// #466: the real Sewanee data and page must show the recognizable school name.
// node --import ./tests/netguard/netguard.mjs --test tests/sewanee_names.test.mjs
// Offline VM/local-fetch pattern used by d3_search_names and program_cards.
// Label and prefix are separate tests so both fail against main before the data fix.
// This checks runtime HTML/search, not browser layout, phone behavior or deployment.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const PUBLIC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../public');
const read = rel => JSON.parse(fs.readFileSync(path.join(PUBLIC, rel), 'utf8'));
const REGISTRY = read('data/registry.json');
const INDEX = read('data/programs/index.json');
const LIST = read('data/list/index.json');
const PROFILE = read('data/programs/sewanee.json');
const CAMPS = read('data/camps/index.json');
const OFFICIAL = 'University of the South';
const school = rows => rows.find(p => p.slug === 'sewanee');
const plain = value => JSON.parse(JSON.stringify(value));

function element() {
  return {
    innerHTML: '', textContent: '', value: '', dataset: {}, style: {}, hidden: false,
    classList: { add() {}, remove() {}, toggle: () => false, contains: () => false },
    setAttribute() {}, getAttribute: () => null, removeAttribute() {},
    addEventListener() {}, removeEventListener() {}, querySelector: () => element(),
    querySelectorAll: () => [], closest: () => null, matches: () => false,
    focus() {}, contains: () => false,
  };
}

async function loadPage() {
  const els = new Map();
  const el = selector => {
    if (!els.has(selector)) els.set(selector, element());
    return els.get(selector);
  };
  const documents = new Map([
    ['data/programs/index.json', INDEX], ['/api/v1/programs', INDEX],
    ['/api/v1/programs/sewanee', PROFILE],
  ]);
  const sb = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number,
    String, Array, Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL,
    encodeURIComponent, decodeURIComponent,
    document: {
      documentElement: element(), body: element(), querySelector: el,
      querySelectorAll: () => [], createElement: element, addEventListener() {},
    },
    location: { hash: '#/programs', replace(h) { this.hash = h; } },
    history: { replaceState() {}, pushState() {} },
    matchMedia: () => ({ matches: false }), innerWidth: 1400, addEventListener() {},
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch: async url => documents.has(url)
      ? { ok: true, status: 200, async json() { return plain(documents.get(url)); } }
      : { ok: false, status: 404, async json() { throw new Error('404'); } },
  };
  sb.window = sb; sb.globalThis = sb;
  const lines = fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8').split(/\r?\n/);
  const a = lines.findIndex(line => line.trim() === '<script>');
  const b = lines.findIndex(line => line.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'real inline page script is present');
  const source = lines.slice(a + 1, b).join('\n') + `
    Object.assign(globalThis, { S, loadIndex, normText, matchScore, searchMatches,
      visibleMatches, suggestionItems, suggestionHtml, cardHtml, tableHtml,
      renderShortlist, cmpTrayHtml, sortCmp, shortlistRows, renderProfile,
      campProgram, campRowHtml, campsQueryMatch });`;
  vm.createContext(sb);
  new vm.Script(source, { filename: 'public/index.html' }).runInContext(sb);
  await sb.loadIndex();
  for (let i = 0; i < 10 && !sb.S.index?.divisions; i++)
    await new Promise(resolve => setTimeout(resolve, 0));
  assert.ok(sb.S.index?.divisions, 'real index finished loading');
  return { sb, el, row: school(sb.S.index.programs) };
}

test('FIX desired label is Sewanee in registry, profile, program index and slim list', () => {
  for (const [label, p] of [
    ['registry', school(REGISTRY.programs)], ['profile', PROFILE],
    ['index', school(INDEX.programs)], ['list', school(LIST.programs)],
  ]) {
    assert.equal(p.shortName, 'Sewanee', `${label}: desired school label`);
    assert.equal(p.name, OFFICIAL, `${label}: official name preserved`);
    assert.equal(p.slug, 'sewanee');
    assert.equal(p.nickname, 'Tigers');
  }
});

test('FIX sew finds Sewanee by a school-name prefix, independently of city matching', async () => {
  const { sb, row } = await loadPage();
  const hit = sb.searchMatches(sb.normText('sew'), Infinity, 'sew').find(h => h.p.slug === 'sewanee');
  assert.ok(hit, 'sew must find the Sewanee slug');
  assert.equal(hit.m.score, 90, 'real short-name prefix score');
  assert.notEqual(hit.m.place, true, 'prefix result must be a school-name hit');
  assert.equal(sb.matchScore(row, 'sew', 'sew')?.score, 90);
});

test('FIX exact Sewanee is a name hit and its real suggestion shows Sewanee', async () => {
  const { sb, row } = await loadPage();
  assert.equal(sb.matchScore(row, 'sewanee', 'sewanee')?.score, 100, 'not just the existing city hit');
  sb.S.q = 'sewanee'; sb.S.qRaw = 'sewanee';
  const option = sb.suggestionItems().find(it => it.kind === 'program' && it.p.slug === 'sewanee');
  assert.ok(option, 'school-name suggestion, not the All matching programs place option');
  assert.equal(sb.suggestionHtml(option, 0).match(/class="qopt-name">([^<]*)</)?.[1], 'Sewanee');
  sb.S.filters.division = ['D1'];
  assert.ok(!sb.visibleMatches().some(h => h.p.slug === 'sewanee'), 'active filters still hide D3');
  const hidden = sb.suggestionItems().find(it => it.kind === 'program' && it.p.slug === 'sewanee');
  assert.equal(hidden?.outside, true, 'existing outside-your-filters name suggestion is preserved');
});

