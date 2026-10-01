"""tools/roster_check.py and tools/camps_check.py's sweep: "checked nothing" is exit 2 and says so, never 0 (#81).

    python tests/check_tools_cache_test.py            # every case
    python tests/check_tools_cache_test.py --verbose  # print every check

Both tools read roster pages from the HTTP cache (common.CACHE_DIR). Each case imports the tool and calls its main()
in-process with CACHE_DIR swapped for a temporary directory, so the same call works on main and on this branch - an
unknown flag cannot make a case fail for the wrong reason - and nothing outside the temp directory is read or written.
Exit 2 is also argparse's usage-error code, so every "checked nothing" case asserts the message as well as the code.

The one-program cache is built at test time, in the temp directory, from a committed fixture page
(tests/fixtures/sidearm); no cache copy is committed, and no player row is printed (no --verbose). Offline, under the
network guard: both tools set COLLEGEDASH_OFFLINE.

Cases:
  empty      an empty cache: both tools return 2 with "checked nothing" (main: 0, silently).
  missing    a cache directory that does not exist: 2, and the message says the directory does not exist.
  one-page   one program's roster page cached: that program is read (returns 0); with a second, uncached program
             it still returns 0 and a `!!` line names the one not checked.
  cache-dir  roster_check --cache-dir reads the directory it is given.
  fixtures   camps_check --fixtures never reads the cache: still 0 with an empty one.
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
# CHECK_TOOLS_DIR (optional) imports the two tools from another copy - e.g. main's - to show these checks failing there.
sys.path.insert(0, os.environ.get("CHECK_TOOLS_DIR") or os.path.join(ROOT, "tools"))
import camps_check  # noqa: E402
import roster_check  # noqa: E402
from collect import common  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sidearm", "roster-head-soccer-coach.html")
FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail="") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:400]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


@contextlib.contextmanager
def cache_dir(path: str):
    old = common.CACHE_DIR
    common.CACHE_DIR = path
    try:
        yield
    finally:
        common.CACHE_DIR = old


def call(main, argv) -> tuple[int, str]:
    """(exit code, stdout) of a tool's main(); an argparse exit (SystemExit) is returned as its code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            rc = main(argv)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
    return rc, buf.getvalue()


REG = common.load_registry()
# Two programs both tools would read a roster page for: an athletics site, no camps link in the registry, no skipReason.
PICK = [p for p in common.iter_programs(REG)
        if (p.get("athletics") or {}).get("baseUrl") and not p["athletics"].get("campsUrl") and not p["athletics"].get("skipReason")][:2]


def roster_url(tool, program) -> str:
    """The URL the tool itself asks the cache for, recorded from its own cached_body call."""
    seen = []
    orig = tool.cached_body
    tool.cached_body = lambda url: seen.append(url)
    try:
        tool.check(program, REG)
    finally:
        tool.cached_body = orig
    return seen[0]


def put(cache: str, url: str) -> None:
    os.makedirs(cache, exist_ok=True)
    with open(FIXTURE, "rb") as src, open(os.path.join(cache, common._cache_key("GET", url, None) + ".body"), "wb") as dst:
        dst.write(src.read())


TOOLS = (("roster_check", roster_check.main, []), ("camps_check sweep", camps_check.main, []))


def test_empty(tmp):
    print("empty: an empty cache checks nothing")
    empty = os.path.join(tmp, "empty")
    os.makedirs(empty)
    with cache_dir(empty):
        for name, main, argv in TOOLS:
            rc, out = call(main, argv)
            ok(f"{name}: exit 2", rc == 2, (rc, out[-300:]))
            ok(f"{name}: says it checked nothing, names the cache and the remedy",
               "checked nothing" in out and empty in out and "--cache-dir" in out, out[-400:])


def test_missing(tmp):
    print("missing: a cache directory that does not exist")
    gone = os.path.join(tmp, "no-such-cache")
    with cache_dir(gone):
        for name, main, argv in TOOLS:
            rc, out = call(main, argv)
            ok(f"{name}: exit 2", rc == 2, (rc, out[-300:]))
            ok(f"{name}: says the directory does not exist", "checked nothing" in out and "does not exist" in out, out[-400:])


def test_one_page(tmp):
    print("one-page: a cache holding one program's roster page")
    ok("fixture: two programs to use, and the committed roster page", len(PICK) == 2 and os.path.exists(FIXTURE), PICK)
    a, b = PICK[0]["slug"], PICK[1]["slug"]
    for name, tool in (("roster_check", roster_check), ("camps_check sweep", camps_check)):
        cache = os.path.join(tmp, f"one-{tool.__name__}")
        put(cache, roster_url(tool, PICK[0]))
        with cache_dir(cache):
            rc, out = call(tool.main, ["--slug", a])
            line = next((l for l in out.splitlines() if l.startswith(a)), "")
            ok(f"{name}: the cached program is read (not not-cached) and the run passes", rc == 0 and line and "not-cached" not in line,
               (rc, line, out[-300:]))
            ok(f"{name}: no `!!` line when everything selected was read", "!!" not in out, out[-300:])
            rc, out = call(tool.main, ["--slug", f"{a},{b}"])
            ok(f"{name}: a partial cache still passes", rc == 0, (rc, out[-300:]))
            ok(f"{name}: and names the program it did not check", f"!! not checked: 1 of 2" in out and b in out, out[-300:])
            ok(f"{name}: no player row is printed", '"name"' not in out and "sample" not in out)


def test_cache_dir(tmp):
    print("cache-dir: roster_check reads the directory it is given")
    cache = os.path.join(tmp, "flag-cache")
    put(cache, roster_url(roster_check, PICK[0]))
    with cache_dir(os.path.join(tmp, "elsewhere")):
        rc, out = call(roster_check.main, ["--slug", PICK[0]["slug"], "--cache-dir", cache])
    ok("--cache-dir: the program is read from that directory", rc == 0 and "not-cached" not in out and "checked nothing" not in out,
       (rc, out[-300:]))


def test_fixtures(tmp):
    print("fixtures: camps_check --fixtures does not need the cache")
    empty = os.path.join(tmp, "empty-for-fixtures")
    os.makedirs(empty)
    with cache_dir(empty):
        rc, out = call(camps_check.main, ["--fixtures"])
    ok("--fixtures with an empty cache: still exit 0", rc == 0, out[-300:])
    ok("--fixtures: never says it checked nothing", "checked nothing" not in out)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    tmp = tempfile.mkdtemp(prefix="check-tools-cache-")
    try:
        for case in (test_empty, test_missing, test_one_page, test_cache_dir, test_fixtures):
            try:
                case(tmp)
            except Exception as e:  # a case that raises is a failed case, not a lost run
                ok(f"{case.__name__} ran to the end", False, f"{type(e).__name__}: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
