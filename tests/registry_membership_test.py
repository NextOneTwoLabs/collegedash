"""Regression tests for the registry's NCAA Directory master list and membership policy (issue #100).

    python tests/registry_membership_test.py            # everything below, offline
    python tests/registry_membership_test.py --verbose  # print every check, not only the failures

Offline: no request, nothing written outside a temporary directory. Synthetic Directory rows and
Scorecard rows exercise collect/registry_builder.py's pure functions; the committed registry is then
checked against what the builder must have produced. Exit 0 when every check passes, 1 otherwise.

Every check names, in a comment, the input that makes it fail.

Covers, in order:
  parsing     a Directory row without an integer orgId, or listed under another division, raises
  domains     normalisation, and the Scorecard join by website domain: same state required
              (ewu.edu is Eastern Washington and Edward Waters), ambiguous rows never tie-broken
  identity    keyed / agreed / reviewed / unresolved, and the reviewed pin that loses to a state
  policy      reclassify -> held, return unchanged when the division is onboarded, not listed ->
              held only when reviewed, unresolved stays put, a new program only in an onboarded
              division, duplicate claims, the departure guard, hold evidence belongs to its program
  new entry   every field from a source or null: Wikipedia needs the state, TDS the conference,
              the timezone comes from the coordinates, a slug collision takes the state suffix
  committed   public/data/registry.json: every pre-#100 slug survives with the same ids, the three
              programs #100 names are where the policy puts them, held programs are invisible to
              iter_programs, and the reviewed pins are the ids the registry carries
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import common  # noqa: E402
from collect import registry_builder as rb  # noqa: E402

PRE_100 = os.path.join(ROOT, "tests", "fixtures", "registry", "pre-100-programs.json")
FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def raises(name: str, exc, fn, *a, **kw) -> None:
    try:
        fn(*a, **kw)
    except exc as e:
        ok(name, True, str(e))
        return
    except Exception as e:  # noqa: BLE001
        ok(name, False, f"raised {type(e).__name__}: {e}")
        return
    ok(name, False, "did not raise")


# ---------- synthetic world ----------

def drow(org, division, name, state, web, ath, conf):
    return {"orgId": org, "division": division, "name": name, "conference": conf, "website": web,
            "athleticsUrl": ath, "state": state, "academicYear": 2027}


def sc(uid, name, city, state, url, lat=1.0, lon=2.0):
    return {"id": uid, "school.name": name, "school.city": city, "school.state": state, "school.school_url": url,
            "location.lat": lat, "location.lon": lon}


BULK = [
    sc(1, "Alpha University", "Alphaville", "TX", "www.alpha.edu/"),
    sc(2, "Beta College", "Betatown", "PA", "beta.edu"),
    sc(3, "Gamma State University", "Gamma", "OH", "gamma.edu"),
    sc(4, "Eastern Washington University", "Cheney", "WA", "www.ewu.edu/"),
    sc(5, "Edward Waters University", "Jacksonville", "FL", "ewu.edu"),
    sc(6, "Delta University-Main", "Delta", "NJ", "delta.edu"),
    sc(7, "Delta University-Branch", "Delta East", "NJ", "delta.edu"),
    sc(8, "Epsilon University", "Pensacola", "FL", "www.epsilon.edu"),
    sc(9, "Zeta University-Twin", "Zeta", "MN", "twin.zeta.edu"),
    sc(10, "Old Program University", "Oldtown", "MS", "old.edu"),
]


def prog(slug, uid, ath, state, *, division="D1", conference="Old Conf", org=None, **extra):
    p = {"slug": slug, "onboarded": True, "name": slug.title(), "shortName": slug.title(), "nickname": "Nicks",
         "division": division, "conference": conference, "colors": ["#000000", "#FFFFFF"],
         "athletics": {"platform": "sidearm", "baseUrl": ath, "sportPath": "/sports/womens-soccer"},
         "ids": {"scorecardUnitId": uid, "tdsClgId": uid * 10, "tdsSlug": slug, "wikipedia": None, "ncaaName": slug,
                 "rpiHistoryName": slug},
         "social": {"x": None, "instagram": None},
         "location": {"city": "X", "state": state, "lat": 1.0, "lon": 2.0, "timezone": "America/Chicago"},
         "onboardedAt": "2026-09-06"}
    if org is not None:
        p["ids"]["ncaaOrgId"] = org
    p.update(extra)
    return p


def world():
    directory = {
        "D1": [drow(101, "D1", "Alpha University", "TX", "www.alpha.edu", "www.goalpha.com", "Big 12 Conference"),
               drow(104, "D1", "Eastern Washington University", "WA", "ewu.edu", "goeags.com", "Big Sky Conference"),
               drow(108, "D1", "Epsilon University", "FL", "epsilon.edu", "www.goepsilon.com", "Atlantic Sun Conference")],
        "D2": [drow(105, "D2", "Edward Waters University", "FL", "ewu.edu", "ewutigers.com", "Independent")],
        "D3": [drow(102, "D3", "Beta College", "PA", "beta.edu", "gobeta.com", "Presidents' Athletic Conference")],
    }
    registry = {"onboardedDivisions": ["D1"], "programs": [
        prog("alpha", 1, "https://goalpha.com", "TX"),
        prog("beta", 2, "https://gobeta.com", "PA"),
        prog("ewu", 4, "https://goeags.com", "WA"),
        prog("old", 10, "https://oldathletics.com", "MS"),
    ], "heldPrograms": []}
    return registry, directory


def with_pins(pins=None, unlisted=None):
    """Context-free swap of the builder's reviewed tables for one call."""
    class _Swap:
        def __enter__(self):
            self.saved = (rb.REVIEWED_ORG_IDS, rb.REVIEWED_NOT_LISTED)
            rb.REVIEWED_ORG_IDS = pins or {}
            rb.REVIEWED_NOT_LISTED = unlisted or {}

        def __exit__(self, *a):
            rb.REVIEWED_ORG_IDS, rb.REVIEWED_NOT_LISTED = self.saved
    return _Swap()


