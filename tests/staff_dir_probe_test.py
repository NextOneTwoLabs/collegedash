"""The staff-directory probe (issue #387 step 1): one name-free line, at most one probe per program per run.

    python tests/staff_dir_probe_test.py            # everything below, offline
    python tests/staff_dir_probe_test.py --verbose  # print every check

Offline, and stricter than a patched fetch function: requests' own transport (HTTPAdapter.send, which the polite
adapter in collect.common hands every request and redirect hop to) is replaced by a table of synthetic pages, and
every URL that reaches it is recorded. So the real fetch path runs - robots hook, per-host gate, guard - and "no
request to that host" means nothing, not even a robots.txt, reached the transport for it. No socket is opened; the
network guard would fail the run if one were. Every page is built here from placeholder names, example.test hosts
and 555-555-01xx numbers.

What is pinned (Huatuo's review and approval on #387, and the TPM's brief):
  * the trigger: players > 0, final staff empty, and a run that fetches the head coach's bio (coach_bios) - silent on a
    daily-style call, with roster staff, with coaches-page staff and with kept staff;
  * C1: robots_allowed() refuses -> robots=0 and no request, in every COLLEGEDASH_ROBOTS mode; a 5xx robots.txt counts
    as a refusal;
  * the build note: a redirect to another host records NO request to that host (not even its robots.txt), in every
    mode; one same-host hop to a directory path is allowed and robots-checked again;
  * one probe per program per run;
  * the line's vocabulary, the label classes, the header allowlist, the caps as literal values (12 headers, 400
    characters) with fixtures that go over them, and a mutation that must fail the leak check;
  * failure isolation: a raising probe never fails the collection; nothing from the directory is stored or cached.
Each pinned behaviour carries a control that shows the check can fail (the same fixture with the guard removed).
"""
from __future__ import annotations

import argparse
import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.pop("COLLEGEDASH_OFFLINE", None)  # the probe refuses to run offline; the transport below is the fake

import requests  # noqa: E402
from requests.structures import CaseInsensitiveDict  # noqa: E402

from collect import athletics_site, common, staff_dir_probe as sdp  # noqa: E402
import camps_check  # noqa: E402

os.environ.pop("COLLEGEDASH_OFFLINE", None)  # camps_check sets it on import; Env below keeps it off while probing

HOST = "athletics.example.test"
OTHER = "other-host.example.test"
BASE = f"https://{HOST}"
SPORT = "/sports/womens-soccer"
ROSTER, COACHES, SCHEDULE = BASE + SPORT + "/roster", BASE + SPORT + "/coaches", BASE + SPORT + "/schedule"
DIRECTORY = BASE + "/staff-directory"
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

# Made-up people and contact details that must never reach the line.
NAMES = ("Placeholder Coachperson", "Sample Assistantperson", "Dummy Mensperson", "Example Adminperson")
SLUGS = ("placeholder-coachperson", "sample-assistantperson", "dummy-mensperson", "example-adminperson")
EMAILS = ("placeholder.coach@example.test", "sample.assistant@example.test", "dummy.mens@example.test")
PHONES = ("555-555-0199", "555-555-0198", "555-555-0197")
TITLE = "Head Women's Soccer Coach"


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:600]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


# ---------- synthetic pages ----------

def page(*parts: str) -> str:
    return "<html><head><title>Placeholder Athletics</title></head><body>" + "".join(parts) + "</body></html>"


def player_table(n: int = 3) -> str:
    rows = "".join(f'<tr><td>{i}</td><th scope="row"><a href="{SPORT}/roster/player-{i}/{900 + i}">Player {i}</a></th>'
                   f"<td>D</td><td>5'6\"</td><td>So.</td><td>Town, ST / High School</td></tr>" for i in range(1, n + 1))
    return ("<table><thead><tr><th>#</th><th>Name</th><th>Pos.</th><th>Ht.</th><th>Year</th>"
            "<th>Hometown / High School</th></tr></thead><tbody>" + rows + "</tbody></table>")


