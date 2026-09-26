"""Regression tests for club name matching and the reviewed alias table (issue #228).

    python tests/clubs_alias_test.py            # everything below, offline
    python tests/clubs_alias_test.py --verbose  # print every check, not only the failures

Offline: reads the committed data/clubs.json and the committed sources, makes no request and writes
nothing. Exit 0 when every check passes, 1 otherwise.

What these hold down, and why each one exists
---------------------------------------------
The whole feature is one decision repeated 11,000 times: does this club string mean the same club
as that one? A wrong "yes" is invisible on the site - two clubs quietly become one row - so the
tests are written against the specific pairs the #228 probe found, by name:

  cleanup       clean_key folds case, punctuation, whitespace and accents and nothing else. It must
                NOT drop a bracketed state, a league tag or a club-type word, because those are the
                only things telling some clubs apart
  near misses   "Ohio Premier" / "Ohio Elite", "Beach FC (CA)" / "Beach FC (VA)", "KC Fusion" /
                "NC Fusion", "Chicago FC United" / "Chicago Fire United", "Evolution" /
                "Revolution", "Richmond Kickers" / "Richmond Strikers" and the rest stay separate,
                in the committed table as well as in the rules
  MVLA          the five spellings of Mountain View Los Altos resolve to one club, which is only
                possible through reviewed aliases - "MVLA" matches no rule
  unmatched     a club string nobody has reviewed keeps its raw spelling, is marked unmatched, and
                turns up in the review report rather than being merged into something similar
  table         a contradictory edit to data/clubs.json (an alias pointing nowhere, one key
                claiming two clubs, a key that is not cleaned) fails the build instead of being
                ignored
  precedence    clubs.resolve: sources that agree keep the most trusted spelling; sources that
                disagree resolve to the most recently updated one, and a roster page is dated with
                its season rather than with the day we fetched it (every source is fetched in the
                same refresh, so fetch dates would make the roster win every time)
  suggestions   suggest_key groups strings for the review report only. The test states the pairs it
                gets wrong, so that nobody promotes it into the matching path
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import clubs  # noqa: E402
from collect import common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def check(name: str, ok: bool, detail: str = "") -> None:
    global TOTAL
    TOTAL += 1
    if not ok:
        FAILS.append(name)
        print(f"FAIL {name}" + (f": {detail}" if detail else ""))
    elif VERBOSE:
        print(f"ok   {name}" + (f": {detail}" if detail else ""))


# every pair here is two different clubs, or one club in two states
NEAR_MISSES = [
    ("Ohio Premier", "Ohio Elite"),
    ("Ohio Premier", "Ohio Elite Soccer Academy"),
    ("Florida Premier FC", "Florida Elite"),
    ("Florida Elite", "Florida United"),
    ("Beach FC (CA)", "Beach FC (VA)"),
    ("KC Fusion", "NC Fusion"),
    ("Chicago FC United", "Chicago Fire United"),
    ("Evolution SC", "Revolution SC"),
    ("Richmond Kickers", "Richmond Strikers"),
    ("Cincinnati Elite", "Cincinnati United"),
    ("Real Futbol Academy", "Total Futbol Academy"),
    ("Arlington SC", "Burlington SC"),
    ("Carolina Elite Soccer Academy", "Ohio Elite Soccer Academy"),
    ("Sporting CA", "Sporting Jax"),
    ("Internationals SC", "Internazionale"),
    ("FC United (IL)", "United FC (WI)"),
]

MVLA = ["Mtn. View Los Altos SC", "Mountain View Los Altos SC (MVLA)", "Mountain View Los Altos SC",
        "Mountain View Los Altos", "MVLA"]


def test_cleanup() -> None:
    same = [("FC Delco", "FC DELCO"), ("Florida Kraze Krush", "Florida Kraze/Krush"),
            ("St. Louis Development Academy", "St Louis Development Academy"),
            ("Slammers HB Køge", "Slammers HB Koge"), ("NDC-Ontario", "NDC Ontario"),
            ("Hawai’i Rush", "Hawaii Rush"), ("Player's Development Academy", "Players Development Academy"),
            ("Utah Royals FC - AZ", "Utah Royals FC AZ"), ("  Solar   SC  ", "Solar SC")]
    for a, b in same:
        check(f"cleanup: {a!r} == {b!r}", clubs.clean_key(a) == clubs.clean_key(b),
              f"{clubs.clean_key(a)!r} vs {clubs.clean_key(b)!r}")
    keeps = [("Beach FC (CA)", "ca"), ("Beach FC (VA)", "va"), ("Ohio Premier ECNL", "ecnl"),
             ("Solar Soccer Club", "soccer"), ("Nationals GA", "ga")]
    for raw, token in keeps:
        check(f"cleanup keeps {token!r} in {raw!r}", token in clubs.clean_key(raw).split(), clubs.clean_key(raw))
    check("cleanup: empty string", clubs.clean_key("") == "" and clubs.clean_key(None) == "")


def test_near_misses(table: clubs.Table) -> None:
    # the pair checks below pass trivially when neither name is in the table, so first make sure
    # the committed table really does carry both sides of several of these pairs
    both = [(a, b) for a, b in NEAR_MISSES
            if table.match(a).status == "matched" and table.match(b).status == "matched"]
    check("near misses: the committed table carries both sides of several pairs", len(both) >= 5,
          f"{len(both)} of {len(NEAR_MISSES)}: {[a for a, _ in both][:6]}")
    for a, b in NEAR_MISSES:
        check(f"rules keep apart: {a!r} / {b!r}", clubs.clean_key(a) != clubs.clean_key(b))
        ma, mb = table.match(a), table.match(b)
        both_known = ma.status == "matched" and mb.status == "matched"
        check(f"table keeps apart: {a!r} / {b!r}", not (both_known and ma.clubId == mb.clubId),
              f"both resolve to {ma.clubId}")


def test_mvla(table: clubs.Table) -> None:
    ids = {s: table.match(s).clubId for s in MVLA}
    check("MVLA: every spelling matches", all(table.match(s).status == "matched" for s in MVLA),
          str({s: table.match(s).status for s in MVLA}))
    check("MVLA: one club for all five spellings", len(set(ids.values())) == 1, str(ids))
    m = table.match("MVLA")
    check("MVLA: the raw string is kept", m.raw == "MVLA" and m.name and m.name != "MVLA", str(m.name))
    check("MVLA: 'MVLA' is a reviewed alias, not a rule",
          clubs.clean_key("MVLA") in table.aliases and clubs.suggest_key("MVLA") != clubs.suggest_key("Mountain View Los Altos SC"))


def test_unmatched(table: clubs.Table) -> None:
    made_up = "Chitu Test Soccer Club That Nobody Reviewed"
    m = table.match(made_up)
    check("unmatched: status", m.status == "unmatched", m.status)
    check("unmatched: raw kept", m.raw == made_up and m.clubId is None)
    rec: dict = {}
    clubs.annotate(rec, [{"raw": made_up, "source": "roster page", "updated": "2026-08-01"}], table)
    check("unmatched: the record still shows the raw club", rec["club"] == made_up)
    check("unmatched: the record says it is unmatched", rec["clubInfo"]["status"] == "unmatched")
    r = clubs.Recorder(table)
    r.observe(made_up, source="roster page", slug="test-program")
    r.observe("Ohio Premier", source="roster page", slug="test-program")
    report = r.report()
    keys = [row["key"] for row in report["unmatched"]]
    check("unmatched: listed in the review report", clubs.clean_key(made_up) in keys, str(keys[:3]))
    check("unmatched: a matched club is not listed", clubs.clean_key("Ohio Premier") not in keys)
    check("unmatched: counted as new since the last build", clubs.clean_key(made_up) in report["newSinceLastBuild"]["keys"])
    check("unmatched: the report explains itself to a reader", len(report["howToUse"]) >= 3)
    again = r.report(report)
    row = next(x for x in again["unmatched"] if x["key"] == clubs.clean_key(made_up))
    check("unmatched: a name already in the report is not new twice", row["new"] is False)
    check("unmatched: firstSeen is carried forward", row["firstSeen"] == report["unmatched"][0]["firstSeen"])


def test_not_a_club(table: clubs.Table) -> None:
    for raw in ("N/A", "None"):
        m = table.match(raw)
        check(f"not-a-club: {raw!r}", m.status == "not-a-club", m.status)
    rec: dict = {"club": "N/A"}
    clubs.annotate(rec, [{"raw": "N/A", "source": "roster page", "updated": "2026-08-01"}], table)
    check("not-a-club: the placeholder is not shown as a club", rec["club"] == "" and rec["clubSource"] is None)
    check("not-a-club: it is still recorded", rec["clubInfo"]["status"] == "not-a-club")


def test_table_validation() -> None:
    good = {"clubs": [{"id": "a", "name": "Alpha SC"}, {"id": "b", "name": "Beta SC"}],
            "aliases": {"alpha soccer club": {"club": "a"}}, "notAClub": {"n a": "placeholder"}}
    t = clubs.Table(good)
    check("table: a club's own name matches", t.match("Alpha SC").clubId == "a")
    check("table: an alias matches", t.match("Alpha Soccer Club").clubId == "a")
    bad = [
        ("alias points at an unknown club", {**good, "aliases": {"alpha soccer club": {"club": "nope"}}}),
        ("alias key is not cleaned", {**good, "aliases": {"Alpha Soccer Club": {"club": "a"}}}),
        ("one key claims two clubs", {**good, "aliases": {"beta sc": {"club": "a"}}}),
        ("two clubs share an id", {**good, "clubs": [{"id": "a", "name": "Alpha SC"}, {"id": "a", "name": "Other"}]}),
        ("a key is both an alias and not-a-club", {**good, "notAClub": {"alpha soccer club": "x"}}),
    ]
    for label, doc in bad:
        raised = False
        try:
            clubs.Table(doc)
        except clubs.TableError:
            raised = True
        check(f"table rejects: {label}", raised)


def test_precedence(table: clubs.Table) -> None:
    check("roster pages are dated by season, not by fetch date", clubs.season_date(2026) == "2026-08-01")
    check("a roster with no season has no date", clubs.season_date(None) is None)

    agree = clubs.resolve([{"raw": "Ohio Premier ECNL", "source": "roster page", "updated": "2026-08-01"},
                           {"raw": "Ohio Premier", "source": "TopDrawerSoccer", "updated": "2026-09-09"}], table)
    check("agreeing sources: the most trusted spelling is kept", agree["raw"] == "Ohio Premier", str(agree))
    check("agreeing sources: no conflict is recorded", "conflict" not in agree)

    newer_roster = clubs.resolve([{"raw": "Crossfire Premier SC", "source": "TopDrawerSoccer", "updated": "2024-05-01"},
                                  {"raw": "Eastside FC", "source": "roster page", "updated": "2026-08-01"}], table)
    check("disagreeing sources: the most recent wins", newer_roster["raw"] == "Eastside FC", str(newer_roster))
    check("disagreeing sources: the other is recorded as a conflict",
          [c["raw"] for c in newer_roster["conflict"]] == ["Crossfire Premier SC"], str(newer_roster))

    newer_commit = clubs.resolve([{"raw": "Eastside FC", "source": "roster page", "updated": "2026-08-01"},
                                  {"raw": "Crossfire Premier SC", "source": "SoccerWire", "updated": "2026-08-20"}], table)
    check("disagreeing sources: a newer commitment record wins", newer_commit["raw"] == "Crossfire Premier SC", str(newer_commit))

    undated = clubs.resolve([{"raw": "Eastside FC", "source": "roster page", "updated": None},
                             {"raw": "Crossfire Premier SC", "source": "SoccerWire", "updated": "2020-01-01"}], table)
    check("an undated source never beats a dated one", undated["raw"] == "Crossfire Premier SC", str(undated))

    tie = clubs.resolve([{"raw": "Eastside FC", "source": "roster page", "updated": "2026-08-01"},
                         {"raw": "Crossfire Premier SC", "source": "TopDrawerSoccer", "updated": "2026-08-01"}], table)
    check("a tie falls back to the source order", tie["raw"] == "Crossfire Premier SC", str(tie))
    check("no candidates resolves to nothing", clubs.resolve([], table) is None)
    check("an empty club string is not a candidate", clubs.resolve([{"raw": "", "source": "roster page"}], table) is None)


def test_suggestions_are_only_suggestions(table: clubs.Table) -> None:
    wrong = [("FC United (IL)", "United FC (WI)"), ("Beach FC (CA)", "Beach FC (VA)"),
             ("Elite Girls Academy", "Elite 11")]
    for a, b in wrong:
        check(f"suggestions would merge {a!r} / {b!r} - so they are not matches",
              clubs.suggest_key(a) == clubs.suggest_key(b), f"{clubs.suggest_key(a)!r} vs {clubs.suggest_key(b)!r}")
        check(f"but matching keeps {a!r} / {b!r} apart", clubs.clean_key(a) != clubs.clean_key(b))
    ok = [("St. Louis Scott Gallagher ECNL 06/07 Navy", "St. Louis Scott Gallagher"),
          ("Eclipse Select SC", "Eclipse Select Soccer Club")]
    for a, b in ok:
        check(f"suggestion groups {a!r} with {b!r}", clubs.suggest_key(a) == clubs.suggest_key(b))
    r = clubs.Recorder(table)
    r.observe("Ohio Premier Soccer Club 08 ECNL Blue", source="roster page", slug="test-program")
    row = r.report()["unmatched"][0]
    check("the review report offers a suggestion", (row["suggestion"] or {}).get("club") == table.match("Ohio Premier").clubId,
          str(row["suggestion"]))
    check("the suggestion says it is a suggestion", "suggestion" in json.dumps(row["suggestion"]).lower()
          or "groups with" in (row["suggestion"] or {}).get("why", ""))


def test_committed_table(table: clubs.Table) -> None:
    check("committed table: clubs are seeded", len(table.clubs) >= 250, str(len(table.clubs)))
    check("committed table: aliases are seeded", len(table.aliases) >= 400, str(len(table.aliases)))
    ids = [c["id"] for c in table.clubs.values()]
    check("committed table: ids are unique", len(ids) == len(set(ids)))
    check("committed table: every club has a name", all((c.get("name") or "").strip() for c in table.clubs.values()))
    countries = {c.get("country") for c in table.clubs.values()}
    check("committed table: country is US, a reviewed country, or not reviewed yet",
          countries <= {"US", "CA", "GB", None}, str(sorted(str(c) for c in countries)))
    outside = [c for c in table.clubs.values() if c.get("country") not in (None, "US")]
    check("committed table: clubs outside the US are marked", len(outside) >= 5, str(len(outside)))
    m = table.match("NDC-Ontario")
    check("outside the US: NDC-Ontario", m.status == "matched" and m.outside_us, f"{m.status} {m.country}")
    check("inside the US: Beach FC (CA)", not table.match("Beach FC (CA)").outside_us)
    # a club that was flagged for a person is not quietly merged into its neighbour
    check("flagged pairs stay separate: Beach FC (CA) / Beach FC",
          table.match("Beach FC (CA)").clubId != table.match("Beach FC").clubId)


def test_owner_decisions_233(table: clubs.Table) -> None:
    """Issue #233: the owner confirmed 8 alias links and merged 14 split groups. Each is checked
    by name, so a later edit that quietly splits or re-points one of them fails here."""
    merged = [("Arizona Arsenal", "AZ Arsenal"), ("Boise Timbers Thorns SC", "Boise Thorns"),
              ("Lou Fusz Athletic", "Lou Fusz"), ("North Carolina Fusion", "NC Fusion"),
              ("Ohio Elite Soccer Academy", "Ohio Elite"), ("Penn Fusion", "Penn Fusion SA"),
              ("Slammers FC", "Slammers FC HB Koge"), ("Slammers FC", "Slammers HB Køge"),
              ("So Cal Blues", "SoCal Blues"), ("SJEB FC", "SJEB Rush"), ("Austin Sting", "Sting Austin"),
              ("United Futbol Academy", "UFA"), ("Crossfire Premier SC", "Crossfire United"),
              ("Cincinnati United Premier", "Cincinnati United Soccer Club"), ("Eclipse Select (IL)", "Eclipse")]
    for canon, other in merged:
        a, b = table.match(canon), table.match(other)
        check(f"#233 merged: {other!r} -> {canon!r}", a.status == b.status == "matched" and a.clubId == b.clubId,
              f"{a.clubId} vs {b.clubId}")
        check(f"#233 merged: {canon!r} is the canonical name", a.name == canon, str(a.name))
        check(f"#233 merged: the owner is recorded on {canon!r}",
              table.clubs[a.clubId].get("reviewedBy", "").startswith("owner"), str(table.clubs[a.clubId].get("reviewedBy")))
    gone = ["az-arsenal", "boise-thorns", "lou-fusz", "nc-fusion", "ohio-elite", "penn-fusion-sa", "slammers-fc-hb-koge",
            "slammers-hb-koge", "socal-blues", "sjeb-rush", "sting-austin", "ufa", "crossfire-united",
            "cincinnati-united-soccer-club", "eclipse"]
    check("#233 merged: the absorbed rows are gone", not any(g in table.clubs for g in gone),
          str([g for g in gone if g in table.clubs]))
    confirmed = {"Albion MLS Next": "Albion SC", "Arlington SC": "Arlington Soccer", "Arlington ECNL": "Arlington Soccer",
                 "Galaxy": "Galaxy SC (IL)", "Legends": "Legends FC", "Legends SC": "Legends FC",
                 "Eagles Soccer Club": "Eagles SC (CA)", "McLean ECNL": "McLean FC", "RISE 05 GA": "Rise SC",
                 "Select Soccer Club": "Eclipse Select (IL)"}
    for raw, name in confirmed.items():
        m = table.match(raw)
        check(f"#233 confirmed: {raw!r} -> {name!r}", m.status == "matched" and m.name == name, f"{m.status} {m.name}")
    # the owner's addition: the players written exactly "Select SC" are Eclipse Select too, so
    # the Select SC row is folded in and its name becomes a reviewed alias
    for raw in ("Select SC", "Select Soccer Club"):
        m = table.match(raw)
        check(f"#233 folded: {raw!r} -> 'Eclipse Select (IL)'", m.status == "matched" and m.clubId == "eclipse-select-il",
              f"{m.status} {m.clubId}")
    check("#233 folded: the Select SC row is gone", "select-sc" not in table.clubs)
    with open(clubs.TABLE_PATH, encoding="utf-8") as f:
        entry = (json.load(f).get("aliases") or {}).get("select sc") or {}
    check("#233 folded: the owner is recorded on the 'select sc' alias",
          entry.get("club") == "eclipse-select-il" and str(entry.get("reviewedBy", "")).startswith("owner"), str(entry))
    # the near-miss guard: merging must not have emptied the pairs the vacuity check relies on
    both = [(a, b) for a, b in NEAR_MISSES if table.match(a).status == "matched" and table.match(b).status == "matched"]
    check("#233: the near-miss vacuity guard still has 5+ pairs after the merges", len(both) >= 5, str(len(both)))


def test_scratch_build_leaves_the_report_alone() -> None:
    """A test that builds into a temp directory must not rewrite data/clubs-review.json.

    The review report lives in data/, which is outside the output directories a scratch build
    swaps, so build() writes it only on a publishing run. tests/seasons_test.py and
    tests/profile_pruning_test.py both run build() into a temp directory."""
    import build  # imported here so the module-level capture happens before anything swaps it

    check("a real build writes the review report", build.publishing_run())
    before = common.PROGRAMS_OUT_DIR
    try:
        common.PROGRAMS_OUT_DIR = os.path.join(tempfile.gettempdir(), "collegedash-scratch-build")
        check("a scratch build does not write the review report", not build.publishing_run())
    finally:
        common.PROGRAMS_OUT_DIR = before
    check("the swap is undone", build.publishing_run())


def test_d2_d3_phase_2_315(table: clubs.Table) -> None:
    """Issue #315 phase 2 (option A): D2/D3 names seen 5+ times, prepared by rule, pending a Reviewer.
    Spellings of existing clubs point at them; new clubs take their spellings; the owner-list and
    unclear names stay unmatched until someone decides them."""
    to_existing = {"Sporting Iowa ECNL": "Sporting Iowa", "Dallas Texans ECNL": "Dallas Texans",
                   "Connecticut Football Club": "Connecticut FC", "PDA White ECNL": "PDA",
                   "Club: Baltimore Armour GA": "Baltimore Armour", "PA Classics Elite Blue": "PA Classics"}
    for raw, name in to_existing.items():
        m = table.match(raw)
        check(f"#315 alias: {raw!r} -> {name!r}", m.status == "matched" and m.name == name, f"{m.status} {m.name}")
    together = [("Wisconsin United FC", "Wisconsin United"), ("NJ Premier", "NJ Premier FC"),
                ("Albany Alleycats", "Albany Alleycats ECRL"), ("Skyline Elite", "Skyline Elite GA")]
    for a, b in together:
        ma, mb = table.match(a), table.match(b)
        check(f"#315 new club: {a!r} and {b!r} are one club", ma.status == mb.status == "matched"
              and ma.clubId == mb.clubId, f"{ma.clubId} vs {mb.clubId}")
    # kept apart by the rules: a longer name is its own club, never folded into its prefix
    check("#315 near-miss: Rush Wisconsin West stays apart from Rush Wisconsin",
          table.match("Rush Wisconsin West").clubId != table.match("Rush Wisconsin").clubId)
    check("#315: 'She/Her' is not a club", table.match("She/Her").status == "not-a-club", table.match("She/Her").status)
    # held: ambiguous (Huatuo R1/R3; Beach FC ECNL and Sting ECNL wait for the state split in #339)
    held = ["Beach FC ECNL", "Sting ECNL", "Back Mountain", "St. Croix", "ECNL Central Il Eclipse", "BC United",
            "AUFC Thorns", "Liverpool FC", "FSA FC", "Force FC", "Sparta FC", "CFC"]
    for raw in held:
        check(f"#315 held for a decision: {raw!r} stays unmatched", table.match(raw).status == "unmatched",
              f"{table.match(raw).status} {table.match(raw).name}")
    # Huatuo R2: four spellings of clubs already in the table are aliases, not new rows
    dup = {"Matchfit Academy": "Match Fit Academy FC", "Matchfit": "Match Fit Academy FC", "PAC NW ECNL": "Pacific NW",
           "Chicago Sockers": "Sockers FC", "WI United FC": "Wisconsin United FC"}
    for raw, name in dup.items():
        m = table.match(raw)
        check(f"#336 R2: {raw!r} -> existing {name!r}", m.status == "matched" and m.name == name, f"{m.status} {m.name}")
    for gone in ("matchfit-academy", "pac-nw-ecnl", "chicago-sockers", "wi-united-fc", "back-mountain", "st-croix",
                 "ecnl-central-il-eclipse", "bc-united", "aufc-thorns", "richmond-strikers", "santa-clara-sporting-ga"):
        check(f"#336: row {gone!r} is not in the table", gone not in table.clubs)
    # R4: league tag out of the display name, the tagged spelling still matches
    m = table.match("Santa Clara Sporting GA")
    check("#336 R4: 'Santa Clara Sporting GA' -> 'Santa Clara Sporting'", m.status == "matched"
          and m.name == "Santa Clara Sporting", f"{m.status} {m.name}")
    # promotions from Huatuo's section 3
    promoted = {"RUSA FC": "RUSA FC", "FC Frederick": "FC Frederick", "Club: FC Frederick": "FC Frederick",
                "BoReal FC": "BoReal FC", "TempesT FC": "TempesT FC", "Firebirds SC": "Firebirds SC",
                "Broomfield SC": "Broomfield SC"}
    for raw, name in promoted.items():
        m = table.match(raw)
        check(f"#336 promoted: {raw!r} -> {name!r}", m.status == "matched" and m.name == name, f"{m.status} {m.name}")
    # the owner's decisions
    owner = {"PDA Shore": "pda", "PDA SCP": "pda", "PDA North": "pda", "PDA South": "pda", "PDA South ECNL": "pda",
             "Cedar Stars": "cedar-stars-academy", "Cedar Stars GA": "cedar-stars-academy",
             "Hex/Keystone FC": "hex-fc", "Beach Futbol Club (CA)": "beach-fc-ca", "Beach FC (CA)": "beach-fc-ca",
             "Richmond Strikers": "richmond-united", "Richmond United": "richmond-united"}
    for raw, cid in owner.items():
        m = table.match(raw)
        check(f"#336 owner: {raw!r} -> {cid!r}", m.status == "matched" and m.clubId == cid, f"{m.status} {m.clubId}")
    check("#336 owner: 'Richmond Strikers' is Richmond United's former name, not an alias",
          "Richmond Strikers" in (table.clubs["richmond-united"].get("formerNames") or []))
    check("#336 owner: rows pda-south and beach-futbol-club-ca are merged away",
          "pda-south" not in table.clubs and "beach-futbol-club-ca" not in table.clubs)
    check("#336 owner: Beach FC (VA) is untouched and still its own club",
          table.match("Beach FC (VA)").clubId not in (None, "beach-fc-ca"), str(table.match("Beach FC (VA)").clubId))
    with open(clubs.TABLE_PATH, encoding="utf-8") as f:
        doc = json.load(f)
    # reversible merges: every key that came from a removed row names that row
    for key, src in (("pda south", "pda-south"), ("pda south ecnl", "pda-south"),
                     ("beach futbol club ca", "beach-futbol-club-ca")):
        basis = (doc["aliases"].get(key) or {}).get("basis", "")
        check(f"#336 provenance: alias {key!r} records the removed row {src!r}",
              f"merged row {src} " in basis and "owner decision #336" in basis, basis)
    rows = [c for c in doc["clubs"] if c.get("prepared") == "2026-09-24"]
    check("#315: 59 rows were added under phase 2 (53 confirmed + 6 promoted)", len(rows) == 59, str(len(rows)))
    check("#336 R6: every phase 2 row carries Huatuo's review",
          all(c.get("reviewed") == "2026-09-24" and c.get("reviewedBy", "").startswith("Huatuo") for c in rows),
          str([c["id"] for c in rows if not c.get("reviewedBy", "").startswith("Huatuo")][:5]))


def test_suggest_folds_385(table: clubs.Table) -> None:
    """Issue #385: every unmatched spelling whose suggest_key points at exactly ONE existing club is an alias of
    it, with provenance; a short name that also sits in other clubs' names, a same-name/state-split key and the
    names the #336 group check held stay unmatched."""
    m = table.match("MVLA ECNL")
    check("#385: 'MVLA ECNL' -> Mountain View Los Altos SC", m.status == "matched" and m.clubId == "mountain-view-los-altos-sc",
          f"{m.status} {m.clubId}")
    for raw, name in (("Skyline Elite SC", "Skyline Elite"), ("Albion Hurricanes 05 ECNL", "Albion Hurricanes FC (TX)"),
                      ("Pipeline ECRL", "Pipeline SC (MD)")):
        mm = table.match(raw)
        check(f"#385: {raw!r} -> {name!r}", mm.status == "matched" and mm.name == name, f"{mm.status} {mm.name}")
    for raw in ("Sting ECNL", "Sting Black RL", "Albion FC", "Arlington", "Rise Soccer Club", "Beach FC ECNL", "United FC"):
        check(f"#385: ambiguous {raw!r} stays unmatched", table.match(raw).status == "unmatched", table.match(raw).clubId)
    # Huatuo on PR #386: a spelling naming another state IN WORDS is held too; his promotions are exact name + tag
    check("#385: 'Scorpions FC New Hampshire' stays unmatched (names a state the club is not recorded in)",
          table.match("Scorpions FC New Hampshire").status == "unmatched", table.match("Scorpions FC New Hampshire").clubId)
    for raw, name in (("FC Wisconsin ECNL-RL", "FC Wisconsin"), ("Concorde Fire Soccer Club", "Concorde Fire"),
                      ("FC Stars RL ECNL", "FC Stars"), ("Club: FC Virginia GA", "FC Virginia"),
                      ("New York Soccer Club GA", "New York SC"), ("FC Dallas 01 DPL", "FC Dallas"),
                      ("Heat FC 02 ECNL", "Heat FC"), ("Long Island SC GA", "Long Island SC")):
        mm = table.match(raw)
        check(f"#385 promoted: {raw!r} -> {name!r}", mm.status == "matched" and mm.name == name, f"{mm.status} {mm.name}")
    for raw in ("Long Island GA", "Crossfire ECNL", "Nationals FC", "Portland Thorns ECNL"):
        check(f"#385: still held {raw!r}", table.match(raw).status == "unmatched", table.match(raw).clubId)
    with open(clubs.TABLE_PATH, encoding="utf-8") as f:
        doc = json.load(f)
    mine = {k: a for k, a in doc["aliases"].items() if isinstance(a, dict) and "issue #385" in a.get("basis", "")}
    check("#385: 163 folds and 12 promotions, each naming its club and the rule it came from",
          len(mine) == 175 and all(a.get("prepared") and a["basis"].startswith("issue #385: ") for a in mine.values()),
          str(len(mine)))
    # the state guard, as a property of the table: no #385 alias names a US state in words that its club's own name
    # and recorded state do not carry ('scorpions fc new hampshire' -> Scorpions SC was one)
    stray = []
    for k, a in mine.items():
        club = table.clubs[a["club"]]
        own = f" {clubs.clean_key(club['name'])} "
        for word, code in US_STATE_NAMES.items():
            if f" {word} " in f" {k} " and f" {word} " not in own and code != club.get("state") \
                    and not (word == "virginia" and " west virginia " in f" {k} "):
                stray.append(f"{k} -> {club['name']} ({word})")
    check("#385: no alias names a state (in words) its club does not carry", not stray, str(stray[:5]))


US_STATE_NAMES = {"alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
                  "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
                  "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
                  "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
                  "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
                  "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
                  "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
                  "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
                  "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
                  "wisconsin": "WI", "wyoming": "WY"}


def main() -> int:
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    VERBOSE = args.verbose

    table = clubs.load_table(reload=True)
    test_cleanup()
    test_near_misses(table)
    test_mvla(table)
    test_unmatched(table)
    test_not_a_club(table)
    test_table_validation()
    test_precedence(table)
    test_suggestions_are_only_suggestions(table)
    test_committed_table(table)
    test_owner_decisions_233(table)
    test_d2_d3_phase_2_315(table)
    test_suggest_folds_385(table)
    test_scratch_build_leaves_the_report_alone()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
