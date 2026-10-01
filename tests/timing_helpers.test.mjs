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
