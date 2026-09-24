"""Trends between college programs (D1, D2 and D3), clubs and high schools (issues #230, #315, #327).

Answers "which programs have the most players from club X?" and the reverse, "which clubs feed
program Y?", from what the build already knows about every player and recruit. The owner's
decisions are on #225: three counts side by side - current roster, past rosters, commits - with
commits shown separately and never added into a program's total; coverage shown with every
result so a low count is never read as a true zero; commits as counts only, never a named list.

What is written: `public/data/trends/index.json`, one file (the owner's decision on #315: about 330 KB
gzipped for all three divisions, held under a 450 KB budget by tests/trends_test.py) the page loads on first entry to
#/trends and never before. It carries counts only - no player, no recruit, no name of a person:

    {
      "updated", "divisions": ["D1", "D2", "D3"], "commitDivisions": ["D1"], "season", "pastSeasons": [2023, 2024, 2025],
      "commitStatuses": ["verbal", "signed"],
      "coverage": {
        "current": {"players", "clubKnown", "schoolNamed", "schoolKnown"},   # every division together
        "past":    {"players", "clubKnown", "schoolNamed", "schoolKnown"},
        "commits": {"recruits", "clubKnown", "schoolNamed", "schoolKnown"},  # commitDivisions only
        "byDivision": {"D1": {"current", "past", "commits"}, "D2": {"current", "past", "commits": null}, ...}
      },
      "programs": {slug: {"division", "current", "past", "commits", "clubKnown": [c, p, m], "schoolKnown": [c, p, m]}},
      "format": "records",
      "programIds": [slug, ...],
      "clubs":    {"id": [clubId | "raw:<key>", ...], "name": [...], "state": [...], "unmatched": [i, ...], "aka": {"i": [...]}},
      "schools":  {"id": [schoolId, ...], "name": [...], "city": [...], "state": [...], "aka": {"i": [...]}} | null,
      "records":  {"p": [...], "s": [...], "c": [...], "h": [...]}
    }

Records (#327, replacing #230's per-club and per-school `programs` cells): one per counted person who has a
known club or a matched high school, as four integer columns of one length - `p` an index into `programIds`,
`s` the status (0 current, 1 former, 2 commit), `c` an index into `clubs.id` and `h` into `schools.id`, -1 where
unknown. They answer "club A or B, and school X, at program P" exactly, which two pair tables could not. Sorted
by (p, s, c, h). `format: "records"` names the shape for anything reading /api/v1/trends. Program totals and
coverage stay in `programs` and `coverage`: people are counted there, never by counting records (people with
neither a club nor a school write no record). validate_records states the rules and every build checks them.

The owner's decision on #327 (P1): a former player's record carries both her club and her high school. The page
shows past and commit counts of 1 or 2 as "1-2" in every result; the file itself is exact.

`divisions` (issue #315) replaces the v1 field `"division": "D1"`: the divisions whose programs the index
holds, sorted. `commitDivisions` are the divisions whose commits are collected. Commits in any other division
are not collected (the owner's decision on #315), so they are null, never 0, everywhere they would appear:
the program's `commits`, the third number of its `clubKnown`/`schoolKnown` and of every club and school cell
`[c, p, m]` of that program, and its division's `coverage.byDivision[d].commits`. The few D2/D3 commitment
records the build holds are not counted anywhere. Coverage is per division as well, because club coverage
differs by division (31% of D1 current players against 5% in D2): a result names the rate of each division in
it, so a low D2 count reads as low coverage.

`aka` (issue #307) is what the page's name search needs beyond the canonical name, as cleaned keys, minus
every key already contained in the cleaned name (a search reaches those through the name), shortest first,
absent when empty, so the file stays small:
  * a club's: its reviewed aliases and former names from data/clubs.json ("mvla");
  * a school's: the spellings seen on rosters and recruiting records that resolved to it, as
    `schools.school_key` reduced them ("southlake carroll" for the school NCES files as "CARROLL H S" in
    Southlake, TX, which that spelling reaches through the city-prefix rule of #325).
    A spelling is a school's name as a roster printed it, never a person's.

The three columns are three disjoint populations, so a program's current + past is a count of
distinct people and commits can be read beside it without being added in:

  * current  - players on the program's current roster;
  * past     - players on a stored past roster of the program who are NOT on its current roster
               (its former players, as far as the stored seasons reach);
  * commits  - recruits listed for the program whose status is verbal or signed: not yet on a
               roster (an enrolled recruit is already counted as a current player) and not
               decommitted.

Where the club of a past player comes from: the same three sources as a current player's, resolved
by the same rule (`clubs.resolve`, most recent source wins): the recruiting records the build
already holds for that name, and the past roster page's own Club column, dated with the start of
its season. A past roster row in the published profile carries no club, so this is computed here,
from the stored sources, and only ever as a count.

High schools: a current player's `schoolInfo` (issue #229) is read when the field exists, so this
works on data built before #229 lands - `schools` is then null and the page says so - and lights
up school results once it does. A past player's high school is matched through the same table
when the `schools` module is present. A recruit has no `schoolInfo` today, so the commits column
of a school is null ("not available"), never 0.

"Club known" counts a player whose club string resolved to a reviewed club or stayed as a visible
unmatched spelling; a placeholder ("N/A") is not a club. An unmatched spelling is its own entry,
keyed "raw:<cleaned key>" and flagged `unmatched`, so it is counted in the open rather than
dropped. "School known" counts only a match to exactly one NCES school; "school named" counts any
high-school string, so the page can say both.

`select`, `feeders`, `programs_for`, `feeders_for` and `answer` at the bottom are pure functions over the
index - the hook the AI ask feature (#165) can call from the Worker later, with no build or DOM in the way.
public/index.html carries the same query in JS (trendsQuery, trendsFeeders).

Output directory: beside the programs directory, wherever that is. `common.PROGRAMS_OUT_DIR` is
what decides whether a build is publishing (build.publishing_run) and what every scratch build
swaps to a temp directory, so deriving the trends path from it keeps a test build out of public/
without a new constant in collect/common.py.
"""

