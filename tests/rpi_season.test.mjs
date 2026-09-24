// Issue #62: which RPI season the page shows, and how it says so.
//
//   node --test tests/rpi_season.test.mjs
//
// The page used to hardcode `const RPI_SEASON = 2025`, so the NCAA's first 2026 table left it showing last
// season's ranks under a label that implied they were current. It now reads the season from the published
// index, and the owner's decision on #62 (2026-09-23) is the rule these checks pin, with literal years so the
// rule cannot drift together with a helper:
//   * rank, filter and sort use the latest season any program is ranked in - the live table included;
//   * while that season is the one being played (index.season.current) it is labelled "in progress"
//     wherever its rank is shown: card, sort, condition field, table footnote, profile header, glance, compare;
//   * "Record" and the other last-season figures stay on the last FINISHED season, and an in-progress season
//     never counts as one - until the registry moves on, when the build reads that season's final snapshot;
//   * a division RPI does not apply to (D2) still shows none.
// The page's inline script runs in a vm against a stub DOM and an in-memory index, as rpi_not_served does.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { expectedRpi } from './rpi_season_helpers.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.RPI_SEASON_TEST_HTML || path.join(PUBLIC, 'index.html');

function loadPage(files) {
  const lines = fs.readFileSync(HTML, 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>');
  const b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'index.html: could not find the inline <script>');
  const src = lines.slice(a + 1, b).join('\n')
    + '\n;Object.assign(globalThis, { S, loadIndex, rpiSeason, rpiInProgress, finishedSeason, rpiOf, cardHtml, tableHtml, sortLabel, COND_FIELDS, glanceHtml, renderProfile, renderCompare, renderList });\n';
  const els = new Map();
  const el = name => ({
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, dataset: {}, style: {},
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => el('child'), querySelectorAll: () => [], closest: () => null, matches: () => false, focus() { }, contains: () => false,
  });
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: {
      documentElement: el('html'), body: el('body'), addEventListener() { }, createElement: el, querySelectorAll: () => [],
      querySelector: s => { if (!els.has(s)) els.set(s, el(s)); return els.get(s); },
    },
    location: { hash: '', replace(h) { this.hash = h; } }, history: { replaceState() { } },
    matchMedia: () => ({ matches: false }), innerWidth: 1400, addEventListener() { },
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    fetch: async url => {
      const body = files[url.replace(/^\//, '')];
      return body === undefined ? { ok: false, status: 404, async json() { throw new Error('404'); } }
        : { ok: true, status: 200, async json() { return JSON.parse(JSON.stringify(body)); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, app: () => sandbox.document.querySelector('#app').innerHTML };
}

// ---------- fixtures: two D1 programs and one D2 one, over three points in the RPI calendar ----------
const row = (slug, division, ranks, last) => ({
  slug, name: `${slug} University`, shortName: slug, nickname: null, searchNames: [slug], conference: 'Test Conference', division,
  colors: null, city: 'Town', state: 'CA', region: 'West', ownership: 'Public', undergradEnrollment: 1000, admissionRate: 0.5,
  sat25: null, sat75: null, academicRank: null, academicRankTied: false, tuitionInState: 1, tuitionOutOfState: 2,
  headCoach: null, coachSince: null, nationalTitles: 0, collegeCups: 0,
  currentSeason: ranks.cur ? { year: ranks.cur[0], record: '5-2-1', rpiRank: ranks.cur[1] } : null,
  lastSeason: last, rpiHistory: division === 'D1' ? ranks.hist.map(([year, rank]) => ({ year, rank })) : [],
  rosterSize: null, commitmentsByYear: {}, fallClimate: null, completeness: 0.5, stale: [], builtAt: '2026-09-23T00:00:00Z', failed: [], tags: [],
});
const seasonsOf = (ranks, division) => [
  ...(ranks.cur ? [{ year: ranks.cur[0], label: String(ranks.cur[0]), record: '5-2-1', inProgress: true,
    ...(division === 'D1' ? { rpiRank: ranks.cur[1], rpi: { rank: ranks.cur[1], through: '2026-09-21', source: 'NCAA.com weekly RPI' } } : {}) }] : []),
  ...ranks.hist.filter(([y]) => !ranks.cur || y !== ranks.cur[0]).map(([year, rank]) => ({ year, label: String(year), record: '18-4-2',
    ...(division === 'D1' ? { rpiRank: rank, rpi: { rank } } : {}) })),
];
const profileOf = (r, ranks) => ({
  slug: r.slug, name: r.name, shortName: r.shortName, nickname: null, conference: r.conference, division: r.division,
  school: { city: 'Town', state: 'CA' }, program: { headCoach: {}, nationalTitles: [], collegeCups: [], _meta: {} },
  links: {}, seasons: seasonsOf(ranks, r.division), roster: null, rosterHistory: {}, schedule: null, commitments: [], news: null,
  camps: null, curated: {}, commitmentsByYear: {},
  _build: { builtAt: '2026-09-23T00:00:00Z', completeness: 0.5, sections: {}, stale: [], failed: [], skipped: [] },
});
// Where the NCAA table stands, as build.py publishes it: `current` is registry.season.current.
const CALENDAR = {
  // 2026-09-23: the NCAA's first 2026 table is out; 2025 is the last finished season (the owner's decision on #62)
  live: { current: 2026, a: { cur: [2026, 3], hist: [[2026, 3], [2025, 8], [2024, 11]] }, b: { cur: [2026, 40], hist: [[2026, 40], [2025, 2]] },
    expect: { season: 2026, inProgress: true, finished: 2025, label: 'RPI 2026 (in progress)' } },
  // the summer before: registry already on 2026, no 2026 table yet - 2025 is both the shown and the finished season
  before: { current: 2026, a: { cur: null, hist: [[2025, 8], [2024, 11]] }, b: { cur: null, hist: [[2025, 2]] },
    expect: { season: 2025, inProgress: false, finished: 2025, label: 'RPI 2025' } },
  // after the registry moves to 2027: 2026's final snapshot stands, and nothing is in progress
  final: { current: 2027, a: { cur: null, hist: [[2026, 4], [2025, 8]] }, b: { cur: null, hist: [[2026, 41], [2025, 2]] },
    expect: { season: 2026, inProgress: false, finished: 2026, label: 'RPI 2026' } },
  // issue #249: the NCAA's table through the College Cup final is out while the registry is still on 2026 -
  // the build publishes season.finished and season.rpiFinal, and 2026 is over on the page the same day
  rpiFinal: { current: 2026, extra: { finished: 2026, rpiFinal: { season: 2026, through: '2026-12-14' } },
    a: { cur: null, hist: [[2026, 4], [2025, 8]] }, b: { cur: null, hist: [[2026, 41], [2025, 2]] },
    expect: { season: 2026, inProgress: false, finished: 2026, label: 'RPI 2026' } },
};
function filesFor(stage) {
  const c = CALENDAR[stage];
  const lastOf = ranks => { const s = seasonsOf(ranks, 'D1').find(x => !x.inProgress); return { year: s.year, record: s.record, rpiRank: s.rpiRank, ncaaResult: null }; };
  const rows = [row('alpha', 'D1', c.a, lastOf(c.a)), row('beta', 'D1', c.b, lastOf(c.b)), row('gamma', 'D2', c.a, lastOf(c.a))];
  const files = { 'api/v1/programs': { updated: '2026-09-23T00:00:00Z', season: { current: c.current, ...c.extra }, programs: rows } };
  for (const [r, ranks] of [[rows[0], c.a], [rows[1], c.b], [rows[2], c.a]]) files[`api/v1/programs/${r.slug}`] = profileOf(r, ranks);
  return files;
}
async function ready(stage) {
  const pg = loadPage(filesFor(stage));
  await pg.sb.loadIndex();
  return pg;
}
const byLabel = (html, label) => html.includes(`<div class="label">${label}</div>`);

test('the season is read from the index at each point of the RPI calendar, not hardcoded', async () => {
  for (const [stage, { expect }] of Object.entries(CALENDAR)) {
    const { sb } = await ready(stage);
    assert.deepEqual({ season: sb.rpiSeason(), inProgress: sb.rpiInProgress(), finished: sb.finishedSeason(), label: sb.sortLabel('rpi') },
      expect, `${stage}: the page's RPI season`);
    // the helper the other suites use agrees with these literal years, so it cannot drift with the page
    assert.deepEqual(expectedRpi(sb.S.index), expect, `${stage}: tests/rpi_season_helpers.mjs`);
  }
  assert.doesNotMatch(fs.readFileSync(HTML, 'utf8'), /const RPI_SEASON\s*=/, 'the hardcoded season is back');
});

test('an in-progress season is never the finished season: Record and last-season figures stay on 2025', async () => {
  const { sb, app } = await ready('live');
  assert.ok(sb.rpiInProgress() && sb.finishedSeason() < sb.rpiSeason(), 'the live season counted as finished');
  const alpha = sb.S.index.programs.find(p => p.slug === 'alpha');
  const table = sb.tableHtml(sb.S.index.programs);
  assert.match(table, /<th[^>]*>(?:<button[^>]*>)?Record 2025(?:<\/button>)?<\/th>/, 'the Record column is not the finished season');
  assert.doesNotMatch(table, /Record 2026/);
  assert.match(sb.tableHtml([alpha]), /<span class="num-strong">18-4-2<\/span>/, 'the Record cell is not the finished season\'s record');
  assert.match(table, /RPI is the 2026 season, in progress[^<]*· Record is the 2025 season/, 'the footnote does not say which is which');
  await sb.renderProfile('alpha');
  // Compare's finished-season row is 2025's record, and the in-progress record is only under "Current record"
  sb.S.compare = ['alpha', 'beta']; await sb.renderCompare();
  assert.match(app(), /<tr><th>2025 record<\/th><td>18-4-2<\/td>/);
  assert.doesNotMatch(app(), /<tr><th>2026 record<\/th>/);
  assert.equal(sb.rpiOf(alpha), 3, 'the rank is not the live 2026 one');
});

test('wherever the live rank is shown, it says "in progress"', async () => {
  const { sb, app } = await ready('live');
  const [alpha] = sb.S.index.programs;
  assert.ok(byLabel(sb.cardHtml(alpha), 'RPI 2026 (in progress)'), 'card');
  assert.match(sb.cardHtml(alpha), /RPI 2026 \(in progress\)<\/div><div class="value">#3</);
  assert.equal(sb.COND_FIELDS.find(d => d.key === 'rpiRank').label, 'RPI 2026 (in progress)', 'condition field');
  assert.equal(sb.COND_FIELDS.find(d => d.key === 'rpiRank').missing, 'no 2026 RPI');
  // sort: by the live rank, and named as such in the list's own subtitle
  sb.S.filters.sort = 'rpi'; sb.location.hash = '#/'; await sb.renderList();
  assert.ok(app().includes('sorted by RPI 2026 (in progress)'), 'list subtitle');
  const sorted = [...sb.S.index.programs].filter(p => p.division === 'D1').sort((a, b) => sb.rpiOf(a) - sb.rpiOf(b)).map(p => p.slug);
  assert.deepEqual(sorted, ['alpha', 'beta'], 'alpha #3 is ahead of beta #40 on the live table, though beta was #2 in 2025');
  await sb.renderProfile('alpha');
  assert.match(app(), /RPI 2026 <b>#3<\/b> \(in progress\)/, 'profile header');
  assert.match(app(), /<div class="stat-label">RPI 2026<\/div><div class="stat-value">#3<\/div><div class="stat-sub">in progress · through /, 'glance');
  sb.S.compare = ['alpha', 'beta']; await sb.renderCompare();
  assert.match(app(), /<tr><th>RPI 2026 \(in progress\)<\/th><td>#3<\/td><td>#40<\/td><\/tr>/, 'compare');
  assert.match(app(), /<tr><th>RPI 2025<\/th><td>#8<\/td><td>#2<\/td><\/tr>/, 'compare, the finished season');
});

test('a finished season carries no "in progress" label anywhere', async () => {
  for (const stage of ['before', 'final', 'rpiFinal']) {
    const { sb, app } = await ready(stage);
    const y = CALENDAR[stage].expect.season;
    const alpha = sb.S.index.programs[0];
    assert.ok(byLabel(sb.cardHtml(alpha), `RPI ${y}`), `${stage}: card`);
    assert.match(sb.tableHtml(sb.S.index.programs), new RegExp(`RPI and record are the ${y} season`), `${stage}: footnote`);
    await sb.renderProfile('alpha');
    assert.doesNotMatch(app(), /in progress/, `${stage}: profile`);
    sb.S.compare = ['alpha', 'beta']; await sb.renderCompare();
    assert.doesNotMatch(app(), /in progress/, `${stage}: compare`);
  }
});

test('Division II still shows RPI as not applicable while the live season is in progress', async () => {
  const { sb, app } = await ready('live');
  const gamma = sb.S.index.programs.find(p => p.slug === 'gamma');
  assert.doesNotMatch(sb.cardHtml(gamma), /RPI/, 'the D2 card shows an RPI fact');
  await sb.renderProfile('gamma');
  assert.doesNotMatch(app(), /RPI 2026|stat-label">RPI/, 'the D2 profile shows an RPI');
  sb.S.compare = ['alpha', 'gamma']; await sb.renderCompare();
  const m = app().match(/<tr><th>RPI 2026 \(in progress\)<\/th><td>[^<]*<\/td><td>([\s\S]*?)<\/td><\/tr>/);
  assert.equal(m?.[1], '<span class="muted small">not applicable to Division II</span>');
});
