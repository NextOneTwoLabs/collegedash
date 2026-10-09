# robots.txt in the collectors (issue #101)

Every request the collectors make goes through one hook, `_PoliteAdapter.send` in `collect/common.py`: the first
request and every redirect hop, keyed by the host each hop contacts. Since #101 that hook also asks the host's
robots.txt, evaluated as our User-Agent token `CollegeDashBot` (falling back to the `*` groups) by the RFC 9309 resolver
in `collect/robots.py` (issue #87; see [Matching](#matching-rfc-9309-issue-87)). A cache hit makes no request and is
not checked. The robots.txt request itself is exempt, and each host's file is fetched once per run.

## Modes: `COLLEGEDASH_ROBOTS`

| Mode | What happens | Where |
| --- | --- | --- |
| `off` | no check in the hook (the code default; local runs) | |
| `report` | **nothing is blocked and no delay changes.** Each request robots.txt would disallow is counted per collector, per call site (`athletics.bio`, `athletics.historyRoster`, `athletics.historySchedule`, `athletics.coachesPage`, `athletics.staffDirectoryProbe`, `athletics.coachBio`, `camps.page`, `camps.newsArticle`, `camps.roster`, `news.page`, `news.rss`, `rpi.history`, or the collector's name) and per host | `refresh.yml` since #101 PR A |
| `enforce` | a disallowed request raises `RobotsDisallowed` before anything is sent, and every host's `Crawl-delay` applies | after the owner's bar below |

The report is written to `public/archive/refresh-state.json` under `robots` (and the run's step summary). It holds
counts, hosts and paths only, never a query string or page content:
- `wouldBlock`: total, `byCollector`, `bySite`, `topHosts`, `samplePaths`;
- `robotsTxt`: how many hosts answered `ok`, `4xx`, `5xx`, or were `unreachable`;
- `unavailableHosts`: the 5xx and unreachable hosts, with how many of their pages then loaded or failed;
- `crawlDelay`: the values asked for, and how many are applied today versus only recorded;
- `projection`: this run's minutes and an estimate of an enforced run (every `Crawl-delay` applied, capped at 30 s);
- `resolverErrors`: requests the hook could not get a verdict for (the step budget ran out): allowed in report mode,
  denied in enforce mode; `explicitResolverErrors`: the same in an explicit `robots_allowed()` check, always denied;
- `truncatedHosts` (a robots.txt over 500 KiB) and `truncatedRules` (a pattern over 4096 octets);
- `resolverDiff` (#87, for 3 scheduled runs, then removed): verdicts the RFC 9309 resolver gives differently from
  `urllib.robotparser` on the same robots.txt, from the hook and from the explicit checks alike, each host and path
  counted once per run. `newlyAllowed`, `newlyBlocked`, `comparisonErrors`, `topHosts` (at most 20) and `samplePaths` (at most 50,
  each with its call site and whether the explicit check or the hook saw it). It is published at `/api/v1/status`
  with the rest of `refresh-state.json` (owner decision 9).

## Owner decision 1 = B: a broken robots.txt is allowed by the hook, in report mode only

**When a host's robots.txt cannot be reached, or answers a server error (5xx), the new hook allows the request, and
counts it.** This **departs from RFC 9309**, which says to assume complete disallow in that case. The owner chose it
(2026-09-25) so a host with a broken robots.txt does not drop out of the collection, and the report counts these hosts,
and whether their pages then loaded, so the choice can be revisited with numbers. How enforce mode treats these hosts
is decided with PR B.

**The existing explicit checks stay strict** (the owner, 2026-09-26): `robots_allowed()` still returns False for a
host whose robots.txt is unreachable or 5xx, as before #101 and as the RFC says. A 4xx robots.txt (no file) is allowed by
both, as before and as the RFC says. Its callers, which block for real in every mode:

| Caller | What a deny does |
| --- | --- |
| `collect/camps.py` `fetch_checked` (an off-site camp page, and a redirect onto another host) | `robotsBlocked` and `robotsDisallowed`: the camps stored for the same `campsUrl` are kept (#87, owner decision 8), whatever the reason for the deny, including a 5xx, unreachable or offline robots.txt |
| `collect/wikipedia.py` | raises `FetchError` |
| `collect/registry_builder.py` | raises `FetchError` |
| `collect/the_rank.py` | raises `FetchError` |
| `collect/site_colors.py` | `skipped: robots` |
| `collect/staff_dir_probe.py` | skipped |

## Crawl-delay in report mode

Report mode changes no spacing. A host checked by an explicit `robots_allowed()` call keeps its `Crawl-delay`, as
before #101, including when the hook loaded the host first. A host only the hook has seen has its delay recorded, not
applied. The delay comes from the same merged group as the rules, as a float (`Crawl-delay: 2.5` is 2.5 s); the
largest value across the merged groups wins.

## Matching: RFC 9309 (issue #87)

`collect/robots.py` decides every verdict; its module docstring is the full spec, approved on #87 (revisions 2, 3 and
3.1, owner decisions of 2026-10-09), and `tests/robots_rfc9309_test.py` is its matrix. In short:

- **Groups.** One or more `User-agent` lines and the rules after them. Only an `Allow` or `Disallow` line closes a run
  of `User-agent` lines; `Crawl-delay`, `Sitemap`, unknown lines and blank lines do not (decision 12). Rules before any
  `User-agent` line are ignored. So a `*` group holding only `Crawl-delay` or `Sitemap`, followed by another bot's group,
  merges with it: `User-agent: *` / `Crawl-delay: 10` / `User-agent: AhrefsBot` / `Disallow: /` disallows everything
  for us too (matrix row X9; decision 12 awaits one more owner confirmation, and X9 flips if it is reversed).
- **Which group.** A `User-agent` value names us when its leading `[A-Za-z_-]+` token is `CollegeDashBot`, in any case
  (`CollegeDashBot/1.0` does; `bot`, `*bot` and `CollegeDash` do not). Every group naming us is merged; failing that,
  every `*` group; failing that, everything is allowed.
- **Rules.** `*` matches anything; `$` anchors only at the end of a pattern; a pattern without a leading `/` gets one
  (decision 10); an empty rule is ignored. The longest matching pattern wins, measured in normalised octets; `Allow`
  wins a tie; no match allows. `/robots.txt` is always allowed.
- **What is matched.** The URL's path (with any `;params`), plus `?` and the query when the URL has a `?`; never the
  fragment. Pattern and path are percent-normalised alike: unsafe octets encoded, `%xx` uppercased, unreserved
  characters decoded, `%2F` kept distinct from `/`. `%2A` and `%24` in a pattern are a literal `*` and `$`.
- **Bounds.** A robots.txt over 500 KiB is read up to the last line break before the limit, and rules past it are not
  seen (decision 7). A pattern over 4096 octets fails closed: a `Disallow` keeps its first 4096 (moved back before a
  split `%xx`), an `Allow` is dropped. One verdict may take at most 2,000,000 matcher steps (decision 11); past that, an explicit check
  denies and the hook counts a `resolverErrors`, allowing in report mode and denying in enforce mode. The matcher is
  linear and builds no regular expression from a robots.txt.

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
