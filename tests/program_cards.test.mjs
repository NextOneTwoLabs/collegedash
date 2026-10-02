// The program card with ONE fact row (#465 PR E; owner decision D6 (b), Huatuo's sort + class rule, Huatuo's plan review).
//
//     node --test tests/program_cards.test.mjs
//
// The card shows: a crest, the name (shortName || name) and nickname; the D-tag · conference · city; the season line;
// ONE fact row; Save and Compare, each named for its program. The fact row is the first rule that applies:
// Recommended's reasons; the value the list is sorted by (when the card does not already show it); a highlighted
// class's commits, after the sorted value in the same row (a Commits sort shows them once); otherwise Undergrads. A
// value the visitor asked for that is missing says why in a word, never a bare dash; a missing default leaves the row
// empty. Plus the Compare tray: "Compare N of 4", each program's remove button named for it, Compare →, Clear.
//
// Offline: the page's own inline script runs in a vm over the committed index. Expected values are read from the
// index rows here (the data refreshes daily), never from a page helper. FIX checks fail on origin/main; GUARD checks
// pass there too and pin what must not change.
//
// PROGRAM_CARDS_TEST_HTML (optional) points at another copy of index.html, to run these checks against it.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.PROGRAM_CARDS_TEST_HTML || path.join(PUBLIC, 'index.html');
const PAGE = fs.readFileSync(HTML, 'utf8');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));

