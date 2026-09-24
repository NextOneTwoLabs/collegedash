"""
Build the program registry from the NCAA Directory, keyed by the Directory's stable `orgId`.

Master list: the NCAA Directory's women's soccer sport-sponsorship lists, one request per division
(`memberList?type=12&division=I|II|III&sportCode=WSO`). Every row carries `orgId`, the official
name, the institution's primary conference, its website and athletics URLs and its state. The
lists are for one academic year, so a reclassified program shows up in its new division and a
program that dropped the sport is in no list at all (issue #100: the previous master list, last
season's final RPI table, still had Saint Francis in D1, Mississippi Valley State in D1 and no
West Florida).

Nothing on the master list is matched by name. Identity is:
  - `ids.ncaaOrgId`, once a program has one;
  - otherwise (a program from before #100, or one added by hand) three signals that are not names:
    state, the website domain of the program's College Scorecard row, and its athletics-site
    domain. A program is given an orgId only when every signal it has agrees on exactly one row,
    or when a person has reviewed it into REVIEWED_ORG_IDS. Anything else is `unresolved`: it stays
    exactly where it is and is reported. It is never removed on a guess.

Membership policy (the owner's decisions on issue #94), applied on every build:
  - `onboardedDivisions` in registry.json is the set of divisions the site publishes. Turning on a
    division is adding it to that list.
  - A program moves to whatever division the Directory lists it in; it does not keep a label.
  - A program whose division is not onboarded, or that no list carries, leaves `programs` for
    `heldPrograms`. The entry is kept whole, slug included, with a `hold` block saying why. refresh,
    onboard and build read `programs` only, so a held program is not collected or published.
    It moves back unchanged when its division is onboarded or it reappears in a list.
  - A Directory row in an onboarded division that no registry entry holds is a new program. Its
    fields come from keyed sources only (the Directory row, the Scorecard row joined by website
    domain in the same state); Wikipedia and TopDrawerSoccer fill a field only when the name
    matches exactly AND an independent signal (state for Wikipedia, conference for TDS) agrees.
    Anything a source does not establish is null and listed in the report.
  - `stagedDivisions` is the set of divisions whose programs are built into `programs` but published
    by nothing. What makes an entry staged is its division being in stagedDivisions, not its
    `onboarded` flag: a staged division's batch is collected (`onboarded: true`, sources kept fresh)
    long before the division itself is onboarded -- that is the point of staging, so collection can
    start early -- and build.published_programs() only publishes an entry that is both `onboarded`
    and in a division listed in `onboardedDivisions`. A staged entry fails the second test whatever
    the first says. It is how a division is prepared -- list, slugs and joins reviewed in a diff --
    before it is onboarded (issue #94, Division II). Onboarding then moves the division from one
    list to the other. A staged entry is not held: heldPrograms is for programs the site has published.
  - A `collectionHold` block ({reason, evidence, since}; reason from COLLECTION_HOLD_REASONS) marks
    an entry that stays in `programs` with `onboarded: false` on purpose: a person decided it is not
    to be collected (issue #199: the six merged PSAC campuses, and four D2 programs with no usable
    athletics source). It is how an uncollected entry may sit in an onboarded division. It is not a
    `hold`: a `hold` moves a program the site published out of `programs`, while a collection hold
    is on a program the site never published and stays where it is. The builder never writes,
    changes or removes one; a build keeps it with the rest of the entry.

Existing entries are preserved: a build writes only `division`, `conference` and `ids.ncaaOrgId`
on a program that stays. data/registry-build-report-<division>.json records every decision, per division:
a run writes the file of each division it decided something in and leaves the others untouched.

    python collegedash.py registry build        # writes registry + the reports of the divisions it touched
"""

from __future__ import annotations

import collections
import copy
import functools
import json
import os
import re
import urllib.parse

from bs4 import BeautifulSoup

from . import common
from .wikipedia import MENS_TITLE_RE

DIRECTORY_URL = "https://web3.ncaa.org/directory/api/directory/memberList?type=12&division={roman}&sportCode=WSO"
DIVISION_ROMAN = {"D1": "I", "D2": "II", "D3": "III"}
WIKI_LIST = {"D1": "https://en.wikipedia.org/api/rest_v1/page/html/List_of_NCAA_Division_I_women%27s_soccer_programs"}
TDS_CONFERENCES = [
    ("america-east", 1), ("american-athletic", 1047), ("asun", 22), ("atlantic-10", 2), ("atlantic-coast", 3),
    ("big-12", 23), ("big-east", 5), ("big-sky", 24), ("big-south", 6), ("big-ten", 7), ("big-west", 8),
    ("coastal-athletic-association", 9), ("conference-usa", 10), ("horizon-league", 11), ("independent", 47),
    ("ivy-league", 12), ("metro-atlantic-athletic-conference", 13), ("mid-american", 14), ("missouri-valley", 15),
    ("mountain-west", 25), ("northeast", 17), ("ohio-valley", 26), ("pacific-12", 27), ("patriot-league", 18),
    ("sec", 1044), ("southern", 19), ("southland", 29), ("southwestern-athletic", 30), ("summit-league", 31),
    ("sun-belt", 32), ("united-athletic-conference", 1056), ("west-coast", 21),
]
SCORECARD_BULK = os.path.join(common.DATA_DIR, "scorecard-bulk.json")


def report_path(division: str) -> str:
    """The build report for one division: data/registry-build-report-<d1|d2|d3>.json (issue #190).

    One file per division, so staging D3 cannot overwrite the evidence of the D2 run that the membership
    checks read, and a later run that decides nothing in a division leaves that division's file untouched."""
    return os.path.join(common.DATA_DIR, f"registry-build-report-{division.lower()}.json")


# The report lists that name programs. A division's report keeps only its own rows of these; every other
# field describes the whole run and is copied as it is.
DIVISION_LISTS = ("staged", "reclassified", "held", "returned", "added", "notAdded", "newPrograms")
# The lists in which a row means the run DECIDED something in that division, so its report is written.
# Not `staged`: it lists every staged entry on every build, so a build that changes nothing would rewrite
# the staged division's report with empty `added` and `newPrograms` and erase the evidence of its staging run.
# Not `notAdded` either: rows left for a later run (--limit) are not a decision about the division.
DECISION_LISTS = ("reclassified", "held", "returned", "added")


def division_reports(report: dict, division_of_slug: dict, division_of_name: dict) -> dict[str, dict]:
    """division -> that division's share of a run report, for each division the run decided something in.

    A row's division is its own `division` (a reclassification's `to`), else its slug's division in the
    registry just written. `unmatched` and `contestedScorecardRows` are filtered the same way, the latter by
    the Directory names claiming the row; `counts` is recomputed from the filtered `unmatched`."""

    def division_of(row: dict):
        return row.get("to") or row.get("division") or division_of_slug.get(row.get("slug"))

    touched = sorted({division_of(r) for key in DECISION_LISTS for r in report.get(key) or []} - {None})
    out = {}
    for d in touched:
        rep = dict(report)
        for key in DIVISION_LISTS:
            rep[key] = [r for r in report.get(key) or [] if division_of(r) == d]
        rep["unmatched"] = {f: kept for f, slugs in (report.get("unmatched") or {}).items()
                            for kept in [[s for s in slugs if division_of_slug.get(s) == d]] if kept}
        rep["contestedScorecardRows"] = {u: names for u, names in (report.get("contestedScorecardRows") or {}).items()
                                         if any(division_of_name.get(n) == d for n in names)}
        if "counts" in report:
            rep["counts"] = {k: len(v) for k, v in rep["unmatched"].items()}
        out[d] = rep
    return out

# A build that would take more than this share of the published programs out of `programs` raises
# instead of writing. A truncated or failed Directory response looks exactly like a mass departure.
MAX_DEPARTURE_SHARE = 0.05

# Directory conferenceName (whitespace-trimmed) -> the label the registry and the conference pills use.
# Every D1 label that existed before #100 is kept for the conference it named. Three are new with
# the 2026-27 lists: Pac-12, UAC and Metro (the Directory's name for the 13 former MAAC members).
# A name missing here is published as the Directory spells it and listed in the report.
#
# The table is Division I only, and conference_label() applies it to a D1 row only. Conference names
# repeat across divisions with different meanings: "Independent" is 1 D1 program and 8 D2 programs,
# and they are not the same conference. Division II keeps the Directory's own spelling until its own
# label table is reviewed (issue #94). Since #199 the D1 independent is labelled plain "Independent"
# (owner decision 5 on #197): the division, not the string, tells the two apart, so anything that
# reads a label as D1's must check the division as well (d1_only_labels, and tds_team_for below).
LABELLED_DIVISION = "D1"
CONFERENCE_LABELS = {
    "America East Conference": "America East", "American Conference": "American", "Atlantic 10 Conference": "Atlantic 10",
    "Atlantic Coast Conference": "ACC", "Atlantic Sun Conference": "ASUN", "BIG EAST Conference": "Big East",
    "Big 12 Conference": "Big 12", "Big Sky Conference": "Big Sky", "Big South Conference": "Big South",
    "Big Ten Conference": "Big Ten", "Big West Conference": "Big West", "Coastal Athletic Association": "CAA",
    "Conference USA": "CUSA", "Horizon League": "Horizon", "Independent": "Independent", "The Ivy League": "Ivy League",
    "Metro Conference": "Metro", "Mid-American Conference": "MAC", "Missouri Valley Conference": "MVC",
    "Mountain West Conference": "Mountain West", "Northeast Conference": "NEC", "Ohio Valley Conference": "OVC",
    "Pac-12 Conference": "Pac-12", "Patriot League": "Patriot", "Southeastern Conference": "SEC",
    "Southern Conference": "SoCon", "Southland Conference": "Southland", "Southwestern Athletic Conf.": "SWAC",
    "The Summit League": "Summit League", "Sun Belt Conference": "Sun Belt", "United Athletic Conference": "UAC",
    "West Coast Conference": "WCC",
}
# The same conferences as TopDrawerSoccer names them, for the conference check on a TDS team match.
LABEL_TDS_CONFERENCE = {
    "America East": "america-east", "American": "american-athletic", "Atlantic 10": "atlantic-10", "ACC": "atlantic-coast",
    "ASUN": "asun", "Big East": "big-east", "Big 12": "big-12", "Big Sky": "big-sky", "Big South": "big-south",
    "Big Ten": "big-ten", "Big West": "big-west", "CAA": "coastal-athletic-association", "CUSA": "conference-usa",
    "Horizon": "horizon-league", "Independent": "independent", "Ivy League": "ivy-league",
    "Metro": "metro-atlantic-athletic-conference", "MAC": "mid-american", "MVC": "missouri-valley",
    "Mountain West": "mountain-west", "NEC": "northeast", "OVC": "ohio-valley", "Pac-12": "pacific-12",
    "Patriot": "patriot-league", "SEC": "sec", "SoCon": "southern", "Southland": "southland",
    "SWAC": "southwestern-athletic", "Summit League": "summit-league", "Sun Belt": "sun-belt", "UAC": "united-athletic-conference",
    "WCC": "west-coast",
}


