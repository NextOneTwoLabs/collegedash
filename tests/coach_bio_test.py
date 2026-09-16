"""Checks for reading a head coach's first season from their bio page (issue #168, part 2).

    python tests/coach_bio_test.py            # everything below, offline
    python tests/coach_bio_test.py --verbose  # print every check, not only the failures

Offline: reads tests/fixtures/coach_bio/ (and one roster fixture of issue #145), and replaces
collect.common's fetch_text, save_source and log with tables, so athletics_site.collect runs end to end
with no request and nothing written under programs/.

Swap-back proof: set COLLEGEDASH_CODE_ROOT to an export of origin/main's collect/ package. origin/main has
no collect/coach_bio.py; the suite then stands in a reader that finds nothing - which is what origin/main
reads from a bio page - so every check still reports on its own:

    git archive origin/main collect | tar -x -C /tmp/pre168b
    COLLEGEDASH_CODE_ROOT=/tmp/pre168b python tests/coach_bio_test.py

Fixtures are real head-coach bio pages trimmed to the page title, the coach's name and the sentences that
state when the tenure began; every email address and telephone number is removed (the privacy checks at
the end scan for both, seven-digit numbers included). Labels: FIX checks fail against origin/main and pass
after the change; CONTROL checks pass on both; GUARD checks (a page that must yield no year) pass on
origin/main only because it reads nothing, and each sits beside a FIX check on the same page that fails there.
"""

from __future__ import annotations

