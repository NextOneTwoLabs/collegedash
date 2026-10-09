// Unit tests for every pure function in public/recs.js, the recommender's ranker (issue #400, PR 2).
// Made-up programs, plus fit-1's real constants from the frozen catalog. Offline: nothing is fetched.
//
// The A-case labels mark the unit-level half of an acceptance case from the plan's table (A2, A3, A7, A8, A10,
// A11); the named A1-A12 tests themselves land in tests/recs_acceptance.test.mjs with PR 7.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { R, CATALOG, row, entry, tinyCatalog, prefs, slugs } from './recs_helpers.mjs';

const C = CATALOG.constants;
const S = CATALOG.sources;
const proj = (r, e = entry()) => R.project(r, e, C);

test('versions and enums are the plan\'s', () => {
  assert.equal(R.RANKER, 'r1');
  assert.equal(R.PREFS_V, 1);
  assert.deepEqual(R.TAXONOMIES, ['fit-1']);
  assert.deepEqual(R.CATEGORIES, ['region', 'division', 'size', 'climate']);
  assert.deepEqual(R.MODES.climate, ['skip', 'prefer'], 'climate is prefer-only (D2)');
  for (const c of ['region', 'division', 'size']) assert.deepEqual(R.MODES[c], ['skip', 'prefer', 'must']);
  const e = R.enums(C);
  assert.deepEqual(e.region, Object.keys(C.regions));
  assert.deepEqual([...e.region].sort(), ['Mid-Atlantic', 'Midwest', 'Northeast', 'South', 'West']);
  assert.deepEqual(e.size, ['lt5k', '5k-15k', 'ge15k']);
  assert.deepEqual(e.climate, ['mild', 'four-season', 'cold']);
  assert.deepEqual(R.enums(null).region, [], 'no constants: no region is valid');
});

test('defaultPrefs skips everything and isActive needs one answered category (A4)', () => {
  const d = R.defaultPrefs();
  assert.deepEqual(d, { v: 1, region: { mode: 'skip', values: [] }, division: { mode: 'skip', values: [] },
                        size: { mode: 'skip', values: [] }, climate: { mode: 'skip', values: [] } });
  assert.equal(R.isActive(d), false);
  assert.equal(R.isActive(null), false);
  assert.equal(R.isActive({ ...d, size: { mode: 'prefer', values: ['lt5k'] } }), true);
  assert.equal(R.isActive({ ...d, region: { mode: 'must', values: ['West'] } }), true);
});

test('validatePrefs keeps what it understands, in taxonomy order, de-duplicated', () => {
  const { prefs: p, issues } = R.validatePrefs(prefs({ region: { mode: 'prefer', values: ['West', 'Northeast', 'West'] },
                                                       size: { mode: 'must', values: ['ge15k', 'lt5k'] } }), C);
  assert.deepEqual(issues, []);
  const order = Object.keys(C.regions);
  assert.deepEqual(p.region.values, ['West', 'Northeast'].sort((a, b) => order.indexOf(a) - order.indexOf(b)));
  assert.deepEqual(p.size, { mode: 'must', values: ['lt5k', 'ge15k'] });
  assert.deepEqual(p.division, { mode: 'skip', values: [] });
  assert.deepEqual(R.validatePrefs(undefined, C), { prefs: R.defaultPrefs(), issues: [] }, 'no saved prefs is the default, silently');
});

