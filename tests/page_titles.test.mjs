// Issue #17: the tab title was always "College Soccer · nextonetwo", so browser tabs, history, bookmarks and screen
// readers could not tell pages apart. Every route now sets its own: "<page> · College Soccer", a program by what the
// reader sees (shortName || name); the unfiltered program list keeps the site's own title.
//
//     node --test tests/page_titles.test.mjs
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM with the published data under public/;
// each route goes through the page's own route(). Expected names come from index.json.
//
// PAGE_TITLES_TEST_HTML (optional) points at another copy of index.html, so the page from before this change can be
// run through these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.PAGE_TITLES_TEST_HTML || path.join(PUBLIC, 'index.html');
const INDEX = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'programs', 'index.json'), 'utf8'));
const SITE = 'College Soccer · nextonetwo';

function makeElement(name) {
  return { _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, dataset: {}, style: {},
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false }, setAttribute() { }, getAttribute: () => null,
    removeAttribute() { }, hasAttribute: () => false,
    addEventListener() { }, removeEventListener() { }, querySelector: () => makeElement('child'), querySelectorAll: () => [],
    closest: () => null, matches: () => false, focus() { }, contains: () => false };
}
function loadPage() {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const readPublic = url => {
    let rel = url.replace(/^\//, '').replace(/\?.*$/, '');
    if (rel.startsWith('api/v1/')) {
      const sub = rel.slice('api/v1/'.length);
      rel = sub === 'programs' ? 'data/programs/index.json' : sub.startsWith('programs/') ? `data/programs/${sub.slice(9)}.json`
        : sub === 'camps' ? 'data/camps/index.json' : sub === 'trends' ? 'data/trends/index.json'
        : sub === 'commitments' ? 'data/commitments/index.json' : sub === 'status' ? 'archive/refresh-state.json' : rel;
    }
    const p = path.join(PUBLIC, rel);
    return p.startsWith(PUBLIC) && fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
  };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, URLSearchParams, encodeURIComponent, decodeURIComponent,
    document: { title: SITE, documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector,
      querySelectorAll: () => [], createElement: makeElement, addEventListener() { } },
    location: { hash: '', search: '', replace(h) { this.hash = h; } }, history: { replaceState() { } }, matchMedia: () => ({ matches: false }),
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } }, innerWidth: 1400, addEventListener() { },
    fetch: async url => {
      const body = readPublic(String(url));
      return body == null ? { ok: false, status: 404, async json() { throw new Error('404'); } }
        : { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(HTML, 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n') + '\n;Object.assign(globalThis, { S, loadIndex, route });\n';
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}
const sb = loadPage();
const settle = async () => { for (let i = 0; i < 30; i++) await new Promise(r => setTimeout(r, 0)); };
async function visit(hash) { sb.location.hash = hash; sb.route(); await settle(); return sb.document.title; }
const withShort = INDEX.programs.find(p => p.shortName && p.shortName !== p.name && fs.existsSync(path.join(PUBLIC, 'data', 'programs', `${p.slug}.json`)));

test('setup', async () => {
  await sb.loadIndex(); await settle();
  assert.ok(withShort, 'fixture: a program whose shortName differs from its name');
});

test('a program page is titled with the name the reader sees (shortName || name), on every tab', async () => {
  assert.equal(await visit(`#/p/${withShort.slug}`), `${withShort.shortName} · College Soccer`);
  assert.equal(await visit(`#/p/${withShort.slug}/roster`), `${withShort.shortName} · College Soccer`);
  const plain = INDEX.programs.find(p => !p.shortName && fs.existsSync(path.join(PUBLIC, 'data', 'programs', `${p.slug}.json`)));
  if (plain) assert.equal(await visit(`#/p/${plain.slug}`), `${plain.name} · College Soccer`);
});

test('the other routes each have their own title', async () => {
  const seen = new Map();
  for (const [hash, want] of [
    ['#/camps', 'Upcoming ID camps · College Soccer'],
    ['#/trends', 'Pipelines · College Soccer'],
    ['#/compare', 'Compare · College Soccer'],
    ['#/shortlist', 'My shortlist · College Soccer'],
    ['#/faq', 'About the data · College Soccer'],
    ['#/api', 'Data API · College Soccer'],
    ['#/p/no-such-program', 'Not found · College Soccer'],
  ]) {
    const got = await visit(hash);
    assert.equal(got, want, hash);
    seen.set(got, hash);
  }
  assert.equal(seen.size, 7, 'two routes share a title');
});

test('the program list: the site\'s own title unfiltered, the conference when one is chosen', async () => {
  sb.S.filters.conf = [];
  assert.equal(await visit('#/'), SITE);
  assert.equal(await visit('#/c/ACC'), 'ACC · College Soccer');
  assert.equal(await visit('#/c/D2%7CIndependent'), 'Independent (D2) · College Soccer');  // #425's label
  sb.S.filters.conf = [];
  assert.equal(await visit('#/'), SITE, 'back on the unfiltered list, the title did not come back');
});

test('leaving a page sets the next page\'s title (never the previous one\'s)', async () => {
  await visit(`#/p/${withShort.slug}`);
  assert.equal(await visit('#/faq'), 'About the data · College Soccer');
  await visit('#/camps');
  sb.S.filters.conf = [];
  assert.equal(await visit('#/'), SITE);
});
