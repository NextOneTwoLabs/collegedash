"""Per-host politeness and outcome recording under `refresh --workers N` (issue #94), witnessed by the server.

    python tests/refresh_politeness_test.py            # offline: talks only to stub servers on 127.0.0.1
    python tests/refresh_politeness_test.py --verbose  # print every check, not only the failures

The refresh collects many programs at once so that it stops idling in one athletics site's
politeness gap while every other host waits. The promise that makes that acceptable is that no host
receives two requests at once or two requests closer than the configured gap. Nobody watches that
promise once it ships, so this suite checks it from the side that cannot be fooled: the server's.
Each "host" is a stub server on its own port (`_host` keys hosts by host:port) that records, for every
request, when it arrived and when its response went out.

What is checked, all through the real collect.common.fetch / robots_allowed / _locked and the real
collegedash.collect_plan, from many threads:

  gap/overlap     on every host, requests never overlap and consecutive arrivals are at least the gap
                  apart; a shared host hit by every thread included
  gap under CPU   the same, with the server in a SEPARATE PROCESS and CPU-bound threads competing for
                  the GIL in the client -- the case an in-process stub cannot show (PR #105 review:
                  the gap was stamped before the request was sent, and the host saw 0.765 s for 1.2)
  body in gate    a slow body is read before the host is released
  crawl-delay     a CollegeDashBot group's Crawl-delay spaces that host; the delay is recorded before
                  the parser is published
  redirects       a redirect hop is a request to the host it lands on
  backoff         after a 503, no worker reaches that host until the backoff ends -- including workers
                  already queued on the gate -- and every backoff is recorded while the gate is held
  one per URL     eight threads missing one URL send one request; robots.txt is fetched once per host
  plan order      collect_plan returns outcomes in plan order; a program's collectors never overlap
  refresh-state   one write per program; a write that fails, transiently or for good, neither
                  misrecords a success nor escapes nor loses an outcome; the in-process path lock has
                  no timeout, is taken before the lock file, and a PermissionError on the lock file
                  means "held"
  tracebacks      a worker's traceback lines carry the program slug
  redirect 503    a backoff after a redirect holds the host that ANSWERED, not the one asked for
  send stamp      the gap is measured from when the request was sent: with a deliberate pre-send
                  delay inside the gate, the host still sees the full gap between arrivals
  state write     a refresh-state write that fails every retry is annotated, counted in lastRun and
                  reported in the summary, and still does not fail the run

Controls: the gap, Crawl-delay, backoff and one-per-URL checkers are also run with the gate or key
lock disabled, and the suite asserts they then REPORT violations. Every other check was shown to fail
against a mutation of the code, or against the previous commit; the PR records which.
"""

from __future__ import annotations

import argparse
import contextlib
import http.server
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for var in ("COLLEGEDASH_OFFLINE", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(var, None)
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"

from collect import common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False

GAP = 0.25          # MIN_GAP_SECONDS for the suite (production: 1.2)
JITTER = 0.05       # JITTER_SECONDS for the suite (production: 0.8)
CRAWL_DELAY = 1     # > GAP, so it must win. An integer: urllib.robotparser ignores "Crawl-delay: 0.8"
BACKOFF = 0.5       # BACKOFF_5XX_SECONDS for the suite (production: 5)
CPU_GAP = 0.6       # MIN_GAP_SECONDS for the CPU-load case (see there)
TOL = 0.03          # clock slack between the client's stamp and the server's arrival stamp


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}" + (f" - {detail}" if detail else ""))
    return bool(cond)


# ---------- stub hosts ----------

