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
//
// What it CANNOT prove: layout at 320-1280 px (see the PR's Playwright check).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { FIT, ON, ready, open, settle } from './recs_page_helpers.mjs';

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
      assert.equal(shown.split(n).length - 1, 1, `${it.slug}: "${n}" once`);
      if (s.asOf) assert.ok(shown.includes(`${n}, fetched ${s.asOf}`), `${it.slug}: ${n} with its date`);
    }
    if (names.includes('College Scorecard')) assert.ok(line[1].includes('<a href="https://collegescorecard.ed.gov/" target="_blank" rel="noopener">College Scorecard</a>'), 'Scorecard links');
    if (names.some((n) => n.startsWith('NOAA'))) assert.match(line[1], /<a href="https:\/\/www\.ncei\.noaa\.gov\/products\/land-based-station\/us-climate-normals" target="_blank" rel="noopener">NOAA/);
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
