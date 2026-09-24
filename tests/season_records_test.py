"""Regression tests for where a season's record comes from (issues #287, #223, #131).

    python tests/season_records_test.py            # everything below, offline
    python tests/season_records_test.py --verbose  # print every check, not only the failures

Synthetic data only: every program, Wikipedia row and schedule below is made up here, shaped like
what the collectors store, and nothing is read from programs/ or fetched. Exit 0 when every check
passes, 1 otherwise.

The rule under test (build_seasons): a season's record, and its conference record with it, comes
from the first source that holds up - a schedule that really is that season's (a result dated
August-December of that year, most dated games in that window), then Wikipedia with an impossible
overall/conference pair swapped back, then the NCAA's D1-only table. No games played is no record,
never 0-0-0. Every check except the preseason guard fails on the code before #287.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import build  # noqa: E402

CURRENT = 2026
REGISTRY = {"season": {"current": CURRENT}}
FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def game(date, result=None, conf=False, exhibition=False, opponent="Opponent"):
    return {"date": date, "result": result, "conferenceGame": conf, "exhibition": exhibition,
            "opponent": opponent, "homeAway": "H", "score": None}


def fall(year: int, results: str, conf_every: int = 0, start_month: int = 8) -> list[dict]:
    """One game per result letter ('W', 'L', 'T', '-' for not played yet), dated through the fall."""
    out = []
    for i, r in enumerate(results):
        month, day = start_month + i // 8, 1 + (i % 8) * 3
        out.append(game(f"{year}-{month:02d}-{day:02d}", None if r == "-" else r,
                        conf=bool(conf_every) and i % conf_every == 0, opponent=f"Opponent {i}"))
    return out


def run(wiki_rows=None, schedule=None, history=None, rpi_finals=None, slug="fixture"):
    """build_seasons on synthetic sources: (rows by year, build log)."""
    program = {"slug": slug, "division": "D1", "ids": {"ncaaName": "Fixture" if rpi_finals else None}}
    wiki = {"data": {"seasons": wiki_rows or []}}
    ath = {"data": {"schedule": schedule or {}, "scheduleHistory": history or {}, "staff": []}}
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        rows = build.build_seasons(program, wiki, ath, {}, rpi_finals or {}, REGISTRY)
    return {r["year"]: r for r in rows}, log.getvalue()


def wiki_row(year, record, conf=None):
    w, l, t = (int(x) for x in record.split("-"))
    return {"year": year, "label": str(year), "headCoach": "Coach", "record": record, "wins": w, "losses": l,
            "ties": t, "confRecord": conf, "confFinish": "3rd", "ncaaResult": None}


def test_stale_wikipedia():
    print("tennessee 2025: a stale Wikipedia row loses to the season's own schedule")
    games = [game("2025-08-06", exhibition=True), game("2025-08-10", exhibition=True)]
    games += fall(2025, "WWWWWWWWWWWWLLLLTTT", conf_every=2)
    rows, log = run([wiki_row(2025, "2-0-0", "0-0-0")], history={"2025": games})
    s = rows.get(2025, {})
    ok("record is the schedule's 12-4-3, not Wikipedia's 2-0-0", s.get("record") == "12-4-3", str(s.get("record")))
    ok("recordSource is schedule and gamesPlayed 19 (exhibitions excluded)",
       (s.get("recordSource"), s.get("gamesPlayed")) == ("schedule", 19), str((s.get("recordSource"), s.get("gamesPlayed"))))
    ok("confRecord comes from the schedule too, not Wikipedia's stale 0-0-0",
       s.get("confRecord") == "6-2-2", str(s.get("confRecord")))
    ok("Wikipedia's confFinish is kept", s.get("confFinish") == "3rd", str(s.get("confFinish")))
    ok("the 17-game gap is in the build log", "RECORD fixture 2025" in log, log)


def test_undated_unparsed():
    print("daemen: opponents only, no dates and no results -> no record anywhere")
    games = [game(None, opponent=f"vs Opponent {i}") for i in range(18)]
    rows, _ = run(schedule={"season": CURRENT, "games": games}, history={"2025": games[:17]})
    ok("no current-season record (was 0-0-0)", not (rows.get(CURRENT) or {}).get("record"), str(rows.get(CURRENT)))
    ok("no 2025 record (was 0-0-0)", not (rows.get(2025) or {}).get("record"), str(rows.get(2025)))
    ok("no row anywhere says 0-0-0", all(r.get("record") != "0-0-0" for r in rows.values()),
       str([r for r in rows.values() if r.get("record") == "0-0-0"]))


def test_copy_of_current():
    print("an old-season URL that served the current season is not that old season")
    cur = fall(CURRENT, "WWLTWL------")
    rows, _ = run(schedule={"season": CURRENT, "games": cur}, history={"2023": [dict(g) for g in cur]})
    ok("the 2026 copy does not become a 2023 record", not (rows.get(2023) or {}).get("record"), str(rows.get(2023)))
    ok("the current season still has its record", (rows.get(CURRENT) or {}).get("record") == "3-2-1",
       str(rows.get(CURRENT)))
    undated = [dict(g, date=None) for g in cur]
    rows, _ = run(schedule={"season": CURRENT, "games": undated}, history={"2023": [dict(g) for g in undated]})
    ok("nor does an undated copy of it", not (rows.get(2023) or {}).get("record"), str(rows.get(2023)))


def test_spring_page():
    print("gonzaga 2024: a spring schedule stored as the fall season")
    spring = [game(f"2024-04-{d:02d}", r) for d, r in ((13, "W"), (20, "L"), (27, "T"), (28, None))]
    rows, _ = run(history={"2024": spring})
    ok("a spring page with results gives no 2024 record", not (rows.get(2024) or {}).get("record"), str(rows.get(2024)))
    rows, _ = run(history={"2024": [dict(g, result=None) for g in spring]})
    ok("and one without results is not 0-0-0", not (rows.get(2024) or {}).get("record"), str(rows.get(2024)))


def test_swapped_wikipedia():
    print("florida 1995: Wikipedia's overall and conference columns swapped, no other source")
    rows, log = run([wiki_row(1995, "6-1-1", "14-4-2")])
    s = rows.get(1995, {})
    ok("the larger total is published as the overall record", s.get("record") == "14-4-2", str(s.get("record")))
    ok("and the smaller as the conference record", s.get("confRecord") == "6-1-1", str(s.get("confRecord")))
    ok("tagged wikipedia-swapped, 20 games", (s.get("recordSource"), s.get("gamesPlayed")) == ("wikipedia-swapped", 20),
       str((s.get("recordSource"), s.get("gamesPlayed"))))
    ok("and logged", "RECORD fixture 1995" in log and "swapped" in log, log)
    section = build.build_program_section({"slug": "fixture", "division": "D1"},
                                          {"data": {"seasons": [wiki_row(1995, "6-1-1", "14-4-2")]}}, None)
    ok("allTimeRecord adds the overall record, not the conference one",
       (section["allTimeRecord"]["wins"], section["allTimeRecord"]["losses"]) == (14, 4), str(section["allTimeRecord"]))


def test_one_game_gap():
    print("the schedule wins over a Wikipedia row one game longer")
    rows, log = run([wiki_row(2024, "10-5-2", "5-2-1")], history={"2024": fall(2024, "WWWWWWWWWWLLLLTT")})
    s = rows.get(2024, {})
    ok("record is the schedule's 10-4-2", s.get("record") == "10-4-2", str(s.get("record")))
    ok("recordSource schedule", s.get("recordSource") == "schedule", str(s.get("recordSource")))
    ok("Wikipedia's conference record is not paired with the schedule's overall", s.get("confRecord") is None,
       str(s.get("confRecord")))
    ok("the schedule being 1 game short is in the build log", "RECORD fixture 2024" in log, log)


def test_ncaa_last():
    print("the NCAA table is the last resort, labelled D1-only")
    finals = {2025: {"teams": [{"school": "Fixture", "rank": 40, "record": "9-7-2"}], "throughGames": "2025-12-08"}}
    rows, _ = run(rpi_finals=finals)
    s = rows.get(2025, {})
    ok("with no other source the NCAA record is published as ncaa-rpi-d1",
       (s.get("record"), s.get("recordSource"), s.get("gamesPlayed")) == ("9-7-2", "ncaa-rpi-d1", 18), str(s))
    # the Table's Record cell reads lastSeason from the index, so it needs the source to say "(D1 games)"
    p = {"slug": "fixture", "name": "Fixture", "seasons": sorted(rows.values(), key=lambda r: -r["year"]),
         "program": {"headCoach": {}}, "_build": {"completeness": 1, "stale": [], "builtAt": "x"}}
    last = (build.summary_row(p) or {}).get("lastSeason") or {}
    ok("the index's lastSeason carries recordSource ncaa-rpi-d1", last.get("recordSource") == "ncaa-rpi-d1", str(last))


def test_preseason():
    print("preseason guard: dated fixtures, nothing played yet (passes before #287 too)")
    rows, _ = run(schedule={"season": CURRENT, "games": fall(CURRENT, "-" * 17)})
    s = rows.get(CURRENT)
    ok("the current season keeps its row", s is not None, str(sorted(rows)))
    ok("in progress, not blank", bool((s or {}).get("inProgress")), str(s))


def test_no_results_current():
    print("a current season with dated fixtures and no results shows no record")
    s = run(schedule={"season": CURRENT, "games": fall(CURRENT, "-" * 17)})[0].get(CURRENT) or {}
    ok("record is empty, not 0-0-0", s.get("record") is None and "record" in s, str(s.get("record", "(absent)")))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    VERBOSE = ap.parse_args(argv).verbose
    for t in (test_stale_wikipedia, test_undated_unparsed, test_copy_of_current, test_spring_page,
              test_swapped_wikipedia, test_one_game_gap, test_ncaa_last, test_preseason, test_no_results_current):
        t()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
