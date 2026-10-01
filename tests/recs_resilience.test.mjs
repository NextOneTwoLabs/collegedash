// "Find programs for me": resilience (issue #400, PR 6). cd.recs migrations, another tab changing it, the program list
// failing to load (O1), the local-only ?recs-timing=1 overlay, reasons in the Stats view, the Start strip's entry
// (#404 decision 3b) and the phone drawer's bar (#422) in Recommended mode.
//
//     node --test tests/recs_resilience.test.mjs
//     RECS_PAGE_HTML=<the PR 5 page> node --test tests/recs_resilience.test.mjs   # the page cases fail
//
// The harness is tests/recs_page_helpers.mjs; the migration cases are unit tests of public/recs.js. Offline.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { FIT, HTML, FOCUS, LOAD_REQUESTS, ON, ready, loadPage, open, settle, plain, toastHtml } from './recs_page_helpers.mjs';
import { parseCss, decls } from './lib/css_cascade.mjs';

const R = createRequire(import.meta.url)('../public/recs.js');
const PREFS = { v: 1, region: { mode: 'prefer', values: ['West', 'Midwest'] }, division: { mode: 'must', values: ['D3'] },
  size: { mode: 'prefer', values: ['lt5k'] } };
const stored = (doc = {}) => ({ 'cd.recs': JSON.stringify({ v: 1, prefs: PREFS, notices: { sharedDevice: true }, ...doc }) });
const oracle = (pg) => R.rank({ list: { updated: pg.sb.S.index.updated, programs: pg.sb.S.index.programs }, fit: FIT, prefs: pg.sb.S.recs.saved,
  filter: (p) => pg.sb.matchesFilters(p, null), hidden: pg.sb.S.recs.hidden.map((h) => h.slug) });
async function shown(storage = stored(), page = {}) {
  const pg = await ready({ status: ON, storage, ...page });
  await pg.sb.recsShowRecommended(); await settle();
  assert.equal(pg.sb.S.recs.active, true, 'Recommended mode did not start');
  return pg;
}

// ---------- migrations (public/recs.js) ----------

test('migrateDoc: a v0 document (no version) is brought to v1; v1 is current; a newer one is left alone', () => {
  assert.equal(R.DOC_V, 1);
  assert.ok(Object.isFrozen(R.MIGRATIONS));
  const bare = { region: { mode: 'prefer', values: ['West'] }, size: { mode: 'must', values: ['lt5k'] } };
  assert.deepEqual(R.migrateDoc(bare), { status: 'migrated', from: 0,
    doc: { v: 1, prefs: { v: 1, region: { mode: 'prefer', values: ['West'] }, size: { mode: 'must', values: ['lt5k'] } } } });
  const wrapped = { prefs: { division: { mode: 'prefer', values: ['D2'] } }, hidden: [{ slug: 'stanford', reason: 'size', at: '2026-09-01' }] };
  assert.deepEqual(R.migrateDoc(wrapped), { status: 'migrated', from: 0,
    doc: { hidden: wrapped.hidden, v: 1, prefs: { division: { mode: 'prefer', values: ['D2'] }, v: 1 } } });
  const current = { v: 1, prefs: { v: 1 } };
  assert.deepEqual(R.migrateDoc(current), { status: 'current', from: 1, doc: current });
  assert.deepEqual(R.migrateDoc({ v: 2, anything: true }), { status: 'newer', from: 2 });
  assert.deepEqual(bare, { region: { mode: 'prefer', values: ['West'] }, size: { mode: 'must', values: ['lt5k'] } }, 'the input was changed');
});

test('migrateDoc: what it can\'t bring up to date is unreadable, never guessed at', () => {
  for (const bad of [null, [], 'text', 7, { v: '1' }, { v: 1.5 }, { v: -1 }, {}, { other: 1 }, { prefs: [] }]) {
    assert.deepEqual(R.migrateDoc(bad), { status: 'unreadable' }, JSON.stringify(bad));
  }
  // A chain step that fails, or skips a version, stops the whole migration.
  assert.deepEqual(R.migrateDoc({ v: 0, x: 1 }, { 0: () => null }), { status: 'unreadable' });
  assert.deepEqual(R.migrateDoc({ v: 0, x: 1 }, { 0: (d) => ({ ...d, v: 2 }) }), { status: 'unreadable' });
  assert.deepEqual(R.migrateDoc({ v: 0 }, {}), { status: 'unreadable' });
});

