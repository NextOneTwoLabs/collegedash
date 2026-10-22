# Plan: #108, concurrent refresh follow-ups

Issue #108 (from the PR #105 review). Checked against origin/main `60bc94e17` (the refresh of 2026-10-21), offline:
`collect/common.py`, `collegedash.py`, `.github/workflows/refresh.yml`, `public/archive/refresh-state.json` and every
`programs/*/sources/*.json`. Author: Jueying. Status: revision 2, after Huatuo's plan review round 1. No code yet.

## Changes since review round 1
- **A recovers.** It trips only after failures have lasted 10 min, then lets one probe through every 5 min, and a
  successful probe reopens the host (REQUIRED 1). The test advances a fake clock: trip, then probe, then requests
  flow again.
- **A's outcome is explicit.** A stopped host's collectors are recorded as `skipped` with error `host stopped: <host>`,
  the same mechanism as robots skips. They don't count toward `--fail-threshold`. Each stopped host gets one
  `::warning`, not one per row (REQUIRED 2).
- **B's crawl delay.** A merged key keeps the larger Crawl-delay. `robots_report` looks it up by the merged key, the
  exact-host tests are updated, and robots allow/deny stays per exact host (REQUIRED 3).
- **C is enforced in the right place.** The deadline is checked inside the adapter's in-gate body read and raises a
  `requests.RequestException` subclass, so the host is held, `fetch()` retries, and A counts it. It covers every hop,
  including robots.txt loads and `fetch_no_redirect` (REQUIRED 4).
- **Optional notes, all taken:**
  - the stop is checked before taking the gate;
  - it says which code counts failures;
  - it says that 3b doesn't help 3a;
  - tests shrink the backoff constants and use a fake clock instead of patching `time.sleep`;
  - stop state is reset in `fresh_state`;
  - the trickle stub stops when the client disconnects;
  - the counts are corrected.

## Status of each item on main
| # | item | status | evidence |
| --- | --- | --- | --- |
| 1 | backoff after a redirect holds the wrong host | **done** | `_PoliteAdapter.send` (common.py:499-519) gates each hop by its own host and holds that gate on a retry status or network error |
| 2 | one server under two names gets two gates | **open** | `_host()` is the lower-cased netloc (common.py:309); `_gates`, `_host_delay`, `_last_request_at` key on it (413, 436, 447, 593) |
| 3a | a throttling shared host stalls the run | **open** | the only per-host stop is camps' `host_guard` (common.py:396-410) |
| 3b | backoff slept after the final failed attempt | **open** | `_fetch_locked` sleeps on the last attempt too (common.py:940, 968) |
| 3c | a slowly trickled body is not capped | **open** | `timeout=` is per socket read; the adapter reads `resp.content` inside the gate with no wall-clock cap |
| 4 | partial data can publish after a crash | **decision** | Commit is `if: always()` (refresh.yml:211), publishing is gated by build + validate, and the time budget keeps stored sources |
| 5a | backoff hold written without a lock | **done** | `_hold` runs only inside `_polite`, under the gate lock (common.py:450-452) |
| 5b | refresh-state keys in completion order | **open, cosmetic** | nothing reads the order; I propose dropping it |

## What matters today (measured offline)
- **The 2026-10-21 daily run lost nothing to the network.** It made 5,056 collector runs: 6 failed and none of those
  was a 429, 5xx or timeout. The 6 were 3 parser errors, 2 HTTP 404 (arizona-state, twice) and 1 browser-rendered
  roster. Its `lastRun` records 4,178 ok and 872 skipped; Huatuo counts 4,177 and 873. Either way, every open item
  is latent.
- **Shared hosts:** 23 of 1,986. The daily ones are SoccerWire (1,012 programs, one fetch each) and TopDrawerSoccer
  (349). A failed collector keeps its stored source: `save_source` runs only after success.
- **Worst case, 3a:** a host answering 429 to everything costs 25 + 50 + 75 = 150 s of gate holds per program, all
  on one gate. The 270-min budget then stops after about 108 programs, and about 900 programs keep yesterday's data
  for **all** their collectors.
- **3b doesn't change that arithmetic.** It frees the worker thread, but the gate hold still delays the next program.
- **Item 2:** 420 sites appear as both `www.x` and `x` (one is `:443`). None spans two programs. No IDN host.

## Plan, by impact
**A. Per-run stop for a failing host (3a), with recovery; no sleep after the last attempt (3b).**
- **Who counts.** `_fetch_locked` records a failure when a fetch gives up after retries on a retry status or a network
  error, against the host of the hop that failed. Any success through the adapter resets the count. Camps'
  `HostRefused`, `RobotsDisallowed` and other 4xx don't count.
