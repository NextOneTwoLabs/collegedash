// #507 v1, PR 1: the Home search's engine, homeSearch(campRows, raw), on the frozen fixture.
//
//     node --test tests/home_search_engine.test.mjs
//
// The engine is sliced out of public/index.html by its banner comment ("Home search (#507 v1)"), together with the
// page code it calls (the program matcher, the list address, the camps helpers), and run in a vm - the way the other
// search tests run the page's code. Data: tests/fixtures/search/{programs,camps}.json only (tools/search_fixture.py),
// at the fixture's clock (the date part of camps.json's `updated`). Nothing here reads public/data, the real date or
// the network, so the daily refresh never moves an expectation.
//
// What is checked (docs/plans/507-search/v1-plan.md, sections 3 and 6):
//   - the judged set, tests/fixtures/search/judged-v1.json: section order, program hits and drawn rows, the closing
//     "All N matching programs" link, camp count and first rows, Enter's target and the message, per query;
//   - "All N" opens exactly N: the link's q read back through the page's own listStateOf gives the same hits;
//   - with no camp word, Programs is exactly today's header-box matcher (searchMatches) for the same text;
//   - the camp-word rule, the Idaho exception, camps of program hits (rule 3), camps before they load;
//   - campsData(idx, doc, today) cuts "upcoming" at the date it is given, not the real one.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HTML = fs.readFileSync(process.env.HOME_SEARCH_TEST_HTML || path.join(HERE, '..', 'public', 'index.html'), 'utf8');
const FIX = path.join(HERE, 'fixtures', 'search');
const read = f => JSON.parse(fs.readFileSync(path.join(FIX, f), 'utf8'));
const PROGRAMS = read('programs.json'), CAMPS = read('camps.json'), JUDGED = read('judged-v1.json');
const CLOCK = CAMPS.updated.slice(0, 10);

function cut(from, to) {
  const i = HTML.indexOf(from);
  assert.ok(i >= 0, `index.html no longer has "${from}"`);
  const j = HTML.indexOf(to, i + from.length);
  assert.ok(j > i, `index.html has no "${to}" after "${from}"`);
  return HTML.slice(i, j);
}
function load() {
  const src = [
    cut('/* ---------- search: word-prefix matching', '/* ---------- condition chips: the field registry'),
    cut('const LIST_PARAMS', '// Writes the list\'s canonical address'),
    cut('const CAMP_CLASSES', '// The list header strip'),
    cut('const campIsPast', '/* #465: the camp page\'s state in the address'),
    cut('const campsNorm', '// Does camp `c` (program `info`) pass'),
    cut('let CAMPS = null;', 'const campsShown'),
    cut('/* ---------- Home search (#507 v1)', '/* ---------- router ---------- */'),
  ].join('\n');
  // The real Date: these tests pass every date explicitly. A call that read the real date would show up as a count
  // that moves, so todayLocal is made to fail instead.
  const sb = {
    S: { index: PROGRAMS, q: '', qRaw: '' }, console,
    matchesFilters: () => true, sanitizeConds: a => a.filter(Boolean), SORT_SPECS: { name: {} }, REGIONS: [],
    CONF_SEP: '|', splitConf: k => { const i = k.indexOf('|'); return i < 0 ? [null, k] : [k.slice(0, i), k.slice(i + 1)]; },
    confKeyOf: (d, c) => `${d}|${c}`,
    todayLocal: () => { throw new Error('read the real date'); },
  };
  vm.createContext(sb);
  vm.runInContext(src + `
    ;globalThis.__api = { homeSearch, campsData, searchMatches, normText, listStateOf, prepareSearch, HOME_ROWS, HOME_CAMP_ROWS };`, sb);
  const api = sb.__api;
  PROGRAMS.programs.forEach(p => api.prepareSearch(p));
  return api;
}
const A = load();
const ROWS = A.campsData(PROGRAMS, CAMPS, CLOCK).all;
const run = q => A.homeSearch(ROWS, q);
// Values made inside the vm have the vm's Array and Object prototypes, which deepEqual (strict) tells apart: compare plain copies.
const plain = v => JSON.parse(JSON.stringify(v));
const slugs = hits => plain(hits.map(h => h.p.slug));

test('the fixture clock gives the upcoming ID camps the ID Camps page would list', () => {
  assert.equal(CLOCK, '2026-10-21');
  assert.equal(ROWS.length, 83);
  assert.ok(ROWS.every(x => x.c.campType === 'id' && x.info && x.info.division), 'a row is not an ID camp or has no division');
  const dates = plain(ROWS.map(x => x.c.startDate));
  assert.deepEqual(dates, [...dates].sort(), 'not in date order');
});

test('campsData cuts "upcoming" at the date it is given, never the real date', () => {
  const later = A.campsData(PROGRAMS, CAMPS, '2026-11-21');
  assert.equal(later.today, '2026-11-21');
  assert.equal(later.all.length, 67);
  const lastOf = c => c.endDate || c.startDate;
  assert.ok(later.all.every(({ c }) => c.precision === 'month' ? lastOf(c).slice(0, 7) >= '2026-11' : lastOf(c) >= '2026-11-21'),
    'a camp that ended before the given date is still listed');
  assert.throws(() => A.campsData(PROGRAMS, CAMPS), /real date/, 'without a date it reads todayLocal(), as before');
});

