# robots.txt in the collectors (issue #101)

Every request the collectors make goes through one hook, `_PoliteAdapter.send` in `collect/common.py`: the first
request and every redirect hop, keyed by the host each hop contacts. Since #101 that hook also asks the host's
robots.txt, evaluated as our User-Agent token `CollegeDashBot` (falling back to the `*` group). A cache hit makes no
request and is not checked. The robots.txt request itself is exempt, and each host's file is fetched once per run.

## Modes: `COLLEGEDASH_ROBOTS`

| Mode | What happens | Where |
| --- | --- | --- |
| `off` | no check in the hook (the code default; local runs) | |
| `report` | **nothing is blocked and no delay changes.** Each request robots.txt would disallow is counted per collector, per call site (`athletics.bio`, `athletics.historyRoster`, `athletics.historySchedule`, `athletics.coachesPage`, `athletics.coachBio`, `camps.page`, `camps.newsArticle`, `camps.roster`, `news.page`, `news.rss`, `rpi.history`, or the collector's name) and per host | `refresh.yml` since #101 PR A |
| `enforce` | a disallowed request raises `RobotsDisallowed` before anything is sent, and every host's `Crawl-delay` applies | after the owner's bar below |

The report is written to `public/archive/refresh-state.json` under `robots` (and the run's step summary). It holds
counts, hosts and paths only, never a query string or page content:
- `wouldBlock`: total, `byCollector`, `bySite`, `topHosts`, `samplePaths`;
- `robotsTxt`: how many hosts answered `ok`, `4xx`, `5xx`, or were `unreachable`;
- `unavailableHosts`: the 5xx and unreachable hosts, with how many of their pages then loaded or failed;
- `crawlDelay`: the values asked for, and how many are applied today versus only recorded;
- `projection`: this run's minutes and an estimate of an enforced run (every `Crawl-delay` applied, capped at 30 s).

## Owner decision 1 = B: a broken robots.txt is allowed by the hook, in report mode only

**When a host's robots.txt cannot be reached, or answers a server error (5xx), the new hook allows the request, and
counts it.** This **departs from RFC 9309**, which says to assume complete disallow in that case. The owner chose it
(2026-09-25) so a host with a broken robots.txt does not drop out of the collection, and the report counts these hosts,
and whether their pages then loaded, so the choice can be revisited with numbers. How enforce mode treats these hosts
is decided with PR B.

**The existing explicit checks stay strict** (the owner, 2026-09-26): `robots_allowed()`, which off-site camp hosts, THE,
`site_colors` and the registry builder call, still returns False for a host whose robots.txt is unreachable or 5xx, as
before #101 and as the RFC says. A 4xx robots.txt (no file) is allowed by both, as before and as the RFC says.

## Crawl-delay in report mode

Report mode changes no spacing. A host checked by an explicit `robots_allowed()` call keeps its `Crawl-delay`, as
before #101, including when the hook loaded the host first. A host only the hook has seen has its delay recorded, not
applied. A non-integer delay (`Crawl-delay: 2.5`), which `urllib.robotparser` drops, is read from the raw lines.

## A block never erases stored data

Under `enforce`, a blocked page is a skip, not a failure, and the program keeps what is stored, matched by a stable
key: a player's bio and club by `bioUrl`, a past-season roster or schedule by its year, the coaches-page staff, and the
camp page's camps by `campsUrl`. A collector with no catch for it (news, TopDrawerSoccer, SoccerWire, Scorecard,
climate, Wikipedia, the main roster page) is recorded `skipped`, reason `robots: <call site>`, and its source file is
not rewritten.

## The time budget

`refresh --time-budget-minutes N` (`refresh.yml`: 270 via `COLLEGEDASH_TIME_BUDGET_MINUTES`) starts no new program
once N minutes have passed. Programs in flight finish; the rest are `skipped`, reason `time budget`, never failed.
Their sources and their refresh-state entries are left as they were, and `lastRun.timeBudget` names them. The collector
step is killed at 300 minutes and the job at 350; the commit step is `if: always()`, so a kill still commits what was
collected.

## Rollout

1. **PR A (this):** report mode, the budget and the timeouts. Nothing is blocked.
2. **The owner's bar for enforcing (decision 5):** at least 3 daily runs and 1 weekly run in report mode; no collector
   losing more than 2% of its programs to blocks unless the owner has seen the list; no stored-data loss; a projected
   run under 4 hours.
3. **PR B:** `COLLEGEDASH_ROBOTS: enforce` in `refresh.yml`, with a `::error` when a collector's blocked share jumps
   over 2%. **Rollback** is that one line back to `report`, taking effect on the next run.
