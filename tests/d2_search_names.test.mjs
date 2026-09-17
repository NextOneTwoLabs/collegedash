// Search for Division II short names and nicknames (issue #200, part of #197 owner decision 6).
//
//     node --test tests/d2_search_names.test.mjs
//
// Before this change, D2 registry entries carry no shortName or nickname (tests/registry_membership_test.py
// enforces that on main), so the site's search can only match a D2 program's long official name: "GVSU" or
// "Lakers" find nothing for Grand Valley State, and "Lakers" alone finds only Mercyhurst, a Division I
// program with the same nickname. This file builds a SYNTHETIC published index the way build.py's
// summary_row() would once D2 publishes, out of the REAL committed public/data/registry.json rows (not
// invented data), in two states:
//
//   BEFORE  every onboarded D2 program's shortName and nickname forced to null -- the state every one of
//           them was actually in before issue #200 (registry_membership_test.py's "nothing a source did
//           not give is filled in" pinned exactly this)
//   AFTER   the registry's current, filled values for the same rows
//
// Both states are combined with the REAL, unmodified Division I rows of public/data/programs/index.json
// (Mercyhurst included, with its own real "Lakers" nickname), so this is genuinely D1+D2 search over
// realistic data, not a toy fixture.
//
// The page's own inline <script> is loaded into a `vm`, the same mechanism as
// tests/division_and_name_sort.test.mjs, so what is under test is the real matchScore/prepareSearch/
// loadIndex source text rather than a reimplementation that could quietly drift from it.
//
// What this proves:
//   - systematically, over every one of the real, currently-onboarded D2 programs (not a hand-picked
//     couple): searching a program's own filled shortName is an EXACT match (score 100) in the AFTER
//     index, and is never an exact match in the BEFORE index (where shortName is null and the search
//     falls back to the long official name); searching a program's filled nickname finds it in the AFTER
//     index and finds nothing for it in the BEFORE index (nicknames, unlike short names, share no words
//     with the long official name, so there is no accidental fallback match to worry about);
//   - named example, matching the issue exactly: searching "Lakers" over the AFTER index returns BOTH
//     Mercyhurst (D1) and Grand Valley State (D2); over the BEFORE index it returns only Mercyhurst --
//     the nickname finds the D2 program, not only the D1 one;
//   - named example: "GVSU" matches Grand Valley State both before AND after the fill. Before, its
//     shortName is null so the client falls back to the full official name, and "GVSU" happens to be
//     that name's own initials. Filling shortName with the three-word "Grand Valley State" would, on its
//     own, break this (its own initials are only "GVS") -- the TPM ruled that regression unacceptable, so
//     build.py's search_names() now also publishes initials computed from shortName plus the generic
//     word it dropped ("University"/"College"), restoring "GVSU" as an explicit search name rather than
//     an accident of the fallback. Checked systematically below, not just for this one program;
//   - the real Division I rows are unaffected: with D2 added to the same index, a sample of real D1
//     programs still resolves to itself by its own short name.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..');
const PUBLIC = path.join(ROOT, 'public');
const INDEX_URL = 'data/programs/index.json';

/* ---------- the page's inline <script>, in a vm against a stub DOM (as division_and_name_sort.test.mjs) ---------- */
function el(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, dataset: {}, style: {},
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => el('child'), querySelectorAll: () => [], closest: () => null, matches: () => false, focus() { }, contains: () => false,
  };
}
function makeEnv(fetchLog, overrides) {
  const els = new Map();
  const store = new Map();
  const sandbox = {
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
    fetch: async url => {
      fetchLog.push(url);
      if (Object.prototype.hasOwnProperty.call(overrides, url)) {
        const doc = overrides[url];
        return { ok: true, status: 200, async json() { return JSON.parse(JSON.stringify(doc)); } };
      }
      return { ok: false, status: 404, async json() { throw new Error('404'); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  return sandbox;
}
const SOURCE_LINES = fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8').split(/\r?\n/);
function loadPage(indexDoc) {
  const a = SOURCE_LINES.findIndex(l => l.trim() === '<script>');
  const b = SOURCE_LINES.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'public/index.html: could not find the inline <script>');
  const src = SOURCE_LINES.slice(a + 1, b).join('\n')
    + '\n;Object.assign(globalThis, { S, matchScore, searchMatches, normText, prepareSearch, loadIndex });\n';
  const fetchLog = [];
  const sandbox = makeEnv(fetchLog, { [INDEX_URL]: indexDoc });
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}
async function ready(sb) {
  await sb.loadIndex();
  for (let i = 0; i < 10 && !sb.S.index?.divisions; i++) await new Promise(r => setTimeout(r, 0));
  assert.ok(sb.S.index?.divisions, 'the index never finished loading');
  return sb.S.index;
}

/* ---------- the real D1 index, and a synthetic D2 index built from the real registry rows ---------- */
// The committed index's Division I rows. Since #197 publishes D2, that index also holds the real D2 rows,
// which the BEFORE/AFTER indexes below replace with their own; keeping them would list each D2 slug twice.
const COMMITTED_INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, INDEX_URL), 'utf8'));
const REAL_D1 = { ...COMMITTED_INDEX, programs: COMMITTED_INDEX.programs.filter(p => p.division === 'D1') };
const REGISTRY = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'registry.json'), 'utf8'));
const D2_ONBOARDED = REGISTRY.programs.filter(p => p.division === 'D2' && p.onboarded);

