// The recommender's dev scenarios (issue #400, PR 2): tests/fixtures/recs/scenarios.json against the frozen
// catalog tests/fixtures/recs/catalog.json, so the daily refresh never moves an expectation. The expectations
// were derived from the catalog by an independent re-implementation of the plan's rules, not by running recs.js.
// Held-out scenarios (written by a Reviewer) join in PR 7. Offline.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
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

// ---------- the Reviewer's held-out cases HU1-HU6 (Huatuo, #429) ----------
// Committed exactly as posted, with the sha256 posted beside them (issuecomment-5934974631), BEFORE they were run
// here. Their format is the Reviewer's own: the full order (or the first `topN`) with each row's score, and the counts.
// HU2 also carries `orderCasefold`, because the plan didn't say whether the name order ignores case; the code and the
// list's Name sort do ("Boise State" before "BYU"), so that is the order checked when it is given.
const HU_FILE = readFileSync(new URL('./fixtures/recs/heldout_reviewer.jsonl', import.meta.url), 'utf8');
const HU = HU_FILE.split(/\r?\n/).filter(Boolean).map(l => JSON.parse(l));

test('HU1-HU6 are exactly the lines the Reviewer posted (sha256 92ee2345…)', () => {
  const lines = HU_FILE.split(/\r?\n/).filter(Boolean);
  assert.equal(createHash('sha256').update(lines.join('\r\n') + '\r\n', 'utf8').digest('hex'),
    '92ee2345d348454ef8827eee09787612b84099642adb19f5ef4e3a6884fafb06');
  assert.deepEqual(HU.map(s => s.id), ['HU1', 'HU2', 'HU3', 'HU4', 'HU5', 'HU6']);
  const all = [...SCENARIOS.scenarios.map(s => s.id), ...HU.map(s => s.id)];
  assert.equal(new Set(all).size, all.length, 'unique ids across both files');
  assert.equal(SCENARIOS.scenarios.filter(s => s.split === 'heldout').length + HU.length, 14, '14 of 37 held out');
});

for (const s of HU) {
  test(`${s.id} (Reviewer): ${s.why}`, () => {
    const res = R.rank({ ...catalogDocs(), prefs: s.prefs, filter: filterPredicate(s.filters), hidden: s.hidden });
    const e = s.expect;
    assert.equal(res.error, undefined);
    assert.equal(res.active, e.active);
    if (!e.active) return;
    assert.deepEqual({ confirmed: res.confirmed.length, needVerification: res.needVerification.length,
                       byFilter: res.excluded.byFilter, byMustHave: res.excluded.byMustHave, hidden: res.excluded.hidden }, e.counts);
    const order = e.orderCasefold || e.order;
    const n = s.topN || order.length;
    assert.deepEqual(slugs(res.confirmed.slice(0, n)), order.slice(0, n));
    assert.deepEqual(res.confirmed.slice(0, n).map(x => x.matched), e.scores.slice(0, n));
    assert.deepEqual(slugs(res.needVerification), e.needVerification);
    assert.deepEqual(res.staleHidden, e.staleHidden);
  });
}
