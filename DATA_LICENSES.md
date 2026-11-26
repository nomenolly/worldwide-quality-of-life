# Data licences

The code in this repository is MIT licensed (see `LICENSE`). The data is in two groups:

* **Observations** (`site/data/observations.json`, `site/data/indicators.json`, `site/data/cells.geojson`, `data/processed/`): each value stays under its source's terms below.
* **Boundary-derived data** (`site/data/boundary-derived/`): the country outlines, each cell's country coverage, outline-overlap and dispute flags, years since census per cell, and the population recency grade that depends on it. This package is offered as a whole under **ODbL 1.0**, because it is derived in part from the ODbL-licensed Uganda and DRC outlines. Terms, attribution text and a Frictionless `datapackage.json` are in that folder.

Only openly licensed sources are used (WQL-001 D-13, proposed). The conflict layer (UCDP GED) is withheld from the Lake Victoria regional research preview and is not in any published file.

| Source | Licence | Used for | Attribution required |
|---|---|---|---|
| GHS-POP R2023A, European Commission JRC | Reuse authorised provided the source is acknowledged (Commission Decision 2011/833/EU); CC BY 4.0 ([JRC record](https://data.jrc.ec.europa.eu/dataset/2ff68a52-5b5b-4a22-8f40-c41da8332cfe)) | `pop.ghsl`, weights for `urb.share` and `acc.*` | Yes; cite doi:10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE |
| GHS-SMOD R2023A, European Commission JRC | Reuse authorised provided the source is acknowledged (Commission Decision 2011/833/EU); CC BY 4.0 | `urb.share` | Yes; cite doi:10.2905/A0DF7A6F-49DE-46EA-9BDE-563437A6E2BA |
| WorldPop Global2 R2025A | CC BY 4.0, confirmed by WorldPop ([catalogue](https://api.worldpop.org/v3/documentation), [FAQ](https://www.worldpop.org/faq/)) | `pop.worldpop`, `pop.disagreement`, `pop.disagreement_abs` | Yes. WorldPop asks that the data not be used to discriminate, exploit or surveil. |
| Malaria Atlas Project, travel time to healthcare 2020 | CC BY 3.0 Unported | `acc.motor`, `acc.walk` | Yes; cite Weiss et al. 2020, Nature Medicine |
| UCDP GED 26.1 | CC BY 4.0 | `sec.conflict`, **withheld from the preview** (C-11) | Yes, if a coarser release is approved; cite Sundberg and Melander 2013 and the 26.1 codebook |
| UNSD census dates | UN web page; facts transcribed | `kno.census_age` (published in the boundary-derived package) | Cite the page |
| geoBoundaries ADM0 | Per country: UGA and COD **ODbL 1.0** (OpenStreetMap via Wambacher); TZA and RWA CC BY 4.0; KEN and BDI public domain | `site/data/boundary-derived/` | Yes; see `site/data/boundary-derived/LICENSE.md`. Share-alike: adapted versions must also be offered under ODbL. |
| OpenStreetMap tiles (basemap, loaded by the browser) | ODbL | Display only | "© OpenStreetMap contributors", shown on the map |

Full citations are in `config/sources.toml` and in each cell's "Caveat and source" panel on the map.
