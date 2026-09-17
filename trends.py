"""Trends between Division I programs, clubs and high schools (issue #230).

Answers "which D1 programs have the most players from club X?" and the reverse, "which clubs feed
program Y?", from what the build already knows about every player and recruit. The owner's
decisions are on #225: three counts side by side - current roster, past rosters, commits - with
commits shown separately and never added into a program's total; coverage shown with every
result so a low count is never read as a true zero; commits as counts only, never a named list.

What is written: `public/data/trends/index.json`, one small file the page loads on first entry to
#/trends and never before. It carries counts only - no player, no recruit, no name of a person:

    {
      "updated", "division": "D1", "season", "pastSeasons": [2023, 2024, 2025],
      "commitStatuses": ["verbal", "signed"],
      "coverage": {
        "current": {"players", "clubKnown", "schoolNamed", "schoolKnown"},
        "past":    {"players", "clubKnown", "schoolNamed", "schoolKnown"},
        "commits": {"recruits", "clubKnown", "schoolNamed", "schoolKnown"}
      },
      "programs": {slug: {"current", "past", "commits", "clubKnown": [c, p, m], "schoolKnown": [c, p, m]}},
      "clubs":    {clubId | "raw:<key>": {"name", "state", "unmatched"?, "programs": {slug: [c, p, m]}}},
      "schools":  {schoolId: {"name", "city", "state", "programs": {slug: [c, p, m]}}} | null
    }

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

`programs_for`, `feeders_for` and `answer` at the bottom are pure functions over the index - the
hook the AI ask feature (#165) can call from the Worker later, with no build or DOM in the way.
public/index.html carries the same functions in JS (trendsProgramsFor, trendsFeedersFor).

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
COLUMNS = ("current", "past", "commits")
KNOWN_CLUB = ("matched", "unmatched")


def out_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(common.PROGRAMS_OUT_DIR)), "trends")


def out_path() -> str:
    return os.path.join(out_dir(), "index.json")


def _pct(n: int, d: int) -> int | None:
    return None if not d else round(100 * n / d)


def _empty_row() -> list[int]:
    return [0, 0, 0]


class Recorder:
    """Counts every D1 profile the build produces into the trends index."""

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
        self.cov = {
            "current": {"players": 0, "clubKnown": 0, "schoolNamed": 0, "schoolKnown": 0},
            "past": {"players": 0, "clubKnown": 0, "schoolNamed": 0, "schoolKnown": 0},
            "commits": {"recruits": 0, "clubKnown": 0, "schoolNamed": 0, "schoolKnown": None},
        }
        self.programs: dict[str, dict] = {}
        self.clubs: dict[str, dict] = {}
        self.schools: dict[str, dict] = {}

    # ----- the school table, only when the module exists ---------------------------------------
    def school_table(self):
        if self._school_table is None and _schools is not None and hasattr(_schools, "load_table"):
            self._school_table = _schools.load_table()
        return self._school_table

    # ----- one entry per club or school ----------------------------------------------------------
    def _club_entry(self, info: dict) -> dict | None:
        """The index entry a `clubInfo` counts into, or None when there is no club to count."""
        if not info or info.get("status") not in KNOWN_CLUB:
            return None
        if info.get("status") == "matched" and info.get("clubId"):
            cid = info["clubId"]
            if cid not in self.clubs:
                club = self.table.clubs.get(cid) or {}
                self.clubs[cid] = {"name": club.get("name") or info.get("club") or info.get("raw"),
                                   "state": club.get("state"), "programs": {}}
            return self.clubs[cid]
        key = info.get("key") or clubs.clean_key(info.get("raw"))
        if not key:
            return None
        rid = f"raw:{key}"
        if rid not in self.clubs:
            self.clubs[rid] = {"name": info.get("raw") or key, "state": None, "unmatched": True, "programs": {}}
        return self.clubs[rid]

    def _school_entry(self, info: dict | None) -> dict | None:
        if not info or info.get("status") != "matched" or not info.get("schoolId"):
            return None
        sid = info["schoolId"]
        if sid not in self.schools:
            self.schools[sid] = {"name": info.get("school") or info.get("raw"), "city": info.get("city"),
                                 "state": info.get("state"), "programs": {}}
        return self.schools[sid]

    @staticmethod
    def _bump(entry: dict | None, slug: str, col: int) -> bool:
        if entry is None:
            return False
        entry["programs"].setdefault(slug, _empty_row())[col] += 1
        return True

    # ----- observing one profile -----------------------------------------------------------------
    def observe(self, profile: dict, program: dict, *, ath=None, tds=None, sw=None) -> None:
        """Count one published profile. D1 only (the owner's decision 7 on #225): a D2 profile is
        left out entirely, so nothing here changes what a D2 page shows.

        `ath`, `tds` and `sw` are the program's stored sources; loaded here when not given, because
        a past player's club is not in the profile and has to be resolved from them."""
        if (program.get("division") or profile.get("division") or "D1") != "D1":
            return
        slug = profile["slug"]
        row = self.programs.setdefault(slug, {"current": 0, "past": 0, "commits": 0,
                                              "clubKnown": _empty_row(), "schoolKnown": _empty_row()})
        roster = profile.get("roster") or {}
        players = roster.get("players") or []
        if roster.get("season"):
            self.season = max(self.season or 0, int(roster["season"]))

        # current roster
        cur_names = set()
        for q in players:
            cur_names.add(common.norm_name(q.get("name") or ""))
            row["current"] += 1
            self.cov["current"]["players"] += 1
            if self._bump(self._club_entry(q.get("clubInfo")), slug, 0):
                row["clubKnown"][0] += 1
                self.cov["current"]["clubKnown"] += 1
            if "schoolInfo" in q:
                self.schools_seen = True
            if (q.get("highSchool") or "").strip():
                self.cov["current"]["schoolNamed"] += 1
            if self._bump(self._school_entry(q.get("schoolInfo")), slug, 0):
                row["schoolKnown"][0] += 1
                self.cov["current"]["schoolKnown"] += 1

        # past rosters: former players only, one count per person however many stored seasons list her
        hist = profile.get("rosterHistory") or {}
        if hist:
            if ath is None:
                ath = common.load_source(slug, "athletics")
            if tds is None:
                tds = common.load_source(slug, "commitments.tds")
            if sw is None:
                sw = common.load_source(slug, "commitments.soccerwire")
            self._observe_past(slug, row, hist, cur_names, ath, tds, sw)

        # commits: counts only, never a name
        for c in profile.get("commitments") or []:
            if c.get("status") not in COMMIT_STATUSES:
                continue
            row["commits"] += 1
            self.cov["commits"]["recruits"] += 1
            if self._bump(self._club_entry(c.get("clubInfo")), slug, 2):
                row["clubKnown"][2] += 1
                self.cov["commits"]["clubKnown"] += 1
            if (c.get("highSchool") or "").strip():
                self.cov["commits"]["schoolNamed"] += 1
            if "schoolInfo" in c:  # not published today; counted the day it is
                if self.cov["commits"]["schoolKnown"] is None:
                    self.cov["commits"]["schoolKnown"] = 0
                if self._bump(self._school_entry(c.get("schoolInfo")), slug, 2):
                    row["schoolKnown"][2] += 1
                    self.cov["commits"]["schoolKnown"] += 1

    def _observe_past(self, slug, row, hist, cur_names, ath, tds, sw) -> None:
        source_hist = (((ath or {}).get("data") or {}).get("rosterHistory") or {})
        cands = self.candidates(tds, sw) if self.candidates else {}
        seen: set[str] = set()
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
                self.cov["past"]["players"] += 1
                rows = list(cands.get(n) or [])
                if not rows and self.same_person and cands:
                    rows = list(next((v for k, v in cands.items() if self.same_person(k, q["name"])), []))
                if column.get(n):
                    rows.append({"raw": column[n], "source": "roster page", "updated": clubs.season_date(int(y))})
                chosen = clubs.resolve(rows, self.table) if rows else None
                info = self.table.match(chosen["raw"]).as_dict() if chosen else None
                if self._bump(self._club_entry(info), slug, 1):
                    row["clubKnown"][1] += 1
                    self.cov["past"]["clubKnown"] += 1
                if (q.get("highSchool") or "").strip():
                    self.cov["past"]["schoolNamed"] += 1
                table = self.school_table()
                if table is not None and (q.get("highSchool") or "").strip():
                    m = table.match(q.get("highSchool"), q.get("hometown"))
                    sinfo = m.as_dict() if getattr(m, "status", None) != "none" else None
                    if self._bump(self._school_entry(sinfo), slug, 1):
                        row["schoolKnown"][1] += 1
                        self.cov["past"]["schoolKnown"] += 1

    # ----- the index -----------------------------------------------------------------------------
    def index(self) -> dict:
        cov = {k: dict(v) for k, v in self.cov.items()}
        if not self.schools_seen:
            # the field does not exist in this build: "not available", never "0 known"
            for k in cov:
                cov[k]["schoolKnown"] = None
        return {
            "updated": common.now_iso(), "division": "D1", "season": self.season,
            "pastSeasons": sorted(self.past_seasons), "commitStatuses": list(COMMIT_STATUSES),
            "columns": list(COLUMNS), "coverage": cov,
            "programs": {s: self.programs[s] for s in sorted(self.programs)},
            "clubs": {k: self.clubs[k] for k in sorted(self.clubs)},
            "schools": {k: self.schools[k] for k in sorted(self.schools)} if self.schools_seen else None,
        }

    def write(self, path: str | None = None) -> dict:
        """Compact JSON, not common.write_json's indented form: the index is thousands of three-number
        cells, and indenting each number onto its own line makes the file four times the size a
        visitor's browser has to fetch. Same atomic replace as write_json."""
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


def summary_line(doc: dict) -> str:
    c = doc["coverage"]
    cur, past, com = c["current"], c["past"], c["commits"]
    sk = ("" if cur["schoolKnown"] is None
          else f", school known {cur['schoolKnown']} ({_pct(cur['schoolKnown'], cur['players'])}%)")
    return (f"trends (D1): {cur['players']} current players, club known {cur['clubKnown']} "
            f"({_pct(cur['clubKnown'], cur['players'])}%){sk}; {past['players']} former players, club known "
            f"{past['clubKnown']} ({_pct(past['clubKnown'], past['players'])}%); {com['recruits']} commits, "
            f"club known {com['clubKnown']} ({_pct(com['clubKnown'], com['recruits'])}%); "
            f"{len(doc['clubs'])} clubs, {len(doc['schools'] or {})} schools")


# ---------- pure functions over the index: the #165 hook ----------------------------------------

def _entities(doc: dict, kind: str) -> dict:
    if kind not in ("club", "school"):
        raise ValueError(f"kind must be club or school, not {kind!r}")
    return doc.get("clubs" if kind == "club" else "schools") or {}


def _sort_key(r: dict):
    return (-(r["current"] + r["past"]), -r["current"], -(r["commits"] or 0), r.get("slug") or r.get("name") or "")


def programs_for(doc: dict, kind: str, entity_id: str) -> list[dict]:
    """The programs a club (or school) sent players to, most players first: current + past decides
    the order, commits never do. Each row: {slug, current, past, commits}; commits is None for a
    school (no recruit carries a matched school today)."""
    entry = _entities(doc, kind).get(entity_id)
    if not entry:
        return []
    school = kind == "school"
    rows = [{"slug": slug, "current": c, "past": p, "commits": None if school else m}
            for slug, (c, p, m) in entry["programs"].items()]
    return sorted(rows, key=_sort_key)


def feeders_for(doc: dict, kind: str, slug: str) -> list[dict]:
    """The clubs (or schools) a program's players came from, most players first.
    Each row: {id, name, state, unmatched?, current, past, commits}."""
    rows = []
    for eid, entry in _entities(doc, kind).items():
        cell = entry["programs"].get(slug)
        if not cell:
            continue
        r = {"id": eid, "name": entry.get("name"), "state": entry.get("state"),
             "current": cell[0], "past": cell[1], "commits": None if kind == "school" else cell[2]}
        if entry.get("unmatched"):
            r["unmatched"] = True
        if kind == "school" and entry.get("city"):
            r["city"] = entry["city"]
        rows.append(r)
    return sorted(rows, key=_sort_key)


def coverage_lines(doc: dict, kind: str, totals: dict | None = None) -> list[str]:
    """One honest sentence per column, e.g. "25 of 9,481 current players; club known for 31%".
    `totals` ({current, past, commits}) are the counts on screen; without them the line states the
    denominators alone."""
    c = doc["coverage"]
    what = "club" if kind == "club" else "high school"
    known_key = "clubKnown" if kind == "club" else "schoolKnown"
    out = []
    for col, noun, denom_key in (("current", "current players", "players"),
                                  ("past", "former players (stored past rosters)", "players"),
                                  ("commits", "verbal or signed commits", "recruits")):
        denom = c[col][denom_key]
        known = c[col].get(known_key)
        if known is None:
            out.append(f"{noun.capitalize()}: {what} not available yet")
            continue
        n = (totals or {}).get(col)
        head = f"{n:,} of {denom:,} {noun}" if n is not None else f"{denom:,} {noun}"
        out.append(f"{head}; {what} known for {_pct(known, denom) or 0}%")
    return out


def answer(doc: dict, question: dict) -> dict:
    """The JSON shape the ask feature (#165) can return, from one structured question:
        {"kind": "club" | "school", "id": <entity id>}   -> programs it feeds
        {"kind": "club" | "school", "program": <slug>}    -> the clubs or schools feeding a program
    Counts only; `note` restates the rules a reader must know."""
    kind = question.get("kind") or "club"
    if question.get("program"):
        rows = feeders_for(doc, kind, question["program"])
        totals = {"current": sum(r["current"] for r in rows), "past": sum(r["past"] for r in rows),
                  "commits": sum(r["commits"] or 0 for r in rows)}
        subject = {"program": question["program"]}
    else:
        rows = programs_for(doc, kind, question.get("id") or "")
        totals = {"current": sum(r["current"] for r in rows), "past": sum(r["past"] for r in rows),
                  "commits": sum(r["commits"] or 0 for r in rows)}
        subject = {kind: question.get("id")}
    return {"division": doc.get("division"), "season": doc.get("season"), "pastSeasons": doc.get("pastSeasons"),
            **subject, "rows": rows, "totals": totals, "coverage": coverage_lines(doc, kind, totals),
            "note": "Current and past are distinct people; commits are shown separately and never added to a "
                    "program's total. Counts are lower bounds: see the coverage lines."}
