"""ID camps daily, with safeguards (issue #284).

    python tests/refresh_schedule_test.py            # offline: talks only to stub servers on 127.0.0.1
    python tests/refresh_schedule_test.py --verbose  # print every check, not only the failures

What is checked:
  schedule       refresh.yml's three scheduled lines (Monday weekly, Aug-Dec daily, Jan-Jul daily) all
                 collect camps; --camps-stored-link is on the Jan-Jul daily line and no other;
                 --camps-retry-429 is on the Monday line and no other; `refresh` runs a program's
                 collectors in COLLECTORS order whatever order --only lists them in (camps after news).
  about          the About page states the real cadence: ID camps daily, rosters daily Aug-Dec.
  refused hosts  through the real collect.common.fetch and `collegedash.py refresh --only camps`, against
                 stub hosts on separate 127.0.0.1 ports (each port is its own host, so each stub is off
                 the athletics site): a recorded host gets zero requests, robots.txt included; the first
                 403/429 records the host and, with 2 workers and 2 programs on it, it gets exactly one
                 page request; a redirect onto a recorded host never reaches it; 404/503, the athletics
                 host and news fetches never record; a cleared entry is requested again; a run that only
                 skips leaves the file byte-identical.
  429 rule       an entry >= 7 days old gets one retry, only with --camps-retry-429: 2xx drops it,
                 another 429 keeps it unchanged; a younger entry, or a run without the flag, sends nothing.
  stored link    with the Jan-Jul line's flags a program with a stored camps.json makes zero roster
                 requests; the Monday line's flags rediscover (one roster request); no stored file, or a
                 404 on the stored link, falls back to discovery.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import http.server
import io
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import threading
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import collegedash  # noqa: E402
from collect import camps, common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False
YML = os.path.join(ROOT, ".github", "workflows", "refresh.yml")


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {ascii(detail)[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


# ---------- refresh.yml ----------

def scheduled_lines() -> dict[str, list[str]]:
    """weekly / daily-season / daily-offseason -> argv of that `python collegedash.py refresh` line."""
    out = {}
    for line in open(YML, encoding="utf-8").read().splitlines():
        m = re.search(r"python collegedash\.py (refresh .*)$", line.strip())
        if not m or "$ONLY_INPUT" in line or "--mode full" in line:
            continue
        argv = shlex.split(m.group(1))
        only = argv[argv.index("--only") + 1].split(",")
        mode = argv[argv.index("--mode") + 1]
        key = "weekly" if mode == "weekly" else "daily-season" if "athletics" in only else "daily-offseason"
        out[key] = argv
    return out


def only_of(argv):
    return argv[argv.index("--only") + 1].split(",")


def test_schedule():
    print("schedule: refresh.yml's scheduled lines")
    lines = scheduled_lines()
    ok("three scheduled lines found", set(lines) == {"weekly", "daily-season", "daily-offseason"}, str(lines))
    for k, argv in lines.items():
        # fails on the pre-#284 workflow: both daily lines lacked camps
        ok(f"FIX the {k} line collects camps", "camps" in only_of(argv), " ".join(argv))
    stored = sorted(k for k, a in lines.items() if "--camps-stored-link" in a)
    ok("FIX --camps-stored-link is on the Jan-Jul daily line and no other", stored == ["daily-offseason"], str(stored))
    retry = sorted(k for k, a in lines.items() if "--camps-retry-429" in a)
    ok("FIX --camps-retry-429 is on the Monday line and no other", retry == ["weekly"], str(retry))

    # a program's collectors run in COLLECTORS order, whatever --only says: camps mines what news wrote
    calls = []
    fake_build = types.ModuleType("build")
    fake_build.build = lambda reg, **kw: None
    reg = {"programs": [{"slug": s, "onboarded": True, "athletics": {"baseUrl": "http://x.invalid"}} for s in ("a", "b")]}
    with patched(collegedash, collect_one=lambda name, p, r, **kw: (calls.append((p["slug"], name)) or
                                                                    ({"program": p["slug"], "collector": name, "outcome": "ok", "error": ""}, None)),
                 report_refresh=lambda results, **kw: 0, record_outcomes=lambda slug, entries: True), \
            patched(common, load_registry=lambda: reg), modules(build=fake_build), quiet():
        collegedash.main(["refresh", "--only", "camps,news", "--workers", "1"])
    per = {s: [c for p, c in calls if p == s] for s in ("a", "b")}
    ok("FIX refresh --only camps,news still runs news before camps for each program",
       per == {"a": ["news", "camps"], "b": ["news", "camps"]}, str(per))


def test_about():
    print("about: the About page's refresh cadence")
    html = open(os.path.join(ROOT, "public", "index.html"), encoding="utf-8").read()
    ok("FIX the About page lists ID camps among the daily refreshes",
       "Commitments, news, ID camps and the NCAA RPI are refreshed daily" in html)
    ok("FIX the About page says rosters are daily from August to December and weekly otherwise",
       "rosters, schedules and staff daily from August to December and weekly (Mondays) the rest of the year" in html)


# ---------- stub hosts ----------

class Stub:
    """One host: an HTTP server on its own port. routes: path -> (status, headers, body). Records every
    request path (robots.txt included)."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.hits: list[str] = []
        stub = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                stub.hits.append(self.path)
                status, headers, body = stub.routes.get(self.path, (404, {}, b"not found"))
                if isinstance(body, str):
                    body = body.encode()
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", headers.get("Content-Type", "text/html; charset=utf-8"))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        self.url = f"http://{self.host}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def pages(self, prefix=""):
        return [p for p in self.hits if p != "/robots.txt" and p.startswith(prefix)]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


