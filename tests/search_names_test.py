"""Checks for build.search_names(), the list of names the search index publishes per program
(issue #200, follow-up).

    python tests/search_names_test.py            # everything below, offline
    python tests/search_names_test.py --verbose  # print every check, not only the failures

Offline: calls build.search_names() directly on hand-built program dicts. Writes nothing.

Swap-back proof: set COLLEGEDASH_CODE_ROOT to an export of origin/main's build.py, and build.py is
imported from there:

    git archive origin/main build.py collect | tar -x -C /tmp/pre200
    COLLEGEDASH_CODE_ROOT=/tmp/pre200 python tests/search_names_test.py

Why this exists
----------------
Filling a D2 program's shortName by dropping a trailing "University"/"College" (issue #200's mechanical
rule, e.g. "Grand Valley State University" -> "Grand Valley State") changes what search_names() computes
initials from. Before shortName existed, the client fell back to the full official name, so a search for
"GVSU" matched by the initials of all four words of "Grand Valley State University". Once shortName is
the three-word "Grand Valley State", the initials shrink to "GVS" and "GVSU" stops matching -- a real
regression the TPM asked not to accept.

search_names() now also adds initials computed from the shortName plus a dropped, purely generic trailing
word ("University"/"College"), restoring the four-letter form, gated tightly so an unrelated long name can
never contribute noise: it only fires when the full name is EXACTLY the shortName followed by nothing but
that one generic word (at most two).

Labels: FIX checks fail against origin/main (before this change) and pass after it; CONTROL checks pass on
both, guarding against a fix broad enough to invent noise for names it should leave alone.
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_ROOT = os.environ.get("COLLEGEDASH_CODE_ROOT") or ROOT
sys.path.insert(0, CODE_ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import build  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def prog(short, name, **extra):
    return {"shortName": short, "name": name, "ids": {}, **extra}


def test_restored_initials() -> None:
    print("restored: initials of the full name, not just the shortened one")
    sn = build.search_names(prog("Grand Valley State", "Grand Valley State University"))
    # FIX: fails on origin/main, where only 'GVS' (the shortName's own initials) is produced
    ok("FIX 'GVSU' is a search name for Grand Valley State", "GVSU" in sn, str(sn))
    ok("CONTROL the shortName's own initials ('GVS') still appear too", "GVS" in sn, str(sn))
    ok("CONTROL the short name and the full name are both still present", {"Grand Valley State",
       "Grand Valley State University"} <= set(sn), str(sn))

    # A trailing "College" is dropped the same way as "University"
    sn2 = build.search_names(prog("Belmont Abbey", "Belmont Abbey College"))
    ok("FIX a dropped trailing College is restored too ('BAC')", "BAC" in sn2, str(sn2))

    # Real-world collision check: two different Wikipedia-sourced D2 shortNames of the same length and
    # shape ('Ferris State' / 'Fairmont State' / 'Frostburg State') all reduce to the same 'FSU' -- that
    # is an accepted, pre-existing property of initials-based search (nicknames already collide the same
    # way, e.g. 'Lakers'), not something this fix needs to prevent.
    fsu_hits = [n for n in ("Ferris State", "Fairmont State", "Frostburg State")
                if "FSU" in build.search_names(prog(n, n + " University"))]
    ok("FIX multiple programs may legitimately share an initials search name", len(fsu_hits) == 3, str(fsu_hits))


def test_gated_against_noise() -> None:
    print("gated: an unrelated long name never contributes a new, made-up initials string")
    # CONTROL: name does not start with "shortName " at all (a leading-strip case: "University of X")
    sn = build.search_names(prog("Central Missouri", "University of Central Missouri"))
    ok("CONTROL a leading-strip shortName ('University of X' -> X) adds nothing new", len(sn) == 2, str(sn))

    # CONTROL: shortName keeps the state name, dropping BOTH a leading "University of" and a trailing
    # campus qualifier -- name does not start with "North Carolina ", so nothing fires
    sn2 = build.search_names(prog("North Carolina", "University of North Carolina at Chapel Hill"))
    ok("CONTROL a two-sided reduction (drops a prefix AND a suffix) adds nothing new", len(sn2) == 2, str(sn2))

    # CONTROL: the word right after shortName is not purely generic ("Pennsylvania", not "University"/
    # "College" alone) -- must not fire just because the name happens to start with the shortName text
    sn3 = build.search_names(prog("Indiana", "Indiana University of Pennsylvania"))
    ok("CONTROL a non-generic trailing qualifier ('of Pennsylvania') adds nothing new", len(sn3) == 2, str(sn3))

    # CONTROL: shortName already covers the whole name (no trailing words at all)
    sn4 = build.search_names(prog("Barry", "Barry University"))
    # 'Barry' is one word, so the existing >=3-word gate already blocks an initials entry from the
    # shortName alone; the new rule must not add a 2-letter 'BU' either (len(full_words) < 3)
    ok("CONTROL a one-word shortName plus 'University' still adds no initials (fewer than 3 words)",
       sn4 == ["Barry", "Barry University"], str(sn4))

    # CONTROL: more than two trailing words, even if the first is generic, does not fire
    sn5 = build.search_names(prog("Test State", "Test State University System"))
    ok("CONTROL more than the generic word(s) alone after shortName adds nothing new", len(sn5) == 2, str(sn5))


def test_still_ordered_and_deduped() -> None:
    print("unchanged: order and de-duplication")
    sn = build.search_names(prog("UC Santa Barbara", "University of California, Santa Barbara"))
    ok("CONTROL the pre-existing 3+-word shortName initials rule is untouched ('UCSB')", "UCSB" in sn, str(sn))
    ok("CONTROL the new rule does not fire when name does not start with shortName",
       sn == ["UC Santa Barbara", "University of California, Santa Barbara", "UCSB"], str(sn))

    sn2 = build.search_names(prog("Ferris State", "Ferris State University"))
    ok("FIX the new initials entry comes after the existing ones, nothing reordered",
       sn2 == ["Ferris State", "Ferris State University", "FSU"], str(sn2))
    # calling twice gives the same result (no hidden state)
    ok("CONTROL search_names is pure", build.search_names(prog("Ferris State", "Ferris State University")) == sn2)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    if CODE_ROOT != ROOT:
        print(f"code under test imported from {CODE_ROOT}")
    for case in (test_restored_initials, test_gated_against_noise, test_still_ordered_and_deduped):
        try:
            case()
        except Exception as e:  # a case that raises is a failed case, not a lost run
            ok(f"{case.__name__} ran to the end", False, f"{type(e).__name__}: {e}")
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
