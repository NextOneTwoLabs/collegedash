// The /api/v1 gate (issue #345, api/access.mjs), through worker.fetch with fakes and no network:
//
//     node --test tests/api_access.test.mjs
//
// - ASSETS serves public/ from disk, as in tests/data_api.test.mjs.
// - API_DB is a real SQLite database (node:sqlite) with api/schema.sql, wrapped in D1's prepare/bind/first API, so
//   the quota upsert is run as SQL, not imitated.
// - SITE_RL, KEYED_IP_RL and KEY_RL are counting fakes that can be told to refuse, to throw, or be absent.
// - API_GATE_STATS records every data point written.
// Keys are made up here at run time; no key value exists in any file.
//
// Production ships API_GATE = "report" (checked below). Enforcement is forced on HERE, in the test environment only,
// to prove the refusals PR 2 will switch on.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import worker from '../worker.js';
import { KEY_RE, SQL_COUNT, sha256Hex, ipBucket, firstPartySignal } from '../api/access.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const PUBLIC = path.join(ROOT, 'public');
const HOST = 'https://college.nextonetwo.com';
const GATED = ['/api/v1/programs', '/api/v1/programs/ucla', '/api/v1/camps', '/api/v1/trends', '/api/v1/commitments'];
const SITE = { 'x-collegedash-client': 'web' };