test('A10 (unit) validatePrefs names every dropped part and never reinterprets one', () => {
  const kinds = raw => R.validatePrefs(raw, C).issues;
  assert.deepEqual(kinds('{"v":1'), [{ kind: 'shape' }], 'corrupt JSON text is a shape issue');
  assert.deepEqual(kinds([1, 2]), [{ kind: 'shape' }]);
  assert.deepEqual(kinds({ region: { mode: 'prefer', values: ['West'] } }), [{ kind: 'version', value: null }]);
  assert.deepEqual(kinds({ v: 2, region: { mode: 'prefer', values: ['West'] } }), [{ kind: 'newer', value: 2 }], 'a newer format is left alone');
  assert.deepEqual(R.validatePrefs({ v: 2 }, C).prefs, R.defaultPrefs(), 'and nothing of it is applied');
  assert.deepEqual(kinds({ v: 1, colour: { mode: 'prefer', values: ['red'] } }), [{ kind: 'key', key: 'colour' }]);
  assert.deepEqual(kinds({ v: 1, region: 'West' }), [{ kind: 'shape', category: 'region' }]);
  assert.deepEqual(kinds({ v: 1, region: { mode: 'prefer', values: 'West' } }), [{ kind: 'shape', category: 'region' }]);
  assert.deepEqual(kinds({ v: 1, region: { mode: 'love', values: ['West'] } }), [{ kind: 'mode', category: 'region', value: 'love' }]);
  // Climate must is not allowed (D2): dropped with an issue, not quietly turned into prefer.
  const climate = R.validatePrefs({ v: 1, climate: { mode: 'must', values: ['mild'] } }, C);
  assert.deepEqual(climate.issues, [{ kind: 'mode', category: 'climate', value: 'must' }]);
  assert.deepEqual(climate.prefs.climate, { mode: 'skip', values: [] });
  // A removed enum value is reported; the category keeps its other values, or is skipped (with an issue) when none is left.
  const removed = R.validatePrefs({ v: 1, region: { mode: 'prefer', values: ['Pacific', 'West'] }, size: { mode: 'must', values: ['huge'] } }, C);
  assert.deepEqual(removed.issues, [{ kind: 'value', category: 'region', value: 'Pacific' }, { kind: 'value', category: 'size', value: 'huge' },
                                    { kind: 'empty', category: 'size' }]);
  assert.deepEqual(removed.prefs.region, { mode: 'prefer', values: ['West'] });
  assert.deepEqual(removed.prefs.size, { mode: 'skip', values: [] });
  assert.deepEqual(kinds({ v: 1, division: { mode: 'prefer', values: [] } }), [{ kind: 'empty', category: 'division' }]);
  assert.deepEqual(kinds({ v: 1, division: { mode: 'skip', values: ['D9'] } }), [], 'values under skip are not read');
});

test('A8 (unit) sizeBand applies the approved half-open boundaries exactly', () => {
  const b = C.sizeBands;
  assert.deepEqual(b, [5000, 15000]);
  assert.equal(R.sizeBand(4999, b), 'lt5k');
  assert.equal(R.sizeBand(5000, b), '5k-15k');
  assert.equal(R.sizeBand(14999, b), '5k-15k');
  assert.equal(R.sizeBand(15000, b), 'ge15k');
  assert.equal(R.sizeBand(0, b), 'lt5k');
  for (const bad of [null, undefined, NaN, -1, '5000', Infinity]) assert.equal(R.sizeBand(bad, b), null, String(bad));
  assert.equal(R.sizeBand(5000, null), null, 'no bands, no band');
});