def staff_table() -> str:
    return ("<table><tr><th>Coaching Staff</th></tr><tr><th>Name</th><th>Title</th></tr>"
            f'<tr><td><a href="{SPORT}/roster/coaches/{SLUGS[0]}/77">{NAMES[0]}</a></td><td>Head Coach</td></tr></table>')


def roster_page(link: str | None = "/staff-directory", *extra: str) -> str:
    nav = f'<nav><a href="{link}">Staff Directory</a></nav>' if link else ""
    return page(nav, player_table(), *extra)


def person_row(i: int, title: str, bio: bool = True) -> str:
    name = f'<a href="/staff-directory/{SLUGS[i]}/{20 + i}">{NAMES[i]}</a>' if bio else NAMES[i]
    return (f"<tr><td>{name}</td><td>{title}</td><td>{PHONES[i % 3]}</td>"
            f'<td><a href="mailto:{EMAILS[i % 3]}">{EMAILS[i % 3]}</a></td></tr>')


def directory_tr_group() -> str:
    """The Sidearm-style directory: one table, a header row, full-width group rows per department."""
    return page("<table><thead><tr><th>Name</th><th>Title</th><th>Phone</th><th>Email</th></tr></thead><tbody>"
                '<tr><th colspan="4">Athletics Administration</th></tr>' + person_row(3, "Director of Athletics")
                + '<tr><th colspan="4">Women’s Soccer</th></tr>' + person_row(0, TITLE)
                + person_row(1, "Assistant Coach", bio=False)
                + '<tr><th colspan="4">Men\'s Soccer</th></tr>' + person_row(2, "Head Men's Soccer Coach")
                + "</tbody></table>")


HEAD = "<tr><th>Name</th><th>Title</th><th>Phone</th><th>Email</th></tr>"


def directory_marked(marker: str) -> str:
    """One section per sport, marked the given way, each with its own table."""
    def section(label: str, rows: str) -> str:
        table = f"<table>{HEAD}{rows}</table>"
        if marker == "caption":
            return f"<table><caption>{label}</caption>{HEAD}{rows}</table>"
        if marker == "div-heading":
            return f'<div class="staff-group__heading">{label}</div>{table}'
        return f"<{marker}>{label}</{marker}>{table}"
    return page(section("Administration", person_row(3, "Director of Athletics")),
                section("Women's Soccer Coaches", person_row(0, TITLE) + person_row(1, "Assistant Coach")),
                section("Men's Soccer", person_row(2, "Head Men's Soccer Coach")))


# ---------- the fake transport ----------

class Net:
    """Pages by URL (exact, query included), 3xx by URL, robots.txt by host; every URL sent is recorded."""

    def __init__(self, pages=None, redirects=None, robots=None):
        self.pages = dict(pages or {})
        self.redirects = dict(redirects or {})
        self.robots = dict(robots or {})
        self.sent: list[str] = []

    def send(self, adapter, request, **kw):
        url = request.url
        self.sent.append(url)
        host = requests.utils.urlparse(url).netloc
        if url.endswith("/robots.txt") and host in self.robots:
            status, body = self.robots[host]
            return self._resp(request, status, body)
        if url in self.redirects:
            return self._resp(request, 301, "", location=self.redirects[url])
        if url in self.pages:
            return self._resp(request, 200, self.pages[url])
        return self._resp(request, 404, "not found")

    @staticmethod
    def _resp(request, status, body, location=None):
        r = requests.Response()
        r.status_code, r.url, r.request, r.encoding = status, request.url, request, "utf-8"
        r._content, r._content_consumed = body.encode("utf-8"), True
        r.headers = CaseInsensitiveDict({"Content-Type": "text/html; charset=utf-8"})
        if location:
            r.headers["Location"] = location
        return r

    def hosts(self) -> set[str]:
        return {requests.utils.urlparse(u).netloc for u in self.sent}


