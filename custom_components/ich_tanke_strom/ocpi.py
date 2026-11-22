"""The new API of ich-tanke-strom.ch (OCPI 2.3), used where it has the data.

The Swiss Federal Office of Energy is moving ich-tanke-strom.ch to a platform
that operators feed over OCPI, and connects them one by one: in November 2026
its API knows about a third of the charge points. The integration therefore
keeps reading every charge point from the previous source (GeoServer, or the
OICP files when that fails) and takes from the new API what it has:

- the live status of the charge points it knows. Its status endpoint agreed
  with the previous source for 99.8 % of the charge points in a comparison
  and carried recent changes earlier;
- charge points only the new API lists.

As more operators are connected, more of the data comes from here without a
change to the integration.

Not taken from the API:
- the status inside the location objects: it is a snapshot from when the
  location was last delivered (older than a week for most), not the live one;
- the tariffs: they are net of VAT, mostly carry no tariff type, and for
  charge points with a published ad-hoc price they often show another amount.
  Prices keep coming from the price atlas (prices.py).

Everything here is best effort: a failure never breaks a refresh, the
charge points then simply keep the status of the previous source.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, KM_PER_DEGREE

_LOGGER = logging.getLogger(__name__)

OCPI_BASE_URL = "https://api.emobility-prod.prometheon.bfe.admin.ch/ocpi/"
FETCH_TIMEOUT_SECONDS = 60
# Locations (master data) change a few times a day.
LOCATIONS_MAX_AGE_HOURS = 6
# The status changes are asked for at most this often, however many config
# entries refresh; the API allows 2000 requests per five minutes.
STATUS_MIN_INTERVAL_SECONDS = 60
# A change can be retrieved a little after it happened: ask with an overlap.
STATUS_OVERLAP_SECONDS = 300
# The status endpoint returns at most 5000 records and has no further pages.
STATUS_LIMIT = 5000
# Without a successful status read for this long the kept status values are
# no longer applied; the previous source's status is shown instead.
STATUS_STALE_AFTER_SECONDS = 600
# After a failure the API is left alone for this long.
RETRY_MINUTES = 30
MAX_PAGES = 20
# A charge point only the new API lists is not added when the previous source
# already has one this close: the same hardware is sometimes listed under
# another id, and a site must not count twice.
SAME_SITE_METRES = 40
# Operators also re-brand sites (seen live: the fast chargers of a motorway
# rest stop listed as "MOVE" by the previous source and as "JOYA" by the new
# API, under new ids, 70 m apart). Within this distance a charge point is
# therefore only added when the previous source has none with the same plug.
SAME_PLUG_METRES = 150

_DATA_KEY = f"{DOMAIN}_ocpi_cache"

# OCPI status -> the status vocabulary of the previous source (OICP).
STATUS_MAP = {
    "AVAILABLE": "Available",
    "CHARGING": "Occupied",
    "BLOCKED": "Occupied",
    "RESERVED": "Reserved",
    "INOPERATIVE": "OutOfService",
    "OUTOFORDER": "OutOfService",
    "UNKNOWN": "Unknown",
    "PLANNED": "Unknown",
}
# OCPI connector standard (and format) -> the plug names of the previous source.
_PLUGS = {
    ("IEC_62196_T2", "SOCKET"): "Type 2 Outlet",
    ("IEC_62196_T2", "CABLE"): "Type 2 Connector (Cable Attached)",
    ("IEC_62196_T2_COMBO", None): "CCS Combo 2 Plug (Cable Attached)",
    ("IEC_62196_T1", None): "Type 1 Connector (Cable Attached)",
    ("IEC_62196_T1_COMBO", None): "CCS Combo 1 Plug (Cable Attached)",
    ("CHADEMO", None): "CHAdeMO",
    ("TESLA_S", None): "Tesla Connector",
    ("TESLA_R", None): "Tesla Connector",
    ("DOMESTIC_J", None): "Type J Swiss Standard",
}
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def normalize_evse_id(evse_id: str | None) -> str:
    """EVSE ids are written with and without separators (CH*ABC*E1 / CHABCE1)."""
    return (evse_id or "").replace("*", "").replace("-", "").replace(" ", "").upper()


def _plug(connector: dict) -> str | None:
    standard, fmt = connector.get("standard"), connector.get("format")
    return _PLUGS.get((standard, fmt)) or _PLUGS.get((standard, None)) or standard


def _opening_times(location: dict) -> tuple[bool | None, list[dict]]:
    """(open around the clock, opening times in the shape of the previous source)."""
    opening = location.get("opening_times") or {}
    if opening.get("twentyfourseven") is True:
        return True, []
    by_day: dict[str, list[dict]] = {}
    for hours in opening.get("regular_hours") or []:
        try:
            day = _WEEKDAYS[int(hours["weekday"]) - 1]
            by_day.setdefault(day, []).append({"begin": hours["period_begin"], "end": hours["period_end"]})
        except (KeyError, ValueError, IndexError, TypeError):
            continue
    times = [{"on": day, "Period": periods} for day, periods in by_day.items()]
    return (False if times or "twentyfourseven" in opening else None), times


def _metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dy = (lat2 - lat1) * KM_PER_DEGREE * 1000
    dx = (lon2 - lon1) * KM_PER_DEGREE * 1000 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


def location_site_id(location: dict) -> str:
    """Site id of a location only the new API lists."""
    return f"ocpi:{location.get('country_code')}:{location.get('party_id')}:{location.get('id')}"


def station_from_ocpi(location: dict, evse: dict, status: str | None, last_update: str | None) -> dict | None:
    """One EVSE of the new API as the station dict the integration works with."""
    evse_id = evse.get("evse_id")
    coordinates = location.get("coordinates") or {}
    try:
        lat, lon = float(coordinates["latitude"]), float(coordinates["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not evse_id:
        return None
    connectors = [c for c in evse.get("connectors") or [] if isinstance(c, dict)]
    watts = max((c.get("max_electric_power") or 0 for c in connectors), default=0)
    power = watts / 1000
    plugs = []
    for connector in connectors:
        plug = _plug(connector)
        if plug and plug not in plugs:
            plugs.append(plug)
    open_24h, opening_times = _opening_times(location)
    return {
        "id": evse_id,
        "evse_id": evse_id,
        "charging_station_id": location_site_id(location),
        "latitude": lat,
        "longitude": lon,
        "distance_km": None,
        "status": status or "Unknown",
        "power_kw": int(power) if float(power).is_integer() else round(power, 1),
        "plugs": plugs,
        "operator": f"{location.get('country_code')}*{location.get('party_id')}",
        "station_name": location.get("name") or (location.get("operator") or {}).get("name"),
        "street": location.get("address"),
        "city": location.get("city"),
        "postal_code": str(location["postal_code"]) if location.get("postal_code") is not None else None,
        "last_update": last_update,
        "open_24h": open_24h,
        "opening_times": opening_times,
        "payment_options": [],
        "renewable_energy": None,
        "accessibility": None,
    }


class OcpiCache:
    """Locations and live status of the new API, shared by every config entry."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # status key (country, party, location id, evse uid) -> (location, evse)
        self._evses: dict[tuple, tuple[dict, dict]] = {}
        # normalised EVSE id -> status key
        self._by_evse_id: dict[str, tuple] = {}
        # status key -> (status in the previous source's vocabulary, last_updated)
        self._status: dict[tuple, tuple[str, str | None]] = {}
        self._locations_at = 0.0
        self._status_at = 0.0
        self._status_synced: datetime | None = None
        self._failed_at = 0.0
        self._warned = False

    # -- state ---------------------------------------------------------------
    @property
    def charge_points(self) -> int:
        return len(self._evses)

    @property
    def with_live_status(self) -> int:
        return len(self._status)

    def usable(self) -> bool:
        """True while the kept status values are recent enough to apply."""
        return bool(self._evses) and time.monotonic() - self._status_at < STATUS_STALE_AFTER_SECONDS

    # -- reading -------------------------------------------------------------
    async def _get(self, hass: HomeAssistant, url: str) -> tuple[Any, str | None]:
        session = async_get_clientsession(hass)
        async with session.get(url, headers={"Accept": "application/json"}, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            resp.raise_for_status()
            body = await resp.json(content_type=None)
            link = resp.headers.get("Link") or ""
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise ValueError("unexpected answer of the OCPI API")
        next_url = link.split(";")[0].strip("<> ") if 'rel="next"' in link else None
        return body["data"], next_url

    async def _load_locations(self, hass: HomeAssistant) -> None:
        evses: dict[tuple, tuple[dict, dict]] = {}
        by_id: dict[str, tuple] = {}
        url: str | None = OCPI_BASE_URL + "locations?limit=1000"
        for _ in range(MAX_PAGES):
            if not url:
                break
            data, url = await self._get(hass, url)
            for location in data:
                for evse in location.get("evses") or []:
                    if evse.get("status") == "REMOVED" or not evse.get("uid"):
                        continue
                    key = (location.get("country_code"), location.get("party_id"), location.get("id"), evse["uid"])
                    evses[key] = (location, evse)
                    # The printed id of the hardware is sometimes delivered as
                    # physical_reference while evse_id carries another one.
                    for candidate in (evse.get("evse_id"), evse.get("physical_reference")):
                        if candidate and "*" in candidate:
                            by_id.setdefault(normalize_evse_id(candidate), key)
        self._evses, self._by_evse_id = evses, by_id
        self._status = {key: value for key, value in self._status.items() if key in evses}

    def _take_status(self, records: list[dict]) -> None:
        for record in records:
            key = (record.get("country_code"), record.get("party_id"), record.get("location_id"), record.get("evse_uid"))
            if key not in self._evses:
                continue
            raw = record.get("status")
            if raw == "REMOVED":
                self._status.pop(key, None)
                continue
            previous = self._status.get(key)
            updated = record.get("last_updated")
            if previous and previous[1] and updated and updated < previous[1]:
                continue  # an older record must not replace a newer one
            self._status[key] = (STATUS_MAP.get(raw, "Unknown"), updated)

    async def _load_status(self, hass: HomeAssistant, since: datetime) -> None:
        stamp = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        data, _ = await self._get(hass, f"{OCPI_BASE_URL}status?date_from={stamp}&limit={STATUS_LIMIT}")
        self._take_status(data)

    async def async_ensure_fresh(self, hass: HomeAssistant) -> None:
        """Bring locations and status up to date. Never raises."""
        async with self._lock:
            now = time.monotonic()
            if self._failed_at and now - self._failed_at < RETRY_MINUTES * 60:
                return
            try:
                started = datetime.now(UTC)
                if not self._evses or now - self._locations_at >= LOCATIONS_MAX_AGE_HOURS * 3600:
                    await self._load_locations(hass)
                    self._locations_at = now
                if self._status_synced is None:
                    # First read: the endpoint returns at most 5000 records per
                    # request, so the long window is completed by the last day.
                    await self._load_status(hass, datetime(2020, 1, 1, tzinfo=UTC))
                    await self._load_status(hass, started - timedelta(hours=24))
                elif now - self._status_at >= STATUS_MIN_INTERVAL_SECONDS:
                    await self._load_status(hass, self._status_synced - timedelta(seconds=STATUS_OVERLAP_SECONDS))
                else:
                    return
                self._status_synced = started
                self._status_at = now
                if self._failed_at:
                    _LOGGER.info("The ich-tanke-strom.ch API answers again")
                self._failed_at = 0.0
                self._warned = False
            except Exception as err:  # noqa: BLE001 - an optional source must never break a refresh
                self._failed_at = now
                if not self._warned:
                    self._warned = True
                    _LOGGER.warning(
                        "The new ich-tanke-strom.ch API could not be read (%s); the status of the previous "
                        "source is shown, the API is tried again in %d minutes",
                        type(err).__name__,
                        RETRY_MINUTES,
                    )

    # -- use -------------------------------------------------------------------
    def status_of(self, evse_id: str | None) -> tuple[str, str | None] | None:
        """Live status of a charge point the API knows, else None."""
        key = self._by_evse_id.get(normalize_evse_id(evse_id))
        return self._status.get(key) if key is not None else None

    def knows(self, evse_id: str | None) -> bool:
        return normalize_evse_id(evse_id) in self._by_evse_id

    def apply_status(self, stations: dict[str, dict]) -> int:
        """Replace the status of the charge points the API has a live status
        for. Returns how many were taken from the API."""
        if not self.usable():
            return 0
        taken = 0
        for station in stations.values():
            live = self.status_of(station.get("evse_id"))
            if live is None:
                station.setdefault("status_source", "previous")
                continue
            station["status"] = live[0]
            if live[1]:
                station["last_update"] = live[1]
            station["status_source"] = "ocpi"
            taken += 1
        return taken

    def _station(self, key: tuple) -> dict | None:
        location, evse = self._evses[key]
        live = self._status.get(key)
        station = station_from_ocpi(location, evse, live[0] if live else None, live[1] if live else None)
        if station is not None:
            station["status_source"] = "ocpi"
        return station

    def station_by_evse_id(self, evse_id: str) -> dict | None:
        key = self._by_evse_id.get(normalize_evse_id(evse_id))
        return self._station(key) if key is not None and self.usable() else None

    def stations_of_site(self, site_id: str) -> dict[str, dict]:
        """Every charge point of a site only the new API lists (ocpi:CC:PARTY:ID)."""
        out: dict[str, dict] = {}
        if not self.usable() or not site_id.startswith("ocpi:"):
            return out
        for key, (location, _evse) in self._evses.items():
            if location_site_id(location) == site_id:
                station = self._station(key)
                if station is not None:
                    out[station["evse_id"]] = station
        return out

    def additional_stations(self, lat: float, lon: float, radius_km: float, existing: dict[str, dict]) -> dict[str, dict]:
        """Charge points within the radius that the previous source does not
        have: unknown id, and no charge point of the previous source at the
        same spot."""
        out: dict[str, dict] = {}
        if not self.usable():
            return out
        have_ids = {normalize_evse_id(s.get("evse_id")) for s in existing.values()}
        spots = [(s["latitude"], s["longitude"], set(s.get("plugs") or [])) for s in existing.values()
                 if s.get("latitude") is not None and s.get("longitude") is not None]
        lat_delta = radius_km / KM_PER_DEGREE
        lon_delta = radius_km / (KM_PER_DEGREE * max(0.1, math.cos(math.radians(lat))))
        for key, (location, evse) in self._evses.items():
            ids = {normalize_evse_id(i) for i in (evse.get("evse_id"), evse.get("physical_reference")) if i}
            if not evse.get("evse_id") or ids & have_ids:
                continue
            coordinates = location.get("coordinates") or {}
            try:
                s_lat, s_lon = float(coordinates["latitude"]), float(coordinates["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if abs(s_lat - lat) > lat_delta or abs(s_lon - lon) > lon_delta:
                continue
            station = self._station(key)
            if station is None:
                continue
            plugs = set(station["plugs"])
            duplicate = False
            for o_lat, o_lon, o_plugs in spots:
                metres = _metres(s_lat, s_lon, o_lat, o_lon)
                if metres <= SAME_SITE_METRES or (metres <= SAME_PLUG_METRES and plugs & o_plugs):
                    duplicate = True
                    break
            if not duplicate:
                out[station["id"]] = station
        return out


def get_ocpi_cache(hass: HomeAssistant) -> OcpiCache:
    if _DATA_KEY not in hass.data:
        hass.data[_DATA_KEY] = OcpiCache()
    return hass.data[_DATA_KEY]
