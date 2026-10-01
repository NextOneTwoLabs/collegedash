"""A pronoun set is never stored as a player's club (issue #337).

    python tests/club_pronouns_test.py

Amherst's 2023 roster stored 'She/Her' as the club of 26 players: some column or card label that season held pronouns
where the other seasons held the club. The fix is a guard where each parser sets `club` (Sidearm's _player_record,
both WMT player builders, the bio-text club), plus, on Sidearm person cards, a stat labelled as the club winning over
a custom field and a label that says "pronoun" never being one. When the guard fires, the collector logs one
name-free '!!' line naming the label or header, so a refresh's own fetch shows which column it was.

Made-up rows only (no real person). FIX checks fail on origin/main; GUARD checks pass on both and keep a future
header alias or label change from mapping pronouns to the club; CONTROL checks pass on both. Offline.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import common  # noqa: E402
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


def table(headers, rows) -> str:
    head = "".join(f'<th scope="col">{h}</th>' for h in headers)
    body = "".join("<tr>" + "".join(
        f'<td class="sidearm-table-player-name"><a href="/sports/womens-soccer/roster/{c.lower().replace(" ", "-")}/1">{c}</a></td>' if i == 1 else f"<td>{c}</td>"
        for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f"<html><head><title>2023 Women's Soccer Roster</title></head><body><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></body></html>"


def card(n: int, name: str, stats: dict) -> str:
    items = "".join(f'<li class="s-person-details__bio-stats-item"><span class="sr-only">{k}</span> {v}</li>' for k, v in stats.items())
    return (f'<div class="s-person-card"><a href="/sports/womens-soccer/roster/{name.lower().replace(" ", "-")}/{n}">x</a>'
            f'<div class="s-person-details__personal-single-line"><h3>{name}</h3></div><ul>{items}</ul></div>')


def cards(*cs) -> str:
    return f"<html><head><title>2023 Women's Soccer Roster</title></head><body>{''.join(cs)}</body></html>"


def wmt_item(name: str, fields: dict) -> str:
    fs = "".join(f'<span class="profile-field-content"><strong class="profile-field-content__title">{k}</strong>'
                 f'<span class="profile-field-content__value">{v}</span></span>' for k, v in fields.items())
    return (f'<li class="player-list-item"><a class="player-list-item__title-link" href="/sports/womens-soccer/roster/player/'
            f'{name.lower().replace(" ", "-")}">{name}</a><span class="player-list-item__position">M</span>{fs}</li>')


def reset() -> None:
    """Start the guard's count from zero (absent on main, where there is no guard)."""
    getattr(common, "club_guard_line", lambda where: None)("")


def by_name(players) -> dict:
    return {p["name"]: p for p in players}


def test_is_pronouns() -> None:
    f = getattr(common, "is_pronouns", None)
    ok("FIX common.is_pronouns exists", f is not None)
    if f is None:
        return
    for t in ("She/Her", "she/hers", "They/Them", "he/him/his", "(she/they)", "Pronouns: she/her", "she / her",
              "HE/HIM", "She/They/Any", "they, them", "ze/zir", "she/any"):
        ok(f"FIX is a pronoun set: {t!r}", f(t) is True)
    for t in ("All/Any", "ALL / ASK", "any/all", "Her", "She", "", None, "FC Stars ECNL", "Her Majesty FC", "NEFC/ECNL",
              "H.E. United", "FC Stars/Pre-ECNL", "Solar SC", "She Rocks FC / ECNL", "Them Lions", "her/her club"):
        ok(f"FIX is not a pronoun set: {t!r}", f(t) is False)


def test_sidearm_cards() -> None:
    html = cards(card(1, "Alex Example", {"Position": "D", "Academic Year": "Fr.", "Custom Field 1": "She/Her"}),
                 card(2, "Bea Sample", {"Position": "M", "Academic Year": "So.", "Custom Field 1": "FC Example"}),
                 card(3, "Cam Placeholder", {"Position": "F", "Custom Field 1": "they/them", "Club": "Example United"}),
                 card(4, "Dana Madeup", {"Position": "GK", "Pronouns": "she/her", "Custom Field 1": "Riverton SC"}))
    reset()  # start from zero
    p = by_name(sidearm.parse_roster(html, BASE)["players"])
    ok("CONTROL four card players", len(p) == 4, list(p))
    ok("FIX a custom field holding 'She/Her' is no club", p["Alex Example"]["club"] == "", p["Alex Example"]["club"])
    ok("CONTROL a custom field holding a club is unchanged", p["Bea Sample"]["club"] == "FC Example", p["Bea Sample"]["club"])
    ok("FIX a stat labelled 'Club' wins over a custom field", p["Cam Placeholder"]["club"] == "Example United", p["Cam Placeholder"]["club"])
    ok("GUARD a 'Pronouns' stat is never the club; the custom field is", p["Dana Madeup"]["club"] == "Riverton SC", p["Dana Madeup"]["club"])
    line = common.club_guard_line("2023 roster") if hasattr(common, "club_guard_line") else None
    ok("FIX the guard's line names the card label and the count, and no one",
       line == "  !! 2023 roster club: 1 pronoun-shaped value not stored as club (source: card label 'custom field 1')", line)


