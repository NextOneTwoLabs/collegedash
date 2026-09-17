// Tests for POST /api/ask in worker.js (issue #165): off by default, and server-side validation of the model's
// answer against the page's own vocabulary.
//
//     node --test tests/ask_worker.test.mjs
//
// They drive the Worker's own fetch handler with a stub env. The global fetch is replaced in every test that
// could reach the Anthropic API, and a test that is not meant to call it fails if it does. No key is used.
// Since #179 a switched-on request also needs a valid Cloudflare Access token and a budget namespace; both are
// stand-ins from tests/ask_access_helpers.mjs (a locally generated RSA key, an in-memory KV).
//
// What this proves:
//   - /api/ask answers exactly like an unknown /api route (it falls through to the assets) unless BOTH
//     ASK_ENABLED is "true" AND ANTHROPIC_API_KEY is set, and nothing calls the API while it is off;
//   - /api/status is byte-identical {"local":false} for everyone, on or off, token or not (ask availability is
//     the owner-only GET /api/ask/status since #179; its tests are in tests/ask_access_budget.test.mjs);
//   - no tracked file carries anything shaped like a key (the switched-on wrangler.toml values are checked in
//     tests/ask_enabled_config.test.mjs);
//   - when on, the request sent upstream uses the pinned model, the hard output-token limit, a json_schema
//     output format and the key only as a header, and the key never appears in any response;
//   - validation turns every answer the page could not show into {unsupported}: an unknown field, a
//     comparison the field does not allow, a display-unit value (admission 30), an unknown conference,
//     class or sort, an empty answer, unreadable JSON, a refusal and a truncated answer;
//   - the Worker's field keys, ops, sorts and regions are exactly those in public/index.html.
//
// ASK_WORKER and ASK_WRANGLER (optional) point at other copies of worker.js and wrangler.toml, so a broken
// copy can be shown failing through these same checks.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..');
const WORKER = process.env.ASK_WORKER || path.join(ROOT, 'worker.js');
const worker = (await import(pathToFileURL(WORKER).href)).default;
const { CERTS_URL, CERTS, accessVars, memoryKV, token } = await import(pathToFileURL(path.join(HERE, 'ask_access_helpers.mjs')).href);
const OWNER = await token();
const A = worker.ask;
const KEY = 'sk-test-0000-not-a-real-key';
const INDEX = JSON.parse(fs.readFileSync(path.join(ROOT, 'public', 'data', 'programs', 'index.json'), 'utf8'));

function env(extra = {}) {
  const assetCalls = [];
  return {
    assetCalls,
    ASSETS: {
      fetch: async (req) => {
        const url = new URL(req.url);
        assetCalls.push(url.pathname);
        if (url.pathname === '/data/programs/index.json') return Response.json(INDEX);
        return new Response('Not found', { status: 404, headers: { 'content-type': 'text/plain' } });
      },
    },
    ASK_BUDGET: memoryKV(),
    ...extra,
  };
}
const request = (pathname, init = {}) => new Request(`https://college.nextonetwo.com${pathname}`, init);
const post = (body, jwt = OWNER) => request('/api/ask', { method: 'POST', headers: { 'content-type': 'application/json', ...(jwt ? { 'cf-access-jwt-assertion': jwt } : {}) },
  body: typeof body === 'string' ? body : JSON.stringify(body) });

// Replace the global fetch for one call. `reply` builds the upstream Response; with none, any call fails the test.
async function withUpstream(reply, fn) {
  const calls = [];
  const real = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    if (String(url) === CERTS_URL) return Response.json(CERTS); // the Access team's public keys, not an upstream call
    calls.push({ url: String(url), init, body: init?.body ? JSON.parse(init.body) : null });
    if (!reply) throw new Error(`unexpected upstream call to ${url}`);
    return reply();
  };
  try {
    return { result: await fn(), calls };
  } finally {
    globalThis.fetch = real;
  }
}
const message = (out, stop_reason = 'end_turn') => () => Response.json({ type: 'message', stop_reason,
  content: [{ type: 'text', text: typeof out === 'string' ? out : JSON.stringify(out) }] });
