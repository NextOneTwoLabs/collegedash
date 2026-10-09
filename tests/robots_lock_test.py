"""The robots hook must not deadlock on its own lock when the counters were never reset (issue #419).

    python tests/robots_lock_test.py            # offline; each call runs in a thread with a timeout
    python tests/robots_lock_test.py --verbose

Before the fix, _robots_check and _robots_note_answer took _robots_lock (a plain, non-reentrant Lock) and then, with
the counters empty, called reset_robots_report(), which takes _robots_lock again: the thread blocked on itself,
forever and silently. `refresh` resets the counters before any fetch, so the scheduled runs never reached it; any
other entry point with COLLEGEDASH_ROBOTS set did, on its first request.

Each call below runs in a daemon thread joined with a timeout, so on the old code the check FAILS (the thread is still
blocked) instead of hanging the run. No request is made: the host's robots.txt is seeded.

ROBOTS_LOCK_TEST_ROOT (optional) points the suite at another checkout, so the code from before the fix can be run
through these same checks to show them failing.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading

ROOT = os.environ.get("ROBOTS_LOCK_TEST_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import common  # noqa: E402

HOST = "athletics.example.test"
TIMEOUT = 10.0
FAILS: list[str] = []
TOTAL = 0
VERBOSE = False
BLOCKED: list[bool] = []  # set once a call is left blocked: it holds the lock, so later cases cannot run


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def within_timeout(fn):
    """(finished, result or exception). A call still running after TIMEOUT is left blocked in its daemon thread."""
    box = {}

    def run():
        try:
            box["result"] = fn()
        except BaseException as e:  # noqa: BLE001 - reported, not raised
            box["error"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(TIMEOUT)
    if t.is_alive():
        BLOCKED.append(True)
    return not t.is_alive(), box.get("error", box.get("result"))


def never_reset(mode: str):
    """The state of a process that has not called reset_robots_report(): empty counters, a seeded host."""
    os.environ["COLLEGEDASH_ROBOTS"] = mode
    with common._robots_lock:
        common._robots_counts.clear()
    common.set_robots_txt(HOST, "User-agent: *\nDisallow: /private\n")


def test_check_without_a_reset():
    for mode in ("report", "enforce"):
        never_reset(mode)
        done, got = within_timeout(lambda: common._robots_check(f"https://{HOST}/sports/womens-soccer/roster"))
        ok(f"{mode}: _robots_check returns on a never-reset report (no self-deadlock)", done,
           f"still blocked after {TIMEOUT:.0f}s")
        if not done:
            return  # the lock is held by the blocked thread; nothing after this can run
        ok(f"{mode}: ... and checks the host", got == HOST, got)
        ok(f"{mode}: ... and counts the request", common._robots_counts.get("requests", {}).get(HOST) == 1,
           common._robots_counts.get("requests"))
    never_reset("report")
    done, got = within_timeout(lambda: common._robots_check(f"https://{HOST}/private/x"))
    ok("report: a disallowed path on a never-reset report returns and is counted as a would-block",
       done and common._robots_counts["blocked"].get(HOST) == 1, (done, dict(common._robots_counts.get("blocked", {}))))


def test_note_answer_without_a_reset():
    never_reset("report")
    with common._robots_lock:
        common._robots_state[HOST] = "5xx"  # the hook notes answers only for hosts whose robots.txt failed
    done, _ = within_timeout(lambda: common._robots_note_answer(HOST, 200))
    ok("_robots_note_answer returns on a never-reset report", done, f"still blocked after {TIMEOUT:.0f}s")
    if done:
        ok("... and counts the page as loaded", common._robots_counts["loaded"].get(HOST) == 1,
           dict(common._robots_counts["loaded"]))


def test_diff_without_a_reset():
    """Issue #87: robots_allowed() records the shadow diff, setting the counters up under _robots_lock through
    _reset_counts_locked(), never through reset_robots_report()."""
    never_reset("off")
    common.set_robots_txt(HOST, "User-agent: *\nDisallow: /*.pdf$\n")  # the stdlib comparison allows /a.pdf
    done, got = within_timeout(lambda: common.robots_allowed(f"https://{HOST}/a.pdf"))
    ok("robots_allowed() returns on a never-reset report while recording the shadow diff", done,
       f"still blocked after {TIMEOUT:.0f}s")
    if done:
        ok("... with the RFC verdict, and the difference counted", got is False
           and common._robots_counts.get("diff_blocked", {}).get(HOST) == 1, (got, common._robots_counts.get("diff_blocked")))


def test_reset_still_resets():
    never_reset("report")
    done, _ = within_timeout(lambda: common._robots_check(f"https://{HOST}/a"))
    if not ok("setup: one request counted", done and common._robots_counts["requests"].get(HOST) == 1):
        return
    done, _ = within_timeout(common.reset_robots_report)
    ok("reset_robots_report() returns and empties the counters",
       done and common._robots_counts["requests"] == {} and set(common._robots_counts) ==
       {"requests", "blocked", "by_site", "by_collector", "paths", "loaded", "failed", "resolver_errors",
        "explicit_resolver_errors",
        # the #87 shadow diff's counters, set up by the same _reset_counts_locked()
        "diff_allowed", "diff_blocked", "diff_seen", "diff_paths", "comparison_errors"}, dict(common._robots_counts))
    done, rep = within_timeout(lambda: common.robots_report(elapsed_seconds=1.0, workers=1))
    ok("robots_report() still builds", done and isinstance(rep, dict) and rep.get("mode") == "report", rep)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--case", help="run one case only (each case can show its own deadlock on the old code)")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose
    saved = os.environ.get("COLLEGEDASH_ROBOTS")
    try:
        cases = (test_check_without_a_reset, test_note_answer_without_a_reset, test_diff_without_a_reset,
                 test_reset_still_resets)
        for case in [c for c in cases if not args.case or c.__name__ == args.case]:
            if BLOCKED:
                ok(f"{case.__name__} skipped: an earlier call is still blocked holding the lock", False)
                continue
            try:
                case()
            except Exception as e:  # a case that raises is a failed case, not a lost run
                ok(f"{case.__name__} ran to the end", False, f"{type(e).__name__}: {e}")
    finally:
        if saved is None:
            os.environ.pop("COLLEGEDASH_ROBOTS", None)
        else:
            os.environ["COLLEGEDASH_ROBOTS"] = saved
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0  # a blocked daemon thread does not keep the process alive


if __name__ == "__main__":
    sys.exit(main())
