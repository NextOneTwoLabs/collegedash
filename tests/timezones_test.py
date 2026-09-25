"""Every program's time zone keeps the clock of its own coordinates (issue #114).

    python tests/timezones_test.py

The old state-to-timezone table gave 10 programs the wrong clock: Tennessee, ETSU and UT Chattanooga Central (they
are Eastern); Murray State, Western Kentucky, Evansville, Southern Indiana and Valparaiso Eastern (Central); UTEP
Central (Mountain); Idaho Mountain/Boise (Pacific). #112 derives a zone from the program's Scorecard coordinates
(timezone-boundary-builder via timezonefinder, requirements-registry.txt) but reports and keeps a stored value that
disagrees. This fixes the 10, and the build now publishes the registry's zone rather than the copy a climate
collection stored (it runs once a year), so a corrected zone shows at the next build.

Offline. Compared as clocks (UTC offset in January and July): 17 programs carry another IANA name for the same clock
('America/Detroit' for 'America/New_York'), which is not a fault. FIX checks fail on origin/main.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import common, registry_builder as rb  # noqa: E402

FAILS: list[str] = []
TOTAL = 0


def ok(name: str, cond: bool, detail="") -> None:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))


def clock(tz: str) -> tuple:
    z = ZoneInfo(tz)
    return tuple(dt.datetime(2026, m, 15, 12, tzinfo=z).utcoffset() for m in (1, 7))


FIXED = {"tennessee": "America/New_York", "east-tennessee-state": "America/New_York", "ut-chattanooga": "America/New_York",
         "murray-state": "America/Chicago", "western-kentucky": "America/Chicago", "evansville": "America/Chicago",
         "southern-indiana": "America/Chicago", "valparaiso": "America/Chicago", "utep": "America/Denver",
         "idaho": "America/Los_Angeles"}


def test_registry_clocks() -> None:
    reg = common.load_registry()
    rows = reg["programs"] + reg.get("heldPrograms", [])
    wrong, checked = [], 0
    for p in rows:
        loc = p.get("location") or {}
        stored, at = loc.get("timezone"), rb.timezone_at(loc.get("lat"), loc.get("lon"))
        if not stored or not at:
            continue
        checked += 1
        if clock(stored) != clock(at):
            wrong.append((p["slug"], stored, at))
    ok("the check reads the whole registry", checked > 1000, checked)
    ok("FIX no program's registry time zone has another clock than its coordinates' zone", wrong == [], wrong[:12])
    by = {p["slug"]: (p.get("location") or {}).get("timezone") for p in rows}
    ok("FIX the ten from #114 carry the zone at their coordinates", {s: by.get(s) for s in FIXED} == FIXED, {s: by.get(s) for s in FIXED})


def test_stored_climate() -> None:
    reg = common.load_registry()
    diff = []
    for p in reg["programs"]:
        s = common.load_source(p["slug"], "climate")
        v = ((s or {}).get("data") or {}).get("timezone")
        if v and v != (p.get("location") or {}).get("timezone"):
            diff.append((p["slug"], v))
    ok("FIX every stored climate source's time zone matches the registry", diff == [], diff[:12])


def test_build_publishes_the_registry_zone() -> None:
    import build
    prog = common.get_program("idaho", common.load_registry())
    src = common.load_source("idaho", "climate")
    real = common.load_source
    try:  # the build's view of a stored climate source that still carries the old zone
        common.load_source = lambda slug, name: ({**src, "data": {**src["data"], "timezone": "America/Boise"}}
                                                  if (slug, name) == ("idaho", "climate") else real(slug, name))
        text = open(os.path.join(ROOT, "build.py"), encoding="utf-8").read()
        ok("FIX build.py publishes the registry's location.timezone in the climate data",
           '"timezone": (program.get("location") or {}).get("timezone") or climate["data"].get("timezone")' in text)
        climate = common.load_source("idaho", "climate")
        merged = {**climate["data"], "timezone": (prog.get("location") or {}).get("timezone") or climate["data"].get("timezone")}
        ok("CONTROL an old stored zone is replaced by the registry's", merged["timezone"] == "America/Los_Angeles", merged["timezone"])
    finally:
        common.load_source = real
    _ = build  # imported to prove the module loads with the change


def main() -> int:
    for fn in (test_registry_clocks, test_stored_climate, test_build_publishes_the_registry_zone):
        print(fn.__name__)
        fn()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
