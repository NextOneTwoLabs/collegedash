// The recommender's Node performance proxy (issue #400, plan §5): rank the frozen 1,011-program catalog and a 5x
// synthetic catalog (5,055 programs) 200 times each, and require p95 <= 10 ms in Node. The phone target is a
// rerank <= 100 ms at p95, so this budget is a proxy about 10x under it; the real-device timing is done by hand
// on the owner's two named devices (D6), with the local-only overlay of PR 6. Offline.
//
// Node runs test files in parallel, so a run can share the CPU with the other suites. The check is built so it
// can't pass by luck: every catalog ALWAYS gets five attempts of 200 timed runs (after 20 warm-up runs each),
// a second apart, and the MEDIAN of the five attempts' p95 must be within budget. One noisy attempt can't fail it
// and one lucky attempt can't pass it; a real slowdown moves at least three of the five. Each p95 is a plain
// wall-clock p95 over 200 single runs, never a best-of. Every attempt is printed as a test diagnostic.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout as sleep } from 'node:timers/promises';
import { R, CATALOG, catalogDocs } from './recs_helpers.mjs';

const BUDGET_MS = 10;
const RUNS = 200;
const WARMUP = 20;
const ATTEMPTS = 5;
const PHONE_TARGET_MS = 100;

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

function p95(docs) {
  for (let i = 0; i < WARMUP; i++) R.rank({ ...docs, prefs: PREFS });
  const t = [];
  for (let i = 0; i < RUNS; i++) {
    const s = process.hrtime.bigint();
    R.rank({ ...docs, prefs: PREFS });
    t.push(Number(process.hrtime.bigint() - s) / 1e6);
  }
  t.sort((a, b) => a - b);
  return { p50: t[Math.floor(RUNS * 0.5)], p95: t[Math.ceil(RUNS * 0.95) - 1], max: t[RUNS - 1] };
}

for (const [label, make, size] of [['frozen catalog', () => catalogDocs(), CATALOG.programs.length], ['5x synthetic catalog', fiveTimes, CATALOG.programs.length * 5]]) {
  test(`rank p95 <= ${BUDGET_MS} ms in Node: ${label} (${size} programs, ${RUNS} runs)`, async t => {
    const docs = make();
    assert.equal(docs.list.programs.length, size);
    const res = R.rank({ ...docs, prefs: PREFS });
    assert.ok(res.confirmed.length > 0, 'the benchmark ranks real results');
    const p95s = [];
    for (let a = 1; a <= ATTEMPTS; a++) {
      const m = p95(docs);
      p95s.push(m.p95);
      t.diagnostic(`${label} attempt ${a}: p50 ${m.p50.toFixed(2)} ms, p95 ${m.p95.toFixed(2)} ms, max ${m.max.toFixed(2)} ms`);
      if (a < ATTEMPTS) await sleep(1000);
    }
    const median = p95s.slice().sort((x, y) => x - y)[Math.floor(ATTEMPTS / 2)];
    t.diagnostic(`${label}: median p95 ${median.toFixed(2)} ms; budget ${BUDGET_MS} ms = phone target ${PHONE_TARGET_MS} ms / ${PHONE_TARGET_MS / BUDGET_MS}`);
    assert.ok(median <= BUDGET_MS, `${label}: median p95 of ${ATTEMPTS} attempts is ${median.toFixed(2)} ms, over the ${BUDGET_MS} ms budget (${p95s.map(x => x.toFixed(2)).join(', ')})`);
  });
}
