// The /api/v1 gate (issue #345): who is asking, and whether they may. Plan approved on #345 (Bianque, round 2;
// owner decisions 1-10).
//
// Two ways in, the same paths:
//   - a customer key in `Authorization: Bearer cdk_<id>_<secret>`: looked up by SHA-256 in D1, metered against a
//     daily quota, per-minute limited;
//   - the website's own calls, keyless: first-party by the X-CollegeDash-Client header, Sec-Fetch-Site: same-origin
//     or a same-origin Referer, rate-limited per IP.
// Anything else is refused with 401. /api/v1/status is never gated (worker.js does not call this for it).
//
// What this does not do: make the data secret. The repository and public/data are public. Every signal above can
// be sent by hand; the gate meters and slows honest traffic and identifies customers.
//
// Modes (env.API_GATE): "off" (or unset) - nothing happens, today's behaviour; "report" - every request is
// classified and counted, and NOTHING is refused; "enforce" - refusals are returned. PR 1 ships "report".
//
// Failure rules (plan section 2.3): the site path never reads D1 and fails OPEN - a missing or throwing rate
// limiter serves the request. A keyed request whose key cannot be checked (no D1 binding, D1 error) gets 503 when
// enforcing (owner decision 9), never served unmetered.
//
// Nothing here logs or stores a key, an Authorization value, an IP or any header value. Analytics Engine gets the
// decision and the signal class; a would-be 429 by IP gets a short HMAC bucket keyed with the IP_BUCKET_SECRET
// Worker secret (Bianque's condition), so no stored value can be tied back to an address.

import { resolveResource } from './data-api.mjs';

// cdk_ + 12-character id + _ + 43 base64url characters (32 random bytes). Checked before any D1 query.
export const KEY_RE = /^cdk_([a-z0-9]{12})_[A-Za-z0-9_-]{43}$/;
export const DOCS_URL = 'https://college.nextonetwo.com/#/api';

// The quota upsert (plan section 4.2): counts the request only while the day's count is under the quota, so a
// refused request is never counted. No row returned means the quota is used. ?1 key id, ?2 UTC day, ?3 quota.
export const SQL_KEY = 'SELECT id, status, quota FROM keys WHERE hash = ?1';
export const SQL_COUNT = 'INSERT INTO usage (key_id, day, count) VALUES (?1, ?2, 1) '
  + 'ON CONFLICT (key_id, day) DO UPDATE SET count = count + 1 WHERE usage.count < ?3 RETURNING count';

export function gateMode(env) {
  const m = String(env?.API_GATE ?? 'off').trim();
  return m === 'report' || m === 'enforce' ? m : 'off';
}

// Which first-party signal a keyless request carries. An explicit cross-site or same-site fetch is refused even
// when it also carries the client header: a page of ours never sends that.
export function firstPartySignal(request) {
  const sfs = (request.headers.get('sec-fetch-site') || '').toLowerCase();
  if (sfs === 'cross-site' || sfs === 'same-site') return 'cross-site';
  if (request.headers.get('x-collegedash-client') === 'web') return 'client-header';
  if (sfs === 'same-origin') return 'sec-fetch-site';
  const ref = request.headers.get('referer');
  if (ref) {
    try {
      if (new URL(ref).origin === new URL(request.url).origin) return 'referer';
    } catch { /* not a URL: no signal */ }
  }
  return 'none';
}

function refusal(request, status, error, extra = {}) {
  const headers = { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', ...extra };
  const body = request.method === 'HEAD' ? null : JSON.stringify({ ok: false, error, docs: DOCS_URL });
  return new Response(body, { status, headers });
}

const hex = buf => [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');

export async function sha256Hex(text) {
  return hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)));
}

// HMAC-SHA256(secret, day | ip), first 8 hex characters: enough to count repeat offenders within a day, nothing
// that reverses to an address without the secret. No secret, no bucket.
export async function ipBucket(secret, day, ip) {
  if (!secret || !ip) return '';
  const k = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return hex(await crypto.subtle.sign('HMAC', k, new TextEncoder().encode(`${day}|${ip}`))).slice(0, 8);
}

const utcDay = now => new Date(now).toISOString().slice(0, 10);
const secondsToMidnight = now => { const d = new Date(now); return Math.max(1, Math.ceil((Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1) - now) / 1000)); };

// One limiter call. 'ok', 'limited', 'missing' (no binding: the Free plan may not have it) or 'error' (it threw).
async function limit(binding, key) {
  if (!binding || typeof binding.limit !== 'function') return 'missing';
  try {
    const r = await binding.limit({ key });
    return r && r.success === false ? 'limited' : 'ok';
  } catch {
    return 'error';
  }
}

