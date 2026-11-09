"""Config flow tests: radius overview, favorite by EvseID (single connector
and whole site), favorite picked near a location, duplicate detection, an
unreachable service and the reconfigure flow. The ich-tanke-strom.ch reads
are faked."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ich_tanke_strom.config_flow import (
    CONF_FAVORITE_SCOPE,
    CONF_MODE,
    MODE_FAVORITE,
    MODE_RADIUS,
    SCOPE_SINGLE,
    SCOPE_SITE,
)
from custom_components.ich_tanke_strom.const import (
    CONF_ENTRY_TYPE,
    CONF_FAVORITE_NAME,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS_KM,
    CONF_STATION_ID,
    CONF_STATION_LOCATION_EVSE_IDS,
    CONF_STATION_LOCATION_ID,
    DOMAIN,
    ENTRY_TYPE_FAVORITE,
    ENTRY_TYPE_FAVORITE_LOCATION,
    ENTRY_TYPE_RADIUS,
)
from custom_components.ich_tanke_strom.coordinator import group_by_location

FLOW = "custom_components.ich_tanke_strom.config_flow."


def _station(evse_id, station_id, status="Available", distance=1.0):
    return {
        "id": f"f-{evse_id}", "evse_id": evse_id, "charging_station_id": station_id, "latitude": 46.95, "longitude": 7.45,
        "distance_km": distance, "status": status, "power_kw": 150, "plugs": ["CCS Combo 2 Plug (Cable Attached)"],
        "operator": "CH*OPX", "station_name": "Parkhaus Mitte", "street": "Bahnhofstrasse 1", "city": "Bern", "postal_code": "3011",
        "last_update": None, "open_24h": True, "opening_times": [], "payment_options": [], "renewable_energy": None, "accessibility": None,
    }


STATIONS = {"CH*OPX*E1": _station("CH*OPX*E1", "CH*OPX*S1"), "CH*OPX*E2": _station("CH*OPX*E2", "CH*OPX*S1", "Occupied")}
SITE = group_by_location(STATIONS)["CH*OPX*S1"]


@pytest.fixture
def fake_api():
    with (
        patch(FLOW + "async_fetch_stations", return_value=STATIONS),
        patch(FLOW + "async_fetch_station_by_id", side_effect=lambda hass, evse_id: STATIONS.get(evse_id)),
        patch(FLOW + "async_fetch_station_location", return_value=None),
        patch(FLOW + "async_resolve_site", return_value=SITE),
        patch(FLOW + "get_price_cache") as cache,
    ):
        cache.return_value.async_ensure_fresh = AsyncMock()
        yield


async def _mode(hass, mode):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_MODE: mode})
    assert result["step_id"] == mode
    return result


async def test_radius_overview_setup(hass: HomeAssistant, enable_custom_integrations, fake_api) -> None:
    result = await _mode(hass, MODE_RADIUS)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_LATITUDE: 46.948, CONF_LONGITUDE: 7.447, CONF_RADIUS_KM: 15})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ENTRY_TYPE: ENTRY_TYPE_RADIUS, CONF_LATITUDE: 46.948, CONF_LONGITUDE: 7.447, CONF_RADIUS_KM: 15.0}
    assert result["result"].unique_id == "radius_46.95_7.45_15.0"


async def test_favorite_by_evse_id_offers_the_whole_site(hass: HomeAssistant, enable_custom_integrations, fake_api) -> None:
    result = await _mode(hass, MODE_FAVORITE)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_STATION_ID: " CH*OPX*E1 "})
    assert result["step_id"] == "favorite_scope"
    assert result["description_placeholders"]["count"] == "2"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_FAVORITE_SCOPE: SCOPE_SITE, CONF_FAVORITE_NAME: "Bahnhof"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ENTRY_TYPE] == ENTRY_TYPE_FAVORITE_LOCATION
    assert result["data"][CONF_STATION_LOCATION_ID] == "CH*OPX*S1"
    assert result["data"][CONF_FAVORITE_NAME] == "Bahnhof"
    assert CONF_STATION_LOCATION_EVSE_IDS not in result["data"]  # a real ChargingStationId covers the site
    assert result["result"].unique_id == "favorite_location_CH*OPX*S1"


async def test_favorite_single_connector(hass: HomeAssistant, enable_custom_integrations, fake_api) -> None:
    result = await _mode(hass, MODE_FAVORITE)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_STATION_ID: "CH*OPX*E2"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_FAVORITE_SCOPE: SCOPE_SINGLE})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ENTRY_TYPE: ENTRY_TYPE_FAVORITE, CONF_STATION_ID: "CH*OPX*E2", CONF_FAVORITE_NAME: None}
    assert result["result"].unique_id == "favorite_CH*OPX*E2"


async def test_unknown_evse_id_is_a_field_error(hass: HomeAssistant, enable_custom_integrations, fake_api) -> None:
    result = await _mode(hass, MODE_FAVORITE)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_STATION_ID: "CH*NOPE*E0"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_STATION_ID: "station_not_found"}


async def test_favorite_picked_near_a_location(hass: HomeAssistant, enable_custom_integrations, fake_api) -> None:
    result = await _mode(hass, MODE_FAVORITE)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATION_ID: "", CONF_LATITUDE: 46.95, CONF_LONGITUDE: 7.45, CONF_RADIUS_KM: 5, "min_power_kw": 50}
    )
    assert result["step_id"] == "favorite_pick"
    assert result["description_placeholders"] == {"count": "2"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_STATION_ID: "LOCATION:CH*OPX*S1"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_STATION_LOCATION_ID] == "CH*OPX*S1"
    assert "Parkhaus Mitte" in result["title"]


async def test_no_station_in_radius_and_unreachable_service(hass: HomeAssistant, enable_custom_integrations, fake_api) -> None:
    result = await _mode(hass, MODE_FAVORITE)
    with patch(FLOW + "async_fetch_stations", return_value={}):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_STATION_ID: "", CONF_LATITUDE: 46.95, CONF_LONGITUDE: 7.45, CONF_RADIUS_KM: 5})
    assert result["errors"] == {"base": "no_stations_found"}
    with patch(FLOW + "async_fetch_stations", side_effect=OSError("down")):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_STATION_ID: "", CONF_LATITUDE: 46.95, CONF_LONGITUDE: 7.45, CONF_RADIUS_KM: 5})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_same_favorite_twice_is_refused(hass: HomeAssistant, enable_custom_integrations, fake_api) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="favorite_CH*OPX*E2", title="Fav", data={CONF_ENTRY_TYPE: ENTRY_TYPE_FAVORITE, CONF_STATION_ID: "CH*OPX*E2"}).add_to_hass(hass)
    result = await _mode(hass, MODE_FAVORITE)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_STATION_ID: "CH*OPX*E2"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_FAVORITE_SCOPE: SCOPE_SINGLE})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_radius_keeps_the_filter_options(hass: HomeAssistant, enable_custom_integrations, fake_api) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="radius_46.95_7.45_15.0", title="Radius",
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_RADIUS, CONF_LATITUDE: 46.948, CONF_LONGITUDE: 7.447, CONF_RADIUS_KM: 15.0},
        options={"min_power_kw": 50.0},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.ich_tanke_strom.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id})
        assert result["step_id"] == "radius"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_LATITUDE: 46.948, CONF_LONGITUDE: 7.447, CONF_RADIUS_KM: 25})
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == "radius_46.95_7.45_25.0"
    assert entry.data[CONF_RADIUS_KM] == 25.0
    assert entry.options == {"min_power_kw": 50.0}
