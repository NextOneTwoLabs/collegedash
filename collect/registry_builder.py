"""
Build registry entries for every NCAA Division I women's soccer program.

Master list: the NCAA weekly RPI table (public/data/rpi/current.json, 350 teams with the NCAA's
short names and conferences). Each team is then matched to:
  - Wikipedia's "List of NCAA Division I women's soccer programs" (city, state, nickname, articles)
  - TopDrawerSoccer conference pages (tdsSlug, tdsClgId)
  - NCAA.com schools index + school page (athletics website)
  - College Scorecard (unit id, coordinates) via ~20 paged API calls cached in data/scorecard-bulk.json
  - Chris Henderson's RPI archive team names (public/data/rpi/2024.json)

Matching is by normalised name with a small override table; everything unmatched is written to
data/registry-build-report.json for review. Existing registry entries are preserved.

    python collegedash.py registry build        # writes registry + report
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse

from bs4 import BeautifulSoup

from . import common

TDS_CONFERENCES = [
    ("america-east", 1), ("american-athletic", 1047), ("asun", 22), ("atlantic-10", 2), ("atlantic-coast", 3),
    ("big-12", 23), ("big-east", 5), ("big-sky", 24), ("big-south", 6), ("big-ten", 7), ("big-west", 8),
    ("coastal-athletic-association", 9), ("conference-usa", 10), ("horizon-league", 11), ("independent", 47),
    ("ivy-league", 12), ("metro-atlantic-athletic-conference", 13), ("mid-american", 14), ("missouri-valley", 15),
    ("mountain-west", 25), ("northeast", 17), ("ohio-valley", 26), ("pacific-12", 27), ("patriot-league", 18),
    ("sec", 1044), ("southern", 19), ("southland", 29), ("southwestern-athletic", 30), ("summit-league", 31),
    ("sun-belt", 32), ("united-athletic-conference", 1056), ("west-coast", 21),
]
WIKI_LIST = "https://en.wikipedia.org/api/rest_v1/page/html/List_of_NCAA_Division_I_women%27s_soccer_programs"
NCAA_INDEX = "https://www.ncaa.com/schools-index"
SCORECARD_BULK = os.path.join(common.DATA_DIR, "scorecard-bulk.json")
REPORT_PATH = os.path.join(common.DATA_DIR, "registry-build-report.json")

STATE_TZ = {
    "CA": "America/Los_Angeles", "WA": "America/Los_Angeles", "OR": "America/Los_Angeles", "NV": "America/Los_Angeles",
    "AZ": "America/Phoenix", "UT": "America/Denver", "CO": "America/Denver", "NM": "America/Denver", "ID": "America/Boise",
    "MT": "America/Denver", "WY": "America/Denver", "HI": "Pacific/Honolulu", "AK": "America/Anchorage",
    "TX": "America/Chicago", "OK": "America/Chicago", "KS": "America/Chicago", "NE": "America/Chicago", "SD": "America/Chicago",
    "ND": "America/Chicago", "MN": "America/Chicago", "IA": "America/Chicago", "MO": "America/Chicago", "AR": "America/Chicago",
    "LA": "America/Chicago", "MS": "America/Chicago", "AL": "America/Chicago", "WI": "America/Chicago", "IL": "America/Chicago",
    "TN": "America/Chicago",
}

# NCAA short name -> per-source targets that no normalisation can reach.
#   wiki: institution as in the Wikipedia list; tds: TopDrawerSoccer slug; hist: RPI-archive team name;
#   site: athletics website; scorecard: Scorecard school name
ALIASES = {
    "UConn": {"wiki": "UConn", "hist": "ConnecticutU"}, "Ole Miss": {"wiki": "Ole Miss", "tds": "mississippi", "hist": "MississippiU"},
    "UCF": {"wiki": "UCF", "tds": "ucf"}, "ULM": {"wiki": "Louisiana–Monroe", "tds": "louisiana-monroe", "hist": "LouisianaMonroe"},
    "Miami (FL)": {"wiki": "Miami (FL)", "tds": "miami"}, "Miami (OH)": {"wiki": "Miami (OH)", "tds": "miami-oh"},
    "South Fla.": {"wiki": "South Florida", "tds": "south-florida", "hist": "SouthFlorida"},
    "ETSU": {"wiki": "East Tennessee State", "tds": "east-tennessee-state", "hist": "EastTennesseeState"},
    "FIU": {"wiki": "FIU", "tds": "fiu"}, "FGCU": {"wiki": "FGCU", "tds": "fgcu", "hist": "FloridaGulfCoast"},
    "Col. of Charleston": {"wiki": "Charleston", "tds": "charleston", "hist": "CollegeofCharleston"},
    "CSU Bakersfield": {"wiki": "Cal State Bakersfield", "tds": "cal-state-bakersfield", "hist": "CalStateBakersfield"},
    "CSUN": {"wiki": "Cal State Northridge", "tds": "csun", "hist": "CalStateNorthridge"},
    "Massachusetts": {"wiki": "UMass", "tds": "massachusetts", "hist": "Massachusetts"},
    "UMass Lowell": {"wiki": "UMass Lowell", "tds": "massachusetts-lowell"},
    "Penn": {"wiki": "Penn", "tds": "penn", "hist": "PennsylvaniaU"}, "Loyola Maryland": {"wiki": "Loyola (MD)", "hist": "LoyolaMD"},
    "LMU (CA)": {"wiki": "Loyola Marymount", "tds": "loyola-marymount", "hist": "LoyolaMarymount"},
    "Loyola Chicago": {"tds": "loyola-chicago"}, "Grambling": {"wiki": "Grambling State", "tds": "grambling-state", "hist": "Grambling"},
    "NIU": {"wiki": "Northern Illinois", "tds": "northern-illinois", "hist": "NorthernIllinois"},
    "UNI": {"wiki": "Northern Iowa", "tds": "northern-iowa", "hist": "NorthernIowa"},
    "UIW": {"wiki": "Incarnate Word", "tds": "incarnate-word", "hist": "IncarnateWord"},
    "UTRGV": {"wiki": "UT Rio Grande Valley", "tds": "utrgv", "hist": "TexasRGV"}, "UTSA": {"wiki": "UTSA", "tds": "utsa"},
    "UTEP": {"wiki": "UTEP", "tds": "utep"}, "LIU": {"wiki": "LIU", "tds": "liu", "hist": "LongIsland"},
    "Queens (NC)": {"wiki": "Queens", "tds": "queens", "hist": "Queens"},
    "IU Indy": {"wiki": "IU Indianapolis", "tds": "iu-indianapolis", "hist": "IUPUI"},
    "Prairie View": {"wiki": "Prairie View A&M", "tds": "prairie-view-am", "hist": "PrairieViewA&M"},
    "Saint Francis": {"wiki": "Saint Francis", "tds": "saint-francis", "hist": "StFrancis"},
    "Milwaukee": {"tds": "wisconsin-milwaukee"}, "Green Bay": {"tds": "wisconsin-green-bay", "site": "https://greenbayphoenix.com"},
    "Chattanooga": {"tds": "ut-chattanooga"}, "Siena": {"tds": "siena-college"}, "Sam Houston": {"tds": "sam-houston-state"},
    "San Diego St.": {"tds": "san-diego-state"},
    "Southern Miss.": {"tds": "southern-mississippi", "hist": "SouthernMississippi"}, "McNeese": {"tds": "mcneese-state", "hist": "McNeeseState"},
    "SIUE": {"wiki": "SIU Edwardsville", "tds": "siue", "hist": "SIUEdwardsville"}, "Southern Ill.": {"hist": "SIUCarbondale"},
    "St. Thomas (MN)": {"wiki": "St. Thomas", "tds": "st-thomas", "hist": "StThomas"}, "Saint Louis": {"tds": "saint-louis", "hist": "StLouis"},
    "Saint Mary's (CA)": {"wiki": "Saint Mary's", "tds": "saint-marys", "hist": "StMarys"},
    "St. John's (NY)": {"tds": "st-johns", "hist": "StJohns"},
    "Saint Joseph's": {"tds": "saint-josephs", "hist": "StJosephs"}, "Saint Peter's": {"tds": "saint-peters", "hist": "StPeters"},
    "Mount St. Mary's": {"tds": "mount-st-marys", "hist": "MountStMary"}, "St. Bonaventure": {"tds": "st-bonaventure", "hist": "StBonaventure"},
    "NC State": {"wiki": "NC State", "tds": "nc-state", "hist": "NCState"},
    "App State": {"wiki": "Appalachian State", "tds": "appalachian-state", "hist": "AppalachianState"},
    "Army West Point": {"wiki": "Army", "tds": "army", "hist": "Army"},
    "UNCW": {"wiki": "UNC Wilmington", "tds": "unc-wilmington", "hist": "UNCWilmington"},
    "UIC": {"wiki": "UIC", "tds": "uic", "hist": "IllinoisChicago"}, "Kansas City": {"wiki": "Kansas City", "tds": "kansas-city", "hist": "UMKC"},
    "USC Upstate": {"wiki": "USC Upstate", "tds": "usc-upstate", "hist": "USCUpstate"},
    "SFA": {"wiki": "Stephen F. Austin", "tds": "stephen-f-austin", "hist": "StephenFAustin"},
    "Little Rock": {"wiki": "Little Rock", "tds": "little-rock", "hist": "UALR"}, "Omaha": {"wiki": "Omaha", "tds": "omaha", "hist": "UNOmaha"},
    "FDU": {"wiki": "Fairleigh Dickinson", "tds": "fairleigh-dickinson", "hist": "FairleighDickinson"},
    "Southeastern La.": {"hist": "SELouisiana"}, "UT Martin": {"wiki": "UT Martin", "tds": "ut-martin", "hist": "TennesseeMartin"},
    "UAlbany": {"wiki": "Albany", "tds": "albany", "hist": "Albany"}, "Purdue Fort Wayne": {"hist": "IPFW"},
    "Houston Christian": {"hist": "HoustonBaptist"}, "East Texas A&M": {"tds": "east-texas-am", "hist": "TexasCommerce"},
    "A&M-Corpus Christi": {"wiki": "Texas A&M–Corpus Christi", "tds": "texas-am-corpus-christi", "hist": "TexasCorpusChristi"},
    "Louisiana": {"wiki": "Louisiana", "tds": "louisiana", "hist": "LouisianaLafayette"},
    "Southern U.": {"wiki": "Southern", "tds": "southern", "hist": "SouthernU"},
    "Mississippi Val.": {"wiki": "Mississippi Valley State", "tds": "mississippi-valley-state", "hist": "MississippiValley"},
    "Alcorn": {"wiki": "Alcorn State", "tds": "alcorn-state"}, "Detroit Mercy": {"tds": "detroit-mercy"}, "Seattle U": {"wiki": "Seattle", "tds": "seattle"},
    "California Baptist": {"tds": "cal-baptist"}, "Boston U.": {"wiki": "Boston University", "hist": "BostonU"},
    "The Citadel": {"wiki": "The Citadel", "tds": "the-citadel", "scorecard": "Citadel Military College of South Carolina"},
    "Virginia Tech": {"scorecard": "Virginia Polytechnic Institute and State University"},
    "Columbia": {"scorecard": "Columbia University in the City of New York"},
    "Hawaii": {"wiki": "Hawaii", "scorecard": "University of Hawaii at Manoa"}, "Weber St.": {"scorecard": "Weber State University"},
    "Southern Ind.": {"scorecard": "University of Southern Indiana", "hist": "SouthernIndiana"},
    "BYU": {"site": "https://byucougars.com"}, "Elon": {"site": "https://elonphoenix.com"}, "North Dakota": {"site": "https://fightinghawks.com"},
    "UIW": {"wiki": "Incarnate Word", "tds": "incarnate-word", "hist": "IncarnateWord", "site": "https://uiwcardinals.com"},
    "FGCU": {"wiki": "Florida Gulf Coast", "tds": "fgcu", "hist": "FloridaGulfCoast", "scorecard": "Florida Gulf Coast University"},
    "Central Conn. St.": {"wiki": "Central Connecticut", "tds": "central-connecticut", "hist": "CentralConnecticut", "scorecard": "Central Connecticut State University"},
    "St. John's (NY)": {"wiki": "St. John's", "tds": "st-johns", "hist": "StJohns", "scorecard": "St. John's University-New York"},
    "Southern Miss.": {"wiki": "Southern Miss", "tds": "southern-mississippi", "hist": "SouthernMississippi", "scorecard": "University of Southern Mississippi"},
    "Mississippi Val.": {"hist": "MississippiValley", "scorecard": "Mississippi Valley State University"},
    "Saint Francis": {"hist": "StFrancis", "scorecard": "Saint Francis University", "site": "https://sfuathletics.com"},
    "Ark.-Pine Bluff": {"wiki": "Arkansas\u2013Pine Bluff", "tds": "arkansas-pine-bluff", "hist": "ArkansasPineBluff", "scorecard": "University of Arkansas at Pine Bluff"},
    "Miami (OH)": {"wiki": "Miami (OH)", "scorecard": "Miami University-Oxford"},
    "Southern U.": {"wiki": "Southern", "hist": "SouthernU", "scorecard": "Southern University and A & M College"},
    "UConn": {"wiki": "UConn", "tds": "connecticut", "hist": "ConnecticutU", "site": "https://uconnhuskies.com"},
    "FIU": {"wiki": "FIU", "tds": "florida-international"},
    "UMass Lowell": {"wiki": "UMass Lowell", "tds": "massachusetts-lowell", "hist": "UMassLowell"},
    "Tarleton St.": {"hist": "Tarleton"}, "Morehead St.": {"hist": "Morehead"}, "Nicholls": {"hist": "NichollsState", "site": "https://geauxcolonels.com"},
    "Detroit Mercy": {"tds": "detroit-mercy", "hist": "Detroit"},
    "Penn St.": {"site": "https://gopsusports.com"}, "LMU (CA)": {"wiki": "Loyola Marymount", "tds": "loyola-marymount", "hist": "LoyolaMarymount", "site": "https://lmulions.com"},
    "East Texas A&M": {"tds": "east-texas-am", "hist": "TexasCommerce", "site": "https://lionathletics.com"},
    "Lamar University": {"site": "https://lamarcardinals.com"}, "Oregon St.": {"site": "https://osubeavers.com"},
}


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
    s = common.strip_accents(expand_ncaa(s or "")).lower().replace("&", " and ").replace("\u2019", "'")
    s = re.sub(r"\bst\.?\s+(?=" + SAINT_NAMES + r")", "saint ", s)      # St. John's -> saint john's
    s = re.sub(r"\bst\.", "state", s)                                    # Florida St. -> florida state
    s = re.sub(r"\bmt\.?\s+", "mount ", s)
    s = s.replace("univ.", "").replace("u.", "")
    s = re.sub(r"[().,'\-\u2013/]", " ", s)
    # keep 'college' - it disambiguates Colorado vs Colorado College, Boston College, etc.
    s = re.sub(r"\b(university|univ|of|the|at|campus|u)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def split_camel(s: str) -> str:
    """'NorthCarolinaU' -> 'North Carolina U', 'UCSantaBarbara' -> 'UC Santa Barbara'."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", s or "")


