"""Per-host politeness under `refresh --workers N` (issue #94), witnessed by the server.

    python tests/refresh_politeness_test.py            # offline: talks only to stub servers on 127.0.0.1
    python tests/refresh_politeness_test.py --verbose  # print every check, not only the failures

The refresh collects many programs at once so that it stops idling in one athletics site's
politeness gap while every other host waits. The promise that makes that acceptable is that no host
sees more or faster traffic than one sequential walk would send it. Nobody watches that promise once
it ships, so this suite checks it from the only side that cannot be fooled: the server's. Each
"host" is a local stub server on its own port (`_host` keys hosts by host:port). The stub records,
for every request it receives, when the request arrived and when its response was sent.

What is checked, all driven through the real collect.common.fetch / robots_allowed from many threads:

  gap/overlap   on every host, requests never overlap (the next one arrives after the previous
                response was sent) and consecutive arrivals are at least MIN_GAP_SECONDS apart;
                a shared host hit by every thread included
  crawl-delay   a host whose robots.txt group for CollegeDashBot asks Crawl-delay gets that spacing,
                not MIN_GAP_SECONDS
  redirects     a redirect hop is a request to the host it lands on: hops onto the shared host are
                spaced and serialised together with direct requests to it
  backoff       after a 503, no worker's request reaches that host until the retry backoff ends
  one per URL   eight threads missing the same URL send one request, not eight
  robots once   eight threads asking about a new host fetch its robots.txt once
  plan order    collegedash.collect_plan returns outcomes in plan order and runs each program's
                collectors in order, identically at 1 and 8 workers

Every politeness check is run twice. The second time the gate (or key lock) is disabled, and the
suite asserts the same checker now REPORTS violations. A checker that cannot fail proves nothing;
this shows each one can.
"""

from __future__ import annotations

import argparse
import contextlib
import http.server
import os
import random
import sys
import tempfile
import threading
import time
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
BACKOFF = 1.0       # BACKOFF_5XX_SECONDS for the suite (production: 5)
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
    """One host: a threaded HTTP server on its own port that records (path, arrived, sent)."""

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
                status, headers, body, latency = stub.respond(self.path, n)
                time.sleep(latency)
                sent = time.monotonic()  # stamped before the last byte goes out: a conservative "end"
                with stub.lock:
                    stub.log.append((self.path, arrived, sent, status))
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

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
    real_polite, real_hold = common._polite, common._hold_host

    @contextlib.contextmanager
    def no_gate(url):
        yield

    common._polite, common._hold_host = no_gate, (lambda url, seconds: None)
    try:
        yield
    finally:
        common._polite, common._hold_host = real_polite, real_hold


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


# ---------- cases ----------

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
            gaps = [b[1] - a[1] for a, b in zip(sorted(delayed.log, key=lambda r: r[1]), sorted(delayed.log, key=lambda r: r[1])[1:])]
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


def load_backoff(flaky: Stub) -> tuple[list[str], list]:
    def first():
        common.fetch(flaky.url("/flaky"), max_age_hours=None, retries=2)

    def later(i):
        time.sleep(0.05)  # let /flaky go first so its 503 lands while these are queued or arriving
        common.fetch(flaky.url(f"/ok/{i}"), max_age_hours=None)

    errors = run_threads([first] + [lambda i=i: later(i) for i in range(6)], workers=7)
    return errors, sorted(flaky.log, key=lambda r: r[1])


def backoff_breaches(rows) -> list[str]:
    """Requests that arrived while a 503's retry backoff should have been holding the host."""
    out = []
    for path, arrived, sent, status in rows:
        if status == 503:
            for p2, a2, _, _ in rows:
                if sent < a2 < sent + BACKOFF - TOL:
                    out.append(f"{p2} arrived {a2 - sent:.3f}s into a {BACKOFF}s backoff")
    return out


