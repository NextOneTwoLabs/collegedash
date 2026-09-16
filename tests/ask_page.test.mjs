// Tests for the ask row in public/index.html (issue #165): off by default, and what it does when switched on.
//
//     node --test tests/ask_page.test.mjs
//
// Same mechanism as tests/condition_chips.test.mjs: the inline <script> runs in a `vm` against a stub DOM.
// The stub records addEventListener handlers, so the search box's real keydown handler is called with
// Enter and Shift+Enter. fetch is a stub that serves public/ and answers api/status and api/ask as each
// test says; nothing leaves the process.
//
// What this proves:
//   - OFF (api/status {"local":false}, the deployed Worker today; {"local":true}, serve.py; or no status at all):
//     no ask markup in the sidebar or either view, the placeholder and search status text are unchanged,
//     Enter with no name match does nothing and Shift+Enter still opens the top match, and api/ask is never
//     requested. With ASK_BASELINE_HTML pointing at the page from before this change, the rendered sidebar,
//     cards, table and camp view are compared with it byte for byte over several filter states (skipped,
//     visibly, when it is not set: CI has no pre-change copy of the page);
//   - ON (api/status {ask: true}): the ✦ Ask row appears, Enter asks only when no name matches and
//     Shift+Enter always asks, an answer is applied as ordinary filter state with a "From your question" line
//     and Undo restores what was there, an unsupported answer changes nothing and says so, values the page
//     cannot show are dropped on the way in, and the line disappears once the filters are changed by hand.
//
// What it CANNOT prove: focus, layout and real key delivery in a browser (see the PR's screenshots).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.ASK_PAGE_HTML || path.join(PUBLIC, 'index.html');

function makeElement(name) {
  const listeners = {};
  return {
    _name: name, _listeners: listeners, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    removeEventListener() { }, querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, contains: () => false,
  };
}
const HANDLES = ['S', 'renderList', 'renderCamps', 'renderSidebar', 'loadIndex', 'setQuery', 'updateSearchStatus', 'normText', 'askQuestion', 'undoAsk', 'saveState'];

