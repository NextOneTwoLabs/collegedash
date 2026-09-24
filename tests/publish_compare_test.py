"""Regression tests for tools/publish_compare.py (issue #94: the D3 switch's before/after comparison).

    python tests/publish_compare_test.py            # everything below, offline
    python tests/publish_compare_test.py --verbose  # print every check, not only the failures

Offline: builds small BEFORE/AFTER data trees in a temporary directory, plus one tree whose trends index is
the committed one. Exit 0 when every check passes. Every check names, in a comment, the input that makes it fail.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_ROOT = os.environ.get("COLLEGEDASH_CODE_ROOT") or ROOT
sys.path.insert(0, os.path.join(CODE_ROOT, "tools"))

import publish_compare as pc  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def tree(base: str, name: str, trends: dict | None, rows: list[dict], profiles: dict[str, dict]) -> str:
    d = os.path.join(base, name)
    os.makedirs(os.path.join(d, "programs"), exist_ok=True)
    if trends is not None:
        os.makedirs(os.path.join(d, "trends"), exist_ok=True)
        with open(os.path.join(d, "trends", "index.json"), "w", encoding="utf-8") as f:
            json.dump(trends, f)
    with open(os.path.join(d, "programs", "index.json"), "w", encoding="utf-8") as f:
        json.dump({"programs": rows}, f)
    for slug, p in profiles.items():
        with open(os.path.join(d, "programs", f"{slug}.json"), "w", encoding="utf-8") as f:
            json.dump(p, f)
    return d


TRENDS = {"updated": "2026-09-23T15:34:00Z", "division": "D1", "programs": {"a": {"current": 3}}}
ROWS = [{"slug": "a", "division": "D1", "rosterSize": 3, "builtAt": "t1"}, {"slug": "b", "division": "D2", "rosterSize": 5, "builtAt": "t1"}]
PROFILES = {"a": {"slug": "a", "division": "D1", "_build": {"builtAt": "t1", "completeness": 0.9}},
            "b": {"slug": "b", "division": "D2", "_build": {"builtAt": "t1", "completeness": 0.5}}}


def stamp(rows, profiles, t):
    rows, profiles = copy.deepcopy(rows), copy.deepcopy(profiles)
    for r in rows:
        r["builtAt"] = t
    for p in profiles.values():
        p["_build"]["builtAt"] = t
    return rows, profiles


def run(base, name, trends=TRENDS, rows=ROWS, profiles=PROFILES):
    before = tree(base, f"{name}-before", TRENDS, ROWS, PROFILES)
    after = tree(base, f"{name}-after", trends, rows, profiles)
    diffs = pc.compare_trends(before, after)
    more, new = pc.compare_programs(before, after)
    return diffs + more, new


def test_compare() -> None:
    print("compare: trends with `updated` masked, D1/D2 rows and profiles with builtAt masked")
    with tempfile.TemporaryDirectory() as base:
        r2, p2 = stamp(ROWS, PROFILES, "t2")
        d3_rows = r2 + [{"slug": "c", "division": "D3", "rosterSize": None, "builtAt": "t2"}]
        d3_prof = {**p2, "c": {"slug": "c", "division": "D3", "_build": {"builtAt": "t2"}}}
        diffs, new = run(base, "switch", {**TRENDS, "updated": "2026-09-24T15:34:00Z"}, d3_rows, d3_prof)
        # fails if `updated` or builtAt are compared, or a new division's rows are counted as differences
        ok("a clean switch: new stamps and new D3 rows are not differences", diffs == [], diffs)
        ok("and the new D3 rows are counted", new == {"D3": 1}, str(new))
        diffs, _ = run(base, "trends", {**TRENDS, "updated": "x", "programs": {"a": {"current": 4}, "c": {"current": 1}}}, d3_rows, d3_prof)
        # fails if the trends comparison stops looking past `updated` (a D3 program counted into trends)
        ok("a trends count that moved is a difference", any("trends/index.json differs" in d and "programs" in d for d in diffs), diffs)
        diffs, _ = run(base, "notrends", None, d3_rows, d3_prof)
        ok("a missing trends index is a difference", any("missing from AFTER" in d for d in diffs), diffs)
        rows = copy.deepcopy(d3_rows)
        rows[1]["rosterSize"] = 6
        diffs, _ = run(base, "d2row", TRENDS, rows, d3_prof)
        # fails if D2 rows are not compared (a switch that changes a published D2 row)
        ok("a changed D2 index row is a difference", "programs b: index row differs apart from builtAt" in diffs, diffs)
        prof = copy.deepcopy(d3_prof)
        prof["a"]["_build"]["completeness"] = 0.1
        diffs, _ = run(base, "d1prof", TRENDS, d3_rows, prof)
        ok("a changed D1 profile is a difference", "programs a: profile differs apart from builtAt" in diffs, diffs)
        diffs, _ = run(base, "dropped", TRENDS, [d3_rows[0], d3_rows[2]], d3_prof)
        ok("a D2 program dropped by the switch is a difference", "programs b: published before, not after" in diffs, diffs)
        diffs, _ = run(base, "newd2", TRENDS, d3_rows + [{"slug": "z", "division": "D2", "builtAt": "t2"}], d3_prof)
        ok("a new row in an already-published division is a difference", "programs z: a new D2 row" in diffs, diffs)
        # the committed trends index against itself with a new stamp
        committed = os.path.join(ROOT, "public", "data", "trends", "index.json")
        with open(committed, encoding="utf-8") as f:
            doc = json.load(f)
        a = tree(base, "real-a", doc, [], {})
        b = tree(base, "real-b", {**doc, "updated": "2099-01-01T00:00:00Z"}, [], {})
        ok("the committed trends index equals itself with only `updated` changed", pc.compare_trends(a, b) == [])


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    VERBOSE = ap.parse_args(argv).verbose
    test_compare()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