class Stub:
    """One host: a threaded HTTP server on its own port that records (path, arrived, sent, status).
    A route returns (status, headers, body, latency) or (..., trickle): with a trickle the body goes
    out in pieces over that many seconds, and `sent` is stamped only before the last piece."""

    def __init__(self, name: str, routes=None):
        self.name = name
        self.log: list[tuple[str, float, float, int]] = []
        self.lock = threading.Lock()
        self.routes = routes or {}
        self.hits: dict[str, int] = {}
        stub = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _serve(self):
                arrived = time.monotonic()
                with stub.lock:
                    n = stub.hits[self.path] = stub.hits.get(self.path, 0) + 1
                status, headers, body, latency, *rest = stub.respond(self.path, n)
                trickle = rest[0] if rest else 0.0
                time.sleep(latency)
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if trickle and len(body) > 1:
                    pieces = 10
                    step = max(1, len(body) // pieces)
                    for i in range(0, len(body) - 1, step):
                        self.wfile.write(body[i:min(i + step, len(body) - 1)])
                        self.wfile.flush()
                        time.sleep(trickle / pieces)
                    sent = time.monotonic()
                    self.wfile.write(body[-1:])
                else:
                    sent = time.monotonic()  # stamped before the body goes out: a conservative "end"
                    self.wfile.write(body)
                with stub.lock:
                    stub.log.append((self.path, arrived, sent, status))

            do_GET = _serve
            do_POST = _serve

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.host = f"127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, path: str) -> str:
        return f"http://{self.host}{path}"

    def respond(self, path: str, n: int):
        for prefix, fn in self.routes.items():
            if path.startswith(prefix):
                return fn(path, n)
        return 200, {"Content-Type": "text/html"}, b"<html>ok</html>" * 50, random.uniform(0.02, 0.4)

    def reset(self):
        with self.lock:
            self.log.clear()
            self.hits.clear()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def violations(stub: Stub, min_gap: float) -> list[str]:
    """Every pair of consecutive requests on `stub` that overlaps or arrives closer than min_gap."""
    rows = sorted(stub.log, key=lambda r: r[1])
    bad = []
    for (p1, a1, s1, _), (p2, a2, s2, _) in zip(rows, rows[1:]):
        if a2 < s1:
            bad.append(f"overlap: {p2} arrived {s1 - a2:.3f}s before {p1} was answered")
        if a2 - a1 < min_gap - TOL:
            bad.append(f"gap: {p2} arrived {a2 - a1:.3f}s after {p1} (< {min_gap}s)")
    return bad


@contextlib.contextmanager
def fresh_state(tmp: str):
    """A clean politeness/robots/cache state for one case, with the suite's short timings."""
    saved = (common.CACHE_DIR, common.MIN_GAP_SECONDS, common.JITTER_SECONDS, common.BACKOFF_5XX_SECONDS,
             common.BACKOFF_NETWORK_SECONDS)
    common.CACHE_DIR = tempfile.mkdtemp(dir=tmp)
    common.MIN_GAP_SECONDS, common.JITTER_SECONDS = GAP, JITTER
    common.BACKOFF_5XX_SECONDS = BACKOFF
    common.BACKOFF_NETWORK_SECONDS = 0.1
    common._gates.clear()
    common._last_request_at.clear()
    common._robots.clear()
    common._host_delay.clear()
    common._key_locks.clear()
    try:
        yield
    finally:
        (common.CACHE_DIR, common.MIN_GAP_SECONDS, common.JITTER_SECONDS, common.BACKOFF_5XX_SECONDS,
         common.BACKOFF_NETWORK_SECONDS) = saved


@contextlib.contextmanager
def gate_disabled():
    """The control: politeness and backoff holds switched off, everything else unchanged."""
    real_polite, real_hold = common._polite, common._hold

    @contextlib.contextmanager
    def no_gate(url):
        yield common._HostGate()  # a gate nobody else shares, never waited on

    common._polite, common._hold = no_gate, (lambda g, seconds: None)
    try:
        yield
    finally:
        common._polite, common._hold = real_polite, real_hold


@contextlib.contextmanager
def key_lock_disabled():
    real = common._key_lock
    common._key_lock = lambda key: threading.Lock()  # a new lock per call excludes nobody
    try:
        yield
    finally:
        common._key_lock = real


def run_threads(jobs, workers: int = 12):
    errors = []

    def call(job):
        try:
            job()
        except Exception as e:  # noqa: BLE001 - a failed fetch is reported, not fatal to the suite
            errors.append(repr(e))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(call, jobs))
    return errors


# ---------- cases: the gate ----------

def load_mixed(shared: Stub, own: list[Stub], redirector: Stub, delayed: Stub) -> list[str]:
    """What a refresh looks like to the network: every worker hits the shared host once per program,
    its own host several times, some redirect onto the shared host, one host asks a Crawl-delay."""
    common.set_robots_txt(delayed.host, f"User-agent: *\nCrawl-delay: 5\n\nUser-agent: CollegeDashBot\nCrawl-delay: {CRAWL_DELAY}\n")
    jobs = []
    for i in range(24):
        jobs.append(lambda i=i: common.fetch(shared.url(f"/team/{i}"), max_age_hours=None))
    for k, s in enumerate(own):
        for i in range(5):
            jobs.append(lambda s=s, i=i: common.fetch(s.url(f"/roster/{i}"), max_age_hours=None))
    for i in range(8):
        jobs.append(lambda i=i: common.fetch(redirector.url(f"/r/{i}"), max_age_hours=None))
    for i in range(4):
        jobs.append(lambda i=i: common.fetch(delayed.url(f"/slow/{i}"), max_age_hours=None))
    random.Random(94).shuffle(jobs)
    return run_threads(jobs, workers=12)


def test_gap_overlap_redirect_crawl_delay(tmp: str) -> None:
    print("gap/overlap, redirects, crawl-delay (12 threads)")
    shared = Stub("shared")
    own = [Stub(f"own{k}") for k in range(3)]
    delayed = Stub("delayed")
    redirector = Stub("redirector", routes={
        "/r/": lambda path, n: (302, {"Location": shared.url("/landed/" + path.rsplit("/", 1)[-1])}, b"", 0.01),
    })
    stubs = [shared, *own, redirector, delayed]
    try:
        with fresh_state(tmp):
            errors = load_mixed(shared, own, redirector, delayed)
            ok("every fetch succeeded", not errors, "; ".join(errors[:3]))
            ok("the stub's robots.txt set the host's Crawl-delay from the CollegeDashBot group",
               common._host_delay.get(delayed.host) == CRAWL_DELAY, f"{common._host_delay}")
            landed = [r for r in shared.log if r[0].startswith("/landed/")]
            ok("redirect hops reached the shared host", len(landed) == 8, f"{len(landed)} hops")
            ok("the shared host saw direct requests and hops interleaved", len(shared.log) == 32, f"{len(shared.log)}")
            for s in [shared, *own, redirector]:
                bad = violations(s, GAP)
                ok(f"{s.name}: no overlap, arrivals >= {GAP}s apart ({len(s.log)} requests)", not bad, "; ".join(bad[:3]))
            bad = violations(delayed, CRAWL_DELAY)
            ok(f"delayed: CollegeDashBot Crawl-delay {CRAWL_DELAY}s honoured, not '*' 5s nor MIN_GAP ({len(delayed.log)} requests)",
               not bad and len(delayed.log) == 4, "; ".join(bad[:3]))
            rows = sorted(delayed.log, key=lambda r: r[1])
            gaps = [b[1] - a[1] for a, b in zip(rows, rows[1:])]
            ok("delayed: the CollegeDashBot group won over '*' (gaps well under 5s)", gaps and max(gaps) < 5 - 1, f"{gaps}")

        # control: the same load with the gate switched off must be caught by the same checker
        for s in stubs:
            s.reset()
        with fresh_state(tmp), gate_disabled():
            load_mixed(shared, own, redirector, delayed)
            ok("CONTROL: with the gate disabled the checker reports shared-host violations",
               len(violations(shared, GAP)) > 0, f"{len(violations(shared, GAP))} found")
            ok("CONTROL: with the gate disabled the checker reports Crawl-delay violations",
               len(violations(delayed, CRAWL_DELAY)) > 0, f"{len(violations(delayed, CRAWL_DELAY))} found")
    finally:
        for s in stubs:
            s.close()


