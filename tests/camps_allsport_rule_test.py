"""The all-sport page rule after #326: one other sport, and no shadow left behind.

    python tests/camps_allsport_rule_test.py            # offline, made-up pages only
    python tests/camps_allsport_rule_test.py --verbose

Why this exists
---------------
#293 calls a page_soccer False page all-sport when its text names another sport, and there a row
needs a soccer signal of its own. #326 measured a stricter "2+ distinct sports" rule, over the 740
cached camp pages and in PR A's report-only shadow in the 2026-09-25 refresh: both found the same 3
pages and 7 added rows, none a women's soccer camp, so the owner dropped it and the shadow is removed.
What stays is the live rule (ALLSPORT_MIN_SPORTS = 1) and the canonical sport list it counts with.
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import collegedash  # noqa: E402
from collect import camps  # noqa: E402

URL = "https://www.example-coach.test/camps"
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


def page(sentence: str) -> str:
    # made-up camps with no soccer word, no sport heading and no register link: no row soccer signal
    return ("<html><head><title>Lions Elite Camps</title></head><body><main><h1>Lions Elite Camps</h1>"
            f"<p>{sentence}</p><p>Summer Elite Camp - July 10, 2027</p><p>Fall Skills Clinic - October 2, 2027</p>"
            "</main></body></html>")


def names(rows):
    return sorted(r["name"] for r in rows)


def run(html):
    return camps.extract_camps(html, URL, title="Lions Elite Camps", page_soccer=False)


def test_live_rule():
    ok("the live rule stays at 1 other sport", camps.ALLSPORT_MIN_SPORTS == 1, camps.ALLSPORT_MIN_SPORTS)
    ok("one 'football' makes the page all-sport: rows without a soccer signal go",
       run(page("Our coaching staff also played college football.")) == [])
    ok("two sports: all-sport as well", run(page("Volleyball and softball camps are listed on their own pages.")) == [])
    ok("no other sport: not all-sport, today's behaviour keeps the rows",
       names(run(page("Our coaching staff has a long track record."))) == ["Fall Skills Clinic", "Summer Elite Camp"])


def test_canonical_sports():
    for text, want in (("swim and swimming", {"swimming"}), ("cheer and cheerleading", {"cheer"}),
                       ("cross country and cross-country", {"cross country"}), ("water polo, water-polo", {"water polo"}),
                       ("thrower and throwers", {"throwers"}), ("pole vault and pole-vault", {"pole vault"}),
                       ("football and golf", {"football", "golf"}), ("no sport here", set())):
        got = camps.allsport_sports(text)
        ok(f"allsport_sports({text!r}) == {sorted(want)}", got == want, sorted(got))


def test_shadow_is_gone():
    # #326: PR B was dropped, so PR A's report-only shadow and its refresh hook are removed
    gone = [n for n in ("allsport_shadow", "allsport_shadow_summary", "_SHADOW", "_PathStats", "SHADOW_MAX_LINES")
            if hasattr(camps, n)]
    ok("camps.py carries no shadow code", not gone, gone)
    ok("the refresh has no shadow report hook", not hasattr(collegedash, "write_allsport_shadow"))
    ok("STATS is a plain Counter again", type(camps.STATS).__name__ == "Counter", type(camps.STATS).__name__)
    try:
        camps.extract_camps(page("x"), URL, title="t", page_soccer=False, min_sports=2)
        ok("extract_camps no longer takes the shadow's min_sports", False)
    except TypeError:
        ok("extract_camps no longer takes the shadow's min_sports", True)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_live_rule, test_canonical_sports, test_shadow_is_gone):
        try:
            case()
        except Exception as e:  # noqa: BLE001 - a crash is that case failing
            ok(f"{case.__name__} ran", False, repr(e))
    print(f"{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
