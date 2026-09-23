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
  staging     stagedDivisions: a division whose programs are in the registry and published by
              nothing -- added as onboarded: false, left alone by the next build, never held and
              never counted as a departure, while a program the site HAS published is still held
  holds       collectionHold (#199): an uncollected entry of an onboarded division is explained only
              by a well-formed hold, and a build keeps the hold
  independent the D1 and D2 independents share one label (#199): the mislabel guard and the
              TopDrawerSoccer match tell them apart by division
  slugs      the collision ladder: "University" dropped and "College" kept, the fuller name, then
              the state, then the orgId, applied to a whole batch so list order names nobody
  new entry   every field from a source or null: Wikipedia needs the state, TDS the conference,
              the timezone comes from the coordinates, a slug collision takes the state suffix
  committed   public/data/registry.json: every pre-#100 slug survives with the same ids, the three
              programs #100 names are where the policy puts them, held programs are invisible to
              iter_programs, the reviewed pins are the ids the registry carries, and the 261 staged
              D2 entries publish nothing and carry only what a source gave them
"""

from __future__ import annotations

import argparse
import collections
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Swap-back proof (issue #187): COLLEGEDASH_CODE_ROOT=<an export of origin/main> runs these checks against that code
CODE_ROOT = os.environ.get("COLLEGEDASH_CODE_ROOT") or ROOT
sys.path.insert(0, CODE_ROOT)
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
        ok("a departure inside the limit is allowed", run(copy.deepcopy(registry), empty, max_departure_share=1.0)["slugs"]
           == {"published": 0, "inPrograms": 0, "held": 2, "staged": 0, "notOnboarded": 0})
        raises("onboardedDivisions missing raises", ValueError, run, {"programs": []}, directory)
        raises("an unknown division in onboardedDivisions raises", ValueError, run, {"onboardedDivisions": ["DII"], "programs": []}, directory)
        raises("one orgId in two lists raises", ValueError, run, registry, {**directory, "D3": directory["D3"] + [directory["D1"][0]]})


# ---------- staged divisions ----------

def staged_world():
    """The world(), with D2 staged: Edward Waters is a D2 row nobody holds, and `ewu` is the D1
    program whose Scorecard domain (ewu.edu) belongs to a different school in another state."""
    registry, directory = world()
    registry["programs"] = [p for p in registry["programs"] if p["slug"] in ("alpha", "ewu")]
    registry["stagedDivisions"] = ["D2"]
    return registry, directory


def test_staging() -> None:
    print("staging: a division in the registry, published by nothing")
    raises("stagedDivisions with an unknown division raises", ValueError, rb.staged_divisions,
           {"onboardedDivisions": ["D1"], "stagedDivisions": ["DII"]})
    raises("a repeated division raises", ValueError, rb.staged_divisions,
           {"onboardedDivisions": ["D1"], "stagedDivisions": ["D2", "D2"]})
    raises("a string instead of a list raises", ValueError, rb.staged_divisions,
           {"onboardedDivisions": ["D1"], "stagedDivisions": "D2"})
    # fails if a division may be onboarded and staged at once, which would leave it unclear whether
    # its programs are published
    raises("a division in both lists raises", ValueError, rb.staged_divisions,
           {"onboardedDivisions": ["D1", "D2"], "stagedDivisions": ["D2"]})
    ok("no stagedDivisions key means nothing is staged", rb.staged_divisions({"onboardedDivisions": ["D1"]}) == [])

    # fails if the D1 label table is applied to another division. Since #199 "Independent" maps to itself,
    # so it can no longer show that; "Conference USA" still can (D1 "CUSA", D2 would keep the Directory's name)
    ok("a D1 conference is labelled from the table", rb.conference_label("Conference USA", "D1") == "CUSA")
    ok("a D2 conference keeps the Directory's own spelling", rb.conference_label("Conference USA", "D2") == "Conference USA")
    # fails if the rename is undone in the table, or the D2 spelling changes with it (owner decision 5 on #197)
    ok("#199: the D1 independent is labelled 'Independent', the same string as D2's",
       rb.conference_label("Independent", "D1") == "Independent" == rb.conference_label("Independent", "D2"))
    ok("#199: no label reads 'DI Independent' any more", "DI Independent" not in set(rb.CONFERENCE_LABELS.values())
       | set(rb.LABEL_TDS_CONFERENCE), str(sorted(set(rb.CONFERENCE_LABELS.values()))))
    # fails if a shared string is counted as D1-only: every D2 independent would then read as mislabelled
    ok("#199: d1_only_labels holds the renamed labels and not 'Independent'",
       "CUSA" in rb.d1_only_labels() and "Independent" not in rb.d1_only_labels(), str(sorted(rb.d1_only_labels())))
    ok("and so does a D2 name the table does not carry",
       rb.conference_label("Northeast 10 Conference", "D2") == "Northeast 10 Conference")

    # --- one Scorecard row, one program
    solo = [sc(20, "Merged University", "Bloomsburg", "PA", "merged.edu")]
    pair = [drow(3, "D2", "Campus One University", "PA", "merged.edu", "c.com", "C"),
            drow(4, "D2", "Campus Two University", "PA", "merged.edu", "d.com", "C")]
    contested = rb.contested_scorecard_ids(pair, solo)
    # fails if a merged university's single Scorecard row may be attached to each of its campuses,
    # giving one of them the other's city, coordinates and time zone
    ok("one Scorecard row claimed by two Directory rows is contested",
       list(contested) == [20] and len(contested[20]) == 2, str(contested))
    ok("a row already used by a registry program is contested too",
       list(rb.contested_scorecard_ids(pair[:1], solo, {"programs": [prog("other", 20, "https://o.com", "PA")]})) == [20])
    ok("an uncontested row is not reported", rb.contested_scorecard_ids(pair[:1], solo) == {})
    entry, ev = rb.new_program_entry(pair[0], bulk=solo, wiki=[], tds={}, taken=set(), contested=contested,
                                     timezone_lookup=lambda lat, lon: "America/New_York")
    ok("a contested row leaves the Scorecard fields null and says so",
       entry["ids"]["scorecardUnitId"] is None and entry["location"]["city"] is None
       and entry["location"]["timezone"] is None and ev["scorecard"].startswith("contested:20"), str(ev["scorecard"]))
    entry, _ = rb.new_program_entry(pair[0], bulk=solo, wiki=[], tds={}, taken=set(), contested={},
                                    timezone_lookup=lambda lat, lon: "America/New_York")
    ok("control: uncontested, the same row is taken", entry["ids"]["scorecardUnitId"] == 20)

    with with_pins():
        registry, directory = staged_world()
        entry = {"slug": "edward-waters", "onboarded": False, "division": "D2", "conference": "Independent",
                 "ids": {"ncaaOrgId": 105}}
        rep = run(registry, directory, new_entries={105: copy.deepcopy(entry), 108: {"slug": "epsilon", "ids": {"ncaaOrgId": 108}}})
        added = {a["slug"]: a for a in rep["added"]}
        # fails if staging a division does not add its rows, or adds them to heldPrograms instead
        ok("a staged division's rows are added to programs", "edward-waters" in added
           and any(p["slug"] == "edward-waters" for p in registry["programs"]), str(rep["added"]))
        ok("and are not held", not any(p["slug"] == "edward-waters" for p in registry["heldPrograms"]))
        # fails if a staged entry could be published: build.published_programs takes onboarded entries
        # whose division is onboarded, so either flag alone keeps it off the site
        new = next(p for p in registry["programs"] if p["slug"] == "edward-waters")
        ok("a staged entry is onboarded: false and in a division that is not onboarded",
           new["onboarded"] is False and new["division"] not in registry["onboardedDivisions"], str(new))
        ok("the report counts published, staged and held separately",
           rep["slugs"] == {"published": 2, "inPrograms": 4, "held": 0, "staged": 1, "notOnboarded": 2}, str(rep["slugs"]))

        # --- a second build recognises it rather than moving it
        again = copy.deepcopy(registry)
        rep2 = run(again, directory, today="2027-01-01")
        # fails if a staged entry is held as "division-not-onboarded" on the next build, which would
        # both move 261 D2 entries into heldPrograms and count them against the departure guard
        ok("a second build leaves the staged entry in programs",
           any(p["slug"] == "edward-waters" for p in again["programs"]) and not again["heldPrograms"], str(again["heldPrograms"]))
        ok("and reports it as staged", [s["slug"] for s in rep2["staged"]] == ["edward-waters"], str(rep2["staged"]))
        ok("the staged count is every unpublished entry in a staged division", rep2["slugs"]["staged"] == 1, str(rep2["slugs"]))
        # fails if a staged entry is rewritten on each build (a slug, a conference or an id churning
        # under an entry nobody has reviewed yet)
        ok("nothing about it changed", next(p for p in again["programs"] if p["slug"] == "edward-waters")
           == next(p for p in registry["programs"] if p["slug"] == "edward-waters"),
           str(next(p for p in again["programs"] if p["slug"] == "edward-waters")))

    # --- a collected staged entry is still staged (issue #187)
    # A staged division's batch is collected (`onboard` sets onboarded: true) long before the division is
    # published. apply_membership keyed staging on `not onboarded`, so the next build held every collected
    # entry as division-not-onboarded: 105 D2 programs on 2026-09-16, stopped only by the departure guard.
    def build_or_refusal(registry, directory, **kw):
        try:
            return run(registry, directory, **kw), None
        except RuntimeError as e:
            return None, str(e)

    with with_pins():
        registry, directory = staged_world()
        collected = prog("edward-waters", 5, "https://ewutigers.com", "FL", division="D2", conference="Independent", org=105)
        registry["programs"].append(collected)
        before = copy.deepcopy(collected)
        rep, refusal = build_or_refusal(registry, directory)
        # fails on the pre-#187 code: 1 of 3 entries "departing" is over the 5% guard, so the build refuses
        ok("FIX a build with a collected staged entry is not refused by the departure guard", refusal is None, str(refusal))
        # a refused build writes nothing (registry["programs"] keeps the entry), so each check below also
        # requires that the build ran: on the pre-#187 code every one of them fails, none is skipped
        built = rep is not None
        after = next((p for p in registry["programs"] if p["slug"] == "edward-waters"), None)
        # fails if the collected entry is moved to heldPrograms (the guard lifted, that is what the old code did)
        ok("FIX a collected staged entry (onboarded: true) stays in programs",
           built and after is not None and not registry["heldPrograms"], str(refusal or registry["heldPrograms"]))
        ok("FIX ... is reported as staged, not as a departure",
           built and [s["slug"] for s in rep["staged"]] == ["edward-waters"] and not rep["held"],
           str(refusal or (rep["staged"], rep["held"])))
        ok("FIX ... and is left exactly as it was: still onboarded, no hold block", built and after == before, str(refusal or after))
        # fails if the report's staged count still means "not onboarded": a collected staged entry is staged
        ok("FIX the report's staged count includes a collected staged entry",
           built and rep["slugs"]["staged"] == 1 and rep["slugs"]["published"] == 2, str(refusal or rep["slugs"]))
        # the same with the guard out of the way, so the placement is checked even where the old code refuses
        registry, directory = staged_world()
        registry["programs"].append(copy.deepcopy(before))
        rep = run(registry, directory, max_departure_share=1.0)
        ok("FIX with no guard in the way, the collected staged entry is still not held",
           not registry["heldPrograms"] and not rep["held"], str(rep["held"]))

        # an uncollected staged entry behaves exactly as before
        registry, directory = staged_world()
        uncollected = prog("edward-waters", 5, "https://ewutigers.com", "FL", division="D2", conference="Independent", org=105,
                           onboarded=False)
        uncollected.pop("onboardedAt")
        registry["programs"].append(uncollected)
        rep, refusal = build_or_refusal(registry, directory)
        ok("CONTROL an uncollected staged entry (onboarded: false) stays in programs, reported as staged",
           refusal is None and [s["slug"] for s in rep["staged"]] == ["edward-waters"] and not registry["heldPrograms"]
           and rep["slugs"]["staged"] == 1, str(refusal or rep["staged"]))

        # a held program whose division is staged stays held: saint-francis, published in D1, is held as D3,
        # and staging D3 must not pull it back into programs (it was published, so it is a departure, not staging)
        registry, directory = staged_world()
        registry["stagedDivisions"] = ["D2", "D3"]
        sf = prog("beta", 2, "https://gobeta.com", "PA", division="D3", org=102, conference="Presidents' Athletic Conference",
                  hold={"reason": "division-not-onboarded", "division": "D3", "orgId": 102, "since": "2026-09-15"})
        registry["heldPrograms"] = [copy.deepcopy(sf)]
        rep, refusal = build_or_refusal(registry, directory, today="2027-01-01")
        ok("CONTROL a held program (saint-francis) stays held when its division is staged, its hold unchanged",
           refusal is None and registry["heldPrograms"] == [sf] and not any(p["slug"] == "beta" for p in registry["programs"])
           and not rep["held"] and not rep["staged"] and not rep["returned"], str(refusal or registry["heldPrograms"]))

    # --- staging never unpublishes, and never hides a departure
    with with_pins():
        registry, directory = staged_world()
        # a program the site HAS published, whose division is now staged
        registry["programs"].append(prog("edward-waters", 5, "https://ewutigers.com", "FL", division="D1", org=105))
        rep = run(registry, directory, max_departure_share=1.0)
        held = {p["slug"]: p for p in registry["heldPrograms"]}
        # fails if staging a division quietly unpublishes a published program instead of holding it,
        # which is what tells the operator (and the departure guard) that the site dropped a page
        ok("a published program whose division is staged is held, not left in programs",
           "edward-waters" in held and held["edward-waters"]["hold"]["reason"] == "division-not-onboarded",
           str(rep["held"]))
        ok("and counts as a departure", [h["slug"] for h in rep["held"]] == ["edward-waters"], str(rep["held"]))

        # fails if a staged batch could be counted as departures and trip the guard, or if a real
        # departure could hide behind one
        registry, directory = staged_world()
        big = {"D1": directory["D1"], "D2": [drow(200 + i, "D2", f"Staged {i} University", "FL", f"s{i}.edu", f"gos{i}.com", "Independent")
                                             for i in range(40)], "D3": directory["D3"]}
        entries = {200 + i: {"slug": f"staged-{i}", "onboarded": False, "division": "D2", "ids": {"ncaaOrgId": 200 + i}}
                   for i in range(40)}
        rep = run(registry, big, new_entries=entries, max_departure_share=0.05)
        ok("40 staged additions to a 2-program registry do not trip the departure guard",
           len(rep["added"]) == 40 and not rep["held"], str(len(rep["added"])))

    # --- a staged entry marked onboarded is refused
    with with_pins():
        registry, directory = staged_world()
        raises("a staged division's entry marked onboarded: true raises", ValueError, run, registry, directory,
               new_entries={105: {"slug": "edward-waters", "onboarded": True, "division": "D2", "ids": {"ncaaOrgId": 105}}})


# ---------- slugs ----------

def test_slugs() -> None:
    print("slugs: the collision rule, applied to a whole batch")
    lad = rb.slug_ladder("Adams State University", "CO", 929)
    # fails if "University" survives into the slug, or the ladder's order changes
    ok("the short form drops University and leads the ladder", lad[0] == "adams-state", str(lad))
    ok("the full name is the next rung", lad[1] == "adams-state-university", str(lad))
    ok("then the state, then the full name with the state, then the orgId",
       lad[2:] == ["adams-state-co", "adams-state-university-co", "adams-state-929"], str(lad))
    # fails if "College" is dropped too: Georgia College would become "georgia", the University of
    # Georgia's slug, and Boston College would become "boston"
    ok("College is kept", rb.slug_ladder("Georgia College", "GA", 1)[0] == "georgia-college")
    ok("so Georgia College does not collide with georgia", "georgia" not in rb.slug_ladder("Georgia College", "GA", 1))
    # fails if a name the Directory itself qualifies is offered bare: Anderson (SC) is D2 and
    # Anderson (IN) is D3, so whichever was built first would take `anderson` and fix the other's URL
    ok("a name the Directory qualifies starts at the state",
       rb.slug_ladder("Anderson University (South Carolina)", "SC", 2) == ["anderson-sc", "anderson-university-sc", "anderson-2"],
       str(rb.slug_ladder("Anderson University (South Carolina)", "SC", 2)))
    ok("and the bare name is not on its ladder", "anderson" not in rb.slug_ladder("Anderson University (South Carolina)", "SC", 2))
    ok("which is the convention the registry already uses",
       rb.slug_ladder("University of Miami (Florida)", "FL", 3)[0] == "miami-fl")
    # fails if an apostrophe becomes a separator: the registry's own D1 slug is st-johns, not st-john-s
    ok("an apostrophe closes up", rb.slug_ladder("Saint Martin's University", "WA", 4)[0] == "saint-martins")
    ok("and a curly one does too", rb.slug_ladder("Saint Martin’s University", "WA", 4)[0] == "saint-martins")
    ok("an ampersand joins rather than splits", rb.slug_ladder("Texas A&M International University", "TX", 3)[0] == "texas-am-international")
    ok("a comma and a long dash are separators",
       rb.slug_ladder("California State University, San Bernardino", "CA", 4)[0] == "california-state-san-bernardino")
    ok("the ladder has no duplicate rung", rb.slug_ladder("Wheaton College", "MA", 9)[:2] == ["wheaton-college", "wheaton-college-ma"])
    ok("a verified short name goes in front", rb.slug_ladder("University of West Florida", "FL", 11740, preferred="West Florida")[0]
       == "west-florida")
    ok("a name that slugifies to nothing still gets a slug", rb.slug_ladder("!!!", "TX", 77) == ["program-77", "program-77-tx", "program-77-77"],
       str(rb.slug_ladder("!!!", "TX", 77)))

    # issue #139: two D3 qualifiers are cities, not states. Each fails against the state-only rule.
    jwu = rb.slug_ladder("Johnson & Wales University (Providence)", "RI", 22626)
    ok("a city qualifier leads the ladder, ahead of the state",
       jwu == ["johnson-wales-providence", "johnson-wales-university-providence", "johnson-wales-ri",
               "johnson-wales-university-ri", "johnson-wales-22626"], str(jwu))
    sju = rb.slug_ladder("St. Joseph's University NY (Brooklyn)", "NY", 30072)
    ok("a name that already ends in its state takes the city, not the state twice",
       sju[0] == "st-josephs-ny-brooklyn" and not any(s.endswith("-ny-ny") for s in sju), str(sju))
    ok("a bare name ending in its state never gets the state appended again",
       not any("-ny-ny" in s for s in rb.slug_ladder("Example University NY", "NY", 5)),
       str(rb.slug_ladder("Example University NY", "NY", 5)))
    ok("a state qualifier is still a state, as a name or as a code",
       rb.slug_ladder("Anderson University (Indiana)", "IN", 939)[0] == "anderson-in"
       and rb.slug_ladder("Anderson University (IN)", "IN", 939)[0] == "anderson-in",
       str(rb.slug_ladder("Anderson University (IN)", "IN", 939)))
    campuses = [drow(31, "D3", "Example University (Brooklyn)", "NY", "a.edu", "a.com", "C"),
                drow(32, "D3", "Example University (Patchogue)", "NY", "b.edu", "b.com", "C")]
    got = rb.assign_slugs(campuses, set())
    # fails under the state-only rule: both campuses are NY, so both fell through to the orgId
    ok("two campuses of one institution in one state are told apart by their city",
       got == {31: "example-brooklyn", 32: "example-patchogue"}, str(got))
    place = getattr(rb, "qualifier_place", None)
    ok("qualifier_place: a city is a place, a state is not", place is not None and place("Brooklyn") == "brooklyn"
       and place("South Carolina") == "" and place("SC") == "" and place(" ") == "")

    rows = [drow(1, "D2", "Trinity University", "CT", "a.edu", "a.com", "C"),
            drow(2, "D2", "Trinity University", "DC", "b.edu", "b.com", "C")]
    got = rb.assign_slugs(rows, set())
    # fails if the row that happens to be processed first keeps the plain slug: both are Trinity, and
    # neither may claim the name because of list order (the D3 name match that linked these two)
    ok("two rows wanting one slug both move down the ladder", got == {1: "trinity-ct", 2: "trinity-dc"}, str(got))
    ok("and the order they arrive in makes no difference", rb.assign_slugs(rows[::-1], set()) == got)
    # fails if a new program may take a slug an existing program already has (a permanent URL moving)
    ok("a slug the registry already holds sends the new row down the ladder",
       rb.assign_slugs([rows[0]], {"trinity"}) == {1: "trinity-university"}, str(rb.assign_slugs([rows[0]], {"trinity"})))
    ok("and the state is next when the fuller name is taken too",
       rb.assign_slugs([rows[0]], {"trinity", "trinity-university"}) == {1: "trinity-ct"})
    ok("the last rung carries the orgId and is always free",
       rb.assign_slugs([rows[0]], {"trinity", "trinity-university", "trinity-ct", "trinity-university-ct"}) == {1: "trinity-1"})
    # fails if the Directory's own qualifier stops reaching the slug when two such rows are built together
    lincolns = [drow(5, "D2", "Lincoln University (Missouri)", "MO", "a.edu", "a.com", "C"),
                drow(6, "D2", "Lincoln University (Pennsylvania)", "PA", "b.edu", "b.com", "C")]
    ok("two qualified rows need no collision handling at all",
       rb.assign_slugs(lincolns, set()) == {5: "lincoln-mo", 6: "lincoln-pa"}, str(rb.assign_slugs(lincolns, set())))
    many = [drow(10 + i, "D2", "Same Name University", "TX", f"s{i}.edu", f"s{i}.com", "C") for i in range(3)]
    got = rb.assign_slugs(many, set())
    # fails if three rows with one name and one state do not each end up unique
    ok("three rows with the same name and state all get distinct slugs", len(set(got.values())) == 3, str(got))
    ok("and, being indistinguishable by name or state, all three fall back to the orgId",
       sorted(got.values()) == ["same-name-10", "same-name-11", "same-name-12"], str(got))


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
    # fails if the slug is invented, or keeps a form-of-institution word no D1 slug carries: with no
    # verified short name the official name's own short form is all there is (issue #94)
    ok("with no Wikipedia row the slug is the official name's short form", entry["slug"] == "epsilon", entry["slug"])
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


# ---------- collection holds (#199) ----------

# The D2 entries deliberately never collected, and why: the owner's decision on #94 (the 6 merged PSAC
# campuses share a College Scorecard row) and the TPM's ruling recorded there (no usable athletics source).
D2_COLLECTION_HOLDS = {
    "bloomsburg-pennsylvania": "merged-scorecard-row", "lock-haven-pennsylvania": "merged-scorecard-row",
    "mansfield-pennsylvania": "merged-scorecard-row", "pennsylvania-western-california": "merged-scorecard-row",
    "pennsylvania-western-clarion": "merged-scorecard-row", "pennsylvania-western-edinboro": "merged-scorecard-row",
    "middle-georgia-state": "no-athletics-source", "texas-am-texarkana": "no-athletics-source",
    "st-cloud-state": "no-athletics-source", "puerto-rico-bayamon": "no-athletics-source",
}


def unexplained_entries(reg: dict) -> list[str]:
    """Slugs in reg.programs no membership state explains: not published, not staged (division in
    stagedDivisions), and not an uncollected entry of an onboarded division with a well-formed
    collectionHold. The committed-registry check and its mutations below share this one definition."""
    import build  # noqa: E402 - local, as in test_committed
    published = {p["slug"] for p in build.published_programs(reg)}
    staged_divs = set(rb.staged_divisions(reg))
    onboarded = set(reg.get("onboardedDivisions") or [])
    return [p["slug"] for p in reg["programs"]
            if p["slug"] not in published and p["division"] not in staged_divs
            and not (p["division"] in onboarded and not p.get("onboarded") and rb.collection_hold_problem(p) is None)]


def test_collection_holds() -> None:
    print("collection holds (#199): an uncollected entry in an onboarded division needs a reason")
    good = {"reason": "no-athletics-source", "evidence": "the Directory gives no athletics URL", "since": "2026-09-16"}

    def reg_with(entry, onboarded=("D1", "D2"), staged=()):
        return {"onboardedDivisions": list(onboarded), "stagedDivisions": list(staged), "heldPrograms": [],
                "programs": [prog("alpha", 1, "https://goalpha.com", "TX", org=101),
                             prog("gamma", 3, "https://gogamma.com", "OH", division="D2", conference="G Conf", org=103),
                             entry]}

    uncollected = prog("delta", 6, None, "NJ", division="D2", conference="G Conf", org=106, onboarded=False)
    uncollected.pop("onboardedAt")
    held_entry = dict(copy.deepcopy(uncollected), collectionHold=dict(good))

    # CONTROL: D2 staged, an uncollected entry is explained by staging alone, hold or not
    ok("CONTROL staged: an uncollected D2 entry with no hold is explained by staging",
       unexplained_entries(reg_with(copy.deepcopy(uncollected), onboarded=("D1",), staged=("D2",))) == [])
    # the check the brief asks for: fails if D2 publishes with an uncollected entry that says nothing
    ok("FIX onboarded: an uncollected D2 entry with no collectionHold is unexplained",
       unexplained_entries(reg_with(copy.deepcopy(uncollected))) == ["delta"],
       str(unexplained_entries(reg_with(copy.deepcopy(uncollected)))))
    ok("FIX onboarded: the same entry with a collectionHold is explained",
       unexplained_entries(reg_with(copy.deepcopy(held_entry))) == [], str(unexplained_entries(reg_with(copy.deepcopy(held_entry)))))
    # fails if any collectionHold-shaped thing will do: each malformed variant must leave the entry unexplained
    variants = {
        "an unknown reason": dict(good, reason="too-hard"),
        "empty evidence": dict(good, evidence="  "),
        "a date that is not ISO": dict(good, since="16/09/2026"),
        "a missing key": {"reason": "no-athletics-source", "evidence": "x"},
        "an extra key": dict(good, note="x"),
        "a string instead of a block": "no-athletics-source",
        "the membership `hold` key instead": None,
    }
    for label, block in variants.items():
        e = copy.deepcopy(uncollected)
        if block is None:
            e["hold"] = dict(good)
        else:
            e["collectionHold"] = block
        ok(f"FIX a collectionHold with {label} does not explain the entry", unexplained_entries(reg_with(e)) == ["delta"],
           str(rb.collection_hold_problem(e)))
    # fails if a collected entry may carry a hold: it would say "not collected" about a program that is
    collected = dict(prog("delta", 6, "https://godelta.com", "NJ", division="D2", conference="G Conf", org=106), collectionHold=dict(good))
    ok("FIX a collectionHold on a collected entry is a problem", rb.collection_hold_problem(collected) is not None,
       str(rb.collection_hold_problem(collected)))
    # a hold does not publish anything or move anything out of an uncollected entry's reach
    import build  # noqa: E402
    ok("a held entry is not published", "delta" not in {p["slug"] for p in build.published_programs(reg_with(copy.deepcopy(held_entry)))})
    ok("and pruning explains it as not onboarded",
       build.prune_explanations(reg_with(copy.deepcopy(held_entry))).get("delta") == "in the registry but not onboarded")

    # --- apply_membership keeps it: D2 staged, and D2 onboarded
    for label, onboarded, staged in (("staged", ["D1"], ["D2"]), ("onboarded", ["D1", "D2"], [])):
        with with_pins():
            registry, directory = world()
            directory["D2"] = [drow(106, "D2", "Delta University", "NJ", "delta-u.edu", "godelta.com", "G Conf")]
            entry = copy.deepcopy(held_entry)
            registry["programs"] = [prog("alpha", 1, "https://goalpha.com", "TX", org=101), entry]
            registry["onboardedDivisions"], registry["stagedDivisions"] = onboarded, staged
            before = copy.deepcopy(entry)
            try:
                rep = run(registry, directory)
                err = None
            except Exception as e:  # noqa: BLE001
                rep, err = None, e
            after = next((p for p in registry["programs"] if p["slug"] == "delta"), None)
            # fails if a build drops, rewrites or holds the entry, or strips its collectionHold
            ok(f"apply_membership with D2 {label}: the held entry stays in programs, unchanged, hold included",
               err is None and after == before and not registry["heldPrograms"], str(err or after))
            ok(f"apply_membership with D2 {label}: it is neither a departure nor a return",
               err is None and not rep["held"] and not rep["returned"], str(err or (rep["held"], rep["returned"])))

    # --- through build(): the written registry keeps it
    with with_pins():
        registry, directory = world()
        directory["D2"] = [drow(106, "D2", "Delta University", "NJ", "delta-u.edu", "godelta.com", "G Conf")]
        registry["programs"] = [prog("alpha", 1, "https://goalpha.com", "TX", org=101), copy.deepcopy(held_entry)]
        registry["onboardedDivisions"], registry["stagedDivisions"] = ["D1"], ["D2"]
        saved = (rb.fetch_directory, rb.fetch_scorecard_bulk, rb.fetch_wiki_list, rb.fetch_tds_teams, rb.timezone_at,
                 common.update_registry, common.write_json)

        def fake_update(mutate):
            mutate(registry)
            return registry

        try:
            rb.fetch_directory = lambda reg=None: directory
            rb.fetch_scorecard_bulk = lambda reg=None: BULK
            rb.fetch_wiki_list = lambda division="D1": []
            rb.fetch_tds_teams = lambda: {}
            rb.timezone_at = lambda lat, lon: None
            common.update_registry = fake_update
            common.write_json = lambda path, obj, **kw: None
            try:
                rb.build(copy.deepcopy(registry))
                err = None
            except Exception as e:  # noqa: BLE001
                err = e
        finally:
            (rb.fetch_directory, rb.fetch_scorecard_bulk, rb.fetch_wiki_list, rb.fetch_tds_teams, rb.timezone_at,
             common.update_registry, common.write_json) = saved
        after = next((p for p in registry["programs"] if p["slug"] == "delta"), None)
        ok("build() writes the registry with the collectionHold kept", err is None and bool(after)
           and after.get("collectionHold") == good, str(err or after))


def test_independent_label_guard() -> None:
    print("Independent (#199): one string in two divisions, told apart by division")
    import build  # noqa: E402
    import contextlib, io

    def staged_reg(*d2):
        return {"onboardedDivisions": ["D1"], "stagedDivisions": ["D2"], "heldPrograms": [],
                "programs": [prog("sc-state", 1, "https://scsu.com", "SC", conference="Independent", org=101)] + list(d2)}

    def check(reg):
        saved = dict(build.STAGED_DIVISION_COUNTS)
        buf = io.StringIO()
        try:
            build.STAGED_DIVISION_COUNTS.clear()
            build.STAGED_DIVISION_COUNTS.update({d: sum(1 for p in reg["programs"] if p["division"] == d)
                                                 for d in reg["stagedDivisions"]})
            with contextlib.redirect_stdout(buf):
                result = build.check_staged_registry(reg)
        finally:
            build.STAGED_DIVISION_COUNTS.clear()
            build.STAGED_DIVISION_COUNTS.update(saved)
        return result, buf.getvalue()

    def d2_entry(slug, org, directory_conf, table_division):
        # a D2 Directory row labelled as the builder would label it for `table_division`
        return prog(slug, org, f"https://go{slug}.com", "FL", division="D2", org=org,
                    conference=rb.conference_label(directory_conf, table_division))

    independent = d2_entry("edward-waters", 105, "Independent", "D2")
    ok_result, out = check(staged_reg(independent))
    # fails if the guard reads the shared string as D1's: every D2 independent would fail validate
    ok("CONTROL a D2 independent beside the D1 'Independent' passes the mislabel guard", ok_result, out)
    ok("CONTROL ... and so does the same row run through the D1 table, because the label is the same string",
       check(staged_reg(d2_entry("edward-waters", 105, "Independent", "D1")))[0])
    # the mutation the guard exists for: a D2 row whose Directory name the D1 table renames
    mislabelled = d2_entry("cusa-two", 106, "Conference USA", "D1")
    bad_result, bad_out = check(staged_reg(independent, mislabelled))
    ok("FIX a D2 row run through the D1 table ('Conference USA' stored as 'CUSA') fails the guard, naming it",
       mislabelled["conference"] == "CUSA" and not bad_result and "Division I conference label" in bad_out
       and "cusa-two" in bad_out and "edward-waters" not in bad_out, bad_out)
    ok("CONTROL the same row labelled for D2 passes", check(staged_reg(independent, d2_entry("cusa-two", 106, "Conference USA", "D2")))[0])
    # fails if the guard reads the label alone: a staged D1 entry is labelled from the table by design
    # (a synthetic registry staging D1, which the real one never does)
    d1_staged = {"onboardedDivisions": ["D2"], "stagedDivisions": ["D1"], "heldPrograms": [],
                 "programs": [prog("cusa-one", 107, "https://gocusa.com", "TX", conference="CUSA", org=107)]}
    ok("FIX the guard goes by division: a staged D1 entry labelled 'CUSA' is not mislabelled", check(d1_staged)[0],
       check(d1_staged)[1])

    # --- TopDrawerSoccer: a D2 independent must not take a D1 independent's TDS team by name
    tds = {"delta": {"tdsName": "Delta University", "tdsSlug": "delta", "tdsConf": "independent", "tdsClgId": 9}}
    d1_row = drow(201, "D1", "Delta University", "SC", "delta.edu", "godelta.com", "Independent")
    d2_row = drow(202, "D2", "Delta University", "FL", "delta.edu", "godelta.com", "Independent")
    got, how = rb.tds_team_for(d1_row, rb.conference_label("Independent", "D1"), None, tds)
    ok("CONTROL a D1 independent matches TDS's independent team by name and conference", bool(got) and how == "name+conference", how)
    got, how = rb.tds_team_for(d2_row, rb.conference_label("Independent", "D2"), None, tds)
    # fails if LABEL_TDS_CONFERENCE is read for a non-D1 row: since #199 D2's label is a key of that map
    ok("FIX a D2 independent with the same name does not take it", got is None, how)


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
    # `programs` holds the published entries and the staged ones (division staged; onboarded may be
    # true or false, see below). Anything else in there is a program the site publishes from a
    # division it does not publish.
    import build  # noqa: E402 - only here, so the rest of this suite does not need build's imports
    published = build.published_programs(reg)
    staged_divs = rb.staged_divisions(reg)
    # A staged entry is one whose division is staged. It may have been through `onboard` -- a batch of
    # them is collected before the division is published (issue #94, option A) -- and it is still not
    # published, because published_programs() needs the division too. "Not onboarded" was the right
    # test only while nothing had been collected.
    staged = [p for p in programs if p["division"] in staged_divs]
    collected = [p for p in staged if p.get("onboarded")]
    # fails if a published program sits in a division that is not onboarded
    ok("every published program is in an onboarded division", all(p["division"] in od for p in published),
       str([p["slug"] for p in published if p["division"] not in od][:5]))
    # fails if an entry in `programs` is neither published nor staged -- the state that would put a
    # page on the site for a division nobody onboarded, or leave an entry no policy explains. The one
    # other state allowed (#199) is an uncollected entry in an onboarded division that carries a
    # well-formed collectionHold: a person decided it is not collected, and the registry says why.
    unexplained = unexplained_entries(reg)
    ok("every entry in programs is published, staged, or held from collection with a reason", not unexplained,
       str(unexplained[:5]))
    # fails if a collectionHold is malformed, carries an unknown reason, or sits on a collected entry --
    # wherever it is, staged division included, so a bad one cannot wait for the day D2 is published
    bad_holds = [(p["slug"], rb.collection_hold_problem(p)) for p in programs
                 if "collectionHold" in p and rb.collection_hold_problem(p)]
    ok("every collectionHold is well formed and on an uncollected entry", not bad_holds, str(bad_holds[:5]))
    ok("no heldPrograms entry carries a collectionHold (a hold already says why it is not published)",
       not any("collectionHold" in p for p in held), str([p["slug"] for p in held if "collectionHold" in p]))
    # fails if staging leaks into the published set: this is the check that says the D2 work publishes nothing
    ok("no staged program is published", not (set(staged_divs) & {p["division"] for p in published}),
       str(sorted({p["division"] for p in published})))
    # iter_programs selects on `onboarded`, not on division, so a staged entry is invisible to the
    # collectors until its batch is collected and visible afterwards -- which is how a collected D2
    # program's sources stay fresh while it publishes nothing. fails if an uncollected entry is handed
    # to a collector, or if a collected one is published.
    seen = {p["slug"] for p in common.iter_programs(reg)}
    ok("an uncollected staged entry is invisible to the collectors",
       not ({p["slug"] for p in staged if not p.get("onboarded")} & seen),
       str(sorted({p["slug"] for p in staged if not p.get("onboarded")} & seen)[:5]))
    ok("a collected one is refreshed but still not published",
       {p["slug"] for p in staged if p.get("onboarded")} <= seen
       and not ({p["slug"] for p in staged} & {p["slug"] for p in published}))
    ok("every program in the registry carries its Directory orgId", all(isinstance(p["ids"].get("ncaaOrgId"), int) for p in programs),
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

    # --- the Division II entries (issue #94): staged, and after publishing (#197) still checked
    # Every check below is about the entries themselves, so it applies whether D2 is staged or onboarded; only
    # what "published" means for them depends on which. Keyed on staged alone, the block stopped running the
    # day D2 was published, and every check in it went quiet with nothing failing.
    d2_onboarded = "D2" in (reg.get("onboardedDivisions") or [])
    ok("D2 is either staged or onboarded, so the D2 checks below run", "D2" in staged_divs or d2_onboarded,
       f"stagedDivisions {staged_divs}, onboardedDivisions {reg.get('onboardedDivisions')}")
    if "D2" in staged_divs or d2_onboarded:
        d2 = [p for p in programs if p["division"] == "D2"]
        # fails if the D2 list is short or long: the 2026-27 Directory list is 261 programs, and a
        # truncated fetch is the way that number quietly drops
        ok("all 261 D2 programs are in the registry", len(d2) == 261, str(len(d2)))
        published_d2 = {p["slug"] for p in d2} & {p["slug"] for p in published}
        if d2_onboarded:
            # fails if publishing D2 leaves a collected entry off the site, or puts an uncollected one on it
            ok("with D2 onboarded, exactly the collected D2 entries are published",
               published_d2 == {p["slug"] for p in d2 if p.get("onboarded")},
               str(sorted(published_d2 ^ {p["slug"] for p in d2 if p.get("onboarded")})[:5]))
        else:
            # fails if a D2 entry reaches the published set. This is the invariant, not "nothing is
            # onboarded": a batch is collected (onboarded: true) before the division is published, so the
            # flag moves per batch and the published set must not.
            ok("and not one of them is published", not published_d2, str(sorted(published_d2)[:5]))
        ok("none is held: a D2 entry was never published before, so there is nothing to hold",
           not any("hold" in p for p in d2))
        # a collected entry says when, and an uncollected one has no date to say
        ok("onboardedAt is present exactly on the collected ones",
           all(("onboardedAt" in p) == bool(p.get("onboarded")) for p in d2),
           str([p["slug"] for p in d2 if ("onboardedAt" in p) != bool(p.get("onboarded"))][:5]))
        ok("each carries its Directory orgId and state", all(isinstance(p["ids"]["ncaaOrgId"], int) and p["location"]["state"] for p in d2))
        # fails if a D2 conference is run through the D1 label table. "Independent" is 8 D2 programs and
        # one D1 program under the same string since #199, so only the labels the D1 table renames can
        # show the mistake; the division is what separates the two independents
        ok("D2 conferences are the Directory's own spelling, not D1 labels",
           not ({p["conference"] for p in d2} & rb.d1_only_labels()),
           str(sorted({p["conference"] for p in d2} & rb.d1_only_labels())))
        # fails if the D1 rename reaches D2 (or is not made), or the D2 count moves
        independents = sorted((p["division"], p["slug"]) for p in everything if p["conference"] == "Independent")
        ok("#199: 'Independent' is the 8 D2 independents and the 1 D1 independent, south-carolina-state",
           sum(1 for d, _ in independents if d == "D2") == 8 and [s for d, s in independents if d == "D1"] == ["south-carolina-state"],
           str(independents))
        ok("#199: nothing in the registry is labelled 'DI Independent'",
           not any(p["conference"] == "DI Independent" for p in everything))
        # fails if an uncollected D2 entry has no collectionHold, or one is added to an entry nobody decided
        # on. The list is the owner's decision (6 merged PSAC campuses) and the TPM's ruling (4 with no
        # usable athletics source), both recorded on #94; changing it is a reviewed edit here.
        holds = {p["slug"]: (p.get("collectionHold") or {}).get("reason") for p in d2 if not p.get("onboarded")}
        ok("#199: the uncollected D2 entries are exactly the 10 held from collection, each with its reason",
           holds == D2_COLLECTION_HOLDS, str(sorted(set(holds.items()) ^ set(D2_COLLECTION_HOLDS.items()), key=str)))
        # fails if a value no source gave is written for a new program (the spike's gogusties.com case).
        # shortName and nickname are handled separately below (issue #200: a D2 program may carry them
        # from a cited source); everything else here still comes from nothing on D2.
        ok("nothing a source did not give is filled in", all(p["colors"] is None
                                                             and p["ids"]["wikipedia"] is None and p["ids"]["tdsClgId"] is None
                                                             and p["ids"]["ncaaName"] is None and p["ids"]["rpiHistoryName"] is None
                                                             for p in d2),
           str([p["slug"] for p in d2 if p["colors"] or p["ids"]["wikipedia"] or p["ids"]["tdsClgId"]
                or p["ids"]["ncaaName"] or p["ids"]["rpiHistoryName"]][:5]))
        # issue #200: a filled shortName or nickname must cite its source in namesNote, following #173's
        # location.note pattern ("every Scorecard id beyond the builder's joins names its source"). Fails
        # if either field is set with no note, or with a note that names no source, or if a note exists
        # with neither field set (a citation for nothing).
        named = [p for p in d2 if p.get("shortName") or p.get("nickname")]
        ok("a filled shortName or nickname cites its source in namesNote",
           all(isinstance(p.get("namesNote"), str) and "wikipedia.org" in p["namesNote"].lower() for p in named),
           str([p["slug"] for p in named if not (isinstance(p.get("namesNote"), str)
                                                  and "wikipedia.org" in p["namesNote"].lower())][:5]))
        ok("a namesNote appears only alongside a shortName or a nickname",
           all(bool(p.get("namesNote")) == bool(p.get("shortName") or p.get("nickname")) for p in d2),
           str([p["slug"] for p in d2 if bool(p.get("namesNote")) != bool(p.get("shortName") or p.get("nickname"))][:5]))
        # fails if a D2 shortName collides with another program's, published or held, in either division
        # -- D1 currently allows no shortName to repeat, so neither may D2's
        short_counts: dict[str, list[str]] = {}
        for q in everything:
            sn = q.get("shortName")
            if sn:
                short_counts.setdefault(sn.strip().lower(), []).append(q["slug"])
        dupes = {k: v for k, v in short_counts.items() if len(v) > 1}
        ok("no shortName is shared by two programs", not dupes, str(dupes))
        # fails if a platform is written for a program nothing has looked at: "auto" until the
        # athletics collector detects one and writes it back on the program's own onboard run
        ok("an uncollected entry's platform is still auto",
           {p["athletics"]["platform"] for p in d2 if not p.get("onboarded")} <= {"auto"},
           str(sorted({p["athletics"]["platform"] for p in d2 if not p.get("onboarded")})))
        # fails if a collected entry claims a platform no adapter detected. The one exception is a host
        # the registry records as refusing us (athletics.skipReason, #182): its athletics collector never
        # contacts the site, so "auto" is the honest value - but only "auto", never an invented platform.
        detected = {"sidearm", "wmt"}
        wrong_platform = sorted(
            (p["slug"], p["athletics"]["platform"]) for p in d2 if p.get("onboarded")
            and p["athletics"]["platform"] not in (detected | {"auto"} if p["athletics"].get("skipReason") else detected))
        ok("and a collected one carries a platform an adapter detected, or auto when its site is skipped",
           not wrong_platform, str(wrong_platform[:5]))
        # fails if an athletics URL is invented for the two rows the Directory leaves blank
        blank = sorted(p["slug"] for p in d2 if p["athletics"]["baseUrl"] is None)
        ok("the two rows with no Directory athletics URL have none", blank == ["middle-georgia-state", "texas-am-texarkana"], str(blank))
        # fails if one Scorecard row is attached to two programs: the Directory lists each campus of a
        # merged university separately on the parent's domain, so Mansfield would take Bloomsburg's
        # city and coordinates, and PennWest Clarion would take California's
        units = [p["ids"]["scorecardUnitId"] for p in everything if p["ids"]["scorecardUnitId"] is not None]
        ok("no Scorecard row is shared by two programs", len(units) == len(set(units)),
           str([u for u in set(units) if units.count(u) > 1]))
        contested = [p["slug"] for p in d2 if p["slug"] in ("bloomsburg-pennsylvania", "mansfield-pennsylvania",
                                                            "pennsylvania-western-california", "pennsylvania-western-clarion")]
        ok("the four merged-campus programs take no Scorecard row at all", len(contested) == 4
           and all(by[s]["ids"]["scorecardUnitId"] is None and by[s]["location"]["city"] is None for s in contested),
           str([(s, by[s]["ids"]["scorecardUnitId"], by[s]["location"]["city"]) for s in contested]))
        # fails if a city, coordinate or time zone appears without the Scorecard row it comes from
        ok("city, coordinates and time zone appear only with a Scorecard row",
           all((p["ids"]["scorecardUnitId"] is None) == (p["location"]["city"] is None) ==
               (p["location"]["lat"] is None) == (p["location"]["timezone"] is None) for p in d2),
           str([p["slug"] for p in d2 if (p["ids"]["scorecardUnitId"] is None) != (p["location"]["city"] is None)][:5]))
        # Which ids the BUILDER joined is read from its own committed report (scorecard: "exact", a website
        # domain plus state match), not inferred from the registry, so a hand-filled id cannot pass as one.
        # Issue #171: an id outside that set may exist only when it was filled by hand from a cited source,
        # and then location.note must name the Scorecard row and the file it was read from.
        # One report per division (#190): staging D3 wrote registry-build-report-d3.json and left the D2 run's
        # report, the evidence read here, byte for byte as the D2 staging run wrote it.
        report = common.read_json(rb.report_path("D2")) or {}
        exact = {r["slug"] for r in report.get("newPrograms") or [] if r.get("scorecard") == "exact"}
        joined = [p for p in d2 if p["slug"] in exact and p["ids"]["scorecardUnitId"] is not None]
        # fails if the builder's join drifts: an exact join lost, or the report rewritten with a different count
        ok("243 of the 261 join a Scorecard row by website domain", len(exact) == 243 and len(joined) == 243,
           f"report exact {len(exact)}, with an id in the registry {len(joined)}")
        # fails if an id beyond the builder's joins carries no note naming its source
        hand = [p for p in d2 if p["ids"]["scorecardUnitId"] is not None and p["slug"] not in exact]
        unsourced = [p["slug"] for p in hand
                     if f"College Scorecard row {p['ids']['scorecardUnitId']}" not in ((p["location"].get("note") or ""))
                     or "data/scorecard-bulk.json" not in (p["location"].get("note") or "")]
        ok("every Scorecard id beyond the builder's joins names its source in location.note", not unsourced,
           f"no sourced note: {unsourced}")
        # fails if a slug the Directory qualifies loses its state, which is what keeps it stable when
        # the other school of the same name arrives with D3
        qualified = sorted(p["slug"] for p in d2 if "(" in p["name"])
        ok("all 15 names the Directory qualifies carry the state", len(qualified) == 15
           and all(s.endswith("-" + by[s]["location"]["state"].lower()) for s in qualified), str(qualified))
        # fails if an apostrophe leaves a stray letter behind ("saint-martin-s")
        ok("no slug ends in a stray -s from an apostrophe", not [s for s in qualified + [p["slug"] for p in d2] if s.endswith("-s")],
           str([p["slug"] for p in d2 if p["slug"].endswith("-s")]))

    # --- the Division III entries (issue #190): staged, named with the owner's reviewed slugs
    ok("D3 is either staged or onboarded, so the D3 checks below run", "D3" in staged_divs or d3_on,
       f"stagedDivisions {staged_divs}, onboardedDivisions {reg.get('onboardedDivisions')}")
    if "D3" in staged_divs or d3_on:
        d3 = [p for p in programs if p["division"] == "D3"]
        # fails if the D3 list is short or long: the 2026-27 Directory list is 416 programs, one of them
        # saint-francis, which stays in heldPrograms until D3 is onboarded
        ok("all 416 D3 programs are in the registry: 415 in programs, saint-francis the 416th",
           len(d3) == (416 if d3_on else 415) and bool(sf), str(len(d3)))
        by_org = {p["ids"].get("ncaaOrgId"): p for p in everything}
        # fails if the registry was built without the owner's table, or the table was edited after the build
        # (an override only names a NEW program, so a late edit silently does nothing)
        unapplied = [(org, slug, (by_org.get(org) or {}).get("slug")) for org, (slug, _) in rb.REVIEWED_SLUGS.items()
                     if (by_org.get(org) or {}).get("slug") != slug]
        ok(f"every one of the {len(rb.REVIEWED_SLUGS)} reviewed slugs names its orgId in the registry", not unapplied,
           str(unapplied[:5]))
        # Which ids the builder joined, from its own D3 report, as for D2 above: exact (website domain plus state)
        # or on the registrable domain. Anything else would have to be hand-filled and name its source.
        report3 = common.read_json(rb.report_path("D3")) or {}
        kinds = collections.Counter(r.get("scorecard") for r in report3.get("newPrograms") or [])
        builder3 = {r["slug"] for r in report3.get("newPrograms") or [] if r.get("scorecard") in ("exact", "registrable")}
        joined3 = [p for p in d3 if p["slug"] in builder3 and p["ids"]["scorecardUnitId"] is not None]
        # fails if the builder's D3 join drifts, or the D3 report is rewritten with a different count
        ok("399 of the 415 join a Scorecard row by website domain (393 exact, 6 on the registrable domain)",
           kinds["exact"] == 393 and kinds["registrable"] == 6 and len(joined3) == 399,
           f"report exact {kinds['exact']}, registrable {kinds['registrable']}, with an id in the registry {len(joined3)}")
        hand3 = [p for p in d3 if p["ids"]["scorecardUnitId"] is not None and p["slug"] not in builder3]
        unsourced3 = [p["slug"] for p in hand3
                      if f"College Scorecard row {p['ids']['scorecardUnitId']}" not in (p["location"].get("note") or "")
                      or "data/scorecard-bulk.json" not in (p["location"].get("note") or "")]
        ok("every D3 Scorecard id beyond the builder's joins names its source in location.note", not unsourced3,
           f"no sourced note: {unsourced3}")

    # PR #112 review R1: fails if a registry mistake unpublishes a long-standing D1 program (onboarded: false, a move
    # to heldPrograms), which pruning would then delete with build and validate otherwise passing
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

    # fails if a staged entry is missing its orgId, state or a well-shaped slug, if a D2 conference
    # was run through the D1 label table, if a staged slug or orgId collides with anything else in
    # the registry, or if registry.stagedDivisions no longer stages what build.STAGED_DIVISION_COUNTS
    # (issue #140) expects it to. That last one is the point: unlike the block above, which only
    # has anything to say while "D2" in staged_divs, this runs every time and fails outright the
    # moment stagedDivisions stops matching the anchor - it cannot pass by finding nothing staged.
    import contextlib, io  # noqa: E402 - only here, matching _quiet() below
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        staged_registry_ok = build.check_staged_registry(reg)
    ok("staged registry entries satisfy build.check_staged_registry (issue #140)", staged_registry_ok,
       buf.getvalue().strip()[:2000])


def _quiet(fn, *a):
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a)


def test_staged_division_count_anchor() -> None:
    print("staged anchor: build.STAGED_DIVISION_COUNTS must cover every division in stagedDivisions (issue #149)")
    import build  # noqa: E402 - local, matching test_committed's own import of build
    import contextlib, io

    def run_check(reg):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = build.check_staged_registry(reg)
        return result, buf.getvalue()

    # D3 is staged, but build.STAGED_DIVISION_COUNTS does not name it - the exact gap issue #149 is
    # about: a division staged later and never added to the dict must fail loudly, not pass with
    # no count anchor at all. The shipped dict names D3 (#190), so D3 is taken out of it for this case.
    reg = {"onboardedDivisions": ["D1"], "stagedDivisions": ["D3"],
           "programs": [prog("gamma-d3", 900, "https://gogamma.com", "OH", division="D3", conference="Old Conf", org=900)],
           "heldPrograms": []}
    saved = dict(build.STAGED_DIVISION_COUNTS)
    try:
        build.STAGED_DIVISION_COUNTS.pop("D3", None)
        result, out = run_check(reg)
    finally:
        build.STAGED_DIVISION_COUNTS.clear()
        build.STAGED_DIVISION_COUNTS.update(saved)
    # fails if a staged division with no entry in STAGED_DIVISION_COUNTS passes silently
    ok("a staged division missing from STAGED_DIVISION_COUNTS fails the check", not result, out)
    ok("names the division, what to do, and when to do it",
       "STAGED D3" in out and "STAGED_DIVISION_COUNTS" in out and "same PR that stages it" in out, out)

    # control: naming D3 with its real count removes the failure, so the case above is really
    # testing the anchor and not some unrelated break in the fixture.
    saved = dict(build.STAGED_DIVISION_COUNTS)
    try:
        build.STAGED_DIVISION_COUNTS.clear()
        build.STAGED_DIVISION_COUNTS.update({"D3": 1})
        result2, out2 = run_check(reg)
        ok("control: naming D3 with its actual count passes", result2, out2)
    finally:
        build.STAGED_DIVISION_COUNTS.clear()
        build.STAGED_DIVISION_COUNTS.update(saved)


def test_division_reports() -> None:
    print("build reports: one per division, each with only its own rows (#190)")
    split = getattr(rb, "division_reports", None)
    if split is None:
        ok("FIX registry_builder.division_reports exists", False, "no division_reports on this code")
        return
    report = {"builtAt": "2026-09-23T00:00:00Z", "stagedDivisions": ["D3"], "timezoneDisagreement": [{"slug": "x1"}],
              "staged": [], "returned": [],
              "added": [{"slug": "a2", "division": "D2"}, {"slug": "a3", "division": "D3"}],
              "notAdded": [{"orgId": 9, "name": "N3", "division": "D3"}],
              "held": [{"slug": "h1", "reason": "not-in-directory", "division": None}],
              "reclassified": [{"slug": "r1", "from": "D2", "to": "D1"}],
              "newPrograms": [{"slug": "a2"}, {"slug": "a3"}],
              "unmatched": {"colors": ["a2", "a3"], "nickname": ["a3"]}, "counts": {"colors": 2, "nickname": 1},
              "contestedScorecardRows": {"11": ["Name A2", "Name B2"], "22": ["Name A3", "x1 (already in the registry)"]}}
    by_slug = {"a2": "D2", "a3": "D3", "h1": "D1", "r1": "D1", "x1": "D1"}
    by_name = {"Name A2": "D2", "Name B2": "D2", "Name A3": "D3", "N3": "D3"}
    out = split(report, by_slug, by_name)
    ok("a report is split into the divisions it decided something in", sorted(out) == ["D1", "D2", "D3"], str(sorted(out)))
    d1, d2, d3 = out.get("D1", {}), out.get("D2", {}), out.get("D3", {})
    ok("D2 keeps only its own rows", [r["slug"] for r in d2.get("added", [])] == ["a2"] and [r["slug"] for r in d2.get("newPrograms", [])] == ["a2"]
       and d2.get("unmatched") == {"colors": ["a2"]} and d2.get("counts") == {"colors": 1}
       and list(d2.get("contestedScorecardRows", {})) == ["11"] and d2.get("notAdded") == [], str(d2))
    ok("D3 keeps only its own rows, notAdded included", [r["slug"] for r in d3.get("added", [])] == ["a3"] and len(d3.get("notAdded", [])) == 1
       and d3.get("unmatched") == {"colors": ["a3"], "nickname": ["a3"]} and list(d3.get("contestedScorecardRows", {})) == ["22"], str(d3))
    ok("a hold with no division and a reclassification go by the registry's division, and `to`",
       [r["slug"] for r in d1.get("held", [])] == ["h1"] and [r["slug"] for r in d1.get("reclassified", [])] == ["r1"]
       and d1.get("added") == [], str(d1))
    ok("run fields are copied to every division's report", all(o.get("builtAt") == report["builtAt"]
                                                              and o.get("timezoneDisagreement") == [{"slug": "x1"}] for o in out.values()))
    ok("the input report is not modified", report["added"][0]["slug"] == "a2" and len(report["added"]) == 2)
    quiet = {k: ([] if isinstance(v, list) else v) for k, v in report.items()}
    ok("a run that decided nothing writes no report", split(quiet, by_slug, by_name) == {}, str(split(quiet, by_slug, by_name)))
    # fails if the `staged` status list (every staged entry, on every build) counts as a decision: the next
    # build after staging D3 would then rewrite the D3 report with nothing added and erase its join evidence
    rerun = dict(quiet, staged=[{"slug": "a3", "division": "D3", "orgId": 3}])
    ok("a later build that only finds D3 still staged leaves the D3 report alone", split(rerun, by_slug, by_name) == {},
       str(sorted(split(rerun, by_slug, by_name))))


def test_reviewed_slugs() -> None:
    print("reviewed slugs: REVIEWED_SLUGS names a new program, never renames one, and refuses an unusable override (#190)")
    missing_fn = lambda *a, **kw: (_ for _ in ()).throw(AttributeError("no name_new_programs on this code"))  # noqa: E731
    name_new = getattr(rb, "name_new_programs", None) or missing_fn
    eastern = drow(301, "D3", "Eastern University", "PA", "eastern.edu", "goeasterneagles.com", "MAC Freedom")
    south = drow(302, "D3", "University of the South", "TN", "sewanee.edu", "sewaneetigers.com", "Southern Athletic Association")
    # a row whose own first rung is the slug reviewed for Eastern: the reviewed slug must win, and this one move down
    rival = drow(303, "D3", "Eastern PA University", "NJ", "epa.edu", "goepa.com", "NJAC")
    taken = {"eastern-illinois", "south-carolina", "alpha"}

    def call(rows, table):
        try:
            return name_new(rows, set(taken), {}, table), None
        except Exception as e:  # noqa: BLE001
            return None, e

    ok("CONTROL with no override the ladder names them: eastern, south",
       rb.assign_slugs([eastern, south], set(taken)) == {301: "eastern", 302: "south"}, str(rb.assign_slugs([eastern, south], set(taken))))
    got, err = call([eastern, south], {})
    ok("FIX an empty table names them exactly as the ladder does", err is None and got == {301: "eastern", 302: "south"}, str(err or got))

    # --- applied to a new program
    got, err = call([eastern, south, rival], {301: ("eastern-pa", "a direction, not a name")})
    # fails if the table is ignored, or the reviewed slug is moved down the ladder instead of taken as given
    ok("FIX a reviewed slug names the new program exactly: 301 -> eastern-pa", err is None and got[301] == "eastern-pa",
       str(err or got))
    ok("FIX ... and a program without an override keeps its ladder: 302 -> south", err is None and got[302] == "south", str(err or got))
    # fails if the reviewed slug is not counted as taken for the rest of the batch: 303's first rung is eastern-pa
    ok("FIX ... and another new row whose ladder reaches the same slug moves down, not the reviewed one",
       err is None and got[303] == "eastern-pa-university" and len(set(got.values())) == 3, str(err or got))

    # --- through build(): the table reaches the entries a build adds, and never an entry already held
    with with_pins():
        registry, directory = staged_world()
        registry["stagedDivisions"] = ["D2", "D3"]
        registry["programs"].append(prog("edward-waters", 5, "https://ewutigers.com", "FL", division="D2", conference="Independent",
                                         org=105, onboarded=False))
        directory["D3"] = [eastern]
        saved = (rb.fetch_directory, rb.fetch_scorecard_bulk, rb.fetch_wiki_list, rb.fetch_tds_teams, rb.timezone_at,
                 common.update_registry, common.write_json, getattr(rb, "REVIEWED_SLUGS", None))
        written = {}

        def fake_update(mutate):
            mutate(registry)
            return registry

        try:
            rb.fetch_directory = lambda reg=None: directory
            rb.fetch_scorecard_bulk = lambda reg=None: BULK
            rb.fetch_wiki_list = lambda division="D1": []
            rb.fetch_tds_teams = lambda: {}
            rb.timezone_at = lambda lat, lon: None
            common.update_registry = fake_update
            common.write_json = lambda path, obj, **kw: written.__setitem__(path, obj)
            # 105 is already in the registry as edward-waters; 301 is new
            rb.REVIEWED_SLUGS = {301: ("eastern-pa", "a direction, not a name"), 105: ("ewu-tigers", "would rename an entry")}
            try:
                build_rep = rb.build(copy.deepcopy(registry))
                build_err = None
            except Exception as e:  # noqa: BLE001
                build_rep, build_err = None, e
            slugs = {p["ids"].get("ncaaOrgId"): p["slug"] for p in registry["programs"]}
            # fails if build() names new programs without the table
            ok("FIX build() names the new D3 program from REVIEWED_SLUGS: eastern-pa",
               build_err is None and slugs.get(301) == "eastern-pa", str(build_err or slugs))
            # This build adds a D1 row (epsilon) and a D3 row (Eastern) and only finds edward-waters still staged in D2.
            # fails if it writes (overwrites) the D2 report, or the old single run report -- the way staging D3 used
            # to erase the D2 join evidence test_committed reads (#190)
            report_path = getattr(rb, "report_path", lambda d: None)
            reports = sorted(os.path.basename(p) for p in written if "registry-build-report" in os.path.basename(p))
            ok("FIX a build writes the report of each division it added to (D1, D3) and leaves D2's alone",
               build_err is None and reports == ["registry-build-report-d1.json", "registry-build-report-d3.json"]
               and report_path("D3") in written, str(reports))
            d3_rep = written.get(report_path("D3")) or {}
            ok("and that report is D3's: the new row in added and newPrograms",
               [r["slug"] for r in d3_rep.get("added") or []] == ["eastern-pa"]
               and [r["slug"] for r in d3_rep.get("newPrograms") or []] == ["eastern-pa"], str(d3_rep.get("added")))
            # fails if an override is applied to (or checked against) an entry the registry already holds. The two GUARD
            # checks pass on code without the table too (nothing there renames anything); the mutation that applies
            # the table to every orgId, not only to rows being added, is what they catch
            ok("GUARD an override for an orgId already in the registry renames nothing: 105 stays edward-waters, and the build runs",
               build_err is None and slugs.get(105) == "edward-waters" and not any(s == "ewu-tigers" for s in slugs.values()),
               str(build_err or slugs))
            # its own slug in the table (the state every reviewed entry is in on the builds after the one that added it)
            # a later build that still has a new row to add, so the table is read: 301 is taken out again
            registry["programs"] = [p for p in registry["programs"] if p["ids"].get("ncaaOrgId") != 301]
            rb.REVIEWED_SLUGS = {105: ("edward-waters", "already added under this slug"), 301: ("eastern-pa", "x")}
            try:
                rb.build(copy.deepcopy(registry))
                again_err = None
            except Exception as e:  # noqa: BLE001
                again_err = e
            slugs = {p["ids"].get("ncaaOrgId"): p["slug"] for p in registry["programs"]}
            ok("GUARD an override naming the slug its own entry already holds is not a collision on later builds",
               again_err is None and slugs.get(301) == "eastern-pa" and slugs.get(105) == "edward-waters", str(again_err or slugs))
        finally:
            (rb.fetch_directory, rb.fetch_scorecard_bulk, rb.fetch_wiki_list, rb.fetch_tds_teams, rb.timezone_at,
             common.update_registry, common.write_json) = saved[:7]
            if saved[7] is None:
                rb.__dict__.pop("REVIEWED_SLUGS", None)
            else:
                rb.REVIEWED_SLUGS = saved[7]

    # --- refused, with the override named
    def refused(label, table, *needles):
        got, err = call([eastern, south], table)
        ok(label, isinstance(err, ValueError) and all(n in str(err) for n in needles), str(err or got))

    # fails if a reviewed slug an entry already holds is quietly moved down the ladder (or published twice)
    refused("FIX an override that collides with an existing slug is refused, naming it",
            {301: ("eastern-illinois", "x")}, "eastern-illinois", "already held")
    # fails if two orgIds may be given one slug
    refused("FIX two overrides with one slug are refused, naming both orgIds",
            {301: ("sewanee", "x"), 302: ("sewanee", "y")}, "sewanee", "301", "302")
    ok("FIX ... the same two with distinct slugs are applied",
       call([eastern, south], {301: ("eastern-pa", "x"), 302: ("sewanee", "y")})[0] == {301: "eastern-pa", 302: "sewanee"})
    # fails if a slug that breaks the shape build.check_staged_registry enforces could be written
    refused("FIX an override with capitals or a doubled hyphen is refused", {301: ("Eastern--PA", "x")}, "Eastern--PA", "not a valid slug")
    refused("FIX an override with an underscore is refused", {301: ("eastern_pa", "x")}, "eastern_pa", "not a valid slug")
    refused("FIX an override with a trailing hyphen is refused", {301: ("eastern-", "x")}, "eastern-", "not a valid slug")
    # The shipped table is the owner's 2026-09-23 decision on #190: all 41 proposed D3 renames. That it was applied
    # is checked against the committed registry in test_committed; here, that the table itself is usable.
    shipped = getattr(rb, "REVIEWED_SLUGS", {})
    ok("the shipped table holds the 41 D3 renames the owner accepted (#190)", len(shipped) == 41, str(len(shipped)))
    ok("every shipped slug is well formed and no two share one",
       all(rb.SLUG_SHAPE.match(s) for s, _ in shipped.values()) and len({s for s, _ in shipped.values()}) == len(shipped),
       str([s for s, _ in shipped.values() if not rb.SLUG_SHAPE.match(s)]))
    ok("every shipped override gives a reason", all(isinstance(r, str) and r.strip() for _, r in shipped.values()))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    VERBOSE = ap.parse_args(argv).verbose
    test_parsing()
    test_domains()
    test_identity()
    test_policy()
    test_staging()
    test_collection_holds()
    test_independent_label_guard()
    test_slugs()
    test_reviewed_slugs()
    test_division_reports()
    test_new_entry()
    test_timezones()
    test_committed()
    test_staged_division_count_anchor()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
