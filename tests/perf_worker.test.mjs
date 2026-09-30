// Speed measurements, the Worker side (issue #394, round-2 plan approved by Bianque on the issue): Server-Timing, the
// server point, POST /api/perf, and #345's rule of at most one Analytics Engine data point per request, across both
// datasets and every gate outcome, the fault paths included.
//
//     node --test tests/perf_worker.test.mjs
//
// Offline: the limiters, KV, the asset server and both datasets are fakes. Run under tests/netguard (run_node_suites.py
// preloads it), so any attempt to reach the network fails the suite.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import worker from '../worker.js';
import { mint, verify, COOKIE } from '../api/session.mjs';
import { hashKey, KEY, clearKeyCache } from '../api/apikey.mjs';
import { pagePoint, perfRate, FIELDS, VIEWS, MAX_BODY } from '../api/perf.mjs';

const SECRET = 'a'.repeat(32) + '-test-secret';
const HOST = 'college.nextonetwo.com';
const PREVIEW = 'abcd1234-collegedash.nextonetwolabs.workers.dev';
// Markers that must never reach a data point: the visitor's address, user agent, cookie, a query and a slug.
const IP = '203.0.113.77';
const UA = 'Mozilla/5.0 (MarkerPhone; UA-MARKER-394)';
const QUERY = '?q=QUERY-MARKER-394';

function limiter(limit) {
  const counts = new Map();
  return { counts, async limit({ key }) { const n = (counts.get(key) || 0) + 1; counts.set(key, n); return { success: n <= limit }; } };
}
// A dataset fake. Every write attempt is recorded, including one that then throws.
function sink(throws = false) {
  const points = [];
  return { points, writeDataPoint(p) { points.push(p); if (throws) throw new Error('AE write failed'); } };
}
function kv(records) { return { async get(k) { const r = records.get(k); return r === undefined ? null : JSON.parse(JSON.stringify(r)); } }; }

// Two profiles of different lengths, so a size that leaked would differ between them.
const PROFILE_A = JSON.stringify({ slug: 'short-one', x: 'a' });
const PROFILE_B = JSON.stringify({ slug: 'much-longer-program', x: 'b'.repeat(5000) });
const assets = { async fetch(r) {
  const p = new URL(r.url).pathname;
  const json = (body, etag) => new Response(r.method === 'HEAD' ? null : body,
    { headers: { 'content-type': 'application/json', 'content-length': String(new TextEncoder().encode(body).length), etag } });
  if (p === '/') return new Response(r.method === 'HEAD' ? null : '<html>page</html>', { headers: { 'content-type': 'text/html', 'content-length': '17' } });
  if (p === '/data/programs/index.json') return json('{"programs":[]}', '"i"');
  if (p === '/data/programs/short-one.json') return json(PROFILE_A, '"a"');
  if (p === '/data/programs/much-longer-program.json') return json(PROFILE_B, '"b"');
  if (p === '/archive/refresh-state.json') return json('{}', '"s"');
  return new Response('<html>fallback</html>', { status: 404, headers: { 'content-type': 'text/html' } });
} };

async function issueKey() {
  const hex = n => randomBytes(n).toString('hex');
  const key = `cdash_live_${hex(6)}_${hex(32)}`;
  return { key, id: KEY.exec(key)[1], record: { v: 1, hash: await hashKey(key), label: 't', created: '2026-09-25T12:00:00.000Z', tier: 'standard', status: 'active' } };
}

async function setup(extra = {}) {
  clearKeyCache();
  const good = await issueKey();
  const env = {
    SESSION_SECRET: SECRET, ASSETS: assets,
    RL_SESSION: limiter(180), RL_ANON: limiter(60), RL_IP: limiter(1200), RL_KEY: limiter(60), RL_PERF: limiter(10),
    API_GATE_STATS: sink(), PERF_STATS: sink(), API_KEYS: kv(new Map([['key:' + good.id, good.record]])),
    PERF_SERVER: 'on', PERF_SAMPLE: '0.1',
    ...extra,
  };
  return { env, good };
}
const token = () => mint(SECRET);
const cookie = t => `${COOKIE}=${t}`;
function req(path, { headers = {}, method = 'GET', host = HOST, body } = {}) {
  return new Request(`https://${host}${path}`, { method, body, headers: { 'cf-connecting-ip': IP, 'user-agent': UA, ...headers } });
}
// Every write attempt on this request, across both datasets.
const writes = env => env.API_GATE_STATS.points.length + env.PERF_STATS.points.length;
async function quietly(fn) {
  const original = console.error;
  console.error = () => {};
  try { return await fn(); } finally { console.error = original; }
}
async function run(env, request) { return quietly(() => worker.fetch(request, env)); }
// With one of the session functions replaced for the length of fn.
async function withSeam(name, replacement, fn) {
  const H = worker.internals, original = H[name];
  H[name] = replacement;
  try { return await fn(); } finally { H[name] = original; }
}
const boom = () => { throw new Error('decorate failed'); };

