"""
Adapter for Sidearm Sports athletics sites (current Nuxt generation: goduke.com, usctrojans.com
and most other D1 sites). Pages are server-rendered.

Roster:   /sports/<sport>/roster[/{year}]   -> first <table> (No., Name, Pos., Ht., Year, Hometown,
          High School/Previous School, [Club Team]) plus "Coaching Staff" / "Support Staff" tables
Bio:      /sports/<sport>/roster/<slug>/<id>  -> .c-rosterbio__playerfields + .sidearm_prose body
Schedule: /sports/<sport>/schedule[/{year}]  -> div.s-game-card-standard cards (no <time> tags),
          or, on sites still on the older theme, li.sidearm-schedule-game rows (see
          _parse_legacy_games)
News:     /sports/<sport>/archives (links) and /rss?path=wsoc (titles + pubDate)
"""

from __future__ import annotations

import collections
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

MONTH_NAMES = "January|February|March|April|May|June|July|August|September|October|November|December"
LEGACY_SIDE_CLASSES = {"sidearm-schedule-home-game": "H", "sidearm-schedule-away-game": "A",
                       "sidearm-schedule-neutral-game": "N"}
# Legacy schedule rows date themselves 'Aug 16 (Sun)' - the weekday suffix is what stops DATE_RE,
# which anchors at end of string, from matching. Measured across all 3,226 legacy rows in the
# corpus: every one of them is this shape, so the weekday is optional only for safety.
LEGACY_DATE_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\b", re.I)
# aria-labels inside the row spell the date out in full ('... on August 16, 2026 at 2:00 PM'),
# which is the only place the row states its year.
LEGACY_ARIA_DATE_RE = re.compile(rf"\b({MONTH_NAMES})\s+(\d{{1,2}}),?\s+((?:19|20)\d\d)\b", re.I)
LEGACY_RESULT_RE = re.compile(r"^([WLT]),?$")
LEGACY_SCORE_RE = re.compile(r"\b(\d+)\s*-\s*(\d+)\b")
# Exhibitions and scrimmages, marked however the site writes it (issues #122, #25). Measured over
# the 24,740 games on the 1,220 cached Sidearm schedule pages: 'exhibition' 1,090 rows, '(Exh.)' 288,
# '(Exhib.)/(Exhib)/(Exhi.)' 45, '(EX)/(Ex.)' 43, '(EXH)' 31, '(EXB)/(Exb.)' 8, an unparenthesised
# 'EXH' ('South Florida - EXH', or alone in the location column) 11, 'scrimmage' 100. Before this,
# the legacy branch matched 'exhibition' and 'exh.' and the current-theme branch only 'exhibition',
# and 336 rows -- 87 of them with a result, so 61 published season records -- were counted as real
# games.
#
# What is deliberately NOT a marker, both measured on the same corpus:
#   * 'alumni', 381 rows. Every one is a venue or a promotion: Notre Dame's ground is Alumni Stadium
#     (where NCAA rounds are played), and 'Alumni Day' / 'Alumni Game' are giveaways. None is an
#     exhibition.
#   * 'spring', 65 rows: the note 'Spring Schedule', and towns such as BOILING SPRINGS, NC.
# 'ex' is only a marker inside parentheses, and every other token must be a whole word, so 'Exeter'
# and 'Essex' are not markers either. tests/sidearm_schedule_test.py pins all of this.
# 'Exhibitions' (plural) is what radford and missouri-state print in the card's own label, so the
# plural is part of the word, not an afterthought: the pre-change current-theme branch matched it
# only because its regex had no word boundary at all.
EXHIBITION_RE = re.compile(r"\bexhibitions?\b|\bexh(?:i|ib)?\b\.?|\bexb\b\.?|\(ex\.?\)|\bscrimmages?\b", re.I)
# The same markers where they decorate the opponent's name: '(Exh.)', '(Scrimmage)', 'Florida - EXH'.
# A bare 'Scrimmage' is not stripped: it is part of names like 'Blue vs. Yellow Scrimmage'.
OPPONENT_MARKER_RE = re.compile(r"\s*[-\u2013]\s*(?:exhibitions?|exh(?:i|ib)?|exb)\.?\s*$"
                                r"|\((?:exhibitions?|exh(?:i|ib)?|exb|ex|scrimmages?)\.?\)", re.I)
