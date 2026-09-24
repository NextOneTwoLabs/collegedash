"""A season's NCAA result agrees with the Honors lists on the same profile (issue #202).

    python tests/postseason_honors_test.py            # everything below, offline
    python tests/postseason_honors_test.py --verbose  # print every check, not only the failures

Offline: builds profiles from the committed sources, makes no request and writes nothing.

Why this exists
---------------
Stanford's History tab listed 2014 among its College Cups (Honors) while its season table gave the 2014 NCAA
result as "Third Round". Both came from the Wikipedia article: Honors from the infobox, the season result from
the year-by-year table, whose 2014 row repeats 2013's "NCAA Third Round". Stanford's 2014 schedule on
gostanford.com shows a quarterfinal win over Florida and a College Cup semifinal loss to Florida State, so the
infobox is right. The build compared neither source with the other; build.reconcile_ncaa_results now makes the
season row agree with the Honors the page publishes.

Labels: FIX checks fail on origin/main (or with reconcile_ncaa_results a no-op) and pass after the change;
CONTROL checks pass on both.
"""

from __future__ import annotations

import argparse
import os
import sys

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
        print(f"  FAIL {name}" + (f" - {ascii(detail)[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def reconcile(rows: list[tuple[int, str | None]], program: dict) -> tuple[dict[int, dict], list[int]]:
    seasons = [{"year": y, "ncaaResult": r} for y, r in rows]
    changed = build.reconcile_ncaa_results(seasons, program)
    return {s["year"]: s for s in seasons}, changed


def test_synthetic() -> None:
    print("synthetic: a season row below, at or beyond the finish its Honors list vouches for")
    program = {"nationalTitles": [2001, 2002], "nationalRunnerUp": [2003, 2004],
               "collegeCups": [2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009]}
    rows, changed = reconcile([
        (2001, "NCAA Final"),                    # a champion's row saying only that it reached the final
        (2002, "NCAA Champions"),
        (2003, "NCAA Second Round"),             # runner-up year, row two rounds short
        (2004, "NCAA College Cup Runner-up"),
        (2005, "NCAA Third Round"),              # the Stanford 2014 shape
        (2006, None),                            # no result in the table at all
        (2007, "NCAA Quarterfinals"),
        (2008, "NCAA College Cup Semifinals"),
        (2009, "NCAA T-3rd"),                    # a placing: tied third is a College Cup
        (2010, "NCAA Third Round"),              # no Honors list names 2010
    ], program)
    ok("FIX a College Cup year whose row says 'Third Round' becomes a College Cup",
       rows[2005]["ncaaResult"] == "NCAA College Cup", str(rows[2005]))
    ok("FIX the row's own text is kept beside it, with where the result came from",
       rows[2005].get("ncaaResultFrom") == {"source": "honors", "seasonTable": "NCAA Third Round"}, str(rows[2005]))
    ok("FIX a College Cup year with no NCAA result in the table gets one",
       rows[2006]["ncaaResult"] == "NCAA College Cup", str(rows[2006]))
    ok("FIX a quarterfinal row in a College Cup year becomes a College Cup",
       rows[2007]["ncaaResult"] == "NCAA College Cup", str(rows[2007]))
    ok("FIX a runner-up year takes the runner-up finish, not the College Cup",
       rows[2003]["ncaaResult"] == "NCAA Runner-up", str(rows[2003]))
    ok("FIX a title year whose row says only 'Final' becomes champions",
       rows[2001]["ncaaResult"] == "NCAA Champions", str(rows[2001]))
    ok("FIX exactly those five years change", changed == [2001, 2003, 2005, 2006, 2007], str(changed))
    ok("CONTROL rows at their list's finish are left as written",
       [rows[y]["ncaaResult"] for y in (2002, 2004, 2008, 2009)]
       == ["NCAA Champions", "NCAA College Cup Runner-up", "NCAA College Cup Semifinals", "NCAA T-3rd"],
       str([rows[y]["ncaaResult"] for y in (2002, 2004, 2008, 2009)]))
    ok("CONTROL a year no Honors list names is untouched",
       rows[2010] == {"year": 2010, "ncaaResult": "NCAA Third Round"}, str(rows[2010]))
    levels = {t: build.ncaa_finish_level(t) for t in ("NCAA Semifinal", "NCAA Quarterfinal", "NCAA Final 4",
                                                     "NCAA Finals", "NCAA 2nd", "NCAA Division I Women's Soccer Championship")}
    ok("CONTROL 'Semifinal', 'Quarterfinal' and 'Final 4' are not a final; 'Championship' is not a title",
       levels == {"NCAA Semifinal": 1, "NCAA Quarterfinal": 0, "NCAA Final 4": 1, "NCAA Finals": 2, "NCAA 2nd": 2,
                  "NCAA Division I Women's Soccer Championship": 0}, str(levels))


def test_stanford_2014() -> None:
    print("stanford: 2014 is a College Cup in Honors and in the season table")
    registry = common.load_registry()
    program = next(p for p in common.iter_programs(registry) if p["slug"] == "stanford")
    profile = build.build_profile(program, registry, build.load_rpi_history(), build.load_rpi_finals(registry["season"]["current"]))
    s2014 = next((s for s in profile["seasons"] if s["year"] == 2014), {})
    ok("CONTROL Honors lists 2014 as a College Cup", 2014 in profile["program"]["collegeCups"],
       str(profile["program"]["collegeCups"]))
    ok("FIX the 2014 season row says College Cup, not 'Third Round'", s2014.get("ncaaResult") == "NCAA College Cup",
       str(s2014.get("ncaaResult")))
    ok("CONTROL 2013, a Third Round year in no Honors list, is untouched",
       next((s for s in profile["seasons"] if s["year"] == 2013), {}).get("ncaaResult") == "NCAA Third Round")


def test_every_program() -> None:
    print("every published program: no season row below the finish its Honors vouch for")
    registry = common.load_registry()
    hist, finals = build.load_rpi_history(), build.load_rpi_finals(registry["season"]["current"])
    bad, checked = [], 0
    for program in build.published_programs(registry):
        wiki = common.load_source(program["slug"], "wikipedia")
        if not wiki:
            continue
        checked += 1
        section = build.build_program_section(program, wiki, common.load_source(program["slug"], "athletics"))
        seasons = build.build_seasons(program, wiki, common.load_source(program["slug"], "athletics"), hist, finals, registry)
        build.reconcile_ncaa_results(seasons, section)
        for s in seasons:
            want = next((lvl for key, lvl, _ in build.HONOR_FINISHES if s["year"] in (section.get(key) or [])), None)
            have = build.ncaa_finish_level(s.get("ncaaResult"))
            if want and (have is None or have < want):
                bad.append((program["slug"], s["year"], s.get("ncaaResult")))
    ok(f"FIX none of {checked} programs with a Wikipedia source publishes a season below its Honors", not bad, str(bad))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_synthetic, test_stanford_2014, test_every_program):
        try:
            case()
        except Exception as e:  # a case that raises is a failed case, not a lost run
            ok(f"{case.__name__} raised", False, repr(e))
    print(f"{TOTAL - len(FAILS)}/{TOTAL} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