test('project returns only the fit facts, the slug and the displayed name', () => {
  const r = row('alpha', { shortName: 'Alpha', name: 'Alpha University', region: 'Midwest', state: 'OH', division: 'D2',
                           undergradEnrollment: 9201, extra: { rpi: 3, rpiHistory: [1], academicRank: 7, rosterSize: 30,
                                                               commitmentsByYear: { 2027: 4 }, conference: 'X' } });
  const p = proj(r, entry({ climate: 'cold', coldMonthMeanF: 20.4, stationKm: 3.3, unitId: 5, station: 'S1', asOf: ['2026-09-06', '2026-09-08'] }));
  assert.deepEqual(p, { slug: 'alpha', displayName: 'Alpha', fit: {
    region: 'Midwest', state: 'OH', division: 'D2', undergrad: 9201, size: '5k-15k', climate: 'cold', climateUnknown: null,
    coldMonthMeanF: 20.4, stationKm: 3.3, unitId: 5, station: 'S1', asOf: { school: '2026-09-06', climate: '2026-09-08' } } });
  assert.equal(proj(row('b', { shortName: null, name: 'Beta College' })).displayName, 'Beta College', 'shortName || name');
  // Unknowns: a value outside the taxonomy is unknown, never coerced.
  const u = proj(row('c', { region: 'Atlantis', division: 'NAIA', undergradEnrollment: null, state: null }), entry({ climate: null, climateUnknown: 'far-station' }));
  assert.equal(u.fit.region, null);
  assert.equal(u.fit.division, null);
  assert.equal(u.fit.size, null);
  assert.equal(u.fit.climate, null);
  assert.equal(u.fit.climateUnknown, 'far-station');
  assert.equal(R.project(row('d'), undefined, C).fit.climateUnknown, 'no-fit-entry', 'a program missing from the fit file');
});

test('fact reports value, detail, source and why for each category', () => {
  const p = proj(row('a', { region: 'South', state: 'TX', undergradEnrollment: 15000, division: 'D1' }),
                 entry({ climate: 'mild', coldMonthMeanF: 51.5, stationKm: 8, unitId: 42, station: 'USW1', asOf: ['2026-09-06', '2026-09-08'] }));
  assert.deepEqual(R.fact(p, 'region', S), { value: 'South', detail: { state: 'TX' },
    source: { name: 'College Scorecard', asOf: '2026-09-06', unitId: 42 }, why: null });
  assert.deepEqual(R.fact(p, 'division', S), { value: 'D1', detail: {}, source: { name: 'NCAA division (program registry)', asOf: null }, why: null });
  assert.deepEqual(R.fact(p, 'size', S).value, 'ge15k');
  assert.deepEqual(R.fact(p, 'size', S).detail, { undergrad: 15000 });
  assert.deepEqual(R.fact(p, 'climate', S), { value: 'mild', detail: { coldMonthMeanF: 51.5, stationKm: 8 },
    source: { name: S.climate.name, asOf: '2026-09-08', station: 'USW1' }, why: null });
  const u = proj(row('u', { region: null, undergradEnrollment: null }), entry({ climate: null, climateUnknown: 'no-climate-source' }));
  assert.equal(R.fact(u, 'region', S).why, 'no-school-record');
  assert.equal(R.fact(u, 'size', S).why, 'no-school-record');
  assert.equal(R.fact(u, 'climate', S).why, 'no-climate-source');
});

test('contributions: one per answered category, OR within a category', () => {
  const p = proj(row('a', { region: 'West', division: 'D3', undergradEnrollment: 1800 }), entry({ climate: 'cold' }));
  const q = R.validatePrefs(prefs({ region: { mode: 'prefer', values: ['West', 'Midwest'] }, division: { mode: 'must', values: ['D1', 'D2'] },
                                    climate: { mode: 'prefer', values: ['mild'] } }), C).prefs;
  const k = R.contributions(p, q, S);
  assert.deepEqual(k.map(x => [x.category, x.mode, x.outcome]), [['region', 'prefer', 'match'], ['division', 'must', 'miss'], ['climate', 'prefer', 'miss']]);
  assert.deepEqual(k[0].wanted, ['West', 'Midwest']);
  assert.deepEqual(R.contributions(p, R.defaultPrefs(), S), [], 'skipped categories contribute nothing');
});