# ---------- parsing ----------

def test_parsing() -> None:
    print("parsing: the Directory rows")
    raw = [{"orgId": 11740, "nameOfficial": "University of West Florida ", "conferenceName": "Atlantic Sun Conference ",
            "webSiteUrl": "www.uwf.edu", "athleticWebUrl": "www.goargos.com", "memberOrgAddress": {"state": "FL"},
            "academicYear": 2027, "divisionRoman": "I"}]
    rows = rb.parse_directory(raw, "D1")
    # fails if names or conferences keep the Directory's trailing spaces (the label table would miss them)
    ok("trailing whitespace is trimmed from name and conference",
       rows[0]["name"] == "University of West Florida" and rows[0]["conference"] == "Atlantic Sun Conference", str(rows[0]))
    # fails if a row without an integer orgId is accepted: it could not be keyed
    raises("a row without an integer orgId raises", common.FetchError, rb.parse_directory, [{**raw[0], "orgId": "11740"}], "D1")
    # fails if a D3 row served under the D1 request is silently filed as D1
    raises("a row listed under another division raises", common.FetchError, rb.parse_directory, [{**raw[0], "divisionRoman": "III"}], "D1")
    raises("a non-list payload raises", common.FetchError, rb.parse_directory, {"error": "x"}, "D1")
    # fails if a Directory name missing from the label table is dropped instead of shown as spelled
    ok("an unknown conference keeps the Directory's own name", rb.conference_label("Presidents' Athletic Conference")
       == "Presidents' Athletic Conference")
    ok("a known conference gets its registry label", rb.conference_label("Metro Conference") == "Metro"
       and rb.conference_label("Atlantic Coast Conference") == "ACC")


# ---------- domains ----------

def test_domains() -> None:
    print("domains: normalisation and the Scorecard join")
    # fails if the trailing dot on 'saintpeters.edu.' (as the Directory serves it) survives
    ok("scheme, www, path and a trailing dot are stripped",
       rb.site_domain("https://www.GoArgos.com/sports/") == "goargos.com" and rb.site_domain("saintpeters.edu.") == "saintpeters.edu"
       and rb.site_domain("www2.x.edu") == "x.edu" and rb.site_domain("") is None and rb.site_domain(None) is None)
    ok("registrable domain is the last two labels", rb.registrable("bloomington.iu.edu") == "iu.edu" and rb.registrable("x") is None)
    row, how = rb.scorecard_by_domain("ewu.edu", "WA", BULK)
    # fails if state is dropped from the join: ewu.edu then matches two schools in two states
    ok("ewu.edu in WA is Eastern Washington, not Edward Waters", row and row["id"] == 4 and how == "exact", f"{row} {how}")
    row, how = rb.scorecard_by_domain("ewu.edu", "FL", BULK)
    ok("ewu.edu in FL is Edward Waters", row and row["id"] == 5, f"{row} {how}")
    row, how = rb.scorecard_by_domain("delta.edu", "NJ", BULK)
    # fails if two same-state rows are tie-broken (by size, name or order) instead of refused
    ok("two Scorecard rows on one domain in one state are refused", row is None and how.startswith("ambiguous"), f"{row} {how}")
    row, how = rb.scorecard_by_domain("zeta.edu", "MN", BULK)
    ok("a unique registrable-domain row is accepted and says so", row and row["id"] == 9 and how == "registrable", f"{row} {how}")
    row, how = rb.scorecard_by_domain("ewu.edu", None, BULK)
    # fails if a join runs without a state
    ok("no state, no join", row is None and how == "no-state", how)
    ok("no website, no join", rb.scorecard_by_domain(None, "TX", BULK) == (None, "no-website"))


