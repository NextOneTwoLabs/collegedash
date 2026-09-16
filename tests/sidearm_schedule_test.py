"""Checks for the Sidearm schedule parser, and in particular the legacy template (issue #35).

    python tests/sidearm_schedule_test.py            # everything below, offline
    python tests/sidearm_schedule_test.py --verbose  # print every check, not only the failures

Offline: reads four fixtures under tests/fixtures/sidearm/ and makes no request. Exit 0 when
every check passes, 1 otherwise.

Why these exist
---------------
160 of the 350 programs on the site had no schedule at all, and 159 of them were one cause: the
schedule page is served in Sidearm's older theme, whose games are `li.sidearm-schedule-game` rows
rather than `div.s-game-card-standard` cards. The pages were fetched fine (HTTP 200), were fully
server-rendered, and every one of those programs had a complete roster from the same run. Only the
schedule parser was missing.

The fixtures are trimmed from real cached pages, one row per behaviour worth pinning, and they are
chosen so each check has an input that makes it fail:

  legacy            eight real rows: an away loss with a score, a neutral-site tournament row, an
                    exhibition flagged in the location column rather than the opponent's name, a
                    canceled game, a tie, a ranked opponent, a conference game, and a bracket row
                    whose result box holds a *different* pairing's score
  no-title-year     LIU, whose schedule <title> states no year at all - the only such page in the
                    corpus - so the rows' own aria-labels have to supply it
  dual-template     CONSTRUCTED, and the file says so: no real page serves both templates as
                    elements, so this one pairs real current-theme cards with real legacy rows to
                    pin down which branch wins
  duplicate-links   one real current-theme card carrying two anchors labelled 'Box Score'

Issues #122 and #25 added four more, and a second reason to have them: exhibitions marked
'(EXH)', '(Exh.)', '(Exhib.)', '(EX)', '(EXB)', 'Exhibitions', '- EXH' or 'Scrimmage' were counted
in season records, and spring games listed after the fall block were dated a year early.

  exhibition-markers          CONSTRUCTED: seven real cards carrying seven spellings, plus three
                              REAL matches that look like markers - a game at Alumni Soccer
                              Stadium, an 'Alumni Day' promotion and a game in BOILING SPRINGS, NC
  legacy-exhibition-markers   CONSTRUCTED: the same question in the legacy theme
  spring-after-fall           one real page (xavier 2025): the last fall game and the spring games
                              printed after it, which belong to 2026
  legacy-spring-after-fall    one real page (navy 2023), including a Feb 29 row - a date that does
                              not exist in the season year, so the year must be the next one
  spring-descriptor-gap       one real page (oklahoma-state 2024): six of its seven spring cards
                              carry a '2025 Spring Exhibition Season' descriptor and the last one
                              does not. Read row by row it is a win, and it published the 2024
                              record as 15-5-3 where the school's release says 14-5-3 (PR #127 audit)

Issue #129 added two more, for the rankings and seeds that were left inside opponent names. Only
'#21 Ohio State' was ever read, and that is the one spelling the corpus no longer contains: 613
names on 294 cached pages carry one of the other forms.

  ranked-opponents            CONSTRUCTED: a real card for every spelling - No. N, RV, (RV), [N],
                              (N) with a rank behind it, No. N seed, #N Seed, #N Seeded, #a/Tb,
                              (N-Seed) with a poll pair behind it, #RV/N - and three rows that must
                              NOT be touched, including a row that begins with a year
  legacy-ranked-opponents     the same question in the legacy theme, where the decoration sits in
                              .sidearm-schedule-game-opponent-name

Every date these fixtures produce is also checked against the weekday the card prints. A weekday
cannot be ambiguous between two years one apart, so it is a self-contained oracle for the date
rules: the audit of PR #127 used it to confirm all 169 moved dates, including the 92 that no other
copy on the page could settle.

`test_matches_origin_behaviour` is the swap-back proof in miniature. `_parse_game_cards` is the
pre-change parser's body, unmodified; running it directly on the legacy fixtures and requiring
zero games is the same evidence as checking the fixture out against the old file, and it keeps
that evidence in the suite rather than in a reviewer's terminal history.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from bs4 import BeautifulSoup  # noqa: E402

from collect import common  # noqa: E402
from collect.adapters import sidearm  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "sidearm")
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
    return sidearm.parse_schedule(fixture(name), BASE)


def by_opponent(games: list[dict]) -> dict[str, dict]:
    return {g["opponent"]: g for g in games}


# --------------------------------------------------------------------------------------------
# the fixtures are legacy, and the pre-change parser found nothing in them

def test_matches_origin_behaviour() -> None:
    """Each legacy fixture yields zero games through the current-theme branch alone.

    Fails if `_parse_game_cards` ever starts matching legacy markup - at which point the legacy
    branch would stop running and these fixtures would stop proving anything.
    """
    print("origin behaviour")
    for name in ("schedule-legacy", "schedule-legacy-no-title-year"):
        html = fixture(name)
        soup = BeautifulSoup(html, "html.parser")
        cards = sidearm._parse_game_cards(soup, BASE, 2026)
        ok(f"{name}: the pre-change current-theme parser finds no games",
           cards == [], f"found {len(cards)}")
        ok(f"{name}: has no s-game-card-standard markup at all",
           "s-game-card-standard" not in html)
        ok(f"{name}: does have li.sidearm-schedule-game rows",
           len(soup.select("li.sidearm-schedule-game")) > 0)
        ok(f"{name}: parses to a non-empty schedule now", len(parse(name)["games"]) > 0)


# --------------------------------------------------------------------------------------------
# every field, on real rows

def test_legacy_fields() -> None:
    """The eight legacy rows, field by field."""
    print("legacy fields")
    result = parse("schedule-legacy")
    games = result["games"]
    ok("legacy: eight rows parse", len(games) == 8, f"got {len(games)}")
    ok("legacy: season comes from the page title", result["season"] == 2026, str(result["season"]))
    g = by_opponent(games)

    # away loss with a score and links. Fails if the result/score/link selectors move.
    si = g.get("Southern Illinois")
    ok("away loss: found", si is not None)
    if si:
        ok("away loss: homeAway is A", si["homeAway"] == "A", str(si["homeAway"]))
        ok("away loss: date", si["date"] == "2026-08-30", str(si["date"]))
        ok("away loss: result", si["result"] == "L", str(si["result"]))
        ok("away loss: score is kept as the site states it", si["score"] == "8-0", str(si["score"]))
        ok("away loss: location", si["location"] == "Carbondale, IL", repr(si["location"]))
        ok("away loss: box score link is absolute", si["links"].get("box score", "").startswith(BASE + "/"))
        ok("away loss: recap link present", "recap" in si["links"], str(sorted(si["links"])))
        ok("away loss: not flagged exhibition", si["exhibition"] is False)

    # a tie, which is a third result letter the W/L pair would miss
    nf = g.get("North Florida")
    ok("tie: found", nf is not None)
    if nf:
        ok("tie: result is T", nf["result"] == "T", str(nf["result"]))
        ok("tie: score", nf["score"] == "1-1", str(nf["score"]))
        ok("tie: homeAway is H", nf["homeAway"] == "H", str(nf["homeAway"]))

    # neutral site. Fails if the neutral class stops mapping to "N" (it would fall back to None).
    swac = g.get("Southwestern Athletic Conference")
    ok("neutral: found", swac is not None)
    if swac:
        ok("neutral: homeAway is N", swac["homeAway"] == "N", str(swac["homeAway"]))
        ok("neutral: a future row has no result", swac["result"] is None)
        ok("neutral: date", swac["date"] == "2026-11-11", str(swac["date"]))

    # ranked opponent: the rank leaves the name and becomes a number
    col = g.get("Colorado")
    ok("ranked: opponent name has no rank in it", col is not None,
       str([x["opponent"] for x in games if "Colorado" in x["opponent"]]))
    if col:
        ok("ranked: opponentRank is 17", col["opponentRank"] == 17, str(col["opponentRank"]))
    ok("ranked: no opponent name starts with '#'",
       not any(x["opponent"].startswith("#") for x in games))


def test_conference_needs_a_name() -> None:
    """A conference game is one whose conference node is *named*, not merely present.

    Every row in this fixture has a `.sidearm-schedule-game-conference` element; six of them are
    empty. A presence-only test would call every row a conference game, so the pair below is what
    makes this check able to fail.
    """
    print("conference")
    games = parse("schedule-legacy")["games"]
    soup = BeautifulSoup(fixture("schedule-legacy"), "html.parser")
    present = sum(1 for li in soup.select("li.sidearm-schedule-game")
                  if li.select_one(".sidearm-schedule-game-conference") is not None)
    ok("conference: the element is present on more rows than are conference games",
       present > 1, f"present on {present} rows")
    g = by_opponent(games)
    sh = g.get("Sacred Heart")
    ok("conference: the named row is a conference game", bool(sh and sh["conferenceGame"]))
    ok("conference: exactly one row is a conference game",
       sum(1 for x in games if x["conferenceGame"]) == 1,
       str([x["opponent"] for x in games if x["conferenceGame"]]))


def test_not_played_has_no_result() -> None:
    """A canceled row keeps no result and no score."""
    print("canceled")
    g = by_opponent(parse("schedule-legacy")["games"])
    wf = g.get("West Florida")
    ok("canceled: the row is still listed", wf is not None)
    if wf:
        ok("canceled: no result", wf["result"] is None, str(wf["result"]))
        ok("canceled: no score", wf["score"] is None, str(wf["score"]))
        ok("canceled: the date survives", wf["date"] == "2026-08-21", str(wf["date"]))
    raw = fixture("schedule-legacy")
    ok("canceled: the fixture really does say so", "Canceled" in raw)
    ok("canceled: 'Canceled' did not become the result letter",
       bool(wf) and wf["result"] != "C")


def test_a_score_needs_a_result() -> None:
    """A score is only this team's score when the box also states this team's result.

    Hawaii's tournament page lists another pairing in the bracket - the result box reads
    'Utah Valley vs. Washington State' with a 1-0 beside it and no W/L/T anywhere on the row.
    Reading the score on its own would file another team's result against this one.
    """
    print("score needs a result")
    games = parse("schedule-legacy")["games"]
    bracket = next((x for x in games if x["opponent"].startswith("Utah Valley")), None)
    ok("bracket row: found", bracket is not None,
       str([x["opponent"] for x in games]))
    if bracket:
        ok("bracket row: no result", bracket["result"] is None, str(bracket["result"]))
        ok("bracket row: and therefore no score", bracket["score"] is None, str(bracket["score"]))
    raw = fixture("schedule-legacy")
    ok("bracket row: the fixture really carries a bare score", "1-0" in raw)
    ok("no game anywhere has a score without a result",
       not any(x["score"] and not x["result"] for x in games),
       str([(x["opponent"], x["score"]) for x in games if x["score"] and not x["result"]]))


def test_exhibition_from_the_location_column() -> None:
    """Legacy marks some exhibitions in the location box, not in the opponent's name.

    Belmont's row names the opponent plainly and puts 'Exhibition' beside the venue. A check that
    only read the opponent name would miss it, so this is the row that makes the whole-row search
    necessary - and the same row proves the word does not survive into `location`.
    """
    print("exhibition")
    g = by_opponent(parse("schedule-legacy")["games"])
    bel = g.get("Belmont")
    ok("exhibition: found by opponent name alone", bel is not None)
    if bel:
        ok("exhibition: flagged", bel["exhibition"] is True)
        ok("exhibition: the opponent's name never said so", "exh" not in "Belmont".lower())
        ok("exhibition: 'Exhibition' is not left in the location",
           bel["location"] == "Huntsville, AL", repr(bel["location"]))
    ok("exhibition: exactly one exhibition in this fixture",
       sum(1 for x in parse("schedule-legacy")["games"] if x["exhibition"]) == 1)


def test_promotions_are_not_locations() -> None:
    """The match-day promotion nests inside the location box and must not become the venue."""
    print("promotions")
    raw = fixture("schedule-legacy")
    ok("promotion: the fixture carries a promotion inside a location box",
       "sidearm-schedule-game-opponent-promotion" in raw and "Appreciation Day" in raw)
    g = by_opponent(parse("schedule-legacy")["games"])
    nf = g.get("North Florida")
    ok("promotion: the promoted row's location is only the place",
       bool(nf) and nf["location"] == "Huntsville, AL", repr(nf and nf["location"]))
    ok("promotion: no location anywhere mentions the promotion",
       not any("Appreciation Day" in (x["location"] or "") for x in parse("schedule-legacy")["games"]))


def test_year_when_the_title_has_none() -> None:
    """LIU's schedule title states no year; the rows' aria-labels do.

    Two of these four rows carry an aria-label date and two do not, so both the per-row year and
    the page-level fallback have to work for all four to come out dated.
    """
    print("year without a title year")
    raw = fixture("schedule-legacy-no-title-year")
    title = re.search(r"<title>(.*?)</title>", raw, re.S)
    ok("no-title-year: the fixture's title really has no year",
       bool(title) and not re.search(r"(19|20)\d\d", title.group(1)), title.group(1) if title else "")
    ok("no-title-year: _season_from_title finds nothing",
       sidearm._season_from_title(BeautifulSoup(raw, "html.parser")) is None)

    result = parse("schedule-legacy-no-title-year")
    ok("no-title-year: the season is recovered from the rows", result["season"] == 2026,
       str(result["season"]))
    games = result["games"]
    ok("no-title-year: four rows parse", len(games) == 4, str(len(games)))
    ok("no-title-year: every row is dated",
       all(x["date"] for x in games), str([x["opponent"] for x in games if not x["date"]]))
    ok("no-title-year: every date is in the recovered season",
       all((x["date"] or "").startswith("2026-") for x in games),
       str([x["date"] for x in games]))

    g = by_opponent(games)
    # Iona's row states its own date in an aria-label; Mercyhurst's does not and needs the page.
    ok("no-title-year: aria-dated row", bool(g.get("Iona")) and g["Iona"]["date"] == "2026-08-13",
       str(g.get("Iona", {}).get("date")))
    ok("no-title-year: row with no aria date still dated",
       bool(g.get("Mercyhurst")) and g["Mercyhurst"]["date"] == "2026-09-20",
       str(g.get("Mercyhurst", {}).get("date")))


def test_current_theme_wins() -> None:
    """When both templates are on one page, the current-theme cards are what get parsed.

    This is the property that makes the change unable to alter a program that already parses:
    the legacy branch runs only on an empty result. Reversing the two branches, or concatenating
    them, fails here.
    """
    print("template precedence")
    raw = fixture("schedule-dual-template")
    soup = BeautifulSoup(raw, "html.parser")
    n_legacy = len(soup.select("li.sidearm-schedule-game"))
    ok("dual: the fixture really carries legacy rows", n_legacy == 3, str(n_legacy))
    ok("dual: the fixture really carries current-theme cards", "s-game-card-standard" in raw)

    games = parse("schedule-dual-template")["games"]
    ok("dual: only the current-theme cards are parsed", len(games) == 2, str(len(games)))
    names = {x["opponent"] for x in games}
    ok("dual: no legacy row leaked into the result",
       not (names & {"Southern Illinois", "Belmont", "Southwestern Athletic Conference"}),
       str(sorted(names)))
    ok("dual: the cards' own opponents are the ones returned",
       all("Mercy" in n or "Loyola" in n for n in names), str(sorted(names)))

    # and the legacy branch on its own would have produced those rows, so the precedence is real
    _, legacy_only = sidearm._parse_legacy_games(soup, BASE, 2026)
    ok("dual: the legacy branch alone would have returned the legacy rows",
       len(legacy_only) == 3, str(len(legacy_only)))


def test_duplicate_link_labels_keep_the_last() -> None:
    """Two anchors labelled 'Box Score' on one card: the last is the one stored.

    This is not hypothetical tidiness. Factoring the link map out of the current-theme branch so
    the legacy branch could share it silently turned last-wins into first-wins, and Wake Forest -
    the one program in the corpus that carries both a PDF and a live boxscore page under the same
    label - changed its stored links because of it. The card below is that card.
    """
    print("duplicate link labels")
    raw = fixture("schedule-duplicate-links")
    hrefs = [a["href"] for a in BeautifulSoup(raw, "html.parser").find_all("a", href=True)
             if re.sub(r"\s+", " ", a.get_text(" ", strip=True)).lower() == "box score"]
    ok("duplicate links: the fixture really carries two 'Box Score' anchors",
       len(hrefs) == 2, str(hrefs))
    ok("duplicate links: and the two point at different documents",
       len(set(hrefs)) == 2, str(hrefs))
    games = parse("schedule-duplicate-links")["games"]
    ok("duplicate links: the card parses to one game", len(games) == 1, str(len(games)))
    if games and len(hrefs) == 2:
        stored = games[0]["links"].get("box score", "")
        ok("duplicate links: the last anchor is the one stored",
           stored.endswith(hrefs[-1]), f"stored={stored} expected to end with {hrefs[-1]}")
        ok("duplicate links: and not the first",
           not stored.endswith(hrefs[0]), stored)
        ok("duplicate links: only one box score is kept",
           sum(1 for k in games[0]["links"] if k == "box score") == 1)


def test_both_branches_agree_on_the_contract() -> None:
    """A legacy game and a current-theme game are the same shape.

    build.py reads `result`, `exhibition` and `conferenceGame` off these dicts to compute a
    season record, so a key present in one branch and absent in the other is a silent data bug
    rather than a cosmetic one. Fails the moment either branch grows or drops a key.
    """
    print("output contract")
    legacy = parse("schedule-legacy")["games"]
    current = parse("schedule-dual-template")["games"]
    ok("contract: both fixtures produced games", bool(legacy) and bool(current))
    expected = {"date", "datetime", "exhibition", "conferenceGame", "homeAway",
                "opponent", "opponentRank", "opponentSeed", "location", "result", "score", "links"}
    ok("contract: current-theme keys are the documented set",
       set(current[0]) == expected, str(sorted(set(current[0]) ^ expected)))
    for game in legacy:
        if not ok(f"contract: legacy row '{game['opponent']}' has the same keys",
                  set(game) == expected, str(sorted(set(game) ^ expected))):
            break
    ok("contract: every legacy result is W, L, T or None",
       all(x["result"] in ("W", "L", "T", None) for x in legacy),
       str(sorted({str(x["result"]) for x in legacy})))
    ok("contract: every legacy homeAway is H, A, N or None",
       all(x["homeAway"] in ("H", "A", "N", None) for x in legacy),
       str(sorted({str(x["homeAway"]) for x in legacy})))
    ok("contract: every legacy date is ISO or None",
       all(x["date"] is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", x["date"]) for x in legacy),
       str([x["date"] for x in legacy]))
    ok("contract: datetime is not invented", all(x["datetime"] is None for x in legacy))
    ok("contract: every link is absolute",
       all(u.startswith("http") for x in legacy for u in x["links"].values()))


def test_fixtures_carry_no_contact_details() -> None:
    """No email address or phone number reaches the repository through these fixtures.

    tools/camps_check.py --fixtures enforces this for tests/fixtures/camps only, and this tree is
    not in its scope, so the same guard is applied here. Fails if a future fixture is trimmed from
    a page that carries a coach's address.
    """
    print("fixture privacy")
    email = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    phone = re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)")
    # Every .html in the tree, not only this suite's: the nine roster-* fixtures issue #33 added
    # are trimmed from staff directories, which is where a coach's address would come from.
    # tests/sidearm_staff_test.py scans those too; a contact detail has to get past both.
    names = sorted(f for f in os.listdir(FIXTURES) if f.endswith(".html"))
    # 20 until issue #145 added roster-no-staff, roster-players-and-staff and the two coaches-* pages
    # 25 since issue #160 added schedule-safelinks (its only address is placeholder@example.invalid)
    # 26 since issue #156 added roster-list-view-no-name-column (Mercyhurst, names are placeholders)
    # 27 since issue #183 added roster-list-view-table-reordered (hawaii-hilo, names are placeholders)
    ok("privacy: there are fixtures to check", len(names) == 27, str(names))
    for name in names:
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
            text = handle.read()
        found = [a for a in email.findall(text) if not a.endswith("example.invalid")]
        ok(f"privacy: {name} has no email address", not found, str(found[:3]))
        ok(f"privacy: {name} has no phone number", not phone.findall(text),
           str(phone.findall(text)[:3]))
        ok(f"privacy: {name} has no mailto: or tel: link",
           not re.search(r"(mailto|tel):(?!removed@example\.invalid|0000000000)", text, re.I))


# (date, homeAway, opponent, exhibition, result, score), in page order
MARKER_GAMES = [
    ("2026-08-05", "H", "Wofford", True, "T", "1-1"),                 # (EXH)
    ("2026-08-28", "A", "Shelbourne FC", True, "W", "3-0"),           # (Exh.)
    ("2026-08-05", "A", "Missouri State", True, "W", "4-0"),          # (exhib.)
    ("2026-08-07", "H", "Kennesaw State", True, "W", "3-0"),          # (Exb.)
    ("2026-08-03", "H", "South Florida", True, "W", "2-1"),           # 'South Florida - EXH'
    ("2026-08-05", "A", "Campbell", True, None, None),                # 'Exhibitions' beside the venue
    ("2026-08-04", None, "Oregon State", True, "W", "2-1"),           # (EX)
    ("2026-09-18", "A", "Notre Dame", False, "L", "2-3"),             # at Alumni Soccer Stadium
    ("2026-10-05", "H", "Ohio State", False, "T", "1-1"),             # 'Alumni Day' promotion; 'No. 21' is now a rank (#129)
    ("2026-10-01", "H", "Winthrop", False, "T", "0-0"),               # BOILING SPRINGS, NC
    ("2026-08-07", "H", "Furman", True, "T", "1-1"),                  # note really does say SCRIMMAGE
]
LEGACY_MARKER_GAMES = [
    ("2026-08-05", "A", "Georgia Southern University", True, "T", "1-1"),   # (EX)
    ("2026-08-06", "H", "LSU-Eunice", True, "W", "7-0"),                    # (Exhib.)
    ("2026-08-07", "H", "Snow College", True, "W", "5-1"),                  # (Scrimmage)
    ("2026-09-06", "H", "Presbyterian College", False, None, None),         # a real game
]
SPRING_GAMES = [("2025-09-20", "DePaul"), ("2026-02-20", "Ohio State"), ("2026-03-26", "Northern Kentucky")]
DESCRIPTOR_GAP_GAMES = [("2024-11-15", "Arkansas", False), ("2025-04-12", "Arkansas", True), ("2025-04-18", "Tulsa", True)]
WEEKDAYS = {"sun": 6, "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5}
LEGACY_SPRING_GAMES = [("2023-10-20", "Holy Cross"), ("2024-02-29", "Towson"), ("2024-04-12", "George Mason")]

# The pre-change rules, copied from origin/main: the current-theme branch searched the card for
# 'exhibition' with no word boundary, the legacy branch for 'exhibition' or 'exh.', and neither
# moved a spring date. They are here so the swap-back proof lives in the suite (as
# test_matches_origin_behaviour does for #35) rather than in a reviewer's terminal history.
ORIGIN_CARD_RE = re.compile(r"exhibition", re.I)
ORIGIN_LEGACY_RE = re.compile(r"\bexhibition\b|\bexh\.", re.I)


def row(g: dict) -> tuple:
    return (g["date"], g["homeAway"], g["opponent"], g["exhibition"], g["result"], g["score"])


def test_exhibition_markers() -> None:
    """Every marker spelling found on the cached pages, and the look-alikes that must not match."""
    print("exhibition markers (issues #122, #25)")
    for name, want in (("schedule-exhibition-markers", MARKER_GAMES),
                       ("schedule-legacy-exhibition-markers", LEGACY_MARKER_GAMES)):
        got = [row(g) for g in parse(name)["games"]]
        ok(f"{name}: every row, with its exhibition flag, result and score", got == want, f"got {got}")
    for label, want in (("(EXH)", True), ("(Exh.)", True), ("(exhib.)", True), ("(Exhib)", True),
                        ("(Exhi.)", True), ("(EXB)", True), ("(Exb.)", True), ("(EX)", True), ("(Ex.)", True),
                        ("Exhibitions", True), ("South Florida - EXH", True), ("Scrimmage", True),
                        ("Blue vs. Yellow Scrimmage", True), ("exhibition", True),
                        ("Alumni Soccer Stadium", False), ("Alumni Day", False), ("Alumni Game / Senior Day", False),
                        ("BOILING SPRINGS, NC", False), ("Spring Schedule", False), ("Exeter", False),
                        ("Essex", False), ("Excel Center", False), ("Texas Tech", False)):
        ok(f"marker {label!r} -> exhibition {want}", bool(sidearm.EXHIBITION_RE.search(label)) is want)
    for label, want in (("Wofford (EXH)", "Wofford"), ("South Florida - EXH", "South Florida"),
                        ("Kennesaw State (Exb.)", "Kennesaw State"), ("Snow College (Scrimmage)", "Snow College"),
                        ("Blue vs. Yellow Scrimmage", "Blue vs. Yellow Scrimmage"),
                        ("Alumni FC", "Alumni FC"), ("Exeter City", "Exeter City")):
        got = sidearm.OPPONENT_MARKER_RE.sub("", label).strip()
        ok(f"opponent {label!r} -> {want!r}", got == want, f"got {got!r}")
    for token, want in (("Exhibitions", True), ("Exhib.", True), ("EXB", True), ("Scrimmage", True),
                        ("Huntsville, AL", False), ("Alumni Soccer Stadium", False)):
        ok(f"location token {token!r} dropped: {want}", bool(sidearm.LEGACY_NON_PLACE_RE.match(token)) is want)


def test_markers_were_missed_before() -> None:
    """The swap-back proof: origin/main's rules find nothing in the rows this pins."""
    print("origin/main missed these markers")
    # radford's card says 'Exhibitions', which origin/main's boundary-free 'exhibition' does catch;
    # every other marker spelling in these fixtures it misses.
    for name, rule, want_missed in (("schedule-exhibition-markers", ORIGIN_CARD_RE, 7),
                                    ("schedule-legacy-exhibition-markers", ORIGIN_LEGACY_RE, 3)):
        soup = BeautifulSoup(fixture(name), "html.parser")
        rows = sidearm._top_level_cards(soup) or soup.select("li.sidearm-schedule-game")
        missed = [r for r in rows if sidearm.EXHIBITION_RE.search(r.get_text(" ")) and not rule.search(r.get_text(" "))]
        ok(f"{name}: origin/main's rule misses {want_missed} of the exhibitions this fixture carries",
           len(missed) == want_missed, f"missed {len(missed)}")
        ok(f"{name}: and it flags no row this change would not flag",
           not [r for r in rows if rule.search(r.get_text(" ")) and not sidearm.EXHIBITION_RE.search(r.get_text(" "))])
    for name, games in (("schedule-spring-after-fall", SPRING_GAMES), ("schedule-legacy-spring-after-fall", LEGACY_SPRING_GAMES)):
        season = parse(name)["season"]
        moved = [d for d, _ in games if int(d[:4]) != season]
        ok(f"{name}: origin/main dated every row in the season year, so {len(moved)} were wrong",
           len(moved) == 2 and all(int(d[:4]) == season + 1 for d in moved), f"{moved} vs season {season}")


