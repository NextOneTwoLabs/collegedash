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

Divisions overall: D1 349, D2 251, D3 411. Of the 76 programs in the camps index (73 with dated upcoming ID camps),
**55 come from Ryzer sites**, 10 external, 9 athletics sites, 1 US Sports Camps, 1 news only.

### 1a. Read, nothing dated: 472 (by stored `vendor`, then title/URL reading)

| Vendor / host family | Programs | D1/D2/D3 | Evidence | Examples |
|---|---|---|---|---|
| **Ryzer** (school-named domains, e.g. `asusoccercamp.com`) | 173 | 81/32/60 | 170 are the site root (`/` or `/index.cfm`), the same page that yields rows on 61 other Ryzer sites; 22 had rows since 09-15 whose last dates were Sep–Oct 2026 (past camps taken down). 134 titles name soccer, 34 are all-sport camp sites. **Points to "no dates posted yet"**, not a parser gap. | adams-state (D2), alabama-am (D1), adrian-college (D3) |
| Athletics site (Sidearm etc.) | 165 | 34/46/85 | 115 titles are all-sport hubs ("Camps and Clinics", "camps-index"); 47 are soccer pages; 19 had rows since 09-15 (mostly Jun–Oct 2026). Hub hop found a target on only 18. **Mostly D3 schools whose hub lists no soccer camp, or dates in a shape we drop (§1d)**. | allegheny-college (D3), alma-college (D3), bard-college (D3, soccer page) |
| Other external camp sites | 120 | 54/27/39 | 60 are a site root; 66 titles all-sport ("Bronco Sports Camps", "Bentley Athletics Camps"), 51 soccer; 25 have no `<title>` (below). | boise-state (D1), bentley (D2), alfred (D3) |
| ↳ **probably TotalCamps on a custom domain** (of the 120) | 10 | 10/0/0 | no `<title>`, never a row, and the TotalCamps URL template: `/About%20Us` (7) or `/shop/EVENT` (3). Not detected because the vendor check reads the host and markup only. **Unverified offline.** | buffalo, virginia, san-diego-state (D1), colorado-college (D1) |
| Coach sites on Weebly | 6 | 6/0/0 | all site roots ("Home", "Welcome"); never a row; dukesocceracademy's camps live on `/idcamps` (fixture `tbd.html`). **Points to: dates on a subpage we never open.** | duke, rutgers, seton-hall (D1) |
| Wix 3, Squarespace 1, Firewood 1, CampDoc 1, US Sports Camps 2 | 8 | 3 D1 Wix: 1/1/1 | Wix pages have no `<title>` (JS-rendered, likely app shell). | bowling-green (D1, Wix), butler (D1), kennesaw-state (D1) |
| **Wrong link** (inside the rows above) | 8 | 1/4/3 | title or URL names another sport or the men's team: auburn-montgomery `?path=msoc`, lewis-clark-college "Men's Soccer Camps", dartmouth "Men's Soccer", simon-fraser `mens-soccer-camps`, mary "Women's Basketball", lycoming-college `MBB_Camps`, colorado-mesa "Women's Lacrosse", averett "canceled … COVID-19" (2020 page). bates-college (D3, "Bates Soccer Camps") is unclear and not counted. **Certain gap; the fix is a link, not a parser.** | as listed |

### 1b. App shell: 128 (all `vendor: totalcamps`)

119 on `*.totalcamps.com`, 9 on custom domains (iowasportscamps.com, wsuathleticcamps.com, sienacamps.com, …).
D1 62 / D2 50 / D3 16 — **the most D1/D2-heavy bucket**. Final paths: `/About%20Us` 62, `/shop/…` 35, `/` 27.
No row in any revision since 09-15. Examples: abilene-christian `acusoccer.totalcamps.com/` (D2), adelphi
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
   (Ryzer 170, external 60, Weebly 6) is never hopped, so a camp list on `/idcamps` or `/camps` is never seen.
2. **Year-less dates are dropped on camp pages.** `parse_camp_dates` gives day precision only with a year in the
   text, a table-caption `default_year` (`_table_entries`, line ~1363) or a news `published` date. `_prose_entries`
   passes no page year, so "ID Camp — June 14" under a "2027 Summer Camps" heading yields nothing. How often this
   happens on the 472 is unknowable offline.
3. **Server HTML only.** No JavaScript runs, so a TotalCamps/Wix shell gives an empty body (`app-shell`).
4. **Gates drop rows silently.** `_row_allowed`, the all-sport gate (`page_soccer is False` → `_row_names_soccer`),
   `REGISTRATION_RE`/`TBD_RE` and the men's gate remove rows with no record of how many. A page whose rows were all
   gated looks the same as an empty page.
5. **Vendor detection** reads host and markup (`detect_vendor`), so custom-domain TotalCamps shells with no marker
   in the HTML stay `external` and are counted as "read nothing" instead of `app-shell`.