from __future__ import annotations

import json
import os

import clubs
from collect import common

try:  # issue #229: present once the high-school matching lands; absent before that
    import schools as _schools
except ImportError:  # pragma: no cover - the data-before-#229 path
    _schools = None

COMMIT_STATUSES = ("verbal", "signed")
DIVISIONS = ("D1", "D2", "D3")
COMMIT_DIVISIONS = ("D1",)  # the owner's decision on #315: D2/D3 commits read "Not collected"
COLUMNS = ("current", "past", "commits")
KNOWN_CLUB = ("matched", "unmatched")
FORMAT = "records"  # #327: the shape of /api/v1/trends


def out_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(common.PROGRAMS_OUT_DIR)), "trends")


def out_path() -> str:
    return os.path.join(out_dir(), "index.json")


def search_aliases(table, club_id: str, name: str | None) -> list[str]:
    """The reviewed keys of `club_id` (aliases and former names) that a substring search over the
    name would not already find: a key contained in the cleaned name adds no match and is left out.
    Shortest first, then alphabetical, so the page can show the shortest key a query hit ("MVLA")."""
    return _aka((k for k, cid in table.aliases.items() if cid == club_id), name)


def _aka(keys, name: str | None) -> list[str]:
    """`keys` less the empty ones and those contained in the cleaned `name`, shortest first."""
    own = clubs.clean_key(name)
    return sorted({k for k in keys if k and k not in own}, key=lambda k: (len(k), k))


def _pct(n: int, d: int) -> int | None:
    return None if not d else round(100 * n / d)


def _empty_row(commits: bool = True) -> list:
    """A program's [current, past, commits] row; commits is null, never 0, where commits are not collected."""
    return [0, 0, 0 if commits else None]


