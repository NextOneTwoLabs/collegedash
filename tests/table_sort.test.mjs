// Tests for the Table view's headers and sorting (issue #285) and the US rank column (issue #59).
//
//     node --test tests/table_sort.test.mjs
//
// Same mechanism as tests/d2_publish_frontend.test.mjs: the inline <script> is pulled out of public/index.html and
// run in a `vm` against a stub DOM, so what is under test is the real source of the real file.
// TABLE_SORT_HTML (optional) points the suite at another copy of index.html, so a deliberately broken copy can be
// run through these same checks to show each of them failing.
//
// The fixture is seven made-up programs (no real names, no people): four D1, one D2, two D3, listed in the index in
// REVERSE name order so a sort that leaves ties in index order is caught. Every expected order below is written
// out by hand from the fixture, never computed with the page's own code.
//
// What this proves:
//   - every data column sorts both ways, and a row showing '—' (or nothing, where the measure does not apply to
//     the division) sorts last in BOTH directions;
//   - Record sorts by win percentage (ties count half a win), Tuition by the out-of-state figure (the in-state
//     one when that is all a school publishes), Titles grouped by division within each run;
//   - the '#' column is labelled with the RPI season, each sortable header is a button, the active one carries
//     aria-sort and a direction class, the others carry none;
//   - the Program line shows the division first for D1, D2 and D3;
//   - the table header, the sidebar Sort select and the sidebar direction button read and write the same state;
//   - the US rank (THE) column exists, and shows even under "Fewer statistics" while it is the active sort (#59).
//
// What it CANNOT prove, and a human must check in a browser: that the arrow reads as an arrow, that the table
// scrolls in its own box at ~400px, and that a real Tab / Enter reaches the header buttons.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const PAGE = process.env.TABLE_SORT_HTML || path.join(PUBLIC, 'index.html');
const clone = (v) => JSON.parse(JSON.stringify(v));

// ---------- the fixture ----------
const row = (slug, division, o) => ({
  slug, name: `${slug[0].toUpperCase()}${slug.slice(1)} College`, shortName: slug[0].toUpperCase() + slug.slice(1),
  nickname: 'Testers', searchNames: [slug], conference: `Test ${division} Conference`, division, colors: [],
  city: 'Testville', state: 'CA', region: null, ownership: null, undergradEnrollment: null, admissionRate: null,
  academicRank: null, tuitionInState: null, tuitionOutOfState: null, nationalTitles: 0, collegeCups: 0,
  lastSeason: null, rpiHistory: [], commitmentsByYear: {}, completeness: 1, stale: [], failed: [], tags: [], ...o,
});
const rec = (record) => ({ year: 2025, record });
const rpi = (rank) => [{ year: 2026, rank }, { year: 2025, rank: rank + 1 }];
const PROGRAMS = [
  row('alpha', 'D1', { rpiHistory: rpi(1), lastSeason: rec('10-2-0'), admissionRate: 0.5, academicRank: 20, tuitionInState: 10000, tuitionOutOfState: 30000,
    undergradEnrollment: 5000, commitmentsByYear: { 2027: 3 }, nationalTitles: 2, collegeCups: 5, region: 'West', ownership: 'Public' }),
  row('bravo', 'D1', { rpiHistory: rpi(5), lastSeason: rec('8-2-2'), admissionRate: 0.2, tuitionInState: 40000, tuitionOutOfState: 40000,
    undergradEnrollment: 20000, commitmentsByYear: { 2027: 1 }, region: 'South', ownership: 'Private nonprofit' }),
  row('charlie', 'D1', { rpiHistory: [{ year: 2025, rank: 200 }], lastSeason: rec('9-3-0'), academicRank: 5, tuitionInState: 20000, tuitionOutOfState: 25000,
    nationalTitles: 1, collegeCups: 2, ownership: 'Public' }),
  row('delta', 'D2', { lastSeason: rec('12-4-4'), admissionRate: 0.8, tuitionInState: 5000, undergradEnrollment: 3000,
    commitmentsByYear: { 2027: 2 }, nationalTitles: 3, region: 'Midwest' }),
  row('echo', 'D3', { admissionRate: 0.35, academicRank: 50, undergradEnrollment: 1500, commitmentsByYear: { 2027: 5 }, region: 'Northeast', ownership: 'Private nonprofit' }),
  row('foxtrot', 'D3', { lastSeason: rec('15-1-0'), admissionRate: 0.1, tuitionInState: 50000, tuitionOutOfState: 50000,
    undergradEnrollment: 2500, nationalTitles: 4, region: 'West', ownership: 'Public' }),
  // a Division I program with nothing at all, named after every D2/D3 row: where the measure applies to D1 only
  // (RPI, College Cups) its blank must still sort ahead of theirs, and after every value everywhere else
  row('golf', 'D1', {}),
].reverse();
const INDEX = { updated: '2026-09-24T00:00:00Z', season: { current: 2026, gradYears: [2026, 2027, 2028, 2029] }, programs: PROGRAMS };

