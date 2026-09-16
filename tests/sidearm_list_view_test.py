"""The legacy Sidearm list view as a roster fallback (issue #156).

    python tests/sidearm_list_view_test.py            # everything below, offline
    python tests/sidearm_list_view_test.py --verbose  # print every check, not only the failures

Offline: reads tests/fixtures/sidearm/ and makes no request.

Why this exists
---------------
Mercyhurst's roster page serves its players twice: as the legacy Sidearm list view
(li.sidearm-roster-player, with the name and bio link), and as a grid table whose columns are Pos.,
Ht., Academic Year, Hometown, High School, Previous School and #. The table has no Name column and no
player link, so parse_roster_tables skips it, and the page parsed to 0 players. The same layout gave 0
players on four more cached pages: hawaii-hilo (current roster), colorado-college 2025, fordham 2023
and charleston-wv 2023.

The fallback reads the list view only when the tables and the person cards give no player, and reads
every field from the player's own list item. It never joins list items to table rows by position,
which would put the wrong name on a player the moment the two views were ordered differently.

roster-list-view-no-name-column is trimmed from Mercyhurst's cached page: three players (list view
and the matching grid rows) and the coaching staff table. Names and bio-URL slugs are placeholders.

roster-list-view-table-reordered (issue #183) is trimmed from hawaii-hilo's cached page: four list-view
players and the grid rows for the same four, with the grid rows deliberately put in a different order
(no row at its player's list position). On every real page the two orders happened to agree, so a
parser that paired list item i with table row i passed every other check here while being wrong by
construction. On this fixture it gets every player's number and hometown wrong.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from bs4 import BeautifulSoup  # noqa: E402

from collect.adapters import sidearm  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "sidearm")
FIXTURE = "roster-list-view-no-name-column.html"
REORDERED = "roster-list-view-table-reordered.html"
BASE = "https://hurstathletics.com"
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


def read(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def li(name="Player Four", href="/sports/womens-soccer/roster/player-4/90004", number="4", pos_long="Goalkeeper",
       pos_short="GK", year="So.", hometown="Erie, Pa.", hs="Erie High") -> str:
    """One list-view item in the markup the fixture carries, for the synthetic cases."""
    return f"""<li class="sidearm-roster-player" data-player-url="{href}">