class Env:
    """Installs a Net as the transport, a robots mode and fresh robots/probe state; restores everything."""

    def __init__(self, net: Net, *, mode: str = "off", seed: dict | None = None):
        self.net, self.mode = net, mode
        self.seed = {HOST: None} if seed is None else seed  # host -> robots.txt text (None = allow all)

    def __enter__(self):
        self.saved = (requests.adapters.HTTPAdapter.send, os.environ.get("COLLEGEDASH_ROBOTS"),
                      common.MIN_GAP_SECONDS, common.JITTER_SECONDS)
        os.environ.pop("COLLEGEDASH_OFFLINE", None)
        net = self.net
        requests.adapters.HTTPAdapter.send = lambda adapter, request, **kw: net.send(adapter, request, **kw)
        os.environ["COLLEGEDASH_ROBOTS"] = self.mode
        common.MIN_GAP_SECONDS = common.JITTER_SECONDS = 0  # no real waiting between fake requests
        reset_robots()
        # As `refresh` does before any fetch. Without it the #101 hook's first report-mode request takes _robots_lock
        # and then calls reset_robots_report(), which takes the same (non-reentrant) lock: a pre-existing self-deadlock
        # that refresh never reaches because it resets first.
        common.reset_robots_report()
        for host, text in self.seed.items():
            common.set_robots_txt(host, text)
        sdp._probed.clear()
        return net

    def __exit__(self, *exc):
        send, mode, gap, jitter = self.saved
        requests.adapters.HTTPAdapter.send = send
        if mode is None:
            os.environ.pop("COLLEGEDASH_ROBOTS", None)
        else:
            os.environ["COLLEGEDASH_ROBOTS"] = mode
        common.MIN_GAP_SECONDS, common.JITTER_SECONDS = gap, jitter
        reset_robots()
        sdp._probed.clear()
        return False


def reset_robots():
    with common._robots_lock:
        common._robots.clear()
        common._robots_state.clear()
        common._robots_delay.clear()
        common._explicit_hosts.clear()
    common._host_delay.clear()


def probe(roster_html: str, net: Net, **env) -> str:
    with Env(net, **env):
        return sdp.probe(roster_html, BASE)


def leaks(line: str) -> list[str]:
    low = line.lower()
    found = [x for x in NAMES + SLUGS + EMAILS + PHONES + (TITLE,) if x.lower() in low]
    found += [w for w in ("placeholder", "sample", "dummy", "example", "@", "mailto", "athletics", "assistant",
                          "administration", "women", "men's", "/staff", OTHER) if w.lower() in low]
    e, p = camps_check.contact_hits(line)
    return found + e + p


# ---------- the line ----------

def test_line_shape_and_counts():
    line = probe(roster_page(), Net(pages={DIRECTORY: directory_tr_group()}))
    want = ("  staff directory probe: robots=1 dir=ok status=200 tables=1 marker=tr-group wsoc=1 soccer=0 msoc=1 "
            "combined=0 rows=2 headCoachRows=1 bioLinks=1 headers=[name, title, phone, email]")
    ok("tr-group directory: the exact line", line == want, line)
    for marker in ("caption", "h2", "h3", "h4", "div-heading"):
        line = probe(roster_page(), Net(pages={DIRECTORY: directory_marked(marker)}))
        ok(f"{marker} directory: marker={marker}, one women's section, 2 rows, 1 head coach, 2 bio links",
           f"marker={marker} wsoc=1 soccer=0 msoc=1 combined=0 rows=2 headCoachRows=1 bioLinks=2 "
           "headers=[name, title, phone, email]" in line, line)
    line = probe(roster_page(), Net(pages={DIRECTORY: page("<p>Contact the athletics office.</p>")}))
    ok("a page with no sections: marker=none, nothing counted",
       line.endswith("tables=0 marker=none wsoc=0 soccer=0 msoc=0 combined=0 rows=0 headCoachRows=0 bioLinks=0 headers=[]"), line)
    two = directory_tr_group().replace("Athletics Administration", "Women's Soccer")
    line = probe(roster_page(), Net(pages={DIRECTORY: two}))
    ok("two women's sections: counted, but no section is read (ambiguous)",
       "wsoc=2" in line and line.endswith("rows=0 headCoachRows=0 bioLinks=0 headers=[]"), line)


