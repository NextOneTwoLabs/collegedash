// The page reads the slim list (issue #395, PR B): /api/v1/list instead of the full index at /api/v1/programs.
//
// Approved plan: https://github.com/NextOneTwoLabs/collegedash/issues/395#issuecomment-5921461115, with Huatuo's build
// conditions (issuecomment-5921493579) and the #400 agreement (issuecomment-5921572865). What is pinned here:
//   1. the page asks for /api/v1/list, never the full index;
//   2. rpiSeasons() and rpiOf read season.rpiSeason and the row's `rpi` (an rpiHistory-free list), and season.finished;
//      the Fall-high condition reads fallAvgHighF; a full-index row is still read the old way (the plan's fallback);
//   3. #394: the list view's report names the file it loaded, `list`;
//   4. a runtime check: every view is drawn over the committed slim list with each row in a Proxy that records any read
//      of a key the slim list dropped (Huatuo's condition 2), and every view must draw without an error;
//   5. a text scan of the page script, the second net: a dropped key is read only where the plan says (a profile, the
//      recommendations state, or the one marked full-index fallback);
//   6. the fields #400's recommender and #507's Home search read from rows are on every slim row.
// Offline: the page script runs in a `vm` against a stub DOM; fetch serves public/ and nothing leaves the process.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { makeElement as baseElement, settle } from './recs_page_helpers.mjs';

// The shared stub element, plus the few DOM methods the Pipelines and ID Camps views also call.
const makeElement = name => Object.assign(baseElement(name), {
  removeAttribute() { }, toggleAttribute() { }, hasAttribute: () => false, appendChild() { }, insertAdjacentHTML() { },
  scrollIntoView() { }, getBoundingClientRect: () => ({ top: 0, left: 0, width: 0, height: 0, bottom: 0, right: 0 }), children: [],
});

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = fs.readFileSync(process.env.SLIM_PAGE_HTML || path.join(PUBLIC, 'index.html'), 'utf8');
const readJson = rel => JSON.parse(fs.readFileSync(path.join(PUBLIC, rel), 'utf8'));
const LIST = readJson('data/list/index.json');
const INDEX = readJson('data/programs/index.json');

// The keys the slim list dropped, from the two committed files themselves: every key some index row has and no list
// row has. Nothing is written down here, so a key the build drops later is covered without an edit.
const keysOf = rows => new Set(rows.flatMap(r => Object.keys(r)));
const LIST_KEYS = keysOf(LIST.programs);
const DROPPED = [...keysOf(INDEX.programs)].filter(k => !LIST_KEYS.has(k)).sort();

const HANDLES = ['S', 'route', 'loadIndex', 'renderSidebar', 'renderList', 'setSort', 'SORT_SPECS', 'COND_FIELDS', 'searchMatches',
  'suggestionItems', 'filteredPrograms', 'rpiSeasons', 'rpiSeason', 'rpiInProgress', 'finishedSeason', 'rpiOf', 'rpiLabel', 'perfRes',
  'PERF_VIEWS', 'displayName', 'programBySlug', 'listHashOf'];

// `list`: the document /api/v1/list answers (default: the committed slim list). `wrap`: applied to each served row.
// `full`: the document /api/v1/programs answers (default: the same as /api/v1/list, so a page still asking for the full
// index is drawn over the same Proxy rows and caught reading a dropped key).
function loadPage({ list = LIST, wrap = r => r, full = null } = {}) {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const requests = [];
  const serveList = doc => ({ ok: true, status: 200, async json() { const d = JSON.parse(JSON.stringify(doc)); d.programs = d.programs.map(wrap); return d; } });
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, WeakMap, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, URLSearchParams, performance, crypto: globalThis.crypto, TextEncoder, Uint8Array,
    encodeURIComponent, decodeURIComponent, Error, TypeError, Proxy, Reflect,
    location: { hash: '', search: '', replace(h) { this.hash = h; } }, history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    sessionStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    innerWidth: 1400, addEventListener() { },
    fetch: async url => {
      url = String(url);
      requests.push(url);
      const ok = body => ({ ok: true, status: 200, async json() { return JSON.parse(JSON.stringify(body)); } });
      if (url === '/api/v1/list') return serveList(list);
      if (url === '/api/v1/programs') return serveList(full || list);
      if (url === 'api/status' || url === '/api/status') return ok({ local: false });
      if (url === 'api/ask/status' || url === '/api/ask/status') return { ok: false, status: 0, type: 'opaqueredirect', async json() { throw new SyntaxError('opaque'); } };
      const m = url.match(/^\/api\/v1\/(programs\/[a-z0-9-]+|camps|trends|status)$/);
      const rel = !m ? null : m[1] === 'status' ? 'archive/refresh-state.json' : m[1] === 'camps' ? 'data/camps/index.json'
        : m[1] === 'trends' ? 'data/trends/index.json' : `data/${m[1]}.json`;
      const p = rel && path.join(PUBLIC, rel);
      return p && fs.existsSync(p) ? ok(JSON.parse(fs.readFileSync(p, 'utf8'))) : { ok: false, status: 404, async json() { return { error: 'not found' }; } };
    },
  };
  const head = makeElement('head'); head.appendChild = () => { };
  sandbox.document = { documentElement: makeElement('html'), body: makeElement('body'), head, querySelector: bySelector,
    querySelectorAll: () => [], addEventListener() { }, createElement: makeElement, activeElement: null, visibilityState: 'visible' };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = HTML.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(HANDLES)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, requests, app: () => bySelector('#app').innerHTML };
}
async function ready(opts) {
  const pg = loadPage(opts);
  await settle();
  if (!pg.sb.S.index) await pg.sb.loadIndex();
  await settle();
  return pg;
}
async function go(pg, hash) {
  pg.sb.location.hash = hash;
  pg.sb.route();
  await settle();
  const html = pg.app();
  assert.ok(!/Something went wrong|Couldn’t load the data/.test(html), `${hash}: ${html.replace(/<[^>]+>/g, ' ').slice(0, 300)}`);
}