PAGE = "<html><head><title>Soccer Camps</title></head><body><p>Camps</p></body></html>"
ROSTER = ("<html><body><nav><a href='/sports/womens-soccer/camps'>Women's Soccer Camps</a></nav>"
          "<p>" + "roster " * 400 + "</p></body></html>")


@contextlib.contextmanager
def patched(mod, **attrs):
    saved = {k: getattr(mod, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)


@contextlib.contextmanager
def modules(**mods):
    saved = {k: sys.modules.get(k) for k in mods}
    try:
        sys.modules.update(mods)
        yield
    finally:
        for k, m in saved.items():
            if m is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = m


@contextlib.contextmanager
def quiet():
    if VERBOSE:
        yield
        return
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


class World:
    """A temp programs/, cache, refused-hosts file and refresh-state, and stub hosts to close."""

    def __init__(self, tmp, name):
        self.dir = os.path.join(tmp, name)
        os.makedirs(self.dir)
        self.refused = os.path.join(self.dir, "data", "camps-refused-hosts.json")
        self.programs = os.path.join(self.dir, "programs")
        self.stubs: list[Stub] = []

    def stub(self, routes=None) -> Stub:
        s = Stub(routes)
        self.stubs.append(s)
        return s

    def seed(self, entries: dict):
        os.makedirs(os.path.dirname(self.refused), exist_ok=True)
        with open(self.refused, "w", encoding="utf-8", newline="\n") as f:
            json.dump(entries, f, indent=2, sort_keys=True)
            f.write("\n")

    def file(self) -> dict | None:
        return common.read_json(self.refused, None)

    def raw(self) -> bytes | None:
        return open(self.refused, "rb").read() if os.path.exists(self.refused) else None

    def store(self, slug, data):
        d = os.path.join(self.programs, slug, "sources")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "camps.json"), "w", encoding="utf-8") as f:
            json.dump({"collector": "camps", "sourceUrl": None, "fetchedAt": "x", "data": data}, f)

    def camps_json(self, slug) -> dict:
        return (common.read_json(os.path.join(self.programs, slug, "sources", "camps.json"), {}) or {}).get("data") or {}

    def refresh(self, programs, flags=(), workers=2):
        """`collegedash.py refresh --only camps <flags>` over `programs`, as a new process would see it."""
        reg = {"programs": programs}
        fake_build = types.ModuleType("build")
        fake_build.build = lambda reg, **kw: None
        camps.reset_refused()
        common._robots.clear()
        common._host_delay.clear()
        with patched(common, CACHE_DIR=os.path.join(self.dir, "cache"), PROGRAMS_DIR=self.programs,
                     REFRESH_STATE_PATH=os.path.join(self.dir, "refresh-state.json"), load_registry=lambda: reg,
                     MIN_GAP_SECONDS=0.02, JITTER_SECONDS=0.0, BACKOFF_429_SECONDS=0.0, BACKOFF_5XX_SECONDS=0.0), \
                patched(camps, REFUSED_PATH=self.refused), patched(collegedash, report_refresh=lambda results, **kw: 0), \
                modules(build=fake_build), quiet():
            shutil.rmtree(os.path.join(self.dir, "cache"), ignore_errors=True)  # a new run: the runner has no cache
            collegedash.main(["refresh", "--only", "camps", *flags, "--workers", str(workers)])
        camps.configure()

    def close(self):
        for s in self.stubs:
            s.close()


def prog(slug, ath: Stub, camps_url=None):
    a = {"baseUrl": ath.url, "sportPath": "/sports/womens-soccer", "platform": "auto"}
    if camps_url:
        a["campsUrl"] = camps_url
    return {"slug": slug, "onboarded": True, "athletics": a}


def days_ago(n):
    return (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=n)).isoformat()


# ---------- refused hosts ----------

