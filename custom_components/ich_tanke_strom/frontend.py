"""Registration of the bundled Lovelace card (ich-tanke-strom-card.js).

Serves the card from this integration's frontend/ directory and registers it
as a Lovelace resource (storage mode) so users never have to add it manually.
The resource URL carries the integration version as a cache-busting query —
on upgrade the existing resource entry is updated in place so browsers fetch
the new file instead of a stale cached one.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILENAME = "swiss-charging-stations-card.js"
CARD_URL_BASE = f"/{DOMAIN}_files/{CARD_FILENAME}"
# Former filename (pre-v1.3.3) — stale resource entries pointing at it are
# removed on startup so browsers don't try to load a URL that no longer exists.
_OLD_CARD_FILENAME = "ich-tanke-strom-card.js"
_REGISTERED_FLAG = f"{DOMAIN}_card_registered"


async def async_register_card(hass: HomeAssistant, version: str) -> None:
    """Serve the bundled card and ensure a matching Lovelace resource exists.

    Idempotent per HA run; safe to call from every config entry setup."""
    if hass.data.get(_REGISTERED_FLAG):
        return
    hass.data[_REGISTERED_FLAG] = True

    card_path = Path(__file__).parent / "frontend" / CARD_FILENAME
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL_BASE, str(card_path), cache_headers=False)]
    )

    url = f"{CARD_URL_BASE}?v={version}"

    lovelace_data = hass.data.get(LOVELACE_DATA)
    resources = getattr(lovelace_data, "resources", None)
    if resources is None:
        _LOGGER.warning(
            "Lovelace resources not available — the bundled card could not be "
            "registered automatically. Add %s as a module resource manually.",
            url,
        )
        return
    if not hasattr(resources, "async_create_item"):
        # YAML-mode Lovelace: resources are user-managed in configuration.yaml.
        _LOGGER.info(
            "Lovelace runs in YAML mode — add %s as a module resource to use "
            "the bundled card.",
            url,
        )
        return

    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True

    existing = None
    stale_ids = []
    for item in resources.async_items():
        item_url = item.get("url", "")
        if CARD_URL_BASE in item_url:
            existing = item
        elif _OLD_CARD_FILENAME in item_url:
            stale_ids.append(item["id"])

    for item_id in stale_ids:
        await resources.async_delete_item(item_id)
        _LOGGER.info("Removed stale card resource entry %s", item_id)

    if existing is not None:
        if existing.get("url") != url:
            await resources.async_update_item(existing["id"], {"url": url})
            _LOGGER.info("Updated bundled card resource to %s", url)
        return

    await resources.async_create_item({"res_type": "module", "url": url})
    _LOGGER.info("Registered bundled card resource %s", url)
