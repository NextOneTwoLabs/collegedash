"""Harness for the "Commit changed data" step of .github/workflows/refresh.yml (issues #82, #117).

    python tests/refresh_commit_step_test.py            # every case
    python tests/refresh_commit_step_test.py --verbose  # print every check, not only the failures
    REFRESH_YML=path/to/refresh.yml python tests/refresh_commit_step_test.py   # run another version of the step

The step's shell is extracted verbatim from the workflow file and run under `bash -e`, the way Actions
runs a `run:` block, inside scratch repositories under a temporary directory. Nothing touches this
repository or any remote.

Each case:
  - seeds a bare "origin" at the object level (hash-object --no-filters, mktree, commit-tree), so
    core.autocrlf can neither add nor hide a difference, and clones it with core.autocrlf=false;
  - plays a refresh in the clone: collected sources change, and a stand-in `python collegedash.py build`
    rewrites every profile (as a real rebuild does: _build.builtAt changes) and prunes profiles the
    registry no longer lists;
  - moves origin's main mid-run, the way a merged PR would;
  - runs the step and inspects origin: main, and any refresh-sources/* branch.

The stand-in `python` is a shell script on PATH: `build` writes one profile per slug listed in
public/data/registry.json, removes any other profile, and writes the three indexes; it fails when the
tree holds BUILD_FAILS, and writes a fifth output when it holds FIFTH_OUTPUT. `validate` fails when the
tree holds VALIDATE_FAILS. `sleep` is a no-op so the retry loop runs in milliseconds.

Cases (issue #117 first, then the #82 gate behaviour that must not change):
  deleted-upstream        main deletes a profile the run rewrote (modify/delete). The deletion stands, the
                          run's data is rebuilt onto main and published, and nothing is left on a branch.
  deleted-and-gated       the same conflict, and validate fails on the rebuilt data. Nothing is published;
                          the collection is on refresh-sources/*, with public/data exactly as main has it
                          (the deleted profile included) apart from rpi and registry.
  deleted-registry-kept   main deletes a profile BY HAND and leaves the registry alone (the issue #107
                          shape). The rebuild puts it back, because the registry still publishes it, and
                          the step says so in a ::warning instead of claiming the deletion was kept.
  deletion-direction      the same, against a build that never recreates a deleted profile: what the step
                          leaves behind is then visible, and it must be the deletion.
  registry-both-sides     main and the run both change registry.json and a profile conflicts: `-X theirs`
                          would keep the run's registry and revert main's membership change, so the step
                          fails closed and keeps the collection.
  content-conflict        both sides change public/data/rpi/current.json: `-X theirs` keeps the run's
                          collected table, which is what the whole step is built on.
  upstream-code-change    main changes collegedash.py mid-run: the published data must be the output of
                          main's code, not of the code the run built with (issue #75).
  unrelated-upstream      main changes an unrelated file. Published as before.
  unhandled-conflict      main deletes a collected SOURCE file the run modified - a conflict the step
                          must not resolve. Nothing is published, and the collection is saved on a
                          refresh-sources/* branch with an ::error saying why.
  pruned-by-run           the run's own registry change unpublishes a profile (the build prunes it) while
                          main rewrites that profile (delete/modify, the reverse direction). The deletion
                          stands and the run publishes.
  mixed-conflict          main deletes a profile the run rewrote AND a source the run modified. One conflict is
                          not the step's to settle, so none is: the collection is saved on a branch.
  push-always-rejected    origin rejects every push to main. After the retries the collection is saved on
                          a refresh-sources/* branch instead of being dropped.
  build-gate              (#82) build fails after the rebase: collection on a branch, data as main has it.
  fifth-output            (#82) build writes a fifth output and validate fails: the fifth-output assertion
                          stops the step, nothing is pushed anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YML = os.environ.get("REFRESH_YML") or os.path.join(ROOT, ".github", "workflows", "refresh.yml")

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:400]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


# ---------- the step, verbatim ----------

def extract_step(path: str, name: str = "Commit changed data") -> str:
    """The `run: |` block of the named step, dedented exactly as YAML's literal block scalar does."""
    lines = open(path, encoding="utf-8").read().splitlines()
    start = next(i for i, l in enumerate(lines) if re.match(rf"\s*- name: {re.escape(name)}\s*$", l))
    run = next(i for i in range(start + 1, len(lines)) if re.match(r"\s*run: \|\s*$", lines[i]))
    body = []
    indent = None
    for l in lines[run + 1:]:
        if l.strip() == "":
            body.append("")
            continue
        lead = len(l) - len(l.lstrip(" "))
        if indent is None:
            indent = lead
        if lead < indent:
            break
        body.append(l[indent:])
    while body and body[-1] == "":
        body.pop()
    return "\n".join(body) + "\n"


