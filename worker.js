// Entry point for the deployed Worker. The site itself is the static files in public/ (see
// [assets] in wrangler.toml); this script sends the workers.dev address to the canonical custom
// domain and serves the two small /api/* endpoints. It runs ahead of the static assets for "/"
// and "/api/*" only (run_worker_first in wrangler.toml), so a page view costs one Worker request
// and every other file is served as a free static asset.
//
// Browsers carry the #fragment across a redirect, so deep links such as #/p/stanford/roster
// still land on the right page.
//
// Endpoints:
//   GET  /api/status    -> {"local":false}. The local dev server (serve.py) answers true; the
//                          front end uses it to decide whether write actions are available.
//                          Before this existed the request 404'd and logged a console error on
//                          every page load (issue #11).
//   POST /api/feedback  -> stores one visitor submission in the FEEDBACK KV namespace.
//                          Ships disabled: FEEDBACK_ENABLED must be "1" (see wrangler.toml).
//
// Nothing here echoes a submission back to the client, and nothing renders one into the site.
import {
  HONEYPOT_FIELD,
  LIMITS,
  sliceBytes,
  stripLoneSurrogates,
  uaFamily,
  validateFeedback,
} from './feedback-validate.mjs';

const CANONICAL_HOST = 'college.nextonetwo.com';

/** Origins allowed to POST feedback. The check stops a cross-site form post and nothing else - a
 *  scripted client sets any header it likes - but it is free and it is the half of the pair that
 *  a browser cannot be talked out of sending. */
const ALLOWED_ORIGINS = new Set([
  'https://' + CANONICAL_HOST,
  'https://collegedash.nextonetwolabs.workers.dev',
]);

/** KV metadata is capped at 1024 bytes by Cloudflare. Exceeding it fails the write. */
const META_MAX_BYTES = 1024;
/** Longest route string kept in the metadata preview line. */
const META_ROUTE_BYTES = 120;

/** Retention, enforced by the storage layer rather than by a cron job anybody can forget. */
const TTL_NEW = 31536000; // 365 days
const TTL_SPAM = 2592000; // 30 days - spam is the bulk under a flood and worth far less

const ID_ALPHABET = '0123456789abcdefghijklmnopqrstuvwxyz';

/**
 * 8 random lowercase alphanumerics from crypto.getRandomValues.
 *
 * The modulo introduces a slight bias across 256 -> 36; irrelevant for a uniqueness suffix. Two
 * submissions in the same millisecond with the same suffix would be a silent overwrite. At a
 * handful of submissions a month that is negligible, but it is a real property of the design and
 * is stated rather than assumed away.
 *
 * @param {Uint8Array} [bytes] Injected randomness, for tests.
 */
export function newId(bytes) {
  const a = bytes || crypto.getRandomValues(new Uint8Array(8));
  let out = '';
  for (let i = 0; i < a.length; i++) out += ID_ALPHABET[a[i] % ID_ALPHABET.length];
  return out;
}

/**
 * `<status>:<ISO-8601 UTC ms>:<id>`, e.g. new:2026-09-10T14:23:05.123Z:k7f3q9x2
 *
 * Date#toISOString is a fixed 24 characters with every field zero-padded, so plain string sort
 * equals chronological sort and `--prefix "new:"` is a real server-side "unfiled work" query.
 * The status lives in the prefix, so filing is a delete plus a small `filed:` tombstone rather
 * than a rewrite.
 */
export function feedbackKey(status, date, id) {
  return status + ':' + date.toISOString() + ':' + id;
}

/**
 * Build the KV metadata object for one submission, capped at META_MAX_BYTES.
 *
 * Metadata is what `wrangler kv key list` returns, so the whole triage queue can be read without
 * fetching a single value. The preview is therefore the first visitor-written text a human or an
 * agent sees, which is why the README's triage rule names the listing explicitly.
 *
 * Two traps this avoids:
 *   - Truncating with String#slice can cut a surrogate pair in half; JSON.stringify then emits a
 *     lone surrogate. sliceBytes uses encodeInto and slices at result.read, which never splits a
 *     character.
 *   - A byte budget computed on the raw preview is not a budget on the stored bytes, because JSON
 *     escaping expands: one control character is 1 raw byte and 6 JSON bytes. The loop
 *     therefore re-measures encode(JSON.stringify(meta)).length after each cut.
 *
 * If the non-preview fields alone do not fit, it returns with a zero-length preview rather than
 * looping forever.
 */
export function metaFor(fields, maxBytes = META_MAX_BYTES) {
  const enc = new TextEncoder();
  const meta = {};
  if (fields.t) meta.t = String(fields.t);
  const route = sliceBytes(stripLoneSurrogates(fields.route || ''), META_ROUTE_BYTES);
  if (route) meta.r = route;
  if (fields.slug) meta.p = stripLoneSurrogates(String(fields.slug));
  if (fields.country) meta.c = stripLoneSurrogates(String(fields.country));
  // "s" (status) is deliberately absent: the key prefix already carries it and the bytes are
  // better spent on the preview.
  meta.m = '';

  const size = () => enc.encode(JSON.stringify(meta)).length;
  const overhead = size();
  if (overhead >= maxBytes) return meta;

  meta.m = sliceBytes(stripLoneSurrogates(fields.message || ''), maxBytes - overhead);
  let over = size() - maxBytes;
  while (meta.m.length > 0 && over > 0) {
    // 6 is the worst-case JSON expansion per source character, so this always makes progress
    // and never overshoots wildly.
    const cut = Math.max(1, Math.ceil(over / 6));
    let next = meta.m.slice(0, Math.max(0, meta.m.length - cut));
    // A cut can leave a trailing high surrogate with no partner.
    next = stripLoneSurrogates(next);
    meta.m = next;
    over = size() - maxBytes;
  }
  if (over > 0) meta.m = '';
  return meta;
}