def tokens(s: str) -> set[str]:
    return set(norm_school(s).split())


def best_match(name: str, candidates: dict[str, dict], *, min_score: float = 0.8) -> tuple[str | None, float]:
    """candidates: {normalised name: row}. Exact normalised match, then compact (space-less) match,
    then token overlap above min_score."""
    n = norm_school(name)
    if n in candidates:
        return n, 1.0
    nc = n.replace(" ", "")
    for cn in candidates:
        if cn.replace(" ", "") == nc:
            return cn, 0.95
    t = set(n.split())
    best, score = None, 0.0
    for cn in candidates:
        ct = set(cn.split())
        if not t or not ct:
            continue
        j = len(t & ct) / len(t | ct)
        if j > score:
            best, score = cn, j
    return (best, score) if score >= min_score else (None, score)


# ---------- sources ----------

def load_ncaa_master() -> list[dict]:
    cur = common.read_json(os.path.join(common.RPI_OUT_DIR, "current.json"), {}) or {}
    return [{"ncaaName": t["school"], "conference": t["conference"]} for t in cur.get("teams", [])]


def fetch_wiki_list() -> list[dict]:
    html, _ = common.fetch_text(WIKI_LIST, max_age_hours=24 * 30)
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
        for a in soup.find_all("a", href=re.compile(r"/college-soccer-details/women/([a-z0-9-]+)/clgid-(\d+)")):
            m = re.search(r"/women/([a-z0-9-]+)/clgid-(\d+)", a["href"])
            name = a.get_text(" ", strip=True)
            if name and len(name) > 1:
                out[m.group(1)] = {"tdsSlug": m.group(1), "tdsClgId": int(m.group(2)), "tdsName": name, "tdsConf": slug}
    return out


