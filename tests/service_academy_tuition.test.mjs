// #493: the program card's Tuition row says "No tuition" over "(service academy)" for Air Force, Army, Navy and Coast
// Guard instead of "Not reported". College Scorecard has no tuition figure for them (they charge none), and a bare
// "Not reported" reads as a hole in the data. Owner decisions (2026-10-17): two lines in the Tuition value, line 1 in the
// normal bold value style and line 2 muted (.na), inside the two lines the row already reserves, so no card changes
// height; exactly these four slugs; only when tuition is missing (a published figure still wins - Merchant Marine
// has an $895 figure and is not an academy here); Stats, the profile and Compare keep their dash; each academy's official
// admissions page is cited three ways - a source constant, the card's tooltip and screen-reader text, a row in the
// About-the-data table.
//
//     node --test tests/service_academy_tuition.test.mjs
//
// Offline: the page's own inline script runs in a vm over the committed index. The expected wording and the unitIds are
// written out here by independent code; the academies' URLs are NOT repeated here (they live in one constant so they
// are easy to change) - the tests read them from the page and check they are used, not what they are.
//
// Tests 1, 2, 5, 6, 6b, 7, 11 and 12 fail on origin/main. Tests 3, 4, 8, 9 and 10 are GUARDS that pass on main too: they stop
// the new rule from reaching a program with a figure, a program that is not one of the four, or another view (Stats, the
// profile's School tab, Compare), which keep their dash; and they keep About the data independent of the program index (it
// draws with the index failing or still loading; the academies row is the one part that reads it).
//
// SERVICE_ACADEMY_TEST_HTML (optional) points at another copy of index.html, to run these checks against it.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..');
const PUBLIC = path.join(ROOT, 'public');
const HTML = process.env.SERVICE_ACADEMY_TEST_HTML || path.join(PUBLIC, 'index.html');
const PAGE = fs.readFileSync(HTML, 'utf8');