# ---------- identity ----------

def test_identity() -> None:
    print("identity: keyed, agreed, reviewed, unresolved")
    _, directory = world()
    rows = {r["orgId"]: r for rs in directory.values() for r in rs}
    by_id = {r["id"]: r for r in BULK}
    with with_pins():
        org, status, _ = rb.resolve_identity(prog("alpha", 1, "https://goalpha.com", "TX"), rows, by_id)
        ok("website, athletics and state agreeing give the orgId", (org, status) == (101, "agreed"), f"{org} {status}")
        org, status, why = rb.resolve_identity(prog("alpha", 1, "https://alpha-sports.com", "TX"), rows, by_id)
        # fails if one agreeing domain is enough without review
        ok("one domain agreeing and one differing is unresolved without a review", (org, status) == (None, "unresolved"), why)
        org, status, _ = rb.resolve_identity(prog("alpha", 1, "https://goalpha.com", "OK"), rows, by_id)
        # fails if state is not part of the agreement
        ok("both domains agreeing in the wrong state is unresolved", status == "unresolved", status)
        org, status, _ = rb.resolve_identity(prog("x", 1, "https://whatever.com", "TX", org=104), rows, by_id)
        # fails if a keyed program is re-matched by its domains
        ok("an ids.ncaaOrgId wins over the domains", (org, status) == (104, "keyed"), f"{org} {status}")
        org, status, _ = rb.resolve_identity(prog("x", 1, "https://whatever.com", "TX", org=999), rows, by_id)
        ok("an ids.ncaaOrgId in no list is keyed-unlisted", (org, status) == (999, "keyed-unlisted"), f"{org} {status}")
        org, status, _ = rb.resolve_identity(prog("old", 10, "https://oldathletics.com", "MS"), rows, by_id)
        # fails if "no candidate" alone removes a program: a stale URL would look exactly like this
        ok("no candidate and no review is unresolved, not unlisted", status == "unresolved", status)
    with with_pins(pins={"alpha": (101, "reviewed"), "wrong": (104, "reviewed")}, unlisted={"old": "reviewed"}):
        org, status, _ = rb.resolve_identity(prog("alpha", 1, "https://alpha-sports.com", "TX"), rows, by_id)
        ok("a reviewed pin resolves the disagreement", (org, status) == (101, "reviewed"), f"{org} {status}")
        org, status, why = rb.resolve_identity(prog("wrong", 1, "https://alpha-sports.com", "TX"), rows, by_id)
        # fails if a pin is trusted when the Directory puts that orgId in another state
        ok("a pin whose row is in another state is unresolved", status == "unresolved", why)
        org, status, _ = rb.resolve_identity(prog("old", 10, "https://oldathletics.com", "MS"), rows, by_id)
        ok("a reviewed not-listed program is reviewed-unlisted", status == "reviewed-unlisted", status)
        org, status, why = rb.resolve_identity(prog("old", 1, "https://goalpha.com", "TX"), rows, by_id)
        # fails if a "not listed" review outlives a row that now matches
        ok("a not-listed review is void once a row matches", status in ("agreed", "unresolved") and status != "reviewed-unlisted", why)


# ---------- policy ----------

def run(registry, directory, **kw):
    kw.setdefault("today", "2026-09-15")
    return rb.apply_membership(registry, directory, BULK, **kw)


