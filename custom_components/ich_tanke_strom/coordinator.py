"""DataUpdateCoordinator for charging stations from ich-tanke-strom.ch (BFE/EnergieSchweiz).

Uses the official WFS/GeoServer REST API, no authentication required. Bbox
query (rough server-side pre-filtering) plus exact Haversine distance
filtering in code — a tested DWITHIN radius query did not return correctly
filtered results on this server.
"""
from __future__ import annotations

import hashlib
import logging
import math
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MIN_POWER_KW,
    CONF_OPERATOR,
    CONF_PLUG_TYPE,
    CONF_RADIUS_KM,
    CONF_STATION_ID,
    CONF_STATION_LOCATION_EVSE_IDS,
    CONF_STATION_LOCATION_ID,
    CONF_STATUS,
    DEFAULT_MIN_POWER_KW,
    DOMAIN,
    FILTER_ALL,
    KM_PER_DEGREE,
    STATUS_AVAILABLE,
    STATUS_OCCUPIED,
    UPDATE_INTERVAL_MINUTES,
    WFS_URL,
)

_LOGGER = logging.getLogger(__name__)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _parse_station(feature: dict, lat: float | None = None, lon: float | None = None) -> dict | None:
    props = feature.get("properties", {})
    geom = feature.get("geometry", {})
    coords = geom.get("coordinates")
    if not coords or len(coords) < 2:
        return None
    station_lon, station_lat = coords[0], coords[1]

    facilities = props.get("ChargingFacilities") or []
    power_kw = max((f.get("Power") or 0) for f in facilities) if facilities else 0

    plugs = list(_as_list(props.get("Plugs")))

    address = props.get("Address", {}) or {}
    evse_id = props.get("EvseID")
    station_id = feature.get("id") or evse_id
    distance_km = (
        round(haversine_km(lat, lon, station_lat, station_lon), 2) if lat is not None and lon is not None else None
    )

    return {
        "id": station_id,
        "evse_id": evse_id,
        "charging_station_id": props.get("ChargingStationId"),
        "latitude": station_lat,
        "longitude": station_lon,
        "distance_km": distance_km,
        "status": props.get("EvseStatus") or "Unknown",
        "power_kw": power_kw,
        "plugs": plugs,
        "operator": props.get("OperatorID"),
        "station_name": (
            (props.get("ChargingStationNames") or [{}])[0].get("value")
            if props.get("ChargingStationNames")
            else None
        ),
        "street": address.get("Street"),
        "city": address.get("City"),
        "postal_code": address.get("PostalCode"),
        "last_update": props.get("lastUpdate"),
        "open_24h": props.get("IsOpen24Hours"),
        "payment_options": props.get("PaymentOptions") or [],
    }


async def async_fetch_stations(hass: HomeAssistant, lat: float, lon: float, radius_km: float) -> dict[str, dict]:
    session = async_get_clientsession(hass)

    lat_delta = radius_km / KM_PER_DEGREE
    lon_delta = radius_km / (KM_PER_DEGREE * max(0.1, math.cos(math.radians(lat))))
    bbox = f"{lon - lon_delta},{lat - lat_delta},{lon + lon_delta},{lat + lat_delta}"

    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": "ich-tanke-strom:evse",
        "outputFormat": "application/json",
        "cql_filter": f"bbox(geometry,{bbox})",
    }
    async with session.get(WFS_URL, params=params, timeout=30) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)

    stations: dict[str, dict] = {}
    for feature in data.get("features", []):
        station = _parse_station(feature, lat, lon)
        if station is None:
            continue
        if station["distance_km"] > radius_km:
            continue
        stations[station["id"]] = station
    return stations


async def async_fetch_station_by_id(hass: HomeAssistant, evse_id: str) -> dict | None:
    """Fetch a single station's current data by its EvseID — the stable,
    human/QR-code-facing identifier printed on the charger itself and shown
    on ich-tanke-strom.ch, as opposed to the opaque WFS feature id used to
    key the radius view's stations dict. Independent of any location/radius,
    used both to validate a favorite during setup and to refresh it
    afterwards. Returns None if no station matches."""
    session = async_get_clientsession(hass)
    escaped_id = evse_id.replace("'", "''")  # CQL string-literal escaping
    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": "ich-tanke-strom:evse",
        "outputFormat": "application/json",
        "cql_filter": f"EvseID='{escaped_id}'",
    }
    async with session.get(WFS_URL, params=params, timeout=30) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    features = data.get("features", [])
    if not features:
        return None
    return _parse_station(features[0])


