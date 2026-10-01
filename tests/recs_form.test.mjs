// "Find programs for me": the switch, the entry button, the panel and form, and cd.recs v1 (issue #400, PR 3).
//
//     node --test tests/recs_form.test.mjs
//     RECS_PAGE_HTML=<a copy of main's index.html> node --test tests/recs_form.test.mjs   # the behavioural cases fail
//
// The page harness is tests/recs_page_helpers.mjs (shared with tests/recs_results.test.mjs): the page's inline <script>
// runs in a `vm` against a stub DOM, fetch is a stub, and recs.js is run when the page appends it. Nothing leaves the process.
//
// What this proves:
//   - the switch: only api/status {recs: true} shows the entry button. Off ({"local":false}, serve.py's
//     {"local":true}, no status, or recs given as anything but true) there is no recs markup, and opening does
//     nothing. The Worker answers {"local":false} byte for byte unless RECS_ENABLED is exactly "true", and
//     wrangler.toml keeps it "false".
//   - no extra request: a page load makes exactly the same requests with the switch on and off, and the panel
//     loads public/recs.js once, on first open, and nothing else (no /api/v1/fit: nothing is ranked yet).
//   - the panel: a dialog (modal only at phone width), four fieldsets with legends, Skip/Choose, pills with
//     aria-pressed, Prefer/Must have with Must disabled for climate and the reason beside it, Clear and Save.
//   - saving: cd.recs is {v: 1, prefs} with the ranker's validated prefs; Shortlist, Compare, filters and residency
//     are untouched; an all-skip save is refused with the A4 message; a Choose with nothing chosen is refused and
//     says which category; climate can never be saved as a must have.
//   - storage: missing, corrupt, throwing, newer-version and removed-value cases each give their notice and never
//     throw; nothing is written until a save; a newer version is never overwritten; unknown fields survive a save.
//
// What it CANNOT prove: focus movement, layout and real key delivery in a browser (see the PR's local check).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import worker from '../worker.js';
import { PUBLIC, HTML, CATALOG, LOAD_REQUESTS, ON, ready, open, settle, plain } from './recs_page_helpers.mjs';

const HERE = path.join(PUBLIC, '..', 'tests');
const saved = (pg) => JSON.parse(pg.store.get('cd.recs'));

// ---------- the switch ----------

const OFF = [['{"local":false}, the Worker with RECS_ENABLED off', { local: false }], ['{"local":true}, serve.py', { local: true }],
  ['no /api/status', null], ['recs: "true" (a string)', { local: false, recs: 'true' }], ['recs: 1', { local: false, recs: 1 }]];
for (const [name, status] of OFF) {
  test(`off (${name}): no recommendation markup, and opening does nothing`, async () => {
    const pg = await ready({ status });
    assert.ok(!/recs|Find programs for me/i.test(pg.sidebar()), 'recommendation markup in the sidebar');
    assert.notEqual(pg.sb.S.recs?.on, true);
    if (pg.sb.recsOpen) await pg.sb.recsOpen();
    await settle();
    assert.equal(pg.panelHtml(), '', 'the panel was drawn');
    assert.deepEqual(pg.requests.filter((u) => !LOAD_REQUESTS.includes(u)), [], 'a request beyond the page load');
  });
}

test('on (api/status {recs: true}): the entry button, labelled and wired as a dialog opener', async () => {
  const pg = await ready({ status: ON });
  assert.equal(pg.sb.S.recs.on, true);
  const m = /<button[^>]*id="recsOpen"[^>]*>Find programs for me<\/button>/.exec(pg.sidebar());
  assert.ok(m, 'no entry button in the sidebar');
  for (const attr of ['type="button"', 'aria-haspopup="dialog"', 'aria-controls="recsPanel"', 'aria-expanded="false"']) assert.ok(m[0].includes(attr), attr);
});

test('no extra request: a page load asks for exactly the same things with the switch on and off', async () => {
  const off = await ready({ status: { local: false } });
  const on = await ready({ status: ON });
  assert.deepEqual([...on.requests].sort(), [...off.requests].sort());
  assert.deepEqual([...on.requests].sort(), [...LOAD_REQUESTS].sort(), 'the page load requests changed');
  assert.ok(!on.requests.includes('recs.js'), 'recs.js loaded on page load');
});

