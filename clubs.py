"""Club names: conservative cleanup, an exact lookup against a reviewed alias table, and the
review report that grows the table.

Issue #228, phase 2a of #225. The owner's decisions are on #225 and #228:

  * the table is reviewed data (`data/clubs.json`), edited by people in pull requests;
  * matching is EXACT against the aliases, after a conservative cleanup (case, punctuation,
    whitespace, accents). There is no fuzzy merging anywhere in this module: two strings match only
    when they clean to the same key, and that key is in the table;
  * "Ohio Premier" and "Ohio Elite" must stay separate, and so must "Beach FC (CA)" and
    "Beach FC (VA)". Nothing here strips a bracketed state, and nothing here compares two names for
    similarity;
  * a string the table does not know stays visible: the raw string is kept, the record is marked
    `unmatched`, and the string is listed in `data/clubs-review.json` for review;
  * renames and mergers are one club with the old name kept as an alias and shown (`formerNames`);
  * when two sources disagree, the most recently updated source wins - see `resolve`.

`suggest_key` is the one place that strips league tags, team colours, birth years and club-type
suffixes. It NEVER matches anything on its own: it only groups strings into SUGGESTIONS in the
review report, labelled as suggestions, for a person to accept or reject. The probe on #228 found
real clubs it would wrongly merge ("FC United (IL)" with "United FC (WI)", "Beach FC (CA)" with
"Beach FC (VA)", "Elite Girls Academy" with "Elite 11"), which is exactly why it cannot decide.
"""
from __future__ import annotations

import os
import re
import unicodedata

from collect import common

TABLE_PATH = os.path.join(common.ROOT, "data", "clubs.json")
REVIEW_PATH = os.path.join(common.ROOT, "data", "clubs-review.json")

# Sources of a club string, most trusted first. This is the order the owner set on #228
# (commitment records, then the roster page's own Club column, then a labelled bio field) and it
# is only a tie-break: a later source with a more recent date wins, see `resolve`.
PRECEDENCE = ("TopDrawerSoccer", "SoccerWire", "roster page", "bio field")

# Letters that NFKD does not decompose, and the punctuation that turns up in scraped names.
_FOLD = str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "Æ": "Ae", "ß": "ss", "ł": "l", "Ł": "L",
                       "đ": "d", "Đ": "D", "ð": "d", "þ": "th", "’": "'", "‘": "'", "‚": "'",
                       "“": '"', "”": '"', "–": "-", "—": "-", "‑": "-", " ": " "})


def clean_key(s: str | None) -> str:
    """The conservative cleanup: case, punctuation, whitespace, accents, and `&` spelled out.

    This is the only normalisation that decides a match. It keeps every word, every number and
    every bracketed qualifier, so "beach fc ca" and "beach fc va" stay different keys.
    """
    if not s:
        return ""
    t = unicodedata.normalize("NFKD", str(s).translate(_FOLD))
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    t = t.replace("&", " and ").replace("'", "")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


# --- suggestion-only rules (never decide a match) ---------------------------------------------

_LEAGUE_TAIL = r"(?:pre ecnl|ecnl rl|ecnl|ecrl|rl|girls academy|ga|npl|edp|dpl|mls next|aspire)"
_COLOUR_TAIL = r"(?:blue|white|red|black|gold|navy|green|orange|silver|grey|gray|platinum)"
_TYPE_TAIL = r"(?:soccer club|football club|youth soccer|futbol club|soccer|sc|fc|s c|f c|club)"
_WRITTEN_OUT = {"mtn": "mountain", "st": "saint", "utd": "united", "intl": "international"}