def test_policy() -> None:
    print("policy: reclassify, hold, return, remove, add")
    with with_pins(unlisted={"old": "no row anywhere"}):
        registry, directory = world()
        before = copy.deepcopy(registry)
        rep = run(registry, directory, max_departure_share=1.0)
        pub = {p["slug"]: p for p in registry["programs"]}
        held = {p["slug"]: p for p in registry["heldPrograms"]}
        # fails if a reclassified program keeps last season's label or stays published
        ok("beta, now D3 with D3 not onboarded, is held", "beta" in held and "beta" not in pub, f"{sorted(pub)} {sorted(held)}")
        ok("beta's division moved to D3", held["beta"]["division"] == "D3", held["beta"]["division"])
        ok("beta's hold says why", held["beta"]["hold"] == {"reason": "division-not-onboarded", "division": "D3", "orgId": 102,
                                                           "since": "2026-09-15"}, str(held["beta"].get("hold")))
        # fails if a program in no list stays published
        ok("old, reviewed as in no list, is held", "old" in held and held["old"]["hold"]["reason"] == "not-in-directory")
        # fails if hold evidence is carried over from whichever program was resolved last (a bug caught
        # in the first scratch run, where Mississippi Valley State's hold quoted Arkansas-Pine Bluff)
        ok("old's hold evidence is its own review, not another program's", held["old"]["hold"].get("evidence") == "no row anywhere",
           str(held["old"]["hold"]))
        ok("alpha and ewu stay published", {"alpha", "ewu"} <= set(pub))
        # fails if a staying entry is rebuilt instead of kept: only division, conference and ncaaOrgId may change
        for slug in ("alpha", "ewu"):
            a = copy.deepcopy(next(p for p in before["programs"] if p["slug"] == slug))
            b = copy.deepcopy(pub[slug])
            b["ids"].pop("ncaaOrgId")
            a.pop("conference"); b.pop("conference")
            ok(f"{slug} is kept field for field", a == b, f"{a} != {b}")
        ok("alpha's conference is the Directory's, labelled", pub["alpha"]["conference"] == "Big 12", pub["alpha"]["conference"])
        # fails if a D2 row is added while D2 is not onboarded
        ok("Edward Waters (D2) is not added while D2 is off", not any(p["ids"].get("ncaaOrgId") == 105 for p in registry["programs"]))
        # fails if a D1 row with no built entry is added anyway, or silently dropped from the report
        ok("Epsilon (D1) with no built entry is reported, not added",
           [n["orgId"] for n in rep["notAdded"]] == [108] and 108 not in {p["ids"].get("ncaaOrgId") for p in registry["programs"]},
           str(rep["notAdded"]))
        ok("the report counts identities", rep["identity"] == {"agreed": 3, "reviewed-unlisted": 1}, str(rep["identity"]))

        # --- a second build: nothing moves, and the hold keeps its date
        again = copy.deepcopy(registry)
        rep2 = run(again, directory, today="2027-01-01")
        ok("a second build is keyed and changes nothing",
           rep2["identity"].get("keyed") == 3 and not rep2["held"] and not rep2["reclassified"] and not rep2["conferenceChanged"],
           str(rep2))
        ok("a hold keeps the date it started", next(p for p in again["heldPrograms"] if p["slug"] == "beta")["hold"]["since"] == "2026-09-15")

        # --- turning D3 on is one edit, and beta comes back exactly as it left
        on = copy.deepcopy(registry)
        on["onboardedDivisions"] = ["D1", "D3"]
        rep3 = run(on, directory)
        back = next((p for p in on["programs"] if p["slug"] == "beta"), None)
        left = copy.deepcopy(next(p for p in registry["heldPrograms"] if p["slug"] == "beta"))
        left.pop("hold")
        # fails if a returning program gets a new slug, loses fields, or keeps its hold block
        ok("with D3 onboarded, beta returns to programs", back is not None and rep3["returned"] == [{"slug": "beta", "division": "D3"}],
           str(rep3["returned"]))
        ok("and returns unchanged, slug included, hold removed", back == left, f"{back} != {left}")
        ok("old stays held: it is in no list", any(p["slug"] == "old" for p in on["heldPrograms"]))

    # --- a new program is added only with a built entry, in an onboarded division
    with with_pins():
        registry, directory = world()
        registry["programs"] = [p for p in registry["programs"] if p["slug"] in ("alpha", "ewu")]
        entry = {"slug": "epsilon", "ids": {"ncaaOrgId": 108}, "division": "D1"}
        rep = run(registry, directory, new_entries={108: entry})
        ok("a D1 row with a built entry is added", any(p["slug"] == "epsilon" for p in registry["programs"]) and
           rep["added"] == [{"slug": "epsilon", "orgId": 108, "name": "Epsilon University", "division": "D1"}], str(rep["added"]))
        registry, directory = world()
        registry["programs"] = [p for p in registry["programs"] if p["slug"] in ("alpha", "ewu")]
        # fails if a new program may take a slug already in the registry
        raises("a new entry with a taken slug raises", ValueError, run, registry, directory,
               new_entries={108: {"slug": "alpha", "ids": {"ncaaOrgId": 108}}})
        registry, directory = world()
        registry["programs"] = [p for p in registry["programs"] if p["slug"] in ("alpha", "ewu")]
        registry["onboardedDivisions"] = ["D1", "D2"]
        rep = run(registry, directory, new_entries={105: {"slug": "edward-waters", "ids": {"ncaaOrgId": 105}}})
        # fails if onboarding D2 needs more than the list entry
        ok("with D2 in onboardedDivisions the D2 row is added", [a["orgId"] for a in rep["added"]] == [105], str(rep["added"]))

    # --- unresolved stays put, and blocks additions
    with with_pins():
        registry, directory = world()
        registry["programs"] = [p for p in registry["programs"] if p["slug"] in ("alpha", "old")]
        rep = run(registry, directory, new_entries={108: {"slug": "epsilon", "ids": {"ncaaOrgId": 108}}, 104: {"slug": "e", "ids": {}}})
        # fails if an unreviewed program with no candidate is removed
        ok("an unresolved program stays published, untouched", any(p["slug"] == "old" and "hold" not in p and "ncaaOrgId" not in p["ids"]
                                                                 for p in registry["programs"]), str(rep["unresolved"]))
        # fails if new rows are added while an entry might be one of them
        ok("an unresolved identity blocks every addition", not rep["added"] and len(rep["notAdded"]) == 2, str(rep["notAdded"]))

    # --- duplicate claims
    with with_pins():
        registry, directory = world()
        registry["programs"] = [prog("alpha", 1, "https://goalpha.com", "TX"), prog("alpha-2", 1, "https://goalpha.com", "TX")]
        rep = run(registry, directory)
        # fails if two entries may both take one orgId (one school's data on two cards)
        ok("two entries claiming one orgId are both unresolved", rep["duplicateOrgId"] == [{"orgId": 101, "slugs": ["alpha", "alpha-2"]}]
           and all("ncaaOrgId" not in p["ids"] for p in registry["programs"]) and rep["identity"] == {"unresolved": 2}, str(rep))

    # --- the departure guard
    with with_pins():
        registry, directory = world()
        registry["programs"] = [prog("alpha", 1, "https://goalpha.com", "TX", org=101), prog("ewu", 4, "https://goeags.com", "WA", org=104)]
        control = copy.deepcopy(registry)
        run(control, directory)
        # the control: the same keyed registry against the full lists holds nothing, so the raise below is the empty list's
        ok("control: the full lists hold nothing", len(control["programs"]) == 2 and not control["heldPrograms"], str(control))
        before = copy.deepcopy(registry)
        empty = {**directory, "D1": []}
        # fails if a failed or truncated D1 response can move every keyed program to heldPrograms
        raises("an empty D1 list raises instead of holding every keyed program", RuntimeError, run, registry, empty)
        # fails if apply_membership edits entries in place before deciding to raise
        ok("and leaves the registry as it was", registry == before)
        ok("a departure inside the limit is allowed", run(copy.deepcopy(registry), empty, max_departure_share=1.0)["slugs"] == {"published": 0, "held": 2})
        raises("onboardedDivisions missing raises", ValueError, run, {"programs": []}, directory)
        raises("an unknown division in onboardedDivisions raises", ValueError, run, {"onboardedDivisions": ["DII"], "programs": []}, directory)
        raises("one orgId in two lists raises", ValueError, run, registry, {**directory, "D3": directory["D3"] + [directory["D1"][0]]})


