// Compare: cost of attendance follows the "I live in" residency for public schools (issue #201).
//
//     node --test tests/compare_coa_residency.test.mjs
//
// Same mechanism as tests/condition_chips.test.mjs: the inline <script> is pulled out of public/index.html and
// run in a `vm` against a stub DOM, and renderCompare() is rendered for real. Expectations come from the
// profile JSON (school.costOfAttendance / tuitionInState / tuitionOutOfState, College Scorecard), never from
// the page's own helpers, so a wrong helper cannot agree with itself.
//
// What this proves, on the shipped UCLA (public, CA) and Stanford (private, CA) profiles plus synthetic ones:
//   - public, out-of-state: the Cost of attendance cell is published COA - in-state + out-of-state tuition,
//     labelled an estimate, and is >= the out-of-state tuition shown in the Tuition row;
//   - public, in-state: the published COA, labelled in-state, >= in-state tuition; and out-of-state > in-state;
//   - "(not set)": both figures, the out-of-state one marked (est.);
//   - private: the published figure, identical for every residency and with no residency label;
//   - missing fields show '—', and a public COA below its own in-state tuition is not shown at all.
// Issue #299: the Profile page's School tab (tabSchool) shows the same residency treatment, checked the same ways.
// What it cannot prove: layout at 400 px and the tooltip wording as read in a browser (checked by hand).
// COA_TEST_HTML (optional) points at another copy of index.html, to show these checks failing on a mutation.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(HERE, '..', 'public');
const HTML = process.env.COA_TEST_HTML || path.join(PUBLIC, 'index.html');
const readJSON = f => JSON.parse(fs.readFileSync(path.join(PUBLIC, f), 'utf8'));
const INDEX = readJSON('data/programs/index.json');
const UCLA = readJSON('data/programs/ucla.json'), STANFORD = readJSON('data/programs/stanford.json');