test('mustHave is tri-state: a known miss fails, else an unknown is unknown, else pass (A2 unit)', () => {
  const q = R.validatePrefs(prefs({ region: { mode: 'must', values: ['Northeast'] }, division: { mode: 'must', values: ['D3'] } }), C).prefs;
  const m = (r, e) => R.mustHave(R.contributions(proj(r, e), q, S));
  assert.deepEqual(m(row('a', { region: 'Northeast', division: 'D3' })), { state: 'pass', perCategory: { region: 'pass', division: 'pass' } });
  assert.deepEqual(m(row('b', { region: null, division: 'D3' })), { state: 'unknown', perCategory: { region: 'unknown', division: 'pass' } });
  assert.deepEqual(m(row('c', { region: 'South', division: 'D3' })).state, 'fail', 'a known region mismatch is excluded, not unknown');
  assert.deepEqual(m(row('d', { region: null, division: 'D1' })).state, 'fail', 'a known miss beats an unknown');
  assert.deepEqual(R.mustHave([]), { state: 'pass', perCategory: {} }, 'no must haves: everyone passes');
});

test('A3 (unit) score uses a fixed denominator: one known match and two unknowns is 1 of 3, with no invented reason', () => {
  const p = proj(row('sparse', { region: 'West', undergradEnrollment: null }), entry({ climate: null, climateUnknown: 'no-normals' }));
  const q = R.validatePrefs(prefs({ region: { mode: 'prefer', values: ['West'] }, size: { mode: 'prefer', values: ['lt5k'] },
                                    climate: { mode: 'prefer', values: ['mild'] } }), C).prefs;
  const k = R.contributions(p, q, S);
  assert.deepEqual(R.score(k), { matched: 1, of: 3, score: 1 / 3 });
  const r = R.reasons(k);
  assert.equal(r.reasons.length, 1);
  assert.equal(r.reasons[0].category, 'region');
  assert.equal(r.tradeoff, null, 'no tradeoff is built from an unknown');
  assert.deepEqual(r.unknowns.map(u => u.category), ['size', 'climate']);
  const words = JSON.stringify(r) + r.unknowns.map(R.unknownText).join(' ') + r.reasons.map(R.reasonText).join(' ');
  assert.doesNotMatch(words, /penalt/i, 'no "missing-data penalty" wording');
  // A passed must is not scored; with no prefer category the score is 0 of 0.
  const mustOnly = R.validatePrefs(prefs({ region: { mode: 'must', values: ['West'] } }), C).prefs;
  assert.deepEqual(R.score(R.contributions(p, mustOnly, S)), { matched: 0, of: 0, score: 0 });
});

test('reasons: at most three, matched prefers before passed musts, shown in category order; one tradeoff; every unknown', () => {
  const p = proj(row('a', { region: 'West', division: 'D3', undergradEnrollment: 1800 }), entry({ climate: 'mild' }));
  const all = R.validatePrefs(prefs({ region: { mode: 'must', values: ['West'] }, division: { mode: 'prefer', values: ['D3'] },
                                      size: { mode: 'prefer', values: ['lt5k'] }, climate: { mode: 'prefer', values: ['mild'] } }), C).prefs;
  const r = R.reasons(R.contributions(p, all, S));
  assert.deepEqual(r.reasons.map(x => x.category), ['division', 'size', 'climate'], 'three prefer matches leave no room for the passed must');
  const two = R.validatePrefs(prefs({ region: { mode: 'must', values: ['West'] }, division: { mode: 'must', values: ['D3'] },
                                      size: { mode: 'prefer', values: ['lt5k'] }, climate: { mode: 'prefer', values: ['cold', 'four-season'] } }), C).prefs;
  const r2 = R.reasons(R.contributions(p, two, S));
  assert.deepEqual(r2.reasons.map(x => [x.category, x.mode]), [['region', 'must'], ['division', 'must'], ['size', 'prefer']]);
  assert.equal(r2.tradeoff.category, 'climate');
  assert.equal(r2.tradeoff.outcome, 'miss');
  assert.equal(R.tradeoffText(r2.tradeoff), 'Mild winters: coldest month averages 50.1°F (weather station 10.2 km away); you preferred four seasons or cold winters', 'values in taxonomy order');
  // Zero positive soft contributions: no reason, not claimed as a match.
  const none = R.validatePrefs(prefs({ region: { mode: 'prefer', values: ['South'] } }), C).prefs;
  const r3 = R.reasons(R.contributions(p, none, S));
  assert.deepEqual(r3.reasons, []);
  assert.equal(r3.tradeoff.category, 'region');
  // Every reason, tradeoff and unknown is one of the contributions, not a copy that could drift from it.
  const k = R.contributions(p, two, S);
  const r4 = R.reasons(k);
  for (const x of [...r4.reasons, r4.tradeoff, ...r4.unknowns]) assert.ok(k.includes(x));
});

