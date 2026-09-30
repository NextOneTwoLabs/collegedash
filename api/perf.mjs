// Speed measurements (issue #394, round-2 plan approved on the issue): server timing for "/" and /api/v1/*, and the
// page's timing reports at POST /api/perf. Both write to the Analytics Engine dataset collegedash_perf (binding
// PERF_STATS), never to the #345 gate's dataset, and both obey #345's rule of at most one data point per request:
// every writer checks and bumps the request's tally, which the gate's count() and sessionFault() bump too.
//
// What a point holds is fixed below, field by field. Never an IP address, session id, user agent, cookie, URL,
// query, program slug or any header value. A profile's size is never written (it would identify the program: its
// length is close to unique per program), whatever the page sends.
import { verify, readCookie, ipKey, usableSecret, PRODUCTION_HOST } from './session.mjs';
import { resolveResource } from './data-api.mjs';

export const PERF_HEADER = 'x-collegedash-perf';
export const MAX_BODY = 1024;
const MAX_MS = 120000;
const MAX_BYTES = 50 * 1000 * 1000;

// The page's sample rate, from the PERF_SAMPLE variable: a number in (0, 1], anything else 0 (off).
export function perfRate(env) {
  const r = Number(env?.PERF_SAMPLE);
  return Number.isFinite(r) && r > 0 && r <= 1 ? r : 0;
}

const site = request => { try { return new URL(request.url).hostname === PRODUCTION_HOST ? 'production' : 'preview'; } catch { return 'preview'; } };
const ms = v => Math.max(0, Math.round(v));

// One point to PERF_STATS, only when nothing has been written for this request yet. A failed write still counts.
export function writePerf(env, tally, point) {
  if (!tally || tally.points !== 0) return false;
  tally.points++;
  try { env.PERF_STATS?.writeDataPoint(point); } catch {}
  return true;
}

const statusClass = s => (s === 304 ? '304' : s >= 500 ? '5xx' : s >= 400 ? '4xx' : s >= 300 ? '3xx' : '2xx');

// The server point for "/" (kind "page") or an /api/v1 request. Body bytes come from content-length when the
// response has one; for a profile (kind "program") they are always 0.
export function serverPoint(kind, response, request, parts) {
  const length = Number(response.headers.get('content-length'));
  const bytes = kind === 'program' || !Number.isFinite(length) ? 0 : Math.min(MAX_BYTES, Math.max(0, Math.round(length)));
  return {
    indexes: [`server:${kind}`],
    blobs: ['server', kind, statusClass(response.status), '', '', site(request)],
    doubles: [1, ms(parts.total), ms(parts.gate || 0), ms(parts.data || 0), bytes],
  };
}

export function v1Kind(request) {
  const r = resolveResource(new URL(request.url).pathname);
  return r.kind || (r.status === 400 ? 'invalid' : 'unknown');
}

// Adds Server-Timing (always: it costs nothing) and, on /api/v1 responses, the page's sample rate; then writes the
// server point when PERF_SERVER is "on" and nothing else was written for this request. Never changes the status or
// body, and never throws: a response whose headers cannot be set is returned as it was.
export function finishServer(request, env, tally, response, parts, kind, { rate = false } = {}) {
  try {
    const value = Object.entries(parts).map(([k, v]) => `${k};dur=${ms(v)}`).join(', ');
    let out = response;
    const set = r => { r.headers.set('server-timing', value); if (rate) r.headers.set(PERF_HEADER, String(perfRate(env))); };
    try { set(out); } catch { out = new Response(response.body, response); set(out); }
    if (env?.PERF_SERVER === 'on') writePerf(env, tally, serverPoint(kind, out, request, parts));
    return out;
  } catch {
    return response;
  }
}

// ---- POST /api/perf: the page's timing report ----