import argparse
import copy
import html as html_lib
import importlib
import os
import re
import sys
import unicodedata
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_ROOT = os.environ.get("COLLEGEDASH_CODE_ROOT") or ROOT
sys.path.insert(0, CODE_ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import athletics_site, common  # noqa: E402

try:
    coach_bio = importlib.import_module("collect.coach_bio")
except ImportError:  # origin/main: nothing reads a coach's bio page
    class _Nothing:
        @staticmethod
        def first_season(html, name, school=()):
            return {"firstSeason": None, "statements": [], "conflict": False}
    coach_bio = _Nothing()

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "coach_bio")
FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {ascii(detail)[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def fixture(slug: str) -> str:
    with open(os.path.join(FIXTURES, slug + ".html"), encoding="utf-8") as f:
        return f.read()


def page(*sentences: str, title: str = "Coach Page") -> str:
    return f"<html><head><title>{title}</title></head><body><main>" + "".join(f"<p>{html_lib.escape(s)}</p>" for s in sentences) + "</main></body></html>"


def first(html: str, name: str) -> dict:
    return coach_bio.first_season(html, name)


def kinds(r: dict) -> list[str]:
    return sorted(s["kind"] for s in r["statements"])


# slug -> (coach, first season or None, conflict, the statement kinds it rests on, what the page says)
REAL = {
    "iowa": ("Dean Ward", 2026, False, ["hired"], "named ... on Feb. 12, 2026: a February hire starts the same fall"),
    "purdue": ("Richard Moodie", 2024, False, ["hired"], "named ... on November 28, 2023: a November hire starts the next fall"),
    "duquesne": ("Jessica Giegucz", 2025, False, ["hired"], "named ... head coach Dec. 20, 2024, with no 'on'"),
    "san-jose-state": ("Sonia Curvelo", 2025, False, ["hired"], "named ... on March 26, 2025"),
    "drexel": ("Shannon Grogan", 2026, False, ["hired"], "named ... in December of 2025"),
    "ucla": ("Gof Boyoko", 2026, False, ["hired"], "announced on Dec. 12, 2025 as the seventh head coach (the sentence also says 'assistant coach')"),
    "arkansas": ("Colby Hale", 2012, False, ["hired"], "head soccer coach ... after being named to the position on Dec. 21, 2011"),
    "liberty": ("Lang Wedemeyer", 2017, False, ["hired", "present", "start"], "Start Date: 01/31/2017, '(2017-present)', became head coach on Jan. 31, 2017"),
    "fairleigh-dickinson": ("Eric Teepe", 2014, False, ["present"], "Head Coach, FDU - 2014-Present"),
    "uab": ("Lisa Mann", 2023, False, ["count", "first"], "enters her fourth season ... in the 2026 season; In 2023, Mann's first season"),
    "usc": ("Jane Alukonis", 2022, False, ["count", "hired"], "begins her fifth season ... entering the 2026 season; named ... on January 20, 2022"),
    "east-tennessee-state": ("Jay Yelton", 2020, False, ["count", "tookover"], "will begin his sixth season ... in 2025; took over ... in front of the 2020 season"),
    "long-beach-state": ("Mauricio Ingrassia", 2004, False, ["count"], "Fall 2025 will mark Ingrassia's 22nd year"),
    "oklahoma-state": ("Colin Carmichael", 2005, False, ["count", "interim"], "will mark Carmichael's 22nd year in 2026; co-head coach in 2005"),
    "northern-iowa": ("Alex Place Thomas", 2025, False, ["hired", "interim"], "interim head coach during the 2025 season, then named in November 2025"),
    "northern-arizona": ("Alan Berrios", 2022, False, ["hired", "interim"], "interim head coach midway through the 2022 season, named in December 2022"),
    "duke": ("Kieran Hall", 2025, False, ["count", "hired", "present"], "announced July 22, 2024 as head coach 'beginning in 2025'"),
    "california": ("Neil McGuire", 2007, False, ["count"], "completed his 19th season with the Bears in 2025"),
    "bowling-green": ("Chris Fox", 2024, False, ["count"], "third season ... in the fall of 2026, 'after guiding the Falcons to a record-setting 2025 season'"),
    "albany": ("Sade Ayinde", 2022, False, ["hired"], "On Wednesday, February 16, 2022, the University at Albany announced the hiring"),
    "alabama": ("Wes Hart", 2015, False, ["hired"], "after taking over the program in April of 2015"),
    "denver": ("Julianne Sitch", 2023, False, ["count"], "fourth season ... for the DU women's soccer team in 2026 ('for the DU' is not another school)"),
    "boston-college": ("Chris Watkins", 2024, False, ["hired", "hired"], "named at Boston College Dec. 14, 2023; named at Gonzaga December 2016"),
    "cal-poly": ("Bernardo Silva", 2025, False, ["hired", "tookover"], "named at Cal Poly Dec. 21, 2024; took over at Cal State Bakersfield before 2023"),
    "florida-state": ("Brian Pensky", None, False, ["hired"], "the only appointment on the page is at the University of Tennessee (2012)"),
    # the coach's name comes from the fixture: tests/rpi_attribution_test.py keeps that surname out of code
    "western-illinois": (None, None, False, ["hired", "interim"], "'Before coming to WIU:' ... named head coach at CSU in December 2021"),
    "radford": ("Ben Sohrabi", None, True, ["count", "since"], "'since 1996' and 'Through 2025 Season / 31st Season' (1995)"),
    "miami-fl": ("Ken Masuhr", None, True, ["count", "hired"], "'third season ... in 2026' (2024) against 'announced ... Dec. 5, 2024' (2025)"),
    "florida": ("Nick Zimmerman", None, True, ["hired", "present"], "'elevated to head coach in December of 2024' (2025) against '(December 5, 2025-present)' (2026)"),
    "cleveland-state": ("Mark Sappington", None, False, [], "'named ... in 2024' has no month; 'enters his third year' has no year"),
}
SCHOOLS = {  # athletics_site.school_names for each program, as the registry has it
    "alabama": ["University of Alabama", "Alabama", "Crimson Tide", "rolltide"],
    "albany": ["University at Albany", "Albany", "Great Danes", "ualbanysports"],
    "arkansas": ["University of Arkansas", "Arkansas", "Razorbacks", "arkansasrazorbacks"],
    "boston-college": ["Boston College", "Boston College", "Eagles", "bceagles"],
    "bowling-green": ["Bowling Green State University", "Bowling Green", "Falcons", "bgsufalcons"],
    "cal-poly": ["California Polytechnic State University, San Luis Obispo", "Cal Poly", "Mustangs", "gopoly"],
    "california": ["University of California, Berkeley", "California", "Golden Bears", "calbears"],
    "cleveland-state": ["Cleveland State University", "Cleveland State", "Vikings", "csuvikings"],
    "denver": ["University of Denver", "Denver", "Pioneers", "denverpioneers"],
    "drexel": ["Drexel University", "Drexel", "Dragons", "drexeldragons"],
    "duke": ["Duke University", "Duke", "Blue Devils", "goduke"],
    "duquesne": ["Duquesne University", "Duquesne", "Dukes", "goduquesne"],
    "east-tennessee-state": ["East Tennessee State University", "East Tennessee State", "Buccaneers", "etsubucs"],
    "fairleigh-dickinson": ["Fairleigh Dickinson University", "Fairleigh Dickinson", "Knights", "fduknights"],
    "florida-state": ["Florida State University", "Florida State", "Seminoles", "seminoles"],
    "florida": ["University of Florida", "Florida", "Gators", "floridagators"],
    "iowa": ["University of Iowa", "Iowa", "Hawkeyes", "hawkeyesports"],
    "liberty": ["Liberty University", "Liberty", "Lady Flames", "libertyflames"],
    "long-beach-state": ["California State University, Long Beach", "Long Beach State", "The Beach", "longbeachstate"],
    "miami-fl": ["University of Miami", "Miami (FL)", "Hurricanes", "miamihurricanes"],
    "northern-arizona": ["Northern Arizona University", "Northern Arizona", "Lumberjacks", "nauathletics"],
    "northern-iowa": ["University of Northern Iowa", "Northern Iowa", "Panthers", "unipanthers"],
    "oklahoma-state": ["Oklahoma State University", "Oklahoma State", "Cowgirls", "okstate"],
    "purdue": ["Purdue University", "Purdue", "Boilermakers", "purduesports"],
    "radford": ["Radford University", "Radford", "Highlanders", "radfordathletics"],
    "san-jose-state": ["San Jose State University", "San Jose State", "Spartans", "sjsuspartans"],
    "uab": ["University of Alabama at Birmingham", "UAB", "Blazers", "uabsports"],
    "ucla": ["University of California, Los Angeles", "UCLA", "Bruins", "uclabruins"],
    "usc": ["University of Southern California", "USC", "Trojans", "usctrojans"],
    "western-illinois": ["Western Illinois University", "Western Illinois", "Leathernecks", "goleathernecks"],
}


def test_real_pages() -> None:
    print("the trimmed real bio pages")
    for slug, (coach, year, conflict, want_kinds, why) in REAL.items():
        coach = coach or re.search(r"<h1>(.*?)</h1>", fixture(slug)).group(1)
        r = coach_bio.first_season(fixture(slug), coach, SCHOOLS[slug])
        # a page that yields no year and no conflict passes on origin/main too, which reads nothing: GUARD,
        # paired with the FIX check below that the statements were read and set aside
        label = "CONTROL" if year is None and not conflict and not want_kinds else "GUARD" if year is None and not conflict else "FIX"
        ok(f"{label} {slug}: {coach} -> {year}{' (conflict)' if conflict else ''}: {why}",
           r["firstSeason"] == year and r["conflict"] == conflict, f"{r['firstSeason']} conflict={r['conflict']}")
        if want_kinds:
            ok(f"FIX {slug}: read from {'+'.join(want_kinds)}, each with its sentence and no contact detail",
               sorted(s["kind"] for s in r["statements"]) == want_kinds
               and all(s["text"] and not re.search(r"@|\d{3}[-. ]\d{4}", s["text"]) for s in r["statements"]),
               str(sorted(s["kind"] for s in r["statements"])))


def test_phrasing_rules() -> None:
    print("the phrasing rules, one at a time")
    base = "Pat Lee was named head coach of the women's soccer program on {} 2, 2024."
    for month, want in (("January", 2024), ("March", 2024), ("April", 2024), ("July", 2024), ("November", 2025), ("December", 2025)):
        r = first(page(base.format(month)), "Pat Lee")
        ok(f"FIX a {month} hire -> first season {want}", r["firstSeason"] == want, str(r["firstSeason"]))
    for month in ("August", "September", "October"):
        r = first(page(base.format(month)), "Pat Lee")
        ok(f"FIX an {month} hire gives no year (the season is under way), but is recorded",
           r["firstSeason"] is None and [s["year"] for s in r["statements"]] == [None], str(r))
    r = first(page("Pat Lee was named associate head coach on January 5, 2020."), "Pat Lee")
    ok("CONTROL an associate head coach appointment is not read", r["statements"] == [], str(r))
    r = first(page("Chris Smith was named head coach of the women's soccer program on January 5, 2020."), "Pat Lee")
    ok("CONTROL a sentence that does not name the coach (a related story about someone else) is not read", r["statements"] == [])
    r = first(page("As the program enters its 31st season in 2026, the team looks ahead."), "Pat Lee")
    ok("CONTROL the program's own season count is not the coach's", r["statements"] == [])
    r = first(page("Pat Lee enters her third season as head coach in 2026."), "Pat Lee")
    ok("FIX 'enters her third season ... in 2026' -> 2024", r["firstSeason"] == 2024, str(r))
    r = first(page("Pat Lee begins her third season."), "Pat Lee")
    ok("CONTROL a count with no year in the sentence gives nothing", r["statements"] == [], str(r))
    r = first(page("In 2021, Lee's first season, the team won 12 games."), "Pat Lee")
    ok("FIX 'In 2021, Lee's first season' -> 2021", r["firstSeason"] == 2021, str(r))
    r = first(page("Lee, who has been at the helm since 2010, has 150 wins."), "Pat Lee")
    ok("FIX 'at the helm since 2010' -> 2010", r["firstSeason"] == 2010, str(r))
    r = first(page("Assistant Coach, Elsewhere - 2019-Present"), "Pat Lee")
    ok("CONTROL an assistant role's 'YYYY-Present' is not read", r["statements"] == [], str(r))
    r = first(page("Pat Lee was named head coach on January 5, 2020.", "Pat Lee begins her fourth season in 2026."), "Pat Lee")
    ok("FIX two statements that disagree (2020 and 2023): no year, conflict", r["firstSeason"] is None and r["conflict"], str(r))
    r = first(page("Pat Lee was named head coach on December 1, 2021 after serving as interim head coach during the 2021 season."), "Pat Lee")
    ok("FIX interim for 2021, then named in December 2021: the interim season is the first season",
       r["firstSeason"] == 2021 and not r["conflict"], str(r))
    r = first(page("Pat Lee served as interim head coach during the 2021 season.", "Pat Lee begins her sixth season in 2026."), "Pat Lee")
    ok("FIX an interim season and a season count that agree (both 2021) give that year",
       r["firstSeason"] == 2021 and not r["conflict"], str(r))
    r = first(page("Pat Lee served as interim head coach during the 2021 season.", "Pat Lee begins her third season in 2026."), "Pat Lee")
    ok("FIX an interim season contradicted by a count (2021 against 2024): no year, conflict",
       r["firstSeason"] is None and r["conflict"], str(r))
    r = first(page("Kathleen Bell-Smith Jr. was named head coach on May 3, 2019."), "Kathleen Bell-Smith Jr.")
    ok("FIX a hyphenated surname with a suffix is still the coach's name", r["firstSeason"] == 2019, str(r))
    r = first(page("Florida Head Coach (December 5, 2025-present)"), "Nick Zimmerman")
    ok("FIX a head-coach 'December 5, 2025-present' line is a hire date: a December hire starts the next fall (2026)",
       r["firstSeason"] == 2026, str(r))
    for sentence, want, label in (
            ("Pat Lee became the fifth head coach in program history in July of 2018.", 2018, "'became the ... head coach ... in July of 2018'"),
            ("Pat Lee was tabbed as the fifth head coach in program history when she was hired in December 2021.", 2022, "'tabbed as the ... head coach ... in December 2021'"),
            ("Pat Lee joined the staff as the Head Women's Soccer Coach in December of 2022.", 2023, "'joined ... as the Head Women's Soccer Coach in December of 2022'"),
            ("Pat Lee was announced as the fifth head coach on July 8th of 2022.", 2022, "an ordinal day, 'July 8th of 2022'"),
            ("On Wednesday, February 16, 2022, the university announced the hiring of Pat Lee as the next head coach.", 2022, "'On <date>, ... announced the hiring of X as the next head coach'"),
            ("Hired by the Director of Athletics on December 7, 2022 as the sixth head coach in program history, Lee has 60 wins.", 2023, "'Hired by ... on December 7, 2022 as the ... head coach'"),
            ("Lee was named to her position on April 10, 2008, becoming only the second head coach in program history.", 2008, "'named to her position on April 10, 2008' beside 'head coach'"),
            ("Head coach Pat Lee concluded her 11th season at the helm, after taking over the program in April of 2015.", 2015, "'taking over the program in April of 2015'"),
            ("Entering her seventh season in 2026, Pat Lee has continued to build.", 2020, "'Entering her seventh season in 2026, <Name>'"),
            ("Pat Lee will enter the 2026 campaign at the helm of the program for her 10th season.", 2017, "'will enter the 2026 campaign ... for her 10th season'"),
            ("Head coach Pat Lee completed her 19th season with the team in 2025.", 2007, "'completed her 19th season ... in 2025'"),
            ("Pat Lee begins her third season as head coach in the fall of 2026, after a record-setting 2025 season.", 2024, "'third season ... in the fall of 2026' (the 2025 after it is ignored)"),
            ("On July 22, 2024, the athletic director announced Lee will be the third head coach beginning in 2025.", 2025, "'announced ... beginning in 2025' overrides the July 2024 date"),
            ("The director announced Monday, Dec. 6, 2021, that Pat Lee has been named as the new head coach, effective January 1, 2022.", 2022, "'effective January 1, 2022'"),
            ("Pat Lee served as the interim head coach midway through the 2022 season.", 2022, "'interim head coach midway through the 2022 season'")):
        r = first(page(sentence), "Pat Lee")
        ok(f"FIX {label} -> {want}", r["firstSeason"] == want and not r["conflict"], str(r))
    r = first(page("Pat Lee enters her third season as head coach of the program, after guiding the team to new heights in 2025."), "Pat Lee")
    ok("CONTROL a count whose only year is a past season ('after ... in 2025') gives nothing", r["statements"] == [], str(r))
    r = first(page("In 2009, the university named Pat Lee as its head coach."), "Pat Lee")
    ok("CONTROL an appointment year with no month gives nothing", r["statements"] == [], str(r))


def test_previous_jobs() -> None:
    print("a bio narrates earlier jobs in the same words; only this school's counts")
    school = ["Florida State University", "Florida State", "Seminoles", "seminoles"]
    r = coach_bio.first_season(page("Pensky was named head soccer coach at the University of Tennessee on Jan. 26, 2012."),
                               "Brian Pensky", school)
    ok("FIX an appointment that names another university (and not this one) is read, marked another job, and gives no year",
       r["firstSeason"] is None and not r["conflict"] and [s["school"] for s in r["statements"]] == ["other"], str(r))
    school = ["Boston College", "Boston College", "Eagles", "bceagles"]
    r = coach_bio.first_season(page("Chris Watkins was named the new head women's soccer coach at Boston College on Dec. 14, 2023.",
                                    "Named the head coach of Gonzaga women's soccer in December 2016, Watkins built the program."),
                               "Chris Watkins", school)
    ok("FIX two appointments that disagree, one naming this school: the one naming this school (2024)",
       r["firstSeason"] == 2024 and not r["conflict"], str(r))
    school = ["University of Miami", "Miami (FL)", "Hurricanes", "miamihurricanes"]
    r = coach_bio.first_season(page("Ken Masuhr enters his third season as the Head Coach of the Miami Soccer program in 2026.",
                                    "Masuhr was announced as the sixth head coach in program history Tuesday, Dec. 5, 2024."),
                               "Ken Masuhr", school)
    ok("FIX a season count and an appointment that disagree are not resolved by preferring either: no year, conflict",
       r["firstSeason"] is None and r["conflict"], str(r))
    school = ["California Polytechnic State University", "Cal Poly", "Mustangs", "gopoly"]
    r = coach_bio.first_season(page("Bernardo Silva was named the second head coach in the history of the Cal Poly women's soccer program on January 8, 2025.",
                                    "Silva took over as head coach at Cal State Bakersfield prior to the 2023 season."),
                               "Bernardo Silva", school)
    ok("FIX 'Cal State Bakersfield' is not Cal Poly (no three-letter school token): 2025",
       r["firstSeason"] == 2025 and not r["conflict"], str(r))
    r = coach_bio.first_season(page("Lewis Robinson was named head women's soccer coach on June 30, 2022."), "Lewis Robinson",
                               ["Western Michigan University", "Western Michigan", "Broncos", "wmubroncos"])
    ok("FIX an appointment that names no school at all still counts", r["firstSeason"] == 2022, str(r))
    uf = ["University of Florida", "Florida", "Gators", "floridagators"]
    r = coach_bio.first_season(page("Pat Lee was named head coach at Florida State on January 5, 2012."), "Pat Lee", uf)
    ok("FIX 'Florida State' is not the University of Florida, though both say Florida: no year",
       r["firstSeason"] is None and [s["school"] for s in r["statements"]] == ["other"], str(r))
    r = coach_bio.first_season(page("Pat Lee was named head coach at the University of Florida on January 5, 2012."), "Pat Lee", uf)
    ok("FIX ... while the University of Florida is", r["firstSeason"] == 2012, str(r))
    r = coach_bio.first_season(page("Indiana University Director of Athletics Scott Dolson announced the hiring of Pat Lee as the head coach on February 11, 2025."),
                               "Pat Lee", ["Indiana University Bloomington", "Indiana", "Hoosiers", "iuhoosiers"])
    ok("FIX 'Indiana University' is Indiana (its name without the generic words is the short name): 2025", r["firstSeason"] == 2025, str(r))
    r = coach_bio.first_season(page("A former assistant at Northeastern University and Boston College, Lee was named Brown's head coach on December 30, 2015."),
                               "Pat Lee", ["Brown University", "Brown", "Bears", "brownbears"])
    ok("FIX a sentence naming other schools and this one ('Brown's') is this school's: 2016", r["firstSeason"] == 2016, str(r))
    r = coach_bio.first_season(page("Pat Lee was named the sixth head coach at CSU in December 2021."), "Pat Lee",
                               ["Western Illinois University", "Western Illinois", "Leathernecks", "goleathernecks"])
    ok("FIX 'at CSU', an acronym that is not this school's, is read as another job: no year",
       r["firstSeason"] is None and [s["school"] for s in r["statements"]] == ["other"], str(r))
    r = coach_bio.first_season(page("Pat Lee enters her fourth season as head coach for the DU women's soccer team in 2026."), "Pat Lee",
                               ["University of Denver", "Denver", "Pioneers", "denverpioneers"])
    ok("FIX 'for the DU women's soccer team' is not read as another school: 2023", r["firstSeason"] == 2023, str(r))
    r = coach_bio.first_season("<html><body><main><p>Before coming to Western:</p><p>Pat Lee was named head coach on January 5, 2015.</p>"
                               "<p>Career Highlights:</p><p>Pat Lee was named head coach on June 1, 2020.</p></main></body></html>",
                               "Pat Lee", ["Western Illinois University", "Western Illinois", "Leathernecks", "goleathernecks"])
    ok("FIX a 'Before coming to ...:' section is an earlier job, and the next heading ends it: 2020, not 2015",
       r["firstSeason"] == 2020 and not r["conflict"], str(r))


def test_collector_stores_it() -> None:
    print("athletics_site.collect stores the head coach's bio reading")
    base = "https://example.invalid"
    sport = "/sports/womens-soccer"
    roster = open(os.path.join(ROOT, "tests", "fixtures", "sidearm", "roster-players-and-staff.html"), encoding="utf-8").read()
    bio_url = base + "/sports/womens-soccer/roster/coaches/tracy--chao/2425"
    bio = fixture("iowa").replace("Dean Ward", "Tracy Chao").replace("Ward", "Chao").replace("the University of Iowa", "Army West Point")
    pages = {base + sport + "/roster": roster, base + sport + "/schedule": "<html></html>", bio_url: bio}
    saved, requests = {}, []

    def fetch_text(url, **kw):
        requests.append((url, kw.get("max_age_hours")))
        if url not in pages:
            raise common.FetchError(f"HTTP 404 for {url}")
        return pages[url], {"url": url, "status": 200, "finalUrl": url, "fromCache": False}

    def save_source(slug, name, data, *, url, collector, extra=None):
        saved.update(copy.deepcopy(data))

    registry = {"season": {"current": 2026}, "sources": {"athleticsPlatforms": {"sidearm": {
        "roster": "{baseUrl}{sportPath}/roster", "rosterSeason": "{baseUrl}{sportPath}/roster/{year}",
        "schedule": "{baseUrl}{sportPath}/schedule", "scheduleSeason": "{baseUrl}{sportPath}/schedule/{year}",
        "news": "{baseUrl}{sportPath}/archives", "rss": "{baseUrl}/rss?path=wsoc"}}}}
    program = {"slug": "fixture", "name": "United States Military Academy", "shortName": "Army", "nickname": "Black Knights",
               "athletics": {"platform": "sidearm", "baseUrl": base, "sportPath": sport}}
    real = (common.fetch_text, common.save_source, common.log)
    common.fetch_text, common.save_source, common.log = fetch_text, save_source, (lambda m: None)
    try:
        athletics_site.collect(program, registry, seasons_back=0, bios=True)
        players_only = [u for u, _ in requests if "/roster/" in u and "/coaches/" not in u]
        hb = saved.get("headCoachBio") or {}
        ok("FIX the stored source carries headCoachBio for the head coach", hb.get("name") == "Tracy Chao" and hb.get("url") == bio_url, str(hb)[:200])
        ok("FIX ... with the first season read from the page (a February 2026 hire -> 2026)", hb.get("firstSeason") == 2026, str(hb.get("firstSeason")))
        ok("FIX ... and the sentence it came from", any("Feb. 12, 2026" in s.get("text", "") for s in hb.get("statements") or []), str(hb)[:300])
        ok("FIX ... judged against this program's own names (the sentence says 'Army West Point': own)",
           [s.get("school") for s in hb.get("statements") or []] == ["own"], str(hb.get("statements"))[:300])
        ok("FIX the bio page is requested once, cached a week like the player bios",
           [a for u, a in requests if u == bio_url] == [24 * 7], str(requests))
        requests.clear()
        saved.clear()
        athletics_site.collect(program, registry, seasons_back=0, bios=False)
        ok("CONTROL with bios=False no bio page is requested, the coach's included",
           not any("/coaches/" in u for u, _ in requests) and saved.get("headCoachBio") is None, str(requests))
        del pages[bio_url]
        saved.clear()
        athletics_site.collect(program, registry, seasons_back=0, bios=True)
        hb = saved.get("headCoachBio") or {}
        ok("FIX a bio page that cannot be fetched is stored as an attempt with no year, and collection goes on",
           hb.get("firstSeason") is None and "error" in hb and bool(saved.get("roster")), str(hb)[:200])
    finally:
        common.fetch_text, common.save_source, common.log = real


def test_no_contact_details() -> None:
    print("privacy: tests/fixtures/coach_bio/")
    names = sorted(f for f in os.listdir(FIXTURES) if f.endswith(".html"))
    ok("thirty fixtures", len(names) == 30, str(len(names)))
    for n in names:
        raw = open(os.path.join(FIXTURES, n), encoding="utf-8").read()
        decoded = unicodedata.normalize("NFKC", unquote(html_lib.unescape(raw)))
        flat = re.sub(r"<[^>]+>", " ", decoded)
        emails = re.findall(r"[A-Za-z0-9._%+-]+\s*(?:@|\(at\)|\[at\])\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}", decoded, re.I)
        phones = re.findall(r"(?<![\d/_.-])(?:\(?\d{3}\)?[-. ]?)?\d{3}[-. ]\d{4}(?![\d/_.-])", flat)
        ok(f"{n}: no email address", not emails, str(emails))
        ok(f"{n}: no telephone number, seven or ten digits", not phones, str(phones))
        ok(f"{n}: no mailto:, tel: or sms: link", not re.search(r"(?:mailto|tel|sms):", decoded, re.I))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    if CODE_ROOT != ROOT:
        print(f"code under test imported from {CODE_ROOT}")
    for case in (test_real_pages, test_phrasing_rules, test_previous_jobs, test_collector_stores_it, test_no_contact_details):
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
