"""Download every source for the configured region into data/raw/.

Re-running skips files that already exist. Each file's URL, size, SHA-256 and
download time go into data/manifest.json, which is committed, so anyone can
check that they rebuilt from the same bytes.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import zipfile
from pathlib import Path

import requests

from common import MANIFEST, RAW, load_region, load_sources, read_json, sha256, write_json

UA = {"User-Agent": "worldwide-quality-of-life pipeline (open research)"}


def download(url: str, dest: Path, manifest: dict, source_id: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    key = str(dest.relative_to(RAW))
    if not dest.exists():
        print(f"  get {url}")
        with requests.get(url, headers=UA, stream=True, timeout=600) as r:
            r.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
            tmp.rename(dest)
        manifest[key] = {
            "source_id": source_id,
            "url": url,
            "bytes": dest.stat().st_size,
            "sha256": sha256(dest),
            "retrieved": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        }
    elif key not in manifest:
        manifest[key] = {"source_id": source_id, "url": url, "bytes": dest.stat().st_size,
                         "sha256": sha256(dest), "retrieved": "unknown (file was present)"}
    else:
        print(f"  have {key}")
    return dest


def unzip_tifs(zpath: Path) -> None:
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            if name.endswith(".tif") and not (zpath.parent / name).exists():
                z.extract(name, zpath.parent)


def main() -> int:
    reg = load_region()["region"]
    src = load_sources()
    manifest = read_json(MANIFEST) if MANIFEST.exists() else {}

    # GHSL population and settlement model tiles (10° x 10° tiles, WGS84 30 arc-second).
    for sid, folder in [("ghsl_pop_2020", "ghsl"), ("ghsl_smod_2020", "ghsl_smod")]:
        print(sid)
        for tile in src[sid]["tiles"]:
            url = src[sid]["download"].format(tile=tile)
            z = download(url, RAW / folder / url.rsplit("/", 1)[1], manifest, sid)
            unzip_tifs(z)

    # WorldPop: one global 1 km file (276 MB). Downloaded whole because the
    # host does not serve it as a cloud-optimised GeoTIFF.
    print("worldpop_2020")
    url = src["worldpop_2020"]["download"]
    download(url, RAW / "worldpop" / url.rsplit("/", 1)[1], manifest, "worldpop_2020")

    # MAP travel time: a WCS subset of the global surface, padded by 0.5°.
    print("map_travel_2020")
    for variant in src["map_travel_2020"]["variants"]:
        url = src["map_travel_2020"]["download"].format(
            variant=variant, south=reg["south"] - 0.5, north=reg["north"] + 0.5,
            west=reg["west"] - 0.5, east=reg["east"] + 0.5)
        download(url, RAW / "map" / f"{variant}.tif", manifest, "map_travel_2020")

    # UCDP GED 26.1 and its codebook.
    print("ucdp_ged_261")
    z = download(src["ucdp_ged_261"]["download"], RAW / "ucdp" / "ged261-csv.zip", manifest, "ucdp_ged_261")
    with zipfile.ZipFile(z) as zf:
        for name in zf.namelist():
            if not (z.parent / name).exists():
                zf.extract(name, z.parent)
    download("https://ucdp.uu.se/downloads/ged/ged261.pdf", RAW / "ucdp" / "ged261.pdf", manifest, "ucdp_ged_261")

    # UNSD census dates page (transcribed in layers/census.py).
    print("unsd_census_dates")
    download(src["unsd_census_dates"]["download"], RAW / "unsd" / "censusdates.html", manifest, "unsd_census_dates")

    # geoBoundaries ADM0 metadata and simplified outlines.
    print("geoboundaries_adm0")
    for iso in reg["countries"]:
        meta = download(src["geoboundaries_adm0"]["download"].format(iso=iso),
                        RAW / "geoboundaries" / f"{iso}-ADM0-meta.json", manifest, "geoboundaries_adm0")
        gj = json.loads(meta.read_text())["simplifiedGeometryGeoJSON"]
        download(gj, RAW / "geoboundaries" / f"{iso}-ADM0.geojson", manifest, "geoboundaries_adm0")

    write_json(MANIFEST, dict(sorted(manifest.items())), compact=False)
    print(f"manifest: {len(manifest)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
