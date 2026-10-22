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
// A page whose boot() never settles, or that never goes quiet, fails after MAX_MS with what was still pending, rather
// than hanging the run (Bianque on this fix). Once that has happened in a file (one process under node --test), every
// later ready() in it fails at once with the first failure's message, so a stuck page costs one wait, not one per test.
//
// requestAnimationFrame: track() routes it through the tracked setTimeout only when the sandbox already defines one, so
// a harness that adds requestAnimationFrame must define it before calling track().
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
  const pending = { timers: new Set(), fetches: 0, last: Date.now(), dead: false };
  const st = sandbox.setTimeout, ct = sandbox.clearTimeout, f = sandbox.fetch;
  // A page marked stuck (see fail()) is stopped: its pending short timers are cleared and it can set no new ones, so
  // a page that keeps re-arming a timer does not keep the test process alive.
  pending.stop = () => { pending.dead = true; for (const h of pending.timers) ct(h); pending.timers.clear(); };
  sandbox.setTimeout = (fn, ms = 0, ...args) => {
    if (pending.dead && ms <= SHORT_MS) return 0;
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

// The first failure to settle in this file, if any (see the header).
let stuck = null;
const fail = (msg, pending) => { stuck ||= msg; pending?.stop?.(); assert.fail(msg); };
const pendingText = pending => `${pending.timers.size} short timers, ${pending.fetches} fetches pending`;
// For tests/page_ready.test.mjs only: forget an earlier failure.
export const _resetForTest = () => { stuck = null; };

// Resolves once the page has nothing short pending and has been quiet for QUIET_MS.
export async function idle(pending, { max = MAX_MS } = {}) {
  if (stuck) assert.fail(`an earlier page in this file never settled; not waiting again (${stuck})`);
  const start = Date.now();
  // Quiet is counted from now, never from before: boot() can settle long after the page's last tracked call (parsing
  // the index is synchronous work), and a 0 ms timer the stub DOM set during the first route (a hash change) must
  // still get its turn.
  pending.last = Math.max(pending.last, start);
  for (;;) {
    if (!pending.timers.size && !pending.fetches && Date.now() - pending.last >= QUIET_MS) return;
    if (Date.now() - start >= max) fail(`the page did not go quiet in ${max} ms (${pendingText(pending)})`, pending);
    await tick(5);
  }
}

// The first view: boot()'s promise, then quiet.
export async function ready(sb, pending, { max = MAX_MS } = {}) {
  if (stuck) assert.fail(`an earlier page in this file never settled; not waiting again (${stuck})`);
  assert.ok(sb.__booted && typeof sb.__booted.then === 'function', 'boot() was not captured (use bootable() on the script)');
  let timer = null;
  const LATE = Symbol('late');
  const late = new Promise(r => { timer = setTimeout(() => r(LATE), max); });
  // A boot() that rejects is a real error (the page's boot() catches its own load failures and draws a card, so it
  // never should): rethrown, not taken as the page being ready (Bianque).
  const won = await Promise.race([Promise.resolve(sb.__booted).then(() => null, err => ({ err })), late]);
  clearTimeout(timer);
  if (won === LATE) fail(`boot() did not settle in ${max} ms (${pendingText(pending)})`, pending);
  if (won?.err !== undefined) throw won.err;
  await idle(pending, { max });
}
