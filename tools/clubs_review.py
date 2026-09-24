"""Write data/clubs-review.json from the stored sources, without rebuilding the site.

The daily build writes the same file (build.build -> clubs.Recorder.write). This is the same pass
on its own, for a reviewer who wants today's list of unmatched club names before touching
data/clubs.json, and for checking an edit to that table:

    python tools/clubs_review.py              # rewrite data/clubs-review.json and print a summary
    python tools/clubs_review.py --dry-run    # print the summary only
    python tools/clubs_review.py --top 20     # also print the most common unmatched names

Reads only the stored sources; it makes no requests and never changes data/clubs.json.

Do not commit the rewritten data/clubs-review.json in a pull request (issue #235): main's copy is
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

import build  # noqa: E402
import clubs  # noqa: E402
from collect import common  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="do not write data/clubs-review.json")
    ap.add_argument("--top", type=int, default=0, metavar="N", help="print the N most common unmatched names")
    ap.add_argument("--division", default="", help="only this division (D1, D2)")
    args = ap.parse_args()

    registry = common.load_registry()
    table = clubs.load_table(reload=True)
    recorder = clubs.Recorder(table)
    programs = 0
    for program in common.iter_programs(registry):
        division = program.get("division", "D1")
        if args.division and division != args.division:
            continue
        programs += 1
        S = lambda n: common.load_source(program["slug"], n)  # noqa: E731
        build.observe_clubs(recorder, S("athletics"), S("commitments.tds"), S("commitments.soccerwire"),
                            slug=program["slug"], division=division)
    report = recorder.report(common.read_json(clubs.REVIEW_PATH)) if args.dry_run else recorder.write()
    s = report["summary"]
    print(f"{programs} programs; {s['recordsWithAClubString']} club strings, "
          f"{s['clubStringsMatched']} matched ({s['matchedShareOfStrings']}%), "
          f"{s['clubStringsUnmatched']} unmatched in {s['distinctUnmatchedKeys']} names; "
          f"{report['newSinceLastBuild']['count']} new since the last report")
    for row in report["unmatched"][:args.top]:
        sug = (row["suggestion"] or {}).get("name")
        print(f"  {row['occurrences']:4}  {row['key']}" + (f"   (suggestion: {sug})" if sug else ""))
    if not args.dry_run:
        print(f"wrote {clubs.REVIEW_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