def fetch_ncaa_index() -> dict[str, str]:
    """NCAA short name -> ncaa.com school slug"""
    out = {}
    for p in range(0, 24):
        url = f"{NCAA_INDEX}/{p}" if p else NCAA_INDEX
        try:
            html, _ = common.fetch_text(url, max_age_hours=24 * 30)
        except common.FetchError:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=re.compile(r"^/schools/[a-z0-9-]+$")):
            nm = a.get_text(" ", strip=True)
            if nm:
                out.setdefault(nm, a["href"].split("/")[-1])
    return out


def fetch_athletics_url(ncaa_slug: str) -> str | None:
    try:
        html, _ = common.fetch_text(f"https://www.ncaa.com/schools/{ncaa_slug}", max_age_hours=24 * 90)
    except common.FetchError:
        return None
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select(".layout-content a[href^='http'], a[href^='http'][target='_blank']"):
        href = a["href"].strip()
        if re.search(r"ncaa\.com|facebook|twitter|x\.com|instagram|youtube|tiktok|amazon|apple|google", href):
            continue
        if re.match(r"https?://[a-z0-9.-]+\.(com|edu|org|net)/?$", href):
            return href.rstrip("/")
    return None


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


def fetch_scorecard_bulk(registry: dict) -> list[dict]:
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