function makeElement(name) {
  return {
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, dataset: {}, style: {},
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => makeElement('child'), querySelectorAll: () => [], closest: () => null, matches: () => false, focus() { }, contains: () => false,
  };
}
// extra: { slug: schoolOverrides } makes synthetic programs cloned from UCLA's profile with those school fields.
function loadPage(extra = {}) {
  const els = new Map();
  const bySelector = sel => { if (!els.has(sel)) els.set(sel, makeElement(sel)); return els.get(sel); };
  const index = JSON.parse(JSON.stringify(INDEX));
  const serve = { '/api/v1/programs': index, '/api/v1/programs/ucla': UCLA, '/api/v1/programs/stanford': STANFORD };
  const uclaRow = index.programs.find(p => p.slug === 'ucla');
  for (const [slug, school] of Object.entries(extra)) {
    index.programs.push({ ...uclaRow, slug, name: slug, shortName: slug });
    serve[`/api/v1/programs/${slug}`] = { ...UCLA, slug, name: slug, shortName: slug, school: { ...UCLA.school, ...school } };
  }
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: { documentElement: makeElement('html'), body: makeElement('body'), querySelector: bySelector,
      querySelectorAll: () => [], addEventListener() { }, createElement: makeElement },
    location: { hash: '', replace(h) { this.hash = h; } }, history: { replaceState() { } },
    matchMedia: () => ({ matches: false }),
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    innerWidth: 1400, addEventListener() { },
    fetch: async url => Object.prototype.hasOwnProperty.call(serve, url)
      ? { ok: true, status: 200, async json() { return JSON.parse(JSON.stringify(serve[url])); } }
      : { ok: false, status: 404, async json() { throw new Error('404'); } },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const lines = fs.readFileSync(HTML, 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>'), b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'index.html: could not find the inline <script>');
  const src = lines.slice(a + 1, b).join('\n') + `\n;for (const k of ['S','renderCompare','tabSchool']) { try { globalThis[k] = eval(k); } catch { } }\n`;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return sandbox;
}
// Render Compare for `slugs` at residency `home`; return { coa: [cell html], tuition: [cell html] } in column order.
async function compare(sb, slugs, home) {
  sb.S.compare = slugs; sb.S.residency = home; sb.S.profiles = sb.S.profiles || {};
  await sb.renderCompare();
  const html = sb.document.querySelector('#app').innerHTML;
  const row = label => {
    const m = new RegExp(`<tr><th>${label}</th>((?:<td>[\\s\\S]*?</td>)+)</tr>`).exec(html);
    assert.ok(m, `Compare has no "${label}" row`);
    return [...m[1].matchAll(/<td>([\s\S]*?)<\/td>/g)].map(x => x[1]);
  };
  return { coa: row('Cost of attendance'), tuition: row('Tuition / yr') };
}
const usd = n => '$' + Number(n).toLocaleString();
const dollars = html => [...html.matchAll(/\$([\d,]+)/g)].map(m => Number(m[1].replace(/,/g, '')));
const text = html => html.replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();

const U = UCLA.school, S_ = STANFORD.school;
test('fixtures are what the checks need: UCLA public in CA with COA below out-of-state tuition; Stanford private', () => {
  assert.equal(U.ownership, 'Public'); assert.equal(U.state, 'CA');
  assert.ok(U.costOfAttendance < U.tuitionOutOfState, 'UCLA no longer reproduces #201; pick another public');
  assert.ok(U.tuitionOutOfState > U.tuitionInState);
  assert.notEqual(S_.ownership, 'Public'); assert.ok(S_.costOfAttendance != null);
});

test('public, out-of-state: COA = published - in-state + out-of-state tuition, labelled an estimate, >= tuition shown', async () => {
  const sb = loadPage();
  const { coa, tuition } = await compare(sb, ['ucla'], 'NY');
  const want = U.costOfAttendance - U.tuitionInState + U.tuitionOutOfState;
  assert.deepEqual(dollars(coa[0]), [want]);
  assert.match(text(coa[0]), /out-of-state, est\./);
  assert.deepEqual(dollars(tuition[0]), [U.tuitionOutOfState], 'Tuition row should show out-of-state tuition');
  assert.ok(dollars(coa[0])[0] >= dollars(tuition[0])[0], 'COA shown is below the tuition shown');
});

test('public, in-state: published COA labelled in-state, >= in-state tuition, and below the out-of-state COA', async () => {
  const sb = loadPage();
  const cal = await compare(sb, ['ucla'], 'CA');
  assert.deepEqual(dollars(cal.coa[0]), [U.costOfAttendance]);
  assert.match(text(cal.coa[0]), /in-state/); assert.doesNotMatch(text(cal.coa[0]), /out-of-state/);
  assert.ok(dollars(cal.coa[0])[0] >= dollars(cal.tuition[0])[0]);
  const ny = await compare(sb, ['ucla'], 'NY');
  assert.ok(dollars(ny.coa[0])[0] > dollars(cal.coa[0])[0], 'out-of-state COA should exceed in-state COA');
});

test('public, residency not set: both figures, the out-of-state one marked (est.)', async () => {
  const sb = loadPage();
  const { coa } = await compare(sb, ['ucla'], '');
  assert.deepEqual(dollars(coa[0]), [U.costOfAttendance, U.costOfAttendance - U.tuitionInState + U.tuitionOutOfState]);
  assert.match(text(coa[0]), /in \/ .* out \(est\.\)/);
});

test('private school: published figure, the same for every residency, no residency label', async () => {
  const sb = loadPage();
  for (const home of ['', 'CA', 'NY']) {
    const { coa } = await compare(sb, ['stanford', 'ucla'], home);
    assert.equal(coa[0], usd(S_.costOfAttendance), `Stanford COA changed at residency "${home}"`);
  }
});

test("missing fields show '—'; a public COA below its own in-state tuition is never shown", async () => {
  const sb = loadPage({
    'no-coa': { costOfAttendance: null },
    'no-out': { tuitionOutOfState: null },
    'coa-below-in': { costOfAttendance: 10000, tuitionInState: 15000, tuitionOutOfState: 40000 },
    'priv-no-coa': { ownership: 'Private nonprofit', costOfAttendance: null },
  });
  const slugs = ['no-coa', 'no-out', 'coa-below-in', 'priv-no-coa'];
  const ny = await compare(sb, slugs, 'NY');
  assert.equal(ny.coa[0], '—'); assert.equal(ny.coa[3], '—');
  assert.deepEqual(dollars(ny.coa[1]), [], 'no out-of-state tuition: the in-state COA must not stand in for it');
  assert.match(text(ny.coa[1]), /^— /);
  assert.deepEqual(dollars(ny.coa[2]), []);
  const ca = await compare(sb, slugs, 'CA');
  assert.equal(ca.coa[0], '—'); assert.equal(ca.coa[3], '—');
  assert.deepEqual(dollars(ca.coa[1]), [U.costOfAttendance]);
  assert.equal(text(ca.coa[2]), '—', 'a COA below the in-state tuition it includes is shown');
});

// Issue #299: the Profile page's School tab shows the same residency treatment as Compare. Residency is the one
// "I live in" choice (S.residency), set on Compare and remembered.
async function profileCoa(sb, profile, home) {
  sb.S.residency = home;
  const html = await sb.tabSchool(profile);
  const m = /<tr><th>Cost of attendance<\/th><td>([\s\S]*?)<\/td><\/tr>/.exec(html);
  assert.ok(m, 'Profile has no "Cost of attendance" row');
  return m[1];
}
test('#299 Profile, public: in-state label, out-of-state estimate labelled est. with its tooltip, both when unset', async () => {
  const sb = loadPage();
  const est = U.costOfAttendance - U.tuitionInState + U.tuitionOutOfState;
  const ca = await profileCoa(sb, UCLA, 'CA');
  assert.deepEqual(dollars(ca), [U.costOfAttendance]);
  assert.match(text(ca), /in-state/); assert.doesNotMatch(text(ca), /out-of-state|est\./);
  const ny = await profileCoa(sb, UCLA, 'NY');
  assert.deepEqual(dollars(ny), [est]);
  assert.match(text(ny), /out-of-state, est\./);
  assert.match(ny, /title="Estimate: [^"]*in-state tuition[^"]*out-of-state tuition/, 'the estimate has no tooltip saying how it is built');
  assert.ok(dollars(ny)[0] >= U.tuitionOutOfState, 'out-of-state COA shown below out-of-state tuition');
  const unset = await profileCoa(sb, UCLA, '');
  assert.deepEqual(dollars(unset), [U.costOfAttendance, est]);
  assert.match(text(unset), /in \/ .* out \(est\.\)/);
});
test("#299 Profile, private: the published figure at every residency, no label; missing fields show '—'", async () => {
  const sb = loadPage();
  for (const home of ['', 'CA', 'NY']) assert.equal(await profileCoa(sb, STANFORD, home), usd(S_.costOfAttendance), `Stanford COA changed at residency "${home}"`);
  const noCoa = { ...UCLA, school: { ...U, costOfAttendance: null } };
  for (const home of ['', 'CA', 'NY']) assert.equal(await profileCoa(sb, noCoa, home), '—');
  const noOut = { ...UCLA, school: { ...U, tuitionOutOfState: null } };
  assert.deepEqual(dollars(await profileCoa(sb, noOut, 'NY')), [], 'no out-of-state tuition: the in-state COA must not stand in for it');
});
