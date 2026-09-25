"""The registry's Wikipedia lookup never lands on a men's team's article, and a recorded "no women's article"
stops the lookup and the collector (issue #349).

    python tests/wiki_lookup_test.py

Offline: wiki_canonical and find_wiki_article are replaced by fixtures, so no request is made.

How the men's titles got in (#303, #346): the registry builder took the list's athletics article
('Old_Dominion_Monarchs'), tried '<article>_women's_soccer' (no such page) and then '<article>_soccer', which
redirects to 'Old_Dominion_Monarchs_men's_soccer'; the redirect was followed and accepted. FIX checks fail on
origin/main; CONTROL checks pass on both.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import common, registry_builder as rb, wikipedia  # noqa: E402

FAILS: list[str] = []
TOTAL = 0


def ok(name: str, cond: bool, detail="") -> None:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))


PAGES = {  # title asked for -> canonical title (a redirect is followed); absent = no such page
    "Example_Monarchs_soccer": "Example_Monarchs_men's_soccer",
    "Example_Monarchs_men's_soccer": "Example_Monarchs_men's_soccer",
    "Sample_Owls_women's_soccer": "Sample_Owls_women's_soccer",
    "Other_Hawks_soccer": "Other_Hawks_soccer",
}


def test_soccer_article_for() -> None:
    real = rb.wiki_canonical
    rb.wiki_canonical = lambda t: PAGES.get(t)
    try:
        ok("FIX '<athletics>_soccer' redirecting to the men's article is refused", rb.soccer_article_for("Example_Monarchs") is None,
           rb.soccer_article_for("Example_Monarchs"))
        ok("FIX a list link that is itself the men's soccer article is refused", rb.soccer_article_for("Example_Monarchs_men's_soccer") is None)
        ok("CONTROL the women's article is found", rb.soccer_article_for("Sample_Owls") == "Sample_Owls_women's_soccer")
        ok("CONTROL a plain '<athletics>_soccer' article (no men's/women's in the title) is still taken",
           rb.soccer_article_for("Other_Hawks") == "Other_Hawks_soccer")
    finally:
        rb.wiki_canonical = real


def test_fix_wiki() -> None:
    reg = {"programs": [
        {"slug": "a", "onboarded": True, "ids": {"wikipedia": None}},
        {"slug": "b", "onboarded": True, "ids": {"wikipedia": None, "wikipediaNone": "no women's soccer article (checked 2026-09-24)"}},
        {"slug": "c", "onboarded": True, "ids": {"wikipedia": None}},
    ]}
    asked = []
    real = rb.find_wiki_article
    rb.find_wiki_article = lambda p: (asked.append(p["slug"]) or ({"a": "A_Tigers_men's_soccer", "c": "C_Owls_women's_soccer"}.get(p["slug"]), []))
    try:
        out = rb.fix_wiki(reg)
        ok("FIX a program recorded as having no women's article is not looked up again", "b" not in asked, asked)
        ok("FIX a men's-team title from the lookup is never taken", "a" not in out["found"] and "a" in out["none"], out)
        ok("CONTROL a women's title is taken", out["found"].get("c") == "C_Owls_women's_soccer", out)
        asked.clear()
        rb.fix_wiki(reg, slugs=["b"])
        ok("CONTROL naming the program looks it up again", asked == ["b"], asked)
    finally:
        rb.find_wiki_article = real


def test_collector_reads_the_marker() -> None:
    reg = {"sources": {"wikipedia": {"htmlApi": "https://example.invalid/{title}"}}}
    try:
        wikipedia.collect({"slug": "b", "ids": {"wikipedia": None, "wikipediaNone": "no women's soccer article (checked 2026-09-24)"}}, reg)
        ok("FIX the collector skips with the recorded reason", False)
    except common.SkipCollector as e:
        ok("FIX the collector skips with the recorded reason", "wikipediaNone" in str(e) and "no women's soccer article" in str(e), str(e))
    ok("CONTROL the men's-title guard from #346 is kept", bool(wikipedia.MENS_TITLE_RE.search("Old_Dominion_Monarchs_men's_soccer"))
       and not wikipedia.MENS_TITLE_RE.search("Old_Dominion_Monarchs_women's_soccer"))


def test_registry() -> None:
    reg = common.load_registry()
    mens = [p["slug"] for p in reg["programs"] if wikipedia.MENS_TITLE_RE.search((p.get("ids") or {}).get("wikipedia") or "")]
    ok("no registry title names a men's team", mens == [], mens)
    both = [p["slug"] for p in reg["programs"] if (p.get("ids") or {}).get("wikipedia") and (p.get("ids") or {}).get("wikipediaNone")]
    ok("no program has both a title and a no-article record", both == [], both)
    four = {p["slug"]: (p.get("ids") or {}).get("wikipediaNone") for p in reg["programs"]
            if p["slug"] in ("old-dominion", "campbell", "east-tennessee-state", "manhattan")}
    ok("#349: the four programs cleared in #346 record that they have no women's article, citing the 2026-09-06 lookup",
       len(four) == 4 and all(v and "2026-09-06" in v for v in four.values()), four)


def main() -> int:
    for fn in (test_soccer_article_for, test_fix_wiki, test_collector_reads_the_marker, test_registry):
        print(fn.__name__)
        fn()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
