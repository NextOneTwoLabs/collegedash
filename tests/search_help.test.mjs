// The header search's help panel (#447): a scope line counted from the index, an instruction, example chips and, on a
// desktop, key hints - when the box is focused and empty; a no-match panel with a hint and 2 chips when typing finds
// nothing. The owner's four decisions on #447 are the spec.
//
//     node --test tests/search_help.test.mjs
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM that keeps attributes, listeners and
// focus (as tests/header_combobox.test.mjs). Expected counts and divisions come from the committed index, and "a chip
// returns a result" is read from the cards the list draws for it, never from the page's own search code.
//
// What it CANNOT prove, and a human must check: what a screen reader actually says, and pixels (local serve.py
// screenshots are in the PR).
//
// SEARCH_HELP_TEST_HTML (optional) points at another copy of index.html, to show these checks failing on main.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = fs.readFileSync(process.env.SEARCH_HELP_TEST_HTML || path.join(PUBLIC, 'index.html'), 'utf8');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const N = INDEX.programs.length.toLocaleString('en-US');
const DIVS = [...new Set(INDEX.programs.map(p => p.division).filter(Boolean))].sort();
const DESKTOP_CHIPS = ['Stanford', 'UNC', 'Bulldogs', 'Ohio', 'Columbus OH'];  // owner decision 1
const PHONE_CHIPS = ['Stanford', 'Ohio', 'Bulldogs'];                          // owner decision 2
const NOMATCH_CHIPS = ['Stanford', 'Ohio'];                                     // owner decision 3 (2 chips)