test('an empty box gives no result at all', () => {
  for (const q of ['', '   ', '\u0007', ' - ']) assert.equal(run(q), null, JSON.stringify(q));
});

for (const j of JUDGED.queries) {
  test(`judged ${j.id} (${j.scope}) ${JSON.stringify(j.q)}: ${j.intent}`, () => {
    const r = run(j.q);
    assert.ok(r, 'no result');
    assert.deepEqual(plain(r.order), j.order, 'section order');
    assert.equal(r.programs.n, j.programs.n, 'program hits');
    assert.deepEqual(slugs(r.programs.rows), j.programs.rows, 'program rows drawn');
    assert.equal(r.programs.href, j.programs.allHref, '"All N matching programs" link');
    assert.equal(r.camps.n, j.camps.n, 'camps');
    assert.deepEqual(plain(r.camps.shown.map(x => ({ slug: x.c.slug, startDate: x.c.startDate }))), j.camps.first, 'first camps drawn');
    assert.deepEqual(plain(r.enter && { kind: r.enter.kind, href: r.enter.href }), j.enter, 'Enter');
    assert.equal(r.message, j.message, 'message');
  });
}

test('the judged set covers what the plan says it covers', () => {
  assert.equal(JUDGED.queries.length, 24);
  const ids = JUDGED.queries.map(j => j.id);
  assert.equal(new Set(ids).size, ids.length, 'duplicate id');
  assert.deepEqual(JUDGED.queries.filter(j => j.scope === 'v2').map(j => j.id), ['C01', 'D01', 'Y01', 'H01']);
});

test('every row carries its division: program rows and camp rows', () => {
  for (const j of JUDGED.queries) {
    const r = run(j.q);
    for (const h of r.programs.rows) assert.match(h.p.division, /^D[123]$/, `${j.q}: ${h.p.slug}`);
    for (const x of r.camps.all) assert.match(x.info.division, /^D[123]$/, `${j.q}: ${x.c.slug}`);
  }
});

