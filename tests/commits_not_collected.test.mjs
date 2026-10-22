// Issue #411: the Commits column and the Commits sort read "not collected" outside the commit divisions, never 0.
//
//     node --test tests/commits_not_collected.test.mjs
//
// Commitments are collected for trends.py COMMIT_DIVISIONS only (the owner's decision on #315; D1 today), which
// Pipelines reads as trends.json `commitDivisions`. The page names the same list once (COMMIT_DIVISIONS); the first
// test pins the two together. Every other check renders the real Stats table from the committed index in a `vm`
// against a stub DOM (the mechanism of tests/shortlist_unsave.test.mjs) and reads the Commits cells. Expected values
// are written from the index's own fields here, never from the page's helpers.
//
// Which real programs carry commits is a fact about the live data and a routine refresh moves it (#508): marshall and
// lamar were D1 programs with none until a source listed one, adelphi and kenyon-college D2/D3 programs with none until
// SoccerWire listed one, and carson-newman's only commit leaves with its class. So no check here names a real program or
// counts how many carry commits. The exact cases ("D1 with none reads 0", "outside D1 reads Not collected, with or
// without an incidental count", "D1 with commits is unchanged") run on FROZEN rows added to the index the page loads
// (frozen-*, built below), which carry the same fields as a real row whatever the data does. The real rows are checked
// by rule: every one outside the commit divisions, every one inside them.
//
// COMMITS_TEST_HTML (optional) points the suite at another copy of index.html, to show these checks failing on main.
// The test finds public/ and trends.py from its own location, so a scratch root with its own tests/ (this file copied
// in), public/ and trends.py runs it against an index with other counts.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..');
const PUBLIC = path.join(ROOT, 'public');
const HTML_PATH = process.env.COMMITS_TEST_HTML || path.join(PUBLIC, 'index.html');
const HTML = fs.readFileSync(HTML_PATH, 'utf8');
const COMMITTED = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
// What Pipelines treats as collected: the committed trends.json, written from trends.py COMMIT_DIVISIONS.
const COLLECTED = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'trends', 'index.json'), 'utf8')).commitDivisions;
// The frozen rows (#508): a real row of the division with the identity and the commits replaced, so they render as any
// program does. The key is the case; the commits are what the data cannot be left to decide.
const FROZEN_CASES = {
  'frozen-d1-none': ['D1', {}],
  'frozen-d1-some': ['D1', { 2027: 3, 2028: 1 }],
  'frozen-d2-none': ['D2', {}],
  'frozen-d2-incidental': ['D2', { 2026: 2 }],
  'frozen-d3-none': ['D3', {}],
  'frozen-d3-incidental': ['D3', { 2027: 1 }],
};
const FROZEN = Object.entries(FROZEN_CASES).map(([slug, [division, commitmentsByYear]]) => {
  const base = COMMITTED.programs.find(p => p.division === division);
  return { ...structuredClone(base), slug, name: `Frozen ${slug}`, shortName: null, nickname: null, searchNames: [`Frozen ${slug}`], commitmentsByYear };
});
// The index the page loads: the committed one plus the frozen rows. Every expectation below reads it, not the page.
const INDEX = { ...COMMITTED, programs: [...COMMITTED.programs, ...FROZEN] };
const row = slug => INDEX.programs.find(p => p.slug === slug);
const total = slug => Object.values(row(slug).commitmentsByYear || {}).reduce((a, n) => a + n, 0);
const isCollected = p => COLLECTED.includes(p.division);

test('the page names the same commit divisions as trends.py COMMIT_DIVISIONS and trends.json', () => {
  const page = /const COMMIT_DIVISIONS = \[([^\]]*)\];/.exec(HTML);
  assert.ok(page, 'index.html has no COMMIT_DIVISIONS list');
  const pageList = [...page[1].matchAll(/'([^']+)'/g)].map(m => m[1]);
  const py = /^COMMIT_DIVISIONS = \(([^)]*)\)/m.exec(fs.readFileSync(path.join(ROOT, 'trends.py'), 'utf8'));
  assert.ok(py, 'trends.py has no COMMIT_DIVISIONS tuple');
  const pyList = [...py[1].matchAll(/"([^"]+)"/g)].map(m => m[1]);
  assert.deepEqual(pageList, pyList, 'index.html COMMIT_DIVISIONS differs from trends.py');
  const trends = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'trends', 'index.json'), 'utf8'));
  assert.deepEqual(pageList, trends.commitDivisions, 'index.html COMMIT_DIVISIONS differs from the committed trends.json');
});

// Rules about the config and the frozen rows, never about how many real programs carry commits (#508).
test('fixtures: D1 is collected and D2/D3 are not; the frozen rows are the cases they say; the real index has all three divisions', () => {
  assert.deepEqual(COLLECTED, ['D1'], 'the cases below assume the owner\'s decision on #315: commits are collected for D1 only');
  for (const d of ['D1', 'D2', 'D3']) assert.ok(COMMITTED.programs.some(p => p.division === d), `the committed index has no ${d} program to build the frozen ${d} rows from`);
  const expected = { 'frozen-d1-none': 0, 'frozen-d1-some': 4, 'frozen-d2-none': 0, 'frozen-d2-incidental': 2, 'frozen-d3-none': 0, 'frozen-d3-incidental': 1 };
  for (const [slug, n] of Object.entries(expected)) {
    assert.equal(total(slug), n, `${slug}: the frozen row does not carry the commits its name says`);
    assert.equal(row(slug).division, FROZEN_CASES[slug][0]);
  }
  assert.equal(new Set(INDEX.programs.map(p => p.slug)).size, INDEX.programs.length, 'a frozen slug is also a real program');
});

