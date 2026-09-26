// Issue #374: the schedule's venue word. Home "vs", away "at", a game the source marks neutral "vs (N)", and a
// game with no home/away value a plain "vs" - never a neutral site nobody stated.
//
//     node --test tests/venue_marker.test.mjs
//
// Same mechanism as tests/opponent_seed.test.mjs: the inline <script> of public/index.html runs in a `vm` against a
// stub DOM. VENUE_TEST_HTML points it at another copy of the page, so main's page can be shown failing. Made-up
// games only. What it cannot prove: layout.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HTML = process.env.VENUE_TEST_HTML || path.join(HERE, '..', 'public', 'index.html');

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
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector,
                querySelectorAll: () => [], addEventListener() { }, createElement: makeElement },
    location: { hash: '', replace(h) { this.hash = h; } }, history: { replaceState() { } },
    matchMedia: () => ({ matches: false }), innerWidth: 1400, addEventListener() { },
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    fetch: async () => ({ ok: false, status: 404, async json() { throw new Error('404'); } }),
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(HTML, 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n') + '\n;Object.assign(globalThis, { tabSchedule });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}

const sb = loadPage();
const program = games => ({ slug: 'example-u', name: 'Example University', seasons: [], school: {}, program: {},
  schedule: { season: 2026, games, record: { played: 0, scheduled: games.length, text: '0-0-0', confText: '0-0-0' }, history: {} } });
const cell = async homeAway => {
  const g = { date: '2099-10-01', opponent: 'Example State' };
  if (homeAway !== undefined) g.homeAway = homeAway;
  const html = await sb.tabSchedule(program([g]));
  return html.match(/<td>(vs \(N\)|vs|at) <b>Example State<\/b>/)?.[1];
};

test('#374 home reads "vs", away reads "at"', async () => {
  assert.equal(await cell('H'), 'vs');
  assert.equal(await cell('A'), 'at');
});

test('#374 a game the source marks neutral reads "vs (N)"', async () => {
  assert.equal(await cell('N'), 'vs (N)');
});

test('#374 a game with no home/away value reads plain "vs", not a neutral site', async () => {
  assert.equal(await cell(undefined), 'vs', 'a missing value is shown as neutral');
  assert.equal(await cell(null), 'vs', 'a null value is shown as neutral');
  assert.equal(await cell(''), 'vs', 'an empty value is shown as neutral');
});

test('#374 the #369 seed wording is intact beside every venue word', async () => {
  for (const [ha, word] of [['N', 'vs (N)'], [null, 'vs'], ['A', 'at']]) {
    const html = await sb.tabSchedule(program([{ date: '2099-10-02', opponent: 'Example State', homeAway: ha, opponentSeed: 3 }]));
    assert.ok(html.includes(`<td>${word} <b>Example State</b> <span class="muted opp-seed" title="Tournament seed">3 seed</span>`),
      `${JSON.stringify(ha)}: ${html.match(/<td>(vs|at)[^]*?<\/td>/)?.[0]}`);
  }
});