def _new_cov(commits: bool) -> dict:
    return {"current": {"players": 0, "clubKnown": 0, "schoolNamed": 0, "schoolKnown": 0},
            "past": {"players": 0, "clubKnown": 0, "schoolNamed": 0, "schoolKnown": 0},
            "commits": {"recruits": 0, "clubKnown": 0, "schoolNamed": 0, "schoolKnown": None} if commits else None}


class RecordsError(ValueError):
    """The records break a rule the published file must keep (see validate_records)."""


class Recorder:
    """Counts every D1, D2 and D3 profile the build produces into the trends index, one record per
    counted person (#327)."""

    def __init__(self, club_table=None, *, candidates=None, same_person=None, school_table=None):
        """`candidates(tds, sw)` -> {normalised name: [club candidate rows]} and `same_person(a, b)`
        are build.py's own; injected rather than imported so this module never imports build."""
        self.table = club_table or clubs.load_table()
        self.candidates = candidates
        self.same_person = same_person
        self._school_table = school_table
        self.schools_seen = False  # a current player carried `schoolInfo`: the field exists in this build
        self.season = None
        self.past_seasons: set[int] = set()
        self.cov: dict[str, dict] = {}  # division -> the coverage of that division
        self.programs: dict[str, dict] = {}
        self.clubs: dict[str, dict] = {}
        self.schools: dict[str, dict] = {}
        self._school_keys: dict[str, set[str]] = {}
        self.records: list[tuple] = []  # (slug, status, club id | None, school id | None), one per counted person

    # ----- the school table, only when the module exists ---------------------------------------
    def school_table(self):
        if self._school_table is None and _schools is not None and hasattr(_schools, "load_table"):
            self._school_table = _schools.load_table()
        return self._school_table

    # ----- one directory entry per club or school -------------------------------------------------
    def _club_id(self, info: dict | None) -> str | None:
        """The directory id a `clubInfo` counts under, or None when there is no club to count."""
        if not info or info.get("status") not in KNOWN_CLUB:
            return None
        if info.get("status") == "matched" and info.get("clubId"):
            cid = info["clubId"]
            if cid not in self.clubs:
                club = self.table.clubs.get(cid) or {}
                name = club.get("name") or info.get("club") or info.get("raw")
                self.clubs[cid] = {"name": name, "state": club.get("state")}
                aka = search_aliases(self.table, cid, name)
                if aka:
                    self.clubs[cid]["aka"] = aka
            return cid
        key = info.get("key") or clubs.clean_key(info.get("raw"))
        if not key:
            return None
        rid = f"raw:{key}"
        if rid not in self.clubs:
            self.clubs[rid] = {"name": info.get("raw") or key, "state": None, "unmatched": True}
        return rid

    def _school_id(self, info: dict | None) -> str | None:
        if not info or info.get("status") != "matched" or not info.get("schoolId"):
            return None
        sid = info["schoolId"]
        if sid not in self.schools:
            self.schools[sid] = {"name": info.get("school") or info.get("raw"), "city": info.get("city"),
                                 "state": info.get("state")}
        if info.get("key"):
            self._school_keys.setdefault(sid, set()).add(info["key"])
        return sid

    def _person(self, slug: str, status: int, row: dict, cov: dict, cid: str | None, sid: str | None) -> None:
        """One counted person: the known-club and known-school tallies, and a record when either is known."""
        col = COLUMNS[status]
        if cid:
            row["clubKnown"][status] += 1
            cov[col]["clubKnown"] += 1
        if sid:
            row["schoolKnown"][status] += 1
            cov[col]["schoolKnown"] += 1
        if cid or sid:
            self.records.append((slug, status, cid, sid))

    # ----- observing one profile -----------------------------------------------------------------
    def observe(self, profile: dict, program: dict, *, ath=None, tds=None, sw=None) -> None:
        """Count one published profile of any division (#315). Commits are counted only in
        COMMIT_DIVISIONS: elsewhere they are null, and a D2/D3 commitment record is not read.

        `ath`, `tds` and `sw` are the program's stored sources; loaded here when not given, because
        a past player's club is not in the profile and has to be resolved from them."""
        division = program.get("division") or profile.get("division") or "D1"
        if division not in DIVISIONS:
            return
        commits_on = division in COMMIT_DIVISIONS
        slug = profile["slug"]
        cov = self.cov.setdefault(division, _new_cov(commits_on))
        row = self.programs.setdefault(slug, {"division": division, "current": 0, "past": 0, "commits": 0 if commits_on else None,
                                              "clubKnown": _empty_row(commits_on), "schoolKnown": _empty_row(commits_on)})
        roster = profile.get("roster") or {}
        players = roster.get("players") or []
        if roster.get("season"):
            self.season = max(self.season or 0, int(roster["season"]))

        # current roster
        cur_names = set()
        for q in players:
            cur_names.add(common.norm_name(q.get("name") or ""))
            row["current"] += 1
            cov["current"]["players"] += 1
            if "schoolInfo" in q:
                self.schools_seen = True
            if (q.get("highSchool") or "").strip():
                cov["current"]["schoolNamed"] += 1
            self._person(slug, 0, row, cov, self._club_id(q.get("clubInfo")), self._school_id(q.get("schoolInfo")))

        # past rosters: former players only, one count per person however many stored seasons list her
        hist = profile.get("rosterHistory") or {}
        if hist:
            if ath is None:
                ath = common.load_source(slug, "athletics")
            if tds is None:
                tds = common.load_source(slug, "commitments.tds")
            if sw is None:
                sw = common.load_source(slug, "commitments.soccerwire")
            self._observe_past(slug, row, cov, hist, cur_names, ath, tds, sw)

        # commits: counts only, never a name; not read at all where commits are not collected
        for c in (profile.get("commitments") or []) if commits_on else ():
            if c.get("status") not in COMMIT_STATUSES:
                continue
            row["commits"] += 1
            cov["commits"]["recruits"] += 1
            if (c.get("highSchool") or "").strip():
                cov["commits"]["schoolNamed"] += 1
            if "schoolInfo" in c and cov["commits"]["schoolKnown"] is None:  # not published today; counted the day it is
                cov["commits"]["schoolKnown"] = 0
            self._person(slug, 2, row, cov, self._club_id(c.get("clubInfo")), self._school_id(c.get("schoolInfo")))

    def _observe_past(self, slug, row, cov, hist, cur_names, ath, tds, sw) -> None:
        source_hist = (((ath or {}).get("data") or {}).get("rosterHistory") or {})
        cands = self.candidates(tds, sw) if self.candidates else {}
        seen: set[str] = set()
        table = self.school_table()
        # season order newest first, so the most recent stored row is the one that speaks for a person
        for y in sorted(hist, key=lambda s: -int(s)):
            self.past_seasons.add(int(y))
            column = {common.norm_name(p.get("name") or ""): (p.get("club") or "").strip()
                      for p in (source_hist.get(y) or [])}
            for q in (hist[y].get("players") or []):
                n = common.norm_name(q.get("name") or "")
                if not n or n in cur_names or n in seen:
                    continue
                seen.add(n)
                row["past"] += 1
                cov["past"]["players"] += 1
                rows = list(cands.get(n) or [])
                if not rows and self.same_person and cands:
                    rows = list(next((v for k, v in cands.items() if self.same_person(k, q["name"])), []))
                if column.get(n):
                    rows.append({"raw": column[n], "source": "roster page", "updated": clubs.season_date(int(y))})
                chosen = clubs.resolve(rows, self.table) if rows else None
                info = self.table.match(chosen["raw"]).as_dict() if chosen else None
                hs = (q.get("highSchool") or "").strip()
                if hs:
                    cov["past"]["schoolNamed"] += 1
                sinfo = None
                if table is not None and hs:
                    m = table.match(q.get("highSchool"), q.get("hometown"))
                    sinfo = m.as_dict() if getattr(m, "status", None) != "none" else None
                self._person(slug, 1, row, cov, self._club_id(info), self._school_id(sinfo))

    # ----- the index -----------------------------------------------------------------------------
    def _coverage(self) -> dict:
        """Every division together (commits: COMMIT_DIVISIONS only), plus `byDivision`."""
        by = {d: {k: (dict(v) if v is not None else None) for k, v in self.cov[d].items()} for d in sorted(self.cov)}
        total = _new_cov(True)
        for c in by.values():
            for col in COLUMNS:
                for k, v in (c[col] or {}).items():
                    if v is not None:
                        total[col][k] = (total[col][k] or 0) + v
        if not self.schools_seen:
            # the field does not exist in this build: "not available", never "0 known"
            for c in (total, *by.values()):
                for col in COLUMNS:
                    if c[col] is not None:
                        c[col]["schoolKnown"] = None
        return {**total, "byDivision": by}

    def index(self) -> dict:
        program_ids = sorted(self.programs)
        club_ids = sorted(self.clubs)
        school_ids = sorted(self.schools) if self.schools_seen else []
        pi = {s: i for i, s in enumerate(program_ids)}
        ci = {c: i for i, c in enumerate(club_ids)}
        hi = {h: i for i, h in enumerate(school_ids)}
        rows = sorted((pi[slug], status, ci[cid] if cid else -1, hi.get(sid, -1) if sid else -1)
                      for slug, status, cid, sid in self.records)
        rows = [r for r in rows if r[2] >= 0 or r[3] >= 0]  # a school-only record of a build without schools is no record
        clubs_dir = {"id": club_ids, "name": [self.clubs[c]["name"] for c in club_ids],
                     "state": [self.clubs[c]["state"] for c in club_ids],
                     "unmatched": [i for i, c in enumerate(club_ids) if self.clubs[c].get("unmatched")],
                     "aka": {str(i): self.clubs[c]["aka"] for i, c in enumerate(club_ids) if self.clubs[c].get("aka")}}
        schools_dir = None
        if self.schools_seen:
            akas = {h: _aka(self._school_keys.get(h) or (), self.schools[h].get("name")) for h in school_ids}
            schools_dir = {"id": school_ids, "name": [self.schools[h]["name"] for h in school_ids],
                           "city": [self.schools[h]["city"] for h in school_ids],
                           "state": [self.schools[h]["state"] for h in school_ids],
                           "aka": {str(i): akas[h] for i, h in enumerate(school_ids) if akas[h]}}
        doc = {
            "updated": common.now_iso(), "format": FORMAT, "divisions": sorted(self.cov),
            "commitDivisions": list(COMMIT_DIVISIONS), "season": self.season,
            "pastSeasons": sorted(self.past_seasons), "commitStatuses": list(COMMIT_STATUSES),
            "columns": list(COLUMNS), "coverage": self._coverage(),
            "programs": {s: self.programs[s] for s in program_ids},
            "programIds": program_ids,
            "clubs": clubs_dir,
            "schools": schools_dir,
            "records": {"p": [r[0] for r in rows], "s": [r[1] for r in rows], "c": [r[2] for r in rows], "h": [r[3] for r in rows]},
        }
        validate_records(doc)  # the weekly refresh stops here rather than publish a file that breaks a rule
        return doc

    def write(self, path: str | None = None) -> dict:
        """Compact JSON, not common.write_json's indented form: the index is tens of thousands of small
        integers, and indenting each onto its own line makes the file four times the size a visitor's
        browser has to fetch. Same atomic replace as write_json."""
        doc = self.index()
        path = path or out_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
                f.write("\n")
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        return doc


