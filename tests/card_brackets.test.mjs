// #492: the program card is a school-colour title band (name and nickname on it, the titles badge on its right), the
// division · conference · location line, an undergrads BRACKET and tuition BRACKET(S) - and no rankings, no match
// records, no commits. Sorting and the class highlight only reorder; they never add a row to the card.
//
//     node --test tests/card_brackets.test.mjs
//
// Offline: the page's own inline script runs in a vm over the committed index. Expected values are computed here
// from the index rows by independent code (the data refreshes daily). Every test below fails on origin/main except the one marked GUARD (8).
//
// CARD_BRACKETS_TEST_HTML (optional) points at another copy of index.html, to run these checks against it.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { parseCss, decls } from './lib/css_cascade.mjs';
const CDRecs = createRequire(import.meta.url)('../public/recs.js');

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.CARD_BRACKETS_TEST_HTML || path.join(PUBLIC, 'index.html');
const PAGE = fs.readFileSync(HTML, 'utf8');
const CSS = [...PAGE.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n');

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
  const names = ['bracketIndex', 'UNDERGRAD_EDGES', 'UNDERGRAD_SIZES', 'TUITION_EDGES', 'SORT_SPECS', 'tableHtml', 'displayName'];
  const src = lines.slice(a + 1, b).join('\n')
    + `\n;Object.assign(globalThis, { S, loadIndex, cardHtml, ${names.map(n => `${n}: typeof ${n} === 'undefined' ? undefined : ${n}`).join(', ')} });\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}
const sb = loadPage();
await sb.loadIndex();
const P = sb.S.index.programs;
const disp = p => p.shortName || p.name;
const esc = t => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const text = h => String(h ?? '').replace(/<span class="sr-only">[\s\S]*?<\/span>/g, '').replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&#39;/g, "'").trim();
const srText = h => [...String(h ?? '').matchAll(/<span class="sr-only">([\s\S]*?)<\/span>/g)].map(m => m[1]).join('');
const card = (p, why) => sb.cardHtml(p, why);
// The inner HTML of every <span class="CLS"> in html (balanced, so nested spans stay inside their parent).
function spansOf(html, cls) {
  const out = [], open = `<span class="${cls}">`;
  for (let at = html.indexOf(open); at >= 0; at = html.indexOf(open, at + 1)) {
    let depth = 1, i = at + open.length; const re = /<(\/?)span\b[^>]*>/g; re.lastIndex = i;
    for (let m; (m = re.exec(html));) { depth += m[1] ? -1 : 1; if (!depth) { out.push(html.slice(i, m.index)); break; } }
  }
  return out;
}
const rowOf = (html, cls) => (html.match(new RegExp(`<div class="card-fact ${cls}">([\\s\\S]*?)</div>\\s*(?=<div class="card-fact|<div class="card-detail)`)) || [, null])[1];

// Independent copies of the owner's tables.
const UG = [['Very small', 'under 2K', 'under 2,000'], ['Small', '2K–5K', '2,000 to 4,999'], ['Medium', '5K–15K', '5,000 to 14,999'],
  ['Large', '15K–30K', '15,000 to 29,999'], ['Very large', '30K+', '30,000 or more']];
const TU = [['Under $15K', 'under $15,000 a year'], ['$15K–30K', '$15,000 to $29,999 a year'], ['$30K–45K', '$30,000 to $44,999 a year'],
  ['$45K–60K', '$45,000 to $59,999 a year'], ['$60K+', '$60,000 or more a year']];
const ugIdx = v => (v < 2000 ? 0 : v < 5000 ? 1 : v < 15000 ? 2 : v < 30000 ? 3 : 4);
const tuIdx = v => (v < 15000 ? 0 : v < 30000 ? 1 : v < 45000 ? 2 : v < 60000 ? 3 : 4);

test('1. bracket helpers: lower-inclusive edges, and null / NaN / negative are no bracket', () => {
  assert.equal(typeof sb.bracketIndex, 'function', 'there is no bracketIndex');
  assert.deepEqual([...sb.UNDERGRAD_EDGES], [2000, 5000, 15000, 30000]);
  assert.deepEqual([...sb.TUITION_EDGES], [15000, 30000, 45000, 60000]);
  const ug = v => sb.bracketIndex(v, sb.UNDERGRAD_EDGES), tu = v => sb.bracketIndex(v, sb.TUITION_EDGES);
  for (const [v, i] of [[0, 0], [1999, 0], [2000, 1], [4999, 1], [5000, 2], [14999, 2], [15000, 3], [29999, 3], [30000, 4], [200000, 4]])
    assert.equal(ug(v), i, `undergrads ${v}`);
  for (const [v, i] of [[0, 0], [14999, 0], [15000, 1], [29999, 1], [30000, 2], [44999, 2], [45000, 3], [59999, 3], [60000, 4]])
    assert.equal(tu(v), i, `tuition ${v}`);
  for (const bad of [null, undefined, NaN, -1, Infinity, '5000']) { assert.equal(ug(bad), null, `undergrads ${String(bad)}`); assert.equal(tu(bad), null, `tuition ${String(bad)}`); }
});

test('2. every card shows its undergrads as a bracket (size word + range, exact wording for screen readers), or "Not reported"', () => {
  const counts = [0, 0, 0, 0, 0]; let missing = 0;
  for (const p of P) {
    const html = card(p), row = rowOf(html, 'card-ug');
    assert.ok(row, `${p.slug}: no undergrads row`);
    assert.ok(text(row).startsWith('Undergrads '), `${p.slug}: ${text(row)}`);
    if (p.undergradEnrollment == null) {
      missing++;
      assert.equal(text(row), 'Undergrads Not reported', p.slug);
      continue;
    }
    const [size, range, sr] = UG[ugIdx(p.undergradEnrollment)];
    counts[ugIdx(p.undergradEnrollment)]++;
    assert.equal(text(row), `Undergrads ${size} · ${range}`, p.slug);
    assert.ok(srText(row).includes(sr), `${p.slug}: screen-reader wording "${srText(row)}" lacks "${sr}"`);
    assert.ok(!text(row).includes(Number(p.undergradEnrollment).toLocaleString('en-US')), `${p.slug}: the exact count is on the card`);
    assert.ok(/<span aria-hidden="true">[^<]*K[^<]*<\/span>/.test(row), `${p.slug}: the K shorthand is not aria-hidden`);
  }
  assert.ok(missing > 0 && counts.every(n => n > 0), 'fixture: every bracket and the missing case should occur in the index');
});

test('3. tuition: one label; two bracket lines for publics (in-state, out-of-state), one for the rest; 30,000 is $30K-45K; gaps are "Not reported"', () => {
  let publics = 0, others = 0;
  for (const p of P) {
    const row = rowOf(card(p), 'card-tuition');
    assert.ok(row, `${p.slug}: no tuition row`);
    assert.equal((row.match(/class="fl"/g) || []).length, 1, `${p.slug}: one Tuition label`);
    assert.ok(text(row).startsWith('Tuition'), p.slug);
    const lines = spansOf(row, 'tl');
    const inS = p.tuitionInState, out = p.tuitionOutOfState;
    if (p.ownership === 'Public') {
      publics++;
      if (inS == null && out == null) { assert.deepEqual(lines.map(text), ['Not reported'], `${p.slug}: both missing`); continue; }
      assert.deepEqual(lines.map(text), [inS == null ? 'Not reported in-state' : `${TU[tuIdx(inS)][0]} in-state`, out == null ? 'Not reported out-of-state' : `${TU[tuIdx(out)][0]} out-of-state`], p.slug);
      if (inS != null) assert.ok(srText(lines[0]).includes(`${TU[tuIdx(inS)][1]}, in-state`), `${p.slug}: ${srText(lines[0])}`);
      if (out != null) assert.ok(srText(lines[1]).includes(`${TU[tuIdx(out)][1]}, out-of-state`), `${p.slug}: ${srText(lines[1])}`);
    } else {
      others++;
      const v = out ?? inS;
      assert.deepEqual(lines.map(text), [v == null ? 'Not reported' : TU[tuIdx(v)][0]], p.slug);
    }
    assert.ok(!/\$\d{1,3},\d{3}/.test(text(row)), `${p.slug}: an exact figure is on the card`);
  }
  assert.ok(publics > 400 && others > 500, 'fixture: publics and privates');
  // exactly on an edge, through the page's own card
  const pub = P.find(p => p.ownership === 'Public' && p.tuitionInState != null && p.tuitionOutOfState != null);
  const edge = card({ ...pub, tuitionInState: 30000, tuitionOutOfState: 45000 });
  assert.deepEqual(spansOf(rowOf(edge, 'card-tuition'), 'tl').map(text), ['$30K–45K in-state', '$45K–60K out-of-state']);
});

test('4. sorting and the class highlight only reorder: the card is byte-identical under every sort and class, with no RPI, rank, record or commits', () => {
  const f = sb.S.filters, was = { sort: f.sort, classYear: f.classYear };
  const keys = [...new Set([...Object.keys(sb.SORT_SPECS), 'name', 'admit', 'academicRank', 'tuition', 'undergrads', 'commits', 'titles', 'cups', 'region', 'type'])];
  assert.ok(keys.length > 8, 'fixture: the sort keys');
  try {
    for (const p of P) {
      f.sort = 'name'; f.classYear = [];
      const base = card(p);
      for (const key of keys) for (const classes of [[], ['2027']]) {
        f.sort = key; f.classYear = classes;
        assert.equal(card(p), base, `${p.slug}: sort ${key} / classes ${classes.join(',') || 'none'} changed the card`);
      }
      const t = text(base);
      assert.ok(!/RPI/.test(base), `${p.slug}: RPI on the card`);
      assert.ok(!/#\d/.test(t), `${p.slug}: a rank on the card: ${t}`);
      assert.ok(!/US rank|Admission|Commits|commits/.test(t), `${p.slug}: ${t}`);
      assert.ok(!/\b\d+-\d+(-\d+)?\b/.test(t), `${p.slug}: a match record on the card: ${t}`);
      if (p.currentSeason?.record) assert.ok(!base.includes(p.currentSeason.record), `${p.slug}: the season record is on the card`);
      assert.ok(!base.includes('card-sum'), 'the season line is still on the card');
    }
  } finally { Object.assign(f, was); }
});

test('5. band: school colours as variables, grey (no style) when none; name, nickname, then the badge on the right; no crest', () => {
  for (const p of P) {
    const html = card(p);
    assert.ok(!/class="crest"|--crest/.test(html), `${p.slug}: the crest is still there`);
    const m = html.match(/<div class="band"(?: style="([^"]*)")?>/);
    assert.ok(m, `${p.slug}: no band`);
    const real = (p.colors || []).filter(c => /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.test(c));
    if (!real.length) assert.equal(m[1], undefined, `${p.slug}: a program with no colours must get the grey band (no style attribute)`);
    else {
      const prim = '#' + real[0].replace('#', ''), sec = '#' + (real[1] || real[0]).replace('#', '');
      assert.ok(m[1].startsWith(`--band:${prim};--band2:${sec};--band-ink:`), `${p.slug}: ${m[1]}`);
    }
    const nick = p.nickname || '';
    assert.ok(html.includes(`<h3 title="${esc(disp(p) + (nick ? ', ' + nick : ''))}">`), `${p.slug}: the heading's title is the display name${nick ? ' and nickname' : ''}`);
    assert.ok(html.includes(`<span class="nm">${esc(disp(p))}</span>`), `${p.slug}: .nm`);
    if (nick) assert.ok(html.includes(`</span><span class="sr-only">, </span><span class="nick">${esc(nick)}</span></h3>`), `${p.slug}: nickname after a screen-reader separator`);
    const band = html.slice(html.indexOf('<div class="band"'), html.indexOf('<div class="body">'));
    const iH = band.indexOf('</h3>'), iB = band.indexOf('<span class="titles">');
    if (p.nationalTitles > 0) assert.ok(iB > iH && iH > 0, `${p.slug}: the badge must come after the heading, on the band's right`);
    else assert.equal(iB, -1, `${p.slug}: a badge with no titles`);
  }
  assert.ok(P.some(p => !(p.colors || []).length) && P.some(p => (p.colors || []).length), 'fixture: both kinds');
});

