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

Existing entries are preserved: a build writes only `division`, `conference` and `ids.ncaaOrgId`
on a program that stays. data/registry-build-report.json records every decision.

    python collegedash.py registry build        # writes registry + report
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
REPORT_PATH = os.path.join(common.DATA_DIR, "registry-build-report.json")

# A build that would take more than this share of the published programs out of `programs` raises
# instead of writing. A truncated or failed Directory response looks exactly like a mass departure.
MAX_DEPARTURE_SHARE = 0.05

# Directory conferenceName (whitespace-trimmed) -> the label the registry and the conference pills use.
# Every D1 label that existed before #100 is kept for the conference it named. Three are new with
# the 2026-27 lists: Pac-12, UAC and Metro (the Directory's name for the 13 former MAAC members).
# A name missing here is published as the Directory spells it and listed in the report.
CONFERENCE_LABELS = {
    "America East Conference": "America East", "American Conference": "American", "Atlantic 10 Conference": "Atlantic 10",
    "Atlantic Coast Conference": "ACC", "Atlantic Sun Conference": "ASUN", "BIG EAST Conference": "Big East",
    "Big 12 Conference": "Big 12", "Big Sky Conference": "Big Sky", "Big South Conference": "Big South",
    "Big Ten Conference": "Big Ten", "Big West Conference": "Big West", "Coastal Athletic Association": "CAA",
    "Conference USA": "CUSA", "Horizon League": "Horizon", "Independent": "DI Independent", "The Ivy League": "Ivy League",
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
    "Horizon": "horizon-league", "DI Independent": "independent", "Ivy League": "ivy-league",
    "Metro": "metro-atlantic-athletic-conference", "MAC": "mid-american", "MVC": "missouri-valley",
    "Mountain West": "mountain-west", "NEC": "northeast", "OVC": "ohio-valley", "Pac-12": "pacific-12",
    "Patriot": "patriot-league", "SEC": "sec", "SoCon": "southern", "Southland": "southland",
    "SWAC": "southwestern-athletic", "Summit League": "summit-league", "Sun Belt": "sun-belt", "UAC": "united-athletic-conference",
    "WCC": "west-coast",
}

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

# Time zones come from the coordinates, never from the state (issue #110). The state table this
# replaces put Knoxville, Chattanooga and Johnson City on Central time, Murray, Bowling Green,
# Evansville and Valparaiso on Eastern, El Paso on Central and Moscow (Idaho) on Mountain, and it had
# to leave Pensacola null because Florida spans two zones.
#
# Source: the timezone-boundary-builder polygons (built from OpenStreetMap, ODbL), looked up offline by
# the `timezonefinder` package, which bundles them. The coordinates are the College Scorecard row's.
_TZ_FINDER = None


def timezone_at(lat, lon) -> str | None:
    """The IANA zone whose boundary contains (lat, lon), or None without coordinates or for a point in
    no zone polygon. Raises ImportError if timezonefinder is not installed: a missing library must not
    look like a program with no time zone."""
    global _TZ_FINDER
    if lat is None or lon is None:
        return None
    if _TZ_FINDER is None:
        from timezonefinder import TimezoneFinder
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


def conference_label(directory_name: str | None) -> str | None:
    if not directory_name:
        return None
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

