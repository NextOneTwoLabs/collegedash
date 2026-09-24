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
              table, a season the archive also covers still resolves its snapshot,
              current.json is read only for the season being played, a season after the archive
              with no table raises instead of publishing 350 blank seasons, and UNPLAYED_SEASONS is
              the way past that for a season nobody played
  join        build_seasons: rows are created and not merely decorated, the match is exact on the
              curated ids with no shortName fallback, Wikipedia and the schedule keep ownership of
              `record` except where the key is present but null, and inProgress defers to a schedule
  build       what build.py publishes, measured against what each program's own data entitles it to
              (issue #110): a lastSeason with a record for every program with a record for 2025,
              an RPI rank exactly where the program has a row under its own ids, and both absent -
              correctly, and checked as such - for a program with none (a new D1 program, any D2 or D3
              one). Plus the per-program coverage of #3's examples, and an anchor that does not come
              from the ids or the loaders at all: every long-standing D1 program keeps its RPI ids, every RPI
              season it published before #110, and its 2025 lastSeason (PR #112 review, M1). And
              issue #62's rule once the NCAA's table for the season being played is live: that season
              is published with its rank but marked in progress, and never counts as a finished ranked
              season - not as lastSeason, not in the finished-season counts. The loader checks
              current.json is read exactly when it holds that season, whichever state the calendar is in
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
# completed season and the first one the archive does not cover, so it is exactly the
# season that only exists because of this change.
FINISHED = 2025
SNAPSHOT = os.path.join(common.RPI_OUT_DIR, "weekly", str(FINISHED), f"{FINISHED}-12-08.json")


def final_on_disk(registry: dict) -> tuple[int, str | None]:
    """(the finished season, the final table's through-date or None), worked out from the files alone and
    never from the build under test (issue #249, Huatuo's review): the season being played is finished
    exactly when the registry's raw finalRpiThrough date for it is set and some weekly/<season>/*.json
    snapshot's own throughGames is on or after it. Otherwise the finished season is the one before."""
    cur = registry["season"]["current"]
    date = ((registry["season"].get("finalRpiThrough") or {}).get(str(cur)))
    d = os.path.join(common.RPI_OUT_DIR, "weekly", str(cur))
    throughs = sorted(json.load(open(os.path.join(d, f), encoding="utf-8")).get("throughGames") or ""
                      for f in (os.listdir(d) if os.path.isdir(d) else []) if f.endswith(".json"))
    if date and any(t >= date for t in throughs):
        return cur, throughs[-1]
    return cur - 1, None


# The finished season the entitlement checks measure against: FINISHED (2025) until the 2026 final RPI
# is on disk, then 2026 - so the day the season ends does not turn main red. Set in main().
LAST_DONE = FINISHED
FINAL_THROUGH: str | None = None

# Long-standing D1 programs and the RPI seasons each published before issue #110 (PR #112 review, M1).
PRE_100 = os.path.join(ROOT, "tests", "fixtures", "registry", "pre-100-programs.json")
RPI_ANCHOR = os.path.join(ROOT, "tests", "fixtures", "registry", "pre-110-rpi-seasons.json")

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
    relabelled, or a synthesised archive sheet added for a season a snapshot also covers."""
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
    # Every directory build() writes to has to be in this swap. A published output missing from it
    # is not a test that fails - it is a test run that overwrites live data in public/ on the way
    # past, which is how CAMPS_OUT_DIR earned its place here the day the camps index was added.
    swap = {"PROGRAMS_OUT_DIR": progs, "COMMITS_OUT_DIR": commits,
            "CAMPS_OUT_DIR": os.path.join(tmp, "camps")}
    if rpi_dir:
        swap["RPI_OUT_DIR"] = rpi_dir
    buf = io.StringIO()
    with swapped(**swap):
        with contextlib.redirect_stdout(buf):
            build.build(common.load_registry())
    return progs, buf.getvalue()


def complaints(log: str) -> str:
    """The lines build's own validate pass prints when an invariant fails."""
    return "\n".join(l for l in log.splitlines()
                     if l.startswith(("SEASONS ", "SCHEMA ", "RANK ", "TITLES ", "CAMPS", "MISSING", "STALE ", "MEMBERSHIP")))


def program(registry: dict, slug: str) -> dict:
    return next(p for p in build.published_programs(registry) if p["slug"] == slug)


def profile(built: str, slug: str) -> dict:
    return json.load(open(os.path.join(built, f"{slug}.json"), encoding="utf-8"))


def season_of(rows: list[dict], year: int) -> dict:
    return next((s for s in rows if s["year"] == year), {})


def early_rpi_claims(seasons: list[dict], before_year: int) -> list[int]:
    """Years before `before_year` that still carry an RPI claim - an `rpiRank` or an `rpi` block -
    which is what "no earlier claim" (issue #153) actually means. Not the same question as how many
    seasons are in the list: the list may carry real pre-D1 history once schedule collection runs,
    and that history is correct data, not a leak. Only a rank or an rpi block for a year the program
    was not D1 would be the leak."""
    return sorted(s["year"] for s in seasons if s["year"] < before_year and (s.get("rpiRank") is not None or "rpi" in s))


# ---------- what each program's data entitles it to ----------

def entitlements(registry: dict, rpi_dir: str | None = None) -> dict[str, dict]:
    """slug -> what the sources and RPI tables say this program should publish, computed from the data
    and never from the build's output. Issue #110: the checks below used to assume every program was a
    long-standing D1 program with a row in every table; a new D1 program has none, nor will any D2 or D3
    program. The expectation is derived per program instead, so a program with no RPI row is asserted
    to publish no rank - absent, and correctly so - rather than skipped.

      rpiYears        seasons with a row under the program's own ids: an archive sheet keyed by
                      ids.rpiHistoryName, or an NCAA table keyed by ids.ncaaName (exact, as the build joins)
      finishedRecord  some source carries a record for LAST_DONE: its NCAA table row, a LAST_DONE schedule
                      history, the live schedule if it is LAST_DONE's, or a Wikipedia LAST_DONE record
      anySeason       any source that creates a season row at all
    """
    ctx = swapped(RPI_OUT_DIR=rpi_dir) if rpi_dir else contextlib.nullcontext()
    with ctx:
        hist = build.load_rpi_history()
        finals = build.load_rpi_finals(registry["season"]["current"])
    out = {}
    for p in build.published_programs(registry):
        ids = p.get("ids") or {}
        hname, nname = ids.get("rpiHistoryName"), ids.get("ncaaName")
        years = {y for y, table in hist.items() if hname and table.get(hname)}
        finals_rows = ({y: next((t for t in doc.get("teams") or [] if t.get("school") == nname), None)
                        for y, doc in finals.items()} if nname else {})
        years |= {y for y, row in finals_rows.items() if row}
        wiki = (common.load_source(p["slug"], "wikipedia") or {}).get("data") or {}
        ath = (common.load_source(p["slug"], "athletics") or {}).get("data") or {}
        wseasons = wiki.get("seasons") or []
        sched = ath.get("schedule") or {}
        history = ath.get("scheduleHistory") or {}
        record = (bool((finals_rows.get(LAST_DONE) or {}).get("record"))
                  or bool(history.get(str(LAST_DONE)))
                  or bool(sched.get("games") and (sched.get("season") or registry["season"]["current"]) == LAST_DONE)
                  or any(w.get("year") == LAST_DONE and w.get("record") for w in wseasons))
        out[p["slug"]] = {"rpiYears": years, "finishedRecord": record,
                          "anySeason": bool(years or wseasons or sched.get("games") or history)}
    return out


def _last(rows: dict, slug: str) -> dict:
    return (rows.get(slug) or {}).get("lastSeason") or {}


def check_anchor(registry: dict, rows: dict[str, dict], label: str) -> None:
    """What the entitlements cannot see (PR #112 review, M1). They are computed from the registry ids and the
    RPI loaders, the same inputs the build reads, so a fault in either moves the expectation with the output:
    nulling rpiHistoryName and ncaaName on 40 programs passed every entitlement check while 40 profiles lost
    their RPI history. These checks do not use either input. The anchor is a fixed list, independent of the
    data under test: the long-standing D1 programs (tests/fixtures/registry/pre-100-programs.json) and the RPI
    seasons each of them published before this change. Past seasons do not disappear, so a program still
    published in D1 must keep its ids, keep at least those seasons, and keep a 2025 lastSeason with a record.
    A new program (West Florida) or a non-D1 one is not in the anchor and is not affected."""
    pre = {p["slug"] for p in json.load(open(PRE_100, encoding="utf-8"))["programs"]}
    anchor_doc = json.load(open(RPI_ANCHOR, encoding="utf-8"))
    anchor = anchor_doc["programs"]
    # the fixture's lastSeason flags were measured for one season; a rollover must re-measure it, not reinterpret it
    ok(f"{label}: the RPI seasons fixture was measured for the finished season {FINISHED}", anchor_doc.get("finished") == FINISHED,
       f"fixture finished {anchor_doc.get('finished')}, FINISHED {FINISHED}")
    progs = [p for p in build.published_programs(registry) if p["slug"] in pre and p.get("division") == "D1"]
    ok(f"{label}: the anchor covers the long-standing D1 programs still published", bool(progs)
       and all(p["slug"] in anchor for p in progs), str([p["slug"] for p in progs if p["slug"] not in anchor][:5]))
    # ncaaName for every one; rpiHistoryName for those with archive seasons (new-haven joined D1 in 2025 and has none)
    lost_ids = [p["slug"] for p in progs
                if not (p.get("ids") or {}).get("ncaaName")
                or (any(y < FINISHED for y in anchor.get(p["slug"], {}).get("rpiYears", [])) and not (p.get("ids") or {}).get("rpiHistoryName"))]
    ok(f"{label}: every long-standing D1 program keeps its RPI ids", not lost_ids, f"{len(lost_ids)}: {lost_ids[:6]}")
    lost_years = {p["slug"]: sorted(set(anchor[p["slug"]]["rpiYears"]) - {h["year"] for h in (rows.get(p["slug"]) or {}).get("rpiHistory") or []})
                  for p in progs if p["slug"] in anchor}
    lost_years = {k: v for k, v in lost_years.items() if v}
    ok(f"{label}: every long-standing D1 program still publishes every RPI season it published before", not lost_years,
       f"{len(lost_years)}: {dict(list(lost_years.items())[:4])}")
    # a floor, not an equality (issue #249): once the 2026 final RPI is out lastSeason moves on to 2026, and the
    # fixture measured for 2025 still says what must never be lost - a lastSeason at least that recent, with a record
    lost_last = [p["slug"] for p in progs if anchor.get(p["slug"], {}).get("lastSeasonRecord")
                 and not ((((rows.get(p["slug"]) or {}).get("lastSeason") or {}).get("year") or 0) >= FINISHED
                          and rows[p["slug"]]["lastSeason"].get("record"))]
    ok(f"{label}: every long-standing D1 program still publishes a lastSeason of {FINISHED} or later, with a record", not lost_last,
       f"{len(lost_last)}: {lost_last[:6]}")


def check_published_against(ent: dict[str, dict], rows: dict[str, dict], built: str | None, label: str) -> None:
    """The published index (and profiles, when `built` is given) against the entitlements, both ways."""
    ok(f"{label}: some program is entitled to an RPI rank, so the rank checks below test something",
       any(e["rpiYears"] for e in ent.values()), "no program has a row in any table")
    ok(f"{label}: some program is entitled to a {LAST_DONE} record", any(e["finishedRecord"] for e in ent.values()))
    ok(f"{label}: the index holds exactly the programs the entitlements were computed for",
       sorted(rows) == sorted(ent), f"{len(rows)} rows, {len(ent)} programs")
    lacking = [s for s, e in ent.items() if e["finishedRecord"] and _last(rows, s).get("year") != LAST_DONE]
    ok(f"{label}: every program with a {LAST_DONE} record has lastSeason {LAST_DONE}", not lacking,
       f"{len(lacking)}: {lacking[:5]}")
    dashes = [s for s, e in ent.items() if e["finishedRecord"] and not _last(rows, s).get("record")]
    ok(f"{label}: and every one carries a record, so the Record column has no dashes", not dashes,
       f"{len(dashes)}: {dashes[:5]}")
    unearned = [s for s, e in ent.items() if not e["finishedRecord"] and _last(rows, s).get("year") == LAST_DONE]
    ok(f"{label}: no program without a {LAST_DONE} record publishes one", not unearned, str(unearned[:5]))
    wrong_rank = [s for s, e in ent.items() if _last(rows, s).get("year") == LAST_DONE
                  and bool(_last(rows, s).get("rpiRank")) != (LAST_DONE in e["rpiYears"])]
    ok(f"{label}: lastSeason carries a rank exactly when the program has a {LAST_DONE} row, and none otherwise",
       not wrong_rank, str([(s, _last(rows, s).get("rpiRank"), LAST_DONE in ent[s]["rpiYears"]) for s in wrong_rank[:5]]))
    hist_wrong = [s for s, e in ent.items()
                  if {h["year"] for h in (rows.get(s) or {}).get("rpiHistory") or []} != e["rpiYears"]]
    ok(f"{label}: rpiHistory lists exactly the seasons with a row, and is empty for a program with none",
       not hist_wrong, str([(s, sorted(h["year"] for h in rows[s].get("rpiHistory") or []), sorted(ent[s]["rpiYears"]))
                            for s in hist_wrong[:3]]))
    if built is None:
        return
    season_wrong, rank_wrong = [], []
    for slug, e in ent.items():
        ss = profile(built, slug)["seasons"]
        if bool(ss) != e["anySeason"]:
            season_wrong.append(slug)
        if {x["year"] for x in ss if x.get("rpiRank")} != e["rpiYears"]:
            rank_wrong.append(slug)
    ok(f"{label}: a profile has season history exactly when a source creates a season", not season_wrong,
       str(season_wrong[:5]))
    ok(f"{label}: a profile's ranked seasons are exactly its rows, and none for a program with no row",
       not rank_wrong, str(rank_wrong[:5]))


def check_in_progress(registry: dict, rows: dict[str, dict], built: str, label: str, rpi_dir: str | None = None) -> None:
    """Issue #62, the owner's decision of 2026-09-23: the NCAA's live table is published - its rank is the
    current rank the page shows, filters and sorts by - but its season is in progress, and an in-progress season
    never counts as a finished ranked season: lastSeason, the Record column and the season history stay on the
    last finished season until that season's final table is the one read (its last weekly snapshot, once the
    registry moves on). Every check here fails if the live season were counted as finished."""
    cur_season = registry["season"]["current"]
    if LAST_DONE == cur_season:
        # issue #249: the final RPI is on disk (final_on_disk), so the season being played is over everywhere
        rows_cur = {slug: season_of(profile(built, slug)["seasons"], cur_season) for slug in rows}
        still = [slug for slug, s in rows_cur.items() if s.get("inProgress")]
        ok(f"{label}: after the final RPI, no {cur_season} row is in progress", not still, f"{len(still)}: {still[:6]}")
        not_last = [slug for slug, s in rows_cur.items() if s.get("record")
                    and (rows[slug].get("lastSeason") or {}).get("year") != cur_season]
        ok(f"{label}: and lastSeason is {cur_season} wherever {cur_season} has a record", not not_last,
           f"{len(not_last)}: {not_last[:6]}")
        return
    live = {}  # slug -> the rank its profile publishes for the season being played
    for slug in rows:
        s = season_of(profile(built, slug)["seasons"], cur_season)
        if s.get("rpiRank") is not None:
            live[slug] = s
    with (swapped(RPI_OUT_DIR=rpi_dir) if rpi_dir else contextlib.nullcontext()):
        table_live = (build.load_rpi_current() or {}).get("season") == cur_season
    ok(f"{label}: programs publish a {cur_season} rank exactly when the live table is the season being played",
       bool(live) == table_live, f"{len(live)} ranked, current.json is {cur_season}: {table_live}")
    finished = [slug for slug, s in live.items() if not s.get("inProgress")]
    ok(f"{label}: every {cur_season} rank from the live table is marked in progress, none as a finished season",
       not finished, f"{len(finished)}: {finished[:6]}")
    as_last = [slug for slug, r in rows.items() if (r.get("lastSeason") or {}).get("year") == cur_season and slug in live]
    ok(f"{label}: no program's lastSeason is its in-progress {cur_season}", not as_last, f"{len(as_last)}: {as_last[:6]}")
    # the page reads the rank from rpiHistory (rank, filter, sort); currentSeason is the list row's live season
    unlisted = [slug for slug, s in live.items()
                if {"year": cur_season, "rank": s["rpiRank"]} not in (rows[slug].get("rpiHistory") or [])
                or ((rows[slug].get("currentSeason") or {}).get("year"), (rows[slug].get("currentSeason") or {}).get("rpiRank"))
                != (cur_season, s["rpiRank"])]
    ok(f"{label}: the list row carries the live rank, in rpiHistory and as its currentSeason",
       not unlisted, f"{len(unlisted)}: {unlisted[:6]}")


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
    # Issue #62: current.json is read exactly when it holds the season being played, and then only as that
    # season's in-progress table. Which state holds today depends on the calendar - the NCAA posts its first
    # table in the autumn - so the rule is checked in whichever one it is, instead of pinning one of them.
    if cur["season"] == cur_season:
        ok("current.json holds the season being played, so it is read, as that season's table",
           finals.get(cur_season, {}).get("throughGames") == cur.get("throughGames") and cur_season != FINISHED,
           f"current.json season {cur['season']}, through {cur.get('throughGames')}")
    else:
        ok("current.json does not hold the season being played, so it is not read",
           cur_season not in finals and cur["season"] == FINISHED, f"current.json season {cur['season']}")
    ok(f"{FINISHED} never comes from current.json, whatever season it holds",
       finals[FINISHED].get("throughGames") == snap["throughGames"], str(finals[FINISHED].get("throughGames")))

    tmp = tempfile.mkdtemp(prefix="seasons-loader-")
    try:
        # current.json is read only for the season being played.
        with swapped(RPI_OUT_DIR=scratch_rpi(tmp + "/played", cur_season=cur_season)):
            f = build.load_rpi_finals(cur_season)
        ok("current.json is picked up once its season is the one being played", cur_season in f, str(sorted(f)))
        ok("and the finished season still comes from its own snapshot",
           f[FINISHED]["throughGames"] == snap["throughGames"], str(f[FINISHED].get("throughGames")))

        # A archive sheet takes the rank, but must not take the snapshot away: archive rows carry
        # no record, and the snapshot is where the record for those seasons lives.
        with swapped(RPI_OUT_DIR=scratch_rpi(tmp + "/arch", cur_season=cur_season, archive_year=FINISHED)):
            f = build.load_rpi_finals(cur_season)
            hist = build.load_rpi_history()
        ok("a season covered by both a archive sheet and a snapshot still resolves its snapshot",
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
           "2020 has no archive sheet, and today's build is clean")
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
    ok("its 2024 rank carries the Chris Thomas provenance",
       season_of(rows, 2024).get("rpi", {}).get("source") == "end-of-season (Chris Thomas archive)",
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
        ok("where a archive sheet exists for a snapshotted season, the archive's rank is published",
           s2.get("rpi", {}).get("source") == "end-of-season (Chris Thomas archive)" and s2.get("rpiRank") != 8,
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
    ok("index.json carries a row for each published program", bool(rows) and
       sorted(rows) == sorted(p["slug"] for p in build.published_programs(registry)), f"{len(rows)} rows")
    check_published_against(entitlements(registry), rows, built, "build")
    check_anchor(registry, rows, "build")

    check_in_progress(registry, rows, built, "build")
    # Issue #249, cross-checked against the files and not against the build's own say-so: the build
    # declares the season finished exactly when a stored snapshot is dated on or after the registry's date.
    season = index.get("season") or {}
    ok(f"index.season.finished is {LAST_DONE}, as the registry date and the stored snapshots say",
       season.get("finished") == LAST_DONE, f"index {season.get('finished')}, on disk {LAST_DONE}")
    ok("index.season.rpiFinal is set exactly when the final table is on disk, and names its through-date",
       (season.get("rpiFinal") or {}).get("through") == FINAL_THROUGH
       and (season.get("rpiFinal") is None) == (FINAL_THROUGH is None), str(season.get("rpiFinal")))
    final = FINAL_THROUGH is not None

    # Issue #3's own examples, and the coverage each one is expected to have. Since issue #62 the live
    # season is published with its rank but is not a finished ranked season, so these count finished
    # seasons, and the in-progress one is checked on its own: the season being played, where the program
    # has a row in its table, and nothing else.
    cur_season = registry["season"]["current"]
    ent = entitlements(registry)
    for slug, ranked in (("alcorn-state", 17), ("utrgv", 10), ("new-haven", 1), ("vanderbilt", 18)):
        got = [s for s in profile(built, slug)["seasons"] if s.get("rpiRank")]
        done = [s["year"] for s in got if not s.get("inProgress") and s["year"] <= FINISHED]
        live = [s["year"] for s in got if s.get("inProgress")]
        ok(f"{slug} publishes {ranked} finished ranked seasons up to {FINISHED}", len(done) == ranked, str(sorted(done)))
        ok(f"{slug}'s only in-progress ranked season is the one being played, where its table has a row",
           live == ([cur_season] if cur_season in ent[slug]["rpiYears"] and not final else []), f"in progress {live}")
    # fails if new-haven's D1 rank leaks onto a season it played before joining D1 (issue #153).
    # Not "the season list is exactly [2025]": once schedule collection runs, the list correctly
    # carries New Haven's real D2-era results too (2023, 2024) - that is data, not a defect. The
    # only thing that must stay true is that no year before 2025 carries an RPI claim.
    nh_seasons = profile(built, "new-haven")["seasons"]
    ok("new-haven, a 2025 D1 newcomer, has exactly one finished ranked season and it is 2025",
       [s["year"] for s in nh_seasons if s.get("rpiRank") and not s.get("inProgress") and s["year"] <= FINISHED] == [FINISHED],
       str([(s["year"], bool(s.get("inProgress"))) for s in nh_seasons if s.get("rpiRank")]))
    ok("and no season before 2025 carries an rpiRank or an rpi block",
       not early_rpi_claims(nh_seasons, FINISHED), str(early_rpi_claims(nh_seasons, FINISHED)))
    ok("alcorn-state's ranks come from the AlcornState archive key the registry now names",
       (registry and program(registry, "alcorn-state")["ids"]["rpiHistoryName"] == "AlcornState"),
       str(program(registry, "alcorn-state")["ids"]["rpiHistoryName"]))
    ok("utrgv's 2014 season stays unclaimed, being filed under TexasPanAmerican",
       2014 not in [s["year"] for s in profile(built, "utrgv")["seasons"] if s.get("rpiRank")])

    if not final:  # once 2026 is final these list rows are 2026's; the profiles' 2025 rows are checked above and below
        v = rows["vanderbilt"]["lastSeason"]
        ok(f"vanderbilt's list row is {FINISHED}, #8, 18-4-2",
           (v["year"], v["rpiRank"], v["record"]) == (FINISHED, 8, "18-4-2"), str(v))
        m = rows["miami-fl"]["lastSeason"]
        ok(f"miami-fl's list row is {FINISHED}, #76, 7-8-3", (m["rpiRank"], m["record"]) == (76, "7-8-3"), str(m))
    st = profile(built, "stanford")
    ok("stanford, which already had a full history, keeps its 43 seasons", len(st["seasons"]) == 43,
       str(len(st["seasons"])))
    ok("and its season being played is in progress exactly until the final RPI (issue #249)",
       bool(season_of(st["seasons"], registry["season"]["current"]).get("inProgress")) is (not final),
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
        # entitlements are read from the relabelled tables, the same ones the rebuild read
        check_published_against(entitlements(registry, os.path.join(tmp, "rpi")), rows, None, "flip")
        check_anchor(registry, rows, "flip")
        ok(f"no lastSeason is the newly labelled {cur_season}",
           not [r for r in rows.values() if (r.get("lastSeason") or {}).get("year") == cur_season])
        check_in_progress(registry, rows, built, "flip", os.path.join(tmp, "rpi"))
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
    """Someone adds next year's archive sheet to registry.sources.rpiHistory.sheets - 17 curated
    entries, and extending them is the ordinary maintenance action - and the archive starts covering
    a season a weekly snapshot also covers.

    That must not half-revert issue #3. Archive rows carry a rank and no record, so a build that
    lets the archive displace the snapshot outright published 173 lastSeasons instead of 350 and
    put the dash back in the Record column for 177 programs - the feature quietly undoing itself
    because the data got *better*, with no guard firing. The archive's rank still wins; the
    snapshot's record is still read.
    """
    print("archive+snapshot: adding a archive sheet for a snapshotted season must not blank records")
    cur_season = registry["season"]["current"]
    tmp = tempfile.mkdtemp(prefix="seasons-arch-")
    try:
        built, log = rebuild(tmp, scratch_rpi(tmp, cur_season=cur_season, archive_year=FINISHED))
        rows = {r["slug"]: r for r in json.load(open(os.path.join(built, "index.json"), encoding="utf-8"))["programs"]}
        ok("the rebuild still validates", not complaints(log), complaints(log)[:400])
        # The Record column must not lose a single entitled program to the new sheet: publishing 173
        # lastSeasons instead of 350 was the bug. Entitlements read the same extended tables.
        check_published_against(entitlements(registry, os.path.join(tmp, "rpi")), rows, None, "archive+snapshot")
        # the synthesised sheet re-ranks 2025 but must not cost any program a season, an id or its lastSeason
        check_anchor(registry, rows, "archive+snapshot")

        # The synthesised sheet's ranks are deliberately wrong, so a published rank names its source.
        v = season_of(profile(built, "vanderbilt")["seasons"], FINISHED)
        ok(f"vanderbilt {FINISHED} publishes the archive's rank, not the snapshot's #8",
           v.get("rpiRank") not in (None, 8)
           and v.get("rpi", {}).get("source") == "end-of-season (Chris Thomas archive)", str(v))
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
    global LAST_DONE, FINAL_THROUGH
    LAST_DONE, FINAL_THROUGH = final_on_disk(registry)
    print(f"finished season on disk: {LAST_DONE}" + (f" (final RPI through {FINAL_THROUGH})" if FINAL_THROUGH else ""))
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
