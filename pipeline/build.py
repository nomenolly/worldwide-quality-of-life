"""Build the H3 substrate and every observational layer for the configured region.

Reads data/raw/ (filled by fetch.py) and writes:
  data/processed/observations.csv   long table, one row per cell x indicator (WQL-001 6.2 schema)
  site/data/cells.geojson           H3 cell outlines for the map
  site/data/observations.json       the same observations, keyed for the browser
  site/data/indicators.json         indicator and source metadata, lineage, grades
  site/data/boundaries.geojson      country outlines (licence per feature)
  site/data/region.json             window, counts, boundary flags, unlocated conflict deaths

Rules that hold throughout (WQL-001 C-01..C-14, WQL-002 decisions):
  * H3 res 6 is a common index. Each value keeps its native grain, and the number
    of source pixels or events behind it.
  * Missing stays missing: a cell with no value gets status "absent" and a reason,
    never a zero or an imputed number.
  * No scores, no rankings, no composites.
"""
from __future__ import annotations

import csv
import glob
import html
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import rasterio
from rasterio.merge import merge
from rasterio.windows import from_bounds
from shapely.geometry import Point, Polygon, shape
from shapely.prepared import prep

from common import (DIMENSIONS, RAW, ROOT, SITE_DATA, load_region, load_sources,
                    weakest, write_json)

PROCESSED = ROOT / "data" / "processed"


# ---------------------------------------------------------------- substrate

def build_substrate(reg: dict, res: int) -> pd.DataFrame:
    """All res-`res` cells whose centre lies inside the window."""
    pad = 0.1
    box = h3.LatLngPoly([(reg["south"] - pad, reg["west"] - pad), (reg["south"] - pad, reg["east"] + pad),
                         (reg["north"] + pad, reg["east"] + pad), (reg["north"] + pad, reg["west"] - pad)])
    cells = []
    for c in h3.polygon_to_cells(box, res):
        lat, lng = h3.cell_to_latlng(c)
        if reg["south"] <= lat <= reg["north"] and reg["west"] <= lng <= reg["east"]:
            cells.append((c, lat, lng, h3.cell_area(c, "km^2")))
    df = pd.DataFrame(cells, columns=["cell_id", "lat", "lng", "area_km2"]).sort_values("cell_id")
    return df.set_index("cell_id")


# ---------------------------------------------------------------- raster helpers

def read_window(paths: list[str], reg: dict, pad: float = 0.1):
    """Read (and mosaic) rasters over the padded window. Returns array, transform, nodata."""
    bounds = (reg["west"] - pad, reg["south"] - pad, reg["east"] + pad, reg["north"] + pad)
    if len(paths) == 1:
        with rasterio.open(paths[0]) as r:
            win = from_bounds(*bounds, transform=r.transform).round_offsets().round_lengths()
            arr = r.read(1, window=win)
            return arr, r.window_transform(win), r.nodata
    srcs = [rasterio.open(p) for p in paths]
    arr, transform = merge(srcs, bounds=bounds)
    nodata = srcs[0].nodata
    for s in srcs:
        s.close()
    return arr[0], transform, nodata


def pixel_centres(arr: np.ndarray, transform):
    rows, cols = np.indices(arr.shape)
    lng = transform.c + (cols + 0.5) * transform.a
    lat = transform.f + (rows + 0.5) * transform.e
    return lat.ravel(), lng.ravel()


def assign_cells(lat: np.ndarray, lng: np.ndarray, res: int) -> np.ndarray:
    return np.array([h3.latlng_to_cell(a, b, res) for a, b in zip(lat, lng)], dtype=object)


