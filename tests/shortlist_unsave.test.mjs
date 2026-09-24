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
// What it CANNOT prove, and a human must check in a browser: layout at desktop and ~400 px, focus after the
// clicked card disappears, and real pointer/keyboard events. The DOM is a stub that records innerHTML.
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