def d1_only_labels() -> set[str]:
    """The D1 labels no Directory name is spelled as: the strings only the D1 table can produce, so
    an entry of another division carrying one was run through that table by mistake. "Independent"
    is not one of them since #199 -- the table maps it to itself, so a D2 independent reads the same
    whichever table it went through, and only its division says which conference it is."""
    return {label for name, label in CONFERENCE_LABELS.items() if label != name}


# Why an entry in `programs` is deliberately not collected (see the module docstring). A new reason is
# a reviewed decision, added here in the PR that first uses it.
COLLECTION_HOLD_REASONS = {
    "merged-scorecard-row": "the campus shares one College Scorecard row with other campuses of a merged university",
    "no-athletics-source": "no citable source gives a usable athletics site",
}
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def collection_hold_problem(p: dict) -> str | None:
    """None when `p` carries a well-formed collection hold, else what is wrong with it (including
    that it has none). Well formed: exactly {reason, evidence, since}, a known reason, non-empty
    evidence, an ISO date, on an entry that is not collected."""
    hold = p.get("collectionHold")
    if hold is None:
        return "no collectionHold"
    if not isinstance(hold, dict) or set(hold) != {"reason", "evidence", "since"}:
        return f"collectionHold must be exactly {{reason, evidence, since}}, got {hold!r}"
    if hold["reason"] not in COLLECTION_HOLD_REASONS:
        return f"collectionHold.reason {hold['reason']!r} is not one of {sorted(COLLECTION_HOLD_REASONS)}"
    if not (isinstance(hold["evidence"], str) and hold["evidence"].strip()):
        return "collectionHold.evidence is empty"
    if not (isinstance(hold["since"], str) and _ISO_DATE.match(hold["since"])):
        return f"collectionHold.since {hold['since']!r} is not a YYYY-MM-DD date"
    if p.get("onboarded"):
        return "collectionHold is on a collected entry (onboarded: true)"
    return None

# Reviewed by hand on issue #100 (2026-09-15, Directory lists for 2026-27): the registry programs
# whose three identity signals did not all agree. State and one domain agree in every case, and the
# other domain points at no other institution; each was read and is the same institution.
# slug -> (orgId, what differed). Only consulted for a program that has no ids.ncaaOrgId yet.
REVIEWED_ORG_IDS = {
    "rhode-island": (572, "Scorecard site web.uri.edu, Directory uri.edu; athletics gorhody.com agrees"),
    "texas-state": (670, "Scorecard site txst.edu, Directory txstate.edu; athletics txstatebobcats.com agrees"),
    "rutgers": (587, "Scorecard site newbrunswick.rutgers.edu, Directory rutgers.edu (New Brunswick); athletics agrees"),
    "indiana": (306, "Scorecard site bloomington.iu.edu, Directory iub.edu (Bloomington); athletics iuhoosiers.com agrees"),
    "quinnipiac": (562, "Scorecard site qu.edu, Directory quinnipiac.edu; athletics gobobcats.com agrees"),
    "minnesota": (428, "Scorecard site twin-cities.umn.edu, Directory umn.edu (Twin Cities); athletics agrees"),
    "college-of-charleston": (1014, "Scorecard site charleston.edu, Directory cofc.edu; athletics cofcsports.com agrees"),
    "southern-illinois": (659, "Scorecard site siu.edu, Directory siuc.edu (Carbondale); athletics siusalukis.com agrees"),
    "indiana-state": (305, "Scorecard site indianastate.edu, Directory indstate.edu; athletics gosycamores.com agrees"),
    "unc-asheville": (456, "Scorecard site new.unca.edu, Directory unca.edu; athletics uncabulldogs.com agrees"),
    "arizona-state": (28, "website asu.edu agrees; athletics thesundevils.com, Directory sundevils.com"),
    "colgate": (153, "website colgate.edu agrees; athletics colgateathletics.com, Directory gocolgateraiders.com"),
    "houston-christian": (287, "website hc.edu agrees; athletics hbuhuskies.com, Directory hcuhuskies.com"),
    "texas": (703, "website utexas.edu agrees; athletics texassports.com, Directory texaslonghorns.com"),
    "northeastern": (500, "website northeastern.edu agrees; athletics gonu.com, Directory nuhuskies.com"),
    "little-rock": (32, "website ualr.edu agrees; the Directory has no athletics URL"),
    "southern-indiana": (661, "website usi.edu agrees; athletics gousieagles.com, Directory usiscreamingeagles.com"),
    "wofford": (2915, "website wofford.edu agrees; athletics athletics.wofford.edu, Directory wofford.edu"),
    "iona-university": (310, "website iona.edu agrees; athletics icgaels.com, Directory ionagaels.com"),
    "west-georgia": (766, "website westga.edu agrees; athletics uwgsports.com, Directory uwgathletics.com"),
    "texas-southern": (699, "website tsu.edu agrees; athletics athletics.tsu.edu, Directory tsusports.com"),
    "fairleigh-dickinson": (222, "fdu.edu is both the Metropolitan campus (222, D1) and Florham (221, D3); "
                                 "athletics fduknights.com and the registry's Teaneck team are 222"),
}
# Reviewed on issue #100: registry programs that no Directory list carries, by id, website domain or
# athletics domain, in any division. slug -> evidence. A program with no orgId leaves the published
# set only when it is listed here; without review it is `unresolved` and stays put.
REVIEWED_NOT_LISTED = {
    "mississippi-val": "2026-27 lists D1 349, D2 261, D3 416: no row for mvsu.edu or mvsusports.com, and no "
                       "Mississippi Valley State under any name",
}

# Reviewed by the owner (issue #190): the slug a NEW program takes when the ladder's own choice is not the one
# to publish -- a generic word ("eastern"), a name read straight off a long official title, or a campus that
# should follow its siblings' pattern. orgId -> (slug, reason).
#
# Only a Directory row the registry does not hold yet is named from here. A slug is a permanent URL and the
# builder never renames an entry it already holds, so an override for an orgId already in the registry does
# nothing -- which is also why the table has to land before the division it names is staged. A reviewed slug
# is taken exactly or the build refuses: one that is not a valid slug, that two overrides share, or that an
# entry already holds is an error, never quietly moved down the ladder to something nobody reviewed.
#
# Division III, 43 renames: all 41 proposed on #190 and accepted by the owner as written (2026-09-23), plus
# mcla and penn-college, which the owner added on #247. The comment on each line is the slug the ladder gives
# without the override.
_D3_GENERIC = "#190: the ladder's slug is a generic word"
_D3_LONG = "#190: the ladder's slug is over 30 characters"
_D3_SUNY = "#190: one pattern, suny-<campus>, for all 18 SUNY campuses"
_D3_SIBLING = "#190: follows its sibling campuses, or mends a name the ladder cut up"
REVIEWED_SLUGS: dict[int, tuple[str, str]] = {
    8968: ("eastern-pa", _D3_GENERIC),  # eastern
    652: ("sewanee", _D3_GENERIC),  # south (University of the South)
    124: ("catholic-dc", _D3_GENERIC),  # catholic
    117: ("capital-oh", _D3_GENERIC),  # capital
    412: ("methodist-nc", _D3_GENERIC),  # methodist
    30264: ("regent-va", _D3_GENERIC),  # regent
    142: ("claremont-mudd-scripps", _D3_LONG),  # claremont-mckenna-harvey-mudd-scripps-colleges
    538: ("penn-state-behrend", _D3_LONG),  # pennsylvania-state-univ-erie-behrend-college
    588: ("rutgers-camden", _D3_LONG),  # rutgers-state-univ-new-jersey-camden
    589: ("rutgers-newark", _D3_LONG),  # rutgers-state-univ-new-jersey-newark
    398: ("mit", _D3_LONG),  # massachusetts-institute-technology
    89: ("caltech", _D3_LONG),  # california-institute-technology
    570: ("rensselaer", _D3_LONG),  # rensselaer-polytechnic-institute
    808: ("wpi", _D3_LONG),  # worcester-polytechnic-institute
    585: ("rose-hulman", _D3_LONG),  # rose-hulman-institute-technology
    282: ("hobart-william-smith", _D3_LONG),  # hobart-and-william-smith-colleges
    321: ("john-jay-college", _D3_LONG),  # john-jay-college-criminal-justice
    751: ("washington-jefferson", _D3_LONG),  # washington-and-jefferson-college
    486: ("mcla", _D3_LONG + ", added by the owner on #247"),  # massachusetts-college-liberal-arts
    30190: ("penn-college", _D3_LONG + ", added by the owner on #247"),  # pennsylvania-college-technology
    78: ("suny-brockport", _D3_SUNY),  # state-new-york-brockport
    85: ("suny-buffalo-state", _D3_SUNY),  # buffalo-state-state-new-york
    30165: ("suny-canton", _D3_SUNY),  # state-new-york-canton
    30083: ("suny-cobleskill", _D3_SUNY),  # state-new-york-cobleskill
    168: ("suny-cortland", _D3_SUNY),  # state-new-york-cortland
    30225: ("suny-delhi", _D3_SUNY),  # state-new-york-delhi
    242: ("suny-fredonia", _D3_SUNY),  # state-new-york-fredonia
    247: ("suny-geneseo", _D3_SUNY),  # state-new-york-geneseo
    478: ("suny-maritime", _D3_SUNY),  # state-new-york-maritime-college
    30067: ("suny-morrisville", _D3_SUNY),  # state-new-york-morrisville
    475: ("suny-new-paltz", _D3_SUNY),  # state-new-york-new-paltz
    524: ("suny-old-westbury", _D3_SUNY),  # state-new-york-old-westbury
    526: ("suny-oneonta", _D3_SUNY),  # state-new-york-oneonta
    530: ("suny-oswego", _D3_SUNY),  # state-new-york-oswego
    547: ("suny-plattsburgh", _D3_SUNY),  # plattsburgh-state-new-york
    9500: ("suny-polytechnic", _D3_SUNY),  # state-new-york-polytechnic-institute
    552: ("suny-potsdam", _D3_SUNY),  # state-new-york-potsdam
    30029: ("suny-purchase", _D3_SUNY),  # purchase-college-state-new-york
    1340: ("st-josephs-ny-long-island", _D3_SIBLING),  # st-josephs-new-york-l-i
    30044: ("penn-state-berks", _D3_SIBLING),  # penn-state-berks-college
    803: ("wisconsin-stout", _D3_SIBLING),  # wisconsin-stout-polytechnic
    722: ("coast-guard", _D3_SIBLING),  # u-s-coast-guard-academy
    724: ("merchant-marine", _D3_SIBLING),  # u-s-merchant-marine-academy
}
SLUG_SHAPE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")  # the shape build.STAGED_SLUG_SHAPE checks on every staged entry

