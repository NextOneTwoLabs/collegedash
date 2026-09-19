// The Honors box's all-time record (issue #221): shown only when games were counted, never "0-0-0 over 0 seasons".
//
//     node --test tests/honors_record.test.mjs
//
// build.py sums allTimeRecord over the Wikipedia seasons table. Every Division II program, and Division I pages
// without such a table, have none, so the sum is 0-0-0 over 0 seasons; a table whose rows carry no parsed results
// sums to 0-0-0 over N. The page printed both as a record. It now leaves the line out (#115: hide what is empty),
// and does not recompute it from p.seasons, which covers a few recent years, not all time.
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM (as tests/header_links.test.mjs does);
// fetch serves a public/ directory. Nothing leaves the process.
//
// What this proves:
//   - every committed profile: the History tab's all-time record row is present exactly when the record counts at
//     least one game, and no Honors box says 0-0-0 or "over 0 seasons" (a season table's own 0-0-0, such as a
//     conference record before conference play, is real data and not checked);
//   - a Division II profile generated from a real one, in the shape the D2 publish build has (Honors shown for its
//     national titles, no Wikipedia page, 0-0-0 over 0 seasons, a four-season table): no all-time record row, while
//     its championships and season table still render; with a counted record, the row is back;
//   - with HONORS_D2_PUBLIC pointing at a D2-published public/ directory (PR #220's branch), the same rule over every
//     profile in it (skipped, visibly, when not set);
//   - with HONORS_BASELINE_HTML pointing at the page before this change, every tab of every committed profile is
//     byte-identical to it apart from the all-time record row removed where it counted no games (skipped, visibly,
//     when not set).
//
// HONORS_HTML (optional) points at another copy of index.html, so a deliberately broken copy can be shown failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const PAGE = process.env.HONORS_HTML || path.join(PUBLIC, 'index.html');
const clone = (v) => JSON.parse(JSON.stringify(v));
const readJsonFrom = (dir, rel) => JSON.parse(fs.readFileSync(path.join(dir, rel), 'utf8'));
const TABS = ['overview', 'school', 'climate', 'history', 'staff', 'roster', 'commitments', 'schedule', 'news', 'camps'];

