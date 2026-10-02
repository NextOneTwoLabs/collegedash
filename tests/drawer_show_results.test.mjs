// Issue #18: on a phone the filter drawer covers the results. Pills and conditions already close it; a reader who
// typed a search, or wants to look before choosing, needs a way to see the results: a "Show N programs" bar at the
// foot of the drawer that closes it.
//
//     node --test tests/drawer_show_results.test.mjs
//
// Same mechanism as tests/shortlist_unsave.test.mjs: the inline <script> of public/index.html runs in a `vm` against
// a stub DOM. Here the stub keeps real class lists and attributes for the drawer, its overlay and the toggle, and
// records focus, so "the drawer closed" and "focus went back to the toggle" are read from state, not assumed.
// Expected counts come from the shipped index.json and from the cards the list view actually draws.
//
// What it CANNOT prove, and a human must check: the bar's position and stickiness on a real phone (measured in an
// emulated 375x740 viewport for the PR), and real touch events.
//
// DRAWER_TEST_HTML (optional) points at another copy of index.html, so the page from before this change can be run
// through these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.DRAWER_TEST_HTML || path.join(PUBLIC, 'index.html');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));

let focused = null;
function makeElement(name) {
  const classes = new Set(), attrs = new Map();
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, onclick: null,
    dataset: {}, style: {},
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)), remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle(c, force) { const on = force === undefined ? !classes.has(c) : !!force; if (on) classes.add(c); else classes.delete(c); return on; },
      contains: c => classes.has(c),
    },
    setAttribute: (k, v) => attrs.set(k, String(v)), getAttribute: k => (attrs.has(k) ? attrs.get(k) : null),
    _listeners: {}, addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null, matches: () => false,
    focus() { focused = name; }, contains: () => false,
  };
}

