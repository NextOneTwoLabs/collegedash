// Session cookie and rate limits for /api/v1/* (issue #345, phase 1). Ported from ecnl-dashboard's
// tests/session.test.mjs (#90; R1-R13 are that plan review's cases), on this site's routes, names and limits, plus
// the preview-host cases of #345's round-4 plan (change 1) and the page's renewal rule.
//
//     node --test tests/session.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { mint, verify, readCookie, setCookie, ipKey, gate, decorate, COOKIE, TTL, RENEW_AFTER, COOKIE_MAX_AGE } from '../api/session.mjs';
import worker from '../worker.js';

const SECRET = 'a'.repeat(32) + '-test-secret';
const OTHER = 'b'.repeat(32) + '-other-secret';
const T0 = Date.UTC(2026, 8, 24, 12, 0, 0);
const HOST = 'college.nextonetwo.com';
const PREVIEW = 'abcd1234-collegedash.nextonetwolabs.workers.dev';
const PLAIN = 'collegedash.nextonetwolabs.workers.dev';
const req = (path, headers = {}, method = 'GET', host = HOST) => new Request(`https://${host}${path}`, { method, headers });
const cookieOf = response => /^__Host-cdash_s=([^;]+);/.exec(response.headers.get('set-cookie') || '')?.[1];

function limiter(limit) {
  const counts = new Map();
  return { counts, async limit({ key }) { const n = (counts.get(key) || 0) + 1; counts.set(key, n); return { success: n <= limit }; } };
}
function sink() { const points = []; return { points, writeDataPoint(p) { points.push(p); } }; }
const limiters = (anon = 60) => ({ RL_SESSION: limiter(180), RL_ANON: limiter(anon), RL_IP: limiter(1200) });
const assets = { reads: 0, async fetch(r) {
  const p = new URL(r.url).pathname;
  if (p === '/') {
    const headers = { 'content-type': 'text/html', 'cache-control': 'public, max-age=0, must-revalidate', etag: '"p"' };
    if (r.headers.get('if-none-match') === '"p"') return new Response(null, { status: 304, headers });
    return new Response(r.method === 'HEAD' ? null : '<html>page</html>', { headers });
  }
  this.reads++;
  if (p === '/data/programs/index.json') return new Response(r.method === 'HEAD' ? null : '{"programs":[]}', { headers: { 'content-type': 'application/json', etag: '"i"' } });
  if (p === '/data/camps/index.json') return new Response(r.method === 'HEAD' ? null : '{"camps":[]}', { headers: { 'content-type': 'application/json', etag: '"c"' } });
  if (p === '/archive/refresh-state.json') return new Response(r.method === 'HEAD' ? null : '{}', { headers: { 'content-type': 'application/json', etag: '"s"' } });
  return new Response('<!doctype html><html>fallback</html>', { status: 404, headers: { 'content-type': 'text/html' } });
} };
async function quietly(fn) {
  const original = console.error, logged = [];
  console.error = (...args) => logged.push(args);
  try { return { result: await fn(), logged }; } finally { console.error = original; }
}

test('wrangler.toml: the three phase-1 limiters with their approved limits and ids, the stats binding, no secret', async () => {
  const toml = (await readFile(new URL('../wrangler.toml', import.meta.url), 'utf8')).replace(/\r\n/g, '\n');
  for (const [name, id, limit] of [['RL_SESSION', '3461', 180], ['RL_ANON', '3462', 60], ['RL_IP', '3463', 1200]]) {
    assert.match(toml, new RegExp(`\\[\\[ratelimits\\]\\]\\nname = "${name}"[^\\n]*\\nnamespace_id = "${id}"\\nsimple = \\{ limit = ${limit}, period = 60 \\}`), name);
  }
  assert.doesNotMatch(toml, /namespace_id = "(9\d{3}|345[1-3])"/, 'an ECNL id or a retired #355 id');
  assert.match(toml, /\[\[analytics_engine_datasets\]\]\nbinding = "API_GATE_STATS"\ndataset = "collegedash_api_gate"/);
  assert.doesNotMatch(toml, /^\s*SESSION_SECRET\s*=|^\[secrets\]/m,'the secret is a Worker secret, never a var or a required secret');
  assert.doesNotMatch(toml, /API_GATE = |API_DB|IP_BUCKET_SECRET =/, '#355 report mode and D1 are gone');
});

