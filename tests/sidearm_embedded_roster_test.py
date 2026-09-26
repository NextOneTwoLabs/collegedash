"""Rosters from the legacy Sidearm Vue/Knockout template's embedded JSON (issue #145).

    python tests/sidearm_embedded_roster_test.py            # everything below, offline
    python tests/sidearm_embedded_roster_test.py --verbose  # print every check

Offline: every page is built here from placeholder names; no request, no page excerpt.

Why this exists
---------------
george-mason, utah-state and wyoming were skipped as "roster rendered in the browser" and published with no
staff and no players. Their roster pages have no table, person card or list item, but the server HTML does
carry the whole roster: `new Vue({ el: '...', data: () => ({ roster: {...} ...` holds a JSON object with
`players`, `coaches` and `support`. sidearm.parse_roster now reads that object - only when tables, person cards
and the list view all found no player, and only when the object has this template's shape.

The same object holds staff email and phone, player birthdates, social accounts, photos and bio text. None of
it may be stored. Rows are built from the named keys in EMBEDDED_PLAYER_FIELDS / EMBEDDED_STAFF_FIELDS (plus
the name and height keys read by name), never by copying the object. The PII checks below put a distinctive
sentinel in every forbidden field and assert that none reaches the parsed output. They then map each
forbidden key into the allowlist in turn and assert the check catches it, so the check cannot pass vacuously.
tools/camps_check.contact_hits runs over the output too; it exempts example.test / 555-555-01xx by design (the
values this fixture must use), so the sentinel check is the leak test and the scanner is a second net.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect.adapters import sidearm  # noqa: E402
import camps_check  # noqa: E402

BASE = "https://athletics.example.edu"
FAILS: list[str] = []
TOTAL = 0
VERBOSE = False

# Every field a row must never carry, with the sentinel the fixture puts in it. Players and staff both get
# every one of them (the real template has email/phone on staff and birthdate/socials on players; the fixture
# does not rely on which is which).
PLAYER_FORBIDDEN = ("email", "phone", "birthdate", "twitter_username", "instagram_username", "facebook_username",
                    "linkedin_username", "snapchat_username", "tiktok_username", "twitch_username", "youtube_username",
                    "cameo_username", "socials", "image", "images", "header_image", "bio", "bio_fields", "pronouns",
                    "weight")
STAFF_FORBIDDEN = ("email", "phone", "birthdate", "twitter", "image", "custom1", "custom2", "custom3", "custom4")


def sentinel(who: str, key: str) -> str:
    if key == "email":
        return f"sentinel-{who}@example.test"
    if key == "phone":
        return "555-555-0142"
    return f"SENTINEL-{who}-{key}"


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def player(n: int, **over) -> dict:
    p = {"rp_id": 900 + n, "player_id": 700 + n, "first_name": "Player", "last_name": f"Number{n}",
         "jersey_number": str(n), "position_short": "D", "position_long": "Defender", "academic_year_short": "So.",
         "academic_year_long": "Sophomore", "height_feet": 5, "height_inches": 7, "hometown": f"Town {n}, ST",
         "highschool": f"High School {n}", "previous_school": "", "major": "", "rp_hide": False, "rp_hide_bio": False,
         "custom1": None, "custom2": None, "custom3": None, "gender": "F"}
    for k in PLAYER_FORBIDDEN:
        p[k] = [{"handle": sentinel(f"p{n}", k)}] if k in ("socials", "images", "bio_fields") else sentinel(f"p{n}", k)
    p.update(over)
    return p


def staff(n: int, title: str) -> dict:
    s = {"id": 500 + n, "staff_id": 0, "firstname": "Staff", "lastname": f"Member{n}", "title": title}
    for k in STAFF_FORBIDDEN:
        s[k] = {"filename": sentinel(f"s{n}", k)} if k == "image" else sentinel(f"s{n}", k)
    return s


def roster_obj(players: list, coaches: list, support: list | None = None, **over) -> dict:
    o = {"id": 1, "template_id": 1, "breakdown_size": "full", "title": "2026 Women's Soccer Roster", "display_coaches": True,
         "display_fields": [], "season": {"id": 1, "title": "2026"}, "sport": {"id": 1, "title": "Women's Soccer"},
         "image": None, "players": players, "all_staff_image": None, "coaches": coaches, "support": support or [],
         "players_by_gender": {"F": [p.get("rp_id") for p in players if isinstance(p, dict)]}}
    o.update(over)
    return o


def vue_script(obj: dict) -> str:
    return ("<script>require(['vue', 'knockout'], function (Vue, ko) { var instance = new Vue({ el: '#roster-app', "
            "data: () => ({ roster: " + json.dumps(obj) + ", selected: null }) }); });</script>")


def page(body: str = "", script: str = "") -> str:
    return ("<html><head><title>2026 Women's Soccer Roster - Example University Athletics</title></head><body>"
            '<div id="roster-app"><p>Loading...</p></div>' + body + script + "</body></html>")


def table(rows: list[tuple[int, str]]) -> str:
    trs = "".join(f'<tr><td>{n}</td><th scope="row"><a href="/sports/womens-soccer/roster/table-player-{n}/{8000 + n}">'
                  f'Table Player{n}</a></th><td>{pos}</td><td>5\'6"</td><td>Jr.</td><td>Town, ST / High School</td></tr>'
                  for n, pos in rows)
    return ("<table><thead><tr><th>#</th><th>Name</th><th>Pos.</th><th>Ht.</th><th>Year</th>"
            "<th>Hometown / High School</th></tr></thead><tbody>" + trs + "</tbody></table>")


def full_page() -> str:
    return page(script=vue_script(roster_obj(
        [player(1), player(2, position_short="", position_long="Midfielder", academic_year_short="R-Fr.",
                            height_feet=None, height_inches=None, previous_school="Example College", major="Biology"),
         player(3, rp_hide=True)],
        [staff(1, "Head Coach"), staff(2, "Assistant Coach ")],
        [staff(3, "Athletic Trainer")])))


def parse(html: str) -> dict:
    return sidearm.parse_roster(html, BASE)


def leaks(out: dict) -> list[str]:
    text = json.dumps(out)
    found = [f"p{n}.{k}" for n in (1, 2, 3) for k in PLAYER_FORBIDDEN if sentinel(f"p{n}", k) in text]
    found += [f"s{n}.{k}" for n in (1, 2, 3) for k in STAFF_FORBIDDEN if sentinel(f"s{n}", k) in text]
    found += [f"'SENTINEL' in output"] if "SENTINEL" in text or "sentinel" in text else []
    return found


def test_maps_players_and_staff():
    r = parse(full_page())
    p = {x["name"]: x for x in r["players"]}
    ok("two players (the rp_hide one is skipped)", sorted(p) == ["Player Number1", "Player Number2"], sorted(p))
    a = p.get("Player Number1", {})
    ok("number, pos, label", (a.get("number"), a.get("pos"), a.get("posLabel")) == ("1", "D", "D"), a)
    ok("height from feet and inches", (a.get("height"), a.get("heightIn")) == ("5'7\"", 67), a)
    ok("class", (a.get("classLabel"), a.get("classCode")) == ("So.", "SO"), a)
    ok("hometown and high school", (a.get("hometown"), a.get("highSchool")) == ("Town 1, ST", "High School 1"), a)
    ok("no bio URL and no social", a.get("bioUrl") is None and a.get("social") == {}, a)
    b = p.get("Player Number2", {})
    ok("empty short position falls back to the long one", (b.get("pos"), b.get("posLabel")) == ("M", "Midfielder"), b)
    ok("no height when the site gives none", (b.get("height"), b.get("heightIn")) == ("", None), b)
    ok("redshirt class, previous school, major",
       (b.get("classCode"), b.get("previousSchool"), b.get("major")) == ("R-FR", "Example College", "Biology"), b)
    ok("player rows carry exactly the table path's keys", set(a) == {
        "number", "name", "pos", "posLabel", "height", "heightIn", "classLabel", "classCode", "hometown", "highSchool",
        "previousSchool", "major", "club", "bioUrl", "social"}, sorted(a))
    s = r["staff"]
    ok("staff are coaches then support", [x["name"] for x in s] == ["Staff Member1", "Staff Member2", "Staff Member3"], s)
    ok("head coach identified", [x["isHeadCoach"] for x in s] == [True, False, False], s)
    ok("coaches are coaching staff; support by title", [x["isCoach"] for x in s] == [True, True, False], s)
    ok("titles trimmed", [x["title"] for x in s] == ["Head Coach", "Assistant Coach", "Athletic Trainer"], s)
    ok("staff rows carry exactly the table path's keys",
       all(set(x) == {"name", "title", "isHeadCoach", "isCoach", "bioUrl", "social"} and x["bioUrl"] is None for x in s), s)
    ok("season from the page title", r["season"] == 2026, r["season"])


def test_no_forbidden_field_reaches_the_output():
    r = parse(full_page())
    ok("no sentinel in the serialized output", not leaks(r), leaks(r))
    emails, phones = camps_check.contact_hits(json.dumps(r))
    ok("contact scanner finds nothing in the output", not emails and not phones, emails + phones)
    ok("no '@' anywhere in the output", "@" not in json.dumps(r))
    # the sentinels really are in the page, so the check above is not vacuous
    html = full_page()
    ok("every sentinel is in the fixture page", all(sentinel("p1", k) in html for k in PLAYER_FORBIDDEN)
       and all(sentinel("s1", k) in html for k in STAFF_FORBIDDEN))


def test_letting_any_field_through_fails():
    # Map each forbidden key into the allowlist in turn: the leak check must then catch it.
    p_orig, s_orig = dict(sidearm.EMBEDDED_PLAYER_FIELDS), dict(sidearm.EMBEDDED_STAFF_FIELDS)
    try:
        for k in PLAYER_FORBIDDEN:
            sidearm.EMBEDDED_PLAYER_FIELDS.clear()
            sidearm.EMBEDDED_PLAYER_FIELDS.update({**p_orig, k: "major"})
            ok(f"player '{k}' let through is caught", f"p1.{k}" in leaks(parse(full_page())))
        sidearm.EMBEDDED_PLAYER_FIELDS.clear()
        sidearm.EMBEDDED_PLAYER_FIELDS.update(p_orig)
        for k in STAFF_FORBIDDEN:
            sidearm.EMBEDDED_STAFF_FIELDS.clear()
            sidearm.EMBEDDED_STAFF_FIELDS.update({**s_orig, k: "title"})
            ok(f"staff '{k}' let through is caught", f"s1.{k}" in leaks(parse(full_page())))
    finally:
        sidearm.EMBEDDED_PLAYER_FIELDS.clear()
        sidearm.EMBEDDED_PLAYER_FIELDS.update(p_orig)
        sidearm.EMBEDDED_STAFF_FIELDS.clear()
        sidearm.EMBEDDED_STAFF_FIELDS.update(s_orig)
    ok("allowlists restored", sidearm.EMBEDDED_PLAYER_FIELDS == p_orig and sidearm.EMBEDDED_STAFF_FIELDS == s_orig)


def test_table_page_is_read_from_the_table_only():
    html = page(body=table([(7, "F"), (8, "GK")]),
                script=vue_script(roster_obj([player(1)], [staff(1, "Head Coach")])))
    r = parse(html)
    ok("players from the table", [p["name"] for p in r["players"]] == ["Table Player7", "Table Player8"], r["players"])
    ok("table player links kept", all(p["bioUrl"] for p in r["players"]))
    ok("nothing from the JSON", "Player Number1" not in json.dumps(r) and not leaks(r))


def test_table_players_without_staff_take_no_staff_from_the_json():
    html = page(body=table([(7, "F")]), script=vue_script(roster_obj([player(1)], [staff(1, "Head Coach")])))
    r = parse(html)
    ok("table players found", len(r["players"]) == 1, r["players"])
    ok("no staff taken from the JSON", r["staff"] == [], r["staff"])


def test_signature_with_an_empty_players_array():
    r = parse(page(script=vue_script(roster_obj([], [staff(1, "Head Coach")]))))
    ok("empty players array: 0 players", r["players"] == [], r["players"])
    ok("empty players array: 0 staff", r["staff"] == [], r["staff"])


def test_nuxt_placeholder():
    html = ('<html><head><title>2026 Women\'s Soccer Roster</title></head><body><div class="c-rosterpage">Loading...</div>'
            '<script type="application/json" id="__NUXT_DATA__">[{"state":1},{"players":2},[]]</script></body></html>')
    r = parse(html)
    ok("Nuxt placeholder: 0 players and 0 staff", r["players"] == [] and r["staff"] == [], r)


def test_players_json_without_the_signature():
    obj = json.dumps(roster_obj([player(1)], [staff(1, "Head Coach")]))
    for label, script in (("a bare assignment", f"<script>var roster = {obj};</script>"),
                          ("a different Vue app", f"<script>new Vue({{ el: '#x', data: () => ({{ schedule: {obj} }}) }});</script>")):
        r = parse(page(script=script))
        ok(f"{label}: 0 players and 0 staff", r["players"] == [] and r["staff"] == [], r)


def test_signature_needs_the_template_shape():
    cases = {
        "no template_id": roster_obj([player(1)], [staff(1, "Head Coach")], template_id=None),
        "players without jersey_number": roster_obj([{k: v for k, v in player(1).items() if k != "jersey_number"}],
                                                    [staff(1, "Head Coach")]),
    }
    del cases["no template_id"]["template_id"]
    for label, obj in cases.items():
        r = parse(page(script=vue_script(obj)))
        ok(f"{label}: 0 players and 0 staff", r["players"] == [] and r["staff"] == [], r)
    r = parse(page(script="<script>new Vue({ el: '#roster-app', data: () => ({ roster: {not json} }) });</script>"))
    ok("unparsable object: 0 players", r["players"] == [] and r["staff"] == [], r)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_maps_players_and_staff, test_no_forbidden_field_reaches_the_output, test_letting_any_field_through_fails,
                 test_table_page_is_read_from_the_table_only, test_table_players_without_staff_take_no_staff_from_the_json,
                 test_signature_with_an_empty_players_array, test_nuxt_placeholder, test_players_json_without_the_signature,
                 test_signature_needs_the_template_shape):
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
