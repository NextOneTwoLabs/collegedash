// Issue #426: program cards in one row of the grid had bands, meta lines and stats at different heights (a long name,
// a title badge beside the name, a long conference). (a) Each card is a subgrid of six row tracks - since #492:
// band (name, nickname, badge on its right), meta, undergrads, tuition, detail (empty, or Recommended's reasons, in one
// wrapper), foot - each part placed on its own track, inside @supports (grid-template-rows: subgrid) so older browsers
// keep the flex card. (c) Since #492 the title badge sits on the band's right, on the name's row (it was under the name),
// and the name is cut to one line with an ellipsis (it used to wrap; #426 said names never truncate).
//
//     node --test tests/card_rows.test.mjs
//
// Node has no layout engine. This pins (1) the card's structure, rendered by the page's own cardHtml in a vm, and
// (2) the CSS that lays it out, read by a small cascade check that understands exactly the forms below and FAILS
// LOUDLY on any other rule that could move or re-lay-out a card part (the #413/#421 lesson): a selector form it does
// not expect, !important, a subgrid outside @supports, any other @supports or @media. The equal heights themselves
// were measured in a browser on local serve.py, both themes, 1280/1024/820/375 px (PR body).
//
// CARD_ROWS_TEST_HTML (optional) points at another copy of index.html, so the page from before this change can be run
// through these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { parseCss, decls, exactLayout } from './lib/css_cascade.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.CARD_ROWS_TEST_HTML || path.join(PUBLIC, 'index.html');
const PAGE = fs.readFileSync(HTML, 'utf8');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const CANNOT = 'the card-rows test cannot read';

