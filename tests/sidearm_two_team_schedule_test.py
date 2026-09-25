"""The legacy Sidearm schedule's two-team rows: dates and results (issue #302, daemen).

    python tests/sidearm_two_team_schedule_test.py            # everything below, offline
    python tests/sidearm_two_team_schedule_test.py --verbose  # print every check, not only the failures

daemen's stored schedules had 17-19 games a season with no dates and no results, so the build published no
record for it. Its schedule page is the legacy theme (li.sidearm-schedule-game rows) in a variant this
parser did not read:
  - there is no .sidearm-schedule-game-opponent-date; the date is in .sidearm-schedule-game-date, weekday
    first ('Sat, Aug 30');
  - each side's goals sit in its own .sidearm-schedule-game-result, under
    .sidearm-schedule-game-team-opponent and .sidearm-schedule-game-team-school, with no W/L/T letter.

The fixture, tests/fixtures/sidearm/schedule-legacy-two-team.html, is SYNTHETIC: made-up schools and
places, no people, with the structure of daemen's 2025 page. It has six rows: a win, a loss, a tie
(tournament, seeded opponent), a cancelled game, an unplayed game, and an exhibition.

Over the real cached pages (1,201 Sidearm schedule pages), this change alters exactly one parse, daemen 2025:
dated 0 -> 18 and results 0 -> 18, each result agreeing with the row's own W/L/T class. That count is
from the PR, not re-run here, because the cache is not in the repository.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bs4 import BeautifulSoup  # noqa: E402

from collect.adapters import sidearm  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sidearm", "schedule-legacy-two-team.html")
LEGACY = os.path.join(ROOT, "tests", "fixtures", "sidearm", "schedule-legacy.html")
BASE = "https://example.invalid"

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:400]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def test_two_team() -> None:
    print("two-team rows: the synthetic fixture")
    html = open(FIXTURE, encoding="utf-8").read()
    s = sidearm.parse_schedule(html, BASE)
    g = {x["opponent"]: x for x in s["games"]}
    ok("the legacy branch reads all six rows, season from the title", s["season"] == 2025 and len(s["games"]) == 6,
       (s["season"], [x["opponent"] for x in s["games"]]))
    ok("FIX a win: date from 'Sat, Aug 30', W 3-1 (own goals first)",
       (g["Northfield College"]["date"], g["Northfield College"]["result"], g["Northfield College"]["score"]) == ("2025-08-30", "W", "3-1"),
       g.get("Northfield College"))
    ok("FIX a loss: 'Thurs, Sept 4' is read, L 0-2",
       (g["Lakeside University"]["date"], g["Lakeside University"]["result"], g["Lakeside University"]["score"]) == ("2025-09-04", "L", "0-2"),
       g.get("Lakeside University"))
    hill = g.get("Hillcrest College") or {}
    ok("FIX a level score is a tie, and the seed comes off the name",
       (hill.get("date"), hill.get("result"), hill.get("score"), hill.get("opponentSeed")) == ("2025-11-01", "T", "1-1", 2), hill)
    ok("FIX a cancelled game is dated and has no result", (g["Riverton State"]["date"], g["Riverton State"]["result"], g["Riverton State"]["score"])
       == ("2025-10-08", None, None), g.get("Riverton State"))
    ok("FIX an unplayed game is dated and has no result", (g["TBD"]["date"], g["TBD"]["result"]) == ("2025-11-09", None), g.get("TBD"))
    ex = g.get("Brookfield College") or {}
    ok("an exhibition keeps its result and is marked exhibition", ex.get("exhibition") is True and ex.get("result") == "W", ex)
    ok("home/away and conference come from the row as before",
       [x["homeAway"] for x in s["games"]] == ["H", "A", "H", "A", "H", "H"] and g["Lakeside University"]["conferenceGame"] is True
       and g["Northfield College"]["conferenceGame"] is False, [x["homeAway"] for x in s["games"]])
    ok("links are read as before", set(g["Northfield College"]["links"]) >= {"box score", "recap"}, g["Northfield College"]["links"])
    # the parser's result against the row's own W/L/T class, which it does not read
    rows = BeautifulSoup(html, "html.parser").select("li.sidearm-schedule-game")
    classes = [next((c for c in li.get("class", []) if c in ("W", "L", "T")), None) for li in rows]
    ok("every result agrees with the row's W/L/T class", [x["result"] for x in s["games"]] == classes, classes)


def test_unchanged() -> None:
    print("unchanged: a standard legacy page, and a row with the date element but no two-team block")
    before = sidearm.parse_schedule(open(LEGACY, encoding="utf-8").read(), BASE)
    ok("the standard legacy fixture still parses with its dates and results",
       len(before["games"]) > 0 and all(x["date"] for x in before["games"]) and any(x["result"] for x in before["games"]))
    # a two-team block alongside an opponent-date element: the date element wins, as before
    html = open(FIXTURE, encoding="utf-8").read().replace(
        '<div class="sidearm-schedule-game-date"><span>Sat, Aug 30</span></div>',
        '<div class="sidearm-schedule-game-date"><span>Sat, Aug 30</span></div>'
        '<div class="sidearm-schedule-game-opponent-date"><span>Aug 31 (Sun)</span></div>', 1)
    g = sidearm.parse_schedule(html, BASE)["games"][0]
    ok("a row with .sidearm-schedule-game-opponent-date keeps the legacy date path", g["date"] == "2025-08-31", g)


def test_privacy() -> None:
    print("privacy: the fixture is synthetic")
    text = open(FIXTURE, encoding="utf-8").read()
    ok("no email address", not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text))
    ok("no phone number", not re.search(r"\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}", text))
    ok("says it is synthetic", "SYNTHETIC" in text and "daemen" in text.lower())
    ok("no real hostnames", not re.search(r"https?://(?!example\.invalid)", text))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for t in (test_two_team, test_unchanged, test_privacy):
        t()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