def suggest_key(s: str | None) -> str:
    """A looser key used ONLY to group strings into suggestions in the review report.

    It drops a trailing bracketed qualifier, a trailing league tag, team colour or birth year, and
    a trailing club-type word, and spells out a few abbreviations. It is deliberately not used for
    matching: see the module docstring for the clubs it would wrongly merge.
    """
    if not s:
        return ""
    t = clean_key(re.sub(r"\s*\([^)]*\)\s*$", "", str(s).strip()))
    t = " ".join(_WRITTEN_OUT.get(w, w) for w in t.split())
    for _ in range(3):
        before = t
        t = re.sub(r"\s+(?:g|b)?(?:20)?(?:0\d|1\d)(?:\s*(?:g|b))?$", "", t)
        t = re.sub(r"\s+" + _COLOUR_TAIL + r"$", "", t)
        t = re.sub(r"\s+" + _LEAGUE_TAIL + r"$", "", t)
        t = re.sub(r"\s+" + _TYPE_TAIL + r"$", "", t)
        t = re.sub(r"^(?:fc|sc)\s+", "", t)
        if t == before:
            break
    return t or clean_key(s)


# --- the reviewed table -------------------------------------------------------------------------

class TableError(ValueError):
    """The reviewed table contradicts itself. Raised on load so a bad edit fails the build."""


class Match:
    """What one raw club string resolved to. `status` is matched / unmatched / not-a-club / none."""

    __slots__ = ("raw", "key", "clubId", "name", "state", "country", "status")

    def __init__(self, raw, key, club=None, club_id=None, status="unmatched"):
        self.raw, self.key, self.status = raw, key, status
        self.clubId = club_id
        self.name = (club or {}).get("name")
        self.state = (club or {}).get("state")
        self.country = (club or {}).get("country")

    @property
    def outside_us(self) -> bool:
        return bool(self.country) and self.country != "US"

    def as_dict(self, source=None, updated=None) -> dict:
        """The per-record field: the raw string always, the canonical id when there is one."""
        out = {"raw": self.raw, "key": self.key, "clubId": self.clubId, "club": self.name,
               "status": self.status, "source": source, "updated": updated}
        if self.status == "matched":
            out["state"] = self.state
            out["country"] = self.country
            if self.outside_us:
                out["outsideUS"] = True
        return out


class Table:
    """`data/clubs.json`: canonical clubs, their reviewed aliases, and the not-a-club list."""

    def __init__(self, doc: dict):
        self.updated = doc.get("updated")
        self.clubs = {c["id"]: c for c in doc.get("clubs") or []}
        self.aliases: dict[str, str] = {}
        self.notAClub: dict[str, str] = {}
        if len(self.clubs) != len(doc.get("clubs") or []):
            raise TableError("data/clubs.json: two clubs share an id")
        for club in self.clubs.values():
            for name in [club["name"], *(club.get("formerNames") or [])]:
                self._add_alias(clean_key(name), club["id"], f"the name of {club['id']}")
        for key, target in (doc.get("aliases") or {}).items():
            club_id = target["club"] if isinstance(target, dict) else target
            if club_id not in self.clubs:
                raise TableError(f"data/clubs.json: alias {key!r} points at unknown club {club_id!r}")
            if clean_key(key) != key:
                raise TableError(f"data/clubs.json: alias {key!r} is not a cleaned key "
                                 f"(expected {clean_key(key)!r})")
            self._add_alias(key, club_id, "an alias")
        for key, reason in (doc.get("notAClub") or {}).items():
            if clean_key(key) != key:
                raise TableError(f"data/clubs.json: notAClub key {key!r} is not a cleaned key")
            if key in self.aliases:
                raise TableError(f"data/clubs.json: {key!r} is both an alias and notAClub")
            self.notAClub[key] = reason

    def _add_alias(self, key: str, club_id: str, what: str) -> None:
        if not key:
            raise TableError(f"data/clubs.json: empty key for club {club_id!r}")
        other = self.aliases.get(key)
        if other and other != club_id:
            raise TableError(f"data/clubs.json: {key!r} is {what} but already maps to {other!r}")
        self.aliases[key] = club_id

    def match(self, raw: str | None) -> Match:
        key = clean_key(raw)
        if not key:
            return Match(raw, key, status="none")
        if key in self.notAClub:
            return Match(raw, key, status="not-a-club")
        club_id = self.aliases.get(key)
        if club_id:
            return Match(raw, key, self.clubs[club_id], club_id, "matched")
        return Match(raw, key, status="unmatched")


_cache: dict[str, Table] = {}


