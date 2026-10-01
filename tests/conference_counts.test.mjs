// Issue #16: the conference pills' counts were fixed once from the index, so with West selected ACC still said 17 and
// West + MAAC gave an unannounced empty list. Each pill now counts what it would list together with every OTHER
// active filter (region, division, search, conditions), leaving the conference selection itself out; a 0 stays a
// clickable pill drawn quieter (.pill-zero), and typing a search updates the counts without rebuilding the drawer.
//
//     node --test tests/conference_counts.test.mjs
//
// Same mechanism as tests/drawer_show_results.test.mjs: the inline <script> of public/index.html runs in a `vm`
// against a stub DOM. Expected counts come from index.json where the filter is plain data (region, division, a
// condition) and from the cards the list view actually draws where it is a search ("what the list would show").
//
// CONF_COUNTS_TEST_HTML (optional) points at another copy of index.html, so the page from before this change can be
// run through these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.CONF_COUNTS_TEST_HTML || path.join(PUBLIC, 'index.html');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const D = p => p.division || 'Other', C = p => p.conference || 'Other';
const unesc = t => t.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

// The conference pills as drawn: [{ div, conf, n, zero, active }]. A pill's division is its data-conf-div, or, on the
// page before this change (which has none), the division group it sits under.
function pills(html) {
  const out = [];
  let div = null;
  for (const m of html.matchAll(/<div class="pill-group-label">([^<]*)<\/div>|<button ([^>]*\bdata-conf="([^"]+)"[^>]*)>([^<]*)<span class="pill-sub">(\d+)<\/span><\/button>/g)) {
    if (m[1] != null) { div = m[1]; continue; }
    const attrs = m[2];
    out.push({ div: unesc(/data-conf-div="([^"]*)"/.exec(attrs)?.[1] ?? div), conf: unesc(m[3]), n: Number(m[5]),
      zero: /class="[^"]*\bpill-zero\b/.test(attrs), active: /class="[^"]*\bactive\b/.test(attrs) });
  }
  return out;
}

// Stubs for the drawn pills, so an in-place update (syncConfCounts) can be read back.
function pillStubs(html) {
  return [...html.matchAll(/<button ([^>]*\bdata-conf-div="([^"]*)"[^>]*)>[^<]*<span class="pill-sub">(\d+)<\/span><\/button>/g)].map(m => {
    const classes = new Set((/class="([^"]*)"/.exec(m[1])?.[1] || '').split(/\s+/));
    const sub = { textContent: m[3] };
    return { dataset: { conf: unesc(/data-conf="([^"]*)"/.exec(m[1])[1]), confDiv: unesc(m[2]) }, title: '', sub,
      querySelector: sel => (sel === '.pill-sub' ? sub : null),
      classList: { toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)), contains: c => classes.has(c) } };
  });
}

let stubs = [];
function makeElement(name) {
  const el = {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, dataset: {}, style: {},
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null, matches: () => false,
    focus() { }, contains: () => false,
  };
  if (name === '#sidebar') el.querySelectorAll = sel => (sel === '[data-conf-div]' ? (stubs = pillStubs(el.innerHTML)) : []);
  return el;
}

