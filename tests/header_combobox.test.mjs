// The header box's suggestions (#434 PR 2): an ARIA 1.2 editable combobox with list autocomplete.
//
//     node --test tests/header_combobox.test.mjs
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM that keeps attributes, class lists,
// listeners and focus, as the other page tests do. Keys go through the box's own keydown listener; the listbox is read
// from what the page writes into #qList. Expected names, divisions and counts come from the committed index and from
// the list the page draws, never from the page's own helpers. Nothing leaves the process.
//
// What it CANNOT prove, and a human must check: what VoiceOver, NVDA or TalkBack actually announce, real key events on
// a phone, and pixels (local serve.py screenshots are in the PR).
//
// COMBOBOX_TEST_HTML (optional) points at another copy of index.html, to show these checks failing before PR 2.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = fs.readFileSync(process.env.COMBOBOX_TEST_HTML || path.join(PUBLIC, 'index.html'), 'utf8');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const row = slug => INDEX.programs.find(p => p.slug === slug);
const shown = p => p.shortName || p.name;
const escHtml = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const FOCUS = { el: null };
function makeElement(name) {
  const listeners = {}, attrs = {}, classes = new Set();
  let txt = '';
  const el = {
    _name: name, _listeners: listeners, _attrs: attrs, _textWrites: 0, innerHTML: '', value: '', title: '', hidden: false, scrollTop: 0,
    placeholder: '', dataset: {}, style: {},
    setAttribute(k, v) { attrs[k] = String(v); }, getAttribute: k => attrs[k] ?? null, removeAttribute(k) { delete attrs[k]; },
    classList: { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c),
      toggle: (c, f) => { const on = f === undefined ? !classes.has(c) : !!f; on ? classes.add(c) : classes.delete(c); return on; } },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { FOCUS.el = name; }, blur() { }, contains: () => false,
  };
  Object.defineProperty(el, 'textContent', { get: () => txt, set: v => { txt = String(v); el._textWrites++; }, enumerable: true });
  return el;
}
function loadPage() {
  const els = new Map(), requests = [];
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
    document: { documentElement: makeElement('html'), body: makeElement('body'), activeElement: null, querySelector: bySelector,
      querySelectorAll: () => [], createElement: makeElement, addEventListener() { } },
    location: { hash: '#/', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    innerWidth: 1280, addEventListener() { },
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
    + `\n;for (const k of ['S', 'route', 'setQuery', 'renderList', 'renderSidebar', 'loadIndex']) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, $: bySelector, requests };
}
const settle = (ms = 120) => new Promise(r => setTimeout(r, ms));
async function ready() {
  const pg = loadPage();
  await pg.sb.loadIndex();
  await settle(30);
  Object.assign(pg.sb.S.filters, { view: 'cards', region: [], division: [], conf: [], cond: [] });
  return pg;
}
async function type(pg, text) {
  const box = pg.$('#q');
  box.value = text;
  for (const fn of box._listeners.input || []) fn({ target: box });
  await settle();
}
function key(pg, k, extra = {}) {
  let prevented = false;
  for (const fn of pg.$('#q')._listeners.keydown || []) fn({ key: k, shiftKey: false, altKey: false, preventDefault() { prevented = true; }, ...extra });
  return prevented;
}
// The options as the page wrote them: [{ id, name, sub, selected, outside }].
function options(pg) {
  const html = pg.$('#qList').innerHTML;
  const groupAt = html.indexOf('role="group"');
  return [...html.matchAll(/<div role="option" id="([^"]+)"[^>]*aria-selected="(true|false)"[^>]*>([\s\S]*?)<\/div>/g)].map(m => ({
    id: m[1], selected: m[2] === 'true', at: m.index,
    name: /<span class="qopt-name">([\s\S]*?)<\/span>/.exec(m[3])?.[1] ?? '',
    sub: /<span class="team-sub">([\s\S]*)<\/span>$/.exec(m[3])?.[1] ?? '',
    outside: groupAt >= 0 && m.index > groupAt && m.id?.startsWith?.('qOpt-out-') !== false && /^qOpt-out-/.test(m[1]),
  }));
}
const box = pg => pg.$('#q');
const cardSlugs = html => [...html.matchAll(/class="card pcard[^"]*" data-slug="([^"]+)"/g)].map(m => m[1]);

test('markup: the box is an editable combobox that controls a labelled listbox, with a hint', () => {
  const input = /<input[^>]*id="q"[^>]*>/.exec(HTML)?.[0] || '';
  for (const a of ['role="combobox"', 'aria-autocomplete="list"', 'aria-expanded="false"', 'aria-controls="qList"', 'aria-describedby="qHint"'])
    assert.ok(input.includes(a), `#q lacks ${a}`);
  assert.match(HTML, /<div class="qlist" id="qList" role="listbox" aria-label="Suggestions" hidden><\/div>/);
  assert.match(HTML, /<span class="sr-only" id="qHint">Type a school, mascot, state or city\. Down arrow for suggestions\.<\/span>/);
});

