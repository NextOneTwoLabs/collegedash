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

# NCAA short name -> Wikipedia institution name (only where normalisation alone fails)
OVERRIDES_WIKI = {
    "southern california": "usc", "miami (fl)": "miami", "miami (oh)": "miami (ohio)", "lmu (ca)": "loyola marymount",
    "st. john's (ny)": "st. john's", "ole miss": "mississippi", "uconn": "connecticut", "umass": "massachusetts",
    "uncw": "unc wilmington", "unc asheville": "unc asheville", "app state": "appalachian state", "fdu": "fairleigh dickinson",
    "liu": "long island", "ucf": "central florida", "utep": "utep", "utsa": "utsa", "ut martin": "ut martin",
    "fiu": "florida international", "fgcu": "florida gulf coast", "siue": "siu edwardsville", "smu": "smu", "tcu": "tcu",
    "byu": "byu", "lsu": "lsu", "vcu": "vcu", "vmi": "vmi", "unlv": "unlv", "usc upstate": "south carolina upstate",
    "sfa": "stephen f. austin", "csun": "cal state northridge", "ucsb": "uc santa barbara", "uc davis": "uc davis",
    "uc irvine": "uc irvine", "uc riverside": "uc riverside", "uc san diego": "uc san diego", "umbc": "umbc", "umkc": "kansas city",
    "penn": "pennsylvania", "pitt": "pittsburgh", "ga. southern": "georgia southern", "ga. tech": "georgia tech",
    "col. of charleston": "college of charleston", "charleston so.": "charleston southern",
    "boston u.": "boston university", "boston college": "boston college", "colorado": "colorado", "colorado col.": "colorado college",
    "army west point": "army", "navy": "navy", "air force": "air force", "cal poly": "cal poly", "cal baptist": "california baptist",
    "long beach st.": "long beach state", "sacramento st.": "sacramento state", "san diego st.": "san diego state",
    "san jose st.": "san jose state", "fresno st.": "fresno state", "cal st. fullerton": "cal state fullerton",
    "cal st. bakersfield": "cal state bakersfield", "saint mary's (ca)": "saint mary's", "loyola chicago": "loyola chicago",
    "loyola maryland": "loyola maryland", "seattle u": "seattle", "the citadel": "the citadel", "ut rio grande valley": "utrgv",
    "texas a&m-commerce": "east texas a&m", "queens (nc)": "queens university of charlotte", "southern ill.": "southern illinois",
    "northern ill.": "northern illinois", "eastern ill.": "eastern illinois", "western ill.": "western illinois",
    "eastern mich.": "eastern michigan", "western mich.": "western michigan", "central mich.": "central michigan",
    "northern ky.": "northern kentucky", "western ky.": "western kentucky", "eastern ky.": "eastern kentucky",
    "middle tenn.": "middle tennessee", "east tenn. st.": "east tennessee state", "southern miss.": "southern miss",
    "ga. southern": "georgia southern", "ga. tech": "georgia tech", "fla. atlantic": "florida atlantic", "north fla.": "north florida",
    "central conn. st.": "central connecticut", "southern ind.": "southern indiana", "purdue fort wayne": "purdue fort wayne",
    "omaha": "omaha", "unc greensboro": "unc greensboro", "n.c. a&t": "north carolina a&t", "n.c. central": "north carolina central",
    "nc state": "nc state", "ole miss": "ole miss", "mississippi val.": "mississippi valley state", "alcorn": "alcorn state",
    "ark.-pine bluff": "arkansas–pine bluff", "little rock": "little rock", "central ark.": "central arkansas",
    "northwestern st.": "northwestern state", "southeastern la.": "southeastern louisiana", "la.-monroe": "louisiana–monroe",
    "mcneese": "mcneese", "nicholls": "nicholls", "houston christian": "houston christian", "a&m-corpus christi": "texas a&m–corpus christi",
    "st. thomas (mn)": "st. thomas", "st. bonaventure": "st. bonaventure", "st. francis (pa)": "saint francis", "st. peter's": "saint peter's",
    "mount st. mary's": "mount st. mary's", "saint joseph's": "saint joseph's", "saint louis": "saint louis", "detroit mercy": "detroit mercy",
    "iupui": "iu indianapolis", "iu indy": "iu indianapolis", "ualbany": "albany", "umass lowell": "umass lowell", "uconn": "connecticut",
    "southern utah": "southern utah", "utah tech": "utah tech", "utah valley": "utah valley", "tarleton st.": "tarleton state",
    "grand canyon": "grand canyon", "sam houston": "sam houston", "kennesaw st.": "kennesaw state", "jacksonville st.": "jacksonville state",
    "app state": "appalachian state", "james madison": "james madison", "old dominion": "old dominion", "coastal carolina": "coastal carolina",
    "wright st.": "wright state", "youngstown st.": "youngstown state", "cleveland st.": "cleveland state", "oakland": "oakland",
    "green bay": "green bay", "milwaukee": "milwaukee", "robert morris": "robert morris",
}


