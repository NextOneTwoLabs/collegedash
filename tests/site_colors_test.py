"""Regression tests for team colours from each program's own athletics site (issue #276, part B).

    python tests/site_colors_test.py            # everything below, offline
    python tests/site_colors_test.py --verbose  # print every check, not only the failures

Offline: no request is made and nothing is written outside a temporary directory. The pages below are
synthetic and minimal, written by hand for these tests; nothing is cut from a live page. The agreement
table (tests/fixtures/colors_site_truth.json) holds slugs and hex values only; it is rebuilt offline with
`python collect/site_colors.py --truth-table --cache-dir <.cache/http>`.

Every check names, in a comment, the input that makes it fail.

Covers, in order:
  extract     classic and Nuxt pages give the right pair, upper-case #RRGGBB; a shifted Nuxt index and a
              page with neither config give nothing
  rule        white/white, a grey primary, black with a white secondary, a pair on 3 hosts, a denylisted
              pair and a classic theme-color mismatch are all left empty; a neutral secondary is dropped
              and the primary kept; black with a chromatic secondary is kept and flagged
  politeness  robots.txt before the fetch, again on an off-host redirect, and a host stopped at its
              first 403/429
  apply       a program that already has colours is untouched; colorsSource is set with the colours
  agreement   the real rule clears the accepted floor and both agreement thresholds on the D1 table, and
              each control fails on the clause it is built to fail
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from collect import common  # noqa: E402
from collect import site_colors as sc  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False

# The D1 table's size, so a rebuilt table that silently shrinks is a reviewed edit here. The plan measured
# 308 hosts; two of those have no cached soccer page any more, so the table holds 306. The accepted floor
# stays at sc.MIN_ACCEPTED_D1 (280), which is stricter on 306 rows than it was on 308.
D1_TRUTH_ROWS = 306


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return cond


# Synthetic pages. The classic config mirrors Sidearm's inline JS object; the Nuxt payload is a flat
# array whose object values are indices into it.
CLASSIC = ('<html><head><meta name="theme-color" content="#8a2432"></head><body><script>'
           'var sidearmTheme = {"primary_background":"#8a2432","primary_text":"#ffffff",'
           '"secondary_background":"#c4a45a"};</script></body></html>')
CLASSIC_MISMATCH = CLASSIC.replace('content="#8a2432"', 'content="#123456"')
NUXT = ('<html><body><script type="application/json" id="__NUXT_DATA__" data-ssr="true">'
        '[{"state":1},{"siteColorPrimaryBackground":3,"siteColorSecondaryBackground":4},"site","#0c2340","#c99700"]'
        '</script></body></html>')
NUXT_SHIFTED = NUXT.replace('"siteColorPrimaryBackground":3,"siteColorSecondaryBackground":4',
                            '"siteColorPrimaryBackground":2,"siteColorSecondaryBackground":3')
NUXT_OUT_OF_RANGE = NUXT.replace('"siteColorPrimaryBackground":3', '"siteColorPrimaryBackground":9')
PLAIN = "<html><head><title>Athletics</title></head><body><p>No theme here.</p></body></html>"


def test_extract() -> None:
    print("extract")
    # fails if the classic regexes miss the config or values are not upper-cased
    ok("classic page gives its primary, secondary and theme-color, upper-case",
       sc.extract(CLASSIC) == ("classic", {"primary": "#8A2432", "secondary": "#C4A45A", "theme": "#8A2432"}),
       str(sc.extract(CLASSIC)))
    # fails if the Nuxt values are used as literals instead of resolved as payload indices
    ok("Nuxt page resolves the indices to the right pair",
       sc.extract(NUXT) == ("nuxt", {"primary": "#0C2340", "secondary": "#C99700", "theme": None}), str(sc.extract(NUXT)))
    # fails if an index that points at a non-hex value, or past the payload, still yields colours
    ok("a shifted Nuxt index gives nothing", sc.extract(NUXT_SHIFTED) == ("nuxt", None), str(sc.extract(NUXT_SHIFTED)))
    ok("an out-of-range Nuxt index gives nothing", sc.extract(NUXT_OUT_OF_RANGE)[1] is None)
    # fails if a page with neither config yields anything
    ok("a page with neither config gives nothing", sc.extract(PLAIN) == ("none", None))
    ok("3-digit hex is expanded, junk is refused", sc.norm_hex("#abc") == "#AABBCC" and sc.norm_hex("red") is None
       and sc.norm_hex("#12345") is None)


def _recs(*pairs, template="nuxt"):
    return [{"slug": f"s{i}", "host": f"h{i}.example", "template": template, "primary": p, "secondary": s, "theme": None}
            for i, (p, s) in enumerate(pairs)]


def test_rule() -> None:
    print("rule")
    must_reject = {
        "white/white": ("#FFFFFF", "#FFFFFF"),
        "grey primary": ("#808080", "#C8102E"),
        "black primary with a white secondary": ("#000000", "#FFFFFF"),
    }
    for name, (p, s) in must_reject.items():
        r = _recs((p, s))
        sc.decide_all(r)
        # fails if this pair is filled
        ok(f"rejected: {name}", r[0]["colors"] is None and r[0]["outcome"].startswith("rejected"), str(r[0]))
    # fails if the denylist compares case-sensitively or is skipped
    r = _recs(("#ffffff", "#ffffff"))
    sc.decide_all(r, guard_hosts=None)
    ok("a denylisted pair (lower-case on the page) is rejected", r[0]["outcome"] == "rejected: denylisted", str(r[0]))
    # fails if a pair served by 3 hosts is filled, or the guard compares case-sensitively
    r = _recs(("#1D4F91", "#C99700"), ("#1d4f91", "#c99700"), ("#1D4F91", "#C99700"), ("#8A2432", "#C4A45A"))
    sc.decide_all(r)
    ok("a pair repeated on 3 hosts is rejected on all three",
       [x["outcome"] for x in r[:3]] == ["rejected: template-guard"] * 3 and all(x["colors"] is None for x in r[:3]),
       str([x["outcome"] for x in r]))
    ok("a pair on one host is still accepted beside them", r[3]["colors"] == ["#8A2432", "#C4A45A"], str(r[3]))
    # fails if a classic page whose theme-color differs from primary_background is filled
    t, c = sc.extract(CLASSIC_MISMATCH)
    r = [dict(c, slug="m", host="m.example", template=t)]
    sc.decide_all(r)
    ok("classic theme-color mismatch is rejected", r[0]["outcome"] == "rejected: theme-mismatch" and r[0]["colors"] is None)
    # fails if the theme guard reaches Nuxt pages, which carry no theme-color
    r = _recs(("#0C2340", "#C99700"))
    r[0]["theme"] = "#123456"
    sc.decide_all(r)
    ok("the theme guard does not apply to Nuxt pages", r[0]["colors"] == ["#0C2340", "#C99700"], str(r[0]))
    # fails if a neutral secondary is stored, or its primary is dropped with it
    r = _recs(("#8A2432", "#D3D3D3"), ("#003366", "#FFFFFF"), ("#00539B", "#252525"))
    sc.decide_all(r)
    ok("a neutral secondary is dropped and the primary kept",
       [x["colors"] for x in r] == [["#8A2432"], ["#003366"], ["#00539B"]]
       and all("secondary-dropped" in x["flags"] for x in r), str([x["colors"] for x in r]))
    # fails if black-and-gold is refused, or not flagged for the review list
    r = _recs(("#000000", "#FFC72C"))
    sc.decide_all(r)
    ok("black primary with a chromatic secondary is kept and flagged",
       r[0]["colors"] == ["#000000", "#FFC72C"] and r[0]["flags"] == ["black-primary"], str(r[0]))
    # fails if a secondary within dE 10 of the primary is stored as a second colour
    r = _recs(("#8A2432", "#8C2634"))
    sc.decide_all(r)
    ok("a secondary within dE 10 of the primary is not stored", r[0]["colors"] == ["#8A2432"], str(r[0]))


class FakeNet:
    """Monkeypatched robots_allowed / fetch_text / forget_cached: records every call, answers from tables."""

    def __init__(self, disallowed=(), pages=None, errors=None, redirects=None):
        self.disallowed, self.pages, self.errors, self.redirects = set(disallowed), pages or {}, errors or {}, redirects or {}
        self.robots_calls, self.fetch_calls, self.forgotten = [], [], []

    def robots_allowed(self, url):
        self.robots_calls.append(url)
        return url not in self.disallowed

    def fetch_text(self, url, **kw):
        self.fetch_calls.append(url)
        if url in self.errors:
            status = self.errors[url]
            raise common.FetchError(f"HTTP {status} for {url}", status=status, final_url=url)
        return self.pages.get(url, NUXT), {"finalUrl": self.redirects.get(url, url), "fromCache": False}

    def forget_cached(self, url, **kw):
        self.forgotten.append(url)
        return True

    def __enter__(self):
        self.saved = common.robots_allowed, common.fetch_text, common.forget_cached
        common.robots_allowed, common.fetch_text, common.forget_cached = self.robots_allowed, self.fetch_text, self.forget_cached
        return self

    def __exit__(self, *exc):
        common.robots_allowed, common.fetch_text, common.forget_cached = self.saved


def _prog(slug, base, division="D3", colors=None, **athletics):
    return {"slug": slug, "division": division, "onboarded": True, "colors": colors,
            "athletics": dict({"platform": "sidearm", "baseUrl": base, "sportPath": "/sports/womens-soccer"}, **athletics)}


def test_politeness() -> None:
    print("politeness")
    tmp = tempfile.mkdtemp()
    # (i) fails if a start URL robots.txt disallows is fetched anyway
    a = _prog("a", "https://a.example")
    with FakeNet(disallowed={sc.page_url(a)}) as net:
        rep = sc.run({"programs": [a]}, report_path=None, sleep=lambda s: None)
    ok("(i) a disallowed start URL is never fetched", net.fetch_calls == [] and rep["programs"][0]["outcome"] == "skipped: robots",
       str(net.fetch_calls))
    # (ii) fails if a page redirected onto a disallowed host is used, or its cache entry kept
    b = _prog("b", "https://b.example")
    other = "https://elsewhere.example/sports/wsoc"
    with FakeNet(disallowed={other}, redirects={sc.page_url(b): other}) as net:
        rep = sc.run({"programs": [b]}, report_path=None, sleep=lambda s: None)
    e = rep["programs"][0]
    ok("(ii) an off-host redirect to a disallowed URL is discarded: no colours",
       e["outcome"] == "skipped: robots (redirect)" and "colors" not in e and rep["counts"]["accepted"] == 0
       and other in net.robots_calls and net.forgotten == [sc.page_url(b)], str(e))
    # (iii) fails if a host that answered 403 is asked again in the same run
    c1 = _prog("c1", "https://c.example")
    c2 = _prog("c2", "https://c.example", sportPath="/sports/wsoc")
    with FakeNet(errors={sc.page_url(c1): 403}) as net:
        rep = sc.run({"programs": [c1, c2]}, report_path=None, sleep=lambda s: None)
    ok("(iii) after a 403, the second program on that host is never requested",
       net.fetch_calls == [sc.page_url(c1)] and [x["outcome"] for x in rep["programs"]] == ["skipped: host stopped (403)"] * 2
       and rep["refusedHosts"] == ["c.example"], str(net.fetch_calls))
    # fails if a 429 on a redirect's final host does not stop that host too
    d1, d2 = _prog("d1", "https://d.example"), _prog("d2", "https://final.example")
    with FakeNet() as net:
        def refuse(url, **kw):
            net.fetch_calls.append(url)
            raise common.FetchError("HTTP 429", status=429, final_url="https://final.example/x")
        common.fetch_text = refuse
        rep = sc.run({"programs": [d1, d2]}, report_path=None, sleep=lambda s: None)
    ok("a 429 stops both the requested host and the final host", len(net.fetch_calls) == 1
       and [x["outcome"] for x in rep["programs"]] == ["skipped: host stopped (429)"] * 2, str(net.fetch_calls))
    # fails if a program with athletics.skipReason is fetched
    s = _prog("s", "https://s.example", skipReason="auto")
    with FakeNet() as net:
        rep = sc.run({"programs": [s]}, report_path=os.path.join(tmp, "r.json"), sleep=lambda s: None)
    ok("a program with athletics.skipReason is not fetched and is listed",
       net.fetch_calls == [] and rep["skippedForSkipReason"] == ["s"], str(net.fetch_calls))
    # fails if the report carries anything but slugs, hosts, hex values and flags
    allowed = {"slug", "division", "host", "finalHost", "template", "primary", "secondary", "theme", "outcome", "colors", "flags"}
    g = _prog("g", "https://g.example")
    with FakeNet(pages={sc.page_url(g): CLASSIC}):
        rep = sc.run({"programs": [g]}, report_path=None, sleep=lambda s: None)
    ok("a report entry holds only slug, host, hex values and flags", set(rep["programs"][0]) <= allowed
       and rep["programs"][0]["colors"] == ["#8A2432", "#C4A45A"], str(rep["programs"][0]))


def test_apply() -> None:
    print("apply")
    reg = {"programs": [
        {"slug": "has", "colors": ["#00274C", "#FFCB05"]},  # existing colours, and a site pair the rule accepts
        {"slug": "none", "colors": None},
        {"slug": "unlisted", "colors": None}]}
    found = {"has": ["#8A2432", "#C4A45A"], "none": ["#0C2340"]}
    sc.apply_mutate(found)(reg)
    # fails if existing colours are overwritten, or labelled as coming from the site
    ok("a program that already has colours is untouched", reg["programs"][0] == {"slug": "has", "colors": ["#00274C", "#FFCB05"]},
       str(reg["programs"][0]))
    # fails if the colours are written without colorsSource, or colorsSource without colours
    ok("an accepted program gets its colours and colorsSource athletics-site",
       reg["programs"][1] == {"slug": "none", "colors": ["#0C2340"], "colorsSource": "athletics-site"}, str(reg["programs"][1]))
    ok("a program not in the report is untouched", reg["programs"][2] == {"slug": "unlisted", "colors": None})
    # fails if apply writes anything but the report's accepted entries, or fetches
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "report.json")
    common.write_json(path, {"programs": [{"slug": "none", "outcome": "accepted", "colors": ["#0C2340"]},
                                          {"slug": "unlisted", "outcome": "rejected: primary-grey"}]})
    seen = {}
    saved = common.update_registry, common.fetch_text
    try:
        common.update_registry = lambda mutate: seen.setdefault("reg", copy.deepcopy(reg)) and mutate(seen["reg"])
        common.fetch_text = lambda *a, **k: (_ for _ in ()).throw(AssertionError("apply must not fetch"))
        reg["programs"][1] = {"slug": "none", "colors": None}
        out = sc.apply_report(path)
    finally:
        common.update_registry, common.fetch_text = saved
    ok("apply writes only the report's accepted colours, without fetching",
       out == {"none": ["#0C2340"]} and seen["reg"]["programs"][1].get("colorsSource") == "athletics-site"
       and seen["reg"]["programs"][2] == {"slug": "unlisted", "colors": None}, str(seen.get("reg")))


def test_agreement() -> None:
    print("agreement")
    rows = common.read_json(sc.TRUTH_PATH)["rows"]
    ok(f"the D1 table has {D1_TRUTH_ROWS} rows of slugs and hex values",
       len(rows) == D1_TRUTH_ROWS and all(set(r) == {"slug", "template", "primary", "secondary", "theme", "wikipedia"} for r in rows),
       str(len(rows)))
    real = sc.agreement(rows)
    # fails if the rule or the extractor regresses: fewer than 280 accepted, or agreement below 90% / 95%
    ok("the real rule passes both clauses", sc.agreement_failures(real) == [], f"{real} {sc.agreement_failures(real)}")
    if VERBOSE:
        print("   ", real)
    # Controls: each must fail, and on the clause it is built to fail.
    grey = [dict(r, primary="#808080", theme="#808080" if r["theme"] else None) for r in rows]
    st = sc.agreement(grey)
    ok("control: grey-swapped primaries fail the accepted-count floor",
       st["accepted"] == 0 and "accepted-floor" in sc.agreement_failures(st), str(st))
    const = [dict(r, primary="#1D4F91", secondary="#C99700", theme="#1D4F91" if r["theme"] else None) for r in rows]
    st = sc.agreement(const, guard_hosts=None)
    f = sc.agreement_failures(st)
    ok("control: a constant palette clears the floor but fails agreement",
       "accepted-floor" not in f and {"all-agree", "primary-agree"} <= set(f), f"{st} {f}")
    st = sc.agreement(const)
    ok("control: with the pair guard on, a constant palette is not accepted at all", st["accepted"] == 0, str(st))
    nuxt = [i for i, r in enumerate(rows) if r["template"] == "nuxt"]
    shifted = [dict(r) for r in rows]
    for a, b in zip(nuxt, nuxt[1:] + nuxt[:1]):  # every Nuxt row reads its neighbour's slot
        shifted[a].update(primary=rows[b]["primary"], secondary=rows[b]["secondary"])
    st = sc.agreement(shifted)
    f = sc.agreement_failures(st)
    ok("control: a shifted Nuxt index clears the floor but fails agreement",
       "accepted-floor" not in f and {"all-agree", "primary-agree"} <= set(f), f"{st} {f}")
    # fails if zero accepted could pass as 0/0
    ok("zero accepted fails every clause", sc.agreement_failures({"accepted": 0, "allAgree": 0, "primaryAgree": 0})
       == ["accepted-floor", "all-agree", "primary-agree"])


def main() -> int:
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose
    test_extract()
    test_rule()
    test_politeness()
    test_apply()
    test_agreement()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
