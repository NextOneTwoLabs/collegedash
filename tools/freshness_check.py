#!/usr/bin/env python3
"""How old is the published data? Run daily by .github/workflows/freshness.yml (issue #69).

    python tools/freshness_check.py            # judge the committed files against the clock
    python tools/freshness_check.py --now 2026-10-09T23:47:00Z   # judge them as of another moment

Everything validate checks is internal consistency, so an index and profiles that are stale *together* (a
refresh that never started, a schedule that was disabled) pass every check while the data ages. This is the
one place the clock is read, and it is read only here, never in build, validate or pull-request CI: a check
that compares data with "today" fails correct data the morning it ages.

Two ages are judged, each against the same two lines:

  publish     hours since `updated` in public/data/programs/index.json: when the site's data was last built.
  collection  for each of camps, tds, soccerwire and news, hours since the newest `at` in
              public/archive/refresh-state.json among that collector's entries that really collected:
              `ok is True` and no `skipped` key (a skipped entry is written {"ok": true, "skipped": ...}
              and collected nothing). `build_only` runs republish without collecting and write no refresh
              state, so a fresh publish over stale collection is caught here and nowhere else.

The thresholds come from the refresh schedule (refresh.yml: cron 0 11 * * *, observed to start 4 to 8.5h late
and run 35 to 50 minutes) and the check time (47 23 * * *): a normal publish is 3.5 to 8.2h old when this
runs, one missed day makes it 27.5 to 32.2h, two make it 51.5 to 56.2h. So:

  up to 12h   ok      (4h above the worst normal case)
  above 12h   warn    a ::warning and a Step Summary line; the run stays green
  above 36h   fail    an ::error naming the dataset and its age; the run goes red

Athletics is left out because it runs daily only August to December, and rpi.* entries carry no `ok`. Exit 0
unless something fails. Offline: reads two committed files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from typing import NamedTuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRAMS_INDEX = os.path.join(ROOT, "public", "data", "programs", "index.json")
REFRESH_STATE = os.path.join(ROOT, "public", "archive", "refresh-state.json")

WARN_HOURS = 12
FAIL_HOURS = 36
SKEW_HOURS = 1  # a stamp this far ahead of the clock is skew and reads as ok; further ahead fails
COLLECTORS = ("camps", "tds", "soccerwire", "news")
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class Finding(NamedTuple):
    dataset: str          # "publish" or a collector name
    level: str            # "ok", "warn" or "fail"
    age_hours: float | None
    message: str


def parse_time(value) -> dt.datetime | None:
    """A `YYYY-MM-DDTHH:MM:SSZ` string as an aware UTC datetime, or None for anything else."""
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.strptime(value, TIME_FORMAT).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def judge(dataset: str, what: str, stamp: dt.datetime | None, now: dt.datetime, raw=None) -> Finding:
    """One age against the two lines. A missing, unparseable or future stamp cannot be dated, which is a fail."""
    if stamp is None:
        return Finding(dataset, "fail", None, f"{dataset}: {what} is missing or unreadable ({raw!r}), so its age cannot be judged")
    hours = (now - stamp).total_seconds() / 3600
    if hours < -SKEW_HOURS:
        return Finding(dataset, "fail", hours, f"{dataset}: {what} {stamp.strftime(TIME_FORMAT)} is {-hours:.1f}h in the future")
    hours = max(hours, 0.0)  # up to SKEW_HOURS ahead is clock skew between runners, not a fault
    age = f"{what} {stamp.strftime(TIME_FORMAT)} is {hours:.1f}h old"
    if hours > FAIL_HOURS:
        return Finding(dataset, "fail", hours, f"{dataset}: {age} (fails above {FAIL_HOURS}h)")
    if hours > WARN_HOURS:
        return Finding(dataset, "warn", hours, f"{dataset}: {age} (warns above {WARN_HOURS}h)")
    return Finding(dataset, "ok", hours, f"{dataset}: {age}")


def newest_collection(state, collector: str) -> dt.datetime | None:
    """The newest `at` among <slug>.<collector> entries that really collected, or None."""
    best = None
    if not isinstance(state, dict):
        return None
    for key, entry in state.items():
        if not isinstance(key, str) or key.rpartition(".")[2] != collector or "." not in key:
            continue
        if not isinstance(entry, dict) or entry.get("ok") is not True or "skipped" in entry:
            continue
        at = parse_time(entry.get("at"))
        if at is not None and (best is None or at > best):
            best = at
    return best


def evaluate(published_updated, state, now: dt.datetime) -> list[Finding]:
    """The publish age first, then each collector's collection age."""
    out = [judge("publish", "the programs index was built at", parse_time(published_updated), now, published_updated)]
    for collector in COLLECTORS:
        newest = newest_collection(state, collector)
        if newest is None:
            out.append(Finding(collector, "fail", None, f"{collector}: no entry in refresh-state.json collected "
                                                        f"(ok and not skipped), so its age cannot be judged"))
        else:
            out.append(judge(collector, "the newest real collection", newest, now))
    return out


def read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--now", help="judge as of this UTC time (YYYY-MM-DDTHH:MM:SSZ); default: the clock")
    args = ap.parse_args(argv)
    now = parse_time(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
    if now is None:
        print(f"--now must look like 2026-10-09T23:47:00Z, got {args.now!r}", file=sys.stderr)
        return 2

    index = read_json(PROGRAMS_INDEX)
    state = read_json(REFRESH_STATE)
    findings = evaluate(index.get("updated") if isinstance(index, dict) else None, state, now)

    lines = ["| dataset | result | age | detail |", "|---|---|---|---|"]
    for f in findings:
        print(f"{f.level.upper():4} {f.message}")
        if f.level == "warn":
            print(f"::warning title=freshness {f.dataset}::{f.message}")
        elif f.level == "fail":
            print(f"::error title=freshness {f.dataset}::{f.message}")
        age = "unknown" if f.age_hours is None else f"{f.age_hours:.1f}h"
        lines.append(f"| {f.dataset} | {f.level} | {age} | {f.message} |")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Data freshness\n\n" + "\n".join(lines) + "\n")
    failed = [f.dataset for f in findings if f.level == "fail"]
    if failed:
        print(f"freshness: FAIL ({', '.join(failed)})")
        return 1
    print("freshness: ok" if all(f.level == "ok" for f in findings) else "freshness: warn (run stays green)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
