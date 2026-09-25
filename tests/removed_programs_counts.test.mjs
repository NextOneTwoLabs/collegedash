// Issue #111: saved state that names a program the site no longer carries (Saint Francis, Mississippi Valley
// State were removed) must not be counted, linked or named; and West Florida's athletics host is stored as the
// final host (goargos.com), not the www host that redirects to it.
//
//     node --test tests/removed_programs_counts.test.mjs
//
// Same mechanism as tests/camps_view.test.mjs: the inline <script> of public/index.html runs in a `vm` against a
// stub DOM, so what runs is the real source text. REMOVED_TEST_HTML points it at another copy of the page, so
// the page from before this change can be run through the same checks to show them failing.
//
// What it cannot prove: layout and real clicks. The DOM is a stub that records innerHTML.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.REMOVED_TEST_HTML || path.join(PUBLIC, 'index.html');
const GONE = ['no-such-program-a', 'no-such-program-b'];  // made-up slugs the index cannot carry

function makeElement(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, contains: () => false,
  };
}
function loadPage(saved) {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map(Object.entries(saved).map(([k, v]) => [k, JSON.stringify(v)]));
  const read = url => {
    let rel = url.replace(/^\//, '');
    if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
    const p = path.join(PUBLIC, rel);
    return p.startsWith(PUBLIC) && fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector,
                querySelectorAll: () => [], addEventListener() { }, createElement: makeElement },
    location: { hash: '', replace(h) { this.hash = h; } }, history: { replaceState() { } },
    matchMedia: () => ({ matches: false }), innerWidth: 1400, addEventListener() { }, alert() { },
    localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) },
    fetch: async url => {
      const body = read(url);
      if (body == null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(HTML, 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n') + '\n;Object.assign(globalThis, { S, loadIndex, renderSidebar, glanceHtml, toggleCompare, route });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sandbox, sidebar: () => bySelector('#sidebar').innerHTML, el: bySelector };
}

const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data/programs/index.json'), 'utf8'));
const [P1, P2, P3, P4, P5] = INDEX.programs;

test('#111 the Shortlist and Compare tab counts leave out programs the index does not carry', async () => {
  const page = loadPage({ 'cd.favorites': [P1.slug, GONE[0], P2.slug], 'cd.compare': [GONE[1], P1.slug] });
  await page.sandbox.loadIndex();
  page.sandbox.renderSidebar();
  const html = page.sidebar();
  assert.ok(html.includes('★ Shortlist (2)'), `the shortlist count includes a removed program: ${html.match(/★ Shortlist[^<]*/)}`);
  assert.ok(html.includes('⇄ Compare (1)'), `the compare count includes a removed program: ${html.match(/⇄ Compare[^<]*/)}`);
  assert.ok(page.sandbox.S.favorites.has(GONE[0]), 'a saved slug was deleted rather than left uncounted');
});

test('#111 "Compare with …" names the first live compared program and never links a removed one', async () => {
  const page = loadPage({ 'cd.compare': [GONE[1], P1.slug] });
  await page.sandbox.loadIndex();
  const html = page.sandbox.glanceHtml(P2, {});
  const name = P1.shortName || P1.name;
  assert.ok(html.includes(`Compare with ${name} →`), `the link falls back to "selection" or names a removed program: ${html.match(/Compare with[^<]*/)}`);
  assert.ok(html.includes(`href="#/compare/${P1.slug},${P2.slug}"`), 'the compare link carries a removed program');
  assert.ok(!html.includes(GONE[1]), 'a removed program is linked');
});

test('#111 a removed program in the compare list does not use up one of the four places', async () => {
  const page = loadPage({ 'cd.compare': [GONE[0], GONE[1], P1.slug, P2.slug] });
  await page.sandbox.loadIndex();
  assert.equal(page.sandbox.toggleCompare(P3.slug), true, 'the fourth live program was refused because removed programs filled the list');
});

test('#111 West Florida\'s athletics host is stored as the final host (goargos.com, not www)', () => {
  const reg = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data/registry.json'), 'utf8'));
  const wf = (reg.programs || reg).find(p => p.slug === 'west-florida');
  assert.equal(wf?.athletics?.baseUrl, 'https://goargos.com');
});

/* ---------- Huatuo's R1 on PR #367: wherever the compare list is cut, it is cut by LIVE programs ---------- */
test('#111 R1 reload: a removed program saved with four live ones does not push a live one out', async () => {
  const page = loadPage({ 'cd.compare': [GONE[0], P1.slug, P2.slug, P3.slug, P4.slug] });
  await page.sandbox.loadIndex();
  const cmp = [...page.sandbox.S.compare];
  for (const p of [P1, P2, P3, P4]) assert.ok(cmp.includes(p.slug), `the reload lost ${p.slug}: ${cmp}`);
});

test('#111 R1 compare route: a link with a removed program and four live ones keeps all four live', async () => {
  const page = loadPage({});
  await page.sandbox.loadIndex();
  page.sandbox.location.hash = `#/compare/${GONE[0]},${P1.slug},${P2.slug},${P3.slug},${P4.slug}`;
  try { await page.sandbox.route(); } catch { /* the stub DOM cannot draw the compare page; the list is set first */ }
  const cmp = [...page.sandbox.S.compare];
  for (const p of [P1, P2, P3, P4]) assert.ok(cmp.includes(p.slug), `the compare route lost ${p.slug}: ${cmp}`);
  assert.ok(!cmp.includes(P5.slug));
});

test('#111 R1 the sidebar "Open comparison" link carries live programs only', async () => {
  const page = loadPage({ 'cd.compare': [GONE[0], P1.slug, P2.slug] });
  await page.sandbox.loadIndex();
  page.sandbox.S.sidebarTab = 'compare';
  page.sandbox.renderSidebar();
  assert.ok(page.sidebar().includes(`href="#/compare/${P1.slug},${P2.slug}"`), 'the Open comparison link carries a removed program');
});

test('#111 "Compare my shortlist" takes four LIVE favourites', async () => {
  const page = loadPage({ 'cd.favorites': [GONE[0], P1.slug, GONE[1], P2.slug, P3.slug, P4.slug, P5.slug] });
  await page.sandbox.loadIndex();
  page.sandbox.S.sidebarTab = 'shortlist';
  page.sandbox.renderSidebar();
  const btn = page.el('#cmpShortlist');
  assert.equal(typeof btn.onclick, 'function', 'the Compare my shortlist button was not wired');
  btn.onclick();
  assert.deepEqual([...page.sandbox.S.compare], [P1.slug, P2.slug, P3.slug, P4.slug], 'removed favourites took compare places');
  assert.equal(page.sandbox.location.hash, `#/compare/${P1.slug},${P2.slug},${P3.slug},${P4.slug}`);
});