// ---------- (2) the CSS ----------
// A selector "targets a card part" when its LAST compound carries one of the card's own classes, or a generic part
// class (.body .meta .foot) under .pcard, or no class at all (a tag, `*`, a pseudo-class) under .pcard - so
// `.band .nick` (inside the band) is not a part, but `.pcard > *:last-child` and `.pcard .band h3` are.
const OWN = /\.(pcard|band|stripe|card-detail|card-ug|card-tuition|card-fact|titles|facts)(?![\w-])/, GENERIC = /\.(body|meta|foot)(?![\w-])/;
const isPart = sel => {
  const parts = sel.split(/\s*[>+~]\s*|\s+/).filter(Boolean), last = parts.pop(), under = /\.pcard(?![\w-])/.test(parts.join(' '));
  return OWN.test(last) || (under && GENERIC.test(last)) || (under && !/\./.test(last.replace(/:[\w-]+(\([^)]*\))?/g, '')) && !/\./.test(last));
};
const SUBGRID_AT = '@supports (grid-template-rows: subgrid)';
// Every rule that sets a layout property (tests/lib/css_cascade.mjs LAYOUT) on a card part, with EXACTLY the layout
// properties it sets (#430: a property added to a known selector - `.pcard .foot { order: -1 }` - must fail too).
const EXPECTED = {
  [`|.pcard`]: { display: 'flex', 'flex-direction': 'column', padding: '0', overflow: 'hidden' },  // the fallback card
  [`|.band`]: { display: 'flex', 'align-items': 'center', gap: '10px', height: '4.75rem', padding: '0 16px' },
  [`|.band .titles`]: { flex: 'none', 'white-space': 'nowrap', 'font-size': '11px', padding: '2px 8px' },
  [`|.pcard .band h3`]: { 'font-size': '17px', 'line-height': '1.2' },
  [`|.pcard .body`]: { flex: '1', padding: '0 16px 12px' },
  [`|.pcard .meta`]: { 'font-size': '12px', 'line-height': '1.4', height: '2.8em', margin: '8px 0 6px', overflow: 'hidden', display: '-webkit-box' },
  [`|.pcard .card-fact`]: { 'font-size': '13px', 'line-height': '1.4' },
  [`|.pcard .card-ug`]: { display: 'flex', gap: '6px', height: '1.4em', 'margin-bottom': '4px' },
  [`|.pcard .card-tuition`]: { display: 'flex', gap: '6px', height: '2.8em' },
  [`|.pcard .foot`]: { display: 'flex', 'align-items': 'center', 'justify-content': 'space-between', gap: '8px', padding: '6px 8px 6px 16px', 'font-size': '12px' },
  [`${SUBGRID_AT}|.grid.cards > .pcard`]: { display: 'grid', 'grid-row': 'span 6', 'grid-template-columns': 'minmax(0, 1fr)', 'grid-template-rows': 'subgrid', 'row-gap': '0' },
  [`${SUBGRID_AT}|.grid.cards > .pcard > .band`]: { 'grid-row': '1' },
  [`${SUBGRID_AT}|.grid.cards > .pcard > .body`]: { 'grid-row': '2 / span 4', display: 'grid', 'grid-template-columns': 'minmax(0, 1fr)', 'grid-template-rows': 'subgrid', 'row-gap': '0' },
  [`${SUBGRID_AT}|.grid.cards > .pcard > .body > .meta`]: { 'grid-row': '1' },
  [`${SUBGRID_AT}|.grid.cards > .pcard > .body > .card-ug`]: { 'grid-row': '2' },
  [`${SUBGRID_AT}|.grid.cards > .pcard > .body > .card-tuition`]: { 'grid-row': '3' },
  [`${SUBGRID_AT}|.grid.cards > .pcard > .body > .card-detail`]: { 'grid-row': '4' },
  [`${SUBGRID_AT}|.grid.cards > .pcard > .foot`]: { 'grid-row': '6' },
};
// The card parts' layout, exactly as EXPECTED; fails loudly on anything else, and on a subgrid outside @supports.
function cardLayout(rules) {
  const got = exactLayout(rules, { watched: isPart, expected: EXPECTED, cannot: CANNOT });
  for (const r of rules) for (const d of decls(r.body))
    if (/subgrid/.test(d.value) && r.at.join(' ') !== SUBGRID_AT) assert.fail(`${CANNOT} subgrid outside ${SUBGRID_AT}: "${r.selectors.join(', ')}"`);
  return got;
}
const CSS = [...PAGE.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n');

test('the cascade check fails loudly on every form it cannot read', () => {
  const run = extra => () => cardLayout(parseCss(`${CSS}\n${extra}`));
  assert.doesNotThrow(run(''), 'the page\'s own CSS is not readable');
  for (const [name, extra] of [
    ['a part moved outside @supports', '.pcard > .foot { grid-row: 4; }'],
    ['a part moved inside @media', `@media (max-width: 600px) { .grid.cards > .pcard > .foot { grid-row: 4; } }`],
    ['another @supports', '@supports (display: grid) { .grid.cards > .pcard { display: grid; } }'],
    ['!important on a track', `${SUBGRID_AT} { .grid.cards > .pcard > .foot { grid-row: 5 !important; } }`],
    ['a descendant form', '.grid.cards .pcard .band { order: 2; }'],
    ['a universal child', `${SUBGRID_AT} { .pcard > *:last-child { grid-row: 2; } }`],
    ['the badge taken out of flow', '.band .titles { position: absolute; }'],
    ['subgrid outside @supports', '.grid.cards > .pcard { grid-template-rows: subgrid; }'],
    ['the band back to a column', '.pcard .band { flex-direction: column; }'],
    // #430: a layout property added to, or changed on, a selector the check already knows (Bianque's three first)
    ['order on the foot (Bianque)', '.pcard .foot { order: -1; }'],
    ['order on the band (Bianque)', '.band { order: 1; }'],
    ['position on the card (Bianque)', '.pcard { position: absolute; }'],
    ['a changed value on a known selector', '.pcard .meta { margin-bottom: 40px; }'],
    ['the tuition row shortened to one line (#492)', '.pcard .card-tuition { height: 1.4em; }'],
    ['the undergrads row allowed to grow (#492)', '.pcard .card-ug { height: auto; }'],
    ['the band allowed to grow (#492)', '.band { height: auto; }'],
    ['a transform on a subgrid part', `${SUBGRID_AT} { .grid.cards > .pcard > .body > .card-ug { transform: translateY(-20px); } }`],
    ['the fact row moved', `${SUBGRID_AT} { .grid.cards > .pcard > .body > .card-detail { grid-row: 2; } }`],
  ]) assert.throws(run(extra), new RegExp(CANNOT), `${name}: the check did not fail`);
});

test('inside @supports subgrid: the card spans six tracks and every part names its own (exactly)', () => {
  const got = cardLayout(parseCss(CSS));
  assert.deepEqual(Object.keys(got).sort(), Object.keys(EXPECTED).sort());
  for (const [key, want] of Object.entries(EXPECTED)) assert.deepEqual({ ...got[key] }, want, key);
});

test('(c) #492: the badge sits on the band\'s right, on the name\'s row, at its own width; the band is a fixed-height row', () => {
  const got = cardLayout(parseCss(CSS));
  assert.equal(got['|.band']?.display, 'flex', 'the band is no longer a row');
  assert.equal(got['|.band']?.height, '4.75rem', 'the band is not a fixed height');
  assert.equal(got['|.band .titles']?.flex, 'none', 'the badge pill would shrink or stretch');
  assert.equal(got['|.band .titles']?.['white-space'], 'nowrap');
});

// ---------- (1) the card, rendered by the page ----------
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
  const src = lines.slice(a + 1, b).join('\n') + '\n;Object.assign(globalThis, { S, loadIndex, cardHtml, displayName });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}
const sb = loadPage();

// A tiny tag-tree reader for one card's markup: the children (tag + class) of the element whose class starts `cls`.
function childrenOf(html, cls) {
  const start = html.search(new RegExp(`<(\\w+) class="${cls}[" ]`));
  assert.ok(start >= 0, `no element with class ${cls}`);
  const out = [];
  let depth = 0, i = html.indexOf('>', start) + 1;
  const re = /<(\/?)(\w+)([^>]*)>/g;
  re.lastIndex = i;
  for (let m; (m = re.exec(html));) {
    const [, close, tag, attrs] = m;
    if (/^(br|img|input|hr|meta|link)$/i.test(tag) || attrs.endsWith('/')) { if (depth === 0) out.push(`${tag}.${/class="([^"]*)"/.exec(attrs)?.[1] || ''}`); continue; }
    if (close) { if (depth === 0) return out; depth--; continue; }
    if (depth === 0) out.push(`${tag}.${/class="([^"]*)"/.exec(attrs)?.[1] || ''}`);
    depth++;
  }
  return out;
}
const WHY = '<ul class="recs-why" aria-label="Why"><li>a reason</li></ul>';

test('setup: the index loads', async () => {
  await sb.loadIndex();
  assert.ok(sb.S.index.programs.length > 900);
});

test('every card: band, body, foot; the body: meta, undergrads, tuition, then ONE detail wrapper (empty, or the reasons)', () => {
  const ps = sb.S.index.programs;
  const withFact = ps.find(p => p.undergradEnrollment != null && p.nationalTitles > 0 && p.division !== 'D1');
  const noFact = ps.find(p => p.undergradEnrollment == null);
  assert.ok(withFact && noFact, 'fixture: need a card with a fact and a badge, and one without');
  for (const [p, why, label] of [[withFact, undefined, 'bracket + badge'], [withFact, WHY, 'reasons'], [noFact, undefined, 'Not reported'], [noFact, WHY, 'reasons only']]) {
    const html = sb.cardHtml(p, why);
    assert.deepEqual(childrenOf(html, 'card pcard').map(c => c.split('.')[1].split(' ')[0]), ['band', 'body', 'foot'], `${label}: card parts`);
    assert.deepEqual(childrenOf(html, 'body').map(c => c.split('.').slice(1).join('.')), ['meta', 'card-fact card-ug', 'card-fact card-tuition', 'card-detail'],
      `${label}: the body has meta, the two bracket rows and one detail wrapper`);
    const detail = childrenOf(html, 'card-detail').map(c => c.split('.')[1]);
    assert.deepEqual(detail, why ? ['recs-why'] : [], `${label}: the detail wrapper is empty, or holds the reasons`);
  }
});

test('(c) #492: the badge is the band\'s own child after the name, on its right, never inside the name\'s heading', () => {
  const p = sb.S.index.programs.find(x => x.nationalTitles > 0 && x.division === 'D3');
  const html = sb.cardHtml(p);
  const band = childrenOf(html, 'band');
  assert.deepEqual(band, ['h3.', 'span.titles'], 'band children: the name, then the badge (no crest)');
  assert.match(html, /<span class="titles">\d+ NCAA D3 titles?<\/span>/, 'the badge text (its accessible name) is unchanged');
});

test('constraints: D1/D2/D3 on every card, and the name readers see is shortName || name', () => {
  for (const d of ['D1', 'D2', 'D3']) {
    const p = sb.S.index.programs.find(x => x.division === d && x.shortName && x.shortName !== x.name);
    const html = sb.cardHtml(p);
    assert.ok(html.includes(`<span class="nm">${p.shortName.replace(/&/g, '&amp;').replace(/'/g, '&#39;')}</span>`), `${d}: the card is not titled with shortName`);
    assert.match(childrenOf(html, 'meta').length >= 0 && html.split('class="meta">')[1].slice(0, 400), new RegExp(`\\b${d}\\b`), `${d}: the meta line lost its division`);
  }
});

test('Need verification rows are list items, not cards (untouched)', () => {
  const fn = /function recsNvHtml\(res\) \{([\s\S]*?)\n\}/.exec(PAGE)?.[1] || '';
  assert.ok(fn.includes('<li class="recs-nv-row">'), 'the Need verification list changed shape');
  assert.ok(!/cardHtml\(|pcard/.test(fn), 'Need verification rows now draw cards');
});