def validate_records(doc: dict) -> None:
    """The rules a published records file keeps (#327, Bianque's plan review), checked on every build and
    by tests/trends_test.py on the committed file:
      * the four columns are integer lists of one length, with keys exactly p, s, c, h (no season);
      * records are sorted by (p, s, c, h), so the file's order says nothing beyond its values;
      * every record points into the directories and knows a club or a school;
      * no record for a commit of a division whose commits are not collected (#315 C1);
      * people are counted by `programs`, never by records: a program's records of one status never
        exceed that program's count of that status."""
    r = doc.get("records") or {}
    if sorted(r) != ["c", "h", "p", "s"]:
        raise RecordsError(f"record keys are {sorted(r)}, not c, h, p, s")
    cols = [r["p"], r["s"], r["c"], r["h"]]
    n = len(cols[0])
    if any(len(c) != n for c in cols) or any(type(v) is not int for c in cols for v in c):
        raise RecordsError("record columns must be integer lists of one length")
    rows = list(zip(*cols))
    if rows != sorted(rows):
        raise RecordsError("records are not sorted by (p, s, c, h)")
    progs = doc["programIds"]
    nclubs = len(doc["clubs"]["id"])
    nschools = len((doc.get("schools") or {}).get("id") or [])
    per: dict[tuple, int] = {}
    for p, s, c, h in rows:
        if not (0 <= p < len(progs)) or s not in (0, 1, 2) or not (-1 <= c < nclubs) or not (-1 <= h < nschools):
            raise RecordsError(f"record {(p, s, c, h)} points outside the directories")
        if c < 0 and h < 0:
            raise RecordsError(f"record {(p, s, c, h)} knows neither a club nor a school")
        per[(p, s)] = per.get((p, s), 0) + 1
    for (p, s), k in per.items():
        prog = doc["programs"][progs[p]]
        total = prog[COLUMNS[s]]
        if total is None:
            raise RecordsError(f"{progs[p]}: {k} {COLUMNS[s]} records where {COLUMNS[s]} are not collected")
        if k > total:
            raise RecordsError(f"{progs[p]}: {k} {COLUMNS[s]} records but {total} {COLUMNS[s]} counted")