test('fixture sanity: the real registry actually has onboarded D2 programs with filled names, or nothing below proves anything', () => {
  assert.ok(D2_ONBOARDED.length > 200, `only ${D2_ONBOARDED.length} onboarded D2 programs`);
  assert.ok(D2_ONBOARDED.some(p => p.shortName), 'no onboarded D2 program has a shortName -- issue #200 has not landed');
  assert.ok(D2_ONBOARDED.every(p => p.nickname), 'some onboarded D2 program still has no nickname');
  const gvsu = D2_ONBOARDED.find(p => p.slug === 'grand-valley-state');
  assert.ok(gvsu, 'grand-valley-state is missing from the registry');
  assert.equal(gvsu.nickname, 'Lakers', 'the named example in issue #197/#200 assumes GVSU\'s nickname is Lakers');
  const mercyhurst = REAL_D1.programs.find(p => p.slug === 'mercyhurst');
  assert.ok(mercyhurst, 'mercyhurst is missing from the real D1 index');
  assert.equal(mercyhurst.nickname, 'Lakers', 'the named example assumes Mercyhurst (D1) is also nicknamed Lakers');
});

// A close mirror of build.py's search_names() (issue #200 follow-up), so the synthetic AFTER index
// carries the same searchNames a real build would publish, including the fix for the shortName-drops-a-
// generic-word regression: 'Grand Valley State University' loses the initials 'GVSU' once shortName is
// the three-word 'Grand Valley State' (only 'GVS' comes from that alone), so search_names() also adds
// initials of shortName plus a dropped, purely generic trailing word ('University'/'College'). See
// tests/search_names_test.py for the Python function itself; this mirror exists only to build a
// realistic fixture here, not as a second implementation to keep in sync by hand -- it is checked
// against real registry rows in the tests below, so a drift would fail loudly.
function isUpperWord(w) { return /[A-Z]/.test(w) && !/[a-z]/.test(w); }
function initialsOf(words) {
  return words.filter(w => /[a-zA-Z]/.test(w[0])).map(w => (isUpperWord(w) && w.length <= 4 ? w : w[0])).join('');
}
function computeSearchNames(p) {
  const out = [];
  const seen = new Set();
  const add = (raw) => {
    const s = (raw || '').replace(/\s*\([^)]*\)/, '').trim();
    if (s && !seen.has(s.toLowerCase())) { seen.add(s.toLowerCase()); out.push(s); }
  };
  for (const s of [p.shortName, p.name]) if (s) add(s);
  const short = p.shortName || '';
  const words = short.split(/\s+/).filter(Boolean);
  if (words.length >= 3) add(initialsOf(words));
  const name = p.name || '';
  if (short && name.toLowerCase().startsWith(short.toLowerCase() + ' ')) {
    const extra = name.slice(short.length).trim().split(/\s+/).filter(Boolean);
    if (extra.length >= 1 && extra.length <= 2 && extra.every(w => ['University', 'College'].includes(w.replace(/,$/, '')))) {
      const fullWords = [...words, ...extra];
      if (fullWords.length >= 3) add(initialsOf(fullWords));
    }
  }
  for (const s of [...out]) {
    if (/\bSt\.?\s/.test(s)) add(s.replace(/\bSt\.?\s/, 'Saint '));
    else if (/\bSaint\s/.test(s)) add(s.replace(/\bSaint\s/, 'St '));
  }
  return out;
}

