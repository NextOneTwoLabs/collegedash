"""The slim program list, public/data/list/index.json and /api/v1/list (issue #395, PR A).

    python tests/list_index_test.py            # every case
    python tests/list_index_test.py --verbose  # print every check, not only the failures

Built here from the committed public/data/programs/index.json with build.list_index, the function the build calls,
so the checks run on every real row without a full build (tests/seasons_test.py's scratch build runs the writer and
build.validate's LIST checks end to end). Nothing is written under public/; a local serve.py on a loopback port
serves a scratch copy. Offline, under tests/netguard.

Cases:
  shape        24 kept fields, 3 carried changed, the dropped ones gone; #400's 9 recommender fields kept; the
               measured size; the schema (schema/list.schema.json) accepts it.
  derived      rpi, lastSeason and fallAvgHighF equal what they are cut from; season.rpiSeason is the page's
               ranking season and season.finished is the index's.
  complaints   build.list_complaints finds nothing on the real list, and names each thing that can go wrong: a
               dropped key back, a recommender field missing, an unknown field, a changed value, a reorder, a
               different `updated`, a wrong rpiSeason. The schema refuses the same shapes.
  check        build.check_list_index against a scratch output directory: passes, then fails with LIST lines.
  path         list_path() follows a swapped PROGRAMS_OUT_DIR, so a test build never writes the live list.
  compact      common.write_json(compact=True) writes no whitespace and reads back equal.
  serve        serve.py answers /api/v1/list from data/list/index.json and refuses the raw path.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import http.client
import io
import json
import os
import shutil
import sys
import tempfile
import threading
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


INDEX = json.load(open(os.path.join(ROOT, "public", "data", "programs", "index.json"), encoding="utf-8"))
LIST = build.list_index(INDEX)
SCHEMA = json.load(open(os.path.join(ROOT, "schema", "list.schema.json"), encoding="utf-8"))
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


def test_shape():
    print("shape: the fields the plan approved, and nothing else")
    ok("24 kept fields", len(build.LIST_KEEP) == 24, len(build.LIST_KEEP))
    changed = {"rpi", "lastSeason", "fallAvgHighF"}
    row_keys = set(build.LIST_KEEP) | changed
    ok("every row carries exactly the kept and changed fields", all(set(r) == row_keys for r in LIST["programs"]),
       next((sorted(set(r) ^ row_keys) for r in LIST["programs"] if set(r) != row_keys), None))
    eight = {"currentSeason", "headCoach", "coachSince", "sat75", "stale", "failed", "builtAt", "tags"}
    ok("the 8 dropped fields, and the 2 carried changed under a new name, are on no row",
       not any(set(r) & (eight | {"rpiHistory", "fallClimate"}) for r in LIST["programs"]))
    ok("build.LIST_DROPPED names exactly those", set(build.LIST_DROPPED) == eight | {"rpiHistory", "fallClimate"})
    recs = {"slug", "name", "shortName", "division", "conference", "city", "state", "region", "undergradEnrollment"}
    ok("#400's 9 recommender fields are the constant, and kept", set(build.LIST_RECOMMENDER_FIELDS) == recs
       and recs <= set(build.LIST_KEEP))
    ok("the same programs as the index, in its order", [r["slug"] for r in LIST["programs"]] == [r["slug"] for r in INDEX["programs"]])
    raw = json.dumps(LIST, ensure_ascii=False, separators=(",", ":")).encode()
    full = json.dumps(INDEX, ensure_ascii=False, indent=2).encode() + b"\n"
    print(f"    list {len(raw):,} B compact against the index's {len(full):,} B as served ({100 * len(raw) / len(full):.0f}%)")
    ok("well under half the full index's size", len(raw) < 0.45 * len(full), (len(raw), len(full)))
    ok("the schema accepts it", not schema_errors(LIST), schema_errors(LIST)[:3])


def test_derived():
    print("derived: rpi, lastSeason, fallAvgHighF and the season fields")
    season = max(h["year"] for r in INDEX["programs"] for h in (r.get("rpiHistory") or []))
    ok("season.rpiSeason is the newest ranked year in any row (what rpiSeasons() works out)", LIST["season"]["rpiSeason"] == season,
       LIST["season"])
    ok("season.finished is the index's (#249)", LIST["season"]["finished"] == INDEX["season"]["finished"])
    ok("season keeps current, gradYears and rpiFinal, and no _comment", all(k in LIST["season"] for k in ("current", "gradYears", "rpiFinal"))
       and not any(k.startswith("_") for k in LIST["season"]) and not any(
           k.startswith("_") for v in LIST["season"].values() if isinstance(v, dict) for k in v))
    bad = []
    for r, f in zip(LIST["programs"], INDEX["programs"]):
        rank = next((h["rank"] for h in (f.get("rpiHistory") or []) if h["year"] == season), None)
        ls = f.get("lastSeason")
        if r["rpi"] != rank or r["fallAvgHighF"] != (f.get("fallClimate") or {}).get("avgHighF") \
                or r["lastSeason"] != ({k: ls.get(k) for k in ("year", "record", "gamesPlayed")} if ls else None) \
                or any(r[k] != f.get(k) for k in build.LIST_KEEP if k != "completeness") \
                or r["completeness"] != round(f["completeness"], 2):
            bad.append(f["slug"])
    ok("every row's fields equal the index's, or what they are cut from", not bad, bad[:5])
    ok("some rows have an RPI, some do not (the check is not vacuous)", 0 < sum(r["rpi"] is not None for r in LIST["programs"]) < len(LIST["programs"]))


def test_complaints():
    print("complaints: the real list is clean, and each fault is named")
    ok("the real list: no complaints", build.list_complaints(LIST, INDEX) == [], build.list_complaints(LIST, INDEX)[:3])

    def broken(fn):
        doc = copy.deepcopy(LIST)
        fn(doc)
        return doc
    cases = [
        ("a dropped key back", lambda d: d["programs"][0].__setitem__("headCoach", "X"), "dropped field(s) headCoach"),
        ("rpiHistory back", lambda d: d["programs"][1].__setitem__("rpiHistory", []), "dropped field(s) rpiHistory"),
        ("a recommender field missing", lambda d: d["programs"][2].pop("region"), "lacks region"),
        ("an unknown field", lambda d: d["programs"][3].__setitem__("extra", 1), "does not define: extra"),
        ("a changed value", lambda d: d["programs"][4].__setitem__("rpi", 999), "rpi differ"),
        ("a longer lastSeason", lambda d: d["programs"][5].__setitem__("lastSeason", {**(d["programs"][5]["lastSeason"] or {}), "ncaaResult": "x"}),
         "lastSeason differ"),
        ("rows reordered", lambda d: d["programs"].reverse(), "not the index's"),
        ("a row missing", lambda d: d["programs"].pop(), "not the index's"),
        ("another `updated`", lambda d: d.__setitem__("updated", "1999-01-01T00:00:00Z"), "`updated`"),
        ("a wrong rpiSeason", lambda d: d["season"].__setitem__("rpiSeason", 1999), "season.rpiSeason"),
        ("no rpiSeason", lambda d: d["season"].pop("rpiSeason"), "season.rpiSeason"),
        ("no finished", lambda d: d["season"].pop("finished"), "season.finished"),
    ]
    for name, fn, want in cases:
        lines = build.list_complaints(broken(fn), INDEX)
        ok(f"{name}: named", any(want in l for l in lines), lines[:3])
    ok("not a list at all: named", build.list_complaints(None, INDEX) != [] and build.list_complaints([], INDEX) != [])
    for name, fn in [("a dropped key", lambda d: d["programs"][0].__setitem__("headCoach", "X")),
                     ("a missing field", lambda d: d["programs"][0].pop("region")),
                     ("a longer lastSeason", lambda d: d["programs"][0].__setitem__("lastSeason", {"year": 1, "record": "1-0", "gamesPlayed": 1, "x": 1})),
                     ("a _comment in season", lambda d: d["season"].__setitem__("_comment", "x"))]:
        ok(f"schema refuses {name}", schema_errors(broken(fn)) != [])


def test_check():
    print("check: build.check_list_index on a scratch output directory")
    tmp = tempfile.mkdtemp(prefix="list-check-")
    progs = os.path.join(tmp, "programs")
    try:
        with swapped(PROGRAMS_OUT_DIR=progs):
            common.write_json(os.path.join(progs, "index.json"), INDEX)
            common.write_json(build.list_path(), LIST, compact=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                good = build.check_list_index()
            ok("passes on the list the build would write", good, buf.getvalue()[:300])
            doc = copy.deepcopy(LIST)
            doc["programs"][0]["tags"] = []
            common.write_json(build.list_path(), doc, compact=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                bad = build.check_list_index()
            ok("fails, printing LIST lines, on a list with a dropped key", not bad and "LIST: " in buf.getvalue() and "tags" in buf.getvalue(),
               buf.getvalue()[:300])
            os.remove(build.list_path())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                missing = build.check_list_index()
            ok("fails on a missing list", not missing and "LIST: " in buf.getvalue(), buf.getvalue()[:300])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_path():
    print("path: list_path() follows PROGRAMS_OUT_DIR")
    live = os.path.join(common.PUBLIC_DATA_DIR, "list", "index.json")
    ok("live: public/data/list/index.json", os.path.normpath(build.list_path()) == os.path.normpath(live), build.list_path())
    tmp = tempfile.mkdtemp(prefix="list-path-")
    try:
        with swapped(PROGRAMS_OUT_DIR=os.path.join(tmp, "programs")):
            ok("swapped: beside the swapped programs directory", os.path.normpath(build.list_path())
               == os.path.normpath(os.path.join(tmp, "list", "index.json")), build.list_path())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok("outside public/data/programs, so the profile prune can never read it as a slug",
       os.path.dirname(os.path.dirname(build.list_path())) == os.path.dirname(os.path.abspath(common.PROGRAMS_OUT_DIR)))


def test_compact():
    print("compact: common.write_json(compact=True)")
    tmp = tempfile.mkdtemp(prefix="list-compact-")
    try:
        path = os.path.join(tmp, "x", "index.json")
        common.write_json(path, LIST, compact=True)
        b = open(path, "rb").read()
        ok("no indentation or spaces after separators", b.count(b"\n") == 1 and b.endswith(b"\n") and b'": ' not in b and b'", "' not in b)
        ok("reads back equal", json.loads(b) == LIST)
        common.write_json(path, {"a": [1, 2]})
        ok("the default is unchanged: indented", open(path, "rb").read() == b'{\n  "a": [\n    1,\n    2\n  ]\n}\n')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_serve():
    print("serve: serve.py answers /api/v1/list")
    tmp = tempfile.mkdtemp(prefix="list-serve-")
    body = json.dumps(LIST, ensure_ascii=False, separators=(",", ":")).encode()
    os.makedirs(os.path.join(tmp, "data", "list"))
    with open(os.path.join(tmp, "data", "list", "index.json"), "wb") as f:
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
            status, data = get("/api/v1/list")
            ok("200 with the file's bytes", status == 200 and data == body, (status, data[:80]))
            status, data = get("/data/list/index.json")
            ok("the raw path is refused", status == 404, status)
            status, _ = get("/api/v1/programs/list")
            ok("/api/v1/programs/list is still the profile route (no such profile: 404)", status == 404, status)
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
    for case in (test_shape, test_derived, test_complaints, test_check, test_path, test_compact, test_serve):
        case()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