test('token: valid, renew, expired, forged, wrong secret, missing, malformed', async () => {
  const t = await mint(SECRET, T0);
  assert.match(t, /^v1\.\d{10}\.\d{10}\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}$/);
  assert.equal((await verify(SECRET, t, T0)).state, 'valid');
  assert.equal((await verify(SECRET, t, T0 + (RENEW_AFTER - 1) * 1000)).state, 'valid');
  assert.equal((await verify(SECRET, t, T0 + RENEW_AFTER * 1000)).state, 'renew');
  assert.equal((await verify(SECRET, t, T0 + (TTL - 1) * 1000)).state, 'renew');
  assert.equal((await verify(SECRET, t, T0 + TTL * 1000)).state, 'expired');
  assert.equal((await verify(OTHER, t, T0)).state, 'invalid', 'wrong secret');
  const [v, iat, exp, sid, sig] = t.split('.');
  assert.equal((await verify(SECRET, [v, iat, String(Number(exp) + 86400), sid, sig].join('.'), T0)).state, 'invalid');
  assert.equal((await verify(SECRET, [v, iat, exp, 'A'.repeat(22), sig].join('.'), T0)).state, 'invalid');
  assert.equal((await verify(SECRET, [v, iat, exp, sid, (sig[0] === 'A' ? 'B' : 'A') + sig.slice(1)].join('.'), T0)).state, 'invalid');
  assert.equal((await verify(SECRET, await mint(SECRET, T0 + 3600 * 1000), T0)).state, 'invalid', 'issued in the future');
  assert.equal((await verify(SECRET, null, T0)).state, 'missing');
  assert.equal((await verify(SECRET, '', T0)).state, 'missing');
  for (const junk of ['x', 'v1', t + '.', 'v2' + t.slice(2), t.replace(/\./g, ','), '<script>']) assert.equal((await verify(SECRET, junk, T0)).state, 'invalid', junk);
  assert.notEqual((await mint(SECRET, T0)).split('.')[3], (await mint(SECRET, T0)).split('.')[3], 'two mints never share an id');
});

