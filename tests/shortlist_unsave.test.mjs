// Tests for issue #203: on #/shortlist, unsaving a program has to update the page at once. Before the fix
// the star flipped and the sidebar updated, but the card, the "N saved programs" count and the Compare link
// stayed until a reload, and unsaving the last program never showed the empty state.
//
//     node --test tests/shortlist_unsave.test.mjs
//
// Same mechanism as tests/camps_view.test.mjs: the inline <script> is pulled out of public/index.html and
// run in a `vm` against a stub DOM. The click goes through the page's own delegated document listener (the
// stub records it), so the path under test is the one a real star click takes: listener -> toggleFav ->
// syncToggles. Expected slugs and counts come from S.favorites and the shipped index, never from the page's
// render helpers.
//
// What it CANNOT prove, and a human must check in a browser: layout at desktop and ~400 px, the focus ring
// where focus lands, and real pointer/keyboard events. The DOM is a stub that records innerHTML.
//
// SHORTLIST_TEST_HTML (optional) points the suite at another copy of index.html, so the page from before
// this change can be run through these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.SHORTLIST_TEST_HTML || path.join(PUBLIC, 'index.html');

// focus() on any stub records it here, so the tests can ask where keyboard focus went.
let focused = null;
// The controls a region's innerHTML currently holds, as stubs: one per data-fav button.
const favStubs = (region, html) => [...html.matchAll(/data-fav="([^"]+)"/g)]
  .map(m => ({ region, dataset: { fav: m[1] }, focus() { focused = { region, fav: m[1] }; } }));
const EMPTY = { '#app': 'shortlist-empty', '#sidebar': 'side-empty' };

function makeElement(name) {
  if (name === '#app' || name === '#sidebar') {
    const el = makeElement('region');
    el.querySelectorAll = sel => (sel === '[data-fav]' ? favStubs(name, el.innerHTML) : []);
    // The empty state counts as focusable only if it is drawn with tabindex="-1".
    el.querySelector = sel => (sel === '.shortlist-empty, .side-empty'
      ? (new RegExp(`class="[^"]*\\b${EMPTY[name]}\\b[^"]*" tabindex="-1"`).test(el.innerHTML)
        ? { focus() { focused = { region: name, empty: true }; } } : null)
      : makeElement('child'));
    return el;
  }
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
  const listeners = [];
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
      querySelector: bySelector, querySelectorAll: () => [], createElement: makeElement,
      addEventListener(type, fn) { listeners.push({ type, fn }); },
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
    + '\n;Object.assign(globalThis, { S, renderShortlist, renderSidebar, loadIndex });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sandbox, store, listeners };
}