# ---------- tools ----------

def find_bash() -> str:
    if os.name == "nt":  # Git for Windows' bash, never WSL's
        exec_path = subprocess.run(["git", "--exec-path"], capture_output=True, text=True).stdout.strip()
        cand = os.path.normpath(os.path.join(exec_path, "..", "..", "..", "bin", "bash.exe"))
        if os.path.exists(cand):
            return cand
    return shutil.which("bash") or "bash"


BASH = find_bash()
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "harness", "GIT_AUTHOR_EMAIL": "harness@example.invalid",
           "GIT_COMMITTER_NAME": "harness", "GIT_COMMITTER_EMAIL": "harness@example.invalid", "GIT_AUTHOR_DATE": "2026-09-16T00:00:00Z",
           "GIT_COMMITTER_DATE": "2026-09-16T00:00:00Z"}


def git(repo: str, *args, input: bytes | None = None, check: bool = True, env: dict | None = None) -> str:
    r = subprocess.run(["git", "-C", repo, *args], input=input, capture_output=True, env={**os.environ, **GIT_ENV, **(env or {})})
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.decode(errors='replace')}")
    return r.stdout.decode(errors="replace").strip()


def commit_files(bare: str, files: dict[str, bytes], parent: str | None, message: str) -> str:
    """A commit holding exactly `files`, built from blobs and trees; no index, no working tree, no filters."""
    tree: dict = {}
    for path, data in files.items():
        node = tree
        parts = path.split("/")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = git(bare, "hash-object", "-w", "--no-filters", "--stdin", input=data)

    def write(node: dict) -> str:
        entries = []
        for name, v in sorted(node.items()):
            if isinstance(v, dict):
                entries.append(f"040000 tree {write(v)}\t{name}")
            else:
                entries.append(f"100644 blob {v}\t{name}")
        return git(bare, "mktree", input=("\n".join(entries) + "\n").encode())

    args = ["commit-tree", write(tree), "-m", message] + (["-p", parent] if parent else [])
    return git(bare, *args)


def tree_files(repo: str, rev: str) -> dict[str, bytes]:
    out = {}
    for line in git(repo, "ls-tree", "-r", rev).splitlines():
        meta, path = line.split("\t", 1)
        out[path] = subprocess.run(["git", "-C", repo, "cat-file", "blob", meta.split()[2]], capture_output=True).stdout
    return out


# ---------- the stand-ins ----------

# `python` on PATH is a two-line shim; the build and validate it runs live in the seeded repository as
# collegedash.py, so a commit on main can change them. That is what makes the rebuild-after-rebase property
# of issue #75 testable here: after a rebase onto a main whose collegedash.py stamps differently, the
# published profiles must carry main's stamp, not the one the run built with.
FAKE_PYTHON = "#!/usr/bin/env bash\nexec bash ./collegedash.py \"$@\"\n"