// sort key -> [natural first-click direction, ascending order, descending order], by hand from the fixture
const A = 'alpha', B = 'bravo', C = 'charlie', D = 'delta', E = 'echo', F = 'foxtrot', G = 'golf';
const EXPECTED = {
  name: ['asc', [A, B, C, D, E, F, G], [G, F, E, D, C, B, A]],
  // ranked, then unranked D1 ('—': C, G), then D2/D3 where RPI does not apply
  rpi: ['asc', [A, B, C, G, D, E, F], [B, A, C, G, D, E, F]],
  // win %: F .9375, A .833, B (8-2-2) = C (9-3-0) = .75, D (12-4-4) .70; E and G have no record
  record: ['desc', [D, B, C, A, F, E, G], [F, A, B, C, D, E, G]],
  admit: ['asc', [F, B, E, A, D, C, G], [D, A, E, B, F, C, G]],
  academicRank: ['asc', [C, A, E, B, D, F, G], [E, A, C, B, D, F, G]],
  // out-of-state: D 5000 (in-state only), C 25000, A 30000, B 40000, F 50000; E, G none. In-state would put A before C.
  tuition: ['asc', [D, C, A, B, F, E, G], [F, B, A, C, D, E, G]],
  undergrads: ['desc', [E, F, D, A, B, C, G], [B, A, D, F, E, C, G]],
  // 0 commits is a count, not a blank
  commits: ['desc', [C, F, G, B, D, A, E], [E, A, D, B, C, F, G]],
  // with titles, by division (D1 C1 A2 | D2 D3 | D3 F4), then without: B, G (D1), E (D3)
  titles: ['desc', [C, A, D, F, B, G, E], [A, C, D, F, B, G, E]],
  // College Cups: A 5, C 2; B and G are D1 '—'; D, E, F are D2/D3 where it does not apply
  cups: ['desc', [C, A, B, G, D, E, F], [A, C, B, G, D, E, F]],
  region: ['asc', [D, E, B, A, F, C, G], [A, F, B, E, D, C, G]],
  type: ['asc', [B, E, A, C, F, D, G], [A, C, F, B, E, D, G]],
};

