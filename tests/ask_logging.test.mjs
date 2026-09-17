// Diagnostic logging for /api/ask failures (issue #165): what the Worker writes to the log when ask fails, and
// what it never writes.
//
//     node --test tests/ask_logging.test.mjs
//
// Everything runs in process against worker.js's own fetch handler, with the owner's valid stand-in Access token
// (tests/ask_access_helpers.mjs), an in-memory budget namespace, and a stubbed Anthropic API that answers each
// documented error type. console is captured. No key, no network.
//
// What this proves:
//   - an upstream error response logs exactly one line: the HTTP status and the error type, and for
//     invalid_request_error a label from a fixed list (credit_balance, max_tokens, output_config, model, other);
//   - an unknown error type logs "other", an unreadable body logs "unknown";
//   - every upstream error line also carries fixed shape labels: ct (json/html/text/none/other), parse (ok/fail),
//     keys (type, error, request_id by name, anything else as x) and rid (whether a request-id header exists);
//   - the documented error body yields its type, and an HTML 400 yields ct=html parse=fail;
//   - a fetch that throws logs the error's name only (TimeoutError, TypeError);
//   - the two 503 paths log a fixed label (vocab, budget_kv);
//   - in every case the upstream error message, the API key, the question, the request-id value and unlisted body
//     key names never appear in any log output.
//
// ASK_WORKER (optional) points at another copy of worker.js, so a deliberately broken copy can be shown failing.
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..');
const WORKER = process.env.ASK_WORKER || path.join(ROOT, 'worker.js');
const worker = (await import(pathToFileURL(WORKER).href)).default;
const A = worker.ask;
const H = await import(pathToFileURL(path.join(HERE, 'ask_access_helpers.mjs')).href);
const INDEX = JSON.parse(fs.readFileSync(path.join(ROOT, 'public', 'data', 'programs', 'index.json'), 'utf8'));
const OWNER = await H.token();
const KEY = 'sk-test-LOGCANARY-key-0000-not-a-real-key';
const QUESTION = 'ACC schools QUESTIONCANARY under 30%';
// Stands in for anything an error message could carry: an organisation name, an id, part of a key.
const SECRET = 'MSGCANARY-org-Acme-Owner-4f2a';

function env(extra = {}) {
  return {
    ...H.accessVars({ ANTHROPIC_API_KEY: KEY }),
    ASK_BUDGET: H.memoryKV(),
    ASSETS: {
      fetch: async (req) => (new URL(req.url).pathname === '/data/programs/index.json'
        ? Response.json(INDEX) : new Response('Not found', { status: 404 })),
    },
    ...extra,
  };
}
const post = () => new Request('https://college.nextonetwo.com/api/ask', {
  method: 'POST', headers: { 'content-type': 'application/json', 'cf-access-jwt-assertion': OWNER },
  body: JSON.stringify({ question: QUESTION }),
});
const apiError = (status, type, message) => () => Response.json({ type: 'error', error: { type, message } }, { status });

// Runs one ask request with every console method captured. Returns the response and every logged line.
async function run(upstream, e = env()) {
  A.resetCache();
  const lines = [];
  const methods = ['log', 'info', 'warn', 'error', 'debug'].map((m) => mock.method(console, m, (...args) => {
    lines.push({ level: m, text: args.map((a) => (typeof a === 'string' ? a : (() => {
      try { return JSON.stringify(a); } catch { return String(a); }
    })())).join(' ') });
  }));
  try {
    const { result } = await H.withFetch(upstream, async () => {
      const res = await worker.fetch(post(), e);
      return { res, body: await res.text() };
    });
    return { ...result, lines };
  } finally {
    for (const m of methods) m.mock.restore();
  }
}