test('typing opens the list with no option active; the arrows move and wrap, named by aria-activedescendant', async () => {
  const pg = await ready();
  await type(pg, 'ohio');
  assert.equal(box(pg)._attrs['aria-expanded'], 'true', 'the list did not open');
  assert.equal(pg.$('#qList').hidden, false);
  assert.equal(box(pg)._attrs['aria-activedescendant'], undefined, 'an option is active before any arrow');
  const opts = options(pg);
  assert.ok(opts.length >= 3, `too few options: ${opts.length}`);
  assert.ok(opts.every(o => !o.selected));
  assert.equal(key(pg, 'ArrowDown'), true, 'ArrowDown was not taken by the list');
  assert.equal(box(pg)._attrs['aria-activedescendant'], opts[0].id);
  assert.ok(options(pg)[0].selected, 'the active option is not aria-selected');
  key(pg, 'ArrowUp');
  assert.equal(box(pg)._attrs['aria-activedescendant'], opts[opts.length - 1].id, 'ArrowUp from the first did not wrap to the last');
  key(pg, 'ArrowDown');
  assert.equal(box(pg)._attrs['aria-activedescendant'], opts[0].id, 'ArrowDown from the last did not wrap to the first');
  assert.equal(options(pg).filter(o => o.selected).length, 1, 'more than one option is selected');
});

test('Esc closes an open list first and clears the box only when closed; Tab closes it; Alt+Down opens without moving', async () => {
  const pg = await ready();
  await type(pg, 'duke');
  key(pg, 'ArrowDown');
  key(pg, 'Escape');
  assert.equal(box(pg)._attrs['aria-expanded'], 'false');
  assert.equal(box(pg)._attrs['aria-activedescendant'], undefined);
  assert.equal(pg.sb.S.qRaw, 'duke', 'the first Esc cleared the box');
  key(pg, 'Escape');
  assert.equal(pg.sb.S.qRaw, '', 'the second Esc did not clear the box');
  await type(pg, 'duke');
  key(pg, 'Tab');
  assert.equal(box(pg)._attrs['aria-expanded'], 'false', 'Tab left the list open');
  key(pg, 'ArrowDown', { altKey: true });
  assert.equal(box(pg)._attrs['aria-expanded'], 'true', 'Alt+Down did not open the list');
  assert.equal(box(pg)._attrs['aria-activedescendant'], undefined, 'Alt+Down moved the active option');
});

test('every program option shows shortName || name and its division tag first', async () => {
  const pg = await ready();
  for (const q of ['state', 'washington', 'ohio', 'saint']) {
    await type(pg, q);
    const progs = options(pg).filter(o => /^qOpt-(out-)?[a-z0-9-]+$/.test(o.id) && !/^qOpt-(place|ask)$/.test(o.id));
    assert.ok(progs.length > 0, `no program options for "${q}"`);
    assert.ok(progs.filter(o => !o.outside).length <= 6 && progs.filter(o => o.outside).length <= 3, 'too many options');
    for (const o of progs) {
      const p = row(o.id.replace(/^qOpt-(out-)?/, ''));
      assert.ok(p, `${o.id} names no program`);
      assert.equal(o.name, escHtml(shown(p)), `${p.slug}: the option reads "${o.name}"`);
      assert.match(o.sub, new RegExp(`^<span class="div-tag"[^>]*>${p.division}</span>`), `${p.slug}: no ${p.division} tag first`);
    }
  }
});

test('a place: one option for the whole list, counted as the list draws it; choosing it shows that list', async () => {
  const pg = await ready();
  await type(pg, 'Ohio');
  await pg.sb.renderList();
  const n = cardSlugs(pg.$('#app').innerHTML).length;
  const place = options(pg).find(o => o.id === 'qOpt-place');
  assert.ok(place, 'no place option for "Ohio"');
  assert.equal(place.name, `All ${n} matching programs →`, 'the place option does not count what the list shows');
  assert.equal(place.sub, 'including every program in Ohio');
  const opts = options(pg);
  for (let i = 0; i <= opts.findIndex(o => o.id === 'qOpt-place'); i++) key(pg, 'ArrowDown');
  assert.equal(box(pg)._attrs['aria-activedescendant'], 'qOpt-place');
  key(pg, 'Enter');
  await settle(20);
  assert.equal(pg.sb.location.hash, '#/', 'choosing the place opened something else');
  assert.equal(pg.sb.S.qRaw, 'Ohio', 'choosing the place cleared the query');
  assert.equal(box(pg)._attrs['aria-expanded'], 'false');
});

