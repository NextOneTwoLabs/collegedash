// Contract tests for /api/v1/* and raw data access controls (issue #240).
//
//     node --test tests/data_api.test.mjs
//
// Tests both worker.js edge routing and api/data-api.mjs contract behavior:
//   - All 6 v1 routes (/api/v1/programs, /programs/:slug, /camps, /trends, /commitments, /status)
//   - Cache-Control: public, max-age=300, must-revalidate on prod edge responses
//   - ETag generation and 304 conditional revalidation
//   - Strict slug validation (400 on invalid format)
//   - HTTP 405 Method Not Allowed on non-GET/HEAD methods with Allow: GET, HEAD
//   - Strict raw path blocking on /data/* and /archive/* (404 JSON on GET, empty body on HEAD)
//   - Path normalization and evasion resistance (percent-encoding, double slashes, uppercase)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import worker from '../worker.js';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const PUBLIC = path.join(ROOT, 'public');
const HOST = 'https://college.nextonetwo.com';

function createMockEnv() {
  const calls = [];
  return {
    calls,
    FEEDBACK: { put() { } },
    ASSETS: {
      async fetch(req) {
        const u = new URL(req.url);
        calls.push(u.pathname);
        let rel = decodeURIComponent(u.pathname).replace(/^\//, '');
        const file = path.join(PUBLIC, rel);
        if (!file.startsWith(PUBLIC) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
          return new Response(null, { status: 404 });
        }
        const content = fs.readFileSync(file);
        // Compute SHA-256 for ETag test
        const hash = await crypto.subtle.digest('SHA-256', content);
        const etag = '"' + Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, '0')).join('') + '"';
        const clientNoneMatch = req.headers.get('if-none-match');
        if (clientNoneMatch && clientNoneMatch === etag) {
          return new Response(null, { status: 304, headers: { etag } });
        }
        return new Response(content, {
          status: 200,
          headers: {
            'content-type': 'application/json; charset=utf-8',
            'etag': etag,
          },
        });
      },
    },
  };
}

test('all 6 v1 routes return 200, valid JSON, and edge cache headers', async () => {
  const env = createMockEnv();
  const routes = [
    { path: '/api/v1/programs', file: 'data/programs/index.json' },
    { path: '/api/v1/programs/ucla', file: 'data/programs/ucla.json' },
    { path: '/api/v1/camps', file: 'data/camps/index.json' },
    { path: '/api/v1/trends', file: 'data/trends/index.json' },
    { path: '/api/v1/commitments', file: 'data/commitments/index.json' },
    { path: '/api/v1/status', file: 'archive/refresh-state.json' },
  ];

  for (const r of routes) {
    const res = await worker.fetch(new Request(HOST + r.path), env);
    assert.equal(res.status, 200, `${r.path} status expected 200, got ${res.status}`);
    assert.ok(res.headers.get('content-type')?.includes('application/json'), `${r.path} content-type missing json`);
    assert.equal(res.headers.get('cache-control'), 'public, max-age=300, must-revalidate', `${r.path} cache-control mismatch`);
    assert.ok(res.headers.get('etag'), `${r.path} missing etag header`);

    const json = await res.json();
    assert.ok(json != null, `${r.path} returned empty json`);
    const expectedFile = path.join(PUBLIC, r.file);
    if (fs.existsSync(expectedFile)) {
      const diskJson = JSON.parse(fs.readFileSync(expectedFile, 'utf8'));
      assert.deepEqual(json, diskJson, `${r.path} payload does not match ${r.file}`);
    }
  }
});

test('conditional GET with matching ETag returns 304 with empty body', async () => {
  const env = createMockEnv();
  const res1 = await worker.fetch(new Request(HOST + '/api/v1/programs'), env);
  assert.equal(res1.status, 200);
  const etag = res1.headers.get('etag');
  assert.ok(etag, 'ETag was not set');

  const res2 = await worker.fetch(new Request(HOST + '/api/v1/programs', {
    headers: { 'if-none-match': etag },
  }), env);
  assert.equal(res2.status, 304, `Expected 304, got ${res2.status}`);
  assert.equal(await res2.text(), '', '304 response should have empty body');
  assert.equal(res2.headers.get('cache-control'), 'public, max-age=300, must-revalidate');
});

test('HEAD request on v1 routes returns 200 with headers and empty body', async () => {
  const env = createMockEnv();
  const res = await worker.fetch(new Request(HOST + '/api/v1/programs', { method: 'HEAD' }), env);
  assert.equal(res.status, 200);
  assert.ok(res.headers.get('etag'), 'HEAD missing etag');
  assert.equal(res.headers.get('cache-control'), 'public, max-age=300, must-revalidate');
  assert.equal(await res.text(), '', 'HEAD response must have an empty body');
});

