// Issue #136: a tournament seed (opponentSeed, parsed since #135) is shown, and never looks like a national
// ranking (opponentRank, "#5"), nor with the neutral-site "(N)": it reads "5 seed" after the opponent's name.
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

test('#136 a seeded opponent shows "N seed" after its name, in words', async () => {
  const html = await sb.tabSchedule(program([game({ homeAway: 'H', opponentSeed: 5 })]));
  assert.ok(html.includes('<b>Example State</b> <span class="muted opp-seed" title="Tournament seed">5 seed</span>'),
    `the seed is not shown as "5 seed" after the name: ${html.match(/<td>vs[^]*?<\/td>/)?.[0]}`);
  assert.ok(!html.includes('#5'), 'a seed must not read like a national ranking');
});

test('#136 R1 (Huatuo): at a neutral site the seed cannot be confused with the "(N)" marker', async () => {
  const html = await sb.tabSchedule(program([game({ homeAway: 'N', opponentSeed: 3 })]));
  assert.ok(html.includes('vs (N) <b>Example State</b> <span class="muted opp-seed" title="Tournament seed">3 seed</span>'), html.match(/<td>vs[^]*?<\/td>/)?.[0]);
  assert.ok(!/\(N\)\s*(<[^>]*>)*\s*\(3\)/.test(html) && !html.includes('(3)'), 'the seed still reads as a second "(N)"-style parenthesis');
});

test('#136 R2 (Huatuo): the seed is visible words a screen reader reads, not an aria-label on a span', async () => {
  const html = await sb.tabSchedule(program([game({ opponentSeed: 4 })]));
  const span = html.match(/<span class="muted opp-seed"[^>]*>[^<]*<\/span>/)?.[0] || '';
  assert.ok(span.includes('>4 seed<'), `the seed's words are not in the text: ${span}`);
  assert.ok(!/aria-label=/.test(span), 'aria-label on a plain span is not announced');
});

test('#136 a ranking still reads "#N" exactly as before, and the two are told apart when both exist', async () => {
  const ranked = await sb.tabSchedule(program([game({ opponentRank: 7 })]));
  assert.ok(ranked.includes('<span class="muted">#7</span> <b>Example State</b>'), 'the ranking markup changed');
  assert.ok(!ranked.includes('opp-seed'), 'an unseeded game grew a seed');
  const both = await sb.tabSchedule(program([game({ opponentRank: 3, opponentSeed: 1 })]));
  assert.ok(both.includes('<span class="muted">#3</span> <b>Example State</b> <span class="muted opp-seed" title="Tournament seed">1 seed</span>'));
});

test('#136 the program glance shows the next opponent\'s seed too', () => {
  const html = sb.glanceHtml(program([game({ opponentSeed: 2 })]), {});
  assert.ok(html.includes('Example State · <span class="muted opp-seed" title="Tournament seed">2 seed</span>'), 'the glance drops the seed');
});

test('#136 no seed, or a nonsense one, adds nothing', async () => {
  for (const s of [null, 0, 'x', -3]) {
    const html = await sb.tabSchedule(program([game({ opponentSeed: s })]));
    assert.ok(!html.includes('opp-seed'), `seed ${JSON.stringify(s)} was rendered`);
  }
});
