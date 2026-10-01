// Issue #9: screen readers announced the conference pills as "17 programs" / "1 programs": the pill's content reads
// "ACC17" and its title is the count, so nothing named the conference. Each conference pill now has an accessible
// name - the conference (with its division where the name is shared, #431), then the count, singular or plural - and
// so does each division pill. Region and "All" pills are named by their text, and the class buttons (#410) already
// carry names; aria-pressed is unchanged everywhere.
//
//     node --test tests/pill_names.test.mjs
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM, as in tests/conference_counts.test.mjs.
//
// PILL_NAMES_TEST_HTML (optional) points at another copy of index.html, so the page from before this change can be run
// through these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.PILL_NAMES_TEST_HTML || path.join(PUBLIC, 'index.html');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const unesc = t => t.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const attr = (attrs, k) => { const m = new RegExp(`\\b${k}="([^"]*)"`).exec(attrs); return m ? unesc(m[1]) : null; };
const programs = n => `${n} program${n === 1 ? '' : 's'}`;

// Every pill button in a group: { attrs, text (visible), sub (the count, or null) }.
function buttons(html, dataAttr) {
  return [...html.matchAll(new RegExp(`<button ([^>]*\\bdata-${dataAttr}="[^"]*"[^>]*)>([^<]*)(?:<span class="pill-sub">(\\d+)</span>)?</button>`, 'g'))]
    .map(m => ({ attrs: m[1], text: unesc(m[2]), sub: m[3] == null ? null : Number(m[3]) }));
}
// Stubs for the drawn conference pills, so an in-place update (syncConfCounts, while typing) can be read back.
let stubs = [];
const pillStubs = html => [...html.matchAll(/<button ([^>]*\bdata-conf-div="([^"]*)"[^>]*)>[^<]*<span class="pill-sub">(\d+)<\/span><\/button>/g)].map(m => {
  const attrs = {}, sub = { textContent: m[3] };
  return { dataset: { conf: unesc(attr(m[1], 'data-conf')), confDiv: unesc(m[2]) }, title: '', sub, attrs,
    setAttribute: (k, v) => { attrs[k] = String(v); }, querySelector: s => (s === '.pill-sub' ? sub : null),
    classList: { toggle() { }, contains: () => false } };
});
function makeElement(name) {
  const el = { _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, dataset: {}, style: {},
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false }, setAttribute() { }, getAttribute: () => null,
    addEventListener() { }, removeEventListener() { }, querySelector: () => makeElement('child'), querySelectorAll: () => [],
    closest: () => null, matches: () => false, focus() { }, contains: () => false };
  if (name === '#sidebar') el.querySelectorAll = sel => (sel === '[data-conf-div]' ? (stubs = pillStubs(el.innerHTML)) : []);
  return el;
}
function loadPage() {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector, querySelectorAll: () => [],
      createElement: makeElement, addEventListener() { } },
    location: { hash: '', replace(h) { this.hash = h; } }, history: { replaceState() { } }, matchMedia: () => ({ matches: false }),
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } }, innerWidth: 1400, addEventListener() { },
    fetch: async url => {
      let rel = url.replace(/^\//, ''); if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
      const p = path.join(PUBLIC, rel.replace(/\?.*$/, ''));
      if (!p.startsWith(PUBLIC) || !fs.existsSync(p)) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      const body = fs.readFileSync(p, 'utf8'); return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(HTML, 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n') + '\n;Object.assign(globalThis, { S, renderSidebar, loadIndex, setQuery });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}
const sb = loadPage();
const S = sb.S;
const draw = (st = {}) => {
  Object.assign(S.filters, { conf: [], region: [], division: [], classYear: [], cond: [], sort: 'name', sortDir: null, view: 'cards' }, st);
  S.q = ''; S.qRaw = ''; S.sidebarTab = 'programs'; sb.location.hash = '#/'; sb.renderSidebar();
  return sb.document.querySelector('#sidebar').innerHTML;
};
const SHARED = new Set(Object.entries(INDEX.programs.reduce((m, p) => ((m[p.conference] ||= new Set()).add(p.division), m), {}))
  .filter(([, ds]) => ds.size > 1).map(([c]) => c));
const confName = (b) => { const c = attr(b.attrs, 'data-conf'), d = attr(b.attrs, 'data-conf-div');
  return `${SHARED.has(c) ? `${c} (${d})` : c}, ${programs(b.sub)}`; };

test('setup', async () => {
  await sb.loadIndex();
  assert.ok(SHARED.has('Independent'), 'fixture: Independent should be shared across divisions');
});

test('every conference pill is named by its conference, then its count - "ACC, 17 programs"', () => {
  const pills = buttons(draw(), 'conf').filter(b => attr(b.attrs, 'data-conf'));
  assert.ok(pills.length > 90, `only ${pills.length} conference pills drawn`);
  for (const b of pills) assert.equal(attr(b.attrs, 'aria-label'), confName(b), `${b.text}: accessible name`);
  const acc = pills.find(b => b.text === 'ACC');
  assert.equal(attr(acc.attrs, 'aria-label'), `ACC, ${programs(acc.sub)}`);
});

test('a shared name names its division ("Independent (D2), 7 programs"), so every conference pill\'s name is unique', () => {
  const pills = buttons(draw(), 'conf').filter(b => attr(b.attrs, 'data-conf'));
  const ind = pills.filter(b => b.text === 'Independent').map(b => attr(b.attrs, 'aria-label')).sort();
  const want = ['D1', 'D2', 'D3'].map(d => `Independent (${d}), ${programs(INDEX.programs.filter(p => p.conference === 'Independent' && p.division === d).length)}`);
  assert.deepEqual(ind, want);
  const names = pills.map(b => attr(b.attrs, 'aria-label'));
  assert.equal(new Set(names).size, names.length, 'two conference pills share an accessible name');
});

test('singular and plural: "1 program", never "1 programs" - in the name and in the title', () => {
  const html = draw({ region: ['West'] });
  const pills = buttons(html, 'conf').filter(b => attr(b.attrs, 'data-conf'));
  assert.ok(pills.some(b => b.sub === 1), 'fixture: some conference should count 1 in the West');
  for (const b of pills) {
    assert.ok(!/\b1 programs\b/.test(attr(b.attrs, 'aria-label')), `${b.text}: "1 programs" in the name`);
    assert.ok(!/\b1 programs\b/.test(attr(b.attrs, 'title')), `${b.text}: "1 programs" in the title`);
  }
  assert.ok(pills.some(b => attr(b.attrs, 'aria-label').endsWith(', 1 program')));
  for (const b of buttons(html, 'division').filter(b => attr(b.attrs, 'data-division'))) {
    assert.ok(!/\b1 programs\b/.test(attr(b.attrs, 'title') || ''), `${b.text}: "1 programs" in the division title`);
  }
});

test('each name starts with what the pill shows (WCAG 2.5.3), and aria-pressed is kept', () => {
  const html = draw({ conf: ['D1|ACC'] });
  for (const b of buttons(html, 'conf')) {
    const name = attr(b.attrs, 'aria-label');
    if (b.text === 'All') assert.equal(name, null, '"All" is named by its text');
    else assert.ok(name !== null && name.startsWith(b.text), `"${name}" does not start with "${b.text}"`);
    assert.match(b.attrs, /\baria-pressed="(true|false)"/, `${b.text}: aria-pressed`);
  }
  assert.ok(buttons(html, 'conf').some(b => /aria-pressed="true"/.test(b.attrs) && b.text === 'ACC'), 'the selected pill is not pressed');
});

test('division pills: "D2 (Division II), 251 programs"', () => {
  const pills = buttons(draw(), 'division').filter(b => attr(b.attrs, 'data-division'));
  assert.deepEqual(pills.map(b => b.text), ['D1', 'D2', 'D3']);
  const names = { D1: 'Division I', D2: 'Division II', D3: 'Division III' };
  for (const b of pills) {
    const n = INDEX.programs.filter(p => p.division === b.text).length;
    assert.equal(attr(b.attrs, 'aria-label'), `${b.text} (${names[b.text]}), ${programs(n)}`);
    assert.match(b.attrs, /\baria-pressed="(true|false)"/);
  }
});

test('typing a search updates each conference pill\'s name with its count', async () => {
  draw();
  sb.setQuery('Ohio');
  await new Promise(r => setTimeout(r, 150));
  assert.ok(stubs.length > 50, 'the pills were not updated in place');
  for (const s of stubs) {
    const n = Number(s.sub.textContent);
    const label = SHARED.has(s.dataset.conf) ? `${s.dataset.conf} (${s.dataset.confDiv})` : s.dataset.conf;
    assert.equal(s.attrs['aria-label'], `${label}, ${programs(n)}`, `${s.dataset.conf}: the name kept the old count`);
  }
  sb.setQuery('');
  await new Promise(r => setTimeout(r, 150));
});

test('GUARD: region and "All" pills are named by their text, and the class buttons (#410) keep their names', () => {
  const html = draw();
  const regions = buttons(html, 'region');
  assert.deepEqual(regions.map(b => b.text), ['All', 'West', 'Midwest', 'South', 'Mid-Atlantic', 'Northeast']);
  for (const b of regions) assert.equal(attr(b.attrs, 'title'), null, `${b.text}: a title would be read instead of nothing better`);
  assert.equal(buttons(html, 'conf').find(b => attr(b.attrs, 'data-conf') === '').text, 'All');
  const cls = buttons(html, 'class').filter(b => attr(b.attrs, 'data-class'));
  for (const b of cls) assert.equal(attr(b.attrs, 'aria-label'), `${b.text}, class of 20${b.text.slice(1)}`);
});
