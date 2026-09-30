// Speed measurements, the page side (issue #394, round-2 plan approved by Bianque on the issue): the device table, the
// once-per-load sampling latch, at most 3 reports, one per view kind, the wire format (exactly the Worker's FIELDS, and
// accepted by the Worker's own parser), a profile's size sent as 0, no URL, hash or slug, and the transport fallback.
//
//     node --test tests/perf_page.test.mjs
//
// The speed block is cut out of public/index.html's inline script and run in a vm with stub browser globals, so what is
// tested is the page's own code. Offline, under tests/netguard.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { FIELDS, pagePoint } from '../api/perf.mjs';

const HTML = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public', 'index.html'), 'utf8').replace(/\r\n/g, '\n');
const START = HTML.indexOf('/* ---------- speed measurements (issue #394');
const END = HTML.indexOf('async function getJSON(url, opts) {');
const BLOCK = HTML.slice(START, END);
const fn = name => { const a = HTML.indexOf(`function ${name}(`); return HTML.slice(a, HTML.indexOf('\n}\n', a)); };

// A fresh copy of the block with stub globals. `now` is the clock the tests move; frames run at once.
// duringFrame(n): called as the n-th animation frame is requested, before it runs (a test hides the page there).
function load({ random = 0, sendBeacon = 'ok', entries = null, coarse = true, screen = { width: 390, height: 844 }, hidden = false, frameWait = 0,
  duringFrame = null } = {}) {
  const sent = [], fetched = [], listeners = {};
  let frames = 0;
  const clock = { now: 0 };
  const byName = entries || (() => []);
  const sandbox = {
    Promise, Math: Object.assign(Object.create(Math), { random: () => random }), Number, JSON, Set, URL, Blob, setTimeout,
    location: { href: 'https://college.nextonetwo.com/#/' },
    document: { get visibilityState() { return sandbox.hidden ? 'hidden' : 'visible'; },
      addEventListener(type, f) { (listeners[type] ||= []).push(f); } }, hidden,
    performance: { now: () => clock.now, getEntriesByName: n => byName(n) },
    // frameWait: how long each frame is held (a browser holds frames while the page is hidden)
    requestAnimationFrame: f => { frames++; if (duringFrame) duringFrame(frames); clock.now += frameWait; f(); },
    matchMedia: q => ({ matches: q === '(pointer: coarse)' ? coarse : false }),
    screen,
    navigator: sendBeacon === 'absent' ? {} : { sendBeacon(url, blob) { if (sendBeacon === 'throws') throw new Error('x'); sent.push({ url, blob }); return sendBeacon === 'ok'; } },
    fetch(url, opts) { fetched.push({ url, opts }); return Promise.resolve({}); },
  };
  vm.createContext(sandbox);
  new vm.Script(BLOCK + '\n;globalThis.__perf = { PERF, PERF_VIEWS, perfDevice, perfLatch, perfRes, perfLoaded, perfBody, perfSend, perfRendered, perfView };', { filename: 'public/index.html' }).runInContext(sandbox);
  // setHidden: the page is hidden or shown, and the browser tells the page's visibilitychange listeners, as it does
  const setHidden = v => { sandbox.hidden = v; for (const f of listeners.visibilitychange || []) f(); };
  return { ...sandbox.__perf, sent, fetched, clock, listeners, setHidden };
}
const answer = rate => ({ headers: { get: k => (k === 'x-collegedash-perf' ? rate : null) } });
const settle = () => new Promise(r => setTimeout(r, 0));
const bodyOf = async s => JSON.parse(await s.blob.text());
// A resource timing entry as a browser gives it for a same-origin fetch.
const entry = (over = {}) => ({ entryType: 'resource', requestStart: 100, responseStart: 180, responseEnd: 490, transferSize: 171300,
  encodedBodySize: 171000, decodedBodySize: 1900000, serverTiming: [{ name: 'gate', duration: 3 }, { name: 'total', duration: 45 }], ...over });

