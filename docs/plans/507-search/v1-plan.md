# #507 universal search, lean v1: one Home box over Programs and ID Camps

Author: Chitu (Opus). Revision 2, answering Huatuo's round-1 review (last section). Plan only; no product code is written until a reviewer (Bianque or Huatuo) approves it and the
owner has answered the decisions in section 7. Part of #507.

Sources. Read-only. CollegeDash `origin/main` at `60bc94e17` (data refresh 2026-10-21T16:21Z). Line numbers are
`public/index.html` at that commit unless a file is named. Counts were measured with two read-only probes in my
session scratchpad (`chitu-507v1/probe_v1.mjs`, `alias_miss.mjs`) that slice the page's own matchers out of
`index.html` and run them over the committed `public/data`; they are a snapshot for this plan, not numbers to pin.
Nothing was fetched.

**Relation to the full plan.** The revision-4 plan (`plan.md` on branch
`claude/collegedash-tech-lead-e7e0cf-mly5n2`, with `study-collegedash.md`, `study-ecnl.md`, `judged-draft.json`,
`review-r5-open-items.md`, `owner-decisions.json`) stays the reference for v2. This v1 reuses its findings and cuts
everything that needs a new data file, a new matcher or a fact parser. Where v1 defers something, it names the
`plan.md` section that holds the design.

## 1. Goal and scope

**Goal.** A visitor lands on Home, types a school, short name, mascot, state, city or "<school> camp", and gets two
groups of answers, Programs and upcoming ID Camps, without picking a category first and without a request per key.

**In v1**
- One search box in the Home hero, between the line under the heading and the three options. This deliberately
  reverses #465's "no box on Home" (owner ruling of 2026-10-02, commit `453203860`), which
  `tests/shell_nav.test.mjs` pins. PR 2 changes those tests on purpose (section 4) and the owner records the
  reversal on #507 (decision 1).
- Two result sections: **Programs** and **ID Camps** (upcoming ID camps, exactly the rows the ID Camps page lists).
- The division (D1/D2/D3) on every program row and every camp row; names read `shortName || name`.
- Programs: today's header-box matcher, unchanged (`matchScore` 1141-1164: short names, names, `searchNames`
  with the registry's cited aliases and initials, nickname, then a whole-query state or city).
- Camps: the ID Camps page's own matcher, unchanged (`campsQueryMatch` 4401-4406), plus the camps of the programs
  the Programs section found by name (section 3).