// `status`: the api/status body, or null for a 404. `answer`: what api/ask returns (body, status).
function loadPage({ html = HTML, status = { local: false }, answer = null } = {}) {
  const els = new Map();
  const bySelector = (sel) => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
  const requests = [];
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector, querySelectorAll: () => [],
      addEventListener() { }, createElement: makeElement },
    location: { hash: '', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
    innerWidth: 1400, addEventListener() { },
    fetch: async (url, init) => {
      requests.push({ url: String(url), init });
      const ok = (body, st = 200) => ({ ok: st < 400, status: st, async json() { return JSON.parse(JSON.stringify(body)); } });
      if (url === 'api/status') return status ? ok(status) : ok({}, 404);
      if (url === 'api/ask') return answer ? ok(answer.body, answer.status || 200) : ok({ error: 'no' }, 404);
      const p = path.join(PUBLIC, String(url));
      return fs.existsSync(p) ? ok(JSON.parse(fs.readFileSync(p, 'utf8'))) : ok({}, 404);
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(html, 'utf8').split(/\r?\n/);
  const a = lines.findIndex((l) => l.trim() === '<script>'), b = lines.findIndex((l) => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(HANDLES)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  const $ = (sel) => sandbox.document.querySelector(sel);
  return { sb: sandbox, $, requests, app: () => $('#app').innerHTML, sidebar: () => $('#sidebar').innerHTML,
    askRequests: () => requests.filter((r) => r.url === 'api/ask') };
}
const settle = async (ms = 0) => { for (let i = 0; i < 30; i++) await new Promise((r) => setTimeout(r, 0)); if (ms) await new Promise((r) => setTimeout(r, ms)); };
async function ready(pg) {
  await pg.sb.loadIndex();
  await settle();
  assert.ok(pg.sb.S.index?.divisions, 'the index never loaded');
  return pg;
}
// Type into the search box the way the input handler does, and wait out its 80 ms debounce.
async function type(pg, text) { pg.$('#q').value = text; pg.sb.setQuery(text); await settle(100); }
// Fire the search box's real keydown handler (the one renderSidebar attached last).
function key(pg, k, shiftKey = false) {
  const fns = pg.$('#q')._listeners.keydown || [];
  assert.ok(fns.length, 'no keydown handler on #q');
  let prevented = false;
  fns[fns.length - 1]({ key: k, shiftKey, preventDefault() { prevented = true; } });
  return prevented;
}
const plain = (v) => JSON.parse(JSON.stringify(v));
const NO_MATCH = 'acc schools with admission under 30%';

for (const [name, status] of [['{"local":false}, the deployed Worker', { local: false }], ['{"local":true}, serve.py', { local: true }], ['no /api/status', null]]) {
  test(`off (${name}): no ask markup, unchanged search text, Enter and Shift+Enter behave as before, api/ask never requested`, async () => {
    const pg = await ready(loadPage({ status }));
    const { S } = pg.sb;
    assert.notEqual(S.ask, true, 'ask switched itself on'); // the page from before #165 has no S.ask at all
    pg.sb.renderSidebar();
    assert.ok(pg.sidebar().includes('placeholder="School or mascot…"'));
    assert.ok(!/ask/i.test(pg.sidebar().replace(/aria-label="[^"]*"/g, '')), 'ask markup in the sidebar');
    await type(pg, NO_MATCH);
    assert.equal(pg.$('#qStatus').textContent, 'No match - try the short name (UCLA, Ole Miss) or the mascot');
    assert.equal(key(pg, 'Enter'), false);
    await settle();
    assert.equal(pg.sb.location.hash, '', 'Enter with no match did something');
    await type(pg, 'stanford');
    assert.equal(pg.$('#qStatus').textContent, '1 match · Enter opens the first');
    key(pg, 'Enter', true);
    await settle();
    assert.equal(pg.sb.location.hash, '#/p/stanford', 'Shift+Enter no longer opens the top match');
    await pg.sb.renderList();
    assert.ok(!pg.app().includes('ask-banner'));
    pg.sb.location.hash = '#/camps';
    await pg.sb.renderCamps();
    assert.ok(!pg.app().includes('ask-banner'));
    assert.deepEqual(pg.askRequests(), [], 'api/ask was requested while off');
  });
}

const BASELINE = process.env.ASK_BASELINE_HTML;
test('off: sidebar, cards, table and camp view are byte-identical to the page before #165', { skip: BASELINE ? false : 'set ASK_BASELINE_HTML to the pre-change public/index.html to run this comparison' }, async () => {
  const now = await ready(loadPage());
  const before = await ready(loadPage({ html: BASELINE }));
  const states = [
    {}, { conf: ['ACC'] }, { region: ['South', 'West'], sort: 'tuition' }, { view: 'table', sort: 'rpi' },
    { cond: [{ field: 'admissionRate', op: '<', value: 0.3 }] }, { classYear: ['2027'], view: 'table' },
  ];
  for (const st of states) {
    const snaps = [];
    for (const pg of [now, before]) {
      Object.assign(pg.sb.S.filters, { conf: [], region: [], division: [], classYear: [], sort: 'name', view: 'cards', cond: [] }, JSON.parse(JSON.stringify(st)));
      pg.sb.location.hash = '';
      pg.sb.renderSidebar();
      await pg.sb.renderList();
      const list = pg.app(), side = pg.sidebar();
      pg.sb.location.hash = '#/camps';
      pg.sb.renderSidebar();
      await pg.sb.renderCamps();
      snaps.push({ side, list, campsSide: pg.sidebar(), camps: pg.app() });
    }
    for (const k of Object.keys(snaps[0])) assert.equal(snaps[0][k], snaps[1][k], `${k} differs for ${JSON.stringify(st)}`);
  }
});

const ANSWER = { division: [], conf: ['ACC'], region: ['South'], classYear: [], cond: [{ field: 'admissionRate', op: '<', value: 0.3 }], sort: 'tuition', reading: 'ACC programs in the South with admission under 30%, cheapest first' };

test('on: the ask row appears; Enter with no name match asks, applies the answer, shows the line, and Undo restores', async () => {
  const pg = await ready(loadPage({ status: { local: false, ask: true }, answer: { body: ANSWER } }));
  const { S } = pg.sb;
  assert.equal(S.ask, true);
  assert.ok(pg.sidebar().includes('placeholder="School, mascot, or a question…"'));
  assert.ok(pg.sidebar().includes('id="askSlot"'));
  S.filters.region = ['West']; S.filters.sort = 'rpi'; pg.sb.saveState();
  await type(pg, NO_MATCH);
  assert.equal(pg.$('#askSlot').innerHTML, `<button type="button" class="ask-row" id="askRow">✦ Ask: “${NO_MATCH}”</button>`);
  assert.equal(pg.$('#qStatus').textContent, 'No name match · Enter asks');
  assert.equal(key(pg, 'Enter'), true);
  await settle();
  assert.deepEqual(pg.askRequests().map((r) => JSON.parse(r.init.body)), [{ question: NO_MATCH }]);
  assert.equal(pg.askRequests()[0].init.method, 'POST');
  assert.deepEqual(plain({ conf: S.filters.conf, region: S.filters.region, cond: S.filters.cond, sort: S.filters.sort }),
    { conf: ['ACC'], region: ['South'], cond: [{ field: 'admissionRate', op: '<', value: 0.3 }], sort: 'tuition' });
  assert.equal(S.qRaw, '', 'the question stayed in the search box and would filter by name');
  await pg.sb.renderList();
  assert.ok(pg.app().includes('From your question: ACC · South region · Admission &lt; 30% · sorted by Tuition (out-of-state)'), pg.app().slice(0, 600));
  assert.ok(pg.app().includes('id="askUndo"'));
  pg.$('#askUndo').onclick();
  await settle();
  assert.deepEqual(plain({ conf: S.filters.conf, region: S.filters.region, cond: S.filters.cond, sort: S.filters.sort }),
    { conf: [], region: ['West'], cond: [], sort: 'rpi' });
  assert.equal(S.qRaw, NO_MATCH, 'Undo did not restore the search text');
  await pg.sb.renderList();
  assert.ok(!pg.app().includes('ask-banner'));
});

test('on: with a name match, Enter still opens the profile and Shift+Enter asks instead', async () => {
  const pg = await ready(loadPage({ status: { local: false, ask: true }, answer: { body: ANSWER } }));
  await type(pg, 'stanford');
  assert.equal(pg.$('#qStatus').textContent, '1 match · Enter opens the first · Shift+Enter asks');
  key(pg, 'Enter', true);
  await settle();
  assert.equal(pg.askRequests().length, 1, 'Shift+Enter did not ask');
  assert.equal(pg.sb.location.hash, '', 'Shift+Enter opened the profile');
  await type(pg, 'stanford');
  key(pg, 'Enter');
  await settle();
  assert.equal(pg.sb.location.hash, '#/p/stanford');
  assert.equal(pg.askRequests().length, 1, 'Enter asked although a name matched');
});

test('on: an unsupported answer changes no filter and says why; a value the page cannot show is dropped on the way in', async () => {
  const pg = await ready(loadPage({ status: { local: false, ask: true }, answer: { body: { unsupported: 'a coach is not a filter' } } }));
  const { S } = pg.sb;
  const before = plain(S.filters);
  await type(pg, 'who coaches stanford');
  await pg.sb.askQuestion(S.qRaw);
  assert.deepEqual(plain(S.filters), before);
  assert.ok(pg.$('#askSlot').innerHTML.includes('That needs the full Q&amp;A: a coach is not a filter'), `the ask slot does not say why: "${pg.$('#askSlot').innerHTML}"`);
  const pg2 = await ready(loadPage({ status: { local: false, ask: true }, answer: { body: { ...ANSWER, conf: ['ACC', 'Gulf South'], region: ['Moon'], classYear: ['2035'],
    cond: [{ field: 'coachSince', op: '<', value: 1 }, { field: 'rpiRank', op: '<=', value: 25 }], sort: 'nope' } } }));
  await type(pg2, NO_MATCH);
  await pg2.sb.askQuestion(pg2.sb.S.qRaw);
  const f = pg2.sb.S.filters;
  assert.deepEqual(plain({ conf: f.conf, region: f.region, classYear: f.classYear, cond: f.cond, sort: f.sort }),
    { conf: ['ACC'], region: [], classYear: [], cond: [{ field: 'rpiRank', op: '<=', value: 25 }], sort: 'name' });
});

test('on: the "From your question" line disappears once the filters are changed by hand', async () => {
  const pg = await ready(loadPage({ status: { local: false, ask: true }, answer: { body: ANSWER } }));
  const { S } = pg.sb;
  await type(pg, NO_MATCH);
  await pg.sb.askQuestion(S.qRaw);
  assert.ok(S.askResult, 'no ask result');
  S.filters.region = ['West']; pg.sb.saveState();
  assert.equal(S.askResult, null);
  await pg.sb.renderList();
  assert.ok(!pg.app().includes('ask-banner'));
});
