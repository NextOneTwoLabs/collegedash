// The Start strip (#404 phase 1, item 1; decision 2a): a search box above the cards that a phone shows without
// opening the side menu, sharing the sidebar's search.
//
//     node --test tests/start_strip.test.mjs
//
// Two halves, both read from public/index.html itself:
//   1. Where the strip shows. The page's own route() is run in a `vm` (same stub-DOM mechanism as
//      tests/shortlist_unsave.test.mjs) to get the classes it puts on .layout for each view; the page's own <style> is
//      then evaluated for those classes at a given width by the small cascade below, which understands exactly the
//      selector and media forms the strip uses and FAILS LOUDLY on any other form that could show or hide the strip or
//      its box (ID selectors, !important, compound selectors, other combinators, visibility, unknown media), so a rule
//      it cannot read can never make a check pass; a self-test feeds it each of those forms. Checked: shown at 375 px on #/; hidden at 1280 px with the sidebar open;
//      shown at 1280 px with the sidebar collapsed; hidden on a program page and on ID Camps.
//   2. That it is the same search. Typing in either box goes through the page's setQuery; the other box mirrors the
//      query only when it differs and the box being typed in is never written to; there is exactly one aria-live
//      search status, the strip's; the strip's placeholder follows Ask, and its box skips Shift+Enter Ask.
//
// STRIP_TEST_HTML (optional) points the suite at another copy of index.html, to show these checks failing on main.
//
// What it CANNOT prove, and a human must check in a browser: pixels. It checks the markup, the CSS rules and the
// routing classes, not rendering; a real phone (keyboard, zoom, safe areas) stays unverified.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML_PATH = process.env.STRIP_TEST_HTML || path.join(PUBLIC, 'index.html');
const HTML = fs.readFileSync(HTML_PATH, 'utf8');

// ---------- the static markup ----------
const body = HTML.slice(HTML.indexOf('<body'));
const STRIP_AT = body.indexOf('id="startStrip"');

test('markup: a search box sits in the Start strip, outside the sidebar and outside #app', () => {
  assert.ok(STRIP_AT >= 0, 'no element with id="startStrip"');
  const main = body.indexOf('id="main"'), app = body.indexOf('<div id="app">');
  assert.ok(main >= 0 && app > main, 'the page layout changed: no #main before #app');
  assert.ok(STRIP_AT > main && STRIP_AT < app, 'the strip is not inside .main ahead of #app (renderList rewrites #app)');
  const strip = body.slice(STRIP_AT, app);
  assert.match(strip, /<input type="search"[^>]*id="qStart"/, 'no search input in the strip');
  assert.match(strip, /<label[^>]*for="qStart"/, 'the strip box has no label');
  for (const id of ['startStrip', 'qStart']) {
    const tag = new RegExp(`<[^<>]*id="${id}"[^<>]*>`).exec(body)?.[0] || '';
    assert.ok(tag && !/\shidden(?=[\s>=])/.test(tag), `#${id} carries the hidden attribute: ${tag}`);
  }
  assert.match(strip, /<div class="start-actions" id="startActions"><\/div>/, 'the #400 PR 3 slot is missing or not empty');
  assert.ok(!/id="qStart"/.test(/<aside class="sidebar"[^>]*>([\s\S]*?)<\/aside>/.exec(body)?.[1] ?? ''), 'the strip box is inside the sidebar');
});

