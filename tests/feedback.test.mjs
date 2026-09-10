// Validation tests for POST /api/feedback. They drive the deployed Worker's own `fetch` with a
// stub `env`, so there is nothing to keep in sync with a second copy of the rules.
//
//     node --test tests/feedback.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import worker from '../worker.js';

/** A stand-in for the KV binding that records what was written. */
function stubEnv() {
  const puts = [];
  return { puts, FEEDBACK: { put: (key, value, opts) => puts.push({ key, value, opts }) } };
}

/** POST a body to /api/feedback. A string is sent as-is, so malformed JSON can be tested. */
function post(body, env, method = 'POST') {
  const req = new Request('https://college.nextonetwo.com/api/feedback', {
    method,
    headers: { 'content-type': 'application/json' },
    body: method === 'POST' ? (typeof body === 'string' ? body : JSON.stringify(body)) : undefined,
  });
  return worker.fetch(req, env);
}

async function send(body, env = stubEnv(), method) {
  const res = await post(body, env, method);
  return { res, env, json: await res.json().catch(() => ({})) };
}

test('a message is required', async () => {
  for (const message of ['', '   \n\t  ', undefined]) {
    const { res, json, env } = await send({ message });
    assert.equal(res.status, 400, JSON.stringify(message));
    assert.equal(json.error, 'Please add a message.');
    assert.equal(env.puts.length, 0);
  }
});

test('the cap is 2,000 UTF-16 code units, matching the textarea maxlength', async () => {
  const ok = await send({ message: 'x'.repeat(2000) });
  assert.equal(ok.res.status, 200);
  assert.equal(JSON.parse(ok.env.puts[0].value).message.length, 2000);

  const over = await send({ message: 'x'.repeat(2001) });
  assert.equal(over.res.status, 400);
  assert.equal(over.json.error, 'Please keep it under 2,000 characters.');
  assert.equal(over.env.puts.length, 0);
});

test('the email is optional, validated only when given, trimmed and lowercased', async () => {
  const bad = await send({ message: 'hi', email: 'not-an-email' });
  assert.equal(bad.res.status, 400);
  assert.equal(bad.json.error, 'Please enter a valid email address.');
  assert.equal(bad.env.puts.length, 0);

  const none = await send({ message: 'hi' });
  assert.equal(none.res.status, 200);
  assert.ok(!('email' in JSON.parse(none.env.puts[0].value)));
  assert.equal(none.env.puts[0].opts.metadata.email, null);

  const given = await send({ message: 'hi', email: '  Someone@Example.COM ' });
  assert.equal(given.res.status, 200);
  assert.equal(JSON.parse(given.env.puts[0].value).email, 'someone@example.com');
  assert.equal(given.env.puts[0].opts.metadata.email, 'someone@example.com');
});

test('a filled honeypot returns success and stores nothing', async () => {
  const { res, json, env } = await send({ message: 'hi', website: 'http://spam.example' });
  assert.equal(res.status, 200);
  assert.equal(json.ok, true);
  assert.equal(env.puts.length, 0);
});

test('GET is 405 with allow: POST', async () => {
  const { res, env } = await send(null, stubEnv(), 'GET');
  assert.equal(res.status, 405);
  assert.equal(res.headers.get('allow'), 'POST');
  assert.equal(env.puts.length, 0);
});

test('non-object and malformed JSON bodies are a clean 400, never a throw', async () => {
  for (const body of ['null', '"str"', '42', '[1,2]', '{oops', '']) {
    const { res, json, env } = await send(body);
    assert.equal(res.status, 400, body);
    assert.equal(json.error, 'Please add a message.');
    assert.equal(env.puts.length, 0);
  }
});

test('a missing binding is a clean 503, not a 500', async () => {
  const { res, json } = await send({ message: 'hi' }, {});
  assert.equal(res.status, 503);
  assert.equal(json.error, 'Feedback is unavailable right now.');
});

// wrangler.toml does bind the namespace (wrangler.toml:28-30), so this is not the shipped state;
// it is the fail-closed path for the day the binding is missing or misconfigured. Only
// /api/feedback is out, and "/" is run_worker_first, so the home page has to keep working.
test('with no FEEDBACK binding the rest of the Worker is unaffected', async () => {
  const env = { ASSETS: { fetch: () => new Response('the home page', { status: 200 }) } };

  const feedback = await post({ message: 'hi' }, env);
  assert.equal(feedback.status, 503);

  const status = await worker.fetch(new Request('https://college.nextonetwo.com/api/status'), env);
  assert.equal(status.status, 200);
  assert.deepEqual(await status.json(), { local: false });

  const home = await worker.fetch(new Request('https://college.nextonetwo.com/'), env);
  assert.equal(home.status, 200);
  assert.equal(await home.text(), 'the home page');
});

