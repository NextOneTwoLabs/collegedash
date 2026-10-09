"""The RFC 9309 robots.txt resolver (issue #87): every row of the approved matrix, plus the shadow diff and the camps
keep rule.

    python tests/robots_rfc9309_test.py            # offline: robots.txt is seeded, or served by a fake session
    python tests/robots_rfc9309_test.py --verbose  # print every check, not only the failures

The spec is the plan on issue #87, revisions 2, 3 and 3.1 (approved by Huatuo), with the owner's decisions of
2026-10-09 (all as recommended). Each check is named by its matrix row. F rows fail on the code before #87
(urllib.robotparser); G rows are guards that passed before and must keep passing; N rows are new checks with no
before (the step bounds, the shadow diff, the camps keep rule). ROBOTS_RFC9309_TEST_ROOT (optional) points the suite
at another checkout, so the code from before the change can be run through these same checks to show the F rows
failing.

Row IDs are distinct. Revision 2's W12 had two URLs: /a*b is W12a and /axb is W12f (Huatuo's note: keep the /axb
row). W12b-W12e are revisions 3 and 3.1's. C1 and C3 give each group a rule line: decision 12 (Crawl-delay does not
close a run of User-agent lines) would otherwise read their groups as one; C5 pins that reading.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import os
import sys
import time

ROOT = os.environ.get("ROBOTS_RFC9309_TEST_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import requests  # noqa: E402

from collect import camps, common  # noqa: E402

try:
    from collect import robots as R  # noqa: E402
except ImportError:  # the code before #87 has no resolver module; the N checks that need it fail
    R = None

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False

HOST = "rfc9309.example"
OURS = "User-agent: CollegeDashBot\n"
STAR = "User-agent: *\n"


def ok(name: str, cond, detail="") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:300]}" if detail != "" else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def guarded(name: str):
    """Run a case; an exception is that case's failure (the code before #87 lacks some of what is checked)."""
    def wrap(fn):
        def run():
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                ok(f"{name} ran to the end", False, f"{type(e).__name__}: {e}")
        run.__name__ = fn.__name__
        return run
    return wrap


def seed(text: str | None, host: str = HOST) -> None:
    common._host_delay.pop(host, None)
    common.set_robots_txt(host, text)


def url(path: str, host: str = HOST) -> str:
    return f"https://{host}{path}"


def allowed(text: str, path: str) -> bool:
    seed(text)
    return common.robots_allowed(url(path))


@contextlib.contextmanager
def env(**values):
    prev = {k: os.environ.get(k) for k in values}
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------- the verdict matrix: (id, F|G, robots.txt, path, RFC verdict) ----------

