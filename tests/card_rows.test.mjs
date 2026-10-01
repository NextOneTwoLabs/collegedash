// Issue #426: program cards in one row of the grid had bands, meta lines and stats at different heights (a long name,
// a title badge beside the name, a long conference). (a) Each card is a subgrid of five row tracks - band, stripe,
// meta, detail (facts + Recommended reasons in ONE wrapper), foot - each part placed on its own track, inside
// @supports (grid-template-rows: subgrid) so older browsers keep the flex card. (c) The title badge sits on its own
// line under the name, not beside it.
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

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.CARD_ROWS_TEST_HTML || path.join(PUBLIC, 'index.html');
const PAGE = fs.readFileSync(HTML, 'utf8');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const CANNOT = 'the card-rows test cannot read';

// ---------- (2) the CSS ----------
function parseCss(text) {
  const src = text.replace(/\/\*[\s\S]*?\*\//g, '');
  const out = [];
  const walk = (chunk, at) => {
    let i = 0;
    while (i < chunk.length) {
      const open = chunk.indexOf('{', i);
      if (open < 0) break;
      let depth = 1, j = open + 1;
      while (j < chunk.length && depth) { if (chunk[j] === '{') depth++; else if (chunk[j] === '}') depth--; j++; }
      const prelude = chunk.slice(i, open).trim(), body = chunk.slice(open + 1, j - 1);
      if (prelude.startsWith('@')) walk(body, [...at, prelude.replace(/\s+/g, ' ')]);
      else out.push({ at, selectors: prelude.split(',').map(s => s.replace(/\s+/g, ' ').trim()).filter(Boolean), body });
      i = j;
    }
  };
  walk(src, []);
  return out;
}
const decls = body => body.split(';').map(d => d.trim()).filter(Boolean).map(d => {
  const i = d.indexOf(':');
  return { prop: d.slice(0, i).trim().toLowerCase(), value: d.slice(i + 1).trim() };
});
// What can move a card part between rows or change how a part lays out its own children.
const LAYOUT = /^(display|grid-row|grid-row-start|grid-row-end|grid-area|grid-template-rows|grid-template|grid|order|position|float|flex-direction|align-items|row-gap|gap)$/;
// A selector "targets a card part" when its LAST compound carries one of the card's own classes, or a generic part
// class (.body .meta .foot) under .pcard, or no class at all (a tag, `*`, a pseudo-class) under .pcard - so
// `.band .nick` (inside the band) is not a part, but `.pcard > *:last-child` is.
const OWN = /\.(pcard|band|stripe|card-detail|titles|facts)(?![\w-])/, GENERIC = /\.(body|meta|foot)(?![\w-])/;
const PART = {
  test(sel) {
    const parts = sel.split(/\s*[>+~]\s*|\s+/).filter(Boolean), last = parts.pop(), under = /\.pcard(?![\w-])/.test(parts.join(' '));
    return OWN.test(last) || (under && GENERIC.test(last)) || (under && !/\./.test(last.replace(/:[\w-]+(\([^)]*\))?/g, '')) && !/\./.test(last));
  },
};
const SUBGRID_AT = '@supports (grid-template-rows: subgrid)';
// The forms read, and where: [at-rule or '', selector] -> the layout declarations expected there (exactly).
const EXPECTED = {
  [`|.pcard`]: { display: 'flex' },  // the fallback card: a flex column, as before
  [`|.band`]: { display: 'flex', 'flex-direction': 'column', 'align-items': 'flex-start', gap: '6px' },
  [`|.facts`]: { display: 'grid', gap: '12px 16px' },
  [`|.pcard .foot`]: { display: 'flex', 'align-items': 'center', gap: '8px' },
  [`${SUBGRID_AT}|.grid.cards > .pcard`]: { display: 'grid', 'grid-row': 'span 5', 'grid-template-rows': 'subgrid', 'row-gap': '0' },
  [`${SUBGRID_AT}|.grid.cards > .pcard > .band`]: { 'grid-row': '1' },
  [`${SUBGRID_AT}|.grid.cards > .pcard > .stripe`]: { 'grid-row': '2' },
  [`${SUBGRID_AT}|.grid.cards > .pcard > .body`]: { 'grid-row': '3 / span 2', display: 'grid', 'grid-template-rows': 'subgrid', 'row-gap': '0' },
  [`${SUBGRID_AT}|.grid.cards > .pcard > .body > .meta`]: { 'grid-row': '1' },
  [`${SUBGRID_AT}|.grid.cards > .pcard > .body > .card-detail`]: { 'grid-row': '2' },
  [`${SUBGRID_AT}|.grid.cards > .pcard > .foot`]: { 'grid-row': '5' },
};
// Every layout declaration on a card part, keyed as in EXPECTED; fails loudly on anything it does not read.
function cardLayout(rules) {
  const got = {};
  for (const r of rules) {
    const ds = decls(r.body).filter(d => LAYOUT.test(d.prop));
    if (!ds.length) continue;
    for (const sel of r.selectors) {
      if (!PART.test(sel)) continue;
      const key = `${r.at.join(' ')}|${sel}`;
      if (!(key in EXPECTED)) assert.fail(`${CANNOT} "${key}", which sets ${ds.map(d => d.prop).join('/')} on a card part`);
      for (const d of ds) {
        if (/!\s*important/i.test(d.value)) assert.fail(`${CANNOT} !important in "${key} { ${d.prop}: ${d.value} }"`);
        (got[key] = got[key] || {})[d.prop] = d.value;
      }
    }
  }
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
    ['the band back to a row', '.pcard .band { flex-direction: row; }'],
  ]) assert.throws(run(extra), new RegExp(CANNOT), `${name}: the check did not fail`);
});