# Tokens that sit in the location column but are not a place.
LEGACY_NON_PLACE_RE = re.compile(r"^(exhibitions?|exh(?:i|ib)?\.?|exb\.?|scrimmages?|tv|radio|live stats|watch|listen|tickets)\b[:.]?$", re.I)
GAME_LINK_LABELS = ("box score", "recap", "live stats", "history", "watch", "listen", "tickets")


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
    "number": "#", "no": "#", "no.": "#", "num": "#", "num.": "#", "#": "#", "jersey number": "#", "number jersey number": "#",
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
        # A staff table says "Title" (or "Alma Mater"); some themes label the coach role "Position",
        # so a name+position table with none of number/height/year/hometown is staff too.
        is_staff = ("title" in idx or "alma mater" in idx
                    or ("pos" in idx and not any(k in idx for k in ("#", "ht", "year", "hometown"))))
        if "name" in idx and "pos" in idx and not is_staff:
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
        elif "name" in idx and is_staff:
            is_coaching = "coach" in keys
            title_col = idx.get("title", idx.get("pos"))
            for tr in rows:
                cells = tr.find_all(["td", "th"])
                if len(cells) <= max(idx["name"], title_col):
                    continue
                name = common.clean(cells[idx["name"]].get_text(" "))
                # cells sometimes hold escaped HTML ("Academic Coordinator<br><em>W Soccer, ...</em>")
                title = cells[title_col].get_text("\n")
                segs = [common.clean(re.sub(r"<[^>]+>", " ", x)) for x in re.split(r"<br\s*/?>|\n", title)]
                title = next((x for x in segs if x), "")
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
    """Games from the schedule page, whichever theme it is served in.

    The current theme is tried first and the legacy one only when it yields nothing. Falling back
    on an empty result, rather than branching on which markup is present, is what makes this
    incapable of changing a program that already parses.

    That distinction is not theoretical. Seven programs that parse fine today contain the string
    'sidearm-schedule-game' - but in six of them (Michigan, 1,305 occurrences) every one of those
    is a CSS rule inside <style> for a theme the page does not use, and zero are elements. A
    marker test on the raw HTML would have fired on all six. Selecting elements, and only after
    the current theme has come up empty, does not.
    """
    soup = BeautifulSoup(html, "html.parser")
    season = _season_from_title(soup)
    games = _parse_game_cards(soup, base_url, season)
    if not games:
        # the legacy branch can recover a season the <title> did not state, so it reports one back
        season, games = _parse_legacy_games(soup, base_url, season)
    return {"season": season, "games": _spring_games(games)}


def _spring_games(games: list[dict]) -> list[dict]:
    """Fix the two things a spring block on a fall-season page gets wrong.

    1. **The year.** Both branches date a row by the page's season, because the rows give month and
       day only. A January-July game listed AFTER an August-December one is in the next calendar
       year: the '2025-26' page ends with spring 2026 (issues #122, #97). A spring block printed
       BEFORE the fall block (gonzaga 2024) is that season's own spring and keeps its year.
       Measured over the cached pages: 173 games fall in January-July, 169 of them after the fall.
       Every moved date agrees with the page's own second copy - the Nuxt payload's ISO datetimes
       (74), an aria-label full date (2), a Feb 29 that does not exist in the season year (1) - and
       the audit of PR #127 confirmed all 169 a third way, by the weekday each card prints.

    2. **The record.** A spring game is a non-championship-segment contest and does not count in the
       season record, and most sites say so in a section descriptor ('2025 Spring Exhibition
       Season'). Some rows omit it: okstate.com's 2024 page carries that descriptor on six of the
       seven spring cards and leaves it off the last one, 'vs Tulsa, W 3-2'. Read row by row that is
       a win, and it published Oklahoma State's 2024 record as 15-5-3 where the school's own release
       says 14-5-3. It is the only row of its kind in the corpus, and inheriting a descriptor down
       the page would be the more dangerous rule - the exhibition block usually comes FIRST, so a
       forward-inheriting descriptor would mark a whole fall season. So the rule is the plain one:
       on a page that has a fall block at all, a January-July game is a spring game and is not
       counted, whether or not its own row says so.

    A page with no August-December game is not a fall-season page, so neither rule applies to it.
    """
    if not any(g.get("date") and int(g["date"][5:7]) >= 8 for g in games):
        return games
    seen_fall = False
    for g in games:
        d = g.get("date")
        if not d:
            continue
        if int(d[5:7]) >= 8:
            seen_fall = True
            continue
        g["exhibition"] = True
        if seen_fall:
            g["date"] = f"{int(d[:4]) + 1}{d[4:]}"
    return games


