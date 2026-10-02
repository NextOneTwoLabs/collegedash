// The list's filters, search and sort in the address (issue #14), with Bianque's five amendments from the plan review.
//
//     node --test tests/list_url_state.test.mjs
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM, as the other page tests do, and boots
// exactly as a browser would (boot() -> loadIndex -> route). What the stub adds for this suite:
//   - a history with real entries: pushState adds one (dropping any forward entries), replaceState rewrites the
//     current one, back()/forward() move and fire popstate and hashchange, and a page assignment to location.hash is a
//     navigation (a new entry and a hashchange), as in a browser. Entry counts are read from it, never assumed;
//   - every innerHTML the page writes, on any element, is recorded, so "planted markup never reaches an HTML sink" is
//     checked against everything the page drew, not against the few places someone thought to look;
//   - sidebar and list buttons are real enough to click: querySelectorAll('[data-x]') returns one node per element in
//     the drawn HTML with its data-* attributes, and the page's own handlers are attached to those nodes;
//   - fetch is recorded (URL, method, body) and answered from public/data. Nothing reaches the network.
// The data is the shipped index (public/data/programs/index.json); no player rows are read or printed.
//
// LIST_URL_TEST_HTML (optional) points at another copy of index.html, to run these checks against main and show
// them failing there.
//
// What it CANNOT prove, and a human must check in a browser: what a real address bar shows and how a chat app links
// it, a real Back button, and Safari's limit on replaceState calls (the writer swallows a refusal).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML_PATH = process.env.LIST_URL_TEST_HTML || path.join(PUBLIC, 'index.html');
const HTML = fs.readFileSync(HTML_PATH, 'utf8');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const LIST_PARAMS = ['div', 'region', 'conf', 'class', 'cond', 'q', 'sort', 'dir', 'view'];

// ---------- the stub page ----------

const unesc = s => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const camel = s => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());

