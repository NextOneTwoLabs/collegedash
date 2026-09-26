// The owner's key tool, tools/apikey.mjs (#345 phase 2; ported from ecnl-dashboard's tests/apikey-tool.test.mjs,
// #93). It is run here as a lone copy in a fresh temp folder, under the network guard, with the system temp folder
// pointed into that folder, so the test proves it is self-contained, and removes every file it made.
//
// Until the owner has created the COLLEGEDASH_API_KEYS namespace and its id is in wrangler.toml and the tool, the
// tool carries a placeholder and refuses every command but help. The command tests then run on a copy with a test id
// in place of the placeholder (the only line changed), and the "OWNER STEP" test fails, so the PR cannot go green
// without the real id.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { KEY, hashKey, checkKey, clearKeyCache } from '../api/apikey.mjs';

const TOOL = readFileSync('tools/apikey.mjs', 'utf8');
const TOML = readFileSync('wrangler.toml', 'utf8').replace(/\r\n/g, '\n');
const TOOL_ID = /^const NAMESPACE_ID = '([^']*)';$/m.exec(TOOL)[1];
const TOML_ID = (/^\[\[kv_namespaces\]\]\nbinding = "API_KEYS"\nid = "([^"]*)"$/m.exec(TOML) || [])[1];
const REAL_ID = /^[0-9a-f]{32}$/;
const PLACEHOLDER = 'OWNER_POSTS_THE_COLLEGEDASH_API_KEYS_ID';
const TEST_ID = '0123456789abcdef0123456789abcdef';
const NAMESPACE_ID = REAL_ID.test(TOOL_ID) ? TOOL_ID : TEST_ID;
const NPX = process.platform === 'win32' ? 'npx.cmd' : 'npx';
const WHERE = `--namespace-id ${NAMESPACE_ID} --remote`;
const GUARD = pathToFileURL(resolve('tests/netguard/netguard.mjs')).href;
const KEY_ANYWHERE = new RegExp('cdash' + '_live_[0-9a-f]{12}_[0-9a-f]{64}', 'g');