def test_spring_descriptor_gap() -> None:
    """A spring card whose own row omits the section descriptor is still a spring game.

    okstate.com's 2024 page is the only row of its kind in the corpus. Inheriting the descriptor
    down the page would be the more dangerous rule - an exhibition block usually comes first, so a
    forward-inheriting descriptor would mark a whole fall season - so a January-July date on a page
    with a fall block is simply not counted.
    """
    print("a spring card with no descriptor of its own")
    cards = sidearm._top_level_cards(BeautifulSoup(fixture("schedule-spring-descriptor-gap"), "html.parser"))
    descriptors = [len(c.select(".s-descriptor__text")) for c in cards]
    ok("descriptor-gap: the middle spring card carries the descriptor and the Tulsa card carries none",
       len(cards) == 3 and descriptors[1] > 0 and descriptors[2] == 0
       and "Tulsa" in cards[2].get_text(" "), f"descriptors per card: {descriptors}")
    games = parse("schedule-spring-descriptor-gap")["games"]
    got = [(g["date"], g["opponent"], g["exhibition"]) for g in games]
    ok("descriptor-gap: the fall game counts; both spring games do not, and both move a year",
       got == DESCRIPTOR_GAP_GAMES, f"got {got}")
    counted = [g for g in games if not g["exhibition"]]
    ok("descriptor-gap: only the fall game reaches the record (0-1-0, not 2-1-0)",
       [g["result"] for g in counted] == ["L"], str([g["result"] for g in counted]))
    ok("descriptor-gap: reading the marker row by row - what origin/main does - would count the Tulsa win",
       not sidearm.EXHIBITION_RE.search("vs Tulsa Neal Patterson Stadium Stillwater, OK W, 3-2 Apr 18 (Fri) 6:00 PM"))


