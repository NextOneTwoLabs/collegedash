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
import json
import os
import re
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


def test_registry_aliases() -> None:
    print("#309: the registry's cited searchAliases are published verbatim, after the derived names")
    sn = build.search_names(prog("North Carolina", "University of North Carolina at Chapel Hill"), ["UNC"])
    ok("FIX 'UNC' is a search name for North Carolina", "UNC" in sn, str(sn))
    ok("CONTROL no alias argument, no alias", build.search_names(prog("North Carolina", "University of North Carolina at Chapel Hill")) == sn[:-1], str(sn))
    sn2 = build.search_names({"shortName": None, "name": "Washington University in St. Louis", "ids": {"rpiHistoryName": "WashU"}}, ["WashU"])
    ok("FIX an alias is not CamelCase-split like an archive name ('WashU' stays 'WashU')", "WashU" in sn2 and "Wash U" in sn2, str(sn2))
    ok("CONTROL an alias equal to an existing name (any case) is not duplicated",
       build.search_names(prog("Cal Poly", "Cal Poly"), ["cal poly"]) == ["Cal Poly"])


def _own_name_says_state(p: dict) -> bool:
    """The issue #513 rule, restated independently of build.py: the program's own name or short name
    says 'State' and says neither 'Saint' nor 'St'/'St.'."""
    own = f"{p.get('name') or ''} {p.get('shortName') or ''}"
    return bool(re.search(r"\bState\b", own)) and not re.search(r"\bSaint\b|\bSt\b", own)


# Frozen fixtures for #513: the name fields of four real programs, copied from the committed
# public/data/programs/<slug>.json (and searchAliases from public/data/registry.json) on 2026-10-22,
# so these checks never move with a data refresh.
ALIASES_513 = {"cal-state-fullerton": ["CSUF"]}
FIXTURE_513 = {
    "cal-state-fullerton": {"shortName": "Cal State Fullerton", "name": "California State University, Fullerton",
                            "ids": {"ncaaName": "Cal St. Fullerton", "rpiHistoryName": "CalStateFullerton"}},
    "saint-mary-s": {"shortName": "Saint Mary's", "name": "Saint Mary's College of California",
                     "ids": {"ncaaName": "Saint Mary's (CA)", "rpiHistoryName": "StMarys"}},
    "mount-st-marys": {"shortName": "Mount St. Mary's", "name": "Mount St. Mary's University",
                       "ids": {"ncaaName": "Mount St. Mary's", "rpiHistoryName": "MountStMary"}},
    "ohio-state": {"shortName": "Ohio State", "name": "Ohio State University",
                   "ids": {"ncaaName": "Ohio St.", "rpiHistoryName": "OhioState"}},
}


def test_st_means_state() -> None:
    print("#513: an NCAA 'St.' on a program whose own name says State is State, not Saint")
    fx = {slug: build.search_names(p, ALIASES_513.get(slug, ())) for slug, p in FIXTURE_513.items()}
    csuf = fx["cal-state-fullerton"]
    ok("FIX cal-state-fullerton has no 'Saint' search name", not any("Saint" in n for n in csuf), str(csuf))
    ok("FIX cal-state-fullerton publishes exactly its own names, NCAA 'Cal St. Fullerton' kept verbatim",
       csuf == ["Cal State Fullerton", "California State University, Fullerton", "Cal St. Fullerton", "CSUF", "CSF"],
       str(csuf))
    ok("CONTROL Saint Mary's keeps its 'Saint' and 'St' forms",
       fx["saint-mary-s"] == ["Saint Mary's", "Saint Mary's College of California", "St Marys", "St Mary's",
                              "St Mary's College of California", "Saint Marys"], str(fx["saint-mary-s"]))
    ok("CONTROL Mount St. Mary's (St. means Saint) still gains its 'Saint' forms",
       fx["mount-st-marys"] == ["Mount St. Mary's", "Mount St. Mary's University", "Mount St Mary", "MSM", "MSMU",
                                "Mount Saint Mary's", "Mount Saint Mary's University", "Mount Saint Mary"],
       str(fx["mount-st-marys"]))
    ok("CONTROL a trailing 'Ohio St.' is untouched (no Saint, nothing invented)",
       fx["ohio-state"] == ["Ohio State", "Ohio State University", "Ohio St.", "OSU"], str(fx["ohio-state"]))
    # A mid-name 'St.' on a State-side program with no plain State form elsewhere becomes 'State'.
    sn = build.search_names({"shortName": "Test State", "name": "Test State University",
                             "ids": {"ncaaName": "Test St. Upstate"}})
    ok("FIX a State-side mid-name 'St.' expands to 'State'", "Test State Upstate" in sn and
       not any("Saint" in n for n in sn), str(sn))

    # Every committed profile, recomputed with the code under test. No counts pinned (the data moves);
    # only the rule: a State-side program never gets a Saint name, and every other program with a
    # mid-name 'St. ' still gets its Saint form (the swap is untouched there).
    prog_dir = os.path.join(ROOT, "public", "data", "programs")
    with open(os.path.join(prog_dir, "index.json"), encoding="utf-8") as fh:
        index = json.load(fh)
    bad, saint_kept, seen = [], [], 0
    for row in index["programs"]:
        with open(os.path.join(prog_dir, f"{row['slug']}.json"), encoding="utf-8") as fh:
            p = json.load(fh)
        sn = build.search_names(p)
        seen += 1
        if _own_name_says_state(p):
            if any(re.search(r"\bSaint\b", n) for n in sn):
                bad.append((row["slug"], sn))
        elif any(re.search(r"\bSt\.?\s", n) for n in sn):
            saint_kept.append(any(re.search(r"\bSaint\b", n) for n in sn))
    ok("CONTROL the committed index was read", seen > 0, str(seen))
    ok("FIX no committed State-side program gets a 'Saint' search name", not bad, str(bad))
    ok("CONTROL every non-State-side program with a 'St. ' name still gets its 'Saint' form",
       bool(saint_kept) and all(saint_kept), f"{saint_kept.count(False)} of {len(saint_kept)} lost it")


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    if CODE_ROOT != ROOT:
        print(f"code under test imported from {CODE_ROOT}")
    for case in (test_restored_initials, test_gated_against_noise, test_still_ordered_and_deduped, test_registry_aliases,
                 test_st_means_state):
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