test('page: a v0 cd.recs is migrated, said once, and written as v1 only when the visitor saves (hidden kept)', async () => {
  const v0 = JSON.stringify({ prefs: { region: { mode: 'must', values: ['Northeast'] } }, hidden: [{ slug: 'stanford', reason: 'other', at: '2026-09-01' }] });
  const pg = await ready({ status: ON, storage: { 'cd.recs': v0 } });
  await open(pg);
  assert.deepEqual(plain(pg.sb.S.recs.notices), ['migrated']);
  assert.match(pg.panelHtml(), /were from an older version of this page and have been brought up to date/);
  assert.ok(!/couldn’t be read/.test(pg.panelHtml()));
  assert.deepEqual(plain(pg.sb.S.recs.draft.region), { use: 'choose', values: ['Northeast'], importance: 'must' });
  assert.equal(pg.store.get('cd.recs'), v0, 'rewritten before a save');
  assert.equal(pg.sb.recsApply(), true);
  const doc = JSON.parse(pg.store.get('cd.recs'));
  assert.equal(doc.v, 1);
  assert.deepEqual(doc.hidden, [{ slug: 'stanford', reason: 'other', at: '2026-09-01' }]);
  assert.deepEqual(doc.prefs.region, { mode: 'must', values: ['Northeast'] });
});

// ---------- another tab ----------

test('another tab: the page listens for cd.recs changes and applies nothing until asked', async () => {
  const pg = await shown();
  assert.ok((pg.windowListeners.storage || []).length >= 1, 'no storage listener');
  const before = pg.app();
  const theirs = JSON.stringify({ v: 1, prefs: { v: 1, division: { mode: 'must', values: ['D1'] } } });
  pg.store.set('cd.recs', theirs);
  for (const fn of pg.windowListeners.storage) fn({ key: 'cd.recs', newValue: theirs });
  assert.match(toastHtml(pg), /^Your preferences changed in another tab\. <button type="button" class="btn" id="recsUseOther">Use those<\/button> <button type="button" class="btn" id="recsKeepThis">Keep these<\/button>$/);
  assert.equal(pg.app(), before, 'something was applied without asking');
  assert.deepEqual(plain(pg.sb.S.recs.saved.division), { mode: 'must', values: ['D3'] });
  for (const fn of pg.windowListeners.storage) fn({ key: 'cd.favorites', newValue: '[]' });
  assert.match(toastHtml(pg), /changed in another tab/, 'another key replaced the prompt');
});

test('another tab: Use those reads them and reranks; Keep these keeps this tab\'s, and its next save overwrites', async () => {
  const pg = await shown();
  const theirs = JSON.stringify({ v: 1, prefs: { v: 1, division: { mode: 'must', values: ['D1'] } } });
  pg.store.set('cd.recs', theirs);
  pg.sb.recsOtherTab(theirs);
  await pg.sb.recsUseOtherTab(); await settle();
  assert.deepEqual(plain(pg.sb.S.recs.saved.division), { mode: 'must', values: ['D1'] });
  assert.equal(toastHtml(pg), 'Now using the preferences from your other tab.', 'the prompt is still up, or Use those said nothing');  // #440
  assert.match(pg.app(), /Division: D1 \(must have\)/);
  const keep = await shown();
  keep.store.set('cd.recs', theirs);
  keep.sb.recsOtherTab(theirs);
  keep.sb.recsKeepThisTab();
  assert.deepEqual(plain(keep.sb.S.recs.saved.division), { mode: 'must', values: ['D3'] });
  await open(keep);
  assert.equal(keep.sb.recsApply(), true);
  assert.deepEqual(JSON.parse(keep.store.get('cd.recs')).prefs.division, { mode: 'must', values: ['D3'] }, 'this tab\'s save did not overwrite');
});

