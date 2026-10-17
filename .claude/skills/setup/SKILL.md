---
name: setup
description: Prepare your worktree so local test runs match CI (Python 3.12 venv with requirements installed, Node 24, a working browser). Use once when you start on an issue, before running tests, and whenever a test passes or fails here but not in CI.
---

# Set up a worktree to match CI

CI (`.github/workflows/tests.yml`) runs Python 3.12 and Node 24. This container usually has Python 3.11 and Node 22. A result from different versions is not CI's result: #491 went red because the full Node suite was never run the way CI runs it. Do this once per session, before you run any tests.

```
python3 .claude/skills/setup/setup_env.py             # report what differs from CI (exit 1 if anything does)
python3 .claude/skills/setup/setup_env.py --install   # create the venv, install requirements, fetch Node 24
```

The script reads the Python version, Node version and pip install line from `tests.yml` each time it runs, so nothing in it can go stale. Standard library only, so the system `python3` can run it.

## Python 3.12 venv

- Location: `$CD_VENV`, otherwise `~/.cache/collegedash/venv312`. One venv serves every worktree; it holds no repository files.
- This container may already have one in the session scratchpad. If so, use it instead of building another: `export CD_VENV=<scratchpad>/v312`.
- By hand, when the script cannot:
  ```
  python3.12 -m venv "$CD_VENV"            # or: uv venv --seed --python 3.12 "$CD_VENV"
  "$CD_VENV/bin/python" -m pip install -r requirements.txt -r requirements-registry.txt
  ```
  The install line is copied from the `Install Python dependencies` step of `tests.yml`; if that step changes, follow it.
- A venv made by plain `uv venv` has no pip. Install into it with `uv pip install --python "$CD_VENV/bin/python" -r requirements.txt -r requirements-registry.txt`.
- Run Python through the venv: `"$CD_VENV/bin/python" ...`, or put `"$CD_VENV/bin"` first on `PATH`. Never `pip install` into the system Python.

## Node 24

`tests/feedback.test.mjs` imports `../worker.js`, which is ESM in a `.js` file; Node reads that only through module-syntax detection (unflagged since 22.7), and CI pins 24 to stay off that edge.

1. `--install` fetches Node 24 from npm into `~/.cache/collegedash/node24` (no root, no nvm). `run-tests` finds it there on its own.
2. Or put any other Node 24 first on `PATH`.
3. If only an older Node is available, you can still run the tests, but **say which version ran** in the PR and in your report ("Node 22.22.0, CI uses 24"). A green run on an older Node does not prove CI is green, and a red one may not be real. Known Node 22 behaviour is in the `run-tests` skill.

## Browser (for the `evidence` skill)

The last line of the report checks that Playwright can start Chromium. Playwright resolves from `PLAYWRIGHT_PATH`, then `require('playwright')`, then `/opt/node-tools/node_modules/playwright`; browsers come from `PLAYWRIGHT_BROWSERS_PATH`. If the line says MISSING, the evidence skill cannot take screenshots here: say so on the PR instead of skipping the evidence silently.

## Next

Run the tests with the `run-tests` skill. Do not edit `tests.yml` to suit this machine.
