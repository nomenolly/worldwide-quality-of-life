"""Release-gate check: no withheld layer in any reachable commit or in the working tree.

Scans every blob under data paths in every commit reachable from all local
branches and tags (fetch first), plus the working tree. Exits 1 on any hit.
"""
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PREFIXES = ("site/data/", "site/global/data/", "data/processed/", "data/manifest.json", "data/builds.json")
# Strings that only appear in published conflict records (not in code or prose).
MARKERS = [b'"sec.conflict":{', b',sec.conflict,', b'"events_within_25km"', b'"deaths_placed_best"',
           b'"unlocated"', b'"deaths_best"']


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def main() -> int:
    withheld = tomllib.loads((ROOT / "config" / "region.toml").read_text()).get("release", {}).get("withheld", [])
    hits = []
    commits = git("rev-list", "--branches", "--tags", "--remotes").split()
    seen = set()
    for c in commits:
        for line in git("ls-tree", "-r", c.decode()).splitlines():
            meta, path = line.split(b"\t", 1)
            sha = meta.split()[2]
            p = path.decode()
            if not p.startswith(DATA_PREFIXES) or sha in seen:
                continue
            seen.add(sha)
            blob = git("cat-file", "-p", sha.decode())
            for m in MARKERS:
                if m in blob:
                    hits.append(f"{c.decode()[:10]} {p}: {m.decode()}")
    for f in (list((ROOT / "site" / "data").rglob("*")) + list((ROOT / "site" / "global" / "data").rglob("*"))
              + list((ROOT / "data" / "processed").rglob("*"))):
        if f.is_file():
            b = f.read_bytes()
            for m in MARKERS:
                if m in b:
                    hits.append(f"working tree {f.relative_to(ROOT)}: {m.decode()}")
    print(f"withheld layers: {withheld}; commits scanned: {len(commits)}; data blobs scanned: {len(seen)}")
    if hits:
        print("RELEASE GATE FAILED:")
        print("\n".join(hits))
        return 1
    print("release gate passed: no withheld records in history or working tree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
