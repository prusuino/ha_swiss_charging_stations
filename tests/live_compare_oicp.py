"""Live comparison, not part of the test suite (run by hand):

    python tests/live_compare_oicp.py <lat> <lon> <radius_km>

Reads the same area once from the WFS and once from the OICP files on
data.geo.admin.ch, both through the integration's own parsing, and compares
charge points, status and the fields the entities use. Three downloads.
"""
from __future__ import annotations

import gzip
import json
import math
import sys
import urllib.parse
import urllib.request
from collections import Counter

from custom_components.ich_tanke_strom import coordinator
from custom_components.ich_tanke_strom.const import KM_PER_DEGREE, WFS_URL
from custom_components.ich_tanke_strom.oicp import OICP_DATA_URL, OICP_STATUS_URL, OicpCache, parse_data, parse_status


def fetch_json(url: str) -> dict:
    # data.geo.admin.ch sends these files gzip-encoded whatever the request
    # asks for; aiohttp in Home Assistant unpacks that by itself, urllib not.
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "ha-ich-tanke-strom-test"})
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return json.loads(body)


def main(lat: float, lon: float, radius: float) -> None:
    lat_d = radius / KM_PER_DEGREE
    lon_d = radius / (KM_PER_DEGREE * max(0.1, math.cos(math.radians(lat))))
    params = {"service": "WFS", "version": "1.0.0", "request": "GetFeature", "typeName": "ich-tanke-strom:evse",
              "outputFormat": "application/json",
              "cql_filter": f"bbox(geometry,{lon - lon_d},{lat - lat_d},{lon + lon_d},{lat + lat_d})"}
    wfs_features = fetch_json(WFS_URL + "?" + urllib.parse.urlencode(params))["features"]

    cache = OicpCache()
    cache._records = parse_data(fetch_json(OICP_DATA_URL))
    cache._statuses = parse_status(fetch_json(OICP_STATUS_URL))
    file_features = cache.features_in_area(lat, lon, radius)

    def stations(features):
        out = {}
        for f in features:
            s = coordinator._parse_station(f, lat, lon)
            if s and s["distance_km"] <= radius:
                out[s["evse_id"]] = s
        return out

    a, b = stations(wfs_features), stations(file_features)
    print(f"WFS: {len(a)} charge points | files: {len(b)} | in both: {len(a.keys() & b.keys())} "
          f"| only WFS: {len(a.keys() - b.keys())} | only files: {len(b.keys() - a.keys())}")
    same_status = sum(1 for k in a.keys() & b.keys() if a[k]["status"] == b[k]["status"])
    print(f"same status: {same_status} of {len(a.keys() & b.keys())}")
    diffs = Counter()
    for k in a.keys() & b.keys():
        for field in ("charging_station_id", "power_kw", "plugs", "operator", "station_name", "street", "city",
                      "postal_code", "open_24h", "opening_times", "renewable_energy", "accessibility"):
            if a[k].get(field) != b[k].get(field):
                diffs[field] += 1
    print("fields that differ (count of charge points):", dict(diffs) or "none")
    sites_a = coordinator.group_by_location(a)
    sites_b = coordinator.group_by_location(b)
    print(f"sites WFS: {len(sites_a)} | sites files: {len(sites_b)} | same site ids: {len(sites_a.keys() & sites_b.keys())}")


if __name__ == "__main__":
    main(float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]))
