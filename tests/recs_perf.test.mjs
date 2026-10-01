// The recommender's Node performance proxy (issue #400, plan §5). The phone targets are a rerank <= 100 ms and an
// Apply <= 300 ms at p95; Node is about 10x faster than a mid-range phone, so the budgets here are those targets / 10.
// The real-device timing is done by hand on the owner's two named devices (D6), with PR 6's local-only overlay.
//
//   warm rerank   rank() again on the list it already ranked (what every preference, filter or sort change does):
//                 the frozen 1,011-program catalog and a 5x synthetic one (5,055), p95 <= 10 ms each.
//   cold          the FIRST rank() of a list it has never seen (a new array, so the remembered name order is rebuilt),
//                 which is what Apply does once the data has loaded: the 1,011 catalog within the same 10 ms, the 5x
//                 catalog within 30 ms, the Apply target / 10 (300 ms on a phone). Cold is part of Apply, never of a
//                 rerank, so it is held to the Apply ratio, not the rerank one; the rerank budget is unchanged.
//
// Why it no longer flakes (#415's CI went red at a 18.9 ms median while the property suite ran beside it):
//   - it measures only while it holds the CPU lock (tests/timing_helpers.mjs), which recs_properties.test.mjs also takes,
//     so the two never overlap. The wait is bounded; if it runs out, the run says so and measures anyway;
//   - each attempt starts in a quiet moment: quietWindow waits (at most 8 s, busy) until a fixed probe that doesn't
//     use the ranker runs at its best speed three times in a row. It decides when to measure, never what passes;
//   - between attempts it spins for 250 ms instead of sleeping: an idle process on Windows was being moved to a slower
//     core, which tripled every attempt after the first sleep (5 ms, then 12-16 ms).
// It still can't pass by luck: every case ALWAYS runs five attempts and the MEDIAN of their p95 must be within budget,
// so one noisy attempt can't fail it and one lucky attempt can't pass it. Each p95 is a plain wall-clock p95, never a
// best-of. Every attempt is printed as a test diagnostic. Offline.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { R, CATALOG, catalogDocs } from './recs_helpers.mjs';
import { acquireCpu, quietWindow, spin, median } from './timing_helpers.mjs';

const RERANK_BUDGET_MS = 10;     // 100 ms phone rerank target / 10
const APPLY_BUDGET_MS = 30;      // 300 ms phone Apply target / 10
const RUNS = 200, COLD_RUNS = 30, WARMUP = 20, ATTEMPTS = 5, SPIN_MS = 250;
const LOCK_WAIT_MS = 150_000, QUIET_WAIT_MS = 8_000;

// Every category answered, multi-valued, with one must: every stage of the ranker does real work.
const PREFS = { v: 1, region: { mode: 'prefer', values: ['West', 'Midwest'] }, division: { mode: 'must', values: ['D1', 'D3'] },
                size: { mode: 'prefer', values: ['lt5k', '5k-15k'] }, climate: { mode: 'prefer', values: ['mild'] } };

function fiveTimes() {
  const d = catalogDocs();
  const programs = [], fit = {};
  for (let k = 0; k < 5; k++) {
    for (const p of d.list.programs) {
      const slug = k ? `${p.slug}-copy${k}` : p.slug;
      programs.push({ ...p, slug, shortName: k && p.shortName ? `${p.shortName} ${k}` : p.shortName });
      fit[slug] = d.fit.fit[p.slug];
    }
  }
  return { list: { ...d.list, programs }, fit: { ...d.fit, fit } };
}

const pct = (sorted, q) => sorted[Math.ceil(sorted.length * q) - 1];
function timeRuns(docs, runs, fresh) {
  const t = [];
  for (let i = 0; i < runs; i++) {
    const input = fresh ? { ...docs, list: { ...docs.list, programs: docs.list.programs.slice() } } : docs; // a new array: cold
    const s = process.hrtime.bigint();
    R.rank({ ...input, prefs: PREFS });
    t.push(Number(process.hrtime.bigint() - s) / 1e6);
  }
  t.sort((a, b) => a - b);
  return { p50: pct(t, 0.5), p95: pct(t, 0.95), max: t[t.length - 1] };
}

let CPU = null;
test.before(async () => { CPU = await acquireCpu('recs_perf', LOCK_WAIT_MS); });
test.after(() => CPU?.release());

const CASES = [
  ['warm rerank, frozen catalog', () => catalogDocs(), CATALOG.programs.length, false, RUNS, RERANK_BUDGET_MS],
  ['warm rerank, 5x synthetic catalog', fiveTimes, CATALOG.programs.length * 5, false, RUNS, RERANK_BUDGET_MS],
  ['cold first rank, frozen catalog', () => catalogDocs(), CATALOG.programs.length, true, COLD_RUNS, RERANK_BUDGET_MS],
  ['cold first rank, 5x synthetic catalog', fiveTimes, CATALOG.programs.length * 5, true, COLD_RUNS, APPLY_BUDGET_MS],
];
for (const [label, make, size, cold, runs, budget] of CASES) {
  test(`${label} (${size} programs): median p95 of ${ATTEMPTS} attempts <= ${budget} ms in Node`, t => {
    t.diagnostic(CPU.held ? `measured holding the CPU lock (waited ${CPU.waitedMs} ms)`
      : `measured WITHOUT the CPU lock (${CPU.timedOut ? `still held by ${CPU.holder} after ${CPU.waitedMs} ms` : CPU.error}): timings may include other suites`);
    const docs = make();
    assert.equal(docs.list.programs.length, size);
    assert.ok(R.rank({ ...docs, prefs: PREFS }).confirmed.length > 0, 'the benchmark ranks real results');
    const p95s = [];
    for (let a = 1; a <= ATTEMPTS; a++) {
      const q = quietWindow(QUIET_WAIT_MS);
      if (!cold) for (let i = 0; i < WARMUP; i++) R.rank({ ...docs, prefs: PREFS });
      const m = timeRuns(docs, runs, cold);
      p95s.push(m.p95);
      t.diagnostic(`${label} attempt ${a}: p50 ${m.p50.toFixed(2)} ms, p95 ${m.p95.toFixed(2)} ms, max ${m.max.toFixed(2)} ms`
        + ` (${q.quiet ? `quiet after ${q.waitedMs} ms` : `NOT quiet after ${q.waitedMs} ms: measured anyway`})`);
      if (a < ATTEMPTS) spin(SPIN_MS);
    }
    const mid = median(p95s);
    t.diagnostic(`${label}: median p95 ${mid.toFixed(2)} ms; budget ${budget} ms`);
    assert.ok(mid <= budget, `${label}: median p95 of ${ATTEMPTS} attempts is ${mid.toFixed(2)} ms, over the ${budget} ms budget (${p95s.map(x => x.toFixed(2)).join(', ')})`);
  });
}
