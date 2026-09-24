// The profile names its division (issue #278) and the RPI chart's y ticks fit the plotted range (issue #279).
//
//     node --test tests/profile_division_rank_axis.test.mjs
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM (as tests/header_links.test.mjs
// does); fetch serves public/ plus profiles generated here. Nothing leaves the process.
//
// What this proves:
//   - for a committed D1, D2 and D3 profile, the division code (as the sidebar's Division pills label it)
//     appears in the header subtitle, the breadcrumb and the "Program at a glance" line, and nowhere is it
//     the other division's code; the program card and the Compare table carry it too;
//   - the "RPI, recent seasons" chart, for a low-ranked series (Abilene Christian, #206-#296) and a top-10
//     series: every y tick lies inside the plotted area, every plotted dot lies inside it too, and no two
//     tick labels are closer than a label's height.
//
// PROFILE_DIVISION_HTML (optional) points at another copy of index.html, so a deliberately broken copy can be
// shown failing through these same checks.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const PAGE = process.env.PROFILE_DIVISION_HTML || path.join(PUBLIC, 'index.html');
const clone = (v) => JSON.parse(JSON.stringify(v));
const readJson = (rel) => JSON.parse(fs.readFileSync(path.join(PUBLIC, rel), 'utf8'));
const INDEX = readJson('data/programs/index.json');

function makeElement(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, contains: () => false,
  };
}
function loadPage(files = {}, stored = {}) {
  const els = new Map();
  const bySelector = (sel) => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map(Object.entries(stored));
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector, querySelectorAll: () => [],
      addEventListener() { }, createElement: makeElement },
    location: { hash: '', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
    innerWidth: 1400, addEventListener() { }, alert() { },
    fetch: async (url) => {
      const ok = (body, st = 200) => ({ ok: st < 400, status: st, async json() { return clone(body); } });
      let u = String(url);
      if (u.startsWith('/api/v1/')) {
        const sub = u.slice('/api/v1/'.length);
        if (sub === 'programs') u = 'data/programs/index.json';
        else if (sub.startsWith('programs/')) u = `data/programs/${sub.slice('programs/'.length)}.json`;
        else if (sub === 'status') u = 'archive/refresh-state.json';
        else u = `data/${sub}/index.json`;
      }
      if (files[u]) return ok(files[u]);
      if (!u.startsWith('data/') && !u.startsWith('archive/')) return ok({}, 404);
      const p = path.join(PUBLIC, u);
      return fs.existsSync(p) ? ok(JSON.parse(fs.readFileSync(p, 'utf8'))) : ok({}, 404);
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(PAGE, 'utf8').split(/\r?\n/);
  const a = lines.findIndex((l) => l.trim() === '<script>'), b = lines.findIndex((l) => l.trim() === '</script>');
  const names = ['S', 'renderProfile', 'renderCompare', 'loadIndex', 'cardHtml'];
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(names)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  const $ = (sel) => sandbox.document.querySelector(sel);
  return { sb: sandbox, app: () => $('#app').innerHTML, tab: () => $('#tab').innerHTML };
}
const text = (html) => html.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim();
const part = (html, re) => { const m = html.match(re); assert.ok(m, `not found: ${re}`); return text(m[1]); };

const FIXTURES = ['D1', 'D2', 'D3'].map((d) => [d, INDEX.programs.find((p) => p.division === d)]);

for (const [div, row] of FIXTURES) {
  test(`${div} (${row.slug}): division in the subtitle, breadcrumb and at-a-glance line`, async () => {
    const pg = loadPage(); await pg.sb.loadIndex();
    await pg.sb.renderProfile(row.slug, 'overview');
    const html = pg.app();
    const others = ['D1', 'D2', 'D3'].filter((d) => d !== div);
    const places = {
      subtitle: part(html, /<div class="content-subtitle">([\s\S]*?)<\/div>/),
      breadcrumb: part(html, /<div class="breadcrumb">([\s\S]*?)<\/div>/),
      glance: part(html, /<div class="glance-meta">([\s\S]*?)<\/div>/),
    };
    for (const [where, t] of Object.entries(places)) {
      const words = t.split(/[\s·›]+/);
      assert.ok(words.includes(div), `${where} lacks ${div}: "${t}"`);
      for (const o of others) assert.ok(!words.includes(o), `${where} names ${o}: "${t}"`);
    }
    // Order: the division reads before the conference, in all three places.
    for (const [where, t] of Object.entries(places)) assert.ok(t.indexOf(div) < t.indexOf(row.conference), `${where}: "${t}"`);
    assert.match(places.breadcrumb, new RegExp(`^All programs ?› ?${div} ?›`));
  });
}

test('program card and Compare show each fixture\'s division', async () => {
  const slugs = FIXTURES.map(([, r]) => r.slug);
  const pg = loadPage({}, { 'cd.compare': JSON.stringify(slugs) }); await pg.sb.loadIndex();
  for (const [div, row] of FIXTURES) {
    const meta = part(pg.sb.cardHtml(row), /<div class="meta">([\s\S]*?)<\/div>/);
    assert.ok(meta.startsWith(`${div} · `), `card meta: "${meta}"`);
  }
  pg.sb.S.compare = slugs;
  await pg.sb.renderCompare();
  const divRow = part(pg.app(), /<tr><th>Division<\/th>([\s\S]*?)<\/tr>/);
  for (const [div, row] of FIXTURES) assert.ok(divRow.includes(`${div} · ${row.conference}`), `compare Division row: "${divRow}"`);
});

// ---- #279: the RPI chart's y axis ----
const LABEL_H = 12; // the chart's tick labels are 11px text; closer than this, two labels overprint
function chartOf(tabHtml) {
  const m = tabHtml.match(/<h3>RPI, recent seasons<\/h3>[\s\S]*?(<svg viewBox="0 0 (\d+) (\d+)"[\s\S]*?<\/svg>)/);
  assert.ok(m, 'no RPI chart');
  const [, svg, , H] = m;
  const ticks = [...svg.matchAll(/<text x="[\d.]+" y="([\d.]+)" text-anchor="end">#(\d+)<\/text>/g)].map((t) => ({ y: +t[1] - 4, rank: +t[2] }));
  const dots = [...svg.matchAll(/<circle class="dot" cx="[\d.]+" cy="([\d.]+)"/g)].map((d) => +d[1]);
  return { ticks, dots, top: 14, bottom: +H - 28 }; // svgLine's margins
}
const SERIES = {
  'low-ranked (Abilene Christian, #206-#296)': null, // the committed profile, unchanged
  'top-10': [3, 1, 7, 2, 10, 5],
};
for (const [name, ranks] of Object.entries(SERIES)) {
  test(`RPI chart, ${name}: ticks inside the plotted range, dots inside it, no labels collide`, async () => {
    const p = readJson('data/programs/abilene-christian.json');
    if (ranks) p.seasons.filter((s) => s.rpiRank).slice(0, 6).forEach((s, i) => { s.rpiRank = ranks[i]; });
    const pg = loadPage({ 'data/programs/abilene-christian.json': p }); await pg.sb.loadIndex();
    await pg.sb.renderProfile('abilene-christian', 'overview');
    const { ticks, dots, top, bottom } = chartOf(pg.tab());
    assert.ok(ticks.length >= 2, `only ${ticks.length} ticks`);
    assert.equal(dots.length, 6);
    for (const t of ticks) assert.ok(t.y >= top - 0.01 && t.y <= bottom + 0.01, `tick #${t.rank} at y=${t.y} is outside ${top}-${bottom}`);
    for (const y of dots) assert.ok(y >= top - 0.01 && y <= bottom + 0.01, `a dot at y=${y} is outside ${top}-${bottom}`);
    const ys = ticks.map((t) => t.y).sort((a, b) => a - b);
    for (let i = 1; i < ys.length; i++) assert.ok(ys[i] - ys[i - 1] >= LABEL_H, `tick labels ${ys[i] - ys[i - 1]}px apart: ${JSON.stringify(ticks)}`);
    // The ticks span the data: one at or above the best rank's dot, one at or below the worst.
    assert.ok(ys[0] <= Math.min(...dots) + 0.01 && ys[ys.length - 1] >= Math.max(...dots) - 0.01, `ticks ${JSON.stringify(ticks)} do not bracket the dots ${dots}`);
    // The plotted range is fitted to the data, not to a fixed #1-#25: for these two series the dots span at
    // least half the plot's height (on the old fixed #1-#25 axis: 31% and 38%).
    const fill = (Math.max(...dots) - Math.min(...dots)) / (bottom - top);
    assert.ok(fill >= 0.5, `the dots use only ${Math.round(fill * 100)}% of the plot height`);
    // Round ranks only: #1, or a multiple of the step the ticks share.
    for (const t of ticks) assert.ok(t.rank >= 1, `tick #${t.rank}`);
    for (const t of ticks) assert.ok(t.rank === 1 || t.rank % 5 === 0 || (ticks.length > 1 && t.rank % 2 === 0), `#${t.rank} is not a round rank`);
  });
}
