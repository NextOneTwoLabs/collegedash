"""Regression tests for national titles per division (issue #113).

    python tests/titles_test.py            # everything below, offline
    python tests/titles_test.py --verbose  # print every check, not only the failures

Offline: reads the committed champions tables, the committed registry and profiles, and builds program
sections from fixtures in memory. Writes only into a temporary directory. Exit 0 when every check passes.

Issue #113: `national_titles()` kept only the years the **Division I** table gave a slug, whatever the
program's division, and threw the rest away with a log line. A Division II program with real Division II
titles published none, `validate` exited 0, and nothing said so. Titles are now looked up in the table
for the program's own division, and a year no table supports is reported instead of dropped.

Covers, in order:
  tables     the committed D1 and D2 champions tables: shape, coverage, no duplicate or invented year,
             and the D2 sources cited in build.py
  matching   title_matches: a slug for D1, an exact normalised school name for D2, a pinned override,
             and the near-misses it deliberately refuses
  build      national_titles per division, including the exact #113 reproduction, and what
             build_program_section publishes
  check      check_titles fails for a wrong D1 year, a missing D1 year, a wrong D2 year and an ambiguous
             D2 champion, passes for correct ones, and reports unsourced claims ("note: titles ...")
             without failing and without borrowing a prefix seasons_test.py reads as a failure
  committed  the published D1 profiles and what check_titles says about them today
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

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def entry(slug, division, name=None, short=None):
    return {"slug": slug, "division": division, "name": name or slug.replace("-", " ").title(), "shortName": short}


def profile_of(program, wiki_years=()):
    wiki = {"data": {"nationalTitles": list(wiki_years)}}
    return build.build_program_section(program, wiki, None)


def run_check(tmp: str, programs: list[dict], sections: dict[str, dict]) -> tuple[bool, str]:
    """check_titles over a scratch profiles directory holding one profile per program."""
    d = os.path.join(tmp, f"case{len(os.listdir(tmp)) if os.path.isdir(tmp) else 0}")
    os.makedirs(d, exist_ok=True)
    for p in programs:
        common.write_json(os.path.join(d, f"{p['slug']}.json"), {"slug": p["slug"], "program": sections[p["slug"]]})
    reg = {"onboardedDivisions": sorted({p["division"] for p in programs}),
           "programs": [{**p, "onboarded": True} for p in programs], "heldPrograms": []}
    buf = io.StringIO()
    real = common.PROGRAMS_OUT_DIR
    common.PROGRAMS_OUT_DIR = d
    try:
        with contextlib.redirect_stdout(buf):
            passed = build.check_titles(reg)
    finally:
        common.PROGRAMS_OUT_DIR = real
    return passed, buf.getvalue().strip()


# ---------- the tables ----------

def test_tables() -> None:
    print("tables: the committed champions tables")
    d1, d2 = build.NCAA_D1_WOMENS_CHAMPIONS, build.NCAA_D2_WOMENS_CHAMPIONS
    ok("the D1 table is unchanged by this work: 1982-2025, 44 years", len(d1) == 44 and min(d1) == 1982 and max(d1) == 2025
       and set(d1) == set(range(1982, 2026)), f"{len(d1)} years")
    # fails if a year is invented, or a played year is dropped: the D2 tournament starts in 1988 and 2020
    # was cancelled, so the table is every year from 1988 to 2025 except 2020
    ok("the D2 table is 1988-2025 with 2020 absent, 37 years",
       set(d2) == set(range(1988, 2026)) - {2020} and len(d2) == 37, f"{len(d2)} years, missing {sorted(set(range(1988, 2026)) - set(d2))}")
    ok("no D2 year is blank or a placeholder", all(isinstance(v, str) and v.strip() and "(" not in v for v in d2.values()),
       [v for v in d2.values() if not (isinstance(v, str) and v.strip() and "(" not in v)])
    ok("2020 is not in either table (cancelled for COVID)", 2020 not in d2 and d1.get(2020) == "santa-clara",
       "D1 2020 was played in spring 2021 and is in the D1 record; D2 2020 was cancelled")
    src = open(os.path.join(ROOT, "build.py"), encoding="utf-8").read()
    # fails if the table is ever edited without the sources it came from staying next to it
    ok("both D2 sources are cited in build.py", "ncaa.com/history/soccer-women/d2" in src
       and "NCAA Division II women's soccer tournament" in src, "citation missing")
    ok("Grand Valley State has the most D2 titles, 7",
       sum(1 for v in d2.values() if v == "Grand Valley State") == 7,
       sum(1 for v in d2.values() if v == "Grand Valley State"))
    ok("every division with a table is a division the site knows", set(build.CHAMPION_TABLES) <= {"D1", "D2", "D3"})


# ---------- matching ----------

def test_matching() -> None:
    print("matching: which program a champion name belongs to")
    unc = entry("north-carolina", "D1", "University of North Carolina at Chapel Hill", "North Carolina")
    ok("a D1 champion is matched by slug, exactly", build.title_matches(unc, "north-carolina", "D1")
       and not build.title_matches(unc, "North Carolina", "D1"))
    gvsu = entry("grand-valley-state", "D2", "Grand Valley State University", "Grand Valley State")
    ok("a D2 champion is matched by its normalised name", build.title_matches(gvsu, "Grand Valley State", "D2"))
    rose = entry("saint-rose", "D2", "The College of Saint Rose", None)
    ok("'The College of' and 'University' are ignored in the comparison", build.title_matches(rose, "Saint Rose", "D2"))
    omaha = entry("omaha", "D2", "University of Nebraska at Omaha", "Omaha")
    ok("so are 'of' and 'at', and a hyphen", build.title_matches(omaha, "Nebraska-Omaha", "D2"))
    # fails if the comparison is ever loosened to a prefix or a token overlap: these are different schools
    loma = entry("point-loma", "D2", "Point Loma Nazarene University", "Point Loma Nazarene")
    ok("a near-miss is refused, not guessed (it needs a pinned entry instead)",
       not build.title_matches(loma, "Point Loma", "D2"))
    ok("and so is another school that merely starts the same way",
       not build.title_matches(entry("west-florida-state", "D2", "West Florida State College"), "West Florida", "D2"))
    saved = build.D2_TITLE_SLUGS
    try:
        build.D2_TITLE_SLUGS = {"Point Loma": "point-loma"}
        ok("a pinned entry settles it", build.title_matches(loma, "Point Loma", "D2"))
        ok("and pins only the slug it names", not build.title_matches(entry("other", "D2", "Other"), "Point Loma", "D2"))
    finally:
        build.D2_TITLE_SLUGS = saved
    ok("the pin table is empty while no D2 program is published", build.D2_TITLE_SLUGS == {})
    # fails if a division with no table starts inheriting another division's
    ok("a D3 program matches nothing, because there is no D3 table yet",
       not build.title_matches(entry("some-d3", "D3", "Grand Valley State University"), "Grand Valley State", "D3"))
    # The D3 path (#94): with no D3 table a D3 program publishes no titles and nothing raises; the years a
    # source claims are kept as unsourced, exactly as for any division without a table.
    d3 = entry("test-d3", "D3", "Test College of Example", "Example")
    ok("with no D3 table, national_titles gives a D3 program no titles and keeps the claim as unsourced",
       build.national_titles(d3, [2019]) == ([], [2019]))
    ok("and D3_TITLE_SLUGS exists, empty, for the table's reviewed joins", build.D3_TITLE_SLUGS == {})
    saved_tables, saved_pins = build.CHAMPION_TABLES, build.D3_TITLE_SLUGS
    try:
        # the shape the cited D3 table will have: keyed by champion NAME, like D2's
        build.CHAMPION_TABLES = {**saved_tables, "D3": {2018: "Example", 2019: "Pinned Champion"}}
        # fails if the D3 path is not the name-keyed join D2 uses (e.g. a slug comparison, or D2's table read for D3)
        ok("with a D3 table, a D3 champion joins its program by normalised name",
           build.national_titles(d3, []) == ([2018], []))
        ok("a D2 program of the same name is not given the D3 title", build.national_titles({**d3, "division": "D2"}, [])[0] == [])
        pinned = entry("pinned-d3", "D3", "Pinned Champion College of Nowhere")
        ok("a D3 name normalisation cannot reach needs a pin", not build.title_matches(pinned, "Pinned Champion", "D3"))
        build.D3_TITLE_SLUGS = {"Pinned Champion": "pinned-d3"}
        # fails if D3's pins are not read (or D2's are read for D3)
        ok("D3_TITLE_SLUGS settles it", build.title_matches(pinned, "Pinned Champion", "D3"))
        ok("and D2_TITLE_SLUGS is not read for D3", build.D2_TITLE_SLUGS.get("Pinned Champion") is None
           and not build.title_matches(entry("pinned-d2", "D2", "Nowhere"), "Pinned Champion", "D3"))
    finally:
        build.CHAMPION_TABLES, build.D3_TITLE_SLUGS = saved_tables, saved_pins


# ---------- what the build publishes ----------

def test_build() -> None:
    print("build: national_titles and the program section, per division")
    unc = entry("north-carolina", "D1", "University of North Carolina at Chapel Hill", "North Carolina")
    titles, unsourced = build.national_titles(unc, [])
    ok("a D1 program still gets exactly its D1 years", titles == sorted(y for y, s in build.NCAA_D1_WOMENS_CHAMPIONS.items()
                                                                       if s == "north-carolina") and len(titles) == 22, str(len(titles)))
    ok("and nothing is reported for it", unsourced == [])

    # The exact #113 reproduction: a D2 program with D2 titles. Before, both years were dropped in silence.
    gvsu = entry("grand-valley-state", "D2", "Grand Valley State University", "Grand Valley State")
    titles, unsourced = build.national_titles(gvsu, [2019, 2021])
    ok("a D2 program's D2 titles survive the build", titles == [2009, 2010, 2013, 2014, 2015, 2019, 2021], str(titles))
    ok("and its Wikipedia years are all accounted for", unsourced == [])
    section = profile_of(gvsu, [2019, 2021])
    ok("the published section carries them", section["nationalTitles"] == titles)
    ok("and carries no unsourced key when there is nothing to report", "unsourcedTitleClaims" not in section)

    # a year nothing supports: reported, not published, and not silently dropped
    titles, unsourced = build.national_titles(gvsu, [2019, 1999])
    ok("a year the table does not give it is reported", titles == [2009, 2010, 2013, 2014, 2015, 2019, 2021] and unsourced == [1999],
       f"{titles} {unsourced}")
    section = profile_of(gvsu, [2019, 1999])
    ok("and published in the profile so check_titles can report it", section.get("unsourcedTitleClaims") == [1999])
    # fails if the new published field is not described where every other published field is
    schema = common.read_json(common.SCHEMA_PATH)
    prop = ((schema.get("properties") or {}).get("program") or {}).get("properties") or {}
    ok("the schema declares the field and its shape",
       prop.get("unsourcedTitleClaims") == {"type": "array", "items": {"type": "integer"}}, prop.get("unsourcedTitleClaims"))
    try:
        import jsonschema
        doc = {"slug": gvsu["slug"], "program": section}
        errs = [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(doc)
                if "unsourcedTitleClaims" in str(list(e.path)) or "unsourcedTitleClaims" in e.message]
        ok("a profile carrying it validates", not errs, errs[:2])
        bad = {"slug": gvsu["slug"], "program": {**section, "unsourcedTitleClaims": ["1999"]}}
        on_field = [e for e in jsonschema.Draft202012Validator(schema).iter_errors(bad)
                    if list(e.path)[:2] == ["program", "unsourcedTitleClaims"]]
        ok("and a non-year in it does not", bool(on_field), "no error on that path")
    except ImportError:
        print("  (jsonschema not installed; the two schema checks below need it)")

    # fails if a division's titles leak into another division's program
    wf = entry("west-florida", "D1", "University of West Florida", "West Florida")
    titles, unsourced = build.national_titles(wf, [])
    ok("West Florida, D2 champion in 2012 and now a D1 program, publishes no D1 title", titles == [], str(titles))
    ok("and the D2 table still names it for 2012", build.NCAA_D2_WOMENS_CHAMPIONS[2012] == "West Florida")
    d2_wf = entry("west-florida", "D2", "University of West Florida", "West Florida")
    ok("the same program as a D2 entry would get 2012", build.national_titles(d2_wf, [])[0] == [2012])


# ---------- check_titles ----------

def test_check() -> None:
    print("check: check_titles fails per division, and reports rather than drops")
    tmp = tempfile.mkdtemp(prefix="titles-")
    try:
        unc = entry("north-carolina", "D1", "University of North Carolina at Chapel Hill", "North Carolina")
        fsu = entry("florida-state", "D1", "Florida State University", "Florida State")
        gvsu = entry("grand-valley-state", "D2", "Grand Valley State University", "Grand Valley State")
        barry = entry("barry", "D2", "Barry University", "Barry")
        programs = [unc, fsu, gvsu, barry]
        good = {p["slug"]: profile_of(p) for p in programs}
        passed, out = run_check(tmp, programs, good)
        ok("correct titles in both divisions pass", passed, out)
        held = sum(len(profile_of(p)["nationalTitles"]) for p in programs)
        rest = len(build.NCAA_D1_WOMENS_CHAMPIONS) + len(build.NCAA_D2_WOMENS_CHAMPIONS) - held
        # fails if a champion year is neither published nor counted as belonging to an unpublished program
        ok("and every other champion year is counted as belonging to a program the site does not publish",
           f"note: titles: {rest} champion years" in out, out)

        # fails if a D1 year can be published by a program that did not win it
        bent = copy.deepcopy(good)
        bent["florida-state"]["nationalTitles"] = sorted(bent["florida-state"]["nationalTitles"] + [1994])
        passed, out = run_check(tmp, programs, bent)
        ok("a wrong D1 year fails, naming the division, year and program",
           not passed and "TITLES D1 1994: published by florida-state" in out, out)

        # fails if a champion can quietly stop publishing a year it won
        bent = copy.deepcopy(good)
        bent["north-carolina"]["nationalTitles"] = [y for y in bent["north-carolina"]["nationalTitles"] if y != 2024]
        passed, out = run_check(tmp, programs, bent)
        ok("a missing D1 year fails", not passed and "TITLES D1 2024: north-carolina is the champion but publishes no title" in out, out)

        # the same, in Division II: this is what #113 could not catch at all
        bent = copy.deepcopy(good)
        bent["barry"]["nationalTitles"] = sorted(bent["barry"]["nationalTitles"] + [2009])
        passed, out = run_check(tmp, programs, bent)
        ok("a wrong D2 year fails, against the D2 table",
           not passed and "TITLES D2 2009: published by barry" in out and "Grand Valley State" in out, out)
        bent = copy.deepcopy(good)
        bent["grand-valley-state"]["nationalTitles"] = []
        passed, out = run_check(tmp, programs, bent)
        ok("a D2 champion publishing nothing fails, seven times", not passed and out.count("TITLES D2") == 7, out)

        # fails if an unsourced claim goes back to being silently dropped
        with_note = copy.deepcopy(good)
        with_note["barry"]["unsourcedTitleClaims"] = [1999]
        passed, out = run_check(tmp, programs, with_note)
        ok("an unsourced claim is reported", "note: titles barry: title years [1999]" in out, out)
        ok("and does not fail validate by itself", passed, out)
        # fails if a note ever borrows the prefix seasons_test.py reads as "an invariant failed": a
        # permanent note starting "TITLES " would make that suite's validate check complain forever
        ok("and no note uses a prefix that suite treats as a failure",
           not any(l.startswith(("TITLES ", "SEASONS ", "SCHEMA ", "RANK ", "CAMPS", "MISSING", "STALE ", "MEMBERSHIP"))
                   for l in out.splitlines()), out)

        # fails if two programs could both be handed one champion's titles
        twin = entry("grand-valley-state-2", "D2", "Grand Valley State University", "Grand Valley State")
        both = programs + [twin]
        sections = {**good, "grand-valley-state-2": profile_of(twin)}
        passed, out = run_check(tmp, both, sections)
        ok("a D2 champion matching two published programs fails, naming both",
           not passed and "matches more than one published program" in out
           and "grand-valley-state-2" in out, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- the committed data ----------

def test_committed() -> None:
    print("committed: the published profiles")
    reg = common.load_registry()
    programs = build.published_programs(reg)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        passed = build.check_titles(reg)
    out = buf.getvalue()
    ok("check_titles passes on the committed profiles", passed, out[:400])
    ok("no published profile carries an unsourced title claim", "note: titles " not in out, out[:400])
    # Keyed by (division, year), not by year alone (#197): 1989 is North Carolina's D1 title and Barry's D2 title,
    # and a year-keyed map made one of them overwrite the other the moment D2 is published.
    published, doubled = {}, []
    for p in programs:
        prof = common.read_json(os.path.join(common.PROGRAMS_OUT_DIR, f"{p['slug']}.json")) or {}
        for y in ((prof.get("program") or {}).get("nationalTitles") or []):
            key = (p.get("division"), y)
            if key in published:
                doubled.append((key, published[key], p["slug"]))
            published[key] = p["slug"]
    ok("no division's title year is published by two programs", not doubled, str(doubled[:4]))
    d1 = {y: s for (d, y), s in published.items() if d == "D1"}
    # fails if a D1 champion's title stops being published, or a year starts being published by a D1 program that did not win it
    ok("every D1 champion year is published by its champion", d1 == build.NCAA_D1_WOMENS_CHAMPIONS,
       str(sorted(set(d1.items()) ^ set(build.NCAA_D1_WOMENS_CHAMPIONS.items()))[:4]))
    # Every other division's published years are years its own table has, published by the program that table's
    # champion joins to. Today no D2 program is published and this holds vacuously; with D2 published it is checked.
    by_slug = {p["slug"]: p for p in programs}
    wrong = sorted((d, y, s, (build.CHAMPION_TABLES.get(d) or {}).get(y)) for (d, y), s in published.items()
                   if d != "D1" and not (y in (build.CHAMPION_TABLES.get(d) or {})
                                         and build.title_matches(by_slug[s], build.CHAMPION_TABLES[d][y], d)))
    # fails if a D2 program publishes a year its table does not give it (or a D1 year leaks into D2)
    ok("every non-D1 title year is its own division's champion year, published by that champion", not wrong, str(wrong[:4]))
    missing = sorted((d, y, champion, [q["slug"] for q in programs if q.get("division") == d and build.title_matches(q, champion, d)])
                     for d, table in build.CHAMPION_TABLES.items() if d != "D1" for y, champion in table.items()
                     if (d, y) not in published and any(q.get("division") == d and build.title_matches(q, champion, d) for q in programs))
    # fails if a published D2 champion stops publishing one of its title years
    ok("every non-D1 champion year whose champion is published is published", not missing, str(missing[:4]))
    ok("no published program is in a division with no champions table",
       all(p.get("division") in build.CHAMPION_TABLES for p in programs),
       sorted({p.get("division") for p in programs} - set(build.CHAMPION_TABLES)))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    VERBOSE = ap.parse_args(argv).verbose
    test_tables()
    test_matching()
    test_build()
    test_check()
    test_committed()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
