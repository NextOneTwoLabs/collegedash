"""Audit the committed Times Higher Education ranking asset and the alias table built from it.

Offline by default: reads only data/the-us-rankings-2026.json and data/the-rank-aliases.json,
makes no request and writes nothing outside --json.

    python tools/the_rank_check.py                      # the committed pair, offline
    python tools/the_rank_check.py --json report.json
    python tools/the_rank_check.py --refetch            # re-fetch, re-parse, diff against the asset
    python tools/the_rank_check.py --refetch --write-asset data/the-us-rankings-2027.json

Exit 0 when everything agrees, 1 when a finding needs a human, 2 on a usage or fetch error.
Deliberately NOT wired into refresh.yml: the ranking is published once a year, the asset is
committed, and refreshing it is a deliberate act that should show its diff to a person first.

Offline findings: missing-asset | missing-aliases | bad-row | duplicate-the-slug | unknown-the-slug |
  name-drift | duplicate-claim | bad-evidence | year-mismatch | count-mismatch

--refetch findings add: rank-change | new-row | dropped-row | alias-row-gone | alias-name-changed |
  newly-matchable

WHY THE PINNED NAME IS THE ROT DETECTOR. The obvious check -- fetch each alias's
/world-university-rankings/<theSlug> URL and see whether it still exists -- does not work. THE's
Drupal redirects an unknown slug with a 301 to a generic ranking page rather than returning 404, so
every alias would look healthy forever. Two slugs already carry Drupal dedup suffixes
(rutgers-university-new-brunswick-0, colorado-state-university-fort-collins-0) precisely because the
un-suffixed forms are taken. So each alias pins (theSlug, name) and rot is found only by parsing a
fresh copy of the table and diffing it against the committed one. This tool never fetches a slug URL.
"""

from __future__ import annotations

import argparse
import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collect import common  # noqa: E402
from collect import the_rank  # noqa: E402

ASSET_PATH = os.path.join(ROOT, "data", "the-us-rankings-2026.json")
ALIAS_PATH = os.path.join(ROOT, "data", "the-rank-aliases.json")
EVIDENCE_TAGS = ("auto", "auto-alias-only", "reviewed")


def finding(kind: str, detail: str, **extra) -> dict:
    return {"finding": kind, "detail": detail, **extra}


# ---------- offline ----------

def check_asset(asset: dict) -> list[dict]:
    """The asset has to be internally sound before the alias table can be checked against it."""
    out, seen_slug, seen_key = [], {}, {}
    for i, r in enumerate(asset.get("rows") or []):
        where = f"row {i} ({r.get('name') or r.get('theSlug')!r})"
        if not r.get("theSlug") or not r.get("name"):
            out.append(finding("bad-row", f"{where}: missing theSlug or name"))
            continue
        if not isinstance(r.get("usRank"), int) or r["usRank"] < 1:
            out.append(finding("bad-row", f"{where}: usRank {r.get('usRank')!r} is not a rank",
                               theSlug=r["theSlug"]))
        if not isinstance(r.get("tied"), bool):
            out.append(finding("bad-row", f"{where}: tied {r.get('tied')!r} is not a boolean",
                               theSlug=r["theSlug"]))
        if r["theSlug"] in seen_slug:
            out.append(finding("duplicate-the-slug",
                               f"{r['theSlug']} appears twice ({seen_slug[r['theSlug']]}, {r['name']})",
                               theSlug=r["theSlug"]))
        seen_slug[r["theSlug"]] = r["name"]
        key = r.get("nameKey") or the_rank.norm_key(r["name"])
        if key in seen_key:
            # Two rows folding to one key would make the derivation's exact-equality join ambiguous.
            out.append(finding("bad-row", f"{where}: nameKey {key!r} collides with {seen_key[key]!r}",
                               theSlug=r["theSlug"]))
        seen_key[key] = r["name"]
    if not asset.get("rows"):
        out.append(finding("missing-asset", "the asset holds no rows"))
    return out


