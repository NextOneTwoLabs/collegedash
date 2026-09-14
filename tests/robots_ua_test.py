"""Regression tests for the collector's User-Agent and for robots.txt evaluated as our own token.

    python tests/robots_ua_test.py            # everything below, offline
    python tests/robots_ua_test.py --verbose  # print every check, not only the failures

Offline: seeds the robots cache with literal robots.txt text through common.set_robots_txt and
makes no request. Exit 0 when every check passes, 1 otherwise.

Why these exist (issue #73). The collector used to send a plain Chrome string and evaluate
robots.txt as agent '*' -- the permissions of an anonymous bot with the identity of a browser.
Now that the User-Agent names the project, a site operator can write a robots.txt group addressed
to CollegeDashBot, and honouring it is the other half of the change: advertising an identity and
then ignoring instructions given to it would be worse than the anonymity it replaced.

Covers, in order:
  string      USER_AGENT names the project, carries a version and a resolvable URL, and is not
              browser-shaped -- no Mozilla/AppleWebKit/Chrome/Safari token anywhere in it
  one place   every request path inherits it: DEFAULT_HEADERS carries it, and collect.the_rank,
              the only module that sets its own User-Agent, sets it to this exact string
  token       ROBOTS_AGENT is the bare product token, which is the form a robots.txt group is
              written against, and is what robots_allowed passes
  resolution  a group naming us wins over '*' in both directions (it can forbid what '*' allows
              and allow what '*' forbids); '*' still applies when no group names us; and the same
              precedence governs Crawl-delay
"""

from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import common  # noqa: E402
from collect import the_rank  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False

HOST = "robots-fixture.example"


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def seed(text: str | None) -> None:
    """Install `text` as HOST's robots.txt and clear any Crawl-delay left by an earlier case."""
    common._host_delay.pop(HOST, None)
    common.set_robots_txt(HOST, text)


def u(path: str) -> str:
    return f"https://{HOST}{path}"


# ---------- the string ----------

def test_string() -> None:
    print("string")
    ua = common.USER_AGENT
    ok("names the project", common.USER_AGENT_PRODUCT in ua, ua)
    ok("carries a version", f"/{common.USER_AGENT_VERSION}" in ua, ua)
    ok("carries a URL a site operator can look up", f"+{common.USER_AGENT_URL}" in ua, ua)
    ok("URL is the project repository", common.USER_AGENT_URL.startswith("https://github.com/"),
       common.USER_AGENT_URL)
    ok("says it is automated", "automated" in ua.lower(), ua)

    # The failure mode the issue calls the worst of both: a browser-shaped string with a project
    # name bolted on. It is what trips the WAFs, because it claims to be something it is not.
    for token in ("Mozilla", "AppleWebKit", "KHTML", "Chrome", "Safari", "Gecko"):
        ok(f"no browser token: {token}", token.lower() not in ua.lower(), ua)

    # A User-Agent header must be one line of printable ASCII or requests will refuse to send it.
    ok("header-safe", bool(re.fullmatch(r"[\x20-\x7e]+", ua)), repr(ua))


# ---------- one place ----------

def test_single_source() -> None:
    print("one place")
    ok("DEFAULT_HEADERS carries it", common.DEFAULT_HEADERS.get("User-Agent") == common.USER_AGENT)
    # the_rank is the only module in the tree that sets its own User-Agent; it must not be a
    # second hand-written string that drifts from this one.
    ok("the_rank inherits it", the_rank.HEADERS.get("User-Agent") == common.USER_AGENT,
       the_rank.HEADERS.get("User-Agent"))


# ---------- the robots token ----------

def test_token() -> None:
    print("token")
    ok("robots token is the bare product token", common.ROBOTS_AGENT == common.USER_AGENT_PRODUCT,
       common.ROBOTS_AGENT)
    ok("robots token carries no version", "/" not in common.ROBOTS_AGENT, common.ROBOTS_AGENT)
    ok("robots token is no longer '*'", common.ROBOTS_AGENT != "*")


# ---------- resolution: our group wins, '*' is the fallback ----------

BOTH = """\
User-agent: *
Disallow: /private/
Crawl-delay: 2

User-agent: CollegeDashBot
Disallow: /camps/
Crawl-delay: 9
"""

STAR_ONLY = """\
User-agent: *
Disallow: /private/
Crawl-delay: 4
"""

# The case that matters most for a site operator: '*' bans everything, and the group naming us
# grants an exception. If we resolved as '*' we would refuse a page we were explicitly allowed.
STAR_BANS_US_ALLOWED = """\
User-agent: *
Disallow: /

User-agent: CollegeDashBot
Disallow: /admin/
Allow: /
"""


def test_resolution() -> None:
    print("resolution")

    seed(BOTH)
    ok("group naming us forbids what '*' allowed",
       common.robots_allowed(u("/camps/x")) is False)
    ok("group naming us allows what '*' forbade",
       common.robots_allowed(u("/private/x")) is True)
    ok("paths neither group names are allowed", common.robots_allowed(u("/roster")) is True)
    ok("our Crawl-delay wins over the '*' one",
       common._host_delay.get(HOST) == 9.0, common._host_delay.get(HOST))

    seed(STAR_ONLY)
    ok("'*' still applies when no group names us",
       common.robots_allowed(u("/private/x")) is False)
    ok("'*' allowance still applies", common.robots_allowed(u("/roster")) is True)
    ok("'*' Crawl-delay still applies", common._host_delay.get(HOST) == 4.0,
       common._host_delay.get(HOST))

    seed(STAR_BANS_US_ALLOWED)
    ok("an exception written for us is honoured", common.robots_allowed(u("/roster")) is True)
    ok("and its own Disallow is still obeyed", common.robots_allowed(u("/admin/x")) is False)

    seed(None)
    ok("no robots.txt = allowed", common.robots_allowed(u("/anything")) is True)

    # A Crawl-delay below MIN_GAP_SECONDS must not speed us up.
    seed("User-agent: CollegeDashBot\nCrawl-delay: 0.1\n")
    ok("a tiny Crawl-delay does not lower the floor", HOST not in common._host_delay,
       common._host_delay.get(HOST))

    seed(None)


def main() -> int:
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose

    test_string()
    test_single_source()
    test_token()
    test_resolution()

    print(f"\n{TOTAL - len(FAILS)}/{TOTAL} checks passed")
    if FAILS:
        for f in FAILS:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
