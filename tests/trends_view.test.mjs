// The clubs & high-schools view, #/trends (issues #230, #307, #310, #315, #327).
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
const D3 = INDEX.programs.find(p => p.division === 'D3' && p.shortName);

/* ---------- the fixture index (#327 records): counts only ----------
   One record per counted person, [program, status (0 current, 1 former, 2 commit), club, school]:
     A: current (mvla, rocklin) (mvla, -) (mvla, -) (surf, -) (zeta, -) (-, rocklin); past (-, rocklin); commits surf x3
     B: current (mvla, rocklin) (mvla, -); past (mvla, -) (mvla, -) (mx, -); commits (mvla, -)
     C: commits mvla x5
     D2: current (lone, -); past (lone, -)
   So, by hand: mvla A [3,0,0], B [2,2,1], C [0,0,5]; surf A [1,0,3]; zeta A [1,0,0]; mx B [0,1,0]; lone D2 [1,1,-];
   rocklin A [2,1,-], B [1,0,-]; mvla AND rocklin: A 1 current, B 1 current. */
function build(people, { schools = true, clubsDir, schoolsDir } = {}) {
  const programIds = [A.slug, B.slug, C.slug, D2.slug].sort();
  const cl = clubsDir || { id: ['lone', 'mvla', 'mx', 'raw:zeta united', 'surf'], name: ['Lone Star FC', 'Mountain View Los Altos SC', 'MX United', 'Zeta United', 'San Diego Surf'],
    state: ['TX', 'CA', 'CA', null, 'CA'], unmatched: [3], aka: { 1: ['mvla', 'mtn view los altos sc'] } };
  const sc = schoolsDir || { id: ['ccd:1'], name: ['Rocklin High'], city: ['Rocklin'], state: ['CA'], aka: {} };
  const rows = people.filter(([, , c, h]) => c || (schools && h)).map(([slug, s, c, h]) => [programIds.indexOf(slug), s, c ? cl.id.indexOf(c) : -1, schools && h ? sc.id.indexOf(h) : -1])
    .sort((x, y) => x[0] - y[0] || x[1] - y[1] || x[2] - y[2] || x[3] - y[3]);
  return { programIds, clubs: cl, schools: schools ? sc : null, records: { p: rows.map(r => r[0]), s: rows.map(r => r[1]), c: rows.map(r => r[2]), h: rows.map(r => r[3]) } };
}
const times = (n, row) => Array.from({ length: n }, () => row);
function people() {
  return [[A.slug, 0, 'mvla', 'ccd:1'], [A.slug, 0, 'mvla', null], [A.slug, 0, 'mvla', null], [A.slug, 0, 'surf', null], [A.slug, 0, 'raw:zeta united', null], [A.slug, 0, null, 'ccd:1'],
    [A.slug, 1, null, 'ccd:1'], ...times(3, [A.slug, 2, 'surf', null]),
    [B.slug, 0, 'mvla', 'ccd:1'], [B.slug, 0, 'mvla', null], [B.slug, 1, 'mvla', null], [B.slug, 1, 'mvla', null], [B.slug, 1, 'mx', null], [B.slug, 2, 'mvla', null],
    ...times(5, [C.slug, 2, 'mvla', null]),
    [D2.slug, 0, 'lone', null], [D2.slug, 1, 'lone', null]];
}
function fixture({ schools = false, extra = [] } = {}) {
  const d1 = { current: { players: 100, clubKnown: 31, schoolNamed: 65, schoolKnown: schools ? 40 : null },
               past: { players: 200, clubKnown: 30, schoolNamed: 120, schoolKnown: schools ? 50 : null },
               commits: { recruits: 50, clubKnown: 49, schoolNamed: 10, schoolKnown: null } };
  const d2 = { current: { players: 50, clubKnown: 3, schoolNamed: 40, schoolKnown: schools ? 20 : null },
               past: { players: 60, clubKnown: 2, schoolNamed: 50, schoolKnown: schools ? 25 : null }, commits: null };
  return {
    updated: '2026-09-17T00:00:00Z', format: 'records', divisions: ['D1', 'D2'], commitDivisions: ['D1'], season: 2026, pastSeasons: [2023, 2024, 2025],
    commitStatuses: ['verbal', 'signed'], columns: ['current', 'past', 'commits'],
    coverage: { current: { players: 150, clubKnown: 34, schoolNamed: 105, schoolKnown: schools ? 60 : null },
                past: { players: 260, clubKnown: 32, schoolNamed: 170, schoolKnown: schools ? 75 : null },
                commits: d1.commits, byDivision: { D1: d1, D2: d2 } },
    programs: { [A.slug]: { division: 'D1', current: 27, past: 29, commits: 11, clubKnown: [19, 1, 11], schoolKnown: schools ? [5, 2, 0] : [0, 0, 0] },
                [B.slug]: { division: 'D1', current: 25, past: 20, commits: 9, clubKnown: [10, 2, 9], schoolKnown: [0, 0, 0] },
                [C.slug]: { division: 'D1', current: 30, past: 10, commits: 2, clubKnown: [3, 0, 2], schoolKnown: [0, 0, 0] },
                [D2.slug]: { division: 'D2', current: 20, past: 15, commits: null, clubKnown: [2, 1, null], schoolKnown: [0, 0, null] } },
    ...build([...people(), ...extra], { schools }),
  };
}
// #307 search data on top: school spellings, two same-name schools, more programs and clubs.
function searchFixture() {
  const doc = fixture({ schools: true });
  const extraProgs = ['stanford', 'north-carolina', 'unc-wilmington', 'louisville'];
  for (const s of extraProgs) doc.programs[s] = { division: 'D1', current: 3, past: 1, commits: 0, clubKnown: [1, 0, 0], schoolKnown: [0, 0, 0] };
  doc.programs.louisville.current = 9; // more players than Stanford: only the exact nickname can put Stanford first for "cardinal"
  const cl = { ...doc.clubs, id: [...doc.clubs.id], name: [...doc.clubs.name], state: [...doc.clubs.state] };
  for (let i = 1; i <= 9; i++) { cl.id.push(`c${i}`); cl.name.push(`Club ${i}`); cl.state.push('CA'); }
  const sc = { id: ['ccd:1', 'ccd:2', 'ccd:3', 'ccd:4'], name: ['Rocklin High', 'Carroll Senior H S', 'Decatur High School', 'Decatur High School'],
    city: ['Rocklin', 'Southlake', 'Decatur', 'Decatur'], state: ['CA', 'TX', 'AL', 'GA'], aka: { 1: ['southlake carroll'] } };
  const extra = [[A.slug, 0, null, 'ccd:2'], [A.slug, 0, null, 'ccd:3'], [B.slug, 0, null, 'ccd:4'], ...Array.from({ length: 9 }, (_, i) => [A.slug, 0, `c${i + 1}`, null])];
  const programIds = [...new Set([...doc.programIds, ...extraProgs])].sort();
  const all = [...people(), ...extra];
  const rows = all.map(([slug, s, c, h]) => [programIds.indexOf(slug), s, c ? cl.id.indexOf(c) : -1, h ? sc.id.indexOf(h) : -1]).sort((x, y) => x[0] - y[0] || x[1] - y[1] || x[2] - y[2] || x[3] - y[3]);
  return { ...doc, programIds, clubs: cl, schools: sc, records: { p: rows.map(r => r[0]), s: rows.map(r => r[1]), c: rows.map(r => r[2]), h: rows.map(r => r[3]) } };
}
// #230's cell file, as the committed index is until the first refresh after #327: the page must still read it.
function cellFixture() {
  const doc = fixture({ schools: true });
  const cells = {};
  const r = doc.records;
  for (let i = 0; i < r.p.length; i++) {
    const slug = doc.programIds[r.p[i]];
    if (r.c[i] >= 0) { const id = doc.clubs.id[r.c[i]]; ((cells.c ||= {})[id] ||= {})[slug] ||= [0, 0, 0]; cells.c[id][slug][r.s[i]]++; }
    if (r.h[i] >= 0) { const id = doc.schools.id[r.h[i]]; ((cells.h ||= {})[id] ||= {})[slug] ||= [0, 0, 0]; cells.h[id][slug][r.s[i]]++; }
  }
  const clubs = Object.fromEntries(doc.clubs.id.map((id, i) => [id, { name: doc.clubs.name[i], state: doc.clubs.state[i], ...(doc.clubs.unmatched.includes(i) ? { unmatched: true } : {}), programs: cells.c[id] || {} }]));
  const schools = Object.fromEntries(doc.schools.id.map((id, i) => [id, { name: doc.schools.name[i], city: doc.schools.city[i], state: doc.schools.state[i], programs: cells.h[id] || {} }]));
  const { records, programIds, format, ...rest } = doc;
  return { ...rest, clubs, schools };
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
    + '\n;Object.assign(globalThis, { S, route, renderProfile, trendsQuery, trendsFeeders, trendsCoverageLines, trendsRosterNames, listTabs, trendsKeyStep, trendsParse, trendsParseLink, trendsUrl, trendsClubCell, trState: () => TR });\n';
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
const chipNames = (page, kind) => [...page.el(`#trChips-${kind}`).innerHTML.matchAll(/aria-label="Remove [^:]+: ([^"]*)"/g)].map(m => m[1]);
const add = (page, kind, text, i = 0) => { type(page, kind, text); const o = page.sandbox.trState().opts[kind][i]; assert.ok(o, `no option for "${text}"`); page.el(`#trList-${kind}`).onclick({ target: { closest: () => ({ dataset: { i: String(i) } }) } }); return o.id; };
const removeChip = (page, kind, i) => page.el(`#trChips-${kind}`).onclick({ target: { closest: () => ({ dataset: { i: String(i) } }) } });

/* ---------- the query ---------- */
test('pure functions: trendsQuery and trendsFeeders by hand from the fixture; commits never enter the total or the order', async () => {
  const page = loadPage({}), doc = fixture({ schools: true }), s = page.sandbox;
  assert.deepEqual(plain(s.trendsQuery(doc, { club: ['mvla'] })).map(r => [r.slug, r.current, r.past, r.commits]),
    [[B.slug, 2, 2, 1], [A.slug, 3, 0, 0], [C.slug, 0, 0, 5]], 'B (4 people) before A (3) before C (0 people, 5 commits)');
  assert.deepEqual(plain(s.trendsFeeders(doc, 'club', { program: [A.slug] })).map(f => [f.id, f.current, f.past, f.commits, f.unmatched]),
    [['mvla', 3, 0, 0, false], ['surf', 1, 0, 3, false], ['raw:zeta united', 1, 0, 0, true]], 'MVLA (3 people) before Surf (1 person, 3 commits)');
  assert.deepEqual(plain(s.trendsQuery(doc, { school: ['ccd:1'] })).map(r => [r.slug, r.current, r.past, r.commits]), [[A.slug, 2, 1, null], [B.slug, 1, 0, null]],
    'a school reports commits as null, never 0');
  assert.deepEqual(plain(s.trendsQuery(doc, { club: ['lone'] })).map(r => [r.slug, r.commits]), [[D2.slug, null]], 'D2 commits: null');
  assert.deepEqual(plain(s.trendsCoverageLines(doc, 'club', { D2: { current: 1, past: 1, commits: null } }, ['D2'])),
    ['Division II: 1 of 50 current players, club known for 6%; 1 of 60 former players (stored past rosters), club known for 3%; commits not collected'],
    'a D2-only result states the D2 rate');
});

test('T1 AND across boxes: club A and school B at P counts the one person with both (not 3, not the 2/2 pairing)', async () => {
  const s = loadPage({}).sandbox;
  // (a, b, P), (a, b2, P), (a2, b, P): one person has club a AND school b
  const doc = { programIds: ['p'], programs: { p: { division: 'D1', current: 3, past: 0, commits: 0 } },
    clubs: { id: ['a', 'a2'], name: ['A', 'A2'], state: [null, null] }, schools: { id: ['b', 'b2'], name: ['B', 'B2'], city: [null, null], state: [null, null] },
    records: { p: [0, 0, 0], s: [0, 0, 0], c: [0, 0, 1], h: [0, 1, 0] } };
  assert.deepEqual(plain(s.trendsQuery(doc, { club: ['a'], school: ['b'], program: ['p'] })).map(r => r.current), [1]);
  assert.deepEqual(plain(s.trendsQuery(doc, { club: ['a'] })).map(r => r.current), [2]);
  assert.deepEqual(plain(s.trendsQuery(doc, { school: ['b'] })).map(r => r.current), [2]);
  // T2: OR within a box
  assert.deepEqual(plain(s.trendsQuery(doc, { club: ['a', 'a2'], program: ['p'] })).map(r => r.current), [3], 'clubs a or a2: 3 (AND within the box would give 0)');
  assert.deepEqual(plain(s.trendsQuery(doc, { club: ['a', 'a2'], school: ['b'] })).map(r => r.current), [2], '(a or a2) and b: 2');
  assert.deepEqual(plain(s.trendsQuery(doc, { club: ['nope'] })), [], 'a box whose values are all unknown matches nothing');
  assert.deepEqual(plain(s.trendsParse('#/trends?club=a,a')), { club: ['a'] }, 'club=a,a is one value, so it counts once');
});

/* ---------- URL ---------- */
test('T5 URL: several values per box round-trip; one value is byte-for-byte #310; a comma inside a value survives', async () => {
  const { sandbox: s } = loadPage({});
  assert.equal(s.trendsUrl({ program: 'stanford', club: 'mvla', school: 'ccd:1' }), '#/trends?club=mvla&school=ccd%3A1&program=stanford', '#310 single values unchanged');
  assert.equal(s.trendsUrl({ program: ['stanford'], club: ['mvla'], school: ['ccd:1'] }), '#/trends?club=mvla&school=ccd%3A1&program=stanford');
  assert.equal(s.trendsUrl({}), '#/trends');
  const sel = { club: ['raw:zeta & sons united', 'mvla', 'odd,club'], school: ['ccd:1', 'ccd:2'], program: ['stanford', 'ucla'] };
  const url = s.trendsUrl(sel);
  assert.equal(url, '#/trends?club=raw%3Azeta%20%26%20sons%20united,mvla,odd%2Cclub&school=ccd%3A1,ccd%3A2&program=stanford,ucla');
  assert.deepEqual(plain(s.trendsParse(url)), sel, 'parse(url(sel)) == sel, the comma value included');
  assert.deepEqual(plain(s.trendsParse('#/trends?school=ccd%3A1&program=stanford&bogus=1')), { school: ['ccd:1'], program: ['stanford'] }, 'an old single value parses to a one-element list');
  assert.deepEqual(plain(s.trendsParse('#/trends?club=c0,c1,c2,c3,c4')), { club: ['c0', 'c1', 'c2'] }, 'at most three per box (#348): the first three');
  assert.deepEqual(plain(s.trendsParseLink('#/trends?club=c0,c1,c2,c3,c4&program=p0,p1,p2')), { sel: { club: ['c0', 'c1', 'c2'], program: ['p0', 'p1', 'p2'] }, dropped: { club: 2 } },
    'and says how many it left out; three is not cut');
});

test('#310 old links: the three path forms redirect with replaceState (not a push); no old-form link is left in the page', async () => {
  for (const [old, now] of [['#/trends/club/mvla', '#/trends?club=mvla'], ['#/trends/school/ccd%3A1', '#/trends?school=ccd%3A1'], [`#/trends/program/${A.slug}`, `#/trends?program=${A.slug}`]]) {
    const page = await open(old, fixture({ schools: true }));
    assert.equal(page.sandbox.location.hash, now, `${old} -> ${now}`);
    assert.deepEqual([page.hist.replaces, page.hist.pushes], [1, 0], `${old}: one replaceState, no pushState`);
  }
  const src = fs.readFileSync(HTML, 'utf8');
  assert.equal(src.match(/#\/trends\/(club|school|program)\//g), null, 'the page source still produces an old-form trends link');
  const page = await open('#/trends?program=' + A.slug);
  assert.equal(page.sandbox.trendsClubCell({ division: 'D1' }, { club: 'MVLA', clubInfo: { status: 'matched', clubId: 'mvla' } }),
    '<a href="#/trends?club=mvla" title="Which programs have players from MVLA">MVLA</a>');
  assert.ok(page.results().includes(`href="#/trends?club=mvla&amp;program=${A.slug}"`), 'a feeder row links to the club + program card');
});

test('#310 raw: ids resolve through the alias table, value by value; an unknown one reads "not in the index"', async () => {
  let page = await open('#/trends?club=raw%3Amtn%20view%20los%20altos%20sc,surf');
  assert.equal(page.sandbox.location.hash, '#/trends?club=mvla,surf', 'rewritten to the club id, the other value kept');
  assert.equal(page.hist.pushes, 0, 'with replaceState');
  assert.deepEqual(chipNames(page, 'club'), ['Mountain View Los Altos SC', 'San Diego Surf']);
  page = await open('#/trends?club=raw%3Azeta%20united');
  assert.ok(page.results().includes('unmatched spelling'));
  page = await open('#/trends?club=raw%3Aqqq');
  assert.deepEqual(chipNames(page, 'club'), ['raw:qqq — not in the index']);
  assert.ok(page.el('#trChips-club').innerHTML.includes('tr-chip missing'));
  assert.ok(page.results().includes('There is no club “raw:qqq” in the clubs and schools index') && page.results().includes('How to read this'), 'a box with no known value is left out');
});

test('#339 a merged-away club id lands on the club it went into, alone or among several; a spelling two clubs claim stays put; an unknown id still reads "not in the index"', async () => {
  const doc = fixture();
  doc.retiredClubs = { 'old-mvla': 'mvla', 'gone-to-nowhere': 'no-such-club' };
  const cl = doc.clubs, n = cl.id.length;
  doc.clubs = { ...cl, id: [...cl.id, 'shore-ca', 'shore-va'], name: [...cl.name, 'Shore FC (CA)', 'Shore FC (VA)'],
    state: [...cl.state, 'CA', 'VA'], aka: { ...cl.aka, [n]: ['shore fc ecnl'], [n + 1]: ['shore fc ecnl'] } };
  let page = await open('#/trends?club=old-mvla', doc);
  assert.equal(page.sandbox.location.hash, '#/trends?club=mvla', 'rewritten to the live club id');
  assert.equal(page.hist.pushes, 0, 'with replaceState');
  assert.deepEqual(chipNames(page, 'club'), ['Mountain View Los Altos SC']);
  page = await open('#/trends?club=surf,old-mvla', doc);
  assert.equal(page.sandbox.location.hash, '#/trends?club=surf,mvla', 'a retired id among several values: only it is rewritten, order kept');
  assert.deepEqual(chipNames(page, 'club'), ['San Diego Surf', 'Mountain View Los Altos SC']);
  page = await open('#/trends?club=mvla,old-mvla', doc);
  assert.equal(page.sandbox.location.hash, '#/trends?club=mvla', 'a retired id resolving to a value already picked is not doubled');
  page = await open('#/trends?club=gone-to-nowhere', doc);
  assert.deepEqual(chipNames(page, 'club'), ['gone-to-nowhere — not in the index'], 'a retired id whose target is missing is not followed');
  page = await open('#/trends?club=raw%3Ashore%20fc%20ecnl', doc);
  assert.equal(page.sandbox.location.hash, '#/trends?club=raw%3Ashore%20fc%20ecnl', 'a state-split spelling is not guessed onto one of its two clubs');
  page = await open('#/trends?club=pda-south', doc);
  assert.deepEqual(chipNames(page, 'club'), ['pda-south — not in the index'], 'an id the index does not retire still reads "not in the index"');
  assert.ok(page.el('#trChips-club').innerHTML.includes('tr-chip missing'));
});

/* ---------- division everywhere, #315 ---------- */
test('division everywhere: program chips, suggestions and result lines carry D1/D2/D3', async () => {
  const p2 = await open('#/trends', searchFixture());
  type(p2, 'program', D2.shortName);
  assert.ok(optIds(p2, 'program').includes(D2.slug), 'the D2 program is offered');
  assert.ok(p2.el('#trList-program').innerHTML.includes('<span class="div-tag" title="Division II">D2</span>'), 'its suggestion carries the division line');
  const p3 = await open(`#/trends?program=${D2.slug},${A.slug}`);
  const chips = p3.el('#trChips-program').innerHTML;
  assert.ok(chips.includes(`${disp(D2).replace(/&/g, '&amp;').replace(/'/g, '&#39;')} <span class="div-tag" title="Division II">D2</span>`) && chips.includes('<span class="div-tag" title="Division I">D1</span>'), 'each chip names its division');
  assert.deepEqual(chipNames(p3, 'program'), [`${disp(D2)}, Division II`, `${disp(A)}, Division I`].map(t => t.replace(/&/g, '&amp;').replace(/'/g, '&#39;')));
  const p4 = await open('#/trends?club=mvla');
  assert.equal((p4.results().match(/class="div-tag"/g) || []).length, 3, 'every program row shows its division');
  const p5 = await open(`#/trends?program=${D3.slug}`, searchFixture());
  assert.deepEqual(chipNames(p5, 'program'), [`${disp(D3)} (D3) — not in the index`]);
  assert.ok(p5.results().includes('(Division III) is not in the clubs and schools index yet'));
});

test('#315 C1 + C2 kept: D2 commits "Not collected" (never 0) in rows, totals, cards and coverage; coverage names the D2 rate', async () => {
  let page = await open('#/trends?club=lone');
  const html = page.results();
  assert.deepEqual(cellsOf(html).map(r => r.nums), [['2', '1', '1', 'Not collected']], 'the D2 row: commits Not collected; one box, so past 1 reads 1');
  assert.ok(html.includes('1 current, 1 former, commits not collected at 1 program'), 'one box: the totals line is exact');
  assert.ok(html.includes('Division II: 1 of 50 current players, club known for 6%') && !html.includes('Division I:'), 'the D2 rate alone');
  page = await open(`#/trends?program=${D2.slug}`);
  assert.ok(page.results().includes('Not collected</span></td>') && page.results().includes('commits not collected'), 'feeder row and coverage');
  assert.ok(page.sub().includes('20 current players, 15 former, commits not collected'), page.sub());
  page = await open(`#/trends?club=mvla&program=${D2.slug}`);
  assert.deepEqual(stats(page.results()), { players: '0', current: '0', past: '0', commits: 'Not collected' }, 'no player there: still Not collected');
});

/* ---------- 1–2 (owner, #327) ---------- */
test('T3 one box shows exact counts, however many values it holds (owner, option a)', async () => {
  let page = await open('#/trends?club=mvla');
  assert.deepEqual(cellsOf(page.results()).map(r => [r.name, ...r.nums]),
    [[disp(B), '4', '2', '2', '1'], [disp(A), '3', '3', '0', '0'], [disp(C), '0', '0', '0', '5']], 'B: past 2 and commit 1 exact; Players 4, no range');
  page = await open('#/trends?club=mvla,mx');
  assert.deepEqual(cellsOf(page.results()).map(r => [r.name, ...r.nums])[0], [disp(B), '5', '2', '3', '1'], 'two values in one box: still exact (commit 1 reads 1)');
  page = await open(`#/trends?program=${B.slug}`);
  assert.ok(page.results().includes('<td class="num">1</td>') && !page.results().includes('1–2'), 'a program alone: MX\'s past 1 reads 1');
  assert.ok(!page.results().includes('read “1–2”'), 'and the page does not claim a 1–2 rule it is not applying');
});

test('T3 two or more boxes: past and commit counts of 1 or 2 read "1–2"; current stays exact; an OR sum is bucketed once', async () => {
  let page = await open(`#/trends?club=mvla&program=${A.slug},${B.slug}`);
  assert.deepEqual(cellsOf(page.results()).map(r => [r.name, ...r.nums]),
    [[disp(B), '3–4', '2', '1–2', '1–2'], [disp(A), '3', '3', '0', '0']], 'B: past 2 and commit 1 read 1–2; current 2 exact; Players 3–4, sorted as shown (above A, 3)');
  page = await open(`#/trends?club=mvla,mx&program=${B.slug}`);
  assert.deepEqual(stats(page.results()), { players: '5', current: '2', past: '3', commits: '1–2' }, 'past 2 + 1 = 3 is shown as 3, never "1–2" per part');
  page = await open(`#/trends?club=mx&program=${B.slug}`);
  assert.deepEqual(stats(page.results()), { players: '1–2', current: '0', past: '1–2', commits: '0' });
  page = await open(`#/trends?club=mvla,mx&school=ccd%3A1`, fixture({ schools: true }));
  assert.deepEqual(cellsOf(page.results()).map(r => r.nums[1]), ['1', '1'], 'current 1 in a combination stays 1');
});

test('T3 the order follows what is shown: with 2+ boxes past 1 and past 2 are one "1–2" bucket, then by name; one box sorts exactly', async () => {
  const [lo, hi] = [B, C].sort((x, y) => disp(x).localeCompare(disp(y)));
  const doc = fixture({ extra: [[hi.slug, 1, 'surf', null], [hi.slug, 1, 'surf', null], [lo.slug, 1, 'surf', null]] });
  let page = await open(`#/trends?club=surf&program=${A.slug},${B.slug},${C.slug}`, doc);
  assert.deepEqual(cellsOf(page.results()).map(r => [r.name, r.nums[2]]), [[disp(lo), '1–2'], [disp(hi), '1–2'], [disp(A), '0']],
    `${disp(hi)} (past 2) does not sort above ${disp(lo)} (past 1)`);
  page = await open('#/trends?club=surf', doc);
  assert.deepEqual(cellsOf(page.results()).map(r => [r.name, r.nums[2]]), [[disp(hi), '2'], [disp(A), '0'], [disp(lo), '1']], 'one box: exact values, exact order');
});

/* ---------- the states ---------- */
test('nothing selected: three boxes, the how-to card and the coverage; the live region is on the page from the start', async () => {
  const page = await open('#/trends');
  const html = page.app();
  for (const k of ['club', 'program']) assert.ok(html.includes(`<label class="trend-label" id="trLbl-${k}" for="trIn-${k}">`) && html.includes(`aria-describedby="trSel-${k}"`), `${k}: a labelled combobox with a description`);
  assert.ok(html.includes('<div class="sr-only" id="trLive" aria-live="polite"></div>'), 'the live region is in the first render');
  assert.equal(page.el('#trLive').textContent, '', 'and says nothing on load');
  assert.ok(page.results().includes('Division I: 100 current players, club known for 31%') && page.results().includes('combined with <b>or</b>'));
  assert.ok(page.sub().startsWith('Clubs and high schools behind college rosters · D1, D2 · 150 current players'), page.sub());
});

test('clubs only: the programs their players went to', async () => {
  const page = await open('#/trends?club=mvla,surf');
  assert.deepEqual(cellsOf(page.results()).map(r => [r.name, ...r.nums]),
    [[disp(A), '4', '4', '0', '3'], [disp(B), '4', '2', '2', '1'], [disp(C), '0', '0', '0', '5']], 'A: MVLA 3 + Surf 1 current; Surf commits 3; one box: exact');
  assert.ok(page.sub().startsWith('Mountain View Los Altos SC or San Diego Surf · D1, D2'), page.sub());
  assert.ok(page.results().includes(`href="#/trends?club=mvla,surf&amp;program=${B.slug}"`), 'a row opens the card at that program, the clubs kept');
});

test('club AND high school, no program: a true AND (#312\'s "not necessarily the same players" note is gone)', async () => {
  const page = await open('#/trends?club=mvla&school=ccd%3A1', fixture({ schools: true }));
  assert.deepEqual(cellsOf(page.results()).map(r => [r.name, ...r.nums]), [A, B].sort((x, y) => disp(x).localeCompare(disp(y))).map(p => [disp(p), '1', '1', '0', '—']),
    'MVLA and Rocklin: one person at A and one at B; a tie sorts by name');
  assert.ok(!page.results().includes('Not necessarily the same players'));
});

test('programs only: clubs and high schools feeding them, summed across the programs', async () => {
  const page = await open(`#/trends?program=${A.slug},${B.slug}`, fixture({ schools: true }));
  const clubs = [...page.results().matchAll(/data-tr-kind="club" data-tr-id="([^"]+)"/g)].map(m => m[1]);
  assert.deepEqual(clubs, ['mvla', 'surf', 'raw:zeta united', 'mx'], 'MVLA: 5 current + 2 past across A and B; one box, so exact order: MX (past 1, no current) last');
  assert.ok(page.results().includes('across 2 programs'));
});

test('program + clubs + school: one card; names come only from the public roster, never past players or commits (T4)', async () => {
  const prof = profileA(2);
  const page = await open(`#/trends?club=mvla&school=ccd%3A1&program=${A.slug}`, fixture({ schools: true }), { [`data/programs/${A.slug}.json`]: prof });
  await tick(30);
  assert.deepEqual(stats(page.results()), { players: '1', current: '1', past: '0', commits: '—' });
  assert.equal(page.el('#trNames').innerHTML, `<b>Current players (1):</b> ${nameOf(prof.roster.players[0])}`, 'the one player with MVLA and Rocklin');
  assert.ok(!page.results().includes('PAST PERSON') && !page.el('#trNames').innerHTML.includes('PAST PERSON') && !page.el('#trNames').innerHTML.includes('RECRUIT'), 'no past player or recruit is named');
  const p2 = await open(`#/trends?club=mvla&program=${A.slug},${B.slug}`);
  assert.deepEqual(cellsOf(p2.results()).map(r => r.name), [disp(B), disp(A)], 'several programs: one row each, as shown (B 3–4 above A 3)');
  assert.equal(p2.results().includes('id="trNames"'), false, 'names load per row, on demand');
  const p3 = await open(`#/trends?club=surf&school=ccd%3A1&program=${B.slug}`, fixture({ schools: true }));
  assert.ok(p3.results().includes('No players in the index are from San Diego Surf and Rocklin High at') && p3.results().includes('Division I:'), 'an empty AND reads as coverage, not a true zero');
});

test('an index built before #327 (per-club cells) still reads: one box exact, club and school together wait for the refresh', async () => {
  let page = await open('#/trends?club=mvla', cellFixture());
  assert.deepEqual(cellsOf(page.results()).map(r => [r.name, ...r.nums]),
    [[disp(B), '4', '2', '2', '1'], [disp(A), '3', '3', '0', '0'], [disp(C), '0', '0', '0', '5']], 'the same answer as the records file');
  page = await open('#/trends?club=mvla&school=ccd%3A1', cellFixture());
  assert.ok(page.results().includes('answered after the next data refresh'), 'says so rather than showing a wrong AND');
  const old = fixture();
  delete old.divisions; delete old.commitDivisions; old.division = 'D1';
  old.coverage = { current: old.coverage.byDivision.D1.current, past: old.coverage.byDivision.D1.past, commits: old.coverage.byDivision.D1.commits };
  page = await open('#/trends?club=mvla', old);
  assert.ok(page.results().includes('Division I: 5 of 100 current players, club known for 31%'), 'and an index from before #315 too');
});

test('#315 phone first load: Loading, then a failed load leaves S.trends unset and Try again fetches; one download on re-entry', async () => {
  const page = loadPage({ 'data/trends/index.json': fixture() });
  const real = page.sandbox.fetch;
  let release, calls = 0;
  page.sandbox.fetch = async url => {
    if (String(url) !== '/api/v1/trends') return real(url);
    calls++; await new Promise(r => { release = r; });
    return { ok: false, status: 503, async json() { throw new Error('503'); } };
  };
  page.sandbox.location.hash = '#/trends';
  const done = page.sandbox.route(); await tick();
  assert.ok(page.app().includes('id="trLoading"') && page.app().includes('Loading…'), 'Loading is on screen while the index downloads');
  const heading = '<h1 class="content-title">From Youth Clubs/High Schools to Colleges<'; // #329: every state carries it
  assert.ok(page.app().includes(heading), 'the Loading state has the page title');
  release(); await done; await tick();
  // #345: the shared load-failed card, which names a 503 as the service being briefly unavailable
  assert.ok(page.app().includes('Couldn’t load the data') && page.app().includes('briefly unavailable') && page.app().includes('id="trRetry"'),
    'a failed load says so and offers Try again');
  assert.ok(page.app().includes(heading), 'the Could not load state has the page title');
  assert.equal(page.sandbox.S.trends, null, 'S.trends stays unset');
  page.sandbox.fetch = real;
  click(page.el('#trRetry')); await tick(40);
  assert.ok(calls >= 1 && page.results().includes('How to read this'));
  const missing = await open('#/trends', null);
  assert.ok(missing.app().includes('Not built yet') && missing.app().includes('id="trRetry"'), 'a 404 still reads "Not built yet"');
  assert.ok(missing.app().includes(heading), 'the Not built yet state has the page title');
  assert.ok(![page, missing].some(pg => pg.app().includes('Where players come from')), 'no state carries the old title');
});

/* ---------- the tab's name (#322) ---------- */
test('the tab and the breadcrumb read "Pipelines"; the page title reads "From Youth Clubs/High Schools to Colleges" (#329); the #/trends URL is unchanged', async () => {
  const page = await open('#/trends');
  const html = page.app();
  const tabs = [...html.matchAll(/<a href="([^"]*)" class="view-tab[^"]*"[^>]*>([^<]*)<\/a>/g)];
  const tab = tabs.find(m => m[1] === '#/trends');
  assert.ok(tab, 'the tab still links to #/trends');
  assert.equal(tab[2], 'Pipelines');
  assert.ok(tab[0].includes('aria-selected="true"'), 'and is the selected tab');
  assert.ok(!/Clubs &amp; schools|Clubs &amp; high schools|Clubs & high schools/.test(html), 'no old label left on the page');
  assert.ok(/class="breadcrumb-current"[^>]*>Pipelines</.test(html), 'the breadcrumb reads Pipelines');
  assert.ok(/<h1 class="content-title">From Youth Clubs\/High Schools to Colleges</.test(html), 'the page title reads the owner\'s wording (#329)');
  assert.ok(!html.includes('Where players come from'), 'the old page title is gone');
});

/* ---------- T8: several chips per box ---------- */
test('T8 chips: pick returns focus to the input; remove moves to the next chip, else the previous, else the input', async () => {
  const page = await open('#/trends', searchFixture());
  const pushes = page.hist.pushes;
  const first = add(page, 'club', 'mvla');
  assert.equal(first, 'mvla');
  assert.equal(page.sandbox.location.hash, '#/trends?club=mvla');
  assert.equal(page.sandbox.document.activeElement, page.el('#trIn-club'), 'after a pick, focus is on the input');
  assert.equal(page.el('#trLive').textContent, 'Added Mountain View Los Altos SC. 3 programs.');
  assert.equal(page.el('#trIn-club').placeholder, 'Add another club');
  assert.equal(page.el('#trSel-club').textContent, '1 club chosen: Mountain View Los Altos SC.', 'the chosen values describe the input');
  add(page, 'club', 'surf'); add(page, 'club', 'club 1');
  assert.equal(page.sandbox.location.hash, '#/trends?club=mvla,surf,c1');
  assert.equal(page.hist.pushes, pushes + 3, 'one history entry per pick');
  assert.deepEqual(chipNames(page, 'club'), ['Mountain View Los Altos SC', 'San Diego Surf', 'Club 1'], 'buttons read "Remove club: X"');
  assert.equal(page.el('#trClrAll-club').hidden, false, '"Clear clubs" at two or more');
  type(page, 'club', '');
  assert.ok(!optIds(page, 'club').some(id => ['mvla', 'surf', 'c1'].includes(id)), 'picked values are not offered again');
  removeChip(page, 'club', 1);
  assert.equal(page.sandbox.location.hash, '#/trends?club=mvla,c1');
  assert.equal(page.sandbox.document.activeElement, page.el('#trX-club-1'), 'focus on the chip that took its place');
  assert.equal(page.el('#trLive').textContent.startsWith('Removed San Diego Surf.'), true);
  removeChip(page, 'club', 1);
  assert.equal(page.sandbox.document.activeElement, page.el('#trX-club-0'), 'the last one removed: focus on the previous chip');
  removeChip(page, 'club', 0);
  assert.equal(page.sandbox.document.activeElement, page.el('#trIn-club'), 'none left: focus on the input');
  add(page, 'club', 'mvla'); add(page, 'club', 'surf');
  click(page.el('#trClrAll-club'));
  assert.equal(page.sandbox.location.hash, '#/trends');
  assert.equal(page.sandbox.document.activeElement, page.el('#trIn-club'), 'after Clear, focus on the input');
  const said = page.el('#trLive').textContent;
  type(page, 'club', 'zzzz');
  assert.equal(page.el('#trLive').textContent, said, 'a suggestion refresh or a no-match line is never announced');
  assert.equal(page.el('#trMsg-club').textContent, 'No club matches “zzzz”.');
});

test('T8 the three-value cap (#348): the input stays focusable (aria-disabled), says why, and a fourth is refused', async () => {
  const page = await open('#/trends', searchFixture());
  add(page, 'club', 'club 1'); add(page, 'club', 'club 2');
  assert.equal(page.el('#trIn-club').getAttribute('aria-disabled'), null, 'two values: not at the cap');
  type(page, 'club', 'club 3');
  assert.deepEqual(plain(optIds(page, 'club')), ['c3'], 'the third is still offered');
  add(page, 'club', 'club 3');
  assert.deepEqual(plain(page.sandbox.trState().sel.club), ['c1', 'c2', 'c3']);
  assert.equal(page.sandbox.document.activeElement, page.el('#trIn-club'), 'focus after the 3rd value: the input, never a disabled element');
  assert.equal(page.el('#trIn-club').getAttribute('aria-disabled'), 'true');
  assert.ok(page.el('#trLive').textContent.includes('That is 3 clubs, the most one box takes'), page.el('#trLive').textContent);
  type(page, 'club', 'mvla');
  assert.deepEqual(plain(optIds(page, 'club')), [], 'a fourth is not offered');
  assert.equal(page.el('#trMsg-club').textContent, 'You can choose up to 3 clubs. Remove one to add another.');
  assert.ok(page.el('#trSel-club').textContent.endsWith('3 is the most.'));
  const pushes = page.hist.pushes;
  page.sandbox.trState().opts.club = [{ id: 'mvla', label: 'x', sub: '' }];
  page.el('#trList-club').onclick({ target: { closest: () => ({ dataset: { i: '0' } }) } });
  assert.deepEqual(plain(page.sandbox.trState().sel.club), ['c1', 'c2', 'c3'], 'a fourth pick changes nothing');
  assert.equal(page.hist.pushes, pushes, 'and pushes no history entry');
});

test('#348 an older link with more than three values keeps the first three and says what it left out', async () => {
  const page = await open('#/trends?club=mvla,surf,mx,lone,raw%3Azeta%20united&program=' + A.slug);
  assert.equal(page.sandbox.location.hash, `#/trends?club=mvla,surf,mx&program=${A.slug}`, 'the URL is rewritten to what the page shows');
  assert.equal(page.hist.pushes, 0, 'with replaceState, so Back does not bounce');
  assert.deepEqual(chipNames(page, 'club'), ['Mountain View Los Altos SC', 'San Diego Surf', 'MX United']);
  assert.ok(page.results().includes('This link listed 5 clubs; a box takes up to 3, so the first 3 are shown and 2 were left out.'));
  assert.ok(page.results().includes('data-stat="players"'), 'the results render for the three kept');
  removeChip(page, 'club', 2);
  assert.ok(!page.results().includes('This link listed'), 'the note goes once the visitor changes the selection');
  const three = await open('#/trends?club=mvla,surf,mx');
  assert.equal(three.sandbox.location.hash, '#/trends?club=mvla,surf,mx');
  assert.ok(!three.results().includes('This link listed'), 'three values: nothing left out, no note');
});

test('#339 + #348 a retired id in an over-long link: the first three are kept, the retired one is rewritten, and the note stays', async () => {
  const doc = fixture();
  doc.retiredClubs = { 'old-mvla': 'mvla' };
  const page = await open('#/trends?club=old-mvla,surf,mx,lone', doc);
  assert.equal(page.sandbox.location.hash, '#/trends?club=mvla,surf,mx', 'cut to three, then the retired id rewritten in place');
  assert.equal(page.hist.pushes, 0, 'with replaceState only');
  assert.deepEqual(chipNames(page, 'club'), ['Mountain View Los Altos SC', 'San Diego Surf', 'MX United']);
  assert.ok(page.results().includes('This link listed 4 clubs; a box takes up to 3, so the first 3 are shown and 1 were left out.')
    || page.results().includes('This link listed 4 clubs; a box takes up to 3, so the first 3 are shown and 1 was left out.'), 'the note survives the rewrite');
  await page.sandbox.route();  // the page may render twice on one entry (#348): the second read keeps the note
  assert.ok(page.results().includes('This link listed 4 clubs'), 'the note survives a second render after the rewrite');
});

test('suggestions follow the "1–2" rule (#343, Bianque): a range with two or more boxes, exact with one', async () => {
  const doc = fixture({ schools: true, extra: [[B.slug, 1, 'mx', 'ccd:1']] });
  let page = await open('#/trends?club=mx', doc);
  let list = type(page, 'school', '');
  assert.ok(list.includes('Rocklin · CA · 1 player<') || list.includes('1 player</span>'), `one box: exact (${list})`);
  assert.ok(!list.includes('1–2'), 'one box: no range in the suggestions');
  page = await open(`#/trends?club=mx&program=${B.slug}`, doc);
  list = type(page, 'school', '');
  assert.ok(list.includes('1–2 players'), `two boxes: the former player reads 1–2 (${list})`);
});

test('#310 keyboard: one listbox of options (not tab stops), arrows, Enter adds, Backspace reaches the last chip, Escape closes', async () => {
  const page = await open('#/trends', searchFixture());
  const input = page.el('#trIn-club');
  input.onfocus();
  const list = page.el('#trList-club').innerHTML;
  assert.equal((list.match(/role="option"/g) || []).length, 12, '12 suggestions: MVLA, Surf, MX, Lone Star and Club 1-9, minus none picked');
  assert.ok(!/<a |<button|tabindex/.test(list), 'options are not tab stops');
  key(page, 'club', 'ArrowDown');
  assert.equal(input.getAttribute('aria-activedescendant'), 'trOpt-club-0');
  key(page, 'club', 'ArrowUp'); key(page, 'club', 'ArrowUp');
  assert.equal(input.getAttribute('aria-activedescendant'), 'trOpt-club-10', 'ArrowUp wraps');
  key(page, 'club', 'ArrowDown');
  const id = page.sandbox.trState().opts.club[11].id;
  key(page, 'club', 'Enter');
  assert.deepEqual(plain(page.sandbox.trState().sel.club), [id], 'Enter adds the marked value');
  assert.equal(page.sandbox.document.activeElement, input, 'and focus stays in the box for another');
  input.value = '';
  assert.equal(key(page, 'club', 'Backspace'), true);
  assert.equal(page.sandbox.document.activeElement, page.el('#trX-club-0'), 'Backspace in an empty box moves to the last chip');
  input.onfocus(); key(page, 'club', 'Escape');
  assert.equal(page.el('#trList-club').hidden, true);
  input.onfocus();
  assert.equal(key(page, 'club', 'Tab'), false, 'Tab is not taken');
});

test('#307 matching: club aliases, school spellings and same-name schools, programs by name, nickname and short name', async () => {
  const page = await open('#/trends', searchFixture());
  for (const q of ['mvla', 'MVLA', 'mountain view', 'Mtn View']) {
    type(page, 'club', q);
    assert.deepEqual(plain(optIds(page, 'club')), ['mvla'], `"${q}" finds only MVLA`);
  }
  assert.ok(type(page, 'club', 'MVLA').includes('also known as MVLA'));
  type(page, 'school', 'rocklin'); assert.deepEqual(plain(optIds(page, 'school')), ['ccd:1']);
  const carroll = type(page, 'school', 'Southlake Carroll');
  assert.ok(carroll.includes('>Carroll Senior H S<') && carroll.includes('also known as Southlake Carroll'));
  const dec = type(page, 'school', 'decatur high');
  assert.ok(dec.includes('Decatur, AL') && dec.includes('Decatur, GA'), 'two same-name schools, told apart by city and state');
  type(page, 'program', 'stanford'); assert.equal(optIds(page, 'program')[0], 'stanford');
  type(page, 'program', 'cardinal');
  assert.deepEqual(plain(optIds(page, 'program')), ['stanford', 'louisville'], '"cardinal": Stanford first by its exact nickname');
});

test('suggestions follow the other boxes through the same AND query; 6 in an empty box on phones, 12 on desktop', async () => {
  let page = await open(`#/trends?program=${B.slug}`, searchFixture());
  type(page, 'club', ''); assert.deepEqual(plain(optIds(page, 'club')), ['mvla', 'mx'], 'clubs feeding B');
  type(page, 'school', ''); assert.deepEqual(plain(optIds(page, 'school')), ['ccd:4', 'ccd:1'], 'schools feeding B (1 each: by name)');
  page = await open('#/trends?club=mvla&school=ccd%3A1', searchFixture());
  type(page, 'program', ''); assert.deepEqual(plain(optIds(page, 'program')).sort(), [A.slug, B.slug].sort(), 'programs with MVLA AND Rocklin players');
  const count = async phone => {
    const p = loadPage({ 'data/trends/index.json': searchFixture() });
    p.sandbox.matchMedia = q => ({ matches: phone && q === '(max-width: 480px)' });
    p.sandbox.location.hash = '#/trends'; await p.sandbox.route(); await tick();
    type(p, 'club', ''); const c = optIds(p, 'club').length;
    type(p, 'club', 'club'); return [c, optIds(p, 'club').length];
  };
  assert.deepEqual(await count(false), [12, 9]);
  assert.deepEqual(await count(true), [6, 9]);
});

test('#310 sidebar filters never hide a picked program', async () => {
  const other = INDEX.programs.find(p => p.division === 'D1' && p.conference && ![A, B, C].some(q => q.conference === p.conference)).conference;
  const page = loadPage({ 'data/trends/index.json': fixture() });
  page.sandbox.S.filters.conf = [other];
  page.sandbox.location.hash = `#/trends?club=mvla&program=${A.slug}`; await page.sandbox.route(); await tick();
  assert.deepEqual(stats(page.results()), { players: '3', current: '3', past: '0', commits: '0' }, 'the card still shows');
  assert.ok(page.results().includes('is outside your sidebar filters; it is shown because you picked it.'));
  page.sandbox.location.hash = '#/trends?club=mvla'; await page.sandbox.route(); await tick();
  assert.deepEqual(cellsOf(page.results()), [], 'unpicked program rows are still filtered');
  assert.ok(page.results().includes('3 programs with these players are hidden by your sidebar filters.'));
});

/* ---------- the rest of the site ---------- */
test('the list view offers the tab; the roster tab links a reviewed club and the program to the URL', async () => {
  const page = await open('#/');
  assert.ok(page.app().includes('href="#/trends"'));
  const prof = profileA(1);
  const p2 = await open(`#/p/${A.slug}/roster`, fixture(), { [`data/programs/${A.slug}.json`]: prof });
  await tick(30);
  assert.ok(p2.tab().includes('href="#/trends?club=mvla"'), 'a matched club links to its trends page');
  assert.ok(!p2.tab().includes('club=raw'), 'an unmatched spelling does not');
  assert.ok(p2.tab().includes(`href="#/trends?program=${A.slug}"`), 'the roster tab links to where the program\'s players come from');
  // #329: the link reads like the page it opens
  const link = p2.tab().match(new RegExp(`<a href="#/trends\\?program=${A.slug}">([^<]*)</a>`));
  assert.ok(link, 'the program link is there');
  const html = s => s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  assert.equal(link[1], `${html(disp(prof))}'s youth clubs and high schools →`, 'the link reads "{School}\'s youth clubs and high schools →" (#329)');
  assert.ok(!p2.tab().includes('players come from'), 'the old link text is gone');
  assert.deepEqual(plain(p2.sandbox.trendsRosterNames({ roster: null, commitments: prof.commitments }, { club: ['mvla'] })), [], 'commitments are never a source of names');
  // #315: every division links (the D1 gate is gone)
  const d2 = JSON.parse(JSON.stringify(prof)); d2.division = 'D2';
  const p3 = await open(`#/p/${A.slug}/roster`, fixture(), { [`data/programs/${A.slug}.json`]: d2 });
  await tick(30);
  assert.ok(p3.tab().includes('href="#/trends?club=mvla"') && p3.tab().includes(`href="#/trends?program=${A.slug}"`), 'a D2 roster links its club and its program');
});