test('opening loads public/recs.js once, on first open, and nothing else (no /api/v1/fit: nothing is ranked yet)', async () => {
  const pg = await ready({ status: ON });
  const before = pg.requests.length;
  await open(pg);
  assert.deepEqual(pg.requests.slice(before), ['recs.js']);
  pg.sb.recsClose();
  await open(pg);
  assert.deepEqual(pg.requests.slice(before), ['recs.js'], 'recs.js loaded twice');
  assert.ok(!pg.requests.some((u) => /fit/.test(u)));
});

test('the Worker answers {"local":false} byte for byte unless RECS_ENABLED is exactly "true"; production keeps it off', async () => {
  const status = async (env) => (await worker.fetch(new Request('https://college.nextonetwo.com/api/status'), env)).text();
  for (const v of [undefined, 'false', 'TRUE', '1', 'yes', ' true']) assert.equal(await status({ RECS_ENABLED: v }), '{"local":false}', String(v));
  assert.equal(await status({}), '{"local":false}');
  assert.equal(await status({ RECS_ENABLED: 'true' }), '{"local":false,"recs":true}');
  const toml = fs.readFileSync(path.join(HERE, '..', 'wrangler.toml'), 'utf8');
  assert.match(toml, /^RECS_ENABLED = "false"$/m, 'wrangler.toml must keep recommendations off in production');
});

// ---------- the panel and form ----------

test('the status line is one persistent live node in the page markup, outside what the panel redraws', () => {
  const page = fs.readFileSync(HTML, 'utf8');
  assert.match(page, /<div class="recs-panel" id="recsPanel" role="dialog" aria-labelledby="recsTitle" hidden><div id="recsPanelBody"><\/div><div class="recs-status" id="recsStatus" role="status" aria-live="polite"><\/div><\/div>/);
});

// The stub DOM has no focus order, so the sheet's controls are stood in for: the heading (tabindex -1, where focus
// lands on open), Close, a radio and Save, in document order. querySelectorAll matches the heading only when the
// selector names it, as a real DOM would for the two selectors in question.
function focusables(pg) {
  const doc = pg.sb.document;
  const el = (id, tag) => Object.assign(pg.$(id), { id: id.slice(1), tag, focus() { doc.activeElement = this; } });
  const items = [el('#recsTitle', 'h2'), el('#recsClose', 'button'), el('#fakeRadio', 'input'), el('#recsSave', 'button')];
  pg.panel().querySelectorAll = (sel) => items.filter((x) => x.tag !== 'h2' || sel.includes('#recsTitle'));
  return items;
}
const tab = (pg, shiftKey) => { let prevented = false; pg.panel().onkeydown({ key: 'Tab', shiftKey, preventDefault() { prevented = true; } }); return prevented; };

test('phone sheet focus trap: Shift+Tab from Close or the heading wraps to the last control, Tab from the last to Close', async () => {
  const pg = await ready({ status: ON, width: 375 });
  await open(pg);
  const [title, close, , save] = focusables(pg);
  pg.sb.document.activeElement = close;
  assert.equal(tab(pg, true), true, 'Shift+Tab from Close left the sheet');
  assert.equal(pg.sb.document.activeElement, save);
  pg.sb.document.activeElement = title;
  assert.equal(tab(pg, true), true, 'Shift+Tab from the heading left the sheet');
  assert.equal(pg.sb.document.activeElement, save);
  pg.sb.document.activeElement = save;
  assert.equal(tab(pg, false), true, 'Tab from the last control left the sheet');
  assert.equal(pg.sb.document.activeElement, close, 'Tab from the last control did not wrap to Close');
});

test('desktop panel: no focus trap; Tab and Shift+Tab leave it normally', async () => {
  const pg = await ready({ status: ON, width: 1400 });
  await open(pg);
  const [, close, , save] = focusables(pg);
  pg.sb.document.activeElement = close;
  assert.equal(tab(pg, true), false);
  pg.sb.document.activeElement = save;
  assert.equal(tab(pg, false), false);
});

