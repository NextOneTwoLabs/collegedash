// Issue #306 (owner rule): wherever the site shows a program, its line names the division, in the Table's form
// from #286 ("D1 · Big Ten · Columbus, OH").
//
//     node --test tests/division_everywhere.test.mjs
//
// Same mechanism as tests/table_sort.test.mjs: the inline <script> of public/index.html runs in a `vm` against a
// stub DOM, and each program-listing view is rendered for real with three made-up programs (no real names, no
// people), one each from D1, D2 and D3. For every place a fixture program's name is shown, the text between that
// name and the next program's name (or 700 characters, whichever is sooner) must carry that program's division tag.
//
// Views rendered: Table, Cards, Shortlist page, sidebar Shortlist, sidebar Compare, ID Camps, Clubs & schools
// (a club's programs), Compare column headers, Compare "Add a school" results, program profile (subtitle and
// glance panel), not-found "Did you mean". The Clubs & schools program picker (a native <select>, which cannot
// hold markup) is checked separately: each option sits in an <optgroup> named for its division.
//
// The mutation check is built in: the same views are rendered again from a copy of the page whose programLine()
// drops the division, and every view must then fail. That proves each check can fail and that every view gets
// its line from the one helper.
//
// What it CANNOT prove, and a human must check in a browser: how the line wraps or truncates at ~400px.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const PAGE = process.env.DIVISION_EVERYWHERE_HTML || path.join(PUBLIC, 'index.html');
const readJSON = f => JSON.parse(fs.readFileSync(path.join(PUBLIC, f), 'utf8'));
const clone = v => JSON.parse(JSON.stringify(v));

// ---------- the fixture: one made-up program per division ----------
const row = (slug, division, city) => ({
  slug, name: `${slug[0].toUpperCase()}${slug.slice(1)} Test University`, shortName: `${slug[0].toUpperCase()}${slug.slice(1)}TU`,
  nickname: 'Testers', searchNames: [slug, 'testu'], conference: `Test ${division} Conference`, division, colors: [],
  city, state: 'CA', region: 'West', ownership: 'Public', undergradEnrollment: null, admissionRate: null,
  academicRank: null, tuitionInState: null, tuitionOutOfState: null, nationalTitles: 0, collegeCups: 0,
  lastSeason: null, rpiHistory: [], commitmentsByYear: {}, completeness: 1, stale: [], failed: [], tags: [],
});
const PROGS = [row('alpha', 'D1', 'Alphaville'), row('bravo', 'D2', 'Bravoton'), row('charlie', 'D3', 'Charlieburg')];
const SLUGS = PROGS.map(p => p.slug);
const INDEX = { updated: '2026-09-24T00:00:00Z', season: { current: 2026, gradYears: [2026, 2027, 2028, 2029] }, programs: PROGS };
const UCLA = readJSON('data/programs/ucla.json');
const PROFILES = Object.fromEntries(PROGS.map(p => [p.slug, { ...clone(UCLA), slug: p.slug, name: p.name, shortName: p.shortName,
  division: p.division, conference: p.conference, school: { ...UCLA.school, city: p.city, state: p.state } }]));
const CAMPS = { updated: '2026-09-24T00:00:00Z', window: { from: '2026-09-24', to: '2027-09-24' }, counts: { total: 3, id: 3, youth: 0, unknown: 0 },
  camps: PROGS.map((p, i) => ({ slug: p.slug, name: `Fixture ID Camp ${i}`, startDate: `2026-10-0${i + 1}`, endDate: null, precision: 'day', campType: 'id',
    kind: 'camp', confidence: 'verified', location: null, ages: null, price: null, registerUrl: null, sourceUrl: 'https://example.org/camp' })) };
