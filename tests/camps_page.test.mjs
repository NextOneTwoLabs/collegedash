// Issue #465 PR F: the ID Camps page body - its own filters (When, Program location, Division, Program, Shortlisted)
// in its own address, the month-grouped list, the empty states, "List refreshed", the shared past-camp helper (#71),
// the camps `program` block (#465 PR C) with the program index as the fallback, and owner decision D4: the Programs
// filters (sidebar pills, condition chips, the header search) do not narrow camps.
//
//     node --test tests/camps_page.test.mjs
//
// Same mechanism as tests/camps_view.test.mjs: the inline <script> of public/index.html runs in a `vm` against a stub
// DOM, so what runs is the real source. CAMPS_PAGE_TEST_HTML points it at another copy of the page, so main's page can
// be shown failing. Camp rows are synthetic (example.org), dated relative to today; program slugs are real index rows.
//
// What it CANNOT prove, and a human must check in a browser: layout at 320/390/768/1440 and 200% zoom, the phone
// Filters disclosure, focus after a real click, and that a screen reader reads the bar's status line.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.CAMPS_PAGE_TEST_HTML || path.join(PUBLIC, 'index.html');
const SOURCE = fs.readFileSync(HTML, 'utf8');

function makeElement(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, checked: false, disabled: false,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, contains: () => false,
  };
}
const history = [];
function loadPage() {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector,
                querySelectorAll: () => [], createElement: makeElement, addEventListener() { } },
    location: { hash: '', replace(h) { this.hash = h; } },
    history: { replaceState: (s, t, h) => { history.push(['replace', h]); sandbox.location.hash = h; },
               pushState: (s, t, h) => { history.push(['push', h]); sandbox.location.hash = h; } },
    matchMedia: () => ({ matches: false }), innerWidth: 1400, addEventListener() { },
    localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) },
    fetch: async url => {
      const rel = url === '/api/v1/programs' ? 'data/programs/index.json' : null;
      if (!rel) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      const body = fs.readFileSync(path.join(PUBLIC, rel), 'utf8');
      return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = SOURCE.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const handles = ['S', 'renderCamps', 'loadIndex', 'todayLocal', 'campsCommit', 'campsStateOf', 'campsHashOf', 'campIsPast'];
  const src = lines.slice(a + 1, b).join('\n')
    + `\n;for (const k of ${JSON.stringify(handles)}) { try { globalThis[k] = eval(k); } catch { } }`
    + `\n;globalThis.campsNow = () => { try { return eval('CAMPS'); } catch { return undefined; } };\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, el: bySelector };
}

const { sb, el } = loadPage();
await sb.loadIndex();
const S = sb.S;
const app = () => el('#app').innerHTML;
const results = () => el('#campsResults').innerHTML;
const today = sb.todayLocal();
const day = n => { const d = new Date(today + 'T12:00:00'); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const IDX = S.index.programs;
const pick = div => IDX.find(p => p.division === div && p.state && p.region && p.city);
const [P1, P2, P3] = [pick('D1'), pick('D2'), pick('D3')];
const P4 = IDX.find(p => p.division === 'D1' && p.state && p.state !== P1.state && p.region !== P1.region);
const block = p => ({ name: p.name, shortName: p.shortName ?? null, division: p.division, city: p.city, state: p.state, region: p.region });
const camp = (p, name, start, extra = {}) => ({ slug: p.slug, name, startDate: start, endDate: start, dateText: start, precision: 'day', yearInferred: false,
  location: null, ages: null, price: null, registerUrl: null, sourceUrl: 'https://example.org/camp', kind: 'camp', campType: 'id', confidence: 'heuristic', ...extra });
const FIXTURE = {
  updated: '2026-10-01T18:01:10Z', window: { from: today, to: null }, counts: { total: 9, id: 8, youth: 1, unknown: 0 },
  camps: [
    camp(P1, 'Ended Yesterday ID Camp', day(-1), { program: block(P1) }),
    camp(P1, 'Running Now ID Camp', day(-1), { endDate: day(1), program: block(P1) }),
    camp(P2, 'Soon Prospect Camp', day(5), { program: block(P2), location: 'Example Stadium', ages: '9th - 12th Grade', price: '$150.00', registerUrl: 'https://example.org/register' }),
    camp(P3, 'Later D3 ID Clinic', day(60), { yearInferred: true }),  // no program block: the index row stands in
    camp(P4, 'Far Winter ID Camp', day(200), { endDate: day(201), program: block(P4) }),
    camp(P2, 'Month Only ID Camp', day(120).slice(0, 7), { endDate: null, precision: 'month', program: block(P2) }),
    { ...camp(P1, 'Block Only ID Camp', day(30)), slug: 'not-in-the-index', program: { name: 'Example College', shortName: null, division: 'D2', city: 'Exampleton', state: 'OH', region: 'Midwest' } },
    { ...camp(P1, 'Orphan ID Camp', day(31)), slug: 'no-such-program' },
    { ...camp(P3, 'Little Kickers Day Camp', day(10)), campType: 'youth' },
  ],
};
async function open(hash) {
  S.camps = JSON.parse(JSON.stringify(FIXTURE));
  sb.location.hash = hash;
  history.length = 0;
  await sb.renderCamps();
  return app();
}
const rowsIn = html => [...html.matchAll(/<li class="camp-row" data-slug="[^"]+">[\s\S]*?<h3 class="camp-title">([^<]+)</g)].map(m => m[1]);

test('#465 the shared past helper (#71): a camp that has ended is gone, one running today stays, months compare as months', async () => {
  assert.equal(typeof sb.campIsPast, 'function', 'no shared campIsPast helper');
  const html = await open('#/camps');
  const names = rowsIn(html);
  assert.ok(!names.includes('Ended Yesterday ID Camp'), 'a camp that ended yesterday is still listed (the index is a day old)');
  assert.ok(names.includes('Running Now ID Camp'), 'a camp running today was dropped');
  assert.ok(names.includes('Month Only ID Camp'));
  assert.ok(sb.campIsPast({ precision: 'month', startDate: day(-40).slice(0, 7) }, today) && !sb.campIsPast({ precision: 'month', startDate: today.slice(0, 7) }, today));
  assert.match(SOURCE, /const isPast = it => campIsPast\(it, today\);/, 'the program tab does not use the shared helper');
});

test('#465 D4: the Programs pills, condition chips and header search do not narrow the camps page', async () => {
  Object.assign(S.filters, { conf: ['D1|Not A Conference'], region: ['Northeast'], division: ['D3'], cond: [{ field: 'admissionRate', op: '<', value: 0 }] });
  S.q = 'zzzz'; S.qRaw = 'zzzz';
  const html = await open('#/camps');
  Object.assign(S.filters, { conf: [], region: [], division: [], cond: [] }); S.q = ''; S.qRaw = '';
  assert.deepEqual(rowsIn(html).sort(), ['Block Only ID Camp', 'Far Winter ID Camp', 'Later D3 ID Clinic', 'Month Only ID Camp', 'Running Now ID Camp', 'Soon Prospect Camp'].sort());
  assert.match(html, /6 upcoming ID camps at 5 programs/);
  assert.doesNotMatch(html, /zzzz|Not A Conference|Northeast region/, 'a Programs filter is named on the camps page');
});

test('#465 the program block is read first; without one the program index row stands in; with neither the row is an orphan', async () => {
  const html = await open('#/camps');
  assert.ok(rowsIn(html).includes('Block Only ID Camp'), 'a row whose program is only in its block was dropped');
  assert.match(html, /<a href="#\/p\/not-in-the-index\/camps" class="team-name">Example College<\/a>/, 'shortName || name from the block');
  assert.match(html, new RegExp(`<a href="#/p/${P3.slug}/camps" class="team-name">${(P3.shortName || P3.name).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}</a>`), 'the index fallback');
  assert.match(html, /class="div-tag"[^>]*>D3<\/span>/, 'the division tag (division everywhere)');
  assert.ok(!html.includes('Orphan ID Camp') && /1 row could not be matched to a program/.test(html));
});

test('#465 a row reads: date, title, program, Event location / Ages / Price or "Not listed", Camp details and Register only when given', async () => {
  const html = await open('#/camps');
  const soon = html.slice(html.indexOf('Soon Prospect Camp') - 400, html.indexOf('Soon Prospect Camp') + 2200);
  assert.match(soon, /<dt>Event location<\/dt><dd>Example Stadium<\/dd>/);
  assert.match(soon, /<dt>Ages \/ grades<\/dt><dd>9th - 12th Grade<\/dd>/);
  assert.match(soon, /<dt>Price<\/dt><dd>\$150\.00<\/dd>/);
  assert.match(soon, />Camp details<span class="sr-only"> for Soon Prospect Camp, [^<]+<\/span> <span aria-hidden="true">↗<\/span><\/a>/);
  assert.match(soon, />Register<span class="sr-only">/);
  const later = html.slice(html.indexOf('Later D3 ID Clinic'), html.indexOf('Later D3 ID Clinic') + 2200);
  assert.equal((later.match(/Not listed/g) || []).length, 3, 'three missing values read Not listed');
  assert.ok(!/>Register</.test(later.slice(0, later.indexOf('</li>'))), 'Register without a registration URL');
  assert.match(later, /Year not stated · confirm date with organizer/);
  assert.match(html, /\(day not stated\)/, 'a month-only camp');
  assert.match(html, / – /, 'a multi-day camp reads as a range');
  assert.match(html, /<h2 class="camps-month-title" id="campsM\d{4}-\d{2}">[^<]+ <span class="muted">\d+ camps?<\/span><\/h2>/, 'month headings');
  assert.match(html, /List refreshed /);
  assert.doesNotMatch(html, /Camp list checked|auto-detected/);
});

test('#465 the bar: Program location is where the school is, with the coverage note; no venue filter', async () => {
  const html = await open('#/camps');
  assert.match(html, /<label class="camps-label" for="campsLoc">Program location<\/label>/);
  assert.match(html, /Where the school is, not where the camp is held: only 1 of 6 camps state a location\./);
  const opts = [...html.matchAll(/<option value="([^"]*)"/g)].map(m => m[1]).filter(Boolean);
  assert.ok(opts.every(v => /^(region|state):/.test(v) || IDX.some(p => p.slug === v) || v === 'not-in-the-index'), `unexpected options: ${opts}`);
  assert.match(html, /Shortlisted programs only/);
  assert.match(html, /data-camps-div="D1"/);
});

test('#465 the address: values are checked and the address is made canonical in place (#14\'s rules)', async () => {
  await open('#/camps?junk=1&div=D9,D2&state=tx,ZZ&region=South,Nowhere&when=30d&program=nope');
  assert.deepEqual(history, [['replace', '#/camps?when=30d&region=South&state=TX&div=D2']]);
  const st = sb.campsStateOf(`when=30d&from=${day(3)}&to=${day(1)}`, new Set());
  assert.deepEqual([st.when, st.from, st.to], [null, day(3), null], 'a range wins over a preset, and a to before from is dropped');
  assert.equal(sb.campsHashOf({ when: null, from: null, to: null, region: [], state: [], div: [], program: null }), '#/camps');
});

test('#465 the filters, from the address: division, location (region or state), program, When, a date range', async () => {
  assert.deepEqual(rowsIn(await open('#/camps?div=D3')), ['Later D3 ID Clinic']);
  assert.match(app(), /1 upcoming ID camp of 6 at 1 program/);
  assert.deepEqual(rowsIn(await open(`#/camps?state=${P4.state}`)), ['Far Winter ID Camp']);
  // a region keeps every camp whose program is in it (from the block, or the index row when there is none)
  const regionOf = c => (c.program || IDX.find(p => p.slug === c.slug))?.region;
  const want = rowsIn(await open('#/camps')).filter(n => regionOf(FIXTURE.camps.find(c => c.name === n)) === P2.region);
  assert.deepEqual(rowsIn(await open(`#/camps?region=${encodeURIComponent(P2.region)}`)), want);
  assert.ok(want.includes('Soon Prospect Camp'));
  assert.deepEqual(rowsIn(await open(`#/camps?program=${P4.slug}`)), ['Far Winter ID Camp']);
  // Next 30 days: today through today + 30, a camp that overlaps it included (Block Only starts on day 30)
  assert.deepEqual(rowsIn(await open('#/camps?when=30d')), ['Running Now ID Camp', 'Soon Prospect Camp', 'Block Only ID Camp']);
  assert.deepEqual(rowsIn(await open(`#/camps?from=${day(50)}&to=${day(70)}`)), ['Later D3 ID Clinic']);
});

