"""Canceled and postponed games (issue #24).

    python tests/game_status_test.py            # everything below, offline
    python tests/game_status_test.py --verbose  # print every check, not only the failures

A game the school's schedule marks as not played had no status: it had no result, so it read "result pending" for
ever, counted in `scheduled` ("X of Y played"), and a non-current season holding one stayed `inProgress`. Now:

  * collect.common.game_status reads the box the parser already reads W/L/T from: canceled / cancelled, no contest
    and abandoned are 'canceled'; postponed, PPD and suspended are 'postponed'.
  * with_game_status sets `status` only on a game with NO result, and the key is absent on every other game: a
    forfeit, or a row the school rewrote with its result ('W 2-1, postponed from 9/1'), is a played game.
  * build._record_from_games leaves status games out of `scheduled` and counts them in `notPlayed`. A postponed
    game's make-up is its own row with its own result, and used to be counted twice. W/L/T cannot change.
  * build.build_seasons (the `played < scheduled` line, 1137) no longer keeps a non-current season in progress
    because of a canceled game - a change, for the better (the current season follows #249's RPI switch).

Every page here is SYNTHETIC: made-up schools and places, no people. Offline, no files written.

Swap-back proof: COLLEGEDASH_CODE_ROOT=<an export of origin/main> runs these checks against that code.
Labels: FIX checks fail against origin/main and pass after the change; GUARD checks pass on both.
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
from collect.adapters import sidearm, wmt  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "sidearm")
BASE = "https://example.invalid"
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


def card(opponent: str, *score_time: str) -> str:
    """One current-theme Sidearm game card: the opponent, and the tokens of its score-time box."""
    spans = "".join(f"<span>{t}</span>" for t in score_time)
    return (f'<div class="s-game-card @container/s-game-card-standard">'
            f'<div class="s-game-card__header__team-event-info"><p>{opponent}</p><p>Example Field</p></div>'
            f'<div class="s-game-card__header__game-score-time"><p>{spans}</p></div></div>')


def cards_page(*cards: str) -> str:
    return "<html><head><title>2026 Women's Soccer Schedule</title></head><body>" + "".join(cards) + "</body></html>"


def by_opp(games: list[dict]) -> dict:
    return {g["opponent"]: g for g in games}


def test_reader() -> None:
    print("the reader: common.game_status")
    gs = getattr(common, "game_status", None)
    want = {"Canceled": "canceled", "CANCELLED": "canceled", "Aug 21 (Thu) Canceled": "canceled",
            "Canceled / Weather Aug 21 (Thu) 7 p.m.": "canceled", "No Contest (Excessive Heat)": "canceled",
            "no contest (weather)": "canceled", "Abandoned": "canceled",
            "Postponed": "postponed", "PPD to 9/12": "postponed", "PPD/Weather": "postponed",
            "Postponed-Make up 9/15": "postponed", "Play suspended in the 70th minute": "postponed",
            "Suspended - Lightning": "postponed"}
    for text, value in want.items():
        got = gs(text) if gs else "no game_status"
        ok(f"FIX {text!r} -> {value}", got == value, got)
    for text in ("W, 2-1", "L 0-3", "T 1-1 (2OT)", "Aug 20 (Thu) 7 PM", "TBA", "FINAL", "", None, "Uncanceled policy", "Cancellation policy"):
        got = gs(text) if gs else None
        ok(f"GUARD {text!r} -> no status", got is None, got)


def test_sidearm_cards() -> None:
    print("Sidearm current theme: the score-time box")
    html = cards_page(card("Northfield College", "W,", "2-1", "Aug 20"),
                      card("Lakeside University", "Aug 22", "Canceled"),
                      card("Riverton State", "PPD to 9/12", "Aug 27", "7:00 PM"),
                      card("Hillcrest College", "No Contest (Excessive Heat)", "Aug 30", "1 PM"),
                      card("Brookfield College", "L,", "- Forfeit", "Sep 3"),
                      card("Easton College", "Sep 6", "7 PM"))
    g = by_opp(sidearm.parse_schedule(html, BASE)["games"])
    ok("GUARD the six cards parse, dated", len(g) == 6 and all(x["date"] for x in g.values()), [(k, v["date"]) for k, v in g.items()])
    ok("FIX 'Canceled' -> status canceled, no result", g["Lakeside University"].get("status") == "canceled"
       and g["Lakeside University"]["result"] is None, g["Lakeside University"])
    ok("FIX 'PPD to 9/12' -> status postponed", g["Riverton State"].get("status") == "postponed", g["Riverton State"])
    ok("FIX 'No Contest (Excessive Heat)' -> status canceled", g["Hillcrest College"].get("status") == "canceled", g["Hillcrest College"])
    ok("GUARD a forfeit keeps its result L and gets no status",
       g["Brookfield College"]["result"] == "L" and "status" not in g["Brookfield College"], g["Brookfield College"])
    ok("GUARD a win and an unplayed future game have no status key",
       "status" not in g["Northfield College"] and "status" not in g["Easton College"])


def test_rewritten_row() -> None:
    print("the rewritten-row shape: the school puts the result on the postponed row")
    html = cards_page(card("Northfield College", "W,", "2-1", "Postponed from 9/1", "Sep 4"))
    x = sidearm.parse_schedule(html, BASE)["games"][0]
    ok("GUARD it keeps its result W 2-1", (x["result"], x["score"]) == ("W", "2-1"), x)
    ok("GUARD it gets no status: it is a played game", "status" not in x, x)


def test_makeup_shape() -> None:
    print("the make-up shape: the original row stays Postponed, a new row carries the result")
    html = cards_page(card("Northfield College", "Aug 20", "W,", "3-0"),
                      card("Lakeside University", "Sep 1", "Postponed"),
                      card("Lakeside University", "Sep 15", "W,", "2-1"),
                      card("Riverton State", "Sep 20", "L,", "0-1"))
    games = sidearm.parse_schedule(html, BASE)["games"]
    orig = next((x for x in games if x["date"] == "2026-09-01"), {})
    make = next((x for x in games if x["date"] == "2026-09-15"), {})
    ok("FIX the original row: status postponed, no result", orig.get("status") == "postponed" and orig.get("result") is None, orig)
    ok("GUARD the make-up row: W 2-1, no status", make.get("result") == "W" and "status" not in make, make)
    rec = build._record_from_games(games)
    ok("FIX scheduled counts the game once: 3, not 4", rec["scheduled"] == 3, rec)
    ok("FIX notPlayed is 1", rec.get("notPlayed") == 1, rec)
    ok("GUARD the record is unchanged: 2-1-0, 3 played", (rec["text"], rec["played"]) == ("2-1-0", 3), rec)


def test_sidearm_legacy() -> None:
    print("Sidearm legacy theme: the result box, and the #302 two-team row's per-side boxes")
    raw = open(os.path.join(FIXTURES, "schedule-legacy-two-team.html"), encoding="utf-8").read()
    g = by_opp(sidearm.parse_schedule(raw, BASE)["games"])
    ok("FIX two-team row 'Canceled' in the school's own result box -> canceled", g["Riverton State"].get("status") == "canceled",
       g["Riverton State"])
    ok("GUARD the unplayed two-team row has no status", "status" not in g["TBD"], g["TBD"])
    sus = raw.replace('<div class="sidearm-schedule-game-result"><span>Canceled</span></div>',
                      '<div class="sidearm-schedule-game-result"><span>Suspended</span></div>')
    ok("GUARD the fixture edit took", sus != raw)
    g = by_opp(sidearm.parse_schedule(sus, BASE)["games"])
    ok("FIX two-team row 'Suspended' -> postponed", g["Riverton State"].get("status") == "postponed", g["Riverton State"])


def block(opponent: str, month_day: str, result_html: str) -> str:
    return (f'<div class="schedule-item-block schedule-item-block--home">'
            f'<div class="schedule-event-date__month-day">{month_day}</div>'
            f'<div class="schedule-item-team__opponent">{opponent}</div>'
            f'<div class="schedule-event-item-result">{result_html}</div></div>')


def test_wmt() -> None:
    print("WMT: the result element")
    html = ("<html><head><title>2026 Women's Soccer Schedule</title></head><body>"
            + block("Northfield College", "Aug 20", '<strong class="schedule-event-item-result__label">W</strong> 2-1')
            + block("Lakeside University", "Aug 22", '<strong class="schedule-event-item-result__label">Canceled</strong>')
            + block("Riverton State", "Aug 27", '<div class="schedule-event-item-result__text">Suspended - Lightning</div>')
            + block("Hillcrest College", "Aug 30", '<strong class="schedule-event-item-result__label">W</strong> 2-1 '
                    '<div class="schedule-event-item-result__text">Game abandoned with 0:30 remaining</div>')
            + "</body></html>")
    g = by_opp(wmt.parse_schedule(html, BASE)["games"])
    ok("GUARD the four block rows parse", len(g) == 4, list(g))
    ok("FIX 'Canceled' label -> canceled", g.get("Lakeside University", {}).get("status") == "canceled", g.get("Lakeside University"))
    ok("FIX 'Suspended - Lightning' -> postponed", g.get("Riverton State", {}).get("status") == "postponed", g.get("Riverton State"))
    hc = g.get("Hillcrest College", {})
    ok("GUARD 'W 2-1 Game abandoned...' keeps W and gets no status", hc.get("result") == "W" and "status" not in hc, hc)
    ok("GUARD a plain result has no status key", "status" not in g.get("Northfield College", {"status": 1}))


def test_record() -> None:
    print("build: a status game is not scheduled")
    games = [{"result": "W", "conferenceGame": True}, {"result": "L"}, {"result": "T"},
             {"status": "canceled"}, {"status": "postponed", "conferenceGame": True}, {"status": "canceled", "exhibition": True},
             {"date": "2099-09-01"}]
    rec = build._record_from_games(games)
    ok("FIX scheduled leaves out the two non-exhibition status games: 4", rec["scheduled"] == 4, rec)
    ok("FIX notPlayed counts them: 2 (the exhibition is not counted)", rec.get("notPlayed") == 2, rec)
    ok("GUARD W/L/T, played, conference record and exhibitions are unchanged",
       (rec["text"], rec["played"], rec["confText"], rec["exhibitions"]) == ("1-1-1", 3, "1-0-0", 1), rec)


def test_non_current_season_in_progress() -> None:
    print("build_seasons line 1137: a non-current season whose only unplayed game is canceled")
    reg = {"season": {"current": 2026, "gradYears": [2026, 2027, 2028, 2029], "finalRpiThrough": {}}}
    prog = {"slug": "alpha", "ids": {}, "division": "D2"}
    games = [{"date": "2025-09-01", "result": "W"}, {"date": "2025-09-05", "result": "L"},
             {"date": "2025-09-12", "result": "W"}, {"date": "2025-09-19", "status": "canceled"}]
    rows = build.build_seasons(prog, None, {"data": {"schedule": {"season": 2025, "games": games}}}, {}, {}, reg, None)
    s = next((r for r in rows if r.get("year") == 2025), {})
    ok("GUARD the 2025 season row exists with the schedule's record", s.get("record") == "2-1-0", s)
    ok("FIX it is not in progress (main kept it in progress for ever)", s.get("inProgress") is False, s.get("inProgress"))
    games[-1] = {"date": "2025-09-19"}
    rows = build.build_seasons(prog, None, {"data": {"schedule": {"season": 2025, "games": games}}}, {}, {}, reg, None)
    s = next((r for r in rows if r.get("year") == 2025), {})
    ok("GUARD with the same game unplayed and no status, it stays in progress", s.get("inProgress") is True, s.get("inProgress"))


def test_log_line() -> None:
    print("the refresh log line: counts only")
    line_fn = getattr(common, "game_status_line", None)
    games = [{"status": "canceled"}, {"status": "canceled"}, {"status": "postponed"}, {"result": "W"}]
    got = line_fn("2026", games) if line_fn else None
    ok("FIX '  2026 schedule: 2 canceled, 1 postponed'", got == "  2026 schedule: 2 canceled, 1 postponed", got)
    ok("FIX nothing to say -> None", bool(line_fn) and line_fn("2026", [{"result": "W"}]) is None)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    if CODE_ROOT != ROOT:
        print(f"code under test imported from {CODE_ROOT}")
    for case in (test_reader, test_sidearm_cards, test_rewritten_row, test_makeup_shape, test_sidearm_legacy, test_wmt,
                 test_record, test_non_current_season_in_progress, test_log_line):
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
