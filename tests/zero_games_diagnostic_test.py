"""The name-free diagnostic line for a schedule page that yields no game (issue #393).

    python tests/zero_games_diagnostic_test.py            # everything below, offline
    python tests/zero_games_diagnostic_test.py --verbose  # print every check

Offline: every page is built here from placeholder names; collect.common.fetch_text is replaced by a table of
those pages, so no request is made.

Why this exists
---------------
george-mason, utah-state and wyoming (#145) stored 0 schedule games: their schedule pages loaded, the parser
found nothing, and an empty schedule was saved. None of those pages is in any local cache, so whether they carry
the games as embedded JSON (as their roster pages carry the roster, #388) cannot be checked offline.
athletics_site.collect now logs one line when the current season's schedule page yields no game, describing
what the page holds instead.

The refresh log is public. The line holds integers, 0/1 flags, and identifiers from the page's code only - the
Vue data key after `data: () => ({` and the names of the list-valued JSON keys of the object it holds - each
logged only if it matches a plain lower-case identifier pattern. Never an opponent, a place, a date, a URL or any
other value. At most 8 keys and 400 characters (the literal values are pinned here). A diagnostic that fails
logs one short line and never fails the collection.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import athletics_site, common  # noqa: E402
import camps_check  # noqa: E402

BASE = "https://athletics.example.test"
SPORT = "/sports/womens-soccer"
ROSTER, SCHEDULE = BASE + SPORT + "/roster", BASE + SPORT + "/schedule"
REGISTRY = {
    "season": {"current": 2026},
    "sources": {"athleticsPlatforms": {"sidearm": {
        "roster": "{baseUrl}{sportPath}/roster", "rosterSeason": "{baseUrl}{sportPath}/roster/{year}",
        "schedule": "{baseUrl}{sportPath}/schedule", "scheduleSeason": "{baseUrl}{sportPath}/schedule/{year}",
        "news": "{baseUrl}{sportPath}/archives", "rss": "{baseUrl}/rss?path=wsoc"}}},
}
FAILS: list[str] = []
TOTAL = 0
VERBOSE = False

# Made-up values that must never reach the line.
VALUES = ("Placeholder State University", "Sample Tech", "Dummy City, ST", "Example Field", "W, 2-1",
          "coach.sample@example.test", "555-555-0177", "https://tickets.example.test/game/1", "Sep. 5")


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def game(i: int) -> dict:
    return {"id": 100 + i, "date": "2026-09-05T19:00:00", "opponent": {"title": VALUES[i % 2], "image": None},
            "location": VALUES[2], "game_facility": {"title": VALUES[3]}, "result": {"status": VALUES[4]},
            "media": {"tickets": VALUES[7]}, "promotion": {"contact": VALUES[5], "phone": VALUES[6]},
            "date_text": VALUES[8], "location_indicator": "H"}


def vue_schedule(obj, key: str = "schedule") -> str:
    return ("<script>require(['vue', 'knockout'], function (Vue, ko) { new Vue({ el: '#schedule-app', "
            f"data: () => ({{ {key}: " + json.dumps(obj) + ", filter: null }) }); });</script>")


def page(*parts: str) -> str:
    return ("<html><head><title>2026 Women's Soccer Schedule - Example University</title></head><body>"
            '<div id="schedule-app">Loading...</div>' + "".join(parts) + "</body></html>")


def legacy_rows(n: int) -> str:
    return "<ul>" + "".join(
        f'<li class="sidearm-schedule-game sidearm-schedule-home-game"><div class="sidearm-schedule-game-opponent-date">'
        f'Sep {i + 1}</div><div class="sidearm-schedule-game-opponent-name">Opponent {i}</div></li>' for i in range(n)) + "</ul>"


def leaks(line: str) -> list[str]:
    found = [v for v in VALUES if v.lower() in line.lower()]
    found += [w for w in ("placeholder", "sample", "dummy", "example", "http", "@", "loading", "person") if w in line.lower()]
    e, p = camps_check.contact_hits(line)
    return found + e + p


def vue_page() -> str:
    return page(vue_schedule({"id": 7, "games": [game(i) for i in range(3)], "events": [], "season": {"title": "2026"},
                              "Placeholder Person": [1, 2], "has space": [1], "UPPER": [1], "sample_key": 5}))


# ---------- the line ----------

def test_vue_schedule_page():
    line = athletics_site.zero_games_diagnostic(vue_page())
    ok("line starts as expected", line.startswith("  no games found: schedule markup "), line)
    for part in ("vue=schedule", "opponentKeys=3", "nuxt=0", "tables=0", "gameCards=0", "legacyGames=0"):
        ok(f"line has {part}", part in line, line)
    ok("list-valued identifier keys with their lengths", "lists=[games=3, events=0]" in line, line)
    ok("non-identifier and non-list keys are not logged", all(k not in line for k in ("Placeholder", "has space", "UPPER", "sample_key", "season")), line)
    ok("no value from the page reaches the line", not leaks(line), leaks(line))
    e, p = camps_check.contact_hits(line)
    ok("contact scanner finds nothing", not e and not p, e + p)
    ok("the fixture really holds every value", all(v in vue_page() for v in VALUES))


def test_other_shapes():
    line = athletics_site.zero_games_diagnostic(page(vue_schedule([game(1), game(2)])))
    ok("a Vue data key holding a list logs its length only", "vue=schedule" in line and "lists=[[]=2]" in line, line)
    line = athletics_site.zero_games_diagnostic(page(vue_schedule({"games": []}, key="Schedule")))
    ok("a non-lower-case Vue key logs as <x>", "vue=<x>" in line and "lists=[games=0]" in line, line)
    line = athletics_site.zero_games_diagnostic(page("<script>new Vue({ el: '#x', data: () => ({ schedule: not json }) });</script>"))
    ok("an unparsable object logs the key and no lists", "vue=schedule" in line and "lists=[]" in line, line)
    nuxt = ('<html><head><title>Schedule</title></head><body><div class="c-schedule">Loading...</div>'
            '<script type="application/json" id="__NUXT_DATA__">[{"state":1}]</script></body></html>')
    line = athletics_site.zero_games_diagnostic(nuxt)
    ok("a Nuxt placeholder: nuxt=1, vue=-", "nuxt=1" in line and "vue=-" in line and "lists=[]" in line, line)
    line = athletics_site.zero_games_diagnostic(page('<script>var obj = {"games": [{"opponent": {"title": "X"}}]};</script>'))
    ok("game-like JSON outside the Vue signature is only counted", "opponentKeys=1" in line and "vue=-" in line, line)


def test_caps_are_400_characters_and_8_keys():
    ok("DIAG_MAX_LEN is 400", athletics_site.DIAG_MAX_LEN == 400, athletics_site.DIAG_MAX_LEN)
    ok("DIAG_MAX_KEYS is 8", athletics_site.DIAG_MAX_KEYS == 8, athletics_site.DIAG_MAX_KEYS)
    nine = page(vue_schedule({f"list_{i}": [] for i in range(9)}))
    line = athletics_site.zero_games_diagnostic(nine)
    keys = line.split("lists=[", 1)[1].split("]", 1)[0].split(", ")
    ok("key cap: exactly 8 keys logged, the ninth counted", len(keys) == 8 and line.endswith(" +1 more"), line)
    long = page(vue_schedule({("k" + "x" * 28 + str(i)): [0] * 1000 for i in range(8)}))  # 8 keys, 30 letters, 4 digits
    real = athletics_site.DIAG_MAX_LEN
    athletics_site.DIAG_MAX_LEN = 10 ** 9
    try:
        free = athletics_site.zero_games_diagnostic(long)
    finally:
        athletics_site.DIAG_MAX_LEN = real
    ok("length fixture goes over 400 characters uncapped", len(free) > 400, len(free))
    line = athletics_site.zero_games_diagnostic(long)
    ok("length cap: at most 400 characters", len(line) <= 400, len(line))
    ok("length cap: dropped keys are counted", " more" in line, line)


def test_mutation_identifier_filter():
    real = athletics_site._IDENT
    athletics_site._IDENT = __import__("re").compile(r".*")  # a broken filter that lets any key through
    try:
        line = athletics_site.zero_games_diagnostic(vue_page())
    finally:
        athletics_site._IDENT = real
    ok("a key filter that lets names through is caught by the leak check", bool(leaks(line)), line)
    ok("filter restored", athletics_site._IDENT is real)


def test_no_request():
    calls = []

    def refuse(*a, **k):
        calls.append(a[:1])
        raise AssertionError("the diagnostic made a request")
    real = (common.fetch_text, common.fetch)
    common.fetch_text = common.fetch = refuse
    try:
        athletics_site.zero_games_diagnostic(vue_page())
        ran = True
    except AssertionError:
        ran = False
    finally:
        common.fetch_text, common.fetch = real
    ok("no request made", ran and not calls, calls)


# ---------- the trigger, through athletics_site.collect ----------

SAVED: list = []


def roster_page() -> str:
    rows = "".join(f'<tr><td>{i}</td><th scope="row"><a href="{SPORT}/roster/player-{i}/{900 + i}">Player {i}</a></th>'
                   f"<td>D</td><td>5'6\"</td><td>So.</td><td>Town, ST / High School</td></tr>" for i in range(1, 4))
    staff = ("<table><tr><th>Coaching Staff</th></tr><tr><th>Name</th><th>Title</th></tr>"
             "<tr><td>Staff Member</td><td>Head Coach</td></tr></table>")
    return ("<html><head><title>2026 Women's Soccer Roster</title></head><body><table><thead><tr><th>#</th><th>Name</th>"
            "<th>Pos.</th><th>Ht.</th><th>Year</th><th>Hometown / High School</th></tr></thead><tbody>" + rows +
            "</tbody></table>" + staff + "</body></html>")


def run_collect(schedule_html: str, *, seasons_back: int = 0, history: dict | None = None):
    logs = []
    pages = {ROSTER: roster_page(), SCHEDULE: schedule_html, **(history or {})}

    def fetch_text(url, **kw):
        if url not in pages:
            raise common.FetchError(f"HTTP 404 for {url}")
        return pages[url], {"url": url, "status": 200, "finalUrl": url, "fromCache": False}

    program = {"slug": "fixture", "athletics": {"platform": "sidearm", "baseUrl": BASE, "sportPath": SPORT}}
    real = (common.fetch_text, common.save_source, common.log, common.load_source)
    SAVED.clear()
    common.fetch_text, common.log = fetch_text, logs.append
    common.save_source = lambda *a, **k: SAVED.append(True)
    common.load_source = lambda slug, name: None
    err = None
    try:
        athletics_site.collect(program, REGISTRY, seasons_back=seasons_back, bios=False, coach_bios=False)
    except Exception as e:
        err = e
    finally:
        common.fetch_text, common.save_source, common.log, common.load_source = real
    return [l for l in logs if "no games found" in l or "zero-games diagnostic failed" in l], err


def test_trigger():
    lines, err = run_collect(page(legacy_rows(3)))
    ok("silent: the schedule page has games", lines == [] and err is None, (lines, err))
    lines, err = run_collect(vue_page())
    ok("fires once: the page loaded and gave no game", len(lines) == 1 and err is None and SAVED == [True], (lines, err))
    ok("... describing the page", "vue=schedule" in (lines or [""])[0], lines)
    lines, err = run_collect(page(legacy_rows(3)), seasons_back=1, history={SCHEDULE + "/2025": page()})
    ok("silent: a history season with no game (only the current page is described)", lines == [] and err is None, (lines, err))


def test_a_failing_diagnostic_never_fails_the_collection():
    real = athletics_site.zero_games_diagnostic

    def boom(*a, **k):
        raise RuntimeError("unexpected")
    athletics_site.zero_games_diagnostic = boom
    try:
        lines, err = run_collect(vue_page())
    finally:
        athletics_site.zero_games_diagnostic = real
    ok("collect still succeeds when the diagnostic raises", err is None, err)
    ok("... and the source is still saved", SAVED == [True], SAVED)
    ok("... with one short failure line naming only the type", lines == ["  !! zero-games diagnostic failed (RuntimeError)"], lines)
    ok("diagnostic restored", athletics_site.zero_games_diagnostic is real)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_vue_schedule_page, test_other_shapes, test_caps_are_400_characters_and_8_keys,
                 test_mutation_identifier_filter, test_no_request, test_trigger,
                 test_a_failing_diagnostic_never_fails_the_collection):
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
