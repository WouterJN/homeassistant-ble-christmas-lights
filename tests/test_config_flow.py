"""Tests for the config flow."""

from unittest.mock import patch

from bleak.exc import BleakError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import ADDRESS, make_service_info
from custom_components.ble_christmas_lights.const import DOMAIN
from custom_components.ble_christmas_lights.device import CharacteristicMissingError

FLOW = "custom_components.ble_christmas_lights.config_flow"


@pytest.fixture(autouse=True)
def ble_device():
    with patch(
        f"{FLOW}.async_ble_device_from_address", return_value=make_service_info().device
    ):
        yield


@pytest.fixture(autouse=True)
def no_setup():
    with patch(
        "custom_components.ble_christmas_lights.async_setup_entry", return_value=True
    ):
        yield


def patch_update(side_effect=None):
    return patch(f"{FLOW}.ChristmasLights.update", side_effect=side_effect)


async def test_bluetooth_discovery(hass: HomeAssistant, controller):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=make_service_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Christmas lights EEFF"
    assert result["data"] == {CONF_ADDRESS: ADDRESS}
    assert result["result"].unique_id == ADDRESS


@pytest.mark.parametrize("name", ["LED-3-05-00000000", "LED-4-02-00000000"])
async def test_bluetooth_discovery_supported_names(hass: HomeAssistant, name):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=make_service_info(name=name)
    )
    assert result["step_id"] == "bluetooth_confirm"


@pytest.mark.parametrize(
    "name", ["LED-4-02-12345678", "LED-strip", "LED-44-02-00000000"]
)
async def test_bluetooth_discovery_unsupported_name(hass: HomeAssistant, name):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_BLUETOOTH},
        data=make_service_info(name=name),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_bluetooth_discovery_cannot_connect_then_retry(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=make_service_info()
    )
    with patch_update(BleakError("out of range")):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    with patch_update():
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_step(hass: HomeAssistant):
    other = make_service_info(address="11:22:33:44:55:66", name="Some speaker")
    with patch(
        f"{FLOW}.async_discovered_service_info",
        return_value=[make_service_info(), other],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch_update():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ADDRESS: ADDRESS}


async def test_user_step_not_supported(hass: HomeAssistant):
    with patch(
        f"{FLOW}.async_discovered_service_info", return_value=[make_service_info()]
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    with patch_update(CharacteristicMissingError("nope")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_user_step_nothing_found(hass: HomeAssistant):
    with patch(f"{FLOW}.async_discovered_service_info", return_value=[]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_already_configured(hass: HomeAssistant):
    MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=make_service_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
