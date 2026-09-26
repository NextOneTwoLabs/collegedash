"""robots.txt in the shared fetch path: report mode, the time budget and the keep rules (issue #101, PR A).

    python tests/robots_enforcement_test.py            # everything below, offline (local stub hosts only)
    python tests/robots_enforcement_test.py --verbose

The owner-approved plan (issue #101, round 2, Bianque's conditions) and owner decision 1 = B:

  adapter     the check sits in _PoliteAdapter.send, the shared request hook: the first request AND every redirect
              hop, keyed by the host each hop contacts. off = no check and no robots.txt request; report = nothing
              blocked, each would-be block counted under its call-site label; enforce = RobotsDisallowed before
              anything is sent. The robots.txt request itself is exempt (no recursion, fetched once per host). A
              cache hit makes no request and is not checked.
  decision B  a robots.txt that answers 5xx or cannot be reached is ALLOWED and counted (departs from RFC 9309),
              with whether the host's pages then loaded; 4xx stays allowed; explicit robots_allowed() follows B.
  delays      report mode keeps every delay that applies today: a host an explicit robots_allowed() call checked is
              spaced by its Crawl-delay (also when the adapter loaded it first); a host only the adapter saw has its
              delay recorded, not applied. Enforce applies it. A non-integer Crawl-delay (2.5) is read.
  report      refresh-state.robots holds counts, hosts and paths only (no query string, no page content), and the
              projected enforced run time.
  keep        a RobotsDisallowed page never erases stored data, matched by a stable key, and the block is counted:
              bio/club by bioUrl, past-season roster and schedule by year, coaches page staff, camp page camps by
              campsUrl; a collector with no catch (news) is skipped, reason robots, and its source is not rewritten.
              Controls: an ordinary fetch error at the same place still behaves as before.
  budget      refresh --time-budget-minutes: after the budget no new program starts; the rest are skipped with
              reason 'time budget' (never failed), their refresh-state is untouched, and report_refresh names them.
  workflow    refresh.yml: COLLEGEDASH_ROBOTS=report and a 270-minute budget on the collector step, timeout-minutes
              300 on the step and 350 on the job, and the commit step still `if: always()` after it.
Offline: stub hosts on 127.0.0.1 and fakes; run under the network guard (tests/netguard), nothing leaves the machine.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import socket
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import refresh_politeness_test as pol  # noqa: E402  (its stub hosts and fresh_state; it clears proxy variables)
import collegedash  # noqa: E402
from collect import adapters, athletics_site, camps, common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False
DELAY = 1.0  # a Crawl-delay above the suite's gap (pol.GAP = 0.25)


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:400]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


@contextlib.contextmanager
def mode(value: str | None):
    prev = os.environ.get("COLLEGEDASH_ROBOTS")
    if value is None:
        os.environ.pop("COLLEGEDASH_ROBOTS", None)
    else:
        os.environ["COLLEGEDASH_ROBOTS"] = value
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("COLLEGEDASH_ROBOTS", None)
        else:
            os.environ["COLLEGEDASH_ROBOTS"] = prev


@contextlib.contextmanager
def fresh(tmp: str):
    with pol.fresh_state(tmp):
        for d in (common._robots_state, common._robots_delay):
            d.clear()
        common._explicit_hosts.clear()
        common.reset_robots_report()
        yield


def page(body: bytes = b"<html>page</html>"):
    return lambda path, n: (200, {"Content-Type": "text/html"}, body, 0.0)


def robots(text: str):
    return lambda path, n: (200, {"Content-Type": "text/plain"}, text.encode(), 0.0)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------- adapter ----------

def test_adapter(tmp: str) -> None:
    print("adapter: off / report / enforce, redirect hops, no recursion, cache hits")
    rules = "User-agent: *\nDisallow: /private/\n"
    b = pol.Stub("b", routes={"/robots.txt": robots(rules), "/private/": page(b"<html>secret</html>"), "/open": page()})
    a = pol.Stub("a", routes={"/robots.txt": robots("User-agent: *\nAllow: /\n"), "/go": lambda p, n: (
        302, {"Location": b.url("/private/x")}, b"", 0.0)})
    try:
        with fresh(tmp), mode(None):
            body, _ = common.fetch(b.url("/private/x?token=abc"), max_age_hours=None)
            ok("off (the default): a disallowed page is fetched as before", body == b"<html>secret</html>")
            ok("off: robots.txt is not requested", b.hits.get("/robots.txt") is None, b.hits)
        b.reset(); a.reset()
        with fresh(tmp), mode("report"):
            with common.fetch_site("athletics.historyRoster"):
                body, _ = common.fetch(b.url("/private/x?token=abc"), max_age_hours=None)
            common.fetch(b.url("/open"), max_age_hours=None)
            common.fetch(b.url("/open"), max_age_hours=6)  # a cache hit: no request, no check
            rep = common.robots_report(elapsed_seconds=60, workers=1)
            ok("report: nothing is blocked, the page is served", body == b"<html>secret</html>")
            ok("report: robots.txt fetched once for the host", b.hits.get("/robots.txt") == 1, b.hits)
            ok("report: the robots.txt request is not itself checked or counted, and a cache hit is not checked",
               rep["requestsChecked"] == 2, rep["requestsChecked"])
            wb = rep["wouldBlock"]
            ok("report: the would-be block is counted under its call site and collector",
               wb["total"] == 1 and wb["bySite"] == {"athletics.historyRoster": 1} and wb["byCollector"] == {"athletics": 1}, wb)
            ok("report: host and path only, never the query string",
               wb["topHosts"] == [{"host": b.host, "count": 1}] and wb["samplePaths"] == [
                   {"host": b.host, "path": "/private/x", "site": "athletics.historyRoster"}]
               and "token" not in json.dumps(rep), wb)
        b.reset(); a.reset()
        with fresh(tmp), mode("report"):
            with common.fetch_site("camps.page"):
                common.fetch(a.url("/go"), max_age_hours=None)
            wb = common.robots_report(elapsed_seconds=1, workers=1)["wouldBlock"]
            ok("report: a redirect hop onto a disallowed path is checked on the host it contacts",
               wb["bySite"] == {"camps.page": 1} and wb["topHosts"] == [{"host": b.host, "count": 1}], wb)
        b.reset(); a.reset()
        with fresh(tmp), mode("enforce"):
            try:
                common.fetch(b.url("/private/x"), max_age_hours=None)
                ok("enforce: a disallowed page raises RobotsDisallowed", False, "no error")
            except common.RobotsDisallowed as e:
                ok("enforce: a disallowed page raises RobotsDisallowed (a FetchError)", isinstance(e, common.FetchError))
            ok("enforce: and nothing is sent to it", b.hits.get("/private/x") is None, b.hits)
            try:
                with common.fetch_site("camps.page"):
                    common.fetch(a.url("/go"), max_age_hours=None)
                ok("enforce: a redirect hop onto a disallowed path raises", False, "no error")
            except common.RobotsDisallowed as e:
                ok("enforce: a redirect hop onto a disallowed path raises, with its call site", e.site == "camps.page", e.site)
            ok("enforce: the hop's target is never requested", b.hits.get("/private/x") is None, b.hits)
            body, _ = common.fetch(b.url("/open"), max_age_hours=None)
            ok("enforce: an allowed page on the same host is fetched", body == b"<html>page</html>")
    finally:
        a.close(); b.close()


# ---------- decision B ----------

def test_decision_b(tmp: str) -> None:
    print("decision B: the hook (report mode) allows and counts a 5xx or unreachable robots.txt; the explicit "
          "robots_allowed() checks stay strict (the owner, 2026-09-26); 4xx allowed by both")
    s5 = pol.Stub("5xx", routes={"/robots.txt": lambda p, n: (503, {}, b"down", 0.0), "/page": page()})
    s4 = pol.Stub("4xx", routes={"/robots.txt": lambda p, n: (404, {}, b"", 0.0), "/page": page()})
    dead = f"127.0.0.1:{free_port()}"
    try:
        with fresh(tmp), mode("report"):
            body, _ = common.fetch(s5.url("/page"), max_age_hours=None)
            ok("B, the hook: a 5xx robots.txt - the page is fetched and nothing is counted as a block",
               body == b"<html>page</html>")
            body, _ = common.fetch(s4.url("/page"), max_age_hours=None)
            ok("CONTROL a 4xx robots.txt: allowed, as before", body == b"<html>page</html>")
            try:
                common.fetch(f"http://{dead}/page", max_age_hours=None, retries=1)
                ok("unreachable: the page fetch fails on the network", False, "no error")
            except common.FetchError:
                ok("B, the hook: an unreachable robots.txt is not a block (the page's own network error instead)", True)
            rep = common.robots_report(elapsed_seconds=1, workers=1)
            ok("B, the hook: none of the three is counted as a would-be block", rep["wouldBlock"]["total"] == 0,
               rep["wouldBlock"])
            ok("the robots.txt states are counted", rep["robotsTxt"] == {"4xx": 1, "5xx": 1, "unreachable": 1}, rep["robotsTxt"])
            un = {u["host"]: u for u in rep["unavailableHosts"]}
            ok("and whether their pages then loaded",
               un.get(s5.host, {}).get("pagesLoaded") == 1 and un.get(dead, {}).get("pagesFailed") == 1
               and s4.host not in un, rep["unavailableHosts"])
            ok("the report says B is the hook's only, and departs from RFC 9309",
               "departing from RFC 9309" in rep["decision1"] and "report mode only" in rep["decision1"], rep["decision1"])
            # the other way, on the SAME hosts the hook has just loaded: the explicit checks stay strict
            ok("STRICT explicit robots_allowed() disallows a host whose robots.txt answered 5xx (hook loaded it first)",
               common.robots_allowed(s5.url("/x")) is False)
            ok("STRICT explicit robots_allowed() disallows a host whose robots.txt was unreachable",
               common.robots_allowed(f"http://{dead}/x") is False)
            ok("CONTROL explicit robots_allowed() allows a 4xx host", common.robots_allowed(s4.url("/x")) is True)
        with fresh(tmp), mode(None):
            ok("STRICT with the hook off, an explicit check alone still disallows the 5xx host",
               common.robots_allowed(s5.url("/x")) is False)
        with fresh(tmp), mode("report"):
            ok("(setup) an explicit check first disallows the 5xx host", common.robots_allowed(s5.url("/x")) is False)
            body, _ = common.fetch(s5.url("/page"), max_age_hours=None)
            ok("B, the hook: after an explicit check on the same host, the hook still allows it in report mode",
               body == b"<html>page</html>" and common.robots_report(elapsed_seconds=1, workers=1)["wouldBlock"]["total"] == 0)
    finally:
        s5.close(); s4.close()


# ---------- delays ----------

def arrivals(stub, prefix):
    return [r[1] for r in sorted(stub.log, key=lambda r: r[1]) if r[0].startswith(prefix)]


def test_delays(tmp: str) -> None:
    print("delays: report mode keeps today's delays exactly; enforce applies every host's")
    body = f"User-agent: *\nCrawl-delay: {DELAY:g}\n"
    x = pol.Stub("explicit", routes={"/robots.txt": robots(body), "/p": page()})
    y = pol.Stub("adapter-only", routes={"/robots.txt": robots(body), "/p": page()})
    z = pol.Stub("enforced", routes={"/robots.txt": robots(body), "/p": page()})
    try:
        with fresh(tmp), mode("report"):
            common.fetch(x.url("/p1"), max_age_hours=None)  # the adapter loads the host first ...
            ok("(setup) the adapter alone does not apply the delay", common._host_delay.get(x.host) is None)
            ok("... then an explicit call (an off-site camp host) applies it", common.robots_allowed(x.url("/p2")) is True
               and common._host_delay.get(x.host) == DELAY, common._host_delay)
            common.fetch(x.url("/p2"), max_age_hours=None)
            common.fetch(x.url("/p3"), max_age_hours=None)
            t = arrivals(x, "/p")
            ok("an explicitly checked host is spaced by its Crawl-delay in report mode",
               len(t) == 3 and t[2] - t[1] >= DELAY - pol.TOL, [round(b - a, 3) for a, b in zip(t, t[1:])])
            for i in range(3):
                common.fetch(y.url(f"/p{i}"), max_age_hours=None)
            t = arrivals(y, "/p")
            ok("a host only the adapter saw is NOT slowed in report mode (delay recorded, not applied)",
               len(t) == 3 and max(b - a for a, b in zip(t, t[1:])) < DELAY and common._robots_delay.get(y.host) == DELAY
               and common._host_delay.get(y.host) is None, [round(b - a, 3) for a, b in zip(t, t[1:])])
            rep = common.robots_report(elapsed_seconds=10, workers=1)
            ok("the Crawl-delay distribution counts both, applied vs recorded only",
               rep["crawlDelay"] == {"hosts": 2, "values": {"1": 2}, "applied": 1, "recordedOnly": 1}, rep["crawlDelay"])
            ok("a projected enforced run time is given", rep["projection"]["projectedEnforcedMinutes"] >= rep["projection"]["actualMinutes"],
               rep["projection"])
        with fresh(tmp), mode("enforce"):
            for i in range(2):
                common.fetch(z.url(f"/p{i}"), max_age_hours=None)
            t = arrivals(z, "/p")
            ok("enforce applies the host's Crawl-delay from its first page", len(t) == 2 and t[1] - t[0] >= DELAY - pol.TOL,
               [round(b - a, 3) for a, b in zip(t, t[1:])])
        rp = common.robotparser.RobotFileParser()
        text = "User-agent: *\nCrawl-delay: 2.5\n\nUser-agent: CollegeDashBot\nCrawl-delay: 0.5\n"
        rp.parse(text.splitlines())
        ok("a non-integer Crawl-delay is read, from the group naming us", common._crawl_delay_of(rp, text) == 0.5)
        rp2 = common.robotparser.RobotFileParser()
        rp2.parse("User-agent: *\nCrawl-delay: 2.5\n".splitlines())
        ok("... and from the '*' group", common._crawl_delay_of(rp2, "User-agent: *\nCrawl-delay: 2.5\n") == 2.5)
    finally:
        x.close(); y.close(); z.close()


# ---------- keep: a block never erases stored data ----------

BASE = "https://keep.invalid"
KEEP_RULES = "User-agent: *\nDisallow: /blocked/\n"


def blocking_fetch(pages: dict, errors: dict | None = None):
    """A fetch_text that runs the real adapter check (enforce, seeded rules for keep.invalid) and then serves `pages`.
    `errors` maps a URL to an ordinary FetchError message (the controls)."""
    def fetch_text(url, **_):
        if errors and url in errors:
            raise common.FetchError(errors[url])
        common._robots_check(url)
        if url not in pages:
            raise common.FetchError(f"HTTP 404 for {url}")
        return pages[url], {"url": url, "finalUrl": url, "status": 200, "fromCache": False, "contentType": "text/html"}
    return fetch_text


@contextlib.contextmanager
def keep_env(stored: dict, fetch_text):
    saved, logs = {}, []
    real = (common.fetch_text, common.save_source, common.load_source, common.log, adapters.get)
    common.fetch_text = fetch_text
    common.save_source = lambda slug, name, data, **kw: saved.setdefault(name, copy.deepcopy(data))
    common.load_source = lambda slug, name: copy.deepcopy(stored.get(name))
    common.log = logs.append
    try:
        with mode("enforce"):
            common.reset_robots_report()
            common.set_robots_txt("keep.invalid", KEEP_RULES)
            yield saved, logs
    finally:
        common.fetch_text, common.save_source, common.load_source, common.log, adapters.get = real
        common._robots.pop("keep.invalid", None)


def athletics_run(stored: dict, *, blocked: bool, bios: bool = True) -> tuple[dict, list[str], dict]:
    """athletics_site.collect over a stub adapter. The roster page lists no staff (so the coaches page is read), one
    player with a bio, and three history seasons. With blocked=True the bio, the 2025 roster, the 2024 schedule and the
    coaches page are under /blocked/ (disallowed); with blocked=False the same URLs fail with an ordinary FetchError."""
    B = BASE + ("/blocked" if blocked else "/gone")
    urls = {"roster": BASE + "/roster", "rosterSeason": lambda y: (B if y == 2025 else BASE) + f"/roster/{y}",
            "schedule": BASE + "/schedule", "scheduleSeason": lambda y: (B if y == 2024 else BASE) + f"/schedule/{y}",
            "coaches": B + "/coaches"}
    player = {"name": "A Player", "bioUrl": B + "/bio/a-player"}
    pages = {BASE + "/roster": "roster", BASE + "/schedule": "schedule"}
    for y in (2024, 2023):
        pages[BASE + f"/roster/{y}"] = f"roster{y}"
    for y in (2025, 2023):
        pages[BASE + f"/schedule/{y}"] = f"schedule{y}"
    ad = types.SimpleNamespace(
        urls=lambda program, registry: urls,
        parse_roster=lambda html, base: {"season": 2026 if html == "roster" else None,
                                         "players": [copy.deepcopy(player)] if html.startswith("roster") else [],
                                         "staff": []},
        parse_schedule=lambda html, base: {"season": 2026, "games": [{"date": f"{html[-4:]}-09-01", "result": "W"}]
                                           if html != "schedule" else []},
        parse_bio=lambda html: {"sections": {}})
    errors = {} if blocked else {u: f"HTTP 500 for {u}" for u in (B + "/roster/2025", B + "/schedule/2024", B + "/coaches",
                                                                 B + "/bio/a-player")}
    with keep_env(stored, blocking_fetch(pages, errors)) as (saved, logs):
        adapters.get = lambda platform: ad
        program = {"slug": "keep", "athletics": {"platform": "stub", "baseUrl": BASE, "sportPath": "/wsoc"}}
        with common.fetch_site("athletics"):
            athletics_site.collect(program, {"season": {"current": 2026}}, seasons_back=3, bios=bios, coach_bios=False)
        rep = common.robots_report(elapsed_seconds=1, workers=1)
    return saved.get("athletics") or {}, logs, rep


def test_keep_athletics() -> None:
    print("keep: athletics - bio/club by bioUrl, history years by season, coaches-page staff")
    stored = {"athletics": {"staffUrl": BASE + "/blocked/coaches", "data": {
        "roster": {"players": [{"name": "A Player", "bioUrl": BASE + "/blocked/bio/a-player",
                                "bio": {"sections": {"Club": "Stored FC"}}, "club": "Stored FC"}]},
        "staff": [{"name": "Stored Coach", "title": "Head Coach"}],
        "rosterHistory": {"2025": [{"name": "Stored 2025 Player"}]},
        "scheduleHistory": {"2024": [{"date": "2024-09-01", "result": "W", "opponent": "Stored"}]},
        "headCoachBio": None}}}
    data, logs, rep = athletics_run(stored, blocked=True)
    p = (data.get("roster") or {}).get("players") or [{}]
    ok("FIX a blocked bio keeps the stored bio and club (matched by bioUrl)",
       p[0].get("club") == "Stored FC" and p[0].get("bio") == {"sections": {"Club": "Stored FC"}}, p[0])
    ok("FIX a blocked past-season roster keeps the stored year",
       (data.get("rosterHistory") or {}).get("2025") == [{"name": "Stored 2025 Player"}], sorted(data.get("rosterHistory") or {}))
    ok("FIX a blocked past-season schedule keeps the stored year",
       (data.get("scheduleHistory") or {}).get("2024") == stored["athletics"]["data"]["scheduleHistory"]["2024"],
       sorted(data.get("scheduleHistory") or {}))
    ok("FIX a blocked coaches page keeps the stored staff", data.get("staff") == [{"name": "Stored Coach", "title": "Head Coach"}],
       data.get("staff"))
    ok("CONTROL the unblocked years are fetched as usual",
       "2024" in (data.get("rosterHistory") or {}) and "2025" in (data.get("scheduleHistory") or {}))
    wb = rep["blocked"]
    ok("each block is counted under its call site",
       wb["bySite"] == {"athletics.bio": 1, "athletics.coachesPage": 1, "athletics.historyRoster": 1,
                        "athletics.historySchedule": 1}, wb["bySite"])
    data, logs, rep = athletics_run({"athletics": copy.deepcopy(stored["athletics"])}, blocked=False)
    p = (data.get("roster") or {}).get("players") or [{}]
    ok("CONTROL an ordinary fetch error still behaves as before: bio and club empty, the year absent, no staff",
       p[0].get("club") == "" and p[0].get("bio") == {} and "2025" not in (data.get("rosterHistory") or {})
       and "2024" not in (data.get("scheduleHistory") or {}) and data.get("staff") == [], data)
    data, _, _ = athletics_run({}, blocked=True)
    ok("CONTROL with nothing stored, a block stores nothing for those parts (no invented data)",
       "2025" not in (data.get("rosterHistory") or {}) and data.get("staff") == []
       and ((data.get("roster") or {}).get("players") or [{}])[0].get("club") == "", data)


def test_keep_camps() -> None:
    print("keep: camps - the camp page's stored camps by campsUrl")
    url = BASE + "/blocked/camps"
    stored_camps = [{"name": "Stored ID Camp", "startDate": "2026-11-01"}]
    stored = {"camps": {"data": {"campsUrl": url, "camps": stored_camps, "pageTitle": "Stored title"}}}
    program = {"slug": "keep", "athletics": {"platform": "auto", "baseUrl": BASE, "sportPath": "/wsoc", "campsUrl": url}}
    with keep_env(stored, blocking_fetch({})) as (saved, logs):
        camps.collect(copy.deepcopy(program), {})
        rep = common.robots_report(elapsed_seconds=1, workers=1)
    data = saved.get("camps") or {}
    ok("FIX a blocked camp page keeps the camps stored for the same campsUrl", data.get("camps") == stored_camps,
       data.get("camps"))
    ok("... marked robotsBlocked", data.get("robotsBlocked") is True and data.get("campsUrl") == url,
       {k: data.get(k) for k in ("robotsBlocked", "campsUrl")})
    ok("the block is counted as camps.page", rep["blocked"]["bySite"] == {"camps.page": 1}, rep["blocked"]["bySite"])
    other = {"camps": {"data": {"campsUrl": BASE + "/old-camps", "camps": stored_camps}}}
    with keep_env(other, blocking_fetch({})) as (saved, _):
        camps.collect(copy.deepcopy(program), {})
    ok("CONTROL camps stored for a DIFFERENT campsUrl are not carried over", (saved.get("camps") or {}).get("camps") == [],
       (saved.get("camps") or {}).get("camps"))


def test_keep_collector() -> None:
    print("keep: a collector with no catch (news) is skipped, reason robots, and its source is not rewritten")
    ad = types.SimpleNamespace(urls=lambda program, registry: {"news": BASE + "/blocked/news"},
                               parse_news=lambda html, base: [])
    program = {"slug": "keep", "athletics": {"platform": "stub", "baseUrl": BASE, "sportPath": "/wsoc"}}
    with keep_env({"news": {"data": {"items": [{"url": "u", "title": "Stored"}]}}}, blocking_fetch({})) as (saved, logs):
        adapters.get = lambda platform: ad
        r, entry = collegedash.collect_one("news", program, {})
        rep = common.robots_report(elapsed_seconds=1, workers=1)
    ok("FIX the collector's outcome is skipped, reason robots: <call site>",
       r["outcome"] == "skipped" and r["error"] == "robots: news.page", r)
    ok("... recorded as ok + skipped in refresh-state, not failed", entry.get("ok") is True and entry.get("skipped") == "robots: news.page",
       entry)
    ok("... and its stored source is not rewritten", "news" not in saved, sorted(saved))
    ok("the block is counted under news.page", rep["blocked"]["bySite"] == {"news.page": 1}, rep["blocked"]["bySite"])


# ---------- time budget ----------

def test_budget() -> None:
    print("budget: no new program after the time budget; the rest are skipped, refresh-state untouched")
    clock = {"t": 1000.0}
    ran, recorded, state = [], {}, {}
    plan = [({"slug": s}, ["news", "camps"]) for s in ("p1", "p2", "p3")]

    def fake_collect_one(name, program, registry, **kw):
        ran.append((program["slug"], name))
        clock["t"] += 50  # each collector takes 50 s of the fake clock
        return {"program": program["slug"], "collector": name, "outcome": "ok", "error": ""}, {"ok": True}

    real = (collegedash._clock, collegedash.collect_one, collegedash.record_outcomes, common.update_refresh_state)
    collegedash._clock = lambda: clock["t"]
    collegedash.collect_one = fake_collect_one
    collegedash.record_outcomes = lambda slug, entries: recorded.update(entries) or True
    common.update_refresh_state = lambda key, info: state.__setitem__(key, info)
    gha = os.environ.pop("GITHUB_ACTIONS", None)  # keep the fake run out of a real step summary in CI
    try:
        results = collegedash.collect_plan(plan, {}, bios=False, workers=1, deadline=1000.0 + 150)
        code = collegedash.report_refresh(results, threshold=0.05, mode="daily", time_budget=1.5)
    finally:
        collegedash._clock, collegedash.collect_one, collegedash.record_outcomes, common.update_refresh_state = real
        if gha is not None:
            os.environ["GITHUB_ACTIONS"] = gha
    ok("programs started before the deadline run all their collectors (p1 at 0 s, p2 at 100 s; the budget is 150 s)",
       ran == [("p1", "news"), ("p1", "camps"), ("p2", "news"), ("p2", "camps")], ran)
    skipped = [r for r in results if r["outcome"] == "skipped"]
    ok("FIX the program not started is skipped with reason 'time budget', never failed",
       [(r["program"], r["collector"], r["error"]) for r in skipped] == [("p3", "news", "time budget"), ("p3", "camps", "time budget")]
       and not any(r["outcome"] == "failed" for r in results), results)
    ok("its refresh-state entries are left as they were", not any(k.startswith("p3.") for k in recorded), sorted(recorded))
    lr = state.get("lastRun") or {}
    ok("report_refresh names them in lastRun, and the run does not fail on them",
       code == 0 and lr.get("timeBudget") == {"minutes": 1.5, "programsNotStarted": 1, "slugs": ["p3"]} and lr.get("failed") == 0,
       lr.get("timeBudget"))
    results2 = collegedash.collect_plan([({"slug": "q"}, [])], {}, bios=False, workers=1, deadline=None)
    ok("CONTROL no budget: nothing is skipped for time", results2 == [], results2)


def test_cli() -> None:
    print("cli: an unknown COLLEGEDASH_ROBOTS value refuses the run; the default is off")
    with mode("enforced"):
        code = collegedash.cmd_refresh(argparse.Namespace(time_budget_minutes=None))
        ok("robots_mode() never guesses an unknown value", common.robots_mode() == "off")
    ok("an unknown mode exits 2 before anything runs", code == 2, code)
    with mode(None):
        ok("unset: off", common.robots_mode() == "off")
    src = open(os.path.join(ROOT, "collegedash.py"), encoding="utf-8").read()
    ok("the budget flag's default is read from COLLEGEDASH_TIME_BUDGET_MINUTES",
       'os.environ.get("COLLEGEDASH_TIME_BUDGET_MINUTES")' in src and "--time-budget-minutes" in src)


def test_workflow() -> None:
    print("workflow: report mode, the budget, the timeouts, and the commit step after a failed step")
    text = open(os.path.join(ROOT, ".github", "workflows", "refresh.yml"), encoding="utf-8").read().replace("\r\n", "\n")
    job = text[text.index("\n  refresh:\n"):]
    head = job[:job.index("\n    steps:\n")]

    def step(name: str) -> str:
        i = job.index(f"      - name: {name}\n")
        j = job.find("\n      - ", i + 1)
        return job[i:j if j > 0 else None]

    refresh, commit = step("Refresh data"), step("Commit changed data")
    ok("the job has timeout-minutes 350", "\n    timeout-minutes: 350" in head, head[-200:])
    ok("the collector step has timeout-minutes 300", "\n        timeout-minutes: 300\n" in refresh)
    ok("the collector step runs robots.txt in report mode", "\n          COLLEGEDASH_ROBOTS: report\n" in refresh)
    ok("... with a 270-minute budget", '\n          COLLEGEDASH_TIME_BUDGET_MINUTES: "270"\n' in refresh)
    ok("the collector step continues on error, so a non-zero exit (or a kill) is not the end of the job",
       "\n        continue-on-error: true\n" in refresh)
    ok("the commit step comes after it and is `if: always()`",
       job.index("- name: Commit changed data") > job.index("- name: Refresh data") and "\n        if: always()\n" in commit)
    ok("the budget leaves the commit step about 50 minutes inside the job limit", 350 - 300 >= 45 and 300 - 270 >= 20)


def main() -> int:
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose
    with tempfile.TemporaryDirectory() as tmp:
        test_adapter(tmp)
        test_decision_b(tmp)
        test_delays(tmp)
    test_keep_athletics()
    test_keep_camps()
    test_keep_collector()
    test_budget()
    test_cli()
    test_workflow()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
