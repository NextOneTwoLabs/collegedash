// Tests for condition chips: a rule on a number (field + comparison + value) that filters both the
// Program View and the ID Camp View, and hides AND COUNTS programs with no data for it (issue #166).
//
//     node --test tests/condition_chips.test.mjs
//
// Same mechanism as tests/division_and_name_sort.test.mjs: the inline <script> is pulled out of
// public/index.html and run in a `vm` against a stub DOM, so what is under test is the real source text.
// Expectations are written from the data shape (index.json field paths, the camps index), never by calling
// the page's own registry accessors, so a wrong accessor cannot agree with itself.
//
// What this proves:
//   - the registry declares exactly the ten fields shipped, each with the parts a caller relies on, and each
//     accessor reads the value the data holds (tuition: the Tuition sort's out-of-state-first figure);
//   - conditions AND with the pills and with search, in the Program View;
//   - '<' and '<=' (and '>' / '>=' / '=') are exact at the boundary value;
//   - display units parse to stored units (30 and 30% -> 0.30, $40k -> 40000) and format back on the chip;
//   - a program without data is hidden and counted apart from one that did not match: one chip on the real
//     index, and two chips over overlapping gaps on a synthetic one, where the total counts a program once;
//   - junk in a saved cd.filters is dropped on load and never thrown on;
//   - every "Clear filters" control on the page clears chips (the set of controls is read from the source,
//     so a new one added without clearing chips fails here);
//   - the ID Camp View honours chips and counts hidden camps;
//   - with no chips, the Program View's rows are in byte-identical order to the predicate and list code that
//     shipped before this change, over 270 sort x conference x region x search states on the real index,
//     and the rendered order and subtitle are unchanged over 60 cards and table states. The expected order
//     comes from a verbatim copy of the old predicate AND the old sort, never from the page's sortCmp;
//   - the add form is labelled native controls whose handlers add, reject, cancel on Escape and re-scope the
//     comparison when the field changes.
//
// What it CANNOT prove, and a human must check in a browser: layout at ~400 px in the drawer, that Tab order
// and real key presses reach these handlers (they are called directly here), and screen-reader output. The
// DOM here is a stub that records innerHTML and swallows everything else.
//
// COND_TEST_HTML (optional) points the suite at another copy of index.html, so a deliberately broken copy,
// or the page from before this change, can be run through these same checks to show each of them failing.
// COND_TEST_PUBLIC (optional) points at the public/ folder, so a copy of THIS file with a deliberately
// vacuous fixture can be run from elsewhere to show that the fixture guards fail too.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = process.env.COND_TEST_PUBLIC || path.join(HERE, '..', 'public');
const HTML = process.env.COND_TEST_HTML || path.join(PUBLIC, 'index.html');
const INDEX_URL = 'data/programs/index.json';
const RPI_SEASON = 2025;
const SHIPPED = JSON.parse(fs.readFileSync(path.join(PUBLIC, INDEX_URL), 'utf8'));
/* The divisions build.py reads national titles from a champions table for (CHAMPION_TABLES), read from build.py
   itself: in those a zero title count is a real zero (issue #206); in any other it is "not collected". */
const TITLE_TABLE_DIVISIONS = (() => {
  const m = fs.readFileSync(path.join(HERE, '..', 'build.py'), 'utf8').match(/^CHAMPION_TABLES = \{([^}]*)\}/m);
  assert.ok(m, 'build.py no longer defines CHAMPION_TABLES on one line');
  return [...m[1].matchAll(/"([^"]+)"\s*:/g)].map(x => x[1]);
})();
const CAMPS = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data/camps/index.json'), 'utf8'));

/* ---------- stub DOM ---------- */
function makeElement(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, contains: () => false,
  };
}
const HANDLES = ['S', 'TITLE_TABLE_DIVISIONS', 'COND_FIELDS', 'COND_UNITS', 'condFromInput', 'condText', 'condStatus', 'condTally', 'condHiddenText',
  'addCond', 'removeCond', 'condRemove', 'condFormOpen', 'condFormClose', 'condFormSubmit', 'filteredPrograms', 'matchesFilters',
  'matchScore', 'sortCmp', 'normText', 'tuitionOf', 'renderList', 'renderCamps', 'renderSidebar', 'loadIndex', 'corpusLabel', 'SORTS'];
