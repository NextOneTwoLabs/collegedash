// Issue #151: a head coach taken from Wikipedia says so, wherever the page shows the name.
//
//     node --test tests/head_coach_source.test.mjs
//
// build.py publishes the school's own head coach (program.headCoach.source 'athletics'). Only when the school names no
// head coach does it fall back to the Wikipedia infobox (source 'wikipedia'), whose name carries no date and cannot be
// checked against the school. The Overview glance, the Staff tab and the Compare row then say "from Wikipedia; the
// school's site names no head coach"; a school-sourced coach reads exactly as before.
//
// The inline <script> of public/index.html runs in a `vm` against a stub DOM (as tests/honors_record.test.mjs does),
// with two profiles generated from a committed one and given made-up coaches (no real people). Nothing leaves the
// process. The mutation check is built in: the same views rendered from a copy of the page whose coachFromWiki()
// returns '' must fail, which proves every view gets its note from that one helper.
//
// HEAD_COACH_SOURCE_HTML (optional) points at another copy of index.html.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const PAGE = process.env.HEAD_COACH_SOURCE_HTML || path.join(PUBLIC, 'index.html');
const clone = (v) => JSON.parse(JSON.stringify(v));
const readJSON = (rel) => JSON.parse(fs.readFileSync(path.join(PUBLIC, rel), 'utf8'));
const NOTE = "the school's site names no head coach";

function makeElement(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0,
    dataset: {}, style: {}, classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null, matches: () => false, focus() { }, contains: () => false,
  };
}

function loadPage(html, files) {
  const els = new Map();
  const bySelector = (sel) => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const store = new Map();
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
        else if (sub === 'camps') u = 'data/camps/index.json';
        else if (sub === 'trends') u = 'data/trends/index.json';
        else if (sub === 'commitments') u = 'data/commitments/index.json';
        else if (sub === 'status') u = 'archive/refresh-state.json';
      }
      if (files[u]) return ok(files[u]);
      if (!u.startsWith('data/') && !u.startsWith('archive/')) return ok({}, 404);
      const p = path.join(PUBLIC, u);
      return fs.existsSync(p) ? ok(JSON.parse(fs.readFileSync(p, 'utf8'))) : ok({}, 404);
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(html, 'utf8').split(/\r?\n/);
  const a = lines.findIndex((l) => l.trim() === '<script>'), b = lines.findIndex((l) => l.trim() === '</script>');
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ${JSON.stringify(['S', 'renderProfile', 'renderCompare', 'loadIndex'])}) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  const $ = (sel) => sandbox.document.querySelector(sel);
  return { sb: sandbox, app: () => $('#app').innerHTML, tab: () => $('#tab').innerHTML };
}

// Two made-up programs built from a committed D1 profile: one whose coach is the school's, one whose coach is Wikipedia's.
function fixtures() {
  const index = clone(readJSON('data/programs/index.json'));
  const baseRow = index.programs.find((r) => r.division === 'D1');
  const base = readJSON(`data/programs/${baseRow.slug}.json`);
  const make = (slug, headCoach, extra = {}) => {
    const p = clone(base);
    Object.assign(p, { slug, name: `${slug} Test University`, shortName: `${slug} TU` });
    p.program = { ...p.program, headCoach, coaches: [], supportStaff: [], ...extra };
    p.links = { ...p.links, wikipedia: 'https://en.wikipedia.org/wiki/Example_Test_University_soccer' };
    const row = { ...clone(baseRow), slug, name: p.name, shortName: p.shortName, headCoach: headCoach.name };
    return { p, row };
  };
  const school = make('school-coach', { name: 'Avery Example', source: 'athletics', title: 'Head Coach', since: null, seasons: null, bioUrl: null, social: {} });
  const wiki = make('wiki-coach', { name: 'Casey Placeholder', source: 'wikipedia', title: null, since: null, seasons: null, bioUrl: null, social: {} },
    { _meta: { ...base.program._meta, athletics: null } });
  index.programs = [...index.programs, school.row, wiki.row];
  return { files: { 'data/programs/index.json': index, 'data/programs/school-coach.json': school.p, 'data/programs/wiki-coach.json': wiki.p } };
}

// The text of every view that shows a head coach, for one program.
async function views(html) {
  const { files } = fixtures();
  const pg = loadPage(html, files);
  await pg.sb.loadIndex();
  const out = {};
  for (const slug of ['school-coach', 'wiki-coach']) {
    await pg.sb.renderProfile(slug, 'overview');
    out[`${slug}/overview`] = pg.app() + pg.tab();
    await pg.sb.renderProfile(slug, 'staff');
    out[`${slug}/staff`] = pg.tab();
  }
  pg.sb.S.compare = ['school-coach', 'wiki-coach'];
  pg.sb.S.profiles = pg.sb.S.profiles || {};
  await pg.sb.renderCompare();
  const cmp = pg.app();
  const row = cmp.slice(cmp.indexOf('Head coach'), cmp.indexOf('</tr>', cmp.indexOf('Head coach')));
  out['compare/head coach row'] = row;
  return out;
}

function problems(v) {
  const bad = [];
  for (const view of ['overview', 'staff']) {
    const w = v[`wiki-coach/${view}`], s = v[`school-coach/${view}`];
    if (!w.includes('Casey Placeholder')) bad.push(`wiki-coach/${view}: the coach is not shown`);
    if (!w.includes(NOTE) || !/>Wikipedia<\/a>/.test(w)) bad.push(`wiki-coach/${view}: no "from Wikipedia" note`);
    if (!s.includes('Avery Example')) bad.push(`school-coach/${view}: the coach is not shown`);
    if (s.includes(NOTE)) bad.push(`school-coach/${view}: a school coach is labelled as Wikipedia's`);
  }
  const row = v['compare/head coach row'];
  const cells = row.split('<td').slice(1);
  const wikiCell = cells.find((c) => c.includes('Casey Placeholder')) || '', schoolCell = cells.find((c) => c.includes('Avery Example')) || '';
  if (!wikiCell.includes(NOTE)) bad.push('compare: the Wikipedia coach has no note');
  if (!schoolCell || schoolCell.includes(NOTE)) bad.push('compare: the school coach is missing or labelled');
  return bad;
}

test('#151 a Wikipedia head coach is labelled in Overview, Staff and Compare; a school head coach is not', async () => {
  assert.deepEqual(problems(await views(PAGE)), []);
});

test('#151 mutation: a page whose coachFromWiki() returns nothing fails every Wikipedia check', async () => {
  const html = fs.readFileSync(PAGE, 'utf8');
  const mutated = html.replace(/const coachFromWiki = \(hc, p\) =>/, "const coachFromWiki = (hc, p) => '' && ");
  assert.notEqual(mutated, html, 'the helper was not found to mutate');
  const tmp = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hc151-')), 'index.html');
  fs.writeFileSync(tmp, mutated);
  try {
    const bad = problems(await views(tmp));
    for (const want of ['wiki-coach/overview: no "from Wikipedia" note', 'wiki-coach/staff: no "from Wikipedia" note',
      'compare: the Wikipedia coach has no note']) assert.ok(bad.includes(want), `the mutated page passed: ${want}`);
  } finally {
    fs.rmSync(path.dirname(tmp), { recursive: true, force: true });
  }
});
