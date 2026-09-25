"""A missing value a site prints as a word is absent, never shown (issue #224).

    python tests/roster_placeholders_test.py

Sidearm's roster template writes 'Columbus, Ga. / null' for a player with no high school (boston-college,
creighton, lipscomb, connecticut, north-florida, tulsa, long-beach-state), keeps 'Evans, Ga. / null' whole in a
hometown column (houston, saint-mary-s), and georgia-southern's Club column reads 'None'; SoccerWire gives a state
of 'None'. The parser stored those words, so the roster tab read 'Accra, Ghana' | 'null'. Now they are dropped where
the value is read.

Made-up rows only (no real person). FIX checks fail on origin/main; CONTROL checks pass on both.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import common  # noqa: E402
from collect.adapters import sidearm  # noqa: E402

FAILS: list[str] = []
TOTAL = 0


def ok(name: str, cond: bool, detail="") -> None:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))


def table(headers, rows) -> str:
    head = "".join(f'<th scope="col">{h}</th>' for h in headers)
    body = "".join("<tr>" + "".join(
        f'<td class="sidearm-table-player-name"><a href="/sports/womens-soccer/roster/{c.lower().replace(" ", "-")}/1">{c}</a></td>' if i == 1 else f"<td>{c}</td>"
        for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f"<html><head><title>2026 Women's Soccer Roster</title></head><body><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></body></html>"


COMBINED = table(["#", "Full Name", "Pos.", "Ht.", "Academic Year", "Hometown / High School", "Club"], [
    ["1", "Alex Example", "GK", "5-9", "Fr.", "Columbus, Ga. / null", "None"],
    ["2", "Bea Sample", "D", "5-6", "So.", "Accra, Ghana / Accra Academy", "FC Example"],
    ["3", "Cam Placeholder", "M", "5-4", "Jr.", "Springfield, Ore. /", "null"],
])
SEPARATE = table(["#", "Full Name", "Pos.", "Ht.", "Academic Year", "Hometown", "High School"], [
    ["4", "Dana Madeup", "F", "5-8", "Sr.", "Evans, Ga. / null", "null"],
    ["5", "Eli Fictional", "D", "5-7", "Fr.", "Lakeview, B.C. / Canada", "Lakeview Secondary"],
    ["6", "Fay Invented", "M", "5-5", "So.", "Riverton, Wyo.", "Riverton HS"],
])


def test_roster_cells() -> None:
    a = {p["name"]: p for p in sidearm.parse_roster(COMBINED, "https://example.edu")["players"]}
    ok("CONTROL three players", len(a) == 3, list(a))
    ok("FIX 'Columbus, Ga. / null': hometown kept, high school absent (not 'null')",
       (a["Alex Example"]["hometown"], a["Alex Example"]["highSchool"]) == ("Columbus, Ga.", ""), a["Alex Example"])
    ok("FIX a Club cell reading 'None' is no club", a["Alex Example"]["club"] == "", a["Alex Example"]["club"])
    ok("FIX a Club cell reading 'null' is no club", a["Cam Placeholder"]["club"] == "", a["Cam Placeholder"]["club"])
    ok("CONTROL a real hometown / high school and club are unchanged",
       (a["Bea Sample"]["hometown"], a["Bea Sample"]["highSchool"], a["Bea Sample"]["club"]) == ("Accra, Ghana", "Accra Academy", "FC Example"))
    s = {p["name"]: p for p in sidearm.parse_roster(SEPARATE, "https://example.edu")["players"]}
    ok("FIX a hometown column holding 'Evans, Ga. / null' reads 'Evans, Ga.'", s["Dana Madeup"]["hometown"] == "Evans, Ga.", s["Dana Madeup"])
    ok("FIX a High School cell reading 'null' is absent", s["Dana Madeup"]["highSchool"] == "", s["Dana Madeup"])
    ok("CONTROL a slash that is part of a real hometown stays", s["Eli Fictional"]["hometown"] == "Lakeview, B.C. / Canada", s["Eli Fictional"])
    ok("CONTROL plain values are unchanged", (s["Fay Invented"]["hometown"], s["Fay Invented"]["highSchool"]) == ("Riverton, Wyo.", "Riverton HS"))


def test_helper() -> None:
    d = getattr(common, "drop_placeholders", None)
    ok("FIX common.drop_placeholders exists", d is not None)
    if d is None:
        return
    cases = {"null": "", "None": "", "undefined": "", "Columbus, Ga. / null": "Columbus, Ga.", "null / Rocklin HS": "Rocklin HS",
             "Nonesuch HS": "Nonesuch HS", "5/7": "5/7", "Trumbull, Conn. /": "Trumbull, Conn. /", "": "", None: ""}
    for s, want in cases.items():
        ok(f"drop_placeholders({s!r}) == {want!r}", d(s) == want, d(s))


def test_build_reads_stored_rows_without_placeholders() -> None:
    """Rows stored before the parser fix are shown without the words too, until they are collected again."""
    import build
    ath = {"data": {"roster": {"season": 2026, "players": [
        {"number": "1", "name": "Alex Example", "pos": "GK", "posLabel": "GK", "classCode": "FR", "classLabel": "Fr.",
         "height": "5'9\"", "hometown": "Columbus, Ga.", "highSchool": "null", "previousSchool": "", "club": "None", "major": ""},
        {"number": "2", "name": "Bea Sample", "pos": "D", "posLabel": "D", "classCode": "SO", "classLabel": "So.",
         "height": "5'6\"", "hometown": "Evans, Ga. / null", "highSchool": "Accra Academy", "previousSchool": "", "club": "FC Example", "major": ""}]},
        "rosterHistory": {"2025": [{"number": "3", "name": "Cam Placeholder", "pos": "M", "classCode": "JR",
                                    "hometown": "Springfield, Ore. / null", "highSchool": "null"}]}}}
    roster, hist = build.build_roster(ath)
    by = {p["name"]: p for p in roster["players"]}
    ok("FIX build: a stored 'null' high school is absent", by["Alex Example"]["highSchool"] == "", by["Alex Example"])
    ok("FIX build: a stored 'None' club is absent", by["Alex Example"].get("club") in ("", None), by["Alex Example"].get("club"))
    ok("FIX build: a stored 'Evans, Ga. / null' hometown reads 'Evans, Ga.'", by["Bea Sample"]["hometown"] == "Evans, Ga.")
    past = hist["2025"]["players"][0]
    ok("FIX build: past-season rows too", (past["hometown"], past["highSchool"]) == ("Springfield, Ore.", ""), past)
    ok("CONTROL build: real values are unchanged", (by["Bea Sample"]["highSchool"], by["Bea Sample"]["club"]) == ("Accra Academy", "FC Example"))


def test_soccerwire_state() -> None:
    src = open(os.path.join(ROOT, "collect", "commitments_soccerwire.py"), encoding="utf-8").read()
    ok("FIX SoccerWire's state goes through drop_placeholders ('None' is no state)",
       'common.state_code(common.drop_placeholders((_vals(meta, "state_province")' in src)


def main() -> int:
    for fn in (test_roster_cells, test_helper, test_build_reads_stored_rows_without_placeholders, test_soccerwire_state):
        print(fn.__name__)
        fn()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
