// The page harness shared by the recommendations page suites (issue #400): tests/recs_form.test.mjs (PR 3) and
// tests/recs_results.test.mjs (PR 4). Not a suite itself: no node:test import.
//
// Same mechanism as tests/ask_page.test.mjs: the page's inline <script> runs in a `vm` against a stub DOM, and fetch
// is a stub that serves public/ and answers api/status as each test says. A <script src="recs.js"> the page appends
// is run from public/recs.js in the same context and recorded as a request. /api/v1/fit is served from the frozen
// catalog (tests/fixtures/recs/catalog.json), stamped with the served index's `updated` as one build would be, unless
// a test asks for it to fail or disagree. Nothing leaves the process.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const PUBLIC = path.join(HERE, '..', 'public');
export const HTML = process.env.RECS_PAGE_HTML || path.join(PUBLIC, 'index.html');
export const RECS_JS = fs.readFileSync(path.join(PUBLIC, 'recs.js'), 'utf8');
export const CATALOG = JSON.parse(fs.readFileSync(path.join(HERE, 'fixtures', 'recs', 'catalog.json'), 'utf8'));
const INDEX_UPDATED = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8')).updated;
export const FIT = { updated: INDEX_UPDATED, fitTaxonomy: CATALOG.fitTaxonomy, constants: CATALOG.constants, sources: CATALOG.sources, fit: CATALOG.fit };
export const LOAD_REQUESTS = ['/api/v1/programs', '/api/v1/status', 'api/status', 'api/ask/status'];
export const ON = { local: false, recs: true };

// The element the page last focused (the stub DOM has no focus of its own). Its _name is the selector it was found by.
export const FOCUS = { el: null };
export function makeElement(name) {
  const listeners = {}, attrs = {};
  return {
    _name: name, _listeners: listeners, _attrs: attrs, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute(k, v) { attrs[k] = String(v); }, getAttribute: (k) => attrs[k] ?? null,
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    removeEventListener() { }, querySelector: (sel) => makeElement(sel), querySelectorAll: () => [], closest: () => null,
    matches: () => false, focus() { FOCUS.el = this; }, contains: () => false,
  };
}
const HANDLES = ['S', 'renderSidebar', 'renderList', 'loadIndex', 'REGIONS', 'recsOpen', 'recsClose', 'recsApply', 'recsReset', 'recsToggleValue',
  'recsSetUse', 'recsSetImportance', 'recsSummary', 'renderRecsPanel', 'recsShowRecommended', 'recsUnfilter', 'setSort', 'filteredPrograms',
  'displayName', 'matchesFilters', 'recsSheetState', 'recsHide', 'recsUndo', 'recsRestore', 'recsRemoveStale', 'recsClearAll',
  'recsEditPreference', 'renderRecsToast', 'programBySlug'];

// `status`: the api/status body, or null for a 404. `storage`: initial localStorage entries, or 'throws'.
// `width`: window.innerWidth. `recsJs`: false makes the recs.js script fail to load.
// `fit`: 'ok', 'missing' (404), 'network' (fetch rejects), 'updating' (always another build) or 'updating-once'.
export function loadPage({ html = HTML, status = { local: false }, storage = {}, width = 1400, recsJs = true, fit = 'ok' } = {}) {
  const els = new Map();
  const bySelector = (sel) => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map(Object.entries(storage === 'throws' ? {} : storage));
  const throwing = storage === 'throws';
  const requests = [];
  let fitServed = 0;
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, WeakMap, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent, Error, TypeError,
    location: { hash: '', search: '', replace(h) { this.hash = h; } },
    history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: {
      getItem: (k) => { if (throwing) throw new Error('SecurityError'); return store.has(k) ? store.get(k) : null; },
      setItem: (k, v) => { if (throwing) throw new Error('QuotaExceededError'); store.set(k, String(v)); },
      removeItem: (k) => { if (throwing) throw new Error('SecurityError'); store.delete(k); },
    },
    innerWidth: width, addEventListener() { },
    fetch: async (url) => {
      requests.push(String(url));
      const ok = (body, st = 200) => ({ ok: st < 400, status: st, async json() { return JSON.parse(JSON.stringify(body)); } });
      if (url === 'api/status' || url === '/api/status') return status ? ok(status) : ok({}, 404);
      if (url === 'api/ask/status' || url === '/api/ask/status') return { ok: false, status: 0, type: 'opaqueredirect', async json() { throw new SyntaxError('opaque'); } };
      if (url === '/api/v1/fit') {
        fitServed += 1;
        if (fit === 'network') throw new TypeError('Failed to fetch');
        if (fit === 'missing') return ok({ error: 'not found' }, 404);
        if (fit === 'updating' || (fit === 'updating-once' && fitServed === 1)) return ok({ ...FIT, updated: '1999-01-01T00:00:00Z' });
        return ok(FIT);
      }
      let u = String(url).replace(/^\//, '');
      if (u.startsWith('api/v1/')) {
        const sub = u.slice('api/v1/'.length);
        if (sub === 'programs') u = 'data/programs/index.json';
        else if (sub === 'status') u = 'archive/refresh-state.json';
        else u = `missing/${sub}`;
      }
      const p = path.join(PUBLIC, u);
      return fs.existsSync(p) ? ok(JSON.parse(fs.readFileSync(p, 'utf8'))) : ok({}, 404);
    },
  };
  const head = makeElement('head');
  head.appendChild = (el) => {
    requests.push(el.src);
    setTimeout(() => {
      if (el.src !== 'recs.js' || !sandbox.__recsJsOk) return el.onerror && el.onerror(new Error('load failed'));
      vm.runInContext(RECS_JS, sandbox, { filename: 'public/recs.js' });
      el.onload && el.onload();
    }, 0);
  };
  sandbox.document = { documentElement: makeElement('html'), body: makeElement('body'), head, querySelector: bySelector, querySelectorAll: () => [],
    addEventListener() { }, createElement: makeElement, activeElement: null };
  sandbox.window = sandbox; sandbox.globalThis = sandbox; sandbox.__recsJsOk = recsJs;
  const lines = fs.readFileSync(html, 'utf8').split(/\r?\n/);
  const a = lines.findIndex((l) => l.trim() === '<script>'), b = lines.findIndex((l) => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(HANDLES)}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  const $ = (sel) => sandbox.document.querySelector(sel);
  return { sb: sandbox, $, requests, store, sidebar: () => $('#sidebar').innerHTML, panel: () => $('#recsPanel'), app: () => $('#app').innerHTML,
    panelHtml: () => $('#recsPanelBody').innerHTML + $('#recsStatus').textContent };
}
export const settle = async () => { for (let i = 0; i < 40; i++) await new Promise((r) => setTimeout(r, 0)); };
export async function ready(opts) {
  const pg = loadPage(opts);
  await settle();
  if (!pg.sb.S.index) await pg.sb.loadIndex(); // the page's own first route loads it; this only waits for it
  await settle();
  assert.ok(pg.sb.S.index?.divisions, 'the index never loaded');
  pg.sb.renderSidebar();
  return pg;
}
export async function open(pg) { await pg.sb.recsOpen(); await settle(); assert.equal(pg.panel().hidden, false, 'the panel did not open'); }
export const plain = (v) => JSON.parse(JSON.stringify(v));