// Runs a lone copy; -> { status, out, err }. The child's temp folder is <dir>/tmp. `id` replaces the tool's
// NAMESPACE_ID in the copy (default: the real id if the tool has one, else the test id).
function sandbox(id = NAMESPACE_ID) {
  const dir = mkdtempSync(join(tmpdir(), 'cdash-apikey-test-'));
  const temp = join(dir, 'tmp');
  mkdirSync(temp);
  writeFileSync(join(dir, 'apikey.mjs'), TOOL.replace(/^const NAMESPACE_ID = '[^']*';$/m, `const NAMESPACE_ID = '${id}';`));
  const env = { ...process.env, TEMP: temp, TMP: temp, TMPDIR: temp, NETGUARD_REPORT: '1', HTTPS_PROXY: 'http://127.0.0.1:9', HTTP_PROXY: 'http://127.0.0.1:9' };
  const run = (...args) => {
    try {
      return { status: 0, out: execFileSync(process.execPath, ['--import', GUARD, 'apikey.mjs', ...args], { cwd: dir, env, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }), err: '' };
    } catch (e) { return { status: e.status, out: e.stdout, err: e.stderr }; }
  };
  return { dir, temp, run, files: () => readdirSync(temp), cleanup: () => rmSync(dir, { recursive: true, force: true }) };
}
const records = (records, cache = true) => { if (cache) clearKeyCache(); return { API_KEYS: { async get(k) { return records.get(k) ?? null; } } }; };

test('tool: self-contained ASCII file; its namespace id is the one wrangler.toml binds as API_KEYS', () => {
  const src = readFileSync('tools/apikey.mjs');
  assert.ok(src.every(b => b < 128), 'plain ASCII, so a PowerShell 5.1 copy with -Encoding ascii is exact');
  assert.deepEqual([...TOOL.matchAll(/^import .* from '([^']+)';/gm)].map(m => m[1]).filter(s => !s.startsWith('node:')), [], 'Node standard library only');
  assert.ok(TOML_ID !== undefined, 'wrangler.toml binds API_KEYS');
  assert.equal(TOOL_ID, TOML_ID, 'the tool and wrangler.toml name the same namespace');
  assert.ok(TOOL_ID === PLACEHOLDER || REAL_ID.test(TOOL_ID), 'the placeholder or a real 32-hex id, nothing else');
});

test('OWNER STEP: the COLLEGEDASH_API_KEYS namespace id is set (fails until the owner posts it on #345)', () => {
  assert.match(TOML_ID || '', REAL_ID, 'create the KV namespace COLLEGEDASH_API_KEYS in the dashboard and post its id on #345');
  assert.ok(!['effbba53953e424aa9f528b2a6f00f4e', 'dfdeb314f1b848a287e6f99b453a5d22'].includes(TOML_ID), 'its own store, never FEEDBACK or ASK_BUDGET');
});

test('tool with the placeholder id refuses every command but help, and writes nothing', () => {
  const s = sandbox(PLACEHOLDER);
  try {
    for (const args of [['new', '--label', 'verifier-345'], ['revoke', 'abcdef012345', '--label', 'x'], ['list'], ['get', 'abcdef012345'], ['purge', 'abcdef012345']]) {
      const r = s.run(...args);
      assert.equal(r.status, 2, args.join(' '));
      assert.match(r.err, /namespace id is not in this file yet/, args.join(' '));
      assert.equal((r.out + r.err).match(KEY_ANYWHERE), null, 'no key printed');
    }
    assert.equal(s.run('help').status, 0);
    assert.deepEqual(s.files(), []);
  } finally { s.cleanup(); }
});

test('tool new: prints the key once; its record matches api/apikey.mjs and is accepted by checkKey', async () => {
  const s = sandbox();
  try {
    const r = s.run('new', '--label', 'verifier-345', '--ttl', '604800');
    assert.equal(r.status, 0, r.err);
    assert.match(r.out, /^netguard: 0 attempts/m, 'ran under the guard, no network');
    const keys = r.out.match(KEY_ANYWHERE);
    assert.equal(keys.length, 1, 'the key is printed exactly once');
    const key = keys[0], id = KEY.exec(key)[1];
    assert.match(key, KEY, 'the format api/apikey.mjs accepts');
    assert.deepEqual(s.files(), [`cdash-apikey-${id}.json`], 'one record file, in the system temp folder');
    const file = join(s.temp, `cdash-apikey-${id}.json`);
    const raw = readFileSync(file, 'utf8');
    assert.ok(!raw.includes(key.slice(24)), 'the record never holds the secret');
    const rec = JSON.parse(raw);
    assert.deepEqual(Object.keys(rec).sort(), ['created', 'hash', 'label', 'status', 'tier', 'v']);
    assert.equal(rec.hash, await hashKey(key), 'the same hash as api/apikey.mjs');
    assert.deepEqual([rec.v, rec.label, rec.tier, rec.status], [1, 'verifier-345', 'standard', 'active']);
    assert.equal((await checkKey('Bearer ' + key, records(new Map([['key:' + id, rec]])))).state, 'ok');
    // The exact commands, for this owner on this platform.
    assert.ok(r.out.includes(`   ${NPX} wrangler kv key put "key:${id}" --path "${file}" ${WHERE} --ttl 604800\n`), r.out);
    assert.ok(r.out.includes(`   ${NPX} wrangler kv key get "key:${id}" ${WHERE}\n`));
    assert.ok(r.out.includes(process.platform === 'win32' ? `   Remove-Item "${file}"\n` : `   rm "${file}"\n`));
    assert.match(r.out, /revoke [0-9a-f]{12} --label "verifier-345"/);
    assert.match(r.out, /--remote because wrangler v4 otherwise uses a local copy/);
    assert.ok(!/--binding/.test(r.out));
    if (process.platform === 'win32') assert.ok(!/(^|\s)npx /m.test(r.out), 'npx.cmd on Windows');
  } finally { s.cleanup(); }
});

test('tool revoke: needs --label; its record reads as revoked; prints the purge', async () => {
  const s = sandbox();
  try {
    const id = 'abcdef012345';
    const bare = s.run('revoke', id);
    assert.equal(bare.status, 2);
    assert.match(bare.err, /--label is required/);
    assert.deepEqual(s.files(), [], 'nothing written when refused');
    const r = s.run('revoke', id, '--label', 'acme-agent');
    assert.equal(r.status, 0, r.err);
    const file = join(s.temp, `cdash-apikey-${id}-revoked.json`);
    const rec = JSON.parse(readFileSync(file, 'utf8'));
    assert.deepEqual(Object.keys(rec).sort(), ['label', 'revoked', 'status', 'v']);
    assert.deepEqual([rec.v, rec.label, rec.status], [1, 'acme-agent', 'revoked']);
    const key = `cdash_live_${id}_${'0'.repeat(64)}`;
    assert.equal((await checkKey('Bearer ' + key, records(new Map([['key:' + id, rec]])))).state, 'revoked');
    assert.ok(r.out.includes(`   ${NPX} wrangler kv key put "key:${id}" --path "${file}" ${WHERE}\n`), 'no --ttl on a revoke');
    assert.ok(r.out.includes(`   ${NPX} wrangler kv key delete "key:${id}" ${WHERE}`));
    assert.equal(s.run('revoke', 'not-an-id', '--label', 'x').status, 2);
  } finally { s.cleanup(); }
});

test('tool list, get, purge and help print the exact commands', () => {
  const s = sandbox();
  try {
    const id = '0123456789ab';
    assert.ok(s.run('list').out.includes(`   ${NPX} wrangler kv key list ${WHERE} --prefix key:\n`));
    assert.ok(s.run('get', id).out.includes(`   ${NPX} wrangler kv key get "key:${id}" ${WHERE}\n`));
    assert.ok(s.run('purge', id).out.includes(`   ${NPX} wrangler kv key delete "key:${id}" ${WHERE}\n`));
    const help = s.run('help');
    assert.equal(help.status, 0);
    for (const verb of ['new:', 'list:', 'get:', 'revoke:', 'purge:']) assert.ok(help.out.includes(verb), verb);
    assert.match(help.out, /project or agent name/);
    assert.match(help.out, /never a person's name/);
    assert.match(help.out, /standalone PowerShell window/);
    assert.equal(s.run('get').status, 2);
    assert.equal(s.run().status, 2);
    assert.equal(s.run('rotate').status, 2);
    assert.deepEqual(s.files(), []);
  } finally { s.cleanup(); }
});

test('tool refuses --ttl under 60 and bad labels, and writes nothing then', () => {
  const s = sandbox();
  try {
    for (const ttl of ['30', '59', '0', '-60', '1e3', 'abc', '']) {
      const r = s.run('new', '--label', 'ttl-test', '--ttl', ttl);
      assert.equal(r.status, 2, `--ttl ${JSON.stringify(ttl)}`);
    }
    assert.match(s.run('new', '--label', 'ttl-test', '--ttl', '30').err, /at least 60/);
    for (const label of ['a@b.c', ' lead', 'x'.repeat(41), '', 'x<y>', '--ttl']) {
      assert.equal(s.run('new', '--label', label).status, 2, JSON.stringify(label));
    }
    assert.equal(s.run('new').status, 2, 'no label');
    assert.deepEqual(s.files(), []);
    const ok = s.run('new', '--label', 'ttl-test', '--ttl', '60');
    assert.equal(ok.status, 0, ok.err);
    assert.match(ok.out, / --ttl 60\n/);
    assert.equal(s.files().length, 1);
  } finally { s.cleanup(); }
  assert.deepEqual(readdirSync(tmpdir()).filter(n => n === s.dir.split(/[\\/]/).pop()), [], 'cleaned up');
});
