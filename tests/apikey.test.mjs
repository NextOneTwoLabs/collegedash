// API keys for direct use of /api/v1 (issue #345). Ported from ecnl-dashboard's tests/apikey.test.mjs (#93; R-A to R-I
// are that plan review's cases), on this site's names and limits. Keys are built at run time, so no key-shaped
// literal is ever in the tree. Phase 1 ships the key door without a key store: these tests give it a fake one;
// production answers 503 to a well-formed key until phase 2 binds API_KEYS.
//
//     node --test tests/apikey.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { gate, mint, COOKIE } from '../api/session.mjs';
import { checkKey, hashKey, sameDigest, looseDecode, keyInUrl, clearKeyCache, KEY, HELP_URL } from '../api/apikey.mjs';
import worker from '../worker.js';

const SECRET = 's'.repeat(40);
const T0 = Date.UTC(2026, 8, 25, 12, 0, 0);
const TOO_MANY = 'Too many requests. Please wait a minute and try again.';
const BAD_KEY = { ok: false, error: 'This API key is not valid or has been revoked.', help: HELP_URL };
const req = (path, headers = {}, method = 'GET') => new Request(`https://college.nextonetwo.com${path}`, { method, headers });
function limiter(limit) {
  const counts = new Map();
  return { counts, async limit({ key }) { const n = (counts.get(key) || 0) + 1; counts.set(key, n); return { success: n <= limit }; } };
}
function sink() { const points = []; return { points, writeDataPoint(p) { points.push(p); } }; }
function kv(records) {
  const reads = [];
  return { reads, records, async get(k, o) { reads.push([k, o]); const r = records.get(k); return r === undefined ? null : JSON.parse(JSON.stringify(r)); } };
}
const hex = n => randomBytes(n).toString('hex');
const fakeKey = () => `cdash_live_${hex(6)}_${hex(32)}`;
// The record shape tools/apikey.mjs writes (tests/apikey-tool.test.mjs checks the tool itself).
async function issue(label = 'test-label') {
  const key = fakeKey();
  const record = { v: 1, hash: await hashKey(key), label, created: '2026-09-25T12:00:00.000Z', tier: 'standard', status: 'active' };
  return { key, id: KEY.exec(key)[1], record };
}
const flip = key => key.slice(0, -1) + (key.endsWith('a') ? 'b' : 'a');
async function setup({ anon = 60, key = 120, extra = {} } = {}) {
  clearKeyCache();
  const good = await issue(), revoked = await issue('revoked-one');
  const store = kv(new Map([['key:' + good.id, good.record], ['key:' + revoked.id, { v: 1, label: 'revoked-one', status: 'revoked', revoked: '2026-09-25T12:00:00.000Z' }]]));
  const env = { SESSION_SECRET: SECRET, RL_SESSION: limiter(180), RL_ANON: limiter(anon), RL_IP: limiter(1200), RL_KEY: limiter(key), API_GATE_STATS: sink(), API_KEYS: store, ...extra };
  return { env, good, revoked, store };
}
const bearer = key => ({ authorization: 'Bearer ' + key });
const outcome = env => env.API_GATE_STATS.points.at(-1);
async function quietly(fn) {
  const original = console.error, logged = [];
  console.error = (...args) => logged.push(args.map(String).join(' '));
  try { return { result: await fn(), logged }; } finally { console.error = original; }
}
const assets = { async fetch(r) {
  const p = new URL(r.url).pathname;
  if (p === '/data/programs/index.json') return new Response(r.method === 'HEAD' ? null : '{"programs":[]}', { headers: { 'content-type': 'application/json', etag: '"c"' } });
  return new Response('<html>fallback</html>', { status: 404, headers: { 'content-type': 'text/html' } });
} };

test('key format, hashing and the constant-time compare', async () => {
  const { key, id, record } = await issue();
  assert.match(key, KEY);
  assert.equal(key.length, 88);
  assert.equal(id.length, 12);
  assert.equal(record.hash, await hashKey(key));
  assert.match(record.hash, /^[0-9a-f]{64}$/);
  assert.ok(sameDigest(record.hash, await hashKey(key)));
  assert.ok(!sameDigest(record.hash, await hashKey(flip(key))));
  assert.ok(!sameDigest(record.hash, record.hash.slice(1)), 'length mismatch');
  assert.ok(!sameDigest(record.hash, undefined));
});