test('Huatuo condition 1: a saved South filter, "Stanford" typed on a profile page - one option under "Outside your filters", and choosing it opens Stanford with the filters kept', async () => {
  const pg = await ready();
  assert.equal(row('stanford')?.region, 'West', 'fixture: Stanford is in the West');
  pg.sb.S.filters.region = ['South'];
  pg.sb.location.hash = '#/p/duke';
  await type(pg, 'Stanford');
  assert.equal(pg.sb.location.hash, '#/p/duke', 'typing on a profile page left it');
  const html = pg.$('#qList').innerHTML;
  assert.match(html, /<div role="group" aria-label="Outside your filters"><div class="qgroup-label" aria-hidden="true">Outside your filters<\/div><div role="option" id="qOpt-out-stanford"/);
  assert.deepEqual(options(pg).map(o => o.id), ['qOpt-out-stanford']);
  assert.match(pg.$('#qStatus').textContent, /^No match within your filters \(1 without them\)$/);
  key(pg, 'Enter');  // no active option: #23 - never opens a program the filters hide
  await settle(20);
  assert.equal(pg.sb.location.hash, '#/p/duke', 'Enter with no active option opened a hidden program');
  key(pg, 'ArrowDown');
  assert.equal(box(pg)._attrs['aria-activedescendant'], 'qOpt-out-stanford');
  key(pg, 'Enter');
  await settle(20);
  assert.equal(pg.sb.location.hash, '#/p/stanford', 'choosing the option did not open Stanford');
  assert.deepEqual([...pg.sb.S.filters.region], ['South'], 'choosing it changed the filters');
});

test('on a profile page typing only suggests; a program picked from search takes focus to its <h1>, and only then', async () => {
  const pg = await ready();
  pg.sb.location.hash = '#/p/duke';
  await type(pg, 'ohio');
  await settle(150);
  assert.equal(pg.sb.location.hash, '#/p/duke', 'typing on a profile page sent it to the list');
  FOCUS.el = null;
  await pg.sb.route(); await settle(60);
  assert.notEqual(FOCUS.el, '.content-title', 'an ordinary route moved focus to the heading');
  await type(pg, 'kenyon');
  key(pg, 'ArrowDown'); key(pg, 'Enter');
  assert.equal(pg.sb.location.hash, '#/p/kenyon-college');
  assert.equal(box(pg).value, '', 'the box kept the query after a pick');
  await pg.sb.route(); await settle(60);
  assert.equal(FOCUS.el, '.content-title', 'focus did not move to the profile heading after a search pick');
  assert.equal(pg.$('.content-title')._attrs.tabindex, '-1');
});

test('mouse: pressing an option keeps the box focused, and a click chooses it', async () => {
  const pg = await ready();
  pg.sb.location.hash = '#/';
  await type(pg, 'kenyon');
  const list = pg.$('#qList');
  let prevented = false;
  for (const fn of list._listeners.mousedown || []) fn({ preventDefault() { prevented = true; } });
  assert.ok(prevented, 'mousedown on the list does not keep focus in the box');
  const first = options(pg)[0];
  const optEl = { dataset: { i: '0' } };
  for (const fn of list._listeners.click || []) fn({ target: { closest: sel => (sel === '[role="option"]' ? optEl : null) } });
  assert.equal(pg.sb.location.hash, `#/p/${first.id.replace(/^qOpt-/, '')}`);
});

// Huatuo's two follow-ups on #445, folded into #447.
test('#445 follow-up: #qStatus is rewritten only when its words change (a filter tap with a query typed is not re-announced)', async () => {
  const pg = await ready();
  pg.sb.location.hash = '#/';
  await type(pg, 'Ohio');
  const st = pg.$('#qStatus'), said = st.textContent, before = st._textWrites;
  assert.ok(said, 'fixture: the status is empty');
  pg.sb.renderSidebar(); pg.sb.renderSidebar();  // what a pill tap does: the sidebar redraws and the status is refreshed
  assert.equal(st.textContent, said);
  assert.equal(st._textWrites, before, 'the same status was written again, so a screen reader announces it again');
});

test('#445 follow-up: picking the profile already on screen leaves no focus flag for the next profile', async () => {
  const pg = await ready();
  pg.sb.location.hash = '#/p/kenyon-college';
  await pg.sb.route(); await settle(60);
  await type(pg, 'kenyon');
  key(pg, 'ArrowDown'); key(pg, 'Enter');
  assert.equal(pg.sb.location.hash, '#/p/kenyon-college');
  assert.ok(!pg.sb.S.titleFocus, 'the focus flag was left set');
  FOCUS.el = null;
  pg.sb.location.hash = '#/p/duke';
  await pg.sb.route(); await settle(60);
  assert.notEqual(FOCUS.el, '.content-title', 'an unrelated profile took heading focus from a stale flag');
});

test('no request while typing or moving through the suggestions', async () => {
  const pg = await ready();
  const before = pg.requests.length;
  await type(pg, 'state'); key(pg, 'ArrowDown'); key(pg, 'ArrowDown'); key(pg, 'ArrowUp'); key(pg, 'Escape');
  await type(pg, 'Ohio'); key(pg, 'ArrowDown');
  assert.deepEqual(pg.requests.slice(before), [], 'the suggestions fetched something');
});
