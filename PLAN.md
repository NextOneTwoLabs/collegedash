# CollegeDash: Women's Soccer College Program Database & Research Dashboard

## Context

You want a research platform for a high-school athlete (your family, one athlete first) to evaluate
NCAA Division I women's soccer programs. Step one is a **program profile database**: one rich,
multi-source, continuously enrichable profile per program (school, location, climate, program history,
yearly RPI, staff, roster, **up-to-date commitments**, plus your own narrative notes). Later phases add
a **student profile → personalized recommendations with reasoning**, then **application tracking**.

Stanford is the first program onboarded end to end.

### What exists today
- `CollegeDash/CollegeSoccerDashboard.jsx` + `index.html`: a 21-school React prototype with hardcoded,
  **unverified** data (e.g. UCLA "Gof Boyoko" looks fabricated). UI reference only → moved to `legacy/`.
- `ECNLDash/` (sibling project): the pattern to copy. `public/` is both Cloudflare static root and local
  server root; Python `archive.py` pre-fetches data into JSON on disk; a `sources.json` registry drives
  everything; a GitHub Action refreshes on schedule and commits; no build step.

### Decisions made with you
| Decision | Choice |
|---|---|
| Audience | Your family / one athlete. No auth; student profile is a local file. |
| Scope | NCAA D1 only (~350 programs). Stanford → ACC/top-25 → all D1. |
| Storage | JSON files in git + static site (ECNLDash pattern), Cloudflare Pages. |
| Narrative | Written by you in a curated file scrapers never touch. |
| Social extraction | **No LLM.** Keyword filter surfaces candidate posts; you approve records in a review queue. |
| X access | Dedicated throwaway account, browser automation (Playwright), low volume, runs on your PC. |
| Instagram access | Dedicated throwaway account, browser automation, same agent. |

### Decisions I made (override if you disagree)
- Vanilla JS single `public/index.html` like ECNLDash (no React/Babel in browser).
- Python 3 + `requests` + `beautifulsoup4` for collectors; `playwright` for the social scout.
- RPI history 2007 → present (what exists publicly).
- New git repo in `CollegeDash/`, GitHub + Cloudflare Pages like ECNLDash.
- Social scout runs **locally** (Windows Task Scheduler, daily) — login sessions must stay on your
  machine; GitHub Actions handles only the public-web collectors.

---

## Architecture

### Repo layout
```
CollegeDash/
  public/                          # static site root = Cloudflare output dir
    index.html                     # dashboard (single file, vanilla JS)
    data/
      registry.json                # D1 program registry: slug, name, conf, site platform, ids, social handles
      programs/index.json          # built: summary row per program
      programs/<slug>.json         # built: full merged profile
      rpi/<year>.json, current.json
      commitments/index.json       # built: all approved/confirmed commits across programs (for roster-need analysis)
      student/profile.json         # phase 5
    archive/refresh-state.json     # last-run times per collector
  programs/<slug>/                 # SOURCE OF TRUTH per program (git-tracked)
    curated.json                   # your narrative + overrides. Machines never write it.
    commitments.reviewed.json      # your decisions: approved social records, merges, status overrides
    sources/
      athletics.json  scorecard.json  climate.json  wikipedia.json
      commitments.tds.json  commitments.soccerwire.json  news.json
  data/commitments/                # global sweeps (all D1), git-tracked
    tds-girls-<gradYear>.json      # every girls commit on TDS for that class, with firstSeen/lastSeen
    soccerwire-girls-<gradYear>.json
  scout/                           # social-media scout (local only)
    watchlist.json  keywords.json  state.json   # state: last-seen post id per account
    queue/<post_id>.json           # candidate posts pending your review (text, url, thumb, hints)
    cache/                         # thumbnails (gitignored)
    browser-profile/               # Playwright persistent profile w/ logins (gitignored)
  collect/                         # public-web collectors
    common.py  athletics_site.py  adapters/{wmt.py,sidearm.py}
    scorecard.py  climate.py  wikipedia.py  rpi.py
    commitments_tds.py  commitments_soccerwire.py  news.py
  scout/scout.py                   # Playwright agent (X + Instagram adapters)
  build.py                         # merge -> public/data; entity-resolve commitments; validate schema
  serve.py                         # local static server + write endpoints for curated/review (local only)
  collegedash.py                   # CLI
  schema/profile.schema.json
  .github/workflows/refresh.yml
  legacy/  requirements.txt  README.md  wrangler.toml  .gitignore
```

