// node --test tests/feedback.test.mjs
//
// Covers the pure parts of the feedback endpoint: the validator (imported from the same module
// worker.js imports, so there is no copy to drift), the KV metadata builder and the key format.
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  HONEYPOT_FIELD,
  LIMITS,
  sliceBytes,
  uaFamily,
  validateFeedback,
} from '../feedback-validate.mjs';
import { feedbackKey, metaFor, newId } from '../worker.js';

const body = (obj) => JSON.stringify(obj);
const bytes = (s) => new TextEncoder().encode(s).length;

const EMOJI = String.fromCodePoint(0x1f600); // one 4-byte character, two UTF-16 code units
const HIGH_SURROGATE = String.fromCharCode(0xd800); // unpaired on its own
const BELL = String.fromCharCode(7);
const SOH = String.fromCharCode(1);

/** True when the string contains a surrogate without its partner. Written as a scan rather than a
 *  regex so this file itself contains no surrogate escapes. */
function hasLoneSurrogate(s) {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      const next = s.charCodeAt(i + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return true;
      i++;
    } else if (c >= 0xdc00 && c <= 0xdfff) {
      return true;
    }
  }
  return false;
}

// --------------------------------------------------------------------- validateFeedback

test('accepts a plain submission', () => {
  const r = validateFeedback(body({ message: '  the Duke roster is stale  ', elapsed: 9000 }));
  assert.equal(r.ok, true);
  assert.equal(r.spamReason, null);
  assert.equal(r.value.message, 'the Duke roster is stale');
});

test('rejects an empty or whitespace-only message', () => {
  for (const message of ['', '   ', '\n\t', undefined]) {
    const r = validateFeedback(body({ message, elapsed: 9000 }));
    assert.equal(r.ok, false);
    assert.equal(r.status, 400);
    assert.equal(r.error, 'message required');
  }
});

test('enforces the length caps', () => {
  const atCap = validateFeedback(body({ message: 'a'.repeat(LIMITS.message), elapsed: 9000 }));
  assert.equal(atCap.ok, true);

  const overCap = validateFeedback(body({ message: 'a'.repeat(LIMITS.message + 1), elapsed: 9000 }));
  assert.equal(overCap.ok, false);
  assert.equal(overCap.status, 400);
  assert.equal(overCap.error, 'message too long');

  const longEmail = validateFeedback(
    body({ message: 'hi', elapsed: 9000, email: 'a'.repeat(LIMITS.email) + '@x.com' })
  );
  assert.equal(longEmail.ok, false);
  assert.equal(longEmail.error, 'email too long');

  const longRoute = validateFeedback(
    body({ message: 'hi', elapsed: 9000, route: '/'.repeat(LIMITS.route + 1) })
  );
  assert.equal(longRoute.ok, false);
  assert.equal(longRoute.error, 'route too long');
});

test('rejects a malformed slug and accepts a real one', () => {
  for (const slug of ['Duke', 'duke/roster', 'duke_1', 'x'.repeat(65), '../etc']) {
    const r = validateFeedback(body({ message: 'hi', elapsed: 9000, slug }));
    assert.equal(r.ok, false, 'expected ' + slug + ' to be rejected');
    assert.equal(r.error, 'slug invalid');
  }
  const ok = validateFeedback(body({ message: 'hi', elapsed: 9000, slug: 'abilene-christian' }));
  assert.equal(ok.ok, true);
  assert.equal(ok.value.slug, 'abilene-christian');
});

test('rejects non-JSON and non-object bodies with 400', () => {
  for (const raw of ['not json at all', '{"message":', '[]', '"a string"', '42', 'null']) {
    const r = validateFeedback(raw);
    assert.equal(r.ok, false, 'expected ' + raw + ' to be rejected');
    assert.equal(r.status, 400);
  }
});

test('rejects an oversized body with 413, and null (reader hit the cap) too', () => {
  const huge = body({ message: 'a'.repeat(LIMITS.bodyBytes + 100) });
  assert.ok(bytes(huge) > LIMITS.bodyBytes);
  const r = validateFeedback(huge);
  assert.equal(r.ok, false);
  assert.equal(r.status, 413);

  const capped = validateFeedback(null);
  assert.equal(capped.ok, false);
  assert.equal(capped.status, 413);
});

test('a filled honeypot is stored as spam, not discarded', () => {
  const r = validateFeedback(body({ message: 'buy pills', elapsed: 9000, [HONEYPOT_FIELD]: 'x' }));
  assert.equal(r.ok, true);
  assert.equal(r.spamReason, 'honeypot');
  assert.equal(r.value.message, 'buy pills');
});

