"""Shared paths, config loading and small helpers for the WQL pipeline."""
from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
SITE_DATA = ROOT / "site" / "data"
MANIFEST = ROOT / "data" / "manifest.json"


def load_region() -> dict:
    with open(ROOT / "config" / "region.toml", "rb") as f:
        return tomllib.load(f)


def load_sources() -> dict:
    with open(ROOT / "config" / "sources.toml", "rb") as f:
        return tomllib.load(f)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj, compact: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        else:
            json.dump(obj, f, indent=2, ensure_ascii=False, allow_nan=False)
            f.write("\n")


def read_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


GRADE_ORDER = "ABCD"
DIMENSIONS = ["recency", "directness", "spatial_fidelity", "coverage", "validation", "interval"]


def weakest(grade_detail: dict) -> str:
    """The weakest of the six dimensions, used as a qualification flag (WQL-001 D-15)."""
    return max((grade_detail[d] for d in DIMENSIONS), key=GRADE_ORDER.index)
