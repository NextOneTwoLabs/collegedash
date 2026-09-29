"""Offline tests for .github/scripts/merge_registry.py, the refresh's registry merge (issue #132).

    python tests/merge_registry_test.py            # every case
    python tests/merge_registry_test.py --verbose  # print every check, not only the failures

merge() is tested on small registries built here and on this repository's own public/data/registry.json, whose
output must be byte-identical to what collect/common.py's write_json writes. The command line is tested once in
a scratch git repository under a temporary directory. The step itself, with the merge in place, is tested by
tests/refresh_commit_step_test.py. Nothing touches this repository's git state or any remote.
"""

from __future__ import annotations

import argparse
import copy
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".github", "scripts"))
sys.path.insert(0, ROOT)
import merge_registry as mr  # noqa: E402
from collect import common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail="") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:600]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def program(slug, platform="auto", **extra):
    return {"slug": slug, "onboarded": True, "athletics": {"baseUrl": f"https://{slug}.example", "platform": platform}, **extra}


def doc(*programs, held=(), updated="2026-09-01"):
    return {"updated": updated, "programs": list(programs), "heldPrograms": list(held)}


def b(d) -> bytes:
    return mr.dumps(d)


def find(d, slug):
    return next((p for p in d["programs"] if p["slug"] == slug), None)


def base_doc():
    return doc(program("alpha"), program("beta"), program("ghost"))


def edited(d, *edits):
    d = copy.deepcopy(d)
    for e in edits:
        e(d)
    return d


def platform(slug, value):
    def e(d):
        find(d, slug)["athletics"]["platform"] = value
    return e


def updated(day):
    def e(d):
        d["updated"] = day
    return e


def unexpected(base, main, run) -> str | None:
    """The Unexpected message, or None when the merge did not refuse."""
    try:
        mr.merge(base, main, run)
    except mr.Unexpected as e:
        return str(e)
    return None


# ---------- the rules ----------

def test_run_untouched():
    print("run-untouched: the run's registry bytes equal base's")
    base = b(base_doc())
    main = (json.dumps(edited(base_doc(), platform("beta", "presto"))) + "\n").encode()  # not write_json's format
    out, warn, applied = mr.merge(base, main, base)
    ok("main's bytes, exactly, whatever their format", out == main)
    ok("no warnings, nothing applied", warn == [] and applied == [])
    ok("even when main does not parse: nothing of the run's to apply", mr.merge(base, b"{not json", base)[0] == b"{not json")


def test_applied():
    print("applied: the run changed a platform main left alone")
    base = base_doc()
    run = edited(base, platform("alpha", "sidearm"), updated("2026-09-28"))
    main = edited(base, lambda d: find(d, "beta").__setitem__("collectionHold", {"reason": "owner-hold"}))
    out, warn, applied = mr.merge(b(base), b(main), b(run))
    ok("main's edit and the run's platform, as write_json writes them",
       out == b(edited(main, platform("alpha", "sidearm"), updated("2026-09-28"))), out[:300])
    ok("applied names alpha, no warnings", applied == ["alpha"] and warn == [], (applied, warn))


def test_updated():
    print("updated: main's unless main left it alone and a platform was applied")
    base = base_doc()
    run = edited(base, platform("alpha", "sidearm"), updated("2026-09-28"))
    main = edited(base, updated("2026-09-27"), lambda d: d["programs"].append(program("newprog")))
    out = json.loads(mr.merge(b(base), b(main), b(run))[0])
    ok("main changed it: main's stands", out["updated"] == "2026-09-27", out["updated"])
    main = edited(base, platform("alpha", "presto"))
    out, warn, applied = mr.merge(b(base), b(main), b(run))
    ok("nothing applied: main's bytes, main's date", out == b(main) and json.loads(out)["updated"] == "2026-09-01")
    run = edited(base, updated("2026-09-28"))
    ok("a run that changed only `updated` is not refused, and publishes main's bytes", mr.merge(b(base), b(main), b(run))[0] == b(main))


def test_main_adds():
    print("main-adds: main onboarded a program mid-run")
    base = base_doc()
    run = edited(base, platform("ghost", "sidearm"))
    main = edited(base, lambda d: d["programs"].insert(1, program("newprog")))
    out = json.loads(mr.merge(b(base), b(main), b(run))[0])
    ok("main's list, the new program included, in main's order", [p["slug"] for p in out["programs"]] == ["alpha", "newprog", "beta", "ghost"])
    ok("and the run's platform applied by slug", find(out, "ghost")["athletics"]["platform"] == "sidearm")


def test_main_removes():
    print("main-removes: main removed a program the run re-detected")
    base = base_doc()
    run = edited(base, platform("ghost", "sidearm"), platform("alpha", "sidearm"))
    main = edited(base, lambda d: d["programs"].remove(find(d, "ghost")))
    out, warn, applied = mr.merge(b(base), b(main), b(run))
    doc_out = json.loads(out)
    ok("ghost is not put back", find(doc_out, "ghost") is None, [p["slug"] for p in doc_out["programs"]])
    ok("alpha's detection is applied", applied == ["alpha"] and find(doc_out, "alpha")["athletics"]["platform"] == "sidearm")
    ok("one warning, naming ghost as removed", len(warn) == 1 and "ghost" in warn[0] and "removed it from programs" in warn[0], warn)


