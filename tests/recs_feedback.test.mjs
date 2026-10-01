// "Find programs for me": feedback (issue #400, PR 5). Not a good fit, Undo, the hidden list and Restore, stale hidden
// IDs, Edit this preference, Clear personalization and the shared-device notice.
//
//     node --test tests/recs_feedback.test.mjs
//     RECS_PAGE_HTML=<the PR 4 page> node --test tests/recs_feedback.test.mjs   # the behavioural cases fail
//
// The harness is tests/recs_page_helpers.mjs. What the list shows is checked against public/recs.js's rank() run here
// with the same hidden list, so these tests prove the page hides exactly what the visitor hid and nothing else.
//
// What it CANNOT prove: focus movement and real key delivery in a browser.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import { FIT, HTML, FOCUS, ON, ready, open, settle, plain } from './recs_page_helpers.mjs';
import { acquireShared } from './timing_helpers.mjs';
// A heavy page suite: it holds the CPU lock shared, so it never runs while a timing suite measures (tests/timing_helpers.mjs).
const CPU = await acquireShared('recs_feedback', 120_000);
test.after(() => CPU.release());

const R = createRequire(import.meta.url)('../public/recs.js');
const PREFS = { v: 1, region: { mode: 'prefer', values: ['West', 'Midwest'] }, division: { mode: 'must', values: ['D3'] },
  size: { mode: 'prefer', values: ['lt5k'] } };