def sample(arr: np.ndarray, transform, lat: np.ndarray, lng: np.ndarray, nodata=None) -> np.ndarray:
    """Nearest-pixel sample of `arr` at points (used to weight one grid by another)."""
    col = np.floor((lng - transform.c) / transform.a).astype(int)
    row = np.floor((lat - transform.f) / transform.e).astype(int)
    ok = (row >= 0) & (row < arr.shape[0]) & (col >= 0) & (col < arr.shape[1])
    out = np.full(lat.shape, np.nan)
    out[ok] = arr[row[ok], col[ok]]
    if nodata is not None:
        out[out == nodata] = np.nan
    return out


def raster_frame(paths, reg, res, value_name="v"):
    arr, transform, nodata = read_window(paths, reg)
    lat, lng = pixel_centres(arr, transform)
    v = arr.ravel().astype("float64")
    if nodata is not None:
        v[v == nodata] = np.nan
    df = pd.DataFrame({"lat": lat, "lng": lng, value_name: v})
    df["cell_id"] = assign_cells(lat, lng, res)
    return df, arr, transform, nodata


# ---------------------------------------------------------------- boundaries

def load_boundaries(reg):
    shapes, feats = {}, []
    for iso in reg["countries"]:
        meta = json.loads((RAW / "geoboundaries" / f"{iso}-ADM0-meta.json").read_text())
        gj = json.loads((RAW / "geoboundaries" / f"{iso}-ADM0.geojson").read_text())
        geom = shape(gj["features"][0]["geometry"]).buffer(0)
        shapes[iso] = geom
        feats.append({"type": "Feature",
                      "properties": {"iso": iso, "name": meta.get("boundaryName", iso),
                                     "licence": meta["boundaryLicense"], "source": meta["boundarySource"],
                                     "year": meta.get("boundaryYearRepresented"),
                                     "build_date": meta.get("buildDate")},
                      "geometry": gj["features"][0]["geometry"]})
    return shapes, feats


# Disputes known from public reporting that fall inside the window. This list is
# NOT authoritative and is not drawn from a neutral register (WQL-001 R-07).
KNOWN_DISPUTES = [
    {"name": "Migingo Island", "claimants": ["KEN", "UGA"], "lat": -0.883, "lng": 33.95,
     "note": "Small island in Lake Victoria claimed by Kenya and Uganda. Point location approximate."},
]
REGISTERED_NOT_PLACED = [
    {"name": "Rukwanzi Island (Lake Albert)", "claimants": ["COD", "UGA"],
     "note": "Reported DRC-Uganda dispute. Location not yet verified, so it is not placed on the map."},
]


def country_assignment(cells: pd.DataFrame, shapes: dict) -> pd.DataFrame:
    """Which country outlines cover each cell, by share of cell area.

    A cell is attached to every outline covering at least 1% of it, largest
    first. Where two outlines overlap inside a cell by more than 1% of its area,
    the independently sourced outlines disagree, and the cell is flagged. That
    is a disagreement between boundary files, not necessarily a political dispute.
    """
    prepared = {k: prep(v) for k, v in shapes.items()}
    rows = []
    for cid in cells.index:
        poly = Polygon([(b, a) for a, b in h3.cell_to_boundary(cid)])
        area = poly.area
        parts = {}
        for k, p in prepared.items():
            if p.intersects(poly):
                parts[k] = shapes[k].intersection(poly)
        shares = sorted(((k, g.area / area) for k, g in parts.items()), key=lambda t: -t[1])
        shares = [(k, round(sh, 3)) for k, sh in shares if sh >= 0.01]
        overlap = 0.0
        keys = list(parts)
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                overlap = max(overlap, parts[keys[i]].intersection(parts[keys[j]]).area / area)
        land_share = round(min(1.0, sum(sh for _, sh in shares)), 3)
        rows.append((cid, [k for k, _ in shares], shares, land_share, overlap > 0.01, len(shares) > 1, not shares))
    return pd.DataFrame(rows, columns=["cell_id", "countries", "shares", "outline_share", "boundary_disagreement",
                                       "border_cell", "no_country"]).set_index("cell_id")


