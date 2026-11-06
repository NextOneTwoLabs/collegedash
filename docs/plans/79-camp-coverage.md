# #79: raising dated ID camp coverage — diagnosis and plan

Part of #79. Planning only; no product code. Offline: `origin/main` bfe628a (refresh 2026-10-30T17:35Z), the
committed `programs/<slug>/sources/camps.json` records and their git history, `public/data/programs/*.json`,
`public/data/camps/index.json`, `collect/camps.py`, `build.py` and `tests/fixtures/camps/`. Nothing was fetched.
Follows `docs/plans/79-camp-zero-rows.md` (its offline slice, `camp_readability` and `coverage`, is on main).

## 0. What the stored data can and cannot tell us

- **No camp-page HTML is stored for any program that yields nothing.** `.cache/http/` is git-ignored and holds no
  camp pages here; the 38 extract fixtures are trims of pages that *do* yield rows, or hand-built. Each record keeps
  only `finalUrl`, `host`, `vendor`, `pageTitle`, `discoveredVia`, `hubUrl`, `parsed` and its rows.
- **Camp history is short:** the shallow clone has camps records from 2026-09-15 on (38 revisions each). Programs
  with dated camp-page rows: 72 of 499 records (09-16), 124 of 943 (10-01), 122 (10-15), 125 (10-30); with a row on
  or after that day: 40, 68, 64, 69. **Flat through October:** no seasonal rise is visible yet, and none can be
  predicted from this data (2027 summer camps are usually posted Jan–Mar, which we have never observed).
- So for "read but nothing dated" the data cannot separate **"page lists no dates yet"** from **"dates the reader
  misses"**. Everything below says which side the evidence points to and how strongly. Slice 1 exists to close
  this gap with counts, so later slices are ranked on measurements, not guesses.

## 1. Diagnosis by bucket (1,011 programs; my recount from the profiles matches the live `coverage` exactly)

Divisions overall: D1 349, D2 251, D3 411. The camps index lists 76 programs: 68 with an upcoming `campType: id`
row (73 counting `unknown`). Split by the stored `vendor` of the program's camp-page record, counting only programs
with at least one camp-page (`kind: camp`) row in the index: 69 programs, **Ryzer 55**, external 7, athletics site 6,
US Sports Camps 1; the other 7 reach the index through news rows only. Of the 107 camp-page rows, 86 are `id`,
11 `youth`, 10 `unknown`; **every gain estimate below counts programs gaining an upcoming `id` row only.**

### 1a. Read, nothing dated: 472 today, 481 after the row-8 label fix (by stored `vendor`, then title/URL reading)

| Vendor / host family | Programs | D1/D2/D3 | Evidence | Examples |
|---|---|---|---|---|
| **Ryzer** (school-named domains, e.g. `asusoccercamp.com`) | 173 | 81/32/60 | 170 are the site root (`/` or `/index.cfm`), the same page that yields rows on 61 other Ryzer sites; 22 had rows since 09-15 whose last dates were Sep–Oct 2026 (past camps taken down). 134 titles name soccer, 34 are all-sport camp sites. **Points to "no dates posted yet"**, not a parser gap. | adams-state (D2), alabama-am (D1), adrian-college (D3) |
| Athletics site (Sidearm etc.) | 165 | 34/46/85 | 115 titles are all-sport hubs ("Camps and Clinics", "camps-index"); 47 are soccer pages; 19 had rows since 09-15 (mostly Jun–Oct 2026). Hub hop found a target on only 18. **Mostly D3 schools whose hub lists no soccer camp, or dates in a shape we drop (§1d)**. | allegheny-college (D3), alma-college (D3), bard-college (D3, soccer page) |
| Other external camp sites | 120 | 54/27/39 | 60 are a site root; 66 titles all-sport ("Bronco Sports Camps", "Bentley Athletics Camps"), 51 soccer; 25 have no `<title>` (below). | boise-state (D1), bentley (D2), alfred (D3) |
| ↳ **probably TotalCamps on a custom domain** (of the 120) | 10 | 10/0/0 | no `<title>`, never a row, and the TotalCamps URL template: `/About%20Us` (7) or `/shop/EVENT` (3). Not detected because the vendor check reads the host and markup only. **Unverified offline.** | buffalo, virginia, san-diego-state (D1), colorado-college (D1) |
| Coach sites on Weebly | 6 | 6/0/0 | all site roots ("Home", "Welcome"); never a row; dukesocceracademy's camps live on `/idcamps` (fixture `tbd.html`). **Points to: dates on a subpage we never open.** | duke, rutgers, seton-hall (D1) |
| Wix 3, Squarespace 1, Firewood 1, CampDoc 1, US Sports Camps 2 | 8 | 3 D1 Wix: 1/1/1 | Wix pages have no `<title>` (JS-rendered, likely app shell). | bowling-green (D1, Wix), butler (D1), kennesaw-state (D1) |
| ↳ **titled pages labelled `totalcamps` by markup only** (counted `app-shell` today, §1b) | 9 | 5/4/0 | they have a `<title>`, so they are server-rendered; `detect_vendor` labelled them because the text "totalcamps" appears somewhere in the HTML (`VENDOR_MARKERS`, camps.py:204, applied at :509-511). Some are not TotalCamps at all: fresno-pacific is a Sidearm story page, ut-martin a Ryzer `?path=general` site, texas-tyler `uttyler.edu/camps/`. | iowa (D1), siena-college (D1), findlay (D2) |
| **Wrong link** (inside the rows above) | 8 | 1/4/3 | title or URL names another sport or the men's team: auburn-montgomery `?path=msoc`, lewis-clark-college "Men's Soccer Camps", dartmouth "Men's Soccer", simon-fraser `mens-soccer-camps`, mary "Women's Basketball", lycoming-college `MBB_Camps`, colorado-mesa "Women's Lacrosse", averett "canceled … COVID-19" (2020 page). bates-college (D3, "Bates Soccer Camps") is unclear and not counted. **Certain gap; the fix is a link, not a parser.** | as listed |