# Time zones come from the coordinates, never from the state (issue #110). The state table this
# replaces put Knoxville, Chattanooga and Johnson City on Central time, Murray, Bowling Green,
# Evansville and Valparaiso on Eastern, El Paso on Central and Moscow (Idaho) on Mountain, and it had
# to leave Pensacola null because Florida spans two zones.
#
# Source: the timezone-boundary-builder polygons (built from OpenStreetMap, ODbL), looked up offline by
# the `timezonefinder` package, which bundles them (requirements-registry.txt). The coordinates are the College Scorecard row's.
_TZ_FINDER = None


def timezone_at(lat, lon) -> str | None:
    """The IANA zone whose boundary contains (lat, lon), or None without coordinates or for a point in
    no zone polygon. Raises ImportError if timezonefinder is not installed: a missing library must not
    look like a program with no time zone."""
    global _TZ_FINDER
    if lat is None or lon is None:
        return None
    if _TZ_FINDER is None:
        try:
            from timezonefinder import TimezoneFinder
        except ImportError as e:  # the registry build's own extra, not part of requirements.txt (PR #112 review, F6)
            raise ImportError("timezonefinder is not installed: pip install -r requirements-registry.txt") from e
        _TZ_FINDER = TimezoneFinder()
    return _TZ_FINDER.timezone_at(lat=float(lat), lng=float(lon))


EXPAND = {
    "fla.": "florida", "ga.": "georgia", "ky.": "kentucky", "mich.": "michigan", "ill.": "illinois", "ind.": "indiana",
    "tenn.": "tennessee", "ark.": "arkansas", "colo.": "colorado", "ariz.": "arizona", "wash.": "washington", "caro.": "carolina",
    "conn.": "connecticut", "mo.": "missouri", "la.": "louisiana", "miss.": "mississippi", "ala.": "alabama", "val.": "valley",
    "col.": "college", "so.": "southern", "mass.": "massachusetts", "tex.": "texas", "okla.": "oklahoma", "minn.": "minnesota",
    "wis.": "wisconsin", "neb.": "nebraska", "ore.": "oregon", "nev.": "nevada", "va.": "virginia", "pa.": "pennsylvania",
    "n.c.": "north carolina", "s.c.": "south carolina", "n.j.": "new jersey", "n.y.": "new york", "md.": "maryland",
    "del.": "delaware", "me.": "maine", "vt.": "vermont", "n.h.": "new hampshire", "r.i.": "rhode island", "w.va.": "west virginia",
    "nw.": "northwestern", "cent.": "central", "int'l": "international", "intl.": "international",
}


def expand_ncaa(name: str) -> str:
    """'South Fla.' -> 'South Florida'; 'Charleston So.' -> 'Charleston Southern'. 'St.' handled in norm_school."""
    return " ".join(EXPAND.get(tok.lower(), tok) for tok in (name or "").split())


SAINT_NAMES = r"(john|joseph|mary|peter|francis|thomas|bonaventure|louis|leo|michael|anselm|ambrose|edward|xavier|cloud|olaf)"


def norm_school(s: str) -> str:
    s = common.strip_accents(expand_ncaa(s or "")).lower().replace("&", " and ").replace("’", "'")
    s = re.sub(r"\bst\.?\s+(?=" + SAINT_NAMES + r")", "saint ", s)      # St. John's -> saint john's
    s = re.sub(r"\bst\.", "state", s)                                    # Florida St. -> florida state
    s = re.sub(r"\bmt\.?\s+", "mount ", s)
    s = s.replace("univ.", "").replace("u.", "")
    s = re.sub(r"[().,'\-–/]", " ", s)
    # keep 'college' - it disambiguates Colorado vs Colorado College, Boston College, etc.
    s = re.sub(r"\b(university|univ|of|the|at|campus|u)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str) -> set[str]:
    return set(norm_school(s).split())


# ---------- domains ----------

@functools.lru_cache(maxsize=None)
def site_domain(url: str | None) -> str | None:
    """'https://www.GoArgos.com/sports/' -> 'goargos.com'; 'saintpeters.edu.' -> 'saintpeters.edu'."""
    if not url or not str(url).strip():
        return None
    u = re.sub(r"^[a-z][a-z0-9+.-]*://", "", str(url).strip().lower())
    host = re.split(r"[/?#]", u, maxsplit=1)[0].split("@")[-1].split(":")[0].rstrip(".")
    host = re.sub(r"^www\d?\.", "", host)
    return host or None


def registrable(domain: str | None) -> str | None:
    """Last two labels: 'bloomington.iu.edu' -> 'iu.edu'. Every US institution domain in the Directory
    and Scorecard is a two-label .edu/.com/.org/.net name, so no public-suffix list is needed."""
    return ".".join(domain.split(".")[-2:]) if domain and "." in domain else None


# ---------- the NCAA Directory ----------

def parse_directory(raw: list[dict], division: str) -> list[dict]:
    """The fields the registry uses, from one division's member list. Raises on a shape change rather
    than guessing: a row without orgId cannot be keyed."""
    if not isinstance(raw, list):
        raise common.FetchError(f"directory {division}: expected a list, got {type(raw).__name__}")
    rows = []
    for x in raw:
        if not isinstance(x, dict) or not isinstance(x.get("orgId"), int):
            raise common.FetchError(f"directory {division}: a row has no integer orgId: {str(x)[:120]}")
        roman = DIVISION_ROMAN[division]
        if x.get("divisionRoman") not in (None, roman):
            raise common.FetchError(f"directory {division}: orgId {x['orgId']} is listed as division {x.get('divisionRoman')}")
        rows.append({
            "orgId": x["orgId"], "division": division, "name": (x.get("nameOfficial") or "").strip(),
            "conference": (x.get("conferenceName") or "").strip() or None,
            "website": (x.get("webSiteUrl") or "").strip() or None, "athleticsUrl": (x.get("athleticWebUrl") or "").strip() or None,
            "state": ((x.get("memberOrgAddress") or {}).get("state") or "").strip().upper() or None,
            "academicYear": x.get("academicYear"),
        })
    return rows


def fetch_directory(registry: dict | None = None) -> dict[str, list[dict]]:
    """division -> parsed rows, for all three divisions. All three are always fetched, onboarded or
    not: a program that leaves D1 for D3 has to be found in D3 to be held rather than removed."""
    template = ((registry or {}).get("sources") or {}).get("ncaaDirectory", {}).get("memberList") or DIRECTORY_URL
    out = {}
    for division, roman in DIVISION_ROMAN.items():
        payload, _ = common.fetch_json(template.format(roman=roman), max_age_hours=24)
        out[division] = parse_directory(payload, division)
        common.log(f"registry: NCAA Directory {division}: {len(out[division])} women's soccer programs")
    return out


def conference_label(directory_name: str | None, division: str | None = LABELLED_DIVISION) -> str | None:
    """The label for a Directory conference name. Only a Division I row is looked up in
    CONFERENCE_LABELS; every other division keeps the Directory's own spelling (see the table)."""
    if not directory_name:
        return None
    if division != LABELLED_DIVISION:
        return directory_name
    return CONFERENCE_LABELS.get(directory_name, directory_name)


# ---------- College Scorecard ----------

# College Scorecard bulk CSV column -> the API field name the rest of the code uses
SCORECARD_COLS = {
    "UNITID": "id", "INSTNM": "school.name", "CITY": "school.city", "STABBR": "school.state", "ZIP": "school.zip",
    "INSTURL": "school.school_url", "LOCALE": "school.locale", "CCBASIC": "school.carnegie_basic", "CONTROL": "school.ownership",
    "RELAFFIL": "school.religious_affiliation", "LATITUDE": "location.lat", "LONGITUDE": "location.lon",
    "UGDS": "latest.student.size", "ADM_RATE": "latest.admissions.admission_rate.overall",
    "SATVR25": "latest.admissions.sat_scores.25th_percentile.critical_reading",
    "SATVR75": "latest.admissions.sat_scores.75th_percentile.critical_reading",
    "SATMT25": "latest.admissions.sat_scores.25th_percentile.math", "SATMT75": "latest.admissions.sat_scores.75th_percentile.math",
    "SAT_AVG": "latest.admissions.sat_scores.average.overall", "ACTCM25": "latest.admissions.act_scores.25th_percentile.cumulative",
    "ACTCM75": "latest.admissions.act_scores.75th_percentile.cumulative", "ACTCMMID": "latest.admissions.act_scores.midpoint.cumulative",
    "TUITIONFEE_IN": "latest.cost.tuition.in_state", "TUITIONFEE_OUT": "latest.cost.tuition.out_of_state",
    "COSTT4_A": "latest.cost.attendance.academic_year", "NPT4_PUB": "_npt_pub", "NPT4_PRIV": "_npt_priv",
    "C150_4": "latest.completion.completion_rate_4yr_150nt", "RET_FT4": "latest.student.retention_rate.four_year.full_time",
    "MD_EARN_WNE_P10": "latest.earnings.10_yrs_after_entry.median", "PREDDEG": "_preddeg", "HIGHDEG": "_highdeg",
}
INT_COLS = {"id", "school.locale", "school.carnegie_basic", "school.ownership", "school.religious_affiliation", "latest.student.size",
            "latest.admissions.sat_scores.25th_percentile.critical_reading", "latest.admissions.sat_scores.75th_percentile.critical_reading",
            "latest.admissions.sat_scores.25th_percentile.math", "latest.admissions.sat_scores.75th_percentile.math",
            "latest.admissions.sat_scores.average.overall", "latest.admissions.act_scores.25th_percentile.cumulative",
            "latest.admissions.act_scores.75th_percentile.cumulative", "latest.admissions.act_scores.midpoint.cumulative",
            "latest.cost.tuition.in_state", "latest.cost.tuition.out_of_state", "latest.cost.attendance.academic_year",
            "latest.earnings.10_yrs_after_entry.median", "_npt_pub", "_npt_priv", "_preddeg", "_highdeg"}


def _num(v: str, as_int: bool):
    if v in (None, "", "NULL", "PrivacySuppressed"):
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return int(f) if as_int else f


def fetch_scorecard_bulk(registry: dict | None = None) -> list[dict]:
    """Every predominantly-bachelor's institution from the Department of Education's bulk file
    (Most-Recent-Cohorts-Institution_<date>.zip, no API key), reshaped to API field names and
    cached in data/scorecard-bulk.json."""
    cached = common.read_json(SCORECARD_BULK)
    if cached and cached.get("results"):
        return cached["results"]
    import csv
    import io
    import zipfile
    page, _ = common.fetch_text("https://collegescorecard.ed.gov/data/", max_age_hours=24 * 30)
    m = re.search(r"https?://[^\"']+/Most-Recent-Cohorts-Institution_\d+\.zip", page)
    if not m:
        raise common.FetchError("scorecard bulk: download link not found on collegescorecard.ed.gov/data/")
    common.log(f"scorecard bulk: downloading {m.group(0)} (one-time, ~100 MB)")
    blob, _ = common.fetch(m.group(0), max_age_hours=24 * 365, timeout=600)
    results = []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        with zf.open(name) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))
            for row in reader:
                # any institution that awards bachelor's degrees (HIGHDEG >= 3)
                if row.get("HIGHDEG") not in ("3", "4"):
                    continue
                r = {}
                for col, key in SCORECARD_COLS.items():
                    v = row.get(col)
                    if key in ("school.name", "school.city", "school.state", "school.zip", "school.school_url"):
                        r[key] = v or None
                    else:
                        r[key] = _num(v, key in INT_COLS)
                r["latest.cost.avg_net_price.overall"] = r.pop("_npt_pub", None) or r.pop("_npt_priv", None)
                r.pop("_npt_priv", None)
                r.pop("_preddeg", None)
                r.pop("_highdeg", None)
                results.append(r)
    common.write_json(SCORECARD_BULK, {"fetchedAt": common.now_iso(), "source": m.group(0), "count": len(results), "results": results})
    common.log(f"scorecard bulk: {len(results)} bachelor's/graduate institutions cached")
    return results


