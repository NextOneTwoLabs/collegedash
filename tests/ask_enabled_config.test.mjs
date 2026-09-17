// The shipped switch-on values in wrangler.toml, checked against worker.js's own config checks (issue #165).
//
//     node --test tests/ask_enabled_config.test.mjs
//
// wrangler.toml is read as text and only the keys this depends on are parsed: [vars] ASK_ENABLED,
// ACCESS_TEAM_DOMAIN and ACCESS_AUD, and the [[kv_namespaces]] entry bound as ASK_BUDGET. Those values, plus a
// stand-in ANTHROPIC_API_KEY (the real key is a Worker secret and never in the repository), are handed to the
// Worker's own functions. No request leaves the process: the certs URL is answered by a stubbed fetch serving a
// locally generated key (tests/ask_access_helpers.mjs), and any other fetch fails the test.
//
// What this proves:
//   - askEnabled(env) is true for the shipped vars when the secret is present, and false without it;
//   - the shipped ACCESS_TEAM_DOMAIN passes accessTeam(), the allow-list that only fetches certs from an https
//     *.cloudflareaccess.com host, and normalises to itself - so it is exactly the issuer a real token carries;
//   - ACCESS_AUD is non-empty (a 64-hex Access audience tag) and the ASK_BUDGET binding is present, uncommented,
//     with a 32-hex namespace id;
//   - end to end, GET /api/ask/status answers 200 {ask: true} for a token with iss = the shipped team domain and
//     aud = the shipped AUD, and fetches certs from that team's own certs URL.
//
// ASK_WRANGLER (optional) points at another copy of wrangler.toml, so a broken copy can be shown failing here.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..');
const WRANGLER = process.env.ASK_WRANGLER || path.join(ROOT, 'wrangler.toml');
const worker = (await import(pathToFileURL(path.join(ROOT, 'worker.js')).href)).default;
const A = worker.ask;
const H = await import(pathToFileURL(path.join(HERE, 'ask_access_helpers.mjs')).href);
const STAND_IN_KEY = 'sk-test-0000-not-a-real-key';

/* ---------- wrangler.toml: only the keys this depends on ---------- */
function readConfig(text) {
  const lines = text.split(/\r?\n/);
  const vars = {};
  const kv = [];
  let table = null;
  let entry = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const header = line.match(/^(\[\[?)\s*([A-Za-z0-9_.]+)\s*\]\]?$/);
    if (header) {
      table = header[2];
      entry = null;
      if (header[1] === '[[' && table === 'kv_namespaces') kv.push((entry = {}));
      continue;
    }
    const pair = line.match(/^([A-Za-z0-9_]+)\s*=\s*"([^"]*)"\s*(#.*)?$/);
    if (!pair) continue;
    if (table === 'vars') vars[pair[1]] = pair[2];
    else if (table === 'kv_namespaces' && entry) entry[pair[1]] = pair[2];
  }
  return { vars, kv };
}

const CONFIG = readConfig(fs.readFileSync(WRANGLER, 'utf8'));
const shippedEnv = (extra = {}) => ({
  ASK_ENABLED: CONFIG.vars.ASK_ENABLED,
  ACCESS_TEAM_DOMAIN: CONFIG.vars.ACCESS_TEAM_DOMAIN,
  ACCESS_AUD: CONFIG.vars.ACCESS_AUD,
  ...extra,
});

test('askEnabled is true for the shipped [vars] when the ANTHROPIC_API_KEY secret is present, and false without it', () => {
  assert.equal(A.askEnabled(shippedEnv({ ANTHROPIC_API_KEY: STAND_IN_KEY })), true,
    `ASK_ENABLED in wrangler.toml is ${JSON.stringify(CONFIG.vars.ASK_ENABLED)}; ask would be switched off`);
  assert.equal(A.askEnabled(shippedEnv()), false, 'ask must still need the secret');
  assert.doesNotMatch(fs.readFileSync(WRANGLER, 'utf8'), /ANTHROPIC_API_KEY\s*=/, 'the key must be a secret, not a var');
});

test('ACCESS_TEAM_DOMAIN passes the Worker\'s *.cloudflareaccess.com certs allow-list and is already in its canonical form', () => {
  const raw = CONFIG.vars.ACCESS_TEAM_DOMAIN;
  const team = A.accessTeam(shippedEnv());
  assert.notEqual(team, null, `ACCESS_TEAM_DOMAIN ${JSON.stringify(raw)} is refused by accessTeam(): every ask request would be 403`);
  assert.match(team, /^https:\/\/[a-z0-9-]+\.cloudflareaccess\.com$/);
  // The token's iss is compared to the normalised form; the shipped value should need no normalising.
  assert.equal(raw, team, 'ACCESS_TEAM_DOMAIN should be written as https://<team>.cloudflareaccess.com, no trailing slash');
});

test('ACCESS_AUD is a non-empty audience tag, and the ASK_BUDGET namespace is bound with a real id', () => {
  const aud = CONFIG.vars.ACCESS_AUD;
  assert.equal(typeof aud, 'string', 'wrangler.toml [vars] has no ACCESS_AUD');
  assert.ok(aud.trim().length > 0, 'ACCESS_AUD is empty: every ask request would be 403');
  assert.match(aud, /^[0-9a-f]{64}$/, 'ACCESS_AUD does not look like an Access AUD tag (64 hex)');
  const budget = CONFIG.kv.filter((b) => b.binding === 'ASK_BUDGET');
  assert.equal(budget.length, 1, 'wrangler.toml needs exactly one uncommented [[kv_namespaces]] binding = "ASK_BUDGET"');
  assert.match(budget[0].id || '', /^[0-9a-f]{32}$/, 'the ASK_BUDGET binding needs its 32-hex namespace id');
  assert.notEqual(budget[0].id, CONFIG.kv.find((b) => b.binding === 'FEEDBACK')?.id, 'ASK_BUDGET must not share the feedback namespace');
});

test('end to end: GET /api/ask/status is 200 {ask: true} for a token issued by the shipped team for the shipped AUD', async () => {
  A.resetCache();
  const team = A.accessTeam(shippedEnv());
  assert.notEqual(team, null, 'ACCESS_TEAM_DOMAIN is refused, so no token can be accepted');
  const certsUrl = `${team}/cdn-cgi/access/certs`;
  const jwt = await H.token({ claims: { iss: team, aud: [CONFIG.vars.ACCESS_AUD] } });
  const fetched = [];
  const real = globalThis.fetch;
  globalThis.fetch = async (url) => {
    fetched.push(String(url));
    if (String(url) === certsUrl) return Response.json(H.CERTS);
    throw new Error(`unexpected fetch to ${url}`);
  };
  let res, body;
  try {
    const env = shippedEnv({ ANTHROPIC_API_KEY: STAND_IN_KEY, ASK_BUDGET: H.memoryKV(),
      ASSETS: { fetch: async () => new Response('Not found', { status: 404 }) } });
    res = await worker.fetch(new Request('https://college.nextonetwo.com/api/ask/status',
      { headers: { 'cf-access-jwt-assertion': jwt } }), env);
    body = await res.json().catch(() => null);
  } finally {
    globalThis.fetch = real;
  }
  assert.equal(res.status, 200, `status ${res.status}, body ${JSON.stringify(body)}`);
  assert.equal(body.ask, true);
  assert.equal(body.spend.capUsd, 10);
  assert.deepEqual(fetched, [certsUrl], 'certs must come from the shipped team\'s own certs URL and nothing else');
});
