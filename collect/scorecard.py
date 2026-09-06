"""
School facts from the US Department of Education College Scorecard API.

Writes programs/<slug>/sources/scorecard.json. Needs SCORECARD_API_KEY (free, instant, from
https://api.data.gov/signup/). Without it the public DEMO_KEY is used, which is rate limited to
30 requests/hour - fine for onboarding one program at a time.
"""

from __future__ import annotations

import os
import urllib.parse

from . import common

NAME = "scorecard"

FIELDS = [
    "id", "school.name", "school.city", "school.state", "school.zip", "school.school_url",
    "school.locale", "school.carnegie_basic", "school.ownership", "school.religious_affiliation",
    "location.lat", "location.lon",
    "latest.student.size", "latest.student.grad_students",
    "latest.admissions.admission_rate.overall",
    "latest.admissions.sat_scores.25th_percentile.critical_reading",
    "latest.admissions.sat_scores.75th_percentile.critical_reading",
    "latest.admissions.sat_scores.25th_percentile.math",
    "latest.admissions.sat_scores.75th_percentile.math",
    "latest.admissions.sat_scores.average.overall",
    "latest.admissions.act_scores.25th_percentile.cumulative",
    "latest.admissions.act_scores.75th_percentile.cumulative",
    "latest.admissions.act_scores.midpoint.cumulative",
    "latest.cost.tuition.in_state", "latest.cost.tuition.out_of_state",
    "latest.cost.attendance.academic_year", "latest.cost.avg_net_price.overall",
    "latest.completion.completion_rate_4yr_150nt",
    "latest.student.retention_rate.four_year.full_time",
    "latest.earnings.10_yrs_after_entry.median",
]

LOCALE = {
    11: "City: Large", 12: "City: Midsize", 13: "City: Small",
    21: "Suburb: Large", 22: "Suburb: Midsize", 23: "Suburb: Small",
    31: "Town: Fringe", 32: "Town: Distant", 33: "Town: Remote",
    41: "Rural: Fringe", 42: "Rural: Distant", 43: "Rural: Remote",
}
CARNEGIE = {
    15: "Doctoral: Very High Research (R1)", 16: "Doctoral: High Research (R2)",
    17: "Doctoral/Professional", 18: "Master's: Larger", 19: "Master's: Medium", 20: "Master's: Small",
    21: "Baccalaureate: Arts & Sciences", 22: "Baccalaureate: Diverse Fields", 23: "Baccalaureate/Associate's",
}
OWNERSHIP = {1: "Public", 2: "Private nonprofit", 3: "Private for-profit"}


def _api_key(registry: dict) -> tuple[str, bool]:
    env = registry["sources"]["scorecard"].get("keyEnv", "SCORECARD_API_KEY")
    key = os.environ.get(env)
    if key:
        return key, False
    common.log("scorecard: SCORECARD_API_KEY not set, using DEMO_KEY (30 req/hour)")
    return "DEMO_KEY", True


def collect(program: dict, registry: dict) -> dict:
    src = registry["sources"]["scorecard"]
    key, demo = _api_key(registry)
    params = {"api_key": key, "fields": ",".join(FIELDS)}
    unit_id = (program.get("ids") or {}).get("scorecardUnitId")
    if unit_id:
        params["id"] = str(unit_id)
    else:
        params["school.name"] = program["name"]
    url = src["api"] + "?" + urllib.parse.urlencode(params)
    payload, meta = common.fetch_json(url, max_age_hours=24 * 30)
    results = payload.get("results") or []
    if not results:
        raise common.FetchError(f"scorecard: no results for {program['slug']}")
    r = results[0]

    def g(k):
        return r.get(k)

    sat_low = (g("latest.admissions.sat_scores.25th_percentile.critical_reading") or 0) + \
              (g("latest.admissions.sat_scores.25th_percentile.math") or 0)
    sat_high = (g("latest.admissions.sat_scores.75th_percentile.critical_reading") or 0) + \
               (g("latest.admissions.sat_scores.75th_percentile.math") or 0)
    data = {
        "unitId": g("id"),
        "name": g("school.name"),
        "city": g("school.city"),
        "state": g("school.state"),
        "zip": g("school.zip"),
        "website": g("school.school_url"),
        "lat": g("location.lat"),
        "lon": g("location.lon"),
        "localeCode": g("school.locale"),
        "locale": LOCALE.get(g("school.locale"), None),
        "carnegieCode": g("school.carnegie_basic"),
        "carnegie": CARNEGIE.get(g("school.carnegie_basic"), None),
        "ownership": OWNERSHIP.get(g("school.ownership"), None),
        "religiousAffiliation": g("school.religious_affiliation"),
        "undergradEnrollment": g("latest.student.size"),
        "gradEnrollment": g("latest.student.grad_students"),
        "admissionRate": g("latest.admissions.admission_rate.overall"),
        "sat25": sat_low or None,
        "sat75": sat_high or None,
        "satAverage": g("latest.admissions.sat_scores.average.overall"),
        "act25": g("latest.admissions.act_scores.25th_percentile.cumulative"),
        "act75": g("latest.admissions.act_scores.75th_percentile.cumulative"),
        "tuitionInState": g("latest.cost.tuition.in_state"),
        "tuitionOutOfState": g("latest.cost.tuition.out_of_state"),
        "costOfAttendance": g("latest.cost.attendance.academic_year"),
        "netPriceAverage": g("latest.cost.avg_net_price.overall"),
        "gradRate6yr": g("latest.completion.completion_rate_4yr_150nt"),
        "retentionRate": g("latest.student.retention_rate.four_year.full_time"),
        "medianEarnings10yr": g("latest.earnings.10_yrs_after_entry.median"),
    }
    # Never write the API key into the repo.
    public_url = src["api"] + "?" + urllib.parse.urlencode({k: v for k, v in params.items() if k != "api_key"})
    common.save_source(program["slug"], NAME, data, url=public_url, collector=NAME,
                       extra={"demoKey": demo, "fromCache": meta.get("fromCache", False)})
    common.log(f"scorecard: {data['name']} admit {data['admissionRate']} size {data['undergradEnrollment']}")
    return data