test('R3 only the canonical base64url encoding of a signature verifies', async () => {
  for (let i = 0; i < 8; i++) {
    const t = await mint(SECRET, T0);
    const head = t.slice(0, -1);
    let accepted = 0;
    for (const ch of 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_') if ((await verify(SECRET, head + ch, T0)).state === 'valid') accepted++;
    assert.equal(accepted, 1, t);
  }
});

test('cookie parsing and attributes: __Host- prefix, 7-day cookie, 24-hour token', () => {
  assert.equal(readCookie(`a=1; ${COOKIE}=tok; b=2`), 'tok');
  assert.equal(readCookie('a=1'), null);
  assert.equal(readCookie(null), null);
  assert.equal(COOKIE, '__Host-cdash_s');
  assert.equal(COOKIE_MAX_AGE, 604800);
  assert.equal(TTL, 86400);
  assert.equal(setCookie('tok'), `${COOKIE}=tok; Max-Age=604800; Path=/; Secure; HttpOnly; SameSite=Lax`);
});

test('R7 ip keys: IPv4 whole, IPv4-mapped as IPv4, IPv6 by /64; junk never throws', () => {
  const cases = {
    '203.0.113.9': 'ip:203.0.113.9',
    '2001:db8:1:2:3:4:5:6': 'ip6:2001:db8:1:2::/64',
    '2001:db8:1:2::9': 'ip6:2001:db8:1:2::/64',
    '2001:DB8:1:2::': 'ip6:2001:db8:1:2::/64',
    '::ffff:198.51.100.7': 'ip:198.51.100.7',
    '0:0:0:0:0:ffff:c633:6407': 'ip:198.51.100.7',
  };
  for (const [ip, want] of Object.entries(cases)) assert.equal(ipKey(ip), want, ip);
  assert.equal(ipKey(null), 'ip:unknown');
  for (const junk of ['', 'not-an-ip', '999.1.1.1', 'x'.repeat(5000), '::ffff:zz.qq.1.1', ':::::', '%E0%A4%A']) assert.doesNotThrow(() => ipKey(junk), junk);
});

test('gate: session tiers, renewal with a fresh id, anonymous states, counts without IP or id', async () => {
  const env = { SESSION_SECRET: SECRET, ...limiters(), API_GATE_STATS: sink() };
  const t = await mint(SECRET, T0);
  const ip = { 'cf-connecting-ip': '198.51.100.7' };
  let g = await gate(req('/api/v1/programs', { ...ip, cookie: `${COOKIE}=${t}`, 'sec-fetch-site': 'same-origin' }), env, T0);
  assert.deepEqual(g, { session: 'ok', cookie: null });
  assert.equal(env.API_GATE_STATS.points.length, 0, 'a routine session request writes nothing');
  g = await gate(req('/api/v1/programs', { ...ip, cookie: `${COOKIE}=${t}` }), env, T0 + 2 * 3600 * 1000);
  assert.equal(g.session, 'renewed');
  const renewed = /^__Host-cdash_s=([^;]+);/.exec(g.cookie)[1];
  assert.notEqual(renewed.split('.')[3], t.split('.')[3], 'a renewal starts a fresh session id');
  for (const [cookie, state] of [[null, 'missing'], ['garbage', 'invalid'], [await mint(OTHER, T0), 'invalid'], [t, 'expired']]) {
    const now = state === 'expired' ? T0 + TTL * 1000 : T0;
    const before = env.API_GATE_STATS.points.length;
    g = await gate(req('/api/v1/camps', { ...ip, ...(cookie ? { cookie: `${COOKIE}=${cookie}` } : {}) }), env, now);
    assert.deepEqual(g, { session: 'none', cookie: null }, state);
    assert.equal(env.API_GATE_STATS.points.length, before + 1, 'one data point per request');
    assert.deepEqual(env.API_GATE_STATS.points.at(-1).blobs, ['anon-' + state, 'camps', 'absent', 'production']);
  }
  await gate(req('/api/v1/programs/Bad_Slug!', ip), env, T0);
  assert.deepEqual(env.API_GATE_STATS.points.at(-1).blobs, ['anon-missing', 'invalid', 'absent', 'production']);
  await gate(req('/api/v1/nope', { ...ip, 'sec-fetch-site': 'weird' }, 'GET', PREVIEW), env, T0);
  assert.deepEqual(env.API_GATE_STATS.points.at(-1).blobs, ['anon-missing', 'unknown', 'other', 'preview']);
  const written = JSON.stringify(env.API_GATE_STATS.points);
  assert.ok(!written.includes('198.51.100') && !written.includes(t.split('.')[3]) && !written.includes(renewed.split('.')[3]), 'no IP or session id in analytics');
});

test('R6 cross-site with a cookie is anon-cross-site; other Sec-Fetch-Site values keep the session', async () => {
  const env = { SESSION_SECRET: SECRET, ...limiters(), API_GATE_STATS: sink() };
  const t = await mint(SECRET, T0);
  const g = await gate(req('/api/v1/camps', { cookie: `${COOKIE}=${t}`, 'sec-fetch-site': 'cross-site' }), env, T0);
  assert.equal(g.session, 'none');
  assert.deepEqual(env.API_GATE_STATS.points[0].blobs, ['anon-cross-site', 'camps', 'cross-site', 'production']);
  for (const sfs of ['same-origin', 'same-site', 'none', undefined]) {
    const h = { cookie: `${COOKIE}=${t}` };
    if (sfs) h['sec-fetch-site'] = sfs;
    assert.equal((await gate(req('/api/v1/camps', h), env, T0)).session, 'ok', String(sfs));
  }
});

test('a forged X-CollegeDash-Client header (the #355 signal) earns nothing: the anonymous tier', async () => {
  const env = { SESSION_SECRET: SECRET, ...limiters(1), API_GATE_STATS: sink() };
  const h = { 'x-collegedash-client': 'web', 'sec-fetch-site': 'same-origin', 'cf-connecting-ip': '203.0.113.77' };
  assert.equal((await gate(req('/api/v1/programs', h), env, T0)).session, 'none');
  const r = (await gate(req('/api/v1/programs', h), env, T0)).response;
  assert.equal(r.status, 429, 'it is limited as any cookieless request');
});

test('limits: 429 JSON with Retry-After and the session header per tier; the anonymous one points to keys; HEAD has no body', async () => {
  const env = { SESSION_SECRET: SECRET, ...limiters(60), API_GATE_STATS: sink() };
  const ip = { 'cf-connecting-ip': '198.51.100.8' };
  for (let i = 0; i < 60; i++) assert.ok(!(await gate(req('/api/v1/programs', ip), env, T0)).response, `anon ${i}`);
  const r = (await gate(req('/api/v1/programs', ip), env, T0)).response;
  assert.equal(r.status, 429);
  assert.equal(r.headers.get('retry-after'), '60');
  assert.equal(r.headers.get('cache-control'), 'no-store');
  assert.equal(r.headers.get('x-collegedash-session'), 'none');
  const help = 'https://github.com/NextOneTwoLabs/collegedash/blob/main/docs/data-api.md#api-keys';
  assert.equal(r.headers.get('link'), `<${help}>; rel="help"`);
  assert.deepEqual(await r.json(), { ok: false, error: 'Too many requests. Please wait a minute and try again.', help });
  assert.equal(await (await gate(req('/api/v1/programs', ip, 'HEAD'), env, T0)).response.text(), '');
  const t = await mint(SECRET, T0);
  for (let i = 0; i < 180; i++) assert.ok(!(await gate(req('/api/v1/programs', { ...ip, cookie: `${COOKIE}=${t}` }), env, T0)).response, `session ${i}`);
  const limited = (await gate(req('/api/v1/programs', { ...ip, cookie: `${COOKIE}=${t}` }), env, T0)).response;
  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get('x-collegedash-session'), 'ok');
  assert.equal(limited.headers.get('link'), null, 'a session-tier 429 carries no key hint');
  assert.ok(!(await gate(req('/api/v1/programs', { ...ip, cookie: `${COOKIE}=${await mint(SECRET, T0)}` }), env, T0)).response, 'a second session on that IP still works');
  const outcomes = env.API_GATE_STATS.points.map(p => p.blobs[0]);
  assert.ok(outcomes.includes('limited-anon') && outcomes.includes('limited-session'));
});

