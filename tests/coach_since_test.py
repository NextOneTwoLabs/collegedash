"""Checks for the head coach's first season, program.headCoach.since (published as coachSince; issue #168).

    python tests/coach_since_test.py            # everything below, offline
    python tests/coach_since_test.py --verbose  # print every check, not only the failures

Offline: builds program sections in memory from seasons tables and infobox strings shaped like the
stored Wikipedia sources (names and years only). Writes nothing. Exit 0 when every check passes.

Swap-back proof: set COLLEGEDASH_CODE_ROOT to an export of origin/main's build.py and collect/, and
build.py is imported from there:

    git archive origin/main build.py collect | tar -x -C /tmp/pre168
    COLLEGEDASH_CODE_ROOT=/tmp/pre168 python tests/coach_since_test.py

Why this exists
---------------
`since` was the earliest season in the Wikipedia seasons table whose coach shared the head coach's LAST
name. Four of the 46 published years were wrong that way:
  pittsburgh      Ben Waldrum "since 2018": 2018-2024 are Randy Waldrum's seasons
  south-florida   Chris Brown "since 2007": 2007-2023 are Denise Schilte-Brown's
  penn-state      Erica Dambach "since 2016": the table lists 2007-2015 as Erica Walsh, the same coach
  west-virginia   Nikki Izzo-Brown "since 2000": the table lists 1996-1999 as Nikki Izzo, the same coach
The rule is now the same person (same_person), one unbroken run of seasons ending at the table's latest
season, and agreement within one season with the infobox's "(Nth season)" for that coach.

Every case is built relative to build.CURRENT_SEASON_FALLBACK, so the suite means the same thing in any
year. Labels: FIX checks fail against origin/main and pass after the change; CONTROL checks pass on both.
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

NOW = build.CURRENT_SEASON_FALLBACK   # the season the build counts from
LAST = NOW - 1                        # the latest season in a typical stored table

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


def seasons(*runs) -> list[dict]:
    """seasons(("Randy Waldrum", 2018, 2024), ("Ben Waldrum", 2025, 2025)) -> table rows, one per year."""
    return [{"year": y, "label": str(y), "headCoach": coach} for coach, first, last in runs for y in range(first, last + 1)]


def since(head: str, rows: list[dict], infobox: str | None, *, from_staff: bool = True):
    """headCoach.since as build_program_section publishes it. The head coach comes from the athletics
    staff (as for every program since #144/#155) unless from_staff is False."""
    wiki = {"data": {"seasons": rows, "headCoach": infobox}}
    ath = {"data": {"staff": [{"name": head, "title": "Head Coach", "isHeadCoach": True, "isCoach": True,
                               "bioUrl": None, "social": {}}]}} if from_staff else None
    return build.build_program_section({"slug": "fixture", "division": "D1"}, wiki, ath)["headCoach"]["since"]


def nth(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')} season"


def test_the_four_wrong_years() -> None:
    print("the four wrong years published before this change (shapes of the stored tables)")
    # pittsburgh: the table ends at Ben Waldrum's first season, after seven of Randy Waldrum's
    rows = seasons(("Greg Miller", LAST - 13, LAST - 8), ("Randy Waldrum", LAST - 7, LAST - 1), ("Ben Waldrum", LAST, LAST))
    got = since("Ben Waldrum", rows, "Ben Waldrum (1st season)")
    ok(f"FIX pittsburgh: Ben Waldrum's first season is {LAST}, not Randy Waldrum's {LAST - 7}", got == LAST, str(got))
    # south-florida: the table stops at Denise Schilte-Brown; the head coach is Chris Brown
    rows = seasons(("Denise Schilte-Brown", LAST - 18, LAST - 2))
    got = since("Chris Brown", rows, "Chris Brown (1st season)")
    ok("FIX south-florida: Chris Brown gets no year from Denise Schilte-Brown's seasons", got is None, str(got))
    # penn-state: the same coach under two surnames; the infobox counts the whole tenure
    rows = seasons(("Paula Wilkins", LAST - 24, LAST - 19), ("Erica Walsh", LAST - 18, LAST - 10), ("Erica Dambach", LAST - 9, LAST - 2))
    got = since("Erica Dambach", rows, f"Erica Dambach ({nth(NOW - (LAST - 18) + 1)})")
    ok("FIX penn-state: the Dambach run disagrees with the infobox's full count, so no year (not a wrong one)",
       got is None, str(got))
    # west-virginia: "Nikki Izzo" and "Nikki Izzo-Brown" are one coach; the infobox confirms the whole run
    first = NOW - 31 + 1
    rows = seasons(("Nikki Izzo", first, first + 3), ("Nikki Izzo-Brown", first + 4, LAST))
    got = since("Nikki Izzo-Brown", rows, "Nikki Izzo-Brown (31st season)")
    ok(f"FIX west-virginia: the run under both spellings starts in {first}, which the infobox's 31st season confirms",
       got == first, str(got))


def test_unbroken_run() -> None:
    print("one unbroken run ending at the table's latest season")
    rows = seasons(("Alex Coach", LAST - 15, LAST - 10), ("Sam Other", LAST - 9, LAST - 6), ("Alex Coach", LAST - 5, LAST))
    got = since("Alex Coach", rows, f"Alex Coach ({nth(NOW - (LAST - 5) + 1)})")
    ok(f"FIX a coach who returned is counted from the return ({LAST - 5}), not the first spell ({LAST - 15})",
       got == LAST - 5, str(got))
    rows = [r for r in seasons(("Alex Coach", LAST - 15, LAST)) if r["year"] != LAST - 4]
    got = since("Alex Coach", rows, f"Alex Coach ({nth(NOW - (LAST - 15) + 1)})")
    ok("FIX a season missing from the table breaks the run: no year from before the gap", got is None, str(got))
    rows = seasons(("Alex Coach", LAST - 10, LAST - 3), ("Sam Other", LAST - 2, LAST))
    got = since("Alex Coach", rows, f"Alex Coach ({nth(11)})")
    ok("FIX a head coach absent from the table's latest season gets no year", got is None, str(got))
    rows = seasons(("Alex Coach", LAST - 10, LAST))
    rows.insert(3, {"year": LAST - 7, "label": str(LAST - 7), "headCoach": None})
    got = since("Alex Coach", rows, f"Alex Coach ({nth(NOW - (LAST - 10) + 1)})")
    ok("FIX a season listed twice, once with no coach, breaks the run", got is None, str(got))
    rows = seasons(("Alex Coach", LAST - 32, LAST))
    rows.append({"year": LAST, "label": str(LAST), "headCoach": "Alex Coach"})
    got = since("Alex Coach", rows, f"Alex Coach ({nth(NOW - (LAST - 32) + 1)})")
    ok("CONTROL a season listed twice with the same coach (nebraska) does not break the run", got == LAST - 32, str(got))


def test_tolerance_is_one_season() -> None:
    """The owner's confirmation rule: the run and the infobox agree within ONE season, and no more.

    Both cases are the stored tables as they are (Reviewer 2 on #169: widening the tolerance changed no check).
    The Wikipedia tables end in 2025 and never move, so these hold whatever the current season is: the table's
    own last season is always one of the two years the count is measured from."""
    print("the tolerance is exactly one season")
    # michigan-state: Tom Saxton to 2020, Jeff Hosler 2021-2025; infobox "Jeff Hosler [ 2 ] (4th season)".
    # From the table's last season (2025) the 4th season began 2022: one season from the run's 2021.
    rows = seasons(("Tom Saxton", 2009, 2020), ("Jeff Hosler", 2021, 2025))
    got = since("Jeff Hosler", rows, "Jeff Hosler [ 2 ] (4th season)")
    ok("CONTROL michigan-state: run 2021, infobox implies 2022 (1 season apart) -> published 2021", got == 2021, str(got))
    # byu: Jennifer Rockwood 1995-2025; infobox "Jennifer Rockwood (29th season)". From 2025 the 29th season began
    # 1997, two seasons after the run's 1995 (and further still from any later current season).
    rows = seasons(("Jennifer Rockwood", 1995, 2025))
    got = since("Jennifer Rockwood", rows, "Jennifer Rockwood (29th season)")
    ok("FIX byu: run 1995, infobox implies 1997 at the nearest (2 seasons apart) -> withdrawn", got is None, str(got))
    ok("FIX byu: ... and withdrawn at 3 seasons apart too (a 30th-season count, 1996, would still be one away; 28th, 1998, is three)",
       since("Jennifer Rockwood", rows, "Jennifer Rockwood (28th season)") is None
       and since("Jennifer Rockwood", rows, "Jennifer Rockwood (30th season)") == 1995,
       str((since("Jennifer Rockwood", rows, "Jennifer Rockwood (28th season)"), since("Jennifer Rockwood", rows, "Jennifer Rockwood (30th season)"))))


def test_infobox_agreement() -> None:
    print("agreement with the infobox's (Nth season)")
    start = LAST - 22
    rows = seasons(("Paul Coach", start, LAST))
    ok("CONTROL a run that agrees with the infobox counted from today is published",
       since("Paul Coach", rows, f"Paul Coach ({nth(NOW - start + 1)})") == start)
    ok("CONTROL ... and one season either way still agrees",
       since("Paul Coach", rows, f"Paul Coach ({nth(NOW - start)})") == start
       and since("Paul Coach", rows, f"Paul Coach ({nth(NOW - start + 2)})") == start)
    stale = seasons(("Derek Coach", LAST - 12, LAST - 6))  # a table last edited six seasons ago
    ok("CONTROL a count written when a stale table was, (N counted from the table's last season), agrees",
       since("Derek Coach", stale, f"Derek Coach ({nth(8)})") == LAST - 12)
    got = since("Paul Coach", rows, f"Paul Coach ({nth(NOW - start + 1 - 6)})")
    ok("FIX a run the infobox disagrees with by more than a season gets no year", got is None, str(got))
    got = since("Paul Coach", rows, "Paul Coach")
    ok("FIX an infobox with no (Nth season) for the head coach gives no year", got is None, str(got))
    got = since("Paul Coach", rows, None)
    ok("FIX no infobox at all gives no year", got is None, str(got))
    got = since("Paul Coach", rows, f"Someone Else ({nth(NOW - start + 1)})")
    ok("FIX a count that belongs to another coach does not confirm this one", got is None, str(got))
    # Rob Alman's earlier spell would give the old rule LAST-20; St. John's count would match that spell,
    # Alman's own count matches only the current run
    co = seasons(("Rob Alman", LAST - 20, LAST - 15), ("Sam Other", LAST - 14, LAST - 11), ("Rob Alman", LAST - 10, LAST))
    got = since("Rob Alman", co, f"Tari St. John ({nth(NOW - (LAST - 20) + 1)}) Rob Alman ({nth(NOW - (LAST - 10) + 1)})")
    ok("FIX co-head coaches: the count read is the one after this coach's name", got == LAST - 10, str(got))
    fn = getattr(build, "infobox_season_number", None)
    ok("FIX a footnote between name and count is skipped ('Jeff Hosler [ 2 ] (4th season)')",
       fn is not None and fn("Jeff Hosler [ 2 ] (4th season)", "Jeff Hosler") == 4)
    ok("CONTROL the head coach from the infobox, with no athletics staff, is matched the same way",
       since("Paul Coach", rows, f"Paul Coach ({nth(NOW - start + 1)})", from_staff=False) == start)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    if CODE_ROOT != ROOT:
        print(f"code under test imported from {CODE_ROOT}")
    for case in (test_the_four_wrong_years, test_unbroken_run, test_tolerance_is_one_season, test_infobox_agreement):
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
