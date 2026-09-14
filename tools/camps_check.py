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
import re
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


# ---------- privacy: no third party's contact details in a fixture ----------
#
# The camps fixtures are trims of real athletics pages, and those pages carry named staff members'
# work email addresses and telephone numbers. Twelve of them reached a fixture on a PUBLIC
# repository before anyone noticed, because nothing looks at a fixture except the parser, and the
# parser does not care. This scan is the thing that looks.
#
# Redaction form: an address at a reserved example domain, and a number in the 555-01xx range
# reserved for fiction. Anything else email-shaped or telephone-shaped is a FAIL naming the file and
# the value, so a new fixture pasted in from a live page cannot land its contact block quietly.
# Deliberately not a regex over "PII" in general - names, cities and prices stay, because a fixture
# has to keep reproducing the real page's extraction to be worth anything.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# A reserved domain: RFC 2606's example.com/.net/.org and .invalid/.test/.example/.localhost, plus
# example.edu, which fixtures.json already uses for a stub page URL.
FAKE_EMAIL_RE = re.compile(r"@example\.(?:com|net|org|edu)$|\.(?:invalid|test|example|localhost)$", re.I)
# '617-817-3589', '(423) 425-2107', '406.243.4346'. Both separators must be '-' or '.', which is
# what keeps the inline SVG path data in the nav fixtures ('714.163 519.284 1160') out of it.
PHONE_RE = re.compile(r"\(?\b[0-9]{3}\)?[-. ]?[0-9]{3}[-.][0-9]{4}\b")
FAKE_PHONE_RE = re.compile(r"^55555501[0-9]{2}$")


def _fixture_files() -> list[str]:
    out = []
    for dirpath, _dirs, names in os.walk(FIXTURES):
        for n in sorted(names):
            out.append(os.path.join(dirpath, n))
    return sorted(out)


def scan_contact_details() -> tuple[list[str], list[str]]:
    """(offending emails, offending telephone numbers), each as 'file: value'."""
    emails, phones = [], []
    for path in _fixture_files():
        rel = os.path.relpath(path, FIXTURES).replace(os.sep, "/")
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        for v in dict.fromkeys(EMAIL_RE.findall(text)):
            if not FAKE_EMAIL_RE.search(v):
                emails.append(f"{rel}: {v}")
        for v in dict.fromkeys(PHONE_RE.findall(text)):
            if not FAKE_PHONE_RE.match(re.sub(r"[^0-9]", "", v)):
                phones.append(f"{rel}: {v}")
    return emails, phones


