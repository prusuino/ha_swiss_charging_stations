"""Geo-location entities for charging stations.

Radius entries only: shows the stations that currently match the live
filters, on the Home Assistant map. Custom lightweight management instead of
an external feed-manager package — on every coordinator update (new data OR
a filter change), the currently filtered station list is diffed against the
entities already created (new ones added, stale ones removed).

Favorite entries (single connector or whole site) intentionally get no map
marker — the radius view already covers map display, and a favorite is
tracked via its sensors instead.
"""
from __future__ import annotations

import logging

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IchTankeStromCoordinator, icon_for_status
from .localization import localized_status, t

_LOGGER = logging.getLogger(__name__)
SOURCE = "ich_tanke_strom"
ATTRIBUTION = "Data: ich-tanke-strom.ch (BFE / EnergieSchweiz / swisstopo)"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: IchTankeStromCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_entities: dict[str, ChargingStationEvent] = {}

    @callback
    def _sync_entities() -> None:
        stations = (coordinator.data or {}).get("filtered_stations", {})

        new_entities = [
            known_entities.setdefault(station_id, ChargingStationEvent(hass, station))
            for station_id, station in stations.items()
            if station_id not in known_entities
        ]
        if new_entities:
            async_add_entities(new_entities)

        for station_id in [e for e in known_entities if e not in stations]:
            entity = known_entities.pop(station_id)
            hass.async_create_task(entity.async_remove(force_remove=True))

    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))
    _sync_entities()


class ChargingStationEvent(GeolocationEvent):
    """A single charging station. Static data snapshot — the lifecycle
    (appearing/disappearing) is managed by the sync function above."""

    _attr_should_poll = False
    _attr_source = SOURCE
    _attr_attribution = ATTRIBUTION
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_has_entity_name = False
    # Hidden from Home Assistant's auto-generated default dashboard map (which
    # otherwise draws every geo_location entity in the system) — still shown
    # on this integration's own dedicated map card, which references entities
    # by source/state directly rather than through the visible-by-default list.
    # visible_default only applies to entities registered for the first time;
    # async_added_to_hass below covers entities that already existed in the
    # registry from before this was introduced.
    _attr_entity_registry_visible_default = False

    def __init__(self, hass: HomeAssistant, station: dict) -> None:
        self._station = station
        self._hass_ref = hass
        self._attr_unique_id = f"{DOMAIN}_{station['id']}"
        name = station.get("station_name") or station.get("city") or t("station_fallback_name", hass)
        power = station.get("power_kw")
        power_text = f"{power:g}kW " if power else ""
        prefix = t("station_entity_prefix", hass)
        self._attr_name = f"{prefix} {power_text}– {name}"
        self._attr_latitude = station["latitude"]
        self._attr_longitude = station["longitude"]
        self._attr_distance = station["distance_km"]
        self._attr_icon = icon_for_status(station.get("status"))
        self._operator_fallback = t("unknown_operator", hass)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Retroactively hide entities that were already in the registry
        # before entity_registry_visible_default existed here — that
        # attribute only takes effect for entities registered for the first
        # time. Only touches entries with no hidden_by set yet, so it never
        # overrides a user's own explicit show/hide choice.
        registry = er.async_get(self.hass)
        entry = registry.async_get(self.entity_id)
        if entry is not None and entry.hidden_by is None:
            registry.async_update_entity(self.entity_id, hidden_by=er.RegistryEntryHider.INTEGRATION)

    @property
    def extra_state_attributes(self):
        s = self._station
        return {
            # Localized for display (used as the map marker label via
            # label_mode: attribute). Filtering uses the raw API value
            # internally in the coordinator, unaffected by this.
            "status": localized_status(s.get("status"), self._hass_ref),
            "power_kw": s.get("power_kw"),
            "plug_types": s.get("plugs"),
            "operator": s.get("operator") or self._operator_fallback,
            "street": s.get("street"),
            "city": s.get("city"),
            "postal_code": s.get("postal_code"),
            "open_24h": s.get("open_24h"),
            "payment_options": s.get("payment_options"),
            "last_update": s.get("last_update"),
        }
