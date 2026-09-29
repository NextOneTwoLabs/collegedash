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

The stand-in `python` is a shell script on PATH: `build` writes one profile per slug in public/data/registry.json's
`programs` (heldPrograms is not read, as in the real build), except slugs listed in an UNPUBLISH marker file,
removes any other profile, and writes the three indexes; it fails when the tree holds BUILD_FAILS, and writes a
fifth output when it holds FIFTH_OUTPUT. It also writes the two review reports that live outside public/data
(data/clubs-review.json, data/schools-review.json: issues #228, #229), as the real build does. `validate` fails
when the tree holds VALIDATE_FAILS. Any other `python` command - the step's .github/scripts/merge_registry.py -
runs the real interpreter on the copy of the script the seeded repository carries, so a commit on main can
break or delete it. `sleep` is a no-op so the retry loop runs in milliseconds.

The registry has the real one's shape, as far as the step cares: `updated`, `programs` (slug, onboarded,
athletics.baseUrl and athletics.platform) and `heldPrograms`, written the way common.write_json writes it. A
run's registry change is what a refresh really writes: athletics.platform, plus `updated`, which
common.save_registry sets on every write.

Cases (issue #117 first, then the #82 gate behaviour that must not change):
  deleted-upstream        main deletes a profile the run rewrote (modify/delete). The deletion stands, the
                          run's data is rebuilt onto main and published, and nothing is left on a branch.
  deleted-and-gated       the same conflict, and validate fails on the rebuilt data. Nothing is published;
                          the collection is on refresh-sources/*, with public/data exactly as main has it
                          (the deleted profile included) apart from rpi and registry.
  deleted-registry-kept   main deletes a profile BY HAND and keeps it in the registry (the issue #107
                          shape). The rebuild puts it back, because the registry still publishes it, and
                          the step says so in a ::warning instead of claiming the deletion was kept.
  deletion-direction      the same, against a build that never recreates a deleted profile: what the step
                          leaves behind is then visible, and it must be the deletion.
  registry-both-sides     (#124, meaning changed by #132) main removes a program the run detected a platform
                          for, and its profile conflicts. The PR #124 guard refused this; the registry merge
                          now publishes it with main's membership standing and the profile not republished.
  content-conflict        both sides change public/data/rpi/current.json: `-X theirs` keeps the run's
                          collected table, which is what the whole step is built on.
  upstream-code-change    main changes collegedash.py mid-run: the published data must be the output of
                          main's code, not of the code the run built with (issue #75).
  unrelated-upstream      main changes an unrelated file. Published as before.
  unhandled-conflict      main deletes a collected SOURCE file the run modified - a conflict the step
                          must not resolve. Nothing is published, and the collection is saved on a
                          refresh-sources/* branch with an ::error saying why.
  pruned-by-run           the run's build unpublishes a profile (the UNPUBLISH marker: a refresh can no longer
                          change membership, #132) while main rewrites that profile (delete/modify, the
                          reverse direction). The deletion stands and the run publishes.
  mixed-conflict          main deletes a profile the run rewrote AND a source the run modified. One conflict is
                          not the step's to settle, so none is: the collection is saved on a branch.
  push-always-rejected    origin rejects every push to main. After the retries the collection is saved on
                          a refresh-sources/* branch instead of being dropped.
  build-gate              (#82) build fails after the rebase: collection on a branch, data as main has it.
  fifth-output            (#82) build writes a fifth output and validate fails: the fifth-output assertion
                          stops the step, nothing is pushed anywhere.
  stray-locks             (#321) a killed run left <file>.lock files beside sources, profiles and data/. With
                          the repository's real .gitignore seeded on main, none reaches main or a sources
                          branch; a control run without it shows `git add -A` would have published them.
  review-reports-previous (#235) the rebuild after the rebase reads main's published data/clubs-review.json as
                          the previous report: a key main's copy lacks is published as new, and firstSeen is
                          main's. A control run of the step without the restore publishes nothing new, as
                          every refresh did before #235. With no report on main, the rebuild writes a first one.

Issue #132, the registry merge after the rebase (the four conditions are Huatuo's plan review):
  registry-only-revert    the #132 shape: the run detects alpha's platform and main puts a collectionHold on alpha
                          mid-run, in the same hunk. Main's hold stands and the run's platform is kept. A control
                          run of the step without the merge shows today's silent revert.
  registry-same-field     both sides change alpha's platform, differently: main's value stands, with a ::warning.
  registry-identical      both sides make the same platform change and a profile conflicts (the #124 guard's
                          over-fire): published, main's registry bytes exactly.
  registry-untouched      the run does not touch the registry and main rewrites it in another format: main's
                          bytes exactly, no reformat.
  registry-unexpected     the run changes another field, or heldPrograms: nothing published, the collection on
                          refresh-sources/*, that branch the run's own commit with its registry as written and an
                          annotation saying not to merge it as is (condition 3).
  registry-held           main moves the program the run detected to heldPrograms: the detection is dropped with
                          a ::warning, and the program is not republished (condition 4).
  registry-script-fails   main's merge script crashes, or is missing: fail closed through save_collection, the
                          collection on refresh-sources/*, exit 1 (condition 1).
  registry-retry          attempt 1 merges, builds and loses the push race to a second registry edit on main;
                          attempt 2 publishes both of main's edits and the run's platform. A control that
                          re-captures pre_rebase inside the loop loses the platform (condition 2).
  registry-gates          build, then validate, fail after a merge: the sources branch carries the merged registry,
                          not the run's (condition 3).
  rebased-label           every attempt's fetch fails, so nothing was ever rebased: the final save says unrebased.
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

def extract_step(path: str, name: str = "Commit changed data", text: str | None = None) -> str:
    """The `run: |` block of the named step, dedented exactly as YAML's literal block scalar does."""
    lines = (text if text is not None else open(path, encoding="utf-8").read()).splitlines()
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
# Anything else - the step's `python .github/scripts/merge_registry.py` (#132) - runs the real interpreter, on the
# script the seeded repository carries. HARNESS_MOVE_MAIN_TO, when set, moves origin's main to that commit the first
# time validate runs, so the attempt that just rebased and built loses the push race (the registry-retry case).
FAKE_PYTHON = r'''#!/usr/bin/env bash
if [ "$1" = collegedash.py ]; then
  if [ "$2" = validate ] && [ -n "$HARNESS_MOVE_MAIN_TO" ] && [ ! -e "$HARNESS_MOVE_MAIN_FLAG" ]; then
    git -C "$HARNESS_ORIGIN" update-ref refs/heads/main "$HARNESS_MOVE_MAIN_TO" && : > "$HARNESS_MOVE_MAIN_FLAG"
  fi
  exec bash ./collegedash.py "$@"
fi
exec "$HARNESS_PYTHON" "$@"
'''

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
    # programs[] only, as build.py reads it: heldPrograms is never built. UNPUBLISH lists slugs the build skips.
    slugs=$("$HARNESS_PYTHON" -c 'import json, os
skip = open("UNPUBLISH").read().split() if os.path.exists("UNPUBLISH") else []
reg = json.load(open("public/data/registry.json", encoding="utf-8"))
print(" ".join(p["slug"] for p in reg["programs"] if p["slug"] not in skip))' | tr -d '\r')
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
    # the two review reports build() writes outside public/data (issues #228, #229), on every build.
    # The clubs report keeps just enough of clubs.Recorder's contract to see which copy the build read as
    # "previous" (issue #235): its "unmatched" keys are the published sources' contents, each as key@firstSeen.
    # firstSeen is carried from the previous report, or is HARNESS_TODAY for a key it lacks, and such a key is
    # also listed in "new".
    mkdir -p data
    prev=""
    if [ -f data/clubs-review.json ]; then prev=$(sed -n 's/.*"unmatched": "\([^"]*\)".*/\1/p' data/clubs-review.json); fi
    unmatched=""; new=""
    for s in $slugs; do
      k=$(tr -d '"\n' < "programs/$s/sources/athletics.json" 2>/dev/null || echo none)
      seen=""
      for e in $prev; do case "$e" in "$k@"*) seen=${e#*@} ;; esac; done
      if [ -z "$seen" ]; then seen=${HARNESS_TODAY:-run-day}; new="${new:+$new }$k"; fi
      unmatched="${unmatched:+$unmatched }$k@$seen"
    done
    printf '{"builtAt": "%s", "unmatched": "%s", "new": "%s"}\n' "$stamp" "$unmatched" "$new" > data/clubs-review.json
    printf '{"builtAt": "%s"}\n' "$stamp" > data/schools-review.json
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

REG = "public/data/registry.json"
MERGE_SCRIPT = ".github/scripts/merge_registry.py"
BASE_DAY, RUN_DAY = "2026-09-01", "2026-09-28"


def program(slug: str, platform: str = "auto") -> dict:
    # athletics.platform is the last line of its block, so an edit main appends after the block (a collectionHold)
    # touches the line after the run's platform line: the same hunk, as in #132
    return {"slug": slug, "onboarded": True, "athletics": {"baseUrl": f"https://{slug}.example", "platform": platform}}


def registry_doc(published=("alpha", "beta", "ghost")) -> dict:
    return {"updated": BASE_DAY, "programs": [program(s) for s in published], "heldPrograms": []}


def reg_bytes(doc: dict) -> bytes:
    """As common.write_json writes the registry."""
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode()


def reg_of(files: dict[str, bytes]) -> dict:
    return json.loads(files[REG])


def prog(doc: dict, slug: str) -> dict | None:
    return next((p for p in doc["programs"] if p["slug"] == slug), None)


def edit_registry(files: dict[str, bytes], *edits) -> dict[str, bytes]:
    doc = reg_of(files)
    for e in edits:
        e(doc)
    files[REG] = reg_bytes(doc)
    return files


def detect(*pairs):
    """What a refresh writes: athletics.platform for each (slug, platform), and `updated` (common.save_registry)."""
    def edit(doc):
        for slug, platform in pairs:
            prog(doc, slug)["athletics"]["platform"] = platform
        doc["updated"] = RUN_DAY
    return edit


def hold(slug: str):
    def edit(doc):
        prog(doc, slug)["collectionHold"] = {"reason": "owner-hold", "evidence": "harness", "since": "2026-09-20"}
    return edit


def set_platform(slug: str, platform: str):
    def edit(doc):
        prog(doc, slug)["athletics"]["platform"] = platform
    return edit


def base_files(published=("alpha", "beta", "ghost")) -> dict[str, bytes]:
    files = {"README.md": b"harness\n", REG: reg_bytes(registry_doc(published)),
             "public/data/rpi/current.json": b'{"season": 2025}\n',
             # the step runs the checkout's copy, which after the rebase is main's (#132)
             MERGE_SCRIPT: open(os.path.join(ROOT, *MERGE_SCRIPT.split("/")), "rb").read().replace(b"\r\n", b"\n")}
    for s in published:
        files[f"programs/{s}/sources/athletics.json"] = f'"{s}-v1"\n'.encode()
        files[f"public/data/programs/{s}.json"] = f'{{"slug": "{s}", "source": "{s}-v1", "builtAt": "old"}}\n'.encode()
    files["collegedash.py"] = COLLEGEDASH.encode()
    files["public/data/programs/index.json"] = b'{"builtAt": "old"}\n'
    files["public/data/commitments/index.json"] = b'{"builtAt": "old"}\n'
    files["public/data/camps/index.json"] = b'{"builtAt": "old"}\n'
    return files


def run_case(tmp: str, name: str, *, upstream, run_markers=(), reject_main_push=False, run_registry_edit=None, run_files=None,
             seed_files=None, yml_text=None, pre_markers=None, upstream2=None, break_fetch=False):
    """Returns (exit code, output, origin path, upstream sha, run clone path).

    run_registry_edit: edits the run's registry (a callable on the parsed document), before its own build.
    pre_markers: {name: text} runner-state files the stand-in build reads, there before the run's own build.
    upstream2: a second change on main, committed on top of `upstream` and moved to when attempt 1 validates.
    break_fetch: every `git pull` fails (a bad fetch URL); pushes still reach origin."""
    root = os.path.join(tmp, name)
    origin = os.path.join(root, "origin.git")
    work = os.path.join(root, "runner")
    os.makedirs(root)
    subprocess.run(["git", "init", "-q", "--bare", origin], check=True, env={**os.environ, **GIT_ENV})
    git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    c0_files = {**base_files(), **(seed_files or {})}  # seed_files: extra files main has before the run starts
    c0 = commit_files(origin, c0_files, None, "seed")
    git(origin, "update-ref", "refs/heads/main", c0)
    subprocess.run(["git", "-c", "core.autocrlf=false", "clone", "-q", origin, work], check=True, capture_output=True, env={**os.environ, **GIT_ENV})
    git(work, "config", "core.autocrlf", "false")

    bin_dir = os.path.join(root, "bin")
    os.makedirs(bin_dir)
    write_exe(os.path.join(bin_dir, "python"), FAKE_PYTHON)
    write_exe(os.path.join(bin_dir, "sleep"), "#!/usr/bin/env bash\nexit 0\n")
    env = {**os.environ, **GIT_ENV, "PATH": bin_dir + os.pathsep + os.environ.get("PATH", ""),
           "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "BUILD_ONLY": "false",
           "HARNESS_PYTHON": sys.executable.replace("\\", "/")}
    if break_fetch:
        git(work, "config", "remote.origin.pushurl", origin)
        git(work, "config", "remote.origin.url", origin + "-unreachable")

    def exclude(marker: str) -> None:  # runner state, never committed
        with open(os.path.join(work, ".git", "info", "exclude"), "a") as f:
            f.write(marker + "\n")
    for m, text in (pre_markers or {}).items():
        with open(os.path.join(work, m), "w", newline="\n") as f:
            f.write(text)
        exclude(m)

    # --- the refresh: collected sources and RPI change, then the refresh's own build rewrites every profile
    with open(os.path.join(work, "programs", "alpha", "sources", "athletics.json"), "w", newline="\n") as f:
        f.write('"alpha-v2-collected"\n')
    with open(os.path.join(work, "programs", "ghost", "sources", "athletics.json"), "w", newline="\n") as f:
        f.write('"ghost-v2-collected"\n')
    with open(os.path.join(work, "public", "data", "rpi", "current.json"), "w", newline="\n") as f:
        f.write('{"season": 2026}\n')
    for path, body in (run_files or {}).items():  # other files the collection itself writes (not build outputs)
        full = os.path.join(work, *path.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(body)
    if run_registry_edit is not None:  # the run's own registry change: a platform detection, in a real refresh
        path = os.path.join(work, *REG.split("/"))
        doc = json.loads(open(path, "rb").read())
        run_registry_edit(doc)
        with open(path, "wb") as f:
            f.write(reg_bytes(doc))
    r = subprocess.run([BASH, "-e", os.path.join(bin_dir, "python"), "collegedash.py", "build"], cwd=work, env=env, capture_output=True)
    assert r.returncode == 0, r.stderr

    # --- main moves mid-run
    up_files = upstream(dict(c0_files))
    c1 = commit_files(origin, up_files, c0, f"upstream change for {name}")
    git(origin, "update-ref", "refs/heads/main", c1)
    if upstream2 is not None:  # main moves again, once, while attempt 1 is between its rebase and its push
        c2 = commit_files(origin, upstream2(dict(up_files)), c1, f"second upstream change for {name}")
        env.update({"HARNESS_ORIGIN": origin.replace("\\", "/"), "HARNESS_MOVE_MAIN_TO": c2,
                    "HARNESS_MOVE_MAIN_FLAG": os.path.join(root, "moved").replace("\\", "/")})
    if reject_main_push:
        hooks = os.path.join(origin, "hooks")
        write_exe(os.path.join(hooks, "pre-receive"),
                  "#!/usr/bin/env bash\nwhile read old new ref; do\n  if [ \"$ref\" = refs/heads/main ]; then echo 'harness: main is protected' >&2; exit 1; fi\ndone\nexit 0\n")
    for m in run_markers:  # markers the stand-in build/validate read from the working tree after the rebase
        open(os.path.join(work, m), "w").close()
        exclude(m)  # keep the marker out of the commit: it is runner state, not data

    script = os.path.join(root, "step.sh")
    with open(script, "w", encoding="utf-8", newline="\n") as f:
        f.write(extract_step(YML, text=yml_text))  # yml_text: a variant of the workflow, for a control run
    r = subprocess.run([BASH, "-e", script], cwd=work, env=env, capture_output=True, timeout=300)
    out = (r.stdout + r.stderr).decode(errors="replace")
    return r.returncode, out, origin, c1, work


def branches(origin: str) -> list[str]:
    return [b for b in git(origin, "for-each-ref", "--format=%(refname)", "refs/heads/").splitlines() if b != "refs/heads/main"]


def data_view(files: dict[str, bytes]) -> dict[str, bytes]:
    """public/data without the collected parts (rpi, registry.json): what the #82 gate restores."""
    return {k: v for k, v in files.items() if k.startswith("public/data/") and not k.startswith("public/data/rpi/")
            and k != "public/data/registry.json"}


def expected_registry(origin: str, rev: str, *edits) -> bytes:
    """The registry at `rev` with `edits` applied, as write_json writes it: what a merge onto `rev` should publish."""
    return edit_registry(tree_files(origin, rev), *edits)[REG]


def registry_warnings(out: str) -> list[str]:
    return [l for l in out.splitlines() if l.startswith("::warning title=registry merge::")]


# ---------- the cases ----------

def drop_ghost(files):
    files.pop("public/data/programs/ghost.json")
    return edit_registry(files, lambda d: d["programs"].remove(prog(d, "ghost")))


def onboard_newprog(files):
    """main onboards a program mid-run: registry entry and sources, no profile yet (the next build writes it)."""
    files["programs/newprog/sources/athletics.json"] = b'"newprog-v1"\n'
    return edit_registry(files, lambda d: d["programs"].append(program("newprog")))


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
    # the run's registry still publishes ghost, so its build rewrites ghost.json and main's deletion really
    # conflicts (a delete/delete would not: PR #124 review, item 6). main also onboards a program in the same
    # change, with no profile yet, so the rebuild creates a profile main has no file for and the gate's restore has
    # to remove it again, which is what `rm -rf public/data/programs` before the checkout is for. (Before #132 the
    # run onboarded it; a refresh can no longer change membership.)
    code, out, origin, c1, _ = run_case(tmp, "deleted-and-gated", upstream=lambda f: onboard_newprog(drop_ghost(f)),
                                        run_markers=("VALIDATE_FAILS",))
    ok("the step fails", code != 0, out[-800:])
    ok("main is exactly the upstream commit", git(origin, "rev-parse", "refs/heads/main") == c1)
    bs = branches(origin)
    ok("the collection is on one refresh-sources/* branch", len(bs) == 1 and bs[0].startswith("refs/heads/refresh-sources/"), bs)
    if len(bs) == 1:
        files = tree_files(origin, bs[0])
        ok("the branch holds the collected source and RPI table", files.get("programs/alpha/sources/athletics.json") == b'"alpha-v2-collected"\n'
           and files.get("public/data/rpi/current.json") == b'{"season": 2026}\n')
        ok("and the program main onboarded has its sources and no profile (main has none)",
           files.get("programs/newprog/sources/athletics.json") == b'"newprog-v1"\n'
           and "public/data/programs/newprog.json" not in files, sorted(k for k in files if "newprog" in k))
        ok("and main's registry (the run did not touch it)", files.get(REG) == tree_files(origin, c1)[REG])
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
    # the run's build skips ghost (UNPUBLISH, there before the run's own build), so the run's commit deletes ghost.json
    code, out, origin, c1, _ = run_case(tmp, "pruned-by-run", upstream=rewrite_ghost, pre_markers={"UNPUBLISH": "ghost\n"})
    files = tree_files(origin, "refs/heads/main")
    ok("the step succeeds", code == 0, out[-1500:])
    ok("published on top of main", git(origin, "rev-parse", "refs/heads/main~1") == c1)
    ok("the resolution really fired: the rebase hit a conflict on the profile", "CONFLICT" in out and "public/data/programs/ghost.json" in out,
       out[-600:])
    ok("the profile the run unpublished is gone, main's rewrite notwithstanding", "public/data/programs/ghost.json" not in files, sorted(files))
    ok("with main's registry and the run's collection", files.get(REG) == tree_files(origin, c1)[REG]
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
    print("deleted-registry-kept: main deletes a profile by hand and keeps it in the registry (#107's shape)")
    def delete_file_only(files):
        files.pop("public/data/programs/ghost.json")
        # main also onboards newprog, whose profile is new to main as well: the warning must not name it
        return onboard_newprog(files)
    code, out, origin, c1, _ = run_case(tmp, "deleted-registry-kept", upstream=delete_file_only)
    files = tree_files(origin, "refs/heads/main")
    ok("the step succeeds", code == 0, out[-1200:])
    # the registry still publishes ghost, so the rebuild recreates it: that is the registry's call, not the step's
    ok("the profile is back, because the registry still publishes it", "public/data/programs/ghost.json" in files)
    # fails if the step claims it kept a deletion it did not keep (PR #124 review, item 1)
    ok("no annotation claims the deletion was kept", "keeping the deletion" not in out, out[-600:])
    ok("the notice says the rebuild decides", "the rebuild decides from the registry" in out, out[-900:])
    warn = next((l for l in out.splitlines() if "::warning" in l), "")
    ok("and a ::warning names the profile that came back", "put back public/data/programs/ghost.json" in warn, out[-900:])
    # fails if the warning lists everything new to main rather than what the resolution removed (R1)
    ok("and names nothing else: a newly onboarded program was not deleted by main",
       "newprog" not in warn and "public/data/programs/newprog.json" in tree_files(origin, "refs/heads/main"), warn)


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
    print("registry-both-sides (#124, now #132): main removes a program the run detected a platform for, and a profile conflicts")
    # main drops ghost (registry entry and profile). The run detected platforms for alpha and ghost, so both sides
    # changed registry.json and the rebase resolves ghost.json: the case the PR #124 guard refused. The merge now
    # settles it: main's membership stands, alpha's detection is kept, ghost's is dropped with a warning.
    code, out, origin, c1, _ = run_case(tmp, "registry-both-sides", upstream=drop_ghost,
                                        run_registry_edit=detect(("alpha", "sidearm"), ("ghost", "sidearm")))
    files = tree_files(origin, "refs/heads/main")
    reg = json.loads(files.get(REG) or b'{"programs": []}')
    ok("the step succeeds: the merge settles what the guard refused", code == 0, out[-1500:])
    ok("the run is published on top of main", git(origin, "rev-parse", "refs/heads/main~1") == c1)
    ok("the resolution really fired: the rebase hit a conflict on the profile", "CONFLICT" in out and "public/data/programs/ghost.json" in out,
       out[-600:])
    # fails if the run's registry can put main's removed program back (PR #124 review, item 2)
    ok("FIX main's membership change stands: ghost is not in the published registry", prog(reg, "ghost") is None,
       [p["slug"] for p in reg["programs"]])
    ok("FIX and the profile main deleted is not republished", "public/data/programs/ghost.json" not in files, sorted(files))
    ok("the registry is exactly main's plus the run's platform for alpha",
       files.get(REG) == expected_registry(origin, c1, detect(("alpha", "sidearm"))), files.get(REG, b"")[:400])
    warn = registry_warnings(out)
    ok("a ::warning says ghost's detection was dropped because main removed it",
       len(warn) == 1 and "ghost" in warn[0] and "removed it from programs" in warn[0], warn)
    ok("no ::warning claims the rebuild put a profile back", "put back" not in out, out[-900:])
    ok("no sources branch", branches(origin) == [], branches(origin))


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


REFUSED = "data/camps-refused-hosts.json"
REFUSED_BODY = json.dumps({"camps.example.com": {"firstAt": "2026-09-24", "status": 403}}, indent=2).encode() + b"\n"


def test_refused_hosts_file(tmp):
    print("refused-hosts-file (#284): the collection adds data/camps-refused-hosts.json, which upstream lacks")
    def readme(files):
        files["README.md"] = b"moved\n"
        return files
    # gated: validate fails. The file is collected data, not a build output, so the gate's restore must
    # leave it alone: it travels with the collection to the sources branch, and main does not get it
    code, out, origin, c1, _ = run_case(tmp, "refused-gated", upstream=readme, run_markers=("VALIDATE_FAILS",),
                                        run_files={REFUSED: REFUSED_BODY})
    ok("gated: the step fails", code != 0, out[-800:])
    ok("gated: main is exactly the upstream commit", git(origin, "rev-parse", "refs/heads/main") == c1)
    bs = branches(origin)
    ok("gated: one sources branch", len(bs) == 1, bs)
    if len(bs) == 1:
        # fails if the file joins the tolerant-restore list (the restore would delete it from the branch)
        ok("FIX gated: the sources branch carries the refused-hosts file", tree_files(origin, bs[0]).get(REFUSED) == REFUSED_BODY,
           sorted(tree_files(origin, bs[0]))[:20])
    ok("gated: main does not have it", REFUSED not in tree_files(origin, "refs/heads/main"))
    # happy path: published with the run's collection
    code, out, origin, c1, _ = run_case(tmp, "refused-published", upstream=readme, run_files={REFUSED: REFUSED_BODY})
    ok("published: the step succeeds", code == 0, out[-1500:])
    ok("FIX published: main gets the refused-hosts file", tree_files(origin, "refs/heads/main").get(REFUSED) == REFUSED_BODY)
    ok("published: no sources branch", branches(origin) == [])


def test_review_reports(tmp):
    print("review-reports (#228, #229): build writes data/*-review.json outside public/data, and validate fails")
    # Upstream has never built a review report. The gate's restore must not fail on the missing paths (a
    # `git checkout` naming a path the commit lacks fails outright), and this run's copies must not reach
    # the sources-only branch: the branch holds "everything build() writes exactly as main has it".
    def readme(files):
        files["README.md"] = b"moved\n"
        return files
    code, out, origin, c1, _ = run_case(tmp, "review-reports-absent", upstream=readme, run_markers=("VALIDATE_FAILS",))
    ok("absent upstream: the step fails", code != 0)
    ok("absent upstream: main is exactly the upstream commit", git(origin, "rev-parse", "refs/heads/main") == c1)
    bs = branches(origin)
    ok("absent upstream: the collection is on one sources branch", len(bs) == 1, bs)
    if len(bs) == 1:
        files = tree_files(origin, bs[0])
        ok("absent upstream: neither review report is on the branch",
           not any(k.startswith("data/") and k.endswith("-review.json") for k in files), sorted(files))
        ok("absent upstream: public/data is exactly main's", data_view(files) == data_view(tree_files(origin, c1)))
    ok("absent upstream: the restore itself did not fail the step", "could not then be restored" not in out, out[-1500:])

    # Upstream carries both reports (a previous build published them): the branch must hold upstream's
    # copies, not this run's.
    def with_reports(files):
        files["README.md"] = b"moved\n"
        files["data/clubs-review.json"] = b'{"builtAt": "upstream"}\n'
        files["data/schools-review.json"] = b'{"builtAt": "upstream"}\n'
        return files
    code, out, origin, c1, _ = run_case(tmp, "review-reports-present", upstream=with_reports, run_markers=("VALIDATE_FAILS",))
    ok("present upstream: the step fails", code != 0)
    ok("present upstream: main is exactly the upstream commit", git(origin, "rev-parse", "refs/heads/main") == c1)
    bs = branches(origin)
    ok("present upstream: the collection is on one sources branch", len(bs) == 1, bs)
    if len(bs) == 1:
        files = tree_files(origin, bs[0])
        ok("present upstream: both review reports are upstream's copies",
           files.get("data/clubs-review.json") == b'{"builtAt": "upstream"}\n'
           and files.get("data/schools-review.json") == b'{"builtAt": "upstream"}\n',
           {k: v for k, v in files.items() if k.startswith("data/")})

    # And on the success path the run's own reports are published with the rest of the build.
    code, out, origin, c1, _ = run_case(tmp, "review-reports-published", upstream=readme)
    files = tree_files(origin, "refs/heads/main")
    ok("success: the step succeeds", code == 0, out[-1500:])
    ok("success: the run's review reports are published on main",
       b'"builtAt": "built-' in files.get("data/clubs-review.json", b"")
       and b'"builtAt": "built-' in files.get("data/schools-review.json", b""), sorted(files))


# Where collect/common.py's _locked() would leave a lock behind if the run holding it were killed: beside a
# collected source, a published profile, and a collected file outside public/data.
STRAY_LOCKS = ("programs/alpha/sources/athletics.json.lock", "public/data/programs/alpha.json.lock",
               "data/camps-refused-hosts.json.lock")


def test_stray_locks(tmp):
    print("stray-locks (#321): a killed run left <file>.lock files in the tree")
    gitignore = open(os.path.join(ROOT, ".gitignore"), "rb").read()
    tracked = [p for p in git(ROOT, "ls-files").splitlines() if p.endswith(".lock")]
    ok("nothing tracked in this repository is named *.lock, so ignoring *.lock hides nothing real", tracked == [], tracked)

    def readme(files):
        files["README.md"] = b"moved\n"
        return files
    locks = {p: b"" for p in STRAY_LOCKS}
    # control: without the repository's .gitignore, the step's `git add -A` publishes the locks. This is the
    # bug, and it shows the checks below can fail
    code, out, origin, c1, _ = run_case(tmp, "stray-locks-control", upstream=readme, run_files=locks)
    main_files = tree_files(origin, "refs/heads/main")
    ok("control: the step succeeds", code == 0, out[-1500:])
    ok("control: without .gitignore the locks reach main", all(p in main_files for p in STRAY_LOCKS),
       [p for p in STRAY_LOCKS if p not in main_files])

    # published: main carries the repository's real .gitignore
    code, out, origin, c1, work = run_case(tmp, "stray-locks-published", upstream=readme, run_files=locks,
                                           seed_files={".gitignore": gitignore})
    main_files = tree_files(origin, "refs/heads/main")
    ok("published: the step succeeds", code == 0, out[-1500:])
    ok("published: the run is published", git(origin, "rev-parse", "refs/heads/main~1") == c1
       and main_files.get("programs/alpha/sources/athletics.json") == b'"alpha-v2-collected"\n')
    ok("FIX published: no stray lock reaches main", not any(p.endswith(".lock") for p in main_files),
       [p for p in main_files if p.endswith(".lock")])
    ok("published: the locks were really there when the step ran", all(os.path.exists(os.path.join(work, *p.split("/")))
       for p in STRAY_LOCKS))

    # gated: validate fails and the collection goes to a sources branch, which must not carry them either
    code, out, origin, c1, _ = run_case(tmp, "stray-locks-gated", upstream=readme, run_files=locks,
                                        run_markers=("VALIDATE_FAILS",), seed_files={".gitignore": gitignore})
    ok("gated: the step fails", code != 0, out[-800:])
    bs = branches(origin)
    ok("gated: one sources branch", len(bs) == 1, bs)
    if len(bs) == 1:
        files = tree_files(origin, bs[0])
        ok("FIX gated: no stray lock is on the sources branch", not any(p.endswith(".lock") for p in files),
           [p for p in files if p.endswith(".lock")])
        ok("gated: the branch still carries the collection", files.get("programs/alpha/sources/athletics.json") == b'"alpha-v2-collected"\n')


def without_report_restore(yml: str) -> tuple[str, int]:
    """The workflow minus the #235 restore before the rebuild (the one in publish_sources_only stays)."""
    return re.subn(r'( *)for report in data/clubs-review\.json data/schools-review\.json; do\n'
                   r'\1  git checkout FETCH_HEAD -- "\$report" 2>/dev/null \|\| rm -f "\$report"\n'
                   r'\1done\n(\1if ! python collegedash\.py build; then\n)', r"\2", yml)


def report_fields(files: dict[str, bytes]) -> tuple[dict[str, str], list[str]]:
    """data/clubs-review.json as the stand-in writes it: {key: firstSeen}, and the keys marked new."""
    doc = json.loads(files.get("data/clubs-review.json", b"{}") or b"{}")
    seen = dict(e.split("@", 1) for e in (doc.get("unmatched") or "").split())
    return seen, (doc.get("new") or "").split()


def test_review_reports_previous(tmp):
    print("review-reports-previous (#235): the rebuild reads main's published report as the previous one")
    # main's report before the run: beta's key, first seen day-0. While the run collects, main moves and its
    # report now knows alpha's collected key too (first seen day-main) and has beta at day-main. The run
    # collects alpha-v2-collected and ghost-v2-collected; its own first build marks both new.
    seed = {"data/clubs-review.json": b'{"builtAt": "old", "unmatched": "beta-v1@day-0", "new": ""}\n'}

    def main_moves(files):
        files["README.md"] = b"moved\n"
        files["data/clubs-review.json"] = (b'{"builtAt": "main", "unmatched": "alpha-v2-collected@day-main beta-v1@day-main", '
                                           b'"new": ""}\n')
        return files
    code, out, origin, c1, _ = run_case(tmp, "review-previous", upstream=main_moves, seed_files=seed)
    seen, new = report_fields(tree_files(origin, "refs/heads/main"))
    ok("the step succeeds", code == 0, out[-1500:])
    ok("FIX a key main's report lacks is published as new", new == ["ghost-v2-collected"], (new, seen))
    ok("FIX and dated the run's day", seen.get("ghost-v2-collected") == "run-day", seen)
    ok("FIX a key main's report has is not new, and keeps main's firstSeen", "alpha-v2-collected" not in new
       and seen.get("alpha-v2-collected") == "day-main", (new, seen))
    ok("FIX firstSeen of an older key is main's current one, not the copy the run started from",
       seen.get("beta-v1") == "day-main", seen)

    # control: the same run through the step without the restore reads the run's own first-build copy
    text, n = without_report_restore(open(YML, encoding="utf-8").read())
    ok("control: the restore before the rebuild is found exactly once", n == 1, n)
    code, out, origin, c1, _ = run_case(tmp, "review-previous-control", upstream=main_moves, seed_files=seed, yml_text=text)
    seen, new = report_fields(tree_files(origin, "refs/heads/main"))
    ok("control: the step succeeds", code == 0, out[-1500:])
    ok("control: without it nothing is new (the 0-new refreshes on main before #235)", new == [], (new, seen))

    # main has no report yet: the restore deletes the run's copy and the build writes a first report
    def main_moves_no_report(files):
        files["README.md"] = b"moved\n"
        return files
    code, out, origin, c1, _ = run_case(tmp, "review-previous-absent", upstream=main_moves_no_report)
    seen, new = report_fields(tree_files(origin, "refs/heads/main"))
    ok("absent on main: the step succeeds", code == 0, out[-1500:])
    ok("absent on main: a first report, every key new", sorted(new) == ["alpha-v2-collected", "beta-v1", "ghost-v2-collected"],
       (new, seen))


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


# ---------- issue #132: the registry merge ----------

UNPUBLISHED = "refs/heads/refresh-sources/123-1-unpublished"


def without_registry_merge(yml: str) -> tuple[str, int]:
    """The workflow minus the #132 registry merge after the rebase: the step as it behaved before."""
    return re.subn(r"( *)if ! merge_base=\$\(git merge-base [^\n]*\n(?:\1   [^\n]*\n)*?\1  save_collection [^\n]*\"registry\" [^\n]*\n\1fi\n",
                   "", yml)


def recapturing_pre_rebase(yml: str) -> tuple[str, int]:
    """The workflow with pre_rebase re-captured at the top of every attempt: what plan review condition 2 forbids."""
    return re.subn(r"( *)for attempt in 1 2 3; do\n", lambda m: m.group(0) + m.group(1) + "  pre_rebase=$(git rev-parse HEAD)\n", yml)


def test_registry_only_revert(tmp):
    print("registry-only-revert (#132): the run detects alpha's platform while main puts a hold on alpha, in the same hunk")
    def hold_alpha(files):
        return edit_registry(files, hold("alpha"))
    code, out, origin, c1, _ = run_case(tmp, "registry-only-revert", upstream=hold_alpha, run_registry_edit=detect(("alpha", "sidearm")))
    files = tree_files(origin, "refs/heads/main")
    reg = json.loads(files.get(REG) or b'{"programs": []}')
    alpha = prog(reg, "alpha") or {}
    ok("the step succeeds", code == 0, out[-1500:])
    ok("the run is published on top of main", git(origin, "rev-parse", "refs/heads/main~1") == c1)
    # -X theirs settles a content conflict silently, so that the two edits really overlap is shown by the control
    # below, where main's hold is lost
    ok("FIX main's hold stands", "collectionHold" in alpha, alpha)
    ok("and the run's platform is kept", alpha.get("athletics", {}).get("platform") == "sidearm", alpha)
    ok("the registry is exactly main's plus the run's platform and `updated`, as write_json writes it",
       files.get(REG) == expected_registry(origin, c1, detect(("alpha", "sidearm"))), files.get(REG, b"")[:400])
    ok("no registry ::warning: nothing clashed", registry_warnings(out) == [], registry_warnings(out))
    ok("the merge says what it applied", "athletics.platform for alpha" in out, out[-900:])
    ok("no sources branch", branches(origin) == [], branches(origin))

    # control: the step without the merge publishes the -X theirs registry, and main's hold silently disappears
    text, n = without_registry_merge(open(YML, encoding="utf-8").read())
    ok("control: the registry merge is found exactly once", n == 1, n)
    code, out, origin, c1, _ = run_case(tmp, "registry-only-revert-control", upstream=hold_alpha,
                                        run_registry_edit=detect(("alpha", "sidearm")), yml_text=text)
    reg = json.loads(tree_files(origin, "refs/heads/main").get(REG) or b'{"programs": []}')
    ok("control: the step succeeds, silently", code == 0 and "::warning" not in out and "::error" not in out, out[-1500:])
    ok("control: main's hold is reverted (the #132 bug)", "collectionHold" not in (prog(reg, "alpha") or {}), prog(reg, "alpha"))
    ok("control: while the run's platform is published", (prog(reg, "alpha") or {}).get("athletics", {}).get("platform") == "sidearm",
       prog(reg, "alpha"))


def test_registry_same_field(tmp):
    print("registry-same-field (#132): both sides change alpha's platform, differently")
    code, out, origin, c1, _ = run_case(tmp, "registry-same-field", upstream=lambda f: edit_registry(f, set_platform("alpha", "presto")),
                                        run_registry_edit=detect(("alpha", "sidearm")))
    files = tree_files(origin, "refs/heads/main")
    ok("the step succeeds", code == 0, out[-1500:])
    ok("main's value stands: the registry is main's, byte for byte", files.get(REG) == tree_files(origin, c1)[REG], files.get(REG, b"")[:400])
    warn = registry_warnings(out)
    ok("a ::warning names alpha and says main's value stands", len(warn) == 1 and "alpha" in warn[0] and "Main's value stands" in warn[0], warn)
    ok("no sources branch", branches(origin) == [], branches(origin))


def test_registry_identical(tmp):
    print("registry-identical (#132): both sides make the same platform change, and a profile conflicts (the #124 over-fire)")
    def same_and_drop(files):
        return edit_registry(drop_ghost(files), set_platform("alpha", "sidearm"))
    code, out, origin, c1, _ = run_case(tmp, "registry-identical", upstream=same_and_drop, run_registry_edit=detect(("alpha", "sidearm")))
    files = tree_files(origin, "refs/heads/main")
    ok("the step succeeds: identical edits are not a conflict to refuse", code == 0, out[-1500:])
    ok("the resolution fired, which is what made the #124 guard refuse it", "CONFLICT" in out and "public/data/programs/ghost.json" in out)
    ok("the registry is main's, byte for byte", files.get(REG) == tree_files(origin, c1)[REG], files.get(REG, b"")[:400])
    ok("no registry ::warning", registry_warnings(out) == [], registry_warnings(out))
    ok("no sources branch", branches(origin) == [], branches(origin))


def test_registry_untouched(tmp):
    print("registry-untouched (#132): the run does not touch the registry; main rewrites it in another format")
    def compact(files):
        doc = reg_of(edit_registry(files, hold("beta")))
        files[REG] = (json.dumps(doc) + "\n").encode()  # one line: not write_json's format
        return files
    code, out, origin, c1, _ = run_case(tmp, "registry-untouched", upstream=compact)
    files = tree_files(origin, "refs/heads/main")
    ok("the step succeeds", code == 0, out[-1500:])
    # fails if the merge re-serialises main's registry when the run had nothing to add
    ok("main's registry bytes exactly, not reformatted", files.get(REG) == tree_files(origin, c1)[REG], files.get(REG, b"")[:200])
    ok("the merge says it applied nothing", "applied no platform of its own" in out, out[-900:])


def test_registry_unexpected(tmp):
    print("registry-unexpected (#132): the run changes a registry field a refresh must not")
    def base_url(doc):
        detect(("alpha", "sidearm"))(doc)
        prog(doc, "alpha")["athletics"]["baseUrl"] = "https://elsewhere.example"
    def held(doc):
        doc["heldPrograms"].append({**program("dropped"), "hold": {"reason": "not-in-directory"}})
    for label, edit, named in (("field", base_url, "alpha's athletics.baseUrl"), ("heldPrograms", held, "`heldPrograms`")):
        code, out, origin, c1, _ = run_case(tmp, f"registry-unexpected-{label}", upstream=lambda f: edit_registry(f, hold("beta")),
                                            run_registry_edit=edit)
        c0 = git(origin, "rev-parse", f"{c1}~1")
        run_reg = registry_doc()
        edit(run_reg)
        ok(f"{label}: the step fails", code == 1, out[-800:])
        ok(f"{label}: main is exactly the upstream commit", git(origin, "rev-parse", "refs/heads/main") == c1)
        bs = branches(origin)
        ok(f"{label}: the collection is saved on the unpublished branch", bs == [UNPUBLISHED], bs)
        ok(f"{label}: the merge's ::error names what the run changed", any(l.startswith("::error title=registry merge::") and named in l
                                                                           for l in out.splitlines()), out[-1500:])
        if bs == [UNPUBLISHED]:
            files = tree_files(origin, bs[0])
            # condition 3: the branch keeps the run's registry as the run wrote it, for a human to inspect
            ok(f"FIX {label}: the branch's registry is the run's, exactly as written", files.get(REG) == reg_bytes(run_reg),
               files.get(REG, b"")[:300])
            ok(f"{label}: the branch is the run's own commit, not rebased", git(origin, "rev-parse", f"{bs[0]}~1") == c0)
            ok(f"{label}: and holds the collection", files.get("programs/alpha/sources/athletics.json") == b'"alpha-v2-collected"\n')
        ok(f"FIX {label}: the ::error says main's registry stands and not to merge the branch as is",
           "MAIN'S REGISTRY STANDS" in out and f"Do NOT merge refresh-sources/123-1-unpublished or push it as it stands" in out, out[-1500:])
        ok(f"{label}: and never that only the push failed", "everything except the push to main succeeded" not in out)


def test_registry_held(tmp):
    print("registry-held (#132, condition 4): main moves the program the run detected to heldPrograms")
    def move_alpha(files):
        files.pop("public/data/programs/alpha.json")
        def move(doc):
            p = prog(doc, "alpha")
            doc["programs"].remove(p)
            doc["heldPrograms"].append({**p, "hold": {"reason": "not-in-directory", "since": "2026-09-20"}})
        return edit_registry(files, move)
    code, out, origin, c1, _ = run_case(tmp, "registry-held", upstream=move_alpha,
                                        run_registry_edit=detect(("alpha", "sidearm"), ("beta", "sidearm")))
    files = tree_files(origin, "refs/heads/main")
    reg = json.loads(files.get(REG) or b'{"programs": [], "heldPrograms": []}')
    ok("the step succeeds", code == 0, out[-1500:])
    ok("FIX alpha stays held, with main's platform, and is not back in programs",
       prog(reg, "alpha") is None and [p["athletics"]["platform"] for p in reg["heldPrograms"] if p["slug"] == "alpha"] == ["auto"],
       reg.get("heldPrograms"))
    ok("FIX and its profile is not republished", "public/data/programs/alpha.json" not in files, sorted(files))
    ok("the registry is main's plus beta's platform", files.get(REG) == expected_registry(origin, c1, detect(("beta", "sidearm"))),
       files.get(REG, b"")[:400])
    warn = registry_warnings(out)
    ok("a ::warning says alpha's detection was dropped because main held it",
       len(warn) == 1 and "alpha" in warn[0] and "moved it to heldPrograms" in warn[0], warn)
    ok("no sources branch", branches(origin) == [], branches(origin))


def test_registry_script_fails(tmp):
    print("registry-script-fails (#132, condition 1): main's merge script crashes, or is missing")
    def crash(files):
        files[MERGE_SCRIPT] = b'raise RuntimeError("harness: merge_registry crashed")\n'
        return files
    def missing(files):
        files.pop(MERGE_SCRIPT)
        return files
    for label, upstream, edit in (("crashed", crash, detect(("alpha", "sidearm"))), ("missing", missing, None)):
        code, out, origin, c1, _ = run_case(tmp, f"registry-script-{label}", upstream=upstream, run_registry_edit=edit)
        ok(f"{label}: the step exits 1", code == 1, out[-1200:])
        ok(f"{label}: main is exactly the upstream commit", git(origin, "rev-parse", "refs/heads/main") == c1)
        bs = branches(origin)
        # fails if the failure goes through errexit: the step would then stop with the collection only on the runner
        ok(f"FIX {label}: the collection is on refresh-sources/*", bs == [UNPUBLISHED], (bs, out[-1200:]))
        if bs == [UNPUBLISHED]:
            ok(f"{label}: which holds the collected source", tree_files(origin, bs[0]).get("programs/alpha/sources/athletics.json")
               == b'"alpha-v2-collected"\n')
            ok(f"{label}: and is the run's own commit, not rebased", git(origin, "rev-parse", f"{bs[0]}~1") == git(origin, "rev-parse", f"{c1}~1"))
        ok(f"{label}: save_collection said so", "::error title=refresh::The registry merge after the rebase" in out
           and "NOTHING WAS PUBLISHED" in out, out[-1200:])


def test_registry_retry(tmp):
    print("registry-retry (#132, condition 2): attempt 1 loses the push race to a second registry edit on main")
    # main's first change holds beta and sets alpha's platform by hand; the second, landing while attempt 1 validates,
    # holds ghost and puts alpha's platform back. Measured against the run's own base, main changed alpha's platform
    # not at all, so the run's detection applies. Re-capturing pre_rebase after attempt 1 would compare against
    # attempt 1's merged registry instead, where main's hand-set value had won, and lose it.
    def first(files):
        return edit_registry(files, hold("beta"), set_platform("alpha", "presto"))
    def second(files):
        return edit_registry(files, hold("ghost"), set_platform("alpha", "auto"))
    code, out, origin, c1, _ = run_case(tmp, "registry-retry", upstream=first, upstream2=second, run_registry_edit=detect(("alpha", "sidearm")))
    c2 = git(origin, "rev-parse", "refs/heads/main~1")
    files = tree_files(origin, "refs/heads/main")
    reg = json.loads(files.get(REG) or b'{"programs": []}')
    ok("the step succeeds", code == 0, out[-1500:])
    ok("attempt 1 merged, built and lost the push race", "attempt 1 did not publish" in out
       and "Main's value stands" in out, out[-2000:])
    ok("published on top of main's second change", git(origin, "rev-parse", f"{c2}~1") == c1, (c1, c2))
    ok("FIX both of main's edits stand", "collectionHold" in (prog(reg, "beta") or {}) and "collectionHold" in (prog(reg, "ghost") or {}),
       reg)
    ok("FIX and the run's platform is published", (prog(reg, "alpha") or {}).get("athletics", {}).get("platform") == "sidearm", prog(reg, "alpha"))
    ok("the registry is exactly main's second change plus the run's platform",
       files.get(REG) == expected_registry(origin, c2, detect(("alpha", "sidearm"))), files.get(REG, b"")[:400])
    step = extract_step(YML)
    ok("pre_rebase is assigned once, before the retry loop", step.count("pre_rebase=") == 1
       and step.index("pre_rebase=") < step.index("for attempt in 1 2 3"), step.count("pre_rebase="))

    # control: re-capturing pre_rebase inside the loop makes attempt 2 treat attempt 1's merge as the run's registry
    text, n = recapturing_pre_rebase(open(YML, encoding="utf-8").read())
    ok("control: the loop is found exactly once", n == 1, n)
    code, out, origin, c1, _ = run_case(tmp, "registry-retry-control", upstream=first, upstream2=second,
                                        run_registry_edit=detect(("alpha", "sidearm")), yml_text=text)
    reg = json.loads(tree_files(origin, "refs/heads/main").get(REG) or b'{"programs": []}')
    ok("control: the step succeeds", code == 0, out[-1500:])
    ok("control: the run's platform is lost", (prog(reg, "alpha") or {}).get("athletics", {}).get("platform") == "auto", prog(reg, "alpha"))


def test_registry_gates(tmp):
    print("registry-gates (#132, condition 3): build or validate fails after a merge")
    def hold_alpha(files):
        return edit_registry(files, hold("alpha"))
    for marker, label in (("BUILD_FAILS", "build"), ("VALIDATE_FAILS", "validate")):
        code, out, origin, c1, _ = run_case(tmp, f"registry-gate-{label}", upstream=hold_alpha, run_markers=(marker,),
                                            run_registry_edit=detect(("alpha", "sidearm")))
        ok(f"{label}: the step fails", code != 0, out[-800:])
        ok(f"{label}: main is exactly the upstream commit", git(origin, "rev-parse", "refs/heads/main") == c1)
        bs = branches(origin)
        ok(f"{label}: the collection is on the gate's per-attempt branch", bs == ["refs/heads/refresh-sources/123-1-1"], bs)
        if len(bs) == 1:
            files = tree_files(origin, bs[0])
            ok(f"FIX {label}: the branch carries the merged registry: main's hold and the run's platform",
               files.get(REG) == expected_registry(origin, c1, detect(("alpha", "sidearm"))), files.get(REG, b"")[:400])
            ok(f"{label}: with public/data (except rpi, registry) exactly main's", data_view(files) == data_view(tree_files(origin, c1)))
        ok(f"{label}: the ::error says the branch holds the merged registry", "never the run's raw copy" in out, out[-1500:])


def test_rebased_label(tmp):
    print("rebased-label (#132): every attempt's fetch fails, so no attempt ever rebased")
    def readme(files):
        files["README.md"] = b"moved\n"
        return files
    code, out, origin, c1, _ = run_case(tmp, "rebased-label", upstream=readme, break_fetch=True)
    c0 = git(origin, "rev-parse", f"{c1}~1")
    ok("the step fails", code == 1, out[-800:])
    ok("main is unchanged", git(origin, "rev-parse", "refs/heads/main") == c1)
    bs = branches(origin)
    ok("the collection is on the unpublished branch", bs == [UNPUBLISHED], (bs, out[-1200:]))
    if bs == [UNPUBLISHED]:
        ok("which is the run's own commit, on the commit it started from", git(origin, "rev-parse", f"{bs[0]}~1") == c0)
    # fails if the final save still calls a commit that never rebased "rebased, rebuilt and gated"
    ok("FIX the ::error says the commit is NOT rebased", "NOT rebased onto the current main" in out
       and "everything except the push to main succeeded" not in out, out[-1500:])


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
             test_build_gate, test_fifth_output, test_review_reports,
             test_refused_hosts_file, test_stray_locks, test_review_reports_previous,
             test_registry_only_revert, test_registry_same_field, test_registry_identical, test_registry_untouched,
             test_registry_unexpected, test_registry_held, test_registry_script_fails, test_registry_retry,
             test_registry_gates, test_rebased_label]
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