SERVER_PROCESS = r'''
import http.server, json, random, sys, threading, time
arrivals, lock = [], threading.Lock()
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_GET(self):
        arrived = time.perf_counter()
        if self.path == "/__log":
            with lock:
                body = json.dumps(sorted(arrivals)).encode()
        else:
            with lock:
                arrivals.append(arrived)
            time.sleep(random.uniform(0.02, 0.1))  # shorter than the gap, so the gap and not latency spaces requests
            body = b"<html>ok</html>" * 200
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
srv.daemon_threads = True
print(srv.server_address[1], flush=True)
srv.serve_forever()
'''


def test_gap_under_cpu_load(tmp: str) -> None:
    print("gap at the host with CPU-bound threads in the client (server in its own process)")
    proc = subprocess.Popen([sys.executable, "-c", SERVER_PROCESS], stdout=subprocess.PIPE, text=True)
    stop = threading.Event()
    try:
        port = int(proc.stdout.readline())
        host = f"http://127.0.0.1:{port}"

        def burn():  # a parser's worth of pure-Python work, holding the GIL in 5 ms slices
            x = 0
            while not stop.is_set():
                for i in range(5000):
                    x += i * i

        burners = [threading.Thread(target=burn, daemon=True) for _ in range(2)]
        with fresh_state(tmp):
            # a gap well above latency, and little jitter: what separates the requests is then the gap
            # alone, so any variation in when the bytes actually leave shows up as a short interval
            common.MIN_GAP_SECONDS, common.JITTER_SECONDS = CPU_GAP, 0.05
            for b in burners:
                b.start()
            errors = run_threads([lambda i=i: common.fetch(f"{host}/p/{i}", max_age_hours=None) for i in range(32)], workers=8)
            stop.set()
            for b in burners:
                b.join()
            arrivals = json.loads(common.fetch(f"{host}/__log", max_age_hours=None)[0])
        gaps = [b - a for a, b in zip(arrivals, arrivals[1:])]
        short = [g for g in gaps if g < CPU_GAP - TOL]
        ok("32 fetches under CPU load all succeeded", not errors and len(arrivals) == 32, "; ".join(errors[:3]))
        ok(f"no two arrivals at the host closer than MIN_GAP {CPU_GAP}s (server-side clock, separate process)",
           not short, f"{len(short)} of {len(gaps)} short, min {min(gaps):.3f}s, mean {sum(gaps) / len(gaps):.3f}s")
        if VERBOSE:
            print(f"       intervals: min {min(gaps):.3f}s mean {sum(gaps) / len(gaps):.3f}s max {max(gaps):.3f}s")
    finally:
        stop.set()
        proc.terminate()
        proc.wait(timeout=10)


def test_body_read_inside_gate(tmp: str) -> None:
    print("a slow body is read before the host is released")
    stub = Stub("trickle", routes={
        "/t/": lambda path, n: (200, {"Content-Type": "text/html"}, b"x" * 4000, 0.01, 0.6),
    })
    try:
        with fresh_state(tmp):
            errors = run_threads([lambda i=i: common.fetch(stub.url(f"/t/{i}"), max_age_hours=None) for i in range(6)], workers=6)
            ok("six trickled bodies arrived whole", not errors, "; ".join(errors[:3]))
            bad = [v for v in violations(stub, GAP) if v.startswith("overlap")]
            ok("no request arrived while the previous body was still being sent", not bad, "; ".join(bad[:3]))
    finally:
        stub.close()


def load_backoff(flaky: Stub) -> tuple[list[str], list]:
    done = threading.Event()

    def first():
        try:
            time.sleep(0.1)  # let the queue form, so the 503s land with workers waiting on the gate
            common.fetch(flaky.url("/flaky"), max_age_hours=None, retries=3)
        finally:
            done.set()

    def later(i):
        j = 0
        while not done.is_set():
            common.fetch(flaky.url(f"/ok/{i}/{j}"), max_age_hours=None)
            j += 1

    errors = run_threads([first] + [lambda i=i: later(i) for i in range(4)], workers=5)
    return errors, sorted(flaky.log, key=lambda r: r[1])


def backoff_breaches(rows) -> list[str]:
    """Requests that arrived while a 503's backoff should have been holding the host. The k-th 503
    answers attempt k, whose backoff is k x BACKOFF_5XX_SECONDS."""
    out = []
    k = 0
    for path, arrived, sent, status in rows:
        if status == 503:
            k += 1
            hold = BACKOFF * k
            for p2, a2, _, _ in rows:
                if sent < a2 < sent + hold - TOL:
                    out.append(f"{p2} arrived {a2 - sent:.3f}s into the {hold}s backoff after 503 #{k}")
    return out