function beacon(over = {}) {
  return { v: 1, view: 'list', res: 'programs', device: 'phone', nav: 'landing', cache: 'network', server: 12, wait: 80, download: 310,
    parse: 120, render: 260, first: 1450, tx: 171000, size: 1900000, rate: 0.1, ...over };
}
async function post(env, body, { headers = {}, t } = {}) {
  const text = typeof body === 'string' ? body : JSON.stringify(body);
  return run(env, req('/api/perf', { method: 'POST', body: text,
    headers: { 'sec-fetch-site': 'same-origin', cookie: cookie(t || await token()), 'content-type': 'text/plain', ...headers } }));
}

// ---------- configuration ----------

test('wrangler.toml: RL_PERF on 3465 at 10/60 s, the perf dataset, and both switches, sampling off', async () => {
  const toml = (await readFile(new URL('../wrangler.toml', import.meta.url), 'utf8')).replace(/\r\n/g, '\n');
  assert.match(toml, /\[\[ratelimits\]\]\nname = "RL_PERF"[^\n]*\nnamespace_id = "3465"\nsimple = \{ limit = 10, period = 60 \}/);
  assert.match(toml, /\[\[analytics_engine_datasets\]\]\nbinding = "PERF_STATS"\ndataset = "collegedash_perf"/);
  assert.match(toml, /^PERF_SAMPLE = "0"$/m, 'PR 1 ships with sampling off (owner: the 7-day request volume comes first)');
  assert.match(toml, /^PERF_SERVER = "on"$/m);
  const ids = [...toml.matchAll(/namespace_id = "(\d+)"/g)].map(m => m[1]);
  assert.deepEqual(ids, [...new Set(ids)], 'every limiter has its own namespace id');
  assert.ok(!ids.some(id => /^9\d{3}$/.test(id)), 'never an ECNL id');
});

test('perfRate: a number in (0, 1], anything else is off', () => {
  for (const [v, r] of [['0.1', 0.1], ['1', 1], ['0', 0], [undefined, 0], ['', 0], ['off', 0], ['1.5', 0], ['-0.1', 0], ['NaN', 0]]) {
    assert.equal(perfRate({ PERF_SAMPLE: v }), r, String(v));
  }
});

// ---------- at most one point per request, every outcome ----------

