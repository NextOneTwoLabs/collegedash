// Division II on the page (issue #198; owner decisions 2-4 on #197).
//
//     node --test tests/d2_publish_frontend.test.mjs
//
// Same mechanism as tests/ask_page.test.mjs: the inline <script> of public/index.html runs in a `vm` against a
// stub DOM, and fetch is a stub. Two datasets:
//   - D1 ONLY: the committed public/data, exactly what the site publishes today;
//   - MIXED: that same data with Division II programs generated in this file, from real Division I rows and
//     profiles. The generated programs deliberately KEEP an RPI rank, RPI history and a College Cup count, so
//     every "not applicable" check below passes because the division rule hides them, not because the data
//     happens to be empty; and two of them come FIRST in the index, so the sorts are tested on order they
//     have to impose rather than order the index already has.
//
// What this proves:
//   - titles by division: "7 NCAA D2 titles" on the card, profile, glance, tiles, History and Compare; Division I
//     keeps "22 titles" / "22 national titles"; the titles sort never interleaves the divisions;
//   - RPI and College Cups do not apply to Division II: left out of the card, the table ('' not '—'), the profile
//     subtitle, glance, tiles, History (chart, RPI/Seed/KPI/Massey columns, College Cup row, tab label) and
//     Compare ("not applicable"); the rpiRank and collegeCups chips exclude Division II programs and say so as
//     "N excluded: RPI not applicable to Division II", never inside "hidden for missing data"; the RPI sort puts
//     them after every Division I program, ranked or not;
//   - division-neutral copy: meta and og descriptions, the About lead and sources; the 14-equivalencies note on
//     Division I profiles only; no "350" count left in the page head or worker.js;
//   - Division I is unaffected: with D1-only data the Division I strings are the ones the page has always shown,
//     and every tab of a Division I profile renders byte for byte the same whether or not Division II is loaded.
//     With D2PUB_BASELINE_HTML pointing at the page from before this change, every list, table, camps, profile,
//     Compare and sidebar view over the D1-only data is also compared byte for byte (skipped, visibly, when it is
//     not set: CI has no pre-change copy of the page).
//
// D2_PAGE_HTML and D2_WORKER_JS (optional) point at other copies of index.html and worker.js, so a deliberately
// broken copy can be shown failing through these same checks.
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
const PAGE = process.env.D2_PAGE_HTML || path.join(PUBLIC, 'index.html');
const readJson = (rel) => JSON.parse(fs.readFileSync(path.join(PUBLIC, rel), 'utf8'));
const clone = (v) => JSON.parse(JSON.stringify(v));

// ---------- data ----------
// The D1 ONLY dataset is the committed index's Division I rows. Before #197 that was the whole index; since
// D2 is published the committed index also holds the real Division II rows, which would otherwise be mixed
// into every "D1 only" view and into MIXED beside the generated programs below.
const COMMITTED_INDEX = readJson('data/programs/index.json');
const REAL_INDEX = { ...COMMITTED_INDEX, programs: COMMITTED_INDEX.programs.filter((p) => p.division === 'D1') };
const D1_FILES = { 'data/programs/index.json': REAL_INDEX };
const row = (slug) => { const r = REAL_INDEX.programs.find((p) => p.slug === slug); assert.ok(r, `no ${slug} in the index`); return r; };
// The RPI season is read from the index, not hardcoded (issue #62): the latest ranked season, in progress while it is played.
const RPI = expectedRpi(REAL_INDEX), RPI_SEASON = RPI.season;
const rpiOfRow = expectedRpiOf(REAL_INDEX);
const UNRANKED_D1 = REAL_INDEX.programs.find((p) => p.division === 'D1' && rpiOfRow(p) == null)?.slug;
const TITLE_YEARS_D2 = [2009, 2010, 2013, 2015, 2016, 2019, 2021];

function d2Row(base, slug, name, titles) {
  const r = clone(row(base));
  Object.assign(r, { slug, name, shortName: name, nickname: 'Testers', division: 'D2', conference: 'Test Division II Conference',
    nationalTitles: titles });
  assert.ok(rpiOfRow(r) != null, `${base} has no ${RPI_SEASON} RPI to keep`);
  assert.ok(r.collegeCups > 0 || base !== 'north-carolina', 'the champion copy must keep a College Cup count');
  return r;
}
const D2_CHAMP = d2Row('north-carolina', 'test-d2-champion', 'Test D2 Champion', 7);
const D2_PLAIN = d2Row('stanford', 'test-d2-plain', 'Test D2 Plain', 0);
// Division II first in the index: a sort that leaves ties in index order would put them first.
const MIXED_INDEX = { ...clone(REAL_INDEX), programs: [D2_PLAIN, D2_CHAMP, ...clone(REAL_INDEX.programs)] };

