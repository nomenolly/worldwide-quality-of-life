"""Global build (WQL-003): from ingested components to the files the global map reads.

Reads data/interim/global/<layer>.parquet (written by ingest.py) and writes
site/global/data/:

  meta.json            layers, the twelve reference indicators (ingested or not, and why),
                       sources, absence reasons, lineage, grades, build version
  r<res>.json          display cells for the coarse global heatmap (one file)
  r4/<parent>.json     display cells at res 4, one file per res-0 parent
  r5/<parent>.json     inspection cells at res 5, one file per res-1 parent

and records the build in data/builds.json (step 5: versioning).

Rules that hold throughout:
  * H3 cells are an index for joining and drawing, never a precision claim. Every
    value carries how many native pixels it came from.
  * Missing stays missing, with a reason. A modelled zero is a value; no estimate
    is not a zero.
  * A cell absent from every file is one where no ingested source has any pixel
    with land, people or a value. The map and inspector state exactly that.
  * No scores, rankings or composites.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import sys
from collections import defaultdict

import h3
import numpy as np
import pandas as pd

from common import MANIFEST, ROOT, load_indicators, load_sources, read_json, weakest, write_json

INTERIM = ROOT / "data" / "interim" / "global"
OUT = ROOT / "site" / "global" / "data"
BUILDS = ROOT / "data" / "builds.json"

# ---------------------------------------------------------------- H3 bit helpers (vectorised)
RES_SHIFT, RES_MASK = np.uint64(52), np.uint64(0xF) << np.uint64(52)


def parent(cells: np.ndarray, res: int) -> np.ndarray:
    """H3 parent at `res` for an array of uint64 cells (all finer than res)."""
    out = (cells & ~RES_MASK) | (np.uint64(res) << RES_SHIFT)
    for r in range(res + 1, 16):
        out |= np.uint64(7) << np.uint64((15 - r) * 3)
    return out


def hexes(cells) -> list[str]:
    return [format(int(c), "x") for c in cells]


# ---------------------------------------------------------------- absence and note codes
REASONS = {
    "wp_nodata": "WorldPop makes no estimate in this cell. Its constrained model places people only where settlement is mapped; elsewhere the raster has no value, which is not a zero.",
    "wp_extent": "Outside WorldPop's extent (60°S to 84°N).",
    "d_missing": "One of the two population models has no value here, so they cannot be compared.",
    "d_small": "Both population models estimate fewer than 100 people here; a percentage difference would mostly be noise.",
    "map_nodata": "The Malaria Atlas Project surface has no value here: open water, or land outside its modelled surface.",
    "map_extent": "Outside the Malaria Atlas Project surface's extent (60°S to 85°N).",
    "ghsl_extent": "Outside the GHSL global mosaic's extent (about 89°S to 89°N).",
}
NOTES = {
    "ghsl_zero_water": "GHSL models no residents here, and GHS-LAND finds no land: this zero is written on water.",
    "ghsl_zero_land": "GHSL models no residents on the land in this cell.",
    "ghsl_partial_water": "Part of this cell is water (see land share), and density is per km² of the whole cell.",
    "map_unweighted": "GHSL models no residents in this cell, so this is the unweighted mean of the pixels.",
    "map_on_water": "GHS-LAND finds no land in this cell, but the Malaria Atlas Project still models a travel time across its surface. Unweighted mean of the pixels.",
    "land_over_100": "Above 100% because whole 1 km pixels are assigned by their centres; read as all land.",
}

EXTENT = {"worldpop": (-60.0, 84.0), "map": (-60.0, 85.0), "ghsl": (-89.1, 89.1)}


def lineage(layer: dict, src: dict | None, res: int) -> list[str]:
    if layer.get("derived") == "disagreement":
        return ["Take the GHSL (G) and WorldPop (W) population counts for the cell",
                f"Leave cells where both are below {layer['min_people']} people without a value",
                "D = 100 x (W - G) / ((W + G) / 2)"]
    steps = [f"Download {src['name']} ({src['native_grain']})",
             "Read the raster in strips of 1,200 rows" + (", reprojecting pixel centres to WGS84" if layer.get("projected") else ""),
             f"Assign each pixel to the H3 resolution-{res} cell containing its centre"]
    rule = layer["ingest"]
    if rule == "sum":
        steps.append("Sum the pixels with a modelled population above zero" if layer.get("positive_only")
                     else "Sum every pixel with a value, and count them")
        steps.append("Divide by the cell's area for density; the inspector also shows the count")
    elif rule == "weighted_mean":
        steps += ["Weight each pixel by the GHSL population at its centre (nearest GHSL pixel)",
                  "Population-weighted mean per cell; the unweighted mean where GHSL models nobody",
                  "Keep the fastest and slowest pixel in the cell as spread"]
    elif rule == "area_share":
        steps.append("Sum square metres of land and divide by the cell's area")
    steps.append("Coarser display cells add up the components of their children, then apply the same formula")
    return steps


def load_components(layers: list[dict]) -> dict[str, pd.DataFrame]:
    return {l["id"]: pd.read_parquet(INTERIM / f"{l['id']}.parquet") for l in layers if l.get("ingest")}


def rollup(comp: dict[str, pd.DataFrame], res: int) -> dict[str, pd.DataFrame]:
    out = {}
    for k, df in comp.items():
        p = parent(df.index.values.astype(np.uint64), res)
        agg = {c: ("min" if c == "mn" else "max" if c == "mx" else "sum") for c in df.columns}
        out[k] = df.groupby(p).agg(agg)
    return out


def cell_table(comp: dict[str, pd.DataFrame], res: int, min_people: int) -> pd.DataFrame:
    """Finished values for every cell that any source touches, at one resolution."""
    idx = np.unique(np.concatenate([df.index.values.astype(np.uint64) for df in comp.values()]))
    t = pd.DataFrame(index=idx)
    t["area"] = [h3.cell_area(format(int(c), "x"), "km^2") for c in idx]
    t["lat"] = [h3.cell_to_latlng(format(int(c), "x"))[0] for c in idx]
    g, w, m, land = (comp[k].reindex(idx) for k in ("pop.ghsl", "pop.worldpop", "acc.motor", "geo.land"))

    t["land_pct"] = (land.s.fillna(0) / (t.area * 1e6) * 100).round(1)
    t["land_n"] = land.n.fillna(0).astype(int)

    t["g_c"] = g.s.fillna(0.0)
    t["g_n"] = g.n.fillna(0).astype(int)
    t["g_v"] = t.g_c / t.area
    t.loc[(t.lat < EXTENT["ghsl"][0]) | (t.lat > EXTENT["ghsl"][1]), "g_v"] = np.nan

    t["w_n"] = w.n.fillna(0).astype(int)
    t["w_c"] = np.where(t.w_n > 0, w.s.fillna(0.0), np.nan)
    t["w_v"] = t.w_c / t.area

    G, W = t.g_c, t.w_c
    d = 100 * (W - G) / ((W + G) / 2)
    small = (np.fmax(G, W.fillna(0)) < min_people)
    t["d_v"] = np.where(W.notna() & ~small & t.g_v.notna(), d, np.nan)

    t["m_n"] = m.n.fillna(0).astype(int)
    weighted = m.sw.fillna(0) > 0
    t["m_v"] = np.where(weighted, m.swv / m.sw.where(weighted), np.where(t.m_n > 0, m.sv / m.n, np.nan))
    t["m_wt"] = weighted.astype(int)
    t["m_min"], t["m_max"] = m.mn, m.mx
    return t


def why(t: pd.DataFrame) -> dict[str, list]:
    """Absence reason (or note) codes per layer, aligned with the table rows."""
    lat = t.lat.values

    def ext(name):
        lo, hi = EXTENT[name]
        return (lat < lo) | (lat > hi)

    out = {}
    out["pop.ghsl"] = np.where(ext("ghsl"), "ghsl_extent",
                       np.where(t.g_c.values > 0, np.where(t.land_pct.values < 95, "ghsl_partial_water", ""),
                       np.where(t.land_n.values > 0, "ghsl_zero_land", "ghsl_zero_water")))
    out["pop.worldpop"] = np.where(t.w_n.values > 0, "", np.where(ext("worldpop"), "wp_extent", "wp_nodata"))
    out["pop.disagreement"] = np.where(~np.isnan(t.d_v.values), "",
                               np.where(np.isnan(t.w_c.values) | np.isnan(t.g_v.values), "d_missing", "d_small"))
    out["acc.motor"] = np.where(t.m_n.values > 0,
                        np.where(t.m_wt.values == 1, "", np.where(t.land_n.values > 0, "map_unweighted", "map_on_water")),
                        np.where(ext("map"), "map_extent", "map_nodata"))
    out["geo.land"] = np.where(t.land_pct.values > 100, "land_over_100", "")
    return {k: v.tolist() for k, v in out.items()}


def rnd(a, nd=1, keep=False):
    """Round for publication: nd decimals below 100, whole numbers above (unless keep)."""
    a = np.asarray(a, dtype="float64")
    return [None if not np.isfinite(x) else (round(float(x), nd) if keep or abs(x) < 100 else round(float(x))) for x in a]


VALUE_COL = {"pop.ghsl": "g_v", "pop.worldpop": "w_v", "pop.disagreement": "d_v", "acc.motor": "m_v", "geo.land": "land_pct"}


def display_payload(t: pd.DataFrame, res: int) -> dict:
    v = {k: rnd(t[c].values, 2 if k.startswith("pop.") and k != "pop.disagreement" else 1) for k, c in VALUE_COL.items()}
    v["geo.land"] = rnd(t.land_pct.values, 1, keep=True)
    return {"res": res, "cells": hexes(t.index.values), "v": v, "why": why(t)}


def inspect_payload(t: pd.DataFrame, res: int) -> dict:
    p = display_payload(t, res)
    p["v"]["pop.ghsl"] = rnd(t.g_v.values, 3)
    p["v"]["pop.worldpop"] = rnd(t.w_v.values, 3)
    p["x"] = {"g_c": rnd(t.g_c.values, 1), "g_n": t.g_n.tolist(), "w_c": rnd(t.w_c.values, 1), "w_n": t.w_n.tolist(),
              "m_n": t.m_n.tolist(), "m_min": rnd(t.m_min.values, 1), "m_max": rnd(t.m_max.values, 1),
              "land_n": t.land_n.tolist()}
    return p


def write_sharded(t: pd.DataFrame, res: int, shard_res: int, payload, folder: str) -> int:
    d = OUT / folder
    d.mkdir(parents=True, exist_ok=True)
    keys = parent(t.index.values.astype(np.uint64), shard_res) if shard_res >= 0 else None
    n = 0
    for k in np.unique(keys):
        part = t[keys == k]
        write_json(d / f"{format(int(k), 'x')}.json", payload(part, res))
        n += 1
    return n


def main() -> int:
    IND, S = load_indicators(), load_sources()
    B = IND["build"]
    layers = IND["layer"]
    min_people = next(l["min_people"] for l in layers if l["id"] == "pop.disagreement")
    res = B["inspect_res"]

    print("loading components")
    comp = load_components(layers)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    print(f"inspection cells, res {res}")
    t5 = cell_table(comp, res, min_people)
    n_shards = write_sharded(t5, res, B["shard_res"], inspect_payload, f"r{res}")
    print(f"  {len(t5):,} cells in {n_shards} files")
    counts = {"inspect": {"res": res, "cells_touched": len(t5), "files": n_shards}}

    display = {}
    for r in sorted(B["display_res"], reverse=True):
        tr = cell_table(rollup(comp, r), r, min_people)
        sr = B["display_shard_res"][str(r)]
        if sr < 0:
            write_json(OUT / f"r{r}.json", display_payload(tr, r))
            display[str(r)] = {"file": f"r{r}.json", "cells": len(tr)}
        else:
            n = write_sharded(tr, r, sr, display_payload, f"r{r}")
            display[str(r)] = {"folder": f"r{r}", "shard_res": sr, "cells": len(tr), "files": n}
        print(f"  display res {r}: {len(tr):,} cells")
    counts["display"] = display

    # ---- metadata
    def layer_meta(l):
        src = S.get(l.get("source_id", ""), None)
        g = dict(l.get("grade") or src["grade"])
        m = {k: l[k] for k in ("id", "reference", "label", "short", "unit", "period", "statistic", "depends_on",
                               "caveat", "scale", "upstream_epochs") if k in l}
        m.update({"status": l.get("status") or src["status"], "grade_detail": g, "grade": weakest(g),
                  "lineage": lineage(l, src, res), "primary": l.get("primary", False), "context": l.get("context", False)})
        if src:
            m.update({"source_id": l["source_id"], "native_grain": src["native_grain"],
                      "reference_period": src["reference_period"], "grade_notes": src.get("grade_notes", "")})
        else:
            m["sources"] = [layers_by_id[i]["source_id"] for i in l["inputs"]]
            m["native_grain"] = "Derived per cell from the two population layers"
            m["reference_period"] = S[m["sources"][0]]["reference_period"]
        if l.get("count_unit"):
            m["count_unit"] = l["count_unit"]
        return m

    layers_by_id = {l["id"]: l for l in layers}
    used = {l["source_id"] for l in layers if l.get("source_id")}
    sources = {k: {kk: vv for kk, vv in S[k].items() if kk not in ("variants", "tile_deg", "parallel", "folder", "raster")}
               for k in sorted(used)}
    manifest = read_json(MANIFEST) if MANIFEST.exists() else {}
    files = {k: {kk: v[kk] for kk in ("sha256", "bytes", "retrieved") if kk in v} | ({"server": v["server"]} if "server" in v else {})
             for k, v in manifest.items() if v.get("source_id") in used}
    digest = hashlib.sha256(json.dumps(files and {k: v["sha256"] for k, v in files.items()}, sort_keys=True).encode()).hexdigest()[:12]
    built = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    version = f"{B['as_of']}+{digest}"
    for sid, s in sources.items():
        s["grade_weakest"] = weakest(s["grade"])
        s["files"] = {k: v for k, v in files.items() if manifest[k]["source_id"] == sid}

    meta = {
        "build": {"name": B["name"], "version": version, "built": built, "as_of": B["as_of"],
                  "inspect_res": res, "display_res": B["display_res"], "shard_res": B["shard_res"]},
        "layers": [layer_meta(l) for l in layers],
        "references": IND["reference"],
        "sources": sources,
        "reasons": REASONS, "notes": NOTES, "extent": EXTENT,
        "untouched": ("No ingested source has any pixel here with land, modelled residents or a value: "
                      "GHS-LAND finds no land, GHSL models no residents, and WorldPop and the Malaria Atlas "
                      "Project make no estimate. This is open water as far as these sources can tell, "
                      "or beyond every source's extent."),
        "counts": counts,
        "totals": {"ghsl_people": round(float(t5.g_c.sum())), "worldpop_people": round(float(np.nansum(t5.w_c))),
                   "land_km2": round(float((t5.land_pct / 100 * t5.area).sum()))},
        "dimensions": ["recency", "directness", "spatial_fidelity", "coverage", "validation", "interval"],
    }
    write_json(OUT / "meta.json", meta, compact=False)

    builds = read_json(BUILDS) if BUILDS.exists() else []
    builds = [b for b in builds if b["version"] != version]
    builds.append({"version": version, "built": built, "inspect_res": res,
                   "sources": {k: {f: v["sha256"] for f, v in s["files"].items()} for k, s in sources.items()}})
    write_json(BUILDS, builds, compact=False)
    print(json.dumps({"version": version, "totals": meta["totals"], "counts": counts}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