- **Trip.** At least `STOP_FAILS` (5) consecutive failed fetches **and** at least `STOP_MIN_SECONDS` (600) since the
  first of them. A 60-150 s blip never trips, and costs what it costs today (a handful of collectors).
- **Stopped.** `fetch()` checks the state **before** taking the key lock and the gate, and the adapter re-checks
  inside the gate for redirect hops. A refused request sends nothing, waits for no gap and doesn't move `g.last`.
  It raises `HostStopped(FetchError)`.
- **Half-open.** After `STOP_COOLDOWN_SECONDS` (300), exactly one caller is let through as a probe. Success reopens
  the host; failure stops it for another cooldown.
- **Cost.** A sustained outage costs about 10 min to trip, then the programs that reach the host while it's stopped:
  at most one cooldown after it recovers. At the daily rate (about 1,000 programs in 34 min) that's up to about 150
  SoccerWire collectors, against about 900 programs' whole refresh today.
- **Outcome.** The collector is `skipped`, with error `host stopped: <host>`, so it's outside the failure share.
  There's one `::warning` per stopped host with its count and stop/reopen times, and `lastRun.hostsStopped`.
  `freshness.yml` still catches TDS or SoccerWire data that goes stale for days.
- **3b.** After the final attempt, `_fetch_locked` raises without sleeping.
- **Tests that fail on main** (`tests/refresh_politeness_test.py`; `fresh_state` also shrinks `BACKOFF_429_SECONDS`
  and resets stop state; the stop's clock is injectable):
  - (a) 20 fetches to an always-429 stub, with the fake clock past `STOP_MIN_SECONDS`: main sends 60 requests; the
    branch sends 15 and then refuses with nothing sent;
  - (b) advance past the cooldown: one probe goes out, the stub now answers 200, and later fetches flow;
  - (c) the probe fails: stopped again, with exactly one probe sent;
  - (d) fetch()'s own backoff waits, counted through a hook rather than a patched `time.sleep`: 2 on the branch,
    3 on main;
  - (e) the run summary records `skipped`/`host stopped`, a failure share of 0, and one warning per host.
- **Guards (pass on main):** a 2-minute blip never trips; another host's gate is unaffected; camps refusals and
  robots denials don't count.
- **Risk:** the trip and cooldown numbers are judgement. They're env-configurable and named in the warning.

**B. One gate per server: `_gate_key(host)`** (lower-case, strip a leading `www.`, drop `:443`/`:80`, IDNA-encode).
- It's used for `_gates`, `_last_request_at`, `_host_delay` and A's stop state.
- `_use_crawl_delay` stores `max(existing, new)`, so one origin can never lower the delay the other asked for.
- `robots_report` (common.py:828) looks delays up by the key.
- The robots verdict caches (`_robots`, `_robots_state`, `_robots_delay`, `_robots_check`'s host) stay per exact host
  (RFC 9309 scopes robots.txt to the authority).
- **Tests that fail on main:**
  - `www.x.test` then `x.test:443` waits the gap;
  - a hold on one name delays the other;
  - Crawl-delays of 4 s and 9 s on the two names leave 9 s whichever is read last.
- **Tests updated to the key:** `robots_ua_test.py:67,160-179` and `refresh_schedule_test.py:247`.
- **Risk:** stricter spacing for those 420 sites, only when they switch names.

**C. A whole-hop deadline, `max(3 × timeout, 120 s)`.**
- It's enforced in `_PoliteAdapter.send`'s in-gate body read, by reading `resp.raw` in chunks against a monotonic
  deadline. `fetch()` never passes `stream=True`, so the body is always read inside the gate.
- Past the deadline it raises `RequestDeadline(requests.exceptions.Timeout)`. The adapter then holds the host,
  `fetch()` retries, and A counts it.
- The cap is per hop, and covers robots.txt loads and `fetch_no_redirect`.
- **First:** for one or two runs, log each host's longest fetch, to confirm 180 s is far above anything legitimate
  (8 KB/s for a 1.5 MB page).
- **Test that fails on main:** a stub that trickles 1 byte every 0.5 s and stops when the client disconnects, with
  `timeout=2` and the deadline set to 3 s. Main reads to the end; the branch raises by about 3 s and holds the host.
- **Risk:** a legitimately slow, very large page is cut off.

**D. Item 4:** owner decision. I recommend keeping today's behaviour and closing the item (Huatuo agrees). The README
side is #89.

**Order.** A, B, C: one PR each, "Part of #108". Each runs `tests/refresh_politeness_test.py`, the robots suites and
the full suites (`run-tests`). The issue closes after C and the owner's ruling on D.
