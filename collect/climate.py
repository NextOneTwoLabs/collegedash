"""
Climate normals for the campus from the Open-Meteo Historical Weather API (ERA5 reanalysis).

Daily max/min temperature (F), precipitation (in) and snowfall (in) for 1991-2020 are aggregated
into 12 monthly normals plus a plain-English summary. Writes programs/<slug>/sources/climate.json.
No API key. The 30-year daily pull is one request (~11k days) and is cached for a year.
"""

from __future__ import annotations

import urllib.parse
from collections import defaultdict

from . import common

NAME = "climate"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _campus_latlon(program: dict) -> tuple[float, float, str]:
    loc = program.get("location") or {}
    lat, lon = loc.get("lat"), loc.get("lon")
    if lat is None or lon is None:
        sc = common.load_source(program["slug"], "scorecard")
        if sc and sc["data"].get("lat") is not None:
            lat, lon = sc["data"]["lat"], sc["data"]["lon"]
    if lat is None or lon is None:
        raise common.FetchError(f"climate: no coordinates for {program['slug']}")
    return float(lat), float(lon), loc.get("timezone", "auto")


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def collect(program: dict, registry: dict) -> dict:
    src = registry["sources"]["climate"]
    lat, lon, tz = _campus_latlon(program)
    y0, y1 = src.get("normalsStart", 1991), src.get("normalsEnd", 2020)
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": f"{y0}-01-01", "end_date": f"{y1}-12-31",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum",
        "temperature_unit": "fahrenheit", "precipitation_unit": "inch", "timezone": tz,
    }
    url = src["api"] + "?" + urllib.parse.urlencode(params)
    payload, meta = common.fetch_json(url, max_age_hours=24 * 365, timeout=120)
    d = payload["daily"]
    days = d["time"]
    # Aggregate: per (year, month) precip/snow totals; per month temperature means.
    tmax = defaultdict(list)
    tmin = defaultdict(list)
    precip_ym = defaultdict(float)
    snow_ym = defaultdict(float)
    wet_ym = defaultdict(int)
    hot_ym = defaultdict(int)
    freeze_ym = defaultdict(int)
    for i, day in enumerate(days):
        y, m = int(day[:4]), int(day[5:7])
        hi, lo = d["temperature_2m_max"][i], d["temperature_2m_min"][i]
        p = d["precipitation_sum"][i] or 0.0
        s = (d["snowfall_sum"][i] or 0.0)
        if hi is not None:
            tmax[m].append(hi)
            if hi >= 90:
                hot_ym[(y, m)] += 1
        if lo is not None:
            tmin[m].append(lo)
            if lo <= 32:
                freeze_ym[(y, m)] += 1
        precip_ym[(y, m)] += p
        snow_ym[(y, m)] += s
        if p >= 0.04:
            wet_ym[(y, m)] += 1
    years = y1 - y0 + 1
    monthly = []
    for m in range(1, 13):
        monthly.append({
            "month": MONTHS[m - 1],
            "tHighF": _mean(tmax[m]),
            "tLowF": _mean(tmin[m]),
            "precipIn": round(sum(v for (y, mm), v in precip_ym.items() if mm == m) / years, 2),
            "snowIn": round(sum(v for (y, mm), v in snow_ym.items() if mm == m) / years, 1),
            "wetDays": round(sum(v for (y, mm), v in wet_ym.items() if mm == m) / years, 1),
            "days90F": round(sum(v for (y, mm), v in hot_ym.items() if mm == m) / years, 1),
            "daysFreeze": round(sum(v for (y, mm), v in freeze_ym.items() if mm == m) / years, 1),
        })
    annual_precip = round(sum(mo["precipIn"] for mo in monthly), 1)
    annual_snow = round(sum(mo["snowIn"] for mo in monthly), 1)
    hottest = max(monthly, key=lambda mo: mo["tHighF"] or -999)
    coldest = min(monthly, key=lambda mo: mo["tLowF"] or 999)
    # Soccer season is Aug-Nov: summarise those months separately.
    season = [mo for mo in monthly if mo["month"] in ("Aug", "Sep", "Oct", "Nov")]
    season_summary = {
        "avgHighF": _mean([mo["tHighF"] for mo in season]),
        "avgLowF": _mean([mo["tLowF"] for mo in season]),
        "precipIn": round(sum(mo["precipIn"] for mo in season), 1),
        "wetDays": round(sum(mo["wetDays"] for mo in season), 0),
    }
    summary = (
        f"Hottest month {hottest['month']} (avg high {hottest['tHighF']}°F), coldest {coldest['month']} "
        f"(avg low {coldest['tLowF']}°F). {annual_precip} in of rain per year"
        + (f", {annual_snow} in of snow." if annual_snow >= 1 else ", essentially no snow.")
        + f" Fall season (Aug–Nov): highs around {season_summary['avgHighF']}°F, "
        f"{season_summary['precipIn']} in of rain over the season."
    )
    data = {
        "lat": lat, "lon": lon, "timezone": payload.get("timezone"), "elevationM": payload.get("elevation"),
        "normalsPeriod": f"{y0}-{y1}", "monthly": monthly,
        "annualPrecipIn": annual_precip, "annualSnowIn": annual_snow,
        "fallSeason": season_summary, "summary": summary,
    }
    common.save_source(program["slug"], NAME, data, url=url, collector=NAME,
                       extra={"provider": "Open-Meteo ERA5", "fromCache": meta.get("fromCache", False)})
    common.log(f"climate: {summary}")
    return data
