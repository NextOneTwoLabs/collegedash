// Tests for the ID Camp View (#/camps) in public/index.html - issue #65.
//
//     node --test tests/camps_view.test.mjs
//
// Node rather than Python because the thing under test is the page's JavaScript; the repo's Python
// suites cover build.py and the collectors and none of them renders public/index.html. No
// dependencies: the inline <script> is pulled out of the HTML and run in a `vm` against a stub DOM,
// so what runs is the real source text of the real file rather than a copy that can drift.
//
// What this proves:
//   - the Program View's row selection AND ordering are unchanged by the matchesFilters extraction,
//     across 400 region x conference x search x sort states on the real 350-program index;
//   - the camp view renders only campType === 'id', in fixed date order, joined by slug;
//   - the hidden-row count is on the page, names every class even at zero, and adds up;
//   - all three empty states appear when they should;
//   - the tab strip is on the programs list and the camp view and NOT on the shortlist;
//   - the sidebar drops the sort select and the recruiting-class pills in the camp view and hands
//     them back with f.sort and f.classYear untouched;
//   - the camps index is not fetched until the camp view is first opened.
//
// What it CANNOT prove, and a human must check in a browser: layout and the tab strip at phone
// width, focus and scroll behaviour, that a row click really navigates, and that the lazy fetch
// does not fire on first paint in a real browser. The DOM here is a stub that records innerHTML
// and swallows everything else.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');

/* ---------- a stub DOM: enough for the page to load and render into ---------- */
function makeElement(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, contains: () => false,
  };
}

