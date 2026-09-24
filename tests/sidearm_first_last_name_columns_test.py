"""First and last name in two 'Name' columns, and a table with no player links (issue #313).

    python tests/sidearm_first_last_name_columns_test.py            # everything below, offline
    python tests/sidearm_first_last_name_columns_test.py --verbose  # print every check

Offline: the fixture is synthetic (placeholder names) and nothing is requested.

Why this exists
---------------
A legacy Sidearm grid table (sidearm-table-grid-template-1) heads BOTH the first-name and the
last-name column 'Name' (<td class="player_firstname"> then <td class="player_lastname">), and no
row carries a player link. _header_index kept the first 'Name' column only, so every player was
published under a first name alone (mercy: 31 of 32 one-word names) with no bio URL, and #263's
list-view position fill, which joins by bio URL, could not reach them (mercy: 32 of 32 positions
blank). The fix joins the two columns and, only for a table where NO row is linked, takes each
player's bio URL from the list item with the same name (unique on both sides, never row order).

Over the 1,378 cached roster pages + fixtures the fix changes 10 pages on 4 hosts (mercy,
goredfoxes, ksuowls, mvsusports) - every change is a name gaining its last name and a bio URL, plus
mercy's 32 blank positions filled - and nothing else.
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
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sidearm", "roster-first-last-name-columns-no-links.html")
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


def fixture() -> str:
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read()


def by_name(parsed: dict) -> dict:
    return {p["name"]: p for p in parsed["players"]}


def test_first_and_last_name_are_joined():
    p = by_name(sidearm.parse_roster(fixture(), BASE))
    ok("three players", len(p) == 3, list(p))
    ok("full names, two-word first name kept whole",
       sorted(p) == ["Alex Placeholder", "Mary Kate Example", "Pat Sample"], sorted(p))


def test_bio_urls_come_from_the_list_by_name():
    # The list is in a different order from the table on purpose: a join by row order would be wrong.
    p = by_name(sidearm.parse_roster(fixture(), BASE))
    want = {"Alex Placeholder": "alex-placeholder/9001", "Mary Kate Example": "mary-kate-example/9002",
            "Pat Sample": "pat-sample/9003"}
    for name, tail in want.items():
        got = p.get(name, {}).get("bioUrl")
        ok(f"{name}: bio URL from its own list item", got == f"{BASE}/{tail}", got)


def test_blank_positions_filled_and_other_fields_from_table():
    p = by_name(sidearm.parse_roster(fixture(), BASE))
    want = {"Alex Placeholder": "GK", "Mary Kate Example": "D", "Pat Sample": "F"}
    for name, code in want.items():
        got = (p.get(name, {}).get("pos"), p.get(name, {}).get("posLabel"))
        ok(f"{name}: position {code} from the list", got == (code, code), got)
    mk = p.get("Mary Kate Example", {})
    ok("other fields still read from the table",
       (mk.get("number"), mk.get("classCode"), mk.get("highSchool"), mk.get("previousSchool"), mk.get("major"))
       == ("4", "SR", "Example Academy", "Example Community College", "Nursing"), mk)


def test_social_links_come_with_the_list_link():
    # A made-up handle, added here rather than to the fixture file.
    ig = "https://www.instagram.com/placeholder.handle.example/"
    html = fixture().replace(
        '<h3><a href="/sports/womens-soccer/roster/alex-placeholder/9001">Alex Placeholder</a></h3></div>',
        '<h3><a href="/sports/womens-soccer/roster/alex-placeholder/9001">Alex Placeholder</a></h3></div>'
        f'<div class="sidearm-roster-player-social"><a href="{ig}">Instagram</a></div>')
    p = by_name(sidearm.parse_roster(html, BASE))
    ok("linked player takes the list item's social link", p["Alex Placeholder"]["social"] == {"instagram": ig},
       p["Alex Placeholder"]["social"])
    ok("player whose list item has none gets none", p["Pat Sample"]["social"] == {}, p["Pat Sample"]["social"])


def with_social(html: str, bio_id: int, handle: str) -> str:
    """Add a made-up social block (reserved .test host) to the list item whose link ends in /<bio_id>."""
    m = f'/{bio_id}">'
    s_i = html.index(m)
    end = html.index("</h3></div>", s_i) + len("</h3></div>")
    return html[:end] + f'<div class="sidearm-roster-player-social"><a href="https://instagram.com.example.test/{handle}">Instagram</a></div>' + html[end:]


def test_ambiguous_names_are_not_linked():
    # Two list items with the same name: no way to tell which bio is whose, so neither is taken.
    # Both same-name list items carry a handle, so no join by list order can dodge the check.
    html = with_social(with_social(fixture().replace(">Pat Sample</a>", ">Alex Placeholder</a>"),
                                   9001, "placeholder_one"), 9003, "placeholder_three")
    p = by_name(sidearm.parse_roster(html, BASE))
    ok("duplicate list name leaves the table player unlinked", p["Alex Placeholder"]["bioUrl"] is None,
       p["Alex Placeholder"])
    # A wrong join would publish one person's handle on another person's row (Bianque, PR #331).
    ok("unlinked row takes no social link from a same-name list item", p["Alex Placeholder"]["social"] == {},
       p["Alex Placeholder"]["social"])
    ok("unmatched table name stays unlinked", p["Pat Sample"]["bioUrl"] is None, p["Pat Sample"])
    ok("unique name beside them is linked", p["Mary Kate Example"]["bioUrl"] is not None, p["Mary Kate Example"])


def test_duplicate_table_names_are_not_linked():
    # Two TABLE rows with the same name and one list item: the one bio cannot belong to both rows, so
    # neither takes it (a join that only checked the list side would give both rows the same URL).
    html = with_social(fixture().replace(
        '<td class="player_firstname">Pat</td><td class="player_lastname">Sample</td>',
        '<td class="player_firstname">Alex</td><td class="player_lastname">Placeholder</td>'), 9001, "placeholder_two")
    players = sidearm.parse_roster(html, BASE)["players"]
    twins = [x for x in players if x["name"] == "Alex Placeholder"]
    ok("the table has two rows of the same name", len(twins) == 2, [x["name"] for x in players])
    ok("neither duplicate table row takes the one list bio", all(x["bioUrl"] is None for x in twins),
       [x["bioUrl"] for x in twins])
    ok("neither duplicate table row takes the list position", all(x["pos"] == "" for x in twins),
       [x["pos"] for x in twins])
    ok("neither duplicate table row takes the list item's social link", all(x["social"] == {} for x in twins),
       [x["social"] for x in twins])
    mk = next((x for x in players if x["name"] == "Mary Kate Example"), {})
    ok("unique name beside them is still linked", mk.get("bioUrl") == f"{BASE}/mary-kate-example/9002", mk)


def test_partly_linked_table_is_not_joined_by_name():
    # One linked row means the table has its own links: unlinked rows stay as #263 left them.
    html = fixture().replace('<td class="player_firstname">Pat</td>',
                             '<td class="player_firstname"><a href="/sports/womens-soccer/roster/pat-sample/9003">Pat</a></td>')
    p = by_name(sidearm.parse_roster(html, BASE))
    ok("linked row keeps its own link", p["Pat Sample"]["bioUrl"] == f"{BASE}/pat-sample/9003", p["Pat Sample"])
    ok("unlinked rows are not joined by name", p["Alex Placeholder"]["bioUrl"] is None
       and p["Alex Placeholder"]["pos"] == "", p["Alex Placeholder"])


def test_single_name_column_unchanged():
    idx, _, _ = sidearm._header_index(sidearm.BeautifulSoup(
        "<table><tr><th>#</th><th>Name</th><th>Pos.</th><th>Name</th></tr></table>", "html.parser").table)
    ok("non-adjacent second 'Name' is not a last-name column", "last name" not in idx, idx)


def test_name_then_full_name_is_not_joined():
    # 'Full Name' aliases to "name" too, but 'Name | Full Name' is not a first/last pair.
    html = fixture().replace('<th scope="col">Name</th><th scope="col">Name</th>',
                             '<th scope="col">Name</th><th scope="col">Full Name</th>')
    html = html.replace('<td class="player_lastname">Placeholder</td>', '<td>Alex Placeholder</td>')
    idx, _, _ = sidearm._header_index(sidearm.BeautifulSoup(html, "html.parser").table)
    ok("'Name | Full Name' has no last-name column", "last name" not in idx, idx)
    names = [x["name"] for x in sidearm.parse_roster(html, BASE)["players"]]
    ok("no doubled name", not any("Alex Alex" in n for n in names), names)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_first_and_last_name_are_joined, test_bio_urls_come_from_the_list_by_name,
                 test_blank_positions_filled_and_other_fields_from_table, test_ambiguous_names_are_not_linked,
                 test_social_links_come_with_the_list_link, test_duplicate_table_names_are_not_linked,
test_partly_linked_table_is_not_joined_by_name,
                 test_single_name_column_unchanged, test_name_then_full_name_is_not_joined):
        try:
            case()
        except Exception as e:  # a crash is a failure of that case, not of the run
            ok(f"{case.__name__} ran", False, repr(e))
    print(f"{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
