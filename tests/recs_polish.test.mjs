// "Find programs for me": three fixes found in the release walkthrough (issue #400).
//
//     node --test tests/recs_polish.test.mjs
//
// The harness is tests/recs_page_helpers.mjs (the page's inline script in a `vm` with a stub DOM). Offline.
//
// What this proves:
//   1. Each reason's source and fetch date are visible text, not only a hover title: a "Sources:" line under the
//      chips names every source the card's reasons and tradeoff use, once each, with its date, and links to the
//      source's own page where the site already links one (College Scorecard, NOAA's climate normals). A phone has no
//      hover, so a title alone showed nothing there. Screen readers read the line once, so the chips no longer
//      carry a hidden "(source: ...)" of their own.
//   2. A tradeoff chip is announced "Tradeoff: ..." once, not "Tradeoff: Tradeoff: ...".
//   3. The "Choose at least one preference" message (A4) goes away as soon as a preference is picked, instead of
//      staying on screen until the next save.
//   4. A returning visitor with saved preferences gets the "Personalization paused · Show recommended" line even when
//      api/status answers after the page has drawn the list (a browser's usual order). The test holds the answer back
//      and never redraws the list itself, so it fails exactly when switching on doesn't redraw it.
//   5. The NOAA source reads "NOAA climate normals" on the card, and those words are its accessible name (WCAG 2.5.3);
//      the full name is its title. It doesn't wrap to three lines at 320 px.
//
// What it CANNOT prove: layout at 320-1280 px (see the PR's Playwright check).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { FIT, ON, loadPage, ready, open, settle } from './recs_page_helpers.mjs';

const R = createRequire(import.meta.url)('../public/recs.js');
const PREFS = { v: 1, region: { mode: 'prefer', values: ['West', 'Midwest'] }, division: { mode: 'must', values: ['D3'] },
  size: { mode: 'prefer', values: ['lt5k'] }, climate: { mode: 'prefer', values: ['mild'] } };
const stored = (prefs) => ({ 'cd.recs': JSON.stringify({ v: 1, prefs }) });
const oracle = (pg, prefs = PREFS) => R.rank({ list: { updated: pg.sb.S.index.updated, programs: pg.sb.S.index.programs }, fit: FIT, prefs,
  filter: (p) => pg.sb.matchesFilters(p, null), hidden: [] });
async function showSaved(prefs = PREFS) {
  const pg = await ready({ status: ON, storage: stored(prefs) });
  await pg.sb.recsShowRecommended();
  await settle();
  return pg;
}
const cardOf = (html, slug) => { const a = html.indexOf(`data-slug="${slug}"`); return html.slice(a, html.indexOf('class="foot"', a)); };
// What a screen reader reads: drop aria-hidden spans and tags, keep sr-only text.
const spoken = (h) => h.replace(/<span aria-hidden="true">[^<]*<\/span>/g, '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ');

