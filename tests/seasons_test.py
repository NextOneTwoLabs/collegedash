"""Regression tests for season history and RPI ranks: the loader, the join, and the invariant.

    python tests/seasons_test.py            # everything below, offline
    python tests/seasons_test.py --verbose  # print every check, not only the failures

Offline: reads the committed sources and the committed RPI tables, makes no request, and writes
only into temporary directories. The published-output checks assert on a build run into a scratch
directory rather than on the committed public/data tree, because the data is rebuilt and committed
by the daily CI refresh and not by the pull request that changes the code. Exit 0 when every check
passes, 1 otherwise.

Issue #3: build_seasons used to iterate the season rows Wikipedia and the athletics schedule had
already created, so the RPI tables could decorate a season but never create one. 173 of 350
programs had no season history at all and 177 had no `lastSeason` in the list. The RPI tables now
create rows, which puts the whole weight of the feature on the join being exact and on the tables
actually being there -- hence the two guards these tests exist to hold down.

Covers, in order:
  loader      load_rpi_finals: the last snapshot per weekly/<season>/ stands as that season's final
              table, a season the Henderson archive also covers still resolves its snapshot,
              current.json is read only for the season being played, a season after the archive
              with no table raises instead of publishing 350 blank seasons, and UNPLAYED_SEASONS is
              the way past that for a season nobody played
  join        build_seasons: rows are created and not merely decorated, the match is exact on the
              curated ids with no shortName fallback, Wikipedia and the schedule keep ownership of
              `record` except where the key is present but null, and inProgress defers to a schedule
  build       what build.py publishes: 350 with seasons / any rank / lastSeason / rpiHistory, every
              lastSeason 2025 and carrying a record, and the per-program coverage of #3's examples
  flip        the time bomb: relabelling current.json as the next season must not erase the last
              one, because the finished season comes from its immutable weekly snapshot
  archive+    the maintenance landmine: extending the archive over a season a snapshot covers takes
  snapshot    the rank and must leave the record, or lastSeason falls 350 -> 173 and the Record
              column re-dashes for 177 programs the day someone curates one more sheet
  invariant   check_seasons: a hand-edited rank, a rank with no row behind it, and one archive key
              claimed by two programs are each caught, by name - and malformed profiles and an
              unreadable table set are reported rather than raised, because a validator that dies
              is not a validator
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

# The season snapshot every finished-season assertion below is anchored to. 2025 is the last
# completed season and the first one the Henderson archive does not cover, so it is exactly the
# season that only exists because of this change.
FINISHED = 2025
SNAPSHOT = os.path.join(common.RPI_OUT_DIR, "weekly", str(FINISHED), f"{FINISHED}-12-08.json")

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
    except Exception as e:  # noqa: BLE001 - the wrong exception type is still a failure
        ok(name, False, f"raised {type(e).__name__}: {e}")
        return
    ok(name, False, "did not raise")


@contextlib.contextmanager
def swapped(**dirs):
    """Point common's output directories at scratch copies for the duration of a block."""
    old = {k: getattr(common, k) for k in dirs}
    for k, v in dirs.items():
        setattr(common, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(common, k, v)


def scratch_rpi(tmp: str, *, weekly: bool = True, cur_season: int | None = None,
                archive_year: int | None = None) -> str:
    """A copy of public/data/rpi under tmp, optionally with weekly/ emptied, current.json
    relabelled, or a synthesised Henderson sheet added for a season a snapshot also covers."""
    dst = os.path.join(tmp, "rpi")
    shutil.copytree(common.RPI_OUT_DIR, dst)
    if not weekly:
        shutil.rmtree(os.path.join(dst, "weekly"))
        os.makedirs(os.path.join(dst, "weekly"))
    if cur_season is not None:
        path = os.path.join(dst, "current.json")
        doc = json.load(open(path, encoding="utf-8"))
        doc["season"] = cur_season
        json.dump(doc, open(path, "w", encoding="utf-8"))
    if archive_year is not None:
        snap = json.load(open(SNAPSHOT, encoding="utf-8"))
        # Deliberately wrong ranks, so a test can tell which table a published rank came from.
        teams = [{"team": t["school"], "rpiRank": 999 - i, "sosRank": 1, "balancedRpiRank": 1,
                  "kpiRank": 1, "masseyRank": 1, "ncaaSeed": None} for i, t in enumerate(snap["teams"])]
        json.dump({"year": archive_year, "kind": "end-of-season", "teams": teams},
                  open(os.path.join(dst, f"{archive_year}.json"), "w", encoding="utf-8"))
    return dst


def rebuild(tmp: str, rpi_dir: str | None = None) -> tuple[str, str]:
    """Build the whole site into a scratch directory; return (profiles dir, what build printed).

    The published-output checks run against a fresh build rather than against the committed
    public/data tree, because the data is rebuilt and committed by the daily CI refresh and not by
    the pull request that changes the code: on the branch, and in CI before the first refresh, the
    committed profiles are still the previous build's.
    """
    progs, commits = os.path.join(tmp, "programs"), os.path.join(tmp, "commitments")
    swap = {"PROGRAMS_OUT_DIR": progs, "COMMITS_OUT_DIR": commits}
    if rpi_dir:
        swap["RPI_OUT_DIR"] = rpi_dir
    buf = io.StringIO()
    with swapped(**swap):
        with contextlib.redirect_stdout(buf):
            build.build(common.load_registry())
    return progs, buf.getvalue()


def complaints(log: str) -> str:
    """The lines build's own validate pass prints when an invariant fails."""
    return "\n".join(l for l in log.splitlines() if l.startswith(("SEASONS ", "SCHEMA ", "RANK ", "TITLES ", "MISSING")))


def program(registry: dict, slug: str) -> dict:
    return next(p for p in common.iter_programs(registry) if p["slug"] == slug)


def profile(built: str, slug: str) -> dict:
    return json.load(open(os.path.join(built, f"{slug}.json"), encoding="utf-8"))


def season_of(rows: list[dict], year: int) -> dict:
    return next((s for s in rows if s["year"] == year), {})


# ---------- the loader ----------

def test_loader(registry: dict) -> None:
    print("loader: load_rpi_finals, its precedence and its guard")
    cur_season = registry["season"]["current"]
    ok("the registry's current season is later than the finished one",
       cur_season > FINISHED, f"current {cur_season}, finished {FINISHED}")
    ok("the weekly snapshot this change rests on is committed", os.path.isfile(SNAPSHOT), SNAPSHOT)

    finals = build.load_rpi_finals(cur_season)
    ok(f"{FINISHED} resolves, from the snapshot and not from current.json", FINISHED in finals,
       str(sorted(finals)))
    snap = json.load(open(SNAPSHOT, encoding="utf-8"))
    ok(f"{FINISHED}'s table is the last snapshot of that season, all 350 teams",
       finals[FINISHED]["teams"] == snap["teams"] and len(snap["teams"]) == 350, str(len(snap["teams"])))
    ok("today no snapshot and archive sheet cover the same season anyway",
       not (set(finals) & set(build.load_rpi_history())), str(sorted(set(finals) & set(build.load_rpi_history()))))
    cur = build.load_rpi_current()
    ok("current.json is still the finished season, so today it is excluded",
       cur["season"] == FINISHED and cur_season not in finals, f"current.json season {cur['season']}")

    tmp = tempfile.mkdtemp(prefix="seasons-loader-")
    try:
        # current.json is read only for the season being played.
        with swapped(RPI_OUT_DIR=scratch_rpi(tmp + "/played", cur_season=cur_season)):
            f = build.load_rpi_finals(cur_season)
        ok("current.json is picked up once its season is the one being played", cur_season in f, str(sorted(f)))
        ok("and the finished season still comes from its own snapshot",
           f[FINISHED]["throughGames"] == snap["throughGames"], str(f[FINISHED].get("throughGames")))

        # A Henderson sheet takes the rank, but must not take the snapshot away: archive rows carry
        # no record, and the snapshot is where the record for those seasons lives.
        with swapped(RPI_OUT_DIR=scratch_rpi(tmp + "/arch", cur_season=cur_season, archive_year=FINISHED)):
            f = build.load_rpi_finals(cur_season)
            hist = build.load_rpi_history()
        ok("a season covered by both a Henderson sheet and a snapshot still resolves its snapshot",
           FINISHED in f and FINISHED in hist, str(sorted(f)))
        ok("and it is still the real snapshot, not the synthesised sheet",
           f[FINISHED]["teams"] == snap["teams"], str(len(f[FINISHED].get("teams") or [])))

        # A season after the archive with no table at all must fail loudly.
        with swapped(RPI_OUT_DIR=scratch_rpi(tmp + "/empty", weekly=False)):
            raises("an empty weekly/ raises rather than blanking the last season",
                   FileNotFoundError, build.load_rpi_finals, cur_season)
            try:
                build.load_rpi_finals(cur_season)
            except FileNotFoundError as e:
                ok("and the message names the season it could not resolve", str(FINISHED) in str(e), str(e))
        # The gap check, not merely "did anything load": a next-season current.json must not
        # disguise the loss of the finished season's snapshot. This is issue #3's own time bomb.
        with swapped(RPI_OUT_DIR=scratch_rpi(tmp + "/gap", weekly=False, cur_season=cur_season)):
            raises("a table for the new season does not excuse a missing finished season",
                   FileNotFoundError, build.load_rpi_finals, cur_season)
            try:
                build.load_rpi_finals(cur_season)
            except FileNotFoundError as e:
                ok("and the message points at the escape hatch", "UNPLAYED_SEASONS" in str(e), str(e))

        # The escape hatch: a season nobody played has no table and never will (2020, when COVID
        # moved the women's championship to spring 2021). Naming it is the supported way through.
        with swapped(RPI_OUT_DIR=scratch_rpi(tmp + "/unplayed", weekly=False, cur_season=cur_season)):
            old = build.UNPLAYED_SEASONS
            try:
                build.UNPLAYED_SEASONS = {FINISHED}
                f = build.load_rpi_finals(cur_season)
                ok("a season listed in UNPLAYED_SEASONS is stepped over instead of failing the build",
                   FINISHED not in f and cur_season in f, str(sorted(f)))
            finally:
                build.UNPLAYED_SEASONS = old
        ok("and the hatch is empty by default, so nothing real is being waved through",
           build.UNPLAYED_SEASONS == set(), str(build.UNPLAYED_SEASONS))
        ok("a hole inside the archive needs no entry: only years above its last sheet are checked",
           2020 not in build.load_rpi_history() and build.load_rpi_finals(cur_season) is not None,
           "2020 has no Henderson sheet, and today's build is clean")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- the join ----------

def test_join(registry: dict) -> None:
    print("join: build_seasons creates rows, on exact curated ids only")
    hist = build.load_rpi_history()
    finals = build.load_rpi_finals(registry["season"]["current"])
    vandy = program(registry, "vanderbilt")
    wiki = common.load_source("vanderbilt", "wikipedia")
    ath = common.load_source("vanderbilt", "athletics")

    ok("vanderbilt is one of the programs Wikipedia never gave a season table",
       not ((wiki or {}).get("data", {}).get("seasons") or []), "wikipedia seasons")
    rows = build.build_seasons(vandy, wiki, ath, hist, finals, registry)
    ok("yet it now has a season history", len(rows) > 15, f"{len(rows)} rows")
    ok("newest first", [r["year"] for r in rows] == sorted((r["year"] for r in rows), reverse=True))
    s = season_of(rows, FINISHED)
    ok(f"vanderbilt {FINISHED} is #8 at 18-4-2 from the NCAA table",
       (s.get("rpiRank"), s.get("record")) == (8, "18-4-2"), str(s))
    ok("a finished season is not marked in progress", not s.get("inProgress"), str(s.get("inProgress")))
    ok("its 2024 rank carries the Henderson provenance",
       season_of(rows, 2024).get("rpi", {}).get("source") == "end-of-season (Henderson archive)",
       str(season_of(rows, 2024).get("rpi", {}).get("source")))

    # No shortName fallback: an unknown id must lose the rank, never borrow another school's.
    blind = copy.deepcopy(vandy)
    blind["ids"]["rpiHistoryName"] = blind["ids"]["ncaaName"] = None
    ok("with both curated ids null, nothing is guessed from the shortName",
       not [r for r in build.build_seasons(blind, wiki, ath, hist, finals, registry) if r.get("rpiRank")],
       "ranks published without an id")
    typo = copy.deepcopy(vandy)
    typo["ids"]["rpiHistoryName"] = "vanderbilt"  # the archive spells it "Vanderbilt"
    ok("and the match is case-exact, not normalised",
       not [r for r in build.build_seasons(typo, wiki, ath, hist, finals, registry)
            if (r.get("rpi") or {}).get("source", "").startswith("end-of-season")],
       "a lowercased id still matched")

    # Wikipedia and the schedule keep `record`, but a key present as null is not a record.
    miami = program(registry, "miami-fl")
    mwiki = common.load_source("miami-fl", "wikipedia")
    wrow = season_of((mwiki or {}).get("data", {}).get("seasons") or [], FINISHED)
    ok(f"miami-fl's Wikipedia {FINISHED} row has the record key present and null",
       "record" in wrow and wrow["record"] is None, str(wrow.get("record", "(absent)")))
    mrows = build.build_seasons(miami, mwiki, common.load_source("miami-fl", "athletics"), hist, finals, registry)
    ok("so the NCAA record fills it (setdefault would not have)",
       season_of(mrows, FINISHED).get("record") == "7-8-3", str(season_of(mrows, FINISHED).get("record")))
    stan = build.build_seasons(program(registry, "stanford"), common.load_source("stanford", "wikipedia"),
                               common.load_source("stanford", "athletics"), hist, finals, registry)
    ok(f"a Wikipedia record is never overwritten by the D1-only NCAA one",
       season_of(stan, FINISHED).get("record") == "21-2-2", str(season_of(stan, FINISHED).get("record")))
    ok("nor is a Wikipedia ncaaResult",
       season_of(stan, FINISHED).get("ncaaResult") == "NCAA College Cup Runner-up",
       str(season_of(stan, FINISHED).get("ncaaResult")))

    # The archive wins the rank where it covers a season - but only the rank.
    tmp = tempfile.mkdtemp(prefix="seasons-join-")
    try:
        with swapped(RPI_OUT_DIR=scratch_rpi(tmp, cur_season=registry["season"]["current"], archive_year=FINISHED)):
            rows2 = build.build_seasons(vandy, wiki, ath, build.load_rpi_history(),
                                        build.load_rpi_finals(registry["season"]["current"]), registry)
        s2 = season_of(rows2, FINISHED)
        ok("where a Henderson sheet exists for a snapshotted season, the archive's rank is published",
           s2.get("rpi", {}).get("source") == "end-of-season (Henderson archive)" and s2.get("rpiRank") != 8,
           str({k: s2.get(k) for k in ("rpiRank", "rpi")}))
        ok("and the snapshot's record is still read, which archive rows do not carry",
           s2.get("record") == "18-4-2", str(s2.get("record")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- what build publishes ----------

def test_build(registry: dict, built: str, log: str) -> None:
    print("build: the profiles and index.json a fresh build publishes")
    ok("the build's own validate pass reports nothing", not complaints(log), complaints(log)[:400])
    index = json.load(open(os.path.join(built, "index.json"), encoding="utf-8"))
    rows = {r["slug"]: r for r in index["programs"]}
    ok("index.json carries 350 rows", len(rows) == 350, str(len(rows)))
    ok("350 rows have a lastSeason", sum(1 for r in rows.values() if r.get("lastSeason")) == 350,
       str(sum(1 for r in rows.values() if r.get("lastSeason"))))
    ok("350 rows have an rpiHistory", sum(1 for r in rows.values() if r.get("rpiHistory")) == 350,
       str(sum(1 for r in rows.values() if r.get("rpiHistory"))))
    ok(f"every lastSeason is {FINISHED}",
       all(r["lastSeason"]["year"] == FINISHED for r in rows.values()),
       str(sorted({r["lastSeason"]["year"] for r in rows.values()})))
    ok("and every one carries a record, so the list's Record column has no dashes",
       all(r["lastSeason"].get("record") for r in rows.values()),
       str([s for s, r in rows.items() if not r["lastSeason"].get("record")][:5]))
    ok("and a rank, so the list's # column has none either",
       all(r["lastSeason"].get("rpiRank") for r in rows.values()),
       str([s for s, r in rows.items() if not r["lastSeason"].get("rpiRank")][:5]))

    n_seasons = n_rank = 0
    for slug in rows:
        ss = profile(built, slug)["seasons"]
        n_seasons += bool(ss)
        n_rank += any(s.get("rpiRank") for s in ss)
    ok("350 profiles have season history", n_seasons == 350, str(n_seasons))
    ok("350 profiles have at least one RPI rank", n_rank == 350, str(n_rank))

    # Issue #3's own examples, and the coverage each one is expected to have.
    for slug, ranked in (("alcorn-state", 17), ("utrgv", 10), ("new-haven", 1), ("vanderbilt", 18)):
        got = [s["year"] for s in profile(built, slug)["seasons"] if s.get("rpiRank")]
        ok(f"{slug} publishes {ranked} ranked seasons", len(got) == ranked, str(sorted(got)))
    ok("new-haven, a 2025 D1 newcomer, has that one season and no earlier claim",
       [s["year"] for s in profile(built, "new-haven")["seasons"]] == [FINISHED],
       str([s["year"] for s in profile(built, "new-haven")["seasons"]]))
    ok("alcorn-state's ranks come from the AlcornState archive key the registry now names",
       (registry and program(registry, "alcorn-state")["ids"]["rpiHistoryName"] == "AlcornState"),
       str(program(registry, "alcorn-state")["ids"]["rpiHistoryName"]))
    ok("utrgv's 2014 season stays unclaimed, being filed under TexasPanAmerican",
       2014 not in [s["year"] for s in profile(built, "utrgv")["seasons"] if s.get("rpiRank")])

    v = rows["vanderbilt"]["lastSeason"]
    ok(f"vanderbilt's list row is {FINISHED}, #8, 18-4-2",
       (v["year"], v["rpiRank"], v["record"]) == (FINISHED, 8, "18-4-2"), str(v))
    m = rows["miami-fl"]["lastSeason"]
    ok(f"miami-fl's list row is {FINISHED}, #76, 7-8-3", (m["rpiRank"], m["record"]) == (76, "7-8-3"), str(m))
    st = profile(built, "stanford")
    ok("stanford, which already had a full history, keeps its 43 seasons", len(st["seasons"]) == 43,
       str(len(st["seasons"])))
    ok("and its live season is still the one being played, from the schedule",
       season_of(st["seasons"], registry["season"]["current"]).get("inProgress") is True,
       str(season_of(st["seasons"], registry["season"]["current"])))


# ---------- the time bomb ----------

def test_flip(registry: dict) -> None:
    """collect/rpi.py overwrites current.json with the new season the day the NCAA posts its first
    table. Before this change that erased every program's finished season; it must not now."""
    print("flip: relabelling current.json as the next season keeps the finished one")
    cur_season = registry["season"]["current"]
    tmp = tempfile.mkdtemp(prefix="seasons-flip-")
    try:
        built, log = rebuild(tmp, scratch_rpi(tmp, cur_season=cur_season))
        rows = {r["slug"]: r for r in json.load(open(os.path.join(built, "index.json"), encoding="utf-8"))["programs"]}
        vandy = profile(built, "vanderbilt")
        ok("the rebuild still validates", not complaints(log), complaints(log)[:400])
        ok("still 350 rows with a lastSeason",
           sum(1 for r in rows.values() if r.get("lastSeason")) == 350,
           str(sum(1 for r in rows.values() if r.get("lastSeason"))))
        ok("still 350 with an rpiHistory", sum(1 for r in rows.values() if r.get("rpiHistory")) == 350,
           str(sum(1 for r in rows.values() if r.get("rpiHistory"))))
        ok(f"lastSeason is still {FINISHED} everywhere, not the newly labelled season",
           {r["lastSeason"]["year"] for r in rows.values()} == {FINISHED},
           str(sorted({r["lastSeason"]["year"] for r in rows.values()})))
        ok("and still carries a record everywhere",
           all(r["lastSeason"].get("record") for r in rows.values()))
        s = season_of(vandy["seasons"], FINISHED)
        ok(f"vanderbilt {FINISHED} survives as #8, 18-4-2, not in progress",
           (s.get("rpiRank"), s.get("record"), s.get("inProgress")) == (8, "18-4-2", None), str(s))
        nxt = season_of(vandy["seasons"], cur_season)
        ok(f"and the newly labelled {cur_season} is the in-progress season",
           nxt.get("inProgress") is True, str(nxt))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- the maintenance landmine ----------

def test_archive_extended(registry: dict) -> None:
    """Someone adds next year's Henderson sheet to registry.sources.rpiHistory.sheets - 17 curated
    entries, and extending them is the ordinary maintenance action - and the archive starts covering
    a season a weekly snapshot also covers.

    That must not half-revert issue #3. Archive rows carry a rank and no record, so a build that
    lets the archive displace the snapshot outright published 173 lastSeasons instead of 350 and
    put the dash back in the Record column for 177 programs - the feature quietly undoing itself
    because the data got *better*, with no guard firing. The archive's rank still wins; the
    snapshot's record is still read.
    """
    print("archive+snapshot: adding a Henderson sheet for a snapshotted season must not blank records")
    cur_season = registry["season"]["current"]
    tmp = tempfile.mkdtemp(prefix="seasons-arch-")
    try:
        built, log = rebuild(tmp, scratch_rpi(tmp, cur_season=cur_season, archive_year=FINISHED))
        rows = {r["slug"]: r for r in json.load(open(os.path.join(built, "index.json"), encoding="utf-8"))["programs"]}
        ok("the rebuild still validates", not complaints(log), complaints(log)[:400])
        ok("still 350 rows with a lastSeason, not 173",
           sum(1 for r in rows.values() if r.get("lastSeason")) == 350,
           str(sum(1 for r in rows.values() if r.get("lastSeason"))))
        ok(f"every lastSeason is still {FINISHED}",
           {r["lastSeason"]["year"] for r in rows.values()} == {FINISHED},
           str(sorted({r["lastSeason"]["year"] for r in rows.values()})))
        dashes = [s for s, r in rows.items() if not r["lastSeason"].get("record")]
        ok("and the Record column stays full: 0 dashes, not 177", not dashes, f"{len(dashes)}: {dashes[:5]}")
        ok("every row still has a rank too", all(r["lastSeason"].get("rpiRank") for r in rows.values()),
           str([s for s, r in rows.items() if not r["lastSeason"].get("rpiRank")][:5]))
        ok("still 350 with an rpiHistory", sum(1 for r in rows.values() if r.get("rpiHistory")) == 350,
           str(sum(1 for r in rows.values() if r.get("rpiHistory"))))

        # The synthesised sheet's ranks are deliberately wrong, so a published rank names its source.
        v = season_of(profile(built, "vanderbilt")["seasons"], FINISHED)
        ok(f"vanderbilt {FINISHED} publishes the archive's rank, not the snapshot's #8",
           v.get("rpiRank") not in (None, 8)
           and v.get("rpi", {}).get("source") == "end-of-season (Henderson archive)", str(v))
        ok("while its record still comes from the snapshot", v.get("record") == "18-4-2", str(v.get("record")))
        ok("and the list row agrees with the profile",
           (rows["vanderbilt"]["lastSeason"]["rpiRank"], rows["vanderbilt"]["lastSeason"]["record"])
           == (v["rpiRank"], "18-4-2"), str(rows["vanderbilt"]["lastSeason"]))
        ok("a program with no Wikipedia history keeps the season it only has from RPI",
           season_of(profile(built, "utrgv")["seasons"], FINISHED).get("record"),
           str(season_of(profile(built, "utrgv")["seasons"], FINISHED)))
        ok("a Wikipedia record still outranks both tables",
           season_of(profile(built, "stanford")["seasons"], FINISHED).get("record") == "21-2-2",
           str(season_of(profile(built, "stanford")["seasons"], FINISHED).get("record")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- the invariant ----------

def _check(tmp: str, profiles: dict[str, dict], programs: list[dict]) -> tuple[bool, str]:
    """Run check_seasons over a scratch profiles directory and return (passed, what it printed)."""
    for slug, p in profiles.items():
        common.write_json(os.path.join(tmp, f"{slug}.json"), p)
    reg = {"season": {"current": common.load_registry()["season"]["current"]}, "programs": programs}
    buf = io.StringIO()
    with swapped(PROGRAMS_OUT_DIR=tmp):
        with contextlib.redirect_stdout(buf):
            passed = build.check_seasons(reg)
    return passed, buf.getvalue().strip()


def test_invariant(registry: dict, built: str) -> None:
    print("invariant: check_seasons traces every published rank to the program's own row")
    with swapped(PROGRAMS_OUT_DIR=built):
        ok("it passes over everything the build just published", build.check_seasons(registry))

    vandy = program(registry, "vanderbilt")
    entry = {"slug": "vanderbilt", "onboarded": True, "ids": vandy["ids"]}
    good = {"slug": "vanderbilt", "seasons": profile(built, "vanderbilt")["seasons"]}
    tmp = tempfile.mkdtemp(prefix="seasons-check-")
    try:
        passed, out = _check(os.path.join(tmp, "a"), {"vanderbilt": good}, [entry])
        ok("a faithful profile passes", passed and not out, out)

        bent = copy.deepcopy(good)
        season_of(bent["seasons"], 2024)["rpiRank"] = 1
        passed, out = _check(os.path.join(tmp, "b"), {"vanderbilt": bent}, [entry])
        ok("a hand-edited rank is caught, by name",
           not passed and "SEASONS vanderbilt:" in out and "2024" in out, out)

        # A rank for a year no table has a row for under this program's own ids.
        invented = copy.deepcopy(good)
        invented["seasons"].append({"year": 1999, "label": "1999", "rpiRank": 12})
        passed, out = _check(os.path.join(tmp, "c"), {"vanderbilt": invented}, [entry])
        ok("a rank with no row behind it is caught", not passed and "no 1999 row" in out, out)

        # A mistyped registry id points a program at a key that is not its own.
        stolen = {"slug": "vanderbilt", "onboarded": True,
                  "ids": {**vandy["ids"], "rpiHistoryName": "Virginia", "ncaaName": "Virginia"}}
        passed, out = _check(os.path.join(tmp, "d"), {"vanderbilt": good}, [stolen])
        ok("a rank taken from another school's row is caught", not passed and "SEASONS vanderbilt:" in out, out)

        # Two programs claiming one archive key.
        twin = {"slug": "vanderbilt-2", "onboarded": True, "ids": vandy["ids"]}
        passed, out = _check(os.path.join(tmp, "e"),
                             {"vanderbilt": good, "vanderbilt-2": {"slug": "vanderbilt-2", "seasons": []}},
                             [entry, twin])
        ok("one archive key claimed by two programs is caught, naming both",
           not passed and "is claimed by vanderbilt, vanderbilt-2" in out, out)
        ok("and the same is checked for the NCAA key", "ncaaName" in out, out)

        # Malformed input is exactly what a validator exists to find, so it must report it rather
        # than die on it. Each of these used to raise AttributeError or TypeError out of validate.
        for name, prof, want in (
            ("`seasons` as an object instead of a list",
             {"slug": "vanderbilt", "seasons": {"2025": {"year": 2025, "rpiRank": 8}}}, "not a list"),
            ("a non-object entry in the seasons list",
             {"slug": "vanderbilt", "seasons": [{"year": 2024, "rpiRank": 3}, "2025"]}, "not an object"),
            ("a season whose year is not a number",
             {"slug": "vanderbilt", "seasons": [{"year": ["2025"], "rpiRank": 8}]}, "year"),
        ):
            passed, out = _check(os.path.join(tmp, name[:6].replace(" ", "_")), {"vanderbilt": prof}, [entry])
            ok(f"{name} is reported, not raised",
               not passed and want in out and "SEASONS vanderbilt:" in out, out)

        strung = copy.deepcopy(good)
        season_of(strung["seasons"], 2024)["rpiRank"] = str(season_of(good["seasons"], 2024)["rpiRank"])
        passed, out = _check(os.path.join(tmp, "str"), {"vanderbilt": strung}, [entry])
        ok("a string rank is reported as a type, not as a value equal to itself",
           not passed and "str" in out and "its own row is" not in out, out)

        # A loader that cannot read its tables must also report rather than raise.
        empty = tempfile.mkdtemp(prefix="seasons-norpi-")
        with swapped(RPI_OUT_DIR=os.path.join(empty, "gone")):
            passed, out = _check(os.path.join(tmp, "f"), {"vanderbilt": good}, [entry])
        shutil.rmtree(empty, ignore_errors=True)
        ok("an unreadable RPI table set is reported, not raised",
           not passed and out.startswith("SEASONS:"), out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    ap.add_argument("--skip-flip", action="store_true",
                    help="skip the two extra full rebuilds the flip and archive+snapshot tests need")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose

    registry = common.load_registry()
    test_loader(registry)
    test_join(registry)
    tmp = tempfile.mkdtemp(prefix="seasons-build-")
    try:
        built, log = rebuild(tmp)
        test_build(registry, built, log)
        if not args.skip_flip:
            test_flip(registry)
            test_archive_extended(registry)
        test_invariant(registry, built)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed"
          + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
