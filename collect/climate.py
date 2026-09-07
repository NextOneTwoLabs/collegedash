"""
Climate normals for the campus from NOAA NCEI's official 1991-2020 U.S. Climate Normals
(monthly dataset), served by the NCEI Access Data Service. No API key, no per-call quota.

The nearest normals station to campus supplies the 12 monthly values (airport / first-order
"USW" stations within 60 km preferred, then cooperative "USC" stations); a station is accepted
only when it has complete temperature and precipitation normals. Snow and day-count normals are
optional (many stations do not report snow). Writes programs/<slug>/sources/climate.json.

Replaces the Open-Meteo ERA5 collector: a 30-year daily pull counted as hundreds of API calls
against Open-Meteo's hourly quota, so most bulk runs ended in HTTP 429.
"""

from __future__ import annotations

import math
import urllib.parse

from . import common

NAME = "climate"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

DEFAULTS = {
    "dataApi": "https://www.ncei.noaa.gov/access/services/data/v1",
    "dataset": "normals-monthly-1991-2020",
    "inventory": "https://www.ncei.noaa.gov/data/normals-monthly/1991-2020/doc/inventory_30yr.txt",
    "preferAirportWithinKm": 60,
    "normalsPeriod": "1991-2020",
}
DATATYPES = {
    "MLY-TMAX-NORMAL": "tHighF",
    "MLY-TMIN-NORMAL": "tLowF",
    "MLY-PRCP-NORMAL": "precipIn",
    "MLY-SNOW-NORMAL": "snowIn",
    "MLY-PRCP-AVGNDS-GE010HI": "wetDays",     # days with >= 0.10 in of precipitation
    "MLY-TMAX-AVGNDS-GRTH090": "days90F",    # days with a high >= 90 F
    "MLY-TMIN-AVGNDS-LSTH032": "daysFreeze",  # days with a low <= 32 F
}
REQUIRED = ("tHighF", "tLowF", "precipIn")
MAX_ROUNDS = 3        # candidate batches to try before giving up
CANDIDATES_PER_ROUND = 3

_stations: list[dict] | None = None


def _campus_latlon(program: dict) -> tuple[float, float]:
    loc = program.get("location") or {}
    lat, lon = loc.get("lat"), loc.get("lon")
    if lat is None or lon is None:
        sc = common.load_source(program["slug"], "scorecard")
        if sc and sc["data"].get("lat") is not None:
            lat, lon = sc["data"]["lat"], sc["data"]["lon"]
    if lat is None or lon is None:
        raise common.FetchError(f"climate: no coordinates for {program['slug']}")
    return float(lat), float(lon)


def _load_stations(src: dict) -> list[dict]:
    """The NCEI station inventory (GHCND-stations fixed-width layout), U.S. airport and
    cooperative stations only. Cached in the HTTP cache for a year."""
    global _stations
    if _stations is not None:
        return _stations
    text, _ = common.fetch_text(src.get("inventory", DEFAULTS["inventory"]), max_age_hours=24 * 365, timeout=120)
    out = []
    for line in text.splitlines():
        if len(line) < 40 or not line.startswith(("USW", "USC")):
            continue
        try:
            out.append({
                "id": line[0:11].strip(), "lat": float(line[12:20]), "lon": float(line[21:30]),
                "elevationM": float(line[31:37]) if line[31:37].strip() else None,
                "state": line[38:40].strip(), "name": common.clean(line[41:71]),
            })
        except ValueError:
            continue
    if not out:
        raise common.FetchError("climate: station inventory parsed 0 stations (format change?)")
    _stations = out
    return out


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _candidates(lat: float, lon: float, stations: list[dict], *, skip: set, airport_km: float,
                n: int = CANDIDATES_PER_ROUND) -> list[tuple[dict, float]]:
    """Nearest untried stations: up to two airport (USW) stations within `airport_km`, then the
    nearest cooperative stations, `n` in total."""
    ranked = sorted(((s, _haversine_km(lat, lon, s["lat"], s["lon"])) for s in stations if s["id"] not in skip),
                    key=lambda t: t[1])
    airports = [t for t in ranked if t[0]["id"].startswith("USW") and t[1] <= airport_km][:2]
    picked = list(airports)
    for t in ranked:
        if len(picked) >= n:
            break
        if t not in picked:
            picked.append(t)
    return picked


def _fetch_normals(src: dict, ids: list[str]) -> tuple[dict[str, list[dict]], str, dict]:
    params = {"dataset": src.get("dataset", DEFAULTS["dataset"]), "stations": ",".join(ids),
              "dataTypes": ",".join(DATATYPES), "format": "json", "units": "standard"}
    url = src.get("dataApi", DEFAULTS["dataApi"]) + "?" + urllib.parse.urlencode(params, safe=",")
    payload, meta = common.fetch_json(url, max_age_hours=24 * 365, timeout=120)
    by_station: dict[str, list[dict]] = {}
    for rec in payload if isinstance(payload, list) else []:
        by_station.setdefault(rec.get("STATION", ""), []).append(rec)
    return by_station, url, meta