test('reason, tradeoff and unknown text is built only from the object, locale-free', () => {
  const p = proj(row('a', { region: 'Midwest', state: 'OH', division: 'D3', undergradEnrollment: 163164 }), entry({ climate: 'four-season', coldMonthMeanF: 27 }));
  const q = R.validatePrefs(prefs({ region: { mode: 'prefer', values: ['Midwest'] }, division: { mode: 'must', values: ['D3'] },
                                    size: { mode: 'prefer', values: ['ge15k'] } }), C).prefs;
  const r = R.reasons(R.contributions(p, q, S));
  assert.deepEqual(r.reasons.map(R.reasonText), ['Midwest region (OH)', 'D3', 'Very large (30K+)']);
  const c = R.validatePrefs(prefs({ climate: { mode: 'prefer', values: ['four-season'] } }), C).prefs;
  assert.equal(R.reasonText(R.reasons(R.contributions(p, c, S)).reasons[0]), 'Four seasons: coldest month averages 27°F (weather station 10.2 km away)', 'D2: the figure and the station distance');
  const u = proj(row('u', { region: null, undergradEnrollment: null }), entry({ climate: null, climateUnknown: 'far-station', stationKm: 63.4 }));
  const all = R.validatePrefs(prefs({ region: { mode: 'must', values: ['West'] }, climate: { mode: 'prefer', values: ['mild'] } }), C).prefs;
  assert.deepEqual(R.reasons(R.contributions(u, all, S)).unknowns.map(R.unknownText),
                   ['Region unknown: no College Scorecard record', 'Climate unknown: the nearest weather station is 63.4 km away, too far to label']);
  // With no distance on record the words still say why, without a number.
  const noKm = R.reasons(R.contributions(proj(row('n'), entry({ climate: null, climateUnknown: 'far-station', stationKm: null })), all, S)).unknowns;
  assert.equal(R.unknownText(noKm.find(x => x.category === 'climate')), 'Climate unknown: the nearest weather station is too far away');
  const noKmReason = R.reasons(R.contributions(proj(row('k'), entry({ climate: 'mild', stationKm: null })), R.validatePrefs(prefs({ climate: { mode: 'prefer', values: ['mild'] } }), C).prefs, S)).reasons[0];
  assert.equal(R.reasonText(noKmReason), 'Mild winters: coldest month averages 50.1°F');
});

test('A8 (unit) equal scores order by displayed name, then slug, and the fast path agrees with compareRanked', () => {
  const rows = [
    row('zeta', { shortName: 'alpha', name: 'Zeta University' }),     // displayed "alpha": sorts by what is shown, not `name`
    row('b-slug', { shortName: 'Beta' }), row('a-slug', { shortName: 'Beta' }),  // same displayed name: slug breaks the tie
    row('c', { shortName: 'Ålborg' }), row('d', { shortName: 'Alpha' }), row('e', { shortName: 'gamma', region: 'South' }),
  ];
  const cat = tinyCatalog(rows);
  const res = R.rank({ ...cat, prefs: prefs({ region: { mode: 'prefer', values: ['West'] } }) });
  // The page's byDisplayName: letters first ignoring case and accents (Ålborg before alpha), then the exact
  // compare (alpha before Alpha), then slug; the 0-of-1 program last.
  assert.deepEqual(slugs(res.confirmed), ['c', 'zeta', 'd', 'a-slug', 'b-slug', 'e']);
  const ref = res.confirmed.slice().sort(R.compareRanked);
  assert.deepEqual(slugs(ref), slugs(res.confirmed));
  assert.deepEqual(slugs(R.group(res.confirmed.slice().reverse()).confirmed), slugs(res.confirmed), 'group without an order uses the comparator');
});

