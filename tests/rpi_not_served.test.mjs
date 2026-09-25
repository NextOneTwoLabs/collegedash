// The site does not serve the RPI tables under public/data/rpi, and the page does not need them (issue #100).
//
//     node --test tests/rpi_not_served.test.mjs
//
// The owner's decision: keep the RPI files in the repo, where the build and the collector read them, and
// block the web address. The files are therefore still uploaded as static assets, and two things together
// are what keeps them off the site:
//
//   1. wrangler.toml lists "/data/rpi/*" in [assets] run_worker_first. A static asset is served BEFORE the
//      Worker runs unless its path matches that list, so without the entry worker.js is never asked.
//   2. worker.js answers 404 for any path under /data/rpi.
//
// Deleting either one exposes every table again, and nothing on the site would look different. So this
// file checks each one on its own terms, against every file actually under public/data/rpi (not a sample),
// and a third group checks that the page no longer asks for the table and that each card's RPI is what the
// table would have given it.
//
// How the pattern is matched. Workers static assets compile each run_worker_first entry the way
// cloudflare/workers-sdk's asset-worker does (rules-engine.ts, generateStaticRoutingRuleMatcher): split
// the rule on "*", regex-escape each piece, join with ".*", anchor with ^...$, no flags. The result is
// tested against URL.pathname, and routing is decided before the asset server checks whether a file
// exists. `rule` below is that algorithm, so "*" is deep (it covers weekly/2025/...) and matching is
// case-sensitive. A negative "!" entry that matches wins over a positive one.
//
// What this cannot prove: that Cloudflare still behaves that way on the day it deploys. That is what
// .github/workflows/rpi-not-served.yml is for; it asks the live site.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import worker from '../worker.js';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const PUBLIC = path.join(ROOT, 'public');
const RPI_DIR = path.join(PUBLIC, 'data', 'rpi');
const HOST = 'https://college.nextonetwo.com';

/* ---------- wrangler.toml: only the two keys this depends on ---------- */
// Not a TOML parser. It reads `directory` and `run_worker_first` out of the [assets] table and fails
// loudly on any shape it does not recognise, rather than guessing, so a reformatted file is a red test
// someone reads and not a silent pass.
function readAssetsConfig(text) {
  const lines = text.split(/\r?\n/);
  const start = lines.findIndex(l => l.trim() === '[assets]');
  assert.ok(start >= 0, 'wrangler.toml has no [assets] table');
  let end = lines.findIndex((l, i) => i > start && /^\s*\[/.test(l));
  if (end < 0) end = lines.length;
  const body = lines.slice(start + 1, end).map(l => l.replace(/^\s*#.*$/, '')).join('\n');
  const dir = body.match(/^\s*directory\s*=\s*"([^"]*)"\s*$/m);
  assert.ok(dir, 'wrangler.toml [assets] has no directory = "..." line this test can read');
  const rwf = body.match(/^\s*run_worker_first\s*=\s*(true|false|\[[\s\S]*?\])\s*$/m);
  let runWorkerFirst = false; // Cloudflare's default when the key is absent
  if (rwf) runWorkerFirst = JSON.parse(rwf[1].replace(/,\s*\]$/, ']'));
  return { directory: dir[1], runWorkerFirst };
}
const escapeRegex = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const rule = r => new RegExp('^' + r.split('*').map(escapeRegex).join('.*') + '$');
function workerRunsFirst(runWorkerFirst, pathname) {
  if (runWorkerFirst === true) return true;
  if (!Array.isArray(runWorkerFirst)) return false;
  const neg = runWorkerFirst.filter(r => r.startsWith('!')).map(r => rule(r.slice(1)));
  const pos = runWorkerFirst.filter(r => !r.startsWith('!')).map(rule);
  return pos.some(re => re.test(pathname)) && !neg.some(re => re.test(pathname));
}

/* ---------- every file under public/data/rpi, as the URL path it is uploaded at ---------- */
function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(e =>
    e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]);
}
const RPI_FILES = walk(RPI_DIR);
const urlPathOf = file => '/' + path.relative(PUBLIC, file).split(path.sep).join('/');
const RPI_PATHS = RPI_FILES.map(urlPathOf);

test('the files this protects exist, so no check below can pass by having nothing to check', () => {
  assert.ok(RPI_PATHS.includes('/data/rpi/current.json'), 'public/data/rpi/current.json is gone');
  assert.ok(RPI_PATHS.some(p => /^\/data\/rpi\/\d{4}\.json$/.test(p)), 'no archive year file under public/data/rpi');
  assert.ok(RPI_PATHS.some(p => p.startsWith('/data/rpi/weekly/')), 'no weekly snapshot under public/data/rpi');
});

