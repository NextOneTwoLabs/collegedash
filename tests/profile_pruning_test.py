"""Regression tests for the published set and profile pruning in build.py (issue #110).

    python tests/profile_pruning_test.py            # everything below, offline
    python tests/profile_pruning_test.py --verbose  # print every check, not only the failures

Offline: synthetic profile directories under a temporary directory, one real build into a temporary
directory, and a read-only look at the committed public/data. Exit 0 when every check passes, 1 otherwise.

A program that leaves the published set (held, not onboarded, or in a division that is not onboarded)
must lose its public/data/programs/<slug>.json, because build.py writes profiles and before this never
deleted one. Pruning deletes live pages when it is wrong, so its guards are tested as hard as the
pruning itself. Each check's comment names the input that makes it fail.

The guard (PR #112 review, F2) is not a share cap: every profile pruning deletes must be explained by
the registry, by logic separate from published_programs(), and anything unexplained is refused whatever
the count. The only override is a one-shot, per-slug argument.

Covers, in order:
  set        published_programs: onboarded entries of registry.programs in an onboarded division
  explain    prune_explanations: held, not onboarded, division off; nothing else
  plan       held / not-onboarded / division-off profiles go; published profiles, index.json and
             non-profile names (a directory or symlink with a profile's name included) stay; a D2
             switch-off goes through with no override; wipe attempts (an empty set, a registry that
             loaded short, a published_programs bug, an unknown division) and any unexplained slug are
             refused with nothing deleted; the per-slug override deletes exactly what it names
  build      a real build into a scratch directory prunes a program moved to a division that is not
             onboarded, refuses an unexplained stale profile before writing anything, and validate's
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


# ---------- the registry's explanations ----------

def reg_of(published=("alpha", "beta", "gamma"), held=("held-one",), not_onboarded=("new-one",), d2=("d2-one",),
           divisions=("D1",)):
    prog = lambda slug, **kw: {"slug": slug, "onboarded": True, "division": "D1", **kw}
    return {"onboardedDivisions": list(divisions),
            "programs": [prog(x) for x in published] + [prog(x, onboarded=False) for x in not_onboarded]
                        + [prog(x, division="D2") for x in d2],
            "heldPrograms": [prog(x, hold={"reason": "division-not-onboarded"}) for x in held]}


def test_explain() -> None:
    print("explain: what the registry accounts for")
    e = build.prune_explanations(reg_of())
    # fails if any of the three registry reasons stops explaining a deletion, or something else starts to
    ok("held, not onboarded and division-off are explained, and nothing published is",
       set(e) == {"held-one", "new-one", "d2-one"} and "held" in e["held-one"] and "not onboarded" in e["new-one"]
       and "D2" in e["d2-one"], str(e))
    ok("with D2 onboarded the D2 program is no longer explained", "d2-one" not in build.prune_explanations(reg_of(divisions=("D1", "D2"))))
    ok("the process-wide override is gone", not hasattr(build, "PRUNE_MAX_SHARE")
       and "COLLEGEDASH_PRUNE_MAX_SHARE" not in open(build.__file__, encoding="utf-8").read())


# ---------- plan_prune and prune_profiles ----------

def published_of(reg):
    return {p["slug"] for p in build.published_programs(reg)}


def test_prune() -> None:
    print("plan: what goes, what stays, and the guards")
    tmp = tempfile.mkdtemp(prefix="prune-")
    try:
        reg = reg_of()
        d = os.path.join(tmp, "p1")
        plant(d, ["alpha.json", "beta.json", "gamma.json", "held-one.json", "new-one.json", "d2-one.json", "index.json",
                  "alpha.json.1234.tmp", "README.txt", "Upper.json"])
        os.makedirs(os.path.join(d, "aa-held.json"))  # a directory carrying a profile's name
        symlinked = False
        try:
            plant(os.path.join(tmp, "target"), ["kept.json"])
            os.symlink(os.path.join(tmp, "target", "kept.json"), os.path.join(d, "ab-link.json"))
            symlinked = True
        except (OSError, NotImplementedError):
            pass  # Windows without the symlink privilege; the CI runner (Linux) exercises it
        before = snapshot_files(d)
        plan = attempt(build.plan_prune, reg, published_of(reg), d)
        # fails if an explained profile is kept, or anything unexplained or non-profile is planned
        ok("the plan is exactly the held, not-onboarded and division-off profiles",
           sorted(plan) == ["d2-one", "held-one", "new-one"], str(plan))
        gone = attempt(build.prune_profiles, plan, published_of(reg), d)
        after = snapshot_files(d)
        ok("they are deleted", sorted(gone) == ["d2-one", "held-one", "new-one"]
           and not {"d2-one.json", "held-one.json", "new-one.json"} & set(after), str(sorted(after)))
        # fails if pruning touches a published profile, even by rewriting it
        ok("every published profile survives byte for byte",
           all(after.get(f) == before[f] for f in ("alpha.json", "beta.json", "gamma.json")))
        # fails if index.json, a temp file, a non-slug name, a directory or a symlink is treated as a profile
        # (F3: `re.match` with `$` took "ghost.json\n"; a directory made os.remove raise part-way)
        ok("index.json, temp files, non-slug names and a directory with a profile's name are untouched, with no crash",
           all(after.get(f) == before[f] for f in ("index.json", "alpha.json.1234.tmp", "README.txt", "Upper.json"))
           and os.path.isdir(os.path.join(d, "aa-held.json")))
        ok("a name that only matches with a trailing newline is not a profile",
           build._PROFILE_FILE.fullmatch("ghost.json\n") is None and build._PROFILE_FILE.fullmatch("ghost.json") is not None)
        if symlinked:
            ok("a symlink with a profile's name is not a profile", os.path.islink(os.path.join(d, "ab-link.json"))
               and os.path.exists(os.path.join(tmp, "target", "kept.json")))

        # --- a D2 switch-off: every D2 program is explained, however many, and needs no override
        d = os.path.join(tmp, "switch-off")
        d2 = [f"d2-{i}" for i in range(680)]
        reg = reg_of(published=[f"d1-{i}" for i in range(348)], held=(), not_onboarded=(), d2=d2)
        plant(d, [f"{x}.json" for x in [f"d1-{i}" for i in range(348)] + d2])
        plan = attempt(build.plan_prune, reg, published_of(reg), d)
        # fails if a count cap comes back and refuses a fully explained switch-off
        ok("switching D2 off deletes all 680 D2 profiles with no override", len(plan) == 680 and set(plan) == set(d2))

        # --- wipe attempts and unexplained slugs: planning refuses. Planning deletes nothing by itself, and
        # build() plans before its first write, so a refusal here is a build that changes nothing (see test_build).
        def refused(label, reg, published, names, **kw):
            dd = os.path.join(tmp, label.replace(" ", "_")[:40])
            plant(dd, names)
            raises(label, RuntimeError, build.plan_prune, reg, published, dd, **kw)

        full = reg_of(published=[f"p{i}" for i in range(348)], held=(), not_onboarded=(), d2=())
        names = [f"p{i}.json" for i in range(348)]
        # fails if an empty published set can prune: every profile here IS explained (none onboarded), so only
        # the empty-set guard stands between this and deleting all 348
        nobody = reg_of(published=(), held=(), not_onboarded=[f"p{i}" for i in range(348)], d2=())
        refused("an empty published set is refused, even when the registry explains every deletion", nobody, set(), names)
        # fails if a registry that loaded short (one program left) wipes the other 347
        short = reg_of(published=["p0"], held=(), not_onboarded=(), d2=())
        refused("a registry that loaded short (1 of 348) is refused", short, published_of(short), names)
        # fails if a bug in published_programs can explain its own deletions (it drops 20 programs here)
        refused("a published_programs bug dropping 20 programs is refused", full, published_of(full) - {f"p{i}" for i in range(20)}, names)
        # fails if an unknown division explains every program away: 347 D1 programs are "division off" and the one
        # program filed under the typo is published, so nothing but the unknown-division guard refuses
        typo = reg_of(published=[f"p{i}" for i in range(1, 348)], held=(), not_onboarded=(), d2=(), divisions=("D9",))
        typo["programs"].append({"slug": "p0", "onboarded": True, "division": "D9"})
        refused("onboardedDivisions ['D9'] is refused", typo, published_of(typo), names)
        # fails if one stale slug nothing explains is deleted, however small the count
        refused("a single unexplained slug among 348 is refused", full, published_of(full), names + ["ghost.json"])
        # fails if the two readings of the registry may disagree about a published program
        refused("a slug both published and explained is refused", reg_of(), published_of(reg_of()) | {"held-one"},
                ["alpha.json", "held-one.json"])
        # fails if the per-slug override outlives the files it was written for
        refused("an override naming a slug that is not an unexplained stale profile is refused", full, published_of(full),
                names + ["ghost.json"], allow_unexplained=frozenset({"ghost", "p3"}))

        d = os.path.join(tmp, "override")
        plant(d, names + ["ghost.json"])
        plan = build.plan_prune(full, published_of(full), d, allow_unexplained=frozenset({"ghost"}))
        ok("the one-shot override deletes exactly the slug it names", list(plan) == ["ghost"]
           and build.prune_profiles(plan, published_of(full), d) == ["ghost"] and len(build.profile_slugs_on_disk(d)) == 348)

        # --- the deletion step re-checks every target before removing any
        d = os.path.join(tmp, "recheck")
        reg = reg_of()
        plant(d, ["alpha.json", "beta.json", "gamma.json", "held-one.json", "new-one.json"])
        plan = build.plan_prune(reg, published_of(reg), d)
        os.remove(os.path.join(d, "new-one.json")); os.makedirs(os.path.join(d, "new-one.json"))
        before = snapshot_files(d)
        # fails if a target that stopped being a profile file crashes the loop after deleting earlier ones
        raises("a target replaced by a directory after planning stops the prune", RuntimeError, build.prune_profiles, plan, published_of(reg), d)
        ok("before the first deletion", snapshot_files(d) == before and os.path.exists(os.path.join(d, "held-one.json")))
        # fails if the published re-check is removed: a plan (built by hand here) naming a published slug
        raises("a plan naming a published slug is refused", RuntimeError, build.prune_profiles, {"alpha": "x"}, {"alpha"}, d)
        ok("and alpha survives", os.path.isfile(os.path.join(d, "alpha.json")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def attempt(fn, *a, **kw):
    """Call fn; on an exception record a failed check naming it and return an empty result, so one broken
    guard shows as a named failure instead of ending the suite."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        ok(f"{fn.__name__} does not raise here", False, f"{type(e).__name__}: {e}")
        return {} if fn.__name__ == "plan_prune" else []


