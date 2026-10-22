# Plan: #90, a renamed or removed build() output must not lose a gated run's collection

Issue #90 and its 2026-10-01 triage comment; gate from #82; `.github/workflows/refresh.yml`, step "Commit changed
data", `publish_sources_only` (main 60bc94e17, lines 298-342). Author: Jueying. Status: for plan review.

## The failure today
- **What the gate does.** On a gate (build or validate fails after the rebase), the step puts what build() writes
  back to `FETCH_HEAD` (main as the rebase found it) and pushes the run's collection to `refresh-sources/*`.
- **Tolerant restores.** The two review reports and `trends/`, `list/` and `fit/index.json` are restored one at a
  time (`git checkout FETCH_HEAD -- p 2>/dev/null || rm -f p`).
- **The strict checkout.** `public/data/programs`, `commitments/index.json` and `camps/index.json` are one checkout
  with no fallback (line 318). If main no longer has one of them, git fails with `pathspec ... did not match` and the
  step exits with "this run's collection was NOT saved".
- **The fifth-output hard stop.** After the restore, `git diff --quiet FETCH_HEAD -- public/data <reports>
  ':(exclude)rpi' ':(exclude)registry.json'` (line 323) stops the step if anything outside the collected parts
  still differs from main. So an unlisted build output is never pushed, and a restore that did nothing is caught.

**The key point.** The step runs the workflow as it was when the run started. If a rename is merged mid-run (the
issue's scenario), main's build writes the new name, but the running step's restore list still names the old one.

## Options
**A. Per-file tolerance for the three strict paths** (the triage comment), using the same `checkout || rm -rf` pattern.
- Fixes a *removed* output.
- Does **not** fix a *rename*. The new name is not in the running step's list, so it still differs from main, the
  fifth-output assertion fires, and the collection is lost anyway.
- Keeps the hard stop exactly as it is.

**B. Directory pathspecs** (`public/data/camps` instead of `camps/index.json`).
Fixes a rename inside one folder only. Still fatal when a whole folder is removed, and the measured rename
(`camps/index.json` to `camps-index.json`) still trips the assertion.

**C. Restore `public/data` except the collected parts, with no list of build outputs** (recommended):
```sh
find public/data -mindepth 1 -maxdepth 1 ! -name rpi ! -name registry.json -exec rm -rf {} +
git checkout FETCH_HEAD -- public/data ':(exclude)public/data/rpi' ':(exclude)public/data/registry.json'
```
- `public/data` always exists on main, so the checkout cannot hit a missing path.
- The `rm` drops whatever main lacks: an old name, a new name, a fifth output.
- The review reports outside `public/data` keep their tolerant per-file lines.
- The two exclusions become the only list. They name what is *collected*, which a build change does not move.

**C and the fifth-output rule.** The rule exists so that an unlisted build output is never *published*. Under C:
- That holds by construction: nothing outside the exclusions can differ from main on the sources branch, and the
  sources branch is the only place this path pushes.
- So a fifth output is no longer a hard stop: it is reset to main's state and the collection is saved.
- The `git diff --quiet` assertion stays word for word, as the check that the restore ran. #82's
  "restore silently no-ops" shim case still trips it. Only its annotation text changes.
- **The new risk:** a future collector writing under `public/data` outside `rpi/` and `registry.json` would be
  reset on a gated run's branch. Today that case is a hard stop that loses the whole collection, so C still loses
  less. Optional guard (reviewer's call): a harness check that every `*_OUT_DIR` / `*_PATH` under `PUBLIC_DATA_DIR`
  in `collect/common.py` is written by build.py or is one of the two exclusions.

**Recommendation: C.** It is the only option that fixes the rename #90 describes, and it removes a list someone must
edit by hand. Nothing unvalidated reaches a branch. The cost is changing #82's agreed `fifth-output` behaviour from
"nothing pushed" to "collection saved, fifth output not on the branch". I am asking for that explicitly. If
reviewers want the hard stop kept, the fallback is A, with the plan stating plainly that it does not cover a mid-run
rename.

**The smaller item, either way.** The gate's `::error` (line 340) gains: "Delete $branch once the failure is
triaged; nothing else deletes it."

## Reproduction and tests (offline, in the existing harness)
`tests/refresh_commit_step_test.py` already runs the step's shell, taken verbatim from `refresh.yml`, under `bash -e`
in a scratch bare `origin` and clone, with a stand-in `python` for build and validate driven by marker files. I add markers `CAMPS_RENAMED` (the stand-in writes `public/data/camps-index.json` instead of `camps/index.json`) and
`CAMPS_REMOVED` (it writes neither). The cases:
1. **`renamed-output`.** Main, mid-run, commits `CAMPS_RENAMED` and renames the file (the issue's measured rename),
   and the run's validate fails.
   - Expect: main unchanged; one `refresh-sources/*` branch holding the run's sources; the branch's `public/data`
     byte-equal to main's apart from `rpi/` and `registry.json`.
   - On main's `refresh.yml` today: no branch, and the output says `could not then be restored`. This is the
     test that fails on main.
2. **`removed-output`.** Main deletes `camps/index.json` and commits `CAMPS_REMOVED`. Same expectations, and it
   fails on main the same way.
3. **`fifth-output`, changed** (only if C is approved). Expect the collection on a branch with no
   `public/data/extra`. A control run of main's step shows today's hard stop.
4. **The new annotation sentence,** asserted in the `build-gate` case.

Each new case runs first against main's step (`REFRESH_YML=<main copy>`) to show it failing, then on the branch.
Every existing case (#82, #117, #132, #235, #321) must pass unchanged, then the full suites via `run-tests`. Out of scope: #89 (README), #86 (`always()` on the fail step), any retention job for `refresh-sources/*`.
