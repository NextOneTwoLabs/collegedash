"""Checks for trends.py, the clubs & high-schools index behind #/trends (issue #230).

    python tests/trends_test.py            # everything below, offline
    python tests/trends_test.py --verbose  # print every check, not only the failures

Offline and in memory: a small fixture of profiles, stored sources and a club table shaped like the
real ones. The one file written goes to a temp directory. Nothing under public/ or data/ is read
or touched except `data/clubs.json`'s loader being bypassed by a fixture table, and read once by
test_search_aka to check the aliases MVLA's search needs (#307).

What this proves
----------------
* The three counts are what the owner asked for on #225: current roster, former players (on a
  stored past roster and not on the current one, counted once however many seasons list them),
  and verbal/signed commits - and commits never enter a program's total or its order.
* The counts equal a direct computation written here, independently of the recorder.
* A past player's club comes from the recruiting records and the past roster page's Club column,
  resolved by the same most-recent-source rule as a current player's.
* Unmatched spellings are counted in the open; placeholders and empty clubs are not counted.
* D1, D2 and D3 profiles are all counted (#315); a program with nothing known is still in `programs`.
  `divisions` replaces the v1 field `"division": "D1"`.
* D2/D3 commits are "not collected" (#315, C1): null, never 0, in the program row, in every club and school
  cell, in the totals and in the coverage - even for a D2 program that holds a verbal commit.
* Coverage is per division (#315, C2): a D2-only result states the D2 rate, never the merged one.
* The published index stays under a 450 KB gzip budget (#315): growth is a decision, not a surprise.
* `schoolInfo` (issue #229): absent in the build -> `schools` is null and the coverage says "not
  available", never 0; present -> matched schools are counted, ambiguous and unmatched are not;
  commits carry no school today, so their school count is null.
* The written file is compact, carries no person's name, and lands beside the programs directory
  - a temp directory when a scratch build swaps `PROGRAMS_OUT_DIR`, never public/.
* `programs_for`, `feeders_for`, `coverage_lines` and `answer` (the #165 hook) are pure functions of
  the index with the documented shape.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import clubs  # noqa: E402
import trends  # noqa: E402
from collect import common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail="") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


# ---------- fixture ----------

TABLE = clubs.Table({"clubs": [{"id": "x-sc", "name": "X SC", "state": "CA"},
                               {"id": "y-club", "name": "Y Club", "state": None}],
                     "aliases": {}, "notAClub": {}})

def ci(raw, club_id=None, status="matched", source="TopDrawerSoccer"):
    m = TABLE.match(raw)
    d = m.as_dict(source, "2025-01-01")
    d["status"] = status
    if club_id is not None:
        d["clubId"] = club_id
    return d

CI_X = ci("X SC")
CI_Y = ci("Y Club")
CI_UNMATCHED = ci("Zeta United", status="unmatched")   # key "zeta united", no id
CI_NOT_A_CLUB = {"raw": "N/A", "key": "n a", "clubId": None, "club": None, "status": "not-a-club"}


def player(name, club_info=None, *, school=None, hs="", hometown=""):
    q = {"number": "", "name": name, "pos": "F", "classCode": "SO", "hometown": hometown, "highSchool": hs,
         "club": (club_info or {}).get("raw") or "", "clubSource": (club_info or {}).get("source"), "clubInfo": club_info}
    if school is not None:
        q["schoolInfo"] = school
    return q


def commit(name, club_info, status="verbal", hs=""):
    return {"name": name, "gradYear": 2027, "status": status, "club": (club_info or {}).get("raw") or "",
            "clubInfo": club_info, "highSchool": hs}


SCHOOL_OK = {"raw": "Rocklin HS", "key": "rocklin", "schoolId": "ccd:1", "state": "CA", "status": "matched",
             "school": "Rocklin High", "city": "Rocklin", "type": "public"}
SCHOOL_AMBIG = {"raw": "San Marcos", "key": "san marcos", "schoolId": None, "state": "CA", "status": "ambiguous", "candidates": 2}


def profile_alpha(with_schools=False):
    """Six current players (2 X, 1 Y, 1 unmatched, 1 placeholder, 1 none); three past rows across two
    seasons, one of them still on the current roster; five commitments of which three count."""
    players = [player("Ada Current", CI_X, school=SCHOOL_OK if with_schools else None, hs="Rocklin HS"),
               player("Bel Current", CI_X, school=SCHOOL_AMBIG if with_schools else None, hs="San Marcos"),
               player("Cy Current", CI_Y),
               player("Di Current", CI_UNMATCHED),
               player("Ed Current", CI_NOT_A_CLUB),
               player("Flo Current", None, school=None if with_schools else None)]
    if with_schools:
        players[2]["schoolInfo"] = None  # the field exists, the player has no high school
    hist = {"2025": {"count": 2, "departed": ["ann former"],
                     "players": [{"name": "Ann Former", "pos": "D", "classCode": "SR", "hometown": "Davis, Calif.", "highSchool": "Davis HS"},
                                 {"name": "Cy Current", "pos": "F", "classCode": "FR", "hometown": "", "highSchool": ""}]},
            "2024": {"count": 2, "departed": None,
                     "players": [{"name": "Ann Former", "pos": "D", "classCode": "JR", "hometown": "Davis, Calif.", "highSchool": "Davis HS"},
                                 {"name": "Bea Former", "pos": "M", "classCode": "SR", "hometown": "Reno, Nev.", "highSchool": "Reno HS"}]}}
    commits = [commit("R One", CI_X), commit("R Two", CI_X), commit("R Three", CI_X, status="enrolled"),
               commit("R Four", CI_Y, status="decommitted"), commit("R Five", None, hs="Some HS")]
    return {"slug": "alpha", "name": "Alpha University", "division": "D1",
            "roster": {"season": 2026, "count": len(players), "players": players},
            "rosterHistory": hist, "commitments": commits}


ATH_ALPHA = {"data": {"rosterHistory": {"2025": [{"name": "Ann Former", "club": "X SC"}, {"name": "Cy Current", "club": ""}],
                                        "2024": [{"name": "Ann Former", "club": "X SC"}, {"name": "Bea Former"}]}}}
# Bea Former has no roster Club column but a SoccerWire alumni record; Cy Current is on the roster, so her past rows never count.
CANDIDATES = {"bea former": [{"raw": "Y Club", "source": "SoccerWire", "updated": "2024-05-01"}]}


def profile_beta():
    """One current player from Y; no history; five commits from X - a commit-heavy program."""
    return {"slug": "beta", "name": "Beta College", "division": "D1",
            "roster": {"season": 2026, "count": 1, "players": [player("Gil Current", CI_Y)]},
            "rosterHistory": {},
            "commitments": [commit(f"R {i}", CI_X) for i in range(5)]}


def profile_gamma_d2():
    return {"slug": "gamma", "name": "Gamma State", "division": "D2",
            "roster": {"season": 2026, "count": 1, "players": [player("Hal Current", CI_X)]},
            "rosterHistory": {}, "commitments": [commit("R Z", CI_X)]}


def profile_delta_empty():
    return {"slug": "delta", "name": "Delta", "division": "D1", "roster": {"season": 2026, "count": 1, "players": [player("Ivy Current", None)]},
            "rosterHistory": {}, "commitments": []}


class NoSchools:
    """A school table that matches nothing. Passed whenever a case does not inject its own, so the
    recorder never falls back to the real `schools` module (present since #236) and the fixture's
    expectations do not depend on data/schools.json."""
    class _M:
        status = "none"
        def as_dict(self):
            return None
    def match(self, hs, hometown):
        return self._M()


def record(with_schools=False, school_table=None) -> trends.Recorder:
    rec = trends.Recorder(TABLE, candidates=lambda tds, sw: CANDIDATES, same_person=lambda a, b: False,
                          school_table=school_table or NoSchools())
    rec.observe(profile_alpha(with_schools), {"slug": "alpha", "division": "D1"}, ath=ATH_ALPHA, tds={}, sw={})
    rec.observe(profile_beta(), {"slug": "beta", "division": "D1"}, ath={}, tds={}, sw={})
    rec.observe(profile_gamma_d2(), {"slug": "gamma", "division": "D2"}, ath={}, tds={}, sw={})
    rec.observe(profile_delta_empty(), {"slug": "delta", "division": "D1"}, ath={}, tds={}, sw={})
    return rec


# ---------- the direct computation the index must equal ----------

def direct_counts(profiles_and_sources) -> dict[str, dict[str, list[int]]]:
    """club entry id -> slug -> [current, past, commits], written as plainly as possible and without
    the recorder: the same definitions, a different route."""
    out: dict[str, dict[str, list[int]]] = {}

    def add(eid, slug, col, d1=True):
        out.setdefault(eid, {}).setdefault(slug, [0, 0, 0 if d1 else None])[col] += 1

    def entry_of(info):
        if not info or info.get("status") not in ("matched", "unmatched"):
            return None
        return info["clubId"] if info.get("status") == "matched" else "raw:" + info["key"]

    for prof, ath, cands in profiles_and_sources:
        d1 = prof["division"] == "D1"
        slug = prof["slug"]
        cur = {common.norm_name(q["name"]) for q in prof["roster"]["players"]}
        for q in prof["roster"]["players"]:
            e = entry_of(q.get("clubInfo"))
            if e:
                add(e, slug, 0, d1)
        seen = set()
        for y in sorted(prof["rosterHistory"], reverse=True):
            col = {common.norm_name(r["name"]): r.get("club") or "" for r in (ath.get("data") or {}).get("rosterHistory", {}).get(y, [])}
            for q in prof["rosterHistory"][y]["players"]:
                n = common.norm_name(q["name"])
                if n in cur or n in seen:
                    continue
                seen.add(n)
                rows = list(cands.get(n, []))
                if col.get(n):
                    rows.append({"raw": col[n], "source": "roster page", "updated": f"{y}-08-01"})
                chosen = clubs.resolve(rows, TABLE) if rows else None
                e = entry_of(TABLE.match(chosen["raw"]).as_dict()) if chosen else None
                if e:
                    add(e, slug, 1, d1)
        for c in prof["commitments"]:
            if d1 and c["status"] in ("verbal", "signed"):
                e = entry_of(c.get("clubInfo"))
                if e:
                    add(e, slug, 2)
    return out


# ---------- checks ----------

def test_counts_equal_a_direct_computation() -> None:
    doc = record().index()
    direct = direct_counts([(profile_alpha(), ATH_ALPHA, CANDIDATES), (profile_beta(), {}, {}),
                            (profile_gamma_d2(), {}, {}), (profile_delta_empty(), {}, {})])
    got = {eid: e["programs"] for eid, e in doc["clubs"].items()}
    ok("every club entry's per-program cells equal the direct computation", got == direct, (got, direct))
    ok("X SC at alpha: 2 current, 1 former (Ann, via the past roster's Club column), 2 verbal commits",
       doc["clubs"]["x-sc"]["programs"]["alpha"] == [2, 1, 2], doc["clubs"]["x-sc"]["programs"].get("alpha"))
    ok("Y Club at alpha: 1 current, 1 former (Bea, via a SoccerWire alumni record), 0 commits",
       doc["clubs"]["y-club"]["programs"]["alpha"] == [1, 1, 0], doc["clubs"]["y-club"]["programs"].get("alpha"))
    ok("an unmatched spelling is its own entry, flagged, counted in the open",
       doc["clubs"].get("raw:zeta united", {}).get("programs", {}).get("alpha") == [1, 0, 0]
       and doc["clubs"]["raw:zeta united"]["unmatched"] is True and doc["clubs"]["raw:zeta united"]["name"] == "Zeta United")
    ok("a placeholder ('N/A') and a player with no club are not entries", not any(k.startswith("raw:n a") for k in doc["clubs"]))
    ok("the reviewed club's name and state come from the table", doc["clubs"]["x-sc"]["name"] == "X SC" and doc["clubs"]["x-sc"]["state"] == "CA")
    ok("a former player listed in two stored seasons counts once", doc["programs"]["alpha"]["past"] == 2)
    ok("a current player's past rows never count as former", doc["clubs"]["y-club"]["programs"]["alpha"][1] == 1)
    ok("the enrolled and the decommitted recruits are not commits", doc["programs"]["alpha"]["commits"] == 3)
    ok("program row alpha: current 6, past 2, commits 3, club known [4, 2, 2]",
       doc["programs"]["alpha"] == {"division": "D1", "current": 6, "past": 2, "commits": 3, "clubKnown": [4, 2, 2], "schoolKnown": [0, 0, 0]}, doc["programs"]["alpha"])
    ok("a D1 program with nothing known is still a row", doc["programs"]["delta"] == {"division": "D1", "current": 1, "past": 0, "commits": 0, "clubKnown": [0, 0, 0], "schoolKnown": [0, 0, 0]})
    # #315: D2 is counted. Fails if the D1 gate in observe() comes back (gamma absent).
    ok("the D2 program is a row, its commits null although it holds a verbal commit (C1)",
       doc["programs"].get("gamma") == {"division": "D2", "current": 1, "past": 0, "commits": None, "clubKnown": [1, 0, None], "schoolKnown": [0, 0, None]},
       doc["programs"].get("gamma"))
    ok("the D2 program's club cell reads null commits, never 0 and never the verbal commit's 1",
       doc["clubs"]["x-sc"]["programs"].get("gamma") == [1, 0, None], doc["clubs"]["x-sc"]["programs"].get("gamma"))
    # #315, C3: `divisions` replaces the v1 field `"division": "D1"`.
    with_d3 = record()
    with_d3.observe({**profile_gamma_d2(), "slug": "epsilon", "division": "D3"}, {"slug": "epsilon", "division": "D3"}, ath={}, tds={}, sw={})
    d3 = with_d3.index()
    ok("a D3 profile is counted, commits null", d3["programs"].get("epsilon", {}).get("commits", 0) is None
       and d3["clubs"]["x-sc"]["programs"].get("epsilon") == [1, 0, None], d3["programs"].get("epsilon"))
    ok("the v1 field `division` is replaced by `divisions`, the divisions the index holds, sorted",
       "division" not in d3 and d3["divisions"] == ["D1", "D2", "D3"] and doc["divisions"] == ["D1", "D2"], (d3.get("divisions"), d3.get("division")))
    ok("`commitDivisions` names the divisions whose commits are collected", d3["commitDivisions"] == ["D1"])
    ok("a program of an unknown division is left out", (lambda r: (r.observe({**profile_gamma_d2(), "slug": "zeta"}, {"slug": "zeta", "division": "NAIA"}, ath={}, tds={}, sw={}), r.index())[1])(record())["programs"].get("zeta") is None)
    cov = doc["coverage"]
    ok("coverage current, all divisions: 9 players (6 alpha, 1 beta, 1 delta, 1 gamma), 6 known",
       {k: cov["current"][k] for k in ("players", "clubKnown")} == {"players": 9, "clubKnown": 6}, cov["current"])
    by = cov["byDivision"]
    ok("coverage by division (C2): D1 8 players, 5 known; D2 1 player, 1 known",
       by["D1"]["current"] == {"players": 8, "clubKnown": 5, "schoolNamed": 2, "schoolKnown": None}
       and by["D2"]["current"] == {"players": 1, "clubKnown": 1, "schoolNamed": 0, "schoolKnown": None}, by)
    ok("D2 commit coverage is null, and the D2 verbal commit is not in the commit coverage (C1)",
       by["D2"]["commits"] is None and by["D1"]["commits"]["recruits"] == 8 and cov["commits"]["recruits"] == 8, (by["D2"]["commits"], cov["commits"]))
    ok("coverage past: 2 former players, both known", cov["past"]["players"] == 2 and cov["past"]["clubKnown"] == 2)
    ok("coverage commits: 8 verbal, 7 known", cov["commits"]["recruits"] == 8 and cov["commits"]["clubKnown"] == 7, cov["commits"])
    ok("season and past seasons come from the data", doc["season"] == 2026 and doc["pastSeasons"] == [2024, 2025])
    ok("the index states which statuses count as commits", doc["commitStatuses"] == ["verbal", "signed"])


def test_commits_never_enter_a_total() -> None:
    doc = record().index()
    rows = trends.programs_for(doc, "club", "x-sc")
    rows = trends.programs_for(doc, "club", "x-sc")
    ok("programs_for lists alpha, gamma (1 player, commits null), then beta (0 players, 5 commits)",
       [r["slug"] for r in rows] == ["alpha", "gamma", "beta"], rows)
    ok("each row carries the three counts separately", rows[2] == {"slug": "beta", "division": "D1", "current": 0, "past": 0, "commits": 5}, rows[2])
    ok("a D2 row's commits are null", rows[1] == {"slug": "gamma", "division": "D2", "current": 1, "past": 0, "commits": None}, rows[1])
    ok("no row carries a total that includes commits", all(set(r) == {"slug", "division", "current", "past", "commits"} for r in rows))
    a = trends.answer(doc, {"kind": "club", "id": "x-sc"})
    ok("answer totals keep commits apart from current + past; a D2 row adds nothing to commits",
       a["totals"] == {"current": 3, "past": 1, "commits": 7}, a["totals"])
    g = trends.answer(doc, {"kind": "club", "program": "gamma"})
    ok("a D2 program's answer: commits total null, not 0 (C1)", g["totals"] == {"current": 1, "past": 0, "commits": None}
       and all(r["commits"] is None for r in g["rows"]), g["totals"])
    ok("... and its coverage is the D2 line, commits not collected", len(g["coverage"]) == 1 and g["coverage"][0].startswith("Division II:")
       and "commits not collected" in g["coverage"][0], g["coverage"])
    ok("the answer says so in words", "never added" in a["note"])
    feeders = trends.feeders_for(doc, "club", "beta")
    ok("feeders_for beta: Y (1 current) before X (5 commits, no player)", [r["id"] for r in feeders] == ["y-club", "x-sc"], feeders)
    # a tie on current + past is broken by current, then by commits, then by name - stated so nobody sorts by commits first
    fake = {"clubs": {"c": {"name": "c", "programs": {"p1": [1, 1, 0], "p2": [2, 0, 9], "p3": [0, 2, 9], "p4": [2, 0, 1]}}}, "schools": None,
            "coverage": doc["coverage"]}
    ok("ties: current + past, then current, then commits, then slug",
       [r["slug"] for r in trends.programs_for(fake, "club", "c")] == ["p2", "p4", "p1", "p3"])
    # C1: null ("not collected") is no data: it sorts after a 0, never level with it
    fake["clubs"]["c"]["programs"] = {"a-null": [2, 0, None], "b-zero": [2, 0, 0]}
    ok("ties on players: null commits sort after 0 commits", [r["slug"] for r in trends.programs_for(fake, "club", "c")] == ["b-zero", "a-null"])


def test_schools_field_gate() -> None:
    without = record().index()
    ok("no schoolInfo in the build: schools is null", without["schools"] is None)
    ok("... and every school coverage reads not available, never 0",
       all(without["coverage"][k]["schoolKnown"] is None for k in ("current", "past", "commits"))
       and all(c[k] is None or c[k]["schoolKnown"] is None for c in without["coverage"]["byDivision"].values() for k in ("current", "past", "commits")))
    lines = trends.coverage_lines(without, "school")
    ok("the school coverage lines say not available", all("not available" in l for l in lines), lines)
    got = trends.coverage_lines(without, "club", {"D1": {"current": 2, "past": 1, "commits": 7}})
    ok("the club coverage line has the documented shape, one per division", got
       == ["Division I: 2 of 8 current players, club known for 62%; 1 of 2 former players (stored past rosters), club known for 100%; "
           "7 of 8 verbal or signed commits, club known for 88%",
           "Division II: 1 current players, club known for 100%; 0 former players (stored past rosters), club known for 0%; commits not collected"], got)
    # C2: a D2-only result states the D2 rate (100%), never the merged 67% (6 of 9) nor D1's 62%. Fails if the split is dropped.
    d2 = trends.coverage_lines(without, "club", {"D2": {"current": 1, "past": 0, "commits": None}}, ["D2"])
    ok("a D2-only result's coverage is the D2 rate alone", d2 == ["Division II: 1 of 1 current players, club known for 100%; "
       "0 of 0 former players (stored past rosters), club known for 0%; commits not collected"], d2)

    class FakeMatch:
        def __init__(self, status, sid=None):
            self.status = status; self.sid = sid
        def as_dict(self):
            return {"raw": "Davis HS", "key": "davis", "schoolId": self.sid, "state": "CA", "status": self.status, "school": "Davis Senior High", "city": "Davis"}

    class FakeSchoolTable:  # the shape of schools.Table.match (issue #229): name plus the hometown's state
        def match(self, hs, hometown):
            if hs == "Davis HS" and "Calif" in (hometown or ""):
                return FakeMatch("matched", "ccd:davis")
            return FakeMatch("unmatched")

    with_ = record(with_schools=True, school_table=FakeSchoolTable()).index()
    ok("schoolInfo present: schools is a table", isinstance(with_["schools"], dict))
    ok("a matched current player counts under her school", with_["schools"]["ccd:1"]["programs"]["alpha"] == [1, 0, 0]
       and with_["schools"]["ccd:1"]["name"] == "Rocklin High" and with_["schools"]["ccd:1"]["city"] == "Rocklin", with_["schools"].get("ccd:1"))
    ok("an ambiguous player is not guessed into any school", not any(e["name"] == "Davis Senior High" and e["programs"].get("alpha", [0])[0] for e in with_["schools"].values())
       and "San Marcos" not in json.dumps(with_["schools"]))
    ok("a former player's high school is matched through the school table (with the hometown's state)",
       with_["schools"].get("ccd:davis", {}).get("programs", {}).get("alpha") == [0, 1, 0], with_["schools"].get("ccd:davis"))
    ok("Bea Former's Reno HS is unmatched and not counted", not any("Reno" in json.dumps(e) for e in with_["schools"].values()))
    ok("coverage: current 1 school known, past 1, commits still null",
       with_["coverage"]["current"]["schoolKnown"] == 1 and with_["coverage"]["past"]["schoolKnown"] == 1
       and with_["coverage"]["commits"]["schoolKnown"] is None, with_["coverage"])
    ok("program row alpha counts schools [1, 1, 0]", with_["programs"]["alpha"]["schoolKnown"] == [1, 1, 0])
    rows = trends.programs_for(with_, "school", "ccd:1")
    ok("programs_for a school reports commits as None, not 0", rows == [{"slug": "alpha", "division": "D1", "current": 1, "past": 0, "commits": None}], rows)
    # #315: a D2 former player's school cell carries null commits
    rec = record(with_schools=True, school_table=FakeSchoolTable())
    rec.observe({"slug": "eta", "division": "D2", "roster": {"season": 2026, "players": []}, "commitments": [commit("R Q", CI_X)],
                 "rosterHistory": {"2025": {"players": [{"name": "Ona Former", "hometown": "Davis, Calif.", "highSchool": "Davis HS"}]}}},
                {"slug": "eta", "division": "D2"}, ath={}, tds={}, sw={})
    ok("a D2 program's school cell is [0, 1, null]", rec.index()["schools"]["ccd:davis"]["programs"].get("eta") == [0, 1, None],
       rec.index()["schools"]["ccd:davis"]["programs"])
    ok("feeders_for a school carries the city", trends.feeders_for(with_, "school", "alpha")[0].get("city") == "Rocklin")


def test_search_aka() -> None:
    """#307: the keys the page's search needs beyond a name, and nothing a name search already reaches."""
    real = trends.search_aliases(clubs.load_table(), "mountain-view-los-altos-sc", "Mountain View Los Altos SC")
    ok("MVLA's reviewed short name is carried, shortest first", real[:1] == ["mvla"], real)
    ok("an alias inside the name is left out", "mountain view los altos" not in real, real)
    table = clubs.Table({"clubs": [{"id": "x-sc", "name": "X SC", "state": "CA"}],
                         "aliases": {"xsc united": "x-sc", "x": "x-sc"}, "notAClub": {}})
    rec = trends.Recorder(table, candidates=lambda t, s: {}, same_person=lambda a, b: False, school_table=NoSchools())
    rec._club_entry({"status": "matched", "clubId": "x-sc", "raw": "X SC"})
    rec._club_entry({"status": "unmatched", "raw": "Zeta United", "key": "zeta united"})
    for key in ("southlake carroll", "carroll senior", "southlake carroll"):
        rec._school_entry({"raw": key, "key": key, "schoolId": "ccd:9", "school": "Carroll Senior H S", "city": "Southlake",
                           "state": "TX", "status": "matched"})
    rec._school_entry(SCHOOL_OK)
    rec.schools_seen = True
    doc = rec.index()
    ok("a club carries its aliases the name does not contain", doc["clubs"]["x-sc"].get("aka") == ["xsc united"], doc["clubs"]["x-sc"])
    ok("an unmatched spelling carries none", "aka" not in doc["clubs"]["raw:zeta united"], doc["clubs"]["raw:zeta united"])
    ok("a school carries its roster spellings once, less those inside its name",
       doc["schools"]["ccd:9"].get("aka") == ["southlake carroll"], doc["schools"]["ccd:9"])
    ok("a school seen only under its own name carries none", "aka" not in doc["schools"]["ccd:1"], doc["schools"]["ccd:1"])


def test_written_file() -> None:
    rec = record()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "trends", "index.json")
        doc = rec.write(path)
        text = open(path, encoding="utf-8").read()
        ok("the file is compact: one line plus the trailing newline", text.count("\n") == 1 and "\n  " not in text)
        ok("what was written parses to what was returned", json.loads(text) == doc)
        names = ["Ada Current", "Ann Former", "Bea Former", "R One", "R Two", "R Five", "Gil Current"]
        ok("no player's or recruit's name is in the file", not any(n in text for n in names))
        ok("the only name keys are club and school names", text.count('"name"') == len(doc["clubs"]) + len(doc["schools"] or {}))
        ok("no D2 recruit's name is in the file either", "R Z" not in text and "Hal Current" not in text)
        ok("no tmp file is left behind", sorted(os.listdir(os.path.dirname(path))) == ["index.json"])
    line = trends.summary_line(doc)
    ok("summary_line reads the coverage, per division", "trends (D1, D2): D1 club known 62%; D2 club known 100%; commits D1 only; "
       "9 current players, club known 6 (67%)" in line, line)


