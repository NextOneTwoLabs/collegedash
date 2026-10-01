// Issue #5: every filter pill press rebuilds the sidebar (renderSidebar replaces its markup), so the pressed button
// was destroyed and keyboard focus fell to <body>; a keyboard or screen-reader user had to tab back from the top.
// Focus now goes back to the same pill in the rebuilt sidebar (found by its data-* key; a conference pill by its
// division as well, #425), or on a phone, where the press closes the drawer, to the drawer's toggle.
//
// Issue #10: the profile's provenance footer printed each skipped collector's raw reason cut at 60 characters,
// e.g. "wikipedia (no team article in the registry (most mid-majors have none; try `regis)". Skipped and failed
// collectors are now named in the reader's words, as the "could not be updated" notice already did.
//
//     node --test tests/pill_focus_and_skips.test.mjs
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM, as in tests/conf_by_division.test.mjs.
// The sidebar stub hands back the pills it drew as fresh objects on every render, so "focus went back" means a pill
// of the NEW render was focused, not the destroyed one. Profiles are the committed ones, read only; the one
// synthetic profile below is built from a committed one with made-up build notes.
//
// What it CANNOT prove, and a human must check: real browser focus and the focus ring after a real key press.
//
// PILL_FOCUS_TEST_HTML (optional) points at another copy of index.html, so the page from before this change can be
// run through these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.PILL_FOCUS_TEST_HTML || path.join(PUBLIC, 'index.html');
const PAGE = fs.readFileSync(HTML, 'utf8');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const unesc = t => t.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

