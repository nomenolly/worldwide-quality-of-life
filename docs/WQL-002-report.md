# WQL-002: Geospatial substrate and regional proof of concept

**Status:** built 2026-11-26; cleared Nolen's proof-of-concept review the same day. Prepared as the **Lake Victoria regional research preview**, on hold for release review. Not deployed: turning on GitHub Pages is Nolen's step. Reproducible with `make all`.

## Collapse audit fixes (2026-11-26)

Nolen's collapse audit scored two patterns as failures (2). Both are fixed at the data-generation level:

* **Boundary as eraser.** The pipeline no longer explains a missing country outline as "open water". Jurisdictional coverage (boundary-derived package) and physical surface (`geo.water_share`, the share of the cell GHS-SMOD classes as water) are now independent observations. Every water statement is attributed to the source that made it.
* **Gap as magnitude.** The signed disagreement D = 100 x (W - G) / ((W + G) / 2) is kept as `pop.disagreement`. Its magnitude abs(D) is a separate field and layer, `pop.disagreement_mag`, with the signed D shown beside it. The signed difference in people, previously labelled "absolute", is renamed `pop.difference_people` so that "absolute" no longer suggests "magnitude".

Score-1 patterns improved cheaply: every legend now shows the layer's reference years and native grain, and says that no colour means better or worse (Mosaic as moment, Grid as ruler, Palette as norm). Every value shows what kind of number it is, how many steps it is from the source, and what it is not independent of (Mean as person, Echo as witness). The withheld conflict layer says its absence implies nothing about safety (Silence as peace).

## Changes for the research preview (release review, 2026-11-26)

| Gate from the review | What changed |
|---|---|
| Population licence text | GHS-POP and GHS-SMOD now cite the JRC terms (reuse authorised with source acknowledgement, Commission Decision 2011/833/EU; CC BY 4.0). WorldPop Global2 R2025A is recorded as CC BY 4.0, confirmed by WorldPop. |
| Boundary redistribution (ODbL) | Everything derived from geoBoundaries moved out of `observations.json` into `site/data/boundary-derived/`: outlines, cell-country coverage, overlap and dispute flags, census age per cell, and the population recency grade that depends on it. The package is offered as a whole under ODbL 1.0 with a `LICENSE.md` (attribution, share-alike, keep-open terms) and a Frictionless `datapackage.json`. The map credits it and links the download. |
| Conflict layer and C-11 | Cell-level conflict records are withheld from the map and from every published file (`[release] withheld` in `config/region.toml`). The build confirms the review's count: 83 cells hold a single recorded event. A coarser release will be proposed separately. |
| Title and disagreement | Retitled "Lake Victoria regional research preview". Population disagreement is now two map layers, relative (% of the mean) and absolute (people), and the inspector shows both with the two estimates. |

Known issue: the first commit on `main` (9bf0353) still contains the cell-level conflict data in git history. Removing it from history means rewriting `main`, which needs Nolen's decision.

WQL-002 moves the Worldwide Quality of Life Map from specification (WQL-001) to construction. This report covers what was built against the acceptance criteria, and gives a full account of missing data, uncertainty and what failed.

## Acceptance criteria

| Criterion | Result | Where |
|---|---|---|
| A reproducible H3 geographic substrate | Met. 9,369 H3 resolution-6 cells whose centres fall in 2°S–3°N, 30°E–36°E (mean 39.6 km² at this latitude). Window and resolution are config, not code. | `config/region.toml`, `pipeline/build.py` (`build_substrate`) |
| Real population observations attached to cells | Met. GHS-POP R2023A (primary) and WorldPop Global2 R2025A (secondary) for 2020, both summed from 30 arc-second pixels. | `pop.ghsl`, `pop.worldpop` |
| Three additional observational layers, harmonised | Met. Urban population share (GHS-SMOD), travel time to health care (motorised and walking, MAP) and years since census (UNSD) are published. Deaths in organised violence (UCDP GED 26.1) was built but is withheld from the preview (C-11). Population disagreement (relative and absolute) is derived from the two population layers. | `urb.share`, `acc.motor`, `acc.walk`, `kno.census_age`, `pop.disagreement`, `pop.disagreement_abs` |
| Interactive map with clickable observations and visible provenance | Met. Static site; clicking a cell shows every value with its native grain, number of source pixels or events, reference period, status, six-dimension evidence grade (weakest flagged), lineage, caveat, source, licence and citation. | `site/` |
| Documented account of missing data, uncertainty and failures | This document, plus `site/limits.html` on the map itself (C-13). | `docs/`, `site/limits.html` |

