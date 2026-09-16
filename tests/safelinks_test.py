"""Checks that no Outlook Safe Links wrapper is stored by the athletics or camps collectors (issue #160).

    python tests/safelinks_test.py            # everything below, offline
    python tests/safelinks_test.py --verbose  # print every check, not only the failures

Offline: reads tests/fixtures/sidearm/schedule-safelinks.html and the roster fixture of issue #145, and
replaces collect.common.fetch_text / save_source with tables, so no request is made and nothing under
programs/ is written.

Swap-back proof: set COLLEGEDASH_CODE_ROOT to an export of origin/main's collect/ package and the code
under test is imported from there while the fixtures still come from this tree:

    git archive origin/main collect | tar -x -C /tmp/pre160
    COLLEGEDASH_CODE_ROOT=/tmp/pre160 python tests/safelinks_test.py

origin/main has no common.unwrap_link / common.unwrap_links. The suite then stands in the identity
function for both - which is exactly what origin/main does to a link - so every check still runs and
reports on its own instead of the whole case failing on an AttributeError.

Why this exists
---------------
Some schools paste links into their CMS from Outlook, which has rewritten them as
https://nam10.safelinks.protection.outlook.com/?url=<real URL>&data=<...|staff mailbox|...>&sdata=...
The collectors stored them verbatim: 13 california-state-los-angeles schedule 'watch' links, 3 clemson
camp registerUrls and 1 old-dominion 'live stats' link across the 2,948 stored sources on main. A
visitor who clicks one goes through Microsoft's redirector with a staff mailbox in the URL. The fix
stores the decoded `url` parameter, and stores no link at all when that does not decode to an
absolute http(s) URL.

Labels: FIX checks fail against origin/main and pass after the change. CONTROL checks pass on both by
design - an ordinary link, a look-alike host, and a page with no wrapper are left exactly as they were.
"""

from __future__ import annotations

