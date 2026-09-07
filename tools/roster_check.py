"""Offline regression check for the roster parsers.

Runs platform detection + parse_roster over every roster page already in the HTTP cache
(.cache/http) for the onboarded programs, without a single live request and without writing
anything under programs/ or public/. Use it before and after touching an adapter.

    python tools/roster_check.py                 # every onboarded program
    python tools/roster_check.py --slug duke,byu # a few
    python tools/roster_check.py --min-ok 155    # exit 1 when fewer than 155 parse
    python tools/roster_check.py --json report.json --verbose

Outcome classes: ok:<players>/<staff> | 0-players | client-rendered | parked-stub | not-cached
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import adapters, common  # noqa: E402
from collect.athletics_site import detect_platform  # noqa: E402
from collect.adapters.sidearm import looks_client_rendered  # noqa: E402


def cached_body(url: str) -> str | None:
    key = common._cache_key("GET", url, None)
    gz = os.path.join(common.CACHE_DIR, key + ".body.gz")
    plain = os.path.join(common.CACHE_DIR, key + ".body")
    if os.path.exists(gz):
        with gzip.open(gz, "rb") as f:
            return f.read().decode("utf-8", "replace")
    if os.path.exists(plain):
        with open(plain, "rb") as f:
            return f.read().decode("utf-8", "replace")
    return None


def check(program: dict, registry: dict) -> dict:
    a = program["athletics"]
    base, sport = a.get("baseUrl"), a.get("sportPath", "")
    url = f"{base}{sport}/roster"
    out = {"slug": program["slug"], "host": common._host(base or ""), "registryPlatform": a.get("platform"), "url": url}
    html = cached_body(url)
    if html is None:
        out["outcome"] = "not-cached"
        return out
    if len(html) < 2000 or "window.location.href" in html[:500]:
        out["outcome"] = "parked-stub"
        return out
    detected = detect_platform(html)
    out["detectedPlatform"] = detected
    if not detected:
        out["outcome"] = "client-rendered" if looks_client_rendered(html) else "unknown-platform"
        return out
    ad = adapters.get(detected)
    roster = ad.parse_roster(html, base)
    n, s = len(roster["players"]), len(roster["staff"])
    if n:
        out["outcome"] = "ok"
        out["players"], out["staff"], out["season"] = n, s, roster["season"]
        out["sample"] = roster["players"][0]
        missing = [k for k in ("pos", "classCode", "hometown") if not sum(1 for p in roster["players"] if p.get(k))]
        if missing:
            out["emptyFields"] = missing
    elif looks_client_rendered(html):
        out["outcome"] = "client-rendered"
    else:
        out["outcome"] = "0-players"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", help="comma-separated slugs (default: every onboarded program)")
    ap.add_argument("--min-ok", type=int, default=0, help="exit 1 when fewer programs parse ok")
    ap.add_argument("--json", help="write the per-program report here")
    ap.add_argument("--verbose", action="store_true", help="print the first player of every ok program")
    args = ap.parse_args(argv)

    reg = common.load_registry()
    if args.slug:
        programs = [common.get_program(s.strip(), reg) for s in args.slug.split(",")]
    else:
        programs = list(common.iter_programs(reg))
    results = [check(p, reg) for p in programs]

    by_outcome = collections.Counter(r["outcome"] for r in results)
    for r in results:
        line = f"{r['slug']:24} {r['outcome']:16}"
        if r["outcome"] == "ok":
            line += f" {r['players']:3} players {r['staff']:2} staff  season {r.get('season')}"
            if r.get("emptyFields"):
                line += f"  (empty: {', '.join(r['emptyFields'])})"
        if r.get("detectedPlatform") and r.get("registryPlatform") not in (None, "auto", r["detectedPlatform"]):
            line += f"  PLATFORM MISMATCH registry={r['registryPlatform']} markup={r['detectedPlatform']}"
        print(line)
        if args.verbose and r["outcome"] == "ok":
            print("   ", json.dumps(r["sample"], ensure_ascii=False))
    print()
    print("summary:", ", ".join(f"{k} {v}" for k, v in sorted(by_outcome.items())), f"(of {len(results)})")
    for outcome in ("0-players", "client-rendered", "parked-stub", "unknown-platform"):
        slugs = [r["slug"] for r in results if r["outcome"] == outcome]
        if slugs:
            print(f"  {outcome}: {', '.join(slugs)}")
    mism = [r["slug"] for r in results if r.get("detectedPlatform") and r.get("registryPlatform") not in (None, "auto", r["detectedPlatform"])]
    if mism:
        print(f"  platform mismatches: {', '.join(mism)}")
    if args.json:
        common.write_json(args.json, results)
    return 0 if by_outcome.get("ok", 0) >= args.min_ok else 1


if __name__ == "__main__":
    sys.exit(main())