// ---------- the page ----------
function makeElement(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null, matches: () => false, focus() { }, contains: () => false,
  };
}
const HANDLES = ['S', 'renderList', 'renderSidebar', 'loadIndex', 'setSort', 'sortCmp', 'syncSortControls'];
function loadPage() {
  const els = new Map();
  const bySelector = (sel) => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
  const ok = (body, st = 200) => ({ ok: st < 400, status: st, async json() { return clone(body); } });
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector, querySelectorAll: () => [], addEventListener() { }, createElement: makeElement },
    location: { hash: '', replace(h) { this.hash = h; } }, history: { replaceState() { } }, matchMedia: () => ({ matches: false }),
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
    innerWidth: 1400, addEventListener() { }, alert() { },
    fetch: async (url) => (String(url) === '/api/v1/programs' ? ok(INDEX) : ok({}, 404)),
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(PAGE, 'utf8').split(/\r?\n/);
  const a = lines.findIndex((l) => l.trim() === '<script>'), b = lines.findIndex((l) => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(HANDLES)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  const $ = (sel) => sandbox.document.querySelector(sel);
  return { sb: sandbox, app: () => $('#app').innerHTML, sidebar: () => $('#sidebar').innerHTML, source: lines.slice(a + 1, b).join('\n') };
}
const settle = async () => { for (let i = 0; i < 30; i++) await new Promise((r) => setTimeout(r, 0)); };
let PG;
async function page() { if (!PG) { PG = loadPage(); await PG.sb.loadIndex(); await settle(); } return PG; }
async function table(filters) {
  const pg = await page();
  Object.assign(pg.sb.S.filters, { conf: [], region: [], division: [], classYear: [], cond: [], sort: 'name', sortDir: null, view: 'table', moreStats: false }, filters);
  pg.sb.S.q = ''; pg.sb.S.qRaw = '';
  pg.sb.renderSidebar();
  await pg.sb.renderList();
  return pg.app();
}
const rowSlugs = (html) => [...html.matchAll(/<tr class="team-row[^"]*" data-slug="([^"]+)"/g)].map((m) => m[1]);
const th = (html, key) => (html.match(new RegExp(`<th [^>]*data-sort="${key}"[^>]*>[\\s\\S]*?</th>`)) || [])[0] || '';
const teamSub = (html, slug) => (html.match(new RegExp(`data-slug="${slug}"[\\s\\S]*?<span class="team-sub">([\\s\\S]*?)</span></span></div>`)) || [])[1] || '';

// ---------- sorting ----------
for (const [key, [natural, asc, desc]] of Object.entries(EXPECTED)) {
  test(`sort ${key}: both directions, blanks last in each`, async () => {
    const up = rowSlugs(await table({ sort: key, sortDir: 'asc', moreStats: true }));
    assert.deepEqual(up, asc, `${key} ascending`);
    const down = rowSlugs(await table({ sort: key, sortDir: 'desc', moreStats: true }));
    assert.deepEqual(down, desc, `${key} descending`);
    // the first click (no direction chosen) is the column's natural direction
    const first = rowSlugs(await table({ sort: key, sortDir: null, moreStats: true }));
    assert.deepEqual(first, natural === 'asc' ? asc : desc, `${key} natural direction`);
  });
}

test('every data column header sorts; the active one has aria-sort and its direction, the rest none', async () => {
  const html = await table({ sort: 'admit', sortDir: 'desc', moreStats: true });
  const keys = [...html.matchAll(/<th [^>]*data-sort="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(keys, ['rpi', 'name', 'record', 'admit', 'academicRank', 'undergrads', 'tuition', 'commits', 'titles', 'cups', 'region', 'type']);
  for (const k of keys) assert.match(th(html, k), /<button type="button" class="th-sort"[^>]*>[^<]+<\/button><\/th>$/, `${k}: the header is not a button`);
  assert.match(th(html, 'admit'), /class="[^"]*sort-active sort-desc"[^>]*aria-sort="descending"/);
  assert.equal([...html.matchAll(/aria-sort=/g)].length, 1, 'more than one header carries aria-sort');
  const up = await table({ sort: 'admit', sortDir: 'asc' });
  assert.match(th(up, 'admit'), /class="[^"]*sort-active sort-asc"[^>]*aria-sort="ascending"/);
  // the headers without a label (shortlist star, compare) are the only ones that do not sort
  const unlabelled = [...html.matchAll(/<th class="[^"]*">([^<]*)<\/th>/g)].map((m) => m[1]);
  assert.deepEqual(unlabelled, ['', '']);
});

test("the '#' column is labelled with the RPI season, and the footnote no longer says '#'", async () => {
  const html = await table({});
  assert.match(th(html, 'rpi'), />RPI 2026 \(in progress\)<\/button>/);
  assert.doesNotMatch(html, /<th[^>]*>#<\/th>|RPI \(#\)/);
});

test('the tuition and record headers say what they sort by', async () => {
  const html = await table({});
  assert.match(th(html, 'tuition'), /title="Sorts by out-of-state tuition"/);
  assert.match(th(html, 'record'), /title="Sorts by win percentage, a tie counting half a win"/);
});

// ---------- the Program line ----------
test('the Program line shows the division first, for D1, D2 and D3', async () => {
  const html = await table({});
  for (const [slug, d, name] of [[A, 'D1', 'Division I'], [D, 'D2', 'Division II'], [E, 'D3', 'Division III']]) {
    assert.equal(teamSub(html, slug), `<span class="div-tag" title="${name}">${d}</span> · Test ${d} Conference · Testville, CA`, `${slug}: the Program line`);
  }
});

// ---------- one source of truth ----------
test('the table header, the sidebar select and the sidebar direction button stay in sync', async () => {
  const pg = await page();
  await table({ sort: 'name', sortDir: null });
  const state = async () => {
    pg.sb.renderSidebar(); await pg.sb.renderList();
    const sel = (pg.sidebar().match(/<select class="season-select" id="sortSelect">([\s\S]*?)<\/select>/) || [])[1] || '';
    return {
      selected: (sel.match(/<option value="([^"]+)" selected>/) || [])[1],
      options: [...sel.matchAll(/<option value="([^"]+)"/g)].map((m) => m[1]),
      button: (pg.sidebar().match(/id="sortDir" title="Sort direction: (\w+)"/) || [])[1],
      aria: (pg.app().match(/data-sort="([^"]+)" aria-sort="(\w+)"/) || []).slice(1).join(' '),
      rows: rowSlugs(pg.app()),
    };
  };
  // a header-only sort (record): the select lists it while it is active and shows it selected
  pg.sb.setSort('record');
  let s = await state();
  assert.equal(s.selected, 'record'); assert.ok(s.options.includes('record'));
  assert.equal(s.button, 'descending'); assert.equal(s.aria, 'record descending'); assert.deepEqual(s.rows, EXPECTED.record[2]);
  // a second header click flips it everywhere
  pg.sb.setSort('record');
  s = await state();
  assert.equal(s.button, 'ascending'); assert.equal(s.aria, 'record ascending'); assert.deepEqual(s.rows, EXPECTED.record[1]);
  // choosing another sort in the select starts it in its natural direction, and the header follows
  pg.sb.setSort('undergrads');
  s = await state();
  assert.equal(s.selected, 'undergrads'); assert.ok(!s.options.includes('record'), 'a header-only sort stayed in the select after it stopped being active');
  assert.equal(s.button, 'descending'); assert.equal(s.aria, 'undergrads descending'); assert.deepEqual(s.rows, EXPECTED.undergrads[2]);
  // the direction button is the same flip
  pg.sb.setSort(pg.sb.S.filters.sort);
  s = await state();
  assert.equal(s.button, 'ascending'); assert.equal(s.aria, 'undergrads ascending'); assert.deepEqual(s.rows, EXPECTED.undergrads[1]);
  // and every control writes through setSort, the one writer, then brings the sidebar controls up to date
  const src = pg.source;
  assert.match(src, /th\[data-sort\] \.th-sort'\)\.forEach\(b => b\.onclick = async \(\) => \{ const k = b\.closest\('th'\)\.dataset\.sort;\s*setSort\(k\); syncSortControls\(\);/, 'the header click does not go through setSort and syncSortControls');
  assert.match(src, /sortSel\.onchange = e => \{ setSort\(e\.target\.value\); syncSortControls\(\);/, 'the sidebar select does not go through setSort and syncSortControls');
  assert.match(src, /dirBtn\.onclick = \(\) => \{ setSort\(f\.sort\); syncSortControls\(\);/, 'the direction button does not go through setSort and syncSortControls');
});

test('syncSortControls updates the sidebar select and direction button in place, without rebuilding the sidebar', async () => {
  const pg = await page();
  await table({ sort: 'name', sortDir: null });
  const sel = pg.sb.document.querySelector('#sortSelect'), btn = pg.sb.document.querySelector('#sortDir');
  pg.sb.setSort('cups'); pg.sb.syncSortControls();
  assert.equal(sel.value, 'cups'); assert.match(sel.innerHTML, /<option value="cups">College Cups<\/option>$/);
  assert.equal(btn.title, 'Sort direction: descending'); assert.equal(btn.textContent, '▾');
  pg.sb.setSort('cups'); pg.sb.syncSortControls();
  assert.equal(btn.title, 'Sort direction: ascending'); assert.equal(btn.textContent, '▴');
  pg.sb.setSort('admit'); pg.sb.syncSortControls();
  assert.equal(sel.value, 'admit'); assert.doesNotMatch(sel.innerHTML, /value="cups"/, 'the header-only sort stayed listed');
  assert.equal(btn.title, 'Sort direction: ascending');
});

test('a saved direction that is not asc/desc is dropped, not trusted', async () => {
  const pg = loadPage();
  assert.equal(pg.sb.S.filters.sortDir, null);
  const src = pg.source;
  assert.match(src, /if \(S\.filters\.sortDir !== 'asc' && S\.filters\.sortDir !== 'desc'\) S\.filters\.sortDir = null;/);
});

// ---------- #59: the US rank column ----------
test('US rank (THE) has a column, shown even under "Fewer statistics" while it is the active sort (#59)', async () => {
  const off = await table({ sort: 'name', moreStats: false });
  assert.match(th(off, 'academicRank'), /class="num col-extra sortable"/, 'US rank is not an extra column when another sort is active');
  const on = await table({ sort: 'academicRank', moreStats: false });
  assert.match(th(on, 'academicRank'), /class="num sortable sort-active sort-asc"[^>]*>.*US rank \(THE\)</, 'the active US rank column is hidden');
  assert.match(on, /data-slug="charlie"[\s\S]*?<td class="num"><span title="[^"]*">#5<\/span><\/td>/, 'the US rank cell is not shown');
  assert.match(on, /data-slug="bravo"[\s\S]*?<td class="num"><span title="[^"]*">—<\/span><\/td>/, 'an unranked university does not show a dash');
});
