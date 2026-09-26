"""Position labels that still published blank after Part B (issue #263 Part C).

    python tests/position_labels_part_c_test.py            # everything below, offline
    python tests/position_labels_part_c_test.py --verbose  # print every check

Offline: plain strings and a page built here from placeholder names; no request.

Why this exists
---------------
After Part B, 18 stored players (of 26,508 with a position label) still had a label and a blank
position: backslash pairs ('M\\D', 'F\\M', 'F\\D' - norm_pos split only on '/' and ','), side-word
phrases ('Left Midfielder', 'Right Forward', 'Right Midfieldert'), and four short forms ('WM' wide
mid, 'WNG' wing, 'STR' striker, 'DB' defensive back).

The fix (Huatuo's plan review on #263):
  * common.pos_parts is the one splitter, '/' '\\' ',', used by norm_pos AND by the Sidearm list-view
    guard sidearm._is_position_label (#311). The guard's rule - every part must map - is unchanged.
  * A leading side word (left / right / center / centre) is dropped ONLY after both lookups fail on
    the whole part, and only when what follows maps. So 'Right Back' keeps its own key (D) and
    'Center Court' stays blank.
  * POS_EXACT gains 'wm' M, 'wng' F (the owner's W/Wing -> F), 'str' F, 'db' D.

Every already-mapped value is unchanged: over 1,449 cached roster pages and 471 TopDrawerSoccer pages
parsed with main's code and this branch's, no position changed; on the stored data only the 18 blanks fill.
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import common  # noqa: E402
from collect.adapters import sidearm  # noqa: E402

BASE = "https://athletics.example.edu/sports/womens-soccer/roster"
FAILS: list[str] = []
TOTAL = 0
VERBOSE = False

# (label, expected) - blank before this change
FIXED = (
    ("M\\D", "M/D"), ("F\\M", "F/M"), ("F\\D", "F/D"), ("D\\M", "D/M"), ("GK \\ D", "GK/D"),
    ("Left Midfielder", "M"), ("Right Midfielder", "M"), ("Right Midfieldert", "M"),
    ("Right Forward", "F"), ("Left Wing Back", "D"), ("Right Wing", "F"),
    ("WM", "M"), ("WNG", "F"), ("STR", "F"), ("DB", "D"), ("WM/F", "M/F"),
)

# (label, expected) - the same before and after this change
UNCHANGED = (
    # labels that already map and start with a side word keep their own key
    ("Right Back", "D"), ("Left Back", "D"), ("Center Back", "D"), ("Centre-Back", "D"),
    ("Center Midfielder", "M"), ("Center Forward", "F"), ("Centre Forward", "F"), ("Wing Back", "D"),
    # still not a position
    ("Manager", ""), ("MGR", ""), ("Mgr.", ""), ("Team Impact", ""), ("Util", ""), ("A", ""), ("C", ""),
    ("Center", ""), ("Center Court", ""), ("Right", ""), ("Left Manager", ""), ("", ""),
)


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def test_fixed_labels():
    for label, want in FIXED:
        got = common.norm_pos(label)
        ok(f"FIX norm_pos({label!r}) is {want!r}", got == want, got)


def test_unchanged_labels():
    for label, want in UNCHANGED:
        got = common.norm_pos(label)
        ok(f"norm_pos({label!r}) stays {want!r}", got == want, got)


def test_every_key_maps_as_before():
    # Each short form and phrase key still maps to its own value: the side-word fallback never runs
    # for a part one of the two lookups already maps, and no new key shadows an old one.
    for table in (common.POS_EXACT, common.POS_MAP):
        for key, code in table.items():
            got = common.pos_code(key)
            ok(f"pos_code({key!r}) is {code!r}", got == code, got)
    ok("no key is in both tables", not set(common.POS_EXACT) & set(common.POS_MAP),
       set(common.POS_EXACT) & set(common.POS_MAP))
    ok("every prefix key is 3+ letters", all(len(k) >= 3 for k in common.POS_MAP),
       [k for k in common.POS_MAP if len(k) < 3])


def test_one_splitter():
    ok("pos_parts splits on / \\ ,", common.pos_parts("GK/D\\M,F") == ["GK", "D", "M", "F"],
       common.pos_parts("GK/D\\M,F"))
    ok("pos_parts of None is one empty part", common.pos_parts(None) == [""])


def test_guard():
    for label, want in (("M\\D", True), ("F\\M", True), ("Left Midfielder", True), ("Right Back", True),
                        ("Manager", False), ("M\\Manager", False), ("Center Court", False), ("", False)):
        ok(f"_is_position_label({label!r}) is {want}", sidearm._is_position_label(label) is want)


def _row(n: int, pos: str) -> str:
    return (f'<tr><td>{n}</td><th scope="row"><a href="/sports/womens-soccer/roster/player-{n}/{9000 + n}">'
            f'Player {n}</a></th><td class="rp_position_short">{pos}</td><td>5\'6"</td><td>So.</td>'
            f'<td>Town, St. / High School {n}</td></tr>')


def _item(n: int, label: str) -> str:
    return (f'<li class="sidearm-roster-player"><div class="sidearm-roster-player-name">'
            f'<h3><a href="/sports/womens-soccer/roster/player-{n}/{9000 + n}">Player {n}</a></h3></div>'
            f'<div class="sidearm-roster-player-position"><span class="text-bold"> {label} </span>'
            f'<span class="sidearm-roster-player-height">5\'6"</span></div></li>')


def test_sidearm_page():
    # Player 1 and 2 have the label in the table; players 3 and 4 only in the list view.
    html = ("<html><head><title>2025 Women's Soccer Roster</title></head><body>"
            '<ul class="sidearm-roster-players">' + _item(3, "Left Midfielder") + _item(4, "Manager") + "</ul>"
            "<table><thead><tr><th>#</th><th>Name</th><th>Pos.</th><th>Ht.</th><th>Year</th>"
            "<th>Hometown / High School</th></tr></thead><tbody>"
            + _row(1, "M\\D") + _row(2, "Right Back") + _row(3, "") + _row(4, "") + "</tbody></table></body></html>")
    p = {x["name"]: (x["pos"], x["posLabel"]) for x in sidearm.parse_roster(html, BASE)["players"]}
    ok("FIX table label 'M\\D' -> M/D", p.get("Player 1") == ("M/D", "M\\D"), p.get("Player 1"))
    ok("table label 'Right Back' still D", p.get("Player 2") == ("D", "Right Back"), p.get("Player 2"))
    ok("FIX list label 'Left Midfielder' taken -> M", p.get("Player 3") == ("M", "Left Midfielder"), p.get("Player 3"))
    ok("list label 'Manager' not taken", p.get("Player 4") == ("", ""), p.get("Player 4"))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_fixed_labels, test_unchanged_labels, test_every_key_maps_as_before, test_one_splitter,
                 test_guard, test_sidearm_page):
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
