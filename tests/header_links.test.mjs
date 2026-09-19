// Profile header links follow the per-program hide-empty rule (issue #206, #115).
//
//     node --test tests/header_links.test.mjs
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM (as tests/ask_page.test.mjs does);
// fetch serves public/ plus profiles generated here. Nothing leaves the process.
//
// What this proves:
//   - on every committed profile, a section's header link (Roster, Schedule, News, Camps, and TopDrawerSoccer
//     for Commitments) shows exactly when the profile has a URL for it AND the page offers that section's tab;
//     the Athletics site, Wikipedia, X and Instagram links show whenever the profile has a URL;
//   - generated from a real profile with every section emptied: those four section links go, the others stay;
//     with the sections filled, all of them show;
//   - with HEADER_LINKS_BASELINE_HTML pointing at the page from before this change, every tab of every committed
//     profile is byte-identical to it apart from the header links, and the header differs only by section links
//     taken away (skipped, visibly, when it is not set: CI has no pre-change copy of the page).
//
// HEADER_LINKS_HTML (optional) points at another copy of index.html, so a deliberately broken copy can be shown
// failing through these same checks.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const PAGE = process.env.HEADER_LINKS_HTML || path.join(PUBLIC, 'index.html');
const clone = (v) => JSON.parse(JSON.stringify(v));
const readJson = (rel) => JSON.parse(fs.readFileSync(path.join(PUBLIC, rel), 'utf8'));
const INDEX = readJson('data/programs/index.json');
const TABS = ['overview', 'school', 'climate', 'history', 'staff', 'roster', 'commitments', 'schedule', 'news', 'camps'];

// header link key -> [its label in the header, the label of the tab it belongs to (null: not a section link)]
const LINKS = {
  athletics: ['Athletics site', null], wikipedia: ['Wikipedia', null], x: ['X', null], instagram: ['Instagram', null],
  roster: ['Roster', 'Roster'], schedule: ['Schedule', 'Schedule'], news: ['News', 'News'], camps: ['Camps', 'ID Camps'],
  tds: ['TopDrawerSoccer', 'Commitments'],
};