function loadPage() {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
  const readPublic = url => {
    let rel = url.replace(/^\//, '');
    if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
    const p = path.join(PUBLIC, rel.replace(/\?.*$/, ''));
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
    innerWidth: 375,  // a phone: isPhone() is true
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
    + '\n;Object.assign(globalThis, { S, renderSidebar, renderList, loadIndex, setQuery, toggleSidebar });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}

const sb = loadPage();
const S = sb.S;
const $ = sel => sb.document.querySelector(sel);
const settle = (ms = 0) => new Promise(r => setTimeout(r, ms));
const bar = () => (/<button type="button" class="btn primary" id="showResults">([^<]*)<\/button>/.exec($('#sidebar').innerHTML) || [])[1] ?? null;
const reset = st => Object.assign(S.filters, { conf: [], region: [], division: [], classYear: [], cond: [], sort: 'rpi', sortDir: null, view: 'cards' }, st);
const cardCount = () => [...$('#app').innerHTML.matchAll(/class="card pcard/g)].length;
const openDrawer = () => { $('#sidebar').classList.remove('open'); sb.toggleSidebar(); };

test('setup: the index loads and the page thinks it is on a phone', async () => {
  await sb.loadIndex();
  assert.ok(INDEX.programs.length > 100);
  openDrawer();
  assert.ok($('#sidebar').classList.contains('open'), 'toggleSidebar did not open the drawer');
});

test('the programs tab of the drawer ends with "Show N programs", N being every program with no filter', () => {
  reset({});
  sb.location.hash = '#/programs';
  S.sidebarTab = 'programs';
  sb.renderSidebar();
  assert.equal(bar(), `Show ${INDEX.programs.length} programs`);
  assert.match($('#sidebar').innerHTML, /<div class="drawer-show"><button type="button" class="btn primary" id="showResults">/);
});

test('N follows the pills: one region selected counts that region\'s programs', () => {
  const region = 'South';
  const want = INDEX.programs.filter(p => p.region === region).length;
  assert.ok(want > 1, 'fixture: no South programs');
  reset({ region: [region] });
  sb.renderSidebar();
  assert.equal(bar(), `Show ${want} programs`);
  reset({});
});

test('N follows a typed search, without rebuilding the drawer, and equals the cards the list draws', async () => {
  reset({});
  sb.location.hash = '#/programs';
  sb.renderSidebar();
  const html = $('#sidebar').innerHTML;
  // #434: typed into the header box, through its own input listener (the drawer has no search box any more)
  const box = $('#q');
  assert.equal((box._listeners.input || []).length, 1, 'the header box has no input handler');
  box.value = 'state';
  box._listeners.input[0]({ target: box });
  await settle(150);
  await sb.renderList();
  const n = cardCount();
  assert.ok(n > 0 && n < INDEX.programs.length, `fixture: "state" should narrow the list (${n})`);
  assert.equal($('#showResults').textContent, `Show ${n} program${n === 1 ? '' : 's'}`, 'the bar did not update while typing');
  assert.equal($('#sidebar').innerHTML, html, 'typing rebuilt the drawer');
  assert.ok(!/id="q"/.test(html), 'a search box is still in the drawer');
  sb.setQuery('');
  await settle(150);
});

test('tapping it closes the drawer, tells the toggle, and hands focus back to the toggle', () => {
  reset({});
  sb.location.hash = '#/programs';
  sb.renderSidebar();
  openDrawer();
  assert.equal($('#sidebarToggle').getAttribute('aria-expanded'), 'true');
  const btn = $('#showResults');
  assert.equal(typeof btn.onclick, 'function', 'the bar has no click handler');
  focused = null;
  btn.onclick();
  assert.ok(!$('#sidebar').classList.contains('open'), 'the drawer is still open');
  assert.ok(!$('#sidebarOverlay').classList.contains('visible'), 'the overlay is still showing');
  assert.equal($('#sidebarToggle').getAttribute('aria-expanded'), 'false', 'the toggle still says expanded');
  // #465 D: on Programs the drawer is More filters, so focus goes back to its button (the toggle is hidden there)
  assert.equal(focused, '#moreFilters', 'focus did not go back to More filters');
  assert.equal(sb.location.hash, '#/programs', 'the list view navigated away');
});

test('from a program page it goes to the list; on the camp view it names the view', () => {
  reset({});
  sb.location.hash = '#/p/some-program';
  sb.renderSidebar();
  openDrawer();
  $('#showResults').onclick();
  assert.equal(sb.location.hash, '#/programs', 'from a profile, Show N programs should open the list');
  sb.location.hash = '#/camps';
  sb.renderSidebar();
  assert.equal(bar(), 'Show camps');
  sb.location.hash = '#/programs';
});

test('only the programs tab carries it, and only phones draw it', () => {
  sb.location.hash = '#/faq';  // #465 D: the tabs are the sidebar's off Programs; on Programs it is More filters
  for (const tab of ['shortlist', 'compare']) {
    S.sidebarTab = tab;
    sb.renderSidebar();
    assert.equal(bar(), null, `the ${tab} tab carries the bar`);
  }
  S.sidebarTab = 'programs';
  const css = (/<style>([\s\S]*?)<\/style>/.exec(fs.readFileSync(HTML, 'utf8')) || [])[1] || '';
  assert.match(css, /^\.drawer-show \{ display: none; \}/m, 'not hidden by default (desktop)');
  // every @media (max-width: 768px) block, braces matched
  const phone = [];
  for (let i = css.indexOf('@media (max-width: 768px) {'); i >= 0; i = css.indexOf('@media (max-width: 768px) {', i + 1)) {
    let j = css.indexOf('{', i) + 1, depth = 1;
    while (j < css.length && depth) { if (css[j] === '{') depth++; else if (css[j] === '}') depth--; j++; }
    phone.push(css.slice(i, j));
  }
  assert.ok(phone.some(block => /\.drawer-show \{ display: block; position: sticky; bottom: 0;/.test(block)),
    'not drawn, or not sticky, in a phone (max-width: 768px) block');
});
