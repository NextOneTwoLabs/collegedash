"""The recommender's fit facts, public/data/fit/index.json and /api/v1/fit (issue #400, PR 1).

    python tests/fit_index_test.py            # every case
    python tests/fit_index_test.py --verbose  # print every check, not only the failures

Built here from the committed public/data/programs/*.json with build.fit_entry and build.fit_index, the functions the
build calls, so the checks run on every real program without a full build (tests/seasons_test.py's scratch build runs
the writer and build.validate's FIT checks end to end). Unit cases use made-up profiles. Nothing is written under
public/; a local serve.py on a loopback port serves a scratch copy. Offline, under tests/netguard.

Cases:
  rules        the owner's D2 rule exactly: coldest-month mean of 12 monthly normals, rounded to 0.1F, then mild >=45,
               four-season 27-45, cold <27, "unknown" past 50 km; the thresholds and 50 km on both sides; fewer than 12
               months, no distance, no climate source.
  constants    the size bands (D1) and climate thresholds (D2) as approved, the regions as build.REGIONS, the taxonomy.
  committed    one entry per published slug in the index's order, exactly build.FIT_KEYS, the schema accepts it, the
               climate counts per division (printed), the 3 programs with no school or climate source, and the size.
  list         the slim list does not carry fit (agreed on #400 with #395): no climate field on its rows.
  complaints   build.fit_complaints is clean on the real file and names each fault; the schema refuses bad shapes.
  check        build.check_fit_index on a scratch output directory of made-up programs: passes, then fails with FIT lines.
  path         fit_path() follows a swapped PROGRAMS_OUT_DIR.
  serve        serve.py answers /api/v1/fit from data/fit/index.json and refuses the raw path.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import gzip
import http.client
import io
import json
import os
import shutil
import sys
import tempfile
import threading
from collections import Counter
from functools import partial
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import build  # noqa: E402
import serve  # noqa: E402
from collect import common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail="") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


PROGRAMS = os.path.join(ROOT, "public", "data", "programs")
INDEX = json.load(open(os.path.join(PROGRAMS, "index.json"), encoding="utf-8"))


def load_profile(slug: str) -> dict | None:
    return common.read_json(os.path.join(PROGRAMS, f"{slug}.json"))


PROFILES = {r["slug"]: load_profile(r["slug"]) for r in INDEX["programs"]}
FIT = build.fit_index(INDEX["updated"], {slug: build.fit_entry(p or {}) for slug, p in PROFILES.items()})
SCHEMA = json.load(open(os.path.join(ROOT, "schema", "fit.schema.json"), encoding="utf-8"))
try:
    import jsonschema
except ImportError:  # requirements.txt has it; say so rather than pass silently
    jsonschema = None


def schema_errors(doc) -> list[str]:
    if jsonschema is None:
        return ["jsonschema is not installed"]
    return [e.message for e in jsonschema.Draft202012Validator(SCHEMA).iter_errors(doc)]


@contextlib.contextmanager
def swapped(**attrs):
    old = {k: getattr(common, k) for k in attrs}
    for k, v in attrs.items():
        setattr(common, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(common, k, v)


def months(cold_mean: float, warm_mean: float = 70.0, spread: float = 20.0) -> list[dict]:
    """Twelve made-up monthly normals whose coldest-month mean is exactly cold_mean (high and low +-spread/2)."""
    out = [{"month": m, "tHighF": warm_mean + spread / 2, "tLowF": warm_mean - spread / 2} for m in range(1, 12)]
    out.insert(0, {"month": 0, "tHighF": cold_mean + spread / 2, "tLowF": cold_mean - spread / 2})
    return out


def profile(cold_mean=None, km=11.0, *, monthly=None, climate=True, school=True) -> dict:
    p = {}
    if climate:
        p["climate"] = {"monthly": monthly if monthly is not None else (months(cold_mean) if cold_mean is not None else []),
                        "station": {"id": "USW00000001", "distanceKm": km},
                        "_meta": {"source": "climate", "asOf": "2026-09-08T00:51:06Z"}}
    if school:
        p["school"] = {"unitId": 100001, "_meta": {"source": "scorecard", "asOf": "2026-09-06T05:49:12Z"}}
    return p


def label(p: dict) -> tuple:
    e = build.fit_entry(p)
    return e["climate"], e["climateUnknown"]


def test_rules():
    print("rules: D2 exactly")
    for mean, want in ((60.0, "mild"), (45.0, "mild"), (44.9, "four-season"), (36.2, "four-season"),
                       (27.0, "four-season"), (26.9, "cold"), (6.4, "cold")):
        ok(f"coldest-month mean {mean}F -> {want}", label(profile(mean)) == (want, None), label(profile(mean)))
    ok("the label is taken from the rounded figure it shows: 26.96F rounds to 27.0, four-season",
       build.fit_entry(profile(26.96))["coldMonthMeanF"] == 27.0 and label(profile(26.96)) == ("four-season", None),
       build.fit_entry(profile(26.96)))
    ok("the coldest month is the minimum of the 12 means, whichever month it is",
       build.coldest_month_mean_f({"monthly": list(reversed(months(31.0)))}) == 31.0)
    ok("a station exactly 50 km away is labelled", label(profile(30.0, km=50.0)) == ("four-season", None))
    ok("a station 50.1 km away: climate unknown (far-station), the figures still shown",
       label(profile(30.0, km=50.1)) == (None, "far-station") and build.fit_entry(profile(30.0, km=50.1))["coldMonthMeanF"] == 30.0)
    ok("no station distance: unknown", label(profile(30.0, km=None)) == (None, "station-distance-unknown"))
    eleven = months(30.0)[:11]
    ok("11 months of normals: no figure, unknown (no-normals)", label(profile(monthly=eleven)) == (None, "no-normals")
       and build.fit_entry(profile(monthly=eleven))["coldMonthMeanF"] is None)
    gap = months(30.0)
    gap[5] = {"month": 5, "tHighF": None, "tLowF": 50.0}
    ok("a month missing its high: unknown (no-normals)", label(profile(monthly=gap)) == (None, "no-normals"))
    ok("no climate source at all: unknown (no-climate-source), no ids", build.fit_entry(profile(climate=False, school=False)) == {
        "climate": None, "climateUnknown": "no-climate-source", "coldMonthMeanF": None, "stationKm": None, "unitId": None,
        "station": None, "asOf": [None, None]})
    e = build.fit_entry(profile(30.0))
    ok("ids and fetch dates come from the profile's sources", e["unitId"] == 100001 and e["station"] == "USW00000001"
       and e["asOf"] == ["2026-09-06", "2026-09-08"], e)
    ok("an entry is exactly build.FIT_KEYS", tuple(e) == build.FIT_KEYS, tuple(e))


def test_constants():
    print("constants: as the owner approved on #400")
    c = build.fit_constants()
    ok("size bands 5,000 and 15,000 (D1: <5,000 / 5,000-14,999 / >=15,000)", c["sizeBands"] == [5000, 15000])
    ok("climate: mild >=45F, cold <27F, unknown past 50 km (D2)",
       (c["climate"]["mildMinF"], c["climate"]["coldBelowF"], c["climate"]["maxStationKm"]) == (45.0, 27.0, 50.0))
    ok("regions are build.REGIONS, 51 state codes including DC", c["regions"] == {r: sorted(s) for r, s in build.REGIONS.items()}
       and sum(len(v) for v in c["regions"].values()) == 51 and "DC" in c["regions"]["Mid-Atlantic"])
    ok("taxonomy fit-1", FIT["fitTaxonomy"] == "fit-1")


def test_committed():
    print("committed: the file the build would write from today's profiles")
    slugs = [r["slug"] for r in INDEX["programs"]]
    ok("one entry per published slug, in the index's order", list(FIT["fit"]) == slugs, (len(FIT["fit"]), len(slugs)))
    ok("every entry is exactly build.FIT_KEYS", all(tuple(e) == build.FIT_KEYS for e in FIT["fit"].values()))
    ok("the schema accepts it", not schema_errors(FIT), schema_errors(FIT)[:3])
    ok("the same `updated` as the index", FIT["updated"] == INDEX["updated"])
    div = {r["slug"]: r["division"] for r in INDEX["programs"]}
    by = {d: Counter() for d in ("D1", "D2", "D3")}
    for slug, e in FIT["fit"].items():
        by[div[slug]][e["climate"] or f"unknown:{e['climateUnknown']}"] += 1
    for d, c in by.items():
        print(f"    {d}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
    none = sorted(s for s, e in FIT["fit"].items() if e["climateUnknown"] == "no-climate-source")
    ok("the programs with no climate source are exactly those whose profile has none",
       none == sorted(s for s, p in PROFILES.items() if not (p or {}).get("climate")), none)
    far = sum(e["climateUnknown"] == "far-station" for e in FIT["fit"].values())
    ok("far-station is exactly the profiles whose station is over 50 km",
       far == sum(((p or {}).get("climate") or {}).get("station", {}).get("distanceKm", 0) > 50 for p in PROFILES.values()), far)
    labelled = sum(e["climate"] is not None for e in FIT["fit"].values())
    ok("most programs are labelled, some are not (the check is not vacuous)", 0 < len(FIT["fit"]) - labelled < labelled)
    raw = json.dumps(FIT, ensure_ascii=False, separators=(",", ":")).encode()
    print(f"    fit file {len(raw):,} B compact, {len(gzip.compress(raw, 9)):,} B gzip-9")
    ok("under 200 KB raw: a panel-only file", len(raw) < 200_000, len(raw))


def test_list():
    print("list: the slim list does not carry fit (#400 revision 2, agreed with #395)")
    ok("no fit or climate field among the list's kept fields", not {"fit", "climate"} & set(build.LIST_KEEP))
    ok("the recommender's row fields are all on the list", set(build.LIST_RECOMMENDER_FIELDS) <= set(build.LIST_KEEP))


def test_complaints():
    print("complaints: the real file is clean, and each fault is named")
    load = lambda slug: PROFILES.get(slug)  # noqa: E731
    ok("the real file: no complaints", build.fit_complaints(FIT, INDEX, load) == [], build.fit_complaints(FIT, INDEX, load)[:3])

    def broken(fn):
        doc = copy.deepcopy(FIT)
        fn(doc)
        return doc
    first, second = list(FIT["fit"])[:2]
    cases = [
        ("another `updated`", lambda d: d.__setitem__("updated", "1999-01-01T00:00:00Z"), "`updated`"),
        ("another taxonomy", lambda d: d.__setitem__("fitTaxonomy", "fit-0"), "fitTaxonomy"),
        ("a moved threshold", lambda d: d["constants"]["climate"].__setitem__("mildMinF", 50.0), "constants"),
        ("a slug missing", lambda d: d["fit"].pop(first), "missing ['" + first),
        ("an extra slug", lambda d: d["fit"].__setitem__("not-a-program", d["fit"][first]), "extra ['not-a-program"),
        ("reordered", lambda d: d.__setitem__("fit", dict(reversed(list(d["fit"].items())))), "index's order"),
        ("a changed label", lambda d: d["fit"][second].__setitem__("climate", "mild" if d["fit"][second]["climate"] != "mild" else "cold"),
         f"{second}: climate"),
        ("an extra key", lambda d: d["fit"][first].__setitem__("region", "West"), f"{first}: region"),
    ]
    for name, fn, want in cases:
        lines = build.fit_complaints(broken(fn), INDEX, load)
        ok(f"{name}: named", any(want in l for l in lines), lines[:3])
    ok("not a fit file at all: named", build.fit_complaints(None, INDEX, load) != [] and build.fit_complaints({}, INDEX, load) != [])
    for name, fn in [("an extra key", lambda d: d["fit"][first].__setitem__("region", "West")),
                     ("an unknown label", lambda d: d["fit"][first].update(climate="tropical", climateUnknown=None)),
                     ("label and unknown both null", lambda d: d["fit"][first].update(climate=None, climateUnknown=None)),
                     ("a bad date", lambda d: d["fit"][first].__setitem__("asOf", ["2026-9-6", None])),
                     ("a bad slug", lambda d: d["fit"].__setitem__("Not A Slug", d["fit"][first]))]:
        ok(f"schema refuses {name}", schema_errors(broken(fn)) != [])


def test_check():
    print("check: build.check_fit_index on a scratch output directory (made-up programs)")
    tmp = tempfile.mkdtemp(prefix="fit-check-")
    progs = os.path.join(tmp, "programs")
    try:
        with swapped(PROGRAMS_OUT_DIR=progs):
            made = {"alpha-college": profile(40.0), "beta-university": profile(20.0, km=80.0)}
            index = {"updated": "2026-10-01T00:00:00Z", "programs": [{"slug": s} for s in made]}
            common.write_json(os.path.join(progs, "index.json"), index)
            for s, p in made.items():
                common.write_json(os.path.join(progs, f"{s}.json"), p)
            doc = build.fit_index(index["updated"], {s: build.fit_entry(p) for s, p in made.items()})
            common.write_json(build.fit_path(), doc, compact=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                good = build.check_fit_index()
            ok("passes on the file the build would write", good, buf.getvalue()[:300])
            ok("... which labels alpha four-season and beta unknown (far-station)",
               (doc["fit"]["alpha-college"]["climate"], doc["fit"]["beta-university"]["climateUnknown"]) == ("four-season", "far-station"))
            common.write_json(os.path.join(progs, "alpha-college.json"), profile(50.0))  # the profile moved on, the file did not
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                stale = build.check_fit_index()
            ok("fails, printing FIT lines, when an entry no longer matches its profile",
               not stale and "FIT: alpha-college: climate, coldMonthMeanF differ" in buf.getvalue(), buf.getvalue()[:300])
            os.remove(build.fit_path())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                missing = build.check_fit_index()
            ok("fails on a missing file", not missing and "FIT: " in buf.getvalue(), buf.getvalue()[:300])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_path():
    print("path: fit_path() follows PROGRAMS_OUT_DIR")
    live = os.path.join(common.PUBLIC_DATA_DIR, "fit", "index.json")
    ok("live: public/data/fit/index.json", os.path.normpath(build.fit_path()) == os.path.normpath(live), build.fit_path())
    tmp = tempfile.mkdtemp(prefix="fit-path-")
    try:
        with swapped(PROGRAMS_OUT_DIR=os.path.join(tmp, "programs")):
            ok("swapped: beside the swapped programs directory",
               os.path.normpath(build.fit_path()) == os.path.normpath(os.path.join(tmp, "fit", "index.json")), build.fit_path())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok("outside public/data/programs, so the profile prune can never read it as a slug",
       os.path.dirname(os.path.dirname(build.fit_path())) == os.path.dirname(os.path.abspath(common.PROGRAMS_OUT_DIR)))


def test_serve():
    print("serve: serve.py answers /api/v1/fit")
    tmp = tempfile.mkdtemp(prefix="fit-serve-")
    body = json.dumps(FIT, ensure_ascii=False, separators=(",", ":")).encode()
    os.makedirs(os.path.join(tmp, "data", "fit"))
    with open(os.path.join(tmp, "data", "fit", "index.json"), "wb") as f:
        f.write(body)
    httpd = None
    try:
        with swapped(PUBLIC_DIR=tmp):
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(serve.Handler, directory=tmp))
            threading.Thread(target=httpd.serve_forever, daemon=True).start()

            def get(path):
                conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
                conn.request("GET", path)
                r = conn.getresponse()
                data = r.read()
                conn.close()
                return r.status, data
            status, data = get("/api/v1/fit")
            ok("200 with the file's bytes", status == 200 and data == body, (status, data[:80]))
            status, _ = get("/data/fit/index.json")
            ok("the raw path is refused", status == 404, status)
    finally:
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_rules, test_constants, test_committed, test_list, test_complaints, test_check, test_path, test_serve):
        try:
            case()
        except Exception as e:  # a case that raises is a failed case, not a lost run
            ok(f"{case.__name__} ran to the end", False, f"{type(e).__name__}: {e}")
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