BUDGET_GZ = 450 * 1024  # #315: the one file for all divisions measured 327,233 B at gzip -9 on 2026-09-24


def test_size_budget() -> None:
    """The published index, gzipped, stays under the budget; growing past it is a decision (#315, C3).
    Checked on the committed file (rewritten by every refresh) and on a synthetic index of that budget's size."""
    path = os.path.join(common.PUBLIC_DATA_DIR, "trends", "index.json")
    if os.path.exists(path):
        raw = open(path, "rb").read()
        size = len(gzip.compress(raw, 9))
        ok(f"public/data/trends/index.json is {size:,} B gzipped, under {BUDGET_GZ:,}", size <= BUDGET_GZ, size)
    # the check itself can fail: an index past the budget is refused
    rec = record()
    for i in range(20000):
        rec._club_entry({"status": "unmatched", "raw": f"Club {i:05d} {os.urandom(12).hex()}", "key": f"club {i:05d} {os.urandom(12).hex()}"})["programs"]["alpha"] = [1, 0, 0]
    big = len(gzip.compress(json.dumps(rec.index(), separators=(",", ":")).encode(), 9))
    ok("an index past the budget would fail the check", big > BUDGET_GZ, big)


def test_out_dir_follows_the_programs_dir() -> None:
    before = common.PROGRAMS_OUT_DIR
    ok("a publishing build writes under public/data/trends",
       os.path.normcase(trends.out_path()) == os.path.normcase(os.path.join(common.PUBLIC_DATA_DIR, "trends", "index.json")), trends.out_path())
    try:
        common.PROGRAMS_OUT_DIR = os.path.join(tempfile.gettempdir(), "collegedash-scratch-build", "programs")
        want = os.path.join(tempfile.gettempdir(), "collegedash-scratch-build", "trends", "index.json")
        ok("a scratch build with PROGRAMS_OUT_DIR swapped writes beside it, never into public/",
           os.path.normcase(trends.out_path()) == os.path.normcase(want), trends.out_path())
    finally:
        common.PROGRAMS_OUT_DIR = before


