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


def _seasons_table(soup: BeautifulSoup) -> list[dict]:
    for t in soup.find_all("table", class_=re.compile(r"wikitable")):
        heads = [common.clean(th.get_text(" ")) for th in t.find_all("th")[:8]]
        if heads and heads[0].lower().startswith("year") and any("overall" in h.lower() for h in heads):
            break
    else:
        return []
    heads = [common.clean(c.get_text(" ")).lower() for c in t.find("tr").find_all(["th", "td"])]

    def col(*names):
        for i, h in enumerate(heads):
            if any(n in h for n in names):
                return i
        return None

    ci = {"year": col("year", "season"), "coach": col("coach"), "overall": col("overall"),
          "conf": col("conference"), "standing": col("standing", "finish", "place"), "ncaa": col("ncaa", "postseason")}
    # 'conference' matches both 'Conference' and 'Conference Standing'; pick the first for record.
    if ci["conf"] is not None and ci["standing"] == ci["conf"]:
        ci["standing"] = next((i for i, h in enumerate(heads) if "standing" in h), None)
    seasons = []
    for tr in t.find_all("tr")[1:]:
        cells = [common.clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
        if not cells or not YEAR_RE.search(cells[0]) or cells[0].lower().startswith("total"):
            continue
        year_txt = cells[0]
        year = int(YEAR_RE.search(year_txt).group(0))

        def cell(k):
            i = ci.get(k)
            return cells[i] if i is not None and i < len(cells) else ""

        rec = _record(cell("overall"))
        crec = _record(cell("conf"))
        seasons.append({
            "year": year, "label": year_txt,
            "headCoach": cell("coach") or None,
            "record": rec["text"] if rec else None,
            "wins": rec["w"] if rec else None, "losses": rec["l"] if rec else None, "ties": rec["t"] if rec else None,
            "confRecord": crec["text"] if crec else None,
            "confFinish": cell("standing") or None,
            "ncaaResult": cell("ncaa") or None,
        })
    return seasons


def collect(program: dict, registry: dict) -> dict:
    title = program["ids"]["wikipedia"]
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
        "collegeCups": _years(find("college cup")),
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