def _parse_game_cards(soup: BeautifulSoup, base_url: str, season: int | None) -> list[dict]:
    """Games from div.s-game-card-standard cards (current Sidearm theme)."""
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
        exhibition = bool(EXHIBITION_RE.search(text))
        opponent = common.clean(OPPONENT_MARKER_RE.sub("", opp_raw))
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
        links = _game_links(c, base_url)
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
    return games


def _game_links(el, base_url: str) -> dict:
    """Box score / recap / history links on a game row, keyed by their label. The legacy template
    renders the same list twice (a mobile copy and a desktop one); keying by label collapses them.

    Last occurrence wins, which is what the current-theme branch has always done - Wake Forest is
    the one program in the corpus where it matters (two 'Box Score' links per row, a PDF and the
    live boxscore page) and switching to first-wins silently changed its stored links.
    """
    links = {}
    for a in el.find_all("a", href=True):
        label = common.clean(a.get_text(" ")).lower()
        if label in GAME_LINK_LABELS and a["href"] not in ("#", ""):
            links[label] = urljoin(base_url, a["href"])
    return links


def _lines(el) -> list[str]:
    """Non-empty text lines of an element, in order."""
    if el is None:
        return []
    return [t for t in (common.clean(x) for x in el.get_text("\n").split("\n")) if t]


def _legacy_date(date_el, season: int | None) -> str | None:
    """ISO date for a legacy row. The visible text gives month and day ('Aug 16 (Sun)'); the year
    comes from the season, as it does for every game in the current-theme branch.

    The rows also spell their dates out in aria-labels ('... on August 16, 2026 at 2:00 PM') and an
    earlier draft read the year from there. It was removed: across all 3,226 legacy rows in the
    corpus the aria year and the season agree every time an aria date exists at all (2,345 of
    them), so the code could not change an outcome. The one thing those labels are needed for -
    a page whose <title> states no year - is handled once per page in _parse_legacy_games instead.
    """
    lines = _lines(date_el)
    m = LEGACY_DATE_RE.match(lines[0]) if lines else None
    if not m:
        return None
    mon = MONTHS.get(m.group(1).lower()[:3])
    if not mon or not season:
        return None
    return f"{season}-{mon:02d}-{int(m.group(2)):02d}"


def _legacy_result(li) -> tuple[str | None, str | None]:
    """(result, score) for a legacy row, both read from the result box and neither without the
    other.

    A row that was not played says 'Canceled', 'Postponed' or 'No Contest' where the letter would
    be, which matches nothing here, so it needs no special case - and requiring the letter before
    keeping a score is what stops a row like 'Utah Valley, 1-0' (another pairing in a tournament
    bracket, of which there are two in the corpus) from being recorded as this team's score.

    The <li> also carries the letter as a class. That is not read: across the corpus the class and
    the box agree on all 1,011 rows that have a result, neither ever appears without the other,
    and a second source that never disagrees is a branch no input can exercise.
    """
    lines = _lines(li.select_one(".sidearm-schedule-game-result"))
    result = next((LEGACY_RESULT_RE.match(t).group(1) for t in lines if LEGACY_RESULT_RE.match(t)), None)
    if result is None:
        return None, None
    sm = LEGACY_SCORE_RE.search(" ".join(lines))
    return result, f"{sm.group(1)}-{sm.group(2)}" if sm else None