// ---------- the page ----------
function makeElement(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, dataset: {}, style: {},
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, blur() { }, contains: () => false,
  };
}
function loadPage() {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector,
      querySelectorAll: () => [], createElement: makeElement, addEventListener() { } },
    location: { hash: '#/', replace(h) { this.hash = h; } }, history: { replaceState() { } },
    matchMedia: () => ({ matches: false }), localStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    innerWidth: 1400, addEventListener() { },
    fetch: async url => url === '/api/v1/programs' || url === '/api/v1/list'
      ? { ok: true, status: 200, async json() { return JSON.parse(JSON.stringify(INDEX)); } }
      : { ok: false, status: 404, async json() { throw new Error('404'); } },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = HTML.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'index.html: could not find the inline <script>');
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ['S', 'renderList', 'loadIndex']) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, $: bySelector };
}
const { sb, $ } = loadPage();
await sb.loadIndex();

// The Stats table sorted by Commits: [{ slug, cell }] in row order, `cell` the Commits cell's HTML.
async function commitsTable(dir) {
  Object.assign(sb.S.filters, { view: 'table', sort: 'commits', sortDir: dir, division: [], conf: [], region: [], classYear: [], cond: [] });
  await sb.renderList();
  const html = $('#app').innerHTML;
  const heads = [...(/<thead><tr>([\s\S]*?)<\/tr><\/thead>/.exec(html)?.[1] || '').matchAll(/<th[^>]*>/g)].map(m => m[0]);
  const at = heads.findIndex(h => h.includes('data-sort="commits"'));
  assert.ok(at >= 0, 'the Stats table has no Commits column');
  return [...html.matchAll(/<tr class="team-row[^"]*" data-slug="([^"]+)"[^>]*>([\s\S]*?)<\/tr>/g)].map(m => {
    const cells = [...m[2].matchAll(/<td[^>]*>([\s\S]*?)<\/td>(?=<td|$)/g)].map(c => c[1]);
    return { slug: m[1], cell: cells[at] };
  });
}
const text = h => (h || '').replace(/<span class="sr-only">[^<]*<\/span>/g, '').replace(/<[^>]+>/g, '').trim();

test('a D2/D3 program shows "—" with an accessible "Not collected", never 0 - including one with an incidental count', async () => {
  const rows = await commitsTable('desc');
  const outside = rows.filter(r => !isCollected(row(r.slug)));
  // the frozen rows are the cases (no commits; an incidental count), in both divisions; every real row outside D1 follows the rule
  for (const slug of ['frozen-d2-none', 'frozen-d2-incidental', 'frozen-d3-none', 'frozen-d3-incidental']) assert.ok(outside.some(r => r.slug === slug), `${slug} not in the table`);
  assert.ok(outside.some(r => !(r.slug in FROZEN_CASES)), 'fixture: no real program outside the commit divisions is in the table');
  for (const r of outside) {
    assert.equal(text(r.cell), '—', `${r.slug} (${row(r.slug).division}, ${total(r.slug)} commits): the Commits cell reads "${text(r.cell)}"`);
    assert.match(r.cell, /<span class="sr-only">Not collected<\/span>/, `${r.slug}: no accessible "Not collected"`);
  }
});

test('a D1 program that was collected but has none still shows 0; a D1 program with commits is unchanged', async () => {
  const rows = await commitsTable('desc');
  const inside = rows.filter(r => isCollected(row(r.slug)));
  const cell = slug => rows.find(x => x.slug === slug)?.cell;
  // the frozen rows are the cases: none reads 0, some reads the sum in the strong markup
  assert.equal(text(cell('frozen-d1-none')), '0', 'a collected D1 program with no commits');
  assert.equal(text(cell('frozen-d1-some')), String(total('frozen-d1-some')));
  assert.equal(cell('frozen-d1-some'), `<span class="num-strong">${total('frozen-d1-some')}</span>`, 'the D1 cell markup changed');
  // every real D1 row follows the same rule, whatever the data holds today
  assert.ok(inside.some(r => !(r.slug in FROZEN_CASES)), 'fixture: no real D1 program is in the table');
  for (const r of inside) {
    const n = total(r.slug);
    if (n === 0) assert.equal(text(r.cell), '0', `${r.slug}: collected, no commits`);
    else assert.equal(r.cell, `<span class="num-strong">${n}</span>`, `${r.slug}: the D1 cell markup changed`);
  }
});

for (const dir of ['desc', 'asc']) {
  test(`sorted by Commits (${dir}): every collected program comes before every not-collected one, in order`, async () => {
    const rows = await commitsTable(dir);
    assert.equal(rows.length, INDEX.programs.length);
    const collected = rows.map(r => COLLECTED.includes(row(r.slug).division));
    const firstNot = collected.indexOf(false);
    assert.ok(firstNot > 0, 'fixture: no collected or no not-collected rows');
    assert.ok(collected.slice(firstNot).every(c => !c), `a collected program sorts after a not-collected one (${dir})`);
    const counts = rows.slice(0, firstNot).map(r => total(r.slug));
    const ordered = counts.every((n, i) => i === 0 || (dir === 'desc' ? counts[i - 1] >= n : counts[i - 1] <= n));
    assert.ok(ordered, `the collected programs are not in ${dir} order of their counts`);
  });
}
