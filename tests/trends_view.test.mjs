// The clubs & high-schools view, #/trends (issue #230).
//
//     node --test tests/trends_view.test.mjs
//
// Same mechanism as tests/section_hiding.test.mjs: the inline <script> of public/index.html runs in a `vm`
// against a stub DOM, so what runs is the real source text of the real file. fetch serves public/ for the
// program index and profiles, and a fixture for data/trends/index.json - counts only, three programs taken
// from the committed index so their names and links are real.
//
// What this proves:
//   - the pure functions (trendsProgramsFor, trendsFeedersFor, trendsCoverageLines) equal a direct computation
//     written here from the fixture, and commits never enter a program's total or its order;
//   - #/trends renders the picker and the coverage; #/trends/club/<id> renders the programs table with the
//     three counts side by side and a coverage line per column; #/trends/program/<slug> renders the clubs
//     feeding a program, and says high schools are not available when the index carries none, and renders
//     them when it does; #/trends/school/<id> reads commits as "—", never 0;
//   - no recruit is ever named: the rendered club page carries names only inside the roster expander, which
//     is served from the public roster on demand, and trendsRosterNames reads roster players only;
//   - the list view offers the Clubs & schools tab, the roster tab links a reviewed club to its trends page,
//     and a missing index renders "Not built yet" rather than an empty table.
//
// What it cannot prove: layout. The phone-width check is a screenshot in the PR.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.TRENDS_TEST_HTML || path.join(PUBLIC, 'index.html');
const readJson = rel => JSON.parse(fs.readFileSync(path.join(PUBLIC, rel), 'utf8'));
const INDEX = readJson('data/programs/index.json');
const D1 = INDEX.programs.filter(p => p.division === 'D1' && fs.existsSync(path.join(PUBLIC, 'data/programs', `${p.slug}.json`)));
assert.ok(D1.length >= 3, 'the committed index needs three D1 programs with profiles');
const [A, B, C] = D1.slice(0, 3);

/* ---------- the fixture index: counts only ---------- */
function fixture({ schools = false } = {}) {
  const doc = {
    updated: '2026-09-17T00:00:00Z', division: 'D1', season: 2026, pastSeasons: [2023, 2024, 2025],
    commitStatuses: ['verbal', 'signed'], columns: ['current', 'past', 'commits'],
    coverage: { current: { players: 100, clubKnown: 31, schoolNamed: 65, schoolKnown: schools ? 40 : null },
                past: { players: 200, clubKnown: 30, schoolNamed: 120, schoolKnown: schools ? 50 : null },
                commits: { recruits: 50, clubKnown: 49, schoolNamed: 10, schoolKnown: null } },
    programs: { [A.slug]: { current: 27, past: 29, commits: 11, clubKnown: [19, 1, 11], schoolKnown: schools ? [5, 2, 0] : [0, 0, 0] },
                [B.slug]: { current: 25, past: 20, commits: 9, clubKnown: [10, 2, 9], schoolKnown: [0, 0, 0] },
                [C.slug]: { current: 30, past: 10, commits: 2, clubKnown: [3, 0, 2], schoolKnown: [0, 0, 0] } },
    clubs: {
      'mvla': { name: 'Mountain View Los Altos SC', state: 'CA', programs: { [A.slug]: [3, 0, 0], [B.slug]: [2, 2, 1], [C.slug]: [0, 0, 5] } },
      'surf': { name: 'San Diego Surf', state: 'CA', programs: { [A.slug]: [1, 0, 3] } },
      'raw:zeta united': { name: 'Zeta United', state: null, unmatched: true, programs: { [A.slug]: [1, 0, 0] } },
    },
    schools: schools ? { 'ccd:1': { name: 'Rocklin High', city: 'Rocklin', state: 'CA', programs: { [A.slug]: [2, 1, 0], [B.slug]: [1, 0, 0] } } } : null,
  };
  return doc;
}

