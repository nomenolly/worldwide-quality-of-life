"""Download every source the global build ingests into data/raw/ (WQL-003).

Driven by config/indicators.toml: each ingested layer names a source in
config/sources.toml, and each source says how it is fetched (`fetch`):

  file      one URL, optionally a zip to extract
  wcs_tiles a WCS coverage requested in lat/long tiles (the server refuses
            whole-globe requests), one GeoTIFF per tile

Re-running skips files already present. Every file's URL, size, SHA-256,
retrieval time and the server's Last-Modified / ETag / Content-Length go into
data/manifest.json, which renew.py later compares against the server to see
whether a source has changed upstream.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import sys
import zipfile
from pathlib import Path

import requests

from common import MANIFEST, RAW, load_indicators, load_sources, read_json, sha256, write_json

UA = {"User-Agent": "worldwide-quality-of-life pipeline (open research)"}


def download(url: str, dest: Path, source_id: str) -> tuple[str, dict | None]:
    """Fetch url to dest unless present. Returns (manifest key, record or None if skipped)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    key = str(dest.relative_to(RAW))
    if dest.exists():
        return key, None
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(4):
        try:
            with requests.get(url, headers=UA, stream=True, timeout=900) as r:
                r.raise_for_status()
                hdr = {k: r.headers.get(k) for k in ("Last-Modified", "ETag", "Content-Length") if r.headers.get(k)}
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            break
        except requests.RequestException as e:
            if attempt == 3:
                raise
            print(f"  retry {attempt + 1} {url}: {e}")
    tmp.rename(dest)
    return key, {"source_id": source_id, "url": url, "bytes": dest.stat().st_size, "sha256": sha256(dest),
                 "retrieved": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                 "server": hdr}


def extract(zpath: Path, suffixes=(".tif", ".tif.ovr")) -> None:
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            if name.endswith(suffixes) and not (zpath.parent / name).exists():
                z.extract(name, zpath.parent)


def tiles(src: dict):
    """Lat/long tiles covering the source's extent, `tile_deg` on a side."""
    s, w, n, e = src["extent"]
    d = src["tile_deg"]
    lat = s
    while lat < n:
        lng = w
        while lng < e:
            yield lat, min(lat + d, n), lng, min(lng + d, e)
            lng += d
        lat += d


def jobs_for(sid: str, src: dict):
    folder = RAW / src["folder"]
    if src["fetch"] == "file":
        url = src["download"]
        yield url, folder / url.rsplit("/", 1)[1]
    elif src["fetch"] == "wcs_tiles":
        for variant in src["variants"]:
            for s, n, w, e in tiles(src):
                url = src["download"].format(variant=variant, south=s, north=n, west=w, east=e)
                yield url, folder / variant / f"{variant}_{s:+04d}_{w:+05d}.tif"
    else:
        raise ValueError(f"{sid}: unknown fetch method {src['fetch']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="*", help="source ids to fetch (default: all used by ingested layers)")
    args = ap.parse_args()
    S, IND = load_sources(), load_indicators()
    wanted = {i["source_id"] for i in IND["layer"] if i.get("ingest")} | set(IND["build"].get("context_sources", []))
    if args.only:
        wanted &= set(args.only)
    manifest = read_json(MANIFEST) if MANIFEST.exists() else {}
    for sid in sorted(wanted):
        src = S[sid]
        print(sid)
        jobs = list(jobs_for(sid, src))
        with cf.ThreadPoolExecutor(max_workers=src.get("parallel", 1)) as pool:
            for key, rec in pool.map(lambda j: download(j[0], j[1], sid), jobs):
                if rec:
                    manifest[key] = rec
                    print(f"  got {key} ({rec['bytes'] / 1e6:.0f} MB)")
                elif key not in manifest:
                    p = RAW / key
                    manifest[key] = {"source_id": sid, "url": next(u for u, d in jobs if d == p),
                                     "bytes": p.stat().st_size, "sha256": sha256(p),
                                     "retrieved": "unknown (file was present)"}
        for _, dest in jobs:
            if dest.suffix == ".zip":
                extract(dest)
        write_json(MANIFEST, dict(sorted(manifest.items())), compact=False)
    print(f"manifest: {len(manifest)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
