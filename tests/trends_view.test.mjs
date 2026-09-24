// The clubs & high-schools view, #/trends (issues #230, #307, #310).
//
//     node --test tests/trends_view.test.mjs
//
// Same mechanism as tests/section_hiding.test.mjs: the inline <script> of public/index.html runs in a `vm`
// against a stub DOM, so what runs is the real source text of the real file. fetch serves public/ for the
// program index and profiles, and a fixture for data/trends/index.json - counts only, three programs taken
// from the committed index so their names and links are real. The stub keeps one element per selector, so a
// test reads what the page wrote into #trResults, #trSub, #trLive and the three boxes, and which element holds
// the focus.
//
// Every expected count below is a literal worked out by hand from the fixture, never a call to a page helper.
//
// What it cannot prove: layout, and real key presses. The in-app browser does not deliver keys, so the
// keyboard is proven here by calling the boxes' own keydown handlers; a person should still try it once.
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
const disp = p => p.shortName || p.name;
const D2 = INDEX.programs.find(p => p.division === 'D2' && p.shortName);

/* ---------- the fixture index: counts only ----------
   mvla: A [3 cur, 0 past, 0 commits], B [2, 2, 1], C [0, 0, 5]  (C: commits only, so Players 0)
   surf: A [1, 0, 3]; raw:zeta united (unmatched): A [1, 0, 0]
   ccd:1 Rocklin High (schools only): A [2, 1, -], B [1, 0, -] */
function fixture({ schools = false } = {}) {
  return {
    updated: '2026-09-17T00:00:00Z', division: 'D1', season: 2026, pastSeasons: [2023, 2024, 2025],
    commitStatuses: ['verbal', 'signed'], columns: ['current', 'past', 'commits'],
    coverage: { current: { players: 100, clubKnown: 31, schoolNamed: 65, schoolKnown: schools ? 40 : null },
                past: { players: 200, clubKnown: 30, schoolNamed: 120, schoolKnown: schools ? 50 : null },
                commits: { recruits: 50, clubKnown: 49, schoolNamed: 10, schoolKnown: null } },
    programs: { [A.slug]: { current: 27, past: 29, commits: 11, clubKnown: [19, 1, 11], schoolKnown: schools ? [5, 2, 0] : [0, 0, 0] },
                [B.slug]: { current: 25, past: 20, commits: 9, clubKnown: [10, 2, 9], schoolKnown: [0, 0, 0] },
                [C.slug]: { current: 30, past: 10, commits: 2, clubKnown: [3, 0, 2], schoolKnown: [0, 0, 0] } },
    clubs: {
      'mvla': { name: 'Mountain View Los Altos SC', state: 'CA', aka: ['mvla', 'mtn view los altos sc'], programs: { [A.slug]: [3, 0, 0], [B.slug]: [2, 2, 1], [C.slug]: [0, 0, 5] } },
      'surf': { name: 'San Diego Surf', state: 'CA', programs: { [A.slug]: [1, 0, 3] } },
      'raw:zeta united': { name: 'Zeta United', state: null, unmatched: true, programs: { [A.slug]: [1, 0, 0] } },
    },
    schools: schools ? { 'ccd:1': { name: 'Rocklin High', city: 'Rocklin', state: 'CA', programs: { [A.slug]: [2, 1, 0], [B.slug]: [1, 0, 0] } } } : null,
  };
}
// #307 search data on top: school spellings, two same-name schools, more programs and clubs.
function searchFixture() {
  const doc = fixture({ schools: true });
  doc.schools['ccd:2'] = { name: 'Carroll Senior H S', city: 'Southlake', state: 'TX', aka: ['southlake carroll'], programs: { [A.slug]: [1, 0, 0] } };
  doc.schools['ccd:3'] = { name: 'Decatur High School', city: 'Decatur', state: 'AL', programs: { [A.slug]: [1, 0, 0] } };
  doc.schools['ccd:4'] = { name: 'Decatur High School', city: 'Decatur', state: 'GA', programs: { [B.slug]: [1, 0, 0] } };
  for (const s of ['stanford', 'north-carolina', 'unc-wilmington', 'louisville', D2.slug]) doc.programs[s] = { current: 3, past: 1, commits: 0, clubKnown: [1, 0, 0], schoolKnown: [0, 0, 0] };
  for (let i = 1; i <= 9; i++) doc.clubs[`c${i}`] = { name: `Club ${i}`, state: 'CA', programs: { [A.slug]: [1, 0, 0] } };
  doc.programs.louisville.current = 9; // more players than Stanford: only the exact nickname can put Stanford first for "cardinal"
  return doc;
}