def load_table(path: str | None = None, *, reload: bool = False) -> Table:
    path = path or TABLE_PATH
    if reload or path not in _cache:
        doc = common.read_json(path) or {"clubs": [], "aliases": {}}
        _cache[path] = Table(doc)
    return _cache[path]


# --- picking between sources --------------------------------------------------------------------

def season_date(season: int | None) -> str | None:
    """The date a roster page's Club column speaks for: the start of its season.

    Not the date we fetched the page. Every stored source is fetched in the same refresh, so a
    fetch date would make the roster column the most recent source for every player, which is the
    opposite of what the owner asked for. A roster page states a club as of its season, so that is
    what it is dated with here.
    """
    return f"{int(season)}-08-01" if season else None


def resolve(candidates: list[dict], table: Table | None = None) -> dict | None:
    """Pick the club for one player or recruit from every candidate we hold.

    Each candidate is `{"raw", "source", "updated"}`, where `updated` is an ISO date:

      * SoccerWire  - the profile's own modified date, else created, else the day we last saw it;
      * TopDrawerSoccer - the day we last saw the record (it publishes no date of its own);
      * roster page - the start of the roster's season (`season_date`).

    Rules, in order:
      1. candidates that agree are one answer: agreement means the same canonical club, or - when
         neither is in the table yet - the same cleaned key. The most trusted source's spelling is
         the one kept (PRECEDENCE), so an agreed club reads the same as it does today;
      2. when they disagree, the most recently updated candidate wins (the owner's decision on
         #228). `conflict` records that it happened, and with what, so the profile can say so;
      3. an undated candidate never beats a dated one, and PRECEDENCE breaks a remaining tie.
    """
    table = table or load_table()
    cands = [c for c in candidates if (c or {}).get("raw")]
    if not cands:
        return None

    def rank(c):
        src = c.get("source")
        return PRECEDENCE.index(src) if src in PRECEDENCE else len(PRECEDENCE)

    def identity(c):
        m = table.match(c["raw"])
        return m.clubId or f"key:{m.key}"

    groups: dict[str, list[dict]] = {}
    for c in cands:
        groups.setdefault(identity(c), []).append(c)
    for members in groups.values():
        members.sort(key=rank)
    # PRECEDENCE first, then most recent wins. Python's sort is stable and stays stable under
    # reverse=True, so same-dated groups keep the precedence order, and an undated group ("")
    # sorts last.
    order = sorted(groups.values(), key=lambda ms: rank(ms[0]))
    order.sort(key=lambda ms: max((m.get("updated") or "") for m in ms), reverse=True)
    winner = dict(order[0][0])
    if len(order) > 1:
        winner["conflict"] = [{"raw": ms[0]["raw"], "source": ms[0].get("source"),
                               "updated": ms[0].get("updated")} for ms in order[1:]]
    return winner


def annotate(record: dict, candidates: list[dict], table: Table | None = None) -> dict | None:
    """Write `club`, `clubSource` and `clubInfo` onto one player or commitment record.

    `club` and `clubSource` keep the shape the profile page already reads; `clubInfo` carries the
    raw string, the cleaned key, the canonical id when the table knows it, and the status, so an
    unmatched club is visible as unmatched rather than as a blank.
    """
    table = table or load_table()
    chosen = resolve(candidates, table)
    if not chosen:
        record["clubInfo"] = None
        return None
    m = table.match(chosen["raw"])
    info = m.as_dict(chosen.get("source"), chosen.get("updated"))
    if chosen.get("conflict"):
        info["conflict"] = chosen["conflict"]
    record["club"] = "" if m.status == "not-a-club" else chosen["raw"]
    record["clubSource"] = None if m.status == "not-a-club" else chosen.get("source")
    record["clubInfo"] = info
    return info


# --- the review report --------------------------------------------------------------------------

HOW_TO_USE = [
    "Generated by the build; do not edit this file. It lists every club string the reviewed table "
    "does not know yet, most common first.",
    "To adopt one: add its `key` to `aliases` in data/clubs.json pointing at the club's id, or add "
    "a new club to `clubs` whose `name` cleans to that key. Then rebuild.",
    "`suggestion` is a rule-based guess only (it ignores brackets, league tags, team colours and "
    "SC/FC). It is never applied automatically - two different clubs can share one suggestion.",
    "Nothing here is dropped from the site: an unmatched string is shown and counted as itself.",
]


