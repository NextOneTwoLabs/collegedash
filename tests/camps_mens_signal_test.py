"""A men's soccer mention is not a women's soccer signal on an all-sport page (issue #317).

    python tests/camps_mens_signal_test.py

UCCS's all-sport camps table has a Sport column; "Men's Soccer" in that cell put the word "soccer" in
the row's evidence, and _row_names_soccer took it as the women's team's camp. The fix excludes men's
and boys' soccer phrases from the signal (as the section heading rule already did); it never rejects a
row for a men's word. The fixture extract/synth-allsport-mens-label.html covers the page end to end.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import camps  # noqa: E402

FAILS, TOTAL = [], 0


def ok(name, cond, detail=""):
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))


def sig(evidence="", name="Elite ID Camp", url=None, section=None):
    return camps._row_names_soccer({"name": name, "_evidence": evidence, "registerUrl": url, "_section": section})


def main() -> int:
    cases = [
        ("'Men's Soccer' in the row's cells is not a signal", sig("Men's Soccer | October 10, 2027 | 11v11 Showcase Camp"), False),
        ("'Boys Soccer' is not a signal", sig("Boys Soccer | December 6, 2027 | Winter ID Clinic"), False),
        ("typographic apostrophe: 'Men’s Soccer' is not a signal", sig("Men’s Soccer | October 10, 2027"), False),
        ("'Women's Soccer' is a signal", sig("Women's Soccer | October 24, 2027 | Elite ID Camp"), True),
        ("'Girls Soccer' is a signal", sig("Girls Soccer | October 24, 2027"), True),
        ("a plain 'Soccer' is a signal", sig("Soccer | November 7, 2027 | Fall Prospect Day"), True),
        # co-ed, women's/girls' word first (Huatuo, PR #354 R1): a signal in either order
        ("co-ed: 'Women's and Men's Soccer' is a signal", sig("Women's and Men's Soccer | May 1, 2027"), True),
        ("co-ed: 'Women's & Men's Soccer' is a signal", sig("Women's & Men's Soccer | May 1, 2027"), True),
        ("co-ed: 'Girls & Boys Soccer' is a signal", sig("Girls & Boys Soccer | May 1, 2027"), True),
        ("co-ed: 'Girls and Boys Soccer' is a signal", sig("", name="Girls and Boys Soccer Camp"), True),
        ("co-ed: 'Girls/Boys Soccer' is a signal", sig("Girls/Boys Soccer | May 1, 2027"), True),
        ("co-ed, men's first: 'Men's and Women's Soccer' is a signal", sig("Men's and Women's Soccer | May 1, 2027"), True),
        ("co-ed, boys first: 'Boys & Girls Soccer' is a signal", sig("Boys & Girls Soccer | May 1, 2027"), True),
        ("men's AND an unqualified soccer mention: still a signal", sig("Men's Soccer staff | Soccer ID Camp | May 1, 2027"), True),
        ("soccer in the row's own name still counts", sig("", name="Soccer Elite ID Camp"), True),
        ("a men's soccer name is not a signal", sig("", name="Men's Soccer Showcase"), False),
        ("register URL on /womens-soccer/ is a signal", sig("", url="https://x.example.test/womens-soccer/id"), True),
        ("register URL on /mens-soccer/ is not a signal", sig("", url="https://x.example.test/mens-soccer/id"), False),
        ("a men's soccer section heading is not a signal (unchanged)",
         sig("", section={"sport": "soccer", "male": True, "token": "soccer"}), False),
        ("a soccer section heading that is not men's is a signal (unchanged)",
         sig("", section={"sport": "soccer", "male": False, "token": "soccer"}), True),
    ]
    for name, got, want in cases:
        ok(name, got is want, f"got {got}")
    print(f"{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