test('nameOrder is remembered per list but never stale after an in-place edit', () => {
  const rows = [row('a', { shortName: 'B' }), row('b', { shortName: 'A' })];
  assert.deepEqual([...R.nameOrder(rows)], [['b', 0], ['a', 1]]);
  rows[0].shortName = '0 first';
  assert.deepEqual([...R.nameOrder(rows)], [['a', 0], ['b', 1]]);
});

test('applyFilters is its own counted layer; applyHidden splits by slug, stored entries or plain slugs', () => {
  const rows = [row('a', { region: 'West' }), row('b', { region: 'South' }), row('c', { region: 'West' })];
  assert.deepEqual(R.applyFilters(rows, null), { rows, filteredOut: 0 });
  const f = R.applyFilters(rows, r => r.region === 'West');
  assert.deepEqual([slugs(f.rows), f.filteredOut], [['a', 'c'], 1]);
  const h = R.applyHidden(rows, ['b', { slug: 'c', reason: 'size', at: '2026-10-01' }, { nope: 1 }, 7]);
  assert.deepEqual([slugs(h.rows), slugs(h.hiddenRows)], [['a'], ['b', 'c']]);
});

test('evaluate builds the result item, with coverage for low-coverage programs (A11 unit)', () => {
  const q = R.validatePrefs(prefs({ division: { mode: 'prefer', values: ['D2'] }, region: { mode: 'must', values: ['West'] } }), C).prefs;
  const lone = R.project(row('new', { region: null, state: null, undergradEnrollment: null, division: 'D2' }), undefined, C);
  const it = R.evaluate(lone, q, S);
  assert.equal(it.mustHave, 'unknown', 'an unknown mandatory field can never be confirmed');
  assert.deepEqual(it.coverage, { known: 1, of: 4 });
  assert.deepEqual([it.matched, it.of], [1, 1], 'content alone permits evaluation');
  const full = R.evaluate(proj(row('full')), q, S);
  assert.deepEqual(full.coverage, { known: 4, of: 4 });
  assert.deepEqual(Object.keys(full), ['slug', 'displayName', 'matched', 'of', 'score', 'mustHave', 'reasons', 'tradeoff', 'unknowns', 'coverage']);
});

test('rank: Confirmed, Need verification and every exclusion counted (A2, A7 unit)', () => {
  const rows = [
    row('ne-1', { region: 'Northeast', undergradEnrollment: 20000 }), row('ne-2', { region: 'Northeast', undergradEnrollment: 3000 }),
    row('unknown', { region: null, state: null, undergradEnrollment: null }), row('south', { region: 'South' }),
    row('west', { region: 'West', conference: 'Other' }),
  ];
  const cat = tinyCatalog(rows);
  const q = prefs({ region: { mode: 'must', values: ['Northeast'] } });
  const res = R.rank({ ...cat, prefs: q });
  assert.deepEqual(slugs(res.confirmed), ['ne-1', 'ne-2']);
  assert.deepEqual(slugs(res.needVerification), ['unknown'], 'unknown region: Need verification only');
  assert.deepEqual(res.excluded, { byFilter: 0, byMustHave: 2, hidden: 0, byMustHaveCategory: { region: 2 } });
  assert.equal(res.total, 5);
  // A7: everything failing or hidden; each cause counted.
  const empty = R.rank({ ...cat, prefs: prefs({ region: { mode: 'must', values: ['Northeast'] }, size: { mode: 'must', values: ['ge15k'] } }),
                         filter: r => r.conference !== 'Other', hidden: ['ne-1', 'unknown'] });
  assert.deepEqual([empty.confirmed, empty.needVerification], [[], []]);
  // Per-category counts overlap: 'south' fails both region and size, so they add up to more than byMustHave.
  assert.deepEqual(empty.excluded, { byFilter: 1, byMustHave: 2, hidden: 2, byMustHaveCategory: { region: 1, size: 2 } });
  assert.deepEqual(empty.hiddenRows, ['ne-1', 'unknown']);
  assert.deepEqual(R.rank({ ...cat, prefs: q, hidden: ['gone-program', 'ne-2'] }).staleHidden, ['gone-program'], 'A10: a hidden slug no longer listed is reported');
});