class Recorder:
    """Counts club strings seen during a build, and writes `data/clubs-review.json`."""

    def __init__(self, table: Table | None = None):
        self.table = table or load_table()
        self.rows: dict[str, dict] = {}
        self.matched_occurrences = 0
        self.records = 0
        self.with_club = 0

    def observe(self, raw: str | None, *, source: str, division: str = "D1", slug: str | None = None,
                counts_as_record: bool = True) -> None:
        if counts_as_record:
            self.records += 1
        key = clean_key(raw)
        if not key:
            return
        self.with_club += 1
        m = self.table.match(raw)
        if m.status != "unmatched":
            self.matched_occurrences += 1
            return
        row = self.rows.setdefault(key, {"key": key, "occurrences": 0, "spellings": {},
                                         "sources": {}, "divisions": {}, "programs": set()})
        row["occurrences"] += 1
        row["spellings"][raw.strip()] = row["spellings"].get(raw.strip(), 0) + 1
        row["sources"][source] = row["sources"].get(source, 0) + 1
        row["divisions"][division] = row["divisions"].get(division, 0) + 1
        if slug:
            row["programs"].add(slug)

    def report(self, previous: dict | None = None, *, today: str | None = None) -> dict:
        today = today or common.today()
        prev_rows = {r["key"]: r for r in (previous or {}).get("unmatched") or []}
        # a suggestion points at a club in the table whose own key groups with this one
        suggestions: dict[str, str] = {}
        for club_id, club in self.table.clubs.items():
            for name in [club["name"], *(club.get("formerNames") or [])]:
                suggestions.setdefault(suggest_key(name), club_id)
        unmatched = []
        for row in self.rows.values():
            first_seen = (prev_rows.get(row["key"]) or {}).get("firstSeen") or today
            # from the raw spelling, not the key: the brackets a suggestion ignores are only in the raw
            common_raw = max(row["spellings"].items(), key=lambda kv: (kv[1], kv[0]))[0]
            club_id = suggestions.get(suggest_key(common_raw))
            unmatched.append({
                "key": row["key"],
                "occurrences": row["occurrences"],
                "spellings": dict(sorted(row["spellings"].items(), key=lambda kv: (-kv[1], kv[0]))),
                "sources": dict(sorted(row["sources"].items())),
                "divisions": dict(sorted(row["divisions"].items())),
                "programs": len(row["programs"]),
                "firstSeen": first_seen,
                "new": row["key"] not in prev_rows,
                "suggestion": ({"club": club_id, "name": self.table.clubs[club_id]["name"],
                                "why": "groups with this club when brackets, league tags, colours and SC/FC are ignored"}
                               if club_id else None),
            })
        unmatched.sort(key=lambda r: (-r["occurrences"], r["key"]))
        new_rows = [r for r in unmatched if r["new"]]
        return {
            "updated": common.now_iso(),
            "howToUse": HOW_TO_USE,
            "summary": {
                "clubsInTable": len(self.table.clubs),
                "aliasesInTable": len(self.table.aliases),
                "recordsSeen": self.records,
                "recordsWithAClubString": self.with_club,
                "clubStringsMatched": self.matched_occurrences,
                "clubStringsUnmatched": sum(r["occurrences"] for r in unmatched),
                "distinctUnmatchedKeys": len(unmatched),
                "matchedShareOfStrings": (round(100 * self.matched_occurrences / self.with_club, 1)
                                          if self.with_club else 0.0),
            },
            "newSinceLastBuild": {
                "count": len(new_rows),
                "note": ("Club strings that were not in the previous report. Review these first."
                         if previous else "First report: every unmatched string is listed as new."),
                "keys": [r["key"] for r in new_rows[:200]],
            },
            "unmatched": unmatched,
        }

    def write(self, path: str | None = None) -> dict:
        path = path or REVIEW_PATH
        report = self.report(common.read_json(path))
        common.write_json(path, report)
        return report