test('one point per request: routine requests get the server point, gate-counted ones get none', async () => {
  const cases = [
    ['routine /api/v1/programs', async () => ({ r: req('/api/v1/programs', { headers: { cookie: cookie(await token()) } }), gate: 0, perf: 1 })],
    ['routine /', async () => ({ r: req('/', { headers: { cookie: cookie(await token()) } }), gate: 0, perf: 1 })],
    ['anon-missing', async () => ({ r: req('/api/v1/programs'), gate: 1, perf: 0 })],
    ['anon-invalid', async () => ({ r: req('/api/v1/programs', { headers: { cookie: cookie('v1.junk') } }), gate: 1, perf: 0 })],
    ['minted on /', async () => ({ r: req('/'), gate: 1, perf: 0 })],
    ['key-ok', async ({ good }) => ({ r: req('/api/v1/programs', { headers: { authorization: 'Bearer ' + good.key } }), gate: 1, perf: 0 })],
    ['key-invalid', async ({ good }) => ({ r: req('/api/v1/programs', { headers: { authorization: 'Bearer ' + good.key.slice(0, -1) + (good.key.endsWith('a') ? 'b' : 'a') } }), gate: 1, perf: 0 })],
    ['key-in-url', async ({ good }) => ({ r: req('/api/v1/programs?key=' + good.key), gate: 1, perf: 0 })],
    ['invalid slug', async () => ({ r: req('/api/v1/programs/Bad_Slug', { headers: { cookie: cookie(await token()) } }), gate: 0, perf: 1 })],
  ];
  for (const [name, make] of cases) {
    const ctx = await setup();
    const { r, gate, perf } = await make(ctx);
    await run(ctx.env, r);
    assert.equal(ctx.env.API_GATE_STATS.points.length, gate, `${name}: gate points`);
    assert.equal(ctx.env.PERF_STATS.points.length, perf, `${name}: perf points`);
  }
  for (const [name, extra, headers] of [['limited-ip', { RL_IP: limiter(0) }, {}], ['limited-session', { RL_SESSION: limiter(0) }, 'cookie'],
    ['limited-anon', { RL_ANON: limiter(0) }, {}], ['disabled (no secret)', { SESSION_SECRET: undefined }, {}]]) {
    const { env } = await setup(extra);
    await run(env, req('/api/v1/programs', { headers: headers === 'cookie' ? { cookie: cookie(await token()) } : headers }));
    assert.equal(env.API_GATE_STATS.points.length, 1, `${name}: the gate's point`);
    assert.equal(env.PERF_STATS.points.length, 0, `${name}: no timing point`);
  }
});

test('fault path: decorate throws in v1() after the gate counted - still one point, the gate outcome', async () => {
  for (const [name, headers, outcome] of [['anonymous', {}, 'anon-missing'], ['key-ok', 'key', 'key-ok']]) {
    const { env, good } = await setup();
    const h = headers === 'key' ? { authorization: 'Bearer ' + good.key } : headers;
    const res = await withSeam('decorate', boom, () => run(env, req('/api/v1/programs', { headers: h })));
    assert.equal(res.status, 200, `${name}: still served`);
    assert.equal(writes(env), 1, `${name}: one point, not the gate's plus gate-error`);
    assert.equal(env.API_GATE_STATS.points[0]?.blobs[0], outcome, name);
  }
});

test('fault path: page() mints a session and decorate throws - still one point, "minted"', async () => {
  const { env } = await setup();
  const res = await withSeam('decorate', boom, () => run(env, req('/')));
  assert.equal(res.status, 200);
  assert.equal(writes(env), 1, 'one point, not minted plus gate-error');
  assert.equal(env.API_GATE_STATS.points[0]?.blobs[0], 'minted');
});

test('fault path: decorate throws on a routine request - exactly one gate-error, no timing point', async () => {
  const { env } = await setup();
  await withSeam('decorate', boom, async () => run(env, req('/api/v1/programs', { headers: { cookie: cookie(await token()) } })));
  assert.equal(env.API_GATE_STATS.points.length, 1);
  assert.equal(env.API_GATE_STATS.points[0].blobs[0], 'gate-error');
  assert.equal(env.PERF_STATS.points.length, 0);
});

test('fault path: the gate throws before counting - one gate-error, served ungated', async () => {
  const { env } = await setup();
  const res = await withSeam('gate', async () => { throw new Error('gate failed'); }, () => run(env, req('/api/v1/programs')));
  assert.equal(res.status, 200);
  assert.equal(writes(env), 1);
  assert.equal(env.API_GATE_STATS.points[0].blobs[0], 'gate-error');
});

test('fault path: a throwing writeDataPoint still counts - at most one attempt per request', async () => {
  for (const [name, r] of [['anonymous', () => req('/api/v1/programs')], ['routine', async () => req('/api/v1/programs', { headers: { cookie: cookie(await token()) } })],
    ['minted', () => req('/')]]) {
    const { env } = await setup({ API_GATE_STATS: sink(true), PERF_STATS: sink(true) });
    const res = await run(env, await r());
    assert.equal(res.status, 200, `${name}: a failed write never changes the response`);
    assert.equal(writes(env), 1, `${name}: one attempt`);
  }
  const { env } = await setup({ API_GATE_STATS: sink(true), PERF_STATS: sink(true) });
  await withSeam('decorate', boom, () => run(env, req('/api/v1/programs')));
  assert.equal(writes(env), 1, 'the gate write failed and decorate threw: still one attempt');
});

