"""The Home search's frozen test data, tests/fixtures/search/{programs,camps}.json, and its builder
tools/search_fixture.py (issue #507, v1 PR 1).

    python tests/search_fixture_test.py            # every case
    python tests/search_fixture_test.py --verbose  # print every check, not only the failures

The fixture is frozen on purpose: the daily refresh must never move a judged-set expectation, so nothing here reads
public/data (comparing with it is `python tools/search_fixture.py --check`, run by hand when regenerating). What is
checked instead: the builder on made-up rows, that cutting the fixture's own docs gives them back unchanged, the
fixture's shape, and that it carries programs and camps only. Offline, under tests/netguard; nothing is written.

Cases:
  builder      cut() on made-up docs: rows in order, exactly the kept keys, the camp's program block cut to its
               keys, a missing block kept as null, no person field or email carried; dumps() round-trips, one row
               per line; clock() is the date part of the camps doc's `updated`.
  idempotent   cut() of the committed fixture's own docs, written with dumps(), is byte-identical to the files.
  shape        top-level keys, unique program slugs, at least 1,000 programs, exactly the kept keys on every row,
               every camp's slug a fixture program, a valid clock, at least one upcoming ID camp on it.
  people       no email address, no person-shaped key.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import search_fixture  # noqa: E402

FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures", "search")
FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail="") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return cond


PERSON_KEYS = re.compile(r'"[^"]*(coach|staff|roster|commit|contact|email|phone|player)[^"]*"\s*:', re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def made_up() -> tuple[dict, dict]:
    def prog(slug, **o):
        r = {"slug": slug, "name": f"{slug.title()} University", "shortName": slug.title(), "nickname": "Owls",
             "searchNames": [slug.title(), f"{slug.title()} University"], "city": "Somewhere", "state": "OH",
             "region": "Midwest", "division": "D3", "conference": "Test", "headCoach": "Should Not Appear",
             "coachSince": 2001, "rosterSize": 28, "commitmentsByYear": {"2027": 3}, "admissionRate": 0.5}
        r.update(o)
        return r
    programs = {"updated": "2026-10-01T00:00:00Z", "season": {"gradYears": [2027]},
                "programs": [prog("beta"), prog("alpha", division="D1", nickname=None)]}
    camps = {"updated": "2026-10-02T23:30:00Z", "window": {"from": "2026-10-02", "to": None}, "counts": {"total": 2},
             "camps": [{"slug": "alpha", "name": "Winter ID Camp", "startDate": "2026-12-05", "endDate": None,
                        "dateText": "Dec 5", "precision": "day", "yearInferred": False, "location": None, "ages": None,
                        "price": None, "registerUrl": "https://example.edu/r", "sourceUrl": "https://example.edu/s",
                        "kind": "camp", "campType": "id", "confidence": "heuristic",
                        "contact": "coach@example.edu",
                        "program": {"name": "Alpha University", "shortName": "Alpha", "division": "D1", "city": "X",
                                    "state": "OH", "region": "Midwest", "headCoach": "Should Not Appear"}},
                       {"slug": "beta", "name": "Fall Clinic", "startDate": "2026-11", "precision": "month",
                        "campType": "youth"}]}
    return programs, camps


def test_builder() -> None:
    programs_in, camps_in = made_up()
    programs, camps = search_fixture.cut(programs_in, camps_in)
    ok("builder: program rows in the doc's order", [r["slug"] for r in programs["programs"]] == ["beta", "alpha"])
    ok("builder: exactly the kept program keys", all(tuple(r) == search_fixture.PROGRAM_KEYS for r in programs["programs"]),
       [list(r) for r in programs["programs"]])
    ok("builder: program values carried unchanged", programs["programs"][1]["division"] == "D1"
       and programs["programs"][1]["nickname"] is None and programs["programs"][0]["searchNames"] == ["Beta", "Beta University"])
    ok("builder: the programs doc keeps updated and programs only", list(programs) == ["updated", "programs"], list(programs))
    ok("builder: the camps doc keeps updated and camps only", list(camps) == ["updated", "camps"], list(camps))
    ok("builder: exactly the kept camp keys", all(tuple(r) == search_fixture.CAMP_KEYS for r in camps["camps"]),
       [list(r) for r in camps["camps"]])
    ok("builder: the program block cut to its keys", tuple(camps["camps"][0]["program"]) == search_fixture.CAMP_PROGRAM_KEYS,
       camps["camps"][0]["program"])
    ok("builder: a missing program block stays null, a missing endDate null",
       camps["camps"][1]["program"] is None and camps["camps"][1]["endDate"] is None, camps["camps"][1])
    out = search_fixture.texts(programs_in, camps_in)
    ok("builder: dumps round-trips", json.loads(out["programs.json"]) == programs and json.loads(out["camps.json"]) == camps)
    ok("builder: one row per line", sum(1 for ln in out["programs.json"].splitlines() if ln.lstrip().startswith('{"slug":')) == 2
       and sum(1 for ln in out["camps.json"].splitlines() if ln.lstrip().startswith('{"slug":')) == 2)
    joined = out["programs.json"] + out["camps.json"]
    ok("builder: nothing from the coach, roster, commitment or contact fields",
       "Should Not Appear" not in joined and not EMAIL.search(joined) and not PERSON_KEYS.search(joined), joined[:300])
    ok("builder: clock is the date part of camps' updated", search_fixture.clock(camps) == "2026-10-02")


def files() -> dict[str, str]:
    out = {}
    for name in ("programs.json", "camps.json"):
        with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as f:
            out[name] = f.read()
    return out


def test_idempotent() -> None:
    have = files()
    again = search_fixture.texts(json.loads(have["programs.json"]), json.loads(have["camps.json"]))
    for name in have:
        ok(f"idempotent: cut() of the fixture's own {name} gives it back byte for byte", again[name] == have[name])


def test_shape() -> None:
    have = files()
    programs, camps = json.loads(have["programs.json"]), json.loads(have["camps.json"])
    ok("shape: programs.json is { updated, programs }", list(programs) == ["updated", "programs"], list(programs))
    ok("shape: camps.json is { updated, camps }", list(camps) == ["updated", "camps"], list(camps))
    rows = programs["programs"]
    slugs = [r["slug"] for r in rows]
    ok("shape: at least 1,000 programs", len(rows) >= 1000, len(rows))
    ok("shape: unique program slugs", len(set(slugs)) == len(slugs))
    ok("shape: every program row has exactly the kept keys", all(tuple(r) == search_fixture.PROGRAM_KEYS for r in rows))
    ok("shape: every program has a division", all(r["division"] in ("D1", "D2", "D3") for r in rows))
    ok("shape: every camp row has exactly the kept keys", all(tuple(r) == search_fixture.CAMP_KEYS for r in camps["camps"]))
    known = set(slugs)
    ok("shape: every camp belongs to a fixture program", all(c["slug"] in known for c in camps["camps"]),
       [c["slug"] for c in camps["camps"] if c["slug"] not in known][:5])
    day = search_fixture.clock(camps)
    ok("shape: the clock is a date", bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)), day)
    upcoming = [c for c in camps["camps"] if c["campType"] == "id" and c["startDate"] and (c["endDate"] or c["startDate"]) >= day]
    ok("shape: at least 50 upcoming ID camps on the clock", len(upcoming) >= 50, len(upcoming))


def test_people() -> None:
    joined = "".join(files().values())
    ok("people: no email address", not EMAIL.search(joined), EMAIL.search(joined))
    ok("people: no person-shaped key", not PERSON_KEYS.search(joined), PERSON_KEYS.search(joined))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_builder, test_idempotent, test_shape, test_people):
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