test('invalid slug formats return 400 Bad Request', async () => {
  const env = createMockEnv();
  const badSlugs = [
    'UCLA',
    'ucla_bruins',
    'ucla bruins',
    'bad..slug',
    'a'.repeat(65),
    'invalid!slug',
    'slug.json',
  ];

  for (const slug of badSlugs) {
    const res = await worker.fetch(new Request(`${HOST}/api/v1/programs/${encodeURIComponent(slug)}`), env);
    assert.equal(res.status, 400, `slug '${slug}' should return 400`);
    const body = await res.json();
    assert.deepEqual(body, { ok: false, error: 'Invalid identifier' });
  }
});

test('non-existent resources return 404 Not Found', async () => {
  const env = createMockEnv();
  const res1 = await worker.fetch(new Request(HOST + '/api/v1/programs/non-existent-slug-xyz'), env);
  assert.equal(res1.status, 404);
  assert.deepEqual(await res1.json(), { ok: false, error: 'Not found' });

  const res2 = await worker.fetch(new Request(HOST + '/api/v1/unknown-resource'), env);
  assert.equal(res2.status, 404);
  assert.deepEqual(await res2.json(), { ok: false, error: 'Not found' });
});

test('non-GET/HEAD methods on v1 return 405 Method Not Allowed with Allow header', async () => {
  const env = createMockEnv();
  for (const method of ['POST', 'PUT', 'DELETE', 'PATCH']) {
    const res = await worker.fetch(new Request(HOST + '/api/v1/programs', { method }), env);
    assert.equal(res.status, 405, `${method} expected 405`);
    assert.equal(res.headers.get('allow'), 'GET, HEAD');
    assert.deepEqual(await res.json(), { ok: false, error: 'Method not allowed' });
  }

  // Method check takes precedence over slug syntax check (returns 405, not 400)
  const badSlugPost = await worker.fetch(new Request(HOST + '/api/v1/programs/bad..slug', { method: 'POST' }), env);
  assert.equal(badSlugPost.status, 405, 'POST on bad slug should return 405');
  assert.equal(badSlugPost.headers.get('allow'), 'GET, HEAD');
});

test('direct access to /data/* and /archive/* is refused with 404 JSON on GET and empty on HEAD', async () => {
  const env = createMockEnv();
  const blockedPaths = [
    '/data/programs/index.json',
    '/data/programs/ucla.json',
    '/data/camps/index.json',
    '/data/trends/index.json',
    '/data/commitments/index.json',
    '/data/registry.json',
    '/archive/2024.json',
    '/data',
    '/data/',
    '/archive',
    '/archive/',
  ];

  for (const p of blockedPaths) {
    // GET
    const getRes = await worker.fetch(new Request(HOST + p), env);
    assert.equal(getRes.status, 404, `GET ${p} expected 404`);
    assert.deepEqual(await getRes.json(), { ok: false, error: 'Not found' });
    assert.equal(getRes.headers.get('content-type'), 'application/json; charset=utf-8');

    // HEAD
    const headRes = await worker.fetch(new Request(HOST + p, { method: 'HEAD' }), env);
    assert.equal(headRes.status, 404, `HEAD ${p} expected 404`);
    assert.equal(await headRes.text(), '', `HEAD ${p} body must be empty`);
  }

  // Ensure asset server was never called for any of these
  assert.deepEqual(env.calls, [], 'Asset server should never be called for blocked raw paths');
});

test('encoded and traversal attempts to /data/* and /archive/* are refused', async () => {
  const env = createMockEnv();
  const evasionAttempts = [
    '//data/programs/index.json',
    '/data%2fprograms%2findex.json',
    '/data%2Fprograms%2Findex.json',
    '/DATA/programs/index.json',
    '/Data/Programs/Index.json',
    '/archive/../data/programs/index.json',
    '/data/../archive/2024.json',
    '/ARCHIVE/2024.json',
  ];

  for (const p of evasionAttempts) {
    const res = await worker.fetch(new Request(HOST + p), env);
    assert.equal(res.status, 404, `Evasion attempt ${p} expected 404, got ${res.status}`);
    assert.deepEqual(await res.json(), { ok: false, error: 'Not found' });
  }
  assert.deepEqual(env.calls, [], 'Asset server should never be called for evasion attempts');
});