// ---------- Server-Timing and the server point ----------

test('Server-Timing on "/" and every /api/v1 response, the rate header on /api/v1 only', async () => {
  const { env } = await setup({ PERF_SAMPLE: '0' });
  const t = await token();
  for (const path of ['/api/v1/programs', '/api/v1/status', '/api/v1/programs/short-one', '/api/v1/nope']) {
    const res = await run(env, req(path, { headers: { cookie: cookie(t) } }));
    assert.match(res.headers.get('server-timing') || '', /^gate;dur=\d+, data;dur=\d+, total;dur=\d+$/, path);
    assert.equal(res.headers.get('x-collegedash-perf'), '0', path);
  }
  const refused = await run((await setup({ RL_ANON: limiter(0) })).env, req('/api/v1/programs'));
  assert.equal(refused.status, 429);
  assert.match(refused.headers.get('server-timing') || '', /total;dur=\d+/, 'a refusal is timed too');
  const page = await run(env, req('/', { headers: { cookie: cookie(t) } }));
  assert.match(page.headers.get('server-timing') || '', /^data;dur=\d+, total;dur=\d+$/);
  assert.equal(page.headers.get('x-collegedash-perf'), null);
  assert.equal((await run((await setup({ PERF_SAMPLE: '0.1' })).env, req('/api/v1/programs', { headers: { cookie: cookie(t) } }))).headers.get('x-collegedash-perf'), '0.1');
});

test('server point: its exact shape, per route kind, production or preview', async () => {
  const { env } = await setup();
  const t = await token();
  await run(env, req('/api/v1/programs', { headers: { cookie: cookie(t) } }));
  await run(env, req('/api/v1/status', { headers: { cookie: cookie(t) }, host: PREVIEW }));
  await run(env, req('/', { headers: { cookie: cookie(t) } }));
  const [programs, status, page] = env.PERF_STATS.points;
  assert.deepEqual(programs.indexes, ['server:programs']);
  assert.deepEqual(programs.blobs, ['server', 'programs', '2xx', '', '', 'production']);
  assert.equal(programs.doubles.length, 5);
  assert.equal(programs.doubles[0], 1);
  assert.equal(programs.doubles[4], 15, 'the shared list file keeps its exact size');
  assert.ok(programs.doubles.slice(1, 4).every(v => Number.isInteger(v) && v >= 0));
  assert.deepEqual(status.blobs, ['server', 'status', '2xx', '', '', 'preview']);
  assert.deepEqual(page.blobs, ['server', 'page', '2xx', '', '', 'production']);
  const r304 = await run(env, req('/api/v1/programs', { headers: { cookie: cookie(t), 'if-none-match': '"i"' } }));
  assert.ok([200, 304].includes(r304.status));
});

test('switches: PERF_SERVER other than "on" writes no server point; Server-Timing stays; a missing binding is harmless', async () => {
  const t = await token();
  for (const PERF_SERVER of ['off', undefined, 'yes']) {
    const { env } = await setup({ PERF_SERVER });
    const res = await run(env, req('/api/v1/programs', { headers: { cookie: cookie(t) } }));
    assert.equal(env.PERF_STATS.points.length, 0, String(PERF_SERVER));
    assert.ok(res.headers.get('server-timing'));
  }
  const { env } = await setup({ PERF_STATS: undefined });
  const res = await run(env, req('/api/v1/programs', { headers: { cookie: cookie(t) } }));
  assert.equal(res.status, 200);
});

// ---------- POST /api/perf ----------

test('/api/perf: a good report writes one page point of the exact shape; always 204, no body', async () => {
  const { env } = await setup();
  const res = await post(env, beacon());
  assert.equal(res.status, 204);
  assert.equal(await res.text(), '');
  assert.equal(env.API_GATE_STATS.points.length, 0, 'the gate does not run on /api/perf');
  assert.deepEqual(env.PERF_STATS.points, [{
    indexes: ['page:list:phone'],
    blobs: ['page', 'list', 'programs', 'phone', 'landing', 'production', 'network'],
    doubles: [1, 12, 80, 310, 171000, 1900000, 120, 260, 1450, 10],
  }]);
});

