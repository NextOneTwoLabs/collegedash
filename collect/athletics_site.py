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
from urllib.parse import urlparse

from . import adapters, coach_bio, common

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


SIDEARM_MARKERS = ("s-person-card", "c-rosterpage", "sidearm-roster")
WMT_MARKERS = ("roster-card-item", "roster-list-item", "roster-card__", "player-list-item", "roster-table-cell",
               "itemprop=\"athlete\"", "roster-item__name", "person__name", "wmt-dfp-component", "wmt.digital")


def detect_platform(html: str) -> str | None:
    """Guess the athletics-site platform from the roster page markup. Specific roster markers
    first; the generic 'sidearmsports' string (asset host) only as a last resort, since some WMT
    pages embed Sidearm-hosted images."""
    if any(m in html for m in SIDEARM_MARKERS):
        return "sidearm"
    if any(m in html for m in WMT_MARKERS):
        return "wmt"
    if "sidearmsports" in html.lower():
        return "sidearm"
    return None


def _persist_platform(program: dict, platform: str) -> None:
    """Remember a detected platform in the registry (locked, so a concurrent process cannot
    overwrite it) and on the in-memory program."""
    slug = program["slug"]
    program["athletics"]["platform"] = platform

    def mutate(reg):
        for p in reg["programs"]:
            if p["slug"] == slug:
                p["athletics"]["platform"] = platform

    common.update_registry(mutate)
    common.log(f"athletics: detected platform '{platform}' for {slug}")


def collect(program: dict, registry: dict, *, seasons_back: int = 3, bios: bool = True, coach_bios: bool | None = None) -> dict:
    slug = program["slug"]
    base = program["athletics"].get("baseUrl")
    if not base:
        raise common.FetchError("athletics: no baseUrl in registry (athletics website unknown)")
    if program["athletics"].get("rosterRequiresBrowser"):
        raise common.SkipCollector("athletics: roster is rendered in the browser (registry athletics.rosterRequiresBrowser); "
                                   "needs a headless browser, see athletics.note")
    if program["athletics"].get("skipReason"):  # e.g. PrestoSports site with no adapter
        raise common.SkipCollector(f"athletics: {program['athletics']['skipReason']} (registry athletics.skipReason)")
    platform = program["athletics"].get("platform") or "auto"
    if platform == "auto":
        probe_url = f"{base}{program['athletics']['sportPath']}/roster"
        html0, _ = common.fetch_text(probe_url, max_age_hours=24)
        platform = detect_platform(html0)
        if not platform:
            if len(html0) < 2000:
                raise common.FetchError(f"athletics: {probe_url} is a stub/redirect page ({len(html0)} bytes) - wrong baseUrl?")
            raise common.FetchError(f"athletics: unsupported site platform at {probe_url}")
        _persist_platform(program, platform)
    ad = adapters.get(platform)
    u = ad.urls(program, registry)

    html, meta = common.fetch_text(u["roster"], max_age_hours=24)
    roster = ad.parse_roster(html, base)
    if not roster["players"]:
        # the registry platform may be wrong (detected from a generic marker); trust the markup
        detected = detect_platform(html)
        if detected and detected != platform:
            common.log(f"athletics: registry says {platform} but roster markup looks like {detected}; switching")
            platform = detected
            _persist_platform(program, platform)
            ad = adapters.get(platform)
            u = ad.urls(program, registry)
            html, meta = common.fetch_text(u["roster"], max_age_hours=24)
            roster = ad.parse_roster(html, base)
    if not roster["players"]:
        from .adapters.sidearm import looks_client_rendered
        if looks_client_rendered(html):
            raise common.FetchError(f"athletics: roster page is rendered in the browser at {u['roster']}; "
                                    f"set athletics.rosterRequiresBrowser=true in the registry to skip it")
        raise common.FetchError(f"athletics: roster parse found 0 players at {u['roster']}")
    season = roster["season"] or registry["season"]["current"]
    common.log(f"athletics[{platform}]: {season} roster {len(roster['players'])} players, {len(roster['staff'])} staff")
    staff, staff_url = roster["staff"], None
    if not staff and u.get("coaches"):
        staff = _coaches_page_staff(ad, u["coaches"], base, program["athletics"]["sportPath"])
        staff_url = u["coaches"] if staff else None

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
    # The head coach's bio is its own switch (issue #168): `onboard` and the weekly/full refresh fetch it even with
    # player bios off; coach_bios=None follows `bios`. A run that does not fetch it keeps the stored one.
    head_coach_bio = _coach_bio_for_run(slug, staff, program, bios if coach_bios is None else coach_bios)

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
            if not s["games"]:
                continue
            fall, dated = schedule_season_share(s["games"], y)
            if dated and not 2 * fall > dated:
                # an old-season URL that served another season (issue #301): not stored, so a history year
                # is either that season's page or absent
                common.log(f"  {y} schedule not stored: {fall} of {dated} dated games are Aug-Dec {y}, "
                           f"so the page is not the {y} season")
                continue
            sched_hist[str(y)] = s["games"]
        except common.FetchError as e:
            common.log(f"  {y} schedule unavailable: {e}")

    data = {
        "platform": platform,
        "season": season,
        "roster": {"season": season, "players": roster["players"]},
        "staff": staff,
        "rosterHistory": history,
        "schedule": {"season": sched["season"] or season, "games": sched["games"]},
        "scheduleHistory": sched_hist,
        "headCoachBio": head_coach_bio,
    }
    extra = {"scheduleUrl": u["schedule"], "fromCache": meta.get("fromCache", False)}
    if staff_url:
        extra["staffUrl"] = staff_url  # the staff did not come from sourceUrl
    # Outlook Safe Links wrappers become the links they wrap, wherever they sit: schedule links,
    # bios, staff (issue #160). A wrapper that wraps nothing usable is dropped, never stored.
    data = common.unwrap_links(data)
    common.save_source(slug, NAME, data, url=u["roster"], collector=NAME, extra=extra)
    return data


