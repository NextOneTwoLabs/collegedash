---
name: run-tests
description: Run every check suite the way CI runs it, with the commands and --min-checks floors read from .github/workflows/tests.yml, and get a result that says which Python and Node ran. Use before you call a PR ready, after you merge main into your branch, and when CI is red and you need to reproduce it here.
---

# Run the tests like CI

The commands and the `--min-checks` floors live in `.github/workflows/tests.yml`. This skill never copies them: `ci_tests.py` reads the workflow each time it runs, so when someone raises a floor or adds a step, you get it with no edit here. Do the `setup` skill first, so Python 3.12 and Node 24 are the ones that run.

```
# CD_VENV=<the venv the setup skill reported> in front of each command; leave it out if you used the default location
python3 .claude/skills/run-tests/ci_tests.py --list      # the steps and floors, read from tests.yml; runs nothing
python3 .claude/skills/run-tests/ci_tests.py --logs DIR  # run every step, keep one full log per step in DIR
python3 .claude/skills/run-tests/ci_tests.py --only node # only steps whose name or command contains "node" (repeatable)
```

## Run it in the background

The full Python suites take more than 10 minutes on this machine (CI allows 15). A foreground shell call times out first. Start it with the shell tool's `run_in_background` and a timeout of an hour or more, send the output to a file outside the repository, and read the file when the notice arrives:

```
CD_VENV=<venv> python3 .claude/skills/run-tests/ci_tests.py --logs <scratchpad>/tests > <scratchpad>/tests.out 2>&1
```

Keep `DIR` and the output file in your session scratchpad, never in the worktree. While it runs, do not edit files under `tests/` or `public/`: several suites read the working tree.

For one suite while you work, run the file itself; the full run is for once before you push and again after any merge of main:

```
python tests/<name>_test.py                                           # a Python suite
node --import ./tests/netguard/netguard.mjs --test tests/<name>.test.mjs   # a Node suite, with the network guard CI uses
```

## Reading the result

The run ends with a table (also saved as `summary.txt` in `DIR`) and one line naming what ran:

```
step                                          result    checks  floor    time
<step names come from tests.yml>              PASS         ...    ...     ...s
ran on: Python 3.12.3 (CI 3.12); Node v24.x (CI 24)
```

- `checks` is the count the runner reported. `floor` is CI's `--min-checks` for that step. Paste the table and the `ran on` line into your report; it goes into the PR description. A result that does not say which versions ran is not evidence.
- If `ran on` says `DIFFERS`, the result is not CI's. Say so next to the numbers.
- Exit code: `0` every step passed; `1` something failed; `2` only timing tests failed under load and then passed alone (see below). Anything but `0` needs an explanation in the report.
- Each step is judged separately, as in CI: an early failure does not stop the later steps.

## Known quirks on this machine

Each one is named in the output when it happens. None of them lowers a floor or edits `tests.yml`.

1. **Node older than 24 says "no tests".** Node 22 and 23 write junit without file names, so `run_node_suites.py` reports `reported 0 passing` or `reported no tests`. `ci_tests.py` then runs the same glob and network-guard preload directly with `node --test` and judges that run by its own `# pass` and `# fail` lines and the floor. The note on the row says so. Prefer Node 24 (setup fetches it) and the quirk never appears. By hand: `node --import ./tests/netguard/netguard.mjs --test --test-reporter=tap "tests/**/*.test.mjs"`.
2. **`tests/recs_perf.test.mjs` measures milliseconds and fails when the machine is busy.** It passes in CI. When it is the only thing that failed, `ci_tests.py` reruns it alone: pass alone marks the row `TIMING` (exit 2), not `FAIL`. If it fails alone too, give `--main DIR` a clean checkout of `origin/main` (`git worktree add <scratchpad>/main origin/main`) and the same command is run there; failing on main as well means the machine, not your change. Without `--main` it stays `FAIL`. Do not run other heavy work (a second suite, screenshots) at the same time.
3. **More than 10 minutes.** See "Run it in the background".

## A red test that is not yours

1. Open the log named in the output and find the first `not ok` or `FAIL` line.
2. Run that one file alone, on your branch and in a clean checkout of `origin/main` (the `--main` checkout). Same failure on both: it is on main, not from your change.
3. Do not fix it in an unrelated PR, and do not skip it. Report it to the coordinator with the test name, the line, and the output from main, and say which of your results it affects.

Two things cause most of these, and the shared rules in `CLAUDE.md` forbid both in new tests: an exact count pinned on live published data (a data refresh changes it overnight), and a result that depends on today's date without a controlled clock (#503).

## What to report

The `ran on` line, the table, the names of any failing tests with where they also fail (branch only, or main too), and the log directory path. Say what you did not run. Never write "all tests pass" from a run that was `FAIL`, `TIMING`, or on a different Node or Python than CI's without saying so.
