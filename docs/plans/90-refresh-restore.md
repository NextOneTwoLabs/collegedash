# Plan: #90, a renamed build() output must not lose a gated run's collection

Issue #90 and its 2026-10-01 triage comment; gate from #82; `.github/workflows/refresh.yml`, step "Commit changed
data", `publish_sources_only` (main 60bc94e17, lines 298-342). Author: Jueying. Revision 2, after Bianque's round-1
review, which endorsed C and the change to #82's behaviour.

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

**A removed output is already safe, so it is not the bug.** Every build rewrites every output (a fresh `builtAt`), so
when main deletes one, the rebase stops on a modify/delete conflict. `save_collection` then saves the run on
`refresh-sources/<run>-unpublished` before `publish_sources_only` is reached (measured by Bianque). A rename that
falls below git's 50% similarity threshold (a rename PR that also rebuilt the file) takes the same path. Only a
rename git detects reaches the gate's restore; that is test 1.

## Options
- **A. Per-file tolerance for the three strict paths** (the triage comment). Does not fix the rename: the new name is
  not in the running step's list, so the assertion fires and the collection is lost anyway (measured).
- **B. Directory pathspecs.** Covers only a rename inside one folder, not the measured `camps/index.json` to
  `camps-index.json`.
- **C. Restore `public/data` except the collected parts, with no list of build outputs** (approved):
```sh
find public/data -mindepth 1 -maxdepth 1 ! -name rpi ! -name registry.json -exec rm -rf {} +
if ! git checkout FETCH_HEAD -- public/data ':(exclude)public/data/rpi' ':(exclude)public/data/registry.json'; then
  ::error ...; exit 1     # the guard line 318 has today
fi
```
  `public/data` always exists on main, so the checkout cannot hit a missing path. The `rm` drops whatever main lacks:
  an old name, a new name, a fifth output.

**This changes #82's behaviour.** A fifth build output is no longer a hard stop that loses the collection. It is
reset to main's state, and the collection is saved. What #82's rule protects still holds by construction: nothing
outside `rpi/` and `registry.json` can differ from main on the sources branch, and main is pushed only after build
and validate pass. The `git diff --quiet` assertion stays word for word, as the check that the restore really ran.
- **Annotations.** The assertion's (line 324) and the success annotation's (line 340) hand-written lists of build
  outputs become "everything under public/data except rpi/ and registry.json", so no list is left to go stale. The
  success annotation gains "Delete $branch once the failure is triaged; nothing else deletes it."
- **Review reports.** The two `data/*-review.json` reports stay per-file and tolerant. A future rename of one would
  reach the sources branch as the run's copy, unseen by the assertion. That is the branch only, never main: low risk,
  noted in a comment.
- **Collector guard.** A static test (new file, `tests/public_data_writers_test.py`): every path under
  `PUBLIC_DATA_DIR` that `collect/` writes is under `RPI_OUT_DIR` or is `REGISTRY_PATH`. A future collector
  writing elsewhere in `public/data` would be reset silently on a gated run's branch; this makes CI red instead.

## Tests (offline, in `tests/refresh_commit_step_test.py`, which runs the step's shell verbatim in scratch repos)
1. **`renamed-output`, the test that fails on main.** Main, mid-run, renames `camps/index.json` to
   `camps-index.json`, and its stand-in build writes the new name; the run's validate fails.
   - Expect: main unchanged; branch `refresh-sources/123-1-1` with the run's sources and RPI table; its `public/data`
     byte-equal to main's apart from `rpi/` and `registry.json`.
   - On main today: no branch, `could not then be restored`.
2. **`removed-output`, a guard, not a failing test.** Main deletes `camps/index.json` and stops writing it. Passes on
   main and on the branch: the collection is on `refresh-sources/123-1-unpublished` and main is unchanged.
3. **`restore-control`, replacing the list/fit controls.** C's checkout is replaced by `true` (the `rm` still runs).
   The step must stop on `does not match` with nothing pushed. This keeps the only test that the assertion catches a
   restore that did nothing.
4. **Repointed checks.** `list-restore`, `fit-restore` and `tests/trends_test.py:529` assert C's restore lines
   instead of their own deleted lines. Their absent / main's-copy / published checks stay.
5. **`fifth-output`, changed.** The collection is on a branch with no `public/data/extra`, and the error annotation
   is the ordinary gate one, not `does not match`.
6. **`build-gate`** also asserts the new "Delete ... once the failure is triaged" sentence.

**Order of work.** First the rename test (shown failing on main's step), then the fix and the repointed checks, then
the full harness and the full suites via `run-tests`.

**Out of scope.** #89 (README), #86 (`always()` on the fail step), and any retention job for `refresh-sources/*`.