test('the sheet is modal and the page behind it inert only at phone width, re-checked on resize, released on close', async () => {
  const pg = await ready({ status: ON, width: 375 });
  await open(pg);
  const behind = ['#main', '#sidebar', '.header'].map((sel) => pg.$(sel));
  assert.equal(pg.panel()._attrs['aria-modal'], 'true');
  assert.ok(behind.every((e) => e.inert === true), 'the page behind the sheet is not inert');
  pg.sb.innerWidth = 1200; pg.sb.recsSheetState(); // rotated to landscape on a tablet, or resized
  assert.equal(pg.panel()._attrs['aria-modal'], 'false');
  assert.ok(behind.every((e) => e.inert === false));
  pg.sb.innerWidth = 375; pg.sb.recsSheetState();
  assert.ok(behind.every((e) => e.inert === true));
  pg.sb.recsClose();
  assert.ok(behind.every((e) => e.inert === false), 'the page stayed inert after the sheet closed');
});

test('the panel: a dialog that is modal only at phone width, four labelled fieldsets, climate prefer-only', async () => {
  for (const [width, modal] of [[1400, 'false'], [375, 'true']]) {
    const pg = await ready({ status: ON, width });
    await open(pg);
    assert.equal(pg.panel()._attrs['aria-modal'], modal, `aria-modal at ${width}px`);
    const html = pg.panelHtml();
    assert.match(html, /<h2 id="recsTitle" tabindex="-1">Find programs for me<\/h2>/);
    assert.match(html, /<button type="button" class="recs-close" id="recsClose" aria-label="Close">/);
    assert.deepEqual([...html.matchAll(/<legend>([^<]+)<\/legend>/g)].map((x) => x[1]), ['Region', 'Division', 'School size', 'Climate']);
    for (const r of pg.sb.REGIONS) assert.ok(html.includes(`data-recs-val="${r}" aria-pressed="false"`), r);
    for (const v of ['D1', 'D2', 'D3', 'lt5k', '5k-15k', 'ge15k', 'mild', 'four-season', 'cold']) assert.ok(html.includes(`data-recs-val="${v}" aria-pressed="false"`), v);
    assert.equal((html.match(/value="must"/g) || []).length, 4);
    assert.match(html, /value="must" data-recs-imp="climate" disabled aria-describedby="recs-climate-why"/);
    assert.match(html, /id="recs-climate-why">Prefer only: climate labels are estimates from the nearest weather station\./);
    assert.ok(!/value="must" data-recs-imp="(region|division|size)"[^>]*disabled/.test(html), 'must disabled outside climate');
    assert.match(html, /<button type="submit" class="btn primary" id="recsSave">Show matches<\/button>/);
    assert.ok(!/match %|% match|admission|recruit/i.test(html), 'no match percentage or admission or recruiting claim');
  }
});

test('the entry button reports the panel open and closed (aria-expanded)', async () => {
  const pg = await ready({ status: ON });
  await open(pg);
  assert.equal(pg.$('#recsOpen')._attrs['aria-expanded'], 'true');
  pg.sb.recsClose();
  assert.equal(pg.panel().hidden, true);
  assert.equal(pg.panelHtml(), '');
  assert.equal(pg.$('#recsOpen')._attrs['aria-expanded'], 'false');
});

test('saving: cd.recs v1 holds the ranker-validated prefs; Shortlist, Compare, filters and residency untouched', async () => {
  const other = { 'cd.favorites': '["stanford"]', 'cd.compare': '["stanford","ucla"]', 'cd.filters': '{"conf":["ACC"],"region":[],"division":[],"sort":"rpi"}', 'cd.residency': '"CA"' };
  const pg = await ready({ status: ON, storage: other });
  const before = Object.fromEntries([...pg.store].filter(([k]) => k !== 'cd.recs'));
  await open(pg);
  const S = pg.sb;
  S.recsToggleValue('region', 'Northeast'); S.recsToggleValue('region', 'West');
  S.recsToggleValue('division', 'D3'); S.recsSetImportance('division', 'must');
  S.recsToggleValue('climate', 'cold');
  assert.equal(S.recsApply(), true);
  assert.deepEqual(saved(pg), { v: 1, prefs: { v: 1, region: { mode: 'prefer', values: ['West', 'Northeast'] }, division: { mode: 'must', values: ['D3'] },
    size: { mode: 'skip', values: [] }, climate: { mode: 'prefer', values: ['cold'] } } });
  const after = Object.fromEntries([...pg.store].filter(([k]) => k !== 'cd.recs'));
  assert.deepEqual(after, before, 'another key changed');
  S.renderRecsPanel();
  assert.match(pg.panelHtml(), /<b>Saved:<\/b> Region: West or Northeast \(prefer\) · Division: D3 \(must have\) · Climate: cold winters \(prefer\)/);
  assert.match(pg.panelHtml(), /Preferences saved\./);
});