test('rank refuses mismatched, unknown-taxonomy or malformed input and ranks nothing', () => {
  const cat = tinyCatalog([row('a'), row('b')]);
  const q = prefs({ region: { mode: 'prefer', values: ['West'] } });
  assert.equal(R.rank({ ...cat, fit: { ...cat.fit, updated: 'other' }, prefs: q }).error, 'mismatch');
  assert.equal(R.rank({ ...cat, fit: { ...cat.fit, fitTaxonomy: 'fit-2' }, prefs: q }).error, 'taxonomy');
  assert.equal(R.rank({ list: { updated: 'x', programs: [row('a'), row('a')] }, fit: { ...cat.fit, updated: 'x' }, prefs: q }).error, 'catalog');
  assert.equal(R.rank({ list: null, fit: cat.fit, prefs: q }).error, 'catalog');
  assert.equal(R.rank().error, 'catalog');
  const r = R.rank({ ...cat, fit: { ...cat.fit, fitTaxonomy: 'fit-2' }, prefs: q });
  assert.equal(r.confirmed, undefined, 'no partial result');
});

test('rank with nothing answered is inactive: nothing ranked, no "for you" (A4 unit)', () => {
  const cat = tinyCatalog([row('a'), row('b')]);
  const r = R.rank({ ...cat, prefs: R.defaultPrefs(), hidden: ['a'] });
  assert.equal(r.active, false);
  assert.deepEqual([r.confirmed, r.needVerification, r.hiddenRows], [[], [], []]);
  assert.equal(R.rank({ ...cat, prefs: prefs({ climate: { mode: 'must', values: ['mild'] } }) }).active, false, 'an invalid-only set is not active either');
});

test('the result carries its versions; stamp and staleness say what changed (stale-cache invalidation)', () => {
  const cat = tinyCatalog([row('a')]);
  const r = R.rank({ ...cat, prefs: prefs({ division: { mode: 'prefer', values: ['D3'] } }) });
  assert.deepEqual([r.v, r.ranker, r.taxonomy, r.catalog], [1, 'r1', 'fit-1', '2026-09-30T00:00:00Z']);
  const s = R.stamp(r);
  assert.deepEqual(s, { taxonomy: 'fit-1', ranker: 'r1', catalog: '2026-09-30T00:00:00Z' });
  assert.deepEqual(R.staleness(s, s), []);
  assert.deepEqual(R.staleness(s, { ...s, catalog: '2026-10-01T00:00:00Z' }), ['catalog']);
  assert.deepEqual(R.staleness(s, { ...s, taxonomy: 'fit-2', ranker: 'r2' }), ['taxonomy', 'ranker']);
  assert.deepEqual(R.staleness(null, s), ['taxonomy', 'ranker', 'catalog']);
});

test('recs.js runs as a plain browser script and exposes window.CDRecs', () => {
  const src = readFileSync(new URL('../public/recs.js', import.meta.url), 'utf8');
  const ctx = { Intl, WeakMap, Map, Set };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  assert.equal(typeof ctx.CDRecs?.rank, 'function');
  assert.equal(ctx.CDRecs.RANKER, R.RANKER);
  assert.ok(Object.isFrozen(ctx.CDRecs));
  assert.doesNotMatch(src, /\bfetch\(|XMLHttpRequest|localStorage|sessionStorage|document\.|Date\.now|new Date|Math\.random/,
    'pure: no network, storage, DOM, clock or randomness');
});
