# Worldwide Quality of Life Map

The Worldwide Quality of Life Map brings population, health access, and other observations onto a common geographic grid, starting around Lake Victoria, so anyone can see what’s known about a place, where estimates disagree, and where evidence is missing.

A geographically continuous, epistemically accountable map of human conditions. Geography is the substrate (H3 cells); jurisdictions are overlays. Every observation keeps its provenance, native resolution, uncertainty and evidence grade. Missing data is shown as missing. There are no composite scores and no rankings.

This repository holds **WQL-002**, the first construction milestone: an H3 resolution-6 substrate and the **Lake Victoria regional research preview** (2°S to 3°N, 30°E to 36°E). The foundational specification is WQL-001.

* **The map:** `site/` (static; published by GitHub Pages once enabled)
* **What is missing and what failed:** [`docs/WQL-002-report.md`](docs/WQL-002-report.md)
* **Limits statement shown on the map:** [`site/limits.html`](site/limits.html)
* **Data licences:** [`DATA_LICENSES.md`](DATA_LICENSES.md); boundary-derived data is ODbL 1.0, see [`site/data/boundary-derived/`](site/data/boundary-derived/)

## Layers in this version

| Indicator | Source | Native grain | Period |
|---|---|---|---|
| `pop.ghsl` population (primary) | GHS-POP R2023A | 30 arc-second raster | 2020 |
| `pop.worldpop` population (secondary) | WorldPop Global2 R2025A, constrained, UN-adjusted | 30 arc-second raster | 2020 |
| `pop.disagreement` WorldPop vs GHSL, relative (%) | derived | 30 arc-second rasters | 2020 |
| `pop.disagreement_abs` WorldPop vs GHSL, absolute (people) | derived | 30 arc-second rasters | 2020 |
| `urb.share` urban population share | GHS-SMOD R2023A | 30 arc-second raster | 2020 |
| `acc.motor`, `acc.walk` travel time to health care | Malaria Atlas Project | 30 arc-second raster | 2019–2020 |
| `kno.census_age` years since census (boundary-derived package, ODbL) | UNSD census dates | country | as of 2026 |

Withheld from the preview: `sec.conflict` (UCDP GED 26.1 deaths). At res 6, 83 cells would show a single recorded event, which does not clear C-11. The pipeline still computes it, but `[release] withheld` in `config/region.toml` keeps it out of every output. A coarser release will be proposed separately.

## Build it

```
pip install -r requirements.txt
make fetch    # about 330 MB into data/raw/, hashes recorded in data/manifest.json
make build    # writes data/processed/ and site/data/ (about 30 s)
make serve    # http://localhost:8000
```

To build another region, edit `config/region.toml` (window, countries) and the GHSL tile list in `config/sources.toml`, then run `make fetch build`.

## Layout

```
config/            region window, H3 resolution, source registry with licences and grades
pipeline/fetch.py  downloads with a checksum manifest
pipeline/build.py  substrate, layers, outputs
data/manifest.json URL, size, SHA-256 and retrieval time of every raw file
data/processed/    observations.csv (one row per cell x indicator), indicators.csv (lineage, grades)
site/              the static map (Leaflet, vendored) and its data
site/data/boundary-derived/  ODbL package: outlines, cell-country coverage, census age, datapackage.json
docs/              milestone reports
```

## Output schema

`data/processed/observations.csv` follows WQL-001 section 6.2: `cell_id, indicator_id, period_start, period_end, value, lower, upper, status, grade, grade_detail, source_id, pop_weight, n_source_units, note`. Status is one of measured, modelled, derived, lower bound or absent. `grade` is the weakest of six evidence dimensions, used as a flag; `grade_detail` holds all six. Lineage is per indicator, in `indicators.csv`.
