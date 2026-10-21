# CollegeDash search today, and what a universal search could use (issue #507)

Read-only survey of /home/user/collegedash at df9417725 (main, data refresh 2026-10-20T16:09Z). No repo file was
changed. Line numbers are from that checkout. Sizes were measured on the committed files; "gz" is gzip level 6,
measured locally (an estimate of transfer size, not a Cloudflare measurement).

The one probe script I wrote is at
/tmp/claude-0/-home-user-collegedash/d8e4b319-4da9-585a-a6b2-980aa72c1e2a/scratchpad/search507/scripts/probe_today.mjs.
It slices the page's own matcher out of public/index.html (from the "search: word-prefix" banner to the "condition
chips" banner), runs it in a `vm` over public/data/programs/index.json and prints hits. It writes nothing.

---------------------------------------------------------------------------------------------------------------------

## 0. Headline facts

1. **Home has no search box, on purpose.** On 2026-10-02 the owner directed (#465) "Home is a heading, one line and
   three large options... The search button, the example chips and Continue are gone"
   (commit 453203860, which removed the box from 4a195350b's Home the same day). renderHome is
   public/index.html:3722-3739. The header box is hidden on Home by `body.no-search` (index.html:725, set by syncNav
   3749 from SEARCH_VIEWS 2472 = list, c, p, camps). Tests pin all of this:
   tests/shell_nav.test.mjs:60-70 (exactly one `id="q"`, inside the header; renderHome may not contain `<input`,
   `appendChild`, `#q`, `setQuery`, `renderSuggestions`), :243-256 (where the box shows), :282-300 (Home draws no
   `<input` or `<button`, no `homeFind` / `data-home-chip`). **So #507 reverses a recorded owner decision, and that
   reversal needs to be confirmed on the issue before any PR.**
2. **The program index is already in memory on every page, Home included.** boot() awaits loadIndex() before route()
   (index.html:6156-6157); loadIndex fetches `/api/v1/programs` = public/data/programs/index.json (1,913,827 B,
   ~174 KB gz, 1,011 rows) and runs prepareSearch on every row (1715-1718). A programs-only search on Home costs
   no new request. Anything beyond programs (camps, clubs, high schools, coaches beyond the head coach, players)
   is either in a file loaded later or not served at all.
3. **Today's search is one matcher over program names + nickname + place.** matchScore (index.html:1137-1160)
   matches school names (shortName, name, searchNames), initials, nickname and place (state, state code in
   capitals, city, "city ST"). It does not match conferences, divisions, coaches, clubs, high schools, camps,
   players or any numeric fact. Every typed word must prefix a word of one name; facts are never parsed out of the
   query, so "D3 Ohio" returns 0 hits (probe, section 6).
4. **Places are a soft union, not a hard filter.** "Ohio" lists 44 programs: 5 name hits first, then 39 programs in
   Ohio (place hits score 20, below every name hit; index.html:1069-1118). "Washington" lists schools named
   Washington (in any state) plus the programs in WA and in Washington, DC (tests/place_search.test.mjs:135). The
   Programs address has no `state` param (LIST_PARAMS index.html:3581), so a state cannot be carried as a filter;
   ID Camps' address does have `state=` (CAMPS_PARAMS 4330).
5. **Three other search boxes exist with their own matchers**: ID Camps' header-box search (word-prefix AND over
   program names, city, state name, region, camp title, month; exact state code / division) at 4370-4402; the
   Pipelines club / high school / program boxes (substring over a name plus `aka` aliases) at 4790-4807 and
   5231-5266; the Programs rail's conference finder (substring over conference names) at 2232-2337. Plus the
   Compare add-box (5976-5991) and not-found suggestions (3857-3864), which reuse searchMatches.
6. **Ask** (owner-only, Cloudflare Access, $10/month) turns a question into the Programs filters via the Worker and
   Claude Haiku 4.5; it is never triggered by typing, only by Shift+Enter or Enter with no name match
   (index.html:2532-2534, 2720-2792; worker.js:240-330; wrangler.toml `ASK_ENABLED = "true"`). Its offline eval
   set, tests/fixtures/ask/eval.json, holds 42 judged questions with expected filter states: the closest thing
   CollegeDash has to a judged query set for "facts typed in the query".
7. **There is a frozen-data precedent**: tests/fixtures/recs/catalog.json (391,153 B, 1,011 programs), built by
   tools/recs_catalog.py from the committed data, `--check` mode, "regenerated only by a reviewed PR", so "the daily
   refresh never moves an expectation". The search tests today read the live public/data instead (section 5).

---------------------------------------------------------------------------------------------------------------------

## 1. Every search surface in public/index.html

public/index.html is 517,565 B (160,140 B gz), 6,170 lines: CSS ~79 KB / 861 lines (inside `<style>`), inline JS
~430 KB / 5,215 lines, no build step (comment at 969-977).

### 1a. The header box (#q) - "the one search box" (#434)

Markup, index.html:897-909: `<div class="header-search" role="search">` holding `<input type="search" id="q"
role="combobox" aria-autocomplete="list" aria-controls="qList" aria-describedby="qHint">`, a clear button `#qClear`,
the panel `#qPanel` (help `#qHelp`, listbox `#qList`, key-hint footer `#qFoot`), the hint `#qHint` and the
screen-reader status `#qStatus` (aria-live polite). Placeholder "School, mascot, state or city…".

Where it shows: SEARCH_VIEWS = list, c, p, camps (2472). Hidden by CSS (`body.no-search .header-search {display:
none}`, 725) on Home, Pipelines, Shortlist, Compare, FAQ, API docs, not-found. On ID Camps it searches camps instead
(see 1e). The comment above renderHome (3726) still says "it shows on Programs and a program's page only"; ID Camps
was added in #471.

Wiring (2693-2709): input -> setQuery (or campsTyped on ID Camps); keydown -> searchKeydown; focus opens the panel;
blur closes it; mousedown on the list keeps focus.

- setQuery (2458-2468): S.qRaw = typed text, S.q = normText(text); an 80 ms timer runs searchApply (status,
  suggestions, Show-results label, conference counts, and on Programs re-renders the list); listTyping() writes the
  Programs address (replaceState) 80 ms after the last key (3648-3649).
- normText (1061-1062): NFKD, accents dropped, lower case, `&` deleted ("Texas A&M" -> "texas am"), dashes -> space,
  other punctuation -> space, spaces collapsed.
- prepareSearch (1123-1134), once per program at load: short = normText(shortName || name); names = every
  `searchNames` entry (falls back to [shortName, name]) with words and a "joined" (no spaces) form; initials of the
  short name; nickname words; city.
- matchScore (1137-1160), highest wins:
  100 short name exact; 90 short name prefix; 80 every query token prefixes a distinct word of the short name (any
  order); 55 initials of the short name (3+ letters); then over searchNames: 95 exact, 70 prefix, 60 token-prefix,
  50 joined prefix (3+ letters); 30 nickname prefix / token-prefix (why = nickname); 45 short name joined prefix
  (4+ letters); else placeMatch -> 20.
- placeMatch / placeQuery (1069-1118): the WHOLE query must be a place: a full state name, a two-letter code typed
  in capitals ("OH", not "oh"), a city (normText equal), or "city state" / "city, ST" (any case after a city).
  STATE_NAMES (1085-1092) has the 50 states + DC. Programs with no state (emmanuel-ga, simon-fraser,
  claremont-mudd-scripps) never match a place (1081-1082).
- searchMatches (1169-1172) ranks all 1,011 programs by score; visibleMatches (1165-1168) cuts to what the active
  Programs filters (division, conference, region, conditions) let through (#23); matchesFilters is 3966-3973.
- Suggestions (2544-2631), an ARIA 1.2 editable combobox: up to 6 name-matched programs inside the filters
  (SUGGEST_MAX), up to 3 more "Outside your filters" in a labelled group (OUTSIDE_MAX), one "All N matching
  programs →" line when the query is a place, and "✦ Ask: …" when Ask is on. Each program option shows
  displayName and programLine (division tag, conference, city, state; 2014-2017).
- Help panel (#447, 2558-2575, 2603-2630): on focus with an empty box, a scope line counted from the index
  ("Every NCAA women's soccer program: 1,011 across D1, D2 and D3."), SEARCH_HINT "Type a school, nickname or
  mascot, a state or a city.", example chips HELP_CHIPS = Stanford, UNC, Bulldogs, Ohio, Columbus OH (PHONE_CHIPS
  = 3 of them), and on desktop the key footer. No-match panel: "No program matches “…”" + 2 chips. The comment
  (2564) says it "never mentions conferences - search does not cover them".
- Status (#qStatus, 2476-2505): "N matches · M more outside your filters · Enter opens the first / Enter shows the
  list", or the no-match hint "try the short name (UCLA, Ole Miss), the mascot, or a state or city". Written only
  when the words change.
- Keys (searchKeydown 2512-2543): arrows move/wrap; Enter on an active option chooses it; Enter otherwise opens the
  top visible hit (openFromSearch 2633-2642: box cleared, profile <h1> focused) or, for a place query, shows the
  Programs list (showPlaceList 2644-2648); Escape closes then clears; "/" focuses the box where it shows (2452).
- Nothing fetches while typing: every result comes from S.index (comment 2557, 2565).

### 1b. Search short forms and search names (built, not typed)

- build.py:1960-2007 `search_names()`: shortName, name, the NCAA name and the RPI-archive name (CamelCase split,
  "(FL)" dropped), the registry's cited `searchAliases`, initials of a 3+ word short name ("UCSB"), full-name
  initials when only "University"/"College" was dropped ("GVSU"), St./Saint swaps. summary_row puts it in each
  index row as `searchNames` (2018).
- public/data/registry.json: 35 programs carry `searchAliases`, each cited to Wikipedia in `searchAliasesNote`
  (UVA, UNC, UIUC, UGA, Cal, URI, UK, CSUF, Pitt, UMich, UTC, MTSU, Mizzou, UVM, UNM, UNT, UNF, UPenn, GW, CSULB, UNH,
  UWF, UAH, UCCS, UIndy, UMSL, UNK, UCSC, Caltech, UChicago, MIT, TCNJ, RIT, "the South" (Sewanee), WashU).
  Ambiguous forms (OSU, FSU, Miami, USF ...) deliberately get none (tests/search_short_forms.test.mjs:109-122).
- Published: 2,606 searchNames across the 1,011 rows, at most 8 per program, 441 programs with more than 2.

### 1c. Ask (#165, #179) - owner only

- Page: askSwitchedOn only if `api/ask/status` (behind Cloudflare Access, fetched with redirect:'manual') says
  {ask:true} (index.html:1745-1746, 2726-2733). Shift+Enter always asks; Enter asks when no name matches
  (2532-2534). askQuestion POSTs `api/ask` (2740-2756); applyAsk re-validates the answer against the page's own
  divisions, conferences, regions, class years, conditions and sorts, clears the query and lands on Programs
  (2759-2780); a "From your question: …" banner with Undo (2781-2792).
- Worker: worker.js:80-81 (routes), 240-330 (contract: returns only division, conf, region, classYear, cond,
  sort, reading, or {unsupported}; vocabulary read from data/programs/index.json, cached 10 min; ASK_FIELDS mirror
  COND_FIELDS; model claude-haiku-4-5-20251001; MAX_QUESTION 300). Owner-only access and $10 monthly budget in KV
  ASK_BUDGET (wrangler.toml).
- Eval: tests/fixtures/ask/eval.json, 42 cases, hand-written recordings ("no live model output yet"); tags:
  conference 17, count 8, unit 7, alias 6, region 6, rank-direction 6, unsupported 6, sort 4, score/climate/class/
  division 1 each. Questions include "ACC schools", "Big 10 programs", "admission rate under 30%", "top 25 RPI
  teams", "cheapest SEC schools", and unsupported ones: "who is the head coach at Stanford?", "players from Texas",
  "coaches in charge since 2010", "graduation rate above 80%", "compare UCLA and USC".

### 1d. The Programs rail: Conference finder and the filters

- Rail (renderSidebar 2115-2231), tab "Browse": Sort select (SORTS 2109: name, rpi, admit, academicRank, tuition,
  undergrads, titles), Division pills (only when the data has >1 division), Conditions ("+ Add": field /
  comparison / value; COND_FIELDS 1261-1288: admissionRate, tuition, undergradEnrollment, academicRank, sat25,
  rpiRank, nationalTitles, collegeCups, rosterSize, fallAvgHighF), Region pills (REGIONS 2002: West, Midwest,
  South, Mid-Atlantic, Northeast), Highlight class pills (gradYears 2026-2029; highlight only), Conference.
- Conference finder on Programs (#465 D, 2232-2337): `#mfConfInput` role=combobox over a multi-select listbox
  grouped by division; matching is `normText(conference).includes(normText(typed))` (confComboItems 2262-2266);
  each option carries the count with the other filters (confCounts 2041-2050, which includes the search query).
  Elsewhere the conferences are pills (2137-2147).
- All of it ANDs with the search (matchesFilters 3966-3973; filteredPrograms 3974-3982 sorts search hits by score
  first). The state lives in the public Programs address (#14, 3557-3639):
  `#/programs?div=&region=&conf=&class=&cond=&q=&sort=&dir=&view=` - "may grow but never change meaning". No state,
  city, size-word or tuition-bracket param exists.

### 1e. ID Camps search (#471) - the header box on #/camps

- campsTyped / campsQueryMatch (4370-4402): every query word must prefix a word of the camp's text (AND, any
  order): program short and full names, city, the state's full name, region, the camp title, and every month the
  camp's dates touch ("jun" -> June); a state code ("TX") and a division ("D1") match only as whole words; "st" and
  "saint" stand for each other; the venue is not searched. "texas june" = Texas camps in June.
- Its own address (#/camps?when=&from=&to=&region=&state=&div=&program=&q=, CAMPS_PARAMS 4330) and its own filters
  (campsMatch 4404-4415). Programs filters and the Programs query never narrow camps (owner D4,
  tests/camps_page.test.mjs:128, 236).

### 1f. Pipelines boxes (#307, #327) and the start field

- trendsFind (4799-4807): substring of a cleaned key (trendsKey 4794: `&` -> "and", apostrophes dropped) in the
  club / school name, else the shortest `aka` alias that contains it.
- trendsOptions (5231-5266): Program box uses matchScore (5243-5246); Club and High-school boxes use trendsFind,
  sorted by players; empty boxes follow the other boxes' selections. Up to 3 values per box, OR within, AND across.
- Privacy rule stated on the page (5107): "Past players and commits are counted, never named. Current players are
  listed only from a program's public roster, when you open that program's row." Also 4776-4777: "commits are
  counts only, never a list of recruits".

### 1g. Compare add-box and not-found suggestions

- Compare (5976-5991): `#cmpAdd` input, searchMatches(normText(value), 8, value) minus programs already picked;
  Enter clicks the first.
- Not found (3851-3864): slugSuggestions runs searchMatches over the bad URL segment, trimming up to 3 characters.

### 1h. Tests for these surfaces (all `node --test`, discovered by glob in CI)

| File | Lines | What it pins |
| --- | --- | --- |
| tests/header_search.test.mjs | 352 | static box in the header (43), one polite status not in a listbox (59), CSS cascade check fails loudly (130), box drawn at 375 px (151), two-row phone header (162), typing filters the list (254), Enter rules (283), phone blur (298), "/" (308), Clear search (319), Ask placeholder / Shift+Enter (333), no request while typing (345) |
| tests/header_combobox.test.mjs | 287 | ARIA combobox/listbox (117-144), shortName + division tag (162), place option (178), "Outside your filters" (197), profile focus (221, 266), mouse (240), status written only on change (255), no request (281) |
| tests/header_narrow.test.mjs | 222 | header layout at 320-400 px and >768 px (CSS cascade) |
| tests/search_help.test.mjs | 195 | help panel scope / chips / keys (99-125), every chip returns a result (145), no-match panel (160), never offers conferences, stores and fetches nothing (171) |
| tests/search_short_forms.test.mjs | 122 | UNC -> North Carolina first, score 95 (73); every alias cited and first (82); Cal, Pitt, Mizzou, MIT, WashU, UNI, GW (101); ambiguous forms unchanged, OSU top 3 = Ohio St, Oklahoma St, Oregon St (109) |
| tests/place_search.test.mjs | 252 | Ohio spans D1-D3 and exactly 3 slugs have no state (107-114), Ohio/OH (116), name hit outranks place (124), Washington (135), Georgia (148), capitals rule (155), "Ohi" not a place (166), Columbus / Columbus OH (170), no-state programs found by name (183), Enter on place keeps the list (203), on #/camps (213), #23 counts and Enter with filters (230, 244) |
| tests/d2_search_names.test.mjs | 302 | D2 short names / nicknames / initials over the real registry and index |
| tests/d3_search_names.test.mjs | 105 | D3 rows carry registry names; exact short-name and nickname hits; William Smith, Herons, Sagehens |
| tests/search_names_test.py | 160 | build.search_names(): initials restored, gated, ordered, registry aliases |
| tests/sewanee_names.test.mjs | 185 | Sewanee by prefix, exact name, old alias; camp search |
| tests/ask_page.test.mjs, ask_worker.test.mjs, ask_eval.test.mjs (+ ask_eval_live.mjs), ask_access_budget.test.mjs, ask_logging.test.mjs, ask_enabled_config.test.mjs | 294 / 241 / 99 / 386 / 183 / 122 | Ask off = byte-identical page, on = Enter/Shift+Enter, Home -> Programs (285); Worker validation; 42-case eval replay; Access + budget; logging; shipped config |
| tests/programs_rail.test.mjs | 445 | the Conference combobox (300), #425 keys (395), conf= address unchanged (426), phone sheet |
| tests/camps_page.test.mjs | 622 | camps search fields (418), normalisation (431), AND / whole-word codes (438), address and Back (450), Clear (475), Enter never navigates (499) |
| tests/trends_view.test.mjs | 852 | Pipelines boxes and results |
| tests/shell_nav.test.mjs | 317 | one #q, never on Home (60-70); where the box shows (243-256); "/" and Clear search where hidden (259-280); Home = heading + 3 options, no input or button (282-300) |
| tests/route_focus.test.mjs | 203 | typing never loses focus on route change (146); hidden box -> heading (153); exactly the existing polite live regions: campsStatus, feedbackNote, qStatus, recsCount, recsStatus, recsToast, trLive (198-203) |
| tests/list_url_state.test.mjs | 568 | the #/programs?… contract, XSS in q/conf/region (411), Home never rewritten (521), Ask from Home lands on Programs (543) |

Every one of these reads public/index.html directly (a `vm` over the inline script with a stub DOM) and, for data,
the committed public/data (not a frozen copy), except the Ask eval (its own fixture).

---------------------------------------------------------------------------------------------------------------------

## 2. The landing page (Home, `#/`) today

- route(): a bare `#/` or no hash is Home (3766-3775, 3821; currentView 2425-2429). Old `#/?…` and `#/list` links
  are rewritten to `#/programs?…` (PROGRAMS_ALIAS 3765).
- renderHome (3729-3739): pageHeader with h1 "Find your college soccer path." and one subtitle "NCAA women’s soccer
  programs, ID camps, and where club and high school players go to college."; then `<div class="content-body
  home">` with an optional load-failed card and `<nav class="home-entries" aria-label="Start here">` of three large
  links: Programs ("Explore and compare every NCAA women’s soccer program.", fact "1,011 programs" from the loaded
  index), ID Camps ("Find upcoming ID camps and their dates."), Pipelines ("See which colleges players from a club
  or high school went to.").
- CSS: `.home-entries` 3 columns, max-width 1080 px (714); `.home-entry` cards 180 px tall (715-721); at <=768 px one
  column, row layout (871-876). No rail on Home (NO_RAIL 3744). On phones the header is one row on Home
  (`body.no-search { --header-height: calc(60px + env(safe-area-inset-top, 0px)) }`, 879), and the bottom nav bar
  shows (921).
- Data: Home reads only S.index for the count. In practice its first paint waits for the full program index,
  because boot() runs route() only after loadIndex() resolves (6157); on a failed load, Home still draws with the
  try-again card (6159-6163). Home is not perf-measured (route 3821: "#394's Worker knows list, profile, trends,
  camps").
- Requests on a cold Home load: `/api/v1/programs` (1.9 MB raw), then in the background `/api/v1/status`
  (public/archive/refresh-state.json, 863,031 B raw / ~60 KB gz, used only for its `updated` stamp, 1742, 1812),
  `api/status`, `api/ask/status` (1744-1746). docs/data-api.md:75 counts "a cold load is 2 API requests".

Where a search box would sit:
- (A) Show the existing header #q on Home: add 'home' to SEARCH_VIEWS (2472). Zero new markup; on phones the header
  becomes two rows (the #434 layout); results land on Programs (Enter on a place) or a profile. Contradicts the
  owner's #465 direction and shell_nav.test.mjs:243-256, 282-300.
- (B) A large box in the Home body, between the subtitle and `.home-entries` (inside `.content-body.home`, before
  the nav at 3736). This is what a "box at the landing page" usually means, but shell_nav.test.mjs:60-70 forbids a
  second `id="q"` and forbids renderHome from drawing or moving an input. Either the header box is reused (moved or
  mirrored, both currently forbidden) or a second combobox is added (a second listbox, and any new status region
  breaks route_focus.test.mjs:198-203, which pins exactly seven polite regions).
- 4a195350b's short-lived Home (same day) had a "Find a program ↑" button that focused the header box and the #447
  chips (`homeFind`, `data-home-chip`); git show 4a195350b:public/index.html, renderHome.

---------------------------------------------------------------------------------------------------------------------

## 3. Published data a search could use without new fetching

"Without new fetching" strictly means S.index only. Everything else is listed with when the page loads it today.

### 3a. Files and routes

| Published file | Route (api/data-reader.mjs) | Raw bytes | gz (local) | Loaded by the page |
| --- | --- | --- | --- | --- |
| public/data/programs/index.json | /api/v1/programs | 1,913,827 | 173,609 | **every page load, before the first view** (loadIndex 1717) |
| public/data/list/index.json | /api/v1/list | 685,829 | 91,694 | **never** (built and served by #395 PR A, aa5abe952; the page still reads /api/v1/programs) |
| public/data/programs/{slug}.json (1,011 files) | /api/v1/programs/{slug} | 119.6 MB total; median 123,877; min 8,417; max 191,877 | ~14 KB median (51-file sample) | on opening a profile, Compare, or a Pipelines "players" row (loadProfile 1749) |
| public/data/camps/index.json | /api/v1/camps | 53,714 | 6,895 | first visit to #/camps (loadCamps 1761) |
| public/data/trends/index.json | /api/v1/trends | 1,217,865 | 258,961 | first visit to #/trends (loadTrends 1775) |
| public/data/fit/index.json | /api/v1/fit | 177,690 | 23,560 | only when recommendations are shown (3093); RECS_ENABLED = "false" in production |
| public/data/commitments/index.json | /api/v1/commitments | 2,751,842 | 201,133 | **never** (API only) |
| public/archive/refresh-state.json | /api/v1/status | 863,031 | 59,820 | every page load, background (1742) |
| public/data/registry.json | none | 1,404,084 | 133,614 | **not served**: /data/* is refused by the Worker (worker.js:84-85, 157-166) and no v1 route reads it; build input only |
| public/data/rpi/*.json (19 files) | none | ~3.7 MB | - | not served (#100) |

### 3b. programs/index.json rows (1,011; the in-memory S.index)

Fields (all 35 present on every row): slug, name, shortName, nickname, searchNames, conference, division, colors,
city, state, region, ownership, undergradEnrollment, admissionRate, sat25, sat75, academicRank, academicRankTied,
tuitionInState, tuitionOutOfState, headCoach, coachSince, nationalTitles, collegeCups, currentSeason, lastSeason,
rpiHistory, rosterSize, commitmentsByYear, fallClimate {avgHighF, avgLowF, precipIn, wetDays}, completeness, stale,
builtAt, failed, tags. Source: build.py summary_row 2010-2039.

list/index.json keeps 24 of them plus `rpi`, `lastSeason` (3 fields) and `fallAvgHighF`, and drops currentSeason,
**headCoach**, coachSince, sat75, stale, failed, builtAt, tags, rpiHistory, fallClimate (build.py:2055-2073). If the
page moves to the slim list, the head coach name leaves memory.

### 3c. Entity types: what exists, counts, fields

| Entity | Where | Count (2026-10-20 data) | Searchable fields | In memory on Home? |
| --- | --- | --- | --- | --- |
| Programs / schools (one school per program) | index rows | 1,011: D1 349, D2 251, D3 411 | name, shortName (differs from name on 1,001), nickname (1,010), searchNames (2,606), city, state, division, conference, region | yes |
| Divisions | index `division`; DIVISION_NAMES (2006) | 3 | D1/D2/D3, "Division I/II/III" | yes |
| Conferences | index `conference` | 98 division-conference pairs (D1 32, D2 22, D3 44); 96 distinct names ("Independent" in all three) | name only. **No alias or short-form table found** (D1 names are short, e.g. "ACC", "Big Ten", "Pac-12"; D2/D3 are long official names, e.g. "New England Small College Athletic Conference", and one is truncated: "Old Dominion Athletic Conf."). Ask's model supplies "Big 10" -> "Big Ten" | yes |
| Regions | index `region`; REGIONS (2002); state lists in fit constants | 5 (3 rows null) | name | yes |
| States | index `state`; STATE_NAMES (1085) | 50 codes in the data incl. DC (no AK program); 3 rows none | code, full name | yes |
| Cities | index `city` | 786 distinct city/state pairs; 62 city names occur in more than one state (Columbus, Rochester ...) | name, "city ST" | yes |
| Head coaches | index `headCoach`, `coachSince` | 926 of 1,011 rows have a name | name | yes (lost if the page switches to list) |
| All coaches and staff | profile `program.coaches`, `program.supportStaff` | 3,344 coach entries, 1,444 support staff (all profiles) | name, title | no (profile files) |
| Current roster players | profile `roster.players` | 26,715 | name, position, class, hometown (26,477), highSchool (23,813), previousSchool (3,569), major (4,144) | no |
| Commits (recruits, mostly minors) | commitments/index.json; profile `commitments` | 3,725 rows: verbal 2,355, enrolled 1,370; class 2026 1,549, 2027 1,492, 2028 682, 2029 2 | name, aliases (18), club, clubId, highSchool, city, state, position, college | no (commitments index never loaded; profile tab lists them per program) |
| Camps | camps/index.json | 97 upcoming (81 id, 8 youth, 8 unknown) from 68 programs; months concentrated Nov 2026-Jan 2027 | camp name, dates (95 day, 2 month precision), program block (name, shortName, division, city, state, region); `location` set on 3 | no (first #/camps) |
| Clubs | trends `clubs` | 1,968 entries: 340 reviewed clubs + 1,628 unmatched raw club strings; 184 with `aka` (472 alias strings); state on 65 | name, aka | no (first #/trends) |
| High schools | trends `schools` (NCES) | 7,211; every one with city and state; 342 with aka | name, city, state, aka | no |
| Stadiums | profile `program.stadium.name` | 86 profiles | name | no |
| Majors offered by a school | - | **not found**: no published list of majors per school. Only roster players' own majors (923 distinct free-text strings over 4,144 players) | - | - |
| School colours by name | - | **not found**: `colors` are hex codes only (932 rows have some) | - | - |
| Religious affiliation | profile `school.religiousAffiliation` | numeric College Scorecard codes, not decoded (670 null) | - | no |

### 3d. Facts that could act as hard filters (all already in S.index unless noted)

- Division (D1/D2/D3, "Division II", "D3"), conference, region, state, city: the Programs filters already exist for
  division / conference / region; state and city do not (they are only a place match on q).
- Size: undergradEnrollment, with the page's own bracket words UNDERGRAD_EDGES 2,000 / 5,000 / 15,000 / 30,000 and
  labels Very small, Small, Medium, Large, Very large (4128-4130); the recommender's bands are 5,000 / 15,000
  (fit constants; RECS_CATS 2812).
- Tuition: tuitionInState / tuitionOutOfState with TUITION_EDGES 15k / 30k / 45k / 60k (4131-4133); the tuition
  condition reads out-of-state (1268-1269).
- Public / private: ownership (Public 421, Private nonprofit 585, Private for-profit 2, null 3).
- Climate: fallClimate.avgHighF in the index (list: fallAvgHighF). The labels mild / four-season / cold (174 / 531 /
  254, 52 null) exist only in fit/index.json, which ordinary visitors never load.
- Academics: academicRank (THE US rank, tie flag), admissionRate, sat25 (sat75 in the full index only).
- Soccer: RPI (list `rpi` = rank in the ranking season; full index rpiHistory; Division I only, NOT_APPLICABLE
  1228), nationalTitles, collegeCups (D1 only), rosterSize, commitmentsByYear (collected for D1 only,
  COMMIT_DIVISIONS 1250).
- Condition chips (COND_FIELDS 1261-1288) and the Ask vocabulary (worker.js ASK_FIELDS) are the existing typed
  vocabulary for numeric facts; the URL carries them as `cond=field:op:value`.

---------------------------------------------------------------------------------------------------------------------

## 4. Constraints

### 4a. One large index.html, no build step
- All UI is in the inline script; tests slice it out of the HTML text and run it in a `vm` (e.g.
  search_short_forms.test.mjs:40-70). New search code either lives inline (adding to 430 KB of JS that every page
  parses) or in a separate file loaded lazily, as public/recs.js is (27,322 B, loaded on first panel open via a
  `<script>` tag, 2838-2846, and `require`d directly by node tests, tests/recs_helpers.mjs:7).
- Pinned layout and a11y: header CSS cascades (header_search, header_narrow), the one #q (shell_nav), the exact set of
  live regions (route_focus:198-203), Huatuo's ARIA conditions on every combobox so far (#434, #445, #465 D).

### 4b. Worker and API rate limits
- /data/* and /archive/* are refused (worker.js:84-85); data reaches the page only through `/api/v1/*` routes listed
  in api/data-api.mjs:5-14 and mapped to files in api/data-reader.mjs:2-24. A new search file needs: a route there,
  a row in docs/data-api.md's table (14-28), tests like tests/data_api.test.mjs:217-260 (the /api/v1/list precedent,
  including the JSON 404 before the first build has written the file), and the perf resource map if it is to be
  measured (perfRes 1592-1595, PERF_VIEWS 1569).
- Every /api/v1 answer is `cache-control: no-cache` (data-api.mjs:62-65): ETag revalidation on every page load that
  asks for it.
- Session gate (api/session.mjs; wrangler.toml [[ratelimits]]): RL_SESSION 180 / 60 s per session, RL_ANON 60 / 60
  s per IP without a cookie, RL_IP 1,200 / 60 s, RL_KEY 60 / 60 s. One extra request at first focus is far inside
  these; a request per keystroke would not be (and the tests forbid any request while typing).
- Ask is the only server-side search path; it costs money and is owner-only.

### 4c. The data refresh would have to build any search data
- .github/workflows/refresh.yml: daily cron "0 11 * * *" (line 61); a `build_only` dispatch rebuilds without
  collecting (144-148). After collecting, the commit step rebuilds on the current main and runs
  `python collegedash.py build` then `validate`; a failure there publishes nothing but the sources
  (485-488).
- build.py build() (2203-2290) writes, from one `updated` stamp: programs/index.json (2253), list/index.json
  (2254, compact), fit/index.json (2255, compact), commitments/index.json (2257), camps/index.json (2261, compact),
  trends (2269). validate() (2293-2328) checks profiles against schema/profile.schema.json, then titles, ranks,
  seasons, camps, stale profiles, membership, staged registry, publish gate, the list (check_list_index 2378-2398:
  must be exactly the slim cut of the full index, plus schema/list.schema.json) and fit (2438). schema/ holds
  camps, fit, list and profile schemas. A search index would follow the list/fit pattern: a builder in build(), a
  `check_*` in validate(), a schema in schema/.
- A new derived file only appears after the next refresh (or a build_only run) on main; the page must work when it
  is missing (the #395/#401 lesson in tests/data_api.test.mjs:217-260).
- Stale comment: build.py:2260 says Home loads the camps index "for its camp preview (owner decision D2)"; renderHome
  no longer loads it.

### 4d. CI suites
- .github/workflows/tests.yml runs on every pull request, every push to main, and after every "Refresh program data"
  run (workflow_run), always against `main` as refreshed (lines 1-95). Python suites (tests/*_test.py, floor 396
  checks), the camps fixtures (390), and Node suites (tests/*.test.mjs, discovered by glob, floor 15), all offline;
  tests/netguard exists to block the network.
- Because tests run after each daily refresh against live data, any expectation pinned on public/data can turn red
  without a code change (the recent fix b82c32033, "profile_pruning T4 no longer depends on the day it runs (#505)",
  is the same class of problem). Search tests today mostly compute expectations from the shipped index, but some pin
  live facts: exactly three stateless slugs (place_search.test.mjs:113), "Ohio spans D1-D3" (110), OSU's top three
  (search_short_forms.test.mjs:121), UNC/Cal/Pitt/... ordering (73-107).
- Frozen-data precedent to copy for exact counts: tests/fixtures/recs/catalog.json + tools/recs_catalog.py `--check`
  ("so the daily refresh never moves an expectation"; it keeps programs and schools only - "no coach, staff, roster,
  commitment or contact field").
- Judged-set precedents: tests/fixtures/ask/eval.json (42 questions with expected filter states) and the recommender's
  tests/fixtures/recs/scenarios.json + heldout_reviewer.jsonl (docs/recs-heldout-review.md).

### 4e. Product and privacy decisions already on record
- #465 (owner, 2026-10-02): no search box on Home; the box only where it searches (section 0 point 1).
- #447 decision 4: no recent searches (saved state) in the help panel (2565).
- #23: search counts and Enter respect the Programs filters; #471 / owner D4: ID Camps does not read Programs filters
  or query.
- Pipelines never names past players or commits (5107, 4776-4777); the frozen recs catalog excludes people fields.
  Cross-program search over commit names (minors: name, club, high school, home city) would be new exposure; today
  names appear only inside one program's Commitments tab (tabCommitments 5788-5812) and the keyed API.
- Commitments are "Not collected" outside D1 (COMMIT_DIVISIONS 1250), so any commit-based answer must say so for
  D2/D3.

---------------------------------------------------------------------------------------------------------------------

## 5. How the existing tests treat data (relevant to "exact counts only on frozen data")

- header_combobox, search_help, place_search, d3_search_names, search_short_forms read
  public/data/programs/index.json (and registry.json) at test time and count expected sets from it ("never from the
  page's own search code"). They are robust to normal daily changes but run on whatever the refresh committed.
- d2_search_names builds a synthetic index from the real registry rows.
- No search test uses a frozen copy of the data today.

---------------------------------------------------------------------------------------------------------------------

## 6. Today's search on sample queries (probe; programs index of 2026-10-20)

Counts below are from today's data and will move with refreshes; they are a snapshot for orientation, not numbers to
pin.

| Query | Hits (name / place) | Top results (score: why) |
| --- | --- | --- |
| Stanford | 1 (1/0) | Stanford (100) |
| UNC | 4 (4/0) | North Carolina (95: UNC), UNC Wilmington, Greensboro, Asheville (90) |
| Ohio | 44 (5/39) | Ohio (100), Ohio State, Ohio Dominican, Ohio Northern (90) |
| OH (capitals) | 44 (7/37) | Ohio State, Ohio, Ohio Dominican, Ohio Northern (90) |
| D3 Ohio, Ohio D3 | 0 | - |
| ACC, SEC, Big Ten, Pac-12, Ivy League | 0 | - |
| D1, Division III | 0 | - |
| Paul Ratcliffe, Ratcliffe (Stanford's head coach) | 0 | - |
| Cardinal | 16 | Stanford (30: Cardinal), Louisville, Ball State (30: Cardinals), Lamar (30: Lady Cardinals) |
| Bulldogs | 27 | Mississippi State, Georgia, Samford, Gonzaga (30: Bulldogs) |
| texas am / Texas A&M | 5 | Texas A&M (100), A&M–Corpus Christi, A&M International (90), East Texas A&M (80) |
| St Marys | 5 | Saint Mary's (95: St Marys), St. Mary's (50), Saint Mary's (MN) (50), Saint Mary's (IN) (50) |
| Columbus OH | 3 (0/3) | Ohio State, Ohio Dominican, Capital (20: Columbus, OH) |
| Boston | 9 (3/6) | Boston University, Boston College (90), Massachusetts Boston (80), Northeastern (20: Boston, MA) |
| New York | 89 (22/67) | New York (100), SUNY Brockport, SUNY Canton, City College of New York (80) |
| NYC, Bay Area, west coast | 0 | - |
| Los Angeles | 5 (2/3) | Cal State LA (80), UCLA (60), USC, Loyola Marymount (20: Los Angeles, CA) |
| LA | 54 (49/5) | La Salle, Lamar, Lafayette, Lake Erie (90) - "LA" in capitals is also Louisiana |
| Miami | 4 (2/2) | Miami (FL), Miami (OH) (90), FIU, Barry (20: Miami, FL) |
| Hawaii | 4 (3/1) | Hawaii (100), Hawaii Pacific (90), Hawaii at Hilo (80), Chaminade (20: in Hawaii) |
| Cal | 34 | California (90), Cal State Fullerton, Cal Poly, Cal State Bakersfield (90) |
| Seminoles | 1 | Florida State (30: Seminoles) |
| MVLA (a club) | 0 | - |
| stanford roster, stanford camps, ID camps Texas | 0 | - |
| cheap schools, nursing, small schools in the west | 0 | - |

Read with the Ask eval's questions, these show the gaps a universal box would close: conferences, divisions and other
facts typed with a name or place ("D3 Ohio"), coaches, clubs / high schools (Pipelines), camps, and intents that name
a profile tab ("stanford roster").

---------------------------------------------------------------------------------------------------------------------

## 7. Things noticed in passing (not search bugs, not acted on)

- The page reads the full 1.9 MB /api/v1/programs on every load; the slim 686 KB /api/v1/list was built for it
  (#395 PR A) but the page switch has not landed (index.html:1717; data-api.mjs:10 calls list "the slim program list
  the site reads"). Phone parse cost scales with raw size (build.py:2058-2059).
- Every load also fetches /api/v1/status, the 863 KB refresh-state.json, to read one timestamp (1742, 1812).
- Stale comments: index.html:3726 (box shows on Programs and profile only; ID Camps too since #471); build.py:2260
  (Home camp preview no longer exists).
