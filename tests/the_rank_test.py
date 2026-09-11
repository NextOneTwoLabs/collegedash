"""Regression tests for the Times Higher Education rank asset, parser, derivation and check tool.

    python tests/the_rank_test.py            # everything below, offline
    python tests/the_rank_test.py --verbose  # print every check, not only the failures

Offline: reads tests/fixtures/the/rankings.html plus the two committed data files, makes no
request, and writes only into a temporary directory. Exit 0 when every check passes, 1 otherwise.

Covers, in order:
  parser        the fixture: ties, the four normalisation cases, banded scores, "1501+", and the
                shapes that must raise rather than be guessed at. Every fixture row is asserted to
                be a verbatim copy of its committed asset row
  asset         the committed data/the-us-rankings-2026.json: 171 rows, ties set on exactly the
                shared ranks, unique slugs and nameKeys
  aliases       the committed data/the-rank-aliases.json: 126 entries, evidence tags, pinned names,
                and the 224 N/A count measured against the registry rather than its own header
  traps         the six fuzzy-match traps from issue #46, asserted one by one
  derivation    group_items refuses to pick between two Wikidata items for one IPEDS unit id, and
                an acronym-shaped candidate cannot claim a row
  check tool    exits 0 on the committed pair and non-zero on a corrupted copy, with every finding
                type it can emit offline actually emitted
  build         what build.py publishes: 126 ranked / 224 null in the profiles and in index.json,
                the spot checks, the hard failure on a missing asset, the schema's required block
                and the validate invariant that traces every published rank back to an asset row
  card          public/index.html: the card renders the rank, and every other admission-rate
                surface -- sort, table column, glance panel, tabs, compare -- is left alone
"""

from __future__ import annotations

import argparse
import collections
import contextlib
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
from collect import common, the_rank  # noqa: E402
from tools import the_rank_check, the_rank_derive  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "the", "rankings.html")
ASSET_PATH = os.path.join(ROOT, "data", "the-us-rankings-2026.json")
ALIAS_PATH = os.path.join(ROOT, "data", "the-rank-aliases.json")

# The five programs whose only automatic evidence was a Wikidata alias -- nothing authoritative
# agreed -- so they carry their own tag and a re-derivation re-surfaces them for review.
ALIAS_ONLY = {"indiana", "michigan", "tennessee", "virginia-tech", "william-mary"}

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
    except Exception as e:  # noqa: BLE001 - the wrong exception type is still a failure
        ok(name, False, f"raised {type(e).__name__}: {e}")
        return
    ok(name, False, "did not raise")


# ---------- parser, against the fixture ----------