test('elapsed below the floor is stored as spam; at or above it is clean', () => {
  const fast = validateFeedback(body({ message: 'hi', elapsed: LIMITS.minElapsedMs - 1 }));
  assert.equal(fast.ok, true);
  assert.equal(fast.spamReason, 'elapsed');

  const ok = validateFeedback(body({ message: 'hi', elapsed: LIMITS.minElapsedMs }));
  assert.equal(ok.spamReason, null);

  // A missing or non-numeric elapsed is not a spam signal on its own.
  assert.equal(validateFeedback(body({ message: 'hi' })).spamReason, null);
  assert.equal(validateFeedback(body({ message: 'hi', elapsed: 'soon' })).spamReason, null);
});

test('strips lone surrogates and control characters from stored text', () => {
  const raw = 'a' + BELL + 'b' + HIGH_SURROGATE + 'c';
  const r = validateFeedback(body({ message: raw, elapsed: 9000 }));
  assert.equal(r.ok, true);
  assert.equal(r.value.message, 'abc');
});

test('uaFamily derives a coarse family, never the raw string', () => {
  const chrome =
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36';
  assert.equal(uaFamily(chrome), 'Chrome on Windows');
  assert.equal(uaFamily(''), '');
});

// --------------------------------------------------------------------- sliceBytes / metaFor

test('sliceBytes never splits a character', () => {
  assert.equal(sliceBytes('ok ' + EMOJI + '!', 6), 'ok ');
  assert.ok(!hasLoneSurrogate(sliceBytes(EMOJI + EMOJI, 5)));
});

test('metaFor: 2,000 emoji plus a 120-character route fits in 1024 bytes, no lone surrogate', () => {
  const meta = metaFor({
    t: '2026-09-10T14:23:05.123Z',
    route: '/p/' + 'a'.repeat(117),
    slug: 'abilene-christian',
    country: 'US',
    message: EMOJI.repeat(2000),
  });
  const encoded = JSON.stringify(meta);
  assert.ok(bytes(encoded) <= 1024, 'metadata was ' + bytes(encoded) + ' bytes');
  assert.ok(!hasLoneSurrogate(encoded), 'metadata JSON contains an unpaired surrogate');
  assert.ok(meta.m.length > 0, 'preview should not be empty');
  assert.equal(meta.r.length, 120);
});

test('metaFor: an all-control-character message still fits (JSON escaping expands sixfold)', () => {
  const meta = metaFor({
    t: '2026-09-10T14:23:05.123Z',
    route: '/#/p/duke/roster',
    slug: 'duke',
    country: 'GB',
    message: SOH.repeat(2000),
  });
  const encoded = JSON.stringify(meta);
  assert.ok(bytes(encoded) <= 1024, 'metadata was ' + bytes(encoded) + ' bytes');
  // A budget computed on raw bytes would have kept ~800 characters and stored ~4,800 bytes.
  assert.ok(meta.m.length < 300, 'preview kept ' + meta.m.length + ' characters');
});

test('metaFor: oversized non-preview fields terminate at preview length 0', () => {
  const meta = metaFor({
    t: '2026-09-10T14:23:05.123Z',
    route: 'r'.repeat(120),
    slug: 's'.repeat(2000),
    country: 'US',
    message: 'this should not survive',
  });
  assert.equal(meta.m, '');
});

test('metaFor: a short message is kept whole and status is not duplicated', () => {
  const meta = metaFor({
    t: '2026-09-10T14:23:05.123Z',
    route: '/#/p/duke',
    slug: 'duke',
    country: 'US',
    message: 'the roster is stale',
  });
  assert.equal(meta.m, 'the roster is stale');
  assert.equal(meta.s, undefined);
});

// --------------------------------------------------------------------- keys

test('keys sort chronologically as plain strings, including across a day boundary', () => {
  const dates = [
    new Date(Date.UTC(2026, 0, 2, 0, 0, 0, 5)), // single-digit month and day
    new Date(Date.UTC(2026, 0, 1, 23, 59, 59, 999)),
    new Date(Date.UTC(2026, 8, 9, 5, 4, 3, 20)),
    new Date(Date.UTC(2026, 9, 10, 5, 4, 3, 2)),
    new Date(Date.UTC(2025, 11, 31, 23, 59, 59, 999)),
  ];
  const keys = dates.map((d, i) => feedbackKey('new', d, 'id00000' + i));
  const byString = [...keys].sort();
  const byTime = dates
    .map((d, i) => ({ d, k: keys[i] }))
    .sort((a, b) => a.d - b.d)
    .map((x) => x.k);
  assert.deepEqual(byString, byTime);
  assert.match(keys[0], /^new:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z:[0-9a-z]{8}$/);
});

test('the filed: tombstone shares the new: suffix exactly', () => {
  const d = new Date(Date.UTC(2026, 8, 10, 14, 23, 5, 123));
  const k = feedbackKey('new', d, 'k7f3q9x2');
  assert.equal('filed:' + k.slice('new:'.length), feedbackKey('filed', d, 'k7f3q9x2'));
});

test('newId is 8 lowercase alphanumerics', () => {
  assert.match(newId(), /^[0-9a-z]{8}$/);
  assert.equal(newId(new Uint8Array([0, 1, 2, 3, 4, 5, 6, 7])), '01234567');
});