COLLEGEDASH = r'''#!/usr/bin/env bash
# stand-in for collegedash.py: build and validate, enough of their contract for the commit step.
set -e
STAMP_PREFIX="built"
cmd="$2"
if [ "$1" != "collegedash.py" ]; then echo "harness: unexpected $*" >&2; exit 2; fi
case "$cmd" in
  build)
    if [ -f BUILD_FAILS ]; then echo "harness: build crashed" >&2; exit 1; fi
    stamp="$STAMP_PREFIX-$(date +%s%N)"
    mkdir -p public/data/programs public/data/commitments public/data/camps
    slugs=$(sed -n 's/.*"published": \[\(.*\)\].*/\1/p' public/data/registry.json | tr -d '" ' | tr ',' ' ')
    for f in public/data/programs/*.json; do
      s=$(basename "$f" .json); [ "$s" = index ] && continue
      case " $slugs " in *" $s "*) ;; *) rm -f "$f" ;; esac
    done
    for s in $slugs; do
      # KEEP_ONLY_EXISTING: a build that updates the profiles it finds and never recreates a deleted one.
      # Not how build.py behaves; it is here so the step's own resolution direction is observable.
      if [ -f KEEP_ONLY_EXISTING ] && [ ! -f "public/data/programs/$s.json" ]; then continue; fi
      src=$(cat "programs/$s/sources/athletics.json" 2>/dev/null || echo none)
      printf '{"slug": "%s", "source": %s, "builtAt": "%s"}\n' "$s" "$src" "$stamp" > "public/data/programs/$s.json"
    done
    printf '{"programs": "%s", "builtAt": "%s"}\n' "$slugs" "$stamp" > public/data/programs/index.json
    printf '{"builtAt": "%s"}\n' "$stamp" > public/data/commitments/index.json
    printf '{"builtAt": "%s"}\n' "$stamp" > public/data/camps/index.json
    if [ -f FIFTH_OUTPUT ]; then mkdir -p public/data/extra; printf '{"x": 1}\n' > public/data/extra/x.json; fi
    ;;
  validate)
    if [ -f VALIDATE_FAILS ]; then echo "harness: validate failed" >&2; exit 1; fi
    ;;
  *) echo "harness: unknown command $cmd" >&2; exit 2 ;;
esac
exit 0
'''


