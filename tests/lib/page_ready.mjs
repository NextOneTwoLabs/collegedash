// Waiting for the page's first view in a `vm`, instead of a fixed delay (shared by the tests that boot the whole inline
// script against a stub DOM: list_url_state, route_focus, phone_sheet, programs_rail).
//
// Why: those tests used to wait a fixed 250-300 ms after starting the script. The page loads the full program index
// (about 1.9 MB of JSON) before its first route, and in the full Node suite - files running in parallel on a busy
// machine - that can take longer, so a test read the address or the DOM before the first route had run and failed
// now and then (#/rpi read as '#/programs' instead of '#/programs?sort=rpi&view=table').
//
// What it waits for, in order:
//   1. the page's own signal: the promise boot() returns, which settles once the index has loaded and the first
//      route() has been called (or the load-failed view drawn). bootable() captures it by turning the script's final
//      `boot();` into `globalThis.__booted = boot();` - the same call, its result kept - and fails loudly if that line
//      is ever not there;
//   2. then the page's own follow-up work: every fetch it started has answered and every short timer it set (at most
//      SHORT_MS: hash changes, which the stub fires on a 0 ms timer, the 80 ms typing debounce, requestAnimationFrame)
//      has run, with nothing new for QUIET_MS. Long timers (session renewal, polling) are not waited for.
// A page that never goes quiet fails after MAX_MS with what was still pending, rather than hanging.
import assert from 'node:assert/strict';

export const SHORT_MS = 300, QUIET_MS = 30, MAX_MS = 15000;

// The inline script, with boot()'s promise kept on globalThis.__booted.
export function bootable(src) {
  const m = src.match(/^boot\(\);$/gm);
  assert.equal(m?.length, 1, 'index.html: the inline script no longer ends with one `boot();` line; update tests/lib/page_ready.mjs');
  return src.replace(/^boot\(\);$/m, 'globalThis.__booted = boot();');
}

// Wraps the sandbox's setTimeout, clearTimeout and fetch so the page's pending work can be counted. Call it after the
// sandbox object is built and before the script runs. Returns the counter idle() reads.
export function track(sandbox) {
  const pending = { timers: new Set(), fetches: 0, last: Date.now() };
  const st = sandbox.setTimeout, ct = sandbox.clearTimeout, f = sandbox.fetch;
  sandbox.setTimeout = (fn, ms = 0, ...args) => {
    let h = null;
    h = st(() => { pending.timers.delete(h); pending.last = Date.now(); if (typeof fn === 'function') fn(...args); }, ms);
    if (ms <= SHORT_MS) pending.timers.add(h);
    pending.last = Date.now();
    return h;
  };
  sandbox.clearTimeout = h => { pending.timers.delete(h); ct(h); };
  if (typeof f === 'function') {
    sandbox.fetch = async (...args) => {
      pending.fetches++; pending.last = Date.now();
      try { return await f(...args); } finally { pending.fetches--; pending.last = Date.now(); }
    };
  }
  if (sandbox.requestAnimationFrame) sandbox.requestAnimationFrame = cb => sandbox.setTimeout(cb, 0);
  return pending;
}

const tick = ms => new Promise(r => setTimeout(r, ms));

// Resolves once the page has nothing short pending and has been quiet for QUIET_MS.
export async function idle(pending) {
  const start = Date.now();
  // Quiet is counted from now, never from before: boot() can settle long after the page's last tracked call (parsing
  // the index is synchronous work), and a 0 ms timer the stub DOM set during the first route (a hash change) must
  // still get its turn.
  pending.last = Math.max(pending.last, start);
  for (;;) {
    if (!pending.timers.size && !pending.fetches && Date.now() - pending.last >= QUIET_MS) return;
    assert.ok(Date.now() - start < MAX_MS, `the page did not go quiet in ${MAX_MS} ms (${pending.timers.size} short timers, ${pending.fetches} fetches pending)`);
    await tick(5);
  }
}

// The first view: boot()'s promise, then quiet.
export async function ready(sb, pending) {
  assert.ok(sb.__booted && typeof sb.__booted.then === 'function', 'boot() was not captured (use bootable() on the script)');
  await sb.__booted;
  await idle(pending);
}
