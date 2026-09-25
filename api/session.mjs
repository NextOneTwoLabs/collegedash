// Session cookie and rate limits for /api/v1/* (issue #345, phase 1). See docs/data-api.md, "Sessions and rate
// limits". Ported from NextOneTwoLabs/ecnl-dashboard api/session.mjs (#90, #93), which is verified on production
// there; the cookie, header, host, realm and binding names are this site's, and the logic is unchanged.
//
// The honest goal: the site stays free with no login, light keyless use is fine, heavy direct use needs an
// owner-issued key, and scraping becomes slow and visible, not impossible. Day one changes nothing for a
// determined scraper: anyone can load `/`, keep the cookie and copy the API at the session pace, or clone the
// public repository, which holds the same data.
//
// The cookie is not a secret: any visitor can read what their browser holds. It is a signed ticket saying "this
// client loaded the page". It holds a random id and two times, nothing personal, and the id keys the
// per-session rate limit. The API never refuses a request for lacking one: it is served under a lower per-IP
// limit instead (the anonymous tier), and beyond that gets a 429 that points to API keys.
//
// Direct use (scripts, agents) sends an owner-issued API key instead (api/apikey.mjs): `Authorization: Bearer
// <key>`, judged before the cookie and never falling back to it.
import { resolveResource } from './data-api.mjs';
import { checkKey, keyInUrl, HELP_URL } from './apikey.mjs';

export const COOKIE = '__Host-cdash_s';
export const HEADER = 'x-collegedash-session';
// Token lifetime, seconds. `exp - iat` must equal it, so changing TTL invalidates every token at once: one
// spike of `anon-invalid` and one background `HEAD /` per open tab.
export const TTL = 24 * 60 * 60;
// Cookie lifetime, longer than the token so a lapsed token arrives as `anon-expired` instead of vanishing into
// `anon-missing` alongside cookieless scripts.
export const COOKIE_MAX_AGE = 7 * 24 * 60 * 60;
// Re-issue, with a fresh id, once a token is older than this.
export const RENEW_AFTER = 60 * 60;
const SKEW = 60;                              // tolerated clock skew for an iat in the future
const RETRY_AFTER = 60;
export const PRODUCTION_HOST = 'college.nextonetwo.com';
// The signature is 32 bytes in 43 base64url characters; the last one carries 2 spare bits, which must be zero,
// so only the canonical encoding of a signature is accepted.
const TOKEN = /^v1\.(\d{10})\.(\d{10})\.([A-Za-z0-9_-]{22})\.([A-Za-z0-9_-]{42}[AEIMQUYcgkosw048])$/;
const enc = new TextEncoder();

const b64u = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const unb64u = text => Uint8Array.from(atob(text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - text.length % 4) % 4)), c => c.charCodeAt(0));

// The HMAC key is imported once per isolate. A failed import is not kept, so one fault does not poison the
// isolate for every later request.
let cachedKey = null;
function hmacKey(secret) {
  if (cachedKey?.secret !== secret) {
    const key = crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
    cachedKey = { secret, key };
    key.catch(() => { if (cachedKey?.key === key) cachedKey = null; });
  }
  return cachedKey.key;
}

// Generate it with the command in docs/data-api.md; any 32 characters pass this check.
export const usableSecret = secret => typeof secret === 'string' && secret.length >= 32;

export async function mint(secret, nowMs = Date.now(), sid = b64u(crypto.getRandomValues(new Uint8Array(16)))) {
  const iat = Math.floor(nowMs / 1000);
  const payload = `v1.${iat}.${iat + TTL}.${sid}`;
  const sig = new Uint8Array(await crypto.subtle.sign('HMAC', await hmacKey(secret), enc.encode(payload)));
  return `${payload}.${b64u(sig)}`;
}

// -> { state: 'missing' | 'invalid' | 'expired' | 'valid' | 'renew', sid? }
export async function verify(secret, token, nowMs = Date.now()) {
  if (!token) return { state: 'missing' };
  const m = TOKEN.exec(token);
  if (!m) return { state: 'invalid' };
  const [, iatText, expText, sid, sig] = m;
  // crypto.subtle.verify compares in constant time.
  const ok = await crypto.subtle.verify('HMAC', await hmacKey(secret), unb64u(sig), enc.encode(`v1.${iatText}.${expText}.${sid}`));
  if (!ok) return { state: 'invalid' };
  const now = Math.floor(nowMs / 1000), iat = Number(iatText), exp = Number(expText);
  if (iat > now + SKEW || exp - iat !== TTL) return { state: 'invalid' };
  if (now >= exp) return { state: 'expired' };
  return { state: now - iat >= RENEW_AFTER ? 'renew' : 'valid', sid };
}

export function readCookie(header, name = COOKIE) {
  for (const part of (header || '').split(';')) {
    const i = part.indexOf('=');
    if (i > 0 && part.slice(0, i).trim() === name) return part.slice(i + 1).trim();
  }
  return null;
}

export const setCookie = token => `${COOKIE}=${token}; Max-Age=${COOKIE_MAX_AGE}; Path=/; Secure; HttpOnly; SameSite=Lax`;

