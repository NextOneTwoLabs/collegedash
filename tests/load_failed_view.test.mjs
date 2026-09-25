// The "couldn't load, try again" state of every data load (issue #345, plan section 2.4).
//
//     node --test tests/load_failed_view.test.mjs
//
// Once the API gate enforces, a site request can be refused (401), rate-limited (429) or unanswered (503), and a
// connection can drop. Each data load a visitor waits on must then show a card that says so, with a Try again
// button that works - not a blank page, a raw "HTTP 429", or "Profile not built yet" for a profile that exists.
// Same mechanism as tests/table_sort.test.mjs: the page's inline <script> runs in a vm against a stub DOM, and
// fetch is a stub whose answers each test sets. Every request's headers are recorded, to check the client header.
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
      requests.push({ url: String(url), headers: { ...(opts?.headers || {}) } });
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

test('every data request carries X-CollegeDash-Client: web', async () => {
  const page = loadPage(null);
  await settle();
  const data = page.requests.filter(r => r.url.startsWith('/api/v1/'));
  assert.ok(data.length >= 2, 'the page made its data requests');
  assert.ok(data.every(r => r.headers['X-CollegeDash-Client'] === 'web'), JSON.stringify(data));
});

test('first load: a 429 shows the card with the wait, and Try again loads the page', async () => {
  let fail = true;
  const page = loadPage(u => (fail && u === '/api/v1/programs' ? { status: 429, body: {}, headers: { 'retry-after': '30' } } : null));
  await settle();
  assert.ok(page.app().includes(CARD) && page.app().includes('Wait 30 seconds') && page.app().includes('id="loadRetry"'), page.app().slice(0, 400));
  assert.ok(!/HTTP 429/.test(page.app()), 'the raw status is not the message');
  fail = false;
  page.el('#loadRetry').onclick();
  await settle();
  assert.ok(!page.app().includes(CARD) && page.sb.S.index?.programs?.length > 0, 'Try again loaded the index');
});

test('first load: 401, 503 and a dropped connection each get the card, in words', async () => {
  for (const [ans, words] of [[{ status: 401, body: {} }, 'refused this request'], [{ status: 503, body: {} }, 'briefly unavailable'], ['network', 'did not load']]) {
    const page = loadPage(u => (u === '/api/v1/programs' ? ans : null));
    await settle();
    assert.ok(page.app().includes(CARD) && page.app().includes(words), `${JSON.stringify(ans)}: ${page.app().slice(0, 300)}`);
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