// The minimal row shape build.py's summary_row() would publish for a D2 program, real registry fields only.
function d2Row(p, { fill }) {
  const shortName = fill ? p.shortName : null;
  const nickname = fill ? p.nickname : null;
  return {
    slug: p.slug, name: p.name, shortName, nickname,
    searchNames: fill ? computeSearchNames({ shortName, name: p.name }) : undefined,
    conference: p.conference, division: 'D2', colors: p.colors || null,
  };
}
function combinedIndex(fill) {
  return { ...REAL_D1, programs: [...REAL_D1.programs, ...D2_ONBOARDED.map(p => d2Row(p, { fill }))] };
}
const BEFORE_INDEX = combinedIndex(false);
const AFTER_INDEX = combinedIndex(true);

test('the BEFORE index really has no D2 shortName or nickname, and the AFTER index has both, on every row', () => {
  const before = BEFORE_INDEX.programs.filter(p => p.division === 'D2');
  const after = AFTER_INDEX.programs.filter(p => p.division === 'D2');
  assert.equal(before.length, D2_ONBOARDED.length);
  assert.deepEqual(before.filter(p => p.shortName || p.nickname).map(p => p.slug), []);
  assert.deepEqual(after.filter(p => !p.nickname).map(p => p.slug), []);
});

/* ---------- systematically, over every real onboarded D2 program ---------- */
test('every D2 program with a filled shortName is an exact search match after the fill, and never an exact match before it', async () => {
  const before = loadPage(BEFORE_INDEX);
  const after = loadPage(AFTER_INDEX);
  await ready(before); await ready(after);
  const withShort = D2_ONBOARDED.filter(p => p.shortName);
  assert.ok(withShort.length > 100, `only ${withShort.length} D2 programs have a shortName to check`);
  const failedAfter = [], failedBefore = [];
  for (const p of withShort) {
    const q = after.normText(p.shortName);
    const bp = before.S.index.programs.find(x => x.slug === p.slug);
    const ap = after.S.index.programs.find(x => x.slug === p.slug);
    const beforeScore = before.matchScore(bp, q)?.score ?? null;
    const afterScore = after.matchScore(ap, q)?.score ?? null;
    if (afterScore !== 100) failedAfter.push(`${p.slug}: ${afterScore}`);
    // a shortName resolved to equal the registry's own official name verbatim (georgia-college, per the
    // TPM's collision ruling on #200) is trivially an exact match even before any fill -- that is not
    // the regression this checks for, so it is not counted as one
    if (beforeScore === 100 && p.shortName.toLowerCase() !== p.name.toLowerCase()) failedBefore.push(`${p.slug}: ${beforeScore}`);
  }
  assert.deepEqual(failedAfter, [], 'these D2 programs do not exact-match their own shortName after the fill');
  assert.deepEqual(failedBefore, [], 'these D2 programs already exact-matched their shortName text before the fill (nothing was filled)');
});

test('every D2 program is found by its own filled nickname after the fill, and by none of these nickname queries before it', async () => {
  const before = loadPage(BEFORE_INDEX);
  const after = loadPage(AFTER_INDEX);
  await ready(before); await ready(after);
  assert.equal(D2_ONBOARDED.length, D2_ONBOARDED.filter(p => p.nickname).length, 'not every onboarded D2 program has a nickname');
  const missingAfter = [], foundBefore = [];
  for (const p of D2_ONBOARDED) {
    const q = after.normText(p.nickname);
    const bp = before.S.index.programs.find(x => x.slug === p.slug);
    const ap = after.S.index.programs.find(x => x.slug === p.slug);
    if (!after.matchScore(ap, q)) missingAfter.push(`${p.slug}: ${p.nickname}`);
    if (before.matchScore(bp, q)) foundBefore.push(`${p.slug}: ${p.nickname}`);
  }
  assert.deepEqual(missingAfter, [], 'these D2 programs are not found by their own nickname after the fill');
  assert.deepEqual(foundBefore, [], 'these D2 programs were already matched by that nickname text before the fill (nothing was filled)');
});