function json(body, status, headers) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', ...(headers || {}) },
  });
}

/**
 * Read the body as text, giving up once maxBytes have arrived.
 *
 * This, not the Content-Length header, is the real bound: Content-Length is supplied by the
 * client and a hostile one can lie or omit it entirely.
 *
 * @returns {Promise<string|null>} null when the cap was exceeded.
 */
async function readBoundedText(request, maxBytes) {
  if (!request.body) return '';
  const reader = request.body.getReader();
  const chunks = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const buf = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    buf.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(buf);
}

/** GET /api/status - three lines that close issue #11. */
function handleStatus(request) {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return json({ error: 'method not allowed' }, 405, { allow: 'GET' });
  }
  return json({ local: false }, 200, { 'cache-control': 'no-store' });
}

/** POST /api/feedback */
async function handleFeedback(request, env) {
  if (request.method !== 'POST') {
    return json({ error: 'method not allowed' }, 405, { allow: 'POST' });
  }

  // Kill switch. Ships as "0", so the endpoint is inert until the owner has created the KV
  // namespace and the Cloudflare rate-limiting rule. Note that `wrangler deploy` replaces
  // plaintext vars from wrangler.toml, so a dashboard edit lasts only until the next deploy -
  // and the daily data refresh pushes to main, which deploys. The durable switch is a commit.
  if (env.FEEDBACK_ENABLED !== '1') {
    return json({ error: 'feedback is not accepting submissions' }, 503);
  }
  // Fail closed on a missing or misnamed binding rather than throwing into the router.
  if (!env.FEEDBACK) {
    return json({ error: 'feedback storage unavailable' }, 503);
  }

  const origin = request.headers.get('origin') || '';
  if (!ALLOWED_ORIGINS.has(origin)) {
    return json({ error: 'origin not allowed' }, 403);
  }

  const contentType = (request.headers.get('content-type') || '').toLowerCase();
  if (!contentType.startsWith('application/json')) {
    return json({ error: 'expected application/json' }, 400);
  }

  // Advisory only. The value is attacker-supplied, so a lie here proves nothing; it just lets an
  // honest oversized request be refused before a byte of it is read. A chunked POST sends no
  // Content-Length at all and is accepted - returning 411 would reject legitimate clients. The
  // enforced bound is the read cap in readBoundedText below.
  const declared = Number(request.headers.get('content-length'));
  if (Number.isFinite(declared) && declared > LIMITS.bodyBytes) {
    return json({ error: 'body too large' }, 413);
  }

  const raw = await readBoundedText(request, LIMITS.bodyBytes);
  const result = validateFeedback(raw);
  if (!result.ok) {
    return json({ error: result.error }, result.status);
  }

  const now = new Date();
  const status = result.spamReason ? 'spam' : 'new';
  const key = feedbackKey(status, now, newId());
  const country = request.headers.get('cf-ipcountry') || (request.cf && request.cf.country) || '';

  // Stored value. No IP and no IP hash: nothing pseudonymous is retained, so there is no salt
  // secret to manage and nothing to null out later. The honeypot's own value is not stored.
  const record = {
    message: result.value.message,
    reply_email: result.value.email || null,
    route: result.value.route || null,
    program_slug: result.value.slug || null,
    country: country || null,
    ua_family: uaFamily(request.headers.get('user-agent')),
    created_at: now.toISOString(),
    elapsed_ms: result.value.elapsed,
    spam_reason: result.spamReason,
    honeypot_field: result.spamReason === 'honeypot' ? HONEYPOT_FIELD : null,
  };

  await env.FEEDBACK.put(key, JSON.stringify(record), {
    expirationTtl: status === 'spam' ? TTL_SPAM : TTL_NEW,
    metadata: metaFor({
      t: record.created_at,
      route: record.route,
      slug: record.program_slug,
      country: record.country,
      message: record.message,
    }),
  });

  // Never echoes the submission, and never returns the key.
  return json({ ok: true }, 200);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // /api/* is routed before the workers.dev redirect below. A 301 is downgraded to GET by most
    // clients, so redirecting a POST would silently turn a submission into a page view.
    if (url.pathname.startsWith('/api/')) {
      try {
        if (url.pathname === '/api/status') return handleStatus(request);
        if (url.pathname === '/api/feedback') return await handleFeedback(request, env);
        return json({ error: 'not found' }, 404);
      } catch (err) {
        // A throw here must never reach the router: "/" is run_worker_first, so an uncaught
        // error would break the home page for everyone. One endpoint degrades instead.
        console.error('api error', (err && err.stack) || err);
        return json({ error: 'unavailable' }, 503);
      }
    }

    if (url.hostname.endsWith('.workers.dev')) {
      url.hostname = CANONICAL_HOST;
      return Response.redirect(url.toString(), 301);
    }
    return env.ASSETS.fetch(request);
  },
};
