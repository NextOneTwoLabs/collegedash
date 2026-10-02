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
import { parseCss, decls } from './lib/css_cascade.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.CAMPS_PAGE_TEST_HTML || path.join(PUBLIC, 'index.html');
const SOURCE = fs.readFileSync(HTML, 'utf8');

const FOCUSED = { el: null };
function makeElement(name) {
  const classes = new Set(), attrs = new Map(), listeners = {};
  return {
    _name: name, _listeners: listeners, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, checked: false, disabled: false,
    dataset: {}, style: {},
    classList: { add: (...c) => c.forEach(x => classes.add(x)), remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle(c, on) { const v = on === undefined ? !classes.has(c) : !!on; if (v) classes.add(c); else classes.delete(c); return v; }, contains: c => classes.has(c) },
    setAttribute: (k, v) => attrs.set(k, String(v)), getAttribute: k => (attrs.has(k) ? attrs.get(k) : null), removeAttribute: k => attrs.delete(k),
    addEventListener(t, fn) { (listeners[t] ||= []).push(fn); }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { FOCUSED.el = this; }, contains: () => false,
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
  const handles = ['S', 'renderCamps', 'loadIndex', 'todayLocal', 'campsCommit', 'campsStateOf', 'campsHashOf', 'campIsPast', 'campsSheet', 'setQuery', 'route'];
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
const settle = ms => new Promise(r => setTimeout(r, ms));
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
  // #465 B's one mechanism: a view in NO_RAIL draws no Programs sidebar and no button to open one
  assert.match(SOURCE, /const NO_RAIL = new Set\(\[[^\]]*'camps'[^\]]*\]\)/, 'ID Camps is not in NO_RAIL');
  assert.match(SOURCE, /body\.no-rail \.sidebar, body\.no-rail \.sidebar-overlay, body\.no-rail \.hamburger \{ display: none; \}/);
  assert.ok(!/view-camps/.test(SOURCE), 'a second hiding mechanism (body.view-camps) is left over');
  const body = SOURCE.slice(SOURCE.indexOf('function campsMatch('), SOURCE.indexOf('/* ---------- trends'));
  assert.ok(!/matchesFilters|S\.filters\.(conf|region|division|cond)|S\.q\b/.test(body.replace(/S\.filters\.view/g, '')), 'the camps page reads a Programs filter');
});

test('#465 D4: a search made on Programs is not applied to ID Camps - the full list shows, and typing there changes nothing', async () => {
  S.camps = JSON.parse(JSON.stringify(FIXTURE));
  sb.location.hash = '#/programs';
  sb.setQuery('stanford');  // what a visitor typed in the header box on Programs
  await settle(120);
  assert.equal(S.q, 'stanford', 'fixture: the Programs search did not take');
  sb.location.hash = '#/camps';
  await sb.renderCamps();
  const html = app();
  assert.deepEqual(rowsIn(html).sort(), ['Block Only ID Camp', 'Far Winter ID Camp', 'Later D3 ID Clinic', 'Month Only ID Camp', 'Running Now ID Camp', 'Soon Prospect Camp'].sort(),
    'the Programs search narrowed the camps');
  assert.match(html, /6 upcoming ID camps at 5 programs/);
  assert.doesNotMatch(html, /programs matching|search matches program names|Clear search/i, 'the Programs query is named on the camps page');
  // and typing in the (hidden) box while on ID Camps does not redraw or narrow it
  el('#campsResults').innerHTML = 'UNCHANGED';
  sb.setQuery('duke'); await settle(120);
  assert.equal(el('#campsResults').innerHTML, 'UNCHANGED', 'typing redrew the camps list');
  sb.setQuery(''); await settle(120);
});