function assertClean(lines, name) {
  const all = lines.map((l) => l.text).join('\n');
  assert.ok(!all.includes('MSGCANARY'), `${name}: the upstream error message reached the log:\n${all}`);
  assert.ok(!all.includes(KEY) && !all.includes('LOGCANARY'), `${name}: the API key reached the log:\n${all}`);
  assert.ok(!all.includes('QUESTIONCANARY'), `${name}: the question reached the log:\n${all}`);
  assert.ok(!all.includes('RIDCANARY'), `${name}: the request-id value reached the log:\n${all}`);
  assert.ok(!all.includes('KEYNAMECANARY'), `${name}: an unlisted body key name reached the log:\n${all}`);
}

const UPSTREAM_CASES = [
  ['401 authentication_error', apiError(401, 'authentication_error', `invalid x-api-key ${SECRET}`),
    'ask: upstream_error status=401 type=authentication_error ct=json parse=ok keys=type,error rid=no'],
  ['403 permission_error', apiError(403, 'permission_error', `Your API key ${SECRET} does not have permission`),
    'ask: upstream_error status=403 type=permission_error ct=json parse=ok keys=type,error rid=no'],
  ['404 not_found_error', apiError(404, 'not_found_error', `model: claude-haiku-4-5-20251001 ${SECRET}`),
    'ask: upstream_error status=404 type=not_found_error ct=json parse=ok keys=type,error rid=no'],
  ['429 rate_limit_error', apiError(429, 'rate_limit_error', `Number of request tokens has exceeded your rate limit ${SECRET}`),
    'ask: upstream_error status=429 type=rate_limit_error ct=json parse=ok keys=type,error rid=no'],
  ['529 overloaded_error', apiError(529, 'overloaded_error', `Overloaded ${SECRET}`),
    'ask: upstream_error status=529 type=overloaded_error ct=json parse=ok keys=type,error rid=no'],
  ['400 invalid_request_error: credit balance', apiError(400, 'invalid_request_error',
    `Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing. ${SECRET}`),
  'ask: upstream_error status=400 type=invalid_request_error reason=credit_balance ct=json parse=ok keys=type,error rid=no'],
  ['400 invalid_request_error: max_tokens', apiError(400, 'invalid_request_error',
    `max_tokens: 99999 > 64000, which is the maximum allowed number of output tokens for claude-haiku-4-5-20251001 ${SECRET}`),
  'ask: upstream_error status=400 type=invalid_request_error reason=max_tokens ct=json parse=ok keys=type,error rid=no'],
  ['400 invalid_request_error: output_config', apiError(400, 'invalid_request_error',
    `output_config.format.schema: For 'array' type, property 'items' is invalid ${SECRET}`),
  'ask: upstream_error status=400 type=invalid_request_error reason=output_config ct=json parse=ok keys=type,error rid=no'],
  ['400 invalid_request_error: model', apiError(400, 'invalid_request_error', `model: Input should be a valid model ${SECRET}`),
    'ask: upstream_error status=400 type=invalid_request_error reason=model ct=json parse=ok keys=type,error rid=no'],
  ['400 invalid_request_error: anything else', apiError(400, 'invalid_request_error', `messages.0.content: Field required ${SECRET}`),
    'ask: upstream_error status=400 type=invalid_request_error reason=other ct=json parse=ok keys=type,error rid=no'],
  ['an error type not on the list', apiError(418, `teapot_error_${SECRET}`, `short and stout ${SECRET}`),
    'ask: upstream_error status=418 type=other ct=json parse=ok keys=type,error rid=no'],
  ['500 with an unreadable body', () => new Response(`<html>upstream exploded ${SECRET}</html>`, { status: 500 }),
    'ask: upstream_error status=500 type=unknown ct=text parse=fail keys=- rid=no'],
  // The documented error body, in shape, with the request-id header the API sends.
  ['400 the documented error body with request_id and a request-id header', () => new Response(
    `{"type":"error","error":{"type":"invalid_request_error","message":"messages: text content blocks must be non-empty ${SECRET}"},"request_id":"req_RIDCANARY_011CSHoEeqs5C35K2UUqR7Fy"}`,
    { status: 400, headers: { 'content-type': 'application/json', 'request-id': 'req_RIDCANARY_011CSHoEeqs5C35K2UUqR7Fy' } }),
  'ask: upstream_error status=400 type=invalid_request_error reason=other ct=json parse=ok keys=type,error,request_id rid=yes'],
  ['400 an HTML error page', () => new Response(`<html><head><title>400 Bad Request</title></head><body><center>${SECRET}</center></body></html>`,
    { status: 400, headers: { 'content-type': 'text/html; charset=UTF-8' } }),
  'ask: upstream_error status=400 type=unknown ct=html parse=fail keys=- rid=no'],
  ['400 JSON of another shape, with key names that are not on the list', () => new Response(
    JSON.stringify({ error: `plain string ${SECRET}`, KEYNAMECANARY_detail: 1, message: SECRET }),
    { status: 400, headers: { 'content-type': 'application/problem+json' } }),
  'ask: upstream_error status=400 type=unknown ct=json parse=ok keys=error,x rid=no'],
  ['400 with no body and no content-type', () => new Response(new Uint8Array(0), { status: 400 }),
    'ask: upstream_error status=400 type=unknown ct=none parse=fail keys=- rid=no'],
  ['400 with a binary content-type', () => new Response(new Uint8Array([1, 2, 3]), { status: 400, headers: { 'content-type': 'application/octet-stream' } }),
    'ask: upstream_error status=400 type=unknown ct=other parse=fail keys=- rid=no'],
];

