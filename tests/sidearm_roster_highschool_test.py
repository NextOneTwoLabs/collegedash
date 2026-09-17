"""Checks for the Sidearm roster table's high-school / previous-school columns (issue #227).

    python tests/sidearm_roster_highschool_test.py            # everything below, offline
    python tests/sidearm_roster_highschool_test.py --verbose  # print every check, not only the failures

Offline: reads two fixtures under tests/fixtures/sidearm/ and makes no request.

Why these exist
----------------
`parse_roster_tables`'s `ci["hs"]` column lookup was `_col(idx, "high school", "previous", "last
school")`. `_col`'s exact-match pass tries "high school" first, so a page with a real "High
School" column was never touched. The break was in `_col`'s PREFIX pass, which tries one
candidate at a time across every header: once "high school" matched nothing, it went on to try
"previous" and "last school" as prefixes, and a page whose combined "Hometown / High School"
column sits beside a separate, genuine "Previous School" column (holding a transfer's prior
COLLEGE) has no header starting with "high school" - so that real "Previous School" column won
`ci["hs"]` instead. Two things followed: a transfer's previous college was published as their
high school, and `ci["hs"] is not None` skipped the one rule able to split the combined column -
so a current (non-transfer) player on the very same page got no high school at all, even though
it was sitting right there before the slash. Measured over the cached pages (#225's discovery
report): 104 Sidearm programs, 2,023 current rows with an empty high school, 6,307 more across
past rosters; fixing it lifts current-roster high-school coverage from 65.5% to 87.0% with no new
requests. `build.py`'s `build_roster` labelling those roster-column clubs "bio text (unverified)"
(no stored row has ever carried a bio field, since the refresh runs --no-bios) is #227's bug 2 and
is covered by build_test.py, not here.

The fix is two independent, narrower column lookups instead of one shared one: a real "High
School" column only (`_col(idx, "high school")`), and a real previous-school column only
(`_prev_col`, which also refuses any header that says "club" or "team" - see its own docstring
and `test_prev_col_excludes_club_and_team_columns` below). When neither exists, the pre-existing
"Hometown / High School" split (guarded by `ci["hs"] is None`) is unchanged.

roster-hometown-highschool-previous-school is trimmed from Oakland's cached page: the exact header
shape the bug hit (43+ of the 104 affected pages carry it), with a clean split, a real transfer,
a three-part combined cell, and an empty-previous-school row.

roster-previous-team-is-a-club is trimmed from Ohio's cached page: a column whose visible header
says "Previous Team" and whose value is a club name, proving that column is never read into
previousSchool.

roster-previous-team-ambiguous-high-school-or-college is trimmed from California Baptist's cached
page: a page whose ONLY school-ish column is also titled "Previous Team", but with no better
source anywhere on the page (no combined Hometown/High School column, no separate Previous
School), and holding a genuine mix of real high schools, real transfer colleges and one club with
no way to tell them apart. Here the fix keeps publishing that column into highSchool exactly as
today's code does, per the brief's rule for an unsplittable cell: keep today's value rather than
invent an empty one.

roster-hometown-no-slash-real-previous-school is trimmed from Hampton's cached page: a row whose
combined column is hometown-only (nothing after the slash) on a page that also has a real,
separate Previous School column. It pins the guard that stops the last-resort fallback above from
reading that real Previous School column into highSchool for this row - the one case tiers 1 and 2
don't reach on an otherwise-#227-shaped page.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect.adapters import sidearm  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "sidearm")
HS_PREV = "roster-hometown-highschool-previous-school.html"
PREV_TEAM = "roster-previous-team-is-a-club.html"
PREV_TEAM_AMBIGUOUS = "roster-previous-team-ambiguous-high-school-or-college.html"
NO_SLASH_REAL_PREV = "roster-hometown-no-slash-real-previous-school.html"
FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def read(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def players_by_name(html: str, base: str) -> dict[str, dict]:
    r = sidearm.parse_roster(html, base)
    return {p["name"]: p for p in r["players"]}


def test_hometown_high_school_splits_when_a_real_previous_school_column_exists() -> None:
    print("combined 'Hometown / High School' beside a real 'Previous School' column (issue #227 bug 1)")
    players = players_by_name(read(HS_PREV), "https://goldengrizzlies.com")
    ok("all five rows parsed", len(players) == 5, sorted(players))

    z = players.get("Julia Zangerl", {})
    ok("Julia Zangerl: hometown/high school split cleanly",
       (z.get("hometown"), z.get("highSchool")) == ("Tirol, Austria", "Sportandels Akademie"),
       (z.get("hometown"), z.get("highSchool")))
    ok("Julia Zangerl: previous school is read from its own column, not invented",
       z.get("previousSchool") == "FC Wacker Innsbruck", z.get("previousSchool"))

    s = players.get("Sunniva Raaen", {})
    ok("Sunniva Raaen: high school still splits out even with no previous school on the row",
       (s.get("hometown"), s.get("highSchool")) == ("Hønefoss, Norway", "Ringerike Videregaende Skole"),
       (s.get("hometown"), s.get("highSchool")))
    ok("Sunniva Raaen: previous school stays empty, not invented", s.get("previousSchool") == "", s.get("previousSchool"))


def test_transfer_previous_college_stays_out_of_high_school() -> None:
    print("named transfer test (issue #227): a real sanitised row, Hannah Russell")
    players = players_by_name(read(HS_PREV), "https://goldengrizzlies.com")
    russell = players.get("Hannah Russell", {})
    ok("Hannah Russell: high school is her actual high school, not her previous college",
       russell.get("highSchool") == "Riverside", russell.get("highSchool"))
    ok("Hannah Russell: previous college lands in previousSchool, never highSchool",
       russell.get("previousSchool") == "St. Francis College (BKN)", russell.get("previousSchool"))
    ok("Hannah Russell: hometown is just the city/state, not the whole combined cell",
       russell.get("hometown") == "Riverside, N.J.", russell.get("hometown"))
    ok("... and the previous college string is nowhere in the published hometown or high school",
       "St. Francis" not in russell.get("hometown", "") and "St. Francis" not in russell.get("highSchool", ""),
       (russell.get("hometown"), russell.get("highSchool")))

    sazali = players.get("Putri Sazali", {})
    ok("Putri Sazali: another real transfer, same rule",
       (sazali.get("highSchool"), sazali.get("previousSchool")) == ("Queensway Secondary", "East Florida State"),
       (sazali.get("highSchool"), sazali.get("previousSchool")))


def test_three_part_combined_cell_is_kept_whole_not_invented() -> None:
    print("a combined cell with three slash-separated parts (issue #227: never invent a high school)")
    players = players_by_name(read(HS_PREV), "https://goldengrizzlies.com")
    mudd = players.get("Frankie Mudd", {})
    # 'Clinton Twp, Mich. / Chippewa Valley / Nationals': splitting only at the FIRST slash keeps
    # the ambiguous remainder together rather than guessing which of the last two parts is the
    # real high school and which is something else (here, a club name the site jammed in too).
    ok("hometown is just the city/state (split at the first slash only)",
       mudd.get("hometown") == "Clinton Twp, Mich.", mudd.get("hometown"))
    ok("high school keeps the whole ambiguous remainder, rather than guessing which part to drop",
       mudd.get("highSchool") == "Chippewa Valley / Nationals", mudd.get("highSchool"))
    ok("previous school stays empty: this page's own Previous School column was blank for her",
       mudd.get("previousSchool") == "", mudd.get("previousSchool"))


def test_previous_team_column_is_never_read_as_previous_school() -> None:
    print("a 'Previous Team' column holds a club, not a school (issue #227)")
    players = players_by_name(read(PREV_TEAM), "https://gobobcats.com")
    ok("both rows parsed", len(players) == 2, sorted(players))
    mandleur = players.get("Madison Mandleur", {})
    ok("high school reads normally", mandleur.get("highSchool") == "East Brunswick", mandleur.get("highSchool"))
    ok("the club in the 'Previous Team' cell ('PDA') is never published as previousSchool",
       mandleur.get("previousSchool") == "", mandleur.get("previousSchool"))
    ok("... and it is not published as club either (this table has no Club column)",
       mandleur.get("club") == "", mandleur.get("club"))
    jarvis = players.get("Olivia Jarvis", {})
    ok("an ordinary row (empty previous-team cell) is unaffected",
       (jarvis.get("highSchool"), jarvis.get("previousSchool")) == ("Simsbury", ""),
       (jarvis.get("highSchool"), jarvis.get("previousSchool")))


def test_ambiguous_previous_team_column_keeps_todays_value_when_nothing_better_exists() -> None:
    print("no explicit High School, no combined column, no real Previous School (issue #227: keep today's value)")
    players = players_by_name(read(PREV_TEAM_AMBIGUOUS), "https://cbulancers.com")
    ok("all three rows parsed", len(players) == 3, sorted(players))

    winton = players.get("Rebecca Winton", {})
    ok("a real high school under 'Previous Team' is still published as highSchool",
       winton.get("highSchool") == "ThunderRidge HS", winton.get("highSchool"))
    ok("... and never invented into previousSchool instead", winton.get("previousSchool") == "", winton.get("previousSchool"))

    jestrovic = players.get("Anja Jestrovic", {})
    ok("a real transfer college under the same header is ALSO kept in highSchool (unsplittable: "
       "no marker on the page says which of the two this is)",
       jestrovic.get("highSchool") == "Creighton University", jestrovic.get("highSchool"))

    sekhon = players.get("Ryeesa Sekhon", {})
    ok("a club under the same header, same rule: kept as today's code keeps it",
       sekhon.get("highSchool") == "Chelsea FC U18", sekhon.get("highSchool"))


def test_no_slash_row_never_falls_through_to_the_real_previous_school_column() -> None:
    print("guard: a blank combined cell must not resurrect issue #227's bug via the last-resort fallback")
    players = players_by_name(read(NO_SLASH_REAL_PREV), "https://hamptonpirates.com")
    ok("both rows parsed", len(players) == 2, sorted(players))

    dah_zossu = players.get("Alvine Dah-Zossu", {})
    ok("no high school is invented for a combined cell with nothing after the slash",
       dah_zossu.get("highSchool") == "", dah_zossu.get("highSchool"))
    ok("her previous college is still read from the real Previous School column",
       dah_zossu.get("previousSchool") == "North Idaho College", dah_zossu.get("previousSchool"))
    ok("... and never duplicated into highSchool by the last-resort fallback",
       "North Idaho" not in dah_zossu.get("highSchool", ""), dah_zossu.get("highSchool"))

    sutton = players.get("Jayda Sutton", {})
    ok("an ordinary row on the same page still splits normally",
       (sutton.get("hometown"), sutton.get("highSchool")) == ("Chesapeake, Va.", "Western Branch HS"),
       (sutton.get("hometown"), sutton.get("highSchool")))


def test_prev_col_excludes_club_and_team_columns() -> None:
    print("_prev_col: unit checks for the header shapes measured in the cached corpus (issue #227)")
    cases = [
        ({"previous school": 5}, 5, "a plain 'Previous School' column"),
        ({"previous college": 3}, 3, "a plain 'Previous College' column"),
        ({"last school": 2}, 2, "a plain 'Last School' column"),
        ({"previous": 6}, 6, "a bare 'Previous' column (jmusports.com), exact match only"),
        ({"previous team": 4}, None, "'Previous Team' holds a club (gobobcats.com: 'PDA')"),
        ({"club team / previous school": 1}, None, "miamiredhawks.com: value is a club ('Kings Hammer ECNL')"),
        ({"previous school/club team": 7}, None, "a combined previous-school/club header: unreliable, left unread"),
        ({"hometown/previous school": 0}, None, "starts with 'hometown': a combined column for _split_slash, not this"),
        ({"hometown (prev school)": 0, "previous school": 2}, 2, "a real 'Previous School' column beside a "
         "hometown-prefixed one that merely mentions 'prev school' in its own label"),
        ({}, None, "no school-ish column at all"),
    ]
    for idx, want, desc in cases:
        got = sidearm._prev_col(idx)
        ok(f"_prev_col({idx!r}) == {want!r}  [{desc}]", got == want, got)


def test_fixture_carries_no_contact_details() -> None:
    print("privacy: the fixtures have no email, phone, mailto: or tel:")
    text = read(HS_PREV) + "\n" + read(PREV_TEAM) + "\n" + read(PREV_TEAM_AMBIGUOUS) + "\n" + read(NO_SLASH_REAL_PREV)
    for label, rx in [("email", r"[\w.+-]+@[\w-]+\.[\w.]+"), ("mailto", r"mailto:"), ("tel", r"tel:"),
                      ("10-digit phone", r"\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}\b"), ("7-digit phone", r"\b\d{3}[\s.-]\d{4}\b")]:
        found = re.findall(rx, text, re.I)
        ok(f"no {label}", not found, found[:3])


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose
    for case in (test_hometown_high_school_splits_when_a_real_previous_school_column_exists,
                 test_transfer_previous_college_stays_out_of_high_school,
                 test_three_part_combined_cell_is_kept_whole_not_invented,
                 test_previous_team_column_is_never_read_as_previous_school,
                 test_ambiguous_previous_team_column_keeps_todays_value_when_nothing_better_exists,
                 test_no_slash_row_never_falls_through_to_the_real_previous_school_column,
                 test_prev_col_excludes_club_and_team_columns,
                 test_fixture_carries_no_contact_details):
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
