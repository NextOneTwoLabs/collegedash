// Issue #79: a camp page we could not read says so, on the program page and (as one count) on the ID Camps page.
//
//     node --test tests/camps_unreadable.test.mjs
//
// The program page (tabCamps): a camps block whose `unreadable` names a cause (app-shell, not-a-listing, not-html)
// says "The camp page could not be read automatically; open it for dates." and never "No upcoming ID camps listed".
// A block with `unreadable: null` reads as before.
//
// The ID Camps page: one line from the camps index's `coverage` block, "Camp pages for N programs could not be read
// automatically, so their camps may be missing.", N = unreadable (all causes) + fetchFailed + refusedHost. Hidden at
// N = 0 and when the index carries no `coverage` (an older index).
//
// Same mechanism as tests/camps_page.test.mjs: the inline <script> of public/index.html runs in a `vm` against a stub
// DOM. CAMPS_UNREADABLE_TEST_HTML points it at another copy of the page, so main's page can be shown failing. Every
// profile and index here is synthetic (example.org); the camps are dated relative to today.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.CAMPS_UNREADABLE_TEST_HTML || path.join(PUBLIC, 'index.html');
const SOURCE = fs.readFileSync(HTML, 'utf8');

function makeElement(name) {
  const classes = new Set(), attrs = new Map();
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, checked: false, disabled: false,
    dataset: {}, style: {},
    classList: { add: (...c) => c.forEach(x => classes.add(x)), remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle(c, on) { const v = on === undefined ? !classes.has(c) : !!on; if (v) classes.add(c); else classes.delete(c); return v; }, contains: c => classes.has(c) },
    setAttribute: (k, v) => attrs.set(k, String(v)), getAttribute: k => (attrs.has(k) ? attrs.get(k) : null), removeAttribute: k => attrs.delete(k),
    addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, contains: () => false,
  };
}
let SERVED_CAMPS = null;  // what /api/v1/camps answers, so a test can go through the page's own loadCamps
function loadPage() {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector,
                querySelectorAll: () => [], createElement: makeElement, addEventListener() { } },
    location: { hash: '', replace(h) { this.hash = h; } },
    history: { replaceState: (s, t, h) => { sandbox.location.hash = h; }, pushState: (s, t, h) => { sandbox.location.hash = h; } },
    matchMedia: () => ({ matches: false, addEventListener() { } }), innerWidth: 1400, addEventListener() { },
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    fetch: async url => {
      if (url === '/api/v1/camps' && SERVED_CAMPS) { const body = JSON.stringify(SERVED_CAMPS); return { ok: true, status: 200, async json() { return JSON.parse(body); } }; }
      if (url !== '/api/v1/programs') return { ok: false, status: 404, async json() { throw new Error('404'); } };
      const body = fs.readFileSync(path.join(PUBLIC, 'data/programs/index.json'), 'utf8');
      return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = SOURCE.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const handles = ['S', 'tabCamps', 'renderCamps', 'loadIndex', 'loadCamps', 'todayLocal'];
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(handles)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, el: bySelector };
}

