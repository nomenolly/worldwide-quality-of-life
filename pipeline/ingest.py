"""Repeatable ingestion: aggregate any global raster onto H3 cells (WQL-003 step 4).

Every [[layer]] in config/indicators.toml with an `ingest` rule goes through
the same steps:

  1. read the source raster(s) in horizontal strips (whole files never sit in memory)
  2. take each pixel's centre, in WGS84 (reprojecting from the source CRS if needed)
  3. assign the pixel to the H3 cell, at the inspection resolution, containing that centre
  4. accumulate per-cell *components* (sums, counts, weighted sums, min, max)

Components rather than finished values are stored so that coarser display
resolutions can be computed exactly by adding children together, and so that
the build can decide what a missing component means for each layer.

Rules (`ingest`):
  sum            s = sum of values, n = pixels summed. With positive_only, only
                 pixels > 0 count (for sources that write 0 on water and on empty
                 land alike). With count_valid, n counts every pixel with a value,
                 zeros included (for sources whose no-value is meaningful).
  weighted_mean  swv, sw = sums of value x weight and of weight, where the weight
                 is another layer's raster sampled at the pixel centre (nearest
                 pixel); sv, n for the unweighted fallback; mn, mx = spread.
  area_share     s = sum of the values, read as square metres of a surface type;
                 the build divides by cell area.

Output: data/interim/global/<layer>.parquet, indexed by H3 cell (uint64).
"""
from __future__ import annotations

import argparse
import glob
import sys
import time

import numpy as np
import pandas as pd
import rasterio
from h3ronpy.vector import coordinates_to_cells
from pyproj import Transformer
from rasterio.windows import Window

from common import RAW, ROOT, load_indicators, load_sources

INTERIM = ROOT / "data" / "interim" / "global"
STRIP_ROWS = 1200


def raster_paths(src: dict) -> list[str]:
    folder = RAW / src["folder"]
    if src["fetch"] == "file":
        return [str(folder / src["raster"])]
    return sorted(glob.glob(str(folder / "**" / "*.tif"), recursive=True))


def to_cells(lat: np.ndarray, lng: np.ndarray, res: int) -> np.ndarray:
    return np.asarray(coordinates_to_cells(lat, lng, res), dtype=np.uint64)


def strips(path: str):
    """Yield (values, lat, lng) per strip, flattened, with pixel centres in WGS84."""
    with rasterio.open(path) as r:
        projected = not r.crs.is_geographic
        tf = Transformer.from_crs(r.crs, "EPSG:4326", always_xy=True) if projected else None
        t = r.transform
        cols = np.arange(r.width)
        for row0 in range(0, r.height, STRIP_ROWS):
            h = min(STRIP_ROWS, r.height - row0)
            arr = r.read(1, window=Window(0, row0, r.width, h))
            yield arr, r.nodata, row0, t, cols, tf


def centres(row0, h, t, cols, tf, mask):
    rr, cc = np.nonzero(mask)
    x = t.c + (cc + 0.5) * t.a
    y = t.f + (rr + row0 + 0.5) * t.e
    if tf is not None:
        x, y = tf.transform(x, y)
    return y, x  # lat, lng


class WeightSampler:
    """Nearest-pixel sampling of a weight raster (e.g. GHSL population) at given points."""

    def __init__(self, path: str):
        self.r = rasterio.open(path)
        self.t = self.r.transform

    def sample(self, lat: np.ndarray, lng: np.ndarray) -> np.ndarray:
        col = np.floor((lng - self.t.c) / self.t.a).astype(np.int64)
        row = np.floor((lat - self.t.f) / self.t.e).astype(np.int64)
        out = np.zeros(lat.shape)
        ok = (row >= 0) & (row < self.r.height) & (col >= 0) & (col < self.r.width)
        if not ok.any():
            return out
        r0, r1 = row[ok].min(), row[ok].max() + 1
        c0, c1 = col[ok].min(), col[ok].max() + 1
        win = self.r.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype("float64")
        out[ok] = win[row[ok] - r0, col[ok] - c0]
        if self.r.nodata is not None:
            out[out == self.r.nodata] = 0.0
        return np.clip(out, 0, None)


def group(cells: np.ndarray, **cols) -> pd.DataFrame:
    """Per-cell sums (and min/max for mn/mx) of the given columns."""
    df = pd.DataFrame({"cell": cells, **cols})
    agg = {k: ("min" if k == "mn" else "max" if k == "mx" else "sum") for k in cols}
    return df.groupby("cell").agg(agg)


def combine(parts: list[pd.DataFrame]) -> pd.DataFrame:
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts)
    agg = {k: ("min" if k == "mn" else "max" if k == "mx" else "sum") for k in df.columns}
    return df.groupby(level=0).agg(agg)


def ingest_layer(layer: dict, S: dict, layers_by_id: dict, res: int) -> pd.DataFrame:
    src = S[layer["source_id"]]
    rule = layer["ingest"]
    sampler = None
    if rule == "weighted_mean":
        wsrc = S[layers_by_id[layer["weight"]]["source_id"]]
        sampler = WeightSampler(raster_paths(wsrc)[0])
    parts = []
    for path in raster_paths(src):
        for arr, nodata, row0, t, cols, tf in strips(path):
            valid = np.isfinite(arr) if arr.dtype.kind == "f" else np.ones(arr.shape, bool)
            if nodata is not None:
                valid &= arr != nodata
            if rule == "sum" and layer.get("positive_only"):
                mask = valid & (arr > 0)
            elif rule == "area_share":
                mask = valid & (arr > 0)
            else:
                mask = valid
            if not mask.any():
                continue
            lat, lng = centres(row0, arr.shape[0], t, cols, tf, mask)
            ok = np.isfinite(lat) & np.isfinite(lng)
            v = arr[mask].astype("float64")[ok]
            lat, lng = lat[ok], lng[ok]
            cells = to_cells(lat, lng, res)
            if rule in ("sum", "area_share"):
                parts.append(group(cells, s=v, n=np.ones(len(v), np.int64)))
            elif rule == "weighted_mean":
                w = sampler.sample(lat, lng)
                parts.append(group(cells, swv=v * w, sw=w, sv=v, n=np.ones(len(v), np.int64), mn=v, mx=v))
            else:
                raise ValueError(f"{layer['id']}: unknown ingest rule {rule}")
        print(f"    {path.rsplit('/', 1)[1]}: {sum(len(p) for p in parts):,} partial rows")
        parts = [combine(parts)]
    return combine(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="*", help="layer ids to ingest (default: every layer with an ingest rule)")
    args = ap.parse_args()
    IND, S = load_indicators(), load_sources()
    res = IND["build"]["inspect_res"]
    layers_by_id = {l["id"]: l for l in IND["layer"]}
    INTERIM.mkdir(parents=True, exist_ok=True)
    for layer in IND["layer"]:
        if not layer.get("ingest") or (args.only and layer["id"] not in args.only):
            continue
        t0 = time.time()
        print(f"{layer['id']} <- {layer['source_id']} ({layer['ingest']}, H3 res {res})")
        df = ingest_layer(layer, S, layers_by_id, res)
        df.index.name = "cell"
        df.to_parquet(INTERIM / f"{layer['id']}.parquet")
        print(f"  {len(df):,} cells in {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
