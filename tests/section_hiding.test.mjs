// Tests for per-program section hiding on cards, the table and the program profile (issue #115).
//
//     node --test tests/section_hiding.test.mjs
//
// Same mechanism as tests/camps_view.test.mjs: the inline <script> is pulled out of public/index.html and run
// in a `vm` against a stub DOM, so what runs is the real source text of the real file.
//
// The owner's rule (#94): a section appears only when THAT program has data for it. The expectations below
// are written from the data shape, independently of the page's own `has` rules, and every section is checked
// in both directions: shown when its data exists, absent when it does not. That is done for every published
// program in the committed index and profiles (all of D1 today), and for synthetic D2 programs with almost
// nothing, including the per-program cases the rule exists for (a D2 program with commitments) and the
// informative absences of #44 (a camps collection that was skipped or failed).
//
// What it CANNOT prove, and a human must check in a browser: layout when a card has fewer facts, a profile
// with two tabs at phone width, and that the rewritten address after a link to a hidden tab behaves in the
// back button. The DOM here is a stub that records innerHTML and swallows everything else.
//
// SECTION_TEST_HTML (optional) points the suite at another copy of index.html. It exists so a deliberately
// broken copy can be run through these same checks to show each of them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { expectedRpi } from './rpi_season_helpers.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.SECTION_TEST_HTML || path.join(PUBLIC, 'index.html');
// The RPI season is read from the index, not hardcoded (issue #62): the latest ranked season, labelled in progress while
// it is being played; the Record column is the last finished season, which an in-progress season never is.
const RPI = expectedRpi(JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data/programs/index.json'), 'utf8')));
const RPI_SEASON = RPI.season;

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

function loadPage(overrides = {}) {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
  const replaced = [];
  const readPublic = url => {
    let rel = url.replace(/^\//, '');
    if (rel.startsWith('api/v1/')) {
      const sub = rel.slice('api/v1/'.length);
      if (sub === 'programs') rel = 'data/programs/index.json';
      else if (sub.startsWith('programs/')) rel = `data/programs/${sub.slice('programs/'.length)}.json`;
      else if (sub === 'camps') rel = 'data/camps/index.json';
      else if (sub === 'trends') rel = 'data/trends/index.json';
      else if (sub === 'commitments') rel = 'data/commitments/index.json';
      else if (sub === 'status') rel = 'archive/refresh-state.json';
    }
    const p = path.join(PUBLIC, rel);
    return p.startsWith(PUBLIC) && fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector,
      querySelectorAll: () => [], addEventListener() { }, createElement: makeElement },
    location: { hash: '', replace(h) { this.hash = h; } },
    history: { replaceState(_s, _t, url) { replaced.push(url); sandbox.location.hash = url; } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) },
    innerWidth: 1400, addEventListener() { },
    fetch: async url => {
      let u = String(url);
      if (Object.prototype.hasOwnProperty.call(overrides, u)) {
        const doc = overrides[u];
        return { ok: true, status: 200, async json() { return JSON.parse(JSON.stringify(doc)); } };
      }
      if (u.startsWith('/api/v1/')) {
        const sub = u.slice('/api/v1/'.length);
        if (sub === 'programs') u = 'data/programs/index.json';
        else if (sub.startsWith('programs/')) u = `data/programs/${sub.slice('programs/'.length)}.json`;
        else if (sub === 'camps') u = 'data/camps/index.json';
        else if (sub === 'trends') u = 'data/trends/index.json';
        else if (sub === 'commitments') u = 'data/commitments/index.json';
        else if (sub === 'status') u = 'archive/refresh-state.json';
      }
      if (Object.prototype.hasOwnProperty.call(overrides, u)) {
        const doc = overrides[u];
        return { ok: true, status: 200, async json() { return JSON.parse(JSON.stringify(doc)); } };
      }
      const body = readPublic(u);
      if (body == null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(HTML, 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'public/index.html: could not find the inline <script>');
  const src = lines.slice(a + 1, b).join('\n')
    + '\n;Object.assign(globalThis, { S, TABS, route, renderProfile, cardHtml, tableHtml, loadIndex });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sandbox, app: () => bySelector('#app').innerHTML, tab: () => bySelector('#tab').innerHTML, replaced };
}

/* ---------- what each section needs, written from the data and not from the page ---------- */
const nonEmpty = v => Array.isArray(v) ? v.length > 0 : v != null && typeof v === 'object' ? Object.keys(v).length > 0 : v != null;
const HONORS = ['nationalTitles', 'nationalRunnerUp', 'collegeCups', 'ncaaAppearances', 'confRegularSeasonTitles', 'confTournamentTitles'];
const expectRow = r => ({
  'RPI fact': (r.lastSeason?.year === RPI_SEASON && r.lastSeason.rpiRank != null) || (r.rpiHistory || []).some(h => h.year === RPI_SEASON),
  'US rank fact': r.academicRank != null,
  'Undergrads fact': r.undergradEnrollment != null,
  'Tuition fact': r.tuitionInState != null || r.tuitionOutOfState != null,
  'Commits foot': nonEmpty(r.commitmentsByYear),
  'roster foot': r.rosterSize != null,
});
const expectProfile = p => {
  const pr = p.program || {}, sch = p.school || {};
  const seasons = p.seasons || [];
  // RPI is not applicable to D2 or D3 (#246, the page's NOT_APPLICABLE.rpi), so a D3 program's RPI data - saint-francis
  // carries its D1-era ranks (#94) - is expected hidden, not shown
  const rpiSeasons = ['D2', 'D3'].includes(p.division) ? [] : seasons.filter(s => s.rpiRank);
  const scheduleData = !!p.schedule && (nonEmpty(p.schedule.games) || nonEmpty(p.schedule.history));
  // #214: a zero is a real 0 in every division with an NCAA champions table (the page's TITLE_TABLE_DIVISIONS)
  const titles = nonEmpty(pr.nationalTitles) || (['D1', 'D2', 'D3'].includes(p.division) && Array.isArray(pr.nationalTitles));
  const cups = nonEmpty(pr.collegeCups) || !!pr._meta?.wikipedia;
  const honors = !!pr._meta?.wikipedia || HONORS.some(k => nonEmpty(pr[k]));
  const rosterData = !!p.roster && nonEmpty(p.roster.players);
  const campsBuild = [...(p._build?.skipped || []), ...(p._build?.failed || [])].some(x => x.collector === 'camps');
  return {
    tabs: {
      school: !!p.school,
      climate: !!p.climate && nonEmpty(p.climate.monthly),
      history: rpiSeasons.length > 0 || seasons.length > 0 || honors,
      staff: !!(pr.headCoach?.name || nonEmpty(pr.coaches) || nonEmpty(pr.supportStaff)),
      roster: rosterData,
      commitments: nonEmpty(p.commitments),
      schedule: scheduleData,
      news: !!p.news && (nonEmpty(p.news.latest) || nonEmpty(p.news.recruiting)),
      camps: !!(p.camps && (nonEmpty(p.camps.items) || p.camps.url)) || campsBuild,
    },
    overview: {
      'season tile': seasons.some(s => !s.inProgress && s.record),
      'National titles tile': titles,
      'College Cups tile': cups,
      'Admission rate tile': sch.admissionRate != null,
      'Undergraduates tile': sch.undergradEnrollment != null,
      'Tuition tile': sch.tuitionInState != null || sch.tuitionOutOfState != null,
      'Commitments tile': nonEmpty(p.commitmentsByYear),
      'RPI chart': rpiSeasons.length > 0,
      'Roster snapshot': rosterData,
    },
    glance: {
      'RPI stat': !!rpiSeasons.find(s => s.year === RPI_SEASON)?.rpiRank,
      'Admit stat': sch.admissionRate != null,
      'Undergrads stat': sch.undergradEnrollment != null,
      'Next match': scheduleData,
      'Head coach': !!pr.headCoach?.name,
      'Roster count': p.roster?.count != null,
      'Commitments': nonEmpty(p.commitmentsByYear),
      'College Cups': cups,
      'Tuition': sch.tuitionInState != null || sch.tuitionOutOfState != null,
      'Avg net price': sch.netPriceAverage != null,
    },
    history: { 'RPI rank by season': rpiSeasons.length > 0, 'Honors': honors, 'Season by season': seasons.length > 0 },
    roster: { 'Roster turnover': nonEmpty(p.rosterHistory) },
    commitments: { 'Roster need': !!p.roster },
    news: { 'Recruiting-related': nonEmpty(p.news?.recruiting), 'Latest': nonEmpty(p.news?.latest) },
    staff: { 'Coaching staff': nonEmpty(pr.coaches), 'Support staff': nonEmpty(pr.supportStaff) || !!p.curated?.culture },
  };
};

/* ---------- how each section shows itself in the rendered markup ---------- */
const factShown = (html, label) => html.includes(`<div class="label">${label}</div>`);
const foot = html => (html.match(/<div class="foot"><span>([\s\S]*?)<span class="foot-actions">/) || [])[1] || '';
const seeRow = html => ({
  'RPI fact': factShown(html, RPI.label), 'US rank fact': factShown(html, 'US rank (THE)'),
  'Undergrads fact': factShown(html, 'Undergrads'), 'Tuition fact': factShown(html, 'Tuition / yr'),
  'Commits foot': /Commits/.test(foot(html)), 'roster foot': /on roster/.test(foot(html)),
});
const tile = (html, re) => [...html.matchAll(/<div class="tile"><div class="label">([^<]*)<\/div>/g)].some(m => re.test(m[1]));
const glance = html => (html.match(/<aside class="glance-panel"[^>]*>([\s\S]*)<\/aside>/) || [])[1] || '';
const see = {
  overview: (tab, app) => ({
    // D1 reads "National titles"; another division names itself, "NCAA D2 titles" (#197 decision 2, #207)
    'season tile': tile(tab, /season$/), 'National titles tile': tile(tab, /^(National titles|NCAA D\d titles)$/), 'College Cups tile': tile(tab, /^College Cups$/),
    'Admission rate tile': tile(tab, /^Admission rate$/), 'Undergraduates tile': tile(tab, /^Undergraduates$/), 'Tuition tile': tile(tab, /^Tuition \/ yr$/),
    'Commitments tile': tile(tab, /^Commitments$/), 'RPI chart': tab.includes('<h3>RPI, recent seasons</h3>'), 'Roster snapshot': tab.includes('<h3>Roster snapshot'),
  }),
  glance: app => {
    const g = glance(app);
    return {
      'RPI stat': g.includes(`<div class="stat-label">RPI ${RPI_SEASON}</div>`), 'Admit stat': g.includes('<div class="stat-label">Admit rate</div>'),
      'Undergrads stat': g.includes('<div class="stat-label">Undergrads</div>'), 'Next match': g.includes('>Next match</div>'),
      'Head coach': g.includes('<dt>Head coach</dt>'), 'Roster count': g.includes('<dt>Roster</dt>'), 'Commitments': g.includes('<dt>Commitments</dt>'),
      'College Cups': g.includes('<dt>College Cups</dt>'), 'Tuition': g.includes('<dt>Tuition (in / out)</dt>'), 'Avg net price': g.includes('<dt>Avg net price</dt>'),
    };
  },
  history: tab => ({ 'RPI rank by season': tab.includes('<h3>RPI rank by season</h3>'), 'Honors': tab.includes('<h3>Honors</h3>'), 'Season by season': tab.includes('<h3>Season by season</h3>') }),
  roster: tab => ({ 'Roster turnover': tab.includes('<h3>Roster turnover</h3>') }),
  commitments: tab => ({ 'Roster need': tab.includes('<h3>Roster need') }),
  news: tab => ({ 'Recruiting-related': tab.includes('<h3>Recruiting-related</h3>'), 'Latest': tab.includes('<h3>Latest</h3>') }),
  staff: tab => ({ 'Coaching staff': tab.includes('>Coaching staff</h4>'), 'Support staff': tab.includes('<h3>Support staff</h3>') }),
};
const tabsShown = (app, slug) => Object.fromEntries(['school', 'climate', 'history', 'staff', 'roster', 'commitments', 'schedule', 'news', 'camps']
  .map(k => [k, app.includes(`href="#/p/${slug}/${k}"`)]));

// Every disagreement between what the data says and what the page shows, for one program.
async function disagreements(page, row, profile) {
  const out = [];
  const cmp = (where, want, got) => { for (const k of Object.keys(want)) if (want[k] !== got[k]) out.push(`${row.slug} ${where} ${k}: data ${want[k] ? 'has it' : 'has none'}, page ${got[k] ? 'shows it' : 'hides it'}`); };
  cmp('card', expectRow(row), seeRow(page.sandbox.cardHtml(row)));
  const want = expectProfile(profile);
  page.sandbox.location.hash = `#/p/${row.slug}`;
  await page.sandbox.renderProfile(row.slug, 'overview');
  cmp('tab strip', want.tabs, tabsShown(page.app(), row.slug));
  cmp('overview', want.overview, see.overview(page.tab(), page.app()));
  cmp('glance', want.glance, see.glance(page.app()));
  for (const k of ['history', 'roster', 'commitments', 'news', 'staff']) {
    if (!want.tabs[k]) continue; // a hidden tab has no body to inspect; the tab strip check covers it
    page.sandbox.location.hash = `#/p/${row.slug}/${k}`;
    await page.sandbox.renderProfile(row.slug, k);
    cmp(`${k} tab`, want[k], see[k](page.tab()));
  }
  return out;
}

/* ---------- synthetic D2 programs with almost nothing ---------- */
function d2Profile(slug, patch = {}) {
  const p = {
    slug, name: `Synthetic ${slug}`, shortName: slug, nickname: null, division: 'D2', conference: 'Gulf South Conference', colors: null,
    ids: {}, social: {}, links: { athletics: 'https://example.invalid' },
    school: { city: 'Pensacola', state: 'FL', region: 'South', ownership: 'Public', undergradEnrollment: 4200, admissionRate: null,
      tuitionInState: 6300, tuitionOutOfState: 19000, netPriceAverage: null, _meta: null },
    academicRank: { rank: null }, climate: null,
    program: { headCoach: { name: null }, coaches: [], supportStaff: [], stadium: null, founded: null, nationalTitles: [], nationalRunnerUp: [],
      collegeCups: [], ncaaAppearances: [], confRegularSeasonTitles: [], confTournamentTitles: [],
      allTimeRecord: { wins: 0, losses: 0, ties: 0, winPct: null, seasons: 0 }, _meta: { wikipedia: null, athletics: null } },
    seasons: [], roster: null, rosterHistory: {}, schedule: null, commitments: [], news: null, camps: null, curated: {}, commitmentsByYear: {},
    _build: { builtAt: '2026-09-16T00:00:00Z', completeness: 0.11, sections: {}, stale: [], failed: [], skipped: [] },
  };
  return Object.assign(p, patch);
}
const d2Row = p => ({
  slug: p.slug, name: p.name, shortName: p.shortName, nickname: null, searchNames: [p.name], conference: p.conference, division: 'D2', colors: null,
  city: p.school?.city, state: p.school?.state, region: p.school?.region, ownership: p.school?.ownership, undergradEnrollment: p.school?.undergradEnrollment,
  admissionRate: p.school?.admissionRate, sat25: null, sat75: null, academicRank: null, academicRankTied: false,
  tuitionInState: p.school?.tuitionInState, tuitionOutOfState: p.school?.tuitionOutOfState, headCoach: null, coachSince: null,
  nationalTitles: 0, collegeCups: 0, currentSeason: null, lastSeason: null, rpiHistory: [], rosterSize: p.roster?.count ?? null,
  commitmentsByYear: p.commitmentsByYear, fallClimate: null, completeness: p._build.completeness, stale: [], builtAt: p._build.builtAt, failed: [], tags: [],
});

const REAL_INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data/programs/index.json'), 'utf8'));
const bare = d2Profile('synthetic-d2-bare');
const committed = d2Profile('synthetic-d2-commits', {
  commitments: [{ id: 'x', name: 'Test Recruit', aliases: [], gradYear: 2027, pos: 'M', club: null, status: 'verbal', confidence: 'single-source', flags: [], sources: [{ kind: 'tds' }], announced: null }],
  commitmentsByYear: { 2027: 1 },
});
const skippedCamps = d2Profile('synthetic-d2-camps-skipped', { _build: { ...bare._build, skipped: [{ collector: 'camps', reason: 'camps: athletics site refuses CollegeDashBot (CloudFront 403)' }] } });
const failedCamps = d2Profile('synthetic-d2-camps-failed', { _build: { ...bare._build, failed: [{ collector: 'camps', error: 'HTTP 500' }] } });
const emptyCamps = d2Profile('synthetic-d2-camps-none', { camps: { url: null, items: [], parsed: false, _meta: [] } });
const synthetic = [bare, committed, skippedCamps, failedCamps, emptyCamps];
const overrides = { 'data/programs/index.json': { ...REAL_INDEX, programs: [...REAL_INDEX.programs, ...synthetic.map(d2Row)] } };
for (const p of synthetic) overrides[`data/programs/${p.slug}.json`] = p;

const page = loadPage(overrides);
await page.sandbox.loadIndex();
const rowOf = slug => page.sandbox.S.index.programs.find(r => r.slug === slug);

test('every published program shows each section exactly when its data exists, in both directions', async () => {
  const bad = [];
  const counts = {};
  for (const row of REAL_INDEX.programs) {
    const profile = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data/programs', `${row.slug}.json`), 'utf8'));
    bad.push(...await disagreements(page, row, profile));
    for (const [k, v] of Object.entries(expectProfile(profile).tabs)) (counts[k] ||= [0, 0])[v ? 0 : 1]++;
  }
  // both directions are exercised on real data, or the check proves less than it says
  for (const k of ['commitments', 'roster', 'schedule', 'news', 'camps', 'staff'])
    assert.ok(counts[k][0] > 0 && counts[k][1] > 0, `the real data has no program on one side of the ${k} rule: ${counts[k]}`);
  assert.deepEqual(bad.slice(0, 20), [], `${bad.length} disagreements`);
});

test('a synthetic D2 program with almost nothing shows only what it has', async () => {
  const bad = [];
  for (const p of synthetic) bad.push(...await disagreements(page, rowOf(p.slug), p));
  assert.deepEqual(bad, []);
  page.sandbox.location.hash = `#/p/${bare.slug}`;
  await page.sandbox.renderProfile(bare.slug, 'overview');
  assert.deepEqual([...page.app().matchAll(/class="view-tab[^"]*"[^>]*>([^<]+)</g)].map(m => m[1]), ['Overview', 'School & Location'],
    'the bare program should offer exactly Overview and School & Location');
  const card = page.sandbox.cardHtml(rowOf(bare.slug));
  assert.ok(!card.includes('N/A') && !card.includes('>—<'), 'the bare card still shows an empty value');
});

test('the rule is per program: a D2 program with commitments gets the commitments tab, one without does not', async () => {
  page.sandbox.location.hash = `#/p/${committed.slug}`;
  await page.sandbox.renderProfile(committed.slug, 'overview');
  assert.ok(page.app().includes(`href="#/p/${committed.slug}/commitments"`));
  await page.sandbox.renderProfile(bare.slug, 'overview');
  assert.ok(!page.app().includes(`href="#/p/${bare.slug}/commitments"`));
});

test('camps (#44): a skipped or failed collection keeps the tab and says why; a collection that found nothing hides it', async () => {
  for (const [p, want, text] of [[skippedCamps, true, 'refuses CollegeDashBot'], [failedCamps, true, 'could not be read'], [emptyCamps, false, null], [bare, false, null]]) {
    page.sandbox.location.hash = `#/p/${p.slug}`;
    await page.sandbox.renderProfile(p.slug, 'overview');
    assert.equal(page.app().includes(`href="#/p/${p.slug}/camps"`), want, `${p.slug}: camps tab ${want ? 'missing' : 'shown'}`);
    if (want) {
      page.replaced.length = 0;
      page.sandbox.location.hash = `#/p/${p.slug}/camps`;
      await page.sandbox.renderProfile(p.slug, 'camps');
      assert.deepEqual(page.replaced, [], `${p.slug}: an offered camps tab redirected`);
      assert.ok(page.tab().includes(text), `${p.slug}: the camps tab does not say why: ${page.tab().slice(0, 200)}`);
    }
  }
});

test('a direct link to a hidden tab lands on Overview, rewrites the address and says why; the default tab is Overview', async () => {
  page.replaced.length = 0;
  page.sandbox.location.hash = `#/p/${bare.slug}/camps`;
  await page.sandbox.route();
  await new Promise(r => setTimeout(r, 0));
  assert.deepEqual(page.replaced, [`#/p/${bare.slug}`], 'the address was not rewritten to the profile');
  assert.ok(page.app().includes(`class="view-tab active" role="tab" aria-selected="true">Overview</a>`), 'Overview is not the active tab');
  assert.ok(page.app().includes('There is no ID camp information for'), 'the page does not say why the tab is missing');
  assert.ok(page.tab().includes('<div class="tiles section">'), 'the overview body was not rendered');
  // an offered tab is not rewritten, and an unknown tab name still falls back quietly as before
  page.replaced.length = 0;
  page.sandbox.location.hash = '#/p/stanford/roster';
  await page.sandbox.renderProfile('stanford', 'roster');
  assert.deepEqual(page.replaced, []);
  assert.ok(page.app().includes(`class="view-tab active" role="tab" aria-selected="true">Roster</a>`));
  await page.sandbox.renderProfile('stanford', 'no-such-tab');
  assert.deepEqual(page.replaced, [], 'an unknown tab name was treated as a hidden tab');
  assert.ok(!page.app().includes('tab is not shown'));
  await page.sandbox.renderProfile(bare.slug, 'overview');
  assert.ok(page.app().includes(`class="view-tab active" role="tab" aria-selected="true">Overview</a>`), 'the default tab is not Overview');
});

test('table columns: a data column is left out only when no row on screen has data for it', () => {
  const S = page.sandbox.S;
  S.filters.moreStats = true; S.filters.classYear = [];
  // a sortable header carries its label in a button (#285)
  const heads = html => [...html.matchAll(/<th class="[^"]*"[^>]*>(?:<button[^>]*>)?([^<]*)(?:<\/button>)?<\/th>/g)].map(m => m[1]);
  const all = heads(page.sandbox.tableHtml(REAL_INDEX.programs));
  // no Record column since #342: the record stays on cards, the profile and Compare
  assert.deepEqual(all, [RPI.label, '', 'Program', 'Admit', 'US rank (THE)', 'Undergrads', 'Tuition / yr', 'Commits', 'Titles', 'College Cups', 'Region', 'Type', ''],
    'the full D1 table lost a column');
  const d2 = heads(page.sandbox.tableHtml([rowOf(bare.slug), rowOf(committed.slug)]));
  assert.deepEqual(d2, ['', 'Program', 'Undergrads', 'Tuition / yr', 'Commits', 'Region', 'Type', ''], 'the synthetic D2 table columns');
  const mixed = heads(page.sandbox.tableHtml([rowOf('stanford'), rowOf(bare.slug)]));
  assert.ok(mixed.includes(RPI.label) && mixed.includes('Titles'), 'one ranked program on screen must keep the RPI and Titles columns');
  // A Division I row without data in a kept column shows a dash. A Division II row shows nothing there at all:
  // RPI does not apply to Division II (#198), which is not the same as missing.
  const unrankedD1 = REAL_INDEX.programs.find(r => r.division === 'D1' && !(r.lastSeason?.year === RPI_SEASON && r.lastSeason.rpiRank) && !(r.rpiHistory || []).some(h => h.year === RPI_SEASON));
  assert.ok(unrankedD1, 'no unranked Division I program in the index to check the dash with');
  assert.ok(page.sandbox.tableHtml([rowOf('stanford'), rowOf(unrankedD1.slug)]).includes('<span class="rank-num">—</span>'), 'a row without data in a kept column shows a dash');
  assert.ok(!page.sandbox.tableHtml([rowOf('stanford'), rowOf(bare.slug)]).includes('<span class="rank-num">—</span>'), 'a Division II row shows the missing-data dash for an RPI that does not apply to it');
  assert.ok(page.sandbox.tableHtml([]).includes('No programs match.'), 'an empty table lost its message');
  S.filters.moreStats = false;
});
