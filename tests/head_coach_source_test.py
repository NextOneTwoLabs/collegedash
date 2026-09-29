"""Checks for where the published head coach comes from (issue #151).

    python tests/head_coach_source_test.py            # everything below, offline
    python tests/head_coach_source_test.py --verbose  # print every check, not only the failures

Offline: builds program sections in memory from made-up staff lists and infobox strings (no real people), then
runs the same rule over every published program's committed sources and prints counts only. Writes nothing.

Swap-back proof: set COLLEGEDASH_CODE_ROOT to an export of origin/main's build.py, the modules it imports and
collect/ (8 FIX checks fail there, 6 CONTROL checks pass):

    git archive origin/main build.py clubs.py schools.py trends.py collect | tar -x -C /tmp/pre151
    COLLEGEDASH_CODE_ROOT=/tmp/pre151 python tests/head_coach_source_test.py

Why this exists
---------------
Four published programs once had no stored staff rows, and their head coach came from the Wikipedia infobox.
On louisiana-monroe that name was not the coach the school's own /coaches page listed ("Head Soccer Coach"),
and on texas it differed too. The school's page wins (as for radford, #144): Wikipedia's name is published only
when the school names no head coach, never when the school's stored page lists a coaching staff without one,
and the profile says which source the name came from (program.headCoach.source) so the page can say so.

Labels: FIX checks fail against origin/main and pass after the change; CONTROL checks pass on both.
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_ROOT = os.environ.get("COLLEGEDASH_CODE_ROOT") or ROOT
sys.path.insert(0, CODE_ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import build  # noqa: E402
from collect import common  # noqa: E402
from collect.adapters.sidearm import is_head_coach  # noqa: E402

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


def row(name: str, title: str, *, coach: bool = True) -> dict:
    return {"name": name, "title": title, "isHeadCoach": is_head_coach(title), "isCoach": coach,
            "bioUrl": None, "social": {}}


def head(staff: list[dict] | None, infobox: str | None) -> dict:
    """program.headCoach as build_program_section publishes it; staff None means no athletics source at all."""
    wiki = {"data": {"seasons": [], "headCoach": infobox}} if infobox is not None else None
    ath = {"data": {"staff": staff}} if staff is not None else None
    real = common.log
    common.log = lambda *a, **k: None  # the #151 log line names the fixture slug only; keep the output to counts
    try:
        return build.build_program_section({"slug": "fixture", "division": "D1"}, wiki, ath)["headCoach"]
    finally:
        common.log = real


def test_school_wins() -> None:
    print("the school's own page wins over Wikipedia")
    hc = head([row("Avery Example", "Head Soccer Coach"), row("Blake Sample", "Assistant Coach")],
              "Casey Placeholder (6th season)")
    ok("CONTROL a 'Head Soccer Coach' row is the school's head coach", is_head_coach("Head Soccer Coach"))
    ok("CONTROL the school's head coach is published, not the infobox's", hc["name"] == "Avery Example", hc)
    ok("FIX and its source says the school's site", hc.get("source") == "athletics", hc)


def test_wikipedia_only_when_school_names_none() -> None:
    print("Wikipedia only when the school names no head coach")
    hc = head(None, "Casey Placeholder (6th season)")
    ok("CONTROL no athletics source: the infobox's coach is published", hc["name"] == "Casey Placeholder", hc)
    ok("FIX and its source says Wikipedia", hc.get("source") == "wikipedia", hc)
    hc = head([], "Casey Placeholder (6th season)")
    ok("FIX an athletics source with no staff rows: Wikipedia, labelled",
       hc["name"] == "Casey Placeholder" and hc.get("source") == "wikipedia", hc)
    hc = head([row("Drew Filler", "Director of Operations", coach=False)], "Casey Placeholder (6th season)")
    ok("FIX support staff only (no coach listed): Wikipedia, labelled",
       hc["name"] == "Casey Placeholder" and hc.get("source") == "wikipedia", hc)


def test_school_lists_coaches_but_no_head() -> None:
    print("a school page that lists coaches but no head coach is not overruled by Wikipedia")
    hc = head([row("Blake Sample", "Assistant Coach"), row("Erin Mock", "Goalkeeper Coach")],
              "Casey Placeholder (6th season)")
    ok("FIX no head coach is published", hc["name"] is None, hc)
    ok("FIX no source, no year", hc.get("source") is None and hc["since"] is None, hc)
    hc = head([row("Casey Placeholder", "Associate Head Coach")], "Casey Placeholder (6th season)")
    ok("FIX the infobox's coach listed by the school as an associate head coach is not published as head",
       hc["name"] is None, hc)


def test_nothing() -> None:
    print("no head coach from either source")
    hc = head(None, None)
    ok("CONTROL no name", hc["name"] is None, hc)
    ok("FIX no source", "source" in hc and hc["source"] is None, hc)
    hc = head([row("Blake Sample", "Assistant Coach")], "")
    ok("CONTROL an empty infobox field with a staff list: no name", hc["name"] is None, hc)


def test_committed_sources() -> None:
    """The rule over every published program's committed sources. Counts only: no names."""
    print("committed sources, every published program")
    if CODE_ROOT != ROOT:  # an exported build.py reads this checkout's committed data, not the export's (absent) copy
        common.PROGRAMS_DIR = os.path.join(ROOT, "programs")
        common.REGISTRY_PATH = os.path.join(ROOT, "public", "data", "registry.json")
    registry = common.load_registry()
    counts = {"athletics": 0, "wikipedia": 0, None: 0}
    wrong = []
    for program in build.published_programs(registry):
        slug = program["slug"]
        wiki, ath = common.load_source(slug, "wikipedia"), common.load_source(slug, "athletics")
        staff = ((ath or {}).get("data") or {}).get("staff") or []
        real = common.log
        common.log = lambda *a, **k: None
        try:
            hc = build.build_program_section(program, wiki, ath)["headCoach"]
        finally:
            common.log = real
        src = hc.get("source")
        counts[src] = counts.get(src, 0) + 1
        school_head = next((s for s in staff if s.get("isHeadCoach")), None)
        if school_head and (src != "athletics" or hc["name"] != school_head["name"]):
            wrong.append(f"{slug}: the school names a head coach but it is not the one published")
        if src == "wikipedia" and any(s.get("isCoach") for s in staff):
            wrong.append(f"{slug}: a Wikipedia coach is published over a school coaching staff")
        if bool(hc["name"]) != (src is not None):
            wrong.append(f"{slug}: a name without a source, or a source without a name")
    print(f"  {sum(counts.values())} programs: head coach from the school's site {counts['athletics']}, "
          f"from Wikipedia {counts['wikipedia']}, none {counts[None]}")
    ok("FIX every published program follows the rule", not wrong, "; ".join(wrong[:10]))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    if CODE_ROOT != ROOT:
        print(f"code under test imported from {CODE_ROOT}")
    for case in (test_school_wins, test_wikipedia_only_when_school_names_none, test_school_lists_coaches_but_no_head,
                 test_nothing, test_committed_sources):
        try:
            case()
        except Exception as e:  # a case that raises is a failed case, not a lost run
            ok(f"{case.__name__} ran to the end", False, f"{type(e).__name__}: {e}")
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
