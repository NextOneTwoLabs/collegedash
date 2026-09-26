// API keys for direct use of /api/v1/* (issue #345). See docs/data-api.md, "API keys".
// Ported from NextOneTwoLabs/ecnl-dashboard api/apikey.mjs (#93), which is verified on production there;
// only the prefix, the help URL and the binding name differ.
//
// A key is `cdash_live_<id>_<secret>`: id 12 lowercase hex (6 random bytes; not secret, used as the KV key,
// the limiter key and in counts), secret 64 lowercase hex (32 random bytes). KV (binding API_KEYS, namespace
// COLLEGEDASH_API_KEYS) holds `key:<id>` -> {"v":1,"hash":<SHA-256 hex of the whole key>,"label","created",
// "tier","status"}. The key itself is never stored, logged or counted.
//
// Phase 1 of #345 ships this module WITHOUT the API_KEYS binding and without keys: the key door already
// judges every `Authorization` header (a key in the URL is refused with 400, a malformed one with 401) and,
// with no key store to ask, fails closed with 503. Phase 2 adds the binding, the per-key limiter, the owner's
// tool and the first keys.
export const KEY = /^cdash_live_([0-9a-f]{12})_([0-9a-f]{64})$/;
export const HELP_URL = 'https://github.com/NextOneTwoLabs/collegedash/blob/main/docs/data-api.md#api-keys';
const KEY_IN_URL = /cdash_live_([0-9a-f]{12})?/i;
const CACHE_MS = 60 * 1000;      // per-isolate record cache, found and missing
const FOUND_MAX = 500;           // records that exist: bounded by the keys the owner issued
const MISSING_MAX = 200;         // ids with no record: anyone can send these, so kept apart
const KV_CACHE_TTL = 60;         // seconds, KV edge cache (minimum 30)
const enc = new TextEncoder();

const hex = bytes => [...new Uint8Array(bytes)].map(b => b.toString(16).padStart(2, '0')).join('');
export const hashKey = async key => hex(await crypto.subtle.digest('SHA-256', enc.encode(key)));

// Decodes %XX escapes and can never throw: a stray or partial `%` stays as it is. Never decodeURIComponent
// here: its URIError would land in the session fault path, which serves the request ungated. Repeated until
// nothing changes, at most 8 passes, so a key encoded several times over is found too.
export function looseDecode(text) {
  for (let i = 0; i < 8; i++) {
    const next = text.replace(/%([0-9a-f]{2})/gi, (_, h) => String.fromCharCode(parseInt(h, 16)));
    if (next === text) break;
    text = next;
  }
  return text;
}

// Anything key-shaped in the path or query string. -> the match (group 1 the id, if any) or null.
export const keyInUrl = requestUrl => {
  const url = new URL(requestUrl);
  return KEY_IN_URL.exec(looseDecode(url.pathname + url.search));
};

// Workers has crypto.subtle.timingSafeEqual; Node (tests) does not, so fall back to a constant-time loop.
// Both inputs are 64-character hex digests, so the length check leaks nothing.
export function sameDigest(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  const x = enc.encode(a), y = enc.encode(b);
  if (typeof crypto.subtle.timingSafeEqual === 'function') return crypto.subtle.timingSafeEqual(x, y);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

// id -> { rec, at }, for as long as the isolate lives. A revoked key keeps working here for at most CACHE_MS
// after KV shows the change (KV itself can take up to 60 s to propagate). Ids with no record are kept in their
// own small map, oldest out first, so a flood of made-up ids can never push a real key out.
const found = new Map(), missing = new Map();
export const clearKeyCache = () => { found.clear(); missing.clear(); };
function remember(map, max, id, entry) {
  if (map.size >= max) map.delete(map.keys().next().value);
  map.set(id, entry);
}
async function lookup(env, id, nowMs) {
  const hit = found.get(id) || missing.get(id);
  if (hit && nowMs - hit.at < CACHE_MS) return hit.rec;
  if (!env.API_KEYS) throw new Error('API_KEYS binding missing');
  const rec = (await env.API_KEYS.get('key:' + id, { type: 'json', cacheTtl: KV_CACHE_TTL })) || null;
  found.delete(id);
  missing.delete(id);
  if (rec) remember(found, FOUND_MAX, id, { rec, at: nowMs });
  else remember(missing, MISSING_MAX, id, { rec, at: nowMs });
  return rec;
}

// -> { state: 'ok' | 'invalid' | 'revoked' | 'error', id?, reason? }. `id` is set only when a record exists for
// it, so an id a caller made up is never returned. KV missing or failing gives `error`, which fails closed: the
// caller answers 503. It can still throw (e.g. timingSafeEqual on a badly written record); gate() catches that
// and also answers 503.
export async function checkKey(authorization, env, nowMs = Date.now()) {
  const m = /^Bearer +(\S+) *$/i.exec(authorization || '');
  if (!m) return { state: 'invalid', reason: 'scheme' };
  const k = KEY.exec(m[1]);
  if (!k) return { state: 'invalid', reason: 'malformed' };
  const id = k[1];
  let rec;
  try { rec = await lookup(env, id, nowMs); } catch (err) {
    console.error('apikey', err && err.message);   // never the key or the header
    return { state: 'error' };
  }
  if (!rec) return { state: 'invalid', reason: 'unknown' };
  if (rec.v !== 1) return { state: 'invalid', id, reason: 'record' };
  if (rec.status !== 'active') return { state: 'revoked', id, reason: '' };
  if (!sameDigest(await hashKey(m[1]), rec.hash)) return { state: 'invalid', id, reason: 'mismatch' };
  return { state: 'ok', id, reason: '', tier: rec.tier || 'standard' };
}
