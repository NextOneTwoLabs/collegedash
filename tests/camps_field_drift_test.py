"""A camp field added at the source must be decided about before it ships (issue #69, problem 2).

    python tests/camps_field_drift_test.py            # every case
    python tests/camps_field_drift_test.py --verbose  # print every check, not only the failures

CAMP_INDEX_FIELDS is an allow-list: a per-item field named there is published, one named in
CAMP_ITEM_UNPUBLISHED is withheld on purpose, and any other field reaches no row. check_camps_index reports
such a field, but only when validate runs on a refresh's output, which costs that day's publish. This test
runs the same decision, `build.camp_item_drift(fields)`, at pull-request time over every key the code can emit:

  - the keys camps._entry builds,
  - the news extras the collector adds (newsTitle, newsUrl, newsDate),
  - the keys of the items build_camps writes for a synthetic camp, a curated entry and a news entry,
  - the keys recorded in tests/fixtures/camps/extract-snapshot.json (real pages, run through extract_camps).

A new field fails here the day a PR adds it, and the PR names it on CAMP_INDEX_FIELDS or CAMP_ITEM_UNPUBLISHED.
It depends on camps._entry staying the only constructor of collected camp items (flagged on #39).

Offline: no files written, no network.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import build  # noqa: E402
from collect import camps  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False
NEWS_EXTRAS = {"newsTitle": "Owls host ID camp", "newsUrl": "https://example.test/n", "newsDate": "2026-09-01"}
DATE = {"startDate": "2026-11-07", "endDate": "2026-11-07", "dateText": "Nov 7", "precision": "day", "yearInferred": False}


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def emitted_fields() -> set:
    """Every per-item key the camp code emits, found by running it rather than by reading a list."""
    entry = camps._entry("Spring ID Camp", DATE, {"location": "Here", "ages": "14-18", "price": "$50"},
                         "https://example.test/register", "https://example.test/camps")
    news = {**camps._entry("Owls host ID camp", DATE, {}, None, "https://example.test/n"), **NEWS_EXTRAS}
    built = build.build_camps({"data": {"camps": [entry], "newsCamps": [news]}, "collector": "camps"},
                              {"data": {}, "collector": "news"},
                              {"camps": [{"name": "Curated ID Day", "startDate": "2026-12-01"}]})
    fields = set(entry) | set(news) | set(NEWS_EXTRAS)
    for it in built["items"]:
        fields |= set(it)
    return fields


def snapshot_fields() -> set:
    path = os.path.join(ROOT, "tests", "fixtures", "camps", "extract-snapshot.json")
    with open(path, encoding="utf-8") as f:
        snap = json.load(f)
    return {k for entries in snap.values() for e in entries for k in e}


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    VERBOSE = ap.parse_args(argv).verbose

    print("drift: the real keys")
    fields = emitted_fields()
    ok("the emitted keys include the ones the allow-list is about", {"name", "kind", "campType", "sources", "newsTitle"} <= fields,
       str(sorted(fields)))
    ok("camp_item_drift exists", hasattr(build, "camp_item_drift"))
    drift = build.camp_item_drift
    ok("the real emitted keys give no drift", drift(fields) == [], str(drift(fields)))
    ok("neither do the keys recorded in extract-snapshot.json (campType is already in it)",drift(snapshot_fields()) == [],
       str(drift(snapshot_fields())))
    ok("the result is a sorted list of names", drift({"zzz", "aaa", "name"}) == ["aaa", "zzz"], str(drift({"zzz", "aaa", "name"})))
    ok("a field withheld on purpose is not drift", drift({"newsTitle", "sources"}) == [])

    print("drift: a new field added at the source")
    real_entry = camps._entry

    def with_sport(*a, **kw):
        return {**real_entry(*a, **kw), "sport": "wsoc"}

    camps._entry = with_sport
    try:
        got = drift(emitted_fields())
    finally:
        camps._entry = real_entry
    ok("adding `sport` to camps._entry reports exactly ['sport']", got == ["sport"], str(got))

    real_unpublished = build.CAMP_ITEM_UNPUBLISHED
    camps._entry = with_sport
    build.CAMP_ITEM_UNPUBLISHED = (*real_unpublished, "sport")
    try:
        got = drift(emitted_fields())
    finally:
        camps._entry = real_entry
        build.CAMP_ITEM_UNPUBLISHED = real_unpublished
    ok("declaring it on CAMP_ITEM_UNPUBLISHED clears it", got == [], str(got))

    real_fields = build.CAMP_INDEX_FIELDS
    camps._entry = with_sport
    build.CAMP_INDEX_FIELDS = (*real_fields, "sport")
    try:
        got = drift(emitted_fields())
    finally:
        camps._entry = real_entry
        build.CAMP_INDEX_FIELDS = real_fields
    ok("and so does adding it to CAMP_INDEX_FIELDS", got == [], str(got))

    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
