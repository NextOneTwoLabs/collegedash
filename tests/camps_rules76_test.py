"""Four camps-extractor rules that could silently drop a real women's soccer camp (issue #76).

    python tests/camps_rules76_test.py            # everything below, offline
    python tests/camps_rules76_test.py --verbose  # print every check, not only the failures

1. The row-NAME sport rule read #293's everyday words anywhere: 'Goalkeeper Dive Clinic' fell on 'dive' and
   'Fast Track ID Camp' on 'track'. An everyday word now names a sport only as the camp's subject ('Dive Camp') or
   in a fixed phrase ('track and field'), and a goalkeeper word outranks it - never a strong sport word.
2. OTHER_SPORT_HOST_RE matched 'dance' inside 'attendance', so a register link under /camp-attendance/ was skipped.
3. _merge_overlaps folded 'ID Camp Session 2' into 'ID Camp' when their dates touched. Names that differ by a
   session token stay apart; a day, an age band or a year of the same camp still merges.
4. _row_allowed's is_hub defaulted to True, the stricter hub path. It is now required.
Plus the one-refresh shadow line (removal: #460): camp titles and rule numbers only, never a URL.

Every name, page and URL here is SYNTHETIC (example.org / example.edu); no real people. Offline, no files written.

Swap-back proof: COLLEGEDASH_CODE_ROOT=<an export of origin/main> runs these checks against that code.
Labels: FIX checks fail against origin/main and pass after the change; GUARD checks pass on both.
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_ROOT = os.environ.get("COLLEGEDASH_CODE_ROOT") or ROOT
sys.path.insert(0, CODE_ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from bs4 import BeautifulSoup  # noqa: E402

from collect import camps  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False
PAGE_URL = "https://www.example.edu/sports/womens-soccer/camps"


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {ascii(detail)[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def shadow():
    """The #76 shadow line, or None on code that has none (origin/main), so the other checks still run there."""
    return camps.shadow76_line() if hasattr(camps, "shadow76_line") else None


def allowed(name: str):
    return camps._row_allowed(name, None, is_hub=False)


def test_rule1_names() -> None:
    print("rule 1: the row-name sport rule")
    for name in ("Goalkeeper Dive Clinic", "Fast Track ID Camp", "Keeper Diving Clinic", "Dive Clinic for Goalkeepers",
                 "GK Diving Camp"):
        ok(f"FIX {name!r} is kept", allowed(name) is True, allowed(name))
    for name in ("Elite ID Camp", "Trackside ID Camp", "Fall Prospect Clinic"):
        ok(f"GUARD {name!r} is kept", allowed(name) is True, allowed(name))
    for name in ("Dive Camp", "Diving Camp", "Track Camp", "Track & Field Camp", "Track and Field Clinic", "Swim and Dive Camp",
                 "Swim & Dive Clinic", "Spirit Squad Camp", "Big Man Camp", "Running Camp", "Dance Team Clinic",
                 "Field Hockey Goalkeeper Clinic", "Fast Track Basketball Camp", "Lacrosse Goalie Camp", "Divers Camp GKs Dive Camp"):
        ok(f"GUARD {name!r} is still rejected", allowed(name) is False, allowed(name))
    # a word boundary on every new word: a longer word neither trips the rule nor excuses a sport
    ok("GUARD 'GKs' is not the keeper word: 'GKs Track Camp' is still rejected", allowed("GKs Track Camp") is False)
    ok("GUARD 'Divers' is not 'dive': 'Divers Elite ID Camp' is kept", allowed("Divers Elite ID Camp") is True)


def _anchors(*hrefs: str):
    html = "".join(f'<a href="{h}">Register</a>' for h in hrefs)
    return BeautifulSoup(html, "html.parser").find_all("a")