function record(env, point) {
  try {
    env.API_GATE_STATS?.writeDataPoint?.({
      blobs: [point.mode, point.decision, point.signal, point.route, point.bucket || '', point.limiter || ''],
      doubles: [1, point.d1Ms ?? 0],
      indexes: [point.route],
    });
  } catch { /* counting must never fail a request */ }
}

// The gate for one /api/v1 request (never /api/v1/status). Returns null when the gate is off, else
// { response, headers }: `response` is a refusal to return as it is (only ever when enforcing), `headers` are added
// to the data response (cache-control private; quota headers for a keyed request).
export async function apiGate(request, env, { now = Date.now() } = {}) {
  const mode = gateMode(env);
  if (mode === 'off') return null;
  const enforce = mode === 'enforce';
  const url = new URL(request.url);
  const route = resolveResource(url.pathname).kind || 'invalid';
  const ip = request.headers.get('cf-connecting-ip') || '';
  const day = utcDay(now);
  const point = { mode, route, decision: '', signal: '', bucket: '', limiter: '' };
  const done = (decision, response = null, headers = {}) => {
    point.decision = decision;
    record(env, point);
    return { response: enforce ? response : null, headers: { 'cache-control': 'private, max-age=300, must-revalidate', ...headers } };
  };

  const auth = request.headers.get('authorization');
  if (auth == null) {
    // ---- the website's own calls
    const signal = firstPartySignal(request);
    point.signal = signal;
    if (signal === 'none' || signal === 'cross-site') {
      return done('refused', refusal(request, 401, 'API key required', { 'www-authenticate': 'Bearer' }));
    }
    const rl = await limit(env.SITE_RL, ip);
    point.limiter = rl;
    if (rl === 'limited') {
      point.bucket = await ipBucket(env.IP_BUCKET_SECRET, day, ip);
      return done('would-429-site', refusal(request, 429, 'Too many requests', { 'retry-after': '60' }));
    }
    return done('first-party'); // 'ok', or fail-open on 'missing' / 'error' (counted in the limiter blob)
  }

  // ---- a customer key
  point.signal = 'key';
  const ipRl = await limit(env.KEYED_IP_RL, ip); // before any D1 query, for every Authorization-bearing request
  point.limiter = ipRl;
  if (ipRl === 'limited') {
    point.bucket = await ipBucket(env.IP_BUCKET_SECRET, day, ip);
    return done('keyed-refused-429-ip', refusal(request, 429, 'Too many requests', { 'retry-after': '60' }));
  }
  const m = /^Bearer\s+(\S+)$/i.exec(auth.trim());
  const key = m ? m[1] : '';
  const km = KEY_RE.exec(key);
  if (!km) {
    return done('keyed-refused-401-malformed', refusal(request, 401, 'Invalid API key', { 'www-authenticate': 'Bearer error="invalid_token"' }));
  }
  const db = env.API_DB;
  const unavailable = () => done('d1-error', refusal(request, 503, 'Key check unavailable', { 'retry-after': '30' }));
  if (!db || typeof db.prepare !== 'function') return unavailable();
  let row;
  const t0 = Date.now();
  try {
    row = await db.prepare(SQL_KEY).bind(await sha256Hex(key)).first();
  } catch {
    return unavailable();
  }
  if (!row || row.id !== km[1]) {
    return done('keyed-refused-401-unknown', refusal(request, 401, 'Invalid API key', { 'www-authenticate': 'Bearer error="invalid_token"' }));
  }
  if (row.status !== 'active') return done('keyed-refused-403', refusal(request, 403, 'API key revoked'));
  const keyRl = await limit(env.KEY_RL, row.id);
  if (keyRl === 'limited') return done('keyed-refused-429-burst', refusal(request, 429, 'Too many requests', { 'retry-after': '60' }));
  if (keyRl !== 'ok') point.limiter = `${ipRl}/${keyRl}`;
  let counted;
  try {
    counted = await db.prepare(SQL_COUNT).bind(row.id, day, row.quota).first();
  } catch {
    return unavailable();
  }
  point.d1Ms = Date.now() - t0;
  if (!counted) {
    return done('keyed-refused-429-quota', refusal(request, 429, 'Daily quota used', {
      'retry-after': String(secondsToMidnight(now)), 'x-quota-limit': String(row.quota), 'x-quota-remaining': '0',
    }));
  }
  return done('keyed-ok', null, {
    'x-quota-limit': String(row.quota),
    'x-quota-remaining': String(Math.max(0, row.quota - Number(counted.count))),
  });
}