const { sandbox, store, listeners } = loadPage();
const S = sandbox.S;
const app = () => sandbox.document.querySelector('#app').innerHTML;
const settle = () => new Promise(r => setTimeout(r, 0));
const cardSlugs = html => [...html.matchAll(/class="card pcard[^"]*" data-slug="([^"]+)"/g)].map(m => m[1]);

// A star click as the browser delivers it: the target's closest('[data-fav]') is the star button.
async function clickStar(slug) {
  const star = { dataset: { fav: slug } };
  const ev = { target: { closest: sel => (sel === '[data-fav]' ? star : null) }, stopPropagation() { }, preventDefault() { } };
  const clicks = listeners.filter(l => l.type === 'click');
  assert.ok(clicks.length, 'the page registered no document click listener');
  clicks.forEach(l => l.fn(ev));
  await settle(); await settle();
}

let A, B;
test('fixture: two saved programs render on #/shortlist', async () => {
  const idx = await sandbox.loadIndex();
  [A, B] = idx.programs.slice(0, 2).map(p => p.slug);
  assert.ok(A && B && A !== B, 'the shipped index has fewer than two programs');
  S.favorites.clear(); S.favorites.add(A); S.favorites.add(B);
  sandbox.location.hash = '#/shortlist';
  await sandbox.renderShortlist();
  assert.deepEqual(cardSlugs(app()).sort(), [A, B].sort());
  assert.match(app(), /2 saved programs/);
});

test('unsaving a non-last program on #/shortlist removes its card and updates the count at once', async () => {
  await clickStar(B);
  assert.ok(!S.favorites.has(B), 'the click did not unsave the program');
  assert.deepEqual(cardSlugs(app()), [A], 'the unsaved card is still on the page');
  assert.match(app(), /1 saved program\b/);
  assert.doesNotMatch(app(), /2 saved programs/);
  assert.doesNotMatch(app(), /Compare 2/, 'the Compare link still counts the unsaved program');
  assert.deepEqual(JSON.parse(store.get('cd.favorites')), [A]);
});

test('unsaving the last program on #/shortlist shows the empty state without a reload', async () => {
  await clickStar(A);
  assert.equal(S.favorites.size, 0);
  assert.deepEqual(cardSlugs(app()), [], 'a card is still on the page after the last program was unsaved');
  assert.match(app(), /Nothing saved yet/);
  assert.doesNotMatch(app(), /saved program/);
  assert.match(app(), /Save a program with the ☆/);
});

test('saving or unsaving on another view does not draw the shortlist over it', async () => {
  sandbox.location.hash = '#/';
  sandbox.document.querySelector('#app').innerHTML = 'LIST VIEW';
  await clickStar(A);
  assert.ok(S.favorites.has(A));
  assert.equal(app(), 'LIST VIEW', 'the shortlist was rendered into #app while the list view was showing');
  await clickStar(A);
  assert.equal(app(), 'LIST VIEW');
});

// Review of PR #294: the redraw removes the clicked star (or sidebar ✕), so focus must be handed on rather
// than dropping to <body>: the next row's control, else the previous row's, else the region's empty state.
// The clicked control is the stub a browser would give: it sits in the list it was drawn in, and after the
// redraw it is detached (isConnected false), as innerHTML replacement leaves it. Row order is read from the
// rendered markup, i.e. what the reader sees.
async function clickIn(region, slug) {
  const el = sandbox.document.querySelector(region);
  const star = { dataset: { fav: slug }, isConnected: false };
  const list = { querySelectorAll: () => favStubs(region, el.innerHTML).map(b => (b.dataset.fav === slug ? star : b)) };
  star.closest = sel => (sel === '[data-fav]' ? star : sel === '.grid.cards, .side-list' ? list : sel === '#app' && region === '#app' ? el : null);
  assert.ok(favStubs(region, el.innerHTML).some(b => b.dataset.fav === slug), `${slug} has no control in ${region}`);
  const ev = { target: star, stopPropagation() { }, preventDefault() { } };
  focused = null;
  listeners.filter(l => l.type === 'click').forEach(l => l.fn(ev));
  await settle(); await settle();
  return focused;
}
const favOrder = region => favStubs(region, sandbox.document.querySelector(region).innerHTML).map(b => b.dataset.fav);

async function threeSaved() {
  const idx = await sandbox.loadIndex();
  S.favorites.clear(); idx.programs.slice(0, 3).forEach(p => S.favorites.add(p.slug));
  sandbox.location.hash = '#/shortlist';
  S.sidebarTab = 'shortlist';
  sandbox.renderSidebar();
  await sandbox.renderShortlist();
}

test('focus: unsaving a card star on #/shortlist moves focus to the next card, then the previous, then the empty state', async () => {
  await threeSaved();
  const [x, y, z] = favOrder('#app');
  assert.ok(x && y && z, 'three cards did not render');
  assert.deepEqual(await clickIn('#app', y), { region: '#app', fav: z }, 'middle card: focus should go to the next card star');
  assert.deepEqual(favOrder('#app'), [x, z]);
  assert.deepEqual(await clickIn('#app', z), { region: '#app', fav: x }, 'last card: focus should go to the previous card star');
  assert.deepEqual(await clickIn('#app', x), { region: '#app', empty: true }, 'no cards left: focus should go to the empty-state card');
});

test('focus: removing with the sidebar ✕ moves focus to the next ✕, then the previous, then the sidebar empty state', async () => {
  await threeSaved();
  const [x, y, z] = favOrder('#sidebar');
  assert.ok(x && y && z, 'three sidebar rows did not render');
  assert.deepEqual(await clickIn('#sidebar', y), { region: '#sidebar', fav: z }, 'middle row: focus should go to the next ✕');
  assert.deepEqual(await clickIn('#sidebar', z), { region: '#sidebar', fav: x }, 'last row: focus should go to the previous ✕');
  assert.deepEqual(await clickIn('#sidebar', x), { region: '#sidebar', empty: true }, 'no rows left: focus should go to the sidebar empty state');
  assert.deepEqual(cardSlugs(app()), [], 'the shortlist page did not follow the sidebar removal');
});

test('focus: the sidebar ✕ hands focus on from other views too, where the page itself is not redrawn', async () => {
  await threeSaved();
  sandbox.location.hash = '#/';
  sandbox.document.querySelector('#app').innerHTML = 'LIST VIEW';
  const [x, y] = favOrder('#sidebar');
  assert.deepEqual(await clickIn('#sidebar', x), { region: '#sidebar', fav: y });
  assert.equal(app(), 'LIST VIEW');
});

// Issue #297: syncToggles() refreshes every [data-fav] / [data-cmp] control after a click, and used to rewrite the
// sidebar's ✕ remove buttons (which carry data-fav / data-cmp too) into ★ / "⇄ Comparing". Here document.querySelectorAll
// answers from the markup actually drawn in #app and #sidebar, honouring ':not(.cls)' clauses as a browser would, and
// every button it hands out is kept so the test can read what the page wrote into it. A human still checks the
// glyph in a browser at desktop and 400 px.
function withButtonQuery(fn) {
  const handed = [];
  const query = sel => {
    const m = /^\[data-(fav|cmp)\]((?::not\(\.[\w-]+\))*)$/.exec(sel);
    if (!m) return [];
    const excluded = [...m[2].matchAll(/\.([\w-]+)/g)].map(x => x[1]);
    const out = [];
    for (const region of ['#app', '#sidebar']) {
      const html = sandbox.document.querySelector(region).innerHTML;
      for (const b of html.matchAll(/<button class="([^"]*)"[^>]*?\bdata-(fav|cmp)="([^"]+)"[^>]*>([^<]*)<\/button>/g)) {
        const cls = b[1].split(/\s+/);
        if (b[2] !== m[1] || excluded.some(c => cls.includes(c))) continue;
        out.push({ region, cls, dataset: { [b[2]]: b[3] }, textContent: b[4], setAttribute() { },
          classList: { contains: c => cls.includes(c), toggle() { } },
          matches: s => s.split(',').some(x => x.trim().startsWith('.') && cls.includes(x.trim().slice(1))) });
      }
    }
    handed.push(...out);
    return out;
  };
  const saved = sandbox.document.querySelectorAll;
  sandbox.document.querySelectorAll = query;
  return fn(handed).finally(() => { sandbox.document.querySelectorAll = saved; });
}

test('#297: after unsaving, the sidebar shortlist ✕ buttons stay ✕ while the stars elsewhere are refreshed', async () => {
  await threeSaved();
  sandbox.location.hash = '#/';
  const [x, y] = favOrder('#sidebar');
  sandbox.document.querySelector('#app').innerHTML = [x, y].map(s =>
    `<button class="star-btn starred" data-fav="${s}" aria-pressed="true" title="Remove from shortlist">★</button>`).join('');
  await withButtonQuery(async handed => {
    await clickIn('#sidebar', x);
    const rms = handed.filter(b => b.region === '#sidebar' && b.cls.includes('rm'));
    const stars = handed.filter(b => b.region === '#app');
    assert.ok(stars.length, 'syncToggles did not refresh the stars in #app at all');
    assert.equal(stars.find(b => b.dataset.fav === x)?.textContent, '☆', 'the unsaved program\'s star was not refreshed');
    assert.match(sandbox.document.querySelector('#sidebar').innerHTML, /class="rm" data-fav="[^"]+"[^>]*>✕</, 'no sidebar ✕ buttons were drawn to check');
    assert.deepEqual(rms.map(b => b.textContent).filter(t => t !== '✕'), [], 'a sidebar ✕ remove button was rewritten');
  });
});

test('#297: removing from the sidebar comparison list leaves its ✕ buttons as ✕', async () => {
  const idx = await sandbox.loadIndex();
  const [x, y, z] = idx.programs.slice(0, 3).map(p => p.slug);
  S.compare.splice(0, S.compare.length, x, y, z);
  sandbox.location.hash = '#/';
  S.sidebarTab = 'compare';
  sandbox.renderSidebar();
  assert.match(sandbox.document.querySelector('#sidebar').innerHTML, new RegExp(`class="rm" data-cmp="${y}"`), 'compare list did not render');
  sandbox.document.querySelector('#app').innerHTML = `<button class="cmp-btn on" data-cmp="${y}" aria-pressed="true">⇄ Comparing</button>`;
  await withButtonQuery(async handed => {
    const btn = { dataset: { cmp: x } };
    const ev = { target: { closest: sel => (sel === '[data-cmp]' ? btn : null) }, stopPropagation() { }, preventDefault() { } };
    listeners.filter(l => l.type === 'click').forEach(l => l.fn(ev));
    await settle(); await settle();
    assert.ok(!S.compare.includes(x), 'the click did not remove the program from comparison');
    assert.equal(handed.find(b => b.region === '#app')?.textContent, '⇄ Comparing', 'syncToggles did not refresh the compare button in #app');
    const rms = handed.filter(b => b.region === '#sidebar' && b.cls.includes('rm'));
    assert.match(sandbox.document.querySelector('#sidebar').innerHTML, /class="rm" data-cmp="[^"]+"[^>]*>✕</, 'no sidebar ✕ buttons were drawn to check');
    assert.deepEqual(rms.map(b => b.textContent).filter(t => t !== '✕'), [], 'a sidebar comparison ✕ button was rewritten');
  });
  S.sidebarTab = 'shortlist';
});