def schedule_season_share(games: list[dict], year: int) -> tuple[int, int]:
    """(games dated August-December of `year`, games with a date) for a history schedule page (issue #301).

    The collector stores a history year only when more than half of its dated games fall in that window, the
    date half of build.schedule_valid_for (issue #287), which stays the final guard: it also needs a result
    and places undated pages. Some old-season URLs serve the current season (29 stored years were copies of
    2026) and one served a spring schedule (gonzaga 2024); both fail here. A page with no dates is stored and
    left to the build. Dates are ISO (YYYY-MM-DD...), as every adapter writes them."""
    dated = [str(g["date"]) for g in games if g.get("date")]
    fall = [d for d in dated if d[:4] == str(year) and "08" <= d[5:7] <= "12"]
    return len(fall), len(dated)


def _coach_bio_for_run(slug: str, staff: list[dict], program: dict, fetch: bool) -> dict | None:
    """headCoachBio for this run's athletics source (issue #168).

    fetch=False (the daily refresh): the stored headCoachBio is carried forward unchanged. The daily run rewrites
    athletics.json, and writing null here would erase every bio year until the next weekly run. A stored bio that
    belongs to a coach who has since left is harmless: build.head_coach_first_season uses a bio only when its
    name is the current head coach's (same_person), and otherwise falls back to the Wikipedia rule.

    fetch=True: one request for the head coach's bio page. If that request fails and a bio is already stored, the
    stored one is kept rather than replaced by an attempt with no year - a transient error on a Monday should not
    take a published year down for a week. With nothing stored, the failed attempt is recorded as before."""
    previous = ((common.load_source(slug, NAME) or {}).get("data") or {}).get("headCoachBio")
    if not fetch:
        return previous
    fetched = _head_coach_bio(staff, program)
    if fetched is not None and fetched.get("error") and previous and not previous.get("error"):
        common.log(f"  head coach bio: fetch failed; keeping the stored bio for {previous.get('name')}")
        return previous
    return fetched


def _head_coach_bio(staff: list[dict], program: dict) -> dict | None:
    """The head coach's first season as their own bio page states it (issue #168): {name, url, firstSeason,
    conflict, statements}, or None when there is no head coach with a bio link. One request per program,
    cached a week like the player bios, through the same fetch path. A failed fetch stores the attempt
    with no year, so the build falls back to Wikipedia rather than to nothing."""
    head = next((s for s in staff if s.get("isHeadCoach") and s.get("bioUrl")), None)
    if not head:
        return None
    try:
        html, _ = common.fetch_text(head["bioUrl"], max_age_hours=24 * 7)
    except common.FetchError as e:
        common.log(f"  head coach bio failed for {head['name']}: {e}")
        return {"name": head["name"], "url": head["bioUrl"], "firstSeason": None, "conflict": False, "statements": [],
                "error": common.error_text(e, 200)}
    parsed = coach_bio.first_season(html, head["name"], school_names(program))
    common.log(f"  head coach bio: {head['name']} first season {parsed['firstSeason']}"
               + (" (the page contradicts itself)" if parsed["conflict"] else "")
               + f" from {len(parsed['statements'])} statement(s)")
    return {"name": head["name"], "url": head["bioUrl"], **parsed}


def school_names(program: dict) -> list[str]:
    """The names a bio sentence may call this school by: registry name, short name, nickname, and the
    athletics site's host label (goduke, uclabruins)."""
    host = re.sub(r"^https?://(?:www\.)?", "", (program.get("athletics") or {}).get("baseUrl") or "").split("/")[0]
    return [n for n in (program.get("name"), program.get("shortName"), program.get("nickname"), host.split(".")[0]) if n]


def _coaches_page_staff(ad, url: str, base: str, sport_path: str) -> list[dict]:
    """Staff from the sport's own coaches page, for a roster page that lists nobody (issue #145).

    Called only when the roster page yielded zero staff rows, so it can never replace or merge into
    staff the roster page did return, and a program whose roster page lists its staff costs no extra
    request. Measured on the live sites: austin-peay, mississippi-state, louisiana-monroe, michigan,
    texas and yale print no staff on the roster page at all, and each serves its coaches at
    /sports/womens-soccer/coaches as a server-rendered table the roster table parser already reads -
    the older theme's 'Staff Directory' table and the current theme's Name/Title table alike.

    A page that has been redirected off the sport's coaches path (to an athletics-wide staff
    directory, say, or a different site) is not used: every coach of every sport would otherwise be
    published as this program's staff. A failed fetch leaves the program as it was, with no staff.
    """
    try:
        html, meta = common.fetch_text(url, max_age_hours=24)
    except common.FetchError as e:
        common.log(f"  coaches page unavailable: {e}")
        return []
    final_path = urlparse(meta.get("finalUrl") or url).path.rstrip("/").lower()
    if not final_path.endswith(f"{sport_path.rstrip('/')}/coaches".lower()):
        common.log(f"  coaches page redirected to {meta.get('finalUrl')}; not used")
        return []
    staff = ad.parse_roster(html, base)["staff"]
    common.log(f"  roster page lists no staff; {len(staff)} from {url}")
    return staff
