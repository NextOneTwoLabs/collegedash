// The header search box (#434 PR 1): one static search box in the header, on every page, that a phone shows without
// opening the side menu (the #404 phase 1 check, which tests/start_strip.test.mjs pinned for the retired Start strip).
//
//     node --test tests/header_search.test.mjs
//
// Two halves, both read from public/index.html itself:
//   1. Where the box is and that nothing hides it. The static markup is read directly; the page's own <style> goes
//      through the shared parser (tests/lib/css_cascade.mjs, #430), and every rule that could set a layout property
//      on the box, its wrapper or the header - judged conservatively from its selector, as tests/header_narrow.test.mjs
//      does - must be one of the rules pinned below, with exactly the pinned declarations. A new rule that could touch
//      them, a changed value, !important, an unknown at-rule or a pseudo-class on them fails LOUDLY, so the "always
//      drawn" check cannot be passed by a rule this test does not understand (the #413 lesson). A self-test feeds it
//      such rules, including Huatuo's two Start-strip mutations re-aimed at the header box.
//   2. That it is the page's search. The inline <script> runs in a `vm` against a stub DOM (as the other page tests do):
//      typing goes through the box's own listeners into setQuery; Enter keeps #409/#23's rules; "/" focuses it; the
//      list subtitle carries "Clear search"; Ask's placeholder follows; one live region, screen-reader only and never
//      inside a listbox; no fetch while typing; and the sidebar no longer has a search box.
//
// HEADER_SEARCH_TEST_HTML (optional) points at another copy of index.html, to show these checks failing on main.
//
// What it CANNOT prove, and a human must check: pixels (measured on local serve.py for the PR), a real phone's keyboard,
// and what a screen reader says.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { parseCss, decls, exactLayout, LAYOUT } from './lib/css_cascade.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML_PATH = process.env.HEADER_SEARCH_TEST_HTML || path.join(PUBLIC, 'index.html');
const HTML = fs.readFileSync(HTML_PATH, 'utf8');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const CSS = [...HTML.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n');
const CANNOT = 'the header-search test cannot read';
const body = HTML.slice(HTML.indexOf('<body'));
const headerHtml = (/<div class="header">([\s\S]*?)\n<\/div>\n/.exec(body.replace(/\r\n/g, '\n')) || [])[1] || '';

// ---------- markup ----------

test('markup: the one search box is static in the header, labelled, outside the sidebar and outside #app', () => {
  assert.match(headerHtml, /<div class="header-search" role="search">/, 'no search box in the header');
  assert.match(headerHtml, /<label class="sr-only" for="q">Search programs<\/label>/, 'the header box has no label');
  assert.match(headerHtml, /<input type="search" class="search-input" id="q" placeholder="School, mascot, state or city…" autocomplete="off" enterkeyhint="search"[^>]*>/);
  assert.match(headerHtml, /<button type="button" class="search-clear" id="qClear" aria-label="Clear search" hidden>✕<\/button>/);
  assert.match(headerHtml, /<div class="header-recs" id="headerRecs"><\/div>/, 'no (empty) slot for "Find programs for me"');
  assert.equal((body.match(/id="q"/g) || []).length, 1, 'more than one #q in the static page');
  assert.ok(!/id="(qStart|startStrip|startActions|recsOpenStart)"/.test(HTML), 'the Start strip is still in the page');
  assert.ok(!/id="askSlot"/.test(HTML), 'the Ask popover is back (#434 PR 2 folded its note into #qStatus)');
  for (const id of ['q', 'qClear', 'qStatus', 'qList', 'qHint', 'headerRecs']) {
    const tag = new RegExp(`<[^<>]*id="${id}"[^<>]*>`).exec(headerHtml)?.[0] || '';
    assert.ok(tag, `#${id} is not in the header`);
  }
  assert.ok(!/\shidden(?=[\s>=])/.test(/<input[^>]*id="q"[^>]*>/.exec(headerHtml)?.[0] || ' hidden'), 'the box carries the hidden attribute');
});

test('status: #qStatus is the one aria-live search status, screen-reader only, and not inside a listbox', () => {
  const status = /<div[^>]*id="qStatus"[^>]*>/.exec(headerHtml)?.[0] || '';
  assert.match(status, /class="sr-only"/, '#qStatus is not screen-reader only (the list subtitle carries the counts on screen)');
  assert.match(status, /aria-live="polite"/);
  // a listbox may hold only options and groups (#434 PR 2 adds one; the status is its sibling, never inside it)
  const listbox = /<div[^>]*role="listbox"[^>]*>([\s\S]*?)<\/div>/.exec(headerHtml)?.[1] ?? '';
  assert.ok(!/id="qStatus"/.test(listbox), '#qStatus sits inside a listbox');
  const live = [...headerHtml.matchAll(/<[^<>]*aria-live=[^<>]*>/g)].map(m => m[0]);
  assert.equal(live.length, 1, `more than one live region in the header: ${live}`);
});

// ---------- CSS: nothing hides the box ----------

// The elements whose layout decides whether the box is drawn, as the markup has them, and what sits above them.
const EL = {
  header: { tag: 'div', classes: ['header', 'has-recs'], ids: [], attrs: ['class'] },
  wrap: { tag: 'div', classes: ['header-search'], ids: [], attrs: ['class', 'role'] },
  box: { tag: 'input', classes: ['search-input'], ids: ['q'], attrs: ['type', 'class', 'id', 'placeholder', 'autocomplete', 'enterkeyhint'] },
};
const ROOTS = [{ tag: 'body', classes: [], ids: [], attrs: [] }, { tag: 'html', classes: [], ids: [], attrs: ['lang', 'data-theme'] }];
const ABOVE = { header: [...ROOTS], wrap: [EL.header, ...ROOTS], box: [EL.wrap, EL.header, ...ROOTS] };
// Could this compound match `el`? Conservative: a class, id, tag or attribute it lacks rules it out; anything else may.
function mayMatch(compound, el) {
  if (compound.includes('::')) return false;  // a pseudo-element is another box
  const attrs = [...compound.matchAll(/\[\s*([\w-]+)\s*(?:=\s*"?([^"\]]*)"?)?\s*\]/g)];
  if (!attrs.every(([, a, v]) => el.attrs.includes(a.toLowerCase()) && (v === undefined || a !== 'type' || v === 'search'))) return false;
  const bare = compound.replace(/:not\([^)]*\)/g, '').replace(/:[\w-]+(\([^)]*\))?/g, '').replace(/\[[^\]]*\]/g, '');
  const tag = /^[a-z*][\w-]*/i.exec(bare)?.[0];
  if (tag && tag !== '*' && tag.toLowerCase() !== el.tag) return false;
  if (![...bare.matchAll(/#([\w-]+)/g)].every(m => el.ids.includes(m[1]))) return false;
  return [...bare.matchAll(/\.([\w-]+)/g)].every(m => el.classes.includes(m[1]));
}
const watched = sel => {
  const parts = sel.split(/\s*[>+~]\s*|\s+/).filter(Boolean), last = parts.pop();
  return Object.keys(EL).some(k => mayMatch(last, EL[k]) && parts.every(p => ABOVE[k].some(a => mayMatch(p, a))));
};
// Every rule that may set layout on the header, the box's wrapper or the box. #434 adds the wrapper, the box's size in
// the header and the two-row phone grid; the rest is what main already had.
const EXPECTED = {
  '|input': { font: 'inherit' },
  '|.header': { padding: '0 20px', height: 'var(--header-height)', display: 'flex', 'align-items': 'center', 'justify-content': 'space-between', position: 'fixed', top: '0', left: '0', right: '0', 'z-index': '100',
    // #465 B: viewport-fit=cover - the header keeps its content inside the safe area (top inset, side insets in landscape)
    'padding-top': 'var(--safe-top)', 'padding-left': 'max(20px, env(safe-area-inset-left, 0px))', 'padding-right': 'max(20px, env(safe-area-inset-right, 0px))' },
  '|.search-input': { width: '100%', height: '40px', padding: '8px 32px 8px 34px', 'font-size': '13px' },
  '|.header-search': { position: 'relative', flex: '1 1 auto', 'min-width': '0', 'max-width': '520px', margin: '0 16px' },
  '|.header-search .search-input': { height: '38px' },
  '@media (max-width: 768px)|.header': { display: 'grid', 'grid-template-columns': 'minmax(0, 1fr) auto', 'grid-template-rows': '52px 52px', 'column-gap': '8px', 'align-items': 'center' },
  '@media (max-width: 768px)|.header-search': { 'grid-row': '2', 'grid-column': '1 / -1', 'max-width': 'none', margin: '0' },
  '@media (max-width: 768px)|.header.has-recs .header-search': { 'grid-column': '1' },
  '@media (max-width: 768px)|.header-search .search-input': { 'font-size': '16px' },
  '@media (max-width: 460px)|.header': { 'padding-left': 'max(12px, env(safe-area-inset-left, 0px))', 'padding-right': 'max(12px, env(safe-area-inset-right, 0px))' },  // #465 B: was padding: 0 12px; now side padding only, so the top safe-area inset stays
  '@media print|.header': { display: 'none' },
};
function check(css) {
  const rules = parseCss(css);
  for (const r of rules) {
    // a rule that sets nothing that can move, size or hide a box (colours, transitions) cannot hide the box either
    if (!decls(r.body).some(d => LAYOUT.test(d.prop) || /^(opacity|clip|clip-path)$/.test(d.prop))) continue;
    for (const sel of r.selectors) {
      if (!watched(sel)) continue;
      for (const at of r.at) if (!/^@media (print|\((max|min)-width: \d+px\))$/.test(at)) assert.fail(`${CANNOT} the at-rule "${at}" on "${sel}"`);
      if (/:(?!:)/.test(sel.replace(/::[\w-]+/g, '')) && decls(r.body).some(d => /^(display|visibility|content-visibility|position|width|height|max-width|max-height|transform|opacity|clip|overflow)/.test(d.prop)))
        assert.fail(`${CANNOT} the pseudo-class rule "${sel}"`);
      for (const d of decls(r.body)) {
        if (/^(visibility|content-visibility|opacity|clip|clip-path)$/.test(d.prop)) assert.fail(`${CANNOT} ${d.prop} on "${sel}"`);
      }
    }
  }
  return exactLayout(rules, { watched, expected: EXPECTED, cannot: CANNOT });
}

test('the CSS check fails loudly on every rule it cannot evaluate', () => {
  assert.doesNotThrow(() => check(CSS), 'the page\'s own CSS is not readable');
  for (const [name, extra] of [
    ['an ID selector hiding the box (Huatuo\'s #413 mutation, re-aimed)', '#q { display: none; }'],
    ['!important at <=768 px (Huatuo\'s #413 mutation, re-aimed)', '@media (max-width: 768px) { .header-search { display: none !important; } }'],
    ['an attribute selector', '.header-search[role] { display: none; }'],
    ['a changed value on the has-recs rule', '@media (max-width: 768px) { .header.has-recs .header-search { display: none; } }'],
    ['a descendant of the header', '.header .header-search { display: none; }'],
    ['a child combinator', '.header > .header-search { display: none; }'],
    ['visibility on the box', '.search-input { visibility: hidden; }'],
    ['opacity on the wrapper', '.header-search { opacity: 0; }'],
    ['an unknown media form', '@media (orientation: portrait) { .header-search { display: none; } }'],
    ['another at-rule', '@supports (display: grid) { .header-search { display: none; } }'],
    ['a bare tag', 'div { display: none; }'],
    ['the universal selector', '.header * { display: none; }'],
    ['a pseudo-class hiding it', '.header-search:empty { display: none; }'],
    ['a changed value on a known rule', '@media (max-width: 768px) { .header-search { grid-row: 3; } }'],
    ['the phone rows taller', '@media (max-width: 768px) { .header { grid-template-rows: 52px 0; } }'],
  ]) assert.throws(() => check(`${CSS}\n${extra}`), new RegExp(CANNOT), `${name}: the check did not fail`);
});

test('#404 phase 1: the box is drawn at 375 px without opening the menu, and at every width and on every page', () => {
  const got = check(CSS);
  for (const [key, ds] of Object.entries(got)) {
    if (key.startsWith('@media print')) continue;
    assert.notEqual(ds.display, 'none', `"${key}" hides part of the header box`);
  }
  // There is no view class on the box's chain any more (the Start strip's .view-list is gone), so nothing the router
  // sets can hide it on a program page, ID Camps or anywhere else.
  assert.ok(!/view-list/.test(HTML), 'a view-dependent class is still in the page');
});

test('#434: at <=768 px the header is two rows and --header-height follows them', () => {
  const root = parseCss(CSS).filter(r => r.selectors.includes(':root'));
  const v = at => root.filter(r => r.at.join(' ') === at).flatMap(r => decls(r.body)).filter(d => d.prop === '--header-height').map(d => d.value).pop();
  assert.equal(v(''), 'calc(60px + env(safe-area-inset-top, 0px))', 'the desktop header height changed');  // #465 B: + the top safe-area inset
  assert.equal(v('@media (max-width: 768px)'), 'calc(112px + env(safe-area-inset-top, 0px))', 'the phone header height does not cover both rows');
  assert.equal(EXPECTED['@media (max-width: 768px)|.header']['grid-template-rows'], '52px 52px');
  assert.ok(52 + 52 <= 112);
});

// ---------- the page ----------

function makeElement(name) {
  const listeners = {}, classes = new Set();
  return {
    _name: name, _listeners: listeners, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, placeholder: '',
    dataset: {}, style: {}, setAttribute() { }, getAttribute: () => null, removeEventListener() { },
    classList: { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c),
      toggle: (c, f) => { const on = f === undefined ? !classes.has(c) : !!f; on ? classes.add(c) : classes.delete(c); return on; } },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { FOCUS.el = name; }, blur() { BLURRED.add(name); }, contains: () => false,
  };
}
const FOCUS = { el: null };
const BLURRED = new Set();
function loadPage({ width = 375, ask = false } = {}) {
  const els = new Map(), docListeners = {}, requests = [];
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const readPublic = url => {
    let rel = url.replace(/^\//, '');
    if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
    else if (rel === 'api/v1/camps') rel = 'data/camps/index.json';
    else if (rel.startsWith('api/v1/programs/')) rel = `data/programs/${rel.slice('api/v1/programs/'.length)}.json`;
    const p = path.join(PUBLIC, rel);
    return p.startsWith(PUBLIC) && fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: {
      documentElement: makeElement('html'), body: makeElement('body'), activeElement: null,
      querySelector: bySelector, querySelectorAll: () => [], createElement: makeElement,
      addEventListener(type, fn) { (docListeners[type] ||= []).push(fn); },
    },
    location: { hash: '#/programs', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    innerWidth: width,
    addEventListener() { },
    fetch: async (url, init) => {
      requests.push(String(url));
      if (url === 'api/ask/status' || url === '/api/ask/status') {
        return ask ? { ok: true, status: 200, async json() { return { ask: true }; } } : { ok: false, status: 404, async json() { return {}; } };
      }
      if (url === 'api/ask' || url === '/api/ask') return { ok: false, status: 404, async json() { return { error: 'no' }; } };
      const b = readPublic(String(url));
      if (b == null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      return { ok: true, status: 200, async json() { return JSON.parse(b); } };
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  const lines = HTML.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'index.html: could not find the inline <script>');
  const src = lines.slice(a + 1, b).join('\n')
    + `\n;for (const k of ['S', 'route', 'setQuery', 'renderList', 'renderSidebar', 'loadIndex', 'askQuestion']) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, $: bySelector, docListeners, requests };
}
const settle = (ms = 120) => new Promise(r => setTimeout(r, ms));
async function ready(opts) {
  const pg = loadPage(opts);
  await pg.sb.loadIndex();
  await settle(30);
  pg.sb.S.filters.view = 'cards';
  return pg;
}
async function typeIn(pg, text) {
  const box = pg.$('#q');
  box.value = text;
  for (const fn of box._listeners.input || []) fn({ target: box });
  await settle();
}
function key(pg, k, extra = {}) {
  const box = pg.$('#q');
  for (const fn of box._listeners.keydown || []) fn({ key: k, shiftKey: false, preventDefault() { }, ...extra });
}
const cardSlugs = html => [...html.matchAll(/class="card pcard[^"]*" data-slug="([^"]+)"/g)].map(m => m[1]);

test('typing in the header box filters the list through the shared search; the sidebar has no search box', async () => {
  const pg = await ready();
  pg.sb.location.hash = '#/programs';
  const box = pg.$('#q');
  assert.equal((box._listeners.input || []).length, 1, 'the header box has no single input handler');
  assert.equal((box._listeners.keydown || []).length, 1, 'the header box has no single keydown handler');
  await typeIn(pg, 'stanford');
  assert.equal(pg.sb.S.qRaw, 'stanford');
  await pg.sb.renderList();
  assert.deepEqual(cardSlugs(pg.$('#app').innerHTML), ['stanford']);
  assert.equal(pg.$('#qStatus').textContent, '1 match · Enter opens the first');
  pg.sb.renderSidebar();
  assert.ok(!/id="q"|Find a program|id="qStatus"|id="askSlot"/.test(pg.$('#sidebar').innerHTML), 'the sidebar still has a search box');
});

// #465 D: on Programs the sidebar is the More filters panel (no tabs, Sort in the toolbar); every other page keeps the
// Browse rail this test pins, so it runs on one of them.
test('#434 decision 3: the sidebar\'s first tab is "Browse" - sort and filters, no search, no repeated heading', async () => {
  const pg = await ready();
  pg.sb.location.hash = '#/faq';
  pg.sb.S.sidebarTab = 'programs';
  pg.sb.renderSidebar();
  const side = pg.$('#sidebar').innerHTML;
  const tabs = [...side.matchAll(/<button class="sidebar-tab[^"]*" role="tab" aria-selected="(true|false)" data-tab="([^"]+)">([^<]*)<\/button>/g)].map(m => [m[2], m[3], m[1]]);
  assert.deepEqual(tabs[0], ['programs', 'Browse', 'true'], `the first tab is ${JSON.stringify(tabs[0])}`);
  assert.ok(!tabs.some(t => t[1] === 'Programs'), 'a tab still reads "Programs"');
  assert.ok(!/<div class="sidebar-section-title">Browse<\/div>/.test(side), 'the Browse tab repeats "Browse" as a heading');
  assert.match(side, /id="sortSelect"/, 'the Browse tab lost its sort');
  assert.ok(!/id="q"/.test(side), 'a search box is back in the sidebar');
});

test('Enter keeps #409/#23\'s rules: a name opens it, a place keeps the list, a filtered-out program never opens', async () => {
  const pg = await ready();
  pg.sb.location.hash = '#/programs';
  await typeIn(pg, 'kenyon'); key(pg, 'Enter'); await settle(20);
  assert.equal(pg.sb.location.hash, '#/p/kenyon-college');
  pg.sb.location.hash = '#/programs';
  await typeIn(pg, 'Ohio'); key(pg, 'Enter'); await settle(20);
  assert.equal(pg.sb.location.hash, '#/programs', 'Enter on a place opened a program');
  pg.sb.S.filters.region = ['West'];
  await typeIn(pg, 'kenyon'); key(pg, 'Enter'); await settle(20);
  assert.equal(pg.sb.location.hash, '#/programs', 'Enter opened Kenyon under a West filter');
  assert.match(pg.$('#qStatus').textContent, /^No match within your filters \(\d+ without them\)$/);
  pg.sb.S.filters.region = [];
});

test('Huatuo on #441: on a phone, Enter on a school name opens it and blurs the box, so the keyboard drops', async () => {
  const pg = await ready({ width: 375 });
  pg.sb.location.hash = '#/programs';
  await typeIn(pg, 'kenyon');
  BLURRED.clear();
  key(pg, 'Enter'); await settle(20);
  assert.equal(pg.sb.location.hash, '#/p/kenyon-college');
  assert.ok(BLURRED.has('#q'), 'the box kept focus (and the phone its keyboard) after Enter opened a program');
});

test('"/" focuses the header box on any page, without opening the drawer', async () => {
  const pg = await ready();
  pg.sb.location.hash = '#/p/stanford';
  FOCUS.el = null;
  const fns = pg.docListeners.keydown || [];
  assert.ok(fns.length, 'no document keydown handler');
  for (const fn of fns) fn({ key: '/', target: { matches: () => false, closest: () => null }, preventDefault() { } });
  assert.equal(FOCUS.el, '#q', '"/" did not focus the header box');
  assert.ok(!pg.$('#sidebar').classList.contains('open'), '"/" opened the drawer');
});

test('the list subtitle carries "Clear search", which clears the query and returns focus to the box', async () => {
  const pg = await ready();
  pg.sb.location.hash = '#/programs';
  await typeIn(pg, 'Ohio');
  await pg.sb.renderList();
  assert.match(pg.$('#app').innerHTML, /matching “Ohio” <button type="button" class="clear-search" data-clear-search>Clear search<\/button>/);
  FOCUS.el = null;
  const click = { target: { closest: sel => (sel === '[data-clear-search]' ? {} : null), matches: () => false } };
  for (const fn of pg.docListeners.click || []) { try { fn(click); } catch { /* other delegated handlers read more of the event */ } }
  assert.equal(pg.sb.S.qRaw, '', 'Clear search did not clear the query');
  assert.equal(pg.$('#q').value, '', 'the box still shows the query');
  assert.equal(FOCUS.el, '#q', 'focus did not return to the box');
});

test('Ask (owner only): the header box\'s placeholder follows it and Shift+Enter asks from it', async () => {
  const pg = await ready({ ask: true });
  await settle(30);
  assert.equal(pg.sb.S.ask, true, 'fixture: Ask did not switch on');
  assert.equal(pg.$('#q').placeholder, 'School, mascot, or a question…');
  let asked = 0;
  pg.sb.askQuestion = () => { asked++; };
  await typeIn(pg, 'stanford');
  key(pg, 'Enter', { shiftKey: true }); await settle(20);
  assert.equal(asked, 1, 'Shift+Enter in the header box did not ask');
});

test('no request while typing, choosing or clearing: the box searches the index already loaded', async () => {
  const pg = await ready();
  pg.sb.location.hash = '#/programs';
  const before = pg.requests.length;
  await typeIn(pg, 'Ohio'); key(pg, 'Enter'); await settle(20);
  await typeIn(pg, 'duke'); await typeIn(pg, '');
  assert.deepEqual(pg.requests.slice(before).filter(u => !/^\/api\/v1\/programs\//.test(u)), [], 'typing fetched something');
});
