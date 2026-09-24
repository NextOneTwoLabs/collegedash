"""Checks for trends.py, the clubs & high-schools index behind #/trends (issues #230, #315, #327).

    python tests/trends_test.py            # everything below, offline
    python tests/trends_test.py --verbose  # print every check, not only the failures

Offline and in memory: a small fixture of profiles, stored sources and a club table shaped like the
real ones. The one file written goes to a temp directory. Nothing under public/ or data/ is read
or touched except `data/clubs.json`'s loader being bypassed by a fixture table, and read once by
test_search_aka to check the aliases MVLA's search needs (#307).

What this proves
----------------
* #327: one record per counted person; the records summed by (club, program) equal counts written by hand
  (T6); AND across boxes and OR within one (T1, T2); validate_records refuses every breach it names and runs
  on the committed file (T4, T7); program totals never come from counting records.
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


# ---------- reading the records index ----------

def entry(doc, kind, eid):
    """A club's or school's directory row as a dict (the index stores columns)."""
    d = doc["clubs"] if kind == "club" else doc["schools"]
    i = d["id"].index(eid)
    out = {k: d[k][i] for k in d if k not in ("id", "unmatched", "aka")}
    if i in set(d.get("unmatched") or []):
        out["unmatched"] = True
    if str(i) in (d.get("aka") or {}):
        out["aka"] = d["aka"][str(i)]
    return out


def pairs(doc, kind):
    """{entity id: {slug: [current, past, commits]}} summed from the records - the pair cells of #230."""
    d = doc["clubs"] if kind == "club" else doc["schools"]
    col = "c" if kind == "club" else "h"
    r = doc["records"]
    out = {}
    for p, s, e in zip(r["p"], r["s"], r[col]):
        if e >= 0:
            out.setdefault(d["id"][e], {}).setdefault(doc["programIds"][p], [0, 0, 0])[s] += 1
    return out


# ---------- checks ----------

def test_records_equal_hand_counts() -> None:
    """T6 (Bianque): the records summed by (club, program) equal counts written out by hand from the fixture."""
    doc = record().index()
    want = {"x-sc": {"alpha": [2, 1, 2], "beta": [0, 0, 5], "gamma": [1, 0, 0]},
            "y-club": {"alpha": [1, 1, 0], "beta": [1, 0, 0]},
            "raw:zeta united": {"alpha": [1, 0, 0]}}
    got = pairs(doc, "club")
    ok("T6 club x program counts from the records equal the hand-written ones", got == want, got)
    direct = direct_counts([(profile_alpha(), ATH_ALPHA, CANDIDATES), (profile_beta(), {}, {}),
                            (profile_gamma_d2(), {}, {}), (profile_delta_empty(), {}, {})])
    drop = lambda m: {k: {s: v for s, v in c.items() if s != "gamma"} for k, c in m.items()}  # noqa: E731
    ok("... and the independent direct computation (D1 programs)", drop(got) == drop(direct), (got, direct))
    ok("an unmatched spelling is its own entry, flagged, named as the roster spelled it",
       entry(doc, "club", "raw:zeta united") == {"name": "Zeta United", "state": None, "unmatched": True})
    ok("a placeholder ('N/A') and a player with no club are not entries", not any(k.startswith("raw:n a") for k in doc["clubs"]["id"]))
    ok("the reviewed club's name and state come from the table", entry(doc, "club", "x-sc") == {"name": "X SC", "state": "CA"})
    ok("a former player listed in two stored seasons counts once", doc["programs"]["alpha"]["past"] == 2)
    ok("the enrolled and the decommitted recruits are not commits", doc["programs"]["alpha"]["commits"] == 3)
    ok("program row alpha: current 6, past 2, commits 3, club known [4, 2, 2]",
       doc["programs"]["alpha"] == {"division": "D1", "current": 6, "past": 2, "commits": 3, "clubKnown": [4, 2, 2], "schoolKnown": [0, 0, 0]}, doc["programs"]["alpha"])
    ok("a D1 program with nothing known is still a row, and writes no record",
       doc["programs"]["delta"] == {"division": "D1", "current": 1, "past": 0, "commits": 0, "clubKnown": [0, 0, 0], "schoolKnown": [0, 0, 0]}
       and doc["programIds"].index("delta") not in doc["records"]["p"])
    ok("the D2 program is a row, its commits null although it holds a verbal commit (#315 C1)",
       doc["programs"].get("gamma") == {"division": "D2", "current": 1, "past": 0, "commits": None, "clubKnown": [1, 0, None], "schoolKnown": [0, 0, None]},
       doc["programs"].get("gamma"))
    g = doc["programIds"].index("gamma")
    ok("T9 a D2 verbal commit writes no record", not any(p == g and s == 2 for p, s in zip(doc["records"]["p"], doc["records"]["s"])))
    with_d3 = record()
    with_d3.observe({**profile_gamma_d2(), "slug": "epsilon", "division": "D3"}, {"slug": "epsilon", "division": "D3"}, ath={}, tds={}, sw={})
    d3 = with_d3.index()
    ok("the v1 field `division` stays replaced by `divisions`; `format` names the records shape",
       "division" not in d3 and d3["divisions"] == ["D1", "D2", "D3"] and d3["format"] == "records" and d3["commitDivisions"] == ["D1"])
    ok("#327: the per-entity `programs` cells are gone", all("programs" not in d for d in (d3["clubs"], d3["schools"] or {})))
    cov = doc["coverage"]
    ok("coverage (#315 C2) is unchanged: D1 8 players 5 known, D2 1 and 1, D2 commits null",
       cov["byDivision"]["D1"]["current"]["players"] == 8 and cov["byDivision"]["D1"]["current"]["clubKnown"] == 5
       and cov["byDivision"]["D2"]["current"]["clubKnown"] == 1 and cov["byDivision"]["D2"]["commits"] is None
       and cov["commits"]["recruits"] == 8 and cov["commits"]["clubKnown"] == 7, cov)
    ok("season and past seasons come from the data", doc["season"] == 2026 and doc["pastSeasons"] == [2024, 2025])


