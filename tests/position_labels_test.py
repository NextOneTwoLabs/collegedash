"""Position labels norm_pos could not map, or mapped wrongly (issue #263 Part B).

    python tests/position_labels_test.py            # everything below, offline
    python tests/position_labels_test.py --verbose  # print every check

Offline: plain strings, no pages, no requests.

Why this exists
---------------
common.norm_pos feeds the Sidearm and WMT roster parsers and the TDS commitments parser. It knew
only GK/D/M/F words, so 'B' (258 players across the cache), 'G', 'CB', 'CM', 'W' and 'Wingback'
were published with a blank position. Its fallback took the first POS_MAP key a label *started
with*, in insertion order, so 'Defensive Mid' and 'DM' came out D ('def', 'd'), 'Fullback' F
('f'), 'Backup Goalkeeper' D ('back') and 'Manager' M ('m').

The fix splits the keys: POS_EXACT holds every 1-2 letter abbreviation (and 'att', 'cam', 'cdm',
'wing') and matches a whole label part only; POS_MAP holds whole words and phrases of 3+ letters
and matches as a prefix, longest key first. Owner decisions on #263: 'W'/'Wing' -> F, 'S' alone ->
F (striker), 'Attacking Mid' -> M, 'Wing Back' -> D. sidearm._is_position_label (#311) now goes
through the same common.pos_code, so it still rejects 'Manager', 'Student Intern' and club names.

Each CASES row carries what norm_pos returned before this change; 58 of the rows differ from it.
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import common, commitments_tds  # noqa: E402
from collect.adapters import sidearm  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False

# (label, expected, what norm_pos returned before this change)
CASES = (
    # new keys, blank before
    ("B", "D", ""), ("CB", "D", ""), ("OB", "D", ""), ("LB", "D", ""), ("RB", "D", ""), ("WB", "D", ""),
    ("FB", "D", "F"), ("SW", "D", ""), ("Center Back", "D", ""), ("Center back", "D", ""),
    ("Centre-Back", "D", ""), ("Outside Back", "D", ""), ("Right Back", "D", ""), ("Left Back", "D", ""),
    ("Sweeper", "D", ""), ("WB/CB", "D", ""), ("OB/WB", "D", ""), ("CB/OB", "D", ""),
    ("G", "GK", ""), ("Goalie", "GK", ""), ("G.", "GK", ""),
    ("CM", "M", ""), ("CDM", "M", ""), ("CAM", "M", ""), ("AM", "M", ""), ("ACM", "M", ""),
    ("LM", "M", ""), ("RM", "M", ""), ("Center Midfielder", "M", ""), ("Central Midfielder", "M", ""),
    ("CB/CM", "D/M", ""),
    ("CF", "F", ""), ("ST", "F", ""), ("ATT", "F", ""), ("Attacker", "F", ""), ("Center Forward", "F", ""),
    # owner decisions
    ("W", "F", ""), ("Wing", "F", ""), ("Winger", "F", ""), ("CF/W", "F", ""), ("W/WB", "F/D", ""),
    ("S", "F", ""),
    ("Attacking Mid", "M", ""), ("Attacking Midfielder", "M", ""),
    ("Wing Back", "D", ""), ("Wingback", "D", ""), ("Wing-Back", "D", ""),
    # already mapped, wrongly
    ("Defensive Mid", "M", "D"), ("Defensive Midfielder", "M", "D"), ("DM", "M", "D"),
    ("Full Back", "D", "F"), ("Fullback", "D", "F"), ("Backup Goalkeeper", "GK", "D"),
    ("Manager", "", "M"), ("Student Intern", "", ""), ("Fan", "", "F"), ("Director", "", "D"),
    # stay blank: no owner decision, or not a position
    ("Util", "", ""), ("Team Impact", "", ""), ("A", "", ""), ("C", "", ""), ("", "", ""),
    # unchanged: labels that already mapped must keep their value
    ("GK", "GK", "GK"), ("Goalkeeper", "GK", "GK"), ("Keeper", "GK", "GK"), ("D", "D", "D"),
    ("Def", "D", "D"), ("Defender", "D", "D"), ("Back", "D", "D"), ("M", "M", "M"), ("MF", "M", "M"),
    ("Mid", "M", "M"), ("Midfield", "M", "M"), ("Midfielder", "M", "M"), ("F", "F", "F"),
    ("Fwd", "F", "F"), ("Forward", "F", "F"), ("Striker", "F", "F"), ("D/M", "D/M", "D/M"),
    ("M/F", "M/F", "M/F"), ("GK/D", "GK/D", "GK/D"), ("Midfielder/Forward", "M/F", "M/F"),
    ("Defenders", "D", "D"), ("Forwards", "F", "F"), ("Midfielders", "M", "M"),
    ("FW", "F", "F"), ("DF", "D", "D"), ("MD", "M", "M"), ("FD", "F", "F"), ("FM", "F", "F"),
    ("FOR", "F", "F"), ("Foward", "F", "F"), ("DLB", "D", "D"), ("F-M", "F/M", "F"), ("M-D", "M/D", "M"),
    ("D.MF", "D/M", "D"), ("FOR/MID", "F/M", "F/M"), ("MGR", "", "M"), ("MANG", "", "M"),
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


def test_norm_pos_table():
    for label, want, _before in CASES:
        got = common.norm_pos(label)
        ok(f"norm_pos({label!r}) is {want!r}", got == want, f"got {got!r}")


def test_table_would_fail_before():
    # The table is only evidence if enough of it disagrees with the old answers.
    changed = [c for c in CASES if c[1] != c[2]]
    ok("at least 50 rows differ from the pre-#263 answer", len(changed) >= 50, len(changed))


def test_prefix_keys_are_whole_words():
    # _is_position_label accepts a part that *starts with* a POS_MAP key, so a short key there
    # would let non-players through the #311 gate.
    short = [k for k in common.POS_MAP if len(k) < 3]
    ok("every POS_MAP (prefix) key has 3+ letters", not short, short)
    both = sorted(set(common.POS_MAP) & set(common.POS_EXACT))
    ok("no key is in both dicts", not both, both)
    for k in ("att", "cam", "cdm", "acm", "wing", "g", "b", "s", "w", "d", "m", "f"):
        ok(f"{k!r} is exact-only", k in common.POS_EXACT and k not in common.POS_MAP)


def test_is_position_label_gate():
    for label, want in (("Goalkeeper", True), ("MF/F", True), ("Midfield", True), ("D", True),
                        ("B", True), ("CB/OB", True), ("Center Back", True), ("Attacking Mid", True),
                        ("Wing Back", True), ("G", True),
                        ("Manager", False), ("Team Manager", False), ("Student Intern", False),
                        ("Student Manager", False), ("FC Dallas", False), ("Attendance", False),
                        ("Camden FC", False), ("Wings Academy", False),
                        ("Forward/Outside Defense", False), ("Team Impact", False), ("Util", False),
                        ("", False)):
        ok(f"_is_position_label({label!r}) is {want}", sidearm._is_position_label(label) is want)


def test_tds_commitments_use_the_same_map():
    # commitments_tds has no suite of its own; one table row per label through the real parser.
    labels = ("B", "CB", "G", "Defensive Mid", "Fullback", "Midfielder")
    rows = "".join(f"<tr><td><a href='/p/{i}'>Player {i}</a></td><td>2027</td><td>{lab}</td><td>Town</td>"
                   f"<td>TX</td><td>Club FC</td></tr>" for i, lab in enumerate(labels))
    html = ("<table class='tds_table'><thead><tr><td>Name</td><td>Year</td><td>Pos.</td><td>City</td>"
            f"<td>State</td><td>Club</td></tr></thead><tbody>{rows}</tbody></table>")
    got = [r["pos"] for r in commitments_tds.parse_team_commitments(html)]
    ok("TDS commitments table maps B/CB/G/Defensive Mid/Fullback/Midfielder",
       got == ["D", "D", "GK", "M", "D", "M"], got)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_norm_pos_table, test_table_would_fail_before, test_prefix_keys_are_whole_words,
                 test_is_position_label_gate, test_tds_commitments_use_the_same_map):
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
