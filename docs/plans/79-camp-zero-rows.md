# #79: camp pages that yield zero rows — classification and plan

Part of #79 (and #38's per-host link work). Offline only: `origin/main` 60bc94e17 (data refresh 2026-10-21), the
committed `programs/*/sources/camps.json`, `public/data/registry.json`, git history of those files, and the camp
fixtures. Nothing was fetched. The local HTTP cache holds no camp page.

## 1. Today's numbers (1,011 published programs)

- 118 have dated rows from their camp page; **893 have none**. Of the 893, 32 still show camps mined from news
  (`newsCamps`, published by `build.py`), so 861 show a visitor no camp at all.
- #79 counted 57 of 347 when only D1 was published; D2 and D3 are now published, so every bucket is larger.

| Stored outcome | Programs | Cause | Fixable without a fetch? |
|---|---|---|---|
| No camps source: athletics site skipped (62 refuse our bot, 4 TLS, 2 PrestoSports, 1 unreachable) | 69 | blocked | no (#73, CI IP) |
| No camp link found on the roster page | 129 | missing link | no: needs a hand-check per site (#38) |
| robots.txt disallows the camp page | 22 | blocked, correct | leave as is |
| Camp host refused us (HTTP 403, recorded, not re-requested) | 23 | blocked | no (#73) |
| Fetch error: 3 dead `abcsportscamps.com`, 4 moved pages (404, 1 dead `cvent.me`), 3 Ryzer HTTP 202, 1 HTTP 401, 2 HTTP 5xx, 1 connection | 14 | dead/moved link, bot check | no |
| Not HTML: 11 PDFs, 2 images (5 of the PDFs are waivers, forms, or another team's flyer) | 13 | wrong link / unreadable format | labels only (§2) |
| Page read, nothing dated (split below) | 623 | | |

**The 623 pages read with no dated row:**

| Split | Pages | Evidence |
|---|---|---|
| TotalCamps (`*.totalcamps.com` and 9 custom domains) | 129 | **0 rows ever** (every sampled revision since collection began); 120 have no `<title>` in the first 20 KB, the shape of a JavaScript app shell |
| Ryzer camp site, never a row since September | 157 | 57 other Ryzer sites do yield rows, so the parser reads Ryzer; these may simply list nothing for 2027 yet |
| Athletics-site camps page, nothing dated for soccer | 145 | mostly all-sport "Camps & Clinics" hubs |
| Other third-party camp site, nothing dated | 96 | |
| Had rows earlier, none now | 40 | the page dropped past sessions: genuinely nothing listed today |
| Third-party page with no `<title>` | 28 | possibly JavaScript-rendered; unverified |
| Wrong link: registration, store, ticketing or form host (Google Forms, TouchNet, NBS store, …) | 13 | host pattern |
| Wrong link: another sport, men's only, or an all-sport page #38 names | 12 | title or #38 |
| Dead vendor `info.abcsportscamps.com` | 3 | #79 / #38 |

**Caveat on "genuinely none":** camp history starts in September 2026, after the summer season, and D2/D3 later still.
So "never a row" cannot separate a parser gap from a page that lists nothing in autumn, except for TotalCamps, where
no page of 129 has ever produced one.

## 2. The offline slice (one PR, no fetch, no camps gained)

Nothing here adds a camp. It stops 150+ programs from reading as "no camps listed" when we could not read the page,
which is #79's ask ("never let a fetch failure read as an empty result") and what #507's search needs to say honestly.

1. **Unreadable verdicts in `collect/camps.py` (stored as `readable` on the camps record):**
   - `app-shell`: vendor `totalcamps` and no dated row. Evidence is the 129/129 above, not a guess about markup.
   - `not-a-listing`: the link's host is a registration, store, ticketing, form or fundraising host (a fixed list,
     extending `REGISTER_PORTAL_RE`), or a document path naming a waiver, liability or forms file, or an image.
   - Otherwise `read` (today's behaviour).
2. **Program page:** `app-shell` and `not-a-listing` say "The camp page could not be read automatically; open it
   for dates" (the existing `unreadable` wording), never "No upcoming ID camps listed".
3. **Camps index `coverage` block (`build.py`):** counts per outcome (rows, read-nothing-dated, unreadable, fetch
   failed, refused, robots, no link, skipped). The ID Camps view adds one line, "Camp pages for N programs could not
   be read, so their camps may be missing", and #507 can use the same counts. Counts only, no slugs on the page.

**Tests (frozen, no dates, no live data):**
- New `tests/camps_readable_test.py`: hand-built camps records and URLs (placeholder hosts, plus host suffixes copied
  from the table above) for each verdict, and controls: a TotalCamps page with a row stays `read`, a Google Form is
  `not-a-listing`, an athletics page is `read`.
- Build: a fixture set of camps records gives exact `coverage` counts (pinned on the fixture, not on today's data).
- Node: the program page and ID Camps view messages for each verdict, from a fixture index.
- All of them fail on main.

**Expected effect on today's data:** 129 TotalCamps and about 25 wrong-link programs move from "No upcoming ID camps
listed" to "could not be read". **Camps gained: 0.**

## 3. What needs a fetch (owner's OK first; exact URLs)

- **TotalCamps, the largest possible gain (up to 129 programs):** one page each from 3 sites, to see whether the
  sessions are in the HTML or embedded JSON (as the legacy Sidearm roster was, #388) or need a browser:
  `https://acusoccer.totalcamps.com/`, `https://armywomenssoccer.totalcamps.com/shop/EVENT`,
  `https://arcadiawomenssoccer.totalcamps.com/`.
- **Ryzer HTTP 202 (bot check), one retry each:** `https://register.ryzer.com/camp.cfm?id=339228`,
  `https://register.ryzer.com/camp.cfm?id=331769`, `https://register.ryzer.com/camp.cfm?sport=7&id=322427`.
- **Ryzer sites with nothing dated:** none until late spring; re-measure then (no fetch now).
- **Dead or moved links:** need a person to find the new page and set `athletics.campsUrl` (#38), not a script:
  cal-state-fullerton, north-alabama, southeast-missouri-state (`abcsportscamps.com`); la-verne, rider,
  southern-new-hampshire (`info.abcsportscamps.com`); carthage-college, loyola-md, washington-college-md,
  wheaton-college-ma.
- **PDF flyers with real camps** (a PDF reader is a separate decision):
  `https://msjlions.com/documents/2026/8/13/Oct_22nd_PUMA_ELITE_ID_Camp.pdf` (an ID camp dated 2026-10-22),
  `https://athletics.gcc.edu/documents/2026/5/7/Summer_ID_camps_flyer.pdf`,
  `https://dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/sabreathletics.com/documents/2026/9/29/Elite_Prospect_Camp_Flyer.pdf`.
- **Not fixable by fetching:** 23 refused camp hosts and 62 refusing athletics sites (#73, CI IP reputation),
  22 robots.txt.

## 4. Order

1. This plan: a Reviewer approves, then the offline PR (§2), with failing tests first.
2. Owner decides on the 3 TotalCamps sample fetches. If the sessions are in the HTML, a narrow TotalCamps parser
   follows as in #388: fixed signature, allowlisted fields, before/after over every stored TotalCamps record.
3. #38's hand-check of dead and wrong links, as a registry PR.
