// Search by place (#404 phase 1, item 2): a state name, a state code, a city, or a city and its state lists the
// programs there, ranked below every name hit.
//
//     node --test tests/place_search.test.mjs
//
// Same mechanism as tests/shortlist_unsave.test.mjs: the inline <script> of public/index.html runs in a `vm` against
// a stub DOM that records innerHTML, and fetches are answered from the committed public/data (nothing leaves the
// machine). The query goes in through the page's own setQuery and the header box's own keydown listener (#434); the list
// is the page's own renderList. Every expected set is counted from the shipped index here (state and city fields),
// never from the page's search code.
//
// PLACE_TEST_HTML (optional) points the suite at another copy of index.html, so the page from before this change can
// be run through these checks to show them failing.
//
// What it CANNOT prove, and a human must check in a browser: the keyboard on a real phone (the in-app browser's key
// presses do not reach inputs), and how a long result list reads at 375 px.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.PLACE_TEST_HTML || path.join(PUBLIC, 'index.html');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const shown = p => p.shortName || p.name;
const inState = st => INDEX.programs.filter(p => p.state === st);

function makeElement(name) {
  const listeners = {};
  return {
    _name: name, _listeners: listeners, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, removeEventListener() { },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { }, blur() { this._blurred = true; }, contains: () => false,
  };
}

