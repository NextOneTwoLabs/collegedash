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
    """Every synthetic row here is a season-table row."""
    seasons = [{"year": y, "ncaaResult": r} for y, r in rows]
    changed = build.reconcile_ncaa_results(seasons, program, {y for y, _ in rows})
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
    seasons = [{"year": 2007, "rpiRank": 3, "rpi": {"rank": 3}}, {"year": 2008, "ncaaResult": "NCAA Third Round"}]
    changed = build.reconcile_ncaa_results(seasons, {"collegeCups": [2007, 2008]}, {2008})
    ok("FIX an RPI-only season (no season-table row) in a College Cup year is left without a result",
       seasons[0] == {"year": 2007, "rpiRank": 3, "rpi": {"rank": 3}} and changed == [2008], f"{seasons} {changed}")


# How far each season-table NCAA result went, written by hand from the words, not from build.py. It lists every
# result in the committed Wikipedia sources (test_every_program fails on one it does not know). None = a mention
# with no finish.
ORDER = ("first round", "second round", "third round", "round of 16", "quarterfinal", "College Cup", "runner-up",
         "champion")
FINISH = {
    "NCAA": None, "NCAA DI tournament appearance": None, "NCAA Division I Women's Soccer Championship": None,
    "NCAA 1st Round": "first round", "NCAA 1st round": "first round", "NCAA First Round": "first round",
    "NCAA First round": "first round", "NCAA first round": "first round", "NCAA tournament first round": "first round",
    "NCAA Tournament 1st Round": "first round", "NCAA Div. II 1st round": "first round",
    "NCAA Round of 64": "first round",
    "NCAA 2nd Round": "second round", "NCAA 2nd round": "second round", "NCAA 2nd round [ 6 ]": "second round",
    "NCAA Second Round": "second round", "NCAA Second round": "second round",
    "NCAA Division I second round": "second round", "NCAA Tournament 2nd Round": "second round",
    "NCAA Round of 32": "second round", "NCAA round of 32": "second round", "NCAA T-17th": "second round",
    "NCAA 3rd Round": "third round", "NCAA 3rd round": "third round", "NCAA Third Round": "third round",
    "NCAA Third round": "third round", "NCAA Division I third round": "third round",
    "NCAA Round of 16": "round of 16", "NCAA round of 16": "round of 16", "NCAA Sweet 16": "round of 16",
    "NCAA Sweet Sixteen": "round of 16",
    "NCAA Quarterfinal": "quarterfinal", "NCAA Quarterfinals": "quarterfinal", "NCAA quarterfinals": "quarterfinal",
    "NCAA Quarterfinalist": "quarterfinal", "NCAA Quarterfinals (Elite Eight)": "quarterfinal",
    "NCAA Division I quarterfinal": "quarterfinal", "NCAA Elite 8": "quarterfinal", "NCAA Elite Eight": "quarterfinal",
    "NCAA T-5th": "quarterfinal",
    "NCAA College Cup": "College Cup", "NCAA Semifinal": "College Cup", "NCAA Semifinals": "College Cup",
    "NCAA Semifinalist": "College Cup", "NCAA College Cup Semifinals": "College Cup",
    "NCAA Semifinals (Final Four)": "College Cup", "NCAA Final 4": "College Cup", "NCAA T-3rd": "College Cup",
    "NCAA Runner-up": "runner-up", "NCAA Runner-Up": "runner-up", "NCAA Runner up": "runner-up",
    "NCAA Runner Up": "runner-up", "NCAA College Cup Runner-up": "runner-up", "NCAA Finals": "runner-up",
    "NCAA 2nd": "runner-up",  # UCLA 2017, lost the final to Stanford
    "NCAA Champions": "champion", "NCAA Champion": "champion", "NCAA Champions (2nd title)": "champion",
    "NCAA College Cup Champion": "champion",
}
HONOR = (("nationalTitles", "champion"), ("nationalRunnerUp", "runner-up"), ("collegeCups", "College Cup"))


def rank(result: str | None) -> int | None:
    """Position in ORDER plus one, from the hand-written table; 0 for a mention with no finish, None for blank."""
    if not result:
        return None
    return ORDER.index(FINISH[result]) + 1 if FINISH[result] else 0


