# Release gates

Ratified by Nolen on 2026-11-27 for public research-preview releases. A release is blocked until every gate holds, for the **repository's full history** as well as its current state.

## 1. Publication protections apply to history

* Withheld data (currently all conflict records, C-11) must not appear in any commit reachable from a public branch or tag, nor in published site files.
* History was rewritten on 2026-11-27 to remove conflict records from the first commit. The original history is kept only as a restricted archive outside the public repository.
* Check before each release: `python3 pipeline/check_release.py` scans every commit reachable from all branches and tags, and the current tree, and fails if a withheld layer appears in any data file.

## 2. Collapse audit

Any collapse pattern scored **2 is an immediate release-gate failure**. Scores stay an unaggregated diagnostic vector; they are never summed.

| Collapse pattern | Metaphor | Nolen's provisional score (2026-11-26) | Since then |
|---|---|---|---|
| Spatial index implies observational precision | Grid as ruler | 1 | Native grain now in every legend; pixel-centre assignment remains |
| Unassigned geography implies uninhabited geography | Boundary as eraser | 2 | Fixed: no water inference from outlines; surface is its own observation (`geo.water_share`) |
| Missing, zero and withheld become indistinguishable | Blank as verdict | 0 | |
| Signed difference becomes absolute magnitude | Gap as magnitude | 2 | Fixed: D, abs(D) and W - G are separate fields and layers |
| Regional observation implies global applicability | Window as world | 0 | |
| Different reference periods appear simultaneous | Mosaic as moment | 1 | Reference years now in every legend |
| Region-specific colour scales imply universal standards | Palette as norm | 1 | Legend says classes are regional and no colour means better or worse |
| Agreement between dependent sources implies independent verification | Echo as witness | 1 | Each value shows what it is not independent of |
| Population averages imply individual experience | Mean as person | 1 | Each value shows its kind of number; travel time notes that the average is no one's journey |
| Absence of reported harm implies safety | Silence as peace | 1 | Withheld conflict card says its absence implies nothing about safety |
| Observed conditions imply governmental performance | Outcome as authority | 0 | |

Re-scoring after the fixes is Nolen's to do.

## 3. Six-axis legibility

Every observation must stay distinguishable at its point of interpretation along: spatial extent, temporal extent, evidentiary basis, inferential distance, representational completeness and normative imposition. A correction that exists only in documentation does not count.

## Notation

W = WorldPop population estimate; G = GHSL population estimate (ratified 2026-11-27). D = 100 x (W - G) / ((W + G) / 2).
