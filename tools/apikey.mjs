// Owner tool for /api/v1 API keys (#345 phase 2). See docs/data-api.md, "API keys".
// Ported from NextOneTwoLabs/ecnl-dashboard tools/apikey.mjs (#93); only the prefix, the namespace and the
// labels in the examples differ.
//
// Self-contained on purpose: Node's standard library only and no import from this repo, so this
// one file runs anywhere, even before the PR that adds it is merged. It makes no network
// request and never runs wrangler. It prints a new key once, writes only the key's hash record
// to the system temp folder, and prints the exact wrangler commands for the owner to run.
// tests/apikey-tool.test.mjs checks that its key format and hash match api/apikey.mjs, and that
// NAMESPACE_ID matches wrangler.toml.
//
//   node tools/apikey.mjs new --label <label> [--ttl <seconds>]
//   node tools/apikey.mjs revoke <id> --label <label>
//   node tools/apikey.mjs list | get <id> | purge <id> | help
//
// Plain ASCII output, one command per line, so it pastes into Windows PowerShell 5.1.
import { createHash, randomBytes } from 'node:crypto';
import { writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative, isAbsolute } from 'node:path';

// The COLLEGEDASH_API_KEYS namespace (binding API_KEYS in wrangler.toml). Named by id, not by
// binding, so the commands work from any folder and before the binding is merged. Until the
// owner has created the namespace and its id is written here, every command but help refuses.
const NAMESPACE_ID = 'OWNER_POSTS_THE_COLLEGEDASH_API_KEYS_ID';
const WIN = process.platform === 'win32';
const NPX = WIN ? 'npx.cmd' : 'npx';   // PowerShell's execution policy blocks plain npx (npx.ps1)
const WHERE = `--namespace-id ${NAMESPACE_ID} --remote`;
const REMOTE = '(--remote because wrangler v4 otherwise uses a local copy on this computer: the command would seem to work and change nothing online.)';
const LABEL = /^[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}$/;
const ID = /^[0-9a-f]{12}$/;
const MIN_TTL = 60;                     // KV's minimum expiration TTL, in seconds
const here = relative(process.cwd(), process.argv[1]);
const SELF = `node "${here && !here.startsWith('..') && !isAbsolute(here) ? here : process.argv[1]}"`;

const kv = (verb, args) => `${NPX} wrangler kv key ${verb}${args ? ' ' + args : ''} ${WHERE}`;
const cmds = {
  put: (id, file, ttl) => kv('put', `"key:${id}" --path "${file}"`) + (ttl ? ` --ttl ${ttl}` : ''),
  list: () => kv('list') + ' --prefix key:',
  get: id => kv('get', `"key:${id}"`),
  purge: id => kv('delete', `"key:${id}"`),
  remove: file => (WIN ? `Remove-Item "${file}"` : `rm "${file}"`),
};

const USAGE = `Usage:
  ${SELF} new --label <label> [--ttl <seconds>]   issue a key (prints it once)
  ${SELF} revoke <id> --label <label>             stop a key (keeps a revoked record)
  ${SELF} list                                    print the command that lists key ids
  ${SELF} get <id>                                print the command that shows one record
  ${SELF} purge <id>                              print the command that deletes a record
  ${SELF} help                                    print this and every command

The label is 1-40 letters, digits, spaces or . _ - : use a project or agent name
(acme-agent, verifier-345), never a person's name or an email address.
--ttl makes KV delete the record after that many seconds (at least ${MIN_TTL}; 7 days is 604800).
Run this in a standalone PowerShell window, not a terminal an assistant can read.`;

const [cmd, ...rest] = process.argv.slice(2);
function opt(name) {
  const i = rest.indexOf('--' + name);
  if (i < 0) return undefined;
  const value = rest[i + 1];
  return value === undefined || value.startsWith('--') ? '' : value;
}
function fail(message) {
  console.error(`${message}\n\n${USAGE}`);
  process.exit(2);
}
function needNamespace() {
  if (!/^[0-9a-f]{32}$/.test(NAMESPACE_ID)) {
    fail('The COLLEGEDASH_API_KEYS namespace id is not in this file yet. Create the namespace in the dashboard\n' +
         '(Workers & Pages > KV), post its id on issue #345, and use the copy of this tool that carries it.');
  }
}
function needLabel() {
  const label = opt('label');
  if (label === undefined) fail('--label is required.');
  if (!LABEL.test(label)) fail('--label: 1-40 letters, digits, spaces or . _ - (a project or agent name, not a person).');
  return label;
}
function needId() {
  const id = rest[0];
  if (!ID.test(id || '')) fail('Give the key id: 12 characters 0-9 a-f (the part after cdash_live_).');
  return id;
}
const writeRecord = (name, record) => {
  const file = join(tmpdir(), name);
  writeFileSync(file, JSON.stringify(record));
  return file;
};
const say = lines => console.log(lines.join('\n'));

