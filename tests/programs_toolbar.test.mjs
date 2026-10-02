// Programs' toolbar, More filters and the Conference control (#465 PR D), as planned on #465 and per the ARIA note
// Huatuo approved there with four conditions (VoiceOver re-point, no-match outside the listbox, stable reversible ids,
// the sheet's inert page and the desktop panel as a non-modal disclosure).
//
//     node --test tests/programs_toolbar.test.mjs
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM that is real enough to click: an element's
// querySelector / querySelectorAll read the HTML the page drew into it (tags, classes, data-* and other attributes) and
// return the same node object for the same element until it is redrawn, so the page's own handlers are what the tests
// press; focus(), inert and attribute writes are recorded; history has real entries.
//
// PROGRAMS_TOOLBAR_TEST_HTML (optional) points at another copy of index.html, to show these checks failing on main.
//
// What it CANNOT prove, and a human must check with a screen reader (NVDA, JAWS, VoiceOver): what is announced when an
// option's selection flips, and the re-point fallback; and on a real phone, the sheet and the keyboard.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = fs.readFileSync(process.env.PROGRAMS_TOOLBAR_TEST_HTML || path.join(PUBLIC, 'index.html'), 'utf8');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const unesc = s => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const camel = s => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const decodeId = id => decodeURIComponent(id.replace(/^mfConf-/, '').replace(/_/g, '%'));

function loadPage({ hash = '#/programs', width = 1280, store = {} } = {}) {
  const FOCUS = { el: null, log: [] };
  const els = new Map(), docListeners = {}, winListeners = {};
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
    matchMedia: () => ({ matches: false }), innerWidth: width, screen: { width, height: 800 }, navigator: {},
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
  const names = ['S', 'route', 'renderList', 'renderSidebar', 'confPillName', 'confOptId', 'confOptKey'];
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(names)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, $: bySelector, body, header, bar, hist, FOCUS, docListeners };
}
const settle = (ms = 80) => new Promise(r => setTimeout(r, ms));
async function open(opts) { const pg = loadPage(opts); await settle(300); return pg; }
const key = (pg, k, extra = {}) => { const ev = { key: k, preventDefault() { ev.prevented = true; }, stopPropagation() { ev.stopped = true; }, ...extra }; (pg.$('#mfConfInput')._listeners.keydown || []).forEach(fn => fn(ev)); return ev; };
const typeConf = (pg, text) => { const box = pg.$('#mfConfInput'); box.value = text; (box._listeners.input || []).forEach(fn => fn({ target: box })); };
const options = pg => [...pg.$('#mfConfList').innerHTML.matchAll(/<div role="option" id="([^"]+)" class="([^"]*)" aria-selected="(true|false)" data-i="(\d+)" aria-label="([^"]*)"/g)]
  .map(m => ({ id: m[1], cls: m[2], selected: m[3] === 'true', i: Number(m[4]), name: unesc(m[5]), key: decodeId(m[1]) }));
const option = (pg, k) => options(pg).find(o => o.key === k);

// ---------- the toolbar and the panel ----------

test('Programs: the toolbar holds Division, Region, More filters, the count and Sort; the sidebar is the More filters panel', async () => {
  const pg = await open();
  const app = pg.$('#app').innerHTML, side = pg.$('#sidebar').innerHTML;
  const bar = /<div class="ptoolbar" role="group" aria-label="Filter and sort programs">([\s\S]*?)<\/div>(?:<div class="pchips"|<div class="ask|<div class="recs|<div class="grid|<div class="flight)/.exec(app)?.[1] || '';
  assert.ok(bar, 'no toolbar above the results');
  assert.match(bar, /role="group" aria-label="Division"/); assert.match(bar, /role="group" aria-label="Region"/);
  assert.match(bar, /<button type="button" class="btn more-btn" id="moreFilters" aria-expanded="false" aria-controls="sidebar">More filters<\/button>/);
  assert.match(bar, new RegExp(`<span class="pt-count" id="ptCount">${INDEX.programs.length.toLocaleString('en-US')} programs</span>`));
  assert.match(bar, /<label class="sr-only" for="sortSelect">Sort<\/label><select class="season-select" id="sortSelect">/);
  assert.match(side, /<h2 id="mfHeading" tabindex="-1">More filters<\/h2>/);
  assert.ok(!/sidebar-tab|id="sortSelect"|data-division=|data-region=|class="pill[^"]*" data-conf=/.test(side), 'the panel repeats a toolbar control, a tab or the conference pills');
  assert.match(side, /id="condAdd"/, 'conditions left More filters'); assert.match(side, /aria-label="Highlight class"/, 'Highlight class left More filters');
  assert.equal(pg.$('#sidebar').getAttribute('aria-label'), 'More filters');
  assert.ok(pg.body.classList.contains('rail-panel'));
  assert.equal((app + side).match(/id="sortSelect"/g)?.length, 1, 'two sort selects');
});