// Rate-limit key for the client address: IPv4 as is, IPv6 by its /64 (one home or host can hold a whole /64,
// so a per-address key would be trivially rotated). An IPv4-mapped IPv6 address (::ffff:a.b.c.d) is keyed as
// its IPv4 address. Pure: never throws, whatever the header holds.
export function ipKey(ip) {
  if (!ip) return 'ip:unknown';
  ip = ip.trim().toLowerCase();
  if (!ip.includes(':')) return 'ip:' + ip;
  const v4 = /(\d+)\.(\d+)\.(\d+)\.(\d+)$/.exec(ip);
  if (v4) ip = ip.slice(0, v4.index) + ((v4[1] << 8) | v4[2]).toString(16) + ':' + ((v4[3] << 8) | v4[4]).toString(16);
  const [head, tail = ''] = ip.split('::');
  const h = head ? head.split(':') : [], t = tail ? tail.split(':') : [];
  const groups = (ip.includes('::') ? [...h, ...Array(Math.max(0, 8 - h.length - t.length)).fill('0'), ...t] : h).map(g => parseInt(g, 16) || 0);
  if (groups.length === 8 && groups.slice(0, 5).every(g => g === 0) && groups[5] === 0xffff) {
    return `ip:${groups[6] >> 8}.${groups[6] & 255}.${groups[7] >> 8}.${groups[7] & 255}`;
  }
  return 'ip6:' + groups.slice(0, 4).map(g => g.toString(16)).join(':') + '::/64';
}

const refuse = (request, status, session, body, extra = {}) => new Response(request.method === 'HEAD' ? null : JSON.stringify({ ok: false, ...body }), {
  status,
  headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', [HEADER]: session, ...extra },
});
const TOO_MANY = 'Too many requests. Please wait a minute and try again.';
// An anonymous-tier 429 also points to API keys, as a bare `help` URL (the page never shows it) and a Link
// header with the same target. Session-tier and key 429s carry neither.
const tooMany = (request, session, help = false) => refuse(request, 429, session,
  help ? { error: TOO_MANY, help: HELP_URL } : { error: TOO_MANY },
  help ? { 'retry-after': String(RETRY_AFTER), link: `<${HELP_URL}>; rel="help"` } : { 'retry-after': String(RETRY_AFTER) });
// One body for every invalid, unknown or revoked key, so the answer says nothing about which.
const badKey = request => refuse(request, 401, 'key', { error: 'This API key is not valid or has been revoked.', help: HELP_URL },
  { 'www-authenticate': 'Bearer realm="collegedash", error="invalid_token"' });
const keyInUrlRefusal = request => refuse(request, 400, 'key',
  { error: 'Send API keys in the Authorization header, never in a URL. Treat this key as exposed and ask for a new one.', help: HELP_URL });
const keyDown = request => refuse(request, 503, 'key', { error: 'API keys cannot be checked right now. Please try again later.' },
  { 'retry-after': String(RETRY_AFTER) });

// A limiter fault on the key path does not refuse: RL_IP is checked before the key is judged, and RL_KEY only
// after the key is proven, as on the session path.
const allowedOpen = async (binding, key) => { try { return await allowed(binding, key); } catch { return true; } };

// Keyed requests. The per-IP ceiling comes first, so an IP over it costs no KV read; then the key; then the
// per-key limit, so an invalid key never spends a real key's allowance. Counts carry the key id only once a
// record exists for it, `-` otherwise.
async function keyGate(request, env, about, ip, nowMs) {
  if (!(await allowedOpen(env.RL_IP, ip))) {
    count(env, 'limited-ip', about, { id: '-', reason: 'key' });
    return { response: tooMany(request, 'key') };
  }
  const v = await checkKey(request.headers.get('authorization'), env, nowMs);
  if (v.state === 'error') { count(env, 'key-error', about, { id: '-' }); return { response: keyDown(request) }; }
  if (v.state !== 'ok') { count(env, v.state === 'revoked' ? 'key-revoked' : 'key-invalid', about, v); return { response: badKey(request) }; }
  if (!(await allowedOpen(env.RL_KEY, 'key:' + v.id))) { count(env, 'limited-key', about, v); return { response: tooMany(request, 'key') }; }
  count(env, 'key-ok', about, v);
  return { session: 'key', cookie: null };
}

// What is recorded about a request, and only for non-routine ones: the outcome, the route kind, the
// Sec-Fetch-Site class and production or preview. No IP address, session id, user agent, key or hash. At most
// one data point per request. A failed write (quota, missing binding) never changes the response.
function describe(request) {
  const url = new URL(request.url);
  const resource = resolveResource(url.pathname);
  const header = request.headers.get('sec-fetch-site');
  return {
    kind: url.pathname === '/' ? 'page' : resource.kind || (resource.status === 400 ? 'invalid' : 'unknown'),
    sfs: header ? (['same-origin', 'same-site', 'cross-site', 'none'].includes(header) ? header : 'other') : 'absent',
    // Preview versions run with production's bindings and vars, so only the host tells them apart.
    site: url.hostname === PRODUCTION_HOST ? 'production' : 'preview',
  };
}

