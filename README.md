# CollegeDash — Women's Soccer College Research

A research dashboard for a high-school athlete evaluating NCAA Division I women's soccer
programs. Every program gets one **profile** assembled from many public sources — school facts,
climate, program history and yearly RPI, staff, roster, schedule, news and **commitments** — plus
your own notes. The profile is a set of JSON files in git, and the dashboard is a single static
page that reads them, so it hosts for free and works offline.

Later phases add a student profile with personalised recommendations, a social-media scout for
commitment announcements, and application tracking (see `PLAN.md`).

## Run it

```bash
pip install -r requirements.txt
python collegedash.py serve            # http://127.0.0.1:8000/
```

Any static server over `public/` also works (`cd public && python -m http.server`), read-only.

The FAQ page (`#/faq`) explains the sources, that nothing is verified by hand, and how to send feedback;
the address is the `FEEDBACK_EMAIL` constant in `public/index.html`.

## Add or refresh a program

```bash
python collegedash.py onboard stanford          # every collector for one program, then build
python collegedash.py refresh                   # refresh all onboarded programs (what CI runs)
python collegedash.py refresh --only tds,news   # a subset: scorecard climate wikipedia athletics tds soccerwire news rpi
python collegedash.py refresh --failed --dry-run # re-run only collectors whose last run failed (drop --dry-run to run)
python tools/roster_check.py                    # offline: parse every cached roster page, report per-program outcome
python collegedash.py build                     # re-merge sources -> public/data (after editing curated.json)
python collegedash.py validate                  # schema + completeness report
python collegedash.py rpi history --force       # re-download the 2007-2024 RPI archive
python collegedash.py sweep tds --years 2027    # all-D1 commitments sweep (phase 2 daily job)
```

To onboard a new program add it to `public/data/registry.json` (ids for College Scorecard,
TopDrawerSoccer, Wikipedia; athletics site platform; social handles) and run `onboard <slug>`.
Set `SCORECARD_API_KEY` (free at https://api.data.gov/signup/) or the collector falls back to
the rate-limited `DEMO_KEY`.

## Layout

| Path | What it is |
|---|---|
| `public/` | Everything the site serves — Cloudflare output dir and local server root |
| `public/index.html` | The dashboard (vanilla JS, no build step) |
| `public/data/registry.json` | Program registry + every source URL template |
| `public/data/programs/<slug>.json` | Built profile per program; `index.json` = list rows |
| `public/data/rpi/<year>.json` | End-of-season RPI 2007–2024 (all D1); `current.json` + `weekly/` = NCAA weekly |
| `public/data/commitments/index.json` | Every resolved commitment across programs |
| `programs/<slug>/curated.json` | Optional hand-written notes and overrides (edit by hand or `PUT /api/curated/<slug>`) — collectors never write here |
| `programs/<slug>/commitments.reviewed.json` | Your decisions: approved social records, merges, status overrides |
| `programs/<slug>/sources/*.json` | Raw collector output with provenance (`collector`, `sourceUrl`, `fetchedAt`) |
| `data/commitments/` | All-D1 commitment sweeps with firstSeen/lastSeen (phase 2) |
| `collect/` | Collectors; `adapters/` = athletics-site platforms (`sidearm`, `wmt`) |
| `tools/` | Maintenance scripts: offline roster parser check, athletics URL probe, cache compaction |
| `build.py` | Merges sources + curated + reviewed into `public/data`, resolves commitment identities |
| `serve.py` | Local server with `/api/curated/<slug>` and `/api/review/<slug>` write endpoints |
| `scout/` | Social-media scout (phase 2): watchlist, keyword filter, review queue |
| `legacy/` | The original hand-written prototype, kept for reference only (data unverified) |
| `.github/workflows/refresh.yml` | Daily refresh (commitments, news, RPI); full refresh on Mondays |

## Sources

| Data | Source | Notes |
|---|---|---|
| Roster, staff, bios, schedule, news | Official athletics site | Sidearm (two generations) and WMT Digital (four roster themes); a few legacy sites render rosters in the browser and are skipped (`athletics.rosterRequiresBrowser`) |
| School facts | College Scorecard API | admission rate, test bands, size, cost, outcomes |
| Climate | NOAA NCEI 1991–2020 U.S. Climate Normals (monthly) | nearest airport/coop station to campus; no key, no quota |
| History, honours | Wikipedia team article | infobox + year-by-year table |
| RPI 2007–2024 | Chris Henderson, *RPI for Division I Women's Soccer* | end-of-season, recomputed under the 2024 formula (XLSX export; the CSV export loses formula values for 2021–24) |
| RPI weekly | NCAA.com RPI page | only the latest week is published; each refresh archives a snapshot |
| Commitments | TopDrawerSoccer team tab; SoccerWire directory (Elasticsearch proxy) | no dates on either; SoccerWire profile date is an approximation |

## Commitments: how "up to date" works

- **TopDrawerSoccer** team tab and **SoccerWire** are pulled daily. Records carry `firstSeen`/`lastSeen`;
  one that vanishes gets `missingSince` and the profile flags `possibly-decommitted`.
- The two are merged by normalised name + grad year, with nickname tolerance ("Ale" ↔ "Alessandra").
  A name variant is kept as an alias. Manual merges live in `commitments.reviewed.json`.
- `confidence` is **confirmed** with two independent sources, an official release, or a roster
  appearance; else **single-source**. `status` is verbal → signed (press release) → enrolled (on roster).
- `announced` is set only from real dates (press release, approved social post). Approximations
  (SoccerWire profile creation, first seen) are shown as ≈ and never presented as announcement dates.
- Phase 2 adds the social scout: a local Playwright browser watches program/aggregator Instagram
  and X accounts, keyword-filters posts, and queues them for your approval — no LLM involved.

## Deploying

The site is a Cloudflare Worker serving static assets (`wrangler.toml` at the repo root:
`[assets] directory = "./public"`, plus a ten-line `worker.js` that only redirects the `workers.dev`
hostname). It is built by Cloudflare's Git integration on the **NextOneTwoLabs** Cloudflare account:
repository `NextOneTwoLabs/collegedash`, branch `main`, build command empty, deploy command
`npx wrangler deploy`. Pushing to `main` — including the scheduled data commits from
`.github/workflows/refresh.yml` — redeploys.

- **Canonical URL:** `https://college.nextonetwo.com` — a custom domain attached to the Worker
  (Settings → Domains & Routes; the `nextonetwo.com` zone lives in the same account, so DNS and the
  certificate are managed automatically).
- `https://collegedash.nextonetwolabs.workers.dev` permanently redirects there (`worker.js` runs ahead of
  the assets for `/` only, so a page view costs one Worker request and every other file is a free static
  asset). Deep-link `#` fragments survive the redirect.
- The daily refresh needs no secret; add `SCORECARD_API_KEY` under the repo's Actions secrets to lift the
  DEMO_KEY rate limit on school-facts refreshes.