/* ---------- stub DOM ---------- */
function makeElement(name, doc) {
  const cls = new Set(), attrs = {};
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, open: false,
    dataset: {}, style: {}, attrs,
    classList: { add: c => cls.add(c), remove: c => cls.delete(c), toggle: (c, on) => ((on ?? !cls.has(c)) ? cls.add(c) : cls.delete(c), cls.has(c)), contains: c => cls.has(c) },
    setAttribute(k, v) { attrs[k] = String(v); }, getAttribute: k => (k in attrs ? attrs[k] : null), removeAttribute(k) { delete attrs[k]; },
    addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child', doc), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { if (doc) doc.activeElement = this; }, contains: () => false,
  };
}

function loadPage(overrides = {}) {
  const els = new Map();
  const document = { querySelectorAll: () => [], addEventListener() { }, activeElement: null };
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel, document)); return els.get(sel); };
  Object.assign(document, { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector, createElement: n => makeElement(n, document) });
  const store = new Map(), hist = { stack: [], pushes: 0, replaces: 0 };
  const serve = u => {
    if (u.startsWith('/api/v1/')) {
      const sub = u.slice('/api/v1/'.length);
      if (sub === 'programs') u = 'data/programs/index.json';
      else if (sub.startsWith('programs/')) u = `data/programs/${sub.slice('programs/'.length)}.json`;
      else if (sub === 'trends') u = 'data/trends/index.json';
      else if (sub === 'camps') u = 'data/camps/index.json';
      else if (sub === 'commitments') u = 'data/commitments/index.json';
      else if (sub === 'status') u = 'archive/refresh-state.json';
    }
    if (Object.prototype.hasOwnProperty.call(overrides, u)) return overrides[u] === null ? null : JSON.stringify(overrides[u]);
    const p = path.join(PUBLIC, u.replace(/^\//, ''));
    return p.startsWith(PUBLIC) && fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent, document,
    location: { hash: '', replace(h) { this.hash = h; } },
    history: {
      pushState(_s, _t, url) { hist.stack.push(sandbox.location.hash); hist.pushes++; sandbox.location.hash = url; },
      replaceState(_s, _t, url) { hist.replaces++; sandbox.location.hash = url; },
      back() { sandbox.location.hash = hist.stack.pop(); },
    },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) },
    innerWidth: 1400, addEventListener() { },
    fetch: async url => {
      const body = serve(String(url));
      if (body == null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(HTML, 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'public/index.html: could not find the inline <script>');
  const src = lines.slice(a + 1, b).join('\n')
    + '\n;Object.assign(globalThis, { S, route, renderProfile, trendsProgramsFor, trendsFeedersFor, trendsBothFor, trendsCoverageLines, trendsRosterNames, listTabs, trendsKeyStep, trendsParse, trendsUrl, trendsClubCell, trState: () => TR });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  const el = sel => bySelector(sel);
  return { sandbox, hist, el, app: () => el('#app').innerHTML, tab: () => el('#tab').innerHTML, results: () => el('#trResults').innerHTML, sub: () => el('#trSub').innerHTML };
}
const tick = (ms = 20) => new Promise(r => setTimeout(r, ms));
async function open(hash, doc = fixture(), extra = {}) {
  const page = loadPage({ 'data/trends/index.json': doc, ...extra });
  page.sandbox.location.hash = hash;
  await page.sandbox.route();
  await tick();
  return page;
}
const key = (page, kind, k) => { let prevented = false; page.el(`#trIn-${kind}`).onkeydown({ key: k, preventDefault() { prevented = true; } }); return prevented; };
const type = (page, kind, text) => { const i = page.el(`#trIn-${kind}`); i.value = text; i.oninput(); return page.el(`#trList-${kind}`).innerHTML; };
const optIds = (page, kind) => page.sandbox.trState().opts[kind].map(o => o.id);
const click = el => el.onclick({ target: el, preventDefault() { } });
// Values that crossed the vm boundary carry the sandbox's own prototypes; strict deep equality compares them.
const plain = x => JSON.parse(JSON.stringify(x));
const cellsOf = html => [...html.matchAll(/<tr class="team-row">([\s\S]*?)<\/tr>/g)].map(m => {
  const nums = [...m[1].matchAll(/<td class="num[^"]*">([\s\S]*?)<\/td>/g)].map(x => x[1].replace(/<[^>]+>/g, '').trim());
  return { name: (m[1].match(/class="team-name">([^<]*)</) || [])[1], nums };
});
const stats = html => Object.fromEntries([...html.matchAll(/data-stat="(\w+)"><b[^>]*>([^<]*)<\/b>/g)].map(m => [m[1], m[2]]));
// A profile of A whose first `n` roster players are from MVLA (and the first of them also from Rocklin High).
function profileA(n) {
  const prof = readJson(`data/programs/${A.slug}.json`), pl = prof.roster.players;
  assert.ok(pl.length >= 5, 'A needs five roster players');
  pl.forEach(p => { delete p.clubInfo; delete p.schoolInfo; });
  for (let i = 0; i < n; i++) { pl[i].club = 'Mountain View Los Altos SC'; pl[i].clubInfo = { raw: 'MVLA', key: 'mvla', clubId: 'mvla', club: 'Mountain View Los Altos SC', status: 'matched' }; }
  pl[0].schoolInfo = { schoolId: 'ccd:1' };
  pl[4].schoolInfo = { schoolId: 'ccd:1' }; // Rocklin, but no club: not a player "with both"
  prof.pastRosters = [{ season: 2025, players: [{ name: 'PAST PERSON', clubInfo: { clubId: 'mvla', status: 'matched' } }] }];
  prof.commitments = [{ name: 'RECRUIT PERSON', club: 'Mountain View Los Altos SC', clubInfo: { clubId: 'mvla', status: 'matched' } }];
  return prof;
}
const nameOf = (pl) => `${pl.name}${pl.pos || pl.classCode ? ` (${[pl.pos, pl.classCode].filter(Boolean).join(', ')})` : ''}`;

/* ---------- pure functions ---------- */
test('pure functions: programs_for, feeders_for and both_for, by hand from the fixture; commits never enter the total or the order', async () => {
  const page = loadPage({}), doc = fixture({ schools: true });
  const rows = plain(page.sandbox.trendsProgramsFor(doc, 'club', 'mvla'));
  assert.deepEqual(rows, [{ slug: B.slug, current: 2, past: 2, commits: 1 }, { slug: A.slug, current: 3, past: 0, commits: 0 }, { slug: C.slug, current: 0, past: 0, commits: 5 }],
    'B (4 people) before A (3) before C (0 people, 5 commits)');
  const feeders = plain(page.sandbox.trendsFeedersFor(doc, 'club', A.slug));
  assert.deepEqual(feeders.map(f => [f.id, f.current, f.past, f.commits, f.unmatched]),
    [['mvla', 3, 0, 0, false], ['surf', 1, 0, 3, false], ['raw:zeta united', 1, 0, 0, true]], 'MVLA (3 people) before Surf (1 person, 3 commits)');
  assert.deepEqual(plain(page.sandbox.trendsBothFor(doc, 'mvla', 'ccd:1')), [{ slug: A.slug, club: 3, school: 3 }, { slug: B.slug, club: 4, school: 1 }],
    'club + school: only programs with both; club players = cur + past (commits left out)');
  assert.deepEqual(plain(page.sandbox.trendsCoverageLines(doc, 'club', { current: 5, past: 2, commits: 6 })),
    ['5 of 100 current players; club known for 31%', '2 of 200 former players (stored past rosters); club known for 15%', '6 of 50 verbal or signed commits; club known for 98%']);
  assert.deepEqual(plain(page.sandbox.trendsProgramsFor(doc, 'school', 'ccd:1')), [{ slug: A.slug, current: 2, past: 1, commits: null }, { slug: B.slug, current: 1, past: 0, commits: null }], 'a school reports commits as null, never 0');
});

/* ---------- URL ---------- */
test('#310 URL: parse and serialise round-trip in a fixed order; a raw: id survives encodeURIComponent', async () => {
  const { sandbox } = loadPage({});
  assert.equal(sandbox.trendsUrl({ program: 'stanford', club: 'mvla', school: 'ccd:1' }), '#/trends?club=mvla&school=ccd%3A1&program=stanford');
  assert.equal(sandbox.trendsUrl({}), '#/trends');
  const raw = sandbox.trendsUrl({ club: 'raw:zeta & sons united' });
  assert.equal(raw, '#/trends?club=raw%3Azeta%20%26%20sons%20united', 'the & and the : are encoded, so the id cannot split the query');
  assert.deepEqual(plain(sandbox.trendsParse(raw)), { club: 'raw:zeta & sons united' });
  assert.deepEqual(plain(sandbox.trendsParse('#/trends?school=ccd%3A1&program=stanford&bogus=1')), { school: 'ccd:1', program: 'stanford' });
});

test('#310 old links: the three path forms redirect with replaceState (not a push); no old-form link is left in the page', async () => {
  for (const [old, now] of [['#/trends/club/mvla', '#/trends?club=mvla'], ['#/trends/school/ccd%3A1', '#/trends?school=ccd%3A1'], [`#/trends/program/${A.slug}`, `#/trends?program=${A.slug}`]]) {
    const page = await open(old, fixture({ schools: true }));
    assert.equal(page.sandbox.location.hash, now, `${old} -> ${now}`);
    assert.deepEqual([page.hist.replaces, page.hist.pushes], [1, 0], `${old}: one replaceState, no pushState`);
  }
  const src = fs.readFileSync(HTML, 'utf8');
  assert.equal(src.match(/#\/trends\/(club|school|program)\//g), null, 'the page source still produces an old-form trends link');
  // the four producers: the roster club cell, the profile's "players come from" link, table rows and the program box
  const page = await open('#/trends?program=' + A.slug);
  assert.equal(page.sandbox.trendsClubCell({ division: 'D1' }, { club: 'MVLA', clubInfo: { status: 'matched', clubId: 'mvla' } }),
    '<a href="#/trends?club=mvla" title="Which programs have players from MVLA">MVLA</a>');
  assert.ok(page.results().includes(`href="#/trends?club=mvla&amp;program=${A.slug}"`), 'a feeder row links to the club + program card');
});

test('#310 raw: ids: a spelling since reviewed into a club resolves through the alias table; an unknown one reads "not in the index"', async () => {
  let page = await open('#/trends?club=raw%3Amtn%20view%20los%20altos%20sc');
  assert.equal(page.sandbox.location.hash, '#/trends?club=mvla', 'rewritten to the club id');
  assert.equal(page.hist.pushes, 0, 'with replaceState');
  assert.equal(page.el('#trChg-club').textContent, 'Mountain View Los Altos SC');
  page = await open('#/trends?club=raw%3Azeta%20united');
  assert.equal(page.sandbox.location.hash, '#/trends?club=raw%3Azeta%20united', 'an id the index carries is left alone');
  assert.ok(page.results().includes('unmatched spelling'));
  page = await open('#/trends?club=raw%3Aqqq');
  assert.equal(page.el('#trChg-club').textContent, 'raw:qqq — not in the index');
  assert.ok(page.el('#trChip-club').classList.contains('missing'));
  assert.ok(page.results().includes('There is no club “raw:qqq” in the clubs and schools index') && page.results().includes('How to read this'), 'results come from the other selections (none)');
});

test('#310 D2 program in the URL: a "not in the index" chip; the Program box only searches the index (D1)', async () => {
  const page = await open(`#/trends?club=mvla&program=${D2.slug}`, searchFixture());
  assert.equal(page.el('#trChg-program').textContent, `${disp(D2)} (D2) — not in the index`);
  assert.equal(page.el('#trChg-program').getAttribute('aria-label'), `Change program: ${disp(D2)} (D2) — not in the index`);
  assert.ok(page.results().includes('is a Division II program, and the clubs and schools index covers Division I only'));
  assert.deepEqual(cellsOf(page.results()).map(r => r.name), [disp(B), disp(A), disp(C)], 'results come from the club alone');
  const p2 = await open('#/trends', searchFixture());
  type(p2, 'program', D2.shortName);
  assert.equal(p2.el('#trMsg-program').textContent, `No program matches “${D2.shortName}”.`, 'a D2 program is not offered even though the fixture index carries it');
});

/* ---------- the tab's name (#322) ---------- */
test('the tab and the breadcrumb read "Pipelines"; the page title and the #/trends URL are unchanged', async () => {
  const page = await open('#/trends');
  const html = page.app();
  const tabs = [...html.matchAll(/<a href="([^"]*)" class="view-tab[^"]*"[^>]*>([^<]*)<\/a>/g)];
  const tab = tabs.find(m => m[1] === '#/trends');
  assert.ok(tab, 'the tab still links to #/trends');
  assert.equal(tab[2], 'Pipelines');
  assert.ok(tab[0].includes('aria-selected="true"'), 'and is the selected tab');
  assert.ok(!/Clubs &amp; schools|Clubs &amp; high schools|Clubs & high schools/.test(html), 'no old label left on the page');
  assert.ok(/class="breadcrumb-current"[^>]*>Pipelines</.test(html), 'the breadcrumb reads Pipelines');
  assert.ok(html.includes('Where players come from'), 'the page title is kept');
});

/* ---------- states ---------- */
test('state 1, nothing selected: three boxes, the how-to card and the coverage', async () => {
  const page = await open('#/trends');
  const html = page.app();
  assert.ok(html.includes('class="view-tab active" role="tab" aria-selected="true">Pipelines</a>'), 'the Pipelines tab is active');
  for (const k of ['club', 'program']) assert.ok(html.includes(`<label class="trend-label" id="trLbl-${k}" for="trIn-${k}">`) && html.includes(`id="trIn-${k}" type="text" role="combobox"`), `${k}: a labelled combobox`);
  assert.ok(html.includes('High-school results are not published yet'), 'schools absent: the school box says so');
  assert.ok(page.results().includes('100 current players; club known for 31%') && page.results().includes('never added into a program'));
  assert.ok(page.sub().startsWith('Clubs and high schools behind Division I rosters · Division I'));
});

test('state 2, club only: programs it feeds, Players = current + past, commits beside and never in Players', async () => {
  const page = await open('#/trends?club=mvla');
  const html = page.results();
  assert.deepEqual(cellsOf(html).map(r => r.name), [disp(B), disp(A), disp(C)], 'most people first; commits do not lift C');
  assert.deepEqual(cellsOf(html).map(r => r.nums), [['4', '2', '2', '1'], ['3', '3', '0', '0'], ['0', '0', '0', '5']]);
  assert.ok(html.includes('5 of 100 current players; club known for 31%') && html.includes('6 of 50 verbal or signed commits; club known for 98%'));
  assert.ok(html.includes(`data-slug="${A.slug}" data-kind="club" data-id="mvla"`) && !html.includes(`data-slug="${C.slug}"`), 'the roster expander only where there are current players');
  assert.ok(html.includes(`href="#/trends?club=mvla&amp;program=${B.slug}" data-tr-kind="program"`), 'each row links to the club + program card');
  assert.ok(page.sub().startsWith('Mountain View Los Altos SC · Division I'), 'the header names the club');
});

test('state 3, high school only: commits read "—", never 0', async () => {
  const page = await open('#/trends?school=ccd%3A1', fixture({ schools: true }));
  assert.deepEqual(cellsOf(page.results()).map(r => r.nums), [['3', '2', '1', '—'], ['1', '1', '0', '—']]);
  assert.ok(page.results().includes('3 of 100 current players; high school known for 40%'));
});

test('state 4, program only: clubs and high schools feeding it; rows link to the pair cards', async () => {
  const page = await open(`#/trends?program=${A.slug}`, fixture({ schools: true }));
  const html = page.results();
  assert.ok(html.includes(`Clubs feeding ${disp(A)}`) && html.includes(`High schools feeding ${disp(A)}`));
  const m = html.indexOf(`?club=mvla&amp;program=${A.slug}`), s = html.indexOf(`?club=surf&amp;program=${A.slug}`);
  assert.ok(m > 0 && s > m, 'MVLA (3 people) before Surf (1 person, 3 commits)');
  assert.ok(html.includes(`?club=raw%3Azeta%20united&amp;program=${A.slug}`) && html.includes('unmatched spelling'));
  assert.ok(html.includes(`?school=ccd%3A1&amp;program=${A.slug}`));
  assert.ok(html.includes('27 current players; club known for 19 (70%)'));
});

test('state 5, club + program: one card, commits never enter Players; names equal the current count', async () => {
  let page = await open(`#/trends?club=mvla&program=${B.slug}`);
  assert.deepEqual(stats(page.results()), { players: '4', current: '2', past: '2', commits: '1' }, 'Players 4 = 2 current + 2 past; the 1 commit is not in it');
  assert.ok(page.results().includes('Past players and commits are counted, never named.'));
  page = await open(`#/trends?club=mvla&program=${C.slug}`);
  assert.deepEqual(stats(page.results()), { players: '0', current: '0', past: '0', commits: '5' }, 'five commits and no player: Players stays 0');
  assert.ok(!page.results().includes('id="trNames"'), 'no current players, so nobody is named');
  // A: 3 current players from MVLA in the index, and 3 on the roster
  const prof = profileA(3);
  page = await open(`#/trends?club=mvla&program=${A.slug}`, fixture(), { [`data/programs/${A.slug}.json`]: prof });
  await tick(30);
  const names = page.el('#trNames').innerHTML;
  assert.ok(names.startsWith('<b>Current players (3):</b>'), 'three names for Current 3');
  for (const pl of prof.roster.players.slice(0, 3)) assert.ok(names.includes(nameOf(pl).replace(/&/g, '&amp;').replace(/'/g, '&#39;')) || names.includes(pl.name), `${pl.name} is listed`);
  assert.ok(!names.includes(prof.roster.players[3].name + ' (') && !names.includes('PAST PERSON') && !names.includes('RECRUIT PERSON'), 'no other roster player, past player or recruit');
  assert.ok(!names.includes('The public roster names'), 'counts agree: no mismatch line');
  // the mismatch the test must catch: the roster names 2 where the index counted 3
  page = await open(`#/trends?club=mvla&program=${A.slug}`, fixture(), { [`data/programs/${A.slug}.json`]: profileA(2) });
  await tick(30);
  assert.ok(page.el('#trNames').innerHTML.startsWith('<b>Current players (2):</b>') && page.el('#trNames').innerHTML.includes('The public roster names 2 of the 3 current players the index counted'),
    'a roster that disagrees with the index is said so, not hidden');
});

test('state 6, high school + program: Commits "—"', async () => {
  const page = await open(`#/trends?school=ccd%3A1&program=${A.slug}`, fixture({ schools: true }));
  assert.deepEqual(stats(page.results()), { players: '3', current: '2', past: '1', commits: '—' });
});

test('state 7, club + high school (option A): programs drawing from both, counts side by side, the caveat above the table', async () => {
  const page = await open('#/trends?club=mvla&school=ccd%3A1', fixture({ schools: true }));
  const html = page.results();
  assert.ok(html.indexOf('Not necessarily the same players.') >= 0 && html.indexOf('Not necessarily the same players.') < html.indexOf('<table'), 'the caveat is above the table');
  assert.ok(html.includes('>From this club<') && html.includes('>From this school<'));
  const rows = [...html.matchAll(/<tr class="team-row">([\s\S]*?)<\/tr>/g)].map(m => [(m[1].match(/class="team-name">([^<]*)</) || [])[1], ...[...m[1].matchAll(/<td class="num">(?:<span class="num-strong">)?(\d+)/g)].map(x => x[1])]);
  assert.deepEqual(rows, [[disp(A), '3', '3'], [disp(B), '4', '1']], 'A: 3 from the club and 3 from the school; B: 4 and 1');
  assert.equal(page.sub().split(' · ')[0], 'Mountain View Los Altos SC × Rocklin High');
});

test('state 8, club + school + program: current players with both, named from the roster; past and commits "—"', async () => {
  const prof = profileA(3);
  const page = await open(`#/trends?club=mvla&school=ccd%3A1&program=${A.slug}`, fixture({ schools: true }), { [`data/programs/${A.slug}.json`]: prof });
  await tick(30);
  assert.deepEqual(stats(page.results()), { both: '…', past: '—', commits: '—' });
  assert.equal(page.el('#trCurBoth').textContent, '1', 'one roster player has MVLA and Rocklin High');
  const names = page.el('#trNames').innerHTML;
  assert.ok(names.startsWith('<b>Current players (1):</b>') && names.includes(prof.roster.players[0].name));
  assert.ok(!names.includes(prof.roster.players[1].name) && !names.includes(prof.roster.players[4].name), 'club only or school only is not "with both"');
});

test('a missing index renders "Not built yet", not an empty table', async () => {
  const page = await open('#/trends?club=mvla', null);
  assert.ok(page.app().includes('Not built yet') && !page.app().includes('<table'));
});

/* ---------- picking, clearing, typing, history ---------- */
test('#310 picks and clears: pushState, update in place, chips with named buttons, focus to the chip and back to the box', async () => {
  const page = await open('#/trends', searchFixture());
  page.el('#main').scrollTop = 500;
  const before = page.results();
  // typing changes nothing but the list
  type(page, 'club', 'mvla');
  assert.deepEqual([page.results(), page.sandbox.location.hash, page.hist.pushes], [before, '#/trends', 0], 'typing leaves the results and the URL alone');
  // Enter picks the first option
  assert.ok(key(page, 'club', 'Enter'));
  assert.equal(page.sandbox.location.hash, '#/trends?club=mvla');
  assert.equal(page.hist.pushes, 1, 'one history entry per pick');
  assert.equal(page.el('#main').scrollTop, 500, 'no jump to the top');
  assert.equal(page.el('#trChip-club').hidden, false); assert.equal(page.el('#trIn-club').hidden, true);
  assert.equal(page.el('#trChg-club').getAttribute('aria-label'), 'Change club: Mountain View Los Altos SC');
  assert.equal(page.el('#trClr-club').getAttribute('aria-label'), 'Clear club: Mountain View Los Altos SC');
  assert.equal(page.el('#trChg-club').title, 'Mountain View Los Altos SC', 'the full name stays in the title when the chip is cut short');
  assert.equal(page.sandbox.document.activeElement, page.el('#trChg-club'), 'focus goes to the chip after a pick');
  assert.equal(page.el('#trLive').textContent, 'Mountain View Los Altos SC: 3 programs with players from this club.', 'the result is announced');
  // a second pick through a results link
  const a = { dataset: { trKind: 'program', trId: B.slug } };
  page.el('#trResults').onclick({ target: { closest: () => a }, preventDefault() { } });
  assert.equal(page.sandbox.location.hash, `#/trends?club=mvla&program=${B.slug}`);
  assert.equal(page.sandbox.document.activeElement, page.el('#trChg-program'));
  assert.equal(page.el('#trLive').textContent, `${disp(B)}: 4 players from Mountain View Los Altos SC.`);
  assert.ok(page.sub().startsWith(`Mountain View Los Altos SC × ${disp(B)} · `), 'the header names both');
  // clear only the club
  click(page.el('#trClr-club'));
  assert.equal(page.sandbox.location.hash, `#/trends?program=${B.slug}`, '✕ clears only that selection');
  assert.equal(page.sandbox.document.activeElement, page.el('#trIn-club'), 'focus goes to the now-empty box');
  assert.equal(page.el('#trIn-club').hidden, false);
  assert.ok(page.sub().startsWith(`${disp(B)} · `));
  // Back twice: the club + program, then the club alone
  page.sandbox.history.back(); await page.sandbox.route(); await tick();
  assert.equal(page.sandbox.location.hash, `#/trends?club=mvla&program=${B.slug}`);
  assert.deepEqual(stats(page.results()).players, '4');
  page.sandbox.history.back(); await page.sandbox.route(); await tick();
  assert.equal(page.el('#trChg-club').textContent, 'Mountain View Los Altos SC');
  assert.equal(page.el('#trChip-program').hidden, true, 'Back undid the program pick');
  assert.deepEqual(cellsOf(page.results()).map(r => r.name), [disp(B), disp(A), disp(C)]);
  assert.equal(page.el('#main').scrollTop, 500, 'Back re-renders in place, without a jump to the top');
});

test('#310 keyboard: one listbox of options (not tab stops), arrows, Enter, Escape restores the chip, Tab leaves without picking', async () => {
  const page = await open('#/trends?club=surf', searchFixture());
  page.el('#trIn-club').onfocus(); // the empty box would open on focus; the chip is showing here, so re-edit first
  click(page.el('#trChg-club'));
  assert.equal(page.el('#trIn-club').hidden, false, 'Change opens the box');
  assert.equal(page.sandbox.document.activeElement, page.el('#trIn-club'));
  const list = page.el('#trList-club').innerHTML;
  assert.equal((list.match(/role="option"/g) || []).length, 11, '11 suggestions: MVLA, Surf and Club 1-9');
  assert.ok(!/<a |<button|tabindex/.test(list), 'options are not tab stops');
  assert.equal(page.el('#trIn-club').getAttribute('aria-expanded'), 'true');
  key(page, 'club', 'ArrowDown'); key(page, 'club', 'ArrowDown');
  assert.equal(page.el('#trIn-club').getAttribute('aria-activedescendant'), 'trOpt-club-1');
  assert.equal(page.el('#trOpt-club-1').getAttribute('aria-selected'), 'true');
  key(page, 'club', 'ArrowUp'); key(page, 'club', 'ArrowUp');
  assert.equal(page.el('#trIn-club').getAttribute('aria-activedescendant'), `trOpt-club-10`, 'ArrowUp wraps to the last');
  assert.equal(key(page, 'club', 'Tab'), false, 'Tab is not swallowed');
  assert.equal(page.sandbox.location.hash, '#/trends?club=surf', 'Tab picks nothing');
  assert.ok(key(page, 'club', 'Escape'));
  assert.equal(page.el('#trChip-club').hidden, false, 'Escape puts the chip back');
  assert.equal(page.el('#trChg-club').textContent, 'San Diego Surf', 'with the old selection');
  assert.equal(page.sandbox.document.activeElement, page.el('#trChg-club'));
  // re-edit, type, pick with the mouse
  click(page.el('#trChg-club'));
  type(page, 'club', 'zzqx');
  assert.equal(page.el('#trMsg-club').textContent, 'No club matches “zzqx”. Still showing San Diego Surf; pick another to change it.');
  assert.equal(page.el('#trLive').textContent, 'No club matches “zzqx”. Still showing San Diego Surf; pick another to change it.', 'no match is announced');
  assert.ok(page.sub().startsWith('San Diego Surf · '), 'the header still names the selection');
  type(page, 'club', 'mountain');
  page.el('#trList-club').onclick({ target: { closest: () => ({ dataset: { i: '0' } }) } });
  assert.equal(page.sandbox.location.hash, '#/trends?club=mvla');
  // the step function behind the arrows
  const k = (at, kk, n) => plain(page.sandbox.trendsKeyStep(at, kk, n));
  assert.deepEqual([k(-1, 'ArrowDown', 3), k(2, 'ArrowDown', 3), k(-1, 'Enter', 3), k(-1, 'Enter', 0)], [{ at: 0 }, { at: 0 }, { at: -1, go: 0 }, { at: -1 }]);
});

/* ---------- #307 matching, inside the new boxes ---------- */
test('#307 matching: club aliases, school spellings and same-name schools, programs by name, nickname and short name', async () => {
  const page = await open('#/trends', searchFixture());
  for (const q of ['mvla', 'MVLA', 'mountain view', 'Mtn View']) {
    type(page, 'club', q);
    assert.deepEqual(plain(optIds(page, 'club')), ['mvla'], `"${q}" finds only MVLA`);
  }
  assert.ok(type(page, 'club', 'MVLA').includes('also known as MVLA'));
  assert.ok(!type(page, 'club', 'mountain view').includes('also known as'));
  type(page, 'club', 'rocklin');
  assert.equal(page.el('#trMsg-club').textContent, 'No club matches “rocklin”.', 'the club box finds clubs only');
  type(page, 'school', 'rocklin'); assert.deepEqual(plain(optIds(page, 'school')), ['ccd:1']);
  const carroll = type(page, 'school', 'Southlake Carroll');
  assert.ok(carroll.includes('>Carroll Senior H S<') && carroll.includes('also known as Southlake Carroll'));
  const dec = type(page, 'school', 'decatur high');
  assert.ok(dec.includes('Decatur, AL') && dec.includes('Decatur, GA'), 'two same-name schools, told apart by city and state');
  type(page, 'program', 'stanford'); assert.equal(optIds(page, 'program')[0], 'stanford');
  const card = type(page, 'program', 'cardinal');
  assert.deepEqual(plain(optIds(page, 'program')), ['stanford', 'louisville'], '"cardinal": Stanford first by its exact nickname, only nickname matches');
  assert.ok(card.includes('· Cardinal</span>') && card.includes('<span class="div-tag"'), 'the division line and the reason');
  type(page, 'program', 'UNC Wil'); assert.equal(optIds(page, 'program')[0], 'unc-wilmington');
});

test('#310 suggestions follow the other selections; 6 in an empty box on phones, 12 on desktop', async () => {
  let page = await open(`#/trends?program=${B.slug}`, searchFixture());
  type(page, 'club', ''); assert.deepEqual(plain(optIds(page, 'club')), ['mvla'], 'clubs feeding B');
  type(page, 'school', ''); assert.deepEqual(plain(optIds(page, 'school')), ['ccd:4', 'ccd:1'], 'schools feeding B (1 player each: by name, Decatur before Rocklin)');
  assert.ok(page.el('#trList-club').innerHTML.includes(`4 players at ${disp(B)}`));
  page = await open('#/trends?club=surf', searchFixture());
  type(page, 'program', ''); assert.deepEqual(plain(optIds(page, 'program')), [A.slug], 'programs Surf feeds');
  const count = async phone => {
    const p = loadPage({ 'data/trends/index.json': searchFixture() });
    p.sandbox.matchMedia = q => ({ matches: phone && q === '(max-width: 480px)' });
    p.sandbox.location.hash = '#/trends'; await p.sandbox.route(); await tick();
    type(p, 'club', ''); type(p, 'program', '');
    const empty = [optIds(p, 'club').length, optIds(p, 'program').length];
    type(p, 'club', 'club');
    return [...empty, optIds(p, 'club').length];
  };
  assert.equal(new Set([A.slug, B.slug, C.slug, 'stanford', 'north-carolina', 'unc-wilmington', 'louisville']).size, 6, 'premise: the committed index makes B Stanford, so the fixture has 6 D1 programs');
  assert.deepEqual(await count(false), [11, 6, 9], 'desktop: 11 clubs, the 6 D1 programs of the fixture; "club" finds 9');
  assert.deepEqual(await count(true), [6, 6, 9], 'phone: 6 in each empty box; a typed query is not cut to 6');
});

test('#310 sidebar filters never hide a picked program', async () => {
  const other = INDEX.programs.find(p => p.division === 'D1' && p.conference && ![A, B, C].some(q => q.conference === p.conference)).conference;
  const page = loadPage({ 'data/trends/index.json': fixture() });
  page.sandbox.S.filters.conf = [other];
  page.sandbox.location.hash = `#/trends?club=mvla&program=${A.slug}`; await page.sandbox.route(); await tick();
  assert.deepEqual(stats(page.results()), { players: '3', current: '3', past: '0', commits: '0' }, 'the card still shows');
  assert.ok(page.results().includes(`${disp(A).replace(/&/g, '&amp;').replace(/'/g, '&#39;')} is outside your sidebar filters; it is shown because you picked it.`));
  page.sandbox.location.hash = '#/trends?club=mvla'; await page.sandbox.route(); await tick();
  assert.deepEqual(cellsOf(page.results()), [], 'unpicked program rows are still filtered');
  assert.ok(page.results().includes('3 programs with these players are hidden by your sidebar filters.'));
});

/* ---------- the rest of the site ---------- */
test('the list view offers the tab; the roster tab links a reviewed club and the program to the new URL form', async () => {
  const page = await open('#/');
  assert.ok(page.app().includes('href="#/trends"'));
  const prof = profileA(1);
  prof.roster.players[1].club = 'Zeta United'; prof.roster.players[1].clubInfo = { raw: 'Zeta United', key: 'zeta united', clubId: null, club: null, status: 'unmatched' };
  const p2 = await open(`#/p/${A.slug}/roster`, fixture(), { [`data/programs/${A.slug}.json`]: prof });
  await tick(30);
  assert.ok(p2.tab().includes('href="#/trends?club=mvla"'), 'a matched club links to its trends page');
  assert.ok(!p2.tab().includes('club=raw'), 'an unmatched spelling does not');
  assert.ok(p2.tab().includes(`href="#/trends?program=${A.slug}"`), 'the roster tab links to where the program\'s players come from');
  assert.deepEqual(plain(p2.sandbox.trendsRosterNames({ roster: null, commitments: prof.commitments }, 'club', 'mvla')), [], 'commitments are never a source of names');
  const d2 = JSON.parse(JSON.stringify(prof)); d2.division = 'D2';
  const p3 = await open(`#/p/${A.slug}/roster`, fixture(), { [`data/programs/${A.slug}.json`]: d2 });
  await tick(30);
  assert.ok(!p3.tab().includes('#/trends'), 'a D2 roster carries no trends link');
});