function makeEnv(fetchLog) {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
  const readPublic = url => {
    let rel = url.replace(/^\//, '');
    if (rel.startsWith('api/v1/')) {
      const sub = rel.slice('api/v1/'.length);
      if (sub === 'programs') rel = 'data/programs/index.json';
      else if (sub.startsWith('programs/')) rel = `data/programs/${sub.slice('programs/'.length)}.json`;
      else if (sub === 'camps') rel = 'data/camps/index.json';
      else if (sub === 'trends') rel = 'data/trends/index.json';
      else if (sub === 'commitments') rel = 'data/commitments/index.json';
      else if (sub === 'status') rel = 'archive/refresh-state.json';
    }
    const p = path.join(PUBLIC, rel);
    return p.startsWith(PUBLIC) && fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: {
      documentElement: makeElement('html'), body: makeElement('body'),
      querySelector: bySelector, querySelectorAll: () => [], createElement: makeElement,
      // #93: document-level listeners are kept, so a test can hand them an event the way the browser would
      _handlers: {}, addEventListener(type, fn) { (this._handlers[type] ||= []).push(fn); },
    },
    location: { hash: '', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: {
      getItem: k => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k),
    },
    innerWidth: 1400,
    addEventListener() { },
    fetch: async url => {
      fetchLog.push(url);
      const body = readPublic(url);
      if (body == null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  return sandbox;
}

function loadPage() {
  const lines = fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>');
  const b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'public/index.html: could not find the inline <script>');
  // The page declares everything with const/let, which in a vm script lands in the script's own
  // lexical scope rather than on globalThis. One appended line hands the test the handles it needs;
  // everything above it is the file untouched, so what runs is exactly what ships.
  const source = lines.slice(a + 1, b).join('\n');
  const src = source
    + '\n;Object.assign(globalThis, { S, filteredPrograms, matchesFilters, matchScore, sortCmp, normText,'
    + ' renderCamps, renderList, renderShortlist, renderSidebar, loadIndex, loadCamps, campTally, campCmp });\n';
  const fetchLog = [];
  const sandbox = makeEnv(fetchLog);
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sandbox, fetchLog, source };
}

/* The Program View exactly as it stood before #65, copied verbatim from filteredPrograms on
 * origin/main at c0366a1d - the commit this branch is cut from. If the matchesFilters extraction
 * changed anything at all, this and the shipped function disagree. */
function filteredProgramsBefore(S, matchScore, sortCmp) {
  const idx = S.index, f = S.filters;
  const score = new Map();
  idx.programs.forEach(p => { const m = S.q ? matchScore(p, S.q) : null; p._why = m?.why || null; if (m) score.set(p.slug, m.score); });
  const rows = idx.programs.filter(p => (!S.q || score.has(p.slug)) && (!f.conf.length || f.conf.includes(p.conference)) && (!f.region.length || f.region.includes(p.region)));
  rows.sort((a, b) => (S.q ? (score.get(b.slug) - score.get(a.slug)) : 0) || sortCmp(f.sort)(a, b));
  return rows;
}

/* ---------- shared state: tests in one file run in order, and these build on each other ---------- */
const { sandbox, fetchLog, source } = loadPage();
const S = sandbox.S;
const app = () => sandbox.document.querySelector('#app').innerHTML;
const sidebar = () => sandbox.document.querySelector('#sidebar').innerHTML;
const published = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data/camps/index.json'), 'utf8'));
let fixture, pa, pb, pc, pd;

test('the camps index is not fetched until the camp view is opened', async () => {
  await sandbox.loadIndex();
  await new Promise(r => setTimeout(r, 0));
  assert.ok(!fetchLog.some(u => u.includes('camps')), `unexpected fetches: ${fetchLog.join(', ')}`);
});

test('the Program View is unchanged by the matchesFilters extraction', () => {
  const confs = [...new Set(S.index.programs.map(p => p.conference).filter(Boolean))].sort();
  const matrix = [];
  for (const region of [[], ['West'], ['Northeast'], ['Midwest', 'South'], ['Mid-Atlantic']])
    for (const conf of [[], [confs[0]], [confs[3], confs[7]], ['Not A Conference']])
      for (const q of ['', 'stanford', 'state', 'u', 'zzzz'])
        for (const sort of ['rpi', 'name', 'academicRank', 'tuition'])
          matrix.push({ region, conf, q, sort });
  assert.ok(matrix.length >= 300, `the matrix is only ${matrix.length} states wide`);

  for (const c of matrix) {
    S.filters.region = c.region.slice(); S.filters.conf = c.conf.slice(); S.filters.sort = c.sort;
    S.qRaw = c.q; S.q = sandbox.normText(c.q);
    const after = sandbox.filteredPrograms().map(p => p.slug);
    const before = filteredProgramsBefore(S, sandbox.matchScore, sandbox.sortCmp).map(p => p.slug);
    assert.deepEqual(after, before, `filter state ${JSON.stringify(c)} selects a different list than it used to`);
  }

  // and the predicate on its own, over every program
  S.filters.region = ['West']; S.filters.conf = [confs[0]]; S.q = ''; S.qRaw = '';
  const direct = S.index.programs.filter(p => sandbox.matchesFilters(p, null)).map(p => p.slug).sort();
  assert.deepEqual(direct, sandbox.filteredPrograms().map(p => p.slug).sort());

  S.filters.region = []; S.filters.conf = []; S.filters.sort = 'rpi'; S.filters.classYear = ['2027'];
  S.q = ''; S.qRaw = '';
});

test('the published camps index renders as it actually is today', async () => {
  // Whatever the index currently holds - including a pre-#85 file whose rows carry no campType and
  // which therefore yields nothing - the view must render it without throwing, and its row count
  // must equal the id rows that join to a program.
  sandbox.location.hash = '#/camps';
  await sandbox.renderCamps();
  assert.ok(fetchLog.includes('/api/v1/camps') || fetchLog.includes('data/camps/index.json'), 'opening the camp view did not fetch the index');

  const bySlug = new Map(S.index.programs.map(p => [p.slug, p]));
  const idRows = (published.camps || []).filter(c => c.campType === 'id');
  const resolvable = idRows.filter(c => bySlug.has(c.slug));
  assert.equal((app().match(/<tr class="team-row"/g) || []).length, resolvable.length);
  assert.deepEqual(idRows.filter(c => !bySlug.has(c.slug)).map(c => c.slug), [],
    'a published id row names a program the index does not carry');
  assert.deepEqual(idRows.filter(c => !c.startDate).map(c => c.name), [],
    'an id row with no start date has nowhere to go in a date-ordered view');

  if (published.counts) {
    const derived = { total: (published.camps || []).length, id: 0, youth: 0, unknown: 0 };
    (published.camps || []).forEach(c => { if (['id', 'youth', 'unknown'].includes(c.campType)) derived[c.campType]++; });
    assert.equal(derived.id, published.counts.id, 'the index\'s declared counts disagree with its own rows');
    assert.equal(sandbox.campTally(S.camps).id, published.counts.id, 'the view ignores the index\'s own counts');
  }
});

test('the published index declares a sane window', () => {
  assert.ok(published.window && published.window.from, 'the index does not declare its window');
  assert.ok(published.window.from <= new Date().toISOString().slice(0, 10), 'the window starts in the future');
  const stray = (published.camps || []).filter(c => c.startDate && (c.endDate || c.startDate) < published.window.from);
  assert.deepEqual(stray.map(c => c.name), [], 'a published row falls before the declared window');
});

test('the camp view shows only id camps, in date order, joined to the right programs', async () => {
  // The published index is a moving target - rebuilt daily, and legitimately empty in some months.
  // The row shape, the ordering and the counts are pinned against a fixture so a failure here means
  // the view changed and not that the season did. The slugs are real, so the join is a real join.
  [pa, pb, pc, pd] = S.index.programs.slice(0, 4);
  fixture = {
    updated: '2026-09-14T20:56:27Z', window: { from: '2026-09-14', to: null },
    counts: { total: 7, id: 4, youth: 1, unknown: 2 },
    camps: [
      { slug: pc.slug, name: 'Late ID Camp', startDate: '2027-01-30', endDate: '2027-01-30', precision: 'day', campType: 'id', kind: 'camp', confidence: 'heuristic', location: 'Home field', ages: '9th - 12th', price: '$200', registerUrl: 'https://example.org/register', sourceUrl: 'https://example.org/camps' },
      { slug: pa.slug, name: 'First ID Camp', startDate: '2026-10-01', endDate: '2026-10-02', precision: 'day', campType: 'id', kind: 'camp', confidence: 'verified', location: null, ages: null, price: null, registerUrl: null, sourceUrl: 'https://example.org/a' },
      { slug: pb.slug, name: 'Middle Prospect Camp', startDate: '2026-11-15', endDate: null, precision: 'day', campType: 'id', kind: 'news', confidence: 'heuristic', yearInferred: true, location: 'Stadium', ages: null, price: '$150', registerUrl: 'javascript:alert(1)', sourceUrl: 'https://example.org/b' },
      { slug: pd.slug, name: 'Little Kickers Day Camp', startDate: '2026-12-01', campType: 'youth', kind: 'camp' },
      { slug: pa.slug, name: '2026 Soccer Camps', startDate: '2026-10-20', campType: 'unknown', kind: 'camp' },
      { slug: pb.slug, name: 'Winter Soccer Camps', startDate: '2026-12-20', campType: 'unknown', kind: 'camp' },
      // an id row whose slug the program index does not carry: rendered nowhere, admitted in the footnote
      { slug: 'no-such-program', name: 'Orphan ID Camp', startDate: '2026-10-05', campType: 'id', kind: 'camp' },
    ],
  };
  S.camps = fixture;
  sandbox.location.hash = '#/camps';
  await sandbox.renderCamps();
  const html = app();

  assert.equal((html.match(/<tr class="team-row"/g) || []).length, 3, 'expected exactly the three joinable id rows');
  assert.ok(!html.includes('Little Kickers'), 'a youth camp reached the view');
  assert.ok(!html.includes('2026 Soccer Camps'), 'an unclassified camp reached the view');
  assert.ok(!html.includes('Orphan ID Camp'), 'a row with an unjoinable slug reached the view');
  assert.ok(html.includes('<th>When</th><th>Camp</th><th>Program</th><th>Details</th><th>Links</th>'));
  assert.ok(html.includes('Upcoming ID camps'));
  assert.ok(html.includes('soonest first'), 'the subtitle does not state the fixed order');
  assert.ok(!/sorted by /.test(html), 'the subtitle claims a sort the visitor cannot change');
  assert.ok(html.includes('3 upcoming ID camps at 3 programs'), 'the subtitle miscounts rows or programs');

  const order = [...html.matchAll(/<tr class="team-row" data-slug="([^"]+)"/g)].map(m => m[1]);
  assert.deepEqual(order, [pa.slug, pb.slug, pc.slug], 'rows are not in soonest-first order');
  const starts = fixture.camps.filter(c => c.campType === 'id').slice().sort(sandbox.campCmp).map(c => c.startDate);
  assert.deepEqual(starts, [...starts].sort(), 'campCmp is not start-date ascending');
  assert.ok(html.includes(`href="#/p/${pa.slug}/camps"`), 'the program cell does not link to its ID Camps tab');
  assert.ok(html.includes(pa.shortName || pa.name), 'the program cell does not name the program');
  assert.ok(html.includes('>register</a>') && html.includes('>source</a>'));
  assert.ok(!html.includes('javascript:alert(1)'), 'a non-http(s) registerUrl became a link');
  assert.ok(html.includes('year inferred') && html.includes('auto-detected') && html.includes('from news release'),
    'the shared badges did not render');
  assert.ok(!html.includes('>past<'), 'an upcoming-only view badged something past');
});

test('the hidden count is on the page, names every class, and adds up', () => {
  const t = sandbox.campTally(fixture);
  assert.equal(t.total, t.id + t.youth + t.unknown + t.unlabelled);
  const html = app();
  assert.ok(html.includes("Women's soccer ID and prospect camps only."));
  assert.ok(html.includes('3 of 7 upcoming camps are not shown here'), 'the hidden count is missing or wrong');
  assert.ok(html.includes("1 youth or kids' camp,"), 'the youth class is not named');
  assert.ok(html.includes('2 we could not classify'), 'the unclassified rows are not named');
  assert.ok(html.includes('could not be matched to a program'), 'an unjoinable row was dropped in silence');
  assert.ok(html.includes('Programs whose camp page we could not read do not appear here'), 'issue #79 is not admitted');
  assert.ok(html.includes('Camp list checked'), 'the footnote does not date the camp list');
});

test('the tab strip is on the list and the camp view, and not on the shortlist', async () => {
  const camps = app();
  assert.ok(camps.includes('>Cards</button>') && camps.includes('>Stats</button>') && camps.includes('>ID Camps</a>'));
  // #342: the tab reads Stats and keeps the view key `table`, so stored choices and old links still open it
  assert.ok(camps.includes('data-view="table">Stats</button>') && !camps.includes('>Table</button>'), 'the tab is not "Stats" on view key table');
  assert.ok(camps.includes('class="view-tab active" role="tab" aria-selected="true">ID Camps</a>'));
  sandbox.location.hash = '#/';
  await sandbox.renderList();
  assert.ok(app().includes('href="#/camps"'), 'the programs list is missing the ID Camps tab');
  await sandbox.renderShortlist();
  assert.ok(!app().includes('#/camps'), 'the shortlist carries a strip it should not - camps are not shortlist-scoped');
});

test('the sidebar drops sort and recruiting class in the camp view and hands them back intact', () => {
  sandbox.location.hash = '#/camps';
  sandbox.renderSidebar();
  const onCamps = sidebar();
  assert.ok(!onCamps.includes('id="sortSelect"'), 'the sort select is still there');
  assert.ok(!onCamps.includes('Recruiting class'), 'the recruiting-class pills are still there');
  assert.ok(!onCamps.includes('cards / stats'), 'the c shortcut hint, inert here, is still there');
  assert.ok(onCamps.includes('aria-label="Region"') && onCamps.includes('aria-label="Conference"'),
    'region or conference went missing');

  sandbox.location.hash = '#/';
  sandbox.renderSidebar();
  const onList = sidebar();
  assert.ok(onList.includes('id="sortSelect"'), 'the sort select did not come back');
  assert.ok(onList.includes('Recruiting class'), 'the recruiting-class pills did not come back');
  assert.ok(onList.includes('cards / stats'), 'the c shortcut hint did not come back');
  assert.equal(S.filters.sort, 'rpi', 'f.sort was written while the camp view was open');
  assert.deepEqual(S.filters.classYear, ['2027'], 'f.classYear was written while the camp view was open');

  const body = source.slice(source.indexOf('async function renderCamps'), source.indexOf('/* ---------- profile'));
  assert.ok(!/f\.sort\s*=|filters\.sort\s*=|f\.classYear\s*=|filters\.classYear\s*=/.test(body),
    'renderCamps assigns f.sort or f.classYear');
});

test('a filter that yields nothing says so, counts the unfiltered set and offers a way out', async () => {
  // On a 37-row view this is the common case, not the exception: regional coverage is thin and most
  // conferences have no upcoming camp at all.
  sandbox.location.hash = '#/camps';
  S.camps = fixture;
  S.filters.conf = ['Not A Conference'];
  await sandbox.renderCamps();
  const html = app();
  S.filters.conf = [];
  assert.ok(html.includes('No upcoming ID camps match these filters'));
  assert.ok(html.includes('Clear filters'), 'no control to clear the filter');
  assert.ok(html.includes('Not A Conference'), 'the empty state does not name the filter that emptied it');
  assert.ok(html.includes('3 upcoming ID camps are published across all programs'), 'no unfiltered count');
  assert.ok(html.includes('3 of 7 upcoming camps are not shown here'),
    'the hidden count collapsed under a filter instead of staying site-wide');
});

test('an index with nothing to show reads as empty, not as broken', async () => {
  S.camps = { updated: published.updated, window: published.window, counts: { total: 0, id: 0, youth: 0, unknown: 0 }, camps: [] };
  await sandbox.renderCamps();
  assert.ok(app().includes('No upcoming ID camps are published right now'));
  assert.ok(app().includes('All 0 upcoming camps we publish are shown here.'), 'the footnote is not honest at zero');
});

test('an index published without campType is reported rather than silently rendered as empty', async () => {
  // The pre-#78 shape. The view must never classify, so it cannot repair these rows - but it must
  // not let them vanish without a word either.
  S.camps = { updated: published.updated, window: published.window, counts: null, camps: [{ slug: 'ucla', name: 'x' }, { slug: 'duke', name: 'y' }] };
  await sandbox.renderCamps();
  assert.ok(app().includes('2 published without a classification'));
});

/* ---------- #93: the hidden-count footnote tells the truth when the index's own tally is wrong ---------- */
const campRow = (slug, campType, d) => ({ slug, name: `Example ${campType} camp`, campType, startDate: d, endDate: d, precision: 'day' });

test('#93 a tally that under-counts the rows: the footnote counts the rows and says the index disagrees', async () => {
  const [p1, p2] = S.index.programs;
  S.camps = { updated: published.updated, window: published.window, counts: { total: 2, id: 2, youth: 0, unknown: 0 },
    camps: [campRow(p1.slug, 'id', '2030-06-01'), campRow(p2.slug, 'id', '2030-06-02'),
            campRow(p1.slug, 'youth', '2030-06-03'), campRow(p2.slug, 'youth', '2030-06-04'), campRow(p1.slug, 'unknown', '2030-06-05')] };
  await sandbox.renderCamps();
  const html = app();
  assert.ok(html.includes('3 of 5 upcoming camps are not shown here'), 'the footnote trusted the index\'s counts over the rows it received');
  assert.ok(!html.includes('All 2 upcoming camps we publish are shown here'), 'a wrong tally was reported as reassurance');
  assert.ok(html.includes("The camp list's own tally (2 camps, 2 ID) does not match the rows it carries (5 camps, 2 ID)"), 'the disagreement is not said');
});

test('#93 a tally whose classes exceed its total (a negative difference) is an error, not "All N shown"', async () => {
  const [p1] = S.index.programs;
  S.camps = { updated: published.updated, window: published.window, counts: { total: 1, id: 3, youth: 0, unknown: 0 },
    camps: [campRow(p1.slug, 'id', '2030-07-01'), campRow(p1.slug, 'youth', '2030-07-02'), campRow(p1.slug, 'youth', '2030-07-03')] };
  await sandbox.renderCamps();
  const html = app();
  assert.ok(!html.includes('All 1 upcoming camps we publish are shown here'), 'Math.max(0, …) turned a corrupt tally into reassurance');
  assert.ok(html.includes('2 of 3 upcoming camps are not shown here'), 'the rows were not counted');
  assert.ok(html.includes('does not match the rows it carries'), 'the corrupt tally is not reported');
  const t = sandbox.campTally(S.camps);
  assert.equal(t.total, t.id + t.youth + t.unknown + t.unlabelled, 'the tally does not add up');
});

test('#93 a tally that agrees with its rows adds no note', async () => {
  const [p1] = S.index.programs;
  S.camps = { updated: published.updated, window: published.window, counts: { total: 2, id: 1, youth: 1, unknown: 0 },
    camps: [campRow(p1.slug, 'id', '2030-08-01'), campRow(p1.slug, 'youth', '2030-08-02')] };
  await sandbox.renderCamps();
  assert.ok(app().includes('1 of 2 upcoming camps are not shown here') && !app().includes('does not match the rows'));
});

/* ---------- #93: Space activates the link tabs as it does the button tabs ----------
   Proven through the page's own document keydown handler with a stub event: the in-app browser does
   not deliver real key presses, so a person should still press Space on the ID Camps tab once. */
function keyOn(target, key) {
  const ev = { key, target, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() { } };
  for (const fn of sandbox.document._handlers.keydown || []) fn(ev);
  return ev;
}
function tabTarget(isLinkTab) {
  const t = { clicks: 0, click() { this.clicks++; } };
  t.matches = sel => (sel === 'input, select, textarea' ? false : sel === 'a.view-tab[role="tab"]' ? isLinkTab : false);
  return t;
}

test('#93 Space on the ID Camps (link) tab activates it, and is not a page scroll', () => {
  const tab = tabTarget(true);
  const ev = keyOn(tab, ' ');
  assert.equal(tab.clicks, 1, 'Space did not activate the link tab');
  assert.ok(ev.defaultPrevented, 'Space would also scroll the page');
});

test('#93 Space elsewhere is left alone; Enter on the link tab is left to the browser', () => {
  const other = tabTarget(false);
  const ev = keyOn(other, ' ');
  assert.equal(other.clicks, 0);
  assert.ok(!ev.defaultPrevented, 'Space was swallowed outside the tab strip');
  const tab = tabTarget(true);
  keyOn(tab, 'Enter');
  assert.equal(tab.clicks, 0, 'Enter is the browser\'s own activation for a link; a second click would double it');
});
