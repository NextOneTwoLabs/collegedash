// Ported verbatim from NextOneTwoLabs/ecnl-dashboard (#89, #90 there) for collegedash issue #345;
// .github/scripts/run_node_suites.py preloads it into every Node suite, locally and in CI.
// Test-only Node network guard (#89 item 5, #90), the Node twin of sitecustomize.py here.
// Preload it into every Node test process:
//
//   node --import ./tests/netguard/netguard.mjs --test tests/data-api.test.mjs tests/session.test.mjs
//
// `node --test` passes the --import on to the child process it runs each file in. The guard
// refuses every non-loopback socket connection, TLS connection, DNS lookup and fetch, records
// each attempt, and at exit fails the process with status 97 when anything was attempted, even
// if the code under test swallowed the error. Set NETGUARD_REPORT=1 to print the attempt count
// when it is 0.
import net from 'node:net';
import tls from 'node:tls';
import dns from 'node:dns';
import dnsPromises from 'node:dns/promises';

const attempts = [];
// An IPv4 loopback literal only: a name such as 127.0.0.1.example.com is not loopback.
const loopback = host => !host || host === 'localhost' || /^127(\.\d{1,3}){3}$/.test(host) || host === '::1' || host === '[::1]';
const deny = what => { attempts.push(what); console.error('netguard: blocked ' + what); throw new Error('netguard: blocked ' + what); };

const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  const options = Array.isArray(args[0]) ? args[0][0] : typeof args[0] === 'object' ? args[0] : { port: args[0], host: args[1] };
  if (options && !options.path && !loopback(options.host)) deny(`connect ${options.host}:${options.port}`);
  return connect.apply(this, args);
};
const tlsConnect = tls.connect;
tls.connect = function (...args) {
  const options = typeof args[0] === 'object' ? args[0] : { port: args[0], host: typeof args[1] === 'string' ? args[1] : undefined };
  if (!loopback(options.host || options.servername)) deny('tls ' + (options.host || options.servername));
  return tlsConnect.apply(this, args);
};
for (const name of ['lookup', 'resolve', 'resolve4', 'resolve6', 'resolveAny']) {
  const callback = dns[name];
  if (callback) dns[name] = function (host, ...rest) { if (!loopback(host)) deny('dns ' + host); return callback.call(this, host, ...rest); };
  const promise = dnsPromises[name];
  if (promise) dnsPromises[name] = function (host, ...rest) { if (!loopback(host)) deny('dns ' + host); return promise.call(this, host, ...rest); };
}
const fetch = globalThis.fetch;
globalThis.fetch = function (input, ...rest) {
  const url = String(input?.url ?? input);
  if (!/^https?:\/\/(127\.[0-9.]+|localhost|\[::1\])(:\d+)?(\/|$)/.test(url)) deny('fetch ' + url);
  return fetch.call(this, input, ...rest);
};

process.on('exit', () => {
  if (attempts.length || process.env.NETGUARD_REPORT === '1') console.log(`netguard: ${attempts.length} attempts (pid ${process.pid})`);
  if (attempts.length) process.exitCode = 97;
});
