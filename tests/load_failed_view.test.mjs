// The "couldn't load, try again" state of every data load (issue #345, plan section 2.4; phase 1 rules from the
// round-4 plan and ECNL #90/#92).
//
//     node --test tests/load_failed_view.test.mjs
//
// A site request can be rate-limited (429) or unanswered (503), and a connection can drop. Each data load a visitor
// waits on must then show a card that says so, with a Try again button that works - not a blank page, a raw
// "HTTP 429", or "Profile not built yet" for a profile that exists. The site's own calls travel on the session
// cookie and never send an API key, so a 401 is not a case of its own. An answer that says
// X-CollegeDash-Session: none makes the page renew its cookie with one background HEAD /.
// Same mechanism as tests/table_sort.test.mjs: the page's inline <script> runs in a vm against a stub DOM, and
// fetch is a stub whose answers each test sets. Every request is recorded, with its method and headers.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const PUBLIC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const SLUG = INDEX.programs.find(p => fs.existsSync(path.join(PUBLIC, 'data', 'programs', `${p.slug}.json`))).slug;

function makeElement(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, onclick: null,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null, matches: () => false, focus() { }, contains: () => false,
  };
}

// answer(url) -> { status, body, headers } | 'network' (fetch rejects). Defaults: the real index and profiles.
function loadPage(answer) {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
  const requests = [];
  const real = url => {
    const u = String(url);
    const file = u === '/api/v1/programs' ? 'data/programs/index.json' : u.startsWith('/api/v1/programs/') ? `data/programs/${u.split('/').pop()}.json`
      : u === '/api/v1/camps' ? 'data/camps/index.json' : null;
    return file && fs.existsSync(path.join(PUBLIC, file)) ? { status: 200, body: JSON.parse(fs.readFileSync(path.join(PUBLIC, file), 'utf8')) } : { status: 404, body: {} };
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector, querySelectorAll: () => [], addEventListener() { }, createElement: makeElement },
    location: { hash: '', replace(h) { this.hash = h; } }, history: { replaceState() { } }, matchMedia: () => ({ matches: false }),
    localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) },
    innerWidth: 1400, addEventListener() { }, alert() { },
    fetch: async (url, opts) => {
      requests.push({ url: String(url), method: opts?.method || 'GET', headers: { ...(opts?.headers || {}) } });
      const a = (page.answer && page.answer(String(url))) || real(url);
      if (a === 'network') throw new TypeError('Failed to fetch');
      const h = new Map(Object.entries(a.headers || {}));
      return { ok: a.status < 400, status: a.status, headers: { get: k => h.get(k.toLowerCase()) ?? null }, async json() { return JSON.parse(JSON.stringify(a.body)); } };
    },
  };
  const page = { answer, requests, sb: sandbox, app: () => bySelector('#app').innerHTML, el: bySelector };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n') + '\n;for (const k of ["S","route","boot"]) { try { globalThis[k] = eval(k); } catch { } }\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return page;
}
const settle = async () => { for (let i = 0; i < 40; i++) await new Promise(r => setTimeout(r, 0)); };
const CARD = 'Couldn’t load the data';
const real200 = () => ({ status: 200, body: INDEX });

test('data requests send no client header (the cookie is the signal); "none" renews the cookie once, "ok" never', async () => {
  const page = loadPage(u => (u === '/api/v1/status' ? { status: 200, body: {}, headers: { 'x-collegedash-session': 'none' } }
    : u === '/api/v1/programs' ? { ...real200(), headers: { 'x-collegedash-session': 'ok' } } : null));
  await settle();
  const data = page.requests.filter(r => r.url.startsWith('/api/v1/'));
  assert.ok(data.length >= 2, 'the page made its data requests');
  assert.ok(data.every(r => !('X-CollegeDash-Client' in r.headers)), JSON.stringify(data));
  const renewals = page.requests.filter(r => r.url === '/' && r.method === 'HEAD');
  assert.equal(renewals.length, 1, 'one background HEAD / for the answer that said none');
});

