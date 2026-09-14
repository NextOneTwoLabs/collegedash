"""Regression tests for the published camps index: the window, the emitter, and the invariant.

    python tests/camps_index_test.py            # everything below, offline
    python tests/camps_index_test.py --verbose  # print every check, not only the failures

Offline: reads the committed sources, makes no request, and writes only into temporary directories.
The published-output checks assert on a build run into a scratch directory rather than on the
committed public/data tree, for the same reason tests/seasons_test.py does: the data is rebuilt and
committed by the daily CI refresh and not by the pull request that changes the code.

Issue #65. public/data/camps/index.json is the first published file with no program of its own to
sit on. A row that names a slug nothing resolves, or one that survived a window it should not have,
is invisible on every profile page and only surfaces in the site-wide view as a camp with no school.

Covers, in order:
  guard       the output-directory hazard, exercised through the function that actually carries it:
              this suite's one build is run by seasons_test.rebuild(), whose swap is what keeps a
              test run out of live data, and every file under public/ is hashed before and after.
              A published output missing from that swap is not a failing test - it is a test run
              that quietly overwrites published data on its way past, and nothing else would catch
              it: no workflow runs these suites (issue #63), so they are run by hand in real
              checkouts and refresh.yml commits whatever it finds with `git add -A`
  window      camp_in_window: the cutoff is inclusive, a camp that is running right now is not past,
              month precision compares months on `endDate or startDate` - which is where the rule
              deliberately parts company with tabCamps, and the case is pinned here - undated and
              malformed rows are dropped, and an upper bound is honoured if one is ever declared
  emitter     what build() publishes: the declared shape and nothing denormalised, every slug
              resolving, the row count equal to the windowed items across the profiles, no row
              outside the window, and out-of-window rows genuinely dropped rather than hidden
  invariant   check_camps_index: an unknown slug, a row outside the window, a foreign or missing
              field, a row the profiles do not hold, an item the index does not publish and any
              field of a matched row that drifted from the profile it came from are each caught by
              name - and a missing or malformed index is reported rather than raised, because a
              validator that dies is not a validator
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import build  # noqa: E402
from collect import common  # noqa: E402
# Imported, not copied: seasons_test.rebuild() owns the output-directory swap that keeps a test run
# out of public/, so it is the function the guard below has to exercise. A local copy of it would
# only ever guard itself, and the swap that can actually clobber live data would go unwatched.
import seasons_test  # noqa: E402

LIVE_INDEX = os.path.join(common.PUBLIC_DATA_DIR, "camps", "index.json")

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


@contextlib.contextmanager
def swapped(**dirs):
    """Point common's output directories at scratch copies for the duration of a block."""
    old = {k: getattr(common, k) for k in dirs}
    for k, v in dirs.items():
        setattr(common, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(common, k, v)


def rebuild(tmp: str) -> tuple[str, str, str]:
    """Build the whole site into a scratch directory; return (profiles dir, camps dir, log).

    The build is run by seasons_test.rebuild() rather than by a swap of this module's own, so that
    the one build this suite performs goes through the real swap - the one a future edit can break.
    Drop CAMPS_OUT_DIR from it and two things happen here, both loudly: the guard sees public/
    change, and the emitter checks find no index at the scratch path.
    """
    progs, log = seasons_test.rebuild(tmp)
    return progs, os.path.join(tmp, "camps"), log


def public_state() -> dict[str, str]:
    """A digest of every file under public/, keyed by path: what a test run must leave untouched.

    Hashing the whole published tree rather than the camps index alone states the actual invariant -
    a test build writes to scratch and to nowhere else - so the next output added to build() is
    covered by this guard on the day it is added, without anyone remembering to extend it.
    """
    out = {}
    for root, _dirs, files in os.walk(common.PUBLIC_DIR):
        for f in files:
            path = os.path.join(root, f)
            with open(path, "rb") as fh:
                out[os.path.relpath(path, common.PUBLIC_DIR).replace("\\", "/")] = hashlib.md5(fh.read()).hexdigest()
    return out


def captured(fn, *a, **kw) -> tuple[bool, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        passed = fn(*a, **kw)
    return passed, buf.getvalue().strip()


# ---------- the hazard guard ----------

def test_guard(before: dict[str, str], after: dict[str, str]) -> None:
    print("guard: a build through seasons_test.rebuild() leaves the published tree alone")
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    live = os.path.relpath(LIVE_INDEX, common.PUBLIC_DIR).replace("\\", "/")
    ok("the real public/data/camps/index.json is byte-for-byte what it was before the build",
       live not in changed,
       "the suite wrote to live data - CAMPS_OUT_DIR is missing from seasons_test.rebuild()'s swap")
    ok("and nothing else under public/ was written either, whatever build() gains next",
       not changed, f"{len(changed)} file(s) changed: {changed[:5]}")


# ---------- the window ----------

def test_window() -> None:
    print("window: camps_window and camp_in_window")
    w = build.camps_window(dt.date(2026, 9, 14))
    ok("the window opens 12 months back", w["from"] == "2025-09-14", str(w))
    ok("and declares an explicit, unbounded upper end", "to" in w and w["to"] is None, str(w))
    ok("the window is a rolling one, anchored on the day it is built",
       build.camps_window(dt.date(2026, 1, 1))["from"] == "2025-01-01")

    def day(start, end=None, **kw):
        return {"name": "x", "startDate": start, "endDate": end, "precision": "day", **kw}

    cases = [
        ("a camp on the cutoff day is in the window", day("2025-09-14"), True),
        ("the day before the cutoff is out", day("2025-09-13"), False),
        ("a camp later today is in", day("2026-09-14"), True),
        ("a camp two seasons out is in, because the window has no upper end", day("2027-08-21"), True),
        ("a multi-day camp that began before the cutoff but is still running is in",
         day("2025-09-01", "2025-09-20"), True),
        ("a multi-day camp that ended before the cutoff is out", day("2025-08-01", "2025-08-20"), False),
        ("an undated row is dropped: it cannot be placed in the window",
         {"name": "x", "startDate": None, "dateText": "Camp dates TBD"}, False),
        ("a month-precision row in the cutoff month is in",
         {"name": "x", "startDate": "2025-09", "precision": "month"}, True),
        ("a month-precision row in the month before is out",
         {"name": "x", "startDate": "2025-08", "precision": "month"}, False),
        # The divergence finding 4 named, pinned as deliberate rather than left to be rediscovered:
        # tabCamps in public/index.html calls a month row past on `startDate` alone, so it would
        # call this one past. The emitter judges a camp by when it finishes, so a camp still
        # running in the cutoff month stays in. Aligning the tab is PR 2's job (issue #65).
        ("a month-precision row that began before the cutoff month but runs into it is in, which is "
         "where this rule deliberately parts company with tabCamps",
         {"name": "x", "startDate": "2025-08", "endDate": "2025-09", "precision": "month"}, True),
        ("a month-precision row that had ended before the cutoff month is out, endDate or no endDate",
         {"name": "x", "startDate": "2025-06", "endDate": "2025-07", "precision": "month"}, False),
        ("a row whose startDate is not a string is dropped, not raised on",
         {"name": "x", "startDate": 20260914, "precision": "day"}, False),
        ("a row that is not an object at all is dropped, not raised on", "June 3", False),
        ("a row whose endDate is the wrong type falls back to startDate",
         day("2026-06-03", end=3), True),
    ]
    for name, item, want in cases:
        ok(name, build.camp_in_window(item, w) is want)

    bounded = {"from": "2025-09-14", "to": "2026-12-31"}
    ok("an upper bound is honoured where one is declared, so `to` is never decorative",
       build.camp_in_window(day("2027-08-21"), bounded) is False)
    ok("and a row inside that bound still passes", build.camp_in_window(day("2026-06-03"), bounded) is True)
    ok("a window declaring no bounds excludes nothing, which is exactly why check_camps_index "
       "refuses an index that declares none", build.camp_in_window(day("2020-01-01"), {}) is True)


# ---------- what build publishes ----------

def profile_items(progs: str) -> list[tuple[str, dict]]:
    out = []
    for f in sorted(os.listdir(progs)):
        if not f.endswith(".json") or f == "index.json":
            continue
        p = json.load(open(os.path.join(progs, f), encoding="utf-8"))
        for it in ((p.get("camps") or {}).get("items") or []):
            out.append((p["slug"], it))
    return out


def test_emitter(progs: str, camps_dir: str, log: str) -> None:
    print("emitter: the index build() publishes")
    complaints = "\n".join(l for l in log.splitlines() if l.startswith("CAMPS"))
    ok("the build's own validate pass reports nothing about the camps index", not complaints,
       complaints[:400])

    path = os.path.join(camps_dir, "index.json")
    if not ok("public/data/camps/index.json is published", os.path.isfile(path), path):
        return
    doc = json.load(open(path, encoding="utf-8"))
    ok("it is an object carrying updated, window and camps",
       isinstance(doc, dict) and {"updated", "window", "camps"} <= set(doc), str(sorted(doc))[:200])
    window = doc["window"]
    ok("the window it declares is the one build would declare today",
       window == build.camps_window(), str(window))
    rows = doc["camps"]
    ok("it publishes rows at all", isinstance(rows, list) and rows, str(type(rows)))

    allowed = ["slug", *build.CAMP_INDEX_FIELDS]
    ok("every row carries exactly the declared fields, in the declared order",
       all(list(r) == allowed for r in rows),
       str(sorted({k for r in rows for k in set(r) ^ set(allowed)}))[:300])
    denormalised = {"programName", "collegeName", "region", "conference", "colors", "shortName"}
    ok("nothing is denormalised onto a row; the view joins by slug",
       not any(denormalised & set(r) for r in rows))

    index = json.load(open(os.path.join(progs, "index.json"), encoding="utf-8"))
    known = {p["slug"] for p in index["programs"]}
    unresolved = sorted({r["slug"] for r in rows} - known)
    ok("every row's slug resolves to a program row in programs/index.json", not unresolved,
       str(unresolved)[:200])

    items = profile_items(progs)
    expected = [build.camp_row(slug, it) for slug, it in items if build.camp_in_window(it, window)]
    ok("the published row count is the windowed item count summed over the profiles",
       len(rows) == len(expected), f"published {len(rows)}, profiles hold {len(expected)}")
    key = lambda r: (r["slug"], str(r["startDate"]), str(r["name"]))
    ok("and the rows are those items, one for one",
       sorted(rows, key=key) == sorted(expected, key=key))
    outside = [r for r in rows if not build.camp_in_window(r, window)]
    ok("no published row falls outside the declared window", not outside, str(outside[:2])[:300])

    dropped = [(s, it) for s, it in items if not build.camp_in_window(it, window)]
    ok("out-of-window rows are dropped at build, not published and hidden",
       len(dropped) > 0 and len(rows) == len(items) - len(dropped),
       f"{len(items)} items, {len(dropped)} dropped, {len(rows)} published")
    ok("the dropped set is dated rows older than the window plus any undated ones",
       all((it.get("startDate") or "") < window["from"] or not it.get("startDate") for _, it in dropped),
       str([(s, it.get("startDate")) for s, it in dropped if (it.get("startDate") or "") >= window["from"]][:3]))
    if VERBOSE:
        print(f"       {len(items)} items across {len({s for s, _ in items})} programs; "
              f"{len(rows)} published, {len(dropped)} dropped; "
              f"{os.path.getsize(path) / 1024:.1f} KB raw")


# ---------- the invariant ----------

GOOD_ROW = {"slug": "clemson", "name": "Spring ID Camp", "startDate": "2026-04-11",
            "endDate": "2026-04-11", "dateText": "April 11, 2026", "precision": "day",
            "yearInferred": False, "location": None, "ages": None, "price": None,
            "registerUrl": None, "sourceUrl": None, "kind": "camp", "confidence": "heuristic"}
WINDOW = {"from": "2025-09-14", "to": None}


def scratch_tree(tmp: str, *, index_doc, items: dict[str, list[dict]]) -> dict:
    """A scratch published tree: a programs index and one profile per slug carrying `items`, plus
    whatever `index_doc` is (an object, a string to write raw, or None to write no file at all).
    Returns the registry naming those slugs."""
    progs, camps = os.path.join(tmp, "programs"), os.path.join(tmp, "camps")
    os.makedirs(progs, exist_ok=True)
    os.makedirs(camps, exist_ok=True)
    common.write_json(os.path.join(progs, "index.json"),
                      {"programs": [{"slug": s} for s in items]})
    for slug, its in items.items():
        common.write_json(os.path.join(progs, f"{slug}.json"), {"slug": slug, "camps": {"items": its}})
    path = os.path.join(camps, "index.json")
    if index_doc is None:
        if os.path.exists(path):
            os.remove(path)
    elif isinstance(index_doc, str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(index_doc)
    else:
        common.write_json(path, index_doc)
    return {"programs": [{"slug": s, "onboarded": True} for s in items]}


def check(tmp: str, *, index_doc, items: dict[str, list[dict]]) -> tuple[bool, str]:
    reg = scratch_tree(tmp, index_doc=index_doc, items=items)
    with swapped(PROGRAMS_OUT_DIR=os.path.join(tmp, "programs"), CAMPS_OUT_DIR=os.path.join(tmp, "camps")):
        return captured(build.check_camps_index, reg)


def doc(rows, window=WINDOW) -> dict:
    return {"updated": "2026-09-14T00:00:00Z", "window": window, "camps": rows}


def item(**kw) -> dict:
    return {k: v for k, v in GOOD_ROW.items() if k != "slug"} | kw


def test_invariant() -> None:
    print("invariant: check_camps_index names what is wrong instead of raising")
    tmp = tempfile.mkdtemp(prefix="camps-invariant-")
    try:
        passed, out = check(tmp, index_doc=doc([GOOD_ROW]), items={"clemson": [item()]})
        ok("a consistent index passes", passed and not out, out[:300])

        stray = {**GOOD_ROW, "slug": "not-a-school"}
        passed, out = check(tmp, index_doc=doc([stray]), items={"clemson": [item()]})
        ok("a row naming a slug no program resolves is caught, by slug",
           not passed and "not-a-school" in out, out[:300])

        old = {**GOOD_ROW, "startDate": "2024-06-27", "endDate": "2024-06-27"}
        passed, out = check(tmp, index_doc=doc([old]),
                            items={"clemson": [item(startDate="2024-06-27", endDate="2024-06-27")]})
        ok("a row outside the declared window is caught", not passed and "outside" in out, out[:300])

        passed, out = check(tmp, index_doc=doc([{**GOOD_ROW, "programName": "Clemson"}]),
                            items={"clemson": [item()]})
        ok("a denormalised field nobody declared is caught, by name",
           not passed and "programName" in out, out[:300])

        passed, out = check(tmp, index_doc=doc([{k: v for k, v in GOOD_ROW.items() if k != "ages"}]),
                            items={"clemson": [item()]})
        ok("a row missing a declared field is caught, by name", not passed and "ages" in out, out[:300])

        passed, out = check(tmp, index_doc=doc([GOOD_ROW]),
                            items={"clemson": [item(), item(name="Summer Elite ID Camp", startDate="2026-06-20")]})
        ok("a windowed profile item the index does not publish is caught",
           not passed and "does not publish" in out, out[:400])

        passed, out = check(tmp, index_doc=doc([GOOD_ROW, {**GOOD_ROW, "name": "Ghost Camp"}]),
                            items={"clemson": [item()]})
        ok("a published row no profile holds is caught", not passed and "Ghost Camp" in out, out[:400])

        # Rows are compared whole, not on (slug, startDate, name): the other ten fields are the ones
        # a view renders, and registerUrl and sourceUrl are third-party strings it renders as links.
        passed, out = check(tmp, index_doc=doc([{**GOOD_ROW, "registerUrl": "https://elsewhere.example/pay"}]),
                            items={"clemson": [item(registerUrl="https://clemson.example/camp")]})
        ok("a published registerUrl the profile does not hold is caught, by field name",
           not passed and "registerUrl" in out, out[:400])

        passed, out = check(tmp, index_doc=doc([{**GOOD_ROW, "endDate": "2026-05-11"}]),
                            items={"clemson": [item()]})
        ok("and an endDate quietly extended past the profile's is caught, not waved through on a "
           "matching start date", not passed and "endDate" in out, out[:400])

        passed, out = check(tmp, index_doc=None, items={"clemson": [item()]})
        ok("a missing index is reported, not raised", not passed and "missing" in out.lower(), out[:300])

        passed, out = check(tmp, index_doc="{not json at all", items={"clemson": [item()]})
        ok("a malformed index is reported, not raised", not passed and "readable JSON" in out, out[:300])

        passed, out = check(tmp, index_doc={"updated": "x", "camps": []}, items={"clemson": [item()]})
        ok("an index declaring no window is refused rather than judged against a guess",
           not passed and "window" in out, out[:300])

        passed, out = check(tmp, index_doc=doc([GOOD_ROW], window={"to": None}), items={"clemson": [item()]})
        ok("a window with no `from` is caught: a stale publish would otherwise be invisible",
           not passed and "window.from" in out, out[:300])

        passed, out = check(tmp, index_doc={"updated": "x", "window": WINDOW, "camps": {}},
                            items={"clemson": [item()]})
        ok("a `camps` that is not a list is reported, not iterated",
           not passed and "not a list" in out, out[:300])

        passed, out = check(tmp, index_doc=doc(["June 3"]), items={"clemson": [item()]})
        ok("a row that is not an object is reported, not attribute-accessed",
           not passed and "not an object" in out, out[:300])

        # The published window is the file's own, not today's: an index published yesterday must not
        # fail the morning a row ages out of a window re-derived here.
        yesterday = {"from": "2025-09-13", "to": None}
        passed, out = check(tmp, index_doc=doc([{**GOOD_ROW, "startDate": "2025-09-13",
                                                "endDate": "2025-09-13"}], window=yesterday),
                            items={"clemson": [item(startDate="2025-09-13", endDate="2025-09-13")]})
        ok("an index is judged against the window it declares, not against today's",
           passed and not out, out[:300])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose

    test_window()
    before = public_state()
    tmp = tempfile.mkdtemp(prefix="camps-build-")
    try:
        progs, camps_dir, log = rebuild(tmp)
        test_guard(before, public_state())
        test_emitter(progs, camps_dir, log)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    test_invariant()

    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed"
          + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
