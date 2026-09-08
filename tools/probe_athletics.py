"""Find the working athletics-site host and women's soccer path for programs whose roster URL
fails (HTTP 404, dead host, parked domain, connection errors).

    python tools/probe_athletics.py                    # every onboarded program whose athletics run failed
    python tools/probe_athletics.py --slug iowa,notre-dame
    python tools/probe_athletics.py --apply            # write single-hit results to the registry
    python tools/probe_athletics.py --slug iowa --apply --pick 2

For each program it tries the registry host plus any KNOWN_HOSTS override, scrapes the home page
for a women's soccer link, then tries the usual sport paths. A hit is a roster page that the
adapters parse to at least one player. Results go to data/athletics-probe-report.json; --apply
updates athletics.baseUrl / sportPath / platform only for programs with exactly one hit unless
--pick chooses one. Fetches go through the shared HTTP cache, so the following refresh is fast.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.parse import urljoin, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collect import adapters, common  # noqa: E402
from collect.athletics_site import detect_platform  # noqa: E402

KNOWN_HOSTS = {
    "buffalo": "https://ubbulls.com",
    "oral-roberts": "https://oruathletics.com",
    "george-washington": "https://gwsports.com",
    "southeast-missouri-state": "https://semoredhawks.com",
    "quinnipiac": "https://gobobcats.com",
    "louisville": "https://gocards.com",
    "arizona-state": "https://thesundevils.com",
    "texas-am": "https://12thman.com",
    "syracuse": "https://cuse.com",
    "wake-forest": "https://godeacs.com",
    "stony-brook": "https://stonybrookathletics.com",
}
SPORT_PATHS = ["/sports/womens-soccer", "/sports/wsoc", "/sports/w-soccer", "/sports/soccer-w", "/sports/womens-soccer-1",
               "/sports/soccer", "/sports/soc", "/sports/women-soccer", "/sports/womens-soc", "/sports/w-soc",
               "/sport/w-soccer", "/sport/wsoc", "/sport/womens-soccer", "/sport/soccer"]
LINK_RE = re.compile(r"""href=["']([^"']*?/sports?/[a-z0-9-]*(?:w-?soccer|womens-soccer|wsoc|soccer-w|women-soccer|w-soc|soc)[a-z0-9-]*)/?["']""", re.I)
PRESTO_RE = re.compile(r"/sports/wsoc/\d{4}-\d{2}/")
FAIL_RE = re.compile(r"HTTP 404|giving up|SSL|reset|timed out|stub|unsupported site platform|NameResolution|Max retries", re.I)
REPORT_PATH = os.path.join(common.DATA_DIR, "athletics-probe-report.json")


def fetch(url: str) -> tuple[str, dict] | None:
    try:
        body, meta = common.fetch(url, max_age_hours=6, retries=1, timeout=25, allow_status=(200, 301, 302, 403, 404))
    except common.FetchError as e:
        return None
    return body.decode("utf-8", "replace"), meta


def on_host(final_url: str | None, host: str) -> bool:
    if not final_url:
        return True
    return urlparse(final_url).netloc.lower().replace("www.", "") == urlparse(host).netloc.lower().replace("www.", "")


def home_redirect_host(host: str) -> str | None:
    """'https://und.com' -> 'https://fightingirish.com' when the home page redirects off-host."""
    got = fetch(host + "/")
    if not got:
        return None
    final = got[1].get("finalUrl") or ""
    if final and not on_host(final, host):
        u = urlparse(final)
        if u.netloc and "godaddy" not in u.netloc and "forsale" not in final:
            return f"{u.scheme}://{u.netloc}".replace("://www.", "://")
    return None


def looks_presto(host: str) -> bool:
    got = fetch(host + "/")
    return bool(got and PRESTO_RE.search(got[0]))


def discover_sport_paths(host: str) -> list[str]:
    got = fetch(host + "/")
    paths = []
    if got:
        html, meta = got
        if meta.get("status") == 200:
            for m in LINK_RE.finditer(html):
                path = urlparse(urljoin(host, m.group(1))).path.rstrip("/")
                low = path.lower()
                if "mens" in low.replace("womens", "") or "/msoc" in low or "m-soccer" in low:
                    continue
                # keep just the /sports/<sport> prefix
                parts = path.split("/")
                if len(parts) >= 3:
                    p = "/".join(parts[:3])
                    if p not in paths:
                        paths.append(p)
    return paths


def try_roster(host: str, sport_path: str) -> dict | None:
    url = f"{host}{sport_path}/roster"
    got = fetch(url)
    if not got:
        return None
    html, meta = got
    if meta.get("status") != 200 or not on_host(meta.get("finalUrl"), host) or "/lander" in (meta.get("finalUrl") or ""):
        return None
    if len(html) < 5000:
        return None
    platform = detect_platform(html)
    if not platform:
        return None
    roster = adapters.get(platform).parse_roster(html, host)
    if not roster["players"]:
        return None
    return {"baseUrl": host, "sportPath": sport_path, "platform": platform, "players": len(roster["players"]),
            "staff": len(roster["staff"]), "url": url}


def probe(program: dict) -> dict:
    slug = program["slug"]
    a = program["athletics"]
    hosts = []
    for h in (KNOWN_HOSTS.get(slug), a.get("baseUrl")):
        if h and h.rstrip("/") not in hosts:
            hosts.append(h.rstrip("/"))
    for h in list(hosts):  # a dead or renamed domain usually redirects to the live one
        r = home_redirect_host(h)
        if r and r not in hosts:
            common.log(f"probe {slug}: {h} redirects to {r}")
            hosts.insert(0, r)
    tried, hits, notes = [], [], []
    for host in hosts:
        if looks_presto(host):
            notes.append(f"{host} looks like PrestoSports (no adapter)")
            continue
        candidates = discover_sport_paths(host)
        for sp in SPORT_PATHS:
            if sp not in candidates:
                candidates.append(sp)
        for sp in candidates:
            url = f"{host}{sp}/roster"
            tried.append(url)
            hit = try_roster(host, sp)
            if hit:
                hits.append(hit)
                common.log(f"probe {slug}: HIT {url} ({hit['platform']}, {hit['players']} players)")
                break  # first working path per host is enough
        if hits:
            break
    if not hits:
        common.log(f"probe {slug}: no working roster URL among {len(tried)} candidates" + (f"; {'; '.join(notes)}" if notes else ""))
    return {"slug": slug, "current": {"baseUrl": a.get("baseUrl"), "sportPath": a.get("sportPath"), "platform": a.get("platform")},
            "tried": tried, "hits": hits, "notes": notes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", help="comma-separated slugs (default: onboarded programs whose athletics run failed)")
    ap.add_argument("--apply", action="store_true", help="write single-hit results to the registry")
    ap.add_argument("--pick", type=int, help="with --apply --slug: use hit number N (1-based)")
    args = ap.parse_args(argv)

    reg = common.load_registry()
    if args.slug:
        programs = [common.get_program(s.strip(), reg) for s in args.slug.split(",")]
    else:
        state = common.load_refresh_state()
        programs = []
        for p in common.iter_programs(reg):
            e = state.get(f"{p['slug']}.athletics")
            if isinstance(e, dict) and e.get("ok") is False and FAIL_RE.search(str(e.get("error", ""))):
                programs.append(p)
        common.log(f"probe: {len(programs)} programs with URL-shaped athletics failures")
    results = [probe(p) for p in programs]
    common.write_json(REPORT_PATH, {"updated": common.now_iso(), "results": results})

    print()
    for r in results:
        cur = r["current"]
        if r["hits"]:
            for i, h in enumerate(r["hits"], 1):
                print(f"{r['slug']:22} hit {i}: {h['baseUrl']}{h['sportPath']}  [{h['platform']}, {h['players']} players]"
                      f"   (was {cur['baseUrl']}{cur['sportPath']})")
        else:
            print(f"{r['slug']:22} no hit ({len(r['tried'])} tried)" + (f"  {'; '.join(r['notes'])}" if r.get("notes") else ""))
    print(f"\nreport: {REPORT_PATH}")

    if args.apply:
        changes = {}
        for r in results:
            hits = r["hits"]
            if not hits:
                continue
            if args.pick and args.slug:
                hit = hits[args.pick - 1]
            elif len(hits) == 1:
                hit = hits[0]
            else:
                print(f"{r['slug']}: {len(hits)} hits, choose with --slug {r['slug']} --apply --pick N")
                continue
            changes[r["slug"]] = hit

        def mutate(reg):
            for p in reg["programs"]:
                h = changes.get(p["slug"])
                if h:
                    p["athletics"]["baseUrl"] = h["baseUrl"]
                    p["athletics"]["sportPath"] = h["sportPath"]
                    p["athletics"]["platform"] = h["platform"]
                    p["athletics"].pop("note", None)

        if changes:
            common.update_registry(mutate)
            print(f"registry updated for {len(changes)} programs: {', '.join(sorted(changes))}")
        else:
            print("nothing applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
