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
                "opponent", "opponentRank", "location", "result", "score", "links"}
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
    names = sorted(f for f in os.listdir(FIXTURES) if f.endswith(".html"))
    ok("privacy: there are fixtures to check", len(names) == 4, str(names))
    for name in names:
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
            text = handle.read()
        found = [a for a in email.findall(text) if not a.endswith("example.invalid")]
        ok(f"privacy: {name} has no email address", not found, str(found[:3]))
        ok(f"privacy: {name} has no phone number", not phone.findall(text),
           str(phone.findall(text)[:3]))
        ok(f"privacy: {name} has no mailto: or tel: link",
           not re.search(r"(mailto|tel):(?!removed@example\.invalid|0000000000)", text, re.I))


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
    test_fixtures_carry_no_contact_details()

    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        for name in FAILS:
            print(f"  failed: {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
