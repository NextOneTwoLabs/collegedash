// "Find programs for me": results mode (issue #400, PR 4). Recommended for you on the list, Need verification, the
// reason, tradeoff and unknown chips, sort switching (A6), conflicts and empty sets (A1, A7), the stale notice and the
// fit file's load (O1).
//
//     node --test tests/recs_results.test.mjs
//     RECS_PAGE_HTML=<the PR 3 page> node --test tests/recs_results.test.mjs   # the behavioural cases fail
//
// The harness is tests/recs_page_helpers.mjs. What the list shows is checked against public/recs.js's rank() run here
// on the same list, fit file, preferences and filter (the ranker itself is tested in recs_ranker/recs_properties):
// these tests prove the PAGE shows the ranker's answer, in its order, with its numbers, and nothing else.
//
// What it CANNOT prove: layout, focus movement and real key delivery in a browser (see the PR's local check).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import { FIT, HTML, LOAD_REQUESTS, ON, ready, open, settle, plain } from './recs_page_helpers.mjs';

const R = createRequire(import.meta.url)('../public/recs.js');
const PREFS = { v: 1, region: { mode: 'prefer', values: ['West', 'Midwest'] }, division: { mode: 'must', values: ['D3'] },
  size: { mode: 'prefer', values: ['lt5k'] }, climate: { mode: 'prefer', values: ['mild'] } };
const stored = (prefs, extra = {}) => ({ 'cd.recs': JSON.stringify({ v: 1, prefs, ...extra }) });
const oracle = (pg, prefs = PREFS) => R.rank({ list: { updated: pg.sb.S.index.updated, programs: pg.sb.S.index.programs }, fit: FIT, prefs,
  filter: (p) => pg.sb.matchesFilters(p, null), hidden: [] });