def test_build_hook_is_wired() -> None:
    src = open(os.path.join(ROOT, "build.py"), encoding="utf-8").read()
    ok("build.py imports trends", "\nimport trends\n" in src)
    ok("build() observes every profile and writes the index", "trends_recorder.observe(profile, program)" in src
       and "trends_recorder.write()" in src)
    ok("build.py passes its own candidate and same-person rules in, so trends.py never imports build",
       "candidates=club_candidates, same_person=same_person" in src and "import build" not in open(os.path.join(ROOT, "trends.py"), encoding="utf-8").read())
    yml = open(os.path.join(ROOT, ".github", "workflows", "refresh.yml"), encoding="utf-8").read()
    ok("refresh.yml restores the index on its failure path, tolerantly", "public/data/trends/index.json 2>/dev/null || rm -f public/data/trends/index.json" in yml)


def test_answer_shapes() -> None:
    doc = record().index()
    a = trends.answer(doc, {"kind": "club", "program": "alpha"})
    ok("answer for a program: rows are feeders with ids, names and the three counts",
       a["program"] == "alpha" and [r["id"] for r in a["rows"]] == ["x-sc", "y-club", "raw:zeta united"]
       and all({"id", "name", "current", "past", "commits"} <= set(r) for r in a["rows"]), a["rows"])
    ok("answer carries coverage lines (one per division in the result) and no person", len(a["coverage"]) == 1 and "Ada" not in json.dumps(a))
    ok("answer names the divisions, not the v1 `division`", a["divisions"] == ["D1", "D2"] and "division" not in a)
    ok("an unknown club answers with no rows rather than raising", trends.answer(doc, {"kind": "club", "id": "nope"})["rows"] == [])
    try:
        trends.programs_for(doc, "team", "x")
        ok("an unknown kind raises", False)
    except ValueError:
        ok("an unknown kind raises", True)


def main() -> int:
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose
    for fn in (test_counts_equal_a_direct_computation, test_commits_never_enter_a_total, test_schools_field_gate, test_search_aka,
               test_written_file, test_size_budget, test_out_dir_follows_the_programs_dir, test_build_hook_is_wired, test_answer_shapes):
        print(fn.__name__)
        fn()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