def norm_school(s: str) -> str:
    s = (s or "").lower().replace("&", " and ").replace("’", "'")
    s = re.sub(r"\bst\.\s+(?=[a-z])", lambda m: "saint " if re.match(r"st\.\s+(john|joseph|mary|peter|francis|thomas|bonaventure|louis)", s[m.start():]) else "state ", s)
    s = s.replace("st.", "state").replace("univ.", "").replace("u.", "")
    s = re.sub(r"[().,'\-–/]", " ", s)
    # keep 'college' - it disambiguates Colorado vs Colorado College, Boston College, etc.
    s = re.sub(r"\b(university|univ|of|the|at|campus)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str) -> set[str]:
    return set(norm_school(s).split())


def best_match(name: str, candidates: dict[str, dict], *, min_score: float = 0.6) -> tuple[str | None, float]:
    """candidates: {normalised name: row}. Exact normalised match first, then token overlap."""
    n = norm_school(name)
    if n in candidates:
        return n, 1.0
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
    "MD_EARN_WNE_P10": "latest.earnings.10_yrs_after_entry.median", "PREDDEG": "_preddeg",
}
INT_COLS = {"id", "school.locale", "school.carnegie_basic", "school.ownership", "school.religious_affiliation", "latest.student.size",
            "latest.admissions.sat_scores.25th_percentile.critical_reading", "latest.admissions.sat_scores.75th_percentile.critical_reading",
            "latest.admissions.sat_scores.25th_percentile.math", "latest.admissions.sat_scores.75th_percentile.math",
            "latest.admissions.sat_scores.average.overall", "latest.admissions.act_scores.25th_percentile.cumulative",
            "latest.admissions.act_scores.75th_percentile.cumulative", "latest.admissions.act_scores.midpoint.cumulative",
            "latest.cost.tuition.in_state", "latest.cost.tuition.out_of_state", "latest.cost.attendance.academic_year",
            "latest.earnings.10_yrs_after_entry.median", "_npt_pub", "_npt_priv", "_preddeg"}


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
                if row.get("PREDDEG") not in ("3", "4"):
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
                results.append(r)
    common.write_json(SCORECARD_BULK, {"fetchedAt": common.now_iso(), "source": m.group(0), "count": len(results), "results": results})
    common.log(f"scorecard bulk: {len(results)} bachelor's/graduate institutions cached")
    return results


def match_scorecard(wiki_row: dict, bulk: list[dict]) -> dict | None:
    state = common.state_code(wiki_row.get("state"))
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

def build(registry: dict, *, limit: int | None = None) -> dict:
    master = load_ncaa_master()
    if not master:
        raise RuntimeError("no NCAA RPI table; run: python collegedash.py rpi current")
    wiki = fetch_wiki_list()
    tds = fetch_tds_teams()
    ncaa_index = fetch_ncaa_index()
    bulk = fetch_scorecard_bulk(registry)
    hist = common.read_json(os.path.join(common.RPI_OUT_DIR, "2024.json"), {}) or {}
    hist_names = {norm_school(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t["team"])): t["team"] for t in hist.get("teams", [])}
    wiki_by_norm = {norm_school(r["institution"]): r for r in wiki}
    tds_by_norm = {norm_school(r["tdsName"]): r for r in tds.values()}
    existing = {p["slug"]: p for p in registry["programs"]}
    existing_ncaa = {p["ids"].get("ncaaName"): p for p in registry["programs"]}
    report = {"builtAt": common.now_iso(), "total": len(master), "unmatched": {"wikipedia": [], "tds": [], "ncaaIndex": [],
              "athleticsUrl": [], "scorecard": [], "rpiHistory": [], "wikiArticle": []}, "lowConfidence": []}
    programs = []
    for i, m in enumerate(master):
        if limit and i >= limit:
            break
        name = m["ncaaName"]
        if name in existing_ncaa:
            programs.append(existing_ncaa[name])
            continue
        lookup = OVERRIDES_WIKI.get(name.lower(), name)
        wn, ws = best_match(lookup, wiki_by_norm)
        w = wiki_by_norm.get(wn) if wn else None
        tn, ts = best_match(lookup, tds_by_norm)
        t = tds_by_norm.get(tn) if tn else None
        if not w:
            report["unmatched"]["wikipedia"].append(name)
        if not t:
            report["unmatched"]["tds"].append(name)
        if (w and ws < 1.0) or (t and ts < 1.0):
            report["lowConfidence"].append({"ncaaName": name, "wiki": w and w["institution"], "wikiScore": round(ws, 2),
                                            "tds": t and t["tdsName"], "tdsScore": round(ts, 2)})
        slug = (t["tdsSlug"] if t else common.slugify(w["institution"] if w else name))
        if slug in existing and existing[slug]["ids"].get("ncaaName") != name:
            slug = slug + "-" + common.slugify(name)[:8]
        ncaa_slug = ncaa_index.get(name)
        if not ncaa_slug:
            report["unmatched"]["ncaaIndex"].append(name)
        ath_url = fetch_athletics_url(ncaa_slug) if ncaa_slug else None
        if not ath_url:
            report["unmatched"]["athleticsUrl"].append(name)
        sc = match_scorecard(w, bulk) if w else None
        if not sc:
            report["unmatched"]["scorecard"].append(name)
        hn, hs = best_match(name, {k: {"team": v} for k, v in hist_names.items()}, min_score=0.5)
        hist_name = hist_names.get(hn) if hn else None
        if not hist_name:
            report["unmatched"]["rpiHistory"].append(name)
        wiki_title = soccer_article_for(w.get("athleticsArticle")) if w else None
        if not wiki_title:
            report["unmatched"]["wikiArticle"].append(name)
        state = common.state_code(w["state"]) if w else (sc.get("school.state") if sc else None)
        entry = {
            "slug": slug, "onboarded": False,
            "name": (w["institutionArticle"].replace("_", " ") if w and w.get("institutionArticle") else (w["institution"] if w else name)),
            "shortName": w["institution"] if w else name, "nickname": w["nickname"] if w else None,
            "division": "D1", "conference": m["conference"], "colors": None,
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
    common.log(f"registry: {len(programs)} programs; unmatched {report['counts']}; low-confidence {len(report['lowConfidence'])}")
    return report