// Key outcomes add blob5, the key id (never the key) or `-`, and blob6, the reason. The id is one a record
// exists for, except for `key-in-url`, which keeps the unverified id from the URL because it tells the owner
// which key to revoke. Points with a verified id are indexed by it, so per-key sums sample fairly.
function count(env, outcome, { kind, sfs, site }, key) {
  const blobs = [outcome, kind, sfs, site];
  if (key) blobs.push(key.id || '-', key.reason || '');
  const index = key?.id && key.id !== '-' && outcome !== 'key-in-url' ? key.id : outcome;
  try { env.API_GATE_STATS?.writeDataPoint({ indexes: [index], blobs, doubles: [1] }); } catch {}
}

const allowed = async (binding, key) => !binding || (await binding.limit({ key })).success;

// Called by the Worker for every /api/v1* request before the data handler.
// -> { response } to answer now (429; for keys also 400, 401 or 503), or { session, cookie } to serve and
// decorate.
export async function gate(request, env, nowMs = Date.now()) {
  const about = describe(request);
  const ip = ipKey(request.headers.get('cf-connecting-ip'));

  // First, and without SESSION_SECRET: a key-shaped string anywhere in the URL is refused; an Authorization
  // header goes to the key path, which answers for its own faults (503) so a key fault never reaches the
  // fail-open sessionFault; only then the cookie, then the allowance.
  const inUrl = keyInUrl(request.url);
  if (inUrl) {
    count(env, 'key-in-url', about, { id: inUrl[1] ? inUrl[1].toLowerCase() : '-' });
    return { response: keyInUrlRefusal(request) };
  }
  if (request.headers.has('authorization')) {
    try { return await keyGate(request, env, about, ip, nowMs); } catch (err) {
      console.error('apikey', err && err.message);
      count(env, 'key-error', about, { id: '-' });
      return { response: keyDown(request) };
    }
  }

  if (!usableSecret(env.SESSION_SECRET)) {
    // Fail open: without a secret no session can be issued, so treating everyone as anonymous would limit every
    // real visitor hard. Only the per-IP backstop applies. Production must never answer `off`.
    if (!(await allowed(env.RL_IP, ip))) { count(env, 'limited-ip', about); return { response: tooMany(request, 'off') }; }
    count(env, 'disabled', about);
    return { session: 'off' };
  }

  // SameSite=Lax withholds the cookie from cross-site subresource requests, so a cross-site request that
  // carries one is a person following a link to an API URL.
  const token = readCookie(request.headers.get('cookie'));
  const v = token && about.sfs === 'cross-site' ? { state: 'cross-site' } : await verify(env.SESSION_SECRET, token, nowMs);
  const hasSession = v.state === 'valid' || v.state === 'renew';
  // The two checks run in parallel, so a request refused by one still uses a count in the other.
  const [ipOk, tierOk] = await Promise.all([
    allowed(env.RL_IP, ip),
    hasSession ? allowed(env.RL_SESSION, 'sid:' + v.sid) : allowed(env.RL_ANON, ip),
  ]);
  if (!ipOk || !tierOk) {
    count(env, !ipOk ? 'limited-ip' : hasSession ? 'limited-session' : 'limited-anon', about);
    // "none" on an anonymous 429 is what makes the page fetch a new cookie.
    return { response: tooMany(request, hasSession ? 'ok' : 'none', !hasSession) };
  }
  if (!hasSession) count(env, 'anon-' + v.state, about);
  return {
    session: hasSession ? (v.state === 'renew' ? 'renewed' : 'ok') : 'none',
    // Requests already in flight when a token turns an hour old each get a new cookie; the browser keeps the
    // last one. Each renewal starts a new id.
    cookie: v.state === 'renew' ? setCookie(await mint(env.SESSION_SECRET, nowMs)) : null,
  };
}

// For the HTML entry ("/"): a Set-Cookie value when the visitor has no usable session or it is due for renewal;
// null otherwise, and always null when sessions are off.
export async function pageCookie(request, env, nowMs = Date.now()) {
  if (!usableSecret(env.SESSION_SECRET)) return null;
  const v = await verify(env.SESSION_SECRET, readCookie(request.headers.get('cookie')), nowMs);
  if (v.state === 'valid') return null;
  if (v.state !== 'renew') count(env, 'minted', describe(request));
  return setCookie(await mint(env.SESSION_SECRET, nowMs));
}

// A throw anywhere in the session code: logged and counted, and the request is served ungated. Never reached
// from the key path, which answers its own faults with 503.
export function sessionFault(request, env, err) {
  console.error('session', err && err.message);
  try { count(env, 'gate-error', describe(request)); } catch {}
  return { session: 'error' };
}

export function decorate(response, { session, cookie }) {
  const headers = new Headers(response.headers);
  if (session) headers.set(HEADER, session);
  if (cookie) {
    headers.append('set-cookie', cookie);
    if (!/no-store/.test(headers.get('cache-control') || '')) headers.set('cache-control', 'private, no-cache');
  }
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}
