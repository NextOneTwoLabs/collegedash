"""No credential reaches a written file or the run's output (issue #258).

    python tests/redact_secrets_test.py            # every case
    python tests/redact_secrets_test.py --verbose  # print every check, not only the failures

A scorecard failure used to put the request URL, api_key and all, into the error text that refresh-state,
the build's `_build.failed`, the onboard batch summary and refresh's log, annotations and step summary
all store or print. Every case plants a random key in SCORECARD_API_KEY and checks that no 8-character
piece of it appears anywhere the run writes or prints. The key itself is never printed: a failing check
names the file, not the text.

Covers, in order:
  header        the scorecard collector sends the key as an X-Api-Key header, never in the URL
  end-to-end    a scorecard HTTP 500 (three attempts) and a network error, then an error from a collector
                that still puts a keyed URL in its message (plain, encoded, nested), go through
                collect_one, the worker-error path, report_refresh (lastRun.failures, log line,
                ::warning, step summary), build.collector_outcomes and onboard_batch summarize
                (.json and .md); nothing written or printed holds any piece of the key
  old-entry     onboard_batch.program_row redacts a refresh-state entry written by code before #258
  redact        common.redact, rule by rule, including the truncation order, short env values, and
                data fields (a camp link's key= parameter) that are left alone

Nothing here touches the network or the repository's data: common's paths point at a scratch tree and
the HTTP session is a stand-in.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import secrets
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.pop("GITHUB_ACTIONS", None)
os.environ.pop("GITHUB_STEP_SUMMARY", None)

from collect import common  # noqa: E402
import build  # noqa: E402
import collegedash  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False
API = "https://api.data.gov/ed/collegescorecard/v1/schools"


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def pieces(key: str, n: int = 8) -> list[str]:
    return [key[i:i + n] for i in range(len(key) - n + 1)]


def leaks(text: str, key: str) -> bool:
    return any(p in text for p in pieces(key))


def files_with_key(root: str, key: str) -> list[str]:
    """Paths (relative to root) of every file under root holding any 8-character piece of the key."""
    found = []
    for d, _, names in os.walk(root):
        for n in names:
            p = os.path.join(d, n)
            with open(p, "rb") as f:
                text = f.read().decode("utf-8", "replace")
            if leaks(text, key):
                found.append(os.path.relpath(p, root).replace(os.sep, "/"))
    return sorted(found)


@contextlib.contextmanager
def scratch(key: str):
    """common's paths at a scratch tree, the key in the env, no backoff; everything restored after."""
    names = ("REFRESH_STATE_PATH", "PROGRAMS_DIR", "CACHE_DIR", "DATA_DIR", "ARCHIVE_DIR")
    saved = {n: getattr(common, n) for n in names}
    saved_backoff, saved_session = common._backoff_seconds, common._session
    saved_env = {v: os.environ.get(v) for v in ("SCORECARD_API_KEY", "GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY")}
    with tempfile.TemporaryDirectory(prefix="redact-258-") as tmp:
        common.ARCHIVE_DIR = os.path.join(tmp, "public", "archive")
        common.REFRESH_STATE_PATH = os.path.join(common.ARCHIVE_DIR, "refresh-state.json")
        common.PROGRAMS_DIR = os.path.join(tmp, "programs")
        common.CACHE_DIR = os.path.join(tmp, ".cache", "http")
        common.DATA_DIR = os.path.join(tmp, "data")  # no scorecard-bulk.json: the collector calls the API
        common._backoff_seconds = lambda *a, **k: 0.0
        os.environ["SCORECARD_API_KEY"] = key
        try:
            yield tmp
        finally:
            for n, v in saved.items():
                setattr(common, n, v)
            common._backoff_seconds, common._session = saved_backoff, saved_session
            for v, val in saved_env.items():
                if val is None:
                    os.environ.pop(v, None)
                else:
                    os.environ[v] = val


class Resp:
    def __init__(self, status: int, url: str):
        self.status_code, self.url, self.content, self.headers = status, url, b"{}", {}