const blank = { unsupported: null, reading: 'a reading', division: [], conf: [], region: [], classYear: [], cond: [], sort: null };

test('off by default: /api/ask is the same 404 as an unknown /api route, and nothing calls the API', async () => {
  const offs = { 'no variables': {}, 'enabled but no key': { ASK_ENABLED: 'true' }, 'key but not enabled': { ANTHROPIC_API_KEY: KEY },
    'enabled "1", not "true"': { ASK_ENABLED: '1', ANTHROPIC_API_KEY: KEY }, 'enabled with an empty key': { ASK_ENABLED: 'true', ANTHROPIC_API_KEY: '' },
    'enabled "false" with a key': { ASK_ENABLED: 'false', ANTHROPIC_API_KEY: KEY } };
  for (const [name, vars] of Object.entries(offs)) {
    const { result, calls } = await withUpstream(null, async () => {
      const e1 = env(vars), e2 = env(vars);
      const ask = await worker.fetch(post({ question: 'ACC schools' }), e1);
      const unknown = await worker.fetch(request('/api/no-such-route', { method: 'POST', body: '{}' }), e2);
      return { ask, unknown, askBody: await ask.text(), unknownBody: await unknown.text(), e1 };
    });
    assert.equal(result.ask.status, 404, name);
    assert.equal(result.ask.status, result.unknown.status, name);
    assert.equal(result.askBody, result.unknownBody, name);
    assert.deepEqual(result.e1.assetCalls, ['/api/ask'], `${name}: did not fall through to the assets`);
    assert.equal(calls.length, 0, `${name}: called the API`);
  }
});

test('/api/status is byte-identical {"local":false} off, on, and on with the owner\'s valid token (#179)', async () => {
  const off = await worker.fetch(request('/api/status'), env({ ASK_ENABLED: 'true' }));
  assert.equal(await off.text(), '{"local":false}');
  const { result } = await withUpstream(null, async () => {
    const on = await worker.fetch(request('/api/status'), env(accessVars({ ANTHROPIC_API_KEY: KEY })));
    const owner = await worker.fetch(request('/api/status', { headers: { 'cf-access-jwt-assertion': OWNER } }), env(accessVars({ ANTHROPIC_API_KEY: KEY })));
    return { on: await on.text(), owner: await owner.text() };
  });
  assert.equal(result.on, '{"local":false}');
  assert.equal(result.owner, '{"local":false}', 'ask availability leaked onto the public status route');
});

test('wrangler.toml holds no ANTHROPIC_API_KEY var, and no tracked file holds anything shaped like an Anthropic key', () => {
  const toml = fs.readFileSync(process.env.ASK_WRANGLER || path.join(ROOT, 'wrangler.toml'), 'utf8');
  assert.doesNotMatch(toml, /ANTHROPIC_API_KEY\s*=/, 'the key must be a secret, not a var');
  const files = execFileSync('git', ['ls-files', '-z'], { cwd: ROOT, encoding: 'utf8', maxBuffer: 1 << 28 }).split('\0').filter(Boolean)
    .filter((f) => /\.(js|mjs|cjs|html|toml|json|md|py|ya?ml|txt|env)$/i.test(f) || !path.extname(f));
  const hits = [];
  for (const f of files) {
    const p = path.join(ROOT, f);
    if (!fs.existsSync(p) || fs.statSync(p).size > 8 << 20) continue;
    if (/sk-ant-[A-Za-z0-9_-]{20,}/.test(fs.readFileSync(p, 'utf8'))) hits.push(f);
  }
  assert.deepEqual(hits, [], 'a key-shaped string is committed');
});