/* ---------- 1. routing: every table reaches the Worker before the asset server ---------- */
const CONFIG = readAssetsConfig(fs.readFileSync(path.join(ROOT, 'wrangler.toml'), 'utf8'));

test('wrangler.toml deploys public/ as the asset directory, so the URL paths below are the real ones', () => {
  assert.equal(CONFIG.directory, './public',
    'assets.directory changed; the URL each RPI file is served at changed with it, so re-derive this test');
});

test('every file under public/data/rpi is routed to the Worker first', () => {
  const served = RPI_PATHS.filter(p => !workerRunsFirst(CONFIG.runWorkerFirst, p));
  assert.deepEqual(served, [],
    'these RPI files would be served as static assets without the Worker ever running; ' +
    'wrangler.toml [assets] run_worker_first needs "/data/rpi/*"');
});

test('the matcher is not vacuous: static assets outside data/archive bypass the worker', () => {
  // Static assets outside data/archive are served straight from assets
  for (const p of ['/index.html', '/robots.txt', '/favicon.ico']) {
    assert.equal(workerRunsFirst(CONFIG.runWorkerFirst, p), false, `${p} runs the Worker first`);
  }
  for (const p of ['/data/programs/index.json', '/data/registry.json', '/archive/2024.json', '/api/feedback']) {
    assert.equal(workerRunsFirst(CONFIG.runWorkerFirst, p), true, `${p} should run Worker first`);
  }
});

/* ---------- 2. the Worker refuses every one of them ---------- */
// An ASSETS binding that would happily serve the real file. A 404 from the Worker therefore means the
// Worker refused it, not that the stub had nothing to give.
function assetsEnv() {
  const calls = [];
  const env = {
    calls,
    FEEDBACK: { put() { } },
    ASSETS: {
      fetch(req) {
        const p = new URL(req.url).pathname;
        calls.push(p);
        const file = path.join(PUBLIC, decodeURIComponent(p));
        return file.startsWith(PUBLIC) && fs.existsSync(file) && fs.statSync(file).isFile()
          ? new Response(fs.readFileSync(file), { status: 200, headers: { 'content-type': 'application/json' } })
          : new Response(null, { status: 404 });
      },
    },
  };
  return env;
}
async function expectRefused(url, init) {
  const env = assetsEnv();
  const res = await worker.fetch(new Request(url, init), env);
  assert.equal(res.status, 404, `${init?.method || 'GET'} ${url} answered ${res.status}`);
  // In issue #240, blocked raw data endpoints return JSON 404 on GET and empty body on HEAD
  if ((init?.method || 'GET').toUpperCase() === 'HEAD') {
    assert.equal(await res.text(), '', `${url}: HEAD 404 has a non-empty body`);
  } else {
    assert.equal(await res.text(), '{"ok":false,"error":"Not found"}', `${url}: GET 404 does not match JSON body`);
  }
  assert.deepEqual(env.calls, [], `${url}: the Worker handed the request to the asset server`);
}

test('the Worker answers 404 for every file under public/data/rpi, and never asks the asset server', async () => {
  for (const p of RPI_PATHS) {
    await expectRefused(HOST + p);
    await expectRefused(HOST + p, { method: 'HEAD' });
  }
});

test('the Worker refuses encoded, doubled-slash, differently-cased and workers.dev forms too', async () => {
  // The run_worker_first pattern sees the raw pathname, so these miss it; the asset server then decodes
  // them and redirects to the canonical /data/rpi/... path, which does match. The Worker refuses them on
  // the decoded form anyway, so that no route into it can serve a table.
  const variants = [
    '/data/rp%69/current.json', '/data/rpi%2Fcurrent.json', '//data/rpi/current.json', '/data//rpi/2007.json',
    '/DATA/RPI/current.json', '/data/rpi/', '/data/rpi', '/data/rpi/weekly/2025/2025-12-08.json?x=1',
    '/data/rpi/does-not-exist.json',
  ];
  for (const p of variants) await expectRefused(HOST + p);
  await expectRefused('https://collegedash.nextonetwolabs.workers.dev/data/rpi/current.json');
});

