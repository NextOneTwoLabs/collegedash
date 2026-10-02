// The one helper behind both phone filter sheets (#465: the plan Bianque approved on #465, with five conditions):
// Programs' rail sheet (#sidebar: openDrawer / closeDrawer) and ID Camps' sheet (#campsBar: campsSheet). These checks
// drive those existing functions, so they run on main too:
// - an element already inert for another reason stays inert when a sheet closes (the book-keeping) - fails on main,
//   where Programs' sheet released #main, the header and the bottom bar unconditionally;
// - Programs' sheet also ends on the phone breakpoint's media-query change (the addition the plan named) - fails on main,
//   where only resize ended it;
// - GUARD checks (pass on main by design): open twice and close once leaves nothing inert; widening ends each sheet with
//   its own focus rule, through resize and through the media query separately; every close returns focus to the opener.
//
//     node --test tests/phone_sheet.test.mjs
//
// PHONE_SHEET_TEST_HTML (optional) points at another copy of index.html, to show these checks failing on main.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { parseCss, decls } from './lib/css_cascade.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = fs.readFileSync(process.env.PHONE_SHEET_TEST_HTML || path.join(PUBLIC, 'index.html'), 'utf8');
const CSS = parseCss([...HTML.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n'));
const decl = (at, sel, prop) => CSS.filter(r => r.at.join(' ') === at && r.selectors.includes(sel)).flatMap(r => decls(r.body)).filter(d => d.prop === prop).map(d => d.value).pop();
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const unesc = s => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const camel = s => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const decodeId = id => decodeURIComponent(id.replace(/^mfConf-/, '').replace(/_/g, '%'));

function loadPage({ hash = '#/programs', width = 1280, store = {} } = {}) {
  const FOCUS = { el: null, log: [] };
  const els = new Map(), docListeners = {}, winListeners = {}, mqListeners = {};
  const ls = new Map(Object.entries(store).map(([k, v]) => [k, JSON.stringify(v)]));
  function makeEl(name, tagAttrs = null) {
    const listeners = {}, classes = new Set(), attrs = new Map(tagAttrs ? Object.entries(tagAttrs) : []);
    if (attrs.has('class')) attrs.get('class').split(/\s+/).filter(Boolean).forEach(c => classes.add(c));
    let html = '', nodes = null;
    const dataset = {};
    for (const [k, v] of attrs) if (k.startsWith('data-')) dataset[camel(k.slice(5))] = v;
    const parse = () => {  // one node per start tag, kept until the element is redrawn
      if (nodes) return nodes;
      nodes = [...html.matchAll(/<([a-z][\w-]*)((?:\s+[\w-]+(?:="[^"]*")?)*)\s*\/?>/gi)].map((m, i) => {
        const a = Object.fromEntries([...m[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)].map(x => [x[1], unesc(x[2] ?? '')]));
        const n = makeEl(`${name} > ${m[1]}${a.id ? '#' + a.id : ''}${Object.entries(a).filter(([k]) => k.startsWith('data-')).map(([k, v]) => `[${k}="${v}"]`).join('')}`, a);
        n._tag = m[1].toLowerCase();
        return n;
      });
      return nodes;
    };
    const matchOne = (n, compound) => {
      const tag = /^[a-z][\w-]*/i.exec(compound)?.[0];
      if (tag && n._tag !== tag.toLowerCase()) return false;
      for (const m of compound.matchAll(/\.([\w-]+)/g)) if (!n.classList.contains(m[1])) return false;
      for (const m of compound.matchAll(/#([\w-]+)/g)) if (n.getAttribute('id') !== m[1]) return false;
      for (const m of compound.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)) { const v = n.getAttribute(m[1]); if (v == null || (m[2] !== undefined && v !== m[2])) return false; }
      return true;
    };
    const select = sel => sel.split(',').map(s => s.trim()).flatMap(s => { const last = s.split(/\s+/).pop(); return parse().filter(n => matchOne(n, last)); });
    const el = {
      _name: name, _listeners: listeners, _attrs: attrs, textContent: '', value: attrs.get('value') ?? '', title: '', scrollTop: 0, inert: false,
      hidden: attrs.has('hidden'), dataset, style: {}, placeholder: '', onclick: null,
      get innerHTML() { return html; }, set innerHTML(v) { html = String(v); nodes = null; },
      setAttribute: (k, v) => { attrs.set(k, String(v)); FOCUS.log.push(['set', name, k, String(v)]); },
      getAttribute: k => (attrs.has(k) ? attrs.get(k) : null),
      removeAttribute: k => { attrs.delete(k); FOCUS.log.push(['remove', name, k]); },
      classList: { add: (...c) => c.forEach(x => classes.add(x)), remove: (...c) => c.forEach(x => classes.delete(x)), contains: c => classes.has(c),
        toggle: (c, f) => { const on = f === undefined ? !classes.has(c) : !!f; on ? classes.add(c) : classes.delete(c); return on; } },
      addEventListener(type, fn) { (listeners[type] ||= []).push(fn); }, removeEventListener() { },
      // an element the page never drew into (static markup this stub does not model, such as the feedback form) answers
      // with a stand-in; one the page drew answers from what it drew, so a miss there is a real null
      querySelector: sel => (/^#[\w-]+$/.test(sel) ? bySelector(sel) : select(sel)[0] || (html ? null : bySelector(`${name} ${sel}`))),
      querySelectorAll: sel => (/^#[\w-]+$/.test(sel) ? [bySelector(sel)] : select(sel)),
      closest: () => null, matches: () => false, contains: () => false,
      focus() { FOCUS.el = name; }, blur() { },
    };
    return el;
  }
  const bySelector = sel => {
    if (!els.has(sel)) {
      // the static markup's attributes for an #id, so a pinned element starts as the page ships it
      const m = /^#([\w-]+)$/.exec(sel), tag = m && new RegExp(`<[a-z]+[^>]*\\sid="${m[1]}"[^>]*>`).exec(HTML)?.[0];
      const a = tag ? Object.fromEntries([...tag.matchAll(/([\w-]+)(?:="([^"]*)")?/g)].slice(1).map(x => [x[1], x[2] ?? ''])) : null;
      els.set(sel, makeEl(sel, a));
    }
    return els.get(sel);
  };
  const readPublic = url => {
    let rel = String(url).replace(/^\//, '').replace(/\?.*$/, '');
    if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
    const p = path.join(PUBLIC, rel);
    return p.startsWith(PUBLIC) && fs.existsSync(p) && fs.statSync(p).isFile() ? fs.readFileSync(p, 'utf8') : null;
  };
  const fire = type => (winListeners[type] || []).forEach(fn => fn({ type }));
  const hist = { entries: [hash], at: 0, pushes: 0 };
  const body = makeEl('body'), header = makeEl('.header'), bar = makeEl('.bottom-nav');
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl, Error,
    isNaN, parseInt, parseFloat, URL, URLSearchParams, encodeURIComponent, decodeURIComponent,
    document: {
      documentElement: makeEl('html'), body, activeElement: null, title: '',
      querySelector: sel => (sel === '.header' ? header : sel === '.bottom-nav' ? bar : bySelector(sel)), createElement: makeEl,
      querySelectorAll: () => [], addEventListener(type, fn) { (docListeners[type] ||= []).push(fn); },
    },
    location: {
      search: '', href: 'http://localhost/',
      get hash() { return hist.entries[hist.at]; },
      set hash(h) { const v = h.startsWith('#') ? h : `#${h}`; if (v === hist.entries[hist.at]) return; hist.entries.splice(hist.at + 1); hist.entries.push(v); hist.at++; setTimeout(() => fire('hashchange'), 0); },
      replace(h) { hist.entries[hist.at] = h; setTimeout(() => fire('hashchange'), 0); },
    },
    history: {
      pushState(_, __, u) { hist.entries.splice(hist.at + 1); hist.entries.push(String(u)); hist.at++; hist.pushes++; },
      replaceState(_, __, u) { hist.entries[hist.at] = String(u); },
    },
    matchMedia: q => ({ matches: false, addEventListener(t, fn) { (mqListeners[`${q} ${t}`] ||= []).push(fn); } }), innerWidth: width, screen: { width, height: 800 }, navigator: {},
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
  const names = ['S', 'route', 'openDrawer', 'closeDrawer', 'campsSheet'];
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(names)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, $: bySelector, body, header, bar, hist, FOCUS, docListeners, winListeners, mqListeners };
}
const settle = (ms = 80) => new Promise(r => setTimeout(r, ms));
async function open(opts) { const pg = loadPage(opts); await settle(300); return pg; }

// index.html's body for the camps walk: body > [header, bottom bar, layout > [rail, #main > #app > content > [camps
// layout > [#campsBar, #campsMain], backdrop]]], as camps_page builds it.
function tree(pg) {
  const kids = (parent, children) => { parent.children = children; for (const c of children) c.parentElement = parent; };
  const $ = pg.$, layout = $('#layout'), content = $('.content-body'), campsLayout = $('.camps-layout');
  kids(pg.body, [pg.header, pg.bar, layout]);
  kids(layout, [$('#sidebar'), $('#main')]);
  kids($('#main'), [$('#app')]);
  kids($('#app'), [content]);
  kids(content, [campsLayout, $('#campsBackdrop')]);
  kids(campsLayout, [$('#campsBar'), $('#campsMain')]);
  const all = { header: pg.header, bar: pg.bar, main: $('#main'), sidebar: $('#sidebar'), layout, content, campsMain: $('#campsMain'), campsBar: $('#campsBar'), back: $('#campsBackdrop') };
  for (const e of Object.values(all)) e.inert = false;
  return all;
}
const inertOf = all => Object.fromEntries(Object.entries(all).map(([k, e]) => [k, !!e.inert]));
const none = all => Object.fromEntries(Object.keys(all).map(k => [k, false]));
const fireResize = pg => (pg.winListeners.resize || []).forEach(fn => fn({ type: 'resize' }));
const fireMedia = pg => (pg.mqListeners['(max-width: 768px) change'] || []).forEach(fn => fn({ matches: false }));

test('an element already inert for another reason stays inert when either sheet closes; only what the sheet set is released', async () => {
  for (const [what, openIt, closeIt] of [
    ['Programs', pg => pg.sb.openDrawer(), pg => pg.sb.closeDrawer({ focus: true })],
    ['ID Camps', pg => pg.sb.campsSheet(true), pg => pg.sb.campsSheet(false)]]) {
    const pg = await open({ width: 390 });
    const all = tree(pg);
    all.header.inert = true;  // made inert by something else first (the #400 sheet does exactly this)
    openIt(pg);
    assert.ok(Object.entries(inertOf(all)).some(([k, v]) => v && k !== 'header'), `${what}: fixture - the sheet made nothing inert`);
    closeIt(pg);
    assert.equal(all.header.inert, true, `${what}: closing released an element it never made inert`);
    assert.deepEqual(inertOf(all), { ...none(all), header: true }, `${what}: closing left something it set inert`);
  }
});

test('GUARD: opening twice and closing once leaves nothing inert, for both sheets', async () => {
  for (const [what, openIt, closeIt] of [
    ['Programs', pg => pg.sb.openDrawer(), pg => pg.sb.closeDrawer()],
    ['ID Camps', pg => pg.sb.campsSheet(true), pg => pg.sb.campsSheet(false)]]) {
    const pg = await open({ width: 390 });
    const all = tree(pg);
    openIt(pg); openIt(pg);
    closeIt(pg);
    assert.deepEqual(inertOf(all), none(all), `${what}: something is still inert`);
  }
});

test('GUARD: widening past 768 px ends each sheet with its own focus rule - through resize, and through the media query', async () => {
  for (const [signal, fire] of [['resize', fireResize], ['the media query', fireMedia]]) {
    // ID Camps: focus stays where it is (inside the sheet it is now in the visible sidebar)
    const pg = await open({ width: 390 });
    const all = tree(pg);
    pg.sb.campsSheet(true);
    assert.equal(pg.FOCUS.el, '#campsSideTitle', 'fixture: the camps sheet did not take focus');
    pg.sb.innerWidth = 900; fire(pg);
    assert.ok(!pg.$('#campsBar').classList.contains('open'), `${signal}: the camps sheet is still open`);
    assert.deepEqual(inertOf(all), none(all), `${signal}: the camps sheet left something inert`);
    assert.equal(pg.FOCUS.el, '#campsSideTitle', `${signal}: camps focus moved to ${pg.FOCUS.el}`);
    assert.equal(pg.$('#campsMoreBtn').getAttribute('aria-expanded'), 'false', `${signal}: the camps opener still says expanded`);
  }
  // Programs, through resize (its signal on main): focus to the opener, which says the desktop rail is shown (#476)
  const pg = await open({ width: 390 });
  const all = tree(pg);
  pg.sb.openDrawer();
  pg.sb.innerWidth = 900; fireResize(pg);
  assert.ok(!pg.$('#sidebar').classList.contains('open'), 'resize: the Programs sheet is still open');
  assert.deepEqual(inertOf(all), none(all), 'resize: the Programs sheet left something inert');
  assert.equal(pg.FOCUS.el, '#sidebarToggle');
  assert.equal(pg.$('#sidebarToggle').getAttribute('aria-expanded'), 'true', 'the opener does not say the desktop rail is shown');
});

test('Programs\' sheet also ends on the media-query change alone (the plan\'s addition), focus and aria-expanded as on resize', async () => {
  const pg = await open({ width: 390 });
  const all = tree(pg);
  pg.sb.openDrawer();
  assert.equal(all.main.inert, true, 'fixture: the Programs sheet is not modal');
  pg.sb.innerWidth = 900; fireMedia(pg);
  assert.ok(!pg.$('#sidebar').classList.contains('open'), 'the media query did not end the Programs sheet');
  assert.deepEqual(inertOf(all), none(all));
  assert.ok(!pg.body.classList.contains('sheet-open'), 'still drawn above the header');
  assert.equal(pg.FOCUS.el, '#sidebarToggle');
  assert.equal(pg.$('#sidebarToggle').getAttribute('aria-expanded'), 'true');
});

test('GUARD: closing returns focus to each sheet\'s own opener', async () => {
  const pg = await open({ width: 390 });
  tree(pg);
  pg.sb.openDrawer(); pg.sb.closeDrawer({ focus: true });
  assert.equal(pg.FOCUS.el, '#sidebarToggle', 'Programs');
  pg.sb.campsSheet(true); pg.sb.campsSheet(false);
  assert.equal(pg.FOCUS.el, '#campsMoreBtn', 'ID Camps');
});
