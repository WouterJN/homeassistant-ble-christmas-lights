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
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN, SUPPORTED_NAME
from .device import BLEAK_EXCEPTIONS, CharacteristicMissingError, ChristmasLights

_LOGGER = logging.getLogger(__name__)


def _is_supported(service_info: BluetoothServiceInfoBleak) -> bool:
    return SUPPORTED_NAME.fullmatch(service_info.name) is not None


def _title(address: str) -> str:
    """Return a readable title; every controller advertises the same name."""
    return f"Christmas lights {address.replace(':', '')[-4:].upper()}"


class ChristmasLightsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BLE Christmas Lights."""

    VERSION = 1

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
            step_id="user",
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
        device = ChristmasLights(ble_device)
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