test('everything else the Worker handles is unaffected', async () => {
  const env = assetsEnv();
  const apiRes = await worker.fetch(new Request(`${HOST}/api/v1/programs`), env);
  assert.equal(apiRes.status, 200);
  assert.ok(apiRes.headers.get('content-type')?.startsWith('application/json'));

  for (const p of ['/']) {
    const e = assetsEnv();
    await worker.fetch(new Request(HOST + p), e);
    assert.deepEqual(e.calls, [p], `${p} did not reach the asset server`);
  }

  const status = await worker.fetch(new Request(`${HOST}/api/status`), env);
  assert.equal(status.status, 200);
  assert.deepEqual(await status.json(), { local: false });

  const puts = [];
  const feedback = await worker.fetch(new Request(`${HOST}/api/feedback`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ message: 'hi' }),
  }), { FEEDBACK: { put: (k, v, o) => puts.push(k) } });
  assert.equal(feedback.status, 200);
  assert.equal(puts.length, 1);
});

/* ---------- 3. the page ---------- */
test('the page names no data/rpi path', () => {
  const html = fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8');
  const hits = html.split(/\r?\n/).map((l, i) => [i + 1, l]).filter(([, l]) => l.includes('data/rpi'));
  assert.deepEqual(hits, [], 'public/index.html refers to data/rpi, which the site answers with 404');
});