ROWS = [
    # agents and groups
    ("A1", "F", "User-agent: bot\nDisallow: /\n", "/x", True),
    ("A2", "G", "User-agent: collegedashbot\nDisallow: /\n", "/x", False),
    ("A3", "F", "User-agent: CollegeDashBot/1.0\nDisallow: /\n", "/x", False),
    ("A4", "F", "User-agent: bot\nAllow: /\n\nUser-agent: CollegeDashBot\nDisallow: /\n", "/x", False),
    ("A5", "F", OURS + "Disallow: /a\n\n" + OURS + "Disallow: /b\n", "/b", False),
    ("A6", "F", STAR + "Disallow: /\n\n" + STAR + "Allow: /\n", "/x", True),
    ("A7", "G", "User-agent: foo\nUser-agent: CollegeDashBot\nDisallow: /\n", "/x", False),
    ("A8", "G", STAR + "Disallow: /\n\n" + OURS + "Allow: /x\n", "/y", True),
    ("A9", "G", "User-agent: *bot\nDisallow: /\n", "/x", True),
    # rules and precedence
    ("R1", "F", OURS + "Allow: /\nDisallow: /admin/\n", "/admin/x", False),
    ("R2", "F", OURS + "Disallow: /\nAllow: /camps/\n", "/camps/x", True),
    ("R3", "F", OURS + "Disallow: /p\nAllow: /p\n", "/p", True),
    ("R4", "G", OURS + "Allow: /camps/\nDisallow: /\n", "/camps/x", True),
    ("R5", "G", OURS + "Disallow:\n", "/x", True),
    ("R6", "G", OURS + "Disallow: /\nAllow:\n", "/x", False),
    ("R7", "G", OURS + "Disallow: /Camps/\n", "/camps/x", True),
    ("R8", "F", OURS + "Disallow: /\n", "/robots.txt", True),
    ("R9", "F", OURS + "Disallow: private\n", "/private", False),
    # group boundaries and line handling
    ("X1", "F", STAR + "Allow:\nDisallow: /\n", "/x", False),
    ("X5", "F", "﻿" + STAR + "Disallow: /\n", "/x", False),
    ("X7", "F", OURS + "\nUser-agent: other\nDisallow: /\n", "/x", False),
    ("X8", "F", OURS + "Crawl-delay: 5\nUser-agent: other\nDisallow: /\n", "/x", False),
    ("L1", "G", OURS + "Sitemap: https://rfc9309.example/sitemap.xml\nDisallow: /\n", "/x", False),
    ("L2", "G", OURS + "Noindex: /a\nDisallow: /\n", "/x", False),
    ("L3", "G", "Disallow: /\n" + STAR + "Allow: /\n", "/x", True),
    ("L4", "G", "User-agent: *\r\nDisallow: /p\r\n", "/p", False),
    ("L5", "G", "User-agent: *  # everyone\nDisallow: /p  # private\n", "/p", False),
    # wildcards and anchors
    ("W1", "F", STAR + "Disallow: /*.pdf$\n", "/a.pdf", False),
    ("W2", "G", STAR + "Disallow: /*.pdf$\n", "/a.pdf?x=1", True),
    ("W3a", "F", STAR + "Disallow: /x$\n", "/x", False),
    ("W3b", "G", STAR + "Disallow: /x$\n", "/xy", True),
    ("W4", "F", STAR + "Disallow: /*/private/\n", "/a/private/x", False),
    ("W5", "F", STAR + "Disallow: /*\n", "/x", False),
    ("W6", "F", STAR + "Disallow: /a**b\n", "/a-x-b", False),
    ("W7", "F", STAR + "Disallow: /*?sort=\n", "/list?sort=asc", False),
    ("W8", "G", STAR + "Allow: /*.html\nDisallow: /private\n", "/private/a.html", False),
    ("W10", "G", STAR + "Disallow: /a$b\n", ("/a$b", "/a"), (False, True)),
    ("W11", "G", STAR + "Allow: /a*\nDisallow: /*b\n", "/ab", True),
    ("W12a", "G", STAR + "Disallow: /a%2Ab\n", "/a*b", False),
    ("W12f", "G", STAR + "Disallow: /a%2Ab\n", "/axb", True),
    ("W12b", "G", STAR + "Disallow: /a%2Ab\n", "/a%2Ab", False),
    ("W12c", "G", STAR + "Disallow: /a%24\n", "/a$", False),
    ("W12d", "G", STAR + "Disallow: /a%24\n", "/a%24", False),
    ("W12e", "F", STAR + "Disallow: /a$\n", "/a%24", True),
    # what is matched
    ("E1", "F", STAR + "Disallow: /$\n", "", False),
    ("E2", "F", STAR + "Disallow: /p$\n", "/p#frag", False),
    ("M1", "G", STAR + "Disallow: /a;jsessionid\n", "/a;jsessionid=1", False),
    ("M2", "F", STAR + "Disallow: /*;jsessionid\n", "/x/a;jsessionid=1", False),
    ("Q1", "G", STAR + "Disallow: /a?\n", "/a?", False),
    # percent-encoding
    ("P1", "G", STAR + "Disallow: /foo/bar/ツ\n", "/foo/bar/%E3%83%84", False),
    ("P2", "G", STAR + "Disallow: /foo/bar/%62%61%7A\n", "/foo/bar/baz", False),
    ("P3", "G", STAR + "Disallow: /~joe/\n", "/%7Ejoe/x", False),
    ("P4", "F", STAR + "Disallow: /a%2Fb\n", "/a/b", True),
    ("P5", "F", STAR + "Disallow: /a/b\n", "/a%2Fb", True),
    ("P6", "G", STAR + "Disallow: /a%3c\n", "/a%3C", False),
    ("U1", "G", STAR + "Disallow: /a|b\n", "/a%7Cb", False),
    ("U2", "G", STAR + "Disallow: /a%7Cb\n", "/a|b", False),
    ("U3", "G", STAR + "Disallow: /a%zz\n", "/a%25zz", False),
    # decision 12's consequence (Huatuo, review of the #87 build): a '*' group holding only Crawl-delay, followed by
    # another bot's group, is ONE group naming both, so its Disallow applies to us through '*'. Flips if the owner
    # reverses decision 12.
    ("X9", "F", STAR + "Crawl-delay: 10\n\nUser-agent: AhrefsBot\nDisallow: /\n", "/x", False),
]


