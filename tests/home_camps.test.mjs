// Issue #465: Home's camp preview (owner decision D2) - the next three upcoming ID camps and the live count, from
// /api/v1/camps, fetched only on Home and only after the page has drawn. The three destinations never wait on it and
// still draw when it fails. Rows are named from their `program` block (#468), and until the first refresh after #468
// from the program index; the past rule and the order are the ID Camps page's own (PR F's campIsPast and campCmp).
//
//     node --test tests/home_camps.test.mjs
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM. HOME_CAMPS_TEST_HTML points it at
// another copy of the page (e.g. #470's, before the preview), to show these checks failing there. Camp rows are
// synthetic (example.org), dated relative to today; program slugs are real index rows.
//
// What it CANNOT prove, and a human must check in a browser: that the request really goes after first paint, the layout
// at phone width, and a screen reader's reading of the rows.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const SOURCE = fs.readFileSync(process.env.HOME_CAMPS_TEST_HTML || path.join(PUBLIC, 'index.html'), 'utf8');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));

function makeElement(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, dataset: {}, style: {},
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, removeAttribute() { }, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null, matches: () => false, focus() { }, contains: () => false,
  };
}
function loadPage({ camps, index = INDEX, hash = '#/' } = {}) {
  const els = new Map(), fetchLog = [];
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector,
                querySelectorAll: () => [], createElement: makeElement, addEventListener() { } },
    location: { hash, replace(h) { this.hash = h; } }, history: { replaceState() { }, pushState() { } },
    matchMedia: () => ({ matches: false }), innerWidth: 1400, addEventListener() { },
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    fetch: async url => {
      fetchLog.push(url);
      if (url === '/api/v1/programs' && index) return { ok: true, status: 200, async json() { return JSON.parse(JSON.stringify(index)); } };
      if (url === '/api/v1/camps' && camps) return { ok: true, status: 200, async json() { return JSON.parse(JSON.stringify(camps)); } };
      return { ok: false, status: 503, headers: { get: () => null }, async json() { throw new Error('503'); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = SOURCE.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const handles = ['S', 'renderHome', 'renderList', 'loadIndex', 'todayLocal', 'route'];
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(handles)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, el: bySelector, fetchLog };
}
const settle = (ms = 30) => new Promise(r => setTimeout(r, ms));
const today = (() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; })();
const day = n => { const d = new Date(today + 'T12:00:00'); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const [P1, P2, P3] = [INDEX.programs.find(p => p.division === 'D1'), INDEX.programs.find(p => p.division === 'D2'), INDEX.programs.find(p => p.division === 'D3')];
const block = p => ({ name: p.name, shortName: p.shortName ?? null, division: p.division, city: p.city, state: p.state, region: p.region });
const camp = (p, name, start, extra = {}) => ({ slug: p.slug, name, startDate: start, endDate: start, dateText: start, precision: 'day', yearInferred: false,
  location: null, ages: null, price: null, registerUrl: null, sourceUrl: 'https://example.org/c', kind: 'camp', campType: 'id', confidence: 'heuristic', ...extra });
const CAMPS = { updated: '2026-10-01T18:01:10Z', window: { from: today, to: null }, counts: { total: 6, id: 5, youth: 1, unknown: 0 },
  camps: [
    camp(P1, 'Over Yesterday ID Camp', day(-1), { program: block(P1) }),
    camp(P2, 'Third ID Camp', day(20), { program: block(P2) }),
    camp(P3, 'First ID Camp', day(2), { location: 'Example Field' }),  // no block: the index row names it
    { ...camp(P1, 'Second ID Camp', day(9)), slug: 'not-in-index', program: { name: 'Example College', shortName: null, division: 'D2', city: 'Exampleton', state: 'OH', region: 'Midwest' } },
    camp(P1, 'Fourth ID Camp', day(40), { program: block(P1) }),
    { ...camp(P2, 'Little Kickers Camp', day(1)), campType: 'youth' },
  ] };

test('#465 first paint: the three destinations and "View all camps" are drawn before any camp request', async () => {
  const pg = loadPage({ camps: CAMPS });
  await pg.sb.loadIndex();
  pg.fetchLog.length = 0;
  pg.sb.renderHome();
  const html = pg.el('#app').innerHTML;
  assert.deepEqual([...html.matchAll(/<a class="home-entry" href="([^"]+)"/g)].map(m => m[1]), ['#/programs', '#/camps', '#/trends']);
  assert.match(html, /<a href="#\/camps">View all camps/, 'no "View all camps" on Home');
  assert.deepEqual(pg.fetchLog, [], 'Home asked for the camps before it had drawn');
  await settle();
  assert.deepEqual(pg.fetchLog, ['/api/v1/camps'], 'the preview did not load the camps once, after the draw');
});

test('#465 the preview: the next three upcoming ID camps, soonest first, named from the block or the index, with the live count', async () => {
  const pg = loadPage({ camps: CAMPS });
  await pg.sb.loadIndex();
  pg.sb.renderHome(); await settle();
  const body = pg.el('#homeCampsBody').innerHTML;
  const names = [...body.matchAll(/<b>([^<]+)<\/b> · ([^<]+?)(?: · |<\/span>)/g)].map(m => m[2]);
  assert.deepEqual(names, ['First ID Camp', 'Second ID Camp', 'Third ID Camp'], 'not the next three, in order (a past or youth camp slipped in)');
  assert.ok(body.includes(`<b>${P3.shortName || P3.name}</b>`), 'a row without a block was not named from the index');
  assert.ok(body.includes('<b>Example College</b>'), 'a row named only by its block was dropped');
  assert.ok(body.includes('Example Field'), 'a stated event location is not shown');
  assert.match(body, /<a href="#\/p\/[a-z0-9-]+\/camps">Camp details<span class="sr-only"> for First ID Camp/);
  assert.equal(pg.el('#homeCampsCount').textContent, '4 upcoming ID camps at 4 programs', 'the count on the ID Camps entry');
});

test('#465 the count is live: computed from the document, never written into the page', async () => {
  const fewer = { ...CAMPS, camps: CAMPS.camps.slice(0, 3) };
  const pg = loadPage({ camps: fewer });
  await pg.sb.loadIndex();
  pg.sb.renderHome(); await settle();
  assert.equal(pg.el('#homeCampsCount').textContent, '2 upcoming ID camps at 2 programs');
  assert.ok(!/\b86 upcoming ID camps\b/.test(SOURCE.slice(SOURCE.indexOf('<script>'))), 'a camp count is written into the page source');
});

test('#465 a failed preview leaves the destinations, says so in a sentence, and keeps "View all camps"', async () => {
  const pg = loadPage({ camps: null });
  await pg.sb.loadIndex();
  pg.sb.renderHome();
  const before = pg.el('#app').innerHTML;
  await settle();
  assert.equal(pg.el('#app').innerHTML, before, 'the page was redrawn by the failed preview');
  assert.match(pg.el('#homeCampsBody').innerHTML, /couldn’t be loaded/);
  assert.equal(pg.el('#homeCampsCount').textContent, '', 'a count was shown with no data');
});

test('#465 without the program index (it failed on Home), rows with a block are still listed', async () => {
  const pg = loadPage({ camps: CAMPS, index: null });
  pg.sb.renderHome('<div class="card">index failed</div>'); await settle();
  const body = pg.el('#homeCampsBody').innerHTML;
  assert.ok(body.includes('Example College') && !body.includes('First ID Camp'), 'block rows should show; the blockless one cannot be named');
});

test('#465 Home only: the Programs page makes no camps request, and leaving Home before the data writes nothing', async () => {
  const pg = loadPage({ camps: CAMPS, hash: '#/programs' });
  await pg.sb.loadIndex();
  pg.fetchLog.length = 0;
  await pg.sb.renderList(); await settle();
  assert.ok(!pg.fetchLog.includes('/api/v1/camps'), 'the Programs page fetched the camps');
  pg.sb.location.hash = '#/';
  pg.sb.renderHome();
  pg.sb.location.hash = '#/programs';  // the visitor leaves before the preview's turn
  await settle();
  assert.equal(pg.el('#homeCampsBody').innerHTML.includes('<ul'), false, 'the preview wrote into a page the visitor had left');
});