def summary_line(doc: dict) -> str:
    c = doc["coverage"]
    cur, past, com = c["current"], c["past"], c["commits"]
    sk = ("" if cur["schoolKnown"] is None
          else f", school known {cur['schoolKnown']} ({_pct(cur['schoolKnown'], cur['players'])}%)")
    by = "; ".join(f"{d} club known {_pct(v['current']['clubKnown'], v['current']['players'])}%"
                   for d, v in (c.get("byDivision") or {}).items())
    return (f"trends ({', '.join(doc.get('divisions') or [])}): {by}; commits {', '.join(doc.get('commitDivisions') or [])} only; "
            f"{cur['players']} current players, club known {cur['clubKnown']} "
            f"({_pct(cur['clubKnown'], cur['players'])}%){sk}; {past['players']} former players, club known "
            f"{past['clubKnown']} ({_pct(past['clubKnown'], past['players'])}%); {com['recruits']} commits, "
            f"club known {com['clubKnown']} ({_pct(com['clubKnown'], com['recruits'])}%); "
            f"{len(doc['clubs']['id'])} clubs, {len((doc['schools'] or {}).get('id') or [])} schools, "
            f"{len(doc['records']['p'])} records")


# ---------- pure functions over the index: the #165 hook ----------------------------------------
# One question, AND across the three boxes and OR within each (#327): which records have a club in
# `clubs` (when any is given) and a school in `schools` (when any) at a program in `programs` (when any).

