"""One camp found in two places is one camp (issue #74).

    python tests/camps_dedup_test.py            # everything below, offline
    python tests/camps_dedup_test.py --verbose  # print every check, not only the failures

A camp announced on a program's camp page and again in a news release was listed and counted twice: le-moyne's
Oct 3 ID clinic appeared as "Soccer ID Clinic | October 3rd" (the camp site) and "WOMEN'S SOCCER TO HOLD ID
CLINIC" (the news release), both registering at https://register.ryzer.com/camp.cfm?sport=7&id=339090, and the ID
Camp View said "2 upcoming camps at 1 program". The two sources only meet in build.build_camps, which merged a
news entry only when its name matched a camp-page entry's exactly.

The rule now, at build time: two entries from DIFFERENT sources (camp page, curated, news) with the same start
date and the same registration link - compared after build.registration_key normalises it - are one camp. The
camp-page entry is kept, and every source it was found in is listed in its `sources` (withheld from the
published camps index, like newsTitle). A name alone never merges, and neither does a date alone.

Offline, no files written: build_camps runs on in-memory sources shaped like the stored ones (the le-moyne
entries are its stored values, trimmed of nothing).

Swap-back proof: COLLEGEDASH_CODE_ROOT=<an export of origin/main> runs these checks against that code.
Labels: FIX checks fail against origin/main and pass after the change; CONTROL checks pass on both.
"""

from __future__ import annotations

