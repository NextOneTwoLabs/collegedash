"""Checks for the head coach read from a Wikipedia seasons table (issue #175).

    python tests/wikipedia_coach_test.py            # everything below, offline
    python tests/wikipedia_coach_test.py --verbose  # print every check, not only the failures

Offline: reads the seasons tables under tests/fixtures/wikipedia/ (Wikipedia text, CC BY-SA 4.0).

Swap-back proof: set COLLEGEDASH_CODE_ROOT to an export of origin/main's collect/ package:

    git archive origin/main collect | tar -x -C /tmp/pre175
    COLLEGEDASH_CODE_ROOT=/tmp/pre175 python tests/wikipedia_coach_test.py

Why this exists
---------------
_seasons_table took a season's coach from the first name-like cell in the row. When the coach cell spans
many seasons by rowspan, the rows it covers carry no coach cell of their own, and the first name-like cell
left was whatever came next: clemson's 'Top points' player (Makenna Morris 2023, Kendall Bodak 2024, JuJu
Harris 2025), the conference name on nicholls, lamar, houston-christian, old-dominion and south-florida
('Southland', 'C-USA', 'Independent'), lsu's division ('West'), north-dakota-state's 'Ineligible due to
Transition to Division I'. On wake-forest, whose table has no coach column at all, every season's 'coach'
was that season's top scorer. The coach now comes from the column headed 'coach', with rowspans and
colspans laid out; a table without one never reads a name from a column headed as players.

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

from bs4 import BeautifulSoup  # noqa: E402

from collect import wikipedia  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "wikipedia")
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


def seasons(slug: str) -> list[dict]:
    with open(os.path.join(FIXTURES, slug + ".html"), encoding="utf-8") as f:
        return wikipedia._seasons_table(BeautifulSoup(f.read(), "html.parser"))


def coach_by_year(slug: str) -> dict[int, str | None]:
    return {s["year"]: s["headCoach"] for s in seasons(slug)}


def test_rowspanned_coach() -> None:
    print("a coach cell that spans seasons by rowspan")
    c = coach_by_year("clemson")
    for year in (2013, 2018, 2020, 2023, 2024, 2025):
        ok(f"FIX clemson {year}: Eddie Radwanski, not the season's top points player", c.get(year) == "Eddie Radwanski", str(c.get(year)))
    ok("FIX clemson 2002-2007: Todd Bramble in every season", all(c.get(y) == "Todd Bramble" for y in range(2002, 2008)),
       str({y: c.get(y) for y in range(2002, 2008)}))
    ok("FIX clemson: no season's coach is a name from the 'Top points' or 'Top scorer' columns",
       not {"Makenna Morris", "Kendall Bodak", "JuJu Harris", "Megan Bornkamp", "Catrina Atanda"} & set(c.values()), str(set(c.values())))
    ok("CONTROL clemson 2011 and 2012 (where the Radwanski cell itself sits) were already right",
       c.get(2011) == "Eddie Radwanski" and c.get(2012) == "Eddie Radwanski", str((c.get(2011), c.get(2012))))
    s = coach_by_year("south-florida")
    ok("FIX south-florida 1995-2006: T. Logan Fleck, not 'Independent' or 'Big East'",
       all(s.get(y) == "T. Logan Fleck" for y in range(1995, 2007)), str({y: s.get(y) for y in range(1995, 2007)}))
    ok("CONTROL south-florida 2018: Denise Schilte-Brown", s.get(2018) == "Denise Schilte-Brown", str(s.get(2018)))


def test_conference_names() -> None:
    print("a conference name is not a coach")
    n = coach_by_year("nicholls")
    ok("FIX nicholls: no season's coach is 'Southland'", "Southland" not in n.values(), str(sorted(set(map(str, n.values())))))
    ok("FIX nicholls 2009-2015: Dylan Harrison; 2016-2018: Michael \"Mac\" McBride",
       all(n.get(y) == "Dylan Harrison" for y in range(2009, 2016)) and all(n.get(y) == 'Michael "Mac" McBride' for y in range(2016, 2019)),
       str({y: n.get(y) for y in range(2009, 2019)}))
    lm = coach_by_year("lamar")
    ok("FIX lamar 2007: P. Matthew \"Matt\" Dillon (a quoted nickname is part of a name)", lm.get(2007) == 'P. Matthew "Matt" Dillon', str(lm.get(2007)))
    ok("FIX lamar 2016-2020: Steve Holeman, not 'Southland'", all(lm.get(y) == "Steve Holeman" for y in range(2016, 2021)),
       str({y: lm.get(y) for y in range(2016, 2021)}))


def test_no_coach_column() -> None:
    print("a table with no coach column, only player columns")
    w = coach_by_year("wake-forest")
    ok("FIX wake-forest: no season has a coach read from 'Top points' / 'Top scorer'", all(v is None for v in w.values()),
       str({y: v for y, v in w.items() if v}))
    ok("CONTROL wake-forest: the table still yields all its seasons", len(w) == 32, str(len(w)))
    cb = coach_by_year("campbell")
    ok("CONTROL campbell (no coach header, no player columns): the first name-like cell is still read",
       cb.get(1976) == "Darrell Saunders" and cb.get(2019) is not None, str((cb.get(1976), cb.get(2019))))


def test_unchanged_elsewhere() -> None:
    print("controls: what does not change")
    st = coach_by_year("stanford")
    ok("CONTROL stanford: Paul Ratcliffe from 2003", st.get(2003) == "Paul Ratcliffe" and st.get(2025) == "Paul Ratcliffe", str((st.get(2003), st.get(2025))))
    cl = {s["year"]: s for s in seasons("clemson")}
    ok("CONTROL clemson: records, conference records and finishes are read as before",
       (cl[2023]["record"], cl[2023]["confRecord"], cl[2023]["confFinish"]) == ("18-4-4", "7-2-1", "3rd"), str(cl[2023]))
    ok("CONTROL clemson: the NCAA result is read exactly as before this change (its own column mapping is a separate fault)",
       cl[2023]["ncaaResult"] == "NCAA College Cup" and cl[2021]["ncaaResult"] == "NCAA Hal Hershfelt/Maliah Morris", str((cl[2023]["ncaaResult"], cl[2021]["ncaaResult"])))


def test_grid() -> None:
    print("the rowspan/colspan grid")
    grid = getattr(wikipedia, "_grid", None)
    html = ("<table><tr><td rowspan='2'>A</td><td colspan='2'>B</td></tr><tr><td>C</td><td>D</td></tr>"
            "<tr><td>E</td><td>F</td><td>G</td></tr></table>")
    rows = BeautifulSoup(html, "html.parser").find_all("tr")
    ok("FIX rowspan and colspan are laid out on columns", grid is not None and grid(rows) == [["A", "B", "B"], ["A", "C", "D"], ["E", "F", "G"]],
       str(grid(rows) if grid else None))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    if CODE_ROOT != ROOT:
        print(f"code under test imported from {CODE_ROOT}")
    for case in (test_rowspanned_coach, test_conference_names, test_no_coach_column, test_unchanged_elsewhere, test_grid):
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
