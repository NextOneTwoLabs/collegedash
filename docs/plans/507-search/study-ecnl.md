# ECNLDash search: a study for CollegeDash issue #507

Read-only study of `/home/user/nextonetwolabs/ecnl-dashboard` (HEAD `12182be`). Paths below are relative to that
repo unless they start with `/home/user/collegedash`. "Not found" means the thing is not in the repo.

What was read: `public/search/*.mjs` (9 modules), `search_data.py`, `docs/data-api.md` ("Search data", lines
464-725), `README.md` (Team search, Judged search queries, Search data, Search modules, The search panel: lines
402-661), the search panel block of `public/index.html` (lines 6606-8058, CSS 2132-2260, markup 2446-2481),
`tests/search/*` (judged.mjs, sets.mjs, freeze.mjs, queries.json, baselines, MANIFEST), `tests/search-*.test.mjs`,
`tests/e2e/search-panel.e2e.mjs`, `tests/netguard/netguard.mjs`, `tests/test_search_data.py` (header, budgets).

Design notes in `docs/`: only `docs/data-api.md` "Search data" (464-725). The design document, "plan v2", the
addenda and the mockups are cited all over the code ("design", "plan v2 MF3", "the mockup") but are **not in the
repo** (they live on GitHub issues #149, #156, #163, #165, #167, #168; not fetched: no network). `docs/` holds
only `data-api.md` and `showcases.md`.

---

## 1. Architecture and module boundaries

Four layers, each with its own tests:

| Layer | Where | Job |
|---|---|---|
| Offline builder | `search_data.py` (1,209 lines), run by `archive.py` after the team directory | Builds the search data files from the committed archive. No network, no clock, no locale (search_data.py:10-12). |
| Data files | `public/archive/search/core.json`, `places.json`, `games-<season>.json` | Prepared records, served as `/api/v1/search/core`, `/places`, `/games/{season}` (docs/data-api.md:26-29). Not the index. |
| Search modules | `public/search/*.mjs` (9 ES modules, ~136 KiB raw) | Pure functions: build the in-memory index, read a query, return a "slate". No DOM, storage, network or clock (search.mjs:1-2; enforced by tests/search-modules.test.mjs:41-58). |
| Page block | `public/index.html` 6606-8058 ("// ===== #165: the search panel") | Loads data, drives the staged build, draws the slate, owns the keys. "The modules draw nothing; this block draws the slate and takes the keys" (index.html:6609). |

Module boundaries (`public/search/`):

| Module | Lines | Role |
|---|---|---|
| `search.mjs` | 162 | Entry point. `startIndex` (staged build, generator, 44-64), `buildIndex` (= drain, 67), `startGames` (72-86), `search(index, query, context, options)` (103-151), `completeGames` (156-162). `SEARCH_API = 4`, `CORE_SCHEMA = 2`, `PLACES_SCHEMA = 1` (32-34). `SearchDataError` names the file (36-38). `checkContext` requires `now`, `timeZone`, `selectedSeason`, `today` (88-95). |
| `vocab.mjs` | 195 | Shared vocabulary: phrases (conferences + aliases, state names, census places, counties, reviewed aliases, field names), kind words, word-codes (`in`, `or`, `me`). `buildVocabG` 39-117, `fieldNamesG` 136-192. |
| `reader.mjs` | 255 | Reads the query once into "readings" per category (teams, events, games), keeping ambiguity, cap 4 per category (11). `readQuery` 215-255. |
| `match.mjs` | 245 | Normalising, word expansion (exact/prefix/typo), OSA edit distance, `TermList`, BM25F `Postings`, `filterScore`, `drain`, counted sorts. |
| `teams.mjs` | 351 | Teams category: one document per squad, postings, filter counts, lookups; `searchTeams`; lazy `TeamRow`. |
| `events.mjs` | 180 | Events category: conference seasons, national events, showcases; `searchEvents`. |
| `games.mjs` | 590 | Games category: per-season typed-array index, fields, pairings, head to head. Never matches words against game text (games.mjs:3-5). |
| `slate.mjs` | 132 | Section order, best match, Enter target, empty reason, coverage. |
| `links.mjs` | 30 | Every link a row opens, in the page's existing hash formats. |

The contract between modules and page: `search(index, query, ctx)` returns a **slate**
`{ query, sections:[{name, rows, total, partialOnly}], best, enter, empty, rule, coverage, gamesAsked, ended, capReached, sizes }`
(slate.mjs:128-131). Rows carry structured fields so the page never parses the debugging `why` text
(README.md:538-542; teams.mjs:317-326).

---

## 2. The search data files

### Shapes (docs/data-api.md:483-648)

- **`core.json`** (schema 2): `{schema, build, directoryBuild, activeSeason, seasons, birthYears:[lo,hi], vocab:{confAliases, states}, events:{id: [season, kind c|n|s, name, eventName, location, start, end, [divisions]]}, teams:{seasons, confs, divs, events, tiers, clubs, families, squads:[{b, c, s:[[season, teamID, name, conf, div, rank, of]...], x?, m?, mp?, e?}]}}`. Teams is the team directory verbatim plus `x` alias ids (search_data.py:736-814). Committed: 1,965 squads, 143 clubs, 81 events, 7 seasons.
- **`places.json`** (schema 1): `{schema, build, census, vocab:{fieldAliases}, counties:{geoid:[name, ST]}, places:{geoid:[name, ST, county]}, clubPlaces:{clubID:[place, county]}, eventPlaces:{eventID:[place, county]}, fields:{"name@zip":[label|null, [seasons], [numbers], place, county]}}` (search_data.py:1020-1066). Committed: 503 places, 205 counties, 947 fields.
- **`games-<season>.json`** (schema 1): `{schema, season, base, build, flights, teams, alt, fields, games:[[matchID-delta, when, flight, home, away, hs, as, hpk, apk, complex, number, flags, dest]...]}`; `when` = days from base x 10000 + HHMM; matchIDs delta-coded; trailing nulls dropped (search_data.py:49-51, 509-525; data-api.md:613-643). 2026-27 has 6,304 games.

### Sizes (measured on the committed files today, gzip level 6)

| File | Raw | Gzip | Budget (tests/test_search_data.py:169-172) |
|---|---|---|---|
| core.json | 409.1 KiB | 72.9 KiB | 120 KiB |
| places.json | 137.1 KiB | 36.3 KiB | 60 KiB |
| games-2026-27.json (active) | 486.4 KiB | 69.2 KiB | 100 KiB |
| all 7 games files | ~3.3 MiB | 567.0 KiB | 800 KiB |

First focus costs core + places, about 109 KB gzipped (README.md:598-599).

### How the refresh builds and validates them

- **Deterministic** (search_data.py:19-22): every set and dict emitted in sort order; byte-identical across processes, hash seeds and time zones (test_search_data.py class `Stability`).
- **Quiet diffs** (search_data.py:14-17; data-api.md:693-698): rows keyed by source ids, one entry per line, leading commas. A one-score refresh rewrites one line plus `build`; measured +19/-17 lines of ~7,385 on real refreshes; closed seasons byte-identical.
- **Build id**: sha256 of the file without `build`, 16 hex (search_data.py:528-534); `directoryBuild` pairs core with the directory it came from (data-api.md:501-502).
- **No silent picks**: a key mapping to two values raises `BuildError` (search_data.py:20-22, 78-79).
- **Reviewed inputs with evidence** (`public/data/field-aliases.json`, `zip-fixes.json`, `zip-place-fixes.json`, `city-counties.json`, `orphan-team-ids.json`): each entry schema-checked; a bad entry is skipped, reported and fails the run (search_data.py:154-197, 590-722).
- **Build report** to stdout only (search_data.py:1109-1117): alias candidates are listed, never merged automatically.
- **Safe write**: only changed bytes; `.tmp` first; games before core; on failure every `.tmp` removed and the run fails (search_data.py:1128-1159; data-api.md:700-706).
- **Drift check in CI**: `python archive.py --search-data --check` fails when a committed file differs from a fresh build (search_data.py:1162-1169; README.md:90).
- **Frozen test fixture**: `tests/search/fixtures/search/` is the same build from a pinned commit, with PROVENANCE (builder sha, input shas) recorded into MANIFEST (search_data.py:1197-1203; README.md:485-498). A builder or input change fails `tests/search-data.test.mjs` until the fixture is rebuilt in the same PR.
- **Python twin decoder** of the JS format (`decode_games`, search_data.py:537-559) and a JS decoder (`tests/search/search-data-format.mjs`) whose schema constants are tested equal (tests/search-data.test.mjs:216).
- **Versioning**: a change that renames, removes or retypes a field bumps `schema`; the page refuses a schema it does not know (data-api.md:469-472).

---

## 3. Query parsing

### Normalising (match.mjs:38-60)
Lower case, accents dropped (only when non-ASCII), `.` and apostrophes dropped, dashes unified; words split on
non-alphanumerics. `NOISE` words ignored (`ecnl, girls, team, the, and, of, based, from`, 52). `AGE_WORD` tokens are
ages, never name words (54). `NAME_ALIAS` both ways: `saint/st`, `mount/mt` (56). Club initials of 3+ words
("United Futbol Academy" -> `ufa`, 62-65).

### Tokens (reader.mjs:18-83), in order
- Season `2024-25`, `24-25`: kept if in the archive, else `unknownSeason` (25-29).
- Date `YYYY-MM-DD` or `M/D` (games only, 30).
- Age group `U15`, `GU15`, `U17/U18` pair (32).
- Birth year `G2011`, `2011G`, band `2009/10`, `G11` (33-44); a bare year is two seasons or a birth year (37, 89-93).
- `field 15` number (45); two-digit birth year inside the catalog range (46).
- Remaining words go through the vocabulary, **longest phrase first** at each position; every phrase of that
  length is a role (52-66). Kind words (`playoffs`, `finals`, `showcase`, `standings`) are their own role (54;
  vocab.mjs:22-25). Two-letter state codes: strict when nothing else names a team or place, else soft; `in`, `or`,
  `me` only as the whole query (63, 71-81; vocab.mjs:28).
- Reviewed aliases with evidence: `la` (Los Angeles + the all-caps word LA in names, never Louisiana), `richmond`
  (Richmond VA only) (vocab.mjs:10-19).
- `vs`, `v`, `@`, `versus` split two sides; a season on one side applies to both (reader.mjs:12, 215-229).

### Readings and hard filters (reader.mjs:87-212)
Every combination of roles (each segment: one of its roles, or name words) is a reading, at most 256 combinations
(95-104), sorted by more filter words, longer phrase, role priority (182), de-duplicated and capped at 4 per category
(`capped`, 208-212). Each category chooses the readings it can use (`forTeams` 185-190, `forEvents` 191-198,
`forGames` 202-206).

**Filters are hard**: a reading's season, age group, birth year and conference are AND filters applied in
`anchorOf` (teams.mjs:114-131) and in the event loop (events.mjs:96-106). Places are OR among themselves; a state
next to a place narrows it (AND) ("Redmond WA", reader.mjs:152-174). A conference conflict kills the reading (175).
Impossible filters produce a typed empty reason instead of results: `season-not-in-archive`, `no-such-age-group`
(teams.mjs:143-147; events.mjs:81-83). An age group with no season means the **selected** season (teams.mjs:116;
events.mjs:99).

Filter words still count in scoring: each scores as an exact match in its own pseudo-field with the rarity of the
documents that pass it (`filterScore`, match.mjs:238-243; teams.mjs:168-173).

---

## 4. Matching and ranking

### Expansion (match.mjs:146-168)
A query word expands into index terms by class: **exact 1.0, prefix 0.7, typo 0.4** (15).
- Prefix: the last word typed at any length; other words from 3 letters (152).
- Typo: letters-only words from 4 letters, within 1 edit (2 from 8 letters), OSA so a swap counts 1 (79-99).
- Initials match exactly or by prefix, never by typo (155-158).
- Refinement A: a word that is itself a known term anywhere is never read as a typo (159; `known` built in search.mjs:56-57).
- Cheap pre-filters before the edit distance: first-two-letters test and a letter-multiset surplus (132-144); terms
  bucketed by length (`TermList`, 102-124); per-search cache of expansions (147-150; search.mjs:107-109).

### Scoring: BM25F, one saturation per query word (match.mjs:212-235)
For each word, its best expansion in each field is weighted and summed, then saturated once with `K1 = 1.2`; length
normalisation off (`B = 0`, tuned on the judged set, 32-36).
- Team fields: name 1.0, club 0.9, older name 0.6, place 0.4 (teams.mjs:7).
- Event fields: name 1.0, event name 0.8, location 0.5, tier 0.3; each field holds only words no higher field holds (events.mjs:9, 14-20).
- A place word read as a place never matches the city text field (teams.mjs:153-155).

### Order
- Teams (teams.mjs:242-265): conference table rows first in table order; direct before nearby; strong before weak
  birth-year match; score; age-pair; whole-title match; plays this season; newest season; then club, title, age.
- Events (events.mjs:144-161): direct before nearby; score; selected season first; nearest to today; age oldest first.
- Games (games.mjs:140-142, 343-349): upcoming soonest first, then newest first, undated last.
- **Partial matches** only when no category matches every word, and never on a <3-letter prefix (search.mjs:142-149; teams.mjs:150-152); ordered by words matched, class, rarity.

---

## 5. Result sections and links

- Sections: `teams`, `events`, `games`; first-show sizes 8 / 6 / 6, then "Show all", then 50 at a time (slate.mjs:7-8; index.html:6657).
- **Section order** is a first-row-wins table (slate.mjs:14-57): 1 conference + age group -> Events, Teams, Games;
  2 kind word -> Events, Games, Teams; 3 vs / field / date -> Games first; 4 only a place -> sections with a result
  in the place itself before ones holding only nearby results; 5 otherwise the section whose top row is strongest
  (class, then more filter words), Games always after a section with results.
- **Best match** (slate.mjs:65-74): an exact whole-name match, promoted only when no other section's first row is
  also exact ("texas" keeps the Texas teams first rather than promoting the Texas conference). Never a game.
- **Enter** target (slate.mjs:111-118): the best match, else the first eligible row; withheld while a games-first query's files are still loading so the first row never flips.
- **Empty** (slate.mjs:120-127): reason `no-match`, `no-full-match` (partial), `season-not-in-archive`, `no-such-age-group`, `games-loading`.
- **Coverage** per season: `ready | loading | not-loaded | on-request | missing | failed` (slate.mjs:9-12) - "not searchable yet" is never shown as "no match".
- **Links** (links.mjs): exactly the page's existing hash formats (team Overview / season tab, conference standings, national stage, showcase, game with `&match=`). An age-less conference row carries one link per age group (`hrefs`). Every href is verified by the judged set's `destinationProblem` (tests/search/judged.mjs:575-635) and every game's link by `tests/search-game-links.test.mjs`.
- Rows are lazy: `TeamRow` / `GameRow` compute links and labels in getters, so a keystroke matching hundreds of squads builds only what is drawn (teams.mjs:293-349; games.mjs:91-127).

---

## 6. The panel UI

**Where it sits.** One box in the header on every page (index.html:2446-2457); `/` focuses it from anywhere
(8153-8156). The landing page has no box of its own: its hero shows a "Search teams, clubs, places..." button that
calls `focusTeamSearch()` (8354), which focuses the header box, or on a phone opens the full-screen sheet (4628-4633).

**ARIA pattern: combobox with a grid popup** (index.html:6610-6611; markup 2451-2453, 2477):
- `input role="combobox" aria-autocomplete="list" aria-haspopup="grid" aria-controls="usearchList" aria-expanded`.
- `ul#usearchList role="grid"`, always in the DOM (so `aria-controls` never points at nothing, 6795); rows hold
  `gridcell`s; the best match is a labelled `rowgroup` inside the grid; focus stays in the box and
  `aria-activedescendant` names the active cell (7832-7842).
- A grid rather than a listbox because a team line is a row of age-group **chips** (several destinations per row).
- An **action bar** outside the grid holds real links (Overview, season tab, "Open in <view>", Head to head), so
  new-tab, copy-link and middle-click work (2478; 7833-7871).
- `role="status" aria-live="polite"` region speaks once per settled result (2480; 7728).

**Keyboard** (index.html:7945-7993): Up/Down move by row to the nearest column; Left/Right/Home/End only after a
vertical move (until then they move the caret); Enter opens the active cell or toggles a fold; Shift+Enter opens a
team's season tab; Esc clears the text, then closes; Tab from the box goes to the action bar's links, then out;
Ctrl/Cmd-click and middle-click open a new tab; hover moves the active cell after a 250 ms rest, never on touch
(7939-7943, 8013-8019). Input is debounced 60 ms (8040).

**Phone layout** (`isPhone` = width <= 768, index.html:3424): the header box hides and a search icon shows; it opens
the popover as a full-screen `role="dialog" aria-modal="true"` sheet with its own input and Cancel (2466-2475,
6749-6751; CSS index.html:2118-2123, `.usearch-slot { display: none }`, `.usearch-pop { inset: 0 }`). Tab is trapped in the sheet
(8025-8033); Cancel returns focus to the header button (6783). Chips are 28 px tall on desktop, 36 px on the phone
(WCAG 2.5.8, 2156, 2197). The e2e test checks no horizontal scroll at 390 px.

**States** (index.html:6786-6822, 7085-7117):
- Loading: "Getting search ready..." with a progress bar driven by build stages, example chips and skeleton rows.
- Fewer than 2 characters: tips with example queries (`SX_TIPS`, 6662).
- Empty: "No team or event matches 'x'" + examples; "No 2030-31 season in this archive. Search covers 2020-21 to
  2026-27."; "No such age group in that season"; "Loading 2024-25 games..."; "Couldn't load ... games" + Try again.
- Partial: "Nothing matches every word of 'x'. These results match some of the words." plus a Partial pill per row.
- Version mismatch / unknown schema: "Search was updated while this page was open" + Reload button, `role="alert"`, never searches.
- Live mode `?live=1`: search off, says so.

**Page rules** R1-R12 and G1-G12 are written at the top of the block (6612-6649) and each is pinned by a test in
`tests/search-panel.test.mjs`. Examples: R1 group by club, one line per team name; R4 the Enter target is always
visible; R6 Nearby pill + one sub-heading per section; R12 the empty texts.

**The painter** (#167, index.html:7665-7733): a keystroke draws the status, best match and the first 16 cells in
its own task; after the next frame the rest is appended (never re-rendered); a deferred Games section then runs in its
own task. The grid is `aria-busy` meanwhile; any key, click or hover first flushes what is pending. The settled panel
is byte-identical to a one-go draw (test at search-panel.test.mjs:1213).

---

## 7. Loading strategy

1. **Idle preload of code**: at the first idle moment the 9 modules are `modulepreload`ed (no data, no API request);
   skipped on Save-Data and in live mode (index.html:8050-8058).
2. **First focus loads data**: core + places in parallel, 2 requests (6672-6691, 6720-6737). Memoised: a 404 is kept
   for the page; a refusal (429/4xx) is kept a minute; a 5xx/network error is forgotten so the next focus retries.
3. **Chunked build**: `startIndex(data, 50)` is a generator; `sxDrive` yields (`scheduler.yield()`, else a
   `MessageChannel` post, never `setTimeout(0)` which clamps to 4 ms) whenever the current task plus the slowest step
   so far would pass 40 ms (6693-6715). Events are the last step so a visitor never sees teams without events
   (search.mjs:40-43). Parsing `core.json` is the one task that cannot be split (README.md:603).
4. **After ready**: exactly 1 request for the active season's games, built in steps of 150 (6730, 7119-7144).
5. **Typing makes no request.** A season the query names is fetched once the box has been still for 500 ms; earlier
   meetings or a field's earlier games only when their Load cell is pressed (at most 6 seasons, 2 at a time).
6. **Warm-up**: once games are in, a few searches and three detached draws run, a task each, to warm the JIT; it stops
   as soon as the visitor types (7735-7758).
7. **Versioning**: the page expects `SEARCH_API` 4 (6652, 6727); any other value, or a `SearchDataError` from an
   unknown schema, shows the reload note. Cache: core/places/active season `no-cache` with a validator; closed
   seasons cached a day (data-api.md:718-725).

---

## 8. The judged query set

**File**: `tests/search/queries.json`, schema 1 (validated by `checkSchema`, judged.mjs:133-183):
- `context`: frozen `now`, `timeZone`, `selectedSeason` (the clock is injected; a canary proves it, judged.mjs:430-442).
- `groups`: nine, fixed order: team-names, typos, events, collisions, not-ignored, cities, fields, games-h2h, nothing (judged.mjs:32). At least 4 per group; 55-70 queries in total (140-141). Today 65.
- `decisions`: D1-D14, the owner's rulings in words (e.g. D2 city covers its county, labelled nearby; D3 LA; D11 birth-year rule; D13 renamed squads).
- `vocabulary`: field aliases and counties used by the judgements.
- Each query: `id` (`T01`), `group`, `q`, `stability` (`frozen` | `closed` | `live`), `sections` (expected order),
  `mustShow`, `mustNever`, `top` (expected top rows per section), `exact`, `order` (before/after), `useful` (what
  counts as a useful first result), `cites`, `decision`, `note`, `place`.
- Refs are typed facts, never engine output: `team {season, teamID}`, `club {clubID}` (+`current`), `conference`,
  `event`, `game`, `field`, `h2h`, `pairing`, `empty {reason}`; modifiers `within`, `partial`, `nearby`, `duplicate`.
- **MF10**: a `live` query may carry only `sections`, `mustShow` and `mustNever` - exact tops and orders only on
  frozen or closed-season data (judged.mjs:155). Closed-season facts the queries cite are compared with the live
  archive on every run so a refresh can't break CI (judged.mjs:692-715).

**Scoring** (`evaluate`, judged.mjs:494-572; `summarise`, 643-671): per query, checks mustShow, mustNever, section
order, relative order, first useful result (is `enter` a `useful` ref?), exact top, reciprocal rank per section cut at
the first-show size, and **wrong destinations** (every href resolves to a real page). Each check is `pass`, `fail` or
`unsupported` (the engine can't show that kind), folded per query. The summary gives per-group and overall pass/fail
counts, first-useful rate, section-agreement rate, MRR, wrong destinations, must-never hits, reading-cap hits.

**Measure first, then compare**: the old search was vendored into `tests/search/engines/today.js` and run through an
adapter (judged.mjs:275-333) to record `baseline/today.json`; the new modules record `baseline/modules.json`. Both are
re-run in CI and must equal their record query by query (search-judged.test.mjs:160-167, 305-313).

| | today (old search) | modules (new) |
|---|---|---|
| first result useful | 41 / 65 (0.63) | 65 / 65 |
| pass / fail / unsupported | 9 / 27 / 29 | 65 / 0 / 0 |
| must-never hits | 13 | 0 |
| must-show missing | 7 | 0 |
| wrong destinations | 0 | 0 |
| section order agrees (supported) | 0.31 | 1.0 |

**Pass criteria** for the new engine (search-judged.test.mjs:315-342): first-useful better than today overall and no
group worse; 0 wrong destinations; 0 must-never hits; section order >= 90%; no reading cap hit; no check that passes
today may fail now; a `KNOWN_FAILING` list with reasons (empty). The old search was later retired explicitly
(`MANIFEST.retired`, legacy markers checked absent, frozen copy checksum-pinned, judged.mjs:407-428).

---

## 9. Performance and test practices

**Work counts, not timing, are the guard** (tests/search-modules.test.mjs:396-523):
- `search(..., { stats })` counts `termsVisited, osaCells, postingsVisited, docsScored, rowsSorted, sortCompares,
  gamesVisited, teamSearches`. Every judged query is typed one character at a time (980 keystrokes); each keystroke's
  counts are weighted into estimated ns with weights fitted on one machine (406).
- `RECORDED = { keystrokes: 980, max: 2509890, maxAt: 'so', p95: 551530 }` is pinned **exactly** (416, 436): any
  change in work must be re-measured, recorded and explained in the PR. p95 must stay under a phone ceiling of
  16 ms / 15 (408); the worst may not exceed 2x its record (420).
- The build's work is pinned exactly too: `units 24069, sorts 759, sortRows 3047, sortCompares 12402, normalised 7358,
  words 8706`, and the same for any step size (504-521). Counting is free when `stats` is absent (match.mjs:172-175).
- **Wall-clock only as a loose backstop**: no keystroke over 20 ms (fastest of 3 runs), cold import + build under
  200 ms of **main-thread CPU** (`process.threadCpuUsage`, fastest of up to 7 fresh processes) (481-498). The comment
  at 459-463 explains why: the clock missed a planted quadratic sort; the counts catch it every time.
- No `localeCompare` during the build (the first call starts ICU, 6-9 ms; vocab.mjs:34-36; test 620).
- Size budgets in Python (test_search_data.py:169-172).

**Network guards**:
- `tests/netguard/netguard.mjs` is preloaded into every Node test (`node --import`): it refuses non-loopback
  sockets, TLS, DNS and fetch, records each attempt, and exits 97 even if the code swallowed the error (1-49). A
  Python twin `sitecustomize.py` does the same.
- The panel test asserts exact fetch counts: 2 on first focus, then exactly 1 games file, none per keystroke, none on
  the second focus; drawing makes no request (search-panel.test.mjs:192, 882, 1076).
- The e2e test (tests/e2e/search-panel.e2e.mjs) runs Chromium against `proxy_server.py --offline`, aborts and counts
  every request not to the loopback port, and asserts nothing off-machine was answered (42-54, 126-130). Not in CI
  (needs Playwright); run for panel PRs and recorded in the PR.

**Other practices**:
- Purity scan of the modules (no `document`, `window`, storage, `fetch`, `Date.now`, `new Date()`, `Math.random`, dynamic import) (search-modules.test.mjs:41-58).
- The panel test slices the real block out of `index.html` by its markers and runs it in a tiny fake DOM on an index
  built by the real modules from the frozen fixture; expectations come from the slate, fixture or a stated rule,
  never from the code under test (search-panel.test.mjs:1-20). `ECNL_TEST_HTML` points it at a mutated copy for
  mutation checks.
- Staged build == one-shot build, slates compared "rows in full" over every judged keystroke at n = 1, 7, 50, 150 (search-modules.test.mjs:554).
- Deferred Games == immediate Games on 2,068 probe queries (README.md:527; `reviewSet`, tests/search/sets.mjs:20-35).
- Time-zone independence: the whole set under `TZ=UTC` and `TZ=Pacific/Kiritimati` (search-judged.test.mjs:144-153, 350-353).
- All checksums over LF text so CRLF checkouts pass (judged.mjs:19-22).

**Phone speed is about drawing**: in the repo this shows as the painter (paint the first 16 cells, append the rest
after a frame, Games in its own task) and lazy row/group building (index.html:6650-6651, 7665-7733). The worst
keystroke ("so", ~500 squads) is admitted to be over the phone ceiling in the work model, "measured on a throttled
browser after merge, Q12" (search-modules.test.mjs:417-419). The throttled-phone measurements themselves: not found
in the repo.

**Mockups**: referenced (index.html:2244; search-panel.test.mjs:1204 `MOCKUP_STATES`), files not found in the repo.

---

## 10. What CollegeDash can reuse

Context from a brief read-only look at CollegeDash (not studied in depth here):
- It already has one header search box on every page: `input#q type=search role=combobox` with a `role=listbox`
  popup `#qList` (/home/user/collegedash/public/index.html:897-908), matching programs only (`searchMatches`, 1169).
- `boot()` awaits `loadIndex()`, which fetches `/api/v1/programs` before the first route (1628, 1715-1718), so the
  1,011-program list (D1 349, D2 251, D3 411; fields include `name, shortName, nickname, searchNames, conference,
  division, city, state, region`) is already in memory on the landing page. `public/data/list/index.json` is 670 KiB raw.
- Other data that a universal box could answer: `public/data/camps/index.json` (53 KiB), `commitments/index.json`
  (2.7 MB), `trends/index.json` (1.2 MB), `fit/index.json` (178 KiB). Whether they belong in the box is an owner call.
- It already has `tests/netguard/netguard.mjs` and `sitecustomize.py`, and search tests (`header_search`,
  `place_search`, `search_short_forms`, `search_help`, `d2_/d3_search_names`).

### Reusable as-is (copy, rename, little or no change)
- **`match.mjs` core**: `normalize`, `words`, `osa`, `typoMax/typoAllowed`, `TermList`, `expand` (exact/prefix/typo
  classes, initials never by typo, known words never as typos), `postingsG`/`Postings` BM25F with one saturation per
  word, `filterScore`, `drain`, `counted/sortCounted`. Drop the ECNL bits inside (`NOISE` words, `AGE_WORD`,
  `teamTitle`, `agePairOf/ageOk`).
- **Staged build pattern**: generator stages + `drain` + `sxDrive`/`sxYield` (index.html:6693-6715) with the 40 ms rule.
- **API/schema versioning**: `SEARCH_API` + per-file `schema` + `SearchDataError` + the "updated while open, Reload" note.
- **The judged-set harness** (`tests/search/judged.mjs`): LF checksums, `stable()`, `makeClock`/canary, `evaluate`,
  `summarise`, baseline record/compare, the `unsupported` status and the pass criteria. The ref kinds and
  `destinationProblem` must be rewritten (see below) but the machinery carries over.
- **Work-count budget test** (search-modules.test.mjs:396-523): stats object, keystroke replay of every judged query,
  weights, pinned exact record, phone ceiling, CPU-time cold build backstop. Weights must be refitted on CollegeDash data.
- **Purity scan** of the modules (search-modules.test.mjs:41-58).
- **Fetch-count assertions** and the e2e "abort everything off-machine" context (e2e/search-panel.e2e.mjs:42-54).
- **Builder hygiene**: deterministic output, build id = sha of content, write-if-changed via `.tmp`, `--check` drift
  test in CI, size budgets, frozen fixture + PROVENANCE.

### Needs adapting
- **Vocabulary** (`vocab.mjs`): replace with CollegeDash roles: division (`D1`, `D2`, `D3`, "Division I"), conference
  names and short forms, state names/codes (the state-code rules and `WORD_CODES` port directly), cities, mascots /
  nicknames, `searchNames` short forms ("FSU"), regions. Alias table with evidence per entry is a good pattern to keep.
- **Reader** (`reader.mjs`): keep the shape (tokens -> segments by longest phrase -> readings, cap 4, hard filters,
  typed empty reasons). Replace the token regexes: ECNL seasons/age groups/birth years/dates become, e.g., division
  and grad/season year if CollegeDash needs them. Drop `vs` unless a head-to-head is wanted.
- **Categories**: `teams.mjs` becomes a programs category (fields: name, shortName/searchNames, nickname, city/state;
  filters: division, conference, state); `events.mjs`'s "a filtered table as a result" idea maps to a conference
  (or conference x division) row. Further sections (camps, clubs/pipelines, coaches) only if the owner wants them.
- **Slate**: section kinds, sizes and the first-row-wins order table must be redrawn for CollegeDash's kinds; the best
  match / Enter / partial / empty-reason logic is generic.
- **Links** (`links.mjs`): CollegeDash hash routes (`#/p/<slug>`, `#/programs`, `#/camps`, `#/trends`...), and a
  CollegeDash `destinationProblem`.
- **Panel**: CollegeDash uses combobox + listbox today. ECNL's grid exists because a row holds several chips; if
  CollegeDash rows are one destination each, combobox + listbox is simpler and still correct. Keep: box keeps focus +
  `aria-activedescendant`, action bar of real links, polite live region spoken once, phone full-screen dialog with Tab
  trap and Cancel, 36 px targets, the painter, typed empty states with examples.
- **Loading**: programs are already loaded at boot, so a programs-only box needs no first-focus fetch at all; the
  "load at first focus" rule applies to any extra kinds (camps, commitments...) or a purpose-built search file.
- **Builder**: a Python step in CollegeDash's refresh (`build.py`/collect) that writes a purpose-built search file
  rather than reusing the 670 KiB list file; budget and drift check as ECNL does.
- **Judged set content**: new groups, decisions and queries from CollegeDash facts (programs by slug, conferences,
  divisions), frozen fixture, and a baseline of today's CollegeDash search recorded first.

### ECNL-specific (do not port)
- `games.mjs` entirely: per-season typed-array games index, fields (`name@zip`), pairings, head to head, Load cells, coverage states for per-season files.
- The census places pipeline in `places.json` (ZCTA tables, counties, "nearby"): only if CollegeDash wants county-level "nearby"; its current place search is by state/city fields.
- Squad continuity across seasons (`maybe`/`maybePrev`, #107), club families, age pairs (#173), orphan team ids (#179), TGS `dest` codes, `undateBorrowedDates`, field aliases and zip fixes.
- The `la` / `richmond` aliases, kind words (playoffs, finals, showcase, standings), `NOISE` = `ecnl, girls...`.
- Vendoring and retiring "today's" engine is ECNL's history; the pattern (freeze the old engine, measure, then retire it with a checked marker list) is reusable.

---

## Process lessons visible in the repo
- Small PRs, each closing one sub-issue and referencing the parent as "Part of #149" (decision D10, queries.json).
- Owner decisions recorded as numbered facts (D1-D14) and cited by the queries that test them.
- Every change to module behaviour re-records the baseline in the same PR and explains the diff (README.md:455-456).
- Every visible-panel PR runs the e2e test locally and records the result in the PR (README.md:656-661).
