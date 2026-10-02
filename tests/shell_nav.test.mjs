// The global shell and Home (#465 PR B), as planned and reviewed on #465 (revision 2: the owner's D1-D3, Huatuo's six
// changes).
//
//     node --test tests/shell_nav.test.mjs
//
// Three halves, all read from public/index.html itself:
//   1. Markup: the header's destinations (Programs · ID Camps · Pipelines) and Shortlist, the phone's bottom bar of four,
//      viewport-fit=cover, the product name linking Home, and the one #q in the header (never in a page).
//   2. CSS, through the shared parser (tests/lib/css_cascade.mjs): the bar inside the safe area and only on phones, the
//      keyboard rule, .layout ending above the bar, #447's panel capped above it, the stacking order, and the header's
//      safe-area padding.
//   3. Behaviour: the inline <script> runs in a `vm` against a stub DOM whose [data-nav] / [data-short-count] nodes come
//      from the static markup. aria-current follows the route, the Shortlist count follows the saved programs, the
//      filter rail goes where filters don't apply (owner's D4), Home draws its parts (the examples from #447's own
//      constants, Continue only from saved state, the destinations with live counts), and the keyboard class.
//
// SHELL_NAV_TEST_HTML (optional) points at another copy of index.html, to show these checks failing on main.
//
// What it CANNOT prove, and a human must check on real phones (the issue's step 4): the safe areas on a notched iPhone in
// both orientations, the on-screen keyboard and the bar, 200% zoom, and the header's room at 769-1180 px.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { parseCss, decls } from './lib/css_cascade.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = fs.readFileSync(process.env.SHELL_NAV_TEST_HTML || path.join(PUBLIC, 'index.html'), 'utf8');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const BODY = HTML.slice(HTML.indexOf('<body'), HTML.indexOf('<script>'));
const CSS = parseCss([...HTML.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n'));
const decl = (at, sel, prop) => CSS.filter(r => r.at.join(' ') === at && r.selectors.includes(sel)).flatMap(r => decls(r.body)).filter(d => d.prop === prop).map(d => d.value).pop();
// every value a property is given, in order: a fallback first, then the value that wins where it is supported
const declAll = (at, sel, prop) => CSS.filter(r => r.at.join(' ') === at && r.selectors.includes(sel)).flatMap(r => decls(r.body)).filter(d => d.prop === prop).map(d => d.value);
const PHONE = '@media (max-width: 768px)';

// ---------- 1. markup ----------

test('markup: the header names the three destinations and the Shortlist; the product name goes Home', () => {
  const gnav = /<nav class="gnav" aria-label="Main">([\s\S]*?)<\/nav>/.exec(BODY)?.[1] || '';
  assert.deepEqual([...gnav.matchAll(/<a href="([^"]+)" data-nav="(\w+)">([^<]+)<\/a>/g)].map(m => [m[1], m[2], m[3]]),
    [['#/programs', 'list', 'Programs'], ['#/camps', 'camps', 'ID Camps'], ['#/trends', 'trends', 'Pipelines']], 'the header nav');
  assert.match(BODY, /<a class="header-link nav-shortlist" href="#\/shortlist" data-nav="shortlist" aria-label="Shortlist">/, 'no Shortlist utility in the header');
  assert.match(BODY, /<a class="section-label" href="#\/" aria-label="College Soccer home">College Soccer<\/a>/, 'the product name does not go Home');
  assert.match(BODY, /<a class="wordmark" href="https:\/\/www\.nextonetwo\.com" aria-label="nextonetwo">/, 'the wordmark loses its name when its text is hidden');
  assert.ok(!/id="observedTop"/.test(BODY), 'the header still carries the data date (said once, in the page it applies to)');
});

test('markup: the phone bar has four labelled destinations, and viewport-fit=cover is set', () => {
  const bar = /<nav class="bottom-nav" aria-label="Main">([\s\S]*?)<\/nav>/.exec(BODY)?.[1] || '';
  const links = [...bar.matchAll(/<a href="([^"]+)" data-nav="(\w+)">[\s\S]*?<span>([A-Za-z ]+)/g)].map(m => [m[1], m[2], m[3]]);
  assert.deepEqual(links, [['#/programs', 'list', 'Programs'], ['#/camps', 'camps', 'ID Camps'], ['#/trends', 'trends', 'Pipelines'], ['#/shortlist', 'shortlist', 'Shortlist']]);
  assert.ok([...bar.matchAll(/<svg[^>]*aria-hidden="true"/g)].length === 4, 'an icon is not hidden from screen readers');
  assert.match(HTML, /<meta name="viewport" content="width=device-width, initial-scale=1\.0, viewport-fit=cover">/);
});

test('markup: one search box, in the header, on every page\'s DOM - Home never draws, moves or reaches for it', () => {
  assert.equal((HTML.match(/id="q"/g) || []).length, 1, 'more than one #q');
  const header = HTML.slice(HTML.indexOf('<div class="header">'), HTML.indexOf('<div class="sidebar-overlay"'));
  assert.ok(header.includes('id="q"'), '#q is not in the header');
  const src = HTML.slice(HTML.indexOf('<script>'));
  const home = /function renderHome\([^)]*\) \{[\s\S]*?\n\}/.exec(src)?.[0] || '';
  assert.ok(home, 'no renderHome');
  assert.ok(!/<input|appendChild|insertBefore|\.append\(|replaceChild/.test(home), 'Home draws or moves a search input');
  // #465 (the owner, 2026-10-02): no box on Home, so nothing there points at it, fills it or focuses it
  assert.ok(!/#q\b|setQuery|renderSuggestions/.test(home), 'Home still reaches for the search box');
});

// ---------- 2. CSS ----------

test('CSS: the bar shows on phones only, fixed at the foot, inside the safe area', () => {
  assert.equal(decl('', '.bottom-nav', 'display'), 'none', 'the bar shows on desktop');
  assert.equal(decl(PHONE, '.gnav', 'display'), 'none', 'the header nav still shows on phones');
  assert.equal(decl(PHONE, '.bottom-nav', 'display'), 'grid');
  assert.equal(decl(PHONE, '.bottom-nav', 'position'), 'fixed');
  assert.equal(decl(PHONE, '.bottom-nav', 'bottom'), '0');
  assert.equal(decl(PHONE, '.bottom-nav', 'height'), 'var(--bottom-nav-h)');
  assert.match(decl(PHONE, '.bottom-nav', 'padding'), /env\(safe-area-inset-bottom, 0px\)/, 'the bar ignores the home indicator');
  assert.equal(decl(PHONE, ':root', '--bottom-nav-h'), 'calc(56px + env(safe-area-inset-bottom, 0px))');
  assert.equal(decl(PHONE, '.bottom-nav a', 'min-height'), '44px', 'a tap target under 44 px');
});

test('CSS: nothing is drawn under the bar - the layout ends above it, the keyboard hides it, #447\'s panel stops above it', () => {
  // Bianque on #470: 100vh is the large viewport (toolbars retracted); while they show, only 100dvh ends above the bar
  assert.deepEqual(declAll(PHONE, '.layout', 'height'), ['calc(100vh - var(--header-height) - var(--bottom-nav-h))', 'calc(100dvh - var(--header-height) - var(--bottom-nav-h))'], 'the last row can sit under the bar');
  assert.deepEqual(declAll('', '.layout', 'height'), ['calc(100vh - var(--header-height))', 'calc(100dvh - var(--header-height))'], 'the desktop layout ignores the dynamic viewport');
  assert.equal(decl(PHONE, 'body.kbd-open', '--bottom-nav-h'), '0px');
  assert.equal(decl(PHONE, 'body.kbd-open .bottom-nav', 'display'), 'none', 'the bar can cover a focused field');
  assert.deepEqual(declAll(PHONE, '.qpanel', 'max-height'), ['calc(100vh - var(--header-height) - var(--bottom-nav-h) - 8px)', 'calc(100dvh - var(--header-height) - var(--bottom-nav-h) - 8px)'], '#447\'s panel can end under the bar');
  assert.equal(decl(PHONE, '.qpanel', 'overflow-y'), 'auto');
});

test('CSS: stacking - page < bar < drawer and overlay < #400 panel < header < #447 panel (Huatuo, change 4)', () => {
  const z = (at, sel) => Number(decl(at, sel, 'z-index'));
  const bar = z(PHONE, '.bottom-nav');
  const order = [['bar', bar], ['drawer overlay', z('', '.sidebar-overlay')], ['drawer', z('', '.sidebar')],
    ['#400 side panel', z('@media (min-width: 769px) and (max-width: 1180px)', '.recs-panel')], ['header', z('', '.header')],
    ['#447 panel', z('', '.qpanel')], ['#400 phone sheet', z(PHONE, '.recs-panel')]];
  for (const [name, v] of order) assert.ok(Number.isFinite(v), `no z-index for ${name}`);
  for (let i = 1; i < order.length - 1; i++) assert.ok(order[i - 1][1] < order[i][1], `${order[i - 1][0]} (${order[i - 1][1]}) is not under ${order[i][0]} (${order[i][1]})`);
  assert.ok(bar < z(PHONE, '.recs-panel'), 'the #400 sheet is under the bar');
  assert.ok(bar < 60, 'the bar must stay under every sheet and panel (z-index below 60)');
});

test('CSS: the header keeps its content inside the safe area (top inset, side insets) and its height grows with it', () => {
  assert.equal(decl('', ':root', '--safe-top'), 'env(safe-area-inset-top, 0px)');
  assert.equal(decl('', '.header', 'padding-top'), 'var(--safe-top)');
  assert.equal(decl('', '.header', 'padding-left'), 'max(20px, env(safe-area-inset-left, 0px))');
  assert.equal(decl('@media (max-width: 460px)', '.header', 'padding-right'), 'max(12px, env(safe-area-inset-right, 0px))');
  assert.equal(decl('', ':root', '--header-height'), 'calc(60px + env(safe-area-inset-top, 0px))');
  assert.equal(decl(PHONE, ':root', '--header-height'), 'calc(112px + env(safe-area-inset-top, 0px))');
});

// Bianque on #470: viewport-fit=cover puts EVERY edge-anchored surface into the notch and home-indicator areas, not
// only the header and the bar - so each one that touches an edge keeps its content clear of the inset there.
test('CSS: every surface on a screen edge keeps clear of the safe areas (the #400 sheet, the drawer, the layout, the side panel)', () => {
  const at768 = '@media (max-width: 768px)';
  assert.equal(decl(at768, '.recs-panel', 'padding-top'), 'calc(12px + env(safe-area-inset-top, 0px))', 'the #400 sheet\'s heading and Close sit under the notch');
  assert.equal(decl(at768, '.recs-panel', 'padding-left'), 'calc(16px + env(safe-area-inset-left, 0px))');
  assert.equal(decl(at768, '.recs-panel', 'padding-right'), 'calc(16px + env(safe-area-inset-right, 0px))');
  // unconditional (Bianque's nit on #470): the 769-1180 px side panel on a landscape iPhone reaches the bottom edge too
  assert.equal(decl('', '.recs-actions', 'padding-bottom'), 'calc(14px + env(safe-area-inset-bottom, 0px))', 'Show matches and Clear sit on the home indicator');
  for (const at of [at768, '@media (min-width: 769px) and (max-width: 1180px)'])
    assert.equal(decl(at, '.recs-actions', 'padding-bottom'), undefined, `${at} overrides the actions' inset`);
  assert.equal(decl(PHONE, '.drawer-show', 'padding-bottom'), 'calc(10px + env(safe-area-inset-bottom, 0px))', 'the drawer\'s Show N programs sits on the home indicator');
  assert.equal(decl(PHONE, '.sidebar', 'padding-left'), 'env(safe-area-inset-left, 0px)', 'the drawer\'s left edge runs under a landscape notch');
  assert.equal(decl('', '.layout', 'padding-left'), 'env(safe-area-inset-left, 0px)', 'a landscape phone over 768 px: the sidebar runs under the notch');
  assert.equal(decl('', '.layout', 'padding-right'), 'env(safe-area-inset-right, 0px)');
  assert.equal(decl('@media (min-width: 769px) and (max-width: 1180px)', '.recs-panel', 'right'), 'env(safe-area-inset-right, 0px)', 'the #400 side panel runs under the rounded corner');
});

// ---------- 3. behaviour ----------

function makeEl(name, extra = {}) {
  const listeners = {}, classes = new Set(), attrs = new Map(extra.attrs || []);
  return {
    _name: name, _listeners: listeners, _attrs: attrs, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: extra.dataset || {}, style: {}, placeholder: '',
    setAttribute: (k, v) => attrs.set(k, String(v)), getAttribute: k => (attrs.has(k) ? attrs.get(k) : null), removeAttribute: k => attrs.delete(k),
    classList: { add: (...c) => c.forEach(x => classes.add(x)), remove: (...c) => c.forEach(x => classes.delete(x)), contains: c => classes.has(c),
      toggle: (c, f) => { const on = f === undefined ? !classes.has(c) : !!f; on ? classes.add(c) : classes.delete(c); return on; } },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); }, removeEventListener() { },
    querySelector: () => makeEl(`${name} child`), querySelectorAll: () => [], closest: () => null, matches: () => false, contains: () => false,
    focus() { FOCUS.el = name; }, blur() { },
  };
}
const FOCUS = { el: null };
// the static [data-nav] and [data-short-count] nodes, one stub each, in markup order
const NAV = [...BODY.matchAll(/<a [^>]*data-nav="(\w+)"[^>]*>/g)].map((m, i) => makeEl(`nav${i}`, { dataset: { nav: m[1] } }));
const COUNTS = [...BODY.matchAll(/data-short-count/g)].map((_, i) => makeEl(`count${i}`));

function loadPage({ hash = '#/', width = 1280, store = {} } = {}) {
  const els = new Map(), docListeners = {}, winListeners = {};
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeEl(sel)); return els.get(sel); };
  const app = bySelector('#app');
  app.querySelectorAll = sel => {  // Home's chips, from what was drawn
    const m = /^\[data-([\w-]+)\]$/.exec(sel); if (!m) return [];
    return (app._q[sel] = [...app.innerHTML.matchAll(new RegExp(`data-${m[1]}="([^"]*)"`, 'g'))].map(x => makeEl('chip', { dataset: { homeChip: x[1] } })));
  };
  app._q = {};
  const ls = new Map(Object.entries(store).map(([k, v]) => [k, JSON.stringify(v)]));
  const body = makeEl('body');
  const readPublic = url => {
    let rel = String(url).replace(/^\//, '').replace(/\?.*$/, '');
    if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
    if (rel === 'api/v1/camps') rel = 'data/camps/index.json';
    const p = path.join(PUBLIC, rel);
    return p.startsWith(PUBLIC) && fs.existsSync(p) && fs.statSync(p).isFile() ? fs.readFileSync(p, 'utf8') : null;
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl, Error,
    isNaN, parseInt, parseFloat, URL, URLSearchParams, encodeURIComponent, decodeURIComponent,
    document: {
      documentElement: makeEl('html'), body, activeElement: null, title: '',
      querySelector: bySelector, createElement: makeEl,
      querySelectorAll: sel => (sel === '[data-nav]' ? NAV : sel === '[data-short-count]' ? COUNTS : []),
      addEventListener(type, fn) { (docListeners[type] ||= []).push(fn); },
    },
    location: { hash, search: '', href: 'http://localhost/', replace(h) { this.hash = h; } },
    history: { replaceState(_, __, u) { sandbox.location.hash = u; }, pushState(_, __, u) { sandbox.location.hash = u; } },
    matchMedia: () => ({ matches: false }), innerWidth: width, screen: { width, height: 800 }, navigator: {},
    performance: { now: () => Date.now(), getEntriesByName: () => [] }, requestAnimationFrame: f => setTimeout(f, 0),
    localStorage: { getItem: k => (ls.has(k) ? ls.get(k) : null), setItem: (k, v) => ls.set(k, String(v)), removeItem: k => ls.delete(k) },
    sessionStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    addEventListener(type, fn) { (winListeners[type] ||= []).push(fn); },
    fetch: async url => {
      const b = readPublic(url);
      if (b == null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      return { ok: true, status: 200, async json() { return JSON.parse(b); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = HTML.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const names = ['S', 'route', 'toggleFav', 'HELP_CHIPS', 'PHONE_CHIPS', 'NO_RAIL'];
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(names)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, $: bySelector, body, docListeners };
}
const settle = (ms = 250) => new Promise(r => setTimeout(r, ms));
const current = () => NAV.filter(n => n.getAttribute('aria-current') === 'page').map(n => n.dataset.nav);

test('aria-current follows the route on every destination link (header and bar); Home and other pages mark none', async () => {
  const pg = loadPage({ hash: '#/' });
  await settle();
  for (const [hash, want] of [['#/', []], ['#/programs', ['list', 'list']], ['#/camps', ['camps', 'camps']], ['#/trends', ['trends', 'trends']],
    ['#/shortlist', ['shortlist', 'shortlist']], ['#/faq', []], [`#/p/${INDEX.programs[0].slug}`, []], ['#/c/ACC', ['list', 'list']]]) {
    pg.sb.location.hash = hash; pg.sb.route(); await settle(60);
    assert.deepEqual(current(), want, `${hash}: aria-current on ${JSON.stringify(current())}`);
  }
});

test('the Shortlist count in the header and the bar follows the saved programs', async () => {
  const [a, b] = INDEX.programs.map(p => p.slug);
  const pg = loadPage({ hash: '#/', store: { 'cd.favorites': [a] } });
  await settle();
  assert.deepEqual(COUNTS.map(c => c.textContent), ['1', '1']);
  pg.sb.toggleFav(b); await settle(30);
  assert.deepEqual(COUNTS.map(c => c.textContent), ['2', '2']);
  pg.sb.toggleFav(a); pg.sb.toggleFav(b); await settle(30);
  assert.deepEqual(COUNTS.map(c => c.textContent), ['', ''], 'an empty Shortlist still shows a count');
});

test('filters belong to their destination: Home, Pipelines and ID Camps draw no Programs rail; Programs keeps it', async () => {
  const pg = loadPage({ hash: '#/' });
  await settle();
  assert.ok(pg.body.classList.contains('no-rail'), 'Home shows the Programs filter rail');
  for (const [hash, rail] of [['#/programs', true], ['#/c/ACC', true], ['#/camps', false], ['#/trends', false], ['#/', false]]) {
    pg.sb.location.hash = hash; pg.sb.route(); await settle(60);
    assert.equal(!pg.body.classList.contains('no-rail'), rail, `${hash}: the rail is ${rail ? 'missing' : 'drawn'}`);
  }
  // #465 (the owner, 2026-10-02): Pipelines has no rail and ignores the Programs filters (trends_view); ID Camps has its
  // own sidebar since PR F (#471) and ignores the Programs filters and search.
  assert.deepEqual([...pg.sb.NO_RAIL], ['home', 'trends', 'camps']);
  assert.match(HTML, /body\.no-rail \.sidebar, body\.no-rail \.sidebar-overlay, body\.no-rail \.hamburger \{ display: none; \}/);
});

// #465 (the owner, 2026-10-02): "show search box only when needed" - on Programs (#/programs, #14's aliases, #/c/) and a
// program's page. Everywhere else body.no-search hides it (and "Find programs for me") with CSS; it stays in the DOM.
test('the search box shows on Programs and a program\'s page only; hidden by CSS elsewhere, the phone header one row', async () => {
  const pg = loadPage({ hash: '#/' });
  await settle();
  const slug = INDEX.programs[0].slug;
  for (const [hash, shown] of [['#/', false], ['#/programs', true], ['#/c/ACC', true], [`#/p/${slug}`, true], [`#/p/${slug}/roster`, true],
    ['#/camps', false], ['#/trends', false], ['#/faq', false], ['#/api', false], ['#/shortlist', false], ['#/compare', false], ['#/nowhere', false]]) {
    pg.sb.location.hash = hash; pg.sb.route(); await settle(60);
    assert.equal(!pg.body.classList.contains('no-search'), shown, `${hash}: the search box is ${shown ? 'hidden' : 'shown'}`);
  }
  assert.equal(decl('', 'body.no-search .header-search', 'display'), 'none');
  assert.equal(decl('', 'body.no-search .header-recs', 'display'), 'none');
  assert.equal(decl('', 'body.no-search .header-right', 'margin-left'), 'auto', 'the Shortlist and theme toggle do not keep to the right edge');
  assert.equal(decl(PHONE, 'body.no-search', '--header-height'), 'calc(60px + env(safe-area-inset-top, 0px))', 'the phone header keeps an empty search row');
});

test('where the box is hidden, "/" does not reach for it, and "Clear search" puts focus on the heading, not in the box', async () => {
  const pg = loadPage({ hash: '#/' });
  await settle();
  const slash = () => { const e = { key: '/', target: { matches: () => false, closest: () => null }, prevented: false, preventDefault() { e.prevented = true; } }; FOCUS.el = null; pg.docListeners.keydown.forEach(fn => fn(e)); return e; };
  for (const hash of ['#/', '#/camps', '#/trends']) {
    pg.sb.location.hash = hash; pg.sb.route(); await settle(80);
    const e = slash();
    assert.ok(!e.prevented && FOCUS.el !== '#q', `${hash}: "/" focused the hidden box`);
  }
  pg.sb.location.hash = '#/programs'; pg.sb.route(); await settle(80);
  assert.ok(slash().prevented && FOCUS.el === '#q', '"/" no longer focuses the box on Programs');
  // a search made on Programs still narrows ID Camps (until PR F), which says so with "Clear search"
  pg.sb.S.qRaw = 'Stanford'; pg.sb.S.q = 'stanford';
  pg.sb.location.hash = '#/camps'; pg.sb.route(); await settle(150);
  FOCUS.el = null;
  pg.docListeners.click.forEach(fn => fn({ target: { closest: s => (s === '[data-clear-search]' ? {} : null) } }));
  await settle(250);
  assert.equal(pg.sb.S.qRaw, '');
  assert.equal(FOCUS.el, '.content-title', `focus went to ${FOCUS.el}`);
});

test('Home: a heading, one line and three large options - Programs, ID Camps, Pipelines - with no rail and no search box', async () => {
  const slug = INDEX.programs[0].slug;
  // saved state that the old Home turned into Continue links: the new Home shows none of it, and writes nothing
  const pg = loadPage({ hash: '#/', store: { 'cd.filters': { division: ['D1'], region: ['West'], sort: 'rpi' }, 'cd.favorites': [slug] } });
  await settle();
  const html = pg.$('#app').innerHTML;
  assert.match(html, /<h1 class="content-title">Find your college soccer path\.<\/h1>/);
  assert.equal((html.match(/class="content-subtitle"/g) || []).length, 1, 'not one line under the heading');
  const opts = [...html.matchAll(/<a class="home-entry" href="([^"]+)">[\s\S]*?<span class="home-entry-title">([^<]+)<\/span><span class="home-entry-desc">([^<]+)<\/span>(?:<span class="home-entry-fact">([^<]+)<\/span>)?<\/span><\/a>/g)]
    .map(m => [m[1], m[2], !!m[3], m[4] || '']);
  assert.deepEqual(opts.map(o => o.slice(0, 3)), [['#/programs', 'Programs', true], ['#/camps', 'ID Camps', true], ['#/trends', 'Pipelines', true]]);
  assert.equal(opts[0][3], `${INDEX.programs.length.toLocaleString('en-US')} programs`, 'the program count is not the live index');
  assert.ok(!/homeFind|data-home-chip|home-continue|Continue:|Shortlist \(|<input|<button/.test(html), 'Home still draws the search button, chips, Continue or a control');
  assert.ok(pg.body.classList.contains('no-rail') && pg.body.classList.contains('no-search'), 'Home shows the rail or the search box');
  const keys = [];
  pg.sb.localStorage.setItem = (k) => keys.push(k);
  pg.sb.location.hash = '#/'; pg.sb.route(); await settle(60);
  assert.deepEqual(keys, [], 'Home wrote saved state');
  assert.match(HTML, /\.home-entries \{ display: grid; grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);/, 'the three options are not side by side on a desktop');
});

test('the bar steps aside while a phone\'s keyboard is up, and comes back after', async () => {
  const pg = loadPage({ hash: '#/', width: 375 });
  await settle();
  const input = { matches: s => /input:not/.test(s) };
  pg.docListeners.focusin.forEach(fn => fn({ target: input }));
  assert.ok(pg.body.classList.contains('kbd-open'), 'typing on a phone did not hide the bar');
  pg.sb.document.activeElement = null;
  pg.docListeners.focusout.forEach(fn => fn({ target: input }));
  await settle(20);
  assert.ok(!pg.body.classList.contains('kbd-open'), 'the bar did not come back');
  const desk = loadPage({ hash: '#/', width: 1280 });
  await settle();
  desk.docListeners.focusin.forEach(fn => fn({ target: input }));
  assert.ok(!desk.body.classList.contains('kbd-open'), 'a desktop focus toggled the phone keyboard rule');
});