def test_label_classes():
    cases = {
        "Women's Soccer": "wsoc", "WOMEN’S SOCCER": "wsoc", "Womens Soccer": "wsoc", "W. Soccer": "wsoc",
        "WSOC": "wsoc", "Soccer (W)": "wsoc", "Soccer - Women": "wsoc", "Soccer Women": "wsoc",
        "Women's Soccer Coaches": "wsoc", "Women's Soccer Coaching Staff": "wsoc", "Women's Soccer Staff": "wsoc",
        "Soccer": "soccer", "Soccer Staff": "soccer",
        "Men's Soccer": "msoc", "Mens Soccer": "msoc", "M. Soccer": "msoc", "MSOC": "msoc", "Soccer (M)": "msoc",
        "Men's & Women's Soccer": "combined", "Men's and Women's Soccer Coaches": "combined", "Soccer (M/W)": "combined",
        # near misses: never a substring match
        "Women's Soccer Camps": None, "Women's Soccer Schedule": None, "Women's Basketball": None,
        "Head Women's Soccer Coach": None, "Soccer Operations": None, "Placeholder Coachperson": None,
        "Women's Soccer " + "x" * 80: None,
    }
    for text, want in cases.items():
        got = sdp.label_class(text)
        ok(f"label {text[:40]!r} -> {want}", got == want, got)


def test_header_allowlist():
    for text, want in (("Name", "name"), ("TITLE", "title"), (" Position ", "position"), ("E-mail", "<x>"),
                       ("Email", "email"), ("Email:", "email"), ("Phone", "phone"), ("Bio", "bio"), ("Photo", "photo"),
                       ("Department", "department"), ("Sport", "sport"), ("Email Address", "<x>"),
                       ("Title/Position", "<x>"), ("Titles", "<x>"), ("", "<x>"), (NAMES[0], "<x>"),
                       (EMAILS[0], "<x>"), (PHONES[0], "<x>")):
        got = sdp.header_word(text)
        ok(f"header {text!r} -> {want}", got == want, got)


def test_no_leak_and_contact_scanner():
    planted = directory_tr_group().replace("<th>Phone</th>", f"<th>{NAMES[0]}</th>")  # a name even as a header
    for marker, html in [("tr-group", planted)] + [(m, directory_marked(m)) for m in ("caption", "h2", "div-heading")]:
        line = probe(roster_page(), Net(pages={DIRECTORY: html}))
        ok(f"{marker}: the fixture really carries every planted name, e-mail, phone and title",
           all(x in html for x in (NAMES[0], NAMES[2], EMAILS[0], PHONES[0], TITLE.replace("'", "'"))), marker)
        ok(f"{marker}: no name, slug, e-mail, phone, title, label or path in the line", not leaks(line), (leaks(line), line))
        e, p = camps_check.contact_hits(line)
        ok(f"{marker}: contact scanner finds nothing", not e and not p, e + p)


def test_mutation_unmasked_header_fails():
    real = sdp.header_word
    sdp.header_word = lambda text: text  # a broken allowlist that lets header text through
    try:
        planted = directory_tr_group().replace("<th>Phone</th>", f"<th>{NAMES[0]}</th>")
        line = probe(roster_page(), Net(pages={DIRECTORY: planted}))
    finally:
        sdp.header_word = real
    ok("mutation: an unmasked header is caught by the leak check", bool(leaks(line)), line)
    ok("allowlist restored", sdp.header_word is real)


def _uncapped(html: str, *, headers: bool = True, length: bool = True) -> str:
    real = (sdp.PROBE_MAX_HEADERS, sdp.PROBE_MAX_LEN)
    if headers:
        sdp.PROBE_MAX_HEADERS = 10 ** 9
    if length:
        sdp.PROBE_MAX_LEN = 10 ** 9
    try:
        return probe(roster_page(), Net(pages={DIRECTORY: html}))
    finally:
        sdp.PROBE_MAX_HEADERS, sdp.PROBE_MAX_LEN = real


