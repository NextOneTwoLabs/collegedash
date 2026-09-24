// Common short forms find their program first (issue #309).
//
//     node --test tests/search_short_forms.test.mjs
//
// "UNC" found UNC Wilmington, Greensboro and Asheville but not North Carolina: north-carolina's searchNames
// lacked "UNC", and even with it an exact search name scored 70, below another program's short-name prefix (90).
// The fix has two halves, both checked here over the REAL committed public/data (registry + index), with the
// page's own matchScore/searchMatches loaded from public/index.html into a vm (as tests/d3_search_names.test.mjs
// does), so this tests the shared matcher itself, not a copy:
//   - registry: 34 programs carry `searchAliases` (one commonly used short form each), each cited in
//     `searchAliasesNote` to the opening paragraph of the institution's own Wikipedia article (the #217
//     Wikipedia-cited names convention); build.py publishes them in searchNames;
//   - matcher: an exact search-name match scores 95, above any short-name prefix (90), below the program's own
//     short name (100). Dropping that back to 70 fails "UNC ranks North Carolina first ..." below.
// Ambiguous forms (OSU, Miami, USF ...) get no alias; their results are checked to be exactly what they are with
// every alias stripped from the index.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const PUBLIC = path.join(ROOT, 'public');
const INDEX_URL = 'data/programs/index.json';
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, INDEX_URL), 'utf8'));
const REGISTRY = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'registry.json'), 'utf8'));
const ALIASED = REGISTRY.programs.filter(p => p.searchAliases);

function el(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, dataset: {}, style: {},
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => el('child'), querySelectorAll: () => [], closest: () => null, matches: () => false, focus() { }, contains: () => false,
  };
}
async function loadPage(index = INDEX) {
  const lines = fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>');
  const b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'public/index.html: could not find the inline <script>');
  const src = lines.slice(a + 1, b).join('\n') + '\n;Object.assign(globalThis, { S, matchScore, searchMatches, normText, loadIndex });\n';
  const els = new Map(), store = new Map();
  const doc = JSON.stringify(index);
  const sb = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: {
      documentElement: el('html'), body: el('body'),
      querySelector: s => { if (!els.has(s)) els.set(s, el(s)); return els.get(s); }, querySelectorAll: () => [],
      addEventListener() { }, createElement: el,
    },
    location: { hash: '', replace(h) { this.hash = h; } }, history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) },
    innerWidth: 1400, addEventListener() { },
    fetch: async url => (url === INDEX_URL || url === '/api/v1/programs')
      ? { ok: true, status: 200, async json() { return JSON.parse(doc); } }
      : { ok: false, status: 404, async json() { throw new Error('404'); } },
  };
  sb.window = sb; sb.globalThis = sb;
  vm.createContext(sb);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sb);
  await sb.loadIndex();
  for (let i = 0; i < 10 && !sb.S.index?.divisions; i++) await new Promise(r => setTimeout(r, 0));
  assert.ok(sb.S.index?.divisions, 'the index never finished loading');
  return sb;
}
const slugs = (sb, q) => sb.searchMatches(sb.normText(q)).map(m => m.p.slug);

test('UNC ranks North Carolina first, then UNC Wilmington, Greensboro and Asheville (exact search name beats a prefix)', async () => {
  const sb = await loadPage();
  const got = slugs(sb, 'UNC');
  assert.equal(got[0], 'north-carolina', `"UNC" -> ${got.join(', ')}`);
  for (const s of ['unc-wilmington', 'unc-greensboro', 'unc-asheville']) assert.ok(got.includes(s), `"UNC" lost ${s}: ${got.join(', ')}`);
  const nc = sb.S.index.programs.find(p => p.slug === 'north-carolina');
  assert.equal(sb.matchScore(nc, 'unc').score, 95, 'an exact search name scores 95');
});

test('every registry search alias is cited, published, and finds its program first', async () => {
  assert.ok(ALIASED.length >= 30, `only ${ALIASED.length} programs carry searchAliases`);
  const bad = ALIASED.filter(p => !(Array.isArray(p.searchAliases) && p.searchAliases.length
    && typeof p.searchAliasesNote === 'string' && p.searchAliasesNote.includes('wikipedia.org/wiki/')
    && p.searchAliases.every(a => p.searchAliasesNote.includes(`"${a}"`)))).map(p => p.slug);
  assert.deepEqual(bad, [], 'searchAliases without a Wikipedia-cited searchAliasesNote naming them');
  assert.deepEqual(REGISTRY.programs.filter(p => 'searchAliasesNote' in p && !p.searchAliases).map(p => p.slug), [],
    'a searchAliasesNote with no searchAliases');
  const rows = new Map(INDEX.programs.map(p => [p.slug, p]));
  const sb = await loadPage();
  const failed = [];
  for (const p of ALIASED) for (const a of p.searchAliases) {
    if (!rows.get(p.slug)?.searchNames?.includes(a)) { failed.push(`${a}: not in ${p.slug}'s published searchNames (rebuild)`); continue; }
    const got = slugs(sb, a);
    if (got[0] !== p.slug) failed.push(`${a} -> ${got.slice(0, 3).join(', ') || 'nothing'} (want ${p.slug})`);
  }
  assert.deepEqual(failed, []);
});

test('named examples: Cal, Pitt, Mizzou, MIT, WashU, UNI and GW find the right program first', async () => {
  const sb = await loadPage();
  for (const [q, want] of [['Cal', 'california'], ['Pitt', 'pittsburgh'], ['Mizzou', 'missouri'], ['MIT', 'mit'],
    ['WashU', 'washington-st-louis'], ['UNI', 'northern-iowa'], ['GW', 'george-washington']]) assert.equal(slugs(sb, q)[0], want, `"${q}" -> ${slugs(sb, q).slice(0, 3)}`);
  // MIT's exact alias (95) outranks Mitchell College's short-name prefix (90), which is still found
  assert.ok(slugs(sb, 'MIT').includes('mitchell-college'));
});

test('ambiguous short forms get no alias: their results are exactly those of the index with every alias removed', async () => {
  const aliasOf = new Map(ALIASED.map(p => [p.slug, new Set(p.searchAliases)]));
  const stripped = structuredClone(INDEX);
  for (const p of stripped.programs) if (aliasOf.has(p.slug)) p.searchNames = p.searchNames.filter(n => !aliasOf.get(p.slug).has(n));
  const [withAliases, without] = [await loadPage(), await loadPage(stripped)];
  const ambiguous = ['OSU', 'FSU', 'MSU', 'ASU', 'KSU', 'ISU', 'USF', 'USD', 'SDSU', 'UMD', 'UF', 'BU', 'BC', 'ND', 'LMU', 'CMU',
    'Miami', 'A&M', 'VT', 'UMN', 'Wazzu'];
  const all = new Set(ALIASED.flatMap(p => p.searchAliases).map(a => withAliases.normText(a)));
  for (const q of ambiguous) {
    assert.ok(!all.has(withAliases.normText(q)), `${q} is ambiguous and must not be a registry alias`);
    assert.deepEqual(slugs(withAliases, q), slugs(without, q), `"${q}" changed`);
  }
  assert.deepEqual(slugs(withAliases, 'OSU').slice(0, 3).sort(), ['ohio-state', 'oklahoma-state', 'oregon-state']);
});
