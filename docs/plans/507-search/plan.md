# #507 plan: a universal search box on the landing page (phase 1), revision 4

Author: Chitu (Opus). Revision 4 answers Huatuo's fourth review (`review-r4.md`). The "Changes since review" section at the end says how each point was handled. No code is written until a reviewer (Bianque or Huatuo) approves this plan and the owner has ruled on the decisions in section 9 that gate the first PR.

Sources. This was a read-only study: no repository file was changed and nothing was fetched.
- CollegeDash at code commit `df9417725`, data refresh `a83a32086` (2026-10-20T16:09:38Z).
  - main is now at `365ce91ec`. Its two newer commits (#510, #509) touch none of the files this plan cites by line, except `collect/common.py`. `public/index.html` and `build.py` are byte-identical at both commits. The plan names `collect/common.py` as the new home of a shared email pattern (PR 2) and cites one function in it, `read_json`, with its line numbers at both commits. The data is still `a83a32086`: `public/data/programs/index.json` on main has the fixture's sha256.
- ECNLDash at `12182be`.
- The "Search phase 1" write-up the owner linked (claude.ai/artifact/7SqSb5KKmsFcdunuY3y1oG), as summarised in #507's brief. I did not re-check its own numbers (902 ≠ 901, 193 ms), because the rules forbid fetching.
- The tools installed in this environment (section 7.5), re-checked for revision 4: Playwright 1.56.1 under `/opt/node-tools/node_modules`, Chromium 141 under `/opt/pw-browsers`, and Node 22.22.0 first on `PATH` (`/opt/node22/bin`). `/usr/local/bin/node` is a link to Node 20.20.0, and 21.7.3 is at `/opt/node21`. There is no Node 24 on `PATH` or under `/opt`, `/usr` or `/root`.

Line numbers are from those commits. CollegeDash paths are relative to the repo root, and ECNLDash paths start with `ecnl:`. A bare line number is in CollegeDash's `public/index.html`. Revision 4 re-read every line it newly cites, and recomputed every fixture count it states with read-only scripts in `scratchpad/search507/chitu-r4/`.

## 0. Summary

- **What we build.** A real search box in the Home hero, between the line under the heading and the three options.
  - One box gives up to five answer kinds in sections: Programs, Lists (a filtered Programs list), Conferences, Camps and Coaches.
  - Nobody picks a category first.
  - The division is shown on every program.
- **Facts beat guesses.** A division, conference, state, region, size, tuition, climate or RPI word typed in the query is a hard filter. So:
  - "d3 ohio" never shows Ohio State;
  - "d3 in ohio" never reads "in" as Indiana;
  - "division 1 west" never shows Western Michigan.
- **Two exact matching rules** (sections 4.1 and 5.2):
  - **"St." that means State.** On a program whose own name says "State" and has no Saint or St, an NCAA "St." and the "Saint" the build makes from it are both read as State. So "saint" never finds Ohio State or Cal State Fullerton, and "ohio st" still finds Ohio State.
  - **When words give a conference row.** Each word must be a whole word of the conference's name (only a last word of 4 or more letters may be a prefix), and shared words such as "university" must be in the name too. So "university of michigan" shows no Michigan Intercollegiate Athletic Association, "st" shows no conference, and "new england" still shows NESCAC.
- **One rule for "too broad".** A query made only of shared words (such as "university", "college", "soccer", "the") or the words "conference" or "coach" is too broad (section 4.1).
  - The panel says so and shows a capped list of the program rows those words find, if any, and no other section. Enter does nothing until the visitor picks a row.
  - A single letter, a short prefix such as "st", or a shared word still being typed ("universit") is not too broad: Enter opens the first row, as it does today.
  - There is no count threshold, so a refresh can't change which queries are too broad.
- **Search data.** One purpose-built file, `public/data/search/index.json`.
  - `build()` writes it after the camps index, from the files this same run has just written.
  - `validate()` checks it.
  - When a refresh fails, the refresh's fallback that publishes only the collected sources restores it like every other build output.
  - Only checks that a code bug can fail may block the publish. Content problems are skipped with one `::warning` each (section 3.3).
  - It is served at `/api/v1/search` and fetched at the box's first focus. After that, typing makes no requests.
- **Measure first.** PR 1 freezes a judged set of 93 queries, built from the 79-query draft and fitted to phase 1, together with a frozen fixture and today's search as the baseline.
  - **Today is two frozen boxes, chosen by a fixed rule.** A query with the word "camp" or "camps" is scored against the ID Camps box; every other query against the header box as it works on the Programs page (section 7.3).
  - The draft scored the header box only: 21 answers, 11 partial, 2 wrong and 45 nothing. The camps rows will change when PR 1 re-measures under the rule.
- **Small PRs, one at a time.** There are twelve: 1, 2, 3, 4, 5, 6a, 6b, 6c, 6d, 6e, 7 and 8.
  - The visible ones need an owner-approved mockup first. PR 4 has its own; PRs 6a-6e, 7 and 8 share one set.
- **Exact numbers are pinned only on frozen test data.** Every test says which data it reads (section 7.7). CI never compares anything with today's `public/data` or with git history.
- **Speed is measured locally with tools already installed.** The browser check (PR 6b) runs offline here with the installed Playwright 1.56.1 and Chromium 141, on Node 22.22.0. It decides whether ECNL's painter and the step-by-step index build come in (section 7.5). CI runs the suites on Node 24, which this machine doesn't have, so a PR run here states its versions.
- **It reverses an owner decision.** On 2026-10-02 the owner ruled "no box on Home" (#465, commit `453203860`), and tests pin it. The owner confirms the reversal on #507 before any PR (decision A).
- **What the owner rules on, and when** (section 9 has each decision with its recommendation):
  - before any PR: A;
  - before PR 1: C, D, I, L, M, S and U, and the status of the draft's C01-C19;
  - before PR 4: H; before PR 5: Q; before the PR 6 mockups: B; before PR 6b: R; before PR 6e: K; after PR 8: J;
  - team defaults E, F, G, N, O, P and T stand unless the owner overrides them;
  - three small issues outside #507 are recommended, none of which blocks it: a "UMass Boston" registry alias (U), a review of the build's initials rule (M), and a fix to the build's St./Saint swap (T).

## 1. Goal and scope

### Goal
A visitor lands on Home and types whatever is on their mind, for example:
- a school, mascot or conference;
- a head coach's name;
- facts such as "d3 ohio" or "small d3 under 30k";
- a camp, such as "ucla id camp".

They get the right answers in one grouped list, and typing sends no request.

### Phase 1 answer kinds (sections)

| Section | One row is | Opens | Data |
|---|---|---|---|
| Programs | one program | `#/p/<slug>`, or a tab such as `#/p/<slug>/roster` (TABS, 5506) | the search file |
| Lists | the Programs list filtered by the facts typed, unless the only fact is one conference | `#/programs?div=…&region=…&state=…&conf=…&cond=…&sort=…`, with facts only and never `q` (section 5.1) | computed from the same rows |
| Conferences | one conference in one division | `#/programs?conf=<division>:<name>&sort=name`: that conference's Programs list, written by the page's own `listHashOf` (3591-3603) | the search file |
| Camps (PR 7) | one upcoming ID camp | `#/p/<slug>/camps` | the search file (the rows the ID Camps page lists) |
| Coaches (PR 8) | a current head coach | `#/p/<slug>/staff` | the search file (the index's `headCoach`: 926 of 1,011 programs) |

**Why a conference row does not open `#/c/<name>`.** The `c` route sets the conference and clears the division, but it keeps the visitor's saved region, class, conditions and search (3794-3802). So what it opens can differ from the count on the row. A `#/programs?…` address replaces every filter, because "a missing param is the page's default" (`listStateOf`, 3604-3639; `listArrive`, 3661-3675).

**There is no single-conference list row.** It would open exactly what the conference row opens.

### Phase 1 facts (hard filters; detail in section 4)
- division, conference, state, and region ("New England" = Northeast, C10);
- size words, tuition "under/over $N", "warm" and "cold" (fall average high), and "top N RPI";
- month words and "this weekend", for camps;
- profile tab words (roster, schedule, staff/coaches, commitments, camps, climate, news), which choose the tab a program row opens.

### Read but not applied in phase 1 (named back, never silently dropped)
- colour (C06), snow (C16), religious affiliation (C18), public/private;
- majors, which are not in the data at all (C17);
- "near <city>" (C14);
- place nicknames such as NYC and Bay Area;
- other numeric conditions (admission rate, SAT, academic rank).

The panel names them back, for example "“psychology” is not in CollegeDash's data", and labels the list row partial.

### Cities in phase 1
A city name narrows nothing. It finds program rows and labels them ("in Boston, MA") inside the Programs section.

There is no city list row, because the Programs address has no city parameter. Today's `q=` place search can't stand in for one either, because it mixes name hits with place hits:
- 8 programs are in Boston: boston-university, emerson-college, emmanuel-college-ma, massachusetts-boston, northeastern, simmons, suffolk and wentworth-institute-technology;
- `q=boston` lists 9, because Boston College (Chestnut Hill) also matches by name.

That is decision S.

### Out of scope for phase 1
- **Players and commits by name.** There are 26,715 current roster rows and 3,725 commits, mostly about minors. Pipelines' stated rule is "counted, never named" (5107, 4776-4777), so a site-wide name search would expose them in a new way (decision C).
- **Assistant and former coaches.** Profiles hold 3,344 `coaches` entries and 1,444 more `supportStaff` entries; nothing outside a profile has them. Adding the coaches entries alone measured +47 KB gzipped.
- **Clubs and high schools.** Pipelines has its own boxes (4799-4807, 5231-5266), and the trends file is 259 KB gzipped.
- **The header box `#q`** on Programs, profiles and ID Camps stays as it is, and so does the Programs page's `q=`, which keeps today's matcher (section 5.7).
- **Semantic search, recent searches and other saved state.** Recent searches were turned down in #447 decision 4.

## 2. What we take from ECNLDash

### Port with little change
- **Matching core** (`ecnl:public/search/match.mjs`):
  - normalising, 38-60;
  - expansion, 146-168;
  - BM25F, 212-235;
  - `filterScore`, 238-243.

  Changes for CollegeDash:
  - Replace ECNL's NOISE words, which are dropped (`ecnl:public/search/match.mjs:52`), with CollegeDash's shared words, which are optional rather than dropped (section 4.1). Drop AGE_WORD.
  - Keep the saint/st and mount/mt twins (`ecnl:public/search/match.mjs:56`), except on a State-side program, where a "st" from an NCAA name such as "Ohio St.", and a "saint" the build made from one, are indexed as "state" (section 4.1).
  - Add CollegeDash's `&` rule ("Texas A&M" → "texas am", normText 1061-1062), and treat "and" and "&" as the same word.
  - **Weights are starting values, not settings.** ECNL tuned K1 = 1.2 and B = 0 on its own judged set ("tuned on the judged set: Y06, W03", `ecnl:public/search/match.mjs:32-36`). The class weights (exact 1.0, prefix 0.7, typo 0.4) and the field weights are ECNL's too. All of them are re-tuned on CollegeDash's set in PRs 3 and 5, and each change is recorded in `baseline/engine.json` with the reason.
- **Versioning:** `SEARCH_API`, a `schema` per file, and the "updated while open, Reload" note (`ecnl:public/search/search.mjs:32-38`; `ecnl:docs/data-api.md:469-472`).
- **Judged-set machinery** (`ecnl:tests/search/judged.mjs`):
  - the schema check, 133-183: `useful` is required on every query (153), and a live query refuses only `exact`, `top` and `order` (155);
  - `evaluate`, 494-572, with its section check at 524-532, which ignores sections that hold only partial matches (526); `destinationProblem`, 575-635; `summarise`, 643-671;
  - baseline equality (`ecnl:tests/search-judged.test.mjs:160-167`) and the pass criteria (315-342).
- **Work-count budgets** (`ecnl:tests/search-modules.test.mjs:396-523`), with the weights refitted on CollegeDash data.
- **Purity scan** (`ecnl:tests/search-modules.test.mjs:41-58`). Its banned list includes `window` and `globalThis` (43-44). `public/search.js` is a plain script with the same export wrapper as `recs.js`, which names `globalThis` (`public/recs.js:480-482`). So the ported scan removes that one wrapper, matched exactly as the file's last statement, before it scans, and a test checks that `globalThis` anywhere else is still flagged (PR 3).
- **Fetch-count assertions** (`ecnl:tests/search-panel.test.mjs:192, 882, 1076`).
- **The local browser check's network handling** (`ecnl:tests/e2e/search-panel.e2e.mjs`):
  - Playwright is not a repo dependency. It is found through `PLAYWRIGHT_MODULES`, whose default is `/opt/node-tools/node_modules/` (7-8, 24), where this environment has it installed (section 7.5);
  - Chromium starts with a dead proxy (38);
  - a context route continues only same-origin requests, and aborts and counts the rest (43-54).

  CollegeDash's version is PR 6b's committed script (section 7.5).
- **Builder habits** (`ecnl:search_data.py`):
  - offline and deterministic, 10-22;
  - a build id, 528-534;
  - write only when the bytes change, 1128-1159;
  - a frozen fixture whose source commit is recorded but not verified (1197-1203; `--commit` "recorded, not verified here", 1183).
- **Reviewed inputs, read correctly.** ECNL skips a bad entry, reports it, and still writes every file (`ecnl:search_data.py:154-197`, "…; skipped"; `ecnl:archive.py:1054-1080`, "the files are still written"). The run is marked failed, but the data is not held back.

  CollegeDash's refresh is different. When `build` raises or `validate` fails, it publishes the sources only, so none of the site's data updates (`.github/workflows/refresh.yml:485-488`). So the faithful translation is: skip the entry, print a `::warning` annotation (`common.annotate`, as `build.py:2213` does), and never fail the run (section 3.3).

### Port only if a measurement asks for it
- **The step-by-step (yielding) index build** (`ecnl:public/search/search.mjs:44-67`; `ecnl:public/index.html:6693-6715`). ECNL needed it at ECNL's scale: 24,069 build units over 1,965 squads, 81 events and the games. CollegeDash indexes 1,011 programs, 98 conference pairs and 81 camps.
  - PR 3 ships the one-shot build.
  - PR 6b's local browser check (`tools/search_browser_check.mjs`, section 7.5) measures the build's longest main-thread task.
  - Only if that task exceeds 40 ms does the yielding build come in, with ECNL's test that the counts are equal at step sizes 1, 7 and 50.
- **ECNL's painter** (`ecnl:public/index.html:7665-7733`). The same rule applies: it comes in only if the same check misses the keystroke targets in section 7.5.

### Adapt
- **Reader:** keep its shape (`ecnl:public/search/reader.mjs:18-212`; `ecnl:public/search/teams.mjs:114-147`):
  - tokens, then the longest phrase first, then readings, capped at 4;
  - hard filters and typed empty reasons.

  Seasons, age groups and birth years are replaced by CollegeDash's facts (section 4). The state-code rules are CollegeDash's own, not ECNL's (section 4.2). ECNL treats only in/or/me as word codes, and they count when they are the whole query (`ecnl:public/search/vocab.mjs:27-28`; `ecnl:public/search/reader.mjs:71-81`).
- **Answer kinds:** `teams.mjs` becomes Programs. The idea in `events.mjs` that a filtered table is itself a result becomes Lists and Conferences.
- **Section order:** redrawn for these kinds (section 5.3). The best-match, Enter, partial and empty logic is kept (`ecnl:public/search/slate.mjs:65-131`).
- **"Show all":** ECNL expands in place, 50 at a time (`ecnl:public/search/slate.mjs:7-8`; `ecnl:public/index.html:6657`). We do the same whenever a link could not open the same rows (section 5.1).
- **Links:** CollegeDash's routes, checked by a CollegeDash `destinationProblem` that runs the page's own address parsers and filters.
- **Panel:** a combobox with a listbox, CollegeDash's own #434/#445 pattern, because each row has one destination; ECNL needs a grid only for its age-group chips. We keep from ECNL:
  - focus stays in the box, with `aria-activedescendant`;
  - one live region that speaks once;
  - the phone's full-screen dialog with a Tab trap and Cancel (`ecnl:public/index.html:2466-2475, 6749-6751, 8025-8033`), built on CollegeDash's own `phoneSheet()` (1457-1473);
  - on phones, a button in the hero, not an input (ECNL's land-search, `ecnl:public/index.html:8354`);
  - typed empty states (7085-7117).
- **Drawing:** ECNL keeps drawing in the page ("The modules draw nothing", `ecnl:public/index.html:6609`). We put the pure HTML-string renderer in `public/search.js` instead, with the page passing in its own `esc`, `programLine` and division-tag helpers. That way it is tested by `require()` without a fake DOM, and it adds no bytes to the 517 KB `index.html` that every page load parses (section 7.5).
- **Loading:** ECNL fetches two files at first focus, about 109 KB gzipped. CollegeDash fetches one self-contained file of about 55 KB at gzip -9 (section 3).

### Do not port
- `games.mjs`;
- the census, county and "nearby" places pipeline;
- squad continuity, club families and age pairs;
- the `la`/`richmond` aliases and ECNL's kind and noise words.

From the old-engine history we keep only the pattern: freeze today's engine, measure it, and retire it later.

### Lessons from the write-up, adopted as rules for this plan
1. **Exact counts only on frozen data.** A refresh turned ECNL's main red (902 ≠ 901). CollegeDash has the same exposure today: `tests/place_search.test.mjs:112` pins the three programs with no state, and `tests/search_short_forms.test.mjs:121` pins OSU's top 3, both on live data. Section 7.7 lists the data every new test reads.
2. **Work counts guard speed; timing is only a backstop.**
3. **Phone speed is about drawing.** ECNL's search took 0.3 ms; the slow phone keystrokes were the panel redrawing. So the first slate is small and the drawing is counted.
4. **A saturated set stops measuring.** At 65/65 the judged set could no longer tell better from good. So we add graded measures and held-out queries.
5. **Tools tested only against fakes hide bugs.** Destination checks run the page's real address parsers and filters.
6. **Production checks need care:** an owner OK, a request budget and an offline dry run first.
7. **Reviewers re-measure independently.** So the browser check is a committed script with a fixed command (PR 6b).

### What is different for CollegeDash
- **The program index is already in memory on Home:** `boot()` awaits `loadIndex()` before the first view (1715-1718, 6156-6157).
- **One 517 KB `index.html` and no build step.** CollegeDash has no `package.json`. The precedent for a lazily loaded pure script is `public/recs.js` (27,322 B raw; 9,185 B with Python's `gzip.compress(…, 9, mtime=0)`). It is loaded by a `<script>` tag (2838-2846) and `require()`d by Node tests.
- **Data is published by `build()`/`validate()` in the daily refresh**, which publishes only the sources when either fails (`refresh.yml:485-488`). That fallback must restore every build output by name (`refresh.yml:298-326`). Tests run after every refresh, against main (`.github/workflows/tests.yml:25-48`).
- **Two public address contracts:** `#/programs?…` (3557-3651) and `#/camps?…` (4330).
- **Owner-only Ask** exists (1745-1746, 2720-2792; `worker.js:240-330`).

## 3. Data

### 3.1 One purpose-built file
`public/data/search/index.json` is written by a new `write_search_index()` in `build.py`.

**Where build() calls it.** Right after the camps index is written (`build.py:2261-2263`), before the camps log line at 2264.
- By then this run has written every input the search file reads:
  - the programs index (2253);
  - the camps index (2261-2263).
- Called any earlier, at the list and fit writes (2254-2255), it would read the previous run's camps index from disk. Check 2 in section 3.3 would then block every refresh in which the camps changed.

**What it reads.** It reads its three inputs from disk, through one function, `search_index_from_files(programs_path, camps_path, aliases_path)`:
- the programs index and the camps index this run has just written;
- `data/conference-aliases.json`.

That function wraps a pure `search_index(index_doc, camps_doc, aliases)`, which returns `(doc, warnings)` and prints nothing. Three callers use the same code path on the same kind of input:
- `build()`, through `write_search_index()`, which writes the file and then annotates each warning once;
- check 2 in `validate()`, which compares bytes and discards the warnings;
- the fixture test.

So each content warning is annotated once per refresh run, by the build. `validate()` runs twice in a refresh, inside `build()` (`build.py:2288`) and again as its own step (`refresh.yml:487`), and neither prints a warning a second time.

**Where it writes.** To `search_path()`, beside `list_path()` and `fit_path()` (2076-2078, 2126-2128). So a test that swaps `PROGRAMS_OUT_DIR` moves the file with it.

**Format.** The same `updated` stamp as the programs index. Schema 1. One row per line; rows sorted; keys sorted.

```
{
  "schema": 1,
  "build": "<first 16 hex of the sha256 of the file without this field>",
  "updated": "<the programs index's updated>",
  "conferences": [[division, name, [aliases]], ...],    // 98 division/conference pairs today
  "programs": [[slug, name, shortName, nickname, [other search names], city, state, region,
                division, conferenceIndex, undergrads, tuition, admissionRate, fallAvgHighF,
                rpiRank, headCoach], ...],              // 1,011 today; every field but slug may be null
  "camps": [[slug, name, startDate, endDate, precision], ...]   // the camps index's dated ID rows (81 today)
}
```

Where the values come from:
- **Every value is copied or derived the way the build already publishes it:**
  - names and search names from `summary_row` (`build.py:2010`) and `search_names` (1960-2007);
  - tuition as the page's Tuition condition reads it: out-of-state, else in-state (1263-1269);
  - the RPI rank by the same code that gives the list file its `rpi` (`list_row`, `build.py:2087-2091`);
  - camps: the camps index's rows with `campType` "id", a `startDate` and a published slug, which is the set the ID Camps page starts from (`campsData`, 4438-4451). The engine drops camps that have passed, using `ctx.now`, as the page does with its own date (4444);
  - the head coach's name from the index row.

  There is no new collection and no network.
- **States, regions and cities are derived by the engine from the rows.** Regions use the fit constants' state lists.
- **Language words live in the code, not the data:** division spellings, size, tuition and climate words, months and tab words. A code-only test checks that the code's bracket edges equal the page's (UNDERGRAD_EDGES and TUITION_EDGES, 4128-4133; COND_FIELDS, 1261-1288).
- **The file is self-contained on purpose** (decision E):
  - the engine and the judged set run on one file;
  - the page can move to the slim list (#395), which drops `headCoach` (`LIST_DROPPED`, `build.py:2069`), without breaking search;
  - section 3.8 says what happens when the search file and the page's index come from different refreshes.
- **Phase 2 facets are added later as new fields:** colour hue from the hex codes, snow, ownership, religion, latitude/longitude. Adding a field needs no schema bump; renaming, removing or retyping one does.

### 3.2 Size budget: a fixed base plus a per-row rate, checked on frozen data
I measured the phase-1 shape above on today's data with a read-only script (`scratchpad/search507/work/estimate_phase1.py`), at gzip -9 as the camps pins do:

| Shape | Raw | gzip -9 |
|---|---|---|
| the phase-1 file (1,011 programs, 98 conference pairs, 81 camps) | 172,386 B | 54,865 B |
| programs and conferences only | 166,100 B | 53,438 B |
| the document with no rows | 116 B | 112 B |
| the worst of 40 seeded draws of 25 programs | | 2,161 B |
| the worst of 40 seeded draws of 100 programs | | 7,021 B |
| for comparison, a superset with phase 2 fields (`work/estimate_size.py`) | 225.6 KB | 73.4 KB at gzip -6 |

The pin follows the camps precedent (`tests/camps_index_test.py:80-83`), a fixed base plus a per-row rate:
- gzip -9 ≤ 1,000 B + 75 B per program + 30 B per camp;
- raw ≤ 2,000 B + 250 B per program + 120 B per camp.

On today's counts that allows 79,255 B gzipped and 264,470 B raw. The 25-row draw is 2,161 B against an allowance of 2,875 B.

Where it is checked:
- **CI (`tests/search_index_test.py`, PR 2)** checks the formula on the file built from the frozen fixture and on 40 seeded subsets of the fixture's rows. It is deterministic and never reads `public/data`.
- **`validate()`** prints a `::warning` when the live file breaks the same formula. It never blocks.
- **Nothing in CI reads the size of the live file**, so a refresh can't turn main red over size.

For scale: Home already downloads `/api/v1/programs` (174 KB at gzip -6) on every load.

### 3.3 Built and checked by the refresh: what may block the publish, and why
`check_search_index()` joins `validate()` (`build.py:2293-2328`), modelled on `check_list_index` (2378-2396).

**The rule: a check may block the publish only when nothing but a code bug or a hand edit can fail it.** Everything that depends on refreshed content is handled by the builder, which repairs or skips the item and warns, and the publish goes ahead.

| # | Check | Reads | If it fails | Why |
|---|---|---|---|---|
| 1 | Parses and passes `schema/search.schema.json` | the written file | **blocks** | The schema fixes types and structure only, with no patterns on names or text, and it allows null in every program field except `slug`. So only a builder bug can fail it. A malformed file would break search for every visitor. `check_list_index` follows the same rule today. |
| 2 | Equals, byte for byte, what `search_index_from_files()` gives from the programs index, camps index and alias table now on disk | the file and its three inputs | **blocks** | `build()` wrote it moments earlier from those same files, after both indexes were written (section 3.1). So a difference means non-determinism or a hand edit. |
| 3 | `updated` equals `programs/index.json`'s | both stamps | **blocks** | One run writes both. |
| 4 | Exactly one row per published program, and one per (division, conference) pair | the file and the programs index | **blocks** | True by construction: the builder never drops a program row (row 7). |
| 5 | No email-shaped string anywhere in the file | the file | **blocks** | The builder and this check use one pattern object, `common.EMAIL_RE`, new in `collect/common.py` (section 3.4). The builder runs it over every string it copies: names, short names, nicknames, search names, cities, head coaches, conference names and aliases, and camp names. A matching string field becomes null, a matching list entry is left out of its list, and a camp row whose name matches is left out, each with a `::warning` naming the slug. So refreshed content can never trip this check; only a broken filter can. An address in a public file is worse than one day of stale data. |
| 6 | Each alias entry is well formed, its (division, conference) exists in this data, and no alias names two conferences in one division | the alias table and the programs index | the entry is **skipped**, with a `::warning`; never blocks | Conferences realign and rename; that is content, not code. The entry is checked when it is added, by a CI test (section 3.5). |
| 7 | Content the builder can't read: a missing division or conference, a figure that isn't a number, a camp with no start date or with a slug no published program has | refreshed rows | **program rows are never dropped**: the unreadable value becomes null. A camp row is left out, as the ID Camps page leaves it out (4444, 4446). Each case gets a `::warning`; none blocks. | Same reason. Keeping every program row is what lets row 4 block safely. |
| 8 | Size above the formula in section 3.2 | the file | `::warning` only | Size is guarded in CI on frozen data. |

- `search_index()` itself never raises on content. PR 2's failing tests feed it broken rows (section 8) and expect a file plus warnings.
- **A missing or unreadable search file** is reported as a `SEARCH:` line and makes `check_search_index()` return False. It never raises. That is what `check_list_index()` does for the list (`build.py:2378-2396`): `read_json` gives None for a missing file, and `list_complaints` names it (2341-2342). In a refresh the file is never missing at validate time, because `build()` has just written it.
- The warnings appear on the refresh run's page. The coordinator reads refresh runs and opens an issue for any search warning that is still there two days running.
- The builder follows ECNL's habits: no clock, no locale, sorted output, one row per line for quiet diffs, and it writes only when the bytes change, through a `.tmp` file.

### 3.4 Wired in everywhere a build output must be
#395 (the list) and #400 (the fit file) each connected a new build output in the same places. PR 2 does all of them for the search file.

| Where | What PR 2 adds | Why |
|---|---|---|
| `.github/workflows/refresh.yml`, `publish_sources_only` | `git checkout FETCH_HEAD -- public/data/search/index.json 2>/dev/null \|\| rm -f public/data/search/index.json`, after the fit line (317). The search file is also added to every list of build outputs the step prints or explains: the comment at 270, the error message at 324, and the "NOTHING WAS PUBLISHED" message at 340, which names what was left exactly as main has it. | When build or validate fails, the fallback puts each build output back by name (311-317). The assertion at 323-324 then stops the step if anything under `public/data` (outside rpi and the registry) still differs. As the comment at 280-282 says, "a fifth build() output added later is a hard stop here". Without the line, the first build or validate failure after PR 2 would end with "this run's collection was NOT saved". |
| `tests/refresh_commit_step_test.py` | The stand-in `build` also writes `public/data/search/index.json`, next to the list and fit writes (266-271). A new `search-restore` case, modelled on list-restore and fit-restore (docstring 97-104; cases 1176-1286), is added to the case list at 1297-1304. | It runs the step's own shell, as the #395 and #400 cases do. |
| `serve.py` | `elif sub == "search": rel_file = os.path.join("data", "search", "index.json")`, beside `list` and `fit` (107-110) | The local server answers the same routes as the Worker. PR 6b's browser check uses it. |
| `api/data-api.mjs:5-14`, `api/data-reader.mjs:2-24`, `docs/data-api.md` | the `/api/v1/search` route; its row in the docs' route table (20-29); the Home box's first focus in the journey count (75); and a recount of "the 5 indexes" a key copies (78). The route table already lists six index files besides profiles and status, so PR 2 recounts rather than adds one. | The Worker serves data only through routes (section 3.7). |
| `tests/perf_worker.test.mjs` | a case modelled on #400's fit case (460-467): a `/api/v1/search` request makes one server point with route kind `search` and nothing about the visitor (`blobs[3..4]` empty) | The perf route kind comes from the route table's kind (`api/data-api.mjs:5-14`, `api/perf.mjs:43`), so no other wiring is needed; the case pins it. On main the route is unknown. |
| `collect/common.py` | `EMAIL_RE`, used by the builder's filter and by check 5 (section 3.3). It is the pattern `tests/staff_fallback_test.py:269` already guards profiles with, which also catches "name (at) school.edu" and "[at]". | One object for the filter and the check, so they can't disagree. `tools/camps_check.py:184` and `collect/coach_bio.py:63` keep their own patterns, which do other jobs (reserved domains; phone numbers). Pointing them at the shared one is a later clean-up, not part of #507. |
| `tests/seasons_test.py:190` | `"SEARCH"` joins the prefixes `complaints()` collects | so the scratch build's own validate pass reports search complaints, as it does for LIST and FIT |
| `tests/camps_index_test.py` | a scratch-build case (below) | It catches a search file built from the wrong run's camps. |

**The `search-restore` case** asserts what the fit-restore case asserts (1243-1286), for the search file:
- **Control.** With the restore line removed from the workflow text, the line is found exactly once, the step fails, nothing is pushed anywhere, and it is the fifth-output assertion ("does not match") that stopped it.
- **Absent on main.** Main has no search file and validate fails: the collection is on a sources branch, the branch has no search file, and `public/data` is exactly main's.
- **Present on main.** Main has a search file and build or validate fails: the branch's search file is main's, byte for byte.
- **Nothing fails.** Main gets the rebuilt file.

On main it fails twice over:
- the control's "found exactly once" is 0;
- with the stand-in build writing the file and no restore line, a run whose validate fails after the build stops at the fifth-output assertion instead of saving its collection. That is exactly the failure the case exists to prevent.

**The scratch-build case in `tests/camps_index_test.py`.** That suite already runs one full build into a temporary tree through `seasons_test.rebuild()` (824; the swap at `tests/seasons_test.py:164-185`). Its guard (164-172) checks that nothing under `public/` is written. PR 2 uses that same build, so CI gains no second full build:
1. Before the build, it writes a sentinel camps index into the scratch camps directory: one ID camp row named "SENTINEL #507".
2. After the build, it asserts:
   - `<tmp>/search/index.json` exists, which proves `search_path()` follows the swap;
   - its `camps` rows equal the dated, published-slug ID rows of `<tmp>/camps/index.json`, the camps index this same build wrote, projected the way `search_index()` projects them;
   - no row names the sentinel;
   - the build log has no `SEARCH` complaint lines.

On main it fails, because there is no search file. A call placed before the camps write would fail it too, because the search file would carry the sentinel. The case pins no number: it compares two files from one run.

### 3.5 Reviewed input: conference aliases, with the evidence kept as text
`data/conference-aliases.json` is new. No such table exists today; only Ask's model prompt maps B1G and Big 10 (`worker.js:356`).

**Which entries ship, and when.** PR 2 ships exactly the four the judged set needs, and no PR in phase 1 adds another:
- "B1G" for Big Ten (D1, F02);
- "CCAA" for California Collegiate Athletic Association (D2, F04);
- "NESCAC" for New England Small College Athletic Conference (D3, F05);
- "UAA" for University Athletic Association (D3, F08).

The other conference queries need no alias. "WCC", "MAC", "Metro", "Pac-12", "Big Ten" and "Ivy League" are the stored names (F01, F03, F06, F07, X01, X03). Any further alias, such as "Big 10", is its own small reviewed PR with its quote and a fixture refresh. PR 5 adds no entry; it only reads the table.

- **Each entry:** `{alias, division, conference, note}`.
- **The note is a new convention, modelled on the registry's `searchAliasesNote`** (#217, #309). It holds:
  - the alias in double quotes, inside a quotation copied from a source;
  - that source's URL;
  - "checked YYYY-MM-DD" and the issue number.

  For example: "NESCAC" in the title "Eleanor Martin named NESCAC Women's Soccer Player of the Week", gobatesbobcats.com/news/2026/10/5/… (Bates College, a member), checked 2026-10-21 (#507).
- **How it differs from the registry's convention.** The registry's test requires a `wikipedia.org/wiki/` link (`tests/search_short_forms.test.mjs:85`). This table accepts any `https://` URL, because a conference's own pages and its members' pages are the usual evidence for its short form.
- **The quote is copied into the table, so the table never depends on a refreshed file.** `programs/bates-college/sources/news.json` is rewritten by every refresh (`git log` shows a83a32086, 69b351a23, 80b50488b, 42536e706 and 48673a288 on consecutive days), so nothing reads it at build time.
- **Where quotes come from, offline:**
  - a line already committed in the repo, found at PR time with a local search;
  - or a citation the owner supplies.

  Reading a live web page needs the owner's OK.
- **The CI test (`tests/search_aliases_test.py`, PR 2) checks entries when they are added.** It reads only the alias table and the frozen fixture's conference list, never `public/data`. It checks that:
  - every entry has exactly the four keys;
  - the note contains `"<alias>"`, an `https://` URL and "checked 20YY-MM-DD";
  - the (division, conference) is in the fixture;
  - no alias names two conferences in one division;
  - no alias equals another conference's own name in the same division.

  An alias for a conference that isn't in the fixture comes with a fixture refresh in the same reviewed PR.
- **At build time** a bad or stale entry is skipped with a warning (row 6 above). That includes an alias whose conference no longer exists after realignment.
- A conference means its current members only (C05).

### 3.6 Frozen test data
`tests/fixtures/search/` holds:
- the inputs, cut by `tools/search_fixture.py` from a checkout of data commit `a83a32086`:
  - `programs.json`: the programs index;
  - `camps.json`: the camps index;
  - `conference-aliases.json`: a copy of the alias table;
- `index.json`: the search file built from those inputs (from PR 2 on);
- `PROVENANCE.json`, which records:
  - the sha256 of each input;
  - the line range and sha256 of each slice frozen into `tests/search/engines/today.js` (section 7.3);
  - the sha256 of the built search file;
  - the data and code commits it was cut from. The commits are recorded but not verified.

**Size.** PR 1 measures the folder; its ceiling is 2.5 MB raw. `programs.json` is the full index (1,913,827 B) unless a trimmed copy still boots the page harness and draws Home and the Programs list without error. A test checks that whichever copy is committed boots.

**What CI checks (`tests/search_fixture_test.py`).** Only committed files against committed files:
- each input's sha256 equals PROVENANCE;
- `today.js`'s sha256 equals PROVENANCE;
- from PR 2 on, `search_index_from_files()` on the committed inputs gives the committed `index.json` byte for byte.

**What CI never does.**
- It never reads `public/data`, so a refresh can't turn main red.
- It never reads git history. The test job's checkout (`tests.yml:103-105`) sets no `fetch-depth`, so it is shallow and `a83a32086` isn't in it.

**By hand only.**
- `tools/search_fixture.py --check` compares the fixture with today's `public/data`. It is run when someone regenerates the fixture, exactly as `tools/recs_catalog.py --check` is (`tests/recs_catalog_test.py:6-9`).
- From PR 6b on, `tools/search_fixture.py --serve PORT` serves the fixture to a local browser (section 7.5).

The fixture changes only in a reviewed PR. A builder change that alters the output fails the byte-equality check until the fixture's `index.json` is rebuilt in the same PR. Every exact count and exact top result is pinned on this fixture, never on `public/data`.

### 3.7 Served how: through the API (decision F, a team default)
- **The route:** `/api/v1/search` maps to `/data/search/index.json` in `api/data-api.mjs:5-14` and `api/data-reader.mjs:2-24`. The local `serve.py` gets the same route (section 3.4).
- **The same session gate and limits as every route:** RL_SESSION 180 per 60 s, RL_ANON 60 per 60 s, RL_IP 1,200 per 60 s (`docs/data-api.md`). One request at first focus is far inside them.
- **Caching:** `cache-control: no-cache` with an ETag (`api/data-api.mjs:62-65`).
- **Before the first build:** a JSON 404 until the first build writes the file, the #395 lesson (`tests/data_api.test.mjs:217-260`).
- **Raw files stay blocked:** `/data/*` is still refused (`worker.js:84-85, 157-166`).
- **Docs:** `docs/data-api.md` gains a row in the route table (20-29), and its journey count (75) gains "the Home box's first focus: 1".
- **Why not a static file:** it would bypass the session gate that #100, #240 and #345 put on all data.

### 3.8 Loaded when
- **Code:** `public/search.js`, a plain script like `public/recs.js` (a global `CDSearch`, `require()`d by Node tests).
  - It is fetched at the first idle moment on Home (`requestIdleCallback` with a 4 s timeout), else at first focus.
  - It is not fetched at idle on Save-Data; it is then fetched at first focus.
  - It is a static file, not an API request. Its size is capped (section 7.5).
- **Data:** one request at the box's first focus, remembered for the life of the page.
  - A 404 is remembered for the page.
  - A 429 is remembered for 60 s.
  - A 5xx or network error is forgotten, so the next focus retries (`ecnl:public/index.html:6672-6691`).
- **Index build:** one-shot (section 2). While it runs, the panel shows "Getting search ready…", and Enter waits so the first row never changes under the visitor.
- **If the file is missing or fails** (PR 6b): the box falls back to today's names-only matcher over the index already in memory (`matchScore`, 1137-1160). A line says only school names can be searched right now.
  - A search file whose `schema` the code doesn't know is treated as failed until PR 6c gives it its own Reload alert.
- **Program rows whose slug is not in the page's index are left out** (PR 6b). So no row ever links to a program the page doesn't have.
- **When the search file and the page's index come from different refreshes** (`search.updated ≠ S.index.updated`, as in a tab left open across a refresh), PR 6c adds:
  - list rows and "Show all" links show no count ("Show these programs"), because the page would count from a different day's rows;
  - a quiet line: "CollegeDash's data was refreshed since this page opened. Reload for the latest."

  PR 6c pins this on a fixture copy with a changed stamp and one slug removed.
- **Typing, moving through results and choosing one:** no request, as `tests/header_search.test.mjs:345` already pins for the header box.

## 4. Query understanding

### 4.1 Normalising, shared words and "too broad"
- ECNL's normalise (lower case; accents, `.` and apostrophes dropped), plus CollegeDash's `&` rule (normText, 1061).
- Pairs treated as the same word, both ways: saint/st (as the camps search does, 4385; except on a State-side program, below), mount/mt, and "&"/"and".

**A "st" that means State.** NCAA names write State as "St.", and the build publishes them as search names: "Ohio St.", "Alabama St.", "Cal St. Fullerton".
- On the fixture, 89 programs have the word "st" in a name or search name. In 50 it means State; in 39 it means Saint ("St. John's", "Mount St. Mary's").
- **The build also turns a State "St." into "Saint".** `search_names` adds a copy of every name with each "St." that is followed by a space replaced by "Saint " (`build.py:2002-2004`), whatever the "St." means. So cal-state-fullerton publishes "Cal Saint Fullerton", made from "Cal St. Fullerton". On the fixture that is the only such name: 40 programs have the word "saint", namely the 39 Saint-side ones and cal-state-fullerton.
- Ported as ECNL has it, the saint/st twin would make "saint" find Ohio State, and "Cal Saint Fullerton" would make it find Cal State Fullerton even without the twin. The camps search never meets this, because it reads only program names and short names (4383), not search names.
- **The rule.** A program is *State-side* when its own `name` or `shortName` has the word "State" and no word "Saint" or "St" (160 programs on the fixture). When the engine indexes a State-side program, every "st" and every "saint" in its names is indexed as "state".
  - A State-side program's own names have no Saint, so a "saint" in its search names can only come from the build's swap.
  - Every other program, and every conference, keeps the saint/st twin.
- **What that gives on the fixture.** A typed "saint" finds, by name, exactly the 39 Saint-side programs. No program is on both sides: the 50 State-side programs with a "st", and cal-state-fullerton's "Cal Saint Fullerton", are all read as State.
- **Typed words.** A typed "st" looks for "st", "saint" and "state", so "ohio st" and "cal st fullerton" still find their schools. A typed "saint" looks for "saint" and "st" only, never "state".
- **Judged** by E15 "saint" (section 7.1). PR 3 also has a unit test that cal-state-fullerton's "Cal Saint Fullerton" is indexed as "cal state fullerton".
- **Today's box meets the same name.** Today's matcher reads search names (`prepareSearch`, 1123-1134). On the fixture, "saint" has 46 hits there, and Cal State Fullerton is the 32nd, through "Cal Saint Fullerton" (score 60, 1152). The box shows only the first 6, but `#/programs?q=saint` lists all 46, Cal State Fullerton among them.
  - I recommend fixing the swap in its own issue, outside #507 (section 9, T).
  - The engine rule does not wait for that fix. Once the build stops making the name, the rule simply has nothing to re-index there, and the fixture is unchanged until a reviewed refresh.

**Shared words (team default T, the draft's C07).** A fixed list in the code, `SHARED_WORDS`:

> the, of, and, soccer, women, womens (from "women's"), ncaa, school, schools, program, programs, university, college

- **When the query has at least one other word, a shared word is optional for program rows.** A program row need not contain it, and it adds to the score of the rows that do. So "boston university" ranks Boston University above Boston College, and "university of michigan" still finds Michigan.
- **For conference rows, a shared word is required** (section 5.2). So "university of michigan" gives no Michigan Intercollegiate Athletic Association row: that name has neither "university" nor "of".
- "university" and "college" are on the list in every position. Revision 2 counted them as shared only "next to a name", which left "university" on its own outside the too-broad rule even though E06 expected it to be too broad. Revision 2 also said shared words were "ignored"; they are now optional, so a row that has them still ranks higher.
- "of" and "and" are added, as in ECNL's NOISE (`ecnl:public/search/match.mjs:52`). "and" between two values of one fact stays a connector (section 4.2).

**Too broad (C19): one exact rule.** A query is too broad when it has at least one whole word and every word is a shared word or one of the kind words conference, conferences, coach, coaches.
- **Whole words only.** "universit", while it is still being typed, is an ordinary prefix.
- **Not too broad:**
  - a single letter, or any short word that is not on the list ("a", "st"). The first-show cap of 6 Programs rows bounds their drawing like any slate's (section 5.1), and Enter opens the first row, as it does today;
  - a camp word alone ("id camps"), which asks for the Camps section;
  - anything with a fact or another name word.
- **No count threshold.** Whether a query is too broad depends on its words only, so a refresh can't change it, and it needs no live number.
- **What the panel shows** (section 5.6):
  - a status line, such as "“university” is in 761 names. Add a name, a state or a division." The count is counted at run time;
  - **the Programs section only.** Its rows are the programs whose names contain the shared words, matched as ordinary name words and ranked by the Programs ranking in section 5.2, shown at first-show size, with "Show all N" expanding in place. A too-broad slate draws no Lists, Conferences, Camps or Coaches section, so "university" shows no University Athletic Association row and "womens soccer" no NEWMAC row (whose stored name, "New England Women's and Men's Athletic Conference", normalises to contain "womens");
  - Enter does nothing unless the visitor has moved to a row (section 5.4).
- **Judged** (section 7.1): E06 "university" (761 programs, so rows) and E14 "womens soccer" (no program name, short name, search name or nickname has either word, so no rows) are too broad, with `sections` Programs and none. E02 "a" and E03 "st" are not.

### 4.2 Vocabulary and roles
The reader tries the longest phrase first and keeps every role a phrase can have as a separate reading, under the rules in 4.3.

| Role | Examples | Source | Effect |
|---|---|---|---|
| Division | d1, d-1, di, div 1, division 1/i/one, ncaa d1 (and D2, D3) | code (DIVISION_NAMES, 2006) | hard filter |
| Conference | big ten, ivy league, new england small college athletic conference (a stored name typed as a phrase); the aliases b1g, ccaa, nescac and uaa (section 3.5) | search file and alias table | on its own: a Conference row, which is that conference's list; with other facts: a hard filter on the list row. Name words can also give conference rows, but only under the word rule in 5.2 |
| State | 51 full names (STATE_NAMES, 1085-1092) and two-letter codes, under the rules below | code | hard filter |
| Region | West, Midwest, South, Mid-Atlantic, Northeast (REGIONS, 2002); "new england" = Northeast (C10) | code | hard filter |
| City | 786 city/state pairs from the rows; "city ST", "city, State" | search file | finds and labels program rows ("in Boston, MA"); no list row (decision S) |
| Size | very small, small, medium, large, very large (UNDERGRAD_SIZES, 4128-4130; "small" per decision L) | code | hard (`cond` undergradEnrollment) |
| Tuition | under 30k, under $30,000, tuition below 20k (C03) | code | hard (`cond` tuition) |
| Climate | warm or hot: fall average high above 80F (C04); cold: decision Q | code | hard (`cond` fallAvgHighF) |
| RPI | top 25, top 25 rpi (D1 only) | code | hard (`cond` rpiRank, sorted by RPI) |
| Kind words | camp, camps, id camp(s); conference(s), coach(es) | code | a camp word puts Camps first (5.3 rule 1). "conference" and "coach" are optional, like shared words, when other words remain, and too broad on their own (4.1); "coach" after a program name opens its staff tab, like the tab word "coaches" |
| Tab words | roster, schedule, staff, coaches, commitments, camps, climate, news (TABS, 5506) | code | chooses the tab a program row opens ("stanford roster" opens `#/p/stanford/roster`) |
| Dates | jan…dec, january…, this weekend, next month (camps only), read against `ctx.now` and `ctx.timeZone` | code | hard on Camps |
| Connectors | "or" and "and" between two values of one fact ("d1 or d2", "ohio and michigan"); "in" before a place | code | joins the values; "in" marks the next word as a place |
| Phase 2 words | colour names, snow, catholic and other affiliations, public/private | code | named back (section 4.6) |
| Name words | everything else: names, short forms, search names, nicknames, head coaches | search file | scored |

**State codes.** This is CollegeDash's own rule, built on #404 (1077-1079).
1. **A two-letter state code typed in capitals is that state.** It finds programs only through the state and through an exact search name, never as a name prefix or a typo. So:
   - "NE" lists Nebraska's programs plus the two programs whose search name is exactly "NE" (section 9, M);
   - "LA" never lists La Salle or Lafayette, which today's matcher puts first (1141);
   - "PA" on its own is Pennsylvania.

   The one exception: "ID" followed by "camp" or "camps" is the camp word.
2. **A query typed entirely in capitals, with two or more words, is read by the lower-case rules below.** So "D3 IN OHIO" reads like "d3 in ohio", and "D1 OR D2" like "d1 or d2". In a mixed-case query, OR or AND between two values of one fact, and IN straight before a state name or city, are connectors even in capitals ("d1 OR d2", "d3 IN ohio").
3. **In lower case, a code counts as a state in only two places:**
   - next to another fact word: "d3 tx", "d1 ca";
   - straight after a city in that state: "columbus oh", "portland me". Today's place search already reads this case (1102-1106).
4. **The codes that are also everyday words (in, or, me, hi, ok, oh, id) are never a state in lower case,** except straight after a city in that state (rule 3's second case). So:
   - "d3 in ohio" means D3 and Ohio, never Indiana;
   - "d1 or d2" means D1 or D2, never Oregon;
   - "schools in texas" means Texas;
   - "id camps texas" means ID camps in Texas, never Idaho;
   - "portland me" means Portland, Maine.
5. **On its own, a lower-case code is only a name word,** so "pa" on the way to "Pacific" adds no Pennsylvania programs (#404's rule).

Judged queries G01-G07 (section 7.1) pin rules 1-4.

### 4.3 Readings and hard filters
- **Readings:** each word plays one role or is a name word. Up to 4 readings are kept per section (`ecnl:public/search/reader.mjs:87-212`).
- **Three rules limit the readings, so a fact the visitor typed stays a fact:**
  1. **A query whose words can all be read as facts, with two or more facts, is read only as facts.** Facts are counted after the longest phrase is taken first, so a phrase that is one fact is never split into two.
     - "division 1 west" is {D1, West} and never the name word "west", so it shows no Western Michigan or West Virginia (D06).
     - "d3 ohio" is {D3, OH} and never "ohio" as a name word.
     - "west virginia" is one fact, the state WV, not {West, VA}. So rule 1 does not apply, the query keeps its name reading, and it is the collision case of 5.3 rule 3 (judged G08).

     A query with one fact keeps both readings: that is the collision case in 5.3 ("texas", "new england", "mac"). So does a query with a word that can only be a name: "d1 ohio state" still finds Ohio State by name.
  2. **"in" right before a state name, region or city makes that word a place only.** So "schools in texas" is the Texas list, not the program Texas.
     - **"of" right after a shared word does the opposite:** the state name or region after "university of" or "college of" is part of a name only, never a fact. So "university of michigan" has no Michigan fact and gives no Michigan list row (S06 keeps `sections` Programs), while "michigan schools" is still the Michigan list. Without this, S06's fact reading {MI} would be facts-only (its other words are shared words, as in "schools in texas") and would add a Lists section from PR 5 that today's box doesn't have.
  3. **A capital state code gives no name-prefix reading** (4.2, rule 1).
- **How filters combine:** several values of one fact (divisions, states, regions) combine with OR. Different facts combine with AND. A state next to a city narrows the city.
- **Facts are hard.** Programs, Lists and Conferences apply the filters, so a row that fails a typed fact is never shown:
  - "d3 ohio" never shows Ohio State or Ohio Dominican;
  - "d2 florida" never shows Florida or Florida State;
  - "d3 in ohio" never shows DePauw or Earlham (D3, Indiana).
- **An impossible combination gives a typed reason**, not an empty list:
  - "sec d3": "No D3 program is in the SEC";
  - "top 25 rpi d3": "RPI is published for D1 only" (NOT_APPLICABLE, 1228).
- **Filter words still add to the score** (`ecnl:public/search/match.mjs:238-243`).

### 4.4 Aliases and short forms
- **Programs:** the 2,606 published search names (`build.py:1960-2007`): NCAA and RPI-archive names, initials, St./Saint swaps, and the registry's 35 cited aliases. Phase 1 adds no program alias without a cited registry entry.
  - The judged query Y07 "umass boston" needs one: massachusetts-boston's search names are "Massachusetts Boston" and its full name only (decision U).
- **Conferences:** the reviewed table in section 3.5.
- **Cities:** none in phase 1, except "LA" for Los Angeles if the owner approves it under decision M.
  - **Where it would live.** The search file has no field for a city alias, and language words live in the code (section 3.1). So it is one entry in a `CITY_ALIASES` constant in `public/search.js`: "LA", read only in capitals, names the pair (Los Angeles, CA).
  - **How it is checked.** A code-only test in PR 5 checks that every entry names a (city, state) pair present in the fixture's rows. Los Angeles, CA has 5 programs there: ucla, usc, loyola-marymount, california-state-los-angeles and occidental-college. Judged X05 pins the effect.
  - If the owner declines, there is no constant, and X05 keeps only its Louisiana `first`.
- **Ambiguous short forms** (OSU, FSU, USF, Miami) keep showing every candidate (`tests/search_short_forms.test.mjs:109-122`).
- **Initials that equal a state code** come from a build rule, not from a reviewer (`build.py:1987-1988`; decision M).
  - On the fixture, 14 distinct two-letter strings are search names. 12 come from that initials rule; "GW" (george-washington) and "UK" (kentucky) are cited registry aliases.
  - 3 of the 12 equal a state code, on 5 programs: "NE" (2), "NC" (2) and "DE" (1).
  - The engine treats them as ordinary search names, and the judged set pins "NE", "DE" and "NC" (X06, X09, X10).

### 4.5 Typos
ECNL's rules, with the weights re-tuned (section 2):
- only words of 4 or more letters, within 1 edit (2 edits from 8 letters), where a swap counts as 1 edit;
- a word that is itself a known word is never read as a typo;
- initials and codes never match by typo;
- the last word also matches as a prefix at any length, the other words from 3 letters;
- typo matches rank below exact and prefix matches.

Judged examples: standford, georgtown, vilanova, mizou, william and mary, the ohio state university.

### 4.6 Words with no data
- **What gets named back.** A word with no reading, a phase-2 word, or a place nickname is named back in a notice. The rows the other words give are labelled partial ("not applied: …"):
  - "d1 blue snow psychology" gives the D1 list, labelled partial, with notices for "blue", "snow" and "psychology";
  - a phase-2 word that some reading uses as a name word with results, such as "blue" in "duke blue devils", is not named back.
- **Rows that match only some of the name words** ("partial matches") show only when no reading accounts for every word (`ecnl:public/search/search.mjs:142-149`). A reading accounts for a word when it applies it, names it back, or treats it as an optional shared word (4.1), so "stanford soccer" gives Stanford as a full match, not a partial one.

## 5. Results

### 5.1 Sections, first-show sizes and "Show all"
- **First show:** Programs 6 (as SUGGEST_MAX, 2577), Lists 3, Conferences 3, Camps 3, Coaches 3. That is 18 rows at most.
- **The rule for "Show all N":** the link, or the expansion, must show exactly the N rows the panel counted.
  - **The panel never puts `q=` in a link in phase 1.** The Programs page reads `q=` through today's matcher (`visibleMatches`/`searchMatches`, 1165-1172), which stays until decision J. So "standford", "michigan wolverines" or "erica dambach" would open 0 programs or a different set.
- **Programs:**
  - When the query has no name words (facts only, such as "d3 ohio", "big ten" or "small d3 under 30k"), "Show all 21" is a link to the same facts-only address as the list row, or as the conference row for a single conference.
  - When it has name words, "Show all N" expands inside the panel, 50 rows at a time, as ECNL does.
- **Camps:**
  - **Facts only** (month, "this weekend", region or state, division): a link to `#/camps?from=…&to=…&region=…&state=…&div=…`, the page's own parameters (CAMPS_PARAMS, 4330).
    - Month words and "this weekend" map to `from` and `to`, never to `when`: CAMPS_WHEN (4335) has only `30d` and `90d`.
    - The engine's date test is the page's: a camp is kept when it overlaps the window, and a month-only camp is compared by month (`campsMatch`, 4409-4412).
  - **Region and state together.** The link is offered only when the camps page reads the facts the same way. `campsMatch` (4404-4415) joins a region and a state with OR, so a query that types both expands in place instead.
  - **With name words:** expands in place.
  - **One known difference is accepted.** A visitor who turned on "Shortlisted programs only" on the ID Camps page earlier in the same page session (`S.campsSaved`, in memory only, 981; applied at 4408) sees fewer camps. The page's own filter chip says so (4463).
- **Conferences and Coaches:** expand in place.
- **Lists and Conferences rows:** each row is itself the link.
- **When the search file and the page's index differ** (section 3.8, PR 6c), links show no count.

The destination check in section 5.5 covers every "Show all" link.

### 5.2 What each section holds, and its ranking
The order is total and deterministic.
- **Programs.**
  - Rows matched by name words come first, filtered by the reading's facts. They are ranked by:
    1. match class: exact, then prefix, then typo;
    2. BM25F score over the fields: displayed name, other search names, nickname, head coach, city. ECNL's field weights are the starting values;
    3. D1 before D2 before D3 (C08);
    4. displayed name, compared as the page's Name sort compares it;
    5. slug.
  - City-only matches rank below every name match, as today (1074-1076).
  - For a reading made only of facts, the programs that pass the facts follow, in the list's own order (by name, or by RPI for "top N RPI").
  - With a camp kind word, only name-word matches are shown.
- **Lists:** one row per facts-only reading, unless that reading's only fact is one conference. None with a camp kind word, and none on a too-broad slate. More fact words used first, then fewer programs (more specific) first.
- **Conferences:** each (division, conference) pair at most once, from two sources, filtered by a division fact. None with a camp kind word, and none on a too-broad slate (4.1).
  - **By a conference fact:** a stored name typed as a phrase, or an alias (section 3.5).
  - **By words,** only under the rule below.
  - Ranked: fact matches first, then whole-word matches, then matches through a last-word prefix; then D1, D2, D3; then the stored name. For section order (5.3), a fact or a whole-word match counts as exact, and a prefix match as prefix.
- **Camps:** only with a camp kind word. Soonest first, a month-only camp at the start of its month, then the program's displayed name.
- **Coaches:** head coaches whose name the name words match. Ranked by match class, then score, then D1 to D3, then name. Two coaches with the same name are two rows.

**When words give a conference row.** A reading gives a conference row by words only when all four of these hold:
1. **It has at least one name word.** Facts, connectors, kind words (conference, coach and camp words), tab words and shared words are not name words.
2. **Every name word and every shared word in the reading matches a different word of the conference's stored name.** The stored name is normalised as program names are (4.1): the saint/st and mount/mt twins apply, and a typed "st" also matches "state".
   - Shared words are required here, unlike in program rows. So "university of michigan" gives no Michigan Intercollegiate Athletic Association row.
   - Kind words are never required, so "ohio conference" still finds the Ohio Athletic Conference.
3. **A word matches when it equals the name's word.** Only the query's last word, when it is a name word of 4 or more letters, may instead be the start of the name's word. There are no typo matches.
4. **A reading whose only name word has one or two letters gives none.** It is a prefix still being typed. Conference initials come through the fact path instead: stored names such as "WCC", "MAC" and "SEC", and the aliases.

**What the rule gives on the fixture.** I applied it to every judged query over the fixture's 98 stored (division, conference) pairs, with a read-only script (`scratchpad/search507/chitu-r4/conf_rule_final.py`, which approximates the reader of 4.3). Only these queries get conference rows:

| Query | Conference rows | How |
|---|---|---|
| F01-F08, X01 "mac", X03 "metro" | that one conference | a fact: its stored name or alias |
| X02 "american" | American (D1); American Rivers and American Southwest (D3); Great American (D2) | "American" is a stored name, so a fact; the other three by the whole word |
| X04 "new england" | Conference of New England, NESCAC and NEWMAC (D3) | whole words |
| L04 "new york" | the City University of New York and State University of New York conferences (D3) | whole words |
| E15 "saint" | St. Louis Intercollegiate Athletic Conference (D3) | the saint/st twin |

D07 "sec d3" names the SEC as a fact and gets the impossible state (4.3), not a row. Every other judged query gets no conference row. Revision 3's rule ("every name word starts a word of the name", with shared words optional) gave rows to several of them; the review counted them on the fixture:
- S02 "cal" started the CCAA and SCIAC names. Now none: no stored name has the word "cal", and a 3-letter last word is never a prefix.
- S06 "university of michigan" started the Michigan Intercollegiate Athletic Association once "university" and "of" were optional. Now none: rule 2.
- S07 "penn state" started the Pennsylvania State Athletic Conference. Now none: "penn" is not a whole word of it.
- E02 "a" started 46 names and E03 "st" 6. Now none: rule 4. ("st" is a whole word of one stored name, "St. Louis Intercollegiate Athletic Conference".)
- E06 "university" started the UAA, CUNY and SUNY conferences, and E14's "womens" is in NEWMAC's stored name. Now none: a too-broad slate draws Programs only (4.1).

So every judged `sections` list agrees with the rule. The only one that changes is E15, which gains Conferences after Programs (section 7.1).

**Many equally good answers.** Only rows matched through the same word in the same field tie on score.
- **"bulldogs"** reaches every Bulldogs program through the one nickname "Bulldogs", so the 27 rows tie on class and score, and D1 sorts first (step 3 of the Programs ranking above). The first row is the D1 Bulldogs program whose displayed name sorts first.
- **"a" and "st"** do not tie that way. A prefix reaches many different words, and BM25F scores each word with that word's own rarity (`ecnl:public/search/match.mjs:202-206, 234`). So which row comes first depends on scores, not on division and name.
- So the judged set defines `first` for E02 and E03 by usefulness, not by the engine's order, and for K06 by the tie rule (section 7.1).
- **A row matched through the nickname is useful** for E02 and E03. The nickname is one of the names the box searches, and the nickname group (K01-K06) judges it as an answer. A nickname word found on one program only is rare, so BM25F may let it lead: uc-irvine's "Anteaters" for "a", fairfield's "Stags" for "st". The engine is not bent to prevent that. A row matched only through a city or a head coach is not useful.

### 5.3 Section order
The first rule that applies decides which section leads; rules 1, 2 and 4 also fix the second. The remaining non-empty sections follow by strength: the match class of their first row, with a fact and a whole-word conference match counting as exact, then the tie order Programs, Lists, Conferences, Coaches, Camps.

A too-broad slate (4.1) has only the Programs section, so these rules don't apply to it.

The rules are redrawn from `ecnl:public/search/slate.mjs:14-57`. Each one is pinned by judged queries, and together they replace the draft's C01.
1. **A camp kind word:** Camps, then Programs. Examples: "ucla id camp", "id camp december".
2. **Every match comes through a head coach's name:** Coaches, then Programs. Examples: "erica dambach", "waldrum" (PR 8).
3. **A collision: the whole query is one fact (a conference or its alias, a region, a state name, or a capital state code) and also a program's search name.**
   - The fact's own section leads: Conferences for a conference, Lists otherwise.
   - The exception: when the query is exactly one program's displayed name (`shortName || name`), Programs leads (decision M).

   For example:
   - "American", "Texas", "Washington" and "New York" → Programs (each is a displayed name);
   - "MAC" → Conferences (Mount Aloysius's search name is "MAC", but its displayed name is "Mount Aloysius");
   - "New England" → the Northeast list ("New England (ME)" and "New England (NH)" are the displayed names);
   - "NE", "DE", "NC" in capitals → their state lists.
4. **The only fact is one conference:** Conferences, then Programs, and no list row. The conference row is that conference's list. Examples: "big ten", "b1g", "wcc", "ivy league", "metro" ("metro" is only a name prefix of Metropolitan State, not one of its search names).
5. **Facts only, with no name words:** Lists, then Programs. Examples: "d3 ohio", "TX", "LA", "d1", "small d3 under 30k", "schools in texas".
6. **Otherwise:** the section whose first row is the strongest match comes first, with Programs winning a tie.

What this gives for the queries the reviews named:

| Query | Rule | Sections in order |
|---|---|---|
| big ten, b1g, wcc, ccaa, nescac, ivy league, pac 12, uaa (F01-F08) | 4 | Conferences, Programs |
| metro (X03) | 4 | Conferences, Programs |
| mac (X01) | 3 | Conferences, Programs |
| american (X02) | 3 | Programs, Conferences (American as a fact; then American Rivers, American Southwest and Great American by the whole word) |
| new england (X04) | 3 | Lists, Programs, Conferences (Conference of New England, NESCAC and NEWMAC by whole words) |
| new york (L04) | 3 | Programs, Lists, Conferences (the CUNY and SUNY conferences by whole words) |
| NE (X06), DE (X09), NC (X10) | 3 | Lists, Programs |
| west virginia (G08) | 3 | Programs, Lists (West Virginia is a displayed name; the WV list follows) |
| d3 ohio (D01), division 1 west (D06), TX (L03), d1 (E09) | 5 | Lists, Programs |
| saint (E15) | 6 | Programs, Conferences (both first rows are exact, so Programs wins the tie) |
| a (E02), st (E03), cal (S02), university of michigan (S06), penn state (S07) | 6 | Programs (no conference row, section 5.2) |
| university (E06), womens soccer (E14) | too broad (4.1) | Programs (E14 has no rows) |

### 5.4 Best match and Enter
- **Best match:** when exactly one exact whole-name row exists across all sections, it is promoted to the top as "Best match" (`ecnl:public/search/slate.mjs:65-74`).
- **Enter opens:**
  1. the active option;
  2. else the best match;
  3. else the first row of the first section.

  So a facts-only query opens the filtered Programs list, as Enter on a place does today (2535-2540), and "big ten" opens the Big Ten's list.
- **Enter waits** while the data is loading.
- **On a too-broad slate** (rule in 4.1), steps 2 and 3 are skipped: Enter opens only an option the visitor has moved to, and otherwise does nothing. The status line asks for another word (E06, E14). The one exception is the owner with Ask on: on a slate with no rows, Enter asks, as section 5.7 says. The judged runs have Ask off.

### 5.5 Links, and how each is checked
The CollegeDash `destinationProblem` runs on the fixture. It uses the page's own parsers and filters, sliced from `index.html`, and does not re-implement them (lesson 5).

| Row or link | Link | Checked by |
|---|---|---|
| program | `#/p/<slug>` or `#/p/<slug>/<tab>` | The slug is in the fixture and the tab is in TABS (5506). A tab the program has no data for lands on Overview with the page's own notice (5598-5604, pinned by `tests/section_hiding.test.mjs:335`); that fallback is accepted. The "camps" tab word links to the camps tab only for programs with an upcoming ID camp row in the search file. |
| list row | `#/programs?…`, facts only | Written by `listHashOf` (3591) and read back by `listStateOf` (3606) with nothing dropped. **The count shown equals the rows `matchesFilters` keeps on the fixture.** |
| conference | `#/programs?conf=<division>:<name>&sort=name` | The same as a list row: written by `listHashOf`, read back by `listStateOf` to that one conference key (`confKeyOf`, 2089), and **the "N programs" on the row equals the rows `matchesFilters` keeps.** |
| Programs "Show all N", facts only | the list row's or conference row's address | **The same count check.** |
| Programs "Show all N", with name words | none: expands in place | The expanded rows are exactly the engine's N. |
| camp | `#/p/<slug>/camps` | The slug exists, and the camp is in the fixture's camps for that program. |
| Camps "Show all N", facts only | `#/camps?…` | The CAMPS_PARAMS parser (4330) keeps every value, and **the count equals the camps the page's own `campsMatch` (4404-4415) keeps on the fixture's `campsData` set (4438-4451)**, with the Shortlist toggle off. |
| Camps "Show all N", with name words | none: expands in place | The expanded rows are exactly the engine's N. |
| coach | `#/p/<slug>/staff` | The slug exists, and that program's head coach has this name. |

### 5.6 Empty and special states (typed reasons)
- **help** (empty box):
  - a scope line counted from the data at run time, such as "1,011 programs in 95 conferences, 81 upcoming ID camps", where conferences are the distinct names other than Independent;
  - example chips, and on desktop the key footer (as #447, 2558-2575).
- **loading:** "Getting search ready…".
- **no-match:** "Nothing matches “zzzz”", with 2 example chips.
- **partial:** a list row with notices, or rows that match some of the words, each labelled.
- **too-broad** (C19; the exact rule is in 4.1): a status line with the count, the capped program rows the shared words find if any ("Show all" expands in place), no other section, and Enter does nothing unless an option is active.
- **impossible:** "No D3 program is in the SEC".
- **no-upcoming-camps:** "Stanford lists no upcoming ID camps", a note on the Stanford program row, not a Camps row (M04).
- **not-applied notices** (section 4.6).
- **failed** (PR 6b): the names-only fallback and a "Try again" button.
- **version mismatch** (PR 6c): "Search was updated while this page was open", with a Reload button (`role=alert`).
- **data refreshed** (PR 6c, section 3.8): a quiet line, with no counts on links.

### 5.7 The header box and Ask
**Recommendation: they coexist in phase 1, and a merge is decided later, on measurement (decision J).**
- **The header box keeps its job.** `#q` stays on Programs, profiles and ID Camps.
  - On Programs, typing filters the list and writes `q=` into the public address (#14) under #23's filter rules. On ID Camps it is the camps search (#471).
  - Making it universal would change those contracts, and many pinned tests, at once.
- **Never two boxes on one screen.** On Home only the new box shows; the header box stays hidden there by `body.no-search` (725).
- **After PR 8,** with the Home box measured, the owner decides whether the header box's suggestions use the same engine on every page.
  - Typing on Programs would still filter the list.
  - The old matcher, and the Programs page's `q=` reading, would be retired only after that, by the freeze, measure, retire pattern.
  - That is also when "Show all" for name queries could become a link.
- **Ask stays owner-only (PR 6e, decision K).**
  - With Ask on, the Home box shows "Ask: …" as its last option.
  - Shift+Enter always asks; Enter asks only when the slate is empty, as the header box does (2532-2534).
  - With Ask off there is no Ask option and no request (the `tests/ask_page.test.mjs` pattern).
- **A reported measure, not a gate:** the 42 Ask eval questions (`tests/fixtures/ask/eval.json`) are run through the offline reader to show how much of Ask's job the free box does.

## 6. UI

### Placement
- Home keeps its heading, its one line and its three options (renderHome, 3729-3739).
- The box goes between the line and the options:
  - full width up to 720 px, 52 px tall on desktop;
  - a placeholder that names what it searches, such as "School, conference, state, coach or camp…", growing as the kinds ship.
- Nothing else is added to Home. There are no chips on the page (#465 removed them); chips appear in the panel on focus.
- The mockup shows whether the "Search CollegeDash" label is visible or for screen readers only (decision B).

### Desktop and tablet (wider than 768 px), PR 6b
- **The hero holds the combobox input itself.**
- The panel opens under the box, at the same width, over the three options. Its maximum height is min(70vh, 640px), and it scrolls inside.
- It has a heading per section, two-line rows (the name, then the program line), "Show all N" per section and a key footer.
- **Until PR 6d lands, the box is hidden at 768 px and narrower**, so phones keep today's Home.

### Phone (768 px and narrower; isPhone, 1444), PR 6d
- **The hero holds a button styled as a search field** ("Search CollegeDash…"), as ECNL's land-search does (`ecnl:public/index.html:8354`). So its role matches what it does: it opens something.
- **Tapping it opens a full-screen sheet** (`role=dialog`, `aria-modal`, labelled "Search") and focuses the sheet's own combobox input in the same tap.
  - The sheet is built on the page's `phoneSheet()` (1457-1473), as the Programs and ID Camps sheets are. That helper gives:
    - the dialog role;
    - inert book-keeping: the page behind (`#main`, the header and the bottom bar) is made inert while the sheet is open and released when it closes, and only what the sheet made inert is released;
    - widening past 768 px closes the sheet.
  - Leaving Home with the sheet open releases inert, as route() does for the camps sheet (`campsInert(false)`, 3777).
- **Closing:**
  - Escape closes the panel's options first; a second Escape (or Escape on an empty box) closes the sheet.
  - Cancel closes the sheet.
  - Both return focus to the hero button.
  - Tab stays inside the sheet.
- Rows are at least 44 px tall.
- No horizontal scroll from 320 to 400 px, checked with a CSS cascade test in the style of `tests/header_narrow.test.mjs`.
- The Home header stays one row (879).

### Keyboard and ARIA
An ARIA 1.2 editable combobox, as in #434, #445 and #447.
- **The input:**
  - `role=combobox`, `aria-autocomplete=list`, `aria-expanded`;
  - `aria-controls` pointing at the listbox, which is always in the DOM;
  - `aria-activedescendant` naming the active option;
  - `aria-describedby` pointing at a hint;
  - the label "Search CollegeDash".
- **The listbox:**
  - one `role=group` per section, labelled by its heading;
  - options with `role=option` and ids, and `aria-selected` on the active one;
  - each option's accessible name includes the division, for example "North Carolina, D1, ACC, Chapel Hill, NC".
- **One polite live region,** written only when its text changes, once results settle. For example: "9 results in 3 sections. Enter opens North Carolina." It is a new id, added to the list in `tests/route_focus.test.mjs:198-203`.
- **Keys:**
  - Down/Up move through the options across sections, and wrap;
  - Enter opens;
  - Escape closes the panel, then clears the box (on a phone, then closes the sheet);
  - Tab closes the panel and moves on;
  - "/" focuses the box on Home;
  - Shift+Enter asks (owner only, PR 6e);
  - Home and End stay caret keys.
- **Mouse:** a mousedown on the panel keeps focus in the box. Hover never moves the active option on touch screens.
- **Focus after choosing:**
  - a program row moves focus to its page's `h1`, as `openFromSearch` does (2633-2642);
  - a list or conference row lands on the Programs heading.

### Drawing (phone speed)
- The first slate is at most 18 rows and 5 headings.
- The drawing is counted per keystroke (options created, characters written) and pinned on the fixture (PR 6a).
- ECNL's painter comes in only if PR 6b's browser check misses its targets (section 7.5).

### Dark mode
- Only the page's own colour tokens are used: `[data-theme="light"]` (33) and `[data-theme="dark"]` (47), for example `--bg-surface`, `--border`, `--text-secondary`, `--accent` and `--accent-surface`.
- No literal colours in the new CSS rules.
- AA contrast is checked in both themes, as `tests/conference_counts.test.mjs:225-251` does, for the box text, placeholder, headings, secondary text and the active row.

### The division on every program result (team rule)
- **Program rows** use `programLine` (2014-2017), which starts with the D1/D2/D3 tag (`divisionTag`, 2009).
- **Camp and coach rows** show the program's `displayName` (1018) and its division tag.
- **Conference rows** show their division: "Big Ten · D1 · 18 programs".
- **List rows** name their division or divisions, or "D1–D3".

A test in PR 6a checks that every option tied to a program carries `class="div-tag"` with that program's division and shows `shortName || name`. Because the page passes in its own helpers, the markup is the page's.

### What opening a list or conference row does to saved filters
A list or conference row is an ordinary `#/programs?…` link. Like any shared Programs link, opening it applies the address's filters and saves them as the visitor's filters (`listArrive` → `saveState`, 3661-3675).
- With "small" = under 5,000 (decision L), the Programs page shows an "Undergrads < 5,000" condition chip, not the cards' "Small" bracket.
- The mockup shows both, and the owner rules on it under L.

### Tests that change on purpose (decision A)
- **`tests/shell_nav.test.mjs:60-70`** (PR 6b): Home may draw the new box. There is still exactly one `#q`, and Home still never reaches for `#q`.
- **`tests/shell_nav.test.mjs:259-280`** (PR 6b): "/" on Home focuses the Home box.
- **`tests/shell_nav.test.mjs:282-300`:**
  - PR 6b: Home is a heading, one line, the box and three options;
  - PR 6d: the phone hero's `<button>` is allowed.
- **`tests/route_focus.test.mjs:198-203`** (PR 6b): one new polite live region, eight in all.

## 7. Measurement

### 7.1 The judged set
**Starting point:** `scratchpad/search507/judged-draft.json`.
- **79 queries in 11 groups:** school-names 8, typos 7, nicknames 5, conferences 8, collisions 8, division-place 6, places 6, people 9, camps 6, attributes 6, edge 10.
- **Stability:** 57 frozen, 5 slow, 17 live.
- **Draft decisions C01-C19:** 29 queries depend on them. Section 9 maps each one to a ruling.

**PR 1 turns it into `tests/search/queries.json`: 93 queries in 12 groups.**

| Group | Queries |
|---|---|
| school-names | S01-S07, S09, S10, S11 (10) |
| typos | Y01-Y04, Y06-Y08 (7) |
| nicknames | K01, K02, K04-K06 (5) |
| conferences | F01-F08 (8) |
| collisions | X01-X10 (10) |
| division-place | D01-D07 (7) |
| places | L01-L06 (6) |
| people | H01, H03, H04, H05 (4) |
| camps | M01-M07 (7) |
| attributes | A01-A06 (6) |
| edge | E01-E15 (15) |
| state-words | G01-G08 (8) |

By stability, 74 are frozen, 5 slow and 14 live.

**The schema (`judged.mjs`, after `ecnl:tests/search/judged.mjs:133-183`):**
- **Every query carries `first`**, ECNL's `useful`: the rows any of which is a useful Enter target.
- **An `empty` ref names a slate state:** `help`, `no-match`, `too-broad` or `impossible`. Section 7.2 says how each is scored, including a too-broad slate that has rows.
- **A live query keeps `first`, `sections`, `mustShow` and `mustNever`.** It may never carry `top`, `exact` or `order`, as ECNL's rule at 153-155 says. So PR 7's and PR 8's tests on M03, M04, H01 and H04 check `first` on live queries legitimately.
- **A `pending` marker** may sit on a query or on a single ref: `"PR 5"`, `"PR 7"`, `"PR 8"` or `"phase 2"`.
  - A check whose marker names a PR later than the engine's level reports `pending`, which is neither pass nor fail.
  - A `phase 2` check stays pending through phase 1 and must give its reason in `note`.
  - At PR 8 a test requires that no `"PR n"` marker remains.
  - This replaces revision 1's hand-kept KNOWN_UNSUPPORTED list, so the support table in 7.4 is computed from the file, not written beside it.

**What PR 1 changes from the draft:**
- **It applies the owner's rulings** (section 9).
- **It renames the conference queries from C01-C08 to F01-F08**, so a query id never looks like a draft decision id. F02 is "b1g".
- **It renames the `people` section to `coaches`**, the only people phase 1 shows.
- **It drops R01-R05** (player names, mostly minors) while players are out of scope (decision D).
- **It fixes the sections to section 5.3's rules:**
  - X04 "new england": first = the Northeast list; sections Lists, Programs, Conferences. mustShow keeps both New England programs, western-new-england and the Northeast list. The two programs tie on match class, score and division, so their order falls to the name tie-break and is not pinned.
  - X06 "NE": first = the Nebraska list; sections Lists, Programs. mustShow keeps both New England programs, nebraska and creighton.
  - X02 "american": sections Programs, Conferences.
  - L04 "new york": sections Programs, Lists, Conferences, and first = new-york only.
  - E09 "d1" and A02-A06: sections Lists, Programs. A facts-only slate previews the members in Programs.
  - L01 "boston", L05 "chicago", L06 "philadelphia", X07 "columbia" and X08 "miami": sections Programs only, because a city gives no list row (decision S).
    - L06's first becomes any of the 8 Philadelphia programs, labelled "in Philadelphia, PA".
    - L01 keeps first = boston-university or boston-college, and its mustShow northeastern and emerson-college (in Boston).
  - X05 "LA": first = the Louisiana list only; the Los Angeles reading becomes program rows labelled "in Los Angeles, CA", if M approves the alias.
  - M04 "stanford camps": sections Programs only; first = stanford, with the no-upcoming-camps note on its row.
  - F01-F08, X01 "mac" and X03 "metro" keep the draft's Conferences, Programs and their conference-first `first`.
  - **Every `sections` list is checked against the rules that make sections,** on the fixture, with the read-only scripts `chitu-r4/conf_rule_final.py` (conference rows, 5.2) and `chitu-r4/list_rows.py` (list rows, 4.3). Both approximate the reader, and PR 1's reviewer re-runs them.
    - Conference rows go only to F01-F08, X01-X04, L04 and E15. So E15 gains Conferences; S02, S06, S07, E02, E03, E06 and E14 keep Programs only (5.2 lists why for each).
    - List rows go only to queries whose `sections` already include Lists, and to D07 "sec d3", whose two facts can't hold together, so it gets the impossible state instead of a row (4.3; the script does not model that). S06 "university of michigan" would have gained one through its Michigan fact; the "of" rule in 4.3 keeps it out.
    - A01, A04 and A06 are not in the script's output, because it reads their phase-2 words as name words. The reader names those words back instead (4.6), so each still gets its D1 list row, as its `first` says.
- **It lists every equally good answer in `first`, by a stated rule** (section 5.2):
  - K06 "bulldogs", by the tie rule: every D1 program whose nickname is Bulldogs (14 of the 27 Bulldogs on the fixture). They tie on class and score, and D1 sorts first.
  - E02 "a", by usefulness: every program with a word starting with "a" in its displayed name, full name, a search name or its nickname. On the fixture that is 140: 121 through a name, plus 19 only through the nickname, such as uc-irvine ("Anteaters") and san-diego-state ("Aztecs"). One letter is the start of a name the box searches, and a nickname is one (section 5.2). A row reached only through a city or a head coach is not useful.
  - E03 "st", by usefulness: every program with a word in its displayed name, full name, a search name or its nickname that is "saint" or starts with "st". On the fixture that is 225: 215 through a name, plus 10 only through the nickname, such as fairfield ("Stags") and heidelberg ("Student Princes"). That covers St. John's, Saint Louis and Mount St. Mary's (exact-word matches, which may rank first), Stanford and Stony Brook (prefixes), and the State schools whose NCAA name says "St.".
  - Words are normalised as section 4.1 says: ECNL's normalise, with `normText`'s "&" rule (1061-1062). So "&" is dropped, and "and" counts as a word that starts with "a". The counts are from `scratchpad/search507/chitu-r4/facts_r4b.py`, and they match the review's own (121 and 19; 215 and 10).
  - E02 and E03 are not too broad (section 4.1). They keep their draft `sections` (Programs) and E02 its mustNever on an Alabama list.

  PR 1 derives each list from the fixture by its stated rule, and a reviewer re-derives it.
- **E06 "university" agrees with the rule in 4.1.** "university" is a shared word, so the query is too broad. `first` is `{empty: too-broad}` and `sections` is Programs: the capped rows of the 761 programs with "University" in a name. Section 7.2 says how it is scored with those rows present.
- **It fits the queries phase 1 can't fully answer** (marked, never silently weakened):

  | Query | Draft expectation | Phase 1 expectation | Pending |
  |---|---|---|---|
  | A01 "d1 blue snow psychology" | a list filtered by D1, blue and snow | first = the D1 list, labelled partial; mustShow notices for "blue", "snow" (phase 2) and "psychology" (not in data); mustNever rochester (D3) | the blue/snow list, buffalo, canisius, notre-dame and marquette, and the mustNevers florida, ucla, vermont and minnesota: `phase 2` (C06, C16) |
  | A04 "catholic d1" | a religion list | first = the D1 list, labelled partial; mustShow a notice for "catholic" | the religion list and the mustNevers byu and baylor: `phase 2` (C18) |
  | A06 "d1 schools with no snow" | a snow-free list | first = the D1 list, labelled partial; mustShow a notice for "no snow" | the snow-free list and the mustNevers buffalo, syracuse and notre-dame: `phase 2` (C16) |
  | M01 "camps near denver" | camps by distance | mustNever the utah-valley camp ("The Den…"), active from PR 7 | first, mustShow and sections: `phase 2` ("near", C14) |
  | M07 "camps in colorado" (new, live) | — | first = colorado-colorado-springs "Elite ID Camp" (2026-10-24); mustShow colorado-state "December ID Camp" (2026-12-13); mustNever the utah-valley camps; sections Camps | from PR 7. It is the phase-1 way to ask M01's question. |
  | H03 "anson dorrance" | a former coach | mustNever a head-coach row for Dorrance, active from PR 8 | first and mustShow: `phase 2` (former coaches) |
  | H04 "waldrum" | Ben and Randy Waldrum | first and mustShow = Ben Waldrum, Pittsburgh's head coach in the index | Randy Waldrum (Technical Director, not in the index): `phase 2` |
  | H05 "chris ducar" | an assistant coach | — | the whole query: `phase 2` (assistants) |
  | E07 "smith" | smith-college first; Shelley Smith among the rows | first = smith-college; mustShow smith-college and hobart-william-smith, from PR 3 | the coach Shelley Smith (South Carolina's head coach in the index) and the Coaches section: `PR 8` |
  | Y07 "umass boston" | massachusetts-boston first | the same | the whole query: `phase 2`, unless decision U adds a cited alias and a fixture refresh includes it |

- **It adds 19 queries:**
  - tab words: S10 "stanford roster", S11 "unc schedule";
  - words named back: E11 "mvla", E12 "bay area", E13 "nursing";
  - E14 "womens soccer": too broad with no rows (no program name has either word). `first` = `{empty: too-broad}`; `sections` none;
  - E15 "saint" (section 4.1):
    - `first` = any of the 39 Saint-side programs: those with the word "saint", or a "st" that means Saint, in their names. The 40th program with the word "saint", cal-state-fullerton, has it only from the build's swap ("Cal Saint Fullerton"), and the rule reads it as State. So `first` and mustNever no longer overlap;
    - `sections` Programs, Conferences, with Conferences `pending: "PR 5"`. Both first rows are exact matches, so Programs leads (5.3 rule 6);
    - mustShow the D3 St. Louis Intercollegiate Athletic Conference row (`pending: "PR 5"`), found through the saint/st twin (5.2);
    - mustNever ohio-state, alabama-state and cal-state-fullerton, whose "St." or build-made "Saint" means State; and the D2 Sunshine State Conference row (`pending: "PR 5"`), because a typed "saint" never looks for "state";
    - six programs whose only match is the nickname "Saints", such as siena-college, match "saint" as a prefix. "saint" has 39 exact matches, and exact ranks above prefix (5.2, step 1), so those six may show but never come first, and are not in `first`;
    - today's box passes the mustNever on cal-state-fullerton (the 32nd of its 46 hits, outside the 6 it shows), so the engine must pass it from PR 3;
  - one impossible fact: D07 "sec d3";
  - M07 "camps in colorado" (above);
  - X09 "DE" and X10 "NC" (capital codes that are also built initials, decision M): first = the Delaware list and the North Carolina list; sections Lists, Programs. Neither pins Davis & Elkins or the North Centrals, whose "DE" and "NC" may go when the initials rule is fixed;
  - a new "state-words" group:

    | Id | Query | first | mustNever |
    |---|---|---|---|
    | G01 | d3 in ohio | the {D3, OH} list | depauw, earlham-college (D3, Indiana); any list row with state IN |
    | G02 | d1 or d2 | the {D1, D2} list | any list row with state OR |
    | G03 | schools in texas | the {TX} list | any list row with state IN; depauw |
    | G04 | id camps texas | ID camps in Texas | any list row with state ID; the program idaho |
    | G05 | portland me | southern-maine | portland, portland-state, lewis-clark-college (Portland, OR) |
    | G06 | D3 IN OHIO | the {D3, OH} list | any list row with state IN; depauw |
    | G07 | D1 OR D2 | the {D1, D2} list | any list row with state OR |
    | G08 | west virginia | west-virginia | any list row with region West or state VA; western-michigan; virginia |

    G08 pins the longest phrase first (4.3 rule 1): "west virginia" is the one fact WV, and it is exactly west-virginia's displayed name, so Programs leads (5.3 rule 3). Its `sections` are Programs, Lists. Its mustShow is the {WV} list (15 programs, all Mid-Atlantic), west-virginia-state and west-virginia-wesleyan-college.

- **It freezes the clock** at `now` 2026-10-20T16:09:38Z, zone America/Los_Angeles (decision N). The draft's own run lost a camp because it read the machine's date.

**Held-out queries, reported and never a gate:**
- PR 3 commits about 20 queries written by Huatuo. They are never seen while tuning. The precedent is `tests/fixtures/recs/heldout_reviewer.jsonl` and `docs/recs-heldout-review.md`.
- Before PR 8's final measurement, Bianque writes a fresh batch of about 15, because the first batch has been visible during PRs 5-8. PR 8 reports both batches.

### 7.2 Scoring
**Per query,** each check is pass, fail, unsupported (the engine has no such section or ref kind) or pending (section 7.1):
- **mustShow and mustNever**, over all of a section's rows, as ECNL does.
- **Section order.** ECNL's rule (`ecnl:tests/search/judged.mjs:524-532`): the non-empty sections, ignoring sections that hold only partial matches, must equal the judged list in order. A list row labelled partial (section 4.6) is a full row for this purpose. Sections still pending are removed from the judged list first, and the check then reports pending instead of pass.
- **First useful:** is the Enter target one of `first`?
  - A list ref matches any destination that opens exactly the ref's programs on the fixture, as the page's own filters compute them.
  - So today's place list for "TX" (2538, then `showPlaceList`, 2644) counts as useful when it opens exactly Texas's programs, and today's "ohio" list (44 rows, 5 of them by name) does not.
  - **An `empty` ref.** Every engine's outcome carries `state`, the slate's typed state (`help`, `no-match`, `too-broad`, `impossible`, or none). An `{empty: {reason}}` ref passes when `state` equals its reason and the outcome has no Enter target.
    - For `help`, `no-match` and `impossible`, the slate must also have no rows. That is ECNL's rule for every empty ref (`allRows.length === 0`, `ecnl:tests/search/judged.mjs:548`), kept for these three.
    - For `too-broad`, rows are allowed: they are the capped slate (section 4.1). This is the one change to ECNL's `evaluate`. Without it E06 could never pass, because its slate has rows by design.
    - The new engine reports `state` from its slate. Today's adapter reports it as section 7.3 says, and never reports `too-broad` or `impossible`, which today's boxes don't have.
- **Exact top** (frozen queries only).
- **Destinations:** every link resolves and every count matches (section 5.5).

**Per group and overall:**
- the first-useful count;
- pass, fail, unsupported and pending counts;
- must-never hits and wrong destinations;
- the section-order agreement rate.

**Graded measures,** so the set doesn't saturate: per section, the reciprocal rank of the first useful row, and how many mustShow rows appear within the first-show rows.

**Baselines.** Both engines run on the frozen fixture in CI, and each must equal its recorded baseline query by query (`ecnl:tests/search-judged.test.mjs:160-167`):
- `tests/search/baseline/today.json`;
- `tests/search/baseline/engine.json`.

Every engine PR re-records `engine.json` and explains the change in the PR.

### 7.3 Today's baseline
**"Today" is two frozen boxes, and a fixed rule says which one answers each query.**

**The rule** (`todayBoxOf(q)` in `tests/search/engines/today-adapter.mjs`):
- A query whose words, after `normText` (1061-1062), include "camp" or "camps" is scored against the **ID Camps box**.
- Every other query is scored against the **header box**, as it works on the Programs page.
- Why: a visitor looking for a camp today goes to ID Camps, where the header box is the camps search (#471). For anything else, the header box is today's search.
- On the 93 queries the rule sends 8 to the ID Camps box (M01-M07, and G04 "id camps texas", which sits in the state-words group) and the other 85 to the header box.
- `baseline/today.json` records, per query, the box used, its rows, its Enter target, its `state` and each check's status. A test checks every recorded box against `todayBoxOf`.

**The frozen slices.** `tests/search/engines/today.js` is a verbatim copy of these slices of `public/index.html` at `df9417725`. Each slice's line range and sha256 is in PROVENANCE, and none is ever compared with the current `index.html`.
- Header box:
  - 1061-1172: normalising, the place search, `matchScore`, `visibleMatches` and `searchMatches`;
  - 2535-2540: the Enter rule. A place hit opens the place list (`showPlaceList`, 2644); otherwise the top hit opens. This slice is the tail of `searchKeydown` (2512) and starts with `else if`, so `today.js` puts it, unchanged, inside a two-line wrapper, `function todayEnter(e) { if (false) {}` … `}`. The wrapper is part of `today.js` (whose own sha256 is in PROVENANCE) but outside the slice's hash;
  - 2566-2568: the help, phone and no-match chip lists;
  - 2577-2591: `SUGGEST_MAX`, `OUTSIDE_MAX` and `suggestionItems`, which decide the rows the box shows.
- ID Camps box:
  - 3582 and 3588: `LIST_Q_MAX` and `listQ`, which clean the typed text;
  - 4272: `CAMP_CLASSES`, which `campTally` reads (new in revision 4);
  - `campCmp` (4274-4275);
  - `campTally` (4283-4293), which `campsData` calls (4449) (new in revision 4);
  - `campIsPast` (4305-4308);
  - `campProgram` (4317-4324);
  - `campsQ` (4334), which the adapter calls to set the camps query (new in revision 4; revision 3 called it without freezing it);
  - the camps search, `campsNorm` to `campsQueryMatch` (4377-4402);
  - `campsMatch` (4404-4415). It reads `campAddDays` and `CAMPS_WHEN` only when a date window is set, which the default state never has. The adapter leaves both undefined, so a change that reached them would throw rather than pass quietly;
  - `campsData` (4438-4451).
- Every other name the slices read is either frozen above or a stub below. The baseline runs `today.js` in a `vm` context that holds only the adapter's stubs and the language built-ins, so a name missing from both throws a ReferenceError on the query that reaches it instead of reading something else.

**The adapter** (`tests/search/engines/today-adapter.mjs`) only supplies what the slices read from the rest of the page, and each stub is cited:
- `S` holds the fixture index, with no saved filters, `S.ask` false and `S.campsSaved` false. `S.favorites` is an empty Set (1403); `campsMatch` never reads it while `S.campsSaved` is false (4408);
- `S.qRaw` is the query and `S.q` is `normText(query)`, as `setQuery` sets them (2458-2459);
- `matchesFilters` returns true, and `isPhone()` returns false;
- `campsBox()` returns false (the camps slices never call it);
- for the Enter rule: `todayEnter` is called with `{ key: 'Enter', preventDefault() {} }`. `closeSuggestions()` (2631) does nothing. `showPlaceList()` (2644) and `openFromSearch(slug)` (2633) record the Enter target instead of navigating: the place list, or that program;
- `todayLocal()` (1005) returns the frozen clock's date in the frozen zone;
- the ID Camps state is the page's default, as `campsStateOf('')` gives it (4338-4356): no `when`, `from`, `to`, region, state, division or program, and `q` = `campsQ(query)`, as `campsTyped` sets it (4654-4656).

**How each box's outcome is scored:**

| | Header box (Programs page) | ID Camps box |
|---|---|---|
| Sections and rows | Programs: the program options `suggestionItems` shows (at most 6). Lists: its place option ("All N matching programs →"), as a list ref holding every visible hit, which is what `showPlaceList` opens (2644). Programs come before Lists, as the box draws them. | Camps: the camps `campsMatch` keeps from `campsData`, in the page's order (`campCmp`). |
| Enter target | The Enter rule (2535-2540): the place list when any hit is a place hit, else the top hit, else none. | Enter only commits the query and stays on the list (2515-2519). So the first listed camp stands for the Enter target: it is the first result the visitor gets. |
| `state` | `help` for an empty box (its chips, 2581); `no-match` when it shows the no-match chips (2590). | `no-match` when no camp is kept: the "No upcoming ID camp found … matching" card (4487-4494). |
| What it can produce | sections programs and lists; refs program, list and empty | section camps; refs camp and empty |

A check on a section or ref kind a box can't produce reports unsupported, as in ECNL (`ecnl:tests/search/judged.mjs:530-531`).

**The verdict labels are computed,** so PR 1's table can be re-derived. In order, the first that applies:
1. **answers:** every active check is supported by the box and passes. An unsupported check never counts as passing, so a query whose active checks the box can't produce is never "answers". For example, M04 "stanford camps" on the ID Camps box: its `first` is a program ref and its sections are Programs, which that box can't produce, so its passing camp mustNever alone doesn't make it "answers" (revision 3's "every active check passes" was vacuously true there);
2. **wrong:** a mustNever hit, or an Enter target that isn't in `first`;
3. **partial:** the Enter target is in `first`, or an active mustShow passes;
4. **nothing:** everything else.

**The target compares counts, not labels.** "No group worse than today" (section 7.4) compares, per group, the number of queries whose active `first` check passes, with each query scored against the box this rule gives it.

**The draft's run** used the header box only: its `today.box` in `judged-draft.json`. It ran on live data, with the machine clock at 2026-10-21, and its verdicts were given by hand. It also recorded the ID Camps box for M01-M06 as `campsPageBox`, but did not count it. Out of the draft's 79 queries: 21 answers, 11 partial, 2 wrong and 45 nothing.

The draft's hand verdicts, header box only:

| Group | Answers | Partial | Wrong | Nothing |
|---|---|---|---|---|
| school-names (8) | 7 | 0 | 0 | 1 |
| typos (7) | 0 | 0 | 0 | 7 |
| nicknames (5) | 4 | 0 | 0 | 1 |
| conferences (8) | 0 | 0 | 0 | 8 |
| collisions (8) | 2 | 5 | 1 | 0 |
| division-place (6) | 0 | 0 | 0 | 6 |
| places (6) | 4 | 2 | 0 | 0 |
| people (9) | 0 | 0 | 0 | 9 |
| camps (6) | 0 | 0 | 0 | 6 |
| attributes (6) | 0 | 0 | 0 | 6 |
| edge (10) | 4 | 4 | 1 | 1 |

**PR 1 re-measures** on the fixture, under the rule above and with the labels computed, and its description replaces this table with the computed one.
- **The camps rows will change.** Under the draft's ID Camps box, M02 "id camp december" found 13 camps with its `first` (Randolph-Macon's December ID Camp) at the top, and M03 "ucla id camp" found UCLA's College ID Camp. So at least M02 and M03 are expected to move off "nothing". The camps group also gains M07.
- Other rows may shift where the computed labels differ from the draft's hand verdicts, or where revisions 3 and 4 changed a query (E02, E03 and E06's `first`; the new E14 and E15). PR 1 lists each difference.

### 7.4 Targets
These are the pass criteria for every engine PR, applied to the checks active at that PR's level. They are final at PR 8.
- First useful better than today overall, and no group worse: per group, the number of queries whose active `first` check passes is never lower than today's on the same checks, with today's box chosen by the rule in 7.3.
- 0 wrong destinations, 0 must-never hits, and no active mustShow missing.
- Section order right on at least 90% of the queries whose section check is active.
- No check that passes today may fail.
- By the end of phase 1, a useful first result on every query whose `first` is active.
  - The only checks still pending at PR 8 are marked `phase 2`, each with its reason: players (dropped), colour, snow, religion, "near", former and assistant coaches, and Y07 unless decision U lands.
  - The owner accepts that list at PR 8.

**What each engine PR newly activates** (computed from the `pending` markers):

| From PR | Newly active |
|---|---|
| 3 (names) | school-names S01-S07, S09; typos Y01-Y04, Y06, Y08; nicknames (5); edge E01-E06 (E06 is the too-broad state), E08, E14, E07 except its coach check, and E15 except its conference checks |
| 5 (facts) | conferences F01-F08; collisions X01-X10; division-place D01-D07; places L01-L06; attributes: A02, A03, A05, and the phase-1 parts of A01, A04 and A06; edge E09-E13; E15's conference checks (its Conferences section, the St. Louis Intercollegiate row, and the mustNever on the Sunshine State row); state-words G01-G08 except G04; S10, S11 |
| 7 (camps) | camps M02-M07; M01's mustNever; G04 |
| 8 (coaches) | H01; H04's Ben Waldrum checks; E07's coach check and its Coaches section; H03's mustNever |
| phase 2 | M01's first, mustShow and sections; H03's first and mustShow; H04's Randy Waldrum; H05; the colour, snow and religion refs of A01, A04 and A06; Y07 unless decision U lands |

Pending checks are left out of a PR's comparison with today. This matters because today's place search already answers 4 of the 6 places queries, plus 2 partial, and engine 1 reads no place facts.

### 7.5 Budgets: work counts first, bytes, then clocks
**Engine work counts** (PR 3, extended in PRs 5, 7 and 8):
- Every prefix of every judged query is replayed, about 1,000 keystrokes.
- Counters: terms visited, edit-distance cells, postings visited, documents scored, rows sorted, sort comparisons.
- Weights fitted on the CollegeDash fixture turn the counts into estimated nanoseconds.
- The record (keystrokes, the worst keystroke and where it falls, p95) is pinned exactly.
- p95 stays under the phone ceiling (16 ms ÷ 15, as in ECNL, refitted), and the worst may not double (`ecnl:tests/search-modules.test.mjs:396-436`).

**Build work counts:**
- The one-shot build's counts (units, sorts, comparisons, strings normalised) are pinned exactly.
- No `localeCompare` during the build (`ecnl:public/search/vocab.mjs:34-36`).
- If the yielding build is adopted (section 2), its counts must be equal at step sizes 1, 7 and 50, and its slates must equal the one-shot build's on every judged keystroke.

**Drawing counts (PR 6a):** the options and headings created, and the characters written, per keystroke, pinned on the fixture. At most 18 rows on first show.

All bytes below are raw, or Python's `gzip.compress(…, 9, mtime=0)`, which is what the tests measure. That gives 159,823 B for today's `index.html` (the `gzip -9` command-line tool gives 159,715 B: it has its own deflate implementation, so its output differs from zlib's).

**The search code** (`tests/search_code_size_test.py`, new in PR 3, raised by each later PR within these ceilings). It reads code files only, never data. The ceilings below carry at least 5% margin over each PR's own estimate.
- **`public/search.js`**, total after each PR (raw / gzip -9):

  | After PR | Ceiling |
  |---|---|
  | 3 | 55 KB / 17 KB |
  | 5 | 80 KB / 24 KB |
  | 6a | 92 KB / 27 KB |
  | 7 | 97 KB / 29 KB |
  | 8 | 100 KB / 30 KB |

  For scale, `recs.js` is 27,322 B / 9,185 B. ECNL's nine modules are 140 KB raw, or 98 KB without `games.mjs`. The file is fetched at idle on Home only, never on other pages.
- **The Home-search block in `public/index.html`:** the code and CSS between `#507 search: begin` and `#507 search: end` comment markers (one script block, one style block). Each PR's addition is stated in the PR, measured against its base commit:

  | PR | May add (raw / gzip -9) |
  |---|---|
  | 4 (outside the markers: the State filter) | 10 KB / 3 KB |
  | 6b | 13 KB / 4 KB |
  | 6c | 3 KB / 1 KB |
  | 6d | 5 KB / 1.5 KB |
  | 6e | 3 KB / 1 KB |
  | 7 | 2 KB / 0.7 KB |
  | 8 | 1.5 KB / 0.5 KB |
  | Phase 1 total | 37.5 KB / 11.7 KB (38,400 B / 11,981 B) |

  The test checks the marker block against the running total for PRs 6b-8: at most 27.5 KB raw and 8.7 KB gzipped at PR 8.

**The whole page** (`tests/page_size_test.py`, new in PR 4). This is its own test, not part of the search code test, and its margin is stated.
- The ceiling is 582,000 B raw and 180,000 B gzip -9.
- That is today's 517,565 B / 159,823 B, plus phase 1's 38,400 B / 11,981 B, plus about 5% of today's size (26,035 B / 8,196 B) for other work and for zlib differences between machines.
- A PR that has to go past it raises the ceiling in the same PR and gives the reason, so growth is a decision rather than a drift.
- Revision 1 put this ceiling inside the search test at 173,000 B. That left about 1.2 KB of margin after phase 1, not the 5% it claimed.

**Clock limits, only as a backstop (Node):**
- no keystroke's search over 20 ms (the fastest of 3 runs);
- loading and building the index in under 150 ms of main-thread CPU (`process.threadCpuUsage`, the fastest of up to 7 fresh processes).

**The local browser check (decision O): `tools/search_browser_check.mjs`, committed in PR 6b.** It is not in CI. It decides whether the yielding build and ECNL's painter come in, so it is written to be repeatable.
- **Where it lives.** In `tools/`, not `tests/`:
  - so neither the Node suite discovery (`tests/**/*.test.mjs`, `.github/scripts/run_node_suites.py:66`) nor its orphan sweep (`tests/**/*.mjs` and the rest, 67, 73, 83-97, which flags any file there that names `node:test`) picks it up;
  - it is a plain Node script, not a `node:test` suite. It prints one JSON record and exits 1 when a target is missed or a request left the machine.
- **Playwright and Chromium.** CollegeDash has no `package.json`, and neither is a repo dependency, as in ECNL (`ecnl:tests/e2e/search-panel.e2e.mjs:7-8`).
  - **This environment already has both, and the check needs no network.**
    - Playwright 1.56.1 is at `/opt/node-tools/node_modules/playwright`, as its `package.json` says (and `playwright-core` 1.56.1 beside it).
    - The environment sets `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`. That folder holds `chromium-1194` (Chromium 141.0.7390.37) and `chromium_headless_shell-1194`, the revision Playwright 1.56.1's own `browsers.json` names.
    - Revision 2 said none was installed. That was wrong: it had looked only in `~/.cache/ms-playwright`.
  - **I checked that it runs**, read-only, with a throwaway script in my scratchpad. Under the dead proxy and `node --import tests/netguard/netguard.mjs`, Playwright launched that Chromium and loaded a test page from a loopback server. The page's Google Fonts stylesheet link, put there to test the route, was aborted, and nothing was answered off the machine. `Emulation.setCPUThrottlingRate` at 4x was accepted.
  - **Node.** `node` first on `PATH` here is 22.22.0 (`/opt/node22/bin`); `/usr/local/bin/node` is 20.20.0, and 21.7.3 is also present. There is no Node 24, which CI uses (`tests.yml:122`), on `PATH` or under `/opt`, `/usr` or `/root` (re-checked for revision 4). The script uses only `node:` built-ins that Node 22 and 24 both have, and its JSON record includes `process.version`.
  - **The script's header pins** Playwright 1.56.1 and Chromium 141.0.7390.37 (revision 1194).
    - It loads Playwright with `createRequire(process.env.PLAYWRIGHT_MODULES || '/opt/node-tools/node_modules/')`, ECNL's own default (`ecnl:tests/e2e/search-panel.e2e.mjs:24`).
    - It leaves `PLAYWRIGHT_BROWSERS_PATH` as the environment sets it.
    - It refuses to run when `playwright/package.json`'s version or `browser.version()` differs from the header.
    - Its JSON record names the Playwright, Chromium and Node versions it ran with.
  - **A fallback, only for a machine without them.** It uses the network: it is a tool install, not data, and never part of the check itself.

    ```
    npm install --prefix ~/.cache/collegedash-e2e playwright@1.56.1
    PLAYWRIGHT_BROWSERS_PATH=~/.cache/collegedash-e2e/browsers \
      npx --prefix ~/.cache/collegedash-e2e playwright install chromium
    ```

    Then run the command below with `PLAYWRIGHT_MODULES=~/.cache/collegedash-e2e/node_modules/` and that same `PLAYWRIGHT_BROWSERS_PATH`.
    - The fallback sets `PLAYWRIGHT_BROWSERS_PATH` itself because an environment like this one exports `/opt/pw-browsers`, which an install would otherwise write into.
    - This environment also sets `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`. In Playwright 1.56.1 that variable is read only on the npm-install path (`playwright-core/lib/server/registry/index.js:1268-1271`). An explicit `playwright install` still downloads, so on a machine that already has the browsers, the fallback is simply not run.
- **Serving the fixture.** `serve.py` serves `public/data`, not the fixture. So PR 6b adds `tools/search_fixture.py --serve PORT`, which:
  1. builds a temporary public tree: copies of `public/index.html`, `public/search.js`, `public/recs.js` and `public/assets/`, with the fixture's `programs.json` at `data/programs/index.json`, its `index.json` at `data/search/index.json` and its `camps.json` at `data/camps/index.json`;
  2. serves that tree on 127.0.0.1 only, with `serve.Handler`, after pointing `common.PUBLIC_DIR` at it. That is the same swap `tests/list_index_test.py:228-258` uses.

  So `/api/v1/programs` and `/api/v1/search` answer through `serve.py`'s own routes (section 3.4). `/api/v1/status` answers 404, because the tree has no `archive/`, and the page already ignores that (1742).
- **Blocking and counting off-machine requests,** as ECNL does:
  - The Python server runs with `PYTHONPATH=tests/netguard`, so `sitecustomize.py`'s guard applies, and with `HTTPS_PROXY` and `HTTP_PROXY` set to a dead proxy, `http://127.0.0.1:9`.
  - The Node script runs under `node --import ./tests/netguard/netguard.mjs`.
  - Chromium starts with `--proxy-server=127.0.0.1:9` and service workers blocked.
  - A context route continues only requests to the local origin (and `data:`/`blob:`), and aborts and records every other request. A `requestfinished` listener records any off-origin request that was answered anyway (`ecnl:tests/e2e/search-panel.e2e.mjs:43-54`).
  - The script fails if any request was answered off the machine. It prints the aborted list: Google Fonts (line 19) is the expected entry.
- **What it measures,** with Chromium's CPU slowed 4x (`Emulation.setCPUThrottlingRate` through a CDP session; ECNL's script does not throttle). Each number is the median of 3 runs:
  - keystroke to paint on Home: p50, p95 and worst, over every prefix of the judged queries typed into the box. The time runs from the input event to the second animation frame after the listbox settles, observed by a test-side MutationObserver installed with `page.addInitScript`. Targets: p95 ≤ 50 ms and **worst ≤ 100 ms** (ECNL's worst was 193 ms);
  - **first focus to ready** (fetch from the local server, parse, build), with a target of ≤ 400 ms;
  - the longest main-thread task during the build (`PerformanceObserver` for `longtask`), with a target of ≤ 40 ms. Missing it brings in the yielding build.
- **The command,** written in the script's header and in each visible PR:

  ```
  HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 \
    node --import ./tests/netguard/netguard.mjs tools/search_browser_check.mjs --runs 3
  ```

  - With no `PLAYWRIGHT_MODULES`, the script uses `/opt/node-tools/node_modules/`. `PLAYWRIGHT_BROWSERS_PATH` comes from the environment (`/opt/pw-browsers` here).
  - On a machine set up with the fallback, prefix the command with `PLAYWRIGHT_MODULES=~/.cache/collegedash-e2e/node_modules/ PLAYWRIGHT_BROWSERS_PATH=~/.cache/collegedash-e2e/browsers`.
  - The script starts `python3 tools/search_fixture.py --serve <free port>` itself and stops it at the end.
- **When it runs.** In PR 6b and in each later visible PR, with its JSON record in the PR. A reviewer re-runs the same command (lesson 7).

### 7.6 Network guard
- **Already in place:**
  - every Node suite runs with `tests/netguard/netguard.mjs` preloaded (`.github/scripts/run_node_suites.py:198-203`);
  - every Python suite runs with `tests/netguard/sitecustomize.py` (`.github/scripts/run_suite.py:64-70`);
  - any off-machine request fails the suite (exit 97).
- **The Home box tests pin exact request counts:**

  | When | Requests |
  |---|---|
  | Home loads | exactly today's four: `/api/v1/programs` (1717), `/api/v1/status` (1742), `api/status` (1744) and `api/ask/status` (1746). Home sends no perf report (3821). |
  | The page goes idle | at most 1 static request (`search.js`) |
  | First focus | exactly 1 API request (`/api/v1/search`), plus `search.js` if it hasn't loaded yet |
  | First focus on Save-Data | exactly 1 static request (`search.js`) plus 1 API request (`/api/v1/search`); none at idle before it |
  | Typing, moving, choosing | 0 |
  | Second focus | 0 |
  | After a 404 | no retry on that page |
  | Ask (owner, PR 6e) | exactly 1 `api/ask` POST per ask; none with Ask off |

  The harness answers every request with no `x-collegedash-session` header. So `noteSession`'s session-renewal `HEAD /` (1692-1700) never fires, and the counts are exact.
- **The builder** reads committed files only.
- **The local browser check** aborts and counts every request that leaves the machine (section 7.5).
- **Any live check after deploy,** such as confirming that `/api/v1/search` answers, needs the owner's OK, a fixed request budget and an offline dry run first.

### 7.7 Which data each test reads
**The rule.**
- A test that pins an exact number or an exact order reads the frozen fixture.
- A test that reads `public/data`, or builds from the committed sources, derives what it expects from the rows it loaded and pins no number.
- No CI test asserts anything about `public/data/search/index.json`, which is live data from its first build on. Two existing tests run `validate()`, and so reach `check_search_index()`, but neither can turn main red over it:
  - `tests/refresh_imports_test.py:60` runs `build.validate` on the committed tree and asserts nothing about the result (its output is discarded). Between PR 2's merge and the first build, the file is missing; the check reports that and returns False without raising (section 3.3), so this test stays green.
  - `tests/profile_pruning_test.py:362-366` asserts that validate passes, but on its own scratch build (paths swapped at 309), which writes its own search file. After PR 2 it also guards `check_search_index()` on a fresh full build, with no extra build in CI.

| Test | PR | Data | May pin exact numbers? |
|---|---|---|---|
| `tests/search_fixture_test.py` | 1 | fixture files and PROVENANCE only | yes (checksums) |
| `tests/search_judged.test.mjs` | 1 | fixture | yes |
| `tests/search_index_test.py` | 2 | fixture inputs, plus synthetic broken rows; a scratch copy for the `serve.py` route | yes |
| `tests/search_aliases_test.py` | 2 | `data/conference-aliases.json` and the fixture's conferences | no live data |
| `tests/refresh_commit_step_test.py` (added case) | 2 | scratch repositories with stand-in data | no data pins |
| `tests/camps_index_test.py` (added case) | 2 | its existing scratch build from the committed sources | no: compares two files of one run |
| `tests/data_api.test.mjs` (added cases) | 2 | a temporary directory, as today | no data pins |
| `tests/perf_worker.test.mjs` (added case) | 2 | a stub Worker environment, as #400's fit case does | no data pins (the route kind only) |
| `tests/profile_pruning_test.py` (existing, unchanged) | from 2 | its own scratch build from the committed sources | no: it asserts that validate passes |
| `tests/refresh_imports_test.py` (existing, unchanged) | from 2 | the committed tree | asserts nothing about validate's result |
| `tests/search_engine.test.mjs` | 3 | fixture | yes (work counts) |
| `tests/search_code_size_test.py` | 3 | `public/search.js`, `public/index.html` (code) | yes (byte ceilings) |
| `tests/page_size_test.py` | 4 | `public/index.html` (code) | yes (byte ceiling) |
| `tests/state_filter.test.mjs` | 4 | the page harness, with fetch answered from the fixture's `programs.json` | yes ("21 D3 Ohio programs" is a fixture fact) |
| `tests/list_url_state.test.mjs`, `tests/programs_rail.test.mjs` (added cases) | 4 | `public/data`, as today (`list_url_state.test.mjs:15, 33`) | no: expected rows are computed from the loaded index, e.g. `INDEX.programs.filter(p => p.division === 'D3' && p.state === 'OH')` |
| `tests/search_panel.test.mjs` | 6a | fixture | yes (draw counts) |
| `tests/home_search.test.mjs` | 6b | the page harness, with fetch answered from the fixture's `programs.json` and `index.json` | yes |
| `tools/search_browser_check.mjs` (local, not CI) | 6b | the fixture, served by `tools/search_fixture.py --serve` | reports timings; pins none in CI |
| `tests/home_search_states.test.mjs` | 6c | the same as 6b, with a changed-stamp copy and a changed-schema copy | yes |
| `tests/home_search_phone.test.mjs` | 6d | the same as 6b | yes |
| `tests/home_search_ask.test.mjs` | 6e | the same, with Ask's status and answer stubbed as `tests/ask_page.test.mjs` does | yes |

## 8. Phased PRs, one at a time
How every PR works:
- it has its own sub-issue, says "Closes #<sub-issue>" and "Part of #507";
- its plan is approved before any code;
- its failing test is shown failing on main first;
- the full suites run exactly as `tests.yml` runs them, on Python 3.12 and Node 24 (`tests.yml:111, 122`). This environment has `/usr/bin/python3.12` (`python` on `PATH` is 3.11.15) and Node 22.22.0, with no Node 24. So a PR run here says which versions it used, and CI's run is the reference for Node 24;
- it states its byte measurements (section 7.5) and which data its tests read (section 7.7);
- the owner merges.

| PR | What | Visible | Mockup first | Tier | Decisions it needs |
|---|---|---|---|---|---|
| 1 | Judged set, frozen fixture, today's baseline | no | no | opus | A; the section 9 rulings marked "before PR 1" |
| 2 | Search data: builder, validate checks, schema, alias table, `/api/v1/search`, and the refresh, serve and scratch-build wiring | no | no | opus | E, F, I |
| 3 | Engine 1, names: matching core, Programs, slate, the too-broad state, links, code-size test | no | no | opus | — (the rulings before PR 1 cover it) |
| 4 | The Programs address gains `state=`, plus a State filter; the page-size test | yes | yes (its own) | opus | H |
| 5 | Engine 2, facts: reader, Lists, Conferences, notices, tab words | no | no | opus | Q |
| 6a | The pure panel renderer with draw counts (in `search.js`, not mounted) | no | the PR 6 set | sonnet | B |
| 6b | The Home box on desktop and tablet: mount, keys, ARIA, live region, "/", loading, failed with the names-only fallback; the local browser check | yes | the PR 6 set | opus | B, G, O, R |
| 6c | The version-mismatch and data-refreshed states | yes | the PR 6 set | sonnet | — |
| 6d | The phone: hero button, full-screen sheet, Escape, inert page, Tab trap | yes | the PR 6 set | opus | B |
| 6e | The Ask option (owner only) | owner only | the PR 6 set | opus | K |
| 7 | Camps section | yes | the PR 6 set | sonnet | — |
| 8 | Coaches section | yes | the PR 6 set | sonnet | — |

**The PR 6 mockup set** is approved before PR 6a. It covers:
- desktop and phone, light and dark;
- the hero on both;
- these states: help, loading, results with all five sections (Camps and Coaches rows included), best match, partial with a notice, no match, too broad, impossible fact, failed fallback, version mismatch, data refreshed, the Ask option, and a "small" list row opened on Programs (decision L).

**After phase 1** (owner decisions):
- the header box on the same engine, then retiring the old matcher (J);
- Home in #394's measured views, if R says so;
- phase 2 facets: colour, snow, public/private, religion;
- "near <city>" and assistant and former coaches;
- clubs and high schools, linking to Pipelines.

### PR 1: the judged set and today's baseline (opus, not visible)
**Files:**
- `tests/search/queries.json`;
- `tests/search/judged.mjs`: schema check (with the live rule and the `pending` marker), frozen clock, `evaluate` (with the `state`-based rule for empty refs, section 7.2), `summarise` (with the computed verdict labels, section 7.3), `destinationProblem`;
- `tests/search/engines/today.js` (the frozen slices, section 7.3) and `tests/search/engines/today-adapter.mjs` (the stubs, `todayBoxOf` and the two boxes' scoring);
- `tests/search/baseline/today.json`;
- `tests/fixtures/search/` (`programs.json`, `camps.json`, `PROVENANCE.json`);
- `tools/search_fixture.py`;
- `tests/search_judged.test.mjs` and `tests/search_fixture_test.py`.

**Fails on main** (none of these files exist there):
- `search_judged.test.mjs`: "today's frozen matcher, on the fixture, equals baseline/today.json query by query";
- `search_judged.test.mjs`: "the schema check refuses a live query that carries `top`, `exact` or `order`, and accepts one that carries `first`";
- `search_judged.test.mjs`: "a `pending: \"PR 8\"` check reports pending at level 3 and is evaluated at level 8";
- `search_judged.test.mjs`: "every query's recorded box in baseline/today.json is `todayBoxOf(q)`: the ID Camps box for M01-M07 and G04, the header box for the other 85";
- `search_judged.test.mjs`: "an `{empty: too-broad}` ref passes on an outcome with state too-broad, Programs rows and no Enter target, and fails when there is an Enter target; an `{empty: no-match}` ref fails when the slate has rows";
- `search_judged.test.mjs`: "an outcome with any unsupported active check is never labelled answers, even when every supported check passes (M04 on the ID Camps box)";
- `search_fixture_test.py`: "every fixture input and each frozen slice match their PROVENANCE sha256".

**Data:** fixture only (section 7.7).

**Risks:**
- Expectations copied from engine output. The rule is typed facts with cites, and a reviewer re-derives a sample, including every `first` list built by a stated rule (K06; E02 and E03 with their nickname-only rows; E15's 39) and every `sections` list, with the two scripts named in 7.1.
- A baseline that scores the wrong box. The box is chosen by `todayBoxOf`, recorded per query and checked against the rule; the verdict labels are computed (section 7.3).
- Live pins. Every exact number is on the fixture, and CI reads neither `public/data` nor git history.
- The fixture's size. Measured, with a 2.5 MB ceiling.
- Open rulings. PR 1 waits for the decisions marked "before PR 1".
- Minors' names. They are dropped from the set.
- A `pending` marker used to hide a failure. Every marker names a PR or gives a phase-2 reason, and PR 8's test refuses any `"PR n"` marker left.

### PR 2: the search data, built by the refresh and served at /api/v1/search (opus, not visible)
**Files:**
- `build.py`:
  - `search_path()`;
  - `search_index()` and `search_index_from_files()`;
  - `write_search_index()`, called after the camps index write (2261-2263);
  - `check_search_index()` in `validate()`;
- `collect/common.py`: `EMAIL_RE` (section 3.4);
- `schema/search.schema.json`;
- `data/conference-aliases.json`, with the four aliases the judged set needs (B1G, CCAA, NESCAC, UAA), each with its note (section 3.5);
- `.github/workflows/refresh.yml`: the tolerant restore line, and the search file in the comment at 270 and the messages at 324 and 340 (section 3.4);
- `serve.py`: the `search` route;
- `api/data-api.mjs`, `api/data-reader.mjs` and `docs/data-api.md` (the route row, the journey count at 75 and the index count at 78);
- `tools/search_fixture.py`, which now also writes the fixture's `index.json`;
- `tests/fixtures/search/index.json` and `conference-aliases.json`, with PROVENANCE updated;
- tests:
  - `tests/search_index_test.py` and `tests/search_aliases_test.py` (new);
  - `tests/refresh_commit_step_test.py`, `tests/camps_index_test.py`, `tests/seasons_test.py:190`, `tests/data_api.test.mjs` and `tests/perf_worker.test.mjs` (added cases).

The PR does not include `public/data/search/index.json`. The first `build_only` run or refresh after the merge writes it. Until then the route answers a JSON 404 and nothing reads it.

**Fails on main:**
- `search_index_test.py`:
  - "`search_index_from_files()` on the fixture inputs equals `tests/fixtures/search/index.json` byte for byte";
  - "on rows with a missing division, a non-numeric figure, an email-shaped program name, nickname, search name, city, head coach or camp name, a camp with no start date, and an alias whose conference is gone, `search_index()`:
    - returns a file and one `::warning` each, and never raises;
    - keeps every program row, with the bad values null;
    - leaves out only the bad camp rows;
    - and `validate` passes on the result";
  - "`validate` blocks a hand-edited search file";
  - "on those broken rows, `build()` followed by `validate()` prints each content `::warning` exactly once" (section 3.1);
  - "`check_search_index()` reports a missing search file and returns False without raising";
  - "the fixture-built file and 40 seeded subsets stay under 1,000 B + 75 B per program + 30 B per camp at gzip -9";
  - "`serve.py` answers `/api/v1/search` with the file's bytes, refuses `/data/search/index.json`, and answers 404 before the file exists" (modelled on `tests/list_index_test.py:22, 228-258`).
- `search_aliases_test.py`: "every alias entry quotes its alias, gives a URL and a checked date, and names a conference in the fixture".
- `refresh_commit_step_test.py`, the `search-restore` case (section 3.4): on main its control finds no restore line, and a run whose validate fails stops at the fifth-output assertion instead of saving its collection.
- `camps_index_test.py`: "the scratch build writes `<tmp>/search/index.json`, whose camps equal that build's camps index and carry no sentinel row". On main there is no search file.
- `data_api.test.mjs`: "`/api/v1/search` maps to `/data/search/index.json` and answers a JSON 404 before the first build". On main the route is unknown.
- `perf_worker.test.mjs`: "a `/api/v1/search` request is counted as one server point with route kind `search`, and carries nothing about the visitor" (modelled on 460-467). On main the route is unknown, so there is no `search` point.

**Risks:**
- **A validate failure withholds all site data.** Only the code-bug checks in section 3.3 may block; content is repaired or skipped with a warning. The broken-rows test pins this.
- **A refresh that fails after PR 2 loses its collection.** Without the restore line it would, so the line and its harness case ship in this PR (section 3.4).
- **The search file built from the previous run's camps.** The call comes after the camps write, and the scratch-build case pins it.
- **Daily diff noise.** One row per line, sorted.
- **Warning noise.** Each content warning is annotated once per run, by the build; validate's re-check discards them (section 3.1).
- **The gap between merge and first build.** The search file is missing until then; `check_search_index()` reports it without raising, and no CI test asserts on the live file (section 7.7).
- **Wrong alias evidence.** The quote is kept in the table and checked in CI when the entry is added.
- **Privacy.** Only head coaches' names are carried. The builder filters email-shaped strings from every string it copies, and validate checks the filter worked.

### PR 3: engine 1, names (opus, not visible; the page doesn't load it yet)
**Files:**
- `public/search.js`: normalising (with the shared words, and the State-side rule for "st" and build-made "saint", section 4.1), the name vocabulary, the matching core, Programs, slate (with the too-broad state, which draws Programs only), links, and the one-shot build;
- `tests/search_engine.test.mjs`: purity scan (with the export wrapper exempted, and a check that `globalThis` elsewhere is still flagged, section 2), the State-side indexing unit test, two time zones, work counts and build counts;
- `tests/search_judged.test.mjs`: the engine run and the pass criteria at level 3 (section 7.4);
- `tests/search/baseline/engine.json` and `tests/search/heldout.json`;
- `tests/search_code_size_test.py`.

**Fails on main:** the engine's judged run, for example:
- Y01 "standford" puts Stanford first (today: nothing);
- K05 "michigan wolverines" puts Michigan first (today: nothing);
- S09 "stanford soccer" puts Stanford first;
- E06 "university" gives the too-broad state, with capped Programs rows and no Enter target (today: Enter opens the first of 761);
- E15 "saint" puts one of the 39 Saint-side programs first and never shows Ohio State, Alabama State or Cal State Fullerton.

`search_engine.test.mjs` also has a unit test that fails on main (there is no engine): "on the fixture, cal-state-fullerton's search names 'Cal St. Fullerton' and 'Cal Saint Fullerton' are both indexed as 'cal state fullerton', and saint-louis's 'St. Louis' keeps its 'saint' twin". `search_code_size_test.py` fails on main too, because `public/search.js` doesn't exist there.

**Risks:**
- Typo false positives. Section 4.5's rules, plus the must-never checks.
- Over-fitting the set. The held-out queries report it.
- Weights tuned on ECNL. They are re-tuned here, with every change recorded.
- Places, conferences and collisions wait for PR 5. Their checks are pending, so they can't count as regressions.

### PR 4: the Programs address gains state=, plus a State filter (opus, visible, mockup first)
**Files:**
- `public/index.html`: `state` in LIST_PARAMS (3581), its reader and writer, `matchesFilters`, `confCounts`, the rail's State control and its chip;
- `tests/list_url_state.test.mjs` and `tests/programs_rail.test.mjs` (added cases, with expectations derived from the loaded rows);
- `tests/state_filter.test.mjs` (new, on the fixture);
- `tests/page_size_test.py` (new, section 7.5).

**Mockup:** the State control on the Programs rail, on desktop and in the phone sheet, and its chip.

**Fails on main:** `state_filter.test.mjs`: "on the fixture, `#/programs?div=D3&state=OH&sort=name` draws the 21 D3 Ohio programs and writes the same address back".
- On main, `state` is dropped and every D3 program shows.
- The 21 is a fact of the frozen fixture.
- The same assertion added to `list_url_state.test.mjs` computes its expected rows from `public/data` and pins no number.

**Bytes:** at most 10 KB raw / 3 KB gzipped added to `index.html`.

**Risks:**
- **The #14 public contract** ("may grow, never change meaning"):
  - old links must stay byte-identical;
  - `state` takes a fixed place in the canonical order (after `region`);
  - a value that isn't one of the 51 codes is dropped, as for every param.
- **Saved filters** (`cd.filters`) without a state must still load.
- **#23's Enter and counts** must respect the state.
- **State ANDs with region on Programs.** `matchesFilters` (3966-3973) ANDs every facet, so the new `state` test ANDs with `region`. That differs on purpose from the ID Camps page, whose `campsMatch` ORs region and state (4406). The engine's list rows AND them too (section 4.3), so a list row's count equals the page's. Section 5.1 already keeps the camps link from carrying both.
- **Two pinned tests change on purpose.** `tests/list_url_state.test.mjs:34` (its copy of the nine params) and `:456` ("a param outside the nine") pin LIST_PARAMS. PR 4 makes both ten and says so.
- **Ask, and ID Camps' own state filter,** stay untouched.

### PR 5: engine 2, facts (opus, not visible)
**Files:**
- `public/search.js`: the reader with section 4.3's reading rules (including the "of" rule), the fact vocabulary and the state-code rules, Lists and Conferences (with the word rule of 5.2, and conference rows linking to the facts-only Programs address), typed empty reasons, notices and tab words, and the "LA" city alias if decision M approves it (section 4.4);
- no new alias entries: all four judged aliases shipped in PR 2 (section 3.5);
- the engine tests, `baseline/engine.json`, and the count-equality destination checks for list rows, conference rows and Programs "Show all" links.

**Fails on main:**
- D01 "d3 ohio" puts the {D3, OH} list row first and never shows Ohio State or Ohio Dominican;
- F02 "b1g" puts the Big Ten conference row first, linking `#/programs?conf=D1:Big+Ten&sort=name`, with sections Conferences, Programs and no list row (today: nothing);
- D06 "division 1 west" never shows Western Michigan or West Virginia;
- G01 "d3 in ohio" never shows DePauw or Earlham; G02 "d1 or d2" and G07 "D1 OR D2" show no Oregon list;
- G08 "west virginia" puts West Virginia first, then the WV list, and shows no list row for the West region or for Virginia;
- the conference word rule (5.2): X04 "new england" shows the Conference of New England, NESCAC and NEWMAC rows after Programs; S06 "university of michigan" shows no Michigan Intercollegiate Athletic Association row and no Michigan list row; E03 "st" shows no conference row; E06 "university" and E14 "womens soccer" show no section but Programs; E15 "saint" shows the St. Louis Intercollegiate Athletic Conference row and never the Sunshine State Conference row.

**Risks:**
- Conference rows on name queries. The word rule in 5.2 is strict (whole words, shared words required, no lone short word, Programs only when too broad), and every judged `sections` list was checked against it on the fixture.
- State codes read where none was meant. Section 4.2's rules and the G queries guard against it.
- Collisions. Decision M, with the X queries.
- A filter that silently empties the results. Every empty has a typed reason.
- List and conference counts that disagree with the Programs page. They are checked with the page's own code on the fixture.

### PR 6a: the panel renderer (sonnet, not visible; inside the approved PR 6 mockups)
**Files:**
- `public/search.js`: `renderSlate(slate, helpers)`, which returns `{html, counts}`. The page passes its own `esc`, `programLine` and division-tag helpers, so the markup is the page's;
- `tests/search_panel.test.mjs`.

**Fails on main:** `search_panel.test.mjs` (`renderSlate` doesn't exist on main):
- "for 'big ten' on the fixture, the listbox has two groups, Conferences then Programs, each labelled by its heading, with unique option ids, and no Lists group";
- "for 'new england', the groups are Lists, Programs and Conferences, in that order";
- "every option tied to a program carries `div-tag` with its division and shows `shortName || name`";
- "the draw counts for every judged query equal the pinned record, with at most 18 options on first show".

**Risks:**
- Markup drifting from the mockup. The approved set is the reference, and the reviewer compares.
- Helpers sliced from `index.html` changing later. The test slices them fresh on every run, so the panel always uses the page's current helpers.

### PR 6b: the Home box on desktop and tablet (opus, visible; inside the approved PR 6 mockups)
**Files:**
- `public/index.html`, between the `#507 search` markers:
  - the box in `renderHome` (hidden at 768 px and narrower until PR 6d);
  - the panel mount, keys and ARIA;
  - one new live region and "/" on Home;
  - idle loading of `search.js`, the first-focus fetch, loading, the names-only fallback and failed with "Try again", and leaving out program rows whose slug the page's index lacks;
  - CSS that uses the colour tokens only;
- `tests/home_search.test.mjs` (new; fixture-served): ARIA, keys, sections and division tags, fetch counts, loading and failed states, contrast in both themes;
- `tests/shell_nav.test.mjs` and `tests/route_focus.test.mjs`, changed per decision A (section 6);
- `tools/search_browser_check.mjs` (new) and `tools/search_fixture.py --serve` (section 7.5).

**Fails on main:**
- `home_search.test.mjs`: "at 1,280 px, Home has a labelled combobox whose listbox shows Conferences then Programs for 'big ten'";
- `home_search.test.mjs`: "Home's load makes exactly today's four requests; first focus adds exactly 1 API request; typing makes none";
- `home_search.test.mjs`: "with one slug removed from the page's index, no row links to it".

**Bytes:** at most 13 KB raw / 4 KB gzipped added to `index.html`. The browser check's JSON record goes in the PR.

**Risks:**
- **It reverses #465.** The owner confirms first (A).
- **Drawing speed.** Measured by the committed browser check; the painter comes in only if needed.
- **The build's longest task.** Measured; the yielding build comes in only if it is over 40 ms.
- **A large edit to a 517 KB file.** ECNL's lesson: make such edits with a script and a verifier, so each change is exact.
- **Home is not perf-measured today** (3821). Decision R decides whether it joins #394's views, as its own PR.

### PR 6c: the version-mismatch and data-refreshed states (sonnet, visible; inside the approved PR 6 mockups)
**Files:**
- `public/index.html`, between the markers:
  - the Reload alert for a search file whose schema or `SEARCH_API` the code doesn't know;
  - the data-refreshed line and count-free links when `search.updated ≠ S.index.updated` (section 3.8);
- `tests/home_search_states.test.mjs` (new).

**Fails on main:** `home_search_states.test.mjs`:
- "with a search file one refresh newer than the index, no list or Show-all link shows a count, and the quiet line shows";
- "a search file with schema 2 shows the `role=alert` Reload note and no rows".

**Bytes:** at most 3 KB raw / 1 KB gzipped.

**Risks:** small. Before this PR both cases fall back safely: a schema mismatch is treated as failed (names-only fallback), and refresh skew shows a count that may be a day old.

### PR 6d: the phone sheet (opus, visible; inside the approved PR 6 mockups)
**Files:**
- `public/index.html`: the phone hero button, the full-screen sheet on `phoneSheet()` with its own combobox input, Escape and Cancel, the inert page behind it, the Tab trap, 44 px rows, and the phone CSS;
- `tests/home_search_phone.test.mjs` (new);
- `tests/shell_nav.test.mjs`: the hero `<button>` is allowed.

**Fails on main:** `home_search_phone.test.mjs`:
- "at 390 px, the Home hero is a button. Tapping it opens a dialog whose input has focus, and `#main` and the header are inert. Tab stays inside the dialog. Escape on the empty box, and Cancel, each close it, release inert and return focus to the button";
- "from 320 to 400 px nothing scrolls sideways" (a CSS cascade check in the style of `tests/header_narrow.test.mjs`).

**Bytes:** at most 5 KB raw / 1.5 KB gzipped.

**Risks:**
- iOS keyboard focus inside the same tap. Checked by hand on a real phone, and noted in the PR.
- The header staying one row (879).
- Inert left behind after navigation. Released as `campsInert(false)` is (3777).

### PR 6e: the Ask option (opus, owner only; inside the approved PR 6 mockups)
**Files:**
- `public/index.html`: the "Ask: …" last option and Shift+Enter. It reuses the existing Ask call unchanged (2720-2792): no new endpoint and no change to the Worker;
- `tests/home_search_ask.test.mjs` (new; Ask stubbed as `tests/ask_page.test.mjs` does).

**Fails on main:** `home_search_ask.test.mjs`:
- "with Ask on, 'cheap schools with snow' on Home offers Ask last, and Shift+Enter sends exactly one `api/ask` POST, then opens Programs with the answer applied";
- "with Ask off there is no Ask option and no request".

**Bytes:** at most 3 KB raw / 1 KB gzipped.

**Risks:**
- Spending the $10 monthly budget by accident. Exactly one POST per explicit ask, pinned.
- Showing Ask to visitors. The option appears only after `api/ask/status` says on, as today (1745-1746).

### PR 7: the Camps section (sonnet, visible; inside the approved PR 6 mockups)
**Files:**
- `public/search.js`: the Camps kind, and month and weekend words read against the context's clock and mapped to `from`/`to`;
- `public/index.html`: camp rows (at most 2 KB raw);
- tests.

**Fails on main:**
- M03 "ucla id camp" puts UCLA's College ID Camp row first (a live query's `first`);
- M04 "stanford camps" gives sections Programs only, Stanford first with the no-upcoming-camps note, and never UCLA's camp;
- M07 "camps in colorado" puts UCCS's Elite ID Camp first and shows Colorado State's December ID Camp;
- a Camps "Show all" link's count equals the camps the ID Camps page keeps on the fixture.

**Risks:**
- Clock and time zone. The engine reads only `ctx.now` and `ctx.timeZone`, and the purity scan bans `Date.now`.
- The camp set must equal the ID Camps page's set (`campsData`, 4438-4451). A test compares them on the fixture.
- Camps pass every day. Exact pins live on the fixture only.

### PR 8: the Coaches section (sonnet, visible; inside the approved PR 6 mockups)
**Files:**
- `public/search.js`: the Coaches kind;
- `public/index.html`: coach rows (at most 1.5 KB raw);
- tests.

It also carries the fresh held-out batch and phase 1's final measurement.

**Fails on main:**
- H01 "erica dambach" puts Penn State's head-coach row first, linking `#/p/penn-state/staff`;
- H04 "waldrum" puts Ben Waldrum's row (Pittsburgh's head coach in the index) first;
- E07 "smith" shows the coach Shelley Smith (South Carolina) after smith-college.

**Risks:**
- Two coaches with the same name: both are shown, D1 to D3.
- Head coaches change, so this is live data, pinned only on the fixture.
- 85 programs list no head coach. They get no row, never a guess.
- Former coaches (H03) and assistants (H05, Randy Waldrum) stay `phase 2`.

## 9. Owner decisions (each with a recommendation)
Each decision below says what is asked, what I recommend, and which PR waits for it, so this section can be read on its own. **Owner rulings** need the owner's word. **Team defaults** stand unless the owner overrides them.

### At a glance: what each decision gates
| Decision | Kind | Needed before | Recommendation in one line |
|---|---|---|---|
| A. Reverse #465: a box on Home | ruling | any PR | yes: a box in the Home hero; the header box stays hidden on Home |
| C. Phase 1 answer kinds | ruling | PR 1 | programs, filtered lists, conferences, ID camps and current head coaches |
| D. Player names in the judged set | ruling | PR 1 | drop R01-R05 while players are out of scope |
| I. Conference aliases | ruling | PR 1 (the table ships in PR 2) | a reviewed table with the quote kept in each entry; a stale entry is skipped with a warning |
| L. Phase 1 fact words | ruling | PR 1 | division, conference, state, region; "small" under 5,000; "under 30k"; "warm" above 80F; top N RPI; the rest named back |
| M. Collisions, conference rows and "too broad" | ruling | PR 1 | a fact leads unless the query is exactly a displayed name; D1 first among ties; conference rows need whole words; one word-based too-broad rule, which shows Programs only |
| S. Cities | ruling | PR 1 | a city finds and labels program rows; no city list row |
| U. "UMass Boston" alias | ruling | PR 1 | a registry alias in its own issue; Y07 is `phase 2` until then |
| C01-C19 (the draft's) | statuses | PR 1 | approve the status table at the end of this section |
| N. Test clock | team default | PR 1 | frozen at 2026-10-20T16:09:38Z, America/Los_Angeles |
| P. Process | team default | PR 1 | one sub-issue per PR |
| T. Shared words and twins | team default | PR 1 (the engine uses them from PR 3) | the fixed list in section 4.1: optional in program rows, required in conference rows; on a State-side program, "St." and a build-made "Saint" read as State |
| E. Search data shape | team default | PR 2 | one self-contained file, about 55 KB at gzip -9 |
| F. Serving | team default | PR 2 | `/api/v1/search`, behind the usual session gate and limits |
| H. `state=` on the Programs address | ruling | PR 4 | yes, with a State filter on the rail |
| Q. "Cold" | ruling | PR 5 | fall average high below 65F |
| B. Phone form and label | ruling | the PR 6 mockup set, so before PR 6a | a hero button opening a full-screen sheet; the owner picks the label style |
| G. Loading | team default | PR 6b | code at idle on Home, data at first focus, no requests while typing |
| O. Local browser check | team default | PR 6b | the committed script, run offline with the installed tools |
| R. Home in #394's measured views | ruling | PR 6b | yes, as its own small PR after 6d |
| K. Ask in the Home box | ruling | PR 6e | an owner-only last option, in its own PR |
| J. The header box | ruling | after PR 8 | coexist in phase 1; decide on measurements after PR 8 |

PRs 3, 6c, 6d, 7 and 8 need no new decision: what they rely on was ruled for an earlier PR (6d's phone form is B, ruled before the mockups). Section 8's PR table gives the same mapping from the PR side.

### Owner rulings
- **A. Reverse #465 for Home** (before any PR). On 2026-10-02 the owner ruled that Home has no box (commit `453203860`, pinned by `tests/shell_nav.test.mjs:60-70, 282-300`).
  - Recommendation: yes. A real box in the Home hero, between the line and the three options. The header box stays hidden on Home.
- **B. Phone form and label** (before the PR 6 mockup set).
  - Recommendation: on phones, the hero is a button that opens a full-screen sheet (ECNL's pattern), built on the page's `phoneSheet()`, with the page behind it inert. Results do not open in place.
  - The mockup shows the "Search CollegeDash" label both visible and for screen readers only, and the owner picks.
- **C. Phase 1 answer kinds** (before PR 1).
  - Recommendation: programs, filtered lists, conferences, ID camps and current head coaches.
  - Players and commits by name stay out: they are mostly minors, and Pipelines' rule is "counted, never named".
  - Assistant and former coaches, clubs and high schools, and "near <city>" (C14) wait for phase 2.
- **D. Player names in the committed judged set** (before PR 1).
  - Recommendation: drop R01-R05 while players are out of scope.
- **H. The Programs address gains `state=`, with a State filter on the rail** (before PR 4).
  - Recommendation: yes. List rows such as "D3 Ohio" need it, and it is additive under #14's "may grow, never change meaning". On Programs it ANDs with region, as every Programs facet does (section 8, PR 4).
- **I. Conference aliases** (before PR 1; the table ships in PR 2).
  - Recommendation: a reviewed table whose evidence is kept as text in each entry (a quote, its URL and the date checked). It is a new convention modelled on the registry's `searchAliasesNote`, accepting any https source. It is checked in CI when added, and skipped with a warning, never failing the refresh, if it goes stale.
  - Phase 1 ships four entries, all in PR 2: B1G, CCAA, NESCAC and UAA (section 3.5).
  - A conference means its current members only (C05).
- **J. The header box** (after PR 8).
  - Recommendation: it coexists with the Home box in phase 1. After PR 8, decide on measurements whether its suggestions use the same engine on every page. The old matcher, and the Programs page's `q=` reading, retire only after that.
- **K. Ask in the Home box** (before PR 6e).
  - Recommendation: an owner-only last option, in its own PR (6e). Shift+Enter always asks; Enter asks only when nothing matched. With Ask off there is no option and no request.
- **L. Phase 1 fact words** (before PR 1). Recommendation:
  - division, conference, state, and region, with New England = Northeast (C10);
  - "small" = under 5,000 undergraduates, including very small (C02), rather than the cards' 2,000-4,999 "Small" bracket. Opening such a row shows an "Undergrads < 5,000" chip on Programs and replaces the visitor's saved filters, as any shared Programs link does; the mockup shows it;
  - "under 30k" = the page's Tuition condition, out-of-state else in-state (C03);
  - "warm" = fall average high above 80F (C04);
  - top N RPI;
  - colour (C06), snow (C16), religion (C18), public/private and majors (C17) are named back as not applied until phase 2. A01, A04 and A06 are judged that way (section 7.1).
- **M. Collisions, conference rows, and when a query is too broad** (before PR 1). Recommendation:
  - **Ties.** Among equal matches, D1 before D2 before D3 (C08).
  - **A fact leads, unless the query is exactly one program's displayed name** (C09, section 5.3 rule 3).
    - "American" opens American University, while "MAC" opens its conference.
    - "Metro" is not a search name at all, so it is simply a conference (rule 4).
    - "west virginia" is one fact, the state WV, and also exactly West Virginia's displayed name, so the program leads and the WV list follows (G08).
    - A state name right after "university of" or "college of" is part of a name, not a fact (4.3 rule 2). So "university of michigan" opens Michigan and shows no Michigan list row (S06).
  - **"New England" and "NE".** Two D3 programs carry both "New England" and "NE" as search names: University of New England (ME, "New England (ME)") and New England College (NH, "New England (NH)").
    - Neither displayed name is exactly the query, so the fact leads: "new england" opens the Northeast list (104 programs on 2026-10-20 data), and "NE" in capitals opens the Nebraska list (6 programs).
    - Both New England programs follow in Programs. Their order between themselves is only the name tie-break and is not pinned. For "new england", the Conference of New England, NESCAC and NEWMAC follow in Conferences, because both words are whole words of their names.
  - **Where such initials come from.** `build.py:1987-1988` makes initials from a short name of 3 or more words. It counts every word, but takes letters only from words that start with a letter, so a "(ME)" disambiguator or an "&" counts as a word and adds no letter.
    - On 2026-10-20 data, 14 distinct two-letter strings are search names. 12 come from this rule; "GW" (George Washington) and "UK" (Kentucky) are cited registry aliases.
    - **3 of the 12 equal a state code, on 5 programs:** "NE" (both New Englands), "NC" (both North Centrals; North Carolina's code) and "DE" (Davis & Elkins; Delaware's code).
    - **The other 9:** "WM" (William & Mary), "EH" (Emory & Henry), "FM" (Franklin & Marshall), "JW" (Johnson & Wales), "LC" (Lewis & Clark), "WJ" (Washington & Jefferson), "WS" (both Wayne States), "SM" (Saint Mary's, IN) and "ST" (St. Thomas, TX).
    - Some may be wanted ("W&M" is a real short form). I recommend a separate issue to review that rule; it is not part of #507.
    - The judged set pins the state reading of "DE" and "NC" (X09, X10) without pinning those programs either way.
  - **"LA" in capitals:** the Louisiana list first, then the 5 programs in Los Angeles, through one reviewed city alias. Never La Salle or Lafayette (4.2 rule 1). Lower-case "la" is only a name prefix (C11).
    - The alias would be one `CITY_ALIASES` entry in `public/search.js`, since the search file has no field for it, checked by a code-only test against the fixture's (city, state) pairs, in PR 5 (section 4.4).
    - If declined, there is no alias, and X05 keeps only its Louisiana `first`.
  - **No nearby cities** in phase 1 (C12).
  - **When name words give a conference row** (section 5.2; it settles part of C01). Every name word must be a whole word of the conference's stored name, except that the query's last word may be a prefix when it has 4 or more letters. Shared words must be in the name too. A lone word of one or two letters gives none. A too-broad slate shows Programs only.
    - So "american" shows American Rivers, American Southwest and Great American after the D1 conference stored as "American", and "new york" shows the CUNY and SUNY conferences.
    - And "university of michigan", "cal", "penn state", "a", "st", "university" and "womens soccer" show no conference row, which their judged `sections` already say. "saint" shows the St. Louis Intercollegiate Athletic Conference, through the saint/st twin.
    - Revision 3's looser rule (any word prefix, shared words optional) gave conference rows to six judged queries whose `sections` leave Conferences out (S02, S06, S07, E02, E03, E06), and through NEWMAC's "womens" it would have touched E14.
  - **Too broad (C19): one word-based rule.** A query is too broad when every whole word in it is a shared word (decision T's list) or one of conference, conferences, coach, coaches (section 4.1).
    - The panel names the count, shows the capped program rows those words find (if any), with "Show all" expanding in place, and no other section. Enter does nothing until the visitor picks a row.
    - **This narrows the draft's C19,** which also named "a single letter". A single letter is an ordinary prefix: Enter opens the first row, as it does today (E02), and the first-show cap of 6 rows already bounds its drawing on a phone.
    - There is no count threshold, so a refresh can never move a query in or out of "too broad".
    - Judged: E06 "university" and E14 "womens soccer" are too broad; E02 "a" and E03 "st" are not.
- **Q. "Cold"** (before PR 5). Section 4.2 leaves this to the owner.
  - Recommendation: "cold" = fall average high below 65F (134 programs on 2026-10-20 data). It uses the same page condition as "warm", so a "cold" list row is a plain Programs link, and the row says "fall average high under 65F" so the reading is visible.
  - The alternative: name "cold" back as not applied until phase 2, together with snow. The fit file's own "cold" label (coldest-month mean below 27F; 254 programs) is not a Programs-page condition.
- **R. Home in #394's measured views** (before PR 6b). The route's comment at 3821 leaves it open.
  - Recommendation: yes, but as its own small PR after 6d (the page, the Worker's view list and `docs/data-api.md`), not inside PR 6b. PR 6a's draw counts and PR 6b's browser check cover phase 1.
- **S. Cities** (before PR 1).
  - Recommendation: in phase 1 a city finds and labels program rows inside the panel. There is no city list row and no `city=` parameter on the Programs address.
  - The page's `q=` place search can't open the same rows: 8 programs are in Boston, but `q=boston` lists 9, because Boston College matches by name (section 1). Revisit with J.
- **U. "UMass Boston" (judged Y07)** (before PR 1). massachusetts-boston's search names are "Massachusetts Boston" and its full name, so no phase-1 rule finds it from "umass boston".
  - Recommendation: add "UMass Boston" as a registry `searchAliases` entry, in its own small issue outside #507. Its note follows the registry's convention, which needs a Wikipedia citation (`tests/search_short_forms.test.mjs:83-89`). That means reading the article once, with the owner's OK, or the owner supplying the quote.
  - Y07 becomes active at the first fixture refresh that includes the alias. Until then, or if the owner declines, Y07 is `phase 2`.
  - Noticed in passing: massachusetts-dartmouth has the same gap ("Massachusetts Dartmouth" only). It is not judged.

### Team defaults (stand unless the owner overrides)
- **E. Search data shape** (before PR 2): one self-contained file, about 55 KB at gzip -9 for the phase 1 fields, pinned by base plus per-row rate. The alternative, a 15 KB supplement joined with the page's index, would tie search to the index format and to one refresh.
- **F. Serving** (before PR 2): `/api/v1/search`, behind the same session gate and rate limits as all data.
- **G. Loading** (before PR 6b, which builds it): the code at idle on Home (at first focus on Save-Data), the data at first focus, then no requests while typing.
- **N. Test clock** (before PR 1): frozen at 2026-10-20T16:09:38Z, America/Los_Angeles, for every judged and camp test (C15). The browser uses the visitor's own clock and zone.
- **O. A local browser check for visible PRs** (before PR 6b): the committed `tools/search_browser_check.mjs`, run outside CI with the command in section 7.5. In this environment it uses the installed Playwright 1.56.1 and Chromium 141 and needs no network. It aborts and counts off-machine requests, and its JSON record goes in the PR.
- **P. Process** (before PR 1): one sub-issue per PR (Closes the sub-issue, Part of #507). PR 4 has its own mockup, and the PR 6 set covers 6a-6e, 7 and 8.
- **T. Shared words** (before PR 1; the draft's C07): the fixed list "the, of, and, soccer, women, womens, ncaa, school, schools, program, programs, university, college" (section 4.1).
  - When the query has other words, a shared word is optional for program rows: it never empties a result, and it adds to the score of the rows that contain it.
  - For conference rows it is required, so "university of michigan" gives no Michigan Intercollegiate Athletic Association row (decision M; section 5.2).
  - A query made only of them (or of "conference" or "coach") is too broad (decision M).
  - saint/st and mount/mt are the same word, except on a State-side program: one whose own name or short name says "State" and has no Saint or St. There, every "st" and every "saint" in its names is read as "state" (section 4.1). So "saint" finds the 39 Saint-side programs and never Ohio State or Cal State Fullerton.
  - **Noticed in passing, for a separate issue outside #507:** the build turns every "St." followed by a space into "Saint " (`build.py:2002-2004`), even when it means State. On 2026-10-20 data that makes one wrong search name, "Cal Saint Fullerton". Today, `#/programs?q=saint` lists Cal State Fullerton because of it. I recommend fixing the swap in its own small issue. #507's engine does not depend on that fix.

### The draft's decisions C01-C19
| Draft | Status | Ruled under |
|---|---|---|
| C01 section order | superseded by section 5.3's six rules and 5.2's conference word rule; approving them is the ruling | M (with 5.2 and 5.3) |
| C02 "small" | decided by the ruling | L |
| C03 "under 30k" | decided by the ruling | L |
| C04 "warm" | decided by the ruling | L |
| C05 conference aliases, current members | decided by the ruling | I |
| C06 "blue" | named back until phase 2 (A01) | L |
| C07 shared words | team default, now an exact list: optional in program rows, required in conference rows | T |
| C08 D1 before D2 before D3 | decided by the ruling | M |
| C09 conference vs program name | decided by the ruling | M |
| C10 New England = Northeast | decided by the ruling | L |
| C11 LA / NE | restated with both New England programs, plus DE and NC | M |
| C12 nearby cities | none in phase 1 | M, S |
| C13 people labels | withdrawn while players are out of scope. Its "same name, separate rows" part is kept for coaches (section 5.2) | C, D |
| C14 "near <city>" | out of phase 1; M01 is `phase 2`, and M07 asks the phase-1 way | C |
| C15 clock and zone | team default | N |
| C16 snow | named back until phase 2 (A01, A06) | L |
| C17 words with no data | named back (section 4.6) | L |
| C18 religion | named back until phase 2 (A04) | L |
| C19 too broad | decided by the ruling, narrowed: shared words only, never a single letter; the slate shows Programs only (section 4.1) | M |

## Appendix: what this plan relies on
- **CollegeDash `public/index.html`:**
  - the Google Fonts stylesheet, 19; the header box, 897-909; `S.campsSaved`, 981; `todayLocal`, 1005; displayName, 1018;
  - normText 1061-1062; place search 1069-1118 (the capitals rule 1077-1079, city then state 1102-1106); placeQueryHits 1122; prepareSearch 1123-1134 (search names read at 1126); matchScore 1137-1160 (a search-name word-prefix hit scores 60 at 1152); visibleMatches and searchMatches 1165-1172;
  - COND_FIELDS 1261-1288; NOT_APPLICABLE 1228; `S.favorites` 1403; isPhone 1444; phoneSheet 1446-1473;
  - noteSession's session-renewal HEAD 1692-1700; loadIndex 1715-1747, with its four requests at 1717, 1742, 1744 and 1746;
  - REGIONS 2002; DIVISION_NAMES 2006; divisionTag 2009; programLine 2014-2017; confKeyOf 2089;
  - setQuery 2458-2459; SEARCH_VIEWS 2472; campsBox 2473; searchKeydown 2512-2543 (ID Camps' Enter 2515-2519; the Enter rule 2535-2540); the help panel 2558-2575, with the chip lists 2566-2568; SUGGEST_MAX and suggestionItems 2577-2591 (help chips 2581, no-match chips 2590); closeSuggestions 2631; openFromSearch 2633; showPlaceList 2644; Ask 2720-2792;
  - recs.js loading 2838-2846;
  - the list address 3557-3651 (LIST_PARAMS 3581, LIST_Q_MAX 3582, listQ 3588, listHashOf 3591-3603, listStateOf 3604-3639), listArrive 3661-3675;
  - renderHome 3729-3739; campsInert(false) in route 3777; the `c` route 3794-3802; Home not measured 3821;
  - matchesFilters 3966-3973;
  - size and tuition brackets 4128-4133;
  - CAMP_CLASSES 4272; campCmp 4274-4275; campTally 4283-4293; campIsPast 4305-4308; campAddDays 4309; campProgram 4317-4324; CAMPS_PARAMS 4330; campsQ 4334; CAMPS_WHEN 4335; campsStateOf 4338-4356; the camps search 4370-4402 (its saint/st twin 4385, over names at 4383); campsMatch 4404-4415 (region OR state 4406; the Shortlist test 4408); campsData 4438-4451 (campTally called at 4449); the Shortlist chip 4463; the camps no-match card 4487-4494; CAMPS_SHEET and campsInert 4585-4593; campsTyped 4654-4656;
  - TABS, TAB_HAS and profileTabs 5506-5510; the hidden-tab fallback 5598-5604; boot 6156-6164;
  - CSS 714-725 and 871-879.
- **CollegeDash, other files:**
  - `build.py`:
    - 1960-2098 (search_names, with the initials rule at 1987-1988 and the St./Saint swaps at 2002-2006, State "St." to "Saint" at 2003-2004; summary_row 2010; LIST_DROPPED 2069; list_path 2076-2078; list_row 2087-2091);
    - fit_path 2126-2128;
    - 2203-2290 (build: the index write 2253, list and fit 2254-2255, camps index 2261-2263, validate 2288);
    - 2213 (`::warning` via common.annotate);
    - 2293-2328 (validate);
    - 2334-2342 (list_complaints names a missing list);
    - 2378-2396 (check_list_index);
  - `collect/common.py:212-216` at `df9417725`, 211-215 on main at `365ce91ec` (read_json gives None for a missing file);
  - `serve.py:93-117` (routes; list and fit at 107-110);
  - `api/data-api.mjs:5-14, 62-65`; `api/data-reader.mjs:2-24`; `api/perf.mjs:43, 50`;
  - `worker.js:84-85, 157-166, 240-356`;
  - `docs/data-api.md:20-29, 75, 78`;
  - `.github/workflows/refresh.yml`:
    - 61;
    - 148 (build_only validates right after its build);
    - 270 and 280-282 (comments);
    - 298-326 (publish_sources_only; the tolerant restores 307-317; the assertion 323-326, message at 324);
    - 340 (the "NOTHING WAS PUBLISHED" message);
    - 485-488 (build, then validate at 487);
  - `.github/workflows/tests.yml:25-48, 103-105, 111, 122`;
  - email patterns: `tools/camps_check.py:184`, `collect/coach_bio.py:63`, `tests/staff_fallback_test.py:269`;
  - `public/recs.js:480-482` (the export wrapper);
  - `.github/scripts/run_node_suites.py:66-97, 198-203`; `.github/scripts/run_suite.py:64-70`;
  - `public/data/registry.json` (searchAliasesNote) and `programs/bates-college/sources/news.json:39`, the latter cited only as where a quote was found;
  - tests:
    - `refresh_commit_step_test.py` (stand-in build 243-296, list and fit cases 1176-1286, case list 1297-1304);
    - `camps_index_test.py` (80-83, 127-172, 824);
    - `seasons_test.py` (164-191);
    - `list_index_test.py` (22, 228-258);
    - `place_search.test.mjs:112`;
    - `search_short_forms.test.mjs` (83-89, 109-122);
    - `section_hiding.test.mjs:335`;
    - shell_nav, route_focus, header_search, header_combobox, conference_counts, data_api;
    - `list_url_state.test.mjs` (:15, :33, :34, :456);
    - `perf_worker.test.mjs` (460-467);
    - `refresh_imports_test.py:60`; `profile_pruning_test.py` (309, 362-366);
    - `recs_catalog_test.py` (:6-9);
  - `tools/recs_catalog.py` and `tests/fixtures/recs/`.
- **ECNLDash:**
  - `public/search/*.mjs`:
    - match 32-36, 38-60 (NOISE 52, NAME_ALIAS 56), 146-168, 202-206 (idf), 212-243 (the word score at 234);
    - reader 18-212 and 71-81;
    - vocab 27-28 and 34-36;
    - slate 7-8, 14-131;
    - search 32-67, 142-149;
  - `search_data.py` 10-22, 154-197, 528-534, 1128-1159, 1183-1203;
  - `archive.py:1054-1080`;
  - `tests/search/judged.mjs` (133-183, with 153-155; 494-572, with 524-532, 526, 530-531 and 548; 575-635; 643-671);
  - `tests/search-judged.test.mjs`; `tests/search-modules.test.mjs` (41-58, with the banned list at 43-44); `tests/search-panel.test.mjs`;
  - `tests/e2e/search-panel.e2e.mjs` (7-8, 24, 38, 43-54);
  - `public/index.html` (lines as cited).
- **The environment** (read-only):
  - `/opt/node-tools/node_modules/playwright/package.json` and `playwright-core/package.json` (1.56.1); `playwright-core/browsers.json` (chromium revision 1194, 141.0.7390.37); `playwright-core/lib/server/registry/index.js:1268-1271` (where `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` is read);
  - `/opt/pw-browsers` (`chromium-1194`, `chromium_headless_shell-1194`, `ffmpeg-1011`); `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers` and `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` in the environment;
  - Node 22.22.0 first on `PATH` (`/opt/node22/bin`); `/usr/local/bin/node` → `/opt/node20` (20.20.0); `/opt/node21` (21.7.3); no Node 24 on `PATH` or under `/opt`, `/usr` or `/root`; Python 3.11.15 on `PATH`, 3.12.3 at `/usr/bin/python3.12`.
- **Scratch notes** in `scratchpad/search507/`:
  - `ecnl.md`, `collegedash.md`, `judged-draft.json`;
  - `work/estimate_size.py` and `work/estimate_phase1.py`, read-only size measurements;
  - `chitu-r3/pw_smoke.mjs`, the read-only check that the installed Playwright drives the installed Chromium offline (section 7.5);
  - `chitu-r3/programs-a83.json`, a copy of `public/data/programs/index.json` at `a83a32086` (the fixture's programs input; same sha256 as main's copy);
  - revision 4's read-only fact scripts, each reading that copy and writing nothing:
    - `chitu-r4/facts_r4.py`: the State-side and Saint-side counts (89 = 50 + 39; 160 State-side programs; 40 with "saint"; only cal-state-fullerton State-side with "saint");
    - `chitu-r4/facts_r4b.py`: E02 and E03 with `normText`'s "&" rule (121 + 19 = 140; 215 + 10 = 225);
    - `chitu-r4/e15_set.py`: E15's 39 and the 6 nickname-only "Saints" rows;
    - `chitu-r4/conf_rule.py` and `chitu-r4/conf_rule_final.py`: conference rows under revision 3's rule and revision 4's, for every judged query;
    - `chitu-r4/list_rows.py`: list rows for every judged query, with and without the "of" rule;
  - `work/today-all.mjs`, run read-only under the netguard and a dead proxy, for today's 46 "saint" hits;
  - `plan-r1.md`, `plan-rev2.md` and `plan-rev3.md`, revisions 1 to 3 of this plan.
- **Not found** in either repo:
  - ECNL's design plan, addenda and mockups (they live on ECNL's GitHub issues), and ECNL's throttled phone measurements;
  - conference abbreviations, colour names, majors offered per school, and a label table for religious-affiliation codes;
  - a `state` or `city` parameter on the Programs address;
  - a `package.json` for CollegeDash. Playwright and Chromium are not repo dependencies; they are installed in this environment outside both repos (section 7.5).

## Changes since review
Revision 1's change list is in `plan-r1.md`, revision 2's in `plan-rev2.md`, and revision 3's in `plan-rev3.md`. This lists revision 4's changes, against Huatuo's two required points (`review-r4.md`) and his three optional notes. Before changing anything, I re-checked each claim against the repos and the fixture myself, with the read-only scripts in `scratchpad/search507/chitu-r4/` (appendix). Nothing in either repo was changed.

**1. E15 "saint" no longer contradicts itself** (section 4.1; also sections 0, 2, 5.3, 7.1 and 7.4, PR 3, and decision T).
- **Confirmed.** `build.py:2003-2004` turns every "St." followed by a space into "Saint ", whatever it means. So cal-state-fullerton publishes "Cal Saint Fullerton"; its search names on the fixture are Cal State Fullerton, California State University, Fullerton, Cal St. Fullerton, CSUF, CSF and Cal Saint Fullerton. Revision 3's rule re-indexed only the word "st", so:
  - a typed "saint" matched that name exactly, and E15's mustNever and PR 3's failing test could not pass;
  - E15's `first` (40) included the program its mustNever names;
  - "none on both sides" was false.
- **Fixed in the engine, the review's first option.** On a State-side program, every "st" and every "saint" in its names is now indexed as "state". A program is State-side when its own name or short name has "State" and no Saint or St (160 on the fixture). Its own names have no Saint, so a "saint" in its search names can only be the build's swap. On the fixture that changes exactly one name.
- **Recounted.** 40 programs have the word "saint": the 39 Saint-side ones and cal-state-fullerton. E15's `first` is now those 39, so it no longer overlaps mustNever. Section 4.1 now says this, and "no program is on both sides" holds under the extended rule.
- **Why not fix the build's swap in PR 2.** That would change published search names, which today's box and the Programs page's `q=` read (today `#/programs?q=saint` lists Cal State Fullerton). The fixture would also have to be re-cut from a new data commit. So the plan recommends it as its own small issue (decision T, noticed in passing). The engine rule works with or without that fix.
- **Pinned.**
  - PR 3: E15 puts a Saint-side program first and never shows Ohio State, Alabama State or Cal State Fullerton. A unit test checks that "Cal St. Fullerton" and "Cal Saint Fullerton" are both indexed as "cal state fullerton", and that saint-louis keeps its twin.
  - Today's box passes the cal-state-fullerton mustNever: the program is the 32nd of its 46 "saint" hits, outside the 6 it shows. So the engine must pass it from PR 3.
- **Found while doing it.** The twins also apply to conference names under the rule in point 2, so "saint" finds the St. Louis Intercollegiate Athletic Conference. E15's `sections` become Programs, Conferences, with Conferences pending PR 5. That row joins mustShow, and the Sunshine State Conference row joins mustNever, because a typed "saint" never looks for "state".

**2. Name words give a conference row only under one strict rule, and every judged `sections` list agrees with it** (section 5.2; also sections 0, 4.1, 4.2, 4.3, 5.3, 5.6, 7.1 and 7.4, PR 5, and decisions M and T).
- **Confirmed** on the fixture's 98 (division, conference) pairs. Revision 3's rule ("every name word starts a word of the name", shared words optional) gave conference rows to six judged queries whose `sections` are Programs only, and whose section checks pass today:
  - S02 "cal" (2 rows), S06 "university of michigan" (1), S07 "penn state" (1), E02 "a" (46), E03 "st" (6) and E06 "university" (3);
  - NEWMAC's stored name contains "womens", which touches E14.
- **The rule (5.2) is the review's suggestion, plus one clause:**
  1. the reading has at least one name word;
  2. every name word and every shared word must match a different word of the stored name. Shared words are required for conference rows, kind words are never required, and the twins apply;
  3. a match is a whole word, except that the query's last word may be a prefix when it has 4 or more letters. There are no typo matches;
  4. **added:** a reading whose only name word has one or two letters gives none. Without this clause, E03 "st" would still get the St. Louis Intercollegiate row, because "st" is a whole word of that stored name.
- **A too-broad slate draws Programs only** (4.1, 5.3, 5.6 and decision M). That settles E06 and E14.
- **Checked on every judged query** with `chitu-r4/conf_rule_final.py`. Conference rows go only to F01-F08, X01-X04, L04 and E15.
  - X02 "american", X04 "new england", L04 "new york" and X03 "metro" get what the 5.3 table had. The table now says "by whole words", not "by prefix".
  - E15 gains Conferences (point 1). No other `sections` list changes.
- **Found while checking every `sections` list, and fixed.** S06 "university of michigan" had the same problem with Lists.
  - Its fact reading {MI} has only shared words beside it, which revision 3 treats as facts-only (like "schools in texas"). So from PR 5 it would have gained a Michigan list row that today's box doesn't show.
  - 4.3 rule 2 now says a state name right after "university of" or "college of" is part of a name, not a fact.
  - `chitu-r4/list_rows.py` shows every other list row goes to a query whose `sections` already include Lists. D07 "sec d3" is the exception: its facts are impossible together, so it gets the impossible state and no row.
- **Pinned** in PR 5's failing tests: X04's three conferences; S06 with no conference row and no list row; E03 with no conference row; E06 and E14 with Programs only; E15 with the St. Louis Intercollegiate row and never the Sunshine State row.

**Optional notes.** All three were checked, and all three are taken.
- **Nickname-only rows for E02 and E03** (5.2, 7.1). A row found only through the nickname now counts as useful. The nickname is one of the names the box searches, and K01-K06 judge it as an answer.
  - `first` grows from 121 to 140 for E02 (19 nickname-only rows, such as uc-irvine "Anteaters" and san-diego-state "Aztecs").
  - It grows from 215 to 225 for E03 (10, such as fairfield "Stags" and heidelberg "Student Princes").
  - Both are counted with `normText`'s "&" rule. Rows found only through a city or a head coach are still not useful.
  - Today's box still passes both `first` checks: arkansas and stanford are in the sets.
- **Frozen slices** (7.3).
  - `LIST_Q_MAX` (3582), `CAMP_CLASSES` (4272) and `campTally` (4283-4293, called at 4449) are now frozen.
  - Also found: `campsQ` (4334), which the adapter calls, was not frozen either. It now is.
  - The Enter slice (2535-2540) starts with `else if`, so it now sits in a stated two-line wrapper.
  - `closeSuggestions` (2631), `openFromSearch` (2633) and `showPlaceList` (2644) are now listed stubs that record the Enter target, and `S.favorites` (1403) is an empty Set.
  - The baseline runs in a `vm` context that holds only the stubs, so a name that is neither frozen nor stubbed throws.
- **"answers" is never vacuously true** (7.3, PR 1). It now needs every active check to be supported by the box and to pass. A PR 1 test pins this with M04 on the ID Camps box.

**Environment** (the header, 7.5 and the appendix). Re-checked as the brief asked:
- Playwright 1.56.1 is at `/opt/node-tools/node_modules/playwright`, with Chromium under `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers` (`chromium-1194`, `chromium_headless_shell-1194`, `ffmpeg-1011`).
- Node 24 is not on this machine. `node` first on `PATH` is 22.22.0 (`/opt/node22/bin`), `/usr/local/bin/node` links to 20.20.0, `/opt/node21` is 21.7.3, and there is nothing else under `/opt`, `/usr` or `/root`.
- So section 8's rule stands: a PR run here states the versions it used, and CI's run is the reference for Node 24. Python 3.12.3 is at `/usr/bin/python3.12`.

**Readability.**
- Section 0 gains one bullet with the two exact matching rules, says a too-broad slate shows Programs only, names the Node versions, and lists the three small issues recommended outside #507 (U, M and T).
- In section 9, the at-a-glance table's M and T rows now cover conference rows and the State-side twin rule. M's recommendation gains the conference word rule and the "of" rule, and T's the State-side rule and the swap issue. The C01, C07 and C19 rows say where the new rules live.
- No decision was added, and none changed which PR it gates.

**Counts that changed.**
- The judged set is still 93 queries: 74 frozen, 5 slow and 14 live.
- E02's `first` is now 140 (was 121), E03's 225 (was 215), and E15's 39 (was 40).
- E15 gains a pending Conferences section, a mustShow and a mustNever. No other query's `sections` changed.
