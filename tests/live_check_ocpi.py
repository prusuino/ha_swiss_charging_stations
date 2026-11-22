"""Live check, not part of the test suite (run by hand):

    python tests/live_check_ocpi.py <lat> <lon> <radius_km>

Runs the integration's own radius fetch against the real sources and reports
how many charge points take their status from the new API, how often that
status differs from the previous source, and which charge points were added.
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter

import aiohttp

from custom_components.ich_tanke_strom import coordinator, ocpi, oicp


class FakeHass:
    """Just enough of Home Assistant for the fetch functions."""

    def __init__(self) -> None:
        self.data: dict = {}

    async def async_add_executor_job(self, func, *args):
        return func(*args)


async def main(lat: float, lon: float, radius: float) -> None:
    async with aiohttp.ClientSession() as session:
        for module in (coordinator, ocpi, oicp):
            module.async_get_clientsession = lambda hass: session
        hass = FakeHass()

        # The previous source alone, for comparison.
        ocpi_cache = ocpi.get_ocpi_cache(hass)
        real_fresh = ocpi_cache.async_ensure_fresh

        async def skip(_hass):
            return None

        ocpi_cache.async_ensure_fresh = skip
        before = await coordinator.async_fetch_stations(hass, lat, lon, radius)
        ocpi_cache.async_ensure_fresh = real_fresh

        after = await coordinator.async_fetch_stations(hass, lat, lon, radius)

    print(f"new API: {ocpi_cache.charge_points} charge points, {ocpi_cache.with_live_status} with a live status")
    sources = Counter(s.get("status_source") for s in after.values())
    print(f"previous source alone: {len(before)} charge points | with the new API: {len(after)} | status from: {dict(sources)}")
    both = before.keys() & after.keys()
    from_api = [k for k in both if after[k].get("status_source") == "ocpi"]
    changed = Counter((before[k]["status"], after[k]["status"]) for k in from_api if before[k]["status"] != after[k]["status"])
    print(f"status taken from the API: {len(from_api)} | differs from the previous source: {sum(changed.values())} {dict(changed)}")
    added = [after[k] for k in after.keys() - before.keys()]
    print(f"added charge points: {len(added)}")
    for station in sorted(added, key=lambda s: s["distance_km"])[:12]:
        nearest = min(
            (ocpi._metres(station["latitude"], station["longitude"], o["latitude"], o["longitude"]) for o in before.values()),
            default=0,
        )
        print(f"   {station['evse_id']:28s} {station['distance_km']:5.1f} km  {station['status']:12s} "
              f"{station['power_kw']} kW {station['plugs']} | {station['station_name']} | {station['street']}, "
              f"{station['postal_code']} {station['city']} | nearest known {nearest:.0f} m")
    sites_before = coordinator.group_by_location(dict(before))
    sites_after = coordinator.group_by_location(dict(after))
    print(f"sites: {len(sites_before)} -> {len(sites_after)}")


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])))
