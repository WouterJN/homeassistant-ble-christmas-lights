"""Config flow for the BLE Christmas Lights integration."""

from __future__ import annotations

import logging
from typing import Any, override

import probatio

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_MEMBERS,
    CONF_STAY_CONNECTED,
    DEFAULT_STAY_CONNECTED,
    DOMAIN,
    MAX_GROUP_MEMBERS,
    SUPPORTED_NAME,
)
from .device import BLEAK_EXCEPTIONS, CharacteristicMissingError, ChristmasLights
from .group import is_group

_LOGGER = logging.getLogger(__name__)


def _is_supported(service_info: BluetoothServiceInfoBleak) -> bool:
    return SUPPORTED_NAME.fullmatch(service_info.name) is not None


def _title(address: str) -> str:
    """Return a readable title; every controller advertises the same name."""
    return f"Christmas lights {address.replace(':', '')[-4:].upper()}"


def _group_errors(user_input: dict[str, Any] | None) -> dict[str, str]:
    """Return what is wrong with the lights chosen for a group."""
    if user_input is None:
        return {}
    members = user_input[CONF_MEMBERS]
    if not members:
        return {CONF_MEMBERS: "no_members"}
    if len(members) > MAX_GROUP_MEMBERS:
        return {CONF_MEMBERS: "too_many_members"}
    return {}


class ChristmasLightsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BLE Christmas Lights."""

    VERSION = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> ChristmasLightsOptionsFlow:
        """Return the options flow."""
        return ChristmasLightsOptionsFlow()

    @classmethod
    @callback
    @override
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        """Only a set of lights has options; a group has no connection."""
        return not is_group(config_entry)

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    @override
    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a controller found by Bluetooth discovery."""
        if not _is_supported(discovery_info):
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": _title(discovery_info.address)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm a discovered controller."""
        assert self._discovery_info is not None
        address = self._discovery_info.address
        errors: dict[str, str] = {}

        if user_input is not None:
            if (error := await self._async_validate(address)) is None:
                return self.async_create_entry(
                    title=_title(address), data={CONF_ADDRESS: address}
                )
            if error == "not_supported":
                return self.async_abort(reason=error)
            errors["base"] = error

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": _title(address)},
            errors=errors,
        )

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add lights, or a group once there are lights to put in it."""
        if not self._lights():
            return await self.async_step_device()
        return self.async_show_menu(step_id="user", menu_options=["device", "group"])

    def _lights(self) -> dict[str, str]:
        """Return the title of every set of lights, by address."""
        return {
            entry.unique_id: entry.title
            for entry in self._async_current_entries(include_ignore=False)
            if not is_group(entry) and entry.unique_id
        }

    async def async_step_group(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Make a group of lights that are set up already."""
        errors = _group_errors(user_input)
        if user_input is not None and not errors:
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={CONF_MEMBERS: user_input[CONF_MEMBERS]},
            )
        return self._async_show_group_form("group", user_input, errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the name of a group and the lights that are in it."""
        entry = self._get_reconfigure_entry()
        if not is_group(entry):
            # Lights have nothing to change here; their options are under
            # "Configure".
            return self.async_abort(reason="reconfigure_lights")

        errors = _group_errors(user_input)
        if user_input is not None and not errors:
            # The settings of the group stay; after the reload its lights,
            # also the new ones, are given them.
            return self.async_update_reload_and_abort(
                entry,
                title=user_input[CONF_NAME],
                data_updates={CONF_MEMBERS: user_input[CONF_MEMBERS]},
            )
        return self._async_show_group_form(
            "reconfigure",
            user_input
            or {
                CONF_NAME: entry.title,
                # Lights that were removed since can no longer be chosen.
                CONF_MEMBERS: [
                    address
                    for address in entry.data[CONF_MEMBERS]
                    if address in self._lights()
                ],
            },
            errors,
        )

    def _async_show_group_form(
        self, step_id: str, values: dict[str, Any] | None, errors: dict[str, str]
    ) -> ConfigFlowResult:
        """Ask for the name of a group and its lights."""
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(CONF_NAME): str,
                        probatio.Required(CONF_MEMBERS): SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    SelectOptionDict(value=address, label=title)
                                    for address, title in self._lights().items()
                                ],
                                multiple=True,
                            )
                        ),
                    }
                ),
                values,
            ),
            errors=errors,
            description_placeholders={"max": str(MAX_GROUP_MEMBERS)},
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick one of the controllers in range."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            if (error := await self._async_validate(address)) is None:
                return self.async_create_entry(
                    title=_title(address), data={CONF_ADDRESS: address}
                )
            if error == "not_supported":
                return self.async_abort(reason=error)
            errors["base"] = error

        current_addresses = self._async_current_ids(include_ignore=False)
        for service_info in async_discovered_service_info(self.hass):
            if service_info.address not in current_addresses and _is_supported(
                service_info
            ):
                self._discovered_devices[service_info.address] = service_info

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="device",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_ADDRESS): probatio.In(
                        {
                            address: f"{_title(address)} ({address})"
                            for address in self._discovered_devices
                        }
                    )
                }
            ),
            errors=errors,
        )

    async def _async_validate(self, address: str) -> str | None:
        """Connect to the controller and read its state; return an error key."""
        ble_device = async_ble_device_from_address(self.hass, address, True)
        if ble_device is None:
            return "cannot_connect"
        device = ChristmasLights(ble_device, now=dt_util.now)
        try:
            await device.update()
        except CharacteristicMissingError:
            return "not_supported"
        except BLEAK_EXCEPTIONS:
            _LOGGER.debug("Could not connect to %s", address, exc_info=True)
            return "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error while connecting to %s", address)
            return "unknown"
        finally:
            await device.stop()
        return None


class ChristmasLightsOptionsFlow(OptionsFlowWithReload):
    """Options for a set of lights; the entry is reloaded when they change."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose whether the connection is kept open."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(
                            CONF_STAY_CONNECTED, default=DEFAULT_STAY_CONNECTED
                        ): bool
                    }
                ),
                self.config_entry.options,
            ),
        )
