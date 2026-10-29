"""Issue #79: camp pages that yield zero rows are labelled, and the camps index says how many there are.

    python tests/camps_readable_test.py            # everything below, offline
    python tests/camps_readable_test.py --verbose  # print every check, not only the failures

Offline and frozen: every record and profile here is hand-built (shaped like real stored ones, named in the plan,
docs/plans/79-camp-zero-rows.md), nothing depends on today's date, and nothing reads the committed data. The one
validate check writes into a temporary directory.

Covers, in order:
  readability  build.camp_readability(record), a pure function of the stored camps record:
               - `null` whenever the record has a dated row (njit's Google Form, plymouth-state's NBS store page),
                 has no camp link, or has a fetchError, robotsBlocked or hostRefused (they keep their own messages);
               - `not-a-listing`: an exact host list (the host, or a subdomain of it: secure.touchnet.net,
                 ithacaedu.formstack.com; never docs.google.com.example), a waiver/liability/form(s) path word
                 between separators (so information-camps-index and uniforms do not match), an image extension,
                 and Sidearm's image proxy judged by the inner URL;
               - `app-shell`: the stored vendor is totalcamps;
               - `not-html`: `parsed` false after those gates.
  profile      build_camps writes `unreadable` and `hostRefused` onto the profile's camps block.
  coverage     build.camp_coverage(profiles): one bucket per program in a fixed order, exact counts on a fixture,
               the buckets add up to `programs`, the key order is fixed, and it carries counts only.
  validate     check_camps_index recomputes `coverage` from the profiles: a tampered or missing block fails, a
               correct one passes.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import build  # noqa: E402
from collect import common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


# A dated camp-page row. The date is a fixed placeholder: nothing here compares it with today.
ROW = {"name": "Women's Soccer ID Camp", "startDate": "1999-06-01", "endDate": "1999-06-01", "dateText": "June 1",
       "precision": "day", "yearInferred": False, "location": None, "ages": None, "price": None,
       "registerUrl": None, "sourceUrl": "https://camps.example.org/", "confidence": "heuristic"}


def rec(url, *, final=None, vendor="external", parsed=True, camps=(), **kw) -> dict:
    """A stored camps record (`data` of programs/<slug>/sources/camps.json), shaped like the collector writes it."""
    from urllib.parse import urlsplit
    final = final or url
    return {"campsUrl": url, "discoveredVia": "anchor", "hubUrl": None, "finalUrl": final,
            "host": urlsplit(final).hostname if final else None, "vendor": vendor, "pageTitle": None,
            "robotsBlocked": False, "fetchError": None, "parsed": parsed, "camps": [dict(r) for r in camps],
            "newsCamps": [], "newsScanned": 0, "hostRefused": False, "linkReused": False, **kw}


def cause(record):
    v = build.camp_readability(record)
    return v.get("cause") if isinstance(v, dict) else v


def test_readability() -> None:
    print("readability: camp_readability on hand-built records")
    if not ok("build.camp_readability exists", callable(getattr(build, "camp_readability", None))):
        return
    caught = [
        # the path rule, on the shapes of the six real waiver/form documents (plan section 2)
        ("aurora: a liability-form-waiver page", "not-a-listing",
         rec("https://athletics.aurora.example/sports/2019/3/12/sport-camp-liability-form-waiver.aspx")),
        ("west-alabama: a liability waiver PDF", "not-a-listing",
         rec("https://uwaathletics.example/documents/2017/6/1/UWA_Liability_Waiver_Camps.pdf", parsed=False)),
        ("st-norbert-college: an ID camp waiver PDF", "not-a-listing",
         rec("https://athletics.snc.example/documents/2026/4/10/SNC_WSOC_ID_Camp_Waiver_2026.pdf", parsed=False)),
        ("west-texas-am: Camp_Forms.pdf", "not-a-listing",
         rec("https://gobuffsgo.example/documents/2023/12/11/Camp_Forms.pdf", parsed=False)),
        ("wisconsin-stevens-point: a health form PDF, with a query string", "not-a-listing",
         rec("https://athletics.uwsp.example/documents/2021/6/14/Camp_Health_Form_Combined.pdf?path=at", parsed=False)),
        ("rose-hulman: a prospect camp form .docx", "not-a-listing",
         rec("https://athletics.rose-hulman.example/documents/2026/2/23/2026_ROSE_WSOC_July_18_Prospect_Camp_Form.docx")),
        ("hollins: a /register/form page", "not-a-listing",
         rec("https://admissions.hollins.example/register/form?id=97f63ec0&path=wsoc")),
        # the host list: the host itself, and a subdomain of it
        ("a Google Form", "not-a-listing", rec("https://docs.google.com/forms/d/e/1FAIpQLSexample/viewform")),
        ("forms.gle", "not-a-listing", rec("https://forms.gle/abc123")),
        ("a TouchNet store on secure.touchnet.net", "not-a-listing",
         rec("https://secure.touchnet.net/C20627_ustores/web/index.jsp")),
        ("a TouchNet store on secure.touchnet.com", "not-a-listing",
         rec("https://secure.touchnet.com/C20568_ustores/web/store_main.jsp?STOREID=11")),
        ("a formstack form on ithacaedu.formstack.com", "not-a-listing",
         rec("https://ithacaedu.formstack.com/forms/wsoccercamp2026")),
        ("an agileticketing page on prod1.agileticketing.net", "not-a-listing",
         rec("https://prod1.agileticketing.net/websales/pages/list.aspx?epguid=x")),
        ("an NBS store", "not-a-listing", rec("https://salve.nbsstore.net/womens-soccer-clinic-2026")),
        ("an eventbrite page on www.eventbrite.com", "not-a-listing",
         rec("https://www.eventbrite.com/e/womens-soccer-id-camp-registration-1")),
        ("an upper-case host", "not-a-listing", rec("https://Docs.Google.COM/forms/d/e/x/viewform")),
        ("the FINAL url decides: a camp link that redirected to a TouchNet store", "not-a-listing",
         rec("https://athletics.example.edu/camps", final="https://secure.touchnet.net/C1_ustores/web/index.jsp")),
        # images, directly and through Sidearm's proxy (judged by the inner URL)
        ("a camp flyer image", "not-a-listing",
         rec("https://mcmurrysports.example/images/2026/8/24/Ava_Camp.JPG", parsed=False)),
        ("an image through the Sidearm proxy", "not-a-listing",
         rec("https://images.sidearmdev.com/convert?url=https%3a%2f%2fdxbhsrqyrr690.cloudfront.net%2fsidearm.nextgen.sites"
             "%2fathletics.augsburg.example%2fimages%2f2026%2f8%2f25%2fcamp_kaidin.jpg&type=webp", parsed=False)),
        ("a waiver PDF through the Sidearm proxy", "not-a-listing",
         rec("https://images.sidearmdev.com/convert?url=https%3a%2f%2fexample.edu%2fdocuments%2fCamp_Waiver.pdf",
             parsed=False)),
        # the vendor
        ("TotalCamps (vendor totalcamps), nothing dated", "app-shell",
         rec("https://acusoccer.totalcamps.com/", vendor="totalcamps")),
        ("TotalCamps on a custom domain: the stored vendor decides, not the host", "app-shell",
         rec("https://soccercamps.example.com/", vendor="totalcamps")),
        # parsed false after the gates
        ("a PDF flyer that is not a form", "not-html",
         rec("https://athletics.example.edu/documents/2026/5/7/Summer_ID_camps_flyer.pdf", parsed=False)),
    ]
    for label, want, r in caught:
        got = cause(r)
        ok(f"caught: {label} -> {want}", got == want, f"got {got!r}")
    ok("the verdict is an object {cause}, not a bare string",
       build.camp_readability(caught[0][2]) == {"cause": "not-a-listing"}, repr(build.camp_readability(caught[0][2])))

    controls = [
        ("njit: a Google Form WITH a dated row", rec("https://docs.google.com/forms/d/e/1FAIpQLSf30/viewform", camps=[ROW])),
        ("plymouth-state: an NBS store page WITH a dated row",
         rec("https://plymouth-usnh.nbsstore.net/psu-womens-soccer-id-clinic-november-22-2026", camps=[ROW])),
        ("a TotalCamps record WITH a dated row", rec("https://x.totalcamps.com/", vendor="totalcamps", camps=[ROW])),
        ("a not-HTML record WITH a dated row", rec("https://example.edu/camp.pdf", parsed=False, camps=[ROW])),
        ("Sidearm's information-camps-index hub, nothing dated",
         rec("https://athletics.example.edu/sports/2020/5/5/information-camps-index.aspx")),
        ("Sidearm's information-camps-index hub, with rows",
         rec("https://athletics.example.edu/sports/2020/5/5/information-camps-index.aspx", camps=[ROW])),
        ("information-camps-clinics-index, nothing dated",
         rec("https://athletics.example.edu/sports/2021/1/1/information-camps-clinics-index.aspx")),
        ("information-camps-clinics-index, with rows",
         rec("https://athletics.example.edu/sports/2021/1/1/information-camps-clinics-index.aspx", camps=[ROW])),
        ("a path with `uniforms`", rec("https://athletics.example.edu/sports/womens-soccer/uniforms-camp")),
        ("a path with `platform`", rec("https://camps.example.org/platform/womens-soccer")),
        ("a host that only CONTAINS a listed name: docs.google.com.example",
         rec("https://docs.google.com.example/camps/womens-soccer")),
        ("a host that ends in a listed name without a dot: notformstack.com", rec("https://notformstack.com/camps")),
        ("an image extension in the query only", rec("https://camps.example.org/register?banner=camp.jpg")),
        ("an athletics camp page with nothing dated", rec("https://athletics.example.edu/sports/womens-soccer/camps")),
        ("a Ryzer page with nothing dated", rec("https://register.ryzer.com/camp.cfm?id=1", vendor="ryzer")),
        ("an older record with parsed null", rec("https://athletics.example.edu/camps", parsed=None)),
        ("a fetch error on a Google Form", rec("https://docs.google.com/forms/d/e/x/viewform", parsed=False,
                                               fetchError="HTTP 404")),
        ("a fetch error on TotalCamps", rec("https://x.totalcamps.com/", vendor="totalcamps", parsed=False,
                                            fetchError="HTTP 500")),
        ("a refused host (recorded, with its fetchError)",
         rec("https://marywood.universitytickets.com/w/default.aspx?cid=160", parsed=False, hostRefused=True,
             fetchError="HTTP 403")),
        ("a refused host WITHOUT a fetchError: the rule does not depend on the pairing",
         rec("https://linktr.ee/x", parsed=False, hostRefused=True)),
        ("a robots block", rec("https://forms.cloud.microsoft/r/x", parsed=False, robotsBlocked=True)),
        ("no camp link", rec(None, final=None, parsed=None) | {"finalUrl": None}),
    ]
    for label, r in controls:
        got = build.camp_readability(r)
        ok(f"null: {label}", got is None, f"got {got!r}")
    for label, r in (("None", None), ("an empty record", {}), ("a string", "x"), ("camps not a list", rec("https://forms.gle/x") | {"camps": "x"})):
        try:
            got, err = build.camp_readability(r), None
        except Exception as e:  # noqa: BLE001 - a raise is the failure
            got, err = None, f"{type(e).__name__}: {e}"
        ok(f"malformed input is judged, not raised: {label}", err is None, err or "")
    r = rec("https://forms.gle/x")
    snapshot = json.dumps(r, sort_keys=True)
    build.camp_readability(r)
    ok("camp_readability does not change the record (pure)", json.dumps(r, sort_keys=True) == snapshot)


def env(record: dict | None) -> dict | None:
    """A source envelope as build_profile passes it to build_camps."""
    if record is None:
        return None
    return {"collector": "camps", "sourceUrl": record.get("finalUrl"), "fetchedAt": "2000-01-01T00:00:00Z", "data": record}


def test_profile() -> None:
    print("profile: build_camps writes `unreadable` and `hostRefused` onto the camps block")
    b = build.build_camps(env(rec("https://acusoccer.totalcamps.com/", vendor="totalcamps")), None, {})
    ok("a TotalCamps page with nothing dated carries unreadable {cause: app-shell}",
       b.get("unreadable") == {"cause": "app-shell"}, repr(b.get("unreadable")))
    b = build.build_camps(env(rec("https://docs.google.com/forms/d/e/x/viewform", camps=[ROW])), None, {})
    ok("a Google Form with a dated row carries unreadable null (the key is there)",
       "unreadable" in b and b["unreadable"] is None, repr(b.get("unreadable", "<absent>")))
    b = build.build_camps(env(rec("https://linktr.ee/x", parsed=False, hostRefused=True, fetchError="HTTP 403")), None, {})
    ok("a refused host carries hostRefused true and no cause", b.get("hostRefused") is True and b.get("unreadable") is None,
       repr({k: b.get(k) for k in ("hostRefused", "unreadable")}))
    b = build.build_camps(env(rec("https://athletics.example.edu/camps")), None, {})
    ok("an ordinary page carries hostRefused false", b.get("hostRefused") is False, repr(b.get("hostRefused")))


# ---------- coverage ----------

def profile(record: dict | None, curated=None) -> dict:
    return {"camps": build.build_camps(env(record), None, {"camps": curated} if curated else {})}


FIXTURE = [
    profile(None),                                                                         # skipped
    profile(None),                                                                         # skipped
    profile(None, curated=[{"name": "Hand-entered ID Camp", "startDate": "1999-07-01"}]),  # skipped: curated only
    profile(rec(None, final=None, parsed=None) | {"finalUrl": None}),                      # noLink
    profile(rec("https://forms.cloud.microsoft/r/x", parsed=False, robotsBlocked=True)),   # robots
    profile(rec("https://linktr.ee/x", parsed=False, hostRefused=True, fetchError="HTTP 403")),  # refusedHost
    profile(rec("https://abc.example/camps", parsed=False, fetchError="HTTP 404")),        # fetchFailed
    profile(rec("https://register.ryzer.com/camp.cfm?id=1", parsed=False, fetchError="HTTP 202")),  # fetchFailed
    profile(rec("https://a.totalcamps.com/", vendor="totalcamps")),                        # app-shell
    profile(rec("https://b.totalcamps.com/", vendor="totalcamps")),                        # app-shell
    profile(rec("https://c.totalcamps.com/", vendor="totalcamps")),                        # app-shell
    profile(rec("https://secure.touchnet.net/C1_ustores/web/index.jsp")),                  # not-a-listing
    profile(rec("https://example.edu/documents/Camp_Forms.pdf", parsed=False)),            # not-a-listing
    profile(rec("https://example.edu/documents/flyer.pdf", parsed=False)),                 # not-html
    profile(rec("https://docs.google.com/forms/d/e/x/viewform", camps=[ROW])),             # withRows (njit's shape)
    profile(rec("https://athletics.example.edu/camps", camps=[ROW, ROW])),                 # withRows
    profile(rec("https://athletics.example.edu/sports/2020/5/5/information-camps-index.aspx")),  # readNothingDated
    profile(rec("https://register.ryzer.com/camp.cfm?id=2", vendor="ryzer")),             # readNothingDated
]
FIXTURE_COVERAGE = {"programs": 18, "withRows": 2, "readNothingDated": 2,
                    "unreadable": {"app-shell": 3, "not-a-listing": 2, "not-html": 1},
                    "fetchFailed": 2, "refusedHost": 1, "robots": 1, "noLink": 1, "skipped": 3}


def bucket_sum(c: dict) -> int:
    return sum(v for k, v in c.items() if k not in ("programs", "unreadable")) + sum(c["unreadable"].values())


def test_coverage() -> None:
    print("coverage: one bucket per program, in a fixed order, counts only")
    if not ok("build.camp_coverage exists", callable(getattr(build, "camp_coverage", None))):
        return
    got = build.camp_coverage(FIXTURE)
    ok("exact counts on the fixture", got == FIXTURE_COVERAGE, json.dumps(got))
    ok("the key order is fixed", list(got) == list(FIXTURE_COVERAGE) and list(got.get("unreadable") or {}) ==
       list(FIXTURE_COVERAGE["unreadable"]), repr(list(got)))
    ok("the buckets add up to `programs`", bucket_sum(got) == got["programs"], json.dumps(got))
    ok("counts only: every value is an int (no slugs, hosts or URLs)",
       all(isinstance(v, int) for k, v in got.items() if k != "unreadable") and
       all(isinstance(v, int) for v in got["unreadable"].values()), json.dumps(got))
    empty = build.camp_coverage([])
    ok("no programs: every bucket named, at zero", empty == {k: ({c: 0 for c in v} if isinstance(v, dict) else 0)
                                                             for k, v in FIXTURE_COVERAGE.items()}, json.dumps(empty))
    # each program lands in exactly one bucket, so the order is what decides overlaps
    both = profile(rec("https://secure.touchnet.net/x", parsed=False, robotsBlocked=True, fetchError="HTTP 403",
                       hostRefused=True))
    ok("robots wins over refused host and fetch error", build.camp_coverage([both])["robots"] == 1)
    ok("refused host wins over its fetch error",
       build.camp_coverage([profile(rec("https://x.example/", parsed=False, hostRefused=True, fetchError="HTTP 403"))])
       ["refusedHost"] == 1)
    odd = [{"camps": "x"}, {}, "not a profile", {"camps": {"items": "x", "_meta": "x"}}]
    try:
        c, err = build.camp_coverage(odd), None
    except Exception as e:  # noqa: BLE001
        c, err = None, f"{type(e).__name__}: {e}"
    ok("malformed profiles are counted as skipped, not raised", err is None and c["skipped"] == 4 and c["programs"] == 4,
       err or json.dumps(c))
    tampered = {**FIXTURE[8], "camps": {**FIXTURE[8]["camps"], "unreadable": {"cause": "made-up"}}}
    c = build.camp_coverage([tampered])
    ok("an unknown cause is not counted as unreadable (the page was read)", c["readNothingDated"] == 1, json.dumps(c))


# ---------- validate ----------

def index_row(slug: str) -> dict:
    return {"slug": slug, "name": f"{slug.title()} College", "shortName": None, "division": "D3",
            "city": "Example City", "state": "OH", "region": "Midwest"}


UPDATED = "2000-01-01T00:00:00Z"


def scratch(tmp: str, coverage) -> dict:
    progs, camps = os.path.join(tmp, "programs"), os.path.join(tmp, "camps")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(progs)
    os.makedirs(camps)
    slugs = [f"p{i:02d}" for i in range(len(FIXTURE))]
    common.write_json(os.path.join(progs, "index.json"), {"updated": UPDATED, "programs": [index_row(s) for s in slugs]})
    for s, p in zip(slugs, FIXTURE):
        # no dated row lies inside the window below, so the index publishes no rows and only coverage is judged
        common.write_json(os.path.join(progs, f"{s}.json"), {"slug": s, **p})
    # #507: campPages is the sorted slugs of profiles with a camp url, as the build writes it
    pages = build.camp_page_slugs(zip(slugs, [p.get("camps") for p in FIXTURE]))
    doc = {"updated": UPDATED, "window": {"from": UPDATED[:10], "to": None}, "counts": build.camp_counts([]),
           "campPages": pages, "camps": []}
    if coverage is not None:
        doc["coverage"] = coverage
    common.write_json(os.path.join(camps, "index.json"), doc)
    return {"programs": [{"slug": s, "onboarded": True} for s in slugs]}


def run_check(tmp: str, coverage) -> tuple[bool, str]:
    reg = scratch(tmp, coverage)
    old = common.PROGRAMS_OUT_DIR, common.CAMPS_OUT_DIR
    common.PROGRAMS_OUT_DIR, common.CAMPS_OUT_DIR = os.path.join(tmp, "programs"), os.path.join(tmp, "camps")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            passed = build.check_camps_index(reg)
    finally:
        common.PROGRAMS_OUT_DIR, common.CAMPS_OUT_DIR = old
    return passed, buf.getvalue()


def test_validate() -> None:
    print("validate: check_camps_index recomputes `coverage` from the profiles")
    tmp = tempfile.mkdtemp(prefix="camps-coverage-")
    try:
        passed, out = run_check(tmp, FIXTURE_COVERAGE)
        ok("a correct coverage block passes", passed and not out, out[:400])
        tampered = {**FIXTURE_COVERAGE, "withRows": 3, "readNothingDated": 1}
        passed, out = run_check(tmp, tampered)
        ok("a tampered coverage block fails, and says so", not passed and "coverage" in out, out[:400])
        tampered = {**FIXTURE_COVERAGE, "unreadable": {**FIXTURE_COVERAGE["unreadable"], "app-shell": 0}}
        passed, out = run_check(tmp, tampered)
        ok("an unreadable count that does not match the profiles fails", not passed and "coverage" in out, out[:400])
        passed, out = run_check(tmp, None)
        ok("an index with no coverage block fails", not passed and "coverage" in out, out[:400])
        passed, out = run_check(tmp, "lots")
        ok("a coverage that is not an object fails, reported not raised", not passed and "coverage" in out, out[:400])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    VERBOSE = ap.parse_args(argv).verbose
    for t in (test_readability, test_profile, test_coverage, test_validate):
        try:
            t()
        except Exception as e:  # noqa: BLE001 - a raise in one group is a failure, and the others still run
            ok(f"{t.__name__} ran without raising", False, f"{type(e).__name__}: {e}")
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