// ---- the stub DOM ----
let focused = null;      // what last had .focus() called on it
let render = 0;          // which sidebar render the current pill stubs belong to
let pills = [];
const KINDS = ['conf', 'region', 'division', 'class'];
const camel = a => a.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
function pillStubs(html) {
  render++;
  return [...html.matchAll(/<button ([^>]*\bdata-(conf|region|division|class)="([^"]*)"[^>]*)>/g)].map(m => {
    const attrs = Object.fromEntries([...m[1].matchAll(/data-([a-z-]+)="([^"]*)"/g)].map(a => [a[1], unesc(a[2])]));
    const stub = { kind: m[2], render, attrs, dataset: Object.fromEntries(Object.entries(attrs).map(([k, v]) => [camel(k), v])), onclick: null };
    stub.focus = () => { focused = stub; };
    return stub;
  });
}
// the attribute selectors a page may look a pill up by: [data-x="v"] one or more times
function findPill(sel) {
  const want = [...sel.matchAll(/\[data-([a-z-]+)="((?:[^"\\]|\\.)*)"\]/g)].map(m => [m[1], m[2].replace(/\\(.)/g, '$1')]);
  if (!want.length || sel.replace(/\[data-[a-z-]+="(?:[^"\\]|\\.)*"\]/g, '').trim()) return null;
  return pills.find(p => want.every(([k, v]) => p.attrs[k] === v)) || null;
}
function makeElement(name) {
  const el = {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, dataset: {}, style: {},
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null, matches: () => false,
    focus() { focused = name; }, contains: () => false,
  };
  if (name === '#sidebar') {
    el.querySelectorAll = sel => {
      const k = /^\[data-([a-z]+)\]$/.exec(sel)?.[1];
      if (!KINDS.includes(k)) return [];
      if (k === 'conf') pills = pillStubs(el.innerHTML);   // renderSidebar asks for [data-conf] first
      return pills.filter(p => p.kind === k);
    };
    el.querySelector = sel => findPill(sel) || makeElement('child');
  }
  return el;
}
function loadPage() {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector,
      querySelectorAll: () => [], createElement: makeElement, addEventListener() { } },
    location: { hash: '', replace(h) { this.hash = h; } }, history: { replaceState() { } }, matchMedia: () => ({ matches: false }),
    localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) },
    innerWidth: 1400, addEventListener() { },
    fetch: async url => {
      let rel = url.replace(/^\//, '');
      if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
      else if (rel === 'api/v1/camps') rel = 'data/camps/index.json';
      const p = path.join(PUBLIC, rel.replace(/\?.*$/, ''));
      if (!p.startsWith(PUBLIC) || !fs.existsSync(p)) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      const body = fs.readFileSync(p, 'utf8'); return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = PAGE.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n')
    + '\n;Object.assign(globalThis, { S, renderSidebar, loadIndex, tabOverview, renderProfile });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}
const sb = loadPage();
const S = sb.S;
const reset = () => { Object.assign(S.filters, { conf: [], region: [], division: [], classYear: [], cond: [], sort: 'name', sortDir: null, view: 'cards' }); S.q = ''; S.qRaw = ''; };
const draw = () => { S.sidebarTab = 'programs'; sb.location.hash = '#/'; sb.renderSidebar(); return pills; };

// ---- #5 ----
// One pill of each kind, and an "All" pill, pressed as a keyboard user would (the click handler, which Enter and
// Space reach on a <button>).
const PRESSES = (() => {
  const d1 = INDEX.programs.find(p => p.division === 'D1');
  const d2Ind = INDEX.programs.find(p => p.division === 'D2' && p.conference === 'Independent');
  return [
    ['a D1 conference pill', { conf: d1.conference, 'conf-div': 'D1' }],
    ['the D2 Independent pill (a name shared with D1 and D3)', { conf: d2Ind.conference, 'conf-div': 'D2' }],
    ['the conference "All" pill', { conf: '' }],
    ['a division pill', { division: 'D2' }],
    ['a region pill', { region: d1.region }],
    ['the region "All" pill', { region: '' }],
    ['a class pill', { class: String(Math.max(...INDEX.programs.flatMap(p => Object.keys(p.commitmentsByYear || {})).map(Number).filter(Boolean))) }],
  ];
})();
const same = (p, want) => Object.entries(want).every(([k, v]) => p.attrs[k] === v) && (want.conf === undefined || 'conf-div' in want || !('conf-div' in p.attrs));

test('setup: the index loads and every pill pressed below is drawn', async () => {
  await sb.loadIndex();
  reset(); draw();
  for (const [what, want] of PRESSES) assert.ok(pills.some(p => same(p, want)), `${what} is not drawn: ${JSON.stringify(want)}`);
});

test('#5: after a pill press rebuilds the sidebar, focus is on the same pill of the new sidebar, never on <body>', () => {
  sb.innerWidth = 1400;
  const bad = [];
  for (const [what, want] of PRESSES) {
    reset(); draw();
    const p = pills.find(x => same(x, want));
    const before = render;
    focused = null;
    p.onclick();
    if (!focused || typeof focused !== 'object') { bad.push(`${what}: focus went to ${focused === null ? 'nothing (<body>)' : focused}`); continue; }
    if (focused.render <= before) bad.push(`${what}: focus went to a pill of the destroyed sidebar`);
    if (!same(focused, want)) bad.push(`${what}: focus went to another pill ${JSON.stringify(focused.attrs)}`);
  }
  assert.deepEqual(bad, []);
});

test('#5: pressing a pill twice (on, then off) keeps focus on it both times', () => {
  sb.innerWidth = 1400;
  reset(); draw();
  const want = PRESSES[1][1];
  for (const step of ['on', 'off']) {
    focused = null;
    pills.find(x => same(x, want)).onclick();
    assert.ok(focused && typeof focused === 'object' && same(focused, want), `after the ${step} press, focus is on ${JSON.stringify(focused?.attrs ?? focused)}`);
  }
  assert.equal(S.filters.conf.length, 0, 'the second press should have turned it off again');
});

test('#5: on a phone the press closes the drawer, so focus goes to the drawer toggle', () => {
  sb.innerWidth = 375;
  try {
    for (const [what, want] of PRESSES) {
      reset(); draw();
      focused = null;
      pills.find(x => same(x, want)).onclick();
      assert.equal(focused, '#sidebarToggle', `${what}: focus went to ${JSON.stringify(focused?.attrs ?? focused)}`);
    }
  } finally { sb.innerWidth = 1400; }
});

// ---- #10 ----
const footerOf = html => unesc((/<div class="provenance">([\s\S]*?)<\/div>/.exec(html) || [])[1] || '');
const PHRASES = ['roster and schedule', 'news', 'ID camps', 'commitments (TopDrawerSoccer)', 'commitments (SoccerWire)', 'history', 'climate', 'school facts'];
const committed = slug => JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', `${slug}.json`), 'utf8'));

test('#10: a program whose history is skipped (shaped like abilene-christian) says so in the reader\'s words', async () => {
  const p = committed('abilene-christian');
  p._build = { ...p._build, failed: [], skipped: [
    { collector: 'wikipedia', reason: 'wikipedia: no team article in the registry (most mid-majors have none; try `registry fix-wiki`)' },
    { collector: 'tds', reason: 'tds: no TopDrawerSoccer page id in the registry (synthetic test note)' }] };
  const foot = footerOf(await sb.tabOverview(p));
  assert.match(foot, /not collected for this program: history, commitments \(TopDrawerSoccer\)$/, foot);
  for (const leak of ['wikipedia', 'tds', 'registry', '`', 'fix-wiki', 'skipped:']) assert.ok(!foot.includes(leak), `the footer shows "${leak}": ${foot}`);
});

test('#10: failed collectors in the footer are named as the notice names them', async () => {
  const p = committed('abilene-christian');
  p._build = { ...p._build, skipped: [], failed: [{ collector: 'scorecard', error: 'HTTP 500' }, { collector: 'news', error: 'timeout' }] };
  const foot = footerOf(await sb.tabOverview(p));
  assert.match(foot, /could not be updated: school facts, news$/, foot);
  assert.ok(!/scorecard|failing:/.test(foot), foot);
});

test('#10: no committed profile shows a collector\'s own reason, name, or a cut-off phrase in its footer', async () => {
  const bad = [];
  let withSkips = 0;
  for (const row of INDEX.programs) {
    const p = committed(row.slug);
    const b = p._build || {};
    if (!(b.skipped?.length || b.failed?.length)) continue;
    withSkips++;
    const foot = footerOf(await sb.tabOverview(p));
    const tail = foot.split(/ · (?=could not be updated: |not collected for this program: )/).slice(1);
    for (const part of tail) for (const name of part.replace(/^[^:]+: /, '').split(/, (?![^(]*\))/))
      if (!PHRASES.includes(name)) bad.push(`${row.slug}: "${name}"`);
    for (const s of b.skipped || []) if (s.reason && foot.includes(s.reason.replace(/^[a-z]+: /, '').slice(0, 20))) bad.push(`${row.slug}: shows the reason of ${s.collector}`);
    if (b.skipped?.length && !foot.includes('not collected for this program: ')) bad.push(`${row.slug}: skips not named`);
  }
  assert.ok(withSkips > 100, `only ${withSkips} committed profiles have skipped or failed collectors; the check proves too little`);
  assert.deepEqual(bad.slice(0, 20), [], `${bad.length} problems`);
});
