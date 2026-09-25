// Division III on the page (issue #94, PR 3 of the D3 publish plan; #246 for the RPI rule).
//
//     node --test tests/d3_publish_frontend.test.mjs
//
// Same mechanism as tests/d2_publish_frontend.test.mjs: the inline <script> of public/index.html runs in a `vm`
// against a stub DOM, and fetch is a stub. D3 is not published yet, so every Division III program here is a
// fixture generated in this file from committed profiles:
//   - test-d3-full: north-carolina's row and profile relabelled D3. It deliberately KEEPS an RPI rank, RPI
//     history and a College Cup count, so every "not applicable" check passes because the division rule hides
//     them, not because the data is empty. Its title count is 0, a D3 program that never won the D3 title;
//   - test-d3-thin: bridgeport's row and profile relabelled D3. Bridgeport is a real published program whose
//     athletics host refuses the collector (registry athletics.skipReason), so this is the thin shape the ~50
//     refused D3 programs will publish in: no roster, schedule, staff or season, school facts and climate kept;
//   - test-d3-champion: stanford relabelled D3 with 3 titles, the shape a D3 champion takes once the D3 table
//     is added (the page reads a count > 0 in any division). The real D3 champions are checked from the
//     committed index too (#94: build.py has the D3 table).
// Two of them come FIRST in the index, so the sorts are tested on order they have to impose.
//
// What this proves:
//   - RPI and College Cups do not apply to Division III (NOT_APPLICABLE, #246): card, table, profile, glance,
//     History and Compare; the chips exclude D3 and say so, never as missing data; the RPI sort puts D3 last;
//   - titles with the D3 table (#94): no title figure on a D3 profile with none, no error, the titles chip counts
//     a D3 zero as a known 0; a D3 count > 0 reads "3 NCAA D3 titles"; real D3 champions' cards show theirs;
//   - the Division III scholarship sentence, on D3 only; D1 and D2 keep theirs;
//   - the thin D3 profile renders every tab without throwing and shows no empty athletics sections;
//   - Division I is unaffected: every tab of a D1 profile renders byte for byte the same with D3 loaded.
//
// D3_PAGE_HTML (optional) points at another copy of index.html, so a deliberately broken copy can be shown
// failing through these same checks.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { expectedRpi, expectedRpiOf, reEscape } from './rpi_season_helpers.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..');
const PUBLIC = path.join(ROOT, 'public');
const PAGE = process.env.D3_PAGE_HTML || path.join(PUBLIC, 'index.html');
const readJson = (rel) => JSON.parse(fs.readFileSync(path.join(PUBLIC, rel), 'utf8'));
const clone = (v) => JSON.parse(JSON.stringify(v));

// ---------- data ----------
const COMMITTED_INDEX = readJson('data/programs/index.json');
const REAL_INDEX = { ...COMMITTED_INDEX, programs: COMMITTED_INDEX.programs.filter((p) => p.division === 'D1') };
const D1_FILES = { 'data/programs/index.json': REAL_INDEX };
const anyRow = (slug) => { const r = COMMITTED_INDEX.programs.find((p) => p.slug === slug); assert.ok(r, `no ${slug} in the index`); return r; };
const RPI = expectedRpi(REAL_INDEX), RPI_SEASON = RPI.season;
const rpiOfRow = expectedRpiOf(REAL_INDEX);
const UNRANKED_D1 = REAL_INDEX.programs.find((p) => rpiOfRow(p) == null)?.slug;
const D3_CONF = 'Test Division III Conference';

function d3Row(base, slug, name, titles) {
  const r = clone(anyRow(base));
  Object.assign(r, { slug, name, shortName: name, nickname: 'Testers', division: 'D3', conference: D3_CONF, nationalTitles: titles });
  return r;
}
function d3Profile(base, r, titleYears) {
  const p = clone(readJson(`data/programs/${base}.json`));
  Object.assign(p, { slug: r.slug, name: r.name, shortName: r.shortName, nickname: r.nickname, division: 'D3', conference: r.conference });
  p.program = { ...(p.program || {}), nationalTitles: titleYears };
  return p;
}
const D3_FULL = d3Row('north-carolina', 'test-d3-full', 'Test D3 Full', 0);
const D3_THIN = d3Row('bridgeport', 'test-d3-thin', 'Test D3 Thin', 0);
const D3_CHAMP = d3Row('stanford', 'test-d3-champion', 'Test D3 Champion', 3);
assert.ok(rpiOfRow(D3_FULL) != null && D3_FULL.collegeCups > 0, 'the full fixture must keep an RPI and a College Cup count');
const FULL_PROFILE = d3Profile('north-carolina', D3_FULL, []);
assert.ok((FULL_PROFILE.seasons || []).some((s) => s.rpiRank) && FULL_PROFILE.program.collegeCups.length > 0, 'the full profile must keep RPI history and College Cups');
const THIN_PROFILE = d3Profile('bridgeport', D3_THIN, []);
assert.ok(!THIN_PROFILE.roster && !THIN_PROFILE.schedule && !(THIN_PROFILE.seasons || []).length && THIN_PROFILE.school,
  'bridgeport is no longer a thin profile with school facts; pick another refused program for the thin fixture');