def test_rule2_register_host() -> None:
    print("rule 2: English words inside a register URL")
    got = camps._register_url(_anchors("https://register.example.org/camp-attendance/elite-id"), PAGE_URL)
    ok("FIX a register link under /camp-attendance/ is chosen", got == "https://register.example.org/camp-attendance/elite-id", got)
    got = camps._register_url(_anchors("https://register.example.org/guidance/tracking/elite-id"), PAGE_URL)
    ok("FIX 'guidance' and 'tracking' in a path do not make it a dance or track host",
       got == "https://register.example.org/guidance/tracking/elite-id", got)
    got = camps._register_url(_anchors("https://www.exampledancecamps.com/register"), PAGE_URL)
    ok("GUARD a dance-camp host is still skipped", got is None, got)
    got = camps._register_url(_anchors("https://www.examplebasketballcamps.com/register",
                                       "https://www.examplesoccercamps.com/register"), PAGE_URL)
    ok("GUARD a basketball host is still skipped for the soccer one", got == "https://www.examplesoccercamps.com/register", got)


def _day(name: str, a: str, b: str) -> dict:
    return {"name": name, "startDate": a, "endDate": b, "precision": "day"}


def _merged(*rows: dict) -> list[tuple]:
    return [(e["name"], e["startDate"], e["endDate"]) for e in camps._merge_overlaps([dict(r) for r in rows])]


def test_rule3_sessions() -> None:
    print("rule 3: numbered sessions are not merged")
    shadow()
    for second in ("ID Camp Session 2", "ID Camp 2", "ID Camp II", "ID Camp Week 2", "ID Camp Part II"):
        got = _merged(_day("ID Camp", "2027-06-10", "2027-06-12"), _day(second, "2027-06-12", "2027-06-14"))
        ok(f"FIX 'ID Camp' + {second!r} on touching dates are 2 rows with their own dates",
           got == [("ID Camp", "2027-06-10", "2027-06-12"), (second, "2027-06-12", "2027-06-14")], got)
    shadow()
    guards = {
        "ID Camp Day 1": (_day("ID Camp", "2027-06-10", "2027-06-12"), _day("ID Camp Day 1", "2027-06-10", "2027-06-10")),
        "ID Camp (Ages 8-12)": (_day("ID Camp", "2027-06-10", "2027-06-12"), _day("ID Camp (Ages 8-12)", "2027-06-11", "2027-06-12")),
        "ID Camp U12": (_day("ID Camp", "2027-06-10", "2027-06-12"), _day("ID Camp U12", "2027-06-11", "2027-06-12")),
        "2-Day ID Camp": (_day("ID Camp", "2027-06-10", "2027-06-11"), _day("2-Day ID Camp", "2027-06-10", "2027-06-11")),
        "ID Camp 2027": (_day("ID Camp 2027", "2027-06-10", "2027-06-12"), _day("ID Camp", "2027-06-11", "2027-06-12")),
        "ID Camp Grades 9-12": (_day("ID Camp", "2027-06-10", "2027-06-12"), _day("ID Camp Grades 9-12", "2027-06-11", "2027-06-12")),
    }
    for label, rows in guards.items():
        got = _merged(*rows)
        ok(f"GUARD {label!r} is the same camp: 1 row", len(got) == 1, got)
    got = _merged(_day("Elite Camp", "2027-07-21", "2027-07-24"),
                  *[_day("Elite Camp", f"2027-07-2{i}", f"2027-07-2{i}") for i in range(1, 5)])
    ok("GUARD a range and each of its four days, same name (the nicholls shape): 1 row",
       got == [("Elite Camp", "2027-07-21", "2027-07-24")], got)
    got = _merged(_day("Summer ID Camp", "2027-06-13", "2027-06-16"), _day("Summer ID Camp", "2027-06-15", "2027-06-19"),
                  _day("Summer ID Camp", "2027-06-17", "2027-06-20"))
    ok("GUARD overlapping same-name ranges (the SMU shape): 1 row", got == [("Summer ID Camp", "2027-06-13", "2027-06-20")], got)
    got = _merged(_day("ID Camp Session 2", "2027-06-10", "2027-06-12"), _day("ID Camp Session 2", "2027-06-20", "2027-06-22"))
    ok("GUARD disjoint dates stay apart, as before", len(got) == 2, got)