def test_parser(asset: dict) -> None:
    print("parser: tests/fixtures/the/rankings.html")
    with open(FIXTURE, encoding="utf-8") as f:
        html = f.read()
    table = the_rank.parse_table(html)
    rows = table["rows"]
    by_slug = {r["theSlug"]: r for r in rows}

    ok("12 data rows, the header row skipped", len(rows) == 12, f"got {len(rows)}")
    ok("rankLabel/rankYear", (table["rankLabel"], table["rankYear"]) == ("US Rank 2026", 2026))

    mit = by_slug["massachusetts-institute-technology"]
    ok("plain rank '1' -> 1, not tied", (mit["usRank"], mit["tied"]) == (1, False), str(mit))
    for slug in ("harvard-university", "stanford-university"):
        r = by_slug[slug]
        ok(f"tie '=3' -> 3 + tied ({slug})", (r["usRank"], r["tied"]) == (3, True), str(r))
    ok("parse_us_rank('=166')", the_rank.parse_us_rank("=166") == (166, True))
    ok("parse_us_rank(' 1 ')", the_rank.parse_us_rank(" 1 ") == (1, False))

    # The four normalisation cases. `name` stays verbatim (invisible characters and all) because it
    # is what the alias table pins; `nameKey` is the only thing a join ever compares.
    purdue = by_slug["purdue-university-west-lafayette"]
    ok("NBSP kept in name (Purdue)", purdue["name"] == "Purdue University West Lafayette",
       repr(purdue["name"]))
    ok("NBSP normalised in nameKey (Purdue)", purdue["nameKey"] == "purdue university west lafayette",
       repr(purdue["nameKey"]))
    northeastern = by_slug["northeastern-university-us"]
    ok("NBSP kept in name (Northeastern)", northeastern["name"] == "Northeastern University, US",
       repr(northeastern["name"]))
    ok("NBSP + ', US' normalised (Northeastern)", northeastern["nameKey"] == "northeastern university",
       repr(northeastern["nameKey"]))
    hawaii = by_slug["university-hawaii-manoa"]
    ok("U+2019 + macron kept in name (Hawai'i)",
       hawaii["name"] == "University of Hawai’i at Mānoa", repr(hawaii["name"]))
    ok("U+2019 + macron normalised (Hawai'i)", hawaii["nameKey"] == "university hawaii manoa",
       repr(hawaii["nameKey"]))
    ok("Hawai'i is ranked =63", (hawaii["usRank"], hawaii["tied"]) == (63, True), str(hawaii))
    rutgers = by_slug["rutgers-university-new-brunswick-0"]
    ok("en dash kept in name (Rutgers)", rutgers["name"] == "Rutgers University–New Brunswick",
       repr(rutgers["name"]))
    ok("en dash normalised (Rutgers)", rutgers["nameKey"] == "rutgers university new brunswick",
       repr(rutgers["nameKey"]))
    ok("Rutgers is ranked =66", (rutgers["usRank"], rutgers["tied"]) == (66, True), str(rutgers))
    ok("Drupal '-0' dedup suffix kept in theSlug",
       rutgers["theSlug"] == "rutgers-university-new-brunswick-0")

    # A macron, an okina and a plain ASCII spelling all have to fold to one key, or the join drops
    # Hawai'i however THE and Wikidata happen to spell it that year.
    ok("norm_key folds every Hawai'i spelling",
       len({the_rank.norm_key(s) for s in ("University of Hawai’i at Mānoa",
                                           "University of Hawaiʻi at Mānoa",
                                           "University of Hawai'i at Manoa",
                                           "University of Hawaii at Manoa")}) == 1)

    ok("banded overall flagged", by_slug["morgan-state-university"]["overallBanded"] is True)
    ok("banded overall kept raw", by_slug["morgan-state-university"]["overall"] == "10.3–27.2",
       repr(by_slug["morgan-state-university"]["overall"]))
    ok("exact overall not flagged", mit["overallBanded"] is False)
    ok("'1501+' world rank kept raw", by_slug["morgan-state-university"]["worldRank"] == "1501+")
    ok("banded world rank kept raw", hawaii["worldRank"] == "251–300", repr(hawaii["worldRank"]))

    # Banding is the common case on this table (116 of 171, 68%), not the tail, so the fixture has
    # to be banded in roughly that proportion or a parser that mishandled bands looks healthy here.
    banded = sum(1 for r in rows if r["overallBanded"])
    ok("8 of 12 fixture rows have a banded overall, as on the page (116 of 171)", banded == 8,
       f"got {banded} of {len(rows)}")
    ok("the fixture's banded share is within 5 points of the real 116/171",
       abs(banded / len(rows) - 116 / 171) < 0.05, f"{banded}/{len(rows)} vs 116/171")
    ok("two rows really do share =66, and =103", sum(1 for r in rows if r["usRank"] == 66) == 2
       and sum(1 for r in rows if r["usRank"] == 103) == 2)

    # "Trimmed out of the real table" has to stay literally true: every fixture row must parse to
    # exactly the row the committed asset holds, or the fixture is testing invented values.
    committed = {r["theSlug"]: r for r in asset["rows"]}
    drift = [r["theSlug"] for r in rows if committed.get(r["theSlug"]) != r]
    ok("every fixture row is its real row from the committed asset", not drift, str(drift))

    raises("no table -> ValueError", ValueError, the_rank.parse_table, "<html><body>nope</body></html>")
    raises("unparseable rank -> ValueError", ValueError, the_rank.parse_us_rank, "Top 10")
    raises("banded rank -> ValueError", ValueError, the_rank.parse_us_rank, "160-166")
    raises("row without a ranking link -> ValueError", ValueError, the_rank.parse_table,
           '<table id="rankingTable"><tr><td>1</td><td>2</td><td>Nowhere U</td><td>9</td></tr></table>')
    raises("duplicate theSlug -> ValueError", ValueError, the_rank.parse_table,
           html.replace("/world-university-rankings/stanford-university",
                        "/world-university-rankings/harvard-university"))


# ---------- the committed asset ----------