test('other pages keep the Browse rail exactly (tabs, sort, pills); More filters belongs to Programs', async () => {
  const pg = await open({ hash: '#/faq' });
  const side = pg.$('#sidebar').innerHTML;
  assert.match(side, /data-tab="programs">Browse<\/button>/); assert.match(side, /id="sortSelect"/); assert.match(side, /data-region="West"/);
  assert.ok(!/mfHeading|mfConfInput/.test(side));
  assert.ok(!pg.body.classList.contains('rail-panel'));
});

test('desktop: More filters is a non-modal disclosure - aria-expanded, focus in on open, Escape or ✕ closes and focus returns', async () => {
  const pg = await open();
  pg.$('#moreFilters').onclick();
  assert.ok(pg.body.classList.contains('more-open'), 'the panel did not open');
  assert.equal(pg.$('#moreFilters').getAttribute('aria-expanded'), 'true');
  assert.equal(pg.FOCUS.el, '#mfHeading', 'focus did not move into the panel');
  assert.equal(pg.$('#sidebar').getAttribute('aria-modal'), null, 'the desktop panel is modal');
  const ev = { key: 'Escape', defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  pg.$('#sidebar')._listeners.keydown.forEach(fn => fn(ev));
  assert.ok(!pg.body.classList.contains('more-open'), 'Escape did not close it');
  assert.equal(pg.$('#moreFilters').getAttribute('aria-expanded'), 'false');
  assert.equal(pg.FOCUS.el, '#moreFilters', 'focus did not return to the button');
  pg.$('#moreFilters').onclick(); pg.$('#mfClose').onclick();
  assert.ok(!pg.body.classList.contains('more-open') && pg.FOCUS.el === '#moreFilters', '✕ did not close it and return focus');
  pg.$('#moreFilters').onclick();
  pg.sb.location.hash = '#/faq'; await settle(200);
  assert.ok(!pg.body.classList.contains('more-open'), 'leaving Programs left the panel open');
});

test('phones: More filters is a modal sheet - aria-modal, and the page, header and bottom bar inert until it closes', async () => {
  const pg = await open({ width: 375 });
  pg.$('#moreFilters').onclick();
  const sb = pg.$('#sidebar');
  assert.ok(sb.classList.contains('open'));
  assert.equal(sb.getAttribute('role'), 'dialog'); assert.equal(sb.getAttribute('aria-modal'), 'true'); assert.equal(sb.getAttribute('aria-labelledby'), 'mfHeading');
  assert.deepEqual([pg.$('#main').inert, pg.header.inert, pg.bar.inert], [true, true, true], 'something behind the sheet is reachable');
  assert.equal(pg.FOCUS.el, '#mfHeading');
  pg.$('#sidebarOverlay').onclick();
  assert.ok(!sb.classList.contains('open'), 'the overlay did not close it');
  assert.deepEqual([pg.$('#main').inert, pg.header.inert, pg.bar.inert], [false, false, false], 'the page stayed inert');
  assert.equal(sb.getAttribute('aria-modal'), null); assert.equal(pg.FOCUS.el, '#moreFilters');
  assert.match(HTML, /for \(const sel of \['#main', '#sidebar', '\.header', '\.bottom-nav'\]\)/, 'the #400 sheet leaves the bottom bar reachable');
});

test('phones: a pick inside the sheet keeps it open (class pill, condition added or removed); other pages\' drawer still closes', async () => {
  // Huatuo on #472: the sheet closes only on Show N, its ✕, Escape (or the overlay), as a conference toggle already did
  const pg = await open({ width: 375 });
  const sb = pg.$('#sidebar');
  const stillOpen = what => {
    assert.ok(sb.classList.contains('open'), `${what} closed the sheet`);
    assert.equal(sb.getAttribute('aria-modal'), 'true', `${what} dropped aria-modal`);
    assert.deepEqual([pg.$('#main').inert, pg.header.inert, pg.bar.inert], [true, true, true], `${what} un-inerted the page`);
  };
  pg.$('#moreFilters').onclick();
  const year = /data-class="(\d{4})"/.exec(sb.innerHTML)?.[1];
  assert.ok(year, 'no Highlight class pill in the sheet');
  sb.querySelector(`[data-class="${year}"]`).onclick(); await settle(150);
  assert.deepEqual([...pg.sb.S.filters.classYear], [year]);
  stillOpen('a Highlight class pill');
  assert.equal(pg.FOCUS.el, `#sidebar > button[data-class="${year}"]`, `focus did not stay on the pill: ${pg.FOCUS.el}`);
  pg.$('#condAdd').onclick();
  pg.$('#condValue').value = '50';
  pg.$('#condForm').onsubmit({ preventDefault() { } }); await settle(150);
  assert.equal(pg.sb.S.filters.cond.length, 1, 'the condition was not added');
  stillOpen('adding a condition');
  assert.equal(pg.FOCUS.el, '#condAdd');
  sb.querySelector('[data-cond-rm="0"]').onclick(); await settle(150);
  assert.equal(pg.sb.S.filters.cond.length, 0, 'the condition was not removed');
  stillOpen('removing a condition');
  pg.$('#showResults').onclick();
  assert.ok(!sb.classList.contains('open'), 'Show N did not close the sheet');
  assert.deepEqual([pg.$('#main').inert, pg.header.inert, pg.bar.inert], [false, false, false]);
  assert.equal(pg.FOCUS.el, '#moreFilters');

  const other = await open({ hash: '#/faq', width: 375 });
  const osb = other.$('#sidebar');
  other.$('#sidebarToggle').onclick();
  assert.ok(osb.classList.contains('open'));
  const y = /data-class="(\d{4})"/.exec(osb.innerHTML)?.[1];
  osb.querySelector(`[data-class="${y}"]`).onclick(); await settle(150);
  assert.ok(!osb.classList.contains('open'), 'off Programs a pill no longer closes the drawer');
  assert.equal(other.FOCUS.el, '#sidebarToggle');
});

test('the toolbar\'s pills commit once and put focus back on the same pill after the list redraws', async () => {
  const pg = await open();
  const before = pg.hist.pushes;
  pg.$('#app').querySelector('[data-division="D1"]').onclick(); await settle(150);
  assert.deepEqual([...pg.sb.S.filters.division], ['D1']);
  assert.equal(pg.hist.pushes - before, 1, 'not one history entry');
  assert.match(pg.FOCUS.el, /\[data-division="D1"\]/, `focus went to ${pg.FOCUS.el}`);
  pg.$('#app').querySelector('[data-region="West"]').onclick(); await settle(150);
  assert.deepEqual([...pg.sb.S.filters.region], ['West']);
  assert.match(pg.FOCUS.el, /\[data-region="West"\]/);
  assert.equal(pg.sb.location.hash, '#/programs?div=D1&region=West&sort=name');
});

test('chips: what More filters holds shows under the toolbar; a removed chip hands focus on; no raw conference key', async () => {
  const pg = await open({ store: { 'cd.filters': { conf: ['D2|Independent', 'D1|ACC'], classYear: ['2027'], cond: [{ field: 'admissionRate', op: '<', value: 0.3 }] } } });
  const app = pg.$('#app').innerHTML;
  const labels = [...app.matchAll(/<span class="pchip">([^<]*)<button type="button" data-chip-(\w+)="(\d+|\d{4})" aria-label="Remove ([^"]*)">/g)].map(m => unesc(m[1]));
  assert.deepEqual(labels.slice(0, 2), ['Independent (D2)', 'ACC']);
  assert.ok(labels.includes('Class of 2027 highlighted') && labels.some(l => /Admission/.test(l)), JSON.stringify(labels));
  assert.match(app, /More filters<span class="nav-count">4<\/span>/, 'the button does not count what is on');
  assert.ok(!app.includes('D2|Independent'), 'a raw key reached the page (#431)');
  pg.$('#app').querySelector('[data-chip-conf="0"]').onclick(); await settle(150);
  assert.deepEqual([...pg.sb.S.filters.conf], ['D1|ACC']);
  assert.match(pg.FOCUS.el, /data-chip-conf="0"/, `focus did not go to the next chip (ACC, now first): ${pg.FOCUS.el}`);
  pg.$('#app').querySelector('#chipsClear').onclick(); await settle(150);
  assert.deepEqual([[...pg.sb.S.filters.conf], [...pg.sb.S.filters.classYear], [...pg.sb.S.filters.cond]], [[], [], []]);
  assert.equal(pg.FOCUS.el, '#moreFilters');
});

// ---------- the Conference control ----------

test('Conference: a combobox owning a multi-select listbox, one labelled group per division, options named as #444\'s pills', async () => {
  const pg = await open();
  const box = pg.$('#mfConfInput'), side = pg.$('#sidebar').innerHTML;
  assert.match(side, /<label class="mf-conf-label" for="mfConfInput">Find a conference<\/label>/);
  for (const [k, v] of [['role', 'combobox'], ['aria-autocomplete', 'list'], ['aria-controls', 'mfConfList'], ['aria-expanded', 'false'], ['aria-describedby', 'mfConfHint']])
    assert.equal(box.getAttribute(k), v, `the box's ${k}`);
  assert.match(side, /<div class="mf-conf-list" id="mfConfList" role="listbox" aria-multiselectable="true" aria-label="Conferences" hidden><\/div>/);
  key(pg, 'ArrowDown');
  const list = pg.$('#mfConfList').innerHTML;
  assert.deepEqual([...list.matchAll(/<div role="group" aria-label="([^"]+)">/g)].map(m => m[1]), ['Division I', 'Division II', 'Division III']);
  const counts = new Map(); for (const p of INDEX.programs) counts.set(`${p.division}|${p.conference}`, (counts.get(`${p.division}|${p.conference}`) || 0) + 1);
  const ind = option(pg, 'D2|Independent'), acc = option(pg, 'D1|ACC');
  assert.equal(ind.name, `Independent (D2), ${counts.get('D2|Independent')} program${counts.get('D2|Independent') === 1 ? '' : 's'}`);
  assert.equal(acc.name, `ACC, ${counts.get('D1|ACC')} programs`);
  assert.equal(acc.name, pg.sb.confPillName('D1', 'ACC', counts.get('D1|ACC')), 'not #444\'s name');
  assert.ok(!/role="option"[^>]*>[^<]*<p|mf-nomatch/.test(list), 'something other than groups and options in the listbox');
});

test('option ids: unique, stable across a redraw, and a reversible encoding of the keyed value (Huatuo, condition 3)', async () => {
  const pg = await open();
  key(pg, 'ArrowDown');
  const all = options(pg);
  assert.equal(new Set(all.map(o => o.id)).size, all.length, 'two options share an id');
  assert.ok(all.every(o => /^mfConf-[A-Za-z0-9_]+$/.test(o.id)), 'an id with a character outside [A-Za-z0-9_]');
  for (const k of ['D3|College Conference of Illinois & Wisconsin', 'D1|Big Ten', 'D2|Independent', 'x_y.z-(a)!*~\'%|é'])
    assert.equal(pg.sb.confOptKey(pg.sb.confOptId(k)), k, `${k} does not round-trip`);
  assert.notEqual(pg.sb.confOptId('D1|A_B'), pg.sb.confOptId('D1|A%5FB'), 'punctuation-only differences collide');
  const before = option(pg, 'D1|ACC').id;
  key(pg, 'Enter'); await settle(30);
  assert.equal(option(pg, 'D1|ACC').id, before, 'the id changed on a redraw');
});

test('keys: Down/Up open and move (wrapping); Enter toggles, stays open, keeps focus, one entry; the active option is re-pointed', async () => {
  const pg = await open();
  const box = pg.$('#mfConfInput'), before = pg.hist.pushes;
  key(pg, 'ArrowDown');
  const first = options(pg)[0];
  assert.equal(box.getAttribute('aria-expanded'), 'true'); assert.equal(box.getAttribute('aria-activedescendant'), first.id);
  key(pg, 'ArrowUp');
  assert.equal(box.getAttribute('aria-activedescendant'), options(pg).at(-1).id, 'Up from the first did not wrap to the last');
  key(pg, 'ArrowDown');
  assert.equal(box.getAttribute('aria-activedescendant'), first.id, 'Down from the last did not wrap to the first');
  pg.FOCUS.el = 'unchanged'; pg.FOCUS.log.length = 0;
  const ev = key(pg, 'Enter');
  assert.ok(ev.prevented);
  assert.deepEqual([...pg.sb.S.filters.conf], [first.key], 'Enter did not add the active conference');
  assert.equal(option(pg, first.key).selected, true);
  assert.equal(box.getAttribute('aria-expanded'), 'true', 'the list closed on a toggle');
  assert.equal(pg.FOCUS.el, 'unchanged', 'a toggle moved focus');
  const cleared = pg.FOCUS.log.findIndex(l => l[0] === 'remove' && l[1] === '#mfConfInput' && l[2] === 'aria-activedescendant');
  assert.ok(cleared >= 0, 'the active descendant was not cleared');
  await settle(20);
  assert.equal(box.getAttribute('aria-activedescendant'), first.id, 'the active descendant was not set again (condition 1)');
  await settle(120);
  assert.equal(pg.hist.pushes - before, 1, 'a toggle is not exactly one history entry');
  key(pg, 'Enter'); await settle(120);
  assert.deepEqual([...pg.sb.S.filters.conf], [], 'Enter again did not remove it');
  const sp = key(pg, ' ');
  assert.ok(!sp.prevented && !pg.sb.S.filters.conf.length, 'Space toggled (it must type)');
});

test('keys: Escape closes, then clears; Tab closes; Backspace in an empty box moves to the last chip and removes nothing', async () => {
  const pg = await open({ store: { 'cd.filters': { conf: ['D1|ACC', 'D1|Big Ten'] } } });
  const box = pg.$('#mfConfInput');
  typeConf(pg, 'big');
  assert.equal(box.getAttribute('aria-expanded'), 'true');
  let ev = key(pg, 'Escape');
  assert.ok(ev.stopped, 'the first Escape also closed the panel');
  assert.equal(box.getAttribute('aria-expanded'), 'false');
  ev = key(pg, 'Escape');
  assert.ok(ev.stopped && box.value === '', 'the second Escape did not clear the text');
  ev = key(pg, 'Escape');
  assert.ok(!ev.stopped, 'Escape on an empty, closed box should reach the panel and close it');
  key(pg, 'ArrowDown'); key(pg, 'Tab');
  assert.equal(box.getAttribute('aria-expanded'), 'false', 'Tab left the list open');
  box.value = '';
  ev = key(pg, 'Backspace');
  assert.ok(ev.prevented);
  assert.match(pg.FOCUS.el, /data-conf-chip="1"/, `focus did not go to the last chip: ${pg.FOCUS.el}`);
  assert.deepEqual([...pg.sb.S.filters.conf], ['D1|ACC', 'D1|Big Ten'], 'Backspace removed a chip');
});

test('typing narrows the list; no match is a plain line OUTSIDE the listbox, which is then empty and collapsed (condition 2)', async () => {
  const pg = await open();
  typeConf(pg, 'big');
  const names = options(pg).map(o => o.key);
  assert.ok(names.length > 1 && names.every(k => /big/i.test(k)), JSON.stringify(names));
  typeConf(pg, 'zzzz');
  assert.equal(options(pg).length, 0);
  assert.equal(pg.$('#mfConfList').hidden, true); assert.equal(pg.$('#mfConfInput').getAttribute('aria-expanded'), 'false');
  assert.equal(pg.$('#mfConfNone').hidden, false); assert.equal(pg.$('#mfConfNone').textContent, 'No conference matches “zzzz”');
  assert.match(pg.$('#sidebar').innerHTML, /id="mfConfList" role="listbox"[^>]*><\/div>\s*<p class="mf-nomatch" id="mfConfNone" hidden><\/p>/, 'the no-match line is not a sibling after the (closed) listbox');
  assert.ok(!/mfConfNone|No conference/.test(pg.$('#mfConfList').innerHTML), 'the no-match line is inside the listbox');
});

test('#425: a bare saved name is one chip, lights every option it covers, and expands only through toggleConf', async () => {
  const pg = await open({ store: { 'cd.filters': { conf: ['Independent'] } } });
  assert.match(pg.$('#mfConfChips').innerHTML, /aria-label="Remove Independent">Independent/);
  key(pg, 'ArrowDown');
  const inds = options(pg).filter(o => o.key.endsWith('|Independent'));
  assert.ok(inds.length > 1 && inds.every(o => o.selected), 'the bare name does not light every Independent');
  const d2 = option(pg, 'D2|Independent');
  for (const fn of pg.$('#mfConfList')._listeners.click) fn({ target: { closest: () => ({ dataset: { i: String(d2.i) } }) } });
  await settle(120);
  assert.deepEqual([...pg.sb.S.filters.conf].sort(), inds.map(o => o.key).filter(k => k !== 'D2|Independent').sort(), 'not toggleConf\'s expansion');
  const md = { prevented: false, preventDefault() { this.prevented = true; } };
  pg.$('#mfConfList')._listeners.mousedown.forEach(fn => fn(md));
  assert.ok(md.prevented, 'pressing an option takes focus from the box');
});

test('a division change prunes the selection; chip removal hands focus to the next chip, else the previous, else the box', async () => {
  const pg = await open({ store: { 'cd.filters': { conf: ['D1|ACC', 'D1|Big Ten', 'D1|SEC'] } } });
  const chip = i => ({ el: pg.$('#mfConfChips').querySelector(`[data-conf-chip="${i}"]`) });
  chip(1).el.onclick(); await settle(150);
  assert.deepEqual([...pg.sb.S.filters.conf], ['D1|ACC', 'D1|SEC']);
  assert.match(pg.FOCUS.el, /data-conf-chip="1"/, `not the next chip: ${pg.FOCUS.el}`);
  chip(1).el.onclick(); await settle(150);
  assert.match(pg.FOCUS.el, /data-conf-chip="0"/, `not the previous chip: ${pg.FOCUS.el}`);
  chip(0).el.onclick(); await settle(150);
  assert.equal(pg.FOCUS.el, '#mfConfInput', 'not the box when no chip is left');
  pg.sb.S.filters.conf = ['D1|ACC']; pg.sb.renderSidebar(); await pg.sb.renderList();
  pg.$('#app').querySelector('[data-division="D2"]').onclick(); await settle(150);
  assert.deepEqual([...pg.sb.S.filters.conf], [], 'a D1 conference survived choosing D2');
  assert.equal(pg.$('#mfConfChips').hidden, true);
});

test('#14: a conference picked in the control writes the same address a pill did; no new live region', async () => {
  const pg = await open();
  key(pg, 'ArrowDown');
  const acc = option(pg, 'D1|ACC');
  for (const fn of pg.$('#mfConfList')._listeners.click) fn({ target: { closest: () => ({ dataset: { i: String(acc.i) } }) } });
  await settle(150);
  assert.equal(pg.sb.location.hash, '#/programs?conf=D1:ACC&sort=name');
  const ids = [...HTML.matchAll(/<[^<>]*aria-live="(polite|assertive)"[^<>]*>/g)].map(m => (/id="([\w-]+)"/.exec(m[0]) || [])[1]).sort();
  assert.deepEqual(ids, ['feedbackNote', 'qStatus', 'recsCount', 'recsStatus', 'recsToast', 'trLive']);
  assert.ok(!/aria-live/.test(pg.$('#sidebar').innerHTML + pg.$('#app').innerHTML), 'a live region drawn by the toolbar or the panel');
});