<div class="sidearm-roster-player-position"><span class="text-bold">
<span class="sidearm-roster-player-position-long-short hide-on-small-down">{pos_long}</span>
<span class="sidearm-roster-player-position-long-short hide-on-medium">{pos_short}</span></span>
<span class="sidearm-roster-player-height">5'8"</span></div>
<div class="sidearm-roster-player-name"><span class="sidearm-roster-player-jersey">
<span class="sidearm-roster-player-jersey-number">{number}</span></span>
<p><h3>{f'<a href="{href}">{name}</a>' if name else ''}</h3></p></div>
<div class="sidearm-roster-player-class-hometown"><span class="sidearm-roster-player-academic-year">{year}</span>
<span class="sidearm-roster-player-hometown">{hometown}</span>
<span class="sidearm-roster-player-highschool">{hs}</span></div></li>"""


def test_fixture_players() -> None:
    print("fixture: the Mercyhurst layout parses to its three players, and its staff as before")
    r = sidearm.parse_roster(read(FIXTURE), BASE)
    players = r["players"]
    ok("three players, not zero", len(players) == 3, len(players))
    ok("names come from the list view", [p["name"] for p in players] == ["Player One", "Player Two", "Player Three"],
       [p["name"] for p in players])
    ok("bio URLs are the players' own links",
       [p["bioUrl"] for p in players] == [f"{BASE}/sports/womens-soccer/roster/player-{i}/9000{i}" for i in (1, 2, 3)],
       [p["bioUrl"] for p in players])
    ok("numbers", [p["number"] for p in players] == ["0", "1", "2"], [p["number"] for p in players])
    ok("positions: the short label, normalised", [(p["posLabel"], p["pos"]) for p in players]
       == [("G", "GK"), ("G", "GK"), ("D", "D")], [(p["posLabel"], p["pos"]) for p in players])
    ok("heights, in inches too", [(p["height"], p["heightIn"]) for p in players]
       == [("6'2\"", 74), ("5'6\"", 66), ("5'5\"", 65)], [(p["height"], p["heightIn"]) for p in players])
    ok("class: the compact label and its code", [(p["classLabel"], p["classCode"]) for p in players]
       == [("Gr.", sidearm.class_code("Gr.")), ("Jr.", sidearm.class_code("Jr.")), ("Fr.", sidearm.class_code("Fr."))]
       and all(p["classCode"] for p in players), [(p["classLabel"], p["classCode"]) for p in players])
    ok("hometown and high school", [(p["hometown"], p["highSchool"]) for p in players]
       == [("Waterford, Pa.", "Fort LeBoeuf"), ("Medina, Ohio", "Walsh Jesuit High School"),
           ("Belfast, Northern Ireland", "Aquinas Diocesan")], [(p["hometown"], p["highSchool"]) for p in players])
    ok("staff table unchanged: two coaches, the head coach flagged",
       [(s["name"], s["title"], s["isHeadCoach"]) for s in r["staff"]]
       == [("Coach One", "Head Coach", True), ("Coach Two", "Assistant Coach", False)], r["staff"])
    ok("season from the title", r["season"] == 2026, r["season"])


def test_same_people_as_the_table() -> None:
    print("same people: each list-view player agrees with the grid table's row on number, hometown and high school")
    html = read(FIXTURE)
    soup = BeautifulSoup(html, "html.parser")
    grid = next(t for t in soup.find_all("table") if "rp_position_short" in str(t))
    heads = [c.get_text(" ", strip=True) for c in grid.find("tr").find_all("th")]
    ok("the grid table really has no Name column and no link", "Name" not in heads and not grid.find_all("a"), heads)
    ok("so the tables alone give no player", sidearm.parse_roster_tables(soup, BASE)[0] == [])
    rows = [[c.get_text(" ", strip=True) for c in tr.find_all("td")] for tr in grid.select("tbody tr")]
    col = {h: i for i, h in enumerate(heads)}
    players = sidearm.parse_roster(html, BASE)["players"]
    agree = [p["number"] == row[col["#"]] and p["hometown"] == row[col["Hometown"]] and p["highSchool"] == row[col["High School"]]
             and p["classLabel"] == row[col["Academic Year"]] and p["posLabel"] == row[col["Pos."]]
             for p, row in zip(players, rows)]
    ok(f"all {len(rows)} rows agree with the list view on number, position, class, hometown and high school",
       len(players) == len(rows) and all(agree), agree)


# The four players of roster-list-view-table-reordered, in list-view order, each field as that player's own
# list item states it. The grid table holds the same four in the order Charlie, Alpha, Delta, Bravo.
REORDERED_PLAYERS = [
    ("Alpha Player", "0", "Idaho Falls, Idaho", "Idaho Falls HS", "GK", "/sports/womens-soccer/roster/alpha-player/70001"),
    ("Bravo Player", "1", "Pasadena, California", "Flintridge Sacred Heart Academy", "GK", "/sports/womens-soccer/roster/bravo-player/70002"),
    ("Charlie Player", "2", "Lakewood, California", "Cerritos HS", "MID", "/sports/womens-soccer/roster/charlie-player/70003"),
    ("Delta Player", "3", "Santa Monica, California", "Santa Monica HS", "DEF", "/sports/womens-soccer/roster/delta-player/70004"),
]


def test_table_order_differs_from_list_order() -> None:
    print("order (#183): with the grid table in a different order, every field still comes from the player's own item")
    base = "https://hiloathletics.com"
    html = read(REORDERED)
    soup = BeautifulSoup(html, "html.parser")
    grid = next(t for t in soup.find_all("table") if "First" in t.find("tr").get_text(" "))
    heads = [c.get_text(" ", strip=True) for c in grid.find("tr").find_all("th")]
    col = {h: i for i, h in enumerate(heads)}
    rows = [[c.get_text(" ", strip=True) for c in tr.find_all("td")] for tr in grid.select("tbody tr")]
    list_numbers = [c.get_text(" ", strip=True) for c in soup.select(".sidearm-roster-player-jersey-number")]
    table_numbers = [r[col["No."]] for r in rows]
    # the property the fixture exists for: if this ever stops holding, the checks below prove nothing
    ok("fixture: the table holds the same players as the list view", sorted(table_numbers) == sorted(list_numbers),
       (table_numbers, list_numbers))
    ok("fixture: no table row sits at its player's list position",
       len(rows) == len(list_numbers) and all(t != l for t, l in zip(table_numbers, list_numbers)),
       (table_numbers, list_numbers))
    ok("fixture: the tables alone give no player, so the list view is what is read",
       sidearm.parse_roster_tables(soup, base)[0] == [])

    players = sidearm.parse_roster(html, base)["players"]
    got = [(p["name"], p["number"], p["hometown"], p["highSchool"], p["posLabel"], p["bioUrl"]) for p in players]
    want = [(n, num, home, hs, pos, base + url) for n, num, home, hs, pos, url in REORDERED_PLAYERS]
    ok("four players, in list-view order", [g[0] for g in got] == [w[0] for w in want], [g[0] for g in got])
    for g, w in zip(got, want):
        ok(f"{w[0]}: number, hometown, high school, position and bio URL are all from {w[0]}'s own item",
           g == w, f"got {g}")
    # and the same people seen from the table, joined by name rather than by position
    by_name = {f"{r[col['First']]} {r[col['Last']]}": r for r in rows}
    agree = [p["name"] in by_name and (p["number"], p["hometown"])
             == (by_name[p["name"]][col["No."]], by_name[p["name"]][col["Hometown"]]) for p in players]
    ok("each player's number and hometown match that player's table row, found by name",
       len(agree) == 4 and all(agree), agree)


def test_fallback_only_when_nothing_else() -> None:
    print("precedence: the list view is read only when the tables and person cards give no player")
    named = read("roster-players-and-staff.html")
    before = sidearm.parse_roster(named, "https://goarmywestpoint.com")
    extra = named.replace("</body>", f"<ul>{li()}</ul></body>")
    after = sidearm.parse_roster(extra, "https://goarmywestpoint.com")
    ok("a page whose table has names ignores a list view beside it", before == after and before["players"],
       (len(before["players"]), len(after["players"])))
    ok("... and no list-view player is added to it", "Player Four" not in [p["name"] for p in after["players"]])
    cards = ('<div class="s-person-card"><a href="/sports/womens-soccer/roster/card-player/555">x</a>'
             '<div class="s-person-details__personal-single-line"><h3>Card Player</h3></div></div>')
    both = f"<html><body>{cards}<ul>{li()}</ul></body></html>"
    ok("person cards come before the list view", [p["name"] for p in sidearm.parse_roster(both, BASE)["players"]] == ["Card Player"],
       [p["name"] for p in sidearm.parse_roster(both, BASE)["players"]])


def test_list_view_edges() -> None:
    print("edges: pronouns on the position, a repeated item, an item with no name")
    html = f"<html><body><ul>{li(pos_long='Goalkeeper (she/her/hers)', pos_short='GK (she/her/hers)')}</ul></body></html>"
    p = sidearm.parse_roster(html, BASE)["players"]
    ok("pronouns in parentheses are not part of the position", len(p) == 1 and (p[0]["posLabel"], p[0]["pos"]) == ("GK", "GK"),
       p[:1] and (p[0]["posLabel"], p[0]["pos"]))
    twice = f"<html><body><ul>{li()}{li()}</ul></body></html>"
    ok("the same player listed twice is one player", len(sidearm.parse_roster(twice, BASE)["players"]) == 1)
    nameless = f"<html><body><ul>{li(name='')}{li(name='Player Five', href='/sports/womens-soccer/roster/player-5/90005')}</ul></body></html>"
    ok("an item with no name is skipped, not published blank",
       [x["name"] for x in sidearm.parse_roster(nameless, BASE)["players"]] == ["Player Five"],
       [x["name"] for x in sidearm.parse_roster(nameless, BASE)["players"]])


def test_fixture_carries_no_contact_details() -> None:
    print("privacy: the list-view fixtures have no email, phone, mailto: or tel:")
    text = read(FIXTURE) + "\n" + read(REORDERED)
    for label, rx in [("email", r"[\w.+-]+@[\w-]+\.[\w.]+"), ("mailto", r"mailto:"), ("tel", r"tel:"),
                      ("10-digit phone", r"\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}\b"), ("7-digit phone", r"\b\d{3}[\s.-]\d{4}\b")]:
        found = re.findall(rx, text, re.I)
        ok(f"no {label}", not found, found[:3])


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose
    for case in (test_fixture_players, test_same_people_as_the_table, test_table_order_differs_from_list_order,
                 test_fallback_only_when_nothing_else,
                 test_list_view_edges, test_fixture_carries_no_contact_details):
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