function loadPage() {
  const el = () => ({ innerHTML: '', textContent: '', value: '', dataset: {}, style: {}, hidden: false,
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false }, setAttribute() { }, getAttribute: () => null,
    addEventListener() { }, removeEventListener() { }, querySelector: () => el(), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, contains: () => false });
  const els = new Map();
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: el(), body: el(), querySelector: s => (els.has(s) ? els.get(s) : (els.set(s, el()), els.get(s))),
      querySelectorAll: () => [], createElement: el, addEventListener() { } },
    location: { hash: '', replace(h) { this.hash = h; } }, history: { replaceState() { } }, matchMedia: () => ({ matches: false }),
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } }, innerWidth: 1400, addEventListener() { },
    fetch: async url => {
      let rel = url.replace(/^\//, ''); if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
      const p = path.join(PUBLIC, rel.replace(/\?.*$/, ''));
      if (!p.startsWith(PUBLIC) || !fs.existsSync(p)) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      const body = fs.readFileSync(p, 'utf8'); return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = PAGE.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n')
    + '\n;Object.assign(globalThis, { S, loadIndex, cardHtml, cmpTrayHtml: typeof cmpTrayHtml === "function" ? cmpTrayHtml : null });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}
const sb = loadPage();
await sb.loadIndex();
const P = INDEX.programs;
const row = slug => sb.S.index.programs.find(p => p.slug === slug);
const disp = p => p.shortName || p.name;
const esc = t => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const num = n => Number(n).toLocaleString('en-US');
// The card's fact row and season line, as markup and as text.
const factOf = html => (html.match(/<div class="card-fact">([\s\S]*?)<\/div>/) || [, null])[1];
const sumOf = html => (html.match(/<div class="card-sum">([\s\S]*?)<\/div>/) || [, null])[1];
const text = h => String(h ?? '').replace(/<span class="sr-only">[\s\S]*?<\/span>/g, '').replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').trim();
// Draw a card with the list's sort and highlighted classes set, then put them back.
function card(p, { sort = 'name', classes = [] } = {}, why) {
  const f = sb.S.filters, was = { sort: f.sort, classYear: f.classYear };
  f.sort = sort; f.classYear = classes;
  try { return sb.cardHtml(p, why); } finally { Object.assign(f, was); }
}
const find = (fn, what) => { const p = P.find(fn); assert.ok(p, `fixture: no program ${what} in the committed index`); return row(p.slug); };

test('FIX default list: the one fact row is Undergrads, nothing else from the old facts grid or foot', () => {
  const p = find(x => x.undergradEnrollment != null && x.tuitionOutOfState != null && x.academicRank != null && Object.keys(x.commitmentsByYear || {}).length && x.rosterSize != null, 'with every old fact');
  for (const sort of ['name', 'rpi', 'record', 'conference']) {
    const html = card(p, { sort });
    assert.equal(text(factOf(html)), `Undergrads ${num(p.undergradEnrollment)}`, `sorted by ${sort}`);
    for (const gone of ['Tuition', 'US rank', 'on roster', 'Commits', 'class="facts"', 'class="dot"'])
      assert.ok(!html.includes(gone), `sorted by ${sort}: "${gone}" is still on the card`);
  }
});

test('FIX a missing default leaves the row empty (its track stays), never a dash or "N/A"', () => {
  const p = find(x => x.undergradEnrollment == null, 'without undergrads');
  const html = card(p);
  assert.equal(factOf(html), '', 'the fact row is not there, or not empty');
  assert.ok(!/>(—|N\/A)</.test(html), 'a placeholder is shown');
});

test('FIX sorted by a fact the card does not show: the row is that value, labelled; a missing one says why in a word', () => {
  const D1 = x => x.division === 'D1';
  const withAll = find(x => D1(x) && x.admissionRate != null && x.academicRank != null && x.tuitionOutOfState != null && x.undergradEnrollment != null && x.region && x.ownership, 'D1 with the facts');
  const t = (p, sort) => text(factOf(card(p, { sort })));
  assert.match(t(withAll, 'admit'), new RegExp(`^Admission rate \\d+(\\.\\d)?%$`));
  assert.equal(t(withAll, 'academicRank'), `US rank (THE) #${withAll.academicRank}`);
  assert.equal(t(withAll, 'tuition'), `Tuition (out-of-state) $${num(withAll.tuitionOutOfState)} / yr`);
  assert.equal(t(withAll, 'undergrads'), `Undergrads ${num(withAll.undergradEnrollment)}`);
  assert.equal(t(withAll, 'region'), `Region ${withAll.region}`);
  assert.equal(t(withAll, 'type'), `Type ${withAll.ownership.replace(/ (nonprofit|for-profit)$/, '')}`);
  const noAdmit = find(x => x.admissionRate == null, 'without an admission rate');
  assert.equal(t(noAdmit, 'admit'), 'Admission rate Not reported');
  const unranked = find(x => x.academicRank == null, 'unranked by THE');
  const ranked = factOf(card(unranked, { sort: 'academicRank' }));
  assert.equal(text(ranked), 'US rank (THE) Not ranked');
  assert.match(ranked, /<span class="sr-only">: [^<]*not among the 171 it ranks<\/span>/, 'the reason is in the accessible text, not only a tooltip');
  const d2 = find(x => x.division === 'D2', 'in D2');
  assert.equal(t(d2, 'cups'), 'College Cups Not applicable', 'College Cups do not apply outside D1');
  for (const sort of ['admit', 'academicRank', 'tuition', 'undergrads', 'cups', 'region', 'type'])
    assert.ok(!/>(—|N\/A)</.test(card(unranked, { sort })), `${sort}: a bare dash or N/A`);
});

test('FIX a highlighted class: its commits - a D1 count (0 included), "(partial)" for an incidental count, "Not collected" otherwise', () => {
  const d1 = find(x => x.division === 'D1' && (x.commitmentsByYear || {})['2027'] > 0, 'D1 with 2027 commits');
  const t = (p, opts) => text(factOf(card(p, opts)));
  assert.equal(t(d1, { classes: ['2027'] }), `Class of 2027 commits ${num(d1.commitmentsByYear['2027'])}`);
  const d1zero = find(x => x.division === 'D1' && !(x.commitmentsByYear || {})['2027'], 'D1 with no 2027 commits');
  assert.equal(t(d1zero, { classes: ['2027'] }), 'Class of 2027 commits 0', 'D1 collects commits, so none is a real 0');
  const partial = find(x => x.division !== 'D1' && (x.commitmentsByYear || {})['2027'] > 0, 'outside D1 with an incidental 2027 count');
  const ph = factOf(card(partial, { classes: ['2027'] }));
  assert.match(ph, /\(partial<span class="sr-only">: not systematically collected<\/span>\)/, '#438\'s note');
  const none = find(x => x.division === 'D3' && !Object.keys(x.commitmentsByYear || {}).length, 'D3 with no commits');
  assert.equal(t(none, { classes: ['2027'] }), 'Class of 2027 commits Not collected', 'never 0 outside D1 (#411)');
  assert.equal(t(d1, { classes: ['2027', '2028'] }), `Class of 2027 + 2028 commits ${num(d1.commitmentsByYear['2027'] + (d1.commitmentsByYear['2028'] || 0))}`);
});

test('FIX Huatuo: sorted by a fact AND a class highlighted - the sorted value first, then the class commits, in ONE row', () => {
  const p = find(x => x.division === 'D1' && x.tuitionOutOfState != null && (x.commitmentsByYear || {})['2027'] > 0, 'D1 with tuition and 2027 commits');
  const html = card(p, { sort: 'tuition', classes: ['2027'] });
  assert.equal(text(factOf(html)), `Tuition (out-of-state) $${num(p.tuitionOutOfState)} / yr · Class of 2027 commits ${num(p.commitmentsByYear['2027'])}`);
  assert.equal((html.match(/class="card-fact"/g) || []).length, 1, 'one fact row');
});

test('FIX Huatuo: sorted by Commits with a class highlighted - the value shows once', () => {
  const p = find(x => x.division === 'D1' && (x.commitmentsByYear || {})['2027'] > 0, 'D1 with 2027 commits');
  const got = text(factOf(card(p, { sort: 'commits', classes: ['2027'] })));
  assert.equal(got, `Class of 2027 commits ${num(p.commitmentsByYear['2027'])}`);
  assert.equal(got.match(/commits/g).length, 1, 'the commits are shown twice');
  const all = Object.values(p.commitmentsByYear).reduce((a, n) => a + n, 0);
  assert.equal(text(factOf(card(p, { sort: 'commits' }))), `Commits ${num(all)}`, 'no class: every class, under the sort\'s own label');
});

test('FIX Recommended: the reasons take the fact row\'s place (one wrapper, no fact row beside them)', () => {
  const p = find(x => x.undergradEnrollment != null, 'with undergrads');
  const why = '<ul class="recs-why" aria-label="Why"><li>a reason</li></ul>';
  const html = card(p, {}, why);
  const detail = (html.match(/<div class="card-detail">([\s\S]*?)<\/div>\s*<\/div>\s*<div class="foot">/) || [])[1] || '';
  assert.equal(detail.trim(), why, 'the detail wrapper holds exactly the reasons');
});

test('FIX the season line: this fall\'s record, with the RPI named by its season where RPI applies', () => {
  const d1 = find(x => x.division === 'D1' && x.currentSeason?.record && (x.rpiHistory || [])[0]?.rank != null, 'D1 with a record and an RPI');
  const s = text(sumOf(card(d1)));
  assert.ok(s.startsWith(`${d1.currentSeason.year}: ${d1.currentSeason.record}`), s);
  assert.match(s, /· RPI \d{4}( \(in progress\))? #\d+$/);
  const d3 = find(x => x.division === 'D3' && x.currentSeason?.record, 'D3 with a record');
  assert.equal(text(sumOf(card(d3))), `${d3.currentSeason.year}: ${d3.currentSeason.record}`, 'RPI does not apply outside D1');
  const none = find(x => !x.currentSeason?.record, 'without a record yet');
  assert.match(text(sumOf(card(none))), /^No \d{4} results yet$/);
});

test('FIX Huatuo: each card\'s Save and Compare are named for the program, by the name readers see', () => {
  const p = find(x => x.shortName && x.shortName !== x.name, 'whose shortName differs from its name');
  const html = card(p);
  assert.ok(html.includes(`aria-label="Save ${esc(disp(p))}"`), 'Save is not named for the program');
  assert.ok(html.includes(`aria-label="Compare ${esc(disp(p))}"`), 'Compare is not named for the program');
  assert.ok(!html.includes(`aria-label="Save ${esc(p.name)}"`), 'named with name, not what the card shows');
});

test('FIX the Compare tray: "Compare N of 4", a remove button named for each program, Compare →, Clear; nothing when empty', () => {
  assert.equal(typeof sb.cmpTrayHtml, 'function', 'there is no Compare tray');
  const [a, b] = P.filter(x => x.shortName && x.shortName !== x.name).slice(0, 2).map(x => row(x.slug));
  const was = sb.S.compare;
  try {
    sb.S.compare = [];
    assert.equal(sb.cmpTrayHtml(), '', 'an empty tray is drawn');
    sb.S.compare = [a.slug, b.slug];
    const html = sb.cmpTrayHtml();
    assert.match(html, /role="region" aria-label="Compare"/);
    assert.ok(html.includes('Compare 2 of 4'));
    for (const p of [a, b]) assert.ok(html.includes(`aria-label="Remove ${esc(disp(p))} from comparison"`), `${p.slug}: its remove button is not named for it`);
    assert.ok(html.includes(`href="#/compare/${a.slug},${b.slug}"`), 'Compare → does not open the comparison');
    assert.ok(html.includes('id="cmpTrayClear"'));
    assert.ok(!/data-cmp="/.test(html), 'a tray ✕ is a toggle that syncToggles would rewrite');
  } finally { sb.S.compare = was; }
});

test('FIX tap targets: Save, Compare and the tray\'s controls are 44px at the site\'s touch breakpoint (768px)', () => {
  const css = [...PAGE.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n').replace(/\r\n/g, '\n');
  const blocks = [...css.matchAll(/@media \(max-width: 768px\) \{([\s\S]*?)\n\}/g)].map(m => m[1]).join('\n');
  const has44 = sel => blocks.split('\n').some(l => l.split('{')[0].split(',').map(x => x.trim()).includes(sel) && /min-height: 44px/.test(l) && /min-width: 44px/.test(l));
  for (const sel of ['.pcard .foot-actions .star-btn', '.pcard .foot-actions .cmp-btn', '.cmp-tray-x', '.cmp-tray .btn']) assert.ok(has44(sel), `${sel}: no 44px rule at 768px`);
});

test('GUARD the card is titled shortName || name, and names its division on every card', () => {
  for (const d of ['D1', 'D2', 'D3']) {
    const p = find(x => x.division === d && x.shortName && x.shortName !== x.name, `in ${d} with a shortName`);
    const html = card(p);
    assert.ok(html.includes(`<h3>${esc(p.shortName)}<span class="nick">`), `${d}: the card is not titled with shortName`);
    const meta = (html.match(/<div class="meta">([\s\S]*?)<\/div>/) || [])[1] || '';
    assert.match(meta, new RegExp(`\\b${d}\\b`), `${d}: the card does not name its division`);
  }
  const noShort = find(x => !x.shortName, 'without a shortName');
  assert.ok(card(noShort).includes(`<h3>${esc(noShort.name)}<span class="nick">`), 'a program with no shortName is not titled by name');
});