/* ---------- the camps page's own sidebar (owner, 2026-10-02): a left column on a wide screen, a sheet on a phone ---------- */
const CSS = parseCss([...SOURCE.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n'));
const css = (at, sel, prop) => CSS.filter(r => r.at.join(' ') === at && r.selectors.includes(sel)).flatMap(r => decls(r.body)).filter(d => d.prop === prop).map(d => d.value).pop();
const PHONE = '@media (max-width: 768px)';

test('#465 the filters are a sidebar beside the list, in the decided order, with the chips and count beside it', async () => {
  const html = await open('#/camps');
  const side = (/<aside class="camps-side" id="campsBar" aria-labelledby="campsSideTitle">([\s\S]*?)<\/aside>/.exec(html) || [])[1] || '';
  assert.ok(side, 'no camps sidebar');
  assert.match(side, /<h2 class="camps-side-title" id="campsSideTitle" tabindex="-1">Filter camps<\/h2>/);
  const order = ['campsWhenLabel', 'campsLoc', 'campsDivLabel', 'campsProgram', 'campsSaved'].map(id => side.indexOf(`id="${id}"`));
  assert.ok(order.every(i => i >= 0) && order.every((v, i) => !i || v > order[i - 1]), `When, Program location, Division, Program, Shortlisted: ${order}`);
  assert.ok(!/class="camps-bar"/.test(html), 'the old top filter bar is still drawn');
  const main = html.slice(html.indexOf('<div class="camps-main" id="campsMain">'));
  assert.match(main, /<button type="button" class="btn camps-more-btn" id="campsMoreBtn" aria-haspopup="dialog" aria-expanded="false" aria-controls="campsBar"/);
  assert.ok(main.indexOf('id="campsActive"') >= 0 && main.indexOf('id="campsStatus"') >= 0 && main.indexOf('id="campsResults"') >= 0);
  assert.match(html, /<div class="camps-backdrop" id="campsBackdrop" hidden><\/div>/);
});

test('#465 CSS: a left column on desktop, sticky; on a phone a bottom sheet over the page, the header and the bottom bar', () => {
  assert.equal(css('', '.camps-layout', 'grid-template-columns'), '260px minmax(0, 1fr)');
  assert.equal(css('', '.camps-side', 'position'), 'sticky');
  assert.equal(css(PHONE, '.camps-layout', 'grid-template-columns'), 'minmax(0, 1fr)');
  assert.equal(css(PHONE, '.camps-side', 'display'), 'none', 'the sheet shows before it is opened');
  assert.equal(css(PHONE, '.camps-side', 'position'), 'fixed');
  assert.equal(css(PHONE, '.camps-side.open', 'display'), 'flex');
  assert.ok(Number(css(PHONE, '.camps-side', 'z-index')) > Number(css('', '.camps-backdrop', 'z-index')), 'the sheet is under its own backdrop');
  assert.ok(Number(css('', '.camps-backdrop', 'z-index')) >= 60, 'the backdrop must cover the bottom bar (#470 keeps the bar under 60)');
  // Huatuo on #471: the fixed header (z-index 100) drew over the sheet and stayed tappable
  const headerZ = Number(css('', '.header', 'z-index'));
  assert.ok(headerZ >= 100 && Number(css('', '.camps-backdrop', 'z-index')) > headerZ, 'the header draws over the backdrop');
  assert.equal(css(PHONE, '.camps-more-btn', 'display'), 'inline-flex', 'no Filters button on a phone');
  for (const sel of ['.camps-more-btn', '.camps-sheet-close', '.camps-sheet-foot']) assert.equal(css('', sel, 'display'), 'none', `${sel} shows on desktop`);
  assert.equal(css(PHONE, '.camps-sheet-close', 'min-height'), '44px');
});

test('#465 the phone sheet: a modal dialog that takes focus, and gives it back to Filters (or the list) when it closes', async () => {
  await open('#/camps');
  const side = el('#campsBar'), back = el('#campsBackdrop'), btn = el('#campsMoreBtn');
  sb.campsSheet(true);
  assert.ok(side.classList.contains('open') && side.getAttribute('role') === 'dialog' && side.getAttribute('aria-modal') === 'true');
  assert.equal(back.hidden, false, 'no backdrop');
  assert.equal(btn.getAttribute('aria-expanded'), 'true');
  assert.equal(FOCUSED.el, el('#campsSideTitle'), 'focus did not move into the sheet');
  sb.campsSheet(false);
  assert.ok(!side.classList.contains('open') && side.getAttribute('role') === null && side.getAttribute('aria-modal') === null);
  assert.equal(back.hidden, true);
  assert.equal(FOCUSED.el, btn, 'focus did not go back to Filters');
  sb.campsSheet(true); sb.campsSheet(false, { focus: 'list' });
  assert.equal(FOCUSED.el, el('#campsResults h2'), '"Show N camps" did not take the reader to the list');
  // Escape closes it, through the page's own keydown listener on the sheet
  sb.campsSheet(true);
  const ev = { key: 'Escape', shiftKey: false, prevented: false, preventDefault() { this.prevented = true; } };
  for (const fn of side._listeners.keydown || []) fn(ev);
  assert.ok(!side.classList.contains('open') && ev.prevented, 'Escape did not close the sheet');
});

/* Huatuo on #471: aria-modal alone hides nothing from Tab, a tap or every screen reader, so while the sheet is open
   everything else is inert. The stub DOM gets the page's real shape (index.html's body > header, bottom bar, layout >
   [rail, #main > [#app, the recs elements, the footer]]), so the walk from the sheet up to <body> meets the same
   siblings it meets in a browser. */
function pageTree() {
  const kids = (parent, children) => { parent.children = children; for (const c of children) c.parentElement = parent; };
  const body = sb.document.body, layout = makeElement('div.layout#layout'), content = makeElement('div.content-body'), campsLayout = makeElement('div.camps-layout');
  const R = {
    header: el('.header'), bottomNav: el('.bottom-nav'), sidebar: el('#sidebar'),
    pageHead: makeElement('div.page-header'), lead: makeElement('p.camps-lead'), campsMain: el('#campsMain'),
    recsToast: el('#recsToast'), recsCount: el('#recsCount'), recsTiming: el('#recsTiming'), footer: makeElement('footer.site-notice'),
  };
  const keep = { side: el('#campsBar'), back: el('#campsBackdrop'), main: el('#main'), app: el('#app'), layout, content, campsLayout };
  kids(body, [R.header, R.bottomNav, layout]);
  kids(layout, [R.sidebar, keep.main]);
  kids(keep.main, [keep.app, R.recsToast, R.recsCount, R.recsTiming, R.footer]);
  kids(keep.app, [R.pageHead, content]);
  kids(content, [R.lead, campsLayout, keep.back]);
  kids(campsLayout, [keep.side, R.campsMain]);
  for (const e of [body, ...Object.values(keep), ...Object.values(R)]) e.inert = false;
  return { R, keep };
}
const noneInert = (R, keep, how) => {
  for (const [k, e] of Object.entries({ ...R, ...keep })) assert.equal(e.inert, false, `${how}: ${k} is still inert`);
};

test('#465 the phone sheet is modal: the header, the bottom bar, the Programs rail and the rest of the page are inert while it is open, and none is after any close', async () => {
  await open('#/camps');
  const { R, keep } = pageTree();
  const side = keep.side, btn = el('#campsMoreBtn');
  const tap = sel => ({ target: { closest: s => (s === sel ? {} : null) } });
  const fire = (node, type, ev) => { for (const fn of node._listeners[type] || []) fn(ev); };
  const closes = {
    '✕': () => fire(side, 'click', tap('#campsSheetClose')),
    'Show N camps': () => fire(side, 'click', tap('#campsShow')),
    'Escape': () => fire(side, 'keydown', { key: 'Escape', shiftKey: false, preventDefault() { } }),
    'the backdrop': () => keep.back.onclick(),
  };
  for (const [how, close] of Object.entries(closes)) {
    fire(R.campsMain, 'click', tap('#campsMoreBtn'));  // the Filters button
    assert.ok(side.classList.contains('open'), `fixture: Filters did not open the sheet (${how})`);
    for (const [k, e] of Object.entries(R)) assert.equal(e.inert, true, `open: ${k} is not inert`);
    // the sheet, its backdrop (the tap that closes it) and every ancestor of the sheet stay live, or the sheet is dead too
    for (const [k, e] of Object.entries(keep)) assert.equal(e.inert, false, `open: ${k} is inert, so the sheet is too`);
    close();
    assert.ok(!side.classList.contains('open'), `${how} did not close the sheet`);
    noneInert(R, keep, `closed by ${how}`);
    assert.equal(FOCUSED.el, how === 'Show N camps' ? el('#campsResults h2') : btn, `${how}: focus did not go back`);
  }
  // an element that was inert before the sheet opened (for its own reason) is still inert after it closes
  R.recsTiming.inert = true;
  sb.campsSheet(true); sb.campsSheet(false);
  assert.equal(R.recsTiming.inert, true, 'closing the sheet cleared an inert it did not set');
  R.recsTiming.inert = false;
  // leaving with the sheet open (Back, a link) does not leave the page inert
  sb.campsSheet(true);
  assert.equal(R.header.inert, true, 'fixture: the sheet did not open');
  sb.location.hash = '#/camps?div=D3';
  sb.route();
  await settle(50);
  noneInert(R, keep, 'a route change');
});

test('#465 planted text in the camps address is dropped by the allowlists, never drawn (#14)', async () => {
  const html = await open('#/camps?program=%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E&state=%22%3E%3Csvg%20onload%3Dalert(1)%3E'
    + '&region=%3Cscript%3Ealert(1)%3C%2Fscript%3E&div=%3Cb%3ED1&when=%22%3E30d&from=%3Cimg%3E&to=2030-01-01%22%3E');
  assert.deepEqual(history, [['replace', '#/camps']], 'a planted value survived into the canonical address');
  const st = sb.campsNow().st;
  assert.equal(JSON.stringify([st.when, st.from, st.to, st.region, st.state, st.div, st.program]), '[null,null,null,[],[],[],null]');  // vm arrays: compare as JSON
  assert.doesNotMatch(html, /<img|<svg|<script|onerror|onload|alert\(1\)/i, 'planted markup reached the page');
});