def test_finish_ranking() -> None:
    print("finish ranking: every season-table wording, graded by the hand-written table")
    ok("CONTROL build.NCAA_FINISHES names the same finishes in the same order", build.NCAA_FINISHES == ORDER,
       str(build.NCAA_FINISHES))
    wrong = {t: (build.ncaa_finish_level(t), rank(t)) for t in FINISH if build.ncaa_finish_level(t) != rank(t)}
    ok(f"FIX all {len(FINISH)} wordings rank as the table says", not wrong, str(wrong))
    exact = {t: build.ncaa_finish_level(t) for t in ("NCAA 1st Round", "NCAA 2nd Round", "NCAA Tournament 2nd Round")}
    ok("FIX 'NCAA 1st Round' and 'NCAA 2nd Round' are early rounds, not a title or a final",
       exact == {"NCAA 1st Round": 1, "NCAA 2nd Round": 2, "NCAA Tournament 2nd Round": 2}, str(exact))
    rows, changed = reconcile([(2001, "NCAA 1st Round"), (2002, "NCAA 2nd Round")],
                              {"nationalTitles": [2001], "nationalRunnerUp": [2002], "collegeCups": [2001, 2002]})
    ok("FIX a title year whose row says '1st Round' and a runner-up year saying '2nd Round' are corrected",
       changed == [2001, 2002] and rows[2001]["ncaaResult"] == "NCAA Champions"
       and rows[2002]["ncaaResult"] == "NCAA Runner-up", str(rows))


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
    print("every published D1 program: no season-table row below its Honors, graded by the hand-written table")
    registry = common.load_registry()
    hist, finals = build.load_rpi_history(), build.load_rpi_finals(registry["season"]["current"])
    bad, unknown, changed, no_row, checked, ucla_2007 = [], set(), [], [], 0, None
    for program in build.published_programs(registry):
        wiki = common.load_source(program["slug"], "wikipedia")
        if not wiki or program.get("division") != "D1":
            continue
        checked += 1
        table = {s["year"] for s in wiki["data"].get("seasons") or []}
        profile = build.build_profile(program, registry, hist, finals)
        for s in profile["seasons"]:
            if (program["slug"], s["year"]) == ("ucla", 2007):
                ucla_2007 = s
            if "ncaaResultFrom" in s:
                changed.append((program["slug"], s["year"]))
            if s["year"] not in table:
                if "ncaaResult" in s or "ncaaResultFrom" in s:
                    no_row.append((program["slug"], s["year"], s.get("ncaaResult")))
                continue
            if s.get("ncaaResult") and s["ncaaResult"] not in FINISH:
                unknown.add(s["ncaaResult"])
                continue
            want = next((ORDER.index(f) + 1 for key, f in HONOR if s["year"] in (profile["program"].get(key) or [])),
                        None)
            have = rank(s.get("ncaaResult"))
            if want and (have is None or have < want):
                bad.append((program["slug"], s["year"], s.get("ncaaResult")))
    ok("CONTROL every season-table NCAA result is in the hand-written table", not unknown, str(sorted(unknown)))
    ok(f"FIX none of {checked} D1 programs with a Wikipedia source publishes a season below its Honors", not bad,
       str(bad))
    ok("FIX no season without a season-table row gets an NCAA result (ucla 2007-09, usc 2007 and 2016, ...)",
       not no_row, str(no_row))
    ok("FIX UCLA 2007, a College Cup year with only an RPI row, is untouched",
       ucla_2007 is not None and "ncaaResult" not in ucla_2007 and "ncaaResultFrom" not in ucla_2007, str(ucla_2007))
    by_program = {slug: sum(1 for s, _ in changed if s == slug) for slug, _ in changed}
    ok("FIX the shipped data changes exactly 19 rows: florida-state 15, florida 2, south-carolina 1, stanford 1",
       by_program == {"florida-state": 15, "florida": 2, "south-carolina": 1, "stanford": 1}, str(changed))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_synthetic, test_finish_ranking, test_stanford_2014, test_every_program):
        try:
            case()
        except Exception as e:  # a case that raises is a failed case, not a lost run
            ok(f"{case.__name__} raised", False, repr(e))
    print(f"{TOTAL - len(FAILS)}/{TOTAL} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
