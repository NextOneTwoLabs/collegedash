"""
Shared helpers for CollegeDash collectors: paths, polite HTTP fetching with an on-disk
raw cache, the program registry, per-program source files, and name normalisation.

Layout (mirrors ECNLDash):
  public/            everything the static site serves (Cloudflare output dir = local server root)
  programs/<slug>/   source of truth per program: curated.json (human), sources/*.json (machine)
  data/              cross-program machine data (commitment sweeps)
  .cache/http/       raw HTTP responses (gitignored) so collectors can be re-run offline
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import gzip
import hashlib
import json
import os
import random
import re
import tempfile
import threading
import time
import unicodedata
from urllib import robotparser
from urllib.parse import parse_qsl, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(ROOT, "public")
PUBLIC_DATA_DIR = os.path.join(PUBLIC_DIR, "data")
PROGRAMS_OUT_DIR = os.path.join(PUBLIC_DATA_DIR, "programs")
RPI_OUT_DIR = os.path.join(PUBLIC_DATA_DIR, "rpi")
COMMITS_OUT_DIR = os.path.join(PUBLIC_DATA_DIR, "commitments")
CAMPS_OUT_DIR = os.path.join(PUBLIC_DATA_DIR, "camps")
REGISTRY_PATH = os.path.join(PUBLIC_DATA_DIR, "registry.json")
ARCHIVE_DIR = os.path.join(PUBLIC_DIR, "archive")
REFRESH_STATE_PATH = os.path.join(ARCHIVE_DIR, "refresh-state.json")

PROGRAMS_DIR = os.path.join(ROOT, "programs")
DATA_DIR = os.path.join(ROOT, "data")
COMMITS_DATA_DIR = os.path.join(DATA_DIR, "commitments")
SCHEMA_PATH = os.path.join(ROOT, "schema", "profile.schema.json")
CACHE_DIR = os.path.join(ROOT, ".cache", "http")

# The collector says what it is instead of impersonating a browser (issue #73). A site operator
# reading their logs can tell this traffic from a person's, look the project up at the URL, and --
# because ROBOTS_AGENT below is this same product token -- write a robots.txt rule addressed to us
# that robots_allowed() will actually honour.
#
# This is honesty at a measured cost of zero, and that is the entire case for it. Two independent
# stratified draws from the committed sources -- 49 hosts and 63 -- were each fetched twice at the
# same URL, once with the old Chrome string and once with this one. No host in either answered
# differently to the two agents. A third draw of 100 compared robots.txt itself, likewise with no
# difference.
#
# It does NOT buy coverage back, and the next reader should not reconstruct the argument that it
# does. Eight camp hosts that this collector records as 403 from CI answer 200 to *both* agents
# from an ordinary address, byte-identically. Whatever refuses us in CI is therefore not reading
# the User-Agent. The cause is unknown. Client IP reputation and TLS/JA3 fingerprint are both live
# candidates; the header set and the HTTP version have been excluded. Neither candidate has been
# tested from the refresh runner, which is the one experiment that separates them -- and nothing
# IP-related would fix it if it turns out to be the TLS handshake. An earlier version of this
# comment asserted the User-Agent was the cause; the control falsified it and it was withdrawn.
#
# Shape follows Googlebot/CCBot: product token, version, +URL, plain-language purpose. Deliberately
# not browser-shaped with a project name bolted on, which reads as neither one thing nor the other.
# Bump USER_AGENT_VERSION when the crawl behaviour changes, not per commit. Keep the string here:
# every collector inherits it through DEFAULT_HEADERS and nothing should hand-write a second one.
USER_AGENT_PRODUCT = "CollegeDashBot"
USER_AGENT_VERSION = "1.0"
USER_AGENT_URL = "https://github.com/NextOneTwoLabs/collegedash"
USER_AGENT = (
    f"{USER_AGENT_PRODUCT}/{USER_AGENT_VERSION} "
    f"(+{USER_AGENT_URL}; automated collector for a public college soccer dashboard)"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Politeness: minimum gap between live requests to the same host, plus jitter.
MIN_GAP_SECONDS = float(os.environ.get("COLLEGEDASH_MIN_GAP", "1.2"))
JITTER_SECONDS = 0.8
# fetch() backs off before retrying: 429 = per-minute quotas (Open-Meteo, api.data.gov) need a real
# pause, not a token one; other retryable statuses and network errors get a shorter one.
BACKOFF_429_SECONDS = 25.0
BACKOFF_5XX_SECONDS = 5.0
BACKOFF_NETWORK_SECONDS = 2.0
_last_request_at: dict[str, float] = {}


class FetchError(RuntimeError):
    """A fetch that failed. `status` is the HTTP status that ended it (None for a network error or an
    offline miss) and `final_url` the URL that answered after redirects, so a caller can stop a host
    at its first 403/429 (issue #276) without parsing the message."""

    def __init__(self, msg: str = "", *, status: int | None = None, final_url: str | None = None):
        super().__init__(msg)
        self.status = status
        self.final_url = final_url


class SkipCollector(RuntimeError):
    """Raised by a collector when there is nothing to collect for this program (no Wikipedia
    article, no TopDrawerSoccer id, roster needs a browser). Recorded as ok+skipped, not as
    a failure, so `refresh --failed` and the dashboard do not keep nagging about it."""


# ---------- secrets in error and log text (issue #258) ----------

# Env vars holding credentials a collector sends. Their values are replaced literally wherever they
# appear in error or log text, as a backstop to the parameter rule below.
SECRET_ENV_VARS = ("SCORECARD_API_KEY",)
REDACTED = "REDACTED"
_SECRET_PARAM_RE = re.compile(
    r"(?i)((?:[?&;]|%3F|%26)"  # the delimiter before the name; %3F/%26 for a URL nested (encoded) in another
    r"(?:api[_-]?key|apikey|key|access_token|auth_token|client_secret|token|secret|password|passwd|pwd"
    r"|signature|sig)"
    r"(?:=|%3D))"
    r"(?:(?!%26|%23)[^&#\s\"'()<>])*")  # the value ends at & # whitespace quotes ( ) < > or an encoded & #
_USERINFO_RE = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s@:]+:[^/\s@]+@")