def scorecard_by_domain(website: str | None, state: str | None, bulk: list[dict]) -> tuple[dict | None, str]:
    """The one Scorecard row for an institution website, in the same state. Exact host first, then
    the registrable domain. Returns (row, 'exact'|'registrable') or (None, reason). Never picks
    between two rows: `ewu.edu` is Eastern Washington (WA) and Edward Waters (FL), `fdu.edu` two
    New Jersey campuses, and choosing by size or name is how a card ends up with another school's
    facts."""
    d = site_domain(website)
    if not d:
        return None, "no-website"
    if not state:
        return None, "no-state"
    exact = [r for r in bulk if site_domain(r.get("school.school_url")) == d and r.get("school.state") == state]
    if len(exact) == 1:
        return exact[0], "exact"
    if exact:
        return None, "ambiguous:" + ",".join(str(r.get("id")) for r in exact)
    base = registrable(d)
    loose = [r for r in bulk if base and registrable(site_domain(r.get("school.school_url"))) == base
             and r.get("school.state") == state]
    if len(loose) == 1:
        return loose[0], "registrable"
    if loose:
        return None, "ambiguous:" + ",".join(str(r.get("id")) for r in loose)
    return None, "none"


def contested_scorecard_ids(rows: list[dict], bulk: list[dict], registry: dict | None = None) -> dict[int, list[str]]:
    """Scorecard rows that more than one program would claim: unitId -> the names claiming it.

    scorecard_by_domain() refuses to pick between two Scorecard rows for one program. This is the
    other direction, and the Directory produces it: a merged university keeps one Scorecard row while
    the Directory still lists each campus, all on the parent's domain. Bloomsburg and Mansfield both
    resolve to Commonwealth University of Pennsylvania (Bloomsburg PA), and PennWest California and
    PennWest Clarion both to Pennsylvania Western University (California PA) -- so one campus of each
    pair would take the other's city, coordinates and time zone. A contested row is used by nobody:
    the fields stay null and the report names it for review (issue #94)."""
    claims: dict[int, list[str]] = collections.defaultdict(list)
    for row in rows:
        sc, _ = scorecard_by_domain(row["website"], row["state"], bulk)
        if sc and sc.get("id") is not None:
            claims[sc["id"]].append(row["name"])
    for p in list((registry or {}).get("programs") or []) + list((registry or {}).get("heldPrograms") or []):
        unit = (p.get("ids") or {}).get("scorecardUnitId")
        if unit in claims:
            claims[unit].append(f"{p['slug']} (already in the registry)")
    return {unit: names for unit, names in claims.items() if len(names) > 1}


# ---------- identity ----------

def _program_state(program: dict, bulk_by_id: dict) -> str | None:
    st = (program.get("location") or {}).get("state")
    if st:
        return st
    sc = bulk_by_id.get((program.get("ids") or {}).get("scorecardUnitId"))
    return sc.get("school.state") if sc else None


def resolve_identity(program: dict, rows_by_org: dict[int, dict], bulk_by_id: dict) -> tuple[int | None, str, str]:
    """(orgId or None, status, evidence) for one registry program.

    status: 'keyed' (ids.ncaaOrgId present and listed), 'keyed-unlisted' (ids.ncaaOrgId present, in no
    list), 'agreed' (every signal agrees on one row), 'reviewed' (REVIEWED_ORG_IDS), 'reviewed-unlisted'
    (REVIEWED_NOT_LISTED), or 'unresolved'."""
    ids = program.get("ids") or {}
    slug = program.get("slug")
    org = ids.get("ncaaOrgId")
    if isinstance(org, int):
        return (org, "keyed", "ids.ncaaOrgId") if org in rows_by_org else (org, "keyed-unlisted", "ids.ncaaOrgId is in no list")
    state = _program_state(program, bulk_by_id)
    sc = bulk_by_id.get(ids.get("scorecardUnitId"))
    web = site_domain(sc.get("school.school_url")) if sc else None
    ath = site_domain((program.get("athletics") or {}).get("baseUrl"))
    by_web = {o for o, r in rows_by_org.items() if web and site_domain(r["website"]) == web and r["state"] == state}
    by_ath = {o for o, r in rows_by_org.items() if ath and site_domain(r["athleticsUrl"]) == ath and r["state"] == state}
    signals = [s for s in (by_web if web else None, by_ath if ath else None) if s is not None]
    if state and len(signals) == 2 and len(by_web) == 1 and by_web == by_ath:
        return next(iter(by_web)), "agreed", f"state {state}, website {web}, athletics {ath}"
    if slug in REVIEWED_ORG_IDS:
        org, why = REVIEWED_ORG_IDS[slug]
        row = rows_by_org.get(org)
        if row is None:
            return None, "unresolved", f"reviewed orgId {org} is in no list"
        if state and row["state"] != state:
            return None, "unresolved", f"reviewed orgId {org} is in {row['state']}, the program in {state}"
        return org, "reviewed", why
    if slug in REVIEWED_NOT_LISTED:
        if by_web or by_ath:
            return None, "unresolved", f"reviewed as not listed, but rows {sorted(by_web | by_ath)} now match"
        return None, "reviewed-unlisted", REVIEWED_NOT_LISTED[slug]
    return None, "unresolved", (f"state {state}, website {web} -> {sorted(by_web)}, athletics {ath} -> {sorted(by_ath)}")


# ---------- membership ----------

def staged_divisions(registry: dict) -> list[str]:
    """registry.stagedDivisions: divisions whose programs are IN the registry but are not published --
    entries built ahead of onboarding so the list, the slugs and the joins can be reviewed, and so
    collection can start, before the division itself is onboarded (issue #94, Division II).

    Explicit policy data, like onboardedDivisions, and for the same reason: onboarding a division is
    then a one-line move from one list to the other, reviewed in a diff. A staged entry is one whose
    division is in stagedDivisions; the `onboarded` flag is not part of that test, on either side of
    it. build.published_programs() publishes an entry only when it is `onboarded` AND its division is
    in onboardedDivisions, so a staged entry stays unpublished whatever its `onboarded` flag says --
    collection (`onboarded: true`, sources kept fresh) can run well ahead of onboarding, which is the
    whole point of staging a division. A division cannot be in both lists: that would leave it unclear
    whether its programs are published, and membership policy is exactly what must not be ambiguous
    (#100)."""
    staged = registry.get("stagedDivisions") or []
    if not isinstance(staged, list) or any(d not in DIVISION_ROMAN for d in staged) or len(staged) != len(set(staged)):
        raise ValueError(f"registry.stagedDivisions must be a list of distinct divisions drawn from "
                         f"{sorted(DIVISION_ROMAN)}, got {staged!r}")
    both = sorted(set(staged) & set(registry.get("onboardedDivisions") or []))
    if both:
        raise ValueError(f"division(s) {both} are in both onboardedDivisions and stagedDivisions; a division is "
                         f"either published or staged, not both. Onboarding removes it from stagedDivisions.")
    return list(staged)