test('first load: a 429 shows the card with the wait, "allow cookies" only when the answer had no session, and Try again loads the page', async () => {
  let fail = true;
  const page = loadPage(u => (fail && u === '/api/v1/programs' ? { status: 429, body: {}, headers: { 'retry-after': '30', 'x-collegedash-session': 'none' } } : null));
  await settle();
  assert.ok(page.app().includes(CARD) && page.app().includes('Try again in 30 seconds, or allow cookies for this site') && page.app().includes('id="loadRetry"'), page.app().slice(0, 400));
  assert.ok(!/HTTP 429|github\.com/.test(page.app()), 'neither the raw status nor the help link is shown');
  fail = false;
  page.el('#loadRetry').onclick();
  await settle();
  assert.ok(!page.app().includes(CARD) && page.sb.S.index?.programs?.length > 0, 'Try again loaded the index');
  const session = loadPage(u => (u === '/api/v1/programs' ? { status: 429, body: {}, headers: { 'retry-after': '60', 'x-collegedash-session': 'ok' } } : null));
  await settle();
  assert.ok(session.app().includes('Try again in 60 seconds.') && !session.app().includes('allow cookies'), 'a session-tier 429 does not mention cookies');
  assert.equal(session.requests.filter(r => r.url === '/' && r.method === 'HEAD').length, 0, 'and sends no renewal');
});

test('first load: 503, a dropped connection and anything else each get the card, in words; a 401 is not special', async () => {
  for (const [ans, words] of [[{ status: 503, body: {} }, 'briefly unavailable'], ['network', 'Check your connection'],
    [{ status: 500, body: {} }, 'The data did not load. Try again.'], [{ status: 401, body: {} }, 'The data did not load. Try again.']]) {
    const page = loadPage(u => (u === '/api/v1/programs' ? ans : null));
    await settle();
    assert.ok(page.app().includes(CARD) && page.app().includes(words), `${JSON.stringify(ans)}: ${page.app().slice(0, 300)}`);
    assert.ok(!page.app().includes('refused'), 'no "refused this request" wording any more');
  }
});

test('a profile: 429 is a load failure with Try again, and only a 404 says "not built yet"', async () => {
  let status = 429;
  const page = loadPage(u => (u === `/api/v1/programs/${SLUG}` ? (status === 200 ? null : { status, body: {} }) : null));
  await settle();
  page.sb.location.hash = `#/p/${SLUG}`;
  page.sb.route(); await settle();
  assert.ok(page.app().includes(CARD) && page.app().includes('id="loadRetry"'), page.app().slice(0, 400));
  assert.ok(!page.app().includes('not been built yet'), 'a rate limit is not "not built yet"');
  status = 200;
  page.el('#loadRetry').onclick(); await settle();
  assert.ok(!page.app().includes(CARD), 'Try again rendered the profile');
  const missing = loadPage(u => (u === `/api/v1/programs/${SLUG}` ? { status: 404, body: {} } : null));
  await settle();
  missing.sb.location.hash = `#/p/${SLUG}`;
  missing.sb.route(); await settle();
  assert.ok(missing.app().includes('not been built yet') && !missing.app().includes(CARD), 'a 404 profile still says not built yet');
});

test('the camp view: a 503 shows the card', async () => {
  const page = loadPage(u => (u === '/api/v1/camps' ? { status: 503, body: {} } : null));
  await settle();
  page.sb.location.hash = '#/camps';
  page.sb.route(); await settle();
  assert.ok(page.app().includes(CARD) && page.app().includes('id="loadRetry"'), page.app().slice(0, 400));
});

test('a bug is still a bug: an error with no HTTP status keeps "Something went wrong"', () => {
  const html = fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8');
  assert.match(html, /if \(Number\.isInteger\(e\?\.status\)\) \{ app\.innerHTML = `<div class="content-body">\$\{loadFailedHtml\(e\)\}/);
  assert.match(html, /<h2>Something went wrong<\/h2>/);
});