test('R5 a cookieless flood writes exactly one data point per request, limited-* replacing anon-*', async () => {
  const env = { SESSION_SECRET: SECRET, ...limiters(60), API_GATE_STATS: sink() };
  const ip = { 'cf-connecting-ip': '198.51.100.20' };
  for (let i = 0; i < 100; i++) await gate(req('/api/v1/programs', ip), env, T0);
  const by = {};
  for (const p of env.API_GATE_STATS.points) by[p.blobs[0]] = (by[p.blobs[0]] || 0) + 1;
  assert.equal(env.API_GATE_STATS.points.length, 100);
  assert.deepEqual(by, { 'anon-missing': 60, 'limited-anon': 40 });
});

test('R9 a request refused by RL_IP counts limited-ip; the parallel session check still used a count', async () => {
  const env = { SESSION_SECRET: SECRET, RL_SESSION: limiter(180), RL_ANON: limiter(60), RL_IP: limiter(0), API_GATE_STATS: sink() };
  const t = await mint(SECRET, T0);
  const g = await gate(req('/api/v1/camps', { cookie: `${COOKIE}=${t}`, 'cf-connecting-ip': '203.0.113.1' }), env, T0);
  assert.equal(g.response.status, 429);
  assert.equal(g.response.headers.get('x-collegedash-session'), 'ok');
  assert.deepEqual(env.API_GATE_STATS.points.map(p => p.blobs[0]), ['limited-ip']);
  assert.deepEqual([...env.RL_SESSION.counts.values()], [1]);
});

