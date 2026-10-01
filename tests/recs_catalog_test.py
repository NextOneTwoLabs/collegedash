"""The recommender's frozen test catalog, tests/fixtures/recs/catalog.json, and its builder tools/recs_catalog.py
(issue #400, PR 2).

    python tests/recs_catalog_test.py            # every case
    python tests/recs_catalog_test.py --verbose  # print every check, not only the failures

The fixture is frozen on purpose: the daily refresh must never move a ranker expectation, so nothing here compares
it with today's public/data (that is `python tools/recs_catalog.py --check`, run by hand when regenerating). What
is checked instead is that it is still the shape and the taxonomy the build makes, and that it carries programs
and schools only. Offline, under tests/netguard; nothing is written under tests/ or public/.

Cases:
  builder      catalog() on made-up profiles: one row per index row, in order, only the ranker's row fields, and
               each fit entry exactly build.fit_entry of that profile; dumps() round-trips and puts one program
               per line.
  taxonomy     the fixture's fitTaxonomy, constants and sources are this build's; every climate label is what
               build.climate_label gives its own coldMonthMeanF and stationKm, so a rule change can't leave the
               fixture behind silently.
  shape        unique slugs, exactly the row keys and build.FIT_KEYS, one fit entry per program in the same
               order, the fit part valid against schema/fit.schema.json, at least 1,000 programs.
  people       no email address, no person-shaped key (coach, staff, roster, commit, contact, email, phone).
  coverage     the three programs with no school record are present and unknown, as the scenarios expect.
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

import build  # noqa: E402
import recs_catalog  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "recs", "catalog.json")
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


def monthly(cold_hi: float, cold_lo: float) -> list[dict]:
    """Twelve months whose coldest has the given normals; the rest are warmer."""
    return [{"tHighF": cold_hi + (5 if i else 0), "tLowF": cold_lo + (5 if i else 0)} for i in range(12)]


def profile(slug: str, *, unit=1, station_km=10.0, hi=40.0, lo=20.0, school=True, climate=True) -> dict:
    p = {"slug": slug}
    if school:
        p["school"] = {"unitId": unit, "_meta": {"asOf": "2026-09-06T12:00:00Z"},
                       "headCoach": {"name": "Should Not Appear", "email": "nobody@example.edu"}}
    if climate:
        p["climate"] = {"station": {"id": f"USW{unit:08d}", "distanceKm": station_km}, "monthly": monthly(hi, lo),
                        "_meta": {"asOf": "2026-09-08T12:00:00Z"}}
    p["roster"] = [{"name": "A Player", "email": "player@example.edu"}]
    return p


def index_row(slug: str, **o) -> dict:
    row = {"slug": slug, "name": f"{slug.title()} University", "shortName": slug.title(), "division": "D3", "conference": "Test",
           "region": "West", "state": "CA", "undergradEnrollment": 2000, "city": "Somewhere", "rpi": 12, "rosterSize": 28,
           "headCoach": "Should Not Appear", "commitmentsByYear": {"2027": 3}}
    row.update(o)
    return row


def test_builder() -> None:
    profiles = {"alpha": profile("alpha", unit=11), "beta": profile("beta", unit=22, station_km=80.0),
                "gamma": profile("gamma", school=False, climate=False)}
    index = {"updated": "2026-09-30T00:00:00Z", "programs": [index_row("beta"), index_row("alpha", division="D1"),
                                                             index_row("gamma", region=None, state=None, undergradEnrollment=None)]}
    doc = recs_catalog.catalog(index, profiles.get)
    ok("builder: rows in the index's order", [r["slug"] for r in doc["programs"]] == ["beta", "alpha", "gamma"], doc["programs"])
    ok("builder: only the ranker's row fields", all(list(r) == list(recs_catalog.ROW_KEYS) for r in doc["programs"]),
       [list(r) for r in doc["programs"]])
    ok("builder: row values carried unchanged", doc["programs"][1]["division"] == "D1" and doc["programs"][2]["region"] is None)
    ok("builder: fit entries are build.fit_entry of each profile",
       all(doc["fit"][s] == build.fit_entry(profiles[s]) for s in profiles), doc["fit"])
    ok("builder: a far station is climate-unknown", doc["fit"]["beta"]["climate"] is None and doc["fit"]["beta"]["climateUnknown"] == "far-station")
    ok("builder: no school or climate source", doc["fit"]["gamma"]["unitId"] is None and doc["fit"]["gamma"]["climateUnknown"] == "no-climate-source")
    ok("builder: taxonomy, constants and sources are the build's",
       (doc["fitTaxonomy"], doc["constants"], doc["sources"]) == (build.FIT_TAXONOMY, build.fit_constants(), build.FIT_SOURCES))
    text = recs_catalog.dumps(doc)
    ok("builder: dumps round-trips", json.loads(text) == doc)
    lines = text.splitlines()
    ok("builder: one program per line", sum(1 for ln in lines if ln.lstrip().startswith('{"slug":')) == 3
       and sum(1 for ln in lines if re.match(r'^\s+"(alpha|beta|gamma)": \{', ln)) == 3, lines)
    ok("builder: nothing from the coach, roster or contact fields", "Should Not Appear" not in text and "@" not in text, text[:300])


FIXTURE_DOC: dict = {}


def load() -> dict:
    if not FIXTURE_DOC:
        with open(FIXTURE, encoding="utf-8") as f:
            FIXTURE_DOC.update(json.load(f))
    return FIXTURE_DOC


def test_taxonomy() -> None:
    doc = load()
    ok("taxonomy: fit-1", doc["fitTaxonomy"] == build.FIT_TAXONOMY == "fit-1", doc["fitTaxonomy"])
    ok("taxonomy: constants are this build's", doc["constants"] == build.fit_constants(), doc["constants"])
    ok("taxonomy: sources are this build's", doc["sources"] == build.FIT_SOURCES)
    wrong = []
    for slug, e in doc["fit"].items():
        if e["climateUnknown"] in ("no-climate-source",):
            continue
        label, why = build.climate_label(e["coldMonthMeanF"], e["stationKm"])
        if (label, why) != (e["climate"], e["climateUnknown"]):
            wrong.append((slug, e["climate"], e["climateUnknown"], label, why))
    ok("taxonomy: every climate label follows the build's rule for its own figures", not wrong, wrong[:5])


def test_shape() -> None:
    doc = load()
    progs = doc["programs"]
    slugs = [p["slug"] for p in progs]
    ok("shape: at least 1,000 programs", len(progs) >= 1000, len(progs))
    ok("shape: unique slugs", len(set(slugs)) == len(slugs))
    ok("shape: exactly the row keys", all(list(p) == list(recs_catalog.ROW_KEYS) for p in progs))
    ok("shape: one fit entry per program, same order", list(doc["fit"]) == slugs)
    ok("shape: exactly build.FIT_KEYS per entry", all(list(e) == list(build.FIT_KEYS) for e in doc["fit"].values()))
    ok("shape: top-level keys", list(doc) == ["about", "updated", "fitTaxonomy", "constants", "sources", "programs", "fit"], list(doc))
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
    if ok("shape: jsonschema is installed (requirements.txt)", jsonschema is not None):
        with open(build.FIT_SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        fit_doc = {k: doc[k] for k in ("updated", "fitTaxonomy", "constants", "sources", "fit")}
        errs = list(jsonschema.Draft202012Validator(schema).iter_errors(fit_doc))
        ok("shape: the fit part is valid against schema/fit.schema.json", not errs, [e.message for e in errs[:3]])


PERSON_KEYS = re.compile(r'"[^"]*(coach|staff|roster|commit|contact|email|phone|player)[^"]*"\s*:', re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def test_people() -> None:
    with open(FIXTURE, encoding="utf-8") as f:
        text = f.read()
    ok("people: no email address", not EMAIL.search(text), EMAIL.search(text))
    ok("people: no person-shaped key", not PERSON_KEYS.search(text), PERSON_KEYS.search(text))


def test_coverage() -> None:
    doc = load()
    rows = {p["slug"]: p for p in doc["programs"]}
    for slug in ("simon-fraser", "emmanuel-ga", "claremont-mudd-scripps"):
        r = rows.get(slug) or {}
        ok(f"coverage: {slug} has no school record", r and r["region"] is None and r["undergradEnrollment"] is None, r)
        ok(f"coverage: {slug} has no climate", doc["fit"].get(slug, {}).get("climate", "x") is None)
    unknown = sorted(s for s, r in rows.items() if r["region"] is None)
    ok("coverage: exactly those three have no region", unknown == ["claremont-mudd-scripps", "emmanuel-ga", "simon-fraser"], unknown)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_builder, test_taxonomy, test_shape, test_people, test_coverage):
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
