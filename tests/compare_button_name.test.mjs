// Compare button accessible name (#486, follow-up to #480; WCAG 2.5.3 Label in Name).
//
//     node --test tests/compare_button_name.test.mjs
//
// The Compare button's visible text is "⇄ Compare", or "⇄ Comparing" once the program is in the tray. Its
// aria-label named the program but always began "Compare", so while on, the name did not contain the visible word
// "Comparing" and voice control could not match it. The name now begins with the visible word in both states, in
// the render path (cmpBtn) and in the refresh path (syncToggles). aria-pressed stays.
//
// Offline: the page's inline script runs in a vm over the committed index. COMPARE_NAME_TEST_HTML (optional)
// points at another copy of index.html, to run these checks against it.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const PAGE = fs.readFileSync(process.env.COMPARE_NAME_TEST_HTML || path.join(PUBLIC, 'index.html'), 'utf8');

function loadPage() {
  const el = () => ({ innerHTML: '', textContent: '', value: '', dataset: {}, style: {}, hidden: false,
    classList: { add() { }, remove() { }, toggle() { }, contains: () => false }, setAttribute() { }, getAttribute: () => null,
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
  const src = lines.slice(a + 1, b).join('\n') + '\n;Object.assign(globalThis, { S, loadIndex, cmpBtn, syncToggles });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}
const sb = loadPage();
await sb.loadIndex();
const P = sb.S.index.programs;
const pick = div => P.find(p => p.division === div && p.shortName);
const SAMPLE = [pick('D1'), pick('D2'), pick('D3')].filter(Boolean);
const disp = p => p.shortName || p.name;
const esc = t => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const labelOf = html => (html.match(/aria-label="([^"]*)"/) || [, null])[1];
const visibleOf = html => html.replace(/^[\s\S]*?>⇄ /, '').replace(/<\/button>$/, '');

test('fixture: a D1, a D2 and a D3 program with a short name exist', () => {
  assert.equal(SAMPLE.length, 3);
});

for (const wide of [false, true]) for (const on of [false, true]) {
  test(`FIX render path (${wide ? 'wide' : 'compact'}, ${on ? 'selected' : 'not selected'}): the accessible name starts with the visible word and names the program`, () => {
    for (const p of SAMPLE) {
      sb.S.compare = on ? [p.slug] : [];
      const html = sb.cmpBtn(p.slug, wide, disp(p));
      const word = on ? 'Comparing' : 'Compare';
      assert.equal(visibleOf(html), word, `${p.division}: visible text`);
      assert.equal(labelOf(html), `${word} ${esc(disp(p))}`, `${p.division}: accessible name`);
      assert.ok(html.includes(`aria-pressed="${on}"`), `${p.division}: aria-pressed kept`);
    }
  });
}

test('GUARD a name with & or \' is escaped in the accessible name, selected or not', () => {
  for (const on of [false, true]) {
    sb.S.compare = on ? ['x'] : [];
    const html = sb.cmpBtn('x', false, "Texas A&M O'Brien");
    assert.equal(labelOf(html), `${on ? 'Comparing' : 'Compare'} Texas A&amp;M O&#39;Brien`);
  }
});

function fakeButton(slug, label) {
  const attrs = { 'aria-pressed': 'false' };
  if (label != null) attrs['aria-label'] = label;
  return { attrs, dataset: { cmp: slug }, textContent: '', classList: { toggle() { }, contains: () => false },
    setAttribute(k, v) { attrs[k] = v; }, getAttribute: k => attrs[k] ?? null, hasAttribute: k => k in attrs };
}

test('FIX refresh path: syncToggles renames the button along with its text, both ways, and keeps aria-pressed', () => {
  for (const p of SAMPLE) {
    const btn = fakeButton(p.slug, `Compare ${disp(p)}`);
    sb.document.querySelectorAll = sel => (sel.includes('data-cmp') ? [btn] : []);
    sb.S.compare = [p.slug]; sb.syncToggles();
    assert.equal(btn.textContent, '⇄ Comparing');
    assert.equal(btn.attrs['aria-label'], `Comparing ${disp(p)}`, `${p.division}: selected`);
    assert.equal(btn.attrs['aria-pressed'], 'true');
    sb.S.compare = []; sb.syncToggles();
    assert.equal(btn.textContent, '⇄ Compare');
    assert.equal(btn.attrs['aria-label'], `Compare ${disp(p)}`, `${p.division}: deselected`);
    assert.equal(btn.attrs['aria-pressed'], 'false');
  }
});

test('GUARD a button rendered without a name gets none from the refresh path', () => {
  const btn = fakeButton(SAMPLE[0].slug, null);
  sb.document.querySelectorAll = sel => (sel.includes('data-cmp') ? [btn] : []);
  sb.S.compare = [SAMPLE[0].slug]; sb.syncToggles();
  assert.ok(!('aria-label' in btn.attrs));
});