## How the substrate works

* **H3 res 6 is an index, not a precision claim.** Each value records its native grain (for example "30 arc-second raster, about 0.93 km" or "event points with a location precision code") and how many source units fell in the cell (43 to 51 pixels per cell for the 30 arc-second rasters).
* **Pixel-centre assignment.** Each raster pixel goes to the cell containing its centre. With about 46 pixels per cell this is close to an area-weighted split, but a dense town on a cell edge can shift a few hundred people between neighbours. Area-weighted splitting is a known next step.
* **Country attachment by area share.** A cell is attached to every geoBoundaries outline covering at least 1% of it, largest first.
* **Missing stays missing.** A cell without a value has status `absent` and a stated reason. Nothing is imputed.
* **No scores.** Each layer is displayed alone. Colour classes are quantiles within this window and carry no normative meaning.
* **Evidence grades.** Each source carries default grades on the six WQL-001 dimensions. The pipeline lowers a dimension for a particular cell where it knows more: population recency drops to C or D where the country's last census is more than 10 or 15 years old (published in the boundary-derived package, because it depends on the country assignment). The weakest grade is shown as a flag.

## Missing data

| Layer | Cells without a value | Why |
|---|---|---|
| Population, GHSL | 0 | GHSL covers every pixel, including water (as zero people). |
| Population, WorldPop | 1,232 | The constrained product places people only where settlement is mapped. Lake cells and some rural cells are empty. |
| Population disagreement D (signed) and its magnitude abs(D) | 1,884 each | 1,232 where WorldPop is empty; 652 where both models estimate fewer than 100 people, so a percentage would be noise. |
| Population difference in people (signed) | 1,232 | WorldPop is empty. |
| Water share of cell surface | 0 | Every cell has classified GHS-SMOD pixels. |
| Urban population share | 1,392 | 1,195 cells are classed entirely water by GHS-SMOD with no modelled residents; 197 others have no modelled residents. Either way a share is undefined. |
| Travel time (both) | 0 | MAP models travel time everywhere, including across Lake Victoria. Cells that GHS-SMOD classes entirely water and where GHS-POP models nobody carry a note saying so, attributed to those sources. |
| Conflict deaths | withheld | Not published in the preview (C-11). |
| Years since census | 1,193 | No country outline covers the cell. This is a fact about the boundary files only; the data never infers water or emptiness from it. Surface and population are separate layers (see the island finding below). |

### Findings that matter for the project

1. **Populated islands fall outside every country outline.** 45 cells with about 37,000 modelled people (GHSL) are covered by no simplified geoBoundaries outline. They are Lake Victoria islands and shoreline fishing settlements (for example around Buvuma and the Ssese Islands in Uganda, and islands in the Tanzanian part of the lake). These people get no country-level values. This is exactly the kind of place WQL-001 warns about, where data infrastructure misses people. Next step: test the full-resolution outlines, and stop dropping cells whose population sits outside the outlines.
2. **Eastern DRC is the region's largest knowledge gap, and it shows twice.** DRC has no census in the 1990, 2000, 2010 or 2020 rounds on the UNSD page, so census age is at least 42 years (1984, not yet confirmed). Independently, the two population models disagree far more there: the median absolute disagreement is 47.6% in DRC cells, against 14% to 24% in Uganda, Kenya, Tanzania and Rwanda. The two layers corroborate each other without being combined.
3. **The two population models agree on totals and disagree on placement.** GHSL puts 72.4 million people in the window and WorldPop 71.3 million. Cell by cell, the median absolute disagreement is 19.3%. 19% of comparable cells disagree by more than 50%, and 6% by more than 100%.
4. **Burundi is outside the window.** Its northern border lies south of 2°S, so no cell is attached to it. It stays in the config for when the window grows.

