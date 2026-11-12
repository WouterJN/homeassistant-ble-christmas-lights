"""Groups of Christmas lights, as in the Lights App.

A group has its own settings. Every change is sent to all the lights in the
group, and lights that connect are given the settings of the group. So the
group does not follow its lights: the lights follow the group.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import time
import logging
from typing import Any, override

from bleak.exc import BleakError

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_MEMBERS, CONF_SETTINGS, DOMAIN
from .device import BLEAK_EXCEPTIONS, ChristmasLights, DeviceState
from .protocol import ALL_MODES, BRIGHTNESS_MAX, Mode, Timer, Timers

_LOGGER = logging.getLogger(__name__)

# The settings of a new group in the app, and after "Restore Default
# Settings": on, full brightness, cycling through all modes, and one timer
# from 18:00 to 23:59 that is not enabled.
DEFAULT_SETTINGS = DeviceState(
    is_on=True,
    brightness=BRIGHTNESS_MAX,
    mode=ALL_MODES,
    timers_enabled=False,
    timers=(Timer(time(18, 0), time(23, 59)), Timer(), Timer()),
)


def is_group(entry: ConfigEntry) -> bool:
    """Return whether a config entry is a group instead of a set of lights."""
    return CONF_MEMBERS in entry.data


def settings_to_dict(settings: DeviceState) -> dict[str, Any]:
    """Return the settings of a group in the form they are stored in."""
    assert settings.mode is not None
    assert settings.timers is not None
    return {
        "is_on": settings.is_on,
        "timers_enabled": settings.timers_enabled,
        "brightness": settings.brightness,
        "mode": int(settings.mode),
        "timers": [
            [timer.start.hour, timer.start.minute, timer.end.hour, timer.end.minute]
            for timer in settings.timers
        ],
    }


def settings_from_dict(data: dict[str, Any] | None) -> DeviceState:
    """Return stored settings of a group, or the default without any."""
    if not data:
        return DEFAULT_SETTINGS
    first, second, third = (
        Timer(time(timer[0], timer[1]), time(timer[2], timer[3]))
        for timer in data["timers"]
    )
    return DeviceState(
        is_on=data["is_on"],
        brightness=data["brightness"],
        mode=Mode(data["mode"]),
        timers_enabled=data["timers_enabled"],
        timers=(first, second, third),
    )


@callback
def async_groups_of(
    hass: HomeAssistant, address: str
) -> list[ChristmasLightsGroupCoordinator]:
    """Return the groups that are set up and have these lights as a member."""
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if is_group(entry)
        and entry.state is ConfigEntryState.LOADED
        and address in entry.data[CONF_MEMBERS]
    ]


class ChristmasLightsGroupCoordinator(DataUpdateCoordinator[DeviceState]):
    """Holds the settings of a group; the entities use it like a set of lights."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the group."""
        super().__init__(hass, _LOGGER, config_entry=entry, name=entry.title)
        self.entry = entry
        self.members: list[str] = entry.data[CONF_MEMBERS]
        self.device = GroupLights(self)
        self.unique_id = entry.entry_id
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            model="Group of lights",
        )
        self.async_set_updated_data(settings_from_dict(entry.data.get(CONF_SETTINGS)))

    @override
    async def _async_update_data(self) -> DeviceState:
        """Return the settings; there is nothing to read them from."""
        return self.data

    @property
    def reachable(self) -> bool:
        """Whether any of the lights in the group can be reached."""
        return any(member.last_update_success for member in self.member_coordinators)

    @property
    def member_coordinators(self) -> list[Any]:
        """Return the lights of the group that are set up."""
        return [
            entry.runtime_data
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.unique_id in self.members
            and not is_group(entry)
            and entry.state is ConfigEntryState.LOADED
        ]

    @callback
    def async_reconnect(self) -> None:
        """Nothing to do: the lights of the group reconnect by themselves."""

    @callback
    def async_member_changed(self) -> None:
        """Update the entities: lights of the group came or went."""
        self.async_update_listeners()

    @callback
    def async_member_connected(self, device: ChristmasLights) -> None:
        """Give lights that connect the settings of the group."""
        self.entry.async_create_background_task(
            self.hass, self._async_sync(device), name=f"{self.name} sync"
        )

    async def async_apply_to(self, device: ChristmasLights) -> None:
        """Give lights all settings of the group at once."""
        settings = self.data
        # A group always has all its settings; see settings_from_dict().
        assert settings.is_on is not None
        assert settings.timers_enabled is not None
        assert settings.brightness is not None
        assert settings.mode is not None
        assert settings.timers is not None
        await device.apply_settings(
            is_on=settings.is_on,
            timers_enabled=settings.timers_enabled,
            brightness=settings.brightness,
            mode=settings.mode,
            timers=settings.timers,
        )

    async def _async_sync(self, device: ChristmasLights) -> None:
        try:
            await self.async_apply_to(device)
        except BLEAK_EXCEPTIONS as err:
            _LOGGER.debug(
                "%s: could not give %s the settings of the group: %r",
                self.name,
                device.address,
                err,
            )

    @callback
    def async_set_settings(self, **changes: Any) -> None:
        """Change the settings of the group and remember them."""
        settings = replace(self.data, **changes)
        self.hass.config_entries.async_update_entry(
            self.entry,
            data={**self.entry.data, CONF_SETTINGS: settings_to_dict(settings)},
        )
        self.async_set_updated_data(settings)