The rows above (Ryzer 173, athletics 165, external 120 including its 10 suspected shells, Weebly 6, and the 8 in the
Wix/… row) sum to today's 472; the 9-row line is added by row 8, giving 481. The wrong-link row is inside the others.

### 1b. App shell: 119 evidenced (+10 suspected); the live count of 128 includes 9 that are not shells

**Evidenced: the 119 on `*.totalcamps.com`**, every one with no `<title>`. D1 57 / D2 46 / D3 16 — **the most
D1/D2-heavy bucket**. Final paths: `/About%20Us` 62, `/shop/…` 35, other paths 22 (20 site roots + 2 `/Content/…` pages: cornell, idaho). **Suspected:** the 10 untitled
custom-domain pages in §1a. **Not shells:** the 9 titled custom-domain records `build.py:1516` counts as `app-shell`
only because their stored `vendor` is `totalcamps` (charleston-wv, iowa, washington-state, eastern-washington,
fresno-pacific, ut-martin, findlay, siena-college, texas-tyler); `schema/camps.schema.json:51`'s "a JavaScript app with
nothing in its HTML" is false for them. Row 8 moves them to read-nothing-dated.
No row in any revision since 09-15. Examples: abilene-christian `acusoccer.totalcamps.com/` (D1), adelphi
`…/shop/product/594388` (D2), american-international-college `aicwomenssoccercamps.totalcamps.com/shop/EVENT` (D2).
**Whether the sessions are in the HTML, a JSON call, or only after JavaScript runs is unknowable offline.**

### 1c. Other buckets

- **noLink 128:** 127 Sidearm sites (D1 27 / D2 32 / D3 69); `find_camps_link` found no camp link on the
  roster page. 4 of them have news releases announcing an ID camp (college-new-jersey, illinois-institute-technology,
  malone, roosevelt), so those programs do run camps. Examples: akron (D1), alcorn-state (D1), alfred-state-college (D3).
- **withRows but nothing upcoming: 56** of the 125 (athletics 32, Ryzer 9, external 8, US Sports Camps 5, Wix/Weebly 2).
  Correct today ("no upcoming"), and the dated rows show the reader works on these pages.