const MIXED_INDEX = { ...clone(REAL_INDEX), programs: [D3_THIN, D3_FULL, D3_CHAMP, ...clone(REAL_INDEX.programs)] };
const MIXED_FILES = {
  'data/programs/index.json': MIXED_INDEX,
  'data/programs/test-d3-full.json': FULL_PROFILE,
  'data/programs/test-d3-thin.json': THIN_PROFILE,
  'data/programs/test-d3-champion.json': d3Profile('stanford', D3_CHAMP, [2018, 2019, 2021]),
};

// ---------- the page (the harness of d2_publish_frontend.test.mjs) ----------
function makeElement(name) {
  const listeners = {};
  return {
    _name: name, _listeners: listeners, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    removeEventListener() { }, querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, contains: () => false,
  };
}
const HANDLES = ['S', 'renderList', 'renderSidebar', 'renderCamps', 'renderProfile', 'renderCompare', 'renderFaq', 'loadIndex', 'condNaTally', 'condNaText', 'NOT_APPLICABLE', 'TITLE_TABLE_DIVISIONS'];

function loadPage(html = PAGE, files = {}) {
  const els = new Map();
  const bySelector = (sel) => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector, querySelectorAll: () => [],
      addEventListener() { }, createElement: makeElement },
    location: { hash: '', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
    innerWidth: 1400, addEventListener() { }, alert() { },
    fetch: async (url) => {
      const ok = (body, st = 200) => ({ ok: st < 400, status: st, async json() { return clone(body); } });
      let u = String(url);
      if (files[u]) return ok(files[u]);
      if (u === '/api/v1/programs' && files['data/programs/index.json']) return ok(files['data/programs/index.json']);
      if (u.startsWith('/api/v1/programs/')) {
        const slug = u.slice('/api/v1/programs/'.length);
        if (files[`data/programs/${slug}.json`]) return ok(files[`data/programs/${slug}.json`]);
      }
      if (u === '/api/v1/programs') u = 'data/programs/index.json';
      else if (u === '/api/v1/status') u = 'archive/refresh-state.json';
      else if (u.startsWith('/api/v1/programs/')) u = `data/programs/${u.slice('/api/v1/programs/'.length)}.json`;
      else if (u === '/api/v1/camps') u = 'data/camps/index.json';
      else if (u === '/api/v1/trends') u = 'data/trends/index.json';
      else if (u === '/api/v1/commitments') u = 'data/commitments/index.json';
      if (!u.startsWith('data/') && !u.startsWith('archive/')) return ok({}, 404);
      const p = path.join(PUBLIC, u);
      return fs.existsSync(p) ? ok(JSON.parse(fs.readFileSync(p, 'utf8'))) : ok({}, 404);
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(html, 'utf8').split(/\r?\n/);
  const a = lines.findIndex((l) => l.trim() === '<script>'), b = lines.findIndex((l) => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(HANDLES)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  const $ = (sel) => sandbox.document.querySelector(sel);
  return { sb: sandbox, $, app: () => $('#app').innerHTML, tab: () => $('#tab').innerHTML };
}
const settle = async () => { for (let i = 0; i < 30; i++) await new Promise((r) => setTimeout(r, 0)); };
const FILTERS = { conf: [], region: [], division: [], classYear: [], sort: 'name', view: 'cards', cond: [], moreStats: false };
async function ready(files, html = PAGE) { const pg = loadPage(html, { ...D1_FILES, ...(files || {}) }); await pg.sb.loadIndex(); await settle(); return pg; }
async function list(pg, filters = {}) {
  Object.assign(pg.sb.S.filters, clone(FILTERS), clone(filters));
  pg.sb.S.q = ''; pg.sb.S.qRaw = ''; pg.sb.location.hash = '';
  pg.sb.renderSidebar();
  await pg.sb.renderList();
  return pg.app();
}
async function profile(pg, slug, tab = 'overview') { await pg.sb.renderProfile(slug, tab); return { app: pg.app(), tab: pg.tab() }; }
const subtitle = (html) => (html.match(/<div class="content-subtitle">([\s\S]*?)<\/div>/) || [])[1] || '';
const cardSlugs = (html) => [...html.matchAll(/<div class="card pcard[^"]*" data-slug="([^"]+)"/g)].map((m) => m[1]);
const card = (html, slug) => (html.match(new RegExp(`<div class="card pcard[^"]*" data-slug="${slug}">[\\s\\S]*?<span class="foot-actions">`)) || [])[0] || '';
const tableRow = (html, slug) => (html.match(new RegExp(`<tr class="team-row[^"]*" data-slug="${slug}"[^>]*>([\\s\\S]*?)</tr>`)) || [])[1] || '';
const cells = (rowHtml) => [...rowHtml.matchAll(/<td class="([^"]*)">([\s\S]*?)<\/td>/g)].map((m) => ({ cls: m[1], html: m[2] }));
const tabLabels = (html) => [...html.matchAll(/class="view-tab[^"]*"[^>]*>([^<]*)<\/a>/g)].map((m) => m[1]);
const PROFILE_TABS = ['overview', 'school', 'climate', 'history', 'staff', 'roster', 'commitments', 'schedule', 'news', 'camps'];
const plain = (v) => JSON.parse(JSON.stringify(v));

// ---------- RPI and College Cups: not applicable to Division III ----------

test('NOT_APPLICABLE lists Division III for RPI and College Cups (#246)', () => {
  const pg = loadPage();
  assert.deepEqual(plain(pg.sb.NOT_APPLICABLE), { rpi: ['D2', 'D3'], collegeCups: ['D2', 'D3'] });
});

test('RPI and College Cups are left out for Division III: card, table, profile, glance, History and Compare', async () => {
  const pg = await ready(MIXED_FILES);
  const cards = await list(pg);
  assert.doesNotMatch(card(cards, 'test-d3-full'), /RPI/, 'the Division III card shows an RPI fact');
  assert.ok(card(cards, 'north-carolina').includes(RPI.label), `the Division I card lacks its ${RPI.label} fact`);
  const table = await list(pg, { view: 'table', moreStats: true });
  const cupsIdx = cells(tableRow(table, 'north-carolina')).findIndex((x) => x.html === String(anyRow('north-carolina').collegeCups));
  assert.ok(cupsIdx > 0);
  assert.equal(cells(tableRow(table, 'test-d3-full'))[cupsIdx].html, '', 'the Division III College Cups cell is not empty');
  const o = await profile(pg, 'test-d3-full');
  assert.doesNotMatch(subtitle(o.app), /RPI/);
  assert.doesNotMatch(o.app, /<div class="stat-label">RPI/, 'the glance shows an RPI');
  assert.doesNotMatch(o.app, /<dt>College Cups<\/dt>/, 'the glance shows College Cups');
  assert.doesNotMatch(o.tab, /College Cups|RPI, recent seasons| · RPI #/, 'the overview shows an RPI or College Cups part');
  assert.deepEqual(tabLabels(o.app).filter((l) => /History/.test(l)), ['History']);
  const h = await profile(pg, 'test-d3-full', 'history');
  assert.doesNotMatch(h.tab, /RPI rank by season|<th class="num">RPI<\/th>|<th class="num">Seed<\/th>|<th class="num">KPI<\/th>|<th class="num">Massey<\/th>/);
  assert.doesNotMatch(h.tab, /College Cup \(final four\)/);
  assert.match(h.tab, /<h3>Season by season<\/h3>/, 'the season table itself was dropped');
  pg.sb.S.compare = ['north-carolina', 'test-d3-full']; await pg.sb.renderCompare();
  for (const label of [RPI.label, `RPI ${RPI_SEASON - 1}`, 'Avg RPI, last 5 seasons', 'College Cups']) {
    const m = pg.app().match(new RegExp(`<tr><th>${reEscape(label)}</th><td>[^<]*</td><td>([\\s\\S]*?)</td></tr>`));
    assert.equal(m?.[1], '<span class="muted small">not applicable to Division III</span>', `Compare ${label}`);
  }
});

test('RPI sort: Division III after every Division I program, ranked or unranked, with no missing dash', async () => {
  const pg = await ready(MIXED_FILES);
  const order = cardSlugs(await list(pg, { sort: 'rpi' }));
  assert.deepEqual(order.slice(-3).sort(), ['test-d3-champion', 'test-d3-full', 'test-d3-thin'], `Division III is not last: ${order.slice(-5)}`);
  assert.ok(UNRANKED_D1 && order.indexOf(UNRANKED_D1) < order.indexOf('test-d3-thin'), 'an unranked Division I program sorted after Division III');
  const table = await list(pg, { view: 'table', sort: 'rpi', moreStats: true });
  assert.equal(cells(tableRow(table, 'test-d3-full'))[0].html, '', 'the Division III rank cell is not empty');
});

test('the rpiRank and collegeCups chips exclude Division III as not applicable, never as missing data', async () => {
  const d1 = await ready(), mixed = await ready(MIXED_FILES);
  for (const [cond, chip] of [
    [[{ field: 'rpiRank', op: '<=', value: 50 }], 'RPI'],
    [[{ field: 'collegeCups', op: '>=', value: 1 }], 'College Cups'],
  ]) {
    const a = subtitle(await list(d1, { cond })), b = subtitle(await list(mixed, { cond }));
    const shown = (s) => Number(s.match(/(\d+) of \d+ programs/)[1]);
    assert.equal(shown(b), shown(a), `${chip}: Division III programs passed the chip`);
    assert.ok(b.includes(`3 excluded: ${chip} not applicable to Division III`), `${chip}: ${b}`);
    const hidden = (s) => (s.match(/(\d+) hidden/) || [])[1] || '0';
    assert.equal(hidden(b), hidden(a), `${chip}: Division III was counted as hidden for missing data`);
  }
});

// ---------- titles, with the Division III champions table (#94) ----------

test('titles: TITLE_TABLE_DIVISIONS names the divisions build.py has a champions table for, D3 included (#94)', () => {
  const pg = loadPage();
  const m = fs.readFileSync(path.join(ROOT, 'build.py'), 'utf8').match(/^CHAMPION_TABLES = \{([^}]*)\}/m);
  const tables = [...m[1].matchAll(/"([^"]+)"\s*:/g)].map((x) => x[1]);
  assert.deepEqual(plain(pg.sb.TITLE_TABLE_DIVISIONS), tables);
  assert.ok(tables.includes('D3'), `build.py CHAMPION_TABLES has no D3: ${tables}`);
});

test('titles: a D3 program with no titles shows a real 0 on its profile (#214) and no error; a D3 count reads "3 NCAA D3 titles"', async () => {
  const pg = await ready(MIXED_FILES);
  const cards = await list(pg);
  assert.doesNotMatch(card(cards, 'test-d3-full'), /class="titles"/, 'a card still shows only a count above 0 (#115)');
  assert.match(card(cards, 'test-d3-champion'), /<span class="titles">3 NCAA D3 titles<\/span>/);
  for (const slug of ['test-d3-full', 'test-d3-thin']) {
    const o = await profile(pg, slug);
    assert.doesNotMatch(subtitle(o.app).replace(/<[^>]*>/g, ''), /title/, // the visible text: the division tag's hover attribute is not a title count (#278)
      `${slug}: the subtitle names a title count for a program with none`);
    // #214: D3 has an NCAA champions table (TITLE_TABLE_DIVISIONS), so its zero is a real 0, as the Titles condition
    // already counted it: the profile's titles tile reads 0, never "not collected", and never an error
    assert.match(o.tab, /<div class="label">NCAA D3 titles<\/div><div class="value">0<\/div>/, `${slug}: the titles tile does not read 0`);
    const h = await profile(pg, slug, 'history');
    assert.doesNotMatch(h.tab, /NCAA D3 championships<\/th><td><b>0/, `${slug}: History lists a zero championships row`);
  }
  const c = await profile(pg, 'test-d3-champion');
  assert.match(subtitle(c.app), /3 NCAA D3 titles/);
  const h = await profile(pg, 'test-d3-champion', 'history');
  assert.match(h.tab, /<tr><th>NCAA D3 championships<\/th><td><b>3<\/b>/);
  // the titles chip: with the D3 table (#94) a D3 zero is a known 0, so no D3 program is hidden for missing data
  const sub = subtitle(await list(pg, { cond: [{ field: 'nationalTitles', op: '>=', value: 0 }] }));
  assert.doesNotMatch(sub, /hidden: no national-title count/, sub);
});

// fails if the committed D3 champions lose their titles on the card: the real index, not a fixture (#94)
test('titles: real D3 champions\' cards show their titles from the committed index', async () => {
  const pg = await ready({ 'data/programs/index.json': COMMITTED_INDEX });
  const cards = await list(pg, { division: ['D3'] });
  assert.match(card(cards, 'messiah'), /<span class="titles">6 NCAA D3 titles<\/span>/);
  assert.match(card(cards, 'hobart-william-smith'), /<span class="titles">2 NCAA D3 titles<\/span>/);
  assert.match(card(cards, 'california-lutheran'), /<span class="titles">1 NCAA D3 title<\/span>/);
});

test('titles sort: Division I first, Division III after, never interleaved', async () => {
  const pg = await ready(MIXED_FILES);
  const order = cardSlugs(await list(pg, { sort: 'titles' }));
  // Since #285 programs with no titles ('—') follow every program with any; each run keeps Division I first (#198).
  const titled = new Set(MIXED_INDEX.programs.filter((p) => p.nationalTitles).map((p) => p.slug));
  const split = order.findIndex((s) => !titled.has(s));
  assert.ok(split > 0 && order.slice(split).every((s) => !titled.has(s)), `a program without titles sorted among those with: at ${split}`);
  for (const run of [order.slice(0, split), order.slice(split)]) {
    const firstD3 = run.findIndex((s) => s.startsWith('test-d3-'));
    assert.ok(firstD3 > 0 && run.slice(firstD3).every((s) => s.startsWith('test-d3-')), `Division III interleaved at ${firstD3}`);
  }
  assert.equal(order[split - 1], 'test-d3-champion');
});

// ---------- the scholarship sentence ----------

test('the Division III scholarship sentence shows on D3 only; D1 and D2 keep theirs', async () => {
  const pg = await ready({ ...MIXED_FILES, 'data/programs/index.json': { ...MIXED_INDEX, programs: [...MIXED_INDEX.programs, ...COMMITTED_INDEX.programs.filter((p) => p.division === 'D2')] } });
  for (const slug of ['test-d3-full', 'test-d3-thin']) {
    const s = (await profile(pg, slug, 'school')).tab;
    assert.match(s, /Division III schools award no athletic scholarships \(<a href="https:\/\/www\.ncaa\.org\/eligibility-center\/initial-eligibility-requirements\/division-iii" target="_blank" rel="noopener">NCAA<\/a>\); aid is need- or merit-based, as for any student\./, `${slug}`);
    assert.doesNotMatch(s, /athletic scholarships are separate|equivalencies/, `${slug} shows the D1/D2 line`);
  }
  const d1 = (await profile(pg, 'north-carolina', 'school')).tab;
  assert.match(d1, /athletic scholarships are separate \(D1 women's soccer allows up to 14 equivalencies, program-dependent\)\.<\/p>/);
  assert.doesNotMatch(d1, /Division III/);
  const d2 = (await profile(pg, 'bridgeport', 'school')).tab;
  assert.match(d2, /athletic scholarships are separate\.<\/p>/);
  assert.doesNotMatch(d2, /Division III|equivalencies/);
});

test('the FAQ scholarship line is division-neutral', async () => {
  const pg = await ready();
  await pg.sb.renderFaq();
  assert.match(pg.app(), /depends on financial aid and, outside Division III, athletic scholarships\. Ask the school\./);
});

// ---------- the thin D3 program ----------

test('a thin D3 program (refused host, skipReason) renders every tab and shows no empty athletics section', async () => {
  const pg = await ready(MIXED_FILES);
  const cards = await list(pg);
  assert.ok(card(cards, 'test-d3-thin'), 'the thin program has no card');
  assert.doesNotMatch(card(cards, 'test-d3-thin'), /RPI|undefined|NaN|null/);
  const table = await list(pg, { view: 'table', moreStats: true });
  assert.doesNotMatch(tableRow(table, 'test-d3-thin'), /undefined|NaN|null/);
  const o = await profile(pg, 'test-d3-thin');
  const labels = tabLabels(o.app);
  for (const gone of ['Roster', 'Schedule', 'Staff']) assert.ok(!labels.includes(gone), `the thin profile lists an empty ${gone} tab: ${labels}`);
  assert.ok(labels.includes('School & Location'), `the thin profile lost its school facts: ${labels}`);
  for (const tab of PROFILE_TABS) {
    const r = await profile(pg, 'test-d3-thin', tab);
    assert.doesNotMatch(r.app + r.tab, /undefined|NaN/, `test-d3-thin/${tab}`);
  }
});

// ---------- Division I unchanged ----------

test('D1 profiles render byte for byte the same whether or not Division III is loaded', async () => {
  const d1 = await ready();
  const mixed = await ready(MIXED_FILES);
  for (const slug of ['north-carolina', UNRANKED_D1]) {
    for (const tab of PROFILE_TABS) {
      const a = await profile(d1, slug, tab), b = await profile(mixed, slug, tab);
      assert.equal(b.app, a.app, `${slug}/${tab}: header or glance changed`);
      assert.equal(b.tab, a.tab, `${slug}/${tab}: tab body changed`);
    }
  }
});