// ---------- 1. the URL ----------

test('the page loads the slim list from /api/v1/list and never the full index', async () => {
  const pg = await ready();
  await go(pg, '#/programs');
  assert.ok(pg.requests.includes('/api/v1/list'), pg.requests.join(' '));
  assert.ok(!pg.requests.includes('/api/v1/programs'), pg.requests.join(' '));
});

// ---------- 2. the changed fields ----------

const row = (slug, extra) => ({ slug, name: `${slug} University`, shortName: slug, division: 'D1', conference: 'Test', ...extra });
const slimDoc = (season, rows) => ({ updated: LIST.updated, season: { current: 2026, gradYears: [2026, 2027], ...season }, programs: rows });

test('rpiSeasons and rpiOf read season.rpiSeason and the row\'s rpi from a list with no rpiHistory', async () => {
  const live = slimDoc({ finished: 2025, rpiFinal: null, rpiSeason: 2026 }, [row('alpha', { rpi: 7 }), row('beta', { rpi: null })]);
  let pg = await ready({ list: live });
  assert.equal(pg.sb.rpiSeason(), 2026);
  assert.equal(pg.sb.rpiInProgress(), true);
  assert.equal(pg.sb.finishedSeason(), 2025);
  assert.equal(pg.sb.rpiLabel(), 'RPI 2026 (in progress)');
  assert.equal(pg.sb.rpiOf(pg.sb.programBySlug('alpha')), 7);
  assert.equal(pg.sb.rpiOf(pg.sb.programBySlug('beta')), null);
  // the final RPI is out: the same season, no longer in progress
  pg = await ready({ list: slimDoc({ finished: 2026, rpiFinal: true, rpiSeason: 2026 }, [row('alpha', { rpi: 3 })]) });
  assert.equal(pg.sb.rpiLabel(), 'RPI 2026');
  assert.equal(pg.sb.finishedSeason(), 2026);
  // no ranked season at all
  pg = await ready({ list: slimDoc({ finished: 2025, rpiFinal: null, rpiSeason: null }, [row('alpha', { rpi: null })]) });
  assert.equal(pg.sb.rpiSeason(), null);
  assert.equal(pg.sb.rpiLabel(), 'RPI');
});

test('a full-index row (rpiHistory, fallClimate, no rpiSeason) is still read the old way', async () => {
  const doc = { updated: LIST.updated, season: { current: 2026, gradYears: [2026], finished: 2025, rpiFinal: null },
    programs: [row('alpha', { rpiHistory: [{ year: 2026, rank: 4 }, { year: 2025, rank: 9 }], fallClimate: { avgHighF: 70 } })] };
  const pg = await ready({ list: doc });
  assert.equal(pg.sb.rpiSeason(), 2026);
  assert.equal(pg.sb.rpiOf(pg.sb.programBySlug('alpha')), 4);
  const fall = pg.sb.COND_FIELDS.find(d => d.key === 'fallAvgHighF');
  assert.equal(fall.get(pg.sb.programBySlug('alpha')), 70);
});

test('the Fall-high condition reads fallAvgHighF from a slim row', async () => {
  const pg = await ready({ list: slimDoc({ finished: 2025, rpiFinal: null, rpiSeason: null }, [row('alpha', { fallAvgHighF: 71.5 }), row('beta', { fallAvgHighF: null })]) });
  const fall = pg.sb.COND_FIELDS.find(d => d.key === 'fallAvgHighF');
  assert.equal(fall.get(pg.sb.programBySlug('alpha')), 71.5);
  assert.equal(fall.get(pg.sb.programBySlug('beta')), null);
});

// ---------- 3. #394's report ----------

test('#394: the list view reports the file it loaded as `list`', async () => {
  const pg = await ready();
  assert.equal(pg.sb.perfRes('/api/v1/list'), 'list');
  assert.equal(pg.sb.PERF_VIEWS.list, 'list');
  assert.equal(pg.sb.perfRes('/api/v1/programs/ucla'), 'program');
  assert.equal(pg.sb.perfRes('/api/v1/list?x=1'), null);
});

