"""
Adapter for Sidearm Sports athletics sites (current Nuxt generation: goduke.com, usctrojans.com
and most other D1 sites). Pages are server-rendered.

Roster:   /sports/<sport>/roster[/{year}]   -> first <table> (No., Name, Pos., Ht., Year, Hometown,
          High School/Previous School, [Club Team]) plus "Coaching Staff" / "Support Staff" tables
Bio:      /sports/<sport>/roster/<slug>/<id>  -> .c-rosterbio__playerfields + .sidearm_prose body
Schedule: /sports/<sport>/schedule[/{year}]  -> div.s-game-card-standard cards (no <time> tags)
News:     /sports/<sport>/archives (links) and /rss?path=wsoc (titles + pubDate)
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import common

CLASS_CODES = [
    (re.compile(r"^(r-?|rs-?|redshirt\s*)(fr|fresh)", re.I), "R-FR"), (re.compile(r"^(r-?|rs-?|redshirt\s*)(so|soph)", re.I), "R-SO"),
    (re.compile(r"^(r-?|rs-?|redshirt\s*)(jr|jun)", re.I), "R-JR"), (re.compile(r"^(r-?|rs-?|redshirt\s*)(sr|sen)", re.I), "R-SR"),
    (re.compile(r"^(fr|fresh)", re.I), "FR"), (re.compile(r"^(so|soph)", re.I), "SO"), (re.compile(r"^(jr|jun)", re.I), "JR"),
    (re.compile(r"^(sr|sen)", re.I), "SR"), (re.compile(r"^(gr|grad|5th|fifth|6th)", re.I), "GR"),
]
HEIGHT_RE = re.compile(r"(\d)\s*[-'′’]\s*(\d{1,2})")
TITLE_YEAR_RE = re.compile(r"(?:19|20)\d\d")
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
DATE_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})$", re.I)
HEAD_COACH_RE = re.compile(r"head coach", re.I)
NOT_HEAD_RE = re.compile(r"assoc|assist|volunteer|director of (?:operations|ops)", re.I)


def urls(program: dict, registry: dict) -> dict:
    t = registry["sources"]["athleticsPlatforms"]["sidearm"]
    a = program["athletics"]
    fmt = lambda key, **kw: t[key].format(baseUrl=a["baseUrl"], sportPath=a["sportPath"], **kw)
    return {
        "roster": fmt("roster"),
        "rosterSeason": lambda y: fmt("rosterSeason", year=y),
        "schedule": fmt("schedule"),
        "scheduleSeason": lambda y: fmt("scheduleSeason", year=y),
        "news": fmt("news"),
        "rss": fmt("rss") if "rss" in t else None,
    }


def class_code(label: str) -> str:
    s = (label or "").strip()
    for rx, code in CLASS_CODES:
        if rx.search(s):
            return code
    return ""


def height_inches(txt: str) -> int | None:
    m = HEIGHT_RE.search(txt or "")
    return int(m.group(1)) * 12 + int(m.group(2)) if m else None


def _season_from_title(soup: BeautifulSoup) -> int | None:
    t = soup.find("title")
    if t:
        m = TITLE_YEAR_RE.search(t.get_text())
        if m:
            return int(m.group(0))
    return None


# Roster table headers vary by site generation and theme ("Name" / "Full Name" / "Player",
# "Pos." / "Position", "Year" / "Academic Year" / "Class" / "Cl.", "Number Jersey Number" on WMT
# tables). Everything is folded onto one canonical key before column lookup.
HEADER_ALIASES = {
    "full name": "name", "player": "name", "player name": "name", "name": "name",
    "position": "pos", "pos.": "pos", "pos": "pos",
    "academic year": "year", "athletic year": "year", "year": "year", "yr.": "year", "yr": "year",
    "class": "year", "cl.": "year", "cl": "year", "eligibility": "year", "elig.": "year",
    "height": "ht", "ht.": "ht", "ht": "ht",
    "number": "#", "no": "#", "no.": "#", "#": "#", "jersey number": "#", "number jersey number": "#",
    "club team": "club", "club": "club",
}


def _norm_header(text: str) -> str:
    h = common.clean(text).lower()
    return HEADER_ALIASES.get(h, h)


def _header_index(table) -> tuple[dict[str, int], int, str]:
    """Return (header index, number of header rows, caption). Staff tables have a caption row
    ('Coaching Staff') above the real header row. Header names are canonicalised through
    HEADER_ALIASES; the first column wins when two headers fold onto the same key."""
    rows = table.find_all("tr")[:2]
    caption = ""
    for n, tr in enumerate(rows, start=1):
        heads = [_norm_header(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
        if "name" in heads:
            idx: dict[str, int] = {}
            for i, h in enumerate(heads):
                idx.setdefault(h, i)
            return idx, n, caption
        caption = " ".join(heads)
    return {}, 0, caption


def _col(idx: dict, *names):
    """Column index for the first header that equals one of `names`; failing that, the first
    header that starts with one of them (so 'hometown / high school' still serves 'hometown')."""
    for n in names:
        if n in idx:
            return idx[n]
    for n in names:
        for h, i in idx.items():
            if h.startswith(n):
                return i
    return None


def _player_record(*, number, name, pos_label, height, class_label, hometown, high_school,
                   previous_school="", club="", major="", bio_url=None, social=None) -> dict:
    ht = height or ""
    return {
        "number": number or "", "name": name, "pos": common.norm_pos(pos_label), "posLabel": pos_label or "",
        "height": re.sub(r"\s*''\s*$", '"', ht).replace("' ", "'").replace("′", "'").replace("″", '"'),
        "heightIn": height_inches(ht),
        "classLabel": class_label or "", "classCode": class_code(class_label or ""),
        "hometown": hometown or "", "highSchool": high_school or "", "previousSchool": previous_school or "",
        "major": major or "", "club": club or "", "bioUrl": bio_url, "social": social or {},
    }


def _split_slash(txt: str) -> tuple[str, str]:
    """'Milton, Ontario / Kielburger Secondary' -> ('Milton, Ontario', 'Kielburger Secondary')."""
    if " / " in txt:
        a, b = txt.split(" / ", 1)
        return common.clean(a), common.clean(b)
    return txt, ""


def parse_roster_tables(soup: BeautifulSoup, base_url: str, social_by_url: dict | None = None) -> tuple[list, list]:
    """Players and staff from <table> markup: the player table (name + position columns) and the
    'Coaching Staff' / 'Support Staff' tables (name + title). Shared with the WMT adapter, whose
    table theme uses the same header vocabulary."""
    social_by_url = social_by_url or {}
    players, staff = [], []
    for table in soup.find_all("table"):
        idx, nhead, caption = _header_index(table)
        if not idx:
            continue
        keys = " ".join(idx) + " " + caption
        rows = table.find_all("tr")[nhead:]
        if "name" in idx and "pos" in idx:
            ci = {"num": _col(idx, "#"), "name": _col(idx, "name"), "pos": _col(idx, "pos"), "ht": _col(idx, "ht"),
                  "yr": _col(idx, "year"), "home": _col(idx, "hometown"),
                  "hs": _col(idx, "high school", "previous", "last school"), "club": _col(idx, "club"),
                  "major": _col(idx, "major", "academic major")}
            for tr in rows:
                cells = tr.find_all(["td", "th"])
                if len(cells) < 4:
                    continue

                def cell(k):
                    i = ci.get(k)
                    return common.clean(cells[i].get_text(" ")) if i is not None and i < len(cells) else ""

                name_cell = cells[ci["name"]] if ci["name"] is not None and ci["name"] < len(cells) else None
                link = name_cell.find("a", href=True) if name_cell else None
                name = cell("name")
                if not name or name.lower() in ("name", "full name"):
                    continue
                hometown = cell("home")
                hs, prev = _split_slash(cell("hs"))
                if ci["hs"] is None and " / " in hometown:  # single 'Hometown / High School' column
                    hometown, hs = _split_slash(hometown)
                bio_url = urljoin(base_url, link["href"]) if link else None
                players.append(_player_record(
                    number=cell("num"), name=name, pos_label=cell("pos"), height=cell("ht"), class_label=cell("yr"),
                    hometown=hometown, high_school=hs, previous_school=prev, club=cell("club"), major=cell("major"),
                    bio_url=bio_url, social=social_by_url.get(bio_url, {})))
        elif "name" in idx and "title" in idx:
            is_coaching = "coach" in keys
            for tr in rows:
                cells = tr.find_all(["td", "th"])
                if len(cells) <= max(idx["name"], idx["title"]):
                    continue
                name = common.clean(cells[idx["name"]].get_text(" "))
                # cells sometimes hold escaped HTML ("Academic Coordinator<br><em>W Soccer, ...</em>")
                title = cells[idx["title"]].get_text("\n")
                title = re.split(r"<br\s*/?>|\n", title)[0]
                title = common.clean(re.sub(r"<[^>]+>", " ", title))
                link = cells[idx["name"]].find("a", href=True)
                if not name or name.lower() == "name":
                    continue
                staff.append({
                    "name": name, "title": title,
                    "isHeadCoach": bool(HEAD_COACH_RE.search(title)) and not NOT_HEAD_RE.search(title),
                    "isCoach": is_coaching or bool(re.search(r"coach", title, re.I)),
                    "bioUrl": urljoin(base_url, link["href"]) if link else None, "social": {},
                })
    return players, staff


def _sr_labelled(el) -> tuple[str, str]:
    """('position', 'GK') from <span><span class="sr-only">Position</span> GK</span>."""
    label = ""
    for sr in el.select(".sr-only"):
        label = common.clean(sr.get_text(" ")).lower()
        sr.extract()
    return label, common.clean(el.get_text(" "))


def _parse_person_cards(soup: BeautifulSoup, base_url: str, social_by_url: dict) -> list[dict]:
    """Players from .s-person-card markup (current Sidearm theme). Used when the page carries no
    player table. Cards are rendered twice (list + standard variants), so dedupe on bio URL."""
    players, seen = [], set()
    for card in soup.select(".s-person-card"):
        a = card.find("a", href=re.compile(r"/roster/[a-z0-9-]+/\d+$"))
        if not a:
            continue
        bio_url = urljoin(base_url, a["href"])
        if bio_url in seen:
            continue
        h3 = card.select_one(".s-person-details__personal-single-line h3, .s-person-details__personal h3")
        name = common.clean(h3.get_text(" ")) if h3 else common.clean(a.get_text(" "))
        if not name:
            continue
        seen.add(bio_url)
        stats = {}
        for item in card.select(".s-person-details__bio-stats-item"):
            label, value = _sr_labelled(item)
            if label:
                stats.setdefault(label, value)
        stamp = card.select_one(".s-stamp__text")
        number = _sr_labelled(stamp)[1] if stamp else ""
        home_el = card.select_one("[data-test-id$='person-hometown'], .s-person-card__content__person__location-item")
        hs_el = card.select_one("[data-test-id$='person-high-school'], .s-person-card__content__person__high-school-item")
        hometown = _sr_labelled(home_el)[1] if home_el else ""
        high_school = _sr_labelled(hs_el)[1] if hs_el else ""
        club = next((v for k, v in stats.items() if k.startswith("custom field") or "club" in k), "")
        players.append(_player_record(
            number=number, name=name, pos_label=stats.get("position", ""), height=stats.get("height", ""),
            class_label=stats.get("academic year", stats.get("class", stats.get("year", ""))),
            hometown=hometown, high_school=high_school, club=club, bio_url=bio_url,
            social=social_by_url.get(bio_url, {})))
    return players


def looks_client_rendered(html: str) -> bool:
    """True when the roster page is a template filled in by the browser (legacy Sidearm Knockout /
    Vue sites, or the current theme's skeleton loader): the served HTML never contains players."""
    return ("{{ roster." in html or "v-cloak" in html or "@season @sport" in html
            or ("skeleton-loader" in html and "c-rosterpage" in html) or html.count("data-bind=") > 40)


def parse_roster(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    # social links live on the person cards, keyed by bio url
    social_by_url: dict[str, dict] = {}
    for card in soup.select(".s-person-card"):
        a = card.find("a", href=re.compile(r"/roster/[a-z0-9-]+/\d+$"))
        if not a:
            continue
        soc = {}
        for l in card.find_all("a", href=True):
            if "instagram.com" in l["href"]:
                soc["instagram"] = l["href"]
            elif "twitter.com" in l["href"] or "x.com/" in l["href"]:
                soc["x"] = l["href"]
        if soc:
            social_by_url[urljoin(base_url, a["href"])] = soc

    players, staff = parse_roster_tables(soup, base_url, social_by_url)
    if not players:
        players = _parse_person_cards(soup, base_url, social_by_url)
    seen, uniq = set(), []
    for s in staff:
        k = s["bioUrl"] or s["name"]
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    return {"season": _season_from_title(soup), "players": players, "staff": uniq}


def parse_bio(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    meta = {}
    pf = soup.select_one(".c-rosterbio__playerfields")
    if pf:
        toks = [common.clean(t) for t in pf.get_text("\n").split("\n")]
        toks = [t for t in toks if t]
        i = 0
        while i < len(toks) - 1:
            if toks[i].endswith(":"):
                meta[toks[i][:-1].lower()] = toks[i + 1]
                i += 2
            else:
                i += 1
    candidates = soup.select(".sidearm_prose, .s-text-paragraph-longform")
    body = max(candidates, key=lambda e: len(e.get_text(" ", strip=True))) if candidates else None
    sections: dict[str, str] = {}
    if body:
        current, buf = "intro", []
        for el in body.descendants:
            if getattr(el, "name", None) == "strong":
                txt = common.clean(el.get_text(" "))
                if 2 < len(txt) < 60:
                    if buf:
                        sections[current] = common.clean(" ".join(buf))
                    current, buf = txt.rstrip(":"), []
                    continue
            if isinstance(el, str):
                t = common.clean(el)
                if t and not (el.parent and el.parent.name == "strong"):
                    buf.append(t)
        if buf:
            sections[current] = common.clean(" ".join(buf))
    return {"meta": meta, "sections": sections}


def _top_level_cards(soup: BeautifulSoup):
    cards = [d for d in soup.find_all("div") if any("s-game-card-standard" in c for c in (d.get("class") or []))]
    ids = {id(c) for c in cards}
    return [c for c in cards if not any(id(p) in ids for p in c.parents)]


def parse_schedule(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    season = _season_from_title(soup)
    games = []
    for c in _top_level_cards(soup):
        text = c.get_text(" | ", strip=True)
        stamp = c.select_one(".s-game-card__header__stamp")
        stamp_txt = common.clean(stamp.get_text()).lower() if stamp else ""
        info = c.select_one(".s-game-card__header__team-event-info")
        toks = [common.clean(t) for t in info.get_text("\n").split("\n")] if info else []
        toks = [t for t in toks if t]
        opp_raw = toks[0] if toks else ""
        rank = None
        m = re.match(r"#\s*(\d+)\s+(.*)", opp_raw)
        if m:
            rank, opp_raw = int(m.group(1)), m.group(2)
        exhibition = bool(re.search(r"exhibition", text, re.I))
        opponent = common.clean(re.sub(r"\((?:exhibition|exh\.?)\)", "", opp_raw, flags=re.I))
        loc_toks = [t for t in toks[1:] if not t.lower().startswith("tv:") and not t.lower().startswith("radio")]
        location = ", ".join(loc_toks[:2]) if loc_toks else None
        sc = c.select_one(".s-game-card__header__game-score-time")
        st = [common.clean(t) for t in sc.get_text("\n").split("\n")] if sc else []
        st = [t for t in st if t]
        result = score = date = None
        for t in st:
            if re.fullmatch(r"[WLT],?", t):
                result = t[0]
            elif re.fullmatch(r"\d+\s*-\s*\d+", t):
                score = re.sub(r"\s", "", t)
            else:
                dm = DATE_RE.match(t)
                if dm and season:
                    mon = MONTHS.get(dm.group(1).lower()[:3])
                    if mon:
                        date = f"{season}-{mon:02d}-{int(dm.group(2)):02d}"
        links = {}
        for a in c.find_all("a", href=True):
            label = common.clean(a.get_text(" ")).lower()
            if label in ("box score", "recap", "live stats", "history", "watch", "listen", "tickets") and a["href"] not in ("#", ""):
                links[label] = urljoin(base_url, a["href"])
        if not opponent:
            continue
        games.append({
            "date": date, "datetime": None,
            "exhibition": exhibition,
            "conferenceGame": bool(c.select_one(".s-game-card__header__conf-text, .s-game-card__header__conf-logo")),
            "homeAway": "A" if stamp_txt.startswith("at") else "H" if stamp_txt.startswith("vs") else None,
            "opponent": opponent, "opponentRank": rank, "location": location,
            "result": result, "score": score, "links": links,
        })
    return {"season": season, "games": games}


def parse_news(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/news/20\d\d/\d{1,2}/\d{1,2}/")):
        href = urljoin(base_url, a["href"])
        title = common.clean(a.get_text(" "))
        if not title or href in seen or len(title) < 8:
            continue
        m = re.search(r"/news/(\d{4})/(\d{1,2})/(\d{1,2})/", href)
        date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None
        seen.add(href)
        items.append({"title": title, "url": href, "date": date})
    return items


def parse_rss(xml_text: str, base_url: str) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    for it in root.iter("item"):
        title = common.clean(it.findtext("title") or "")
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        date = None
        if pub:
            try:
                date = parsedate_to_datetime(pub).date().isoformat()
            except (TypeError, ValueError):
                date = None
        if title and link:
            items.append({"title": title, "url": urljoin(base_url, link), "date": date})
    return items
