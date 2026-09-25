"""Overall and conference records read in the column order the table's header gives (issue #303).

    python tests/wikipedia_record_columns_test.py

_seasons_table took the first record-like cell of a season row as the overall record and the second as the
conference one. florida's table ('Conference record' ... 'Regular season record') and san-diego-state's
('Record: Conference | Overall') put the conference record first, so 58 stored rows had the two swapped (#287's
build swap-back caught them). The header now decides for those tables; every other table reads as before.
Also: a registered title that names the men's team (old-dominion, east-tennessee-state, manhattan, campbell) is
skipped rather than collected.

Synthetic tables only, in these pages' column order; no real person, the coach cells read 'Coach A'.
FIX checks fail on origin/main; CONTROL checks pass on both.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from bs4 import BeautifulSoup  # noqa: E402

from collect import common, wikipedia  # noqa: E402

FAILS: list[str] = []
TOTAL = 0


def ok(name: str, cond: bool, detail="") -> None:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))


def seasons(html: str) -> dict:
    return {s["year"]: (s["record"], s["confRecord"]) for s in wikipedia._seasons_table(BeautifulSoup(html, "html.parser"))}


def rows(lines) -> str:
    return "".join("<tr>" + "".join(f"<td>{c}</td>" for c in line) + "</tr>" for line in lines)


# florida's order: the conference record first, the overall ("regular season") record later, a conference
# tournament's own record between them, and rows that leave a cell out
FLORIDA = ("<table class='wikitable'><tr><th>Season</th><th>Head coach</th><th>Conference</th><th>Conference record</th>"
           "<th>Conference ranking</th><th>Conference tournament results</th><th>Regular season record</th><th>Final ranking</th><th>Postseason results</th></tr>"
           + rows([["2001", "Coach A", "SEC", "6–1–1", "2", "Champions", "14–4–2", "NR", "Quarterfinals"],
                   ["2002", "Coach A", "SEC", "8–0–0", "1", "1–1", "22–3–0", "3", "Final Four"],
                   ["2003", "Coach A", "SEC", "3–6–1", "10", "16–5–1", "NR", "First round"],  # a cell left out
                   ["2004", "Coach A", "SEC", "0–9–1", "14", "", "2–14–1", "NR", ""],
                   ["2005", "Coach A", "SEC", "2–4–4", "11th", "", "6–5–6", "NR", ""]]) + "</table>")

# san-diego-state's order: a two-row header 'Record' over 'Conference | Overall', a conference name across the
# table above the first season, and a season with an overall record only
SDSU = ("<table class='wikitable'><tr><th rowspan='2'>Season</th><th rowspan='2'>Head coach</th><th colspan='2'>Record</th>"
        "<th rowspan='2'>Conference standing</th><th rowspan='2'>Postseason</th></tr><tr><th>Conference</th><th>Overall</th></tr>"
        "<tr><th colspan='6'>Western Athletic Conference</th></tr>"
        + rows([["1989", "Coach A", "", "5–4", "", ""],
                ["1990", "Coach A", "4–1–0", "16–7–0", "1st", ""],
                ["1991", "Coach A", "2–3–0", "10–6–1", "4th", ""],
                ["1992", "Coach A", "6–0–0", "19–3–1", "1st", "NCAA First round"],
                ["1993", "Coach A", "9–1–1", "14–3–3", "1st", ""]]) + "</table>")

# the usual order (Stanford): overall first; and the same with a conference name across the table
USUAL = ("<table class='wikitable'><tr><th>Year</th><th>Head coach</th><th>Overall</th><th>Conference</th><th>Standing</th><th>NCAA Tournament</th></tr>"
         + rows([["2001", "Coach A", "14–4–2", "6–1–1", "2nd", ""], ["2002", "Coach A", "22–3–0", "8–0–0", "1st", ""],
                 ["2003", "Coach A", "16–5–1", "3–6–1", "5th", ""], ["2004", "Coach A", "2–14–1", "", "", ""],
                 ["2005", "Coach A", "6–5–6", "2–4–4", "8th", ""]]) + "</table>")
USUAL_SECTION = ("<table class='wikitable'><tr><th rowspan='2'>Season</th><th rowspan='2'>Head coach</th><th colspan='2'>Record</th><th rowspan='2'>Standing</th></tr>"
                 "<tr><th>Overall</th><th>Conference</th></tr><tr><th colspan='5'>Mountain West Conference</th></tr>"
                 + rows([["2001", "Coach A", "14–4–2", "6–1–1", "2nd"], ["2002", "Coach A", "22–3–0", "8–0–0", "1st"],
                         ["2003", "Coach A", "16–5–1", "3–6–1", "5th"], ["2004", "Coach A", "2–14–1", "", ""],
                         ["2005", "Coach A", "6–5–6", "2–4–4", "8th"]]) + "</table>")


def test_conference_first() -> None:
    f = seasons(FLORIDA)
    ok("FIX florida order: overall from 'Regular season record', conference from 'Conference record'",
       f.get(2001) == ("14-4-2", "6-1-1") and f.get(2002) == ("22-3-0", "8-0-0") and f.get(2005) == ("6-5-6", "2-4-4"), f)
    ok("FIX florida order: a row that leaves a cell out still reads right (cell order, not column number)",
       f.get(2003) == ("16-5-1", "3-6-1") and f.get(2004) == ("2-14-1", "0-9-1"), f)
    s = seasons(SDSU)
    ok("FIX san-diego-state order: 'Record: Conference | Overall' under a conference name",
       s.get(1990) == ("16-7-0", "4-1-0") and s.get(1993) == ("14-3-3", "9-1-1"), s)
    ok("CONTROL a season with an overall record only keeps it as overall", s.get(1989) == ("5-4-0", None), s.get(1989))


def test_usual_order_unchanged() -> None:
    u = seasons(USUAL)
    ok("CONTROL overall first: unchanged", u.get(2001) == ("14-4-2", "6-1-1") and u.get(2004) == ("2-14-1", None), u)
    v = seasons(USUAL_SECTION)
    ok("CONTROL overall first under a conference name across the table: unchanged",
       v.get(2001) == ("14-4-2", "6-1-1") and v.get(2005) == ("6-5-6", "2-4-4"), v)


def test_mens_article_skipped() -> None:
    reg = {"sources": {"wikipedia": {"page": "https://example.invalid/{title}"}}}
    for title in ("Old_Dominion_Monarchs_men's_soccer", "Campbell Fighting Camels men's soccer"):
        try:
            wikipedia.collect({"slug": "x", "ids": {"wikipedia": title}}, reg)
            ok(f"FIX a men's-team title is skipped: {title}", False)
        except common.SkipCollector:
            ok(f"FIX a men's-team title is skipped: {title}", True)
        except Exception as e:  # noqa: BLE001 - origin/main tries to fetch it
            ok(f"FIX a men's-team title is skipped: {title}", False, repr(e)[:120])
    ok("CONTROL a women's title is not", not wikipedia.MENS_TITLE_RE.search("Florida_Gators_women's_soccer"))
    reg_file = common.load_registry()
    mens = [p["slug"] for p in reg_file["programs"] if wikipedia.MENS_TITLE_RE.search((p.get("ids") or {}).get("wikipedia") or "")]
    ok("no program in the registry is registered to a men's-team article", mens == [], mens)
    stored = [s for s in ("old-dominion", "east-tennessee-state", "manhattan", "campbell") if common.load_source(s, "wikipedia")]
    ok("their stored men's-team sources are gone", stored == [], stored)


def main() -> int:
    for fn in (test_conference_first, test_usual_order_unchanged, test_mens_article_skipped):
        print(fn.__name__)
        fn()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