test('inside @supports subgrid: the card spans five tracks and every part names its own', () => {
  const got = cardLayout(parseCss(CSS));
  for (const [key, want] of Object.entries(EXPECTED)) {
    for (const [prop, value] of Object.entries(want)) assert.equal(got[key]?.[prop], value, `${key} { ${prop} }`);
  }
});

test('(c) the band is a column with the badge pill at its own width (align-items: flex-start)', () => {
  const got = cardLayout(parseCss(CSS));
  assert.equal(got['|.band']?.['flex-direction'], 'column', 'the band still lays the badge beside the name');
  assert.equal(got['|.band']?.['align-items'], 'flex-start', 'the badge pill would stretch to the band width');
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

test('every card: band, stripe, body, foot; the body: meta, then ONE detail wrapper holding facts and reasons', () => {
  const ps = sb.S.index.programs;
  const withFacts = ps.find(p => p.undergradEnrollment != null && p.nationalTitles > 0 && p.division !== 'D1');
  const noFacts = ps.find(p => p.undergradEnrollment == null && p.tuitionInState == null && p.tuitionOutOfState == null && p.academicRank == null);
  assert.ok(withFacts && noFacts, 'fixture: need a card with facts and a badge, and one without facts');
  for (const [p, why, label] of [[withFacts, undefined, 'facts + badge'], [withFacts, WHY, 'facts + reasons'], [noFacts, undefined, 'no facts'], [noFacts, WHY, 'reasons only']]) {
    const html = sb.cardHtml(p, why);
    assert.deepEqual(childrenOf(html, 'card pcard').map(c => c.split('.')[1].split(' ')[0]), ['band', 'stripe', 'body', 'foot'], `${label}: card parts`);
    assert.deepEqual(childrenOf(html, 'body').map(c => c.split('.')[1]), ['meta', 'card-detail'], `${label}: the body has meta and one detail wrapper`);
    const detail = childrenOf(html, 'card-detail').map(c => c.split('.')[1]);
    assert.deepEqual(detail, [...(p === withFacts ? ['facts'] : []), ...(why ? ['recs-why'] : [])], `${label}: what the detail wrapper holds`);
  }
});

test('(c) the badge is the band\'s own child after the name, never inside the name\'s heading', () => {
  const p = sb.S.index.programs.find(x => x.nationalTitles > 0 && x.division === 'D3');
  const html = sb.cardHtml(p);
  const band = childrenOf(html, 'band');
  assert.deepEqual(band.map(c => c.split('.')[0] + (c.split('.')[1] ? '.' + c.split('.')[1] : '')), ['h3', 'span.titles'], 'band children');
  assert.match(html, /<span class="titles">\d+ NCAA D3 titles?<\/span>/, 'the badge text (its accessible name) is unchanged');
});

test('constraints: D1/D2/D3 on every card, and the name readers see is shortName || name', () => {
  for (const d of ['D1', 'D2', 'D3']) {
    const p = sb.S.index.programs.find(x => x.division === d && x.shortName && x.shortName !== x.name);
    const html = sb.cardHtml(p);
    assert.ok(html.includes(`<h3>${p.shortName.replace(/&/g, '&amp;').replace(/'/g, '&#39;')}<span class="nick">`), `${d}: the card is not titled with shortName`);
    assert.match(childrenOf(html, 'meta').length >= 0 && html.split('class="meta">')[1].slice(0, 400), new RegExp(`\\b${d}\\b`), `${d}: the meta line lost its division`);
  }
});

test('Need verification rows are list items, not cards (untouched)', () => {
  const fn = /function recsNvHtml\(res\) \{([\s\S]*?)\n\}/.exec(PAGE)?.[1] || '';
  assert.ok(fn.includes('<li class="recs-nv-row">'), 'the Need verification list changed shape');
  assert.ok(!/cardHtml\(|pcard/.test(fn), 'Need verification rows now draw cards');
});
