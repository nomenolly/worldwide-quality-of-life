# Data licences

The code in this repository is MIT licensed (see `LICENSE`). The data in `data/processed/` and `site/data/` is derived from the sources below and stays under their terms. Only openly licensed sources are used (WQL-001 D-13).

| Source | Licence | Used for | Attribution required |
|---|---|---|---|
| GHS-POP R2023A, European Commission JRC | CC BY 4.0 | `pop.ghsl`, weights for `urb.share` and `acc.*` | Yes; cite doi:10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE |
| GHS-SMOD R2023A, European Commission JRC | CC BY 4.0 | `urb.share` | Yes; cite doi:10.2905/A0DF7A6F-49DE-46EA-9BDE-563437A6E2BA |
| WorldPop Global2 R2025A | CC BY 4.0 per Google Earth Engine; not stated on WorldPop's own pages | `pop.worldpop`, `pop.disagreement` | Yes. Confirm the licence with WorldPop before redistributing derived rasters. WorldPop asks that the data not be used to discriminate, exploit or surveil. |
| Malaria Atlas Project, travel time to healthcare 2020 | CC BY 3.0 Unported | `acc.motor`, `acc.walk` | Yes; cite Weiss et al. 2020, Nature Medicine |
| UCDP GED 26.1 | CC BY 4.0 | `sec.conflict` | Yes; cite Sundberg and Melander 2013 and the 26.1 codebook, with the version number |
| UNSD census dates | UN web page; facts transcribed | `kno.census_age` | Cite the page |
| geoBoundaries ADM0 | Per country: UGA and COD **ODbL 1.0**; TZA and RWA CC BY 4.0; KEN and BDI public domain | `site/data/boundaries.geojson`; cell-to-country attachment | Yes. ODbL is share-alike: the boundary file and the cell-to-country attachment for Uganda and DRC carry ODbL. |
| OpenStreetMap tiles (basemap, loaded by the browser) | ODbL | Display only | "© OpenStreetMap contributors", shown on the map |

Full citations are in `config/sources.toml` and in each cell's "Caveat and source" panel on the map.
