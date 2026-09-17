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
    test_scratch_build_leaves_the_report_alone()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
