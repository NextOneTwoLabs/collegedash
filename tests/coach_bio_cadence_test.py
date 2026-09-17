"""When the head coach's bio page is fetched, and what a run that does not fetch it stores (issue #168).

    python tests/coach_bio_cadence_test.py            # everything below, offline
    python tests/coach_bio_cadence_test.py --verbose  # print every check, not only the failures

#181 reads the head coach's first season from their bio page, but the collector fetched that page only when player
bios were on, and every refresh.yml mode that collects athletics passes --no-bios. So no path ever fetched it, and
a run with bios off wrote headCoachBio: null over whatever was stored. The owner's rulings:
  - the Monday weekly and the full refresh fetch it (--coach-bios), with player bios still off;
  - `onboard` fetches it even with --no-bios;
  - a run that does not fetch it (the in-season daily) keeps the stored one;
  - a coach who has left is handled at build time: a bio is used only for the current head coach (same_person).
A coach-bio fetch that fails keeps the stored bio when there is one (chosen on #168: a transient error on a Monday
should not take a published year down for a week); with nothing stored the failed attempt is stored as before.

Offline: collect.common's fetch_text, save_source and load_source are replaced by tables (the Army roster fixture
of issue #145 and the iowa bio fixture of #181), and collegedash's collectors, rpi, build and refresh-state writes
by recorders, so nothing touches the network, programs/ or the registry.

Swap-back proof: COLLEGEDASH_CODE_ROOT=<an export of origin/main> runs these checks against that code (and reads
that export's refresh.yml).

Labels: FIX checks fail against origin/main and pass after the change; CONTROL checks pass on both.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import io
import os
import re
import shlex
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_ROOT = os.environ.get("COLLEGEDASH_CODE_ROOT") or ROOT
sys.path.insert(0, CODE_ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import collegedash  # noqa: E402
from collect import athletics_site, common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False

BASE = "https://example.invalid"
SPORT = "/sports/womens-soccer"
BIO_URL = BASE + SPORT + "/roster/coaches/tracy--chao/2425"
REGISTRY = {"season": {"current": 2026}, "onboardedDivisions": ["D1"], "sources": {"athleticsPlatforms": {"sidearm": {
    "roster": "{baseUrl}{sportPath}/roster", "rosterSeason": "{baseUrl}{sportPath}/roster/{year}",
    "schedule": "{baseUrl}{sportPath}/schedule", "scheduleSeason": "{baseUrl}{sportPath}/schedule/{year}",
    "news": "{baseUrl}{sportPath}/archives", "rss": "{baseUrl}/rss?path=wsoc"}}}}
PROGRAM = {"slug": "fixture", "name": "United States Military Academy", "shortName": "Army", "nickname": "Black Knights",
           "division": "D1", "onboarded": True, "athletics": {"platform": "sidearm", "baseUrl": BASE, "sportPath": SPORT}}
STORED = {"name": "Tracy Chao", "url": BIO_URL, "firstSeason": 2024, "conflict": False,
          "statements": [{"kind": "hired", "year": 2024, "text": "stored earlier", "school": "own"}]}


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {ascii(detail)[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def pages(with_bio: bool = True) -> dict[str, str]:
    roster = open(os.path.join(ROOT, "tests", "fixtures", "sidearm", "roster-players-and-staff.html"), encoding="utf-8").read()
    out = {BASE + SPORT + "/roster": roster, BASE + SPORT + "/schedule": "<html></html>"}
    if with_bio:
        bio = open(os.path.join(ROOT, "tests", "fixtures", "coach_bio", "iowa.html"), encoding="utf-8").read()
        out[BIO_URL] = bio.replace("Dean Ward", "Tracy Chao").replace("Ward", "Chao").replace("the University of Iowa", "Army West Point")
    return out


def collect(stored: dict | None, *, with_bio: bool = True, **kw) -> tuple[dict, list[str]]:
    """athletics_site.collect over the fixture pages with `stored` as the athletics source already on disk.
    Returns (the data it saved, every URL it requested)."""
    table, saved, requests = pages(with_bio), {}, []

    def fetch_text(url, **_):
        requests.append(url)
        if url not in table:
            raise common.FetchError(f"HTTP 404 for {url}")
        return table[url], {"url": url, "status": 200, "finalUrl": url, "fromCache": False}

    def save_source(slug, name, data, *, url, collector, extra=None):
        saved.update(copy.deepcopy(data))

    def load_source(slug, name):
        return {"data": {"headCoachBio": copy.deepcopy(stored)}} if (stored is not None and name == "athletics") else None

    real = (common.fetch_text, common.save_source, common.load_source, common.log)
    common.fetch_text, common.save_source, common.load_source, common.log = fetch_text, save_source, load_source, (lambda m: None)
    try:
        athletics_site.collect(copy.deepcopy(PROGRAM), REGISTRY, seasons_back=0, **kw)
    finally:
        common.fetch_text, common.save_source, common.load_source, common.log = real
    return saved, requests


def coach_requests(requests):
    return [u for u in requests if "/roster/coaches/" in u]


def player_bio_requests(requests):
    return [u for u in requests if re.search(r"/roster/(?!coaches/)[^/]+/\d+", u)]


def test_collector() -> None:
    print("athletics_site.collect: fetch the coach bio, or keep the stored one")
    # --- daily: player bios off, coach bios not asked for
    try:
        saved, requests = collect(STORED, bios=False)
        err = None
    except Exception as e:  # noqa: BLE001
        saved, requests, err = {}, [], e
    # fails if a run that does not fetch the coach bio writes null over the stored one (the pre-#168 behaviour)
    ok("FIX a daily run (bios off, no --coach-bios) keeps the stored headCoachBio unchanged",
       err is None and saved.get("headCoachBio") == STORED, str(err or saved.get("headCoachBio")))
    ok("CONTROL ... and requests no bio page at all", err is None and not coach_requests(requests) and not player_bio_requests(requests),
       str(err or requests))

    # --- weekly: player bios off, coach bios on
    try:
        saved, requests = collect(STORED, bios=False, coach_bios=True)
        err = None
    except TypeError as e:
        saved, requests, err = {}, [], e
    # fails if --coach-bios still depends on player bios, or fetches the coach page more than once
    ok("FIX a weekly run (--no-bios --coach-bios) requests exactly one coach bio page, the head coach's",
       err is None and coach_requests(requests) == [BIO_URL], str(err or requests))
    # fails if turning coach bios on turns player bios on too
    ok("FIX ... and zero player bio pages", err is None and not player_bio_requests(requests) and bool(saved.get("roster", {}).get("players")),
       str(err or player_bio_requests(requests)[:3]))
    ok("FIX ... and stores the fresh reading, not the stored one (the fixture says 2026, the stored bio 2024)",
       err is None and (saved.get("headCoachBio") or {}).get("firstSeason") == 2026, str(err or saved.get("headCoachBio"))[:200])

    # --- a failed coach-bio fetch
    try:
        saved, requests = collect(STORED, with_bio=False, bios=False, coach_bios=True)
        err = None
    except TypeError as e:
        saved, requests, err = {}, [], e
    # fails if a transient fetch error replaces a stored year with an attempt that has none
    ok("FIX a coach-bio fetch that fails keeps the stored bio (with its year)",
       err is None and coach_requests(requests) == [BIO_URL] and saved.get("headCoachBio") == STORED, str(err or saved.get("headCoachBio")))
    saved, requests = collect(None, with_bio=False, bios=True)
    ok("CONTROL ... and with nothing stored, the failed attempt is stored with no year, as before",
       (saved.get("headCoachBio") or {}).get("firstSeason") is None and "error" in (saved.get("headCoachBio") or {}),
       str(saved.get("headCoachBio")))
    saved, requests = collect(None, bios=True)
    ok("CONTROL player bios on still fetch the coach bio (2026) and the player bios",
       (saved.get("headCoachBio") or {}).get("firstSeason") == 2026 and coach_requests(requests) == [BIO_URL]
       and bool(player_bio_requests(requests)), str(requests[:4]))


# ---------- what each command hands the athletics collector ----------

def run_cli(argv: list[str], registry: dict) -> list[dict]:
    """collegedash.main(argv) in process with every collector, rpi, build, refresh-state and registry write replaced;
    returns the keyword arguments each athletics collector call received."""
    calls: list[dict] = []

    def fake_collect_one(name, program, registry_, **kw):
        if name == "athletics":
            calls.append({"slug": program["slug"], **kw})
        return {"program": program["slug"], "collector": name, "outcome": "ok", "error": ""}, None

    fake_rpi = types.ModuleType("collect.rpi")
    fake_rpi.history = lambda reg: None
    fake_rpi.current = lambda reg: None
    fake_build = types.ModuleType("build")
    fake_build.build = lambda reg, **kw: None
    import collect
    saved = {"collect_one": collegedash.collect_one, "record_outcomes": collegedash.record_outcomes,
             "report_refresh": collegedash.report_refresh, "_mark_onboarded": collegedash._mark_onboarded,
             "load_registry": common.load_registry, "update_refresh_state": common.update_refresh_state,
             "update_refresh_state_many": common.update_refresh_state_many, "update_registry": common.update_registry}
    saved_modules = {k: sys.modules.get(k) for k in ("collect.rpi", "build")}
    saved_rpi_attr = getattr(collect, "rpi", None)
    reg = copy.deepcopy(registry)
    try:
        collegedash.collect_one = fake_collect_one
        collegedash.record_outcomes = lambda slug, entries: True
        collegedash.report_refresh = lambda results, **kw: 0
        collegedash._mark_onboarded = lambda slug: reg
        common.load_registry = lambda: reg
        # nothing may reach public/archive/refresh-state.json or the registry file (onboard_batch records onboardBatch)
        common.update_refresh_state = lambda key, info: None
        common.update_refresh_state_many = lambda entries: None
        common.update_registry = lambda mutate: reg
        sys.modules["collect.rpi"], sys.modules["build"], collect.rpi = fake_rpi, fake_build, fake_rpi
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            collegedash.main(argv)
    finally:
        collegedash.collect_one = saved["collect_one"]
        collegedash.record_outcomes = saved["record_outcomes"]
        collegedash.report_refresh = saved["report_refresh"]
        collegedash._mark_onboarded = saved["_mark_onboarded"]
        common.load_registry = saved["load_registry"]
        common.update_refresh_state = saved["update_refresh_state"]
        common.update_refresh_state_many = saved["update_refresh_state_many"]
        common.update_registry = saved["update_registry"]
        for k, m in saved_modules.items():
            if m is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = m
        if saved_rpi_attr is None:
            if hasattr(collect, "rpi"):
                delattr(collect, "rpi")
        else:
            collect.rpi = saved_rpi_attr
    return calls


def workflow_commands() -> dict[str, list[str]]:
    """mode label -> argv of the `python collegedash.py refresh ...` line in refresh.yml that carries it."""
    text = open(os.path.join(CODE_ROOT, ".github", "workflows", "refresh.yml"), encoding="utf-8").read()
    out = {}
    for line in text.splitlines():
        m = re.search(r"python collegedash\.py (refresh .*)$", line.strip())
        if not m or "$ONLY_INPUT" in line:
            continue
        argv = shlex.split(m.group(1))
        mode = argv[argv.index("--mode") + 1] if "--mode" in argv else "?"
        key = mode if mode not in out else f"{mode}:{'athletics' if 'athletics' in m.group(1) else 'no-athletics'}"
        out[key] = argv
    return out


def coach_fetch(call: dict) -> bool:
    """Whether athletics_site.collect fetches the coach bio for these kwargs (coach_bios=None follows bios)."""
    return call.get("coach_bios") if call.get("coach_bios") is not None else call.get("bios", True)


def test_commands() -> None:
    print("the commands: refresh.yml's modes and onboard")
    progs = [dict(PROGRAM, slug="alpha"), dict(PROGRAM, slug="beta")]
    registry = {**REGISTRY, "programs": progs, "heldPrograms": []}
    cmds = workflow_commands()
    for label in ("weekly", "full"):
        argv = cmds.get(label)
        calls = run_cli(argv + ["--workers", "1"], registry) if argv else []
        # fails if the Monday weekly or the full run does not fetch the head coach's bio page
        ok(f"FIX refresh.yml's {label} run fetches each head coach's bio, with player bios off",
           len(calls) == 2 and all(coach_fetch(c) and c.get("bios") is False for c in calls), f"{argv} -> {calls}")
    daily = next((v for k, v in cmds.items() if k.startswith("daily") and "athletics" in " ".join(v)), None)
    calls = run_cli(daily + ["--workers", "1"], registry) if daily else []
    # fails if the in-season daily run starts fetching coach bio pages (option A: weekly and full only)
    ok("CONTROL refresh.yml's in-season daily run fetches no coach bio (it keeps the stored one)",
       len(calls) == 2 and not any(coach_fetch(c) for c in calls), f"{daily} -> {calls}")
    full_desc = re.search(r"full:\s*\n\s*description:\s*\"([^\"]*)\"", open(os.path.join(CODE_ROOT, ".github", "workflows", "refresh.yml"),
                                                                           encoding="utf-8").read())
    # fails if the full input still promises (player) bios it does not fetch
    ok("FIX the full input's description no longer promises bios it does not collect",
       bool(full_desc) and "head-coach bios" in full_desc.group(1) and "player bios are not fetched" in full_desc.group(1),
       full_desc.group(1) if full_desc else "no description")

    unonboarded = {**registry, "programs": [dict(p, onboarded=False) for p in progs]}
    calls = run_cli(["onboard", "alpha", "--no-bios"], unonboarded)
    # fails if onboarding a program with --no-bios leaves it with no bio year until the next Monday
    ok("FIX onboard <slug> --no-bios fetches the head coach's bio (player bios still off)",
       len(calls) == 1 and coach_fetch(calls[0]) and calls[0].get("bios") is False, str(calls))
    calls = run_cli(["onboard", "alpha", "beta", "--no-bios", "--workers", "1"], unonboarded)
    ok("FIX the batch form, onboard a b --no-bios, fetches each head coach's bio too",
       len(calls) == 2 and all(coach_fetch(c) and c.get("bios") is False for c in calls), str(calls))
    calls = run_cli(["refresh", "--only", "athletics", "--no-bios", "--workers", "1"], registry)
    ok("CONTROL a plain refresh --no-bios (a manual only=athletics) fetches no coach bio",
       len(calls) == 2 and not any(coach_fetch(c) for c in calls), str(calls))


def test_build_ignores_a_stale_bio() -> None:
    print("build: a carried-forward bio for a coach who has left is not used")
    import build  # noqa: E402
    wiki = {"data": {"seasons": [{"year": y, "label": str(y), "headCoach": "Pat Lee"} for y in range(2021, 2026)],
                     "headCoach": "Pat Lee (5th season)"}}
    staff = [{"name": "Pat Lee", "title": "Head Coach", "isHeadCoach": True, "isCoach": True, "bioUrl": BASE + "/c/pat-lee/9", "social": {}}]
    ath = {"data": {"staff": staff, "headCoachBio": copy.deepcopy(STORED)}}  # stored for Tracy Chao, who has left
    since = build.build_program_section({"slug": "fixture", "division": "D1"}, wiki, ath)["headCoach"]["since"]
    # fails if the build takes a bio year without checking it belongs to the current head coach
    ok("CONTROL a stored bio for a previous coach (Tracy Chao, 2024) is ignored: the new coach's year comes from Wikipedia (2021)",
       since == 2021, str(since))
    ath["data"]["headCoachBio"] = {**STORED, "name": "Pat Lee"}
    ok("CONTROL ... while the same bio under the current coach's name is used (2024)",
       build.build_program_section({"slug": "fixture", "division": "D1"}, wiki, ath)["headCoach"]["since"] == 2024)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    if CODE_ROOT != ROOT:
        print(f"code under test imported from {CODE_ROOT}")
    for case in (test_collector, test_commands, test_build_ignores_a_stale_bio):
        try:
            case()
        except Exception as e:  # a case that raises is a failed case, not a lost run
            ok(f"{case.__name__} ran to the end", False, f"{type(e).__name__}: {e}")
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
