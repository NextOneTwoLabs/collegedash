"""Checks for who the Sidearm adapter calls the head coach (issue #33).

    python tests/sidearm_staff_test.py            # everything below, offline
    python tests/sidearm_staff_test.py --verbose  # print every check, not only the failures

Offline: reads nine fixtures under tests/fixtures/sidearm/ and makes no request.

Why these exist
---------------
`HEAD_COACH_RE` was the literal `head coach`, so a program whose staff page says "Head Women's
Soccer Coach" had no head coach at all: `program.headCoach.name` was null, the Staff tab's hero
read "-", and the person was published as an ordinary member of the coaching staff. Measured over
the 313 cached Sidearm roster pages, 41 pages were in that state, and at the published level 35
programs gained a head coach from this change, 7 more replaced a bare Wikipedia name with the
school's own spelling and title, and none lost or swapped one.

The direction that matters more than the fix is the other one. The pattern the issue proposed,
`head\\b.*\\bcoach`, also matches six rows in the same corpus that belong to somebody else - four
spellings of "Head Strength & Conditioning Coach", "Head Olympic Strength and Conditioning Coach"
and "Head Sports Performance Coach (Women's Soccer, Softball, Men's Tennis, Golf)" - and two rows
today's pattern already gets wrong, "Former Head Coach (1979-2024)" and a page that spells it
"Assosicate Head Coach". On every one of those pages the real head coach happens to be listed
first, so build.py publishes the right person by luck rather than by rule. These fixtures pin the
rule instead of the luck.

The fixtures are the staff tables of real cached pages, with the email and phone columns removed:

  roster-head-womens-soccer-coach  army: the form 31 pages use, over an "Associate Head Women's
                                   Soccer Coach" who must not win it
  roster-head-soccer-coach         prairie-view-am: "Head Soccer Coach" over "Associate Head
                                   Soccer Coach"
  roster-head-womens-coach         memphis: "Head Women's Coach", with two associates under it
  roster-typographic-apostrophe    evansville: "Head Women's Soccer Coach" written with U+2019,
                                   the only non-ASCII character in any staff title in the corpus
  roster-strength-coach            colorado-state: a real head coach and a real "Head Olympic
                                   Strength and Conditioning Coach" on one page
  roster-sports-performance-coach  uic: "Head Sports Performance Coach (Women's Soccer, ...)",
                                   a title that names women's soccer and is not the head coach
  roster-former-head-coach         north-carolina: Anson Dorrance, listed under his successor
  roster-misspelled-associate      indiana-state: "Assosicate Head Coach"
  roster-co-head-coaches           butler: two "Co-Head Coach" rows, because there are two

`test_origin_behaviour` and `test_the_sketch_over_matches` are the swap-back proof: the rules
before this change, and the one the issue proposed, are written out here and run against the same
fixtures, so what each of them does lives in the suite rather than in a reviewer's terminal.
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
BASE = "https://example.invalid"

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {ascii(detail)[:400]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def staff(name: str) -> list[dict]:
    with open(os.path.join(FIXTURES, name + ".html"), encoding="utf-8") as f:
        return sidearm.parse_roster(f.read(), BASE)["staff"]


def heads(rows: list[dict]) -> list[dict]:
    return [s for s in rows if s["isHeadCoach"]]


# The rules before this change, copied from origin/main, and the one issue #33 proposed.
ORIGIN_HEAD_RE = re.compile(r"head coach", re.I)
ORIGIN_NOT_HEAD_RE = re.compile(r"assoc|assist|volunteer|director of (?:operations|ops)", re.I)
SKETCH_HEAD_RE = re.compile(r"head\b.*\bcoach", re.I)


def origin_is_head(title: str) -> bool:
    return bool(ORIGIN_HEAD_RE.search(title)) and not ORIGIN_NOT_HEAD_RE.search(title)


def sketch_is_head(title: str) -> bool:
    return bool(SKETCH_HEAD_RE.search(title)) and not ORIGIN_NOT_HEAD_RE.search(title)


# fixture -> (head coach's name, that person's title)
EXPECTED = {
    "roster-head-womens-soccer-coach": ("Tracy Chao", "Head Women's Soccer Coach"),
    "roster-head-soccer-coach": ("Abe García", "Head Soccer Coach"),
    "roster-head-womens-coach": ("Brooks Monaghan", "Head Women's Coach"),
    "roster-typographic-apostrophe": ("Chris Pfau", "Head Women’s Soccer Coach"),
    "roster-strength-coach": ("Keeley Hagen", "Head Coach"),
    "roster-sports-performance-coach": ("David Nikolic", "Head Coach"),
    "roster-former-head-coach": ("Damon Nahas", "Head Coach"),
    "roster-misspelled-associate": ("Paul Lawrence", "Head Coach"),
    "roster-co-head-coaches": ("Tari St. John", "Co-Head Coach"),
}
# the four the literal `head coach` could not see at all
GAP_FIXTURES = ["roster-head-womens-soccer-coach", "roster-head-soccer-coach",
                "roster-head-womens-coach", "roster-typographic-apostrophe"]


def test_every_fixture_publishes_its_head_coach() -> None:
    """The person build.py would publish - the first flagged row - is the right one, on every page."""
    print("the head coach on each page")
    for name, (want_name, want_title) in EXPECTED.items():
        rows = staff(name)
        found = heads(rows)
        ok(f"{name}: somebody is the head coach", bool(found), f"{len(rows)} staff, none flagged")
        if not found:
            continue
        ok(f"{name}: it is {want_name}", (found[0]["name"], found[0]["title"]) == (want_name, want_title),
           f"{found[0]['name']} / {found[0]['title']}")
        ok(f"{name}: the flagged row is the one build.py takes, first in page order",
           rows.index(found[0]) == min(rows.index(s) for s in found))


def test_nobody_else_is_flagged() -> None:
    """Across all nine pages, 10 of the 60 staff rows are a head coach and the rest are not.

    This is the check that fails when the rule widens: every associate, assistant, strength coach,
    trainer, operations director and former coach on these pages is counted here.
    """
    print("nobody else on the page")
    total, flagged = 0, []
    for name in EXPECTED:
        rows = staff(name)
        total += len(rows)
        flagged += [(name, s["title"]) for s in heads(rows)]
    ok("60 staff rows across the nine pages", total == 60, str(total))
    ok("exactly 10 of them are a head coach (butler has two)", len(flagged) == 10, str(flagged))
    ok("and no title is flagged twice for the wrong reason",
       sorted(t for _, t in flagged) == sorted([
           "Co-Head Coach", "Co-Head Coach", "Head Coach", "Head Coach", "Head Coach",
           "Head Soccer Coach", "Head Women's Coach", "Head Women's Soccer Coach",
           "Head Women’s Soccer Coach", "Head Coach"]), str(sorted(t for _, t in flagged)))


def test_origin_behaviour() -> None:
    """The swap-back proof: what the rules before this change did with these same pages."""
    print("origin/main's rule on these fixtures")
    for name in GAP_FIXTURES:
        rows = staff(name)
        ok(f"{name}: origin/main found no head coach at all",
           not any(origin_is_head(s["title"]) for s in rows),
           str([s["title"] for s in rows if origin_is_head(s["title"])]))
        ok(f"{name}: and the person it missed is the one this fixture is about",
           EXPECTED[name][1] in [s["title"] for s in rows])
    nc = staff("roster-former-head-coach")
    ok("former: origin/main flagged two people, the head coach and his predecessor",
       [s["name"] for s in nc if origin_is_head(s["title"])] == ["Damon Nahas", "Anson Dorrance"],
       str([s["name"] for s in nc if origin_is_head(s["title"])]))
    ok("former: now only the current head coach is flagged",
       [s["name"] for s in heads(nc)] == ["Damon Nahas"], str([s["name"] for s in heads(nc)]))
    ind = staff("roster-misspelled-associate")
    ok("misspelled: origin/main flagged the 'Assosicate Head Coach' too",
       [s["name"] for s in ind if origin_is_head(s["title"])] == ["Paul Lawrence", "Chris Gnehm"],
       str([s["name"] for s in ind if origin_is_head(s["title"])]))
    ok("misspelled: now it does not",
       [s["name"] for s in heads(ind)] == ["Paul Lawrence"], str([s["name"] for s in heads(ind)]))
    for name in ("roster-strength-coach", "roster-sports-performance-coach", "roster-co-head-coaches"):
        rows = staff(name)
        ok(f"{name}: the pages origin/main already got right are unchanged",
           [s["name"] for s in rows if origin_is_head(s["title"])] == [s["name"] for s in heads(rows)],
           str([s["name"] for s in heads(rows)]))


def test_the_sketch_over_matches() -> None:
    """`head\\b.*\\bcoach`, the pattern issue #33 proposed, takes the wrong people with it."""
    print("the proposed pattern, on the same pages")
    for name, who, title in (
            ("roster-strength-coach", "Jason Phillips", "Head Olympic Strength and Conditioning Coach"),
            ("roster-sports-performance-coach", "Gina Tanglis",
             "Head Sports Performance Coach (Women's Soccer, Softball, Men's Tennis, Golf)")):
        rows = staff(name)
        row = next(s for s in rows if s["name"] == who)
        ok(f"{name}: the page really carries {title!r}", row["title"] == title, row["title"])
        ok(f"{name}: 'head.*coach' would call {who} the head coach", sketch_is_head(title))
        ok(f"{name}: this rule does not", not row["isHeadCoach"])
        ok(f"{name}: and the head coach is still the right person",
           [s["name"] for s in heads(rows)] == [EXPECTED[name][0]], str([s["name"] for s in heads(rows)]))
    ok("'head.*coach' would also have kept the former head coach",
       sketch_is_head("Former Head Coach (1979-2024)") and not sidearm.is_head_coach("Former Head Coach (1979-2024)"))
    ok("and the misspelled associate",
       sketch_is_head("Assosicate Head Coach") and not sidearm.is_head_coach("Assosicate Head Coach"))