# T1/T2: three programs of current players with a club and a school each. A = club a, A' = club a2; B, B' = schools.
def _school(sid, name):
    return {"raw": name, "key": name.lower(), "schoolId": sid, "state": "CA", "status": "matched", "school": name, "city": "Town"}


def and_or_doc():
    table = clubs.Table({"clubs": [{"id": "a", "name": "A FC", "state": "CA"}, {"id": "a2", "name": "A2 FC", "state": "CA"},
                                   {"id": "m", "name": "M SC", "state": "CA"}], "aliases": {}, "notAClub": {}})
    c = lambda cid: {**table.match({"a": "A FC", "a2": "A2 FC", "m": "M SC"}[cid]).as_dict("TopDrawerSoccer", "2025-01-01"), "status": "matched", "clubId": cid}  # noqa: E731
    B, B2 = _school("ccd:b", "B High"), _school("ccd:b2", "B2 High")
    players = [player("P1", c("a"), school=B), player("P2", c("a"), school=B2), player("P3", c("a2"), school=B),
               player("P4", c("m"), school=None)]
    rec = trends.Recorder(table, candidates=lambda t, s: {}, same_person=lambda a, b: False, school_table=NoSchools())
    rec.observe({"slug": "p", "division": "D1", "roster": {"season": 2026, "players": players}, "rosterHistory": {}, "commitments": []},
                {"slug": "p", "division": "D1"}, ath={}, tds={}, sw={})
    rec.observe({"slug": "q", "division": "D1", "roster": {"season": 2026, "players": [player("Q1", c("a"), school=B)]}, "rosterHistory": {}, "commitments": []},
                {"slug": "q", "division": "D1"}, ath={}, tds={}, sw={})
    return rec.index()