test('when on: the upstream request uses the pinned model, a hard token limit, a json_schema format, and the key only as a header', async () => {
  const e = env(accessVars({ ANTHROPIC_API_KEY: KEY }));
  const { result, calls } = await withUpstream(message({ ...blank, conf: ['ACC'] }), async () => {
    const res = await worker.fetch(post({ question: '  ACC   schools ' }), e);
    return { res, text: await res.text() };
  });
  assert.equal(result.res.status, 200);
  assert.equal(calls.length, 1);
  const [call] = calls;
  assert.equal(call.url, 'https://api.anthropic.com/v1/messages');
  assert.equal(call.init.headers['x-api-key'], KEY);
  assert.equal(call.init.headers['anthropic-version'], '2023-06-01');
  assert.equal(call.body.model, 'claude-haiku-4-5-20251001');
  assert.equal(call.body.max_tokens, 1024);
  assert.equal(call.body.output_config.format.type, 'json_schema');
  assert.deepEqual(call.body.messages, [{ role: 'user', content: 'ACC schools' }]);
  assert.ok(!JSON.stringify(call.body).includes(KEY), 'the key is in the request body');
  assert.ok(!result.text.includes(KEY), 'the key is in the response');
  assert.equal(result.res.headers.get('cache-control'), 'no-store');
  assert.deepEqual(JSON.parse(result.text), { division: [], conf: ['ACC'], region: [], classYear: [], cond: [], sort: null, reading: 'a reading' });
  // the schema's enums carry the live vocabulary, including every conference in the index
  const schema = call.body.output_config.format.schema;
  assert.deepEqual(schema.properties.conf.items.enum, [...new Set(INDEX.programs.map((p) => p.conference))].sort());
  assert.deepEqual(schema.properties.cond.items.properties.field.enum, Object.keys(A.FIELDS));
});

test('when on: method, empty and over-long questions are refused before any upstream call; upstream errors do not leak', async () => {
  const on = accessVars({ ANTHROPIC_API_KEY: KEY });
  await withUpstream(null, async () => {
    const get = await worker.fetch(request('/api/ask', { headers: { 'cf-access-jwt-assertion': OWNER } }), env(on));
    assert.equal(get.status, 405);
    assert.equal(get.headers.get('allow'), 'POST');
    for (const body of [{}, { question: '   ' }, 'not json', { question: 42 }]) {
      assert.equal((await worker.fetch(post(body), env(on))).status, 400, JSON.stringify(body));
    }
    const long = await worker.fetch(post({ question: 'x'.repeat(A.MAX_QUESTION + 1) }), env(on));
    assert.equal(long.status, 400);
  });
  const { result } = await withUpstream(() => new Response(`{"error":{"message":"invalid x-api-key ${KEY}"}}`, { status: 401 }), async () => {
    const res = await worker.fetch(post({ question: 'ACC schools' }), env(on));
    return { res, text: await res.text() };
  });
  assert.equal(result.res.status, 502);
  assert.ok(!result.text.includes(KEY) && !result.text.includes('x-api-key'), 'the upstream error was passed through');
});

