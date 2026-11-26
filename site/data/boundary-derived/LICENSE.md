# Boundary-derived data: licence and attribution

The files in this folder are the **boundary-derived database** of the Worldwide Quality of Life Map,
Lake Victoria regional research preview:

| File | Contents |
|---|---|
| `boundaries.geojson` | Simplified national outlines for six countries, one feature per country, with its licence |
| `cell-countries.csv`, `cell-countries.json` | For each H3 res-6 cell: the countries whose outlines cover it and by what share, outline overlaps, the known-dispute flag, years since census (attached through the country), and the population recency grade that depends on it |
| `datapackage.json` | Machine-readable description of these files and their licences (Frictionless Data Package) |

## Licence

This database is made available under the **Open Database License 1.0 (ODbL)**: https://opendatacommons.org/licenses/odbl/1-0/.
Any rights in individual contents of the database are licensed under the Database Contents License:
https://opendatacommons.org/licenses/dbcl/1-0/

It is offered under ODbL because it contains data derived from the Uganda and Democratic Republic of the
Congo outlines, which geoBoundaries distributes under ODbL 1.0 (source: OpenStreetMap, Wambacher). The
outlines of the other countries keep their original terms as well (listed below), so material derived
only from them may also be used under those terms.

**Share-alike (ODbL 4.4).** If you publicly use an adapted version of this database, or a work produced
from an adapted version, you must offer the adapted database under ODbL 1.0 too.

**Keep it open (ODbL 4.6, 4.7).** If you redistribute this database or an adapted version, you may not
apply technical restrictions that prevent others from using it, unless you also make an unrestricted
version available.

**Attribution (ODbL 4.2, 4.3).** Any public use or produced work must carry a notice such as:

> Contains boundary-derived data from the Worldwide Quality of Life Map, made available under the
> Open Database License 1.0. Country outlines from geoBoundaries (Runfola et al. 2020); Uganda and
> DRC outlines © OpenStreetMap contributors (via Wambacher), ODbL 1.0.

## Inputs

| ISO | Name | Source (per geoBoundaries) | Licence | Year represented |
|---|---|---|---|---|
| UGA | Uganda | OpenStreetMap, Wambacher | Open Data Commons Open Database License 1.0 | 2017 |
| KEN | Kenya | RCMRD GeoPortal, geoBoundaries | Public Domain | 2020 |
| TZA | United Republic of Tanzania | Sentinel-2 10-Meter Land Use/LandCover | Creative Commons Attribution 4.0 (CC BY 4.0) | 2021 |
| RWA | Rwanda | Sentinel-2 10-Meter Land Use/LandCover | Creative Commons Attribution 4.0 (CC BY 4.0) | 2021 |
| BDI | Burundi | geoBoundaries, Wikimedia Commons | Public Domain | 2006 |
| COD | Democratic Republic of the Congo | OpenStreetMap, Wambacher | Open Data Commons Open Database License 1.0 | 2017 |

geoBoundaries: Runfola, D. et al. (2020) geoBoundaries: A global database of political administrative
boundaries. PLoS ONE 15(4): e0231866. https://www.geoboundaries.org

## What these files are not

Outlines are simplified and drawn for orientation. Where two outlines overlap, the files flag it as a
disagreement between boundary sources, not a political dispute. The known-dispute flag is not drawn
from a neutral register and is incomplete.
