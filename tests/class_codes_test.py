"""Class labels that stored an empty class code now map (issue #34).

    python tests/class_codes_test.py

Over the cached roster pages, 753 rows had an empty `classCode`; 643 of them carry a label that names a class:
first-year and ordinal forms ('Fy.', 'FY', '1st', '2nd YR', 'Third Year', 'Fourth Year', 'Sixth Year'), 'RS So.'
with a space the redshirt prefix did not allow, 'Red 5th', and 'Rf.', which the sites' own list view expands to
'Redshirt Freshman'. The new rules are APPENDED to sidearm.CLASS_CODES, so first match wins and no label that maps
today can change; WMT falls back to the same table.

Made-up rows only (no real person). FIX checks fail on origin/main; CONTROL checks pass on both; GUARD checks pass on
both and keep ambiguous labels empty. Offline.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect.adapters import sidearm, wmt  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
BASE = "https://example.edu"


def ok(name: str, cond: bool, detail="") -> None:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))


NEW = {
    "Fy.": "FR", "FY": "FR", "Fy": "FR", "1st": "FR", "1st YR": "FR", "1st Year": "FR", "1st year": "FR",
    "First Year": "FR", "First-Year": "FR",
    "2nd": "SO", "2nd YR": "SO", "2nd Year": "SO", "Second Year": "SO",
    "3rd": "JR", "3rd YR": "JR", "3rd year": "JR", "Third Year": "JR",
    "4th": "SR", "4th YR": "SR", "4th year": "SR", "Fourth Year": "SR",
    "Sixth Year": "GR", "Red 5th": "GR",
    "RS FR": "R-FR", "RS So.": "R-SO", "RS SO": "R-SO", "RS Jr.": "R-JR", "RS Sr.": "R-SR", "RS SR": "R-SR",
    "Rf.": "R-FR",
}
UNCHANGED = {
    "Fr.": "FR", "Freshman": "FR", "So.": "SO", "Sophomore": "SO", "Jr.": "JR", "Junior": "JR", "Sr.": "SR",
    "Senior": "SR", "Gr.": "GR", "Graduate": "GR", "5th": "GR", "Fifth Year": "GR", "6th": "GR",
    "R-Fr.": "R-FR", "RS-So": "R-SO", "Redshirt Sophomore": "R-SO", "R-Jr.": "R-JR", "Redshirt Senior": "R-SR",
}
STAY_EMPTY = ["", "Rs.", "8th", "Redshirt", "Secondary", "Thirdly", "Firstly",
              # #458 review: WMT asks class_code which of a card's values is the class, so a rule anchored only at the
              # start took school and club names for one. Every appended rule now matches the whole label.
              "Second Baptist School", "1st Touch FC", "Third Coast Soccer", "Fourth Presbyterian", "Sixth Form College",
              "FY Academy", "Red Sox Academy", "Red Senators FC", "RS Soccer Club", "2nd Street Academy"]


def test_class_code() -> None:
    for label, code in NEW.items():
        ok(f"FIX {label!r} -> {code}", sidearm.class_code(label) == code, sidearm.class_code(label))
    for label, code in UNCHANGED.items():
        ok(f"CONTROL {label!r} stays {code}", sidearm.class_code(label) == code, sidearm.class_code(label))
    for label in STAY_EMPTY:
        ok(f"GUARD {label!r} stays empty", sidearm.class_code(label) == "", sidearm.class_code(label))


def test_wmt_falls_back() -> None:
    for label, code in (("First Year", "FR"), ("Second Year", "SO"), ("Third Year", "JR"), ("Fourth Year", "SR"),
                        ("Sixth Year", "GR")):
        ok(f"FIX WMT {label!r} -> {code} (no WMT pattern takes it first)", wmt.class_code(label) == code, wmt.class_code(label))
    ok("CONTROL WMT 'Redshirt Freshman' stays R-FR", wmt.class_code("Redshirt Freshman") == "R-FR")


def table(headers, rows) -> str:
    head = "".join(f'<th scope="col">{h}</th>' for h in headers)
    body = "".join("<tr>" + "".join(
        f'<td class="sidearm-table-player-name"><a href="/sports/womens-soccer/roster/{c.lower().replace(" ", "-")}/1">{c}</a></td>' if i == 1 else f"<td>{c}</td>"
        for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f"<html><head><title>2025 Women's Soccer Roster</title></head><body><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></body></html>"


def test_sidearm_table() -> None:
    html = table(["#", "Full Name", "Pos.", "Ht.", "Cl.", "Hometown"], [
        ["1", "Alex Example", "GK", "5-9", "Fy.", "Evans, Ga."], ["2", "Bea Sample", "D", "5-6", "2nd", "Riverton, Wyo."],
        ["3", "Cam Placeholder", "M", "5-4", "3rd YR", "Lakeview, B.C."], ["4", "Dana Madeup", "F", "5-8", "4th", "Springfield, Ore."],
        ["5", "Eli Fictional", "D", "5-7", "Rf.", "Accra, Ghana"], ["6", "Fay Invented", "M", "5-5", "Fr.", "Columbus, Ga."]])
    got = {p["name"]: p["classCode"] for p in sidearm.parse_roster(html, BASE)["players"]}
    ok("FIX a Sidearm table's 'Fy.' / '2nd' / '3rd YR' / '4th' / 'Rf.' read FR / SO / JR / SR / R-FR",
       [got.get(n) for n in ("Alex Example", "Bea Sample", "Cam Placeholder", "Dana Madeup", "Eli Fictional")]
       == ["FR", "SO", "JR", "SR", "R-FR"], got)
    ok("CONTROL 'Fr.' in the same table stays FR", got.get("Fay Invented") == "FR", got)


def test_wmt_list() -> None:
    def item(name, year):
        return (f'<li class="player-list-item"><a class="player-list-item__title-link" href="/sports/womens-soccer/roster/player/'
                f'{name.lower().replace(" ", "-")}">{name}</a><span class="player-list-item__position">M</span>'
                f'<span class="profile-field-content"><strong class="profile-field-content__title">Year</strong>'
                f'<span class="profile-field-content__value">{year}</span></span></li>')
    html = "<html><body><ul>" + item("Gil Madeup", "First Year") + item("Hal Example", "Fourth Year") + "</ul></body></html>"
    got = {p["name"]: p["classCode"] for p in wmt.parse_roster(html, BASE)["players"]}
    ok("FIX a WMT list item's 'First Year' / 'Fourth Year' read FR / SR",
       (got.get("Gil Madeup"), got.get("Hal Example")) == ("FR", "SR"), got)


def test_wmt_unlabelled_card() -> None:
    """#458 review: on a WMT card whose values carry no labels, a school named like an ordinal is not the class."""
    def card(name, *vals):
        items = "".join(f'<span class="roster-players-cards-item__info-item">{v}</span>' for v in vals)
        return (f'<div class="roster-card"><a class="roster-card__title-link" href="/sports/womens-soccer/roster/'
                f'{name.lower().replace(" ", "-")}/1">{name}</a><span class="roster-card__position">D</span>'
                f'<div class="roster-card__body">{items}</div></div>')
    html = ("<html><body>" + card("Ivy Sample", "5'6\"", "Houston, TX", "Second Baptist School")
            + card("Jo Example", "5'8\"", "Second Year", "Lakeview, B.C.") + "</body></html>")
    got = {p["name"]: p for p in wmt.parse_roster(html, BASE)["players"]}
    ivy, jo = got.get("Ivy Sample", {}), got.get("Jo Example", {})
    ok("GUARD a WMT card with no class value and the school 'Second Baptist School': no class, hometown 'Houston, TX'",
       (ivy.get("classLabel"), ivy.get("classCode"), ivy.get("hometown")) == ("", "", "Houston, TX"), ivy)
    ok("FIX a WMT card whose unlabelled value is 'Second Year' reads it as the class",
       (jo.get("classLabel"), jo.get("classCode"), jo.get("hometown")) == ("Second Year", "SO", "Lakeview, B.C."), jo)


def main() -> int:
    for fn in (test_class_code, test_wmt_falls_back, test_sidearm_table, test_wmt_list, test_wmt_unlabelled_card):
        print(fn.__name__)
        fn()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
