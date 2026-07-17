# Data Source & Attribution

This integration retrieves charging-station data at runtime from the official **ich-tanke-strom.ch** platform, operated on behalf of the Swiss Federal Office of Energy (BFE / SFOE), EnergieSchweiz, and swisstopo.

The dataset is published as Open Data on [opendata.swiss](https://opendata.swiss/en/dataset/ladestationen-fuer-elektroautos) under the **"Open Use. Must provide the source. Commercial use requires permission of the data owner"** terms (opendata.swiss code `NonCommercialAllowed-CommercialAllowed-ReferenceRequired`, commonly abbreviated *CC BY (Ask)*): free use for non-commercial purposes with attribution; commercial use requires the data owner's (BFE) permission.

**Required attribution:** *ich-tanke-strom.ch (BFE / EnergieSchweiz / swisstopo)*

This integration fulfills that requirement by setting the `attribution` attribute (`"Data: ich-tanke-strom.ch (BFE / EnergieSchweiz / swisstopo)"`) on every entity it creates, which Home Assistant surfaces in the entity's "More Info" dialog. If you build dashboards, automations, or republish this data elsewhere, please keep that attribution visible or add your own equivalent notice.

This integration is unofficial and not affiliated with, endorsed by, or supported by the BFE, EnergieSchweiz, swisstopo, or ich-tanke-strom.ch. It only reads their published Open Data via the public WFS/GeoServer API.

Official documentation: https://github.com/SFOE/ichtankestrom_Documentation