def test_and_across_or_within() -> None:
    doc = and_or_doc()
    got = trends.select(doc, clubs=["a"], schools=["ccd:b"], programs=["p"])
    ok("T1 club A and school B at P is 1 person (an OR across boxes gives 3; pairing counts gives 2/2)",
       [(r["slug"], r["current"]) for r in got] == [("p", 1)], got)
    ok("T1 club A and school B, any program: P 1, Q 1", [(r["slug"], r["current"]) for r in trends.select(doc, clubs=["a"], schools=["ccd:b"])]
       == [("p", 1), ("q", 1)])
    got = trends.select(doc, clubs=["a", "m"], programs=["p"])
    ok("T2 clubs A or M at P is 3 people (A twice, M once); AND within a box gives 0", [(r["slug"], r["current"]) for r in got] == [("p", 3)], got)
    ok("T2 a repeated value counts once", trends.select(doc, clubs=["a", "a"], programs=["p"])[0]["current"] == 2)
    ok("T2 schools B or B2 with club A at P: 2", trends.select(doc, clubs=["a"], schools=["ccd:b", "ccd:b2"], programs=["p"])[0]["current"] == 2)
    ok("an unknown value in a box with no known value matches nothing", trends.select(doc, clubs=["nope"]) == [])
    f = trends.feeders(doc, "club", schools=["ccd:b"])
    ok("feeders: the clubs of the people from school B, most first", [(r["id"], r["current"]) for r in f] == [("a", 2), ("a2", 1)], f)
    ok("feeders with a school chosen: commits are not a number", all(r["commits"] is None for r in f))


def test_commits_never_enter_a_total() -> None:
    doc = record().index()
    rows = trends.programs_for(doc, "club", "x-sc")
    ok("programs_for lists alpha, gamma (1 player, commits null), then beta (0 players, 5 commits)",
       [r["slug"] for r in rows] == ["alpha", "gamma", "beta"], rows)
    ok("each row carries the three counts separately", rows[2] == {"slug": "beta", "division": "D1", "current": 0, "past": 0, "commits": 5}, rows[2])
    ok("a D2 row's commits are null", rows[1] == {"slug": "gamma", "division": "D2", "current": 1, "past": 0, "commits": None}, rows[1])
    a = trends.answer(doc, {"kind": "club", "id": "x-sc"})
    ok("answer totals keep commits apart from current + past", a["totals"] == {"current": 3, "past": 1, "commits": 7}, a["totals"])
    g = trends.answer(doc, {"kind": "club", "program": "gamma"})
    ok("a D2 program's answer: commits total null, not 0", g["totals"] == {"current": 1, "past": 0, "commits": None}, g["totals"])
    ok("... and its coverage is the D2 line, commits not collected", len(g["coverage"]) == 1 and g["coverage"][0].startswith("Division II:")
       and "commits not collected" in g["coverage"][0], g["coverage"])
    m = trends.answer(and_or_doc(), {"clubs": ["a", "m"], "schools": [], "programs": ["p"]})
    ok("answer takes a multi-value selection", m["totals"]["current"] == 3 and m["rows"][0]["slug"] == "p", m)
    feeders = trends.feeders_for(doc, "club", "beta")
    ok("feeders_for beta: Y (1 current) before X (5 commits, no player)", [r["id"] for r in feeders] == ["y-club", "x-sc"], feeders)
    ok("ties on players: null commits sort after 0 commits",
       sorted([{"slug": "a-null", "current": 2, "past": 0, "commits": None}, {"slug": "b-zero", "current": 2, "past": 0, "commits": 0}],
              key=trends._sort_key)[0]["slug"] == "b-zero")


