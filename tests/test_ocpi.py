"""The new API of ich-tanke-strom.ch (OCPI): live status for the charge
points it knows, charge points only it lists, and nothing when it fails."""
from __future__ import annotations

import json
import re
from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.ich_tanke_strom import coordinator, ocpi
from custom_components.ich_tanke_strom.const import WFS_URL
from custom_components.ich_tanke_strom.ocpi import (
    OCPI_BASE_URL,
    get_ocpi_cache,
    normalize_evse_id,
    station_from_ocpi,
)

BERN = (46.948, 7.447)
LOCATIONS_URL = OCPI_BASE_URL + "locations?limit=1000"
STATUS_URL = re.compile(re.escape(OCPI_BASE_URL) + r"status\?.*")


def wfs_feature(evse_id: str, status: str, lat: float = 46.948, lon: float = 7.447, site: str = "SITE-1") -> dict:
    return {
        "id": evse_id,
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "EvseID": evse_id,
            "ChargingStationId": site,
            "EvseStatus": status,
            "ChargingFacilities": [{"Power": 22}],
            "Plugs": ["Type 2 Outlet"],
            "Address": {"Street": "Bahnhofplatz", "PostalCode": "3011", "City": "Bern"},
            "OperatorID": "CH*AAA",
            "lastUpdate": "2026-01-01T00:00:00Z",
        },
    }


def location(loc_id: str, lat: str, lon: str, evses: list[dict], party: str = "AAA") -> dict:
    return {
        "country_code": "CH",
        "party_id": party,
        "id": loc_id,
        "publish": True,
        "name": f"Site {loc_id}",
        "address": "Neue Strasse 1",
        "city": "Bern",
        "postal_code": 3012,
        "coordinates": {"latitude": lat, "longitude": lon},
        "evses": evses,
        "opening_times": {"twentyfourseven": True},
        "operator": {"name": "Example A"},
    }


def evse(uid: str, evse_id: str | None, status: str = "AVAILABLE", **extra) -> dict:
    return {
        "uid": uid,
        "evse_id": evse_id,
        "status": status,  # the snapshot inside the location, not the live status
        "connectors": [
            {"id": "1", "standard": "IEC_62196_T2_COMBO", "format": "CABLE", "power_type": "DC", "max_electric_power": 150000}
        ],
        **extra,
    }


LOCATIONS = [
    # Known to the previous source as CH*AAA*E1*1 and CH*AAA*E1*2.
    location("L1", "46.948", "7.447", [evse("u1", "CH*AAA*E1*1"), evse("u2", "CHAAAE1*2")]),
    # Same hardware as CH*AAA*E1*3 of the previous source, listed under another id.
    location("L2", "46.948", "7.447", [evse("u3", "FR*073*X", physical_reference="CH*AAA*E1*3")]),
    # Only the new API lists these two; the second has been removed.
    location("L3", "46.960", "7.460", [evse("u4", "CH*NEW*E7*1"), evse("u5", "CH*NEW*E7*2", status="REMOVED")]),
    # At the spot of a charge point of the previous source, under an unknown id.
    location("L4", "46.94801", "7.44701", [evse("u6", "CH*ZZZ*E9")]),
    # Far away.
    location("L5", "47.377", "8.541", [evse("u7", "CH*NEW*E8*1")]),
    # A re-branded site: 80 m from the fast charger CH*OLD*E6 of the previous
    # source, same plug, new ids.
    location("L6", "46.9557", "7.4500", [evse("u8", "CH*NEW*E6*1")]),
]


def status_record(loc_id: str, uid: str, status: str, updated: str = "2026-11-22T14:00:00Z", party: str = "AAA") -> dict:
    return {"country_code": "CH", "party_id": party, "location_id": loc_id, "evse_uid": uid, "status": status,
            "last_updated": updated}


STATUS = [
    status_record("L1", "u1", "CHARGING"),
    status_record("L1", "u2", "OUTOFORDER"),
    status_record("L3", "u4", "CHARGING"),
    status_record("L9", "unknown", "AVAILABLE"),  # not in the locations: ignored
]


def ocpi_answer(data: list) -> str:
    return json.dumps({"data": data, "status_code": 1000, "timestamp": "2026-11-22T14:00:05Z"})


def mock_sources(aioclient_mock, wfs: list[dict], locations=LOCATIONS, status=STATUS) -> None:
    aioclient_mock.get(WFS_URL, text=json.dumps({"features": wfs}))
    aioclient_mock.get(LOCATIONS_URL, text=ocpi_answer(locations))
    aioclient_mock.get(STATUS_URL, text=ocpi_answer(status))