# ---------- new entries ----------

def test_new_entry() -> None:
    print("new entry: every field from a source or null")
    row = drow(108, "D1", "Epsilon University", "FL", "epsilon.edu", "www.goepsilon.com/landing/index", "Atlantic Sun Conference")
    wiki = [{"institution": "Epsilon", "institutionArticle": "Epsilon_University", "city": "Pensacola", "state": "Florida",
             "nickname": "Argos", "athleticsArticle": "Epsilon_Argos"}]
    tds = {"epsilon": {"tdsSlug": "epsilon", "tdsClgId": 742, "tdsName": "Epsilon", "tdsConf": "asun"}}
    looked, asked = [], []
    entry, ev = rb.new_program_entry(row, bulk=BULK, wiki=wiki, tds=tds, taken={"alpha"},
                                     article_lookup=lambda a: looked.append(a) or None,
                                     timezone_lookup=lambda lat, lon: asked.append((lat, lon)) or "Zone/FromCoordinates")
    ok("Scorecard by domain gives unit id, city and coordinates", entry["ids"]["scorecardUnitId"] == 8
       and entry["location"]["city"] == "Pensacola" and entry["location"]["lat"] == 1.0, str(entry))
    ok("Wikipedia row with name and state gives short name and nickname", entry["shortName"] == "Epsilon" and entry["nickname"] == "Argos")
    ok("TDS with name and conference gives the team ids", (entry["ids"]["tdsSlug"], entry["ids"]["tdsClgId"]) == ("epsilon", 742))
    # fails if the athletics URL keeps a path (the Directory's /landing/index) or invents a scheme+www it did not give
    ok("the athletics base URL is the Directory host", entry["athletics"]["baseUrl"] == "https://www.goepsilon.com", entry["athletics"]["baseUrl"])
    # fails if the timezone comes from anywhere but the Scorecard coordinates (a state table, a default)
    ok("the timezone is looked up from the Scorecard row's coordinates", asked == [(1.0, 2.0)]
       and entry["location"]["timezone"] == "Zone/FromCoordinates", f"{asked} {entry['location']['timezone']}")
    ok("the state table is gone", not hasattr(rb, "STATE_TZ") and not hasattr(rb, "timezone_for"))
    ok("colours, NCAA name and RPI-archive name are null, and reported", entry["colors"] is None and entry["ids"]["ncaaName"] is None
       and entry["ids"]["rpiHistoryName"] is None and {"colors", "ids.ncaaName", "ids.rpiHistoryName"} <= set(ev["null"]), str(ev))
    ok("not onboarded until its collectors run", entry["onboarded"] is False and entry["slug"] == "epsilon" and entry["division"] == "D1")

    wrong_state = [{**wiki[0], "state": "Texas"}]
    entry, ev = rb.new_program_entry(row, bulk=BULK, wiki=wrong_state, tds={}, taken=set(), article_lookup=lambda a: "X",
                                     timezone_lookup=lambda lat, lon: None)
    # fails if a same-named Wikipedia row in another state fills the fields
    ok("a Wikipedia name match in another state fills nothing", entry["shortName"] is None and entry["nickname"] is None
       and entry["ids"]["wikipedia"] is None and ev["wikipediaList"].startswith("name matches, state disagrees"), str(ev))
    entry, ev = rb.new_program_entry(row, bulk=BULK, wiki=wiki, tds={"epsilon": {**tds["epsilon"], "tdsConf": "big-sky"}},
                                     taken=set(), article_lookup=lambda a: None, timezone_lookup=lambda lat, lon: None)
    # fails if a same-named TDS team in another conference is accepted (Trinity CT / Trinity DC)
    ok("a TDS name match in another conference fills nothing", entry["ids"]["tdsClgId"] is None and ev["tds"].startswith("name matches"), str(ev))
    entry, ev = rb.new_program_entry({**row, "website": "delta.edu", "state": "NJ"}, bulk=BULK, wiki=[], tds={}, taken=set(),
                                     timezone_lookup=lambda lat, lon: "Zone/Should/Not/Be/Asked")
    # fails if an ambiguous Scorecard domain is tie-broken
    ok("an ambiguous Scorecard domain leaves unit id and coordinates null", entry["ids"]["scorecardUnitId"] is None
       and entry["location"]["lat"] is None and ev["scorecard"].startswith("ambiguous"), str(ev))
    # fails if a timezone is supplied for a program whose coordinates no source established
    ok("and with no coordinates there is no timezone", entry["location"]["timezone"] is None
       and "location.timezone" in ev["null"], str(entry["location"]))
    entry, ev = rb.new_program_entry({**row, "athleticsUrl": None}, bulk=BULK, wiki=[], tds={}, taken=set(),
                                     timezone_lookup=lambda lat, lon: None)
    # fails if a missing athletics URL is filled from anywhere but the Directory
    ok("no Directory athletics URL means baseUrl null", entry["athletics"]["baseUrl"] is None and "athletics.baseUrl" in ev["null"])
    ok("with no Wikipedia row the slug comes from the official name", entry["slug"] == "epsilon-university", entry["slug"])
    # fails if a new program can take a slug that is already published or held
    ok("a slug collision takes the state, then the orgId", rb.new_slug("Wheaton College", "MA", 9, {"wheaton-college"}) == "wheaton-college-ma"
       and rb.new_slug("Wheaton College", "MA", 9, {"wheaton-college", "wheaton-college-ma"}) == "wheaton-college-9")