def test_asset(asset: dict) -> None:
    print("asset: data/the-us-rankings-2026.json")
    rows = asset["rows"]
    ok("171 rows", len(rows) == 171, f"got {len(rows)}")
    ok("124 tied", sum(1 for r in rows if r["tied"]) == 124,
       f"got {sum(1 for r in rows if r['tied'])}")
    ok("116 banded overall scores", sum(1 for r in rows if r["overallBanded"]) == 116,
       f"got {sum(1 for r in rows if r['overallBanded'])}")
    ok("every theSlug unique", len({r["theSlug"] for r in rows}) == len(rows))
    ok("every nameKey unique", len({r["nameKey"] for r in rows}) == len(rows))
    bad = [r["theSlug"] for r in rows
           if not isinstance(r["usRank"], int) or not 1 <= r["usRank"] <= 166]
    ok("usRank is an int in 1..166 everywhere", not bad, str(bad[:5]))
    ok("usRank ascending", [r["usRank"] for r in rows] == sorted(r["usRank"] for r in rows))
    # A band ("=103" covering three schools) is carried by `tied`, never by the number, so `tied`
    # has to be set on exactly the shared ranks. The old assertion here re-ran the isinstance check
    # above it and could not fail. This one catches a row that claims a tie it is not in, or sits
    # in one it does not admit to -- which is how a card would print "=39" against a unique rank.
    shared = collections.Counter(r["usRank"] for r in rows)
    mismarked = [(r["theSlug"], r["usRank"], r["tied"]) for r in rows
                 if r["tied"] != (shared[r["usRank"]] > 1)]
    ok("tied is set on exactly the shared ranks", not mismarked, str(mismarked[:5]))
    ok("the ties really are groups: 124 rows across 15 shared ranks",
       sum(1 for n in shared.values() if n > 1) == 15
       and sum(n for n in shared.values() if n > 1) == 124,
       f"{sum(1 for n in shared.values() if n > 1)} groups, "
       f"{sum(n for n in shared.values() if n > 1)} rows")
    ok("provenance present", bool(asset.get("sourceUrl")) and bool(asset.get("fetchedAt")))
    ok("sourceUrl is the page the parser reads", asset["sourceUrl"] == the_rank.SOURCE_URL)
    ok("nameKey agrees with norm_key(name) on every row",
       all(r["nameKey"] == the_rank.norm_key(r["name"]) for r in rows))


# ---------- the committed alias table ----------

def test_aliases(asset: dict, table: dict) -> None:
    print("aliases: data/the-rank-aliases.json")
    aliases = table["aliases"]
    rows = {r["theSlug"]: r for r in asset["rows"]}

    ok("126 ranked programs", len(aliases) == 126, f"got {len(aliases)}")
    ok("header count agrees", table.get("ranked") == len(aliases))
    ok("rankYear agrees with the asset", table.get("rankYear") == asset.get("rankYear"))
    missing = [s for s, a in aliases.items() if a["theSlug"] not in rows]
    ok("every theSlug is in the asset", not missing, str(missing))
    claims: dict[str, list[str]] = {}
    for s, a in aliases.items():
        claims.setdefault(a["theSlug"], []).append(s)
    dupes = {k: v for k, v in claims.items() if len(v) > 1}
    ok("no THE row claimed twice", not dupes, str(dupes))
    drift = [s for s, a in aliases.items() if rows.get(a["theSlug"], {}).get("name") != a["name"]]
    ok("every pinned name still matches its row", not drift, str(drift))
    tags = {s: a["evidence"] for s, a in aliases.items()}
    ok("every evidence tag is known",
       set(tags.values()) <= set(the_rank_check.EVIDENCE_TAGS), str(set(tags.values())))
    ok("the five alias-only matches are tagged",
       {s for s, t in tags.items() if t == "auto-alias-only"} == ALIAS_ONLY,
       str(sorted(s for s, t in tags.items() if t == "auto-alias-only")))
    ok("every reviewed alias carries a note",
       all(a.get("note") for a in aliases.values() if a["evidence"] == "reviewed"))
    # The old form iterated the header's own keys, so an empty or half-written evidenceCounts
    # passed vacuously. Compare the two mappings whole, both directions, and require the tags to
    # account for every alias.
    counts = dict(table.get("evidenceCounts") or {})
    actual = dict(collections.Counter(a["evidence"] for a in aliases.values()))
    ok("evidenceCounts names every tag and counts every alias",
       counts == actual and sum(counts.values()) == len(aliases) and bool(counts),
       f"header {counts}, entries {actual}")
    ok("the evidence split is 106 auto + 5 auto-alias-only + 15 reviewed",
       actual == {"auto": 106, "auto-alias-only": 5, "reviewed": 15}, str(actual))

    # The N/A count is the whole coverage claim on issue #46, so it is measured against the
    # registry the build reads, not against the number this table wrote about itself.
    programs = sum(1 for _ in common.iter_programs(common.load_registry()))
    ok("350 programs in the registry", programs == 350, f"got {programs}")
    ok("224 programs are N/A", programs - len(aliases) == 224,
       f"{programs} programs - {len(aliases)} ranked")
    ok("the header's program count is the registry's", table.get("programs") == programs,
       f"header {table.get('programs')}, registry {programs}")