## Uncertainty

* **Population.** Neither GHSL nor WorldPop publishes a per-pixel interval, so both carry interval grade D, and so their weakest-evidence flag is D everywhere. The disagreement layer is the best available signal of uncertainty, but it measures how far two models diverge, not the error of either one.
* **Conflict deaths.** Withheld from the preview. The release review found that 83 cells would display a single recorded event with its fatality estimate and range, which does not clear C-11. Any coarser release (larger cells, longer periods, suppression of small counts) goes to a separate review.
* **An upstream quirk in UCDP.** In about 1% of GED events worldwide (3,691 of 417,968), the high estimate is below best, and in 1,419 the low is above best. This matters for any future conflict release.
* **Travel time.** The within-cell minimum and maximum are shown as spread, not uncertainty. MAP publishes no interval. Cells with no residents use an unweighted mean and say so.
* **Urbanisation.** GHS-SMOD is derived from GHS-POP and built-up surface. It is not independent of the population layer, and the two should not be read as corroborating each other.
* **Time.** Layers describe different moments: population 2020, travel time 2019–2020, census dates as of 2026.

## Boundaries and disputes

* 32 cells contain an overlap of more than 1% of their area between two country outlines. All are on the Kenya–Uganda border. These are disagreements between independently sourced boundary files (Uganda's from OpenStreetMap, Kenya's from RCMRD), not known political disputes, and the map labels them that way.
* 211 cells are legitimately covered by two or more countries.
* **Known disputes are flagged by hand.** The map marks Migingo Island (Kenya and Uganda). Rukwanzi Island in Lake Albert (DRC and Uganda) is registered but not placed, because its location is not yet verified. The list comes from public reporting, not a neutral register, and is incomplete (WQL-001 R-07).
* **Licence.** Uganda's and DRC's outlines are ODbL 1.0 (share-alike). All boundary-derived data is published together in `site/data/boundary-derived/` under ODbL 1.0, with its own licence file and data package. Observations outside that folder contain no boundary-derived values.

## What failed or was not done

| Item | What happened | Next step |
|---|---|---|
| Night-light radiance (VIIRS VNL V2.2, core layer 3) | Not attempted. EOG requires a login, and the licence wording is hedged (WQL-001 4.6). | Decide whether to register for EOG or use the Earth Engine copy, then confirm the licence. |
| PM2.5 (ACAG V6.GL.03, core layer 9) | Not attempted. The data is served from a WashU file host that the build environment does not yet allow. | Find a direct, scriptable URL (AWS open data registry mirror) and add its host. |
| Basemap tiles in testing | The build environment blocks OpenStreetMap tiles, so the map was tested without the basemap. In a normal browser the tiles load. | None needed; the map works without the basemap (toggle off). |
| Area-weighted aggregation | Pixel-centre assignment used instead. | Add exact pixel-hexagon overlap weights if edge effects matter. |
| Full evidence-grading rules (R-10) | Simplified: source-level defaults plus two per-cell rules. | Write the grading rules down and implement them per observation. |
| DRC 1984 census date | Not confirmed; treated as a lower bound. | Confirm from a primary source. |
| Burundi's provinces | Not relevant at ADM0 and outside the window. | Revisit when the window grows. |

## Reproducing the build

```
pip install -r requirements.txt
make all        # fetch (about 330 MB), build, serve on http://localhost:8000
```

`data/manifest.json` records the URL, size, SHA-256 and retrieval time of every downloaded file. If a source republishes, the hashes will differ and the build can be compared against this one.