def test_dates_match_the_weekday_on_the_card() -> None:
    """The date rules' own oracle: a weekday cannot be ambiguous between years one apart.

    Every Sidearm row prints the weekday beside the date ('Apr 18 (Fri)', 'Feb 29 (Thu)'). If the
    year is wrong the weekday will not match, which is what makes this a check and not a restatement
    of the parser. The last block shows it can fail: the pre-change date for every moved game lands
    on a different weekday.
    """
    print("dates agree with the weekday printed on the card")
    import datetime as dt
    checked = 0
    # only the fixtures trimmed from ONE page: the two CONSTRUCTED marker fixtures gather cards from
    # several seasons under one title year, so their dates are deliberately not their pages' dates
    for name in ("schedule-spring-after-fall", "schedule-legacy-spring-after-fall",
                 "schedule-spring-descriptor-gap", "schedule-legacy", "schedule-legacy-no-title-year"):
        soup = BeautifulSoup(fixture(name), "html.parser")
        rows = sidearm._top_level_cards(soup) or soup.select("li.sidearm-schedule-game")
        games = parse(name)["games"]
        if len(rows) != len(games):
            continue  # a fixture whose rows and games do not line up 1:1 is covered elsewhere
        for g, r in zip(games, rows):
            m = re.search(r"\((Sun|Mon|Tue|Wed|Thu|Fri|Sat)[a-z]*\.?\)", r.get_text(" "))
            if not (m and g["date"]):
                continue
            checked += 1
            y, mo, d = (int(x) for x in g["date"].split("-"))
            ok(f"{name}: {g['opponent']} on {g['date']} is a {m.group(1)}",
               dt.date(y, mo, d).weekday() == WEEKDAYS[m.group(1).lower()[:3]],
               f"{g['date']} is a {dt.date(y, mo, d).strftime('%a')}")
    ok("weekday oracle: it actually looked at some dates", checked >= 10, str(checked))
    wrong = 0
    for name, games in (("schedule-spring-after-fall", SPRING_GAMES), ("schedule-legacy-spring-after-fall", LEGACY_SPRING_GAMES)):
        season = parse(name)["season"]
        soup = BeautifulSoup(fixture(name), "html.parser")
        rows = sidearm._top_level_cards(soup) or soup.select("li.sidearm-schedule-game")
        for (date, _opp), r in zip(games, rows):
            if int(date[:4]) == season:
                continue
            m = re.search(r"\((Sun|Mon|Tue|Wed|Thu|Fri|Sat)[a-z]*\.?\)", r.get_text(" "))
            if not m:
                continue
            old = f"{season}-{date[5:]}"
            try:
                bad = dt.date(*(int(x) for x in old.split("-"))).weekday() != WEEKDAYS[m.group(1).lower()[:3]]
            except ValueError:
                bad = True  # Feb 29 in a non-leap year: not a date at all
            wrong += bool(bad)
    ok("weekday oracle can fail: every pre-change date lands on the wrong weekday (or does not exist)",
       wrong == 4, str(wrong))