test('A4: saving with every category skipped is refused with the plan\'s message, and nothing is written', async () => {
  const pg = await ready({ status: ON, storage: { 'cd.filters': '{"conf":["SEC"]}' } });
  await open(pg);
  assert.equal(pg.sb.recsApply(), false);
  assert.equal(pg.sb.S.recs.status, 'Choose at least one preference to get recommendations.');
  assert.equal(pg.store.has('cd.recs'), false);
  assert.equal(pg.store.get('cd.filters'), '{"conf":["SEC"]}');
  assert.ok(!/for you/i.test(pg.sidebar() + pg.panelHtml()));
});

test('Choose with nothing chosen is refused and names the category; Skip keeps chosen values out of the save', async () => {
  const pg = await ready({ status: ON });
  await open(pg);
  const S = pg.sb;
  S.recsSetUse('size', 'choose');
  S.recsToggleValue('division', 'D2');
  assert.equal(S.recsApply(), false);
  assert.equal(S.S.recs.error, 'Choose at least one option for School size, or set it to Skip.');
  assert.equal(pg.store.has('cd.recs'), false);
  S.recsSetUse('size', 'skip');
  S.recsToggleValue('region', 'South'); S.recsSetUse('region', 'skip');
  assert.equal(S.recsApply(), true);
  assert.deepEqual(saved(pg).prefs.region, { mode: 'skip', values: [] });
  assert.deepEqual(saved(pg).prefs.division, { mode: 'prefer', values: ['D2'] });
});

test('climate can never be saved as a must have; Clear resets the form without saving', async () => {
  const pg = await ready({ status: ON });
  await open(pg);
  const S = pg.sb;
  S.recsToggleValue('climate', 'mild');
  S.recsSetImportance('climate', 'must');
  assert.equal(S.S.recs.draft.climate.importance, 'prefer');
  S.S.recs.draft.climate.importance = 'must'; // even if the draft were forced
  assert.equal(S.recsApply(), true);
  assert.deepEqual(saved(pg).prefs.climate, { mode: 'prefer', values: ['mild'] });
  const keep = pg.store.get('cd.recs');
  S.recsReset();
  assert.ok(Object.values(S.S.recs.draft).every((d) => d.use === 'skip' && !d.values.length));
  assert.equal(pg.store.get('cd.recs'), keep, 'Clear wrote to storage');
});

test('a saved set comes back into the form on the next page load', async () => {
  const prefs = { v: 1, region: { mode: 'must', values: ['Midwest'] }, division: { mode: 'skip', values: [] }, size: { mode: 'prefer', values: ['lt5k', 'ge15k'] }, climate: { mode: 'skip', values: [] } };
  const pg = await ready({ status: ON, storage: { 'cd.recs': JSON.stringify({ v: 1, prefs }) } });
  await open(pg);
  assert.deepEqual(plain(pg.sb.S.recs.draft.region), { use: 'choose', values: ['Midwest'], importance: 'must' });
  assert.deepEqual(plain(pg.sb.S.recs.draft.size), { use: 'choose', values: ['lt5k', 'ge15k'], importance: 'prefer' });
  assert.match(pg.panelHtml(), /data-recs-val="Midwest" aria-pressed="true"/);
  assert.equal(pg.sb.S.recs.notices.length, 0);
});

// ---------- storage that is missing, corrupt, unavailable or from another version ----------