def test_backoff(tmp: str) -> None:
    print("backoff holds the host, including for workers already queued on it")
    routes = {"/flaky": lambda path, n: ((503, {}, b"busy", 0.3) if n <= 2 else (200, {}, b"fine", 0.05)),
              "/ok/": lambda path, n: (200, {}, b"fine", 0.05)}
    flaky = Stub("flaky", routes=routes)
    try:
        writes: list[bool] = []
        real_gate = common._HostGate

        class OwnedLock:
            """threading.Lock that remembers which thread holds it."""

            def __init__(self):
                self._lock, self.owner = threading.Lock(), None

            def acquire(self, *a, **kw):
                got = self._lock.acquire(*a, **kw)
                if got:
                    self.owner = threading.get_ident()
                return got

            def release(self):
                self.owner = None
                self._lock.release()

            def locked(self):
                return self._lock.locked()

            __enter__ = acquire

            def __exit__(self, *exc):
                self.release()

        class WatchedGate(real_gate):
            """Records, for every backoff written after construction, whether the WRITING thread held the
            gate at that moment (merely 'locked' is not enough: a queued worker may hold it by then)."""
            __slots__ = ("_nb", "_ready")

            def __init__(self):
                self._ready = False
                super().__init__()
                self.lock = OwnedLock()
                self._ready = True

            @property
            def not_before(self):
                return self._nb

            @not_before.setter
            def not_before(self, value):
                if self._ready:
                    writes.append(self.lock.owner == threading.get_ident())
                self._nb = value

        with fresh_state(tmp):
            common._HostGate = WatchedGate
            try:
                errors, rows = load_backoff(flaky)
            finally:
                common._HostGate = real_gate
            ok("the flaky fetch recovered on its third attempt and the rest succeeded", not errors, "; ".join(errors[:3]))
            ok("two 503s were served, with other requests around them",
               sum(r[3] == 503 for r in rows) == 2 and len(rows) > 6, f"{len(rows)} requests")
            bad = backoff_breaches(rows)
            ok("no request reached the host during either backoff (0.5s, then 1.0s)", not bad, "; ".join(bad[:3]))
            ok("no overlap and gaps held around the backoff", not violations(flaky, GAP), "; ".join(violations(flaky, GAP)[:3]))
            ok("every backoff was recorded by the thread holding the host's gate (so no queued worker can miss it)",
               writes and all(writes), f"{len(writes)} writes, {writes.count(False)} outside the gate")
        flaky.reset()
        with fresh_state(tmp), gate_disabled():
            _, rows = load_backoff(flaky)
            ok("CONTROL: with the hold disabled the checker reports requests inside the backoff",
               len(backoff_breaches(rows)) > 0, f"{len(backoff_breaches(rows))} found")
    finally:
        flaky.close()


def test_one_request_per_url(tmp: str) -> None:
    print("one live request per URL, one robots.txt per host, Crawl-delay before the parser is published")
    robots_body = f"User-agent: *\nDisallow: /private/\n\nUser-agent: CollegeDashBot\nDisallow: /private/\nCrawl-delay: {CRAWL_DELAY}\n".encode()
    stub = Stub("same", routes={
        "/robots.txt": lambda path, n: (200, {"Content-Type": "text/plain"}, robots_body, 0.3),
        "/same": lambda path, n: (200, {"Content-Type": "text/html"}, b"<html>same</html>", 0.3),
    })
    try:
        with fresh_state(tmp):
            errors = run_threads([lambda: common.fetch(stub.url("/same"), max_age_hours=6)] * 8, workers=8)
            ok("eight threads fetching one URL all got the body", not errors, "; ".join(errors[:3]))
            ok("eight threads missing one URL sent exactly one request", stub.hits.get("/same") == 1, f"{stub.hits.get('/same')}")
            answers, published_first = [], []
            real_apply = common._apply_crawl_delay

            def watched_apply(host, rp):
                published_first.append(host in common._robots)
                return real_apply(host, rp)

            common._apply_crawl_delay = watched_apply
            try:
                errors = run_threads([lambda: answers.append(common.robots_allowed(stub.url("/private/x")))] * 8, workers=8)
            finally:
                common._apply_crawl_delay = real_apply
            ok("eight threads asking robots for a new host fetched robots.txt exactly once",
               stub.hits.get("/robots.txt") == 1, f"{stub.hits.get('/robots.txt')}")
            ok("and every thread got the same, correct verdict", answers == [False] * 8, f"{answers}")
            ok("the host's Crawl-delay was recorded before its parser became visible to other threads",
               published_first == [False] and common._host_delay.get(stub.host) == CRAWL_DELAY,
               f"published before delay: {published_first}, delay {common._host_delay.get(stub.host)}")
        stub.reset()
        with fresh_state(tmp), key_lock_disabled():
            run_threads([lambda: common.fetch(stub.url("/same"), max_age_hours=6)] * 8, workers=8)
            run_threads([lambda: common.robots_allowed(stub.url("/x"))] * 8, workers=8)
            ok("CONTROL: without the key lock the same load sends duplicate requests",
               (stub.hits.get("/same") or 0) > 1 or (stub.hits.get("/robots.txt") or 0) > 1,
               f"/same {stub.hits.get('/same')}, robots {stub.hits.get('/robots.txt')}")
    finally:
        stub.close()