def test_matrix() -> None:
    print("matrix: agents, rules, boundaries, wildcards, what is matched, percent-encoding")
    for rid, kind, text, path, want in ROWS:
        try:
            if isinstance(path, tuple):
                got = tuple(allowed(text, p) for p in path)
            else:
                got = allowed(text, path)
        except Exception as e:  # noqa: BLE001
            got = f"{type(e).__name__}: {e}"
        ok(f"{rid} ({kind}) {text.strip()[:60]!r} {path!r} -> {'allow' if want is True else want}", got == want,
           f"got {got}")


# ---------- work bounds ----------

def _timed(fn):
    t = time.perf_counter()
    v = fn()
    return v, time.perf_counter() - t


@guarded("W9")
def test_w9() -> None:
    print("W9: 40 stars against a 4 KB path (no ReDoS)")
    pat = "/" + "a*" * 40 + "b"
    path = "/" + "a" * 4096
    text = STAR + f"Disallow: {pat}\n"
    seed(text)
    got, secs = _timed(lambda: common.robots_allowed(url(path)))
    ok("W9 (G) allowed, under 1 s as a backstop", got is True and secs < 1.0, (got, round(secs, 3)))
    ok("W9-steps (N) the resolver module exists", R is not None)
    steps = R.Steps()
    R.Robots.parse(text).allowed(url(path), common.ROBOTS_AGENT, steps=steps)
    m, n = len(pat), len(path)
    ok("W9-steps (N) steps <= 4(m+1)(n+1)", steps.n <= 4 * (m + 1) * (n + 1), (steps.n, 4 * (m + 1) * (n + 1)))


@guarded("G1")
def test_glob_reference() -> None:
    """The linear matcher against a reference regex built here, in the test, from the raw pattern ('*' is '.*', a
    final '$' is the end, anything else literal). Seeded, so a failure reproduces."""
    print("G1: the matcher agrees with a reference glob on 20,000 seeded random cases")
    import random
    import re
    ok("G1 (N) the resolver module exists", R is not None)
    rng = random.Random(87)
    bad = []
    for _ in range(20000):
        pat = "/" + "".join(rng.choice("ab*$/") for _ in range(rng.randint(0, 7)))
        path = "/" + "".join(rng.choice("ab$/") for _ in range(rng.randint(0, 9)))
        rx = "".join(".*" if c == "*" else r"\Z" if c == "$" and i == len(pat) - 1 else re.escape(c)
                     for i, c in enumerate(pat))
        want = re.match(rx, path, re.S) is not None
        got = R._matches(R._Rule(False, pat.encode()), R.target(url(path)), R.Steps())
        if got != want:
            bad.append((pat, path, got))
    ok("G1 (N) no disagreement", not bad, bad[:5])


W13A = STAR + "Disallow: /a*a*a*a*b\n" * 50000
W13A_PATH = "/" + "a" * 8000