test('missing or short secret fails open ("off", RL_IP only); the rollback: missing tier bindings are allowed', async () => {
  for (const secret of [undefined, '', 'short']) {
    const env = { SESSION_SECRET: secret, RL_IP: limiter(2), API_GATE_STATS: sink() };
    assert.deepEqual(await gate(req('/api/v1/programs'), env, T0), { session: 'off' });
    assert.deepEqual(await gate(req('/api/v1/programs'), env, T0), { session: 'off' });
    const r = (await gate(req('/api/v1/programs'), env, T0)).response;
    assert.equal(r.status, 429);
    assert.equal(r.headers.get('x-collegedash-session'), 'off');
    assert.deepEqual(env.API_GATE_STATS.points.map(p => p.blobs[0]), ['disabled', 'disabled', 'limited-ip']);
  }
  // claude/345-rollback-limits removes RL_SESSION and RL_ANON: every tier request is then allowed, RL_IP still holds.
  const rollback = { SESSION_SECRET: SECRET, RL_IP: limiter(1200), API_GATE_STATS: sink() };
  for (let i = 0; i < 500; i++) assert.ok(!(await gate(req('/api/v1/programs', { 'cf-connecting-ip': '203.0.113.9' }), rollback, T0)).response, `rollback ${i}`);
  assert.deepEqual(await gate(req('/api/v1/programs'), { SESSION_SECRET: SECRET }, T0), { session: 'none', cookie: null });
});

test('worker: "/" mints a cookie once, the API honours it, the curl jar flow works', async () => {
  const env = { ASSETS: assets, SESSION_SECRET: SECRET, ...limiters(), API_GATE_STATS: sink() };
  for (const method of ['GET', 'HEAD']) {
    const home = await worker.fetch(req('/', {}, method), env);
    assert.equal(home.status, 200);
    assert.match(home.headers.get('set-cookie'), /^__Host-cdash_s=v1\.[^;]+; Max-Age=604800; Path=\/; Secure; HttpOnly; SameSite=Lax$/);
    assert.equal(home.headers.get('cache-control'), 'private, no-cache');
    const token = cookieOf(home);
    const again = await worker.fetch(req('/', { cookie: `${COOKIE}=${token}` }, method), env);
    assert.equal(again.headers.get('set-cookie'), null, 'a valid cookie is not re-issued');
    const api = await worker.fetch(req('/api/v1/programs', { cookie: `${COOKIE}=${token}` }), env);
    assert.equal(api.status, 200);
    assert.equal(api.headers.get('x-collegedash-session'), 'ok');
    assert.equal(api.headers.get('cache-control'), 'no-cache');
    assert.equal(api.headers.get('set-cookie'), null);
  }
  assert.deepEqual(env.API_GATE_STATS.points.map(p => p.blobs.slice(0, 2)), [['minted', 'page'], ['minted', 'page']]);
  const anon = await worker.fetch(req('/api/v1/programs'), env);
  assert.equal(anon.status, 200, 'no cookie is served under the anonymous tier, not refused');
  assert.equal(anon.headers.get('x-collegedash-session'), 'none');
  const status = await worker.fetch(req('/api/v1/status'), env);
  assert.equal(status.status, 200, '/api/v1/status needs no key');
  const off = { ASSETS: assets };
  assert.equal((await worker.fetch(req('/'), off)).headers.get('set-cookie'), null);
  const offApi = await worker.fetch(req('/api/v1/programs'), off);
  assert.equal(offApi.status, 200);
  assert.equal(offApi.headers.get('x-collegedash-session'), 'off');
});

