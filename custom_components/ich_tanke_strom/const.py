"""Constants for the ich-tanke-strom.ch integration."""
DOMAIN = "ich_tanke_strom"

WFS_URL = "http://ich-tanke-strom.switzerlandnorth.cloudapp.azure.com:8080/geoserver/ich-tanke-strom/ows"
KM_PER_DEGREE = 111.0
UPDATE_INTERVAL_MINUTES = 5

CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_RADIUS_KM = "radius_km"

DEFAULT_RADIUS_KM = 15

# Which kind of config entry this is. Radius entries (the original/default
# kind) show every station within a live-filterable area. Favorite entries
# pin exactly one specific station, independent of any location/radius —
# added again, once per favorite, same as radius entries are added again for
# a different area. Entries created before this distinction existed have no
# CONF_ENTRY_TYPE key at all; treat that as ENTRY_TYPE_RADIUS (the only kind
# that used to exist), never write a migration-required default for it.
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_RADIUS = "radius"
ENTRY_TYPE_FAVORITE = "favorite"
ENTRY_TYPE_FAVORITE_LOCATION = "favorite_location"

# Favorite-specific config keys.
CONF_STATION_ID = "station_id"  # the station's EvseID — stable, queryable, independent of the opaque WFS feature id used to key the radius view's stations dict
CONF_FAVORITE_NAME = "favorite_name"

# Favorite-location-specific config key. A "location" groups every charge
# point (EVSE) sharing the same ChargingStationId — many real charging sites
# have several connectors that all sit at identical GPS coordinates, so
# favoriting/mapping them individually produces stacked, indistinguishable
# markers. A location favorite is one device with one summary sensor and one
# map marker for the whole site instead.
CONF_STATION_LOCATION_ID = "station_location_id"

# Options (live-adjustable filters, stored in entry.options).
CONF_MIN_POWER_KW = "min_power_kw"
CONF_PLUG_TYPE = "plug_type"
CONF_STATUS = "status"
CONF_OPERATOR = "operator"

DEFAULT_MIN_POWER_KW = 0.0

# Canonical (language-independent) values stored in entry.options. The
# user-facing labels for these are resolved via localization.py at render
# time, so filtering logic never depends on the active HA language.
FILTER_ALL = "__all__"
STATUS_AVAILABLE = "available"
STATUS_OCCUPIED = "occupied"

# Known plug types reported by the API — used as a filter on the favorite
# station search form, chosen upfront before searching (the full list can't
# be known before a fetch). Matches the API's own literal string values
# exactly, since filtering must match raw strings, not a translated label.
# Verified against a near-complete national query (18,881 of ~19,000
# stations) on 2026-07-17 — these 8 are the only values that actually occur.
KNOWN_PLUG_TYPES = [
    "CCS Combo 1 Plug (Cable Attached)",
    "CCS Combo 2 Plug (Cable Attached)",
    "CHAdeMO",
    "Tesla Connector",
    "Type 1 Connector (Cable Attached)",
    "Type 2 Connector (Cable Attached)",
    "Type 2 Outlet",
    "Type J Swiss Standard",
]
