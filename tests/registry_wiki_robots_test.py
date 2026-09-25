"""The registry builder asks Wikipedia only for what robots.txt allows (issue #99).

    python tests/registry_wiki_robots_test.py            # every check, offline
    python tests/registry_wiki_robots_test.py --verbose

en.wikipedia.org/robots.txt disallows /w/ and /api/ for every agent (quoted on #99, verified by the TPM). The
builder used both - the REST html and summary endpoints, the search API and index.php?action=raw - and never asked
common.robots_allowed(). Now every Wikipedia request goes through registry_builder._wiki_fetch, which asks first.

  rules       with those rules seeded (common.set_robots_txt), every URL the builder builds is allowed, and each
              URL it used to build is not (control: the checks can fail)
  source      collect/registry_builder.py names no /api/ or /w/ URL on en.wikipedia.org
  refuse      with robots.txt disallowing everything, no Wikipedia helper makes a request
  parse       the /wiki/ pages parse: the Division I list (rendered '/wiki/' links, and './' links from a page cached
              before #99), a canonical title from <link rel="canonical"> (a redirect names its target; a 404 is None),
              the colour module's source from the Module: page, and the probes-only article finder
Offline: common.fetch is replaced by a table of synthetic pages; nothing is requested.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collect import common  # noqa: E402
from collect import registry_builder as rb  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False

# The two rules #99 quotes from en.wikipedia.org/robots.txt, under User-agent: *.
WIKIPEDIA_ROBOTS = "User-agent: *\nDisallow: /w/\nDisallow: /api/\n"
OLD_URLS = [
    "https://en.wikipedia.org/api/rest_v1/page/html/List_of_NCAA_Division_I_women%27s_soccer_programs",
    "https://en.wikipedia.org/api/rest_v1/page/summary/Example_Owls_women%27s_soccer",
    "https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=6&srsearch=Example%20women%27s%20soccer",
    "https://en.wikipedia.org/w/index.php?title=Module:College_color/data&action=raw",
]


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


class Fetches:
    """Stands in for common.fetch: url -> (status, html). Records every URL asked for."""

    def __init__(self, pages: dict[str, tuple[int, str]]):
        self.pages, self.asked = pages, []

    def __call__(self, url, **kw):
        self.asked.append(url)
        status, html = self.pages.get(url, (404, ""))
        allow = kw.get("allow_status") or (200,)
        if status not in allow:
            raise common.FetchError(f"HTTP {status} for {url}")
        return html.encode("utf-8"), {"status": status}


def with_fetch(pages, fn):
    fake, real = Fetches(pages), common.fetch
    common.fetch = fake
    try:
        return fn(), fake.asked
    finally:
        common.fetch = real


def built_urls() -> list[str]:
    """Every Wikipedia URL the builder builds, taken from the code paths themselves."""
    urls = list(rb.WIKI_LIST.values()) + [rb.COLOR_MODULE_URL]
    _, asked = with_fetch({}, lambda: [rb.wiki_canonical(t) for t in ("Example_Owls_women's_soccer", "Example_Owls",
                                                                          "St._Example's_Gaels_women's_soccer")])
    return urls + asked


def test_rules() -> None:
    print("rules: every URL the builder builds is allowed under Wikipedia's robots.txt")
    common.set_robots_txt("en.wikipedia.org", WIKIPEDIA_ROBOTS)
    urls = built_urls()
    ok("the builder builds list, canonical and colour-module URLs", len(urls) >= 5, urls)
    bad = [u for u in urls if not common.robots_allowed(u)]
    ok("FIX every one is allowed", not bad, bad)
    ok("every one is a /wiki/ page", all(u.startswith("https://en.wikipedia.org/wiki/") for u in urls), urls)
    ok("control: each URL it used to build is disallowed", not any(common.robots_allowed(u) for u in OLD_URLS),
       [u for u in OLD_URLS if common.robots_allowed(u)])


def test_source() -> None:
    print("source: no /api/ or /w/ Wikipedia URL left in the builder")
    src = open(os.path.join(ROOT, "collect", "registry_builder.py"), encoding="utf-8").read()
    hits = re.findall(r"en\.wikipedia\.org/(?:api|w)/\S*", src)
    ok("FIX collect/registry_builder.py names none", not hits, hits)
    ok("the search API helper is gone", "_wiki_search" not in src and "srsearch" not in src)


def test_refuse() -> None:
    print("refuse: a disallowed URL is never requested")
    common.set_robots_txt("en.wikipedia.org", "User-agent: *\nDisallow: /\n")
    try:
        (canon, asked) = with_fetch({rb.WIKI + "Example_Owls": (200, "<html></html>")}, lambda: rb.wiki_canonical("Example_Owls"))
        ok("wiki_canonical returns None and makes no request", canon is None and asked == [], (canon, asked))
        for name, fn in (("fetch_wiki_list", lambda: rb.fetch_wiki_list("D1")), ("fetch_color_table", rb.fetch_color_table)):
            try:
                _, asked = with_fetch({}, fn)
                ok(f"{name} refuses", False, "no error")
            except common.FetchError as e:
                ok(f"{name} raises 'robots.txt disallows' before any request", "robots.txt disallows" in str(e), str(e))
    finally:
        common.set_robots_txt("en.wikipedia.org", WIKIPEDIA_ROBOTS)


LIST_HTML = """<html><body><table class="wikitable"><tr><th>Institution</th><th>City</th><th>State</th><th>Type</th><th>Nickname</th><th>Conference</th></tr>
<tr><td><a href="/wiki/Example_University" title="Example University">Example University</a><sup>[1]</sup></td><td>Exampleton</td><td>ZZ</td><td>Public</td>
<td><a href="/wiki/Example_Owls" title="Example Owls">Owls</a></td><td>Example Conference</td></tr>
<tr><td><a href="./St._Example%27s_College">St. Example's College</a></td><td>Sampleville</td><td>ZZ</td><td>Private</td>
<td><a href="./St._Example%27s_Gaels_women%27s_soccer">Gaels</a></td><td>Example Conference</td></tr>
</table></body></html>"""


def article(canonical: str) -> str:
    return (f'<html><head><link rel="canonical" href="https://en.wikipedia.org/wiki/{canonical}"></head>'
            f'<body><h1>{canonical.replace("_", " ")}</h1></body></html>')


def module_page(n: int) -> str:
    lines = ["return {"] + [f'\t["Example College {i}"] = {{"{i:06X}", "FFFFFF", name1="c{i}"}},' for i in range(n)]
    lines += ['\t["Example Alias"] = "Example College 1",', "}"]
    code = "\n".join(f'<span class="linenos" data-line="{k + 1}"></span>{line.replace("<", "&lt;")}' for k, line in enumerate(lines))
    return ('<html><body><div class="mw-highlight mw-highlight-lang-lua mw-content-ltr mw-highlight-lines" dir="ltr">'
            f"<pre>{code}</pre></div></body></html>")


def test_parse() -> None:
    print("parse: the /wiki/ pages")
    common.set_robots_txt("en.wikipedia.org", WIKIPEDIA_ROBOTS)
    rows, _ = with_fetch({rb.WIKI_LIST["D1"]: (200, LIST_HTML)}, lambda: rb.fetch_wiki_list("D1"))
    ok("the list reads both rows", len(rows) == 2, rows)
    if len(rows) == 2:
        ok("rendered '/wiki/' links give article titles", rows[0]["institutionArticle"] == "Example_University"
           and rows[0]["athleticsArticle"] == "Example_Owls", rows[0])
        ok("'./' links from an older cached page still read, percent-decoded",
           rows[1]["athleticsArticle"] == "St._Example's_Gaels_women's_soccer", rows[1])
        ok("cells lose their footnote marks", rows[0]["institution"] == "Example University", rows[0])

    pages = {rb.WIKI + "Example_Owls_soccer": (200, article("Example_Owls_men%27s_soccer")),
             rb.WIKI + "Example_Owls_women%27s_soccer": (200, article("Example_Owls_women%27s_soccer")),
             rb.WIKI + "Nope": (404, "")}
    got, _ = with_fetch(pages, lambda: (rb.wiki_canonical("Example_Owls_women's_soccer"), rb.wiki_canonical("Example_Owls_soccer"),
                                        rb.wiki_canonical("Nope")))
    ok("a canonical link gives the title, decoded", got[0] == "Example_Owls_women's_soccer", got)
    ok("a redirect names its target", got[1] == "Example_Owls_men's_soccer", got)
    ok("a 404 is None", got[2] is None, got)
    art, _ = with_fetch(pages, lambda: rb.soccer_article_for("Example_Owls"))
    ok("soccer_article_for still takes the women's article, not a men's redirect", art == "Example_Owls_women's_soccer", art)

    found, asked = with_fetch(pages, lambda: rb.find_wiki_article({"name": "Example", "shortName": "Example", "nickname": "Owls"}))
    ok("find_wiki_article finds by a direct probe", found == ("Example_Owls_women's_soccer", []), found)
    miss, asked = with_fetch({}, lambda: rb.find_wiki_article({"name": "Nowhere", "shortName": "Nowhere", "nickname": "Ghosts"}))
    ok("a miss makes only the two probes, both /wiki/ pages, and no search", miss == (None, []) and len(asked) == 2
       and all(u.startswith(rb.WIKI) for u in asked), asked)

    (entries, aliases), _ = with_fetch({rb.COLOR_MODULE_URL: (200, module_page(600))}, rb.fetch_color_table)
    ok("the colour module's source is read from its page", len(entries) == 600 and aliases == {"Example Alias": "Example College 1"},
       (len(entries), aliases))
    ok("an entry's colours parse", entries.get("Example College 10") == ["#00000A", "#FFFFFF"], entries.get("Example College 10"))
    try:
        with_fetch({rb.COLOR_MODULE_URL: (200, "<html><body><p>no code</p></body></html>")}, rb.fetch_color_table)
        ok("a page with no code block fails loudly", False)
    except common.FetchError as e:
        ok("a page with no code block fails loudly", "parsed only 0 entries" in str(e), str(e))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    common.log = lambda msg: None
    for t in (test_rules, test_source, test_refuse, test_parse):
        t()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