def dispute_cells(res):
    return {h3.latlng_to_cell(d["lat"], d["lng"], res): d for d in KNOWN_DISPUTES}


# ---------------------------------------------------------------- census (UNSD transcription)

CENSUS_NAMES = {"BDI": "Burundi", "COD": "Democratic Republic of the Congo", "KEN": "Kenya",
                "RWA": "Rwanda", "UGA": "Uganda", "TZA": "United Republic of Tanzania"}


def parse_census_dates():
    """Most recent completed census per country from the UNSD page.

    The page lists one cell per census round; future dates are in parentheses.
    Returns {iso: {"year": int|None, "text": str, "note": str}}.
    """
    t = (RAW / "unsd" / "censusdates.html").read_text(encoding="utf-8", errors="replace")
    txt = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", t)))
    out = {}
    for iso, name in CENSUS_NAMES.items():
        m = re.search(r"\| " + re.escape(name) + r" \|(.{0,400})", txt)
        seg = (m.group(1) if m else "").replace("(P)", "")  # (P): footnote marker, not a date
        # stop at the next country row: rows end with the planned-date cell "(...)" or "(date)"
        seg = seg.split(")", 1)[0] + ")" if ")" in seg else seg
        done = [y for y in re.findall(r"(?<!\()\b(19[89]\d|20[0-2]\d)\b(?![^()]*\))", seg)]
        if done:
            y = int(done[-1])
            out[iso] = {"year": y, "lower_bound": False, "text": seg.strip(" |"),
                        "note": f"Last census {y} (UNSD)."}
        else:
            out[iso] = {"year": 1984, "lower_bound": True, "text": seg.strip(" |"),
                        "note": "No census in the 1990, 2000, 2010 or 2020 rounds on the UNSD page. "
                                "1984 is reported elsewhere and is not yet confirmed, so the age is a lower bound."}
    return out


# ---------------------------------------------------------------- main build

