# #315: clubs and high schools (Pipelines) for D2 and D3: status, and what is left

Author: Jueying. Measured offline from committed data on `origin/main` 60bc94e17 (refresh of 2026-10-21); nothing
fetched. Status: for review. **Main finding: the feature asked for in #315 already shipped.** This file records the
evidence and proposes what is left. It is not a plan for new building.

## What is already on main
The plan and its review are on the issue: Dilu's plan, the owner's decisions of 2026-09-24, Huatuo's C1-C3, and
Dilu's adoption of them. Then:
- **#330** (`c25ae562b`), phase 1: Pipelines covers D2 and D3 with that day's club table; high schools are matched
  against NCES for every division.
- **#336** (`4926222cb`), phase 2, option A: the D2/D3 club aliases and new clubs, reviewed. Refined later by #339,
  #347 and #385.
- **#414 / #411, #438 / #416:** commits read "Not collected" outside the commit divisions, sorted last, and a commit
  count outside D1 is described as partial.
- **#343 / #327:** the index is in the records format. #467 is the later page flow.

On main today:
- `public/data/trends/index.json` has `divisions: ["D1","D2","D3"]`, `commitDivisions: ["D1"]` and
  `coverage.byDivision`, and holds 1,011 programs (349 D1, 251 D2, 411 D3).
- `public/index.html` reads `commitDivisions` and shows "Not collected" for D2/D3 commits.
- `tests/trends_test.py` pins the 450 KB gzip budget (line 483).

## Coverage today, per division (counts of people; from the committed index and profiles)
**Current-roster fields**, from `public/data/programs/*.json`:

| field | D1 (9,555) | D2 (7,088) | D3 (10,069) |
| --- | ---: | ---: | ---: |
| hometown | 97.6% | 100.0% | 100.0% |
| high school named | 83.6% | 86.3% | 96.4% |
| club named | 30.8% | 5.3% | 9.6% |
| previous school | 19.0% | 18.9% | 4.0% |

**What the index resolves**, from `coverage.byDivision` and `records`:

| | D1 | D2 | D3 |
| --- | ---: | ---: | ---: |
| current: school matched to NCES | 54.6% | 57.0% | 68.9% |
| current: club known | 30.8% | 5.3% | 9.6% |
| ... of which a reviewed club, not `raw:` | 85.4% | 50.7% | 55.3% |
| former: club known / reviewed | 15.2% / 73.5% | 3.3% / 48.2% | 7.7% / 47.3% |
| commits | 2,350 recruits | not collected | not collected |

- **High schools carry D2/D3.** Every division has a named high school for more than 80% of current players,
  and D2/D3 match NCES at least as well as D1.
- **Clubs are thin in D2/D3 at the source.** Few D2/D3 roster pages have a Club column. The reviewed share
  (about 51% D2, 55% D3) is where option A was planned to land (51%).
- **Commits are D1 only by design** (the owner's decision 3).

**Payload:** 1,217,889 B raw and 259,634 B at gzip -9. That is 58% of the 460,800 B budget, so there is no
pressure to split the file. Brotli is not installed here, so I could not reproduce the 254 KB br figure you gave me.

## Can it be built without new collection?
It already was. Everything above comes from stored sources. Nothing left on this list needs fetching except
item 3, and I am not proposing it.

## What is left (owner decisions; no code until one is taken)
1. **Close #315** (owner). All five scope items in the issue body are delivered:
   - the coverage probe;
   - club aliases (option A);
   - D2/D3 high-school matching;
   - the index size and its delivery (one file, with a budget);
   - privacy unchanged.

   The PRs said "Part of #315" while phase 2 was open, so nothing closed the issue.
2. **Optional: a second D2/D3 club review (option B).**
   - **Today's tail**, from `data/clubs-review.json`: 1,039 unmatched keys and 2,145 occurrences in D2/D3.
   - **Names seen 2+ times:** 580, covering 78.6% of those occurrences. Only 18 have a suggested existing club,
     so most decisions are a new row (name, state, country), as before.
   - **Effect:** reviewed share rises to roughly 85-90% of D2/D3 club strings. But club-known coverage stays
     5-10% of players, so the visible gain is small.
   - **Effort:** about 4-6 h of Reviewer time. This is an estimate scaled from #315's figures, not measured.
   - **I recommend not now.** If wanted, it is a data-only PR like #336, plus `tests/clubs_alias_test.py` cases.
3. **Not proposed: D2/D3 commits.** This would need new fetching, so I am naming it rather than planning it:
   - TopDrawerSoccer team commitment tabs for 662 D2/D3 programs (one page each, each needing a `clgid` mapping
     per program);
   - or SoccerWire's commitments filtered by `college_division_committed`.

   Both need your OK, a robots check, and a coverage probe first (#315 found 3 D2 and 3 D3 records). Until then
   "Not collected" is the honest label.

## If option B is approved: changes, tests, split
- **Data only:** `data/clubs.json` gains aliases and clubs. No change to build, API or page. Divisions are already
  shown on every Pipelines result, program box suggestion and coverage line (#330, #467).
- **Tests:**
  - `tests/clubs_alias_test.py` gets one case per merge or rename the owner rules on (frozen strings, no live
    counts);
  - D1 near-miss pairs stay apart (existing suite);
  - `trends_test.py`'s budget test guards the size.

  None depends on today's date: counts are pinned only on fixtures (#508).
- **PR split:** one PR, "Part of #315". It closes the issue only if you say so.
- **Risks:** many single-occurrence names are noise (team names, a high school typed in the Club column). Those
  stay `raw:`, as for D1.

## Owner decisions
- **A.** Close #315 now? Recommended: yes.
- **B.** A second D2/D3 club review (option B, about 580 names)? Recommended: not now.
- **C.** Probe D2/D3 commitment sources (needs fetching)? Recommended: not now; "Not collected" stays.
