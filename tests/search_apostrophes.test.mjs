// #479: the search normaliser drops the ʻokina and apostrophe-like marks instead of turning them into spaces.
//
//     node --test tests/search_apostrophes.test.mjs
//
// normText (the header box, the Programs q, Compare, the conference finder and Home's search all go through it) turned
// every mark that is not a letter or digit into a space, so "Hawaiʻi" became "hawai i" and "St. Mary's" "st mary s":
// typing "hawaii" or "st marys" could not match those words. ID Camps' campsNorm already dropped apostrophes and the
// ʻokina before normText (#471); now normText does, so the two agree.
//
// The page's own code is sliced out of public/index.html (the search block and the camps normaliser) and run in a vm,
// as the other search tests do. Data: made-up rows, plus relations over the committed index that pin no count.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = fs.readFileSync(process.env.SEARCH_APOS_TEST_HTML || path.join(PUBLIC, 'index.html'), 'utf8');
function cut(from, to) {
  const i = HTML.indexOf(from), j = HTML.indexOf(to, i + 1);
  assert.ok(i >= 0 && j > i, `index.html: no "${from}" ... "${to}"`);
  return HTML.slice(i, j);
}
function load(index) {
  const sb = { S: { index, q: '', qRaw: '' }, matchesFilters: () => true };
  vm.createContext(sb);
  vm.runInContext([
    cut('/* ---------- search: word-prefix matching', '/* ---------- condition chips: the field registry'),
    cut('const campsNorm', '\n'),
  ].join('\n') + '\n;globalThis.__api = { normText, campsNorm, prepareSearch, searchMatches };', sb);
  index.programs.forEach(p => sb.__api.prepareSearch(p));
  return sb.__api;
}
const MARKS = ['ʻ', 'ʼ', "'", '’', '‘', '`', '´', '′', 'ʹ'];  // ʻ ʼ ' ’ ‘ ` ´ ′ ʹ
const APOS = new RegExp(`[${MARKS.join('')}‛ʽˈ]`, 'g');

test('normText drops the ʻokina and apostrophe-like marks: Hawaiʻi is "hawaii", St. Mary\'s is "st marys"', () => {
  const A = load({ programs: [] });
  for (const m of MARKS) assert.equal(A.normText(`Hawai${m}i`), 'hawaii', `U+${m.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}`);
  assert.equal(A.normText('University of Hawaiʻi at Mānoa'), 'university of hawaii at manoa');
  assert.equal(A.normText("St. Mary's"), 'st marys');
  assert.equal(A.normText('D’Youville'), 'dyouville');
  assert.equal(A.normText("Nor'easters"), 'noreasters');
  // everything else is as before: other punctuation and dashes are spaces, & is dropped, accents go
  assert.equal(A.normText('Texas A&M–Corpus Christi'), 'texas am corpus christi');
  assert.equal(A.normText('St. John (NY)'), 'st john ny');
  assert.equal(A.normText('  Mānoa  '), 'manoa');
});

test('ID Camps\' campsNorm and normText now agree, on made-up text and on every name in the committed data', () => {
  const index = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
  const camps = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'camps', 'index.json'), 'utf8'));
  const A = load({ programs: [] });
  const texts = ['Hawaiʻi', "Women's ID Camp", 'Women’s Soccer', 'D`Youville', 'Kapiʻolani', 'Saint Mary’s (IN)'];
  for (const p of index.programs) texts.push(p.name, p.shortName, p.nickname, p.city, ...(p.searchNames || []));
  for (const c of camps.camps) texts.push(c.name, c.program?.name, c.program?.shortName, c.program?.city);
  const differ = texts.filter(Boolean).filter(t => A.campsNorm(t) !== A.normText(t));
  assert.deepEqual(differ, [], 'the two searches read these differently');
});

test('a name with an ʻokina or apostrophe is found by its words typed without the mark', () => {
  const rows = [
    { slug: 'kapiolani', name: 'Kapiʻolani Community College', shortName: 'Kapiʻolani', nickname: 'Nor’easters', searchNames: ['Kapiʻolani', 'Kapiʻolani Community College'], city: 'Honolulu', state: 'HI' },
    { slug: 'saint-marys-x', name: "Saint Mary's College of Somewhere", shortName: "Saint Mary's", nickname: 'Gaels', searchNames: ["Saint Mary's", "St Mary's"], city: 'Somewhere', state: 'CA' },
  ];
  const A = load({ programs: rows });
  const top = q => A.searchMatches(A.normText(q), Infinity, q)[0];
  assert.equal(top('kapiolani')?.p.slug, 'kapiolani');
  assert.equal(top('kapiolani')?.m.score, 100, '"kapiolani" is not the exact short name');
  assert.equal(top('kapiolani community')?.m.score >= 60, true, 'the full name\'s words do not match');
  assert.equal(top('noreasters')?.p.slug, 'kapiolani', 'the nickname without its apostrophe');
  assert.equal(top('saint marys')?.m.score, 100);
  assert.equal(top('st marys')?.p.slug, 'saint-marys-x');
  assert.equal(top('st marys')?.m.score, 95, '"St Mary\'s" is an exact search name');
  assert.equal(top("st. mary's")?.m.score, 95, 'typed with its punctuation, the same');
});

test('on the committed index: every label carrying such a mark is found by its words typed without it', () => {
  const index = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
  const A = load(index);
  const labels = [];
  for (const p of index.programs) for (const l of [p.name, ...(p.searchNames || [])]) if (l && APOS.test(l)) labels.push([p.slug, l]);
  APOS.lastIndex = 0;
  assert.ok(labels.length >= 20, `fixture: only ${labels.length} labels with an apostrophe-like mark`);
  const missed = [];
  for (const [slug, l] of labels) {
    const typed = l.replace(APOS, '');
    const hit = A.searchMatches(A.normText(typed), Infinity, typed).find(h => h.p.slug === slug);
    if (!hit || hit.m.score < 60) missed.push(`${slug}: "${typed}" -> ${hit ? hit.m.score : 'no match'}`);
  }
  assert.deepEqual(missed, [], 'typed without the mark, these labels are not matched by their words');
});
