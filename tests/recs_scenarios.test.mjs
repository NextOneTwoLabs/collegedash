// The recommender's dev scenarios (issue #400, PR 2): tests/fixtures/recs/scenarios.json against the frozen
// catalog tests/fixtures/recs/catalog.json, so the daily refresh never moves an expectation. The expectations
// were derived from the catalog by an independent re-implementation of the plan's rules, not by running recs.js.
// Held-out scenarios (written by a Reviewer) join in PR 7. Offline.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { R, CATALOG, SCENARIOS, catalogDocs, filterPredicate, slugs } from './recs_helpers.mjs';

test('the scenarios are pinned to this taxonomy and ranker, and well formed', () => {
  assert.deepEqual(SCENARIOS.pinned, { taxonomy: CATALOG.fitTaxonomy, ranker: R.RANKER },
    'a new taxonomy or ranker version means re-deriving and re-reviewing every expectation');
  const ids = SCENARIOS.scenarios.map(s => s.id);
  assert.equal(new Set(ids).size, ids.length, 'unique ids');
  assert.ok(ids.length >= 20, `20-30 scenarios (plan §5), got ${ids.length}`);
  const bySlug = new Set(CATALOG.programs.map(p => p.slug));
  for (const s of SCENARIOS.scenarios) {
    assert.ok(['dev', 'heldout'].includes(s.split), s.id);
    assert.ok(s.why && s.why.length > 10, `${s.id} says why it exists`);
    for (const slug of [...(s.expect.top || []), ...(s.expect.needVerification || []), ...(s.expect.mustExclude || [])]) {
      assert.ok(bySlug.has(slug), `${s.id}: ${slug} is in the frozen catalog`);
    }
  }
});

for (const s of SCENARIOS.scenarios) {
  test(`${s.id}: ${s.why}`, () => {
    const res = R.rank({ ...catalogDocs(), prefs: s.prefs, filter: filterPredicate(s.filters), hidden: s.hidden });
    const e = s.expect;
    assert.equal(res.error, undefined);
    assert.equal(res.active, e.active);
    assert.deepEqual(res.issues.map(i => i.kind), e.issues);
    assert.deepEqual(res.staleHidden, e.staleHidden);
    if (!e.active) return;
    assert.equal(res.confirmed.length === 0, e.zeroResults);
    assert.deepEqual({ confirmed: res.confirmed.length, needVerification: res.needVerification.length,
                       byFilter: res.excluded.byFilter, byMustHave: res.excluded.byMustHave, hidden: res.excluded.hidden }, e.counts);
    assert.deepEqual(slugs(res.confirmed.slice(0, e.top.length)), e.top);
    if (e.needVerification) assert.deepEqual(slugs(res.needVerification), e.needVerification);
    const shown = new Set([...slugs(res.confirmed), ...slugs(res.needVerification)]);
    for (const x of e.mustExclude) assert.ok(!shown.has(x), `${x} must not be listed`);
    for (const x of e.mustInclude || []) assert.ok(shown.has(x), `${x} must be listed`);
    // The fast sort agrees with the reference comparator on the whole real catalog.
    assert.deepEqual(slugs(res.confirmed.slice().sort(R.compareRanked)), slugs(res.confirmed));
    assert.deepEqual(slugs(res.needVerification.slice().sort(R.compareRanked)), slugs(res.needVerification));
  });
}
