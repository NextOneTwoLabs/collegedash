"""
Roster, staff, schedule and player bios from the program's official athletics website.

Dispatches to collect/adapters/<platform>.py based on program.athletics.platform.
Writes programs/<slug>/sources/athletics.json:
  { season, roster: {season, players[]}, staff[], rosterHistory: {year: players[]},
    schedule: {season, games[]}, scheduleHistory: {year: games[]} }
Player bios are fetched individually (one request per player, cached a week) so that club and
career notes are available; pass bios=False to skip.
"""

from __future__ import annotations

import re

from . import adapters, common

NAME = "athletics"
# Club names as they appear in bios: 1-4 capitalised words ending in a club-ish token.
CLUB_HINT_RE = re.compile(
    r"\b((?:[A-Z][\w.'&-]*\s+){0,3}(?:SC|FC|Surf|Academy|Force|Slammers|Rush|Strikers|Fusion|Blues|Thunder|Rangers|"
    r"Nationals|Courage|Royals|Alliance|Legends|Galaxy|Earthquakes|Timbers|Sounders|Dash|Pride|Spirit|Wave|Fire|Crew|"
    r"Union|Revolution|Rapids|Dynamo|Sporting|Real|Inter|Atl[ée]tico|Athletic|Premier|Elite|Eagles|Stars|United)"
    r"(?:\s+(?:Academy|ECNL|GA|Premier|SC|FC|Soccer Club))?)\b"
)
CLUB_STOP = re.compile(r"tournament|champion|conference|all-|team of|player of|first team|second team|honor|award|"
                       r"national team|academic|scholar|league\b|cup\b|ncaa|pac-12|acc\b|\btime\b|\bthe\b|season", re.I)
CLUB_CONTEXT = re.compile(r"\bclub\b|played (?:club )?for|member of|\bECNL\b|Girls Academy|\bGA\b|MLS Next|"
                          r"Development Academy|\bDA\b", re.I)


def _extract_club(sections: dict) -> str:
    """Best-effort club name from bio text, no LLM. Only accepts a club-shaped phrase that sits in
    a sentence that also mentions club soccer, and rejects phrases that look like honours.
    Returns '' when nothing plausible is found; build.py prefers TDS/SoccerWire club data anyway."""
    ordered = [v for k, v in sections.items() if re.search(r"prior|club|personal|before", k, re.I)]
    ordered += [v for v in sections.values() if v not in ordered]
    for t in ordered:
        for sent in re.split(r"(?<=[.…])\s+|\s*\|\s*", t):
            if not CLUB_CONTEXT.search(sent):
                continue
            for m in CLUB_HINT_RE.finditer(sent):
                cand = common.clean(m.group(1))
                if len(cand.split()) <= 5 and not CLUB_STOP.search(cand) and len(cand) > 3:
                    return cand
    return ""


def detect_platform(html: str) -> str | None:
    """Guess the athletics-site platform from the roster page markup."""
    if "s-person-card" in html or "c-rosterpage" in html or "sidearmsports" in html.lower():
        return "sidearm"
    if "roster-card-item" in html or "roster-list-item" in html or "wmt.digital" in html:
        return "wmt"
    return None


def collect(program: dict, registry: dict, *, seasons_back: int = 3, bios: bool = True) -> dict:
    slug = program["slug"]
    base = program["athletics"].get("baseUrl")
    if not base:
        raise common.FetchError("athletics: no baseUrl in registry (athletics website unknown)")
    platform = program["athletics"].get("platform") or "auto"
    if platform == "auto":
        probe_url = f"{base}{program['athletics']['sportPath']}/roster"
        html0, _ = common.fetch_text(probe_url, max_age_hours=24)
        platform = detect_platform(html0)
        if not platform:
            raise common.FetchError(f"athletics: unsupported site platform at {probe_url}")
        program["athletics"]["platform"] = platform
        reg = common.load_registry()
        for p in reg["programs"]:
            if p["slug"] == slug:
                p["athletics"]["platform"] = platform
        common.save_registry(reg)
        common.log(f"athletics: detected platform '{platform}' for {slug}")
    ad = adapters.get(platform)
    u = ad.urls(program, registry)

    html, meta = common.fetch_text(u["roster"], max_age_hours=24)
    roster = ad.parse_roster(html, base)
    if not roster["players"]:
        raise common.FetchError(f"athletics: roster parse found 0 players at {u['roster']}")
    season = roster["season"] or registry["season"]["current"]
    common.log(f"athletics[{platform}]: {season} roster {len(roster['players'])} players, {len(roster['staff'])} staff")

    if bios:
        for p in roster["players"]:
            try:
                bhtml, _ = common.fetch_text(p["bioUrl"], max_age_hours=24 * 7)
                b = ad.parse_bio(bhtml)
                p["bio"] = {"sections": b.get("sections", {})}
                p["club"] = _extract_club(b.get("sections", {}))
            except common.FetchError as e:
                common.log(f"  bio failed for {p['name']}: {e}")
                p["bio"], p["club"] = {}, ""

    history = {}
    for y in range(season - 1, season - 1 - seasons_back, -1):
        try:
            h, _ = common.fetch_text(u["rosterSeason"](y), max_age_hours=24 * 30)
            r = ad.parse_roster(h, base)
            if r["players"]:
                history[str(y)] = [{k: v for k, v in p.items() if k not in ("bio", "social")} for p in r["players"]]
                common.log(f"  {y} roster: {len(r['players'])} players")
        except common.FetchError as e:
            common.log(f"  {y} roster unavailable: {e}")

    shtml, _ = common.fetch_text(u["schedule"], max_age_hours=12)
    sched = ad.parse_schedule(shtml, base)
    common.log(f"  {sched['season']} schedule: {len(sched['games'])} games")
    sched_hist = {}
    for y in range(season - 1, season - 1 - seasons_back, -1):
        try:
            h, _ = common.fetch_text(u["scheduleSeason"](y), max_age_hours=24 * 30)
            s = ad.parse_schedule(h, base)
            if s["games"]:
                sched_hist[str(y)] = s["games"]
        except common.FetchError as e:
            common.log(f"  {y} schedule unavailable: {e}")

    data = {
        "platform": platform,
        "season": season,
        "roster": {"season": season, "players": roster["players"]},
        "staff": roster["staff"],
        "rosterHistory": history,
        "schedule": {"season": sched["season"] or season, "games": sched["games"]},
        "scheduleHistory": sched_hist,
    }
    common.save_source(slug, NAME, data, url=u["roster"], collector=NAME,
                       extra={"scheduleUrl": u["schedule"], "fromCache": meta.get("fromCache", False)})
    return data