### Profile data model (`public/data/programs/<slug>.json`)
Every section carries `_meta: {source, url, asOf}`; `curated` overrides same-named fields at build.
```jsonc
{ "slug","name","nickname","division","conference","colors",
  "ids": { "scorecardUnitId","tdsClgId":267,"athleticsUrl","athleticsPlatform":"wmt","wikipedia",
           "social": {"x":"StanfordWSoccer","instagram":"stanfordwsoc"} },
  "school":   { city,state,lat,lon,locale,enrollment,admissionRate,sat25_75,act25_75,tuitionIn,tuitionOut,netPrice,gradRate,carnegie,website },
  "climate":  { monthly:[{month,tHighF,tLowF,precipIn}], summary },
  "program":  { headCoach:{name,title,since,bioUrl}, staff:[{name,title,bioUrl}], stadium:{name,capacity}, founded,
                nationalTitles:[years], collegeCups, conferenceTitles:[years] },
  "seasons":  [{ year,record,confRecord,confFinish,ncaaResult,rpiRank,rpiValue,pollRank }],
  "roster":   { season, players:[{number,name,pos,height,class,hometown,highSchool,club,major,bioUrl}], byPosClass },
  "rosterHistory": { "2025":[...], "2024":[...] },
  "commitments": [ /* see below */ ],
  "schedule": { season, games:[{date,opponent,homeAway,result,score,location}] },
  "curated":  { programSummary,playingStyle,culture,academicsNotes,recruitingNotes,tags,myFitNotes,links },
  "_build":   { builtAt, completeness, stale:[...] } }
```

### Commitment record (the unit of the whole commitments pipeline)
```jsonc
{ "id": "kennedy-kelly-2026", "name": "Kennedy Kelly", "pos": "D", "club": "Tophat SC", "state": "GA",
  "gradYear": 2026, "college": "stanford",
  "status": "verbal" | "signed" | "enrolled" | "decommitted",
  "announced": "2025-06-14",                 // best-known date
  "announcedSource": "instagram_post" | "press_release" | "first_seen",
  "confidence": "confirmed" | "single-source" | "unreviewed",
  "sources": [ { "kind":"tds", "url":"…clgid-267/tab-commitments", "firstSeen":"2026-09-06", "lastSeen":"2026-09-06" },
               { "kind":"soccerwire", "url":"…", "firstSeen":"…", "lastSeen":"…" },
               { "kind":"instagram", "url":"https://www.instagram.com/p/…", "postedAt":"2025-06-14", "approvedBy":"you" },
               { "kind":"press_release", "url":"https://gostanford.com/news/…", "postedAt":"2025-11-12" } ] }
```

---

## Commitments pipeline (deep dive)

### Sources, verified today
| Source | What it gives | Access | Role |
|---|---|---|---|
| **TopDrawerSoccer team tab** `…/women/stanford/clgid-267/tab-commitments` | Per program: name, pos, club, state, grad year (18 Stanford commits for 2026–28 today). No dates. | Public HTML, no login. | Primary structured source per onboarded program. |
| **TopDrawerSoccer commitments search** `/search/?genderId=f&graduationYear=2027&area=commitments&pageNo=N` | Every girls commit for a class: name, state, pos, grad, college. Paginated. No college filter, no dates. | Public HTML. | Daily all-D1 sweep → detects new commits for every program by diff. |
| **SoccerWire player directory** `/soccer-player-directory/?filter=<base64 JSON>` with facets `meta.gender.raw`, `meta.graduation_year.raw`, `meta.is_committed.raw`, college facet (`meta.college…`, exact key confirmed in spike) | Name, pos, club, grad year, college (on card/profile). User-submitted ("Report a Commitment" form). | Public HTML; filter is decodable/encodable JSON. | Second confirming source; sometimes earlier than TDS. |
| **School news** `gostanford.com/sports/womens-soccer/news` | Signing-day / "welcomes class of 20xx" releases with dates. | Public HTML. | Authoritative `signed` status + date. |
| **Instagram / X** (program account, its **Tagged** tab, aggregator accounts) | Announcement graphics + captions with **timestamps**; earliest signal for verbal commits. | Logged-in browser automation, local. | Recency and dates; feeds the review queue. |

### How "up to date" is achieved
1. **Daily sweeps** of TDS (team tabs for onboarded programs + global search per grad year, ~30 pages)
   and SoccerWire (per grad year, committed=1). Each record gets `firstSeen` on first appearance and
   `lastSeen` each time it is present. A new name = new commit; `announced` defaults to `firstSeen`.
2. **Disappearance detection**: a TDS record missing for 2 consecutive sweeps → flagged
   `possibly decommitted` in the review queue (TDS removes decommits silently).
3. **Social scout** (below) supplies posts with real timestamps; when you approve a post, `announced`
   becomes the post date and `announcedSource: instagram_post`.
4. **News collector** upgrades status to `signed` with the release date when a name matches a signing
   release; **roster collector** upgrades to `enrolled` when the name appears on the roster.
