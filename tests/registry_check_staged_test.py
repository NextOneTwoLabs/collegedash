"""Regression tests for tools/registry_check.py's --staged mode and the whole-registry
duplicate-unit-id detection it relies on (issue #140).

    python tests/registry_check_staged_test.py            # every case
    python tests/registry_check_staged_test.py --verbose  # print every check, not only failures

Offline and fully synthetic: the registries here are built in memory and written only to a
temporary file this process creates and removes, never to public/data/registry.json. Every slug
is invented and has no programs/<slug>/sources/ directory on disk, so registry_check.check() finds
no Scorecard source for any of them - which is deliberately the point for the ones marked
`onboarded: False` (that is "not-collected", not a finding) and deliberately a real finding
("no-scorecard-source") for the one below marked `onboarded: True` with nothing collected for it.

Each case runs tools/registry_check.py's own main() in-process, via a REGISTRY_PATH swapped for a
temp file (and always restored, even on error) - the real CLI path, not a reimplementation of it.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import common  # noqa: E402
import tools.registry_check as registry_check  # noqa: E402

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


def prog(slug: str, org: int, division: str, state: str, *, unit_id: int | None = None,
         onboarded: bool = True, conference: str = "Conf") -> dict:
    return {"slug": slug, "onboarded": onboarded, "name": slug.title(), "division": division,
            "conference": conference, "ids": {"ncaaOrgId": org, "scorecardUnitId": unit_id},
            "location": {"city": "X", "state": state}}


def registry(programs: list[dict], staged: list[str] | None = None,
             onboarded_divs=("D1",)) -> dict:
    return {"onboardedDivisions": list(onboarded_divs), "stagedDivisions": staged or [],
            "programs": programs, "heldPrograms": []}


def run_main(reg: dict, *args: str) -> tuple[int, str]:
    """Point collect.common.REGISTRY_PATH at a fresh temp file holding `reg`, run
    tools/registry_check.py's own main() against it, and return (exit code, combined output).
    REGISTRY_PATH is restored and the temp file removed even if main() raises."""
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(reg, f)
        saved = common.REGISTRY_PATH
        common.REGISTRY_PATH = path
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = registry_check.main(list(args))
        finally:
            common.REGISTRY_PATH = saved
        return rc, buf.getvalue()
    finally:
        os.remove(path)


def test_staged_selection() -> None:
    print("staged: --staged selects every staged-division entry, onboarded or not")
    reg = registry([
        prog("d1-a", 1, "D1", "TX", unit_id=901, onboarded=True),
        prog("d2-uncollected-1", 2, "D2", "OH", unit_id=902, onboarded=False),
        prog("d2-uncollected-2", 3, "D2", "PA", unit_id=903, onboarded=False),
    ], staged=["D2"])
    rc, out = run_main(reg, "--staged", "--max-suspects", "0")
    # fails if an uncollected staged entry is treated as a suspect for lacking a source it was never
    # going to have yet - "not-collected" must not count against --max-suspects
    ok("exit 0: two uncollected staged entries are not-collected, not suspects", rc == 0, out)
    ok("both uncollected staged entries are reported not-collected",
       "not-collected 2" in out, out)
    # fails if --staged pulls in a published D1 program instead of only the staged division
    ok("the D1 program is not part of the --staged population", "d1-a" not in out, out)


def test_collected_staged_entry_needs_a_source() -> None:
    print("staged: a COLLECTED staged entry with no source is a real suspect, not not-collected")
    reg = registry([
        prog("d2-collected", 2, "D2", "OH", unit_id=902, onboarded=True),
    ], staged=["D2"])
    rc, out = run_main(reg, "--staged", "--max-suspects", "0")
    # fails if "onboarded: true" and "onboarded: false" staged entries are both waved through as
    # not-collected - once a batch is collected (issue #94 option A), a missing source is exactly
    # as wrong as it would be for a published program
    ok("exit 1: a collected staged entry with no source is a suspect", rc == 1, out)
    ok("classed no-scorecard-source, not not-collected", "no-scorecard-source" in out and "not-collected" not in out, out)


def test_empty_staged_population_fails() -> None:
    print("staged: an empty staged population is a failure, not a quiet pass (issue #140)")
    reg = registry([prog("d1-a", 1, "D1", "TX", unit_id=901)], staged=[])
    rc, out = run_main(reg, "--staged", "--max-suspects", "0")
    # fails if --staged exits 0 (or exits non-zero without saying why) when nothing is staged -
    # this is the exact defect class issue #140 exists to end
    ok("exit 1 when the staged population is empty", rc == 1, out)
    ok("says why, by name", "no staged entries found" in out, out)


def test_duplicate_across_populations() -> None:
    print("duplicates: a scorecardUnitId collision is caught across staged and published together")
    reg = registry([
        prog("d1-a", 1, "D1", "TX", unit_id=555, onboarded=True),
        prog("d2-a", 2, "D2", "PA", unit_id=555, onboarded=False),
    ], staged=["D2"])
    rc, out = run_main(reg, "--staged", "--max-suspects", "0")
    # fails if duplicate-unit-id is computed only over the population being reported on (the old
    # behaviour: `everyone` was always the onboarded set), which would never see the D1 side of a
    # collision from a --staged run
    ok("a --staged run catches a collision with a published (D1) program",
       rc == 1 and "duplicate-unit-id" in out and "d1-a" in out, out)
    rc2, out2 = run_main(reg, "--max-suspects", "0")  # default (onboarded) population
    # fails if the default run's own duplicate detection stops seeing a collision once the other
    # side of the pair is a staged (unselected) entry
    ok("and the default run catches the same collision from its side",
       rc2 == 1 and "duplicate-unit-id" in out2, out2)


def test_default_mode_excludes_uncollected_staged() -> None:
    print("default: an uncollected staged entry never reaches the default (onboarded) population")
    reg = registry([
        prog("d1-a", 1, "D1", "TX", unit_id=901, onboarded=True),
        prog("d2-uncollected", 2, "D2", "OH", unit_id=902, onboarded=False),
    ], staged=["D2"])
    rc, out = run_main(reg, "--max-suspects", "0")
    # fails if --staged's widening of duplicate detection to the whole registry leaked into
    # widening which programs the default run reports on
    ok("the uncollected D2 entry is absent from the default run's own report",
       "d2-uncollected" not in out, out)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    VERBOSE = ap.parse_args(argv).verbose
    test_staged_selection()
    test_collected_staged_entry_needs_a_source()
    test_empty_staged_population_fails()
    test_duplicate_across_populations()
    test_default_mode_excludes_uncollected_staged()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
