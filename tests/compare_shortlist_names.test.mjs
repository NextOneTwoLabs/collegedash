// Tests for issues #405 and #406 (both confirmed in Huatuo's review on #404).
//
//     node --test tests/compare_shortlist_names.test.mjs
//
// #405: a Compare chip labelled a program with no shortName (89 of them, all D2 or D3) by its URL slug. It now uses
//       the name every other view shows: shortName, else name.
// #406: both shortlist surfaces (the sidebar's shortlist tab and #/shortlist) sorted by RPI, which ranks within a
//       division, so a saved D2 or D3 program always sat below every saved D1. They now take the list's Name sort,
//       by the displayed name, and both "Compare 4" controls take the first four in that order.
//
// Same mechanism as tests/shortlist_unsave.test.mjs: the inline <script> is pulled out of public/index.html and run
// in a `vm` against a stub DOM that records innerHTML; fetches are answered from the committed public/data, nothing
// leaves the machine. The programs are real ones from the shipped index, and every expectation below is written out
// by hand (names and slugs), never computed with the page's own helpers.
//
// NAMES_TEST_HTML (optional) points the suite at another copy of index.html, so the page from before this change
// can be run through these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.NAMES_TEST_HTML || path.join(PUBLIC, 'index.html');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const row = slug => INDEX.programs.find(p => p.slug === slug);

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
  const readPublic = url => {
    let rel = url.replace(/^\//, '');
    if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
    else if (rel.startsWith('api/v1/programs/')) rel = `data/programs/${rel.slice('api/v1/programs/'.length)}.json`;
    const p = path.join(PUBLIC, rel);
    return p.startsWith(PUBLIC) && fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  };
  const store = new Map();
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
    innerWidth: 1400,
    addEventListener() { },
    alert() { },
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
    + `\n;for (const k of ['S', 'renderShortlist', 'renderSidebar', 'renderCompare', 'loadIndex']) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}

const html = (sb, sel) => sb.document.querySelector(sel).innerHTML;
const text = h => h.replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();

// ---------- #405 ----------
// alabama-huntsville is a D2 program with no shortName; ucla has one.
const NO_SHORT = 'alabama-huntsville', NO_SHORT_NAME = 'University of Alabama in Huntsville';

test('#405 fixture: alabama-huntsville has a name and no shortName in the shipped index', () => {
  assert.equal(row(NO_SHORT)?.name, NO_SHORT_NAME);
  assert.ok(!row(NO_SHORT).shortName, 'alabama-huntsville now has a shortName; pick another program without one');
  assert.equal(row('ucla')?.shortName, 'UCLA');
});

test('#405: a Compare chip shows the name of a program with no shortName, never its slug', async () => {
  const sb = loadPage();
  sb.S.compare = [NO_SHORT, 'ucla'];
  await sb.renderCompare();
  const chips = [...html(sb, '#app').matchAll(/<span class="chip">([\s\S]*?)<button class="chip-x" data-cmp="([^"]+)"/g)]
    .map(m => [m[2], text(m[1])]);
  assert.deepEqual(chips, [[NO_SHORT, NO_SHORT_NAME], ['ucla', 'UCLA']]);
});

// ---------- #406 ----------
// Five saved programs across all three divisions, saved in an order that is neither the name order nor the RPI order.
// Their displayed names, in the list's Name order: Abilene Christian (D1), Adelphi (D2), Adrian (D3),
// University of Alabama in Huntsville (D2, no shortName: sorted by its name), Yale (D1).
const SAVED = ['yale', 'adrian-college', NO_SHORT, 'abilene-christian', 'adelphi'];
const NAME_ORDER = ['abilene-christian', 'adelphi', 'adrian-college', NO_SHORT, 'yale'];

test('#406 fixture: the shortlist spans D1, D2 and D3 with the displayed names the order below assumes', () => {
  assert.deepEqual(NAME_ORDER.map(s => row(s)?.division), ['D1', 'D2', 'D3', 'D2', 'D1']);
  assert.deepEqual(NAME_ORDER.map(s => row(s).shortName || row(s).name),
    ['Abilene Christian', 'Adelphi', 'Adrian', NO_SHORT_NAME, 'Yale']);
});

async function shortlisted() {
  const sb = loadPage();
  await sb.loadIndex();
  sb.S.favorites.clear();
  SAVED.forEach(s => sb.S.favorites.add(s));
  return sb;
}

test('#406: #/shortlist lists a mixed-division shortlist in displayed-name order', async () => {
  const sb = await shortlisted();
  sb.location.hash = '#/shortlist';
  await sb.renderShortlist();
  const cards = [...html(sb, '#app').matchAll(/class="card pcard[^"]*" data-slug="([^"]+)"/g)].map(m => m[1]);
  assert.deepEqual(cards, NAME_ORDER);
});

test('#406: the #/shortlist "Compare 4" link takes the first four in that order', async () => {
  const sb = await shortlisted();
  sb.location.hash = '#/shortlist';
  await sb.renderShortlist();
  const m = /href="#\/compare\/([^"]+)">⇄ Compare 4</.exec(html(sb, '#app'));
  assert.ok(m, 'no Compare 4 link on #/shortlist');
  assert.deepEqual(m[1].split(','), NAME_ORDER.slice(0, 4));
});

test('#406: the sidebar shortlist tab lists the same programs in the same order', async () => {
  const sb = await shortlisted();
  sb.location.hash = '#/';
  sb.S.sidebarTab = 'shortlist';
  sb.renderSidebar();
  const rows = [...html(sb, '#sidebar').matchAll(/<li class="side-item" data-open="([^"]+)"/g)].map(m => m[1]);
  assert.deepEqual(rows, NAME_ORDER);
});

test('#406: the sidebar "Compare 4" button compares the first four in that order', async () => {
  const sb = await shortlisted();
  sb.location.hash = '#/';
  sb.S.sidebarTab = 'shortlist';
  sb.renderSidebar();
  assert.match(html(sb, '#sidebar'), /id="cmpShortlist">Compare 4</, 'no Compare 4 button in the sidebar');
  const btn = sb.document.querySelector('#cmpShortlist');
  assert.equal(typeof btn.onclick, 'function', 'the sidebar Compare button has no click handler');
  btn.onclick();
  assert.deepEqual([...sb.S.compare], NAME_ORDER.slice(0, 4));
  assert.equal(sb.location.hash, `#/compare/${NAME_ORDER.slice(0, 4).join(',')}`);
});
