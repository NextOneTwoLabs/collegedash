"""Regression tests for the Times Higher Education rank asset, parser, derivation and check tool.

    python tests/the_rank_test.py            # everything below, offline
    python tests/the_rank_test.py --verbose  # print every check, not only the failures

Offline: reads tests/fixtures/the/rankings.html plus the two committed data files, makes no
request, and writes only into a temporary directory. Exit 0 when every check passes, 1 otherwise.

Covers, in order:
  parser        the fixture: ties, the four normalisation cases, banded scores, "1501+", and the
                shapes that must raise rather than be guessed at
  asset         the committed data/the-us-rankings-2026.json: 171 rows, 124 tied, unique slugs
  aliases       the committed data/the-rank-aliases.json: 126 entries, evidence tags, pinned names
  traps         the six fuzzy-match traps from issue #46, asserted one by one
  derivation    group_items refuses to pick between two Wikidata items for one IPEDS unit id
  check tool    exits 0 on the committed pair and non-zero on a corrupted copy
"""

from __future__ import annotations

import argparse
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

def test_parser() -> None:
    print("parser: tests/fixtures/the/rankings.html")
    with open(FIXTURE, encoding="utf-8") as f:
        html = f.read()
    table = the_rank.parse_table(html)
    rows = table["rows"]
    by_slug = {r["theSlug"]: r for r in rows}

    ok("8 data rows, the header row skipped", len(rows) == 8, f"got {len(rows)}")
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
    ok("3 of 8 fixture rows have a banded overall",
       sum(1 for r in rows if r["overallBanded"]) == 3)

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
    ok("no banded usRank", all(isinstance(r["usRank"], int) for r in rows))
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
    counts = table.get("evidenceCounts") or {}
    ok("evidenceCounts agrees with the entries",
       all(sum(1 for a in aliases.values() if a["evidence"] == k) == v for k, v in counts.items()),
       str(counts))
    ok("224 programs are N/A", (table.get("programs") or 0) - len(aliases) == 224,
       f"programs {table.get('programs')}")


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
    ok("conflicts() spots a row claimed twice",
       the_rank_derive.conflicts({"a": {"theSlug": "x"}, "b": {"theSlug": "x"}}) == {"x": ["a", "b"]})
    ok("conflicts() is empty on the committed table",
       the_rank_derive.conflicts(json.load(open(ALIAS_PATH, encoding="utf-8"))["aliases"]) == {})


# ---------- the check tool ----------

def _run_check(*argv) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = the_rank_check.main(list(argv))
    return code, buf.getvalue()


def test_check_tool() -> None:
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

        # --refetch's diff, driven offline: the fixture stands in for "a freshly parsed table".
        asset = json.load(open(ASSET_PATH, encoding="utf-8"))
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


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose

    asset = json.load(open(ASSET_PATH, encoding="utf-8"))
    table = json.load(open(ALIAS_PATH, encoding="utf-8"))

    test_parser()
    test_asset(asset)
    test_aliases(asset, table)
    test_traps(asset, table)
    test_derivation(asset)
    test_check_tool()

    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed"
          + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