def fixtures(args) -> int:
    spec = json.load(open(os.path.join(FIXTURES, "fixtures.json"), encoding="utf-8"))
    fails, total = [], 0

    def ok(name: str, cond: bool, detail: str = "") -> bool:
        nonlocal total
        total += 1
        print(f"  {'ok  ' if cond else 'FAIL'} {name}{(' - ' + detail) if detail and not cond else ''}")
        if not cond:
            fails.append(name)
        return bool(cond)  # returned so a check can guard the one after it; it used to return None,
        # which silently made `if not ok(...): continue` an unconditional skip

    print("privacy: no contact details in tests/fixtures/camps/")
    bad_emails, bad_phones = scan_contact_details()
    ok("no real email address in any fixture", not bad_emails, "; ".join(bad_emails))
    ok("no real telephone number in any fixture", not bad_phones, "; ".join(bad_phones))

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

    # ---- issue #39: the row-level gate, the name repairs and the price filter ----
    # These groups name private helpers directly, so they cannot discriminate against a parser that
    # does not have them. `helper` makes that degrade to a reported FAIL per check instead of an
    # AttributeError that aborts the suite partway through and takes the remaining groups with it -
    # which is what a swap-back against origin/main used to do, leaving the extract group's result
    # as the only real evidence. `missing` is the detail line those failures carry.
    def helper(attr: str):
        return getattr(camps, attr, None)

    def missing(attr: str) -> str:
        return f"collect.camps has no {attr} - this check cannot run"

    print("sections: _sport_section")
    _sport_section = helper("_sport_section")
    for fx in spec.get("sections") or []:
        for text, sport, male in fx.get("cases") or []:
            got = _sport_section(text) if _sport_section else None
            ok(f"{text!r} -> {sport}{' male' if male else ''}",
               _sport_section is not None and bool(got) and got["sport"] == sport and got["male"] is male,
               missing("_sport_section") if _sport_section is None else f"got {got!r}")
        for text in fx.get("notSections") or []:
            got = _sport_section(text) if _sport_section else None
            ok(f"{text!r} is not a section heading",
               _sport_section is not None and got is None,
               missing("_sport_section") if _sport_section is None else f"got {got!r}")

    print("rows: _row_allowed")
    _row_allowed = helper("_row_allowed")
    rows = spec.get("rows") or {}
    named = rows.get("sections") or {}
    for name, sec, want in rows.get("cases") or []:
        got = _row_allowed(name, named.get(sec) if sec else None) if _row_allowed else None
        ok(f"{name!r} under {sec or 'no section'} -> {'keep' if want else 'drop'}",
           _row_allowed is not None and got is want,
           missing("_row_allowed") if _row_allowed is None else f"got {got}")
    # the same rows on a page that is not an all-sport hub: the section must not bite
    for name, sec in rows.get("notHub") or []:
        got = _row_allowed(name, named.get(sec), is_hub=False) if _row_allowed else None
        ok(f"{name!r} under {sec}, page is not a hub -> keep",
           _row_allowed is not None and got is True,
           missing("_row_allowed") if _row_allowed is None else f"got {got}")

    # Issue #80's P1, as a unit. `named="page"` says the row's name came from the page and so names
    # no sport and no gender; the gate then has to read the evidence the row was built from. These
    # cases fail against origin/main, whose _row_allowed takes no evidence at all - reported as a
    # FAIL per case by the same `helper` degradation the group above uses.
    print("rowsEvidence: _row_allowed on the text a page-named row was assembled from")
    for fx in (spec.get("rowsEvidence") or {}).get("cases") or []:
        want = fx["expect"]
        try:
            got = _row_allowed(fx["name"], None, named=fx.get("named", "row"), evidence=fx.get("evidence"),
                               own_evidence=fx.get("ownEvidence"),
                               page_is_soccer=bool(fx.get("pageIsSoccer"))) if _row_allowed else None
        except TypeError as e:  # a parser whose _row_allowed has no evidence parameter
            got, e = None, e
            ok(f"{fx['why']} -> {'keep' if want else 'drop'}", False,
               f"_row_allowed does not take evidence: {e}")
            continue
        ok(f"{fx['why']} -> {'keep' if want else 'drop'}",
           _row_allowed is not None and got is want,
           missing("_row_allowed") if _row_allowed is None else f"got {got}")

    print("newRow: _starts_new_row")
    _starts_new_row = helper("_starts_new_row")
    for line, want in (spec.get("newRow") or {}).get("cases") or []:
        ds = camps.parse_camp_dates(line)
        if not ok(f"{line[:56]!r} parses a date at all", bool(ds), "no date, so the case proves nothing"):
            continue
        got = _starts_new_row(line, ds[0]["pos"]) if _starts_new_row else None
        ok(f"{line[:56]!r} -> {'its own row' if want else 'a continuation'}",
           _starts_new_row is not None and got is want,
           missing("_starts_new_row") if _starts_new_row is None else f"got {got}")

    # _page_is_soccer decides whether a SECTION rejection bites at all. Every known hub title must
    # be False here, or the gating this issue adds stops working on the pages it was built for.
    print("pages: _page_is_soccer")
    _page_is_soccer = helper("_page_is_soccer")
    pages = spec.get("pages") or {}
    for t in pages.get("soccer") or []:
        got = _page_is_soccer(t) if _page_is_soccer else None
        ok(f"{t!r} is the page's own soccer page", _page_is_soccer is not None and got is True,
           missing("_page_is_soccer") if _page_is_soccer is None else f"got {got}")
    for t in pages.get("notSoccer") or []:
        got = _page_is_soccer(t) if _page_is_soccer else None
        ok(f"{t!r} does not suppress section gating", _page_is_soccer is not None and got is False,
           missing("_page_is_soccer") if _page_is_soccer is None else f"got {got}")

    print("names: _is_chrome_name / _clean_name")
    _is_chrome_name, _clean_name = helper("_is_chrome_name"), helper("_clean_name")
    names = spec.get("names") or {}
    for n in names.get("chrome") or []:
        ok(f"{n!r} is page chrome",
           _is_chrome_name is not None and _is_chrome_name(n) is True,
           missing("_is_chrome_name") if _is_chrome_name is None else "")
    for n in names.get("notChrome") or []:
        ok(f"{n!r} is a real camp name",
           _is_chrome_name is not None and _is_chrome_name(n) is False,
           missing("_is_chrome_name") if _is_chrome_name is None else "")
    for raw, want in names.get("clean") or []:
        got = _clean_name(raw) if _clean_name else None
        ok(f"clean {raw!r}", _clean_name is not None and got == want,
           missing("_clean_name") if _clean_name is None else f"got {got!r}, expected {want!r}")

    print("prices: the price-label filter")
    _entry = helper("_entry")
    for raw, want in (spec.get("prices") or {}).get("cases") or []:
        got = _entry("X", {"startDate": "2026-01-01", "endDate": "2026-01-01", "dateText": "",
                           "precision": "day"}, {"price": raw}, None,
                     "https://example.edu")["price"] if _entry else None
        ok(f"price {raw!r} -> {want!r}", _entry is not None and got == want,
           missing("_entry") if _entry is None else f"got {got!r}")

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