def test_spring_after_fall() -> None:
    """A January-July game listed after an August-December one belongs to the next year."""
    print("spring games listed after the fall block")
    for name, want in (("schedule-spring-after-fall", SPRING_GAMES),
                       ("schedule-legacy-spring-after-fall", LEGACY_SPRING_GAMES)):
        got = [(g["date"], g["opponent"]) for g in parse(name)["games"]]
        ok(f"{name}: the fall game keeps the season year and the spring games move on a year",
           got == want, f"got {got}")
    leap = [g for g in parse("schedule-legacy-spring-after-fall")["games"] if (g["date"] or "").endswith("-02-29")]
    ok("legacy-spring-after-fall: the Feb 29 row proves it - 2023 has no Feb 29, 2024 does",
       len(leap) == 1 and leap[0]["date"] == "2024-02-29", str([g["date"] for g in leap]))
    before_fall = [{"date": "2024-04-13"}, {"date": "2024-04-20"}, {"date": "2024-08-15"}]
    ok("a spring block printed BEFORE the fall block keeps its year (gonzaga 2024)",
       [g["date"] for g in sidearm._spring_games(before_fall)] == ["2024-04-13", "2024-04-20", "2024-08-15"])
    ok("...and is still a spring game, so it does not count",
       [g.get("exhibition") for g in before_fall] == [True, True, None])
    dateless = [{"date": None}, {"date": "2025-08-10"}, {"date": None}, {"date": "2025-03-01"}]
    ok("a row with no date is passed over, and the ones around it still work",
       [g["date"] for g in sidearm._spring_games(dateless)] == [None, "2025-08-10", None, "2026-03-01"])
    spring_only = [{"date": "2026-03-01"}, {"date": "2026-04-02"}]
    ok("a page with no fall block at all is not a fall-season page: nothing is moved or flagged",
       [(g["date"], g.get("exhibition")) for g in sidearm._spring_games(spring_only)]
       == [("2026-03-01", None), ("2026-04-02", None)])


