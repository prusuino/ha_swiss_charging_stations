# Changelog

## 1.2.0 — 2026-07-17

- New: when picking a favorite, you can now also favorite an entire physical charging site instead of a single connector — useful for sites with several charge points at the same address (e.g. multiple CCS chargers at one Migros). Pick a location from the setup dropdown (marked with 📍 and the number of charge points) instead of an individual connector, and one device is created with a summary sensor (available/total count) plus a `connectors` attribute listing every charge point's status, power, and plug type. Each connector also gets its own status/power/plug-type/operator/ID sensors, mirroring what a single favorite station provides.
- New: favoriting a station or a whole site automatically adds a pre-filled card to the "Favorites" view of the auto-generated dashboard, showing status, power, plug type, operator, and EvseID (grouped per connector for a site) — no manual dashboard setup needed. Removing a favorite removes its card again (and the "Favorites" view itself once empty); the card also stays in sync with connector changes on every restart.
- Fixed: radius-view station markers no longer show up on Home Assistant's own auto-generated default dashboard map (which draws every `geo_location` entity in the system) — they remain fully visible on this integration's own dedicated map card. Applies retroactively to entities that already existed before this fix, not just newly created ones.
- Changed: favorite entries (single connector or whole site) no longer create a `geo_location` map marker — favorites are tracked via their sensors, and the radius view already covers map display, so a separate marker was just visual clutter.

## 1.1.1 — 2026-07-17

- Fixed: the plug-type filter on the favorite-station search form was missing two real connector types (CCS Combo 1, Type J Swiss Standard) — verified against a near-complete national query (18,881 of ~19,000 stations), all 8 plug types that actually occur are now selectable.

## 1.1.0 — 2026-07-17

- New setup mode: pin a single favorite charging station, independent of any location or radius — repeatable, add the integration again for another favorite. Either enter the station's EvseID directly (e.g. from a QR code on the charger), or search near a location (with optional minimum-power and plug-type filters applied upfront) and pick from a distance-sorted list.
- Each favorite gets its own status sensor (available/occupied/out of service), a dedicated charging-power sensor, a plug-type sensor, an operator sensor, a station-ID sensor, and a `geo_location` map marker (distance shown relative to your Home Assistant home zone) — all refreshed live, independent of the radius view.

## 1.0.0 — 2026-07-16

Initial public release.

- `geo_location` entities for charging stations within a configurable radius, sourced from the ich-tanke-strom.ch WFS API (~19,000 charging points nationwide)
- `sensor.charging_stations_available_<radius>km` — count of currently available stations matching the active filters
- Live-adjustable filters via `number`/`select` entities: minimum power, plug type, availability status, operator — changes apply immediately, no restart needed
- Automatic dashboard setup with a native Map card showing live station status
- Multi-language support (German, English, French, Italian) for entity names, device info, dashboard, and filter dropdown values, based on the Home Assistant language setting
- Data refreshed every 5 minutes
- All entities carry the required Open Data attribution
