// #345 phase 2: the #/api page, docs/data-api.md and wrangler.toml say the same thing. Direct use needs a key; the
// limits quoted are the ones bound; the page's status table is ECNL's (no 403); the owner steps name the key store,
// the tool's --namespace-id/--remote commands and the test key's file route (a file outside every repository, read
// into a variable, deleted afterwards; never an environment variable set before the session, which a subagent in a
// running session never sees).
//
//     node --test tests/api_docs_agree.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const TOML = readFileSync('wrangler.toml', 'utf8').replace(/\r\n/g, '\n');
const DOCS = readFileSync('docs/data-api.md', 'utf8').replace(/\r\n/g, '\n');
const HTML = readFileSync('public/index.html', 'utf8').replace(/\r\n/g, '\n');
const PAGE = (() => {
  const start = HTML.indexOf('async function renderApiDocs()');
  assert.ok(start > 0, 'renderApiDocs is in public/index.html');
  return HTML.slice(start, HTML.indexOf('\n}\n', start));
})();
// name -> limit per 60 s, for the limiters wrangler.toml binds (the rollback PR may remove RL_SESSION and RL_ANON)
const LIMITS = Object.fromEntries([...TOML.matchAll(/\[\[ratelimits\]\]\nname = "(RL_[A-Z]+)"[^\n]*\nnamespace_id = "\d+"\nsimple = \{ limit = (\d+), period = 60 \}/g)]
  .map(m => [m[1], Number(m[2])]));
const n = x => x.toLocaleString('en-US');

test('wrangler.toml binds RL_KEY and RL_IP (the doors the docs describe)', () => {
  assert.equal(LIMITS.RL_KEY, 60);
  assert.ok(LIMITS.RL_IP > 0);
});

test('docs: direct use needs a key; never described as a public, keyless API; the anchor the answers link to', () => {
  assert.match(DOCS, /\*\*Direct use of the API needs a key\.\*\*/);
  assert.match(DOCS, /^## API keys$/m);
  assert.doesNotMatch(DOCS, /public API|no key (is )?needed|without a key is fine|light use without a key/i);
  assert.doesNotMatch(DOCS, /Keys arrive in\s+phase 2|until phase 2/i, 'no phase-1 placeholders left');
  assert.doesNotMatch(DOCS, /Monday to Wednesday/, 'the merge window was dropped by the owner');
});

test('docs: every limit quoted matches wrangler.toml, and the approximate counting is said plainly', () => {
  for (const [name, limit] of Object.entries(LIMITS)) {
    assert.match(DOCS, new RegExp('\\| `' + name + '` \\| [^|]+ \\| ' + n(limit) + ' per 60 s'), name + ' in the limits table');
  }
  assert.match(DOCS, new RegExp('\\*\\*Limits\\.\\*\\* ' + LIMITS.RL_KEY + ' requests per 60 s per key \\(`RL_KEY`\\)'));
  assert.match(DOCS, new RegExp('\\(`RL_IP`, ' + n(LIMITS.RL_IP) + ' per 60 s\\)'));
  assert.match(DOCS, /\*\*The counters are approximate\.\*\*/);
});

test('docs: the owner steps name the key store, the tool commands and the test key file route', () => {
  assert.match(DOCS, /KV namespace `COLLEGE_API_KEYS`/);
  assert.match(DOCS, /--namespace-id <COLLEGE_API_KEYS id> --remote/);
  assert.match(DOCS, /never `--binding`/);
  assert.match(DOCS, /node tools\\apikey\.mjs new --label "verifier-345" --ttl 604800/);
  // the test key travels in a file outside every repository, in a standalone window; read into a variable, never printed
  assert.doesNotMatch(DOCS, /COLLEGEDASH_TEST_KEY/, 'no environment-variable route: a subagent in a running session never sees it');
  assert.match(DOCS, /writes it to a file outside every repository and worktree/);
  assert.match(DOCS, /\*\*standalone\*\* PowerShell window/);
  assert.match(DOCS, /Set-Content -NoNewline -Path "\$env:USERPROFILE\\\.collegedash\\test-key\.txt" -Value '<key>'/);
  assert.match(DOCS, /\$k = \(Get-Content -Raw "\$env:USERPROFILE\\\.collegedash\\test-key\.txt"\)\.Trim\(\)/);
  assert.match(DOCS, /-H "Authorization: Bearer \$k"/, 'the command text holds the variable, not the key');
  assert.match(DOCS, /never `-i` on a keyed request/);
  assert.match(DOCS, /\*\*deletes the file\*\*/);
  assert.match(DOCS, /appears in any output, it is treated as\s+exposed/);
  assert.match(DOCS, /never the feedback store/);
});

test('page #/api: key required for direct use, the limits bound, a link to #api-keys, and ECNL\'s status table', () => {
  assert.match(PAGE, /<b>Direct use needs an API key<\/b>/);
  assert.match(PAGE, new RegExp('<b>' + LIMITS.RL_KEY + ' a minute per key</b>'));
  if (LIMITS.RL_ANON) assert.match(PAGE, new RegExp(LIMITS.RL_ANON + ' a minute per internet address without a key'));
  assert.match(PAGE, /\$\{esc\(docs\)\}#api-keys/);
  assert.match(PAGE, /approximate/);
  const codes = [...PAGE.matchAll(/^\s*\['([0-9 /]+)', '/gm)].map(m => m[1]);
  assert.deepEqual(codes, ['200 / 304', '400', '401', '429', '503'], 'no 403: every bad key is 401');
  assert.doesNotMatch(PAGE, /Light use without a key is fine/);
});
