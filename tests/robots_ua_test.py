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
  limits      the four places urllib.robotparser stops short of RFC 9309, pinned as the behaviour
              we actually ship rather than the behaviour we would like. Named-over-'*' is the only
              precedence it implements. These checks assert the WRONG-per-RFC answers on purpose:
              if one starts failing, the library got better and the notes above ROBOTS_AGENT in
              collect/common.py -- and probably the case for a real resolver -- need revisiting.
  monotonic   the change is strictly an improvement on the old '*' evaluation: a group naming us
              used to be ignored entirely, and the rule-line ordering quirks are pre-existing
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
#
# NOTE the rule-line order. robotparser returns the FIRST matching rule line in a group, not the
# longest-matching one, so this fixture only behaves as its name says because Disallow precedes
# Allow. test_limits below pins the swapped order, which answers differently on the same rules.
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


# ---------- limits: where robotparser stops short of RFC 9309 ----------

# Every check below asserts the answer the library actually gives, which in four places is NOT the
# answer RFC 9309 specifies. They are here so the gap is documented and pinned rather than
# discovered by someone reading the comment in common.py and trusting it too far. A failure here
# means the stdlib changed and common.py's notes need updating -- not that the collector broke.

def test_limits() -> None:
    print("limits (documented robotparser gaps, asserted as-shipped)")

    # 1. Rule lines resolve first-match, not longest-match (RFC 9309 2.2.2). The shipped fixture
    #    STAR_BANS_US_ALLOWED only passes because Disallow precedes Allow; swapping two lines that
    #    RFC 9309 treats as identical flips the verdict, and flips it OPEN.
    seed("User-agent: *\nDisallow: /\n\nUser-agent: CollegeDashBot\nAllow: /\nDisallow: /admin/\n")
    ok("rule lines are first-match, not longest-match (RFC 9309 would say False)",
       common.robots_allowed(u("/admin/x")) is True,
       "library now longest-matches; update the notes in common.py")

    # 2. The commonest operator carve-out. 'You may have /camps/ and nothing else' is denied
    #    outright, because 'Disallow: /' is the first line that matches. This one fails CLOSED:
    #    we lose a page we were allowed, rather than taking one we were refused.
    seed("User-agent: CollegeDashBot\nDisallow: /\nAllow: /camps/\n")
    ok("carve-out after a blanket disallow is NOT honoured (RFC 9309 would say True)",
       common.robots_allowed(u("/camps/x")) is False,
       "library now longest-matches; update the notes in common.py")
    # Written the other way round it works, which is the only reason the shipped fixture passes.
    seed("User-agent: CollegeDashBot\nAllow: /camps/\nDisallow: /\n")
    ok("the same carve-out written Allow-first is honoured",
       common.robots_allowed(u("/camps/x")) is True)

    # 3. Groups resolve first-in-file, not most-specific (RFC 9309 2.2.1), and agent matching is a
    #    substring test. Together these mean a loose group listed above the group naming us
    #    exactly hides it completely -- UNDER-obedience, the harm this change exists to prevent.
    seed("User-agent: bot\nAllow: /\n\nUser-agent: CollegeDashBot\nDisallow: /\n")
    ok("a loose substring group listed first hides the group naming us (fails OPEN)",
       common.robots_allowed(u("/roster")) is True,
       "library now prefers the most specific group; update the notes in common.py")
    seed("User-agent: CollegeDashBot\nDisallow: /\n\nUser-agent: bot\nAllow: /\n")
    ok("reversed, the group naming us is found first and obeyed",
       common.robots_allowed(u("/roster")) is False)

    # 4. Agent matching is substring, so groups never meant for us now apply. This is the only gap
    #    this change newly exposes: under ROBOTS_AGENT = '*' no named group matched at all.
    for tok in ("bot", "dash", "college", "DashBot"):
        seed(f"User-agent: {tok}\nDisallow: /\n")
        ok(f"substring group 'User-agent: {tok}' applies to us",
           common.robots_allowed(u("/roster")) is False)

    # 5. No path wildcards at all: RuleLine.applies_to is a plain startswith, so the '*' and '$'
    #    metacharacters RFC 9309 defines are treated as literal characters and the rule matches
    #    nothing. Fails OPEN, and is the gap most likely to matter in the wild.
    seed("User-agent: CollegeDashBot\nDisallow: /*.pdf$\n")
    ok("wildcard path rules are ignored entirely (RFC 9309 would say False)",
       common.robots_allowed(u("/a.pdf")) is True,
       "library now supports wildcards; update the notes in common.py")
    seed("User-agent: CollegeDashBot\nDisallow: /x$\n")
    ok("end-anchor '$' is literal, not an anchor (RFC 9309 would say False)",
       common.robots_allowed(u("/x")) is True)

    # 6. A second 'User-agent: *' group is silently discarded (_add_entry keeps the first).
    seed("User-agent: *\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    ok("only the first '*' group is kept", common.robots_allowed(u("/roster")) is False)

    seed(None)


# ---------- the change is monotonic against the old '*' evaluation ----------

def test_monotonic() -> None:
    """The gaps above are real, but none of them is a regression: evaluating as our own token is
    strictly better than evaluating as '*' for the case this change exists to serve."""
    print("monotonic")
    original = common.ROBOTS_AGENT
    try:
        # The case that matters: an operator writes a group addressed to us, telling us to stay out.
        rules = "User-agent: *\nAllow: /\n\nUser-agent: CollegeDashBot\nDisallow: /\n"

        common.ROBOTS_AGENT = "*"
        seed(rules)
        ok("before: a group naming us was ignored entirely, and we would have crawled",
           common.robots_allowed(u("/roster")) is True)

        common.ROBOTS_AGENT = original
        seed(rules)
        ok("after: the group naming us is honoured", common.robots_allowed(u("/roster")) is False)

        # And the rule-line ordering quirks predate this change -- they behaved identically when
        # the collector resolved as '*', so this PR neither introduces nor worsens them.
        for label, text, path in [
            ("carve-out", "Disallow: /\nAllow: /camps/\n", "/camps/x"),
            ("allow-then-disallow", "Allow: /\nDisallow: /admin/\n", "/admin/x"),
        ]:
            common.ROBOTS_AGENT = "*"
            seed(f"User-agent: *\n{text}")
            before = common.robots_allowed(u(path))
            common.ROBOTS_AGENT = original
            seed(f"User-agent: {original}\n{text}")
            after = common.robots_allowed(u(path))
            ok(f"{label} behaves the same before and after the change (pre-existing, not a regression)",
               before == after, f"before={before} after={after}")
    finally:
        common.ROBOTS_AGENT = original
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
    test_limits()
    test_monotonic()

    print(f"\n{TOTAL - len(FAILS)}/{TOTAL} checks passed")
    if FAILS:
        for f in FAILS:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