/* ---------- stub DOM ---------- */
function makeElement(name) {
  const el = {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, open: false,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, contains: () => false,
  };
  return el;
}

function loadPage(overrides = {}) {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
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
    history: { replaceState(_s, _t, url) { sandbox.location.hash = url; } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) },
    innerWidth: 1400, addEventListener() { },
    fetch: async url => {
      let u = String(url);
      if (Object.prototype.hasOwnProperty.call(overrides, u)) {
        const doc = overrides[u];
        if (doc === null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
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
        if (doc === null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
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
    + '\n;Object.assign(globalThis, { S, route, renderTrends, renderProfile, renderList, loadIndex, trendsProgramsFor, trendsFeedersFor, trendsCoverageLines, trendsRosterNames, listTabs, trendsKeyStep });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sandbox, app: () => bySelector('#app').innerHTML, tab: () => bySelector('#tab').innerHTML };
}
const withIndex = (doc, extra = {}) => loadPage({ 'data/trends/index.json': doc, ...extra });
// Values that crossed the vm boundary carry the sandbox's own Array/Object prototypes; strict deep equality
// compares prototypes, so they are flattened to plain JSON first.
const plain = x => JSON.parse(JSON.stringify(x));
const cellsOf = html => [...html.matchAll(/<tr class="team-row">([\s\S]*?)<\/tr>/g)].map(m => {
  const nums = [...m[1].matchAll(/<td class="num[^"]*">([\s\S]*?)<\/td>/g)].map(x => x[1].replace(/<[^>]+>/g, '').trim());
  return { name: (m[1].match(/class="team-name">([^<]*)</) || [])[1], nums };
});

/* ---------- direct computation, written from the fixture and not from the page ---------- */
function directProgramsFor(doc, id) {
  return Object.entries(doc.clubs[id].programs).map(([slug, [c, p, m]]) => ({ slug, current: c, past: p, commits: m }))
    .sort((x, y) => (y.current + y.past) - (x.current + x.past) || y.current - x.current || y.commits - x.commits || x.slug.localeCompare(y.slug));
}

test('pure functions: programs_for and feeders_for equal a direct computation; commits never enter the total or the order', async () => {
  const page = withIndex(fixture());
  const doc = fixture();
  const rows = plain(page.sandbox.trendsProgramsFor(doc, 'club', 'mvla'));
  assert.deepEqual(rows, directProgramsFor(doc, 'mvla'));
  assert.deepEqual(rows.map(r => r.slug), [B.slug, A.slug, C.slug], 'B (4 people) before A (3) before C (0 people, 5 commits)');
  assert.deepEqual(rows[2], { slug: C.slug, current: 0, past: 0, commits: 5 });
  for (const r of rows) assert.deepEqual(Object.keys(r).sort(), ['commits', 'current', 'past', 'slug'], 'no row carries a total');
  const feeders = plain(page.sandbox.trendsFeedersFor(doc, 'club', A.slug));
  assert.deepEqual(feeders.map(f => [f.id, f.current, f.past, f.commits, f.unmatched]),
    [['mvla', 3, 0, 0, false], ['surf', 1, 0, 3, false], ['raw:zeta united', 1, 0, 0, true]], 'MVLA (3 people) before Surf (1 person, 3 commits)');
  assert.deepEqual(plain(page.sandbox.trendsProgramsFor(doc, 'club', 'nope')), []);
  assert.deepEqual(plain(page.sandbox.trendsCoverageLines(doc, 'club', { current: 5, past: 2, commits: 6 })),
    ['5 of 100 current players; club known for 31%', '2 of 200 former players (stored past rosters); club known for 15%', '6 of 50 verbal or signed commits; club known for 98%']);
  assert.deepEqual(plain(page.sandbox.trendsCoverageLines(doc, 'school')), ['Current players: high school not available yet', 'Former players (stored past rosters): high school not available yet', 'Verbal or signed commits: high school not available yet']);
  const schoolRows = plain(page.sandbox.trendsProgramsFor(fixture({ schools: true }), 'school', 'ccd:1'));
  assert.deepEqual(schoolRows, [{ slug: A.slug, current: 2, past: 1, commits: null }, { slug: B.slug, current: 1, past: 0, commits: null }], 'a school reports commits as null, never 0');
});

test('#/trends: the picker, the how-to card and the coverage', async () => {
  const page = withIndex(fixture());
  page.sandbox.location.hash = '#/trends';
  await page.sandbox.route();
  await new Promise(r => setTimeout(r, 20));
  const html = page.app();
  assert.ok(html.includes('class="view-tab active" role="tab" aria-selected="true">Clubs &amp; schools</a>'), 'the Clubs & schools tab is active');
  assert.ok(html.includes('id="trendsQ"') && html.includes('id="trendsProgram"'), 'the picker has a name search and a program search');
  assert.ok(html.includes(`class="pill trend-hit" href="#/trends/program/${A.slug}"`) && !html.includes('program/gamma'), 'the program box offers the indexed programs');
  assert.ok(html.includes('href="#/trends/club/mvla"') && html.includes('Mountain View Los Altos SC'), 'the top clubs are offered as pills');
  assert.ok(!html.includes('href="#/trends/club/raw%3Azeta%20united"'), 'an unmatched spelling is not in the default top list');
  assert.ok(html.includes('100 current players; club known for 31%'), 'the coverage is stated up front');
  assert.ok(html.includes('never added into a program'), 'the commits rule is stated');
  assert.ok(html.includes('High-school results are not published yet'), 'schools absent: said so');
});

test('#/trends/club/<id>: three counts side by side, sorted by people, with a coverage line per column', async () => {
  const page = withIndex(fixture());
  page.sandbox.location.hash = '#/trends/club/mvla';
  await page.sandbox.route();
  await new Promise(r => setTimeout(r, 20));
  const html = page.app();
  const rows = cellsOf(html);
  const disp = p => p.shortName || p.name;
  assert.deepEqual(rows.map(r => r.name), [disp(B), disp(A), disp(C)], 'most people first; commits do not lift C');
  assert.deepEqual(rows.map(r => r.nums), [['4', '2', '2', '1'], ['3', '3', '0', '0'], ['0', '0', '0', '5']],
    'Players = current + past; commits sit in their own column and are not in it');
  assert.ok(html.includes('5 of 100 current players; club known for 31%'), 'coverage: current');
  assert.ok(html.includes('2 of 200 former players (stored past rosters); club known for 15%'), 'coverage: past');
  assert.ok(html.includes('6 of 50 verbal or signed commits; club known for 98%'), 'coverage: commits (49 of 50)');
  assert.ok(html.includes('never added into a program'), 'the commits rule is on the page');
  assert.ok(html.includes(`href="#/p/${A.slug}/roster"`), 'a program links to its roster');
  assert.ok(html.includes(`data-slug="${A.slug}" data-kind="club" data-id="mvla"`), 'a program with current players offers the roster expander');
  assert.ok(!html.includes(`data-slug="${C.slug}"`), 'a program with commits only has no expander: commits are never listed');
  assert.ok(html.includes('commits are never listed by name'), 'the privacy rule is on the page');
  assert.ok(!html.includes('unmatched spelling'), 'a reviewed club carries no unmatched badge');
  // an unmatched spelling is shown as such
  page.sandbox.location.hash = '#/trends/club/raw%3Azeta%20united';
  await page.sandbox.route();
  await new Promise(r => setTimeout(r, 20));
  assert.ok(page.app().includes('Zeta United') && page.app().includes('unmatched spelling'));
  // an id the index does not carry
  page.sandbox.location.hash = '#/trends/club/nope';
  await page.sandbox.route();
  await new Promise(r => setTimeout(r, 20));
  assert.ok(page.app().includes('Not in the index') && page.app().includes('id="trendsQ"'), 'unknown id: says so and keeps the picker');
});

test('#/trends/school/<id>: commits read as not available, never 0', async () => {
  const page = withIndex(fixture({ schools: true }));
  page.sandbox.location.hash = '#/trends/school/ccd%3A1';
  await page.sandbox.route();
  await new Promise(r => setTimeout(r, 20));
  const html = page.app();
  assert.ok(html.includes('Rocklin High') && html.includes('Rocklin, CA'));
  const rows = cellsOf(html);
  assert.deepEqual(rows.map(r => r.nums), [['3', '2', '1', '—'], ['1', '1', '0', '—']]);
  assert.ok(html.includes('3 of 100 current players; high school known for 40%'), 'a high-school coverage line, from schoolKnown (2 at A + 1 at B)');
  assert.ok(html.includes('Commits are not shown for high schools'));
});

test('#/trends/program/<slug>: the clubs feeding a program, and high schools only when the index has them', async () => {
  let page = withIndex(fixture());
  page.sandbox.location.hash = `#/trends/program/${A.slug}`;
  await page.sandbox.route();
  await new Promise(r => setTimeout(r, 20));
  let html = page.app();
  assert.ok(html.includes(`Clubs feeding ${A.shortName || A.name}`));
  assert.ok(html.includes('href="#/trends/club/mvla"') && html.includes('href="#/trends/club/surf"') && html.includes('href="#/trends/club/raw%3Azeta%20united"'), 'each club links to its own page');
  assert.ok(html.indexOf('href="#/trends/club/mvla"') < html.indexOf('href="#/trends/club/surf"'), 'MVLA (3 people) before Surf (1 person, 3 commits)');
  assert.ok(html.includes('unmatched spelling'), 'the unmatched entry is badged');
  assert.ok(html.includes('27 current players; club known for 19 (70%)') && html.includes('29 former players; club known for 1 (3%)') && html.includes('11 verbal or signed commits; club known for 11 (100%)'), 'per-program coverage');
  assert.ok(html.includes('High-school results are not available yet'), 'schools absent: said so');
  assert.ok(html.includes(`class="pill trend-hit active" href="#/trends/program/${A.slug}"`), 'the program box marks the chosen program');
  page = withIndex(fixture({ schools: true }));
  page.sandbox.location.hash = `#/trends/program/${A.slug}`;
  await page.sandbox.route();
  await new Promise(r => setTimeout(r, 20));
  html = page.app();
  assert.ok(html.includes(`High schools feeding ${A.shortName || A.name}`) && html.includes('href="#/trends/school/ccd%3A1"') && html.includes('Rocklin High'));
  assert.ok(html.includes('27 current players; high school known for 5 (19%)'), 'per-program school coverage');
  // a program the index does not carry
  const d2 = INDEX.programs.find(p => p.division !== 'D1');
  if (d2) {
    page.sandbox.location.hash = `#/trends/program/${d2.slug}`;
    await page.sandbox.route();
    await new Promise(r => setTimeout(r, 20));
    assert.ok(page.app().includes('not a Division I program'), 'a D2 program: says the index is D1 only');
  }
});

test('a missing index renders "Not built yet", not an empty table', async () => {
  const page = withIndex(null);
  page.sandbox.location.hash = '#/trends/club/mvla';
  await page.sandbox.route();
  await new Promise(r => setTimeout(r, 20));
  assert.ok(page.app().includes('Not built yet') && !page.app().includes('<table'));
});

test('the list view offers the tab; the roster tab links a reviewed club to trends and names only roster players', async () => {
  const page = withIndex(fixture());
  page.sandbox.location.hash = '#/';
  await page.sandbox.route();
  await new Promise(r => setTimeout(r, 20));
  assert.ok(page.app().includes('href="#/trends"'), 'the programs list is missing the Clubs & schools tab');
  assert.ok(page.sandbox.listTabs('cards').includes('>ID Camps</a>'), 'ID Camps is still there');
  // a D1 profile with one matched and one unmatched club
  const prof = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data/programs', `${A.slug}.json`), 'utf8'));
  const pl = prof.roster.players;
  pl[0].club = 'Mountain View Los Altos SC'; pl[0].clubInfo = { raw: 'MVLA', key: 'mvla', clubId: 'mvla', club: 'Mountain View Los Altos SC', status: 'matched' };
  pl[1].club = 'Zeta United'; pl[1].clubInfo = { raw: 'Zeta United', key: 'zeta united', clubId: null, club: null, status: 'unmatched' };
  const p2 = withIndex(fixture(), { [`data/programs/${A.slug}.json`]: prof });
  p2.sandbox.location.hash = `#/p/${A.slug}/roster`;
  await p2.sandbox.route();
  await new Promise(r => setTimeout(r, 30));
  const tab = p2.tab();
  assert.ok(tab.includes('href="#/trends/club/mvla"'), 'a matched club links to its trends page');
  assert.ok(!tab.includes('href="#/trends/club/raw'), 'an unmatched spelling does not');
  assert.ok(tab.includes(`href="#/trends/program/${A.slug}"`), 'the roster tab links to where the program\'s players come from');
  assert.deepEqual(plain(p2.sandbox.trendsRosterNames(prof, 'club', 'mvla')), [`${pl[0].name} (${[pl[0].pos, pl[0].classCode].filter(Boolean).join(', ')})`]);
  assert.deepEqual(plain(p2.sandbox.trendsRosterNames(prof, 'club', 'raw:zeta united')), [`${pl[1].name} (${[pl[1].pos, pl[1].classCode].filter(Boolean).join(', ')})`]);
  assert.deepEqual(plain(p2.sandbox.trendsRosterNames({ roster: null, commitments: prof.commitments }, 'club', 'mvla')), [], 'commitments are never a source of names');
  // a D2 profile gets neither link
  const d2 = JSON.parse(JSON.stringify(prof)); d2.division = 'D2';
  const p3 = withIndex(fixture(), { [`data/programs/${A.slug}.json`]: d2 });
  p3.sandbox.location.hash = `#/p/${A.slug}/roster`;
  await p3.sandbox.route();
  await new Promise(r => setTimeout(r, 30));
  assert.ok(!p3.tab().includes('#/trends/'), 'a D2 roster carries no trends link');
});

/* ---------- #307: type-ahead search by alias, program search, and a header that agrees with the search ---------- */
// The aka list is what trends.search_aliases writes for MVLA from data/clubs.json (tests/trends_test.py checks that side).
const D2 = INDEX.programs.find(p => p.division === 'D2' && p.shortName);
function searchFixture() {
  const doc = fixture({ schools: true });
  doc.clubs.mvla.aka = ['mvla', 'mtn view los altos sc', 'mountain view los altos sc mvla'];
  doc.schools['ccd:2'] = { name: 'Carroll Senior H S', city: 'Southlake', state: 'TX', aka: ['southlake carroll'], programs: { [A.slug]: [1, 0, 0] } };
  doc.schools['ccd:3'] = { name: 'Decatur High School', city: 'Decatur', state: 'AL', programs: { [A.slug]: [1, 0, 0] } };
  doc.schools['ccd:4'] = { name: 'Decatur High School', city: 'Decatur', state: 'GA', programs: { [B.slug]: [1, 0, 0] } };
  for (const s of ['stanford', 'north-carolina', 'unc-wilmington', 'louisville', D2.slug]) doc.programs[s] = { current: 3, past: 1, commits: 0, clubKnown: [1, 0, 0], schoolKnown: [0, 0, 0] };
  for (let i = 1; i <= 9; i++) doc.clubs[`c${i}`] = { name: `Club ${i}`, state: 'CA', programs: { [A.slug]: [1, 0, 0] } };
  doc.programs.louisville.current = 9; // more players than Stanford: only the exact nickname can put Stanford first for "cardinal"
  return doc;
}
async function typeInto(hash, box, hits, text) {
  const page = withIndex(searchFixture());
  page.sandbox.location.hash = hash;
  await page.sandbox.route();
  await new Promise(r => setTimeout(r, 20));
  const input = page.sandbox.document.querySelector(box);
  input.value = text; input.oninput();
  return { hits: page.sandbox.document.querySelector(hits).innerHTML, header: page.app().split('class="content-body"')[0] };
}
const clubHits = text => typeInto('#/trends', '#trendsQ', '#trendsHits', text).then(r => r.hits);
const progHits = text => typeInto('#/trends', '#trendsProgram', '#trendsProgHits', text).then(r => r.hits);

test('#307 club search: "mvla", "MVLA" and "mountain view" all find Mountain View Los Altos SC; a school by its name; unknown says no match', async () => {
  for (const q of ['mvla', 'MVLA', 'mountain view', 'Mtn View']) {
    const h = await clubHits(q);
    assert.ok(h.includes('href="#/trends/club/mvla"') && h.includes('>Mountain View Los Altos SC<'), `"${q}" finds the canonical club`);
    assert.ok(!h.includes('San Diego Surf'), `"${q}" finds only that club`);
  }
  assert.ok((await clubHits('MVLA')).includes('also known as MVLA'), 'an alias hit says which alias it matched, a short name in capitals');
  assert.ok(!(await clubHits('mountain view')).includes('also known as'), 'a hit on the name itself carries no alias line');
  const hs = await clubHits('rocklin');
  assert.ok(hs.includes('href="#/trends/school/ccd%3A1"') && hs.includes('Rocklin High'), 'a high school is found by its name');
  const carroll = await clubHits('Southlake Carroll');
  assert.ok(carroll.includes('href="#/trends/school/ccd%3A2"') && carroll.includes('>Carroll Senior H S<') && carroll.includes('also known as Southlake Carroll'),
    'a roster spelling finds the school under its NCES name, saying which spelling matched');
  const dec = await clubHits('decatur high');
  assert.ok(dec.includes('Decatur, AL') && dec.includes('Decatur, GA') && dec.includes('ccd%3A3') && dec.includes('ccd%3A4'), 'two same-name schools are both listed, told apart by city and state');
  const none = await clubHits('zzqx united');
  assert.ok(none.includes('No club or high school in the index matches “zzqx united”.') && !none.includes('trend-hit'), 'an unknown string shows the no-match message');
});

test('#307 phones: an empty box suggests 6 buttons at ≤480px and 12 on desktop; a typed query is not cut to 6', async () => {
  const count = html => (html.match(/class="pill trend-hit/g) || []).length;
  const render = async phone => {
    const page = withIndex(searchFixture());
    page.sandbox.matchMedia = q => ({ matches: phone && q === '(max-width: 480px)', addEventListener() { }, addListener() { } });
    page.sandbox.location.hash = '#/trends';
    await page.sandbox.route();
    await new Promise(r => setTimeout(r, 20));
    const d = page.sandbox.document, q = d.querySelector('#trendsQ'), pq = d.querySelector('#trendsProgram');
    q.value = ''; q.oninput(); pq.value = ''; pq.oninput(); // the empty boxes, rendered through the same handler as typing
    const first = { clubs: count(d.querySelector('#trendsHits').innerHTML), progs: count(d.querySelector('#trendsProgHits').innerHTML) };
    q.value = 'club'; q.oninput();
    return { ...first, typed: count(d.querySelector('#trendsHits').innerHTML) };
  };
  const desk = await render(false), phone = await render(true);
  const progsIn = Object.keys(searchFixture().programs).filter(s => INDEX.programs.some(p => p.slug === s)).length;
  assert.ok(progsIn > 6 && progsIn <= 12, 'the fixture has between 7 and 12 programs');
  assert.deepEqual([desk.clubs, desk.progs], [11, progsIn], 'desktop: every suggestion up to 12 (11 clubs and every program in the fixture)');
  assert.deepEqual([phone.clubs, phone.progs], [6, 6], 'phone: 6 suggestions in each empty box');
  assert.equal(phone.typed, 9, 'phone: a typed query still lists its matches beyond 6');
});

test('#307 header:a search that finds nothing names the selection the header and the card still show', async () => {
  const r = await typeInto('#/trends/club/surf', '#trendsQ', '#trendsHits', 'zzqx');
  assert.ok(r.header.includes('San Diego Surf ·'), 'the header names the selected club');
  assert.ok(r.hits.includes('No club or high school in the index matches “zzqx”. Still showing San Diego Surf below'), 'the no-match line names the same selection, so the two agree');
  const none = await typeInto('#/trends', '#trendsQ', '#trendsHits', 'zzqx');
  assert.ok(!none.hits.includes('Still showing'), 'with nothing selected, no selection is claimed');
  const p = await typeInto('#/trends/program/stanford', '#trendsProgram', '#trendsProgHits', 'zzqx');
  assert.ok(p.header.includes('Stanford ·') && p.hits.includes('No program in the index matches “zzqx”. Still showing Stanford below'), 'the program box names the selected program too');
});

test('#307 program search: name, nickname, short name, division line; arrow keys and Enter', async () => {
  assert.ok((await progHits('stanford')).startsWith('<a class="pill trend-hit" href="#/trends/program/stanford">Stanford<'), '"stanford" finds Stanford first');
  const card = await progHits('cardinal');
  assert.ok(card.startsWith('<a class="pill trend-hit" href="#/trends/program/stanford">') && card.includes('· Cardinal</span>'), '"cardinal" finds Stanford first, by its exact nickname, and says so');
  assert.ok(card.includes('href="#/trends/program/louisville"') && !card.includes('program/north-carolina'), 'and only nickname matches');
  assert.ok((await progHits('UNC Wil')).startsWith('<a class="pill trend-hit" href="#/trends/program/unc-wilmington">'), '"UNC Wil" finds UNC Wilmington by its short name');
  assert.ok((await progHits('north carolina')).includes('href="#/trends/program/north-carolina"'), '"north carolina" finds North Carolina');
  const d2 = await progHits(D2.shortName);
  assert.ok(d2.includes(`href="#/trends/program/${D2.slug}"`) && d2.includes('<span class="div-tag" title="Division II">D2</span>'), 'a D2 program shows its division in the results');
  assert.ok((await progHits('zzqx')).includes('No program in the index matches “zzqx”.'), 'an unknown program says no match');
  // keyboard: the step function the keydown handler runs (the handler itself is read in the PR; see the PR body)
  const sb = withIndex(searchFixture()).sandbox;
  const k = (at, key, n) => plain(sb.trendsKeyStep(at, key, n));
  assert.deepEqual(k(-1, 'ArrowDown', 3), { at: 0 }, 'ArrowDown from the box marks the first hit');
  assert.deepEqual(k(2, 'ArrowDown', 3), { at: 0 }, 'ArrowDown wraps');
  assert.deepEqual(k(-1, 'ArrowUp', 3), { at: 2 }, 'ArrowUp from the box marks the last hit');
  assert.deepEqual(k(1, 'Enter', 3), { at: 1, go: 1 }, 'Enter opens the marked hit');
  assert.deepEqual(k(-1, 'Enter', 3), { at: -1, go: 0 }, 'Enter with none marked opens the first');
  assert.deepEqual(k(-1, 'Enter', 0), { at: -1 }, 'Enter with no hits does nothing');
  assert.deepEqual(k(1, 'a', 3), { at: 1 }, 'other keys leave the mark alone');
});