def redact(text) -> str:
    """`text` with credential values removed: the value of any key/token/secret/password-like URL
    parameter, the user:password of a URL, and the literal value of each SECRET_ENV_VARS variable that
    is set and at least 8 characters long (a short or empty value would redact ordinary text). For
    error and log text only, never data fields. Redact before truncating: a cut can split the
    parameter name and hide the value from the rule."""
    s = "" if text is None else str(text)
    for name in SECRET_ENV_VARS:
        v = os.environ.get(name) or ""
        if len(v) >= 8 and v in s:
            s = s.replace(v, REDACTED)
    s = _SECRET_PARAM_RE.sub(lambda m: m.group(1) + REDACTED, s)
    return _USERINFO_RE.sub(lambda m: m.group(1) + REDACTED + "@", s)


def error_text(e, limit: int) -> str:
    """str(e) redacted, then cut to `limit` characters: what any error stored or printed goes through."""
    return redact(str(e))[:limit]


# ---------- time ----------

def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    return _dt.date.today().isoformat()


_log_lock = threading.Lock()
_log_context = threading.local()


def set_log_context(label: str | None) -> None:
    """Prefix this thread's log lines with `label` (a program slug under `refresh --workers N`, where
    lines from different programs interleave). None clears it; the sequential path never sets it."""
    _log_context.label = label


def log_traceback() -> None:
    """Print the current exception's traceback to stderr as one block, each line prefixed with this
    thread's log label (the program slug under refresh --workers N), so it cannot interleave with
    another worker's lines and says whose it is. Without a label it prints exactly what
    traceback.print_exc() did."""
    import sys
    import traceback
    label = getattr(_log_context, "label", None)
    text = redact(traceback.format_exc())
    if label:
        text = "".join(f"{label} | {line}\n" for line in text.rstrip("\n").split("\n"))
    with _log_lock:
        sys.stderr.write(text)
        sys.stderr.flush()


def annotate(line: str) -> None:
    """Print a GitHub Actions workflow command (`::warning ...`) on its own line: no timestamp
    prefix, which Actions would not parse, and under the log lock so a worker thread cannot split
    it across another thread's output."""
    line = redact(line)
    with _log_lock:
        print(line, flush=True)


def log(msg: str) -> None:
    label = getattr(_log_context, "label", None)
    line = f"[{_dt.datetime.now().strftime('%H:%M:%S')}] " + (f"{label} | " if label else "") + redact(msg)
    with _log_lock:  # print() writes the text and the newline separately; threads must not split them
        print(line, flush=True)


# ---------- JSON files ----------