def _headers(line: str) -> list[str]:
    inner = line.split("headers=[", 1)[1].split("]", 1)[0]
    return inner.split(", ") if inner else []


def wide_directory(n: int) -> str:
    words = (list(sdp.HEADER_WORDS) * 10)[:n]
    head = "<tr>" + "".join(f"<th>{w.title()}</th>" for w in words) + "</tr>"
    row = "<tr>" + "".join(f"<td>{TITLE if w == 'title' else 'x'}</td>" for w in words) + "</tr>"
    return page(f"<table><caption>Women's Soccer</caption>{head}{row}</table>")


def test_caps_are_12_headers_and_400_characters():
    # The literal values, not the constants: raising either must fail here.
    ok("PROBE_MAX_HEADERS is 12", sdp.PROBE_MAX_HEADERS == 12, sdp.PROBE_MAX_HEADERS)
    ok("PROBE_MAX_LEN is 400", sdp.PROBE_MAX_LEN == 400, sdp.PROBE_MAX_LEN)
    # header cap alone: 20 headers, under 400 characters uncapped
    free = _uncapped(wide_directory(20))
    ok("header fixture has 20 headers uncapped", len(_headers(free)) == 20, free)
    ok("header fixture stays under 400 characters uncapped", len(free) < 400, len(free))
    line = probe(roster_page(), Net(pages={DIRECTORY: wide_directory(20)}))
    ok("header cap: exactly 12 headers logged", len(_headers(line)) == 12, line)
    ok("header cap: the other 8 are counted, not logged", line.endswith(" +8 more"), line)
    # length cap alone: 40 headers with the header cap lifted go over 400 characters
    free = _uncapped(wide_directory(40))
    ok("length fixture goes over 400 characters uncapped", len(free) > 400, len(free))
    line = _uncapped(wide_directory(40), length=False)
    ok("length cap: at most 400 characters", len(line) <= 400, len(line))
    ok("length cap: headers dropped are counted", " more" in line, line)
    ok("length cap: what is kept is whole headers", all(h in sdp.HEADER_WORDS or h == "<x>" for h in _headers(line)), line)


# ---------- C1: robots, asked first ----------

def test_robots_refusal_sends_nothing():
    for mode in ("off", "report", "enforce"):
        net = Net(pages={DIRECTORY: directory_tr_group()})
        line = probe(roster_page(), net, mode=mode, seed={HOST: "User-agent: *\nDisallow: /staff-directory\n"})
        ok(f"{mode}: robots refuses -> robots=0", line == "  staff directory probe: robots=0 dir=skipped", line)
        ok(f"{mode}: ... and no request at all", net.sent == [], net.sent)
    # the strict check: a robots.txt answering 5xx is a refusal (the #101 hook alone would allow and count it)
    net = Net(pages={DIRECTORY: directory_tr_group()}, robots={HOST: (503, "")})
    line = probe(roster_page(), net, mode="report", seed={})
    ok("5xx robots.txt -> robots=0", line.startswith("  staff directory probe: robots=0"), line)
    ok("... and only robots.txt was requested", net.sent == [BASE + "/robots.txt"], net.sent)
    # control: the same refused fixture with the check removed does reach the page
    real = common.robots_allowed
    common.robots_allowed = lambda url: True
    try:
        net = Net(pages={DIRECTORY: directory_tr_group()})
        probe(roster_page(), net, mode="off", seed={HOST: "User-agent: *\nDisallow: /staff-directory\n"})
    finally:
        common.robots_allowed = real
    ok("control: without the robots check the directory would be requested", net.sent == [DIRECTORY], net.sent)


# ---------- the build note: redirects ----------