import argparse
import copy
import os
import re
import sys
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_ROOT = os.environ.get("COLLEGEDASH_CODE_ROOT") or ROOT
sys.path.insert(0, CODE_ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import athletics_site, camps, common  # noqa: E402
from collect.adapters import sidearm  # noqa: E402

unwrap_link = getattr(common, "unwrap_link", lambda u: u)
unwrap_links = getattr(common, "unwrap_links", lambda o: o)

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
BASE = "https://example.invalid"
SPORT = "/sports/womens-soccer"
PLACEHOLDER_DATA = "05%7C02%7Cplaceholder%40example.invalid%7C0ac03cb5%7C0%7C0%7C639233812585201345%7CUnknown%7C%7C%7C"


def wrap(target: str, host: str = "nam10.safelinks.protection.outlook.com") -> str:
    """A wrapper in the exact shape stored on main: url, data, sdata, reserved."""
    return f"https://{host}/?url={quote(target, safe='')}&data={PLACEHOLDER_DATA}&sdata=AbCdEf%3D&reserved=0"


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


def wrapped_anywhere(obj) -> list[str]:
    found = []

    def walk(v):
        if isinstance(v, str):
            if "safelinks" in v.lower() or "example.invalid%7c" in v.lower() or "placeholder" in v.lower():
                found.append(v[:80])
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(obj)
    return found


def test_unwrap_link() -> None:
    print("the unwrap rule")
    csula = ("https://nam10.safelinks.protection.outlook.com/?url=https%3A%2F%2Fflosports.link%2F4fHQ89Z"
             f"&data={PLACEHOLDER_DATA}&sdata=x&reserved=0")
    ok("FIX the CSULA shape unwraps to its flosports link", unwrap_link(csula) == "https://flosports.link/4fHQ89Z",
       str(unwrap_link(csula)))
    target = "https://stats.statbroadcast.com/broadcast/?id=495505&vislive=odu"
    ok("FIX a target with its own query string comes back whole", unwrap_link(wrap(target, "nam11.safelinks.protection.outlook.com")) == target)
    ok("FIX clemson's region and path shape", unwrap_link(wrap("https://apps.ideal-logic.com/cuathletics?key=S2QM",
                                                               "nam12.safelinks.protection.outlook.com")) == "https://apps.ideal-logic.com/cuathletics?key=S2QM")
    ok("FIX host matched without regard to case", unwrap_link(wrap("https://a.example/x", "NAM10.SafeLinks.Protection.Outlook.COM")) == "https://a.example/x")
    ok("FIX the US-government service (office365.us)", unwrap_link(wrap("https://a.example/x", "gcc02.safelinks.protection.office365.us")) == "https://a.example/x")
    ok("FIX a wrapper around a wrapper unwraps all the way", unwrap_link(wrap(wrap("https://a.example/deep"))) == "https://a.example/deep")
    ok("FIX the parameter name is matched without regard to case",
       unwrap_link("https://nam10.safelinks.protection.outlook.com/?URL=https%3A%2F%2Fa.example%2Fx&data=1") == "https://a.example/x")
    for label, bad in (("a javascript: target", wrap("javascript:alert(1)")),
                       ("a mailto: target", wrap("mailto:placeholder@example.invalid")),
                       ("a relative target", wrap("/sports/womens-soccer")),
                       ("no url parameter", f"https://nam10.safelinks.protection.outlook.com/?data={PLACEHOLDER_DATA}"),
                       ("an empty url parameter", "https://nam10.safelinks.protection.outlook.com/?url=&data=1"),
                       ("a scheme with no host", wrap("https:///nohost"))):
        ok(f"FIX {label} gives no link, never the wrapper", unwrap_link(bad) is None, str(unwrap_link(bad))[:80])
    for label, keep in (("an ordinary link", "https://flosports.link/4fHQ89Z"),
                        ("a look-alike host that is not Microsoft's", "https://safelinks.protection.outlook.com.example.invalid/?url=https%3A%2F%2Fa.example"),
                        ("a URL merely carrying another URL in its query", "https://go.active.com/?c=1&t=https%3A%2F%2Fcampscui.active.com%2Forgs%2FX"),
                        ("None", None), ("an empty string", "")):
        ok(f"CONTROL {label} is returned unchanged", unwrap_link(keep) == keep, str(unwrap_link(keep)))


def test_unwrap_links_structure() -> None:
    print("where an unwrapped or dropped link goes")
    game = {"opponent": "Cal Poly Pomona", "links": {"watch": wrap("https://flosports.link/4fHQ89Z"),
                                                     "tickets": "https://events.example/x",
                                                     "live stats": wrap("javascript:void(0)")}}
    out = unwrap_links(copy.deepcopy(game))
    ok("FIX links.watch becomes the real link", out["links"].get("watch") == "https://flosports.link/4fHQ89Z", str(out["links"].get("watch"))[:80])
    ok("FIX an undecodable wrapper is removed from a links mapping, not left as null", "live stats" not in out["links"],
       str(out["links"]))
    ok("CONTROL the other link and fields are untouched", out["links"].get("tickets") == "https://events.example/x"
       and out["opponent"] == "Cal Poly Pomona")
    camp = {"name": "ID Camp", "registerUrl": wrap("ftp://files.example/form"), "sourceUrl": "https://clemsontigers.com/camp"}
    out = unwrap_links(copy.deepcopy(camp))
    ok("FIX an undecodable wrapper in an ordinary field becomes null", "registerUrl" in out and out["registerUrl"] is None,
       str(out.get("registerUrl"))[:80])
    lst = unwrap_links(["https://a.example/1", wrap("https://a.example/2"), wrap("data:text/html,x")])
    ok("FIX in a list: unwrapped in place, undecodable dropped", lst == ["https://a.example/1", "https://a.example/2"], str(lst)[:160])
    text = f"Watch live at {wrap('https://flosports.link/abc')} or listen at {wrap('javascript:x')} today."
    ok("FIX a wrapper inside prose is replaced by its target, an undecodable one removed",
       unwrap_links({"bio": text})["bio"] == "Watch live at https://flosports.link/abc or listen at  today.",
       unwrap_links({"bio": text})["bio"][:160])
    plain = {"a": [1, 2.5, None, True, {"b": "https://x.example/?url=https%3A%2F%2Fy.example"}], "safelinks": "a word, not a link"}
    ok("CONTROL an object with no wrapper comes back equal", unwrap_links(copy.deepcopy(plain)) == plain)


def run_athletics(schedule_html: str) -> tuple[dict, list[str]]:
    saved, requests = {}, []
    pages = {BASE + SPORT + "/roster": fixture("sidearm/roster-players-and-staff"), BASE + SPORT + "/schedule": schedule_html}

    def fetch_text(url, **kw):
        requests.append(url)
        if url not in pages:
            raise common.FetchError(f"HTTP 404 for {url}")
        return pages[url], {"url": url, "status": 200, "finalUrl": url, "fromCache": False}

    def save_source(slug, name, data, *, url, collector, extra=None):
        saved.update({"sourceUrl": url, **(extra or {}), "data": copy.deepcopy(data)})

    registry = {"season": {"current": 2026}, "sources": {"athleticsPlatforms": {"sidearm": {
        "roster": "{baseUrl}{sportPath}/roster", "rosterSeason": "{baseUrl}{sportPath}/roster/{year}",
        "schedule": "{baseUrl}{sportPath}/schedule", "scheduleSeason": "{baseUrl}{sportPath}/schedule/{year}",
        "news": "{baseUrl}{sportPath}/archives", "rss": "{baseUrl}/rss?path=wsoc"}}}}
    program = {"slug": "fixture", "athletics": {"platform": "sidearm", "baseUrl": BASE, "sportPath": SPORT}}
    real = (common.fetch_text, common.save_source, common.log)
    common.fetch_text, common.save_source, common.log = fetch_text, save_source, (lambda m: None)
    try:
        athletics_site.collect(program, registry, seasons_back=0, bios=False)
    finally:
        common.fetch_text, common.save_source, common.log = real
    return saved, requests


def test_athletics_collector() -> None:
    print("athletics: the CSULA schedule, collected")
    html = fixture("sidearm/schedule-safelinks")
    parsed = sidearm.parse_schedule(html, BASE)
    ok("CONTROL the fixture parses to three games, two with a wrapped watch link",
       len(parsed["games"]) == 3 and sum("safelinks" in (g["links"].get("watch") or "") for g in parsed["games"]) == 2,
       str([sorted(g["links"]) for g in parsed["games"]]))
    saved, requests = run_athletics(html)
    games = saved.get("data", {}).get("schedule", {}).get("games", [])
    ok("CONTROL the collector stored all three games", len(games) == 3, str(len(games)))
    ok("FIX no stored value anywhere is a wrapper or carries the wrapper's mailbox",
       not wrapped_anywhere(saved), str(wrapped_anywhere(saved)[:2]))
    ok("FIX 2026-09-18 Cal Poly Pomona: watch is https://flosports.link/4fHQ89Z",
       len(games) == 3 and games[1]["links"].get("watch") == "https://flosports.link/4fHQ89Z", str(games[1]["links"].get("watch") if len(games) == 3 else games)[:90])
    ok("FIX 2026-10-02 Cal Poly Humboldt: watch is https://flosports.link/4h8W527",
       len(games) == 3 and games[2]["links"].get("watch") == "https://flosports.link/4h8W527", str(games[2]["links"].get("watch") if len(games) == 3 else games)[:90])
    ok("CONTROL every other link on those games is the one the page gives",
       len(games) == 3 and all(games[i]["links"].get(k) == v for i in range(3)
                               for k, v in parsed["games"][i]["links"].items() if "safelinks" not in v))
    ok("CONTROL the unwrapped links are stored without any extra request", requests == [BASE + SPORT + "/roster", BASE + SPORT + "/schedule"],
       str(requests))
    # the same page with one wrapper made undecodable: that watch link is not stored at all
    broken = html.replace("url=https%3A%2F%2Fflosports.link%2F4h8W527", "url=javascript%3Avoid(0)")  # every copy of that row's link
    ok("CONTROL (setup) the broken copy differs from the fixture", broken != html)
    saved, _ = run_athletics(broken)
    games = saved.get("data", {}).get("schedule", {}).get("games", [])
    ok("FIX a watch wrapper that decodes to javascript: is not stored, and the game keeps its other links",
       len(games) == 3 and "watch" not in games[2]["links"] and bool(games[2]["links"].get("live stats")),
       str(games[2]["links"] if len(games) == 3 else games)[:160])


def test_camps() -> None:
    print("camps: a registration link wrapped in Safe Links")
    reg = "https://apps.ideal-logic.com/cuathletics?key=S2QM-6QBSB"
    ok("FIX camps._http_url unwraps", camps._http_url(wrap(reg, "nam12.safelinks.protection.outlook.com")) == reg,
       str(camps._http_url(wrap(reg)))[:80])
    ok("FIX camps._http_url gives None for an undecodable wrapper", camps._http_url(wrap("javascript:alert(1)")) is None)
    ok("CONTROL camps._http_url still refuses javascript: and resolves relative links",
       camps._http_url("javascript:alert(1)") is None and camps._http_url("/camp", "https://clemsontigers.com/x") == "https://clemsontigers.com/camp")
    page = ("<html><head><title>Tiger Girls Soccer Camp</title></head><body><main><h2>Tiger Girls Soccer Camp</h2>"
            f"<p>Elite ID Camp: June 14-15, 2027. <a href=\"{wrap(reg, 'nam12.safelinks.protection.outlook.com')}\">Register</a></p>"
            "</main></body></html>")
    rows = camps.extract_camps(page, "https://clemsontigers.com/tiger-girls-soccer-camp", title="Tiger Girls Soccer Camp")
    ok("CONTROL (setup) the page yields its one camp", len(rows) == 1, str(rows)[:200])
    ok("FIX the camp's registerUrl is the real registration page", bool(rows) and rows[0]["registerUrl"] == reg,
       str(rows[0]["registerUrl"] if rows else None)[:90])

    saved = {}
    url = "https://clemsontigers.com/tiger-girls-soccer-camp/"

    titled = page.replace("<title>Tiger Girls Soccer Camp</title>",
                          f"<title>Tiger Girls Soccer Camp {wrap(reg, 'nam12.safelinks.protection.outlook.com')}</title>")

    def fetch_text(u, **kw):
        if u != url:
            raise common.FetchError(f"HTTP 404 for {u}")
        return titled, {"url": u, "status": 200, "finalUrl": u, "fromCache": False, "contentType": "text/html"}

    def save_source(slug, name, data, *, url, collector, extra=None):
        saved.update({"sourceUrl": url, "data": copy.deepcopy(data)})

    program = {"slug": "fixture", "athletics": {"platform": "sidearm", "baseUrl": "https://clemsontigers.com",
                                                "sportPath": SPORT, "campsUrl": wrap(url, "nam12.safelinks.protection.outlook.com")}}
    real = (common.fetch_text, common.save_source, common.log, common.load_source)
    common.fetch_text, common.save_source, common.log, common.load_source = fetch_text, save_source, (lambda m: None), (lambda *a, **k: None)
    try:
        camps.collect(program, {"season": {"current": 2026}})
    except Exception as e:
        ok("camps.collect ran to the end", False, f"{type(e).__name__}: {e}")
    finally:
        common.fetch_text, common.save_source, common.log, common.load_source = real
    data = saved.get("data", {})
    ok("FIX a wrapped registry campsUrl is followed to the real camps page", data.get("campsUrl") == url.rstrip("/") or data.get("campsUrl") == url,
       str(data.get("campsUrl"))[:90])
    ok("FIX the stored camps source holds no wrapper and no mailbox anywhere", bool(saved) and not wrapped_anywhere(saved),
       str(wrapped_anywhere(saved)[:2]))
    ok("FIX ... and its one camp registers at the real page", [c.get("registerUrl") for c in data.get("camps", [])] == [reg],
       str([c.get("registerUrl") for c in data.get("camps", [])])[:120])
    ok("FIX a wrapper outside the URL fields (here in the page title) is unwrapped too, by the last pass before saving",
       # the collector cuts pageTitle to 120 characters before this pass, so the target is cut too
       (data.get("pageTitle") or "").startswith("Tiger Girls Soccer Camp https://apps.ideal-logic.com/")
       and "safelinks" not in (data.get("pageTitle") or ""), str(data.get("pageTitle"))[:120])


def test_no_contact_details() -> None:
    print("privacy: the CSULA fixture")
    import html as html_lib
    import unicodedata
    from urllib.parse import unquote
    raw = fixture("sidearm/schedule-safelinks")
    decoded = unicodedata.normalize("NFKC", unquote(unquote(html_lib.unescape(raw))))
    emails = set(re.findall(r"[A-Za-z0-9._+-]+\s*(?:@|\(at\)|\[at\])\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}", decoded, re.I))
    ok("the only address, raw or decoded, is the placeholder", emails == {"placeholder@example.invalid"}, str(emails))
    flat = re.sub(r"<[^>]+>", " ", decoded)
    phones = re.findall(r"(?<![\d/_.-])(?:\(?\d{3}\)?[-. ]?)?\d{3}[-. ]\d{4}(?![\d/_.-])", flat)
    ok("no telephone number, seven or ten digits", not phones, str(phones))
    ok("no mailto:, tel: or sms: link", not re.search(r"(?:mailto|tel|sms):", decoded, re.I))
    ok("header comment names where it was trimmed from", "lagoldeneagles.com" in raw.split("-->", 1)[0])


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    if CODE_ROOT != ROOT:
        print(f"code under test imported from {CODE_ROOT}")
    for case in (test_unwrap_link, test_unwrap_links_structure, test_athletics_collector, test_camps, test_no_contact_details):
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
