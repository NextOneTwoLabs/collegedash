# Plan: #108, concurrent refresh follow-ups

Issue #108 (from the PR #105 review). Checked against origin/main `60bc94e17` (the refresh of 2026-10-21), offline:
`collect/common.py`, `.github/workflows/refresh.yml`, `public/archive/refresh-state.json` and every
`programs/*/sources/*.json`. Author: Jueying. Status: plan for review; no code.

## Status of each item on main
| # | item | status | evidence |
| --- | --- | --- | --- |
| 1 | backoff after a redirect holds the wrong host | **done** | `_PoliteAdapter.send` (common.py:499-519) runs every hop through `_polite(request.url)` and holds that hop's gate on a retry status or network error |
| 2 | one server under two names gets two gates | **open** | `_gate(_host(url))` keys on the lower-cased netloc (common.py:309, 413); `www.`/bare and `:443` are separate gates, and so is `_host_delay` (Crawl-delay) |
| 3a | a throttling shared host stalls the run | **open** | no per-host stop outside camps' `host_guard` (common.py:404, used only by camps) |
| 3b | backoff slept after the final failed attempt | **open** | `_fetch_locked` sleeps `_backoff_seconds` and `continue`s on the last attempt too (common.py ~938-970) |
| 3c | a slowly trickled body is not capped | **open** | `requests` `timeout=` is per socket read, not per request; nothing caps a whole response |
| 4 | partial data can publish after a crash | **decision, not a bug** | "Commit changed data" is `if: always()` (refresh.yml:211), but publishing is gated by build + validate (#82) and #101's `--time-budget-minutes 270` keeps unstarted programs' stored sources; line 563's annotation states it |
| 5a | backoff hold written without a lock | **done** | `_hold` is "call only inside _polite" (common.py ~446), under the gate lock |
| 5b | refresh-state keys in completion order | **open, cosmetic** | no reader depends on the order; propose to drop it |

## What matters for completeness today (measured offline)
- **The last daily run (2026-10-21) lost nothing to the network.** It made 5,056 collector runs: 4,178 ok, 872 skipped by
  schedule, 6 failed (four parser or 404 errors, one browser-rendered roster, no 429/5xx/timeout). It ran 15:47-16:21Z, 34 min.
  So every open item is **latent**: it costs nothing until a host misbehaves, and then it can cost a whole day.
- **Shared hosts:** 1,986 hosts in stored sources, 23 used by two or more programs. The daily ones are
  www.soccerwire.com (1,012 programs) and www.topdrawersoccer.com (349). Weekly or occasional: www.ncei.noaa.gov and
  api.data.gov (1,009 each), en.wikipedia.org (98), register.ryzer.com (60).
- **Worst case for 3a/3b, by arithmetic:** a host answering 429 to everything costs each program 3 attempts with gate
  holds of 25 + 50 + 75 s, all serialised on one gate. For SoccerWire that is 1,012 × 150 s ≈ 42 h, so the 270-minute
  time budget stops the run after about 108 programs. The other ~900 programs, **all their collectors**, keep yesterday's data.
  One sick shared host therefore costs the whole day's refresh, not just its own collector.
- **Aliases (item 2):** 420 sites appear under two names in stored sources (`www.x` and `x`, plus one `goslugs.com:443`).
  None is shared across programs, so no two programs collide. But one program's requests can alternate names and skip
  the 1.2 s gap or a Crawl-delay, and a backoff on one name doesn't hold the other. That is politeness, not completeness.
  There are no internationalised hostnames, so that part of item 2 is moot today.

## Plan, by impact
**A. Per-run circuit breaker for a failing host (3a), and no sleep after the last attempt (3b).** Biggest impact.
- The gate counts **consecutive** fetches to a host that ended in failure after retries (429, 5xx, network). At
  `BREAKER_FAILS` (proposed 5, configurable by env), the host is open for the rest of the run.
- An open host raises `HostRefused` at once, inside the gate, for every hop to it. The collector fails as today, the program keeps
  its stored data, and refresh-state records `host stopped: <host>`. Any success resets the count. Camps' `host_guard`
  stays as it is.
- The run's summary lists stopped hosts as a `::warning`.
- `fetch()` raises right after the final attempt instead of sleeping first.
- **Tests that fail on main** (`tests/refresh_politeness_test.py`, local stub server, `time.sleep` patched to record):
  - 20 sequential fetches to an always-429 stub: main sends 60 requests; the branch sends at most `BREAKER_FAILS × 3`, then refuses with nothing sent.
  - `fetch(retries=3)` to an always-503 stub records 2 sleeps, not 3.
  - one success between failures resets the count (a host with occasional 503s is never stopped). This one passes on main, as a guard.
  - a stopped host doesn't affect another host's gate.
- **Risk:** a brief outage of a shared host stops it for the whole run, so its collector waits a day. That's bounded and
  visible in the warning, and better than losing every collector of 900 programs. 5 consecutive failures after
  retries is about 15 bad answers in a row.

**B. One gate per server name: canonical host key (2).**
- `_gate_key(host)`: lower-case, strip a leading `www.`, drop `:443`/`:80`, IDNA-encode. It's used for `_gates`,
  `_host_delay`, `_last_request_at` and the breaker.
- **Tests that fail on main:** `_polite("https://www.x.test/")` then `_polite("https://x.test:443/")` with a patched clock: the second waits the gap
  (main: no wait); a hold on `www.x.test` delays `x.test`; a Crawl-delay read for `x.test` applies to `www.x.test`.
- **Risk:** stricter spacing for 420 sites that sometimes alternate names. It's within one program, so it adds at most
  about a gap per switch. I'll measure the daily run time before and after with the stub replay in the PR. A `www`
  host that really is a different server only gets more conservative spacing.

**C. A whole-request deadline (3c).**
- Stream the body and stop at `max(3 × timeout, 120 s)` wall time. Raise a network-style `FetchError`, so the host is
  held and counted toward A.
- **Test that fails on main:** a stub that trickles 1 byte every 0.5 s for 30 s, with `timeout=2`. Main returns after 30 s;
  the branch raises by the deadline (the test patches the deadline down to 3 s).
- **Risk:** a large page on a slow host is cut off. Today's biggest pages (1-1.5 MB athletics HTML) load in seconds,
  far under 120 s.

**D. Item 4 is a decision for the owner, with no code.** I recommend keeping today's behaviour and closing the item:
- the publish is gated by build + validate;
- the time budget keeps stored data;
- the annotation already says so.

The README side is #89.
**Order.** A, B, C: one PR each, "Part of #108". Each runs `tests/refresh_politeness_test.py` and the full suites
(`run-tests`). The issue closes after C and the owner's ruling on D.