def test_traps(asset: dict, table: dict) -> None:
    """The six pairings fuzzy matching produced on this very list (issue #46), one assertion each,
    plus the two rows that only exist because of must-fix 1's normalisation."""
    print("traps: the six fuzzy-match pairings, asserted individually")
    aliases = table["aliases"]
    rows = {r["theSlug"]: r for r in asset["rows"]}

    def rank_of(slug):
        a = aliases.get(slug)
        return None if not a else (rows[a["theSlug"]]["usRank"], rows[a["theSlug"]]["tied"])

    ok("virginia -> UVA at 50, not Virginia Commonwealth", rank_of("virginia") == (50, False),
       f"{aliases.get('virginia')} -> {rank_of('virginia')}")
    ok("virginia's row is university-virginia-main-campus",
       aliases["virginia"]["theSlug"] == "university-virginia-main-campus")
    ok("penn-state -> Penn State at =39, not University of Pennsylvania (8)",
       rank_of("penn-state") == (39, True), f"{aliases.get('penn-state')} -> {rank_of('penn-state')}")
    ok("penn-state's row is penn-state-main-campus",
       aliases["penn-state"]["theSlug"] == "penn-state-main-campus")
    for slug, wrong in (("san-diego", "UC San Diego"), ("east-texas-am", "Texas A&M"),
                        ("south-dakota-state", "University of South Dakota"),
                        ("siena-college", "New York University")):
        ok(f"{slug} is absent (fuzzy matching offered {wrong})", slug not in aliases,
           str(aliases.get(slug)))

    ok("hawaii -> =63 (must-fix 1: U+2019 and a macron)", rank_of("hawaii") == (63, True),
       f"{aliases.get('hawaii')} -> {rank_of('hawaii')}")
    ok("rutgers -> =66 (must-fix 1: an en dash)", rank_of("rutgers") == (66, True),
       f"{aliases.get('rutgers')} -> {rank_of('rutgers')}")
    ok("the two ambiguous unit ids are not in the table",
       "liu" not in aliases and "iu-indianapolis" not in aliases)


# ---------- derivation ----------

def _binding(unit, qid, label, article=None, alias=None):
    b = {"unit": unit, "item": f"http://www.wikidata.org/entity/{qid}", "itemLabel": label}
    if article:
        b["article"] = "https://en.wikipedia.org/wiki/" + article
    if alias:
        b["alias"] = alias
    return b


def test_derivation(asset: dict) -> None:
    print("derivation: tools/the_rank_derive.py")
    # 151111 really does resolve to two Wikidata items today: IU Indianapolis and the dissolved
    # IUPUI. With no pin, refusing to choose is the whole point.
    two = [_binding("151111", "Q123207578", "Indiana University Indianapolis"),
           _binding("151111", "Q1433199", "Indiana University – Purdue University Indianapolis")]
    raises("unit 151111 with two items and no pin -> AmbiguousUnitId",
           the_rank_derive.AmbiguousUnitId, the_rank_derive.group_items, two, known={})
    raises("a pin naming different QIDs still raises", the_rank_derive.AmbiguousUnitId,
           the_rank_derive.group_items, two,
           known={"151111": (frozenset({"Q123207578", "Q99999999"}), "stale pin")})
    grouped = the_rank_derive.group_items(two)  # the real KNOWN_AMBIGUOUS pin
    ok("the pinned ambiguous id is flagged, not resolved", grouped["151111"]["ambiguous"] is True,
       str(grouped["151111"]))
    ok("an ambiguous entry offers no names to match on",
       the_rank_derive.candidates(grouped["151111"]) == [])
    ok("both live ambiguous ids are pinned",
       set(the_rank_derive.KNOWN_AMBIGUOUS) == {"151111", "192448"})

    one = [_binding("166027", "Q13371", "Harvard University", "Harvard_University", "Harvard")]
    g = the_rank_derive.group_items(one)
    ok("a single item resolves cleanly", g["166027"]["label"] == "Harvard University", str(g))
    ok("the sitelink title is unescaped", g["166027"]["article"] == "Harvard University")
    ok("candidates are label, sitelink, then aliases",
       [k for k, _ in the_rank_derive.candidates(g["166027"])] == ["label", "sitelink", "alias"])

    # The join itself, on the real 171 rows: a program named "Pennsylvania State University" must
    # not land on "University of Pennsylvania", however close the strings look.
    rows = asset["rows"]
    programs = [{"slug": "penn-state", "name": "Pennsylvania State University",
                 "ids": {"scorecardUnitId": 214777}},
                {"slug": "harvard", "name": "Harvard University", "ids": {"scorecardUnitId": 166027}}]
    wd = the_rank_derive.group_items(
        [_binding("214777", "Q49115", "Pennsylvania State University", "Pennsylvania_State_University"),
         _binding("166027", "Q13371", "Harvard University", "Harvard_University")])
    built, report = the_rank_derive.derive(programs, wd, rows, reviewed={})
    ok("Penn State matches nothing without its reviewed alias", "penn-state" not in built, str(built))
    ok("Harvard matches automatically", built.get("harvard", {}).get("theSlug") == "harvard-university",
       str(built))
    ok("the miss is reported as unranked",
       [r["outcome"] for r in report if r["slug"] == "penn-state"] == ["unranked"], str(report))
    built2, _ = the_rank_derive.derive(
        programs, wd, rows, reviewed={"penn-state": ("penn-state-main-campus", "University Park.")})
    ok("the reviewed alias puts Penn State on =39",
       built2["penn-state"]["theSlug"] == "penn-state-main-campus"
       and built2["penn-state"]["evidence"] == "reviewed", str(built2.get("penn-state")))
    # An acronym is never specific enough to claim a row: 42 norm_key values in the Wikidata name
    # set are shared by two different programs of ours, all of them acronyms.
    ok("a bare acronym is not a matchable key",
       [the_rank_derive.matchable_key(s) for s in ("USC", "MSU", "UT", "NU")] == [None] * 4)
    ok("a real name still is", the_rank_derive.matchable_key("University of Southern California")
       == "university southern california")
    ok("no committed THE row folds below the threshold, so the guard changes no match today",
       min(len(r["nameKey"].split()) for r in rows) >= the_rank_derive.MIN_CANDIDATE_TOKENS,
       str(min((len(r["nameKey"].split()), r["theSlug"]) for r in rows)))
    # The hole, made concrete: if THE ever printed a row as a bare "USC", our usc program's
    # Wikidata alias "USC" would fold onto it -- and so would south-carolina's. Neither may claim
    # it. The label, the only authoritative name, does not match that row and is not enough.
    acronym_row = [{"name": "USC", "nameKey": "usc", "theSlug": "usc", "usRank": 1, "tied": False}]
    usc = the_rank_derive.group_items(
        [_binding("123961", "Q4614", "University of Southern California", alias="USC")])
    built3, report3 = the_rank_derive.derive(
        [{"slug": "usc", "name": "University of Southern California",
          "ids": {"scorecardUnitId": 123961}}], usc, acronym_row, reviewed={})
    ok("a Wikidata alias of 'USC' cannot claim a THE row printed as 'USC'", built3 == {},
       str(built3))
    ok("and the program is reported unranked rather than matched",
       [r["outcome"] for r in report3] == ["unranked"], str(report3))

    ok("conflicts() spots a row claimed twice",
       the_rank_derive.conflicts({"a": {"theSlug": "x"}, "b": {"theSlug": "x"}}) == {"x": ["a", "b"]})
    ok("conflicts() is empty on the committed table",
       the_rank_derive.conflicts(json.load(open(ALIAS_PATH, encoding="utf-8"))["aliases"]) == {})


