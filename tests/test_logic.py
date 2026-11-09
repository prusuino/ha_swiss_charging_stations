"""Pure logic: station parsing, grouping of connectors into sites, opening
hours and site status, the live filters and the published prices."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from custom_components.ich_tanke_strom.const import FILTER_ALL, STATUS_AVAILABLE, STATUS_OCCUPIED
from custom_components.ich_tanke_strom.coordinator import (
    _parse_station,
    apply_filters,
    group_by_location,
    is_closed_all_day_today,
    is_open_now,
    site_status,
    weekly_opening_periods,
)
from custom_components.ich_tanke_strom.prices import _parse_prices

ZURICH = ZoneInfo("Europe/Zurich")
HOURS = [{"on": "Monday", "Period": [{"begin": "07:30", "end": "20:00"}]}, {"on": "Saturday", "Period": {"begin": "08:00", "end": "17:00"}}]


def _feature(evse_id, station_id="CH*OPX*S1", status="Available", lon=7.45, lat=46.95, **props):
    return {
        "id": f"feature-{evse_id}",
        "geometry": {"coordinates": [lon, lat]},
        "properties": {
            "EvseID": evse_id, "ChargingStationId": station_id, "EvseStatus": status, "OperatorID": "CH*OPX",
            "ChargingFacilities": [{"Power": 22}, {"Power": 150}],
            "Plugs": ["CCS Combo 2 Plug (Cable Attached)", "Type 2 Outlet"],
            "ChargingStationNames": {"lang": "de", "value": "Parkhaus Mitte"},  # a bare dict, as the source sometimes serialises it
            "Address": {"Street": "Bahnhofstrasse 1", "City": "Bern", "PostalCode": "3011"},
            "IsOpen24Hours": False, "OpeningTimes": HOURS, **props,
        },
    }


def test_parse_station_normalises_the_odd_shapes():
    station = _parse_station(_feature("CH*OPX*E1"), 46.95, 7.46)
    assert station["id"] == "feature-CH*OPX*E1" and station["evse_id"] == "CH*OPX*E1"
    assert station["power_kw"] == 150
    assert station["station_name"] == "Parkhaus Mitte"
    assert station["plugs"] == ["CCS Combo 2 Plug (Cable Attached)", "Type 2 Outlet"]
    assert 0.7 < station["distance_km"] < 0.8
    assert station["opening_times"] == HOURS
    assert _parse_station({"geometry": {"coordinates": []}, "properties": {}}) is None
    assert _parse_station(_feature("x", EvseStatus=None))["status"] == "Unknown"


def test_group_by_location_merges_same_site_and_address():
    stations = {
        "E1": _parse_station(_feature("E1", "S1")),
        "E2": _parse_station(_feature("E2", "S1", status="Occupied")),
        "E3": _parse_station(_feature("E3", "E3")),  # operator echoes the EvseID: same address, merged by address
        "E4": _parse_station(_feature("E4", "S9", Address={"Street": "Andere Strasse 2", "City": "Thun", "PostalCode": "3600"})),
    }
    sites = group_by_location(stations)
    assert len(sites) == 2
    merged = next(s for s in sites.values() if s["is_synthetic"])
    assert set(merged["connectors"]) == {"E1", "E2", "E3"}
    assert merged["count_total"] == 3 and merged["count_available"] == 2
    assert merged["location_id"].startswith("addr_")
    assert sites["S9"]["count_total"] == 1 and sites["S9"]["is_synthetic"] is False


def test_opening_hours():
    monday_noon = datetime(2026, 11, 9, 12, 0, tzinfo=ZURICH)
    assert is_open_now(HOURS, monday_noon) is True
    assert is_open_now(HOURS, datetime(2026, 11, 9, 21, 0, tzinfo=ZURICH)) is False
    assert is_open_now(HOURS, datetime(2026, 11, 8, 12, 0, tzinfo=ZURICH)) is False  # Sunday is absent: closed
    assert is_open_now([], monday_noon) is None  # no schedule: unknown, not closed
    overnight = [{"on": "Monday", "Period": [{"begin": "22:00", "end": "06:00"}]}]
    assert is_open_now(overnight, datetime(2026, 11, 9, 23, 30, tzinfo=ZURICH)) is True
    assert weekly_opening_periods(HOURS) == {0: ["07:30–20:00"], 5: ["08:00–17:00"]}
    assert is_closed_all_day_today({"opening_times": HOURS}, datetime(2026, 11, 8, 12, 0, tzinfo=ZURICH)) is True
    assert is_closed_all_day_today({"opening_times": HOURS, "open_24h": True}, datetime(2026, 11, 8, 12, 0, tzinfo=ZURICH)) is False


def test_site_status():
    def site(statuses, **extra):
        return {"connectors": {f"E{i}": {"status": s} for i, s in enumerate(statuses)}, "open_24h": True, **extra}

    assert site_status(site(["Available", "Occupied"])) == "available"
    assert site_status(site(["Occupied", "OutOfService"])) == "occupied"
    assert site_status(site(["OutOfService"])) == "out_of_service"
    assert site_status(site(["OutOfService"], open_24h=False)) == "closed"
    assert site_status(site([])) == "unknown"
    # outside the opening hours the site is closed even with Available connectors
    always_closed = [{"on": "Monday", "Period": [{"begin": "00:00", "end": "00:01"}]}]
    assert site_status(site(["Available"], open_24h=False, opening_times=always_closed)) == "closed"


def test_filters():
    stations = {
        "fast": {"power_kw": 150, "plugs": ["CCS Combo 2 Plug (Cable Attached)"], "status": "Available", "operator": "CH*A"},
        "slow": {"power_kw": 11, "plugs": ["Type 2 Outlet"], "status": "Occupied", "operator": "CH*B"},
    }
    assert set(apply_filters(stations, 0, FILTER_ALL, FILTER_ALL, FILTER_ALL)) == {"fast", "slow"}
    assert set(apply_filters(stations, 50, FILTER_ALL, FILTER_ALL, FILTER_ALL)) == {"fast"}
    assert set(apply_filters(stations, 0, "Type 2 Outlet", FILTER_ALL, FILTER_ALL)) == {"slow"}
    assert set(apply_filters(stations, 0, FILTER_ALL, STATUS_AVAILABLE, FILTER_ALL)) == {"fast"}
    assert set(apply_filters(stations, 0, FILTER_ALL, STATUS_OCCUPIED, "CH*B")) == {"slow"}
    assert apply_filters(stations, 0, FILTER_ALL, STATUS_OCCUPIED, "CH*A") == {}


def test_published_prices_from_the_popup_html():
    row = '<tr><td><a href="https://ladepreiskarte.ch/?stationids={ids}" target="_blank">Preis</a></td><td> {price} </td></tr>'
    data = {"features": [
        {"id": "S1", "properties": {"description": row.format(ids="CH*A*E1,CH*A*E2", price="0.55 CHF/kWh")}},
        {"id": "S2", "properties": {"description": row.format(ids="CH*B*E9", price="Bitte beim Anbieter nachfragen")}},
        {"id": "S3", "properties": {}},
    ]}
    by_evse, by_station = _parse_prices(data)
    assert by_station == {"S1": "0.55 CHF/kWh"}  # the fallback text without a digit is not a price
    assert by_evse == {"CH*A*E1": "0.55 CHF/kWh", "CH*A*E2": "0.55 CHF/kWh"}
