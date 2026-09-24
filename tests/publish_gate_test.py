"""Regression tests for the publish gate (issue #94; Bianque's review of #252, plan revision 1 on #94).

    python tests/publish_gate_test.py            # everything below, offline
    python tests/publish_gate_test.py --verbose  # print every check, not only the failures

Offline: reads the committed registry and checks which programs have a stored athletics source; writes
nothing. Exit 0 when every check passes, 1 otherwise. Every check names, in a comment, the input that makes
it fail.

build.check_publish_gate() (run by `collegedash.py validate`): every published program has
programs/<slug>/sources/athletics.json, or carries athletics.skipReason, or athletics.rosterRequiresBrowser, or
is on build.PUBLISH_GATE_REVIEWED with a reason and a date. A stale reviewed entry fails, and so does
rosterRequiresBrowser on a program that has athletics data.

Covers, in order:
  synthetic  each reason passes on its own, no reason fails, each stale / malformed reviewed entry fails,
             rosterRequiresBrowser with data fails, and a D3 program is covered the moment D3 is published
  committed  the gate passes on the committed registry, the reviewed list is empty, and the six D1 programs
             with no athletics source are the six that carry rosterRequiresBrowser
  mutations  the committed registry with one reason removed, or one stale entry added, fails
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# COLLEGEDASH_CODE_ROOT=<a mutated copy of the code> runs these checks against that code (issue #187's swap-back proof)
CODE_ROOT = os.environ.get("COLLEGEDASH_CODE_ROOT") or ROOT
sys.path.insert(0, CODE_ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import build  # noqa: E402
from collect import common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False
BROWSER_D1 = {"oklahoma", "utah-state", "wyoming", "ohio-university", "george-mason", "st-thomas"}


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def gate(registry, **kw) -> tuple[bool, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        passed = build.check_publish_gate(registry, **kw)
    return passed, out.getvalue()


def prog(slug, division="D1", **athletics):
    return {"slug": slug, "division": division, "onboarded": True, "athletics": {"baseUrl": "https://x.test", **athletics}}


def reg(*programs, divisions=("D1", "D2")):
    return {"onboardedDivisions": list(divisions), "programs": list(programs)}


# ---------- synthetic ----------

def test_synthetic() -> None:
    print("synthetic: which programs the gate lets through")
    has = lambda slug: slug.startswith("data-")  # noqa: E731
    passed, _ = gate(reg(prog("data-a"), prog("data-b", "D2")), has_athletics=has, reviewed={})
    # fails if a program WITH athletics data is ever refused
    ok("programs with athletics data pass", passed)
    passed, out = gate(reg(prog("data-a"), prog("empty-a")), has_athletics=has, reviewed={})
    # fails if the gate stops looking at programs without data (the whole point)
    ok("a published program with no data and no reason fails", not passed and "GATE empty-a:" in out, out)
    passed, _ = gate(reg(prog("empty-a", skipReason="athletics site refuses CollegeDashBot: HTTP 403")), has_athletics=has, reviewed={})
    ok("athletics.skipReason is a reason", passed)
    passed, _ = gate(reg(prog("empty-a", skipReason="   ")), has_athletics=has, reviewed={})
    # fails if a blank skipReason is accepted as a reason
    ok("a blank skipReason is not a reason", not passed)
    passed, _ = gate(reg(prog("empty-a", rosterRequiresBrowser=True)), has_athletics=has, reviewed={})
    ok("athletics.rosterRequiresBrowser is a reason", passed)
    passed, _ = gate(reg(prog("empty-a")), has_athletics=has, reviewed={"empty-a": {"reason": "reviewed on #94", "date": "2026-09-23"}})
    ok("a reviewed entry with a reason and a date is a reason", passed)
    passed, out = gate(reg(prog("data-a", rosterRequiresBrowser=True)), has_athletics=has, reviewed={})
    # fails if a program whose roster came back keeps the flag that stops its collector
    ok("rosterRequiresBrowser on a program that has athletics data fails", not passed and "rosterRequiresBrowser is set" in out, out)
    # stale entries: the list cannot quietly grow
    passed, out = gate(reg(prog("data-a")), has_athletics=has, reviewed={"data-a": {"reason": "r", "date": "2026-09-23"}})
    ok("a reviewed entry for a program that now has data fails (stale)", not passed and "now has athletics data" in out, out)
    passed, out = gate(reg(prog("data-a")), has_athletics=has, reviewed={"gone": {"reason": "r", "date": "2026-09-23"}})
    ok("a reviewed entry for a program that is not published fails (stale)", not passed and "not published" in out, out)
    unpub = {**prog("empty-u"), "onboarded": False}
    passed, out = gate(reg(prog("data-a"), unpub), has_athletics=has, reviewed={"empty-u": {"reason": "r", "date": "2026-09-23"}})
    ok("an entry for a registry program that is not onboarded is stale too", not passed and "not published" in out, out)
    for bad in ({"reason": "", "date": "2026-09-23"}, {"reason": "r"}, {"reason": "r", "date": "Sept 23"}, "just a string"):
        passed, _ = gate(reg(prog("empty-a")), has_athletics=has, reviewed={"empty-a": bad})
        ok(f"a malformed reviewed entry fails: {bad!r}", not passed)
    # the D3 switch (#94 PR 4): staged programs are not in scope, published ones are
    d3 = prog("empty-d3", "D3")
    passed, _ = gate(reg(prog("data-a"), d3, divisions=("D1", "D2")), has_athletics=has, reviewed={})
    ok("a staged D3 program is outside the gate while D3 is not published", passed)
    passed, out = gate(reg(prog("data-a"), d3, divisions=("D1", "D2", "D3")), has_athletics=has, reviewed={})
    # fails if the gate ever keys on a hard-coded division list instead of the published set
    ok("the same D3 program fails the moment D3 is published", not passed and "GATE empty-d3:" in out, out)
    passed, _ = gate(reg(prog("data-a"), prog("empty-d3", "D3", skipReason="HTTP 403"), divisions=("D1", "D2", "D3")), has_athletics=has, reviewed={})
    ok("and passes with its skipReason", passed)


# ---------- committed ----------

def test_committed(registry: dict) -> None:
    print("committed: the gate on public/data/registry.json")
    passed, out = gate(registry)
    # fails if a published program loses its data and its reason, or a reason goes stale
    ok("the gate passes on the committed registry", passed, out)
    ok("the reviewed list starts empty (plan revision 1 on #94)", build.PUBLISH_GATE_REVIEWED == {}, str(build.PUBLISH_GATE_REVIEWED))
    published = build.published_programs(registry)
    no_data = {p["slug"] for p in published if not os.path.isfile(common.source_path(p["slug"], "athletics"))}
    browser = {p["slug"] for p in published if (p.get("athletics") or {}).get("rosterRequiresBrowser") is True}
    ok("the published programs flagged rosterRequiresBrowser are the six D1 programs Huatuo named on #94", browser == BROWSER_D1,
       str(sorted(browser ^ BROWSER_D1)))
    ok("each of the six has no athletics source", BROWSER_D1 <= no_data, str(sorted(BROWSER_D1 - no_data)))
    # not a check: what the gate would say if D3 were switched on with today's registry (#94 PR 4 must reach 0)
    d3 = copy.deepcopy(registry)
    d3["onboardedDivisions"] = sorted(set(d3.get("onboardedDivisions") or []) | {"D3"})
    _, out = gate(d3)
    lines = [ln for ln in out.splitlines() if ln.startswith("GATE ")]
    print(f"  note: with D3 published on today's registry the gate would name {len(lines)} programs")


def test_mutations(registry: dict) -> None:
    print("mutations: the committed registry with one reason removed or one stale entry added")
    by_slug = {p["slug"]: p for p in registry["programs"]}

    def without(slug, key):
        r = copy.deepcopy(registry)
        for p in r["programs"]:
            if p["slug"] == slug:
                p["athletics"].pop(key, None)
        return r
    for slug in sorted(BROWSER_D1):
        passed, out = gate(without(slug, "rosterRequiresBrowser"))
        ok(f"removing rosterRequiresBrowser from {slug} fails the gate", not passed and f"GATE {slug}:" in out, out)
    published = {p["slug"] for p in build.published_programs(registry)}
    refused = sorted(s for s in published if (by_slug[s].get("athletics") or {}).get("skipReason")
                     and not os.path.isfile(common.source_path(s, "athletics")))
    ok("the committed registry has a published refused program to mutate", bool(refused))
    for slug in refused[:3]:
        passed, out = gate(without(slug, "skipReason"))
        ok(f"removing skipReason from {slug} ({by_slug[slug].get('division')}) fails the gate", not passed and f"GATE {slug}:" in out, out)
    with_data = next(s for s in sorted(published) if os.path.isfile(common.source_path(s, "athletics")))
    passed, out = gate(registry, reviewed={with_data: {"reason": "test", "date": "2026-09-23"}})
    ok(f"a reviewed entry for {with_data}, which has data, fails as stale", not passed and "now has athletics data" in out, out)
    held = (registry.get("heldPrograms") or [{}])[0].get("slug") or "saint-francis"
    passed, out = gate(registry, reviewed={held: {"reason": "test", "date": "2026-09-23"}})
    ok(f"a reviewed entry for {held}, which is not published, fails as stale", not passed and "not published" in out, out)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    VERBOSE = ap.parse_args(argv).verbose
    registry = common.load_registry()
    test_synthetic()
    test_committed(registry)
    test_mutations(registry)
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
