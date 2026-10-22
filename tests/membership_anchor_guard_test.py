"""The long-standing-program fixture behind validate's membership anchor is itself guarded (issue #126, F-a).

    python tests/membership_anchor_guard_test.py            # everything below, offline
    python tests/membership_anchor_guard_test.py --verbose  # print every check

Offline: reads the committed registry and tests/fixtures/registry/pre-100-programs.json, writes edited copies of the
fixture to a temporary directory only, and calls build.check_membership_anchor. Nothing is fetched or built.

Why this exists
---------------
build.check_membership_anchor stops validate when a long-standing D1 program (one in the registry before issue #100)
leaves the published set without a reviewed reason, so a registry mistake cannot delete live pages silently (PR #112
review, R1). Its list of long-standing programs is a fixture file. PR #112's approval found (F-a) that truncating that
file - 40 slugs removed, the same 40 unpublished in the registry - made validate exit 0 and the build delete 40
profiles; only a single `len(pre) == 350` literal in one test suite noticed. The anchor now checks the fixture itself:
its program count and a SHA-256 of its sorted slugs are pinned in build.py, so an edited fixture fails validate.

F-b, the same review: the anchor only saw absence, so relabelling 40 long-standing D1 programs as D2 (with D2
onboarded) deleted nothing and passed, while they quietly left everything scoped to D1 (the RPI join, D1 counts).
The anchor now also requires each published long-standing program to be D1, unless build.REVIEWED_RECLASSIFIED names
its division and the reviewed reason (Saint Francis, D3, #94).

FIX checks fail on origin/main (where any fixture is taken at its word); CONTROL checks pass on both.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import build  # noqa: E402
from collect import common  # noqa: E402

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


def anchor(registry: dict, fixture_doc: dict | None = None) -> tuple[bool, str]:
    """check_membership_anchor against `registry`, reading `fixture_doc` (written to a temporary file) instead of the
    committed fixture when given. Returns (result, printed text)."""
    real = build.LONG_STANDING_PATH
    with tempfile.TemporaryDirectory() as tmp:
        if fixture_doc is not None:
            path = os.path.join(tmp, "pre-100-programs.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(fixture_doc, f)
            build.LONG_STANDING_PATH = path
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                result = build.check_membership_anchor(registry)
        finally:
            build.LONG_STANDING_PATH = real
    return result, out.getvalue()


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose

    registry = common.load_registry()
    with open(build.LONG_STANDING_PATH, encoding="utf-8") as f:
        fixture = json.load(f)
    published = {p["slug"] for p in build.published_programs(registry)}

    print("control: the committed registry and fixture pass")
    result, text = anchor(registry)
    ok("CONTROL the committed fixture and registry pass the anchor", result, text)

    print("F-a: a truncated fixture, its programs unpublished to match, fails validate")
    victims = sorted(p["slug"] for p in fixture["programs"] if p["slug"] in published)[:40]
    ok("CONTROL 40 long-standing published programs to work with", len(victims) == 40, str(len(victims)))
    truncated = {**fixture, "programs": [p for p in fixture["programs"] if p["slug"] not in set(victims)]}
    unpublished = copy.deepcopy(registry)
    for p in unpublished["programs"]:
        if p["slug"] in victims:
            p["onboarded"] = False
    ok("CONTROL the edited registry really unpublishes them",
       not ({p["slug"] for p in build.published_programs(unpublished)} & set(victims)))
    result, text = anchor(unpublished, truncated)
    ok("FIX a fixture 40 programs short fails the anchor", result is False, text)
    ok("FIX ... and says the fixture changed, with its count", "MEMBERSHIP" in text and "fixture" in text
       and str(len(truncated["programs"])) in text, text)

    print("F-a: the same count with one slug swapped fails too (the digest, not just the count)")
    # swapped for a program that is published but not long-standing, so nothing reads as unpublished: only the digest
    # can tell this fixture from the committed one
    newcomer = sorted(published - {p["slug"] for p in fixture["programs"]})[0]
    swapped = copy.deepcopy(fixture)
    swapped["programs"][0]["slug"] = newcomer
    result, text = anchor(registry, swapped)
    ok("FIX a fixture with one slug replaced fails the anchor", result is False, text)

    print("the pins themselves")
    ok("FIX build pins the fixture's program count", getattr(build, "LONG_STANDING_COUNT", None) == len(fixture["programs"]),
       getattr(build, "LONG_STANDING_COUNT", None))
    ok("CONTROL reordering the fixture's entries changes nothing (the digest is over sorted slugs)",
       anchor(registry, {**fixture, "programs": list(reversed(fixture["programs"]))})[0])

    print("F-b: relabelling long-standing D1 programs to another division fails validate")
    d1 = sorted(p["slug"] for p in build.published_programs(registry) if p["slug"] in {q["slug"] for q in fixture["programs"]}
                and p["division"] == "D1")[:40]
    ok("CONTROL 40 long-standing D1 programs to relabel", len(d1) == 40, str(len(d1)))
    relabelled = copy.deepcopy(registry)
    for p in relabelled["programs"]:
        if p["slug"] in d1:
            p["division"] = "D2"
    ok("CONTROL they stay published (D2 is onboarded), so the absence check cannot see them",
       set(d1) <= {p["slug"] for p in build.published_programs(relabelled)})
    result, text = anchor(relabelled)
    ok("FIX 40 long-standing D1 programs relabelled D2 fail the anchor", result is False, text)
    ok("FIX ... naming each one and its new division", all(s in text for s in d1) and "D2" in text, text[:300])
    one = copy.deepcopy(registry)
    for p in one["programs"]:
        if p["slug"] == d1[0]:
            p["division"] = "D3"
    ok("FIX even one relabelled program fails", anchor(one)[0] is False)
    by = {p["slug"]: p for p in registry["programs"]}
    ok("CONTROL a reviewed reclassification passes: saint-francis is D3 (#94) on today's registry",
       by.get("saint-francis", {}).get("division") == "D3" and anchor(registry)[0])
    ok("FIX every reviewed reclassification names its division and why",
       all(isinstance(v, tuple) and len(v) == 2 and v[0] in ("D1", "D2", "D3") and v[1]
           for v in getattr(build, "REVIEWED_RECLASSIFIED", {"x": ("D3", "")}).values())
       if hasattr(build, "REVIEWED_RECLASSIFIED") else False)

    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
