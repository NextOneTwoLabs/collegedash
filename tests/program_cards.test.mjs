// The program card (#465 PR E; restated by #492: a school-colour title band, brackets, no ranks or records).
//
//     node --test tests/program_cards.test.mjs
//
// The card shows: a title band (name = shortName || name, nickname, the titles badge on its right); the D-tag ·
// conference · city; Undergrads and Tuition as brackets; Save and Compare, each named for its program. Recommended mode
// puts its reasons in the detail wrapper under them. The brackets, the band colours, the heights and "sorting only
// reorders" are tested in tests/card_brackets.test.mjs. Plus the Compare tray: "Compare N of 4", each program's remove
// button named for it, Compare →, Clear.
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
const text = h => String(h ?? '').replace(/<span class="sr-only">[\s\S]*?<\/span>/g, '').replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').trim();
// Draw a card with the list's sort and highlighted classes set, then put them back.
function card(p, { sort = 'name', classes = [] } = {}, why) {
  const f = sb.S.filters, was = { sort: f.sort, classYear: f.classYear };
  f.sort = sort; f.classYear = classes;
  try { return sb.cardHtml(p, why); } finally { Object.assign(f, was); }
}
const find = (fn, what) => { const p = P.find(fn); assert.ok(p, `fixture: no program ${what} in the committed index`); return row(p.slug); };

test('FIX Recommended: the reasons fill the detail wrapper under the two bracket rows; ordinary cards leave it empty', () => {
  const p = find(x => x.undergradEnrollment != null, 'with undergrads');
  const why = '<ul class="recs-why" aria-label="Why"><li>a reason</li></ul>';
  const detailOf = html => (html.match(/<div class="card-detail">([\s\S]*?)<\/div>\s*<\/div>\s*<div class="foot">/) || [])[1];
  assert.equal((detailOf(card(p, {}, why)) || '').trim(), why, 'the detail wrapper holds exactly the reasons');
  assert.equal(detailOf(card(p)), '', 'an ordinary card adds nothing under the brackets (no sort or class fact)');
  const html = card(p, {}, why);
  assert.ok(html.indexOf('card-ug') < html.indexOf('card-tuition') && html.indexOf('card-tuition') < html.indexOf('card-detail'), 'rows: undergrads, tuition, then the reasons');
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
    assert.ok(html.includes(`<span class="nm">${esc(p.shortName)}</span>`), `${d}: the card is not titled with shortName`);
    const meta = (html.match(/<div class="meta">([\s\S]*?)<\/div>/) || [])[1] || '';
    assert.match(meta, new RegExp(`\\b${d}\\b`), `${d}: the card does not name its division`);
  }
  const noShort = find(x => !x.shortName, 'without a shortName');
  assert.ok(card(noShort).includes(`<span class="nm">${esc(noShort.name)}</span>`), 'a program with no shortName is not titled by name');
});