# ---------- time zones ----------

def test_timezones() -> None:
    print("timezones: boundaries, not states")
    # Real lookups through timezonefinder. Each pair is two campuses in ONE state on different clocks,
    # so any state-based rule gets at least one of them wrong. An ImportError here is a failure, not a
    # skip: CI installs requirements-registry.txt (tests.yml), and a missing library must not look like a null timezone.
    try:
        cases = (("Pensacola, FL (West Florida)", 30.549076, -87.218511, "America/Chicago"),
                 ("Tallahassee, FL (Florida State)", 30.443147, -84.295064, "America/New_York"),
                 ("Knoxville, TN (Tennessee)", 35.9544, -83.9295, "America/New_York"),
                 ("Memphis, TN", 35.1187, -89.9375, "America/Chicago"),
                 ("El Paso, TX (UTEP)", 31.7719, -106.5047, "America/Denver"),
                 ("Moscow, ID (Idaho)", 46.7271, -117.0152, "America/Los_Angeles"),
                 ("Boise, ID (Boise State)", 43.6027, -116.2014, "America/Boise"))
        for label, lat, lon, want in cases:
            got = rb.timezone_at(lat, lon)
            ok(f"{label} is {want}", got == want, str(got))
    except ImportError as e:
        ok("timezonefinder is installed (requirements-registry.txt)", False, str(e))
    ok("no coordinates, no timezone", rb.timezone_at(None, -87.2) is None and rb.timezone_at(30.5, None) is None)
    # F6: the refresh installs requirements.txt only, so the lookup must not be in it, and the extra must be capped
    req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
    extra = open(os.path.join(ROOT, "requirements-registry.txt"), encoding="utf-8").read()
    ok("timezonefinder is not in requirements.txt, which the data refresh installs", "timezonefinder" not in req)
    ok("requirements-registry.txt pins timezonefinder below 10", "timezonefinder>=6.5,<10" in extra, extra)
    refresh = open(os.path.join(ROOT, ".github", "workflows", "refresh.yml"), encoding="utf-8").read()
    tests_yml = open(os.path.join(ROOT, ".github", "workflows", "tests.yml"), encoding="utf-8").read()
    ok("the refresh does not install the registry extra, and the Tests workflow does",
       "requirements-registry.txt" not in refresh and "-r requirements-registry.txt" in tests_yml)

    with with_pins():
        registry, directory = world()
        registry["programs"] = [prog("alpha", 1, "https://goalpha.com", "TX"), prog("ewu", 4, "https://goeags.com", "WA")]
        registry["programs"][0]["location"]["timezone"] = None
        rep = run(registry, directory, timezone_lookup=lambda lat, lon: "Zone/Looked/Up")
        pub = {p["slug"]: p for p in registry["programs"]}
        # fails if a null timezone is left null when the coordinates settle it
        ok("a null timezone is filled from the coordinates", pub["alpha"]["location"]["timezone"] == "Zone/Looked/Up"
           and rep["timezoneFilled"] == [{"slug": "alpha", "timezone": "Zone/Looked/Up"}], str(rep["timezoneFilled"]))
        # fails if a stored timezone is silently overwritten (correcting existing values is a reviewed change)
        ok("a stored timezone that disagrees is reported and kept", pub["ewu"]["location"]["timezone"] == "America/Chicago"
           and rep["timezoneDisagreement"] == [{"slug": "ewu", "registry": "America/Chicago", "coordinates": "Zone/Looked/Up"}],
           str(rep["timezoneDisagreement"]))
        registry, directory = world()
        registry["programs"] = [prog("alpha", 1, "https://goalpha.com", "TX")]
        registry["programs"][0]["location"]["timezone"] = None
        run(registry, directory)
        ok("without a lookup nothing is filled", registry["programs"][0]["location"]["timezone"] is None)


