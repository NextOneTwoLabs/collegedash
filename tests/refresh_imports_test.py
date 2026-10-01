"""The data refresh never needs `timezonefinder` (issue #121).

    python tests/refresh_imports_test.py

The refresh workflow installs requirements.txt only; `timezonefinder` is in requirements-registry.txt, which only the
registry builder needs (collect/registry_builder.py's timezone_at imports it on first use). This was guarded by a string
match on the requirements and workflow files, which would miss the dependency arriving indirectly - a new import at the
top of a module the refresh loads. Now the check runs the refresh's own code paths, in a child process whose import
system refuses `timezonefinder` exactly as the refresh's environment would, and records every attempt:

  refresh-path   imports collegedash and every collector module the refresh runs, plans `refresh --dry-run`, and runs
                 build.validate over the committed registry and data (which loads registry_builder for its staged-
                 division check - that import is fine, timezonefinder is not). Nothing may ask for timezonefinder.
  watcher-bites  the same watcher, around registry_builder.timezone_at(), does record the attempt and raise
                 ImportError, so the check above cannot pass by watching nothing.

Offline (COLLEGEDASH_OFFLINE=1): the dry run plans and fetches nothing, and validate only reads.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS: list[str] = []
TOTAL = 0

WATCHER = r"""
import importlib.abc, json, os, sys
ASKED = []
class _RefuseTimezonefinder(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "timezonefinder" or name.startswith("timezonefinder."):
            ASKED.append(name)
            raise ModuleNotFoundError(f"No module named {name!r} (the refresh does not install it)", name=name)
        return None
sys.meta_path.insert(0, _RefuseTimezonefinder())
for _m in [m for m in sys.modules if m == "timezonefinder" or m.startswith("timezonefinder.")]:
    del sys.modules[_m]
os.environ["COLLEGEDASH_OFFLINE"] = "1"
sys.path.insert(0, ROOT)
os.chdir(ROOT)
"""

REFRESH_PATH = r"""
import contextlib, io
out = {"asked": None}
import collegedash
from collect import scorecard, climate, wikipedia, athletics_site, commitments_tds, commitments_soccerwire, news, camps, rpi
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    out["dry_run_exit"] = collegedash.main(["refresh", "--dry-run"])
out["planned"] = sum(1 for line in buf.getvalue().splitlines() if line.startswith("-- "))
import build
from collect import common
with contextlib.redirect_stdout(io.StringIO()):
    build.validate(common.load_registry())
out["validate_ran"] = True
out["registry_builder_loaded"] = "collect.registry_builder" in sys.modules
out["asked"] = ASKED
print("RESULT " + json.dumps(out))
"""

WATCHER_BITES = r"""
out = {}
from collect import registry_builder
try:
    registry_builder.timezone_at(30.5, -87.2)
    out["raised"] = False
except ImportError:
    out["raised"] = True
out["asked"] = ASKED
print("RESULT " + json.dumps(out))
"""


def ok(name: str, cond: bool, detail="") -> None:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:600]}" if detail else ""))


def child(body: str) -> dict:
    code = f"ROOT = {ROOT!r}\n" + WATCHER + body
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=600, env=dict(os.environ, COLLEGEDASH_OFFLINE="1", PYTHONIOENCODING="utf-8"))
    line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT ")), None)
    if line is None:
        return {"error": (p.stderr or p.stdout)[-1500:]}
    return json.loads(line[len("RESULT "):])


def test_refresh_path() -> None:
    print("refresh-path: the refresh's code runs with timezonefinder unavailable, and never asks for it")
    r = child(REFRESH_PATH)
    ok("the refresh path ran to the end (no ImportError anywhere in it)", "error" not in r, r.get("error"))
    if "error" in r:
        return
    ok("refresh --dry-run planned and exited 0", r["dry_run_exit"] == 0 and r["planned"] == 1, r)
    ok("build.validate ran over the committed data", r["validate_ran"] is True, r)
    ok("nothing on the refresh path asked for timezonefinder", r["asked"] == [], r["asked"])
    ok("CONTROL validate does load registry_builder (its staged check); that import alone pulls in no timezonefinder",
       r["registry_builder_loaded"] is True, r)


def test_watcher_bites() -> None:
    print("watcher-bites: the watcher records and refuses a real timezonefinder import")
    r = child(WATCHER_BITES)
    ok("the control child ran", "error" not in r, r.get("error"))
    if "error" in r:
        return
    ok("registry_builder.timezone_at raised ImportError under the watcher", r["raised"] is True, r)
    ok("and the watcher recorded the attempt", "timezonefinder" in r["asked"], r["asked"])


def main() -> int:
    for fn in (test_refresh_path, test_watcher_bites):
        fn()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