test('"All N matching programs" opens exactly N: its q, read back by listStateOf, gives the same hits', () => {
  let seen = 0;
  for (const j of JUDGED.queries) {
    const r = run(j.q);
    if (!r.programs.href) { assert.ok(r.programs.n <= A.HOME_ROWS && r.programs.rows.length === r.programs.n, `${j.q}: hits hidden with no link`); continue; }
    seen++;
    assert.match(r.programs.href, /^#\/programs\?q=[^&]+&sort=name$/, 'only q (and the default sort) - every other filter at its default');
    const st = A.listStateOf(r.programs.href.split('?')[1]);
    assert.equal(A.searchMatches(A.normText(st.q), Infinity, st.q).length, r.programs.n, j.q);
  }
  assert.ok(seen >= 8, `only ${seen} judged queries have the link`);
});

test('with no camp word, Programs is exactly the header box\'s matcher for the same text', () => {
  for (const q of ['unc', 'Ohio', 'OH', 'columbus oh', 'bulldogs', 'st. mary\'s', 'washington', 'philadelphia', 'a', 'st']) {
    const r = run(q);
    assert.deepEqual(slugs(r.programs.hits), slugs(A.searchMatches(A.normText(q), Infinity, q)), q);
    assert.deepEqual(slugs(r.programs.rows), slugs(r.programs.hits.filter(h => !h.m.place).slice(0, 6)), `${q}: rows are the first 6 non-place hits`);
  }
  const p = run('philadelphia');  // only place hits: no rows, the place option, and Enter opens the list
  assert.equal(p.programs.rows.length, 0);
  assert.ok(p.programs.n > 0 && p.programs.href);
  assert.deepEqual(plain({ kind: p.enter.kind, href: p.enter.href }), { kind: 'list', href: p.programs.href });
});

test('camp words: removed from the program query, a lone camp word still finds a program, only camp words list every camp', () => {
  const camp = run('camp');
  assert.ok(slugs(camp.programs.rows).includes('campbell'), 'a lone "camp" no longer finds Campbell');
  assert.equal(camp.camps.n, ROWS.length);
  assert.deepEqual(plain(camp.order), ['camps', 'programs']);
  const id = run('id');
  assert.deepEqual(slugs(id.programs.rows), ['idaho', 'idaho-state'], 'a lone lowercase "id" no longer finds Idaho');
  assert.equal(id.camps.n, ROWS.length);
  assert.deepEqual(plain(id.order), ['camps', 'programs']);
  for (const q of ['id camps', 'CLINICS', 'ID Camp']) assert.equal(run(q).camps.n, ROWS.length, q);
  assert.equal(run('TX camps').programs.n, run('TX').programs.n, '"TX camps" keeps the capitals rule');
  assert.equal(run('TX camps').programs.href, run('TX').programs.href);
  assert.equal(run('tx camps').programs.n, run('tx').programs.n);
  assert.deepEqual(plain({ ...run('ucla id-camp'), typed: 0, programs: slugs(run('ucla id-camp').programs.hits) }), plain({ ...run('ucla id camp'), typed: 0, programs: slugs(run('ucla id camp').programs.hits) }), 'a hyphen joins words; it does not hide a camp word');
});

// Bianque on PR 1: with camp words dropped, the "All N" link carries what was typed, case and punctuation kept, so the
// Programs page's box shows "St. Mary's", not "st mary s" - and it still finds exactly the same programs.
test('camp words dropped: the program query (and the "All N" link) keeps the typed case and punctuation', () => {
  for (const [q, pq] of [["St. Mary's camps", "St. Mary's"], ['TX camps', 'TX'], ['tx camps', 'tx'], ['ucla id-camp', 'ucla'],
    ['ID camps Ohio', 'Ohio'], ['Texas A&M camp', 'Texas A&M'], ['camps: penn state', 'penn state'], ['bulldogs, clinics', 'bulldogs']]) {
    const r = run(q), plainRun = run(pq);
    assert.equal(r.pq, pq, q);
    assert.deepEqual(slugs(r.programs.hits), slugs(plainRun.programs.hits), `${q}: not the same programs as "${pq}"`);
  }
  assert.equal(run('bulldogs, clinics').programs.href, '#/programs?q=bulldogs&sort=name');
  // a link that carries punctuation: the Programs page reads back exactly what was typed, and lists the same N
  const st = run('St. camps');
  assert.equal(st.programs.href, '#/programs?q=St.&sort=name');
  const back = A.listStateOf(st.programs.href.split('?')[1]).q;
  assert.equal(back, 'St.');
  assert.equal(A.searchMatches(A.normText(back), Infinity, back).length, st.programs.n);
});

test('the Idaho exception: exactly "ID" in capitals is a state code, not a camp word', () => {
  const r = run('ID'), spaced = run('  ID ');
  assert.deepEqual(plain(r.order), ['programs', 'camps']);
  assert.ok(r.camps.all.every(x => x.info.state === 'ID') && r.camps.n === 1, 'camps at Idaho programs only');
  assert.equal(r.enter.kind, 'list');
  assert.deepEqual(plain(spaced.order), plain(r.order), 'surrounding spaces do not matter');
  assert.deepEqual(plain(run('Id').order), ['camps', 'programs'], 'only capitals make it a code');
});

test('rule 3: camps of the programs found by name, alias or mascot - never by place', () => {
  for (const [q, slug] of [['msu', 'mississippi-state'], ['bruins', 'ucla'], ['gvsu', 'grand-valley-state'], ['uccs', 'colorado-colorado-springs']]) {
    const r = run(q);
    assert.ok(r.camps.n > 0 && r.camps.all.every(x => x.c.slug === slug), `${q}: ${r.camps.all.map(x => x.c.slug)}`);
  }
  const boston = run('boston');  // Northeastern is a place hit (Boston, MA); its camps must not come in by rule 3
  assert.ok(boston.programs.hits.some(h => h.m.place));
  assert.ok(boston.camps.all.every(x => boston.programs.hits.some(h => !h.m.place && h.p.slug === x.c.slug) || x.info.city === 'Boston'));
});

test('first show: 6 program rows and 4 camp rows; the rest are counted', () => {
  assert.equal(A.HOME_ROWS, 6);
  // Bianque on PR 1: Home draws as many program rows as the header box does; the two must not drift apart.
  assert.match(HTML, /\bconst SUGGEST_MAX = 6\b/, 'the header box\'s SUGGEST_MAX changed; HOME_ROWS must follow it');
  assert.equal(A.HOME_CAMP_ROWS, 4);
  const r = run('a');
  assert.equal(r.programs.rows.length, 6);
  assert.equal(r.camps.shown.length, 4);
  assert.ok(r.camps.shown.every((x, i) => x === r.camps.all[i]));
});

test('before the camps load: Programs work, Camps say they are loading', () => {
  const unc = A.homeSearch(null, 'unc');
  assert.equal(unc.camps, null);
  assert.equal(unc.message, null);
  assert.equal(unc.enter.href, '#/p/north-carolina');
  const usc = A.homeSearch(null, 'usc camps');
  assert.deepEqual(plain(usc.order), ['camps', 'programs']);
  assert.equal(usc.message, 'loading');
  assert.equal(usc.enter.href, '#/p/usc', 'Enter opens the first program row until camps arrive');
  assert.equal(A.homeSearch(null, 'zzzz').message, 'loading', 'no-match is not decided before camps arrive');
});

test('a long query is capped the way the Programs address caps q', () => {
  const r = run('x'.repeat(150));
  assert.equal(r.typed.length, 100);
  const w = run('washington' + ' '.repeat(200) + 'x');
  assert.equal(w.typed, 'washington', 'cut to 100 characters, then trimmed');
});
