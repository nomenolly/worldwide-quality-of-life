# WQL-003: Global reference preview

**Objective (Nolen, 2026-11-27):** global coverage before analytical sophistication. The proof of concept is reached when any locality on Earth can be selected and the engine returns what it presently knows, including an honest account of what it does not know.

**Status:** proof of concept reached on a branch. Not published: the global page is excluded from the Pages workflow until Nolen approves its release under the release gates.

## What exists now

* **The whole globe on one H3 substrate.** 603,090 H3 resolution-5 cells (about 253 km² each on average) hold land, modelled residents or a value from at least one source. Every other cell on Earth is still selectable; the inspector says that no source touches it and what that means.
* **A global map with Nolen's four controls** at `site/global/index.html`: Locality (click, or type latitude/longitude or an H3 cell id), Indicator, Observation date and Evidence. The heatmap is drawn at H3 resolution 2, 3, 4 or 5 depending on zoom.
* **A locality inspector** that lists, for any place: every ingested value with its source, native grain, number of source pixels behind it, kind of number, reference period, evidence grades and lineage; every ingested indicator that has no value there, with the reason; and all ten reference indicators that are not yet on the map, with why and what would unblock them.
* **The same query from the command line**: `make locate LL="-1.29 36.82"` (reads only the published files, so it returns exactly what the map shows).

### Layers

| Layer | Source | Native grain | Period | Aggregation |
|---|---|---|---|---|
| `pop.ghsl` population density (primary) | GHS-POP R2023A global mosaic | 30″ raster | 2020 | sum of positive pixels ÷ cell area |
| `pop.worldpop` population density | WorldPop Global2 R2025A, constrained | 30″ raster | 2020 | sum of valid pixels ÷ cell area |
| `pop.disagreement` D, signed | derived from the two | per cell | 2020 | D = 100(W − G)/((W + G)/2); none where both < 100 people |
| `acc.motor` travel time to care, motorised | Malaria Atlas Project 2020 (60 WCS tiles) | 30″ raster | 2019–2020 | GHSL-population-weighted mean; min and max kept as spread |
| `geo.land` land share of cell | GHS-LAND R2022A | 1 km Mollweide | 2018 | m² of land ÷ cell area |

Global totals as a sanity check: GHSL 7.84 billion people, WorldPop 7.85 billion, land 144.6 million km².

### The twelve reference indicators

| Indicator | Status | Why not yet |
|---|---|---|
| Population density | **on the map** | |
| Healthcare accessibility | **on the map** | |
| Night-light intensity | blocked | EOG VIIRS needs an account login; NASA Black Marble needs an Earthdata token |
| PM2.5 exposure | blocked | ACAG host not on the cloud allowlist; licence to verify |
| Extreme heat | blocked | ERA5 needs a CDS API key; which heat measure to publish is a design choice |
| Child mortality | prospective | only IHME (non-commercial terms, to verify) known; LMICs only |
| Electricity access | next | Falchetta et al. 2019 candidate; licence to verify; derived from night lights and population |
| Drinking water access | prospective | IHME gridded (non-commercial); JMP is national only |
| Educational attainment | prospective | IHME gridded (non-commercial) |
| Vegetation coverage | next | ESA WorldCover (CC BY 4.0) needs a tiled ingestion rule for 10 m data |
| Internet accessibility | prospective | Ookla Open Data is CC BY-NC-SA |
| Census recency | next | built regionally in WQL-002; needs all-country UNSD dates and a global boundary source |

"Prospective" follows proposed D-13 (openly licensed data only for v0.1). Four of the twelve, including child mortality, have no openly licensed gridded source known so far. **Nolen's ruling on D-13 decides whether they can be ingested.**

## Construction sequence

1. **Whole globe, one real population layer:** done (GHSL 2020).
2. **Provenance and uncertainty:** done. Every value carries source, licence, citation, native grain, pixel count, lineage and six evidence grades. Uncertainty is shown honestly as what exists: neither population model publishes an interval (interval grade D), so the second model and their signed disagreement D stand beside the first, labelled as not independent.
3. **Second indicator through the same architecture:** done (MAP travel time to care).
4. **Repeatable ingestion:** done. `config/indicators.toml` declares each layer and its aggregation rule (`sum`, `weighted_mean`, `area_share`); `pipeline/ingest.py` applies the rule to any raster in any CRS, in strips, and stores per-cell components so coarser resolutions are exact sums of finer ones. Adding a raster indicator is a source entry plus a layer entry.
5. **Source renewal and versioning:** started. `pipeline/renew.py` (also a monthly GitHub Action, `renewal.yml`) compares each source with the server's Last-Modified/ETag/size recorded at download and scans publisher listings for newer releases. It downloads nothing; renewing is a reviewed change. Each build gets a version (`as_of` date + hash of the source files) recorded in `data/builds.json`. First check: nothing changed; the GHSL listing also shows `GHS_WUP_POP_GLOBE_R2025A` and `GHS_POP_ARCTIC_R2025A`, whose relationship to R2023A is not yet checked.
6. **Expand coverage:** the registry says what each next indicator needs.

