"""Write data/schools-review.json from the stored rosters, without rebuilding the site.

The daily build writes the same file (build.build -> schools.Recorder.write). This is the same pass
on its own, for the owner who wants today's high-school match report (issue #229) without a build:

    python tools/schools_review.py              # rewrite data/schools-review.json and print a summary
    python tools/schools_review.py --dry-run    # print the summary only
    python tools/schools_review.py --top 20     # also print the most common unmatched names
    python tools/schools_review.py --samples 10 # also print that many matched players' school lines

Reads only the stored sources and data/schools.json; it makes no requests.

Do not commit the rewritten data/schools-review.json in a pull request (issue #235): main's copy is
published by the daily refresh only, and CI's "Generated reports not in PR" check fails a PR that
changes it. Paste the --dry-run summary into the PR description instead. If you rebuild locally and
stage with `git add -A`, `git update-index --skip-worktree data/clubs-review.json data/schools-review.json`
keeps both reports out of your commits (`--no-skip-worktree` undoes it).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import schools  # noqa: E402
from collect import common  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="do not write data/schools-review.json")
    ap.add_argument("--top", type=int, default=0, metavar="N", help="print the N most common unmatched names")
    ap.add_argument("--samples", type=int, default=0, metavar="N", help="print N matched examples")
    ap.add_argument("--division", default="all", help="only this division (D1, D2 or D3); default all, as the build (#315)")
    args = ap.parse_args()

    registry = common.load_registry()
    table = schools.load_table(reload=True)
    recorder = schools.Recorder(table)
    programs = 0
    samples: list[str] = []
    for program in common.iter_programs(registry):
        if args.division != "all" and program.get("division", "D1") != args.division:
            continue
        programs += 1
        ath = common.load_source(program["slug"], "athletics")
        for p in ((((ath or {}).get("data") or {}).get("roster") or {}).get("players") or []):
            m = recorder.observe(p, slug=program["slug"], division=program.get("division", "D1"))
            if m.status == "matched" and len(samples) < args.samples:
                samples.append(f"{m.raw!r} + {p.get('hometown')!r} -> {m.school['name']} ({m.school['city']}, "
                               f"{m.state}, {m.school['type']}) {m.schoolId}")
    report = recorder.report(common.read_json(schools.REVIEW_PATH)) if args.dry_run else recorder.write()
    s = report["summary"]
    print(f"{programs} {args.division} programs; {s['playersSeen']} current players, {s['playersWithAHighSchool']} "
          f"with a high school: {s['matched']} matched ({s['matchedShareOfPlayersWithAHighSchool']}%) to "
          f"{s['distinctSchoolsMatched']} schools, {s['unmatched']} unmatched ({s['unmatchedWithoutAState']} with "
          f"no state, {s['unmatchedUntilTheNextRosterCollection']} on rows not yet re-collected since #227), "
          f"{s['ambiguous']} ambiguous (left unmatched), {s['outsideUS']} outside the US; "
          f"{report['newSinceLastBuild']['count']} names new since the last report")
    for row in report["unmatched"][:args.top]:
        extra = ""
        if row["status"] == "ambiguous":
            extra = "   ambiguous: " + "; ".join(f"{c['name']} ({c['city']})" for c in row["candidates"][:3])
        print(f"  {row['occurrences']:4}  {row['key']}  [{row['state'] or 'no state'}]{extra}")
    for line in samples:
        print("  " + line)
    if not args.dry_run:
        print(f"wrote {schools.REVIEW_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