test('the block is in the page, and the page calls it where the plan says', () => {
  assert.ok(START > 0 && END > START, 'the speed block sits right before getJSON');
  const get = fn('getJSON');
  assert.match(get, /noteSession\(r, sentAt\);\n\s+perfLatch\(r\);/, 'the rate is latched from every answer, the first one with a rate wins');
  assert.match(get, /const data = await r\.json\(\);\n\s+perfLoaded\(url\);[^\n]*\n\s+return data;/);
  const route = fn('route');
  for (const [view, render] of [['profile', 'renderProfile'], ['list', 'renderList'], ['camps', 'renderCamps'], ['trends', 'renderTrends']]) {
    assert.match(route, new RegExp(`go\\(perfView\\('${view}', ${render}\\(`), view);
  }
  assert.equal((route.match(/perfView\('list'/g) || []).length, 2, 'the list and a conference deep link');
});

test('never sent on visibilitychange, pagehide or a back-forward cache restore; never the user agent', () => {
  const code = BLOCK.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, ''); // the code, not its comments
  assert.ok(code.includes('function perfSend('), 'the code is really there');
  for (const word of ['pagehide', 'pageshow', 'beforeunload', 'unload', 'userAgent', 'userAgentData', 'navigator.connection']) {
    assert.ok(!code.includes(word), word);
  }
  // exactly one visibilitychange listener, record-only (#399 review): it notes when the page was hidden
  assert.equal((code.match(/visibilitychange/g) || []).length, 1, 'one visibilitychange listener, nothing else');
  assert.match(code, /document\.addEventListener\('visibilitychange', \(\) => \{ if \(document\.visibilityState === 'hidden'\) PERF\.hiddenAt = performance\.now\(\); \}\)/);
});

test('the visibilitychange listener only records: hiding and showing the page sends nothing', async () => {
  const p = load({ random: 0, entries: () => [entry()] });
  p.perfLatch(answer('1'));
  p.perfLoaded('/api/v1/programs');
  assert.equal(p.listeners.visibilitychange?.length, 1, 'the block registered its one listener');
  p.clock.now = 5000;
  p.setHidden(true);
  assert.equal(p.PERF.hiddenAt, 5000, 'it records when the page was hidden');
  p.setHidden(false);
  p.setHidden(true);
  p.setHidden(false);
  await settle();
  assert.equal(p.sent.length + p.fetched.length, 0, 'and never sends');
});

test('device: phone, tablet or desktop from pointer and the short side of the screen', () => {
  const { perfDevice } = load();
  for (const [coarse, w, h, d] of [[false, 390, 844, 'desktop'], [false, 1920, 1080, 'desktop'], [true, 390, 844, 'phone'], [true, 844, 390, 'phone'],
    [true, 599, 1000, 'phone'], [true, 600, 1000, 'tablet'], [true, 820, 1180, 'tablet'], [true, 1920, 1080, 'tablet']]) {
    assert.equal(perfDevice(coarse, w, h), d, `${coarse} ${w}x${h}`);
  }
});

test('latch: the first answer carrying a rate decides, once; sampled when random < rate', () => {
  let p = load({ random: 0.05 });
  p.perfLatch(answer(null));
  assert.equal(p.PERF.rate, null, 'an answer without the header (e.g. /api/status) decides nothing');
  p.perfLatch(answer('0.1'));
  assert.equal(p.PERF.rate, 0.1);
  assert.equal(p.PERF.sampled, true);
  p.perfLatch(answer('1'));
  assert.equal(p.PERF.rate, 0.1, 'never re-read on this page load');
  p = load({ random: 0.5 });
  p.perfLatch(answer('0.1'));
  assert.equal(p.PERF.sampled, false);
  for (const junk of ['0', '2', '-1', 'x', '']) {
    p = load({ random: 0 });
    p.perfLatch(answer(junk));
    assert.equal(p.PERF.sampled, false, JSON.stringify(junk));
  }
  p = load();
  p.perfLatch(null);
  p.perfLatch({ headers: { get() { throw new Error('x'); } } });
  assert.equal(p.PERF.rate, null, 'a broken answer throws nothing');
});