WFS = [
    wfs_feature("CH*AAA*E1*1", "Available"),
    wfs_feature("CH*AAA*E1*2", "Available"),
    wfs_feature("CH*AAA*E1*3", "Occupied"),
    wfs_feature("CH*OLD*E5", "Occupied", lat=46.950, lon=7.450, site="SITE-5"),
    {**wfs_feature("CH*OLD*E6", "Available", lat=46.955, lon=7.450, site="SITE-6"),
     "properties": {**wfs_feature("CH*OLD*E6", "Available", lat=46.955, lon=7.450, site="SITE-6")["properties"],
                    "Plugs": ["CCS Combo 2 Plug (Cable Attached)"], "ChargingFacilities": [{"Power": 150}]}},
]


def test_ids_are_compared_without_separators() -> None:
    assert normalize_evse_id("CH*AAA*E1*1") == normalize_evse_id("chaaae1-1") == "CHAAAE11"
    assert normalize_evse_id(None) == ""


def test_an_evse_of_the_new_api_becomes_a_station() -> None:
    loc = location("L3", "46.960", "7.460", [evse("u4", "CH*NEW*E7*1")])
    loc["opening_times"] = {"twentyfourseven": False, "regular_hours": [
        {"weekday": 1, "period_begin": "08:00", "period_end": "20:00"},
        {"weekday": 7, "period_begin": "10:00", "period_end": "16:00"},
    ]}
    station = station_from_ocpi(loc, loc["evses"][0], "Occupied", "2026-11-22T14:00:00Z")
    assert station["evse_id"] == station["id"] == "CH*NEW*E7*1"
    assert station["charging_station_id"] == "ocpi:CH:AAA:L3"
    assert (station["latitude"], station["longitude"]) == (46.960, 7.460)
    assert station["status"] == "Occupied"
    assert station["power_kw"] == 150
    assert station["plugs"] == ["CCS Combo 2 Plug (Cable Attached)"]
    assert station["operator"] == "CH*AAA"
    assert station["station_name"] == "Site L3"
    assert (station["street"], station["city"], station["postal_code"]) == ("Neue Strasse 1", "Bern", "3012")
    assert station["open_24h"] is False
    assert station["opening_times"] == [
        {"on": "Monday", "Period": [{"begin": "08:00", "end": "20:00"}]},
        {"on": "Sunday", "Period": [{"begin": "10:00", "end": "16:00"}]},
    ]
    # The shape the rest of the integration works with.
    assert coordinator.group_by_location({station["evse_id"]: station})
    assert coordinator.is_open_now(station["opening_times"]) in (True, False)

    assert station_from_ocpi(loc, evse("u9", None), None, None) is None  # no id to show
    loc["coordinates"] = {}
    assert station_from_ocpi(loc, loc["evses"][0], None, None) is None  # nowhere to put it


async def test_live_status_comes_from_the_new_api_and_new_charge_points_are_added(
    hass: HomeAssistant, aioclient_mock
) -> None:
    mock_sources(aioclient_mock, WFS)
    stations = await coordinator.async_fetch_stations(hass, *BERN, 5)

    # Known to both: master data of the previous source, live status of the API.
    assert stations["CH*AAA*E1*1"]["status"] == "Occupied"
    assert stations["CH*AAA*E1*1"]["status_source"] == "ocpi"
    assert stations["CH*AAA*E1*1"]["charging_station_id"] == "SITE-1"  # ids and sites stay as they were
    assert stations["CH*AAA*E1*1"]["last_update"] == "2026-11-22T14:00:00Z"
    assert stations["CH*AAA*E1*2"]["status"] == "OutOfService"  # matched although written differently
    # Listed by the API but without a live status there: the previous status stays.
    assert stations["CH*AAA*E1*3"]["status"] == "Occupied"
    assert stations["CH*AAA*E1*3"]["status_source"] == "previous"
    # Not known to the API at all.
    assert stations["CH*OLD*E5"]["status"] == "Occupied"
    assert stations["CH*OLD*E5"]["status_source"] == "previous"

    # Only the API lists it: added, with its live status and its distance.
    new = stations["CH*NEW*E7*1"]
    assert new["status"] == "Occupied" and new["status_source"] == "ocpi"
    assert 1.0 < new["distance_km"] < 2.5
    # Not added: removed, same hardware under another id, same spot, out of
    # range, and the re-branded site with the same plug close by.
    assert set(stations) == {"CH*AAA*E1*1", "CH*AAA*E1*2", "CH*AAA*E1*3", "CH*OLD*E5", "CH*OLD*E6", "CH*NEW*E7*1"}

    cache = get_ocpi_cache(hass)
    assert cache.charge_points == 7  # the removed one is not kept
    assert cache.with_live_status == 3


