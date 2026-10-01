// Shared by the test suites that time code in wall-clock milliseconds (tests/recs_perf.test.mjs, issue #400; the
// apikey R-I check in tests/apikey.test.mjs, issue #345) and the heavy suites they must not overlap (recs_properties
// and the recs page suites). Not a suite itself: no node:test import.
//
// Why: node --test runs files in parallel. A timing taken while another suite saturates the CPU measures that suite,
// not the code under test: #415's CI went red at an 18.9 ms median p95 against a 10 ms budget while the property
// suite (about 20 s of ranking at full tilt) ran beside the perf suite, and the R-I average does the same under load.
// Three tools, none of which moves a budget:
//
//   acquireShared / acquireExclusive
//                               a machine-wide readers-writer lock (files in the OS temp directory). The heavy suites
//                               (recs_properties and the recs page suites) hold it shared, so they still run beside each
//                               other; a timing suite holds it exclusive while it measures, so none of them runs beside
//                               it. It can't hang a run: a holder whose process is gone is stale and removed, and every
//                               wait is bounded - past maxWaitMs the caller goes on and is told so.
//   quietWindow(maxWaitMs)      waits (bounded) until a fixed, code-independent probe runs as fast as it has run in this
//                               process three times in a row, so an attempt starts in a quiet moment rather than a burst
//                               from the other suites. It gates WHEN to measure, never what passes.
//   spin(ms)                    busy-waits between attempts instead of sleeping: an idle process on Windows is moved
//                               to a slower core, which tripled every attempt after the first sleep (5 ms, then 12-16 ms).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// The lock is a directory in the OS temp folder holding one file per holder, named for its kind and process:
//   shared-<pid>-<n>.lock   a heavy suite running (recs_properties and the recs page suites); any number at once;
//   exclusive.lock          a timing suite measuring (recs_perf, R-I); one at a time, created with 'wx'.
// A timing suite first takes exclusive.lock, which stops NEW shared holders from starting, then waits for the shared
// holders already running to finish; so it measures with none of them beside it, and is never starved by them. A
// holder whose process is gone (a crash, a kill) is stale: its file is removed and ignored. Every wait is bounded:
// past maxWaitMs the caller goes on (a shared holder runs, a timing suite measures) and is told why.
export const LOCK_DIR = process.env.CD_CPU_LOCK_DIR || path.join(os.tmpdir(), 'collegedash-test-cpu');
const EXCLUSIVE = 'exclusive.lock';
const alive = (pid) => { try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ensureDir = () => { try { fs.mkdirSync(LOCK_DIR, { recursive: true }); return true; } catch { return false; } };
let counter = 0;

// The live holders of a kind ('shared' or 'exclusive'), removing stale ones. Each: {file, pid, who}.
function holders(kind) {
  let names = [];
  try { names = fs.readdirSync(LOCK_DIR); } catch { return []; }
  const live = [];
  for (const name of names) {
    if (kind === 'shared' ? !/^shared-\d+-\d+\.lock$/.test(name) : name !== EXCLUSIVE) continue;
    const file = path.join(LOCK_DIR, name);
    let info = null, age = Infinity;
    try { age = Date.now() - fs.statSync(file).mtimeMs; info = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { /* being written, or gone */ }
    const pid = info?.pid ?? Number(name.split('-')[1]);
    const stale = info ? !Number.isInteger(pid) || !alive(pid) : (kind === 'exclusive' ? age > 2000 : !alive(pid));
    if (stale) { try { fs.unlinkSync(file); } catch { /* removed by someone else */ } continue; }
    live.push({ file, pid, who: info?.who ?? 'unknown' });
  }
  return live;
}
function releaser(file) {
  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    try { if (JSON.parse(fs.readFileSync(file, 'utf8')).pid === process.pid) fs.unlinkSync(file); } catch { /* already gone */ }
  };
  process.once('exit', release);
  return release;
}

/** A heavy suite: wait (at most maxWaitMs) while a timing suite measures, then hold a shared place. Never rejects.
 *  Resolves {held, waitedMs, release(), timedOut?, holder?, error?}. */
export async function acquireShared(who, maxWaitMs) {
  const t0 = Date.now();
  if (!ensureDir()) return { held: false, waitedMs: 0, release() { }, error: 'no lock directory' };
  for (;;) {
    const ex = holders('exclusive');
    if (!ex.length) {
      const file = path.join(LOCK_DIR, `shared-${process.pid}-${counter++}.lock`);
      try { fs.writeFileSync(file, JSON.stringify({ pid: process.pid, who }), { flag: 'wx' }); }
      catch (e) { return { held: false, waitedMs: Date.now() - t0, release() { }, error: e.code }; }
      return { held: true, waitedMs: Date.now() - t0, release: releaser(file) };
    }
    if (Date.now() - t0 >= maxWaitMs) return { held: false, waitedMs: Date.now() - t0, release() { }, timedOut: true, holder: ex[0].who };
    await sleep(200);
  }
}

/** A timing suite: take the exclusive place (at most maxWaitMs in all), then wait for the shared holders already running
 *  to finish. Never rejects. Resolves {held, waitedMs, release(), timedOut?, holder?, sharedLeft?, error?}: `held` is
 *  true only when it measures alone. */
export async function acquireExclusive(who, maxWaitMs) {
  const t0 = Date.now();
  if (!ensureDir()) return { held: false, waitedMs: 0, release() { }, error: 'no lock directory' };
  const file = path.join(LOCK_DIR, EXCLUSIVE);
  let release = null;
  while (!release) {
    try {
      fs.writeFileSync(file, JSON.stringify({ pid: process.pid, who }), { flag: 'wx' });
      release = releaser(file);
    } catch (e) {
      if (e.code !== 'EEXIST') return { held: false, waitedMs: Date.now() - t0, release() { }, error: e.code };
      const ex = holders('exclusive'); // removes a stale one, so the next try can take it
      if (ex.length && Date.now() - t0 >= maxWaitMs) return { held: false, waitedMs: Date.now() - t0, release() { }, timedOut: true, holder: ex[0].who };
      if (ex.length) await sleep(200);
    }
  }
  for (;;) {
    const sh = holders('shared');
    if (!sh.length) return { held: true, waitedMs: Date.now() - t0, release };
    if (Date.now() - t0 >= maxWaitMs) return { held: false, waitedMs: Date.now() - t0, release, timedOut: true, holder: sh.map((h) => h.who).join(', '), sharedLeft: sh.length };
    await sleep(200);
  }
}
/** Before #400's shared lock this was the one mutex; a timing suite now takes the exclusive place. */
export const acquireCpu = acquireExclusive;

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