function makeElement(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null, matches: () => false, focus() { }, contains: () => false,
  };
}
function loadPage(html = PAGE, publicDir = PUBLIC, files = {}) {
  const els = new Map();
  const bySelector = (sel) => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector, querySelectorAll: () => [],
      addEventListener() { }, createElement: makeElement },
    location: { hash: '', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
    innerWidth: 1400, addEventListener() { }, alert() { },
    fetch: async (url) => {
      const ok = (body, st = 200) => ({ ok: st < 400, status: st, async json() { return clone(body); } });
      let u = String(url);
      if (files[u]) return ok(files[u]);
      if (u.startsWith('/api/v1/')) {
        const sub = u.slice('/api/v1/'.length);
        if (sub === 'programs') u = 'data/programs/index.json';
        else if (sub.startsWith('programs/')) u = `data/programs/${sub.slice('programs/'.length)}.json`;
        else if (sub === 'camps') u = 'data/camps/index.json';
        else if (sub === 'trends') u = 'data/trends/index.json';
        else if (sub === 'commitments') u = 'data/commitments/index.json';
        else if (sub === 'status') u = 'archive/refresh-state.json';
      }
      if (files[u]) return ok(files[u]);
      if (!u.startsWith('data/') && !u.startsWith('archive/')) return ok({}, 404);
      const p = path.join(publicDir, u);
      return fs.existsSync(p) ? ok(JSON.parse(fs.readFileSync(p, 'utf8'))) : ok({}, 404);
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(html, 'utf8').split(/\r?\n/);
  const a = lines.findIndex((l) => l.trim() === '<script>'), b = lines.findIndex((l) => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(['S', 'renderProfile', 'loadIndex'])}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  const $ = (sel) => sandbox.document.querySelector(sel);
  return { sb: sandbox, app: () => $('#app').innerHTML, tab: () => $('#tab').innerHTML };
}

const RECORD_ROW = /<tr><th>All-time record<\/th><td>[^<]*<\/td><\/tr>/;
// The Honors card only: a season table's own "0-0-0" (a conference record before conference play) is real data.
const honorsBox = (html) => { const i = html.indexOf('<h3>Honors</h3>'); return i < 0 ? null : html.slice(i, html.indexOf('</table>', i)); };
const counted = (p) => { const r = p.program?.allTimeRecord; return !!r && ((r.wins || 0) + (r.losses || 0) + (r.ties || 0)) > 0; };

// Every profile in publicDir: the History tab's record row is there exactly when the record counts a game.
async function checkAll(publicDir, label) {
  const index = readJsonFrom(publicDir, 'data/programs/index.json');
  const pg = loadPage(PAGE, publicDir); await pg.sb.loadIndex();
  const wrong = [];
  const tally = { shown: 0, hidden: 0, honors: 0, byDivision: {} };
  for (const row of index.programs) {
    const p = readJsonFrom(publicDir, `data/programs/${row.slug}.json`);
    await pg.sb.renderProfile(row.slug, 'history');
    const html = pg.tab();
    const honors = honorsBox(html);
    const hasHonors = honors !== null;
    const hasRow = RECORD_ROW.test(html);
    if (hasHonors) tally.honors++;
    if (hasRow) tally.shown++;
    if (hasHonors && !hasRow) { tally.hidden++; tally.byDivision[p.division] = (tally.byDivision[p.division] || 0) + 1; }
    if (/>0-0-0 /.test(honors || '')) wrong.push(`${row.slug}: the Honors box says 0-0-0`);
    if (/over 0 seasons/.test(honors || '')) wrong.push(`${row.slug}: the Honors box says "over 0 seasons"`);
    if (hasHonors && hasRow !== counted(p)) wrong.push(`${row.slug}: all-time record row ${hasRow ? 'shown' : 'missing'} (games counted: ${counted(p)})`);
  }
  assert.deepEqual(wrong, [], `${label}: ${wrong.length} History tabs disagree with the rule:\n  ${wrong.slice(0, 40).join('\n  ')}`);
  console.log(`# ${label}: ${index.programs.length} profiles, Honors on ${tally.honors}, record row shown ${tally.shown}, left out ${tally.hidden} ${JSON.stringify(tally.byDivision)}`);
  return tally;
}

test('every committed profile: the all-time record row shows exactly when it counts a game, and Honors never says 0-0-0', async () => {
  await checkAll(PUBLIC, 'committed data');
});

// A Division II profile in the shape the D2 publish build (PR #220) gives it, generated from a real committed one.
function d2Profile({ record }) {
  const index = readJsonFrom(PUBLIC, 'data/programs/index.json');
  const baseRow = index.programs.find((r) => r.division === 'D1' && readJsonFrom(PUBLIC, `data/programs/${r.slug}.json`).seasons?.length >= 4);
  const p = clone(readJsonFrom(PUBLIC, `data/programs/${baseRow.slug}.json`));
  const row = clone(baseRow);
  const slug = record ? 'generated-d2-counted' : 'generated-d2';
  Object.assign(p, { slug, name: `Generated ${slug}`, division: 'D2', conference: 'Test Division II Conference' });
  Object.assign(row, { slug, name: p.name, shortName: p.name, division: 'D2', conference: p.conference, nationalTitles: 3 });
  p.program = { ...p.program, nationalTitles: [2009, 2013, 2021], nationalRunnerUp: [], collegeCups: [], ncaaAppearances: [],
    confRegularSeasonTitles: [], confTournamentTitles: [], founded: null, stadium: null,
    allTimeRecord: record || { wins: 0, losses: 0, ties: 0, winPct: null, seasons: 0 },
    _meta: { ...p.program._meta, wikipedia: null } };
  p.seasons = p.seasons.slice(0, 4).map((s) => ({ ...s, rpiRank: null, rpi: null }));
  return { row, p };
}

test('generated Division II profile: Honors keeps its titles and season table, and leaves out 0-0-0 over 0 seasons', async () => {
  const zero = d2Profile({ record: null });
  const real = d2Profile({ record: { wins: 120, losses: 40, ties: 10, winPct: 0.735, seasons: 9 } });
  const index = { ...clone(readJsonFrom(PUBLIC, 'data/programs/index.json')) };
  index.programs = [...index.programs, zero.row, real.row];
  if (index.divisions && !index.divisions.includes('D2')) index.divisions = [...index.divisions, 'D2'];
  const pg = loadPage(PAGE, PUBLIC, { 'data/programs/index.json': index, [`data/programs/${zero.p.slug}.json`]: zero.p, [`data/programs/${real.p.slug}.json`]: real.p });
  await pg.sb.loadIndex();

  await pg.sb.renderProfile(zero.p.slug, 'history');
  const z = pg.tab();
  assert.ok(z.includes('<h3>Honors</h3>'), 'the generated D2 profile shows its Honors box (for its titles)');
  assert.ok(z.includes('<b>3</b> — 2009, 2013, 2021'), 'its championships still render');
  assert.ok(z.includes('<h3>Season by season</h3>'), 'its season table still renders');
  assert.doesNotMatch(honorsBox(z), />0-0-0 /, 'the Honors box says 0-0-0');
  assert.doesNotMatch(honorsBox(z), /over 0 seasons/, 'the Honors box says "over 0 seasons"');
  assert.doesNotMatch(z, RECORD_ROW, 'an all-time record row with no games counted is shown');

  await pg.sb.renderProfile(real.p.slug, 'history');
  const r = pg.tab();
  assert.match(r, /<tr><th>All-time record<\/th><td>120-40-10 \(0\.735\) over 9 seasons<\/td><\/tr>/, 'a counted record is shown as before');
});

const D2_PUBLIC = process.env.HONORS_D2_PUBLIC;
test('D2-published data (PR #220): every profile follows the rule, and no Honors box says 0-0-0',
  { skip: D2_PUBLIC ? false : 'set HONORS_D2_PUBLIC to a D2-published public/ directory (PR #220\'s branch) to run this' }, async () => {
    const t = await checkAll(D2_PUBLIC, 'D2-published data');
    assert.ok((t.byDivision.D2 || 0) > 0, 'the D2-published data has no Division II Honors box to check, so this proved nothing');
  });

const BASELINE = process.env.HONORS_BASELINE_HTML;
test('every tab of every committed profile is byte-identical to the page before #221 apart from uncounted record rows',
  { skip: BASELINE ? false : 'set HONORS_BASELINE_HTML to the pre-change public/index.html to run this comparison' }, async () => {
    const index = readJsonFrom(PUBLIC, 'data/programs/index.json');
    const before = loadPage(BASELINE), now = loadPage();
    await before.sb.loadIndex(); await now.sb.loadIndex();
    const problems = [];
    const changed = [];
    for (const row of index.programs) {
      const p = readJsonFrom(PUBLIC, `data/programs/${row.slug}.json`);
      for (const tab of TABS) {
        await before.sb.renderProfile(row.slug, tab); await now.sb.renderProfile(row.slug, tab);
        const a = before.app() + before.tab(), b = now.app() + now.tab();
        if (a === b) continue;
        const removedRow = a.replace(RECORD_ROW, '');
        if (tab !== 'history' || counted(p) || removedRow !== b) problems.push(`${row.slug}/${tab}: changed other than removing an uncounted all-time record row`);
        else changed.push(`${row.slug}(${row.division})`);
      }
    }
    assert.deepEqual(problems, []);
    console.log(`# profiles whose History lost an uncounted all-time record row: ${changed.length}: ${changed.join(', ')}`);
  });
