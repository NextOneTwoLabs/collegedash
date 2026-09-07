"""
Program history from the team's Wikipedia article: infobox facts (founded, stadium, titles,
College Cups, conference championships) and the year-by-year results table.

Writes programs/<slug>/sources/wikipedia.json. Uses the REST HTML endpoint (stable markup).
"""

from __future__ import annotations

import re
import urllib.parse

from bs4 import BeautifulSoup

from . import common

NAME = "wikipedia"
YEAR_RE = re.compile(r"\b(?:19|20)\d\d\b")
RECORD_RE = re.compile(r"(\d+)\s*[–—-]\s*(\d+)(?:\s*[–—-]\s*(\d+))?")


def _years(text: str) -> list[int]:
    return sorted({int(y) for y in YEAR_RE.findall(text or "")})


def _record(text: str) -> dict | None:
    m = RECORD_RE.search(text or "")
    if not m:
        return None
    w, l, t = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    return {"w": w, "l": l, "t": t, "text": f"{w}-{l}-{t}"}


def _infobox(soup: BeautifulSoup) -> dict:
    """Return {label: text} from the infobox, handling the 'header row then value row' layout
    Wikipedia uses for lists of years."""
    ib = soup.find("table", class_=re.compile(r"\binfobox\b"))
    out: dict[str, str] = {}
    if not ib:
        return out
    rows = ib.find_all("tr")
    pending_header = None
    for tr in rows:
        th, td = tr.find("th"), tr.find("td")
        if th and td:
            out[common.clean(th.get_text(" "))] = common.clean(td.get_text(" "))
            pending_header = None
        elif th and not td:
            pending_header = common.clean(th.get_text(" "))
        elif td and pending_header:
            out[pending_header] = common.clean(td.get_text(" "))
            pending_header = None
    return out


FINISH_RE = re.compile(r"\b(T-?\d+(?:st|nd|rd|th)|\d+(?:st|nd|rd|th))\b")
NCAA_RE = re.compile(r"NCAA[^,;]*")
COACH_RE = re.compile(r"^[A-Z][A-Za-z.'’\- ]{3,}$")
BAD_COACH = re.compile(r"NCAA|Round|Final|Champion|Semifinal|Quarterfinal|Conference|Tournament|Runner|Winner|Sweet|Elite|"
                       r"College Cup|Regional|Did not|—|–|^[WLT]\b", re.I)