def test_sequential_unchanged(tmp: str) -> None:
    print("one thread: the sequential spacing is unchanged")
    stub = Stub("seq")
    try:
        with fresh_state(tmp):
            for i in range(5):
                common.fetch(stub.url(f"/p/{i}"), max_age_hours=None)
            rows = sorted(stub.log, key=lambda r: r[1])
            ok("five sequential requests, none closer than MIN_GAP", len(rows) == 5 and not violations(stub, GAP),
               "; ".join(violations(stub, GAP)))
            gaps = [b[1] - a[1] for a, b in zip(rows, rows[1:])]
            ok("and not slowed beyond gap + jitter + latency",
               all(g < GAP + JITTER + 0.4 + 0.15 for g in gaps), f"{[round(g, 3) for g in gaps]}")
    finally:
        stub.close()


# ---------- cases: collect_plan and refresh-state ----------

COLLECT = ["athletics", "tds", "soccerwire", "news"]
MODULES = {"athletics": "athletics_site", "tds": "commitments_tds", "soccerwire": "commitments_soccerwire", "news": "news"}


def expected_outcome(i: int, name: str) -> str:
    k = i * 7 + COLLECT.index(name)
    return "failed" if k % 11 == 0 else "skipped" if k % 13 == 0 else "ok"


@contextlib.contextmanager
def fake_collectors(spans: dict):
    """Replace the four daily collectors with fakes whose outcome is a function of (program, collector)
    and which record when each run started and ended."""
    import importlib
    mods = {name: importlib.import_module(f"collect.{m}") for name, m in MODULES.items()}
    real = {name: mod.collect for name, mod in mods.items()}
    lock = threading.Lock()

    def make(name):
        def collect(program, registry, **kw):
            i = int(program["slug"][1:])
            start = time.monotonic()
            time.sleep(random.uniform(0.001, 0.008))
            end = time.monotonic()
            with lock:
                spans[(program["slug"], name)] = (start, end)
            outcome = expected_outcome(i, name)
            if outcome == "failed":
                raise common.FetchError(f"injected failure {program['slug']}.{name}")
            if outcome == "skipped":
                raise common.SkipCollector(f"injected skip {program['slug']}.{name}")
        return collect

    for name, mod in mods.items():
        mod.collect = make(name)
    try:
        yield
    finally:
        for name, mod in mods.items():
            mod.collect = real[name]


@contextlib.contextmanager
def state_file(tmp: str, fail_every: int = 0):
    """Point refresh-state at a temp file and count the writes to it. fail_every=3 makes every third
    write attempt raise OSError; fail_every=1 makes every one raise."""
    saved = common.REFRESH_STATE_PATH
    path = os.path.join(tempfile.mkdtemp(dir=tmp), "refresh-state.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{}\n")
    common.REFRESH_STATE_PATH = path
    real_write = common.write_json
    counts = {"attempts": 0, "written": 0}
    lock = threading.Lock()
    last_failed = threading.local()  # transient means transient: never fail the same thread twice running

    def write_json(p, obj, **kw):
        if p == path:
            with lock:
                counts["attempts"] += 1
                n = counts["attempts"]
            if fail_every == 1 or (fail_every and n % fail_every == 0 and not getattr(last_failed, "v", False)):
                last_failed.v = True
                raise OSError(f"injected refresh-state write failure #{n}")
            last_failed.v = False
            out = real_write(p, obj, **kw)
            with lock:
                counts["written"] += 1
            return out
        return real_write(p, obj, **kw)

    common.write_json = write_json
    try:
        yield path, counts
    finally:
        common.write_json = real_write
        common.REFRESH_STATE_PATH = saved


