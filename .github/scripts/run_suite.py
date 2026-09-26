#!/usr/bin/env python3
"""Run one check suite for .github/workflows/tests.yml, and refuse to call "checked nothing" a pass.

    python .github/scripts/run_suite.py --name camps-fixtures --min-checks 390 -- python tools/camps_check.py --fixtures

Exit 0 only when the command exited 0 *and* reported at least --min-checks checks. Anything else
is a non-zero exit plus a GitHub `::error::` annotation naming which of the two it was.

`run_and_check` below is the whole of that logic as one function. The workflow calls this file
directly for the one suite it still names on purpose (`tools/camps_check.py --fixtures`, which is
not under tests/ and is not discoverable); `run_python_suites.py` imports `run_and_check` and calls
it once per discovered suite, so a discovered suite is judged by exactly the same rules - same
output formats, same annotations, same Summary row - as a named one.

Why this wrapper exists rather than the bare command in the workflow
--------------------------------------------------------------------
Issue #81. Two of this repository's check tools exit 0 having checked nothing when the local HTTP
cache is absent, which is exactly a CI runner's state: `tools/roster_check.py` reports
`not-cached 350 (of 350)` and exits 0. Six always-passing checks have shipped or been caught on
this project in a single week. So the exit code on its own is not evidence that anything ran, and
a workflow that treats it as evidence converts an absence of testing into a positive signal -
worse than not running the suite at all.

The floor closes that. Each suite prints how many checks it ran; this asserts the number is at
least the floor it was given. A suite that silently stops running half its checks - the way 79 of
120 fixture checks were unreachable in PR #68's predecessor - goes red here instead of green.
Adding checks raises the count and keeps passing; removing them deliberately means editing the
floor, which is a visible, reviewable act rather than a silent drift.

For the one suite the workflow still names, that floor is the count it reported when the step was
written. For a discovered suite it is 1, and the erosion guard moves to an aggregate floor over all
of them: a per-suite number keyed to a filename would be a list to maintain, and a list to maintain
is the thing discovery exists to stop needing.

It also forces UTF-8 on the child (issue #77): `tools/camps_check.py` prints scraped camp names,
and on a non-UTF-8 locale that raises UnicodeEncodeError partway through - a check tool that
aborts partway reports success for everything it never reached. ubuntu-latest is UTF-8 today; this
makes the suite independent of that staying true.

Output formats understood
-------------------------
Three, because the suites were written separately and do not agree:

    "81 of 81 checks passed"    tests/seasons_test.py, the_rank_test.py, camps_index_test.py,
                                tools/camps_check.py --fixtures
    "44/44 checks passed"       tests/robots_ua_test.py
    "# pass 15"                 node --test --test-reporter=tap

A suite whose output matches none of them is a failure here, not a pass: an unparsed count is
indistinguishable from no count, and guessing in that direction is the whole bug this guards.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time

REPO_ROOT_FOR_GUARD = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUARD_DIR = os.path.join(REPO_ROOT_FOR_GUARD, "tests", "netguard")
DEAD_PROXY = "http://127.0.0.1:9"


def guarded_env(base: dict | None = None) -> dict:
    """The environment every suite runs in (issue #345): tests/netguard on PYTHONPATH, so each Python child imports
    the network guard as `sitecustomize` (refuses non-loopback DNS and connections, exits 97 if anything was
    attempted), and a dead proxy, so a request that bypassed the guard would still go nowhere. NO_PROXY keeps
    requests to the suites' own loopback test servers direct. Node suites get the guard by --import instead
    (run_node_suites.py); the variables do no harm there. Set by the runners, so local runs match CI."""
    env = dict(os.environ if base is None else base)
    env["PYTHONPATH"] = GUARD_DIR + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        env[key] = DEAD_PROXY
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost,::1"
    return env


# Ordered by specificity. Each yields (passed, total); the TAP form has no separate total, so the
# pass count stands as both and `# fail N` is left to the exit code, which node already sets.
COUNT_PATTERNS = (
    re.compile(r"^\s*(\d+)\s+of\s+(\d+)\s+checks passed\s*$", re.M),
    re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s+checks passed\s*$", re.M),
    re.compile(r"^#\s*pass\s+(\d+)\s*$", re.M),
)


def make_output_lossless() -> None:
    """Never let re-printing a suite's output be the thing that fails the step.

    The child is forced to UTF-8 below, but this process inherits the console's encoding, and on a
    cp1252 console `sys.stdout.write` of a scraped camp name raises UnicodeEncodeError - the wrapper
    dying on the same class of bug it exists to survive (issue #77). Observed, not theoretical:
    tools/camps_check.py prints 'ORU Winter College Men�s ID Camp I'. Escaping rather than
    re-encoding, so a UTF-8 runner still shows the real characters and a cp1252 console shows an
    escape instead of mojibake.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


def parse_counts(text: str) -> tuple[int, int] | None:
    """The last count line in `text`, as (passed, total), or None if there is no count line."""
    best: tuple[int, tuple[int, int]] | None = None
    for pattern in COUNT_PATTERNS:
        for match in pattern.finditer(text):
            groups = match.groups()
            passed = int(groups[0])
            total = int(groups[1]) if len(groups) > 1 else passed
            if best is None or match.end() > best[0]:
                best = (match.end(), (passed, total))
    return best[1] if best else None


def annotate(level: str, name: str, message: str) -> None:
    """A GitHub annotation, and the same text on stdout so a local run reads the same."""
    print(f"::{level} title=tests: {name}::{message}")


def summarise(row: str) -> None:
    """Append one row to the run's Summary tab, when there is one to append to."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(row + "\n")


DEFAULT_FLOOR_NOTE = (
    "Either checks stopped running (issue #81: a suite that checks nothing must not be green), or "
    "they were removed on purpose - in which case lower the floor in "
    ".github/workflows/tests.yml in the same change."
)


def run_and_check(
    name: str,
    command: list[str],
    min_checks: int,
    *,
    cwd: str | os.PathLike[str] | None = None,
    display: str | None = None,
    floor_note: str = DEFAULT_FLOOR_NOTE,
) -> tuple[bool, int]:
    """Run one suite, re-print its output, annotate and summarise it. Returns (passed, checks).

    `display` is how the command is named in annotations, so a caller that has to invoke
    `sys.executable` can still print `python tests/seasons_test.py` rather than a 60-character
    interpreter path. `floor_note` is the advice appended when the check count is under the floor:
    the default tells the reader to edit the floor in the workflow, which is right for a suite the
    workflow names and wrong for one it discovers, where there is no per-suite floor to edit.
    """
    shown_command = display if display is not None else " ".join(command)

    # PYTHONUTF8 covers the child's own file reads, PYTHONIOENCODING its stdout; neither affects
    # node, which is UTF-8 unconditionally. Both are set for every child rather than only the
    # python ones, so adding a suite here cannot forget it.
    env = dict(guarded_env(), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")

    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
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

    counts = parse_counts(output)
    shown = f"{counts[0]}/{counts[1]}" if counts else "?"

    if code != 0:
        annotate(
            "error",
            name,
            f"{shown_command} exited {code} after {seconds:.1f}s "
            f"(reported {shown} checks). See this step's log for the failing check.",
        )
        summarise(f"| {name} | FAIL (exit {code}) | {shown} | {seconds:.1f}s |")
        return False, counts[1] if counts else 0

    if counts is None:
        annotate(
            "error",
            name,
            f"{shown_command} exited 0 but printed no check count, so there is no evidence it "
            f"checked anything (issue #81). Expected a line like '<n> of <n> checks passed', "
            f"'<n>/<n> checks passed' or '# pass <n>'.",
        )
        summarise(f"| {name} | FAIL (no count) | ? | {seconds:.1f}s |")
        return False, 0

    passed, total = counts
    if passed != total:
        annotate(
            "error",
            name,
            f"{shown_command} exited 0 but reported {passed} of {total} checks passed. "
            f"The suite is not failing the way it should; treat the exit code as unreliable.",
        )
        summarise(f"| {name} | FAIL ({passed}/{total}) | {shown} | {seconds:.1f}s |")
        return False, total

    if total < min_checks:
        annotate(
            "error",
            name,
            f"{shown_command} passed, but ran {total} checks where at least {min_checks} "
            f"were expected. {floor_note}",
        )
        summarise(f"| {name} | FAIL (floor {min_checks}) | {shown} | {seconds:.1f}s |")
        return False, total

    print(f"{name}: {total} checks passed in {seconds:.1f}s (floor {min_checks})")
    summarise(f"| {name} | pass | {total} | {seconds:.1f}s |")
    return True, total


def main() -> int:
    make_output_lossless()
    parser = argparse.ArgumentParser(
        description="Run one check suite and require it to report a real number of checks."
    )
    parser.add_argument("--name", required=True, help="short suite name used in annotations")
    parser.add_argument(
        "--min-checks",
        type=int,
        required=True,
        help="fail when the suite reports fewer checks than this (0 is rejected: the point is a floor)",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- then the command to run")
    args = parser.parse_args()

    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        print("run_suite.py: no command given after --", file=sys.stderr)
        return 2
    if args.min_checks < 1:
        print("run_suite.py: --min-checks must be at least 1", file=sys.stderr)
        return 2

    passed, _ = run_and_check(args.name, command, args.min_checks)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
