"""Tests for tools/freshness_check.py, the age check behind .github/workflows/freshness.yml (issue #69).

    python tests/freshness_check_test.py            # every case
    python tests/freshness_check_test.py --verbose  # print every check, not only the failures

Offline and clock-free: every case passes `now` in, so no result depends on the day it runs.

What it pins:
  thresholds  ok up to 12h, warn above 12h, fail above 36h, for the publish age and for each collector.
  publish     the programs index `updated` is missing, unparseable, in the future, or old.
  collectors  camps, tds, soccerwire and news are judged by the newest entry with `ok is True` and no
              `skipped` key (a skipped entry is written {"ok": true, "skipped": ...} and collected nothing);
              `ok: false` entries, the top-level keys and rpi.* entries (no `ok`) are ignored.
  build-only  a fresh publish over stale collection (a build_only republish) still fails and names the dataset.
  real-data   the committed refresh-state.json is readable by the reader without raising.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import freshness_check as fc  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False
NOW = dt.datetime(2026, 10, 9, 23, 47, tzinfo=dt.timezone.utc)
COLLECTORS = ("camps", "tds", "soccerwire", "news")


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def ago(hours: float) -> str:
    return (NOW - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def state(hours: float = 5.0, **over) -> dict:
    """A refresh-state with every daily collector collected `hours` ago, plus the non-entry keys the real
    file carries. `over` replaces one collector's entries: name=list of dicts (one program each)."""
    st: dict = {"updated": ago(0.1), "onboardAll": False, "lastRun": {"ok": 1, "at": ago(0.1)},
                "robots": {}, "rpi.current": {"teams": 349, "at": ago(0.1)},
                "rpi.history": {"years": {}, "at": ago(900)}}
    for c in COLLECTORS:
        for i, e in enumerate(over.get(c, [{"ok": True, "at": ago(hours)}])):
            st[f"prog{i}.{c}"] = e
    return st


def run(published, st: dict) -> dict:
    """{dataset: level} for every finding."""
    return {f.dataset: f.level for f in fc.evaluate(published, st, NOW)}


def test_thresholds() -> None:
    print("thresholds")
    ok("WARN_HOURS is 12", fc.WARN_HOURS == 12, str(fc.WARN_HOURS))
    ok("FAIL_HOURS is 36", fc.FAIL_HOURS == 36, str(fc.FAIL_HOURS))
    for hours, want in ((8.2, "ok"), (12.0, "ok"), (12.1, "warn"), (32.2, "warn"), (36.0, "warn"),
                        (36.1, "fail"), (56.0, "fail")):
        got = run(ago(hours), state())
        ok(f"a publish {hours}h old is {want}", got.get("publish") == want, str(got))
        got = run(ago(1), state(hours))
        ok(f"every collector {hours}h old is {want}", all(got.get(c) == want for c in COLLECTORS), str(got))
    got = run(ago(5), state())
    ok("a fresh publish over fresh collectors gives only ok", set(got.values()) == {"ok"}, str(got))


def test_publish() -> None:
    print("publish: the programs index `updated`")
    future = (NOW + dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for label, value in (("missing", None), ("unparseable", "x"), ("a number", 5), ("an empty string", ""),
                         ("in the future", future), ("a date with no time", "2026-10-09")):
        got = run(value, state())
        ok(f"a {label} `updated` fails", got.get("publish") == "fail", str(got))
    soon = (NOW + dt.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ok("an `updated` 30 minutes ahead of the clock is ok (skew, not a fault)", run(soon, state()).get("publish") == "ok",
       str(run(soon, state())))
    ok("and 2h ahead fails", run(future, state()).get("publish") == "fail")


def test_collectors() -> None:
    print("collectors: which entries count")
    # The failure revision 1 missed: a skipped entry is {"ok": true, "skipped": ...}. A camps collector that
    # collected nothing for 40h but is "skipped" every day must not read as fresh.
    st = state(camps=[{"ok": True, "at": ago(40)}, {"ok": True, "skipped": "no camps page", "at": ago(1)}])
    got = run(ago(1), st)
    ok("fresh skipped-only camps entries over a real `ok` 40h old fail", got.get("camps") == "fail", str(got))
    fs = {f.dataset: f for f in fc.evaluate(ago(1), st, NOW)}
    ok("and the finding names camps and the 40h age", "camps" in fs["camps"].message and "40" in fs["camps"].message,
       fs["camps"].message)
    ok("the other collectors are unaffected", all(got.get(c) == "ok" for c in ("tds", "soccerwire", "news")), str(got))

    st = state(news=[{"ok": False, "at": ago(1), "error": "markup change"}, {"ok": True, "at": ago(30)}])
    ok("an `ok: false` entry is ignored, the newest real ok (30h) decides",
       run(ago(1), st).get("news") == "warn", str(run(ago(1), st)))
    st = state(tds=[{"ok": True, "at": ago(30)}, {"ok": True, "at": ago(3)}])
    ok("the newest of several ok entries decides", run(ago(1), st).get("tds") == "ok", str(run(ago(1), st)))
    st = state(soccerwire=[{"ok": False, "at": ago(1)}])
    ok("a collector with no ok entry at all fails", run(ago(1), st).get("soccerwire") == "fail",
       str(run(ago(1), st)))
    st = state()
    del st["prog0.camps"]
    ok("a collector with no entry at all fails", run(ago(1), st).get("camps") == "fail", str(run(ago(1), st)))

    st = state()
    st["updated"] = ago(500)
    st["lastRun"] = {"ok": 5, "at": ago(500)}
    st["rpi.current"] = {"teams": 1, "at": ago(500)}
    st["athletics-only.athletics"] = {"ok": True, "at": ago(500)}
    st["prog0.scorecard"] = {"ok": True, "at": ago(5000)}
    st["weird"] = "text"
    st["weird2"] = None
    got = run(ago(1), st)
    ok("top-level keys, rpi.*, other collectors and non-dict values neither crash the reader nor count",
       all(got.get(c) == "ok" for c in COLLECTORS) and set(got) == {"publish", *COLLECTORS}, str(got))
    got = run(ago(1), state(camps=[{"ok": True, "at": "soon"}, {"ok": True, "at": ago(2)}]))
    ok("an entry with an unparseable `at` is ignored", got.get("camps") == "ok", str(got))

    got = run(ago(1), state(40.0))
    ok("a fresh publish over 40h-old collection (a build_only republish) fails every collector by name",
       all(got.get(c) == "fail" for c in COLLECTORS) and got.get("publish") == "ok", str(got))
    got = run(ago(50), state())
    ok("a stale publish over fresh collection fails publish only",
       got == {"publish": "fail", **{c: "ok" for c in COLLECTORS}}, str(got))


def test_real_data() -> None:
    print("real-data: the committed refresh-state.json")
    with open(os.path.join(ROOT, "public", "archive", "refresh-state.json"), encoding="utf-8") as f:
        real = json.load(f)
    at = dt.datetime.strptime(real["updated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    findings = fc.evaluate(real["updated"], real, at)
    ok("the real file is read without raising and judges the four collectors and the publish",
       {f.dataset for f in findings} == {"publish", *COLLECTORS}, str([f.dataset for f in findings]))
    ok("the real file, judged at its own `updated`, has no fail",
       all(f.level != "fail" for f in findings), str([(f.dataset, f.level, f.message) for f in findings]))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    VERBOSE = ap.parse_args(argv).verbose
    test_thresholds()
    test_publish()
    test_collectors()
    test_real_data()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