def apply_membership(registry: dict, directory: dict[str, list[dict]], bulk: list[dict], *, today: str,
                     new_entries: dict[int, dict] | None = None, max_departure_share: float = MAX_DEPARTURE_SHARE,
                     timezone_lookup=None) -> dict:
    """Apply the Directory lists and the membership policy to `registry` in place. Pure: no network,
    no file access. Returns the membership part of the build report.

    `new_entries`: orgId -> a fully built registry entry, for Directory rows in an onboarded division
    that no registry entry holds (see new_program_entry). A row with none is reported, not added."""
    onboarded = registry.get("onboardedDivisions")
    if not isinstance(onboarded, list) or not onboarded or any(d not in DIVISION_ROMAN for d in onboarded):
        raise ValueError(f"registry.onboardedDivisions must be a non-empty list drawn from {sorted(DIVISION_ROMAN)}, got {onboarded!r}")
    rows_by_org: dict[int, dict] = {}
    for division, rows in directory.items():
        for r in rows:
            if r["orgId"] in rows_by_org:
                raise ValueError(f"orgId {r['orgId']} is listed in both {rows_by_org[r['orgId']]['division']} and {division}")
            rows_by_org[r["orgId"]] = r
    bulk_by_id = {r.get("id"): r for r in bulk}
    new_entries = new_entries or {}
    rep = {"onboardedDivisions": list(onboarded), "directoryCounts": {d: len(rows) for d, rows in directory.items()},
           "identity": collections.Counter(), "unresolved": [], "reviewed": [], "duplicateOrgId": [],
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
            label = conference_label(row["conference"])
            if row["conference"] and row["conference"] not in CONFERENCE_LABELS:
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
        raise RuntimeError(f"registry build would take {departures} of {published_before} programs out of the published set "
                           f"(limit {max_departure_share:.0%}); refusing to write. A failed or truncated Directory response "
                           f"looks exactly like this. Report so far: held {[h['slug'] for h in rep['held']]}")

    taken = {p["slug"] for p in programs} | {p["slug"] for p in held}
    held_orgs = {(p.get("ids") or {}).get("ncaaOrgId") for p in programs + held}
    for division in onboarded:
        for row in directory.get(division, []):
            if row["orgId"] in held_orgs:
                continue
            entry = new_entries.get(row["orgId"])
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
    rep["slugs"] = {"published": len(programs), "held": len(held)}
    return rep


def missing_org_rows(registry: dict, directory: dict[str, list[dict]], bulk: list[dict]) -> list[dict]:
    """Directory rows in an onboarded division that no registry entry will hold after this build --
    the programs new_program_entry must build. Uses the same identity rules as apply_membership."""
    rows_by_org = {r["orgId"]: r for rows in directory.values() for r in rows}
    bulk_by_id = {r.get("id"): r for r in bulk}
    held = set()
    for p in list(registry.get("programs") or []) + list(registry.get("heldPrograms") or []):
        org, status, _ = resolve_identity(p, rows_by_org, bulk_by_id)
        if org is not None:
            held.add(org)
    return [r for d in registry.get("onboardedDivisions") or [] for r in directory.get(d, []) if r["orgId"] not in held]


def new_slug(name: str, state: str | None, org_id: int, taken: set[str]) -> str:
    """slugify(name); on a collision '<slug>-<state>'; then '<slug>-<orgId>'. Every candidate comes
    from the source row, and a slug already in the registry (published or held) is never reused."""
    base = common.slugify(name) or f"program-{org_id}"
    for cand in (base, f"{base}-{state.lower()}" if state else None, f"{base}-{org_id}"):
        if cand and cand not in taken:
            return cand
    raise ValueError(f"no free slug for {name} (orgId {org_id})")


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
        return wiki_canonical(athletics_article)
    for suffix in ("_women's_soccer", "_soccer"):
        t = wiki_canonical(athletics_article + suffix)
        if t and "soccer" in t.lower():
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
    want_conf = LABEL_TDS_CONFERENCE.get(label or "")
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
                      article_lookup=soccer_article_for, timezone_lookup=timezone_at) -> tuple[dict, dict]:
    """(registry entry, what each source established) for a Directory row the registry does not hold.
    Every field is from a source or null; nothing is supplied from memory."""
    label = conference_label(row["conference"])
    sc, sc_how = scorecard_by_domain(row["website"], row["state"], bulk)
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
    slug = new_slug(short or row["name"], row["state"], row["orgId"], taken)
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
    """Fetch the Directory (3 requests), build entries for new programs in onboarded divisions, then
    apply the membership policy to a freshly locked registry and write it with the report.
    `limit` caps how many new programs are built in one run (the rest are reported as notAdded)."""
    if not registry.get("onboardedDivisions"):
        raise ValueError("registry.onboardedDivisions is missing; it names the divisions the site publishes")
    directory = fetch_directory(registry)
    years = sorted({r["academicYear"] for rows in directory.values() for r in rows})
    bulk = fetch_scorecard_bulk(registry)
    missing = missing_org_rows(registry, directory, bulk)
    if limit is not None:
        missing = missing[:limit]
    new_entries, evidence = {}, []
    if missing:
        wiki = {d: fetch_wiki_list(d) for d in sorted({r["division"] for r in missing})}
        tds = fetch_tds_teams() if any(r["division"] == "D1" for r in missing) else {}
        taken = {p["slug"] for p in list(registry.get("programs") or []) + list(registry.get("heldPrograms") or [])}
        for row in missing:
            entry, ev = new_program_entry(row, bulk=bulk, wiki=wiki.get(row["division"], []), tds=tds, taken=taken)
            taken.add(entry["slug"])
            new_entries[row["orgId"]] = entry
            evidence.append(ev)
            common.log(f"registry: new {row['division']} program {row['name']} -> {entry['slug']} "
                       f"(scorecard {ev['scorecard']}, wikipedia {ev['wikipediaList']}, tds {ev['tds']})")
    holder = {}

    def mutate(reg):
        holder["membership"] = apply_membership(reg, directory, bulk, today=common.today(), new_entries=new_entries,
                                                timezone_lookup=timezone_at)

    common.update_registry(mutate)
    m = holder["membership"]
    unmatched = collections.defaultdict(list)
    for ev in evidence:
        for field in ev["null"]:
            unmatched[field].append(ev["slug"])
    report = {"builtAt": common.now_iso(), "source": DIRECTORY_URL, "academicYears": years, **m,
              "newPrograms": evidence, "unmatched": dict(unmatched),
              "lowConfidence": [{"slug": u["slug"], "evidence": u["evidence"]} for u in m["unresolved"]]}
    report["counts"] = {k: len(v) for k, v in report["unmatched"].items()}
    common.write_json(REPORT_PATH, report)
    common.log(f"registry: {m['slugs']['published']} published, {m['slugs']['held']} held; identity {m['identity']}; "
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
    targets = [p for p in registry["programs"] if (slugs and p["slug"] in slugs)
               or (not slugs and p.get("onboarded") and not (p.get("ids") or {}).get("wikipedia"))]
    found, none = {}, []
    for p in targets:
        title, others = find_wiki_article(p)
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
