"""The athletics collector stores a history schedule only when it is that season's page (issue #301).

    python tests/schedule_history_season_test.py            # everything below, offline
    python tests/schedule_history_season_test.py --verbose  # print every check, not only the failures

Some old-season schedule URLs serve another season. 29 stored history years were copies of the 2026
schedule, and gonzaga 2024 was a spring schedule. Since #287, build.schedule_valid_for keeps them out of the
published records, but the collector still stored them. collect/athletics_site.py now skips a history page
unless more than half of its dated games fall August-December of the requested year. A page with no dates
is still stored and left to the build.

  share        schedule_season_share on synthetic pages: current-season copy, spring schedule, fall season
               with a spring exhibition, exact half, undated
  collector    athletics_site.collect over a stub adapter and stub fetch (nothing touches the network or
               programs/): the real season is stored, a 2026 copy and a spring page are not and are logged,
               and an undated page is stored
  stored data  over the committed programs/*/sources/athletics.json: every history year the guard would
               drop is one build.schedule_valid_for already rejects, so the guard never removes a published
               record. Prints the before/after counts.
"""

from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import build  # noqa: E402
from collect import adapters, athletics_site, common  # noqa: E402

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


def games(*dates, result="W"):
    return [{"date": d, "opponent": f"Opp {i}", "result": result} for i, d in enumerate(dates)]


FALL_2025 = games("2025-08-21", "2025-09-04", "2025-10-12", "2025-11-02")
COPY_OF_2026 = games("2026-08-20", "2026-09-03", "2026-10-11", "2026-11-01", result=None)
SPRING_2024 = games("2024-03-15", "2024-04-02", "2024-04-09", "2024-04-20")  # the gonzaga 2024 shape
UNDATED = [{"date": None, "opponent": "Opp A", "result": "W"}, {"opponent": "Opp B", "result": "L"}]


def test_share() -> None:
    print("share: schedule_season_share")
    share = athletics_site.schedule_season_share
    ok("a fall season is all in season", share(FALL_2025, 2025) == (4, 4), share(FALL_2025, 2025))
    ok("a copy of 2026 asked for as 2023 has none in season", share(COPY_OF_2026, 2023) == (0, 4))
    ok("a spring schedule has none in season", share(SPRING_2024, 2024) == (0, 4))
    ok("December (College Cup) counts, a spring exhibition does not",
       share(games("2025-12-05", "2025-10-01", "2025-04-10"), 2025) == (2, 3))
    ok("an undated page has no dated games", share(UNDATED, 2025) == (0, 0))


# ---------- collector ----------

PROGRAM = {"slug": "fixture", "name": "Fixture University", "division": "D1",
           "athletics": {"platform": "fixture", "baseUrl": "https://example.invalid", "sportPath": "/sports/wsoc"}}
REGISTRY = {"season": {"current": 2026}}


def collect(pages: dict[str, list[dict]]) -> tuple[dict, list[str]]:
    """athletics_site.collect with a stub adapter: `pages` maps a schedule URL to the games it parses to."""
    saved, logs = {}, []
    ad = types.SimpleNamespace(
        urls=lambda program, registry: {"roster": "roster", "rosterSeason": lambda y: f"roster/{y}",
                                        "schedule": "schedule", "scheduleSeason": lambda y: f"schedule/{y}"},
        parse_roster=lambda html, base: {"season": 2026, "players": [{"name": "A Player"}] if html == "roster" else [],
                                         "staff": [{"name": "A Coach", "title": "Head Coach"}]},
        parse_schedule=lambda html, base: {"season": 2026 if html == "schedule" else None,
                                           "games": copy.deepcopy(pages.get(html, []))})

    def fetch_text(url, **_):
        return url, {"fromCache": True}

    def save_source(slug, name, data, *, url, collector, extra=None):
        saved["data"] = data

    real = (adapters.get, common.fetch_text, common.save_source, common.load_source, common.log)
    adapters.get = lambda platform: ad
    common.fetch_text, common.save_source, common.load_source, common.log = (
        fetch_text, save_source, (lambda slug, name: None), logs.append)
    try:
        athletics_site.collect(copy.deepcopy(PROGRAM), REGISTRY, seasons_back=3, bios=False)
    finally:
        adapters.get, common.fetch_text, common.save_source, common.load_source, common.log = real
    return saved.get("data") or {}, logs


def test_collector() -> None:
    print("collector: which history years athletics_site.collect stores")
    data, logs = collect({"schedule": games("2026-08-20"), "schedule/2025": FALL_2025,
                          "schedule/2024": SPRING_2024, "schedule/2023": COPY_OF_2026})
    hist = data.get("scheduleHistory")
    ok("the real 2025 season is stored", hist.get("2025") == FALL_2025, sorted(hist or {}))
    ok("FIX the spring page asked for as 2024 is not stored", "2024" not in hist, sorted(hist))
    ok("FIX the 2026 copy asked for as 2023 is not stored", "2023" not in hist, sorted(hist))
    ok("each skipped year is logged with its count",
       any("2024 schedule not stored: 0 of 4" in m for m in logs) and any("2023 schedule not stored: 0 of 4" in m for m in logs),
       [m for m in logs if "schedule" in m])
    ok("the current schedule is untouched", data.get("schedule", {}).get("games") == games("2026-08-20"))

    data, _ = collect({"schedule": games("2026-08-20"), "schedule/2025": UNDATED})
    ok("an undated page is stored (the build places it)", data.get("scheduleHistory", {}).get("2025") == UNDATED)
    data, _ = collect({"schedule": games("2026-08-20"), "schedule/2025": games("2025-09-01", "2026-09-01")})
    ok("exactly half in season is not stored, as in build.schedule_valid_for", "2025" not in data.get("scheduleHistory", {}))


# ---------- stored data ----------

def test_stored_data() -> None:
    print("stored data: the guard only drops years the build already rejects")
    years = build_rejects = 0
    dropped, dropped_but_published = [], []
    for path in sorted(glob.glob(os.path.join(ROOT, "programs", "*", "sources", "athletics.json"))):
        slug = os.path.basename(os.path.dirname(os.path.dirname(path)))
        d = (json.load(open(path, encoding="utf-8")).get("data") or {})
        cur = (d.get("schedule") or {}).get("games") or []
        for y, gs in (d.get("scheduleHistory") or {}).items():
            years += 1
            valid = build.schedule_valid_for(gs, int(y), cur)
            build_rejects += not valid
            fall, dated = athletics_site.schedule_season_share(gs, int(y))
            if dated and not 2 * fall > dated:
                dropped.append(f"{slug}:{y}")
                if valid:
                    dropped_but_published.append(f"{slug}:{y}")
    ok("there is stored history to check", years > 0, years)
    ok("no year the guard drops is one the build publishes", dropped_but_published == [], dropped_but_published[:10])
    print(f"  stored history years {years} -> {years - len(dropped)} after re-collection; "
          f"build.schedule_valid_for rejects {build_rejects} -> {build_rejects - len(dropped)}")


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for t in (test_share, test_collector, test_stored_data):
        t()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