test('S9: on Workers, sameDigest uses crypto.subtle.timingSafeEqual', async () => {
  assert.equal(typeof crypto.subtle.timingSafeEqual, 'undefined', 'Node has no native one; this test stubs it');
  const calls = [];
  crypto.subtle.timingSafeEqual = (a, b) => { calls.push([a, b]); return a.length === b.length && a.every((x, i) => x === b[i]); };
  try {
    const h = await hashKey('x'), g = await hashKey('y');
    assert.equal(sameDigest(h, h), true);
    assert.equal(sameDigest(h, g), false);
    assert.equal(calls.length, 2);
    assert.ok(calls.every(([a, b]) => a instanceof Uint8Array && b instanceof Uint8Array && a.length === 64 && b.length === 64));
    assert.equal(sameDigest(h, h.slice(1)), false);
    assert.equal(calls.length, 2, 'unequal lengths never reach timingSafeEqual');
    // End to end through the gate, with the stub answering.
    const { env, good } = await setup();
    assert.equal((await gate(req('/api/v1/status', bearer(good.key)), env, T0)).session, 'key');
    assert.equal((await gate(req('/api/v1/status', bearer(flip(good.key))), env, T0)).response.status, 401);
    assert.equal(calls.length, 4);
  } finally { delete crypto.subtle.timingSafeEqual; }
});

test('gate order: key in URL, then Authorization, then cookie, then the allowance', async () => {
  const { env, good } = await setup();
  const t = await mint(SECRET, T0);
  assert.deepEqual(await gate(req('/api/v1/programs', bearer(good.key)), env, T0), { session: 'key', cookie: null });
  assert.deepEqual(outcome(env).blobs, ['key-ok', 'programs', 'absent', 'production', good.id, '']);
  assert.deepEqual(outcome(env).indexes, [good.id], 'keyed points are indexed by key id');
  const before = env.API_GATE_STATS.points.length;
  assert.equal((await gate(req('/api/v1/programs', { cookie: `${COOKIE}=${t}` }), env, T0)).session, 'ok');
  assert.equal(env.API_GATE_STATS.points.length, before, 'a routine cookie request writes nothing');
  // S11: a bad key beside a valid cookie is judged as a key and never falls back to the cookie.
  const r = (await gate(req('/api/v1/programs', { ...bearer(flip(good.key)), cookie: `${COOKIE}=${t}` }), env, T0)).response;
  assert.equal(r.status, 401);
  assert.equal((await gate(req('/api/v1/programs'), env, T0)).session, 'none', 'no key, no cookie: the allowance');
  const u = (await gate(req('/api/v1/programs?api_key=' + good.key, { ...bearer(good.key), cookie: `${COOKIE}=${t}` }), env, T0)).response;
  assert.equal(u.status, 400, 'a key in the URL is refused before anything else');
  assert.equal(u.headers.get('x-collegedash-session'), 'key');
  assert.deepEqual(await u.json(), { ok: false, error: 'Send API keys in the Authorization header, never in a URL. Treat this key as exposed and ask for a new one.', help: HELP_URL });
  assert.deepEqual(outcome(env).blobs, ['key-in-url', 'programs', 'absent', 'production', good.id, ''], 'the unverified id is kept: it says which key to revoke');
  assert.deepEqual(outcome(env).indexes, ['key-in-url']);
});

