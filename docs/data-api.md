# Data API v1

The site reads its published data through a same-origin, read-only API (`/api/v1/*`, issue #240). This document is
the contract for the people and scripts that call it, and the runbook for the owner. The design follows the one the
owner shipped on ecnl.nextonetwo.com (NextOneTwoLabs/ecnl-dashboard #90, #92, #93); the code in `api/session.mjs`
and `api/apikey.mjs` is ported from there.

## What it is, honestly (issue #345)

The website stays free, with no login. Light use without a key is fine; heavy direct use needs an API key that the
owner issues. The limits make copying the data **slow and visible, not impossible**. **Day one changes nothing for a
determined scraper**: anyone can load `/`, keep the cookie it sets, and copy the API at the session pace, and the
project's repository is public and holds the same data. Keys are a sanctioned, visible and revocable path, not a
lock. Success is measured by the `limited-*` counts below, not by zero scraping.

| GET / HEAD route | Response |
| --- | --- |
| `/api/v1/programs` | the program index (`public/data/programs/index.json`) |
| `/api/v1/programs/{slug}` | one program's profile (`public/data/programs/{slug}.json`); a slug is `[a-z0-9-]{1,64}` |
| `/api/v1/commitments` | the commitments index |
| `/api/v1/camps` | the camps index |
| `/api/v1/trends` | the clubs and high-schools index (counts only) |
| `/api/v1/status` | the refresh state (`public/archive/refresh-state.json`) |

Bodies are the published files' bytes, unchanged. An invalid slug is 400, an unknown route or file 404, another
method 405 (`Allow: GET, HEAD`), a storage fault 503. Errors are `{"ok": false, "error": "..."}` with
`Cache-Control: no-store`. Data answers are `Cache-Control: no-cache` (revalidate with the ETag); one that also sets
the session cookie is `private, no-cache`. The API sends no `Access-Control-*` header, so another site's page cannot
call it.

## Sessions and rate limits (phase 1)

Every `/api/v1*` request comes in through one of three doors, in this order:

1. **A key-shaped string anywhere in the URL** (plain or percent-encoded, up to 8 times): **400**, whatever else the
   request carries. Treat that key as exposed.
2. **An `Authorization` header**: judged as an API key, **always**, even beside a valid cookie; a bad key never falls
   back to the cookie. See [API keys](#api-keys).
3. **The session cookie**, then **the small anonymous allowance**.

### The session cookie

When the Worker serves the page (`GET` or `HEAD /`, including a 304), it sets, when there is no valid session or it is
over an hour old:

    __Host-cdash_s=v1.<iat>.<exp>.<id>.<signature>; Max-Age=604800; Path=/; Secure; HttpOnly; SameSite=Lax

It holds a random 16-byte id and two times, signed with HMAC-SHA-256 under the `SESSION_SECRET` Worker secret: nothing
personal. It is not a secret; it says "this client loaded the page", and its id keys the per-session limit. The token
is valid for 24 hours and re-issued with a fresh id once it is an hour old; the cookie is kept 7 days, so a lapsed
token is counted `anon-expired`. `Sec-Fetch-Site: cross-site` with a cookie (someone following a link to an API URL) is
served on the anonymous tier.

The page itself: any answer saying `X-CollegeDash-Session: none` makes it send one background `HEAD /`, at most once a
minute, which sets a fresh cookie. If a request sent after that renewal still says `none`, the browser is not keeping
cookies, and the page stops renewing until an answer says `ok` again. A refused load shows "Couldn't load the data" with
**Try again**; nothing retries by itself.

### Limits

| Limiter | Key | Limit | Applies to |
| --- | --- | --- | --- |
| `RL_SESSION` | session id | 180 per 60 s | requests with a valid session cookie |
| `RL_ANON` | IP address, or the IPv6 /64 | 60 per 60 s (30 later, only after the page work and a measured week) | requests with neither a key nor a valid cookie |
| `RL_IP` | IP address, or the IPv6 /64 | 1,200 per 60 s | every request, on every door (a ceiling sized for a shared Wi-Fi) |
| `RL_KEY` | API key id | 60 per 60 s | requests with a valid API key (phase 2) |

The numbers come from this site's own journeys, counted from the page code: a cold load is 2 API requests, a profile 1
on first open, Compare up to 4 at once, Pipelines 1 plus 1 per opened "players" row, ID Camps 1; the heaviest realistic
minute is about 20, and opening ten profiles in new tabs about 30. Counters are per Cloudflare location and deliberately
approximate; errors favour visitors.

Over a limit: `429`, `{"ok":false,"error":"Too many requests. Please wait a minute and try again."}`,
`Retry-After: 60`, `Cache-Control: no-store`. On the anonymous tier the body also has `help`, the URL of
[API keys](#api-keys), and the same target is in a `Link: <...>; rel="help"` header. Every answer carries
`X-CollegeDash-Session`:

| Value | Meaning |
| --- | --- |
| `ok` / `renewed` | served on the session tier (`renewed` also sets a new cookie) |
| `key` | the request carried an `Authorization` header or a key in its URL: served on its key, or refused (400, 401, 429, 503) |
| `none` | no key and no valid session: served on the anonymous tier, or refused there (429) |
| `off` | sessions are off: no usable `SESSION_SECRET`, or the local Python server |
| `error` | a fault in the session code; the data is served without a limit (never on the key path) |

### Using the API from a script

Scripts and agents use an API key (phase 2). Without one, `curl` works within the small anonymous allowance, and beyond
it gets a 429 whose `help` points to keys. How the web app's own session works, for the team's checks (anyone can see
this; keys don't close it):

```sh
curl -s -o /dev/null -c jar.txt https://college.nextonetwo.com/
curl -s -b jar.txt -c jar.txt https://college.nextonetwo.com/api/v1/status
```

The second answer says `X-CollegeDash-Session: ok`. Delete `jar.txt` afterwards.

### The Workers Free quota (shared with ECNL)

The account is on **Workers Free: 100,000 Worker requests a day, account-wide** (this Worker, `ecnl-dashboard` and any
other on the account), reset at 00:00 UTC. After that `/` and `/api/*` fail for every visitor of both sites until
00:00 UTC, and every request counts, **including the Worker's own 429s**. The limits make an unwanted request cheap to
answer; they do not stop it from being counted. One cookie-holding script at `RL_SESSION`'s pace would use the day in
about 9 hours. **Workers Paid is the only full remedy**; the owner approved moving to it before phase 4 (#345).

### What is recorded

Each non-routine request writes **one** Workers Analytics Engine data point (dataset `collegedash_api_gate`, binding
`API_GATE_STATS`): `blob1` the outcome, `blob2` the route kind (`programs`, `program`, `camps`, `trends`,
`commitments`, `status`, `invalid`, `unknown`, or `page` for `/`), `blob3` the `Sec-Fetch-Site` class, `blob4`
`production` or `preview` (from the host), `double1` 1. **No IP address, session id, user agent, key or hash.**
Routine session requests write nothing. Outcomes:

- `anon-missing`, `anon-invalid`, `anon-expired`, `anon-cross-site`: served on the anonymous tier.
- `limited-session`, `limited-anon`, `limited-ip`: refused with 429.
- `minted`: `/` issued a new session. `disabled`: served with sessions off. `gate-error`: a fault in the session code.
- Keys: `key-ok`, `key-invalid` (reason in `blob6`: `scheme`, `malformed`, `unknown`, `record`, `mismatch`),
  `key-revoked`, `limited-key`, `key-error` (503), `key-in-url` (400). Key points add `blob5`, the key id once a record
  exists for it (`-` otherwise; `key-in-url` keeps the unverified id, which says which key to revoke).

Report with a token that has *Account · Account Analytics · Read*, always weighting by `_sample_interval`:

```sql
SELECT blob1 AS outcome, blob4 AS site, SUM(_sample_interval) AS requests
FROM collegedash_api_gate WHERE timestamp > NOW() - INTERVAL '1' DAY
GROUP BY outcome, site ORDER BY requests DESC
```

### Failure modes

- **No secret** (or one under 32 characters): sessions are `off`. No cookie, only `RL_IP`, each request counted
  `disabled`. **Production must never answer `off`.**
- **A fault in the session code** (a limiter or crypto throw): the data is still served as JSON with
  `X-CollegeDash-Session: error`, counted `gate-error`. Nothing in the URL or the client address can cause one.
- **The key store missing or failing**: keyed requests **fail closed** with 503. Cookie and anonymous requests never
  touch it. Until phase 2 binds the key store, every well-formed key gets this 503.
- **The local Python server** (`serve.py`) runs with sessions off (`X-CollegeDash-Session: off`, no cookie, no limits)
  and checks no keys.
- **Preview hosts**: only the Worker's plain address `collegedash.nextonetwolabs.workers.dev` redirects to
  `college.nextonetwo.com`. A version preview (`<version>-collegedash.nextonetwolabs.workers.dev`) serves its own
  deployment, cookie included, so it can be checked without testing production. Previews run with production's
  bindings and secrets.

### Rollback

Phase 1 can refuse (429) from its first deploy. The rollback is the unmerged PR from `claude/345-rollback-limits`: it
removes the `RL_SESSION` and `RL_ANON` blocks from `wrangler.toml` (a missing limiter is treated as allowed) and keeps
`RL_IP`. The owner or TPM merges it without waiting for review; it takes effect after a Workers Builds deploy, **about
5 to 15 minutes**, not instantly.

### Owner setup (the team runs none of this)

In PowerShell, in the CollegeDash checkout, in a standalone window (not the desktop app's Terminal panel):

1. **Before the first build with these bindings:** the Analytics Engine dataset `collegedash_api_gate` exists in the
   dashboard (Workers & Pages > Analytics Engine). A dataset or store is always created in the dashboard first.
2. **Before the PR's preview check:** create the secret with a generated value and add it to a new version **without
   deploying**, then use **Retry build** on the PR's latest Workers Build:

   ```powershell
   node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"
   npx.cmd wrangler versions secret put SESSION_SECRET --name collegedash
   ```

   **Never** use a plain `wrangler secret put`, or the dashboard's Deploy, while a PR preview is the latest version:
   both build the new version from that latest version and could put unmerged PR code into production. Don't list the
   secret under `[secrets] required` (it would block every deploy, the data refreshes included). A preview uploaded
   before the secret exists answers `off` until it is uploaded again (Retry build).
3. **Before merge:** confirm no other Worker on the account uses rate-limit `namespace_id`s 3461-3463.
4. **Merge only Monday to Wednesday**, so the first days of counts and any rollback fall in the working week.
5. **Never** turn on Bot Fight Mode or Pseudo IPv4 "Overwrite headers" (both zone-wide, shared with ECNL), or Workers
   Logs (`[observability]`) without first checking whether it records request headers. The one free WAF rate rule for
   the zone is agreed with the ECNL side (#345).

## API keys

Direct use of `/api/v1` (scripts, agents, other servers) needs an API key that the owner issues. **Keys arrive in
phase 2 of #345**: until then the key door is in place but has no key store, so a well-formed key gets 503, and none
has been issued. While the account is on Workers Free, keys go only to the team, time-limited; outside keys wait for
Workers Paid. The website never uses a key.

**How to ask for one.** Use **Send feedback** on the site, with a reply address, and say what the key is for and
roughly how many requests a day. The owner replies from their own email. Keys are never sent in a GitHub issue, a pull
request or a chat.

**How to send it.** Only in the `Authorization` header, as `Bearer <key>`. Never in a URL: a key-shaped string in the
path or query string, plain or encoded, is refused with 400 ("Treat this key as exposed").

```sh
curl -s -H "Authorization: Bearer $COLLEGEDASH_API_KEY" https://college.nextonetwo.com/api/v1/programs
```

A key is `cdash_live_<id>_<secret>`: `id` is 12 lowercase hex characters and not secret; `secret` is 64 lowercase hex
characters. Only its SHA-256 is stored. Answers:

| Case | Status | Body and headers |
| --- | --- | --- |
| Valid key | 200 (or 304, 400, 404, 405 as for any request) | the data; no cookie |
| Invalid, unknown or revoked key, or not `Bearer <key>` | 401 | `{"ok":false,"error":"This API key is not valid or has been revoked.","help":"<this section>"}`, the same for every reason; `WWW-Authenticate: Bearer realm="collegedash", error="invalid_token"` |
| Over `RL_KEY` or `RL_IP` | 429 | `Retry-After: 60` |
| Key in the URL | 400 | "Send API keys in the Authorization header, never in a URL. Treat this key as exposed and ask for a new one." |
| Key store unavailable | 503 | `Retry-After: 60` |

**Handling a key.** Treat it like a password: an environment variable or a file outside any repository; never
committed, pasted in an issue or chat, or put in a URL; no `curl -v`, HAR export or browser trace while a key is in use;
redacted to `cdash_live_<id>_...` in reports. A team verifier's test key is set by the owner in the shell environment
(`COLLEGEDASH_TEST_KEY`) **before** the agent session starts, and never passes through a conversation. A CI test fails
if a key-shaped string is ever in the repository; if it does, revoke that key first.
