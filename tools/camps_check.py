"""Offline checks for the camps collector (collect/camps.py). No live requests, nothing written
under programs/, public/ or .cache/ (the robots fixtures use a temporary cache directory).

    python tools/camps_check.py                      # discovery sweep over every cached roster page
    python tools/camps_check.py --slug duke,stanford # a few programs
    python tools/camps_check.py --min-found 260      # exit 1 when fewer programs get a camps link
    python tools/camps_check.py --titles             # news titles: accepted / rejected by mine_camp_news
    python tools/camps_check.py --fixtures           # regression fixtures under tests/fixtures/camps/
    python tools/camps_check.py --cache-dir "D:/Projects/CollegeDash/.cache/http"   # read another checkout's cache

The sweep reads roster pages from the HTTP cache (.cache/http). A git worktree has no cache of its
own: run the sweep from the main checkout, or point --cache-dir at its cache (read only).

Sweep outcomes: found-external | found-hub (internal Sidearm /sports/YYYY/M/D/ page, followed live) |
found-internal | none | skipped (registry skipReason, no campsUrl) | not-cached
"""

from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import os
import sys
import tempfile
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import adapters, camps, common  # noqa: E402
import build  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "camps")


def cached_body(url: str) -> str | None:
    key = common._cache_key("GET", url, None)
    gz = os.path.join(common.CACHE_DIR, key + ".body.gz")
    plain = os.path.join(common.CACHE_DIR, key + ".body")
    if os.path.exists(gz):
        with gzip.open(gz, "rb") as f:
            return f.read().decode("utf-8", "replace")
    if os.path.exists(plain):
        with open(plain, "rb") as f:
            return f.read().decode("utf-8", "replace")
    return None


# ---------- discovery sweep ----------

def check(program: dict, registry: dict) -> dict:
    a = program["athletics"]
    base = a.get("baseUrl") or ""
    out = {"slug": program["slug"], "host": common._host(base), "platform": a.get("platform")}
    if a.get("campsUrl"):
        out.update(outcome="registry", url=a["campsUrl"])
        return out
    if a.get("skipReason"):
        out["outcome"] = "skipped"
        return out
    platform = a.get("platform") or "auto"
    url = adapters.get(platform).urls(program, registry)["roster"] if platform != "auto" else f"{base}{a.get('sportPath', '')}/roster"
    html = cached_body(url)
    if html is None:
        out["outcome"] = "not-cached"
        return out
    link = camps.find_camps_link(html, url)
    if not link:
        out["outcome"] = "none"
        return out
    out.update(url=link["url"], text=link["text"], via=link["via"], linkHost=camps._host(link["url"]))
    if not camps._same_site(link["url"], out["host"]):
        out["outcome"] = "found-external"
    elif camps.HUB_PATH_RE.search(urlparse(link["url"]).path) and not (link["female"] or link["soccer"]):
        out["outcome"] = "found-hub"
    else:
        out["outcome"] = "found-internal"
    return out


def sweep(args) -> int:
    reg = common.load_registry()
    programs = [common.get_program(s.strip(), reg) for s in args.slug.split(",")] if args.slug else list(common.iter_programs(reg))
    results = [check(p, reg) for p in programs]
    by = collections.Counter(r["outcome"] for r in results)
    for r in results:
        line = f"{r['slug']:24} {r['outcome']:15}"
        if r.get("url"):
            line += f" {r['url'][:80]}"
            if r.get("text"):
                line += f"  [{r['via']}: {r['text'][:40]}]"
        print(line)
    found = sum(v for k, v in by.items() if k.startswith("found") or k == "registry")
    print()
    print("summary:", ", ".join(f"{k} {v}" for k, v in sorted(by.items())), f"(of {len(results)}); found {found}")
    hosts = collections.Counter(r.get("linkHost") for r in results if r["outcome"] == "found-external")
    print("top external hosts:", ", ".join(f"{h} {n}" for h, n in hosts.most_common(12)))
    if args.json:
        common.write_json(args.json, results)
    return 0 if found >= args.min_found else 1