def test_sidearm_tables() -> None:
    html = table(["#", "Full Name", "Pos.", "Ht.", "Academic Year", "Hometown", "Pronouns", "Club Team"], [
        ["1", "Eli Fictional", "D", "5-7", "Fr.", "Lakeview, B.C.", "she/her", "Lakeview FC"],
        ["2", "Fay Invented", "M", "5-5", "So.", "Riverton, Wyo.", "they/them", ""]])
    p = by_name(sidearm.parse_roster(html, BASE)["players"])
    ok("GUARD a Pronouns column beside Club Team: the club comes from Club Team",
       (p["Eli Fictional"]["club"], p["Fay Invented"]["club"]) == ("Lakeview FC", ""), [(k, v["club"]) for k, v in p.items()])
    only = table(["#", "Full Name", "Pos.", "Ht.", "Academic Year", "Hometown", "Pronouns"], [
        ["3", "Gil Madeup", "F", "5-9", "Jr.", "Evans, Ga.", "he/him"]])
    q = by_name(sidearm.parse_roster(only, BASE)["players"])
    ok("GUARD a Pronouns column alone gives no club", q["Gil Madeup"]["club"] == "", q["Gil Madeup"]["club"])
    held = table(["#", "Full Name", "Pos.", "Ht.", "Academic Year", "Hometown", "Club"], [
        ["4", "Hal Example", "D", "5-8", "Sr.", "Springfield, Ore.", "She/Her"],
        ["5", "Ivy Sample", "M", "5-4", "Fr.", "Lakeview, B.C.", "Example SC"]])
    reset()
    r = by_name(sidearm.parse_roster(held, BASE)["players"])
    ok("FIX a Club column holding 'She/Her' stores no club; a real one is unchanged",
       (r["Hal Example"]["club"], r["Ivy Sample"]["club"]) == ("", "Example SC"), [(k, v["club"]) for k, v in r.items()])
    line = common.club_guard_line("2023 roster") if hasattr(common, "club_guard_line") else None
    ok("FIX the guard's line names the table header", line is not None and "(source: table header 'club')" in line, line)


def test_wmt() -> None:
    html = ("<html><body><ul>" + wmt_item("Jo Example", {"Hometown": "Evans, Ga.", "Club Team": "they/them"})
            + wmt_item("Kai Sample", {"Hometown": "Riverton, Wyo.", "Club Team": "Example FC"}) + "</ul></body></html>")
    p = by_name(wmt.parse_roster(html, BASE)["players"])
    ok("CONTROL two WMT list players", len(p) == 2, list(p))
    ok("FIX a WMT 'Club Team' field holding 'they/them' is no club", p.get("Jo Example", {}).get("club") == "", p.get("Jo Example"))
    ok("CONTROL a WMT club is unchanged", p.get("Kai Sample", {}).get("club") == "Example FC", p.get("Kai Sample"))


def test_collector_logs_and_bio_guard() -> None:
    src = open(os.path.join(ROOT, "collect", "athletics_site.py"), encoding="utf-8").read()
    ok("FIX the bio-text club goes through the guard", 'common.club_value(_extract_club(b.get("sections", {})), "bio text")' in src)
    ok("FIX each past-season parse logs the guard's line",
       'r = ad.parse_roster(h, base)\n            _log_club_guard(f"{y} roster")' in src.replace("\r\n", "\n"))
    ok("FIX the current-season parse logs the guard's line", '_log_club_guard(f"{season} roster")' in src)


def main() -> int:
    for fn in (test_is_pronouns, test_sidearm_cards, test_sidearm_tables, test_wmt, test_collector_logs_and_bio_guard):
        print(fn.__name__)
        try:
            fn()
        except Exception as e:  # a missing helper on main must read as a failed check, not a crash
            FAILS.append(f"{fn.__name__} raised {type(e).__name__}: {e}")
            print(f"  FAIL {fn.__name__} raised {type(e).__name__}: {e}")
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
