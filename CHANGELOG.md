# Changelog

## 1.8.0 — 2026-07-20

- New: **charging prices**. For operators that publish their ad-hoc (direct payment) price to the Swiss eMobility price atlas — about a quarter of all Swiss sites, including Swisscharge, MOVE, Energie 360°, IWB, AVIA VOLT, GOFAST, M-Charge, PLUG'N ROLL, ewz, Electra, and Fastned — the integration now shows it:
  - a **Price sensor** per favorite (single charge point and whole site), e.g. "0.57 CHF/kWh"; the source's free-text is kept as-is since some operators add time components ("+ 0.25 CHF/Min (> 1h)"). Sites without a published price show a localized "Not published". The raw value (or `None`) is available as a `price` attribute for automations.
  - a price line on the **bundled card** header, below the address and opening hours (only when a price is published).
  - a price row on the **auto-generated dashboard cards**.
  - the price after the distance in the **favorite picker** labels ("📍 Migros Möhlin (4 charge points) · 1.2 km · 0.45 CHF/kWh").
  - a `price` attribute on the radius map markers.
- Prices come from the "Ladepreiskarte Swiss eMobility" open dataset (price atlas by chargeprice.app), republished by the SFOE on data.geo.admin.ch — the same values ich-tanke-strom.ch and map.geo.admin.ch display. They are fetched at most every 6 hours by one shared cache; a price fetch failure never affects the availability data.

## 1.7.5 — 2026-07-19

- New: the card's header badges now stack vertically at a uniform size: availability, accessibility, renewable energy. A new **hide badges** multi-select in the visual editor (`hidden_badges` in YAML) hides individual ones.
- New: the source's **Accessibility** declaration is read and shown as a badge — "Publicly accessible" (neutral), "Restricted access" (amber), "Paid access" (gray-blue), localized; also exposed as `accessibility` (raw) and `accessibility_text` attributes on the favorite status and site overview sensors.
- New: the source's **RenewableEnergy** declaration is now read and exposed — as a `renewable_energy` attribute on the favorite status sensor, per connector in the site overview's `connectors` attribute (`renewable`), and as a dark-green leaf badge in the bundled card's header next to the availability badge (for a whole site only when no connector explicitly reports otherwise).

## 1.7.1 — 2026-07-19

- Changed: the auto-created dashboard is now titled **"Ladestationen CH"** / "Charging Stations CH" (localized) instead of the unsuffixed name, so it stays distinguishable next to sibling integrations for other countries. Existing installations are migrated automatically on the next restart — but only if the dashboard still carries the exact old default title; a title you customized yourself is never touched.

## 1.7.0 — 2026-07-19

- New: **per-plug-type availability sensors for favorite sites** — every plug type present at a site automatically gets its own sensor counting the currently available charge points of that type (e.g. `sensor.charging_station_favorite_location_<name>_available_ccs2` / `..._available_chademo`), matching the bundled card's visible-plug-types filter. The auto-generated dashboard card lists them as rows below the overall count — also for single-type sites, where naming the plug type makes the card easier to read. The site overview sensor additionally exposes the counts as an `available_by_plug_type` dictionary attribute.
- New: **per-plug-type availability sensors** for radius entries — the integration now has a Configure dialog (it previously had none) with a multi-select of plug types, and each selected type gets its own sensor counting the available charge points of that type within the radius (e.g. `sensor.charging_stations_available_15km_ccs2`). These sensors respect the minimum-power and operator filters but deliberately ignore the live plug-type and status filters, so filtering the map to Type 2 no longer makes your "free CCS" count drop to 0. Selecting/deselecting types adds/removes the sensors live, no restart needed.
- New: the radius availability sensor has an `available_by_plug_type` attribute — the same per-type counts as a dictionary, for templates without a dedicated sensor.

## 1.6.5 — 2026-07-19

