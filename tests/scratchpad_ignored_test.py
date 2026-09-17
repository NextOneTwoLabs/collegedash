"""scratchpad/ is ignored and nothing under it is tracked (issue #195).

    python tests/scratchpad_ignored_test.py            # every check
    python tests/scratchpad_ignored_test.py --verbose  # print every check, not only the failures

Agents and reviewers have written scratch notes to a scratchpad/ folder inside their worktree. Some of those
notes held real staff contact details copied from bio pages, and one reviewer's notes were swept into the
working-tree scan in tests/rpi_attribution_test.py and failed CI. .gitignore now lists scratchpad/; this
suite checks the rule is in place and effective, and - because `git add -f` goes straight past an ignore
rule - that git's index holds no path with a scratchpad/ segment, at any depth. A file staged there fails this
suite before it can be committed.

Reads git's view of the repository only (`git check-ignore`, `git ls-files`); writes nothing.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True)


def test_ignore_rule() -> None:
    print("ignore: .gitignore lists scratchpad/, and git treats a file there as ignored")
    with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as f:
        lines = [line.strip() for line in f]
    ok(".gitignore has a scratchpad/ line", "scratchpad/" in lines, [x for x in lines if "scratch" in x])
    # --no-index: judge the path by the rules alone, whether or not something there is already tracked
    for path in ("scratchpad/notes.md", "scratchpad/task-1/proof.py", "tests/scratchpad/notes.md"):
        res = git("check-ignore", "--no-index", "-q", path)
        ok(f"git ignores {path}", res.returncode == 0, f"check-ignore exit {res.returncode}: {res.stderr.decode(errors='replace')}")
    res = git("check-ignore", "--no-index", "-q", "tests/rpi_attribution_test.py")
    ok("CONTROL: an ordinary file is not ignored", res.returncode == 1, f"check-ignore exit {res.returncode}")


def test_nothing_tracked() -> None:
    print("tracked: git's index holds no path under a scratchpad/ folder, committed or staged")
    res = git("ls-files", "-z", "--cached")
    ok("git ls-files ran", res.returncode == 0, res.stderr.decode(errors="replace"))
    paths = [p for p in res.stdout.decode("utf-8", errors="replace").split("\0") if p]
    ok("git ls-files listed the repository (so an empty result below means something)", len(paths) > 100, len(paths))
    under = [p for p in paths if "scratchpad" in p.split("/")[:-1]]
    ok("no tracked or staged file is under scratchpad/", not under, under[:20])


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_ignore_rule, test_nothing_tracked):
        try:
            case()
        except Exception as e:  # a case that raises is a failed case, not a lost run
            ok(f"{case.__name__} ran to the end", False, f"{type(e).__name__}: {e}")
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