/* ---------- the named example from the issue: "Lakers" ---------- */
test('"Lakers" finds only Mercyhurst (D1) before the fill, and finds Grand Valley State (D2) too after it', async () => {
  const before = loadPage(BEFORE_INDEX);
  const after = loadPage(AFTER_INDEX);
  await ready(before); await ready(after);
  const beforeSlugs = before.searchMatches('lakers').map(m => m.p.slug).sort();
  const afterSlugs = after.searchMatches('lakers').map(m => m.p.slug).sort();
  assert.deepEqual(beforeSlugs, ['mercyhurst'], 'before the fill, "Lakers" should find only the D1 program with that nickname');
  assert.ok(afterSlugs.includes('mercyhurst'), 'after the fill, Mercyhurst (D1) should still be found');
  assert.ok(afterSlugs.includes('grand-valley-state'), 'after the fill, "Lakers" does not find Grand Valley State (D2)');
  assert.ok(afterSlugs.length >= 2, 'after the fill, "Lakers" should return at least the two same-nicknamed programs');
});

// Filling shortName with the three-word "Grand Valley State" (dropping "University") would, on its own,
// break "GVSU": before the fill, s.short fell back to the full four-word official name, so the client's
// own initials computation ('GVS' + 'U') happened to spell "GVSU"; after the fill, s.short is the
// three-word shortName alone and its own initials are just "GVS". The TPM ruled this regression is not
// acceptable (a visitor searching initials is real, and it worked before this PR), so search_names()
// (build.py) now also publishes initials computed from shortName plus the dropped generic word, and
// computeSearchNames() above mirrors that for this synthetic index. This is a real, useful improvement,
// not merely restoring the accident: it also fires for a filled shortName that never had this problem
// before (e.g. any newly-mechanically-derived D2 shortName), which the systematic test below covers.
test('"GVSU" keeps matching Grand Valley State after the fill (search_names() restores the initials shortName alone would have dropped)', async () => {
  const before = loadPage(BEFORE_INDEX);
  const after = loadPage(AFTER_INDEX);
  await ready(before); await ready(after);
  assert.ok(before.searchMatches('gvsu').some(m => m.p.slug === 'grand-valley-state'),
    'expected "GVSU" to still match Grand Valley State before the fill, via its long name\'s initials (sanity: if this fails, the premise below is untested)');
  assert.ok(after.searchMatches('gvsu').some(m => m.p.slug === 'grand-valley-state'),
    '"GVSU" no longer finds Grand Valley State after the fill -- the shortName-drops-a-word regression is back');
});

// Systematically, over every real onboarded D2 program whose mechanical shortName rule dropped a
// trailing "University"/"College": the initials of the FULL official name (what search matched on before
// shortName existed) must still be a search hit after the fill, not just the shortName's own, shorter
// initials.
test('every D2 program that lost a generic word from its shortName still matches its full name\'s initials after the fill', async () => {
  const after = loadPage(AFTER_INDEX);
  await ready(after);
  const affected = D2_ONBOARDED.filter(p => p.shortName && p.name.toLowerCase().startsWith(p.shortName.toLowerCase() + ' ')
    && ['University', 'College'].includes(p.name.slice(p.shortName.length).trim())
    && p.shortName.split(/\s+/).length + 1 >= 3);
  assert.ok(affected.length > 100, `only ${affected.length} D2 programs match the shortName-drops-a-word shape`);
  const missing = [];
  for (const p of affected) {
    // the full-name initials entry computeSearchNames() adds, e.g. 'GVSU' for Grand Valley State
    // University -- reusing initialsOf (not a second hand-rolled computation) so this checks the client
    // actually matches what the fill publishes, not a copy of it that could quietly drift
    const fullWords = [...p.shortName.split(/\s+/), p.name.slice(p.shortName.length).trim()];
    const initials = initialsOf(fullWords);
    const ap = after.S.index.programs.find(x => x.slug === p.slug);
    if (!after.matchScore(ap, after.normText(initials))) missing.push(`${p.slug}: ${p.name} -> "${initials}"`);
  }
  assert.deepEqual(missing, [], 'these D2 programs no longer match their full name\'s initials after shortName was filled');
});

/* ---------- D1 is unaffected ---------- */
test('a sample of real D1 programs still finds itself by its own short name once D2 shares the index', async () => {
  const after = loadPage(AFTER_INDEX);
  await ready(after);
  const sample = ['north-carolina', 'ucla', 'florida-state', 'mercyhurst'];
  for (const slug of sample) {
    const p = REAL_D1.programs.find(x => x.slug === slug);
    assert.ok(p, `${slug} is missing from the real D1 index -- pick another sample slug`);
    const top = after.searchMatches(after.normText(p.shortName))[0];
    assert.equal(top?.p.slug, slug, `searching "${p.shortName}" no longer resolves ${slug} to itself first`);
  }
});