def match_scorecard(wiki_row: dict, bulk: list[dict]) -> dict | None:
    state = common.state_code(wiki_row.get("state"))
    if not state and wiki_row.get("state"):
        state = None
    full = (wiki_row.get("institutionArticle") or wiki_row["institution"]).replace("_", " ")
    full = re.sub(r"\s*\(.*?\)\s*$", "", full)
    want = tokens(full) | tokens(wiki_row["institution"])
    best, score = None, 0.0
    for r in bulk:
        if state and r.get("school.state") != state:
            continue
        have = tokens(r.get("school.name", ""))
        if not have:
            continue
        j = len(want & have) / len(want | have)
        # exact normalised full-name match wins outright
        if norm_school(r.get("school.name", "")) == norm_school(full):
            j = 1.0
        if j > score or (j == score and best and (r.get("latest.student.size") or 0) > (best.get("latest.student.size") or 0)):
            best, score = r, j
    return best if score >= 0.5 else None


# ---------- build ----------

CONF_WORDS = {
    "ACC": {"atlantic-coast", "acc"}, "Big Ten": {"big-ten", "bigten"}, "SEC": {"sec"}, "Big 12": {"big-12", "big12", "bigtwelve"},
    "Big East": {"big-east", "bigeast"}, "American": {"american-athletic", "american"}, "Independent": {"independent"}, "Sun Belt": {"sun-belt", "sunbelt"},
    "MAC": {"mid-american", "mac"}, "WCC": {"west-coast", "westcoast"}, "Ivy League": {"ivy-league", "ivy"},
    "Mountain West": {"mountain-west", "mountainwest"}, "Big West": {"big-west", "bigwest"}, "A-10": {"atlantic-10", "atlantic10", "atlanticten"},
    "CAA": {"coastal-athletic-association", "caa", "colonial"}, "C-USA": {"conference-usa", "cusa"}, "Horizon": {"horizon-league", "horizon"},
    "MAAC": {"metro-atlantic-athletic-conference", "maac", "metroatlantic"}, "MVC": {"missouri-valley", "mvc"}, "NEC": {"northeast", "nec"},
    "OVC": {"ohio-valley", "ovc"}, "Patriot": {"patriot-league", "patriot"}, "SoCon": {"southern", "socon"},
    "Southland": {"southland"}, "SWAC": {"southwestern-athletic", "swac", "southwestern"}, "Summit League": {"summit-league", "summit"},
    "UAC": {"united-athletic-conference", "uac", "wac", "asun", "atlanticsun"}, "ASUN": {"asun", "uac", "atlanticsun", "wac"}, "Big Sky": {"big-sky", "bigsky"},
    "Big South": {"big-south", "bigsouth"}, "America East": {"america-east", "americaeast"}, "Pac-12": {"pacific-12", "pac-12", "pactwelve"},
}


