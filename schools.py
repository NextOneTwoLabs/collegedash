"""High schools: match a roster player's high-school string to one school in the federal NCES
directory, using the state from the player's hometown, and report what did not match.

Issue #229, phase 2b of #225. The owner's decisions are on #225 and #229:

  * NEVER match without a state. "Mountain View" is a high school in seven states, and the name
    alone cannot tell them apart. The state comes from the player's hometown ("Mountain View,
    Calif." -> CA); a player whose hometown gives no US state is not matched;
  * a player whose hometown is outside the US is marked `outside-us`, not matched. Their school is
    not in the NCES directory anyway;
  * matching is EXACT: the cleaned school name plus the state. If more than one school in that
    state cleans to the same key, the player is `ambiguous` and stays unmatched. Nothing guesses;
  * the candidate list is `data/schools.json`, derived from two public-domain federal files by
    tools/schools_nces.py: the Common Core of Data (public schools) and the Private School Survey
    (private schools). Only the fields a match needs are kept: id, name, city, state, public or
    private, and the source year. Its header records the source URLs and the download date;
  * an unmatched name stays visible: the raw string is kept on the player, marked `unmatched`, and
    listed in `data/schools-review.json` for the owner, most common first.

`school_key` is the only thing that decides a match. It is `clubs.clean_key` (case, punctuation,
whitespace, accents) plus the school-specific variants that mean nothing: "HS", "H.S.", "High
School", "Senior High", "Secondary School" and a leading "The", and "St." / "Mt." / "Ft." spelled
out. It keeps every other word, so "Mountain View" and "Mountain View Los Altos" stay different.
"""
from __future__ import annotations

import os

import clubs
from collect import common

TABLE_PATH = os.path.join(common.ROOT, "data", "schools.json")
REVIEW_PATH = os.path.join(common.ROOT, "data", "schools-review.json")

# --- the state from a hometown -------------------------------------------------------------------

# Roster pages write hometowns AP-style ("Calif.", "N.J.", "Fla."), which common.state_code does not
# read. Keys are cleaned with clubs.clean_key, so "N.J." -> "n j" and "Calif." -> "calif".
_AP_STATES = {
    "ala": "AL", "ariz": "AZ", "ark": "AR", "calif": "CA", "cal": "CA", "colo": "CO", "conn": "CT",
    "del": "DE", "fla": "FL", "ill": "IL", "ind": "IN", "kan": "KS", "kans": "KS", "mass": "MA",
    "mich": "MI", "minn": "MN", "miss": "MS", "mont": "MT", "neb": "NE", "nebr": "NE", "nev": "NV",
    "n h": "NH", "n j": "NJ", "n m": "NM", "n mex": "NM", "n y": "NY", "n c": "NC", "n d": "ND",
    "n dak": "ND", "okla": "OK", "ore": "OR", "penn": "PA", "penna": "PA", "r i": "RI", "s c": "SC",
    "s d": "SD", "s dak": "SD", "tenn": "TN", "tex": "TX", "wash": "WA", "w va": "WV", "w v": "WV",
    "wis": "WI", "wisc": "WI", "wyo": "WY", "d c": "DC",
}
_STATE_KEYS: dict[str, str] = {}
for _code, _name in common.US_STATES.items():
    _STATE_KEYS[clubs.clean_key(_code)] = _code
    _STATE_KEYS[clubs.clean_key(_name)] = _code
_STATE_KEYS.update(_AP_STATES)


def hometown_state(hometown: str | None) -> tuple[str | None, str]:
    """(state code, how it was decided) from a roster hometown.

    Returns ("CA", "us") for a hometown whose last part names a US state in any spelling the roster
    pages use; (None, "outside-us") when the hometown is stated but its last part is not a US state
    (a country or a province: "Toronto, Ontario, Canada", "London, England"); and (None, "none")
    when there is no hometown, or a one-word hometown that names no state ("Layton") - not a US
    state, but not evidence of another country either.

    Anything after a slash is dropped first: pages not yet re-collected since #227 still carry
    "City, ST / High School" in the hometown cell.
    """
    s = common.clean((hometown or "").split("/", 1)[0])
    if not s:
        return None, "none"
    parts = [p for p in (x.strip() for x in s.split(",")) if p]
    if not parts:
        return None, "none"
    tail = parts[-1]
    code = _STATE_KEYS.get(clubs.clean_key(tail))
    if code:
        return code, "us"
    if len(parts) == 1:
        # "Greensboro N.C." / "Seguin Texas": the state is the last word, with no comma before it
        words = tail.split()
        if len(words) > 1:
            code = _STATE_KEYS.get(clubs.clean_key(words[-1]))
            if code:
                return code, "us"
        return None, "none"
    return None, "outside-us"


