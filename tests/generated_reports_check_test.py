"""Offline tests for .github/scripts/check_generated_reports.py (issue #235).

    python tests/generated_reports_check_test.py            # every case
    python tests/generated_reports_check_test.py --verbose  # print every check, not only the failures

Each case builds a scratch "origin" and a clone under a temporary directory, the way a PR looks to
the "Generated reports not in PR" job: main carries both review reports, a branch is cut, and a
"refresh" then rewrites the reports on main. The script runs with the working directory set to the
clone and whatever the case has checked out. In most cases that is GitHub's test merge (main merged
into the branch, detached), because that is the job's real checkout, and a script that diffed the
checked-out HEAD instead of --head would fail those cases. Nothing touches this repository or any remote.

Cases:
  untouched          the branch changes only data/clubs.json, cut before the refresh      -> pass
  regenerated        the branch commits its own copy of a report                           -> fail
  false-pass         cut before the refresh, reports set to main's CURRENT copy, no rebase -> fail
                     (a diff against main's tip would pass it; the next refresh conflicts)
  fix-command        that branch after running the failure message's own fix command     -> pass
  rebased            rebased onto main, keeping main's copy                                -> pass
  deleted            the branch deletes a report                                           -> fail
  added              the merge base has no schools report and the branch adds one          -> fail
  bad-input          an unknown sha                                                        -> exit 2
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, ".github", "scripts", "check_generated_reports.py")
sys.path.insert(0, os.path.dirname(SCRIPT))
import check_generated_reports as cgr  # noqa: E402

CLUBS, SCHOOLS = cgr.REPORTS

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False

GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "harness",
           "GIT_AUTHOR_EMAIL": "harness@example.invalid", "GIT_COMMITTER_NAME": "harness",
           "GIT_COMMITTER_EMAIL": "harness@example.invalid"}
ENV = {**os.environ, **GIT_ENV}


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:600]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def find_bash() -> str:
    if os.name == "nt":  # Git for Windows' bash, never WSL's
        exec_path = subprocess.run(["git", "--exec-path"], capture_output=True, text=True).stdout.strip()
        cand = os.path.normpath(os.path.join(exec_path, "..", "..", "..", "bin", "bash.exe"))
        if os.path.exists(cand):
            return cand
    return shutil.which("bash") or "bash"


BASH = find_bash()


def git(repo: str, *args: str) -> str:
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env=ENV)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr}")
    return r.stdout.strip()


def write(repo: str, path: str, text: str) -> None:
    full = os.path.join(repo, *path.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def commit(repo: str, msg: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


class Scene:
    """origin (bare) + a clone. main: seed -> refresh; `branch` is cut from seed."""

    def __init__(self, tmp: str, name: str, *, seed_schools: bool = True):
        root = os.path.join(tmp, name)
        self.origin = os.path.join(root, "origin.git")
        self.work = os.path.join(root, "work")
        os.makedirs(root)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin], check=True, env=ENV)
        subprocess.run(["git", "-c", "core.autocrlf=false", "clone", "-q", self.origin, self.work],
                       check=True, capture_output=True, env=ENV)
        git(self.work, "config", "core.autocrlf", "false")
        git(self.work, "symbolic-ref", "HEAD", "refs/heads/main")
        write(self.work, "README.md", "harness\n")
        write(self.work, "data/clubs.json", '{"clubs": 1}\n')
        write(self.work, CLUBS, '{"updated": "seed"}\n')
        if seed_schools:
            write(self.work, SCHOOLS, '{"updated": "seed"}\n')
        self.seed = commit(self.work, "seed")
        git(self.work, "push", "-q", "origin", "main")
        git(self.work, "checkout", "-q", "-b", "branch", self.seed)

    def refresh_main(self) -> str:
        """A refresh lands on main: both reports rewritten (schools created if main had none)."""
        git(self.work, "checkout", "-q", "main")
        write(self.work, CLUBS, '{"updated": "refresh-1"}\n')
        write(self.work, SCHOOLS, '{"updated": "refresh-1"}\n')
        write(self.work, "programs/a/sources/x.json", '"collected"\n')
        sha = commit(self.work, "data: refresh")
        git(self.work, "push", "-q", "origin", "main")
        git(self.work, "checkout", "-q", "branch")
        return sha

    def push_branch(self) -> str:
        git(self.work, "push", "-q", "-f", "origin", "branch")
        return git(self.work, "rev-parse", "branch")

    def checkout_test_merge(self) -> None:
        """What actions/checkout gives a pull_request job: main merged into the PR head, detached."""
        git(self.work, "fetch", "-q", "origin")
        git(self.work, "checkout", "-q", "--detach", "origin/branch")
        git(self.work, "merge", "-q", "--no-edit", "origin/main")

    def run(self, head: str | None = None, base: str | None = None) -> tuple[int, str]:
        base = base or git(self.work, "rev-parse", "origin/main")
        head = head or git(self.work, "rev-parse", "origin/branch")
        r = subprocess.run([sys.executable, SCRIPT, "--base", base, "--head", head], cwd=self.work,
                           capture_output=True, text=True, env=ENV)
        return r.returncode, r.stdout + r.stderr

    def head_diff(self) -> list[str]:
        """What a script diffing the checked-out HEAD (not --head) would see."""
        mb = git(self.work, "merge-base", "origin/main", "origin/branch")
        return [p for p in git(self.work, "diff", "--name-only", mb, "HEAD", "--", *cgr.REPORTS).splitlines() if p]


def test_untouched(tmp):
    print("untouched: a table-only branch cut before a refresh")
    s = Scene(tmp, "untouched")
    write(s.work, "data/clubs.json", '{"clubs": 2}\n')
    commit(s.work, "table edit")
    s.push_branch()
    s.refresh_main()
    s.checkout_test_merge()
    ok("the test merge is checked out, and a HEAD diff would see both reports",
       sorted(s.head_diff()) == sorted(cgr.REPORTS), s.head_diff())
    code, out = s.run()
    ok("FIX passes: the script diffs --head, not the test merge", code == 0, out)


def test_regenerated(tmp):
    print("regenerated: the branch commits its own report")
    s = Scene(tmp, "regenerated")
    write(s.work, "data/clubs.json", '{"clubs": 2}\n')
    write(s.work, CLUBS, '{"updated": "branch build"}\n')
    commit(s.work, "table edit + rebuilt report")
    s.push_branch()
    s.refresh_main()
    # no test merge here: it would conflict, and GitHub gives a conflicting PR no pull_request run at all.
    # The script is run on the branch as it was pushed, before the refresh made it conflict.
    code, out = s.run()
    ok("fails", code == 1, out)
    ok("names the changed report, and only it", f"This pull request changes {CLUBS}.\n" in out, out)
    ok("gives the fix command", cgr.FIX in out, out)
    ok("emits an ::error annotation", "::error title=generated reports::" in out)


def test_false_pass_and_fix(tmp):
    print("false-pass: cut before the refresh, reports set to main's current copy without rebasing")
    s = Scene(tmp, "false-pass")
    write(s.work, "data/clubs.json", '{"clubs": 2}\n')
    write(s.work, CLUBS, '{"updated": "branch build"}\n')
    commit(s.work, "table edit + rebuilt report")
    s.push_branch()
    s.refresh_main()
    git(s.work, "fetch", "-q", "origin")
    git(s.work, "checkout", "-q", "origin/main", "--", *cgr.REPORTS)  # the plan's first, wrong instruction
    commit(s.work, "take main's reports")
    s.push_branch()
    tip_diff = git(s.work, "diff", "--name-only", "origin/main", "origin/branch", "--", *cgr.REPORTS)
    ok("control: a diff against main's tip sees nothing (the false pass)", tip_diff == "", tip_diff)
    s.checkout_test_merge()
    code, out = s.run()
    ok("FIX fails: against the merge base the branch still changes both reports", code == 1 and CLUBS in out and SCHOOLS in out, out)

    print("fix-command: the failure message's own command, run as written")
    git(s.work, "checkout", "-q", "branch")
    r = subprocess.run([BASH, "-c", cgr.FIX], cwd=s.work, capture_output=True, text=True, env=ENV)
    ok("the fix command runs", r.returncode == 0, r.stdout + r.stderr)
    s.push_branch()
    s.checkout_test_merge()
    code, out = s.run()
    ok("after it the check passes", code == 0, out)
    ok("and the branch's reports are the merge base's",
       git(s.work, "diff", "--name-only", s.seed, "origin/branch", "--", *cgr.REPORTS) == "")


def test_rebased(tmp):
    print("rebased: the branch is rebased onto main and keeps main's copy")
    s = Scene(tmp, "rebased")
    write(s.work, "data/clubs.json", '{"clubs": 2}\n')
    commit(s.work, "table edit")
    s.refresh_main()
    git(s.work, "rebase", "-q", "main")
    s.push_branch()
    s.checkout_test_merge()
    code, out = s.run()
    ok("passes", code == 0, out)


def test_deleted(tmp):
    print("deleted: the branch deletes a report")
    s = Scene(tmp, "deleted")
    os.remove(os.path.join(s.work, *SCHOOLS.split("/")))
    commit(s.work, "drop report")
    s.push_branch()
    s.checkout_test_merge()
    code, out = s.run()
    ok("fails and names it", code == 1 and SCHOOLS in out, out)


def test_added(tmp):
    print("added: the merge base has no schools report and the branch adds one")
    s = Scene(tmp, "added", seed_schools=False)
    write(s.work, SCHOOLS, '{"updated": "branch build"}\n')
    commit(s.work, "add report")
    s.push_branch()
    s.checkout_test_merge()
    code, out = s.run()
    ok("fails and names it", code == 1 and SCHOOLS in out, out)


def test_bad_input(tmp):
    print("bad-input: an unknown sha")
    s = Scene(tmp, "bad-input")
    s.push_branch()
    code, out = s.run(head="0" * 40)
    ok("exits 2 with an ::error", code == 2 and "::error" in out, out)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    tmp = tempfile.mkdtemp(prefix="gen-reports-")
    try:
        for case in (test_untouched, test_regenerated, test_false_pass_and_fix, test_rebased, test_deleted,
                     test_added, test_bad_input):
            case(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
