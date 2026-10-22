# #79: camp pages that yield zero rows — classification and plan

Part of #79 (and #38). Offline: `origin/main` 60bc94e17 (data of 2026-10-21), the committed camps sources, the
registry, their git history and the camp fixtures. Nothing was fetched; the local HTTP cache holds no camp page.

## 1. Today's numbers (1,011 published programs)

118 have dated rows from their camp page; **893 have none** (32 of those still show camps mined from news, so 861
show no camp at all). #79's 57 of 347 was D1 only.

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

**Caveat:** camp history starts in September 2026, after the summer season, so "never a row" cannot separate a
parser gap from a page empty in autumn, except for TotalCamps, where no page of 129 has ever produced one.

## 2. The offline slice (one PR, no fetch, no camps gained)

Nothing here adds a camp. It stops 150+ programs reading as "no camps listed" when the page could not be read.

**Design: the verdict is derived in `build.py`; `collect/camps.py` is not touched.** `build_camps` already reads
every stored record, and the verdict is a pure function of fields it has (vendor, rows, final URL, `parsed`,
`fetchError`, `robotsBlocked`, `hostRefused`). Nothing is re-collected, and the next build applies it to today's data.

1. **`camp_readability(record)` in `build.py`, a pure function, written onto the profile's `camps` block** as
   `unreadable: null | {"cause": ...}`, with exactly one cause:
   - `app-shell`: vendor `totalcamps` and no dated row. The evidence is the 129/129 above, not a guess about markup.
   - `not-a-listing`: the final URL's host is a registration, store, ticketing, form or fundraising host (a fixed
     suffix list in `build.py`: Google Forms, Microsoft Forms, TouchNet, NBS store, universitytickets, agileticketing,
     givesmart, givelively, cvent, linktr.ee, jotform, eventbrite), or its path names a waiver, liability or forms
     document, or it is an image.
   - `not-html`: `parsed` false with no fetch error or robots block (a PDF or empty body; already shown as unreadable).
   - Otherwise `null`. Fetch errors, refused hosts and robots keep their existing fields and messages.
2. **Program page:** any `unreadable` cause says "The camp page could not be read automatically; open it for
   dates" (the existing wording), never "No upcoming ID camps listed".
3. **Camps index `coverage` block, counts only:** `{"programs", "withRows", "readNothingDated", "unreadable":
   {"app-shell", "not-a-listing", "not-html"}, "fetchFailed", "refusedHost", "robots", "noLink", "skipped"}`,
   computed from the published profiles in the same pass as `counts`, with each program counted once. No slugs and
   no hosts, so the index grows by a few hundred bytes. `validate` recomputes it from the profiles (as it does
   `counts`) and fails on a mismatch, and the counts must add up to `programs`.
4. **ID Camps view:** one line under the results, from `coverage`: "Camp pages for N programs could not be read
   automatically, so their camps may be missing." N is the unreadable, fetch-failed and refused counts together;
   robots and no-link are left out (we chose not to read those, or found nothing to read). Hidden when N is 0 or the
   block is absent (an older index). It names no program, so it carries no division; row text added later does.
5. **For #507:** the search box is not changed; `coverage` sits in the camps index it already loads.

**Tests (frozen, no dates, no live data), each failing on main first:**
- New `tests/camps_readable_test.py`: `camp_readability` on hand-built records for each cause. Controls, all
  `null`: a TotalCamps record with a row; an athletics page with nothing dated; a fetch error or robots block (they
  keep their own fields); a host that only contains a listed name (`notgoogle.com.example`).
- Build: a fixture set of camps records gives exact `coverage` counts (pinned on the fixture, not today's data),
  the counts add up to `programs`, and `validate` fails on a tampered `coverage`.
- Node: the program-page message per cause; the ID Camps line shown, hidden at N = 0 and without `coverage`.

**Expected on today's data:** 129 TotalCamps and about 25 wrong-link programs move from "No upcoming ID camps
listed" to "could not be read". **Camps gained: 0.**

## 3. What needs a fetch (owner's OK first; exact URLs)

- **TotalCamps (up to 129 programs):** are the sessions in the HTML or embedded JSON (#388) or browser-only?
  `https://acusoccer.totalcamps.com/`, `https://armywomenssoccer.totalcamps.com/shop/EVENT`,
  `https://arcadiawomenssoccer.totalcamps.com/`.
- **Ryzer HTTP 202 (bot check), one retry each:** `https://register.ryzer.com/camp.cfm?id=339228`,
  `https://register.ryzer.com/camp.cfm?id=331769`, `https://register.ryzer.com/camp.cfm?sport=7&id=322427`.
- **Dead or moved links,** a person sets `athletics.campsUrl` (#38): cal-state-fullerton, north-alabama,
  southeast-missouri-state, la-verne, rider, southern-new-hampshire (abcsportscamps), carthage-college, loyola-md,
  washington-college-md, wheaton-college-ma.
- **PDF flyers with real camps** (a PDF reader is a separate decision), one an ID camp on 2026-10-22:
  `https://msjlions.com/documents/2026/8/13/Oct_22nd_PUMA_ELITE_ID_Camp.pdf`,
  `https://athletics.gcc.edu/documents/2026/5/7/Summer_ID_camps_flyer.pdf`,
  `https://dxbhsrqyrr690.cloudfront.net/sidearm.nextgen.sites/sabreathletics.com/documents/2026/9/29/Elite_Prospect_Camp_Flyer.pdf`.
- **Not fixable by fetching:** 23 refused camp hosts, 62 refusing athletics sites (#73, CI IP), 22 robots.txt.

## 4. Order

1. This plan: a Reviewer approves, then the offline PR (§2), with failing tests first, full suites (Node 24),
   and before/after screenshots of the ID Camps view at 390 and 1280 px.
2. Owner decides on the TotalCamps sample fetches; if the sessions are in the HTML, a narrow parser as in #388.
3. #38's hand-check of dead and wrong links, as a registry PR.
