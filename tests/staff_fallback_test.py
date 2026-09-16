"""Checks for programs whose roster page yields no staff rows (issue #145).

    python tests/staff_fallback_test.py            # everything below, offline
    python tests/staff_fallback_test.py --verbose  # print every check, not only the failures

Offline: reads fixtures under tests/fixtures/sidearm/ and tests/fixtures/wmt/, and replaces
collect.common.fetch_text with a table of those fixtures, so no request is made and every request the
collector *would* make is recorded.

Swap-back proof: set COLLEGEDASH_CODE_ROOT to a checkout (or `git archive`) of origin/main and the
collector and adapters are imported from there while the fixtures still come from this tree:

    git archive origin/main collect | tar -x -C /tmp/pre145
    COLLEGEDASH_CODE_ROOT=/tmp/pre145 python tests/staff_fallback_test.py

Why these exist
---------------
Measured over the stored sources and the live sites, two different things leave a program with no
staff row at all even though its athletics site lists the staff:

1. **Sidearm sites that print no staff on the roster page.** austin-peay, mississippi-state,
   louisiana-monroe, michigan, texas and yale list their players at /sports/womens-soccer/roster and
   their coaches only at /sports/womens-soccer/coaches, a server-rendered table the roster table
   parser already reads. collect/athletics_site.py now reads that page, and only when the roster page
   yielded zero staff rows: it never replaces or merges into staff the roster page returned, and a
   program whose roster page has staff makes no extra request.

2. **A WMT page that mixes themes.** wsucougars.com lists its players in the older
   li.roster-list-item markup and its staff in the 2025 redesign's li.staff-list-item. Only the
   redesign branch read li.staff-list-item, and it ran only when no player had been found, so the
   eight staff rows were never read. collect/adapters/wmt.py now reads them when nothing else did.

Fixtures (every contact column, contact link, image and social link removed; header comment in each):

  sidearm/roster-no-staff             mississippi-state roster: three players, no staff anywhere
  sidearm/coaches-current-theme       mississippi-state /coaches: current theme Name/Title table
  sidearm/coaches-staff-directory     austin-peay /coaches: the older theme's 'Staff Directory' table
  sidearm/roster-players-and-staff    CONTROL, army roster: players and staff on the roster page
  wmt/roster-mixed-theme-staff        washington-state roster: old player markup, redesign staff

The checks are labelled. FIX checks fail against origin/main and pass after the change. The rest pass
on both by design: PIN records that the roster table parser already reads both coaches-page shapes
unchanged (the fallback depends on that); CONTROL that a program which had staff keeps exactly those
rows and makes exactly the requests it made before; GUARD that the fallback refuses a page redirected
off the sport's coaches path - origin/main passes those only because it never reads /coaches, which is
why each GUARD sits beside a FIX check on the same page that does fail there.
"""

from __future__ import annotations

import argparse
import copy
import html as html_lib
import os
import re
import sys
import unicodedata
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_ROOT = os.environ.get("COLLEGEDASH_CODE_ROOT") or ROOT
sys.path.insert(0, CODE_ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import athletics_site, common  # noqa: E402
from collect.adapters import sidearm, wmt  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
BASE = "https://example.invalid"
SPORT = "/sports/womens-soccer"
PAGES = {  # fixture -> origin it was trimmed from (for the header-comment check)
    "sidearm/roster-no-staff": "hailstate.com",
    "sidearm/coaches-current-theme": "hailstate.com",
    "sidearm/coaches-staff-directory": "letsgopeay.com",
    "sidearm/roster-players-and-staff": "goarmywestpoint.com",
    "wmt/roster-mixed-theme-staff": "wsucougars.com",
}
REGISTRY = {  # the two platform templates as public/data/registry.json has them; nothing else is read
    "season": {"current": 2026},
    "sources": {"athleticsPlatforms": {
        "wmt": {"roster": "{baseUrl}{sportPath}/roster", "rosterSeason": "{baseUrl}{sportPath}/roster/season/{year}",
                "schedule": "{baseUrl}{sportPath}/schedule", "scheduleSeason": "{baseUrl}{sportPath}/schedule/season/{year}",
                "news": "{baseUrl}{sportPath}/news"},
        "sidearm": {"roster": "{baseUrl}{sportPath}/roster", "rosterSeason": "{baseUrl}{sportPath}/roster/{year}",
                    "schedule": "{baseUrl}{sportPath}/schedule", "scheduleSeason": "{baseUrl}{sportPath}/schedule/{year}",
                    "news": "{baseUrl}{sportPath}/archives", "rss": "{baseUrl}/rss?path=wsoc"},
    }},
}
ROSTER, COACHES, SCHEDULE = BASE + SPORT + "/roster", BASE + SPORT + "/coaches", BASE + SPORT + "/schedule"

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {ascii(detail)[:400]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name + ".html"), encoding="utf-8") as f:
        return f.read()