def main() -> int:
    R = load_region()
    reg, res, as_of = R["region"], R["substrate"]["h3_resolution"], R["reference"]["as_of_year"]
    S = load_sources()

    print("substrate")
    cells = build_substrate(reg, res)
    print(f"  {len(cells)} res-{res} cells")

    print("boundaries")
    shapes, boundary_feats = load_boundaries(reg)
    ca = country_assignment(cells, shapes)
    disputes = dispute_cells(res)

    obs: dict[str, dict[str, dict]] = defaultdict(dict)  # obs[cell][indicator] = record

    def absent(cid, ind, reason):
        obs[cid][ind] = {"st": "absent", "why": reason}

    # ---- population: GHSL (primary)
    print("population: GHSL")
    ghsl_paths = sorted(glob.glob(str(RAW / "ghsl" / "*.tif")))
    gdf, g_arr, g_tr, _ = raster_frame(ghsl_paths, reg, res)
    gsum = gdf.groupby("cell_id").v.agg(["sum", "count"])
    # ---- population: WorldPop (secondary)
    print("population: WorldPop")
    wdf, _, _, _ = raster_frame(glob.glob(str(RAW / "worldpop" / "*.tif")), reg, res)
    wagg = wdf.groupby("cell_id").v.agg(["sum", "count"])
    w_valid = wdf.assign(ok=wdf.v.notna()).groupby("cell_id").ok.sum()

    census = parse_census_dates()

    for cid in cells.index:
        if cid in gsum.index and gsum.loc[cid, "count"] > 0:
            obs[cid]["pop.ghsl"] = {"v": round(float(gsum.loc[cid, "sum"]), 1), "st": "modelled",
                                    "n": int(gsum.loc[cid, "count"])}
        else:
            absent(cid, "pop.ghsl", "No GHSL pixels in this cell.")
        if cid in wagg.index and w_valid.get(cid, 0) > 0:
            obs[cid]["pop.worldpop"] = {"v": round(float(wagg.loc[cid, "sum"]), 1), "st": "modelled",
                                        "n": int(w_valid[cid])}
        else:
            absent(cid, "pop.worldpop", "WorldPop has no data here (constrained product: no mapped settlement, or water).")

    # Per-cell recency for population: lowered where the country's census is old.
    def census_recency(cid):
        cs = ca.loc[cid, "countries"]
        if not cs:
            return None
        ages = [as_of - census[c]["year"] for c in cs]
        age = max(ages)
        return "A" if age <= 5 else "B" if age <= 10 else "C" if age <= 15 else "D"

    for cid in cells.index:
        rg = census_recency(cid)
        for ind in ("pop.ghsl", "pop.worldpop"):
            if obs[cid][ind]["st"] != "absent" and rg in ("C", "D"):
                obs[cid][ind]["g"] = {"recency": rg}

    # ---- population disagreement (indicator 14)
    print("population disagreement")
    MIN_PEOPLE = 100
    for cid in cells.index:
        g, w = obs[cid]["pop.ghsl"], obs[cid]["pop.worldpop"]
        if g["st"] == "absent" or w["st"] == "absent":
            absent(cid, "pop.disagreement", "One of the two population sources has no value here.")
            continue
        G, W = g["v"], w["v"]
        if max(G, W) < MIN_PEOPLE:
            absent(cid, "pop.disagreement", f"Both sources estimate fewer than {MIN_PEOPLE} people; a percentage difference would mostly be noise.")
            continue
        d = (W - G) / ((W + G) / 2) * 100
        obs[cid]["pop.disagreement"] = {"v": round(d, 1), "st": "derived", "x": {"ghsl": G, "worldpop": W}}

    # ---- urbanisation: GHS-SMOD, population share by settlement class
    print("urbanisation: GHS-SMOD")
    smod_paths = sorted(glob.glob(str(RAW / "ghsl_smod" / "*.tif")))
    sdf, _, _, _ = raster_frame(smod_paths, reg, res, value_name="cls")
    # SMOD and GHS-POP 30ss tiles share one grid (checked: same origin and pixel size),
    # so the population weight is the GHSL pixel at the same position.
    sdf["pop"] = gdf.v.values if len(gdf) == len(sdf) and np.allclose(gdf.lat, sdf.lat) else sample(
        g_arr, g_tr, sdf.lat.values, sdf.lng.values)
    group = {30: "urban_centre", 23: "urban_cluster", 22: "urban_cluster", 21: "urban_cluster",
             13: "rural", 12: "rural", 11: "rural", 10: "water"}
    sdf["grp"] = sdf.cls.map(lambda c: group.get(int(c), "nodata") if not np.isnan(c) else "nodata")
    for cid, part in sdf.groupby("cell_id"):
        if cid not in cells.index:
            continue
        p = part.groupby("grp").pop.sum()
        n_cls = part.grp.value_counts()
        tot = float(p.drop(labels=["water", "nodata"], errors="ignore").sum())
        if tot <= 0:
            if n_cls.get("water", 0) == len(part):
                absent(cid, "urb.share", "Water: the settlement model classes every pixel here as water.")
            else:
                absent(cid, "urb.share", "No resident population, so a population share is undefined.")
            continue
        shares = {k: round(float(p.get(k, 0.0)) / tot * 100, 1) for k in ("urban_centre", "urban_cluster", "rural")}
        obs[cid]["urb.share"] = {"v": round(shares["urban_centre"] + shares["urban_cluster"], 1),
                                 "st": "modelled", "n": int(len(part)), "x": shares}
    for cid in cells.index:
        obs[cid].setdefault("urb.share", {"st": "absent", "why": "No settlement-model pixels in this cell."})

    # ---- travel time to healthcare: population-weighted mean of pixels
    print("travel time: MAP")
    tt = {}
    for key, fname in [("acc.motor", "Motorized_Travel_Time_to_Healthcare.tif"),
                       ("acc.walk", "Walking_Only_Travel_Time_To_Healthcare.tif")]:
        tdf, _, _, _ = raster_frame([str(RAW / "map" / fname)], reg, res)
        tdf["pop"] = sample(g_arr, g_tr, tdf.lat.values, tdf.lng.values)
        tt[key] = tdf
        for cid, part in tdf.groupby("cell_id"):
            if cid not in cells.index:
                continue
            vals = part.dropna(subset=["v"])
            if vals.empty:
                absent(cid, key, "MAP has no value here (water or outside the modelled land surface).")
                continue
            w = vals["pop"].fillna(0).values
            if w.sum() > 0:
                v, how = float(np.average(vals.v, weights=w)), "population-weighted"
            else:
                v, how = float(vals.v.mean()), "unweighted (no resident population)"
            note = ({"note": "Open water: MAP models a travel time across the water surface; nobody lives here."}
                    if obs[cid].get("urb.share", {}).get("why", "").startswith("Water") else {})
            obs[cid][key] = {"v": round(v, 1), "st": "modelled", "n": int(len(vals)),
                             "x": {"min": round(float(vals.v.min()), 1), "max": round(float(vals.v.max()), 1),
                                   "weighting": how, "pixels_missing": int(len(part) - len(vals)), **note}}
        for cid in cells.index:
            obs[cid].setdefault(key, {"st": "absent", "why": "No MAP pixels in this cell."})

    # ---- conflict deaths: UCDP GED 26.1, 2021-2025, safely aggregated
    print("conflict: UCDP GED")
    period = S["ucdp_ged_261"]["reference_period"]
    y0, y1 = int(period[0][:4]), int(period[1][:4])
    ged = pd.read_csv(glob.glob(str(RAW / "ucdp" / "GEDEvent_v26_1.csv"))[0], low_memory=False,
                      usecols=["year", "where_prec", "latitude", "longitude", "best", "low", "high",
                               "country", "type_of_violence"])
    ged = ged[(ged.year >= y0) & (ged.year <= y1)
              & ged.latitude.between(reg["south"], reg["north"]) & ged.longitude.between(reg["west"], reg["east"])]
    located = ged[ged.where_prec <= 2].copy()
    located["cell_id"] = assign_cells(located.latitude.values, located.longitude.values, res)
    # Upstream quirk: in about 1% of GED events the high estimate is below best, or low above best.
    # They are kept as published and counted, not corrected.
    located["inconsistent"] = (located.high < located.best) | (located.low > located.best)
    unlocated = (ged[ged.where_prec > 2].groupby(["country", "where_prec"])
                 .agg(events=("best", "size"), deaths_best=("best", "sum"),
                      deaths_low=("low", "sum"), deaths_high=("high", "sum")).reset_index())
    cagg = located.groupby("cell_id").agg(best=("best", "sum"), low=("low", "sum"), high=("high", "sum"),
                                          events=("best", "size"),
                                          prec2=("where_prec", lambda s: int((s == 2).sum())),
                                          inconsistent=("inconsistent", "sum"))
    for cid in cells.index:
        if cid in cagg.index:
            r = cagg.loc[cid]
            rec = {"v": int(r.best), "lo": int(r.low), "hi": int(r.high), "st": "measured",
                   "n": int(r.events), "x": {"events_within_25km": int(r.prec2)}}
            if r.inconsistent:
                rec["x"]["note"] = (f"{int(r.inconsistent)} event(s) here have UCDP high/low estimates on the wrong side of "
                                    "the best estimate, as published. The interval is shown unaltered.")
            if r.prec2 > 0:
                rec["g"] = {"spatial_fidelity": "C"}
            obs[cid]["sec.conflict"] = rec
        else:
            # Zero recorded deaths is a measurement of the record, not of peace.
            obs[cid]["sec.conflict"] = {"v": 0, "lo": 0, "hi": 0, "st": "measured", "n": 0,
                                        "x": {"note": "No UCDP-recorded fatal event located in this cell."}}

    # ---- years since census (indicator 13): a national fact on every cell
    print("census age")
    for cid in cells.index:
        cs = ca.loc[cid, "countries"]
        if not cs:
            absent(cid, "kno.census_age", "No country outline covers this cell (open water in the simplified outlines).")
            continue
        parts = {c: {"year": census[c]["year"], "age": as_of - census[c]["year"],
                     "lower_bound": census[c]["lower_bound"]} for c in cs}
        main = parts[cs[0]]  # the country covering the largest share of the cell
        rec = {"v": main["age"], "st": "measured", "x": {"countries": parts, "shown": cs[0]}}
        if main["lower_bound"]:
            rec["st"] = "lower bound"
            rec["lo"] = main["age"]
        obs[cid]["kno.census_age"] = rec

    # ---------------------------------------------------------------- indicator metadata
    def meta(ind, label, domain, unit, sid, lineage, caveat, scale, extra=None, grade=None, status=None):
        src = S[sid]
        g = dict(grade or src["grade"])
        m = {"id": ind, "label": label, "domain": domain, "unit": unit, "source_id": sid,
             "period": src.get("reference_period"), "native_grain": src["native_grain"],
             "status": status or src["status"], "lineage": lineage, "grade_detail": g,
             "grade": weakest(g), "caveat": caveat, "scale": scale}
        if extra:
            m.update(extra)
        return m

    pixel_lineage = ["Read the 30 arc-second raster over the window (+0.1° pad)",
                     "Assign each pixel to the H3 res-6 cell containing the pixel centre"]
    indicators = [
        meta("pop.ghsl", "Population (GHSL, primary)", "Context: population", "people", "ghsl_pop_2020",
             pixel_lineage + ["Sum pixel populations per cell"],
             "Modelled residential population for 2020. Not a count. Pixel-centre assignment means cells on the edge of a dense town can gain or lose a few hundred people relative to an exact area-weighted split.",
             {"type": "log", "palette": "seq"}),
        meta("pop.worldpop", "Population (WorldPop, secondary)", "Context: population", "people", "worldpop_2020",
             pixel_lineage + ["Sum pixel populations per cell"],
             "Constrained product: people are placed only where settlement is mapped, so many rural cells are empty here but not in GHSL. National totals are adjusted to UN estimates.",
             {"type": "log", "palette": "seq"}),
        meta("pop.disagreement", "Population disagreement (WorldPop vs GHSL)", "Knowledge: data quality", "% of mean",
             "worldpop_2020",
             ["Take pop.ghsl and pop.worldpop for the cell",
              f"Skip cells where both are below {MIN_PEOPLE} people",
              "Compute (WorldPop - GHSL) / mean(WorldPop, GHSL) x 100"],
             "A measure of how far two reputable models disagree, not of which is right. Positive means WorldPop places more people here than GHSL.",
             {"type": "diverging", "palette": "div", "domain": [-200, 200]},
             grade={"recency": "B", "directness": "C", "spatial_fidelity": "A", "coverage": "B",
                    "validation": "C", "interval": "D"}, status="derived",
             extra={"sources": ["ghsl_pop_2020", "worldpop_2020"]}),
        meta("urb.share", "Urban population share (GHS-SMOD)", "Context: settlement", "% of cell population",
             "ghsl_smod_2020",
             pixel_lineage + ["Weight each pixel by its GHS-POP 2020 population (same grid)",
                              "Urban share = population in urban centres (class 30) + urban clusters (21-23), over all non-water population"],
             "Degree of Urbanisation classes are a harmonised international definition, not national definitions of 'urban'. The inspector shows the urban centre / urban cluster / rural split.",
             {"type": "linear", "palette": "seq", "domain": [0, 100]}),
        meta("acc.motor", "Travel time to nearest health facility, motorised", "Health access", "minutes",
             "map_travel_2020",
             ["Request the 30 arc-second WCS subset for the window (+0.5° pad)"] + pixel_lineage[1:] +
             ["Weight each pixel by GHS-POP 2020 sampled at the pixel centre (nearest pixel)",
              "Population-weighted mean per cell; unweighted mean where nobody lives"],
             "Modelled best-case travel time assuming motorised transport is available. Says nothing about facility quality, staffing, cost or opening hours. The inspector shows the within-cell minimum and maximum, which is spread, not uncertainty.",
             {"type": "log", "palette": "seq"}),
        meta("acc.walk", "Travel time to nearest health facility, walking only", "Health access", "minutes",
             "map_travel_2020",
             ["Request the 30 arc-second WCS subset for the window (+0.5° pad)"] + pixel_lineage[1:] +
             ["Weight each pixel by GHS-POP 2020 sampled at the pixel centre (nearest pixel)",
              "Population-weighted mean per cell; unweighted mean where nobody lives"],
             "Modelled walking time with no vehicle. Same facility list and caveats as the motorised layer.",
             {"type": "log", "palette": "seq"}),
        meta("sec.conflict", f"Deaths in organised violence, {y0}-{y1} (UCDP GED)", "Physical security",
             "deaths (5-year total)", "ucdp_ged_261",
             [f"Keep events dated {y0}-{y1} with coordinates inside the window",
              "Keep events located exactly (precision 1) or within 25 km of a known point (precision 2)",
              "Assign each event to the H3 res-6 cell containing its coded point",
              "Sum best, low and high death estimates per cell over the five years",
              "Events located only to an administrative area or coarser are counted per country, not placed"],
             "Recorded deaths in state-based, non-state and one-sided violence with at least 25 deaths per year in the conflict or dyad. A zero means no recorded event, not no violence. Precision-2 events may have happened up to 25 km away, i.e. in a neighbouring cell. Only five-year cell totals are published; no event-level detail is shown.",
             {"type": "log", "palette": "seq"},
             extra={"interval_meaning": "UCDP low and high death estimates, summed"}),
        meta("kno.census_age", "Years since the last population census", "Knowledge: data quality", "years",
             "unsd_census_dates",
             ["Transcribe the most recent completed census per country from the UNSD page",
              f"Years since = {as_of} - census year",
              "Attach to every cell that a country's geoBoundaries outline covers (at least 1% of the cell)",
              "A cell covered by two or more outlines shows the country covering most of it; the inspector lists the others"],
             "A national fact spread over every cell, so it is the same for a capital and a remote valley. It matters because every population model above is anchored to these censuses.",
             {"type": "linear", "palette": "seq", "domain": [0, 45]}),
    ]
    ind_ids = [m["id"] for m in indicators]

    # ---------------------------------------------------------------- outputs
    print("writing outputs")
    PROCESSED.mkdir(parents=True, exist_ok=True)
    ind_by_id = {m["id"]: m for m in indicators}
    with open(PROCESSED / "observations.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cell_id", "indicator_id", "period_start", "period_end", "value", "lower", "upper",
                    "status", "grade", "grade_detail", "source_id", "pop_weight",
                    "n_source_units", "note"])
        for cid in cells.index:
            pw = obs[cid]["pop.ghsl"].get("v", "")
            for ind in ind_ids:
                o, m = obs[cid][ind], ind_by_id[ind]
                gd = {**m["grade_detail"], **o.get("g", {})}
                w.writerow([cid, ind, (m["period"] or ["", ""])[0], (m["period"] or ["", ""])[1],
                            o.get("v", ""), o.get("lo", ""), o.get("hi", ""), o["st"],
                            weakest(gd) if o["st"] != "absent" else "",
                            json.dumps(gd, separators=(",", ":")) if o["st"] != "absent" else "",
                            m["source_id"], pw, o.get("n", ""), o.get("why", "")])
    # Lineage is per indicator, so it is written once rather than on 75,000 rows.
    with open(PROCESSED / "indicators.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["indicator_id", "label", "unit", "source_id", "status", "native_grain", "grade",
                    "grade_detail", "lineage", "caveat"])
        for m in indicators:
            w.writerow([m["id"], m["label"], m["unit"], m["source_id"], m["status"], m["native_grain"], m["grade"],
                        json.dumps(m["grade_detail"], separators=(",", ":")), " > ".join(m["lineage"]), m["caveat"]])

    features = []
    for cid in cells.index:
        ring = [[round(b, 5), round(a, 5)] for a, b in h3.cell_to_boundary(cid)]
        ring.append(ring[0])
        features.append({"type": "Feature", "id": cid, "properties": {"id": cid},
                         "geometry": {"type": "Polygon", "coordinates": [ring]}})
    write_json(SITE_DATA / "cells.geojson", {"type": "FeatureCollection", "features": features})

    cell_out = {}
    for cid in cells.index:
        a = ca.loc[cid]
        flags = {"countries": a.countries, "shares": a.shares, "outline_share": a.outline_share}
        if a.boundary_disagreement:
            flags["boundary_disagreement"] = True
        if a.no_country:
            flags["no_country"] = True
        if cid in disputes:
            flags["known_dispute"] = disputes[cid]["name"]
        cell_out[cid] = {"o": {ind: obs[cid][ind] for ind in ind_ids}, "f": flags,
                         "c": [round(cells.loc[cid, "lat"], 4), round(cells.loc[cid, "lng"], 4)],
                         "a": round(cells.loc[cid, "area_km2"], 2)}
    write_json(SITE_DATA / "observations.json", cell_out)

    sources_out = {k: {kk: vv for kk, vv in v.items() if kk not in ("tiles", "variants")} for k, v in S.items()}
    for v in sources_out.values():
        if "grade" in v:
            v["grade_weakest"] = weakest(v["grade"])
    write_json(SITE_DATA / "indicators.json", {"indicators": indicators, "sources": sources_out,
                                              "dimensions": DIMENSIONS}, compact=False)
    write_json(SITE_DATA / "boundaries.geojson", {"type": "FeatureCollection", "features": boundary_feats})

    absent_counts = {ind: sum(1 for cid in cells.index if obs[cid][ind]["st"] == "absent") for ind in ind_ids}
    region_out = {
        "region": reg, "h3_resolution": res, "as_of_year": as_of, "n_cells": len(cells),
        "mean_cell_area_km2": round(float(cells.area_km2.mean()), 2),
        "absent_counts": absent_counts,
        "boundary": {"cells_where_outlines_overlap": int(ca.boundary_disagreement.sum()),
                     "cells_in_no_outline": int(ca.no_country.sum()),
                     "border_cells": int(ca.border_cell.sum()),
                     "known_disputes": KNOWN_DISPUTES, "registered_not_placed": REGISTERED_NOT_PLACED},
        "census": census,
        "conflict": {"period": [y0, y1], "events_in_window": int(len(ged)),
                     "events_placed": int(len(located)), "deaths_placed_best": int(located.best.sum()),
                     "unlocated": unlocated.to_dict(orient="records")},
        "population_totals": {"ghsl": round(float(sum(obs[c]["pop.ghsl"].get("v", 0) for c in cells.index))),
                              "worldpop": round(float(sum(obs[c]["pop.worldpop"].get("v", 0) for c in cells.index)))},
    }
    write_json(SITE_DATA / "region.json", region_out, compact=False)
    print(json.dumps({k: region_out[k] for k in ("n_cells", "absent_counts", "boundary", "population_totals")}
                     | {"conflict": {k: v for k, v in region_out["conflict"].items() if k != "unlocated"}},
                     indent=1, default=str)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
