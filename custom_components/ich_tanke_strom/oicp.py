"""Fallback source: the OICP files on data.geo.admin.ch.

The stations are normally read from the GeoServer (WFS) of ich-tanke-strom.ch,
which filters by area or id on the server. The Swiss Federal Office of Energy
is moving that platform to a new API in late 2026; the old server is no longer
mentioned in its documentation, and the new API does not cover every operator
yet. The same data is published in full on data.geo.admin.ch as two OICP
files, over HTTPS:

- EVSE data (about 1 MB gzip, 27 MB JSON): every charge point with address,
  coordinates, plugs, power and opening times. Read at most every
  DATA_MAX_AGE_HOURS.
- EVSE status (about 170 KB gzip): the current status of every charge point,
  regenerated about every minute. Read at most every STATUS_MAX_AGE_SECONDS.

When the WFS fails, the fetch functions in coordinator.py answer from these
files instead and filter locally, and the WFS is left alone for
WFS_RETRY_MINUTES before it is tried again. One cache is shared by every
config entry. The records are turned into the same feature shape the WFS
delivers, so the rest of the integration does not notice the difference;
only `PaymentOptions` and `lastUpdate` are missing in the files.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, KM_PER_DEGREE

_LOGGER = logging.getLogger(__name__)

OICP_DATA_URL = (
    "https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/data/oicp/"
    "ch.bfe.ladestellen-elektromobilitaet.json"
)
OICP_STATUS_URL = (
    "https://data.geo.admin.ch/ch.bfe.ladestellen-elektromobilitaet/status/oicp/"
    "ch.bfe.ladestellen-elektromobilitaet.json"
)
DATA_MAX_AGE_HOURS = 6
STATUS_MAX_AGE_SECONDS = 120
FETCH_TIMEOUT_SECONDS = 90
# After a WFS failure the next refreshes go straight to the files for this
# long: a server that hangs would otherwise cost every refresh its timeout.
WFS_RETRY_MINUTES = 30

_DATA_KEY = f"{DOMAIN}_oicp_cache"


def _coordinates(record: dict) -> tuple[float, float] | None:
    """(lat, lon) of a record. The files write them as Google "lat lon";
    the other OICP notations are read as well."""
    geo = record.get("GeoCoordinates") or {}
    google = geo.get("Google")
    if isinstance(google, str):
        parts = google.replace(",", " ").split()
        if len(parts) == 2:
            try:
                return float(parts[0]), float(parts[1])
            except ValueError:
                return None
    decimal = geo.get("DecimalDegree")
    if isinstance(decimal, dict):
        try:
            return float(decimal["Latitude"]), float(decimal["Longitude"])
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _number(value: Any) -> Any:
    """The files carry the power partly as text ("200.0"); the WFS as a
    number (200). Text would compare as text ("50.0" > "200.0")."""
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _facility(item: Any) -> Any:
    """The files write `power`/`powertype` where the WFS has `Power`/`PowerType`."""
    if not isinstance(item, dict):
        return item
    out = dict(item)
    if "Power" not in out and "power" in out:
        out["Power"] = out.pop("power")
    if "PowerType" not in out and "powertype" in out:
        out["PowerType"] = out.pop("powertype")
    if "Power" in out:
        out["Power"] = _number(out["Power"])
    return out


def _address(value: Any) -> Any:
    """The files carry some postal codes as numbers (8001); the WFS and the
    grouping by address expect text throughout."""
    if not isinstance(value, dict):
        return value
    return {key: (str(item) if isinstance(item, (int, float)) and not isinstance(item, bool) else item)
            for key, item in value.items()}


def to_feature(record: dict, operator_id: str | None, status: str | None) -> dict | None:
    """One OICP EVSE data record as the feature the WFS would return."""
    coords = _coordinates(record)
    evse_id = record.get("EvseID")
    if coords is None or not evse_id:
        return None
    lat, lon = coords
    facilities = record.get("ChargingFacilities")
    if isinstance(facilities, list):
        facilities = [_facility(f) for f in facilities]
    else:
        facilities = _facility(facilities)
    properties = {
        "EvseID": evse_id,
        "ChargingStationId": record.get("ChargingStationId"),
        "EvseStatus": status or "Unknown",
        "ChargingFacilities": facilities,
        "Plugs": record.get("Plugs"),
        "Address": _address(record.get("Address")),
        "ChargingStationNames": record.get("ChargingStationNames"),
        "OperatorID": operator_id,
        "IsOpen24Hours": record.get("IsOpen24Hours"),
        "OpeningTimes": record.get("OpeningTimes"),
        "RenewableEnergy": record.get("RenewableEnergy"),
        "Accessibility": record.get("Accessibility"),
    }
    return {"id": evse_id, "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": properties}


def parse_data(payload: dict) -> dict[str, tuple[dict, str | None]]:
    """EvseID -> (data record, operator id) from the EVSE data file."""
    records: dict[str, tuple[dict, str | None]] = {}
    for operator in payload.get("EVSEData") or []:
        operator_id = operator.get("OperatorID")
        for record in operator.get("EVSEDataRecord") or []:
            evse_id = record.get("EvseID")
            if evse_id:
                records[evse_id] = (record, operator_id)
    return records


def parse_status(payload: dict) -> dict[str, str]:
    """EvseID -> status from the EVSE status file."""
    statuses: dict[str, str] = {}
    for operator in payload.get("EVSEStatuses") or []:
        for record in operator.get("EVSEStatusRecord") or []:
            evse_id = record.get("EvseID")
            if evse_id:
                statuses[evse_id] = record.get("EVSEStatus") or "Unknown"
    return statuses


class OicpCache:
    """The two files and the state of the WFS, shared by every config entry."""

    def __init__(self) -> None:
        self._records: dict[str, tuple[dict, str | None]] = {}
        self._statuses: dict[str, str] = {}
        self._data_at = 0.0
        self._status_at = 0.0
        self._lock = asyncio.Lock()
        self._wfs_failed_at = 0.0
        self.in_use = False

    # -- WFS state ---------------------------------------------------------
    def wfs_usable(self) -> bool:
        """False for WFS_RETRY_MINUTES after a WFS failure."""
        return time.monotonic() - self._wfs_failed_at >= WFS_RETRY_MINUTES * 60 or not self._wfs_failed_at

    def wfs_failed(self, err: BaseException) -> None:
        first = not self.in_use
        self._wfs_failed_at = time.monotonic()
        self.in_use = True
        if first:
            _LOGGER.warning(
                "ich-tanke-strom.ch GeoServer not reachable (%s); reading the station data from the "
                "OICP files on data.geo.admin.ch instead, the GeoServer is tried again in %d minutes",
                type(err).__name__,
                WFS_RETRY_MINUTES,
            )

    def wfs_ok(self) -> None:
        if self.in_use:
            _LOGGER.info("ich-tanke-strom.ch GeoServer answers again; using it as the source again")
        self._wfs_failed_at = 0.0
        self.in_use = False

    # -- files -------------------------------------------------------------
    async def _fetch(self, hass: HomeAssistant, url: str) -> dict:
        session = async_get_clientsession(hass)
        async with session.get(url, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            resp.raise_for_status()
            body = await resp.read()
        return await hass.async_add_executor_job(json.loads, body)

    async def async_ensure_fresh(self, hass: HomeAssistant) -> None:
        """Load the files that are older than their maximum age. A failed
        read keeps what was loaded before; with nothing loaded it raises."""
        async with self._lock:
            now = time.monotonic()
            if not self._records or now - self._data_at >= DATA_MAX_AGE_HOURS * 3600:
                try:
                    payload = await self._fetch(hass, OICP_DATA_URL)
                    self._records = await hass.async_add_executor_job(parse_data, payload)
                    self._data_at = now
                except Exception:
                    if not self._records:
                        raise
                    _LOGGER.debug("OICP data file not read, keeping the previous one", exc_info=True)
            if not self._statuses or now - self._status_at >= STATUS_MAX_AGE_SECONDS:
                try:
                    payload = await self._fetch(hass, OICP_STATUS_URL)
                    self._statuses = await hass.async_add_executor_job(parse_status, payload)
                    self._status_at = now
                except Exception:
                    if not self._statuses:
                        raise
                    _LOGGER.debug("OICP status file not read, keeping the previous one", exc_info=True)

    # -- queries -----------------------------------------------------------
    def _feature(self, evse_id: str) -> dict | None:
        found = self._records.get(evse_id)
        if found is None:
            return None
        record, operator_id = found
        return to_feature(record, operator_id, self._statuses.get(evse_id))

    def features_in_area(self, lat: float, lon: float, radius_km: float) -> list[dict]:
        """Every charge point in the box around the point; the caller
        filters by the exact distance, as it does for the WFS answer."""
        lat_delta = radius_km / KM_PER_DEGREE
        lon_delta = radius_km / (KM_PER_DEGREE * max(0.1, math.cos(math.radians(lat))))
        out = []
        for evse_id, (record, _operator) in self._records.items():
            coords = _coordinates(record)
            if coords is None:
                continue
            if abs(coords[0] - lat) <= lat_delta and abs(coords[1] - lon) <= lon_delta:
                feature = self._feature(evse_id)
                if feature is not None:
                    out.append(feature)
        return out

    def features_by_evse_ids(self, evse_ids: list[str]) -> list[dict]:
        return [f for f in (self._feature(e) for e in evse_ids) if f is not None]

    def features_by_station_id(self, charging_station_id: str) -> list[dict]:
        out = []
        for evse_id, (record, _operator) in self._records.items():
            if record.get("ChargingStationId") == charging_station_id:
                feature = self._feature(evse_id)
                if feature is not None:
                    out.append(feature)
        return out


def get_oicp_cache(hass: HomeAssistant) -> OicpCache:
    if _DATA_KEY not in hass.data:
        hass.data[_DATA_KEY] = OicpCache()
    return hass.data[_DATA_KEY]