# (opponent, rank, seed), in page order
RANKED_GAMES = [
    ("Notre Dame", 5, None),                        # No. 5 Notre Dame
    ("Pepperdine", None, None),                     # RV Pepperdine - receiving votes, no number
    ("Illinois", None, None),                       # (RV) Illinois
    ("Ohio State", None, 8),                        # [8] Ohio State - a bracket seed
    ("Texas", 21, 4),                               # (4) #21 Texas - seed and rank in one label
    ("Louisiana Tech", None, 7),                    # No. 7 seed Louisiana Tech
    ("ULM", None, 3),                               # #3 Seed ULM - the label is all that precedes it
    ("Tarleton State University", None, 5),         # #5 Seeded Tarleton State University
    ("UCLA", 7, None),                              # #7/T9 UCLA - first poll wins, T means tied
    ("Baylor", 23, 5),                              # (5-Seed) #23/18 Baylor
    ("Saint Louis", 21, None),                      # #RV/21 Saint Louis
    ("2026 Summit League Soccer Championship", None, None),   # a year, not a rank
    ("Michigan", None, None),
    ("Baylor", None, None),
]
LEGACY_RANKED_GAMES = [
    ("West Virginia", 20, None),                    # No. 20 West Virginia
    ("Kansas", 21, None),                           # RV/No. 21 Kansas
    ("Brown", 23, None),                            # #NR/RV/23 Brown
    ("UC Irvine", None, 4),                         # [4] UC Irvine
    ("Lamar", None, 1),                             # No. 1 Seed Lamar
    ("FAU", None, 7),                               # #7 SEED FAU
    ("University of Wisconsin", None, None),        # RV-University of Wisconsin
    ("2026 Metro Championship", None, None),
    ("Duquesne", None, None),
]
# What the pre-change parser did: it read a rank only from '#21 Ohio State' and left everything else
# in the name. Kept here so the swap-back proof lives in the suite.
ORIGIN_RANK_RE = re.compile(r"#\s*(\d+)\s+(.*)")