import argparse
import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_ROOT = os.environ.get("COLLEGEDASH_CODE_ROOT") or ROOT
sys.path.insert(0, CODE_ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import build  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False

RYZER = "https://register.ryzer.com/camp.cfm?sport=7&id=339090"
CAMP = {"name": "Soccer ID Clinic | October 3rd", "startDate": "2026-10-03", "endDate": "2026-10-03", "dateText": "10/03/2026",
        "precision": "day", "yearInferred": False, "location": None, "ages": "9th - College Junior Grade as of Fall 2026",
        "price": "$164.00", "registerUrl": RYZER, "sourceUrl": "https://www.vanfleetsoccercamps.com/", "confidence": "heuristic"}
NEWS = {"name": "WOMEN'S SOCCER TO HOLD ID CLINIC", "startDate": "2026-10-03", "endDate": "2026-10-03", "dateText": "OCTOBER 3RD",
        "precision": "day", "yearInferred": True, "location": None, "ages": None, "price": None, "registerUrl": RYZER,
        "sourceUrl": "https://lemoynedolphins.com/news/2026/8/25/wsoc-id-clinic-8-25-26.aspx", "confidence": "heuristic",
        "newsTitle": "WOMEN'S SOCCER TO HOLD ID CLINIC ON OCTOBER 3RD",
        "newsUrl": "https://lemoynedolphins.com/news/2026/8/25/wsoc-id-clinic-8-25-26.aspx", "newsDate": "2026-08-25"}


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {ascii(detail)[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def items(camps=(), news=(), curated=()):
    src = {"data": {"campsUrl": "https://www.vanfleetsoccercamps.com", "camps": [copy.deepcopy(c) for c in camps],
                    "newsCamps": [copy.deepcopy(n) for n in news]}, "fetchedAt": "2026-09-16T00:00:00Z", "sourceUrl": "x"}
    section = build.build_camps(src, {"data": {}, "fetchedAt": "2026-09-16T00:00:00Z", "sourceUrl": "y"},
                                {"camps": [copy.deepcopy(c) for c in curated]})
    return section["items"] if section else []


def summary(its):
    return [(it.get("kind"), it.get("startDate"), it.get("name")) for it in its]


def test_merge() -> None:
    print("the same camp from the camp page and a news release")
    got = items([CAMP], [NEWS])
    ok("FIX le-moyne: one Oct 3 clinic, not two", len(got) == 1, str(summary(got)))
    kept = got[0] if got else {}
    ok("CONTROL ... the camp-page entry is the one kept (its name, price, ages and registration link)",
       (kept.get("kind"), kept.get("name"), kept.get("price"), kept.get("registerUrl")) == ("camp", CAMP["name"], "$164.00", RYZER), str(kept)[:300])
    srcs = kept.get("sources") or []
    ok("FIX ... and it lists both sources: the camp site and the news release, with the release's title and date",
       [(s.get("kind"), s.get("sourceUrl")) for s in srcs] == [("camp", CAMP["sourceUrl"]), ("news", NEWS["sourceUrl"])]
       and srcs[1].get("newsTitle") == NEWS["newsTitle"] and srcs[1].get("newsDate") == "2026-08-25", str(srcs))
    rows = [build.camp_row("le-moyne", it) for it in got if build.camp_in_window(it, {"from": "2026-09-16", "to": None})]
    ok("FIX the camps index gets one row for it, and counts one camp", len(rows) == 1 and build.camp_counts(rows)["total"] == 1, str(rows))
    ok("FIX `sources` is withheld from the published row, and declared as withheld (so check_camps_index accepts it)",
       rows and "sources" not in rows[0] and "sources" in build.CAMP_ITEM_UNPUBLISHED, str(build.CAMP_ITEM_UNPUBLISHED))

    got = items([CAMP], [], [{**NEWS, "name": "Hand-entered ID clinic", "sourceUrl": None}])
    ok("FIX a curated entry with the same date and registration link merges into the camp-page entry too",
       summary(got) == [("camp", "2026-10-03", CAMP["name"])] and [s.get("kind") for s in got[0].get("sources") or []] == ["camp", "curated"],
       str(summary(got)))


def test_normalised_links() -> None:
    print("registration links are compared after normalising")
    variants = {
        "http, not https": "http://register.ryzer.com/camp.cfm?sport=7&id=339090",
        "www. and capitals in the host": "https://WWW.Register.Ryzer.com/camp.cfm?sport=7&id=339090",
        "parameters in another order": "https://register.ryzer.com/camp.cfm?id=339090&sport=7",
        "a tracking parameter and a fragment": "https://register.ryzer.com/camp.cfm?sport=7&id=339090&utm_source=news#register",
    }
    for label, url in variants.items():
        got = items([CAMP], [{**NEWS, "registerUrl": url}])
        ok(f"FIX {label}: still one camp", len(got) == 1, str(summary(got)))
    ok("FIX registration_key: a trailing slash on the path does not matter",
       getattr(build, "registration_key", lambda u: u)("https://x.example/camps/") == getattr(build, "registration_key", lambda u: None)("https://x.example/camps"))


def test_not_merged() -> None:
    print("what is not the same camp")
    got = items([CAMP], [{**NEWS, "registerUrl": "https://register.ryzer.com/camp.cfm?sport=7&id=339091"}])
    ok("CONTROL same date, different registration link (another Ryzer id): two camps", len(got) == 2, str(summary(got)))
    got = items([CAMP], [{**NEWS, "startDate": "2026-10-04", "endDate": "2026-10-04"}])
    ok("CONTROL same registration link, different date: two camps", len(got) == 2, str(summary(got)))
    got = items([CAMP], [{**NEWS, "registerUrl": None}])
    ok("CONTROL same date, the news release gives no registration link: two camps (a date alone never merges)",
       len(got) == 2, str(summary(got)))
    got = items([CAMP], [{**NEWS, "name": CAMP["name"], "startDate": "2026-11-07", "endDate": "2026-11-07", "registerUrl": None}])
    ok("CONTROL same name, different date, no link: two camps (a name alone never merges)", len(got) == 2, str(summary(got)))
    two = [{**NEWS, "name": "CAMP #1"}, {**NEWS, "name": "Camps on June 20 & August 1"}]
    got = items([], two)
    ok("CONTROL two entries from the SAME source with one date and link stay two (the rule is across sources; roosevelt's news)",
       len(got) == 2, str(summary(got)))
    got = items([CAMP, {**CAMP, "name": "Soccer ID Clinic | October 3rd (session 2)"}], [])
    ok("CONTROL two camp-page entries with one date and link stay two", len(got) == 2, str(summary(got)))
    got = items([CAMP], [NEWS, {**NEWS, "name": "ANOTHER RELEASE ABOUT THE CLINIC", "sourceUrl": "https://lemoynedolphins.com/news/2"}])
    ok("FIX two news releases about the camp-page camp both merge into it, each listed",
       len(got) == 1 and [s.get("kind") for s in got[0].get("sources") or []] == ["camp", "news", "news"], str(summary(got)))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    if CODE_ROOT != ROOT:
        print(f"code under test imported from {CODE_ROOT}")
    for case in (test_merge, test_normalised_links, test_not_merged):
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
