"""Regression tests for high-school matching against the NCES school list (issue #229).

    python tests/schools_match_test.py            # everything below, offline
    python tests/schools_match_test.py --verbose  # print every check, not only the failures

Offline: reads the committed data/schools.json, makes no request and writes nothing in the
repository. Exit 0 when every check passes, 1 otherwise.

What these hold down, and why each one exists
---------------------------------------------
The owner's rule on #229 is one sentence: never match a high school without the state. "Mountain
View" is a high school in thirteen states in the NCES list, and the rosters name it in seven, so
the name alone would put most of those players in California. The tests are written against the
committed list, by name:

  key           school_key folds case, punctuation, accents, "HS" / "H.S." / "High School" /
                "Senior High" / "Secondary School" / a leading "The", and spells out St., Mt. and
                Ft. It keeps every other word: "Mountain View" and "Mountain View Los Altos" and
                "Lincoln" and "Lincoln Southwest" stay different keys
  state         hometown_state reads the AP-style state the roster pages use ("Calif.", "N.J."),
                a full name, a two-letter code, and a one-word-plus-state form; a hometown ending
                in a country or a province is outside the US; no hometown is no state
  same name     "Mountain View" from Meridian, Idaho and from Orem, Utah resolve to two different
                NCES schools, and from Mountain View, Calif. to none, because California has four.
                A guard checks the committed list really carries all three cases, so the test
                cannot pass against a list that lacks one of them
  ambiguous     two St. Francis High Schools in California: the player stays unmatched, marked
                ambiguous with the candidate count, and the review report lists both candidates
  outside US    the same school name from Vancouver, British Columbia is outside-us and unmatched;
                from Vancouver, Wash. it is the Washington school
  not split     a hometown still carrying "/ <school>" (collected before #227's fix) is not
                matched on its stored highSchool value, which is the Previous School column there
  city prefix   (#325) a spelling that starts with its city - "Southlake Carroll" - matches the one
                school with the rest of the name in that city and state (CARROLL H S, Southlake,
                TX, ccd:481302009392), though "Carroll" alone is ambiguous in Texas. Two schools
                left in the city stay unmatched; the same spelling from another state, from no
                state, or naming a school in a different city does not match
  empty         an empty or placeholder high school ("null", "N/A") gets no schoolInfo
  table         a file that is not what tools/schools_nces.py writes fails to load
  build         annotate_roster_schools writes schoolInfo on a D1 roster and leaves a D2 roster
                alone; a scratch build does not rewrite data/schools-review.json
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

import schools  # noqa: E402
from collect import common  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def check(name: str, ok: bool, detail: str = "") -> None:
    global TOTAL
    TOTAL += 1
    if not ok:
        FAILS.append(name)
        print(f"FAIL {name}" + (f": {detail}" if detail else ""))
    elif VERBOSE:
        print(f"ok   {name}" + (f": {detail}" if detail else ""))


def test_key() -> None:
    same = ["Mountain View HS", "Mountain View High School", "MOUNTAIN VIEW HIGH SCHOOL", "Mountain View H.S.",
            "Mountain View High", "Mountain View Senior High School", "Mountain View Sr. High", "The Mountain View School",
            "Mtn. View HS", "Mountain View Secondary School"]
    for s in same:
        check(f"key: {s!r} -> 'mountain view'", schools.school_key(s) == "mountain view", schools.school_key(s))
    check("key: St. = Saint", schools.school_key("St. Francis HS") == schools.school_key("Saint Francis High School") == "saint francis")
    check("key: apostrophes and accents", schools.school_key("St. Mary's Académie") == "saint marys academie")
    check("key: Ft. and Mt.", schools.school_key("Ft. Worth Mt. Zion") == "fort worth mount zion")
    check("key: preparatory = prep", schools.school_key("Bishop Prep School") == schools.school_key("Bishop Preparatory") == "bishop prep")
    different = [("Mountain View", "Mountain View Los Altos"), ("Lincoln", "Lincoln Southwest"),
                 ("Beach", "Long Beach"), ("Central", "Central Catholic"), ("Mater Dei", "Mater Dei Catholic")]
    for a, b in different:
        check(f"key keeps {a!r} apart from {b!r}", schools.school_key(a) != schools.school_key(b))
    check("key: a bare 'High School' is empty, not a match for everything",
          schools.school_key("High School") == "high" and schools.school_key("School") == "school",
          f"{schools.school_key('High School')!r} {schools.school_key('School')!r}")
    for s in ("null", "N/A", "None", "TBD", "Homeschool", ""):
        check(f"placeholder {s!r}", schools.is_placeholder(s) or not schools.school_key(s))
    check("a school name is not a placeholder", not schools.is_placeholder("Nulla Vista High"))


def test_hometown_state() -> None:
    cases = [
        ("Mountain View, Calif.", ("CA", "us")), ("Los Altos, CA", ("CA", "us")), ("Fresno, California", ("CA", "us")),
        ("Hoboken, N.J.", ("NJ", "us")), ("Orem, Utah", ("UT", "us")), ("Meridian, Idaho", ("ID", "us")),
        ("Vancouver, Wash.", ("WA", "us")), ("Washington, D.C.", ("DC", "us")), ("Bucyrus, Kan.", ("KS", "us")),
        ("Greensboro N.C.", ("NC", "us")), ("Seguin Texas", ("TX", "us")),
        ("Austin, Texas / Westlake HS", ("TX", "us")), ("Austin, Texas /", ("TX", "us")),
        ("Vancouver, British Columbia, Canada", (None, "outside-us")), ("Toronto, Ont.", (None, "outside-us")),
        ("London, England", (None, "outside-us")), ("Stockholm, Sweden", (None, "outside-us")),
        ("", (None, "none")), (None, (None, "none")), ("Layton", (None, "none")), ("/", (None, "none")),
    ]
    for hometown, want in cases:
        got = schools.hometown_state(hometown)
        check(f"hometown_state({hometown!r}) == {want}", got == want, str(got))


def synthetic_table() -> schools.Table:
    rows = [
        ["ccd:1", "Mountain View High School", "Mountain View", "CA", "public", "2023-24"],
        ["ccd:2", "Mountain View High", "El Monte", "CA", "public", "2023-24"],
        ["ccd:3", "MOUNTAIN VIEW HIGH SCHOOL", "Meridian", "ID", "public", "2023-24"],
        ["ccd:4", "Mountain View High", "Orem", "UT", "public", "2023-24"],
        ["pss:5", "ST FRANCIS HIGH SCHOOL", "Mountain View", "CA", "private", "2023-24"],
        ["pss:6", "ST FRANCIS HIGH SCHOOL", "La Canada Flintridge", "CA", "private", "2021-22"],
        ["ccd:7", "Los Altos High", "Los Altos", "CA", "public", "2023-24"],
        ["ccd:8", "Miami School", "Miami", "TX", "public", "2023-24"],
    ]
    return schools.Table({"columns": list(schools.COLUMNS), "rows": rows})


def test_rules_on_a_synthetic_table() -> None:
    t = synthetic_table()
    m = t.match("Mountain View HS", "Meridian, Idaho")
    check("synthetic: Idaho player -> the Idaho school", m.status == "matched" and m.schoolId == "ccd:3", m.as_dict())
    m = t.match("Mountain View High School", "Orem, Utah")
    check("synthetic: Utah player -> the Utah school", m.status == "matched" and m.schoolId == "ccd:4", m.as_dict())
    m = t.match("Mountain View HS", "Mountain View, Calif.")
    check("synthetic: two Mountain Views in California -> ambiguous, no id",
          m.status == "ambiguous" and m.schoolId is None and m.candidates == 2 and m.state == "CA", m.as_dict())
    m = t.match("Mountain View HS", "Mountain View")
    check("synthetic: no state -> unmatched, never the California school",
          m.status == "unmatched" and m.schoolId is None and m.state is None, m.as_dict())
    # The rule is "never without a state", not "never when the name is in several states": a name
    # that is unique across the whole table must not match either. Los Altos is the only one here.
    check("synthetic guard: exactly one Los Altos in the whole table",
          sum(1 for (st, k) in t.by_key if k == "los altos") == 1)
    for hometown in ("", None, "Los Altos"):
        m = t.match("Los Altos High School", hometown)
        check(f"synthetic: a table-wide unique name with hometown {hometown!r} is still unmatched",
              m.status == "unmatched" and m.schoolId is None and m.state is None, m.as_dict())
    m = t.match("St. Francis", "Mountain View, Calif.")
    check("synthetic: St. Francis in California is ambiguous across two survey years",
          m.status == "ambiguous" and m.candidates == 2, m.as_dict())
    m = t.match("Mountain View HS", "Vancouver, British Columbia, Canada")
    check("synthetic: outside the US is not matched", m.status == "outside-us" and m.schoolId is None, m.as_dict())
    m = t.match("Miami", "McKinney, Texas / Frisco Heritage")
    check("synthetic: a hometown not yet split keeps its Previous School value unmatched",
          m.status == "unmatched" and m.schoolId is None and m.reason == schools.REASON_NOT_SPLIT, m.as_dict())
    m = t.match("Los Altos", "Los Altos, Calif. / Los Altos High")
    check("synthetic: a not-yet-split hometown whose slash part IS the high school still matches",
          m.status == "matched" and m.schoolId == "ccd:7", m.as_dict())
    m = t.match("Los Altos", "Los Altos, Calif. /")
    check("synthetic: a trailing slash with nothing after it is still an unsplit cell: unmatched",
          m.status == "unmatched" and m.schoolId is None and m.reason == schools.REASON_NOT_SPLIT, m.as_dict())
    for raw in ("", None, "null", "N/A"):
        m = t.match(raw, "Los Altos, Calif.")
        check(f"synthetic: {raw!r} high school -> none", m.status == "none" and m.schoolId is None)
    d = t.match("Mountain View HS", "Orem, Utah").as_dict()
    check("as_dict carries raw, key, schoolId, state, status, school, city, type",
          d == {"raw": "Mountain View HS", "key": "mountain view", "schoolId": "ccd:4", "state": "UT",
                "status": "matched", "school": "Mountain View High", "city": "Orem", "type": "public"}, d)
    check("candidates() is empty without a state", t.candidates("Mountain View", None) == [])


def test_city_prefix() -> None:
    """#325 on a synthetic table. The first two checks fail on the code before #325; the rest are
    guards (the code before #325 also leaves them unmatched) that keep the new rule narrow."""
    rows = [
        ["pss:10", "ST FRANCIS HIGH SCHOOL", "Mountain View", "CA", "private", "2023-24"],
        ["pss:11", "ST FRANCIS HIGH SCHOOL", "Sacramento", "CA", "private", "2023-24"],
        ["ccd:12", "Los Altos High", "Los Altos", "CA", "public", "2023-24"],
        ["ccd:13", "CENTRAL H S", "Keller", "TX", "public", "2023-24"],
        ["ccd:14", "Central High School", "Keller", "TX", "public", "2023-24"],
        ["ccd:15", "Polytechnic High", "Long Beach", "CA", "public", "2023-24"],
    ]
    t = schools.Table({"columns": list(schools.COLUMNS), "rows": rows})
    m = t.match("Mountain View St. Francis", "Palo Alto, Calif.")
    check("city prefix: 'Mountain View St. Francis' in CA -> the one St. Francis in Mountain View",
          m.status == "matched" and m.schoolId == "pss:10", m.as_dict())
    m = t.match("Long Beach Polytechnic HS", "Long Beach, Calif.")
    check("city prefix: a two-word city ('Long Beach') is tried", m.status == "matched" and m.schoolId == "ccd:15",
          m.as_dict())
    m = t.match("Keller Central", "Keller, Texas")
    check("guard: city prefix with two schools left in the city stays unmatched",
          m.status == "unmatched" and m.schoolId is None, m.as_dict())
    m = t.match("Mountain View St. Francis", "Portland, Ore.")
    check("guard: city prefix in the wrong state does not match", m.status == "unmatched" and m.schoolId is None,
          m.as_dict())
    m = t.match("Mountain View St. Francis", "Layton")
    check("guard: city prefix without a state does not match", m.status == "unmatched" and m.schoolId is None,
          m.as_dict())
    m = t.match("Mountain View Los Altos", "Mountain View, Calif.")
    check("guard: the rest of the name must be a school in THAT city (Los Altos High is in Los Altos)",
          m.status == "unmatched" and m.schoolId is None, m.as_dict())
    m = t.match("St. Francis", "Mountain View, Calif.")
    check("guard: a bare name ambiguous in the state stays ambiguous (the hometown city is not used)",
          m.status == "ambiguous", m.as_dict())


def test_table_validation() -> None:
    bad = [
        ("wrong columns", {"columns": ["id", "name"], "rows": []}),
        ("short row", {"columns": list(schools.COLUMNS), "rows": [["ccd:1", "X High", "Y", "CA"]]}),
        ("duplicate id", {"columns": list(schools.COLUMNS),
                          "rows": [["ccd:1", "X High", "Y", "CA", "public", "2023-24"], ["ccd:1", "Z High", "Y", "CA", "public", "2023-24"]]}),
        ("not a state", {"columns": list(schools.COLUMNS), "rows": [["ccd:1", "X High", "Y", "ON", "public", "2023-24"]]}),
    ]
    for name, doc in bad:
        try:
            schools.Table(doc)
            check(f"table: {name} fails to load", False)
        except schools.TableError:
            check(f"table: {name} fails to load", True)
    try:
        schools.load_table(os.path.join(tempfile.gettempdir(), "collegedash-no-such-schools.json"), reload=True)
        check("table: a missing file fails to load", False)
    except schools.TableError:
        check("table: a missing file fails to load", True)


def test_committed_list(t: schools.Table) -> None:
    # The guard: the committed list must carry the three cases, or the same-name checks below would
    # pass vacuously against a list that simply lacks the school.
    idaho = t.candidates("Mountain View High School", "ID")
    utah = t.candidates("Mountain View High School", "UT")
    calif = t.candidates("Mountain View High School", "CA")
    check("guard: the list has exactly one Mountain View in Idaho", len(idaho) == 1, str(idaho))
    check("guard: the list has exactly one Mountain View in Utah", len(utah) == 1, str(utah))
    check("guard: the list has more than one Mountain View in California", len(calif) > 1, str(calif))
    check("guard: the list has two St. Francis in California", len(t.candidates("St. Francis", "CA")) == 2,
          str(t.candidates("St. Francis", "CA")))
    check("guard: the list has exactly one Mountain View in Washington", len(t.candidates("Mountain View", "WA")) == 1)
    # #325: "Carroll" alone is ambiguous in Texas; the city in front of it picks the Southlake one
    check("guard: the list has more than one Carroll in Texas", len(t.candidates("Carroll", "TX")) > 1,
          str(t.candidates("Carroll", "TX")))
    for raw in ("Southlake Carroll", "Southlake Carroll HS", "Southlake Carroll H.S.", "Southlake Carroll High School"):
        m = t.match(raw, "Southlake, Texas")
        check(f"city prefix: {raw!r} from Texas -> CARROLL H S, Southlake (ccd:481302009392)",
              m.status == "matched" and m.schoolId == "ccd:481302009392", m.as_dict())
    m = t.match("Southlake Carroll", "Tulsa, Okla.")
    check("guard: 'Southlake Carroll' from Oklahoma does not match", m.status != "matched", m.as_dict())
    check("guard: the list carries public and private schools",
          any(s["type"] == "public" for s in t.schools.values()) and any(s["type"] == "private" for s in t.schools.values()))
    check("guard: the list carries both survey years", {s["year"] for s in t.schools.values()} >= {"2023-24", "2021-22"})
    check("guard: every row is in the 50 states or DC", all(s["state"] in common.US_STATES for s in t.schools.values()))
    check("guard: the header names both sources with a URL and a year",
          all(t.sources.get(k, {}).get("url") and t.sources[k].get("year") for k in ("ccd", "pss")), str(t.sources))

    m_id = t.match("Mountain View HS", "Meridian, Idaho")
    m_ut = t.match("Mountain View High School", "Orem, Utah")
    m_ca = t.match("Mountain View HS", "Mountain View, Calif.")
    check("same name, Idaho: matched to the Meridian school",
          m_id.status == "matched" and m_id.school["city"] == "Meridian" and m_id.state == "ID", m_id.as_dict())
    check("same name, Utah: matched to the Orem school",
          m_ut.status == "matched" and m_ut.school["city"] == "Orem" and m_ut.state == "UT", m_ut.as_dict())
    check("same name, two states: two different NCES ids", m_id.schoolId != m_ut.schoolId)
    check("same name, California: ambiguous, left unmatched",
          m_ca.status == "ambiguous" and m_ca.schoolId is None and m_ca.candidates == len(calif), m_ca.as_dict())
    m_no = t.match("Mountain View HS", "")
    check("same name, no hometown: unmatched, not the Idaho school", m_no.status == "unmatched" and m_no.schoolId is None)
    # A name unique across the entire list is the common case (most cleaned keys are in one state
    # only), and it must not match without a state either. Guarded: the list really has exactly
    # one school whose name cleans to "punahou", so a "unique name" fallback would have matched it.
    punahou = [(st, k) for (st, k) in t.by_key if k == "punahou"]
    check("guard: the list has exactly one Punahou, in Hawaii, and one school under that key",
          punahou == [("HI", "punahou")] and len(t.by_key[("HI", "punahou")]) == 1, str(punahou))
    m_hi = t.match("Punahou School", "Honolulu, Hawaii")
    check("Punahou with its state: matched", m_hi.status == "matched" and m_hi.state == "HI", m_hi.as_dict())
    for hometown in ("", None, "Honolulu"):
        m = t.match("Punahou School", hometown)
        check(f"a list-wide unique name with hometown {hometown!r}: unmatched, no id",
              m.status == "unmatched" and m.schoolId is None and m.state is None, m.as_dict())

    m_sf = t.match("St. Francis", "Mountain View, Calif.")
    check("St. Francis, California: ambiguous with 2 candidates", m_sf.status == "ambiguous" and m_sf.candidates == 2, m_sf.as_dict())
    m_bc = t.match("Mountain View High School", "Vancouver, British Columbia, Canada")
    m_wa = t.match("Mountain View High School", "Vancouver, Wash.")
    check("Vancouver, B.C.: outside-us, no id", m_bc.status == "outside-us" and m_bc.schoolId is None, m_bc.as_dict())
    check("Vancouver, Wash.: the Washington school", m_wa.status == "matched" and m_wa.state == "WA", m_wa.as_dict())
    m_tx = t.match("Miami", "McKinney, Texas / Frisco Heritage")
    check("committed list: 'Miami' on a not-yet-split Texas row is not matched",
          m_tx.status == "unmatched" and m_tx.schoolId is None and m_tx.reason == schools.REASON_NOT_SPLIT, m_tx.as_dict())


def test_recorder_and_report(t: schools.Table) -> None:
    r = schools.Recorder(t)
    players = [
        {"highSchool": "Mountain View HS", "hometown": "Meridian, Idaho"},
        {"highSchool": "St. Francis", "hometown": "Mountain View, Calif."},
        {"highSchool": "St. Francis HS", "hometown": "Sacramento, Calif."},
        {"highSchool": "Nowhere Fictional Academy", "hometown": "Boise, Idaho"},
        {"highSchool": "Nowhere Fictional Academy", "hometown": "Boise, Idaho"},
        {"highSchool": "Mountain View HS", "hometown": "Vancouver, British Columbia, Canada"},
        {"highSchool": "Mountain View HS", "hometown": ""},
        {"highSchool": "", "hometown": "Orem, Utah"},
        {"highSchool": "Miami", "hometown": "McKinney, Texas / Frisco Heritage"},
    ]
    for i, p in enumerate(players):
        r.observe(p, slug=f"prog-{i % 2}")
    c = r.counts
    check("recorder counts", c == {"players": 9, "withHighSchool": 8, "matched": 1, "unmatched": 4, "ambiguous": 2,
                                   "outsideUS": 1, "noState": 1, "notSplit": 1}, str(c))
    report = r.report(None, today="2026-09-17")
    s = report["summary"]
    check("report summary", s["matched"] == 1 and s["unmatched"] == 4 and s["ambiguous"] == 2 and s["outsideUS"] == 1
          and s["unmatchedWithoutAState"] == 1 and s["unmatchedUntilTheNextRosterCollection"] == 1
          and s["playersWithAHighSchool"] == 8 and s["distinctUnmatchedNames"] == 4, str(s))  # St. Francis x2 is one key
    rows = report["unmatched"]
    check("report: most common first", [x["key"] for x in rows][:2] == ["nowhere fictional academy", "saint francis"],
          [x["key"] for x in rows])
    check("report: the fictional name counts 2 across 2 programs and is new",
          rows[0]["occurrences"] == 2 and rows[0]["programs"] == 2 and rows[0]["new"] and rows[0]["firstSeen"] == "2026-09-17"
          and rows[0]["state"] == "ID" and rows[0]["status"] == "unmatched", str(rows[0]))
    sf = next(x for x in rows if x["key"] == "saint francis")
    check("report: the ambiguous row lists both candidates with city and type",
          sf["status"] == "ambiguous" and len(sf["candidates"]) == 2
          and {c["city"] for c in sf["candidates"]} == {"Mountain View", "La Canada Flintridge"}
          and all(c["type"] == "private" for c in sf["candidates"]), str(sf))
    check("report: the not-split row carries its reason",
          any(x.get("reason") == schools.REASON_NOT_SPLIT for x in rows), str([x.get("reason") for x in rows]))
    check("report: outside-us is a count, not a row", all(x["status"] != "outside-us" for x in rows))
    check("report: first report marks everything new", report["newSinceLastBuild"]["count"] == len(rows))
    again = r.report(report, today="2026-09-18")
    check("report: a second build keeps firstSeen and marks nothing new",
          again["newSinceLastBuild"]["count"] == 0 and again["unmatched"][0]["firstSeen"] == "2026-09-17")


def test_build_integration(t: schools.Table) -> None:
    import build

    roster = {"season": 2026, "players": [
        {"name": "A", "pos": "D", "classCode": "FR", "highSchool": "Mountain View HS", "hometown": "Meridian, Idaho"},
        {"name": "B", "pos": "M", "classCode": "SO", "highSchool": "", "hometown": "Orem, Utah"},
        {"name": "C", "pos": "F", "classCode": "JR", "highSchool": "St. Francis", "hometown": "Mountain View, Calif."},
    ]}
    d2 = copy.deepcopy(roster)
    r = schools.Recorder(t)
    build.annotate_roster_schools(roster, division="D1", table=t, recorder=r)
    build.annotate_roster_schools(d2, division="D2", table=t, recorder=r)
    p = roster["players"]
    check("build: D1 player gets a matched schoolInfo", (p[0].get("schoolInfo") or {}).get("status") == "matched"
          and p[0]["schoolInfo"]["state"] == "ID", str(p[0].get("schoolInfo")))
    check("build: empty high school stays empty", "schoolInfo" in p[1] and p[1]["schoolInfo"] is None)
    check("build: ambiguous player is marked, not guessed", p[2]["schoolInfo"]["status"] == "ambiguous"
          and p[2]["schoolInfo"]["schoolId"] is None and p[2]["schoolInfo"]["candidates"] == 2)
    check("build: raw string and key are kept", p[0]["schoolInfo"]["raw"] == "Mountain View HS"
          and p[0]["schoolInfo"]["key"] == "mountain view")
    check("build: a D2 roster is left alone", all("schoolInfo" not in q for q in d2["players"]))
    check("build: the recorder only saw the D1 roster", r.counts["players"] == 3, str(r.counts))
    check("build: no player was mutated beyond schoolInfo",
          {k for q in p for k in q} == {"name", "pos", "classCode", "highSchool", "hometown", "schoolInfo"})

    # The review report lives in data/, outside the output directories a scratch build swaps, so
    # build() decides with publishing_run() whether to write it (as it does for clubs, #228).
    check("a real build writes the review report", build.publishing_run())
    saved = common.PROGRAMS_OUT_DIR
    try:
        common.PROGRAMS_OUT_DIR = os.path.join(tempfile.gettempdir(), "collegedash-scratch-build")
        check("a scratch build does not write the review report", not build.publishing_run())
    finally:
        common.PROGRAMS_OUT_DIR = saved
    check("the swap is undone", build.publishing_run())
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "schools-review.json")
        written = r.write(path)
        check("Recorder.write writes where it is told", os.path.exists(path) and written["summary"]["matched"] == 1)
    check("Recorder.write did not touch the repository's report timestamp",
          not os.path.exists(schools.REVIEW_PATH) or common.read_json(schools.REVIEW_PATH).get("updated") != written["updated"])


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose
    test_key()
    test_hometown_state()
    test_rules_on_a_synthetic_table()
    test_city_prefix()
    test_table_validation()
    table = schools.load_table(reload=True)
    test_committed_list(table)
    test_recorder_and_report(table)
    test_build_integration(table)
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