def apply_membership(registry: dict, directory: dict[str, list[dict]], bulk: list[dict], *, today: str,
                     new_entries: dict[int, dict] | None = None, max_departure_share: float = MAX_DEPARTURE_SHARE,
                     timezone_lookup=None) -> dict:
    """Apply the Directory lists and the membership policy to `registry` in place. Pure: no network,
    no file access. Returns the membership part of the build report.

    `new_entries`: orgId -> a fully built registry entry, for Directory rows in an onboarded or staged
    division that no registry entry holds (see new_program_entry). A row with none is reported, not added."""
    onboarded = registry.get("onboardedDivisions")
    if not isinstance(onboarded, list) or not onboarded or any(d not in DIVISION_ROMAN for d in onboarded):
        raise ValueError(f"registry.onboardedDivisions must be a non-empty list drawn from {sorted(DIVISION_ROMAN)}, got {onboarded!r}")
    staged = staged_divisions(registry)
    rows_by_org: dict[int, dict] = {}
    for division, rows in directory.items():
        for r in rows:
            if r["orgId"] in rows_by_org:
                raise ValueError(f"orgId {r['orgId']} is listed in both {rows_by_org[r['orgId']]['division']} and {division}")
            rows_by_org[r["orgId"]] = r
    bulk_by_id = {r.get("id"): r for r in bulk}
    new_entries = new_entries or {}
    rep = {"onboardedDivisions": list(onboarded), "stagedDivisions": list(staged),
           "directoryCounts": {d: len(rows) for d, rows in directory.items()},
           "identity": collections.Counter(), "unresolved": [], "reviewed": [], "duplicateOrgId": [], "staged": [],
           "reclassified": [], "held": [], "returned": [], "added": [], "notAdded": [], "conferenceChanged": [],
           "conferenceUnlabelled": [], "stateDisagreement": [], "scorecardDomainDisagreement": [],
           "timezoneFilled": [], "timezoneDisagreement": [], "slugs": {}}

    # work on copies: a build that raises (the departure guard below) must leave `registry` untouched
    current = copy.deepcopy(list(registry.get("programs") or []))
    held_before = copy.deepcopy(list(registry.get("heldPrograms") or []))
    entries = [(p, False) for p in current] + [(p, True) for p in held_before]
    resolved = []
    for p, was_held in entries:
        org, status, why = resolve_identity(p, rows_by_org, bulk_by_id)
        rep["identity"][status] += 1
        if status == "unresolved":
            rep["unresolved"].append({"slug": p["slug"], "held": was_held, "evidence": why})
        elif status in ("reviewed", "reviewed-unlisted"):
            rep["reviewed"].append({"slug": p["slug"], "status": status, "orgId": org, "evidence": why})
        resolved.append([p, was_held, org, status, why])
    # one orgId, one program: two entries claiming the same row are both left untouched
    claims = collections.defaultdict(list)
    for item in resolved:
        if item[2] is not None and item[3] in ("keyed", "agreed", "reviewed"):
            claims[item[2]].append(item)
    for org, items in claims.items():
        if len(items) > 1:
            rep["duplicateOrgId"].append({"orgId": org, "slugs": [i[0]["slug"] for i in items]})
            for i in items:
                rep["identity"][i[3]] -= 1
                rep["identity"]["unresolved"] += 1
                i[3], i[4] = "unresolved", f"orgId {org} is claimed by more than one entry"
                rep["unresolved"].append({"slug": i[0]["slug"], "held": i[1], "evidence": f"orgId {org} is claimed by more than one entry"})

    programs, held = [], []
    departures = 0
    for p, was_held, org, status, why in resolved:
        slug = p["slug"]
        if status == "unresolved":
            (held if was_held else programs).append(p)
            continue
        row = rows_by_org.get(org) if status in ("keyed", "agreed", "reviewed") else None
        # read before the Directory's division overwrites p["division"] below
        published_before = not was_held and bool(p.get("onboarded")) and p.get("division") in onboarded
        if row is not None:
            p.setdefault("ids", {})["ncaaOrgId"] = org
            state = _program_state(p, bulk_by_id)
            if state and row["state"] and state != row["state"]:
                rep["stateDisagreement"].append({"slug": slug, "orgId": org, "registry": state, "directory": row["state"]})
            sc, how = scorecard_by_domain(row["website"], row["state"], bulk)
            unit = (p.get("ids") or {}).get("scorecardUnitId")
            if sc and unit and sc.get("id") != unit:
                rep["scorecardDomainDisagreement"].append({"slug": slug, "registry": unit, "domainJoin": sc.get("id"), "how": how})
            if p.get("division") != row["division"]:
                rep["reclassified"].append({"slug": slug, "from": p.get("division"), "to": row["division"], "orgId": org})
                p["division"] = row["division"]
            label = conference_label(row["conference"], row["division"])
            if row["conference"] and row["division"] == LABELLED_DIVISION and row["conference"] not in CONFERENCE_LABELS:
                rep["conferenceUnlabelled"].append({"slug": slug, "directory": row["conference"]})
            if label and p.get("conference") != label:
                rep["conferenceChanged"].append({"slug": slug, "from": p.get("conference"), "to": label, "directory": row["conference"]})
                p["conference"] = label
        if row is not None and row["division"] in onboarded:
            if was_held:
                p.pop("hold", None)
                rep["returned"].append({"slug": slug, "division": row["division"]})
            programs.append(p)
            continue
        if row is not None and row["division"] in staged and not was_held and not published_before:
            # Staged: in the registry, never published, and its division is not onboarded yet. It
            # stays in `programs` as it is. heldPrograms is for a program the site HAS published and
            # no longer does -- holding one that was never published would say the site dropped it,
            # and would count it as a departure against the guard below.
            #
            # Staging is decided by the division, not by `onboarded` (issue #187). A collected staged
            # entry (`onboarded: true`, its batch run through `onboard`) is exactly as staged as an
            # uncollected one. Keying this on `not onboarded` held all 105 collected D2 entries on the
            # next build, which only the departure guard stopped. What is still held is a program the
            # site published before this build (onboarded, in an onboarded division) or one already
            # held, such as saint-francis: for those, a staged division is a real departure.
            rep["staged"].append({"slug": slug, "division": row["division"], "orgId": org})
            programs.append(p)
            continue
        hold = ({"reason": "division-not-onboarded", "division": row["division"], "orgId": org} if row is not None
                else {"reason": "not-in-directory", "division": None, "orgId": org, "evidence": why})
        previous = p.get("hold") or {}
        hold["since"] = previous.get("since") if previous.get("reason") == hold["reason"] else today
        p["hold"] = hold
        if not was_held:
            departures += 1
            rep["held"].append({"slug": slug, **hold})
        held.append(p)

    published_before = len(current)
    if published_before and departures > max_departure_share * published_before:
        raise RuntimeError(f"registry build would move {departures} of {published_before} entries out of registry.programs "
                           f"(limit {max_departure_share:.0%}); refusing to write. A failed or truncated Directory response "
                           f"looks exactly like this. Report so far: held {[h['slug'] for h in rep['held']]}")

    taken = {p["slug"] for p in programs} | {p["slug"] for p in held}
    held_orgs = {(p.get("ids") or {}).get("ncaaOrgId") for p in programs + held}
    for division in list(onboarded) + staged:
        for row in directory.get(division, []):
            if row["orgId"] in held_orgs:
                continue
            entry = new_entries.get(row["orgId"])
            if entry is not None and division in staged and entry.get("onboarded"):
                raise ValueError(f"new program {row['name']} (orgId {row['orgId']}) is in staged division {division} "
                                 f"and must be onboarded: false; a staged division publishes nothing")
            if rep["unresolved"]:
                # an unresolved entry may be this very row under an identity nobody has confirmed;
                # adding it would publish the school twice
                rep["notAdded"].append({"orgId": row["orgId"], "name": row["name"], "division": division,
                                        "reason": f"{len(rep['unresolved'])} registry entries have an unresolved identity"})
                continue
            if entry is None:
                rep["notAdded"].append({"orgId": row["orgId"], "name": row["name"], "division": division,
                                        "reason": "no entry was built for it (build limit, or it appeared after the fetch)"})
                continue
            if entry["slug"] in taken:
                raise ValueError(f"new program {row['name']} (orgId {row['orgId']}) was given slug {entry['slug']!r}, which is taken")
            taken.add(entry["slug"])
            programs.append(entry)
            rep["added"].append({"slug": entry["slug"], "orgId": row["orgId"], "name": row["name"], "division": division})

    # A null timezone is filled from the program's own coordinates. A stored one that disagrees is
    # reported and left alone: correcting existing values is a reviewed change, not a side effect.
    if timezone_lookup is not None:
        for p in programs + held:
            loc = p.get("location") or {}
            tz = timezone_lookup(loc.get("lat"), loc.get("lon"))
            if tz is None:
                continue
            if loc.get("timezone") is None:
                loc["timezone"] = tz
                rep["timezoneFilled"].append({"slug": p["slug"], "timezone": tz})
            elif loc["timezone"] != tz:
                rep["timezoneDisagreement"].append({"slug": p["slug"], "registry": loc["timezone"], "coordinates": tz})

    registry["programs"] = programs
    registry["heldPrograms"] = held
    rep["identity"] = {k: v for k, v in rep["identity"].items() if v}
    rep["slugs"] = {"published": sum(1 for p in programs if p.get("onboarded") and p.get("division") in onboarded),
                    "inPrograms": len(programs), "held": len(held),
                    # staged: every entry in programs whose division is staged, collected or not (#187);
                    # notOnboarded: every entry not through `onboard` yet, staged or in an onboarded division
                    "staged": sum(1 for p in programs if p.get("division") in staged),
                    "notOnboarded": sum(1 for p in programs if not p.get("onboarded"))}
    return rep


def missing_org_rows(registry: dict, directory: dict[str, list[dict]], bulk: list[dict],
                     divisions: list[str] | None = None) -> list[dict]:
    """Directory rows in an onboarded or staged division that no registry entry will hold after this
    build -- the programs new_program_entry must build. Same identity rules as apply_membership."""
    rows_by_org = {r["orgId"]: r for rows in directory.values() for r in rows}
    bulk_by_id = {r.get("id"): r for r in bulk}
    held = set()
    for p in list(registry.get("programs") or []) + list(registry.get("heldPrograms") or []):
        org, status, _ = resolve_identity(p, rows_by_org, bulk_by_id)
        if org is not None:
            held.add(org)
    if divisions is None:
        divisions = list(registry.get("onboardedDivisions") or []) + staged_divisions(registry)
    return [r for d in divisions for r in directory.get(d, []) if r["orgId"] not in held]


# Words dropped from an official name to get the short form a slug reads best as. "University" is a
# form-of-institution word that common usage drops ("Adams State University" is Adams State), and so
# are the connectors. "College" is NOT dropped: it is part of the name in common usage, and dropping
# it turns Boston College into "boston" and Georgia College into "georgia", which is both misleading
# and a collision with two different D1 schools. norm_school() keeps "college" for the same reason.
SLUG_DROP_WORDS = {"university", "universities", "the", "of", "at", "in"}


def qualifier_place(qualifier: str) -> str:
    """The slug of a Directory name qualifier that is a place other than a US state, or "" when it is a
    state ("South Carolina", "SC") or empty. "Providence" -> providence; "Brooklyn" -> brooklyn."""
    q = common.clean(qualifier or "")
    if not q or common.state_code(q) in common.US_STATES:
        return ""
    return common.slugify(q)


