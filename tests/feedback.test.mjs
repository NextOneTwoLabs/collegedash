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

test('route and program are capped and stored when they fit', async () => {
  const kept = await send({ message: 'hi', route: '#/p/stanford/roster', program: 'stanford' });
  const record = JSON.parse(kept.env.puts[0].value);
  assert.equal(record.route, '#/p/stanford/roster');
  assert.equal(record.program, 'stanford');
  assert.equal(kept.env.puts[0].opts.metadata.route, '#/p/stanford/roster');

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
