"""Same-name clubs resolved by the player's state (issue #339).

    python tests/clubs_state_split_test.py            # unit checks on made-up tables + the data check
    python tests/clubs_state_split_test.py --verbose

The rule, stated honestly: the state is the player's HOMETOWN state, used only when a school of that
name exists in NCES in that state (schools.club_state). It is a conservative filter on the hometown,
never an independent high-school state: a player whose school is unmatched, ambiguous, missing or
outside the US gets no state, whatever the hometown says, and a state-split key stays unmatched.

The table entry is {"byState": {"VA": "beach-fc-va", "CA": "beach-fc-ca"}}; every other key matches
exactly as before. The data check at the end reads the committed sources: every club resolved by
state must carry the same state as that player's NCES-matched school (it fails if the state were
taken from the hometown alone, because Beach FC ECNL rows with an unmatched school would resolve).
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import build  # noqa: E402
import clubs  # noqa: E402
import schools  # noqa: E402
import trends  # noqa: E402
from collect import common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:400]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


# ---- made-up table and schools --------------------------------------------------------------------

def doc(**extra_aliases):
    return {"clubs": [{"id": "shore-fc-va", "name": "Shore FC (VA)", "state": "VA"},
                      {"id": "shore-fc-ca", "name": "Shore FC (CA)", "state": "CA"},
                      {"id": "harbor-sc", "name": "Harbor SC", "state": None, "formerNames": ["Old Harbor"]}],
            "aliases": {"shore fc ecnl": {"byState": {"VA": "shore-fc-va", "CA": "shore-fc-ca"}},
                        "harbor ecnl": {"club": "harbor-sc"}, **extra_aliases},
            "notAClub": {"n a": "placeholder"}}


T = clubs.Table(doc())
VA = {"state": "VA", "school": "matched"}
CA = {"state": "CA", "school": "matched"}
NY = {"state": "NY", "school": "matched"}


class _SM:
    def __init__(self, status, state):
        self.status, self.state = status, state

    def as_dict(self):
        return {"status": self.status, "state": self.state, "schoolId": None}


class StubSchools:
    """schools.Table stand-in: {highSchool: (status, hometown-derived state)}."""

    def __init__(self, rows):
        self.rows = rows

    def match(self, high_school, hometown):
        status, state = self.rows.get(high_school, ("none", None))
        return _SM(status, state)


SCH = StubSchools({"Va School": ("matched", "VA"), "Ca School": ("matched", "CA"),
                   "Unknown Academy": ("unmatched", "VA"), "Twin HS": ("ambiguous", "VA"),
                   "Ny School": ("matched", "NY")})


def test_match_by_state():
    m = T.match("Shore FC ECNL", VA)
    ok("VA: the split key resolves to the VA club", (m.status, m.clubId) == ("matched", "shore-fc-va"), m.clubId)
    d = m.as_dict()
    ok("VA: clubInfo says how", d.get("via") == "high-school state" and d.get("hsState") == "VA", d)
    ok("CA: the split key resolves to the CA club", T.match("Shore FC ECNL", CA).clubId == "shore-fc-ca")
    none = T.match("Shore FC ECNL", {"state": None, "school": "ambiguous"}).as_dict()
    ok("no state: unmatched, with the reason and the school status",
       none["status"] == "unmatched" and none.get("stateSplit") == {"reason": "no high-school state",
                                                                   "school": "ambiguous", "states": ["CA", "VA"]}, none)
    other = T.match("Shore FC ECNL", NY).as_dict()
    ok("other state: unmatched, 'state matches neither club'",
       other["status"] == "unmatched" and other["stateSplit"]["reason"] == "state matches neither club", other)
    ok("a recruit (no school state at all) stays unmatched", T.match("Shore FC ECNL", None).status == "unmatched")
    plain = T.match("Harbor ECNL", VA).as_dict()
    ok("a plain key ignores the state and matches exactly as before",
       plain["clubId"] == "harbor-sc" and "via" not in plain and "stateSplit" not in plain, plain)
    ok("a plain key's clubInfo is byte-identical with or without a state",
       T.match("Harbor ECNL", VA).as_dict() == T.match("Harbor ECNL").as_dict())


def test_club_state_uses_only_a_matched_school():
    ok("matched school -> its state", schools.club_state(SCH, "Va School", "Town, VA") == VA)
    for hs, status in (("Unknown Academy", "unmatched"), ("Twin HS", "ambiguous"), ("", "none")):
        got = schools.club_state(SCH, hs, "Town, VA")
        ok(f"{status} school with a VA hometown -> no state", got == {"state": None, "school": status}, got)


def test_resolve_groups_by_the_players_state():
    rows = [{"raw": "Shore FC ECNL", "source": "roster page", "updated": "2026-08-01"},
            {"raw": "Shore FC (VA)", "source": "TopDrawerSoccer", "updated": "2025-06-01"}]
    va = clubs.resolve(rows, T, VA)
    ok("VA player: 'Shore FC ECNL' + 'Shore FC (VA)' agree - no conflict", "conflict" not in va, va)
    info = {}
    rec = {}
    clubs.annotate(rec, rows, T, VA)
    info = rec["clubInfo"]
    ok("VA player: annotated to the VA club", info["clubId"] == "shore-fc-va" and "conflict" not in info, info)
    ca = clubs.resolve(rows, T, CA)
    ok("CA player: the same pair is a real conflict", bool(ca.get("conflict")), ca)
    rec2 = {}
    clubs.annotate(rec2, rows, T, CA)
    ok("CA player: most recent wins, as today (roster page, CA club)", rec2["clubInfo"]["clubId"] == "shore-fc-ca",
       rec2["clubInfo"])


def test_table_validation():
    bad = {
        "club and byState together": {"x fc": {"club": "harbor-sc", "byState": {"VA": "shore-fc-va", "CA": "shore-fc-ca"}}},
        "one state only": {"x fc": {"byState": {"VA": "shore-fc-va"}}},
        "unknown club": {"x fc": {"byState": {"VA": "shore-fc-va", "CA": "nope"}}},
        "not a state code": {"x fc": {"byState": {"Virginia": "shore-fc-va", "CA": "shore-fc-ca"}}},
        "club listed under another state": {"x fc": {"byState": {"CA": "shore-fc-va", "VA": "shore-fc-ca"}}},
        "not a cleaned key": {"X FC": {"byState": {"VA": "shore-fc-va", "CA": "shore-fc-ca"}}},
        "equal to a club name": {"harbor sc": {"byState": {"VA": "shore-fc-va", "CA": "shore-fc-ca"}}},
        # (a JSON object can't hold the same key as a plain alias too; a former name is the other collision)
        "equal to a former name": {"old harbor": {"byState": {"VA": "shore-fc-va", "CA": "shore-fc-ca"}}},
        "in notAClub": {"n a": {"byState": {"VA": "shore-fc-va", "CA": "shore-fc-ca"}}},
    }
    for label, alias in bad.items():
        d = doc()
        d["aliases"].update(alias)
        try:
            clubs.Table(d)
            ok(f"validation: {label} is refused", False)
        except clubs.TableError:
            ok(f"validation: {label} is refused", True)


def test_build_and_review_report():
    roster = {"season": 2026, "players": [
        {"name": "Player One", "highSchool": "Va School", "hometown": "Town, VA"},
        {"name": "Player Two", "highSchool": "Unknown Academy", "hometown": "Town, VA"},
        {"name": "Player Three", "highSchool": "Ca School", "hometown": "City, CA"}]}
    ath = {"data": {"roster": {"players": [dict(p, club="Shore FC ECNL") for p in roster["players"]]},
                    "rosterHistory": {"2025": [{"name": "Player Four", "highSchool": "Ny School",
                                                "hometown": "Town, NY", "club": "Shore FC ECNL"}]}}}
    build.annotate_roster_clubs(roster, ath, None, None, T, SCH)
    got = [q["clubInfo"]["clubId"] or q["clubInfo"]["status"] for q in roster["players"]]
    ok("build: VA -> VA club, unmatched school -> unmatched, CA -> CA club (the state reaches clubs)",
       got == ["shore-fc-va", "unmatched", "shore-fc-ca"], got)
    ok("build: no schoolInfo is written by the club step (profile key order unchanged)",
       not any("schoolInfo" in q for q in roster["players"]))
    rec = clubs.Recorder(T)
    build.observe_clubs(rec, ath, None, None, slug="example-u", division="D3", school_table=SCH)
    row = rec.rows.get("shore fc ecnl") or {}
    ok("review report: 2 of 4 rows count as matched", rec.matched_occurrences == 2, rec.matched_occurrences)
    ok("review report: the unresolved rows are listed by reason and school status",
       row.get("stateSplit") == {"no high-school state (school: unmatched)": 1,
                                 "state matches neither club (school: matched)": 1}, row.get("stateSplit"))
    rep = rec.report(None, today="2026-09-24")
    ok("review report: the stateSplit counts are written into the row", rep["unmatched"][0].get("stateSplit") ==
       row.get("stateSplit"), rep["unmatched"][0])


def test_trends_past_and_search():
    r = trends.Recorder(T, candidates=lambda tds, sw: {}, same_person=None, school_table=SCH)
    profile = {"slug": "example-u", "division": "D3", "roster": {"season": 2026, "players": []},
               "rosterHistory": {"2025": {"players": [{"name": "Past VA", "highSchool": "Va School", "hometown": "Town, VA"},
                                                      {"name": "Past None", "highSchool": "Twin HS", "hometown": "Town, VA"}]}},
               "commitments": []}
    ath = {"data": {"rosterHistory": {"2025": [{"name": "Past VA", "club": "Shore FC ECNL"},
                                               {"name": "Past None", "club": "Shore FC ECNL"}]}}}
    r.observe(profile, {"division": "D3"}, ath=ath, tds={}, sw={})
    # records format (#327): one (slug, status, club id, school id) per counted person; status 1 = former player
    past = sorted(c for slug, s, c, _h in r.records if slug == "example-u" and s == 1)
    ok("trends: the VA past player counts under the VA club, the unresolved one under raw:shore fc ecnl",
       past == ["raw:shore fc ecnl", "shore-fc-va"], past)
    for cid in ("shore-fc-va", "shore-fc-ca"):
        aka = trends.search_aliases(T, cid, T.clubs[cid]["name"])
        ok(f"search: 'shore fc ecnl' is searchable under {cid}", "shore fc ecnl" in aka, aka)


def test_retired_ids():
    # part C: a merged-away id points at a live row; never a live row itself, never at a missing one
    d = doc()
    d["retired"] = {"old-shore": "shore-fc-va"}
    ok("retired: a merged-away id resolves to its live club", clubs.Table(d).retired == {"old-shore": "shore-fc-va"})
    for label, retired in (("a retired id that is still a row", {"harbor-sc": "shore-fc-va"}),
                           ("a retired id pointing at a missing row", {"old-shore": "nope"}),
                           ("a chain (target is itself retired)", {"a-old": "b-old", "b-old": "shore-fc-va"})):
        d = doc()
        d["retired"] = retired
        try:
            clubs.Table(d)
            ok(f"retired: {label} is refused", False)
        except clubs.TableError:
            ok(f"retired: {label} is refused", True)
    t = clubs.load_table(reload=True)
    ok("committed table: pda-south and beach-futbol-club-ca are retired into pda / beach-fc-ca",
       t.retired == {"pda-south": "pda", "beach-futbol-club-ca": "beach-fc-ca"}, t.retired)
    r = trends.Recorder(t, candidates=lambda tds, sw: {}, school_table=SCH)
    ok("trends index carries retiredClubs", r.index().get("retiredClubs") == t.retired)


def test_committed_table():
    t = clubs.load_table(reload=True)
    ok("committed table: 'beach fc ecnl' splits VA/CA",
       t.split.get("beach fc ecnl") == {"VA": "beach-fc-va", "CA": "beach-fc-ca"}, t.split)
    ok("committed table: Sting ECNL stays unmatched (both candidate clubs are Texas)",
       t.match("Sting ECNL", {"state": "TX", "school": "matched"}).status == "unmatched")
    ok("committed table: bare 'Beach FC' stays on the beach-fc row, whatever the state",
       t.match("Beach FC", VA).clubId == "beach-fc" and t.match("Beach FC").clubId == "beach-fc")


def test_data_every_state_resolved_club_agrees_with_the_matched_school():
    """Huatuo's condition 3, over committed sources: every row resolved by state carries the state of
    the player's NCES-matched school (checked with the school table directly, not through
    schools.club_state), and at least one row resolves. Fails if the state came from the hometown."""
    t, st = clubs.load_table(reload=True), schools.load_table()
    resolved = bad = 0
    for program in common.iter_programs(common.load_registry()):
        ath = common.load_source(program["slug"], "athletics")
        data = (ath or {}).get("data") or {}
        seasons = [(data.get("roster") or {}).get("players") or []] + list((data.get("rosterHistory") or {}).values())
        if not any(clubs.clean_key(p.get("club")) in t.split for pl in seasons for p in pl or []):
            continue
        for pl in seasons:
            for p in pl or []:
                if clubs.clean_key(p.get("club")) not in t.split:
                    continue
                info = t.match(p["club"], schools.club_state(st, p.get("highSchool"), p.get("hometown"))).as_dict()
                if info.get("via") != "high-school state":
                    continue
                resolved += 1
                m = st.match(p.get("highSchool"), p.get("hometown"))
                if not (m.status == "matched" and m.state == info["hsState"] == t.clubs[info["clubId"]]["state"]):
                    bad += 1
    ok("data: some rows resolve by state", resolved > 0, resolved)
    ok("data: every state-resolved club's state is the player's matched school state", bad == 0, f"{bad} of {resolved}")


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_match_by_state, test_club_state_uses_only_a_matched_school, test_resolve_groups_by_the_players_state,
                 test_table_validation, test_build_and_review_report, test_trends_past_and_search, test_retired_ids,
                 test_committed_table,
                 test_data_every_state_resolved_club_agrees_with_the_matched_school):
        try:
            case()
        except Exception as e:  # noqa: BLE001 - a crash is that case failing
            ok(f"{case.__name__} ran", False, repr(e))
    print(f"{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
