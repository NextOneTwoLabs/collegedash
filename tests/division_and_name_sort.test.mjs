// Tests for the Division filter pill and the division-grouped conference pills (issue #94), and for
// Name as the default sort ordering on the name a reader actually sees (issue #60).
//
//     node --test tests/division_and_name_sort.test.mjs
//
// Same mechanism as tests/camps_view.test.mjs: the inline <script> is pulled out of public/index.html
// and run in a `vm` against a stub DOM, so what is under test is the real source text of the real file
// rather than a copy that can drift. The page is loaded more than once here - once against the real
// published index, and again against a synthetic three-division one - because the whole point of the
// change is that the UI is derived from whatever data loaded.
//
// What this proves:
//   - the shipped index carries `division` on every row and holds exactly one division today;
//   - THE HEADLINE PROPERTY: with the shipped single-division data, row selection AND ordering are
//     byte-for-byte what they were before the division clause existed, over 720 filter states, and the
//     rendered conference pill row is character-identical to the markup this page shipped before;
//   - the Division pill row does not exist with one division and does exist, with counts, with three;
//   - conference pills group under their division, narrow to the selected divisions, and carry a
//     heading only when there are two or more groups to tell apart;
//   - division is multi-select, and a selected conference is dropped when its division is deselected;
//   - a cd.filters saved before this change - no `division` key at all - loads and filters correctly,
//     as do a null and a bare string, and a saved division the data does not carry is pruned;
//   - the camp view filters by division through matchesFilters, joined by slug;
//   - #/c/<conf> still selects the conference as an array, and #/rpi no longer writes a string (#21);
//   - the default sort is Name, and the Name sort orders by the string the cards and table render,
//     so no two adjacent rows read as out of alphabetical order - measured against the comparator
//     that shipped before, which leaves 50 of them;
//   - a visitor whose saved cd.filters names a sort keeps it, and an unknown one does not break.
//
// A note on what the equivalence test does and does not prove: both sides call the SHIPPED sortCmp,
// so it proves the division clause changed no row selection and no ordering THROUGH THAT CLAUSE. The
// Name sort changed on purpose and is pinned separately, below.
//
// What it CANNOT prove, and a human must check in a browser: that the group headings actually read as
// headings at sidebar width, that the pill row wraps sanely at ~100 conferences, and how the drawer
// behaves on a phone. The DOM here is a stub that records innerHTML and swallows everything else.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const INDEX_URL = 'data/programs/index.json';

/* ---------- a stub DOM: enough for the page to load and render into ---------- */
function makeElement(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, contains: () => false,
  };
}

