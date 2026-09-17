"""Checks for build.build_roster's club-source label (issue #227 bug 2).

    python tests/build_club_source_test.py            # everything below, offline
    python tests/build_club_source_test.py --verbose  # print every check, not only the failures

Offline: builds a roster in memory from a minimal athletics-source dict shaped like a stored
programs/*/sources/athletics.json. Writes nothing.

Swap-back proof: set COLLEGEDASH_CODE_ROOT to an export of origin/main's build.py, and build.py is
imported from there:

    git archive origin/main build.py collect | tar -x -C /tmp/pre227
    COLLEGEDASH_CODE_ROOT=/tmp/pre227 python tests/build_club_source_test.py

Why this exists
----------------
`build_roster` labelled any club already sitting on a roster row "bio text (unverified)" - as if
it had come from a player's bio page and hadn't been checked. It never had: the weekly/full
refresh always runs with `--no-bios` (see collect/athletics_site.py's `bios` switch), so no stored
roster row carries a `bio` key with a club field, and the only way `q.get("club")` is ever
non-empty here is that the Sidearm/WMT roster table itself had a Club column (#225's discovery
report: all 697 players published with this label). The fix is a truthful label - "roster page" -
for the same, unchanged value; the commitment-record path (SoccerWire / TopDrawerSoccer, still
preferred over the roster column) is untouched.
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
        print(f"  FAIL {name}" + (f" - {str(detail)[:400]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def player(name, club="", pos="F", class_code="FR") -> dict:
    return {"number": "", "name": name, "pos": pos, "posLabel": pos, "height": "", "heightIn": None,
            "classLabel": class_code, "classCode": class_code, "hometown": "", "highSchool": "",
            "previousSchool": "", "major": "", "club": club, "bioUrl": None, "social": {}}


def ath_with(players: list[dict]) -> dict:
    return {"data": {"roster": {"season": 2026, "players": players}, "rosterHistory": {}}}


def by_name(roster: dict) -> dict[str, dict]:
    return {p["name"]: p for p in roster["players"]}


def test_roster_column_club_is_labelled_roster_page_not_bio() -> None:
    print("a club already on the roster row (the table's own Club column) is labelled 'roster page'")
    ath = ath_with([player("Kylie Odom", club="Michigan Hawks")])
    roster, _ = build.build_roster(ath, club_lookup={})
    p = by_name(roster)["Kylie Odom"]
    ok("club is unchanged", p["club"] == "Michigan Hawks", p["club"])
    ok("clubSource is 'roster page', not 'bio text (unverified)' (issue #227 bug 2)",
       p["clubSource"] == "roster page", p["clubSource"])
    ok("... and the word 'bio' is nowhere in the label - no stored roster row has ever had a bio "
       "club field (the refresh runs --no-bios)", "bio" not in (p["clubSource"] or "").lower(), p["clubSource"])


def test_commitment_record_still_wins_and_keeps_its_own_source() -> None:
    print("control: a commitment-record match is unaffected by the roster-page label change")
    ath = ath_with([player("Kylie Odom", club="Michigan Hawks")])  # roster column disagrees with the commit record
    lookup = {build.common.norm_name("Kylie Odom"): {"club": "Michigan Rush", "source": "SoccerWire"}}
    roster, _ = build.build_roster(ath, club_lookup=lookup)
    p = by_name(roster)["Kylie Odom"]
    ok("club comes from the commitment record, not the roster column", p["club"] == "Michigan Rush", p["club"])
    ok("clubSource names the commitment source", p["clubSource"] == "SoccerWire", p["clubSource"])


def test_no_club_anywhere_is_still_none() -> None:
    print("control: a player with no club at all still gets clubSource None")
    ath = ath_with([player("Ava Chen", club="")])
    roster, _ = build.build_roster(ath, club_lookup={})
    p = by_name(roster)["Ava Chen"]
    ok("club stays empty", p["club"] == "", p["club"])
    ok("clubSource is None, not a label for data that isn't there", p["clubSource"] is None, p["clubSource"])


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose
    for case in (test_roster_column_club_is_labelled_roster_page_not_bio,
                 test_commitment_record_still_wins_and_keeps_its_own_source,
                 test_no_club_anywhere_is_still_none):
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
