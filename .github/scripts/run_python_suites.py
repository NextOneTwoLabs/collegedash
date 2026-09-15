#!/usr/bin/env python3
"""Run every Python check suite under tests/, discovered rather than named (issues #63, #81).

    python .github/scripts/run_python_suites.py --min-checks 396

Why this exists
---------------
tests.yml named its Python suites: five steps, each spelling out one command - four of them a
`tests/*_test.py` file, the fifth `tools/camps_check.py --fixtures`, which is still named on
purpose and is discussed below. The Node step next to them had the same shape until it was changed
to discover `tests/**/*.test.mjs`, for exactly the reason that applies here - a second Node suite
would not have run and the workflow would have been green while skipping it.

Naming left the same hole on the Python half, and it was not hypothetical: `main` carried four
`tests/*_test.py` files and the workflow named four, so PR #96's `tests/sidearm_schedule_test.py`
would have been merged, never run, and reported green. That is #63's own failure mode surviving
inside the mechanism built to end it, which is why the fix is discovery rather than a sixth step.

The three assertions, all derived from the tree at run time
-----------------------------------------------------------
Discovery alone is not enough - it only moves the hole. The guards are deliberately not numbers,
because a number that has to be raised by hand whenever a suite is added goes stale silently, in
the direction that still looks green:

  * the discovery glob must match at least one file - "discovered nothing" is a failure, not a pass;
  * every .py file under tests/ that is suite-shaped must be matched by that glob, so a suite
    cannot be added under a filename discovery would step over (`test_sidearm.py`,
    `sidearm_schedule_tests.py`, `sidearm_check.py`);
  * every discovered suite must report at least one check of its own, so a file that is discovered
    but contributes nothing is a failure too.

None of the three needs editing when a suite is added or removed, and none of them assumes a
particular number of suites - which matters while #96 is open, because a guard that assumed four
suites, or five, would have turned `main` red depending only on merge order.

--min-checks stays as a conservative *aggregate* backstop against checks eroding inside an existing
file - the same job it does for the Node step. It is a minimum over the sum, so adding a suite can
only move the total away from it: this file is correct whether #96 merges before or after it.

What is deliberately NOT discovered, and why that is not an oversight
---------------------------------------------------------------------
Discovery is rooted at `tests/` and never reaches `tools/`. Both patterns below begin with
`tests/`, `Path.glob` cannot walk upward out of the directory it is rooted in, and `main()` asserts
every discovered path really is under `tests/` rather than leaving that to be read off the pattern.

That is on purpose. `tools/roster_check.py` and `tools/camps_check.py`'s discovery sweep both read
roster pages from a local HTTP cache (.cache/http) that a fresh checkout - i.e. every CI runner -
does not have. Absent the cache they skip every program and still exit 0: roster_check.py prints
`summary: not-cached 350 (of 350)` and succeeds. That is issue #81, and running them here would
paint a green tick over zero coverage, which is worse than not running them at all because it turns
an absence of testing into a positive signal. If discovery swept `tools/` it would pick both up and
do precisely that. `tools/camps_check.py --fixtures` is a different mode, is genuinely cacheless -
390 real checks against tests/fixtures/camps - and keeps its own named step in tests.yml with its
own floor. When #81 makes "checked nothing" a non-zero outcome inside the tools themselves, the
sweep can be added there too; it does not belong in a `tests/` discovery either way.

Why one step and not one step per suite
----------------------------------------
GitHub Actions cannot generate steps from a glob - a step list is static YAML, and the only way to
get one *unit* per discovered file is a matrix job fed by `fromJSON` from a discovery job. That was
considered and rejected: `fromJSON('[]')` expands to a matrix of zero jobs that **succeeds**, which
would add a fresh always-green path to the workflow whose entire purpose is to remove them, and the
job-scoped Summary table would fragment into one table per suite.

So this is one step that keeps per-suite reporting inside it. Every suite still gets its own banner
in the log, its own `::error::` annotation naming it, and its own row in the run's Summary table
with its own check count and time - the four rows that were there before this change are the four
rows that are there after it. Every discovered suite runs even after an earlier one has failed,
which is what `if: ${{ !cancelled() }}` bought between the old per-suite steps; the run fails at the
end with the full list rather than at the first red suite.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_suite import annotate, make_output_lossless, summarise  # noqa: E402
from run_suite import run_and_check  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = REPO_ROOT / "tests"

# What counts as a Python suite, and where one could hide. DISCOVERY is what gets run; SCOPE is the
# wider net the orphan check sweeps, so a suite named off-pattern is caught rather than quietly
# skipped. Both are rooted at tests/ - see the module docstring on tools/ and issue #81.
DISCOVERY = "tests/**/*_test.py"
SCOPE = ("tests/**/*.py",)

# Suite-shaped, by either of two cheap signals:
#
#   * it prints a check count. Every suite in this repository ends with a line this workflow can
#     parse ("81 of 81 checks passed", "44/44 checks passed"); a file under tests/ that prints one
#     and is not discovered is a suite nothing runs.
#   * "test" or "tests" appears as a word in the filename. That is what catches the realistic near
#     misses - test_sidearm.py, sidearm_schedule_tests.py - including one written before its count
#     line exists. Matched as a word so latest_registry.py is not dragged in by the "test" inside
#     "latest".
#
# Both can also match something that is not a suite - a helper named check_test_data.py, a comment
# quoting the phrase. That direction is deliberate, and is the same trade the Node script makes: a
# false orphan report is a loud, one-line fix, while a missed one is a suite nothing runs. The
# honest limit is that a suite under a name with no "test" in it *and* no count line would slip
# past both - but such a file cannot report a count, so the workflow could not accept it as a suite
# anyway; it would fail here the moment it were renamed into discovery.
PRINTS_A_COUNT = re.compile(r"checks passed", re.I)
TEST_TOKEN = re.compile(r"(?:^|[^a-z])tests?(?:[^a-z]|$)")
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def names_a_test(stem: str) -> bool:
    """True when "test"/"tests" appears as a word in a filename stem, in snake or camel case.

    As a word, not a substring: `latest_registry.py` is not a suite, and reporting it as one every
    run would train the reader to ignore this check, which is worse than the narrower net.
    """
    return bool(TEST_TOKEN.search(CAMEL_BOUNDARY.sub("_", stem).lower()))

STEP_NAME = "python"


def relative(path: Path) -> str:
    """A repo-relative, forward-slashed path, so annotations read the same on both platforms."""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def suite_name(path: Path) -> str:
    """The short name a suite is reported under: tests/the_rank_test.py -> "the-rank".

    Derived from the filename rather than looked up in a table, because a table of names is one
    more list that has to be edited when a suite is added - the thing this script exists to stop
    needing. These are the names the workflow used when the steps were written by hand, so the
    Summary table and the annotations read exactly as they did before.
    """
    stem = path.name[: -len("_test.py")] if path.name.endswith("_test.py") else path.stem
    return stem.replace("_", "-") or path.stem


def discovered_files() -> list[Path]:
    """The suites that will run, resolved and sorted, exactly as the glob matches them."""
    return sorted({p.resolve() for p in REPO_ROOT.glob(DISCOVERY) if p.is_file()})


def orphaned_files(discovered: set[Path]) -> list[Path]:
    """Suite-shaped files under tests/ that the discovery glob does not match."""
    orphans = []
    for pattern in SCOPE:
        for path in REPO_ROOT.glob(pattern):
            resolved = path.resolve()
            if not path.is_file() or resolved in discovered:
                continue
            if names_a_test(path.stem):
                orphans.append(resolved)
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if PRINTS_A_COUNT.search(text):
                orphans.append(resolved)
    return sorted(set(orphans))


def strays(discovered: list[Path]) -> list[Path]:
    """Discovered files that are not under tests/ - the tools/ exclusion, asserted not assumed."""
    out = []
    for path in discovered:
        try:
            path.relative_to(TESTS_ROOT)
        except ValueError:
            out.append(path)
    return out


def main() -> int:
    make_output_lossless()
    parser = argparse.ArgumentParser(
        description="Run every discovered Python check suite and require each one to have run."
    )
    parser.add_argument(
        "--min-checks",
        type=int,
        required=True,
        help="aggregate backstop: fail when the discovered suites report fewer checks in total",
    )
    args = parser.parse_args()
    if args.min_checks < 1:
        print("run_python_suites.py: --min-checks must be at least 1", file=sys.stderr)
        return 2

    files = discovered_files()

    # Orphans are reported before "nothing was discovered", because when the glob matches nothing
    # the interesting fact is almost never that the directory is empty - it is that the suites are
    # right there and the pattern stopped reaching them. Naming those files is the diagnosis; "no
    # files matched" is only the symptom.
    orphans = orphaned_files(set(files))
    if orphans:
        annotate(
            "error",
            STEP_NAME,
            f"{', '.join(relative(p) for p in orphans)} "
            f"{'looks' if len(orphans) == 1 else 'look'} like a check suite but "
            f"{'is' if len(orphans) == 1 else 'are'} not matched by {DISCOVERY}, so "
            f"{'it' if len(orphans) == 1 else 'they'} would never run. Rename to *_test.py, or "
            f"widen DISCOVERY in .github/scripts/run_python_suites.py - do not leave a suite that "
            f"nothing runs.",
        )
        summarise(f"| {STEP_NAME} | FAIL (undiscovered suite) | ? | 0.0s |")
        return 1

    if not files:
        annotate(
            "error",
            STEP_NAME,
            f"{DISCOVERY} matched no files, so no Python suite ran. Discovery finding nothing is a "
            f"failure here, not an empty pass (issue #81).",
        )
        summarise(f"| {STEP_NAME} | FAIL (discovered nothing) | 0 | 0.0s |")
        return 1

    escaped = strays(files)
    if escaped:
        annotate(
            "error",
            STEP_NAME,
            f"{DISCOVERY} matched {', '.join(relative(p) for p in escaped)}, which "
            f"{'is' if len(escaped) == 1 else 'are'} outside tests/. This step runs only what is "
            f"under tests/: tools/roster_check.py and tools/camps_check.py's sweep exit 0 having "
            f"checked nothing without an HTTP cache, which is a runner's state (issue #81), so "
            f"sweeping them in would be a green tick over no coverage.",
        )
        summarise(f"| {STEP_NAME} | FAIL (discovery left tests/) | ? | 0.0s |")
        return 1

    print(f"discovered {len(files)} Python suite(s) via {DISCOVERY}:")
    for path in files:
        print(f"  {relative(path)}")
    print()

    # Every suite runs, including the ones after a failure: one red suite must never hide the state
    # of the others, which is what the old per-suite steps used `if: ${{ !cancelled() }}` for.
    failed: list[str] = []
    total = 0
    for path in files:
        name = suite_name(path)
        shown = f"python {relative(path)}"
        print(f"--- {name} ({relative(path)}) ---")
        # sys.executable, not "python": a wrapper that hands its suites to a different interpreter
        # than the one running it is its own class of surprise. The floor is 1 - the assertion is
        # "this discovered suite reported checks of its own", not a per-suite number to maintain.
        passed, checks = run_and_check(
            name,
            [sys.executable, str(path)],
            1,
            cwd=REPO_ROOT,
            display=shown,
            floor_note=(
                "It was discovered and it ran, but it reported no checks of its own, so it "
                "contributed nothing to this run. A suite that checks nothing must not pass "
                "(issue #81)."
            ),
        )
        total += checks
        if not passed:
            failed.append(name)
        print()

    if failed:
        annotate(
            "error",
            STEP_NAME,
            f"{len(failed)} of {len(files)} discovered Python suite(s) failed: "
            f"{', '.join(failed)}. Each has its own annotation and its own row in the Summary "
            f"table above.",
        )
        return 1

    if total < args.min_checks:
        annotate(
            "error",
            STEP_NAME,
            f"the {len(files)} discovered Python suite(s) passed, but ran {total} checks in total "
            f"where at least {args.min_checks} were expected. Either checks stopped running inside "
            f"a suite (issue #81), or they were removed on purpose - in which case lower "
            f"--min-checks in .github/workflows/tests.yml in the same change. Adding or removing a "
            f"whole suite is not what this number is for; the per-suite assertions above are.",
        )
        summarise(f"| {STEP_NAME} (aggregate) | FAIL (floor {args.min_checks}) | {total} | - |")
        return 1

    plural = "suite" if len(files) == 1 else "suites"
    print(
        f"{STEP_NAME}: {total} checks passed across {len(files)} discovered {plural} "
        f"({', '.join(suite_name(p) for p in files)}); aggregate floor {args.min_checks}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
