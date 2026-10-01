// The recommendations pilot link (issue #400, PR 8 part 1): <site>/#pilot=<token>, checked in the page against the
// SHA-256 in RECS_PILOT_SHA256, with the production switch (RECS_ENABLED) off. tools/recs_pilot.mjs makes the token
// and writes only its hash. Offline: the harness is tests/recs_page_helpers.mjs; nothing is fetched.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { HTML, LOAD_REQUESTS, loadPage, settle } from './recs_page_helpers.mjs';
import { makeToken, sha256Hex, setPilotHash, pilotLink } from '../tools/recs_pilot.mjs';

const TOKEN = makeToken(); // a fresh one per run: no token is ever stored in the repository
const withHash = (hash) => (src) => {
  assert.ok(src.includes('const RECS_PILOT_SHA256 = null;'), 'the page has no RECS_PILOT_SHA256 line');
  return src.replace('const RECS_PILOT_SHA256 = null;', `const RECS_PILOT_SHA256 = '${hash}';`);
};
async function page(opts) {
  const pg = loadPage({ status: { local: false }, ...opts });
  await pg.sb.recsPilotReady;
  await settle();
  if (!pg.sb.S.index) await pg.sb.loadIndex();
  await settle();
  pg.sb.renderSidebar();
  return pg;
}
const on = (pg) => pg.sb.S.recs.on === true && /id="recsOpen"/.test(pg.sidebar());

test('the page ships with no pilot: RECS_PILOT_SHA256 is null, so every #pilot= link does nothing', async () => {
  assert.match(fs.readFileSync(HTML, 'utf8'), /^const RECS_PILOT_SHA256 = null;$/m);
  const pg = await page({ hash: `#pilot=${TOKEN}` });
  assert.equal(on(pg), false);
  assert.equal(pg.sb.location.hash, '#/', 'the token stayed in the address');
});

test('the right token switches recommendations on for this session, takes the token out of the address, and makes no request', async () => {
  const pg = await page({ hash: `#pilot=${TOKEN}`, transform: withHash(sha256Hex(TOKEN)) });
  assert.equal(on(pg), true);
  assert.equal(pg.sb.S.recs.pilot, true);
  assert.equal(pg.sb.location.hash, '#/');
  assert.equal(pg.sessionStore.get('cd.recs.pilot'), sha256Hex(TOKEN));
  assert.ok(!pg.sessionStore.has('cd.recs') && ![...pg.store.values()].some((v) => v.includes(TOKEN)), 'the token was stored');
  assert.deepEqual([...pg.requests].sort(), [...LOAD_REQUESTS].sort(), 'the pilot made a request');
  await pg.sb.recsOpen(); await settle();
  assert.match(pg.panelHtml(), /Pilot: you are trying recommendations before they are released\./);
});

test('a wrong token, an empty one, a plain ?recs=1 or #recs=1 do nothing', async () => {
  const hash = withHash(sha256Hex(TOKEN));
  for (const opts of [{ hash: `#pilot=${TOKEN}x` }, { hash: '#pilot=' }, { search: '?recs=1' }, { hash: '#recs=1' }, { hash: `#pilot=${sha256Hex(TOKEN)}` }]) {
    const pg = await page({ ...opts, transform: hash });
    assert.equal(on(pg), false, JSON.stringify(opts));
    assert.equal(pg.sessionStore.size, 0, JSON.stringify(opts));
  }
});

test('the session keeps it across reloads; #pilot=off ends it; a new hash revokes old sessions', async () => {
  const hash = sha256Hex(TOKEN);
  const reload = await page({ session: { 'cd.recs.pilot': hash }, transform: withHash(hash) });
  assert.equal(on(reload), true);
  const off = await page({ hash: '#pilot=off', session: { 'cd.recs.pilot': hash }, transform: withHash(hash) });
  assert.equal(on(off), false);
  assert.equal(off.sessionStore.has('cd.recs.pilot'), false);
  const rotated = await page({ session: { 'cd.recs.pilot': hash }, transform: withHash(sha256Hex(makeToken())) });
  assert.equal(on(rotated), false, 'an old session survived a new hash');
  const none = await page({ session: { 'cd.recs.pilot': hash } });
  assert.equal(on(none), false, 'a session survived the pilot ending (hash null)');
});

test('the production switch still works on its own, and the pilot adds nothing to a normal page load', async () => {
  const prod = await page({ status: { local: false, recs: true } });
  assert.equal(on(prod), true);
  assert.equal(prod.sb.S.recs.pilot, false);
  const plain = await page({});
  assert.deepEqual([...plain.requests].sort(), [...LOAD_REQUESTS].sort());
});

test('tools/recs_pilot.mjs: a 256-bit base64url token, its SHA-256, one exact line edited, and the link', () => {
  const t = makeToken();
  assert.match(t, /^[A-Za-z0-9_-]{43}$/);
  assert.notEqual(t, makeToken());
  assert.equal(sha256Hex('abc'), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  const page = 'x\nconst RECS_PILOT_SHA256 = null;\ny\n';
  const set = setPilotHash(page, sha256Hex(t));
  assert.equal(set, `x\nconst RECS_PILOT_SHA256 = '${sha256Hex(t)}';\ny\n`);
  assert.equal(setPilotHash(set, null), page);
  assert.throws(() => setPilotHash(page, 'not-a-hash'), /SHA-256/);
  assert.throws(() => setPilotHash('no line here', null), /found 0/);
  assert.throws(() => setPilotHash(page + page, null), /found 2/);
  assert.equal(pilotLink('T'), 'https://college.nextonetwo.com/#pilot=T');
  assert.ok(!fs.readFileSync(new URL('../tools/recs_pilot.mjs', import.meta.url), 'utf8').includes('writeFileSync(PAGE, token'), 'the tool writes the token');
});
