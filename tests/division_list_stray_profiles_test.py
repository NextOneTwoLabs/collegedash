"""One division list, and validate reports a stray profile-named entry (issue #121).

    python tests/division_list_stray_profiles_test.py

1. build.KNOWN_DIVISIONS, registry_builder.DIVISION_ROMAN and trends.DIVISIONS were three hand-written copies of the
   NCAA divisions, free to drift apart. All three now derive from collect/common.py's DIVISIONS, and no module lists
   the divisions literally any more.
2. A directory or a symlink in public/data/programs/ named like a profile (`<slug>.json`) was skipped by
   profile_slugs_on_disk and refused by prune_profiles, so nothing ever reported it, while the deploy serves whatever
   sits there. check_no_stale_profiles, which validate runs, now reports each one as STRAY and fails.

Offline; the stray-entry cases use a temporary directory, never public/data. FIX checks fail on origin/main; CONTROL
checks pass on both.
"""

from __future__ import annotations

import ast
import re
import contextlib
import io
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import build  # noqa: E402
import trends  # noqa: E402
from collect import common, registry_builder  # noqa: E402

FAILS: list[str] = []
TOTAL = 0


def ok(name: str, cond: bool, detail="") -> None:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))


def test_one_division_list() -> None:
    print("one-division-list")
    divisions = getattr(common, "DIVISIONS", None)
    ok("FIX collect/common.py defines DIVISIONS", isinstance(divisions, dict), divisions)
    if not isinstance(divisions, dict):
        return
    ok("CONTROL the divisions are D1, D2, D3 with the Directory's numerals",
       divisions == {"D1": "I", "D2": "II", "D3": "III"}, divisions)
    ok("FIX build.KNOWN_DIVISIONS is derived from it", set(build.KNOWN_DIVISIONS) == set(divisions), build.KNOWN_DIVISIONS)
    ok("FIX registry_builder.DIVISION_ROMAN is derived from it", registry_builder.DIVISION_ROMAN == divisions)
    ok("FIX trends.DIVISIONS is derived from it, in order", trends.DIVISIONS == tuple(divisions), trends.DIVISIONS)
    for rel in ("build.py", os.path.join("collect", "registry_builder.py"), "trends.py"):
        found = division_literals(os.path.join(ROOT, rel))
        ok(f"FIX {rel} lists no divisions of its own (a list, tuple, set or dict holding 'D1' and 'D2')", not found, found)


def division_literals(path: str) -> list[int]:
    """Line numbers of literals in `path`'s code that ARE a list of the divisions: a list, tuple or set of nothing but
    division codes ('D1', 'D2', ...), or a dict from division codes to their roman numerals. Docstrings and comments are
    text, not code, and a dict that maps each division to its own data (CHAMPION_TABLES, DIVISION_NAMES) is not a copy
    of the list."""
    code = re.compile(r"^D\d$")
    tree = ast.parse(open(path, encoding="utf-8").read())
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            vals = [e.value if isinstance(e, ast.Constant) else None for e in node.elts]
            if len(vals) >= 2 and all(isinstance(v, str) and code.match(v) for v in vals):
                lines.append(node.lineno)
        elif isinstance(node, ast.Dict) and len(node.keys) >= 2:
            keys = [k.value if isinstance(k, ast.Constant) else None for k in node.keys]
            vals = [v.value if isinstance(v, ast.Constant) else None for v in node.values]
            if (all(isinstance(k, str) and code.match(k) for k in keys)
                    and all(isinstance(v, str) and re.fullmatch(r"I{1,3}|IV|V", v) for v in vals)):
                lines.append(node.lineno)
    return lines


def registry(*slugs: str) -> dict:
    return {"onboardedDivisions": ["D1"], "programs": [{"slug": s, "onboarded": True, "division": "D1"} for s in slugs]}


def test_stray_entries() -> None:
    print("stray-entries")
    stray_fn = getattr(build, "stray_profile_entries", None)
    ok("FIX build.stray_profile_entries exists", stray_fn is not None)
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "alpha-u.json"), "w", encoding="utf-8").write("{}")
        open(os.path.join(d, "index.json"), "w", encoding="utf-8").write("{}")
        os.mkdir(os.path.join(d, "notes"))  # not shaped like a profile: never reported
        clean, said = profile_check(registry("alpha-u"), d)
        ok("CONTROL a directory of regular published profiles passes", clean is True, said)

        os.mkdir(os.path.join(d, "beta-college.json"))
        expected = ["beta-college.json"]
        try:
            os.symlink(os.path.join(d, "alpha-u.json"), os.path.join(d, "gamma-state.json"))
            expected.append("gamma-state.json")
        except (OSError, NotImplementedError):  # Windows without the symlink privilege: the directory case still runs
            print("  (symlinks not permitted here: the symlink case is skipped)")
        if stray_fn is not None:
            ok("FIX a directory and a symlink named like profiles are reported, nothing else",
               stray_fn(d) == sorted(expected), stray_fn(d))
        result, said = profile_check(registry("alpha-u"), d)
        ok("FIX validate's profile check fails on them", result is False, result)
        ok("FIX and prints one STRAY line naming each",
           all(f"STRAY public/data/programs/{n}" in said for n in expected), said)
        ok("CONTROL the published regular profile is never called stray or stale", "alpha-u" not in said, said)


def profile_check(reg: dict, out_dir: str) -> tuple[bool, str]:
    """build.check_no_stale_profiles(reg) as validate calls it, over `out_dir` in place of public/data/programs."""
    saved = common.PROGRAMS_OUT_DIR
    buf = io.StringIO()
    try:
        common.PROGRAMS_OUT_DIR = out_dir
        with contextlib.redirect_stdout(buf):
            result = build.check_no_stale_profiles(reg)
    finally:
        common.PROGRAMS_OUT_DIR = saved
    return result, buf.getvalue()


def test_validate_calls_it() -> None:
    print("validate-calls-it")
    src = open(os.path.join(ROOT, "build.py"), encoding="utf-8").read()
    ok("CONTROL validate runs check_no_stale_profiles", "stale_ok = check_no_stale_profiles(registry)" in src)
    ok("CONTROL the shipped public/data/programs has no stray entry", getattr(build, "stray_profile_entries", lambda d: [])(
        common.PROGRAMS_OUT_DIR) == [])


def main() -> int:
    for fn in (test_one_division_list, test_stray_entries, test_validate_calls_it):
        fn()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
