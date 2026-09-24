"""Blank table positions filled from the legacy Sidearm list view (issue #263).

    python tests/sidearm_list_view_positions_test.py            # everything below, offline
    python tests/sidearm_list_view_positions_test.py --verbose  # print every check

Offline: the pages are built here from placeholder names and make no request.

Why this exists
---------------
Legacy Sidearm roster pages serve the roster twice: a table and the list view (li.sidearm-roster-
player). On wheaton-college-il and spalding the table's Pos. cell is empty for every player
(<td class="rp_position_short"></td>) while each list item shows the position in
<div class="sidearm-roster-player-position"><span class="text-bold">Goalkeeper</span>
<span class="sidearm-roster-player-height">5'9"</span></div>. parse_roster read the table, found
players, never looked at the list, and published every position blank (wheaton 35 of 35, spalding
25 of 25). Over the 1,467 cached roster pages the fill changes 6 pages and 64 players, and every
change is an empty position becoming a real one.

What must not change: a table label that is present (even one norm_pos cannot map), a list label
that is not a playing position ('Manager' - norm_pos's one-letter prefixes would make it M), and
the join, which is by bio URL only, never by row order (issue #183).
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect.adapters import sidearm  # noqa: E402

BASE = "https://athletics.example.edu/sports/womens-soccer/roster"
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


def href(n: int) -> str:
    return f"/sports/womens-soccer/roster/player-{n}/{9000 + n}"


def row(n: int, pos: str = "", link: bool = True) -> str:
    name = f'<a href="{href(n)}">Player {n}</a>' if link else f"Player {n}"
    return (f'<tr><td>{n}</td><th scope="row">{name}</th><td class="rp_position_short">{pos}</td>'
            f'<td>5\'6"</td><td>So.</td><td>Town, St. / High School {n}</td></tr>')


def item(n: int, pos_html: str) -> str:
    return (f'<li class="sidearm-roster-player"><div class="sidearm-roster-player-name">'
            f'<h3><a href="{href(n)}">Player {n}</a></h3></div>'
            f'<div class="sidearm-roster-player-position">{pos_html}</div></li>')


def bold(label: str, height: str = "5'6\"") -> str:
    return (f'<span class="text-bold"> {label} </span>'
            f'<span class="sidearm-roster-player-height">{height}</span>')


def page(rows: list[str], items: list[str]) -> str:
    return ("<html><head><title>2025 Women's Soccer Roster</title></head><body>"
            '<ul class="sidearm-roster-players">' + "".join(items) + "</ul>"
            "<table><thead><tr><th>#</th><th>Name</th><th>Pos.</th><th>Ht.</th><th>Year</th>"
            "<th>Hometown / High School</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
            "</body></html>")


def by_name(parsed: dict) -> dict:
    return {p["name"]: p for p in parsed["players"]}


def test_blank_table_positions_come_from_the_list():
    # The list is in a different order from the table on purpose: a join by position would be wrong.
    html = page([row(1), row(2), row(3), row(4)],
                [item(4, bold("Midfielder/Forward")), item(3, bold("Defender")),
                 item(2, bold("Forward (she/her)")), item(1, bold("Goalkeeper", "5'9\""))])
    p = by_name(sidearm.parse_roster(html, BASE))
    ok("four players", len(p) == 4, list(p))
    want = {"Player 1": ("GK", "Goalkeeper"), "Player 2": ("F", "Forward"),
            "Player 3": ("D", "Defender"), "Player 4": ("M/F", "Midfielder/Forward")}
    for name, (code, label) in want.items():
        got = (p.get(name, {}).get("pos"), p.get(name, {}).get("posLabel"))
        ok(f"{name} position {code} from its own list item", got == (code, label), got)
    ok("height is not part of the label", all("5'" not in x["posLabel"] for x in p.values()))
    ok("other fields still read from the table", p["Player 1"]["classCode"] == "SO"
       and p["Player 1"]["highSchool"] == "High School 1", p["Player 1"])


def test_present_table_label_is_kept():
    html = page([row(1, "B"), row(2, "D")], [item(1, bold("Defender")), item(2, bold("Midfielder"))])
    p = by_name(sidearm.parse_roster(html, BASE))
    ok("unmapped table label 'B' kept as the label", p["Player 1"]["posLabel"] == "B", p["Player 1"])
    ok("mapped table label kept over the list's", (p["Player 2"]["pos"], p["Player 2"]["posLabel"]) == ("D", "D"),
       p["Player 2"])


def test_non_positions_are_not_taken():
    html = page([row(1), row(2), row(3)],
                [item(1, bold("Manager")), item(2, bold("Student Intern")), item(3, bold("Club FC 2006 GA"))])
    p = by_name(sidearm.parse_roster(html, BASE))
    for name in p:
        ok(f"{name}: non-position list label leaves the position blank",
           (p[name]["pos"], p[name]["posLabel"]) == ("", ""), p[name])


def test_no_link_no_join():
    html = page([row(1, link=False), row(2)], [item(1, bold("Goalkeeper")), item(2, bold("Defender"))])
    p = by_name(sidearm.parse_roster(html, BASE))
    ok("row without a player link stays blank", p["Player 1"]["pos"] == "", p["Player 1"])
    ok("linked row beside it is filled", p["Player 2"]["pos"] == "D", p["Player 2"])


def test_empty_list_position_stays_blank():
    # hanover-college: both the table cell and the list block are empty - the source has no position.
    html = page([row(1), row(2)], [item(1, " "), item(2, '<span class="sidearm-roster-player-height">5\'4"</span>')])
    p = by_name(sidearm.parse_roster(html, BASE))
    ok("blank in both views stays blank", all(x["pos"] == "" and x["posLabel"] == "" for x in p.values()), p)


def test_is_position_label():
    for label, want in (("Goalkeeper", True), ("MF/F", True), ("Midfield", True), ("D", True),
                        ("Manager", False), ("Forward/Outside Defense", False), ("", False), ("Team Impact", False)):
        ok(f"_is_position_label({label!r}) is {want}", sidearm._is_position_label(label) is want)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_blank_table_positions_come_from_the_list, test_present_table_label_is_kept,
                 test_non_positions_are_not_taken, test_no_link_no_join, test_empty_list_position_stays_blank,
                 test_is_position_label):
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