def test_ranks_and_seeds_leave_the_name(name: str = "schedule-ranked-opponents") -> None:
    print("rankings and seeds in front of the opponent (issue #129)")
    for fixture_name, want in (("schedule-ranked-opponents", RANKED_GAMES),
                               ("schedule-legacy-ranked-opponents", LEGACY_RANKED_GAMES)):
        games = parse(fixture_name)["games"]
        got = [(g["opponent"], g["opponentRank"], g["opponentSeed"]) for g in games]
        ok(f"{fixture_name}: every opponent, rank and seed", got == want, f"got {got}")
        ok(f"{fixture_name}: no name is left empty", all((g["opponent"] or "").strip() for g in games),
           str([g["opponent"] for g in games]))
        ok(f"{fixture_name}: no name still carries a decoration",
           not [g for g in games if re.match(r"^(?:#|No\.?\s*\d|RV\b|NR\b|seed(?:ed)?\b|[\[(]\s*(?:\d{1,2}|RV|NR))", g["opponent"], re.I)],
           str([g["opponent"] for g in games]))


def test_every_spelling_and_the_ones_to_leave_alone() -> None:
    """The unit table: every form measured in the corpus, and the strings that must survive intact."""
    print("every ranking spelling, and the names that must survive")
    for label, want in [
        ("#21 Ohio State", (21, None, "Ohio State")),
        ("No. 10 Arkansas", (10, None, "Arkansas")),
        ("No. 3 Utah State University", (3, None, "Utah State University")),
        ("No. 6/7 North Carolina", (6, None, "North Carolina")),
        ("#14/#16 Michigan State", (14, None, "Michigan State")),
        ("#T18 Wake Forest", (18, None, "Wake Forest")),
        ("#7/T9 UCLA", (7, None, "UCLA")),
        ("#NR/RV/23 Brown", (23, None, "Brown")),
        ("#RV/RV/NR Indiana", (None, None, "Indiana")),
        ("(25/19) Texas Tech", (25, None, "Texas Tech")),
        ("(25/-) Colorado State", (25, None, "Colorado State")),
        ("RV Utah State", (None, None, "Utah State")),
        ("(RV) Iowa", (None, None, "Iowa")),
        ("[RV] Xavier", (None, None, "Xavier")),
        ("(rv) Texas Tech", (None, None, "Texas Tech")),
        ("RV-University of Wisconsin", (None, None, "University of Wisconsin")),
        ("RV/No. 21 Kansas", (21, None, "Kansas")),
        ("(6) New Mexico vs. (3) Utah State (First Round)", (None, 6, "New Mexico vs. (3) Utah State (First Round)")),
        ("[8] Ohio State", (None, 8, "Ohio State")),
        ("No. 1 Seed Western Michigan", (None, 1, "Western Michigan")),
        ("#2 Seed Arkansas", (None, 2, "Arkansas")),
        ("#5 Seeded Tarleton State University", (None, 5, "Tarleton State University")),
        ("(5-Seed) #23/18 Baylor", (23, 5, "Baylor")),
        ("Seed ULM", (None, None, "ULM")),
        ("Seed Old Dominion", (None, None, "Old Dominion")),
        ("Seeded UCLA", (None, None, "UCLA")),
        # names and labels that must come through untouched
        ("Texas Tech", (None, None, "Texas Tech")),
        ("Norfolk State", (None, None, "Norfolk State")),
        ("Nova Southeastern", (None, None, "Nova Southeastern")),
        ("Seedorf FC", (None, None, "Seedorf FC")),
        ("Seed", (None, None, "Seed")),
        ("RV", (None, None, "RV")),
        ("No. 5", (None, None, "No. 5")),
        ("2026 Summit League Soccer Championship", (None, None, "2026 Summit League Soccer Championship")),
        ("2026 Metro Championship", (None, None, "2026 Metro Championship")),
        ("19 Xavier", (None, None, "19 Xavier")),
        ("24 Hour Classic", (None, None, "24 Hour Classic")),
        ("1st Round", (None, None, "1st Round")),
    ]:
        got = sidearm.rank_seed_and_name(label)
        ok(f"{label!r} -> {want}", got == want, f"got {got}")


