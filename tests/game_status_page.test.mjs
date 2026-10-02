// Issue #24: a game the school marks canceled or postponed carries `status` (collect/common.py game_status), and
// build.py leaves it out of `record.scheduled` and counts it in `record.notPlayed`. The page:
//   * names it in the result cell, "Canceled" or "Postponed", whatever its date and in history rows too - never
//     "result pending", "upcoming" or "not recorded";
//   * leaves it out of "N pending" and says "N canceled or postponed" in the season line;
//   * never offers it as the program glance's "Next match" (Bianque's required change: a game canceled in advance
//     would otherwise be named as the next match).
//
//     node --test tests/game_status_page.test.mjs
//
// Same mechanism as tests/opponent_seed.test.mjs: the inline <script> of public/index.html runs in a `vm` against a
// stub DOM. GAME_STATUS_TEST_HTML points it at another copy of the page, so main's page can be shown failing.
// Made-up games only. What it cannot prove: layout. The DOM is a stub.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.GAME_STATUS_TEST_HTML || path.join(PUBLIC, 'index.html');

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
  const src = lines.slice(a + 1, b).join('\n') + '\n;Object.assign(globalThis, { S, tabSchedule, glanceHtml, todayLocal });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}

const sb = loadPage();
const PAST = '2001-09-01', FUTURE = '2099-09-01', LATER = '2099-09-08';
const game = (opponent, extra) => ({ date: PAST, homeAway: 'H', opponent, links: {}, ...extra });
// record as build.py writes it for these games: 2 played (W, L), 4 scheduled (W, L, the pending one, the future one),
// 3 canceled or postponed (two past, one future), 1 exhibition
const GAMES = [
  game('Northfield College', { result: 'W', score: '2-1' }),
  game('Lakeside University', { result: 'L', score: '0-1' }),
  game('Riverton State', { status: 'canceled' }),
  game('Hillcrest College', { status: 'postponed' }),
  game('Easton College', {}),
  game('Brookfield College', { exhibition: true, status: 'canceled' }),
  game('Westfield College', { date: FUTURE, status: 'canceled' }),
  game('Southport College', { date: FUTURE }),
];
const program = (games, record, history = {}) => ({
  slug: 'example-u', name: 'Example University', seasons: [], school: {}, program: {},
  schedule: { season: 2026, games, record, history },
});
const RECORD = { played: 2, scheduled: 4, notPlayed: 3, text: '1-1-0', confText: null, exhibitions: 1 };
const cell = (html, opp) => html.match(new RegExp(`<b>${opp}</b>[^]*?</td>[^]*?</td>\\s*<td>([^]*?)</td>`))?.[1] || '';

test('#24 the result cell names a canceled or postponed game in the school\'s word, past or future', async () => {
  const html = await sb.tabSchedule(program(GAMES, RECORD));
  assert.match(cell(html, 'Riverton State'), />Canceled</, cell(html, 'Riverton State'));
  assert.match(cell(html, 'Hillcrest College'), />Postponed</, cell(html, 'Hillcrest College'));
  assert.match(cell(html, 'Westfield College'), />Canceled</, `a future canceled game read: ${cell(html, 'Westfield College')}`);
  assert.match(cell(html, 'Brookfield College'), />Canceled</, `an exhibition with a status read: ${cell(html, 'Brookfield College')}`);
  for (const opp of ['Riverton State', 'Hillcrest College', 'Westfield College'])
    assert.ok(!/result pending|upcoming|not recorded/.test(cell(html, opp)), `${opp}: ${cell(html, opp)}`);
});

test('#24 GUARD: a game with no status reads exactly as before', async () => {
  const html = await sb.tabSchedule(program(GAMES, RECORD));
  assert.match(cell(html, 'Easton College'), />result pending</);
  assert.match(cell(html, 'Southport College'), />upcoming</);
  assert.match(cell(html, 'Northfield College'), />W<\/b> 2-1/);
});

test('#24 the season line: pending leaves status games out, and they are counted as canceled or postponed', async () => {
  const html = await sb.tabSchedule(program(GAMES, RECORD));
  const line = html.match(/<span class="muted small">\(([^)]*)\)<\/span><\/h3>/)?.[1] || '';
  assert.equal(line, '2 of 4 played, 1 pending, 3 canceled or postponed, 1 exhibition excluded', line);
});

test('#24 a history row with a status reads Canceled, not "not recorded"', async () => {
  const hist = { 2025: { record: '1-0-0', games: [game('Northfield College', { date: '2025-09-01', result: 'W', score: '1-0' }),
    game('Riverton State', { date: '2025-09-05', status: 'canceled' }), game('Easton College', { date: '2025-09-09' })] } };
  const html = await sb.tabSchedule(program([], { played: 0, scheduled: 0, text: '0-0-0' }, hist));
  const details = html.slice(html.indexOf('<details'));
  assert.match(cell(details, 'Riverton State'), />Canceled</, cell(details, 'Riverton State'));
  assert.match(cell(details, 'Easton College'), />not recorded</, 'GUARD: an unscored history row without a status reads as before');
});

test('#24 (Bianque): a game canceled in advance is not the glance panel\'s next match', () => {
  const html = sb.glanceHtml(program([game('Westfield College', { date: FUTURE, status: 'canceled' }),
    game('Southport College', { date: LATER })], RECORD), {});
  const next = html.match(/<div class="glance-next-opp[^"]*">([^]*?)<\/div>/)?.[1] || '';
  assert.ok(next.includes('Southport College') && !next.includes('Westfield'), `next match: ${next}`);
});

test('#24 (Bianque): with only a canceled or postponed game ahead, the panel says no upcoming match', () => {
  for (const status of ['canceled', 'postponed']) {
    const html = sb.glanceHtml(program([game('Westfield College', { date: FUTURE, status }),
      game('Northfield College', { result: 'W', score: '2-1' })], RECORD), {});
    const next = html.match(/<div class="glance-next-opp[^"]*">([^]*?)<\/div>/)?.[1] || '';
    assert.equal(next, 'No upcoming match listed', `${status}: ${next}`);
  }
});

test('#24 GUARD: a normal future game is still the next match', () => {
  const html = sb.glanceHtml(program([game('Southport College', { date: FUTURE })], RECORD), {});
  assert.ok((html.match(/<div class="glance-next-opp[^"]*">([^]*?)<\/div>/)?.[1] || '').includes('Southport College'));
});
