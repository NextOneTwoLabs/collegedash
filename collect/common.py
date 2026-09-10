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
import time
import unicodedata
from urllib import robotparser

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(ROOT, "public")
PUBLIC_DATA_DIR = os.path.join(PUBLIC_DIR, "data")
PROGRAMS_OUT_DIR = os.path.join(PUBLIC_DATA_DIR, "programs")
RPI_OUT_DIR = os.path.join(PUBLIC_DATA_DIR, "rpi")
COMMITS_OUT_DIR = os.path.join(PUBLIC_DATA_DIR, "commitments")
REGISTRY_PATH = os.path.join(PUBLIC_DATA_DIR, "registry.json")
ARCHIVE_DIR = os.path.join(PUBLIC_DIR, "archive")
REFRESH_STATE_PATH = os.path.join(ARCHIVE_DIR, "refresh-state.json")

PROGRAMS_DIR = os.path.join(ROOT, "programs")
DATA_DIR = os.path.join(ROOT, "data")
COMMITS_DATA_DIR = os.path.join(DATA_DIR, "commitments")
SCHEMA_PATH = os.path.join(ROOT, "schema", "profile.schema.json")
CACHE_DIR = os.path.join(ROOT, ".cache", "http")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Politeness: minimum gap between live requests to the same host, plus jitter.
MIN_GAP_SECONDS = float(os.environ.get("COLLEGEDASH_MIN_GAP", "1.2"))
_last_request_at: dict[str, float] = {}


class FetchError(RuntimeError):
    pass


class SkipCollector(RuntimeError):
    """Raised by a collector when there is nothing to collect for this program (no Wikipedia
    article, no TopDrawerSoccer id, roster needs a browser). Recorded as ok+skipped, not as
    a failure, so `refresh --failed` and the dashboard do not keep nagging about it."""


# ---------- time ----------

def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    return _dt.date.today().isoformat()


def log(msg: str) -> None:
    print(f"[{_dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


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


@contextlib.contextmanager
def _locked(path: str, *, timeout: float = 15.0, stale_after: float = 60.0):
    """Cross-process lock around a read-modify-write of `path` (lock file = path + '.lock',
    created with O_EXCL). A lock older than `stale_after` seconds is treated as abandoned."""
    lock = path + ".lock"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
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
    return re.sub(r"^https?://([^/]+).*$", r"\1", url)


def _polite_wait(url: str) -> None:
    host = _host(url)
    last = _last_request_at.get(host)
    if last is not None:
        gap = max(MIN_GAP_SECONDS, _host_delay.get(host, 0.0)) + random.uniform(0, 0.8)
        elapsed = time.monotonic() - last
        if elapsed < gap:
            time.sleep(gap - elapsed)
    _last_request_at[host] = time.monotonic()


# ---------- robots.txt ----------
# Hosts outside the athletics sites (camp vendors, coaches' own sites) are checked against their
# robots.txt before a request is made. Cached per host for the life of the process (never on disk,
# so a denied host leaves no trace in .cache/http). A Crawl-delay for '*' raises that host's gap
# between requests above MIN_GAP_SECONDS.
_robots: dict[str, "robotparser.RobotFileParser"] = {}
_host_delay: dict[str, float] = {}
ROBOTS_AGENT = "*"


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
        _polite_wait(url)
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=20)
    except requests.RequestException as e:
        log(f"robots: {host} unreachable ({type(e).__name__}); treating as disallowed")
        rp.disallow_all = True
        return rp
    if 200 <= resp.status_code < 300:
        rp.parse(resp.text.splitlines())
    elif 400 <= resp.status_code < 500:
        rp.allow_all = True  # no robots.txt = no restrictions
    else:
        log(f"robots: {host} returned HTTP {resp.status_code}; treating as disallowed")
        rp.disallow_all = True
    return rp


def robots_allowed(url: str) -> bool:
    """True when `url` may be fetched under the host's robots.txt (agent '*'). 4xx = allowed;
    unreachable or 5xx = disallowed. Records the host's Crawl-delay for _polite_wait."""
    m = re.match(r"^(https?)://([^/]+)", url)
    if not m:
        return False
    scheme, host = m.group(1), m.group(2).lower()
    rp = _robots.get(host)
    if rp is None:
        rp = _load_robots(host, scheme)
        _robots[host] = rp
        _apply_crawl_delay(host, rp)
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
    """
    body_str = json.dumps(json_body, sort_keys=True) if json_body is not None else None
    key = _cache_key(method, url, body_str)
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
        raise FetchError(f"offline and not cached: {url}")

    hdrs = dict(DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)
    if json_body is not None:
        hdrs.setdefault("Content-Type", "application/json")

    last_err: Exception | None = None
    for attempt in range(retries):
        _polite_wait(url)
        try:
            resp = requests.request(method, url, headers=hdrs, data=body_str, timeout=timeout)
        except requests.RequestException as e:  # network
            last_err = e
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code in allow_status:
            meta = {"url": url, "status": resp.status_code, "fetchedAt": now_iso(), "fromCache": False,
                    "contentType": resp.headers.get("Content-Type", ""), "finalUrl": resp.url}
            with gzip.open(gz_path, "wb", compresslevel=6) as f:
                f.write(resp.content)
            if os.path.exists(body_path):
                os.remove(body_path)
            write_json(meta_path, meta)
            return resp.content, meta
        if resp.status_code in (429, 500, 502, 503, 504):
            last_err = FetchError(f"HTTP {resp.status_code} for {url}")
            # 429: per-minute quotas (Open-Meteo, api.data.gov) need a real pause, not a token one
            time.sleep((25 if resp.status_code == 429 else 5) * (attempt + 1))
            continue
        raise FetchError(f"HTTP {resp.status_code} for {url}")
    raise FetchError(f"giving up after {retries} attempts: {last_err}")  # last_err names the URL


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
    with _locked(REFRESH_STATE_PATH):
        state = read_json(REFRESH_STATE_PATH, {}) or {}
        entry = dict(info)
        entry["at"] = now_iso()
        state[key] = entry
        state["updated"] = now_iso()
        write_json(REFRESH_STATE_PATH, state)


def load_refresh_state() -> dict:
    return read_json(REFRESH_STATE_PATH, {}) or {}


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


POS_MAP = {
    "goalkeeper": "GK", "gk": "GK", "keeper": "GK",
    "defender": "D", "d": "D", "def": "D", "back": "D",
    "midfielder": "M", "m": "M", "mf": "M", "mid": "M", "midfield": "M",
    "forward": "F", "f": "F", "fwd": "F", "striker": "F",
}


def norm_pos(s: str | None) -> str:
    """Map assorted position labels to GK / D / M / F (slash-combos kept, e.g. 'D/M')."""
    if not s:
        return ""
    parts = re.split(r"[/,]", s.lower())
    out = []
    for p in parts:
        p = p.strip()
        code = POS_MAP.get(p)
        if code is None:
            for k, v in POS_MAP.items():
                if p.startswith(k):
                    code = v
                    break
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
