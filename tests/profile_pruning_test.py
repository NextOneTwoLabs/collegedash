"""Regression tests for the published set and profile pruning in build.py (issue #110).

    python tests/profile_pruning_test.py            # everything below, offline
    python tests/profile_pruning_test.py --verbose  # print every check, not only the failures

Offline: synthetic profile directories under a temporary directory, one real build into a temporary
directory, and a read-only look at the committed public/data. Exit 0 when every check passes, 1 otherwise.

A program that leaves the published set (held, in no Directory list, or in a division that is not
onboarded) must lose its public/data/programs/<slug>.json, because build.py writes profiles and
before this never deleted one. Pruning deletes live pages when it is wrong, so its guards are
tested as hard as the pruning itself. Each check's comment names the input that makes it fail.

Covers, in order:
  set        published_programs: onboarded entries of registry.programs in an onboarded division
  prune      stale and held profiles go; published profiles, index.json and non-profile files stay
             byte-identical; an empty published set, an unwritten profile and a mass deletion raise
             and delete nothing
  build      a real build into a scratch directory prunes a planted stale profile and a program
             whose division is not onboarded, keeps every published profile, and validate's
             STALE check fails when a stale profile is put back
  committed  the committed public/data/programs holds no profile outside the published set
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import build  # noqa: E402
from collect import common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def raises(name: str, exc, fn, *a, **kw) -> None:
    try:
        fn(*a, **kw)
    except exc as e:
        ok(name, True, str(e))
        return
    except Exception as e:  # noqa: BLE001
        ok(name, False, f"raised {type(e).__name__}: {e}")
        return
    ok(name, False, "did not raise")


@contextlib.contextmanager
def swapped(**attrs):
    old = {k: getattr(common, k) for k in attrs}
    for k, v in attrs.items():
        setattr(common, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(common, k, v)


def snapshot(d: str) -> dict[str, bytes]:
    return {f: open(os.path.join(d, f), "rb").read() for f in sorted(os.listdir(d))}


def plant(d: str, names: list[str]) -> None:
    os.makedirs(d, exist_ok=True)
    for n in names:
        with open(os.path.join(d, n), "w", encoding="utf-8") as f:
            f.write(json.dumps({"slug": n[:-5] if n.endswith(".json") else n}))


# ---------- the published set ----------

def test_set() -> None:
    print("set: published_programs")
    reg = {"onboardedDivisions": ["D1"], "programs": [
        {"slug": "a", "onboarded": True, "division": "D1"},
        {"slug": "b", "onboarded": False, "division": "D1"},
        {"slug": "c", "onboarded": True, "division": "D2"},
    ], "heldPrograms": [{"slug": "h", "onboarded": True, "division": "D1", "hold": {"reason": "not-in-directory"}}]}
    # fails if a D2 program stays published while D2 is not onboarded, or a held/un-onboarded one leaks in
    ok("only onboarded programs in an onboarded division are published",
       [p["slug"] for p in build.published_programs(reg)] == ["a"], str([p["slug"] for p in build.published_programs(reg)]))
    reg2 = copy.deepcopy(reg)
    reg2["onboardedDivisions"] = ["D1", "D2"]
    ok("adding D2 to onboardedDivisions publishes the D2 program", [p["slug"] for p in build.published_programs(reg2)] == ["a", "c"])
    reg3 = copy.deepcopy(reg)
    reg3.pop("onboardedDivisions")
    ok("a registry from before onboardedDivisions publishes every onboarded program",
       [p["slug"] for p in build.published_programs(reg3)] == ["a", "c"])


# ---------- prune_profiles ----------

def test_prune() -> None:
    print("prune: what goes, what stays, and the guards")
    tmp = tempfile.mkdtemp(prefix="prune-")
    try:
        d = os.path.join(tmp, "p1")
        plant(d, ["alpha.json", "beta.json", "gamma.json", "ghost.json", "held-one.json", "index.json",
                  "alpha.json.1234.tmp", "README.txt", "Upper.json"])
        before = snapshot(d)
        gone = build.prune_profiles({"alpha", "beta", "gamma"}, d, max_share=1.0)
        after = snapshot(d)
        # fails if a stale or held program's profile survives
        ok("the stale and held profiles are deleted", gone == ["ghost", "held-one"] and "ghost.json" not in after
           and "held-one.json" not in after, str(gone))
        # fails if pruning touches a published profile, even by rewriting it
        ok("every published profile survives byte for byte",
           all(after.get(f) == before[f] for f in ("alpha.json", "beta.json", "gamma.json")), str(sorted(after)))
        # fails if index.json, a writer's temp file or a non-slug name is treated as a profile
        ok("index.json, temp files and names that are not slugs are never touched",
           all(after.get(f) == before[f] for f in ("index.json", "alpha.json.1234.tmp", "README.txt", "Upper.json")))

        d = os.path.join(tmp, "p2")
        plant(d, ["alpha.json", "beta.json", "index.json"])
        before = snapshot(d)
        # fails if a registry that loaded empty wipes every page
        raises("an empty published set raises", RuntimeError, build.prune_profiles, set(), d, max_share=1.0)
        ok("and deletes nothing", snapshot(d) == before)

        d = os.path.join(tmp, "p3")
        plant(d, ["alpha.json", "ghost.json"])
        before = snapshot(d)
        # fails if pruning may run when a published profile was never written (a build that crashed part-way)
        raises("a published program with no profile on disk raises", RuntimeError,
               build.prune_profiles, {"alpha", "beta"}, d, max_share=1.0)
        ok("and deletes nothing, not even the stale one", snapshot(d) == before)

        d = os.path.join(tmp, "p4")
        plant(d, [f"p{i}.json" for i in range(10)] + ["x1.json", "x2.json"])
        before = snapshot(d)
        # fails if a mass deletion (a short registry, a typo in onboardedDivisions) goes through
        raises("deleting more than the share limit raises", RuntimeError,
               build.prune_profiles, {f"p{i}" for i in range(10)}, d, max_share=0.10)
        ok("and deletes nothing", snapshot(d) == before)
        ok("inside the limit the same prune goes through",
           build.prune_profiles({f"p{i}" for i in range(10)}, d, max_share=0.2) == ["x1", "x2"]
           and sorted(snapshot(d)) == sorted(f"p{i}.json" for i in range(10)))

        d = os.path.join(tmp, "p5")
        plant(d, ["alpha.json"])
        ok("nothing stale, nothing deleted", build.prune_profiles({"alpha"}, d) == [] and snapshot(d) == {"alpha.json": b'{"slug": "alpha"}'})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- a real build ----------

def test_build() -> None:
    print("build: a real build into a scratch directory")
    reg = common.load_registry()
    published = [p["slug"] for p in build.published_programs(reg)]
    ok("the committed registry publishes programs", len(published) > 20, str(len(published)))
    # a program the committed registry publishes, moved to a division that is not onboarded
    # (not a national champion: check_titles would then fail validate for a reason of its own)
    moved = next(s for s in published if s not in set(build.NCAA_D1_WOMENS_CHAMPIONS.values()))
    reg2 = copy.deepcopy(reg)
    for p in reg2["programs"]:
        if p["slug"] == moved:
            p["division"] = "D3"
    tmp = tempfile.mkdtemp(prefix="prune-build-")
    progs = os.path.join(tmp, "programs")
    try:
        plant(progs, ["ghost-program.json", f"{moved}.json"])
        buf = io.StringIO()
        with swapped(PROGRAMS_OUT_DIR=progs, COMMITS_OUT_DIR=os.path.join(tmp, "commitments"),
                     CAMPS_OUT_DIR=os.path.join(tmp, "camps")):
            with contextlib.redirect_stdout(buf):
                build.build(reg2)
            on_disk = build.profile_slugs_on_disk(progs)
            want = set(published) - {moved}
            # fails if build.py does not prune
            ok("the planted stale profile is pruned", "ghost-program" not in on_disk)
            # fails if a program whose division is not onboarded keeps its page
            ok(f"{moved}, moved to a division that is not onboarded, is pruned", moved not in on_disk)
            # fails if pruning or the build loses a published page
            ok("every published program has its profile", on_disk == want,
               f"missing {sorted(want - on_disk)[:5]}, extra {sorted(on_disk - want)[:5]}")
            index = json.load(open(os.path.join(progs, "index.json"), encoding="utf-8"))
            ok("index.json lists exactly the published programs", {r["slug"] for r in index["programs"]} == want)
            ok("the build's validate reports no stale profile", "STALE " not in buf.getvalue(),
               [l for l in buf.getvalue().splitlines() if l.startswith("STALE")][:3])
            with contextlib.redirect_stdout(io.StringIO()):
                ok("check_no_stale_profiles passes on the pruned tree", build.check_no_stale_profiles(reg2))
                ok("and validate as a whole passes on it, so the failure below is the stale file's", build.validate(reg2))
            plant(progs, ["ghost-program.json"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                passed = build.check_no_stale_profiles(reg2)
            # fails if validate cannot see a stale profile that survived
            ok("and fails, naming it, when a stale profile is put back",
               not passed and "STALE ghost-program" in out.getvalue(), out.getvalue())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                passed = build.validate(reg2)
            ok("which fails validate as a whole", not passed and "STALE ghost-program" in out.getvalue())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- the committed tree ----------

def test_committed() -> None:
    print("committed: public/data/programs")
    reg = common.load_registry()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        passed = build.check_no_stale_profiles(reg)
    # fails if a profile outside the published set is committed (Saint Francis's and Mississippi Valley
    # State's were, until PR #107 deleted them by hand)
    ok("no committed profile is outside the published set", passed, out.getvalue().strip()[:300])
    held = [p["slug"] for p in reg.get("heldPrograms") or []]
    ok("no held program has a committed profile",
       not [s for s in held if os.path.exists(os.path.join(common.PROGRAMS_OUT_DIR, f"{s}.json"))], str(held))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    VERBOSE = ap.parse_args(argv).verbose
    test_set()
    test_prune()
    test_build()
    test_committed()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