def run_collect(platform: str, pages: dict, *, fail: tuple = ()) -> tuple[dict | None, list[str], dict]:
    """athletics_site.collect over a URL -> (html, finalUrl) table. Returns (saved envelope, requested
    URLs in order, collect's return value). A URL in `fail`, or not in the table, raises FetchError."""
    requests: list[str] = []
    saved: dict = {}

    def fetch_text(url, **kw):
        requests.append(url)
        if url in fail or url not in pages:
            raise common.FetchError(f"HTTP 404 for {url}")
        body, final = pages[url]
        return body, {"url": url, "status": 200, "finalUrl": final or url, "fromCache": False}

    def save_source(slug, name, data, *, url, collector, extra=None):
        saved.update({"sourceUrl": url, **(extra or {}), "data": copy.deepcopy(data)})

    program = {"slug": "fixture", "athletics": {"platform": platform, "baseUrl": BASE, "sportPath": SPORT}}
    real = (common.fetch_text, common.save_source, common.log)
    common.fetch_text, common.save_source, common.log = fetch_text, save_source, (lambda msg: None)
    try:
        data = athletics_site.collect(program, REGISTRY, seasons_back=0, bios=False)
    finally:
        common.fetch_text, common.save_source, common.log = real
    return saved, requests, data


def head(rows: list[dict]) -> str | None:
    return next((s["name"] for s in rows if s["isHeadCoach"]), None)


def test_coaches_pages_parse() -> None:
    """PIN: the roster table parser already reads both coaches-page shapes; the fallback relies on it."""
    print("PIN: the two coaches-page shapes parse unchanged")
    for name, want_rows, want_head, want_coaches in (
            ("sidearm/coaches-current-theme", 5, "Kevin O'Brien", 4),
            ("sidearm/coaches-staff-directory", 2, "Kim McGowan", 2)):
        r = sidearm.parse_roster(fixture(name), BASE)
        ok(f"PIN {name}: {want_rows} staff rows", len(r["staff"]) == want_rows, str(len(r["staff"])))
        ok(f"PIN {name}: head coach is {want_head}, the first row", head(r["staff"]) == want_head
           and r["staff"][0]["isHeadCoach"], str(head(r["staff"])))
        ok(f"PIN {name}: {want_coaches} of them coaches", sum(s["isCoach"] for s in r["staff"]) == want_coaches)
        ok(f"PIN {name}: no players on a coaches page", r["players"] == [])
        ok(f"PIN {name}: every row links its bio on the coaches path",
           all((s["bioUrl"] or "").startswith(BASE + SPORT + "/roster/coaches/") for s in r["staff"]))
    r = sidearm.parse_roster(fixture("sidearm/roster-no-staff"), BASE)
    ok("PIN sidearm/roster-no-staff: 3 players and zero staff rows - the state the fallback exists for",
       len(r["players"]) == 3 and r["staff"] == [], f"{len(r['players'])} players, {len(r['staff'])} staff")


def test_fallback_fills_an_empty_roster_page() -> None:
    print("FIX: a roster page with no staff takes them from /coaches")
    for coaches, want_head, want in (("sidearm/coaches-current-theme", "Kevin O'Brien", 5),
                                     ("sidearm/coaches-staff-directory", "Kim McGowan", 2)):
        pages = {ROSTER: (fixture("sidearm/roster-no-staff"), None), COACHES: (fixture(coaches), None),
                 SCHEDULE: ("<html></html>", None)}
        saved, requests, data = run_collect("sidearm", pages)
        staff = saved.get("data", {}).get("staff", [])
        ok(f"FIX {coaches}: the stored source has {want} staff rows", len(staff) == want, str(len(staff)))
        ok(f"FIX {coaches}: the stored head coach is {want_head}", head(staff) == want_head, str(head(staff)))
        ok(f"FIX {coaches}: exactly the rows the coaches page parses to, in page order",
           staff == sidearm.parse_roster(fixture(coaches), BASE)["staff"])
        ok(f"FIX {coaches}: /coaches requested exactly once", requests.count(COACHES) == 1, str(requests))
        ok(f"FIX {coaches}: the envelope says where the staff came from", saved.get("staffUrl") == COACHES,
           str(saved.get("staffUrl")))
        ok(f"FIX {coaches}: the players still come from the roster page", len(saved.get("data", {})
           .get("roster", {}).get("players", [])) == 3 and saved.get("sourceUrl") == ROSTER)
    # a redirect that keeps the sport's coaches path (texassports.com -> texaslonghorns.com) is used
    pages = {ROSTER: (fixture("sidearm/roster-no-staff"), None),
             COACHES: (fixture("sidearm/coaches-current-theme"), "https://other.invalid/sports/womens-soccer/coaches/"),
             SCHEDULE: ("<html></html>", None)}
    saved, _, _ = run_collect("sidearm", pages)
    ok("FIX a redirect to another host on the same coaches path is still this sport's coaches page",
       len(saved["data"]["staff"]) == 5, str(len(saved["data"]["staff"])))


