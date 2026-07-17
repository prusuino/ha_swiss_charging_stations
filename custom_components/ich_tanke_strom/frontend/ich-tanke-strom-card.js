/* Swiss Charging Stations card — colored per-connector status boxes for a
 * favorite charging station or a whole favorite site, in the visual style of
 * ich-tanke-strom.ch (green = available, red = occupied, gray = out of
 * service). Ships with the integration; registered as a Lovelace resource
 * automatically, no manual setup required.
 *
 * Config:
 *   type: custom:ich-tanke-strom-card
 *   entity: sensor.charging_station_favorite_location_xxx   (site summary)
 *     — or —
 *   entity: sensor.charging_station_favorite_xxx            (single station)
 *   title: optional override for the card header
 */

const STATUS_COLORS = {
  Available: "var(--success-color, #2e7d32)",
  Occupied: "var(--error-color, #c62828)",
  OutOfService: "var(--disabled-text-color, #757575)",
};
const UNKNOWN_COLOR = "var(--warning-color, #f9a825)";

const AVAILABLE_WORD = { de: "frei", en: "available", fr: "libre", it: "liberi" };

const TYPE_WORD = { de: "Typ", en: "Type", fr: "Type", it: "Tipo" };
const CABLE_WORD = { de: "Kabel", en: "cable", fr: "câble", it: "cavo" };

/* Abbreviations stay short as long as they are unambiguous; only the two
 * Type-2 variants (socket vs. attached cable) need the distinction. */
function shortPlug(plug, lang) {
  if (!plug) return "";
  const type = TYPE_WORD[lang] || TYPE_WORD.en;
  if (plug.startsWith("CCS Combo 2")) return "CCS";
  if (plug.startsWith("CCS Combo 1")) return "CCS 1";
  if (plug.startsWith("CHAdeMO")) return "CHAdeMO";
  if (plug.startsWith("Tesla")) return "Tesla";
  if (plug.startsWith("Type 2 Outlet")) return `${type} 2`;
  if (plug.startsWith("Type 2 Connector"))
    return `${type} 2 ${CABLE_WORD[lang] || CABLE_WORD.en}`;
  if (plug.startsWith("Type 1")) return `${type} 1`;
  if (plug.startsWith("Type J")) return "T13";
  return plug;
}

function shortPlugs(plugs, lang) {
  if (!Array.isArray(plugs)) return "";
  const shorts = [...new Set(plugs.map((p) => shortPlug(p, lang)).filter(Boolean))];
  return shorts.join(" · ");
}

class IchTankeStromCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) {
      throw new Error("ich-tanke-strom-card: 'entity' is required");
    }
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 3;
  }

  static getStubConfig(hass) {
    const candidate = Object.keys(hass.states).find((id) =>
      id.startsWith("sensor.charging_station_favorite")
    );
    return { entity: candidate || "" };
  }

  _lang() {
    const lang = (this._hass && this._hass.language) || "en";
    return lang.split("-")[0];
  }

  _render() {
    if (!this._hass || !this._config) return;
    const stateObj = this._hass.states[this._config.entity];

    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
    }

    if (!stateObj) {
      this._root.innerHTML = `<ha-card><div style="padding:16px;">
        Entity not found: ${this._escape(this._config.entity)}</div></ha-card>`;
      return;
    }

    const attrs = stateObj.attributes;
    const isSite = Array.isArray(attrs.connectors);
    const title =
      this._config.title || attrs.friendly_name || this._config.entity;
    const addressParts = [
      attrs.street,
      [attrs.postal_code, attrs.city].filter(Boolean).join(" "),
    ].filter(Boolean);
    const address = addressParts.join(", ");

    let boxes;
    let badge = "";
    if (isSite) {
      const total = attrs.count_total || attrs.connectors.length;
      const available = Number(stateObj.state) || 0;
      const word = AVAILABLE_WORD[this._lang()] || AVAILABLE_WORD.en;
      badge = `${available}/${total} ${word}`;
      boxes = attrs.connectors.map((c, i) =>
        this._box(
          c.status_raw,
          c.status,
          c.power_kw,
          shortPlugs(c.plug_types, this._lang()),
          i + 1
        )
      );
    } else {
      boxes = [
        this._box(
          attrs.status_raw,
          stateObj.state,
          attrs.power_kw,
          shortPlugs(attrs.plug_types, this._lang()),
          null
        ),
      ];
    }

    this._root.innerHTML = `
      <style>
        .wrap { padding: 12px 16px 16px; }
        .head {
          display: flex; align-items: baseline; justify-content: space-between;
          gap: 8px; margin-bottom: 2px;
        }
        .title {
          font-size: 1.15em; font-weight: 500;
          color: var(--primary-text-color);
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .badge {
          flex: none; font-size: 0.85em; font-weight: 500;
          padding: 2px 10px; border-radius: 12px;
          background: var(--secondary-background-color, rgba(127,127,127,.15));
          color: var(--primary-text-color);
        }
        .addr {
          font-size: 0.85em; color: var(--secondary-text-color);
          margin-bottom: 12px;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .grid {
          display: grid; gap: 8px;
          grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
        }
        .box {
          border-radius: 8px; padding: 10px 8px; color: #fff;
          display: flex; flex-direction: column; align-items: center;
          gap: 2px; text-align: center; cursor: pointer;
          min-height: 64px; justify-content: center;
        }
        .box .num { font-size: 1em; font-weight: 700; opacity: 0.95; }
        .box .plug { font-size: 0.95em; font-weight: 600; }
        .box .power { font-size: 1.1em; font-weight: 600; }
        .box .status { font-size: 0.85em; font-weight: 500; }
      </style>
      <ha-card>
        <div class="wrap">
          <div class="head">
            <div class="title">${this._escape(title)}</div>
            ${badge ? `<div class="badge">${this._escape(badge)}</div>` : ""}
          </div>
          ${address ? `<div class="addr">${this._escape(address)}</div>` : ""}
          <div class="grid">${boxes.join("")}</div>
        </div>
      </ha-card>`;

    this._root.querySelector("ha-card").addEventListener("click", () => {
      this.dispatchEvent(
        new CustomEvent("hass-more-info", {
          bubbles: true,
          composed: true,
          detail: { entityId: this._config.entity },
        })
      );
    });
  }

  _box(statusRaw, statusText, powerKw, plugShort, num) {
    const color = STATUS_COLORS[statusRaw] || UNKNOWN_COLOR;
    const power = powerKw ? `${Number(powerKw)} kW` : "";
    return `<div class="box" style="background:${color};">
      ${num !== null ? `<div class="num">#${num}</div>` : ""}
      ${plugShort ? `<div class="plug">${this._escape(plugShort)}</div>` : ""}
      ${power ? `<div class="power">${this._escape(power)}</div>` : ""}
      <div class="status">${this._escape(statusText || "?")}</div>
    </div>`;
  }

  _escape(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }
}

customElements.define("ich-tanke-strom-card", IchTankeStromCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "ich-tanke-strom-card",
  name: "Swiss Charging Stations Card",
  description:
    "Colored per-connector status boxes for a favorite charging station or site (ich-tanke-strom.ch).",
  preview: true,
});