// `seed` maps a localStorage key to the RAW string stored, which is how a hand-edited or corrupt save is reproduced.
function loadPage({ index, seed = {} } = {}) {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map(Object.entries(seed));
  const serve = { [INDEX_URL]: index || SHIPPED, 'data/camps/index.json': CAMPS };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector,
      querySelectorAll: () => [], addEventListener() { }, createElement: makeElement },
    location: { hash: '', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) },
    innerWidth: 1400, addEventListener() { },
    fetch: async url => {
      if (Object.prototype.hasOwnProperty.call(serve, url)) { const doc = serve[url]; return { ok: true, status: 200, async json() { return JSON.parse(JSON.stringify(doc)); } }; }
      return { ok: false, status: 404, async json() { throw new Error('404'); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox; sandbox._store = store;
  const lines = fs.readFileSync(HTML, 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'index.html: could not find the inline <script>');
  // One handle at a time through a direct eval, which sees the script's lexical scope: a page that lacks a
  // name (the page from before this change) still loads, and each test then fails on its own assertion.
  const src = lines.slice(a + 1, b).join('\n')
    + `\n;for (const k of ${JSON.stringify(HANDLES)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  const $ = sel => sandbox.document.querySelector(sel);
  return { sb: sandbox, $, app: () => $('#app').innerHTML, sidebar: () => $('#sidebar').innerHTML };
}
async function ready(page) {
  await page.sb.loadIndex();
  for (let i = 0; i < 20 && !page.sb.S.index?.divisions; i++) await new Promise(r => setTimeout(r, 0));
  assert.ok(page.sb.S.index?.divisions, 'the index never finished loading');
  return page;
}
const plain = v => v === undefined ? v : JSON.parse(JSON.stringify(v)); // undefined passes through, so an assertion reports it
const subtitle = html => (/<div class="content-subtitle">([\s\S]*?)<\/div>/.exec(html) || [])[1] ?? null;
const slugsIn = html => [...html.matchAll(/data-slug="([^"]+)"/g)].map(m => m[1]);
const nz = v => (typeof v === 'number' && Number.isFinite(v)) ? v : null;
function reset(S) { Object.assign(S.filters, { conf: [], region: [], division: [], classYear: [], sort: 'name', view: 'cards', cond: [] }); S.q = ''; S.qRaw = ''; S.condForm = null; }

/* What each field should read, written from index.json's field paths and NOT from the page. */
const EXPECT_GET = {
  admissionRate: p => p.admissionRate,
  tuition: p => p.tuitionOutOfState ?? p.tuitionInState, // the Tuition sort's rule: "Tuition (out-of-state)"
  undergradEnrollment: p => p.undergradEnrollment,
  academicRank: p => p.academicRank,
  sat25: p => p.sat25,
  rpiRank: p => (p.lastSeason?.year === RPI_SEASON ? p.lastSeason.rpiRank : null) ?? (p.rpiHistory || []).find(r => r.year === RPI_SEASON)?.rank,
  nationalTitles: p => (TITLE_TABLE_DIVISIONS.includes(p.division) || p.nationalTitles > 0) ? p.nationalTitles : null,
  collegeCups: p => (p.division === 'D1' || p.collegeCups > 0) ? p.collegeCups : null,
  rosterSize: p => p.rosterSize,
  fallAvgHighF: p => p.fallClimate?.avgHighF,
};

/* A synthetic index for exact boundaries and overlapping gaps. Every other field is left out on purpose. */
const row = (slug, extra) => ({ slug, name: `${slug} University`, shortName: slug, conference: 'Test', division: 'D1', region: 'West',
  state: 'CA', nationalTitles: 0, collegeCups: 0, ...extra });
const SYNTH = { updated: SHIPPED.updated, season: SHIPPED.season, programs: [
  row('below', { admissionRate: 0.29, academicRank: 49, sat25: 1300 }),
  row('exact', { admissionRate: 0.3, academicRank: 50, sat25: 1200 }),
  row('above', { admissionRate: 0.31, academicRank: 51, sat25: 1100 }),
  // two chips, academicRank <= 100 AND sat25 >= 1200, over these gaps:
  row('gapRank', { admissionRate: 0.5, sat25: 1250 }),                   // no rank, passes SAT     -> hidden, missing rank
  row('gapSat', { admissionRate: 0.5, academicRank: 80 }),               // no SAT, passes rank     -> hidden, missing SAT
  row('gapBoth', { admissionRate: 0.5 }),                                // neither                 -> hidden ONCE, missing both
  row('gapRankFailsSat', { admissionRate: 0.5, sat25: 900 }),            // no rank, FAILS SAT      -> did not match, not hidden
  row('failsBoth', { admissionRate: 0.5, academicRank: 300, sat25: 800 }), // has both, fails        -> did not match
  row('noAdmit', { academicRank: 10, sat25: 1500 }),
] };

/* ---------- the page as it shipped before #166, verbatim from origin/main at 948a46ea ----------
   The ordering is copied too (sortCmp and the helpers it reads), so the equivalence below does not lean on
   the page's own sortCmp: a change to how the list sorts fails it just as a change to what it selects does. */
const displayNameBefore = p => p.shortName || p.name || '';
const byDisplayNameBefore = (a, b) => { const x = displayNameBefore(a), y = displayNameBefore(b);
  return x.localeCompare(y, undefined, { sensitivity: 'accent' }) || x.localeCompare(y); };
const rpiOfBefore = p => (p.lastSeason?.year === RPI_SEASON ? p.lastSeason.rpiRank : null) ?? (p.rpiHistory || []).find(r => r.year === RPI_SEASON)?.rank ?? null;
const tuitionOfBefore = p => p.tuitionOutOfState ?? p.tuitionInState ?? 1e12;
const commitsForBefore = (p, years) => Object.entries(p.commitmentsByYear || {}).filter(([y]) => !years.length || years.includes(y)).reduce((a, [, n]) => a + n, 0);
const sortCmpBefore = S => key => {
  const cy = S.filters.classYear;
  return (a, b) => key === 'name' ? byDisplayNameBefore(a, b)
    : key === 'admit' ? (a.admissionRate ?? 1) - (b.admissionRate ?? 1)
    : key === 'titles' ? b.nationalTitles - a.nationalTitles
    : key === 'tuition' ? tuitionOfBefore(a) - tuitionOfBefore(b)
    : key === 'undergrads' ? (b.undergradEnrollment ?? -1) - (a.undergradEnrollment ?? -1)
    : key === 'record' ? (b.lastSeason?.record || '').localeCompare(a.lastSeason?.record || '')
    : key === 'commits' ? commitsForBefore(b, cy) - commitsForBefore(a, cy)
    : key === 'conference' ? (a.conference || '').localeCompare(b.conference || '')
    : key === 'academicRank' ? ((a.academicRank ?? 1e9) - (b.academicRank ?? 1e9)) || byDisplayNameBefore(a, b)
    : (rpiOfBefore(a) ?? 999) - (rpiOfBefore(b) ?? 999);
};
function matchesFiltersBefore(S, matchScore, p, score) {
  const f = S.filters;
  return (!S.q || (score ? score.has(p.slug) : !!matchScore(p, S.q)))
    && (!f.conf.length || f.conf.includes(p.conference))
    && (!f.region.length || f.region.includes(p.region))
    && (!f.division.length || f.division.includes(p.division));
}
function filteredProgramsBefore(S, matchScore, sortCmp) {
  const idx = S.index, f = S.filters;
  const score = new Map();
  idx.programs.forEach(p => { const m = S.q ? matchScore(p, S.q) : null; p._why = m?.why || null; if (m) score.set(p.slug, m.score); });
  let rows = idx.programs.filter(p => matchesFiltersBefore(S, matchScore, p, score));
  rows.sort((a, b) => (S.q ? (score.get(b.slug) - score.get(a.slug)) : 0) || sortCmp(f.sort)(a, b));
  return rows;
}
function subtitleBefore(sb, rows) {
  const S = sb.S, f = S.filters, idx = S.index;
  const escFor = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const bits = [sb.corpusLabel(), `${rows.length} of ${idx.programs.length} program${idx.programs.length === 1 ? '' : 's'}`];
  if (f.conf.length > 1) bits.push(escFor(f.conf.join(', ')));
  if (f.region.length) bits.push(`${escFor(f.region.join(', '))} region${f.region.length > 1 ? 's' : ''}`);
  if (f.classYear.length) bits.push(`class${f.classYear.length > 1 ? 'es' : ''} of ${escFor(f.classYear.join(', '))}`);
  if (S.q) bits.push(`matching “${escFor(S.qRaw)}”`);
  bits.push(`sorted by ${sb.SORTS.find(s => s[0] === f.sort)?.[1] || 'RPI'}`);
  return bits.join(' · ');
}

const real = await ready(loadPage());

test('registry: exactly the ten fields shipped, each complete, and each accessor reads what index.json holds', () => {
  const { COND_FIELDS, COND_UNITS } = real.sb;
  assert.ok(Array.isArray(COND_FIELDS), 'COND_FIELDS: no field registry on the page');
  assert.deepEqual(plain(COND_FIELDS.map(d => d.key)), Object.keys(EXPECT_GET), 'the registry is not exactly the fields #166 ships');
  for (const d of COND_FIELDS) {
    for (const k of ['label', 'chip', 'missing']) assert.ok(typeof d[k] === 'string' && d[k], `${d.key}: no ${k}`);
    assert.ok(COND_UNITS[d.unit], `${d.key}: unit ${d.unit} is not in COND_UNITS`);
    assert.ok(d.ops.length && d.ops.every(op => ['<', '<=', '>', '>=', '='].includes(op)), `${d.key}: bad ops ${d.ops}`);
    assert.equal(typeof d.get, 'function', `${d.key}: no accessor`);
  }
  assert.deepEqual(plain(COND_FIELDS.filter(d => d.lowerIsBetter).map(d => d.key)), ['academicRank', 'rpiRank'], 'the lower-is-better fields');
  assert.ok(!COND_FIELDS.find(d => d.key === 'admissionRate').ops.includes('='), 'equality on a rate is not offered');
  // Every shipped row is D1 today, so non-D1 rows are added. D3 has no champions table: its zero title and
  // College Cup counts must read as "no data", while a real title still counts. D2 has one (#206): its zero
  // title count is a real 0, and its zero College Cup count is still "no data".
  const rows = [...SHIPPED.programs, { slug: 'synthetic-d3', division: 'D3', nationalTitles: 0, collegeCups: 0 },
    { slug: 'synthetic-d3-champion', division: 'D3', nationalTitles: 2, collegeCups: 3 },
    { slug: 'synthetic-d2', division: 'D2', nationalTitles: 0, collegeCups: 0 },
    { slug: 'synthetic-d2-champion', division: 'D2', nationalTitles: 7, collegeCups: 0 }];
  assert.deepEqual(plain(real.sb.TITLE_TABLE_DIVISIONS), TITLE_TABLE_DIVISIONS, 'the page and build.py disagree on which divisions have a champions table');
  const titles = COND_FIELDS.find(d => d.key === 'nationalTitles');
  assert.equal(titles.get(rows.find(p => p.slug === 'synthetic-d2')), 0, 'a D2 program with no titles reads as no data, not 0');
  assert.equal(titles.get(rows.find(p => p.slug === 'synthetic-d3')), null, 'a D3 zero (no champions table) reads as a known 0');
  assert.equal(real.sb.condStatus(rows.find(p => p.slug === 'synthetic-d2'), [{ field: 'nationalTitles', op: '>=', value: 1 }]), 'fail',
    'Titles >= 1 on a D2 program with no titles: hidden for missing data instead of simply not matching');
  for (const d of COND_FIELDS) {
    const wrong = rows.filter(p => nz(d.get(p)) !== nz(EXPECT_GET[d.key](p)));
    assert.equal(wrong.length, 0, `${d.key}: accessor disagrees with the data on ${wrong.slice(0, 3).map(p => p.slug)}`);
  }
  // tuition: where a school publishes two different figures, the condition reads the one the Tuition sort orders by
  const both = SHIPPED.programs.filter(p => p.tuitionInState != null && p.tuitionOutOfState != null && p.tuitionInState !== p.tuitionOutOfState);
  assert.ok(both.length > 50, 'expected public schools with separate in-state and out-of-state tuition');
  const tuition = COND_FIELDS.find(d => d.key === 'tuition');
  for (const p of both) assert.equal(tuition.get(p), real.sb.tuitionOf ? real.sb.tuitionOf(p) : p.tuitionOutOfState, `${p.slug}: tuition condition does not follow the Tuition sort`);
});

test('display units: 30 and 30% are 0.30, $40k is 40000; the chip formats them back; junk input is refused', () => {
  const { condFromInput, condText } = real.sb;
  const v = (f, op, t) => plain(condFromInput(f, op, t)).cond?.value;
  assert.equal(v('admissionRate', '<', '30'), 0.3, 'admissionRate < "30"');
  assert.equal(v('admissionRate', '<', '30%'), 0.3, 'admissionRate < "30%"');
  assert.equal(v('admissionRate', '<', ' 7.5 % '), 0.075, 'admissionRate < " 7.5 % "');
  assert.equal(v('tuition', '<=', '$40k'), 40000, 'tuition <= "$40k"');
  assert.equal(v('tuition', '<=', '40K'), 40000, 'tuition <= "40K"');
  assert.equal(v('tuition', '<=', '$40,000'), 40000, 'tuition <= "$40,000"');
  assert.equal(v('tuition', '<=', '40000'), 40000, 'tuition <= "40000"');
  assert.equal(v('academicRank', '<=', '#50'), 50, 'academicRank <= "#50"');
  assert.equal(v('fallAvgHighF', '>=', '75°F'), 75, 'fallAvgHighF >= "75°F"');
  assert.equal(v('undergradEnrollment', '>', '10,000'), 10000, 'undergradEnrollment > "10,000"');
  for (const bad of ['', 'abc', '30abc', 'Infinity', '1e999', '$', 'k', '--3']) {
    const r = plain(condFromInput('admissionRate', '<', bad));
    assert.ok(r.error && !r.cond, `"${bad}" should be refused, got ${JSON.stringify(r)}`);
  }
  assert.ok(plain(condFromInput('admissionRate', '=', '30')).error, 'an op the field does not allow is refused');
  assert.ok(plain(condFromInput('coachSince', '<', '2000')).error, 'a field outside the registry is refused');
  assert.equal(condText({ field: 'admissionRate', op: '<', value: 0.3 }), 'Admission < 30%');
  assert.equal(condText({ field: 'tuition', op: '<=', value: 40000 }), 'Tuition ≤ $40k');
  assert.equal(condText({ field: 'tuition', op: '<=', value: 40500 }), 'Tuition ≤ $40,500');
  // ranks are worded, never a bare symbol that reads backwards
  assert.equal(condText({ field: 'rpiRank', op: '<=', value: 50 }), 'RPI #50 or better');
  assert.equal(condText({ field: 'academicRank', op: '>', value: 100 }), 'US rank worse than #100');
});

test('boundary: < excludes the value itself and <= includes it (and > / >= / = likewise)', async () => {
  const pg = await ready(loadPage({ index: SYNTH }));
  const { S, filteredPrograms } = pg.sb;
  const run = (field, op, value) => { reset(S); S.filters.cond = [{ field, op, value }]; return plain(filteredPrograms().map(p => p.slug)).sort(); };
  assert.deepEqual(run('admissionRate', '<', 0.3), ['below']);
  assert.deepEqual(run('admissionRate', '<=', 0.3), ['below', 'exact']);
  assert.deepEqual(run('admissionRate', '>', 0.3), ['above', 'gapBoth', 'gapRank', 'gapRankFailsSat', 'gapSat', 'failsBoth'].sort());
  assert.deepEqual(run('admissionRate', '>=', 0.3), ['above', 'exact', 'gapBoth', 'gapRank', 'gapRankFailsSat', 'gapSat', 'failsBoth'].sort());
  assert.deepEqual(run('academicRank', '=', 50), ['exact']);
  assert.deepEqual(run('academicRank', '<', 50), ['below', 'noAdmit']);
  assert.deepEqual(run('academicRank', '<=', 50), ['below', 'exact', 'noAdmit']);
});

test('AND: conditions narrow together with the pills and with search, in both directions', () => {
  const { S, filteredPrograms, matchScore, normText } = real.sb;
  const P = S.index.programs; // the loaded rows: matchScore needs the search index the page builds on load
  reset(S);
  S.filters.region = ['South']; S.q = normText('state'); S.qRaw = 'state';
  S.filters.cond = [{ field: 'admissionRate', op: '>=', value: 0.5 }, { field: 'undergradEnrollment', op: '>', value: 15000 }];
  const got = plain(filteredPrograms().map(p => p.slug)).sort();
  const want = P.filter(p => p.region === 'South' && matchScore(p, S.q) && p.admissionRate >= 0.5 && p.undergradEnrollment > 15000).map(p => p.slug).sort();
  // Fixture guards, computed from the data alone: each of the four parts removes programs the other three
  // keep, so a page that dropped any one of them from the conjunction could not produce `want`.
  const keeps = (region, search, admit, ug) => P.filter(p => (!region || p.region === 'South') && (!search || matchScore(p, S.q))
    && (!admit || p.admissionRate >= 0.5) && (!ug || p.undergradEnrollment > 15000)).length;
  assert.ok(want.length > 0, 'fixture: the state should leave some programs');
  assert.ok(keeps(false, true, true, true) > want.length, 'fixture: the region pill narrows nothing');
  assert.ok(keeps(true, false, true, true) > want.length, 'fixture: search narrows nothing');
  assert.ok(keeps(true, true, false, true) > want.length, 'fixture: the first chip narrows nothing');
  assert.ok(keeps(true, true, true, false) > want.length, 'fixture: the second chip narrows nothing');
  assert.deepEqual(got, want);
  // a conference pill with a chip
  reset(S); S.filters.conf = ['SEC']; S.filters.cond = [{ field: 'tuition', op: '<=', value: 40000 }];
  assert.deepEqual(plain(filteredPrograms().map(p => p.slug)).sort(),
    P.filter(p => p.conference === 'SEC' && (p.tuitionOutOfState ?? p.tuitionInState) != null && (p.tuitionOutOfState ?? p.tuitionInState) <= 40000).map(p => p.slug).sort());
  reset(S);
});

test('hide and count, one chip on the real index: programs with no academic rank are hidden and counted apart', async () => {
  const { S, renderList } = real.sb;
  reset(S); S.filters.cond = [{ field: 'academicRank', op: '<=', value: 50 }];
  await renderList();
  const P = SHIPPED.programs;
  const shown = P.filter(p => p.academicRank != null && p.academicRank <= 50).length;
  const missing = P.filter(p => p.academicRank == null).length;
  assert.ok(missing > 100 && shown > 0, `unexpected data: ${shown} shown, ${missing} missing`);
  const sub = subtitle(real.app());
  assert.ok(sub.includes(`${shown} of ${P.length} programs · ${missing} hidden: no academic rank`), `subtitle: ${sub}`);
  assert.ok(sub.includes('US rank #50 or better'), `the chip is named in the subtitle: ${sub}`);
  assert.equal(slugsIn(real.app()).length, shown, 'cards on screen');
  // with a pill as well, the count is taken over what the pill leaves
  S.filters.region = ['West'];
  await renderList();
  const westMissing = P.filter(p => p.region === 'West' && p.academicRank == null).length;
  assert.ok(subtitle(real.app()).includes(` · ${westMissing} hidden: no academic rank`), subtitle(real.app()));
  /* A second chip, with its expectation read off the shipped index rather than assumed (#197): on the D1-only index
     every program has an undergraduate count, so the chip adds no hidden phrase at all; with D2 published two
     programs lack one, and the phrase must count exactly those. */
  reset(S); S.filters.cond = [{ field: 'undergradEnrollment', op: '>', value: 0 }];
  await renderList();
  const noUndergrads = P.filter(p => nz(p.undergradEnrollment) == null).length;
  const withUndergrads = P.filter(p => nz(p.undergradEnrollment) != null && p.undergradEnrollment > 0).length;
  const sub2 = subtitle(real.app());
  if (noUndergrads === 0) assert.ok(!/hidden/.test(sub2), `every program has an undergraduate count, so nothing is hidden: ${sub2}`);
  else assert.ok(sub2.includes(`${withUndergrads} of ${P.length} programs · ${noUndergrads} hidden: no undergraduate count`), `subtitle: ${sub2}`);
  reset(S);
});

test('hide and count, two chips over overlapping gaps: a program missing both is counted once; one failing a known rule is not hidden', async () => {
  const pg = await ready(loadPage({ index: SYNTH }));
  const { S, renderList, condTally, condHiddenText, filteredPrograms } = pg.sb;
  reset(S);
  const conds = [{ field: 'academicRank', op: '<=', value: 100 }, { field: 'sat25', op: '>=', value: 1200 }];
  S.filters.cond = conds;
  assert.deepEqual(plain(filteredPrograms().map(p => p.slug)).sort(), ['below', 'exact', 'noAdmit']);
  const t = plain(condTally(SYNTH.programs, conds));
  // gapRank, gapSat, gapBoth are hidden for missing data; gapRankFailsSat and failsBoth simply did not match; 'above' fails SAT
  assert.deepEqual(t, { pass: 3, fail: 3, missing: 3, byField: { academicRank: 2, sat25: 2 } });
  assert.equal(condHiddenText(t, conds), '3 hidden for missing data: 2 no academic rank, 2 no SAT score (counted once when more than one is missing)');
  await renderList();
  assert.ok(subtitle(pg.app()).includes(`3 of ${SYNTH.programs.length} programs · 3 hidden for missing data: 2 no academic rank, 2 no SAT score (counted once`), subtitle(pg.app()));
  // without the program missing both, the parts add up and the "counted once" note is not printed
  const noOverlap = SYNTH.programs.filter(p => p.slug !== 'gapBoth');
  assert.equal(condHiddenText(condTally(noOverlap, conds), conds), '2 hidden for missing data: 1 no academic rank, 1 no SAT score');
  // two chips on the SAME field count that field once per program
  const same = [{ field: 'sat25', op: '>=', value: 1000 }, { field: 'sat25', op: '<=', value: 1400 }];
  assert.deepEqual(plain(condTally(SYNTH.programs, same)).byField, { sat25: 2 }, 'a field named by two chips was counted twice per program');
  assert.equal(condHiddenText(condTally(SYNTH.programs, same), same), '2 hidden: no SAT score');
});

test('saved cd.filters: junk conditions are dropped on load, never thrown on, and the valid one survives', async () => {
  const valid = { field: 'academicRank', op: '<=', value: 50 };
  const junk = [
    { field: 'coachSince', op: '<', value: 2000 }, { field: 'constructor', op: '<', value: 1 }, { field: '__proto__', op: '<', value: 1 },
    { field: 'toString', op: '<', value: 1 }, { field: 'admissionRate', op: '=', value: 0.3 }, { field: 'admissionRate', op: '!=', value: 0.3 },
    { field: 'admissionRate', op: '<', value: '0.3' }, { field: 'admissionRate', op: '<', value: null }, { field: 'admissionRate', op: '<' },
    { field: ['admissionRate'], op: '<', value: 0.3 }, { op: '<', value: 0.3 }, null, 7, 'admissionRate<0.3', ['admissionRate', '<', 0.3], [],
  ];
  // 1e999 parses to Infinity: written raw, because JSON.stringify cannot produce it
  const raw = JSON.stringify({ conf: [], region: ['South'], cond: [...junk, valid] }).replace(/\]\}$/, ',{"field":"sat25","op":">","value":1e999}]}');
  const cases = {
    'junk entries': [raw, [valid]],
    'cond is a string': [JSON.stringify({ cond: 'admissionRate<0.3' }), []],
    'cond is one object, not a list': [JSON.stringify({ cond: valid }), []],
    'cond is null': [JSON.stringify({ cond: null }), []],
    'a save from before #166': [JSON.stringify({ conf: ['SEC'], sort: 'rpi' }), []],
    'cd.filters is not JSON': ['{not json', []],
  };
  for (const [name, [stored, want]] of Object.entries(cases)) {
    let pg;
    assert.doesNotThrow(() => { pg = loadPage({ seed: { 'cd.filters': stored } }); }, name);
    await ready(pg);
    assert.deepEqual(plain(pg.sb.S.filters.cond), want, name);
    await assert.doesNotReject(pg.sb.renderList(), name);
    assert.ok(subtitle(pg.app()) != null, `${name}: the list did not render`);
  }
  const pg = await ready(loadPage({ seed: { 'cd.filters': raw } }));
  assert.deepEqual(plain(pg.sb.S.filters.region), ['South'], 'the pills in the same save are untouched');
});

test('every "Clear filters" control on the page clears condition chips', async () => {
  const source = fs.readFileSync(HTML, 'utf8');
  // The controls are read from the source, so one added later without clearing chips is caught by this list growing.
  const ids = [...source.matchAll(/id="([A-Za-z]+)"[^>]*>\s*Clear filters\s*</g)].map(m => m[1]);
  assert.deepEqual(ids, ['campsClear'], `the Clear filters controls on the page: ${ids}`);
  const pg = await ready(loadPage());
  const { S, renderCamps } = pg.sb;
  reset(S); S.filters.region = ['South'];
  S.filters.cond = [{ field: 'admissionRate', op: '<', value: 0 }]; // matches nothing, so the empty state and its button render
  pg.sb.location.hash = '#/camps';
  await renderCamps();
  assert.ok(pg.app().includes('id="campsClear"'), 'the camps empty state has no Clear filters button');
  const clear = pg.$('#campsClear').onclick;
  assert.equal(typeof clear, 'function', '#campsClear has no handler');
  clear();
  assert.deepEqual(plain(S.filters.cond), [], 'Clear filters left the chips on');
  assert.deepEqual(plain(S.filters.region), [], 'Clear filters left a pill on');
  const saved = JSON.parse(pg.sb._store.get('cd.filters') || '{}');
  assert.ok(Array.isArray(saved.cond) && saved.cond.length === 0, `the cleared chips were not saved: ${JSON.stringify(saved.cond)}`);
  reset(S);
});

test('the ID Camp View honours chips and counts the camps hidden for missing data', async () => {
  const pg = await ready(loadPage());
  const { S, renderCamps } = pg.sb;
  const byProgram = new Map(SHIPPED.programs.map(p => [p.slug, p]));
  const idCamps = CAMPS.camps.filter(c => c.campType === 'id' && byProgram.has(c.slug));
  reset(S); S.filters.cond = [{ field: 'academicRank', op: '<=', value: 100 }];
  pg.sb.location.hash = '#/camps';
  await renderCamps();
  const want = idCamps.filter(c => byProgram.get(c.slug).academicRank != null && byProgram.get(c.slug).academicRank <= 100);
  const missing = idCamps.filter(c => byProgram.get(c.slug).academicRank == null).length;
  assert.ok(want.length > 0 && missing > 0, `fixture: ${want.length} shown, ${missing} missing`);
  const html = pg.app();
  assert.deepEqual(slugsIn(html).sort(), want.map(c => c.slug).sort(), 'camp rows on screen');
  const sub = subtitle(html);
  assert.ok(sub.includes(`${want.length} upcoming ID camp${want.length === 1 ? '' : 's'} of ${idCamps.length}`), sub);
  assert.ok(sub.includes(`${missing} camp${missing === 1 ? '' : 's'} hidden: no academic rank`), sub);
  assert.ok(sub.includes('US rank #100 or better'), sub);
  reset(S);
});

test('no chips: Program View rows are in byte-identical order to the code that shipped before, and the subtitle is unchanged', async () => {
  const { S, filteredPrograms, matchScore, normText, renderList } = real.sb;
  const sortCmp = sortCmpBefore(S); // the ordering as it shipped, not the page's
  // every key sortCmp handles: the sidebar's sorts and the table-header-only ones
  const sorts = ['name', 'rpi', 'admit', 'academicRank', 'tuition', 'undergrads', 'titles', 'record', 'commits', 'conference'];
  const confs = [[], ['SEC'], ['ACC', 'Big Ten']];
  const regions = [[], ['South'], ['West', 'Midwest']];
  const queries = ['', 'state', 'u'];
  const views = ['cards', 'table'];
  let states = 0;
  for (const sort of sorts) for (const conf of confs) for (const region of regions) for (const q of queries) {
    reset(S); Object.assign(S.filters, { sort, conf: [...conf], region: [...region] }); S.q = normText(q); S.qRaw = q;
    const before = filteredProgramsBefore(S, matchScore, sortCmp).map(p => p.slug).join('\n');
    const after = filteredPrograms().map(p => p.slug).join('\n');
    assert.equal(after, before, `row order differs: sort=${sort} conf=${conf} region=${region} q=${q}`);
    states++;
  }
  assert.equal(states, 270);
  for (const view of views) for (const sort of sorts) for (const conf of confs) {
    reset(S); Object.assign(S.filters, { sort, conf: [...conf], region: ['South'], view }); S.q = normText('a'); S.qRaw = 'a';
    const rows = filteredProgramsBefore(S, matchScore, sortCmp);
    await renderList();
    const html = real.app();
    assert.equal(subtitle(html), subtitleBefore(real.sb, rows), `subtitle differs: view=${view} sort=${sort} conf=${conf}`);
    assert.equal(slugsIn(html).join('\n'), rows.map(p => p.slug).join('\n'), `rendered order differs: view=${view} sort=${sort} conf=${conf}`);
  }
  reset(S);
});

test('the add form: labelled native controls; a bad value is refused in words, a good one becomes a chip; Escape cancels', () => {
  const pg = real;
  const { S, condFormOpen, condFormSubmit, renderSidebar, condRemove } = pg.sb;
  reset(S); renderSidebar();
  assert.ok(/id="condAdd"[^>]*aria-expanded="false"|aria-expanded="false"[^>]*id="condAdd"/.test(pg.sidebar()), 'the + Add control is missing or not a disclosure');
  assert.ok(/<button type="button" class="pill" id="condAdd"/.test(pg.sidebar()), '+ Add is not a button styled as a pill');
  condFormOpen();
  const sb = pg.sidebar();
  for (const id of ['condField', 'condOp', 'condValue']) {
    assert.ok(sb.includes(`<label for="${id}">`) && sb.includes(`id="${id}"`), `${id} has no label`);
  }
  assert.ok(/<form class="cond-form" id="condForm"[\s\S]*<button type="submit"[\s\S]*<\/form>/.test(sb), 'Enter in the value field needs a submit button inside the form');
  assert.ok(sb.includes('aria-expanded="true"'), '+ Add does not report the form open');
  pg.$('#condValue').value = 'thirty';
  assert.equal(condFormSubmit(), false);
  assert.ok(S.condForm?.error, 'no error recorded');
  assert.ok(/aria-invalid="true"/.test(pg.sidebar()) && /role="alert">Enter a number/.test(pg.sidebar()), 'the error is not announced');
  assert.deepEqual(plain(S.filters.cond), []);
  pg.$('#condValue').value = '30';
  assert.equal(condFormSubmit(), true);
  assert.deepEqual(plain(S.filters.cond), [{ field: 'admissionRate', op: '<', value: 0.3 }]);
  assert.equal(S.condForm, null, 'the form stayed open after adding');
  assert.ok(pg.sidebar().includes('aria-label="Remove condition: Admission &lt; 30%"'), 'the chip has no labelled remove button');
  assert.deepEqual(JSON.parse(pg.sb._store.get('cd.filters') || '{}').cond, [{ field: 'admissionRate', op: '<', value: 0.3 }], 'the chip was not saved');
  // changing field re-scopes the comparison: '=' is allowed on a rank, not on a rate
  condFormOpen();
  pg.$('#condField').onchange({ target: { value: 'academicRank' } });
  pg.$('#condOp').onchange({ target: { value: '=' } });
  pg.$('#condField').onchange({ target: { value: 'admissionRate' } });
  assert.equal(S.condForm.field, 'admissionRate');
  assert.equal(S.condForm.op, '<', 'a comparison the new field does not allow was kept');
  let prevented = false;
  pg.$('#condForm').onkeydown({ key: 'Escape', preventDefault() { prevented = true; }, stopPropagation() { } });
  assert.equal(S.condForm, null, 'Escape did not close the form');
  assert.ok(prevented);
  condRemove(0);
  assert.deepEqual(plain(S.filters.cond), [], 'the chip was not removed');
  reset(S);
});
