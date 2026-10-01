// The readers-writer CPU lock in tests/timing_helpers.mjs (issue #400): heavy suites share it, a timing suite measures
// alone, stale holders are cleared, and no wait is unbounded. Runs against its own temporary lock directory, so it
// never touches the real one the other suites use. Offline.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'cd-lock-test-'));
process.env.CD_CPU_LOCK_DIR = DIR;
const { acquireShared, acquireExclusive, LOCK_DIR } = await import('./timing_helpers.mjs');
test.after(() => fs.rmSync(DIR, { recursive: true, force: true }));
const files = () => fs.readdirSync(DIR).sort();

test('the lock lives in the directory it was given', () => {
  assert.equal(LOCK_DIR, DIR);
});

test('shared holders run together; a timing suite waits for them, bounded, and then measures alone', async () => {
  const a = await acquireShared('heavy a', 1000), b = await acquireShared('heavy b', 1000);
  assert.ok(a.held && b.held, 'two shared holders could not run together');
  const blocked = await acquireExclusive('timing', 400);
  assert.equal(blocked.held, false);
  assert.equal(blocked.timedOut, true);
  assert.equal(blocked.sharedLeft, 2);
  assert.ok(blocked.waitedMs >= 400 && blocked.waitedMs < 3000, `the wait was not bounded: ${blocked.waitedMs} ms`);
  blocked.release(); a.release(); b.release();
  assert.deepEqual(files(), []);
  const alone = await acquireExclusive('timing', 1000);
  assert.equal(alone.held, true);
  alone.release();
});

test('while a timing suite holds it, a new shared holder waits (bounded) and is told who holds it', async () => {
  const ex = await acquireExclusive('recs_perf', 1000);
  assert.equal(ex.held, true);
  const late = await acquireShared('heavy', 400);
  assert.deepEqual([late.held, late.timedOut, late.holder], [false, true, 'recs_perf']);
  const second = await acquireExclusive('R-I', 400);
  assert.deepEqual([second.held, second.timedOut, second.holder], [false, true, 'recs_perf'], 'two timing suites measured at once');
  ex.release();
  const now = await acquireShared('heavy', 400);
  assert.equal(now.held, true);
  now.release();
});

test('a holder whose process is gone is stale: removed, and never waited for', async () => {
  const dead = 2 ** 22 + 12345; // far above any live pid on the test machines
  fs.writeFileSync(path.join(DIR, `shared-${dead}-0.lock`), JSON.stringify({ pid: dead, who: 'crashed heavy' }));
  fs.writeFileSync(path.join(DIR, 'exclusive.lock'), JSON.stringify({ pid: dead, who: 'crashed timing' }));
  const t0 = Date.now();
  const ex = await acquireExclusive('timing', 2000);
  assert.equal(ex.held, true);
  assert.ok(Date.now() - t0 < 1500, 'it waited for a dead holder');
  assert.deepEqual(files(), ['exclusive.lock']);
  assert.equal(JSON.parse(fs.readFileSync(path.join(DIR, 'exclusive.lock'), 'utf8')).pid, process.pid);
  ex.release();
  assert.deepEqual(files(), []);
});

test('#439 review: a stale exclusive.lock that cannot be removed still ends at the bound, pausing between tries', async () => {
  const dead = 2 ** 22 + 12346;
  const file = path.join(DIR, 'exclusive.lock');
  fs.writeFileSync(file, JSON.stringify({ pid: dead, who: 'crashed timing' }));
  // Held open without delete sharing (an indexer, antivirus) or another user's file: removing it fails. The helpers
  // and this test share the node:fs module object, so the stub reaches them.
  const real = fs.unlinkSync;
  let tries = 0;
  fs.unlinkSync = (p, ...rest) => {
    if (path.resolve(String(p)) === path.resolve(file)) { tries++; throw Object.assign(new Error('EPERM: operation not permitted'), { code: 'EPERM' }); }
    return real.call(fs, p, ...rest);
  };
  let ex, took;
  try {
    const t0 = Date.now();
    ex = await acquireExclusive('timing', 1000);
    took = Date.now() - t0;
  } finally { fs.unlinkSync = real; }
  assert.equal(ex.held, false);
  assert.equal(ex.timedOut, true);
  assert.ok(took >= 1000 && took < 2000, `the wait was not bounded: ${took} ms against 1000`);
  assert.ok(tries >= 2 && tries <= 10, `${tries} tries in ${took} ms: it spun instead of pausing`);
  fs.unlinkSync(file);
  assert.deepEqual(files(), []);
});