def check_aliases(asset: dict, table: dict) -> list[dict]:
    """Every alias must name a row that is in the asset, exactly once, under the pinned name.

    Rows are read with .get and the keyless ones skipped. check_asset has already reported those as
    bad-row; indexing them here used to raise KeyError before a single finding reached stdout, so
    the diagnostic vanished exactly on the malformed asset it exists to describe.
    """
    out = []
    rows = {r["theSlug"]: r for r in asset.get("rows") or [] if r.get("theSlug")}
    aliases = table.get("aliases") or {}

    if table.get("rankYear") != asset.get("rankYear"):
        out.append(finding("year-mismatch",
                           f"alias table says rankYear {table.get('rankYear')!r}, "
                           f"asset says {asset.get('rankYear')!r}"))
    if table.get("ranked") is not None and table["ranked"] != len(aliases):
        out.append(finding("count-mismatch",
                           f"alias table header says ranked {table['ranked']}, holds {len(aliases)}"))

    claims = collections.defaultdict(list)
    for slug, a in sorted(aliases.items()):
        claims[a.get("theSlug")].append(slug)
        if a.get("evidence") not in EVIDENCE_TAGS:
            out.append(finding("bad-evidence", f"{slug}: evidence {a.get('evidence')!r} is not one of "
                                               f"{', '.join(EVIDENCE_TAGS)}", slug=slug))
        elif a["evidence"] == "reviewed" and not a.get("note"):
            out.append(finding("bad-evidence", f"{slug}: a reviewed alias must carry a note", slug=slug))
        row = rows.get(a.get("theSlug"))
        if row is None:
            out.append(finding("unknown-the-slug",
                               f"{slug}: theSlug {a.get('theSlug')!r} is not in the asset", slug=slug))
            continue
        if row.get("name") != a.get("name"):
            # The pin is the whole rot detector; a changed name means the row is not the row that
            # was reviewed, whatever the slug still says.
            out.append(finding("name-drift",
                               f"{slug}: pinned name {a.get('name')!r} but the asset row "
                               f"{a['theSlug']} now reads {row.get('name')!r}",
                               slug=slug, theSlug=a["theSlug"]))
    for the_slug, slugs in sorted(claims.items()):
        if len(slugs) > 1:
            out.append(finding("duplicate-claim",
                               f"{the_slug} is claimed by {', '.join(slugs)}", theSlug=the_slug))
    return out


# ---------- --refetch ----------

def diff_tables(asset: dict, fresh_rows: list[dict], table: dict, registry: dict | None) -> list[dict]:
    """What changed between the committed asset and a freshly parsed copy of the page.

    Like check_aliases, this reads rows with .get and skips the ones with no theSlug: a malformed
    asset is check_asset's finding to report, not a KeyError that swallows the whole report.
    """
    out = []
    old = {r["theSlug"]: r for r in asset.get("rows") or [] if r.get("theSlug")}
    new = {r["theSlug"]: r for r in fresh_rows if r.get("theSlug")}
    aliases = table.get("aliases") or {}

    for the_slug, r in sorted(new.items()):
        o = old.get(the_slug)
        if o is None:
            out.append(finding("new-row", f"{the_slug}: {r.get('name')} at "
                                          f"{'=' if r.get('tied') else ''}{r.get('usRank')}",
                               theSlug=the_slug))
        elif (o.get("usRank"), o.get("tied")) != (r.get("usRank"), r.get("tied")):
            out.append(finding("rank-change",
                               f"{the_slug}: {'=' if o.get('tied') else ''}{o.get('usRank')} -> "
                               f"{'=' if r.get('tied') else ''}{r.get('usRank')}", theSlug=the_slug))
    for the_slug, o in sorted(old.items()):
        if the_slug not in new:
            out.append(finding("dropped-row", f"{the_slug}: {o.get('name')} was "
                                              f"{'=' if o.get('tied') else ''}{o.get('usRank')}",
                               theSlug=the_slug))

    for slug, a in sorted(aliases.items()):
        r = new.get(a.get("theSlug"))
        if r is None:
            out.append(finding("alias-row-gone",
                               f"{slug}: {a.get('theSlug')!r} is no longer in the table; "
                               f"re-run tools/the_rank_derive.py", slug=slug))
        elif r.get("name") != a.get("name"):
            out.append(finding("alias-name-changed",
                               f"{slug}: pinned {a.get('name')!r}, the page now says {r.get('name')!r}",
                               slug=slug, theSlug=a["theSlug"]))

    if registry is not None:
        # A prompt, not a join: any row nobody claims whose name now folds onto a program's own name
        # is worth putting through tools/the_rank_derive.py. It is deliberately name-based and
        # deliberately not trusted -- nothing here edits the alias table.
        claimed = {a.get("theSlug") for a in aliases.values()}
        by_name = {}
        for p in common.iter_programs(registry):
            by_name.setdefault(the_rank.norm_key(p.get("name")), p["slug"])
        for the_slug, r in sorted(new.items()):
            if the_slug in claimed:
                continue
            slug = by_name.get(r.get("nameKey") or the_rank.norm_key(r.get("name")))
            if slug:
                out.append(finding("newly-matchable",
                                   f"{the_slug} ({r.get('name')}) now folds onto program {slug}; "
                                   f"re-run tools/the_rank_derive.py to confirm through Wikidata",
                                   slug=slug, theSlug=the_slug))
    return out