def test_fallback_never_touches_roster_staff() -> None:
    """CONTROL: a roster page that lists staff keeps exactly those rows and makes no extra request."""
    print("CONTROL: roster-page staff is never replaced, merged or supplemented")
    roster_html = fixture("sidearm/roster-players-and-staff")
    want = sidearm.parse_roster(roster_html, BASE)["staff"]
    ok("CONTROL the army fixture has 7 staff rows of its own", len(want) == 7, str(len(want)))
    pages = {ROSTER: (roster_html, None), COACHES: (fixture("sidearm/coaches-current-theme"), None),
             SCHEDULE: ("<html></html>", None)}
    saved, requests, _ = run_collect("sidearm", pages)
    ok("CONTROL stored staff is exactly the roster page's, in order", saved["data"]["staff"] == want,
       str([s["name"] for s in saved["data"]["staff"]]))
    ok("CONTROL head coach is still Tracy Chao", head(saved["data"]["staff"]) == "Tracy Chao")
    ok("CONTROL /coaches is never requested", COACHES not in requests, str(requests))
    ok("CONTROL the requests are the roster and the schedule and nothing else", requests == [ROSTER, SCHEDULE],
       str(requests))
    ok("CONTROL no staffUrl in the envelope", "staffUrl" not in saved)


def test_fallback_refuses_what_is_not_this_sports_coaches_page() -> None:
    print("FIX, GUARD and CONTROL: the fallback's refusals")
    base_pages = {ROSTER: (fixture("sidearm/roster-no-staff"), None), SCHEDULE: ("<html></html>", None)}
    # CONTROL: the coaches page is missing (404, timeout): the program is stored as before, no staff
    saved, requests, _ = run_collect("sidearm", dict(base_pages), fail=(COACHES,))
    ok("CONTROL a failed /coaches fetch leaves zero staff and the source is still saved",
       saved.get("data", {}).get("staff") == [] and len(saved["data"]["roster"]["players"]) == 3)
    ok("FIX ... and it was tried once, not retried by the collector", requests.count(COACHES) == 1, str(requests))
    ok("CONTROL ... and no staffUrl is claimed", "staffUrl" not in saved)
    # GUARD: redirected off the sport's coaches path, e.g. to an athletics-wide staff directory
    for final in (BASE + "/staff-directory", BASE + "/sports/mens-soccer/coaches", BASE + "/"):
        pages = dict(base_pages, **{COACHES: (fixture("sidearm/coaches-current-theme"), final)})
        saved, _, _ = run_collect("sidearm", pages)
        ok(f"GUARD a /coaches request that ends at {final[len(BASE):]} is not used", saved["data"]["staff"] == [],
           str(len(saved["data"]["staff"])))
    # FIX, paired with the refusals above so they cannot pass by the fallback simply not existing
    pages = dict(base_pages, **{COACHES: (fixture("sidearm/coaches-current-theme"), COACHES)})
    saved, _, _ = run_collect("sidearm", pages)
    ok("FIX ... while the same page at its own path is used", len(saved["data"]["staff"]) == 5)
    # CONTROL: WMT has no /coaches template; a WMT roster with no staff requests nothing extra
    no_staff = re.sub(r'<div class="roster-staff-members".*', "</body></html>", fixture("wmt/roster-mixed-theme-staff"), flags=re.S)
    pages = {ROSTER: (no_staff, None), COACHES: (fixture("sidearm/coaches-current-theme"), None),
             SCHEDULE: ("<html></html>", None)}
    saved, requests, _ = run_collect("wmt", pages)
    ok("CONTROL a WMT program with no staff makes no /coaches request", COACHES not in requests
       and saved["data"]["staff"] == [], str(requests))