- Fixed: the card's tile order now matches the "Charge Point 1/2/3" sections of the entities card — the tiles followed the API's response order while the sections are numbered by sorted charge-point ID, so tile #1 could describe a different connector than "Charge Point 1" right below it.
- Fixed: customizations made on an auto-generated favorite card (e.g. the new plug-type filter, or a changed title) no longer get wiped by the restart sync — the sync now only refreshes what the integration manages (the entity lists), keeping your edits on the graphic card.
- Fixed: deleting a favorite could leave its auto-generated dashboard card behind when Lovelace wasn't ready at that exact moment (e.g. right after a restart) — the one-shot cleanup silently no-oped. A sweep on every start now removes leftover cards whose favorite no longer exists.
- Fixed: the auto-generated favorite cards now support Home Assistant's **visual editor** — the internal marker key that identified each card for syncing/removal made the editor refuse the card ("visual editor not supported"). Cards are now identified through the integration's persistent store instead, keeping the card config clean; existing cards are migrated automatically on the next restart.
- New: the bundled card has an optional **visible plug types** filter (multi-select in the visual editor, `plug_types` in YAML) — tiles of other plug types are hidden and the availability badge counts only the visible connectors (e.g. "1/2 available" for just the CCS chargers of a 3-connector site). Purely visual: the favorite, its sensors, and the dashboard entities card keep covering the whole site. The editor offers the plug types actually present at the selected site; tiles keep their original numbering so they still match the per-connector sensors; a filter matching nothing falls back to showing everything.

## 1.6.4 — 2026-07-19

- Changed: the availability badge ("2/3 available") is now colored like the tiles — green while at least one connector is free, red when every connector is taken (previously always gray).
- Changed: the card badge distinguishes full-day closures from being outside today's hours — "Closed today" (localized) when the schedule has no opening periods for today at all (e.g. Sundays), plain "Closed" otherwise. Exposed as a `closed_all_day_today` attribute on the favorite status/overview sensors.
- Changed: while a site is closed (outside its opening hours), the bundled card now shows every connector tile in blue with "Closed" instead of green "Available" (user report: the operator keeps reporting Available, which is technically correct from the API's perspective, but you can't charge right now — misleading if you only glance at the green tiles). Blue is a distinct fourth color next to green (available), red (occupied), and gray (out of service); the closed badge uses it too. The underlying sensors keep reporting the raw operator status for automations; single-favorite cards get the same treatment via a new `site_status` attribute on the favorite status sensor.
- Changed: the opening-hours line now shows the full weekly schedule with consecutive days collapsed ("Mon–Fri 08:00–20:00 · Sat 07:30–18:00", localized weekday names) instead of only today's hours — the current open/closed state is already covered by the status. The sensor attribute is renamed from `opening_hours_today` to `opening_hours` accordingly.

## 1.6.1 — 2026-07-19

- Fixed: adding a favorite by ID no longer under-counts the site (user report: 2 of 4, 1 of 3, 1 of 8 charge points shown). Several operators give each pole (e.g. `CH*MIG*P*1797` vs `*1813`) or even each connector (aggregators, where the site ID equals the EvseID) its own ID, so a direct ID lookup only ever saw a slice of the site. The ID path now resolves the full physical site through the same operator+address merge the search picker has used since v1.2.1: a site ChargingStationId expands to all connectors at that address automatically, and an EvseID whose site has more charge points opens a new choice step — pin just that charge point, or the whole site (default).
- New: adding a favorite by ID now ends in a **confirmation step** showing what was resolved (the site with its charge-point count, or the single charge point) with an optional **custom name** field — previously the ID path created the favorite immediately and never offered naming (that only existed in the location search picker).
- New: today's opening hours are shown on the bundled card below the address ("Today 07:30–20:00" / "Closed today" / "Open 24 h", localized) and as an "Opening hours" row on the auto-generated dashboard card, plus as an `opening_hours_today` attribute on the favorite status/overview sensors for use in automations. Sites without schedule data simply omit the line.
- Improved: site status now evaluates the source's structured `OpeningTimes` schedule (present for some operators, e.g. Migros; evaluated in the Swiss timezone). A site outside its opening hours shows as "Closed" even while its connectors still report "Available" — previously closed sites could look available. Sites without schedule data keep the existing every-connector-out-of-service heuristic; 24h sites are unaffected.

## 1.5.0 — 2026-07-18

- New: whole-site favorites get a derived **overall status** — "Available", "Occupied", "Closed", or "Out of service". The source has no opening-hours data, but "every connector out of service at a non-24h site" reliably means closed outside opening hours, distinct from a genuinely broken 24h site. Shown as its own status sensor (localized state, raw `site_status` attribute for automations) listed right below the available-count on the auto-generated dashboard card, as a badge on the bundled card (replacing "0/6 available"), and as the map marker label on the radius view.
- New: a favorite can now be added by **site ID** — the ID field of the favorite setup accepts a whole-site ChargingStationId in addition to a single charge point's EvseID, creating a whole-site favorite directly without searching by location.
- Fixed: the auto-created dashboard came back after a restart if you had deleted it. It is now created only once — deleting it sticks. Note that removing its sidebar entry additionally needs one restart (a Home Assistant limitation for integration-registered panels).