const TRENDS = {
  updated: '2026-09-17T00:00:00Z', division: 'D1', season: 2026, pastSeasons: [2023, 2024, 2025],
  commitStatuses: ['verbal', 'signed'], columns: ['current', 'past', 'commits'],
  coverage: { current: { players: 10, clubKnown: 5, schoolNamed: 5, schoolKnown: null }, past: { players: 10, clubKnown: 5, schoolNamed: 5, schoolKnown: null },
              commits: { recruits: 5, clubKnown: 5, schoolNamed: 1, schoolKnown: null } },
  programs: Object.fromEntries(SLUGS.map(s => [s, { current: 3, past: 2, commits: 1, clubKnown: [1, 1, 1], schoolKnown: [0, 0, 0] }])),
  clubs: { fxc: { name: 'Fixture Club', state: 'CA', programs: { alpha: [3, 0, 1], bravo: [2, 1, 0], charlie: [1, 1, 1] } } },
  schools: null,
};

// ---------- the page ----------
function makeElement(name) {
  const el = {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, _on: {},
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener(t, fn) { el._on[t] = fn; }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null, matches: () => false, focus() { }, contains: () => false,
  };
  return el;
}
const HANDLES = ['S', 'renderList', 'renderSidebar', 'loadIndex', 'renderShortlist', 'renderCamps', 'renderTrends', 'renderCompare', 'renderProfile', 'renderNotFound'];
function loadPage(transform = s => s) {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
  const serve = { '/api/v1/programs': INDEX, '/api/v1/camps': CAMPS, '/api/v1/trends': TRENDS,
    ...Object.fromEntries(SLUGS.map(s => [`/api/v1/programs/${s}`, PROFILES[s]])) };
  const ok = (body, st = 200) => ({ ok: st < 400, status: st, async json() { return clone(body); } });
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector, querySelectorAll: () => [], addEventListener() { }, createElement: makeElement },
    location: { hash: '', replace(h) { this.hash = h; } }, history: { replaceState() { } }, matchMedia: () => ({ matches: false }),
    localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) },
    innerWidth: 1400, addEventListener() { }, alert() { },
    fetch: async url => { const u = String(url).split('?')[0]; return u in serve ? ok(serve[u]) : ok({}, 404); },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(PAGE, 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const src = transform(lines.slice(a + 1, b).join('\n')) + `\n;for (const k of ${JSON.stringify(HANDLES)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, $: bySelector };
}
const settle = async () => { for (let i = 0; i < 30; i++) await new Promise(r => setTimeout(r, 0)); };

// Render every program-listing view; returns [view, html, how the name is shown, programs expected].
async function renderAll(transform) {
  const { sb, $ } = loadPage(transform);
  const app = () => $('#app').innerHTML;
  await sb.loadIndex(); await settle();
  const short = p => p.shortName, long = p => p.name;
  const out = [];
  const list = async view => {
    Object.assign(sb.S.filters, { conf: [], region: [], division: [], classYear: [], cond: [], sort: 'name', sortDir: null, view, moreStats: false });
    sb.S.q = ''; sb.S.qRaw = '';
    await sb.renderList(); return app();
  };
  out.push(['Table', await list('table'), short, PROGS]);
  out.push(['Cards', await list('cards'), short, PROGS]);
  sb.S.favorites = new Set(SLUGS);
  await sb.renderShortlist(); out.push(['Shortlist page', app(), short, PROGS]);
  sb.S.sidebarTab = 'shortlist'; sb.renderSidebar(); out.push(['Sidebar shortlist', $('#sidebar').innerHTML, short, PROGS]);
  sb.S.compare = [...SLUGS];
  sb.S.sidebarTab = 'compare'; sb.renderSidebar(); out.push(['Sidebar compare', $('#sidebar').innerHTML, short, PROGS]);
  await sb.renderCamps(); out.push(['ID Camps', app(), short, PROGS]);
  await sb.renderTrends('club', 'fxc'); out.push(['Clubs & schools (a club\'s programs)', app(), short, PROGS]);
  sb.S.profiles = sb.S.profiles || {};
  await sb.renderCompare(); await settle();
  const cmp = app();
  out.push(['Compare column headers', cmp.slice(cmp.indexOf('<table class="cmp-table">'), cmp.indexOf('<th class="group"')), short, PROGS]);
  sb.S.compare = [];
  await sb.renderCompare(); await settle();
  const add = $('#cmpAdd'); add.value = 'testu'; assert.ok(add._on.input, 'Compare "Add a school" has no input handler');
  add._on.input(); out.push(['Compare "Add a school" results', $('#cmpResults').innerHTML, short, PROGS]);
  for (const p of PROGS) { await sb.renderProfile(p.slug, 'overview'); await settle(); out.push([`Profile (${p.division})`, app(), short, [p]]); }
  sb.renderNotFound({ title: 'Page not found', message: 'x', suggestions: PROGS }); out.push(['Not found "Did you mean"', app(), long, PROGS]);
  return out;
}

// Every place a program's name is shown must be followed, before the next program's name, by its division tag.
function checkView([view, html, nameOf, progs]) {
  const names = PROGS.map(nameOf);
  let seen = 0;
  for (const p of progs) {
    let i = -1;
    const at = new Set();
    while ((i = html.indexOf(`>${nameOf(p)}<`, i + 1)) !== -1) {
      if (html.startsWith('<option', html.lastIndexOf('<', i))) continue; // the picker's options: checked by their optgroup below
      seen++; at.add(p.slug);
      let end = Math.min(html.length, i + 700);
      for (const n of names) { const j = html.indexOf(`>${n}<`, i + 1); if (j !== -1 && j < end) end = j; }
      assert.match(html.slice(i, end), new RegExp(`class="div-tag"[^>]*>${p.division}</span>`), `${view}: ${nameOf(p)} is shown without its division`);
    }
    assert.ok(at.has(p.slug), `${view}: ${nameOf(p)} (${p.division}) is not listed at all`);
  }
  return seen;
}

let REAL;
test('every program-listing view shows each program with its division (D1, D2, D3)', async () => {
  REAL = await renderAll();
  for (const v of REAL) checkView(v);
  const names = REAL.map(v => v[0]);
  for (const need of ['Table', 'ID Camps', 'Clubs & schools (a club\'s programs)', 'Shortlist page', 'Compare column headers']) assert.ok(names.includes(need), need);
});

test('the program line reads "D1 · Conference · City, ST", the Table\'s form', async () => {
  const table = REAL.find(v => v[0] === 'Table')[1];
  assert.match(table, /<span class="team-sub"><span class="div-tag" title="[^"]+">D2<\/span><span class="pl-rest"> · Test D2 Conference · Bravoton, CA<\/span><\/span>/);
});

test('the Clubs & schools program picker groups its programs under their division', async () => {
  const trends = REAL.find(v => v[0].startsWith('Clubs'))[1];
  const groups = [...trends.matchAll(/<optgroup label="([^"]+)">([\s\S]*?)<\/optgroup>/g)];
  for (const p of PROGS) {
    const g = groups.find(m => m[2].includes(`value="${p.slug}"`));
    assert.ok(g, `${p.slug} is not inside an optgroup`);
    assert.match(g[1], new RegExp(`Division ${{ D1: 'I', D2: 'II', D3: 'III' }[p.division]}\\b`), `${p.slug} is grouped under ${g[1]}`);
  }
});

test('at narrow widths the Clubs & schools table hides the rest of the line, never the division', () => {
  const css = fs.readFileSync(PAGE, 'utf8');
  assert.ok(/\.trend-table \.team-sub \.pl-rest[^{]*\{ display: none; \}/.test(css), 'the narrow rule does not hide .pl-rest');
  assert.ok(!/\.trend-table \.team-sub(,| \{)/.test(css), 'a narrow rule still hides the whole line, division included');
});

test('mutation: a programLine() that drops the division fails every view', async () => {
  const MARK = 'return divisionTag(p.division) + (rest';
  const mutated = await renderAll(src => { assert.ok(src.includes(MARK), 'programLine() not found in the page'); return src.replace(MARK, "return '' + (rest"); });
  for (const v of mutated) assert.throws(() => checkView(v), /without its division/, `${v[0]} still passes with the division removed from programLine()`);
});
