"""
Commitments from TopDrawerSoccer (TDS).

Two collectors:
  collect(program, registry)   -> team commitments tab for one program
                                  programs/<slug>/sources/commitments.tds.json
  sweep(registry, grad_years)  -> every girls commit for a class, all pages
                                  data/commitments/tds-girls-<gradYear>.json  (firstSeen/lastSeen per record)

TDS shows no commitment dates; the sweep's firstSeen is our best proxy, and a record that vanishes
from the list is a likely decommit (the team tab is also diffed the same way).
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import common

NAME = "commitments.tds"
TDS = "https://www.topdrawersoccer.com"
CLGID_RE = re.compile(r"/college-soccer-details/women/([a-z0-9-]+)/clgid-(\d+)")


def record_key(name: str, grad_year: int | str) -> str:
    return f"{common.norm_name(name).replace(' ', '-')}-{grad_year}"


def has_commitments_table(html: str) -> bool:
    """True when the team page carries the commitments table at all (it may be empty)."""
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.select("table.tds_table"):
        heads = [common.clean(c.get_text()).lower() for c in table.select("thead td, thead th")]
        if heads and "club" in heads and "name" in heads[0]:
            return True
    return False


def parse_team_commitments(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for table in soup.select("table.tds_table"):
        heads = [common.clean(c.get_text()).lower() for c in table.select("thead td, thead th")]
        if not heads or "club" not in heads or "name" not in heads[0]:
            continue
        idx = {h: i for i, h in enumerate(heads)}
        for tr in table.select("tbody tr"):
            cells = tr.find_all("td")
            if len(cells) < len(heads):
                continue
            a = cells[idx["name"]].find("a")
            name = common.clean(cells[idx["name"]].get_text(" "))
            grad = common.clean(cells[idx.get("year", 1)].get_text())
            if not name or not grad.isdigit():
                continue
            out.append({
                "name": name,
                "gradYear": int(grad),
                "pos": common.norm_pos(common.clean(cells[idx.get("pos.", idx.get("pos", 2))].get_text())),
                "city": common.clean(cells[idx["city"]].get_text()) if "city" in idx else "",
                "state": common.state_code(common.clean(cells[idx["state"]].get_text())) if "state" in idx else "",
                "club": common.clean(cells[idx["club"]].get_text()) if "club" in idx else "",
                "playerUrl": urljoin(TDS, a["href"]) if a and a.get("href") else None,
            })
    return out


def parse_search_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table.tds_table tbody tr"):
        cells = tr.find_all("td")
        if len(cells) < 6:
            continue
        name_cell = cells[0]
        a = name_cell.select_one("a.bd") or name_cell.find("a")
        name = common.clean(a.get_text(" ")) if a else ""
        # club text is the loose text inside .ml-2 after the rating span
        club = ""
        ml = name_cell.select_one(".ml-2")
        if ml:
            loose = [common.clean(t) for t in ml.find_all(string=True, recursive=False)]
            loose = [t for t in loose if t]
            club = loose[0] if loose else ""
            if not club:
                # fallback: all text minus name minus mobile helper divs
                txt = common.clean(ml.get_text(" "))
                txt = re.sub(r"State:\s*\(\w+\)|Pos:\s*\(\w+\)", "", txt).replace(name, "")
                club = common.clean(txt)
        college_a = cells[5].find("a")
        college = common.clean(cells[5].get_text(" "))
        m = CLGID_RE.search(college_a["href"]) if college_a and college_a.get("href") else None
        grad = common.clean(cells[4].get_text())
        if not name or not grad.isdigit():
            continue
        rows.append({
            "name": name,
            "gender": common.clean(cells[1].get_text()),
            "state": common.state_code(common.clean(cells[2].get_text())),
            "pos": common.norm_pos(common.clean(cells[3].get_text())),
            "gradYear": int(grad),
            "club": club,
            "college": college,
            "collegeTdsSlug": m.group(1) if m else None,
            "collegeTdsId": int(m.group(2)) if m else None,
            "playerUrl": urljoin(TDS, a["href"]) if a and a.get("href") else None,
        })
    return rows


def _diff_merge(prev_records: dict, fresh: list[dict], today: str) -> tuple[dict, dict]:
    """Merge a fresh listing into the stored records, maintaining firstSeen/lastSeen and
    flagging records that disappeared. Returns (records, summary)."""
    records = dict(prev_records)
    fresh_keys = set()
    added = []
    for r in fresh:
        k = record_key(r["name"], r["gradYear"])
        fresh_keys.add(k)
        if k in records:
            rec = records[k]
            rec.update({kk: vv for kk, vv in r.items() if vv not in (None, "")})
            rec["lastSeen"] = today
            rec["missingSince"] = None
        else:
            records[k] = {**r, "firstSeen": today, "lastSeen": today, "missingSince": None}
            added.append(k)
    gone = []
    for k, rec in records.items():
        if k not in fresh_keys and rec.get("lastSeen") != today:
            if not rec.get("missingSince"):
                rec["missingSince"] = today
            gone.append(k)
    return records, {"added": added, "missing": gone, "total": len(fresh)}


def collect(program: dict, registry: dict) -> dict:
    ids = program["ids"]
    if not ids.get("tdsClgId") or not ids.get("tdsSlug"):
        raise common.SkipCollector("tds: no TopDrawerSoccer team id in the registry (set ids.tdsClgId + ids.tdsSlug)")
    url = registry["sources"]["tds"]["teamCommitments"].format(tdsSlug=ids["tdsSlug"], tdsClgId=ids["tdsClgId"])
    html, meta = common.fetch_text(url, max_age_hours=12)
    fresh = parse_team_commitments(html)
    if not fresh and not has_commitments_table(html):
        raise common.FetchError(f"tds: no commitments table at {url} (markup change or wrong team id?)")
    if not fresh:
        common.log(f"tds: commitments tab is empty at {url}")
    prev = common.load_source(program["slug"], NAME)
    prev_records = (prev["data"].get("records") if prev else None) or {}
    # If the stored file predates today's diff semantics we still want to keep firstSeen values.
    records, summary = _diff_merge(prev_records, fresh, common.today())
    data = {"records": records, "lastListing": [record_key(r["name"], r["gradYear"]) for r in fresh],
            "summary": summary}
    common.save_source(program["slug"], NAME, data, url=url, collector=NAME,
                       extra={"fromCache": meta.get("fromCache", False)})
    by_year = {}
    for r in fresh:
        by_year[r["gradYear"]] = by_year.get(r["gradYear"], 0) + 1
    common.log(f"tds: {len(fresh)} commits {dict(sorted(by_year.items()))}; new {len(summary['added'])}, missing {len(summary['missing'])}")
    return data


def sweep(registry: dict, grad_years: list[int] | None = None, *, max_pages: int = 80) -> dict:
    """Walk the TDS girls commitments search for each class year and update
    data/commitments/tds-girls-<year>.json."""
    src = registry["sources"]["tds"]
    grad_years = grad_years or registry["season"]["gradYears"]
    out = {}
    for gy in grad_years:
        fresh: list[dict] = []
        for page in range(max_pages):
            url = src["commitSearch"].format(gradYear=gy, page=page)
            html, _ = common.fetch_text(url, max_age_hours=12)
            rows = parse_search_page(html)
            fresh.extend(rows)
            if len(rows) < src.get("pageSize", 25):
                break
        path = f"{common.COMMITS_DATA_DIR}/tds-girls-{gy}.json"
        prev = common.read_json(path, {}) or {}
        records, summary = _diff_merge(prev.get("records") or {}, fresh, common.today())
        common.write_json(path, {"gradYear": gy, "updated": common.now_iso(), "source": src["commitSearch"].format(gradYear=gy, page=0),
                                 "records": records, "summary": summary})
        common.log(f"tds sweep {gy}: {len(fresh)} commits on {page + 1} pages; new {len(summary['added'])}, missing {len(summary['missing'])}")
        out[gy] = summary
    return out