## Pipeline

```
make global-fetch    # about 5.5 GB into data/raw (GHSL 0.5 GB, WorldPop 0.3 GB, GHS-LAND 0.2 GB, MAP 60 tiles x 67 MB)
make global-ingest   # about 4 minutes on 4 cores
make global-build    # about 15 seconds; writes site/global/data (76 MB, about 14 MB gzipped)
make renew           # upstream change check
make serve           # then open http://localhost:8000/global/
```

New dependencies: `h3ronpy` (vectorised H3 assignment, about 3 million pixels a second), `pyarrow`, `pyproj`. The browser uses `h3-js` 4.5.0, vendored with its Apache-2.0 licence.

## Proposed decisions (for Nolen to ratify or change)

* **D-24.** The global build reports at H3 resolution 5 in the inspector and draws resolutions 2 to 4 when zoomed out; regional builds keep resolution 6. Reason: a resolution-6 global build would be about 4 million cells and roughly 200 MB of published files. Reading native pixels directly (cloud-optimised GeoTIFFs) is the way to go finer, later.
* **D-25.** GHS-LAND is the physical-surface observation for the global build, so that water is never inferred from a zero population or from a missing boundary. The global build uses no country outlines at all.
* **D-26.** Global colour classes are fixed per indicator, not quantiles, and the legend says they are for display only.
* **D-27.** A cell that no source touches is not drawn. Selecting it states exactly what that means, and the legend shows it.
* **D-28.** Population density is per km² of the whole cell, water included. The inspector shows the land share and the count beside it.
* **D-29.** Generated global data is committed to the repository for now. Before publication, consider publishing build outputs as release assets instead, so that renewal does not grow the repository by about 14 MB a build.

## Collapse audit, self-check

Claude's provisional scores against the ratified audit; re-scoring is Nolen's. None is scored 2.

| Pattern | Score | Why |
|---|---|---|
| Grid as ruler | 1 | Native grain and pixel counts at every value; resolution and "index, not precision" shown under the map. Pixel-centre assignment remains, and zoomed-out cells are coarser still. |
| Boundary as eraser | 0 | No boundaries used. Land is its own observation; untouched cells are explained. |
| Blank as verdict | 1 | Value, modelled zero, no estimate, outside extent and untouched are distinct in the Evidence view and the inspector. In the value view, GHSL's zero on water and zero on land share one colour. |
| Gap as magnitude | 0 | Only signed D is a layer. |
| Window as world | 0 | Global now. The opposite risk (implying uniform evidence everywhere) is addressed by extent and absence reasons; LMIC-only sources are not ingested. |
| Mosaic as moment | 1 | Reference years on every value and in the legend; the date control shows that one epoch exists per layer. |
| Palette as norm | 1 | Fixed global classes could read as a standard; the legend says otherwise. |
| Echo as witness | 1 | D carries the dependence note; GHS-LAND and GHS-POP are flagged as one production family. |
| Mean as person | 1 | Travel time is a population-weighted mean with within-cell spread shown. |
| Silence as peace | 0 | No harm data in this build, and none is implied. |
| Outcome as authority | 0 | No jurisdictions. |

## Known gaps and failures

* Only one epoch per layer, so the observation-date control has one option each. GHSL publishes 1975 to 2030 and WorldPop 2015 to 2030; both are registered for ingestion.
* Evidence grades are source-level. The census-age lowering of population recency from WQL-002 is not applied globally (it needs census recency, registered as next).
* The weakest-dimension flag reads D for every layer because no source publishes an interval. That is accurate but uninformative; the full six grades are one click away.
* MAP models travel time across lake surfaces; the inspector says so where GHS-LAND finds no land.
* Basemap tiles come from tile.openstreetmap.org, as in WQL-002.
* No place-name search: it would need an outside geocoding service, which would send people's queries elsewhere. Coordinates and H3 ids only.
