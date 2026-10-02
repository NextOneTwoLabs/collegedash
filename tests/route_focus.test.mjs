// Focus on a route change (issue #453): the new page's <h1> takes focus, so a screen reader hears where it landed.
//
//     node --test tests/route_focus.test.mjs
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM and boots as a browser would. The stub's
// history has real entries; assigning location.hash is a navigation that fires hashchange, and back() fires popstate
// and hashchange, as a browser does. document.querySelector('.content-title') and ('.view-tab.active') answer only
// when #app's drawn HTML holds that element (a stub that always answered could not tell "no heading" from "focused"),
// and every focus() call is recorded with its options. document.activeElement is set by each test to stand for where
// the reader is: in the header search box, on a view tab, in the recommendations dialog, or nowhere.
//
// ROUTE_FOCUS_TEST_HTML (optional) points at another copy of index.html, to show these checks failing on main.
//
// What it CANNOT prove, and a human must check with a screen reader: that the heading is read out on arrival, and how
// NVDA, JAWS and VoiceOver treat focus moving to a tabindex="-1" heading.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML_PATH = process.env.ROUTE_FOCUS_TEST_HTML || path.join(PUBLIC, 'index.html');
const HTML = fs.readFileSync(HTML_PATH, 'utf8');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const SLUG = INDEX.programs.find(p => fs.existsSync(path.join(PUBLIC, 'data', 'programs', `${p.slug}.json`))).slug;