if (cmd === 'new') {
  const label = needLabel();
  const ttl = opt('ttl');
  if (ttl !== undefined && !(/^[1-9][0-9]*$/.test(ttl) && Number(ttl) >= MIN_TTL)) fail(`--ttl: whole seconds, at least ${MIN_TTL} (KV's minimum).`);
  needNamespace();
  // Same format and hash as api/apikey.mjs: cdash_live_<12 hex id>_<64 hex secret>, SHA-256 hex
  // of the whole key.
  const id = randomBytes(6).toString('hex');
  const key = `cdash_live_${id}_${randomBytes(32).toString('hex')}`;
  const hash = createHash('sha256').update(key).digest('hex');
  const file = writeRecord(`cdash-apikey-${id}.json`,
    { v: 1, hash, label, created: new Date().toISOString(), tier: 'standard', status: 'active' });
  say([
    `New API key "${label}", id ${id}.`,
    '',
    '1. Give this key to its holder privately, by email. Never in GitHub, a chat or a screenshot.',
    '   It is shown only this once:',
    '',
    `   ${key}`,
    '',
    '2. Store its record (the hash of the key, never the key) in COLLEGEDASH_API_KEYS:',
    '',
    `   ${cmds.put(id, file, ttl)}`,
    '',
    `   ${REMOTE}`,
    ...(ttl ? [`   KV deletes the record after ${ttl} seconds, and the key stops working then.`] : []),
    '',
    '3. Delete the record file (it holds only the hash):',
    '',
    `   ${cmds.remove(file)}`,
    '',
    'The key works about 2 minutes after step 2 (caches). To check the record:',
    '',
    `   ${cmds.get(id)}`,
    '',
    'To revoke it later:',
    '',
    `   ${SELF} revoke ${id} --label "${label}"`,
  ]);
} else if (cmd === 'revoke') {
  const id = needId();
  const label = needLabel();
  needNamespace();
  const file = writeRecord(`cdash-apikey-${id}-revoked.json`,
    { v: 1, label, status: 'revoked', revoked: new Date().toISOString() });
  say([
    `Revoke key ${id} ("${label}"). The record keeps the id, the label and the revoke time; the`,
    'hash is dropped, so the key stops working within about 2 minutes (caches).',
    '',
    '1. Overwrite its record:',
    '',
    `   ${cmds.put(id, file)}`,
    '',
    `   ${REMOTE}`,
    '',
    '2. Delete the record file:',
    '',
    `   ${cmds.remove(file)}`,
    '',
    'To delete the id entirely instead (purge; the counts can then no longer show that a revoked',
    'key is still being tried):',
    '',
    `   ${cmds.purge(id)}`,
  ]);
} else if (cmd === 'list') {
  needNamespace();
  say(['List the key ids (names and expiry only, never a key or a hash):', '', `   ${cmds.list()}`, '', `   ${REMOTE}`]);
} else if (cmd === 'get') {
  const id = needId();
  needNamespace();
  say([`Show the record of ${id} (label, created, status and the hash, never the key):`, '', `   ${cmds.get(id)}`, '', `   ${REMOTE}`]);
} else if (cmd === 'purge') {
  const id = needId();
  needNamespace();
  say([`Delete the record of ${id} entirely (revoke keeps a record instead):`, '', `   ${cmds.purge(id)}`, '', `   ${REMOTE}`]);
} else if (cmd === 'help' || cmd === '--help' || cmd === '-h') {
  say([USAGE, '', 'The wrangler commands (the new and revoke steps print the put with the real file):', '',
    `   new:     ${cmds.put('<id>', '<record file>', '<seconds, optional>')}`,
    `   list:    ${cmds.list()}`,
    `   get:     ${cmds.get('<id>')}`,
    `   revoke:  ${cmds.put('<id>', '<revoked record file>')}`,
    `   purge:   ${cmds.purge('<id>')}`,
    '', REMOTE]);
} else {
  fail(cmd ? `Unknown command "${cmd}".` : 'Give a command.');
}
