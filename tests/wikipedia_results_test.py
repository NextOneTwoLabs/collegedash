"""Checks for the NCAA result and conference finish read from a Wikipedia seasons table (issue #176).

    python tests/wikipedia_results_test.py            # everything below, offline
    python tests/wikipedia_results_test.py --verbose  # print every check, not only the failures

Offline: reads the seasons tables under tests/fixtures/wikipedia/ (Wikipedia text, CC BY-SA 4.0). Each fixture
parses to exactly the seasons its full cached page gives.

Swap-back proof: set COLLEGEDASH_CODE_ROOT to an export of origin/main's collect/ package:

    git archive origin/main collect | tar -x -C /tmp/pre176
    COLLEGEDASH_CODE_ROOT=/tmp/pre176 python tests/wikipedia_results_test.py

Why this exists
---------------
_seasons_table took a season's NCAA result from the first cell mentioning 'NCAA' and, in tables that split wins,
losses and ties into columns, otherwise from the last text cell in the row, prefixed 'NCAA '. That cell was often
not the NCAA column: clemson's 'Top points' players ('NCAA Hal Hershfelt / Maliah Morris', 2021), its conference
finish ('NCAA 11th', 2009), the conference tournament ('NCAA Runner up' for north-dakota-state 2000, whose NCAA
cell is a dash), 'No Conference' notes, 'DNQ' (saint-louis). Where the table did head an NCAA column with plain
round names (north-carolina 'Champions', old-dominion '1st round'), nothing was read. The conference finish had
the same fault in a milder form: the first ordinal anywhere in the row (campbell's 'NAIA Tournament 5th place',
siue's 'OVC Tournament 2nd'). Both now come from the column whose header names them, when the table has one.

Labels: FIX checks fail against origin/main and pass after the change; CONTROL checks pass on both; GUARD checks
pass on origin/main only because it reads nothing there, and each sits beside a FIX check on the same table.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_ROOT = os.environ.get("COLLEGEDASH_CODE_ROOT") or ROOT
sys.path.insert(0, CODE_ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from bs4 import BeautifulSoup  # noqa: E402

from collect import wikipedia  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "wikipedia")
FAILS: list[str] = []
TOTAL = 0
VERBOSE = False
# what an NCAA result says: a round, a placing in the tournament, or 'College Cup'
RESULT = re.compile(r"^NCAA .*(round|final|champion|runner|sweet 16|elite|college cup|regional)", re.I)


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {ascii(detail)[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def by_year(slug: str) -> dict[int, dict]:
    with open(os.path.join(FIXTURES, slug + ".html"), encoding="utf-8") as f:
        return {s["year"]: s for s in wikipedia._seasons_table(BeautifulSoup(f.read(), "html.parser"))}


def ncaa(rows: dict[int, dict], year: int):
    return rows[year]["ncaaResult"] if year in rows else "(no season)"


def test_clemson() -> None:
    print("clemson: the NCAA column, not the players beside it")
    c = by_year("clemson")
    ok("FIX clemson 2021: 'NCAA First round' (the page's NCAA cell), not the 'Top points' players", ncaa(c, 2021) == "NCAA First round", str(ncaa(c, 2021)))
    ok("FIX clemson 2004: 'NCAA First round', not 'Courtney Foster/Lindsay Browne'", ncaa(c, 2004) == "NCAA First round", str(ncaa(c, 2004)))
    ok("FIX clemson 2009: no NCAA result (the NCAA cell is a dash), not 'NCAA 11th'", ncaa(c, 2009) is None, str(ncaa(c, 2009)))
    ok("CONTROL clemson 2009: '11th' is still the conference finish", c[2009]["confFinish"] == "11th", str(c[2009]["confFinish"]))
    ok("CONTROL clemson 2023: 'NCAA College Cup', read before and after", ncaa(c, 2023) == "NCAA College Cup", str(ncaa(c, 2023)))
    bad = {y: s["ncaaResult"] for y, s in c.items() if s["ncaaResult"] and not RESULT.search(s["ncaaResult"])}
    ok("FIX clemson: every stored NCAA result names a round or placing", not bad, str(bad))


def test_not_results() -> None:
    print("cells in or beside the NCAA column that are not tournament results")
    n = by_year("north-dakota-state")
    ok("FIX north-dakota-state 2004: 'Ineligible due to Transition to Division I' is no result (was 'NCAA No Conference')",
       ncaa(n, 2004) is None, str(ncaa(n, 2004)))
    ok("FIX north-dakota-state 2000: the conference tournament's 'Runner up' is not an NCAA result", ncaa(n, 2000) is None, str(ncaa(n, 2000)))
    ok("FIX north-dakota-state 1997: the finish '4th' is not an NCAA result", ncaa(n, 1997) is None, str(ncaa(n, 1997)))
    ok("CONTROL north-dakota-state 1997 and 2000: the finish is '4th'", n[1997]["confFinish"] == "4th" and n[2000]["confFinish"] == "4th",
       str((n[1997]["confFinish"], n[2000]["confFinish"])))
    s = by_year("saint-louis")
    dnq = {y: v["ncaaResult"] for y, v in s.items() if v["ncaaResult"] and "DNQ" in v["ncaaResult"]}
    ok("FIX saint-louis: 'DNQ' (did not qualify) is no result, in any season", not dnq, str(dnq))
    b = by_year("boston-college")
    ok("FIX boston-college 1994: the conference tournament's 'Runner up' is not an NCAA result", ncaa(b, 1994) is None, str(ncaa(b, 1994)))
    ok("FIX boston-college 1980: an empty NCAA cell is no result, not 'NCAA '", ncaa(b, 1980) is None, str(ncaa(b, 1980)))
    ok("CONTROL boston-college 2004 and 2009: 'NCAA Third Round', 'NCAA Quarterfinals'",
       (ncaa(b, 2004), ncaa(b, 2009)) == ("NCAA Third Round", "NCAA Quarterfinals"), str((ncaa(b, 2004), ncaa(b, 2009))))


def test_round_names_in_the_column() -> None:
    print("an NCAA column that holds bare round names")
    u = by_year("north-carolina")
    ok("FIX north-carolina 1982: 'NCAA Champions' from the 'NCAA tourn.' column", ncaa(u, 1982) == "NCAA Champions", str(ncaa(u, 1982)))
    ok("FIX north-carolina 1985: 'NCAA Runner up'", ncaa(u, 1985) == "NCAA Runner up", str(ncaa(u, 1985)))
    ok("GUARD north-carolina 1980 and 1981: 'AIAW Semifinals' / 'AIAW Champions' are not NCAA results",
       ncaa(u, 1980) is None and ncaa(u, 1981) is None, str((ncaa(u, 1980), ncaa(u, 1981))))
    o = by_year("old-dominion")
    ok("FIX old-dominion 1989: 'NCAA 1st round' from the 'NCAA' column (the 'Final ranking' beside it is not read)",
       ncaa(o, 1989) == "NCAA 1st round", str(ncaa(o, 1989)))
    ok("CONTROL old-dominion 1989: the finish '1st' from 'Conf. place'", o[1989]["confFinish"] == "1st", str(o[1989]["confFinish"]))


def test_finish_column() -> None:
    print("the conference finish from its own column")
    s = by_year("siue")
    ok("FIX siue 2019: 'T1st' from 'Standing', not '2nd' from 'OVC Tournament 2nd'", s[2019]["confFinish"] == "T1st", str(s[2019]["confFinish"]))
    ok("FIX siue 2017: a tie written 't-6th' is kept as 'T-6th'", s[2017]["confFinish"] == "T-6th", str(s[2017]["confFinish"]))
    w = by_year("wake-forest")
    ok("FIX wake-forest 2000: 'T-2nd' from 'Pos.', not the 'Conference Tourn. Pos.' column", w[2000]["confFinish"] == "T-2nd", str(w[2000]["confFinish"]))
    ok("CONTROL wake-forest 2000: a table with no NCAA column still reads 'NCAA 2nd Round' from its Honors cell",
       ncaa(w, 2000) == "NCAA 2nd Round", str(ncaa(w, 2000)))
    c = by_year("campbell")
    ok("FIX campbell 1969: 'NAIA Tournament 5th place' is not a conference finish (the 'Standing' cell is empty)",
       c[1969]["confFinish"] is None, str(c[1969]["confFinish"]))


def test_unchanged() -> None:
    print("controls: what does not change")
    st = by_year("stanford")
    ok("CONTROL stanford 2019 and 2025: finish and NCAA result as before",
       (st[2019]["confFinish"], ncaa(st, 2019), st[2025]["confFinish"], ncaa(st, 2025)) == ("1st", "NCAA College Cup Champion", "1st", "NCAA College Cup Runner-up"),
       str((st[2019], st[2025])))
    c = by_year("clemson")
    ok("CONTROL clemson 2021: coach, record and conference record untouched",
       (c[2021]["headCoach"], c[2021]["record"], c[2021]["confRecord"]) == ("Eddie Radwanski", "12-7-1", "6-3-1"), str(c[2021]))


def test_header_layout() -> None:
    print("_result_columns: which columns the header names")
    columns = getattr(wikipedia, "_result_columns", None)
    html = ("<table>"
            "<tr><th rowspan='3'>Season</th><th>Head coach</th><th colspan='3'>Result</th><th colspan='2'>Tournaments</th></tr>"
            "<tr><th>W</th><th>L</th><th>Finish</th><th>Conference</th><th>NCAA</th></tr>"
            "<tr><th colspan='7'>Jane Doe (NCAA Division I, Some Conference, 3rd place) (1990–1999)</th></tr>"
            "<tr><td>1990</td><td>Jane Doe</td><td>1</td><td>2</td><td>3rd</td><td>Runner up</td><td>First round</td></tr>"
            "</table>")
    rows = BeautifulSoup(html, "html.parser").find_all("tr")
    got = columns(rows, rows[3:], wikipedia._grid(rows)) if columns else None
    ok("FIX a header row one column short (no rowspan on 'Head coach') is right-aligned, and a divider row across "
       "the table names no column: NCAA is column 6, the finish column 4", got == (6, 4), str(got))
    html = ("<table><tr><th>Year</th><th>Overall</th><th>NCAA W–L</th><th>NCAA win pct</th><th>Conf. tourn. pos.</th>"
            "<th>Conf. place</th><th>Final ranking</th><th>NCAA</th></tr>"
            "<tr><td>2001</td><td>10–5–2</td><td>1–1</td><td>.500</td><td>3rd</td><td>2nd</td><td>19th</td><td>2nd round</td></tr></table>")
    rows = BeautifulSoup(html, "html.parser").find_all("tr")
    got = columns(rows, rows[1:], wikipedia._grid(rows)) if columns else None
    ok("FIX tallies ('NCAA W–L', 'NCAA win pct', south-carolina) are not the NCAA result column, and a conference "
       "tournament position ('Conf. tourn. pos.', wake-forest) is not the finish: NCAA is column 7, the finish column 5",
       got == (7, 5), str(got))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    if CODE_ROOT != ROOT:
        print(f"code under test imported from {CODE_ROOT}")
    for case in (test_clemson, test_not_results, test_round_names_in_the_column, test_finish_column, test_unchanged, test_header_layout):
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
