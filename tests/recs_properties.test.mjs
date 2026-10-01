// The recommender's release gates as property checks (issue #400, plan §5), over every dev scenario and 1,000
// seeded random preference sets against the frozen catalog. Offline. The facts each gate checks against are
// recomputed here from the raw rows (independentFacts), not taken from recs.js.
//
// Gates covered here (ranker level): zero must-have violations in Confirmed; unknown must -> Need verification,
// never dropped (every program accounted for exactly once); fixed-denominator scoring; every reason's value is
// the row's fact and carries a source; no reason or tradeoff from an unknown; determinism; the same order for
// shuffled input; stable ties; hide then Undo gives the identical result; mutating RPI, THE rank, roster size or
// commitments leaves the output byte-identical. "Clear leaves no cd.recs" is a page gate (PR 5).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { R, CATALOG, SCENARIOS, catalogDocs, filterPredicate, independentFacts, rng, shuffle } from './recs_helpers.mjs';

const RANDOM_SETS = 1000;
const C = CATALOG.constants;
const ENUMS = R.enums(C);
const CONFERENCES = [...new Set(CATALOG.programs.map(p => p.conference))].sort();
const SLUGS = CATALOG.programs.map(p => p.slug);

function randomCase(rand) {
  const pick = arr => arr[Math.floor(rand() * arr.length)];
  const subset = (arr, max = arr.length) => shuffle(arr, rand).slice(0, 1 + Math.floor(rand() * Math.min(max, arr.length)));
  const prefs = { v: 1 };
  for (const c of R.CATEGORIES) {
    const r = rand();
    if (r < 0.3) continue;                                       // absent: skip
    const mode = r < 0.33 ? pick(['must', 'love', 'skip']) : pick(R.MODES[c].filter(m => m !== 'skip').concat('prefer'));
    const values = subset(ENUMS[c]);
    if (rand() < 0.05) values.push('retired-value');             // a removed enum value now and then
    prefs[c] = { mode, values };
  }
  const filters = {};
  if (rand() < 0.4) {
    if (rand() < 0.5) filters.region = subset(ENUMS.region, 3);
    if (rand() < 0.5) filters.division = subset(ENUMS.division, 2);
    if (rand() < 0.3) filters.conf = subset(CONFERENCES, 4);
  }
  const hidden = rand() < 0.5 ? subset(SLUGS, 5) : [];
  if (rand() < 0.1) hidden.push('a-program-no-longer-listed');
  return { prefs, filters, hidden };
}

const CASES = (() => {
  const rand = rng(400);
  const out = SCENARIOS.scenarios.map(s => ({ id: s.id, prefs: s.prefs, filters: s.filters, hidden: s.hidden }));
  for (let i = 0; i < RANDOM_SETS; i++) out.push({ id: `random-${i}`, ...randomCase(rand) });
  return out;
})();

const DOCS = catalogDocs();
const run = (c, docs = DOCS, extra = {}) => R.rank({ ...docs, prefs: c.prefs, filter: filterPredicate(c.filters), hidden: c.hidden, ...extra });

