// Tests for issue #15 (#404 phase 1, decision 4(b)): the recruiting-class buttons only highlight a class (they
// change the Commits column, its sort and the bold count on each card), they do not filter. Before the fix the
// group was labelled "Recruiting class" and the list subtitle read "class of 2027", next to "South region",
// as if a class filter were on.
//
//     node --test tests/highlight_class.test.mjs
//
// Same mechanism as tests/shortlist_unsave.test.mjs: the inline <script> is pulled out of public/index.html
// and run in a `vm` against a stub DOM that records innerHTML. Expected coverage comes from the shipped
// index.json, never from the page's helpers.
//
// What it CANNOT prove, and a human must check in a browser: how the longer subtitle wraps at ~400 px, and
// what a screen reader actually announces for the group and its buttons.
//
// HIGHLIGHT_TEST_HTML (optional) points the suite at another copy of index.html, so the page from before this
// change can be run through these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.HIGHLIGHT_TEST_HTML || path.join(PUBLIC, 'index.html');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));

function makeElement(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, contains: () => false,
  };
}

function loadPage() {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
  const readPublic = url => {
    let rel = url.replace(/^\//, '');
    if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
    const p = path.join(PUBLIC, rel);
    return p.startsWith(PUBLIC) && fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: {
      documentElement: makeElement('html'), body: makeElement('body'),
      querySelector: bySelector, querySelectorAll: () => [], createElement: makeElement, addEventListener() { },
    },
    location: { hash: '', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: {
      getItem: k => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k),
    },
    innerWidth: 1400,
    addEventListener() { },
    fetch: async url => {
      const body = readPublic(url);
      if (body == null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(HTML, 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>');
  const b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'index.html: could not find the inline <script>');
  const src = lines.slice(a + 1, b).join('\n')
    + '\n;Object.assign(globalThis, { S, renderSidebar, renderList, loadIndex });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}

const sb = loadPage();
const S = sb.S;
const sidebar = () => sb.document.querySelector('#sidebar').innerHTML;
const subtitle = () => (/<div class="content-subtitle">([\s\S]*?)<\/div>/.exec(sb.document.querySelector('#app').innerHTML) || [])[1] ?? null;
const reset = st => Object.assign(S.filters, { conf: [], region: [], division: [], classYear: [], cond: [], sort: 'rpi', sortDir: null, view: 'cards' }, st);
// The class group as drawn: its label, its accessible name and each button's value, text and pressed state.
function classGroup(html) {
  const g = /<div class="browse-label">([^<]*)<\/div>\s*<div class="pill-row" role="group" aria-label="([^"]*)">((?:<button [^>]*data-class=[^>]*>[^<]*<\/button>)+)<\/div>/.exec(html);
  if (!g) return null;
  const buttons = [...g[3].matchAll(/<button ([^>]*)>([^<]*)<\/button>/g)].map(m => ({
    value: /data-class="([^"]*)"/.exec(m[1])?.[1], pressed: /aria-pressed="([^"]*)"/.exec(m[1])?.[1], text: m[2] }));
  return { label: g[1], name: g[2], buttons };
}

// Commit-data coverage per division, from index.json: [programs with any commitmentsByYear, programs].
const COVERAGE = {};
for (const p of INDEX.programs) {
  const d = p.division || 'D1', t = COVERAGE[d] || (COVERAGE[d] = [0, 0]);
  t[1]++; if (Object.keys(p.commitmentsByYear || {}).length) t[0]++;
}

test('setup: the shipped index has the coverage this wording describes (D1 mostly collected, D2 and D3 rarely)', async () => {
  await sb.loadIndex();
  assert.ok(COVERAGE.D1 && COVERAGE.D1[0] * 2 >= COVERAGE.D1[1], `D1 commit coverage fell under half: ${COVERAGE.D1}`);
  for (const d of ['D2', 'D3']) assert.ok(COVERAGE[d] && COVERAGE[d][0] * 2 < COVERAGE[d][1],
    `${d} commit coverage is now ${COVERAGE[d]}; the "(D2 and D3 commits rarely collected)" expectations below need revisiting`);
  assert.ok((INDEX.season?.gradYears || []).map(String).includes('2027'), 'the index has no class of 2027 to highlight');
});

test('the class button group is labelled "Highlight class", visibly and as the group\'s accessible name', () => {
  reset({});
  sb.location.hash = '#/';
  S.sidebarTab = 'programs';
  sb.renderSidebar();
  const g = classGroup(sidebar());
  assert.ok(g, 'no class button group in the sidebar');
  assert.equal(g.label, 'Highlight class', 'visible label');
  assert.equal(g.name, 'Highlight class', 'the group\'s aria-label');
  assert.doesNotMatch(sidebar(), /Recruiting class/, 'the old filter-like label is still drawn');
});

test('the class buttons keep a toggle state that matches the selection: All pressed by default, then the chosen class', () => {
  const years = (INDEX.season.gradYears || []).map(String);
  reset({});
  sb.renderSidebar();
  let g = classGroup(sidebar());
  assert.deepEqual(g.buttons.map(b => b.value), ['', ...years], 'one All button, then one per class');
  assert.deepEqual(g.buttons.map(b => b.text), ['All', ...years.map(y => `'${y.slice(2)}`)]);
  assert.deepEqual(g.buttons.map(b => b.pressed), ['true', ...years.map(() => 'false')], 'nothing highlighted: All is pressed');
  reset({ classYear: ['2027'] });
  sb.renderSidebar();
  g = classGroup(sidebar());
  assert.deepEqual(g.buttons.filter(b => b.pressed === 'true').map(b => b.value), ['2027'], 'only the highlighted class is pressed');
});

// No subtitle bit may open with "class of" / "classes of": that is the shape of a filter bit ("South region").
const filterLike = sub => sub.split(' · ').filter(bit => /^class(es)? of\b/i.test(bit.trim()));

test('with a class highlighted, the subtitle says it is highlighting, never "class of 2027" as if it were a filter', async () => {
  reset({ classYear: ['2027'] });
  sb.location.hash = '#/';
  await sb.renderList();
  const sub = subtitle();
  assert.ok(sub, 'no subtitle drawn');
  assert.deepEqual(filterLike(sub), [], `a subtitle bit reads like a class filter: ${sub}`);
  assert.ok(sub.split(' · ').includes('highlighting commits for the class of 2027 (D2 and D3 commits rarely collected)'),
    `the class bit is not the agreed wording: ${sub}`);
  // highlighting never hides a program: every program in the index is still listed
  assert.match(sub, new RegExp(`\\b${INDEX.programs.length} of ${INDEX.programs.length} programs\\b`), 'the class narrowed the list');
});

test('the coverage note names only the divisions on screen that lack commit data, and the classes read in order', async () => {
  reset({ classYear: ['2027'], division: ['D1'] });
  await sb.renderList();
  assert.ok(subtitle().split(' · ').includes('highlighting commits for the class of 2027'), `D1 only: ${subtitle()}`);
  reset({ classYear: ['2027', '2026'], division: ['D1', 'D3'] });
  await sb.renderList();
  assert.deepEqual(filterLike(subtitle()), [], subtitle());
  assert.ok(subtitle().split(' · ').includes('highlighting commits for the classes of 2026 and 2027 (D3 commits rarely collected)'),
    `D1 + D3, two classes: ${subtitle()}`);
  reset({});
  await sb.renderList();
  assert.doesNotMatch(subtitle(), /highlighting|class/, 'no class highlighted, yet the subtitle mentions one');
});