test('route and program are capped and stored when they fit', async () => {
  const kept = await send({ message: 'hi', route: '#/p/stanford/roster', program: 'stanford' });
  const record = JSON.parse(kept.env.puts[0].value);
  assert.equal(record.route, '#/p/stanford/roster');
  assert.equal(record.program, 'stanford');
  assert.deepEqual(Object.keys(kept.env.puts[0].opts.metadata), ['email'], 'metadata is email only');

  const capped = await send({ message: 'hi', route: '#/' + 'a'.repeat(500), program: 'Not A Slug' });
  const trimmed = JSON.parse(capped.env.puts[0].value);
  assert.equal(trimmed.route.length, 200);
  assert.ok(!('program' in trimmed), 'a slug that fails the pattern is dropped, not stored');
});

test('keys are <ISO>-<8 hex> and sort chronologically', async () => {
  const env = stubEnv();
  for (let i = 0; i < 5; i++) await post({ message: `m${i}` }, env);
  const keys = env.puts.map((p) => p.key);
  for (const key of keys) assert.match(key, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z-[0-9a-f]{8}$/);
  assert.deepEqual(keys.map((k) => k.slice(0, 24)), [...keys.map((k) => k.slice(0, 24))].sort());
});

test('a route that is not a #/ hash route is dropped, a valid one is stored', async () => {
  for (const route of ['javascript:alert(1)', 'https://example.com/#/p/x', 'p/stanford', '#p/stanford', '#/ has a space', '#']) {
    const { res, env } = await send({ message: 'hi', route });
    assert.equal(res.status, 200, route);
    assert.ok(!('route' in JSON.parse(env.puts[0].value)), `dropped: ${route}`);
  }
  for (const route of ['#/', '#/p/stanford/roster', '#/faq']) {
    const { env } = await send({ message: 'hi', route });
    assert.equal(JSON.parse(env.puts[0].value).route, route);
  }
});

// KV rejects a write whose metadata exceeds 1024 bytes, and a rejected write loses the submission.
// Storing the route alongside the email was measured at 1371 bytes for the pair below, so the
// metadata is now the email alone; the route stays in the record value, where triage reads it.
test('metadata stays under the 1024-byte KV limit for the longest legal email and route', async () => {
  const email = '漢'.repeat(125) + '@' + '漢'.repeat(124) + '.' + '漢';
  const route = '#/' + '漢'.repeat(198);
  assert.equal(email.length, 252, 'passes the 254 cap');
  assert.equal(route.length, 200, 'at MAX_ROUTE');

  const { res, env } = await send({ message: 'hi', email, route });
  assert.equal(res.status, 200);
  const { metadata } = env.puts[0].opts;
  const bytes = (value) => new TextEncoder().encode(JSON.stringify(value)).length;
  assert.ok(bytes(metadata) < 1024, `metadata is ${bytes(metadata)} bytes`);
  assert.deepEqual(Object.keys(metadata), ['email']);
  assert.ok(bytes({ ...metadata, route }) > 1024, 'the dropped field is what used to cross the limit');
  assert.equal(JSON.parse(env.puts[0].value).route, route, 'the route is still in the record');
});

test('a KV write that fails is a clean 503, not a 500 and not an uncaught throw', async () => {
  const throws = { FEEDBACK: { put: () => { throw new Error('metadata too large'); } } };
  const rejects = { FEEDBACK: { put: async () => { throw new Error('KV unavailable'); } } };
  for (const env of [throws, rejects]) {
    const res = await post({ message: 'hi' }, env);
    assert.equal(res.status, 503);
    assert.equal((await res.json()).error, 'Feedback is unavailable right now.');
  }
});

test('/api/status answers GET and HEAD, and 405s anything else', async () => {
  const env = stubEnv();
  const status = (method) =>
    worker.fetch(new Request('https://college.nextonetwo.com/api/status', { method }), env);

  for (const method of ['GET', 'HEAD']) {
    const res = await status(method);
    assert.equal(res.status, 200, method);
  }
  assert.deepEqual(await (await status('GET')).json(), { local: false });

  for (const method of ['DELETE', 'POST', 'PUT']) {
    const res = await status(method);
    assert.equal(res.status, 405, method);
    assert.equal(res.headers.get('allow'), 'GET, HEAD');
  }
});

// /api/* is matched ahead of the workers.dev redirect. That order is the point of the routing:
// a 301 is downgraded to GET by most clients, so a redirected POST would become a page view.
test('workers.dev redirects the page but not /api/*', async () => {
  const env = { ...stubEnv(), ASSETS: { fetch: () => new Response('assets', { status: 200 }) } };
  const workersDev = 'https://collegedash.nextonetwolabs.workers.dev';

  const deep = await worker.fetch(new Request(`${workersDev}/#/p/stanford/roster`), env);
  assert.equal(deep.status, 301);
  assert.equal(
    deep.headers.get('location'),
    'https://college.nextonetwo.com/#/p/stanford/roster',
    'the canonical host, with the deep-link fragment intact',
  );

  const submission = await worker.fetch(
    new Request(`${workersDev}/api/feedback`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ message: 'from the workers.dev host' }),
    }),
    env,
  );
  assert.equal(submission.status, 200, 'handled, not redirected');
  assert.equal(env.puts.length, 1);
  assert.equal(JSON.parse(env.puts[0].value).message, 'from the workers.dev host');

  const status = await worker.fetch(new Request(`${workersDev}/api/status`), env);
  assert.equal(status.status, 200);
  assert.deepEqual(await status.json(), { local: false });
});
