"""Automatic setup of the charging-stations dashboard with a pre-configured map card.

Uses Home Assistant's internal Lovelace storage API (there is no officially
documented integration API for this). Purely additive and idempotent — once
a dashboard has been created, this code never touches it again.
"""
from __future__ import annotations

import logging

from homeassistant.components import frontend
from homeassistant.components.lovelace import dashboard as ll_dashboard
from homeassistant.components.lovelace.const import (
    CONF_ALLOW_SINGLE_WORD,
    CONF_ICON,
    CONF_REQUIRE_ADMIN,
    CONF_SHOW_IN_SIDEBAR,
    CONF_TITLE,
    CONF_URL_PATH,
    DOMAIN as LOVELACE_DOMAIN,
    LOVELACE_DATA,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import voluptuous as vol

from .const import DOMAIN
from .localization import t

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PATH = "ladestationen"
DASHBOARD_ICON = "mdi:ev-station"
FAVORITES_VIEW_PATH = "favoriten"
CARD_ENTRY_ID_KEY = "ich_tanke_strom_entry_id"


async def async_ensure_dashboard(hass: HomeAssistant) -> None:
    """Create the charging-stations dashboard if it doesn't exist yet (idempotent)."""
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None:
        _LOGGER.warning(
            "Lovelace data not available — could not automatically set up the "
            "charging stations dashboard. Please create it manually."
        )
        return

    if DASHBOARD_URL_PATH in lovelace_data.dashboards:
        return  # already exists — don't overwrite (respect any user edits)

    title = t("dashboard_title", hass)

    dashboards_collection = ll_dashboard.DashboardsCollection(hass)
    await dashboards_collection.async_load()

    try:
        item = await dashboards_collection.async_create_item(
            {
                CONF_URL_PATH: DASHBOARD_URL_PATH,
                CONF_TITLE: title,
                CONF_ICON: DASHBOARD_ICON,
                CONF_SHOW_IN_SIDEBAR: True,
                CONF_REQUIRE_ADMIN: False,
                CONF_ALLOW_SINGLE_WORD: True,
            }
        )
    except (HomeAssistantError, vol.Invalid) as err:
        _LOGGER.warning("Could not create the charging stations dashboard: %s", err)
        return

    view_config = {
        "views": [
            {
                "title": title,
                "path": "ladestationen",
                "type": "panel",
                "cards": [
                    {
                        "type": "map",
                        "title": t("map_card_title", hass),
                        "geo_location_sources": [
                            {
                                "source": DOMAIN,
                                "label_mode": "attribute",
                                "attribute": "status",
                            }
                        ],
                        "default_zoom": 11,
                    }
                ],
            }
        ]
    }

    storage = ll_dashboard.LovelaceStorage(hass, item)
    lovelace_data.dashboards[DASHBOARD_URL_PATH] = storage
    await storage.async_save(view_config)

    frontend.async_register_built_in_panel(
        hass,
        LOVELACE_DOMAIN,
        frontend_url_path=DASHBOARD_URL_PATH,
        require_admin=False,
        show_in_sidebar=True,
        sidebar_title=title,
        sidebar_icon=DASHBOARD_ICON,
        config={"mode": "storage"},
        update=False,
    )

    _LOGGER.info("Charging stations dashboard set up automatically at /%s", DASHBOARD_URL_PATH)


async def async_add_location_card(hass: HomeAssistant, entry: ConfigEntry, card: dict) -> None:
    """Add or refresh the pre-filled Entities card for one favorite (single
    connector or whole site) in the dashboard's "Favorites" view (creating
    that view if needed), so its status/power/plug type/operator/ID sensors
    are visible together without manually building a card. Upserts by entry
    ID — re-running this (e.g. every restart) keeps the card's entity list
    in sync as connectors appear/disappear, without duplicating it or
    touching any other card the user has added to the same view."""
    await async_ensure_dashboard(hass)

    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None or DASHBOARD_URL_PATH not in lovelace_data.dashboards:
        return

    storage = lovelace_data.dashboards[DASHBOARD_URL_PATH]
    try:
        config = await storage.async_load(False)
    except HomeAssistantError:
        return

    views = config.setdefault("views", [])
    favorites_view = next((v for v in views if v.get("path") == FAVORITES_VIEW_PATH), None)
    if favorites_view is None:
        favorites_view = {
            "title": t("favorites_view_title", hass),
            "path": FAVORITES_VIEW_PATH,
            "type": "masonry",
            "cards": [],
        }
        views.append(favorites_view)

    cards = favorites_view.setdefault("cards", [])
    card = {**card, CARD_ENTRY_ID_KEY: entry.entry_id}
    existing_index = next((i for i, c in enumerate(cards) if c.get(CARD_ENTRY_ID_KEY) == entry.entry_id), None)
    if existing_index is None:
        cards.append(card)
    else:
        cards[existing_index] = card

    await storage.async_save(config)
    _LOGGER.info("Synced favorites-dashboard card for entry %s", entry.entry_id)


async def async_remove_location_card(hass: HomeAssistant, entry_id: str) -> None:
    """Remove a favorite's card from the Favorites view when its config entry
    is deleted, so the dashboard doesn't accumulate stale cards for favorites
    that no longer exist. Also drops the Favorites view itself if it ends up
    empty. No-op if the dashboard, view, or card is already gone (e.g. the
    user removed it manually)."""
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None or DASHBOARD_URL_PATH not in lovelace_data.dashboards:
        return

    storage = lovelace_data.dashboards[DASHBOARD_URL_PATH]
    try:
        config = await storage.async_load(False)
    except HomeAssistantError:
        return

    views = config.get("views", [])
    favorites_view = next((v for v in views if v.get("path") == FAVORITES_VIEW_PATH), None)
    if favorites_view is None:
        return

    cards = favorites_view.get("cards", [])
    remaining = [c for c in cards if c.get(CARD_ENTRY_ID_KEY) != entry_id]
    if len(remaining) == len(cards):
        return  # nothing matched — already removed or never added

    if remaining:
        favorites_view["cards"] = remaining
    else:
        views.remove(favorites_view)

    await storage.async_save(config)
    _LOGGER.info("Removed favorites-dashboard card for entry %s", entry_id)