# ---------- news titles ----------

def titles(args) -> int:
    items = []
    for f in sorted(glob.glob(os.path.join(common.PROGRAMS_DIR, "*", "sources", "news.json"))):
        slug = os.path.basename(os.path.dirname(os.path.dirname(f)))
        for it in (common.read_json(f) or {}).get("data", {}).get("items") or []:
            items.append({**it, "slug": slug})
    accepted, rejected = camps.mine_camp_news(items)
    print(f"{len(items)} archived news items; {len(accepted)} accepted, {len(rejected)} rejected")
    print("\nACCEPTED")
    for it in accepted:
        print(f"  {it['slug']:22} {it.get('date') or '':10} {it['title'][:90]}")
    print("\nREJECTED")
    for it in rejected:
        print(f"  {it['slug']:22} {it['why']:16} {it['title'][:80]}")
    return 0


# ---------- fixtures ----------

def _read(rel: str) -> str:
    with open(os.path.join(FIXTURES, rel), encoding="utf-8") as f:
        return f.read()


def fixtures(args) -> int:
    spec = json.load(open(os.path.join(FIXTURES, "fixtures.json"), encoding="utf-8"))
    fails, total = [], 0

    def ok(name: str, cond: bool, detail: str = ""):
        nonlocal total
        total += 1
        print(f"  {'ok  ' if cond else 'FAIL'} {name}{(' - ' + detail) if detail and not cond else ''}")
        if not cond:
            fails.append(name)

    print("nav: find_camps_link")
    for fx in spec["nav"]:
        link = camps.find_camps_link(_read(fx["file"]), fx["pageUrl"])
        got = link and link["url"]
        ok(fx["file"], got == fx["expect"] and (fx.get("via") is None or (link and link["via"] == fx["via"])),
           f"got {got!r} via {link and link['via']}, expected {fx['expect']!r}")
    print("hub: find_hub_hop")
    for fx in spec["hub"]:
        hop = camps.find_hub_hop(_read(fx["file"]), fx["pageUrl"], set(fx.get("exclude") or []))
        got = hop and hop["url"]
        ok(fx["file"], got == fx["expect"], f"got {got!r}, expected {fx['expect']!r}")
    print("extract: extract_camps")
    for fx in spec["extract"]:
        entries = camps.extract_camps(_read(fx["file"]), fx["pageUrl"], published=fx.get("published"), title=fx.get("title"),
                                      body_only=bool(fx.get("bodyOnly")))
        if "count" in fx:
            ok(f"{fx['file']} count", len(entries) == fx["count"], f"got {len(entries)}: {[e['name'] + ' ' + str(e['startDate']) for e in entries]}")
        for exp in fx.get("expect") or []:
            match = [e for e in entries if all(e.get(k) == v for k, v in exp.items())]
            ok(f"{fx['file']} has {exp}", bool(match), f"entries: {[{k: e.get(k) for k in exp} for e in entries]}")
        for exp in fx.get("reject") or []:
            match = [e for e in entries if all(e.get(k) == v for k, v in exp.items())]
            ok(f"{fx['file']} lacks {exp}", not match)
    print("robots: fetch_checked")
    real_cache = common.CACHE_DIR
    for fx in spec["robots"]:
        for host, text in fx["robots"].items():
            common.set_robots_txt(host, text)
        calls = []
        real = common.fetch_text
        body = fx.get("body", "<html><body><p>Girls ID Camp June 6, 2026</p></body></html>")

        def stub(url, **kw):
            calls.append(url)
            return body, {"url": url, "finalUrl": fx.get("finalUrl") or url, "contentType": fx.get("contentType", "")}

        # a throwaway .cache/http holding an entry for the URL, as common.fetch would have written it
        # before fetch_checked could look at the final host
        tmp = tempfile.mkdtemp(prefix="camps-check-")
        key = common._cache_key("GET", fx["url"], None)
        with gzip.open(os.path.join(tmp, key + ".body.gz"), "wb") as f:
            f.write(body.encode("utf-8"))
        common.write_json(os.path.join(tmp, key + ".json"), {"url": fx["url"], "status": 200})
        common.CACHE_DIR = tmp
        common.fetch_text = stub
        try:
            r = camps.fetch_checked(fx["url"], fx["baseHost"])
        finally:
            common.fetch_text = real
            common.CACHE_DIR = real_cache
        ok(f"{fx['name']}: robotsBlocked", r["robotsBlocked"] is fx["expectBlocked"], f"got {r}")
        if "expectFetched" in fx:
            ok(f"{fx['name']}: request made", bool(calls) is fx["expectFetched"], f"calls {calls}")
        if "expectBody" in fx:
            ok(f"{fx['name']}: body kept", (r["html"] is not None) is fx["expectBody"], f"got html={r['html'] is not None}")
        if "expectNonHtml" in fx:
            ok(f"{fx['name']}: nonHtml", r["nonHtml"] is fx["expectNonHtml"], f"got {r}")
        if "expectCacheCleared" in fx:
            left = sorted(os.listdir(tmp))
            ok(f"{fx['name']}: cache entry {'removed' if fx['expectCacheCleared'] else 'kept'}",
               (not left) is fx["expectCacheCleared"], f"cache dir holds {left}")
        for name in os.listdir(tmp):
            os.remove(os.path.join(tmp, name))
        os.rmdir(tmp)
    print("news: mine_camp_news")
    rows = json.loads(_read(spec["news"]["file"]))
    accepted, rejected = camps.mine_camp_news(rows)
    acc = {(r["slug"], r["title"]) for r in accepted}
    for r in rows:
        want = r["expect"] == "accept"
        ok(f"{r['expect']:6} {r['slug']}: {r['title'][:60]}", ((r["slug"], r["title"]) in acc) is want)
    ok("accepted count", len(accepted) == spec["news"]["expectAccepted"], f"got {len(accepted)}")
    print("dates: parse_camp_dates")
    for fx in spec["dates"]:
        ds = camps.parse_camp_dates(fx["text"], fx.get("published"))
        got = [(d["startDate"], d["endDate"], d["precision"]) for d in ds]
        exp = [tuple(x) for x in fx["expect"]]
        ok(f"{fx['text'][:50]!r}", got == exp, f"got {got}, expected {exp}")
    print("urls: _http_url")
    for fx in spec.get("urls") or []:
        got = camps._http_url(fx["href"], fx.get("base"))
        ok(f"{fx['href']!r}", got == fx["expect"], f"got {got!r}, expected {fx['expect']!r}")
    print("curated: build_camps")
    for fx in spec.get("curated") or []:
        items = (build.build_camps(None, None, {"camps": fx["camps"]}) or {}).get("items") or []
        for exp in fx["expect"]:
            match = [e for e in items if all(e.get(k) == v for k, v in exp.items())]
            ok(f"curated {exp}", bool(match), f"items: {[{k: e.get(k) for k in exp} for e in items]}")
    print(f"\n{total - len(fails)} of {total} checks passed" + (f"; FAILED: {fails}" if fails else ""))
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", help="comma-separated slugs (default: every onboarded program)")
    ap.add_argument("--min-found", type=int, default=0, help="sweep: exit 1 when fewer programs get a camps link")
    ap.add_argument("--json", help="sweep: write the per-program report here")
    ap.add_argument("--cache-dir", help="read roster pages from this .cache/http directory (e.g. the main checkout's)")
    ap.add_argument("--titles", action="store_true", help="print accepted/rejected news titles instead of the sweep")
    ap.add_argument("--fixtures", action="store_true", help="run the regression fixtures under tests/fixtures/camps/")
    args = ap.parse_args(argv)
    if args.cache_dir:
        common.CACHE_DIR = args.cache_dir
    if args.fixtures:
        return fixtures(args)
    if args.titles:
        return titles(args)
    return sweep(args)


if __name__ == "__main__":
    sys.exit(main())