function loadPage({ hash = '#/' } = {}) {
  const els = new Map(), winListeners = {}, focus = [];
  function makeEl(name, classes = []) {
    const listeners = {}, cls = new Set(classes), attrs = new Map();
    return {
      _name: name, _listeners: listeners, _attrs: attrs, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
      placeholder: '', disabled: false, dataset: {}, style: {},
      setAttribute: (k, v) => attrs.set(k, String(v)), getAttribute: k => (attrs.has(k) ? attrs.get(k) : null), removeAttribute: k => attrs.delete(k),
      classList: { add: (...c) => c.forEach(x => cls.add(x)), remove: (...c) => c.forEach(x => cls.delete(x)), contains: c => cls.has(c),
        toggle: (c, f) => { const on = f === undefined ? !cls.has(c) : !!f; on ? cls.add(c) : cls.delete(c); return on; } },
      addEventListener(type, fn) { (listeners[type] ||= []).push(fn); }, removeEventListener() { },
      querySelector: sel => (/^#[\w-]+$/.test(sel) ? bySelector(sel) : makeEl(`${name} ${sel}`)), querySelectorAll: () => [],
      closest: () => null, matches: () => false, contains: () => false, blur() { },
      focus(opts) { focus.push({ el: name, opts: opts || null, href: attrs.get('href') ?? null, tabindex: attrs.get('tabindex') ?? null }); },
    };
  }
  // the heading and the active tab exist only when #app's HTML has them; each answer is a fresh node for what is drawn
  const drawn = {
    '.content-title': () => /<h1 class="content-title">/.test(bySelector('#app').innerHTML) ? makeEl('.content-title', ['content-title']) : null,
    '.view-tab.active': () => {
      const m = /<a href="([^"]*)" class="view-tab active"|<(?:a|button)[^>]*class="view-tab active"[^>]*?(?:href="([^"]*)")?[^>]*>/.exec(bySelector('#app').innerHTML);
      if (!m) return null;
      const el = makeEl('.view-tab.active', ['view-tab', 'active']); el._attrs.set('href', m[1] ?? m[2] ?? ''); return el;
    },
  };
  const bySelector = sel => { if (drawn[sel]) return drawn[sel](); if (!els.has(sel)) els.set(sel, makeEl(sel)); return els.get(sel); };
  const readPublic = url => {
    let rel = String(url).replace(/^\//, '').replace(/\?.*$/, '');
    if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
    else if (rel === 'api/v1/camps') rel = 'data/camps/index.json';
    else if (rel === 'api/v1/trends') rel = 'data/trends/index.json';
    else if (rel.startsWith('api/v1/programs/')) rel = `data/programs/${rel.slice('api/v1/programs/'.length)}.json`;
    const p = path.join(PUBLIC, rel);
    return p.startsWith(PUBLIC) && fs.existsSync(p) && fs.statSync(p).isFile() ? fs.readFileSync(p, 'utf8') : null;
  };
  const fire = type => (winListeners[type] || []).forEach(fn => fn({ type }));
  const hist = { entries: [hash], at: 0 };
  const loc = {
    search: '', href: 'http://localhost/',
    get hash() { return hist.entries[hist.at]; },
    set hash(h) { const v = h.startsWith('#') ? h : `#${h}`; if (v === hist.entries[hist.at]) return; hist.entries.splice(hist.at + 1); hist.entries.push(v); hist.at++; setTimeout(() => fire('hashchange'), 0); },
    replace(h) { const v = h.startsWith('#') ? h : `#${h}`; const was = hist.entries[hist.at]; hist.entries[hist.at] = v; if (v !== was) setTimeout(() => fire('hashchange'), 0); },
  };
  const go = d => { const to = hist.at + d; if (to < 0 || to >= hist.entries.length) return; const was = hist.entries[hist.at]; hist.at = to; fire('popstate'); if (hist.entries[to] !== was) fire('hashchange'); };
  const history = {
    pushState(_, __, url) { hist.entries.splice(hist.at + 1); hist.entries.push(String(url)); hist.at++; },
    replaceState(_, __, url) { hist.entries[hist.at] = String(url); },
    back: () => go(-1), forward: () => go(1),
  };
  const doc = {
    documentElement: makeEl('html'), body: makeEl('body'), activeElement: null, title: '', visibilityState: 'visible',
    querySelector: bySelector, querySelectorAll: () => [], createElement: makeEl, addEventListener() { },
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl, Error,
    isNaN, parseInt, parseFloat, URL, URLSearchParams, encodeURIComponent, decodeURIComponent, TextEncoder,
    document: doc, location: loc, history,
    matchMedia: () => ({ matches: false }), innerWidth: 1280, screen: { width: 1280, height: 800 }, navigator: {},
    performance: { now: () => Date.now(), getEntriesByName: () => [] }, requestAnimationFrame: f => setTimeout(f, 0),
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    sessionStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    addEventListener(type, fn) { (winListeners[type] ||= []).push(fn); }, removeEventListener() { },
    fetch: async url => {
      const b = readPublic(url);
      if (b == null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      return { ok: true, status: 200, async json() { return JSON.parse(b); } };
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  const lines = HTML.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'index.html: could not find the inline <script>');
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ['S', 'route']) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, $: bySelector, focus, hist };
}
const settle = (ms = 60) => new Promise(r => setTimeout(r, ms));
async function open(hash = '#/') { const pg = loadPage({ hash }); await settle(250); return pg; }
async function nav(pg, hash, ms = 250) { pg.focus.length = 0; pg.sb.location.hash = hash; await settle(ms); return pg.focus.slice(); }
const at = (sel, extra = {}) => ({ matches: s => s === sel || extra.matches?.(s), closest: s => (extra.closest?.(s) ?? null) });
const IN_SEARCH = { matches: s => s === 'input, select, textarea', closest: s => (s.includes('.header-search') ? {} : null) };
const ON_VIEW_TAB = at('a.view-tab');
const headingFocus = f => f.length && f.at(-1).el === '.content-title' && f.at(-1).opts?.preventScroll === true && f.at(-1).tabindex === '-1';

test('the first view of a page load takes no focus', async () => {
  for (const h of ['#/', '#/programs', `#/p/${SLUG}`, '#/camps', '#/rpi']) {
    const pg = await open(h);
    assert.deepEqual(pg.focus, [], `${h}: the landing view took focus`);
  }
});

test('every route change focuses the new page\'s <h1> (tabindex -1, preventScroll)', async () => {
  const pg = await open('#/');
  for (const h of [`#/p/${SLUG}`, '#/camps', '#/trends', '#/compare', '#/shortlist', '#/faq', '#/api', '#/no-such-page', '#/programs', '#/']) {
    const f = await nav(pg, h, 400);
    assert.ok(headingFocus(f), `${h}: focus did not move to the page heading (${JSON.stringify(f)})`);
  }
});

test('Back and Forward: the heading of the page returned to takes focus, without scrolling', async () => {
  const pg = await open('#/');
  await nav(pg, `#/p/${SLUG}`, 400);
  pg.focus.length = 0;
  pg.sb.history.back(); await settle(300);
  assert.ok(headingFocus(pg.focus), 'Back: focus did not move to the list heading');
  assert.equal(pg.$('#main').scrollTop, 0);
  pg.focus.length = 0;
  pg.sb.history.forward(); await settle(400);
  assert.ok(headingFocus(pg.focus), 'Forward: focus did not move to the profile heading');
  assert.ok(pg.focus.every(f => f.opts?.preventScroll === true), 'a focus call could scroll the page');
});

test('typing in the header search box: a route change never takes focus from it', async () => {
  const pg = await open('#/camps');
  pg.sb.document.activeElement = IN_SEARCH;  // e.g. Enter on a place, which opens the list and keeps the box focused (#409)
  assert.deepEqual(await nav(pg, '#/'), [], 'the list took focus from the search box');
  assert.deepEqual(await nav(pg, `#/p/${SLUG}`, 400), [], 'a profile took focus from the search box');
});

test('the recommendations dialog and the feedback form keep focus through a route change', async () => {
  const pg = await open('#/');
  for (const where of ['#recsPanel', '#feedback']) {
    pg.sb.document.activeElement = { matches: () => false, closest: s => (s.split(', ').includes(where) ? {} : null) };
    assert.deepEqual(await nav(pg, pg.sb.location.hash.startsWith('#/p/') ? '#/' : `#/p/${SLUG}`, 400), [], `${where} lost focus`);
  }
});

test('a profile tab switch focuses the new active tab, not the heading', async () => {
  const pg = await open(`#/p/${SLUG}`);
  const tabs = [...pg.$('#app').innerHTML.matchAll(/<a href="(#\/p\/[^"]+)" class="view-tab(?: active)?"/g)].map(m => m[1]);
  assert.ok(tabs.length >= 2, `fixture: ${SLUG} has fewer than two tabs`);
  const f = await nav(pg, tabs[1], 400);
  assert.equal(f.at(-1)?.el, '.view-tab.active', `the tab switch did not focus the active tab (${JSON.stringify(f)})`);
  assert.equal(f.at(-1).href, tabs[1]);
  assert.equal(f.at(-1).opts?.preventScroll, true);
});

test('a view tab used to reach ID Camps focuses the ID Camps tab', async () => {
  const pg = await open('#/');
  pg.sb.document.activeElement = ON_VIEW_TAB;
  const f = await nav(pg, '#/camps', 400);
  assert.equal(f.at(-1)?.el, '.view-tab.active', `ID Camps did not focus its tab (${JSON.stringify(f)})`);
  assert.equal(f.at(-1).href, '#/camps');
});

test('the same page drawn again (a retry, an address rewritten in place) takes no focus', async () => {
  const pg = await open('#/');
  await nav(pg, `#/p/${SLUG}`, 400);
  pg.focus.length = 0;
  await pg.sb.route(); await settle(300);
  assert.deepEqual(pg.focus, [], 'redrawing the same page took focus');
});

test('no new live region: exactly the six polite regions main has (#qStatus covers search), none assertive', () => {
  const ids = [...HTML.matchAll(/<[^<>]*aria-live="(polite|assertive)"[^<>]*>/g)].map(m => (/id="([\w-]+)"/.exec(m[0]) || [])[1]).sort();
  // #465: campsStatus is the ID Camps filter bar's result count, like Pipelines' trLive; it is never used on a route change
  assert.deepEqual(ids, ['campsStatus', 'feedbackNote', 'qStatus', 'recsCount', 'recsStatus', 'recsToast', 'trLive'], 'a live region was added or removed');
  assert.ok(!/aria-live="assertive"/.test(HTML), 'an assertive live region');
});