def test_offhost_redirect_requests_nothing_from_the_other_host():
    target = f"https://{OTHER}/staff-directory"
    for mode in ("off", "report", "enforce"):
        net = Net(pages={target: directory_tr_group()}, redirects={DIRECTORY: target})
        line = probe(roster_page(), net, mode=mode)
        ok(f"{mode}: off-host redirect -> dir=offhost", line == "  staff directory probe: robots=1 dir=offhost status=301", line)
        ok(f"{mode}: ... NO request to the other host, not even its robots.txt", OTHER not in net.hosts(), net.sent)
        ok(f"{mode}: ... one request in all, to the roster host's directory", net.sent == [DIRECTORY], net.sent)
    net = Net(pages={target: directory_tr_group()}, redirects={DIRECTORY: "//" + OTHER + "/staff"})
    line = probe(roster_page(), net)
    ok("a scheme-relative Location to another host is off-host too", "dir=offhost" in line and OTHER not in net.hosts(), net.sent)
    # control: the ordinary redirect-following fetch, through the same fake transport, DOES reach the other host -
    # so the transport would have recorded a request there had the probe followed the redirect.
    net = Net(pages={target: directory_tr_group()}, redirects={DIRECTORY: target})
    with Env(net):
        common.fetch(DIRECTORY, max_age_hours=None)
        common.forget_cached(DIRECTORY)
    ok("control: a redirect-following fetch would have requested the other host", OTHER in net.hosts(), net.sent)


def test_same_host_hop():
    staff = BASE + "/staff"
    net = Net(pages={DIRECTORY: directory_tr_group()}, redirects={staff: DIRECTORY})
    line = probe(roster_page("/staff"), net)
    ok("/staff -> /staff-directory on the same host: followed once, dir=ok", "dir=ok status=200" in line, line)
    ok("... two requests, both on the roster host", net.sent == [staff, DIRECTORY], net.sent)
    net = Net(pages={DIRECTORY: directory_tr_group()}, redirects={staff: f"https://www.{HOST}/staff-directory"})
    probe(roster_page("/staff"), net, seed={HOST: None, "www." + HOST: None})
    ok("a www. hop counts as the same host", net.sent == [staff, f"https://www.{HOST}/staff-directory"], net.sent)
    net = Net(pages={DIRECTORY: directory_tr_group()}, redirects={staff: DIRECTORY})
    line = probe(roster_page("/staff"), net, seed={HOST: "User-agent: *\nDisallow: /staff-directory\n"})
    ok("the hop is robots-checked again: refused -> robots=0", line.startswith("  staff directory probe: robots=0 dir=skipped"), line)
    ok("... and the hop is not requested", net.sent == [staff], net.sent)
    net = Net(redirects={staff: BASE + "/about-placeholder"})
    line = probe(roster_page("/staff"), net)
    ok("a same-host hop off the directory paths -> dir=offpath, not requested", "dir=offpath" in line and net.sent == [staff],
       (line, net.sent))
    net = Net(redirects={staff: DIRECTORY, DIRECTORY: staff})
    line = probe(roster_page("/staff"), net)
    ok("a second redirect -> dir=redirects, nothing after it", "dir=redirects" in line and net.sent == [staff, DIRECTORY],
       (line, net.sent))


def test_which_link_is_probed():
    for link, why in ((None, "no link"), (f"https://{OTHER}/staff-directory", "a link to another host"),
                      (f"/staff-directory/{SLUGS[0]}/12", "a directory entry, not the directory"),
                      ("/staff-directory-old", "another path"), ("mailto:" + EMAILS[0], "a mailto link")):
        net = Net(pages={DIRECTORY: directory_tr_group()})
        line = probe(roster_page(link), net)
        ok(f"{why}: dir=none and no request", line == "  staff directory probe: robots=- dir=none" and net.sent == [],
           (line, net.sent))
    net = Net(pages={BASE + "/Staff-Directory/": directory_tr_group()})
    line = probe(roster_page("/Staff-Directory/?sport=placeholder#top"), net)
    ok("case and trailing slash allowed; query and fragment dropped", net.sent == [BASE + "/Staff-Directory/"], net.sent)
    net = Net()
    line = probe(roster_page(), net)
    ok("a 404 directory -> dir=error status=404", line == "  staff directory probe: robots=1 dir=error status=404", line)