def test_origin_left_these_in_the_name() -> None:
    """The swap-back proof: origin/main read a rank only from '#N ' and left the rest in the name."""
    print("origin/main left these decorations in the name")
    left = [(g["opponent"], g["opponentRank"], g["opponentSeed"]) for name in
            ("schedule-ranked-opponents", "schedule-legacy-ranked-opponents") for g in parse(name)["games"]]
    decorated = 0
    for fixture_name in ("schedule-ranked-opponents", "schedule-legacy-ranked-opponents"):
        soup = BeautifulSoup(fixture(fixture_name), "html.parser")
        rows = sidearm._top_level_cards(soup) or soup.select("li.sidearm-schedule-game")
        for r in rows:
            el = r.select_one(".s-game-card__header__team-event-info") or r.select_one(".sidearm-schedule-game-opponent-name")
            raw = [t for t in (common.clean(x) for x in el.get_text("\n").split("\n")) if t][0] if el else ""
            m = ORIGIN_RANK_RE.match(raw)
            origin_name = common.clean(m.group(2)) if m else raw
            ours = sidearm.rank_seed_and_name(raw)[2]
            if origin_name != ours:
                decorated += 1
    ok("origin/main leaves a decoration in 15 of the 23 names these fixtures carry", decorated == 15, str(decorated))
    ok("and none of ours is empty or still decorated", all(n and not re.match(r"^(#|No\.\s*\d|RV\b|seed\b|\[|\()", n, re.I) or n.startswith("2026") for n, _, _ in left),
       str([n for n, _, _ in left]))


def main() -> int:
    global VERBOSE
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    VERBOSE = parser.parse_args().verbose

    test_matches_origin_behaviour()
    test_legacy_fields()
    test_conference_needs_a_name()
    test_not_played_has_no_result()
    test_a_score_needs_a_result()
    test_exhibition_from_the_location_column()
    test_promotions_are_not_locations()
    test_year_when_the_title_has_none()
    test_current_theme_wins()
    test_duplicate_link_labels_keep_the_last()
    test_both_branches_agree_on_the_contract()
    test_exhibition_markers()
    test_markers_were_missed_before()
    test_spring_after_fall()
    test_spring_descriptor_gap()
    test_dates_match_the_weekday_on_the_card()
    test_ranks_and_seeds_leave_the_name()
    test_every_spelling_and_the_ones_to_leave_alone()
    test_origin_left_these_in_the_name()
    test_fixtures_carry_no_contact_details()

    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        for name in FAILS:
            print(f"  failed: {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