@guarded("W13a")
def test_w13a() -> None:
    print("W13a: a step budget per verdict; explicit checks deny, the hook counts a resolver error")
    seed(W13A)
    got, secs = _timed(lambda: common.robots_allowed(url(W13A_PATH)))
    ok("W13a (F) the budget runs out: the explicit check denies, within 1 s", got is False and secs < 1.0,
       (got, round(secs, 3)))
    with env(COLLEGEDASH_ROBOTS="report"):
        common.reset_robots_report()
        got = common._robots_check(url(W13A_PATH))
        rep = common.robots_report(elapsed_seconds=1, workers=1)
    ok("W13a-hook-report (N) report mode allows and counts resolverErrors",
       got == HOST and rep.get("resolverErrors") == 1 and rep["wouldBlock"]["total"] == 0,
       (got, rep.get("resolverErrors"), rep["wouldBlock"]["total"]))
    with env(COLLEGEDASH_ROBOTS="enforce"):
        common.reset_robots_report()
        try:
            common._robots_check(url(W13A_PATH))
            raised = False
        except common.RobotsDisallowed:
            raised = True
        rep = common.robots_report(elapsed_seconds=1, workers=1)
    ok("W13a-hook-enforce (N) enforce mode denies and counts resolverErrors", raised and rep.get("resolverErrors") == 1,
       (raised, rep.get("resolverErrors")))
    common.reset_robots_report()
    ok("W13a-steps (N) the resolver module exists", R is not None)
    rb = R.Robots.parse(W13A)
    ok("W13a-truncated (N) the ~1025 KiB body is cut to 500 KiB at a line break", rb.truncated_body
       and 20000 < len(rb._groups[0].rules) < 25000, len(rb._groups[0].rules))
    steps = R.Steps()
    try:
        rb.allowed(url(W13A_PATH), common.ROBOTS_AGENT, steps=steps)
        raised = False
    except R.BudgetExceeded:
        raised = True
    ok("W13a-steps (N) BudgetExceeded, steps <= 2e6", raised and steps.n <= R.STEP_BUDGET == 2_000_000,
       (raised, steps.n))


@guarded("W13b-e")
def test_w13_lines() -> None:
    print("W13b-W13e: the 4096-octet pattern cap, the %XX backoff, many rules within budget")
    ok("W13b (F) an overlong Disallow keeps its first 4096 octets (broader: fails closed)",
       allowed(STAR + "Disallow: /" + "a" * 6000 + "\n", "/" + "a" * 4095 + "z") is False)
    ok("W13c (F) an overlong Allow is dropped (fails closed)",
       allowed(STAR + "Allow: /" + "a" * 6000 + "\nDisallow: /\n", "/" + "a" * 6000) is False)
    tail = "/" + "a" * 4093 + "%E3%83%84"
    ok("W13d (G) a cut inside %E3 moves back before the '%'", allowed(STAR + f"Disallow: {tail}\n", tail) is False)
    # a cut just after a mid-pattern '$' must not turn it into an end anchor (that narrows the rule: fails open).
    # A guard against main (urllib.robotparser has no cap); it failed on this branch before the fix (Huatuo's review).
    ok("W13f (G) a cut ending on a mid-pattern '$' does not anchor",
       allowed(STAR + "Disallow: /" + "a" * 4094 + "$bbb\n", "/" + "a" * 4094 + "$bbbzzz") is False)
    w13e = STAR + "".join(f"Disallow: /p{i:05d}/\n" for i in range(20000)) \
        + "".join(f"Disallow: /*.x{i:03d}$\n" for i in range(200))
    path = "/q" + "z" * 298
    ok("W13e (G) 20,200 rules, none matching: allowed", allowed(w13e, path) is True)
    ok("W13e-steps (N) the resolver module exists", R is not None)
    steps = R.Steps()
    got = R.Robots.parse(w13e).allowed(url(path), common.ROBOTS_AGENT, steps=steps)
    ok("W13e-steps (N) the budget is not exhausted: under 10% of it", got is True and steps.n < R.STEP_BUDGET // 10,
       steps.n)
    rb = R.Robots.parse(STAR + "Disallow: /" + "a" * 6000 + "\nAllow: /" + "b" * 5000 + "\n")
    ok("W13-count (N) both overlong rules are counted as truncated", rb.truncated_rules == 2, rb.truncated_rules)


# ---------- Crawl-delay ----------