const cardSlugs = (html) => [...html.matchAll(/class="card pcard[^"]*" data-slug="([^"]+)"/g)].map((m) => m[1]);
// Save through the form's own submit handler, the way the Show matches button does.
async function saveFromPanel(pg, set) {
  await open(pg);
  set(pg.sb);
  pg.panel().onsubmit({ preventDefault() { } });
  await settle();
}
const setPrefs = (prefs) => (sb) => {
  for (const c of ['region', 'division', 'size', 'climate']) {
    const q = prefs[c] || { mode: 'skip', values: [] };
    if (q.mode === 'skip') { sb.recsSetUse(c, 'skip'); continue; }
    for (const v of q.values) sb.recsToggleValue(c, v);
    sb.recsSetImportance(c, q.mode);
  }
};
async function showSaved(opts = {}) {
  const pg = await ready({ status: ON, storage: stored(opts.prefs || PREFS, opts.extra), ...opts.page });
  await pg.sb.recsShowRecommended();
  await settle();
  return pg;
}

test('page load: no recs.js and no fit file, with the switch on and preferences saved; the paused line offers them', async () => {
  const pg = await ready({ status: ON, storage: stored(PREFS) });
  assert.deepEqual([...pg.requests].sort(), [...LOAD_REQUESTS].sort());
  await pg.sb.renderList();
  assert.match(pg.app(), /Personalization paused \(sorted by Name\) · <button type="button" class="btn" id="recsResume">Show recommended<\/button>/);
  assert.deepEqual([...pg.requests].sort(), [...LOAD_REQUESTS].sort(), 'drawing the list fetched something');
});

test('no saved preferences, or the switch off: no paused line, and the sort has no Recommended option when off', async () => {
  const none = await ready({ status: ON });
  await none.sb.renderList();
  assert.ok(!/Personalization paused|recs-/.test(none.app()));
  assert.match(none.sidebar(), /<option value="recommended" >Recommended<\/option>/);
  const off = await ready({ status: { local: false }, storage: stored(PREFS) });
  await off.sb.renderList();
  assert.ok(!/Personalization paused|Recommended|recs-/.test(off.app() + off.sidebar()));
});

test('Show matches ranks: the fit file is fetched once, then the list is Recommended for you, in the ranker\'s order', async () => {
  const pg = await ready({ status: ON });
  const before = pg.requests.length;
  await saveFromPanel(pg, setPrefs(PREFS));
  assert.deepEqual(pg.requests.slice(before), ['recs.js', '/api/v1/fit']);
  assert.equal(pg.sb.S.recs.active, true);
  assert.equal(pg.panel().hidden, true, 'the panel stays open over the results');
  const res = oracle(pg);
  const html = pg.app();
  assert.match(html, /Recommended for you/);
  assert.match(html, new RegExp(`${res.confirmed.length} confirmed matches`));
  assert.match(html, /<b>4 preferences:<\/b> Region: West or Midwest \(prefer\) · Division: D3 \(must have\) · School size: under 5,000 undergraduates \(prefer\) · Climate: mild winters \(prefer\)/);
  assert.deepEqual(cardSlugs(html), res.confirmed.slice(0, 25).map((x) => x.slug));
  assert.equal(pg.$('#recsCount').textContent, `Showing 25 of ${res.confirmed.length} confirmed matches`);
  assert.ok(!html.includes('id="recsCount"'), 'the count is redrawn inside #app');
  assert.match(html, /id="recsMore">Show 25 more<\/button>/);
  assert.equal(pg.$('#sortSelect').value, 'recommended', 'the sort select does not show Recommended');
  pg.sb.renderSidebar();
  assert.match(pg.sidebar(), /<option value="recommended" selected>Recommended<\/option>/);
  await pg.sb.renderList();
  assert.equal(pg.requests.filter((u) => u === '/api/v1/fit').length, 1, 'the fit file was fetched again');
});

test('the chips: reasons, a tradeoff and unknowns from the ranker, each with its source; no match percentage', async () => {
  const pg = await showSaved();
  const res = oracle(pg);
  const html = pg.app();
  const first = res.confirmed[0];
  const card = html.slice(html.indexOf(`data-slug="${first.slug}"`), html.indexOf('class="foot"', html.indexOf(`data-slug="${first.slug}"`)));
  for (const r of first.reasons) {
    assert.ok(card.includes(`<span class="sr-only">Matches: </span>${R.reasonText(r).replace(/&/g, '&amp;')}`), R.reasonText(r));
    assert.ok(card.includes(`title="Source: ${r.source.name}${r.source.asOf ? `, fetched ${r.source.asOf}` : ''}"`), 'reason source');
  }
  const withTrade = res.confirmed.slice(0, 25).find((x) => x.tradeoff);
  assert.ok(withTrade, 'the first page has a tradeoff to check');
  assert.ok(html.includes(`Tradeoff: ${R.tradeoffText(withTrade.tradeoff)}`));
  const withUnknown = res.confirmed.slice(0, 25).find((x) => x.unknowns.length) || res.needVerification[0];
  if (withUnknown) assert.ok(html.includes(R.unknownText(withUnknown.unknowns[0])), 'unknown chip');
  // D2 (owner, #415 review): a climate chip gives the figure AND the station distance.
  const mild = res.confirmed.slice(0, 25).flatMap((x) => x.reasons).find((r) => r.category === 'climate');
  assert.ok(mild, 'the first page has a climate reason to check');
  assert.ok(html.includes(`coldest month averages ${mild.detail.coldMonthMeanF}°F (weather station ${mild.detail.stationKm} km away)`), 'the climate chip leaves out the station distance');
  assert.ok(!/\d\s?%/.test(html.replace(/<[^>]+>/g, ' ').replace(/admission rate[^<]*/gi, '')), 'a percentage is shown');
});

test('Show 25 more adds the next 25 in order and says how many are showing', async () => {
  const pg = await showSaved();
  const res = oracle(pg);
  await pg.$('#recsMore').onclick();
  await settle();
  assert.deepEqual(cardSlugs(pg.app()), res.confirmed.slice(0, 50).map((x) => x.slug));
  assert.equal(pg.$('#recsCount').textContent, `Showing 50 of ${res.confirmed.length} confirmed matches`);
});

test('A2: Need verification is its own collapsed group, with the ranker\'s programs and their division tags', async () => {
  const prefs = { v: 1, region: { mode: 'must', values: ['Northeast'] } };
  const pg = await showSaved({ prefs });
  const res = oracle(pg, prefs);
  assert.ok(res.needVerification.length > 0, 'the catalog has programs with no region');
  const html = pg.app();
  assert.match(html, new RegExp(`<details class="recs-nv card"><summary>Need verification \\(${res.needVerification.length}\\)`));
  const nv = html.slice(html.indexOf('<details class="recs-nv'));
  for (const it of res.needVerification) {
    assert.ok(nv.includes(`href="#/p/${it.slug}"`), it.slug);
    assert.match(nv.slice(nv.indexOf(`href="#/p/${it.slug}"`)), /^[^]*?class="div-tag"[^>]*>D[123]<\/span>/);
  }
  assert.ok(!cardSlugs(html).some((s) => res.needVerification.some((x) => x.slug === s)), 'a Need verification program among the confirmed');
  assert.match(html, /Region unknown: no College Scorecard record/);
});

test('A6: Recommended, then Name, then Recommended: the ordinary list in between, the same result after', async () => {
  const pg = await showSaved();
  const first = pg.app();
  const sel = pg.$('#sortSelect');
  pg.sb.renderSidebar();
  sel.onchange({ target: { value: 'name' } });
  await settle();
  assert.equal(pg.sb.S.recs.active, false);
  assert.equal(pg.sb.S.filters.sort, 'name');
  assert.equal(pg.sb.S.filters.sortDir, null, 'picking the sort underneath flipped its direction');
  const browse = pg.app();
  assert.match(browse, /Personalization paused \(sorted by Name\)/);
  assert.ok(!/recs-why|Need verification|Recommended for you/.test(browse));
  assert.deepEqual(cardSlugs(browse), pg.sb.filteredPrograms().map((p) => p.slug), 'not the ordinary browse list');
  assert.equal(cardSlugs(browse).length, pg.sb.S.index.programs.length, 'must-haves still applied while paused');
  sel.onchange({ target: { value: 'recommended' } });
  await settle();
  assert.equal(pg.app(), first);
  assert.ok(!(pg.store.get('cd.filters') || '').includes('recommended'), 'Recommended was stored as a sort');
});

test('A4: an all-Skip save never enters Recommended mode', async () => {
  const pg = await ready({ status: ON });
  await saveFromPanel(pg, () => { });
  assert.equal(pg.sb.S.recs.active, false);
  assert.ok(!pg.requests.includes('/api/v1/fit'));
  await pg.sb.renderList();
  assert.ok(!/for you/i.test(pg.app()));
});

test('A1: a D1 filter against a D3 must-have says both, offers to remove the filter, and relaxes nothing', async () => {
  const prefs = { v: 1, division: { mode: 'must', values: ['D3'] } };
  const pg = await ready({ status: ON, storage: { ...stored(prefs), 'cd.filters': JSON.stringify({ division: ['D1'] }) } });
  await pg.sb.recsShowRecommended(); await settle();
  const html = pg.app();
  assert.match(html, /<b>No programs can match:<\/b> your filter keeps only D1, and your must-have keeps only D3\./);
  assert.match(html, /data-recs-unfilter="division">Remove the D1 filter<\/button>/);
  assert.deepEqual(plain(pg.sb.S.filters.division), ['D1']);
  assert.deepEqual(plain(pg.sb.S.recs.saved.division), { mode: 'must', values: ['D3'] });
  assert.deepEqual(cardSlugs(html), []);
  pg.sb.recsUnfilter('division'); await settle();
  assert.equal(cardSlugs(pg.app()).length, 25);
});

test('A7: an empty set names every cause with its count; per-must-have counts are listed, never added up', async () => {
  const prefs = { v: 1, region: { mode: 'must', values: ['Northeast'] }, division: { mode: 'must', values: ['D3'] }, size: { mode: 'must', values: ['ge15k'] } };
  const pg = await showSaved({ prefs });
  const res = oracle(pg, prefs);
  assert.equal(res.confirmed.length, 0);
  const ex = res.excluded, cats = ex.byMustHaveCategory;
  const sum = cats.region + cats.division + cats.size;
  assert.notEqual(sum, ex.byMustHave, 'the case must tell a sum from the total');
  const text = pg.app().replace(/<[^>]+>/g, '');
  assert.match(text, new RegExp(`your must-haves rule out ${ex.byMustHave.toLocaleString('en-US')} programs`, 'i'));
  for (const [c, words] of [['region', 'Region: Northeast'], ['division', 'Division: D3'], ['size', 'School size: 15,000\\+ undergraduates']]) {
    assert.match(text, new RegExp(`“${words}” rules out ${cats[c].toLocaleString('en-US')}`));
  }
  assert.match(text, /a program can fail more than one/);
  assert.ok(!text.includes(sum.toLocaleString('en-US')), 'the per-category counts were added up');
  assert.match(text, new RegExp(`${res.needVerification.length} programs? needs? verification \\(below\\)`));
});

test('A7: filters and search are named as a cause, with Clear filters', async () => {
  const prefs = { v: 1, size: { mode: 'must', values: ['ge15k'] } };
  const pg = await ready({ status: ON, storage: { ...stored(prefs), 'cd.filters': JSON.stringify({ region: ['Northeast'], division: ['D3'] }) } });
  await pg.sb.recsShowRecommended(); await settle();
  const res = oracle(pg, prefs);
  assert.equal(res.confirmed.length, 0);
  const text = pg.app().replace(/<[^>]+>/g, '');
  assert.match(text, new RegExp(`Your filters leave ${res.total - res.excluded.byFilter} programs of ${res.total.toLocaleString('en-US')}`));
  assert.match(pg.app(), /data-recs-unfilter="all">Clear filters<\/button>/);
});

test('stale: results computed under other versions are recomputed and say so; the new stamp is saved', async () => {
  const old = { taxonomy: 'fit-1', ranker: 'r0', catalog: '2026-01-01T00:00:00Z' };
  const pg = await showSaved({ extra: { applied: old } });
  assert.match(pg.app(), /Program data has been updated since you set these preferences; the results are recomputed\./);
  assert.deepEqual(JSON.parse(pg.store.get('cd.recs')).applied, { taxonomy: 'fit-1', ranker: R.RANKER, catalog: FIT.updated });
  const again = await showSaved({ extra: { applied: { taxonomy: 'fit-1', ranker: R.RANKER, catalog: FIT.updated } } });
  assert.ok(!/Program data has been updated/.test(again.app()));
});

for (const [fit, words, requests] of [['missing', 'Recommendations need school and climate data, which didn’t load.', 1],
  ['network', 'Recommendations need school and climate data, which didn’t load.', 1], ['updating', 'Program data is updating; try again in a minute.', 2]]) {
  test(`O1: a fit file that is ${fit} leaves the ordinary list, says why, and offers Try again`, async () => {
    const pg = await showSaved({ page: { fit } });
    assert.equal(pg.sb.S.recs.active, false);
    assert.equal(pg.requests.filter((u) => u === '/api/v1/fit').length, requests);
    assert.ok(pg.app().includes(`role="alert">${words} <button type="button" class="btn" id="recsResume">Try again</button>`));
    assert.ok(!/Recommended for you|recs-why/.test(pg.app()));
    assert.equal(cardSlugs(pg.app()).length, pg.sb.S.index.programs.length, 'the ordinary list is not shown');
  });
}

test('a fit file from another build is fetched once more, and used when it then agrees', async () => {
  const pg = await showSaved({ page: { fit: 'updating-once' } });
  assert.equal(pg.requests.filter((u) => u === '/api/v1/fit').length, 2);
  assert.equal(pg.sb.S.recs.active, true);
  assert.match(pg.app(), /Recommended for you/);
});

test('the Stats view in Recommended mode lists the confirmed programs in the ranker\'s order', async () => {
  const pg = await ready({ status: ON, storage: { ...stored(PREFS), 'cd.filters': JSON.stringify({ view: 'table' }) } });
  await pg.sb.recsShowRecommended(); await settle();
  const res = oracle(pg);
  const rows = [...pg.app().matchAll(/<tr class="team-row[^"]*" data-slug="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(rows, res.confirmed.slice(0, 25).map((x) => x.slug));
});

test('filters and search narrow the recommendations as their own layer', async () => {
  const pg = await ready({ status: ON, storage: { ...stored(PREFS), 'cd.filters': JSON.stringify({ region: ['West'] }) } });
  await pg.sb.recsShowRecommended(); await settle();
  const res = oracle(pg);
  assert.ok(res.excluded.byFilter > 0);
  assert.deepEqual(cardSlugs(pg.app()), res.confirmed.slice(0, 25).map((x) => x.slug));
  assert.match(pg.app(), /West region/);
});

test('the count line is one persistent live node in the page markup, cleared when the ordinary list returns', async () => {
  const page = fs.readFileSync(HTML, 'utf8');
  // Static markup after #app (other persistent nodes may sit between them), never drawn by a render.
  // After the END of #app's own line: inside #app it would be wiped by the next render (#417 review re-anchor).
  const appLineEnd = page.indexOf('\n', page.indexOf('<div id="app">')), script = page.indexOf('<script>');
  const at = page.indexOf('<p class="sr-only" id="recsCount" role="status" aria-live="polite"></p>');
  assert.ok(appLineEnd > 0 && at > appLineEnd && at < script, 'not a static node after #app');
  assert.equal(page.split('id="recsCount"').length, 2, 'the count node is also drawn by a render');
  const pg = await showSaved();
  assert.match(pg.$('#recsCount').textContent, /^Showing 25 of \d+ confirmed matches$/);
  pg.$('#sortSelect').onchange({ target: { value: 'name' } }); await settle();
  assert.equal(pg.$('#recsCount').textContent, '');
});

test('the Stats view in Recommended mode claims no column sort (no aria-sort, no active header)', async () => {
  const pg = await ready({ status: ON, storage: { ...stored(PREFS), 'cd.filters': JSON.stringify({ view: 'table', sort: 'name' }) } });
  await pg.sb.recsShowRecommended(); await settle();
  assert.ok(!/aria-sort=|sort-active/.test(pg.app()), 'a column claims to sort the ranked rows');
});
