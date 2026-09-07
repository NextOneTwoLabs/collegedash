"""
Commitments from SoccerWire's player directory, queried through the site's own Elasticsearch
proxy (the same endpoint the directory page uses; the page's ?filter= param is just base64 JSON
of these facets).

collect(program, registry)  -> programs/<slug>/sources/commitments.soccerwire.json
sweep(registry, grad_years) -> data/commitments/soccerwire-girls-<gradYear>.json

Each SoccerWire record has a profile creation date (post_date). Profiles are usually created when
the commitment is reported, so post_date is a reasonable 'announced' proxy - better than nothing,
weaker than a dated press release or social post.
"""

from __future__ import annotations

import os

from . import common
from .commitments_tds import _diff_merge, record_key

NAME = "commitments.soccerwire"
PAGE = 100


def _vals(meta: dict, key: str) -> list[str]:
    arr = meta.get(key) or []
    return [str(x.get("value", "")).strip() for x in arr if str(x.get("value", "")).strip()]


def _record(hit: dict) -> dict | None:
    src = hit["_source"]
    meta = src.get("meta") or {}
    gy = _vals(meta, "graduation_year")
    if not gy or not gy[0].isdigit():
        return None
    clubs = [c for c in _vals(meta, "related_clubs_players") if not c.isdigit()]
    college = _vals(meta, "college_team")
    return {
        "name": common.clean(src.get("post_title", "")),
        "gradYear": int(gy[0]),
        "pos": "/".join(_vals(meta, "positions")),
        "state": common.state_code((_vals(meta, "state_province") or [""])[0]),
        "club": clubs[0] if clubs else "",
        "highSchool": (_vals(meta, "high_school") or [""])[0],
        "college": college[0] if college else "",
        "collegeKey": (meta.get("college_team") or [{}])[0].get("raw"),
        "division": (_vals(meta, "college_division_committed") or [""])[0],
        "isCommitted": (_vals(meta, "is_committed") or ["0"])[0] == "1",
        "playerUrl": src.get("permalink"),
        "profileCreated": (src.get("post_date") or "")[:10] or None,
        "profileModified": (src.get("post_modified") or "")[:10] or None,
    }


def _search(registry: dict, must: list[dict], *, size: int = PAGE, frm: int = 0, max_age_hours: float = 12) -> dict:
    url = registry["sources"]["soccerwire"]["elasticProxy"]
    body = {
        "size": size, "from": frm,
        "sort": [{"post_date": {"order": "desc"}}],
        "query": {"match_all": {}},
        "post_filter": {"bool": {"must": [{"term": {"post_type.raw": "players"}}] + must, "must_not": []}},
    }
    headers = {"Referer": registry["sources"]["soccerwire"]["directory"], "Origin": "https://www.soccerwire.com"}
    payload, meta = common.fetch(url, method="POST", json_body=body, headers=headers, max_age_hours=max_age_hours)
    import json
    return json.loads(payload.decode("utf-8", "replace"))


def team_key(program: dict) -> str:
    ids = program.get("ids") or {}
    return ids.get("soccerwireTeam") or f"{ids.get('tdsSlug') or program['slug']}-women"


def collect(program: dict, registry: dict) -> dict:
    key = team_key(program)
    resp = _search(registry, [{"term": {"meta.college_team.raw": key}}], size=200)
    hits = resp.get("hits", {}).get("hits", [])
    fresh = [r for r in (_record(h) for h in hits) if r]
    tracked = set(registry["season"]["gradYears"])
    fresh_tracked = [r for r in fresh if r["gradYear"] in tracked]
    prev = common.load_source(program["slug"], NAME)
    records, summary = _diff_merge((prev["data"].get("records") if prev else None) or {}, fresh_tracked, common.today())
    data = {"teamKey": key, "records": records, "allRecords": fresh, "summary": summary}
    url = registry["sources"]["soccerwire"]["directory"] + f"#college_team={key}"
    common.save_source(program["slug"], NAME, data, url=url, collector=NAME)
    common.log(f"soccerwire: {len(fresh)} profiles for {key}, {len(fresh_tracked)} in tracked classes; new {len(summary['added'])}")
    return data


def sweep(registry: dict, grad_years: list[int] | None = None) -> dict:
    grad_years = grad_years or registry["season"]["gradYears"]
    out = {}
    for gy in grad_years:
        must = [{"term": {"meta.is_committed.raw": "1"}}, {"term": {"meta.gender.raw": "female"}},
                {"term": {"meta.graduation_year.raw": str(gy)}}]
        fresh, frm = [], 0
        while True:
            resp = _search(registry, must, size=PAGE, frm=frm)
            hits = resp.get("hits", {}).get("hits", [])
            fresh.extend(r for r in (_record(h) for h in hits) if r)
            total = resp.get("hits", {}).get("total", 0)
            total = total.get("value", 0) if isinstance(total, dict) else total
            frm += PAGE
            if frm >= total or not hits:
                break
        path = os.path.join(common.COMMITS_DATA_DIR, f"soccerwire-girls-{gy}.json")
        prev = common.read_json(path, {}) or {}
        records, summary = _diff_merge(prev.get("records") or {}, fresh, common.today())
        common.write_json(path, {"gradYear": gy, "updated": common.now_iso(), "records": records, "summary": summary})
        common.log(f"soccerwire sweep {gy}: {len(fresh)} committed girls; new {len(summary['added'])}, missing {len(summary['missing'])}")
        out[gy] = summary
    return out