def test_validate_records() -> None:
    """T4/T7: the rules every build checks (validate_records), each shown to refuse its breach."""
    base = record().index()
    ok("the fixture's records pass", trends.validate_records(base) is None)
    ok("T4 record keys are exactly p, s, c, h and hold integers only", sorted(base["records"]) == ["c", "h", "p", "s"]
       and all(type(v) is int for col in base["records"].values() for v in col))

    def refused(name, mutate):
        doc = json.loads(json.dumps(base))
        mutate(doc)
        try:
            trends.validate_records(doc)
            ok(f"T7 refused: {name}", False)
        except trends.RecordsError:
            ok(f"T7 refused: {name}", True)

    refused("records out of (p, s, c, h) order", lambda d: [d["records"][k].reverse() for k in "psch"])
    refused("a season column", lambda d: d["records"].__setitem__("y", [2025] * len(d["records"]["p"])))
    refused("a record for a D2 commit", lambda d: [d["records"][k].append(v) for k, v in zip("psch", (d["programIds"].index("gamma"), 2, 0, -1))])
    refused("counting people by records: more current records at alpha than alpha's current players",
            lambda d: [d["records"][k].extend([v] * 5) for k, v in zip("psch", (d["programIds"].index("alpha"), 0, 0, -1))])
    refused("a record that knows neither a club nor a school", lambda d: d["records"]["c"].__setitem__(0, -1) or d["records"]["h"].__setitem__(0, -1))
    refused("a text value", lambda d: d["records"]["c"].__setitem__(0, "x-sc"))
    rec = record()
    rec.records.append(("alpha", 0, "x-sc", None))
    rec.records *= 3
    try:
        rec.index()
        ok("index() itself refuses a file that breaks a rule, so the refresh stops before writing it", False)
    except trends.RecordsError:
        ok("index() itself refuses a file that breaks a rule, so the refresh stops before writing it", True)


def test_built_file() -> None:
    """T7 on the built file: the committed index, rewritten by every refresh. Until the first refresh after #327 it
    is #315's cell file; then every records rule is checked on it."""
    path = os.path.join(common.PUBLIC_DATA_DIR, "trends", "index.json")
    ok("public/data/trends/index.json exists", os.path.exists(path), path)
    if not os.path.exists(path):
        return
    doc = json.load(open(path, encoding="utf-8"))
    if doc.get("format") == "records":
        try:
            trends.validate_records(doc)
            ok("T7 the committed records file keeps every rule", True)
        except trends.RecordsError as e:
            ok("T7 the committed records file keeps every rule", False, e)
    else:
        ok("the committed file is #315's cell file, which the page still reads", "records" not in doc
           and isinstance(doc.get("clubs"), dict) and all("programs" in e for e in list(doc["clubs"].values())[:5]))


def test_schools_field_gate() -> None:
    without = record().index()
    ok("no schoolInfo in the build: schools is null", without["schools"] is None)
    ok("... and every school coverage reads not available, never 0",
       all(without["coverage"][k]["schoolKnown"] is None for k in ("current", "past", "commits")))
    ok("the school coverage lines say not available", all("not available" in l for l in trends.coverage_lines(without, "school")))

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
    sp = pairs(with_, "school")
    ok("schoolInfo present: schools is a directory", isinstance(with_["schools"], dict) and "ccd:1" in with_["schools"]["id"])
    ok("a matched current player counts under her school", sp["ccd:1"]["alpha"] == [1, 0, 0]
       and entry(with_, "school", "ccd:1") == {"name": "Rocklin High", "city": "Rocklin", "state": "CA"}, sp.get("ccd:1"))
    ok("an ambiguous player is not guessed into any school", "San Marcos" not in json.dumps(with_["schools"]))
    ok("a former player's high school is matched through the school table", sp.get("ccd:davis", {}).get("alpha") == [0, 1, 0], sp.get("ccd:davis"))
    ok("P1 (owner, #327): a former player's record carries her club and her school together",
       any(s == 1 and c >= 0 and h >= 0 for s, c, h in zip(with_["records"]["s"], with_["records"]["c"], with_["records"]["h"])))
    ok("coverage: current 1 school known, past 1, commits still null",
       with_["coverage"]["current"]["schoolKnown"] == 1 and with_["coverage"]["past"]["schoolKnown"] == 1
       and with_["coverage"]["commits"]["schoolKnown"] is None, with_["coverage"])
    rows = trends.programs_for(with_, "school", "ccd:1")
    ok("programs_for a school reports commits as None, not 0", rows == [{"slug": "alpha", "division": "D1", "current": 1, "past": 0, "commits": None}], rows)
    ok("feeders_for a school carries the city", trends.feeders_for(with_, "school", "alpha")[0].get("city") in ("Rocklin", "Davis"))


