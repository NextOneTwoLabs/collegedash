"""The name-free diagnostic line for a roster with players and no staff (issue #387).

    python tests/zero_staff_diagnostic_test.py            # everything below, offline
    python tests/zero_staff_diagnostic_test.py --verbose  # print every check

Offline: every page is built here from placeholder names; collect.common.fetch_text is replaced by a table of
those pages, so no request is made.

Why this exists
---------------
Eight Sidearm programs (#387) publish players and no staff: their roster page yields no staff row and their
/sports/<sport>/coaches page is a 404. None of their pages is in any local cache, so the parser fix cannot be
planned offline. athletics_site.collect now logs one line when the FINAL staff list is empty - after the roster
page, the coaches page and (robots enforce mode) the kept stored staff - describing the page's staff-like markup.

The refresh log is public, so the line may hold only integers, 0/1 flags and link paths masked segment by
segment (athletics_site.DIAG_STRUCTURAL_WORDS, the program's own sportPath, <n>, <x>). The checks here follow
Bianque's review on #387: exact whole-segment matching that logs the allowlist's own word; the sport path from
the program's sportPath only; encoded, upper-case and '@' segments masked, split on '/' before any decoding;
other hosts log nothing; a cap on the whole line; leak checks with the contact scanner as a second net; a
mutation that must fail; no request; and the trigger (fires on an empty final list only).
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
ROSTER, COACHES = BASE + SPORT + "/roster", BASE + SPORT + "/coaches"
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

# Made-up people and details that must never reach the line.
NAMES = ("Placeholder Coachperson", "Sample Staffmember", "Dummy Assistant")
SLUGS = ("placeholder-coachperson", "coach-placeholder-name", "staff-member-sample", "placeholder-bio",
         "placeholder-soccer-coach", "PLACEHOLDER-UPPER", "jane%20doe", "coaches%2Fname", "name@example.test",
         "womens-soccer-placeholder")
EMAIL, PHONE = "placeholder.coach@example.test", "555-555-0199"


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def player_table(n: int = 3) -> str:
    rows = "".join(f'<tr><td>{i}</td><th scope="row"><a href="{SPORT}/roster/player-{i}/{900 + i}">Player {i}</a></th>'
                   f"<td>D</td><td>5'6\"</td><td>So.</td><td>Town, ST / High School</td></tr>" for i in range(1, n + 1))
    return ("<table><thead><tr><th>#</th><th>Name</th><th>Pos.</th><th>Ht.</th><th>Year</th>"
            "<th>Hometown / High School</th></tr></thead><tbody>" + rows + "</tbody></table>")


def staff_table() -> str:
    return ("<table><tr><th>Coaching Staff</th></tr><tr><th>Name</th><th>Title</th></tr>"
            f'<tr><td><a href="{SPORT}/roster/coaches/{SLUGS[0]}/77">{NAMES[0]}</a></td><td>Head Coach</td></tr></table>')


def no_staff_markup() -> str:
    """Staff-like markup the table parser does not read, with name-bearing links of every awkward shape."""
    links = [f"{SPORT}/roster/coaches/{s}/{100 + i}" for i, s in enumerate(SLUGS)]
    links += [f"/sports/{SLUGS[4]}/staff", f"/COACHES/{SLUGS[5]}", "/staff-directory", "/Staff-Directory?id=5#top"]
    items = "".join(f'<li class="c-coach-card"><a href="{h}">{NAMES[i % 3]}</a></li>' for i, h in enumerate(links))
    return (f'<section class="coaching-staff"><h2>Coaching Staff</h2><ul>{items}</ul>'
            f'<p>Contact {NAMES[1]} at <a href="mailto:{EMAIL}">{EMAIL}</a> or <a href="tel:{PHONE}">{PHONE}</a>.</p>'
            f'<a href="https://other-host.example.test/roster/coaches/{SLUGS[0]}/5">elsewhere</a>'
            f'<a href="//other-host.example.test/staff/{SLUGS[1]}">elsewhere too</a></section>')


def page(*parts: str) -> str:
    return "<html><head><title>2026 Women's Soccer Roster</title></head><body>" + "".join(parts) + "</body></html>"


def diag(html: str, sport: str = SPORT) -> str:
    return athletics_site.zero_staff_diagnostic(html, BASE, sport)


def leaks(line: str) -> list[str]:
    found = [n for n in NAMES if n.lower() in line.lower()]
    found += [s for s in SLUGS if s.lower() in line.lower()]
    found += [w for w in ("jane", "doe", "placeholder", "sample", "dummy", "%", "@", "other-host", "elsewhere",
                          "mailto", "tel:", EMAIL, PHONE, "Contact") if w.lower() in line.lower()]
    e, p = camps_check.contact_hits(line)
    return found + e + p


# ---------- the line ----------

def test_counts_and_masked_paths():
    line = diag(page(player_table(), no_staff_markup()))
    ok("line starts as expected", line.startswith("  no staff found: roster markup "), line)
    for part in ("tables=1", "staffTables=0", "personCards=0", "sig145=0"):
        ok(f"line has {part}", part in line, line)
    ok("staff-like classes counted", "staffClasses=0" not in line, line)
    ok("coach mentions counted", "coach=0" not in line, line)
    links = line.split("links=[", 1)[1].split("]", 1)[0].split(", ")
    ok("name-bearing coach links masked", links[0] == "/sports/womens-soccer/roster/coaches/<x>/<n>", links)
    ok("every coaches link masks to the same shape (deduplicated)",
       links.count("/sports/womens-soccer/roster/coaches/<x>/<n>") == 1, links)
    ok("at most 8 paths", len(links) <= 8, links)
    ok("/staff-directory kept, query and fragment dropped, canonical spelling", "/staff-directory" in links, links)


def test_exact_whole_segment_match():
    # a segment that merely CONTAINS coach / staff / bio is a name, never a structural word
    for seg in ("coach-placeholder-name", "staff-member-sample", "placeholder-bio", "coaching", "bios-sample"):
        got = athletics_site._mask_path_segment(seg, {"sports": "sports", "womens-soccer": "womens-soccer"})
        ok(f"segment {seg!r} -> <x>", got == "<x>", got)
    for seg, want in (("COACHES", "coaches"), ("Staff", "staff"), ("Staff-Directory", "staff-directory"), ("BIO", "bio"),
                      ("123", "<n>"), ("１２３", "<x>")):
        got = athletics_site._mask_path_segment(seg, {})
        ok(f"segment {seg!r} -> {want!r} (the allowlist's own spelling)", got == want, got)


def test_sport_path_is_the_programs_own():
    line = diag(page(f'<a href="/sports/{SLUGS[4]}/staff">x</a><a href="/sports/mens-soccer/coaches/77">y</a>'
                     f'<a href="/sports/womens-soccer/coaches">z</a>'))
    ok("a 'placeholder-soccer-coach' segment is <x>", "/sports/<x>/staff" in line, line)
    ok("another sport's path is not the program's", "/sports/<x>/coaches/<n>" in line, line)
    ok("the program's own sport path is logged", "/sports/womens-soccer/coaches" in line, line)
    line2 = diag(page('<a href="/sports/w-soccer/coaches">z</a>'), sport="/sports/w-soccer")
    ok("sport path comes from sportPath", "/sports/w-soccer/coaches" in line2, line2)
    line3 = diag(page('<a href="/sports/w-soccer/coaches">z</a>'))
    ok("... and not from any segment that looks like soccer", "/sports/<x>/coaches" in line3, line3)


def test_encoded_upper_and_at_segments():
    line = diag(page(f'<a href="{SPORT}/roster/coaches/jane%20doe/12">a</a>',
                     f'<a href="{SPORT}/roster/coaches%2Fname/13">b</a>',
                     f'<a href="{SPORT}/roster/coaches/PLACEHOLDER-UPPER">c</a>',
                     f'<a href="{SPORT}/roster/coaches/name@example.test">d</a>'))
    links = line.split("links=[", 1)[1].split("]", 1)[0].split(", ")
    ok("percent-encoded name masked", "/sports/womens-soccer/roster/coaches/<x>/<n>" in links, links)
    ok("an encoded slash is not split (split on '/' before decoding)", "/sports/womens-soccer/roster/<x>/<n>" in links, links)
    ok("upper-case and '@' names masked", "/sports/womens-soccer/roster/coaches/<x>" in links, links)
    ok("nothing decoded or raw reaches the line", not leaks(line), leaks(line))


def test_other_hosts_log_nothing():
    line = diag(page(f'<a href="https://other-host.example.test/roster/coaches/{SLUGS[0]}/5">a</a>',
                     f'<a href="//other-host.example.test/staff/{SLUGS[1]}">b</a>',
                     f'<a href="https://www.athletics.example.test/staff-directory">same host with www</a>'))
    ok("off-host links absent entirely", line.endswith("links=[/staff-directory]"), line)


def _links(line: str) -> list[str]:
    inner = line.split("links=[", 1)[1].split("]", 1)[0]
    return inner.split(", ") if inner else []


def _uncapped(html: str) -> str:
    """The same line with both caps lifted - proves a fixture really goes over them."""
    real = (athletics_site.DIAG_MAX_LEN, athletics_site.DIAG_MAX_LINKS)
    athletics_site.DIAG_MAX_LEN, athletics_site.DIAG_MAX_LINKS = 10 ** 9, 10 ** 9
    try:
        return diag(html)
    finally:
        athletics_site.DIAG_MAX_LEN, athletics_site.DIAG_MAX_LINKS = real


def test_caps_are_400_characters_and_8_links():
    # The literal values, not the constants: raising either constant must fail here (Bianque's review on #390).
    ok("DIAG_MAX_LEN is 400", athletics_site.DIAG_MAX_LEN == 400, athletics_site.DIAG_MAX_LEN)
    ok("DIAG_MAX_LINKS is 8", athletics_site.DIAG_MAX_LINKS == 8, athletics_site.DIAG_MAX_LINKS)

    # link cap alone: 9 short, distinct structural shapes - over 8 links, under 400 characters
    nine = page("".join(f'<a href="/staff{"/bio" * i}">l</a>' for i in range(9)))
    free = _uncapped(nine)
    ok("link fixture has 9 paths uncapped", len(_links(free)) == 9, free)
    ok("link fixture stays under 400 characters uncapped", len(free) < 400, len(free))
    line = diag(nine)
    ok("link cap: exactly 8 paths logged", len(_links(line)) == 8, line)
    ok("link cap: the ninth is counted, not logged", line.endswith(" +1 more"), line)

    # length cap alone: 3 long structural shapes - under 8 links, over 400 characters
    long3 = page("".join(f'<a href="/coaches{"/roster" * (25 + i)}">l</a>' for i in range(3)))
    free = _uncapped(long3)
    ok("length fixture has 3 paths uncapped", len(_links(free)) == 3, free)
    ok("length fixture goes over 400 characters uncapped", len(free) > 400, len(free))
    line = diag(long3)
    ok("length cap: the line is at most 400 characters", len(line) <= 400, len(line))
    ok("length cap: paths dropped are counted", " more" in line, line)

    # both at once: 40 long distinct shapes plus 59 more
    many = "".join(f'<a href="/staff/{"a" * 30}/{i}/{"b" * 30}/{"c" * i}/{i}{"/x" * i}">l</a>' for i in range(40))
    many += "".join(f'<a href="/coaches/{"/".join(["roster"] * i)}">m</a>' for i in range(1, 60))
    free = _uncapped(page(many))
    ok("big fixture goes over both caps uncapped", len(free) > 400 and len(_links(free)) > 8, (len(free), len(_links(free))))
    line = diag(page(many))
    ok("big fixture: at most 400 characters", len(line) <= 400, len(line))
    ok("big fixture: at most 8 paths", len(_links(line)) <= 8, _links(line))
    ok("big fixture: a capped line says how many paths were left out", " more" in line, line)


def test_no_leak_and_contact_scanner():
    line = diag(page(player_table(), no_staff_markup()))
    ok("no name, slug, email, phone, link text or other host in the line", not leaks(line), leaks(line))
    e, p = camps_check.contact_hits(line)
    ok("contact scanner finds nothing", not e and not p, e + p)
    html = page(player_table(), no_staff_markup())
    ok("the fixture really carries every name, slug, email and phone", all(x in html for x in NAMES + SLUGS + (EMAIL, PHONE)))


def test_mutation_unmasked_path_fails():
    real = athletics_site._mask_path_segment
    athletics_site._mask_path_segment = lambda seg, sport: seg  # a broken masker that lets segments through
    try:
        line = diag(page(player_table(), no_staff_markup()))
    finally:
        athletics_site._mask_path_segment = real
    ok("an unmasked path is caught by the leak check", bool(leaks(line)), line)
    ok("masker restored", athletics_site._mask_path_segment is real)


def test_no_request():
    calls = []

    def refuse(*a, **k):
        calls.append(a[:1])
        raise AssertionError("the diagnostic made a request")
    real = (common.fetch_text, common.fetch)
    common.fetch_text = common.fetch = refuse
    try:
        diag(page(player_table(), no_staff_markup()))
        ran = True
    except AssertionError:
        ran = False
    finally:
        common.fetch_text, common.fetch = real
    ok("no request made", ran and not calls, calls)


# ---------- the trigger, through athletics_site.collect ----------

SAVED: list = []


def run_collect(pages: dict, *, robots: tuple = (), stored: dict | None = None) -> tuple[list[str], list[str], Exception | None]:
    logs, requests = [], []
    pages = {BASE + SPORT + "/schedule": page(), **pages}  # an empty schedule page, so collect runs to the end

    def fetch_text(url, **kw):
        requests.append(url)
        if url in robots:
            raise common.RobotsDisallowed(url, "athletics.coachesPage")
        if url not in pages:
            raise common.FetchError(f"HTTP 404 for {url}")
        return pages[url], {"url": url, "status": 200, "finalUrl": url, "fromCache": False}

    program = {"slug": "fixture", "athletics": {"platform": "sidearm", "baseUrl": BASE, "sportPath": SPORT}}
    real = (common.fetch_text, common.save_source, common.log, common.load_source)
    common.fetch_text, common.log = fetch_text, logs.append
    SAVED.clear()
    common.save_source = lambda *a, **k: SAVED.append(True)
    common.load_source = lambda slug, name: copy.deepcopy(stored) if stored else None
    err = None
    try:
        athletics_site.collect(program, REGISTRY, seasons_back=0, bios=False, coach_bios=False)
    except Exception as e:  # 0 players raises; recorded, not fatal to the test
        err = e
    finally:
        common.fetch_text, common.save_source, common.log, common.load_source = real
    return [l for l in logs if "no staff found" in l or "diagnostic failed" in l], requests, err


def test_trigger():
    lines, requests, err = run_collect({ROSTER: page(player_table(), no_staff_markup())})
    ok("fires: players, no roster staff, coaches page 404", len(lines) == 1 and err is None, (lines, err))
    ok("... and the diagnostic added no request (roster, coaches, schedule only)",
       sorted(set(requests)) == sorted({ROSTER, COACHES, BASE + SPORT + "/schedule"}), requests)
    lines, _, err = run_collect({ROSTER: page(player_table(), staff_table(), no_staff_markup())})
    ok("silent: the roster page has staff", lines == [] and err is None, (lines, err))
    lines, _, err = run_collect({ROSTER: page(player_table(), no_staff_markup()), COACHES: page(staff_table())})
    ok("silent: the coaches fallback found staff", lines == [] and err is None, (lines, err))
    kept = {"data": {"staff": [{"name": "Kept Person", "title": "Head Coach", "isHeadCoach": True, "isCoach": True,
                                "bioUrl": None, "social": {}}]}}
    lines, _, err = run_collect({ROSTER: page(player_table(), no_staff_markup())}, robots=(COACHES,), stored=kept)
    ok("silent: coaches page disallowed by robots.txt and stored staff kept", lines == [] and err is None, (lines, err))
    lines, _, err = run_collect({ROSTER: page(player_table(), no_staff_markup())}, robots=(COACHES,), stored={"data": {"staff": []}})
    ok("fires: coaches page disallowed and nothing stored (final list empty)", len(lines) == 1 and err is None, (lines, err))
    lines, _, err = run_collect({ROSTER: page(no_staff_markup())})
    ok("silent: 0 players (a roster problem; collect raises first)", lines == [] and isinstance(err, common.FetchError), (lines, err))


def test_a_failing_diagnostic_never_fails_the_collection():
    real = athletics_site.zero_staff_diagnostic

    def boom(*a, **k):
        raise RuntimeError("unexpected")
    athletics_site.zero_staff_diagnostic = boom
    try:
        lines, _, err = run_collect({ROSTER: page(player_table(), no_staff_markup())})
    finally:
        athletics_site.zero_staff_diagnostic = real
    ok("collect still succeeds when the diagnostic raises", err is None, err)
    ok("... and the source is still saved", SAVED == [True], SAVED)
    ok("... with one short failure line, naming only the exception type",
       lines == ["  !! zero-staff diagnostic failed (RuntimeError)"], lines)
    ok("diagnostic restored", athletics_site.zero_staff_diagnostic is real)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_counts_and_masked_paths, test_exact_whole_segment_match, test_sport_path_is_the_programs_own,
                 test_encoded_upper_and_at_segments, test_other_hosts_log_nothing, test_caps_are_400_characters_and_8_links,
                 test_no_leak_and_contact_scanner, test_mutation_unmasked_path_fails, test_no_request, test_trigger,
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