async def async_fetch_stations_by_evse_ids(hass: HomeAssistant, evse_ids: list[str]) -> dict[str, dict]:
    """Fetch specific connectors by their EvseIDs. Used to refresh a location
    favorite whose group was formed via the address fallback in
    group_by_location, where no single ChargingStationId covers the whole
    site. Returns a dict keyed by evse_id, empty if none of them exist
    anymore."""
    session = async_get_clientsession(hass)
    escaped = ",".join(f"'{e.replace(chr(39), chr(39) * 2)}'" for e in evse_ids)
    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": "ich-tanke-strom:evse",
        "outputFormat": "application/json",
        "cql_filter": f"EvseID IN ({escaped})",
    }
    async with session.get(WFS_URL, params=params, timeout=30) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    stations: dict[str, dict] = {}
    for feature in data.get("features", []):
        station = _parse_station(feature)
        if station is None or not station.get("evse_id"):
            continue
        stations[station["evse_id"]] = station
    return stations


async def async_fetch_station_location(hass: HomeAssistant, charging_station_id: str) -> dict[str, dict]:
    """Fetch every charge point (EVSE) sharing the given ChargingStationId —
    i.e. every connector at one physical site. Returns a dict keyed by
    evse_id, empty if the location no longer has any connectors."""
    session = async_get_clientsession(hass)
    escaped_id = charging_station_id.replace("'", "''")  # CQL string-literal escaping
    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": "ich-tanke-strom:evse",
        "outputFormat": "application/json",
        "cql_filter": f"ChargingStationId='{escaped_id}'",
    }
    async with session.get(WFS_URL, params=params, timeout=30) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    stations: dict[str, dict] = {}
    for feature in data.get("features", []):
        station = _parse_station(feature)
        if station is None or not station.get("evse_id"):
            continue
        stations[station["evse_id"]] = station
    return stations


def _address_key(street: str | None, postal_code: str | None, city: str | None) -> str | None:
    parts = [(street or "").strip().lower(), (postal_code or "").strip().lower(), (city or "").strip().lower()]
    if not any(parts):
        return None
    return "|".join(parts)


def group_by_location(stations: dict[str, dict]) -> dict[str, dict]:
    """Group EVSE-level station dicts by their physical site — many real
    charging sites have several connectors that all sit at identical GPS
    coordinates, so treating each one as its own map marker/entity produces
    stacked, indistinguishable results.

    Primary key is the API's ChargingStationId. That alone isn't enough
    though — verified against live data on 2026-07-17, two distinct cases
    still split one physical site into several groups: (1) several smaller
    operators (Tesla, various e-mobility CH aggregator IDs, MOVE/CCC) report
    no shared site ID at all, each connector echoing its own EvseID back as
    its ChargingStationId; (2) some operators (e.g. Migros/Migrol — reported
    by a user: "Migros | Möhlin 1" / "Migros | Möhlin 2") give each pole at
    one site its own real, distinct ChargingStationId. Both cases are caught
    by a second pass: any of the primary groups that share the same
    operator + street + postal_code + city get merged together. Groups whose
    key is unique already (the common case — GOFAST, Shell evpass, Migrol,
    Lidl, Energie 360°, ... — one real shared ChargingStationId, nothing else
    at that address+operator) pass through untouched, keeping their real
    ChargingStationId as location_id.

    Returns one summary dict per location: connector list plus aggregated
    count/availability, keyed by charging_station_id — or, for a merged
    group, a synthetic `addr_<hash>` id (flagged `is_synthetic: True`, since
    no single ChargingStationId covers the merged group anymore; see
    async_fetch_stations_by_evse_ids)."""
    groups: dict[str, dict] = {}
    for evse_id, s in stations.items():
        location_id = s.get("charging_station_id") or evse_id
        groups.setdefault(location_id, {"location_id": location_id, "connectors": {}})["connectors"][evse_id] = s

    merged: dict[str, dict] = {}
    by_key: dict[tuple[str, str], list[dict]] = {}
    for location_id, g in groups.items():
        first = next(iter(g["connectors"].values()))
        addr_key = _address_key(first.get("street"), first.get("postal_code"), first.get("city"))
        if addr_key is None:
            merged[location_id] = g
            continue
        key = (addr_key, (first.get("operator") or "").strip().lower())
        by_key.setdefault(key, []).append(g)

    for key, group_list in by_key.items():
        if len(group_list) == 1:
            g = group_list[0]
            merged[g["location_id"]] = g
            continue
        synthetic_id = f"addr_{hashlib.md5('|'.join(key).encode()).hexdigest()[:12]}"
        combined_connectors: dict[str, dict] = {}
        for g in group_list:
            combined_connectors.update(g["connectors"])
        merged[synthetic_id] = {"location_id": synthetic_id, "connectors": combined_connectors, "is_synthetic": True}

    for location_id, g in merged.items():
        connectors = g["connectors"]
        first = next(iter(connectors.values()))
        g["station_name"] = first.get("station_name")
        g["street"] = first.get("street")
        g["city"] = first.get("city")
        g["postal_code"] = first.get("postal_code")
        g["operator"] = first.get("operator")
        g["latitude"] = first.get("latitude")
        g["longitude"] = first.get("longitude")
        g["distance_km"] = first.get("distance_km")
        g["open_24h"] = first.get("open_24h")
        g["count_total"] = len(connectors)
        g["count_available"] = sum(1 for c in connectors.values() if c.get("status") == "Available")
        g.setdefault("is_synthetic", False)
    return merged