def test_search_aka() -> None:
    """#307: the keys the page's search needs beyond a name, and nothing a name search already reaches."""
    real = trends.search_aliases(clubs.load_table(), "mountain-view-los-altos-sc", "Mountain View Los Altos SC")
    ok("MVLA's reviewed short name is carried, shortest first", real[:1] == ["mvla"], real)
    table = clubs.Table({"clubs": [{"id": "x-sc", "name": "X SC", "state": "CA"}],
                         "aliases": {"xsc united": "x-sc", "x": "x-sc"}, "notAClub": {}})
    rec = trends.Recorder(table, candidates=lambda t, s: {}, same_person=lambda a, b: False, school_table=NoSchools())
    rec._club_id({"status": "matched", "clubId": "x-sc", "raw": "X SC"})
    rec._club_id({"status": "unmatched", "raw": "Zeta United", "key": "zeta united"})
    for key in ("southlake carroll", "carroll senior", "southlake carroll"):
        rec._school_id({"raw": key, "key": key, "schoolId": "ccd:9", "school": "Carroll Senior H S", "city": "Southlake",
                        "state": "TX", "status": "matched"})
    rec._school_id(SCHOOL_OK)
    rec.schools_seen = True
    doc = rec.index()
    ok("a club carries its aliases the name does not contain", entry(doc, "club", "x-sc").get("aka") == ["xsc united"], entry(doc, "club", "x-sc"))
    ok("an unmatched spelling carries none", "aka" not in entry(doc, "club", "raw:zeta united"))
    ok("a school carries its roster spellings once, less those inside its name", entry(doc, "school", "ccd:9").get("aka") == ["southlake carroll"])
    ok("a school seen only under its own name carries none", "aka" not in entry(doc, "school", "ccd:1"))


def test_written_file() -> None:
    rec = record(with_schools=True)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "trends", "index.json")
        doc = rec.write(path)
        text = open(path, encoding="utf-8").read()
        ok("the file is compact: one line plus the trailing newline", text.count("\n") == 1 and "\n  " not in text)
        ok("what was written parses to what was returned", json.loads(text) == doc)
        names = ["Ada Current", "Ann Former", "Bea Former", "R One", "R Two", "R Five", "Gil Current", "R Z", "Hal Current"]
        ok("T4 no player's or recruit's name is in the file", not any(n in text for n in names))
        ok("the only name keys are the club and school directories' name columns", text.count('"name"') == 2)
        ok("no tmp file is left behind", sorted(os.listdir(os.path.dirname(path))) == ["index.json"])
    line = trends.summary_line(doc)
    ok("summary_line reads the coverage and the record count", "9 current players, club known 6 (67%)" in line and "records" in line, line)


BUDGET_GZ = 450 * 1024  # #315's budget; #327's records file measured 257,308 B at gzip -9 on 2026-09-24


def gz_size(raw: bytes) -> int:
    return len(gzip.compress(raw, 9))


def within_budget(size: int) -> bool:
    return size <= BUDGET_GZ


def test_size_budget() -> None:
    """T10: the published index, gzipped, stays under the budget; growing past it is a decision."""
    path = os.path.join(common.PUBLIC_DATA_DIR, "trends", "index.json")
    ok("public/data/trends/index.json exists (it is tracked; a missing file fails, never skips)", os.path.exists(path), path)
    if os.path.exists(path):
        size = gz_size(open(path, "rb").read())
        ok(f"public/data/trends/index.json is {size:,} B gzipped, under {BUDGET_GZ:,}", within_budget(size), size)
    doc = record().index()
    doc["clubs"]["name"] += [os.urandom(24).hex() for _ in range(20000)]
    big = gz_size(json.dumps(doc, separators=(",", ":")).encode())
    ok("an index past the budget fails the check", not within_budget(big), big)
    ok("an index under the budget passes it", within_budget(gz_size(json.dumps(record().index()).encode())))


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
    for fn in (test_records_equal_hand_counts, test_and_across_or_within, test_commits_never_enter_a_total, test_validate_records,
               test_built_file, test_schools_field_gate, test_search_aka, test_written_file, test_size_budget,
               test_out_dir_follows_the_programs_dir, test_build_hook_is_wired, test_answer_shapes):
        print(fn.__name__)
        fn()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