# ---------- the committed registry ----------

def test_committed() -> None:
    print("committed: public/data/registry.json")
    reg = common.load_registry()
    programs, held = reg["programs"], reg.get("heldPrograms")
    # Which divisions are on is the owner's call and changes with onboarding (issue #110), so this checks
    # the shape, not a value: a non-empty list of known divisions, with D1 among them.
    od = reg.get("onboardedDivisions")
    ok("onboardedDivisions is explicit data: a non-empty list of known divisions including D1",
       isinstance(od, list) and "D1" in od and set(od) <= set(rb.DIVISION_ROMAN) and len(od) == len(set(od)), str(od))
    ok("the old top-level division label is gone", "division" not in reg)
    ok("heldPrograms is a list", isinstance(held, list))
    held = held or []
    everything = programs + held
    slugs = [p["slug"] for p in everything]
    ok("slugs are unique across published and held", len(slugs) == len(set(slugs)))
    orgs = [p["ids"].get("ncaaOrgId") for p in everything if p["ids"].get("ncaaOrgId") is not None]
    ok("orgIds are unique", len(orgs) == len(set(orgs)))
    # fails if a published program sits in a division that is not onboarded
    ok("every published program is in an onboarded division", all(p["division"] in (reg.get("onboardedDivisions") or []) for p in programs),
       str([p["slug"] for p in programs if p["division"] not in (reg.get("onboardedDivisions") or [])][:5]))
    ok("every published program carries its Directory orgId", all(isinstance(p["ids"].get("ncaaOrgId"), int) for p in programs),
       str([p["slug"] for p in programs if not isinstance(p["ids"].get("ncaaOrgId"), int)]))
    ok("every held program says why", all((p.get("hold") or {}).get("reason") in ("division-not-onboarded", "not-in-directory") for p in held))
    ok("no published program carries a hold", not any("hold" in p for p in programs))

    # fails if any program's slug changed, or two programs swapped slugs (a shortlist key pointing at another school)
    pre = json.load(open(PRE_100, encoding="utf-8"))["programs"]
    now = {p["slug"]: p for p in everything}
    lost = [p["slug"] for p in pre if p["slug"] not in now]
    moved = [p["slug"] for p in pre if p["slug"] in now and (now[p["slug"]]["ids"].get("scorecardUnitId"), now[p["slug"]]["ids"].get("tdsClgId"))
             != (p["scorecardUnitId"], p["tdsClgId"])]
    ok(f"all {len(pre)} pre-#100 slugs survive, published or held", len(pre) == 350 and not lost, str(lost))
    ok("and each is still attached to the same Scorecard and TDS ids", not moved, str(moved))

    by = {p["slug"]: p for p in everything}
    sf, mvsu, uwf = by.get("saint-francis"), by.get("mississippi-val"), by.get("west-florida")
    # held exactly while D3 is not onboarded; published (and hold-free) once it is
    d3_on = "D3" in (reg.get("onboardedDivisions") or [])
    ok("Saint Francis is D3, held exactly while D3 is not onboarded", bool(sf) and sf["division"] == "D3"
       and sf["ids"].get("ncaaOrgId") == 600 and ((sf in programs and "hold" not in sf) if d3_on
                                                   else (sf in held and sf["hold"]["reason"] == "division-not-onboarded")),
       str(sf and sf.get("hold")))
    ok("Mississippi Valley State is held as in no list", mvsu in held and mvsu["hold"]["reason"] == "not-in-directory", str(mvsu and mvsu.get("hold")))
    # onboarded is deliberately not asserted: `onboard west-florida` flips it, and that must not turn this red
    ok("West Florida is a D1 entry in registry.programs with its orgId", uwf in programs and uwf["ids"].get("ncaaOrgId") == 11740
       and uwf["division"] == "D1", str(uwf))
    # fails if a value supplied from memory enters the registry (the spike's gogusties.com)
    ok("no athletics URL came from memory", "gogusties" not in json.dumps(reg))

    # PR #112 review R1: fails if a registry mistake unpublishes a long-standing D1 program (onboarded: false, a move
    # to heldPrograms), which pruning would then delete with build and validate otherwise passing
    import build  # noqa: E402 - only here, so the rest of this suite does not need build's imports
    long_standing = {p["slug"] for p in pre}
    unpublished = long_standing - {p["slug"] for p in build.published_programs(reg)}
    ok("the long-standing D1 programs not published are exactly build.REVIEWED_UNPUBLISHED", unpublished == set(build.REVIEWED_UNPUBLISHED),
       f"unreviewed {sorted(unpublished - set(build.REVIEWED_UNPUBLISHED))[:8]}, listed but published {sorted(set(build.REVIEWED_UNPUBLISHED) - unpublished)}")
    ok("and validate agrees", _quiet(build.check_membership_anchor, reg))

    # fails if held programs reach the collectors or the build
    listed = {p["slug"] for p in common.iter_programs(reg, onboarded_only=False)}
    ok("iter_programs never yields a held program", not (listed & {p["slug"] for p in held}), str(listed & {p["slug"] for p in held}))
    ok("the reviewed pins are the ids the registry carries",
       all((by.get(s) or {}).get("ids", {}).get("ncaaOrgId") == org for s, (org, _) in rb.REVIEWED_ORG_IDS.items()),
       str([s for s, (org, _) in rb.REVIEWED_ORG_IDS.items() if (by.get(s) or {}).get("ids", {}).get("ncaaOrgId") != org]))
    ok("every reviewed not-listed program is held as not listed",
       all(((by.get(s) or {}).get("hold") or {}).get("reason") == "not-in-directory" for s in rb.REVIEWED_NOT_LISTED),
       str([s for s in rb.REVIEWED_NOT_LISTED if s not in by]))
    labels = set(rb.CONFERENCE_LABELS.values())
    # The label table covers D1 today; a division without labels yet publishes the Directory's own name
    # (reported by the builder), which must still be a non-empty string.
    ok("every published D1 conference is a label from the table",
       all(p["conference"] in labels for p in programs if p["division"] == "D1"),
       str(sorted({p["conference"] for p in programs if p["division"] == "D1"} - labels)))
    ok("every published program has a conference", all(isinstance(p.get("conference"), str) and p["conference"].strip()
                                                        for p in programs),
       str([p["slug"] for p in programs if not (isinstance(p.get("conference"), str) and p["conference"].strip())][:5]))
    ok("every label has a TopDrawerSoccer conference for the new-program check", labels <= set(rb.LABEL_TDS_CONFERENCE),
       str(sorted(labels - set(rb.LABEL_TDS_CONFERENCE))))
    tds = {slug for slug, _ in rb.TDS_CONFERENCES}
    ok("and each of those is a conference page the builder fetches", set(rb.LABEL_TDS_CONFERENCE.values()) <= tds,
       str(sorted(set(rb.LABEL_TDS_CONFERENCE.values()) - tds)))


def _quiet(fn, *a):
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    VERBOSE = ap.parse_args(argv).verbose
    test_parsing()
    test_domains()
    test_identity()
    test_policy()
    test_new_entry()
    test_timezones()
    test_committed()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
