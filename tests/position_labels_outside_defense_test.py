"""'Outside Defense' / 'Outside Defender' read as D (issue #263, the last label gap).

    python tests/position_labels_outside_defense_test.py            # everything below, offline
    python tests/position_labels_outside_defense_test.py --verbose  # print every check

Offline: plain strings and a page built here from placeholder names; no request.

Why this exists
---------------
After the 2026-09-30 refresh, one stored player (chicago-state) was blank although her page prints a position: the
table cell is empty and the Sidearm list view says 'Forward/Outside Defense'. norm_pos mapped 'Forward' but not
'Outside Defense', so #311's list-view guard (every part must map) rejected the label and the fill skipped it.

The fix (Huatuo's plan review on #263): two POS_MAP phrases, 'outside defense' and 'outside defender' -> D, matched
as a prefix with the longest key first like 'outside back'. Expected effect, as Huatuo corrected: no change anywhere
except a D added by this phrase - a single-phrase label or a #311 list-view fill goes from blank to D, and a table
label like 'Midfielder/Outside Defender' goes from M to M/D. 'Outside Defensive Mid' matches neither phrase and stays
blank. Every other key maps exactly as before.
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

# (label, expected after, expected before) - the only labels this change moves: a D appears where the phrase is
CHANGED = (
    ("Outside Defense", "D", ""), ("Outside Defender", "D", ""), ("outside defenders", "D", ""),
    ("Forward/Outside Defense", "F/D", "F"),
    ("Midfielder/Outside Defender", "M/D", "M"), ("Outside Defender/Midfielder", "D/M", "M"),
)
# (label, expected) - the same before and after
UNCHANGED = (
    ("Outside Defensive Mid", ""), ("Outside-Defense", "D"),  # split on "-" before, a whole phrase now: D both ways
    ("Outside Back", "D"), ("Defense", "D"), ("Defender", "D"), ("Forward", "F"),
    ("Outside", ""), ("Outside Mid", ""), ("Defensive Mid", "M"), ("Center Back", "D"), ("Wing Back", "D"),
    ("Manager", ""), ("Student Intern", ""), ("Team Impact", ""),
)
# Every key's value as it was before this change (the phrases added here are checked in CHANGED).
NEW_KEYS = {"outside defense", "outside defender"}


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def test_changed_labels():
    for label, want, _before in CHANGED:
        got = common.norm_pos(label)
        ok(f"FIX norm_pos({label!r}) is {want!r}", got == want, got)


def test_unchanged_labels():
    for label, want in UNCHANGED:
        got = common.norm_pos(label)
        ok(f"norm_pos({label!r}) stays {want!r}", got == want, got)


def test_every_other_key_maps_as_before():
    for table in (common.POS_EXACT, common.POS_MAP):
        for key, code in table.items():
            got = common.pos_code(key)
            ok(f"pos_code({key!r}) is {code!r}", got == code, got)
    ok("the new phrases are prefix keys", NEW_KEYS <= set(common.POS_MAP), NEW_KEYS - set(common.POS_MAP))
    ok("no key is in both tables", not set(common.POS_EXACT) & set(common.POS_MAP))
    ok("every prefix key is 3+ letters", all(len(k) >= 3 for k in common.POS_MAP))


def test_guard():
    for label, want in (("Forward/Outside Defense", True), ("Outside Defender", True),
                        ("Outside Defensive Mid", False), ("Manager", False), ("Student Intern", False),
                        ("Forward/Manager", False)):
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
    # chicago-state's shape: the table cell is empty, the list view carries 'Forward/Outside Defense'.
    html = ("<html><head><title>2025 Women's Soccer Roster</title></head><body>"
            '<ul class="sidearm-roster-players">' + _item(1, "Forward/Outside Defense") + _item(3, "Outside Defensive Mid")
            + "</ul><table><thead><tr><th>#</th><th>Name</th><th>Pos.</th><th>Ht.</th><th>Year</th>"
            "<th>Hometown / High School</th></tr></thead><tbody>"
            + _row(1, "") + _row(2, "Midfielder/Outside Defender") + _row(3, "") + "</tbody></table></body></html>")
    p = {x["name"]: (x["pos"], x["posLabel"]) for x in sidearm.parse_roster(html, BASE)["players"]}
    ok("FIX list-view fill 'Forward/Outside Defense' -> F/D", p.get("Player 1") == ("F/D", "Forward/Outside Defense"), p.get("Player 1"))
    ok("FIX table 'Midfielder/Outside Defender' -> M/D", p.get("Player 2") == ("M/D", "Midfielder/Outside Defender"), p.get("Player 2"))
    ok("list label 'Outside Defensive Mid' is not taken", p.get("Player 3") == ("", ""), p.get("Player 3"))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_changed_labels, test_unchanged_labels, test_every_other_key_maps_as_before, test_guard,
                 test_sidearm_page):
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