const FOCUS = { el: null };
function makeElement(name) {
  const listeners = {}, attrs = {}, classes = new Set();
  return {
    _name: name, _listeners: listeners, _attrs: attrs, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    placeholder: '', dataset: {}, style: {},
    setAttribute(k, v) { attrs[k] = String(v); }, getAttribute: k => attrs[k] ?? null, removeAttribute(k) { delete attrs[k]; },
    classList: { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c),
      toggle: (c, f) => { const on = f === undefined ? !classes.has(c) : !!f; on ? classes.add(c) : classes.delete(c); return on; } },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { FOCUS.el = name; }, blur() { }, contains: () => false,
  };
}
function loadPage(width) {
  const els = new Map(), requests = [], writes = [];
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const readPublic = url => {
    let rel = url.replace(/^\//, '');
    if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
    else if (rel.startsWith('api/v1/programs/')) rel = `data/programs/${rel.slice('api/v1/programs/'.length)}.json`;
    const p = path.join(PUBLIC, rel);
    return p.startsWith(PUBLIC) && fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), activeElement: null, querySelector: bySelector,
      querySelectorAll: () => [], createElement: makeElement, addEventListener() { } },
    location: { hash: '#/', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: () => null, setItem: (k) => writes.push(k), removeItem: (k) => writes.push(k) },
    innerWidth: width, addEventListener() { },
    fetch: async url => {
      requests.push(String(url));
      const b = readPublic(String(url));
      if (b == null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      return { ok: true, status: 200, async json() { return JSON.parse(b); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = HTML.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'index.html: could not find the inline <script>');
  const src = lines.slice(a + 1, b).join('\n')
    + `\n;for (const k of ['S', 'setQuery', 'renderList', 'loadIndex']) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, $: bySelector, requests, writes };
}
const settle = (ms = 120) => new Promise(r => setTimeout(r, ms));
async function ready(width = 1280) {
  const pg = loadPage(width);
  await pg.sb.loadIndex();
  await settle(30);
  Object.assign(pg.sb.S.filters, { view: 'cards', region: [], division: [], conf: [], cond: [] });
  return pg;
}
const box = pg => pg.$('#q');
function focusBox(pg) { for (const fn of box(pg)._listeners.focus || []) fn({ target: box(pg) }); }
async function type(pg, text) { box(pg).value = text; for (const fn of box(pg)._listeners.input || []) fn({ target: box(pg) }); await settle(); }
function key(pg, k) { for (const fn of box(pg)._listeners.keydown || []) fn({ key: k, shiftKey: false, altKey: false, preventDefault() { } }); }
const chipNames = pg => [...pg.$('#qList').innerHTML.matchAll(/<div role="option" id="qOpt-chip-[^"]+"[^>]*><span class="qopt-name">([^<]*)<\/span><\/div>/g)].map(m => m[1]);
const text = h => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
const cardCount = html => (html.match(/class="card pcard/g) || []).length;

test('markup: the panel under the box holds the help, the listbox and the key hints, and starts hidden', () => {
  assert.match(HTML, /<div class="qpanel" id="qPanel" hidden>\s*<div class="qhelp" id="qHelp"><\/div>\s*<div class="qlist" id="qList" role="listbox" aria-label="Suggestions" hidden><\/div>\s*<div class="qhelp-foot" id="qFoot" aria-hidden="true"><\/div>\s*<\/div>/);
});

test('desktop: focusing the empty box opens the help - scope counted from the index, the instruction, 5 chips, the keys', async () => {
  const pg = await ready(1280);
  focusBox(pg);
  assert.equal(pg.$('#qPanel').hidden, false, 'the panel did not open on focus');
  assert.equal(box(pg)._attrs['aria-expanded'], 'true');
  const scope = `Every NCAA women's soccer program: ${N} across ${DIVS.slice(0, -1).join(', ')} and ${DIVS[DIVS.length - 1]}.`;
  assert.equal(text(pg.$('#qHelp').innerHTML), `${scope.replace(/'/g, '&#39;')} Type a school, nickname or mascot, a state or a city. For example:`);
  assert.match(pg.$('#qList').innerHTML, /^<div role="group" aria-label="Examples" class="qchips">/, 'the chips are not a labelled group in the listbox');
  assert.deepEqual(chipNames(pg), DESKTOP_CHIPS);
  assert.equal(text(pg.$('#qFoot').innerHTML), '↑ ↓ move · Enter open · Esc close Filters on the left still apply');
  assert.equal(pg.$('#qStatus').textContent, `${scope} Type a school, nickname or mascot, a state or a city. Down arrow for examples.`,
    'the one live region does not announce the help');
});

test('phone: 3 chips, a one-line scope, and no keyboard hints', async () => {
  const pg = await ready(375);
  focusBox(pg);
  assert.equal(text(pg.$('#qHelp').innerHTML), `${N} programs, ${DIVS[0]}–${DIVS[DIVS.length - 1]}. Try:`);
  assert.deepEqual(chipNames(pg), PHONE_CHIPS);
  assert.equal(pg.$('#qFoot').innerHTML, '', 'keyboard hints on a phone');
});

test('the arrows reach the chips and Enter runs that search; a click does the same', async () => {
  const pg = await ready(1280);
  pg.sb.location.hash = '#/';
  focusBox(pg);
  key(pg, 'ArrowDown');
  assert.equal(box(pg)._attrs['aria-activedescendant'], 'qOpt-chip-stanford');
  key(pg, 'ArrowDown'); key(pg, 'ArrowDown');
  assert.equal(box(pg)._attrs['aria-activedescendant'], 'qOpt-chip-bulldogs');
  key(pg, 'Enter');
  await settle();
  assert.equal(pg.sb.S.qRaw, 'Bulldogs');
  assert.equal(box(pg).value, 'Bulldogs');
  assert.equal(pg.$('#qHelp').innerHTML, '', 'the help stayed after a chip ran its search');
  assert.ok(/role="option" id="qOpt-(?!chip)/.test(pg.$('#qList').innerHTML), 'the suggestions did not replace the chips');
  box(pg).value = ''; pg.sb.setQuery(''); await settle(); focusBox(pg);
  for (const fn of pg.$('#qList')._listeners.click || []) fn({ target: { closest: s => (s === '[role="option"]' ? { dataset: { i: '3' } } : null) } });
  await settle();
  assert.equal(pg.sb.S.qRaw, 'Ohio', 'clicking the fourth chip did not run "Ohio"');
});

test('owner decision 1: every chip returns at least one result', async () => {
  const pg = await ready(1280);
  for (const chip of [...new Set([...DESKTOP_CHIPS, ...PHONE_CHIPS, ...NOMATCH_CHIPS])]) {
    pg.sb.location.hash = '#/';
    box(pg).value = ''; pg.sb.setQuery(''); await settle();
    focusBox(pg);
    const i = chipNames(pg).indexOf(chip);
    assert.ok(i >= 0, `"${chip}" is not offered`);
    for (const fn of pg.$('#qList')._listeners.click || []) fn({ target: { closest: s => (s === '[role="option"]' ? { dataset: { i: String(i) } } : null) } });
    await settle();
    await pg.sb.renderList();
    assert.ok(cardCount(pg.$('#app').innerHTML) >= 1, `"${chip}" lists no program`);
  }
});

test('no match: "No program matches …" with the hint and 2 chips, and the status says so', async () => {
  const pg = await ready(1280);
  focusBox(pg);
  await type(pg, 'zzqx');
  assert.equal(text(pg.$('#qHelp').innerHTML), 'No program matches “zzqx”. Try a school\'s short name, a mascot, a full state name, or a state code in capitals (OH):');
  assert.deepEqual(chipNames(pg), NOMATCH_CHIPS);
  assert.match(pg.$('#qStatus').textContent, /^No match/);
  await type(pg, 'stanford');
  assert.equal(pg.$('#qHelp').innerHTML, '', 'the no-match panel outlived the match');
});

test('the panel never offers conference search, and stores nothing and fetches nothing', async () => {
  const pg = await ready(1280);
  const req = pg.requests.length, wr = pg.writes.length;
  for (const q of ['', 'zzqx']) {
    box(pg).value = ''; pg.sb.setQuery(''); await settle();
    focusBox(pg);
    if (q) await type(pg, q);
    const said = [pg.$('#qHelp').innerHTML, pg.$('#qFoot').innerHTML, ...chipNames(pg), pg.$('#qStatus').textContent].join(' ');
    assert.ok(!/conference/i.test(said), `the panel mentions conferences: ${said}`);
  }
  key(pg, 'ArrowDown'); key(pg, 'Enter'); await settle();
  assert.deepEqual(pg.requests.slice(req), [], 'the help fetched something');
  assert.deepEqual(pg.writes.slice(wr), [], 'the help saved something (no recent searches: owner decision 4)');
});

test('Esc closes the help; the panel closes when the box loses focus', async () => {
  const pg = await ready(1280);
  focusBox(pg);
  key(pg, 'Escape');
  assert.equal(pg.$('#qPanel').hidden, true);
  assert.equal(box(pg)._attrs['aria-expanded'], 'false');
  focusBox(pg);
  for (const fn of box(pg)._listeners.blur || []) fn({});
  assert.equal(pg.$('#qPanel').hidden, true, 'the panel stayed open after blur');
});
