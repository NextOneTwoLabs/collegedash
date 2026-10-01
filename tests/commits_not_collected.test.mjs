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
// COMMITS_TEST_HTML (optional) points the suite at another copy of index.html, to show these checks failing on main.
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
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const row = slug => INDEX.programs.find(p => p.slug === slug);
// What Pipelines treats as collected: the committed trends.json, written from trends.py COMMIT_DIVISIONS.
const COLLECTED = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'trends', 'index.json'), 'utf8')).commitDivisions;
const total = slug => Object.values(row(slug).commitmentsByYear || {}).reduce((a, n) => a + n, 0);

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

test('fixtures: the programs these checks use still look as they assume', () => {
  assert.equal(row('adelphi')?.division, 'D2'); assert.equal(total('adelphi'), 0);
  assert.equal(row('carson-newman')?.division, 'D2'); assert.ok(total('carson-newman') > 0, 'carson-newman lost its incidental count');
  assert.equal(row('kenyon-college')?.division, 'D3'); assert.equal(total('kenyon-college'), 0);
  for (const s of ['marshall', 'lamar']) { assert.equal(row(s)?.division, 'D1'); assert.equal(total(s), 0, `${s} now has commits`); }
  assert.equal(row('ucla')?.division, 'D1'); assert.ok(total('ucla') > 0);
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
    fetch: async url => url === '/api/v1/programs'
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
  for (const slug of ['adelphi', 'kenyon-college', 'carson-newman']) {
    const r = rows.find(x => x.slug === slug);
    assert.ok(r, `${slug} not in the table`);
    assert.equal(text(r.cell), '—', `${slug}: the Commits cell reads "${text(r.cell)}"`);
    assert.match(r.cell, /<span class="sr-only">Not collected<\/span>/, `${slug}: no accessible "Not collected"`);
  }
});

test('a D1 program that was collected but has none still shows 0; a D1 program with commits is unchanged', async () => {
  const rows = await commitsTable('desc');
  for (const slug of ['marshall', 'lamar']) assert.equal(text(rows.find(x => x.slug === slug)?.cell), '0', `${slug}`);
  assert.equal(text(rows.find(x => x.slug === 'ucla')?.cell), String(total('ucla')));
  assert.equal(rows.find(x => x.slug === 'ucla')?.cell, `<span class="num-strong">${total('ucla')}</span>`, 'the D1 cell markup changed');
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