def test_several_coaches_match() -> None:
    """What happens when a page really does list two head coaches."""
    print("two head coaches on one page")
    rows = staff("roster-co-head-coaches")
    found = heads(rows)
    ok("co-head: both rows are flagged", [s["name"] for s in found] == ["Tari St. John", "Rob Alman"],
       str([s["name"] for s in found]))
    ok("co-head: they are both titled Co-Head Coach", {s["title"] for s in found} == {"Co-Head Coach"})
    ok("co-head: build.py publishes the first in page order, which is the page's own order",
       rows.index(found[0]) < rows.index(found[1]))
    ok("co-head: this is the only fixture where more than one row matches",
       [n for n in EXPECTED if len(heads(staff(n))) > 1] == ["roster-co-head-coaches"],
       str([n for n in EXPECTED if len(heads(staff(n))) > 1]))


# (title, is this the women's soccer head coach?, why the case is here)
TITLE_CASES = [
    ("Head Coach", True, "the plain form, 239 rows"),
    ("Head Women's Soccer Coach", True, "31 rows, and the whole of issue #33"),
    ("Head Women’s Soccer Coach", True, "the same with a typographic apostrophe"),
    ("Head Women�s Soccer Coach", True, "the same from a mis-decoded page"),
    ("Head Soccer Coach", True, "8 rows"),
    ("Head Women's Coach", True, "memphis"),
    ("Head Coach, Women's Soccer", True, "3 rows"),
    ("Women's Soccer Head Coach", True, "8 rows"),
    ("Interim Head Coach", True, "2 rows: an interim head coach is the head coach"),
    ("Co-Head Coach", True, "butler"),
    ("Head Coach (20th Season)", True, "cal-state-fullerton"),
    ("Head Coach/15th Year", True, "tcu"),
    ("Douglas N. Brush Head Coach", True, "penn: an endowed title"),
    ("The Branca Family Head Coach for Harvard Women's Soccer", True, "harvard: another"),
    ("HEAD COACH", True, "case does not matter"),
    ("Head Varsity Soccer Coach", True, "not in the corpus; the vocabulary allows it"),
    ("Head Coach / Associate Athletic Director", True,
     "the coach who is also an AD: 'associate' is not in front of 'head'"),
    ("Head Coach, Men's and Women's Soccer", True, "one coach for both programs"),
    ("Head Men's and Women's Soccer Coach", True, "the same, written the other way"),
    ("Associate Head Coach", False, "97 rows"),
    ("Senior Associate Head Coach", False, "2 rows"),
    ("Assistant Head Coach", False, "west-virginia"),
    ("Assosicate Head Coach", False, "indiana-state spells it this way"),
    ("Associate Head Women's Soccer Coach", False, "5 rows"),
    ("Women's Soccer Associate Head Coach", False, "2 rows, the qualifier in front"),
    ("Assistant Coach", False, "408 rows"),
    ("Volunteer Assistant Coach", False, "17 rows"),
    ("Former Head Coach (1979-2024)", False, "north-carolina"),
    ("Head Coach Emeritus", False, "not in the corpus; emeritus is not the head coach"),
    ("Head Strength & Conditioning Coach", False, "2 rows"),
    ("Head Strength and Conditioning Coach", False, "2 rows"),
    ("Head Olympic Strength and Conditioning Coach", False, "colorado-state"),
    ("Head Sports Performance Coach (Women's Soccer, Softball, Men's Tennis, Golf)", False, "uic"),
    ("Head Athletic Trainer", False, "not a coach"),
    ("Head of Player Development/Recruitment", False, "florida-state"),
    ("Head of Sports Science, Duke Women's Soccer", False, "duke"),
    ("Director of Sports Medicine, Head Team Physician", False, "quinnipiac"),
    ("Head Men's Soccer Coach", False, "the other program's coach on a shared page"),
    ("Head Coach, Men's Soccer", False, "the same, and today's rule takes it"),
    ("Men's Soccer Head Coach", False, "and the same again"),
    ("Director of Operations", False, "36 rows"),
    ("Goalkeeper Coach", False, "12 rows"),
    ("Assistant Women's Soccer Coach", False, "35 rows"),
]


