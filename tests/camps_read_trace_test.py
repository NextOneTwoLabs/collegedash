"""The camp page's read trace: counts of why a page yielded what it did (issue #79, slice S1 of
docs/plans/79-camp-coverage.md).

    python tests/camps_read_trace_test.py            # every case
    python tests/camps_read_trace_test.py --verbose  # print every check, not only the failures

What is checked:
  same rows      extract_camps(..., trace={}) returns exactly what it returns without `trace`, on every extract
                 fixture in tests/fixtures/camps/fixtures.json, and still returns a list.
  counts         exact counts on frozen fixtures: the year-less page, the TBD page, the all-sport hub, the
                 registration-deadline table, the Ryzer table, the 25-row table (rows cut by MAX_CAMPS), the app
                 shell (scripts counted before they are removed; coarse buckets) and the coach site's links.
  per call       the trace is the dict the caller passed, filled by that call only: two calls, two traces, and two
                 threads at once do not mix.
  collect        collect() writes `readTrace` into camps.json when the page was read, and null when there is no
                 HTML (a robots block that keeps the stored camps, a fetch error, no link). Only the camp-page call
                 passes a trace: the news-article calls do not.
  build          `readTrace` never reaches a profile's camps block, a camps index row or the coverage block.

Offline: fixtures and stubs only; no files written, no network.
"""

from __future__ import annotations