def test_main_holds():
    print("main-holds: main moved the program the run detected to heldPrograms (condition 4)")
    base = base_doc()
    run = edited(base, platform("alpha", "sidearm"))

    def move(d):
        p = find(d, "alpha")
        d["programs"].remove(p)
        d["heldPrograms"].append({**p, "hold": {"reason": "not-in-directory"}})
    main = edited(base, move)
    out, warn, applied = mr.merge(b(base), b(main), b(run))
    ok("main's registry, byte for byte: the held copy keeps main's platform", out == b(main))
    ok("one warning, saying main held it", len(warn) == 1 and "alpha" in warn[0] and "moved it to heldPrograms" in warn[0], warn)
    ok("nothing applied", applied == [])


def test_main_reorders():
    print("main-reorders: main reordered the programs")
    base = base_doc()
    run = edited(base, platform("beta", "sidearm"))
    main = edited(base, lambda d: d["programs"].reverse())
    out = json.loads(mr.merge(b(base), b(main), b(run))[0])
    ok("main's order", [p["slug"] for p in out["programs"]] == ["ghost", "beta", "alpha"])
    ok("the platform applied to the right program", find(out, "beta")["athletics"]["platform"] == "sidearm"
       and find(out, "alpha")["athletics"]["platform"] == "auto")


def test_clash_and_identical():
    print("clash: both sides changed the same platform")
    base = base_doc()
    run = edited(base, platform("alpha", "sidearm"))
    main = edited(base, platform("alpha", "presto"))
    out, warn, applied = mr.merge(b(base), b(main), b(run))
    ok("different values: main's stands, byte for byte", out == b(main))
    ok("with one warning naming alpha and both values", len(warn) == 1 and "alpha" in warn[0] and '"presto"' in warn[0]
       and '"sidearm"' in warn[0], warn)
    main = edited(base, platform("alpha", "sidearm"))
    out, warn, applied = mr.merge(b(base), b(main), b(run))
    ok("the same value: main's bytes, no warning", out == b(main) and warn == [] and applied == [], warn)


def test_missing_key():
    print("missing-key: base has no athletics.platform for the program")
    def drop(d):
        del find(d, "alpha")["athletics"]["platform"]
    base = edited(base_doc(), drop)
    run = edited(base, lambda d: find(d, "alpha")["athletics"].__setitem__("platform", "sidearm"))
    out, warn, applied = mr.merge(b(base), b(base), b(run))
    ok("main left it absent too: the run's value applied", json.loads(out)["programs"][0]["athletics"]["platform"] == "sidearm" and applied == ["alpha"])
    main = edited(base, lambda d: find(d, "alpha")["athletics"].__setitem__("platform", None))
    out, warn, applied = mr.merge(b(base), b(main), b(run))
    ok("main set it to null: absent and null differ, so main's stands", out == b(main) and len(warn) == 1, warn)
    ok("the run removing the key is refused", "removed alpha's athletics.platform" in (unexpected(b(run), b(run), b(base)) or ""))


def test_refused():
    print("refused: any other change the run made, and unparsable copies")
    base = base_doc()
    cases = [
        ("another field", edited(base, lambda d: find(d, "alpha").__setitem__("onboarded", False)), "alpha's onboarded"),
        ("another athletics field", edited(base, lambda d: find(d, "beta")["athletics"].__setitem__("baseUrl", "https://x.example")),
         "beta's athletics.baseUrl"),
        ("a new field", edited(base, lambda d: find(d, "beta").__setitem__("collectionHold", {"reason": "x"})), "beta's collectionHold"),
        ("heldPrograms", edited(base, lambda d: d["heldPrograms"].append(program("dropped"))), "`heldPrograms`"),
        ("a top-level key", edited(base, lambda d: d.__setitem__("onboardedDivisions", ["D1"])), "`onboardedDivisions`"),
        ("a program added", edited(base, lambda d: d["programs"].append(program("newprog"))), "added newprog"),
        ("a program removed", edited(base, lambda d: d["programs"].pop()), "removed ghost"),
        ("programs reordered", edited(base, lambda d: d["programs"].reverse()), "reordered"),
        ("a platform and another field together", edited(base, platform("alpha", "sidearm"),
                                                         lambda d: find(d, "alpha").__setitem__("name", "Alpha")), "alpha's name"),
        ("`updated` removed", edited(base, lambda d: d.pop("updated")), "`updated`"),
    ]
    for label, run, named in cases:
        msg = unexpected(b(base), b(base), b(run))
        ok(f"{label}: refused, naming {named}", msg is not None and named in msg, msg)
    good = b(edited(base, platform("alpha", "sidearm")))
    for side, args in (("base", (b"{", b(base), good)), ("main", (b(base), b"{", good)), ("run", (b(base), b(base), b"{"))):
        msg = unexpected(*args)
        ok(f"unparsable {side}: refused, naming the {side} copy", msg is not None and f"the {side} copy" in msg, msg)
    ok("not a registry: refused", unexpected(b(base), b"[]\n", good) is not None)
    ok("not UTF-8: refused", unexpected(b(base), b"\xff\xfe", good) is not None)
    dup = b(doc(program("alpha"), program("alpha")))
    ok("a slug listed twice: refused", "twice" in (unexpected(b(base), dup, good) or ""))