test('#465 Shortlisted programs only: reads the visitor\'s Shortlist, and is never in the address', async () => {
  S.favorites = new Set([P4.slug]); S.campsSaved = true;
  const html = await open('#/camps');
  S.campsSaved = false; S.favorites = new Set();
  assert.deepEqual(rowsIn(html), ['Far Winter ID Camp']);
  assert.ok(!history.some(([, h]) => /saved|short/i.test(h)), `the toggle reached the address: ${JSON.stringify(history)}`);
});

test('#465 a commit pushes one history entry and updates the list in place, with the count in the bar\'s status line', async () => {
  await open('#/camps');
  const st = sb.campsNow().st;
  sb.campsCommit({ ...st, div: ['D3'] }, 'div-D3');
  assert.deepEqual(history, [['push', '#/camps?div=D3']]);
  assert.deepEqual(rowsIn(results()), ['Later D3 ID Clinic'], 'the list was not updated in place');
  assert.match(el('#campsStatus').textContent, /^1 upcoming ID camp of 6 at 1 program\.$/);
});

test('#465 empty states say "found in our sources", never that no camp exists', async () => {
  let html = await open(`#/camps?program=${IDX.find(p => ![P1, P2, P3, P4].includes(p)).slug}`);
  assert.match(html, /No upcoming ID camp found in our sources for these filters/);
  assert.match(html, /a camp may exist that is not listed here/);
  S.camps = { updated: FIXTURE.updated, window: FIXTURE.window, counts: { total: 0, id: 0, youth: 0, unknown: 0 }, camps: [] };
  sb.location.hash = '#/camps';
  await sb.renderCamps();
  html = app();
  assert.match(html, /No upcoming ID camp found in our sources</);
});

test('#465 the Programs sidebar is not drawn on the camps page (D4), and the page never re-reads the Programs filters', () => {
  assert.match(SOURCE, /body\.view-camps \.sidebar, body\.view-camps \.sidebar-overlay, body\.view-camps #sidebarToggle \{ display: none !important; \}/);
  assert.match(SOURCE, /document\.body\.classList\.toggle\('view-camps', view === 'camps'\)/);
  const body = SOURCE.slice(SOURCE.indexOf('function campsMatch('), SOURCE.indexOf('/* ---------- trends'));
  assert.ok(!/matchesFilters|S\.filters\.(conf|region|division|cond)|S\.q\b/.test(body.replace(/S\.filters\.view/g, '')), 'the camps page reads a Programs filter');
});