test('preview hosts (round-4 change 1): a version preview serves its own page with a cookie; only the plain workers.dev address redirects', async () => {
  const env = { ASSETS: assets, SESSION_SECRET: SECRET, ...limiters(), API_GATE_STATS: sink() };
  for (const method of ['GET', 'HEAD']) {
    const preview = await worker.fetch(req('/', {}, method, PREVIEW), env);
    assert.equal(preview.status, 200, `${method} / on a version preview`);
    assert.ok(cookieOf(preview), 'the preview mints its own cookie');
    assert.equal(preview.headers.get('cache-control'), 'private, no-cache');
    const plain = await worker.fetch(req('/', {}, method, PLAIN), env);
    assert.equal(plain.status, 301, `${method} / on the plain workers.dev address`);
    assert.equal(plain.headers.get('location'), `https://${HOST}/`);
    assert.equal(plain.headers.get('set-cookie'), null, 'a redirect sets no cookie');
    const canonical = await worker.fetch(req('/', {}, method, HOST), env);
    assert.equal(canonical.status, 200);
    assert.ok(cookieOf(canonical));
  }
  const deep = await worker.fetch(req('/assets/og.png?v=2', {}, 'GET', PLAIN), env);
  assert.equal(deep.headers.get('location'), `https://${HOST}/assets/og.png?v=2`, 'a deep link keeps its path and query');
  assert.equal(assets.reads >= 0, true);
  // /api/* is answered on every host, never redirected (a 301 would turn a POST into a GET)
  for (const host of [PREVIEW, PLAIN, HOST]) {
    const api = await worker.fetch(req('/api/v1/status', {}, 'GET', host), env);
    assert.equal(api.status, 200, host);
    assert.equal((await worker.fetch(req('/api/status', {}, 'GET', host), env)).status, 200, host);
  }
  const previewApi = await worker.fetch(req('/api/v1/programs', {}, 'GET', PREVIEW), env);
  assert.equal(env.API_GATE_STATS.points.at(-1).blobs[3], 'preview', 'counts tell a preview from production');
  assert.equal(previewApi.headers.get('x-collegedash-session'), 'none');
  const tokenOnPreview = cookieOf(await worker.fetch(req('/', {}, 'GET', PREVIEW), env));
  const withCookie = await worker.fetch(req('/api/v1/programs', { cookie: `${COOKIE}=${tokenOnPreview}` }, 'GET', PREVIEW), env);
  assert.equal(withCookie.headers.get('x-collegedash-session'), 'ok', 'the jar flow works on the preview');
});

test('R4 a 304 on "/" still carries the cookie and private, no-cache; the cookie only on "/"', async () => {
  const env = { ASSETS: assets, SESSION_SECRET: SECRET, API_GATE_STATS: sink() };
  const r = await worker.fetch(req('/', { 'if-none-match': '"p"' }), env);
  assert.equal(r.status, 304);
  assert.match(r.headers.get('set-cookie') || '', /^__Host-cdash_s=v1\./);
  assert.equal(r.headers.get('cache-control'), 'private, no-cache');
  assert.equal((await worker.fetch(req('/index.html'), env)).headers.get('set-cookie'), null);
  assert.equal((await worker.fetch(req('/', {}, 'POST'), env)).headers.get('set-cookie'), null);
  const old = await mint(SECRET, Date.now() - 2 * 3600 * 1000);
  const renewed = await worker.fetch(req('/', { cookie: `${COOKIE}=${old}` }), env);
  assert.ok(cookieOf(renewed) && cookieOf(renewed).split('.')[3] !== old.split('.')[3]);
  assert.deepEqual(env.API_GATE_STATS.points.map(p => p.blobs[0]), ['minted'], 'a renewal on "/" is not counted as a mint');
});