def icon_for_status(status: str | None) -> str:
    if status == "Available":
        return "mdi:ev-station"
    if status == "Occupied":
        return "mdi:car-electric"
    if status == "OutOfService":
        return "mdi:alert-circle-outline"
    return "mdi:help-circle-outline"


def apply_filters(
    stations: dict[str, dict],
    min_power_kw: float,
    plug_type: str,
    status: str,
    operator: str,
) -> dict[str, dict]:
    """Filter stations using canonical (language-independent) filter values."""
    result = {}
    for station_id, s in stations.items():
        if s["power_kw"] < min_power_kw:
            continue
        if plug_type != FILTER_ALL and plug_type not in s["plugs"]:
            continue
        if status == STATUS_AVAILABLE and s["status"] != "Available":
            continue
        if status == STATUS_OCCUPIED and s["status"] != "Occupied":
            continue
        if operator != FILTER_ALL and s["operator"] != operator:
            continue
        result[station_id] = s
    return result


class IchTankeStromCoordinator(DataUpdateCoordinator[dict]):
    """Fetches charging stations within the configured radius and applies the
    current (live-adjustable) filters from the config entry's options."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self._entry = entry

    async def _async_update_data(self) -> dict:
        data = self._entry.data
        try:
            all_stations = await async_fetch_stations(
                self.hass,
                data[CONF_LATITUDE],
                data[CONF_LONGITUDE],
                data[CONF_RADIUS_KM],
            )
        except Exception as err:
            raise UpdateFailed(f"ich-tanke-strom.ch unreachable: {err}") from err

        options = self._entry.options
        filtered = apply_filters(
            all_stations,
            options.get(CONF_MIN_POWER_KW, DEFAULT_MIN_POWER_KW),
            options.get(CONF_PLUG_TYPE, FILTER_ALL),
            options.get(CONF_STATUS, FILTER_ALL),
            options.get(CONF_OPERATOR, FILTER_ALL),
        )

        plug_types = sorted({p for s in all_stations.values() for p in s["plugs"]})
        operators = sorted({s["operator"] for s in all_stations.values() if s["operator"]})

        return {
            "all_stations": all_stations,
            "filtered_stations": filtered,
            "plug_types": plug_types,
            "operators": operators,
            "count_total": len(all_stations),
            "count_filtered": len(filtered),
            "count_available_filtered": sum(
                1 for s in filtered.values() if s["status"] == "Available"
            ),
        }


class FavoriteStationCoordinator(DataUpdateCoordinator[dict]):
    """Fetches a single pinned favorite station's current status by its
    EvseID — independent of any location or radius."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self._entry = entry

    async def _async_update_data(self) -> dict:
        evse_id = self._entry.data[CONF_STATION_ID]
        try:
            station = await async_fetch_station_by_id(self.hass, evse_id)
        except Exception as err:
            raise UpdateFailed(f"ich-tanke-strom.ch unreachable: {err}") from err
        if station is None:
            raise UpdateFailed(f"Station {evse_id} no longer found in ich-tanke-strom.ch data")
        return station


class FavoriteLocationCoordinator(DataUpdateCoordinator[dict]):
    """Fetches every charge point at a single pinned physical site by its
    ChargingStationId — independent of any search location or radius."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self._entry = entry

    async def _async_update_data(self) -> dict:
        location_id = self._entry.data[CONF_STATION_LOCATION_ID]
        evse_ids = self._entry.data.get(CONF_STATION_LOCATION_EVSE_IDS)
        try:
            if evse_ids:
                # Synthetic (address-merged) location — no single ChargingStationId
                # covers the whole site, so refetch by the pinned EvseIDs instead.
                connectors = await async_fetch_stations_by_evse_ids(self.hass, evse_ids)
            else:
                connectors = await async_fetch_station_location(self.hass, location_id)
        except Exception as err:
            raise UpdateFailed(f"ich-tanke-strom.ch unreachable: {err}") from err
        if not connectors:
            raise UpdateFailed(f"Location {location_id} no longer has any connectors in ich-tanke-strom.ch data")

        groups = group_by_location(connectors)
        if evse_ids:
            return max(groups.values(), key=lambda g: len(g["connectors"]))
        return groups[location_id]
