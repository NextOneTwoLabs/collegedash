// #507 v1, PR 2: the search box in the Home hero (docs/plans/507-search/v1-plan.md, sections 3 and 4).
//
//     node --test tests/home_search.test.mjs
//
// The page's inline <script> runs in a `vm` against a stub DOM, as tests/shell_nav.test.mjs does. Data: the frozen
// fixture tests/fixtures/search/{programs,camps}.json only, served for /api/v1/programs and /api/v1/camps; every other
// request is a 404. The clock is the fixture's date at local noon (a Date whose no-argument constructor and now() give
// it; new Date(arg) stays real), so "upcoming" never depends on the day the test runs. No network.
//
// What is checked:
//   - markup: a labelled ARIA 1.2 combobox between Home's line and its three options, its listbox (#homeList), the
//     message line (#homeMsg) outside the listbox, one polite status (#homeStatus); no box when the index failed;
//   - the listbox holds only groups and options; each group is named by its aria-hidden heading (aria-labelledby);
//   - every option tied to a program shows its division (div-tag) and shortName || name;
//   - messages (no match, no camp, loading, couldn't load) are in #homeMsg, never in the listbox, and in #homeStatus;
//   - the camps index is requested once, at the first focus, and nothing is requested while typing;
//   - keys: arrows move and wrap, Enter opens the active option or the engine's Enter target, Escape closes then
//     clears; a click on an option opens it; "Show all N camps" expands in place.
//
// What it CANNOT prove: the rendered layout and the screen reader's speech. Those are the PR's browser check
// (Playwright on local serve.py at 320/375/768/1440 px in both themes) and tests/home_search_css.test.mjs's pins.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HTML = fs.readFileSync(process.env.HOME_SEARCH_TEST_HTML || path.join(HERE, '..', 'public', 'index.html'), 'utf8');
const FIX = path.join(HERE, 'fixtures', 'search');
const PROGRAMS_TEXT = fs.readFileSync(path.join(FIX, 'programs.json'), 'utf8');
const CAMPS_TEXT = fs.readFileSync(path.join(FIX, 'camps.json'), 'utf8');
const PROGRAMS = JSON.parse(PROGRAMS_TEXT), CAMPS = JSON.parse(CAMPS_TEXT);
const CLOCK = CAMPS.updated.slice(0, 10);
const BY_SLUG = new Map(PROGRAMS.programs.map(p => [p.slug, p]));
const display = p => p.shortName || p.name;

const FOCUS = { el: null };
function makeEl(name, extra = {}) {
  const listeners = {}, classes = new Set(), attrs = new Map(extra.attrs || []);
  return {
    _name: name, id: name.startsWith('#') ? name.slice(1) : '', _listeners: listeners, _attrs: attrs, innerHTML: '', textContent: '',
    value: '', title: '', hidden: false, scrollTop: 0, dataset: extra.dataset || {}, style: {}, placeholder: '',
    setAttribute: (k, v) => attrs.set(k, String(v)), getAttribute: k => (attrs.has(k) ? attrs.get(k) : null), removeAttribute: k => attrs.delete(k),
    classList: { add: (...c) => c.forEach(x => classes.add(x)), remove: (...c) => c.forEach(x => classes.delete(x)), contains: c => classes.has(c),
      toggle: (c, f) => { const on = f === undefined ? !classes.has(c) : !!f; on ? classes.add(c) : classes.delete(c); return on; } },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); }, removeEventListener() { },
    querySelector: () => null, querySelectorAll: () => [], closest: () => null, matches: () => false, contains: () => false,
    scrollIntoView() { }, focus() { FOCUS.el = name; }, blur() { if (FOCUS.el === name) FOCUS.el = null; },
  };
}
const BODY = HTML.slice(HTML.indexOf('<body'), HTML.indexOf('<script>'));
const NAV = [...BODY.matchAll(/<a [^>]*data-nav="(\w+)"[^>]*>/g)].map((m, i) => makeEl(`nav${i}`, { dataset: { nav: m[1] } }));

