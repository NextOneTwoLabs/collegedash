"""validate's profile readers report a malformed profile by path instead of raising (issue #462).

    python tests/validate_guards_test.py            # every case, offline
    python tests/validate_guards_test.py --verbose  # print every check, not only the failures

#459 (issue #70) made check_camps_index name a malformed profile instead of raising. The other readers that
validate runs still used a bare json.load:
  - validate()'s own schema loop;
  - check_titles, check_academic_ranks and check_seasons;
  - check_fit_index's per-profile load.
One broken profile then ended `collegedash.py validate` with a traceback (exit 2) instead of a line naming the file.

Each case points common.PROGRAMS_OUT_DIR at a scratch copy of the committed profiles (with list/ and fit/ linked
beside it, as build.list_path() and fit_path() expect), with one profile replaced by truncated JSON. Nothing is
fetched and nothing under public/ is written.

Issue #79: common.CAMPS_OUT_DIR points at a scratch copy of the committed camps index too, carrying the `coverage`
block build.camp_coverage computes from the copied profiles - the block a build writes. The committed index has none
until the first refresh after #79 merges, and this suite judges the profile readers, not that transition.

Cases:
  control   the scratch tree with no damage passes validate, so every failure below is the damaged file's
  readers   each reader, called on its own, returns False and names the file instead of raising
  validate  the whole validate run returns False with exactly one "is not readable JSON" line naming the file,
            no other line names the program (check_titles once printed "is the champion but publishes no title"
            for the skipped profile), and every check after the schema loop still runs
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "collect"))

import build  # noqa: E402
from collect import common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False
BAD = "stanford"
LIVE_PROGRAMS = common.PROGRAMS_OUT_DIR
LIVE_CAMPS = common.CAMPS_OUT_DIR


def ok(name: str, cond: bool, detail: str = "") -> None:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")


def scratch(tmp: str, damage: bool) -> str:
    """tmp/programs: a copy of the committed profiles, one replaced by truncated JSON when `damage`; tmp/list and
    tmp/fit link to the committed ones."""
    root = tempfile.mkdtemp(dir=tmp)
    progs = os.path.join(root, "programs")
    shutil.copytree(LIVE_PROGRAMS, progs)  # copies, not links: check_no_stale_profiles refuses a linked profile
    live_data = os.path.dirname(LIVE_PROGRAMS)
    for d in ("list", "fit"):
        os.symlink(os.path.join(live_data, d), os.path.join(root, d))
    # #79: the camps index as a build writes it, with the coverage of exactly the profiles copied above
    camps = common.read_json(os.path.join(LIVE_CAMPS, "index.json"))
    published = [common.read_json(os.path.join(progs, f"{p['slug']}.json")) or {}
                 for p in build.published_programs(common.load_registry())]
    camps["coverage"] = build.camp_coverage(published)
    os.makedirs(os.path.join(root, "camps"))
    common.write_json(os.path.join(root, "camps", "index.json"), camps, compact=True)
    if damage:
        bad = os.path.join(progs, f"{BAD}.json")
        os.remove(bad)
        with open(bad, "w", encoding="utf-8") as f:
            f.write('{"slug": "stanford", "name": ')
    return progs


@contextlib.contextmanager
def programs_at(path: str):
    """The scratch profiles at `path`, and the scratch camps index beside them (#79)."""
    old = common.PROGRAMS_OUT_DIR, common.CAMPS_OUT_DIR
    common.PROGRAMS_OUT_DIR, common.CAMPS_OUT_DIR = path, os.path.join(os.path.dirname(path), "camps")
    try:
        yield
    finally:
        common.PROGRAMS_OUT_DIR, common.CAMPS_OUT_DIR = old


def run(fn, *a) -> tuple[bool | None, str, str | None]:
    """(result, printed output, the exception if it raised)."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            res = fn(*a)
        return res, buf.getvalue(), None
    except Exception as e:  # noqa: BLE001 - raising is the failure these cases exist to catch
        return None, buf.getvalue(), f"{type(e).__name__}: {e}"


def unreadable_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if "is not readable JSON" in line]


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    registry = common.load_registry()
    tmp = tempfile.mkdtemp(prefix="validate-guards-")
    try:
        print("control: the undamaged scratch tree passes validate")
        with programs_at(scratch(tmp, damage=False)):
            res, out, raised = run(build.validate, registry)
        ok("control: validate passes on the undamaged copy", res is True and raised is None, raised or out[-600:])

        print("readers: each one names the malformed profile instead of raising")
        progs = scratch(tmp, damage=True)
        readers = [("check_titles", (registry,)), ("check_academic_ranks", (registry,)), ("check_seasons", (registry,)),
                   ("check_fit_index", ()), ("check_camps_index", (registry,))]
        with programs_at(progs):
            for name, args in readers:
                res, out, raised = run(getattr(build, name), *args)
                fix = "" if name == "check_camps_index" else "FIX "  # camps was guarded by #459; the rest fail on main
                ok(f"{fix}{name}: does not raise", raised is None, raised)
                ok(f"{fix}{name}: fails, naming {BAD}.json", res is False and any(f"{BAD}.json" in line for line in unreadable_lines(out)),
                   out[-600:])

        print("validate: one named complaint, and every later check still runs")
        called: list[str] = []
        later = ["check_titles", "check_academic_ranks", "check_seasons", "check_camps_index", "check_no_stale_profiles",
                 "check_membership_anchor", "check_staged_registry", "check_publish_gate", "check_list_index", "check_fit_index"]
        originals = {n: getattr(build, n) for n in later}

        def recording(n):
            def f(*a, **kw):
                called.append(n)
                return originals[n](*a, **kw)
            return f
        try:
            for n in later:
                setattr(build, n, recording(n))
            with programs_at(progs):
                res, out, raised = run(build.validate, registry)
        finally:
            for n, f in originals.items():
                setattr(build, n, f)
        ok("FIX validate: does not raise", raised is None, raised)
        ok("FIX validate: fails", res is False, out[-600:])
        lines = unreadable_lines(out)
        ok("FIX validate: exactly one 'is not readable JSON' line, naming the file", len(lines) == 1 and f"{BAD}.json" in lines[0],
           lines or out[-600:])
        ok("FIX validate: every check after the schema loop still ran", called == later, called)
        others = [line for line in out.splitlines() if BAD in line and "is not readable JSON" not in line]
        ok("FIX validate: no other line names the unreadable program (no false 'publishes no title')", not others, others[:5])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