## 1.4.0 — 2026-07-17

- Changed: the radius map now shows **one marker per charging site** instead of one per charge point — connectors at the same location are grouped (same logic as the favorite picker), so multi-charger sites no longer stack indistinguishable markers on identical coordinates. Multi-connector sites are labeled with their availability ("6/7 available", localized), single chargers keep their plain status label. Markers are now refreshed in place on every update, so the labels stay live. Leftover per-connector marker entities from earlier versions are cleaned up automatically.
- Changed: the radius is now capped at **30 km** in the setup (radius overview and favorite search) — larger areas make the source server slow (20–40+ seconds per fetch) and would flood Home Assistant with thousands of entities. Existing entries with a larger radius keep working. Independently, at most the 500 nearest sites get a map marker; the availability sensor always counts the full filtered set.
- Fixed: a radius fetch could fail entirely (integration setup aborting with "unreachable: 0") when the source returned a station with a malformed single-element field — observed live for 2 of ~6,000 stations reporting `ChargingStationNames` as an object instead of a list. Parsing now normalizes these fields, and a malformed station is skipped instead of breaking the whole refresh.
- Improved: large-radius fetches are much faster and no longer time out — the request now asks only for the needed properties (roughly halves response size and server time) and uses a more generous timeout (90 s instead of 30 s).

## 1.3.3 — 2026-07-17

- Changed: the bundled card is renamed to `swiss-charging-stations-card` (matching the integration name); use `type: custom:swiss-charging-stations-card` going forward. The former `custom:ich-tanke-strom-card` keeps working as a compatibility alias, auto-generated dashboard cards migrate automatically on restart, and the stale resource entry for the old file name is cleaned up.

## 1.3.2 — 2026-07-17

- Fixed: declare the `http` component as a manifest dependency (used since v1.3.0 to serve the bundled card) — resolves the hassfest validation error. No functional change.

## 1.3.1 — 2026-07-17

- New: the bundled card now has a visual config editor — when adding it from the card picker or editing an existing one, a form with an entity dropdown (filtered to this integration's sensors) and an optional title field appears instead of the YAML editor. Editor labels are localized in all four languages.

## 1.3.0 — 2026-07-17

- New: bundled Lovelace card `ich-tanke-strom-card` — colored per-connector status boxes (green = available, red = occupied, gray = out of service), each showing plug type, charging power, and status, plus site name, address, and an available/total badge. Works for whole-site favorites (one box per connector) and single favorite stations. Registers itself as a Lovelace resource automatically — no manual setup — and appears in the card picker as "Swiss Charging Stations Card". Clicking the card opens the entity's more-info dialog.
- New: the auto-generated "Favorites" dashboard cards now show the graphical card on top of the existing per-connector entities list.
- New: favorite sensors expose the raw API status (`status_raw`) as an attribute alongside the localized display text, so the card's colors work independently of the active language.
- Plug-type abbreviations on the card stay short where unambiguous (CCS, CCS 1, CHAdeMO, Tesla, T13); the two Type 2 variants are distinguished as "Type 2" (outlet — bring your own cable) and "Type 2 cable" (attached cable), localized in all four languages.

## 1.2.2 — 2026-07-17

- Improved: whole-site entries (📍) in the favorite picker now show the distance in km, matching what individual charge points already display.

## 1.2.1 — 2026-07-17

- Fixed: charging sites that the data source reports as several separate stations are now merged into one location when they share the same operator and address. This affects two real-world data patterns: operators that report no shared site ID at all (each connector listed as its own station — e.g. Tesla Superchargers, various e-mobility aggregator stations, MOVE), and operators that assign each charging pole at one site its own ID (e.g. a Migros site listed as "Migros | Möhlin 1" and "Migros | Möhlin 2"). A Tesla site with 10 charge points now appears as one location with 10 charge points instead of 10 single-connector entries, and the Migros example becomes one location with 4 charge points instead of two with 2. Correctly grouped sites are unaffected.
- Fixed: favoriting such a merged location now works reliably — since no single station ID covers the merged site in the source data, the individual charge-point IDs are pinned instead and refreshed together.
- Changed: setup wording now says "Pin a single station or location" to make clear that whole sites can be favorited, not just single connectors (all four languages).

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