@guarded("C")
def test_crawl_delay() -> None:
    print("C1-C5: Crawl-delay from the chosen merged group only")
    cases = [
        ("C1", "F", "User-agent: bot\nDisallow: /b\nCrawl-delay: 9\n\nUser-agent: *\nDisallow: /s\nCrawl-delay: 2\n", 2.0),
        ("C2", "G", OURS + "Crawl-delay: 2.5\n", 2.5),
        ("C3", "G", OURS + "Disallow: /x\n\n" + STAR + "Disallow: /y\nCrawl-delay: 5\n", None),
        ("C4", "F", OURS + "Disallow: /a\nCrawl-delay: 2\n\n" + OURS + "Disallow: /b\nCrawl-delay: 7\n", 7.0),
        # decision 12: Crawl-delay does not close the User-agent run, so 'bot' and '*' are one group here
        ("C5", "N", "User-agent: bot\nCrawl-delay: 9\n\nUser-agent: *\nCrawl-delay: 2\n", 9.0),
    ]
    for rid, kind, text, want in cases:
        seed(text)
        got = common._robots_delay.get(HOST)
        ok(f"{rid} ({kind}) Crawl-delay {want}", got == want, got)


# ---------- the size cap and the robots.txt states, through the real loader ----------

class _Resp:
    def __init__(self, status: int, body: bytes = b""):
        self.status_code, self.content = status, body
        self.text = body.decode("utf-8", "replace")


class _FakeSession:
    def __init__(self, answer):
        self.answer = answer

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kw):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@contextlib.contextmanager
def served(host: str, answer):
    """`host`'s robots.txt answered by `answer` (a _Resp, or an exception) through common._load_robots."""
    real = common._session
    common._session = lambda: _FakeSession(answer)
    common._robots.pop(host, None)
    try:
        with env(COLLEGEDASH_OFFLINE=None):
            yield
    finally:
        common._session = real
        common._robots.pop(host, None)


T1_BODY = (STAR + "Disallow: /a\n" + "# filler line ........................................\n" * 11000
           + "Disallow: /z\n").encode()


@guarded("T/S")
def test_loader() -> None:
    print("T1, T2: the 500 KiB cap on the raw body; S1-S4: robots.txt states")
    assert len(T1_BODY) > 600 * 1024 - 20000
    seed(T1_BODY.decode())
    ok("T1 (F) seeded: a rule past 500 KiB is not read", common.robots_allowed(url("/z")) is True)
    ok("T1-early (G) a rule before the cap still applies", common.robots_allowed(url("/a")) is False)
    host = "t1.example"
    with served(host, _Resp(200, T1_BODY)):
        ok("T1-loaded (F) fetched: a rule past 500 KiB is not read", common.robots_allowed(url("/z", host)) is True)
        rep = common.robots_report(elapsed_seconds=1, workers=1)
        ok("T1-count (N) truncated hosts are counted", rep.get("resolverDiff", {}).get("truncatedHosts", 0) >= 1,
           rep.get("resolverDiff"))
    # 1800 comment lines of 100 'ツ' each: about 185,000 characters but 545,000 octets
    t2 = (STAR + ("# " + "ツ" * 100 + "\n") * 1800 + "Disallow: /z\n").encode()
    assert len(t2.decode()) < 500 * 1024 < len(t2)
    with served("t2.example", _Resp(200, t2)):
        ok("T2 (F) the cap counts octets of the raw body, not characters",
           common.robots_allowed(url("/z", "t2.example")) is True)
    with served("s1.example", _Resp(404)):
        ok("S1 (G) 404: allowed", common.robots_allowed(url("/x", "s1.example")) is True)
    with served("s2.example", _Resp(503)):
        ok("S2a (G) 503: the explicit check denies", common.robots_allowed(url("/x", "s2.example")) is False)
    with served("s2b.example", _Resp(503)), env(COLLEGEDASH_ROBOTS="report"):
        common.reset_robots_report()
        got = common._robots_check(url("/x", "s2b.example"))
        ok("S2b (G) 503: the hook in report mode allows and counts it (decision B)",
           got == "s2b.example" and common._robots_state.get("s2b.example") == "5xx", got)
    with served("s2c.example", requests.ConnectionError("down")):
        ok("S2c (G) unreachable: the explicit check denies", common.robots_allowed(url("/x", "s2c.example")) is False)
    common._robots.pop("s3.example", None)
    with env(COLLEGEDASH_OFFLINE="1"):
        ok("S3 (G) offline: denied", common.robots_allowed(url("/x", "s3.example")) is False)
    seed(None)
    ok("S4 (G) seeded None: allowed", common.robots_allowed(url("/x")) is True)
    common.reset_robots_report()


