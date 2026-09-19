import { readAsset } from './data-reader.mjs';

const SLUG_RE = /^[a-z0-9-]{1,64}$/;

const routes = [
  [/^\/api\/v1\/status$/, 'status', []],
  [/^\/api\/v1\/programs$/, 'programs', []],
  [/^\/api\/v1\/programs\/([^/]+)$/, 'program', ['slug']],
  [/^\/api\/v1\/camps$/, 'camps', []],
  [/^\/api\/v1\/trends$/, 'trends', []],
  [/^\/api\/v1\/commitments$/, 'commitments', []],
];

export function resolveResource(path) {
  for (const [pattern, kind, fields] of routes) {
    const match = pattern.exec(path);
    if (!match) continue;
    if (fields.includes('slug')) {
      const slug = match[1];
      if (!SLUG_RE.test(slug)) return { status: 400 };
    }
    return { kind, ...Object.fromEntries(fields.map((name, i) => [name, match[i + 1]])) };
  }
  return { status: 404 };
}

function failure(request, status) {
  const errors = {
    400: 'Invalid identifier',
    404: 'Not found',
    405: 'Method not allowed',
    503: 'Data is temporarily unavailable',
  };
  const headers = {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  };
  if (status === 405) headers.allow = 'GET, HEAD';
  return new Response(
    request.method === 'HEAD' ? null : JSON.stringify({ ok: false, error: errors[status] || 'Error' }),
    { status, headers },
  );
}

export async function dataApi(request, env) {
  if (!['GET', 'HEAD'].includes(request.method)) return failure(request, 405);
  const resource = resolveResource(new URL(request.url).pathname);
  if (resource.status) return failure(request, resource.status);
  try {
    const stored = await readAsset(request, env, resource);
    if (stored.status === 404) return failure(request, 404);
    // Missing assets may return HTML through SPA/404 fallback; never expose it as data.
    if (
      stored.status !== 304 &&
      (stored.status !== 200 || !/^application\/json(?:;|$)/i.test(stored.headers.get('content-type') || ''))
    ) {
      return failure(request, stored.status === 200 ? 404 : 503);
    }
    const headers = new Headers(stored.headers);
    headers.set('cache-control', 'public, max-age=300, must-revalidate');
    headers.delete('set-cookie');
    return new Response(request.method === 'HEAD' || stored.status === 304 ? null : stored.body, {
      status: stored.status,
      headers,
    });
  } catch (error) {
    console.error('data-api', error);
    return failure(request, 503);
  }
}