const { sb, el } = loadPage();
await sb.loadIndex();
const today = sb.todayLocal();
const day = n => { const d = new Date(today + 'T12:00:00'); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

/* ---------- the program page ---------- */
const COULD_NOT = 'The camp page could not be read automatically; open it for dates.';
const NONE_LISTED = /No upcoming ID camps listed on the camp page/;
const profile = (camps) => ({ slug: 'example', links: { athletics: 'https://athletics.example.org' }, _build: { skipped: [], failed: [] },
  camps: { url: 'https://camps.example.org/', finalUrl: 'https://camps.example.org/', host: 'camps.example.org', vendor: 'external',
    discoveredVia: 'anchor', robotsBlocked: false, fetchError: null, hostRefused: false, parsed: true, unreadable: null,
    items: [], _meta: [{ source: 'camps', url: 'https://camps.example.org/', asOf: '2026-10-21T15:55:01Z' }], ...camps } });

for (const [cause, parsed] of [['app-shell', true], ['not-a-listing', true], ['not-a-listing', false], ['not-html', false]]) {
  test(`#79 program page: unreadable ${cause} (parsed ${parsed}) says "could not be read automatically", never "No upcoming ID camps listed"`, async () => {
    const html = await sb.tabCamps(profile({ unreadable: { cause }, parsed }));
    assert.ok(html.includes(COULD_NOT), `no "could not be read" line for ${cause}`);
    assert.doesNotMatch(html, NONE_LISTED, `${cause} still reads as an empty listing`);
    assert.equal(html.split(COULD_NOT).length - 1, 1, 'the line is said once');
    assert.match(html, /Camp page on camps\.example\.org/, 'the link to the page is still offered');
  });
}

test('#79 program page: a page that was read with nothing dated (unreadable null) still says "No upcoming ID camps listed"', async () => {
  const html = await sb.tabCamps(profile({}));
  assert.match(html, NONE_LISTED);
  assert.ok(!html.includes(COULD_NOT));
});

test('#79 program page: an older profile with no `unreadable` key reads exactly as before', async () => {
  const p = profile({}); delete p.camps.unreadable; delete p.camps.hostRefused;
  assert.match(await sb.tabCamps(p), NONE_LISTED);
  const pdf = profile({ parsed: false }); delete pdf.camps.unreadable;
  assert.ok((await sb.tabCamps(pdf)).includes(COULD_NOT), 'parsed false alone still reads as unreadable');
});

test('#79 program page: a cause with an upcoming news camp still lists the camp, under the "could not be read" line', async () => {
  const camp = { kind: 'news', name: 'Fall ID Clinic', startDate: day(10), endDate: day(10), precision: 'day', confidence: 'heuristic' };
  const html = await sb.tabCamps(profile({ unreadable: { cause: 'app-shell' }, items: [camp] }));
  assert.match(html, /<h3>Upcoming camps<\/h3>[\s\S]*Fall ID Clinic/);
  assert.ok(html.includes(COULD_NOT));
});

test('#79 program page: a fetch error or robots block keeps its own message, and gains no second one', async () => {
  const fe = await sb.tabCamps(profile({ fetchError: 'HTTP 404', parsed: false }));
  assert.match(fe, /could not be read on the last check/);
  assert.ok(!fe.includes(COULD_NOT));
  const rb = await sb.tabCamps(profile({ robotsBlocked: true, parsed: false }));
  assert.match(rb, /robots\.txt/);
  assert.ok(!rb.includes(COULD_NOT));
});

/* ---------- the ID Camps page ---------- */
const IDX = sb.S.index.programs;
const P1 = IDX.find(p => p.division === 'D1' && p.state && p.region);
const camp = (name, start) => ({ slug: P1.slug, name, startDate: start, endDate: start, dateText: start, precision: 'day', yearInferred: false,
  location: null, ages: null, price: null, registerUrl: null, sourceUrl: 'https://example.org/camp', kind: 'camp', campType: 'id', confidence: 'heuristic',
  program: { name: P1.name, shortName: P1.shortName ?? null, division: P1.division, city: P1.city, state: P1.state, region: P1.region } });
const COVERAGE = { programs: 1011, withRows: 118, readNothingDated: 477, unreadable: { 'app-shell': 129, 'not-a-listing': 22, 'not-html': 8 },
  fetchFailed: 14, refusedHost: 23, robots: 22, noLink: 129, skipped: 69 };
async function open(coverage, rows = [camp('Soon ID Camp', day(5))]) {
  const doc = { updated: '2026-10-21T16:21:00Z', window: { from: today, to: null }, counts: { total: rows.length, id: rows.length, youth: 0, unknown: 0 }, camps: rows };
  if (coverage !== undefined) doc.coverage = coverage;
  sb.S.camps = JSON.parse(JSON.stringify(doc));
  sb.location.hash = '#/camps';
  await sb.renderCamps();
  return el('#app').innerHTML;
}
const line = n => `Camp pages for ${n} programs could not be read automatically, so their camps may be missing.`;

test('#79 ID Camps: one line, N = unreadable (every cause) + fetch failed + refused host; robots and no-link left out', async () => {
  const html = await open(COVERAGE);
  const n = 129 + 22 + 8 + 14 + 23;
  assert.ok(html.includes(line(n)), `expected "${line(n)}"`);
  assert.equal(html.split('could not be read automatically, so their camps may be missing').length - 1, 1, 'said once');
  assert.ok(!html.includes(line(n + 22)) && !html.includes(line(n + 129)), 'robots or no-link counted in');
});

test('#79 ID Camps: the line names no program and no host (counts only)', async () => {
  const html = await open(COVERAGE);
  const at = html.indexOf('Camp pages for');
  assert.ok(at >= 0, 'no coverage line to check');
  const p = html.slice(html.lastIndexOf('<p', at), html.indexOf('</p>', at));
  assert.doesNotMatch(p, /href|\.com|\.edu|data-slug/);
});

test('#79 ID Camps: one program reads in the singular', async () => {
  const html = await open({ ...COVERAGE, unreadable: { 'app-shell': 1, 'not-a-listing': 0, 'not-html': 0 }, fetchFailed: 0, refusedHost: 0 });
  assert.ok(html.includes('Camp pages for 1 program could not be read automatically, so their camps may be missing.'));
});

test('#79 ID Camps: the line is shown on the empty page too', async () => {
  const html = await open(COVERAGE, []);
  assert.ok(html.includes(line(196)));
});

test('#79 ID Camps: hidden when N is 0', async () => {
  const html = await open({ ...COVERAGE, unreadable: { 'app-shell': 0, 'not-a-listing': 0, 'not-html': 0 }, fetchFailed: 0, refusedHost: 0 });
  assert.doesNotMatch(html, /Camp pages for \d+ programs? could not be read/);
});

test('#79 ID Camps: hidden for an older index with no coverage block, or a malformed one', async () => {
  for (const cov of [undefined, null, 'lots', { programs: 3 }, { unreadable: 'x', fetchFailed: 'many' }]) {
    const html = await open(cov);
    assert.doesNotMatch(html, /Camp pages for \d+ programs? could not be read/, `shown for ${JSON.stringify(cov)}`);
    assert.match(html, /Soon ID Camp/, 'the camps still render');
  }
});

test('#79 ID Camps: the line survives the page loading the camps index itself (loadCamps keeps `coverage`)', async () => {
  SERVED_CAMPS = { updated: '2026-10-21T16:21:00Z', window: { from: today, to: null }, counts: { total: 1, id: 1, youth: 0, unknown: 0 },
    coverage: COVERAGE, camps: [camp('Soon ID Camp', day(5))] };
  try {
    sb.S.camps = null;
    sb.location.hash = '#/camps';
    await sb.renderCamps();
    assert.deepEqual(JSON.parse(JSON.stringify(sb.S.camps.coverage ?? null)), COVERAGE, 'loadCamps dropped `coverage`');
    assert.ok(el('#app').innerHTML.includes(line(196)), 'no coverage line after a real load');
  } finally { SERVED_CAMPS = null; }
});
