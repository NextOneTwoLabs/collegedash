# Plan: #108 C, a whole-hop deadline (split out of the #108 plan, for its own review)

Part of #108. A (host stop, `fix/108-a-host-stop`) and B (one gate per server, `fix/108-b-host-key`) are being built.
This is C alone, revised for Huatuo's round-2 REQUIRED 1. Author: Jueying. Status: plan only; no code.

## The problem
- `requests`' `timeout=` is per socket read, not per request.
- The adapter reads `resp.content` inside the host's gate (`_PoliteAdapter.send`), so a body that arrives one byte
  every few seconds holds the gate as long as the server likes.
- A chunked read doesn't fix that by itself. urllib3 2.x `HTTPResponse.read(amt)` loops until `amt` bytes arrive, and
  each trickled byte resets the socket timeout. At 1 byte per 0.5 s, an 8–64 KiB read would check the deadline only
  once every 1–9 hours.

## The fix
- **Where:** `_PoliteAdapter.send`, in the in-gate body read. `fetch()` never passes `stream=True`, so the body is
  always read inside the gate.
- **Deadline:** `max(3 × timeout, 120 s)` from the start of the hop.
- **How each read stays inside it.** Read `resp.raw` with `read1(n)` (urllib3 ≥ 2.0; this venv has 2.8.0).
  - `read1` returns whatever one socket read gives, without looping until `n` bytes.
  - Before each read, set the socket timeout to `min(timeout, time remaining)`. One read can therefore never outlast
    the deadline: it either returns some bytes or times out by then.
  - Then check the clock again.
- **Content.** Keep `decode_content=True`, so gzip/deflate still decode. Assemble the bytes into `resp._content`, as
  `requests` does, so callers see the same `resp.content`.
- **Past the deadline:** close the response and raise `RequestDeadline(requests.exceptions.Timeout)`.
  - It's a `RequestException`, so the adapter's existing `except` holds the host (`_hold`, network backoff).
  - `fetch()`'s retry loop retries it, and A counts it as a network failure.
- **Scope:** per hop. It applies to the first request, every redirect hop, robots.txt loads and `fetch_no_redirect`,
  since all of them go through the adapter.
- **First, measure.** For one or two runs, log each host's longest fetch, to confirm 180 s (at the default 60 s
  timeout) is far above anything legitimate. A 1.5 MB page needs only about 8 KB/s to finish in 180 s.

## Tests
In `tests/refresh_politeness_test.py`, with local stubs only.

**Fails on main:** a stub that sends headers, then trickles one byte every 0.5 s and **ends after 15 s** (a fixed end,
so main finishes instead of hanging).
- The test sets `timeout=2` and the deadline to 3 s.
- Main reads all 15 s, which is past deadline + slack.
- The branch raises `RequestDeadline` by about 3 s, and the stub's host is held afterwards: a second fetch waits the
  network backoff.

**Guards** (pass on main):
- a 1 MB body sent at full speed is read whole and decoded the same;
- a gzip body still decodes;
- a slow first byte under `timeout` still succeeds.

Real time used: about 3 s on the branch and about 15 s on main.

## Risk and limits
- **A slow, very large page is cut off.** The log above shows the margin before the cap ships.
- **Trickled headers are not covered.** `read1` caps the body only. A server that trickles its status line or headers
  is still bounded only by the per-read `timeout`. That's out of scope here; a separate connect-and-headers cap
  would need urllib3 internals.
- **Constants:** `timeout` is per call. The deadline follows it, so callers passing `timeout=600` (the Scorecard bulk
  download) get 1,800 s.
