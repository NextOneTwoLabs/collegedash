// Pure validation for POST /api/feedback.
//
// This module holds every rule that decides whether a submission is acceptable, and nothing that
// touches the network, KV or the Workers runtime. worker.js imports it (wrangler bundles the
// import) and tests/feedback.test.mjs imports the same file, so the tested code is the shipped
// code and no copy can drift.
//
// Everything here treats the submission as hostile text written by an anonymous stranger. It is
// never echoed back to the client and never rendered into the site; it is stored and later quoted
// into a GitHub issue as data, never as instructions.

/** Field name for the honeypot input. Deliberately not "website", "url", "company" or anything
 *  else a password manager or browser autofill recognises - a filled honeypot must mean a bot,
 *  not a helpful autofill, or real feedback gets flagged as spam. */
export const HONEYPOT_FIELD = 'hp_ref';

export const LIMITS = {
  /** Hard cap on the request body, enforced by the Worker while reading the stream. The same
   *  number is re-checked here so the rule has one home. 8 KB comfortably holds a 2,000-character
   *  message even when every character is a 4-byte emoji JSON-escaped to 12 bytes. */
  bodyBytes: 8192,
  message: 2000,
  email: 254,
  route: 200,
  userAgent: 300,
  /** Milliseconds between the dialog opening and Send. Anything faster is scripted. Measured from
   *  dialog open rather than page load, so a reader who takes their time is never penalised. */
  minElapsedMs: 1200,
};

const SLUG_RE = /^[a-z0-9-]{1,64}$/;

/** Unpaired UTF-16 surrogates. JSON.parse happily produces them from a "\uD800" escape; they are
 *  not valid text, they break TextEncoder round-trips, and they must never reach KV metadata. */
const LONE_SURROGATE_RE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g;

/** C0/C7 control characters except tab and newline. */
const CONTROL_RE = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g;

/** Remove unpaired surrogates only. Used where control characters must survive (KV metadata
 *  previews re-measure after JSON.stringify instead of pre-stripping) but a lone surrogate must
 *  not, because it would round-trip through TextEncoder as U+FFFD. */
export function stripLoneSurrogates(value) {
  if (typeof value !== 'string') return '';
  return value.replace(LONE_SURROGATE_RE, '');
}

/** Strip lone surrogates and stray control characters. Keeps the stored value printable and keeps
 *  every later byte measurement honest. */
export function cleanText(value) {
  if (typeof value !== 'string') return '';
  return stripLoneSurrogates(value).replace(CONTROL_RE, '');
}

/** Byte length of a string as UTF-8. */
export function byteLength(value) {
  return new TextEncoder().encode(value).length;
}

/** Truncate to at most maxBytes of UTF-8 without ever splitting a character.
 *
 *  str.slice(n) is wrong here: "ok \u{1F600}!".slice(0, 4) keeps half an emoji, which encodes to
 *  EF BF BD and makes JSON.stringify emit a lone surrogate. TextEncoder#encodeInto refuses to
 *  split a character - given a 6-byte buffer for "ok \u{1F600}!" it reports read: 3, written: 3 -
 *  so slicing at result.read is safe by construction. */
export function sliceBytes(str, maxBytes) {
  if (typeof str !== 'string' || str.length === 0 || maxBytes <= 0) return '';
  if (byteLength(str) <= maxBytes) return str;
  const buf = new Uint8Array(maxBytes);
  const { read } = new TextEncoder().encodeInto(str, buf);
  return str.slice(0, read);
}

/** A coarse browser/OS family, e.g. "Chrome on Windows". A full user-agent string is a
 *  fingerprinting vector and a bug report never needs one. */
export function uaFamily(ua) {
  const s = cleanText(ua || '').slice(0, LIMITS.userAgent);
  if (!s) return '';
  let browser = 'Other';
  if (/\bEdg\//.test(s)) browser = 'Edge';
  else if (/\bOPR\/|\bOpera\b/.test(s)) browser = 'Opera';
  else if (/\bFirefox\//.test(s)) browser = 'Firefox';
  else if (/\bChrome\//.test(s)) browser = 'Chrome';
  else if (/\bSafari\//.test(s) && /\bVersion\//.test(s)) browser = 'Safari';
  let os = 'Other';
  if (/\bWindows NT\b/.test(s)) os = 'Windows';
  else if (/\bAndroid\b/.test(s)) os = 'Android';
  else if (/\b(iPhone|iPad|iPod)\b/.test(s)) os = 'iOS';
  else if (/\bMac OS X\b/.test(s)) os = 'macOS';
  else if (/\bCrOS\b/.test(s)) os = 'ChromeOS';
  else if (/\bLinux\b/.test(s)) os = 'Linux';
  return browser + ' on ' + os;
}

function reject(status, error) {
  return { ok: false, status, error };
}

/**
 * Validate one raw request body.
 *
 * @param {string|null} raw The body as text. null means the reader hit the byte cap.
 * @returns {{ok: true, spamReason: string|null, value: object}
 *          |{ok: false, status: number, error: string}}
 *
 * A spam verdict is still ok:true. Honeypot and elapsed hits are *stored* under the `spam:` key
 * prefix rather than silently dropped - a false positive that vanishes behind a fake thank-you
 * loses real feedback, and both signals are weak enough to produce false positives.
 */
export function validateFeedback(raw) {
  if (raw === null || raw === undefined) return reject(413, 'body too large');
  if (typeof raw !== 'string') return reject(400, 'invalid body');
  if (byteLength(raw) > LIMITS.bodyBytes) return reject(413, 'body too large');

  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return reject(400, 'invalid json');
  }
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    return reject(400, 'invalid json');
  }

  const message = cleanText(body.message).trim();
  if (!message) return reject(400, 'message required');
  if (message.length > LIMITS.message) return reject(400, 'message too long');

  const email = cleanText(body.email).trim();
  if (email.length > LIMITS.email) return reject(400, 'email too long');
  // Deliberately not a full RFC 5322 check: an address that never receives a reply is the
  // visitor's problem, a rejected submission is ours. Only an obvious non-address is refused.
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return reject(400, 'email invalid');

  const route = cleanText(body.route).trim();
  if (route.length > LIMITS.route) return reject(400, 'route too long');

  const slug = cleanText(body.slug).trim();
  if (slug && !SLUG_RE.test(slug)) return reject(400, 'slug invalid');

  const elapsed = Number.isFinite(body.elapsed) ? Math.trunc(body.elapsed) : null;

  let spamReason = null;
  // The honeypot value itself is never stored - only the fact that it was filled.
  if (cleanText(body[HONEYPOT_FIELD]).trim()) spamReason = 'honeypot';
  else if (elapsed !== null && elapsed < LIMITS.minElapsedMs) spamReason = 'elapsed';

  return {
    ok: true,
    spamReason,
    value: { message, email, route, slug, elapsed },
  };
}