def test_refused(tmp):
    print("refused hosts: recorded, then never requested")
    w = World(tmp, "recorded-zero")
    try:
        ath, b = w.stub({"/sports/womens-soccer/roster": (200, {}, ROSTER)}), w.stub({"/a": (200, {}, PAGE), "/b": (200, {}, PAGE)})
        w.seed({b.host: {"status": 403, "firstAt": days_ago(30), "program": "old", "url": b.url + "/a"}})
        before = w.raw()
        w.refresh([prog("alpha", ath, b.url + "/a"), prog("beta", ath, b.url + "/b")])
        # fails if the refused-host check is missing, or runs after robots_allowed
        ok("FIX a recorded host gets zero requests, robots.txt included", b.hits == [], str(b.hits))
        ok("both programs say hostRefused", w.camps_json("alpha").get("hostRefused") and w.camps_json("beta").get("hostRefused"),
           str(w.camps_json("alpha")))
        ok("FIX a run that only skips leaves the file byte-identical", w.raw() == before)
    finally:
        w.close()

    for status in (403, 429):
        w = World(tmp, f"record-{status}")
        try:
            ath = w.stub()
            b = w.stub({"/a": (status, {}, "no"), "/b": (status, {}, "no")})
            w.refresh([prog("alpha", ath, b.url + "/a"), prog("beta", ath, b.url + "/b")], workers=2)
            f = w.file() or {}
            # fails on main: nothing is recorded, and both programs request the host every run
            ok(f"FIX a {status} host with 2 programs and 2 workers gets exactly one page request", len(b.pages()) == 1, str(b.hits))
            ok(f"FIX the {status} is recorded for that host", f.get(b.host, {}).get("status") == status, str(f))
            ok(f"the {status} entry names the program and date", f.get(b.host, {}).get("program") in ("alpha", "beta")
               and f.get(b.host, {}).get("firstAt") == common.today(), str(f))
            b.hits.clear()
            w.refresh([prog("alpha", ath, b.url + "/a"), prog("beta", ath, b.url + "/b")])
            ok(f"the next run sends the {status} host nothing", b.hits == [], str(b.hits))
            if status == 403:
                # clearing: the entry is deleted by a PR between runs; the next run asks once more
                w.seed({})
                b.hits.clear()
                b.routes["/a"] = b.routes["/b"] = (200, {}, PAGE)
                w.refresh([prog("alpha", ath, b.url + "/a"), prog("beta", ath, b.url + "/b")])
                ok("CONTROL a cleared host is requested again", sorted(b.pages()) == ["/a", "/b"], str(b.hits))
        finally:
            w.close()

    w = World(tmp, "redirect")
    try:
        ath, b = w.stub(), w.stub({"/camp": (200, {}, PAGE)})
        a = w.stub({"/go": (302, {"Location": b.url + "/camp"}, "")})
        w.seed({b.host: {"status": 403, "firstAt": days_ago(2), "program": "old", "url": b.url + "/camp"}})
        w.refresh([prog("alpha", ath, a.url + "/go")])
        # fails if the veto is only in fetch_checked: the redirect is followed inside common.fetch
        ok("FIX a redirect onto a recorded host never reaches it", b.hits == [] and a.pages() == ["/go"], f"a={a.hits} b={b.hits}")
        ok("and the program says hostRefused", w.camps_json("alpha").get("hostRefused") is True, str(w.camps_json("alpha")))
    finally:
        w.close()

    w = World(tmp, "not-refusals")
    try:
        ath = w.stub({"/camps": (403, {}, "no")})
        c = w.stub({"/gone": (404, {}, "x"), "/down": (503, {}, "x")})
        w.refresh([prog("alpha", ath, c.url + "/gone"), prog("beta", ath, c.url + "/down"), prog("gamma", ath, ath.url + "/camps")])
        ok("CONTROL a 404, a 503 and an athletics-site 403 record nothing", w.file() is None, str(w.file()))
        d = w.stub({"/news": (403, {}, "no")})
        camps.reset_refused()
        with patched(camps, REFUSED_PATH=w.refused), patched(common, CACHE_DIR=os.path.join(w.dir, "cache"), MIN_GAP_SECONDS=0.0), quiet():
            r = camps.fetch_checked(d.url + "/news", ath.host, slug="alpha", record=False)
        ok("CONTROL a news-article fetch (record=False) never records", w.file() is None and r["status"] == 403, str(r))
    finally:
        w.close()