// `overrides` maps a url to an object served instead of the file on disk; `seed` pre-fills
// localStorage, which is how a cd.filters saved by an earlier version of the page is reproduced.
function makeEnv(fetchLog, overrides = {}, seed = {}) {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map(Object.entries(seed));
  const readPublic = url => {
    const p = path.join(PUBLIC, url);
    return p.startsWith(PUBLIC) && fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: {
      documentElement: makeElement('html'), body: makeElement('body'),
      querySelector: bySelector, querySelectorAll: () => [], addEventListener() { }, createElement: makeElement,
    },
    location: { hash: '', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: {
      getItem: k => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k),
    },
    innerWidth: 1400,
    addEventListener() { },
    fetch: async url => {
      fetchLog.push(url);
      if (Object.prototype.hasOwnProperty.call(overrides, url)) {
        const doc = overrides[url];
        return { ok: true, status: 200, async json() { return JSON.parse(JSON.stringify(doc)); } };
      }
      const body = readPublic(url);
      if (body == null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox._store = store;
  return sandbox;
}

const SOURCE_LINES = fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8').split(/\r?\n/);
function loadPage(overrides, seed) {
  const a = SOURCE_LINES.findIndex(l => l.trim() === '<script>');
  const b = SOURCE_LINES.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'public/index.html: could not find the inline <script>');
  // The page declares everything with const/let, which in a vm script lands in the script's own
  // lexical scope rather than on globalThis. One appended line hands the test the handles it needs;
  // everything above it is the file untouched, so what runs is exactly what ships.
  const source = SOURCE_LINES.slice(a + 1, b).join('\n');
  const src = source
    + '\n;Object.assign(globalThis, { S, filteredPrograms, matchesFilters, matchScore, sortCmp, normText,'
    + ' renderCamps, renderList, renderSidebar, loadIndex, loadCamps, route,'
    + ' shownDivisions, conferenceGroups, pruneConfToDivisions, corpusLabel, divisionName });\n';
  const fetchLog = [];
  const sandbox = makeEnv(fetchLog, overrides, seed);
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sandbox, fetchLog, source };
}

/* The predicate exactly as it stood before #94 - the three clauses that shipped, copied verbatim from
 * matchesFilters on origin/main at a9028abe, the commit this branch is cut from. If the division
 * clause changed anything at all for a visitor whose data holds one division, this and the shipped
 * function disagree. */
function matchesFiltersBefore(S, matchScore, p, score) {
  const f = S.filters;
  return (!S.q || (score ? score.has(p.slug) : !!matchScore(p, S.q)))
    && (!f.conf.length || f.conf.includes(p.conference))
    && (!f.region.length || f.region.includes(p.region));
}
function filteredProgramsBefore(S, matchScore, sortCmp) {
  const idx = S.index, f = S.filters;
  const score = new Map();
  idx.programs.forEach(p => { const m = S.q ? matchScore(p, S.q) : null; if (m) score.set(p.slug, m.score); });
  const rows = idx.programs.filter(p => matchesFiltersBefore(S, matchScore, p, score));
  rows.sort((a, b) => (S.q ? (score.get(b.slug) - score.get(a.slug)) : 0) || sortCmp(f.sort)(a, b));
  return rows;
}
/* The conference pill row exactly as it was rendered before #94, again verbatim from a9028abe. The
 * single-division page must still produce this character for character. */
function confRowBefore(S, esc, pillAttrs) {
  const f = S.filters;
  const confs = Object.entries(S.index.byConf).sort((a, b) => a[0].localeCompare(b[0]));
  return `<div class="pill-row" role="group" aria-label="Conference"><button ${pillAttrs('conf', '', !f.conf.length)}>All</button>${confs.map(([c, n]) => `<button ${pillAttrs('conf', c, f.conf.includes(c))} title="${n} programs">${esc(c)}<span class="pill-sub">${n}</span></button>`).join('')}</div>`;
}
const escFor = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pillAttrsFor = (attr, value, on) => `class="pill${on ? ' active' : ''}" data-${attr}="${escFor(value)}" aria-pressed="${on}"`;
/* Arrays and objects built inside the vm are instances of the SANDBOX's Array and Object, so
 * deepStrictEqual against a literal written out here fails on the prototype alone even when the
 * contents match. Everything crossing that boundary into an assertion goes through this first. */
const plain = v => JSON.parse(JSON.stringify(v));
/* The page boots itself with `loadIndex().then(...)` the moment the script runs, so by the time a test
 * calls loadIndex the boot call is already past its first await and has set S.index. The second call
 * hits `if (S.index) return S.index` and hands back the HALF-BUILT index, before the tallies are on it.
 * Waiting for the boot call to finish is the only way to observe the loaded state; this drains the
 * queue rather than guessing at one tick. */
async function ready(sb) {
  await sb.loadIndex();
  for (let i = 0; i < 10 && !sb.S.index?.divisions; i++) await new Promise(r => setTimeout(r, 0));
  assert.ok(sb.S.index?.divisions, 'the index never finished loading');
  return sb.S.index;
}

/* ---------- the real published index, and a synthetic three-division one built from it ---------- */
const REAL = JSON.parse(fs.readFileSync(path.join(PUBLIC, INDEX_URL), 'utf8'));
const D3_CONFS = ['NESCAC', 'Centennial', 'UAA', 'DIII Independent'];
const D2_CONFS = ['Peach Belt', 'GLIAC'];
// Real rows with division and conference reassigned, so every other field stays real and the views
// render as they really would. Rows 0-199 stay D1, 200-299 become D3, the rest (300 on) become D2. The
// D2 count is taken from the real index, which changes size when membership does (issue #100).
const D2_ROWS = REAL.programs.length - 300;
function multiDivisionIndex() {
  const doc = JSON.parse(JSON.stringify(REAL));
  doc.programs.forEach((p, i) => {
    if (i >= 300) { p.division = 'D2'; p.conference = D2_CONFS[i % D2_CONFS.length]; }
    else if (i >= 200) { p.division = 'D3'; p.conference = D3_CONFS[i % D3_CONFS.length]; }
  });
  return doc;
}

/* ---------- the real, single-division page ---------- */
const real = loadPage();
const S = real.sandbox.S;
const sidebar = () => real.sandbox.document.querySelector('#sidebar').innerHTML;
const app = () => real.sandbox.document.querySelector('#app').innerHTML;

test('the shipped index carries a division on every row, and holds exactly one', async () => {
  await ready(real.sandbox);
  const missing = REAL.programs.filter(p => !p.division);
  assert.deepEqual(missing.map(p => p.slug), [], 'a published program row has no division');
  assert.deepEqual(plain(S.index.divisions), ['D1'], 'the shipped index no longer holds exactly one division');
  assert.equal(S.index.byDiv.D1, REAL.programs.length);
  // the per-division split of the conference tally must reconstruct the site-wide tally exactly
  const rebuilt = {};
  for (const d of S.index.divisions) for (const [c, n] of Object.entries(S.index.byDivConf[d])) rebuilt[c] = (rebuilt[c] || 0) + n;
  assert.deepEqual(rebuilt, plain(S.index.byConf), 'byDivConf does not add back up to byConf');
});

test('single-division data selects and orders exactly what it did before the division clause', () => {
  const confs = [...new Set(S.index.programs.map(p => p.conference).filter(Boolean))].sort();
  const matrix = [];
  for (const region of [[], ['West'], ['Northeast'], ['Midwest', 'South'], ['Mid-Atlantic'], ['Nowhere']])
    for (const conf of [[], [confs[0]], [confs[3], confs[7]], ['Not A Conference']])
      for (const q of ['', 'stanford', 'state', 'u', 'zzzz', 'ucla'])
        for (const sort of ['rpi', 'name', 'academicRank', 'tuition', 'undergrads'])
          matrix.push({ region, conf, q, sort });
  assert.ok(matrix.length >= 700, `the matrix is only ${matrix.length} states wide`);

  for (const c of matrix) {
    // f.division stays [] throughout: that is the real condition today, because the pill row that
    // writes it does not render against single-division data.
    S.filters.region = c.region.slice(); S.filters.conf = c.conf.slice(); S.filters.sort = c.sort;
    S.filters.division = [];
    S.qRaw = c.q; S.q = real.sandbox.normText(c.q);
    const after = real.sandbox.filteredPrograms().map(p => p.slug);
    const before = filteredProgramsBefore(S, real.sandbox.matchScore, real.sandbox.sortCmp).map(p => p.slug);
    assert.deepEqual(after, before, `filter state ${JSON.stringify(c)} selects a different list than it used to`);
    // and the predicate on its own, over every program, not just the ones that survived
    const score = new Map();
    S.index.programs.forEach(p => { const m = S.q ? real.sandbox.matchScore(p, S.q) : null; if (m) score.set(p.slug, m.score); });
    const disagree = S.index.programs.filter(p =>
      real.sandbox.matchesFilters(p, score) !== matchesFiltersBefore(S, real.sandbox.matchScore, p, score));
    assert.deepEqual(disagree.map(p => p.slug), [], `matchesFilters disagrees with its old self at ${JSON.stringify(c)}`);
  }
  S.filters.region = []; S.filters.conf = []; S.filters.division = []; S.filters.sort = 'rpi';
  S.q = ''; S.qRaw = '';
});

test('with one division there is no Division pill row and no conference grouping', () => {
  real.sandbox.location.hash = '#/';
  real.sandbox.renderSidebar();
  const html = sidebar();
  assert.ok(!html.includes('aria-label="Division"'), 'a Division pill row rendered against single-division data');
  assert.ok(!html.includes('data-division='), 'a division pill rendered against single-division data');
  assert.ok(!html.includes('>Division</div>'), 'a Division browse label rendered against single-division data');
  assert.ok(!html.includes('pill-group-label'), 'a group heading rendered over a single group');
  assert.ok(!html.includes('pill-row-all'), 'the conference All pill was split onto its own row');
  // the strongest form of "unchanged": the rendered markup, character for character
  assert.ok(html.includes(confRowBefore(S, escFor, pillAttrsFor)),
    'the conference pill row is not character-identical to the row that shipped before #94');
});

test('with one division the list still calls itself NCAA Division I women\'s soccer', async () => {
  real.sandbox.location.hash = '#/';
  await real.sandbox.renderList();
  assert.ok(app().includes("NCAA Division I women's soccer"),
    'the subtitle stopped naming the division for a single-division corpus');
  assert.equal(real.sandbox.corpusLabel(), "NCAA Division I women's soccer");
});

test('#/c/<conf> selects the conference as an array, and #/rpi no longer writes a string (#21)', async () => {
  real.sandbox.location.hash = '#/c/ACC';
  await real.sandbox.route();
  assert.deepEqual(plain(S.filters.conf), ['ACC'], 'the deep link did not select the conference');
  assert.ok(Array.isArray(S.filters.conf), 'the deep link set conf to something other than an array');
  assert.deepEqual(plain(S.filters.division), [], 'the deep link left a division filter that could hide its own conference');

  real.sandbox.location.hash = '#/rpi';
  await real.sandbox.route();
  assert.ok(Array.isArray(S.filters.conf), '#/rpi set conf to a string - issue #21 is back');
  assert.deepEqual(plain(S.filters.conf), []);
  // and the pill toggle that the string used to break still works
  real.sandbox.location.hash = '#/';
  real.sandbox.renderSidebar();
  S.filters.conf = []; S.filters.division = [];
});

/* ---------- a cd.filters written before this change ever existed ---------- */
test('a cd.filters saved before division existed loads and filters correctly', async () => {
  // Exactly what is on a visitor's machine right now: every key this page wrote before #94, and no
  // `division` at all. It must not throw, must not filter anything away, and must stay usable.
  const stale = { conf: ['ACC'], region: ['South'], sort: 'name', classYear: ['2027'], view: 'table', moreStats: true };
  const { sandbox } = loadPage({}, { 'cd.filters': JSON.stringify(stale) });
  assert.deepEqual(plain(sandbox.S.filters.division), [], 'a save with no division key did not default to "all"');
  assert.deepEqual(plain(sandbox.S.filters.conf), ['ACC'], 'the rest of the stale save was lost');
  assert.equal(sandbox.S.filters.sort, 'name');
  await ready(sandbox);
  sandbox.location.hash = '#/';
  await sandbox.renderList();
  const rows = sandbox.filteredPrograms();
  assert.ok(rows.length > 0, 'a stale save filtered every program away');
  assert.deepEqual(plain(rows.map(p => p.conference).filter(c => c !== 'ACC')), [], 'the stale conference filter stopped working');
  sandbox.renderSidebar();
  assert.ok(!sandbox.document.querySelector('#sidebar').innerHTML.includes('data-division='),
    'a stale save somehow produced a division pill against single-division data');
});

test('a division saved as null, as a bare string, or naming a division the data lacks', async () => {
  for (const [saved, expect] of [[null, []], ['D1', ['D1']], [['D1'], ['D1']], ['', []]]) {
    const { sandbox } = loadPage({}, { 'cd.filters': JSON.stringify({ conf: [], region: [], division: saved }) });
    assert.deepEqual(plain(sandbox.S.filters.division), expect, `a saved division of ${JSON.stringify(saved)} did not normalise`);
    await ready(sandbox);
    assert.ok(sandbox.filteredPrograms().length > 0, `a saved division of ${JSON.stringify(saved)} emptied the page`);
  }
  // A division the loaded data does not carry is dropped, because the pill row that would let a
  // visitor clear it is hidden against single-division data.
  const { sandbox } = loadPage({}, { 'cd.filters': JSON.stringify({ conf: [], region: [], division: ['D3'] }) });
  assert.deepEqual(plain(sandbox.S.filters.division), ['D3'], 'the save was not read at all');
  await ready(sandbox);
  assert.deepEqual(plain(sandbox.S.filters.division), [], 'a stale D3 survived against a D1-only index and hid every program');
  assert.equal(sandbox.filteredPrograms().length, REAL.programs.length, 'a stale D3 emptied the page');
  assert.ok(String(sandbox._store.get('cd.filters')).includes('"division":[]'), 'the pruned value was not written back');
});

/* ---------- the synthetic three-division page ---------- */
const multi = loadPage({ [INDEX_URL]: multiDivisionIndex() });
const M = multi.sandbox.S;
const mSidebar = () => multi.sandbox.document.querySelector('#sidebar').innerHTML;
const mApp = () => multi.sandbox.document.querySelector('#app').innerHTML;

test('three divisions in the data put a Division pill row on the page, with counts', async () => {
  await ready(multi.sandbox);
  assert.deepEqual(plain(M.index.divisions), ['D1', 'D2', 'D3'], 'the divisions were not derived from the rows');
  assert.ok(D2_ROWS > 0, `the real index has ${REAL.programs.length} rows, too few to put any in D2`);
  assert.deepEqual(plain(M.index.byDiv), { D1: 200, D3: 100, D2: D2_ROWS });
  multi.sandbox.location.hash = '#/';
  multi.sandbox.renderSidebar();
  const html = mSidebar();
  assert.ok(html.includes('aria-label="Division"'), 'the Division pill row is missing');
  assert.ok(html.includes('>Division</div>'), 'the Division browse label is missing');
  for (const [d, n] of [['D1', 200], ['D2', D2_ROWS], ['D3', 100]]) {
    assert.ok(html.includes(`data-division="${d}"`), `the ${d} pill is missing`);
    assert.ok(html.includes(`>${d}<span class="pill-sub">${n}</span></button>`), `the ${d} pill does not carry its count`);
  }
  assert.ok(html.includes('title="Division III · 100 programs"'), 'the division pill does not spell itself out');
  // the All pill, exactly as the other groups do it
  assert.ok(html.includes(`<button ${pillAttrsFor('division', '', true)}>All</button>`), 'the Division row has no All pill');
});

test('conference pills group under their division, with a heading per group', () => {
  const html = mSidebar();
  assert.ok(html.includes('class="pill-group-label">Division I<'), 'no Division I heading over the conference pills');
  assert.ok(html.includes('class="pill-group-label">Division II<'), 'no Division II heading');
  assert.ok(html.includes('class="pill-group-label">Division III<'), 'no Division III heading');
  assert.equal((html.match(/pill-group-label/g) || []).length, 3, 'wrong number of conference groups');
  assert.ok(html.includes('aria-label="Division III conferences"'), 'a group is not labelled for a screen reader');

  const groups = Object.fromEntries(plain(multi.sandbox.conferenceGroups()).map(([d, l]) => [d, l.map(([c]) => c)]));
  assert.deepEqual(groups.D3.slice().sort(), D3_CONFS.slice().sort(), 'the D3 group holds the wrong conferences');
  assert.deepEqual(groups.D2.slice().sort(), D2_CONFS.slice().sort(), 'the D2 group holds the wrong conferences');
  assert.ok(!groups.D1.includes('NESCAC') && !groups.D1.includes('Peach Belt'), 'a conference leaked into the wrong division');
  assert.deepEqual(groups.D1, groups.D1.slice().sort((a, b) => a.localeCompare(b)), 'a group is not in name order');
  // counts are per group, and each group's counts add up to its division's programs
  for (const [d, list] of multi.sandbox.conferenceGroups())
    assert.equal(list.reduce((a, [, n]) => a + n, 0), M.index.byDiv[d], `the ${d} group's counts do not add up`);
});

test('division is multi-select, and it filters both views through matchesFilters', async () => {
  M.filters.division = ['D3'];
  let rows = multi.sandbox.filteredPrograms();
  assert.equal(rows.length, 100);
  assert.deepEqual(plain([...new Set(rows.map(p => p.division))]), ['D3'], 'a non-D3 program survived the D3 filter');

  M.filters.division = ['D1', 'D3'];
  rows = multi.sandbox.filteredPrograms();
  assert.equal(rows.length, 300, 'selecting two divisions did not show both');
  assert.deepEqual(plain([...new Set(rows.map(p => p.division))].sort()), ['D1', 'D3']);

  // and it ANDs with the other pills rather than replacing them
  M.filters.division = ['D3']; M.filters.region = ['West'];
  rows = multi.sandbox.filteredPrograms();
  assert.ok(rows.every(p => p.division === 'D3' && p.region === 'West'), 'division and region stopped ANDing');
  M.filters.region = [];

  // the camp view gets it from the same predicate, joined by slug
  const idx = M.index;
  const d1 = idx.programs.find(p => p.division === 'D1'), d3 = idx.programs.find(p => p.division === 'D3');
  M.camps = {
    updated: '2026-09-14T20:56:27Z', window: { from: '2026-09-14', to: null },
    counts: { total: 2, id: 2, youth: 0, unknown: 0 },
    camps: [
      { slug: d1.slug, name: 'A D1 ID Camp', startDate: '2026-10-01', campType: 'id', kind: 'camp' },
      { slug: d3.slug, name: 'A D3 ID Camp', startDate: '2026-10-02', campType: 'id', kind: 'camp' },
    ],
  };
  multi.sandbox.location.hash = '#/camps';
  M.filters.division = ['D3'];
  await multi.sandbox.renderCamps();
  assert.ok(mApp().includes('A D3 ID Camp'), 'the D3 camp was filtered out of its own division');
  assert.ok(!mApp().includes('A D1 ID Camp'), 'a D1 camp survived a D3-only filter - the camp view is not using matchesFilters');
  assert.ok(mApp().includes('1 upcoming ID camp of 2'), 'the camp view does not count the division filter as a filter');
  assert.ok(mApp().includes("NCAA Division III women's soccer"), 'the camp view still claims the wrong division');

  M.filters.division = [];
  await multi.sandbox.renderCamps();
  assert.ok(mApp().includes('A D1 ID Camp') && mApp().includes('A D3 ID Camp'), 'clearing the division did not restore both');
  multi.sandbox.location.hash = '#/';
});

test('conference pills narrow to the selected divisions', () => {
  M.filters.division = ['D3'];
  multi.sandbox.renderSidebar();
  const html = mSidebar();
  assert.ok(html.includes('data-conf="NESCAC"'), 'the selected division lost its own conferences');
  assert.ok(!html.includes('data-conf="ACC"'), 'a D1 conference pill survived a D3-only selection');
  assert.ok(!html.includes('data-conf="Peach Belt"'), 'a D2 conference pill survived a D3-only selection');
  assert.ok(!html.includes('pill-group-label'), 'a heading rendered over the only group on screen');
  assert.equal(multi.sandbox.shownDivisions().join(), 'D3');

  M.filters.division = ['D2', 'D3'];
  multi.sandbox.renderSidebar();
  const two = mSidebar();
  assert.equal((two.match(/pill-group-label/g) || []).length, 2, 'two selected divisions did not give two groups');
  assert.ok(two.includes('data-conf="Peach Belt"') && two.includes('data-conf="NESCAC"'));
  assert.ok(!two.includes('data-conf="ACC"'), 'a D1 conference pill survived a D2+D3 selection');
  M.filters.division = [];
});

test('a selected conference is dropped when its division is deselected', () => {
  M.filters.division = ['D1']; M.filters.conf = ['ACC'];
  multi.sandbox.pruneConfToDivisions();
  assert.deepEqual(plain(M.filters.conf), ['ACC'], 'a conference was dropped while its own division was still selected');

  // the visitor swaps D1 for D3: the ACC pill leaves the sidebar, so the ACC filter leaves with it
  M.filters.division = ['D3'];
  multi.sandbox.pruneConfToDivisions();
  assert.deepEqual(plain(M.filters.conf), [], 'a conference filter outlived the pill that could clear it');
  assert.equal(multi.sandbox.filteredPrograms().length, 100, 'the orphaned filter emptied the page');

  // clearing the division filter shows every group again and prunes nothing
  M.filters.conf = ['ACC', 'NESCAC']; M.filters.division = [];
  multi.sandbox.pruneConfToDivisions();
  assert.deepEqual(plain(M.filters.conf), ['ACC', 'NESCAC'], 'clearing the division filter pruned conferences that are on screen');
  M.filters.conf = [];
});

test('the list names the divisions it is showing', async () => {
  M.filters.division = [];
  assert.equal(multi.sandbox.corpusLabel(), "NCAA women's soccer · Division I, Division II, Division III");
  M.filters.division = ['D3'];
  assert.equal(multi.sandbox.corpusLabel(), "NCAA Division III women's soccer");
  M.filters.division = ['D1', 'D3'];
  assert.equal(multi.sandbox.corpusLabel(), "NCAA women's soccer · Division I, Division III");
  multi.sandbox.location.hash = '#/';
  await multi.sandbox.renderList();
  assert.ok(mApp().includes("NCAA women's soccer · Division I, Division III"), 'the list does not say which divisions it shows');
  assert.ok(mApp().includes(`300 of ${REAL.programs.length} programs`), 'the list miscounts under a division filter');
  M.filters.division = [];
  // a division code the spelling table does not know prints itself rather than vanishing
  assert.equal(multi.sandbox.divisionName('DII'), 'DII');
});

/* =====================================================================================
   Name as the default sort, ordering on the rendered name - issue #60
   ===================================================================================== */

// The comparator exactly as it shipped before #60: the STORED name, which is what made the
// alphabetical sort read as unsorted. Kept here so the fix has to prove it changed something.
const nameSortBefore = (a, b) => a.name.localeCompare(b.name);
const disp = p => p.shortName || p.name || '';
// How many ADJACENT pairs a reader would see out of alphabetical order. Not the positional figure -
// this is the thing actually visible when you scan a list from the top. Case-insensitive and nothing
// more, matching the shipped comparator; the count is 50 under every other reasonable definition too
// (plain localeCompare, lowercased <, and raw code points all agree), so it is not an artefact of it.
function adjacentInversions(rows) {
  let n = 0;
  for (let i = 0; i + 1 < rows.length; i++)
    if (disp(rows[i]).localeCompare(disp(rows[i + 1]), undefined, { sensitivity: 'accent' }) > 0) n++;
  return n;
}

test('the default sort is Name, and the select lists it first', () => {
  // No cd.filters at all: a first-time visitor. RPI exists only for Division I, so it cannot be the
  // default of a page that is about to carry three divisions.
  const { sandbox } = loadPage({}, {});
  assert.equal(sandbox.S.filters.sort, 'name', 'a visitor with nothing saved does not get the Name sort');
  assert.ok(real.source.includes("const SORTS = [['name', 'Name']"), 'the sort select does not list Name first');
});

test('the Name sort orders by the name the page renders, not the stored one', () => {
  S.filters.conf = []; S.filters.region = []; S.filters.division = []; S.q = ''; S.qRaw = '';
  S.filters.sort = 'name';
  const after = S.index.programs.slice().sort(real.sandbox.sortCmp('name'));
  const before = S.index.programs.slice().sort(nameSortBefore);

  // the check has to be able to fail: the old comparator really does leave visible inversions
  const wasWrong = adjacentInversions(before);
  assert.ok(wasWrong > 0, 'the pre-#60 comparator produced no inversions - this check cannot fail and proves nothing');
  assert.equal(wasWrong, 50, 'the number of visible inversions in the OLD order changed; re-measure before trusting the new one');
  assert.equal(adjacentInversions(after), 0, 'the Name sort still leaves rows out of alphabetical order');

  // the specific programs issue #60 measured on the live site
  const at = n => after.findIndex(p => disp(p) === n);
  assert.ok(at('Air Force') < 5 && at('Akron') < 5,
    `Air Force and Akron are still buried at ${at('Air Force')} and ${at('Akron')}`);
  assert.ok(before.findIndex(p => disp(p) === 'Air Force') > 200, 'the old order no longer reproduces the reported bug');
  // and the pairs the brief quoted
  for (const [x, y] of [['Fresno State', 'Cal State Fullerton'], ['BYU', 'Brown'], ['William & Mary', 'Holy Cross']])
    assert.ok(at(x) > at(y), `"${x}" still sorts ahead of "${y}"`);
});

test('the rendered list is in the order the comparator produced', async () => {
  // Ties the sort to the render: the first cards on the page must be the first rows of the sorted
  // list, labelled with the same string the comparator ordered by.
  S.filters.sort = 'name'; S.filters.view = 'cards';
  real.sandbox.location.hash = '#/';
  await real.sandbox.renderList();
  const rows = real.sandbox.filteredPrograms();
  assert.equal(adjacentInversions(rows), 0, 'the list the page renders is not in alphabetical order');
  const html = app();
  const first = html.indexOf(`>${disp(rows[0])}<`), second = html.indexOf(`>${disp(rows[1])}<`);
  assert.ok(first >= 0 && second > first,
    `the first two cards are not in the comparator's order (${disp(rows[0])} at ${first}, ${disp(rows[1])} at ${second})`);
  assert.ok(html.includes('sorted by Name'), 'the subtitle does not name the sort in effect');
});

test('the US rank tiebreak breaks ties on the rendered name too (#57)', () => {
  const ranked = S.index.programs.slice().sort(real.sandbox.sortCmp('academicRank'));
  const bad = [];
  for (let i = 0; i + 1 < ranked.length; i++)
    if ((ranked[i].academicRank ?? null) === (ranked[i + 1].academicRank ?? null)
      && disp(ranked[i]).localeCompare(disp(ranked[i + 1]), undefined, { sensitivity: 'accent' }) > 0)
      bad.push(`${disp(ranked[i])} before ${disp(ranked[i + 1])}`);
  assert.deepEqual(bad, [], 'a tied academic rank is not broken on the rendered name');
});

test('a saved sort survives the new default, and an unknown one does not break the page', async () => {
  // A returning visitor carries sort:'rpi' - possibly chosen, possibly written out as a side effect of
  // clicking any other filter, and the two are indistinguishable from here. It is KEPT: silently
  // reordering a list someone has been using, with nothing on the page to explain it, is the worse
  // failure, and the sort select shows what is in effect and is one click away from Name.
  const kept = loadPage({}, { 'cd.filters': JSON.stringify({ conf: [], region: [], sort: 'rpi', view: 'cards' }) });
  assert.equal(kept.sandbox.S.filters.sort, 'rpi', 'a saved sort was overwritten by the new default');
  await ready(kept.sandbox);
  kept.sandbox.location.hash = '#/';
  await kept.sandbox.renderList();
  assert.ok(kept.sandbox.document.querySelector('#app').innerHTML.includes('sorted by RPI 2025'),
    'the page does not say which sort a returning visitor is on');

  // and a value this page has never written, or no longer writes
  const odd = loadPage({}, { 'cd.filters': JSON.stringify({ conf: [], region: [], sort: 'nonsense' }) });
  await ready(odd.sandbox);
  odd.sandbox.location.hash = '#/';
  await odd.sandbox.renderList();
  assert.equal(odd.sandbox.filteredPrograms().length, REAL.programs.length, 'an unknown sort lost rows');
  assert.ok(odd.sandbox.document.querySelector('#app').innerHTML.includes('sorted by RPI'),
    'an unknown sort is not labelled as the RPI fallback it actually falls through to');
});

test('the camp view still omits the sort select and hands f.sort back untouched', () => {
  S.filters.sort = 'admit';
  real.sandbox.location.hash = '#/camps';
  real.sandbox.renderSidebar();
  assert.ok(!sidebar().includes('id="sortSelect"'), 'the sort select reappeared in the camp view');
  real.sandbox.location.hash = '#/';
  real.sandbox.renderSidebar();
  assert.ok(sidebar().includes('id="sortSelect"'), 'the sort select did not come back');
  assert.equal(S.filters.sort, 'admit', 'f.sort was written while the camp view was open');
  assert.ok(sidebar().includes('value="name"'), 'Name is missing from the sort select');
  S.filters.sort = 'name';
});

test('nothing else in the page orders programs by the stored name', () => {
  // #60 is the fifth instance of this one mismatch on this codebase. The rule is worth something only
  // if it is applied everywhere, so this reads the shipped source rather than trusting the diff.
  const offenders = [...real.source.matchAll(/[ab]\.name\.localeCompare\([ab]\.name\)/g)].map(m => m[0]);
  assert.deepEqual(offenders, [], `a comparator still orders by the stored name: ${offenders.join(', ')}`);
  assert.ok(real.source.includes('const displayName = p => p.shortName || p.name'),
    'the shared rendered-name helper is gone');
  // campCmp orders CAMPS by camp name, which IS the string the camp view renders - not a program
  // label, and deliberately not swept into the program rule.
  assert.ok(real.source.includes("|| (a.name || '').localeCompare(b.name || '')"),
    'the camp comparator changed; check it still orders camp names');
});