test('bad, malformed, unknown, revoked keys: one 401 JSON body; reasons counted; HEAD without body', async () => {
  const { env, good, revoked, store } = await setup();
  const cases = [
    ['Basic abc', 'key-invalid', '-', 'scheme'], ['Bearer', 'key-invalid', '-', 'scheme'], ['Bearer x ' + good.key, 'key-invalid', '-', 'scheme'],
    ['Bearer ' + good.key.toUpperCase(), 'key-invalid', '-', 'malformed'], ['Bearer ' + good.key + 'x', 'key-invalid', '-', 'malformed'],
    ['Bearer ' + good.key.replace(good.id, '0'.repeat(12)), 'key-invalid', '-', 'unknown'],
    ['Bearer ' + flip(good.key), 'key-invalid', good.id, 'mismatch'],
    ['Bearer ' + revoked.key, 'key-revoked', revoked.id, ''],
  ];
  for (const [authorization, name, id, reason] of cases) {
    const r = (await gate(req('/api/v1/camps', { authorization }), env, T0)).response;
    assert.equal(r.status, 401, authorization.slice(0, 20));
    assert.equal(r.headers.get('cache-control'), 'no-store');
    assert.equal(r.headers.get('x-collegedash-session'), 'key');
    assert.equal(r.headers.get('www-authenticate'), 'Bearer realm="collegedash", error="invalid_token"');
    assert.equal(r.headers.get('set-cookie'), null);
    assert.deepEqual(await r.json(), BAD_KEY, 'every reason looks the same to the caller');
    assert.deepEqual(outcome(env).blobs.slice(0, 1).concat(outcome(env).blobs.slice(4)), [name, id, reason]);
  }
  assert.equal((await gate(req('/api/v1/camps', { authorization: 'bearer ' + good.key }), env, T0)).session, 'key', 'the scheme is case-insensitive');
  assert.equal(env.RL_KEY.counts.get('key:' + good.id), 1, 'only the valid call used the key allowance');
  assert.ok(store.reads.length <= 3, 'scheme and malformed errors never read KV');
  // S11: HEAD with a bad key: 401 with no body.
  const h = (await gate(req('/api/v1/camps', { authorization: 'Bearer nope' }, 'HEAD'), env, T0)).response;
  assert.equal(h.status, 401);
  assert.equal(await h.text(), '');
});

test('over the per-key limit: 429 "key" without the key hint; keyed calls count toward RL_IP', async () => {
  const { env, good } = await setup({ key: 3 });
  for (let i = 0; i < 3; i++) assert.equal((await gate(req('/api/v1/status', bearer(good.key)), env, T0)).session, 'key');
  const r = (await gate(req('/api/v1/status', bearer(good.key)), env, T0)).response;
  assert.equal(r.status, 429);
  assert.equal(r.headers.get('x-collegedash-session'), 'key');
  assert.equal(r.headers.get('retry-after'), '60');
  assert.equal(r.headers.get('link'), null);
  assert.deepEqual(await r.json(), { ok: false, error: TOO_MANY });
  assert.deepEqual(outcome(env).blobs, ['limited-key', 'status', 'absent', 'production', good.id, '']);
  assert.deepEqual([...env.RL_KEY.counts.keys()], ['key:' + good.id], 'limiter keyed by id, never the key');
  assert.equal(env.RL_IP.counts.get('ip:unknown'), 4, 'every keyed call counts toward RL_IP');
});

test('invalid keys never spend a real key\'s allowance', async () => {
  const { env, good } = await setup({ key: 2 });
  for (let i = 0; i < 20; i++) await gate(req('/api/v1/status', bearer(flip(good.key))), env, T0);
  assert.equal(env.RL_KEY.counts.size, 0);
  assert.equal((await gate(req('/api/v1/status', bearer(good.key)), env, T0)).session, 'key');
});