async def test_favourites_use_the_new_api_too(hass: HomeAssistant, aioclient_mock) -> None:
    mock_sources(aioclient_mock, [WFS[0]])
    station = await coordinator.async_fetch_station_by_id(hass, "CH*AAA*E1*1")
    assert station["status"] == "Occupied"

    aioclient_mock.clear_requests()
    mock_sources(aioclient_mock, [])  # the previous source does not know these
    only_new = await coordinator.async_fetch_station_by_id(hass, "CH*NEW*E7*1")
    assert only_new["charging_station_id"] == "ocpi:CH:AAA:L3" and only_new["status"] == "Occupied"
    assert await coordinator.async_fetch_station_by_id(hass, "CH*NOPE*E0") is None
    site = await coordinator.async_fetch_station_location(hass, "ocpi:CH:AAA:L3")
    assert set(site) == {"CH*NEW*E7*1"}
    several = await coordinator.async_fetch_stations_by_evse_ids(hass, ["CH*NEW*E7*1", "CH*NOPE*E0"])
    assert set(several) == {"CH*NEW*E7*1"}


async def test_status_changes_are_asked_for_at_most_once_a_minute_and_newer_wins(
    hass: HomeAssistant, aioclient_mock
) -> None:
    mock_sources(aioclient_mock, WFS)
    await coordinator.async_fetch_stations(hass, *BERN, 5)
    first = len(aioclient_mock.mock_calls)
    await coordinator.async_fetch_stations(hass, *BERN, 5)
    # Only the previous source was asked again: the API rests for a minute.
    assert len(aioclient_mock.mock_calls) == first + 1

    aioclient_mock.clear_requests()
    mock_sources(aioclient_mock, WFS, status=[
        status_record("L1", "u1", "AVAILABLE", "2026-11-22T14:05:00Z"),
        status_record("L1", "u2", "AVAILABLE", "2026-11-22T13:00:00Z"),  # older than what is known
    ])
    with patch.object(ocpi, "STATUS_MIN_INTERVAL_SECONDS", 0):
        stations = await coordinator.async_fetch_stations(hass, *BERN, 5)
    assert stations["CH*AAA*E1*1"]["status"] == "Available"
    assert stations["CH*AAA*E1*2"]["status"] == "OutOfService"
    # One request for the changes, none for the locations.
    asked = [str(call[1]) for call in aioclient_mock.mock_calls]
    assert sum("status?" in url for url in asked) == 1 and not any("locations" in url for url in asked)


async def test_without_the_new_api_everything_stays_as_before(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(WFS_URL, text=json.dumps({"features": WFS}))
    aioclient_mock.get(LOCATIONS_URL, status=403)  # e.g. the rate limit of the API
    stations = await coordinator.async_fetch_stations(hass, *BERN, 5)
    assert set(stations) == {"CH*AAA*E1*1", "CH*AAA*E1*2", "CH*AAA*E1*3", "CH*OLD*E5", "CH*OLD*E6"}
    assert stations["CH*AAA*E1*1"]["status"] == "Available"

    # The API is left alone after the failure.
    calls = len(aioclient_mock.mock_calls)
    await coordinator.async_fetch_stations(hass, *BERN, 5)
    assert len(aioclient_mock.mock_calls) == calls + 1


async def test_a_status_that_is_no_longer_refreshed_is_not_applied(hass: HomeAssistant, aioclient_mock) -> None:
    mock_sources(aioclient_mock, WFS)
    stations = await coordinator.async_fetch_stations(hass, *BERN, 5)
    assert stations["CH*AAA*E1*1"]["status"] == "Occupied"

    aioclient_mock.clear_requests()
    aioclient_mock.get(WFS_URL, text=json.dumps({"features": WFS}))
    aioclient_mock.get(STATUS_URL, status=500)
    with patch.object(ocpi, "STATUS_MIN_INTERVAL_SECONDS", 0), patch.object(ocpi, "STATUS_STALE_AFTER_SECONDS", 0):
        stations = await coordinator.async_fetch_stations(hass, *BERN, 5)
    # The live status could not be renewed: the previous source's status shows.
    assert stations["CH*AAA*E1*1"]["status"] == "Available"
    assert "CH*NEW*E7*1" not in stations
