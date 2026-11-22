"""Fallback to the OICP files on data.geo.admin.ch when the WFS fails."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.ich_tanke_strom import coordinator, oicp
from custom_components.ich_tanke_strom.const import WFS_URL
from custom_components.ich_tanke_strom.oicp import (
    OICP_DATA_URL,
    OICP_STATUS_URL,
    get_oicp_cache,
    parse_data,
    parse_status,
    to_feature,
)

# Two sites in Bern (one with two charge points sharing a ChargingStationId)
# and one in Zürich, in the shape of the data.geo.admin.ch files.
DATA = {
    "EVSEData": [
        {
            "OperatorID": "CH*AAA",
            "OperatorName": "Example A",
            "EVSEDataRecord": [
                {
                    "EvseID": "CH*AAA*E1*1",
                    "ChargingStationId": "SITE-1",
                    "GeoCoordinates": {"Google": "46.948 7.447"},
                    "ChargingFacilities": [{"Voltage": 400, "Amperage": 32, "power": 22.0, "powertype": "AC_3_PHASE"}],
                    "Plugs": ["Type 2 Outlet"],
                    "ChargingStationNames": [{"lang": "en", "value": "Example Bern"}],
                    "Address": {"Street": "Bahnhofplatz", "PostalCode": "3011", "City": "Bern"},
                    "IsOpen24Hours": True,
                    "OpeningTimes": None,
                    "RenewableEnergy": True,
                    "Accessibility": "Free publicly accessible",
                },
                {
                    "EvseID": "CH*AAA*E1*2",
                    "ChargingStationId": "SITE-1",
                    "GeoCoordinates": {"Google": "46.948 7.447"},
                    # Text, as some operators deliver it; must compare as a number.
                    "ChargingFacilities": [{"power": "50.0", "powertype": "DC"}, {"power": "150.0", "powertype": "DC"}],
                    "Plugs": "CCS Combo 2 Plug (Cable Attached)",
                    "Address": {"Street": "Bahnhofplatz", "PostalCode": "3011", "City": "Bern"},
                },
            ],
        },
        {
            "OperatorID": "CH*BBB",
            "OperatorName": "Example B",
            "EVSEDataRecord": [
                {
                    "EvseID": "CH*BBB*E9*1",
                    "ChargingStationId": "SITE-9",
                    "GeoCoordinates": {"DecimalDegree": {"Latitude": "47.377", "Longitude": "8.541"}},
                    "ChargingFacilities": [{"Power": 11, "PowerType": "AC_3_PHASE"}],
                    "Plugs": ["Type 2 Outlet"],
                    # Postal code as a number, as some operators deliver it.
                    "Address": {"Street": "Bahnhofstrasse", "PostalCode": 8001, "City": "Zürich"},
                },
                {"EvseID": "CH*BBB*BROKEN", "GeoCoordinates": {"Google": "not a coordinate"}},
            ],
        },
    ]
}
STATUS = {
    "EVSEStatuses": [
        {"OperatorID": "CH*AAA", "EVSEStatusRecord": [
            {"EvseID": "CH*AAA*E1*1", "EVSEStatus": "Available"},
            {"EvseID": "CH*AAA*E1*2", "EVSEStatus": "Occupied"},
        ]},
        {"OperatorID": "CH*BBB", "EVSEStatusRecord": [{"EvseID": "CH*BBB*E9*1", "EVSEStatus": "OutOfService"}]},
    ]
}
BERN = (46.948, 7.447)


def test_records_become_the_features_the_wfs_delivers() -> None:
    records = parse_data(DATA)
    statuses = parse_status(STATUS)
    assert set(records) == {"CH*AAA*E1*1", "CH*AAA*E1*2", "CH*BBB*E9*1", "CH*BBB*BROKEN"}
    assert statuses["CH*AAA*E1*2"] == "Occupied"

    record, operator = records["CH*AAA*E1*1"]
    feature = to_feature(record, operator, statuses.get("CH*AAA*E1*1"))
    assert feature["id"] == "CH*AAA*E1*1"
    assert feature["geometry"]["coordinates"] == [7.447, 46.948]  # lon, lat as in GeoJSON
    station = coordinator._parse_station(feature, *BERN)
    assert station["evse_id"] == "CH*AAA*E1*1"
    assert station["charging_station_id"] == "SITE-1"
    assert station["status"] == "Available"
    assert station["power_kw"] == 22.0  # lower-case "power" of the files is read
    assert station["plugs"] == ["Type 2 Outlet"]
    assert station["operator"] == "CH*AAA"  # operator id from the operator level
    assert station["station_name"] == "Example Bern"
    assert station["city"] == "Bern"
    assert station["distance_km"] == 0.0

    record, operator = records["CH*AAA*E1*2"]
    fast = coordinator._parse_station(to_feature(record, operator, None), *BERN)
    assert fast["power_kw"] == 150  # "150.0" as a number, the larger of the two
    assert fast["plugs"] == ["CCS Combo 2 Plug (Cable Attached)"]

    # The other coordinate notation, a numeric postal code, and a record
    # that cannot be placed.
    record, operator = records["CH*BBB*E9*1"]
    zurich = coordinator._parse_station(to_feature(record, operator, None))
    assert zurich["postal_code"] == "8001"
    assert coordinator.group_by_location({zurich["evse_id"]: zurich})  # no crash on the address key
    assert to_feature(record, operator, None)["geometry"]["coordinates"] == [8.541, 47.377]
    assert to_feature(record, operator, None)["properties"]["EvseStatus"] == "Unknown"
    assert to_feature(*records["CH*BBB*BROKEN"], None) is None


def _mock_files(aioclient_mock) -> None:
    aioclient_mock.get(OICP_DATA_URL, text=json.dumps(DATA))
    aioclient_mock.get(OICP_STATUS_URL, text=json.dumps(STATUS))


async def test_a_failing_wfs_is_replaced_by_the_files(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(WFS_URL, status=502)
    _mock_files(aioclient_mock)

    stations = await coordinator.async_fetch_stations(hass, *BERN, 5)
    assert set(stations) == {"CH*AAA*E1*1", "CH*AAA*E1*2"}  # Zürich is outside 5 km
    assert stations["CH*AAA*E1*2"]["status"] == "Occupied"
    assert get_oicp_cache(hass).in_use is True

    station = await coordinator.async_fetch_station_by_id(hass, "CH*BBB*E9*1")
    assert station["status"] == "OutOfService"
    assert await coordinator.async_fetch_station_by_id(hass, "CH*XXX*NONE") is None
    site = await coordinator.async_fetch_station_location(hass, "SITE-1")
    assert set(site) == {"CH*AAA*E1*1", "CH*AAA*E1*2"}
    both = await coordinator.async_fetch_stations_by_evse_ids(hass, ["CH*AAA*E1*2", "CH*BBB*E9*1", "CH*XXX*NONE"])
    assert set(both) == {"CH*AAA*E1*2", "CH*BBB*E9*1"}

    # After the failure the WFS is left alone; the data file was read once.
    wfs_calls = [c for c in aioclient_mock.mock_calls if str(c[1]).startswith(WFS_URL)]
    data_calls = [c for c in aioclient_mock.mock_calls if str(c[1]) == OICP_DATA_URL]
    assert len(wfs_calls) == 1
    assert len(data_calls) == 1


async def test_the_wfs_is_tried_again_after_its_rest_and_used_when_it_answers(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.get(WFS_URL, exc=TimeoutError())
    _mock_files(aioclient_mock)
    await coordinator.async_fetch_stations(hass, *BERN, 5)
    cache = get_oicp_cache(hass)
    assert cache.in_use is True

    aioclient_mock.clear_requests()
    wfs_answer = {"type": "FeatureCollection", "features": [to_feature(*parse_data(DATA)["CH*AAA*E1*1"], "Available")]}
    aioclient_mock.get(WFS_URL, text=json.dumps(wfs_answer))
    with patch.object(oicp, "WFS_RETRY_MINUTES", 0):
        stations = await coordinator.async_fetch_stations(hass, *BERN, 5)
    assert set(stations) == {"CH*AAA*E1*1"}  # from the WFS, not the files
    assert cache.in_use is False


async def test_a_wfs_answer_without_features_counts_as_a_failure(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(WFS_URL, text="<html>maintenance</html>")
    _mock_files(aioclient_mock)
    stations = await coordinator.async_fetch_stations(hass, *BERN, 5)
    assert set(stations) == {"CH*AAA*E1*1", "CH*AAA*E1*2"}


async def test_when_both_sources_fail_the_refresh_fails(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(WFS_URL, status=503)
    aioclient_mock.get(OICP_DATA_URL, status=503)
    aioclient_mock.get(OICP_STATUS_URL, status=503)
    with pytest.raises(Exception):
        await coordinator.async_fetch_stations(hass, *BERN, 5)


async def test_a_stale_status_file_is_kept_when_it_cannot_be_read(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(WFS_URL, status=502)
    _mock_files(aioclient_mock)
    await coordinator.async_fetch_stations(hass, *BERN, 5)

    aioclient_mock.clear_requests()
    aioclient_mock.get(OICP_STATUS_URL, status=500)
    with patch.object(oicp, "STATUS_MAX_AGE_SECONDS", 0):
        stations = await coordinator.async_fetch_stations(hass, *BERN, 5)
    assert stations["CH*AAA*E1*2"]["status"] == "Occupied"  # the last good status