def _seasons_table(soup: BeautifulSoup) -> list[dict]:
    """Year-by-year results. Wikipedia articles use several layouts:
      Stanford: Year | Head coach | Overall | Conference | Conference Standing | NCAA Tournament
      UCLA:     Season | Coach | Record (Overall, Conference) | Notes            (coach cell rowspans)
      Duke:     Season | Head coach | Wins Losses Ties | Wins Losses Ties | Conference | NCAA
    so the parser reads records from whatever cells look like records or W/L/T triples, and the
    coach from the first name-like cell (carrying it forward across rowspans)."""
    best = None
    for t in soup.find_all("table", class_=re.compile(r"wikitable")):
        rows = t.find_all("tr")
        first = rows[0] if rows else None
        heads = [common.clean(c.get_text(" ")).lower() for c in first.find_all(["th", "td"])] if first else []
        if not heads or not heads[0].startswith(("year", "season")):
            continue
        def is_season_row(r):
            first_txt = common.clean(r.find(["th", "td"]).get_text(" ")) if r.find(["th", "td"]) else ""
            # '2011' or '2020–21' are seasons; '2007–2013' is a coaching era, not a season
            return bool(r.find("td")) and bool(YEAR_RE.match(first_txt)) and not re.search(r"\d{4}\s*[–-]\s*\d{4}", first_txt)
        data_rows = [r for r in rows if is_season_row(r)]
        if len(data_rows) < 5:
            continue
        joined = " ".join(common.clean(r.get_text(" ")).lower() for r in rows[:3])
        if not re.search(r"record|overall|wins|w–l|w-l", joined) or re.search(r"opponent|round", joined):
            continue
        if best is None or len(data_rows) > len(best[1]):
            best = (t, data_rows, rows)
    if not best:
        return []
    t, data_rows, rows = best
    header_txt = " ".join(common.clean(r.get_text(" ")).lower() for r in rows[:3])
    split_wlt = "wins" in header_txt and "losses" in header_txt
    seasons, coach_last = [], None
    for tr in data_rows:
        cells = [common.clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
        year_txt = cells[0]
        year = int(YEAR_RE.search(year_txt).group(0))
        rest = cells[1:]
        coach = next((c for c in rest if COACH_RE.match(c) and not BAD_COACH.search(c) and not RECORD_RE.search(c)), None)
        if coach:
            coach_last = coach
        else:
            coach = coach_last
        rec = crec = None
        if split_wlt:
            nums = [int(c) for c in rest if re.fullmatch(r"\d{1,2}", c)]
            if len(nums) >= 3:
                rec = {"w": nums[0], "l": nums[1], "t": nums[2], "text": f"{nums[0]}-{nums[1]}-{nums[2]}"}
            if len(nums) >= 6:
                crec = {"w": nums[3], "l": nums[4], "t": nums[5], "text": f"{nums[3]}-{nums[4]}-{nums[5]}"}
        else:
            recs = [c for c in rest if RECORD_RE.search(c) and not re.search(r"[A-Za-z]{4,}", c)]
            rec = _record(recs[0]) if recs else None
            crec = _record(recs[1]) if len(recs) > 1 else None
        ncaa = None
        for c in rest:
            m = NCAA_RE.search(c)
            if m:
                ncaa = common.clean(m.group(0))
                break
        if ncaa is None and split_wlt:
            tail = [c for c in rest if not re.fullmatch(r"\d{1,2}", c) and c not in ("—", "–", "-") and c != coach]
            if tail:
                ncaa = "NCAA " + tail[-1] if "ncaa" not in tail[-1].lower() else tail[-1]
        finish = None
        for c in rest:
            if c == coach or (ncaa and c == ncaa):
                continue
            m = FINISH_RE.search(c)
            if m and not re.search(r"round|ncaa", c, re.I):
                finish = m.group(1)
                break
        seasons.append({
            "year": year, "label": year_txt, "headCoach": coach,
            "record": rec["text"] if rec else None,
            "wins": rec["w"] if rec else None, "losses": rec["l"] if rec else None, "ties": rec["t"] if rec else None,
            "confRecord": crec["text"] if crec else None, "confFinish": finish, "ncaaResult": ncaa,
        })
    return seasons


def collect(program: dict, registry: dict) -> dict:
    title = program["ids"].get("wikipedia")
    if not title:
        raise common.SkipCollector("wikipedia: no team article in the registry (most mid-majors have none; "
                                   "try `registry fix-wiki`)")
    url = registry["sources"]["wikipedia"]["htmlApi"].format(title=urllib.parse.quote(title, safe=""))
    html, meta = common.fetch_text(url, max_age_hours=24 * 7)
    soup = BeautifulSoup(html, "html.parser")
    ib = _infobox(soup)

    def find(*labels):
        for k, v in ib.items():
            kl = k.lower()
            if any(l in kl for l in labels):
                return v
        return ""

    stadium_txt = find("stadium")
    cap = re.search(r"capacity[:\s]*([\d,]+)", stadium_txt, re.I)
    seasons = _seasons_table(soup)
    data = {
        "title": title,
        "pageUrl": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title)}",
        "founded": (_years(find("founded")) or [None])[0],
        "headCoach": find("head coach") or None,
        "conference": find("conference") or None,
        "stadium": {"name": re.sub(r"\(.*", "", stadium_txt).strip() or None,
                    "capacity": int(cap.group(1).replace(",", "")) if cap else None},
        "nickname": find("nickname") or None,
        "nationalTitles": _years(find("tournament championships", "national championships")),
        "nationalRunnerUp": _years(find("runner-up", "runner up")),
        # some articles label the final four 'Semifinals' instead of 'College Cup'
        "collegeCups": _years(find("college cup") or find("semifinal")),
        "ncaaQuarterfinals": _years(find("quarterfinal")),
        "ncaaAppearances": _years(find("tournament appearances", "ncaa appearances")),
        "confRegularSeasonTitles": _years(find("regular season champ")),
        "confTournamentTitles": _years(find("tournament champ") if "tournament champ" in " ".join(ib).lower() and "ncaa" not in find("tournament champ").lower() else ""),
        "seasons": seasons,
        "infobox": ib,
    }
    # Conference tournament titles: look for a label that mentions conference + tournament.
    for k, v in ib.items():
        kl = k.lower()
        if "conference" in kl and "tournament" in kl:
            data["confTournamentTitles"] = _years(v)
    common.save_source(program["slug"], NAME, data, url=data["pageUrl"], collector=NAME,
                       extra={"fromCache": meta.get("fromCache", False)})
    common.log(f"wikipedia: {len(seasons)} seasons, titles {data['nationalTitles']}, stadium {data['stadium']}")
    return data