- Keyboard and screen-reader accessible (an ARIA 1.2 editable combobox, as #434/#445); 320-1440 px; on phones the
  same inline box, no sheet.

**Out of v1 (v2, designed in `plan.md`)**

| v2 item | Where `plan.md` designs it |
|---|---|
| Conferences section and conference aliases (B1G, NESCAC...) | 1 "Phase 1 answer kinds", 3.5, 5.2 Conferences; decision I |
| Coaches section | 1 table, 5.2, PR 8 (and `review-r5-open-items.md` item 1, the coach word rule) |
| Filtered lists and fact words (division, state, region, size, tuition, climate, RPI as filters) | 1 "Phase 1 facts", 4.2-4.3, 5.2 Lists, PR 4-5; decisions H, L, Q |
| Typo tolerance ("standford") | 4.5 |
| City words as their own rows | 1 "Cities in phase 1"; decision S |
| Ask in the Home box | 5.7, PR 6e; decision K |
| Replacing the header box `#q` or its matcher | 5.7; decision J |
| The St./Saint rule | 4.1; decision T. Handled separately by #513 |
| "Too broad" and shared words ("stanford soccer", "university") | 4.1; decision M |
| The search file `/api/v1/search`, size budget, browser speed check | 3.1-3.8, 7.5; decisions E, F, G, O |
| Phone full-screen sheet | 6 "Phone"; decision B |

**What a visitor sees** (text mockup; the owner approves a real mockup before PR 2 is built)

```
Find your college soccer path.
NCAA women's soccer programs, ID camps, and where club and high school players go to college.

[ Search programs and ID camps: school, mascot, state, city…            ]   <- typed: "usc camps"
 ID CAMPS · 5 upcoming
   One Day ID Camp | December - GIRLS Only             D1  USC · Sun, Dec 13
   One Day ID Camp | January - GIRLS Only              D1  USC · Sun, Jan 31
   …(2 more rows)
   Show all 5 camps
   Browse all ID camps →
 PROGRAMS · 2
   USC                                                 D1 · Big Ten · Los Angeles, CA
   USC Upstate                                         D1 · Big South · Spartanburg, SC
 [Programs] [ID Camps] [Pipelines]      <- the three options, pushed down while results show
```

With no camp word ("ohio"): Programs first (its 5 name rows, then "All 44 matching programs →", which counts the 39 programs in Ohio), then ID Camps. Nothing
matches: one line, "No program or upcoming ID camp matches “zzzz”. Try a school's short name, a mascot, a state or a
city." Empty box: no panel (no chips; #465 removed them).

## 2. Data

| Section | Reads | From | Loaded when | Size |
|---|---|---|---|---|
| Programs | `S.index.programs` (1,011 rows, already `prepareSearch`ed) | `/api/v1/programs` | already in memory on Home: `boot()` awaits `loadIndex()` before the first route (6160ff, 1719) | 0 new bytes |
| ID Camps | `S.camps` through `campsData(idx, doc).all`: `campType === 'id'`, a start date, not past (`campIsPast` 4309), date order (`campCmp` 4278) | `/api/v1/camps` via `loadCamps()` (1765) | first focus of the Home box (or first input, whichever is first); cached for the page session; the ID Camps page then reuses it | 54,806 B raw, 6,979 B gzip -6; 99 rows, 83 upcoming ID camps at 62 programs on 2026-10-22 |

- **No new build output.** Both sections read data the page already loads or already serves. The full plan's search
  file (`plan.md` 3.1, about 55 KB gz) exists for conferences, coaches and facts, all v2.
- **Requests.** Zero while typing. At most one per page session (the camps index), and none for a visitor who never
  focuses the box. Until camps arrive, the Camps section is not drawn; when they arrive the panel redraws once if open.
  If the request fails, the section reads "ID camps couldn't load." and Programs still work.
- **Code size.** The engine and the box are inline in `public/index.html` (517,942 B today, no build step); expected
  +8-12 KB raw. PR 2 states the measured growth.
- **One refactor for the clock.** `campsData(idx, doc)` calls `todayLocal()` itself (4444). PR 1 gives it an
  optional third argument, `today = todayLocal()`, so tests inject the date. Behaviour on the page is unchanged.

## 3. Matching and ranking

Let `raw` be the box text, `q = normText(raw)` (1065).

**Camp words.** `camp`, `camps`, `clinic`, `clinics`, `id` are camp words. They are looked for among the words of
`normText(raw)`, so "ucla id-camp" is read like "ucla id camp".
- **The Idaho exception.** When the whole query, trimmed, is exactly `ID` in capitals, it is Idaho's state code
  (the site tells visitors to type codes in capitals, 2628) and not a camp word: `camp` is false, Programs runs on
  "ID" as today (Idaho, Idaho State, then the place option for Idaho), and the Camps section shows only camps at
  programs whose `state` is `ID` (one today, Northwest Nazarene). Lowercase "id", on the way to "idaho", stays a camp
  word as below.
- `rest` = the `normText` words without camp words. `camp = (rest has fewer words than normText(raw))`.
- Program query `pq`: when `camp` and `rest` is not empty, `raw` with each whole camp word deleted (case-insensitive,
  a word boundary being any character that is not a letter or digit), so "TX camps" keeps "TX" in capitals for the
  capitals rule; otherwise `raw`. So "ucla id camp" looks for "ucla", while a lone "camp" still finds Campbell and a
  lone "id" still finds Idaho on the way to typing them.
- Camp query: `rest` joined (empty when only camp words were typed).

**Programs section.** `searchMatches(normText(pq), Infinity, pq)` (1173) over all programs. It reads the global
`S.index` (1174-1175) and the place memo (`placeQuery`), so the engine takes no index argument (section 4, PR 1). Home
has no filters, so `visibleMatches`/`matchesFilters` are not applied (filters belong to their destination, owner D4).
- Order is today's: score descending (100 short-name exact ... 30 nickname, 20 place), ties in index order.
- Rows: up to 6 hits that are not place hits (`SUGGEST_MAX`, 2581), as the header box shows them (2587). Place hits are
  deliberately not drawn as rows; like the header box's "All N matching programs →" (2589-2592), they are counted in
  one closing option.
- Closing option "All N matching programs →", shown when N exceeds the rows drawn or any hit is a place hit. It
  links to `listHashOf({ defaults, q: pq })` = `#/programs?q=…`. The Programs page runs the same matcher with every
  other filter at its default (`listArrive` 3665-3680, which keeps the case of `q`, 3674), so it lists exactly N.
  This is an addition, on purpose: the header box shows its closing option only for place hits, so for "bulldogs"
  it shows 6 rows and nothing more, while v1 adds "All 27 matching programs →".
- The "why" text ("Bulldogs", "UNC") is shown as the header box shows it.

**ID Camps section.** An upcoming ID camp is shown when either
1. the camp query is empty (only camp words were typed), or
2. `campsQueryMatch(c, info, campQuery)` is true: every word prefixes a word of the program's names, city, state
   name, region, the camp title or a month the camp touches; a state code or D1/D2/D3 only as a whole word;
   "st"/"saint" swap (4374-4406), or
3. the camp's program is a Programs-section hit with score >= 30 that is not a place hit (a name, alias, initials or
   nickname match).