// Every way an answer can be something the page cannot show. Each must become {unsupported}.
const INVALID = {
  'an unknown condition field': { cond: [{ field: 'coachSince', op: '<', value: 2010 }] },
  'a field name from Object.prototype': { cond: [{ field: 'constructor', op: '<', value: 1 }] },
  'a comparison the field does not allow': { cond: [{ field: 'admissionRate', op: '=', value: 0.3 }] },
  'admission in display units (30, not 0.3)': { cond: [{ field: 'admissionRate', op: '<', value: 30 }] },
  'a negative tuition': { cond: [{ field: 'tuition', op: '<', value: -1 }] },
  'a rank of 0': { cond: [{ field: 'rpiRank', op: '<=', value: 0 }] },
  'a string value': { cond: [{ field: 'sat25', op: '>', value: '1300' }] },
  'a conference the site does not carry': { conf: ['Gulf South'] },
  'a region that is not a pill': { region: ['Pacific Northwest'] },
  'a recruiting class the site does not track': { classYear: ['2035'] },
  'a division the site does not publish': { division: ['D3'] },
  'a sort the page does not have': { sort: 'record' },
  'no filter at all': {},
};
test('validation: every answer the page could not show becomes {unsupported}', async () => {
  const v = A.vocabFromIndex(INDEX);
  for (const [name, patch] of Object.entries(INVALID)) {
    const out = A.validateAsk({ ...blank, ...patch }, v);
    assert.equal(typeof out.unsupported, 'string', `${name}: ${JSON.stringify(out)}`);
    assert.deepEqual(Object.keys(out), ['unsupported'], name);
  }
  const ok = A.validateAsk({ ...blank, conf: ['SEC', 'SEC'], cond: [{ field: 'admissionRate', op: '<', value: 0.3 }], sort: 'tuition' }, v);
  assert.deepEqual(ok, { division: [], conf: ['SEC'], region: [], classYear: [], cond: [{ field: 'admissionRate', op: '<', value: 0.3 }], sort: 'tuition', reading: 'a reading' });
  assert.deepEqual(A.validateAsk({ ...blank, unsupported: 'a coach is not a filter', conf: ['SEC'] }, v), { unsupported: 'a coach is not a filter' });
});

test('through the route: an invalid field, unreadable JSON, a refusal and a truncated answer are all {unsupported}', async () => {
  const on = accessVars({ ANTHROPIC_API_KEY: KEY });
  const cases = {
    'invalid field': message({ ...blank, cond: [{ field: 'coachSince', op: '<', value: 2010 }] }),
    'unreadable JSON': message('{"conf": ["ACC"'),
    refusal: message({ ...blank, conf: ['ACC'] }, 'refusal'),
    'max_tokens': message({ ...blank, conf: ['ACC'] }, 'max_tokens'),
  };
  for (const [name, reply] of Object.entries(cases)) {
    const { result } = await withUpstream(reply, async () => {
      const res = await worker.fetch(post({ question: 'anything' }), env(on));
      return { res, body: await res.json() };
    });
    assert.equal(result.res.status, 200, name);
    assert.equal(typeof result.body.unsupported, 'string', `${name}: ${JSON.stringify(result.body)}`);
  }
});

test('the Worker vocabulary is exactly the page\'s: condition fields and ops, sort keys, regions', () => {
  const lines = fs.readFileSync(path.join(ROOT, 'public', 'index.html'), 'utf8').split(/\r?\n/);
  const a = lines.findIndex((l) => l.trim() === '<script>'), b = lines.findIndex((l) => l.trim() === '</script>');
  // Only the declarations are evaluated: the page's registry, sorts and regions, with the helpers they name.
  const src = lines.slice(a + 1, b).join('\n');
  const grab = (re) => { const m = re.exec(src); assert.ok(m, `not found in index.html: ${re}`); return m[0]; };
  const code = [
    'const RPI_SEASON = 2025; const fmtNum = String; const fmtUsd = String; const tuitionOf = () => 0; const rpiOf = () => 0;',
    grab(/const COND_OPS = [^\n]*/), grab(/const ORDER_OPS = [^\n]*/), grab(/const d1Count = [^\n]*/),
    grab(/const COND_FIELDS = \[[\s\S]*?\n\];/), grab(/const SORTS = [^\n]*/), grab(/const REGIONS = [^\n]*/),
    'globalThis.out = { fields: Object.fromEntries(COND_FIELDS.map(d => [d.key, [...d.ops]])), sorts: SORTS.map(s => s[0]), regions: [...REGIONS] };',
  ].join('\n');
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  const page = JSON.parse(JSON.stringify(sandbox.out));
  assert.deepEqual(Object.fromEntries(Object.entries(A.FIELDS).map(([k, f]) => [k, f.ops])), page.fields);
  assert.deepEqual(A.SORTS, page.sorts);
  assert.deepEqual(A.REGIONS, page.regions);
});
