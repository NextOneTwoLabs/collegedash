// The helper behind the page tests' first-view wait (tests/lib/page_ready.mjs; Bianque's review of the fix): it waits
// for the page's own boot() and then for quiet, never forever.
//
//     node --test tests/page_ready.test.mjs
//
// Made-up sandboxes only: a boot() that settles, one that never does, a page that never goes quiet, and a script that
// lost its `boot();` line. The time cap is passed small here (the page tests use the default 15 s).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bootable, track, ready, idle, _resetForTest, MAX_MS } from './lib/page_ready.mjs';

const sandbox = (booted, extra = {}) => {
  const sb = { setTimeout, clearTimeout, fetch: async () => ({ ok: true }), requestAnimationFrame: f => setTimeout(f, 0), ...extra };
  const pending = track(sb);
  sb.__booted = booted;
  return { sb, pending };
};

test('the default cap is 15 s', () => assert.equal(MAX_MS, 15000));

test('ready(): boot() settles, then the page\'s short timers and fetches run, then it resolves', async () => {
  _resetForTest();
  let done = false;
  const { sb, pending } = sandbox(Promise.resolve());
  sb.setTimeout(() => { sb.fetch('/x').then(() => sb.setTimeout(() => { done = true; }, 50)); }, 20);
  await ready(sb, pending, { max: 2000 });
  assert.ok(done, 'resolved before the page\'s own follow-up work ran');
});

test('ready(): a boot() that never settles fails within the cap and names what is pending - it never hangs', async () => {
  _resetForTest();
  const { sb, pending } = sandbox(new Promise(() => { }));
  const t0 = Date.now();
  await assert.rejects(ready(sb, pending, { max: 200 }), /boot\(\) did not settle in 200 ms \(0 short timers, 0 fetches pending\)/);
  assert.ok(Date.now() - t0 < 1500, 'the wait was not capped');
});

test('after one page never settled, later waits in the same file fail at once with the first message', async () => {
  _resetForTest();
  const stuckPage = sandbox(new Promise(() => { }));
  await assert.rejects(ready(stuckPage.sb, stuckPage.pending, { max: 100 }));
  const fine = sandbox(Promise.resolve());
  const t0 = Date.now();
  await assert.rejects(ready(fine.sb, fine.pending, { max: 5000 }), /an earlier page in this file never settled; not waiting again \(boot\(\) did not settle in 100 ms/);
  assert.ok(Date.now() - t0 < 200, 'the second wait was not immediate');
  _resetForTest();
});

test('idle(): a page that never goes quiet fails within the cap and counts its pending timers', async () => {
  _resetForTest();
  const { sb, pending } = sandbox(Promise.resolve());
  let on = true;
  const again = () => { if (on) sb.setTimeout(again, 10); };  // a page that keeps re-arming a short timer
  again();
  try {
    await assert.rejects(idle(pending, { max: 200 }), /the page did not go quiet in 200 ms \(1 short timers, 0 fetches pending\)/);
  } finally { on = false; _resetForTest(); }  // stop it, or the process never exits
});

test('bootable(): keeps boot()\'s promise, and fails loudly when the script no longer ends with one `boot();` line', () => {
  assert.equal(bootable('a();\nboot();\n'), 'a();\nglobalThis.__booted = boot();\n');
  assert.throws(() => bootable('a();\nboot().then(x);\n'), /no longer ends with one `boot\(\);` line/);
  assert.throws(() => bootable('boot();\nboot();\n'), /no longer ends with one `boot\(\);` line/);
});