function loadPage({ hash = '#/programs', store = {}, session = {}, ask = false } = {}) {
  const els = new Map(), docListeners = {}, winListeners = {}, requests = [], sinks = [], writes = [];
  const ls = new Map(Object.entries(store).map(([k, v]) => [k, JSON.stringify(v)]));
  const ss = new Map(Object.entries(session));
  function makeEl(name) {
    const listeners = {}, classes = new Set(), attrs = new Map(), q = {};
    let html = '';
    const el = {
      _name: name, _listeners: listeners, _q: q, textContent: '', value: '', title: '', hidden: false, scrollTop: 0, placeholder: '',
      disabled: false, dataset: {}, style: {}, elements: null, open: false,
      get innerHTML() { return html; },
      set innerHTML(v) { html = String(v); sinks.push({ el: name, html }); },
      setAttribute: (k, v) => attrs.set(k, String(v)), getAttribute: k => (attrs.has(k) ? attrs.get(k) : null), removeAttribute: k => attrs.delete(k),
      classList: { add: (...c) => c.forEach(x => classes.add(x)), remove: (...c) => c.forEach(x => classes.delete(x)), contains: c => classes.has(c),
        toggle: (c, f) => { const on = f === undefined ? !classes.has(c) : !!f; on ? classes.add(c) : classes.delete(c); return on; } },
      addEventListener(type, fn) { (listeners[type] ||= []).push(fn); }, removeEventListener() { },
      querySelector: sel => (/^#[\w-]+$/.test(sel) ? bySelector(sel) : makeEl(`${name} ${sel}`)),
      // '[data-x]': one node per element of the drawn HTML carrying data-x, with its attributes, so handlers can be clicked
      querySelectorAll(sel) {
        const m = /^\[data-([\w-]+)\]$/.exec(sel); if (!m) return [];
        const nodes = [...html.matchAll(/<(\w+)((?:\s+[\w-]+(?:="[^"]*")?)*)\s*\/?>/g)].filter(t => new RegExp(`\\sdata-${m[1]}(?:=|\\s|$)`).test(t[2])).map(t => {
          const a = Object.fromEntries([...t[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)].map(x => [x[1], unesc(x[2] ?? '')]));
          const node = makeEl(`${name} ${sel}`);
          node._attrs = a;
          for (const [k, v] of Object.entries(a)) if (k.startsWith('data-')) node.dataset[camel(k.slice(5))] = v;
          node.closest = () => null;
          return node;
        });
        q[sel] = nodes;
        return nodes;
      },
      closest: () => null, matches: () => false, focus() { }, blur() { }, contains: () => false,
    };
    return el;
  }
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeEl(sel)); return els.get(sel); };
  const readPublic = url => {
    let rel = String(url).replace(/^\//, '').replace(/\?.*$/, '');
    if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
    else if (rel === 'api/v1/camps') rel = 'data/camps/index.json';
    else if (rel === 'api/v1/trends') rel = 'data/trends/index.json';
    else if (rel.startsWith('api/v1/programs/')) rel = `data/programs/${rel.slice('api/v1/programs/'.length)}.json`;
    const p = path.join(PUBLIC, rel);
    return p.startsWith(PUBLIC) && fs.existsSync(p) && fs.statSync(p).isFile() ? fs.readFileSync(p, 'utf8') : null;
  };
  const fire = (type, ev = {}) => (winListeners[type] || []).forEach(fn => fn({ type, ...ev }));
  // the history: entries and a cursor; the address is entries[at]
  const hist = { entries: [hash], at: 0 };
  const loc = {
    search: '', href: 'http://localhost/',
    get hash() { return hist.entries[hist.at]; },
    set hash(h) { const v = h.startsWith('#') ? h : `#${h}`; if (v === hist.entries[hist.at]) return; hist.entries.splice(hist.at + 1); hist.entries.push(v); hist.at++; writes.push({ kind: 'navigate', url: v }); setTimeout(() => fire('hashchange'), 0); },
    replace(h) { const v = h.startsWith('#') ? h : `#${h}`; const was = hist.entries[hist.at]; hist.entries[hist.at] = v; writes.push({ kind: 'location.replace', url: v }); if (v !== was) setTimeout(() => fire('hashchange'), 0); },
  };
  const go = d => { const to = hist.at + d; if (to < 0 || to >= hist.entries.length) return; const was = hist.entries[hist.at]; hist.at = to; fire('popstate'); if (hist.entries[to] !== was) fire('hashchange'); };
  const history = {
    pushState(_, __, url) { hist.entries.splice(hist.at + 1); hist.entries.push(String(url)); hist.at++; writes.push({ kind: 'push', url: String(url) }); },
    replaceState(_, __, url) { hist.entries[hist.at] = String(url); writes.push({ kind: 'replace', url: String(url) }); },
    back: () => go(-1), forward: () => go(1),
    get length() { return hist.entries.length; },
  };
  const doc = {
    documentElement: makeEl('html'), body: makeEl('body'), activeElement: null, title: 'College Soccer', visibilityState: 'visible',
    querySelector: bySelector, querySelectorAll: () => [], createElement: makeEl, getElementById: id => bySelector(`#${id}`),
    addEventListener(type, fn) { (docListeners[type] ||= []).push(fn); },
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl, Error,
    isNaN, parseInt, parseFloat, URL, URLSearchParams, encodeURIComponent, decodeURIComponent, TextEncoder,
    document: doc, location: loc, history,
    matchMedia: () => ({ matches: false }), innerWidth: 1280, screen: { width: 1280, height: 800 }, navigator: {},
    performance: { now: () => Date.now(), getEntriesByName: () => [] }, requestAnimationFrame: f => setTimeout(f, 0),
    localStorage: { getItem: k => (ls.has(k) ? ls.get(k) : null), setItem: (k, v) => ls.set(k, String(v)), removeItem: k => ls.delete(k) },
    sessionStorage: { getItem: k => (ss.has(k) ? ss.get(k) : null), setItem: (k, v) => ss.set(k, String(v)), removeItem: k => ss.delete(k) },
    addEventListener(type, fn) { (winListeners[type] ||= []).push(fn); }, removeEventListener() { },
    fetch: async (url, init = {}) => {
      requests.push({ url: String(url), method: init.method || 'GET', body: init.body ?? null });
      const u = String(url).replace(/^\//, '');
      if (u === 'api/ask/status') return ask ? { ok: true, status: 200, async json() { return { ask: true }; } } : { ok: false, status: 404, async json() { return {}; } };
      if (u === 'api/ask') return { ok: false, status: 503, async json() { return { error: 'no' }; } };
      if (u === 'api/feedback') return { ok: true, status: 200, async json() { return { ok: true }; } };
      const b = readPublic(url);
      if (b == null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      return { ok: true, status: 200, async json() { return JSON.parse(b); } };
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  const lines = HTML.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'index.html: could not find the inline <script>');
  const names = ['S', 'route', 'setQuery', 'renderSidebar', 'loadIndex', 'listHashOf', 'listStateOf', 'condFormOpen', 'condFormSubmit', 'condRemove', 'feedbackRoute'];
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(names)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, $: bySelector, hist, writes, requests, sinks, docListeners, ls, ss };
}
const settle = (ms = 60) => new Promise(r => setTimeout(r, ms));
async function open(opts) { const pg = loadPage(opts); await settle(250); return pg; }
const pushes = pg => pg.writes.filter(w => w.kind === 'push').length;
function pill(pg, attr, value, div) {
  const nodes = pg.$('#sidebar')._q[`[data-${attr}]`] || [];
  const key = camel(attr), n = nodes.find(x => x.dataset[key] === value && (div === undefined || x.dataset.confDiv === div));
  assert.ok(n, `no ${attr} pill "${value}" in the sidebar`);
  return n;
}
async function click(pg, attr, value, div) { pill(pg, attr, value, div).onclick(); await settle(); }
async function type(pg, text) {
  const box = pg.$('#q');
  assert.equal((box._listeners.input || []).length, 1, 'the header box has no input handler');
  for (let i = 1; i <= text.length; i++) { box.value = text.slice(0, i); box._listeners.input[0]({ target: box }); }
}
const back = async pg => { pg.sb.history.back(); await settle(); };
const forward = async pg => { pg.sb.history.forward(); await settle(); };
const DEFAULT = { division: [], region: [], conf: [], classYear: [], cond: [], q: '', sort: 'name', sortDir: null, view: 'cards' };
const plain = v => JSON.parse(JSON.stringify(v));

// ---------- 1. the format (snapshot) and its round trip ----------

const SNAPSHOT = [
  [{}, '#/programs?sort=name'],
  [{ division: ['D2'], region: ['West'], conf: ['D2|Independent'], q: 'Ohio' }, '#/programs?div=D2&region=West&conf=D2:Independent&q=Ohio&sort=name'],
  [{ division: ['D3', 'D1'], region: ['West', 'Midwest'] }, '#/programs?div=D1,D3&region=Midwest,West&sort=name'],
  [{ conf: ['D3|College Conference of Illinois & Wisconsin'] }, '#/programs?conf=D3:College+Conference+of+Illinois+%26+Wisconsin&sort=name'],
  [{ conf: ['D1|Big Ten', 'ACC'] }, '#/programs?conf=ACC,D1:Big+Ten&sort=name'],
  [{ cond: [{ field: 'admissionRate', op: '<', value: 0.3 }, { field: 'academicRank', op: '<=', value: 50 }] }, '#/programs?cond=academicRank:le:50,admissionRate:lt:0.3&sort=name'],
  [{ classYear: ['2027', '2026'] }, '#/programs?class=2026,2027&sort=name'],
  [{ q: 'a+b & c%d #e, f:g Montréal' }, '#/programs?q=a%2Bb+%26+c%25d+%23e%2C+f%3Ag+Montr%C3%A9al&sort=name'],
  [{ sort: 'admit', sortDir: 'asc', view: 'table' }, '#/programs?sort=admit&dir=asc&view=table'],
  [{ division: ['D2'], region: ['West', 'Midwest'], conf: ['D2|Independent'], classYear: ['2027'], cond: [{ field: 'admissionRate', op: '<', value: 0.3 }], q: 'Ohio State', sort: 'admit', sortDir: 'asc', view: 'table' },
    '#/programs?div=D2&region=Midwest,West&conf=D2:Independent&class=2027&cond=admissionRate:lt:0.3&q=Ohio+State&sort=admit&dir=asc&view=table'],
];
let BASE = null;
const base = async () => (BASE ||= await open({ hash: '#/programs' }));

test('format snapshot: ten states give exactly these addresses (the public contract)', async () => {
  const pg = await base();
  assert.equal(typeof pg.sb.listHashOf, 'function', 'there is no list address writer (listHashOf)');
  for (const [st, want] of SNAPSHOT) assert.equal(pg.sb.listHashOf({ ...DEFAULT, ...st }), want, JSON.stringify(st));
  // the TPM's example spelling is read too: | and %7C as the division separator
  assert.deepEqual(plain(pg.sb.listStateOf('conf=D2|Independent').conf), ['D2|Independent']);
  assert.deepEqual(plain(pg.sb.listStateOf('conf=D2%7CIndependent').conf), ['D2|Independent']);
});

test('round trip: reading each snapshot address gives back the state, sorted', async () => {
  const pg = await base();
  for (const [st, h] of SNAPSHOT) {
    const want = { ...DEFAULT, ...st };
    for (const k of ['division', 'region', 'conf', 'classYear']) want[k] = [...want[k]].sort();
    want.conf = want.conf.slice().sort((x, y) => (x.replace('|', ':') < y.replace('|', ':') ? -1 : 1));
    want.cond = want.cond.slice().sort((x, y) => (x.field < y.field ? -1 : 1));
    const got = plain(pg.sb.listStateOf(h.slice(h.indexOf('?') + 1)));
    assert.deepEqual(got, plain(want), h);
    assert.equal(pg.sb.listHashOf(got), h, `${h} is not canonical after a round trip`);
  }
});

test('encoding (amendment 4): + is a space, %2B a plus; + & % # , : and non-ASCII survive in q; a malformed escape is dropped', async () => {
  const pg = await base();
  const q = s => pg.sb.listStateOf(s).q;
  assert.equal(q('q=a+b'), 'a b');
  assert.equal(q('q=a%2Bb'), 'a+b');
  assert.equal(q('q=Montr%C3%A9al'), 'Montréal');
  for (const s of ['1+1', 'A&M', '100%', '#1', 'a,b', 'a:b', 'Montréal', 'São Paulo, SP', 'x %2B y']) {
    const h = pg.sb.listHashOf({ ...DEFAULT, q: s });
    assert.ok(!/[,:]/.test(h.slice(h.indexOf('q='), h.indexOf('&sort'))), `${s}: a , or : inside q is not escaped (${h})`);
    assert.equal(q(h.slice(h.indexOf('?') + 1)), s, `${s} does not survive the round trip (${h})`);
  }
  assert.equal(q('q=%E0'), '', 'a malformed escape is carried');
  assert.equal(q('q=%E0&sort=admit').length, 0);
  assert.equal(pg.sb.listStateOf('q=%E0&sort=admit').sort, 'admit', 'one bad value took the rest of the address with it');
});

// ---------- 2. hostile and stale input (amendment 1) ----------

test('every arriving value is checked against what the page knows; only q is free text (capped, no control characters)', async () => {
  const pg = await base();
  const st = plain(pg.sb.listStateOf(['foo=1', '__proto__=x', 'constructor=y', 'region=Nowhere,West,%3Cb%3E', 'region=South', 'div=D9,D1',
    'class=1999,2027', 'conf=Nowhere,__proto__,constructor,D9:ACC,D2:ACC,%3Cscript%3E,ACC', 'cond=admissionRate:lt:abc,constructor:lt:1,admissionRate:zz:1,admissionRate:lt:0.3:9,admissionRate:lt:0.4',
    'sort=__proto__', 'dir=up', 'view=grid', `q=%07a%0Ab${'x'.repeat(300)}`].join('&')));
  assert.deepEqual(st.region, ['West'], 'an unknown region or a repeated param was carried');
  assert.deepEqual(st.division, ['D1']);
  assert.deepEqual(st.classYear, ['2027']);
  assert.deepEqual(st.conf, ['ACC'], 'an unknown conference, a wrong division or markup was carried');
  assert.deepEqual(st.cond, [{ field: 'admissionRate', op: '<', value: 0.4 }]);
  assert.equal(st.sort, 'name'); assert.equal(st.sortDir, null); assert.equal(st.view, 'cards');
  assert.equal(st.q.length, 100, 'q is not capped at 100 characters');
  assert.ok(st.q.startsWith('abxxx'), 'control characters are carried in q');
  assert.equal(({}).x, undefined); assert.equal(Object.prototype.constructor, Object);
  // a conference keyed to a division the address does not select is pruned, as a division pill prunes
  assert.deepEqual(plain(pg.sb.listStateOf('div=D1&conf=D2:Independent,D1:ACC').conf), ['D1|ACC']);
});

// ---------- 3. arriving (replace only) ----------

test('arriving on a link applies it over the saved filters, saves it, and rewrites the address in place', async () => {
  const pg = await open({ hash: '#/programs?div=D2&conf=D2:Independent&q=Ohio', store: { 'cd.filters': { region: ['South'], sort: 'rpi', view: 'table' } } });
  const f = pg.sb.S.filters;
  assert.deepEqual(plain(f.division), ['D2']);
  assert.deepEqual(plain(f.conf), ['D2|Independent']);
  assert.deepEqual(plain(f.region), [], 'the saved region survived a link that has none');
  assert.equal(f.sort, 'name'); assert.equal(f.view, 'cards');
  assert.equal(pg.sb.S.qRaw, 'Ohio'); assert.equal(pg.$('#q').value, 'Ohio', 'the search box does not show the link\'s search');
  assert.match(pg.$('#app').innerHTML, /matching “Ohio”/);
  assert.equal(pill(pg, 'conf', 'Independent', 'D2')._attrs['aria-pressed'], 'true', 'the D2 Independent pill is not lit');
  assert.deepEqual(JSON.parse(pg.ls.get('cd.filters')).division, ['D2'], 'the link\'s state is not saved');
  assert.deepEqual(pg.hist.entries, ['#/programs?div=D2&conf=D2:Independent&q=Ohio&sort=name'], 'arriving added an entry or did not canonicalise');
  assert.equal(pushes(pg), 0, 'arriving pushed');
});

test('a bare #/programs keeps the saved filters and becomes canonical in place', async () => {
  const pg = await open({ hash: '#/programs', store: { 'cd.filters': { region: ['West'], sort: 'admit' } } });
  assert.deepEqual(plain(pg.sb.S.filters.region), ['West']);
  assert.deepEqual(pg.hist.entries, ['#/programs?region=West&sort=admit']);
  assert.equal(pushes(pg), 0);
});

test('a link whose every value is dropped is replaced, never pushed (the old-form #/?region=Nowhere, through the #465 alias)', async () => {
  const pg = await open({ hash: '#/?region=Nowhere&sort=__proto__', store: { 'cd.filters': { region: ['West'] } } });
  assert.deepEqual(pg.hist.entries, ['#/programs?sort=name']);
  assert.deepEqual(plain(pg.sb.S.filters.region), []);
  assert.equal(pushes(pg), 0);
});

// ---------- 4. history (amendment 2) ----------

test('history: a commit adds one entry, typing adds none, and Back/Forward restore the state without adding any', async () => {
  const pg = await open({ hash: '#/programs' });
  assert.deepEqual(pg.hist.entries, ['#/programs?sort=name']);
  await click(pg, 'region', 'West');
  assert.deepEqual(pg.hist.entries, ['#/programs?sort=name', '#/programs?region=West&sort=name'], 'a pill did not add exactly one entry');
  await type(pg, 'Ohio'); await settle(150);
  assert.equal(pg.hist.entries.length, 2, 'typing added history entries');
  assert.equal(pg.sb.location.hash, '#/programs?region=West&q=Ohio&sort=name', 'typing did not replace the entry with the search');
  pg.$('#sortSelect').onchange({ target: { value: 'admit' } }); await settle();
  assert.deepEqual(pg.hist.entries.slice(2), ['#/programs?region=West&q=Ohio&sort=admit'], 'the sort did not add one entry');
  const n = pg.hist.entries.length, p = pushes(pg);
  await back(pg);
  assert.equal(pg.sb.S.filters.sort, 'name'); assert.deepEqual(plain(pg.sb.S.filters.region), ['West']); assert.equal(pg.$('#q').value, 'Ohio');
  await back(pg);
  assert.deepEqual(plain(pg.sb.S.filters.region), []); assert.equal(pg.sb.S.qRaw, '', 'Back did not take the search off');
  assert.equal(pill(pg, 'region', 'West')._attrs['aria-pressed'], 'false', 'the sidebar was not redrawn on Back');
  await forward(pg);
  assert.deepEqual(plain(pg.sb.S.filters.region), ['West']);
  await back(pg);
  assert.equal(pg.hist.entries.length, n, 'Back, Forward, Back added entries');
  assert.equal(pushes(pg), p, 'Back or Forward pushed');
  assert.equal(pg.sb.location.hash, '#/programs?sort=name');
});

test('history: a commit within 80 ms of typing writes the typing into the entry it was typed on first', async () => {
  const pg = await open({ hash: '#/programs' });
  await type(pg, 'Te');
  pill(pg, 'region', 'West').onclick();  // no wait: the typing replace is still pending
  await settle(150);
  assert.deepEqual(pg.hist.entries, ['#/programs?q=Te&sort=name', '#/programs?region=West&q=Te&sort=name']);
});

test('history: the other commits (direction, Cards/Stats key, conditions) push once each; Back from a program lands on the filtered list', async () => {
  const pg = await open({ hash: '#/programs' });
  await click(pg, 'division', 'D1');
  pg.$('#sortDir').onclick(); await settle();
  assert.equal(pg.sb.location.hash, '#/programs?div=D1&sort=name&dir=desc');
  pg.docListeners.keydown.forEach(fn => fn({ key: 'c', target: { matches: () => false, closest: () => null }, preventDefault() { } })); await settle();
  assert.equal(pg.sb.location.hash, '#/programs?div=D1&sort=name&dir=desc&view=table');
  pg.sb.condFormOpen(); pg.$('#condValue').value = '30'; pg.sb.condFormSubmit(); await settle();
  assert.match(pg.sb.location.hash, /^#\/programs\?div=D1&cond=admissionRate:(lt|le|gt|ge):0\.3&sort=name&dir=desc&view=table$/);
  pg.sb.condRemove(0); await settle();
  assert.equal(pg.hist.entries.length, 6, 'each commit did not add exactly one entry');
  const n = pg.hist.entries.length;
  pg.sb.location.hash = `#/p/${INDEX.programs[0].slug}`; await settle(150);
  await back(pg);
  assert.equal(pg.sb.location.hash, '#/programs?div=D1&sort=name&dir=desc&view=table');
  assert.deepEqual(plain(pg.sb.S.filters.division), ['D1']); assert.equal(pg.sb.S.filters.view, 'table');
  assert.equal(pg.hist.entries.length, n + 1, 'coming back from a program added an entry');
});

// ---------- 5. old links ----------

test('old links: #/c/<name>, a keyed #/c/, #/rpi, #pilot=, #/p/ and #/trends keep working, and only ever replace', async () => {
  let pg = await open({ hash: '#/c/ACC', store: { 'cd.filters': { division: ['D2'] } } });
  assert.deepEqual(plain(pg.sb.S.filters.conf), ['ACC']); assert.deepEqual(plain(pg.sb.S.filters.division), []);
  assert.deepEqual(pg.hist.entries, ['#/programs?conf=ACC&sort=name']);
  assert.deepEqual(JSON.parse(pg.ls.get('cd.filters')).conf, ['ACC'], '#/c/ no longer saves the conference');
  assert.equal(pill(pg, 'conf', 'ACC')._attrs['aria-pressed'], 'true', 'the sidebar was not redrawn for #/c/');
  pg = await open({ hash: '#/c/D2%7CIndependent' });
  assert.deepEqual(pg.hist.entries, ['#/programs?conf=D2:Independent&sort=name']);
  for (const h of ['#/c/%E0', '#/c/Nowhere', '#/c/%3Cscript%3E']) {
    pg = await open({ hash: h });
    assert.deepEqual(plain(pg.sb.S.filters.conf), [], `${h} carried a value the data does not have`);
    assert.deepEqual(pg.hist.entries, ['#/programs?sort=name'], h);
  }
  pg = await open({ hash: '#/rpi' });
  assert.deepEqual(pg.hist.entries, ['#/programs?sort=rpi&view=table']);
  pg = await open({ hash: '#pilot=abc123secret' });
  assert.ok(pg.writes.every(w => !w.url.includes('abc123secret')) && pg.hist.entries.every(h => !h.includes('abc123secret')), 'the pilot token was written back');
  assert.deepEqual(pg.hist.entries, ['#/'], 'the pilot strip lands on Home (#465), which is never rewritten');
  const slug = INDEX.programs[0].slug;
  pg = await open({ hash: `#/p/${slug}` });
  assert.deepEqual(pg.hist.entries, [`#/p/${slug}`]);
  pg = await open({ hash: '#/trends' });
  assert.ok(pg.hist.entries.every(h => h.startsWith('#/trends')), `Pipelines took the list format: ${pg.hist.entries}`);
  for (const p of [pg]) assert.equal(pushes(p), 0);
});

// ---------- 6. planted markup (amendment 1) and Ask ----------

test('XSS: planted markup in q, conf and region reaches no HTML sink on the list, Camps or Pipelines, and arriving never asks', async () => {
  const planted = '"><img src=x onerror=alert(1)>';
  const pg = await open({ hash: '#/programs?q=%22%3E%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E&conf=%3Cscript%3E&region=%3Cb%3E', ask: true });
  assert.equal(pg.sb.S.ask, true, 'fixture: Ask is not on, so "never asks" would prove nothing');
  assert.equal(pg.sb.S.qRaw, planted, 'the planted search did not arrive, so the sinks were never exercised');
  assert.deepEqual(plain(pg.sb.S.filters.conf), []); assert.deepEqual(plain(pg.sb.S.filters.region), []);
  // the box's own paths: its suggestions, its status line and the Ask option
  pg.$('#q')._listeners.input[0]({ target: pg.$('#q') }); await settle(150);
  pg.sb.location.hash = '#/camps'; await settle(250);
  // Pipelines names the search only while a club or high school is picked (and no program), so one is picked
  const club = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'trends', 'index.json'), 'utf8')).clubs.id[0];
  pg.sb.location.hash = `#/trends?club=${encodeURIComponent(club)}`; await settle(300);
  assert.ok(pg.sinks.some(s => /^#(app|trSub)$/.test(s.el) && /programs matching “&quot;&gt;&lt;img/.test(s.html)), 'Pipelines never drew its search line, so it was not checked');
  const drawn = new Set(pg.sinks.map(s => s.el));
  for (const el of ['#sidebar', '#app', '#qList']) assert.ok(drawn.has(el), `${el} was never drawn, so it was not checked`);
  // The page draws no <img> or <script> through innerHTML at all, so any one is the planted markup; an unescaped quote
  // breaking out of an attribute would leave the same <img behind it.
  for (const s of pg.sinks) assert.ok(!/<img|<script|onerror=alert\(1\)>/i.test(s.html), `planted markup reached ${s.el}: ${s.html.slice(0, 200)}`);
  assert.ok(/&quot;&gt;&lt;img src=x onerror=alert\(1\)&gt;/.test(pg.sinks.filter(s => s.el === '#app').map(s => s.html).join('')), 'the search is not shown, escaped, in the page');
  assert.ok(!pg.sb.document.title.includes('img'), 'the search reached document.title');
  for (const el of ['#qStatus']) assert.ok(!/<img/.test(pg.$(el).innerHTML), `${el} holds markup`);
  assert.deepEqual(pg.requests.filter(r => /(^|\/)api\/ask$/.test(r.url)), [], 'arriving with a search asked the question');
  assert.ok(pg.hist.entries.every(h => !/[<>"]/.test(h)), 'raw markup was written into the address');
});

// ---------- 7. privacy (amendments 3 and 5) ----------

test('privacy: no address ever carries recommendations, the pilot, compare, shortlist, residency or More statistics; the title never carries q', async () => {
  const pg = await open({
    hash: '#/programs',
    store: { 'cd.recs': { v: 1, prefs: { SENTINEL_RECS: 1 } }, 'cd.compare': ['SENTINEL_CMP'], 'cd.favorites': ['SENTINEL_FAV'], 'cd.residency': 'SENTINEL_RES', 'cd.filters': { moreStats: true } },
    session: { 'cd.recs.pilot': 'SENTINEL_PILOT' },
  });
  await click(pg, 'region', 'West'); await click(pg, 'division', 'D1'); await click(pg, 'class', '2027');
  await click(pg, 'conf', 'ACC', 'D1');
  pg.$('#sortSelect').onchange({ target: { value: 'admit' } }); pg.$('#sortDir').onclick(); await settle();
  pg.sb.condFormOpen(); pg.$('#condValue').value = '40'; pg.sb.condFormSubmit(); await settle();
  await type(pg, 'Secret Player'); await settle(150);
  const written = [...pg.writes.map(w => w.url), ...pg.hist.entries];
  assert.ok(written.length >= 8);
  for (const h of written) {
    assert.match(h, /^#\/programs\?/, `not a list address: ${h}`);
    const keys = h.slice(h.indexOf('?') + 1).split('&').map(p => p.split('=')[0]);
    assert.ok(keys.every(k => LIST_PARAMS.includes(k)), `a param outside the nine: ${h}`);
    assert.ok(!/SENTINEL|moreStats|recs|pilot|residency|compare|fav/i.test(h), `private state in the address: ${h}`);
  }
  assert.match(pg.sb.location.hash, /q=Secret\+Player/);
  assert.ok(!/Secret/.test(pg.sb.document.title), 'the search reached document.title');
});

test('feedback sends a rebuilt route: the canonical list address without q on the list, the bare path elsewhere', async () => {
  const pg = await open({ hash: '#/programs?q=Secret+Name&foo=bar&region=West&zz=%3Cb%3E' });
  const form = pg.$('#feedbackForm');
  form.elements = { message: { value: 'hello' }, email: { value: '' }, website: { value: '' } };
  const send = async () => { await form._listeners.submit[0]({ preventDefault() { } }); await settle(); return JSON.parse(pg.requests.filter(r => r.url.endsWith('api/feedback')).at(-1).body); };
  assert.equal((await send()).route, '#/programs?region=West&sort=name');
  pg.sb.location.hash = '#/trends?club=SENTINEL_CLUB'; await settle(250);
  assert.equal((await send()).route, '#/trends');
  const slug = INDEX.programs[0].slug;
  pg.sb.location.hash = `#/p/${slug}/camps?q=Secret`; await settle(250);
  const body = await send();
  assert.equal(body.route, `#/p/${slug}/camps`);
  assert.equal(body.program, slug, 'the program field changed');
  assert.ok(pg.requests.filter(r => r.url.endsWith('api/feedback')).every(r => !/Secret|SENTINEL|foo|zz/.test(r.body)), 'a search or a leftover param reached the feedback body');
});

// ---------- 8. one writer, one set of commits ----------

test('static: one writer of list addresses; pushState only from listCommit and the Pipelines picker; feedback never reads location.hash', () => {
  const script = HTML.slice(HTML.indexOf('<script>'), HTML.indexOf('</script>'));
  const code = script.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
  const pushSites = [...code.matchAll(/history\.pushState\(|'pushState'/g)].length;
  assert.equal(pushSites, 3, 'a pushState outside listUrlWrite, trendsCommit and campsCommit (#465)');
  assert.match(code, /history\.pushState\(null, '', trendsUrl\(sel\)\)/);
  assert.match(code, /function campsCommit\(next, focus\) \{[^]*?history\.pushState\(null, '', h\)/);
  assert.match(code, /function listUrlWrite\(mode, st = listSnapshot\(\)\) \{[^]*?history\[mode === 'push' \? 'pushState' : 'replaceState'\]\(null, '', h\)/);
  assert.ok(!/history\.replaceState\(null, '', '#\/'\); return go/.test(code), '#/c/ still rewrites to a bare #/');
  assert.equal([...code.matchAll(/listCommit\(\);/g)].length, 16, 'the commit sites changed: pills (4), sort, direction, two conditions, the c key, Cards/Stats (2), table headers (2), Ask applied and undone, Recommended\'s clear');
  assert.match(code, /route: feedbackRoute\(\)/);
  assert.ok(!/route: location\.hash/.test(code), 'feedback still sends the raw address');
  // About the data says what a shared link carries (Bianque, non-blocking)
  assert.match(HTML, /<h3>What does a shared link include\?<\/h3>[\s\S]{0,400}anything typed in the search box and a recruiting class year/);
  // Bianque on #456: a Compare link names the programs compared, so the card must not say comparison never travels
  assert.match(HTML, /A link to the Compare page lists the programs you're comparing\./);
  assert.ok(!/shortlist, comparison, residency/.test(HTML), 'the About card still says comparison is never in a link');
});

// ---------- 9. #465 (owner's D1): Home at #/, Programs at #/programs?…, #14's #/?… a permanent alias ----------

test('#465: every old #14 address (#/?…, #/?, #/list) opens the same list at #/programs?…, in place, never Home', async () => {
  const cases = [
    ['#/?div=D2&conf=D2:Independent&q=Ohio', '#/programs?div=D2&conf=D2:Independent&q=Ohio&sort=name'],
    ['#/?div=D2&conf=D2|Independent&q=Ohio&sort=name', '#/programs?div=D2&conf=D2:Independent&q=Ohio&sort=name'],
    ['#?region=West&sort=admit&dir=asc&view=table', '#/programs?region=West&sort=admit&dir=asc&view=table'],
    ['#/?', '#/programs?sort=name'],
    ['#/list?class=2027', '#/programs?class=2027&sort=name'],
  ];
  for (const [from, to] of cases) {
    const pg = await open({ hash: from, store: { 'cd.filters': { region: ['South'] } } });
    assert.deepEqual(pg.hist.entries, [to], `${from} did not become ${to} in place`);
    assert.equal(pushes(pg), 0, `${from}: the alias pushed`);
    assert.ok(!/Find your college soccer path/.test(pg.$('#app').innerHTML), `${from} opened Home`);
  }
  // a bare #/list keeps the saved filters, as a bare #/programs does
  const pg = await open({ hash: '#/list', store: { 'cd.filters': { region: ['South'] } } });
  assert.deepEqual(pg.hist.entries, ['#/programs?region=South&sort=name']);
});

test('#465: a bare #/ (and no hash at all) is Home - never rewritten, never sort=name, saved filters untouched', async () => {
  for (const hash of ['#/', '', '#']) {
    const pg = await open({ hash, store: { 'cd.filters': { region: ['West'], sort: 'admit' } } });
    assert.deepEqual(pg.hist.entries, [hash], `${JSON.stringify(hash)} was rewritten`);
    assert.equal(pg.writes.length, 0, `${JSON.stringify(hash)}: something was written to history`);
    assert.match(pg.$('#app').innerHTML, /<h1 class="content-title">Find your college soccer path\.<\/h1>/);
    assert.match(pg.$('#app').innerHTML, /href="#\/programs"[^>]*>(?:(?!<\/a>)[\s\S])*Browse Programs[\s\S]*?<\/a>[\s\S]*href="#\/camps"[^>]*>(?:(?!<\/a>)[\s\S])*Find ID Camps[\s\S]*?<\/a>[\s\S]*href="#\/trends"[^>]*>(?:(?!<\/a>)[\s\S])*Explore Pipelines/);
    assert.deepEqual(JSON.parse(pg.ls.get('cd.filters')).region, ['West'], 'Home changed the saved filters');
    assert.equal(pg.sb.feedbackRoute(), '#/');
  }
});

test('#465: Home -> Programs uses the saved filters; Back returns to Home without rewriting it', async () => {
  const pg = await open({ hash: '#/', store: { 'cd.filters': { division: ['D1'] } } });
  pg.sb.location.hash = '#/programs'; await settle(300);
  assert.deepEqual(pg.hist.entries, ['#/', '#/programs?div=D1&sort=name']);
  await back(pg);
  assert.equal(pg.sb.location.hash, '#/');
  assert.match(pg.$('#app').innerHTML, /Find your college soccer path/);
  assert.equal(pg.hist.entries.length, 2);
});

test('#465: Ask from Home lands on Programs; old #/c/ and #/rpi land on #/programs', async () => {
  const src = HTML.slice(HTML.indexOf('<script>'), HTML.indexOf('</script>'));
  assert.match(src, /if \(v === 'list' \|\| v === 'camps'\) rerenderForFilters\(\); else location\.hash = '#\/programs';/, 'applyAsk off the list does not go to #/programs');
  let pg = await open({ hash: '#/c/ACC' });
  assert.deepEqual(pg.hist.entries, ['#/programs?conf=ACC&sort=name']);
  pg = await open({ hash: '#/rpi' });
  assert.deepEqual(pg.hist.entries, ['#/programs?sort=rpi&view=table']);
});

// The inventory (Huatuo, change 5): every bare-root address string left in the page is one of these, each meaning Home.
// A new '#/' meaning "the list" fails here; the list is '#/programs'.
test('#465 inventory: the only bare-root ("#/") addresses left are Home links and the pilot strip', () => {
  const src = HTML.replace(/\r\n/g, '\n');
  const found = [...src.matchAll(/[^\n]{0,60}['"`]#\/['"`][^\n]{0,30}/g)].map(m => m[0].trim());
  const allowed = [
    /history\.replaceState\(null, '', '#\/'\); \} catch/,           // the #400 pilot strip (Home)
    /if \(location\.hash !== '#\/'\) location\.replace\('#\/'\)/,   // its fallback (Home)
    /\{ label: 'Home', href: '#\/' \}/,                              // breadcrumbs that start at Home
    /<a class="section-label" href="#\/" aria-label="College Soccer/,  // the header's product name (#465 B)
  ];
  const stray = found.filter(l => !allowed.some(re => re.test(l)));
  assert.deepEqual(stray, [], 'a bare "#/" that is not Home');
  assert.equal(found.length, 10, `the inventory changed: ${found.length} bare-root strings (2 pilot, 7 Home crumbs: not found, the list twice, camps, Pipelines, About, Data API; the header's College Soccer link)`);
  assert.ok(!/location\.hash = '#\/'/.test(src) && !/location\.replace\('#\/'\)\s*;?\s*return/.test(src), 'a navigation to "#/" meant as the list');
  assert.ok((src.match(/'#\/programs'/g) || []).length >= 10, 'the list-intent navigations do not say #/programs');
});
