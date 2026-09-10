"""Offline audit of the registry's College Scorecard match for every program.

Reads only public/data/registry.json and the committed programs/<slug>/sources/scorecard.json,
makes no request and writes nothing outside --json. It catches the failure mode behind issue #48:
registry_builder.match_scorecard picks the Scorecard row with the highest token overlap against
the institution name, so a flagship whose legal name diverges from its common name can be matched
to a branch campus, or to an unrelated school whose name happens to contain the common name.

    python tools/registry_check.py                    # every onboarded program
    python tools/registry_check.py --slug lsu,penn-state
    python tools/registry_check.py --json report.json --verbose
    python tools/registry_check.py --max-suspects 0   # exit 1 on any unaccepted suspect

Classes: duplicate-unit-id | state-mismatch | city-mismatch | name-drift | no-registry-location | ok

duplicate-unit-id and state-mismatch are hard signals and are never silenced by ACCEPTED.
no-registry-location is reported but never counts as a suspect: with no registry city or state
there is nothing to compare the Scorecard row against, so it is a gap, not a finding.

When data/scorecard-bulk.json is present, every suspect is offered the best same-state
alternative unit id, ranked by registry-city match first and name overlap second.
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import common  # noqa: E402
from collect.registry_builder import tokens  # noqa: E402

BULK_PATH = os.path.join(ROOT, "data", "scorecard-bulk.json")

# Name overlap below this counts as name-drift. Deliberately far under match_scorecard's own
# accept threshold: this is a "these are not the same school" alarm, not a match-quality score.
NAME_DRIFT_BELOW = 0.2

HARD_CLASSES = ("duplicate-unit-id", "state-mismatch")

# The 27 variances reviewed by hand during the issue #48 audit, each confirmed to be a naming
# difference rather than a wrong campus. Keyed by slug: (Scorecard city reviewed, reason).
#
# The city is pinned rather than the slug blanket-accepted, and that matters: before the fix,
# `minnesota` pointed at Rasmussen University in St. Cloud, so a slug-level allowlist entry for
# its Falcon Heights / Minneapolis variance would have hidden the very bug this tool exists to
# find. Pinning means the acceptance lapses the moment the row moves to a different town.
# A city of None accepts name-drift only. Acceptance never suppresses duplicate-unit-id or
# state-mismatch, since no spelling of a city name explains either.
ACCEPTED = {
    # --- suburb, township or legal-city naming: the campus is right, the town name differs ---
    "rutgers": ("New Brunswick", "Scorecard names the New Brunswick campus; the fields sit in Piscataway."),
    "harvard": ("Cambridge", "Scorecard uses Cambridge; the registry uses the Boston metro."),
    "boston-college": ("Chestnut Hill", "Chestnut Hill is the village inside Newton holding the campus."),
    "binghamton": ("Vestal", "The Binghamton campus is physically in Vestal."),
    "samford": ("Birmingham", "Homewood is the incorporated suburb of Birmingham holding the campus."),
    "umbc": ("Baltimore", "Catonsville is the unincorporated area inside Baltimore County."),
    "oakland": ("Rochester Hills", "Rochester Hills split from Rochester; both name the same campus."),
    "charleston-southern": ("Charleston", "The campus is in North Charleston, filed by Scorecard as Charleston."),
    "st-johns": ("Queens", "Jamaica is the Queens neighbourhood the campus sits in."),
    "richmond": ("University of Richmond", "Scorecard's city is the literal postal place name."),
    "alcorn-state": ("Alcorn State", "Scorecard's city is the campus post office, not Lorman."),
    "minnesota": ("Minneapolis", "Registry says Falcon Heights, the suburb holding part of Twin Cities."),
    "gardner-webb": ("Boiling Springs", "Registry city is a typo, Boilings Springs for Boiling Springs."),
    "fairleigh-dickinson": ("Teaneck", "Metropolitan campus is correct; the registry's Madison is the wrong half."),
    "virginia-tech": (None, "Legal name Virginia Polytechnic Institute and State University shares few tokens."),
    # --- Main Campus is the Scorecard's ordinary naming for a flagship, not a warning sign.
    # These agreed on city when reviewed and so raise nothing today; they are kept as the record
    # of what the audit cleared, and --verbose lists any entry that has stopped flagging. ---
    "ohio-state": ("Columbus", "Main Campus suffix only; city agrees."),
    "bowling-green": ("Bowling Green", "Main Campus suffix only; city agrees."),
    "oklahoma-state": ("Stillwater", "Main Campus suffix only; city agrees."),
    "cincinnati": ("Cincinnati", "Main Campus suffix only; city agrees."),
    "new-mexico": ("Albuquerque", "Main Campus suffix only; city agrees."),
    "purdue": ("West Lafayette", "Main Campus suffix only; city agrees."),
    "ohio-university": ("Athens", "Main Campus suffix only; city agrees."),
    "akron": ("Akron", "Main Campus suffix only; city agrees."),
    "wright-state": ("Dayton", "Main Campus suffix only; city agrees."),
    "new-mexico-state": ("Las Cruces", "Main Campus suffix only; city agrees."),
    "north-dakota-state": ("Fargo", "Main Campus suffix only; city agrees."),
    "arizona-state": ("Tempe", "Campus Immersion is ASU's Tempe campus, 64,674 undergrads; correct."),
}

SAINT_PREFIX = re.compile(r"\bst\.?\s+")
PARENTHETICAL = re.compile(r"\s*\(.*?\)")
PUNCT = re.compile("[.,'’\\-/]")


def norm_city(s: str | None) -> str:
    """'St. Cloud' -> 'saint cloud'; 'Boston (Allston)' -> 'boston'. For comparison only."""
    s = common.strip_accents(s or "").lower()
    s = PARENTHETICAL.sub("", s)
    s = SAINT_PREFIX.sub("saint ", s)
    s = PUNCT.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def overlap(a: str | None, b: str | None) -> float:
    """Jaccard over registry_builder's own name tokens, so a low score means the matcher
    accepted a pair it should not have."""
    ta, tb = tokens(a or ""), tokens(b or "")
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def load_bulk() -> list[dict]:
    bulk = common.read_json(BULK_PATH, {}) or {}
    return bulk.get("results") or []


def suggest(program: dict, bulk: list[dict]) -> dict | None:
    """Best same-state row for a suspect: registry-city match first, then name overlap, then size."""
    loc = program.get("location") or {}
    state, city = loc.get("state"), norm_city(loc.get("city"))
    if not state or not bulk:
        return None
    current = (program.get("ids") or {}).get("scorecardUnitId")
    best, best_key = None, None
    for row in bulk:
        if row.get("school.state") != state or row.get("id") == current:
            continue
        key = (
            1 if city and norm_city(row.get("school.city")) == city else 0,
            round(overlap(program.get("name"), row.get("school.name")), 4),
            row.get("latest.student.size") or 0,
        )
        if best_key is None or key > best_key:
            best, best_key = row, key
    if best is None or best_key[:2] == (0, 0.0):
        return None
    return {
        "unitId": best["id"],
        "name": best.get("school.name"),
        "city": best.get("school.city"),
        "undergrads": best.get("latest.student.size"),
        "cityMatch": bool(best_key[0]),
        "nameOverlap": best_key[1],
    }


def check(program: dict, dup_slugs: dict) -> dict:
    slug = program["slug"]
    loc = program.get("location") or {}
    unit_id = (program.get("ids") or {}).get("scorecardUnitId")
    data = (common.load_source(slug, "scorecard") or {}).get("data") or {}
    out = {
        "slug": slug,
        "unitId": unit_id,
        "registryName": program.get("name"),
        "registryCity": loc.get("city"),
        "registryState": loc.get("state"),
        "scorecardName": data.get("name"),
        "scorecardCity": data.get("city"),
        "scorecardState": data.get("state"),
        "nameOverlap": round(overlap(program.get("name"), data.get("name")), 3),
        "classes": [],
    }
    if unit_id in dup_slugs:
        out["classes"].append("duplicate-unit-id")
        out["sharedWith"] = [s for s in dup_slugs[unit_id] if s != slug]
    if not data:
        out["classes"].append("no-scorecard-source")
    elif not loc.get("city") or not loc.get("state"):
        out["classes"].append("no-registry-location")
    else:
        if data.get("state") and data["state"] != loc["state"]:
            out["classes"].append("state-mismatch")
        if data.get("city") and norm_city(data["city"]) != norm_city(loc["city"]):
            out["classes"].append("city-mismatch")
    if data and out["nameOverlap"] < NAME_DRIFT_BELOW:
        out["classes"].append("name-drift")

    pinned_city, reason = ACCEPTED.get(slug, (None, None))
    accepted_for = []
    if reason:
        for c in out["classes"]:
            if c in HARD_CLASSES:
                continue
            if c == "city-mismatch" and norm_city(data.get("city")) != norm_city(pinned_city):
                continue  # the row moved somewhere the audit never reviewed: still a suspect
            accepted_for.append(c)
    out["suspectClasses"] = [
        c for c in out["classes"] if c not in accepted_for and c != "no-registry-location"
    ]
    if accepted_for:
        out["accepted"] = reason
        out["acceptedClasses"] = accepted_for
    if not out["classes"]:
        out["classes"] = ["ok"]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", help="comma-separated slugs (default: every onboarded program)")
    ap.add_argument("--max-suspects", type=int, default=None,
                    help="exit 1 when more than this many unaccepted suspects remain")
    ap.add_argument("--json", help="write the per-program report here")
    ap.add_argument("--verbose", action="store_true",
                    help="print accepted variances, unchecked programs and idle ACCEPTED entries")
    args = ap.parse_args(argv)

    reg = common.load_registry()
    everyone = list(common.iter_programs(reg))
    # Duplicates are always computed over the whole registry: --slug must not hide a collision
    # with a program outside the selection.
    by_unit = collections.defaultdict(list)
    for p in everyone:
        unit_id = (p.get("ids") or {}).get("scorecardUnitId")
        if unit_id:
            by_unit[unit_id].append(p["slug"])
    dup_slugs = {k: v for k, v in by_unit.items() if len(v) > 1}

    if args.slug:
        programs = [common.get_program(s.strip(), reg) for s in args.slug.split(",")]
    else:
        programs = everyone
    results = [check(p, dup_slugs) for p in programs]

    suspects = [r for r in results if r["suspectClasses"]]
    if suspects:
        bulk = load_bulk()
        by_slug = {p["slug"]: p for p in programs}
        for r in suspects:
            s = suggest(by_slug[r["slug"]], bulk)
            if s:
                r["suggestion"] = s

    for r in results:
        if r["suspectClasses"]:
            print(f"{r['slug']:24} {','.join(r['suspectClasses']):34} "
                  f"registry={r['registryCity']}, {r['registryState']} != "
                  f"scorecard={r['scorecardCity']}, {r['scorecardState']} "
                  f"[{r['unitId']}] {r['scorecardName']}")
            if r.get("sharedWith"):
                print(f"{'':24}   unit id also used by: {', '.join(r['sharedWith'])}")
            if r.get("suggestion"):
                s = r["suggestion"]
                # Without a city match this is only the nearest name in the same state, and when
                # the registry city is itself a suburb that can be the wrong campus. Say so.
                lead = "suggest" if s["cityMatch"] else "weak guess, no city match:"
                print(f"{'':24}   {lead} {s['unitId']}: {s['name']} ({s['city']}, "
                      f"{s['undergrads']} undergrads, overlap {s['nameOverlap']})")
        elif args.verbose and r.get("accepted"):
            print(f"{r['slug']:24} {'accepted:' + ','.join(r['acceptedClasses']):34} {r['accepted']}")
        elif args.verbose and "no-registry-location" in r["classes"]:
            print(f"{r['slug']:24} {'no-registry-location':34} "
                  f"nothing to check against; scorecard says {r['scorecardCity']}, {r['scorecardState']}")

    by_class = collections.Counter(c for r in results for c in r["classes"])
    print()
    print("summary:", ", ".join(f"{k} {v}" for k, v in sorted(by_class.items())), f"(of {len(results)})")
    unchecked = [r["slug"] for r in results if "no-registry-location" in r["classes"]]
    if unchecked:
        print(f"  no registry location, not checked: {', '.join(unchecked)}")
    print(f"  unaccepted suspects: {len(suspects)}")

    if args.verbose:
        seen = {r["slug"] for r in results}
        stale = [s for s in ACCEPTED if s in seen and not any(
            r["slug"] == s and r.get("accepted") for r in results)]
        if stale:
            print(f"  reviewed entries raising nothing today: {', '.join(sorted(stale))}")

    if args.json:
        common.write_json(args.json, results)
    if args.max_suspects is not None and len(suspects) > args.max_suspects:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