# ---------- through athletics_site.collect: trigger, one per run, isolation ----------

SAVED: list = []


def run_collect(net: Net, pages: dict, *, coach_bios=True, bios=False, stored: dict | None = None,
                robots: tuple = (), slug: str = "fixture", fresh: bool = True):
    logs, fetched = [], []
    pages = {SCHEDULE: page(), **pages}

    def fetch_text(url, **kw):
        fetched.append(url)
        if url in robots:
            raise common.RobotsDisallowed(url, "athletics.coachesPage")
        if url not in pages:
            raise common.FetchError(f"HTTP 404 for {url}")
        return pages[url], {"url": url, "status": 200, "finalUrl": url, "fromCache": False}

    program = {"slug": slug, "athletics": {"platform": "sidearm", "baseUrl": BASE, "sportPath": SPORT}}
    real = (common.fetch_text, common.save_source, common.log, common.load_source, athletics_site._coach_bio_for_run)
    common.fetch_text, common.log = fetch_text, logs.append
    SAVED.clear()
    common.save_source = lambda slug, name, data, **k: SAVED.append(copy.deepcopy(data))
    common.load_source = lambda slug, name: copy.deepcopy(stored) if stored else None
    athletics_site._coach_bio_for_run = lambda *a, **k: None  # the head-coach bio is another collector's business
    err = None
    env = Env(net)
    try:
        env.__enter__() if fresh else None
        athletics_site.collect(program, REGISTRY, seasons_back=0, bios=bios, coach_bios=coach_bios)
    except Exception as e:
        err = e
    finally:
        if fresh:
            env.__exit__()
        common.fetch_text, common.save_source, common.log, common.load_source, athletics_site._coach_bio_for_run = real
    return [l for l in logs if "staff directory probe" in l or "staff-directory probe" in l], fetched, err


def test_trigger():
    roster = {ROSTER: roster_page()}
    net = Net(pages={DIRECTORY: directory_tr_group()})
    lines, _, err = run_collect(net, roster, coach_bios=True)
    ok("fires: players, no staff, coaches 404, coach_bios=True", len(lines) == 1 and "dir=ok" in lines[0] and err is None,
       (lines, err))
    ok("... one request, the directory", net.sent == [DIRECTORY], net.sent)
    for kw, why in (({"coach_bios": False, "bios": False}, "a daily-style call (no bios, no coach bios)"),
                    ({"coach_bios": None, "bios": False}, "coach_bios=None following bios=False"),
                    ({"coach_bios": False, "bios": True}, "coach_bios=False with player bios on")):
        net = Net(pages={DIRECTORY: directory_tr_group()})
        lines, _, err = run_collect(net, roster, **kw)
        ok(f"silent: {why}", lines == [] and net.sent == [] and err is None, (lines, net.sent, err))
    net = Net(pages={DIRECTORY: directory_tr_group()})
    lines, _, err = run_collect(net, roster, coach_bios=None, bios=True)
    ok("fires: coach_bios=None following bios=True (as the head-coach bio does)", len(lines) == 1, (lines, err))
    net = Net(pages={DIRECTORY: directory_tr_group()})
    lines, _, err = run_collect(net, {ROSTER: roster_page("/staff-directory", staff_table())})
    ok("silent: the roster page has staff", lines == [] and net.sent == [] and err is None, (lines, net.sent, err))
    net = Net(pages={DIRECTORY: directory_tr_group()})
    lines, _, err = run_collect(net, {**roster, COACHES: page(staff_table())})
    ok("silent: the coaches page has staff", lines == [] and net.sent == [] and err is None, (lines, net.sent, err))
    kept = {"data": {"staff": [{"name": "Kept Person", "title": "Head Coach", "isHeadCoach": True, "isCoach": True,
                                "bioUrl": None, "social": {}}]}}
    net = Net(pages={DIRECTORY: directory_tr_group()})
    lines, _, err = run_collect(net, roster, robots=(COACHES,), stored=kept)
    ok("silent: coaches page disallowed and stored staff kept", lines == [] and net.sent == [] and err is None,
       (lines, net.sent, err))
    net = Net(pages={DIRECTORY: directory_tr_group()})
    lines, _, err = run_collect(net, {ROSTER: page('<a href="/staff-directory">d</a>')})
    ok("silent: 0 players (collect raises first)", lines == [] and net.sent == [] and isinstance(err, common.FetchError),
       (lines, net.sent, err))


