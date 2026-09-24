# CollegeDash local data guide

All paths below are relative to the selected checkout. Read JSON using `encoding="utf-8"`; Windows' default text encoding cannot decode every school name. Discover current counts and years from files rather than assuming the example snapshot remains current.

## Files and envelopes

| File | Shape and use |
|---|---|
| `public/data/programs/index.json` | Object with `updated`, `season`, and `programs` list; search the full list first. |
| `public/data/programs/<slug>.json` | One profile; select named sections/fields and `_build` metadata. |
| `public/data/commitments/index.json` | Object with `updated` and `commitments` list; use for discovery and counts. Aggregate records omit detailed `sources` and `clubInfo`; retrieve the matching profile commitment for source citations. |
| `public/data/camps/index.json` | Object with `updated`, `window`, `counts`, and `camps` list; inspect dates and precision before claiming availability. |
| `public/data/trends/index.json` | Precomputed feeder data for D1, D2 and D3 (#315, #327): `updated`, `format` (`"records"`), `divisions`, `commitDivisions` (D2/D3 commits are null: not collected), `season`, `pastSeasons`, `commitStatuses`, `columns`, `coverage` (with `byDivision`), `programs` (each with `division`), `programIds`, `clubs`, `schools`, `records`. See Feeder counts. |

The program index supplies `slug`, `name`, `shortName`, `nickname`, `searchNames`, `division`, `conference`, `city`, `state`, `region`, `ownership`, `undergradEnrollment`, `admissionRate`, `sat25`, `sat75`, `academicRank`, `academicRankTied`, `tuitionInState`, `tuitionOutOfState`, `headCoach`, `coachSince`, `nationalTitles`, `collegeCups`, `currentSeason`, `lastSeason`, `rpiHistory`, `rosterSize`, `commitmentsByYear`, `fallClimate`, `completeness`, `stale`, `builtAt`, and `failed`. Select only fields needed for the question; omit `tags`.

Profile research sections include `school`, `academicRank`, `climate`, `program`, `seasons`, `roster`, `rosterHistory`, `schedule`, `commitments`, `news`, `camps`, `links`, and `_build`. Never emit `curated`. These are section names for local parsing, not permission to print entire sections. Inspect keys and project relevant nested fields.

## Meaning and provenance

- Rates such as `admissionRate` are fractions: display 0.12 as 12%. Costs are USD; distinguish in-state/out-of-state tuition, cost of attendance, and average net price. Do not present averages as a personalized aid estimate.
- `academicRank` is a ranking position (lower is better); profile metadata identifies year and source. Climate `avgHighF`/`avgLowF` use Fahrenheit; `precipIn` uses inches. Normals describe a historical climate period, not a forecast.
- `roster.season` identifies the current stored roster; `players` is the list. `rosterHistory` is keyed by year. Class labels and roster positions can be ambiguous; do not silently equate mixed positions or fifth-year status with eligibility or openings.
- Profile `seasons` are newest-first, but select by explicit `year` and check `inProgress` rather than relying on list position. Never compare an in-progress record with a full season without qualifying that difference.
- A season with `ncaaResultFrom` has an `ncaaResult` taken from the program's Honors lists (College Cup, runner-up, title) because its season-table row gave a lesser finish or none; `ncaaResultFrom.seasonTable` is the row's own text (null = the row was blank). Treat it as derived from Honors, not as the table's record.
- A season row with a `record` also carries `gamesPlayed` (games with a result, exhibitions excluded) and `recordSource`: `schedule` (the athletics schedule, preferred), `wikipedia`, `wikipedia-swapped` (Wikipedia with its overall and conference columns swapped back), or `ncaa-rpi-d1` (the NCAA RPI table, Division I games only, so it can be a few games short of the overall record). `confRecord` comes from the same source. Qualify a finished season with `gamesPlayed` under 10 as short (2020, early seasons). A missing record means no source gave one, not 0-0-0.
- `_build.builtAt` and index `updated` are build times. `_build.sections`, `stale`, `failed`, and `skipped` describe build coverage and problems. Section `_meta` commonly includes `source`, `url`, and `asOf`; inspect actual fields. `asOf` can mean collection time, not reporting year. If reporting year is absent, say so.
- Source links come from relevant section `_meta.url`, program `links`, player `bioUrl`, commitment `sources`, or news/camp URLs. Select actual source fields; do not synthesize a missing source URL. A dashboard link can use `https://college.nextonetwo.com/#/p/<slug>` but represents the live site, which may differ from the local snapshot.
- Commitments use `gradYear`, `pos`, `college`, `status`, `confidence`, `flags`, `sources`, `announced`, `announcedSource`, `approxDate`, and `firstSeen`. Approximate and first-seen dates are not announcement dates. A missing record is not proof that no commitment exists; sparse D2 coverage needs explicit qualification.
- RPI applies to D1. Use only already-published per-program summaries in index/profile fields, never raw RPI tables. Attribute historical data to Chris Thomas, *RPI for Division I Women's Soccer*. From 2010 the historical ranks are restated under the no-overtime rule and 2024 formula; 2007-2009 use their era's rules. Do not label those restated values contemporary NCAA rankings.

## Feeder counts

Read the file's `format`, `divisions`, `commitDivisions`, `season`, `pastSeasons`, `columns` and `coverage` first. If `format` is not `"records"`, the file is an older shape; say so rather than guessing.

- **Totals and coverage** come from `programs` (per program: `division`, `current`, `past`, `commits`, `clubKnown`, `schoolKnown`, each array ordered by `columns`) and `coverage` (all divisions together, and per division in `coverage.byDivision`). Never count people by counting records: a person with neither a known club nor a matched school has no record, so records undercount every total.
- **Directories:** `programIds` is a list of slugs; `clubs` and `schools` hold parallel lists (`id`, `name`, `state`, and for schools `city`), plus `unmatched` (club positions whose spelling is not a reviewed club) and `aka` (position → extra search keys). `schools` is null when high schools are not matched in the build.
- **Records** are four parallel integer lists, `records.p`, `.s`, `.c`, `.h`: one record per counted person who has a known club or a matched high school. `p` is a position in `programIds`; `s` is the status (0 `current`, 1 `past`, 2 `commits`); `c` a position in `clubs.id` and `h` in `schools.id`, -1 where unknown. Records are sorted by (p, s, c, h); their order carries no meaning.
- **Adding them up:** filter records, then count by status. Several clubs (or schools, or programs) are combined with OR within their list and AND across the lists: "players from club A or B who went to high school X, at program P" counts the records with `c` in {A, B}, `h` = X and `p` = P. A former player's record carries both her club and her high school; report what the question needs, not the linked pair for a named person.
- `current`: people on that program's current roster. `past`: distinct people in stored past rosters who are not on that program's current roster. `commits`: qualifying commitments, separate from roster populations; never add them to roster counts.
- Commits are collected for `commitDivisions` only; elsewhere a program's `commits` is null and it has no commit records: report "not collected", never 0. High-school commitment counts are not supported: report not available.
- Counts across programs are program-person relationships, not necessarily distinct people across the whole sport (transfers can appear at more than one program).
- Report known-club/known-school coverage with denominators, per division. Missing feeder identity is not evidence of no relationship. Rank roster relationships by current plus past, using current as a tie-breaker; keep commits separate. The site shows past and commit counts of 1 or 2 as "1-2" when two or more of club, high school and program are chosen, and exact counts for one; the file is exact.

```python
trends = load("public/data/trends/index.json")
assert trends.get("format") == "records"
r, clubs = trends["records"], trends["clubs"]["id"]
want = {clubs.index(c) for c in ("mountain-view-los-altos-sc",) if c in clubs}  # club ids chosen from trends["clubs"]
by_program = {}
for p, s, c in zip(r["p"], r["s"], r["c"]):
    if c in want:
        row = by_program.setdefault(trends["programIds"][p], [0, 0, 0])
        row[s] += 1
ranked = sorted(by_program.items(), key=lambda kv: (-(kv[1][0] + kv[1][1]), -kv[1][0], kv[0]))
```

## Reproducible projections

These are Python examples to adapt in a read-only execution tool. Pass user choices as data, not interpolated executable code. `checkout` must be the already-resolved path; `slug` must be selected from the index.

```python
import json
from pathlib import Path

checkout = Path(r"D:\Projects\CollegeDash")  # replace with resolved checkout
def load(relative):
    return json.loads((checkout / relative).read_text(encoding="utf-8"))

index = load("public/data/programs/index.json")
population = [p for p in index["programs"] if p.get("division") == "D1"
              and p.get("state") in {"CA", "OR", "WA"}]
missing = sum(p.get("tuitionOutOfState") is None for p in population)
matches = [p for p in population if p.get("tuitionOutOfState") is not None
           and p["tuitionOutOfState"] < 40000]
fields = ("slug", "shortName", "state", "division", "tuitionOutOfState")
result = {
    "updated": index.get("updated"),
    "criteria": "D1; CA/OR/WA; out-of-state tuition below USD 40,000",
    "eligibleBeforeCost": len(population), "missingCost": missing,
    "matchCount": len(matches),
    "programs": [{k: p.get(k) for k in fields}
                 for p in sorted(matches, key=lambda p: (p["tuitionOutOfState"], p["slug"]))],
}
print(json.dumps(result, ensure_ascii=True))
```

For a roster comparison, project player evidence instead of dumping the profile:

```python
slug = "stanford"
assert slug in {p["slug"] for p in index["programs"]}
profile = load(f"public/data/programs/{slug}.json")
roster = profile.get("roster") or {}
build = profile.get("_build") or {}
meta = roster.get("_meta") or {}
fields = ("name", "pos", "classLabel", "classCode", "bioUrl")
result = {
    "slug": slug, "season": roster.get("season"), "reportedCount": roster.get("count"),
    "builtAt": build.get("builtAt"), "stale": build.get("stale"),
    "failed": [{k: item.get(k) for k in ("collector", "at")}
               for item in build.get("failed", []) if isinstance(item, dict)],
    "collectedAt": meta.get("asOf"),
    "sourceUrl": meta.get("url") or (profile.get("links") or {}).get("roster"),
    "players": [{k: p.get(k) for k in fields} for p in roster.get("players", [])],
}
print(json.dumps(result, ensure_ascii=True))
```

These examples omit `curated`, `tags`, player biographies, and social accounts by construction. For other questions create similarly narrow projections before emitting evidence. If a file/section is missing, malformed, or disagrees with another snapshot, report that limitation instead of filling values or silently dropping the school.