def read_json(path: str, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, obj, *, sort_keys: bool = False) -> str:
    """Atomically write pretty JSON (UTF-8, trailing newline). The temp file name is unique per
    writer so two processes (serve + refresh, onboard --all + refresh) never share one."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False, sort_keys=sort_keys)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise
    return path


_path_locks: dict[str, threading.Lock] = {}
_path_locks_lock = threading.Lock()


@contextlib.contextmanager
def _locked(path: str, *, timeout: float = 15.0, stale_after: float = 60.0):
    """Cross-process lock around a read-modify-write of `path` (lock file = path + '.lock',
    created with O_EXCL). A lock older than `stale_after` seconds is treated as abandoned.

    Threads of one process (refresh --workers N) first take an in-process lock for the path, so only
    one of them at a time contends for the lock file. Measured without it on Windows: a thread's
    O_EXCL create racing another thread's delete of the lock file raises PermissionError (the file is
    delete-pending), not FileExistsError, and the refresh crashed within two minutes. PermissionError
    is also treated as "held" below, which covers the same race between two processes (serve +
    refresh) that predates the workers.

    The in-process lock has NO timeout, on purpose (PR #105 review). A queue of N workers on a large
    file can wait longer than any fixed bound, and a timeout there turned successful collector runs
    into recorded failures and crashed 32- and 64-worker runs. A thread only ever waits here for
    another thread of this process that is making progress. `timeout` still bounds the wait for the
    lock FILE, i.e. for another process, which is what it was written for."""
    with _path_locks_lock:
        plock = _path_locks.setdefault(os.path.abspath(path), threading.Lock())
    plock.acquire()
    try:
        with _file_locked(path, timeout=timeout, stale_after=stale_after):
            yield
    finally:
        plock.release()


@contextlib.contextmanager
def _file_locked(path: str, *, timeout: float, stale_after: float):
    lock = path + ".lock"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except (FileExistsError, PermissionError):
            try:
                if time.time() - os.path.getmtime(lock) > stale_after:
                    os.remove(lock)
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError(f"could not lock {path} within {timeout}s (stale {lock}?)")
            time.sleep(0.05)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            os.remove(lock)


# ---------- HTTP with raw cache ----------

def _cache_key(method: str, url: str, body: str | None) -> str:
    h = hashlib.sha1()
    h.update(method.encode())
    h.update(url.encode())
    if body:
        h.update(body.encode())
    return h.hexdigest()


def _host(url: str) -> str:
    return re.sub(r"^https?://([^/]+).*$", r"\1", url).lower()  # lower-cased: _host_delay is keyed by lower-cased host


def forget_cached(url: str, *, method: str = "GET", json_body=None) -> bool:
    """Remove a URL's `.cache/http` entry (body and meta). Used when a fetch turns out to be one we
    should not keep, e.g. a redirect onto a host whose robots.txt disallows crawling. True when
    something was removed."""
    body_str = json.dumps(json_body, sort_keys=True) if json_body is not None else None
    key = _cache_key(method, url, body_str)
    removed = False
    with _key_lock(key):  # never while another thread is reading or writing this entry
        for name in (key + ".body.gz", key + ".body", key + ".json"):
            path = os.path.join(CACHE_DIR, name)
            if os.path.exists(path):
                os.remove(path)
                removed = True
    return removed


# ---------- per-host politeness gate (issue #94) ----------
# Every live request, and every redirect hop inside one, passes through the gate of the host it
# actually contacts. The gate is a lock held for the whole request -- body included -- so two requests
# to one host never overlap, plus the same gap the sequential collector always kept:
# max(MIN_GAP_SECONDS, that host's Crawl-delay) + uniform(0, JITTER_SECONDS).
#
# The gap is measured from the moment the previous request finished SENDING, not from when it was
# allowed to start (PR #105 review). Building, connecting and sending all need the GIL, so with other
# threads parsing pages the time between "allowed to start" and "bytes on the wire" varies by hundreds
# of milliseconds; measured from the earlier stamp, a host saw 13 of 99 intervals under 1.2 s, the
# shortest 0.765 s. The later stamp is taken by the urllib3 connection itself right after the request
# is written (_StampingHTTPConnection). The next request cannot start before that stamp + gap, so the
# host cannot see two requests closer than the gap, network jitter aside. Where no stamp is taken (a
# proxy, an error part-way) the moment the request finished is used instead, which is later still.
# Measuring from the response END instead would put shared hosts at latency + gap (~1.9-2.0 s); the
# send stamp costs next to nothing.
#
# A sequential run therefore behaves as before, only fractionally more spaced (a redirect hop now
# waits its gap too), and `refresh --workers N` can run programs side by side without any host
# receiving two requests at once or two requests closer than that gap.
#
# What this does NOT preserve: in a sequential walk a host every program uses (TopDrawerSoccer,
# SoccerWire) was visited once per program, i.e. about every 16-19 s on a daily run, far slower than
# the gap requires. With workers those hosts receive the same number of requests at the gap itself,
# about one every 1.7 s. Raising a shared host's spacing is a policy choice with a direct cost in wall
# time (issue #94 has the numbers); the gate is where it would be set.
#
# Backoffs after a 429/5xx or a network error are recorded on the gate of the host that answered (the
# hop, not the URL the caller asked for), inside the gate, before it is released. Sequentially that
# sleep paused the whole process and nobody touched the host meanwhile; with workers another thread is
# usually already queued on the gate, and a hold recorded after release would race it. Because every
# write to `not_before` happens under the gate lock, a thread waiting in the gate is never overtaken by
# a hold recorded while it sleeps, so the wait needs no re-check.
#
# The gap is per process. Two refresh processes at once (not something the workflow does: its
# concurrency group forbids it) would each keep their own gates, exactly as before this change.
#
# A robots.txt check (issue #101, deliberately not done here) would go in _PoliteAdapter.send, before
# the gate: it sees the first request and every redirect hop, keyed by the host actually contacted.

RETRY_STATUSES = (429, 500, 502, 503, 504)


class _HostGate:
    __slots__ = ("lock", "last", "not_before")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last: float | None = None      # when the previous request finished sending
        self.not_before = 0.0               # a backoff; written only while `lock` is held


_gates: dict[str, _HostGate] = {}
_gates_lock = threading.Lock()
_sending = threading.local()   # the request this thread is sending: .gate, .sent_at
_retry = threading.local()     # fetch()'s attempt number (1-based), so the gate can scale a backoff

# A caller-scoped host veto (issue #284). A caller that must never send a request to certain hosts -
# camps, for the camp hosts that refused it with a 403/429 - installs a guard with host_guard() around
# its own fetch. _PoliteAdapter.send consults it INSIDE the host gate, for the first request and every
# redirect hop: every hop, because a link on one host that redirects onto a recorded host must not
# reach it; inside the gate, because workers heading for one host are serialised there, so the second
# sees what the first one's answer recorded. guard.before(host, url) returns a reason to refuse
# (nothing is sent; HostRefused is raised) or None; guard.after(host, url, status) sees every answer
# while the gate is still held. Fetches made without a guard - every other collector, robots.txt - are
# unaffected.
_host_guard = threading.local()


class HostRefused(FetchError):
    """A request the thread's host guard vetoed: nothing was sent to that host."""


@contextlib.contextmanager
def host_guard(guard):
    prev = getattr(_host_guard, "guard", None)
    _host_guard.guard = guard
    try:
        yield
    finally:
        _host_guard.guard = prev


def _gate(host: str) -> _HostGate:
    with _gates_lock:
        g = _gates.get(host)
        if g is None:
            g = _gates[host] = _HostGate()
        return g


def _mark_sent() -> None:
    """Called by the connection once a request has been written to the socket."""
    if getattr(_sending, "gate", None) is not None:
        _sending.sent_at = time.monotonic()


@contextlib.contextmanager
def _polite(url: str):
    """Hold `url`'s host for one request: wait for its turn, then keep every other thread off the host
    until the block exits. Yields the gate so the caller can record a backoff while still holding it."""
    host = _host(url)
    g = _gate(host)
    with g.lock:
        wait_until = g.not_before
        if g.last is not None:
            gap = max(MIN_GAP_SECONDS, _host_delay.get(host, 0.0)) + random.uniform(0, JITTER_SECONDS)
            wait_until = max(wait_until, g.last + gap)
        delay = wait_until - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        _sending.gate, _sending.sent_at = g, None
        try:
            yield g
        finally:
            sent = _sending.sent_at
            _sending.gate = _sending.sent_at = None
            g.last = _last_request_at[host] = sent if sent is not None else time.monotonic()


def _hold(g: _HostGate, seconds: float) -> None:
    """Keep every thread off gate `g`'s host for `seconds` from now. Call only inside _polite."""
    g.not_before = max(g.not_before, time.monotonic() + seconds)


def _backoff_seconds(status: int | None) -> float:
    """The retry pause for a response status (None = a network error), scaled by fetch()'s attempt."""
    attempt = getattr(_retry, "attempt", 1)
    if status is None:
        base = BACKOFF_NETWORK_SECONDS
    elif status == 429:
        base = BACKOFF_429_SECONDS
    else:
        base = BACKOFF_5XX_SECONDS
    return base * attempt


class _StampingHTTPConnection(HTTPConnection):
    def request(self, *args, **kwargs):
        try:
            return super().request(*args, **kwargs)
        finally:
            _mark_sent()


class _StampingHTTPSConnection(HTTPSConnection):
    def request(self, *args, **kwargs):
        try:
            return super().request(*args, **kwargs)
        finally:
            _mark_sent()


class _StampingHTTPPool(HTTPConnectionPool):
    ConnectionCls = _StampingHTTPConnection


class _StampingHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _StampingHTTPSConnection


class _PoliteAdapter(HTTPAdapter):
    """requests transport that passes each request -- the first and every redirect hop, since
    Session.resolve_redirects sends each hop through the adapter -- through its host's gate."""

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _StampingHTTPPool, "https": _StampingHTTPSPool}

    def send(self, request, **kwargs):
        guard = getattr(_host_guard, "guard", None)
        with _polite(request.url) as g:
            if guard is not None:
                why = guard.before(_host(request.url), request.url)
                if why:
                    raise HostRefused(why, final_url=request.url)
            try:
                resp = super().send(request, **kwargs)
                if resp.status_code in RETRY_STATUSES:
                    _hold(g, _backoff_seconds(resp.status_code))
                if not kwargs.get("stream"):
                    resp.content  # read the body while the host is still held; Session reads it later otherwise
            except requests.RequestException:
                _hold(g, _backoff_seconds(None))
                raise
            if guard is not None:
                guard.after(_host(request.url), request.url, resp.status_code)
            return resp