test('anonymous allowance: over it, 429 "none" with a bare help URL and a Link header', async () => {
  const { env } = await setup({ anon: 2 });
  for (let i = 0; i < 2; i++) assert.equal((await gate(req('/api/v1/status'), env, T0)).session, 'none');
  const r = (await gate(req('/api/v1/status'), env, T0)).response;
  assert.equal(r.status, 429);
  assert.equal(r.headers.get('x-collegedash-session'), 'none', 'still triggers the page renewal');
  assert.equal(r.headers.get('link'), `<${HELP_URL}>; rel="help"`);
  assert.deepEqual(await r.json(), { ok: false, error: TOO_MANY, help: HELP_URL }, 'the text the page shows is unchanged');
  assert.match(HELP_URL, /^https:\/\/github\.com\/NextOneTwoLabs\/collegedash\/blob\/main\/docs\/data-api\.md#api-keys$/);
  assert.match(readFileSync('docs/data-api.md', 'utf8'), /^## API keys\r?$/m, 'the anchor the help URL names exists');
  const { env: e2 } = await setup({ extra: { RL_SESSION: limiter(0) } });
  const s = (await gate(req('/api/v1/status', { cookie: `${COOKIE}=${await mint(SECRET, T0)}` }), e2, T0)).response;
  assert.equal(s.status, 429);
  assert.equal(s.headers.get('link'), null, 'a session-tier 429 carries no hint');
  assert.deepEqual(await s.json(), { ok: false, error: TOO_MANY });
});

test('isolate cache: one KV read per id per minute, misses too; revocation within the cache window', async () => {
  const { env, good, store } = await setup();
  for (let i = 0; i < 50; i++) await gate(req('/api/v1/status', bearer(good.key)), env, T0 + i * 1000);
  assert.equal(store.reads.length, 1);
  assert.deepEqual(store.reads[0], ['key:' + good.id, { type: 'json', cacheTtl: 60 }]);
  const unknown = good.key.replace(good.id, 'f'.repeat(12));
  for (let i = 0; i < 50; i++) await gate(req('/api/v1/status', bearer(unknown)), env, T0);
  assert.equal(store.reads.length, 2, 'a missing record is cached');
  for (let i = 0; i < 50; i++) await gate(req('/api/v1/status', bearer('cdash_live_zz')), env, T0);
  assert.equal(store.reads.length, 2, 'a malformed key never reads KV');
  store.records.set('key:' + good.id, { v: 1, label: 'test-label', status: 'revoked', revoked: '2026-09-25T12:00:30.000Z' });
  assert.equal((await gate(req('/api/v1/status', bearer(good.key)), env, T0 + 59_000)).session, 'key', 'cached for up to 60 s');
  assert.equal((await gate(req('/api/v1/status', bearer(good.key)), env, T0 + 61_000)).response.status, 401);
});

test('KV missing or failing: keyed requests fail closed (503 JSON, id "-"); cookie and allowance unaffected', async () => {
  for (const API_KEYS of [undefined, { async get() { throw new Error('KV GET failed: 429 Too Many Requests'); } }]) {
    const { env, good } = await setup({ extra: { API_KEYS } });
    const { result, logged } = await quietly(() => gate(req('/api/v1/status', bearer(good.key)), env, T0));
    const r = result.response;
    assert.equal(r.status, 503);
    assert.equal(r.headers.get('x-collegedash-session'), 'key');
    assert.equal(r.headers.get('retry-after'), '60');
    assert.deepEqual(await r.json(), { ok: false, error: 'API keys cannot be checked right now. Please try again later.' });
    assert.deepEqual(outcome(env).blobs, ['key-error', 'status', 'absent', 'production', '-', ''], 'M3: no id from the request is stored');
    assert.deepEqual(outcome(env).indexes, ['key-error']);
    assert.ok(logged.length === 1 && logged[0].startsWith('apikey') && !logged[0].includes(good.key.slice(24)), 'logged without the key');
    assert.equal((await gate(req('/api/v1/status', { cookie: `${COOKIE}=${await mint(SECRET, T0)}` }), env, T0)).session, 'ok');
    assert.equal((await gate(req('/api/v1/status'), env, T0)).session, 'none');
  }
});

test('a throw anywhere on the key path answers 503, never the fail-open "error"', async () => {
  const { env, good } = await setup({ extra: { API_GATE_STATS: { writeDataPoint() { throw new Error('quota'); } } } });
  // Reading the Authorization header throws: only the key path reads it.
  const request = new Proxy(req('/api/v1/programs', bearer(good.key)), { get(t, prop) {
    if (prop === 'headers') return new Proxy(t.headers, { get(h, p) {
      if (p === 'get') return name => { if (name === 'authorization') throw new Error('boom'); return h.get(name); };
      const v = Reflect.get(h, p, h); return typeof v === 'function' ? v.bind(h) : v;
    } });
    const v = Reflect.get(t, prop, t); return typeof v === 'function' ? v.bind(t) : v;
  } });
  const { result, logged } = await quietly(() => worker.fetch(request, { ...env, ASSETS: assets }));
  assert.equal(result.status, 503);
  assert.equal(result.headers.get('x-collegedash-session'), 'key');
  assert.ok(logged.every(l => !l.includes(good.key.slice(24))));
});

test('keys work with sessions off (no SESSION_SECRET); a throwing RL_KEY or RL_IP serves a proven key', async () => {
  const { env, good } = await setup({ extra: { SESSION_SECRET: undefined } });
  assert.equal((await gate(req('/api/v1/status', bearer(good.key)), env, T0)).session, 'key');
  assert.equal((await gate(req('/api/v1/status', { authorization: 'Bearer junk' }), env, T0)).response.status, 401);
  assert.equal((await gate(req('/api/v1/status'), env, T0)).session, 'off');
  const down = { async limit() { throw new Error('down'); } };
  const { env: e2, good: g2 } = await setup({ extra: { RL_KEY: down, RL_IP: down } });
  assert.equal((await gate(req('/api/v1/status', bearer(g2.key)), e2, T0)).session, 'key');
  assert.equal((await gate(req('/api/v1/status', bearer(flip(g2.key))), e2, T0)).response.status, 401, 'a limiter fault never skips the key check');
});

test('worker end to end: keyed data, 401 JSON never HTML, no key material anywhere in responses or counts', async () => {
  const { env, good } = await setup();
  const e = { ...env, ASSETS: assets };
  const seen = [];
  for (const [path, headers, status, session] of [
    ['/api/v1/programs', bearer(good.key), 200, 'key'], ['/api/v1/nope', bearer(good.key), 404, 'key'],
    ['/api/v1/programs', bearer(flip(good.key)), 401, 'key'], ['/api/v1/programs?k=' + good.key, {}, 400, 'key'],
    ['/api/v1/' + good.key, {}, 400, 'key'], ['/api/v1/programs', {}, 200, 'none'],
  ]) {
    const r = await worker.fetch(req(path, headers), e);
    assert.equal(r.status, status, path.slice(0, 30));
    assert.equal(r.headers.get('x-collegedash-session'), session);
    assert.match(r.headers.get('content-type'), /application\/json/);
    assert.equal(r.headers.get('set-cookie'), null);
    seen.push(JSON.stringify([...r.headers]), await r.text());
  }
  const secret = good.key.slice(24);
  const all = seen.join('\n') + JSON.stringify(e.API_GATE_STATS.points) + JSON.stringify([...e.RL_KEY.counts.keys(), ...e.RL_IP.counts.keys()]);
  assert.ok(!all.includes(secret), 'the secret part appears nowhere');
  assert.ok(!all.includes(good.record.hash), 'nor its hash');
});

// ---- The Reviewer's cases (R-A to R-I), against the fixes ----

test('R-A / M1: a key anywhere in the URL, plain or encoded, in the query or the path, gets 400', async () => {
  const { env, good } = await setup({ anon: 0 });
  const k = good.key;
  for (const [name, path] of [
    ['plain', '/api/v1/status?k=' + k], ['upper', '/api/v1/status?k=' + k.toUpperCase()],
    ['%5F', '/api/v1/status?k=' + k.replace(/_/g, '%5F')], ['%5f', '/api/v1/status?k=' + k.replace(/_/g, '%5f')],
    ['%63', '/api/v1/status?k=%63' + k.slice(1)], ['double-encoded', '/api/v1/status?k=' + k.replace(/_/g, '%255F')],
    ['quadruple-encoded', '/api/v1/status?k=' + k.replace(/_/g, '%25252525' + '5F')],
    ['8 times encoded', '/api/v1/status?k=' + k.replace(/_/g, '%' + '25'.repeat(7) + '5F')],
    ['path', '/api/v1/' + k], ['path %5F', '/api/v1/' + k.replace(/_/g, '%5F')],
    ['encodeURIComponent', '/api/v1/status?k=' + encodeURIComponent(k)], ['URLSearchParams', '/api/v1/status?' + new URLSearchParams({ k })],
    ['beside a stray %', '/api/v1/status?x=%&k=' + k.replace(/_/g, '%5F')], ['fake %5F key', '/api/v1/status?k=' + fakeKey().replace(/_/g, '%5F')],
  ]) {
    const r = (await gate(req(path), env, T0)).response;
    assert.equal(r?.status, 400, name);
    assert.equal(outcome(env).blobs[0], 'key-in-url', name);
  }
});

test('R-G / M1: undecodable escapes (?x=%, ?x=%E0%A4%A) stay gated: 429 over the allowance, never "error"', async () => {
  for (const q of ['?x=%', '?x=%E0%A4%A', '?x=%ZZ', '?x=%%35F', '?%']) {
    assert.doesNotThrow(() => looseDecode(q));
    assert.equal(keyInUrl('https://college.nextonetwo.com/api/v1/status' + q), null);
    const { env } = await setup({ anon: 1 });
    const e = { ...env, ASSETS: assets };
    const first = await worker.fetch(req('/api/v1/programs' + q), e);
    assert.equal(first.status, 200, q);
    assert.equal(first.headers.get('x-collegedash-session'), 'none', q);
    const second = await worker.fetch(req('/api/v1/programs' + q), e);
    assert.equal(second.status, 429, q);
    assert.equal(second.headers.get('x-collegedash-session'), 'none', q);
    assert.ok(!e.API_GATE_STATS.points.some(p => p.blobs[0] === 'gate-error'), q);
  }
  assert.equal(looseDecode('a%5Fb%255F%'), 'a_b_%');
  // Until nothing changes, at most 8 passes: 8 times encoded is decoded, 9 times is not.
  assert.equal(looseDecode('%' + '25'.repeat(7) + '5F'), '_');
  assert.equal(looseDecode('%' + '25'.repeat(8) + '5F'), '%5F');
  const flood = '%25'.repeat(200_000);
  assert.doesNotThrow(() => looseDecode(flood));
});

test('R-B / M3: key-in-url keeps the unverified id; key-error, unknown and IP-refused keys store "-"', async () => {
  const { env } = await setup();
  await gate(req('/api/v1/status?x=cdash_live_ABCDEFabcdef'), env, T0);
  assert.deepEqual(outcome(env).blobs.slice(4), ['abcdefabcdef', '']);
  await gate(req('/api/v1/status?x=cdash_live_'), env, T0);
  assert.deepEqual(outcome(env).blobs.slice(4), ['-', '']);
  const made = fakeKey(), madeId = KEY.exec(made)[1];
  await gate(req('/api/v1/status', bearer(made)), env, T0);
  assert.deepEqual(outcome(env).blobs.slice(4), ['-', 'unknown']);
  const { env: e2 } = await setup({ extra: { API_KEYS: { async get() { throw new Error('down'); } } } });
  await quietly(() => gate(req('/api/v1/status', bearer(made)), e2, T0));
  assert.deepEqual(outcome(e2).blobs.slice(4), ['-', '']);
  const { env: e3 } = await setup({ extra: { RL_IP: limiter(0) } });
  await gate(req('/api/v1/status', bearer(made)), e3, T0);
  assert.deepEqual(outcome(e3).blobs, ['limited-ip', 'status', 'absent', 'production', '-', 'key']);
  for (const e of [env, e2, e3]) assert.ok(!JSON.stringify(e.API_GATE_STATS.points).includes(madeId), 'a made-up id sent as a header is never stored');
});

test('R-C / S4: an IP over RL_IP gets 429 before its key is judged, with no KV read', async () => {
  const { env, good, store } = await setup({ extra: { RL_IP: limiter(0) } });
  for (let i = 0; i < 20; i++) {
    const r = (await gate(req('/api/v1/status', bearer(fakeKey())), env, T0)).response;
    assert.equal(r.status, 429);
    assert.equal(r.headers.get('x-collegedash-session'), 'key');
    assert.equal(r.headers.get('link'), null);
  }
  assert.equal((await gate(req('/api/v1/status', bearer(good.key)), env, T0)).response.status, 429);
  assert.equal(store.reads.length, 0);
  assert.equal(env.RL_KEY.counts.size, 0, 'an IP-refused key does not spend its own allowance');
});

test('R-D / S5: 600 made-up ids never push a real key out of the isolate cache', async () => {
  const { env, good, revoked, store } = await setup();
  await gate(req('/api/v1/status', bearer(good.key)), env, T0);
  await gate(req('/api/v1/status', bearer(revoked.key)), env, T0);
  const reads = id => store.reads.filter(([k]) => k === 'key:' + id).length;
  for (let i = 0; i < 600; i++) await gate(req('/api/v1/status', bearer(fakeKey())), env, T0 + 1000);
  assert.equal(store.reads.length, 602, 'each made-up id costs one read, as any request would');
  assert.equal((await gate(req('/api/v1/status', bearer(good.key)), env, T0 + 2000)).session, 'key');
  assert.equal((await gate(req('/api/v1/status', bearer(revoked.key)), env, T0 + 2000)).response.status, 401);
  assert.equal(reads(good.id), 1, 'no fresh KV read for the real key');
  assert.equal(reads(revoked.id), 1, 'nor for a revoked one');
  // Misses are still cached, oldest out first: the latest made-up ids read KV once each.
  const last = fakeKey();
  for (let i = 0; i < 5; i++) await gate(req('/api/v1/status', bearer(last)), env, T0 + 3000);
  assert.equal(reads(KEY.exec(last)[1]), 1);
});

test('R-E: odd KV records never serve', async () => {
  const good = await issue();
  const shapes = {
    toolRevoke: [{ v: 1, label: 'x', status: 'revoked', revoked: '2026-09-25T12:00:00Z' }, 'revoked'],
    noStatus: [{ v: 1, hash: good.record.hash }, 'revoked'],
    activeNoHash: [{ v: 1, status: 'active' }, 'invalid'],
    v2: [{ ...good.record, v: 2 }, 'invalid'],
    string: ['active', 'invalid'],
    number: [1, 'invalid'],
  };
  for (const [name, [rec, state]] of Object.entries(shapes)) {
    clearKeyCache();
    assert.equal((await checkKey('Bearer ' + good.key, { API_KEYS: kv(new Map([['key:' + good.id, rec]])) }, T0)).state, state, name);
  }
  clearKeyCache();
  assert.equal((await checkKey('Bearer ' + good.key, { API_KEYS: kv(new Map([['key:' + good.id, good.record]])) }, T0)).state, 'ok');
});

test('R-F: odd Authorization headers', async () => {
  const { env, good } = await setup();
  for (const [name, h, expected] of [
    ['empty', '', 401], ['two combined', `Bearer ${good.key}, Bearer ${good.key}`, 401], ['tab', 'Bearer\t' + good.key, 401],
    ['double space', 'Bearer  ' + good.key, 'key'], ['trailing space', 'Bearer ' + good.key + ' ', 'key'],
  ]) {
    const headers = new Headers();
    headers.set('authorization', h);
    const g = await gate(new Request('https://college.nextonetwo.com/api/v1/status', { headers }), env, T0);
    assert.equal(g.response ? g.response.status : g.session, expected, name);
  }
});

test('R-I: refusal reasons differ in time only by microseconds and not at all in the answer', async () => {
  const { env, good, revoked } = await setup();
  const out = {};
  for (const [name, k] of [['unknown', good.key.replace(good.id, 'f'.repeat(12))], ['mismatch', flip(good.key)], ['revoked', revoked.key], ['ok', good.key]]) {
    const first = await checkKey('Bearer ' + k, env, T0);
    assert.equal(first.state === 'ok', name === 'ok');
    const t = process.hrtime.bigint();
    for (let i = 0; i < 500; i++) await checkKey('Bearer ' + k, env, T0);
    out[name] = Number(process.hrtime.bigint() - t) / 500 / 1000;
  }
  // Ids are not secret, and the bodies are identical (tested above), so this is recorded, not bounded.
  assert.ok(Object.values(out).every(us => us > 0 && us < 5000), JSON.stringify(out));
});

test('phase 1: wrangler.toml declares no key store and no RL_KEY yet; namespace ids are unique; well-formed keys answer 503', async () => {
  const toml = readFileSync('wrangler.toml', 'utf8').replace(/\r\n/g, '\n');
  assert.doesNotMatch(toml, /^binding = "API_KEYS"$/m, 'phase 2 adds the key store');
  assert.doesNotMatch(toml, /^name = "RL_KEY"/m, 'phase 2 adds RL_KEY (namespace_id 3464)');
  const ids = [...toml.matchAll(/^namespace_id = "(\d+)"$/gm)].map(m => m[1]);
  assert.equal(new Set(ids).size, ids.length, 'each limiter has its own namespace_id');
  const { env, good } = await setup({ extra: { API_KEYS: undefined, RL_KEY: undefined } });
  const { result } = await quietly(() => gate(req('/api/v1/programs', bearer(good.key)), env, T0));
  assert.equal(result.response.status, 503, 'fails closed until phase 2');
  assert.equal((await gate(req('/api/v1/programs', { authorization: 'Bearer junk' }), env, T0)).response.status, 401, 'a malformed key is refused without a store');
});

// The files to scan under `dir`, relative with `/`: git's tracked and untracked files, or, when
// git can't list them (a `git archive` copy, no git), a walk that skips .git and node_modules.
function treeFiles(dir, gitEnv = {}) {
  let files;
  try {
    files = execFileSync('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard'],
      { cwd: dir, env: { ...process.env, ...gitEnv }, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, stdio: ['ignore', 'pipe', 'ignore'] }).split('\0');
  } catch {
    files = [];
    const walk = rel => { for (const entry of readdirSync(join(dir, rel), { withFileTypes: true })) {
      if (entry.name === '.git' || entry.name === 'node_modules') continue;
      const p = rel ? rel + '/' + entry.name : entry.name;
      if (entry.isDirectory()) walk(p); else if (entry.isFile()) files.push(p);
    } };
    walk('');
  }
  return files.filter(p => p && !/^(public\/archive|reconstructed|export)\//.test(p));
}
const KEY_SHAPE = new RegExp('cdash' + '_live_[0-9a-f]{12}_[0-9a-f]{64}', 'i');
const keyShaped = (dir, files) => files.filter(p => {
  try { const f = join(dir, p); return statSync(f).size < 2_000_000 && KEY_SHAPE.test(readFileSync(f, 'latin1')); } catch { return false; }
});

test('no key-shaped string anywhere in the tree (N3: if this ever fails, revoke that key first)', () => {
  const files = treeFiles('.');
  assert.ok(files.includes('api/apikey.mjs'));
  assert.deepEqual(keyShaped('.', files), []);
});

test('the key scan walks the folder when git cannot list it, skipping .git and node_modules', () => {
  const dir = mkdtempSync(join(tmpdir(), 'cdash-keyscan-test-'));
  try {
    const plant = (p, text) => { mkdirSync(join(dir, p, '..'), { recursive: true }); writeFileSync(join(dir, p), text); };
    plant('api/apikey.mjs', '// clean');
    plant('docs/leak.md', 'token: ' + fakeKey().toUpperCase());
    plant('.git/objects/x', fakeKey());
    plant('node_modules/pkg/y.js', fakeKey());
    plant('public/archive/z.json', fakeKey());
    const files = treeFiles(dir, { GIT_DIR: join(dir, 'no-such-git-dir') });
    assert.deepEqual(files.sort(), ['api/apikey.mjs', 'docs/leak.md'], 'fell back to the walk');
    assert.deepEqual(keyShaped(dir, files), ['docs/leak.md']);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

// #345 round-4 plan, change 3: the keyed variant of the `?x=%` test. A bad key together with a hostile URL and a
// malformed or missing client address must end in 400 (a key in the URL) or 401 (a bad key) with a key store, or
// 400 / 503 without one; never served, never `error`, `ok` or `none`. That pins "nothing attacker-controlled throws
// into the fail-open session path" for the key door, and keeps it pinned if anything is later added before the
// Authorization branch.
test('keyed hostile-URL table: bad key x hostile URL x hostile client address -> 400, 401 or 503, never served', async () => {
  const made = fakeKey();
  const auths = ['Bearer junk', 'Bearer ' + flip(made), 'Basic x', 'Bearer ' + made.toUpperCase()];
  const urlKey = n => { let s = made.replace(/_/g, '%5F'); for (let i = 1; i < n; i++) s = s.replace(/%/g, '%25'); return s; };
  const paths = ['/api/v1/programs?x=%', '/api/v1/programs?x=%E0%A4%A', '/api/v1/%', '/api/v1/programs?k=' + urlKey(1),
    '/api/v1/programs?k=' + urlKey(3), '/api/v1/programs?k=' + urlKey(8), '/api/v1/' + urlKey(1)];
  const ips = [undefined, '', 'not-an-ip', '999.1.1.1', 'x'.repeat(4000), '::ffff:zz.1', '%E0%A4%A'];
  const keyInPath = p => /%5F|%25/.test(p);
  const stores = [['store', {}], ['no store', { API_KEYS: undefined }], ['throwing store', { API_KEYS: { async get() { throw new Error('down'); } } }],
    ['sessions off', { SESSION_SECRET: undefined }]];
  let cases = 0;
  for (const [label, extra] of stores) {
    const { env } = await setup({ extra });
    const reads = { n: 0 };
    const e = { ...env, ASSETS: { async fetch(r) { reads.n++; return assets.fetch(r); } } };
    for (const authorization of auths) for (const path of paths) for (const ip of ips) {
      const headers = { authorization };
      if (ip !== undefined) headers['cf-connecting-ip'] = ip;
      const { result: r } = await quietly(() => worker.fetch(req(path, headers), e));
      const expected = keyInPath(path) ? [400] : label === 'store' || label === 'sessions off' ? [401] : [401, 503];
      assert.ok(expected.includes(r.status), `${label} | ${authorization.slice(0, 14)} | ${path.slice(0, 40)} | ${String(ip).slice(0, 12)} -> ${r.status}`);
      assert.equal(r.headers.get('x-collegedash-session'), 'key', `${label} ${path}`);
      cases++;
    }
    assert.equal(reads.n, 0, `${label}: no request in the table was served data`);
    assert.ok(!env.API_GATE_STATS.points.some(p => ['gate-error', 'key-ok', 'anon-missing'].includes(p.blobs[0])), `${label}: never error, ok or none`);
  }
  assert.equal(cases, 4 * 4 * 7 * 7);
});