def test_one_probe_per_program_per_run():
    roster = {ROSTER: roster_page()}
    net = Net(pages={DIRECTORY: directory_tr_group()})
    with Env(net):
        a, _, _ = run_collect(net, roster, fresh=False)
        b, _, _ = run_collect(net, roster, fresh=False)
        same = list(net.sent)
        c, _, _ = run_collect(net, roster, fresh=False, slug="another-fixture")
    ok("the same program twice in one run: one directory request, one line", same == [DIRECTORY] and len(a) == 1 and b == [],
       (same, a, b))
    ok("... a second program is probed on its own", len(c) == 1 and net.sent == [DIRECTORY, DIRECTORY], (c, net.sent))
    # control: with the per-run record cleared between calls the same program would be probed twice
    net = Net(pages={DIRECTORY: directory_tr_group()})
    with Env(net):
        run_collect(net, roster, fresh=False)
        sdp._probed.clear()
        run_collect(net, roster, fresh=False)
    ok("control: without the per-run record, two requests", net.sent.count(DIRECTORY) == 2, net.sent)


def test_failure_isolation_and_nothing_stored():
    roster = {ROSTER: roster_page()}
    real = sdp.probe

    def boom(*a, **k):
        raise RuntimeError("unexpected")
    sdp.probe = boom
    try:
        net = Net(pages={DIRECTORY: directory_tr_group()})
        lines, _, err = run_collect(net, roster)
    finally:
        sdp.probe = real
    ok("collect still succeeds when the probe raises", err is None, err)
    ok("... the source is still saved", len(SAVED) == 1, len(SAVED))
    ok("... with one short failure line naming only the exception type",
       lines == ["  !! staff-directory probe failed (RuntimeError)"], lines)
    ok("probe restored", sdp.probe is real)

    real_fetch = common.fetch_no_redirect

    def net_down(url, **kw):
        raise common.FetchError("ConnectionError for " + url)
    common.fetch_no_redirect = net_down
    try:
        lines, _, err = run_collect(Net(), roster)
    finally:
        common.fetch_no_redirect = real_fetch
    ok("a network error is dir=error, and collect succeeds", lines == ["  staff directory probe: robots=1 dir=error"]
       and err is None, (lines, err))

    net = Net(pages={DIRECTORY: directory_tr_group()})
    lines, fetched, err = run_collect(net, roster)
    ok("the probe ran", len(lines) == 1 and "dir=ok" in lines[0], lines)
    saved = repr(SAVED)
    ok("nothing from the directory is stored: staff stays empty", SAVED and SAVED[0].get("staff") == [], SAVED[:1])
    ok("... and no planted name, e-mail or phone is anywhere in the saved source",
       not any(x in saved for x in NAMES + EMAILS + PHONES), saved[:300])
    ok("the directory never went through the cached fetch path", DIRECTORY not in fetched, fetched)
    ok("... and has no .cache/http entry",
       not any(os.path.exists(os.path.join(common.CACHE_DIR, common._cache_key("GET", DIRECTORY, None) + s))
               for s in (".body.gz", ".body", ".json")))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_line_shape_and_counts, test_label_classes, test_header_allowlist, test_no_leak_and_contact_scanner,
                 test_mutation_unmasked_header_fails, test_caps_are_12_headers_and_400_characters,
                 test_robots_refusal_sends_nothing, test_offhost_redirect_requests_nothing_from_the_other_host,
                 test_same_host_hop, test_which_link_is_probed, test_trigger, test_one_probe_per_program_per_run,
                 test_failure_isolation_and_nothing_stored):
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
