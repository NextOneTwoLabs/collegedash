"""Two WMT roster themes whose player fields carry no labels (issue #263).

    python tests/wmt_unlabeled_roster_test.py

wsucougars.com (li.roster-list-item > .roster-list-item__fields-item) and odusports.com
(.roster-card-item > .roster-card-component__profile-box) print position, height, class and hometown as
unlabelled groups, so the WMT adapter read every player there with a blank position (58 players), and
wsucougars.com with no name either. The fixtures are made up; their markup copies the two themes.

FIX checks fail on the code before #263. GUARD checks pass before and after: a labelled layout never
reaches the unlabelled reader, and a school span is never taken for a hometown.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collect.adapters import wmt  # noqa: E402

FAILS: list[str] = []
TOTAL = 0


def ok(name: str, cond: bool, detail="") -> None:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))


def fixture(name: str) -> str:
    with open(os.path.join(ROOT, "tests", "fixtures", "wmt", name + ".html"), encoding="utf-8") as f:
        return f.read()


def pick(p: dict, *keys) -> tuple:
    return tuple(p.get(k) for k in keys)


def test_list_theme() -> None:
    pl = wmt.parse_roster(fixture("roster-unlabeled-list"), "https://example.edu")["players"]
    ok("GUARD three players", len(pl) == 3, len(pl))
    ok("FIX names come from the title link, not the heading with its number and pronunciation widget",
       [p["name"] for p in pl] == ["Alex Example", "Bea Sample", "Cam Placeholder"], [p["name"] for p in pl])
    ok("FIX positions", [pick(p, "pos", "posLabel") for p in pl] == [("GK", "Goalkeeper"), ("M", "Midfielder"), ("F", "Forward")],
       [pick(p, "pos", "posLabel") for p in pl])
    ok("FIX heights", [pick(p, "height", "heightIn") for p in pl] == [("5'9\"", 69), ("5'4\"", 64), ("5'6\"", 66)],
       [pick(p, "height", "heightIn") for p in pl])
    ok("FIX class labels and codes", [pick(p, "classLabel", "classCode") for p in pl]
       == [("Redshirt Senior", "R-SR"), ("Sophomore", "SO"), ("Sixth Year", "")], [pick(p, "classLabel", "classCode") for p in pl])
    ok("FIX hometowns", [p["hometown"] for p in pl] == ["Springfield, Ore.", "Lakeview, B.C., Canada", ""], [p["hometown"] for p in pl])
    ok("GUARD a school with no comma is never taken for a hometown", pl[2]["hometown"] == "")
    ok("GUARD unlabelled school spans are left out, never guessed", all(not p["highSchool"] and not p["previousSchool"] for p in pl))
    ok("FIX numbers", [p["number"] for p in pl] == ["#0", "#14", "#9"], [p["number"] for p in pl])


def test_card_theme() -> None:
    pl = wmt.parse_roster(fixture("roster-unlabeled-card"), "https://example.edu")["players"]
    ok("GUARD three players with names", [p["name"] for p in pl] == ["Dana Madeup", "Eli Fictional", "Fay Invented"])
    ok("FIX positions", [pick(p, "pos", "posLabel") for p in pl] == [("D", "Defender"), ("M/F", "Midfielder/Forward"), ("GK", "Goalkeeper")],
       [pick(p, "pos", "posLabel") for p in pl])
    ok("FIX heights, and none where the box has none", [p["height"] for p in pl] == ["5'8\"", "", "5'11\""], [p["height"] for p in pl])
    ok("FIX class labels", [p["classLabel"] for p in pl] == ["Fourth Year", "Junior", "Redshirt Senior"], [p["classLabel"] for p in pl])
    ok("FIX hometowns; a lone school span is not a hometown", [p["hometown"] for p in pl] == ["Hilltown, Va.", "Bayside, England", ""],
       [p["hometown"] for p in pl])
    ok("FIX numbers", [p["number"] for p in pl] == ["#2", "#10", "#31"], [p["number"] for p in pl])


LABELLED_LIST = """<ul><li class="roster-list-item"><h3 class="roster-list-item__title">Gia Guard</h3>
<a href="/sports/womens-soccer/roster/player/gia-guard">bio</a><span class="roster-list-item__jersey-number">7</span>
<div class="roster-list-item__fields-item"><strong>Forward</strong><span>6'0"</span></div>
<span class="roster-player-list-profile-field--position">Defender</span>
<span class="roster-player-list-profile-field--height">5'7"</span>
<span class="roster-player-list-profile-field--class-level">Junior</span>
<span class="roster-player-list-profile-field--hometown">Elm, Ohio</span></li></ul>"""

LABELLED_CARD = """<div class="roster-card-item"><a href="/sports/womens-soccer/roster/player/hal-guard">x</a>
<h3 class="roster-card-item__title">Hal Guard</h3><span class="roster-card-item__position">Midfielder</span>
<div class="roster-player-card-profile-field"><span class="roster-player-card-profile-field__label">Hometown</span>
<span class="roster-player-card-profile-field__value">Oak, Iowa</span></div>
<div class="roster-card-component__profile-box"><strong>Forward</strong><span>Maple, Utah</span></div></div>"""


def test_labelled_layouts_untouched() -> None:
    p = wmt.parse_roster(LABELLED_LIST, "https://example.edu")["players"][0]
    ok("GUARD a labelled list item keeps its labelled fields", pick(p, "pos", "height", "classLabel", "hometown", "number")
       == ("D", "5'7\"", "Junior", "Elm, Ohio", "7"), p)
    c = wmt.parse_roster(LABELLED_CARD, "https://example.edu")["players"][0]
    ok("GUARD a labelled card keeps its position and hometown", pick(c, "pos", "hometown") == ("M", "Oak, Iowa"), c)


def main() -> int:
    for fn in (test_list_theme, test_card_theme, test_labelled_layouts_untouched):
        print(fn.__name__)
        fn()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
