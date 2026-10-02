// Issue #416: commitments are collected for COMMIT_DIVISIONS (D1) only (#315), and the Commits column says "Not
// collected" outside it (#414). Fifteen D2/D3 programs still carry one or two commits SoccerWire happened to list, and
// their cards and profiles show that count - so the card and the column disagreed. Wherever a card or profile shows a
// count for a program outside COMMIT_DIVISIONS it now says "partial: not systematically collected", decided by the
// column's own commitsCollected. The sections themselves stay (per program, never by division: #94).
//
// Also (Huatuo, non-blocking on #431): a raw conference key such as "D2|Independent" never reaches rendered HTML.
//
//     node --test tests/commits_partial.test.mjs
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM, with the published data under public/.
// Expected programs come from index.json. Tests marked GUARD pass on main too, on purpose.
//
// COMMITS_PARTIAL_TEST_HTML (optional) points at another copy of index.html, so the page from before this change can
// be run through these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.COMMITS_PARTIAL_TEST_HTML || path.join(PUBLIC, 'index.html');
const PAGE = fs.readFileSync(HTML, 'utf8');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const NOTE = 'partial: not systematically collected';
const hasCommits = p => Object.keys(p.commitmentsByYear || {}).length > 0;
const PARTIAL = INDEX.programs.filter(p => p.division !== 'D1' && hasCommits(p));
const D1_WITH = INDEX.programs.filter(p => p.division === 'D1' && hasCommits(p));
const hasProfile = p => fs.existsSync(path.join(PUBLIC, 'data', 'programs', `${p.slug}.json`));