def _legacy_location_tokens(li) -> list[str]:
    """City and venue for a legacy row.

    The location box also hosts the match-day promotion - Alabama A&M's home games nest a
    <div class="sidearm-schedule-game-opponent-promotion"> inside it - and taking the box's text
    wholesale turns a location into 'Huntsville, AL, Faculty & Staff Appreciation Day'. The place
    is always in the box's own <span> children, so those are read and the nested boxes are not.
    Falls back to the whole box for any theme that puts the text straight in the div.
    """
    el = li.select_one(".sidearm-schedule-game-location")
    if el is None:
        return []
    spans = el.find_all("span", recursive=False)
    if spans:
        return [t for s in spans for t in _lines(s)]
    return _lines(el)


def _parse_legacy_games(soup: BeautifulSoup, base_url: str, season: int | None) -> tuple[int | None, list[dict]]:
    """(season, games) from li.sidearm-schedule-game rows (the older Sidearm schedule theme,
    issue #35). The season comes back because these rows can supply one the page <title> did not.

    These pages are fully server-rendered - the rows are in the HTML as fetched - so the only
    thing that was missing was a parser. 159 of the 160 Sidearm programs that had no schedule at
    all are this template and nothing else.
    """
    rows = soup.select("li.sidearm-schedule-game")
    if season is None:
        # LIU is the one program in the corpus whose schedule <title> carries no year. Its rows
        # still state theirs in aria-labels, so the page's own most common year stands in for the
        # season - without which every row on such a page would be dateless, which is what the
        # current-theme branch does.
        years = collections.Counter(
            int(m.group(3))
            for li in rows
            for a in li.find_all(attrs={"aria-label": True})
            for m in [LEGACY_ARIA_DATE_RE.search(a.get("aria-label", ""))] if m
        )
        season = years.most_common(1)[0][0] if years else None

    games = []
    for li in rows:
        classes = li.get("class") or []
        name_el = li.select_one(".sidearm-schedule-game-opponent-name")
        opp_raw = common.clean(name_el.get_text(" ")) if name_el else ""
        rank = None
        m = re.match(r"#\s*(\d+)\s+(.*)", opp_raw)
        if m:
            rank, opp_raw = int(m.group(1)), m.group(2)
        opponent = common.clean(OPPONENT_MARKER_RE.sub("", opp_raw))
        if not opponent:
            continue

        # "Exhibition" is as likely to sit in the location column as in the opponent's name, so
        # the whole row is searched - and then the word is kept out of `location`.
        exhibition = bool(EXHIBITION_RE.search(li.get_text(" ", strip=True)))

        # One of these three classes is on every one of the 3,226 legacy rows in the corpus. The
        # row also says 'at' or 'vs' in .sidearm-schedule-game-conference-vs, and an earlier draft
        # fell back to reading that; it is gone for the same reason the result-class fallback is,
        # namely that it agreed with the class on every row that had both and so could never
        # change an answer. A row with none of the three gets None, which is what the current-theme
        # branch returns when its own stamp says neither.
        home_away = next((v for c, v in LEGACY_SIDE_CLASSES.items() if c in classes), None)

        # The conference node is rendered empty on non-conference rows and carries the
        # conference's name ('CAA', 'A10') on conference ones, so presence alone means nothing.
        conf_el = li.select_one(".sidearm-schedule-game-conference")
        conference = bool(conf_el and common.clean(conf_el.get_text(" ")))

        loc_toks = [t for t in _legacy_location_tokens(li) if not LEGACY_NON_PLACE_RE.match(t)]
        result, score = _legacy_result(li)
        games.append({
            "date": _legacy_date(li.select_one(".sidearm-schedule-game-opponent-date"), season),
            "datetime": None,
            "exhibition": exhibition,
            "conferenceGame": conference,
            "homeAway": home_away,
            "opponent": opponent, "opponentRank": rank,
            "location": ", ".join(loc_toks[:2]) if loc_toks else None,
            "result": result, "score": score, "links": _game_links(li, base_url),
        })
    return season, games


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