def test_title_rule() -> None:
    """is_head_coach() on every title form the corpus carries, and the ones it must refuse."""
    print("the rule, title by title")
    for title, want, why in TITLE_CASES:
        ok(f"{'is' if want else 'is not'} the head coach: {ascii(title)} ({why})",
           sidearm.is_head_coach(title) is want, f"rule said {sidearm.is_head_coach(title)}")


def test_fixtures_carry_no_contact_details() -> None:
    """These pages carry coaches' email addresses and desk numbers; the fixtures must not."""
    print("fixture privacy")
    email = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    phone = re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)")
    names = sorted(f for f in os.listdir(FIXTURES) if f.startswith("roster-"))
    # nine from issue #33, plus roster-no-staff and roster-players-and-staff from #145 (staff_fallback_test.py),
    # plus roster-list-view-no-name-column from #156 and roster-list-view-table-reordered from #183
    # (sidearm_list_view_test.py), plus roster-hometown-highschool-previous-school,
    # roster-previous-team-is-a-club, roster-previous-team-ambiguous-high-school-or-college and
    # roster-hometown-no-slash-real-previous-school from #227 (sidearm_roster_highschool_test.py)
    ok("privacy: there are roster fixtures to check", len(names) == 17, str(names))
    for name in names:
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
            text = handle.read()
        found = [a for a in email.findall(text) if not a.endswith("example.invalid")]
        ok(f"privacy: {name} has no email address", not found, str(found[:3]))
        ok(f"privacy: {name} has no phone number", not phone.findall(text), str(phone.findall(text)[:3]))
        ok(f"privacy: {name} has no mailto: or tel: link", not re.search(r"(mailto|tel):", text, re.I))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose
    for case in (test_every_fixture_publishes_its_head_coach, test_nobody_else_is_flagged,
                 test_origin_behaviour, test_the_sketch_over_matches, test_several_coaches_match,
                 test_title_rule, test_fixtures_carry_no_contact_details):
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