// ---------- 4. the runtime check ----------

test('the committed files really drop keys, so the runtime check has something to catch', () => {
  for (const k of ['rpiHistory', 'fallClimate', 'headCoach', 'currentSeason']) assert.ok(DROPPED.includes(k), `${k}: ${DROPPED.join(', ')}`);
  assert.ok(!DROPPED.includes('rpi') && !DROPPED.includes('slug'), DROPPED.join(', '));
});

test('every view draws over the slim list without reading a dropped key (Proxy rows)', async () => {
  const reads = new Map();
  const dropped = new Set(DROPPED);
  const wrap = r => new Proxy(r, {
    get(t, k, recv) {
      if (typeof k === 'string' && dropped.has(k)) { const e = new Error().stack.split('\n').slice(2, 4).join(' | '); reads.set(`${k} @ ${e}`, (reads.get(`${k} @ ${e}`) || 0) + 1); }
      return Reflect.get(t, k, recv);
    },
  });
  const pg = await ready({ wrap });
  const sb = pg.sb, slugs = LIST.programs.filter(p => p.division === 'D1').slice(0, 4).map(p => p.slug);
  sb.S.favorites = new Set(slugs.slice(0, 3));
  // Every list state through the page's own address writer (listHashOf), as a link or a click would set it: each sort
  // key both ways in cards and in Stats, each condition chip, and searches by name, alias, initials, mascot and place.
  const at = st => go(pg, sb.listHashOf({ sort: 'name', ...st }));
  for (const view of ['cards', 'table']) {
    for (const sort of Object.keys(sb.SORT_SPECS)) for (const sortDir of ['asc', 'desc']) await at({ view, sort, sortDir });
  }
  for (const d of sb.COND_FIELDS) {
    for (const view of ['cards', 'table']) await at({ view, cond: [{ field: d.key, op: d.ops[0], value: 1 }] });
    assert.equal(sb.S.filters.cond[0]?.field, d.key, `the ${d.key} condition was not applied`);
  }
  for (const q of ['ucla', 'state', 'UNC', 'Bruins', 'CA', 'saint', 'Ohio']) {
    sb.searchMatches(q.toLowerCase(), 6, q);
    await at({ q });
  }
  await at({});
  await go(pg, '#/shortlist');
  await go(pg, '#/camps');
  await go(pg, '#/trends');
  await go(pg, `#/compare/${slugs.join(',')}`);
  await go(pg, `#/p/${slugs[0]}`);
  await go(pg, `#/p/${slugs[1]}/camps`);
  await go(pg, '#/');
  assert.deepEqual([...reads.entries()].map(([k, n]) => `${k} (${n}x)`), [], 'a view read a key the slim list dropped');
});

// ---------- 5. the text scan ----------

// Where a dropped key may appear in the page script, and why. Anything else is a new reader of a dropped key.
const ALLOWED = [
  [/\b(?:p\.program|pr|p\.program\?)\??\.headCoach\b/, 'the profile\'s program block'],
  [/\bs\.headCoach\b/, 'a profile season row'],
  [/\b(?:p\.school|sch|s)\.sat75\b/, 'the profile\'s school block'],
  [/\b(?:p\._build|b)\??\.(?:failed|stale|builtAt)\b/, 'the profile\'s _build block'],
  [/\b(?:R|S\.recs)\.stale\b/, 'the recommendations state (#400), not a row'],
  [/\bhas\.rpiHistory\b/, 'a profile section check (reads p.seasons)'],
  [/\bfull\.(?:rpiHistory|fallClimate)\b/, 'the one full-index fallback (#395 plan: the old calculation stays as the fallback)'],
];
test('text scan: a dropped key is read only where the plan says', () => {
  const lines = HTML.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n');
  const bad = [];
  for (const k of DROPPED) {
    const re = new RegExp(`[\\w$.?\\]\\)]*\\??\\.${k}\\b|\\[['"]${k}['"]\\]`, 'g');
    for (const m of src.matchAll(re)) {
      const ctx = src.slice(Math.max(0, m.index - 20), m.index + m[0].length + 5);
      if (!ALLOWED.some(([r]) => r.test(m[0]) || r.test(ctx))) bad.push(`${k}: …${ctx.replace(/\s+/g, ' ')}…`);
    }
  }
  assert.deepEqual(bad, []);
});

// ---------- 6. the fields other features read from rows ----------

test('the recommender\'s 9 fields (#400) and the Home search\'s 10 (#507) are on every slim row', () => {
  const need = ['slug', 'name', 'shortName', 'division', 'conference', 'city', 'state', 'region', 'undergradEnrollment',
    'nickname', 'searchNames'];
  const missing = LIST.programs.flatMap(r => need.filter(k => !(k in r)).map(k => `${r.slug}.${k}`));
  assert.deepEqual(missing, []);
  assert.equal(LIST.programs.length, INDEX.programs.length);
  assert.deepEqual(LIST.programs.map(r => r.slug), INDEX.programs.map(r => r.slug));
});