Rule 3 is needed: of the 213 search names and nicknames of the 62 programs with upcoming camps, 78 find none of their
own program's camps through the camps page's matcher, among them "MSU", "GVSU", "UCCS", "UVU", "Bruins", "Trojans"
(probe `alias_miss.mjs`). With rule 3, "msu" shows Mississippi State's 3 camps and "trojans" 7 camps (USC, Troy,
Trevecca Nazarene). Place hits are left out of rule 3 because rule 2 already reads state and city words.

Order: date, soonest first (`campCmp`), as the ID Camps page orders them. First show 4, then a "Show all N camps"
option, which expands the section in place (at most 83 rows today). It is not a link: because of rule 3,
`#/camps?q=…` can list fewer camps than the section counts. A last option, "Browse all ID camps →" (`#/camps`, no
count), ends the section whenever it is drawn.

**Section order.** ID Camps first when a camp word was typed or Programs is empty; otherwise Programs first. A
section with no rows is not drawn, except a Camps section that leads (a camp word was typed): it then holds only
"Browse all ID camps →", and its message goes outside the listbox (below).

**What sits inside `#homeList`, and what does not.** As the #465 ARIA rule (`tests/programs_rail.test.mjs:3-4`) and the
header box (2626-2628) require:
- The listbox holds only `role=group` elements and `role=option` elements; nothing else.
- One group per drawn section, named by `aria-labelledby` pointing at its heading. The heading ("ID Camps · 5
  upcoming", "Programs · 9") is a `div` inside the group with `aria-hidden="true"`, as `qgroup-label` is (2615).
- Options: program rows, camp rows, "All N matching programs →", "Show all N camps", "Browse all ID camps →".
- Messages are never inside the listbox: the no-match line, "No upcoming ID camps match “…”" (a camp word typed, no
  camp), "Loading camps…" and "ID camps couldn't load." sit in `#homeMsg`, a plain `div` after the listbox, and the
  same text is written to `#homeStatus`.

**Rows and links.**
- Program row: `shortName || name`, then `programLine(p)` (2018), which starts with the division tag; opens
  `#/p/<slug>`.
- Camp row: the camp title, then the division tag, the program's `shortName || name` and `campDate(c)` (4317); opens
  `#/p/<slug>/camps`, the program's camps tab.
- Every option's accessible name includes the division: "UCLA, D1, College ID Camp, Sun, Jan 17".

**Enter with no active option.**
- When Programs leads and its hits include a place hit: the "All N matching programs" link (today's `placeQueryHits`
  rule, 1126 and 2541, and `showPlaceList`, 2648). "ID", "TX" and "boston" land here.
- Otherwise the first program or camp row in the panel, in section order. When the leading Camps section is empty,
  that is the first program row ("stanford camps" opens Stanford). When there is no row but a place option
  ("philadelphia"), the place option.
- Nothing on an empty slate.

## 4. Pull requests (two)

Each PR says "Part of #507", carries a test that fails on main, and runs the three CI suites as `tests.yml` does
(Python 3.12, Node 24) before pushing. Costs are estimates for a Sonnet build including one review round, not
measurements.

### PR 1: the engine, the frozen fixture and the judged set (not visible)

What changes
- `public/index.html`: `homeSearch(campRows, raw)` returning `{ sections, programsHref, enterTarget, message }`, in
  its own banner block so tests can slice it. It reads the global `S.index`, as `searchMatches` and the place memo do
  (1173-1175); the caller (and every test) sets `S.index` first. `campRows` are `campsData(...).all`, already cut to
  upcoming. Plus `campsData(idx, doc, today = todayLocal())`. No caller on the page yet; no visible change.
- `tools/search_fixture.py` (copies `tools/recs_catalog.py`'s pattern: rebuild, `--check`, `--out`): writes
  `tests/fixtures/search/programs.json` (slug, name, shortName, nickname, searchNames, city, state, region, division,
  conference: about 280 KB raw, 41 KB gz) and `tests/fixtures/search/camps.json` (slug, name, startDate, endDate,
  precision, campType, program block: under 55 KB). Each file keeps the published doc's shape that `cut()` reads:
  `programs.json` = `{ updated, programs }`, `camps.json` = `{ updated, camps }`; nothing else from either doc. The
  test clock is the date part of `camps.json`'s `updated`. Its cut is a pure function `cut(programs_doc, camps_doc)`,
  so `cut()` of the fixture's own docs gives them back unchanged. Regenerated only by a reviewed PR. `--check` against `public/data` is run by
  hand when regenerating, never by CI (as `tests/recs_catalog_test.py:7-9`), because CI also runs after every daily
  refresh. No person field (no `headCoach`); the Python test fails if a person-shaped key appears.
- `tests/fixtures/search/judged-v1.json`: the judged set of section 6, with expected first rows, must-show,
  must-not-show and section order per query.

Tests that fail on main first
- `tests/home_search_engine.test.mjs`: slices `homeSearch` (absent on main, so it fails) and runs the judged set on
  the fixture at the fixture's clock; checks the camp-word rule (including "ucla id-camp" and the "ID" exception),
  rule 3, section order, Enter target, and that `programsHref` read back through `listStateOf` gives the same program
  set (the "Show all" destination check).
- The same file pins `campsData(fixtureIdx, fixtureCamps, clock)` against two fixed clocks (the fixture's, and one a
  month later that drops the camps ending before it). It does not rely on today's real date to fail on main; the
  file already fails on main because `homeSearch` is absent.
- `tests/search_fixture_test.py`, never reading `public/data`: fixture shape and key allow-list; `cut()` run on
  made-up rows gives exactly the expected keys and drops person-shaped keys; `cut()` run on the committed fixture's own
  rows gives them back unchanged (the cut is idempotent). It reports its check count with `recs_catalog_test.py`'s
  `ok()` and `main()`, the format `run_python_suites.py` reads.

Cost: about $6-12. Risk: low. The only shared-code change is `campsData`'s optional argument; the existing
`tests/camps_page.test.mjs` must pass unchanged.

### PR 2: the Home box (visible; owner-approved mockup first)

What changes
- `renderHome` (3733) draws the box after `pageHeader`, before `.home-entries`: `<label>` "Search programs and ID
  camps" (visible or screen-reader only per the mockup), `input#homeQ` with `role=combobox`,
  `aria-autocomplete=list`, `aria-expanded`, `aria-controls=homeList`, `aria-activedescendant`, `aria-describedby`
  a hint; `div#homeList role=listbox` holding only groups and options (section 3); `div#homeMsg` after it for messages;
  one new polite region `#homeStatus`, written only when its text changes ("2 programs and 5 upcoming ID camps. Enter
  opens One Day ID Camp, USC."; or the message text).
- Wiring: input (80 ms debounce, as `setQuery`), first focus loads camps, Down/Up across sections with wrap, Enter,
  Escape closes then clears, Tab closes and moves on, mousedown on the list keeps focus, "/" focuses `#homeQ` on Home.
  Choosing a row navigates; route focus then lands on the page `h1` (#453).
- Layout: results in normal flow under the box at every width, pushing the three options down while shown; no overlay,
  so nothing new in the header/panel stacking order. On phones focus scrolls the box to the top of the viewport so rows
  show above the keyboard. Page colour tokens only (both themes), plus one new token pair, `--home-q-placeholder` in
  `[data-theme="light"]` and `[data-theme="dark"]`, used by `.home-q::placeholder`, so the contrast test can read the
  placeholder colour from a token (the cascade helper cannot read pseudo-elements).
- The layout lives on single-class selectors only, so `exactLayout` can pin them (it refuses descendant, compound and
  pseudo selectors):
  - `.home-search` (wrapper): `width: 100%; max-width: 720px`;
  - `.home-q` (the input): `width: 100%; min-width: 0`;
  - `.home-list`, `.home-msg`: no layout property at all (block, in flow). They are not keys of `expected`, because
    a key no rule sets fails (`css_cascade.mjs:44`); the `watched` predicate catches any rule that names them, so a
    `position` (or any layout property) added later fails loudly;
  - `.home-opt` (every option): `display: flex; flex-direction: column; min-height: 44px`;
  - `.home-opt-name`, `.home-opt-sub` (option text): `min-width: 0; overflow-wrap: anywhere`.
  - `watched` matches every selector that names a `.home-search`, `.home-q`, `.home-list`, `.home-msg` or
    `.home-opt*` class, compound or descendant included (`.home-opt.active`), and never `.home-entries` or
    `.home-entry`, which `shell_nav.test.mjs:299` already pins.
- `#homeMsg` sits next to the section it describes: before the listbox when Camps leads ("stanford camps"), after it
  otherwise. The mockup confirms it.
- The header box `#q` stays hidden on Home (`SEARCH_VIEWS` unchanged).
- When the program index failed to load, Home draws the try-again card and no box (`boot()` 6160-6170 renders Home
  without data); a test pins it.

Tests changed on purpose (decision 1)
- `tests/shell_nav.test.mjs` 60-70: still exactly one `id="q"` in the header and Home never reaches for `#q`, but
  `renderHome` may draw `#homeQ`. 259-280: "/" on Home focuses `#homeQ`. 282-300: Home is a heading, one line, the
  search box and three options (an `<input>` is allowed; still no rail, chips or Continue). Its existing assertion that
  Home writes nothing to `localStorage` (297) is kept and extended to typing and choosing in the box: the box never
  remembers a query (#447 decision 4).
- `tests/route_focus.test.mjs` 198-203: the pinned live-region list gains `homeStatus` (eight).

New tests that fail on main first
- `tests/home_search.test.mjs` (stub DOM, in the style of `tests/header_combobox.test.mjs`), on the PR 1 fixture and
  clock:
  - the combobox ARIA; every option tied to a program carries `class="div-tag"` with that program's division and shows
    `shortName || name`; keys; Enter rules; links (`#/p/<slug>`, `#/p/<slug>/camps`, `#/programs?q=…`);
  - the listbox rule: every child of `#homeList` is a `role=group`, every child of a group is a `role=option` or its
    one `aria-hidden` heading, and each group's `aria-labelledby` names that heading; "Show all N camps" and "Browse
    all ID camps →" are options;
  - the no-match (zzzz), no-camp (stanford camps), loading and failed-load messages appear in `#homeMsg`, never inside
    `#homeList`, and the same text is in `#homeStatus`;
  - exactly one request (`/api/v1/camps`) after the first focus, none while typing, none without focus; a failed camps
    load keeps Programs;
  - Home draws no box when the program index failed to load.
  - The clock: `todayLocal` is a top-level `const` (1009) and calls `new Date()`, so the sandbox's `Date` is a
    subclass whose no-argument constructor (and `now()`) returns the fixture clock; `load_failed_view.test.mjs:48`'s
    `FakeDate` overrides only `now()` and is not enough.
- `tests/home_search_css.test.mjs`: `exactLayout` (`tests/lib/css_cascade.mjs`) pins the exact layout declarations of
  the selectors listed above, at every `@media` they appear in; AA contrast (`tests/lib/contrast.mjs`) of the box text,
  `--home-q-placeholder`, headings, option text and the active option in both themes, as
  `tests/conference_counts.test.mjs` does. Node has no layout engine, so this pins the CSS, not the rendering.
- A human browser check, recorded in the PR body (as `header_narrow.test.mjs:5-16` records its widths): local
  `serve.py`, widths 320, 375, 768 and 1440 px, light and dark; at each, no sideways scroll, the box and rows inside
  the viewport, rows at least 44 px, focus ring visible, a screenshot or the measured widths per case.

Cost: about $15-30 (mockup artifact, build, one review round). Risk: medium. It changes the landing page and reverses
a pinned owner decision, and it adds a second combobox to the page. Under this seat's tier rule a visible redesign is
Opus work; the coordinator decides the model.

## 5. Test rules

- **Exact counts only on the frozen fixture.** Every count or order the tests pin reads `tests/fixtures/search/*`.
  Tests that touch live `public/data` assert only relations (for example "the box's Programs set equals
  `searchMatches` for the same text"), never a number.
- **No test depends on today's date.** "Upcoming" is computed with the injected clock (`campsData`'s third argument,
  and `homeSearch` receives rows already cut). Page-level tests give the sandbox a `Date` subclass whose no-argument
  constructor and `now()` return the fixture clock built at local noon (`clock + 'T12:00:00'`, as `campDayText` does),
  so no runner time zone shifts the date; `new Date(arg)` stays real. `todayLocal` (1009) cannot be reassigned.
- **No network.** `getJSON` is stubbed; tests count the requests it receives. CI's network guard stays on.
- Tests read `index.html` text and slice functions by their banner comments, as today's search tests do.

## 6. Judged set (23 queries)

"Today" is what exists now: Home has no box, so each query is scored against the header box on Programs and the ID
Camps page's box, the full plan's rule (`plan.md` 7.3). Counts are probe output on 2026-10-22 data; PR 1 re-measures
them on the frozen fixture and pins those. IDs from `judged-draft.json` where one fits; N = new.

| ID | Query | Today: header box / camps box | v1 expected |
|---|---|---|---|
| S01 | unc | 4, North Carolina first / 0 | P 4, North Carolina first; no camps |
| S02 | cal | 34, California first / 6 | P 34, California first; C 6 (USC, UCLA by "California") |
| S06 | university of michigan | 1 Michigan / 0 | P Michigan |
| K01 | tar heels | 1 North Carolina / 0 | P North Carolina |
| K06 | bulldogs | 27 / 0 | P 27; C 3, Mississippi State's (rule 3) |
| E08 | st. mary's | 6, St. Mary's (TX) first / 1 | P 6; C 1, St. Mary's (TX) |
| L01 | boston | 9 (3 name, 6 place) / 0 | P 3 rows (Boston University first) + "All 9 matching programs"; Enter opens `#/programs?q=boston` |
| L03 | TX | 51 / 3 | P 2 rows (St. Thomas TX, Trinity TX) + "All 51"; C 3 (St. Mary's TX, Concordia Texas, TCU); Enter opens `#/programs?q=TX` |
| N05 | ID | 4 (Idaho, Idaho State, 2 by place) / 81 | Programs first: 2 rows + "All 4"; C 1 (Northwest Nazarene, state ID); Enter opens `#/programs?q=ID` |
| E10 | washington | 23, Washington first / 1 | P 23; C 1 (Puget Sound) |
| M02 | id camp december | 0 / 14 | Camps first: C 19 (all December camps; the camp words no longer have to be in the title); no programs |
| M03 | ucla id camp | 0 / 1 | Camps first: C 1 UCLA; P UCLA; "ucla id-camp" gives the same |
| M04 | stanford camps | 0 / 0 | Camps first: only "Browse all ID camps", message "No upcoming ID camps match" in `#homeMsg`; P Stanford; Enter opens Stanford |
| N01 | usc camps | 0 / 0 | Camps first: C 5, all USC; P USC, USC Upstate |
| N02 | msu | 8 / 0 | P 8 (MSU alias); C 3, Mississippi State's (rule 3) |
| N03 | trojans | 7 / 0 | P 7; C 7 (USC, Troy, Trevecca Nazarene) |
| N04 | gvsu camps | 0 / 0 | Camps first: C 1 Grand Valley State; P Grand Valley State |
| E02 | a | 139 / 37 | P 139 (6 shown), C 37 (4 shown); order Programs, Camps |
| E05 | zzzz | 0 / 0 | the no-match line |
| C01 | big ten | 0 / 0 | v2 (conferences): no rows, no-match line |
| D01 | d3 ohio | 0 / 2 | v2 (fact words): P 0; C 2 (Heidelberg, Denison, by the camps matcher's whole-word D3) |
| Y01 | standford | 0 / 0 | v2 (typos): no-match line |
| H01 | erica dambach | 0 / 0 | v2 (coaches): no-match line |

Scoring: a query passes when its expected first row, must-show rows, must-not rows and section order hold. The v2
rows are pinned as known gaps, so v2 flips them on purpose. Draft queries left out: conference, list, people, city-near
and fact queries beyond these samples (all v2), and player names (out by the privacy rule, `plan.md` decision D).

## 7. Risks and open owner decisions

Risks
- **Saved Programs filters.** "All N matching programs" opens `#/programs?q=…`, which, like any shared Programs link,
  replaces and saves the visitor's Programs filters (`listArrive` → `saveState`). Decision 4.
- **Two matchers in one panel.** Programs and camps match words differently (for example "d3 ohio" finds 2 camps and
  no programs; "texas" finds camps by state name while programs list Texas by place). v1 accepts this. One engine
  is v2 (`plan.md` 4).
- **Broad queries.** "a" or "st" show 139 or 224 programs; the panel shows 6 and 4 rows and counts the rest, as the
  header box does today.
- **Camps freshness.** Upcoming is computed against the visitor's own date when camps load, as on the ID Camps page.
- **Small data.** 83 upcoming camps today; most program queries show no camps. The empty Camps section is not drawn
  unless a camp word was typed.

Open decisions (each with a recommendation)
1. **Reverse #465: a box in the Home hero.** The owner asked for it; recommendation: record the ruling on #507 before
   PR 2, and keep the header box hidden on Home.
2. **Results in flow, or an overlay panel on wide screens.** Recommendation: in flow at every width (one layout, no new
   stacking, simplest on phones). The owner picks from the PR 2 mockup.
3. **Camp matching = the ID Camps page's matcher plus rule 3.** Recommendation: yes. It keeps the camps page's
   words (city, state, region, month, D1-D3) and finds camps by alias and mascot. The alternative, names and camp
   titles only, is a new matcher and loses "TX" and "december".
4. **"All N matching programs" is a link to Programs** (exact count, replaces saved filters). Recommendation: yes, as
   every shared Programs link does. The alternative is expanding in place, as the Camps section does.

Team defaults (stand unless overridden): first show 6 programs and 4 camps; camps load at first focus; test clock =
the fixture's date; the fixture is regenerated only by a reviewed PR.

## Changes since review round 1

Huatuo's round-1 review (CHANGES REQUESTED). Every item is applied.

| Item | Change |
|---|---|
| R1 "ID" in capitals | Section 3: the Idaho exception (whole query exactly `ID` in capitals is a state code, not a camp word; Camps then shows camps at Idaho programs only). Judged row N05 added with section order and Enter target. Probe: Programs 4 (2 rows + place option), Camps 1, Enter opens `#/programs?q=ID`. |
| R2 fixture test and live data | PR 1: `tools/search_fixture.py`'s cut is a pure `cut()`; `search_fixture_test.py` runs it on made-up rows and on the committed fixture's own rows, never on `public/data`. `--check` against `public/data` is manual only. |
| R3 overflow test | PR 2: replaced by `exactLayout` pins on named single-class selectors (`.home-search`, `.home-q`, `.home-list`, `.home-msg`, `.home-opt`, `.home-opt-name`, `.home-opt-sub`), AA contrast with a new `--home-q-placeholder` token, and a recorded human browser check at 320/375/768/1440 px in both themes. |
| R4 listbox content | Section 3 "What sits inside `#homeList`": groups and options only, `aria-hidden` headings naming their group through `aria-labelledby`, the two camps links as options, every message in `#homeMsg` outside the listbox and written to `#homeStatus`. PR 2 tests each. |
| O1 Enter on an empty leading Camps section | Section 3 Enter rules: the first row in the panel ("stanford camps" opens Stanford); pinned in M04. |
| O2 page-test clock | Sections 4 and 5: a `Date` subclass whose no-argument constructor returns the fixture clock. |
| O3 the `idx` argument | Dropped: `homeSearch(campRows, raw)` reads `S.index`, as `searchMatches` does; callers and tests set it. |
| O4 place rows among the first six | Changed rather than only explained: Programs rows are non-place hits, and place hits are counted in one "All N matching programs →" option, as the header box does for place hits (2587-2592); v1 also shows it for name-only overflow, which the header box does not. L01, L03 and N05 show it. |
| O5 hyphens | Camp words are found among `normText` words; "ucla id-camp" is in M03 and the PR 1 test. |
| O6 Python report format | PR 1: `search_fixture_test.py` copies `recs_catalog_test.py`'s `ok()` and `main()`. |
| O7 no saved state | PR 2: the `localStorage` assertion in `shell_nav.test.mjs` is kept and extended to typing and choosing in the box. |
| O8 the `campsData` fail-on-main case | Replaced by two fixed clocks; the file fails on main through the missing `homeSearch`. |

Round 2 (Huatuo, APPROVE) left five optional notes, all folded in: the closing "All N" option for name-only overflow
is called an addition (section 3 and the table above); `exactLayout` details for `.home-list`/`.home-msg` and the
`watched` predicate (PR 2); `#homeMsg` placed next to the section it describes (PR 2); the fake clock built at local
noon (section 5); the fixture keeps `{ updated, programs }` and `{ updated, camps }` (PR 1).
