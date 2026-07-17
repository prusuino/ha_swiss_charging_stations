"""Config flow for the ich-tanke-strom.ch charging stations integration.

Two independent kinds of entry, chosen in the first step:
- Radius overview (original behavior): many stations within a live-filterable
  area around a location.
- Favorite: pins exactly one specific station, independent of any location
  or radius. Repeatable — add the integration again for another favorite.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_ENTRY_TYPE,
    CONF_FAVORITE_NAME,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MIN_POWER_KW,
    CONF_PLUG_TYPE,
    CONF_RADIUS_KM,
    CONF_STATION_ID,
    CONF_STATION_LOCATION_EVSE_IDS,
    CONF_STATION_LOCATION_ID,
    DEFAULT_MIN_POWER_KW,
    DEFAULT_RADIUS_KM,
    DOMAIN,
    MAX_RADIUS_KM,
    ENTRY_TYPE_FAVORITE,
    ENTRY_TYPE_FAVORITE_LOCATION,
    ENTRY_TYPE_RADIUS,
    FILTER_ALL,
    KNOWN_PLUG_TYPES,
)
from .coordinator import apply_filters, async_fetch_station_by_id, async_fetch_stations, group_by_location
from .localization import location_display_label, station_display_label, t

CONF_MODE = "mode"
MODE_RADIUS = "radius"
MODE_FAVORITE = "favorite"

_LOCATION_PREFIX = "LOCATION:"  # sentinel prefix for a whole-location pick — never collides with a real EvseID

# Radius input with the upper bound visible/enforced in the UI. Bigger radii
# strain both the source server (20-40+ s per fetch) and Home Assistant
# (thousands of stations); see MAX_RADIUS_KM in const.py.
_RADIUS_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=1, max=MAX_RADIUS_KM, step=0.5, unit_of_measurement="km", mode=NumberSelectorMode.BOX)
)


class IchTankeStromConfigFlow(ConfigFlow, domain=DOMAIN):
    """Setup wizard: pick radius overview or favorite mode, then configure it."""

    VERSION = 1

    def __init__(self) -> None:
        self._favorite_candidates: dict[str, dict] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            if user_input[CONF_MODE] == MODE_FAVORITE:
                return await self.async_step_favorite()
            return await self.async_step_radius()

        schema = vol.Schema(
            {
                vol.Required(CONF_MODE, default=MODE_RADIUS): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=MODE_RADIUS, label=t("mode_radius", self.hass)),
                            SelectOptionDict(value=MODE_FAVORITE, label=t("mode_favorite", self.hass)),
                        ],
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_radius(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Original behavior: a live-filterable overview of every station
        within a location + radius."""
        if user_input is not None:
            lat = user_input[CONF_LATITUDE]
            lon = user_input[CONF_LONGITUDE]
            radius = user_input[CONF_RADIUS_KM]
            await self.async_set_unique_id(f"radius_{round(lat, 2)}_{round(lon, 2)}_{radius}")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=t("device_name", self.hass, radius=radius),
                data={
                    CONF_ENTRY_TYPE: ENTRY_TYPE_RADIUS,
                    CONF_LATITUDE: lat,
                    CONF_LONGITUDE: lon,
                    CONF_RADIUS_KM: radius,
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_LATITUDE, default=self.hass.config.latitude): vol.Coerce(float),
                vol.Required(CONF_LONGITUDE, default=self.hass.config.longitude): vol.Coerce(float),
                vol.Required(CONF_RADIUS_KM, default=DEFAULT_RADIUS_KM): _RADIUS_SELECTOR,
            }
        )
        return self.async_show_form(step_id="radius", data_schema=schema)

    async def async_step_favorite(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Pin one station as a favorite — either by its EvseID directly
        (e.g. from a QR code on the charger), or by searching near a
        location and picking one from a list on the next screen."""
        errors: dict[str, str] = {}

        if user_input is not None:
            station_id = (user_input.get(CONF_STATION_ID) or "").strip()
            if station_id:
                try:
                    station = await async_fetch_station_by_id(self.hass, station_id)
                except Exception:
                    errors["base"] = "cannot_connect"
                else:
                    if station is None:
                        errors[CONF_STATION_ID] = "station_not_found"
                    else:
                        return await self._create_favorite_entry(station, user_input.get(CONF_FAVORITE_NAME))
            else:
                lat = user_input[CONF_LATITUDE]
                lon = user_input[CONF_LONGITUDE]
                radius = user_input[CONF_RADIUS_KM]
                try:
                    stations = await async_fetch_stations(self.hass, lat, lon, radius)
                except Exception:
                    errors["base"] = "cannot_connect"
                else:
                    stations = apply_filters(
                        stations,
                        user_input.get(CONF_MIN_POWER_KW, DEFAULT_MIN_POWER_KW),
                        user_input.get(CONF_PLUG_TYPE, FILTER_ALL),
                        FILTER_ALL,
                        FILTER_ALL,
                    )
                    if not stations:
                        errors["base"] = "no_stations_found"
                    else:
                        self._favorite_candidates = stations
                        return await self.async_step_favorite_pick()

        schema = vol.Schema(
            {
                vol.Optional(CONF_STATION_ID, default=""): str,
                vol.Optional(CONF_LATITUDE, default=self.hass.config.latitude): vol.Coerce(float),
                vol.Optional(CONF_LONGITUDE, default=self.hass.config.longitude): vol.Coerce(float),
                vol.Optional(CONF_RADIUS_KM, default=DEFAULT_RADIUS_KM): _RADIUS_SELECTOR,
                vol.Optional(CONF_MIN_POWER_KW, default=DEFAULT_MIN_POWER_KW): vol.Coerce(float),
                vol.Optional(CONF_PLUG_TYPE, default=FILTER_ALL): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=FILTER_ALL, label=t("option_all", self.hass)),
                            *(SelectOptionDict(value=p, label=p) for p in KNOWN_PLUG_TYPES),
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                        sort=False,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="favorite", data_schema=schema, errors=errors)

    async def async_step_favorite_pick(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Pick either a single charge point or a whole physical site (all
        its connectors together) from the nearby search results gathered in
        the previous step."""
        if user_input is not None:
            selected = user_input[CONF_STATION_ID]
            if selected.startswith(_LOCATION_PREFIX):
                return await self._create_favorite_location_entry(
                    selected[len(_LOCATION_PREFIX) :], user_input.get(CONF_FAVORITE_NAME)
                )
            station = self._favorite_candidates.get(selected)
            if station is None:
                return await self.async_step_favorite()
            return await self._create_favorite_entry(station, user_input.get(CONF_FAVORITE_NAME))

        locations = group_by_location(self._favorite_candidates)
        location_options = [
            SelectOptionDict(
                value=f"{_LOCATION_PREFIX}{location_id}", label=location_display_label(location, self.hass)
            )
            for location_id, location in sorted(locations.items(), key=lambda kv: kv[1]["distance_km"])
        ]
        connector_options = [
            SelectOptionDict(value=station_id, label=station_display_label(station, self.hass))
            for station_id, station in sorted(
                self._favorite_candidates.items(), key=lambda kv: kv[1]["distance_km"]
            )
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_STATION_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=[*location_options, *connector_options], mode=SelectSelectorMode.DROPDOWN, sort=False
                    )
                ),
                vol.Optional(CONF_FAVORITE_NAME, default=""): str,
            }
        )
        return self.async_show_form(
            step_id="favorite_pick",
            data_schema=schema,
            description_placeholders={"count": str(len(connector_options))},
        )

    async def _create_favorite_entry(self, station: dict, custom_name: str | None) -> FlowResult:
        evse_id = station.get("evse_id")
        if not evse_id:
            return self.async_show_form(
                step_id="favorite",
                data_schema=vol.Schema(
                    {
                        vol.Optional(CONF_STATION_ID, default=""): str,
                        vol.Optional(CONF_LATITUDE, default=self.hass.config.latitude): vol.Coerce(float),
                        vol.Optional(CONF_LONGITUDE, default=self.hass.config.longitude): vol.Coerce(float),
                        vol.Optional(CONF_RADIUS_KM, default=DEFAULT_RADIUS_KM): _RADIUS_SELECTOR,
                    }
                ),
                errors={"base": "no_evse_id"},
            )

        await self.async_set_unique_id(f"favorite_{evse_id}")
        self._abort_if_unique_id_configured()

        custom_name = (custom_name or "").strip()
        name = custom_name or station.get("station_name") or station.get("city") or evse_id
        return self.async_create_entry(
            title=t("favorite_device_name", self.hass, name=name),
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_FAVORITE,
                CONF_STATION_ID: evse_id,
                CONF_FAVORITE_NAME: custom_name or None,
            },
        )

    async def _create_favorite_location_entry(self, location_id: str, custom_name: str | None) -> FlowResult:
        location = group_by_location(self._favorite_candidates).get(location_id)

        await self.async_set_unique_id(f"favorite_location_{location_id}")
        self._abort_if_unique_id_configured()

        custom_name = (custom_name or "").strip()
        fallback = (location.get("station_name") or location.get("city") or location_id) if location else location_id
        name = custom_name or fallback
        data = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_FAVORITE_LOCATION,
            CONF_STATION_LOCATION_ID: location_id,
            CONF_FAVORITE_NAME: custom_name or None,
        }
        if location and location.get("is_synthetic"):
            # No real ChargingStationId covers this site (see group_by_location) —
            # pin the member EvseIDs so the coordinator can re-fetch it later.
            data[CONF_STATION_LOCATION_EVSE_IDS] = sorted(location["connectors"])
        return self.async_create_entry(
            title=t("favorite_location_device_name", self.hass, name=name),
            data=data,
        )