def slug_ladder(name: str, state: str | None, org_id: int, preferred: str | None = None) -> list[str]:
    """The slug candidates for a Directory row, best first. A slug is a permanent URL, so every rung
    is derived from the source row and nothing is invented (issue #94):

      1. the short form: the official name without a parenthetical qualifier, "University" and the
         connectors  -- "Adams State University" -> adams-state
      2. the full official name, minus the qualifier                  -- "Georgia College" -> georgia-college
         (this rung is what separates Georgia College from the University of Georgia, and Queens
         College from Queens University of Charlotte, without reaching for a state)
      3. the short form plus the state                                -- "Lincoln University" -> lincoln-mo
      4. the full name plus the state
      5. the short form plus the orgId -- always free, never expected

    When the Directory qualifies the name itself -- "Anderson University (South Carolina)", as all 15
    D2 and 5 D1 qualifiers and 41 of D3's 43 do -- the bare name is not offered at all and the ladder
    starts at the state.

    Two D3 qualifiers are cities, not states (issue #139): "Johnson & Wales University (Providence)"
    and "St. Joseph's University NY (Brooklyn)". A city qualifier names a campus, and campuses of one
    institution are usually in one state, so the state cannot be what separates them. For those the
    ladder starts at the qualifier itself -- johnson-wales-providence, st-josephs-ny-brooklyn -- and the
    state rungs follow. A state rung is never added to a form that already ends in that state, which
    is what produced st-josephs-ny-ny. Neither change alters the ladder of any D1 or D2 row. The source is saying the name alone does not identify the school, and the registry
    already says so too: `miami-fl` and `miami-oh`. It also keeps the slug stable across divisions,
    which matters because a slug is a permanent URL: Anderson (SC) is D2 and Anderson (IN) is D3, and
    without this the one built first would take `anderson` and the other `anderson-university`.

    Apostrophes close up rather than splitting, as the registry's own `st-johns` does, so
    "Saint Martin's University" is saint-martins and not saint-martin-s.

    `preferred` (the verified Wikipedia short name, when a list gives one) goes in front, which is
    how every D1 entry built since #107 was named.
    """
    name = common.strip_accents(name or "").replace("'", "").replace("’", "")
    qualifier = re.search(r"\(([^)]*)\)", name)
    qualified = bool(qualifier)
    plain = re.sub(r"\s*\([^)]*\)", " ", name).replace("&", "")
    full = common.slugify(plain)
    words = [w for w in re.split(r"[\s,–—-]+", plain) if w]
    short = common.slugify(" ".join(w for w in words if re.sub(r"[^a-z]", "", w.lower()) not in SLUG_DROP_WORDS))
    short = short or full or f"program-{org_id}"
    full = full or short
    st = (state or "").strip().lower()
    place = qualifier_place(qualifier.group(1)) if qualifier else ""
    placed = [f"{short}-{place}", f"{full}-{place}"] if place else []
    unqualified = [] if (qualified and st) else [short, full]

    def with_state(base: str) -> str | None:
        # "St. Joseph's University NY" already ends in its state; appending it again gave st-josephs-ny-ny (#139)
        if not st or base == st or base.endswith(f"-{st}"):
            return None
        return f"{base}-{st}"

    ladder = [common.slugify(preferred) if preferred else None, *placed, *unqualified,
              with_state(short), with_state(full), f"{short}-{org_id}"]
    out: list[str] = []
    for c in ladder:  # in order, without duplicates: "Wheaton College" makes rungs 1 and 2 the same
        if c and c not in out:
            out.append(c)
    return out


def reviewed_slug_pins(rows: list[dict], taken: set[str], table: dict[int, tuple[str, str]] | None = None) -> dict[int, str]:
    """orgId -> reviewed slug, for the rows in `rows` (Directory rows about to be added) that REVIEWED_SLUGS names.

    Raises ValueError, naming the override, when the table is unusable: a slug that is not lowercase words joined
    by single hyphens, one slug given to two orgIds, or -- for a row being added -- a slug an entry in `taken`
    already holds. An override for an orgId that is not among `rows` (the registry already holds it) is not
    applied and not checked against `taken`: its own entry holds that slug from the build that added it."""
    table = REVIEWED_SLUGS if table is None else table
    errors = []
    for org, value in sorted(table.items()):
        slug = value[0] if isinstance(value, (tuple, list)) and value else None
        if not isinstance(org, int) or not isinstance(slug, str) or not SLUG_SHAPE.match(slug):
            errors.append(f"orgId {org!r} -> {slug!r} is not a valid slug (lowercase words joined by single hyphens)")
    by_slug = collections.defaultdict(list)
    for org, value in table.items():
        if isinstance(value, (tuple, list)) and value:
            by_slug[value[0]].append(org)
    for slug, orgs in sorted(by_slug.items()):
        if len(orgs) > 1:
            errors.append(f"{slug!r} is given to more than one orgId: {sorted(orgs)}")
    adding = {r["orgId"]: r for r in rows}
    pins = {org: table[org][0] for org in sorted(table) if org in adding}
    for org, slug in pins.items():
        if slug in taken:
            errors.append(f"{slug!r} for {adding[org]['name']} (orgId {org}) is already held by a registry entry")
    if errors:
        raise ValueError("REVIEWED_SLUGS is not usable: " + "; ".join(errors))
    return pins


def name_new_programs(rows: list[dict], taken: set[str], preferred: dict[int, str] | None = None,
                      table: dict[int, tuple[str, str]] | None = None) -> dict[int, str]:
    """orgId -> slug for a batch of new Directory rows: a reviewed slug (REVIEWED_SLUGS) exactly as given, and the
    rest by assign_slugs() with those reviewed slugs counted as taken, so no ladder can reach one."""
    pins = reviewed_slug_pins(rows, taken, table)
    out = assign_slugs([r for r in rows if r["orgId"] not in pins], set(taken) | set(pins.values()), preferred)
    out.update(pins)
    return out


def new_slug(name: str, state: str | None, org_id: int, taken: set[str], preferred: str | None = None) -> str:
    """The first slug_ladder() rung that no registry entry (published or held) already uses."""
    for cand in slug_ladder(name, state, org_id, preferred):
        if cand not in taken:
            return cand
    raise ValueError(f"no free slug for {name} (orgId {org_id})")


def assign_slugs(rows: list[dict], taken: set[str], preferred: dict[int, str] | None = None) -> dict[int, str]:
    """orgId -> slug for a batch of Directory rows, none of them colliding with each other or with
    `taken`. Order-independent, unlike calling new_slug() row by row: when two new rows want the same
    rung, BOTH move down the ladder, so neither gets to be the plain name because it was processed
    first. A rung an existing entry holds also moves the new row, because a published slug is a URL
    that must not change (issue #100)."""
    preferred = preferred or {}
    ladders = {r["orgId"]: slug_ladder(r["name"], r["state"], r["orgId"], preferred.get(r["orgId"])) for r in rows}
    rung = {org: 0 for org in ladders}

    def pick(org):
        return ladders[org][min(rung[org], len(ladders[org]) - 1)]

    for _ in range(max((len(l) for l in ladders.values()), default=0) + 1):
        wanted = collections.Counter(pick(org) for org in ladders)
        moved = False
        for org in ladders:
            if rung[org] >= len(ladders[org]) - 1:
                continue  # the last rung carries the orgId and is free by construction
            if pick(org) in taken or wanted[pick(org)] > 1:
                rung[org] += 1
                moved = True
        if not moved:
            break
    out = {org: pick(org) for org in ladders}
    clash = [s for s, n in collections.Counter(out.values()).items() if n > 1] + sorted(set(out.values()) & taken)
    if clash:
        raise ValueError(f"slug assignment did not converge; still colliding: {sorted(set(clash))[:8]}")
    return out


# ---------- enrichment of a new program ----------

def fetch_wiki_list(division: str = "D1") -> list[dict]:
    url = WIKI_LIST.get(division)
    if not url:
        return []
    html, _ = common.fetch_text(url, max_age_hours=24 * 30)
    soup = BeautifulSoup(html, "html.parser")
    t = soup.find_all("table", "wikitable")[0]
    rows = []
    for tr in t.find_all("tr")[1:]:
        c = tr.find_all(["td", "th"])
        if len(c) < 6:
            continue

        def cell(i):
            return re.sub(r"\s*\[\s*\w+\s*\]", "", c[i].get_text(" ", strip=True)).strip()

        def link(i):
            a = c[i].find("a")
            return urllib.parse.unquote(a["href"].replace("./", "")) if a and a.get("href", "").startswith("./") else None

        rows.append({"institution": cell(0), "institutionArticle": link(0), "city": cell(1), "state": cell(2),
                     "type": cell(3), "nickname": cell(4), "athleticsArticle": link(4), "conference": cell(5)})
    return rows


def fetch_tds_teams() -> dict[str, dict]:
    out = {}
    for slug, cfid in TDS_CONFERENCES:
        url = f"https://www.topdrawersoccer.com/college-soccer/college-conferences/conference-details/women/{slug}/cfid-{cfid}"
        try:
            html, _ = common.fetch_text(url, max_age_hours=24 * 30)
        except common.FetchError as e:
            common.log(f"registry: tds conference {slug} failed: {e}")
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=re.compile(r"/college-soccer-details/women/([a-z0-9()'.-]+)/clgid-(\d+)")):
            m = re.search(r"/women/([a-z0-9-]+)/clgid-(\d+)", a["href"])
            name = a.get_text(" ", strip=True)
            if m and name and len(name) > 1:
                out[m.group(1)] = {"tdsSlug": m.group(1), "tdsClgId": int(m.group(2)), "tdsName": name, "tdsConf": slug}
    return out


def wiki_canonical(title: str) -> str | None:
    """Canonical article title (follows redirects), or None if the page does not exist."""
    url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title, safe="")
    try:
        body, meta = common.fetch(url, max_age_hours=24 * 90, allow_status=(200, 404))
    except common.FetchError:
        return None
    if meta.get("status") != 200:
        return None
    try:
        return json.loads(body.decode("utf-8", "replace")).get("title", title).replace(" ", "_")
    except ValueError:
        return title