function makeElement(name) {
  const listeners = {};
  return {
    _name: name, _listeners: listeners, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    removeEventListener() { }, querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, contains: () => false,
  };
}
function loadPage(html = PAGE, files = {}) {
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
      const p = path.join(PUBLIC, u);
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
const LINKS_BLOCK = /<div class="ext-links">([\s\S]*?)<\/div><\/div>\s*<\/div>/;
const headerLinks = (html) => [...((html.match(LINKS_BLOCK) || [])[1] || '').matchAll(/<\/svg>([^<]*)<\/a>/g)].map((m) => m[1].trim());
const tabLabels = (html) => [...html.matchAll(/class="view-tab[^"]*"[^>]*>([^<]*)<\/a>/g)].map((m) => m[1]);
async function header(pg, slug) {
  await pg.sb.renderProfile(slug, 'overview');
  return { links: headerLinks(pg.app()), tabs: tabLabels(pg.app()) };
}

test('every committed profile: a section link shows exactly when its tab does; other links whenever there is a URL', async () => {
  const pg = loadPage(); await pg.sb.loadIndex();
  const wrong = [];
  let sectionLinksHidden = 0;
  for (const row of INDEX.programs) {
    const p = readJson(`data/programs/${row.slug}.json`);
    const { links, tabs } = await header(pg, row.slug);
    for (const [key, [label, tabLabel]] of Object.entries(LINKS)) {
      const url = !!(p.links || {})[key];
      const expected = url && (tabLabel === null || tabs.includes(tabLabel));
      if (url && !expected) sectionLinksHidden++;
      if (links.includes(label) !== expected) wrong.push(`${row.slug}: ${label} ${links.includes(label) ? 'shown' : 'missing'} (url ${url}, tab ${tabLabel === null ? 'n/a' : tabs.includes(tabLabel)})`);
    }
    assert.ok(links.length === new Set(links).size, `${row.slug}: a header link is repeated`);
  }
  assert.deepEqual(wrong, [], `${wrong.length} header links disagree with the rule:\n  ${wrong.slice(0, 40).join('\n  ')}`);
  // informational, and true of today's data: some committed profile does lose a link, so this is not vacuous
  console.log(`# header links hidden by the rule across ${INDEX.programs.length} committed profiles: ${sectionLinksHidden}`);
});

// A real profile, with its links kept and its sections emptied or kept.
const BASE_SLUG = 'north-carolina';
function generated(slug, { empty }) {
  const p = clone(readJson(`data/programs/${BASE_SLUG}.json`));
  const row = clone(INDEX.programs.find((r) => r.slug === BASE_SLUG));
  p.slug = row.slug = slug;
  p.name = row.name = `Generated ${slug}`;
  p.links = { athletics: 'https://example.invalid/athletics', roster: 'https://example.invalid/roster', schedule: 'https://example.invalid/schedule',
    news: 'https://example.invalid/news', camps: 'https://example.invalid/camps', tds: 'https://example.invalid/tds',
    wikipedia: 'https://example.invalid/wiki', x: 'https://example.invalid/x', instagram: 'https://example.invalid/ig' };
  if (empty) {
    p.roster = null; p.schedule = null; p.news = null; p.commitments = []; p.commitmentsByYear = {};
    p.camps = { items: [], url: null }; p._build = { ...p._build, skipped: [], failed: [] };
  } else {
    p.camps = { ...(p.camps || {}), url: p.camps?.url || 'https://example.invalid/camps-page' };
    if (!(p.commitments || []).length) p.commitments = [{ name: 'A Player', gradYear: 2027 }];
  }
  return { row, p };
}
test('generated: with every section emptied only the section links go; with them filled, every link shows', async () => {
  const emptied = generated('generated-empty', { empty: true }), full = generated('generated-full', { empty: false });
  const index = { ...clone(INDEX), programs: [...clone(INDEX.programs), emptied.row, full.row] };
  const pg = loadPage(PAGE, { 'data/programs/index.json': index, 'data/programs/generated-empty.json': emptied.p, 'data/programs/generated-full.json': full.p });
  await pg.sb.loadIndex();
  const e = await header(pg, 'generated-empty');
  for (const tab of ['Roster', 'Schedule', 'News', 'ID Camps', 'Commitments']) assert.ok(!e.tabs.includes(tab), `generator did not empty ${tab}`);
  assert.deepEqual(e.links, ['Athletics site', 'Wikipedia', 'X', 'Instagram'], 'emptied profile: header links');
  const f = await header(pg, 'generated-full');
  for (const tab of ['Roster', 'Schedule', 'News', 'ID Camps', 'Commitments']) assert.ok(f.tabs.includes(tab), `generator did not fill ${tab}`);
  assert.deepEqual(f.links, ['Athletics site', 'Roster', 'Schedule', 'News', 'Camps', 'TopDrawerSoccer', 'Wikipedia', 'X', 'Instagram'], 'filled profile: header links');
});

const BASELINE = process.env.HEADER_LINKS_BASELINE_HTML;
test('every tab of every committed profile is byte-identical to the page before #206 apart from section links taken away', { skip: BASELINE ? false : 'set HEADER_LINKS_BASELINE_HTML to the pre-change public/index.html to run this comparison' }, async () => {
  const before = loadPage(BASELINE), now = loadPage();
  await before.sb.loadIndex(); await now.sb.loadIndex();
  const problems = [];
  let changedProfiles = 0;
  for (const row of INDEX.programs) {
    let changed = false;
    for (const tab of TABS) {
      await before.sb.renderProfile(row.slug, tab); await now.sb.renderProfile(row.slug, tab);
      const a = before.app(), b = now.app();
      if (a.replace(LINKS_BLOCK, '[links]') !== b.replace(LINKS_BLOCK, '[links]') || before.tab() !== now.tab()) problems.push(`${row.slug}/${tab}: something besides the header links changed`);
      const la = headerLinks(a), lb = headerLinks(b);
      if (lb.some((l) => !la.includes(l))) problems.push(`${row.slug}/${tab}: a link was added: ${lb.filter((l) => !la.includes(l))}`);
      if (la.filter((l) => !lb.includes(l)).some((l) => !['Roster', 'Schedule', 'News', 'Camps', 'TopDrawerSoccer'].includes(l))) problems.push(`${row.slug}/${tab}: a non-section link was removed`);
      if (la.join() !== lb.join()) changed = true;
    }
    if (changed) changedProfiles++;
  }
  assert.deepEqual(problems, []);
  console.log(`# profiles whose header links changed: ${changedProfiles}`);
});