// camps: 'ok' (the fixture), 'fail' (a 404), 'hang' (never answers); programs: 'ok' or 'fail'
function loadPage({ hash = '#/', width = 1280, camps = 'ok', programs = 'ok' } = {}) {
  const els = new Map(), docListeners = {}, requests = [], writes = [];
  const $ = sel => { if (!els.has(sel)) els.set(sel, makeEl(sel)); return els.get(sel); };
  const noon = new Date(`${CLOCK}T12:00:00`).getTime();
  class FixedDate extends Date {
    constructor(...a) { if (a.length) super(...a); else super(noon); }
    static now() { return noon; }
  }
  const answer = (ok, text) => (ok ? { ok: true, status: 200, headers: { get: () => null }, async json() { return JSON.parse(text); } }
    : { ok: false, status: 404, headers: { get: () => null }, async json() { throw new Error('404'); } });
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date: FixedDate, JSON, Math, Number, String, Array, Object, RegExp, Intl, Error,
    isNaN, parseInt, parseFloat, URL, URLSearchParams, encodeURIComponent, decodeURIComponent,
    document: {
      documentElement: makeEl('html'), body: makeEl('body'), activeElement: null, title: '',
      querySelector: $, createElement: makeEl,
      querySelectorAll: sel => (sel === '[data-nav]' ? NAV : []),
      addEventListener(type, fn) { (docListeners[type] ||= []).push(fn); },
    },
    location: { hash, search: '', href: 'http://localhost/', replace(h) { this.hash = h; } },
    history: { replaceState(_, __, u) { sandbox.location.hash = u; }, pushState(_, __, u) { sandbox.location.hash = u; } },
    matchMedia: () => ({ matches: false }), innerWidth: width, screen: { width, height: 800 }, navigator: {},
    performance: { now: () => 0, getEntriesByName: () => [] }, requestAnimationFrame: f => setTimeout(f, 0),
    localStorage: { getItem: () => null, setItem: k => writes.push(k), removeItem: k => writes.push(k) },
    sessionStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    addEventListener() { },
    fetch: url => {
      const u = String(url).replace(/\?.*$/, '');
      requests.push(u);
      if (u === '/api/v1/programs') return Promise.resolve(answer(programs === 'ok', PROGRAMS_TEXT));
      if (u === '/api/v1/camps') return camps === 'hang' ? new Promise(() => { }) : Promise.resolve(answer(camps === 'ok', CAMPS_TEXT));
      return Promise.resolve(answer(false));
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = HTML.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const names = ['S', 'route'];
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(names)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  const fire = (type, e) => (docListeners[type] || []).forEach(fn => fn(e));
  const box = $('#homeQ');
  const key = (k, extra = {}) => { const e = { key: k, target: box, prevented: false, preventDefault() { e.prevented = true; }, ...extra }; fire('keydown', e); return e; };
  const type = async v => { box.value = v; fire('input', { target: box }); await settle(120); };
  const focus = async () => { FOCUS.el = '#homeQ'; sandbox.document.activeElement = box; fire('focusin', { target: box }); await settle(60); };
  return { sb: sandbox, $, box, fire, key, type, focus, requests, writes };
}
const settle = (ms = 250) => new Promise(r => setTimeout(r, ms));

// A small tree of the page's own markup (div/span/label/input/p/a), enough to check what sits where.
function tree(html) {
  const root = { tag: 'root', attrs: {}, kids: [], text: '' }, stack = [root];
  for (const m of String(html).matchAll(/<(\/?)([a-z0-9]+)([^>]*)>|([^<]+)/gi)) {
    if (m[4] != null) { stack.forEach(n => { n.text += m[4]; }); continue; }
    if (m[1]) { stack.pop(); continue; }
    const attrs = Object.fromEntries([...m[3].matchAll(/([\w-]+)(?:="([^"]*)")?/g)].map(x => [x[1], x[2] ?? '']));
    const n = { tag: m[2].toLowerCase(), attrs, kids: [], text: '' };
    stack[stack.length - 1].kids.push(n);
    if (!['input', 'br', 'img'].includes(n.tag)) stack.push(n);
  }
  return root;
}
const all = (n, f, out = []) => { if (f(n)) out.push(n); n.kids.forEach(k => all(k, f, out)); return out; };
const byId = (root, id) => all(root, n => n.attrs.id === id)[0];
const unesc = s => s.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
const results = pg => tree(pg.$('#homeResults').innerHTML);
const listOf = pg => byId(results(pg), 'homeList');
const options = pg => all(listOf(pg), n => n.attrs.role === 'option');
const msgOf = pg => byId(results(pg), 'homeMsg');
const statusOf = pg => pg.$('#homeStatus').textContent;

async function home(opts) { const pg = loadPage(opts); await settle(); return pg; }

test('markup: a labelled combobox between Home\'s line and its three options, its listbox, the message line and one polite status', async () => {
  const pg = await home();
  const html = pg.$('#app').innerHTML;
  const at = s => html.indexOf(s);
  assert.ok(at('class="content-subtitle"') < at('id="homeQ"') && at('id="homeQ"') < at('class="home-entries"'), 'the box is not between the line and the options');
  const t = tree(html);
  const input = byId(t, 'homeQ');
  assert.ok(input && input.tag === 'input', 'no input#homeQ');
  for (const [k, v] of [['type', 'search'], ['role', 'combobox'], ['aria-autocomplete', 'list'], ['aria-expanded', 'false'], ['aria-controls', 'homeList'], ['class', 'home-q']])
    assert.equal(input.attrs[k], v, `#homeQ ${k}`);
  assert.ok(byId(t, input.attrs['aria-describedby']), 'aria-describedby names nothing');
  const label = all(t, n => n.tag === 'label' && n.attrs.for === 'homeQ')[0];
  assert.match(label?.text || '', /Search programs and ID camps/);
  const list = byId(t, 'homeList');
  assert.equal(list?.attrs.role, 'listbox');
  assert.ok('hidden' in list.attrs, 'the listbox shows before anything is typed');
  assert.ok(byId(t, 'homeMsg') && !all(list, n => n.attrs.id === 'homeMsg').length, '#homeMsg is missing or inside the listbox');
  const status = byId(t, 'homeStatus');
  assert.equal(status?.attrs['aria-live'], 'polite');
  assert.equal((html.match(/aria-live=/g) || []).length, 1, 'more than one live region on Home');
  assert.equal(pg.sb.document.body.classList.contains('no-search'), true, 'the header box shows on Home');
});

test('no box when the program index failed: Home keeps its try-again card', async () => {
  const pg = await home({ programs: 'fail' });
  const html = pg.$('#app').innerHTML;
  assert.match(html, /home-entries/);
  assert.ok(!/id="homeQ"/.test(html), 'a box with no data behind it');
});

test('the camps index is requested once, at the first focus; typing requests nothing', async () => {
  const pg = await home();
  const camps = () => pg.requests.filter(u => u === '/api/v1/camps').length;
  const before = pg.requests.length;
  assert.equal(camps(), 0, 'camps loaded before the box was focused');
  await pg.focus();
  assert.equal(camps(), 1);
  for (const v of ['u', 'uc', 'ucl', 'ucla', 'ucla id', 'ucla id camp', 'TX', 'a', 'zzzz', '']) await pg.type(v);
  await pg.focus();
  assert.equal(camps(), 1, 'a second camps request');
  assert.deepEqual(pg.requests.slice(before), ['/api/v1/camps'], 'a request while typing');
});

test('"ucla id camp": ID Camps first, then Programs; the listbox holds only groups and options, each group named by its heading', async () => {
  const pg = await home();
  await pg.focus(); await pg.type('ucla id camp');
  const list = listOf(pg);
  assert.ok(!('hidden' in list.attrs));
  assert.equal(pg.box.getAttribute('aria-expanded'), 'true');
  assert.ok(list.kids.length >= 1 && list.kids.every(g => g.attrs.role === 'group'), 'a listbox child is not a group');
  for (const g of list.kids) {
    const [head, ...rest] = g.kids;
    assert.equal(head.attrs['aria-hidden'], 'true', 'the heading is not aria-hidden');
    assert.equal(g.attrs['aria-labelledby'], head.attrs.id, 'the group is not named by its heading');
    assert.ok(rest.length && rest.every(o => o.attrs.role === 'option' && o.attrs.id && o.attrs['aria-selected'] === 'false'), 'a group child is not an option');
  }
  assert.deepEqual(list.kids.map(g => g.kids[0].text), ['ID Camps · 1 upcoming', 'Programs · 1']);
  const opts = options(pg);
  assert.deepEqual(opts.map(o => o.attrs['data-kind']), ['camp', 'browse', 'program']);
  assert.match(unesc(opts[0].text), /College ID Camp/);
  assert.equal(opts[1].text, 'Browse all ID camps →');
  assert.equal(msgOf(pg).attrs.hidden, '', 'a message with results on screen');
  assert.equal(statusOf(pg), '1 program and 1 upcoming ID camp. Enter opens College ID Camp, UCLA.');
});

test('every option tied to a program shows its division and shortName || name', async () => {
  const pg = await home();
  await pg.focus();
  let seen = 0;
  for (const q of ['a', 'TX', 'trojans', 'id camp december', 'msu', 'st. mary\'s', 'usc camps']) {
    await pg.type(q);
    const k = pg.key('ArrowDown'); assert.ok(k.prevented);  // expand nothing; just make sure the list is open
    for (const o of options(pg).filter(o => o.attrs['data-slug'])) {
      const p = BY_SLUG.get(o.attrs['data-slug']);
      const tags = all(o, n => /\bdiv-tag\b/.test(n.attrs.class || ''));
      assert.equal(tags.length, 1, `${q}: ${p.slug} has ${tags.length} division tags`);
      assert.equal(tags[0].text, p.division, `${q}: ${p.slug}`);
      assert.ok(unesc(o.text).includes(display(p)), `${q}: ${p.slug} does not show ${display(p)}`);
      seen++;
    }
  }
  assert.ok(seen >= 30, `only ${seen} options checked`);
});

test('no match: the message is in #homeMsg and #homeStatus, never in the listbox', async () => {
  const pg = await home();
  await pg.focus(); await pg.type('zzzz');
  const list = listOf(pg), msg = msgOf(pg);
  assert.ok('hidden' in list.attrs && list.kids.length === 0, 'the listbox shows or holds something');
  assert.ok(!('hidden' in msg.attrs));
  const text = 'No program or upcoming ID camp matches “zzzz”. Try a school’s short name, a mascot, a state or a city.';
  assert.equal(unesc(msg.text), text);
  assert.equal(statusOf(pg), text);
  assert.equal(pg.box.getAttribute('aria-expanded'), 'false');
});

test('"stanford camps": the no-camp message sits before the listbox, next to the ID Camps section it describes; Enter opens Stanford', async () => {
  const pg = await home();
  await pg.focus(); await pg.type('stanford camps');
  const top = results(pg).kids.map(n => n.attrs.id);
  assert.deepEqual(top, ['homeMsg', 'homeList'], 'the message is not first when ID Camps leads');
  assert.equal(unesc(msgOf(pg).text), 'No upcoming ID camps match “stanford camps”.');
  const groups = listOf(pg).kids;
  assert.deepEqual(groups.map(g => g.kids[0].text), ['ID Camps · 0 upcoming', 'Programs · 1']);
  assert.deepEqual(groups[0].kids.slice(1).map(o => o.attrs['data-kind']), ['browse']);
  assert.match(statusOf(pg), /No upcoming ID camps match “stanford camps”\..*Enter opens Stanford\./);
  const e = pg.key('Enter');
  assert.ok(e.prevented);
  assert.equal(pg.sb.location.hash, '#/p/stanford');
  // and when Programs leads, the message comes after the list
  const pg2 = await home({ camps: 'fail' });
  await pg2.focus(); await pg2.type('unc');
  assert.deepEqual(results(pg2).kids.map(n => n.attrs.id), ['homeList', 'homeMsg']);
});

test('keys: arrows move and wrap across sections, Enter opens the active option, Escape closes then clears', async () => {
  const pg = await home();
  await pg.focus(); await pg.type('TX');
  const n = options(pg).length;
  assert.ok(n >= 6);
  pg.key('ArrowDown');
  assert.equal(pg.box.getAttribute('aria-activedescendant'), 'homeOpt-0');
  assert.equal(options(pg)[0].attrs['aria-selected'], 'true');
  pg.key('ArrowUp');
  assert.equal(pg.box.getAttribute('aria-activedescendant'), `homeOpt-${n - 1}`, 'Up from the first does not wrap to the last');
  pg.key('ArrowDown');
  assert.equal(pg.box.getAttribute('aria-activedescendant'), 'homeOpt-0', 'Down from the last does not wrap to the first');
  pg.key('ArrowDown');  // the second program row
  const second = options(pg)[1];
  pg.key('Enter');
  assert.equal(pg.sb.location.hash, `#/p/${second.attrs['data-slug']}`);
  // Enter with no active option: the engine's target (a place query opens the list)
  const pg2 = await home();
  await pg2.focus(); await pg2.type('TX');
  pg2.key('Enter');
  assert.equal(pg2.sb.location.hash, '#/programs?q=TX&sort=name');
  // Enter right after typing, before the 80 ms wait: the box's text, not the last search
  const pg3 = await home();
  await pg3.focus(); await pg3.type('stan');
  pg3.box.value = 'ucla id camp'; pg3.fire('input', { target: pg3.box });
  pg3.key('Enter');
  assert.equal(pg3.sb.location.hash, '#/p/ucla/camps');
  // Escape: close, then clear
  const pg4 = await home();
  await pg4.focus(); await pg4.type('unc');
  assert.ok(pg4.key('Escape').prevented);
  assert.equal(pg4.box.getAttribute('aria-expanded'), 'false');
  assert.equal(pg4.box.value, 'unc');
  pg4.key('Escape');
  assert.equal(pg4.box.value, '');
  await settle(120);
  assert.equal(statusOf(pg4), '');
  // Tab closes and lets focus move on
  const pg5 = await home();
  await pg5.focus(); await pg5.type('unc');
  assert.ok(!pg5.key('Tab').prevented);
  assert.equal(pg5.box.getAttribute('aria-expanded'), 'false');
});

test('a click on an option opens it; a press on the results keeps focus in the box', async () => {
  const pg = await home();
  await pg.focus(); await pg.type('usc camps');
  const md = { target: { closest: s => (s === '#homeResults' ? {} : null) }, prevented: false, preventDefault() { md.prevented = true; } };
  pg.fire('mousedown', md);
  assert.ok(md.prevented, 'a press on the results takes focus out of the box');
  const opts = options(pg);
  const i = opts.findIndex(o => o.attrs['data-kind'] === 'program');
  pg.fire('click', { target: { closest: s => (s === '#homeList [role="option"]' ? { dataset: { i: String(i) } } : null) } });
  assert.equal(pg.sb.location.hash, `#/p/${opts[i].attrs['data-slug']}`);
});

test('"Show all N camps" expands the section in place', async () => {
  const pg = await home();
  await pg.focus(); await pg.type('a');
  const camps = () => options(pg).filter(o => o.attrs['data-kind'] === 'camp').length;
  assert.equal(camps(), 4);
  const more = options(pg).find(o => o.attrs['data-kind'] === 'more');
  assert.equal(more.text, 'Show all 37 camps');
  const hash = pg.sb.location.hash;
  pg.fire('click', { target: { closest: s => (s === '#homeList [role="option"]' ? { dataset: { i: more.attrs['data-i'] } } : null) } });
  assert.equal(camps(), 37);
  assert.ok(!options(pg).some(o => o.attrs['data-kind'] === 'more'));
  assert.equal(pg.sb.location.hash, hash, 'expanding navigated');
});

test('camps still loading: Programs work, the message says so; camps that fail to load leave Programs working', async () => {
  const pg = await home({ camps: 'hang' });
  await pg.focus(); await pg.type('usc camps');
  assert.equal(unesc(msgOf(pg).text), 'Loading camps…');
  assert.ok(options(pg).some(o => o.attrs['data-slug'] === 'usc'), 'Programs wait for camps');
  const pg2 = await home({ camps: 'fail' });
  await pg2.focus(); await pg2.type('unc');
  assert.deepEqual(options(pg2).filter(o => o.attrs['data-kind'] === 'program').map(o => o.attrs['data-slug']), ['north-carolina', 'unc-wilmington', 'unc-greensboro', 'unc-asheville']);
  assert.equal(unesc(msgOf(pg2).text), 'ID camps couldn’t load.');
  assert.match(statusOf(pg2), /ID camps couldn’t load\./);
});

test('the box remembers nothing: no saved state written while typing, moving or choosing', async () => {
  const pg = await home();
  pg.writes.length = 0;
  await pg.focus();
  for (const q of ['ucla id camp', 'TX', 'zzzz', 'unc']) await pg.type(q);
  pg.key('ArrowDown'); pg.key('Escape'); pg.key('Escape');
  await pg.type('unc'); pg.key('ArrowDown'); pg.key('Enter');
  await settle(200);
  assert.deepEqual(pg.writes, [], 'Home wrote saved state');
});
