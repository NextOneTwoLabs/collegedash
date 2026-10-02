// Issue #425: conference selection was keyed by name only, so tapping the D2 "Independent" pill selected the
// Independents of all three divisions (7 pill, 9 listed). A pill now writes "<division>|<conference>"; a bare name
// (a save from before, an Ask answer, a bare #/c/ link) keeps its old meaning: that name in every division.
//
//     node --test tests/conf_by_division.test.mjs
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM, as in tests/conference_counts.test.mjs.
// The sidebar stub hands back the conference pills it drew, so a tap goes through the page's own click handler.
// Expected lists are counted from index.json.
//
// Tests marked GUARD pass on main too, on purpose: they pin the old meaning of a bare name (a visitor's saved filters,
// existing #/c/<name> links), which this change must not break.
//
// CONF_DIV_TEST_HTML (optional) points at another copy of index.html, so the page from before this change can be run
// through these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.CONF_DIV_TEST_HTML || path.join(PUBLIC, 'index.html');
const PAGE = fs.readFileSync(HTML, 'utf8');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const IND = INDEX.programs.filter(p => p.conference === 'Independent');
const slugsOf = ps => ps.map(p => p.slug).sort();
const unesc = t => t.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

// The conference pills as drawn, as stubs a click can be sent to: { conf, div, active, onclick }.
let pills = [];
function pillStubs(html) {
  return [...html.matchAll(/<button ([^>]*\bdata-conf="([^"]*)"[^>]*)>/g)].map(m => ({
    dataset: { conf: unesc(m[2]), confDiv: unesc(/data-conf-div="([^"]*)"/.exec(m[1])?.[1] || '') },
    active: /class="[^"]*\bactive\b/.test(m[1]), onclick: null,
  }));
}
function makeElement(name) {
  const el = {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, dataset: {}, style: {},
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null, matches: () => false,
    focus() { }, contains: () => false,
  };
  if (name === '#sidebar') el.querySelectorAll = sel => (sel === '[data-conf]' ? (pills = pillStubs(el.innerHTML)) : []);
  return el;
}
function loadPage() {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector,
      querySelectorAll: () => [], createElement: makeElement, addEventListener() { } },
    location: { hash: '', replace(h) { this.hash = h; } }, history: { replaceState() { } }, matchMedia: () => ({ matches: false }),
    localStorage: { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) },
    innerWidth: 1400, addEventListener() { },
    fetch: async url => {
      let rel = url.replace(/^\//, '');
      if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
      else if (rel === 'api/v1/camps') rel = 'data/camps/index.json';
      const p = path.join(PUBLIC, rel.replace(/\?.*$/, ''));
      if (!p.startsWith(PUBLIC) || !fs.existsSync(p)) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      const body = fs.readFileSync(p, 'utf8'); return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = PAGE.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n')
    + '\n;Object.assign(globalThis, { S, renderSidebar, renderList, renderCamps, loadIndex, filteredPrograms, route, applyAsk });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}
const sb = loadPage();
const S = sb.S;
const app = () => sb.document.querySelector('#app').innerHTML;
const reset = st => { Object.assign(S.filters, { conf: [], region: [], division: [], classYear: [], cond: [], sort: 'name', sortDir: null, view: 'cards' }, st); S.q = ''; S.qRaw = ''; S.askResult = null; };
const draw = () => { S.sidebarTab = 'programs'; sb.location.hash = '#/'; sb.renderSidebar(); return pills; };
const pill = (div, conf) => draw().find(p => p.dataset.conf === conf && p.dataset.confDiv === div);
const tap = (div, conf) => { const p = pill(div, conf); assert.ok(p && typeof p.onclick === 'function', `no ${div} ${conf} pill to tap`); p.onclick(); };
const listed = () => slugsOf(sb.filteredPrograms());
const lit = conf => draw().filter(p => p.dataset.conf === conf && p.active).map(p => p.dataset.confDiv).sort();
const title = () => unesc((/<h1[^>]*>([\s\S]*?)<\/h1>/.exec(app()) || /class="content-title"[^>]*>([\s\S]*?)<\//.exec(app()) || [])[1] || '');

test('setup: Independent exists in D1, D2 and D3', async () => {
  await sb.loadIndex();
  assert.deepEqual([...new Set(IND.map(p => p.division))].sort(), ['D1', 'D2', 'D3']);
  assert.ok(IND.filter(p => p.division === 'D2').length > 1);
  for (const p of INDEX.programs) assert.ok(!String(p.conference).includes('|'), `a conference name contains the key separator: ${p.conference}`);
});

test('tapping D2 Independent lists exactly the D2 Independents, lights only that pill, and the title names the division', async () => {
  reset({});
  tap('D2', 'Independent');
  assert.deepEqual(listed(), slugsOf(IND.filter(p => p.division === 'D2')), 'the list is not exactly the D2 Independents');
  assert.deepEqual(lit('Independent'), ['D2']);
  await sb.renderList();
  assert.match(title(), /^Independent \(D2\)/, `title: ${title()}`);
  tap('D2', 'Independent');
  assert.deepEqual([...S.filters.conf], [], 'tapping it again does not clear it');
});

test('GUARD: a saved bare "Independent" still means every division, and lights all three pills', () => {
  reset({ conf: ['Independent'] });
  assert.deepEqual(listed(), slugsOf(IND));
  assert.deepEqual(lit('Independent'), ['D1', 'D2', 'D3']);
});

test('tapping D2 under a saved bare "Independent" leaves D1 and D3 selected', () => {
  reset({ conf: ['Independent'] });
  tap('D2', 'Independent');
  assert.deepEqual(listed(), slugsOf(IND.filter(p => p.division !== 'D2')));
  assert.deepEqual(lit('Independent'), ['D1', 'D3']);
});

test('Huatuo\'s condition: a bare name expands only into the divisions on screen', () => {
  reset({ conf: ['Independent'], division: ['D1', 'D2'] });
  tap('D2', 'Independent');
  assert.deepEqual([...S.filters.conf], ['D1|Independent'], 'expanded into a division that is not on screen');
  assert.deepEqual(listed(), slugsOf(IND.filter(p => p.division === 'D1')));
});

test('the #/c/ route: a keyed link selects one division\'s conference', async () => {
  reset({});
  sb.location.hash = '#/c/D2%7CIndependent';
  await sb.route();
  assert.deepEqual(listed(), slugsOf(IND.filter(p => p.division === 'D2')), 'the keyed link does not select the D2 Independents');
  reset({});
});

test('GUARD: a bare #/c/ACC link works as before', async () => {
  reset({});
  sb.location.hash = '#/c/ACC';
  await sb.route();
  assert.deepEqual(listed(), slugsOf(INDEX.programs.filter(p => p.conference === 'ACC')), 'GUARD: #/c/ACC');
});

test('a profile\'s conference crumb links the keyed form only for a shared name', () => {
  // the crumb expression, evaluated against two programs: a D2 Independent and an ACC school
  const m = /\{ label: p\.conference \|\| 'Programs', href: (`#\/c\/[^`]*`) \}/.exec(PAGE);
  assert.ok(m, 'the crumb expression changed shape');
  const href = vm.runInContext(`p => ${m[1]}`, sb);
  const d2 = IND.find(p => p.division === 'D2'), acc = INDEX.programs.find(p => p.conference === 'ACC');
  assert.equal(href(d2), '#/c/D2%7CIndependent');
  assert.equal(href(acc), '#/c/ACC');
});

test('Ask: a name stays bare (every division); a shared name asked with one division is keyed, and the banner names it', () => {
  reset({});
  sb.location.hash = '#/';
  sb.applyAsk({ conf: ['Independent'], division: [], region: [], classYear: [], cond: [], sort: null, reading: '' });
  assert.deepEqual([...S.filters.conf], ['Independent']);
  reset({});
  sb.applyAsk({ conf: ['Independent', 'ACC'], division: ['D2'], region: [], classYear: [], cond: [], sort: null, reading: '' });
  assert.ok(S.filters.conf.includes('D2|Independent'), `asked with D2: ${JSON.stringify(S.filters.conf)}`);
  assert.ok(S.askResult.parts.includes('Independent (D2)'), `banner parts: ${JSON.stringify(S.askResult.parts)}`);
});

test('one label helper: every place that prints the selection says "Independent (D2)"', async () => {
  // no printing site reads f.conf raw any more
  const script = PAGE.slice(PAGE.indexOf('<script>'), PAGE.indexOf('</script>'));
  for (const raw of [/f\.conf\.join\(/, /f\.conf\[0\]/, /\.\.\.f\.conf\b/]) assert.doesNotMatch(script, raw, `a raw print of f.conf: ${raw}`);
  reset({ conf: ['D2|Independent', 'ACC'] });
  sb.location.hash = '#/';
  await sb.renderList();
  assert.match(app(), /Independent \(D2\), ACC/, 'list subtitle');
  reset({ conf: ['D2|Independent'], view: 'table' });
  await sb.renderList();
  assert.match(app(), /<div class="flight-title">Independent \(D2\)<\/div>/, 'Stats table title');
  // #465 (D4): the ID Camps page no longer prints or applies the Programs conference selection
  reset({ conf: ['D2|Independent'] });
  sb.location.hash = '#/camps';
  await sb.renderCamps();
  assert.doesNotMatch(app(), /Independent \(D2\)/, 'the camps page carried the Programs conference selection');
  sb.location.hash = '#/';
});

test('#465 D4: a keyed Programs conference selection does not narrow the ID Camps page', async () => {
  // Before #465 the camp view applied the Programs pills (and #425 made a keyed value work there). The owner's D4: the
  // Programs filters do not narrow camps, so the page lists every upcoming ID camp whatever the pills say.
  const CAMPS = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'camps', 'index.json'), 'utf8'));
  const bySlug = new Map(INDEX.programs.map(p => [p.slug, p]));
  const tally = {};
  for (const c of CAMPS.camps) { const p = bySlug.get(c.slug); if (c.campType === 'id' && p?.division === 'D2') tally[p.conference] = (tally[p.conference] || 0) + 1; }
  const [conf, n] = Object.entries(tally).sort((a, b) => b[1] - a[1])[0] || [];
  assert.ok(n > 0, 'fixture: no D2 conference has an ID camp');
  reset({ conf: [`D2|${conf}`] });
  sb.location.hash = '#/camps';
  await sb.renderCamps();
  const today = new Date(), iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  const all = CAMPS.camps.filter(c => c.campType === 'id' && (bySlug.has(c.slug) || c.program) && (c.endDate || c.startDate) >= iso).length;
  const got = Number((/(\d+) upcoming ID camps? at/.exec(app()) || [])[1]);
  assert.ok(!/upcoming ID camps? of/.test(app()), 'the subtitle reads as filtered');
  assert.equal(got, all, `D2|${conf} (${n} camps) narrowed the camps page to ${got}; it lists ${all}`);
  sb.location.hash = '#/';
  reset({});
});