function checkInvariants(c, res) {
  const where = c.id;
  assert.equal(res.error, undefined, where);
  const clean = R.validatePrefs(c.prefs, C).prefs;
  assert.equal(res.active, R.isActive(clean), where);
  if (!res.active) return 0;
  const filter = filterPredicate(c.filters) || (() => true);
  const hidden = new Set(c.hidden);
  const rowBy = new Map(CATALOG.programs.map(p => [p.slug, p]));
  const facts = slug => independentFacts(rowBy.get(slug), CATALOG.fit[slug], C);
  const answered = R.CATEGORIES.filter(k => clean[k].mode !== 'skip');
  const musts = answered.filter(k => clean[k].mode === 'must');
  const prefers = answered.filter(k => clean[k].mode === 'prefer');

  // Every program is accounted for exactly once.
  let byFilter = 0, byMust = 0, hid = 0;
  const expectGroup = new Map();
  for (const p of CATALOG.programs) {
    if (!filter(p)) { byFilter++; continue; }
    const f = facts(p.slug);
    const fail = musts.some(k => f[k] !== null && !clean[k].values.includes(f[k]));
    if (fail) { byMust++; continue; }
    if (hidden.has(p.slug)) { hid++; continue; }
    expectGroup.set(p.slug, musts.some(k => f[k] === null) ? 'nv' : 'confirmed');
  }
  assert.deepEqual([res.excluded.byFilter, res.excluded.byMustHave, res.excluded.hidden], [byFilter, byMust, hid], `${where}: layer counts`);
  assert.equal(res.confirmed.length + res.needVerification.length + byFilter + byMust + hid, CATALOG.programs.length, `${where}: partition`);
  for (const [g, items] of [['confirmed', res.confirmed], ['nv', res.needVerification]]) {
    for (const it of items) assert.equal(expectGroup.get(it.slug), g, `${where}: ${it.slug} belongs in ${expectGroup.get(it.slug)}, listed in ${g}`);
  }
  assert.equal(new Set([...res.confirmed, ...res.needVerification].map(x => x.slug)).size, expectGroup.size, `${where}: no program dropped or duplicated`);

  for (const it of [...res.confirmed, ...res.needVerification]) {
    const f = facts(it.slug);
    const e = CATALOG.fit[it.slug];
    // Zero must-have violations in Confirmed; Need verification has an unknown must and no known miss.
    if (it.mustHave === 'pass') for (const k of musts) assert.ok(clean[k].values.includes(f[k]), `${where}: ${it.slug} violates must ${k}`);
    else {
      assert.equal(it.mustHave, 'unknown');
      assert.ok(musts.some(k => f[k] === null), `${where}: ${it.slug} in Need verification without an unknown must`);
    }
    // Fixed denominator: of = every answered prefer category, unknowns included; matched = known matches only.
    assert.equal(it.of, prefers.length, `${where}: ${it.slug} denominator`);
    assert.equal(it.matched, prefers.filter(k => f[k] !== null && clean[k].values.includes(f[k])).length, `${where}: ${it.slug} matched`);
    assert.equal(it.score, prefers.length ? it.matched / prefers.length : 0);
    // Reasons: a known match, the row's own value, with a source; at most three.
    assert.ok(it.reasons.length <= R.MAX_REASONS);
    for (const r of it.reasons) {
      assert.notEqual(r.value, null, `${where}: a reason from an unknown`);
      assert.equal(r.value, f[r.category], `${where}: ${it.slug} ${r.category} reason value`);
      assert.ok(clean[r.category].values.includes(r.value));
      assert.ok(r.source && typeof r.source.name === 'string' && r.source.name.length > 0, `${where}: reason without a source`);
      if (r.category === 'region' || r.category === 'size') assert.equal(r.source.asOf, e?.asOf?.[0] ?? null);
      if (r.category === 'climate') assert.equal(r.source.asOf, e.asOf[1]);
      if (r.category === 'size') assert.equal(r.detail.undergrad, rowBy.get(it.slug).undergradEnrollment);
      if (r.category === 'climate') assert.equal(r.detail.coldMonthMeanF, e.coldMonthMeanF);
      assert.equal(typeof R.reasonText(r), 'string');
    }
    const matches = answered.filter(k => f[k] !== null && clean[k].values.includes(f[k])).length;
    assert.equal(it.reasons.length, Math.min(matches, R.MAX_REASONS), `${where}: ${it.slug} reason count`);
    if (it.tradeoff) {
      assert.notEqual(it.tradeoff.value, null, `${where}: a tradeoff from an unknown`);
      assert.equal(it.tradeoff.value, f[it.tradeoff.category]);
      assert.ok(!clean[it.tradeoff.category].values.includes(it.tradeoff.value));
      assert.equal(it.tradeoff.mode, 'prefer');
    } else {
      assert.ok(!prefers.some(k => f[k] !== null && !clean[k].values.includes(f[k])), `${where}: ${it.slug} has a known prefer miss but no tradeoff`);
    }
    // Every unknown is shown, never silently dropped.
    assert.deepEqual(it.unknowns.map(u => u.category), answered.filter(k => f[k] === null), `${where}: ${it.slug} unknowns`);
  }

  // Order: score descending, then displayed name, then slug - and ties keep that order.
  for (const items of [res.confirmed, res.needVerification]) {
    for (let i = 1; i < items.length; i++) assert.ok(R.compareRanked(items[i - 1], items[i]) < 0, `${where}: order at ${i}`);
  }
  return res.confirmed.length + res.needVerification.length;
}

test(`invariants hold on every scenario and ${RANDOM_SETS} random preference sets`, () => {
  let listed = 0, active = 0, nv = 0;
  for (const c of CASES) {
    const res = run(c);
    listed += checkInvariants(c, res);
    if (res.active) active++;
    nv += res.active ? res.needVerification.length : 0;
  }
  // The random sets must actually exercise the gates, or the checks above could pass vacuously.
  assert.ok(active > RANDOM_SETS * 0.6, `active sets: ${active}`);
  assert.ok(nv > 0, 'some sets reach Need verification');
  assert.ok(listed > 100000, `programs checked: ${listed}`);
});

test('determinism, shuffled input, hide then Undo, and no hidden signals: byte-identical results', () => {
  const rand = rng(1011);
  for (const c of CASES) {
    const base = JSON.stringify(run(c));
    assert.equal(JSON.stringify(run(c)), base, `${c.id}: deterministic`);

    const shuffledFit = Object.fromEntries(shuffle(Object.entries(DOCS.fit.fit), rand));
    const shuffled = { list: { ...DOCS.list, programs: shuffle(DOCS.list.programs, rand) }, fit: { ...DOCS.fit, fit: shuffledFit } };
    assert.equal(JSON.stringify(run(c, shuffled)), base, `${c.id}: shuffled input`);

    const extra = SLUGS[Math.floor(rand() * SLUGS.length)];
    const hiddenMore = run({ ...c, hidden: [...c.hidden, extra] });
    if (hiddenMore.active) {
      assert.ok(![...hiddenMore.confirmed, ...hiddenMore.needVerification].some(x => x.slug === extra), `${c.id}: hidden ${extra} not listed`);
    }
    assert.equal(JSON.stringify(run(c)), base, `${c.id}: Undo restores the identical result`);

    const noisy = { ...DOCS, list: { ...DOCS.list, programs: DOCS.list.programs.map(p => ({ ...p,
      rpi: Math.floor(rand() * 400), rpiHistory: [{ season: 2025, rank: Math.floor(rand() * 400) }], academicRank: Math.floor(rand() * 500),
      rosterSize: Math.floor(rand() * 40), commitmentsByYear: { 2027: Math.floor(rand() * 9) }, admissionRate: rand(),
      tuitionOutOfState: Math.floor(rand() * 7e4) })) } };
    assert.equal(JSON.stringify(run(c, noisy)), base, `${c.id}: RPI, THE rank, roster and commitments never reach the ranker`);
  }
  assert.equal(JSON.stringify(DOCS), JSON.stringify(catalogDocs()), 'rank never mutates its input');
});
