# #126 F-d: `python collegedash.py build` always exits 0 — design note (not implemented)

**Today** (`origin/main` 60bc94e17): `build.build()` plans the prune (it refuses only *unexplained* stale profiles),
writes every profile, **deletes the stale ones**, then calls `validate()` and only logs "schema validation reported
errors" (`build.py:2313`). `cmd_build` returns 0 (`collegedash.py:823`). So a registry that unpublishes 40 programs
"explainably" (F-a's case) deletes 40 profiles, and the command still exits 0. The message says "schema" for what is a
`MEMBERSHIP` failure. Five callers run `build.build()`: `cmd_build`, `cmd_refresh` (:594), and `onboard` (:299, :427, :509).

**What CI does with it today:**
- The refresh commit step (`refresh.yml:485-488`, `if: always()`) runs `build`, then `validate`. A failing `validate`
  routes to `publish_sources_only` ("validate failed"), which restores `public/data/programs` from main, so **CI never
  publishes the deletion**. The harm is local runs, and a misleading exit code.
- The `build_only` step (:147-148) runs `build && validate`; validate's exit fails the run.

**Option A — fail before anything is deleted.** Run the registry-only checks (`check_membership_anchor`, plus F-b's
division check now inside it) before `plan_prune` and before the first write. On failure, raise with a `MEMBERSHIP`
message; nothing is written or deleted. `cmd_build` exits 1.
- refresh.yml: the commit step sees `build` fail, so it reports "build failed" instead of "validate failed". The
  outcome is the same: sources-only branch, nothing published, the run fails.
- **Risk:** `cmd_refresh` calls `build.build()` before `report_refresh`. A raise there would skip the run summary
  (lastRun, failure warnings) and turn the refresh step's code to 1, which "Fail if too many collectors failed" would
  misreport as a collector threshold. So `cmd_refresh` (and `onboard`) must catch it, log it, still report, and leave
  the gate to the commit step's rebuild. That's a few lines, and it needs a test.
- Only registry checks can move ahead; the profile and schema checks need the written files, so they stay after.

**Option B — keep the order and return non-zero.** `build()` returns validate's result, `cmd_build` exits 1 when it
fails, and the message names the failing check groups (`MEMBERSHIP`, `SCHEMA`, ...), not "schema".
- refresh.yml: the same as A (a "build failed" label instead of "validate failed"); `build_only` stops one command
  earlier.
- **Risk:** the 40 profiles are still deleted on disk before the failure. Locally, someone has to `git checkout` them
  back. CI is safe only because the commit step restores from main.

**Recommendation: A, with B's message and exit code.** Check registry membership before writing or deleting
anything; keep the full `validate()` after the build; exit non-zero on either; catch it in `cmd_refresh` and
`onboard` so the run summary is always written. Tests, failing on main first:
1. `build` with F-a's truncated-registry case exits 1, and the profiles directory is byte-identical afterwards.
2. `cmd_refresh` with a failing membership check still writes lastRun and its warnings, with code 1 and a
   `MEMBERSHIP` annotation, not a threshold message.
3. `tests/refresh_commit_step_test.py`: a failing build routes to `publish_sources_only` as a failing validate does.

This changes the exit code the workflow sees, so it needs a Reviewer's approval before code.
