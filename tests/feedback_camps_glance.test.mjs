// Three small page fixes (PR for #47, #71 and #8).
//   #47 the feedback form's failure is styled as one (.feedback-note.error) and takes focus, as success does;
//   #71 a month-precision camp is past only once the month it ENDS in is over (build.py camp_in_window's rule);
//   #8  the "Program at a glance" stats grid can shrink inside its 300 px panel and its values wrap instead of being cut.
//
//     node --test tests/feedback_camps_glance.test.mjs
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM. #8's CSS is read with the exact-layout
// check of tests/lib/css_cascade.mjs (#430); the rendered width was measured in a browser (PR body).
//
// FCG_TEST_HTML (optional) points at another copy of index.html, so the page from before this change can be run through
// these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { parseCss, exactLayout } from './lib/css_cascade.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.FCG_TEST_HTML || path.join(PUBLIC, 'index.html');
const PAGE = fs.readFileSync(HTML, 'utf8');

let focused = null;
function makeElement(name) {
  const classes = new Set();
  const el = { _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, dataset: {}, style: {},
    classList: { add: (...c) => c.forEach(x => classes.add(x)), remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, on) => ((on ?? !classes.has(c)) ? classes.add(c) : classes.delete(c)), contains: c => classes.has(c) },
    setAttribute() { }, getAttribute: () => null, removeAttribute() { }, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null, matches: () => false,
    focus() { focused = name; }, contains: () => false };
  return el;
}
function loadPage(fetchAnswer) {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  // the feedback form, as the IIFE reads it at load: its submit listener and its Send button are kept
  const listeners = {};
  const form = bySelector('#feedbackForm');
  form.elements = { message: { value: 'A test message' }, email: { value: '' }, website: { value: '' } };
  form.addEventListener = (type, fn) => { listeners[type] = fn; };
  form.querySelector = () => ({ disabled: false, addEventListener() { } });
  bySelector('#feedback').querySelector = () => makeElement('summary');
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector, querySelectorAll: () => [],
      createElement: makeElement, addEventListener() { } },
    location: { hash: '#/', replace(h) { this.hash = h; } }, history: { replaceState() { } }, matchMedia: () => ({ matches: false }),
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } }, innerWidth: 1400, addEventListener() { },
    fetch: async url => {
      if (String(url) === '/api/feedback') return fetchAnswer();
      let rel = String(url).replace(/^\//, ''); if (rel === 'api/v1/programs') rel = 'data/programs/index.json';
      const p = path.join(PUBLIC, rel.replace(/\?.*$/, ''));
      if (!p.startsWith(PUBLIC) || !fs.existsSync(p)) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      const body = fs.readFileSync(p, 'utf8'); return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = PAGE.split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n') + '\n;Object.assign(globalThis, { tabCamps });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sb: sandbox, note: bySelector('#feedbackNote'), form, submit: () => listeners.submit({ preventDefault() { } }) };
}
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise(r => setTimeout(r, 0)); };

// ---------- #47 ----------
for (const [what, answer] of [
  ['the server refuses (400)', async () => ({ ok: false, status: 400, async json() { return { error: 'Message is required' }; } })],
  ['the server cannot be reached', async () => { throw new TypeError('Failed to fetch'); }],
]) {
  test(`#47: when ${what}, the note is styled as an error and takes focus`, async () => {
    const pg = loadPage(answer);
    focused = null;
    await pg.submit(); await settle();
    assert.ok(pg.note.classList.contains('error'), 'the failure note has no error class');
    assert.ok(!pg.note.classList.contains('ok'), 'the failure note is styled as a success');
    assert.equal(focused, '#feedbackNote', 'focus did not move to the note (it stays on <body>)');
    assert.equal(pg.note.tabIndex, -1);
    assert.equal(pg.form.hidden, false, 'the form (with what the visitor typed) must stay');
  });
}
test('#47: a later success clears the error class, and the CSS styles .feedback-note.error', async () => {
  let fail = true;
  const pg = loadPage(async () => (fail ? { ok: false, status: 503, async json() { return {}; } } : { ok: true, status: 200, async json() { return { ok: true }; } }));
  await pg.submit(); await settle();
  assert.ok(pg.note.classList.contains('error'));
  fail = false;
  await pg.submit(); await settle();
  assert.ok(pg.note.classList.contains('ok') && !pg.note.classList.contains('error'), 'success after a failure kept the error class');
  assert.match(PAGE, /\.feedback-note\.error \{ color: var\(--danger-text\); \}/);
});

// ---------- #71 ----------
test('#71: a month-precision camp running into this month is upcoming, as camp_in_window reads it', async () => {
  const pg = loadPage(async () => ({ ok: true, status: 200, async json() { return {}; } }));
  const d = new Date(), ym = (y, m) => `${y}-${String(m).padStart(2, '0')}`;
  const thisM = ym(d.getFullYear(), d.getMonth() + 1);
  const prev = new Date(d.getFullYear(), d.getMonth() - 1, 1), prevM = ym(prev.getFullYear(), prev.getMonth() + 1);
  const camp = (name, startDate, endDate) => ({ kind: 'camp', name, precision: 'month', startDate, endDate, confidence: 'heuristic' });
  const p = { slug: 'x', links: { athletics: 'https://athletics.example.test' }, _build: { skipped: [], failed: [] },
    camps: { url: 'https://athletics.example.test/camps', host: 'athletics.example.test', _meta: [],
      items: [camp('Runs into this month', prevM, thisM), camp('Ended last month', prevM, prevM), camp('No end date, last month', prevM, null)] } };
  const html = await pg.sb.tabCamps(p);
  const up = /<h3>Upcoming camps<\/h3>([\s\S]*?)<\/div><\/div>/.exec(html)?.[1] || '';
  const past = /<b>Past camps<\/b>([\s\S]*?)<\/details>/.exec(html)?.[1] || '';
  assert.ok(up.includes('Runs into this month'), 'a camp ending this month is listed as past');
  assert.ok(past.includes('Ended last month') && past.includes('No end date, last month'), 'a camp that ended last month is not past');
  assert.ok(!up.includes('Ended last month'));
});

// ---------- #8 ----------
test('#8: the glance stats grid can shrink inside its panel, and its values wrap (never cut off)', () => {
  const css = [...PAGE.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n');
  const watched = sel => ['.glance-stats', '.stat-value', '.stat-sub', '.glance-panel'].includes(sel);
  const expected = {
    '|.glance-panel': { position: 'sticky', top: '0', overflow: 'hidden', 'min-width': '0' },
    '@media (max-width: 1024px)|.glance-panel': { order: '-1', position: 'static' },  // one column: the panel goes first
    '|.glance-stats': { display: 'grid', 'grid-template-columns': 'repeat(2, minmax(0, 1fr))', gap: '12px 16px', padding: '14px 18px' },
    '|.stat-value': { 'margin-top': '2px', 'font-size': '20px', 'line-height': '1.2' },
    '|.stat-sub': { 'margin-top': '2px', 'font-size': '11px' },
  };
  exactLayout(parseCss(css), { watched, expected, cannot: 'the glance test cannot read' });
  for (const sel of ['.stat-value', '.stat-sub']) {
    const body = new RegExp(`(?:^|\\n)${sel.replace('.', '\\.')} \\{([^}]*)\\}`).exec(css)?.[1] || '';
    assert.match(body, /overflow-wrap: anywhere/, `${sel} does not wrap`);
    assert.doesNotMatch(body, /nowrap|text-overflow/, `${sel} is still cut off`);
  }
});