test('another tab cleared everything: the prompt says so; nothing happens in a tab that never read cd.recs', async () => {
  const pg = await shown();
  pg.store.delete('cd.recs');
  for (const fn of pg.windowListeners.storage) fn({ key: null, newValue: null });
  assert.match(toastHtml(pg), /^Your preferences were cleared in another tab\./);
  const fresh = await ready({ status: ON });
  fresh.sb.recsOtherTab('{}');
  assert.equal(toastHtml(fresh), '', 'a tab with nothing read was prompted');
});

// ---------- the program list failing to load (O1) ----------

test('O1: with no program list, Show matches says so in the panel with Try again; nothing is ranked; the form stays', async () => {
  const pg = loadPage({ status: ON, programs: 'missing' });
  await settle();
  assert.equal(pg.sb.S.index, null);
  pg.sb.S.recs.on = true; // the switch normally arrives after the list; this checks the order can't matter
  await open(pg);
  pg.sb.recsToggleValue('division', 'D3');
  pg.panel().onsubmit({ preventDefault() { } }); await settle();
  assert.equal(pg.sb.S.recs.active, false);
  assert.equal(pg.panel().hidden, false, 'the form closed');
  assert.match(pg.panelHtml(), /role="alert">Recommendations need the program list, which didn’t load\. <button type="button" class="btn" id="recsCatalogRetry">Try again<\/button>/);
  assert.ok(!pg.requests.includes('/api/v1/fit'), 'fetched the fit file without a list');
  assert.equal(FOCUS.el?._name, '#recsCatalogRetry');
});

// ---------- ?recs-timing=1 ----------

test('?recs-timing=1: the overlay shows rerank and Apply timings from this browser; nothing is sent', async () => {
  const pg = await ready({ status: ON, search: '?recs-timing=1' });
  await open(pg);
  pg.sb.recsToggleValue('division', 'D3');
  pg.panel().onsubmit({ preventDefault() { } }); await settle();
  const el = pg.$('#recsTiming');
  assert.equal(el.hidden, false);
  assert.match(el.textContent, /^Recommendations timing, measured in this browser only; nothing is sent\. rerank: n \d+, last [\d.]+ ms, p95 [\d.]+ ms \(target ≤100 ms\) · apply: n 1, last [\d.]+ ms, p95 [\d.]+ ms \(target ≤300 ms\)$/);
  assert.deepEqual(pg.requests.filter((u) => !LOAD_REQUESTS.includes(u)), ['recs.js', '/api/v1/fit'], 'the overlay made a request');
  const off = await shown();
  assert.equal(off.$('#recsTiming').textContent, '', 'the overlay drew without the parameter');
  assert.match(fs.readFileSync(HTML, 'utf8'), /<div class="recs-timing" id="recsTiming" hidden><\/div>/);
});

// ---------- reasons in the Stats view ----------

test('the Stats view in Recommended mode has a Why column with each row\'s reasons', async () => {
  const pg = await shown({ ...stored(), 'cd.filters': JSON.stringify({ view: 'table', sort: 'name' }) });
  const html = pg.app();
  assert.match(html, /<th class="recs-why-cell">Why<\/th>/);
  const first = oracle(pg).confirmed[0];
  const row = html.slice(html.indexOf(`data-slug="${first.slug}"`), html.indexOf('</tr>', html.indexOf(`data-slug="${first.slug}"`)));
  assert.match(row, /<td class="recs-why-cell"><ul class="recs-why"/);
  for (const r of first.reasons) assert.ok(row.includes(R.reasonText(r).replace(/&/g, '&amp;')), R.reasonText(r));
  pg.$('#sortSelect').onchange({ target: { value: 'name' } }); await settle();
  assert.ok(!/recs-why-cell/.test(pg.app()), 'the Why column outlived Recommended mode');
});

// ---------- the header's entry (#434 decision 4; it replaced the Start strip's #startActions, #427) ----------

const HEADER_BUTTON = '<button type="button" class="btn recs-entry" id="recsOpen" aria-haspopup="dialog" aria-controls="recsPanel" aria-expanded="false" aria-label="Find programs for me" title="Find programs for me"><span class="recs-entry-full">Find programs for me</span><span class="recs-entry-short" aria-hidden="true">For me</span></button>';

