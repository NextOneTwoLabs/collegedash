#!/usr/bin/env python3
"""Run every Node test suite in the repository, discovered rather than named (issues #63, #81).

    python .github/scripts/run_node_suites.py --min-checks 15

Why this is a script and not one more line in tests.yml
--------------------------------------------------------
tests.yml ran `node --test --test-reporter=tap tests/feedback.test.mjs`: one file, named. A second
Node suite - tests/camps_view.test.mjs, the only automated coverage of the ID Camp View - would not
have run, and the workflow would have been green while skipping the newest and most user-facing
checks in the repository. A green tick over a suite nobody ran is the exact failure #63 exists to
end, so this step has to discover its files instead of listing them.

Discovery on its own is not enough. The guard that protects the other five suites is a
hand-maintained floor, and a floor that has to be raised by hand every time a file is added is the
same trap one level up: it goes stale silently, in the direction that still looks green. So the
guard here is deliberately not a number. Three assertions, all computed from the tree at run time:

  * the discovery glob must match at least one file - "discovered nothing" is a failure, not a pass;
  * every .mjs/.js/.cjs file under tests/ that imports node:test must be matched by that glob, so a
    suite cannot be added under a filename discovery would step over;
  * every matched file must report at least one test in the run's per-file results, so a file that
    is discovered but contributes nothing is a failure too.

None of the three needs editing when a suite is added or removed. --min-checks remains as a
conservative aggregate backstop against erosion inside an existing file - the same job it does for
the Python suites - but it is no longer the thing standing between the repository and a silently
skipped suite, which is the part that had to stop depending on someone remembering.

How the per-file numbers are obtained
-------------------------------------
node --test is given two reporters at once: tap to stdout, so the log reads as it did before and
the count line stays in a format run_suite.py already understands, and junit to a temporary file,
whose <testcase> elements each carry a file="..." attribute. TAP's output is flat - on a green run
it names no files at all - so the junit copy is the only way to prove *which* files ran.

A note on the discovery pattern
-------------------------------
`node --test tests/`, the obvious form, is not used: on Node 24 (Windows, v24.14.0) it treats
`tests` as a module to execute rather than a directory to search, fails with MODULE_NOT_FOUND and
reports one failed test. Handing node the glob instead is unambiguous on every platform, and node
expands it itself, so the behaviour does not depend on the shell.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ElementTree
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_suite import annotate, make_output_lossless, parse_counts, summarise  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

# What counts as a Node suite, and where one could hide. DISCOVERY is what node is handed; SCOPE is
# the wider net the orphan check sweeps, so a test file named off-pattern is caught rather than
# quietly skipped.
DISCOVERY = "tests/**/*.test.mjs"
SCOPE = ("tests/**/*.mjs", "tests/**/*.js", "tests/**/*.cjs")

# A file that registers tests names the built-in runner somewhere, whether by `import ... from`,
# `import(...)` or `require(...)`, so matching the quoted specifier catches all of them. It can also
# match a mention inside a comment; that direction is deliberate - a false orphan report is a loud,
# one-line fix, while a missed one is a suite nothing runs.
IMPORTS_NODE_TEST = re.compile(r"""['"]node:test['"]""")

SUITE_NAME = "node"


def discovered_files() -> list[Path]:
    """The files node will run, resolved and sorted, exactly as the glob matches them."""
    return sorted({p.resolve() for p in REPO_ROOT.glob(DISCOVERY) if p.is_file()})


def orphaned_files(discovered: set[Path]) -> list[Path]:
    """Test files that exist, register tests, and are not matched by the discovery glob."""
    orphans = []
    for pattern in SCOPE:
        for path in REPO_ROOT.glob(pattern):
            resolved = path.resolve()
            if not path.is_file() or resolved in discovered:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if IMPORTS_NODE_TEST.search(text):
                orphans.append(resolved)
    return sorted(set(orphans))


def is_placeholder(case_name: str | None, origin: Path) -> bool:
    """True for node's stand-in entry for a file that registered no tests of its own.

    A file with tests contributes one <testcase> per test. A file with *none* - every test commented
    out, or an `if` that stopped wrapping any - still contributes exactly one, named after the file
    itself ('tests\\hollow.test.mjs'), and node reports it as a pass. Counting that as a real test
    would let an emptied suite read as a suite that ran, which is the whole failure being guarded
    against, so it is matched by name and discarded. Observed on Node 24.14.0, not assumed.
    """
    if not case_name:
        return False
    normalised = case_name.replace("\\", "/")
    return normalised in (origin.as_posix(), relative(origin))


def counts_per_file(junit_path: Path) -> dict[Path, int]:
    """How many real tests each file reported, from the junit reporter's file="..." attributes."""
    per_file: dict[Path, int] = {}
    if not junit_path.exists():
        return per_file
    try:
        root = ElementTree.parse(junit_path).getroot()
    except ElementTree.ParseError:
        return per_file
    for case in root.iter("testcase"):
        origin = case.get("file")
        if not origin:
            continue
        resolved = Path(origin).resolve()
        per_file.setdefault(resolved, 0)
        if not is_placeholder(case.get("name"), resolved):
            per_file[resolved] += 1
    return per_file


