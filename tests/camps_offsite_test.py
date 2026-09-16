"""Checks that a camps link off the athletics site is used only when it is a camp vendor's or the school's
(issue #162).

    python tests/camps_offsite_test.py            # everything below, offline
    python tests/camps_offsite_test.py --verbose  # print every check, not only the failures

Offline: reads tests/fixtures/camps/offsite/ and replaces collect.common's fetch_text, robots_allowed,
load_source, save_source and log with tables, so camps.collect runs end to end with no request and
nothing written under programs/.

Swap-back proof: set COLLEGEDASH_CODE_ROOT to an export of origin/main's collect/ package and the code
under test is imported from there while the fixtures still come from this tree:

    git archive origin/main collect | tar -x -C /tmp/pre162
    COLLEGEDASH_CODE_ROOT=/tmp/pre162 python tests/camps_offsite_test.py

Why this exists
---------------
missouri-western-state's roster page links, in its site navigation, to 'KANSAS CITY CHIEFS TRAINING
CAMP' at chiefs.com/trainingcamp/ (the NFL team trains on that campus). It was the page's only camp
link, find_camps_link had no rule about pages off the athletics site, and the Chiefs' news cards were
stored as four dated camps. An off-site camps page must now show it is a camp vendor's or the school's,
from the link (vendor host, .edu, a school store, soccer, women/girls, an ID camp, or the school's name)
or from the fetched page (vendor markup, or a title naming the school).

Labels: FIX checks fail against origin/main and pass after the change. CONTROL checks pass on both by
design: which link is picked does not change, and a legitimate off-site camps site is still used.
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

from collect import camps, common  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "camps", "offsite")
MWSU_ROSTER = "https://www.gogriffons.com/sports/womens-soccer/roster"
CHIEFS = "https://www.chiefs.com/trainingcamp/"
EB_ROSTER = "https://eastbaypioneers.com/sports/womens-soccer/roster"
EB_CAMPS = "https://eastbaysportscamps.com/"

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


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name + ".html"), encoding="utf-8") as f:
        return f.read()


def run_collect(base: str, pages: dict, *, robots_denied: tuple = ()) -> tuple[dict, list[str], list[str]]:
    """camps.collect for a program at `base` over a URL -> html table. Returns (saved data, requests, log)."""
    saved, requests, logs = {}, [], []

    def fetch_text(url, **kw):
        requests.append(url)
        if url not in pages:
            raise common.FetchError(f"HTTP 404 for {url}")
        return pages[url], {"url": url, "status": 200, "finalUrl": url, "fromCache": False, "contentType": "text/html"}

    def save_source(slug, name, data, *, url, collector, extra=None):
        saved.update(copy.deepcopy(data))

    program = {"slug": "fixture", "athletics": {"platform": "auto", "baseUrl": base, "sportPath": "/sports/womens-soccer"}}
    real = (common.fetch_text, common.save_source, common.log, common.load_source, common.robots_allowed)
    common.fetch_text, common.save_source, common.log = fetch_text, save_source, logs.append
    common.load_source = lambda *a, **k: None
    common.robots_allowed = lambda url: not any(url.startswith(d) for d in robots_denied)
    try:
        camps.collect(program, {})
    finally:
        common.fetch_text, common.save_source, common.log, common.load_source, common.robots_allowed = real
    return saved, requests, logs


def test_missouri_western() -> None:
    print("missouri-western-state: the Kansas City Chiefs' training camp")
    roster = fixture("roster-missouri-western-state")
    link = camps.find_camps_link(roster, MWSU_ROSTER)
    ok("CONTROL find_camps_link still picks the page's one camp link (the pick is unchanged)",
       bool(link) and link["url"] == CHIEFS, str(link))
    ok("FIX ... and says the link does not vouch for itself", bool(link) and link.get("vouched") is False, str(link))
    saved, requests, logs = run_collect("https://www.gogriffons.com", {MWSU_ROSTER: roster, CHIEFS: fixture("chiefs-training-camp")})
    ok("CONTROL (setup) the Chiefs page yields camp rows to the extractor",
       len(camps.extract_camps(fixture("chiefs-training-camp"), CHIEFS, title="2026 Chiefs Training Camp")) == 2)
    ok("FIX the stored camps source has no camps link", saved.get("campsUrl") is None, str(saved.get("campsUrl")))
    ok("FIX ... and none of the Chiefs' dates as camps", saved.get("camps") == [], str([c.get("name") for c in saved.get("camps") or []]))
    ok("FIX ... and no vendor, host or page title from chiefs.com",
       saved.get("vendor") is None and saved.get("host") is None and saved.get("pageTitle") is None,
       str({k: saved.get(k) for k in ("vendor", "host", "pageTitle")}))
    ok("FIX the log says why the link was not used", any("not used (#162)" in m for m in logs), str(logs)[:300])
    # robots.txt denies the Chiefs page: nothing to read, so nothing can vouch for it
    saved, _, _ = run_collect("https://www.gogriffons.com", {MWSU_ROSTER: roster}, robots_denied=("https://www.chiefs.com",))
    ok("FIX an unvouched off-site link whose page robots.txt denies is not kept as a link-only camps page",
       saved.get("campsUrl") is None and saved.get("robotsBlocked") is False, str({k: saved.get(k) for k in ("campsUrl", "robotsBlocked")}))


def test_school_site_still_used() -> None:
    print("california-state-east-bay: an off-site camps site that is the school's")
    roster = fixture("roster-california-state-east-bay")
    saved, _, _ = run_collect("https://eastbaypioneers.com", {EB_ROSTER: roster, EB_CAMPS: fixture("eastbaysportscamps")})
    ok("CONTROL eastbaysportscamps.com ('Cal State East Bay Camps') is still the camps page", saved.get("campsUrl") == EB_CAMPS,
       str(saved.get("campsUrl")))
    ok("CONTROL ... with its page title stored", saved.get("pageTitle") == "Cal State East Bay Camps", str(saved.get("pageTitle")))
    anonymous = fixture("eastbaysportscamps").replace("<title>Cal State East Bay Camps</title>", "<title>Summer Camps</title>")
    ok("CONTROL (setup) the anonymous copy differs", anonymous != fixture("eastbaysportscamps"))
    saved, _, _ = run_collect("https://eastbaypioneers.com", {EB_ROSTER: roster, EB_CAMPS: anonymous})
    ok("FIX the same generic off-site link is not used when its page names neither a vendor nor the school",
       saved.get("campsUrl") is None, str(saved.get("campsUrl")))
    ryzer = anonymous.replace("<main>", '<main><img src="https://s3.amazonaws.com/ryzer/logo.png">')
    saved, _, _ = run_collect("https://eastbaypioneers.com", {EB_ROSTER: roster, EB_CAMPS: ryzer})
    ok("CONTROL ... and is used when the page is a camp vendor's by its markup (Ryzer)", saved.get("campsUrl") == EB_CAMPS,
       str(saved.get("campsUrl")))


def test_what_a_link_vouches_for() -> None:
    print("what an off-site link shows by itself")
    stanford_title = "<title>Women's Soccer 2026 - Stanford Cardinal - Official Athletics Website</title>"
    page = "https://gostanford.com/sports/womens-soccer/roster"

    def vouched(href: str, text: str, title: str = stanford_title, roster_url: str = page):
        html = f"<html><head>{title}</head><body><nav><a href=\"{href}\">{text}</a></nav></body></html>"
        link = camps.find_camps_link(html, roster_url)
        return None if link is None else link.get("vouched")

    for label, href, text, want in (
            ("same site", "https://gostanford.com/camps", "Camps", True),
            ("another host on the athletics site's own domain", "https://camps.gostanford.com/", "Camps", True),
            ("a camp vendor's host", "https://stanfordwsoc.totalcamps.com/About%20Us", "Camps", True),
            ("a .edu host", "https://summer.stanford.edu/camps", "Camps", True),
            ("a school's hosted store", "https://secure.touchnet.net/C20127_ustores/web/index.jsp", "Camps and Clinics", True),
            ("soccer named in the host", "https://www.cardinalsoccercamps.com/", "Camps", True),
            ("girls named in the text", "https://www.example-camps.com/", "Girls Camps", True),
            ("an ID camp", "https://www.example-camps.com/", "Summer ID Camp", True),
            ("the school in the host", "https://stanfordathleticscamps.com/", "Camps", True),
            ("an off-site page that merely says camp", "https://www.chiefs.com/trainingcamp/", "TRAINING CAMP", False),
            ("an all-sports camps site that does not name the school", "https://www.bestsummercamps.com/", "Camps", False)):
        got = vouched(href, text)
        ok(f"{'FIX' if want is not None else 'CONTROL'} {label}: vouched is {want}", got is want, f"{href} -> {got}")
    wmu = "<title>2026 Women's Soccer Roster - Western Michigan University Athletics</title>"
    ok("FIX the school's initials lead a host label (wmuevents.com for Western Michigan University)",
       vouched("http://www.wmuevents.com/", "Camps, Events & Outings", wmu, "https://wmubroncos.com/sports/womens-soccer/roster") is True)
    ok("FIX initials inside another word do not name the school (swmuevents.com)",
       vouched("http://www.swmuevents.com/", "Camps", wmu, "https://wmubroncos.com/sports/womens-soccer/roster") is False)


def test_no_contact_details() -> None:
    print("privacy: tests/fixtures/camps/offsite/")
    names = sorted(f for f in os.listdir(FIXTURES) if f.endswith(".html"))
    ok("four fixtures", len(names) == 4, str(names))
    for n in names:
        raw = open(os.path.join(FIXTURES, n), encoding="utf-8").read()
        decoded = unicodedata.normalize("NFKC", unquote(html_lib.unescape(raw)))
        flat = re.sub(r"<[^>]+>", " ", decoded)
        emails = re.findall(r"[A-Za-z0-9._%+-]+\s*(?:@|\(at\)|\[at\])\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}", decoded, re.I)
        phones = re.findall(r"(?<![\d/_.-])(?:\(?\d{3}\)?[-. ]?)?\d{3}[-. ]\d{4}(?![\d/_.-])", flat)
        ok(f"{n}: no email address", not emails, str(emails))
        ok(f"{n}: no telephone number, seven or ten digits", not phones, str(phones))
        ok(f"{n}: no mailto:, tel: or sms: link", not re.search(r"(?:mailto|tel|sms):", decoded, re.I))
        ok(f"{n}: header comment says where it was trimmed from", "Trimmed from https://" in raw.split("-->", 1)[0])


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    if CODE_ROOT != ROOT:
        print(f"code under test imported from {CODE_ROOT}")
    for case in (test_missouri_western, test_school_site_still_used, test_what_a_link_vouches_for, test_no_contact_details):
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
