"""Ask the global build what it knows about any place on Earth (WQL-003 proof of concept).

    python3 pipeline/locate.py -1.29 36.82          # latitude, longitude
    python3 pipeline/locate.py 0 -150 --json

Reads only the published files in site/global/data, exactly as the map's
locality inspector does, and prints every ingested observation for the
place's H3 cell, then every reference indicator that is not known, and why.
"""
from __future__ import annotations

import argparse
import json
import sys

import h3

from common import ROOT, read_json

DATA = ROOT / "site" / "global" / "data"


def locate(lat: float, lng: float) -> dict:
    meta = read_json(DATA / "meta.json")
    B = meta["build"]
    cell = h3.latlng_to_cell(lat, lng, B["inspect_res"])
    shard = h3.cell_to_parent(cell, B["shard_res"])
    path = DATA / f"r{B['inspect_res']}" / f"{shard}.json"
    rec = None
    if path.exists():
        d = read_json(path)
        if cell in d["cells"]:
            i = d["cells"].index(cell)
            rec = {"v": {k: v[i] for k, v in d["v"].items()}, "x": {k: v[i] for k, v in d["x"].items()},
                   "why": {k: v[i] for k, v in d["why"].items()}}
    clat, clng = h3.cell_to_latlng(cell)
    out = {"query": [lat, lng], "cell": cell, "res": B["inspect_res"], "cell_centre": [round(clat, 4), round(clng, 4)],
           "cell_area_km2": round(h3.cell_area(cell, "km^2"), 1), "build": B["version"], "known": [], "not_known": []}
    if rec is None:
        out["untouched"] = meta["untouched"]
    for L in meta["layers"]:
        if rec is None:
            v, code = (0.0, "ghsl_zero_water") if L["id"] == "pop.ghsl" else (0.0, "") if L["id"] == "geo.land" else (None, None)
            if L["id"] == "pop.worldpop":
                code = "wp_extent" if not (-60 <= clat <= 84) else "wp_nodata"
            elif L["id"] == "acc.motor":
                code = "map_extent" if not (-60 <= clat <= 85) else "map_nodata"
            elif L["id"] == "pop.disagreement":
                code = "d_missing"
        else:
            v, code = rec["v"][L["id"]], rec["why"][L["id"]]
        entry = {"layer": L["id"], "label": L["label"], "unit": L["unit"], "period": L["period"],
                 "status": L["status"] if v is not None else "absent", "evidence_flag": L["grade"]}
        if v is None:
            entry["why"] = meta["reasons"].get(code, code)
            out["not_known"].append(entry)
        else:
            entry["value"] = v
            if code:
                entry["note"] = meta["notes"].get(code, code)
            if rec and L["id"] == "pop.ghsl":
                entry["people"] = rec["x"]["g_c"]
            if rec and L["id"] == "pop.worldpop":
                entry["people"] = rec["x"]["w_c"]
            if rec and L["id"] == "acc.motor":
                entry["spread_minutes"] = [rec["x"]["m_min"], rec["x"]["m_max"]]
            out["known"].append(entry)
    for R in meta["references"]:
        if R["status"] != "ingested":
            out["not_known"].append({"reference": R["label"], "status": R["status"], "why": R["reason"]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("lat", type=float)
    ap.add_argument("lng", type=float)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = locate(a.lat, a.lng)
    if a.json:
        print(json.dumps(r, indent=1, ensure_ascii=False))
        return 0
    print(f"{a.lat}, {a.lng} -> H3 res {r['res']} cell {r['cell']} ({r['cell_area_km2']} km²), build {r['build']}")
    if "untouched" in r:
        print(f"  {r['untouched']}")
    print("Known:")
    for e in r["known"]:
        extra = f" ({e['people']:,} people)" if e.get("people") is not None else ""
        extra += f", within-cell spread {e['spread_minutes'][0]}-{e['spread_minutes'][1]} min" if e.get("spread_minutes") else ""
        print(f"  {e['label']}: {e['value']} {e['unit']}{extra} [{e['status']}, {e['period']}, flag {e['evidence_flag']}]")
        if e.get("note"):
            print(f"      note: {e['note']}")
    print("Not known:")
    for e in r["not_known"]:
        print(f"  {e.get('label') or e.get('reference')} [{e['status']}]: {e['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