def write_exe(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ---------- one case ----------

def base_files(published=("alpha", "beta", "ghost")) -> dict[str, bytes]:
    reg = json.dumps({"published": list(published)}) + "\n"
    files = {"README.md": b"harness\n", "public/data/registry.json": reg.encode(),
             "public/data/rpi/current.json": b'{"season": 2025}\n'}
    for s in published:
        files[f"programs/{s}/sources/athletics.json"] = f'"{s}-v1"\n'.encode()
        files[f"public/data/programs/{s}.json"] = f'{{"slug": "{s}", "source": "{s}-v1", "builtAt": "old"}}\n'.encode()
    files["collegedash.py"] = COLLEGEDASH.encode()
    files["public/data/programs/index.json"] = b'{"builtAt": "old"}\n'
    files["public/data/commitments/index.json"] = b'{"builtAt": "old"}\n'
    files["public/data/camps/index.json"] = b'{"builtAt": "old"}\n'
    return files


def run_case(tmp: str, name: str, *, upstream, run_markers=(), reject_main_push=False, run_registry=None):
    """Returns (exit code, output, origin path, main-before sha, upstream sha, run clone path)."""
    root = os.path.join(tmp, name)
    origin = os.path.join(root, "origin.git")
    work = os.path.join(root, "runner")
    os.makedirs(root)
    subprocess.run(["git", "init", "-q", "--bare", origin], check=True, env={**os.environ, **GIT_ENV})
    git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    c0_files = base_files()
    c0 = commit_files(origin, c0_files, None, "seed")
    git(origin, "update-ref", "refs/heads/main", c0)
    subprocess.run(["git", "-c", "core.autocrlf=false", "clone", "-q", origin, work], check=True, capture_output=True, env={**os.environ, **GIT_ENV})
    git(work, "config", "core.autocrlf", "false")

    bin_dir = os.path.join(root, "bin")
    os.makedirs(bin_dir)
    write_exe(os.path.join(bin_dir, "python"), FAKE_PYTHON)
    write_exe(os.path.join(bin_dir, "sleep"), "#!/usr/bin/env bash\nexit 0\n")
    env = {**os.environ, **GIT_ENV, "PATH": bin_dir + os.pathsep + os.environ.get("PATH", ""),
           "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "BUILD_ONLY": "false"}

    # --- the refresh: collected sources and RPI change, then the refresh's own build rewrites every profile
    with open(os.path.join(work, "programs", "alpha", "sources", "athletics.json"), "w", newline="\n") as f:
        f.write('"alpha-v2-collected"\n')
    with open(os.path.join(work, "programs", "ghost", "sources", "athletics.json"), "w", newline="\n") as f:
        f.write('"ghost-v2-collected"\n')
    with open(os.path.join(work, "public", "data", "rpi", "current.json"), "w", newline="\n") as f:
        f.write('{"season": 2026}\n')
    if run_registry is not None:  # the run's own registry change (a registry build or onboard during the run)
        with open(os.path.join(work, "public", "data", "registry.json"), "w", newline="\n") as f:
            f.write(json.dumps({"published": run_registry}) + "\n")
        for slug in run_registry:  # a program the run onboarded has sources but no profile on main yet
            d = os.path.join(work, "programs", slug, "sources")
            os.makedirs(d, exist_ok=True)
            if not os.path.exists(os.path.join(d, "athletics.json")):
                with open(os.path.join(d, "athletics.json"), "w", newline="\n") as f:
                    f.write(f'"{slug}-v2-collected"\n')
    r = subprocess.run([BASH, "-e", os.path.join(bin_dir, "python"), "collegedash.py", "build"], cwd=work, env=env, capture_output=True)
    assert r.returncode == 0, r.stderr

    # --- main moves mid-run
    up_files = upstream(dict(c0_files))
    c1 = commit_files(origin, up_files, c0, f"upstream change for {name}")
    git(origin, "update-ref", "refs/heads/main", c1)
    if reject_main_push:
        hooks = os.path.join(origin, "hooks")
        write_exe(os.path.join(hooks, "pre-receive"),
                  "#!/usr/bin/env bash\nwhile read old new ref; do\n  if [ \"$ref\" = refs/heads/main ]; then echo 'harness: main is protected' >&2; exit 1; fi\ndone\nexit 0\n")
    for m in run_markers:  # markers the stand-in build/validate read from the working tree after the rebase
        up_marker = os.path.join(work, m)
        open(up_marker, "w").close()
        # keep the marker out of the commit: it is runner state, not data
        with open(os.path.join(work, ".git", "info", "exclude"), "a") as f:
            f.write(m + "\n")

    script = os.path.join(root, "step.sh")
    with open(script, "w", encoding="utf-8", newline="\n") as f:
        f.write(extract_step(YML))
    r = subprocess.run([BASH, "-e", script], cwd=work, env=env, capture_output=True, timeout=300)
    out = (r.stdout + r.stderr).decode(errors="replace")
    return r.returncode, out, origin, c1, work


def branches(origin: str) -> list[str]:
    return [b for b in git(origin, "for-each-ref", "--format=%(refname)", "refs/heads/").splitlines() if b != "refs/heads/main"]


def data_view(files: dict[str, bytes]) -> dict[str, bytes]:
    """public/data without the collected parts (rpi, registry.json): what the #82 gate restores."""
    return {k: v for k, v in files.items() if k.startswith("public/data/") and not k.startswith("public/data/rpi/")
            and k != "public/data/registry.json"}


# ---------- the cases ----------

def drop_ghost(files):
    files.pop("public/data/programs/ghost.json")
    files["public/data/registry.json"] = (json.dumps({"published": ["alpha", "beta"]}) + "\n").encode()
    return files


def test_deleted_upstream(tmp):
    print("deleted-upstream: main deletes a profile the run rewrote")
    code, out, origin, c1, _ = run_case(tmp, "deleted-upstream", upstream=drop_ghost)
    main = git(origin, "rev-parse", "refs/heads/main")
    files = tree_files(origin, "refs/heads/main")
    ok("the step succeeds", code == 0, out[-1500:])
    ok("the run's commit is published on top of the upstream change", main != c1 and git(origin, "rev-parse", "refs/heads/main~1") == c1)
    ok("the profile deleted upstream stays deleted", "public/data/programs/ghost.json" not in files, sorted(files))
    ok("the collected source is published", files.get("programs/alpha/sources/athletics.json") == b'"alpha-v2-collected"\n')
    ok("the published profiles are rebuilt from it", b"alpha-v2-collected" in files.get("public/data/programs/alpha.json", b"")
       and b'"builtAt": "old"' not in files.get("public/data/programs/beta.json", b""))
    ok("the collected RPI table is published", files.get("public/data/rpi/current.json") == b'{"season": 2026}\n')
    ok("no sources branch is left behind", branches(origin) == [], branches(origin))


def test_deleted_and_gated(tmp):
    print("deleted-and-gated: main deletes a profile, and validate fails on the rebuilt data")
    # the run also onboards a new program, so the rebuild creates a profile main has no file for: the gate's restore
    # has to remove it again, which is what `rm -rf public/data/programs` before the checkout is for
    # the run's registry still publishes ghost, so its build rewrites ghost.json and main's deletion really
    # conflicts (a delete/delete would not: PR #124 review, item 6). It also onboards a new program, so the
    # rebuild creates a profile main has no file for and the gate's restore has to remove it again.
    code, out, origin, c1, _ = run_case(tmp, "deleted-and-gated", upstream=drop_ghost, run_markers=("VALIDATE_FAILS",),
                                        run_registry=["alpha", "beta", "ghost", "newprog"])
    ok("the step fails", code != 0, out[-800:])
    ok("main is exactly the upstream commit", git(origin, "rev-parse", "refs/heads/main") == c1)
    bs = branches(origin)
    ok("the collection is on one refresh-sources/* branch", len(bs) == 1 and bs[0].startswith("refs/heads/refresh-sources/"), bs)
    if len(bs) == 1:
        files = tree_files(origin, bs[0])
        ok("the branch holds the collected source and RPI table", files.get("programs/alpha/sources/athletics.json") == b'"alpha-v2-collected"\n'
           and files.get("public/data/rpi/current.json") == b'{"season": 2026}\n')
        ok("and the newly onboarded program's sources, with no profile for it (main has none)",
           files.get("programs/newprog/sources/athletics.json") == b'"newprog-v2-collected"\n'
           and "public/data/programs/newprog.json" not in files, sorted(k for k in files if "newprog" in k))
        ok("its public/data (except rpi and registry) is exactly main's, the deleted profile included",
           data_view(files) == data_view(tree_files(origin, c1)), sorted(set(data_view(files)) ^ set(data_view(tree_files(origin, c1)))))
        ok("the branch is one commit on top of main", git(origin, "rev-parse", f"{bs[0]}~1") == c1)
    ok("an ::error says validate failed and names the branch", "::error" in out and "validate failed" in out and "refresh-sources/" in out)
    # fails if the case stops exercising the resolution: a delete/delete raises no conflict at all
    ok("the resolution really fired: the rebase hit a conflict on the profile", "CONFLICT" in out and "public/data/programs/ghost.json" in out,
       out[-600:])
    ok("the branch is named for this run and attempt", bs == ["refs/heads/refresh-sources/123-1-1"], bs)


def test_unrelated_upstream(tmp):
    print("unrelated-upstream: main changes an unrelated file")
    def readme(files):
        files["README.md"] = b"harness, edited upstream\n"
        return files
    code, out, origin, c1, _ = run_case(tmp, "unrelated-upstream", upstream=readme)
    files = tree_files(origin, "refs/heads/main")
    ok("the step succeeds", code == 0, out[-1500:])
    ok("published on top of the upstream change, keeping it", git(origin, "rev-parse", "refs/heads/main~1") == c1
       and files.get("README.md") == b"harness, edited upstream\n")
    ok("with the run's collection and every profile", files.get("programs/alpha/sources/athletics.json") == b'"alpha-v2-collected"\n'
       and {"public/data/programs/alpha.json", "public/data/programs/beta.json", "public/data/programs/ghost.json"} <= set(files))
    ok("no sources branch", branches(origin) == [])


def test_unhandled_conflict(tmp):
    print("unhandled-conflict: main deletes a collected source file the run modified")
    def drop_source(files):
        files.pop("programs/ghost/sources/athletics.json")
        return files
    code, out, origin, c1, work = run_case(tmp, "unhandled-conflict", upstream=drop_source)
    ok("the step fails", code != 0, out[-800:])
    ok("main is exactly the upstream commit", git(origin, "rev-parse", "refs/heads/main") == c1)
    bs = branches(origin)
    ok("the collection is saved on the unpublished branch", bs == ["refs/heads/refresh-sources/123-1-unpublished"], bs)
    ok("the ::error describes an unrebased, ungated commit", "NOT rebased onto the current main" in out, out[-900:])
    if len(bs) == 1:
        files = tree_files(origin, bs[0])
        ok("the branch holds every collected file, the conflicted one included",
           files.get("programs/alpha/sources/athletics.json") == b'"alpha-v2-collected"\n'
           and files.get("programs/ghost/sources/athletics.json") == b'"ghost-v2-collected"\n'
           and files.get("public/data/rpi/current.json") == b'{"season": 2026}\n')
    ok("an ::error names the unresolved conflict", "::error" in out and "programs/ghost/sources/athletics.json" in out, out[-1200:])
    ok("the runner is not left mid-rebase", not os.path.isdir(os.path.join(work, ".git", "rebase-merge")))


def test_pruned_by_run(tmp):
    print("pruned-by-run: the run prunes a profile that main rewrote")
    def rewrite_ghost(files):
        files["public/data/programs/ghost.json"] = b'{"slug": "ghost", "source": "ghost-v1", "builtAt": "upstream-rebuild"}\n'
        return files
    code, out, origin, c1, _ = run_case(tmp, "pruned-by-run", upstream=rewrite_ghost, run_registry=["alpha", "beta"])
    files = tree_files(origin, "refs/heads/main")
    ok("the step succeeds", code == 0, out[-1500:])
    ok("published on top of main", git(origin, "rev-parse", "refs/heads/main~1") == c1)
    ok("the profile the run unpublished is gone, main's rewrite notwithstanding", "public/data/programs/ghost.json" not in files, sorted(files))
    ok("with the run's registry and collection", files.get("public/data/registry.json") == b'{"published": ["alpha", "beta"]}\n'
       and files.get("programs/alpha/sources/athletics.json") == b'"alpha-v2-collected"\n')
    ok("no sources branch", branches(origin) == [])


def test_mixed_conflict(tmp):
    print("mixed-conflict: main deletes a profile the run rewrote and a source the run modified")
    def drop_both(files):
        files = drop_ghost(files)
        files.pop("programs/ghost/sources/athletics.json")
        return files
    code, out, origin, c1, work = run_case(tmp, "mixed-conflict", upstream=drop_both)
    ok("the step fails", code != 0, out[-800:])
    ok("main is exactly the upstream commit", git(origin, "rev-parse", "refs/heads/main") == c1)
    bs = branches(origin)
    ok("the collection is saved on one refresh-sources/* branch", len(bs) == 1 and bs[0].startswith("refs/heads/refresh-sources/"), bs)
    ok("the ::error names the source conflict", "::error" in out and "programs/ghost/sources/athletics.json" in out)
    ok("the runner is not left mid-rebase", not os.path.isdir(os.path.join(work, ".git", "rebase-merge")))


def test_push_always_rejected(tmp):
    print("push-always-rejected: every push to main is refused")
    def readme(files):
        files["README.md"] = b"moved\n"
        return files
    code, out, origin, c1, _ = run_case(tmp, "push-always-rejected", upstream=readme, reject_main_push=True)
    ok("the step fails", code != 0)
    ok("main is unchanged", git(origin, "rev-parse", "refs/heads/main") == c1)
    bs = branches(origin)
    # the name carries the run id and attempt, which is what stops a re-run from pushing to a stale ref
    ok("after the retries, the collection is saved on the unpublished branch for this run",
       bs == ["refs/heads/refresh-sources/123-1-unpublished"], (bs, out[-1200:]))
    if len(bs) == 1:
        files = tree_files(origin, bs[0])
        ok("the branch holds the collected source", files.get("programs/alpha/sources/athletics.json") == b'"alpha-v2-collected"\n')
    ok("an ::error says the collection was saved, not published", "::error" in out and "refresh-sources/" in out)
    # fails if the annotation tells the operator to redo a rebase and a build that already happened (item 4)
    ok("and says the commit is rebased, rebuilt and gated", "rebased onto main, rebuilt from the stored sources and past both build and validate" in out
       and "NOT rebased" not in out, out[-1200:])


def test_deleted_registry_kept(tmp):
    print("deleted-registry-kept: main deletes a profile by hand and leaves the registry alone (#107's shape)")
    def delete_file_only(files):
        files.pop("public/data/programs/ghost.json")
        return files
    code, out, origin, c1, _ = run_case(tmp, "deleted-registry-kept", upstream=delete_file_only)
    files = tree_files(origin, "refs/heads/main")
    ok("the step succeeds", code == 0, out[-1200:])
    # the registry still publishes ghost, so the rebuild recreates it: that is the registry's call, not the step's
    ok("the profile is back, because the registry still publishes it", "public/data/programs/ghost.json" in files)
    # fails if the step claims it kept a deletion it did not keep (PR #124 review, item 1)
    ok("no annotation claims the deletion was kept", "keeping the deletion" not in out, out[-600:])
    ok("the notice says the rebuild decides", "the rebuild decides from the registry" in out, out[-900:])
    ok("and a ::warning names the profile that came back", "::warning" in out and "put back public/data/programs/ghost.json" in out, out[-900:])


def test_deletion_direction(tmp):
    print("deletion-direction: with a build that never recreates a profile, the step's own resolution shows")
    def delete_file_only(files):
        files.pop("public/data/programs/ghost.json")
        return files
    code, out, origin, c1, _ = run_case(tmp, "deletion-direction", upstream=delete_file_only, run_markers=("KEEP_ONLY_EXISTING",))
    files = tree_files(origin, "refs/heads/main")
    ok("the step succeeds", code == 0, out[-1200:])
    # fails if the conflict is resolved by KEEPING the file: the rebuild cannot recreate it here, so what the
    # step left behind is what gets published (PR #124 review, item 7)
    ok("the profile main deleted is not republished", "public/data/programs/ghost.json" not in files, sorted(files))
    ok("and the other profiles are still published and rebuilt", {"public/data/programs/alpha.json", "public/data/programs/beta.json"} <= set(files)
       and b'"builtAt": "old"' not in files["public/data/programs/alpha.json"])


def test_registry_both_sides(tmp):
    print("registry-both-sides: main and the run both change registry.json, and a profile conflicts")
    def drop_ghost_upstream(files):
        return drop_ghost(files)
    # the run writes registry.json too (it onboarded newprog), and its copy still publishes ghost, so -X theirs
    # would keep the run's registry and put main's removed program back
    code, out, origin, c1, work = run_case(tmp, "registry-both-sides", upstream=drop_ghost_upstream,
                                           run_registry=["alpha", "beta", "ghost", "newprog"])
    ok("the step fails", code != 0, out[-800:])
    ok("main is exactly the upstream commit, with its membership change intact",
       git(origin, "rev-parse", "refs/heads/main") == c1
       and tree_files(origin, c1)["public/data/registry.json"] == b'{"published": ["alpha", "beta"]}\n')
    bs = branches(origin)
    ok("the collection is saved on the unpublished branch", bs == ["refs/heads/refresh-sources/123-1-unpublished"], bs)
    if bs:
        files = tree_files(origin, bs[0])
        ok("which holds the run's collection", files.get("programs/alpha/sources/athletics.json") == b'"alpha-v2-collected"\n')
    # fails if the run's registry can silently overwrite main's (PR #124 review, item 2)
    ok("the ::error says both sides changed the registry", "::error" in out and "both changed public/data/registry.json" in out, out[-900:])
    ok("and says the collection is rebased and gated, not raw", "rebased onto main, rebuilt" in out, out[-900:])


def test_content_conflict(tmp):
    print("content-conflict: both sides change the collected RPI table")
    def move_rpi(files):
        files["public/data/rpi/current.json"] = b'{"season": 2025, "note": "upstream edit"}\n'
        return files
    code, out, origin, c1, _ = run_case(tmp, "content-conflict", upstream=move_rpi)
    files = tree_files(origin, "refs/heads/main")
    ok("the step succeeds", code == 0, out[-1200:])
    # fails if the merge strategy stops preferring the run's freshly collected data (-X theirs -> -X ours)
    ok("the run's collected RPI table wins over main's edit", files.get("public/data/rpi/current.json") == b'{"season": 2026}\n',
       files.get("public/data/rpi/current.json"))
    ok("and the run is published on top of main", git(origin, "rev-parse", "refs/heads/main~1") == c1)


def test_upstream_code_change(tmp):
    print("upstream-code-change: main changes collegedash.py mid-run (#75)")
    def new_code(files):
        files["collegedash.py"] = files["collegedash.py"].replace(b'STAMP_PREFIX="built"', b'STAMP_PREFIX="built-by-upstream-code"')
        return files
    code, out, origin, c1, _ = run_case(tmp, "upstream-code-change", upstream=new_code)
    files = tree_files(origin, "refs/heads/main")
    ok("the step succeeds", code == 0, out[-1200:])
    # fails if the rebuild after the rebase is skipped: the profiles then carry the stamp of the code the run
    # checked out hours earlier (PR #124 review, item 9)
    ok("every published profile is built by main's code", all(b'"builtAt": "built-by-upstream-code' in v
       for k, v in files.items() if k.startswith("public/data/programs/") and k != "public/data/programs/index.json"),
       [k for k, v in files.items() if k.startswith("public/data/programs/") and b"built-by-upstream-code" not in v])
    ok("main's code change survives", b'built-by-upstream-code' in files["collegedash.py"])


def test_build_gate(tmp):
    print("build-gate (#82): build fails after the rebase")
    def readme(files):
        files["README.md"] = b"moved\n"
        return files
    code, out, origin, c1, _ = run_case(tmp, "build-gate", upstream=readme, run_markers=("BUILD_FAILS",))
    ok("the step fails", code != 0)
    ok("main is exactly the upstream commit", git(origin, "rev-parse", "refs/heads/main") == c1)
    bs = branches(origin)
    ok("the collection is on the gate's per-attempt branch", bs == ["refs/heads/refresh-sources/123-1-1"], bs)
    if len(bs) == 1:
        files = tree_files(origin, bs[0])
        ok("with public/data (except rpi, registry) exactly main's", data_view(files) == data_view(tree_files(origin, c1)))
        ok("and the collected source", files.get("programs/alpha/sources/athletics.json") == b'"alpha-v2-collected"\n')
    ok("an ::error says build failed", "::error" in out and "build failed" in out)


def test_fifth_output(tmp):
    print("fifth-output (#82): build writes an output the gate does not restore, and validate fails")
    def readme(files):
        files["README.md"] = b"moved\n"
        return files
    code, out, origin, c1, _ = run_case(tmp, "fifth-output", upstream=readme, run_markers=("FIFTH_OUTPUT", "VALIDATE_FAILS"))
    ok("the step fails", code != 0)
    ok("main is exactly the upstream commit", git(origin, "rev-parse", "refs/heads/main") == c1)
    ok("nothing carrying the unrestored output is pushed anywhere", branches(origin) == [], branches(origin))
    ok("the fifth-output assertion is what stopped it", "does not match" in out, out[-1200:])


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--case", action="append", help="run only these cases (by function suffix)")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose
    print(f"step: {os.path.relpath(YML, ROOT) if YML.startswith(ROOT) else YML}; bash: {BASH}")
    tmp = tempfile.mkdtemp(prefix="refresh-step-")
    cases = [test_deleted_upstream, test_deleted_and_gated, test_deleted_registry_kept, test_deletion_direction,
             test_registry_both_sides, test_content_conflict, test_upstream_code_change, test_unrelated_upstream,
             test_unhandled_conflict, test_pruned_by_run, test_mixed_conflict, test_push_always_rejected,
             test_build_gate, test_fifth_output]
    try:
        for c in cases:
            if args.case and not any(c.__name__.endswith(x.replace("-", "_")) for x in args.case):
                continue
            c(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