def _ids(doc: dict, kind: str) -> list:
    if kind not in ("club", "school"):
        raise ValueError(f"kind must be club or school, not {kind!r}")
    return ((doc.get("clubs") if kind == "club" else doc.get("schools")) or {}).get("id") or []


def _matching(doc: dict, clubs_=(), schools_=(), programs=()):
    """The records (p, s, c, h) that match the selection, as index tuples."""
    cix = {c: i for i, c in enumerate(_ids(doc, "club"))}
    hix = {h: i for i, h in enumerate(_ids(doc, "school"))}
    pix = {s: i for i, s in enumerate(doc["programIds"])}
    cs = {cix[c] for c in clubs_ if c in cix}
    hs = {hix[h] for h in schools_ if h in hix}
    ps = {pix[p] for p in programs if p in pix}
    if (clubs_ and not cs) or (schools_ and not hs) or (programs and not ps):
        return []
    r = doc["records"]
    return [t for t in zip(r["p"], r["s"], r["c"], r["h"])
            if (not cs or t[2] in cs) and (not hs or t[3] in hs) and (not ps or t[0] in ps)]


def _commits_shown(doc: dict, slug: str, schools_) -> bool:
    """Commits are a number for a program whose division collects them, and not when a school is chosen
    (no recruit carries a matched high school)."""
    return (doc["programs"].get(slug) or {}).get("commits") is not None and not schools_