def test_rule4_is_hub_required() -> None:
    print("rule 4: is_hub has no default")
    try:
        camps._row_allowed("Elite ID Camp", {"sport": "other", "male": False, "token": "golf"})
        ok("FIX _row_allowed without is_hub raises TypeError", False, "accepted: it defaults to the hub path")
    except TypeError:
        ok("FIX _row_allowed without is_hub raises TypeError", True)
    other = {"sport": "other", "male": False, "token": "golf"}
    ok("GUARD under another sport's section: dropped on a hub", camps._row_allowed("Elite ID Camp", other, is_hub=True) is False)
    ok("GUARD under another sport's section: kept off a hub", camps._row_allowed("Elite ID Camp", other, is_hub=False) is True)


PAGE = """<html><head><title>Example College Women's Soccer Camps</title></head><body><main>
<h1>Example College Women's Soccer Camps</h1>
<table>
<tr><th>Camp</th><th>Dates</th><th>Registration</th></tr>
<tr><td>Goalkeeper Dive Clinic</td><td>June 8, 2027</td><td><a href="https://register.example.org/gk-clinic">Register</a></td></tr>
<tr><td>Fast Track ID Camp</td><td>June 20, 2027</td><td><a href="https://register.example.org/camp-attendance/fast">Register</a></td></tr>
<tr><td>ID Camp</td><td>July 10-12, 2027</td><td><a href="https://register.example.org/id-1">Register</a></td></tr>
<tr><td>ID Camp Session 2</td><td>July 12-14, 2027</td><td><a href="https://register.example.org/id-2">Register</a></td></tr>
</table></main></body></html>"""


def test_page() -> None:
    print("a synthetic women's soccer camps page with all three shapes")
    shadow()
    rows = camps.extract_camps(PAGE, PAGE_URL, title="Example College Women's Soccer Camps", page_soccer=True)
    got = [(e["name"], e["startDate"], e["endDate"]) for e in rows]
    ok("FIX all four camps are listed, each on its own dates", got == [
        ("Goalkeeper Dive Clinic", "2027-06-08", "2027-06-08"), ("Fast Track ID Camp", "2027-06-20", "2027-06-20"),
        ("ID Camp", "2027-07-10", "2027-07-12"), ("ID Camp Session 2", "2027-07-12", "2027-07-14")], got)
    fast = next((e for e in rows if e["name"] == "Fast Track ID Camp"), {})
    ok("FIX the /camp-attendance/ link is the Fast Track row's registerUrl",
       fast.get("registerUrl") == "https://register.example.org/camp-attendance/fast", fast.get("registerUrl"))
    line = shadow()
    ok("FIX the shadow line names each rule that kept something, by title", bool(line)
       and "'Goalkeeper Dive Clinic' (rule 1)" in line and "'Fast Track ID Camp' (rule 1)" in line
       and "a register link (rule 2)" in line and "'ID Camp Session 2' (rule 3)" in line, line)
    ok("FIX the shadow line carries no URL", bool(line) and "http" not in line and "example.org" not in line, line)
    ok("FIX the shadow line is cleared once read", hasattr(camps, "shadow76_line") and shadow() is None)
    camps.SHADOW_76 = False
    try:
        camps.extract_camps(PAGE, PAGE_URL, title="Example College Women's Soccer Camps", page_soccer=True)
        ok("FIX with SHADOW_76 off nothing is recorded", hasattr(camps, "shadow76_line") and shadow() is None)
    finally:
        camps.SHADOW_76 = True


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    if CODE_ROOT != ROOT:
        print(f"code under test imported from {CODE_ROOT}")
    for case in (test_rule1_names, test_rule2_register_host, test_rule3_sessions, test_rule4_is_hub_required, test_page):
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