test('rate 1 (the owner\'s decision, #394): every page load is sampled, whatever Math.random gives', async () => {
  for (const random of [0, 0.5, 0.999999]) {
    const p = load({ random, entries: () => [entry()] });
    await visit(p, 'list', '/api/v1/programs', 'landing', { rate: '1' });
    assert.equal(p.PERF.sampled, true, String(random));
    assert.equal(p.sent.length, 1, String(random));
    const body = await bodyOf(p.sent[0]);
    assert.equal(body.rate, 1);
    assert.ok(pagePoint(JSON.stringify(body), 1, new Request('https://college.nextonetwo.com/api/perf')), 'the Worker accepts it at rate 1');
    assert.equal(pagePoint(JSON.stringify(body), 1, new Request('https://college.nextonetwo.com/api/perf')).doubles[9], 1, 'one page load per report');
  }
});

// The wording the owner approved on #394 (round-2 plan, §6), exactly, with only the rate phrase changed by the owner's
// decision of 2026-09-30: "some page loads (currently about 1 in 10) send" -> "every page load sends".
const APPROVED_ROUND_2 = 'To find out how fast the site loads, some page loads (currently about 1 in 10) send a short timing report after a '
  + 'view appears. It says which kind of view it was (the list, a program, trends or camps), whether the device is a phone, tablet or '
  + 'desktop, and how many milliseconds loading, reading and drawing the data took, plus the size of the shared list, trends and camps '
  + 'data. Our server also records how long it took to answer most data requests. We don\'t record your IP address, a session or '
  + 'visitor id, your browser\'s user agent, the page address, the program you opened, or anything you searched for. Reports are kept '
  + 'as timestamped rows in Cloudflare Analytics Engine, for up to three months, and are used only to make the site faster.';
const APPROVED_NOW = APPROVED_ROUND_2.replace('some page loads (currently about 1 in 10) send', 'every page load sends');

test('the About page card and docs/data-api.md say exactly the approved wording, with "every page load"', () => {
  assert.notEqual(APPROVED_NOW, APPROVED_ROUND_2, 'the rate phrase was found and changed');
  const faq = fn('renderFaq');
  const card = /<div class="card"><h3>Speed measurements<\/h3>\s*<p>([^<]*)<\/p><\/div>/.exec(faq);
  assert.ok(card, 'the About page has the card');
  assert.equal(card[1], APPROVED_NOW);
  const docs = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'docs', 'data-api.md'), 'utf8').replace(/\r\n/g, '\n');
  const quote = /> \*\*Speed measurements\.\*\* ([\s\S]*?)\n\n/.exec(docs);
  assert.ok(quote, 'docs/data-api.md quotes it');
  assert.equal(quote[1].replace(/\n> /g, ' ').replace(/\s+/g, ' ').trim(), APPROVED_NOW);
  assert.ok(!/1 in 10/.test(faq) && !/currently about 1 in 10/.test(docs), 'the old rate phrase is gone from both');
});

test('perfRes: only the four measured files, never a path with anything else in it', () => {
  const { perfRes } = load();
  assert.equal(perfRes('/api/v1/programs'), 'programs');
  assert.equal(perfRes('/api/v1/programs/stanford'), 'program');
  assert.equal(perfRes('/api/v1/trends'), 'trends');
  assert.equal(perfRes('/api/v1/camps'), 'camps');
  for (const u of ['/api/v1/status', 'api/status', '/api/v1/commitments', '/api/v1/programs/x?y=1', '/api/v1/programs?q=1']) assert.equal(perfRes(u), null, u);
});