function loadPage() {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
  const readPublic = url => {
    let rel = url.replace(/^\//, '');
    if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
    const p = path.join(PUBLIC, rel.replace(/\?.*$/, ''));
    return p.startsWith(PUBLIC) && fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: {
      documentElement: makeElement('html'), body: makeElement('body'),
      querySelector: bySelector, querySelectorAll: () => [], createElement: makeElement, addEventListener() { },
    },
    location: { hash: '', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: {
      getItem: k => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k),
    },
    innerWidth: 1400,
    addEventListener() { },
    fetch: async url => {
      const body = readPublic(url);
      if (body == null) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(HTML, 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>');
  const b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'index.html: could not find the inline <script>');
  const src = lines.slice(a + 1, b).join('\n')
    + '\n;Object.assign(globalThis, { S, renderSidebar, renderList, loadIndex, setQuery, filteredPrograms });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}

const sb = loadPage();
const S = sb.S;
const side = () => sb.document.querySelector('#sidebar').innerHTML;
const settle = (ms = 0) => new Promise(r => setTimeout(r, ms));
const reset = st => { Object.assign(S.filters, { conf: [], region: [], division: [], classYear: [], cond: [], sort: 'rpi', sortDir: null, view: 'cards' }, st); S.q = ''; S.qRaw = ''; };
const draw = () => { S.sidebarTab = 'programs'; sb.location.hash = '#/'; sb.renderSidebar(); return pills(side()); };
const tally = rows => { const m = new Map(); rows.forEach(p => m.set(`${D(p)}|${C(p)}`, (m.get(`${D(p)}|${C(p)}`) || 0) + 1)); return m; };
const drawnAs = ps => new Map(ps.map(p => [`${p.div}|${p.conf}`, p.n]));

test('setup', async () => {
  await sb.loadIndex();
  reset({});
  assert.ok(INDEX.programs.length > 900 && S.index.divisions.length === 3, 'fixture: three divisions expected');
});

// Pills drawn under a group label on the old page carry the label, not the code: map it back.
const norm = ps => ps.map(p => ({ ...p, div: /^D\d$|^Other$/.test(p.div) ? p.div : ({ 'Division I': 'D1', 'Division II': 'D2', 'Division III': 'D3' }[p.div] || p.div) }));

test('no filter: every pill counts its division\'s programs in that conference', () => {
  reset({});
  const got = drawnAs(norm(draw()));
  const want = tally(INDEX.programs);
  assert.ok(got.size > 50, `only ${got.size} conference pills drawn`);
  for (const [k, n] of got) assert.equal(n, want.get(k) || 0, k);
});

test('West: ACC counts its West programs, Metro (the MAAC) reads 0 (drawn quieter, still a button)', () => {
  reset({ region: ['West'] });
  const ps = norm(draw());
  const want = tally(INDEX.programs.filter(p => p.region === 'West'));
  for (const p of ps) assert.equal(p.n, want.get(`${p.div}|${p.conf}`) || 0, `${p.div} ${p.conf} under West`);
  const acc = ps.find(p => p.div === 'D1' && p.conf === 'ACC'), maac = ps.find(p => p.div === 'D1' && p.conf === 'Metro');
  assert.equal(acc.n, INDEX.programs.filter(p => p.region === 'West' && p.conference === 'ACC').length);
  assert.ok(acc.n < INDEX.programs.filter(p => p.conference === 'ACC').length, 'fixture: ACC should have programs outside the West');
  assert.equal(maac.n, 0);
  assert.ok(maac.zero && !acc.zero, 'a 0 pill is drawn as .pill-zero, a non-zero one is not');
});

test('each count equals the list the pill would give (West, D1 only)', async () => {
  reset({ region: ['West'], division: ['D1'] });
  const ps = norm(draw());
  assert.ok(ps.every(p => p.div === 'D1'), 'with D1 selected only D1 conferences are drawn');
  for (const p of ps.filter(x => x.conf !== 'Independent')) {
    S.filters.conf = [p.conf];
    assert.equal(sb.filteredPrograms().length, p.n, `West + D1 + ${p.conf}: the pill says ${p.n}`);
  }
  S.filters.conf = [];
});

test('region plus division: South + D2, and Northeast + D3', () => {
  for (const [region, div] of [['South', 'D2'], ['Northeast', 'D3']]) {
    reset({ region: [region], division: [div] });
    const ps = norm(draw());
    const want = tally(INDEX.programs.filter(p => p.region === region && D(p) === div));
    assert.ok(ps.length && ps.every(p => p.div === div), `${region} + ${div}: only ${div} pills`);
    for (const p of ps) assert.equal(p.n, want.get(`${p.div}|${p.conf}`) || 0, `${region} + ${div}: ${p.conf}`);
    assert.ok(ps.some(p => p.n === 0) && ps.some(p => p.n > 0), `${region} + ${div}: fixture should give both zero and non-zero pills`);
  }
});

test('the selected conference is left out of its own count, and of the others\'', () => {
  reset({ region: ['West'] });
  const before = drawnAs(norm(draw()));
  S.filters.conf = ['ACC'];
  const ps = norm(draw());
  for (const p of ps) assert.equal(p.n, before.get(`${p.div}|${p.conf}`), `${p.conf} changed when ACC was selected`);
  assert.ok(ps.find(p => p.conf === 'ACC' && p.div === 'D1').active);
});

test('a condition counts too (admission rate under 30%)', () => {
  reset({ cond: [{ field: 'admissionRate', op: '<', value: 0.3 }] });
  const ps = norm(draw());
  const want = tally(INDEX.programs.filter(p => p.admissionRate != null && p.admissionRate < 0.3));
  for (const p of ps) assert.equal(p.n, want.get(`${p.div}|${p.conf}`) || 0, `${p.div} ${p.conf} with the condition`);
});

test('search "Ohio": counts equal what the list draws per conference; with West as well, every pill reads 0', async () => {
  reset({});
  S.q = 'ohio'; S.qRaw = 'Ohio';
  const ps = norm(draw());
  const want = tally(sb.filteredPrograms());
  assert.ok(sb.filteredPrograms().length > 5, 'fixture: "Ohio" should match several programs');
  for (const p of ps) assert.equal(p.n, want.get(`${p.div}|${p.conf}`) || 0, `Ohio: ${p.div} ${p.conf}`);
  S.filters.region = ['West'];
  assert.equal(sb.filteredPrograms().length, 0, 'fixture: West + Ohio lists nothing');
  const west = norm(draw());
  assert.ok(west.length && west.every(p => p.n === 0 && p.zero), 'West + Ohio: a pill still promises programs');
});

test('typing a search updates the counts in place, without rebuilding the drawer', async () => {
  reset({});
  draw();
  const html = side();
  sb.setQuery('Ohio');
  await settle(150);
  assert.equal(side(), html, 'typing rebuilt the drawer (focus would leave the search box)');
  assert.ok(stubs.length > 50, 'the drawn pills were not updated in place');
  const want = tally(sb.filteredPrograms());
  for (const b of stubs) {
    const n = want.get(`${b.dataset.confDiv}|${b.dataset.conf}`) || 0;
    assert.equal(b.sub.textContent, String(n), `${b.dataset.confDiv} ${b.dataset.conf}`);
    assert.equal(b.classList.contains('pill-zero'), n === 0);
    assert.match(b.title, new RegExp(`^${n} program`));
  }
  sb.setQuery('');
  await settle(150);
});

test('a 0 pill is drawn quieter by colour and border, not opacity, and is never hidden', () => {
  const css = (/<style>([\s\S]*?)<\/style>/.exec(fs.readFileSync(HTML, 'utf8')) || [])[1] || '';
  const rule = /\.pill\.pill-zero:not\(\.active\) \{([^}]*)\}/.exec(css)?.[1] || '';
  assert.match(rule, /color: var\(--text-secondary\)/);
  assert.doesNotMatch(rule, /display|visibility|opacity/);
  reset({ region: ['West'] });
  const before = norm(draw()).map(p => `${p.div}|${p.conf}`);
  reset({});
  assert.deepEqual(norm(draw()).map(p => `${p.div}|${p.conf}`), before, 'the set or order of pills changed with the counts');
});
