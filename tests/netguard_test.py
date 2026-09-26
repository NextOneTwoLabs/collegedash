"""The suite-wide network guard (issue #345): tests/netguard/sitecustomize.py, ported from ecnl-dashboard.

    python tests/netguard_test.py            # every check
    python tests/netguard_test.py --verbose

The collectors swallow fetch errors by design (a failed page is logged and skipped), so a test that reached for the
network could still pass. The guard turns any such attempt into a failed run: at exit the process fails with 97.
Each check spawns a child Python with the guard, the way .github/scripts/run_suite.py runs every suite, makes a
deliberate unmocked request to a `.invalid` host (so even a broken guard could reach nothing), swallows the error
the way a collector does, and expects the process to fail at exit.

  loaded      this run itself has the guard when it runs under the runner (and must, in CI)
  refused     an unmocked collect.common.fetch and a raw socket each fail the child with 97, error swallowed
  dead proxy  a request routed through the dead proxy is refused as well
  clean       importing the collectors, the build and the local server, with no request, exits 0
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".github", "scripts"))
from run_suite import DEAD_PROXY, GUARD_DIR  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False
PROXY_KEYS = {"https_proxy", "http_proxy", "all_proxy", "no_proxy"}


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:400]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def run_child(code: str, proxy: bool) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k.lower() not in PROXY_KEYS and k not in ("NETGUARD_REPORT", "PYTHONPATH")}
    env.update(PYTHONPATH=GUARD_DIR, PYTHONIOENCODING="utf-8", COLLEGEDASH_MIN_GAP="0")
    if proxy:
        env.update(HTTPS_PROXY=DEAD_PROXY, HTTP_PROXY=DEAD_PROXY)
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


UNMOCKED_FETCH = """
from collect import common
try:
    common.fetch("https://netguard-proof.invalid/roster", max_age_hours=None, retries=1)
except Exception as e:
    print("swallowed:", type(e).__name__)
"""

RAW_SOCKET = """
import socket
try:
    socket.create_connection(("192.0.2.1", 443), timeout=2)
except Exception as e:
    print("swallowed:", type(e).__name__)
"""


def test_loaded() -> None:
    print("loaded: the guard is on in this run when the runner starts it")
    loaded = getattr(sys.modules.get("sitecustomize"), "NETGUARD_ACTIVE", False)
    if os.environ.get("GITHUB_ACTIONS"):
        ok("CI runs this suite with the guard (PYTHONPATH=tests/netguard)", loaded)
    else:
        ok("the guard is loaded, or this is a bare local run", loaded or "tests/netguard" not in os.environ.get("PYTHONPATH", ""))


def test_refused() -> None:
    print("refused: an unmocked request fails the run at exit, even when the caller swallows the error")
    for proxy in (True, False):
        r = run_child(UNMOCKED_FETCH, proxy)
        ok(f"common.fetch swallowed by the caller (dead proxy {proxy})", "swallowed:" in r.stdout, r.stdout + r.stderr[-400:])
        ok(f"common.fetch fails the child with 97 (dead proxy {proxy})", r.returncode == 97, (r.returncode, r.stderr[-400:]))
        ok(f"and says what it refused (dead proxy {proxy})", "network attempt(s) refused" in r.stderr
           and ("127.0.0.1:9" if proxy else "netguard-proof.invalid") in r.stderr, r.stderr[-400:])
    r = run_child(RAW_SOCKET, proxy=True)
    ok("a raw socket to a non-loopback address fails the child with 97", "swallowed:" in r.stdout and r.returncode == 97,
       (r.returncode, r.stdout, r.stderr[-300:]))


def test_clean() -> None:
    print("clean: no request, no failure")
    r = run_child("import collegedash, build, serve; from collect import common, athletics_site, camps, wikipedia; print('ok')", proxy=True)
    ok("importing the collectors, the build and the server exits 0", (r.returncode, r.stdout.strip()) == (0, "ok"), (r.returncode, r.stderr[-400:]))
    ok("and the guard printed nothing", "netguard" not in r.stderr, r.stderr[-300:])


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for t in (test_loaded, test_refused, test_clean):
        t()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
