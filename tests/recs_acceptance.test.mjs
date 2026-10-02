// The PRD's acceptance cases A1-A12 for "Find programs for me" (issue #400, PR 7): one named test each, as the plan's
// table maps them (revision 2, §F). Most are page tests on the shared harness (tests/recs_page_helpers.mjs); A3 and A8
// are unit tests of public/recs.js, as the plan says. Several cases are also covered piecemeal by the PR 3-6 suites;
// these are the end-to-end statements of each case, in the PRD's own terms. Offline.
//
// A12's "optional LLM timeout" is not applicable to V1: there is no LLM input (the owner deferred it, #400 decision
// comment; free text is #402). The test says so in its name and checks the rest of A12.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { FIT, FOCUS, ON, ready, loadPage, open, settle, plain, CATALOG, toastHtml } from './recs_page_helpers.mjs';
import { row, entry, tinyCatalog, prefs as mk } from './recs_helpers.mjs';

const R = createRequire(import.meta.url)('../public/recs.js');
const doc = (pg) => JSON.parse(pg.store.get('cd.recs'));
const cardSlugs = (html) => [...html.matchAll(/class="card pcard[^"]*" data-slug="([^"]+)"/g)].map((m) => m[1]);
const oracle = (pg, extra = {}) => R.rank({ list: { updated: pg.sb.S.index.updated, programs: pg.sb.S.index.programs }, fit: FIT,
  prefs: pg.sb.S.recs.saved, filter: (p) => pg.sb.matchesFilters(p, null), hidden: pg.sb.S.recs.hidden.map((h) => h.slug), ...extra });
const saved = (prefs, more = {}) => ({ 'cd.recs': JSON.stringify({ v: 1, prefs, notices: { sharedDevice: true }, ...more }) });
async function recommend(storage, page = {}) {
  const pg = await ready({ status: ON, storage, ...page });
  await pg.sb.recsShowRecommended(); await settle();
  return pg;
}
const text = (html) => html.replace(/<[^>]+>/g, '');

test('A1 combined conflict: a D1 filter and a D3 must-have give no matches; both stay visible; neither is relaxed', async () => {
  const pg = await recommend({ ...saved({ v: 1, division: { mode: 'must', values: ['D3'] } }), 'cd.filters': JSON.stringify({ division: ['D1'] }) });
  assert.deepEqual(cardSlugs(pg.app()), []);
  assert.match(pg.app(), /No programs can match:<\/b> your filter keeps only D1, and your must-have keeps only D3\./);
  assert.match(pg.app(), /Division: D3 \(must have\)/, 'the preference summary is not visible');
  // #465 D: on Programs the Division pills are the toolbar's, above the results
  assert.match(pg.app(), /data-division="D1" aria-pressed="true"/, 'the D1 filter is not visible as on');
  assert.deepEqual(plain(pg.sb.S.filters.division), ['D1']);
  assert.deepEqual(doc(pg).prefs.division, { mode: 'must', values: ['D3'] });
  assert.match(pg.app(), /data-recs-unfilter="division">Remove the D1 filter<\/button>/, 'removing one is not offered as an explicit action');
});

test('A2 unknown mandatory: must Northeast puts the programs with no region in Need verification only; known misses are excluded', async () => {
  const pg = await recommend(saved({ v: 1, region: { mode: 'must', values: ['Northeast'] } }));
  const res = oracle(pg);
  const unknown = CATALOG.programs.filter((p) => p.region == null).map((p) => p.slug).sort();
  assert.deepEqual(res.needVerification.map((x) => x.slug).sort(), unknown);
  const nv = pg.app().slice(pg.app().indexOf('<details class="recs-nv'));
  for (const s of unknown) assert.ok(nv.includes(`href="#/p/${s}"`), s);
  assert.ok(!cardSlugs(pg.app()).some((s) => unknown.includes(s)));
  const southern = CATALOG.programs.find((p) => p.region === 'South').slug;
  assert.ok(!pg.app().includes(`href="#/p/${southern}"`) && !cardSlugs(pg.app()).includes(southern), 'a known non-Northeast program is listed');
  assert.equal(res.excluded.byMustHave, CATALOG.programs.filter((p) => p.region && p.region !== 'Northeast').length);
});

test('A3 sparse soft data: one known match out of a fixed three, one reason, two unknowns, no tradeoff or penalty wording', () => {
  const cat = tinyCatalog([row('sparse', { region: 'West', undergradEnrollment: null })], { sparse: entry({ climate: null, climateUnknown: 'no-normals' }) });
  const res = R.rank({ ...cat, prefs: mk({ region: { mode: 'prefer', values: ['West'] }, size: { mode: 'prefer', values: ['lt5k'] }, climate: { mode: 'prefer', values: ['mild'] } }) });
  const it = res.confirmed[0];
  assert.deepEqual([it.matched, it.of, it.score], [1, 3, 1 / 3], 'not one of a fixed three');
  assert.notEqual(it.score, 1, 'a perfect score from sparse data');
  assert.equal(it.reasons.length, 1);
  assert.equal(R.reasonText(it.reasons[0]), 'West region (CA)');
  assert.equal(it.tradeoff, null);
  assert.deepEqual(it.unknowns.map((u) => u.category), ['size', 'climate']);
  assert.doesNotMatch(JSON.stringify(it) + it.unknowns.map(R.unknownText).join(' '), /penalt/i);
});

test('A4 no preferences: an all-Skip save keeps ordinary browsing, claims no personalization, and leaves saved filters alone', async () => {
  const filters = JSON.stringify({ conf: ['SEC'], region: [], division: [], sort: 'rpi' });
  const pg = await ready({ status: ON, storage: { 'cd.filters': filters } });
  await open(pg);
  pg.panel().onsubmit({ preventDefault() { } }); await settle();
  assert.equal(pg.sb.S.recs.active, false);
  assert.equal(pg.sb.S.recs.status, 'Choose at least one preference to get recommendations.');
  await pg.sb.renderList();
  // #465 D: the toolbar's sort select lists Recommended as an option while recs is on - an option is not a claim
  assert.ok(!/for you|Recommended/i.test(text(pg.app().replace(/<select[\s\S]*?<\/select>/g, ''))), 'a personalization claim');
  assert.equal(pg.store.get('cd.filters'), filters, 'the saved filters changed');
  assert.ok(!pg.store.has('cd.recs'));
});

test('A5 item vs global: hiding one large school for size hides only it; the size preference is unchanged; Undo restores the list', async () => {
  const prefs = { v: 1, size: { mode: 'prefer', values: ['lt5k'] }, division: { mode: 'must', values: ['D1'] } };
  const pg = await recommend(saved(prefs));
  const before = pg.app();
  // A 15,000+ school, as the plan's A5 says (Huatuo on #429).
  const big = oracle(pg).confirmed.find((x) => (CATALOG.programs.find((p) => p.slug === x.slug).undergradEnrollment ?? 0) >= 15000);
  assert.ok(big, 'a confirmed 15,000+ program to hide');
  await pg.sb.recsHide(big.slug, 'size');
  assert.deepEqual(cardSlugs(pg.app()), oracle(pg).confirmed.slice(0, 25).map((x) => x.slug));
  assert.equal(oracle(pg).confirmed.length + 1, oracle(pg, { hidden: [] }).confirmed.length, 'more than one program left');
  assert.deepEqual(doc(pg).prefs.size, { mode: 'prefer', values: ['lt5k'] }, 'the global size preference changed');
  assert.match(toastHtml(pg), /Edit this preference/, 'a global change is not offered as its own step');
  await pg.sb.recsUndo();
  assert.equal(pg.app(), before);
});

test('A6 sort switch: Recommended, then Name, then Recommended; ordinary browsing between, with a clear paused state', async () => {
  const pg = await recommend(saved({ v: 1, division: { mode: 'must', values: ['D3'] } }));
  const hidden = oracle(pg).confirmed[0].slug;
  await pg.sb.recsHide(hidden, 'other');
  const first = pg.app();
  assert.ok(!cardSlugs(first).includes(hidden));
  pg.$('#sortSelect').onchange({ target: { value: 'name' } }); await settle();
  const browse = pg.app();
  assert.deepEqual(cardSlugs(browse), pg.sb.filteredPrograms().map((p) => p.slug));
  assert.ok(cardSlugs(browse).includes(hidden), 'a hidden program did not reappear under the Name sort (Huatuo on #429)');
  assert.ok(cardSlugs(browse).some((s) => CATALOG.programs.find((p) => p.slug === s).division !== 'D3'), 'must-haves still applied');
  assert.match(browse, /Personalization paused \(sorted by Name\)/);
  pg.$('#sortSelect').onchange({ target: { value: 'recommended' } }); await settle();
  assert.equal(pg.app(), first, 'the saved preferences did not reapply unchanged');
});

test('A7 empty eligible set: each cause is named with its count and a control; nothing is fabricated or relaxed', async () => {
  // All failing must-haves.
  const failing = await recommend(saved({ v: 1, region: { mode: 'must', values: ['Northeast'] }, size: { mode: 'must', values: ['ge15k'] }, division: { mode: 'must', values: ['D3'] } }));
  assert.deepEqual(cardSlugs(failing.app()), []);
  assert.match(text(failing.app()), /your must-haves rule out [\d,]+ programs/i);
  assert.match(failing.app(), /data-recs-edit>Edit preferences<\/button>/);
  // All hidden.
  const filters = JSON.stringify({ conf: ['Ivy League'] });
  const hiddenAll = await recommend({ ...saved({ v: 1, division: { mode: 'must', values: ['D1'] } }), 'cd.filters': filters });
  for (const s of oracle(hiddenAll).confirmed.map((x) => x.slug)) await hiddenAll.sb.recsHide(s, 'other');
  assert.match(text(hiddenAll.app()), /8 programs are hidden/);
  assert.match(hiddenAll.app(), /data-recs-show-hidden>Show hidden<\/button>/);
  // A mix: a filter, a failing must-have and hidden programs, each counted.
  const mix = await recommend({ ...saved({ v: 1, size: { mode: 'must', values: ['ge15k'] } }), 'cd.filters': JSON.stringify({ conf: ['Ivy League'] }) });
  const res = oracle(mix);
  for (const x of res.confirmed) await mix.sb.recsHide(x.slug, 'other');
  const t = text(mix.app());
  assert.match(t, /your filters leave 8 programs of 1,011/i);
  assert.match(t, /must-haves rule out \d+ programs?/);
  assert.match(t, /\d+ programs? (is|are) hidden/);
  assert.match(mix.app(), /data-recs-unfilter="all">Clear filters<\/button>/);
  assert.deepEqual(cardSlugs(mix.app()), [], 'a candidate was fabricated');
});

test('A8 boundaries and ties: 4,999 | 5,000 | 14,999 | 15,000 band exactly; equal scores keep the displayed-name order under shuffle', () => {
  const b = CATALOG.constants.sizeBands;
  assert.deepEqual([4999, 5000, 14999, 15000].map((n) => R.sizeBand(n, b)), ['lt5k', '5k-15k', '5k-15k', 'ge15k']);
  const rows = [row('m', { shortName: 'Mu' }), row('a', { shortName: 'Alpha' }), row('z', { shortName: 'alpha' }), row('b', { shortName: 'Beta' })];
  const want = R.rank({ ...tinyCatalog(rows), prefs: mk({ division: { mode: 'prefer', values: ['D3'] } }) }).confirmed.map((x) => x.slug);
  assert.deepEqual(want, ['z', 'a', 'b', 'm'], 'not displayed name, then the exact compare, then slug');
  for (const order of [[3, 2, 1, 0], [1, 3, 0, 2], [2, 0, 3, 1]]) {
    const shuffled = R.rank({ ...tinyCatalog(order.map((i) => rows[i])), prefs: mk({ division: { mode: 'prefer', values: ['D3'] } }) });
    assert.deepEqual(shuffled.confirmed.map((x) => x.slug), want);
  }
});

test('A9 refresh and reset: saved preferences and hides come back after a reload; Clear removes only recommendation state', async () => {
  const other = { 'cd.favorites': '["stanford"]', 'cd.compare': '["stanford","ucla"]', 'cd.filters': '{"conf":[],"sort":"name"}', 'cd.residency': '"CA"' };
  const pg = await recommend({ ...saved({ v: 1, division: { mode: 'must', values: ['D3'] } }), ...other });
  const hid = oracle(pg).confirmed[0].slug;
  await pg.sb.recsHide(hid, 'other');
  const shownBefore = cardSlugs(pg.app());
  const reload = await recommend({ 'cd.recs': pg.store.get('cd.recs'), ...other });
  assert.deepEqual(cardSlugs(reload.app()), shownBefore, 'the reload did not restore the same list');
  assert.deepEqual(plain(reload.sb.S.recs.hidden.map((h) => h.slug)), [hid]);
  const before = Object.fromEntries([...reload.store].filter(([k]) => k !== 'cd.recs'));
  await reload.sb.recsClearAll();
  assert.equal(reload.store.has('cd.recs'), false);
  assert.deepEqual(Object.fromEntries([...reload.store]), before, 'Shortlist, Compare, filters or residency changed');
});

test('A10 bad or stale state: corrupt JSON, storage that throws, a removed enum value and a removed program; no crash, each said', async () => {
  const corrupt = await ready({ status: ON, storage: { 'cd.recs': '{"v":1,"prefs":' } });
  await open(corrupt);
  assert.match(corrupt.panelHtml(), /couldn’t be read, so the form starts empty/);
  const throwing = await ready({ status: ON, storage: 'throws' });
  await open(throwing);
  assert.match(throwing.panelHtml(), /won’t be remembered on this device/);
  const removed = await ready({ status: ON, storage: saved({ v: 1, region: { mode: 'prefer', values: ['Pacific', 'West'] } }) });
  await open(removed);
  assert.match(removed.panelHtml(), /no longer offered and were left out: Region “Pacific”/);
  assert.deepEqual(plain(removed.sb.S.recs.draft.region.values), ['West'], 'silently reinterpreted');
  const stale = await recommend(saved({ v: 1, region: { mode: 'prefer', values: ['West'] } }, { hidden: [{ slug: 'a-program-that-left', reason: 'other', at: '2026-09-01' }] }));
  assert.match(stale.app(), /1 hidden program is no longer listed · <button type="button" class="btn" data-recs-remove-stale>Remove<\/button>/);
  assert.deepEqual(doc(stale).hidden.map((h) => h.slug), ['a-program-that-left'], 'dropped before the visitor asked');
});

test('A11 new and low coverage: a program with only its division known is evaluated, marked limited, and never confirmed on an unknown must', async () => {
  const cat = tinyCatalog([row('newbie', { region: null, state: null, undergradEnrollment: null, division: 'D2' })], { newbie: null });
  const prefer = R.rank({ ...cat, prefs: mk({ division: { mode: 'prefer', values: ['D2'] } }) });
  assert.deepEqual(prefer.confirmed.map((x) => [x.slug, x.matched, x.of]), [['newbie', 1, 1]], 'content alone did not permit evaluation');
  assert.deepEqual(prefer.confirmed[0].coverage, { known: 1, of: 4 });
  const must = R.rank({ ...cat, prefs: mk({ region: { mode: 'must', values: ['West'] }, division: { mode: 'prefer', values: ['D2'] } }) });
  assert.deepEqual([must.confirmed.length, must.needVerification.map((x) => x.slug)], [0, ['newbie']]);
  // On the page: the real program with only its division known shows "Limited data" in Need verification.
  const pg = await recommend(saved({ v: 1, region: { mode: 'must', values: ['West'] } }));
  const nv = pg.app().slice(pg.app().indexOf('<details class="recs-nv'));
  const at = nv.indexOf('href="#/p/claremont-mudd-scripps"');
  assert.ok(at >= 0, 'the low-coverage program is not in Need verification');
  const end = nv.indexOf('class="recs-nv-row"', at);
  assert.match(nv.slice(at, end < 0 ? undefined : end), /Limited data: 1 of 4 facts known/);
});

test('A12 accessible failure (keyboard-only mobile, load error, choices kept; LLM timeout not applicable in V1: no LLM input)', async () => {
  const pg = await ready({ status: ON, width: 375, fit: 'missing' });
  await open(pg);
  assert.equal(pg.panel()._attrs['aria-modal'], 'true');
  assert.equal(FOCUS.el?._name, '#recsTitle', 'focus did not move into the sheet');
  pg.sb.recsToggleValue('division', 'D3');
  pg.panel().onsubmit({ preventDefault() { } }); await settle();
  assert.match(pg.app(), /role="alert">Recommendations need school and climate data, which didn’t load\. <button type="button" class="btn" id="recsResume">Try again<\/button>/,
    'the load error is not announced');
  assert.deepEqual(doc(pg).prefs.division, { mode: 'prefer', values: ['D3'] }, 'the choices did not survive the error');
  assert.equal(pg.sb.S.recs.active, false);
  await pg.sb.recsOpen(); await settle();
  assert.deepEqual(plain(pg.sb.S.recs.draft.division), { use: 'choose', values: ['D3'], importance: 'prefer' }, 'the form lost the choices');
  // The rest of A12's keyboard path is real-device work: Tab and Esc are tested in recs_form; a person checks a phone.
});