def test_backoff(tmp: str) -> None:
    print("backoff holds the host, not just the thread")
    routes = {"/flaky": lambda path, n: ((503, {}, b"busy", 0.02) if n == 1 else (200, {}, b"fine", 0.02))}
    flaky = Stub("flaky", routes=routes)
    try:
        with fresh_state(tmp):
            errors, rows = load_backoff(flaky)
            ok("the flaky fetch recovered on retry and the rest succeeded", not errors, "; ".join(errors[:3]))
            ok("a 503 was served", any(r[3] == 503 for r in rows))
            bad = backoff_breaches(rows)
            ok(f"no request reached the host during the {BACKOFF}s backoff", not bad, "; ".join(bad[:3]))
            ok("no overlap and gaps held around the backoff", not violations(flaky, GAP), "; ".join(violations(flaky, GAP)[:3]))
        flaky.reset()
        with fresh_state(tmp), gate_disabled():
            _, rows = load_backoff(flaky)
            ok("CONTROL: with the hold disabled the checker reports requests inside the backoff",
               len(backoff_breaches(rows)) > 0, f"{len(backoff_breaches(rows))} found")
    finally:
        flaky.close()


def test_one_request_per_url(tmp: str) -> None:
    print("one live request per URL, one robots.txt per host")
    robots_body = b"User-agent: *\nDisallow: /private/\n"
    stub = Stub("same", routes={
        "/robots.txt": lambda path, n: (200, {"Content-Type": "text/plain"}, robots_body, 0.3),
        "/same": lambda path, n: (200, {"Content-Type": "text/html"}, b"<html>same</html>", 0.3),
    })
    try:
        with fresh_state(tmp):
            errors = run_threads([lambda: common.fetch(stub.url("/same"), max_age_hours=6)] * 8, workers=8)
            ok("eight threads fetching one URL all got the body", not errors, "; ".join(errors[:3]))
            ok("eight threads missing one URL sent exactly one request", stub.hits.get("/same") == 1, f"{stub.hits.get('/same')}")
            answers = []
            errors = run_threads([lambda: answers.append(common.robots_allowed(stub.url("/private/x")))] * 8, workers=8)
            ok("eight threads asking robots for a new host fetched robots.txt exactly once",
               stub.hits.get("/robots.txt") == 1, f"{stub.hits.get('/robots.txt')}")
            ok("and every thread got the same, correct verdict", answers == [False] * 8, f"{answers}")
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
            ok("and not slowed beyond gap + jitter + latency (start-to-start, as before)",
               all(g < GAP + JITTER + 0.4 + 0.15 for g in gaps), f"{[round(g, 3) for g in gaps]}")
    finally:
        stub.close()


def test_plan_order() -> None:
    print("collect_plan: order and completeness")
    import collegedash

    real = collegedash.run_collector_outcome
    started: dict[str, list[str]] = {}
    lock = threading.Lock()

    def fake(name, program, registry, **kw):
        with lock:
            started.setdefault(program["slug"], []).append(name)
        time.sleep(random.uniform(0, 0.01))
        outcome = "failed" if (hash(program["slug"] + name) % 7 == 0) else "ok"
        return {"program": program["slug"], "collector": name, "outcome": outcome, "error": ""}

    collegedash.run_collector_outcome = fake
    try:
        plan = [({"slug": f"p{i:03d}"}, ["athletics", "tds", "news", "camps"][: 1 + i % 4]) for i in range(60)]
        seq = collegedash.collect_plan(plan, {}, bios=False, workers=1)
        started.clear()
        par = collegedash.collect_plan(plan, {}, bios=False, workers=8)
        expected = [(p["slug"], c) for p, cs in plan for c in cs]
        ok("sequential outcomes are in plan order", [(r["program"], r["collector"]) for r in seq] == expected)
        ok("8-worker outcomes are identical to sequential, in plan order", par == seq)
        ok("every program ran its collectors in COLLECTORS order", all(started[p["slug"]] == cs for p, cs in plan))
    finally:
        collegedash.run_collector_outcome = real


def main() -> int:
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose
    random.seed(94)
    with tempfile.TemporaryDirectory() as tmp:
        test_sequential_unchanged(tmp)
        test_gap_overlap_redirect_crawl_delay(tmp)
        test_backoff(tmp)
        test_one_request_per_url(tmp)
    test_plan_order()
    print(f"\n{TOTAL - len(FAILS)}/{TOTAL} checks passed")
    if FAILS:
        for f in FAILS:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