# ---------- the check tool ----------

def _run_check(*argv) -> tuple[int | None, str]:
    """(exit code, everything it printed). An exception comes back as code None rather than
    unwinding the suite: the bug this file now guards against was the tool raising on a malformed
    asset, and a test for it has to survive to report that."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = the_rank_check.main(list(argv))
    except Exception as e:  # noqa: BLE001 - any exception is the failure under test
        return None, f"raised {type(e).__name__}: {e}\n{buf.getvalue()}"
    return code, buf.getvalue()


def _kinds(out: str) -> collections.Counter:
    """{finding kind: how many were printed}, read off the tool's own output. Only the finding
    lines are indented, so --quiet output parses exactly."""
    return collections.Counter(line.split()[0] for line in out.splitlines()
                               if line.startswith("  ") and line.split())


def test_check_tool(asset: dict) -> None:
    print("check tool: tools/the_rank_check.py")
    code, out = _run_check("--quiet")
    ok("exits 0 on the committed pair", code == 0, out)

    tmp = tempfile.mkdtemp(prefix="the-rank-test-")
    try:
        asset_copy = os.path.join(tmp, "asset.json")
        alias_copy = os.path.join(tmp, "aliases.json")
        shutil.copyfile(ASSET_PATH, asset_copy)
        table = json.load(open(ALIAS_PATH, encoding="utf-8"))
        # Exactly the rot the pin exists to catch: THE renames a row, the slug still resolves.
        table["aliases"]["stanford"]["name"] = "Leland Stanford Junior University"
        common.write_json(alias_copy, table)
        code, out = _run_check("--quiet", "--asset", asset_copy, "--aliases", alias_copy)
        ok("a changed pinned name exits non-zero", code == 1, out)
        ok("and names the slug", "stanford" in out and "name-drift" in out, out)

        table = json.load(open(ALIAS_PATH, encoding="utf-8"))
        table["aliases"]["stanford"]["theSlug"] = "stanford-university-renamed"
        common.write_json(alias_copy, table)
        code, out = _run_check("--quiet", "--asset", asset_copy, "--aliases", alias_copy)
        ok("an alias pointing at no row exits non-zero", code == 1, out)
        ok("and reports unknown-the-slug", "unknown-the-slug" in out, out)

        table = json.load(open(ALIAS_PATH, encoding="utf-8"))
        table["aliases"]["clemson"] = dict(table["aliases"]["stanford"])
        common.write_json(alias_copy, table)
        code, out = _run_check("--quiet", "--asset", asset_copy, "--aliases", alias_copy)
        ok("two programs claiming one row exits non-zero", code == 1, out)
        ok("and reports duplicate-claim", "duplicate-claim" in out, out)

        table = json.load(open(ALIAS_PATH, encoding="utf-8"))
        table["aliases"]["stanford"]["evidence"] = "vibes"
        common.write_json(alias_copy, table)
        code, out = _run_check("--quiet", "--asset", asset_copy, "--aliases", alias_copy)
        ok("an unknown evidence tag exits non-zero", code == 1, out)

        # bad-row. THE MUST-FIX: check_asset reported this row correctly and then check_aliases
        # indexed the very key it had just reported missing, so the tool died with KeyError before
        # printing anything. The finding has to reach stdout, not just the exit code.
        common.write_json(asset_copy, {"rankYear": 2026, "rows": [{"name": "Nameless University"}]})
        code, out = _run_check("--asset", asset_copy, "--aliases", ALIAS_PATH)
        ok("a row with no theSlug exits non-zero", code == 1, out)
        ok("and PRINTS bad-row rather than raising KeyError", "bad-row" in out, out)
        ok("and names the row it is talking about", "Nameless University" in out, out)

        # bad-row again, for the three checks that run on a row that does have a slug. An empty
        # alias table keeps the output to the asset's own findings.
        common.write_json(alias_copy, {"rankYear": 2026, "aliases": {}})
        common.write_json(asset_copy, {"rankYear": 2026, "rows": [
            {"name": "A", "theSlug": "a", "nameKey": "a", "usRank": "=3", "tied": "yes"},
            {"name": "B", "theSlug": "b", "nameKey": "a", "usRank": 2, "tied": False}]})
        code, out = _run_check("--quiet", "--asset", asset_copy, "--aliases", alias_copy)
        ok("a string usRank, a string tied and a colliding nameKey are three bad-rows",
           _kinds(out) == {"bad-row": 3}, f"{dict(_kinds(out))}\n{out}")
        ok("and the nameKey collision says which rows collided", "collides with" in out, out)

        # duplicate-the-slug: two rows, one slug, which would make "the row" ambiguous.
        common.write_json(asset_copy, dict(asset, rows=asset["rows"] + [dict(asset["rows"][0])]))
        code, out = _run_check("--quiet", "--asset", asset_copy, "--aliases", alias_copy)
        ok("a repeated theSlug exits non-zero", code == 1, out)
        ok("and reports duplicate-the-slug once, alongside the nameKey collision",
           _kinds(out) == {"duplicate-the-slug": 1, "bad-row": 1}, f"{dict(_kinds(out))}\n{out}")

        # missing-asset: an asset that parses but holds nothing.
        common.write_json(asset_copy, {"rankYear": 2026, "rows": []})
        code, out = _run_check("--quiet", "--asset", asset_copy, "--aliases", alias_copy)
        ok("an empty asset exits non-zero", code == 1, out)
        ok("and reports missing-asset", _kinds(out) == {"missing-asset": 1},
           f"{dict(_kinds(out))}\n{out}")

        # year-mismatch: the alias table was derived against a different year's asset.
        common.write_json(asset_copy, dict(asset, rankYear=2025))
        code, out = _run_check("--quiet", "--asset", asset_copy, "--aliases", alias_copy)
        ok("an asset from another year exits non-zero", code == 1, out)
        ok("and reports year-mismatch", _kinds(out) == {"year-mismatch": 1},
           f"{dict(_kinds(out))}\n{out}")

        # count-mismatch: the header stopped describing the entries under it.
        shutil.copyfile(ASSET_PATH, asset_copy)
        table = json.load(open(ALIAS_PATH, encoding="utf-8"))
        table["ranked"] = 999
        common.write_json(alias_copy, table)
        code, out = _run_check("--quiet", "--asset", asset_copy, "--aliases", alias_copy)
        ok("a header count that does not match the entries exits non-zero", code == 1, out)
        ok("and reports count-mismatch", _kinds(out) == {"count-mismatch": 1},
           f"{dict(_kinds(out))}\n{out}")

        # --refetch's diff, driven offline: the fixture stands in for "a freshly parsed table".
        table = json.load(open(ALIAS_PATH, encoding="utf-8"))
        with open(FIXTURE, encoding="utf-8") as f:
            fresh = the_rank.parse_table(f.read())["rows"]
        moved = [dict(r, usRank=7, tied=False) if r["theSlug"] == "harvard-university" else r
                 for r in fresh]
        kinds = {f["finding"] for f in the_rank_check.diff_tables(asset, moved, table, None)}
        ok("--refetch diff reports a rank change", "rank-change" in kinds, str(sorted(kinds)))
        ok("--refetch diff reports dropped rows", "dropped-row" in kinds, str(sorted(kinds)))
        ok("--refetch diff reports aliases whose row is gone", "alias-row-gone" in kinds,
           str(sorted(kinds)))
        renamed = [dict(r, name="Harvard College") if r["theSlug"] == "harvard-university" else r
                   for r in asset["rows"]]
        kinds = {f["finding"] for f in the_rank_check.diff_tables(asset, renamed, table, None)}
        ok("--refetch diff reports a renamed pinned row", kinds == {"alias-name-changed"},
           str(sorted(kinds)))
        ok("--refetch diff is silent when nothing moved",
           the_rank_check.diff_tables(asset, asset["rows"], table, None) == [])

        # The must-fix's second site: diff_tables indexed the same missing key. A malformed row is
        # check_asset's finding to report; here it must simply be skipped, not raise.
        broken = dict(asset, rows=[{"name": "Nameless University"}] + asset["rows"])
        try:
            kinds = {f["finding"] for f in the_rank_check.diff_tables(broken, asset["rows"],
                                                                      table, None)}
        except Exception as e:  # noqa: BLE001 - raising is the regression
            kinds = f"raised {type(e).__name__}: {e}"
        ok("diff_tables skips a row with no theSlug instead of raising", kinds == set(), str(kinds))
        newcomer = asset["rows"] + [{"name": "Clemson University", "nameKey": "clemson university",
                                     "theSlug": "clemson-university", "usRank": 170, "tied": False,
                                     "worldRank": "1501+", "overall": "10.3–27.2",
                                     "overallBanded": True}]
        kinds = {f["finding"] for f in
                 the_rank_check.diff_tables(asset, newcomer, table, common.load_registry())}
        ok("--refetch diff flags a new row that now matches a program",
           kinds == {"new-row", "newly-matchable"}, str(sorted(kinds)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- build, schema and card ----------

def _fake_profiles(tmp: str, rows: dict[str, dict]) -> dict:
    """Write {slug: academicRank block} into a scratch profiles directory and return a registry
    naming exactly those slugs, so check_academic_ranks can be tested without touching public/."""
    for slug, ar in rows.items():
        common.write_json(os.path.join(tmp, f"{slug}.json"), {"slug": slug, "academicRank": ar})
    return {"programs": [{"slug": s, "onboarded": True} for s in rows]}


def _check_ranks(tmp: str, rows: dict[str, dict]) -> tuple[bool, str]:
    reg = _fake_profiles(tmp, rows)
    real = common.PROGRAMS_OUT_DIR
    common.PROGRAMS_OUT_DIR = tmp
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            passed = build.check_academic_ranks(reg)
    finally:
        common.PROGRAMS_OUT_DIR = real
    return passed, buf.getvalue().strip()


def test_build(asset: dict, table: dict) -> None:
    """What build.py publishes, and the two guards that stop a silent failure looking like data."""
    print("build: profiles, index.json, and the validate invariant")
    index = json.load(open(os.path.join(common.PROGRAMS_OUT_DIR, "index.json"), encoding="utf-8"))
    rows = index["programs"]
    ranked = [r for r in rows if r.get("academicRank") is not None]
    ok("index.json carries 350 rows", len(rows) == 350, str(len(rows)))
    ok("126 ranked in index.json", len(ranked) == 126, str(len(ranked)))
    ok("224 unranked in index.json", len(rows) - len(ranked) == 224, str(len(rows) - len(ranked)))
    ok("every row carries the key, so undefined never means unranked",
       all("academicRank" in r and "academicRankTied" in r for r in rows))

    asset_rows = {r["theSlug"]: r for r in asset["rows"]}
    by_slug, n_ranked, n_null = {}, 0, 0
    for f in sorted(os.listdir(common.PROGRAMS_OUT_DIR)):
        if f == "index.json" or not f.endswith(".json"):
            continue
        p = json.load(open(os.path.join(common.PROGRAMS_OUT_DIR, f), encoding="utf-8"))
        by_slug[p["slug"]] = p.get("academicRank")
        if isinstance(p.get("academicRank"), dict) and p["academicRank"].get("rank") is not None:
            n_ranked += 1
        else:
            n_null += 1
    ok("126 ranked profiles", n_ranked == 126, str(n_ranked))
    ok("224 null profiles", n_null == 224, str(n_null))
    ok("every profile carries the block", all(isinstance(v, dict) for v in by_slug.values()))

    for slug, want in (("stanford", (3, True)), ("virginia", (50, False)), ("penn-state", (39, True)),
                       ("hawaii", (63, True)), ("rutgers", (66, True))):
        a = by_slug[slug]
        ok(f"{slug} publishes {'=' if want[1] else ''}{want[0]}", (a["rank"], a["tied"]) == want, str(a))
        ok(f"{slug}'s theSlug is a real asset row", a["theSlug"] in asset_rows, str(a.get("theSlug")))
    for slug in ("clemson", "san-diego", "siena-college"):
        a = by_slug[slug]
        ok(f"{slug} publishes rank null and no theSlug",
           a["rank"] is None and a["theSlug"] is None, str(a))
    ok("the block names Times Higher Education and its URL",
       by_slug["stanford"]["source"] == "Times Higher Education"
       and by_slug["stanford"]["sourceUrl"] == asset["sourceUrl"], str(by_slug["stanford"]))

    # Losing the asset must not look like 224 unranked programs turning into 350.
    tmp = tempfile.mkdtemp(prefix="the-rank-build-")
    try:
        reg = common.load_registry()
        for name, attr in (("ranking asset", "THE_ASSET_PATH"), ("alias table", "THE_ALIAS_PATH")):
            real = getattr(build, attr)
            setattr(build, attr, os.path.join(tmp, "gone.json"))
            try:
                raises(f"a missing {name} raises rather than emitting 350 nulls",
                       FileNotFoundError, build.load_academic_ranks, reg)
            finally:
                setattr(build, attr, real)

        good = {"rank": 50, "tied": False, "theSlug": "university-virginia-main-campus",
                "year": 2026, "label": "US Rank 2026", "source": "Times Higher Education",
                "sourceUrl": asset["sourceUrl"], "asOf": asset["fetchedAt"]}
        null = {**good, "rank": None, "tied": False, "theSlug": None}
        passed, out = _check_ranks(tmp, {"virginia": good, "clemson": null})
        ok("validate passes on a sound pair", passed, out)
        passed, out = _check_ranks(tmp, {"virginia": {**good, "theSlug": "university-of-nowhere"}})
        ok("validate catches a theSlug that is not in the asset",
           not passed and "not in" in out, out)
        passed, out = _check_ranks(tmp, {"virginia": {**good, "rank": 1}})
        ok("validate catches a rank hand-edited away from its row",
           not passed and "publishes 1" in out, out)
        passed, out = _check_ranks(tmp, {"virginia": good, "clemson": dict(good)})
        ok("validate catches one asset row claimed twice",
           not passed and "claimed by" in out, out)
        passed, out = _check_ranks(tmp, {"virginia": {**null, "theSlug": "stanford-university"}})
        ok("validate catches a null rank still claiming a row", not passed, out)

        import jsonschema
        schema = common.read_json(common.SCHEMA_PATH)
        profile = json.load(open(os.path.join(common.PROGRAMS_OUT_DIR, "clemson.json"), encoding="utf-8"))
        ok("the committed clemson profile is schema-valid",
           not list(jsonschema.Draft202012Validator(schema).iter_errors(profile)))
        for broken, why in ((lambda p: p.pop("academicRank"), "no academicRank block at all"),
                            (lambda p: p["academicRank"].pop("rank"), "a block with no rank key")):
            p = json.loads(json.dumps(profile))
            broken(p)
            ok(f"the schema rejects {why}",
               bool(list(jsonschema.Draft202012Validator(schema).iter_errors(p))))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_card() -> None:
    """The card shows the rank; every other admission-rate surface is left alone (issue #46)."""
    print("card: public/index.html")
    html = open(os.path.join(ROOT, "public", "index.html"), encoding="utf-8").read()
    card = html[html.index("function cardHtml("):html.index("function tableHtml(")]

    ok("the card's fact names the source", "fact('US rank (THE)', rankHtml(p), rankTitle(p))" in card)
    ok("the card no longer reads the admission rate", "admissionRate" not in card, card)
    ok("a tie renders with THE's '=' marker",
       "p.academicRankTied ? '=' : ''" in html and "'#' " not in html.split("const rankHtml")[1][:200])
    ok("an unranked program renders N/A", "p.academicRank == null ? 'N/A'" in html)
    ok("the title attribute spells out the ranking",
       "Times Higher Education, Best universities in the United States 2026" in html)
    ok("fact() renders a title attribute when given one",
       'const fact = (label, value, title) =>' in html and 'title="${esc(title)}"' in html)

    for what, needle in (
            ("the sort options keep Admission rate", "['admit', 'Admission rate']"),
            ("sortCmp keeps its admit key", "key === 'admit' ? (a.admissionRate ?? 1)"),
            ("the table keeps its Admit column", "['admit', 'Admit', 'num', p => fmtPct(p.admissionRate)"),
            ("the at-a-glance panel keeps Admit rate", 'Admit rate</div><div class="stat-value">${fmtPct(sch.admissionRate)}'),
            ("the Overview tab keeps Admission rate", "tile('Admission rate', fmtPct(sch.admissionRate)"),
            ("the School tab keeps Admission rate", "kv('Admission rate', fmtPct(s.admissionRate))"),
            ("compare keeps Admission rate", "['Admission rate', p => fmtPct(p.school?.admissionRate)]"),
            ("the FAQ credits Times Higher Education", "ext(THE_RANK_URL, 'Times Higher Education')")):
        ok(what, needle in html, needle)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose

    asset = json.load(open(ASSET_PATH, encoding="utf-8"))
    table = json.load(open(ALIAS_PATH, encoding="utf-8"))

    test_parser(asset)
    test_asset(asset)
    test_aliases(asset, table)
    test_traps(asset, table)
    test_derivation(asset)
    test_check_tool(asset)
    test_build(asset, table)
    test_card()

    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed"
          + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
