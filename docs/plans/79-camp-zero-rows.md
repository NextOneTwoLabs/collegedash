# #79: camp pages that yield zero rows — classification and plan

Part of #79 (and #38). Offline: `origin/main` 60bc94e17 (data of 2026-10-21), committed sources and their history.

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

**The 623 read with nothing dated:** 129 TotalCamps (**no row ever**, 120 with no `<title>`: a JavaScript app
shell); 157 Ryzer (57 other Ryzer sites yield rows, so these may list nothing for 2027 yet); 145 athletics-site camp
pages (mostly all-sport hubs); 96 other camp sites; 40 that had rows earlier and dropped past sessions; 28 third-party
pages with no `<title>` (possibly JavaScript, unverified); 25 wrong links (registration/store/form hosts, another sport,
#38's list); 3 on dead `info.abcsportscamps.com`. **Caveat:** camp history starts after the summer season, so "never
a row" separates a parser gap from an empty autumn page only for TotalCamps.

## 2. The offline slice (one PR, no fetch, no camps gained)

**Design: the verdict is derived in `build.py`; `collect/camps.py` is not touched.** `build_camps` already reads
every stored record, and the verdict is a pure function of fields it has (vendor, rows, final URL, `parsed`,
`fetchError`, `robotsBlocked`, `hostRefused`). Nothing is re-collected, and the next build applies it to today's data.

1. **`camp_readability(record)` in `build.py`, a pure function, written onto the profile's `camps` block** as
   `unreadable: null | {"cause": ...}`. **It is `null` whenever the record has a dated row** (njit's Google Form and
   plymouth-state's NBS store page show camps today), when there is no camp link, and when the record has a
   `fetchError`, `robotsBlocked` or `hostRefused` (they keep their own fields and messages). Otherwise, in this order:
   - `not-a-listing`: the final URL's host is, or ends in `.` plus, one of `docs.google.com forms.gle
     forms.cloud.microsoft forms.office.com touchnet.net touchnet.com nbsstore.net universitytickets.com
     agileticketing.net givesmart.com givelively.org cvent.me cvent.com linktr.ee jotform.com eventbrite.com
     formstack.com`; or its path (for Sidearm's `images.sidearmdev.com/convert?url=` proxy, the inner URL's path)
     matches `(?:^|[/_.\-])(?:waivers?|liability|forms?)(?=[/_.\-]|$)` (case-insensitive, whole word between
     separators, so `information-camps-index` and `uniforms` do not match) or ends in an image extension
     (`jpg jpeg png gif webp heic`).
   - `app-shell`: the stored record's `vendor` is `totalcamps` (set by the collector from the host and markup, so it
     covers the 9 custom domains). The evidence is 129/129 with no row in any of 3,721 revisions (Bianque, round 1).
   - `not-html`: `parsed` is false.
2. **Program page:** any `unreadable` cause says "The camp page could not be read automatically; open it for
   dates" (the existing wording), never "No upcoming ID camps listed".
3. **Camps index `coverage` block, counts only:** `{"programs", "withRows", "readNothingDated", "unreadable":
   {"app-shell", "not-a-listing", "not-html"}, "fetchFailed", "refusedHost", "robots", "noLink", "skipped"}`. One
   function, `camp_coverage(profiles)`, puts each program in exactly one bucket in this order: no camps record
   (skipped), no link, robots, refused host, fetch error, unreadable cause, with rows, read nothing dated. Build and
   `validate` both call it, so the sum equals `programs` by construction; `validate` compares the index's block with a
   fresh computation, as it does `counts`. No slugs or hosts.
4. **ID Camps view:** one line under the results, from `coverage`: "Camp pages for N programs could not be read
   automatically, so their camps may be missing." N is the unreadable, fetch-failed and refused counts together;
   robots and no-link are left out (we chose not to read those, or found nothing to read). Hidden when N is 0 or the
   block is absent (an older index). It names no program, so it carries no division; row text added later does.
5. **For #507:** the search box is not changed; `coverage` sits in the camps index it already loads.

**Tests (frozen, no dates, no live data), each failing on main first:**
- New `tests/camps_readable_test.py`: `camp_readability` on hand-built records shaped like these real ones:
  - caught: `aurora` `/sports/2019/3/12/sport-camp-liability-form-waiver.aspx`, `west-alabama`
    `UWA_Liability_Waiver_Camps.pdf`, `st-norbert-college` `..._ID_Camp_Waiver_2026.pdf`, `west-texas-am`
    `Camp_Forms.pdf`, `wisconsin-stevens-point` `Camp_Health_Form_Combined.pdf`, `rose-hulman`
    `..._Prospect_Camp_Form.docx`, a Google Form, a TouchNet store, an image through the Sidearm proxy, TotalCamps;
  - `null` (controls): a Google Forms page and an NBS store page **with a dated row**; `/sports/2020/5/5/
    information-camps-index.aspx` and `information-camps-clinics-index` (with and without rows); a path with
    `uniforms`; a host that only contains a listed name (`docs.google.com.example`); a TotalCamps record with a row;
    an athletics page with nothing dated; a fetch error, a refused host, a robots block.
- Build: a fixture set of camps records gives exact `coverage` counts (pinned on the fixture, not today's data),
  the counts add up to `programs`, and `validate` fails on a tampered `coverage`.
- Node: the program-page message per cause; the ID Camps line shown, hidden at N = 0 and without `coverage`.

**Expected on today's data** (measured with a prototype of exactly these rules over the committed sources): 129
`app-shell` and 17 `not-a-listing` pages that were read move from "No upcoming ID camps listed" to "could not be read";
5 more `not-a-listing` and 8 `not-html` were already shown as unreadable and now carry a cause. No program with rows
changes. **Camps gained: 0.**

## 3. What needs a fetch (owner's OK first; exact URLs)

- **TotalCamps (up to 129 programs), HTML/JSON or browser-only?** `https://acusoccer.totalcamps.com/`,
  `https://armywomenssoccer.totalcamps.com/shop/EVENT`, `https://arcadiawomenssoccer.totalcamps.com/`.
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