def soccer_article_for(athletics_article: str | None) -> str | None:
    """The list's nickname link is either the athletics article ('Colorado_Buffaloes') or already
    the soccer article ('Florida_State_Seminoles_women's_soccer')."""
    if not athletics_article:
        return None
    if "soccer" in athletics_article.lower():
        t = wiki_canonical(athletics_article)
        return None if t and MENS_TITLE_RE.search(t) else t
    for suffix in ("_women's_soccer", "_soccer"):
        t = wiki_canonical(athletics_article + suffix)
        # #349: 'Old_Dominion_Monarchs_soccer' redirects to the men's team's article; following it published the
        # men's seasons as the women's (old-dominion, campbell, east-tennessee-state, manhattan; fixed in #346)
        if t and "soccer" in t.lower() and not MENS_TITLE_RE.search(t):
            return t
    return None


def _name_forms(name: str) -> set[str]:
    """Normalised forms of an official name: 'University of West Florida' -> {'west florida'};
    'College of Charleston (South Carolina)' also yields 'college charleston'."""
    forms = {norm_school(name)}
    forms.add(norm_school(re.sub(r"\s*\([^)]*\)\s*", " ", name)))
    return {f for f in forms if f}


def wiki_row_for(row: dict, wiki: list[dict]) -> tuple[dict | None, str]:
    """The Wikipedia list row for a Directory row: exact normalised name (institution cell or its
    article title) AND the same state, and only one such row. Otherwise (None, reason)."""
    forms = _name_forms(row["name"])
    hits = []
    for w in wiki:
        names = {norm_school(w["institution"])}
        if w.get("institutionArticle"):
            names.add(norm_school(re.sub(r"\s*\(.*?\)\s*$", "", w["institutionArticle"].replace("_", " "))))
        if forms & names:
            hits.append(w)
    same_state = [w for w in hits if common.state_code(w.get("state")) == row["state"]]
    if len(same_state) == 1:
        return same_state[0], "name+state"
    if len(same_state) > 1:
        return None, f"ambiguous: {len(same_state)} rows"
    if hits:
        return None, "name matches, state disagrees: " + ", ".join(f"{w['institution']} ({w.get('state')})" for w in hits)
    return None, "no row"


def tds_team_for(row: dict, label: str | None, wiki_row: dict | None, tds: dict[str, dict]) -> tuple[dict | None, str]:
    """The TopDrawerSoccer team for a Directory row: exact normalised name (official name, or the
    verified Wikipedia short name) AND TDS files the team under the same conference; unique."""
    forms = _name_forms(row["name"]) | ({norm_school(wiki_row["institution"])} if wiki_row else set())
    # D1 labels only (#199): D2's "Independent" is the same string as D1's and is not TDS's D1 independents
    want_conf = LABEL_TDS_CONFERENCE.get(label or "") if row.get("division") == LABELLED_DIVISION else None
    hits = [t for t in tds.values() if norm_school(t["tdsName"]) in forms]
    agree = [t for t in hits if want_conf and t["tdsConf"] == want_conf]
    if len(agree) == 1:
        return agree[0], "name+conference"
    if len(agree) > 1:
        return None, f"ambiguous: {[t['tdsSlug'] for t in agree]}"
    if hits:
        return None, "name matches, conference disagrees: " + ", ".join(f"{t['tdsSlug']} ({t['tdsConf']})" for t in hits)
    return None, "no team"


def new_program_entry(row: dict, *, bulk: list[dict], wiki: list[dict], tds: dict[str, dict], taken: set[str],
                      article_lookup=soccer_article_for, timezone_lookup=timezone_at,
                      slug: str | None = None, contested: dict[int, list[str]] | None = None) -> tuple[dict, dict]:
    """(registry entry, what each source established) for a Directory row the registry does not hold.
    Every field is from a source or null; nothing is supplied from memory.

    `slug`: the slug assign_slugs() gave this row when a whole batch is being named at once. Without
    one the row is named on its own, against `taken`."""
    label = conference_label(row["conference"], row["division"])
    sc, sc_how = scorecard_by_domain(row["website"], row["state"], bulk)
    if sc and (contested or {}).get(sc.get("id")):
        # another program's domain resolves to this same Scorecard row; see contested_scorecard_ids
        sc, sc_how = None, f"contested:{sc['id']} claimed by {len(contested[sc['id']])} programs"
    w, w_how = wiki_row_for(row, wiki)
    t, t_how = tds_team_for(row, label, w, tds)
    article = article_lookup(w.get("athleticsArticle")) if w else None
    ath_host = site_domain(row["athleticsUrl"])
    raw_ath = (row["athleticsUrl"] or "").strip()
    base_url = None
    if ath_host:
        host = re.split(r"[/?#]", re.sub(r"^[a-z][a-z0-9+.-]*://", "", raw_ath.lower()), maxsplit=1)[0].rstrip(".")
        base_url = "https://" + host
    short = w["institution"] if w else None
    if slug is None:
        slug = new_slug(row["name"], row["state"], row["orgId"], taken, preferred=short)
    elif slug in taken:
        raise ValueError(f"slug {slug!r} for {row['name']} (orgId {row['orgId']}) is already taken")
    city = sc.get("school.city") if sc else None
    entry = {
        "slug": slug, "onboarded": False, "name": row["name"], "shortName": short, "nickname": w["nickname"] if w else None,
        "division": row["division"], "conference": label, "colors": None,
        "athletics": {"platform": "auto", "baseUrl": base_url, "sportPath": "/sports/womens-soccer"},
        "ids": {"ncaaOrgId": row["orgId"], "scorecardUnitId": sc.get("id") if sc else None,
                "tdsClgId": t["tdsClgId"] if t else None, "tdsSlug": t["tdsSlug"] if t else None,
                "wikipedia": article, "ncaaName": None, "ncaaSlug": None, "rpiHistoryName": None},
        "social": {"x": None, "instagram": None},
        "location": {"city": city, "state": row["state"], "lat": sc.get("location.lat") if sc else None,
                     "lon": sc.get("location.lon") if sc else None,
                     "timezone": timezone_lookup(sc.get("location.lat"), sc.get("location.lon")) if sc else None},
    }
    evidence = {"slug": slug, "orgId": row["orgId"], "name": row["name"], "scorecard": sc_how, "wikipediaList": w_how,
                "tds": t_how, "wikipediaArticle": bool(article), "athleticsUrl": bool(base_url),
                "null": sorted(k for k, v in {**{f"ids.{k}": v for k, v in entry["ids"].items()},
                                              **{f"location.{k}": v for k, v in entry["location"].items()},
                                              "shortName": short, "nickname": entry["nickname"], "colors": None,
                                              "athletics.baseUrl": base_url}.items() if v is None)}
    if w and city and common.clean(w.get("city") or "").lower() != city.lower():
        evidence["cityDisagreement"] = {"wikipedia": w.get("city"), "scorecard": city}
    return entry, evidence


# ---------- build ----------

def build(registry: dict, *, limit: int | None = None) -> dict:
    """Fetch the Directory (3 requests), build entries for new programs in onboarded and staged
    divisions, then apply the membership policy to a freshly locked registry and write it with the
    report. `limit` caps how many new programs are built in one run (the rest are reported as notAdded).

    A staged division (registry.stagedDivisions) is built exactly like an onboarded one except that
    nothing is published: every new entry is onboarded: false, so no collector and no page follows from
    this run."""
    if not registry.get("onboardedDivisions"):
        raise ValueError("registry.onboardedDivisions is missing; it names the divisions the site publishes")
    staged = staged_divisions(registry)
    directory = fetch_directory(registry)
    years = sorted({r["academicYear"] for rows in directory.values() for r in rows})
    bulk = fetch_scorecard_bulk(registry)
    missing = missing_org_rows(registry, directory, bulk)
    if limit is not None:
        missing = missing[:limit]
    new_entries, evidence, contested = {}, [], {}
    if missing:
        wiki = {d: fetch_wiki_list(d) for d in sorted({r["division"] for r in missing})}
        tds = fetch_tds_teams() if any(r["division"] == "D1" for r in missing) else {}
        taken = {p["slug"] for p in list(registry.get("programs") or []) + list(registry.get("heldPrograms") or [])}
        # name the whole batch at once, so two new programs wanting one slug both move down the ladder
        preferred = {r["orgId"]: w["institution"] for r in missing
                     for w, _ in [wiki_row_for(r, wiki.get(r["division"], []))] if w}
        # a reviewed slug (REVIEWED_SLUGS, issue #190) is taken as given; everything else takes its ladder
        slugs = name_new_programs(missing, taken, preferred)
        contested = contested_scorecard_ids(missing, bulk, registry)
        for unit, names in sorted(contested.items()):
            common.log(f"registry: Scorecard row {unit} is claimed by {len(names)} programs ({', '.join(names)}); "
                       f"none of them takes it")
        for row in missing:
            entry, ev = new_program_entry(row, bulk=bulk, wiki=wiki.get(row["division"], []), tds=tds, taken=taken,
                                          slug=slugs[row["orgId"]], contested=contested)
            taken.add(entry["slug"])
            new_entries[row["orgId"]] = entry
            evidence.append(ev)
            common.log(f"registry: new {row['division']} program {row['name']} -> {entry['slug']} "
                       f"(scorecard {ev['scorecard']}, wikipedia {ev['wikipediaList']}, tds {ev['tds']})"
                       + (" [staged, not published]" if row["division"] in staged else ""))
    holder = {}

    def mutate(reg):
        holder["membership"] = apply_membership(reg, directory, bulk, today=common.today(), new_entries=new_entries,
                                                timezone_lookup=timezone_at)
        holder["division"] = {p["slug"]: p.get("division")
                              for p in list(reg.get("programs") or []) + list(reg.get("heldPrograms") or [])}

    common.update_registry(mutate)
    m = holder["membership"]
    unmatched = collections.defaultdict(list)
    for ev in evidence:
        for field in ev["null"]:
            unmatched[field].append(ev["slug"])
    report = {"builtAt": common.now_iso(), "source": DIRECTORY_URL, "academicYears": years, **m,
              "contestedScorecardRows": {str(u): names for u, names in sorted(contested.items())},
              "newPrograms": evidence, "unmatched": dict(unmatched),
              "lowConfidence": [{"slug": u["slug"], "evidence": u["evidence"]} for u in m["unresolved"]]}
    report["counts"] = {k: len(v) for k, v in report["unmatched"].items()}
    by_name = {r["name"]: r["division"] for r in missing}
    for division, rep in division_reports(report, holder["division"], by_name).items():
        common.write_json(report_path(division), rep)
    common.log(f"registry: {m['slugs']['published']} published, {m['slugs']['staged']} staged ({', '.join(staged) or '-'}), "
               f"{m['slugs']['held']} held; identity {m['identity']}; "
               f"added {len(m['added'])}, held now {len(m['held'])}, returned {len(m['returned'])}, reclassified "
               f"{len(m['reclassified'])}, conference changes {len(m['conferenceChanged'])}, unresolved {len(m['unresolved'])}")
    return report


