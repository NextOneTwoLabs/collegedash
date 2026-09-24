"""Issue #249: the season being played is finished only when the NCAA's final RPI is out.

    python tests/rpi_final_test.py            # offline, small fixtures, no live data
    python tests/rpi_final_test.py --verbose  # print every check, not only the failures

Before this change a program's own schedule decided: once every listed game was played, its 2026 row
lost `inProgress`, lastSeason jumped to 2026 and the page showed "-" in its Record column - from late
October, one program at a time, and flip-flopping when an NCAA tournament game was added. The rule
now is one site-wide switch, for every division: season S is final once a weekly snapshot of S is
dated on or after registry.season.finalRpiThrough[S] (the D1 College Cup final, entered by a person
once a year). Until then every S row is in progress, whatever its schedule says.

Each test below runs on its own, so on a build.py without this change the ones written against the
old API (1, 4, 5, 6) fail by assertion - the bug reproduced - and the rest fail because the API they
test does not exist. The fixture date is FINAL below; it is a fixture, not the real 2026 date (#290).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import build  # noqa: E402
from collect import common  # noqa: E402

CUR = 2026
FINAL = "2026-12-14"          # fixture College Cup final date
DAY_BEFORE = "2026-12-13"
FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f"  [{detail}]" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return cond


def registry(date: str | None = FINAL, cur: int = CUR, extra: dict | None = None) -> dict:
    dates = {} if date is None else {str(CUR): date}
    return {"season": {"current": cur, "gradYears": [2026, 2027, 2028, 2029],
                       "finalRpiThrough": {**dates, **(extra or {})}}}


def table(season: int, through: str, alpha_rank: int = 5) -> dict:
    teams = [{"school": f"Team {i}", "rank": i + 10, "record": "5-5-5"} for i in range(120)]
    teams.insert(0, {"school": "Alpha", "rank": alpha_rank, "record": "15-3-2", "prevRank": 6})
    return {"kind": "weekly", "season": season, "throughGames": through, "teams": teams}


@contextlib.contextmanager
def rpi_dir(snaps: dict[int, list[str]], current: tuple[int, str] | None = None):
    """A scratch public/data/rpi: weekly/<season>/<through>.json for each date, and current.json."""
    tmp = tempfile.mkdtemp(prefix="rpi-final-")
    try:
        for season, dates in snaps.items():
            os.makedirs(os.path.join(tmp, "weekly", str(season)), exist_ok=True)
            for d in dates:
                json.dump(table(season, d), open(os.path.join(tmp, "weekly", str(season), f"{d}.json"), "w", encoding="utf-8"))
        if current:
            json.dump(table(*current), open(os.path.join(tmp, "current.json"), "w", encoding="utf-8"))
        old = common.RPI_OUT_DIR
        common.RPI_OUT_DIR = tmp
        try:
            yield tmp
        finally:
            common.RPI_OUT_DIR = old
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


PROGRAM = {"slug": "alpha", "ids": {"ncaaName": "Alpha"}, "division": "D1"}
WIKI_2025 = {"data": {"seasons": [{"year": 2025, "label": "2025", "record": "12-5-3"}]}}
COMPLETE = {"data": {"schedule": {"season": CUR, "games": [{"result": r} for r in "WWLTWWLW"]}}}


def season(rows: list[dict], year: int) -> dict:
    return next((s for s in rows if s.get("year") == year), {})


def last_season(rows: list[dict]) -> int | None:
    """lastSeason exactly as summary_row publishes it."""
    p = {"slug": "alpha", "name": "Alpha", "seasons": rows, "program": {"headCoach": {}},
         "_build": {"completeness": 1, "stale": [], "builtAt": "x"}}
    return ((build.summary_row(p) or {}).get("lastSeason") or {}).get("year")


# ---------- the tests ----------

def t1_complete_schedule_no_final():
    """The bug: a complete schedule while the NCAA is still posting weekly tables."""
    reg = registry()
    with rpi_dir({2025: ["2025-12-08"], CUR: ["2026-10-19", "2026-10-26"]}, (CUR, "2026-10-26")):
        rows = build.build_seasons(PROGRAM, WIKI_2025, COMPLETE, {}, build.load_rpi_finals(CUR), reg)
    ok("1: complete schedule, no final table: 2026 is still in progress",
       season(rows, CUR).get("inProgress") is True, str(season(rows, CUR)))
    ok("1: and lastSeason stays 2025", last_season(rows) == 2025, str(last_season(rows)))


def t2_final_table():
    reg = registry()
    with rpi_dir({2025: ["2025-12-08"], CUR: ["2026-12-07", FINAL]}, (CUR, FINAL)):
        final = build.rpi_final_state(reg)
        finals = build.load_rpi_finals(CUR, final)
        rows = build.build_seasons(PROGRAM, WIKI_2025, {"data": {"schedule": {"season": CUR, "games": [{"result": "W"}, {}]}}},
                                   {}, finals, reg, final)
        idx = build.index_season(reg, {}, finals, final)
    ok("2: a snapshot through finalRpiThrough makes 2026 final", final == {"season": CUR, "through": FINAL}, str(final))
    ok("2: 2026 is not in progress, even with an unplayed game on the schedule",
       "inProgress" not in season(rows, CUR), str(season(rows, CUR)))
    ok("2: lastSeason is 2026", last_season(rows) == CUR, str(last_season(rows)))
    ok("2: the rank is labelled as the NCAA's final RPI",
       (season(rows, CUR).get("rpi") or {}).get("source") == "NCAA.com final RPI", str(season(rows, CUR).get("rpi")))
    ok("2: index.season.finished is 2026 and rpiFinal names the table",
       (idx.get("finished"), idx.get("rpiFinal")) == (CUR, {"season": CUR, "through": FINAL}), str(idx))


def t3_one_day_earlier():
    """The boundary: >= and not >. A table through the day before the final is not final."""
    reg = registry()
    with rpi_dir({2025: ["2025-12-08"], CUR: [DAY_BEFORE]}, (CUR, DAY_BEFORE)):
        final = build.rpi_final_state(reg)
        finals = build.load_rpi_finals(CUR, final)
        rows = build.build_seasons(PROGRAM, WIKI_2025, COMPLETE, {}, finals, reg, final)
        idx = build.index_season(reg, {}, finals, final)
    ok("3: a snapshot one day before finalRpiThrough is not final", final is None, str(final))
    ok("3: so 2026 stays in progress", season(rows, CUR).get("inProgress") is True, str(season(rows, CUR)))
    ok("3: and index.season is finished 2025, rpiFinal null",
       (idx.get("finished"), idx.get("rpiFinal")) == (2025, None), str(idx))


def t4_wikipedia_only():
    """A 2026 row from Wikipedia alone: no schedule, no ncaaName."""
    reg = registry()
    wiki = {"data": {"seasons": [{"year": CUR, "label": "2026", "record": "9-1-0"},
                                 {"year": 2025, "label": "2025", "record": "12-5-3"}]}}
    prog = {"slug": "beta", "ids": {}, "division": "D1"}
    with rpi_dir({2025: ["2025-12-08"], CUR: ["2026-10-26"]}, (CUR, "2026-10-26")):
        rows = build.build_seasons(prog, wiki, None, {}, build.load_rpi_finals(CUR), reg)
    ok("4: a Wikipedia-only 2026 row is in progress until the final",
       season(rows, CUR).get("inProgress") is True, str(season(rows, CUR)))
    ok("4: and lastSeason stays 2025", last_season(rows) == 2025, str(last_season(rows)))


def t5_d2_complete_schedule():
    """Owner decision 1 (2026-09-24): one site-wide switch, D2 and D3 included."""
    reg = registry()
    prog = {"slug": "gamma", "ids": {}, "division": "D2"}
    hist = {"data": {"schedule": COMPLETE["data"]["schedule"],
                     "scheduleHistory": {"2025": [{"result": "W"}, {"result": "L"}]}}}
    with rpi_dir({2025: ["2025-12-08"], CUR: ["2026-10-26"]}, (CUR, "2026-10-26")):
        rows = build.build_seasons(prog, None, hist, {}, build.load_rpi_finals(CUR), reg)
    ok("5: a D2 program with a complete schedule is in progress until the D1 final",
       season(rows, CUR).get("inProgress") is True, str(season(rows, CUR)))
    ok("5: and its lastSeason stays 2025", last_season(rows) == 2025, str(last_season(rows)))


def t6_next_season_current_json():
    """The 2027 overwrite gap: the NCAA's first 2027 table lands in current.json before anyone moves the
    registry. 2026 must still resolve, from its last snapshot, and 2027 must not be published."""
    with rpi_dir({2025: ["2025-12-08"], CUR: ["2026-12-07", FINAL], 2027: ["2027-09-20"]}, (2027, "2027-09-20")):
        finals = build.load_rpi_finals(CUR)
    ok("6: with a 2027 current.json, 2026 still resolves from its last snapshot",
       (finals.get(CUR) or {}).get("throughGames") == FINAL, str({y: d.get("throughGames") for y, d in finals.items()}))
    ok("6: and no 2027 table is published while the registry says 2026", 2027 not in finals, str(sorted(finals)))


def t7_date_guard():
    for bad in ("2026-11-14", "2027-02-01", "2026-13-01", "Dec 14"):
        try:
            common.final_rpi_dates(registry(bad))
            ok(f"7: finalRpiThrough {bad!r} is refused", False, "accepted")
        except ValueError:
            ok(f"7: finalRpiThrough {bad!r} is refused", True)
    ok("7: the range ends are accepted", common.final_rpi_dates(registry("2026-11-15")) == {CUR: "2026-11-15"}
       and common.final_rpi_dates(registry("2027-01-31")) == {CUR: "2027-01-31"})
    with rpi_dir({CUR: ["2026-11-20"]}):
        try:
            build.rpi_final_state(registry("2027-03-01"))
            ok("7: the build raises on an out-of-range date", False, "no exception")
        except ValueError:
            ok("7: the build raises on an out-of-range date", True)
    with rpi_dir({2025: ["2025-12-08"], CUR: [FINAL, "2026-12-20"]}, (CUR, "2026-12-20")):
        ok("7: with no date entered the season is never final", build.rpi_final_state(registry(None)) is None)
    ok("7: the collector labels a table final by the same rule (informational only)",
       common.is_final_rpi(registry(), CUR, FINAL) and not common.is_final_rpi(registry(), CUR, DAY_BEFORE)
       and not common.is_final_rpi(registry(None), CUR, FINAL))


def t8_warnings():
    with rpi_dir({2025: ["2025-12-08"], CUR: ["2026-12-07"]}, (CUR, "2026-12-07")):
        w = lambda reg, day: build.rpi_final_warnings(reg, dt.date.fromisoformat(day))  # noqa: E731
        ok("8: Jan 16 with no final table warns", any("no final 2026 RPI" in m for m in w(registry(), "2027-01-16")),
           str(w(registry(), "2027-01-16")))
        ok("8: Jan 14 does not", not w(registry(), "2027-01-14"), str(w(registry(), "2027-01-14")))
        ok("8: Oct 1 with no 2026 date warns", any("no 2026 date" in m for m in w(registry(None), "2026-10-01")))
        ok("8: Sep 30 does not", not w(registry(None), "2026-09-30"), str(w(registry(None), "2026-09-30")))
    with rpi_dir({2025: ["2025-12-08"], CUR: ["2026-12-07", FINAL]}, (CUR, FINAL)):
        ok("8: once the final table is seen, no warning", not build.rpi_final_warnings(registry(), dt.date(2027, 1, 20)))
    with rpi_dir({CUR: ["2026-12-07"], 2027: ["2027-09-20"]}, (2027, "2027-09-20")):
        msgs = build.rpi_final_warnings(registry(cur=2027, extra={"2027": "2027-12-13"}), dt.date(2027, 9, 23))
        ok("8: registry moved to 2027 with 2026's last snapshot before its date warns",
           any("2026's last snapshot is through 2026-12-07" in m for m in msgs), str(msgs))


TESTS = [t1_complete_schedule_no_final, t2_final_table, t3_one_day_earlier, t4_wikipedia_only,
         t5_d2_complete_schedule, t6_next_season_current_json, t7_date_guard, t8_warnings]


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for t in TESTS:
        print(t.__name__)
        try:
            t()
        except Exception as e:  # noqa: BLE001 - one test's missing API must not hide the others' assertions
            ok(f"{t.__name__} raised {type(e).__name__}: {e}", False, traceback.format_exc(limit=1).strip()[-200:])
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