## 2. Fixes ranked by programs gained per unit of work and risk

Gains are new programs with a dated **upcoming** camp-page row, as ranges. "Pool" is the programs the fix can touch.

| # | Fix | Pool | Gain (est.) | Work | Risk | Needs a fetch first? |
|---|---|---|---|---|---|---|
| 1 | **Read trace** (counts only, §3 S1): why each page yielded nothing | 472 + 128 | 0 directly; turns rows 3–7 from guesses into measurements | S | low | no |
| 2 | **Wrong-link repairs** (registry `athletics.campsUrl`, #38) | 8 | 0–6 | S per link | low | yes: a person finds the right page |
| 3 | **Follow one same-host camps subpage** on a vendor/coach site root that read nothing (Weebly, Wix, external, Ryzer) | ~240 | 3–25 | M | medium (1 more request per program, weekly) | samples (owner OK) |
| 4 | **TotalCamps** (128 + ~10 custom domains): read the sessions if the HTML or a public JSON the page calls carries them | ~138 | 0–90 (all or nothing per vendor; 0 if browser-only or ToS forbids) | M–L | medium–high (ToS, undocumented endpoint) | yes: 3–4 samples (owner OK) |
| 5 | **Page-level year for year-less dates** (one explicit year in title/headings, no other year on the page) | unknown share of 472 | 0–20 | S–M | high (false dates) | no for the code; trace sizes it |
| 6 | **noLink discovery** from the sport home page `/sports/womens-soccer` and the site's own camps nav | 128 | 2–15 (D3-heavy; many run no camp) | M | low–medium (1 more athletics request, weekly) | samples (owner OK) |
| 7 | **All-sport hubs:** hop on a unisex "Soccer" camp link | ~180 | 0–10 | S | medium (men's camps) | no; trace sizes it |
| 8 | **Truthful labels:** custom-domain TotalCamps → `app-shell`; "past camps only, none upcoming" on the 56 + 44 | ~110 | 0 | S | low | no |

Why this order: Ryzer, the biggest bucket, already reads well (61 of 64 roots with rows are the same page type), so
its 173 are mostly seasonal and will fill only when schools post 2027 dates; no parser work moves them now. The
largest *engineering* lever is TotalCamps, but it is blocked on facts only a fetch can give. Row 1 is the only
offline work that de-risks rows 3, 5, 6 and 7, so it goes first even though it gains nothing by itself.

**Unknowable offline:** how many of the 472 list no dates vs dates we miss; whether TotalCamps exposes sessions
without JavaScript; whether coach sites put camps on subpages; how many schools will post 2027 dates and when.

## 3. PR slices (ordered; each small, shippable alone, tests fail on main, frozen fixtures, no `today`)

**S1 — read trace (fully offline, from stored fixtures).** `extract_camps` returns its rows as today and fills a
counts-only `readTrace` that `collect()` writes into `programs/<slug>/sources/camps.json` (never into the camps
index, never page text, per #531):
`{"dayDates": n, "yearlessDayDates": n, "years": {"2026": n, "2027": n}, "gated": {"otherSport": n, "mens": n,
"allSport": n, "registration": n, "tbd": n, "chrome": n}, "sameHostCampLinks": n, "vendorLinks": {"ryzer": n,
"totalcamps": n, "ussportscamps": n, "abc": n, "other": n}, "textChars": n, "scripts": n}`.
`vendorLinks` keys come from a fixed list (no hosts or URLs). Also: `detect_vendor` treats a no-title page whose
path is `/About%20Us` or `/shop/EVENT` as `totalcamps`, which moves the ~10 custom domains to `app-shell` (row 8).
Tests (new `tests/camps_read_trace_test.py` + fixture entries read by `tools/camps_check.py --fixtures`):
`ryzer-table.html`, `tbd.html` (`gated.tbd` = 1, no rows), `hub-wofford.html` (`gated.allSport` > 0),
`synth-table-deadline.html` (`gated.registration`), a new hand-built year-less page ("June 14–16" under a
"2027" heading: `yearlessDayDates` = 1, rows = 0, which pins today's behaviour), and a hand-built no-title
`/About%20Us` shell → `totalcamps`. Each asserts exact counts, measured on the fixture in the PR (the gate counts
named here are expectations, not yet run). All fail on main (no `readTrace`, vendor `external`).
`extract-snapshot.json` must not change (rows identical). Gain: 0. After one refresh, a counts-only summary of
`readTrace` by bucket goes on #79 and re-ranks S3–S6.

**S2 — wrong-link repairs (registry PR, #38).** After a person checks each page (owner OK list, B): set
`athletics.campsUrl` for the 8. Separately, a test-first change so a fetched page whose `<title>` names only the
men's team or another sport, or a Ryzer `?path=msoc`, is recorded as a wrong link (`not-a-listing`) rather than
"nothing dated"; frozen cases are the 8 stored titles/URLs above.

**S3 — one subpage hop on vendor/coach sites.** When a non-athletics root page yields no rows, follow at most one
same-host link whose text names ID/prospect/camps/schedule (reusing `_sport_link_score` and `NOT_CAMP_PAGE_RE`),
on the Monday rediscovery run only; daily runs reuse the stored target as they reuse `campsUrl` (#284). Fixtures:
trimmed real pages from the owner-approved samples (A), frozen. Ships only if S1 shows `sameHostCampLinks` > 0 on
enough of the pool.

**S4 — TotalCamps.** Only if samples (A) show sessions in server HTML or a public, robots-allowed JSON call: a
narrow parser as in #388, frozen fixture, `campType` labels as today. If browser-only, close as "app-shell, link
shown" (the current truthful state) and say so on #79.

**S5 — page-level year** (only if S1 shows `yearlessDayDates` on a meaningful number of pages): accept a year-less
date only when the page's title or headings carry exactly one year and the body no other; otherwise drop, as now.
Negative fixtures: two years on the page; a year only in a footer copyright; a registration-deadline line.

**S6 — noLink discovery** from `/sports/womens-soccer` (one extra request to the athletics host, Monday only).
**S7 — all-sport hub unisex hop** and **S8 — past-only label** ("Camps listed earlier; none upcoming"), each small.

## 4. Risks

- **Robots and politeness.** Every new request goes through `fetch_checked` (robots.txt before any off-site
  request, the per-host gate, `camps-refused-hosts.json` and the #530 host stop). S3/S6 add at most one request per
  program per week, on the Monday run. No retry loops; a 403/429 records the host as today.
- **Vendor ToS.** TotalCamps and Ryzer terms are not in the repo; reading an undocumented JSON endpoint needs the
  owner's decision on top of robots. S4 does not ship without it.
- **False dates.** Every new row passes the same gates; S5 is the riskiest and is fenced by negative fixtures and
  "exactly one year". No date is ever inferred from the run date. Camps keep `campType` (`id`/`youth`/`unknown`), and
  the ID Camps view still shows `id` only, with D1/D2/D3 on every row and `shortName || name`.
- **Page size.** `readTrace` is ~300 bytes per source record (~0.3 MB across 943 records, not shipped to readers);
  the camps index stays counts-only with no page text.
- **Refresh time.** S3/S6 add ≤ ~370 requests on Monday only, spread across hosts by the existing gate.
- **Wrong-program pages.** A subpage hop can land on another team's camps; the men's/other-sport gates and the
  hop's women/soccer scoring apply, and the S3 fixtures include a men's subpage as a negative.

## 5. Needs owner OK (fetches; nothing here has been requested)

Each is one GET of the page (and its host's `robots.txt`) with the collector's User-Agent, results saved as frozen
trimmed fixtures; no other pages.

A. **Format samples** (S3, S4):
- TotalCamps, is the data in HTML or a JSON call? `https://acusoccer.totalcamps.com/`,
  `https://aicwomenssoccercamps.totalcamps.com/shop/EVENT`,
  `https://adelphipantherswomenssoccercamps.totalcamps.com/shop/product/594388`, plus, only if the HTML is a shell,
  the same-host script bundle it references (to find the endpoint it calls).
- Suspected TotalCamps custom domain: `https://www.ubsoccercamps.com/About%20Us`.
- Ryzer roots that read nothing, to confirm "no 2027 dates yet": `https://www.asusoccercamp.com/`,
  `https://www.alabamastateidcamp.com/`, `https://www.rolltidesocceracademy.com/`; and one that yields rows, for
  comparison: `https://www.angelosoccercamps.com/`.
- Weebly coach sites (subpage hop): `https://www.dukesocceracademy.com/`, `https://www.rutgerswomenssoccercamps.com/`.
- noLink sport home pages (S6): `https://gozips.com/sports/womens-soccer`,
  `https://alcornsports.com/sports/womens-soccer`, `https://www.tcnjathletics.com/sports/womens-soccer`.

B. **Wrong-link hand-checks** (S2; a person finds the women's camp page, starting from the program's site):
`https://www.coachthornesoccer.com/?path=wsoc` (auburn-montgomery), `https://golcathletics.com` (lewis-clark-college),
`https://dartmouthsports.com` (dartmouth), `https://athletics.sfu.ca` (simon-fraser), `https://www.goumary.com`
(mary), `https://lycomingathletics.com` (lycoming-college), `https://cmumavericks.com` (colorado-mesa),
`https://www.averettcougars.com` (averett).

Not fixable by fetching: 23 refused hosts, 22 robots-blocked, 69 skipped (#73).