// WCAG contrast, computed here.
const lum = hex => { let h = hex.replace('#', ''); if (h.length === 3) h = [...h].map(c => c + c).join('');
  const [r, g, b] = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) / 255).map(v => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
const cssRules = parseCss(CSS);
const declsOf = sel => { const o = {}; for (const r of cssRules) if (!r.at.length && r.selectors.includes(sel)) for (const d of decls(r.body)) o[d.prop] = d.value; return o; };

test('6. band ink: every program\'s band text reaches 4.5:1, and the CSS lets the name, nickname and badge inherit it', () => {
  let n = 0;
  for (const p of P) {
    const m = card(p).match(/<div class="band" style="--band:(#[0-9a-fA-F]+);--band2:[^;]+;--band-ink:(#[0-9a-fA-F]+)"/);
    if (!m) continue;
    n++;
    assert.ok(ratio(m[1], m[2]) >= 4.5, `${p.slug}: ${m[2]} on ${m[1]} is ${ratio(m[1], m[2]).toFixed(2)}:1`);
  }
  assert.ok(n > 900, `fixture: ${n} coloured bands`);
  assert.match(declsOf('.band').color || '', /^var\(--band-ink,/, '.band takes its ink from --band-ink');
  assert.match(declsOf('.band').background || '', /^var\(--band,/, '.band takes its colour from --band');
  for (const r of cssRules) for (const s of r.selectors) {
    if (!/(^|[ >])\.band\b/.test(s)) continue;
    if (s === '.band') continue;
    for (const d of decls(r.body)) {
      if (d.prop === 'color') assert.equal(d.value, 'inherit', `"${s}" sets a band text colour other than inherit`);
      assert.notEqual(d.prop, 'opacity', `"${s}" sets opacity on band text (it costs contrast)`);
    }
  }
});

test('7. CSS: the exact heights (lines x line-height), band 4.75rem, one-line ellipsis rules, aligned label column', () => {
  const sel = s => declsOf(s);
  assert.equal(sel('.band').height, '4.75rem');
  const meta = sel('.pcard .meta');
  assert.deepEqual([meta['font-size'], meta['line-height'], meta.height, meta.overflow], ['12px', '1.4', '2.8em', 'hidden']);
  assert.equal(meta['-webkit-line-clamp'], '2');
  const fact = sel('.pcard .card-fact');
  assert.deepEqual([fact['font-size'], fact['line-height']], ['13px', '1.4']);
  assert.equal(sel('.pcard .card-ug').height, '1.4em', 'undergrads is one line');
  assert.equal(sel('.pcard .card-tuition').height, '2.8em', 'tuition always reserves two lines');
  const tl = sel('.card-tuition .tl');
  assert.deepEqual([tl.display, tl.height, tl.overflow, tl['text-overflow'], tl['white-space']], ['block', '1.4em', 'hidden', 'ellipsis', 'nowrap']);
  const tv = sel('.card-tuition .tv');
  assert.deepEqual([tv.display, tv['flex-direction'], tv.gap, tv['min-width']], ['flex', 'column', '0', '0']);
  const ugv = sel('.card-ug .fv');
  assert.deepEqual([ugv.overflow, ugv['text-overflow'], ugv['white-space'], ugv['min-width']], ['hidden', 'ellipsis', 'nowrap', '0']);
  const fl = sel('.card-fact .fl');
  assert.deepEqual([fl.width, fl.flex], ['7.4em', 'none'], 'the label column scales with text zoom (7.4em = 96px at 13px)');
  const why = sel('.pcard .foot .why'), fw = sel('.pcard .foot .fw');
  assert.deepEqual([why.display, why['max-width'], why.overflow, why['text-overflow'], why['white-space']], ['block', '100%', 'hidden', 'ellipsis', 'nowrap'], 'the search tag is one line');
  assert.deepEqual([fw['min-width'], fw.overflow], ['0', 'hidden'], 'the foot\'s first span can shrink');
  for (const s of ['.band .nm', '.band .nick']) {
    const d = sel(s);
    assert.deepEqual([d['white-space'], d['text-overflow'], d.overflow], ['nowrap', 'ellipsis', 'hidden'], s);
  }
  const h3 = sel('.band h3');
  assert.deepEqual([h3['min-width'], h3.flex], ['0', '1 1 auto']);
  const titles = sel('.band .titles');
  assert.deepEqual([titles.flex, titles['white-space']], ['none', 'nowrap']);
  assert.ok(!cssRules.some(r => r.selectors.some(s => /\.(crest|card-sum)\b/.test(s))), 'crest / card-sum CSS is still there');
});

test('8. GUARD (passes on main too): Stats\' US rank (THE) cell is unchanged for every program (the rank moved off the card, the column stays)', () => {
  const rows = P.slice();
  const html = sb.tableHtml(rows, {});
  const want = p => `<span title="${esc(p.academicRank == null
    ? 'Times Higher Education, Best universities in the United States 2026 — this university is not among the 171 it ranks'
    : p.academicRankTied ? 'Times Higher Education, Best universities in the United States 2026 — this rank is shared with other universities'
      : 'Times Higher Education, Best universities in the United States 2026')}">${p.academicRank == null ? '—' : '#' + p.academicRank}</span>`;
  let seen = 0;
  for (const p of rows) { if (!html.includes(want(p))) assert.fail(`${p.slug}: the Stats rank cell changed`); seen++; }
  assert.equal(seen, rows.length);
});

test('9. Recommended: a size reason names the same bracket as the card (recs.js copy of the edges cannot drift), also in the Why column', () => {
  assert.equal(typeof CDRecs.sizeBracketText, 'function', 'recs.js has no sizeBracketText');
  for (const v of [0, 1999, 2000, 4999, 5000, 14999, 15000, 29999, 30000, 163164]) {
    const [size, range] = sb.UNDERGRAD_SIZES[sb.bracketIndex(v, sb.UNDERGRAD_EDGES)];
    assert.equal(CDRecs.sizeBracketText(v), `${size} (${range})`, `undergrads ${v}`);
    // valueText feeds reasonText: the card's reasons AND the Stats table's Why column
    assert.equal(CDRecs.reasonText({ category: 'size', value: 'ge15k', detail: { undergrad: v } }), `${size} (${range})`);
  }
  assert.equal(CDRecs.reasonText({ category: 'size', value: 'ge15k', detail: { undergrad: 40000 } }), 'Very large (30K+)');
});
