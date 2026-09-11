"""Derive data/the-rank-aliases.json: which of our programs appear in Times Higher Education's
US table, and under which row. Committed so the join is reproducible, not folklore.

    python tools/the_rank_derive.py                     # re-derive and write the alias table
    python tools/the_rank_derive.py --dry-run           # print the join, write nothing
    python tools/the_rank_derive.py --json report.json  # per-program evidence, including the misses
    python tools/the_rank_derive.py --asset data/the-us-rankings-2026.json --out data/the-rank-aliases.json

Exit 0 when the join is clean, 1 when anything needs a human, 2 on a usage or fetch error.

WHY THIS IS NOT A NAME MATCHER. Ranking a program's academics off a fuzzy name match is exactly
how issue #48 put Michigan's admission rate on Michigan State's card. Run against this list, token
similarity confidently pairs University of Virginia with Virginia Commonwealth, Penn State with the
University of Pennsylvania, San Diego with UC San Diego, East Texas A&M with Texas A&M, South
Dakota State with the University of South Dakota and Siena with New York University. So the join
runs through an identifier instead:

    ids.scorecardUnitId  --wdt:P1771-->  a Wikidata item  -->  its English label, aliases and
    (IPEDS unit id)                                            en.wikipedia sitelink

and a program is matched to a THE row only when one of those names is *exactly equal* to the row's
name after collect.the_rank.norm_key folding (case, accents, punctuation, a handful of stopwords)
and folds to at least MIN_CANDIDATE_TOKENS tokens, so a bare acronym can never claim a row.
No similarity score exists anywhere in this file. Wikidata is a derivation-time tool only: the
build reads the committed alias table and never queries anything.

EVIDENCE TAGS, which are the point of committing the table rather than the query:

    auto             the Wikidata label or the en.wikipedia article title matched. The safe class.
    auto-alias-only  only a Wikidata *alias* matched, so nothing authoritative agreed. There are
                     five (indiana, michigan, tennessee, virginia-tech, william-mary), all checked
                     by hand; the tag exists so a re-derivation re-surfaces them for review rather
                     than letting an edited alias quietly move a card.
    reviewed         a hand-written alias with a note. These are the campus-suffix rows THE prints
                     that no Wikidata name spells the same way ("Penn State (Main campus)").

P1771 IS NOT 1:1. Two of our unit ids resolve to two Wikidata items each, because a merged or
defunct institution kept the id: 151111 is both IU Indianapolis and the dissolved IUPUI, 192448
both Long Island University and LIU Post. Neither is ranked, so no card is affected today, but
*silently taking whichever row SPARQL returned first* is the failure this whole design exists to
avoid. group_items therefore raises on any unit id with more than one item unless that exact set
of QIDs is pinned in KNOWN_AMBIGUOUS below, and a pinned id is excluded from matching outright.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collect import common  # noqa: E402
from collect import the_rank  # noqa: E402

ASSET_PATH = os.path.join(ROOT, "data", "the-us-rankings-2026.json")
ALIAS_PATH = os.path.join(ROOT, "data", "the-rank-aliases.json")

SPARQL_URL = "https://query.wikidata.org/sparql"
SPARQL_HEADERS = dict(the_rank.HEADERS, Accept="application/sparql-results+json")
CHUNK = 60  # unit ids per query; the whole set in one VALUES block times out

QUERY = """
SELECT ?unit ?item ?itemLabel ?alias ?article WHERE {
  VALUES ?unit { %s }
  ?item wdt:P1771 ?unit .
  OPTIONAL { ?item skos:altLabel ?alias FILTER(lang(?alias) = "en") }
  OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

# IPEDS unit ids that legitimately carry two Wikidata items, pinned to the exact QIDs reviewed.
# A pinned id is never matched automatically: if one of these schools is ever ranked it must come
# in as a `reviewed` alias, chosen by a person. Change the QID set and the script raises again.
KNOWN_AMBIGUOUS = {
    "151111": (frozenset({"Q123207578", "Q1433199"}),
               "IU Indianapolis and the dissolved IUPUI both carry the id; neither is ranked."),
    "192448": (frozenset({"Q1783603", "Q543394"}),
               "Long Island University and LIU Post both carry the id; neither is ranked."),
}

# Hand-written aliases for the rows THE prints with a campus suffix that no Wikidata name spells
# the same way. Each was checked against the registry's city and state before being written here;
# the note says what was checked, in the style of tools/registry_check.py's ACCEPTED.
REVIEWED = {
    "purdue": ("purdue-university-west-lafayette",
               "THE names the West Lafayette campus; our purdue IS West Lafayette (unit 243780)."),
    "ohio-state": ("ohio-state-university-main-campus",
                   "'(Main campus)' is Columbus, our program's campus. Distinct from Ohio University below."),
    "penn-state": ("penn-state-main-campus",
                   "'Penn State (Main campus)' is University Park. NOT university-pennsylvania, rank 8."),
    "massachusetts": ("university-massachusetts",
                      "THE's unsuffixed 'University of Massachusetts' row is Amherst, our unit 166629."),
    "pittsburgh": ("university-pittsburgh-pittsburgh-campus",
                   "'-Pittsburgh campus' is the main campus, our unit 215293."),
    "virginia": ("university-virginia-main-campus",
                 "UVA, Charlottesville. NOT virginia-commonwealth-university (=80) or Virginia Tech (=63)."),
    "arizona-state": ("arizona-state-university-tempe",
                      "'(Tempe)' is ASU's main campus, our unit 104151. NOT university-arizona, rank 45."),
    "florida-state": ("florida-state-university",
                      "Exact name, but Q861548 carries the historical alias 'University of Florida', "
                      "which also matches THE's rank-44 row; pinned by hand so that cannot decide it."),
    "south-carolina": ("university-south-carolina-columbia",
                       "'-Columbia' is the flagship, our unit 218663. NOT university-southern-california."),
    "colorado-state": ("colorado-state-university-fort-collins-0",
                       "'Fort Collins' is the main campus. Note the Drupal '-0' dedup suffix in the slug."),
    "missouri": ("mizzou-university-missouri",
                 "THE files Columbia as 'Mizzou'. NOT Missouri S&T or UMKC, both also =103."),
    "new-mexico-state": ("new-mexico-state-university-main-campus",
                         "'(Main campus)' is Las Cruces, our unit 188030."),
    "ohio-university": ("ohio-university-main-campus",
                        "Athens. Deliberately the row below ohio-state-university-main-campus."),
    "binghamton": ("suny-binghamton-university", "THE prefixes the SUNY campuses; our unit 196079."),
    "albany": ("suny-university-albany", "THE prefixes the SUNY campuses; our unit 196060."),
}


# A candidate name has to fold to at least this many tokens before it may claim a THE row. The
# Wikidata name set holds 42 norm_key values shared by two *different* programs of ours -- usc, msu,
# osu, ut, um, asu, nu and friends -- and every one of them is an acronym. Nothing fires today only
# because no THE row is acronym-shaped (the shortest row key on the page is two tokens), which is a
# property of this year's page rather than a rule. This makes it a rule: an acronym is never
# specific enough to put one university's ranking on another's card (issues #46 and #48).
MIN_CANDIDATE_TOKENS = 2


class AmbiguousUnitId(RuntimeError):
    """One IPEDS unit id, more than one Wikidata item, and no pin saying which is which."""


# ---------- Wikidata ----------

def sparql(unit_ids, *, max_age_hours: float | None = 24.0) -> list[dict]:
    """P1771 lookups for every unit id, in chunks. Read-only, cached under .cache/http."""
    out = []
    for i in range(0, len(unit_ids), CHUNK):
        values = " ".join('"%s"' % u for u in unit_ids[i:i + CHUNK])
        url = SPARQL_URL + "?" + urllib.parse.urlencode({"query": QUERY % values, "format": "json"})
        body, _ = common.fetch_json(url, headers=SPARQL_HEADERS, max_age_hours=max_age_hours)
        out += [{k: v["value"] for k, v in b.items()} for b in body["results"]["bindings"]]
    return out


def group_items(bindings, *, known=KNOWN_AMBIGUOUS) -> dict:
    """{unit id: {"qid", "label", "article", "aliases", "ambiguous", "note"}}.

    Raises AmbiguousUnitId when a unit id resolves to several Wikidata items and that exact set of
    QIDs is not pinned in `known`. Pinned ids come back with ambiguous=True and no usable names, so
    they cannot match anything: the caller must not guess either.
    """
    per_item = collections.defaultdict(lambda: collections.defaultdict(
        lambda: {"label": None, "article": None, "aliases": set()}))
    for b in bindings:
        qid = b["item"].rsplit("/", 1)[-1]
        e = per_item[b["unit"]][qid]
        e["label"] = e["label"] or b.get("itemLabel")
        if b.get("article"):
            e["article"] = urllib.parse.unquote(b["article"].rsplit("/", 1)[-1]).replace("_", " ")
        if b.get("alias"):
            e["aliases"].add(b["alias"])

    out = {}
    for unit, items in per_item.items():
        if len(items) > 1:
            qids = frozenset(items)
            pinned = known.get(unit)
            if not pinned or pinned[0] != qids:
                raise AmbiguousUnitId(
                    f"IPEDS unit id {unit} resolves to {len(items)} Wikidata items "
                    f"({', '.join(f'{q} ({items[q]['label']})' for q in sorted(items))}). "
                    f"Refusing to pick one. Review them and pin the set in KNOWN_AMBIGUOUS, "
                    f"or fix ids.scorecardUnitId in the registry.")
            out[unit] = {"qid": sorted(qids), "label": None, "article": None, "aliases": [],
                         "ambiguous": True, "note": pinned[1]}
            continue
        qid, e = next(iter(items.items()))
        out[unit] = {"qid": qid, "label": e["label"], "article": e["article"],
                     "aliases": sorted(e["aliases"]), "ambiguous": False}
    return out


def matchable_key(name: str | None) -> str | None:
    """the_rank.norm_key(name) when the fold is specific enough to claim a row, else None.

        'University of Southern California' -> 'university southern california'
        'USC'                               -> None   (shared with south-carolina)
        'UT'                                -> None   (Texas, Tennessee, Toledo, Utah...)
    """
    key = the_rank.norm_key(name)
    return key if len(key.split()) >= MIN_CANDIDATE_TOKENS else None


def candidates(entry: dict) -> list[tuple[str, str]]:
    """[(kind, name)] for one Wikidata item, most authoritative first. Empty when ambiguous."""
    if entry.get("ambiguous"):
        return []
    out = []
    if entry.get("label"):
        out.append(("label", entry["label"]))
    if entry.get("article"):
        out.append(("sitelink", entry["article"]))
    out += [("alias", a) for a in entry.get("aliases") or []]
    return out


# ---------- the join ----------

def derive(programs, wikidata: dict, rows: list[dict], *, reviewed=REVIEWED) -> tuple[dict, list[dict]]:
    """(alias table, per-program report). The alias table holds only matched programs."""
    by_key, by_slug = {}, {}
    for r in rows:
        by_key[r["nameKey"]] = r
        by_slug[r["theSlug"]] = r

    aliases, report = {}, []
    for p in programs:
        slug = p["slug"]
        unit = str((p.get("ids") or {}).get("scorecardUnitId") or "")
        entry = wikidata.get(unit) or {}
        rec = {"slug": slug, "name": p.get("name"), "unitId": unit, "qid": entry.get("qid")}

        hand = reviewed.get(slug)
        if hand:
            row = by_slug.get(hand[0])
            if row is None:
                rec.update(outcome="reviewed-missing-row", theSlug=hand[0], note=hand[1])
                report.append(rec)
                continue
            aliases[slug] = {"theSlug": row["theSlug"], "name": row["name"],
                             "evidence": "reviewed", "note": hand[1]}
            rec.update(outcome="reviewed", theSlug=row["theSlug"], usRank=row["usRank"], note=hand[1])
            report.append(rec)
            continue

        if not unit:
            rec["outcome"] = "no-unit-id"
            report.append(rec)
            continue
        if not entry:
            rec["outcome"] = "no-wikidata-item"
            report.append(rec)
            continue
        if entry.get("ambiguous"):
            rec.update(outcome="ambiguous-unit-id", note=entry.get("note"))
            report.append(rec)
            continue

        hits = collections.defaultdict(list)
        for kind, name in candidates(entry):
            key = matchable_key(name)
            if key is None:
                continue  # an acronym; see MIN_CANDIDATE_TOKENS
            row = by_key.get(key)
            if row:
                hits[row["theSlug"]].append({"kind": kind, "name": name})
        if not hits:
            rec["outcome"] = "unranked"
            report.append(rec)
            continue
        if len(hits) > 1:
            # Two different THE rows answer to this one item's names. Always a bad Wikidata alias
            # (Florida State carries "University of Florida"); never guessed at, always hand-pinned.
            rec.update(outcome="ambiguous-name", matches={k: v for k, v in hits.items()})
            report.append(rec)
            continue
        the_slug, evidence = next(iter(hits.items()))
        row, kinds = by_slug[the_slug], {e["kind"] for e in evidence}
        tag = "auto-alias-only" if kinds == {"alias"} else "auto"
        aliases[slug] = {"theSlug": row["theSlug"], "name": row["name"], "evidence": tag,
                         "matchedOn": evidence[0]["name"]}
        rec.update(outcome=tag, theSlug=the_slug, usRank=row["usRank"], evidence=evidence)
        report.append(rec)

    return dict(sorted(aliases.items())), report


def conflicts(aliases: dict) -> dict:
    """{theSlug: [slug, ...]} for any THE row claimed by more than one program. Must be empty."""
    by_row = collections.defaultdict(list)
    for slug, a in aliases.items():
        by_row[a["theSlug"]].append(slug)
    return {k: v for k, v in by_row.items() if len(v) > 1}


# ---------- main ----------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asset", default=ASSET_PATH, help="the committed parsed table")
    ap.add_argument("--out", default=ALIAS_PATH, help="where to write the alias table")
    ap.add_argument("--json", help="write the full per-program report here, misses included")
    ap.add_argument("--dry-run", action="store_true", help="print the join and write nothing")
    ap.add_argument("--max-age-hours", type=float, default=24.0,
                    help="reuse a cached SPARQL response younger than this (0 forces live)")
    args = ap.parse_args(argv)

    asset = common.read_json(args.asset)
    if not asset or not asset.get("rows"):
        print(f"no ranking asset at {args.asset}; run tools/the_rank_check.py --refetch first",
              file=sys.stderr)
        return 2
    rows = asset["rows"]

    reg = common.load_registry()
    programs = list(common.iter_programs(reg))
    unit_ids = sorted({str((p.get("ids") or {}).get("scorecardUnitId")) for p in programs
                       if (p.get("ids") or {}).get("scorecardUnitId")})
    print(f"{len(programs)} programs, {len(unit_ids)} unit ids, {len(rows)} ranked rows")

    try:
        bindings = sparql(unit_ids, max_age_hours=args.max_age_hours or None)
    except common.FetchError as e:
        print(f"Wikidata query failed: {e}", file=sys.stderr)
        return 2
    try:
        wikidata = group_items(bindings)
    except AmbiguousUnitId as e:
        print("\n*** AMBIGUOUS IPEDS UNIT ID -- refusing to derive the alias table ***",
              file=sys.stderr)
        print(e, file=sys.stderr)
        return 1
    print(f"{len(wikidata)} unit ids resolved to a Wikidata item "
          f"({sum(1 for e in wikidata.values() if e.get('ambiguous'))} pinned ambiguous)")

    aliases, report = derive(programs, wikidata, rows)
    by_outcome = collections.Counter(r["outcome"] for r in report)

    for r in report:
        if r["outcome"] in ("auto", "unranked"):
            continue
        detail = r.get("note") or json.dumps(r.get("matches") or r.get("evidence") or {}, ensure_ascii=False)
        print(f"  {r['slug']:22} {r['outcome']:20} {r.get('theSlug') or '':44} {detail[:100]}")

    clash = conflicts(aliases)
    used = {a["theSlug"] for a in aliases.values()}
    print()
    print("summary:", ", ".join(f"{k} {v}" for k, v in sorted(by_outcome.items())))
    print(f"  ranked {len(aliases)}, N/A {len(programs) - len(aliases)}, "
          f"THE rows unused {len(rows) - len(used)}")
    problems = []
    if clash:
        problems.append(f"THE rows claimed twice: {clash}")
    for r in report:
        if r["outcome"] in ("ambiguous-name", "reviewed-missing-row", "no-unit-id", "no-wikidata-item"):
            problems.append(f"{r['slug']}: {r['outcome']}")
    for line in problems:
        print(f"  PROBLEM {line}")

    if args.json:
        common.write_json(args.json, report)
    if args.dry_run:
        print("\n--dry-run: alias table not written")
        return 1 if problems else 0

    out = {
        "tool": "tools/the_rank_derive.py",
        "derivedAt": common.now_iso(),
        "asset": os.path.relpath(args.asset, ROOT).replace(os.sep, "/"),
        "rankLabel": asset.get("rankLabel"),
        "rankYear": asset.get("rankYear"),
        "programs": len(programs),
        "ranked": len(aliases),
        "evidenceCounts": dict(sorted(collections.Counter(
            a["evidence"] for a in aliases.values()).items())),
        "aliases": aliases,
    }
    common.write_json(args.out, out)
    print(f"wrote {args.out} ({len(aliases)} aliases)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