- skipped 69, robots 22, refusedHost 23, fetchFailed 14, not-a-listing 22, not-html 8: unchanged by this plan
  (#73, #38, PDF reader decision in the earlier plan).

### 1d. Where the reader gives up (`collect/camps.py`)

1. **One page per program.** `collect()` reads `finalUrl` only. `find_hub_hop` runs only when the page is on the
   athletics site *and* the link named neither women nor soccer (line 2082); a vendor or coach site's root
   (Ryzer 170, external 60, Weebly 6, Wix 3) is never hopped, so a camp list on `/idcamps` or `/camps` is never seen.
2. **Year-less dates are dropped on camp pages.** `parse_camp_dates` gives day precision only with a year in the
   text, a table-caption `default_year` (`_table_entries`, line ~1363) or a news `published` date. `_prose_entries`
   passes no page year, so "ID Camp — June 14" under a "2027 Summer Camps" heading yields nothing. How often this
   happens on the 481 is unknowable offline.
3. **Server HTML only.** No JavaScript runs, so a TotalCamps (and likely Wix) shell has no camp text.
4. **Gates drop rows silently.** `_row_allowed`, the all-sport gate (`page_soccer is False` → `_row_names_soccer`),
   `REGISTRATION_RE`/`TBD_RE` and the men's gate remove rows with no record of how many. A page whose rows were all
   gated looks the same as an empty page.
5. **Vendor detection errs both ways** (`detect_vendor`, :502-512). A markup match anywhere in the HTML
   (`VENDOR_MARKERS`, :204) labels a titled, server-rendered page `totalcamps` (the 9 in §1b), and custom-domain
   shells with no marker stay `external` (the 10 suspected).

## 2. Fixes ranked by programs gained per unit of work and risk

**Gain = programs that newly show an upcoming `campType: id` camp-page row** (youth/unknown rows are not counted),
as ranges, judged against today's rates: of the 237 readable Ryzer records (240 have `vendor: ryzer`; 3 were blocked, refused or failed), 55 (23%) have upcoming rows, and 63 of the 69
programs with camp-page rows in the index (91%) have an `id` row. "Pool" is the programs the fix can touch.

| # | Fix | Pool | ID gain (est.) | Work | Risk | Needs a fetch first? |
|---|---|---|---|---|---|---|
| 1 | **Read trace** (counts only, §3 S1): why each page yielded nothing | 481 + 119 | 0 directly; sizes rows 3, 5, 6, 7 | S | low | no |
| 2 | **Wrong-link repairs** (registry `athletics.campsUrl`, #38) | 10 | 0–6 | S per link | low | yes: a person finds the right page |
| 3 | **Follow one same-host camps subpage** on a non-Ryzer vendor/coach site root that read nothing (external 60, Weebly 6, Wix 3, Firewood 1, plus the 9 of §1b) | ≈79 | 1–10 | M | medium (1 more request per program, Monday only) | only the subpage S1 points to (owner OK) |
| 4 | **TotalCamps**: read the sessions if the HTML or a public JSON the page calls carries them | ≈129 (119 + 10 suspected) | 0–30 now (≈ 129 × 23% × 91%; many TotalCamps sites may list youth camps only; more in spring, unknowable); 0 if browser-only or ToS forbids | M–L | medium–high (ToS, undocumented endpoint) | yes: 3 samples + bundle + 1 custom domain (owner OK) |
| 5 | **Page-level year for year-less dates** (one explicit year in title/headings, no other year on the page) | unknown share of 481 | 0–15 | S–M | high (false dates) | no for the code; S1 sizes it |
| 6 | **noLink discovery** from the sport home page `/sports/womens-soccer` | 128 | 2–12 (D3-heavy; many run no camp) | M | low–medium (1 more athletics request, Monday only) | 3 samples (owner OK) |
| 7 | **All-sport hubs:** hop on a unisex "Soccer" camp link | ~180 | 0–8 | S | medium (men's camps) | no; S1 sizes it |
| 8 | **Truthful labels:** (a) a markup-only `totalcamps` match on a page with a `<title>` is not `app-shell` (the 9 move to read-nothing-dated; schema text fixed); (b) after the ubsoccercamps sample confirms it, no-title + exact `/About%20Us` or `/shop/EVENT` path + off-athletics host → `totalcamps` (the 10); (c) "past camps only, none upcoming" on the 56 + 44 | ~120 | 0 | S | low (changes public `coverage` counts) | (b) only |

Why this order: Ryzer, the biggest bucket, already reads well (61 of 64 Ryzer records with rows are the same root
page type), so its 173 are mostly seasonal and fill only when schools post 2027 dates; no parser or hop work is
planned for them, and S1's daily counts (`years`, `dayDates`) will show when they do, at no extra requests. The
largest *engineering* lever is TotalCamps, blocked on facts only a fetch gives. Row 1 is the only offline work
that sizes rows 3, 5, 6 and 7, so it goes first although it gains nothing itself. **Re-read S1's counts in
February** (when 2027 summer dates are usually posted) before ranking S5 down or closing S3.

**Unknowable offline:** how many of the 481 list no dates vs dates we miss; whether TotalCamps exposes sessions
without JavaScript, and how many of its sites list ID camps at all; whether coach sites put camps on subpages; how
many schools will post 2027 dates and when.

## 3. PR slices (ordered; each small, shippable alone, tests fail on main, frozen fixtures, no `today`)

**S1 — read trace only (fully offline, from stored fixtures).** No vendor or label change.
- `extract_camps` keeps returning `list[dict]` (callers: collect/camps.py:2006 news, :2100 camp page,
  tools/camps_check.py:315 and :562, and 5 test files). New keyword `trace: dict | None = None`, filled in place per
  call, never through the shared `STATS` (collectors run in threads). Only the camp-page call at :2100 passes one.
- Counts (no text, hosts or URLs): `{"dayDates", "yearlessDayDates", "years": {"2026": n, …}, "gated":
  {"otherSport", "mens", "allSport", "registration", "tbd", "cap"}, "sameHostCampLinks", "vendorLinks":
  {"ryzer", "totalcamps", "ussportscamps", "abc", "other"}, "textChars", "scripts"}`; `vendorLinks` keys from a fixed
  list; `gated.cap` counts rows cut by `MAX_CAMPS`. `scripts` is counted before the decompose at :1732.
  `textChars` and `scripts` are stored as coarse buckets (`0`, `<500`, `<5k`, `5k+`; `0`, `1-5`, `6+`) so the daily
  diff does not churn.
- `collect()` writes `readTrace` into `programs/<slug>/sources/camps.json` (never the camps index, per #531);
  `null` when there is no HTML, including the robots path that keeps stored camps (:2102-2109).
- Tests: new `tests/camps_read_trace_test.py` + fixture entries for `tools/camps_check.py --fixtures`:
  `ryzer-table.html`, `tbd.html` (0 rows; a `tbd` count), `hub-wofford.html` (all-sport gating),
  `synth-table-deadline.html` (registration), a new hand-built year-less page ("June 14–16" under a "2027" heading:
  `yearlessDayDates` = 1, rows = 0, pinning today's behaviour), a two-threads case (two traces stay separate), and a
  robots-kept record (`readTrace` null). Exact counts are measured on each fixture in the PR (the gate names above
  are expectations, not yet run). All fail on main (no `trace` keyword). `extract-snapshot.json` must not change.
  Gain: 0. After one refresh, a counts-only summary by bucket goes on #79 and re-ranks S3–S7.

**S2 — wrong links (registry PR, #38), 10 links.** After a person checks each page (list B): set
`athletics.campsUrl` for the 8 of §1a plus kings-college-pa (D3) and shaw (D2), whose links are Google Forms for
girls'/youth basketball camps (counted `not-a-listing` today). Separately, test-first: a fetched page whose `<title>`
names only the men's team or another sport, or a Ryzer `?path=msoc`, is recorded as a wrong link (`not-a-listing`)
rather than "nothing dated"; frozen cases are the stored titles/URLs.

**S3 — one subpage hop on non-Ryzer vendor/coach sites.** Only if S1 shows `sameHostCampLinks` > 0 on enough of the
≈79. When such a root page yields no rows, follow at most one same-host link whose text names ID/prospect/camps
(reusing `_sport_link_score` and `NOT_CAMP_PAGE_RE`), on the Monday rediscovery run only; daily runs reuse the stored
target (#284). Fixtures: trimmed copies of the subpages fetched with the owner's OK, plus a men's subpage negative.

**S4 — TotalCamps.** Only if samples (A) show sessions in server HTML or a public, robots-allowed JSON call, and the
owner accepts the vendor's terms: a narrow parser as in #388, frozen fixture, `campType` labels as today. Otherwise
close as "app-shell, link shown" (the current truthful state) and say so on #79.

**S5 — page-level year** (only if S1 shows `yearlessDayDates` on a meaningful number of pages): accept a year-less
date only when the page's title or headings carry exactly one year and the body no other; otherwise drop, as now.
Negative fixtures: two years on the page; a year only in a footer copyright; a registration-deadline line.

**S6 — noLink discovery** from `/sports/womens-soccer` (one extra athletics request, Monday only).
**S7 — all-sport hub unisex hop.** **S8 — labels** (row 8): (a) and (c) any time, test-first in
`tests/camps_readable_test.py`; (b) after the ubsoccercamps sample.

## 4. Risks

- **Public counts change.** Row 8 (and later slices) move programs between `coverage` buckets on the ID Camps page;
  `tests/camps_readable_test.py::test_coverage` and `test_validate` pin the counts on frozen records, and the PR
  states the before/after counts on today's data. S1 changes no bucket.
- **Vendor false positives both ways** are a truthfulness risk: a markup match calls a readable page a shell (today's
  9), and a URL pattern could call a non-TotalCamps site one. Hence (a) first, and (b) only with the sample, the
  exact-path + no-title + off-athletics-host rule and a negative fixture.
- **Trace is per call.** Passed in and filled by one `extract_camps` call; no module-level state, so threaded
  collectors cannot mix counts. Rows cut by `MAX_CAMPS` are counted (`gated.cap`), so a full page is not misread.
- **Robots and politeness.** Every new request goes through `fetch_checked` (robots.txt before any off-site request,
  the per-host gate, `camps-refused-hosts.json`, the #530 host stop). S3/S6 add at most one request per program per
  week. No retry loops; a 403/429 records the host as today.
- **Vendor ToS.** TotalCamps and Ryzer terms are not in the repo; reading an undocumented JSON endpoint needs the
  owner's decision on top of robots. S4 does not ship without it.
- **False dates.** Every new row passes the same gates; S5 is the riskiest and is fenced by negative fixtures and
  "exactly one year". No date is ever inferred from the run date. Rows keep `campType`, the ID Camps view shows `id`
  only, with D1/D2/D3 on every row and `shortName || name`.
- **Size and churn.** `readTrace` is ~300 bytes per source record (~0.3 MB across 943, not shipped to readers);
  coarse buckets keep daily diffs small (941 camps.json already change daily via `fetchedAt`). The camps index stays
  counts-only with no page text.
- **Refresh time.** S3 + S6 add at most ≈79 + 128 ≈ 207 requests, Monday only, spread across hosts by the gate.

## 5. Needs owner OK (fetches; nothing here has been requested)

Each is one GET of the page (and its host's `robots.txt`) with the collector's User-Agent, saved as a frozen trimmed
fixture; no other pages.

A. **Format samples** (S4, row 8b, S6):
- TotalCamps, is the data in HTML or a JSON call? `https://acusoccer.totalcamps.com/`,
  `https://aicwomenssoccercamps.totalcamps.com/shop/EVENT`,
  `https://adelphipantherswomenssoccercamps.totalcamps.com/shop/product/594388`; plus, only if the HTML is a shell,
  the script bundle it references (on the same host or the CDN host the page names, which will be reported before
  fetching it).
- Suspected TotalCamps custom domain: `https://www.ubsoccercamps.com/About%20Us`.
- noLink sport home pages: `https://gozips.com/sports/womens-soccer`, `https://alcornsports.com/sports/womens-soccer`,
  `https://www.tcnjathletics.com/sports/womens-soccer`.

B. **Wrong-link hand-checks** (S2; a person finds the women's camp page, starting from the program's site):
`https://www.coachthornesoccer.com/?path=wsoc` (auburn-montgomery), `https://golcathletics.com` (lewis-clark-college),
`https://dartmouthsports.com` (dartmouth), `https://athletics.sfu.ca` (simon-fraser), `https://www.goumary.com`
(mary), `https://lycomingathletics.com` (lycoming-college), `https://cmumavericks.com` (colorado-mesa),
`https://www.averettcougars.com` (averett), `https://kingscollegeathletics.com` (kings-college-pa),
`https://www.shawbears.com` (shaw).

Deferred, not requested now: Ryzer roots (S1's daily counts answer "no 2027 dates yet" at zero extra requests);
Weebly coach sites (only the one subpage S1's `sameHostCampLinks` points to, after S1 ships).
Not fixable by fetching: 23 refused hosts, 22 robots-blocked, 69 skipped (#73).

## Changes since review (Bianque, round 1)

- R1: §1b restated as 119 evidenced shells (+10 suspected); the 9 titled custom-domain records moved to
  read-nothing-dated (§1a) and into the S3 and row-8 pools; row 8 gains the reverse label fix; S4 pool ≈129.
- R2: abilene-christian is D1; 68 programs with an upcoming `id` row (73 with `unknown`); vendor split defined
  (camp-page programs only; 7 news-only).
- R3: Ryzer removed from row 3 (pool ≈79, gain 1–10); Monday requests ≈207.
- R4: every estimate is ID-only; row 4 allows for youth-only sites (0–30); kings-college-pa and shaw added (10 links);
  February re-read of S1 counts planned.
- R5: URL-pattern recognition removed from S1; it is row 8b, after the ubsoccercamps sample, with the guards asked for.
- R6: S1 plumbing pinned (signature, per-call trace, :2100 only, scripts counted before :1732, null without HTML,
  coarse buckets, `gated.cap`). Risks (a)–(d) added. Fetch list: Ryzer dropped, Weebly deferred, CDN host allowed.

## As built (S1, branch feat/79-s1-read-trace)

- `gated.chrome` is dropped: no code path removes a row for a chrome name (it is renamed, never rejected), so the
  count would always be 0.
- Dates and `textChars` are counted on the page content with navigation, header, footer, scoreboard and ticker
  stripped as `_content` strips them (on a copy); links on the whole page. A scoreboard's daily dates would
  otherwise rewrite every Sidearm camps.json each day.