// The view each report is about, and the data file that view loads.
export const VIEWS = { list: 'programs', profile: 'program', trends: 'trends', camps: 'camps' };
const DEVICES = ['phone', 'tablet', 'desktop'];
const NAVS = ['landing', 'in-app'];
const CACHES = ['network', 'revalidated', 'memory'];
const TIMES = ['server', 'wait', 'download', 'parse', 'render', 'first'];
const SIZES = ['tx', 'size'];
export const FIELDS = ['v', 'view', 'res', 'device', 'nav', 'cache', ...TIMES, ...SIZES, 'rate'];

const clamp = (v, max) => Math.min(max, Math.max(0, Math.round(v)));

// A report body -> the point to write, or null when anything about it is off. Exactly FIELDS, nothing else.
export function pagePoint(text, rate, request) {
  let b;
  try { b = JSON.parse(text); } catch { return null; }
  if (!b || typeof b !== 'object' || Array.isArray(b)) return null;
  const keys = Object.keys(b);
  if (keys.length !== FIELDS.length || !FIELDS.every(k => Object.hasOwn(b, k))) return null;
  if (b.v !== 1 || !Object.hasOwn(VIEWS, b.view) || VIEWS[b.view] !== b.res) return null;
  if (!DEVICES.includes(b.device) || !NAVS.includes(b.nav) || !CACHES.includes(b.cache)) return null;
  if (typeof b.rate !== 'number' || b.rate !== rate) return null;
  for (const k of [...TIMES, ...SIZES]) if (typeof b[k] !== 'number' || !Number.isFinite(b[k])) return null;
  const profile = b.res === 'program';
  return {
    indexes: [`page:${b.view}:${b.device}`],
    blobs: ['page', b.view, b.res, b.device, b.nav, site(request), b.cache],
    doubles: [1, clamp(b.server, MAX_MS), clamp(b.wait, MAX_MS), clamp(b.download, MAX_MS),
      profile ? 0 : clamp(b.tx, MAX_BYTES), profile ? 0 : clamp(b.size, MAX_BYTES),
      clamp(b.parse, MAX_MS), clamp(b.render, MAX_MS), b.nav === 'landing' ? clamp(b.first, MAX_MS) : 0, Math.round(1 / rate)],
  };
}

// The body, read up to MAX_BODY bytes: null when it is longer (the rest is never read).
async function readCapped(request) {
  const declared = Number(request.headers.get('content-length'));
  if (Number.isFinite(declared) && declared > MAX_BODY) return null;
  if (!request.body) return '';
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BODY) { try { await reader.cancel(); } catch {} return null; }
    chunks.push(value);
  }
  const all = new Uint8Array(size);
  let at = 0;
  for (const c of chunks) { all.set(c, at); at += c.byteLength; }
  return new TextDecoder().decode(all);
}

const allowed = async (binding, key) => !binding || (await binding.limit({ key })).success;

// Always 204 with no body, so the page learns nothing from the answer. Writes one point, or none. The order is the
// plan's: the switch first (nothing is read while it is off), then the method, the size, Fetch Metadata, the session
// cookie, the per-session limit RL_PERF, the per-IP ceiling RL_IP, and the body itself, whose rate must be the
// current one. A limiter that fails refuses: a report is never worth serving through a fault.
export async function perfBeacon(request, env, tally) {
  const done = () => new Response(null, { status: 204, headers: { 'cache-control': 'no-store' } });
  try {
    const rate = perfRate(env);
    if (!rate || request.method !== 'POST') return done();
    const text = await readCapped(request);
    if (text === null) return done();
    if (request.headers.get('sec-fetch-site') !== 'same-origin') return done();
    if (!usableSecret(env.SESSION_SECRET)) return done();
    const v = await verify(env.SESSION_SECRET, readCookie(request.headers.get('cookie')));
    if (v.state !== 'valid' && v.state !== 'renew') return done();
    if (!(await allowed(env.RL_PERF, 'perf:' + v.sid))) return done();
    if (!(await allowed(env.RL_IP, ipKey(request.headers.get('cf-connecting-ip'))))) return done();
    const point = pagePoint(text, rate, request);
    if (point) writePerf(env, tally, point);
  } catch {}
  return done();
}