def run_plan(collegedash, plan, workers):
    """collect_plan with its log output captured. Returns (results or None, escaped exception text, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            return collegedash.collect_plan(plan, {}, bios=False, workers=workers), "", err.getvalue()
    except Exception:
        return None, traceback.format_exc().strip().splitlines()[-1], err.getvalue()


def test_plan_and_state(tmp: str) -> None:
    print("collect_plan: order, no overlap within a program, refresh-state recorded once per program and never lost")
    import collegedash

    n = 80
    plan = [({"slug": f"p{i:03d}"}, list(COLLECT)) for i in range(n)]
    expected = [{"program": f"p{i:03d}", "collector": c, "outcome": expected_outcome(i, c)} for i in range(n) for c in COLLECT]

    def strip(results):
        return None if results is None else [{k: r[k] for k in ("program", "collector", "outcome")} for r in results]

    def state_matches(path):
        state = common.read_json(path, {}) or {}
        missing, wrong = [], []
        for e in expected:
            entry = state.get(f"{e['program']}.{e['collector']}")
            if not isinstance(entry, dict):
                missing.append(f"{e['program']}.{e['collector']}")
            elif entry.get("ok") is not (e["outcome"] != "failed") or (e["outcome"] == "skipped") != ("skipped" in entry):
                wrong.append(f"{e['program']}.{e['collector']}={entry}")
        return missing, wrong

    spans: dict = {}
    with fake_collectors(spans):
        runs = {}
        for workers in (1, 8, 64):
            with state_file(tmp) as (path, counts):
                spans.clear()
                results, escaped, err = run_plan(collegedash, plan, workers)
                runs[workers] = (strip(results), escaped, dict(counts), state_matches(path), dict(spans), err)
        for workers, (results, escaped, counts, (missing, wrong), sp, err) in runs.items():
            ok(f"{workers} worker(s): no exception escaped collect_plan", not escaped, escaped)
            ok(f"{workers} worker(s): every outcome returned, correct, in plan order", results == expected,
               f"{sum(1 for a, b in zip(results or [], expected) if a != b)} differ" if results else "no results")
            ok(f"{workers} worker(s): refresh-state records every outcome correctly", not missing and not wrong,
               f"missing {len(missing)}, wrong {len(wrong)}: {(missing + wrong)[:2]}")
            ok(f"{workers} worker(s): refresh-state written once per program ({n}), not once per collector",
               counts["written"] == n, f"{counts['written']} writes")
            overlaps = [f"{p['slug']}: {a} ran until {sp[(p['slug'], a)][1]:.4f}, {b} started {sp[(p['slug'], b)][0]:.4f}"
                        for p, cs in plan for a, b in zip(cs, cs[1:])
                        if (p["slug"], a) in sp and (p["slug"], b) in sp and sp[(p["slug"], b)][0] < sp[(p["slug"], a)][1]]
            ok(f"{workers} worker(s): each program's collectors ran strictly one after another", not overlaps, "; ".join(overlaps[:2]))
        err64 = runs[64][5]
        lines = [ln for ln in err64.splitlines() if ln.strip()]
        unlabelled = [ln for ln in lines if not re.match(r"^p\d{3} \| ", ln)]
        failures = sum(1 for e in expected if e["outcome"] == "failed")
        headers = sum(1 for ln in lines if ln.endswith("| Traceback (most recent call last):"))
        ok("64 workers: every traceback line is prefixed with its program slug",
           lines and not unlabelled and headers == failures, f"{len(unlabelled)} unlabelled of {len(lines)}; {headers} tracebacks for {failures} failures; e.g. {unlabelled[:1]}")

        with state_file(tmp, fail_every=3) as (path, counts):
            results, escaped, _ = run_plan(collegedash, plan, 64)
            missing, wrong = state_matches(path)
            ok("transient refresh-state write failures (every 3rd write, never twice running on one thread): nothing escaped", not escaped, escaped)
            ok("transient: no success recorded as a failure and no outcome lost", strip(results) == expected,
               f"{sum(1 for a, b in zip(strip(results) or [], expected) if a != b)} outcomes differ" if results else "no results")
            ok("transient: refresh-state still ends up recording every outcome correctly", not missing and not wrong,
               f"missing {len(missing)}, wrong {len(wrong)}: {(missing + wrong)[:2]}")

        with state_file(tmp, fail_every=1) as (path, counts):
            results, escaped, _ = run_plan(collegedash, plan, 64)
            ok("refresh-state unwritable for the whole run: nothing escaped", not escaped, escaped)
            ok("unwritable: every outcome still returned, correct, in plan order (the summary is built from these)",
               strip(results) == expected, "no results" if results is None else "" if strip(results) == expected else "outcomes differ")


def test_path_lock(tmp: str) -> None:
    print("_locked: no in-process timeout, threads queue in-process, PermissionError means held")
    path = os.path.join(tempfile.mkdtemp(dir=tmp), "state.json")
    lock_file = path + ".lock"
    real_open = os.open

    # 1. a thread waiting longer than `timeout` for another THREAD does not fail
    held = threading.Event()
    result = {}

    def holder():
        with common._locked(path, timeout=0.3):
            held.set()
            time.sleep(1.0)

    def waiter():
        held.wait()
        t = time.monotonic()
        try:
            with common._locked(path, timeout=0.3):
                result["waited"] = time.monotonic() - t
        except Exception as e:  # noqa: BLE001
            result["error"] = repr(e)

    a, b = threading.Thread(target=holder), threading.Thread(target=waiter)
    a.start(), b.start()
    a.join(), b.join()
    ok("a thread queued 1.0s behind another thread, with timeout=0.3, got the lock instead of failing",
       "error" not in result and result.get("waited", 0) > 0.5, f"{result}")

    # 2. while one thread holds the path, another does not poll the lock file
    polls = {"n": 0}
    held.clear()
    released = threading.Event()
    waiter_ident = {}

    def counting_open(p, *args, **kw):
        if p == lock_file and threading.get_ident() == waiter_ident.get("id"):
            polls["n"] += 1
        return real_open(p, *args, **kw)

    def holder2():
        with common._locked(path):
            held.set()
            time.sleep(0.6)
        released.set()

    def waiter2():
        waiter_ident["id"] = threading.get_ident()
        held.wait()
        with common._locked(path):
            polls["after_release"] = released.is_set()

    os.open = counting_open
    try:
        a, b = threading.Thread(target=holder2), threading.Thread(target=waiter2)
        a.start(), b.start()
        a.join(), b.join()
    finally:
        os.open = real_open
    ok("a thread waiting on another thread's lock does not touch the lock file until it is released (one poll, not ~12)",
       polls["n"] <= 1, f"{polls['n']} lock-file attempts")

    # 3. PermissionError on the lock file (Windows: delete pending) is treated as held, not raised
    calls = {"n": 0}

    def flaky_open(p, *args, **kw):
        if p == lock_file:
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError(13, "Permission denied (injected: delete pending)", p)
        return real_open(p, *args, **kw)

    os.open = flaky_open
    try:
        with common._locked(path, timeout=2):
            got = True
    except Exception as e:  # noqa: BLE001
        got = repr(e)
    finally:
        os.open = real_open
    ok("a PermissionError creating the lock file is retried as 'held', not raised", got is True and calls["n"] == 2,
       f"{got}, {calls['n']} attempts")


def test_redirect_backoff_holds_the_answering_host(tmp: str) -> None:
    """A 429/5xx after a redirect holds the host that answered it (issue #119 B).

    Nothing in the suite covered this: a mutation that held the originally requested host instead
    passed every check. Here host A only redirects, host B answers 503, and other workers are
    hammering B - so if the hold lands on A, B is hit during its own backoff.
    """
    print("a backoff after a redirect holds the host that answered")
    landing = Stub("landing", routes={
        "/boom": lambda path, n: ((503, {}, b"busy", 0.05) if n == 1 else (200, {}, b"fine", 0.05)),
        "/ok/": lambda path, n: (200, {}, b"fine", 0.05),
    })
    redirector = Stub("redirector", routes={"/r": lambda path, n: (302, {"Location": landing.url("/boom")}, b"", 0.01)})
    try:
        with fresh_state(tmp):
            done = threading.Event()

            def first():
                try:
                    time.sleep(0.1)
                    common.fetch(redirector.url("/r"), max_age_hours=None, retries=3)
                finally:
                    done.set()

            def later(i):
                j = 0
                while not done.is_set():
                    common.fetch(landing.url(f"/ok/{i}/{j}"), max_age_hours=None)
                    j += 1

            errors = run_threads([first] + [lambda i=i: later(i) for i in range(3)], workers=4)
            rows = sorted(landing.log, key=lambda r: r[1])
            ok("the redirected fetch recovered on its retry and the rest succeeded", not errors, "; ".join(errors[:3]))
            ok("the 503 was answered by the host the redirect landed on",
               any(r[0] == "/boom" and r[3] == 503 for r in rows) and len(rows) > 4, f"{len(rows)} requests")
            ok("no request reached the ANSWERING host during its backoff", not backoff_breaches(rows),
               "; ".join(backoff_breaches(rows)[:3]))
            ok("and the redirector was not held instead (it was asked twice, a gap apart)",
               len(redirector.log) == 2 and not violations(redirector, GAP), f"{len(redirector.log)} requests")
    finally:
        landing.close()
        redirector.close()


SEND_GAP = 1.5   # MIN_GAP_SECONDS for this case, chosen larger than PRE_SEND + LATENCY so that the
PRE_SEND = 0.4   # three candidate stamps - gate entry, send, response end - give three different
LATENCY = 0.6    # arrival spacings and the check can tell them apart


def test_the_gap_starts_when_the_request_is_sent(tmp: str) -> None:
    """The gate stamps the moment the request was SENT (issue #119 C).

    Removing the stamp passed every check in the suite, and it would quietly lengthen every gap in
    every run. This makes the three candidates measurable without CPU contention: a connection that
    takes PRE_SEND to write the request, inside the gate, and a stub that takes LATENCY to answer.
    With the gap at SEND_GAP, arrival-to-arrival at the host is

        SEND_GAP                      = 1.5s   stamped on entry to the gate      (too soon)
        PRE_SEND + SEND_GAP           = 1.9s   stamped when the request was sent (what the gate does)
        PRE_SEND + LATENCY + SEND_GAP = 2.5s   stamped when the response was read (too late: this is
                                               the fallback used when no stamp is taken at all)

    so one two-sided check separates all three. JITTER is set to zero here for the same reason.
    """
    print("the gap is measured from when the request was sent")
    stub = Stub("sent", routes={"/p/": lambda path, n: (200, {}, b"ok" * 200, LATENCY)})
    real_conn, real_mark = common._StampingHTTPPool.ConnectionCls, common._mark_sent
    marks = []

    class SlowToSend(real_conn):
        def request(self, *args, **kwargs):
            time.sleep(PRE_SEND)  # building, connecting and writing, made deterministic
            return super().request(*args, **kwargs)

    try:
        with fresh_state(tmp):
            common.MIN_GAP_SECONDS, common.JITTER_SECONDS = SEND_GAP, 0.0
            common._StampingHTTPPool.ConnectionCls = SlowToSend
            common._mark_sent = lambda: (marks.append(time.monotonic()), real_mark())[1]
            errors = run_threads([lambda i=i: common.fetch(stub.url(f"/p/{i}"), max_age_hours=None) for i in range(4)], workers=4)
        ok("four slow-to-send fetches succeeded", not errors and len(stub.log) == 4, "; ".join(errors[:3]))
        ok("the connection stamped the send of every request", len(marks) == 4, f"{len(marks)} stamps")
        rows = sorted(stub.log, key=lambda r: r[1])
        gaps = [round(b[1] - a[1], 3) for a, b in zip(rows, rows[1:])]
        want = PRE_SEND + SEND_GAP
        ok(f"arrivals are {want}s apart: the gap runs from the send, not from the gate ({SEND_GAP}s) "
           f"and not from the response ({PRE_SEND + LATENCY + SEND_GAP}s)",
           gaps and all(want - 0.15 <= g <= want + 0.25 for g in gaps), f"gaps {gaps}")
        ok(f"no arrival is closer than MIN_GAP {SEND_GAP}s", not violations(stub, SEND_GAP), "; ".join(violations(stub, SEND_GAP)[:2]))
    finally:
        common._StampingHTTPPool.ConnectionCls = real_conn
        common._mark_sent = real_mark
        stub.close()


def test_backoff_with_workers_already_on_the_host(tmp: str) -> None:
    """Issue #119 D: the same backoff property as a black-box, under contention.

    Four workers keep the host busy while two 503s land, so at every release there is a worker
    queued on the gate. What makes this hold is that a hold is written by the thread inside the
    gate, before it releases: a queued worker therefore reads it when it gets in, and no re-check
    while it sleeps is needed.
    """
    print("a backoff with workers already queued on the host")
    routes = {"/flaky": lambda path, n: ((503, {}, b"busy", 0.2) if n in (1, 2) else (200, {}, b"fine", 0.05)),
              "/ok/": lambda path, n: (200, {}, b"fine", 0.05)}
    flaky = Stub("queued", routes=routes)
    try:
        with fresh_state(tmp):
            errors, rows = load_backoff(flaky)
            ok("the flaky fetch recovered and the queue kept moving", not errors, "; ".join(errors[:3]))
            ok("two 503s landed with other workers on the host",
               sum(1 for r in rows if r[3] == 503) == 2 and len(rows) >= 8, f"{len(rows)} requests")
            ok("no worker's request arrived inside either backoff", not backoff_breaches(rows),
               "; ".join(backoff_breaches(rows)[:3]))
    finally:
        flaky.close()


def test_failed_state_write_is_visible(tmp: str) -> None:
    """A refresh-state write that fails every retry is annotated and counted (issue #119 A)."""
    print("a refresh-state write that fails is visible")
    import collegedash

    real_many, real_one = common.update_refresh_state_many, common.update_refresh_state
    real_attempts = collegedash.RECORD_ATTEMPTS
    summary_path = os.path.join(tempfile.mkdtemp(dir=tmp), "summary.md")
    last_run = {}
    attempts = []
    os.environ["GITHUB_ACTIONS"] = "true"
    os.environ["GITHUB_STEP_SUMMARY"] = summary_path
    try:
        collegedash.RECORD_ATTEMPTS = 2
        collegedash.clear_not_recorded()
        common.update_refresh_state_many = lambda entries: attempts.append(entries) or (_ for _ in ()).throw(OSError("disk on fire"))
        common.update_refresh_state = lambda key, info: last_run.setdefault(key, info)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            wrote = collegedash.record_outcomes("p001", {"p001.athletics": {"ok": True}, "p001.news": {"ok": False}})
        printed = out.getvalue()
        ok("record_outcomes reports the failure to its caller", wrote is False)
        ok("it retried RECORD_ATTEMPTS times", len(attempts) == 2, f"{len(attempts)}")
        ok("the program is remembered, with how many entries were lost",
           collegedash.not_recorded()[:1] and collegedash.not_recorded()[0][:2] == ("p001", 2),
           str(collegedash.not_recorded()))
        ok("a ::warning names the program", "::warning title=refresh: refresh-state not recorded for p001::" in printed,
           printed[:200])
        ok("the warning says what is stale and what is not",
           "stale" in printed and "sources are safe" in printed, printed[:200])
        ok("the warning is on a line of its own, with no timestamp prefix",
           any(line.startswith("::warning") for line in printed.splitlines()), printed[:200])

        results = [{"program": "p001", "collector": "athletics", "outcome": "ok", "error": ""},
                   {"program": "p002", "collector": "news", "outcome": "failed", "error": "boom"}]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = collegedash.report_refresh(results, threshold=0.6, mode="daily")
        printed = out.getvalue()
        ok("the run still exits 0: stale metadata is not lost data", code == 0, str(code))
        ok("lastRun carries the count", last_run.get("lastRun", {}).get("notRecorded")
           == {"programs": 1, "entries": 2, "slugs": ["p001"]}, str(last_run.get("lastRun", {}).get("notRecorded")))
        ok("the summary line says it", "refresh-state not recorded for 1 program(s), 2 entries" in printed, printed[:400])
        ok("an aggregate ::warning is annotated", "::warning title=refresh::refresh-state was not recorded for 1 program(s)" in printed,
           printed[:400])
        with open(summary_path, encoding="utf-8") as f:
            summary = f.read()
        ok("and the step summary says it", "refresh-state not recorded for 1 program(s)" in summary, summary[:300])

        collegedash.clear_not_recorded()
        last_run.clear()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            collegedash.report_refresh(results, threshold=0.6, mode="daily")
        zero = last_run.get("lastRun", {}).get("notRecorded")
        ok("with nothing lost, lastRun records zero and nothing is annotated",
           zero == {"programs": 0, "entries": 0, "slugs": []} and "not recorded" not in out.getvalue(), str(zero))
    finally:
        common.update_refresh_state_many, common.update_refresh_state = real_many, real_one
        collegedash.RECORD_ATTEMPTS = real_attempts
        collegedash.clear_not_recorded()
        os.environ.pop("GITHUB_ACTIONS", None)
        os.environ.pop("GITHUB_STEP_SUMMARY", None)


def main() -> int:
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--only", help="comma-separated case names (for mutation runs)")
    args = ap.parse_args()
    VERBOSE = args.verbose
    random.seed(94)
    cases = [test_sequential_unchanged, test_gap_overlap_redirect_crawl_delay, test_gap_under_cpu_load,
             test_the_gap_starts_when_the_request_is_sent, test_body_read_inside_gate, test_backoff,
             test_redirect_backoff_holds_the_answering_host, test_backoff_with_workers_already_on_the_host,
             test_one_request_per_url, test_plan_and_state, test_path_lock, test_failed_state_write_is_visible]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c.__name__ in wanted]
    with tempfile.TemporaryDirectory() as tmp:
        for case in cases:
            try:
                case(tmp)
            except Exception:  # a case that crashes is a failed check, and the other cases still run
                ok(f"{case.__name__} ran to completion", False, traceback.format_exc().strip().splitlines()[-1])
    print(f"\n{TOTAL - len(FAILS)}/{TOTAL} checks passed")
    if FAILS:
        for f in FAILS:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