def select(doc: dict, clubs=(), schools=(), programs=()) -> list[dict]:
    """Per program: {slug, division, current, past, commits} of the people matching the selection, most
    players first. commits is None where it is not a number (see _commits_shown)."""
    out: dict[str, list] = {}
    ids = doc["programIds"]
    for p, s, _c, _h in _matching(doc, clubs, schools, programs):
        out.setdefault(ids[p], [0, 0, 0])[s] += 1
    rows = [{"slug": slug, "division": doc["programs"][slug].get("division"), "current": c, "past": pa,
             "commits": m if _commits_shown(doc, slug, schools) else None}
            for slug, (c, pa, m) in out.items()]
    return sorted(rows, key=_sort_key)


def feeders(doc: dict, kind: str, clubs=(), schools=(), programs=()) -> list[dict]:
    """The clubs (or schools) of the people matching the selection, most players first.
    Each row: {id, name, state, city?, unmatched?, current, past, commits}."""
    ids = _ids(doc, kind)
    d = doc["clubs"] if kind == "club" else doc["schools"]
    col = 2 if kind == "club" else 3
    counts: dict[int, list] = {}
    for t in _matching(doc, clubs, schools, programs):
        if t[col] >= 0:
            counts.setdefault(t[col], [0, 0, 0])[t[1]] += 1
    commits_known = kind == "club" and not schools and any(
        (doc["programs"].get(s) or {}).get("commits") is not None for s in (programs or doc["programIds"]))
    unmatched = set((d or {}).get("unmatched") or [])
    rows = []
    for i, (c, pa, m) in counts.items():
        r = {"id": ids[i], "name": d["name"][i], "state": d["state"][i], "current": c, "past": pa,
             "commits": m if commits_known else None}
        if i in unmatched:
            r["unmatched"] = True
        if kind == "school" and d["city"][i]:
            r["city"] = d["city"][i]
        rows.append(r)
    return sorted(rows, key=_sort_key)


def _sort_key(r: dict):
    # commits never decide the order; as the last tie-break, null ("not collected") is no data and sorts after 0
    m = r["commits"]
    return (-(r["current"] + r["past"]), -r["current"], -(m if m is not None else -1), r.get("slug") or r.get("name") or "")


def programs_for(doc: dict, kind: str, entity_id: str) -> list[dict]:
    """The programs one club (or school) sent players to: select() with one value in one box."""
    _ids(doc, kind)
    return select(doc, clubs=[entity_id] if kind == "club" else (), schools=[entity_id] if kind == "school" else ())


def feeders_for(doc: dict, kind: str, slug: str) -> list[dict]:
    """The clubs (or schools) one program's players came from."""
    return feeders(doc, kind, programs=[slug])



DIVISION_NAMES = {"D1": "Division I", "D2": "Division II", "D3": "Division III"}


def division_totals(rows: list[dict]) -> dict:
    """{division: {current, past, commits}} over result rows; commits null when no row has a count."""
    out: dict[str, dict] = {}
    for r in rows:
        t = out.setdefault(r.get("division") or "D1", {"current": 0, "past": 0, "commits": None})
        t["current"] += r["current"]
        t["past"] += r["past"]
        if r["commits"] is not None:
            t["commits"] = (t["commits"] or 0) + r["commits"]
    return out