def _session() -> requests.Session:
    """A fresh Session per call, as requests.request() uses internally, with the polite transport."""
    s = requests.Session()
    adapter = _PoliteAdapter()
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


# One live fetch per cache key at a time: two workers that miss the same URL must not both request it
# (more traffic than a sequential run, where the second would have hit the first one's cache), and a
# reader must not see a body another thread is writing. Locks are created on demand and kept.
_key_locks: dict[str, threading.Lock] = {}
_key_locks_lock = threading.Lock()


def _key_lock(key: str) -> threading.Lock:
    with _key_locks_lock:
        lk = _key_locks.get(key)
        if lk is None:
            lk = _key_locks[key] = threading.Lock()
        return lk


# ---------- robots.txt ----------
# Hosts outside the athletics sites (camp vendors, coaches' own sites) are checked against their
# robots.txt before a request is made. Cached per host for the life of the process (never on disk,
# so a denied host leaves no trace in .cache/http; a redirect onto a denied host is fetched once and
# the entry is then removed with forget_cached). A Crawl-delay that applies to us raises that host's
# gap between requests above MIN_GAP_SECONDS.
#
# Rules are evaluated as our own product token, not as '*' (issue #73). Once the User-Agent names
# the project a site operator can write a group addressed to CollegeDashBot, and ignoring it would
# be worse than the anonymity it replaced: we would have advertised an identity and then disregarded
# instructions given to it. Token only, no '/1.0': that is what a robots.txt group is written
# against.
#
# What urllib.robotparser actually guarantees, verified against the CPython source and pinned in
# tests/robots_ua_test.py: a group naming us beats the '*' group, for can_fetch and crawl_delay
# alike. That single guarantee is what this change rests on, and it is enough -- before it, a group
# addressed to us was never consulted at all.
#
# It is NOT full RFC 9309 precedence. Four gaps, all pre-existing library behaviour and none a
# regression introduced here (the rule-line ones behaved identically when ROBOTS_AGENT was '*'):
#   * Agent match is substring, not token (Entry.applies_to does `agent in useragent`), so
#     'User-agent: bot', 'dash' or 'college' now apply to us where we used to fall through to '*'.
#     This is the only gap this change newly exposes us to.
#   * Among named groups the FIRST in file order wins, not the most specific (RFC 9309 2.2.1). A
#     loose 'User-agent: bot' group listed above a 'User-agent: CollegeDashBot' group hides the one
#     naming us exactly -- so this gap fails OPEN.
#   * Within a group the FIRST matching rule line wins, not the longest path (RFC 9309 2.2.2). The
#     ordinary operator carve-out 'Disallow: /' then 'Allow: /camps/' therefore denies /camps/
#     (fails closed), while 'Allow: /' then 'Disallow: /admin/' permits /admin/ (fails open).
#   * No path wildcards at all: RuleLine.applies_to is a plain startswith, so 'Disallow: /*.pdf$'
#     matches nothing and is silently ignored. Fails open.
# Sampled three times for issue #73 -- 187 hosts, then 63, then 100 -- and no robots.txt in any of
# them names us or any substring of our token, so none of the four gaps changes a verdict on the web
# as it stands. Those are samples of a 604-host frame, not the frame. Fixing the gaps means a real
# resolver with its own test matrix, including the wildcard support none of this has, so it is
# tracked as a follow-up rather than bolted onto this change.
_robots: dict[str, "robotparser.RobotFileParser"] = {}
_host_delay: dict[str, float] = {}
ROBOTS_AGENT = USER_AGENT_PRODUCT