test('#434: "Find programs for me" is the one header button while on, nothing while off; focus returns to it', async () => {
  const off = await ready({ status: { local: false } });
  assert.equal(off.$('#headerRecs').innerHTML, '');
  const pg = await ready({ status: ON });
  assert.equal(pg.$('#headerRecs').innerHTML, HEADER_BUTTON);
  assert.ok(!/Find programs for me|recsOpen/.test(pg.sidebar()), 'a second entry is still in the sidebar');
  pg.$('#recsOpen').onclick(); await settle();
  assert.equal(pg.panel().hidden, false);
  assert.equal(pg.$('#recsOpen')._attrs['aria-expanded'], 'true');
  pg.sb.recsClose();
  assert.equal(FOCUS.el?._name, '#recsOpen', 'focus did not return to the header button');
});

test('#434 condition 4: switched on before the index loads (the #433 pilot), the header button is already there', async () => {
  const pg = loadPage({ status: { local: false } });
  assert.ok(!pg.sb.S.index, 'fixture: the index had already loaded');
  pg.sb.recsSwitchedOn();
  assert.equal(pg.$('#headerRecs').innerHTML, HEADER_BUTTON, 'no header button before the index loaded');
  await settle();
});

test('#434 condition 6: on a phone the open sheet covers the two-row header - it starts at 0 and the header is inert', async () => {
  const pg = await ready({ status: ON, width: 375 });
  await open(pg);
  pg.sb.recsSheetState();
  assert.equal(pg.$('.header').inert, true, 'the header is not inert under the open sheet');
  assert.equal(pg.$('#main').inert, true);
  assert.equal(pg.$('#sidebar').inert, true);
  pg.sb.recsClose();
  assert.equal(pg.$('.header').inert, false, 'the header stayed inert after the sheet closed');
  assert.equal(FOCUS.el?._name, '#recsOpen');
  // the sheet's own phone rule: fixed, inset 0 - it never takes its top from --header-height, which #434 changes
  const css = fs.readFileSync(HTML, 'utf8');
  const phone = parseCss([...css.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n'))
    .filter(r => r.selectors.includes('.recs-panel') && r.at.join(' ') === '@media (max-width: 768px)');
  const d = Object.fromEntries(phone.flatMap(r => decls(r.body)).map(x => [x.prop, x.value]));
  assert.equal(d.position, 'fixed');
  assert.equal(d.inset, '0', 'the phone sheet does not start at 0');
  assert.ok(!phone.some(r => /header-height/.test(r.body)), 'the phone sheet depends on --header-height');
});

// ---------- the phone drawer's bar ----------

test('the drawer bar reads "Show N recommendations" in Recommended mode, and the program count again when paused', async () => {
  const pg = await shown();
  const n = oracle(pg).confirmed.length;
  assert.equal(pg.sb.showResultsLabel(), `Show ${n} recommendations`);
  assert.equal(pg.$('#showResults').textContent, `Show ${n} recommendations`);
  pg.$('#sortSelect').onchange({ target: { value: 'name' } }); await settle();
  assert.equal(pg.sb.showResultsLabel(), `Show ${pg.sb.filteredPrograms().length} programs`);
  assert.equal(pg.$('#showResults').textContent, `Show ${pg.sb.filteredPrograms().length} programs`);
});

// ---------- #427 review: the other-tab prompt holds, and nothing is written while it waits ----------

async function pendingOther() {
  const pg = await shown();
  const theirs = JSON.stringify({ v: 1, prefs: { v: 1, division: { mode: 'must', values: ['D1'] } }, hidden: [{ slug: 'stanford', reason: 'size', at: '2026-09-02' }] });
  pg.store.set('cd.recs', theirs);
  for (const fn of pg.windowListeners.storage) fn({ key: 'cd.recs', newValue: theirs });
  return { pg, theirs };
}
const prompting = (pg) => /changed in another tab\./.test(toastHtml(pg)) && pg.$('#recsToast').hidden === false;

test('#427 review: while another tab\'s change waits, a hide writes nothing and the prompt stays', async () => {
  const { pg, theirs } = await pendingOther();
  await pg.sb.recsHide(oracle(pg).confirmed[0].slug, 'other');
  assert.equal(pg.store.get('cd.recs'), theirs, 'the hide overwrote the other tab\'s preferences');
  assert.ok(prompting(pg), 'the hide replaced the prompt');
});

test('#427 review: Name then Recommended neither dismisses the prompt nor writes', async () => {
  const { pg, theirs } = await pendingOther();
  pg.$('#sortSelect').onchange({ target: { value: 'name' } }); await settle();
  assert.ok(prompting(pg), 'choosing Name dismissed the prompt');
  pg.$('#sortSelect').onchange({ target: { value: 'recommended' } }); await settle();
  assert.ok(prompting(pg), 'showing Recommended dismissed the prompt');
  assert.equal(pg.store.get('cd.recs'), theirs, 'showing Recommended wrote the applied stamp over the other tab\'s');
});

test('#427 review: a save or Clear while the prompt waits writes nothing; after Keep these, the next save does', async () => {
  const { pg, theirs } = await pendingOther();
  await open(pg);
  pg.sb.recsToggleValue('size', 'ge15k');
  assert.equal(pg.sb.recsApply(), true);
  assert.equal(pg.store.get('cd.recs'), theirs, 'the save overwrote while the prompt waited');
  await pg.sb.recsClearAll();
  assert.equal(pg.store.get('cd.recs'), theirs, 'Clear deleted the other tab\'s preferences while the prompt waited');
  assert.ok(prompting(pg));
  // #440 follow-up: the cause is the other tab, not a newer version of the page, and the message says so
  assert.equal(pg.$('#recsToastMsg').innerHTML, 'Personalization cleared for this visit. What your other tab saved is left as it is.',
    'Clear while the prompt waits blames a newer version of the page');
  pg.sb.recsKeepThisTab();
  assert.ok(!prompting(pg), 'Keep these left the prompt');
  assert.equal(toastHtml(pg), 'Keeping this tab’s preferences. Your next change here replaces the other tab’s.');
  assert.equal(FOCUS.el?._name, '#recsToast', 'focus did not go to the toast');
  await open(pg);
  pg.sb.recsToggleValue('division', 'D2');
  assert.equal(pg.sb.recsApply(), true);
  assert.deepEqual(JSON.parse(pg.store.get('cd.recs')).prefs.division, { mode: 'prefer', values: ['D2'] }, 'Keep these did not let the next save write');
});

test('#427 review: Show recommended does not rewrite a migrated document before the visitor saves', async () => {
  const v0 = JSON.stringify({ prefs: { division: { mode: 'must', values: ['D3'] } } });
  const pg = await ready({ status: ON, storage: { 'cd.recs': v0 } });
  await pg.sb.recsShowRecommended(); await settle();
  assert.equal(pg.sb.S.recs.active, true);
  assert.equal(pg.store.get('cd.recs'), v0, 'the applied stamp rewrote the migrated document');
});

test('#427 note: a hide while the prompt waits shows its Undo beside the prompt, focus lands on Undo, and still nothing is written', async () => {
  const { pg, theirs } = await pendingOther();
  const slug = oracle(pg).confirmed[0].slug;
  await pg.sb.recsHide(slug, 'other');
  assert.match(pg.$('#recsToastPrompt').innerHTML, /^Your preferences changed in another tab\. <button type="button" class="btn" id="recsUseOther">Use those<\/button> <button type="button" class="btn" id="recsKeepThis">Keep these<\/button>$/);
  assert.match(pg.$('#recsToastMsg').innerHTML, /^Hidden: [^<]+ \(for this visit only\)\. <button type="button" class="btn" id="recsUndo">Undo<\/button>$/);
  assert.equal(pg.$('#recsToastPrompt').hidden, false); assert.equal(pg.$('#recsToastMsg').hidden, false);
  assert.equal(FOCUS.el?._name, '#recsUndo', 'focus did not land on Undo');
  assert.equal(pg.store.get('cd.recs'), theirs);
  await pg.sb.recsUndo();
  assert.ok(pg.app().includes(`data-slug="${slug}"`), 'Undo did not bring the program back');
  assert.ok(prompting(pg), 'Undo dismissed the prompt');
  assert.ok(!/id="recsUndo"/.test(toastHtml(pg)), 'the Undo outlived its use');
  assert.equal(pg.store.get('cd.recs'), theirs, 'Undo wrote while the prompt waited');
});

// #440 review (Huatuo) 1: the toast is one polite live region, which announces what is written into it. Across a hide
// and its Undo, the prompt part must be the same node with its content never rewritten, and the toast itself never
// rewritten as a whole - so the hide announces "Hidden: …" alone, and Undo announces nothing new.
function countWrites(el) {
  let html = el.innerHTML;
  const log = [];
  Object.defineProperty(el, 'innerHTML', { configurable: true, get: () => html, set: (v) => { log.push(v); html = v; } });
  return log;
}
test('#440 review: a hide and its Undo rewrite only the message part; the waiting prompt is never written again', async () => {
  const { pg } = await pendingOther();
  const prompt = pg.$('#recsToastPrompt'), msg = pg.$('#recsToastMsg');
  assert.match(prompt.innerHTML, /^Your preferences changed in another tab\./, 'the prompt is not in its own part');
  assert.equal(prompt.hidden, false);
  const promptWrites = countWrites(prompt), msgWrites = countWrites(msg), toastWrites = countWrites(pg.$('#recsToast'));
  const slug = oracle(pg).confirmed[0].slug;
  await pg.sb.recsHide(slug, 'other');
  await pg.sb.recsUndo();
  assert.equal(pg.$('#recsToastPrompt'), prompt, 'the prompt part is not the same node');
  assert.deepEqual(promptWrites, [], 'the prompt part was rewritten (re-announced) by a hide or its Undo');
  assert.deepEqual(toastWrites, [], 'the toast was rewritten as a whole');
  assert.equal(msgWrites.length, 2, 'the message part: one write for the hide, one for its Undo');
  assert.match(msgWrites[0], /^Hidden: /);
  assert.equal(msgWrites[1], '');
  assert.equal(msg.hidden, true, 'the empty message part is still shown');
});

// #440 review 2: "Keep these" keeps a hide's Undo, and focus never drops to <body> when the prompt goes.
test('#440 review: hide, then Keep these: the Undo stays, takes focus, and still works', async () => {
  const { pg } = await pendingOther();
  const slug = oracle(pg).confirmed[0].slug;
  await pg.sb.recsHide(slug, 'other');
  pg.sb.recsKeepThisTab();
  assert.equal(pg.sb.S.recs.toast?.kind, 'hidden', 'Keep these threw away the Undo of a hide still in effect');
  assert.ok(!prompting(pg), 'the prompt did not go');
  assert.match(toastHtml(pg), /id="recsUndo"/, 'the Undo is not shown');
  assert.equal(FOCUS.el?._name, '#recsUndo', 'focus did not go to Undo');
  await pg.sb.recsUndo();
  assert.ok(pg.app().includes(`data-slug="${slug}"`), 'Undo no longer brings the program back');
  assert.ok(!pg.sb.S.recs.hidden.some((h) => h.slug === slug));
});

test('#440 review: hide, then Use those: the hide goes with this tab\'s state, and the toast says so and takes focus', async () => {
  const { pg } = await pendingOther();
  await pg.sb.recsHide(oracle(pg).confirmed[0].slug, 'other');
  await pg.sb.recsUseOtherTab(); await settle();
  assert.equal(FOCUS.el?._name, '#recsToast', 'focus did not go to the toast');
  assert.ok(!prompting(pg), 'the prompt did not go');
  assert.ok(!/id="recsUndo"/.test(toastHtml(pg)), 'an Undo for this tab\'s state survived Use those');
  assert.equal(toastHtml(pg), 'Now using the preferences from your other tab.');
  assert.equal(pg.$('#recsToast').hidden, false);
  assert.equal(FOCUS.el?._name, '#recsToast', 'focus did not go to the toast');
});
