"""Check whether any global source has changed or been superseded upstream (WQL-003 step 5).

For every source an ingested layer uses, according to its `renewal` entry in
config/sources.toml:

  head              ask the server for the file's Last-Modified, ETag and size, and
                    compare them with what data/manifest.json recorded at download
  listing           read the publisher's directory listing and look for a release
                    newer than the one ingested (for example GHS_POP_GLOBE_R2025A)
  wcs_capabilities  read the WCS capabilities and look for a newer coverage id

Every source is also checked with `head` on its download URL when it is a single file.

Writes data/renewal.json and prints a summary. Nothing is downloaded or rebuilt:
renewing a source is a reviewed change to sources.toml followed by
`make global`, which records a new build version in data/builds.json.

Exit status: 0 when nothing changed or could not be checked, 1 with --strict when
any source changed or has a newer release (so a scheduled job can flag it).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

import requests

from common import MANIFEST, ROOT, load_indicators, load_sources, read_json, write_json

UA = {"User-Agent": "worldwide-quality-of-life renewal check (open research)"}
REPORT = ROOT / "data" / "renewal.json"


def head(url: str) -> dict:
    r = requests.head(url, headers=UA, timeout=60, allow_redirects=True)
    r.raise_for_status()
    return {k: r.headers.get(k) for k in ("Last-Modified", "ETag", "Content-Length") if r.headers.get(k)}


def newer(found: list[str], current: str) -> list[str]:
    return sorted({f for f in found if f > current})


def check(sid: str, src: dict, manifest: dict) -> dict:
    ren = src.get("renewal", {})
    out = {"source_id": sid, "name": src["name"], "kind": ren.get("kind", "none"), "changed": False, "findings": []}
    try:
        if src.get("fetch") == "file":
            now = head(src["download"])
            rec = next((v for v in manifest.values() if v.get("url") == src["download"]), None)
            then = (rec or {}).get("server", {})
            if not then:
                out["findings"].append("Download was recorded without server headers; recording today's as the baseline: "
                                       + ", ".join(f"{k} {v}" for k, v in now.items()) + ".")
                if rec is not None:
                    rec["server"] = now
                    rec["server_baseline"] = f"recorded by renew.py on {dt.date.today().isoformat()}, after download"
            else:
                diff = {k: (then.get(k), now.get(k)) for k in set(then) | set(now) if then.get(k) != now.get(k)}
                if diff:
                    out["changed"] = True
                    out["findings"].append("File changed upstream: " + "; ".join(f"{k} {a} -> {b}" for k, (a, b) in diff.items()))
                else:
                    out["findings"].append("File unchanged since download.")
        if ren.get("kind") in ("listing", "wcs_capabilities"):
            url = ren.get("listing") or ren.get("capabilities")
            text = requests.get(url, headers=UA, timeout=120).text
            found = re.findall(ren["pattern"], text)
            n = newer(found, ren["current"])
            if n:
                out["changed"] = True
                out["findings"].append(f"Newer release(s) than {ren['current']}: {', '.join(n)}")
            else:
                out["findings"].append(f"No release newer than {ren['current']} listed.")
            if ren.get("related"):
                rel = sorted(set(re.findall(ren["related"], text)) - {ren["current"]})
                if rel:
                    out["findings"].append("Related products also listed (whether any supersedes the ingested one is not checked): "
                                           + ", ".join(rel) + ".")
            if ren.get("cadence_months"):
                out["cadence_months"] = ren["cadence_months"]
    except requests.RequestException as e:
        out["error"] = f"Could not check: {e.__class__.__name__}: {e}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--strict", action="store_true", help="exit 1 when any source changed or has a newer release")
    args = ap.parse_args()
    S, IND = load_sources(), load_indicators()
    manifest = read_json(MANIFEST) if MANIFEST.exists() else {}
    used = sorted({l["source_id"] for l in IND["layer"] if l.get("source_id")})
    results = [check(sid, S[sid], manifest) for sid in used]
    builds = read_json(ROOT / "data" / "builds.json") if (ROOT / "data" / "builds.json").exists() else []
    report = {"checked": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "current_build": builds[-1]["version"] if builds else None, "sources": results}
    write_json(REPORT, report, compact=False)
    write_json(MANIFEST, dict(sorted(manifest.items())), compact=False)
    for r in results:
        mark = "CHANGED" if r["changed"] else "error" if r.get("error") else "ok"
        print(f"[{mark}] {r['source_id']}: {' '.join(r['findings'])} {r.get('error', '')}".rstrip())
    return 1 if args.strict and any(r["changed"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
