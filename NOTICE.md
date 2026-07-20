# Data Source & Attribution

This integration retrieves charging-station data at runtime from the official **ich-tanke-strom.ch** platform, operated on behalf of the Swiss Federal Office of Energy (BFE / SFOE), EnergieSchweiz, and swisstopo.

The dataset is published as Open Data on [opendata.swiss](https://opendata.swiss/en/dataset/ladestationen-fuer-elektroautos) under the **"Open Use. Must provide the source. Commercial use requires permission of the data owner"** terms (opendata.swiss code `NonCommercialAllowed-CommercialAllowed-ReferenceRequired`, commonly abbreviated *CC BY (Ask)*): free use for non-commercial purposes with attribution; commercial use requires the data owner's (BFE) permission.

**Required attribution:** *ich-tanke-strom.ch (BFE / EnergieSchweiz / swisstopo)*

This integration fulfills that requirement by setting the `attribution` attribute (`"Data: ich-tanke-strom.ch (BFE / EnergieSchweiz / swisstopo)"`) on every entity it creates, which Home Assistant surfaces in the entity's "More Info" dialog. If you build dashboards, automations, or republish this data elsewhere, please keep that attribution visible or add your own equivalent notice.

## Charging price data

Since v1.8.0 the integration additionally reads the published ad-hoc charging prices embedded in the official charging-station GeoJSON on **data.geo.admin.ch** (the file behind the map.geo.admin.ch charging-station layer, published by the BFE / SFOE). The prices in that file originate from the **"Ladepreiskarte Swiss eMobility"** dataset — the charging price atlas operated by Swiss eMobility together with chargeprice.app.

That dataset is likewise published as Open Data on [opendata.swiss](https://opendata.swiss/en/dataset/ladepreiskarte-swiss-emobility) under the same **"Open use. Must provide the source. Commercial use requires permission of the data owner"** terms (`terms_by_ask`): free use with attribution; commercial use requires the data owner's (Swiss eMobility) permission.

**Required attribution:** *Ladepreisatlas Swiss eMobility (chargeprice.app)*

This integration fulfills that requirement by setting the `attribution` attribute (`"Prices: Ladepreisatlas Swiss eMobility (chargeprice.app) via BFE / data.geo.admin.ch"`) on every price sensor it creates. The integration does **not** access chargeprice's key-protected API — it only reads the openly republished federal GeoJSON.

## Scope

This integration is unofficial and not affiliated with, endorsed by, or supported by the BFE, EnergieSchweiz, swisstopo, ich-tanke-strom.ch, Swiss eMobility, or chargeprice.app. It only reads their published Open Data via the public WFS/GeoServer API and the public GeoJSON on data.geo.admin.ch.

Official documentation: https://github.com/SFOE/ichtankestrom_Documentation