for (const [name, upstream, expected] of UPSTREAM_CASES) {
  test(`upstream ${name}: 502, one log line with status and type only`, async () => {
    const { res, body, lines } = await run(upstream);
    assert.equal(res.status, 502, name);
    assert.ok(!body.includes('MSGCANARY'), `${name}: the upstream message reached the response`);
    assertClean(lines, name);
    assert.deepEqual(lines, [{ level: 'error', text: expected }], name);
  });
}

test('a fetch that throws logs the error name only (TimeoutError, TypeError)', async () => {
  const cases = [
    ['TimeoutError', () => { throw new DOMException(`The operation timed out ${SECRET}`, 'TimeoutError'); }],
    ['TypeError', () => { throw new TypeError(`fetch failed ${SECRET}`); }],
  ];
  for (const [errName, upstream] of cases) {
    const { res, lines } = await run(upstream);
    assert.equal(res.status, 502, errName);
    assertClean(lines, errName);
    assert.deepEqual(lines, [{ level: 'error', text: `ask: upstream_fetch_failed name=${errName}` }], errName);
  }
});

test('the 503 paths log a fixed label: the vocabulary could not load, the budget namespace refused', async () => {
  const noUpstream = () => { throw new Error('the API must not be called'); };
  const vocab = await run(noUpstream, env({ ASSETS: { fetch: async () => new Response('broken', { status: 500 }) } }));
  assert.equal(vocab.res.status, 503);
  assertClean(vocab.lines, 'vocab');
  assert.deepEqual(vocab.lines, [{ level: 'error', text: 'ask: unavailable reason=vocab' }]);

  const noBinding = await run(noUpstream, env({ ASK_BUDGET: undefined }));
  assert.equal(noBinding.res.status, 503);
  assertClean(noBinding.lines, 'no binding');
  assert.deepEqual(noBinding.lines, [{ level: 'error', text: 'ask: unavailable reason=budget_kv' }]);

  const kv = H.memoryKV();
  kv.fail.getThrows = true;
  const kvThrows = await run(noUpstream, env({ ASK_BUDGET: kv }));
  assert.equal(kvThrows.res.status, 503);
  assert.deepEqual(kvThrows.lines, [{ level: 'error', text: 'ask: unavailable reason=budget_kv' }]);
});

test('a successful answer logs nothing', async () => {
  const ok = () => Response.json({ type: 'message', stop_reason: 'end_turn', usage: { input_tokens: 10, output_tokens: 10 },
    content: [{ type: 'text', text: JSON.stringify({ unsupported: null, reading: 'r', division: [], conf: ['ACC'], region: [],
      classYear: [], cond: [], sort: null }) }] });
  const { res, lines } = await run(ok);
  assert.equal(res.status, 200);
  assert.deepEqual(lines, []);
});