// `index` says what the page's request for the program index does: 'ok' (the default), 'http500' (an error answer), 'abort'
// (no answer at all) or 'hold' (no answer until the test calls __test.release()). __test.calls lists every URL the page fetched.
function loadPage({ index = 'ok' } = {}) {
  const calls = []; let release; const held = new Promise(r => { release = r; });
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
      calls.push(url);
      if (url.replace(/^\//, '') === 'api/v1/programs') {
        if (index === 'http500') return { ok: false, status: 500, async json() { throw new Error('HTTP 500'); } };
        if (index === 'abort') throw new TypeError('Failed to fetch');
        if (index === 'hold') await held;
      }
      let rel = url.replace(/^\//, ''); if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
      else if (rel.startsWith('api/v1/programs/')) rel = `data/programs/${rel.slice('api/v1/programs/'.length)}.json`; // a profile (the School tab, Compare)
      const p = path.join(PUBLIC, rel.replace(/\?.*$/, ''));
      if (!p.startsWith(PUBLIC) || !fs.existsSync(p)) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      const body = fs.readFileSync(p, 'utf8'); return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  sandbox.__test = { calls, release: () => release() };
  const lines = PAGE.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const names = ['SERVICE_ACADEMY_SOURCES'];
  const src = lines.slice(a + 1, b).join('\n')
    + `\n;Object.assign(globalThis, { S, loadIndex, cardHtml, renderFaq, renderProfile, renderCompare, tableHtml, ${names.map(n => `${n}: typeof ${n} === 'undefined' ? undefined : ${n}`).join(', ')} });\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}
const sb = loadPage();
await sb.loadIndex();
const P = sb.S.index.programs;
const bySlug = Object.fromEntries(P.map(p => [p.slug, p]));
const text = h => String(h ?? '').replace(/<span class="sr-only">[\s\S]*?<\/span>/g, '').replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&#39;/g, "'").trim();
const srText = h => [...String(h ?? '').matchAll(/<span class="sr-only">([\s\S]*?)<\/span>/g)].map(m => m[1]).join('');
const card = p => sb.cardHtml(p);
// The inner HTML of every <span class="CLS"> in html (balanced, so nested spans stay inside their parent).
function spansOf(html, cls) {
  const out = [], open = `<span class="${cls}">`;
  for (let at = html.indexOf(open); at >= 0; at = html.indexOf(open, at + 1)) {
    let depth = 1, i = at + open.length; const re = /<(\/?)span\b[^>]*>/g; re.lastIndex = i;
    for (let m; (m = re.exec(html));) { depth += m[1] ? -1 : 1; if (!depth) { out.push(html.slice(i, m.index)); break; } }
  }
  return out;
}
// A tuition line is `<span class="tl"` plus optional attributes; this returns each line's outer HTML, balanced.
function tuitionLines(html) {
  const out = [];
  for (let at = html.indexOf('<span class="tl"'); at >= 0; at = html.indexOf('<span class="tl"', at + 1)) {
    let depth = 0; const re = /<(\/?)span\b[^>]*>/g; re.lastIndex = at;
    for (let m; (m = re.exec(html));) { depth += m[1] ? -1 : 1; if (!depth) { out.push(html.slice(at, m.index + m[0].length)); break; } }
  }
  return out;
}
const rowOf = (html, cls) => (html.match(new RegExp(`<div class="card-fact ${cls}">([\\s\\S]*?)</div>\\s*(?=<div class="card-fact|<div class="card-detail)`)) || [, null])[1];
const tuitionRow = p => rowOf(card(p), 'card-tuition');
const tlText = p => tuitionLines(tuitionRow(p)).map(text);
const attr = (tag, name) => (tag.match(new RegExp(`${name}="([^"]*)"`)) || [, null])[1];
const unesc = t => String(t).replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

// Independent copies of the owner's decisions.
const ACADEMY_UNITIDS = { 'air-force': 128328, 'army': 197036, 'navy': 164155, 'coast-guard': 130624 };
const ACADEMIES = Object.keys(ACADEMY_UNITIDS);
const noFigure = p => ({ ...p, tuitionInState: null, tuitionOutOfState: null });
// How the FAQ's prose names a program: as readers see it everywhere (shortName || name), then its division.
const academyName = p => `${p.shortName || p.name} (${p.division})`;
const andList = xs => (xs.length > 1 ? `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}` : xs.join(''));

test('1. the four academies\' cards read "No tuition" over "(service academy)": line 1 plain bold, line 2 muted (.na), two lines, the row\'s own height', () => {
  for (const slug of ACADEMIES) {
    const p = bySlug[slug];
    assert.ok(p, `${slug}: not in the index`);
    for (const [label, row] of [['the index row', p], ['with no figure', noFigure(p)]]) {
      // The live row has no figure today; if Scorecard ever publishes one, the figure wins (test 3) and this row is a bracket.
      if (row === p && (p.tuitionInState != null || p.tuitionOutOfState != null)) continue;
      const html = tuitionRow(row);
      assert.ok(html, `${slug}: no tuition row`);
      assert.equal((html.match(/class="fl"/g) || []).length, 1, `${slug}: one Tuition label`);
      assert.ok(text(html).startsWith('Tuition'), slug);
      const lines = tuitionLines(html);
      assert.deepEqual(lines.map(text), ['No tuition', '(service academy)'], `${slug} (${label})`);
      assert.ok(!/class="na"/.test(lines[0]), `${slug}: line 1 must be the normal bold value style, not muted`);
      assert.ok(/<span class="na"[^>]*>\(service academy\)/.test(lines[1]), `${slug}: line 2 must be the muted .na style`);
      assert.ok(!/Not reported/.test(text(html) + srText(html)), `${slug}: still says Not reported`);
      assert.ok(!/\$\d/.test(text(html)), `${slug}: a dollar figure on the card`);
    }
  }
});

test('2. the card cites the academy\'s admissions page in its tooltip (title) and its screen-reader text, from the one constant', () => {
  for (const slug of ACADEMIES) {
    const src = sb.SERVICE_ACADEMY_SOURCES?.[slug];
    assert.ok(src && typeof src.name === 'string' && src.name && /^https:\/\//.test(src.url), `${slug}: no source (name + https url) in SERVICE_ACADEMY_SOURCES`);
    const html = tuitionRow(noFigure(bySlug[slug]));
    const titles = [...html.matchAll(/ title="([^"]*)"/g)].map(m => unesc(m[1]));
    assert.ok(titles.length >= 1, `${slug}: no tooltip on the tuition row`);
    for (const line of tuitionLines(html)) assert.ok(/ title="/.test(line), `${slug}: hovering "${text(line)}" shows no source`);
    for (const t of titles) {
      assert.ok(t.includes(src.name), `${slug}: tooltip "${t}" does not name its source "${src.name}"`);
      assert.match(t, /service academies charge no tuition/i, `${slug}: tooltip "${t}"`);
    }
    const sr = srText(html);
    assert.ok(sr.includes(src.name) && /service academies charge no tuition/i.test(sr), `${slug}: screen-reader text "${sr}"`);
    // the visible words and the screen-reader words are separate: the sr-only span sits inside the muted line, once
    assert.equal((html.match(/class="sr-only"/g) || []).length, 1, `${slug}: screen-reader text said once`);
  }
});

test('3. GUARD (passes on main too): the rule applies only when tuition is missing: an academy with a figure shows its bracket(s), exactly as any other program', () => {
  for (const slug of ACADEMIES) {
    const p = bySlug[slug];
    assert.equal(p.ownership, 'Public', `fixture: ${slug} is Public in the index (two residency lines when it has a figure)`);
    const both = { ...p, tuitionInState: 5000, tuitionOutOfState: 5000 };
    assert.deepEqual(tlText(both), ['Under $15K in-state', 'Under $15K out-of-state'], `${slug}: both figures`);
    const oneSide = { ...p, tuitionInState: 20000, tuitionOutOfState: null };
    assert.deepEqual(tlText(oneSide), ['$15K–30K in-state', 'Not reported out-of-state'], `${slug}: one residency only`);
    const other = { ...p, tuitionInState: null, tuitionOutOfState: 61000 };
    assert.deepEqual(tlText(other), ['Not reported in-state', '$60K+ out-of-state'], `${slug}: out-of-state only`);
    const priv = { ...p, ownership: 'Private', tuitionInState: null, tuitionOutOfState: 52000 };
    assert.deepEqual(tlText(priv), ['$45K–60K'], `${slug}: a single bracket line`);
    const zero = { ...p, tuitionInState: 0, tuitionOutOfState: 0 };
    assert.deepEqual(tlText(zero), ['Under $15K in-state', 'Under $15K out-of-state'], `${slug}: a published 0 is a figure, not a gap`);
    for (const row of [both, oneSide, other, priv, zero]) assert.ok(!/No tuition|service academy/.test(text(tuitionRow(row)) + srText(tuitionRow(row))), `${slug}: academy wording next to a figure`);
  }
});

test('4. GUARD (passes on main too): every other program with missing tuition still reads "Not reported"; Merchant Marine (has $895) and look-alike slugs get no academy wording', () => {
  const missing = P.filter(p => p.tuitionInState == null && p.tuitionOutOfState == null && !ACADEMIES.includes(p.slug)).map(p => p.slug);
  for (const must of ['emmanuel-ga', 'simon-fraser', 'claremont-mudd-scripps']) assert.ok(missing.includes(must), `fixture: ${must} has no tuition in the index`);
  for (const slug of missing) {
    const row = tuitionRow(bySlug[slug]);
    assert.deepEqual(tuitionLines(row).map(text), ['Not reported'], `${slug}: ${text(row)}`);
    assert.ok(!/No tuition|service academy/.test(text(row) + srText(row)), `${slug}: academy wording on a non-academy`);
  }
  // Merchant Marine publishes $895: a bracket today, and "Not reported" - never the academy wording - if the figure went missing.
  const mm = bySlug['merchant-marine'];
  assert.ok(mm && mm.tuitionInState === 895 && mm.tuitionOutOfState === 895, 'fixture: merchant-marine has its $895 figure');
  assert.deepEqual(tlText(mm), ['Under $15K in-state', 'Under $15K out-of-state']);
  assert.deepEqual(tlText(noFigure(mm)), ['Not reported'], 'merchant-marine is not one of the four');
  assert.ok(!Object.keys(sb.SERVICE_ACADEMY_SOURCES || {}).includes('merchant-marine'), 'merchant-marine is in SERVICE_ACADEMY_SOURCES');
  // keyed by slug alone: a name that merely resembles an academy, and slugs that are properties of every object, get nothing
  const emmanuel = bySlug['emmanuel-ga'];
  for (const slug of ['constructor', '__proto__', 'toString', 'hasOwnProperty', 'air-force-2', 'United States Air Force Academy'])
    assert.deepEqual(tlText({ ...emmanuel, slug }), ['Not reported'], slug);
  assert.deepEqual(tlText({ ...emmanuel, name: 'United States Air Force Academy', shortName: 'Air Force' }), ['Not reported'], 'matched on the name, not the slug');
});

test('5. the set is exactly air-force, army, navy and coast-guard, and each slug is pinned to its College Scorecard unitId', () => {
  assert.deepEqual(Object.keys(sb.SERVICE_ACADEMY_SOURCES || {}).sort(), [...ACADEMIES].sort());
  for (const [slug, unitId] of Object.entries(ACADEMY_UNITIDS)) {
    const file = path.join(ROOT, 'programs', slug, 'sources', 'scorecard.json');
    assert.ok(fs.existsSync(file), `${slug}: no ${path.relative(ROOT, file)}`);
    const sc = JSON.parse(fs.readFileSync(file, 'utf8'));
    assert.equal(sc.data?.unitId, unitId, `${slug}: Scorecard unitId`);
    assert.match(sc.sourceUrl || '', new RegExp(`[?&]id=${unitId}\\b`), `${slug}: the Scorecard request was for another school`);
    assert.ok(bySlug[slug], `${slug}: not in the index`);
  }
  // the one other military academy in the data is not an academy for this rule
  const mm = JSON.parse(fs.readFileSync(path.join(ROOT, 'programs', 'merchant-marine', 'sources', 'scorecard.json'), 'utf8'));
  assert.equal(mm.data.unitId, 197027);
  assert.ok(!Object.values(ACADEMY_UNITIDS).includes(mm.data.unitId));
});

// The "Where does the data come from?" table, as rows of cells.
const tableRowsOf = app => {
  const at = app.indexOf('<h3>Where does the data come from?</h3>');
  assert.ok(at >= 0, 'the FAQ has no "Where does the data come from?" card');
  const table = app.slice(at, app.indexOf('</table>', at));
  return [...table.matchAll(/<tr>([\s\S]*?)<\/tr>/g)].map(m => [...m[1].matchAll(/<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/g)].map(c => c[1]));
};
async function faqRows(pg = sb) { await pg.renderFaq(); return tableRowsOf(pg.document.querySelector('#app').innerHTML); }
// A promise that rejects (and so fails the test) when it has not settled in ms, instead of a test that hangs.
const within = (promise, ms, what) => { let t; return Promise.race([promise, new Promise((_, no) => { t = setTimeout(() => no(new Error(`${what} did not finish in ${ms} ms`)), ms); })]).finally(() => clearTimeout(t)); };
const settle = async () => { for (let i = 0; i < 30; i++) await new Promise(r => setTimeout(r, 0)); };
const indexRequests = pg => pg.__test.calls.filter(u => u.replace(/^\//, '') === 'api/v1/programs').length;
const isAcademyRow = r => Object.values(sb.SERVICE_ACADEMY_SOURCES || {}).some(s => r[0].includes(s.url));

test('6. the About-the-data table credits the academies: one row, a link to each admissions page from the constant, saying what it supplies', async () => {
  const rows = await faqRows();
  assert.ok(rows.length >= 7, 'fixture: the source table');
  assert.deepEqual(rows[0].map(text), ['Source', 'What it supplies', 'Who publishes it']);
  const sources = Object.values(sb.SERVICE_ACADEMY_SOURCES || {});
  assert.equal(sources.length, 4);
  const mine = rows.filter(r => sources.some(s => r[0].includes(s.url)));
  assert.equal(mine.length, 1, 'the academies are credited in exactly one row');
  const [src, supplies, who] = mine[0];
  assert.equal(rows.length, rows.filter(r => r.length === 3).length, 'every row has three cells');
  for (const s of sources) {
    const link = src.match(new RegExp(`<a [^>]*href="${s.url.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}"[^>]*>([^<]*)</a>`));
    assert.ok(link, `no link to ${s.url} in the source cell: ${src}`);
    assert.ok(/target="_blank"/.test(link[0]) && /rel="noopener"/.test(link[0]), `${s.url}: opens in a new tab with noopener, as the other sources do`);
    assert.ok(text(link[1]), `${s.url}: link text`);
  }
  // What the source supplies, in the THE and Scorecard rows' manner: the fact, then what the card does with it.
  const slugs = Object.keys(sb.SERVICE_ACADEMY_SOURCES);
  const named = slugs.map(s => academyName(bySlug[s]));
  assert.equal(text(supplies),
    `That ${andList(named)} charge no tuition: their program cards say “No tuition (service academy)” where College Scorecard has no tuition figure`);
  assert.ok(text(who), 'says who publishes it');
});

// The division rule (D1/D2/D3 wherever a program appears) reaches the FAQ's prose: each academy is named as readers see it
// everywhere (shortName || name) with its division, "Army (D1)" as the trends chips' "not in the index" text does, and the
// divisions are read off the index rows, not written down in the page.
test('6b. the FAQ names every academy with its division, and reads the division from the data (change a row and the prose follows)', async () => {
  const supplies = async () => {
    const row = (await faqRows()).find(r => Object.values(sb.SERVICE_ACADEMY_SOURCES || {}).some(s => r[0].includes(s.url)));
    return text(row?.[1]);
  };
  const slugs = ACADEMIES.slice().sort();
  const before = await supplies();
  for (const slug of slugs) {
    const p = bySlug[slug], label = academyName(p);
    assert.match(p.division, /^D[123]$/, `${slug}: the index row has a division`);
    assert.ok(before.includes(label), `${slug}: "${label}" is not in the FAQ prose: ${before}`);
  }
  // no academy appears bare: take every "Name (Dn)" out and none of the names is left
  let rest = before; for (const slug of slugs) rest = rest.replace(academyName(bySlug[slug]), '');
  for (const slug of slugs) assert.ok(!rest.includes(bySlug[slug].shortName || bySlug[slug].name), `${slug}: named without its division: ${before}`);
  // and it is the DATA that says it: move Army and Coast Guard to other divisions in the loaded rows and the prose follows
  const army = bySlug['army'], cg = bySlug['coast-guard'], was = [army.division, cg.division];
  try {
    army.division = was[0] === 'D2' ? 'D3' : 'D2'; cg.division = was[1] === 'D1' ? 'D3' : 'D1';
    const after = await supplies();
    assert.ok(after.includes(academyName(army)) && after.includes(academyName(cg)), `the prose did not follow the data: ${after}`);
    assert.notEqual(after, before);
  } finally { [army.division, cg.division] = was; }
});

test('7. one constant: each academy URL appears once in the page source, and the constant is the only place the card and the FAQ get it', () => {
  assert.equal(Object.keys(sb.SERVICE_ACADEMY_SOURCES || {}).length, 4, 'SERVICE_ACADEMY_SOURCES has the four academies');
  for (const [slug, s] of Object.entries(sb.SERVICE_ACADEMY_SOURCES || {})) {
    assert.equal(PAGE.split(s.url).length - 1, 1, `${slug}: ${s.url} is written ${PAGE.split(s.url).length - 1} times in index.html (want 1)`);
    assert.equal(new URL(s.url).protocol, 'https:', slug);
  }
});

// GUARD. The owner decided "the card change only": Stats, the profile and Compare keep their dash for a missing tuition, and
// the academy wording lives in the card's tuitionLinesHtml and nowhere else. This passes on main too. What it protects is a
// future refactor that routes those views through tuitionLinesHtml (or the card's academy helpers) to "share the tuition
// logic": it would flip these three dashes to "No tuition (service academy)", in a table column, a facts row and a
// side-by-side comparison, none of which reserve two lines or carry the source.
test('8. GUARD (passes on main too): Stats, the profile\'s School tab and Compare still show "—" for the four academies\' tuition', async () => {
  const wording = /No tuition|service academy|Not reported/;
  // Stats: the Tuition / yr column. It is only on the table when a program in it has a figure, so a program with one goes in too.
  const control = bySlug['florida-state'];
  assert.ok(control && control.tuitionOutOfState != null, 'fixture: florida-state has a tuition figure');
  const table = sb.tableHtml([...ACADEMIES.map(s => bySlug[s]), control], {});
  const heads = [...table.matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/g)].map(m => text(m[1]));
  const at = heads.findIndex(h => /Tuition \/ yr/.test(h));
  assert.ok(at >= 0, `fixture: the Tuition / yr column is on the table (columns: ${heads.join(' | ')})`);
  const statsCells = slug => [...((table.match(new RegExp(`<tr class="team-row[^"]*" data-slug="${slug}"[^>]*>([\\s\\S]*?)</tr>`)) || [, ''])[1]).matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)].map(m => m[1]);
  assert.equal(statsCells('florida-state').length, heads.length, 'fixture: one cell per column');
  assert.match(text(statsCells('florida-state')[at]), /\$/, 'fixture: the control row shows a dollar figure in that column');
  for (const slug of ACADEMIES) assert.equal(text(statsCells(slug)[at]), '—', `Stats, ${slug}`);

  // The profile's School tab: the Cost card's two rows.
  const school = async slug => { await sb.renderProfile(slug, 'school'); return sb.document.querySelector('#tab').innerHTML; };
  const mmTab = await school('merchant-marine');
  assert.match(mmTab, /<tr><th>Tuition \(in-state\)<\/th><td>\$895<\/td><\/tr>/, 'fixture: the control profile shows its figure in these rows');
  for (const slug of ACADEMIES) {
    const tab = await school(slug);
    assert.match(tab, /<tr><th>Tuition \(in-state\)<\/th><td>—<\/td><\/tr>/, `profile, ${slug}: in-state`);
    assert.match(tab, /<tr><th>Tuition \(out-of-state\)<\/th><td>—<\/td><\/tr>/, `profile, ${slug}: out-of-state`);
    assert.doesNotMatch(tab, wording, `profile, ${slug}: the card's wording is on the School tab`);
  }

  // Compare: the Tuition / yr row, one cell per program.
  const compareRow = async slugs => {
    sb.S.compare = slugs; await sb.renderCompare();
    const m = sb.document.querySelector('#app').innerHTML.match(/<tr><th>Tuition \/ yr<\/th>((?:<td\b[^>]*>[\s\S]*?<\/td>)+)<\/tr>/);
    assert.ok(m, `fixture: Compare has a Tuition / yr row for ${slugs.join(', ')}`);
    return [...m[1].matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)].map(c => c[1]);
  };
  try {
    assert.deepEqual((await compareRow(['air-force', 'merchant-marine'])).map(text), ['—', '$895 in / $895 out'], 'fixture: the control column shows its figure');
    const four = await compareRow([...ACADEMIES]);
    assert.deepEqual(four.map(text), ['—', '—', '—', '—'], 'Compare, the four academies');
    for (const c of four) assert.doesNotMatch(c, wording, 'Compare: the card\'s wording is in a Compare cell');
  } finally { sb.S.compare = []; }
});

// About the data must not depend on the program index (Bianque, #493). It is static prose; the academies row is the one
// thing in it that reads the index (names and divisions), so with no index the row is simply left out and the rest of the
// page - the source table, the feedback email, the speed note - draws as it always has. boot() redraws the page when the
// index arrives. Rendering it must never fetch the index itself: that would turn a failed index into the whole page replaced
// by "Couldn't load the data", and a slow one into a blank page and a second request.
test('9. GUARD (passes on main too): with the index request failing, About the data still renders its whole source table, without the academies row, and asks for no index of its own', async () => {
  const healthy = await faqRows();
  assert.ok(healthy.length >= 8, 'fixture: the healthy source table');
  for (const how of ['http500', 'abort']) {
    const pg = loadPage({ index: how });
    await settle(); // boot() asked for the index and was refused: it has drawn its try-again card, S.index stays empty
    assert.ok(!pg.S.index, `fixture (${how}): the index did not load`);
    const asked = indexRequests(pg);
    assert.equal(asked, 1, `fixture (${how}): boot() asked for the index once`);
    const rows = await within(faqRows(pg), 2000, `About the data with the index failing (${how})`);
    const app = pg.document.querySelector('#app').innerHTML;
    assert.doesNotMatch(app, /Couldn’t load the data|load-failed/, `${how}: the FAQ was replaced by the try-again card`);
    assert.equal(indexRequests(pg), asked, `${how}: rendering About the data asked for the index itself`);
    assert.equal(rows.filter(isAcademyRow).length, 0, `${how}: an academies row with no index to name them from`);
    assert.deepEqual(rows, healthy.filter(r => !isAcademyRow(r)), `${how}: every other source row is there, unchanged`);
    assert.ok(app.includes('nextonetwolabs@gmail.com'), `${how}: the feedback email is hidden`);
    assert.ok(app.includes('<h3>Speed measurements</h3>'), `${how}: the speed notice is hidden`);
  }
});

test('10. GUARD (passes on main too): with the index still loading, About the data draws at once and asks for no second index', async () => {
  const pg = loadPage({ index: 'hold' });
  await settle();
  assert.equal(indexRequests(pg), 1, 'fixture: boot() has asked for the index and is waiting');
  const rows = await within(faqRows(pg), 1000, 'About the data while the index is still loading');
  assert.equal(indexRequests(pg), 1, 'rendering About the data asked for a second index');
  assert.equal(rows.filter(isAcademyRow).length, 0, 'an academies row before the index arrived');
  assert.ok(rows.length >= 7, 'the rest of the source table is there');
});

test('11. when the index arrives, boot() redraws About the data and the academies row appears', async () => {
  const pg = loadPage({ index: 'hold' });
  await settle();
  pg.location.hash = '#/faq';
  const early = await within(faqRows(pg), 1000, 'About the data while the index is still loading'); // what a hashchange to #/faq draws meanwhile
  assert.equal(early.filter(isAcademyRow).length, 0);
  pg.__test.release();
  await settle(); // boot() now has the index and routes #/faq
  const rows = tableRowsOf(pg.document.querySelector('#app').innerHTML);
  assert.equal(rows.filter(isAcademyRow).length, 1, 'no academies row after the index arrived');
  assert.equal(rows.length, early.length + 1);
});

test('12. the prose agrees in number: one academy in the data "charges ... its program card says"; none leaves the row out', async () => {
  const all = sb.S.index.programs;
  const keep = slugs => all.filter(p => !ACADEMIES.includes(p.slug) || slugs.includes(p.slug));
  const supplies = async () => (await faqRows()).filter(isAcademyRow).map(r => text(r[1]));
  try {
    sb.S.index.programs = keep(['army']);
    assert.deepEqual(await supplies(), [`That ${academyName(bySlug['army'])} charges no tuition: its program card says “No tuition (service academy)” where College Scorecard has no tuition figure`]);
    sb.S.index.programs = keep(['army', 'navy']);
    assert.deepEqual(await supplies(), [`That ${academyName(bySlug['army'])} and ${academyName(bySlug['navy'])} charge no tuition: their program cards say “No tuition (service academy)” where College Scorecard has no tuition figure`]);
    sb.S.index.programs = keep([]);
    assert.deepEqual(await supplies(), [], 'a row with no academy to name');
    assert.ok((await faqRows()).length >= 7, 'the rest of the table is there');
  } finally { sb.S.index.programs = all; }
});
