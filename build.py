"""
Merge every program's machine sources (programs/<slug>/sources/*.json), the human-written
curated.json and commitments.reviewed.json into the published profiles under public/data/.

  public/data/programs/<slug>.json   full profile (what the dashboard renders)
  public/data/programs/index.json    one summary row per program (list/filter views)
  public/data/commitments/index.json every resolved commitment across programs

Every section carries _meta {source, url, asOf} so the UI can show provenance and staleness.
Curated fields override machine fields; machines never write curated.json.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from collections import defaultdict

from collect import common
from collect.commitments_tds import record_key

CURRENT_SEASON_FALLBACK = dt.date.today().year
GRADUATING = {"SR", "R-SR", "GR"}
POS_ORDER = ["GK", "D", "M", "F"]
CLASS_ORDER = ["FR", "R-FR", "SO", "R-SO", "JR", "R-JR", "SR", "R-SR", "GR"]
REGIONS = {
    "West": {"CA", "OR", "WA", "NV", "AZ", "UT", "ID", "MT", "WY", "CO", "NM", "HI", "AK"},
    "Midwest": {"OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "KS", "NE", "SD", "ND"},
    "South": {"TX", "OK", "AR", "LA", "MS", "AL", "TN", "KY", "GA", "FL", "SC", "NC"},
    "Mid-Atlantic": {"VA", "WV", "MD", "DC", "DE", "PA", "NJ", "NY"},
    "Northeast": {"CT", "RI", "MA", "VT", "NH", "ME"},
}
NICKNAMES = {"ale": "alessandra", "alex": "alexandra", "liz": "elizabeth", "beth": "elizabeth", "kate": "katherine",
             "katie": "katherine", "maddie": "madeline", "maddy": "madison", "abby": "abigail", "ellie": "eleanor",
             "sam": "samantha", "izzy": "isabella", "bella": "isabella", "sophie": "sophia", "mia": "amelia",
             "gabby": "gabriella", "nat": "natalie", "jess": "jessica", "becca": "rebecca", "lexi": "alexis",
             "lily": "lillian", "olivia": "olivia", "livi": "olivia", "vi": "vienna"}


def region_for(state: str | None) -> str | None:
    for r, states in REGIONS.items():
        if state in states:
            return r
    return None


def _meta(env: dict | None, url: str | None = None) -> dict | None:
    if not env:
        return None
    return {"source": env.get("collector"), "url": url or env.get("sourceUrl"), "asOf": env.get("fetchedAt")}


def _age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        t = dt.datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 86400


# ---------- name matching ----------

def _name_parts(name: str) -> tuple[str, str]:
    parts = common.norm_name(name).split()
    if not parts:
        return "", ""
    first = NICKNAMES.get(parts[0], parts[0])
    return first, parts[-1]


def same_person(a: str, b: str) -> bool:
    """True for exact normalised matches and for obvious variants (nickname vs full first name,
    same last name)."""
    na, nb = common.norm_name(a), common.norm_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    fa, la = _name_parts(a)
    fb, lb = _name_parts(b)
    if la != lb:
        # hyphenated / double last names: accept if one contains the other
        if not (la and lb and (la in nb.split() or lb in na.split())):
            return False
    if fa == fb:
        return True
    if len(fa) >= 3 and len(fb) >= 3 and (fa.startswith(fb) or fb.startswith(fa)):
        return True
    return False


# ---------- RPI ----------

def load_rpi_history() -> dict[int, dict[str, dict]]:
    out = {}
    if not os.path.isdir(common.RPI_OUT_DIR):
        return out
    for f in os.listdir(common.RPI_OUT_DIR):
        if re.fullmatch(r"\d{4}\.json", f):
            d = common.read_json(os.path.join(common.RPI_OUT_DIR, f), {})
            out[int(f[:4])] = {t["team"]: t for t in d.get("teams", [])}
    return out


def load_rpi_current() -> dict | None:
    return common.read_json(os.path.join(common.RPI_OUT_DIR, "current.json"))


def rpi_weekly_for(school: str, season: int) -> list[dict]:
    base = os.path.join(common.RPI_OUT_DIR, "weekly", str(season))
    out = []
    if not os.path.isdir(base):
        return out
    for f in sorted(os.listdir(base)):
        d = common.read_json(os.path.join(base, f), {})
        for t in d.get("teams", []):
            if t.get("school") == school:
                out.append({"through": d.get("throughGames"), "rank": t["rank"], "record": t.get("record")})
                break
    return out


# ---------- sections ----------

def build_program_section(program, wiki, ath) -> dict:
    w = wiki["data"] if wiki else {}
    a = ath["data"] if ath else {}
    staff = a.get("staff", [])
    head = next((s for s in staff if s.get("isHeadCoach")), None)
    seasons = w.get("seasons", [])
    head_name = head["name"] if head else (re.sub(r"\(.*?\)", "", w.get("headCoach") or "").strip() or None)
    since = None
    if head_name and seasons:
        last = _name_parts(head_name)[1]
        yrs = [s["year"] for s in seasons if s.get("headCoach") and _name_parts(s["headCoach"])[1] == last]
        since = min(yrs) if yrs else None
    wins = sum(s.get("wins") or 0 for s in seasons)
    losses = sum(s.get("losses") or 0 for s in seasons)
    ties = sum(s.get("ties") or 0 for s in seasons)
    coaches = [s for s in staff if s.get("isCoach")]
    support = [s for s in staff if not s.get("isCoach")]
    return {
        "headCoach": {"name": head_name, "title": head["title"] if head else None,
                      "since": since, "seasons": (CURRENT_SEASON_FALLBACK - since + 1) if since else None,
                      "bioUrl": head["bioUrl"] if head else None, "social": head.get("social", {}) if head else {}},
        "coaches": coaches,
        "supportStaff": support,
        "stadium": w.get("stadium"),
        "founded": w.get("founded"),
        "nationalTitles": w.get("nationalTitles", []),
        "nationalRunnerUp": w.get("nationalRunnerUp", []),
        "collegeCups": w.get("collegeCups", []),
        "ncaaAppearances": w.get("ncaaAppearances", []),
        "confRegularSeasonTitles": w.get("confRegularSeasonTitles", []),
        "confTournamentTitles": w.get("confTournamentTitles", []),
        "allTimeRecord": {"wins": wins, "losses": losses, "ties": ties,
                          "winPct": round((wins + 0.5 * ties) / (wins + losses + ties), 3) if (wins + losses + ties) else None,
                          "seasons": len(seasons)},
        "_meta": {"wikipedia": _meta(wiki, w.get("pageUrl")), "athletics": _meta(ath)},
    }


def _record_from_games(games: list[dict]) -> dict:
    real = [g for g in games if not g.get("exhibition")]
    w = sum(1 for g in real if g.get("result") == "W")
    l = sum(1 for g in real if g.get("result") == "L")
    t = sum(1 for g in real if g.get("result") == "T")
    conf = [g for g in real if g.get("conferenceGame")]
    cw = sum(1 for g in conf if g.get("result") == "W")
    cl = sum(1 for g in conf if g.get("result") == "L")
    ct = sum(1 for g in conf if g.get("result") == "T")
    return {"wins": w, "losses": l, "ties": t, "text": f"{w}-{l}-{t}", "played": w + l + t, "scheduled": len(real),
            "confText": f"{cw}-{cl}-{ct}" if conf else None, "exhibitions": len(games) - len(real)}


def build_seasons(program, wiki, ath, rpi_hist, rpi_cur, registry) -> list[dict]:
    ids = program["ids"]
    hist_name = ids.get("rpiHistoryName") or program["shortName"]
    ncaa_name = ids.get("ncaaName") or program["shortName"]
    seasons = {s["year"]: dict(s) for s in ((wiki or {}).get("data", {}).get("seasons") or [])}
    cur_season = registry["season"]["current"]
    a = (ath or {}).get("data", {})
    # Current season from the live schedule (Wikipedia lags).
    sched = a.get("schedule") or {}
    if sched.get("games"):
        yr = sched.get("season") or cur_season
        rec = _record_from_games(sched["games"])
        s = seasons.setdefault(yr, {"year": yr, "label": str(yr)})
        s.update({"record": rec["text"], "wins": rec["wins"], "losses": rec["losses"], "ties": rec["ties"],
                  "inProgress": rec["played"] < rec["scheduled"], "gamesPlayed": rec["played"]})
        if rec.get("confText") and rec["confText"] != "0-0-0" and not s.get("confRecord"):
            s["confRecord"] = rec["confText"]
        if not s.get("headCoach"):
            head = next((st["name"] for st in a.get("staff", []) if st.get("isHeadCoach")), None)
            s["headCoach"] = head
    # Prior seasons' schedules give conference-record-free but reliable records too.
    for y, games in (a.get("scheduleHistory") or {}).items():
        s = seasons.setdefault(int(y), {"year": int(y), "label": y})
        if not s.get("record"):
            rec = _record_from_games(games)
            s.update({"record": rec["text"], "wins": rec["wins"], "losses": rec["losses"], "ties": rec["ties"]})
    for y, s in seasons.items():
        h = (rpi_hist.get(y) or {}).get(hist_name)
        if h:
            s["rpiRank"] = h.get("rpiRank")
            s["rpi"] = {"rank": h.get("rpiRank"), "sosRank": h.get("sosRank"), "balancedRank": h.get("balancedRpiRank"),
                        "kpiRank": h.get("kpiRank"), "masseyRank": h.get("masseyRank"), "ncaaSeed": h.get("ncaaSeed"),
                        "source": "end-of-season (Henderson archive)"}
        if rpi_cur and rpi_cur.get("season") == y:
            row = next((t for t in rpi_cur["teams"] if t.get("school") == ncaa_name), None)
            if row:
                s["rpiRank"] = row["rank"]
                s["rpi"] = {"rank": row["rank"], "record": row.get("record"), "through": rpi_cur.get("throughGames"),
                            "prevRank": row.get("prevRank"), "source": "NCAA.com weekly RPI",
                            "weekly": rpi_weekly_for(ncaa_name, y)}
    return [seasons[y] for y in sorted(seasons, reverse=True)]


def build_club_lookup(tds, sw) -> dict[str, dict]:
    """norm name -> {club, source} from every commitment record we hold for this program,
    including past classes (SoccerWire returns alumni profiles too)."""
    out = {}
    for r in ((sw or {}).get("data", {}).get("allRecords") or []):
        if r.get("club"):
            out[common.norm_name(r["name"])] = {"club": r["club"], "source": "SoccerWire"}
    for r in ((tds or {}).get("data", {}).get("records") or {}).values():
        if r.get("club"):
            out[common.norm_name(r["name"])] = {"club": r["club"], "source": "TopDrawerSoccer"}
    return out


def build_roster(ath, club_lookup: dict | None = None) -> tuple[dict | None, dict]:
    a = (ath or {}).get("data") or {}
    roster = a.get("roster")
    if not roster:
        return None, {}
    players = []
    matrix = {p: {c: 0 for c in CLASS_ORDER} for p in POS_ORDER}
    for p in roster["players"]:
        q = dict(p)
        secs = (q.get("bio") or {}).get("sections") or {}
        q["bio"] = {k: (v[:1500] + "…" if len(v) > 1500 else v) for k, v in secs.items()}
        # Club: recruiting databases are far more reliable than bio-text regex.
        known = club_lookup.get(common.norm_name(q["name"])) if club_lookup else None
        if not known and club_lookup:
            known = next((v for n, v in club_lookup.items() if same_person(n, q["name"])), None)
        if known:
            q["club"], q["clubSource"] = known["club"], known["source"]
        elif q.get("club"):
            q["clubSource"] = "bio text (unverified)"
        else:
            q["clubSource"] = None
        players.append(q)
        pos = (q.get("pos") or "").split("/")[0]
        cls = q.get("classCode") or ""
        if pos in matrix and cls in matrix[pos]:
            matrix[pos][cls] += 1
    graduating = defaultdict(int)
    for p in players:
        if p.get("classCode") in GRADUATING:
            graduating[(p.get("pos") or "?").split("/")[0]] += 1
    by_class = defaultdict(int)
    for p in players:
        by_class[p.get("classCode") or "?"] += 1
    hist = {}
    cur_names = {common.norm_name(p["name"]) for p in players}
    for y, plist in (a.get("rosterHistory") or {}).items():
        names = {common.norm_name(p["name"]) for p in plist}
        hist[y] = {"count": len(plist),
                   "players": [{k: p.get(k) for k in ("number", "name", "pos", "classCode", "hometown", "highSchool")} for p in plist],
                   "departed": sorted(n for n in names - cur_names) if int(y) == roster["season"] - 1 else None}
    return ({"season": roster["season"], "count": len(players), "players": players,
             "byPosClass": matrix, "byClass": dict(by_class), "graduatingByPos": dict(graduating),
             "_meta": _meta(ath)}, hist)


def build_schedule(ath) -> dict | None:
    a = (ath or {}).get("data") or {}
    s = a.get("schedule")
    if not s:
        return None
    rec = _record_from_games(s["games"])
    hist = {y: {"record": _record_from_games(g)["text"], "games": g} for y, g in (a.get("scheduleHistory") or {}).items()}
    return {"season": s.get("season"), "record": rec, "games": s["games"], "history": hist,
            "_meta": _meta(ath, (ath or {}).get("scheduleUrl"))}


# ---------- commitments ----------

def resolve_commitments(program, tds, sw, reviewed, news, roster, registry) -> list[dict]:
    slug = program["slug"]
    tracked = set(registry["season"]["gradYears"])
    merged: list[dict] = []

    def find(name, gy):
        for c in merged:
            if c["gradYear"] == gy and (same_person(c["name"], name) or any(same_person(al, name) for al in c["aliases"])):
                return c
        return None

    def add(rec: dict, source: dict, *, prefer: bool):
        gy = rec["gradYear"]
        if gy not in tracked:
            return
        c = find(rec["name"], gy)
        if c is None:
            c = {"id": record_key(rec["name"], gy), "name": rec["name"], "aliases": [], "gradYear": gy,
                 "pos": rec.get("pos") or "", "club": rec.get("club") or "", "state": rec.get("state") or "",
                 "city": rec.get("city") or "", "highSchool": rec.get("highSchool") or "",
                 "college": slug, "status": "verbal", "announced": None, "announcedSource": None,
                 "firstSeen": None, "sources": [], "flags": []}
            merged.append(c)
        else:
            if common.norm_name(rec["name"]) != common.norm_name(c["name"]) and rec["name"] not in c["aliases"]:
                c["aliases"].append(rec["name"])
                if "name-variant" not in c["flags"]:
                    c["flags"].append("name-variant")
            if prefer and rec["name"] != c["name"]:
                c["aliases"].append(c["name"])
                c["name"] = rec["name"]
                c["id"] = record_key(rec["name"], gy)
        for k in ("pos", "club", "state", "city", "highSchool"):
            v = rec.get(k) or ""
            if v and (prefer or not c[k]):
                c[k] = v
        c["sources"].append(source)
        fs = source.get("firstSeen")
        if fs and (c["firstSeen"] is None or fs < c["firstSeen"]):
            c["firstSeen"] = fs

    tds_url = registry["sources"]["tds"]["teamCommitments"].format(tdsSlug=program["ids"]["tdsSlug"], tdsClgId=program["ids"]["tdsClgId"])
    for key, r in ((tds or {}).get("data", {}).get("records") or {}).items():
        add(r, {"kind": "tds", "url": r.get("playerUrl") or tds_url, "listUrl": tds_url,
                "firstSeen": r.get("firstSeen"), "lastSeen": r.get("lastSeen"), "missingSince": r.get("missingSince")}, prefer=True)
    for key, r in ((sw or {}).get("data", {}).get("records") or {}).items():
        if not r.get("isCommitted", True):
            continue
        add(r, {"kind": "soccerwire", "url": r.get("playerUrl"), "firstSeen": r.get("firstSeen"),
                "lastSeen": r.get("lastSeen"), "missingSince": r.get("missingSince"),
                "profileCreated": r.get("profileCreated")}, prefer=False)
    for r in (reviewed or {}).get("approved", []):
        src = {"kind": r.get("sourceKind", "social"), "url": r.get("sourceUrl"), "postedAt": r.get("postedAt"),
               "approvedAt": r.get("approvedAt"), "note": r.get("note")}
        add(r, src, prefer=False)

    # manual merges: [{"from": "<id>", "into": "<id>"}]
    for m in (reviewed or {}).get("merges", []):
        a = next((c for c in merged if c["id"] == m.get("from")), None)
        b = next((c for c in merged if c["id"] == m.get("into")), None)
        if a and b and a is not b:
            b["aliases"].append(a["name"])
            b["sources"].extend(a["sources"])
            for k in ("pos", "club", "state", "city", "highSchool"):
                b[k] = b[k] or a[k]
            merged.remove(a)

    roster_names = [p["name"] for p in (roster or {}).get("players", [])]
    recruiting_news = ((news or {}).get("data", {}).get("recruitingItems") or [])
    overrides = (reviewed or {}).get("statusOverrides", {})
    for c in merged:
        kinds = {s["kind"] for s in c["sources"]}
        # announced: only dates that really mark the announcement (dated social post you approved,
        # press release). SoccerWire profile dates and our own first-seen dates are approximations
        # kept separately so the UI can label them honestly.
        dated, approx = [], []
        for s in c["sources"]:
            if s.get("postedAt") and s["kind"] not in ("tds", "soccerwire"):
                dated.append((s["postedAt"], s["kind"]))
            if s.get("profileCreated"):
                approx.append((s["profileCreated"], "SoccerWire profile created"))
        for n in recruiting_news:
            if any(w in common.norm_name(n["title"]) for w in [common.norm_name(c["name"])] if w):
                c["sources"].append({"kind": "press_release", "url": n["url"], "postedAt": n.get("date"), "title": n["title"]})
                kinds.add("press_release")
                if n.get("date"):
                    dated.append((n["date"], "press_release"))
        if c.get("firstSeen"):
            approx.append((c["firstSeen"], "first seen by CollegeDash"))
        if dated:
            dated.sort()
            c["announced"], c["announcedSource"] = dated[0]
        c["approxDate"] = None
        if approx:
            approx.sort()
            # profile-created beats first-seen when both exist; prefer the earliest plausible one
            c["approxDate"] = {"date": approx[0][0], "basis": approx[0][1]}
        # status
        if any(same_person(c["name"], rn) or any(same_person(al, rn) for al in c["aliases"]) for rn in roster_names):
            c["status"] = "enrolled"
        elif "press_release" in kinds:
            c["status"] = "signed"
        if all(s.get("missingSince") for s in c["sources"] if s["kind"] in ("tds", "soccerwire")) and \
                any(s["kind"] in ("tds", "soccerwire") for s in c["sources"]) and c["status"] != "enrolled":
            c["flags"].append("possibly-decommitted")
        if c["id"] in overrides:
            c["status"] = overrides[c["id"]]
        independent = {k for k in kinds if k != "soccerwire_profile"}
        c["confidence"] = "confirmed" if (len(independent) >= 2 or "press_release" in kinds or c["status"] == "enrolled") else "single-source"
        c["sourceKinds"] = sorted(kinds)
    merged.sort(key=lambda c: (c["gradYear"], common.norm_name(c["name"])))
    return merged


# ---------- profile ----------

def build_profile(program: dict, registry: dict, rpi_hist, rpi_cur) -> dict:
    slug = program["slug"]
    S = lambda n: common.load_source(slug, n)
    scorecard, climate, wiki, ath = S("scorecard"), S("climate"), S("wikipedia"), S("athletics")
    tds, sw, news = S("commitments.tds"), S("commitments.soccerwire"), S("news")
    curated = common.load_curated(slug)
    reviewed = common.load_reviewed(slug)

    roster, roster_hist = build_roster(ath, build_club_lookup(tds, sw))
    a = program["athletics"]
    profile = {
        "slug": slug, "name": program["name"], "shortName": program.get("shortName"), "nickname": program.get("nickname"),
        "division": program.get("division", "D1"), "conference": program.get("conference"),
        "colors": program.get("colors"), "ids": program.get("ids", {}), "social": program.get("social", {}),
        "links": {
            "athletics": a["baseUrl"] + a["sportPath"], "roster": a["baseUrl"] + a["sportPath"] + "/roster",
            "schedule": a["baseUrl"] + a["sportPath"] + "/schedule", "news": a["baseUrl"] + a["sportPath"] + "/news",
            "tds": registry["sources"]["tds"]["team"].format(tdsSlug=program["ids"]["tdsSlug"], tdsClgId=program["ids"]["tdsClgId"]),
            "wikipedia": (wiki or {}).get("data", {}).get("pageUrl"),
            "x": f"https://x.com/{program['social']['x']}" if program.get("social", {}).get("x") else None,
            "instagram": f"https://www.instagram.com/{program['social']['instagram']}/" if program.get("social", {}).get("instagram") else None,
        },
        "school": ({**scorecard["data"], "region": region_for(scorecard["data"].get("state")), "_meta": _meta(scorecard)} if scorecard else None),
        "climate": ({**climate["data"], "_meta": _meta(climate)} if climate else None),
        "program": build_program_section(program, wiki, ath),
        "seasons": build_seasons(program, wiki, ath, rpi_hist, rpi_cur, registry),
        "roster": roster,
        "rosterHistory": roster_hist,
        "schedule": build_schedule(ath),
        "commitments": resolve_commitments(program, tds, sw, reviewed, news, roster, registry),
        "news": ({"recruiting": (news["data"].get("recruitingItems") or [])[:25], "latest": (news["data"].get("items") or [])[:12],
                  "_meta": _meta(news)} if news else None),
        "curated": {k: v for k, v in curated.items() if not k.startswith("_") and k != "overrides"},
    }
    # curated overrides: {"program": {"headCoach": {"since": 2003}}, "school": {...}}
    for section, patch in (curated.get("overrides") or {}).items():
        if isinstance(profile.get(section), dict) and isinstance(patch, dict):
            _deep_update(profile[section], patch)

    commits_by_year = defaultdict(int)
    for c in profile["commitments"]:
        commits_by_year[str(c["gradYear"])] += 1
    profile["commitmentsByYear"] = dict(sorted(commits_by_year.items()))
    profile["_build"] = _build_meta(profile, {"athletics": ath, "tds": tds, "soccerwire": sw, "news": news, "scorecard": scorecard})
    return profile


def _deep_update(dst: dict, patch: dict):
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_update(dst[k], v)
        else:
            dst[k] = v


def _build_meta(profile: dict, envs: dict) -> dict:
    checks = {
        "school": bool(profile.get("school")),
        "climate": bool(profile.get("climate")),
        "program": bool(profile["program"].get("headCoach", {}).get("name")),
        "seasons": bool(profile.get("seasons")),
        "rpi": any(s.get("rpiRank") for s in profile.get("seasons", [])),
        "roster": bool(profile.get("roster")),
        "schedule": bool(profile.get("schedule")),
        "commitments": bool(profile.get("commitments")),
        "news": bool(profile.get("news")),
        "curated.programSummary": bool(profile["curated"].get("programSummary")),
        "curated.playingStyle": bool(profile["curated"].get("playingStyle")),
        "curated.myFitNotes": bool(profile["curated"].get("myFitNotes")),
    }
    thresholds = {"athletics": 14, "tds": 3, "soccerwire": 3, "news": 7, "scorecard": 120}
    stale = []
    for k, env in envs.items():
        age = _age_days((env or {}).get("fetchedAt"))
        if env is None:
            stale.append(f"{k}: never collected")
        elif age is not None and age > thresholds.get(k, 30):
            stale.append(f"{k}: {age:.0f}d old")
    return {"builtAt": common.now_iso(), "completeness": round(sum(checks.values()) / len(checks), 2),
            "sections": checks, "stale": stale}


def summary_row(p: dict) -> dict:
    school = p.get("school") or {}
    seasons = p.get("seasons") or []
    cur = next((s for s in seasons if s.get("inProgress")), None)
    last_final = next((s for s in seasons if not s.get("inProgress") and s.get("record")), None)
    return {
        "slug": p["slug"], "name": p["name"], "shortName": p.get("shortName"), "nickname": p.get("nickname"),
        "conference": p.get("conference"), "division": p.get("division"), "colors": p.get("colors"),
        "city": school.get("city"), "state": school.get("state"), "region": school.get("region"),
        "ownership": school.get("ownership"), "undergradEnrollment": school.get("undergradEnrollment"),
        "admissionRate": school.get("admissionRate"), "sat25": school.get("sat25"), "sat75": school.get("sat75"),
        "headCoach": p["program"]["headCoach"].get("name"), "coachSince": p["program"]["headCoach"].get("since"),
        "nationalTitles": len(p["program"].get("nationalTitles") or []),
        "collegeCups": len(p["program"].get("collegeCups") or []),
        "currentSeason": ({"year": cur["year"], "record": cur.get("record"), "rpiRank": cur.get("rpiRank")} if cur else None),
        "lastSeason": ({"year": last_final["year"], "record": last_final.get("record"), "rpiRank": last_final.get("rpiRank"),
                        "ncaaResult": last_final.get("ncaaResult")} if last_final else None),
        "rpiHistory": [{"year": s["year"], "rank": s.get("rpiRank")} for s in seasons if s.get("rpiRank")],
        "rosterSize": (p.get("roster") or {}).get("count"),
        "commitmentsByYear": p.get("commitmentsByYear", {}),
        "fallClimate": (p.get("climate") or {}).get("fallSeason"),
        "completeness": p["_build"]["completeness"], "stale": p["_build"]["stale"], "builtAt": p["_build"]["builtAt"],
        "tags": (p.get("curated") or {}).get("tags", []),
    }


def build(registry: dict) -> list[dict]:
    rpi_hist = load_rpi_history()
    rpi_cur = load_rpi_current()
    rows, all_commits = [], []
    for program in common.iter_programs(registry):
        profile = build_profile(program, registry, rpi_hist, rpi_cur)
        common.write_json(os.path.join(common.PROGRAMS_OUT_DIR, f"{program['slug']}.json"), profile)
        rows.append(summary_row(profile))
        for c in profile["commitments"]:
            all_commits.append({**{k: v for k, v in c.items() if k != "sources"}, "sourceCount": len(c["sources"]),
                                "collegeName": program.get("shortName") or program["name"]})
        common.log(f"build: {program['slug']} completeness {profile['_build']['completeness']} "
                   f"({len(profile['commitments'])} commits, {len(profile['seasons'])} seasons)"
                   + (f" stale: {profile['_build']['stale']}" if profile["_build"]["stale"] else ""))
    common.write_json(os.path.join(common.PROGRAMS_OUT_DIR, "index.json"),
                      {"updated": common.now_iso(), "season": registry["season"], "programs": rows})
    common.write_json(os.path.join(common.COMMITS_OUT_DIR, "index.json"),
                      {"updated": common.now_iso(), "commitments": all_commits})
    validate(registry)
    return rows


def validate(registry: dict, verbose: bool = False) -> bool:
    ok = True
    schema = common.read_json(common.SCHEMA_PATH)
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
        if verbose:
            print("jsonschema not installed; skipping schema validation (pip install jsonschema)")
    for program in common.iter_programs(registry):
        path = os.path.join(common.PROGRAMS_OUT_DIR, f"{program['slug']}.json")
        p = common.read_json(path)
        if not p:
            print(f"MISSING {path}")
            ok = False
            continue
        if schema and jsonschema:
            errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(p), key=lambda e: list(e.path))
            for e in errs[:10]:
                print(f"SCHEMA {program['slug']}: {'/'.join(str(x) for x in e.path)}: {e.message[:160]}")
            ok = ok and not errs
        if verbose:
            b = p["_build"]
            missing = [k for k, v in b["sections"].items() if not v]
            print(f"{program['slug']}: completeness {b['completeness']}; missing {missing or 'none'}; stale {b['stale'] or 'none'}")
    return ok


if __name__ == "__main__":
    build(common.load_registry())