def test_wmt_mixed_theme() -> None:
    print("FIX: WMT staff in redesign markup beside players in the older markup")
    r = wmt.parse_roster(fixture("wmt/roster-mixed-theme-staff"), BASE)
    ok("PIN the fixture's three players still come from li.roster-list-item", len(r["players"]) == 3,
       str(len(r["players"])))
    ok("FIX all eight staff rows are read", len(r["staff"]) == 8, str(len(r["staff"])))
    ok("FIX the head coach is Chris Citowicki, the first row", head(r["staff"]) == "Chris Citowicki"
       and bool(r["staff"]) and r["staff"][0]["isHeadCoach"], str(head(r["staff"])))
    ok("FIX exactly one head coach (the associate head coach is not)",
       sum(s["isHeadCoach"] for s in r["staff"]) == 1, str([s["title"] for s in r["staff"] if s["isHeadCoach"]]))
    ok("FIX titles in page order", [s["title"] for s in r["staff"]] == [
        "Head Coach", "Associate Head Coach", "Assistant Coach", "Assistant Coach",
        "Assistant Director of Athletics, Sports Medicine", "Assistant Strength & Conditioning Coach",
        "Performance Nutrition Dietitian", "Academic Services"], str([s["title"] for s in r["staff"]]))
    ok("FIX every row has its own bio URL", len({s["bioUrl"] for s in r["staff"]}) == 8
       and all("/staff/" in (s["bioUrl"] or "") for s in r["staff"]))
    # CONTROL: when the older markup already yielded staff, li.staff-list-item is not read on top of it.
    # No cached page is in this state; the row is written into the fixture here, in the older theme's
    # own staff markup, so the rule is pinned rather than only measured.
    older_staff = ('<li class="roster-list-item"><div class="roster-list-item__title">Older Markup Coach</div>'
                   '<div class="roster-list-item__profile-field--position">Head Coach</div>'
                   f'<a href="{SPORT}/roster/staff/older-markup-coach">Full Bio</a></li>')
    both = fixture("wmt/roster-mixed-theme-staff").replace("</ul>", older_staff + "</ul>", 1)
    r = wmt.parse_roster(both, BASE)
    ok("CONTROL staff found in the older markup is the whole staff list, as before",
       [s["name"] for s in r["staff"]] == ["Older Markup Coach"] and len(r["players"]) == 3,
       str([s["name"] for s in r["staff"]]))
    saved, requests, _ = run_collect("wmt", {ROSTER: (fixture("wmt/roster-mixed-theme-staff"), None),
                                             SCHEDULE: ("<html></html>", None)})
    ok("FIX the collector stores the eight rows for a WMT program", len(saved["data"]["staff"]) == 8)
    ok("CONTROL ... from the roster page alone", requests == [ROSTER, SCHEDULE] and "staffUrl" not in saved,
       str(requests))


# Wider than the other suites' patterns on purpose: austin-peay's live coaches page prints seven-digit
# local numbers ('221-7972') that neither `(\d{3})[-. ]\d{3}[-. ]\d{4}` nor tools/camps_check.py sees.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+\s*(?:@|\(at\)|\[at\])\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.I)
PHONE_RE = re.compile(r"(?<![\d/_.-])(?:\(?\d{3}\)?[-. ]?)?\d{3}[-. ]\d{4}(?![\d/_.-])")


def contact_views(raw: str) -> list[str]:
    decoded = unicodedata.normalize("NFKC", unquote(html_lib.unescape(raw)))
    return [raw, decoded, re.sub(r"<[^>]+>", " ", decoded)]


def test_no_contact_details() -> None:
    print("privacy: the five fixtures carry no contact detail")
    for name, host in PAGES.items():
        raw = fixture(name)
        views = contact_views(raw)
        ok(f"{name}: header comment names where it was trimmed from", host in raw.split("-->", 1)[0])
        ok(f"{name}: no email address", not any(EMAIL_RE.search(v) for v in views),
           str([EMAIL_RE.findall(v)[:2] for v in views]))
        ok(f"{name}: no telephone number, seven or ten digits", not PHONE_RE.search(views[2]),
           str(PHONE_RE.findall(views[2])[:3]))
        ok(f"{name}: no mailto:, tel: or sms: link", not re.search(r"(?:mailto|tel|sms):", views[1], re.I))
        ok(f"{name}: no email, phone, office or fax column header",
           not re.search(r">\s*(?:e-?mail(?: address)?|phone(?: number)?|office|fax)\s*<", views[1], re.I))
        ok(f"{name}: no social-media link", not re.search(r"instagram\.com|twitter\.com|//x\.com|facebook\.com|tiktok\.com",
                                                          views[1], re.I))
    for name, want in (("sidearm/coaches-current-theme", 0), ("wmt/roster-mixed-theme-staff", 0)):
        ok(f"{name}: no image left", fixture(name).count("<img") == want)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    if CODE_ROOT != ROOT:
        print(f"code under test imported from {CODE_ROOT}")
    for case in (test_coaches_pages_parse, test_fallback_fills_an_empty_roster_page, test_fallback_never_touches_roster_staff,
                 test_fallback_refuses_what_is_not_this_sports_coaches_page, test_wmt_mixed_theme, test_no_contact_details):
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