# ---------- main ----------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asset", default=ASSET_PATH, help="the committed parsed table")
    ap.add_argument("--aliases", default=ALIAS_PATH, help="the committed alias table")
    ap.add_argument("--refetch", action="store_true",
                    help="re-fetch and re-parse the page, then diff it against the asset")
    ap.add_argument("--write-asset", metavar="PATH",
                    help="with --refetch, write the freshly parsed table here (never over --asset "
                         "by accident: name the file you mean)")
    ap.add_argument("--json", help="write the findings here")
    ap.add_argument("--quiet", action="store_true", help="print findings only, no summary lines")
    args = ap.parse_args(argv)

    asset = common.read_json(args.asset)
    if not asset:
        print(f"missing ranking asset: {args.asset}", file=sys.stderr)
        return 2
    table = common.read_json(args.aliases)
    if not table:
        print(f"missing alias table: {args.aliases}", file=sys.stderr)
        return 2

    findings = check_asset(asset) + check_aliases(asset, table)
    rows, aliases = asset.get("rows") or [], table.get("aliases") or {}
    if not args.quiet:
        counts = collections.Counter(a.get("evidence") for a in aliases.values())
        print(f"{args.asset}: {len(rows)} rows, {sum(1 for r in rows if r.get('tied'))} tied, "
              f"{sum(1 for r in rows if r.get('overallBanded'))} with a banded overall score")
        print(f"{args.aliases}: {len(aliases)} ranked programs "
              f"({', '.join(f'{k} {v}' for k, v in sorted(counts.items()))}), "
              f"{len(rows) - len({a.get('theSlug') for a in aliases.values()})} rows unused")

    if args.refetch:
        try:
            html, meta = the_rank.fetch_table()
            fresh = the_rank.parse_table(html)
        except (common.FetchError, ValueError) as e:
            print(f"refetch failed: {type(e).__name__}: {e}", file=sys.stderr)
            return 2
        if not args.quiet:
            print(f"refetched {the_rank.SOURCE_URL}: {len(fresh['rows'])} rows "
                  f"(committed asset has {len(rows)}, fetched {meta.get('fetchedAt')})")
        try:
            registry = common.load_registry()
        except (FileNotFoundError, OSError):
            registry = None
        findings += diff_tables(asset, fresh["rows"], table, registry)
        if args.write_asset:
            common.write_json(args.write_asset,
                              the_rank.build_asset(html, fetched_at=meta.get("fetchedAt")))
            print(f"wrote {args.write_asset}")

    for f in findings:
        print(f"  {f['finding']:20} {f['detail']}")
    by_kind = collections.Counter(f["finding"] for f in findings)
    if not args.quiet:
        print()
        print("findings:", ", ".join(f"{k} {v}" for k, v in sorted(by_kind.items())) or "none")
    if args.json:
        common.write_json(args.json, findings)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