const stored = (doc) => ({ 'cd.recs': JSON.stringify({ v: 1, prefs: PREFS, notices: { sharedDevice: true }, ...doc }) });
const cardSlugs = (html) => [...html.matchAll(/class="card pcard[^"]*" data-slug="([^"]+)"/g)].map((m) => m[1]);
const oracle = (pg, hidden = []) => R.rank({ list: { updated: pg.sb.S.index.updated, programs: pg.sb.S.index.programs }, fit: FIT, prefs: pg.sb.S.recs.saved,
  filter: (p) => pg.sb.matchesFilters(p, null), hidden });
const doc = (pg) => JSON.parse(pg.store.get('cd.recs'));
const toast = (pg) => pg.$('#recsToast');
const OTHER = { 'cd.favorites': '["stanford"]', 'cd.compare': '["stanford","ucla"]', 'cd.filters': '{"conf":[],"region":[],"division":[],"sort":"name"}', 'cd.residency': '"CA"' };
async function shown(storage = stored({}), page = {}) {
  const pg = await ready({ status: ON, storage, ...page });
  await pg.sb.recsShowRecommended();
  await settle();
  assert.equal(pg.sb.S.recs.active, true, 'Recommended mode did not start');
  return pg;
}

test('every Recommended card has "Not a good fit", labelled with its displayed name, with the five reasons', async () => {
  const pg = await shown();
  const first = oracle(pg).confirmed[0];
  const html = pg.app();
  const at = html.indexOf(`data-slug="${first.slug}"`);
  const card = html.slice(at, html.indexOf('class="foot"', at));
  assert.ok(card.includes(`<summary>Not a good fit<span class="sr-only">: ${first.displayName}</span></summary>`));
  assert.deepEqual([...card.matchAll(new RegExp(`data-recs-hide="${first.slug}" data-recs-reason="(\\w+)">([^<]+)<`, 'g'))].map((m) => [m[1], m[2]]),
    [['region', 'Wrong region'], ['division', 'Wrong division'], ['size', 'Wrong size'], ['climate', 'Wrong climate'], ['other', 'Not for me']]);
  assert.match(card, /class="div-tag"[^>]*>D3<\/span>/, 'the card lost its division tag');
});

test('A5: hiding one program for size hides only it; the size preference is unchanged; Undo restores the identical list', async () => {
  const pg = await shown();
  const before = pg.app();
  const target = oracle(pg).confirmed[2];
  assert.equal(await pg.sb.recsHide(target.slug, 'size'), true);
  const want = oracle(pg, [target.slug]);
  assert.deepEqual(cardSlugs(pg.app()), want.confirmed.slice(0, 25).map((x) => x.slug));
  assert.ok(!cardSlugs(pg.app()).includes(target.slug));
  const d = doc(pg);
  assert.deepEqual(d.prefs, plain(R.validatePrefs(PREFS, FIT.constants).prefs), 'a preference changed');
  assert.equal(d.hidden.length, 1);
  assert.equal(d.hidden[0].slug, target.slug);
  assert.equal(d.hidden[0].reason, 'size');
  assert.match(d.hidden[0].at, /^\d{4}-\d{2}-\d{2}$/);
  assert.equal(toast(pg).hidden, false);
  assert.match(toast(pg).innerHTML, new RegExp(`^Hidden: ${target.displayName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\. <button type="button" class="btn" id="recsUndo">Undo</button> <button type="button" class="btn" id="recsEditPref" data-recs-cat="size">Edit this preference</button>$`));
  assert.equal(await pg.sb.recsUndo(), true);
  assert.equal(pg.app(), before, 'Undo did not restore the identical list');
  assert.deepEqual(doc(pg).hidden, []);
  assert.equal(toast(pg).hidden, true);
});

test('a reason for a category the visitor skipped offers no "Edit this preference"; "Not for me" never does', async () => {
  const pg = await shown();
  const [a, b] = oracle(pg).confirmed;
  await pg.sb.recsHide(a.slug, 'climate');
  assert.ok(!toast(pg).innerHTML.includes('Edit this preference'));
  await pg.sb.recsHide(b.slug, 'other');
  assert.ok(!toast(pg).innerHTML.includes('Edit this preference'));
});

test('Edit this preference opens the form and changes nothing by itself', async () => {
  const pg = await shown();
  await pg.sb.recsHide(oracle(pg).confirmed[0].slug, 'region');
  const before = pg.store.get('cd.recs');
  pg.sb.recsEditPreference('region');
  await settle();
  assert.equal(pg.sb.S.recs.open, true);
  assert.equal(pg.store.get('cd.recs'), before, 'opening the form changed what is saved');
  assert.deepEqual(plain(pg.sb.S.recs.saved.region), PREFS.region);
});

test('repeated feedback: hide, Undo, hide again', async () => {
  const pg = await shown();
  const t = oracle(pg).confirmed[0].slug;
  await pg.sb.recsHide(t, 'size'); await pg.sb.recsUndo(); await pg.sb.recsHide(t, 'other');
  assert.deepEqual(doc(pg).hidden.map((h) => [h.slug, h.reason]), [[t, 'other']]);
  assert.ok(!cardSlugs(pg.app()).includes(t));
  assert.equal(await pg.sb.recsHide(t, 'size'), false, 'hid the same program twice');
});

test('the hidden list: a count, Show, each program with its division tag and Restore; Restore brings it back', async () => {
  const pg = await shown();
  const [a, b] = oracle(pg).confirmed;
  await pg.sb.recsHide(a.slug, 'size'); await pg.sb.recsHide(b.slug, 'region');
  assert.match(pg.app(), /2 hidden programs · <button type="button" class="btn" data-recs-toggle-hidden aria-expanded="false" aria-controls="recsHiddenList">Show<\/button>/);
  pg.sb.S.recs.showHidden = true; await pg.sb.renderList();
  const list = pg.app().slice(pg.app().indexOf('id="recsHiddenList"'), pg.app().indexOf('</ul>', pg.app().indexOf('id="recsHiddenList"')));
  for (const x of [a, b]) {
    assert.ok(list.includes(`<span class="name">${x.displayName}</span>`), x.slug);
    assert.ok(list.includes(`data-recs-restore="${x.slug}">Restore<span class="sr-only"> ${x.displayName}</span>`));
  }
  assert.equal((list.match(/class="div-tag"/g) || []).length, 2);
  assert.equal(await pg.sb.recsRestore(a.slug), true);
  assert.deepEqual(doc(pg).hidden.map((h) => h.slug), [b.slug]);
  assert.deepEqual(cardSlugs(pg.app()), oracle(pg, [b.slug]).confirmed.slice(0, 25).map((x) => x.slug));
  assert.equal(toast(pg).innerHTML, `Restored: ${a.displayName}.`);
});

test('A10: a hidden program no longer listed gets one line with Remove; nothing is dropped until the visitor says so', async () => {
  const pg = await shown(stored({ hidden: [{ slug: 'a-program-gone', reason: 'size', at: '2026-09-01' }] }));
  assert.match(pg.app(), /1 hidden program is no longer listed · <button type="button" class="btn" data-recs-remove-stale>Remove<\/button>/);
  assert.deepEqual(doc(pg).hidden.map((h) => h.slug), ['a-program-gone'], 'dropped before the visitor asked');
  await pg.sb.recsRemoveStale();
  assert.deepEqual(doc(pg).hidden, []);
  assert.ok(!/no longer listed/.test(pg.app()));
});

test('A10: unreadable hidden entries are left out and counted, never reinterpreted', async () => {
  const pg = await shown(stored({ hidden: [{ slug: 'Not A Slug' }, 7, { reason: 'size' }, { slug: 'stanford', reason: 'weird' }] }));
  assert.deepEqual(plain(pg.sb.S.recs.hidden), [{ slug: 'stanford', reason: 'other', at: null }]);
  assert.match(pg.app(), /3 saved hidden programs couldn’t be read and are left out/);
  const pg2 = await shown(stored({ hidden: 'everything' }));
  assert.deepEqual(plain(pg2.sb.S.recs.hidden), []);
  assert.match(pg2.app(), /1 saved hidden program couldn’t be read and is left out/);
});

test('A7: when every remaining program is hidden, the empty state says so and offers Show hidden', async () => {
  const prefs = { v: 1, division: { mode: 'must', values: ['D3'] } };
  const filters = JSON.stringify({ conf: ['New England Small College Athletic Conference'] });
  const pg = await shown({ 'cd.recs': JSON.stringify({ v: 1, prefs, notices: { sharedDevice: true } }), 'cd.filters': filters });
  for (const slug of oracle(pg).confirmed.map((x) => x.slug)) await pg.sb.recsHide(slug, 'other');
  const res = oracle(pg, pg.sb.S.recs.hidden.map((h) => h.slug));
  assert.equal(res.confirmed.length, 0);
  const text = pg.app().replace(/<[^>]+>/g, '');
  assert.match(text, new RegExp(`${res.excluded.hidden} programs are hidden`));
  assert.match(pg.app(), /data-recs-show-hidden>Show hidden<\/button>/);
});

test('A9: Clear personalization removes cd.recs only; Shortlist, Compare, filters and residency are byte-identical', async () => {
  const pg = await shown({ ...stored({ hidden: [{ slug: 'stanford', reason: 'size', at: '2026-09-01' }] }), ...OTHER });
  const others = () => Object.fromEntries([...pg.store].filter(([k]) => k !== 'cd.recs'));
  const before = others();
  await pg.sb.recsClearAll();
  assert.equal(pg.store.has('cd.recs'), false);
  assert.deepEqual(others(), before);
  assert.equal(pg.sb.S.recs.active, false);
  assert.ok(!/Recommended for you|Personalization paused|recs-why/.test(pg.app()), 'not the ordinary list');
  assert.equal(pg.$('#sortSelect').value, 'name');
  assert.equal(toast(pg).innerHTML, 'Personalization cleared. Your Shortlist, Compare and filters are unchanged.');
  assert.deepEqual(plain(pg.sb.S.recs.hidden), []);
});

test('the shared-device notice: once, on the first save to this browser; never when nothing could be saved', async () => {
  const pg = await ready({ status: ON });
  await open(pg);
  pg.sb.recsToggleValue('division', 'D3');
  pg.panel().onsubmit({ preventDefault() { } }); await settle();
  assert.match(pg.app(), /Your preferences and hidden programs are saved in this browser only\. Anyone using this device can see them\./);
  assert.deepEqual(doc(pg).notices, { sharedDevice: true });
  const again = await ready({ status: ON, storage: { 'cd.recs': pg.store.get('cd.recs') } });
  await open(again);
  again.sb.recsToggleValue('region', 'South');
  again.panel().onsubmit({ preventDefault() { } }); await settle();
  assert.ok(!/Anyone using this device/.test(again.app()), 'shown twice');
  const none = await ready({ status: ON, storage: 'throws' });
  await open(none);
  none.sb.recsToggleValue('division', 'D2');
  none.panel().onsubmit({ preventDefault() { } }); await settle();
  assert.ok(!/Anyone using this device/.test(none.app()));
});

test('storage that throws: hiding works for this visit and says so; nothing throws', async () => {
  const pg = await ready({ status: ON, storage: 'throws' });
  await open(pg);
  pg.sb.recsToggleValue('division', 'D3');
  pg.panel().onsubmit({ preventDefault() { } }); await settle();
  const t = oracle(pg).confirmed[0];
  assert.equal(await pg.sb.recsHide(t.slug, 'size'), true);
  assert.match(toast(pg).innerHTML, /\(for this visit only\)\./);
  assert.ok(!cardSlugs(pg.app()).includes(t.slug));
});

test('a newer cd.recs is never overwritten by a hide', async () => {
  const newer = JSON.stringify({ v: 2, prefs: {}, hidden: [] });
  const pg = await ready({ status: ON, storage: { 'cd.recs': newer } });
  await open(pg);
  pg.sb.recsToggleValue('division', 'D3');
  pg.panel().onsubmit({ preventDefault() { } }); await settle();
  await pg.sb.recsHide(oracle(pg).confirmed[0].slug, 'other');
  assert.equal(pg.store.get('cd.recs'), newer);
});

test('the toast is cleared by the next action: choosing another sort, or showing the recommendations again', async () => {
  const pg = await shown();
  await pg.sb.recsHide(oracle(pg).confirmed[0].slug, 'size');
  assert.equal(toast(pg).hidden, false);
  pg.$('#sortSelect').onchange({ target: { value: 'name' } }); await settle();
  assert.equal(toast(pg).hidden, true);
});

// ---------- #417 review: focus, the newer version, the dropped-entries notice ----------

test('the toast is a static node after #app, focusable by script (tabindex -1), so Clear never drops focus to <body>', async () => {
  const page = fs.readFileSync(HTML, 'utf8');
  const appLineEnd = page.indexOf('\n', page.indexOf('<div id="app">')), script = page.indexOf('<script>');
  const at = page.indexOf('<div class="recs-toast" id="recsToast" role="status" aria-live="polite" tabindex="-1" hidden></div>');
  assert.ok(appLineEnd > 0 && at > appLineEnd && at < script, 'the toast is not a focusable static node after #app');
  const pg = await shown();
  await pg.sb.recsClearAll();
  assert.equal(FOCUS.el?._name, '#recsToast');
});

test('after Restore, focus moves to the next Restore, then the one before, then the preferences line', async () => {
  const pg = await shown();
  const [a, b, c] = oracle(pg).confirmed;
  for (const x of [a, b, c]) await pg.sb.recsHide(x.slug, 'other');
  pg.sb.S.recs.showHidden = true; await pg.sb.renderList();
  await pg.sb.recsRestore(b.slug);
  assert.equal(FOCUS.el?._name, `[data-recs-restore="${c.slug}"]`);
  assert.ok(pg.app().includes(`data-recs-restore="${c.slug}"`), 'focused a Restore that is not on the page');
  await pg.sb.recsRestore(c.slug);
  assert.equal(FOCUS.el?._name, `[data-recs-restore="${a.slug}"]`);
  assert.ok(pg.app().includes(`data-recs-restore="${a.slug}"`));
  await pg.sb.recsRestore(a.slug);
  assert.equal(FOCUS.el?._name, '#recsBarText');
  assert.ok(pg.app().includes('id="recsBarText" tabindex="-1"'));
});

test('with the list collapsed, Restore focuses the Show toggle while programs stay hidden', async () => {
  const pg = await shown();
  const [a, b] = oracle(pg).confirmed;
  await pg.sb.recsHide(a.slug, 'other'); await pg.sb.recsHide(b.slug, 'other');
  await pg.sb.recsRestore(a.slug);
  assert.equal(FOCUS.el?._name, '[data-recs-toggle-hidden]');
  assert.ok(pg.app().includes('data-recs-toggle-hidden'));
});

test('Clear personalization never deletes a newer version: it clears this visit and says so', async () => {
  const newer = JSON.stringify({ v: 2, prefs: {}, hidden: [] });
  const pg = await ready({ status: ON, storage: { 'cd.recs': newer } });
  await open(pg);
  pg.sb.recsToggleValue('division', 'D3');
  pg.panel().onsubmit({ preventDefault() { } }); await settle();
  await pg.sb.recsClearAll();
  assert.equal(pg.store.get('cd.recs'), newer);
  assert.equal(toast(pg).innerHTML, 'Personalization cleared for this visit. What a newer version of this page saved is left as it is.');
  assert.equal(pg.sb.S.recs.active, false);
});

test('the "couldn\'t be read" notice goes once the hidden list has been saved again', async () => {
  const pg = await shown(stored({ hidden: [7, { slug: 'stanford', reason: 'size', at: '2026-09-01' }] }));
  assert.match(pg.app(), /1 saved hidden program couldn’t be read/);
  await pg.sb.recsHide(oracle(pg).confirmed[0].slug, 'other');
  assert.ok(!/couldn’t be read/.test(pg.app()), 'the notice outlived the rewrite');
  assert.equal(doc(pg).hidden.length, 2);
});