def test_429_rule(tmp):
    print("429 rule: one retry on a Monday run, >= 7 days after recording")
    cases = [("due-kept", 8, ["--camps-retry-429"], 429, 1, True),
             ("due-unblocked", 8, ["--camps-retry-429"], 200, None, False),
             ("not-yet", 3, ["--camps-retry-429"], 200, 0, True),
             ("no-flag", 30, [], 200, 0, True)]
    for name, age, flags, answer, want_pages, kept in cases:
        w = World(tmp, f"429-{name}")
        try:
            ath = w.stub()
            b = w.stub({"/a": (answer, {}, PAGE), "/b": (answer, {}, PAGE)})
            w.seed({b.host: {"status": 429, "firstAt": days_ago(age), "program": "old", "url": b.url + "/a"}})
            before = w.raw()
            w.refresh([prog("alpha", ath, b.url + "/a"), prog("beta", ath, b.url + "/b")], flags=flags, workers=2)
            f = w.file() or {}
            if want_pages is not None:
                ok(f"FIX 429 {name}: {want_pages} page request(s) to the host, 2 programs, 2 workers",
                   len(b.pages()) == want_pages, str(b.hits))
            if kept:
                ok(f"FIX 429 {name}: the entry is kept, file byte-identical", w.raw() == before, str(f))
            else:
                ok("FIX 429 due-unblocked: a 2xx retry drops the entry", b.host not in f, str(f))
                ok("and the host is then requested normally for both programs", sorted(b.pages()) == ["/a", "/b"], str(b.hits))
        finally:
            w.close()
    w = World(tmp, "403-never-retried")
    try:
        ath, b = w.stub(), w.stub({"/a": (200, {}, PAGE)})
        w.seed({b.host: {"status": 403, "firstAt": days_ago(60), "program": "old", "url": b.url + "/a"}})
        w.refresh([prog("alpha", ath, b.url + "/a")], flags=["--camps-retry-429"])
        ok("CONTROL a 403 entry is never retried, even on a Monday run", b.hits == [], str(b.hits))
    finally:
        w.close()


# ---------- stored link ----------

def test_stored_link(tmp):
    print("stored link: Jan-Jul non-Monday runs make no roster request")
    lines = scheduled_lines()
    off = [a for a in lines.get("daily-offseason", []) if a.startswith("--camps-")]
    mon = [a for a in lines.get("weekly", []) if a.startswith("--camps-")]
    camp_path = "/sports/womens-soccer/camps"
    roster_path = "/sports/womens-soccer/roster"

    def world(name, stored=True, camp_status=200):
        w = World(tmp, name)
        ath = w.stub({roster_path: (200, {}, ROSTER), camp_path: (200, {}, PAGE), "/old-camps": (camp_status, {}, PAGE)})
        if stored:
            w.store("alpha", {"campsUrl": ath.url + "/old-camps", "discoveredVia": "anchor", "hubUrl": ath.url + "/hub"})
        return w, ath

    w, ath = world("stored-offseason")
    try:
        w.refresh([prog("alpha", ath)], flags=off)
        # fails if the Jan-Jul line lacks the flag, or the collector ignores it
        ok("FIX the Jan-Jul line's flags: zero roster requests, the stored camp page once",
           ath.pages(roster_path) == [] and ath.pages("/old-camps") == ["/old-camps"], str(ath.hits))
        d = w.camps_json("alpha")
        ok("the stored link is kept with its hub and marked linkReused",
           d.get("linkReused") is True and d.get("campsUrl") == ath.url + "/old-camps" and d.get("hubUrl") == ath.url + "/hub", str(d))
    finally:
        w.close()
    w, ath = world("stored-monday")
    try:
        w.refresh([prog("alpha", ath)], flags=mon)
        ok("CONTROL the Monday line's flags rediscover: one roster request", ath.pages(roster_path) == [roster_path], str(ath.hits))
        ok("and the rediscovered link replaces the stored one", w.camps_json("alpha").get("campsUrl") == ath.url + camp_path,
           str(w.camps_json("alpha")))
    finally:
        w.close()
    w, ath = world("no-stored-file", stored=False)
    try:
        w.refresh([prog("alpha", ath)], flags=off)
        ok("CONTROL with no stored camps.json the flag falls back to discovery", ath.pages(roster_path) == [roster_path], str(ath.hits))
    finally:
        w.close()
    w, ath = world("stored-404", camp_status=404)
    try:
        w.refresh([prog("alpha", ath)], flags=off)
        d = w.camps_json("alpha")
        ok("FIX a 404 on the stored link rediscovers in the same run",
           ath.pages(roster_path) == [roster_path] and d.get("campsUrl") == ath.url + camp_path and d.get("linkReused") is False,
           f"{ath.hits} {d}")
    finally:
        w.close()


def main(argv=None) -> int:
    global VERBOSE
    VERBOSE = "--verbose" in (argv or sys.argv[1:])
    tmp = tempfile.mkdtemp(prefix="refresh-schedule-")
    try:
        test_schedule()
        test_about()
        test_refused(tmp)
        test_429_rule(tmp)
        test_stored_link(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{TOTAL - len(FAILS)}/{TOTAL} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