def snapshot_files(d: str) -> dict[str, bytes]:
    return {f: open(os.path.join(d, f), "rb").read() for f in sorted(os.listdir(d)) if os.path.isfile(os.path.join(d, f))}


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
    # with D3 staged (#190), a staged D3 entry must carry a D3 conference as the Directory spells it, not a D1 label
    d3_conference = next((q["conference"] for q in reg2["programs"] if q["division"] == "D3"), None)
    for p in reg2["programs"]:
        if p["slug"] == moved:
            p["division"] = "D3"
            if d3_conference:
                p["conference"] = d3_conference
    # With D3 published (#94) no division is left unpublished, so for this scenario D3 goes back to staged: the
    # moved program and every real D3 entry are then collected but not published, and none of them may keep a page
    d3_slugs = {q["slug"] for q in reg2["programs"] if q["division"] == "D3"}
    if "D3" in reg2["onboardedDivisions"]:
        reg2["onboardedDivisions"] = [d for d in reg2["onboardedDivisions"] if d != "D3"]
        reg2["stagedDivisions"] = [*(reg2.get("stagedDivisions") or []), "D3"]
    # a real reclassification of a long-standing program is a reviewed edit to build.REVIEWED_UNPUBLISHED (R1);
    # the scenario makes that edit for its duration
    # the same goes for a long-standing program already in D3 (saint-francis, published as D3 since #94): staging
    # D3 again for the scenario unpublishes it too
    long_standing = {q["slug"] for q in json.load(open(build.LONG_STANDING_PATH, encoding="utf-8"))["programs"]}
    build.REVIEWED_UNPUBLISHED = {**build.REVIEWED_UNPUBLISHED, moved: "test: reclassified to D3",
                                  **{s: "test: D3 staged again for the scenario" for s in (d3_slugs & long_standing) - {moved}}}
    # With D3 staged the moved program is one more staged D3 entry, collected but still not published, so the
    # scenario sets the D3 count anchor to the staged entries it made, moved one included, for its duration;
    # otherwise validate fails on the count
    saved_counts = build.STAGED_DIVISION_COUNTS
    build.STAGED_DIVISION_COUNTS = {**saved_counts, "D3": len(d3_slugs)}
    tmp = tempfile.mkdtemp(prefix="prune-build-")
    progs = os.path.join(tmp, "programs")
    swap = dict(PROGRAMS_OUT_DIR=progs, COMMITS_OUT_DIR=os.path.join(tmp, "commitments"), CAMPS_OUT_DIR=os.path.join(tmp, "camps"))
    try:
        # --- an unexplained stale profile: refused before the first write
        plant(progs, ["ghost-program.json", f"{moved}.json"])
        before = snapshot_files(progs)
        with swapped(**swap):
            with contextlib.redirect_stdout(io.StringIO()):
                raises("a build with an unexplained stale profile raises", RuntimeError, build.build, reg2)
        # fails if the plan is worked out after the writes (F3: a refused prune left a half-written tree)
        ok("and writes nothing: no profile, no index.json", snapshot_files(progs) == before
           and not os.path.exists(os.path.join(tmp, "commitments")), str(sorted(snapshot_files(progs))[:5]))

        # --- named for one run, the same build goes through
        buf = io.StringIO()
        with swapped(**swap):
            with contextlib.redirect_stdout(buf):
                build.build(reg2, allow_unexplained_prune=frozenset({"ghost-program"}))
            on_disk = build.profile_slugs_on_disk(progs)
            want = set(published) - d3_slugs
            ok("with the one-shot override the unexplained profile is pruned", "ghost-program" not in on_disk)
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
        build.REVIEWED_UNPUBLISHED = {k: v for k, v in build.REVIEWED_UNPUBLISHED.items() if k != moved}
        build.STAGED_DIVISION_COUNTS = saved_counts
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
    test_explain()
    test_prune()
    test_build()
    test_committed()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
