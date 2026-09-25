// Ported verbatim from NextOneTwoLabs/ecnl-dashboard for collegedash issue #345.
// Self-check of tests/netguard/netguard.mjs. The attempts are made in a child process with the
// guard preloaded, so this run's own guard still counts 0. Every refusal happens before any
// lookup or connection is made.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

const guard = new URL('./netguard/netguard.mjs', import.meta.url).href;
const child = `
  const net = require('node:net'), dns = require('node:dns');
  const tryIt = (name, fn) => { try { fn(); console.log(name, 'allowed'); } catch (e) { console.log(name, 'refused'); } };
  tryIt('socket name', () => net.connect(443, '127.0.0.1.example.com').on('error', () => {}));
  tryIt('dns name', () => dns.lookup('127.0.0.1.example.com', () => {}));
  tryIt('fetch name', () => fetch('http://127.0.0.1.example.com/').catch(() => {}));
  tryIt('socket other', () => net.connect(443, '192.0.2.1').on('error', () => {}));
  const server = net.createServer(socket => socket.end()).listen(0, '127.0.0.1', () => {
    const socket = net.connect(server.address().port, '127.0.0.1', () => { console.log('socket loopback allowed'); socket.end(); server.close(); });
  });
`;

test('netguard refuses names that merely start with 127. and allows the loopback literal', () => {
  const run = spawnSync(process.execPath, ['--import', guard, '-e', child], { encoding: 'utf8', timeout: 20000, env: { ...process.env, NETGUARD_REPORT: '1' } });
  const lines = run.stdout.trim().split(/\r?\n/);
  for (const name of ['socket name', 'dns name', 'fetch name', 'socket other']) assert.ok(lines.includes(`${name} refused`), `${name}: ${run.stdout}`);
  assert.ok(lines.includes('socket loopback allowed'), run.stdout);
  assert.match(run.stdout, /netguard: 4 attempts/);
  assert.equal(run.status, 97, 'a guarded process that attempted anything fails at exit');
});