test('FIX official name and explicit old alias find Sewanee with honest compatibility provenance', async () => {
  const p = school(REGISTRY.programs);
  assert.ok(p.searchAliases?.includes('the South'), 'old label is an explicit alias');
  assert.match(p.searchAliasesNote || '', /"the South"/);
  assert.match(p.searchAliasesNote || '', /mechanically derived former registry/i);
  assert.match(p.searchAliasesNote || '', /compatibility.*#466|#466.*compatibility/i);
  assert.match(p.searchAliasesNote || '', /not independently verified/i);
  assert.match(p.namesNote, /wikipedia\.org\/wiki\/List_of_NCAA_Division_III_institutions/);
  assert.match(p.searchAliasesNote, /wikipedia\.org\/wiki\/List_of_NCAA_Division_III_institutions/);
  for (const rows of [INDEX.programs, LIST.programs])
    assert.deepEqual(school(rows).searchNames, ['Sewanee', OFFICIAL, 'the South']);
  const { sb } = await loadPage();
  for (const q of [OFFICIAL, 'the South']) {
    const hit = sb.searchMatches(sb.normText(q), Infinity, q).find(h => h.p.slug === 'sewanee');
    assert.ok(hit, `${q} finds the correct slug`);
    assert.notEqual(hit.m.place, true, 'retained names match as names');
  }
});

test('FIX real cards, table, Shortlist and Compare labels show Sewanee', async () => {
  const { sb, el, row } = await loadPage();
  assert.equal(sb.cardHtml(row).match(/<h3[^>]*><span class="nm">([^<]*)<\/span>/)?.[1], 'Sewanee');
  assert.equal(sb.tableHtml([row]).match(/class="team-name" title="University of the South">([^<]*)</)?.[1], 'Sewanee');
  sb.S.favorites = new Set(['sewanee']);
  await sb.renderShortlist();
  assert.equal(el('#app').innerHTML.match(/<h3[^>]*><span class="nm">([^<]*)<\/span>/)?.[1], 'Sewanee');
  sb.S.compare = ['sewanee'];
  assert.equal(sb.cmpTrayHtml().match(/<li><span>([^<]*)<\/span>/)?.[1], 'Sewanee');
});

test('FIX real Name comparator orders the desired label; Shortlist uses that comparator', async () => {
  const { sb, row } = await loadPage();
  const before = { ...row, slug: 'sort-before', shortName: 'Sentry' };
  const after = { ...row, slug: 'sort-after', shortName: 'Tamarack' };
  assert.deepEqual([after, row, before].sort(sb.sortCmp('name', 'asc')).map(p => p.slug),
    ['sort-before', 'sewanee', 'sort-after']);
  sb.S.index.programs.push(before, after);
  sb.S.favorites = new Set(['sort-after', 'sewanee', 'sort-before']);
  assert.deepEqual(plain(sb.shortlistRows()).map(p => p.slug), ['sort-before', 'sewanee', 'sort-after']);
});

test('GUARD real profile heading stays University of the South', async () => {
  const { sb, el } = await loadPage();
  await sb.renderProfile('sewanee', 'overview');
  const html = el('#app').innerHTML;
  assert.equal(html.match(/<h1[^>]*>([^<]*)/)?.[1], OFFICIAL);
});

test('FIX real profile glance label uses Sewanee', async () => {
  const { sb, el } = await loadPage();
  await sb.renderProfile('sewanee', 'overview');
  const html = el('#app').innerHTML;
  assert.equal(html.match(/<span title="University of the South">([^<]*)<\/span>/)?.[1], 'Sewanee');
});

test('FIX generated camp blocks and real camp rendering/search use Sewanee', async () => {
  const { sb } = await loadPage();
  const p = school(INDEX.programs);
  const rows = CAMPS.camps.filter(c => c.slug === 'sewanee');
  for (const c of rows) {
    assert.equal(c.program.shortName, 'Sewanee');
    assert.equal(c.program.name, OFFICIAL);
    assert.deepEqual(c.program, Object.fromEntries(
      ['name', 'shortName', 'division', 'city', 'state', 'region'].map(k => [k, p[k] ?? null])));
  }
  // A school's last upcoming camp eventually expires; keep its renderer covered then too.
  const c = rows[0] || { slug: 'sewanee', name: 'Fixture camp', startDate: '2030-10-01', program: p };
  const info = sb.campProgram(c, new Map(INDEX.programs.map(p => [p.slug, p])));
  assert.equal(info.name, 'Sewanee', 'embedded name must agree with the index');
  assert.equal(sb.campRowHtml(c, info).match(/class="team-name">([^<]*)<\/a>/)?.[1], 'Sewanee');
  for (const q of ['sewanee', 'sew', OFFICIAL]) assert.equal(sb.campsQueryMatch(c, info, q), true, q);
});
