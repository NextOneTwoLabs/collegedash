import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { parseCss, decls } from './lib/css_cascade.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = fs.readFileSync(process.env.FILTERS_ARIA_TEST_HTML || path.join(PUBLIC, 'index.html'), 'utf8');
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
const fireResize = pg => (pg.winListeners.resize || []).forEach(fn => fn({ type: 'resize' }));
const fireMedia = pg => (pg.mqListeners['(max-width: 768px) change'] || []).forEach(fn => fn({ matches: false }));
const setWidth = (pg, w) => { pg.sb.innerWidth = w; fireMedia(pg); fireResize(pg); };  // a real viewport change fires both
const aria = pg => pg.$('#sidebarToggle').getAttribute('aria-expanded');
const sheetOpen = pg => pg.$('#sidebar').classList.contains('open');
// what is shown: on a phone the sheet (open or shut); past 768 px the rail (shown unless collapsed)
const shown = pg => String(pg.sb.innerWidth <= 768 ? sheetOpen(pg) : !pg.$('#layout').classList.contains('sidebar-collapsed'));

// phone -> wider than 768 px -> phone, with the drawer open or shut when the window widens, and the rail collapsed or not while wide
for (const drawer of ['shut', 'open']) for (const collapse of [false, true]) {
  test(`#485: phone -> wide -> phone, drawer ${drawer}${collapse ? ', rail collapsed while wide' : ''}: aria-expanded matches what is shown`, async () => {
    const pg = loadPage({ width: 390 }); await settle(300);
    const check = step => assert.equal(aria(pg), shown(pg), `${step}: aria-expanded="${aria(pg)}" but "${shown(pg)}" is shown (width ${pg.sb.innerWidth}, sheet open: ${sheetOpen(pg)})`);
    if (drawer === 'open') { pg.$('#sidebarToggle').onclick(); assert.ok(sheetOpen(pg), 'fixture: the Filters toggle did not open the sheet'); }
    if (drawer === 'open') check('phone, drawer open');  // the shut start is the load check below
    setWidth(pg, 900);
    check('widened past 768 px');
    if (collapse) { pg.$('#sidebarToggle').onclick(); check('rail collapsed while wide'); }
    setWidth(pg, 390);
    assert.ok(!sheetOpen(pg), 'no sheet is open after the round trip');
    check('narrowed to phone again');
  });
}

test('#485: loading at phone width with the drawer shut: aria-expanded is false; loading wide it is true', async () => {
  const phone = loadPage({ width: 390 }); await settle(300);
  assert.equal(aria(phone), 'false', 'phone, sheet shut');
  const wide = loadPage({ width: 1280 }); await settle(300);
  assert.equal(aria(wide), 'true', 'desktop, rail shown');
});