test('worker: an API renewal sets the cookie; R10 an API error keeps no-store', async () => {
  const env = { ASSETS: assets, SESSION_SECRET: SECRET, ...limiters(), API_GATE_STATS: sink() };
  const old = await mint(SECRET, Date.now() - 2 * 3600 * 1000);
  const r = await worker.fetch(req('/api/v1/programs', { cookie: `${COOKIE}=${old}` }), env);
  assert.equal(r.headers.get('x-collegedash-session'), 'renewed');
  assert.ok(cookieOf(r));
  assert.equal(r.headers.get('cache-control'), 'private, no-cache');
  const missing = await worker.fetch(req('/api/v1/programs/no-such-program', { cookie: `${COOKIE}=${old}` }), env);
  assert.equal(missing.status, 404);
  assert.ok(cookieOf(missing));
  assert.equal(missing.headers.get('cache-control'), 'no-store');
  assert.equal(decorate(new Response('{}', { status: 404, headers: { 'cache-control': 'no-store' } }), { session: 'renewed', cookie: '__Host-cdash_s=x' }).headers.get('cache-control'), 'no-store');
});

test('R2 a throwing writeDataPoint never changes a response', async () => {
  const env = { ASSETS: assets, SESSION_SECRET: SECRET, ...limiters(0), API_GATE_STATS: { writeDataPoint() { throw new Error('quota'); } } };
  assert.equal((await worker.fetch(req('/api/v1/programs', { cookie: `${COOKIE}=${await mint(SECRET)}` }), env)).status, 200);
  const none = await worker.fetch(req('/api/v1/programs'), env);
  assert.equal(none.status, 429);
  assert.equal(none.headers.get('x-collegedash-session'), 'none');
  assert.ok(cookieOf(await worker.fetch(req('/'), env)));
});

test('R13 an anonymous-tier 429 says "none", so the page renews its cookie, and the next request is served', async () => {
  const env = { ASSETS: assets, SESSION_SECRET: SECRET, RL_SESSION: limiter(180), RL_ANON: limiter(0), RL_IP: limiter(1200), API_GATE_STATS: sink() };
  const r = await worker.fetch(req('/api/v1/programs', { 'cf-connecting-ip': '203.0.113.50' }), env);
  assert.equal(r.status, 429);
  assert.equal(r.headers.get('x-collegedash-session'), 'none');
  const head = await worker.fetch(req('/', { 'cf-connecting-ip': '203.0.113.50' }, 'HEAD'), env);
  const next = await worker.fetch(req('/api/v1/programs', { 'cf-connecting-ip': '203.0.113.50', cookie: `${COOKIE}=${cookieOf(head)}` }), env);
  assert.equal(next.status, 200);
  assert.equal(next.headers.get('x-collegedash-session'), 'ok');
});