function d2Profile(base, r, titleYears) {
  const p = clone(readJson(`data/programs/${base}.json`));
  Object.assign(p, { slug: r.slug, name: r.name, shortName: r.shortName, nickname: r.nickname, division: 'D2', conference: r.conference });
  p.program.nationalTitles = titleYears;
  assert.ok((p.seasons || []).some((s) => s.rpiRank), `${base}'s profile has no RPI history to keep`);
  assert.ok((p.program.collegeCups || []).length > 0, `${base}'s profile has no College Cups to keep`);
  return p;
}
const MIXED_FILES = {
  'data/programs/index.json': MIXED_INDEX,
  'data/programs/test-d2-champion.json': d2Profile('north-carolina', D2_CHAMP, TITLE_YEARS_D2),
  'data/programs/test-d2-plain.json': d2Profile('stanford', D2_PLAIN, []),
};

// ---------- the page ----------
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
const HANDLES = ['S', 'renderList', 'renderSidebar', 'renderCamps', 'renderProfile', 'renderCompare', 'renderFaq', 'loadIndex', 'condNaTally', 'condNaText', 'condTally'];

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
  return { sb: sandbox, $, app: () => $('#app').innerHTML, tab: () => $('#tab').innerHTML, sidebar: () => $('#sidebar').innerHTML, head: lines.slice(0, a).join('\n') };
}
const settle = async () => { for (let i = 0; i < 30; i++) await new Promise((r) => setTimeout(r, 0)); };
const FILTERS = { conf: [], region: [], division: [], classYear: [], sort: 'name', view: 'cards', cond: [], moreStats: false };
async function ready(files) { const pg = loadPage(PAGE, { ...D1_FILES, ...(files || {}) }); await pg.sb.loadIndex(); await settle(); return pg; }
async function list(pg, filters = {}) {
  Object.assign(pg.sb.S.filters, clone(FILTERS), clone(filters));
  pg.sb.S.q = ''; pg.sb.S.qRaw = ''; pg.sb.location.hash = '';
  pg.sb.renderSidebar();
  await pg.sb.renderList();
  return pg.app();
}
async function profile(pg, slug, tab = 'overview') { await pg.sb.renderProfile(slug, tab); return { app: pg.app(), tab: pg.tab() }; }
const subtitle = (html) => (html.match(/<div class="content-subtitle">([\s\S]*?)<\/div>/) || [])[1] || '';
const text = (html) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
const cardSlugs = (html) => [...html.matchAll(/<div class="card pcard[^"]*" data-slug="([^"]+)"/g)].map((m) => m[1]);
const card = (html, slug) => (html.match(new RegExp(`<div class="card pcard[^"]*" data-slug="${slug}">[\\s\\S]*?<span class="foot-actions">`)) || [])[0] || '';
const tableRow = (html, slug) => (html.match(new RegExp(`<tr class="team-row[^"]*" data-slug="${slug}"[^>]*>([\\s\\S]*?)</tr>`)) || [])[1] || '';
const cells = (rowHtml) => [...rowHtml.matchAll(/<td class="([^"]*)">([\s\S]*?)<\/td>/g)].map((m) => ({ cls: m[1], html: m[2] }));
const tabLabels = (html) => [...html.matchAll(/class="view-tab[^"]*"[^>]*>([^<]*)<\/a>/g)].map((m) => m[1]);
const PROFILE_TABS = ['overview', 'school', 'climate', 'history', 'staff', 'roster', 'commitments', 'schedule', 'news', 'camps'];

// ---------- Division I, as it has always been ----------

test('D1 only: titles, RPI, College Cups and the equivalencies note read exactly as before', async () => {
  const pg = await ready();
  const cards = await list(pg);
  assert.match(card(cards, 'north-carolina'), /<span class="titles">22 titles<\/span>/);
  const table = await list(pg, { view: 'table', sort: 'rpi', moreStats: true });
  assert.ok(UNRANKED_D1, 'the index has no unranked Division I program to check');
  const unranked = cells(tableRow(table, UNRANKED_D1));
  assert.equal(unranked[0].html, '<span class="rank-num">—</span>', 'an unranked Division I program no longer shows the missing dash');
  assert.equal(cells(tableRow(table, 'north-carolina')).find((c) => c.cls === 'num col-extra' && /^\d+$/.test(c.html) && c.html !== '22')?.html, String(row('north-carolina').collegeCups));
  assert.doesNotMatch(table, /shown for Division I only/, 'a Division I-only table grew a division footnote');
  const rpiCond = await list(pg, { cond: [{ field: 'rpiRank', op: '<=', value: 50 }] });
  assert.doesNotMatch(subtitle(rpiCond), /excluded/, 'a Division I-only list says something was excluded');
  const nc = await profile(pg, 'north-carolina');
  assert.match(subtitle(nc.app), /22 national titles/);
  assert.ok(tabLabels(nc.app).includes('History & RPI'));
  assert.match(nc.tab, /<div class="label">National titles<\/div>/);
  const hist = await profile(pg, 'north-carolina', 'history');
  assert.match(hist.tab, /<th class="num">RPI<\/th><th class="num">Seed<\/th><th class="num">KPI<\/th><th class="num">Massey<\/th>/);
  assert.match(hist.tab, /<tr><th>NCAA championships<\/th>/);
  assert.match(hist.tab, /<tr><th>College Cup \(final four\)<\/th>/);
  const school = await profile(pg, 'north-carolina', 'school');
  assert.match(school.tab, /athletic scholarships are separate \(D1 women's soccer allows up to 14 equivalencies, program-dependent\)\./);
});

test('D1 profiles render byte for byte the same whether or not Division II is loaded', async () => {
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

const BASELINE = process.env.D2PUB_BASELINE_HTML;
test('D1 only: every view is byte-identical to the page before #198, apart from the division-neutral copy', { skip: BASELINE ? false : 'set D2PUB_BASELINE_HTML to the pre-change public/index.html to run this comparison' }, async () => {
  const views = async (html) => {
    const pg = loadPage(html, D1_FILES); await pg.sb.loadIndex(); await settle();
    const out = {};
    const cases = { default: {}, rpi: { sort: 'rpi' }, titles: { sort: 'titles' }, table: { view: 'table', sort: 'rpi', moreStats: true },
      condRpi: { cond: [{ field: 'rpiRank', op: '<=', value: 50 }] }, condCups: { view: 'table', cond: [{ field: 'collegeCups', op: '>=', value: 1 }, { field: 'sat25', op: '>', value: 1000 }] },
      condTitles: { cond: [{ field: 'nationalTitles', op: '>=', value: 1 }] } };
    for (const [k, f] of Object.entries(cases)) { out[`list:${k}`] = await list(pg, f); out[`sidebar:${k}`] = pg.sidebar(); }
    Object.assign(pg.sb.S.filters, clone(FILTERS), { cond: [{ field: 'rpiRank', op: '<=', value: 50 }] });
    await pg.sb.renderCamps(); out.camps = pg.app();
    for (const slug of ['north-carolina', 'stanford', UNRANKED_D1]) for (const tab of PROFILE_TABS) { const r = await profile(pg, slug, tab); out[`${slug}/${tab}`] = r.app + r.tab; }
    pg.sb.S.compare = ['north-carolina', 'stanford', UNRANKED_D1]; await pg.sb.renderCompare(); out.compare = pg.app();
    return out;
  };
  const before = await views(BASELINE), now = await views(PAGE);
  for (const k of Object.keys(before)) assert.equal(now[k], before[k], `${k} differs from the page before #198`);
});

// ---------- Division II ----------

test('titles by division: "7 NCAA D2 titles" on the card, table, profile, glance, History and Compare', async () => {
  const pg = await ready(MIXED_FILES);
  assert.match(card(await list(pg), 'test-d2-champion'), /<span class="titles">7 NCAA D2 titles<\/span>/);
  assert.match(card(await list(pg), 'north-carolina'), /<span class="titles">22 titles<\/span>/, 'Division I lost its wording');
  const table = await list(pg, { view: 'table', moreStats: true });
  assert.ok(cells(tableRow(table, 'test-d2-champion')).some((c) => c.html === '<span title="7 NCAA D2 titles">7 D2</span>'), 'the table titles cell does not name the division');
  const o = await profile(pg, 'test-d2-champion');
  assert.match(subtitle(o.app), /7 NCAA D2 titles/);
  assert.doesNotMatch(subtitle(o.app), /national title/);
  assert.match(o.tab, /<div class="label">NCAA D2 titles<\/div><div class="value">7<\/div>/);
  assert.doesNotMatch(o.tab, /<div class="label">National titles<\/div>/);
  assert.match(o.app, /<div class="stat-sub">7 NCAA D2 titles<\/div>|<div class="stat-label">NCAA D2 titles<\/div>/, 'the glance titles figure does not name the division');
  const h = await profile(pg, 'test-d2-champion', 'history');
  assert.match(h.tab, /<tr><th>NCAA D2 championships<\/th><td><b>7<\/b>/);
  pg.sb.S.compare = ['north-carolina', 'test-d2-champion']; await pg.sb.renderCompare();
  assert.match(pg.app(), /<tr><th>National titles<\/th><td>22<\/td><td>7 <span class="muted small">NCAA D2<\/span><\/td><\/tr>/);
});

test('titles sort: Division I counts first, then Division II, never interleaved', async () => {
  const pg = await ready(MIXED_FILES);
  const order = cardSlugs(await list(pg, { sort: 'titles' }));
  const division = new Map(MIXED_INDEX.programs.map((p) => [p.slug, p.division]));
  // Since #285 a program with no titles ('—') sorts after every program with any, so the list is two runs -
  // with titles, then without - and each run keeps Division I before Division II, never interleaved (#198).
  const titled = new Set(MIXED_INDEX.programs.filter((p) => p.nationalTitles).map((p) => p.slug));
  const split = order.findIndex((s) => !titled.has(s));
  assert.ok(split > 0 && order.slice(split).every((s) => !titled.has(s)), `a program without titles sorted among those with: at ${split}`);
  for (const run of [order.slice(0, split), order.slice(split)]) {
    const firstD2 = run.findIndex((s) => division.get(s) === 'D2');
    assert.ok(firstD2 > 0 && run.slice(firstD2).every((s) => division.get(s) === 'D2'), `a Division II program sorted among Division I: first D2 at ${firstD2} of ${run.length}`);
  }
  assert.equal(order[split - 1], 'test-d2-champion', 'Division II with 7 titles is not the last program with titles');
  assert.equal(order.at(-1), 'test-d2-plain', 'Division II with 0 titles is not last');
  assert.equal(order[0], 'north-carolina');
});

test('RPI sort: Division II after every Division I program, ranked or unranked, and shown without a missing dash', async () => {
  const pg = await ready(MIXED_FILES);
  const order = cardSlugs(await list(pg, { sort: 'rpi' }));
  assert.deepEqual(order.slice(-2).sort(), ['test-d2-champion', 'test-d2-plain'], `Division II is not last: ${order.slice(-4)}`);
  assert.ok(order.indexOf(UNRANKED_D1) < order.indexOf('test-d2-plain'), 'an unranked Division I program sorted after Division II');
  const table = await list(pg, { view: 'table', sort: 'rpi', moreStats: true });
  const c = cells(tableRow(table, 'test-d2-champion'));
  assert.equal(c[0].html, '', `the rank cell for Division II is ${JSON.stringify(c[0].html)}, not empty`);
  assert.equal(cells(tableRow(table, UNRANKED_D1))[0].html, '<span class="rank-num">—</span>');
  assert.match(table, /RPI and College Cups are shown for Division I only/);
});

test('RPI and College Cups are left out for Division II: card, table, profile, glance, tiles, History and Compare', async () => {
  const pg = await ready(MIXED_FILES);
  const cards = await list(pg);
  assert.doesNotMatch(card(cards, 'test-d2-champion'), /RPI/, 'the Division II card shows an RPI fact');
  assert.ok(card(cards, 'north-carolina').includes(RPI.label), `the Division I card lacks its ${RPI.label} fact`);
  const table = await list(pg, { view: 'table', moreStats: true });
  const champ = cells(tableRow(table, 'test-d2-champion'));
  const cupsIdx = cells(tableRow(table, 'north-carolina')).findIndex((x) => x.html === String(row('north-carolina').collegeCups));
  assert.ok(cupsIdx > 0);
  assert.equal(champ[cupsIdx].html, '', 'the Division II College Cups cell is not empty');
  const o = await profile(pg, 'test-d2-champion');
  assert.doesNotMatch(subtitle(o.app), /RPI/);
  assert.doesNotMatch(o.app, /<div class="stat-label">RPI/, 'the glance shows an RPI');
  assert.doesNotMatch(o.app, /<dt>College Cups<\/dt>/, 'the glance shows College Cups');
  assert.doesNotMatch(o.tab, /College Cups|RPI, recent seasons| · RPI #/, 'the overview shows an RPI or College Cups part');
  assert.deepEqual(tabLabels(o.app).filter((l) => /History/.test(l)), ['History']);
  const h = await profile(pg, 'test-d2-champion', 'history');
  assert.doesNotMatch(h.tab, /RPI rank by season|<th class="num">RPI<\/th>|<th class="num">Seed<\/th>|<th class="num">KPI<\/th>|<th class="num">Massey<\/th>/);
  assert.doesNotMatch(h.tab, /College Cup \(final four\)/);
  assert.match(h.tab, /<h3>Season by season<\/h3>/, 'the season table itself was dropped');
  pg.sb.S.compare = ['north-carolina', 'test-d2-champion']; await pg.sb.renderCompare();
  for (const label of [RPI.label, `RPI ${RPI_SEASON - 1}`, 'Avg RPI, last 5 seasons', 'College Cups']) {
    const m = pg.app().match(new RegExp(`<tr><th>${reEscape(label)}</th><td>[^<]*</td><td>([\\s\\S]*?)</td></tr>`));
    assert.equal(m?.[1], '<span class="muted small">not applicable to Division II</span>', `Compare ${label}`);
  }
});

test('the rpiRank and collegeCups chips exclude Division II as not applicable, never as missing data', async () => {
  const d1 = await ready(), mixed = await ready(MIXED_FILES);
  for (const [cond, chip, n] of [
    [[{ field: 'rpiRank', op: '<=', value: 50 }], 'RPI', 2],
    [[{ field: 'collegeCups', op: '>=', value: 1 }], 'College Cups', 2],
    [[{ field: 'rpiRank', op: '<=', value: 100 }, { field: 'collegeCups', op: '>=', value: 0 }], 'RPI and College Cups', 2],
  ]) {
    const a = subtitle(await list(d1, { cond })), b = subtitle(await list(mixed, { cond }));
    const shown = (s) => Number(s.match(/(\d+) of \d+ programs/)[1]);
    assert.equal(shown(b), shown(a), `${chip}: Division II programs passed the chip`);
    assert.ok(b.includes(`${n} excluded: ${chip} not applicable to Division II`), `${chip}: ${b}`);
    const hidden = (s) => (s.match(/(\d+) hidden/) || [])[1] || '0';
    assert.equal(hidden(b), hidden(a), `${chip}: Division II was counted as hidden for missing data`);
  }
  // a chip that applies to Division II counts it as before
  const titles = subtitle(await list(mixed, { cond: [{ field: 'nationalTitles', op: '>=', value: 1 }] }));
  assert.doesNotMatch(titles, /excluded/);
  // the ID Camp View's unit
  const { condNaTally, condNaText } = mixed.sb;
  const conds = [{ field: 'rpiRank', op: '<=', value: 50 }];
  const camps = [{ slug: 'test-d2-champion' }, { slug: 'test-d2-champion' }, { slug: 'north-carolina' }];
  const byProgram = new Map(MIXED_INDEX.programs.map((p) => [p.slug, p]));
  assert.equal(condNaText(condNaTally(camps, conds, (c) => byProgram.get(c.slug)), conds, 'camp'), '2 camps excluded: RPI not applicable to Division II');
});

// ---------- division-neutral copy ----------

test('copy: the meta, og and About text say NCAA women\'s soccer, and no "350" count is left', async () => {
  const pg = loadPage();
  const desc = (pg.head.match(/<meta name="description" content="([^"]*)"/) || [])[1];
  const og = (pg.head.match(/<meta property="og:description" content="([^"]*)"/) || [])[1];
  assert.equal(desc, "A research dashboard for NCAA women's soccer: program profiles built from public sources — school, roster, schedule, RPI and commitments.");
  assert.equal(og, desc);
  await pg.sb.loadIndex(); await settle();
  await pg.sb.renderFaq();
  assert.match(pg.app(), /public information about NCAA women’s soccer programs into one place/);
  assert.doesNotMatch(pg.app(), /Division I women’s soccer programs/);
  assert.match(text(pg.app()), /Division I only\. Weekly RPI during the season/);
  assert.match(text(pg.app()), /checked against each division’s NCAA champions list/);
  assert.doesNotMatch(pg.head, /\b350\b/);
  assert.doesNotMatch(fs.readFileSync(process.env.D2_WORKER_JS || path.join(ROOT, 'worker.js'), 'utf8'), /\b350 program/);
  const mixed = await ready(MIXED_FILES);
  const school = await profile(mixed, 'test-d2-champion', 'school');
  assert.match(school.tab, /athletic scholarships are separate\.<\/p>/);
  assert.doesNotMatch(school.tab, /equivalencies/, 'the Division I equivalencies note shows on a Division II profile');
});