class Session:
    """Stands in for common._session(): records each request, answers with `status` or raises."""

    def __init__(self, calls: list, status: int | None, key: str | None = None):
        self.calls, self.status, self.key = calls, status, key

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def request(self, method, url, headers=None, data=None, timeout=None):
        import requests
        self.calls.append({"url": url, "headers": dict(headers or {})})
        if self.status is None:  # requests' own wording: the path and query are in the message
            path = url.split("api.data.gov", 1)[-1]
            raise requests.ConnectionError(
                f"HTTPSConnectionPool(host='api.data.gov', port=443): Max retries exceeded with url: {path} "
                f"(Caused by NewConnectionError('Failed to establish a new connection'))")
        return Resp(self.status, url)


def registry() -> dict:
    return {"sources": {"scorecard": {"api": API, "keyEnv": "SCORECARD_API_KEY"}}, "programs": []}


def prog(slug: str) -> dict:
    return {"slug": slug, "name": slug.title(), "division": "D3", "conference": "Test", "onboarded": True,
            "ids": {"scorecardUnitId": 999999}}


def load_onboard_batch():
    spec = importlib.util.spec_from_file_location(
        "onboard_batch_258", os.path.join(ROOT, ".github", "scripts", "onboard_batch.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------- cases ----------

def test_header() -> None:
    key = secrets.token_hex(20)
    calls: list = []
    with scratch(key):
        common._session = lambda: Session(calls, 200)
        from collect import scorecard
        try:
            scorecard.collect(prog("hdr"), registry())
        except common.FetchError:
            pass  # the stub answers {}: no results; the request is what this case checks
    ok("header: one request sent", len(calls) == 1, f"{len(calls)} requests")
    ok("header: the key is not in the request URL", calls and not leaks(calls[0]["url"], key))
    ok("header: the key is sent as X-Api-Key", calls and calls[0]["headers"].get("X-Api-Key") == key)


def test_end_to_end() -> None:
    key = secrets.token_hex(20)
    out, err = io.StringIO(), io.StringIO()
    with scratch(key) as tmp:
        step = os.path.join(tmp, "step-summary.md")
        os.environ["GITHUB_ACTIONS"] = "true"
        os.environ["GITHUB_STEP_SUMMARY"] = step
        reg = registry()
        a, b, c, d = prog("alpha"), prog("bravo"), prog("charlie"), prog("delta")
        reg["programs"] = [a, b, c, d]
        started = "2000-01-01T00:00:00Z"
        results = []
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            # 1. the real scorecard collector, answered with HTTP 500 (retried) and then a network error
            common._session = lambda: Session([], 500)
            r, entry = collegedash.collect_one("scorecard", a, reg)
            results.append(r)
            collegedash.record_outcomes("alpha", {"alpha.scorecard": entry})
            common._session = lambda: Session([], None)
            r, entry = collegedash.collect_one("scorecard", b, reg)
            results.append(r)
            collegedash.record_outcomes("bravo", {"bravo.scorecard": entry})
            # 2. a collector whose own message still carries a keyed URL: plain, last parameter before
            # " (", encoded and nested in another URL, and after ?key=
            from collect import scorecard
            saved = scorecard.collect
            keyed = (f"HTTP 500 for {API}?fields=id&api_key={key} (Caused by x); nested "
                     f"https://r.example/?u={API}%3Ffields%3Did%26api_key%3D{key}%26id%3D1 and ?key={key})")
            try:
                def boom(program, registry):
                    raise common.FetchError(keyed)
                scorecard.collect = boom
                r, entry = collegedash.collect_one("scorecard", c, reg)
                results.append(r)
                collegedash.record_outcomes("charlie", {"charlie.scorecard": entry})
                # 3. the worker-error path: collect_one itself raising
                saved_one = collegedash.collect_one

                def broken(*a, **k):
                    raise RuntimeError(keyed)
                collegedash.collect_one = broken
                try:
                    results += collegedash.collect_plan([(d, ["scorecard"])], reg, bios=False, coach_bios=False,
                                                        workers=1)
                finally:
                    collegedash.collect_one = saved_one
            finally:
                scorecard.collect = saved
            code = collegedash.report_refresh(results, threshold=0.5, mode="test")
            state = common.load_refresh_state()
            failed = [f for s in ("alpha", "bravo", "charlie", "delta") for f in build.collector_outcomes(s, state)[0]]
            common.write_json(os.path.join(tmp, "public", "data", "programs", "outcomes.json"), failed)
            # 4. onboard_batch summarize over the same refresh-state
            ob = load_onboard_batch()
            ob.ROOT = tmp
            common.write_json(os.path.join(tmp, "public", "data", "registry.json"), reg)
            plan = {"batchName": "t-258", "branch": "onboard/t-258", "division": "D3", "divisionState": "staged",
                    "conferences": ["Test"], "requestedSlugs": [], "held": [],
                    "slugs": ["alpha", "bravo", "charlie", "delta"]}
            plan_p, run_p = os.path.join(tmp, "plan.json"), os.path.join(tmp, "run.json")
            common.write_json(plan_p, plan)
            common.write_json(run_p, {"exit": 1, "startedAt": started})
            ob.main(["summarize", "--plan", plan_p, "--run", run_p,
                     "--base-registry", os.path.join(tmp, "public", "data", "registry.json"),
                     "--json-out", os.path.join(tmp, "data", "onboard-batches", "t-258.json"),
                     "--md-out", os.path.join(tmp, "data", "onboard-batches", "t-258.md")])
        ok("end-to-end: the run reports its failures", code == 1 and len(results) == 4,
           f"exit {code}, {len(results)} results")
        ok("end-to-end: every stage failed as staged", all(r["outcome"] == "failed" for r in results))
        last = (state.get("lastRun") or {}).get("failures") or []
        ok("end-to-end: lastRun.failures recorded", len(last) == 4, f"{len(last)} entries")
        # the worker-error path records nothing in refresh-state (its collect_one never returned an entry)
        ok("end-to-end: the build lists the three recorded failures", len(failed) == 3, f"{len(failed)}")
        summary = common.read_json(os.path.join(tmp, "data", "onboard-batches", "t-258.json")) or {}
        ok("end-to-end: the summary lists four programs", len(summary.get("programs") or []) == 4)
        ok("end-to-end: the step summary was written", os.path.exists(step))
        ok("end-to-end: the errors still say what failed",
           all("HTTP 500" in f["error"] or "Max retries" in f["error"] for f in failed if f["collector"]))
        found = files_with_key(tmp, key)
        ok("end-to-end: no written file holds any piece of the key", not found, f"in {found}")
    ok("end-to-end: stdout holds no piece of the key", not leaks(out.getvalue(), key))
    ok("end-to-end: stderr holds no piece of the key", not leaks(err.getvalue(), key))


def test_old_entry() -> None:
    key = secrets.token_hex(20)
    with scratch(key):
        ob = load_onboard_batch()
        old = (f"giving up after 3 attempts: HTTP 500 for {API}?api_key={key}&fields=id,school.name")[:300]
        state = {"alpha.scorecard": {"ok": False, "error": old, "at": "2026-09-20T00:00:00Z"}}
        row = ob.program_row("alpha", {"alpha": prog("alpha")}, state, {}, "2026-09-19T00:00:00Z")
        text = json.dumps(row) + ob.render_md({"batchName": "x", "division": "D3", "divisionState": "staged",
                                               "conferences": [], "requestedSlugs": [], "held": [],
                                               "programs": [row], "guard": [],
                                               "totals": {"failed": 1, "runs": 8, "notRun": 0},
                                               "run": {}})
        ok("old-entry: program_row keeps the failure", "scorecard" in row["failures"])
        ok("old-entry: no piece of the key in the row or the .md", not leaks(text, key))


def test_redact() -> None:
    key = secrets.token_hex(20)
    saved = os.environ.get("SCORECARD_API_KEY")
    try:
        os.environ.pop("SCORECARD_API_KEY", None)  # the parameter rules alone, without the env backstop
        r = common.redact
        for name in ("key", "api_key", "API_KEY", "apikey", "api-key", "token", "access_token", "auth_token",
                     "secret", "client_secret", "password", "passwd", "pwd", "sig", "signature"):
            ok(f"redact: ?{name}=", not leaks(r(f"GET https://h.example/p?{name}={key}&x=1"), key))
            ok(f"redact: &{name}= keeps the next parameter", r(f"/p?a=1&{name}={key}&x=1").endswith("&x=1"))
        ok("redact: ;key=", not leaks(r(f"/p;key={key}"), key))
        ok("redact: %3D separator", not leaks(r(f"/p?api_key%3D{key}"), key))
        ok("redact: nested %3F and %26", not leaks(r(f"/r?u=https%3A%2F%2Fh%2Fp%3Fa%3D1%26api_key%3D{key}%26b%3D2"), key))
        ok("redact: nested value stops at %26",
           r(f"/r?u=h%3Fapi_key%3D{key}%26b%3D2") == "/r?u=h%3Fapi_key%3DREDACTED%26b%3D2")
        ok("redact: last parameter before ' ('", r(f"url: /p?api_key={key} (Caused by x)") ==
           "url: /p?api_key=REDACTED (Caused by x)")
        ok("redact: last parameter before ')'", r(f"(url /p?api_key={key})") == "(url /p?api_key=REDACTED)")
        ok("redact: value ends at a quote", r(f"'/p?token={key}'") == "'/p?token=REDACTED'")
        ok("redact: value ends at #", r(f"/p?token={key}#frag") == "/p?token=REDACTED#frag")
        ok("redact: user:password in a URL", not leaks(r(f"https://bot:{key}@h.example/p"), key))
        ok("redact: None and empty", r(None) == "" and r("") == "")
        ok("redact: ordinary text unchanged", r("HTTP 500 for https://h.example/p?id=1&fields=a,b") ==
           "HTTP 500 for https://h.example/p?id=1&fields=a,b")
        ok("redact: a name that only ends in key is not matched", r("/p?monkey=1") == "/p?monkey=1")
        for n in (60, 120, 160, 200, 300):
            long = "giving up after 3 attempts: HTTP 500 for " + API + "?fields=" + "x" * 40 + "&api_key=" + key
            ok(f"redact then cut at {n}", not leaks(r(long)[:n], key))
        ok("redact: a cut placeholder is still not the key", not leaks(r(f"/p?api_key={key}")[:14], key))
        # the env backstop
        os.environ["SCORECARD_API_KEY"] = key
        ok("redact: the env key anywhere", not leaks(r(f"header X-Api-Key: {key} sent"), key))
        for short in ("", "abc", "1234567"):
            os.environ["SCORECARD_API_KEY"] = short
            ok(f"redact: an env value of {len(short)} characters changes nothing",
               r("abc 1234567 plain text") == "abc 1234567 plain text")
        # data fields are not error text: a camp registration link keeps its own key= parameter
        with scratch(key) as tmp:
            link = "https://apps.example.com/register?key=PUBLICFORMKEY1234&x=1"
            common.save_source("camp-x", "camps", {"items": [{"registerUrl": link}]}, url=link, collector="camps")
            back = common.load_source("camp-x", "camps") or {}
            ok("redact: a camp link in a data field is left alone",
               back.get("data", {}).get("items", [{}])[0].get("registerUrl") == link and back.get("sourceUrl") == link)
            ok("redact: scratch used", os.path.isdir(os.path.join(tmp, "programs", "camp-x")))
    finally:
        if saved is None:
            os.environ.pop("SCORECARD_API_KEY", None)
        else:
            os.environ["SCORECARD_API_KEY"] = saved


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_header, test_end_to_end, test_old_entry, test_redact):
        try:
            case()
        except Exception as e:  # a case that raises is a failed case, not a lost run
            ok(f"{case.__name__} ran to the end", False, type(e).__name__)  # not the message: it may hold the key
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
