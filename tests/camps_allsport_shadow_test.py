"""All-sport page rule by distinct sports, and its report-only shadow (issue #326 item 1, PR A).

    python tests/camps_allsport_shadow_test.py            # offline, made-up pages only
    python tests/camps_allsport_shadow_test.py --verbose

Why this exists
---------------
#293 calls a page_soccer False page all-sport when its text names ONE other sport, and there a row
needs a soccer signal of its own. A coach's soccer-only site that mentions "football" once loses
every row. The proposed rule needs 2+ DISTINCT sports (swim/swimming is one). PR A keeps the live
rule at 1 (ALLSPORT_MIN_SPORTS) and runs the 2+ rule as a shadow in the daily refresh, recording
what pages would gain; PR B flips the constant after a Reviewer checks those rows. The shadow must
decide on the same text as the rule (extract_camps(min_sports=2)), never change published rows,
never touch the shared STATS counter other workers are writing, and never fail a collection.
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import camps  # noqa: E402

URL = "https://www.example-coach.test/camps"
FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:400]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def page(sentence: str, extra: str = "") -> str:
    # made-up camps with no soccer word, no sport heading and no register link: no row soccer signal
    return ("<html><head><title>Lions Elite Camps</title></head><body><main><h1>Lions Elite Camps</h1>"
            f"<p>{sentence}</p><p>Summer Elite Camp - July 10, 2027</p><p>Fall Skills Clinic - October 2, 2027</p>"
            f"{extra}</main></body></html>")


COACH = page("Our coaching staff also played college football.")
TWO = page("Volleyball and softball camps are listed on their own pages.")
SWIM = page("Swim lessons and swimming camps run at the pool.")
SESSION = page("Our coaching staff also played college football.",
               '<div class="session"><div class="session--header"><h3><span class="dates">Jul. 17 - Jul. 17, 2027</span>'
               '<br/><span class="label">Summer Keeper Camp</span></h3></div></div>')


def names(rows):
    return sorted(r["name"] for r in rows)


def run(html, **kw):
    return camps.extract_camps(html, URL, title="Lions Elite Camps", page_soccer=False, **kw)


def test_live_rule_unchanged():
    ok("PR A keeps the live rule at 1 sport", camps.ALLSPORT_MIN_SPORTS == 1, camps.ALLSPORT_MIN_SPORTS)
    ok("today's rule: one 'football' makes the coach page all-sport (rows dropped)", run(COACH) == [], names(run(COACH)))


def test_one_other_sport_keeps_rows_at_2():
    # test 1 - fails if extract_camps ignores min_sports (the shadow would measure nothing)
    got = names(run(COACH, min_sports=2))
    ok("2+ rule: a page naming one other sport once keeps its rows",
       got == ["Fall Skills Clinic", "Summer Elite Camp"], got)


def test_two_sports_still_gate():
    # test 2 - a real all-sport page stays all-sport at 2
    ok("2+ rule: volleyball + softball page still gates rows without a soccer signal", run(TWO, min_sports=2) == [],
       names(run(TWO, min_sports=2)))


def test_canonical_sports():
    # test 3 - 'swim' + 'swimming' is one sport; lower-cased text would count two
    ok("2+ rule: a page naming only 'swim' and 'swimming' is not all-sport",
       names(run(SWIM, min_sports=2)) == ["Fall Skills Clinic", "Summer Elite Camp"], names(run(SWIM, min_sports=2)))
    for text, want in (("swim and swimming", {"swimming"}), ("cheer and cheerleading", {"cheer"}),
                       ("cross country and cross-country", {"cross country"}), ("water polo, water-polo", {"water polo"}),
                       ("thrower and throwers", {"throwers"}), ("pole vault and pole-vault", {"pole vault"}),
                       ("football and golf", {"football", "golf"})):
        got = camps.allsport_sports(text)
        ok(f"allsport_sports({text!r}) == {sorted(want)}", got == want, sorted(got))


def test_shadow_records_without_changing_rows_or_stats():
    # test 4 - the shadow never touches the live rows, records exactly what 2+ adds, and its own
    # extract_camps call leaves STATS alone while another thread's writes still land
    camps._shadow_reset()
    info: dict = {}
    camps.STATS.clear()
    live = run(SESSION, info=info)
    stats_after_live = dict(camps.STATS)
    before = copy.deepcopy(live)
    ok("info carries the page's other sports", info.get("allsportSports") == ["football"], info)
    ok("the live call counted its session page", stats_after_live.get("session_pages") == 1, stats_after_live)
    camps.allsport_shadow("example-college", SESSION, URL, "Lions Elite Camps", live, info)
    ok("shadow leaves the live rows byte-identical", live == before, names(live))
    ok("shadow leaves STATS exactly as the live call left it", dict(camps.STATS) == stats_after_live, dict(camps.STATS))
    rep = camps._SHADOW_REPORT
    added = rep["pages"][0]["added"] if rep["pages"] else []
    ok("shadow records the rows 2+ would add", sorted(n for n, _d in added)
       == ["Fall Skills Clinic", "Summer Elite Camp", "Summer Keeper Camp"], added)
    ok("shadow counts: 1 evaluated, 1 would flip, 0 lost, 0 failures",
       (rep["evaluated"], rep["oneSport"], rep["removed"], rep["failures"]) == (1, 1, 0, 0), rep)
    # another worker's write during a shadow must land (no snapshot/restore, no global mute)
    camps.STATS.clear()
    camps._SHADOW.active = True
    try:
        t = threading.Thread(target=lambda: camps.STATS.__setitem__("session_pages", camps.STATS["session_pages"] + 1))
        t.start()
        t.join()
        camps.STATS["session_pages"] += 1  # this thread is in the shadow: dropped
    finally:
        camps._SHADOW.active = False
    ok("a write from another thread during the shadow is kept; the shadow thread's is dropped",
       camps.STATS["session_pages"] == 1, dict(camps.STATS))
    # a page that is not a one-sport page is evaluated but never re-extracted
    camps._shadow_reset()
    info2: dict = {}
    camps.allsport_shadow("example-two", TWO, URL, "Lions Elite Camps", run(TWO, info=info2), info2)
    ok("two-sport page: evaluated, not a flip, nothing recorded",
       (camps._SHADOW_REPORT["evaluated"], camps._SHADOW_REPORT["oneSport"], camps._SHADOW_REPORT["pages"]) == (1, 0, []),
       camps._SHADOW_REPORT)


def test_shadow_failure_is_counted():
    # test 5 - a shadow that raises is counted and swallowed
    camps._shadow_reset()
    real = camps.extract_camps

    def boom(*a, **kw):
        if kw.get("min_sports") == 2:
            raise RuntimeError("shadow boom")
        return real(*a, **kw)
    camps.extract_camps = boom
    try:
        info: dict = {}
        live = run(COACH, info=info)
        raised = False
        try:
            camps.allsport_shadow("example-college", COACH, URL, "Lions Elite Camps", live, info)
        except Exception:  # noqa: BLE001
            raised = True
    finally:
        camps.extract_camps = real
        camps._SHADOW.active = False
    ok("a failing shadow does not raise", not raised)
    ok("a failing shadow is counted", camps._SHADOW_REPORT["failures"] == 1, camps._SHADOW_REPORT)
    ok("the shadow flag is cleared after a failure", not getattr(camps._SHADOW, "active", False))


def test_summary_format():
    # test 6 - counts first, at most SHADOW_MAX_LINES page lines, no URLs
    camps._shadow_reset()
    for i in range(45):
        info: dict = {}
        camps.allsport_shadow(f"example-{i:02d}", COACH, URL, "Lions Elite Camps", run(COACH, info=info), info)
    lines = camps.allsport_shadow_summary(today="2026-09-24") or []
    ok("summary starts with the counts", lines and lines[0].startswith("camps all-sport shadow (#326")
       and "45 pages evaluated" in lines[0] and "45 would flip" in lines[0] and "+90 rows (90 upcoming)" in lines[0],
       lines[:1])
    ok("summary lists at most 40 pages, then says how many more", len(lines) == 1 + 40 + 1 and "5 more" in lines[-1],
       len(lines))
    ok("summary carries no URL", not any("http" in ln or "www." in ln for ln in lines))
    ok("a page line is slug | sport | +N rows | rows", lines[1].split(" | ")[1:3] == ["football", "+2 rows"], lines[1])
    camps._shadow_reset()
    ok("no summary when nothing was evaluated", camps.allsport_shadow_summary() is None)


def test_summary_goes_to_the_step_summary():
    # the refresh writes the block to GITHUB_STEP_SUMMARY (and the log), never to a repo file
    import tempfile
    import collegedash
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "summary.md")
        old = os.environ.get("GITHUB_STEP_SUMMARY")
        os.environ["GITHUB_STEP_SUMMARY"] = path
        try:
            wrote = collegedash.write_allsport_shadow(
                lambda: ["camps all-sport shadow (#326 ...): counts", "example-01 | golf | +1 rows | X 2027-07-10"])
            quiet = collegedash.write_allsport_shadow(lambda: None)
        finally:
            if old is None:
                os.environ.pop("GITHUB_STEP_SUMMARY", None)
            else:
                os.environ["GITHUB_STEP_SUMMARY"] = old
        text = open(path, encoding="utf-8").read()
    ok("step Summary gets its own block with the counts and the page lines",
       wrote and quiet and text.startswith("## Camps all-sport shadow (#326)") and "counts" in text
       and "example-01 | golf" in text, text[:200])


def test_report_write_never_crashes_the_refresh():
    # Bianque, PR #340: building or writing the report runs before build() and report_refresh(); an
    # error there must be logged and counted, never raised (a raise marks the whole refresh crashed)
    import tempfile
    import collegedash
    before = collegedash.SHADOW_REPORT_FAILURES

    def bad_summary():
        raise ValueError("summary boom")
    raised = []
    with tempfile.TemporaryDirectory() as d:
        old = os.environ.get("GITHUB_STEP_SUMMARY")
        os.environ["GITHUB_STEP_SUMMARY"] = d  # a directory: open(..., "a") raises OSError
        try:
            for fn in (bad_summary, lambda: ["camps all-sport shadow (#326 ...): counts"]):
                try:
                    got = collegedash.write_allsport_shadow(fn)
                    raised.append(("ok", got))
                except Exception as e:  # noqa: BLE001
                    raised.append(("raised", type(e).__name__))
        finally:
            if old is None:
                os.environ.pop("GITHUB_STEP_SUMMARY", None)
            else:
                os.environ["GITHUB_STEP_SUMMARY"] = old
    ok("a failing summary and an unwritable step Summary are both swallowed, returning False",
       raised == [("ok", False), ("ok", False)], raised)
    ok("both failures are counted", collegedash.SHADOW_REPORT_FAILURES - before == 2,
       collegedash.SHADOW_REPORT_FAILURES - before)
    with open(os.path.join(ROOT, "collegedash.py"), encoding="utf-8") as f:
        src = f.read()
    ok("the refresh passes the summary builder itself, so building it is inside the guard",
       "write_allsport_shadow(camps.allsport_shadow_summary)" in src
       and "write_allsport_shadow(camps.allsport_shadow_summary())" not in src)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_live_rule_unchanged, test_one_other_sport_keeps_rows_at_2, test_two_sports_still_gate,
                 test_canonical_sports, test_shadow_records_without_changing_rows_or_stats,
                 test_shadow_failure_is_counted, test_summary_format, test_summary_goes_to_the_step_summary,
                 test_report_write_never_crashes_the_refresh):
        try:
            case()
        except Exception as e:  # noqa: BLE001 - a crash is that case failing, not the run
            ok(f"{case.__name__} ran", False, repr(e))
    camps._shadow_reset()
    print(f"{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