// ---------- a cascade for the strip's display ----------
// Huatuo on #413: the first version passed forms it did not understand (an ID selector, !important, a compound
// selector). This one reads exactly the forms below and FAILS LOUDLY on anything else that could decide whether the
// strip or its box is shown, so a rule it cannot evaluate can never make a check pass. The self-test further down
// feeds it each of those forms.
const css = [...HTML.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n').replace(/\/\*[\s\S]*?\*\//g, '');
// Flatten into [{ media, selectors, decls, order }], one level of @media nesting (all this page uses).
function parseCss(text) {
  const out = []; let i = 0, order = 0;
  const block = (from) => { let depth = 0, j = from; for (; j < text.length; j++) { if (text[j] === '{') depth++; else if (text[j] === '}' && --depth === 0) return j; } return -1; };
  const rules = (chunk, media) => {
    for (const m of chunk.matchAll(/([^{}]+)\{([^{}]*)\}/g)) out.push({ media, selectors: m[1].trim().split(',').map(s => s.trim()), decls: m[2], order: order++ });
  };
  while (i < text.length) {
    const at = text.indexOf('@media', i);
    if (at < 0) { rules(text.slice(i), null); break; }
    rules(text.slice(i, at), null);
    const open = text.indexOf('{', at), close = block(open);
    rules(text.slice(open + 1, close), text.slice(at + 6, open).trim());
    i = close + 1;
  }
  return out;
}
const RULES = parseCss(css);
const CANNOT = 'the strip test cannot read';
// true / false, or a loud failure for a media form it does not read (only (max-width: Npx) and (min-width: Npx), joined by "and")
function mediaMatches(media, width) {
  if (!media) return true;
  return media.split(/\band\b/).map(s => s.trim()).filter(Boolean).every(c => {
    const m = /^\((max|min)-width:\s*(\d+)px\)$/.exec(c);
    assert.ok(m, `${CANNOT} @media ${media}`);
    return m[1] === 'max' ? width <= +m[2] : width >= +m[2];
  });
}
const decls = text => text.split(';').map(d => d.trim()).filter(Boolean).map(d => {
  const i = d.indexOf(':');
  return { prop: d.slice(0, i).trim().toLowerCase(), value: d.slice(i + 1).trim() };
});
// The strip itself, and every hook inside it that could hide the box: a rule whose target is one of these and that
// sets display: none or visibility: hidden is a form this test does not evaluate, so it fails loudly. The one
// exception is the empty #400 slot, which is meant to take no space.
const STRIP_RE = /\.start-strip(?![\w-])|#startStrip(?![\w-])/;
const INNER_RE = /#qStart(?![\w-])|\.start-row(?![\w-])|\.start-label(?![\w-])|\.start-status(?![\w-])|#qStartStatus(?![\w-])|\.search-input(?![\w-])/;
const HIDES = ds => ds.some(d => (d.prop === 'display' && /^none\b/.test(d.value)) || (d.prop === 'visibility' && !/^visible\b/.test(d.value)));
// The strip's computed display at `width` with .layout carrying `layoutClasses`. The only selector forms it evaluates
// are `.start-strip` and `.layout(.x)* .start-strip` (one descendant step); no !important, no ID, no compound on the
// strip, no other combinator, no visibility. Anything else that names the strip, or hides something inside it, fails.
function stripDisplay(width, layoutClasses, rules = RULES) {
  let best = null;
  for (const r of rules) {
    const ds = decls(r.decls);
    for (const sel of r.selectors) {
      const names = STRIP_RE.test(sel), inner = INNER_RE.test(sel);
      if (!names && !inner) continue;
      if (/[>+~]/.test(sel)) assert.fail(`${CANNOT} the combinator in "${sel}"`);
      const parts = sel.split(/\s+/), last = parts[parts.length - 1];
      if (last.includes('::')) continue;  // a pseudo-element (the search box's cancel button), not the box itself
      if (!STRIP_RE.test(last)) {  // something inside the strip (or the box anywhere): it must not hide anything
        if (HIDES(ds) && !(sel === '.start-actions:empty')) assert.fail(`${CANNOT} "${sel}", which hides part of the strip or its box`);
        continue;
      }
      if (sel.includes('#startStrip')) assert.fail(`${CANNOT} the ID selector "${sel}"`);
      if (last !== '.start-strip') assert.fail(`${CANNOT} the compound selector "${last}"`);
      if (parts.length > 2 || (parts.length === 2 && !/^\.layout(\.[\w-]+)*$/.test(parts[0]))) assert.fail(`${CANNOT} the selector "${sel}"`);
      for (const d of ds) {
        if (/!\s*important/i.test(d.value)) assert.fail(`${CANNOT} !important in "${sel} { ${d.prop}: ${d.value} }"`);
        if (d.prop === 'visibility' || d.prop === 'content-visibility') assert.fail(`${CANNOT} ${d.prop} on "${sel}"`);
      }
      const display = ds.filter(d => d.prop === 'display').map(d => d.value).pop();
      const mm = mediaMatches(r.media, width);
      const need = parts.length === 2 ? parts[0].split('.').filter(Boolean) : [];
      const applies = need.every(c => layoutClasses.has(c)), spec = need.length + 1;
      if (!mm || !applies || !display) continue;
      if (!best || spec > best.spec || (spec === best.spec && r.order > best.order)) best = { display, spec, order: r.order };
    }
  }
  return best ? best.display : 'block';  // a div's default
}

// The cascade's own self-test: each form it does not evaluate must fail loudly, not pass. The first two are the
// mutations Huatuo used on #413 (both hid the strip in a browser while the first version still passed).
test('the cascade fails loudly on every form it cannot evaluate', () => {
  const at375 = extra => () => stripDisplay(375, new Set(['layout', 'view-list']), parseCss(`${css}\n${extra}`));
  assert.doesNotThrow(at375(''), 'the page\'s own CSS is not readable');
  for (const [name, extra] of [
    ['an ID selector (Huatuo)', '#startStrip { display: none; }'],
    ['!important at <=768 px (Huatuo)', '@media (max-width: 768px) { .start-strip { display: none !important; } }'],
    ['a compound selector on the strip', '.start-strip.x { display: block; }'],
    ['a child combinator', '.layout > .start-strip { display: none; }'],
    ['an unknown media form', '@media (orientation: portrait) { .start-strip { display: none; } }'],
    ['visibility on the strip', '.start-strip { visibility: hidden; }'],
    ['the box hidden by ID', '#qStart { display: none; }'],
    ['the box hidden through the shared class', '@media (max-width: 768px) { .search-input { display: none; } }'],
    ['the row hidden', '.start-row { visibility: hidden; }'],
    ['an unknown ancestor', '.main .start-strip { display: none; }'],
  ]) assert.throws(at375(extra), new RegExp(CANNOT), `${name}: the cascade did not fail`);
});

// ---------- the page in a vm ----------
function makeElement(name) {
  const listeners = {};
  let value = '';
  const el = {
    _name: name, _listeners: listeners, _writes: 0, innerHTML: '', textContent: '', title: '', hidden: false, scrollTop: 0,
    placeholder: '', dataset: {}, style: {}, setAttribute() { }, getAttribute: () => null, removeEventListener() { },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, blur() { }, contains: () => false,
  };
  Object.defineProperty(el, 'value', { get: () => value, set: v => { value = v; el._writes++; }, enumerable: true });
  const classes = new Set();
  el.classList = {
    add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c),
    toggle: (c, force) => { const on = force === undefined ? !classes.has(c) : !!force; on ? classes.add(c) : classes.delete(c); return on; },
    _set: classes,
  };
  return el;
}