def set_robots_txt(host: str, text: str | None) -> None:
    """Seed the robots cache for `host` (tests, offline runs). None = no robots.txt (allow all)."""
    rp = robotparser.RobotFileParser()
    if text is None:
        rp.allow_all = True
    else:
        rp.parse(text.splitlines())
    _robots[host] = rp
    _apply_crawl_delay(host, rp)


def _apply_crawl_delay(host: str, rp) -> None:
    try:
        delay = rp.crawl_delay(ROBOTS_AGENT)
    except Exception:  # robotparser raises on a parser that has not been fed
        delay = None
    if delay and float(delay) > MIN_GAP_SECONDS:
        _host_delay[host] = min(float(delay), 30.0)
        log(f"robots: {host} asks Crawl-delay {delay}s; using {_host_delay[host]:.0f}s between requests")


def _load_robots(host: str, scheme: str) -> "robotparser.RobotFileParser":
    rp = robotparser.RobotFileParser()
    if os.environ.get("COLLEGEDASH_OFFLINE"):
        rp.disallow_all = True  # unknown = do not fetch
        return rp
    url = f"{scheme}://{host}/robots.txt"
    try:
        with _session() as s:
            resp = s.get(url, headers=DEFAULT_HEADERS, timeout=20)
    except requests.RequestException as e:
        log(f"robots: {host} unreachable ({type(e).__name__}); treating as disallowed")
        rp.disallow_all = True
        return rp
    if 200 <= resp.status_code < 300:
        rp.parse(resp.text.splitlines())
    elif 400 <= resp.status_code < 500:
        # No robots.txt = no restrictions. Note this fails OPEN, and that this request carries the
        # same User-Agent as everything else: a host that served robots.txt to the old Chrome string
        # but refused our token would silently lose its rules rather than fail loudly. Measured
        # before shipping the rename (issue #73) across 100 hosts stratified over the four vendor
        # families -- 91 x 200, 6 x 404, 3 connection failures, and *zero* hosts where the status
        # differed between the two agents, so the risk is real in principle and absent in practice.
        # Worth re-checking if 4xx rates on robots.txt ever climb after an agent change.
        rp.allow_all = True
    else:
        log(f"robots: {host} returned HTTP {resp.status_code}; treating as disallowed")
        rp.disallow_all = True
    return rp


def robots_allowed(url: str) -> bool:
    """True when `url` may be fetched under the host's robots.txt, evaluated as ROBOTS_AGENT --
    the product token this collector puts in its User-Agent -- falling back to the '*' group when
    no group names us.

    Named-over-'*' is the only precedence urllib.robotparser implements. Among named groups the
    first in file order wins rather than the most specific; within a group the first matching rule
    line wins rather than the longest path, so an 'Allow:' carve-out written after a blanket
    'Disallow: /' is not honoured; agent matching is substring; and path wildcards are unsupported.
    See the notes above ROBOTS_AGENT for which of those fail open and which fail closed.

    4xx = allowed; unreachable or 5xx = disallowed. Records the host's Crawl-delay for the host's
    politeness gate (_polite)."""
    m = re.match(r"^(https?)://([^/]+)", url)
    if not m:
        return False
    scheme, host = m.group(1), m.group(2).lower()
    rp = _robots.get(host)
    if rp is None:
        with _key_lock("robots:" + host):  # once per host: a second worker waits for the first's answer
            rp = _robots.get(host)
            if rp is None:
                rp = _load_robots(host, scheme)
                _apply_crawl_delay(host, rp)  # before publishing rp: a worker that sees the parser also sees its delay
                _robots[host] = rp
    return rp.can_fetch(ROBOTS_AGENT, url)


def fetch(
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    json_body=None,
    max_age_hours: float | None = 6.0,
    retries: int = 3,
    timeout: int = 60,
    allow_status: tuple[int, ...] = (200,),
) -> tuple[bytes, dict]:
    """Fetch a URL, serving from `.cache/http` when a copy younger than `max_age_hours`
    exists. Returns (body_bytes, meta) where meta has url, status, fetchedAt, fromCache.

    Set max_age_hours=None to force a live request; 0 also forces live.
    Set the env var COLLEGEDASH_OFFLINE=1 to refuse live requests (cache only).

    Thread-safe: the cache check, the live request and the cache write for one key run under that
    key's lock, and the live request itself under its host's politeness gate.
    """
    body_str = json.dumps(json_body, sort_keys=True) if json_body is not None else None
    key = _cache_key(method, url, body_str)
    with _key_lock(key):
        return _fetch_locked(url, key, body_str, method=method, headers=headers, json_body=json_body,
                             max_age_hours=max_age_hours, retries=retries, timeout=timeout,
                             allow_status=allow_status)