# ---------- the shadow diff ----------

def diff() -> dict:
    return common.robots_report(elapsed_seconds=1, workers=1)["resolverDiff"]


@guarded("D1")
def test_d1() -> None:
    print("D1-D4: the shadow diff (decision 2): capped, no query strings, errors isolated, counted once")
    common.reset_robots_report()
    hosts = [f"d{i:02d}.example" for i in range(30)]
    for h in hosts:
        seed(STAR + "Disallow: /*/private/\n", h)
    for i in range(80):
        common.robots_allowed(url(f"/a{i}/private/x?token=secret{i}", hosts[i % 30]))
    d = diff()
    ok("D1 (N) 80 newly blocked paths on 30 hosts are all counted", d["newlyBlocked"] == 80 and d["newlyAllowed"] == 0,
       {k: d[k] for k in ("newlyBlocked", "newlyAllowed")})
    ok("D1 (N) topHosts is capped at 20", len(d["topHosts"]) == 20, len(d["topHosts"]))
    ok("D1 (N) samplePaths is capped at 50", len(d["samplePaths"]) == 50, len(d["samplePaths"]))
    ok("D1 (N) no query string reaches the report", "?" not in repr(d) and "secret" not in repr(d))
    ok("D1 (N) each sample is labelled with its check and change", all(
        p["check"] == "explicit" and p["change"] == "newlyBlocked" and set(p) == {"host", "path", "site", "check", "change"}
        for p in d["samplePaths"]), d["samplePaths"][:2])


@guarded("D2")
def test_d2() -> None:
    common.reset_robots_report()
    seed(STAR + "Disallow: /*.pdf$\n")

    class Boom:
        def can_fetch(self, *a):
            raise RuntimeError("comparison parser exploded")
    common._robots_cmp[HOST] = Boom()
    got = common.robots_allowed(url("/a.pdf"))
    ok("D2 (N) a comparison error leaves the explicit verdict unchanged", got is False, got)
    with env(COLLEGEDASH_ROBOTS="report"):
        got = common._robots_check(url("/b.pdf"))
    d = diff()
    ok("D2 (N) ... and the hook's", got == HOST)
    ok("D2 (N) comparisonErrors counts both", d["comparisonErrors"] == 2 and d["newlyBlocked"] == 0, d)
    common.reset_robots_report()


@guarded("D3")
def test_d3() -> None:
    common.reset_robots_report()
    seed(STAR + "Disallow: /*/private/\n")
    u = url("/a/private/x?q=1")
    with env(COLLEGEDASH_ROBOTS="report"), common.fetch_site("camps.page"):
        common.robots_allowed(u)
        common._robots_check(u)
        common._robots_check(url("/a/private/x?q=2"))
    d = diff()
    ok("D3 (N) the same (host, path) through the explicit check and the hook is counted once",
       d["newlyBlocked"] == 1 and len(d["samplePaths"]) == 1, d)
    ok("D3 (N) the first sighting labels it", d["samplePaths"][0] == {
        "host": HOST, "path": "/a/private/x", "site": "camps.page", "check": "explicit", "change": "newlyBlocked"},
       d["samplePaths"])
    with env(COLLEGEDASH_ROBOTS="report"):
        common._robots_check(url("/b/private/y"))
    d = diff()
    ok("D4 (N) a difference only the hook sees is recorded, labelled hook",
       d["newlyBlocked"] == 2 and d["samplePaths"][1]["check"] == "hook", d)
    seed(OURS + "Disallow: /\nAllow: /camps/\n")
    common.robots_allowed(url("/camps/x"))
    d = diff()
    ok("D4 (N) a widening is counted as newlyAllowed", d["newlyAllowed"] == 1 and d["topHosts"][0] == {
        "host": HOST, "newlyAllowed": 1, "newlyBlocked": 2}, d)
    common.reset_robots_report()


# ---------- camps: an explicit block keeps the stored camps (decision 8) ----------