// The page's inline script in a vm against a stub DOM, as tests/division_and_name_sort.test.mjs does.
function loadPage() {
  const lines = fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8').split(/\r?\n/);
  const a = lines.findIndex(l => l.trim() === '<script>');
  const b = lines.findIndex(l => l.trim() === '</script>');
  assert.ok(a >= 0 && b > a, 'public/index.html: could not find the inline <script>');
  const src = lines.slice(a + 1, b).join('\n')
    + '\n;Object.assign(globalThis, { S, rpiOf, rpiCell, tableHtml, cardHtml, loadIndex, rpiSeason });\n';
  const els = new Map();
  const el = name => ({
    _name: name, innerHTML: '', textContent: '', value: '', title: '', hidden: false, scrollTop: 0, dataset: {}, style: {},
    classList: { add() { }, remove() { }, toggle: () => false, contains: () => false },
    setAttribute() { }, getAttribute: () => null, addEventListener() { }, removeEventListener() { },
    querySelector: () => el('child'), querySelectorAll: () => [], closest: () => null, matches: () => false, focus() { }, contains: () => false,
  });
  const fetchLog = [];
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, Map, Set, Date, JSON, Math, Number, String, Array, Object, RegExp, Intl,
    isNaN, parseInt, parseFloat, URL, encodeURIComponent, decodeURIComponent,
    document: {
      documentElement: el('html'), body: el('body'), addEventListener() { }, createElement: el, querySelectorAll: () => [],
      querySelector: s => { if (!els.has(s)) els.set(s, el(s)); return els.get(s); },
    },
    location: { hash: '', replace(h) { this.hash = h; } }, history: { replaceState() { } },
    matchMedia: () => ({ matches: false }), innerWidth: 1400, addEventListener() { },
    localStorage: { getItem: () => null, setItem() { }, removeItem() { } },
    fetch: async url => {
      fetchLog.push(url);
      let rel = url.replace(/^\//, '');
      if (rel.startsWith('api/v1/')) {
        const sub = rel.slice('api/v1/'.length);
        if (sub === 'programs') rel = 'data/programs/index.json';
        else if (sub.startsWith('programs/')) rel = `data/programs/${sub.slice('programs/'.length)}.json`;
        else if (sub === 'camps') rel = 'data/camps/index.json';
        else if (sub === 'trends') rel = 'data/trends/index.json';
        else if (sub === 'commitments') rel = 'data/commitments/index.json';
        else if (sub === 'status') rel = 'archive/refresh-state.json';
      }
      const file = path.join(PUBLIC, rel);
      if (!file.startsWith(PUBLIC) || !fs.existsSync(file)) return { ok: false, status: 404, async json() { throw new Error('404'); } };
      const body = fs.readFileSync(file, 'utf8');
      return { ok: true, status: 200, async json() { return JSON.parse(body); } };
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  new vm.Script(src, { filename: 'public/index.html' }).runInContext(sandbox);
  return { sandbox, fetchLog };
}

test('loading the page requests no RPI table', async () => {
  const { sandbox, fetchLog } = loadPage();
  await sandbox.loadIndex();
  for (let i = 0; i < 10; i++) await new Promise(r => setTimeout(r, 0));
  assert.ok(fetchLog.includes('/api/v1/programs') || fetchLog.includes('data/programs/index.json'), 'the page did not load its index, so the log proves nothing');
  assert.deepEqual(fetchLog.filter(u => u.includes('rpi')), []);
});

// What the page used to show: the NCAA table's rank under the program's shortName || name, when the table
// is for the ranking season, else the program's own row. This is that rule, written against the committed
// table, so a program whose published row disagrees with the table it was built from fails here by name.
test('every program shows the RPI it showed when the page read the table, on the card and in the table', async () => {
  const { sandbox } = loadPage();
  const idx = await sandbox.loadIndex();
  const table = JSON.parse(fs.readFileSync(path.join(RPI_DIR, 'current.json'), 'utf8'));
  const bySchool = table.season === sandbox.rpiSeason() ? new Map(table.teams.map(t => [t.school, t.rank])) : new Map();
  const programs = idx.programs;
  const registry = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data', 'registry.json'), 'utf8'));
  // build.py publishes an entry of registry.programs only when it is onboarded AND its division is in
  // onboardedDivisions; a new program waits for its onboard run, heldPrograms (issue #100) are never
  // published, and a staged division (issue #94) is collected but not published, so `onboarded` alone
  // stopped being the rule the moment the first D2 batch was collected
  const published = registry.programs.filter(p => p.onboarded && registry.onboardedDivisions.includes(p.division));
  assert.deepEqual(programs.map(p => p.slug).sort(), published.map(p => p.slug).sort(),
    'the index does not hold every published registry program');
  assert.ok(programs.length > 0);
  const wrong = [];
  // #248: every published D1 program carries the ids.ncaaName the build joins the NCAA RPI table by. West Florida
  // (D1 from 2026) was onboarded without one, so its 2026 rank (#171) never showed; the registry now has it.
  const noName = published.filter(p => p.division === 'D1' && !(p.ids || {}).ncaaName).map(p => p.slug);
  assert.deepEqual(noName, [], 'published D1 programs without ids.ncaaName: the build cannot join their RPI rank');
  // #365: strict, no allowance. The index was rebuilt with West Florida's name, so every D1 program whose registry
  // ncaaName the RPI season's table ranks must carry that join in the committed index.
  const byName = new Map(registry.programs.map(p => [p.slug, (p.ids || {}).ncaaName]));
  const unjoined = programs.filter(p => p.division === 'D1' && bySchool.has(byName.get(p.slug)) && sandbox.rpiOf(p) == null).map(p => p.slug);
  assert.deepEqual(unjoined, [], 'D1 programs the RPI table ranks under their registry ncaaName but the index does not join');
  for (const p of programs) {
    const before = bySchool.get(p.shortName || p.name)
      ?? (p.lastSeason?.year === sandbox.rpiSeason() ? p.lastSeason.rpiRank : null)
      ?? (p.rpiHistory || []).find(r => r.year === sandbox.rpiSeason())?.rank ?? null;
    const shown = before == null ? '—' : '#' + before;
    const card = sandbox.cardHtml(p);
    const tableRow = sandbox.tableHtml([p]);
    const cardFact = card.match(/RPI \d{4}(?: \(in progress\))?<\/[^>]+>\s*<[^>]+>([^<]*)</);
    const rankCell = tableRow.match(/<span class="rank-num[^"]*">([^<]*)<\/span>/);
    // Since issue #115 a program with no RPI shows no RPI fact on its card, and a one-row table for it has
    // no rank column at all - the em dash is only for a program that shares a table with a ranked one.
    // Every Division II program is such a program.
    const cardOk = before == null ? cardFact === null : cardFact?.[1] === shown;
    const tableOk = before == null ? rankCell === null : rankCell?.[1] === String(before);
    if (sandbox.rpiOf(p) !== before || sandbox.rpiCell(p) !== shown || !cardOk || !tableOk) {
      wrong.push(`${p.slug}: was ${shown}, now rpiOf ${sandbox.rpiOf(p)}, card ${cardFact?.[1] ?? '(no fact)'}, table ${rankCell?.[1] ?? '(no column)'}`);
    }
  }
  assert.deepEqual(wrong, [], `${wrong.length} of ${programs.length} programs changed`);
  // the two branches above are both exercised by the shipped index, or one of them proves nothing
  const ranked = programs.filter(p => sandbox.rpiOf(p) != null).length;
  assert.ok(ranked > 0 && ranked < programs.length,
    `every published program is on the same side of the RPI check (${ranked} of ${programs.length} ranked)`);
});