def _fetch_locked(url, key, body_str, *, method, headers, json_body, max_age_hours, retries, timeout,
                  allow_status) -> tuple[bytes, dict]:
    os.makedirs(CACHE_DIR, exist_ok=True)
    body_path = os.path.join(CACHE_DIR, key + ".body")
    meta_path = os.path.join(CACHE_DIR, key + ".json")

    # Bodies are stored gzip-compressed (<key>.body.gz); plain <key>.body files from older runs are
    # still readable. Athletics pages are 1-1.5 MB of HTML each and compress about 10x.
    gz_path = body_path + ".gz"
    stored = gz_path if os.path.exists(gz_path) else body_path if os.path.exists(body_path) else None
    if stored and os.path.exists(meta_path):
        meta = read_json(meta_path, {})
        age_h = (time.time() - os.path.getmtime(stored)) / 3600.0
        # a cached error page (e.g. a 404 kept by a probe with allow_status) must not satisfy a caller
        # that only accepts 200
        status_ok = meta.get("status", 200) in allow_status
        if status_ok and ((max_age_hours and age_h <= max_age_hours) or os.environ.get("COLLEGEDASH_OFFLINE")):
            meta["fromCache"] = True
            if stored.endswith(".gz"):
                with gzip.open(stored, "rb") as f:
                    return f.read(), meta
            with open(stored, "rb") as f:
                return f.read(), meta

    if os.environ.get("COLLEGEDASH_OFFLINE"):
        raise FetchError(f"offline and not cached: {redact(url)}")

    hdrs = dict(DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)
    if json_body is not None:
        hdrs.setdefault("Content-Type", "application/json")

    last_err: Exception | None = None
    for attempt in range(retries):
        _retry.attempt = attempt + 1  # the gate scales the answering host's hold by it
        try:
            with _session() as s:  # what requests.request() does, plus the per-host gate on every hop
                resp = s.request(method, url, headers=hdrs, data=body_str, timeout=timeout)
        except requests.RequestException as e:  # network; the host that failed is already held
            last_err = e
            time.sleep(_backoff_seconds(None))  # and this thread pauses too, as it always did
            continue
        finally:
            _retry.attempt = 1
        if resp.status_code in allow_status:
            meta = {"url": url, "status": resp.status_code, "fetchedAt": now_iso(), "fromCache": False,
                    "contentType": resp.headers.get("Content-Type", ""), "finalUrl": resp.url}
            # temp file + os.replace, like write_json: a reader never sees a half-written body
            fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, prefix=key + ".", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as raw, gzip.GzipFile(filename="", mode="wb", compresslevel=6,
                                                               fileobj=raw) as f:
                    f.write(resp.content)
                os.replace(tmp, gz_path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.remove(tmp)
                raise
            if os.path.exists(body_path):
                os.remove(body_path)
            write_json(meta_path, meta)
            return resp.content, meta
        if resp.status_code in RETRY_STATUSES:
            last_err = FetchError(f"HTTP {resp.status_code} for {redact(url)}", status=resp.status_code,
                                  final_url=resp.url)
            # 429: per-minute quotas (Open-Meteo, api.data.gov) need a real pause, not a token one. The
            # gate already holds the host that answered for this long; this thread pauses with it.
            _retry.attempt = attempt + 1
            time.sleep(_backoff_seconds(resp.status_code))
            _retry.attempt = 1
            continue
        raise FetchError(f"HTTP {resp.status_code} for {redact(url)}", status=resp.status_code, final_url=resp.url)
    raise FetchError(f"giving up after {retries} attempts: {redact(last_err)}",  # last_err names the URL
                     status=getattr(last_err, "status", None), final_url=getattr(last_err, "final_url", None))


def fetch_text(url: str, **kw) -> tuple[str, dict]:
    body, meta = fetch(url, **kw)
    return body.decode("utf-8", "replace"), meta


def fetch_json(url: str, **kw):
    body, meta = fetch(url, **kw)
    return json.loads(body.decode("utf-8", "replace")), meta


# ---------- registry ----------

def load_registry() -> dict:
    reg = read_json(REGISTRY_PATH)
    if reg is None:
        raise FileNotFoundError(f"missing registry: {REGISTRY_PATH}")
    return reg


def final_rpi_dates(registry: dict) -> dict[int, str]:
    """season -> registry.season.finalRpiThrough[season]: the through-date of the NCAA table that
    includes the D1 College Cup final, entered by a person once a year (issue #249). A season is
    final - for every division, one site-wide switch - once a weekly snapshot of it is dated on or
    after this date.

    Raises on a malformed or out-of-range date (outside Nov 15 of the season to Jan 31 of the next)
    rather than ignoring it: one typo here would finish, or never finish, 1,011 programs at once."""
    raw = ((registry or {}).get("season") or {}).get("finalRpiThrough") or {}
    if not isinstance(raw, dict):
        raise ValueError(f"registry season.finalRpiThrough must be an object of season -> date, got {raw!r:.60}")
    out = {}
    for key, val in raw.items():
        if str(key).startswith("_"):
            continue
        try:
            season, day = int(key), _dt.date.fromisoformat(str(val))
        except ValueError:
            raise ValueError(f"registry season.finalRpiThrough[{key!r}] = {val!r} is not a season -> YYYY-MM-DD date") from None
        lo, hi = _dt.date(season, 11, 15), _dt.date(season + 1, 1, 31)
        if not lo <= day <= hi:
            raise ValueError(f"registry season.finalRpiThrough[{key!r}] = {val} is outside {lo} .. {hi}; "
                             f"the {season} College Cup final cannot fall there, so this is a typo")
        out[season] = day.isoformat()
    return out


def is_final_rpi(registry: dict, season: int, through: str | None) -> bool:
    """True when an NCAA table of `season` dated `through` includes the College Cup final."""
    date = final_rpi_dates(registry).get(season)
    return bool(date and through and str(through)[:10] >= date)


def save_registry(reg: dict) -> None:
    reg["updated"] = today()
    write_json(REGISTRY_PATH, reg)


def update_registry(mutate) -> dict:
    """Read-modify-write the registry under a lock: `mutate(reg)` edits it in place. Returns the
    freshly saved registry. Use this instead of load/save pairs so concurrent processes
    (onboard --all, refresh, serve) never overwrite each other's changes."""
    with _locked(REGISTRY_PATH):
        reg = load_registry()
        mutate(reg)
        save_registry(reg)
    return reg


def get_program(slug: str, reg: dict | None = None) -> dict:
    reg = reg or load_registry()
    for p in reg["programs"]:
        if p["slug"] == slug:
            return p
    raise KeyError(f"unknown program slug: {slug}")


def iter_programs(reg: dict | None = None, onboarded_only: bool = True):
    reg = reg or load_registry()
    for p in reg["programs"]:
        if onboarded_only and not p.get("onboarded"):
            continue
        yield p


# ---------- per-program source files ----------

def program_dir(slug: str) -> str:
    return os.path.join(PROGRAMS_DIR, slug)


def source_path(slug: str, name: str) -> str:
    return os.path.join(program_dir(slug), "sources", f"{name}.json")


def save_source(slug: str, name: str, data, *, url: str, collector: str, extra: dict | None = None) -> str:
    """Write programs/<slug>/sources/<name>.json with provenance envelope."""
    env = {"collector": collector, "sourceUrl": url, "fetchedAt": now_iso()}
    if extra:
        env.update(extra)
    env["data"] = data
    return write_json(source_path(slug, name), env)


def load_source(slug: str, name: str) -> dict | None:
    return read_json(source_path(slug, name))


def load_curated(slug: str) -> dict:
    return read_json(os.path.join(program_dir(slug), "curated.json"), {}) or {}


def load_reviewed(slug: str) -> dict:
    return read_json(os.path.join(program_dir(slug), "commitments.reviewed.json"),
                     {"approved": [], "rejected": [], "merges": [], "statusOverrides": {}}) or {}


# ---------- refresh state ----------

def update_refresh_state(key: str, info: dict) -> None:
    update_refresh_state_many({key: info})


def update_refresh_state_many(entries: dict[str, dict]) -> None:
    """Record several refresh-state entries in one locked read-modify-write. An entry that already
    carries "at" keeps it (the time its collector finished); the others are stamped now. `refresh`
    records each program's collectors with one call: the file is ~300 KB at 350 programs and ~800 KB
    at 1,050, and rewriting it once per collector run is what made the lock contended (PR #105)."""
    with _locked(REFRESH_STATE_PATH):
        state = read_json(REFRESH_STATE_PATH, {}) or {}
        stamp = now_iso()
        for key, info in entries.items():
            entry = dict(info)
            entry.setdefault("at", stamp)
            state[key] = entry
        state["updated"] = stamp
        write_json(REFRESH_STATE_PATH, state)


def load_refresh_state() -> dict:
    return read_json(REFRESH_STATE_PATH, {}) or {}


# ---------- link-rewriting wrappers (issue #160) ----------
# Some schools paste links into their CMS from Outlook, which has rewritten them into Microsoft
# Defender "Safe Links": https://<region>.safelinks.protection.outlook.com/?url=<real URL>&data=...
# The real URL is the percent-encoded `url` query parameter (Microsoft's documented format); `data`
# carries the mailbox that received the message. Stored as-is, such a link sends visitors through
# Microsoft's redirector and publishes a staff address. Measured over every stored source on main
# (2,948 files): 17 wrapped URLs, all Safe Links (13 california-state-los-angeles schedule "watch"
# links, 3 clemson camp registerUrls, 1 old-dominion "live stats" link), and no Proofpoint
# urldefense or Check Point protect.checkpoint wrapper - so those are not unwrapped here.
# office365.us is the same service for US government tenants.
SAFELINKS_HOST_RE = re.compile(r"(?:^|\.)safelinks\.protection\.(?:outlook\.com|office365\.us)$", re.I)
_SAFELINKS_IN_TEXT_RE = re.compile(r"https?://[A-Za-z0-9.-]*safelinks\.protection\.(?:outlook\.com|office365\.us)"
                                   r"(?::\d+)?/[^\s\"'<>]*", re.I)
_DROP = object()


def is_wrapped_link(url) -> bool:
    """True when `url` is a Safe Links wrapper (whatever it decodes to)."""
    if not isinstance(url, str):
        return False
    try:
        host = urlsplit(url.strip()).hostname or ""
    except ValueError:
        return False
    return bool(SAFELINKS_HOST_RE.search(host))


def unwrap_link(url: str | None) -> str | None:
    """The real target of a Safe Links wrapper; any other value comes back unchanged.

    A wrapper whose `url` parameter is missing, or does not decode to an absolute http(s) URL, gives
    None: the caller stores no link rather than the wrapper. A wrapper around a wrapper is unwrapped
    all the way down."""
    for _ in range(5):
        if not is_wrapped_link(url):
            return url
        try:
            targets = [v for k, v in parse_qsl(urlsplit(url.strip()).query, keep_blank_values=True) if k.lower() == "url"]
            target = targets[0].strip() if targets else ""
            parts = urlsplit(target)
        except ValueError:
            return None
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return None
        url = target
    return None  # still wrapped after five layers: not a link worth storing


def unwrap_links(obj):
    """A copy of `obj` (JSON-shaped) with every Safe Links wrapper replaced by its target.

    A string that is a wrapper becomes its target; one that does not decode is removed from a
    `links` mapping (label -> URL, where a null would render as an empty link) and from lists, and
    becomes None anywhere else. A wrapper inside longer text (a bio paragraph) is replaced in place by
    its target, or removed from the text. Everything else is returned as it was."""
    out = _unwrap(obj, None)
    return None if out is _DROP else out


def _unwrap(v, key):
    if isinstance(v, str):
        if is_wrapped_link(v) and not any(c.isspace() for c in v.strip()):
            target = unwrap_link(v)
            return _DROP if target is None else target
        if "safelinks" in v.lower():
            return _SAFELINKS_IN_TEXT_RE.sub(lambda m: unwrap_link(m.group(0)) or "", v)
        return v
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            nx = _unwrap(x, k)
            if nx is _DROP:
                if key == "links":
                    continue
                nx = None
            out[k] = nx
        return out
    if isinstance(v, list):
        return [nx for nx in (_unwrap(x, key) for x in v) if nx is not _DROP]
    return v


# ---------- text helpers ----------

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_name(s: str) -> str:
    """Normalise a person's name for matching: lowercase, no accents/punctuation, single spaces.
    'Sadie Leal-Schuman' -> 'sadie leal schuman'."""
    s = strip_accents(s or "").lower().replace("-", " ").replace("'", "").replace(".", "")
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def slugify(s: str) -> str:
    s = strip_accents(s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def clean(s: str | None) -> str:
    if s is None:
        return ""
    return _WS.sub(" ", s.replace("\xa0", " ")).strip()


# A missing value some sites print as a word (#224): Sidearm's roster template writes 'Columbus, Ga. / null' for a
# player with no high school, a Club cell reads 'None', SoccerWire's state reads 'None'. Never a real value here.
PLACEHOLDER_WORDS = frozenset({"null", "undefined", "none", "nan"})
_SLASH_PARTS = re.compile(r"(?:^|\s+)/(?:\s+|$)")  # ' / ' between parts, or a bare '/' at an end; never '5/7'



def drop_placeholders(s: str | None) -> str:
    """The text with placeholder words treated as absent: a whole value that is one ('null' -> ''), and a part of a
    ' / '-joined value that is one ('Columbus, Ga. / null' -> 'Columbus, Ga.'). A value with no placeholder is returned
    cleaned and otherwise unchanged."""
    text = clean(s)
    parts = [clean(x) for x in _SLASH_PARTS.split(text)]
    if not any(p.lower() in PLACEHOLDER_WORDS for p in parts):
        return text  # nothing to drop: the value is returned exactly as it was (a trailing '/' included)
    return " / ".join(p for p in parts if p and p.lower() not in PLACEHOLDER_WORDS)


# Position labels, in two dicts (#263). POS_EXACT keys match a whole label part only: every 1-2
# letter abbreviation lives here, so 'Manager' is not M, 'Fullback' is not F and 'Student Intern'
# is nothing. POS_MAP keys also match as a prefix ('Midfielders', 'Center Backs'), longest key
# first, so 'Defensive Mid' is M rather than 'def' -> D and 'Wing Back' is D. Every POS_MAP key is
# a whole position word or phrase of 3+ letters; sidearm._is_position_label (#311) accepts a part
# that starts with one, so a short abbreviation ('att', 'cam') must go in POS_EXACT instead.
POS_EXACT = {
    "g": "GK", "gk": "GK",
    "d": "D", "df": "D", "b": "D", "cb": "D", "ob": "D", "lb": "D", "rb": "D", "wb": "D", "fb": "D",
    "sw": "D",
    "m": "M", "mf": "M", "cm": "M", "cdm": "M", "cam": "M", "dm": "M", "am": "M", "acm": "M", "lm": "M",
    "rm": "M",
    "f": "F", "fw": "F", "cf": "F", "st": "F", "att": "F", "s": "F", "w": "F", "wing": "F",
    # short forms the old one-letter prefixes happened to map; kept at their old value
    "md": "M", "fd": "F", "fm": "F", "for": "F", "dlb": "D",
}
POS_MAP = {
    "goalkeeper": "GK", "keeper": "GK", "goalie": "GK", "backup goalkeeper": "GK", "backup keeper": "GK",
    "defender": "D", "def": "D", "back": "D", "center back": "D", "centre back": "D", "centerback": "D",
    "outside back": "D", "full back": "D", "fullback": "D", "right back": "D", "left back": "D",
    "wing back": "D", "wingback": "D", "sweeper": "D",
    "midfielder": "M", "mid": "M", "midfield": "M", "center mid": "M", "centre mid": "M",
    "central mid": "M", "attacking mid": "M", "defensive mid": "M",
    "forward": "F", "foward": "F", "fwd": "F", "striker": "F", "attacker": "F", "winger": "F", "center forward": "F",
    "centre forward": "F",
}


def pos_code(part: str) -> str:
    """GK / D / M / F for one label part ('CB', 'Center Back', 'Midfielders'), '' when unknown."""
    p = re.sub(r"[\s-]+", " ", part.lower()).strip(" .")
    if p in POS_EXACT:
        return POS_EXACT[p]
    best = max((k for k in POS_MAP if p.startswith(k)), key=len, default=None)
    return POS_MAP[best] if best else ""


def norm_pos(s: str | None) -> str:
    """Map assorted position labels to GK / D / M / F (slash-combos kept, e.g. 'D/M')."""
    if not s:
        return ""
    out = []
    for p in re.split(r"[/,]", s):
        # 'F-M', 'D.MF': split on '-' or '.' only when the whole part is not a label ('Wing-Back')
        whole = pos_code(p)
        codes = [whole] if whole or not re.search(r"\w[-.]\w", p) else [pos_code(x) for x in re.split(r"[-.]", p)]
        for code in codes:
            if code and code not in out:
                out.append(code)
    return "/".join(out)


US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
_STATE_BY_NAME = {v.lower(): k for k, v in US_STATES.items()}


def state_code(s: str | None) -> str:
    """'California' -> 'CA'; 'CA' -> 'CA'; unknown -> original text."""
    if not s:
        return ""
    s = clean(s)
    if len(s) == 2 and s.upper() in US_STATES:
        return s.upper()
    return _STATE_BY_NAME.get(s.lower(), s)