# --- the school key ------------------------------------------------------------------------------

_WRITTEN_OUT = {"st": "saint", "ste": "sainte", "mt": "mount", "mtn": "mountain", "ft": "fort",
                "preparatory": "prep", "jr": "junior", "sr": "senior"}
# Trailing phrases that say "this is a high school" and nothing else. Longest first, so "senior high
# school" is taken whole rather than as "school" then "high" then "senior".
_TYPE_TAILS = [t.split() for t in (
    "junior senior high school", "junior senior high", "senior high school", "senior high",
    "secondary school", "high school", "h s", "hs", "shs", "high", "secondary", "school",
)]
_PLACEHOLDERS = {"null", "none", "n a", "na", "tbd", "unknown", "undecided", "homeschool", "home school",
                 "homeschooled", "home schooled"}


def school_key(s: str | None) -> str:
    """`clubs.clean_key`, then the school-type words dropped and a few abbreviations written out.

    "Mountain View HS", "Mountain View High School", "MOUNTAIN VIEW HIGH SCHOOL" and "Mountain View
    H.S." all become "mountain view"; "St. Francis" and "Saint Francis" both become "saint francis".
    Every other word stays, which is what keeps "Mountain View" apart from "Mountain View Los Altos"
    and "Lincoln" apart from "Lincoln Southwest".
    """
    words = [_WRITTEN_OUT.get(w, w) for w in clubs.clean_key(s).split()]
    if words and words[0] == "the":
        words = words[1:]
    changed = True
    while changed and words:
        changed = False
        for tail in _TYPE_TAILS:
            if len(words) > len(tail) and words[-len(tail):] == tail:
                words = words[:-len(tail)]
                changed = True
                break
    return " ".join(words)


def is_placeholder(s: str | None) -> bool:
    """"null", "N/A", "TBD", "Homeschool": a cell that names no school."""
    return clubs.clean_key(s) in _PLACEHOLDERS


# --- the derived table --------------------------------------------------------------------------

class TableError(ValueError):
    """data/schools.json is not what tools/schools_nces.py writes. Raised on load so a bad file fails the build."""


COLUMNS = ("id", "name", "city", "state", "type", "year")
# `reason` on an unmatched row whose hometown was collected before #227's parser fix
REASON_NOT_SPLIT = ("hometown still carries '/ school' from before the roster fix (#227); "
                    "resolved by the next roster collection")


class Match:
    """What one high-school string resolved to for one player.

    `status` is matched / unmatched / ambiguous / outside-us / none. `candidates` is the number of
    schools in the state that share the key: 1 when matched, 2+ when ambiguous.
    """

    __slots__ = ("raw", "key", "state", "status", "school", "candidates", "reason")

    def __init__(self, raw, key, state, status, school=None, candidates=0, reason=None):
        self.raw, self.key, self.state, self.status = raw, key, state, status
        self.school = school
        self.candidates = candidates
        self.reason = reason

    @property
    def schoolId(self):
        return self.school["id"] if self.school else None

    def as_dict(self) -> dict:
        out = {"raw": self.raw, "key": self.key, "schoolId": self.schoolId, "state": self.state,
               "status": self.status}
        if self.school:
            out["school"] = self.school["name"]
            out["city"] = self.school["city"]
            out["type"] = self.school["type"]
        if self.status == "ambiguous":
            out["candidates"] = self.candidates
        if self.reason:
            out["reason"] = self.reason
        return out


