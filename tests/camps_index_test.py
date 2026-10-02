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

Issue #78 narrows what the index carries: upcoming camps only, each labelled id / youth / unknown so
the site-wide view can show ID camps alone. A youth camp is correct data and is never deleted - it
stays on the profile the program page renders - so the label is a filter for one view, not a
rejection. The index also declares `counts`, because a view that hides rows without saying how many
is how a drifting classifier would never be noticed.

Covers, in order:
  guard       the output-directory hazard, exercised through the function that actually carries it:
              this suite's one build is run by seasons_test.rebuild(), whose swap is what keeps a
              test run out of live data, and every file under public/ is hashed before and after.
              A published output missing from that swap is not a failing test - it is a test run
              that quietly overwrites published data on its way past, and nothing else would catch
              it: no workflow runs these suites (issue #63), so they are run by hand in real
              checkouts and refresh.yml commits whatever it finds with `git add -A`
  classify    classify_camp and camp_counts: the id/youth/unknown vocabulary on real corpus names,
              the precedence rule (an age token beats an ID token, because "make sure only" breaks
              ties towards showing less), 'day camp' as a format rather than an age, and a tally
              that names every class even at zero
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
              validator that dies is not a validator; so is a malformed programs index or profile (#70)
  undated     the build log counts the undated camp items the index leaves out, so a growing number is
              visible instead of silent (#70)
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import gzip
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
# #465 size pins (gzip -9 of the file as build writes it, compact): a fixed allowance plus a per-row rate. The rows
# follow the calendar, and the document has a fixed head (updated, window, counts: ~132 B gzipped with no rows) while
# gzip has little to share across a handful of rows, so a pure per-row pin fails a correct build in an off-season with
# ~20 or fewer camps (Bianque's review of #468). Measured for the PR on 2026-10-02: 7,004 B for 98 rows, of which the
# program blocks are 1,803 B; and on a scratch document, 458 B for one row (71 B of it the block).
CAMPS_GZ_BASE, CAMPS_GZ_PER_ROW = 600, 85
PROGRAM_BLOCK_GZ_BASE, PROGRAM_BLOCK_GZ_PER_ROW = 150, 24


def camps_size_ok(gz: int, rows: int) -> bool:
    return gz <= CAMPS_GZ_BASE + CAMPS_GZ_PER_ROW * rows


def block_size_ok(block_gz: int, rows: int) -> bool:
    return block_gz <= PROGRAM_BLOCK_GZ_BASE + PROGRAM_BLOCK_GZ_PER_ROW * rows

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
    # The owner's rule (#78): "only show upcoming camps, drop the past year." The failing input for
    # this check is any reinstated lower bound - set the old 365 back and `from` moves to 2025-09-14.
    ok("the window opens today: the published index is upcoming-only", w["from"] == "2026-09-14", str(w))
    ok("and declares an explicit, unbounded upper end", "to" in w and w["to"] is None, str(w))
    ok("the window is a rolling one, anchored on the day it is built",
       build.camps_window(dt.date(2026, 1, 1))["from"] == "2026-01-01")
    ok("no past-window constant survives for someone to turn back up",
       not hasattr(build, "CAMPS_PAST_WINDOW_DAYS"),
       "CAMPS_PAST_WINDOW_DAYS is still defined; the upcoming-only rule is one edit from being undone")

    def day(start, end=None, **kw):
        return {"name": "x", "startDate": start, "endDate": end, "precision": "day", **kw}

    cases = [
        ("a camp today is in the window", day("2026-09-14"), True),
        ("a camp that finished yesterday is out: the past year goes", day("2026-09-13"), False),
        ("last season's camp, which the 365-day window used to publish, is out",
         day("2026-06-07"), False),
        ("a camp two seasons out is in, because the window has no upper end", day("2027-08-21"), True),
        ("a multi-day camp that began before today but is still running is in - it has not happened "
         "yet, so 'upcoming' has to include it", day("2026-09-10", "2026-09-20"), True),
        ("a multi-day camp that ended yesterday is out", day("2026-08-01", "2026-09-13"), False),
        ("an undated row is dropped: it cannot be placed in the window",
         {"name": "x", "startDate": None, "dateText": "Camp dates TBD"}, False),
        ("a month-precision row in the current month is in",
         {"name": "x", "startDate": "2026-09", "precision": "month"}, True),
        ("a month-precision row in the month before is out",
         {"name": "x", "startDate": "2026-08", "precision": "month"}, False),
        # A camp is judged by when it finishes, so one still running in the cutoff month stays in.
        # tabCamps in public/index.html uses the same rule since #71
        # (tests/feedback_camps_glance.test.mjs pins it there).
        ("a month-precision row that began before the cutoff month but runs into it is in, as it is "
         "upcoming on the profile tab (#71)",
         {"name": "x", "startDate": "2026-08", "endDate": "2026-09", "precision": "month"}, True),
        ("a month-precision row that had ended before the cutoff month is out, endDate or no endDate",
         {"name": "x", "startDate": "2026-06", "endDate": "2026-07", "precision": "month"}, False),
        ("a row whose startDate is not a string is dropped, not raised on",
         {"name": "x", "startDate": 20260914, "precision": "day"}, False),
        ("a row that is not an object at all is dropped, not raised on", "June 3", False),
        ("a row whose endDate is the wrong type falls back to startDate",
         day("2026-09-14", end=3), True),
    ]
    for name, item, want in cases:
        ok(name, build.camp_in_window(item, w) is want)

    bounded = {"from": "2025-09-14", "to": "2026-12-31"}
    ok("an upper bound is honoured where one is declared, so `to` is never decorative",
       build.camp_in_window(day("2027-08-21"), bounded) is False)
    ok("and a row inside that bound still passes", build.camp_in_window(day("2026-06-03"), bounded) is True)
    ok("a window declaring no bounds excludes nothing, which is exactly why check_camps_index "
       "refuses an index that declares none", build.camp_in_window(day("2020-01-01"), {}) is True)


# ---------- the id / youth classification ----------

def test_classify() -> None:
    """classify_camp and camp_counts. Issue #78.

    Every case is a real name from the corpus, and every one of them changes answer if the rule it
    exercises is removed - which is what keeps this from being a list of things that cannot fail.
    The precedence pair is the point: an age token beats an ID token, because "make sure only" means
    ties break towards showing less.

    The `little` / `junior` block is the exception to "a real name from the corpus", deliberately:
    those two tokens matched ZERO of the 130 stored names and were dropped, and the cases below are
    the input that makes putting them back fail. `little-rock` is a program in this registry with 0
    camp rows today only because the collector has found no page for it, so "Little Rock Fall ID
    Camp" is not a hypothetical - it is what that program's first parsed page will produce.
    """
    print("classify: classify_camp and camp_counts")
    cases = [
        ("Fall ID Camp", "id"),
        ("Elite Prospect ID Camp | November 21st - 22nd", "id"),
        ("Wildcats Fall Elite ID Clinic", "id"),
        ("College ID Camp", "id"),
        ("WOMEN'S SOCCER TO HOLD ID CLINIC", "id"),
        ("2 Day ID Camp", "id"),  # 'Day ID Camp' is not 'day camp'
        ("ELITE DAY CAMP PROGRAM", "id"),  # a day camp is a format, not an age
        ("Youth Camps (Ages 5-12)", "youth"),
        ("Spring Break Kids Camp", "youth"),
        ("Mini Vaqueros Camp", "youth"),
        ("SUMMER GIRLS YOUTH DAY CAMP 1", "youth"),
        ("Half Day Camp", "youth"),
        ("Girls Soccer Day Camp - Session 1", "youth"),
        ("Middle School Elite Skills Camp (grades 6-8)", "youth"),
        # The precedence rule, named. denver's camp says ID twice and is still a youth camp.
        ("2026 DENVER WOMEN'S SOCCER YOUTH ID CAMP", "youth"),
        ("Cal Girls Soccer Camp", "unknown"),
        ("2026 Women's Soccer Camps", "unknown"),
        ("Goalkeeper Camp", "unknown"),
        ("Nike Soccer Camp at Seattle University", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
        # `little` and `junior` dropped from CAMP_AGE_RE: zero hits on the corpus, and each hides a
        # real ID camp. little-rock is a program in this registry.
        ("Little Rock Fall ID Camp", "id"),
        ("UA Little Rock ID Clinic", "id"),
        ("Junior College ID Camp", "id"),
        ("Junior Varsity ID Clinic", "id"),
        ("Bill Smith Jr. Soccer Camp", "unknown"),
        # and the tokens that do earn their place still fire: youth 15 hits, kids 1, mini 1
        ("Little Kickers Youth Camp", "youth"),
    ]
    for name, want in cases:
        got = build.classify_camp(name)
        ok(f"{(name or '')[:52]!r} -> {want}", got == want, f"got {got!r}")

    # #292: stored ages break a tie ONLY when the name says nothing, and (TPM ruling on #296) ages
    # raise a row to 'id' only when the row itself says soccer. Cases 2-3 fail on the pre-#292
    # classifier (fail-first); Cal's fail-first is its extraction fixture (tools/camps_check.py
    # --fixtures), since its new name alone already reads 'id'. The shippensburg / wilmington shapes
    # fail if the soccer requirement is removed. The rest are regression guards.
    age_cases = [
        ("Cal Girls Soccer College ID Camp - Fall", "Age Group 13 - 18", "id"),  # Cal, as now extracted
        ("Summer Soccer Camp", "Ages 6-12", "youth"),
        ("Winter Soccer Clinic", "grades 9-12", "id"),
        # the row does not say soccer: the page did, the row is Field Hockey / Boys Lacrosse (Huatuo)
        ("2026 December Indoor Day Clinic", "grades 9-12", "unknown"),                    # shippensburg
        ("Fall Clinic and Visit Day", "9th - 12th Grade as of Fall 2026", "unknown"),     # wilmington-college-oh
        ("Goalkeeper Camp", "13 - 18 year old", "unknown"),                              # florida-state: no soccer word
        ("Soccer Prospect Day", "grades 9-12", "id"),
        # a SINGLE value is unknown, never youth: "7th Grade" is what GRADES_RE keeps of
        # "7th Grade - 12th Grade". Fails if the single-value rule is removed (it would read youth).
        ("Winter Clinic", "7th Grade", "unknown"),
        ("Winter Clinic", "Age 12", "unknown"),
        # a unitless range classifies only when the age and grade readings agree
        ("Winter Clinic", "9-12", "unknown"),
        ("Winter Soccer Clinic", "13 - 18", "id"),
        ("Goalkeeper Camp", "6th - 12th Grade", "unknown"),  # straddles
        ("Overnight Team Camp", "14 - 19", "unknown"),       # team camps stay out of id
        ("Team Camps", "grades 9-12", "unknown"),
        # the team exclusion beats the name's ID words too (owner ruling on #292); fails if the team
        # check is moved back below CAMP_ID_RE, where 'high school' / 'ID' would win
        ("Girls Soccer High School Team Camp", None, "unknown"),
        ("High School Team Camp", "grades 9-12", "unknown"),
        ("ID Team Camp", None, "unknown"),
        ("Youth Team Camp", None, "youth"),
        ("Youth ID Camp", "13-18", "youth"),                 # the name still wins
        ("Spring ID Camp", "Ages 6-12", "id"),               # ...in both directions
        ("Soccer Camp", None, "unknown"),
    ]
    for name, ages, want in age_cases:
        got = build.classify_camp(name, ages)
        ok(f"{name!r} with ages {ages!r} -> {want}", got == want, f"got {got!r}")

    rows = [{"campType": "id"}, {"campType": "id"}, {"campType": "youth"}, {"campType": "unknown"}]
    ok("camp_counts tallies the rows it is given", build.camp_counts(rows) ==
       {"total": 4, "id": 2, "youth": 1, "unknown": 0 + 1}, str(build.camp_counts(rows)))
    ok("every class is named even at zero, so a class that stopped being produced is visible "
       "rather than a missing key", set(build.camp_counts([])) == {"total", "id", "youth", "unknown"}
       and build.camp_counts([])["youth"] == 0, str(build.camp_counts([])))
    odd = build.camp_counts([{"campType": "prospect"}, {}])
    ok("a campType outside the three classes lands in no bucket, so `total` stops matching the sum "
       "instead of quietly inventing a fourth class nobody reads",
       odd["total"] == 2 and odd["id"] + odd["youth"] + odd["unknown"] == 0, str(odd))


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
    ok("it is an object carrying updated, window, counts and camps",
       isinstance(doc, dict) and {"updated", "window", "counts", "camps"} <= set(doc),
       str(sorted(doc))[:200])
    window = doc["window"]
    ok("the window it declares is the one build would declare today",
       window == build.camps_window(), str(window))

    # Issue #70: an undated item has nowhere to sit in a date-ordered index and is left out by design; the log
    # says how many, counted here independently from the profiles build wrote.
    undated = 0
    for f in os.listdir(progs):
        if f.endswith(".json") and f != "index.json":
            p = json.load(open(os.path.join(progs, f), encoding="utf-8"))
            for it in ((p.get("camps") or {}).get("items") or []):
                if not (isinstance(it, dict) and isinstance(it.get("startDate"), str) and it.get("startDate")):
                    undated += 1
    said = [l for l in log.splitlines() if "build: camps index" in l]
    ok("the build log counts the undated items the index leaves out (#70)",
       len(said) == 1 and f"; {undated} undated item(s) left out" in said[0], (said or ["no camps index line"])[0][-200:])
    rows = doc["camps"]
    ok("it publishes rows at all", isinstance(rows, list) and rows, str(type(rows)))

    allowed = ["slug", *build.CAMP_INDEX_FIELDS, "program"]
    ok("every row carries exactly the declared fields, in the declared order, the program block last (#465)",
       all(list(r) == allowed for r in rows),
       str(sorted({k for r in rows for k in set(r) ^ set(allowed)}))[:300])
    denormalised = {"programName", "collegeName", "region", "conference", "colors", "shortName"}
    ok("nothing else is denormalised onto a row: program fields live only in the declared `program` block",
       not any(denormalised & set(r) for r in rows))

    index = json.load(open(os.path.join(progs, "index.json"), encoding="utf-8"))
    known = {p["slug"] for p in index["programs"]}
    unresolved = sorted({r["slug"] for r in rows} - known)
    ok("every row's slug resolves to a program row in programs/index.json", not unresolved,
       str(unresolved)[:200])
    by_slug = {p["slug"]: p for p in index["programs"]}
    want_fields = ["name", "shortName", "division", "city", "state", "region"]
    ok("#465 the program block is exactly name, shortName, division, city, state, region",
       list(build.CAMP_PROGRAM_FIELDS) == want_fields and all(list(r["program"]) == want_fields for r in rows))
    drift = [(r["slug"], k) for r in rows for k in want_fields if r["program"].get(k) != by_slug[r["slug"]].get(k)]
    ok("#465 every row's program block equals its program's programs/index.json row", not drift, str(drift[:5]))
    ok("#465 every block has a name, so `shortName || name` is never blank",
       all(isinstance(r["program"]["name"], str) and r["program"]["name"] for r in rows))
    try:
        import jsonschema
        schema = json.load(open(os.path.join(ROOT, "schema", "camps.schema.json"), encoding="utf-8"))
        errs = list(jsonschema.Draft202012Validator(schema).iter_errors(doc))
        ok("#465 the built index matches schema/camps.schema.json", not errs, str([e.message for e in errs[:3]])[:300])
    except ImportError:
        ok("jsonschema is installed, so the schema check runs", False)
    # #465 size pin: the camps document is what Home loads for its preview (owner decision D2), so it stays small.
    # Pinned per row so a spring with three times the camps does not fail a correct build: the whole document, and
    # the block's own share, gzipped as published.
    raw = open(path, "rb").read()
    ok("#465 the camps index is written compact, like the slim list (#395)", b"\n  " not in raw and raw.endswith(b"}\n"))
    stripped = json.dumps({**doc, "camps": [{k: v for k, v in r.items() if k != "program"} for r in rows]},
                          ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    gz, gz0 = len(gzip.compress(raw, 9)), len(gzip.compress(stripped, 9))
    ok(f"#465 size: the gzipped camps document is at most {CAMPS_GZ_BASE} + {CAMPS_GZ_PER_ROW} B per row",
       camps_size_ok(gz, len(rows)), f"{gz} B for {len(rows)} rows")
    ok(f"#465 size: the program blocks add at most {PROGRAM_BLOCK_GZ_BASE} + {PROGRAM_BLOCK_GZ_PER_ROW} B per row, gzipped",
       block_size_ok(gz - gz0, len(rows)), f"+{gz - gz0} B for {len(rows)} rows")
    if VERBOSE:
        print(f"       camps index: {len(raw)} B raw, {gz} B gzipped ({gz0} B without the program blocks), {len(rows)} rows")

    items = profile_items(progs)
    expected = [build.camp_row(slug, it, by_slug.get(slug)) for slug, it in items if build.camp_in_window(it, window)]
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
    ok("the dropped set is rows that had finished before the window opened, plus any undated ones",
       all((it.get("endDate") or it.get("startDate") or "") < window["from"] or not it.get("startDate")
           for _, it in dropped),
       str([(s, it.get("startDate")) for s, it in dropped
            if (it.get("endDate") or it.get("startDate") or "") >= window["from"]][:3]))
    # The window is upcoming-only, so this is the check that it actually bit. Its failing input is
    # the old 365-day lower bound: reinstate it and most of the past season comes back.
    ok("the upcoming-only window drops the bulk of the corpus, which is what the owner asked for",
       len(dropped) > len(rows),
       f"{len(rows)} published vs {len(dropped)} dropped - the window is not doing what #78 asked")

    # ---- the classification, on real published rows ----
    ok("every published row carries a campType from the three declared classes",
       all(r.get("campType") in ("id", "youth", "unknown") for r in rows),
       str(sorted({r.get("campType") for r in rows}))[:200])
    ok("each row's campType is what the classifier says about its name, not something the emitter "
       "made up on the way past",
       all(r["campType"] == build.classify_camp(r["name"], r.get("ages")) for r in rows),
       str([(r["slug"], r["name"], r["campType"]) for r in rows
            if r["campType"] != build.classify_camp(r["name"], r.get("ages"))][:3])[:300])
    tally = build.camp_counts(rows)
    ok("the index declares counts, and they are the tally of the rows it published",
       doc["counts"] == tally, f"declared {doc['counts']}, rows tally {tally}")
    ok("so the number the camp view hides is derivable from the file alone",
       doc["counts"]["total"] - doc["counts"]["id"] ==
       sum(1 for r in rows if r["campType"] != "id"))
    # Youth rows are a classification, never a deletion (#78). They must still reach the profile the
    # program page renders. The failing input is any extractor or emitter that starts dropping them.
    youth_items = [(s, it) for s, it in items if build.classify_camp(it.get("name"), it.get("ages")) == "youth"]
    ok("youth camps are still in the profiles the program page renders - classified, not deleted",
       len(youth_items) > 0,
       "no youth camp survives anywhere in the profiles, so this PR deleted data it was told to keep")
    ok("and every profile item carries the label too, not only the published index rows",
       all(it.get("campType") == build.classify_camp(it.get("name"), it.get("ages")) for _s, it in items),
       str([(s, it.get("name"), it.get("campType")) for s, it in items
            if it.get("campType") != build.classify_camp(it.get("name"), it.get("ages"))][:3])[:300])
    if VERBOSE:
        print(f"       {len(items)} items across {len({s for s, _ in items})} programs; "
              f"{len(rows)} published, {len(dropped)} dropped; counts {doc['counts']}; "
              f"{len(youth_items)} youth items kept on profiles; "
              f"{os.path.getsize(path) / 1024:.1f} KB raw")


# ---------- the size pin at small row counts (#465, Bianque's review of #468) ----------

def synthetic_rows(n: int) -> list[dict]:
    """n synthetic published rows of realistic length, each different, as build writes them. Made-up names only."""
    states = ["TX", "OH", "CA", "NC", "PA", "IL", "GA", "NY"]
    out = []
    for i in range(n):
        slug = f"example-college-{i}"
        it = {"name": f"Winter Elite ID Clinic {i} | January {i % 28 + 1}th", "startDate": f"2027-01-{i % 28 + 1:02d}",
              "endDate": f"2027-01-{i % 28 + 1:02d}", "dateText": f"01/{i % 28 + 1:02d}/2027", "precision": "day",
              "yearInferred": i % 17 == 0, "location": None, "ages": "9th - 12th Grade as of Fall 2026" if i % 2 else None,
              "price": f"${150 + i}.00" if i % 3 == 0 else None,
              "registerUrl": f"https://register.example.org/camp.cfm?sport=7&id={340000 + i * 37}",
              "sourceUrl": f"https://www.examplecollege{i}soccercamps.example/", "kind": "camp", "campType": "id",
              "confidence": "heuristic"}
        out.append(build.camp_row(slug, it, {"slug": slug, "name": f"Example College {i}", "shortName": f"Example {i}",
                                             "division": ("D1", "D2", "D3")[i % 3], "city": f"Example City {i}",
                                             "state": states[i % len(states)], "region": "South"}))
    return out


def test_size_small() -> None:
    print("size: the pin holds when camps thin out")
    head = {"updated": "2026-10-02T15:00:00Z", "window": {"from": "2026-10-02", "to": None}}
    for n in (0, 1, 5, 20):
        rows = synthetic_rows(n)
        with_blocks = json.dumps({**head, "counts": build.camp_counts(rows), "camps": rows}, ensure_ascii=False, separators=(",", ":"))
        without = json.dumps({**head, "counts": build.camp_counts(rows), "camps": [{k: v for k, v in r.items() if k != "program"} for r in rows]},
                             ensure_ascii=False, separators=(",", ":"))
        gz, gz0 = len(gzip.compress((with_blocks + "\n").encode(), 9)), len(gzip.compress((without + "\n").encode(), 9))
        # FIX where the pure per-row pins this replaces (85 and 24 B per row) would have failed this correct document
        fix_doc, fix_block = gz > CAMPS_GZ_PER_ROW * n, gz - gz0 > PROGRAM_BLOCK_GZ_PER_ROW * n
        ok(f"{'FIX ' if fix_doc else ''}{n} row(s): the document ({gz} B gzipped) is within the pin", camps_size_ok(gz, n), f"{gz} B")
        ok(f"{'FIX ' if fix_block else ''}{n} row(s): the blocks (+{gz - gz0} B) are within the pin", block_size_ok(gz - gz0, n), f"+{gz - gz0} B")
        if n <= 1:  # the pure per-row pin this replaces would have failed a correct build here
            ok(f"{n} row(s): a pure {CAMPS_GZ_PER_ROW} B-per-row pin would have failed this correct document",
               gz > CAMPS_GZ_PER_ROW * n, f"{gz} B against {CAMPS_GZ_PER_ROW * n}")


# ---------- the invariant ----------

def index_row(slug: str) -> dict:
    """A scratch programs-index row: the slug and the fields a camps row's `program` block copies (#465). Synthetic."""
    return {"slug": slug, "name": f"{slug.title()} University", "shortName": slug.title(), "division": "D1",
            "city": "Example City", "state": "SC", "region": "South"}


def prog(slug: str) -> dict:
    return {k: index_row(slug)[k] for k in build.CAMP_PROGRAM_FIELDS}


GOOD_ROW = {"slug": "clemson", "name": "Spring ID Camp", "startDate": "2026-04-11",
            "endDate": "2026-04-11", "dateText": "April 11, 2026", "precision": "day",
            "yearInferred": False, "location": None, "ages": None, "price": None,
            "registerUrl": None, "sourceUrl": None, "kind": "camp", "campType": "id",
            "confidence": "heuristic", "program": prog("clemson")}
WINDOW = {"from": "2025-09-14", "to": None}


def scratch_tree(tmp: str, *, index_doc, items: dict[str, list[dict]]) -> dict:
    """A scratch published tree: a programs index and one profile per slug carrying `items`, plus
    whatever `index_doc` is (an object, a string to write raw, or None to write no file at all).
    Returns the registry naming those slugs."""
    progs, camps = os.path.join(tmp, "programs"), os.path.join(tmp, "camps")
    os.makedirs(progs, exist_ok=True)
    os.makedirs(camps, exist_ok=True)
    common.write_json(os.path.join(progs, "index.json"),
                      {"programs": [index_row(s) for s in items]})
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


def doc(rows, window=WINDOW, counts=None) -> dict:
    return {"updated": "2026-09-14T00:00:00Z", "window": window,
            "counts": build.camp_counts(rows) if counts is None else counts, "camps": rows}


def item(**kw) -> dict:
    return {k: v for k, v in GOOD_ROW.items() if k not in ("slug", "program")} | kw


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

        # Issue #70: the other two files it opens. A raise here would end the whole validate run.
        for which in ("programs index", "profile"):
            reg = scratch_tree(tmp, index_doc=doc([GOOD_ROW, {**GOOD_ROW, "slug": "duke", "name": "Duke ID", "program": prog("duke")}]),
                               items={"clemson": [item()], "duke": [item(name="Duke ID")]})
            bad = os.path.join(tmp, "programs", "index.json" if which == "programs index" else "duke.json")
            with open(bad, "w", encoding="utf-8") as f:
                f.write('{"programs": [')
            try:
                with swapped(PROGRAMS_OUT_DIR=os.path.join(tmp, "programs"), CAMPS_OUT_DIR=os.path.join(tmp, "camps")):
                    passed, out = captured(build.check_camps_index, reg)
                raised = None
            except Exception as e:  # noqa: BLE001 - the failure this check exists to catch
                passed, out, raised = True, "", f"{type(e).__name__}: {e}"
            ok(f"a malformed {which} is reported by path, not raised (#70)",
               raised is None and not passed and "readable JSON" in out and os.path.basename(bad) in out,
               raised or out[:300])
            if which == "profile":
                ok("and the unreadable profile's published row is not reported a second time as a row no profile "
                   "holds, while the readable profile is still checked",
                   raised is None and "no profile holds" not in out and "does not publish" not in out, raised or out[:400])

        passed, out = check(tmp, index_doc={"updated": "x", "camps": []}, items={"clemson": [item()]})
        ok("an index declaring no window is refused rather than judged against a guess",
           not passed and "window" in out, out[:300])

        passed, out = check(tmp, index_doc=doc([GOOD_ROW], window={"to": None}), items={"clemson": [item()]})
        ok("a window with no `from` is caught: a stale publish would otherwise be invisible",
           not passed and "window.from" in out, out[:300])

        # ---- issue #78: the hidden count, and #69's allow-list hazard ----
        passed, out = check(tmp, index_doc=doc([GOOD_ROW], counts={"total": 9, "id": 9, "youth": 0,
                                                                  "unknown": 0}),
                            items={"clemson": [item()]})
        ok("counts that do not match the rows are caught: the view reports its hidden number from "
           "them, so a stale tally would understate what is hidden",
           not passed and "counts" in out, out[:400])

        passed, out = check(tmp, index_doc={"updated": "x", "window": WINDOW, "camps": [GOOD_ROW]},
                            items={"clemson": [item()]})
        ok("an index declaring no counts at all is caught, so silent exclusion cannot come back",
           not passed and "counts" in out, out[:300])

        passed, out = check(tmp, index_doc=doc([GOOD_ROW]),
                            items={"clemson": [item(sponsorTier="gold")]})
        ok("a per-item field the index publishes on no row is caught by name - the allow-list "
           "hazard #69 filed, which `campType` is the first field to make real",
           not passed and "sponsorTier" in out, out[:400])

        passed, out = check(tmp, index_doc=doc([GOOD_ROW]),
                            items={"clemson": [item(newsTitle="Tigers to host ID camp")]})
        ok("but a field declared as deliberately withheld is not reported, so the guard cannot be "
           "trained to be ignored", passed and not out, out[:400])

        passed, out = check(tmp, index_doc=doc([{**GOOD_ROW, "campType": "youth"}]),
                            items={"clemson": [item()]})
        ok("a campType the profile does not hold is caught like any other drifted field, by name",
           not passed and "campType" in out, out[:400])

        passed, out = check(tmp, index_doc={"updated": "x", "window": WINDOW, "camps": {}},
                            items={"clemson": [item()]})
        ok("a `camps` that is not a list is reported, not iterated",
           not passed and "not a list" in out, out[:300])

        passed, out = check(tmp, index_doc=doc(["June 3"]), items={"clemson": [item()]})
        ok("a row that is not an object is reported, not attribute-accessed",
           not passed and "not an object" in out, out[:300])

        # ---- issue #465: the `program` block, a copy of the program's index row ----
        passed, out = check(tmp, index_doc=doc([{k: v for k, v in GOOD_ROW.items() if k != "program"}]),
                            items={"clemson": [item()]})
        ok("FIX #465 a row without its program block is caught, by name", not passed and "program" in out, out[:300])
        drifted = {**GOOD_ROW, "program": {**prog("clemson"), "division": "D2"}}
        passed, out = check(tmp, index_doc=doc([drifted]), items={"clemson": [item()]})
        ok("FIX #465 a program block that drifted from the program's index row is caught, by field",
           not passed and "program block differs" in out and "division" in out, out[:400])
        for label, block in (("an extra key", {**prog("clemson"), "conference": "ACC"}),
                             ("a missing key", {k: v for k, v in prog("clemson").items() if k != "region"}),
                             ("not an object", "Clemson")):
            passed, out = check(tmp, index_doc=doc([{**GOOD_ROW, "program": block}]), items={"clemson": [item()]})
            ok(f"FIX #465 a program block with {label} is caught", not passed and "program" in out, out[:300])
        reg = scratch_tree(tmp, index_doc=doc([{**GOOD_ROW, "program": {**prog("clemson"), "shortName": None}}]),
                           items={"clemson": [item()]})
        rows_path = os.path.join(tmp, "programs", "index.json")
        common.write_json(rows_path, {"programs": [{**index_row("clemson"), "shortName": None}]})
        with swapped(PROGRAMS_OUT_DIR=os.path.join(tmp, "programs"), CAMPS_OUT_DIR=os.path.join(tmp, "camps")):
            passed, out = captured(build.check_camps_index, reg)
        ok("#465 a program with no shortName passes with its name in the block (the 89-program case, #405)",
           passed and not out, out[:300])

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
    test_classify()
    test_size_small()
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