def conf_consistent(ncaa_conf: str, other: str | None) -> bool | None:
    """Loose check that a matched source row sits in the same conference; None when unknown."""
    if not other:
        return None
    words = CONF_WORDS.get(ncaa_conf)
    if not words:
        return None
    o = other.lower().replace(" ", "").replace("-", "")
    return any(w.replace("-", "") in o or o in w.replace("-", "") for w in words)


def wiki_infobox_site(article: str | None) -> str | None:
    """Athletics website from the athletics-program article infobox (e.g. 'BYU_Cougars')."""
    if not article:
        return None
    url = "https://en.wikipedia.org/api/rest_v1/page/html/" + urllib.parse.quote(article, safe="")
    try:
        html, _ = common.fetch_text(url, max_age_hours=24 * 90)
    except common.FetchError:
        return None
    soup = BeautifulSoup(html, "html.parser")
    ib = soup.find("table", class_=re.compile(r"\binfobox\b"))
    if not ib:
        return None
    for tr in ib.find_all("tr"):
        th = tr.find("th")
        if th and "website" in th.get_text(" ", strip=True).lower():
            a = tr.find("a", href=True)
            if a and a["href"].startswith("http"):
                m = re.match(r"(https?://[^/]+)", a["href"])
                return m.group(1).replace("http://", "https://") if m else None
    return None