5. **Entity resolution** in `build.py`: key = normalized name (lowercase, accents stripped, punctuation
   removed) + gradYear; club/state used as tie-breakers; conflicts and near-matches go to the review
   queue as `merge?` items. Your decisions persist in `commitments.reviewed.json`.
6. **Confidence**: `confirmed` when ≥2 independent sources or an official release; else `single-source`;
   social-only pending your approval = `unreviewed` (not shown in the profile until approved).

---

## Social scout (X + Instagram agent, no LLM)

### Principles
- **Your machine, your throwaway accounts, low volume.** Playwright Chromium with
  `launch_persistent_context(user_data_dir="scout/browser-profile")`. First run is headed:
  `python collegedash.py scout login instagram` / `… login x` — you log in by hand once; cookies persist.
- ~40 page loads per run, one run/day at a randomized time, 3–8 s random delays, human-like scrolling.
  Stops immediately on a login wall / captcha / rate-limit page and writes a `needs-attention` flag.
- Public posts only; stores post url, text, timestamp, one thumbnail; no follower graphs, no DMs.
- ToS caveat stated plainly: automation violates X/Instagram terms; worst case is the throwaway
  account being suspended. Nothing else in the system depends on the scout.

### Watchlist (`scout/watchlist.json`)
- Per onboarded program: `x` and `instagram` handles from the registry (Stanford: `@StanfordWSoccer`,
  `stanfordwsoc`), and the program's **Instagram Tagged tab** (recruits tag the program in their own
  announcement posts — highest-yield page).
- Global aggregators (handles verified at implementation): TopDrawerSoccer, SoccerWire, ImYouthSoccer,
  Prep Soccer, ECNL Girls, Girls Academy.
- X searches: `@StanfordWSoccer committed`, `"committed" "Stanford" soccer` since last run.
- Optional: club accounts and players you add by hand.

### Per-run flow (`scout/scout.py`)
1. For each watchlist entry: open page, scroll until posts older than `state.lastSeen[account]`.
2. Extract per post: id, url, author, timestamp, text/caption, image URLs; save a thumbnail to `scout/cache/`.
3. **Keyword filter** (`scout/keywords.json`, configurable): commit, committed, commitment, #committed,
   verbal, signed, NLI, signing day, "next chapter", "welcome to the family", "class of 20xx", plus any
   program name/handle match. Non-matching posts are recorded as seen (id only) so they're never re-fetched.
4. Optional, no-LLM: if Tesseract is installed, OCR the image and run the same keyword filter on the
   OCR text (catches caption-less graphics). Off by default.
5. Matching posts → `scout/queue/<post_id>.json` with **regex hints** to prefill the review form:
   grad year (`20\d\d`), position words (GK/D/M/F/keeper/defender/midfielder/forward), club from the
   known-club list built from TDS data, college from handle/name mention.
6. Summary printed + written to `archive/refresh-state.json` (`scout.lastRun`, counts, flags).

### Review queue (dashboard, local `serve` mode only)
- "Review" tab lists pending items: thumbnail, text, link to the original post, prefilled form
  (name, pos, club, state, grad year, college, date). Buttons: **Approve** (writes record to
  `programs/<slug>/commitments.reviewed.json`), **Reject**, **Not a commit**, **Merge with…** (for
  entity-resolution conflicts), **Mark decommitted / signed**.
- `serve.py` exposes `PUT /api/curated/<slug>`, `POST /api/review/<id>` only when running locally;
  the Cloudflare copy is read-only and shows no Review tab.
- Also exposed: `possibly decommitted` and `merge?` items generated by `build.py`.

---