def test_real_registry():
    print("real-registry: this repository's registry, merged, is byte-identical to write_json's")
    raw = open(os.path.join(ROOT, "public", "data", "registry.json"), "rb").read().replace(b"\r\n", b"\n")
    base = json.loads(raw)
    tmp = tempfile.mkdtemp(prefix="merge-registry-")
    try:
        def write_json(d) -> bytes:
            p = os.path.join(tmp, "registry.json")
            common.write_json(p, d)
            return open(p, "rb").read()
        ok("the repository's registry is itself write_json's format", write_json(base) == raw)
        first, last = base["programs"][0]["slug"], base["programs"][-1]["slug"]
        run = edited(base, platform(first, "presto"), updated("2099-01-01"))
        main = edited(base, lambda d: find(d, last).__setitem__("collectionHold", {"reason": "owner-hold", "evidence": "test", "since": "2099-01-01"}))
        out, warn, applied = mr.merge(write_json(base), write_json(main), write_json(run))
        ok("merged output is exactly write_json of the expected registry",
           out == write_json(edited(main, platform(first, "presto"), updated("2099-01-01"))))
        ok("and main's bytes exactly when the run changed nothing", mr.merge(raw, write_json(main), raw)[0] == write_json(main))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- the command line ----------

GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "harness", "GIT_AUTHOR_EMAIL": "harness@example.invalid",
           "GIT_COMMITTER_NAME": "harness", "GIT_COMMITTER_EMAIL": "harness@example.invalid"}


def test_cli():
    print("cli: reads the three copies with git show and writes the working tree's registry")
    tmp = tempfile.mkdtemp(prefix="merge-registry-cli-")
    env = {**os.environ, **GIT_ENV}
    here = os.getcwd()

    def git(*args):
        return subprocess.run(["git", "-C", tmp, *args], capture_output=True, text=True, env=env, check=True).stdout.strip()

    def commit(d, msg):
        path = os.path.join(tmp, *mr.REGISTRY.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b(d))
        git("add", "-A")
        git("commit", "-q", "-m", msg)
        return git("rev-parse", "HEAD")

    def run_cli(*args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = mr.main(list(args))
        return code, buf.getvalue()
    try:
        git("init", "-q")
        git("config", "core.autocrlf", "false")
        base = base_doc()
        c_base = commit(base, "base")
        c_run = commit(edited(base, platform("alpha", "sidearm")), "run")
        git("checkout", "-q", c_base)
        c_main = commit(edited(base, platform("beta", "presto")), "main")
        os.chdir(tmp)
        code, out = run_cli("--base", c_base, "--main", c_main, "--run", c_run)
        written = open(os.path.join(tmp, *mr.REGISTRY.split("/")), "rb").read()
        ok("exit 0", code == 0, out)
        ok("the working tree's registry is the merge", written == b(edited(base, platform("beta", "presto"), platform("alpha", "sidearm"))))
        ok("no temp file left beside it", sorted(os.listdir(os.path.join(tmp, "public", "data"))) == ["registry.json"],
           os.listdir(os.path.join(tmp, "public", "data")))
        c_bad = commit(edited(base, lambda d: find(d, "alpha").__setitem__("onboarded", False)), "bad run")
        before = open(os.path.join(tmp, *mr.REGISTRY.split("/")), "rb").read()
        code, out = run_cli("--base", c_base, "--main", c_main, "--run", c_bad)
        ok("an unexpected change: exit 1 with an ::error", code == 1 and out.startswith("::error title=registry merge::"), out)
        ok("and nothing written", open(os.path.join(tmp, *mr.REGISTRY.split("/")), "rb").read() == before)
        code, out = run_cli("--base", "", "--main", c_main, "--run", c_run)
        ok("an empty revision (a failed merge-base): exit 1, never the index", code == 1 and "no revision" in out, out)
        code, out = run_cli("--base", "0" * 40, "--main", c_main, "--run", c_run)
        ok("an unknown revision: exit 1", code == 1 and "could not read" in out, out)
    finally:
        os.chdir(here)
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_run_untouched, test_applied, test_updated, test_main_adds, test_main_removes, test_main_holds,
                 test_main_reorders, test_clash_and_identical, test_missing_key, test_refused, test_real_registry, test_cli):
        case()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
