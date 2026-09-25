// Issue #136: a tournament seed (opponentSeed, parsed since #135) is shown, and never looks like a national
// ranking (opponentRank, "#5"). The seed reads "(5)" and names itself on hover and to a screen reader.
//
//     node --test tests/opponent_seed.test.mjs
//
// Same mechanism as tests/camps_view.test.mjs: the inline <script> of public/index.html runs in a `vm` against a
// stub DOM. SEED_TEST_HTML points it at another copy of the page, so main's page can be shown failing.
// Made-up games only. What it cannot prove: layout. The DOM is a stub.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.SEED_TEST_HTML || path.join(PUBLIC, 'index.html');

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
const future = '2099-11-01';
const game = (extra) => ({ date: future, homeAway: 'N', opponent: 'Example State', ...extra });
const program = games => ({
  slug: 'example-u', name: 'Example University', seasons: [], school: {}, program: {},
  schedule: { season: 2026, games, record: { played: 0, scheduled: games.length, text: '0-0-0', confText: '0-0-0' }, history: {} },
});

test('#136 a seeded opponent shows its seed, marked as a tournament seed', async () => {
  const html = await sb.tabSchedule(program([game({ opponentSeed: 5 })]));
  assert.ok(html.includes('(5)'), 'the seed is not shown');
  assert.ok(html.includes('title="Tournament seed 5"') && html.includes('aria-label="tournament seed 5"'), 'the seed does not say what it is');
  assert.ok(!html.includes('#5'), 'a seed must not read like a national ranking');
});

test('#136 a ranking still reads "#N" exactly as before, and the two are told apart when both exist', async () => {
  const ranked = await sb.tabSchedule(program([game({ opponentRank: 7 })]));
  assert.ok(ranked.includes('<span class="muted">#7</span> <b>Example State</b>'), 'the ranking markup changed');
  assert.ok(!ranked.includes('Tournament seed'), 'an unseeded game grew a seed');
  const both = await sb.tabSchedule(program([game({ opponentRank: 3, opponentSeed: 1 })]));
  assert.ok(both.includes('#3') && both.includes('(1)') && both.includes('Tournament seed 1'));
});

test('#136 the program glance shows the next opponent\'s seed too', () => {
  const html = sb.glanceHtml(program([game({ opponentSeed: 2 })]), {});
  assert.ok(html.includes('title="Tournament seed 2"'), 'the glance drops the seed');
});

test('#136 no seed, or a nonsense one, adds nothing', async () => {
  for (const s of [null, 0, 'x', -3]) {
    const html = await sb.tabSchedule(program([game({ opponentSeed: s })]));
    assert.ok(!html.includes('Tournament seed'), `seed ${JSON.stringify(s)} was rendered`);
  }
});