class Table:
    """data/schools.json, indexed by (state, key)."""

    def __init__(self, doc: dict):
        cols = tuple(doc.get("columns") or ())
        if cols != COLUMNS:
            raise TableError(f"data/schools.json: columns {cols!r}, expected {COLUMNS!r}")
        self.sources = doc.get("sources") or {}
        self.schools: dict[str, dict] = {}
        self.by_key: dict[tuple[str, str], list[dict]] = {}
        for row in doc.get("rows") or []:
            if len(row) != len(COLUMNS):
                raise TableError(f"data/schools.json: row {row!r} does not have {len(COLUMNS)} columns")
            school = dict(zip(COLUMNS, row))
            if school["id"] in self.schools:
                raise TableError(f"data/schools.json: two rows share id {school['id']!r}")
            if school["state"] not in common.US_STATES:
                raise TableError(f"data/schools.json: {school['id']!r} has state {school['state']!r}")
            self.schools[school["id"]] = school
            self.by_key.setdefault((school["state"], school_key(school["name"])), []).append(school)

    def candidates(self, name: str | None, state: str | None) -> list[dict]:
        """Every school in `state` whose name cleans to the same key as `name`. Empty without a state."""
        key = school_key(name)
        if not key or not state:
            return []
        return list(self.by_key.get((state, key), []))

    def match(self, raw: str | None, hometown: str | None) -> Match:
        """One player's high-school string and hometown -> a Match. Never guesses: exact key and
        state, one candidate, or nothing."""
        key = school_key(raw)
        if not key or is_placeholder(raw):
            return Match(raw, key, None, "none")
        state, how = hometown_state(hometown)
        if how == "outside-us":
            return Match(raw, key, None, "outside-us")
        # A hometown that still carries a slash ("City, ST / <school>", or "City, ST /" with the
        # school part empty) is a combined "Hometown / High School" cell the parser had not split
        # when this row was collected (issue #227). On those pages the stored highSchool is the
        # Previous School column - a college for a transfer - so matching it would pair "Miami" with
        # a Texas high school called Miami. The row is left unmatched until the next roster
        # collection stores the split, when this guard no longer fires. The one exception is a slash
        # part that IS the stored high school: that value did come from the right column.
        _, slash, after = (hometown or "").partition("/")
        if slash and school_key(after) != key:
            return Match(raw, key, state, "unmatched", reason=REASON_NOT_SPLIT)
        if not state:
            return Match(raw, key, None, "unmatched")
        found = self.by_key.get((state, key), [])
        if len(found) == 1:
            return Match(raw, key, state, "matched", found[0], 1)
        if len(found) > 1:
            return Match(raw, key, state, "ambiguous", None, len(found))
        return Match(raw, key, state, "unmatched")


_cache: dict[str, Table] = {}


def load_table(path: str | None = None, *, reload: bool = False) -> Table:
    path = path or TABLE_PATH
    if reload or path not in _cache:
        doc = common.read_json(path)
        if doc is None:
            raise TableError(f"{path} is missing: run python tools/schools_nces.py to derive it")
        _cache[path] = Table(doc)
    return _cache[path]


def annotate(player: dict, table: Table | None = None) -> dict | None:
    """Write `schoolInfo` onto one roster player: the raw string, the key, the NCES id when exactly
    one school in the hometown's state carries that name, and the status. An empty high school
    stays empty (`schoolInfo` is None)."""
    table = table or load_table()
    m = table.match(player.get("highSchool"), player.get("hometown"))
    if m.status == "none":
        player["schoolInfo"] = None
        return None
    player["schoolInfo"] = m.as_dict()
    return player["schoolInfo"]


# --- the review report --------------------------------------------------------------------------

HOW_TO_USE = [
    "Generated by the build; do not edit this file. It lists every current-roster high-school "
    "string that did not resolve to one NCES school, most common first, with the state the "
    "player's hometown gave.",
    "`ambiguous`: two or more schools in that state clean to the same name, listed under "
    "`candidates`. The player is left unmatched rather than guessed.",
    "`unmatched` with a state: no school in that state cleans to this name. `nearby` lists up to "
    "five schools in the state whose cleaned name contains, or is contained in, this one - a "
    "reading aid only, never applied.",
    "`unmatched` with no state: the hometown names no US state, so nothing can be matched.",
    "`unmatched` with a `reason`: the row was collected before the roster fix on #227 and its "
    "high-school value is the page's Previous School column. Nothing to review; the next roster "
    "collection stores the split and the row is matched normally.",
    "`outside-us`: counted in the summary only; the hometown is outside the US and the school is "
    "not in the NCES directory.",
    "Nothing here is dropped from the site: the raw string stays on the player, marked with its status.",
]


