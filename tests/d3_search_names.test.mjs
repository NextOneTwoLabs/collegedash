// Search for Division III short names and nicknames (#94, PR 2 of the D3 publish plan).
//
//     node --test tests/d3_search_names.test.mjs
//
// The D3 registry entries gain shortName and nickname from Wikipedia's List of NCAA Division III institutions
// (see namesNote on each entry). This runs the page's real search (matchScore / searchMatches, loaded from
// public/index.html's inline <script> into a vm, as tests/d2_search_names.test.mjs does) over the REAL committed
// public/data/programs/index.json, D1 + D2 + D3 as published, and checks that:
//   - the published D3 rows carry the registry's names (so the build published them, not just the registry);
//   - every D3 program with a shortName is an exact match (score 100) for it;
//   - every D3 program with a nickname is found by it;
//   - the named examples: "William Smith" and "Herons" find hobart-william-smith (its registry name is
//     "Hobart and William Smith Colleges"), and "Sagehens" finds pomona-pitzer-colleges.
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
const D3_ROWS = INDEX.programs.filter(p => p.division === 'D3');

function el(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, dataset: {}, style: {},
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => el('child'), querySelectorAll: () => [], closest: () => null, matches: () => false, focus() { }, contains: () => false,
  };
}
async function loadPage() {
  const lines = fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>');
  const b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'public/index.html: could not find the inline <script>');
  const src = lines.slice(a + 1, b).join('\n') + '\n;Object.assign(globalThis, { S, matchScore, searchMatches, normText, loadIndex });\n';
  const els = new Map(), store = new Map();
  const doc = JSON.stringify(INDEX);
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

test('the published D3 rows carry the registry\'s D3 names', () => {
  const reg = new Map(REGISTRY.programs.filter(p => p.division === 'D3').map(p => [p.slug, p]));
  assert.ok(D3_ROWS.length >= 400, `only ${D3_ROWS.length} D3 rows in the index`);
  const wrong = D3_ROWS.filter(p => (p.shortName ?? null) !== (reg.get(p.slug)?.shortName ?? null)
    || (p.nickname ?? null) !== (reg.get(p.slug)?.nickname ?? null)).map(p => p.slug);
  assert.deepEqual(wrong, [], 'these index rows disagree with the registry: rebuild');
  assert.ok(D3_ROWS.filter(p => p.shortName).length > 300, 'fewer than 300 D3 rows have a shortName');
  assert.ok(D3_ROWS.filter(p => p.nickname).length > 400, 'fewer than 400 D3 rows have a nickname');
});

test('every D3 program with a shortName is an exact search match for it', async () => {
  const sb = await loadPage();
  const failed = [];
  for (const p of D3_ROWS.filter(r => r.shortName)) {
    const row = sb.S.index.programs.find(x => x.slug === p.slug);
    const score = sb.matchScore(row, sb.normText(p.shortName))?.score ?? null;
    if (score !== 100) failed.push(`${p.slug} "${p.shortName}": ${score}`);
  }
  assert.deepEqual(failed, []);
});

test('every D3 program with a nickname is found by it', async () => {
  const sb = await loadPage();
  const missing = D3_ROWS.filter(p => p.nickname)
    .filter(p => !sb.searchMatches(sb.normText(p.nickname)).some(m => m.p.slug === p.slug))
    .map(p => `${p.slug} "${p.nickname}"`);
  assert.deepEqual(missing, []);
});

test('named examples: "William Smith" and "Herons" find Hobart and William Smith; "Sagehens" finds Pomona-Pitzer', async () => {
  const sb = await loadPage();
  const top = q => sb.searchMatches(sb.normText(q))[0]?.p.slug;
  const all = q => sb.searchMatches(sb.normText(q)).map(m => m.p.slug);
  assert.equal(top('William Smith'), 'hobart-william-smith');
  assert.ok(all('Herons').includes('hobart-william-smith'), all('Herons').join(','));
  assert.ok(all('Sagehens').includes('pomona-pitzer-colleges'), all('Sagehens').join(','));
});