function loadPage() {
  const el = name => ({ _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, dataset: {}, style: {},
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false }, setAttribute() { }, getAttribute: () => null,
    addEventListener() { }, removeEventListener() { }, querySelector: () => el('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, contains: () => false });
  const els = new Map();
  const readPublic = url => {
    let rel = url.replace(/^\//, '').replace(/\?.*$/, '');
    if (rel.startsWith('api/v1/')) {
      const sub = rel.slice('api/v1/'.length);
      rel = sub === 'programs' ? 'data/programs/index.json' : sub.startsWith('programs/') ? `data/programs/${sub.slice(9)}.json`
        : sub === 'camps' ? 'data/camps/index.json' : rel;
    }
    const p = path.join(PUBLIC, rel);
    return p.startsWith(PUBLIC) && fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: el('html'), body: el('body'), addEventListener() { }, createElement: el, querySelectorAll: () => [],
      querySelector: s => { if (!els.has(s)) els.set(s, el(s)); return els.get(s); } },
    location: { hash: '', replace(h) { this.hash = h; } }, history: { replaceState() { } }, matchMedia: () => ({ matches: false }),
    innerWidth: 1400, addEventListener() { }, localStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    fetch: async url => {
      const body = readPublic(url);
      return body == null ? { ok: false, status: 404, async json() { throw new Error('404'); } }
        : { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = PAGE.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n')
    + '\n;Object.assign(globalThis, { S, loadIndex, cardHtml, tableHtml, renderProfile, renderCompare, renderList, renderCamps, renderSidebar, applyAsk });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  // a profile draws its frame into #app and the tab body into #tab (a separate element in the stub)
  const q = s => sandbox.document.querySelector(s).innerHTML;
  return { sb: sandbox, app: () => q('#app'), side: () => q('#sidebar'), profile: () => q('#app') + q('#tab') };
}
const { sb, app, side, profile } = loadPage();
const row = slug => sb.S.index.programs.find(p => p.slug === slug);
const partialIn = html => html.includes('class="commits-partial');

test('setup: fifteen programs outside D1 carry a count, carson-newman among them', async () => {
  await sb.loadIndex();
  assert.equal(PARTIAL.length, 15, `fixture: ${PARTIAL.length} programs outside D1 carry commits`);
  assert.ok(PARTIAL.some(p => p.slug === 'carson-newman'));
  assert.ok(D1_WITH.length > 100);
});

// #465 E: commits left the default card; they are its fact row when the list is sorted by Commits (or a class is
// highlighted), so the cards are checked in that state.
const sortedByCommits = fn => { const was = sb.S.filters.sort; sb.S.filters.sort = 'commits'; try { return fn(); } finally { sb.S.filters.sort = was; } };
test('cards: every one of the fifteen says "partial", and no D1 card with commits does', () => sortedByCommits(() => {
  for (const p of PARTIAL) {
    const html = sb.cardHtml(row(p.slug));
    assert.ok(partialIn(html), `${p.slug}: the card shows its count without the note`);
    assert.match(html, /\(partial<span class="sr-only">: not systematically collected<\/span>\)/, `${p.slug}: the card's note text`);
  }
  for (const p of D1_WITH) assert.ok(!partialIn(sb.cardHtml(row(p.slug))), `${p.slug} (D1): the note is on a collected program`);
}));

test('the card and the Commits column now agree, by the same rule', () => {
  const cn = row('carson-newman');
  assert.match(sb.tableHtml([cn]), /<span class="sr-only">Not collected<\/span>/, 'the column says Not collected');
  assert.ok(sortedByCommits(() => partialIn(sb.cardHtml(cn))), 'the card shows the count without saying it is partial');
  const fn = /const commitsPartial = \(p, short = false\) => ([^\n]*)/.exec(PAGE)?.[1] || '';
  assert.match(fn, /^commitsCollected\(p\)/, 'the note does not use the column\'s commitsCollected');
});

test('profile (carson-newman): the glance, the overview tile, the Commitments tab and Compare carry the note; the section stays', async () => {
  sb.location.hash = '#/p/carson-newman';
  await sb.renderProfile('carson-newman');
  const html = profile();
  assert.ok((html.match(/class="commits-partial/g) || []).length >= 2, 'the glance panel and the overview tile should both carry the note');
  assert.ok(html.includes(`(${NOTE})`));
  assert.ok(html.includes('href="#/p/carson-newman/commitments"'), 'GUARD (#94): the Commitments tab is still offered');
  await sb.renderProfile('carson-newman', 'commitments');
  assert.match(profile(), new RegExp(`\\(${NOTE}\\)</span> Commitments are collected for Division I programs only`), 'the Commitments tab\'s note');
  const d1 = D1_WITH.find(hasProfile);
  sb.S.compare = ['carson-newman', d1.slug];
  await sb.renderCompare();
  const cmp = app();
  assert.equal((cmp.match(/class="commits-partial/g) || []).length, 1, 'Compare: exactly the carson-newman cell carries the note');
});

test('GUARD: a D1 program with commits carries no note on its profile', async () => {
  const d1 = D1_WITH.find(hasProfile);
  sb.location.hash = `#/p/${d1.slug}`;
  await sb.renderProfile(d1.slug);
  assert.ok(!partialIn(profile()), `${d1.slug}: overview`);
  assert.ok(profile().includes('<dt>Commitments</dt>'), `${d1.slug}: fixture - its glance should show a count`);
  await sb.renderProfile(d1.slug, 'commitments');
  assert.ok(!partialIn(profile()), `${d1.slug}: Commitments tab`);
  assert.ok(profile().includes('Class of '), `${d1.slug}: fixture - its Commitments tab should list a class`);
});

test('GUARD (#431): a raw conference key never reaches rendered HTML', async () => {
  const reset = st => Object.assign(sb.S.filters, { conf: [], region: [], division: [], classYear: [], cond: [], sort: 'name', sortDir: null, view: 'cards' }, st);
  const raw = /D[123]\|[A-Z]/;
  for (const view of ['cards', 'table']) {
    reset({ conf: ['D2|Independent', 'D1|ACC'], view });
    sb.location.hash = '#/';
    sb.S.sidebarTab = 'programs';
    sb.renderSidebar();
    await sb.renderList();
    assert.doesNotMatch(app(), raw, `${view}: a raw key in the list`);
    assert.doesNotMatch(side(), raw, `${view}: a raw key in the sidebar`);
  }
  sb.location.hash = '#/camps';
  await sb.renderCamps();
  assert.doesNotMatch(app(), raw, 'a raw key on the camp view');
  sb.location.hash = '#/';
  reset({});
  sb.applyAsk({ conf: ['Independent'], division: ['D2'], region: [], classYear: [], cond: [], sort: null, reading: '' });
  await sb.renderList();
  assert.doesNotMatch(app(), raw, 'a raw key in the Ask banner');
  reset({}); sb.S.askResult = null;
});