test('the report: exactly the Worker\'s FIELDS, accepted by the Worker\'s own parser, no URL or slug', () => {
  const { perfBody } = load();
  const body = perfBody('list', { url: '/api/v1/programs', done: 610 }, 900, 'landing', entry(), 0.1, 'phone');
  assert.deepEqual(Object.keys(body), FIELDS, 'same keys, same order');
  assert.deepEqual(JSON.parse(JSON.stringify(body)), { v: 1, view: 'list', res: 'programs', device: 'phone', nav: 'landing', cache: 'network', server: 45, wait: 80,
    download: 310, parse: 120, render: 290, first: 900, tx: 171300, size: 1900000, rate: 0.1 });
  const point = pagePoint(JSON.stringify(body), 0.1, new Request('https://college.nextonetwo.com/api/perf'));
  assert.ok(point, 'the Worker accepts what the page sends');
  const prof = perfBody('profile', { url: '/api/v1/programs/stanford', done: 610 }, 900, 'in-app', entry(), 0.1, 'desktop');
  const text = JSON.stringify(prof);
  assert.ok(!/stanford|http|\/api|#/.test(text), 'no URL, path, hash or slug: ' + text);
  assert.equal(prof.first, 0, 'first render is for the landing view only');
  assert.ok(pagePoint(text, 0.1, new Request('https://college.nextonetwo.com/api/perf')));
});

test('privacy: two profiles of different lengths give identical size fields (0)', () => {
  const { perfBody } = load();
  const a = perfBody('profile', { url: '/api/v1/programs/short-one', done: 610 }, 900, 'in-app', entry({ transferSize: 4000, encodedBodySize: 3800, decodedBodySize: 21437 }), 0.1, 'phone');
  const b = perfBody('profile', { url: '/api/v1/programs/much-longer-program', done: 610 }, 900, 'in-app', entry({ transferSize: 41000, encodedBodySize: 40800, decodedBodySize: 189607 }), 0.1, 'phone');
  assert.deepEqual([a.tx, a.size], [0, 0]);
  assert.deepEqual([a.tx, a.size], [b.tx, b.size]);
  const list = perfBody('trends', { url: '/api/v1/trends', done: 610 }, 900, 'in-app', entry({ transferSize: 254000, decodedBodySize: 1200000 }), 0.1, 'phone');
  assert.deepEqual([list.tx, list.size], [254000, 1200000], 'shared files keep their exact sizes');
});

test('cache state from transfer size against body size; nothing measured, nothing sent', () => {
  const { perfBody } = load();
  const at = e => perfBody('list', { url: '/api/v1/programs', done: 610 }, 900, 'landing', entry(e), 0.1, 'phone');
  assert.equal(at({}).cache, 'network');
  assert.equal(at({ transferSize: 300 }).cache, 'revalidated', 'a 304: headers only');
  assert.equal(at({ transferSize: 0, requestStart: 0 }).cache, 'memory');
  assert.equal(at({ transferSize: 0, requestStart: 0 }).wait, 0);
  assert.equal(at({ serverTiming: undefined }).server, 0, 'no Server-Timing (older Safari): 0');
  assert.equal(perfBody('list', { url: '/api/v1/programs', done: 610 }, 900, 'landing', undefined, 0.1, 'phone'), null, 'no timing entry: no report');
  assert.equal(perfBody('compare', { url: '/api/v1/programs', done: 610 }, 900, 'landing', entry(), 0.1, 'phone'), null);
});

// A page load: the rate arrives, a view's data loads while it renders, the view is drawn.
async function visit(p, view, url, nav, { rate = '0.1' } = {}) {
  p.perfLatch(answer(rate));
  p.clock.now += 10;
  const rendering = p.perfView(view, Promise.resolve('rendered'), nav);
  p.clock.now += 100;
  p.perfLoaded(url);
  p.clock.now += 50;
  return rendering;
}

test('a sampled load: one report per view kind, at most 3, each right after its view renders', async () => {
  const p = load({ random: 0, entries: () => [entry()] });
  assert.equal(await visit(p, 'list', '/api/v1/programs', 'landing'), 'rendered', 'the render\'s own result passes through');
  assert.equal(p.sent.length, 1);
  assert.equal(p.sent[0].url, '/api/perf');
  assert.equal(p.sent[0].blob.type, 'text/plain');
  assert.equal((await bodyOf(p.sent[0])).nav, 'landing');
  await visit(p, 'list', '/api/v1/programs', 'in-app');
  assert.equal(p.sent.length, 1, 'the list once');
  await visit(p, 'profile', '/api/v1/programs/stanford', 'in-app');
  await visit(p, 'profile', '/api/v1/programs/yale', 'in-app');
  await visit(p, 'trends', '/api/v1/trends', 'in-app');
  await visit(p, 'camps', '/api/v1/camps', 'in-app');
  assert.deepEqual(await Promise.all(p.sent.map(async s => (await bodyOf(s)).view)), ['list', 'profile', 'trends'], 'three, one per kind');
});

test('not sampled, rate 0, or data already in memory: nothing is sent', async () => {
  let p = load({ random: 0.5, entries: () => [entry()] });
  await visit(p, 'list', '/api/v1/programs', 'landing');
  assert.equal(p.sent.length, 0, 'not sampled');
  p = load({ random: 0, entries: () => [entry()] });
  await visit(p, 'list', '/api/v1/programs', 'landing', { rate: '0' });
  assert.equal(p.sent.length + p.fetched.length, 0, 'rate 0');
  // in-app: the list's data came in with an earlier view (a profile landing loads the index too), so this list view
  // loaded nothing and has nothing of its own to report
  p = load({ random: 0, entries: () => [entry()] });
  p.perfLatch(answer('0.1'));
  p.perfLoaded('/api/v1/programs');
  p.clock.now += 100;
  await p.perfView('list', Promise.resolve(), 'in-app');
  assert.equal(p.sent.length, 0, 'an in-app view does not report a load from before it started');
});

test('the landing list, in boot()\'s real order: the index loads before route() runs, and is still reported', async () => {
  // boot() awaits loadIndex() before route(), so /api/v1/programs has finished before perfView('list', ..., 'landing')
  // records its start (Bianque, #397). The landing view is the one #395 needs most: it must be reported.
  const p = load({ random: 0, entries: () => [entry()] });
  p.clock.now = 300;
  p.perfLatch(answer('0.1'));
  p.perfLoaded('/api/v1/programs'); // boot(): loadIndex()
  p.clock.now = 420;
  await p.perfView('list', Promise.resolve(), 'landing'); // then route() -> renderList()
  assert.equal(p.sent.length, 1, 'one report for the landing list');
  const body = await bodyOf(p.sent[0]);
  assert.equal(body.res, 'programs');
  assert.equal(body.nav, 'landing');
  assert.ok(body.first > 0, 'with its first render time: ' + body.first);
  assert.equal(body.first, 420);
  assert.equal(body.render, 120, 'render runs from data ready to the drawn frame');
});

test('a view drawn while the page is hidden is not reported, and does not use up its view kind', async () => {
  // Found on the #399 preview: in a background tab the browser holds animation frames until the tab is shown, so the
  // render and first-render times would include the time spent hidden.
  const p = load({ random: 0, hidden: true, entries: () => [entry()] });
  await visit(p, 'list', '/api/v1/programs', 'landing', { rate: '1' });
  assert.equal(p.sent.length, 0, 'hidden when drawn: nothing sent');
  assert.equal(p.PERF.sent.size, 0, 'and the list can still be reported later');
  p.setHidden(false);
  await visit(p, 'list', '/api/v1/programs', 'in-app', { rate: '1' });
  assert.equal(p.sent.length, 1, 'shown again: the next list view is reported');
});

test('a slow paint on a visible page is reported, however long: that is the tail #395 needs', async () => {
  // Bianque, #399: the landing list's first frame lays out about 1,000 rows, and on a low-end phone that alone can take
  // seconds. Nothing but a real hide may drop it.
  for (const frameWait of [1000, 1500, 2500]) {
    const p = load({ random: 0, frameWait, entries: () => [entry()] });
    await visit(p, 'list', '/api/v1/programs', 'landing', { rate: '1' });
    assert.equal(p.sent.length, 1, `two frames of ${frameWait} ms, visible: reported`);
    assert.equal((await bodyOf(p.sent[0])).render, 50 + 2 * frameWait, 'render counts to the drawn frame');
  }
  const q = load({ random: 0, frameWait: 16, entries: () => [entry()] });
  await visit(q, 'list', '/api/v1/programs', 'landing', { rate: '1' });
  assert.equal((await bodyOf(q.sent[0])).render, 82, 'normal frames (50 + 2 x 16)');
});

test('a hide between draw and paint drops the report and frees its view kind', async () => {
  let p;
  // the page is hidden as the second frame is requested, and shown again later: the browser held the frame meanwhile
  p = load({ random: 0, frameWait: 16, entries: () => [entry()], duringFrame: n => { if (n === 2) { p.clock.now += 5; p.setHidden(true); p.clock.now += 4000; p.setHidden(false); } } });
  await visit(p, 'list', '/api/v1/programs', 'landing', { rate: '1' });
  assert.equal(p.sent.length, 0, 'hidden in between: dropped');
  assert.equal(p.PERF.sent.has('list'), false, 'and the list kind is free again');
  assert.equal(p.PERF.sent.size, 0, 'no slot used');
  await visit(p, 'list', '/api/v1/programs', 'in-app', { rate: '1' });
  assert.equal(p.sent.length, 1, 'a later list view is reported');
  // a hide before the view was drawn (and long over) does not drop a later view's report
  const q = load({ random: 0, frameWait: 16, entries: () => [entry()] });
  q.clock.now = 100;
  q.setHidden(true);
  q.setHidden(false);
  await visit(q, 'list', '/api/v1/programs', 'landing', { rate: '1' });
  assert.equal(q.sent.length, 1, 'an earlier hide is not this view\'s');
});

test('a report that cannot be measured frees its view kind', async () => {
  const p = load({ random: 0, entries: () => [] }); // no resource timing entry: perfBody gives null
  await visit(p, 'list', '/api/v1/programs', 'landing', { rate: '1' });
  assert.equal(p.sent.length, 0);
  assert.equal(p.PERF.sent.size, 0, 'nothing sent, nothing used up');
});

test('transport: sendBeacon, else fetch with keepalive; nothing throws', async () => {
  for (const mode of ['absent', 'false', 'throws']) {
    const p = load({ random: 0, sendBeacon: mode === 'false' ? false : mode, entries: () => [entry()] });
    await visit(p, 'list', '/api/v1/programs', 'landing');
    assert.equal(p.fetched.length, 1, mode);
    assert.equal(p.fetched[0].url, '/api/perf');
    assert.equal(p.fetched[0].opts.method, 'POST');
    assert.equal(p.fetched[0].opts.keepalive, true);
    assert.deepEqual(Object.keys(JSON.parse(p.fetched[0].opts.body)), FIELDS);
  }
  const p = load({ random: 0, sendBeacon: 'absent', entries: () => [entry()] });
  p.fetch = () => { throw new Error('offline'); };
  await visit(p, 'list', '/api/v1/programs', 'landing');
});

test('a failure in measuring never reaches rendering', async () => {
  const p = load({ random: 0, entries: () => { throw new Error('timing broken'); } });
  assert.equal(await visit(p, 'list', '/api/v1/programs', 'landing'), 'rendered');
  assert.equal(p.sent.length, 0);
  const q = load({ random: 0 });
  q.performance = undefined;
  await assert.rejects(q.perfView('list', Promise.reject(new Error('render failed')), 'landing'), /render failed/, 'a render failure still reaches route()\'s catch');
  await settle();
});