SCHOOL = "https://school.invalid"


@contextlib.contextmanager
def camps_env(stored: dict, pages: dict, redirects: dict | None = None):
    saved, logs = {}, []
    real = (common.fetch_text, common.save_source, common.load_source, common.log, common.forget_cached)

    def fetch_text(u, **_):
        final = (redirects or {}).get(u, u)
        if final not in pages:
            raise common.FetchError(f"HTTP 404 for {final}")
        return pages[final], {"url": u, "finalUrl": final, "status": 200, "fromCache": False,
                              "contentType": "text/html"}
    common.fetch_text = fetch_text
    common.save_source = lambda slug, name, data, **kw: saved.setdefault(name, copy.deepcopy(data))
    common.load_source = lambda slug, name: copy.deepcopy(stored.get(name))
    common.log = logs.append
    common.forget_cached = lambda *a, **k: False
    try:
        with env(COLLEGEDASH_ROBOTS=None):
            yield saved, logs
    finally:
        common.fetch_text, common.save_source, common.load_source, common.log, common.forget_cached = real


def camps_run(camps_url: str, stored_url: str, pages: dict | None = None, redirects: dict | None = None) -> dict:
    stored_camps = [{"name": "Stored ID Camp", "startDate": "2026-11-01"}]
    stored = {"camps": {"data": {"campsUrl": stored_url, "camps": stored_camps, "pageTitle": "Stored title"}}}
    program = {"slug": "keep87", "athletics": {"platform": "auto", "baseUrl": SCHOOL, "sportPath": "/wsoc",
                                               "campsUrl": camps_url}}
    with camps_env(stored, pages or {}, redirects) as (saved, _):
        camps.collect(copy.deepcopy(program), {})
    return saved.get("camps") or {}


@guarded("K")
def test_camps_keep() -> None:
    print("K1-K4: camps keep their stored camps when an explicit robots check blocks the page (decision 8)")
    stored_camps = [{"name": "Stored ID Camp", "startDate": "2026-11-01"}]
    seed(STAR + "Disallow: /camps/\n", "vendor.invalid")
    u1 = "https://vendor.invalid/camps/soccer"
    d = camps_run(u1, u1)
    ok("K1 (F) an off-site camp page disallowed before the request keeps its stored camps",
       d.get("camps") == stored_camps and d.get("robotsBlocked") is True, {k: d.get(k) for k in ("camps", "robotsBlocked")})
    seed(STAR + "Disallow: /*/soccer$\n", "wild.invalid")
    u2 = "https://wild.invalid/x/soccer"
    d = camps_run(u2, u2)
    ok("K2 (F) ... also when a wildcard rule newly blocks it", d.get("camps") == stored_camps
       and d.get("robotsBlocked") is True, {k: d.get(k) for k in ("camps", "robotsBlocked")})
    seed(STAR + "Allow: /\n", "hop.invalid")
    seed(STAR + "Disallow: /\n", "other.invalid")
    u3, final = "https://hop.invalid/camps", "https://other.invalid/camps/x"
    d = camps_run(u3, u3, pages={final: "<html><title>Camps</title></html>"}, redirects={u3: final})
    ok("K3 (F) ... and when it redirects onto a host that disallows it (camps.py, the final-host check)",
       d.get("camps") == stored_camps and d.get("robotsBlocked") is True,
       {k: d.get(k) for k in ("camps", "robotsBlocked")})
    d = camps_run(u1, "https://vendor.invalid/old-camps")
    ok("K4 (G) CONTROL camps stored for a different campsUrl are not carried over", d.get("camps") == [], d.get("camps"))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    saved_mode = os.environ.get("COLLEGEDASH_ROBOTS")
    try:
        for case in (test_matrix, test_glob_reference, test_w9, test_w13a, test_w13_lines, test_crawl_delay, test_loader, test_d1, test_d2,
                     test_d3, test_camps_keep):
            case()
    finally:
        if saved_mode is None:
            os.environ.pop("COLLEGEDASH_ROBOTS", None)
        else:
            os.environ["COLLEGEDASH_ROBOTS"] = saved_mode
        seed(None)
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED:\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
