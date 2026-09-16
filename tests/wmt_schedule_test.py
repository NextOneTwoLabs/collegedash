"""Checks for the WMT schedule parser, and in particular the later WMT themes (issue #97).

    python tests/wmt_schedule_test.py            # everything below, offline
    python tests/wmt_schedule_test.py --verbose  # print every check, not only the failures

Offline: reads the fixtures under tests/fixtures/wmt/ and makes no request. Exit 0 when every check
passes, 1 otherwise.

Why these exist
---------------
30 D1 programs on WMT sites had no schedule. Every one had a full roster from the same run and a
cached schedule page served with HTTP 200; the parser simply found no game. Measured on those pages
(issue #97): 22 are 2025-redesign event cards, 4 redesign item blocks, 2 the older WordPress theme,
1 the Bordeaux template, and 1 (Notre Dame) is rendered in the browser and ships no games at all,
which no HTML parser can fix.

The redesign is one theme family, but each site names its fields differently, so the parser reads
fields by role. Each fixture is trimmed from a real cached page and pins one naming variant or one
trap, noted in the fixture's own header comment:

  redesign-default-event    schedule-default-event__name; our own rank BEFORE the divider; explicit
                            venue word; '(EXH)' in a name; a College Cup placeholder
  redesign-opponent-name    __opponent-name; a rank AFTER the 'at' divider is the opponent's
  redesign-current-team     our own rank inside a --current block while the label carries a divider
  redesign-teams-name       .schedule-event cards; both teams named, ours --current-team
  redesign-hide-on-desktop  our name as __name--hide-on-desktop; opponent in __opponent-heading
  redesign-title            the opponent as __title beside a promo line
  redesign-grid-date        'Aug 23 (Sun)' dates, a venue link, a tournament card with no result
  redesign-own-rank-first   '#24 at South Carolina': the #24 is Clemson's
  redesign-item-block       .schedule-item-block with 'vs. #21/20 Memphis' in __heading
  redesign-spring-after-fall  a '2025-26' page whose spring game, listed after the fall, is in 2026
  wordpress-table-row       gamecocksonline.com rows
  wordpress-item            ukathletics.com items
  bordeaux                  arkansasrazorbacks.com: season only in the <h1>, winner-first scores
  original-time-datetime    CONTROL, gostanford.com: must still go down the original branch

`test_origin_finds_nothing` is the swap-back proof kept in the suite: `_parse_schedule_original` is
origin/main's parse_schedule body, unmodified, and it must find zero games on every new fixture.
The PR's before-and-after run loaded origin/main's wmt.py itself over every cached page.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect.adapters import wmt  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "wmt")
BASE = "https://example.edu"

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


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name + ".html"), encoding="utf-8") as handle:
        return handle.read()


def parse(name: str) -> dict:
    return wmt.parse_schedule(fixture(name), BASE)


def row(g: dict) -> tuple:
    return (g["date"], g["homeAway"], g["opponent"], g["opponentRank"], g["result"], g["score"])


# (date, homeAway, opponent, opponentRank, result, score), in page order - read off the fixture text
EXPECTED = {
    "redesign-default-event": [
        ("2026-08-16", "H", "Liberty", None, "W", "2-0"),
        ("2026-08-05", "H", "Maryland (EXH)", None, None, None),
        ("2026-12-11", "N", "College Cup", None, None, None),
    ],
    "redesign-opponent-name": [
        ("2026-08-12", "A", "UCLA", 9, "W", "2-1"),
        ("2026-08-08", "H", "Idaho State", None, "W", "5-1"),
    ],
    "redesign-current-team": [
        ("2026-08-16", "H", "Northwestern State", None, "W", "5-0"),
        ("2026-08-12", "A", "Wake Forest", 18, "L", "0-2"),
    ],
    "redesign-teams-name": [
        ("2026-08-12", "H", "Texas State", None, "T", "2-2"),
        ("2026-08-08", "A", "Texas A&M-Corpus Christi", None, "T", "0-0"),
    ],
    "redesign-hide-on-desktop": [
        ("2026-08-15", "H", "Texas Tech", 23, "T", "0-0"),
        ("2026-08-13", "H", "Kansas State", None, "L", "0-4"),
    ],
    "redesign-title": [
        ("2026-08-16", "H", "Purdue Fort Wayne", None, "W", "7-1"),
        ("2026-08-05", "A", "Bowling Green", None, None, None),
    ],
    "redesign-grid-date": [
        ("2026-08-23", "H", "Buffalo", None, "W", "5-0"),
        ("2026-11-09", None, "Big 12 Tournament", None, None, None),
    ],
    "redesign-own-rank-first": [
        ("2026-08-20", "A", "South Carolina", None, "L", "0-1"),
        ("2026-08-16", "H", "Ohio State", 17, "T", "0-0"),
    ],
    "redesign-item-block": [
        ("2026-08-21", "H", "Memphis", 21, "W", "4-1"),
        ("2026-08-12", "H", "SMU", None, "W", "4-3"),
    ],
    "wordpress-table-row": [
        ("2026-08-16", "A", "Wake Forest", 18, "L", "0-3"),
        ("2026-08-12", "H", "Oregon State", None, "W", "2-0"),
    ],
    "wordpress-item": [
        ("2026-08-17", "H", "Kent State", None, "W", "5-2"),
        ("2026-08-08", "H", "Lexington SC (EXH)", None, None, None),
    ],
    "bordeaux": [
        ("2026-08-12", "H", "Baylor", None, "L", "1-4"),
        ("2026-08-08", "A", "Memphis", None, "L", "0-2"),
    ],
    "redesign-spring-after-fall": [
        ("2025-11-21", "A", "Vanderbilt", None, "L", "2-3"),
        ("2026-03-07", "A", "Georgia Southern", None, None, None),
    ],
}
SEASON = {name: 2026 for name in EXPECTED} | {"redesign-spring-after-fall": 2025}
NEW_FIXTURES = list(EXPECTED)


def test_games() -> None:
    print("every new fixture: games, in page order")
    for name, want in EXPECTED.items():
        out = parse(name)
        got = [row(g) for g in out["games"]]
        ok(f"{name}: {len(want)} games with date, home/away, opponent, rank, result and score", got == want,
           f"got {got}")
        ok(f"{name}: season {SEASON[name]}", out["season"] == SEASON[name], f"got {out['season']}")


def test_origin_finds_nothing() -> None:
    print("origin/main's parser finds no game on any new fixture")
    original = getattr(wmt, "_parse_schedule_original", None)
    for name in NEW_FIXTURES:
        n = len(original(fixture(name), BASE)["games"]) if original else "n/a"
        ok(f"{name}: origin/main's parse_schedule body returns 0 games", n == 0, f"got {n}")


def test_control_unchanged() -> None:
    print("control: a page the original branch parses goes down that branch, unchanged")
    html = fixture("original-time-datetime")
    original = getattr(wmt, "_parse_schedule_original", None)
    out = wmt.parse_schedule(html, BASE)
    ok("original-time-datetime: parse_schedule == the original branch's output",
       original is not None and out == original(html, BASE))
    ok("original-time-datetime: two games, full datetimes from <time datetime>",
       [(g["datetime"] or "")[:10] for g in out["games"]] == ["2026-08-08", "2026-08-16"],
       f"got {[g['datetime'] for g in out['games']]}")


def test_details() -> None:
    print("details")
    grid = parse("redesign-grid-date")["games"]
    ok("grid-date: the venue link is not a game link", grid and all("stadium" not in k for k in grid[0]["links"]),
       f"links {list(grid[0]['links']) if grid else None}")
    ok("grid-date: the game links are kept", grid and {"box score", "recap"} <= set(grid[0]["links"]),
       f"links {list(grid[0]['links']) if grid else None}")
    ok("grid-date: a tournament card with no result and no location is still read",
       len(grid) == 2 and grid[1]["location"] is None and grid[1]["result"] is None)
    virginia = parse("redesign-default-event")["games"]
    ok("default-event: an image-only link with only screen-reader text gets no key",
       virginia and "opens in a new window" not in virginia[0]["links"], f"links {list(virginia[0]['links']) if virginia else None}")
    ok("default-event: 'Maryland (EXH)' is an exhibition; 'Liberty' and 'College Cup' are not",
       [g["exhibition"] for g in virginia] == [True if "(EXH)" in g["opponent"] else False for g in virginia] == [False, True, False],
       f"got {[g['exhibition'] for g in virginia]}")
    ky = parse("wordpress-item")["games"]
    ok("wordpress-item: 'Lexington SC (EXH)' is an exhibition", len(ky) > 1 and ky[1]["exhibition"] is True)
    for label, want in (("Kansas State (Exh.)", True), ("Omaha (exhib.)", True), ("Auburn (Exhi.)", True),
                        ("British Columbia (EXHIBITION)", True), ("Exeter", False), ("Texas Tech", False)):
        ok(f"exhibition label {label!r} -> {want}", bool(wmt.EXHIBITION_RE.search(label)) is want)
    spring = parse("redesign-spring-after-fall")["games"]
    ok("spring-after-fall: the March game after the November one is dated the next calendar year",
       [g["date"] for g in spring] == ["2025-11-21", "2026-03-07"], f"got {[g['date'] for g in spring]}")
    utsa = parse("redesign-teams-name")["games"]
    ok("teams-name: a card whose promo says 'Exhibition' is flagged", len(utsa) > 1 and utsa[1]["exhibition"] is True)
    ark = parse("bordeaux")
    title = fixture("bordeaux").split("<title>")[1].split("</title>")[0]
    ok("bordeaux: the page <title> states no year; the season comes from the <h1>",
       "20" not in title and ark["season"] == 2026, f"title {title!r}, season {ark['season']}")
    ok("bordeaux: 'L, 4-1' is stored our-goals-first as 1-4", ark["games"] and ark["games"][0]["score"] == "1-4")
    ok("bordeaux: 'at Memphis' loses its divider and sets away", len(ark["games"]) > 1 and ark["games"][1]["opponent"] == "Memphis"
       and ark["games"][1]["homeAway"] == "A")
    sc = parse("wordpress-table-row")["games"]
    ok("wordpress-table-row: box score and recap links, resolved against the base URL",
       sc and sc[0]["links"].get("box score", "").startswith(BASE + "/boxscore/"), f"links {sc[0]['links'] if sc else None}")
    for label, want in (("at Memphis", "Memphis"), ("vs. UCF", "UCF"), ("@ Rice", "Rice"),
                        ("Atlantic 10 Championship", "Atlantic 10 Championship"), ("Vsu Classic", "Vsu Classic")):
        m = wmt.DIVIDER_RE.match(label)
        got = label[m.end():] if m else label
        ok(f"divider: {label!r} -> {want!r} ('at' and 'vs' only as whole words)", got == want, f"got {got!r}")
    nothing = wmt.parse_schedule("<html><head><title>Women's Soccer 2026</title></head><body>"
                                 "<div class='schedule-skeleton'></div></body></html>", BASE)
    ok("a browser-rendered skeleton page (fightingirish.com) still returns no games rather than inventing any",
       nothing["games"] == [])


def test_no_contact_details() -> None:
    print("privacy: no contact details in tests/fixtures/wmt/")
    spec = importlib.util.spec_from_file_location("camps_check", os.path.join(ROOT, "tools", "camps_check.py"))
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)
    names = sorted(f for f in os.listdir(FIXTURES) if f.endswith(".html"))
    # plus roster-mixed-theme-staff from issue #145 (tests/staff_fallback_test.py)
    ok("fixtures present (13 new + 1 control + 1 roster)", len(names) == 15, f"{len(names)}")
    for f in names:
        with open(os.path.join(FIXTURES, f), encoding="utf-8") as h:
            emails, phones = cc.contact_hits(h.read())
        ok(f"{f}: no email address or telephone number", not emails and not phones, f"{emails} {phones}")


def main() -> int:
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose
    test_games()
    test_origin_finds_nothing()
    test_control_unchanged()
    test_details()
    test_no_contact_details()
    print(f"\n{TOTAL - len(FAILS)}/{TOTAL} checks passed")
    if FAILS:
        for f in FAILS:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