test('1: a visible Sources line names each source of the card\'s reasons and tradeoff once, with its date and link', async () => {
  const pg = await showSaved();
  const res = oracle(pg);
  const html = pg.app();
  const items = res.confirmed.slice(0, 25);
  const withTrade = items.find((x) => x.tradeoff);
  assert.ok(withTrade, 'the first page has a tradeoff to check');
  for (const it of [items[0], withTrade]) {
    const card = cardOf(html, it.slug);
    const line = /<p class="recs-src">Sources: ([\s\S]*?)<\/p>/.exec(card);
    assert.ok(line, `${it.slug}: a visible Sources line`);
    const srcs = [...it.reasons, ...(it.tradeoff ? [it.tradeoff] : [])].map((c) => c.source);
    const names = [...new Set(srcs.map((s) => s.name))];
    for (const n of names) {
      const s = srcs.find((x) => x.name === n);
      const shown = line[1].replace(/<[^>]+>/g, '');
      const label = n.startsWith('NOAA') ? 'NOAA climate normals' : n; // the short label (test 5); the full name is its accessible name
      assert.equal(shown.split(label).length - 1, 1, `${it.slug}: "${label}" once`);
      if (s.asOf) assert.ok(shown.includes(`${label}, fetched ${s.asOf}`), `${it.slug}: ${label} with its date`);
    }
    if (names.includes('College Scorecard')) assert.ok(line[1].includes('<a href="https://collegescorecard.ed.gov/" target="_blank" rel="noopener">College Scorecard</a>'), 'Scorecard links');
    if (names.some((n) => n.startsWith('NOAA'))) assert.match(line[1], /<a href="https:\/\/www\.ncei\.noaa\.gov\/products\/land-based-station\/us-climate-normals" target="_blank" rel="noopener"[^>]*>NOAA/);
    assert.ok(!/<span class="sr-only"> \(source: /.test(card), `${it.slug}: no hidden per-chip source left to read twice`);
    assert.ok(!line[0].includes('sr-only'), 'the line itself is visible text');
  }
});

test('2: a tradeoff is announced "Tradeoff:" once', async () => {
  const pg = await showSaved();
  const withTrade = oracle(pg).confirmed.slice(0, 25).find((x) => x.tradeoff);
  const chip = /<li class="recs-chip trade"[\s\S]*?<\/li>/.exec(cardOf(pg.app(), withTrade.slug))[0];
  const text = spoken(chip);
  assert.equal(text.split('Tradeoff:').length - 1, 1, text);
  assert.ok(text.includes(`Tradeoff: ${R.tradeoffText(withTrade.tradeoff)}`), text);
});

test('3: the A4 message goes away as soon as a preference is picked', async () => {
  const A4 = 'Choose at least one preference to get recommendations.';
  for (const pick of [(sb) => sb.recsToggleValue('region', 'West'), (sb) => sb.recsSetUse('size', 'choose')]) {
    const pg = await ready({ status: ON });
    await open(pg);
    assert.equal(pg.sb.recsApply(), false);
    pg.sb.renderRecsPanel();
    assert.equal(pg.$('#recsStatus').textContent, A4);
    pick(pg.sb);
    pg.sb.renderRecsPanel();
    assert.equal(pg.sb.S.recs.status, '', 'the message is cleared in state');
    assert.equal(pg.$('#recsStatus').textContent, '', 'and on screen');
  }
  // any other status ("Preferences saved.") is left alone by a pick
  const pg = await ready({ status: ON });
  await open(pg);
  pg.sb.S.recs.status = 'Preferences saved.';
  pg.sb.recsToggleValue('region', 'West');
  assert.equal(pg.sb.S.recs.status, 'Preferences saved.');
});

test('4: a returning visitor\'s list offers their saved preferences even when api/status answers after the list is drawn', async () => {
  // No renderList after load: the page draws the list itself, then the switch arrives, as in a browser.
  let answer;
  const gate = new Promise((r) => { answer = r; });
  const pg = loadPage({ hash: '#/programs', status: ON, storage: stored(PREFS), statusGate: gate });
  await settle();
  if (!pg.sb.S.index) await pg.sb.loadIndex();
  await settle();
  assert.match(pg.app(), /class="card pcard/, 'the list is drawn before the switch arrives');
  assert.ok(!/recsResume/.test(pg.app()), 'nothing about recommendations before the switch');
  answer();
  await settle();
  assert.equal(pg.sb.S.recs.on, true, 'the switch arrived');
  assert.match(pg.app(), /Personalization paused \(sorted by Name\) · <button type="button" class="btn" id="recsResume">Show recommended<\/button>/,
    'the list was redrawn with the saved preferences on offer');
});

test('5: the NOAA source reads "NOAA climate normals", which is also its accessible name; the full name is its title', async () => {
  const pg = await showSaved();
  const html = pg.app();
  const m = /<a href="https:\/\/www\.ncei\.noaa\.gov\/products\/land-based-station\/us-climate-normals" target="_blank" rel="noopener"([^>]*)>([^<]*)<\/a>/.exec(html);
  assert.ok(m, 'a NOAA link');
  assert.equal(m[2], 'NOAA climate normals');
  assert.equal(m[1], ` title="${FIT.sources.climate.name}"`, 'the full name is the title, and nothing else is set');
  // WCAG 2.5.3 Label in Name: no aria-label, so the accessible name is the visible text itself
  assert.ok(!/aria-label/.test(m[1]), 'an aria-label would replace the visible words as the accessible name');
});

// A browser's focus, modelled on the stub DOM (Huatuo's round-2 repro, scratchpad huatuo400/focus-table.cjs): setting
// #app's innerHTML replaces every element in it, and focus on a replaced element falls to <body>. getElementById
// finds the element the current #app markup draws, a new one after each redraw.
function focusModel(pg) {
  const doc = pg.sb.document, app = pg.$('#app');
  let html = app.innerHTML, gen = 0, draws = 0;
  const live = new Map();
  const el = (id) => {
    const key = `${gen}:${id}`;
    if (!live.has(key)) {
      const e = { id, gen, closest: (s) => (s === '#app' ? app : null), focus() { doc.activeElement = this; } };
      Object.defineProperty(e, 'isConnected', { get: () => e.gen === gen });
      live.set(key, e);
    }
    return live.get(key);
  };
  Object.defineProperty(app, 'innerHTML', { get: () => html, set: (v) => {
    html = v; gen += 1; draws += 1;
    if (doc.activeElement && doc.activeElement.isConnected === false) doc.activeElement = doc.body;
  } });
  doc.getElementById = (id) => (html.includes(`id="${id}"`) ? el(id) : null);
  doc.contains = (e) => e === doc.body || !!(e && e.isConnected);
  return { draws: () => draws, el };
}
async function heldSwitch({ prefs }) {
  let answer;
  const gate = new Promise((r) => { answer = r; });
  const storage = { 'cd.filters': JSON.stringify({ view: 'table' }), ...(prefs ? stored(prefs) : {}) };
  const pg = loadPage({ hash: '#/programs', status: ON, storage, statusGate: gate });
  await settle();
  if (!pg.sb.S.index) await pg.sb.loadIndex();
  await settle();
  assert.match(pg.app(), /id="moreStats"/, 'the table is drawn before the switch arrives');
  return { pg, answer };
}

test('6: a focused control in the list keeps focus when the switch arrives and the list is redrawn (table view)', async () => {
  const { pg, answer } = await heldSwitch({ prefs: PREFS });
  const fm = focusModel(pg);
  const old = pg.sb.document.getElementById('moreStats');
  old.focus();
  const before = fm.draws();
  answer();
  await settle();
  assert.equal(pg.sb.S.recs.on, true, 'the switch arrived');
  assert.ok(fm.draws() > before, 'the list was redrawn for the saved preferences');
  const now = pg.sb.document.activeElement;
  assert.notEqual(now, pg.sb.document.body, 'focus did not fall to <body>');
  assert.equal(now.id, 'moreStats', 'focus is on #moreStats');
  assert.notEqual(now, old, 'on the new #moreStats, the one the redraw drew');
  assert.equal(now.isConnected, true);
});

test('6b: with no saved preferences the switch does not redraw the list, and focus stays where it was', async () => {
  const { pg, answer } = await heldSwitch({ prefs: null });
  const fm = focusModel(pg);
  const old = pg.sb.document.getElementById('moreStats');
  old.focus();
  const before = fm.draws();
  answer();
  await settle();
  assert.equal(pg.sb.S.recs.on, true, 'the switch arrived');
  assert.equal(fm.draws(), before, 'nothing to offer, so no redraw');
  assert.equal(pg.sb.document.activeElement, old, 'focus is untouched');
});
