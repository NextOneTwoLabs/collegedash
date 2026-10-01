// Shared by the recommender ranker suites (issue #400, PR 2). Not a suite itself: no node:test import.
// Everything is offline: the frozen catalog is read from tests/fixtures/recs, and nothing is fetched.
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
export const R = require('../public/recs.js');

const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/recs/${name}`, import.meta.url), 'utf8'));
export const CATALOG = fixture('catalog.json');
export const SCENARIOS = fixture('scenarios.json');

/** The two documents the page will have: the list and the fit file, from the frozen catalog. Fresh copies. */
export function catalogDocs(fx = CATALOG) {
  const copy = JSON.parse(JSON.stringify(fx));
  return {
    list: { updated: copy.updated, programs: copy.programs },
    fit: { updated: copy.updated, fitTaxonomy: copy.fitTaxonomy, constants: copy.constants, sources: copy.sources, fit: copy.fit },
  };
}

/** The scenarios' filters with the sidebar's matchesFilters semantics: OR within a group, AND across, empty = all. */
export function filterPredicate(f) {
  if (!f || !Object.keys(f).length) return null;
  const has = (vals, v) => !vals || !vals.length || vals.includes(v);
  return r => has(f.conf, r.conference) && has(f.region, r.region) && has(f.division, r.division);
}

/** Facts recomputed here from the raw row and fit entry, independently of recs.js, for the property gates. */
export function independentFacts(row, entry, constants) {
  const [lo, hi] = constants.sizeBands;
  const n = row.undergradEnrollment;
  return {
    region: Object.keys(constants.regions).includes(row.region) ? row.region : null,
    division: ['D1', 'D2', 'D3'].includes(row.division) ? row.division : null,
    size: typeof n === 'number' ? (n < lo ? 'lt5k' : n < hi ? '5k-15k' : 'ge15k') : null,
    climate: entry && ['mild', 'four-season', 'cold'].includes(entry.climate) ? entry.climate : null,
  };
}

/** A small seeded PRNG (mulberry32), so the 1,000 random preference sets are the same on every run. */
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function shuffle(arr, rand) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rand() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

/** A made-up program row for unit tests. */
export const row = (slug, o = {}) => ({ slug, name: o.name ?? `${slug} University`, shortName: o.shortName ?? null,
  division: o.division ?? 'D3', conference: o.conference ?? 'Test Conference', region: o.region === undefined ? 'West' : o.region,
  state: o.state === undefined ? 'CA' : o.state, undergradEnrollment: o.undergradEnrollment === undefined ? 2000 : o.undergradEnrollment, ...o.extra });

/** A made-up fit entry for unit tests. */
export const entry = (o = {}) => ({ climate: 'mild', climateUnknown: null, coldMonthMeanF: 50.1, stationKm: 10.2, unitId: 100001,
  station: 'USW00000001', asOf: ['2026-09-01', '2026-09-02'], ...o });

/** A made-up catalog: rows plus fit entries keyed by slug, with fit-1's real constants. */
export function tinyCatalog(rows, entries = {}, updated = '2026-09-30T00:00:00Z') {
  return {
    list: { updated, programs: rows },
    fit: { updated, fitTaxonomy: 'fit-1', constants: CATALOG.constants, sources: CATALOG.sources,
           fit: Object.fromEntries(rows.map(r => [r.slug, entries[r.slug] === undefined ? entry() : entries[r.slug]]).filter(([, e]) => e !== null)) },
  };
}

export const prefs = (o = {}) => ({ v: 1, ...o });
export const slugs = items => items.map(x => x.slug);
