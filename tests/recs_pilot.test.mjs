// The recommendations pilot link (issue #400, PR 8 part 1): <site>/#pilot=<token>, checked in the page against the
// SHA-256 in RECS_PILOT_SHA256, with the production switch (RECS_ENABLED) off. tools/recs_pilot.mjs makes the token
// and writes only its hash. Offline: the harness is tests/recs_page_helpers.mjs; nothing is fetched.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { HTML, LOAD_REQUESTS, loadPage, settle } from './recs_page_helpers.mjs';
import { makeToken, sha256Hex, setPilotHash, pilotLink, runPilot, WARNING, NOT_A_TERMINAL } from '../tools/recs_pilot.mjs';

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

// ---------- #433 review: strip first, never throw; the tool's own output warns, and only a terminal sees a link ----------

test('#433 review: the address is stripped by the first statement of the script, before any other code runs', () => {
  const lines = fs.readFileSync(HTML, 'utf8').split(/\r?\n/);
  const a = lines.findIndex((l) => l.trim() === '<script>');
  const code = lines.slice(a + 1).filter((l) => l.trim() && !/^\s*(\/\/|\/\*|\*)/.test(l));
  assert.equal(code[0], "'use strict';");
  assert.equal(code[1], 'const RECS_PILOT_RAW = (() => {', 'something runs before the pilot token leaves the address');
});

test('#433 review: a malformed link still leaves the address as #/, and switches nothing on', async () => {
  for (const bad of ['%E0%A4', '%', `${TOKEN}%`]) {
    const pg = await page({ hash: `#pilot=${bad}`, transform: withHash(sha256Hex(TOKEN)) });
    assert.equal(pg.sb.location.hash, '#/', `#pilot=${bad} stayed in the address`);
    assert.equal(on(pg), false);
    assert.equal(pg.sessionStore.size, 0);
  }
});

test('#433 review: when history.replaceState is refused, location.replace strips the address and the right token still works', async () => {
  const refuse = (src) => "history.replaceState = () => { throw new Error('SecurityError'); };\n" + withHash(sha256Hex(TOKEN))(src);
  const pg = await page({ hash: `#pilot=${TOKEN}`, transform: refuse });
  assert.equal(pg.sb.location.hash, '#/', 'the token stayed in the address');
  assert.equal(on(pg), true);
});

test('#433 review: the tool makes a link only for an interactive terminal, and its output carries the warning', () => {
  const page = 'x\nconst RECS_PILOT_SHA256 = null;\ny\n';
  const piped = runPilot('new', page, { tty: false });
  assert.deepEqual([piped.html, piped.lines, piped.code], [null, [NOT_A_TERMINAL], 1], 'a pipe or an assistant could capture the link');
  const t = makeToken();
  const tty = runPilot('new', page, { tty: true, token: t });
  assert.equal(tty.html, setPilotHash(page, sha256Hex(t)));
  assert.equal(tty.lines.filter((l) => l.includes(t)).length, 1, 'the link is not printed exactly once');
  assert.equal(tty.lines[0], WARNING);
  assert.equal(tty.lines.at(-1), WARNING);
  assert.match(WARNING, /chat, an issue or a PR/);
  assert.match(WARNING, /assistant/);
  const off = runPilot('off', setPilotHash(page, sha256Hex(t)), { tty: false });
  assert.equal(off.html, page, 'off needs no terminal: it prints no link');
});
