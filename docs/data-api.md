# Data API v1

The site reads its published data through a same-origin, read-only API (`/api/v1/*`, issue #240). This document is
the contract for the people and scripts that call it, and the runbook for the owner. The design follows the one the
owner shipped on ecnl.nextonetwo.com (NextOneTwoLabs/ecnl-dashboard #90, #92, #93); the code in `api/session.mjs`
and `api/apikey.mjs` and the owner's `tools/apikey.mjs` are ported from there.

## What it is, honestly (issue #345)

**Direct use of the API needs a key.** The website stays free, with no login, and never needs one: the page carries
its own session cookie. Scripts, agents and other servers send an API key that the owner issues (see
[API keys](#api-keys)). Without a key or the page's cookie there is only a small allowance per internet address, for a
quick look.

The limits make copying the data **slow and visible, not impossible**. Anyone can load `/`, keep the cookie it sets,
and read the API at the session pace, and the project's repository is public and holds the same data. Keys are a
sanctioned, visible and revocable path, not a lock. Success is measured by the `limited-*` counts below, not by zero
scraping.

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

## Doors and rate limits

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
| `RL_KEY` | API key id | 60 per 60 s | requests with a valid API key |
| `RL_SESSION` | session id | 180 per 60 s | requests with a valid session cookie |
| `RL_ANON` | IP address, or the IPv6 /64 | 60 per 60 s (30 later, only after the page work and a measured week) | requests with neither a key nor a valid cookie |
| `RL_IP` | IP address, or the IPv6 /64 | 1,200 per 60 s | every request, on every door, keyed ones included (a ceiling sized for a shared Wi-Fi) |

The numbers come from this site's own journeys, counted from the page code: a cold load is 2 API requests, a profile 1
on first open, Compare up to 4 at once, Pipelines 1 plus 1 per opened "players" row, ID Camps 1; the heaviest realistic
minute is about 20, and opening ten profiles in new tabs about 30. At a key's pace, one request a second, a copy of all
1,011 profiles and the 5 indexes takes about 17 minutes.

**The counters are approximate.** Cloudflare keeps them per location and per machine, and they favour visitors: a burst
spread over several connections, two clock minutes or both IPv4 and IPv6 (two different IP keys) can pass the number
before it is refused. From one keep-alive IPv4 connection within one clock minute, the anonymous limit was measured on
the #371 preview and on production: the first 429 came at request 62.

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

Scripts and agents use an API key, sent in the `Authorization` header (see [API keys](#api-keys)):

```sh
curl -s -H "Authorization: Bearer $COLLEGEDASH_API_KEY" https://college.nextonetwo.com/api/v1/status
```

Without a key, `curl` still works within the small anonymous allowance, and beyond it gets a 429 whose `help` field
points to keys.

### How the web app's session works (team testing)

Anyone can see this; keys don't close it, and it is not a way to use the API:

```sh
curl -s -o /dev/null -c jar.txt https://college.nextonetwo.com/
curl -s -b jar.txt -c jar.txt https://college.nextonetwo.com/api/v1/status
```

The second answer says `X-CollegeDash-Session: ok`. Delete `jar.txt` afterwards.

### The Workers Free quota (shared with ECNL)

The account is on **Workers Free: 100,000 Worker requests a day, account-wide** (this Worker, `ecnl-dashboard` and any
other on the account), reset at 00:00 UTC. After that `/` and `/api/*` fail for every visitor of both sites until
00:00 UTC, and every request counts, **including the Worker's own 401s and 429s**. The limits make an unwanted request
cheap to answer; they do not stop it from being counted. One cookie-holding script at `RL_SESSION`'s pace would use the
day in about 9 hours; **one key at full pace uses 86,400 a day**, most of the quota. That is why, while the account is
on Free, keys go only to the team and are time-limited. **Workers Paid is the only full remedy**; the owner approved
moving to it before phase 4 (#345), and before any key goes to anyone outside the team.

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
  `key-revoked`, `limited-key`, `key-error` (503), `key-in-url` (400), and `limited-ip` with `blob6` `key`. Key points
  add `blob5`, the key id once a record exists for it (`-` otherwise; `key-in-url` keeps the unverified id, which says
  which key to revoke). Points with a verified id are indexed by it.

Report with a token that has *Account · Account Analytics · Read*, always weighting by `_sample_interval`:

```sql
SELECT blob1 AS outcome, blob4 AS site, SUM(_sample_interval) AS requests
FROM collegedash_api_gate WHERE timestamp > NOW() - INTERVAL '1' DAY
GROUP BY outcome, site ORDER BY requests DESC
```

Per key:

```sql
SELECT blob5 AS key_id, blob1 AS outcome, SUM(_sample_interval) AS requests
FROM collegedash_api_gate WHERE timestamp > NOW() - INTERVAL '7' DAY AND blob1 LIKE '%key%'
GROUP BY key_id, outcome ORDER BY requests DESC
```

### Failure modes

- **No secret** (or one under 32 characters): sessions are `off`. No cookie, only `RL_IP`, each request counted
  `disabled`. **Production must never answer `off`.** Keys still work: the key path doesn't need the secret.
- **A fault in the session code** (a limiter or crypto throw): the data is still served as JSON with
  `X-CollegeDash-Session: error`, counted `gate-error`. Nothing in the URL or the client address can cause one.
- **The key store missing or failing**: keyed requests **fail closed** with 503, counted `key-error`. Cookie and
  anonymous requests never touch it.
- **The local Python server** (`serve.py`) runs with sessions off (`X-CollegeDash-Session: off`, no cookie, no limits)
  and checks no keys.
- **Preview hosts**: only the Worker's plain address `collegedash.nextonetwolabs.workers.dev` redirects to
  `college.nextonetwo.com`. A version or branch preview (`<version>-collegedash.nextonetwolabs.workers.dev`) serves its
  own deployment, cookie included, so it can be checked without testing production. **Previews run with production's
  bindings and secrets**, so a preview reads the same key store: a key works on both.

### Rollback

The limits can refuse (429) from their first deploy. The rollback is the unmerged PR #372 (`claude/345-rollback-limits`):
it removes the `RL_SESSION` and `RL_ANON` blocks from `wrangler.toml` (a missing limiter is treated as allowed) and
keeps `RL_IP` and `RL_KEY`. The owner or TPM merges it without waiting for review; it takes effect after a Workers
Builds deploy, **about 5 to 15 minutes**, not instantly. A single key is stopped by revoking it (below), not by a
rollback.

### Owner setup (the team runs none of this)

In PowerShell, in the CollegeDash checkout, in a standalone window (not the desktop app's Terminal panel):

1. **Stores first, always in the dashboard.** The Analytics Engine dataset `collegedash_api_gate` (Workers & Pages >
   Analytics Engine) and the KV namespace `COLLEGE_API_KEYS` (Workers & Pages > KV > Create; its id is shown in the
   namespace list) exist before the first build that binds them. A namespace id is an identifier, not a credential:
   post it on #345, and it goes into `wrangler.toml` and `tools/apikey.mjs`. `COLLEGE_API_KEYS` was created on
   2026-09-25 (the name matches ECNL's `ECNL_API_KEYS`).
2. **The session secret:** create it with a generated value and add it to a new version **without deploying**, then use
   **Retry build** on the PR's latest Workers Build:

   ```powershell
   node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"
   npx.cmd wrangler versions secret put SESSION_SECRET --name collegedash
   ```

   **Never** use a plain `wrangler secret put`, or the dashboard's Deploy, while a PR preview is the latest version:
   both build the new version from that latest version and could put unmerged PR code into production. Don't list the
   secret under `[secrets] required` (it would block every deploy, the data refreshes included). A preview uploaded
   before the secret exists answers `off` until it is uploaded again (Retry build).
3. **Rate-limit ids:** no other Worker on the account uses `namespace_id`s 3461-3464 (ECNL uses 9001-9004).
4. **Never** turn on Bot Fight Mode or Pseudo IPv4 "Overwrite headers" (both zone-wide, shared with ECNL), or Workers
   Logs (`[observability]`) without first checking whether it records request headers (it could record
   `Authorization`). The one free WAF rate rule for the zone is agreed with the ECNL side (#345).

## API keys

Direct use of `/api/v1` (scripts, agents, other servers) needs an API key that the owner issues (#345). The website
never uses one; it keeps its session cookie. There is no self-service signup and no billing. **While the account is on
Workers Free, keys go only to the team, time-limited; a key for anyone outside the team waits for Workers Paid.**

**How to ask for one.** Use **Send feedback** on the site, with a reply address, and say what the key is for (a project
or agent name) and roughly how many requests a day. The owner replies from their own email with the key. Keys are never
sent in a GitHub issue, a pull request or a chat.

**How to send it.** Only in the `Authorization` header, as `Bearer <key>` (`Bearer` in any case). Never in a URL: URLs
end up in browser history, `Referer` headers, proxy and server logs, chat previews and shared links. A key-shaped string
anywhere in the path or query string, plain or percent-encoded (up to 8 times over), is refused with 400, "Treat this
key as exposed and ask for a new one", and the owner can see which key it was.

```sh
curl -s -H "Authorization: Bearer $COLLEGEDASH_API_KEY" https://college.nextonetwo.com/api/v1/programs
```

```python
import os, urllib.request
req = urllib.request.Request("https://college.nextonetwo.com/api/v1/programs",
                             headers={"Authorization": "Bearer " + os.environ["COLLEGEDASH_API_KEY"]})
print(urllib.request.urlopen(req).read()[:200])
```

A key is `cdash_live_<id>_<secret>`: `id` is 12 lowercase hex characters and not secret (it names the key in counts, in
the per-key limit and in the owner's commands); `secret` is 64 lowercase hex characters. Only the SHA-256 of the whole
key is stored. The API sends no CORS headers, so a key only works from servers, scripts and agents, not from another
site's page.

**Limits.** 60 requests per 60 s per key (`RL_KEY`), and every keyed request also counts toward the per-IP ceiling
(`RL_IP`, 1,200 per 60 s), which is checked first, before the key is looked up. That is one request a second: a full
copy takes about 17 minutes. Over a limit: 429 with `Retry-After: 60`, and no `help` (you already have a key).

**Answers.** Every answer to a keyed request says `X-CollegeDash-Session: key`. Refusals (400, 401, 429, 503) are JSON
with `Cache-Control: no-store`. A served request is answered as any other: the data with `Cache-Control: no-cache`, or a
304 with no body. HEAD never has a body.

| Case | Status | Body and headers |
| --- | --- | --- |
| Valid key | 200 (or 304, 400, 404, 405 as for any request) | the data; no cookie |
| Invalid, unknown or revoked key, or not `Bearer <key>` | 401 | `{"ok":false,"error":"This API key is not valid or has been revoked.","help":"<this section's URL>"}`, the same for every reason; `WWW-Authenticate: Bearer realm="collegedash", error="invalid_token"` |
| Over `RL_KEY` or `RL_IP` | 429 | `{"ok":false,"error":"Too many requests. Please wait a minute and try again."}`, `Retry-After: 60` |
| Key in the URL | 400 | `{"ok":false,"error":"Send API keys in the Authorization header, never in a URL. Treat this key as exposed and ask for a new one.","help":"<this section's URL>"}` |
| Key store unavailable | 503 | `{"ok":false,"error":"API keys cannot be checked right now. Please try again later."}`, `Retry-After: 60` |

- An `Authorization` header is always judged as a key, even beside a valid session cookie: a bad key gets 401 and never
  falls back to the cookie.
- **Timing.** A new key works about 2 minutes after the owner stores it, and a revoked key stops within about 2 minutes:
  up to 60 s in the Worker's own cache plus up to 60 s for KV to reach every location. A key used before it is stored is
  remembered as unknown for as long, so wait the 2 minutes. Made-up ids are cached apart from real ones, so a flood of
  them cannot push a real key out of the cache.
- **The Workers Free quota applies to keyed traffic too**, 401s and 429s included (see "The Workers Free quota").

**What the owner keeps about a key.** One KV record per key in the `COLLEGE_API_KEYS` namespace (binding
`API_KEYS`; its own store, never the feedback store), under `key:<id>`:

| Field | Value |
| --- | --- |
| `v` | 1 |
| `hash` | SHA-256 (hex) of the whole key. The key itself is never stored. |
| `label` | a project or agent name the owner chooses, 1-40 letters, digits, spaces or `._-`; never a person's name or an email address |
| `created` | ISO time |
| `tier` | `standard` |
| `status` | `active`, or `revoked` (a revoked record keeps `v`, `label`, `status` and `revoked`, the time, and drops the hash) |

Counts record the key id, never the key (see "What is recorded").

**Handling a key.** Treat it like a password.
- Keep it in an environment variable or a file outside any repository; never commit it, paste it in an issue or chat,
  or put it in a URL.
- Never capture it in a debugging record: no `curl -v`, no browser HAR export and no Playwright trace while a key is in
  use, because all of them record request headers.
- In reports and messages, redact it to `cdash_live_<id>_...`.
- If it may have been exposed, ask for a new one; the owner revokes the old one.
- `tests/apikey.test.mjs` fails CI if a key-shaped string is in the repository (it also scans a copy that is not a git
  checkout). **If it ever finds one, revoke that key first**: the repository is public, so a pushed key is already
  exposed. Then remove it from the tree.
- Keys travel in a request header. Workers Logs and `wrangler tail` may record request headers, including
  `Authorization` (not verified). This Worker has no `[observability]` section; keep it that way, or check first.

### Issuing and revoking keys (owner)

`tools/apikey.mjs` does it. It needs only Node, makes no network request and never runs wrangler: it prints the key
once, writes only the hash record to the system temp folder, and prints the exact commands to run. **Run it in a
standalone PowerShell window, not the desktop app's Terminal panel,** which assistants can read. Run the printed
`npx.cmd wrangler` commands in the same window, in your CollegeDash folder; they name the namespace by id
(`--namespace-id`, never `--binding`), so they don't need this branch's `wrangler.toml`, and they always pass `--remote`,
because wrangler v4 otherwise writes only to a local copy on your computer. Until the namespace id is in the tool, every
command but `help` refuses.

```powershell
node tools\apikey.mjs new --label "acme-agent"                      # prints the key once, then the commands
node tools\apikey.mjs new --label "verifier-345" --ttl 604800       # a test key that KV deletes after 7 days
node tools\apikey.mjs revoke <id> --label "acme-agent"              # keeps a revoked record; prints the commands
node tools\apikey.mjs list                                          # prints the command that lists key ids
node tools\apikey.mjs get <id>                                      # prints the command that shows one record
node tools\apikey.mjs purge <id>                                    # prints the command that deletes a record
node tools\apikey.mjs help                                          # all of the above, with every wrangler command
```

`new` prints, in order: the key (give it to its holder by private email; it is not shown again), the
`npx.cmd wrangler kv key put "key:<id>" --path "<temp file>" --namespace-id <COLLEGE_API_KEYS id> --remote` that
stores the record, and the `Remove-Item` for the temp file (it holds only the hash). Use a project or agent name as the
label, never a person's name. `--ttl` is in seconds, at least 60; `revoke` needs `--label`. **Once you have sent the key
and run the printed commands, close that PowerShell window:** the key stays in its scrollback until you do.

**Revoking** keeps a record with the id, label and time, so the counts still show a revoked key that is being tried
(`key-revoked`). **Purging** (`kv key delete`) removes it entirely; use it only to clean up.

**Before phase 2 is merged** (the preview check), your checkout doesn't have the tool yet. It is one self-contained file,
so copy it, pinned to the commit the Reviewer reviewed, and run it from the temp folder:

```powershell
git fetch origin claude/345-phase2-keys
git show <reviewed commit>:tools/apikey.mjs | Set-Content -Encoding ascii "$env:TEMP\cdash-apikey-tool.mjs"
node "$env:TEMP\cdash-apikey-tool.mjs" new --label "verifier-345" --ttl 604800
```

**Keep that copy until the test key is revoked, and revoke with it:**
`node "$env:TEMP\cdash-apikey-tool.mjs" revoke <id> --label "verifier-345"`. Only then delete the copy
(`Remove-Item "$env:TEMP\cdash-apikey-tool.mjs"`). **After merge and a `git pull`,** `node tools\apikey.mjs ...` works
from your checkout, as above.

**The team's test key.** One per verification round, issued by the owner:
- `new --label "verifier-345" --ttl 604800`: KV deletes the record after 7 days, so a forgotten key expires. **Revoke it
  after the production check.**
- **It never passes through a conversation.** The owner sets it in the verifier's shell environment, as
  `COLLEGEDASH_TEST_KEY`, **before** the agent session starts: for example `$env:COLLEGEDASH_TEST_KEY = '<key>'`, typed
  by the owner in the PowerShell window that launches the session. It is never pasted into a chat, an issue or a PR:
  agent transcripts are stored. If it ever appears in one, it is treated as exposed: revoke it and issue another.
- The verifier refers to it only as `$env:COLLEGEDASH_TEST_KEY`, never echoes it, never uses `curl -v`, HAR or traces
  with it, and redacts it to `cdash_live_<id>_...` in reports.
- **It works on production too:** previews use production's bindings, so preview and production read the same store.