class GroupLights:
    """Stands in for the lights of a group: commands go to all of them."""

    def __init__(self, group: ChristmasLightsGroupCoordinator) -> None:
        """Initialize the lights of the group."""
        self._group = group

    async def turn_on(
        self, brightness: int | None = None, mode: Mode | None = None
    ) -> None:
        """Turn the lights of the group on."""
        timers_enabled = bool(self._group.data.timers_enabled)
        await self._send(
            lambda device: device.turn_on(brightness, mode, timers_enabled)
        )
        changes: dict[str, Any] = {"is_on": True}
        if brightness is not None:
            changes["brightness"] = brightness
        if mode is not None:
            changes["mode"] = mode & ALL_MODES
        self._group.async_set_settings(**changes)

    async def turn_off(self) -> None:
        """Turn the lights of the group off."""
        timers_enabled = bool(self._group.data.timers_enabled)
        await self._send(lambda device: device.turn_off(timers_enabled))
        self._group.async_set_settings(is_on=False)

    async def set_mode(self, mode: Mode) -> None:
        """Select the mode(s) the lights of the group cycle through."""
        await self._send(lambda device: device.set_mode(mode))
        self._group.async_set_settings(mode=mode & ALL_MODES)

    async def set_timers_enabled(self, enabled: bool) -> None:
        """Enable or disable the timers of the lights of the group."""
        is_on = bool(self._group.data.is_on)
        await self._send(lambda device: device.set_timers_enabled(enabled, is_on))
        self._group.async_set_settings(timers_enabled=enabled)

    async def set_timers(self, timers: Timers) -> None:
        """Set the timers of the lights of the group."""
        await self._send(lambda device: device.set_timers(timers))
        self._group.async_set_settings(timers=timers)

    async def restore_defaults(self) -> None:
        """Put the group and its lights back to the default settings."""
        await self._send(lambda device: device.restore_defaults())
        self._group.async_set_settings(
            brightness=DEFAULT_SETTINGS.brightness,
            mode=DEFAULT_SETTINGS.mode,
            timers=DEFAULT_SETTINGS.timers,
        )
        # The lights have new settings that they were not asked for one by one.
        for member in self._group.member_coordinators:
            await member.async_request_refresh()

    async def sync(self) -> None:
        """Give all lights of the group its settings again, in one command each."""
        await self._send(self._group.async_apply_to)

    async def stop(self) -> None:
        """Nothing to close: the connections belong to the lights themselves."""

    async def _send(
        self, command: Callable[[ChristmasLights], Awaitable[None]]
    ) -> None:
        """Send a command to all lights; it fails when it reached none of them."""
        members = self._group.member_coordinators
        if not members:
            raise BleakError("none of the lights of the group is set up")
        results = await asyncio.gather(
            *(command(member.device) for member in members), return_exceptions=True
        )
        failed = 0
        for member, result in zip(members, results, strict=True):
            if isinstance(result, BLEAK_EXCEPTIONS):
                failed += 1
                _LOGGER.debug(
                    "%s: %s did not get it: %r", self._group.name, member.name, result
                )
                # Find out whether these lights can still be reached.
                member.async_reconnect()
            elif isinstance(result, BaseException):
                raise result
        if failed == len(members):
            raise BleakError("none of the lights of the group could be reached")
