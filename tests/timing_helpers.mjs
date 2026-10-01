// Shared by the test suites that time code in wall-clock milliseconds (tests/recs_perf.test.mjs, issue #400; the
// apikey R-I check in tests/apikey.test.mjs, issue #345) and the one heavy suite they must not overlap
// (tests/recs_properties.test.mjs). Not a suite itself: no node:test import.
//
// Why: node --test runs files in parallel. A timing taken while another suite saturates the CPU measures that suite,
// not the code under test: #415's CI went red at an 18.9 ms median p95 against a 10 ms budget while the property
// suite (about 20 s of ranking at full tilt) ran beside the perf suite, and the R-I average does the same under load.
// Three tools, none of which moves a budget:
//
//   acquireCpu(who, maxWaitMs)  a machine-wide mutex (a file in the OS temp directory, created exclusively). The heavy
//                               suite holds it while it runs; a timing suite holds it while it measures, so the two never
//                               overlap. It can't hang a run: a holder whose process is gone is stale and removed, and
//                               waiting is bounded - past maxWaitMs the caller goes on without the lock and is told so.
//   quietWindow(maxWaitMs)      waits (bounded) until a fixed, code-independent probe runs as fast as it has run in this
//                               process three times in a row, so an attempt starts in a quiet moment rather than a burst
//                               from the other suites. It gates WHEN to measure, never what passes.
//   spin(ms)                    busy-waits between attempts instead of sleeping: an idle process on Windows is moved
//                               to a slower core, which tripled every attempt after the first sleep (5 ms, then 12-16 ms).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

export const LOCK = process.env.CD_CPU_LOCK || path.join(os.tmpdir(), 'collegedash-test-cpu.lock');
const alive = (pid) => { try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Wait (at most maxWaitMs) for the lock. Resolves {held, waitedMs, release(), timedOut?, holder?, error?}. Never rejects. */
export async function acquireCpu(who, maxWaitMs) {
  const t0 = Date.now();
  for (;;) {
    try {
      const fd = fs.openSync(LOCK, 'wx');
      fs.writeSync(fd, JSON.stringify({ pid: process.pid, who }));
      fs.closeSync(fd);
      let released = false;
      const release = () => {
        if (released) return;
        released = true;
        try { if (JSON.parse(fs.readFileSync(LOCK, 'utf8')).pid === process.pid) fs.unlinkSync(LOCK); } catch { /* already gone */ }
      };
      process.once('exit', release);
      return { held: true, waitedMs: Date.now() - t0, release };
    } catch (e) {
      if (e.code !== 'EEXIST') return { held: false, waitedMs: Date.now() - t0, release() { }, error: e.code };
    }
    let holder = null, age = Infinity;
    try { age = Date.now() - fs.statSync(LOCK).mtimeMs; holder = JSON.parse(fs.readFileSync(LOCK, 'utf8')); } catch { /* being written, or gone */ }
    const stale = holder ? !Number.isInteger(holder.pid) || !alive(holder.pid) : age > 2000;
    if (stale) { try { fs.unlinkSync(LOCK); } catch { /* someone else removed it */ } continue; }
    if (Date.now() - t0 >= maxWaitMs) return { held: false, waitedMs: Date.now() - t0, release() { }, timedOut: true, holder: holder?.who ?? 'unknown' };
    await sleep(200);
  }
}

export function spin(ms) { const end = performance.now() + ms; while (performance.now() < end) { /* stay on a fast core */ } }

// A fixed workload independent of the code under test, so a slower ranker or key check can't change when the gate opens.
const PROBE_INPUT = Float64Array.from({ length: 40000 }, (_, i) => Math.sin(i * 12.9898) * 43758.5453 % 1);
function probeMs() { const a = PROBE_INPUT.slice(); const s = performance.now(); a.sort(); return performance.now() - s; }
let bestProbe = Infinity;

/** Wait (at most maxWaitMs, busy) for three probes in a row within 25% of the fastest seen. Resolves {quiet, waitedMs}. */
export function quietWindow(maxWaitMs) {
  const t0 = performance.now();
  let streak = 0;
  for (;;) {
    const p = probeMs();
    bestProbe = Math.min(bestProbe, p);
    streak = p <= bestProbe * 1.25 ? streak + 1 : 0;
    const waitedMs = Math.round(performance.now() - t0);
    if (streak >= 3) return { quiet: true, waitedMs };
    if (waitedMs >= maxWaitMs) return { quiet: false, waitedMs };
    spin(20);
  }
}

export const median = (xs) => xs.slice().sort((a, b) => a - b)[Math.floor(xs.length / 2)];