class Recorder:
    """Counts high-school strings seen during a build, and writes data/schools-review.json."""

    def __init__(self, table: Table | None = None):
        self.table = table or load_table()
        self.rows: dict[tuple[str, str | None], dict] = {}
        self.counts = {"players": 0, "withHighSchool": 0, "matched": 0, "unmatched": 0,
                       "ambiguous": 0, "outsideUS": 0, "noState": 0, "notSplit": 0}
        self.matched_ids: dict[str, int] = {}

    def observe(self, player: dict, m: Match | None = None, *, slug: str | None = None) -> Match:
        self.counts["players"] += 1
        m = m or self.table.match(player.get("highSchool"), player.get("hometown"))
        if m.status == "none":
            return m
        self.counts["withHighSchool"] += 1
        if m.status == "matched":
            self.counts["matched"] += 1
            self.matched_ids[m.schoolId] = self.matched_ids.get(m.schoolId, 0) + 1
            return m
        if m.status == "outside-us":
            self.counts["outsideUS"] += 1
            return m
        self.counts[m.status] += 1
        if m.status == "unmatched" and m.reason == REASON_NOT_SPLIT:
            self.counts["notSplit"] += 1
        elif m.status == "unmatched" and not m.state:
            self.counts["noState"] += 1
        row = self.rows.setdefault((m.key, m.state), {
            "key": m.key, "state": m.state, "status": m.status, "occurrences": 0, "spellings": {},
            "programs": set(), "reason": m.reason})
        row["occurrences"] += 1
        raw = common.clean(m.raw)
        row["spellings"][raw] = row["spellings"].get(raw, 0) + 1
        if slug:
            row["programs"].add(slug)
        return m

    def _nearby(self, key: str, state: str, limit: int = 5) -> list[dict]:
        out = []
        for (st, k), schools in self.table.by_key.items():
            if st != state or k == key or not (key in k or k in key):
                continue
            out.extend(schools)
        out.sort(key=lambda s: (len(school_key(s["name"])), s["name"]))
        return [{"id": s["id"], "name": s["name"], "city": s["city"]} for s in out[:limit]]

    def report(self, previous: dict | None = None, *, today: str | None = None) -> dict:
        today = today or common.today()
        prev = {(r["key"], r.get("state")): r for r in (previous or {}).get("unmatched") or []}
        rows = []
        for row in self.rows.values():
            key, state = row["key"], row["state"]
            entry = {
                "key": key, "state": state, "status": row["status"], "occurrences": row["occurrences"],
                "spellings": dict(sorted(row["spellings"].items(), key=lambda kv: (-kv[1], kv[0]))),
                "programs": len(row["programs"]),
                "firstSeen": (prev.get((key, state)) or {}).get("firstSeen") or today,
                "new": (key, state) not in prev,
            }
            if row["reason"]:
                entry["reason"] = row["reason"]
            if row["status"] == "ambiguous":
                entry["candidates"] = [{"id": s["id"], "name": s["name"], "city": s["city"], "type": s["type"]}
                                       for s in self.table.by_key.get((state, key), [])]
            elif state:
                entry["nearby"] = self._nearby(key, state)
            rows.append(entry)
        rows.sort(key=lambda r: (-r["occurrences"], r["key"], r["state"] or ""))
        c = self.counts
        with_hs = c["withHighSchool"]
        return {
            "updated": common.now_iso(),
            "howToUse": HOW_TO_USE,
            "sources": self.table.sources,
            "summary": {
                "schoolsInTable": len(self.table.schools),
                "playersSeen": c["players"],
                "playersWithAHighSchool": with_hs,
                "matched": c["matched"],
                "unmatched": c["unmatched"],
                "unmatchedWithoutAState": c["noState"],
                "unmatchedUntilTheNextRosterCollection": c["notSplit"],
                "ambiguous": c["ambiguous"],
                "outsideUS": c["outsideUS"],
                "matchedShareOfPlayersWithAHighSchool": round(100 * c["matched"] / with_hs, 1) if with_hs else 0.0,
                "distinctSchoolsMatched": len(self.matched_ids),
                "distinctUnmatchedNames": len(rows),
            },
            "newSinceLastBuild": {
                "count": sum(1 for r in rows if r["new"]),
                "note": ("Names (with their state) that were not in the previous report."
                         if previous else "First report: every name is listed as new."),
                "keys": [f"{r['key']} ({r['state'] or 'no state'})" for r in rows if r["new"]][:200],
            },
            "unmatched": rows,
        }

    def write(self, path: str | None = None) -> dict:
        path = path or REVIEW_PATH
        report = self.report(common.read_json(path))
        common.write_json(path, report)
        return report