function assets() {
  return {
    async fetch(req) {
      const u = new URL(req.url);
      const file = path.join(PUBLIC, decodeURIComponent(u.pathname).replace(/^\//, ''));
      if (!file.startsWith(PUBLIC) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return new Response(null, { status: 404 });
      return new Response(fs.readFileSync(file), { status: 200, headers: { 'content-type': 'application/json; charset=utf-8', etag: '"x"' } });
    },
  };
}

// D1's surface over node:sqlite: prepare(sql).bind(...).first() / .run(). Counts queries.
function d1() {
  const db = new DatabaseSync(':memory:');
  db.exec(fs.readFileSync(path.join(ROOT, 'api', 'schema.sql'), 'utf8'));
  const api = {
    queries: 0, fail: false, db,
    prepare(sql) {
      let args = [];
      const st = { bind(...a) { args = a; return st; },
        async first() { api.queries++; if (api.fail) throw new Error('D1 down'); return db.prepare(sql).get(...args) ?? null; },
        async run() { api.queries++; if (api.fail) throw new Error('D1 down'); const r = db.prepare(sql).run(...args); return { meta: { changes: r.changes } }; } };
      return st;
    },
  };
  return api;
}

function limiter(max = Infinity) {
  const seen = new Map();
  return { calls: 0, throws: false, async limit({ key }) {
    this.calls++;
    if (this.throws) throw new Error('rate limiter down');
    const n = (seen.get(key) || 0) + 1; seen.set(key, n); return { success: n <= max };
  } };
}

function env(mode, over = {}) {
  const points = [];
  return {
    API_GATE: mode, ASSETS: assets(), FEEDBACK: { put() { } },
    API_DB: d1(), SITE_RL: limiter(), KEYED_IP_RL: limiter(), KEY_RL: limiter(),
    IP_BUCKET_SECRET: 'test-only-secret-not-a-real-one',
    API_GATE_STATS: { points, writeDataPoint(p) { points.push(p); } },
    ...over,
  };
}

function makeKey() {
  const abc = 'abcdefghijklmnopqrstuvwxyz0123456789';
  const id = Array.from(crypto.getRandomValues(new Uint8Array(12)), b => abc[b % abc.length]).join('');
  const secret = Buffer.from(crypto.getRandomValues(new Uint8Array(32))).toString('base64url');
  return { id, key: `cdk_${id}_${secret}` };
}

async function addKey(e, { status = 'active', quota = 5 } = {}) {
  const k = makeKey();
  e.API_DB.db.prepare('INSERT INTO keys (id, hash, label, created, status, quota) VALUES (?, ?, ?, ?, ?, ?)')
    .run(k.id, await sha256Hex(k.key), 'test', '2026-09-25T00:00:00Z', status, quota);
  return k;
}

const get = (e, p, headers = {}, init = {}) => worker.fetch(new Request(HOST + p, { headers: { 'cf-connecting-ip': '203.0.113.9', ...headers }, ...init }), e);
const bearer = k => ({ authorization: `Bearer ${k}` });
const decisions = e => e.API_GATE_STATS.points.map(p => p.blobs[1]);
const signals = e => e.API_GATE_STATS.points.map(p => p.blobs[2]);

// ---------- production config ----------
test('wrangler.toml ships the gate in report mode, with the site limit and the stats binding', () => {
  const toml = fs.readFileSync(path.join(ROOT, 'wrangler.toml'), 'utf8');
  assert.match(toml, /^API_GATE = "report"$/m, 'PR 1 must ship report mode (enforcement is its own PR, owner decision 8)');
  assert.match(toml, /binding = "API_GATE_STATS"/);
  // the Rate Limiting bindings failed the Workers Build on the Free plan (#355); the gate runs without them
  assert.doesNotMatch(toml, /^\[\[ratelimits\]\]/m, 'a [[ratelimits]] block is back: confirm the plan supports it first');
  assert.doesNotMatch(toml, /^\s*IP_BUCKET_SECRET\s*=/m, 'the HMAC key is a Worker secret, never a var');
  assert.doesNotMatch(toml, /cdk_[a-z0-9]{12}_[A-Za-z0-9_-]{43}/, 'a key value in wrangler.toml');
});

test('getJSON sends X-CollegeDash-Client: web on every call', () => {
  const html = fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8');
  const fn = html.slice(html.indexOf('async function getJSON('), html.indexOf('function loadFailedHtml('));
  assert.match(fn, /headers: \{ 'X-CollegeDash-Client': 'web', \.\.\.\(o\.headers \|\| \{\}\) \}/);
});

// ---------- enforcement, forced on in this test environment only ----------
test('enforce: no key and no first-party signal is refused with 401 on every data route, and status stays open', async () => {
  const e = env('enforce');
  for (const p of GATED) {
    const r = await get(e, p);
    assert.equal(r.status, 401, p);
    assert.equal(r.headers.get('www-authenticate'), 'Bearer');
    const body = await r.json();
    assert.equal(body.error, 'API key required');
    assert.equal(body.docs, 'https://college.nextonetwo.com/#/api');
  }
  assert.equal((await get(e, '/api/v1/status')).status, 200, '/api/v1/status is open');
  assert.equal(e.API_GATE_STATS.points.length, GATED.length, 'status is not counted');
});

test('enforce: each first-party signal is served; an explicit cross-site or same-site fetch is not', async () => {
  const e = env('enforce');
  assert.equal((await get(e, '/api/v1/programs', SITE)).status, 200, 'client header');
  assert.equal((await get(e, '/api/v1/programs', { 'sec-fetch-site': 'same-origin' })).status, 200, 'Sec-Fetch-Site');
  assert.equal((await get(e, '/api/v1/programs', { referer: `${HOST}/#/p/ucla` })).status, 200, 'same-origin Referer');
  for (const sfs of ['cross-site', 'same-site']) {
    assert.equal((await get(e, '/api/v1/programs', { ...SITE, 'sec-fetch-site': sfs })).status, 401, `${sfs} with the header`);
  }
  assert.equal((await get(e, '/api/v1/programs', { 'sec-fetch-site': 'none' })).status, 401, 'Sec-Fetch-Site: none');
  assert.equal((await get(e, '/api/v1/programs', { referer: 'https://elsewhere.example/page' })).status, 401, 'another origin');
  assert.deepEqual(signals(e), ['client-header', 'sec-fetch-site', 'referer', 'cross-site', 'cross-site', 'none', 'none']);
  const ok = await get(e, '/api/v1/programs', SITE);
  assert.equal(ok.headers.get('cache-control'), 'private, max-age=300, must-revalidate', 'gated data is private');
});

test('enforce: the site path fails open when the rate limiter is missing or throws, and 429s over the limit', async () => {
  const missing = env('enforce', { SITE_RL: undefined });
  assert.equal((await get(missing, '/api/v1/programs', SITE)).status, 200, 'no binding');
  const throwing = env('enforce'); throwing.SITE_RL.throws = true;
  assert.equal((await get(throwing, '/api/v1/programs', SITE)).status, 200, 'limiter throws');
  assert.deepEqual(missing.API_GATE_STATS.points.map(p => p.blobs[5]), ['missing']);
  assert.deepEqual(throwing.API_GATE_STATS.points.map(p => p.blobs[5]), ['error']);
  const e = env('enforce', { SITE_RL: limiter(2) });
  assert.equal((await get(e, '/api/v1/programs', SITE)).status, 200);
  assert.equal((await get(e, '/api/v1/programs', SITE)).status, 200);
  const r = await get(e, '/api/v1/programs', SITE);
  assert.equal(r.status, 429);
  assert.equal(r.headers.get('retry-after'), '60');
  assert.equal(e.API_DB.queries, 0, 'the site path never reads D1');
});

test('enforce: a gate that throws on a keyless request still serves it', async () => {
  const e = env('enforce');
  Object.defineProperty(e, 'SITE_RL', { get() { throw new Error('binding exploded'); } });
  const orig = console.error; const logged = []; console.error = (...a) => logged.push(a.join(' '));
  try {
    assert.equal((await get(e, '/api/v1/programs', SITE)).status, 200);
  } finally { console.error = orig; }
  assert.ok(logged.every(l => !/203\.0\.113|x-collegedash|authorization/i.test(l)), 'the log names only the error');
});

test('enforce: keys - valid, malformed (no D1), unknown, revoked, per-IP limit before D1, D1 down', async () => {
  const e = env('enforce');
  const good = await addKey(e, { quota: 5 });
  const r = await get(e, '/api/v1/programs', bearer(good.key));
  assert.equal(r.status, 200);
  assert.equal(r.headers.get('x-quota-limit'), '5');
  assert.equal(r.headers.get('x-quota-remaining'), '4');
  assert.equal(r.headers.get('cache-control'), 'private, max-age=300, must-revalidate');

  const before = e.API_DB.queries;
  for (const bad of ['cdk_short', 'not-a-key', `${good.key}x`, `Basic ${good.key}`]) {
    const res = await get(e, '/api/v1/programs', { authorization: bad.startsWith('Basic') ? bad : `Bearer ${bad}` });
    assert.equal(res.status, 401, bad);
  }
  assert.equal(e.API_DB.queries, before, 'a malformed key never reaches D1');
  assert.equal((await get(e, '/api/v1/programs', bearer(makeKey().key))).status, 401, 'unknown key');
  const revoked = await addKey(e, { status: 'revoked' });
  assert.equal((await get(e, '/api/v1/programs', bearer(revoked.key))).status, 403, 'revoked key');

  const spam = env('enforce', { KEYED_IP_RL: limiter(3) });
  for (let i = 0; i < 3; i++) await get(spam, '/api/v1/programs', bearer(makeKey().key));
  const q0 = spam.API_DB.queries;
  const limited = await get(spam, '/api/v1/programs', bearer(makeKey().key));
  assert.equal(limited.status, 429, 'the per-IP limit on keyed requests');
  assert.equal(spam.API_DB.queries, q0, 'and it runs before any D1 query');
  assert.ok(spam.API_GATE_STATS.points.at(-1).blobs[4].length === 8, 'a would-be IP 429 carries an 8-character bucket');

  const down = env('enforce');
  const k = await addKey(down);
  down.API_DB.fail = true;
  const r503 = await get(down, '/api/v1/programs', bearer(k.key));
  assert.equal(r503.status, 503, 'D1 down: 503, never served unmetered (owner decision 9)');
  assert.equal(r503.headers.get('retry-after'), '30');
  assert.equal((await get(env('enforce', { API_DB: undefined }), '/api/v1/programs', bearer(k.key))).status, 503, 'no D1 binding');
  assert.equal((await get(down, '/api/v1/programs', SITE)).status, 200, 'the site is not affected by D1');
});

test('enforce: a key plus first-party headers is still metered; a key in the query string is ignored', async () => {
  const e = env('enforce');
  const k = await addKey(e, { quota: 5 });
  const r = await get(e, '/api/v1/programs', { ...bearer(k.key), ...SITE, 'sec-fetch-site': 'same-origin' });
  assert.equal(r.headers.get('x-quota-remaining'), '4', 'counted');
  assert.equal((await get(e, `/api/v1/programs?key=${encodeURIComponent(k.key)}`)).status, 401, 'query-string key');
  assert.equal((await get(e, `/api/v1/programs?api_key=${encodeURIComponent(k.key)}`)).status, 401);
});

test('enforce: quota N serves N requests, refuses N+1 with 429, and the stored count stays at N', async () => {
  const e = env('enforce');
  const k = await addKey(e, { quota: 3 });
  for (let i = 1; i <= 3; i++) assert.equal((await get(e, '/api/v1/camps', bearer(k.key))).status, 200, `request ${i}`);
  const r = await get(e, '/api/v1/camps', bearer(k.key));
  assert.equal(r.status, 429);
  assert.equal((await r.json()).error, 'Daily quota used');
  const ra = Number(r.headers.get('retry-after'));
  assert.ok(ra >= 1 && ra <= 86400, 'Retry-After runs to the next UTC midnight');
  assert.equal(r.headers.get('x-quota-remaining'), '0');
  await get(e, '/api/v1/camps', bearer(k.key));
  const row = e.API_DB.db.prepare('SELECT count FROM usage WHERE key_id = ?').get(k.id);
  assert.equal(row.count, 3, 'refused requests are not counted');
});

test('the quota statement is the conditional upsert of plan section 4.2', () => {
  assert.match(SQL_COUNT, /ON CONFLICT \(key_id, day\) DO UPDATE SET count = count \+ 1 WHERE usage\.count < \?3 RETURNING count$/);
});

// ---------- report mode (production) ----------
test('report: nothing is refused, and every decision and signal class is counted', async () => {
  const e = env('report', { SITE_RL: limiter(1), KEYED_IP_RL: limiter(100) });
  const k = await addKey(e, { quota: 1 });
  const cases = [
    [{}, 'refused', 'none'],
    [{ 'sec-fetch-site': 'cross-site' }, 'refused', 'cross-site'],
    [SITE, 'first-party', 'client-header'],
    [SITE, 'would-429-site', 'client-header'],
    [bearer('cdk_bad'), 'keyed-refused-401-malformed', 'key'],
    [bearer(makeKey().key), 'keyed-refused-401-unknown', 'key'],
    [bearer(k.key), 'keyed-ok', 'key'],
    [bearer(k.key), 'keyed-refused-429-quota', 'key'],
  ];
  for (const [h] of cases) assert.equal((await get(e, '/api/v1/programs', h)).status, 200, JSON.stringify(h));
  assert.deepEqual(decisions(e), cases.map(c => c[1]));
  assert.deepEqual(signals(e), cases.map(c => c[2]));
  assert.ok(e.API_GATE_STATS.points.every(p => p.blobs[0] === 'report' && p.indexes[0] === 'programs'));
  const d1Down = env('report'); d1Down.API_DB.fail = true;
  assert.equal((await get(d1Down, '/api/v1/programs', bearer((await addKey(env('report'))).key))).status, 200, 'report mode serves even when D1 is down');
});

test('off (or unset): no classification, no counting, today\'s headers', async () => {
  for (const mode of ['off', undefined, 'bogus']) {
    const e = env(mode);
    const r = await get(e, '/api/v1/programs');
    assert.equal(r.status, 200);
    assert.equal(r.headers.get('cache-control'), 'public, max-age=300, must-revalidate');
    assert.equal(e.API_GATE_STATS.points.length, 0);
  }
});

// ---------- nothing identifying is stored or echoed ----------
test('no key, IP or header value in a response, a log line or a data point; the IP bucket is an HMAC', async () => {
  const e = env('enforce', { SITE_RL: limiter(0) });
  const k = await addKey(e, { quota: 1 });
  const logged = [];
  const orig = { log: console.log, warn: console.warn, error: console.error };
  console.log = console.warn = console.error = (...a) => logged.push(a.map(String).join(' '));
  const seen = [];
  try {
    for (const h of [bearer(k.key), bearer(k.key), bearer(`${k.key.slice(0, -1)}Z`), SITE, {}]) {
      const r = await get(e, '/api/v1/programs', h);
      seen.push(await r.text(), JSON.stringify([...r.headers]));
    }
  } finally { Object.assign(console, orig); }
  const secret = k.key.slice(17);
  const hay = [...seen, ...logged, JSON.stringify(e.API_GATE_STATS.points)].join('\n');
  assert.ok(!hay.includes(secret), 'the key secret appears');
  assert.ok(!hay.includes('203.0.113.9'), 'the IP appears');
  const bucket = e.API_GATE_STATS.points.find(p => p.blobs[1] === 'would-429-site').blobs[4];
  const day = new Date().toISOString().slice(0, 10);
  assert.equal(bucket, await ipBucket(e.IP_BUCKET_SECRET, day, '203.0.113.9'), 'bucket = HMAC(secret, day|ip), truncated');
  assert.notEqual(bucket, await ipBucket('another-secret', day, '203.0.113.9'), 'a different secret, a different bucket');
  assert.equal(await ipBucket('', day, '203.0.113.9'), '', 'no secret, no bucket');
  assert.equal((await sha256Hex(day + '203.0.113.9')).slice(0, 8) === bucket, false, 'not a plain hash of the IP');
});

test('the key format and the first-party signal helpers', () => {
  assert.ok(KEY_RE.test(makeKey().key));
  assert.ok(!KEY_RE.test('cdk_ABCDEFGHIJKL_' + 'a'.repeat(43)), 'the id is lower-case');
  const req = h => new Request(HOST + '/api/v1/programs', { headers: h });
  assert.equal(firstPartySignal(req({ 'x-collegedash-client': 'Web' })), 'none', 'the header value is exact');
  assert.equal(firstPartySignal(req({ referer: 'not a url' })), 'none');
});