def build(registry: dict, *, limit: int | None = None) -> dict:
    master = load_ncaa_master()
    if not master:
        raise RuntimeError("no NCAA RPI table; run: python collegedash.py rpi current")
    wiki = fetch_wiki_list()
    tds = fetch_tds_teams()
    ncaa_index = fetch_ncaa_index()
    bulk = fetch_scorecard_bulk(registry)
    hist = common.read_json(os.path.join(common.RPI_OUT_DIR, "2024.json"), {}) or {}
    hist_rows = {t["team"]: t for t in hist.get("teams", [])}
    hist_by_norm = {norm_school(split_camel(t)): t for t in hist_rows}
    wiki_by_norm = {norm_school(r["institution"]): r for r in wiki}
    wiki_by_inst = {r["institution"]: r for r in wiki}
    tds_by_norm = {norm_school(r["tdsName"]): r for r in tds.values()}
    bulk_by_name = {r.get("school.name"): r for r in bulk}
    existing = {p["slug"]: p for p in registry["programs"]}
    existing_ncaa = {p["ids"].get("ncaaName"): p for p in registry["programs"]}
    report = {"builtAt": common.now_iso(), "total": len(master),
              "unmatched": {"wikipedia": [], "tds": [], "athleticsUrl": [], "scorecard": [], "rpiHistory": [], "wikiArticle": []},
              "lowConfidence": [], "conferenceMismatch": []}
    programs, used_slugs = [], set()
    for i, m in enumerate(master):
        if limit and i >= limit:
            break
        name, conf = m["ncaaName"], m["conference"]
        if name in existing_ncaa:
            programs.append(existing_ncaa[name])
            used_slugs.add(existing_ncaa[name]["slug"])
            continue
        al = ALIASES.get(name, {})
        # --- Wikipedia list row
        w = wiki_by_inst.get(al["wiki"]) if al.get("wiki") else None
        ws = 1.0 if w else 0.0
        if not w:
            wn, ws = best_match(name, wiki_by_norm)
            w = wiki_by_norm.get(wn) if wn else None
        # --- TopDrawerSoccer
        t = tds.get(al["tds"]) if al.get("tds") else None
        ts = 1.0 if t else 0.0
        if not t:
            tn, ts = best_match(name, tds_by_norm)
            t = tds_by_norm.get(tn) if tn else None
        # --- RPI archive name
        hist_name = al.get("hist") if al.get("hist") in hist_rows else None
        if not hist_name:
            hn, hs = best_match(name, {k: {"team": v} for k, v in hist_by_norm.items()}, min_score=0.66)
            hist_name = hist_by_norm.get(hn) if hn else None
        # consistency checks against the NCAA conference
        for label, other in (("rpiHistory", hist_name and hist_rows[hist_name].get("conference")),):
            ok = conf_consistent(conf, other)
            if ok is False:
                report["conferenceMismatch"].append({"ncaaName": name, "conference": conf, "source": label, "matched": other,
                                                     "matchedName": (t["tdsName"] if label == "tds" else w["institution"] if label == "wiki" else hist_name)})
        if not w:
            report["unmatched"]["wikipedia"].append(name)
        if not t:
            report["unmatched"]["tds"].append(name)
        if not hist_name:
            report["unmatched"]["rpiHistory"].append(name)
        if (w and ws < 1.0) or (t and ts < 1.0):
            report["lowConfidence"].append({"ncaaName": name, "wiki": w and w["institution"], "wikiScore": round(ws, 2),
                                            "tds": t and t["tdsName"], "tdsScore": round(ts, 2)})
        # --- slug
        slug = t["tdsSlug"] if t else common.slugify(w["institution"] if w else name)
        if slug in used_slugs or (slug in existing and existing[slug]["ids"].get("ncaaName") != name):
            slug = common.slugify(name)
        used_slugs.add(slug)
        # --- athletics website: alias > NCAA.com school page > Wikipedia athletics infobox
        ncaa_slug = ncaa_index.get(name)
        ath_url = al.get("site") or (fetch_athletics_url(ncaa_slug) if ncaa_slug else None) or wiki_infobox_site(w.get("athleticsArticle") if w else None)
        if not ath_url:
            report["unmatched"]["athleticsUrl"].append(name)
        # --- Scorecard
        sc = bulk_by_name.get(al["scorecard"]) if al.get("scorecard") else None
        if not sc and w:
            sc = match_scorecard(w, bulk)
        if not sc:
            report["unmatched"]["scorecard"].append(name)
        # --- Wikipedia soccer article
        wiki_title = soccer_article_for(w.get("athleticsArticle")) if w else None
        if not wiki_title:
            report["unmatched"]["wikiArticle"].append(name)
        state = common.state_code(w["state"]) if w else (sc.get("school.state") if sc else None)
        entry = {
            "slug": slug, "onboarded": False,
            "name": (w["institutionArticle"].replace("_", " ") if w and w.get("institutionArticle") else (w["institution"] if w else name)),
            "shortName": w["institution"] if w else name, "nickname": w["nickname"] if w else None,
            "division": "D1", "conference": conf, "colors": None,
            "athletics": {"platform": "auto", "baseUrl": ath_url, "sportPath": "/sports/womens-soccer"},
            "ids": {"scorecardUnitId": sc.get("id") if sc else None, "tdsClgId": t["tdsClgId"] if t else None,
                    "tdsSlug": t["tdsSlug"] if t else None, "wikipedia": wiki_title, "ncaaName": name,
                    "ncaaSlug": ncaa_slug, "rpiHistoryName": hist_name},
            "social": {"x": None, "instagram": None},
            "location": {"city": w["city"] if w else (sc.get("school.city") if sc else None), "state": state,
                         "lat": sc.get("location.lat") if sc else None, "lon": sc.get("location.lon") if sc else None,
                         "timezone": STATE_TZ.get(state or "", "America/New_York")},
        }
        programs.append(entry)
        common.log(f"registry: {name:<24} slug={slug:<22} tds={'ok' if t else '--'} wiki={'ok' if w else '--'} "
                   f"site={'ok' if ath_url else '--'} scorecard={'ok' if sc else '--'} rpiHist={'ok' if hist_name else '--'} article={'ok' if wiki_title else '--'}")
    registry["programs"] = programs
    common.save_registry(registry)
    report["counts"] = {k: len(v) for k, v in report["unmatched"].items()}
    common.write_json(REPORT_PATH, report)
    common.log(f"registry: {len(programs)} programs; unmatched {report['counts']}; low-confidence {len(report['lowConfidence'])}; "
               f"conference mismatches {len(report['conferenceMismatch'])}")
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


def find_wiki_article(program: dict) -> tuple[str | None, list[str]]:
    """Best guess at the program's Wikipedia team article via the search API, verified to exist.
    Returns (canonical title or None, other plausible candidates)."""
    short = program.get("shortName") or program["name"]
    nick = program.get("nickname") or ""
    key_tokens = {t for t in tokens(short) | tokens(nick) if len(t) > 2 and t not in ("state", "university", "college")}
    queries = [f'"{short} {nick} women\'s soccer"', f"{short} {nick} women's soccer", f"{short} women's soccer"]
    seen, plausible = [], []
    for q in queries:
        for title in _wiki_search(q):
            if title in seen:
                continue
            seen.append(title)
            low = title.lower()
            if not low.endswith("women's soccer") or SEASON_ARTICLE_RE.match(title):
                continue
            if not (tokens(title) & key_tokens):
                continue
            plausible.append(title)
        if plausible:
            break
    for title in plausible:
        canon = wiki_canonical(title.replace(" ", "_"))
        if canon:
            return canon, [t for t in plausible if t != title]
    return None, plausible


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