test('A10: corrupt JSON or the wrong shape starts the form empty, says so once, and rewrites nothing until a save', async () => {
  for (const raw of ['{"v":1,"prefs":', '[1,2]', '"text"', '{"prefs":{}}', '{"v":"1"}']) {
    const pg = await ready({ status: ON, storage: { 'cd.recs': raw } });
    await open(pg);
    assert.deepEqual(plain(pg.sb.S.recs.notices), ['corrupt'], raw);
    assert.match(pg.panelHtml(), /couldn’t be read, so the form starts empty/);
    assert.equal(pg.store.get('cd.recs'), raw, 'rewritten before a save');
    pg.sb.recsToggleValue('division', 'D1');
    assert.equal(pg.sb.recsApply(), true);
    assert.equal(saved(pg).v, 1);
  }
});

test('A10: storage that throws runs in memory and says the preferences won\'t be remembered; nothing throws', async () => {
  const pg = await ready({ status: ON, storage: 'throws' });
  await open(pg);
  assert.deepEqual(plain(pg.sb.S.recs.notices), ['unavailable']);
  pg.sb.recsToggleValue('size', 'lt5k');
  assert.equal(pg.sb.recsApply(), true);
  assert.match(pg.sb.S.recs.status, /^Preferences set for this visit only\./);
  assert.deepEqual(plain(pg.sb.S.recs.saved.size), { mode: 'prefer', values: ['lt5k'] });
  pg.sb.renderRecsPanel();
  assert.match(pg.panelHtml(), /won’t be remembered on this device/);
});

test('A10: a newer version is left untouched, the page says so, and saving never overwrites it', async () => {
  const newer = JSON.stringify({ v: 2, prefs: { anything: true }, hidden: ['stanford'] });
  const pg = await ready({ status: ON, storage: { 'cd.recs': newer } });
  await open(pg);
  assert.deepEqual(plain(pg.sb.S.recs.notices), ['newer']);
  pg.sb.recsToggleValue('region', 'South');
  assert.equal(pg.sb.recsApply(), true);
  assert.equal(pg.store.get('cd.recs'), newer);
  assert.match(pg.sb.S.recs.status, /for this visit only/);
});

test('A10: a removed value or a climate must is named, not silently dropped; unknown fields survive a save', async () => {
  const doc = { v: 1, prefs: { v: 1, region: { mode: 'prefer', values: ['Pacific', 'West'] }, climate: { mode: 'must', values: ['mild'] } },
    hidden: [{ slug: 'stanford', reason: 'size', at: '2026-10-01' }] };
  const pg = await ready({ status: ON, storage: { 'cd.recs': JSON.stringify(doc) } });
  await open(pg);
  assert.match(pg.panelHtml(), /no longer offered and were left out: Region “Pacific”, Climate “Must have”\./);
  assert.deepEqual(plain(pg.sb.S.recs.draft.region), { use: 'choose', values: ['West'], importance: 'prefer' });
  assert.equal(pg.sb.S.recs.draft.climate.use, 'skip');
  assert.equal(pg.store.get('cd.recs'), JSON.stringify(doc), 'cleaned before the visitor saved');
  assert.equal(pg.sb.recsApply(), true);
  assert.deepEqual(saved(pg).hidden, doc.hidden, 'a later PR\'s field was lost');
  assert.deepEqual(saved(pg).prefs.region, { mode: 'prefer', values: ['West'] });
});

test('recs.js failing to load shows a load-failed message with Try again, and Try again recovers', async () => {
  const pg = await ready({ status: ON, recsJs: false });
  await open(pg);
  assert.match(pg.panelHtml(), /The preferences form didn’t load\. <button type="button" class="btn" id="recsRetry">Try again<\/button>/);
  assert.equal(pg.store.has('cd.recs'), false);
  pg.sb.__recsJsOk = true;
  await pg.sb.recsOpen();
  await settle();
  assert.match(pg.panelHtml(), /<legend>Region<\/legend>/, 'Try again did not recover');
  assert.equal(pg.requests.filter((u) => u === 'recs.js').length, 2);
});

test('the form\'s regions are exactly the fit taxonomy\'s regions', async () => {
  const pg = await ready({ status: ON });
  assert.deepEqual([...pg.sb.REGIONS].sort(), Object.keys(CATALOG.constants.regions).sort());
});