## Other collectors (verified sources)
| Section | Source | Status |
|---|---|---|
| Roster/staff/schedule | Stanford = **WMT Digital** site: `/sports/womens-soccer/roster`, `/roster/season/2025`, `/roster/player/<slug>`, `/schedule?season=2025`. Most other D1 = **Sidearm**. | Verified; adapters `wmt` then `sidearm`. |
| School facts | College Scorecard API `api.data.gov/ed/collegescorecard/v1/schools` | Verified; **you request a free key** (`SCORECARD_API_KEY`). |
| Climate | Open-Meteo Historical Weather API (ERA5), 1991–2020 daily → monthly normals | Verified, no key. |
| Year-by-year, titles, stadium | Wikipedia `Stanford_Cardinal_women's_soccer` all-time table | Verified. |
| RPI history 2007–2024 | Chris Henderson "RPI for D1 Women's Soccer" Google Sheets (CSV export) | Verified; one-time load. Recomputed under 2024 formula (documented). |
| RPI weekly (current season) | ncaa.com is JS-rendered; stats.ncaa.org nitty-gritty returned 403 to a plain client | **Spike**: browser headers → underlying JSON → Playwright fallback (we'll have it anyway). |

### CLI
```
python collegedash.py onboard stanford            # all public collectors for one program + build
python collegedash.py refresh [--only roster,rpi,commitments] [--all]   # scheduled workflow
python collegedash.py sweep commitments           # TDS + SoccerWire all-D1 sweep (daily in workflow)
python collegedash.py scout login instagram|x     # headed browser, manual login once
python collegedash.py scout run [--dry-run]       # daily local run → queue
python collegedash.py build | validate | serve
```

### Dashboard (`public/index.html`)
List (search/filter/sort/favorites) · Profile tabs: Overview · School & Location · Climate · History &
RPI chart · Staff · Roster (table + pos×class grid) · **Commitments** (by class year, status badges,
source chips, "new this week" highlight, per-position counts vs graduating seniors) · Schedule ·
**Review** (local only) · Compare 2–4 programs. Provenance + as-of on every section.
ECNLDash conventions (tokens, dark mode, hash routes, "Updated Xh ago"). Charts follow `dataviz` skill.

---

## Phased roadmap
**Phase 1 — Foundation + Stanford:** repo scaffold (git init, layout, `legacy/`, requirements, README),
registry + schema, `common.py`, collectors (`wmt` adapter, scorecard, climate, wikipedia, RPI history,
`commitments_tds` team tab, `commitments_soccerwire`, `news`), `build.py` with entity resolution,
`onboard stanford`, dashboard with all tabs incl. Commitments, `curated.json` template, refresh workflow
(daily commitments sweep; weekly roster/schedule in season), `wrangler.toml`.

**Phase 2 — Social scout + review:** Playwright scout (Instagram adapter incl. Tagged tab, X adapter,
searches), keyword filter + regex hints, queue, `serve.py` write endpoints, Review tab, Task Scheduler
job, optional Tesseract OCR. Global TDS sweep with firstSeen/lastSeen + decommit detection.

**Phase 3 — Spikes:** weekly RPI; SoccerWire college facet key; Sidearm adapter.

**Phase 4 — Scale to D1:** registry for all ~350 programs (Wikipedia D1 list + Scorecard matching +
platform detection + social handles), batch onboarding, completeness dashboard.

**Phase 5 — Student profile + recommendations:** local profile JSON; rule-based scorer with reasoning
strings per dimension (academic band, RPI tier vs level, **roster need** = graduating players at
position minus commits in the athlete's class, location/climate/size/cost). Reach/target/likely bands.

**Phase 6 — Application tracking:** per-program status pipeline, contact log, deadlines, recruiting
calendar reminders. Local JSON.

---

## Verification
**Phase 1**
1. `onboard stanford` runs clean; all `sources/*.json` present with `fetched_at`; `validate` passes,
   completeness ≥ 0.8.
2. Spot-check vs sources: head coach Paul Ratcliffe; staff Paul Hart, Daisy Sanchez, Pinder Nijjar;
   2026 roster ~30 players; 2025 season 21-2-2 / 9-0-1 / NCAA runner-up; 2019 champion; Cagan Stadium;
   Scorecard admission rate + enrollment; 12 climate months.
3. Commitments tab shows the 18 TDS commits (7×2026, 6×2027, 5×2028) with `single-source` badges;
   SoccerWire matches raise some to `confirmed`; no duplicate names after entity resolution.
4. Dashboard at `python -m http.server` in `public/`: all tabs render, provenance links correct, dark
   mode + deep links work, no horizontal scroll. `refresh` twice → no diff second time.

**Phase 2**
5. `scout login instagram` persists a session; `scout run --dry-run` lists ≥1 post from `stanfordwsoc`
   and its Tagged tab without touching the queue; real run writes queue items only for keyword hits.
6. Approve one queued post in the Review tab → record appears in `commitments.reviewed.json`, rebuild
   shows it with `announced` = post date and an Instagram source chip.
7. Simulate a TDS removal in a fixture → `possibly decommitted` item appears in Review.
8. Login wall fixture → scout exits with `needs-attention` and zero further requests.

## Risks
- **Account suspension** of the throwaway X/IG accounts; mitigated by low volume and human-like pacing.
  Everything else works without the scout.
- **Site markup changes** (TDS, SoccerWire, WMT, Sidearm): each collector has a fixture test and fails
  loudly rather than writing empty data.
- **Weekly RPI** access (spike). **SoccerWire college facet key** (spike; per-grad-year sweep works regardless).
- **Minors' data**: store only what public recruiting sites already publish (name, pos, club, state,
  grad year, college); no contact info, no follower data.