test('/api/perf: every refusal is 204 and writes nothing', async () => {
  const t = await token();
  const refusals = [
    ['sampling off', { PERF_SAMPLE: '0' }, beacon({ rate: 0 }), {}],
    ['sampling unset', { PERF_SAMPLE: undefined }, beacon(), {}],
    ['rate mismatch', {}, beacon({ rate: 0.5 }), {}],
    ['rate as a string', {}, beacon({ rate: '0.1' }), {}],
    ['GET', {}, null, { method: 'GET' }],
    ['cross-site', {}, beacon(), { headers: { 'sec-fetch-site': 'cross-site' } }],
    ['same-site', {}, beacon(), { headers: { 'sec-fetch-site': 'same-site' } }],
    ['none', {}, beacon(), { headers: { 'sec-fetch-site': 'none' } }],
    ['no Sec-Fetch-Site', {}, beacon(), { headers: { 'sec-fetch-site': '' } }],
    ['no session', {}, beacon(), { headers: { cookie: '' } }],
    ['forged session', {}, beacon(), { headers: { cookie: cookie(t.slice(0, -2) + 'AA') } }],
    ['no secret', { SESSION_SECRET: undefined }, beacon(), {}],
    ['RL_IP exceeded', { RL_IP: limiter(0) }, beacon(), {}],
    ['RL_PERF exceeded', { RL_PERF: limiter(0) }, beacon(), {}],
    ['RL_PERF failing', { RL_PERF: { async limit() { throw new Error('limiter down'); } } }, beacon(), {}],
    ['too big', {}, JSON.stringify(beacon()) + ' '.repeat(MAX_BODY), {}],
    ['not JSON', {}, 'hello', {}],
    ['an array', {}, '[1]', {}],
    ['an extra key', {}, { ...beacon(), slug: 'stanford' }, {}],
    ['a missing key', {}, (({ tx, ...b }) => b)(beacon()), {}],
    ['unknown view', {}, beacon({ view: 'compare', res: 'programs' }), {}],
    ['view and resource disagree', {}, beacon({ view: 'list', res: 'trends' }), {}],
    ['unknown device', {}, beacon({ device: 'watch' }), {}],
    ['unknown nav', {}, beacon({ nav: 'reload' }), {}],
    ['unknown cache', {}, beacon({ cache: 'disk' }), {}],
    ['v2', {}, beacon({ v: 2 }), {}],
    ['a number as a string', {}, beacon({ download: '310' }), {}],
    ['a null number', {}, beacon({ parse: null }), {}],
  ];
  for (const [name, extra, body, opts] of refusals) {
    const { env } = await setup(extra);
    let res;
    if (opts.method === 'GET') res = await run(env, req('/api/perf', { headers: { 'sec-fetch-site': 'same-origin', cookie: cookie(t) } }));
    else {
      const headers = { 'sec-fetch-site': 'same-origin', cookie: cookie(t), ...(opts.headers || {}) };
      for (const k of Object.keys(headers)) if (headers[k] === '') delete headers[k];
      res = await run(env, req('/api/perf', { method: 'POST', body: typeof body === 'string' ? body : JSON.stringify(body), headers }));
    }
    assert.equal(res.status, 204, name);
    assert.equal(env.PERF_STATS.points.length, 0, name);
    assert.equal(env.API_GATE_STATS.points.length, 0, name);
  }
});

test('/api/perf: RL_PERF is keyed per session id and allows 10 a minute', async () => {
  const { env } = await setup({ RL_PERF: limiter(10) });
  const t = await token(), other = await token();
  for (let i = 0; i < 12; i++) await post(env, beacon(), { t });
  assert.equal(env.PERF_STATS.points.length, 10);
  await post(env, beacon(), { t: other });
  assert.equal(env.PERF_STATS.points.length, 11, 'another session has its own allowance');
  const sid = (await verify(SECRET, t)).sid;
  assert.deepEqual([...env.RL_PERF.counts.keys()].sort(), ['perf:' + sid, 'perf:' + (await verify(SECRET, other)).sid].sort());
});