function loadPage() {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const readPublic = url => {
    let rel = url.replace(/^\//, '');
    if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
    else if (rel === 'api/v1/camps') rel = 'data/camps/index.json';
    const p = path.join(PUBLIC, rel);
    return p.startsWith(PUBLIC) && fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array,
    Object, RegExp, Intl, isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: {
      documentElement: makeElement('html'), body: makeElement('body'),
      querySelector: bySelector, querySelectorAll: () => [], createElement: makeElement, addEventListener() { },
    },
    location: { hash: '#/', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } },
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
    + `\n;for (const k of ['S', 'setQuery', 'searchMatches', 'renderList', 'renderSidebar', 'loadIndex']) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}

const sb = loadPage();
await sb.loadIndex();
sb.S.filters.view = 'cards';
const settle = () => new Promise(r => setTimeout(r, 120));  // setQuery re-renders after an 80 ms pause

// Type a query the way the header box does, and return the cards the list shows, in order, with their division tags.
async function search(raw) {
  sb.location.hash = '#/';
  sb.setQuery(raw);
  await settle();
  await sb.renderList();
  const html = sb.document.querySelector('#app').innerHTML;
  const cards = html.split('<div class="card pcard').slice(1);
  return cards.map(c => ({
    slug: /data-slug="([^"]+)"/.exec(c)?.[1],
    div: /<div class="meta"><span class="div-tag"[^>]*>(D[123])<\/span>/.exec(c)?.[1] ?? null,
    why: /<span class="why"[^>]*>([^<]*)<\/span>/.exec(c)?.[1] ?? null,
  }));
}
const slugs = rows => rows.map(r => r.slug);
const DIV = Object.fromEntries(INDEX.programs.map(p => [p.slug, p.division]));

test('fixture: the index has Ohio programs in all three divisions, and 3 programs with no state', () => {
  const oh = inState('OH');
  const by = d => oh.filter(p => p.division === d).length;
  assert.ok(by('D1') && by('D2') && by('D3'), `Ohio no longer spans D1-D3: ${by('D1')}/${by('D2')}/${by('D3')}`);
  console.log(`    Ohio in the index: ${oh.length} (D1 ${by('D1')}, D2 ${by('D2')}, D3 ${by('D3')})`);
  assert.deepEqual(INDEX.programs.filter(p => !p.state).map(p => p.slug).sort(), ['claremont-mudd-scripps', 'emmanuel-ga', 'simon-fraser']);
});

for (const q of ['Ohio', 'OH']) {
  test(`"${q}" lists every Ohio program in the index, each with its own division tag`, async () => {
    const rows = await search(q);
    const got = new Set(slugs(rows)), want = inState('OH').map(p => p.slug);
    assert.deepEqual(want.filter(s => !got.has(s)), [], `Ohio programs missing for "${q}"`);
    for (const r of rows.filter(r => want.includes(r.slug))) assert.equal(r.div, DIV[r.slug], `${r.slug}: division tag`);
  });
}

test('"Ohio": a name hit outranks a place hit (Ohio and Ohio State before Kenyon), and the place hit says why', async () => {
  const rows = await search('Ohio'), order = slugs(rows);
  const place = rows.filter(r => r.why === 'in Ohio');
  assert.ok(place.length, 'no program was listed for being in Ohio');
  const at = s => { const i = order.indexOf(s); assert.ok(i >= 0, `${s} not listed`); return i; };
  assert.ok(at('ohio-university') < at('kenyon-college') && at('ohio-state') < at('kenyon-college'), 'a place-only hit came before a name hit');
  assert.equal(rows.find(r => r.slug === 'kenyon-college')?.why, 'in Ohio');
  const firstPlace = rows.findIndex(r => r.why === 'in Ohio');
  assert.ok(rows.slice(firstPlace).every(r => r.why === 'in Ohio'), 'a name hit came after a place hit');
});

test('"Washington": every school named Washington comes first, then the programs in Washington state and Washington, DC', async () => {
  const rows = await search('Washington'), order = slugs(rows);
  const named = INDEX.programs.filter(p => /\bwashington\b/i.test(shown(p))).map(p => p.slug);
  const placeOnly = [...inState('WA'), ...INDEX.programs.filter(p => p.city === 'Washington' && p.state === 'DC')]
    .map(p => p.slug).filter(s => !named.includes(s));
  assert.ok(named.length >= 5 && placeOnly.length >= 5, `fixture: ${named.length} named, ${placeOnly.length} place-only`);
  assert.deepEqual(placeOnly.filter(s => !order.includes(s)), [], 'a program in Washington state or DC is missing');
  const lastNamed = Math.max(...named.map(s => order.indexOf(s)));
  const firstPlace = Math.min(...placeOnly.map(s => order.indexOf(s)));
  assert.ok(named.every(s => order.includes(s)), 'a school named Washington is missing');
  assert.ok(lastNamed < firstPlace, 'a place-only hit came before a school named Washington');
});

test('"Georgia": the University of Georgia is first; Georgia\'s programs follow; emmanuel-ga (no state) is not a place hit', async () => {
  const rows = await search('Georgia'), order = slugs(rows);
  assert.equal(order[0], 'georgia');
  assert.deepEqual(inState('GA').map(p => p.slug).filter(s => !order.includes(s)), []);
  assert.notEqual(rows.find(r => r.slug === 'emmanuel-ga')?.why, 'in Georgia', 'emmanuel-ga has no state in the index, so it cannot be a place hit');
});

test('a two-letter code counts only typed in capitals: "pa" does not add Pennsylvania, "PA" does', async () => {
  const pa = inState('PA').map(p => p.slug);
  const lower = await search('pa');
  assert.ok(!lower.some(r => r.why === 'in Pennsylvania'), '"pa" listed programs for being in Pennsylvania');
  assert.ok(!slugs(lower).includes('villanova'), '"pa" listed Villanova');
  const upper = await search('PA');
  assert.deepEqual(pa.filter(s => !slugs(upper).includes(s)), [], '"PA" missed a Pennsylvania program');
  const typing = await search('Pac');
  assert.ok(!slugs(typing).includes('villanova'), '"Pac" listed Villanova');
});

test('a partial state name is not a place: "Ohi" does not list Kenyon', async () => {
  assert.ok(!slugs(await search('Ohi')).includes('kenyon-college'));
});

test('a city: "Columbus" lists every program in a city of that name; "Columbus OH" and "columbus, ohio" only Ohio\'s', async () => {
  const all = INDEX.programs.filter(p => p.city === 'Columbus').map(p => p.slug);
  const oh = INDEX.programs.filter(p => p.city === 'Columbus' && p.state === 'OH').map(p => p.slug);
  assert.ok(oh.length >= 2 && all.length > oh.length, 'fixture: Columbus should be in Ohio and elsewhere');
  const any = slugs(await search('Columbus'));
  assert.deepEqual(all.filter(s => !any.includes(s)), []);
  for (const q of ['Columbus OH', 'columbus, ohio']) {
    const got = slugs(await search(q));
    assert.deepEqual(oh.filter(s => !got.includes(s)), [], `${q}: an Ohio program in Columbus is missing`);
    assert.deepEqual(all.filter(s => !oh.includes(s)).filter(s => got.includes(s)), [], `${q}: a Columbus outside Ohio is listed`);
  }
});

test('the three programs with no state are still found by name', async () => {
  for (const [q, slug] of [['Emmanuel', 'emmanuel-ga'], ['Simon Fraser', 'simon-fraser']]) {
    assert.ok(slugs(await search(q)).includes(slug), `${slug} not found by "${q}"`);
  }
});

// Enter through the header box's own keydown listener (#434: the box is static and wired once, at load).
async function enter(raw, hash = '#/') {
  sb.location.hash = hash;
  const box = sb.document.querySelector('#q');  // #434: the header box, wired once at load
  assert.equal((box._listeners.keydown || []).length, 1, 'the header box should have exactly one keydown handler');
  box.value = raw;
  sb.setQuery(raw);
  await settle();
  const ev = { key: 'Enter', shiftKey: false, preventDefault() { } };
  for (const fn of box._listeners.keydown || []) fn(ev);
  await settle();
  return sb.location.hash;
}

test('Enter on a place query keeps the list (no single program opens); Enter on a name query still opens the top hit', async () => {
  assert.equal(await enter('Ohio'), '#/', 'Enter on "Ohio" left the list');
  assert.equal(await enter('OH'), '#/', 'Enter on "OH" left the list');
  assert.equal(await enter('Kenyon'), '#/p/kenyon-college', 'Enter on a school name no longer opens it');
  // Stanford is also its city's name, but the only program in Stanford, CA is Stanford: nothing is listed for the place alone.
  assert.equal(INDEX.programs.find(p => p.slug === 'stanford')?.city, 'Stanford', 'fixture: Stanford is in Stanford, CA');
  assert.equal(await enter('Stanford'), '#/p/stanford', 'Enter on a school that shares its city name no longer opens it');
});

// Huatuo on #409: typing on #/camps narrows the camps to the matching programs, so a place query's Enter must stay there.
test('on #/camps, Enter on a place query stays on the ID Camps view', async () => {
  assert.equal(await enter('Ohio', '#/camps'), '#/camps', 'Enter on "Ohio" left the ID Camps view');
  assert.equal(await enter('OH', '#/camps'), '#/camps');
});

// #23: the status count and Enter describe the list the filters leave, not every match in the index.
const statusCount = () => {
  const t = sb.document.querySelector('#qStatus').textContent;
  const m = /^(\d+) match/.exec(t);
  return { text: t, n: m ? Number(m[1]) : /^No match/.test(t) ? 0 : NaN };
};
async function withFilters(patch, fn) {
  const f = sb.S.filters, saved = { region: f.region, division: f.division, conf: f.conf };
  Object.assign(f, { region: [], division: [], conf: [] }, patch);
  try { return await fn(); } finally { Object.assign(f, saved); }
}

test('#23: with a region or division filter, the status count equals the cards the list shows', async () => {
  for (const [patch, q] of [[{ region: ['West'] }, 'Ohio'], [{ region: ['West'] }, 'Texas A&M'], [{ division: ['D3'] }, 'Ohio'],
    [{ region: ['West'] }, 'Washington']]) {
    await withFilters(patch, async () => {
      const shownCards = (await search(q)).length, st = statusCount();
      assert.equal(st.n, shownCards, `${JSON.stringify(patch)} "${q}": the status says "${st.text}" over ${shownCards} cards`);
    });
  }
  await withFilters({ region: ['West'] }, async () => {
    await search('Ohio');
    assert.match(statusCount().text, /^No match within your filters \(\d+ without them\)$/);
  });
});

test('#23: Enter never opens a program the filters hide', async () => {
  assert.equal(INDEX.programs.find(p => p.slug === 'kenyon-college')?.region, 'Midwest', 'fixture: Kenyon is in the Midwest');
  await withFilters({ region: ['West'] }, async () => {
    assert.equal(await enter('Kenyon'), '#/', 'Enter opened Kenyon although the West filter hides it');
  });
  await withFilters({ region: ['Midwest'] }, async () => {
    assert.equal(await enter('Kenyon'), '#/p/kenyon-college', 'Enter no longer opens a program the filters show');
  });
});
