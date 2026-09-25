"""The weekly Wikipedia collector asks only for what robots.txt allows (issue #364).

    python tests/wikipedia_robots_test.py            # every check, offline
    python tests/wikipedia_robots_test.py --verbose

collect/wikipedia.py read each program's article from en.wikipedia.org/api/rest_v1/page/html/{title}, and
en.wikipedia.org/robots.txt disallows /api/ (and /w/) for every agent (the rules #99 quotes). It now reads
/wiki/{title}, from registry sources.wikipedia.page, and asks common.robots_allowed() before any request.

  rules       with those rules seeded (common.set_robots_txt), the URL built for every registered title is an allowed
              /wiki/ page, and the rest_v1 URL it used to build is not (control: the check can fail)
  collect     collect() run for every registered title, with common.fetch_text replaced: every URL it asks for is
              allowed, one per title, none under /api/ or /w/
  refuse      a template pointed back at rest_v1, or robots.txt disallowing everything: FetchError, no request
  source      collect/wikipedia.py and registry sources.wikipedia name no /api/ or /w/ Wikipedia URL
  parse       the same infobox and season table parse to the same result from a rendered /wiki/ page (mw-parser-output,
              edit-section links, footnote markers) and from the REST HTML shape (section wrappers)
  keep        a page that parses to nothing does not replace a stored source that had seasons (control: with nothing
              stored, it is saved)
  athletics   a title with no 'soccer' in it (a general athletics article) is skipped with no request; northwestern and
              georgia record that they have no women's article, and their athletics-article sources are gone
Offline: common.fetch_text, load_source and save_source are replaced; nothing is requested or written.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bs4 import BeautifulSoup  # noqa: E402

from collect import common  # noqa: E402
from collect import wikipedia  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False

# The two rules #99 quotes from en.wikipedia.org/robots.txt, under User-agent: *.
WIKIPEDIA_ROBOTS = "User-agent: *\nDisallow: /w/\nDisallow: /api/\n"
OLD_TEMPLATE = "https://en.wikipedia.org/api/rest_v1/page/html/{title}"


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


INFOBOX = ("<table class='infobox vcard'><tr><th>Founded</th><td>1994<sup class='reference'><a href='#cite_note-1'>[1]</a></sup></td></tr>"
           "<tr><th>Head coach</th><td><a href='/wiki/Coach_A'>Coach A</a> (5th season)</td></tr>"
           "<tr><th>Stadium</th><td>Example Field (capacity: 2,500)</td></tr>"
           "<tr><th>NCAA Tournament College Cup</th><td>2004, 2011</td></tr></table>")
SEASONS = ("<table class='wikitable'><tr><th>Year</th><th>Head coach</th><th>Overall</th><th>Conference</th><th>Standing</th><th>NCAA Tournament</th></tr>"
           + "".join(f"<tr><td>{y}</td><td>Coach A</td><td>{w}–{l}–{t}<sup class='reference'>[2]</sup></td><td>5–3–1</td><td>2nd</td><td></td></tr>"
                     for y, w, l, t in ((2019, 10, 7, 1), (2020, 6, 4, 0), (2021, 12, 6, 2), (2022, 14, 5, 1), (2023, 9, 8, 3)))
           + "</table>")


def rendered_page() -> str:
    """The /wiki/ page shape: skin chrome, mw-parser-output, [edit] links in headings."""
    return ("<!DOCTYPE html><html><head><title>Example Owls women's soccer - Wikipedia</title></head><body>"
            "<div id='mw-navigation'><table class='wikitable'><tr><td>not a season table</td></tr></table></div>"
            "<div id='mw-content-text'><div class='mw-content-ltr mw-parser-output'>" + INFOBOX
            + "<h2><span class='mw-headline' id='Seasons'>Seasons</span><span class='mw-editsection'>[<a href='/w/index.php?action=edit'>edit</a>]</span></h2>"
            + SEASONS + "</div></div></body></html>")


def rest_page() -> str:
    """The REST HTML shape the collector read before: section wrappers, no skin."""
    return ("<!DOCTYPE html><html><head></head><body><section data-mw-section-id='0'>" + INFOBOX
            + "</section><section data-mw-section-id='1'><h2 id='Seasons'>Seasons</h2>" + SEASONS + "</section></body></html>")


class Harness:
    """Replaces common.fetch_text, load_source and save_source for the length of a with-block."""

    def __init__(self, html: str = "", stored: dict | None = None):
        self.html, self.stored, self.asked, self.saved = html, stored or {}, [], []

    def __enter__(self):
        self.real = (common.fetch_text, common.load_source, common.save_source, common.log)

        def fetch_text(url, **kw):
            self.asked.append(url)
            return self.html, {"fromCache": False}

        common.fetch_text = fetch_text
        common.log = lambda *a, **kw: None
        common.load_source = lambda slug, name: self.stored.get(slug)
        common.save_source = lambda slug, name, data, **kw: self.saved.append((slug, data))
        return self

    def __exit__(self, *exc):
        common.fetch_text, common.load_source, common.save_source, common.log = self.real
        return False


def registered() -> list[dict]:
    reg = common.load_registry()
    return [p for p in reg["programs"] if (p.get("ids") or {}).get("wikipedia")]


def test_rules() -> None:
    print("rules: the URL built for every registered title is an allowed /wiki/ page")
    common.set_robots_txt("en.wikipedia.org", WIKIPEDIA_ROBOTS)
    reg = common.load_registry()
    progs = registered()
    urls = [wikipedia.page_url(reg, p["ids"]["wikipedia"]) for p in progs]
    ok("the registry has titles to check", len(urls) >= 90, len(urls))
    bad = [u for u in urls if not common.robots_allowed(u)]
    ok("FIX every one is allowed", not bad, bad[:5])
    ok("every one is a /wiki/ page", all(u.startswith("https://en.wikipedia.org/wiki/") for u in urls),
       [u for u in urls if not u.startswith("https://en.wikipedia.org/wiki/")][:5])
    old = [OLD_TEMPLATE.format(title=p["ids"]["wikipedia"]) for p in progs]
    ok("control: the rest_v1 URL it used to build is disallowed for every title",
       not any(common.robots_allowed(u) for u in old), [u for u in old if common.robots_allowed(u)][:5])


def test_collect() -> None:
    print("collect: every URL collect() asks for, over every registered title, is allowed")
    common.set_robots_txt("en.wikipedia.org", WIKIPEDIA_ROBOTS)
    reg = common.load_registry()
    progs = registered()
    errors = []
    with Harness(rendered_page()) as h:
        for p in progs:
            try:
                wikipedia.collect(p, reg)
            except Exception as e:  # noqa: BLE001 - reported below
                errors.append((p["slug"], repr(e)[:120]))
    ok("no registered title fails or is skipped", not errors, errors[:5])
    ok("one request per title", len(h.asked) == len(progs), (len(h.asked), len(progs)))
    ok("FIX every request is allowed", all(common.robots_allowed(u) for u in h.asked),
       [u for u in h.asked if not common.robots_allowed(u)][:5])
    ok("no request is under /api/ or /w/", not [u for u in h.asked if re.search(r"wikipedia\.org/(?:api|w)/", u)])
    ok("each program's source is saved with its /wiki/ page URL", len(h.saved) == len(progs)
       and all(d["pageUrl"].startswith("https://en.wikipedia.org/wiki/") for _, d in h.saved))


def test_refuse() -> None:
    print("refuse: a disallowed URL is never requested")
    p = {"slug": "x", "ids": {"wikipedia": "Example_Owls_women's_soccer"}}
    common.set_robots_txt("en.wikipedia.org", WIKIPEDIA_ROBOTS)
    old_reg = {"sources": {"wikipedia": {"page": OLD_TEMPLATE}}}
    with Harness(rendered_page()) as h:
        try:
            wikipedia.collect(p, old_reg)
            ok("a template pointed back at rest_v1 raises FetchError", False, "no error")
        except common.FetchError as e:
            ok("a template pointed back at rest_v1 raises 'robots.txt disallows'", "robots.txt disallows" in str(e), str(e))
        ok("and makes no request", h.asked == [], h.asked)
    common.set_robots_txt("en.wikipedia.org", "User-agent: *\nDisallow: /\n")
    try:
        with Harness(rendered_page()) as h:
            try:
                wikipedia.collect(p, common.load_registry())
                ok("robots.txt disallowing everything raises FetchError", False, "no error")
            except common.FetchError as e:
                ok("robots.txt disallowing everything raises 'robots.txt disallows'", "robots.txt disallows" in str(e), str(e))
            ok("and makes no request", h.asked == [], h.asked)
    finally:
        common.set_robots_txt("en.wikipedia.org", WIKIPEDIA_ROBOTS)


def test_source() -> None:
    print("source: no /api/ or /w/ Wikipedia URL in the collector or its registry template")
    src = open(os.path.join(ROOT, "collect", "wikipedia.py"), encoding="utf-8").read()
    hits = re.findall(r"en\.wikipedia\.org/(?:api|w)/\S*", src)
    ok("FIX collect/wikipedia.py names none", not hits, hits)
    ok("the collector no longer reads sources.wikipedia.htmlApi", "htmlApi" not in src)
    wsrc = common.load_registry()["sources"]["wikipedia"]
    ok("FIX registry sources.wikipedia is the /wiki/ page template",
       wsrc == {"page": "https://en.wikipedia.org/wiki/{title}"}, wsrc)


def test_parse() -> None:
    print("parse: a rendered /wiki/ page parses as the REST HTML did")
    a, b = BeautifulSoup(rendered_page(), "html.parser"), BeautifulSoup(rest_page(), "html.parser")
    ia, ib = wikipedia._infobox(a), wikipedia._infobox(b)
    sa, sb = wikipedia._seasons_table(a), wikipedia._seasons_table(b)
    ok("the infobox reads", ia.get("Founded", "").startswith("1994") and "Coach A" in ia.get("Head coach", ""), ia)
    ok("FIX the rendered page's infobox matches the REST HTML's", ia == ib, (ia, ib))
    ok("the season table reads, skin tables ignored", [s["year"] for s in sa] == [2019, 2020, 2021, 2022, 2023]
       and sa[2]["record"] == "12-6-2" and sa[2]["confRecord"] == "5-3-1", sa)
    ok("FIX the rendered page's seasons match the REST HTML's", sa == sb, (sa, sb))
    common.set_robots_txt("en.wikipedia.org", WIKIPEDIA_ROBOTS)
    reg = {"sources": {"wikipedia": {"page": "https://en.wikipedia.org/wiki/{title}"}}, "season": {"current": 2025}}
    with Harness(rendered_page()) as h:
        d = wikipedia.collect({"slug": "x", "ids": {"wikipedia": "Example_Owls_women's_soccer"}}, reg)
    ok("collect() on the rendered page: seasons, College Cups, stadium, founded",
       len(d["seasons"]) == 5 and d["collegeCups"] == [2004, 2011] and d["stadium"] == {"name": "Example Field", "capacity": 2500}
       and d["founded"] == 1994, {k: d[k] for k in ("seasons", "collegeCups", "stadium", "founded")})


def test_keep() -> None:
    print("keep: a page that parses to nothing does not replace a stored source")
    common.set_robots_txt("en.wikipedia.org", WIKIPEDIA_ROBOTS)
    reg = common.load_registry()
    p = {"slug": "x", "ids": {"wikipedia": "Example_Owls_women's_soccer"}}
    stored = {"x": {"data": {"seasons": [{"year": 2023}] * 20, "infobox": {"Founded": "1994"}}}}
    empty = "<html><body><div class='mw-parser-output'><p>Nothing here.</p></div></body></html>"
    with Harness(empty, stored) as h:
        try:
            wikipedia.collect(p, reg)
            ok("FIX an empty parse over a stored source raises FetchError", False, "no error")
        except common.FetchError as e:
            ok("FIX an empty parse over a stored source raises FetchError", "kept the stored source (20 seasons)" in str(e), str(e))
        ok("and saves nothing", h.saved == [], h.saved)
    with Harness(empty) as h:
        wikipedia.collect(p, reg)
        ok("control: with nothing stored, the empty parse is saved", len(h.saved) == 1, h.saved)


def test_athletics() -> None:
    print("athletics: a general athletics article is not read")
    common.set_robots_txt("en.wikipedia.org", WIKIPEDIA_ROBOTS)
    reg = common.load_registry()
    for title in ("Georgia_Bulldogs", "Northwestern_Wildcats"):
        with Harness(rendered_page()) as h:
            try:
                wikipedia.collect({"slug": "x", "ids": {"wikipedia": title}}, reg)
                ok(f"FIX {title} is skipped", False, "no skip")
            except common.SkipCollector as e:
                ok(f"FIX {title} is skipped as not a soccer article", "not a soccer article" in str(e), str(e))
            ok(f"{title}: no request", h.asked == [], h.asked)
    non_soccer = [p["slug"] for p in registered() if "soccer" not in p["ids"]["wikipedia"].lower()]
    ok("no registered title is a general athletics article", non_soccer == [], non_soccer)
    by = {p["slug"]: p["ids"] for p in reg["programs"] if p["slug"] in ("northwestern", "georgia")}
    ok("#364: northwestern and georgia have no title and record the 2026-09-06 lookup",
       len(by) == 2 and all(i.get("wikipedia") is None and "2026-09-06" in (i.get("wikipediaNone") or "")
                            and "#364" in i["wikipediaNone"] for i in by.values()), by)
    stored = [s for s in ("northwestern", "georgia") if os.path.exists(common.source_path(s, "wikipedia"))]
    ok("their stored athletics-article sources are gone", stored == [], stored)


def main() -> int:
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose
    for fn in (test_rules, test_collect, test_refuse, test_source, test_parse, test_keep, test_athletics):
        fn()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