def _num(v) -> float | None:
    """NCEI values arrive as space-padded strings; -7777 means a trace, -9999 missing."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    if f <= -9000:
        return None
    if f <= -7000:
        return 0.0
    return f


def _monthly_from(records: list[dict]) -> list[dict] | None:
    """12 months in order, or None when temperature/precipitation normals are incomplete."""
    by_month = {}
    for rec in records:
        try:
            m = int(str(rec.get("DATE", "")).strip()[:2])
        except ValueError:
            continue
        if 1 <= m <= 12:
            by_month[m] = rec
    monthly = []
    for m in range(1, 13):
        rec = by_month.get(m)
        if rec is None:
            return None
        row = {"month": MONTHS[m - 1]}
        for dtype, key in DATATYPES.items():
            row[key] = _num(rec.get(dtype))
        if any(row[k] is None for k in REQUIRED):
            return None
        row["tHighF"], row["tLowF"] = round(row["tHighF"], 1), round(row["tLowF"], 1)
        row["precipIn"] = round(row["precipIn"], 2)
        for k in ("snowIn", "wetDays", "days90F", "daysFreeze"):
            if row[k] is not None:
                row[k] = round(row[k], 1)
        monthly.append(row)
    return monthly


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def _sum(xs, digits=1):
    xs = [x for x in xs if x is not None]
    return round(sum(xs), digits) if xs else None


def _summarize(monthly: list[dict]) -> dict:
    annual_precip = _sum(m["precipIn"] for m in monthly)
    annual_snow = _sum(m["snowIn"] for m in monthly) if all(m["snowIn"] is not None for m in monthly) else None
    hottest = max(monthly, key=lambda mo: mo["tHighF"])
    coldest = min(monthly, key=lambda mo: mo["tLowF"])
    # Soccer season is Aug-Nov: summarise those months separately.
    season = [mo for mo in monthly if mo["month"] in ("Aug", "Sep", "Oct", "Nov")]
    fall = {
        "avgHighF": _mean(mo["tHighF"] for mo in season),
        "avgLowF": _mean(mo["tLowF"] for mo in season),
        "precipIn": _sum(mo["precipIn"] for mo in season),
        "wetDays": (round(s, 0) if (s := _sum(mo["wetDays"] for mo in season)) is not None else None),
    }
    snow_clause = ("" if annual_snow is None else f", {annual_snow} in of snow." if annual_snow >= 1 else ", essentially no snow.")
    summary = (
        f"Hottest month {hottest['month']} (avg high {hottest['tHighF']}°F), coldest {coldest['month']} "
        f"(avg low {coldest['tLowF']}°F). {annual_precip} in of rain per year{snow_clause or '.'}"
        f" Fall season (Aug–Nov): highs around {fall['avgHighF']}°F, {fall['precipIn']} in of rain over the season."
    )
    return {"annualPrecipIn": annual_precip, "annualSnowIn": annual_snow, "fallSeason": fall, "summary": summary}


def collect(program: dict, registry: dict) -> dict:
    src = registry["sources"].get("climate") or {}
    lat, lon = _campus_latlon(program)
    stations = _load_stations(src)
    airport_km = float(src.get("preferAirportWithinKm", DEFAULTS["preferAirportWithinKm"]))
    tried: set[str] = set()
    for _ in range(MAX_ROUNDS):
        cands = _candidates(lat, lon, stations, skip=tried, airport_km=airport_km)
        if not cands:
            break
        by_station, url, meta = _fetch_normals(src, [s["id"] for s, _ in cands])
        for station, dist in cands:
            tried.add(station["id"])
            monthly = _monthly_from(by_station.get(station["id"], []))
            if not monthly:
                continue
            data = {
                "lat": lat, "lon": lon, "timezone": (program.get("location") or {}).get("timezone"),
                "elevationM": station["elevationM"], "normalsPeriod": src.get("normalsPeriod", DEFAULTS["normalsPeriod"]),
                "station": {"id": station["id"], "name": station["name"], "state": station["state"],
                            "distanceKm": round(dist, 1), "elevationM": station["elevationM"]},
                "monthly": monthly, **_summarize(monthly),
            }
            common.save_source(program["slug"], NAME, data, url=url, collector=NAME,
                               extra={"provider": "NOAA NCEI 1991-2020 U.S. Climate Normals (monthly)",
                                      "fromCache": meta.get("fromCache", False)})
            common.log(f"climate: {station['id']} {station['name']} ({dist:.0f} km): {data['summary']}")
            return data
    raise common.FetchError(f"climate: no station with complete 1991-2020 normals near {lat:.3f},{lon:.3f} "
                            f"(tried {', '.join(sorted(tried)) or 'none'})")