import json
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import build  # noqa: E402
from collect import camps, common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False
FIX = os.path.join(ROOT, "tests", "fixtures", "camps")
KEYS = {"dayDates", "yearlessDayDates", "years", "gated", "sameHostCampLinks", "vendorLinks", "textChars", "scripts"}
GATES = {"otherSport", "mens", "allSport", "registration", "tbd", "cap"}
VENDORS = {"ryzer", "totalcamps", "ussportscamps", "abc", "other"}


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {ascii(detail)[:400]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def read(rel: str) -> str:
    with open(os.path.join(FIX, rel), encoding="utf-8") as f:
        return f.read()


def traced(rel: str, url: str, **kw):
    """(rows, trace) for one fixture, or (rows, None) when extract_camps takes no `trace` (main)."""
    t: dict = {}
    try:
        rows = camps.extract_camps(read(rel), url, trace=t, **kw)
    except TypeError as e:
        return camps.extract_camps(read(rel), url, **kw), None, str(e)
    return rows, t, ""


def test_same_rows() -> None:
    print("same rows: a trace changes nothing extract_camps returns")
    with open(os.path.join(FIX, "fixtures.json"), encoding="utf-8") as f:
        spec = json.load(f)
    for fx in spec["extract"]:
        kw = {"published": fx.get("published"), "title": fx.get("title"), "body_only": bool(fx.get("bodyOnly"))}
        if "pageSoccer" in fx:
            kw["page_soccer"] = fx["pageSoccer"]
        plain = camps.extract_camps(read(fx["file"]), fx["pageUrl"], **kw)
        rows, t, err = traced(fx["file"], fx["pageUrl"], **kw)
        label = fx["file"] + (f" [pageSoccer={fx['pageSoccer']}]" if "pageSoccer" in fx else "")
        ok(f"{label}: takes trace=", t is not None, err)
        ok(f"{label}: same rows with a trace", isinstance(rows, list) and json.dumps(rows, sort_keys=True, default=str)
           == json.dumps(plain, sort_keys=True, default=str))
        if t is not None:
            ok(f"{label}: the trace has every key", set(t) == KEYS and set(t["gated"]) == GATES
               and set(t["vendorLinks"]) == VENDORS, str(t))


def expect(rel: str, url: str, want: dict, *, n_rows: int | None = None, **kw) -> dict | None:
    rows, t, err = traced(rel, url, **kw)
    if not ok(f"{rel}: takes trace=", t is not None, err):
        return None
    if n_rows is not None:
        ok(f"{rel}: {n_rows} rows, as today", len(rows) == n_rows, str(len(rows)))
    for k, v in want.items():
        got = t
        for part in k.split("."):
            got = got.get(part) if isinstance(got, dict) else None
        ok(f"{rel}: {k} == {v!r}", got == v, f"got {got!r}; trace {t}")
    return t


def test_counts() -> None:
    print("counts on frozen fixtures")
    # The year-less page: two day dates with no year, dropped today (0 rows); the heading's 2027 is not a day date.
    expect("extract/synth-trace-yearless.html", "https://example.test/camps", n_rows=0,
           title="Women's Soccer Camps", want={"dayDates": 0, "yearlessDayDates": 2, "years": {},
                                              "textChars": "<500", "scripts": "0"})
    # 'When: TBD' under the camp name: the lookahead stops on it.
    expect("extract/tbd.html", "https://www.dukesocceracademy.com/idcamps", n_rows=0, title="ID Camps",
           want={"gated.tbd": 1, "dayDates": 0})
    # The all-sport hub: one soccer row kept, the other sports' rows gated (section and name rules).
    expect("extract/hub-wofford.html", "https://athletics.wofford.edu/sports/2008/5/5/summer camp.aspx", n_rows=1,
           title="Summer Camps @ Wofford", want={"gated.otherSport": 17, "gated.mens": 0, "gated.allSport": 0,
                                                 "gated.cap": 0})
    # Same hub read as an all-sport page (pageSoccer false): the extra all-sport rule removes nothing more.
    expect("extract/hub-wofford.html", "https://athletics.wofford.edu/sports/2008/5/5/summer camp.aspx", n_rows=1,
           title="Summer Camps @ Wofford", page_soccer=False, want={"gated.otherSport": 17, "gated.allSport": 0})
    # The deadline table: the Deadline column's date is skipped as a registration date.
    expect("extract/synth-table-deadline.html", "https://www.example-camps.test/index.cfm", n_rows=1,
           title="Example Women's Soccer Camps and Clinics", page_soccer=True, want={"gated.registration": 1})
    # The Ryzer table: 4 rows, slash dates with years, 4 links to register.ryzer.com.
    expect("extract/ryzer-table.html", "https://www.hailstatecamps.com/soccer/", n_rows=4, title="Hailstate Soccer Camps",
           want={"years": {"2026": 2, "2027": 3}, "vendorLinks.ryzer": 4, "vendorLinks.totalcamps": 0,
                 "sameHostCampLinks": 0, "gated.cap": 0})
    # 25 dated rows: 20 returned (MAX_CAMPS), the 5 cut are counted.
    expect("extract/synth-trace-cap.html", "https://example.test/camps", n_rows=camps.MAX_CAMPS,
           title="Women's Soccer ID Camps", want={"gated.cap": 5, "dayDates": 25, "years": {"2027": 25}})
    # The app shell: 7 scripts, counted before extract_camps removes them; no readable text.
    expect("extract/synth-trace-shell.html", "https://www.example-camps.test/About%20Us", n_rows=0,
           want={"scripts": "6+", "textChars": "0", "dayDates": 0})
    # The coach site: 2 distinct same-host camp links (the nav one counts; the body repeats it), and one link
    # each to Ryzer, TotalCamps, US Sports Camps and another camp site. Hosts are not stored, only counts.
    expect("extract/synth-trace-links.html", "https://www.examplesocceracademy.com/", n_rows=0,
           title="Example Soccer Academy", want={"sameHostCampLinks": 2, "vendorLinks": {
               "ryzer": 1, "totalcamps": 1, "ussportscamps": 1, "abc": 0, "other": 1}})


def test_per_call() -> None:
    print("per call: the caller's dict, filled by that call only")
    a, b = {}, {}
    try:
        camps.extract_camps(read("extract/synth-trace-cap.html"), "https://example.test/camps", title="ID Camps", trace=a)
        camps.extract_camps(read("extract/synth-trace-yearless.html"), "https://example.test/camps", title="Camps", trace=b)
    except TypeError as e:
        ok("extract_camps takes trace=", False, str(e))
        return
    ok("two calls fill two traces", a.get("dayDates") == 25 and b.get("dayDates") == 0, f"{a} {b}")
    ok("a reused dict is reset, not added to", (camps.extract_camps(
        read("extract/synth-trace-cap.html"), "https://example.test/camps", title="ID Camps", trace=a) or True)
       and a.get("dayDates") == 25 and a["gated"]["cap"] == 5, str(a))
    out: dict = {}

    def run(name, rel, n):
        for _ in range(n):
            t: dict = {}
            camps.extract_camps(read(rel), "https://example.test/camps", title="ID Camps", trace=t)
            out.setdefault(name, []).append(t["dayDates"])

    ths = [threading.Thread(target=run, args=("cap", "extract/synth-trace-cap.html", 5)),
           threading.Thread(target=run, args=("yearless", "extract/synth-trace-yearless.html", 5))]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    ok("two threads at once do not mix", out.get("cap") == [25] * 5 and out.get("yearless") == [0] * 5, str(out))


class _Patch:
    def __init__(self, **attrs):
        self.attrs, self.old = attrs, {}

    def __enter__(self):
        for k, v in self.attrs.items():
            mod, name = k.split("__", 1)
            target = {"camps": camps, "common": common}[mod]
            self.old[k] = getattr(target, name)
            setattr(target, name, v)

    def __exit__(self, *a):
        for k, v in self.old.items():
            mod, name = k.split("__", 1)
            setattr({"camps": camps, "common": common}[mod], name, v)


def run_collect(fetched: dict, stored: dict | None = None, news_html: str | None = None) -> tuple[dict, list]:
    """collect() for one program whose registry names its camp page, with fetch, storage and news stubbed."""
    saved: dict = {}
    calls: list = []
    url = "https://www.example-camps.test/camps"
    real_extract = camps.extract_camps

    def spy(*a, **kw):
        calls.append("trace" in kw)
        return real_extract(*a, **kw)

    def fake_fetch(u, base_host, **kw):
        if u.startswith("https://news.example.test/"):
            return {"url": u, "finalUrl": u, "html": news_html, "robotsBlocked": False, "hostRefused": False,
                    "error": None, "status": None, "nonHtml": False}
        return {"url": u, "finalUrl": u, "robotsBlocked": False, "hostRefused": False, "error": None, "status": None,
                "nonHtml": False, "html": None, **fetched}

    def fake_load(slug, name):
        if name == "news":
            return {"data": {"items": [{"title": "Women's Soccer to Host ID Camp", "url": "https://news.example.test/a",
                                        "date": "2026-05-01"}]}} if news_html else None
        return {"data": stored} if stored else None

    def fake_save(slug, name, data, **kw):
        saved.update(data)
        return ""

    program = {"slug": "example", "athletics": {"baseUrl": "https://example-athletics.test", "campsUrl": url}}
    with _Patch(camps__fetch_checked=fake_fetch, camps__extract_camps=spy, common__load_source=fake_load,
                common__save_source=fake_save):
        camps.collect(program, {})
    return saved, calls


def test_collect() -> None:
    print("collect: readTrace in camps.json, null without HTML")
    news = "<html><body><article><p>ID Camp - June 3, 2026</p></article></body></html>"
    d, calls = run_collect({"html": read("extract/synth-trace-cap.html")}, news_html=news)
    ok("a read page stores its trace", isinstance(d.get("readTrace"), dict) and d["readTrace"].get("dayDates") == 25
       and d["readTrace"]["gated"]["cap"] == 5, str(d.get("readTrace")))
    ok("and its rows as before", len(d.get("camps") or []) == camps.MAX_CAMPS, str(len(d.get("camps") or [])))
    ok("only the camp-page call passes a trace (not the news article)", calls == [True, False], str(calls))
    stored = {"campsUrl": "https://www.example-camps.test/camps", "pageTitle": "Camps",
              "camps": [{"name": "ID Camp", "startDate": "2027-06-01"}], "readTrace": {"dayDates": 9}}
    d, _ = run_collect({"robotsBlocked": True, "robotsDisallowed": True}, stored=stored)
    ok("a robots block keeps the stored camps", d.get("camps") == stored["camps"], str(d.get("camps")))
    ok("but stores readTrace null (nothing was read)", "readTrace" in d and d["readTrace"] is None, str(d.get("readTrace")))
    d, _ = run_collect({"error": "HTTP 500", "status": 500})
    ok("a fetch error stores readTrace null", "readTrace" in d and d["readTrace"] is None, str(d.get("readTrace")))
    d, _ = run_collect({"nonHtml": True})
    ok("a PDF (not HTML) stores readTrace null", "readTrace" in d and d["readTrace"] is None, str(d.get("readTrace")))


def test_build() -> None:
    print("build: readTrace never reaches the published output")
    trace = {"dayDates": 3, "yearlessDayDates": 1, "years": {"2027": 3}, "gated": {g: 0 for g in GATES},
             "sameHostCampLinks": 1, "vendorLinks": {v: 0 for v in VENDORS}, "textChars": "<5k", "scripts": "1-5"}
    row = camps._entry("Elite ID Camp", {"startDate": "2027-06-01", "endDate": "2027-06-01", "dateText": "June 1, 2027",
                                         "precision": "day", "yearInferred": False}, {}, None, "https://c.test/camps")
    rec = {"collector": "camps", "sourceUrl": "https://c.test/camps", "fetchedAt": "2026-10-30T00:00:00Z",
           "data": {"campsUrl": "https://c.test/camps", "finalUrl": "https://c.test/camps", "host": "c.test",
                    "vendor": "external", "pageTitle": "Camps", "parsed": True, "camps": [row], "newsCamps": [],
                    "newsScanned": 0, "readTrace": trace}}
    block = build.build_camps(rec, {"data": {}, "collector": "news"}, {})
    text = json.dumps(block, default=str)
    ok("the profile's camps block carries no readTrace", "readTrace" not in text and "yearlessDayDates" not in text, text[:300])
    rows = [build.camp_row("example", it, None) for it in block["items"]]
    ok("nor does a camps index row", "readTrace" not in json.dumps(rows, default=str), json.dumps(rows, default=str)[:300])
    cov = build.camp_coverage([{"camps": block}])
    ok("and the coverage block is counts by bucket only, the same as without it",
       cov == build.camp_coverage([{"camps": build.build_camps({**rec, "data": {k: v for k, v in rec["data"].items()
                                                                               if k != "readTrace"}},
                                                               {"data": {}, "collector": "news"}, {})}]), str(cov))


def main(argv=None) -> int:
    global VERBOSE
    VERBOSE = "--verbose" in (argv if argv is not None else sys.argv[1:])
    test_same_rows()
    test_counts()
    test_per_call()
    test_collect()
    test_build()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {len(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