def coverage_lines(doc: dict, kind: str, totals: dict | None = None, divisions=None) -> list[str]:
    """One honest sentence per division (#315: coverage differs by division, so it is never merged), e.g.
    "Division I: 25 of 9,481 current players, club known for 31%; ...; commits not collected" for D2.
    `divisions` are the divisions in the result (default: every division in the index); `totals`
    ({division: {current, past, commits}}, see division_totals) are the counts on screen; without them
    the line states the denominators alone."""
    by = doc["coverage"]["byDivision"]
    what = "club" if kind == "club" else "high school"
    known_key = "clubKnown" if kind == "club" else "schoolKnown"
    out = []
    for d in [d for d in (divisions or doc.get("divisions") or sorted(by)) if d in by]:
        parts = []
        for col, noun, denom_key in (("current", "current players", "players"),
                                      ("past", "former players (stored past rosters)", "players"),
                                      ("commits", "verbal or signed commits", "recruits")):
            c = by[d][col]
            if c is None:
                parts.append("commits not collected")
                continue
            denom, known = c[denom_key], c.get(known_key)
            if known is None:
                parts.append(f"{noun}: {what} not available yet")
                continue
            n = ((totals or {}).get(d) or {}).get(col)
            head = f"{n:,} of {denom:,} {noun}" if n is not None else f"{denom:,} {noun}"
            parts.append(f"{head}, {what} known for {_pct(known, denom) or 0}%")
        out.append(f"{DIVISION_NAMES.get(d, d)}: " + "; ".join(parts))
    return out


def answer(doc: dict, question: dict) -> dict:
    """The JSON shape the ask feature (#165) can return, from one structured question:
        {"clubs": [...], "schools": [...], "programs": [...]}  -> per program, AND across keys, OR within one
        {"kind": "club" | "school", "id": <entity id>}        -> the programs it feeds
        {"kind": "club" | "school", "program": <slug>}         -> the clubs or schools feeding a program
    Counts only; `note` restates the rules a reader must know."""
    kind = question.get("kind") or "club"
    if question.get("program") and not any(question.get(k) for k in ("clubs", "schools", "programs")):
        rows = feeders_for(doc, kind, question["program"])
        division = ((doc.get("programs") or {}).get(question["program"]) or {}).get("division")
        by = division_totals([{**r, "division": division} for r in rows])
        divisions = [division] if division else []
        subject = {"program": question["program"]}
    else:
        if any(question.get(k) for k in ("clubs", "schools", "programs")):
            sel = {k: list(question.get(k) or []) for k in ("clubs", "schools", "programs")}
            kind = "school" if sel["schools"] and not sel["clubs"] else "club"
        else:
            sel = {"clubs": [question.get("id") or ""] if kind == "club" else [],
                   "schools": [question.get("id") or ""] if kind == "school" else [], "programs": []}
        rows = select(doc, sel["clubs"], sel["schools"], sel["programs"])
        by = division_totals(rows)
        divisions = [d for d in (doc.get("divisions") or []) if d in by]
        subject = {kind: question.get("id")} if question.get("id") else sel
    known = [r["commits"] for r in rows if r["commits"] is not None]
    totals = {"current": sum(r["current"] for r in rows), "past": sum(r["past"] for r in rows),
              "commits": sum(known) if known else None}
    return {"divisions": doc.get("divisions"), "season": doc.get("season"), "pastSeasons": doc.get("pastSeasons"),
            **subject, "rows": rows, "totals": totals, "coverage": coverage_lines(doc, kind, by, divisions),
            "note": "Current and past are distinct people; commits are shown separately and never added to a "
                    "program's total, and are collected for " + ", ".join(doc.get("commitDivisions") or []) +
                    " only (null elsewhere). Counts are lower bounds: see the coverage lines."}