function loadPage(width) {
  const els = new Map();
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
      querySelector: bySelector, querySelectorAll: () => [], createElement: makeElement, addEventListener() { },
    },
    location: { hash: '#/', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    innerWidth: width,
    addEventListener() { },
    fetch: async url => {
      const b = readPublic(url);
      if (b == null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      return { ok: true, status: 200, async json() { return JSON.parse(b); } };
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  const lines = HTML.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>');
  const b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'index.html: could not find the inline <script>');
  const src = lines.slice(a + 1, b).join('\n')
    + `\n;for (const k of ['S', 'route', 'setQuery', 'renderList', 'renderSidebar', 'loadIndex', 'askSwitchedOn']) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  // .layout's classes as the static markup has them
  const layout = bySelector('#layout');
  for (const c of (/<div class="([^"]*)" id="layout"/.exec(HTML)?.[1] || '').split(/\s+/).filter(Boolean)) layout.classList.add(c);
  return { sb: sandbox, $: bySelector };
}
const settle = (ms = 120) => new Promise(r => setTimeout(r, ms));

async function stripAt(width, hash, { collapsed = false } = {}) {
  const { sb, $ } = loadPage(width);
  await sb.loadIndex();
  if (collapsed) $('#layout').classList.add('sidebar-collapsed');
  sb.location.hash = hash;
  try { await sb.route(); } catch { /* the stub DOM cannot draw every view; route sets .layout's classes first */ }
  await settle(20);
  return stripDisplay(width, $('#layout').classList._set);
}

test('375 px, #/: the strip and its search box show without opening the side menu', async () => {
  assert.ok(STRIP_AT >= 0, 'no Start strip in the page');
  assert.notEqual(await stripAt(375, '#/'), 'none');
});
test('1280 px with the sidebar open: the strip is hidden (the sidebar box is on screen)', async () => {
  assert.ok(STRIP_AT >= 0, 'no Start strip in the page');
  assert.equal(await stripAt(1280, '#/'), 'none');
});
test('1280 px with the sidebar collapsed: the strip shows', async () => {
  assert.ok(STRIP_AT >= 0, 'no Start strip in the page');
  assert.notEqual(await stripAt(1280, '#/', { collapsed: true }), 'none');
});
test('375 px on a program page and on ID Camps: the strip is hidden', async () => {
  assert.ok(STRIP_AT >= 0, 'no Start strip in the page');
  assert.equal(await stripAt(375, '#/p/stanford'), 'none', 'the strip shows on a program page');
  assert.equal(await stripAt(375, '#/camps'), 'none', 'the strip shows on ID Camps');
});

// ---------- one search ----------
const cardSlugs = html => [...html.matchAll(/class="card pcard[^"]*" data-slug="([^"]+)"/g)].map(m => m[1]);
async function typeIn(sb, box, text) {
  box.value = text;  // the browser sets the value; then fires input
  const before = box._writes;
  for (const fn of box._listeners.input || []) fn({ target: box });
  await settle();
  return box._writes - before;  // writes the PAGE made to the box being typed in
}

test('typing in the strip box filters the list through the shared search and mirrors into the sidebar box', async () => {
  const { sb, $ } = loadPage(375);
  await sb.loadIndex();
  sb.S.filters.view = 'cards';
  sb.location.hash = '#/';
  sb.renderSidebar();
  const strip = $('#qStart'), side = $('#q');
  assert.ok((strip._listeners.input || []).length, 'the strip box has no input handler');
  assert.equal(await typeIn(sb, strip, 'stanford'), 0, 'the page wrote back into the box being typed in');
  assert.equal(sb.S.qRaw, 'stanford');
  assert.equal(side.value, 'stanford', 'the sidebar box did not mirror the strip');
  await sb.renderList();
  assert.deepEqual(cardSlugs($('#app').innerHTML), ['stanford']);
  assert.match($('#qStartStatus').textContent, /^1 match · Enter opens the first$/);
  assert.equal(await typeIn(sb, side, 'duke'), 0, 'the page wrote back into the sidebar box being typed in');
  assert.equal(strip.value, 'duke', 'the strip box did not mirror the sidebar');
  const stripWrites = strip._writes;
  await typeIn(sb, side, 'duke');  // the same query again: the strip already holds it
  assert.equal(strip._writes, stripWrites, 'a mirror write reached a box whose value already matched');
});

test('Enter in the strip box opens the top name hit, like the sidebar box', async () => {
  const { sb, $ } = loadPage(375);
  await sb.loadIndex();
  sb.location.hash = '#/';
  const strip = $('#qStart');
  await typeIn(sb, strip, 'kenyon');
  for (const fn of strip._listeners.keydown || []) fn({ key: 'Enter', shiftKey: false, preventDefault() { } });
  await settle();
  assert.equal(sb.location.hash, '#/p/kenyon-college');
});

test('one live region: the strip status is aria-live, the sidebar #qStatus is not', async () => {
  assert.match(body.slice(STRIP_AT), /id="qStartStatus" aria-live="polite"/);
  const { sb, $ } = loadPage(375);
  await sb.loadIndex();
  sb.renderSidebar();
  const side = $('#sidebar').innerHTML;
  assert.match(side, /id="qStatus"/);
  assert.ok(!/id="qStatus"[^>]*aria-live/.test(side), '#qStatus is aria-live: every count would be announced twice');
});

test('Ask on: the strip placeholder follows it, and the strip box skips Shift+Enter Ask while the sidebar box keeps it', async () => {
  const { sb, $ } = loadPage(375);
  await sb.loadIndex();
  sb.location.hash = '#/';
  assert.equal($('#qStart').placeholder || /id="qStart"[^>]*placeholder="([^"]*)"/.exec(body)?.[1], 'School or mascot…');
  sb.askSwitchedOn();
  assert.equal($('#qStart').placeholder, 'School, mascot, or a question…');
  let asked = 0;
  sb.askQuestion = () => { asked++; };
  const strip = $('#qStart');
  await typeIn(sb, strip, 'stanford');
  assert.match($('#qStartStatus').textContent, /^1 match · Enter opens the first$/, 'the strip status offers Shift+Enter Ask');
  for (const fn of strip._listeners.keydown || []) fn({ key: 'Enter', shiftKey: true, preventDefault() { } });
  await settle();
  assert.equal(asked, 0, 'Shift+Enter in the strip asked; its answer would land in the hidden sidebar');
  assert.equal(sb.location.hash, '#/p/stanford', 'Shift+Enter in the strip should act as Enter');
  sb.location.hash = '#/';
  sb.renderSidebar();
  const side = $('#q');
  await typeIn(sb, side, 'stanford');
  const fns = side._listeners.keydown || [];
  fns[fns.length - 1]({ key: 'Enter', shiftKey: true, preventDefault() { } });
  await settle();
  assert.equal(asked, 1, 'Shift+Enter in the sidebar box no longer asks');
});