test('R1 R12 a throwing limiter, or ?x=% and other hostile URLs, still serves JSON on the session path; a failed import is not cached', async () => {
  const boom = { async limit() { throw new Error('limiter down'); } };
  const env = { ASSETS: assets, SESSION_SECRET: SECRET, RL_SESSION: boom, RL_ANON: boom, RL_IP: boom, API_GATE_STATS: sink() };
  const { result: r, logged } = await quietly(() => worker.fetch(req('/api/v1/programs'), env));
  assert.equal(r.status, 200);
  assert.match(r.headers.get('content-type'), /application\/json/);
  assert.equal(r.headers.get('x-collegedash-session'), 'error');
  assert.deepEqual(env.API_GATE_STATS.points.map(p => p.blobs.slice(0, 2)), [['gate-error', 'programs']]);
  assert.deepEqual(logged.map(args => args[0]), ['session']);
  // nothing in the URL or the IP header can throw into the session path: these stay gated ('none'), never 'error'
  const gated = { ASSETS: assets, SESSION_SECRET: SECRET, ...limiters(), API_GATE_STATS: sink() };
  for (const [path, ip] of [['/api/v1/programs?x=%', '203.0.113.5'], ['/api/v1/programs?x=%E0%A4%A', 'not-an-ip'], ['/api/v1/%', '999.1.1.1'], ['/api/v1/programs', 'x'.repeat(3000)]]) {
    const res = await worker.fetch(req(path, { 'cf-connecting-ip': ip }), gated);
    assert.equal(res.headers.get('x-collegedash-session'), 'none', path);
  }
  const fresh = 'c'.repeat(32) + '-import-fault';
  const stale = `${COOKIE}=${await mint(OTHER)}`;
  const importKey = crypto.subtle.importKey;
  crypto.subtle.importKey = async () => { throw new Error('import fault'); };
  let faulted;
  try {
    faulted = await quietly(async () => ({
      api: await worker.fetch(req('/api/v1/camps', { cookie: stale }), { ...env, SESSION_SECRET: fresh, ...limiters() }),
      page: await worker.fetch(req('/'), { ...env, SESSION_SECRET: fresh }),
    }));
  } finally { crypto.subtle.importKey = importKey; }
  assert.equal(faulted.result.api.status, 200);
  assert.equal(faulted.result.api.headers.get('x-collegedash-session'), 'error');
  assert.equal(faulted.result.page.status, 200, 'the page is served without a cookie');
  assert.equal(faulted.result.page.headers.get('set-cookie'), null);
  const home = await worker.fetch(req('/'), { ...env, SESSION_SECRET: fresh });
  assert.ok(cookieOf(home), 'the import works again: the failure was not kept for the isolate');
});

// The page's own noteSession (public/index.html), run with a stub fetch and clock.
test('page: only X-CollegeDash-Session "none" sends a background HEAD /, at most once a minute, and stops when cookies are not kept', async () => {
  const html = (await readFile(new URL('../public/index.html', import.meta.url), 'utf8')).replace(/\r\n/g, '\n');
  const start = html.indexOf('let sessionRenewAt = 0');
  const end = html.indexOf('\n}\n', html.indexOf('function noteSession(', start)) + 3;
  assert.ok(start >= 0 && end > start, 'noteSession not found in index.html');
  const calls = [], clock = { t: 1e12 };
  const load = () => new Function('fetch', 'Date', html.slice(start, end) + '\nreturn noteSession;')(
    (url, options) => { calls.push([url, options.method, options.cache]); return { then: ok => { ok(); return Promise.resolve(); } }; }, { now: () => clock.t });
  const answer = session => ({ headers: new Headers(session ? { 'x-collegedash-session': session } : {}) });
  let noteSession = load();
  for (const session of ['ok', 'renewed', 'off', 'error', 'key', null]) noteSession(answer(session), clock.t);
  assert.equal(calls.length, 0);
  noteSession(answer('none'), clock.t);
  noteSession(answer('none'), clock.t);
  assert.deepEqual(calls, [['/', 'HEAD', 'no-store']]);
  // a request sent AFTER the renewal landed still says none: the browser is not keeping the cookie; stop
  clock.t += 60001;
  noteSession(answer('none'), clock.t);
  assert.equal(calls.length, 1, 'no renewal once cookies are known not to be kept');
  // an answer that says ok resets it, so a later cookie loss renews again
  noteSession(answer('ok'), clock.t);
  noteSession(answer('none'), clock.t);
  assert.equal(calls.length, 2);
  // an answer to a request sent BEFORE the renewal landed does not count as "not kept"
  noteSession = load(); calls.length = 0; clock.t = 2e12;
  noteSession(answer('none'), clock.t - 5);
  clock.t += 60001;
  noteSession(answer('none'), clock.t - 70000);
  assert.equal(calls.length, 2, 'an in-flight answer from before the renewal is not proof');
  assert.doesNotMatch(html, /X-CollegeDash-Client/, 'the #355 header is gone from the page');
});