def relative(path: Path) -> str:
    """A repo-relative, forward-slashed path, so annotations read the same on both platforms."""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    make_output_lossless()
    parser = argparse.ArgumentParser(
        description="Run every discovered Node test suite and require each one to have run."
    )
    parser.add_argument(
        "--min-checks",
        type=int,
        required=True,
        help="aggregate backstop: fail when the run reports fewer tests than this in total",
    )
    args = parser.parse_args()
    if args.min_checks < 1:
        print("run_node_suites.py: --min-checks must be at least 1", file=sys.stderr)
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
            SUITE_NAME,
            f"{', '.join(relative(p) for p in orphans)} "
            f"{'imports' if len(orphans) == 1 else 'import'} node:test but "
            f"{'is' if len(orphans) == 1 else 'are'} not matched by {DISCOVERY}, so "
            f"{'it' if len(orphans) == 1 else 'they'} would never run. Rename to *.test.mjs, or "
            f"widen DISCOVERY in .github/scripts/run_node_suites.py - do not leave a suite that "
            f"nothing runs.",
        )
        summarise(f"| {SUITE_NAME} | FAIL (undiscovered suite) | ? | 0.0s |")
        return 1

    if not files:
        annotate(
            "error",
            SUITE_NAME,
            f"{DISCOVERY} matched no files, so no Node suite ran. Discovery finding nothing is a "
            f"failure here, not an empty pass (issue #81).",
        )
        summarise(f"| {SUITE_NAME} | FAIL (discovered nothing) | 0 | 0.0s |")
        return 1

    print(f"discovered {len(files)} Node suite(s) via {DISCOVERY}:")
    for path in files:
        print(f"  {relative(path)}")

    with tempfile.TemporaryDirectory() as workspace:
        junit_path = Path(workspace) / "node-junit.xml"
        command = [
            "node",
            "--test",
            # tap to stdout keeps the log and the count line exactly as they were; junit to a file
            # is what makes the per-file assertion below possible.
            "--test-reporter=tap",
            "--test-reporter-destination=stdout",
            "--test-reporter=junit",
            f"--test-reporter-destination={junit_path}",
            DISCOVERY,
        ]

        started = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        captured: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            captured.append(line)
        code = process.wait()
        seconds = time.monotonic() - started
        output = "".join(captured)
        per_file = counts_per_file(junit_path)

    # The authoritative number is the junit sum, not TAP's. TAP counts node's placeholder entry for
    # a file that registered no tests as a pass, so a suite emptied to nothing would raise the TAP
    # total rather than lower it. The TAP line is still required below as evidence node reported at
    # all; it is just not what the floor is measured against.
    counts = parse_counts(output)
    total = sum(per_file.values())
    shown = str(total) if counts else "?"

    if code != 0:
        annotate(
            "error",
            SUITE_NAME,
            f"node --test {DISCOVERY} exited {code} after {seconds:.1f}s (reported {shown} passing "
            f"of {len(files)} file(s)). See this step's log for the failing test.",
        )
        summarise(f"| {SUITE_NAME} | FAIL (exit {code}) | {shown} | {seconds:.1f}s |")
        return 1

    if counts is None:
        annotate(
            "error",
            SUITE_NAME,
            f"node --test {DISCOVERY} exited 0 but printed no TAP count line, so there is no "
            f"evidence it ran anything (issue #81). Expected a '# pass <n>' line.",
        )
        summarise(f"| {SUITE_NAME} | FAIL (no count) | ? | {seconds:.1f}s |")
        return 1

    # The assertion that replaces a hand-maintained floor: discovered is not the same as ran.
    silent = [path for path in files if per_file.get(path, 0) == 0]
    if silent:
        annotate(
            "error",
            SUITE_NAME,
            f"{', '.join(relative(p) for p in silent)} was discovered but reported no tests, so it "
            f"contributed nothing to this green run. A suite that runs nothing must not pass "
            f"(issue #81).",
        )
        summarise(f"| {SUITE_NAME} | FAIL (suite ran nothing) | {shown} | {seconds:.1f}s |")
        return 1

    if total < args.min_checks:
        annotate(
            "error",
            SUITE_NAME,
            f"node --test {DISCOVERY} passed, but ran {total} tests where at least "
            f"{args.min_checks} were expected. Either tests stopped running, or they were removed "
            f"on purpose - in which case lower --min-checks in .github/workflows/tests.yml in the "
            f"same change.",
        )
        summarise(f"| {SUITE_NAME} | FAIL (floor {args.min_checks}) | {shown} | {seconds:.1f}s |")
        return 1

    breakdown = ", ".join(f"{relative(path)} {per_file[path]}" for path in files)
    print(
        f"{SUITE_NAME}: {total} tests passed in {seconds:.1f}s across {len(files)} discovered "
        f"file(s) ({breakdown}); floor {args.min_checks}"
    )
    plural = "file" if len(files) == 1 else "files"
    summarise(
        f"| {SUITE_NAME} ({len(files)} {plural}, discovered) | pass | {total} | {seconds:.1f}s |"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