# ---------- post-build fixes ----------

WIKI_SEARCH = "https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=6&srsearch={q}"
SEASON_ARTICLE_RE = re.compile(r"^\d{4}")


def _wiki_search(q: str) -> list[str]:
    url = WIKI_SEARCH.format(q=urllib.parse.quote(q, safe=""))
    try:
        payload, _ = common.fetch_json(url, max_age_hours=24 * 30)
    except common.FetchError:
        return []
    return [hit.get("title", "") for hit in payload.get("query", {}).get("search", [])]


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", common.strip_accents(t.replace("_", " ")).lower()).strip()


def _accept_title(title: str, short: str, nick: str = "") -> bool:
    """Only the title forms '<Short> <Nickname> women's soccer' / '<Short> women's soccer' for THIS
    school ('Iowa' must not accept 'Iowa State Cyclones women's soccer', 'Illinois State' must not
    accept 'Northern Illinois Huskies women's soccer')."""
    if SEASON_ARTICLE_RE.match(title):
        return False
    low = _norm_title(title)
    wanted = {_norm_title(f"{short} women's soccer")}
    if nick:
        wanted.add(_norm_title(f"{short} {nick} women's soccer"))
    return low in wanted


def find_wiki_article(program: dict) -> tuple[str | None, list[str]]:
    """Best guess at the program's Wikipedia team article, verified to exist. Direct title probes
    first ('Kentucky Wildcats women's soccer'), then the search API; a probe that redirects to the
    athletics article ('Kentucky Wildcats') means there is no dedicated article.
    Returns (canonical title or None, rejected-but-plausible candidates)."""
    short = program.get("shortName") or program["name"]
    nick = program.get("nickname") or ""
    rejected: list[str] = []
    probes = [f"{short} {nick} women's soccer", f"{short} women's soccer"] if nick else [f"{short} women's soccer"]
    for title in probes:
        canon = wiki_canonical(title.replace(" ", "_"))
        if canon and _accept_title(canon, short, nick):
            return canon, rejected
    seen = []
    for q in (f"{short} {nick} women's soccer", f"{short} women's soccer"):
        for title in _wiki_search(q):
            if title in seen:
                continue
            seen.append(title)
            if _accept_title(title, short, nick):
                canon = wiki_canonical(title.replace(" ", "_"))
                if canon and _accept_title(canon, short, nick):
                    return canon, rejected
            elif _norm_title(title).endswith("women s soccer") and not SEASON_ARTICLE_RE.match(title):
                rejected.append(title)
    return None, rejected


def fix_wiki(registry: dict, *, apply: bool = False, slugs: list[str] | None = None) -> dict:
    """Fill ids.wikipedia for onboarded programs that have none. Dry run by default; --apply
    writes the registry (locked). Prints found / none tables."""
    # a program whose registry records that it has no women's article (ids.wikipediaNone, #349) is looked up
    # again only when named with a slug
    targets = [p for p in registry["programs"] if (slugs and p["slug"] in slugs)
               or (not slugs and p.get("onboarded") and not (p.get("ids") or {}).get("wikipedia")
                   and not (p.get("ids") or {}).get("wikipediaNone"))]
    found, none = {}, []
    for p in targets:
        title, others = find_wiki_article(p)
        if title and MENS_TITLE_RE.search(title):  # never a men's team's article, whatever the lookup returns
            others, title = [title, *others], None
        if title:
            found[p["slug"]] = title
            common.log(f"wiki: {p['slug']:24} -> {title}" + (f"   (also: {', '.join(others)})" if others else ""))
        else:
            none.append(p["slug"])
            common.log(f"wiki: {p['slug']:24} -> (none)" + (f"   candidates rejected: {', '.join(others)}" if others else ""))
    print(f"\nfound {len(found)} of {len(targets)}; none: {', '.join(none) or '-'}")
    if apply and found:
        def mutate(reg):
            for p in reg["programs"]:
                if p["slug"] in found:
                    p.setdefault("ids", {})["wikipedia"] = found[p["slug"]]
        common.update_registry(mutate)
        print(f"registry updated: ids.wikipedia set for {len(found)} programs")
    elif found:
        print("dry run - pass --apply to write the registry")
    return {"found": found, "none": none}


# ---------- team colours (Wikipedia Module:College color/data) ----------

COLOR_MODULE_URL = "https://en.wikipedia.org/w/index.php?title=Module:College_color/data&action=raw"
# One entry per line:  ["Key"] = {"RRGGBB", "RRGGBB", ..., name1="crimson", cite="..."},  -- optional comment
#                      ["Alias"] = "Canonical Key",
_COLOR_ENTRY = re.compile(r'^\s*\["(?P<key>[^"]+)"\]\s*=\s*(?:"(?P<alias>[^"]+)"|\{(?P<body>.*)\})\s*,?\s*(?:--.*)?$')
_HEX6 = re.compile(r'"([0-9A-Fa-f]{6})"')
_BODY_TAIL = re.compile(r"\b(?:name\d|cite|order)\s*=")  # cite text can contain stray hex-looking strings
COLOR_OVERRIDES = {  # registry slug -> module key where no name form matches
    "loyola-chicago": "Loyola Ramblers", "long-beach-state": "Long Beach State Beach",
    "mississippi-val": "Mississippi Valley State Delta Devils", "saint-francis": "Saint Francis Red Flash",
    "ohio-university": "Ohio Bobcats", "st-thomas": "St. Thomas (Minnesota) Tommies",
}


def fetch_color_table() -> tuple[dict[str, list[str]], dict[str, str]]:
    """(entries: key -> ['#RRGGBB', ...], aliases: key -> canonical key) from the Lua data module."""
    text, _ = common.fetch_text(COLOR_MODULE_URL, max_age_hours=24 * 30)
    entries: dict[str, list[str]] = {}
    aliases: dict[str, str] = {}
    for line in text.splitlines():
        m = _COLOR_ENTRY.match(line)
        if not m:
            continue
        if m.group("alias"):
            aliases[m.group("key")] = m.group("alias")
            continue
        head = _BODY_TAIL.split(m.group("body"))[0]
        hexes = ["#" + h.upper() for h in _HEX6.findall(head)]
        if hexes:
            entries[m.group("key")] = hexes
    if len(entries) < 500:
        raise common.FetchError(f"college colour table parsed only {len(entries)} entries (format change?)")
    common.log(f"colors: {len(entries)} entries, {len(aliases)} aliases from Wikipedia")
    return entries, aliases


def _color_norm(s: str) -> str:
    s = common.strip_accents(s or "").lower().replace("’", "'").replace("–", "-").replace("—", "-")
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\bst\b", "saint", s)
    return re.sub(r"\s+", " ", s).strip()


def _resolve_color_key(key: str | None, entries: dict, aliases: dict) -> str | None:
    for _ in range(4):
        if not key:
            return None
        if key in entries:
            return key
        key = aliases.get(key)
    return None


def _registry_colors(hexes: list[str]) -> list[str]:
    """Wikipedia stores {primary, contrast-text colour, secondary, ...}; the registry keeps [primary, secondary]."""
    if len(hexes) >= 3:
        return [hexes[0], hexes[2]]
    return hexes[:2]


def match_colors(program: dict, entries: dict, aliases: dict, by_norm: dict[str, str]) -> tuple[str | None, str]:
    slug = program["slug"]
    short = program.get("shortName") or program["name"]
    nick = program.get("nickname") or ""
    bare_nick = re.sub(r"^Lady\s+", "", nick)

    def lookup(text: str, how: str):
        k = _resolve_color_key(text, entries, aliases)
        if k:
            return k, how
        k = _resolve_color_key(by_norm.get(_color_norm(text)), entries, aliases)
        return (k, how + "-norm") if k else (None, "")

    if slug in COLOR_OVERRIDES:
        k = _resolve_color_key(COLOR_OVERRIDES[slug], entries, aliases)
        if k:
            return k, "override"
    candidates = []
    if nick:
        candidates.append((f"{short} {nick}", "exact"))
        if bare_nick != nick:
            candidates.append((f"{short} {bare_nick}", "no-lady"))
        candidates.append((f"{program['name']} {nick}", "fullname"))
    for text, how in candidates:
        k, h = lookup(text, how)
        if k:
            return k, h
    # unique prefix (+ suffix) scan over normalised keys
    ns, nn = _color_norm(short), _color_norm(bare_nick)
    hits = [k for n, k in by_norm.items() if n.startswith(ns + " ") and (not nn or n.endswith(" " + nn))]
    hits = sorted({_resolve_color_key(k, entries, aliases) for k in hits} - {None})
    if len(hits) == 1:
        return hits[0], "prefix"
    return None, ""


def fill_colors(registry: dict, *, apply: bool = False, slugs: list[str] | None = None) -> dict:
    """Fill `colors` for programs that have none from Wikipedia's college colour table. Dry run by
    default; --apply writes the registry (locked). Hand-set colours are never overwritten."""
    entries, aliases = fetch_color_table()
    by_norm: dict[str, str] = {}
    for k in list(entries) + list(aliases):
        by_norm.setdefault(_color_norm(k), k)
    targets = [p for p in registry["programs"] if not slugs or p["slug"] in slugs]
    found, none, kept = {}, [], []
    for p in targets:
        if p.get("colors"):
            kept.append(p["slug"])
            common.log(f"colors: {p['slug']:24} -> (kept) {p['colors']}  hand-set")
            continue
        key, how = match_colors(p, entries, aliases, by_norm)
        if key:
            found[p["slug"]] = _registry_colors(entries[key])
            common.log(f"colors: {p['slug']:24} -> {key:40} {' '.join(found[p['slug']])}   ({how})")
        else:
            none.append(p["slug"])
            common.log(f"colors: {p['slug']:24} -> (none)")
    print(f"\nmatched {len(found)} of {len(targets) - len(kept)} needing colours; kept {len(kept)} hand-set; "
          f"unmatched: {', '.join(none) or '-'}")
    if apply and found:
        def mutate(reg):
            for p in reg["programs"]:
                if p["slug"] in found and not p.get("colors"):
                    p["colors"] = found[p["slug"]]
        common.update_registry(mutate)
        print(f"registry updated: colors set for {len(found)} programs")
    elif found:
        print("dry run - pass --apply to write the registry")
    return {"found": found, "none": none, "kept": kept}