test('/api/perf: numbers are clamped and rounded; first render only on a landing view', async () => {
  const { env } = await setup();
  await post(env, beacon({ download: 1e9, parse: -5, render: 12.6, tx: 1e12, nav: 'in-app', first: 900 }));
  const d = env.PERF_STATS.points[0].doubles;
  assert.equal(d[3], 120000);
  assert.equal(d[6], 0);
  assert.equal(d[7], 13);
  assert.equal(d[4], 50000000);
  assert.equal(d[8], 0, 'first render is for the landing view only');
  assert.equal(pagePoint(JSON.stringify(beacon({ download: Infinity })), 0.1, req('/api/perf')), null, 'Infinity does not survive JSON, and is refused');
});

// ---------- privacy ----------

test('privacy: two profiles of different lengths give identical size fields, in the page point and the server point', async () => {
  const { env } = await setup();
  const t = await token();
  for (const slug of ['short-one', 'much-longer-program']) {
    const res = await run(env, req(`/api/v1/programs/${slug}`, { headers: { cookie: cookie(t) } }));
    assert.equal(res.status, 200);
  }
  const [a, b] = env.PERF_STATS.points;
  assert.equal(a.doubles[4], 0);
  assert.equal(b.doubles[4], 0, 'a profile body size is never written');
  assert.deepEqual(a.blobs, b.blobs, 'nothing else tells the two apart');
  // the page reports of those two profiles, as the page sends them (sizes 0) and as a forged page might
  const pa = pagePoint(JSON.stringify(beacon({ view: 'profile', res: 'program', tx: 0, size: 0 })), 0.1, req('/api/perf'));
  const pb = pagePoint(JSON.stringify(beacon({ view: 'profile', res: 'program', tx: 0, size: 0 })), 0.1, req('/api/perf'));
  assert.deepEqual([pa.doubles[4], pa.doubles[5]], [pb.doubles[4], pb.doubles[5]]);
});

test('privacy: a forged profile size is written as 0', async () => {
  const { env } = await setup();
  await post(env, beacon({ view: 'profile', res: 'program', tx: 21437, size: 21437 }));
  const d = env.PERF_STATS.points[0].doubles;
  assert.deepEqual([d[4], d[5]], [0, 0]);
  const shared = await setup();
  await post(shared.env, beacon({ view: 'trends', res: 'trends', tx: 254000, size: 1200000 }));
  assert.deepEqual(shared.env.PERF_STATS.points[0].doubles.slice(4, 6), [254000, 1200000], 'shared files keep their sizes');
});

test('privacy: no IP, user agent, cookie, session id, query or slug in any point written', async () => {
  const { env, good } = await setup();
  const t = await token();
  const sid = (await verify(SECRET, t)).sid;
  const requests = [
    req('/api/v1/programs/short-one' + QUERY, { headers: { cookie: cookie(t) } }),
    req('/api/v1/programs/much-longer-program', { headers: { cookie: cookie(t) } }),
    req('/api/v1/programs' + QUERY, { headers: { cookie: cookie(t) } }),
    req('/' + QUERY, { headers: { cookie: cookie(t) } }),
    req('/api/v1/programs', { headers: { authorization: 'Bearer ' + good.key } }),
    req('/'),
  ];
  for (const r of requests) await run(env, r);
  await post(env, beacon({ view: 'profile', res: 'program' }), { t });
  const all = JSON.stringify([env.PERF_STATS.points, env.API_GATE_STATS.points]);
  assert.ok(env.PERF_STATS.points.length >= 5, 'the check saw real points');
  for (const [what, marker] of [['IP', IP], ['user agent', 'UA-MARKER-394'], ['cookie', t], ['session id', sid], ['query', 'QUERY-MARKER-394'],
    ['slug', 'short-one'], ['slug', 'much-longer-program'], ['key', good.key]]) {
    assert.ok(!all.includes(marker), `${what} must not be written`);
  }
  for (const p of env.PERF_STATS.points) {
    assert.ok(p.blobs.every(b => /^[a-z0-9:-]*$/.test(b)), 'every blob is one of the fixed words: ' + p.blobs);
  }
});

test('FIELDS and VIEWS: the wire format the page sends, nothing more', () => {
  assert.deepEqual(FIELDS, ['v', 'view', 'res', 'device', 'nav', 'cache', 'server', 'wait', 'download', 'parse', 'render', 'first', 'tx', 'size', 'rate']);
  assert.deepEqual(VIEWS, { list: 'programs', profile: 'program', trends: 'trends', camps: 'camps' });
});
