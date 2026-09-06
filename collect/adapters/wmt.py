"""
Adapter for WMT Digital athletics sites (e.g. gostanford.com). Pages are server-rendered.

Roster:   /sports/<sport>/roster            -> .roster-card-item cards (players + staff)
          /sports/<sport>/roster/season/{y}
Bio:      /sports/<sport>/roster/player/<slug>   -> .roster-bio (meta fields + biography tab)
Schedule: /sports/<sport>/schedule[/season/{y}]  -> .schedule-event-item blocks with <time datetime>
News:     /sports/<sport>/news                   -> .news-archive__list a.article-link + date text
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import common

CLASS_CODES = [
    (re.compile(r"redshirt\s+fresh", re.I), "R-FR"), (re.compile(r"redshirt\s+soph", re.I), "R-SO"),
    (re.compile(r"redshirt\s+jun", re.I), "R-JR"), (re.compile(r"redshirt\s+sen", re.I), "R-SR"),
    (re.compile(r"fresh", re.I), "FR"), (re.compile(r"soph", re.I), "SO"), (re.compile(r"jun", re.I), "JR"),
    (re.compile(r"sen", re.I), "SR"), (re.compile(r"fifth|5th|grad", re.I), "GR"),
]
HEIGHT_RE = re.compile(r"(\d)\s*[′'’]\s*(\d{1,2})")
TITLE_YEAR_RE = re.compile(r"(?:19|20)\d\d")
HEAD_COACH_RE = re.compile(r"head coach|director of women'?s soccer", re.I)
NOT_HEAD_RE = re.compile(r"assoc|assist|volunteer|director of (?:operations|ops)", re.I)


def urls(program: dict, registry: dict) -> dict:
    t = registry["sources"]["athleticsPlatforms"]["wmt"]
    a = program["athletics"]
    fmt = lambda key, **kw: t[key].format(baseUrl=a["baseUrl"], sportPath=a["sportPath"], **kw)
    return {
        "roster": fmt("roster"),
        "rosterSeason": lambda y: fmt("rosterSeason", year=y),
        "schedule": fmt("schedule"),
        "scheduleSeason": lambda y: fmt("scheduleSeason", year=y),
        "news": fmt("news"),
    }


def class_code(label: str) -> str:
    for rx, code in CLASS_CODES:
        if rx.search(label or ""):
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


def _social(card) -> dict:
    out = {}
    for a in card.find_all("a", href=True):
        href = a["href"]
        if "instagram.com" in href:
            out["instagram"] = href
        elif "twitter.com" in href or "x.com" in href:
            out["x"] = href
    return out


def parse_roster(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    players, staff = [], []
    for card in soup.select(".roster-card-item"):
        # current season: /roster/player/<slug>; past seasons: /roster/season/<y>/player/<slug>
        link = card.select_one("a[href*='/roster/'][href*='/player/']")
        staff_link = card.select_one("a[href*='/staff/']")
        title_el = card.select_one(".roster-card-item__title")
        name = common.clean(title_el.get_text(" ")) if title_el else common.clean((link or staff_link).get_text(" ") if (link or staff_link) else "")
        pos_el = card.select_one(".roster-card-item__position")
        pos_label = common.clean(pos_el.get_text(" ")) if pos_el else ""
        if link and not staff_link:
            fields = {}
            for f in card.select(".roster-player-card-profile-field"):
                lab = f.select_one(".roster-player-card-profile-field__label")
                vals = [common.clean(v.get_text(" ")) for v in f.select(".roster-player-card-profile-field__value")]
                if lab:
                    fields[common.clean(lab.get_text(" ")).lower()] = " ".join(vals)
                else:
                    fields.setdefault("_basic", []).extend(vals)
            basic = fields.get("_basic", [])
            height = next((b for b in basic if HEIGHT_RE.search(b)), "")
            class_label = next((b for b in basic if class_code(b)), "")
            num_el = card.select_one(".roster-card-item__jersey-number")
            players.append({
                "number": common.clean(num_el.get_text()) if num_el else "",
                "name": name,
                "pos": common.norm_pos(pos_label),
                "posLabel": pos_label.title() if pos_label.isupper() else pos_label,
                "height": height.replace("′", "'").replace("″", '"'),
                "heightIn": height_inches(height),
                "classLabel": class_label,
                "classCode": class_code(class_label),
                "hometown": fields.get("hometown", ""),
                "highSchool": fields.get("high school", ""),
                "previousSchool": fields.get("previous school", ""),
                "major": fields.get("major", ""),
                "bioUrl": urljoin(base_url, link["href"]),
                "social": _social(card),
            })
        elif staff_link:
            staff.append({
                "name": name,
                "title": pos_label,
                "isHeadCoach": bool(HEAD_COACH_RE.search(pos_label)) and not NOT_HEAD_RE.search(pos_label),
                "isCoach": bool(re.search(r"coach|director of women", pos_label, re.I)),
                "bioUrl": urljoin(base_url, staff_link["href"]),
                "social": _social(card),
            })
    # de-duplicate staff (cards can appear twice in markup for mobile/desktop)
    seen, uniq = set(), []
    for s in staff:
        if s["bioUrl"] not in seen:
            seen.add(s["bioUrl"])
            uniq.append(s)
    return {"season": _season_from_title(soup), "players": players, "staff": uniq}


def parse_bio(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    bio = soup.select_one(".roster-bio")
    if not bio:
        return {}
    meta = {}
    for f in bio.select(".roster-bio-meta__profile-field"):
        txt = common.clean(f.get_text(" | "))
        if "|" in txt:
            k, v = txt.split("|", 1)
            meta[common.clean(k).lower()] = common.clean(v)
    tab = bio.select_one(".roster-biography-tab") or bio.select_one(".roster-bio__content")
    sections: dict[str, str] = {}
    if tab:
        current = "intro"
        buf: list[str] = []
        for el in tab.descendants:
            if getattr(el, "name", None) == "strong":
                txt = common.clean(el.get_text(" "))
                if 2 < len(txt) < 60:
                    if buf:
                        sections[current] = common.clean(" ".join(buf))
                    current, buf = txt, []
                    continue
            if isinstance(el, str):
                t = common.clean(el)
                if t and not (el.parent and el.parent.name == "strong"):
                    buf.append(t)
        if buf:
            sections[current] = common.clean(" ".join(buf))
    return {"meta": meta, "sections": sections}


def parse_schedule(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    games = []
    for it in soup.select(".schedule-event-item"):
        t = it.find("time")
        dt = t.get("datetime") if t else None
        venue_el = it.select_one(".schedule-event-item__venue-label-text")
        venue = common.clean(venue_el.get_text()).lower() if venue_el else ""
        opp_el = it.select_one(".schedule-event-item-team__opponent-name")
        loc_el = it.select_one(".schedule-event-item-team__location")
        rank_el = it.select_one(".schedule-event-item-team__team-rank")
        res_el = it.select_one(".schedule-event-item-result")
        result, score = None, None
        if res_el:
            rtxt = common.clean(res_el.get_text(" "))
            m = re.search(r"\b(W|L|T)\b", rtxt)
            result = m.group(1) if m else None
            m2 = re.search(r"(\d+)\s*-\s*(\d+)", rtxt)
            score = f"{m2.group(1)}-{m2.group(2)}" if m2 else None
        links = {}
        for a in it.select(".schedule-event-links__link, .schedule-event-item__actions a"):
            label = common.clean(a.get_text(" ")).lower()
            if a.get("href") and label:
                links[label] = urljoin(base_url, a["href"])
        raw = str(it)
        games.append({
            "date": dt[:10] if dt else None,
            "datetime": dt,
            # WMT marks nothing explicitly; the recap title/URL is the only exhibition signal.
            "exhibition": bool(re.search(r"exhibition", raw, re.I)),
            "conferenceGame": bool(it.select_one(".schedule-event-item-team__conference-image")),
            "homeAway": {"home": "H", "away": "A", "neutral": "N"}.get(venue, venue or None),
            "opponent": common.clean(opp_el.get_text(" ")) if opp_el else None,
            "opponentRank": int(rank_el.get_text().strip("# ")) if rank_el and rank_el.get_text().strip("# ").isdigit() else None,
            "location": common.clean(loc_el.get_text(" ")) if loc_el else None,
            "result": result,
            "score": score,
            "links": links,
        })
    games = [g for g in games if g["opponent"]]
    return {"season": _season_from_title(soup), "games": games}


DATE_RE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}")
MONTHS = {m: i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"])}


def parse_news(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()
    for a in soup.select("a.article-link[href*='/news/'], .news-archive__list a[href*='/news/']"):
        href = urljoin(base_url, a["href"])
        title = common.clean(a.get_text(" "))
        if not title or href in seen:
            continue
        # date sits in the surrounding card text
        ctx = a.parent
        date = None
        for _ in range(4):
            if ctx is None:
                break
            m = DATE_RE.search(ctx.get_text(" "))
            if m:
                mon, day, yr = re.match(r"(\w+)\s+(\d{1,2}),\s+(\d{4})", m.group(0)).groups()
                date = f"{yr}-{MONTHS[mon]:02d}-{int(day):02d}"
                break
            ctx = ctx.parent
        if not date:
            m = re.search(r"/news/(\d{4})/(\d{1,2})/(\d{1,2})/", href)
            if m:
                date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        seen.add(href)
        items.append({"title": title, "url": href, "date": date})
    return items
