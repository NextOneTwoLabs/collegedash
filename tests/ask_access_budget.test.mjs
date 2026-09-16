// Owner-only access and the $10 monthly budget for /api/ask (issue #179).
//
//     node --test tests/ask_access_budget.test.mjs
//
// Everything runs in process against worker.js's own fetch handler. The Cloudflare Access team is a stand-in
// (tests/ask_access_helpers.mjs): a locally generated RSA key signs real RS256 tokens and a stubbed fetch serves
// its public key at the team's certs URL. The budget namespace is an in-memory KV with failure switches. The
// Anthropic API is a stubbed fetch too; a test that must not call it fails if it does. No key, no network.
//
// What this proves:
//   - access: GET /api/ask/status and POST /api/ask answer only a request whose Cf-Access-Jwt-Assertion header
//     is a valid token for this application. Missing, "alg: none", signed by another key, edited after signing,
//     wrong audience, wrong issuer, expired and not-yet-valid tokens are all 403, before any upstream call or
//     budget write; a token in the CF_Authorization cookie alone is not accepted; an Access configuration that is
//     missing, or names a team domain outside cloudflareaccess.com, refuses and fetches no certs from it;
//   - the owner's GET /api/ask/status reports ask and this month's spend; off, the path is the usual 404;
//   - budget boundary: a request whose worst case lands exactly on $10 is allowed; one micro-dollar more is 429
//     with no upstream call;
//   - month rollover: a month at its cap refuses up to 23:59:59.999 UTC on its last day and the next month starts
//     at zero, in its own key, leaving the old month's counter as it was;
//   - fail closed: a missing binding, a KV read or write that throws, and a corrupt counter each refuse (503)
//     with no upstream call;
//   - recording: the actual cost from usage replaces the reservation; unreadable usage and a lost connection keep
//     the worst case; an upstream error response is released; a KV failure after the call keeps the worst case;
//   - the prices and the cap are the named constants the issue asks for.
//
// ASK_WORKER (optional) points at another copy of worker.js, so a deliberately broken copy can be shown failing
// through these same checks.
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..');
const WORKER = process.env.ASK_WORKER || path.join(ROOT, 'worker.js');
const worker = (await import(pathToFileURL(WORKER).href)).default;
const A = worker.ask;
const H = await import(pathToFileURL(path.join(HERE, 'ask_access_helpers.mjs')).href);
const INDEX = JSON.parse(fs.readFileSync(path.join(ROOT, 'public', 'data', 'programs', 'index.json'), 'utf8'));
const CAP = 10_000_000;
const QUESTION = 'ACC schools with admission under 30%';

function env(extra = {}) {
  return {
    ...H.accessVars(),
    ASK_BUDGET: H.memoryKV(),
    ASSETS: {
      fetch: async (req) => (new URL(req.url).pathname === '/data/programs/index.json'
        ? Response.json(INDEX) : new Response('Not found', { status: 404 })),
    },
    ...extra,
  };
}
const url = (p) => `https://college.nextonetwo.com${p}`;
const statusReq = (headers = {}) => new Request(url('/api/ask/status'), { headers });
const askReq = (headers = {}) => new Request(url('/api/ask'), { method: 'POST', headers: { 'content-type': 'application/json', ...headers },
  body: JSON.stringify({ question: QUESTION }) });
const bearer = (jwt) => ({ 'cf-access-jwt-assertion': jwt });
const answer = (usage) => () => Response.json({ type: 'message', stop_reason: 'end_turn',
  content: [{ type: 'text', text: JSON.stringify({ unsupported: null, reading: 'r', division: [], conf: ['ACC'], region: [], classYear: [], cond: [], sort: null }) }],
  ...(usage === undefined ? {} : { usage }) });

// The worst case the Worker reserves for QUESTION, computed the way the Worker computes it.
const WORST = A.worstCaseMicroUsd(JSON.stringify(A.buildAskRequest(QUESTION, A.vocabFromIndex(INDEX))));

// Pin the clock (Date only; timers stay real). Tokens are signed after this, against the pinned time.
function at(iso) {
  mock.timers.enable({ apis: ['Date'], now: Date.parse(iso) });
  A.resetCache();
}
const release = () => { mock.timers.reset(); A.resetCache(); };

// ---------- access ----------

test('access: the owner\'s valid token gets GET /api/ask/status with ask and this month\'s spend', async () => {
  at('2026-09-16T12:00:00.000Z');
  try {
    const e = env();
    e.ASK_BUDGET.store.set('ask-spend:2026-09', '1234567');
    const jwt = await H.token();
    const { result, calls } = await H.withFetch(null, async () => {
      const res = await worker.fetch(statusReq(bearer(jwt)), e);
      return { status: res.status, body: await res.json(), cache: res.headers.get('cache-control') };
    });
    assert.equal(result.status, 200);
    assert.deepEqual(result.body, { ask: true, spend: { month: '2026-09', usd: 1.2346, capUsd: 10 } });
    assert.equal(result.cache, 'no-store');
    assert.equal(calls.certs, 1, 'the team certs were not consulted');
    assert.deepEqual(calls.upstream, []);
  } finally {
    release();
  }
});

const BAD_TOKENS = {
  'no header at all': async () => null,
  'an empty header': async () => '',
  'not a JWT': async () => 'owner',
  '"alg: none", unsigned': async () => H.unsignedToken(),
  'signed by another key under the team\'s kid (forged)': async () => H.token({ privateKey: H.attackerKeys.privateKey }),
  'a valid token with its claims edited after signing': async () => {
    const [h, , sig] = (await H.token()).split('.');
    const other = (await H.token({ claims: { email: 'someone-else@example.invalid' } })).split('.')[1];
    return `${h}.${other}.${sig}`;
  },
  'an HS256 header': async () => H.token({ header: { alg: 'HS256' } }),
  'a kid the team does not publish': async () => H.token({ header: { kid: 'not-a-team-key' } }),
  'the wrong audience (another Access application)': async () => H.token({ claims: { aud: ['aud-tag-of-another-app'] } }),
  'no audience': async () => H.token({ claims: { aud: undefined } }),
  'the wrong issuer (another team)': async () => H.token({ claims: { iss: 'https://another-team.cloudflareaccess.com' } }),
  'expired one second ago': async () => H.token({ claims: { exp: Math.floor(Date.now() / 1000) - 1 } }),
  'expiring this very second': async () => H.token({ claims: { exp: Math.floor(Date.now() / 1000) } }),
  'no expiry': async () => H.token({ claims: { exp: undefined } }),
  'not valid for another ten minutes (nbf)': async () => H.token({ claims: { nbf: Math.floor(Date.now() / 1000) + 600 } }),
};
test('access: every token short of valid is 403 on both routes, before any upstream call or budget write', async () => {
  at('2026-09-16T12:00:00.000Z');
  try {
    for (const [name, make] of Object.entries(BAD_TOKENS)) {
      const jwt = await make();
      const headers = jwt === null ? {} : bearer(jwt);
      const e = env();
      const { result, calls } = await H.withFetch(answer({ input_tokens: 1, output_tokens: 1 }), async () => {
        const s = await worker.fetch(statusReq(headers), e);
        const a = await worker.fetch(askReq(headers), e);
        return { s: s.status, sBody: await s.text(), a: a.status };
      });
      assert.equal(result.s, 403, `${name}: /api/ask/status answered ${result.s}`);
      assert.ok(!result.sBody.includes('spend') && !result.sBody.includes('"ask"'), `${name}: status leaked ${result.sBody}`);
      assert.equal(result.a, 403, `${name}: /api/ask answered ${result.a}`);
      assert.equal(calls.upstream.length, 0, `${name}: called the API`);
      assert.deepEqual(e.ASK_BUDGET.puts, [], `${name}: wrote the budget`);
    }
  } finally {
    release();
  }
});

test('access: the token is read from the header only - a CF_Authorization cookie alone is refused', async () => {
  const jwt = await H.token();
  const { result } = await H.withFetch(null, async () => (await worker.fetch(statusReq({ cookie: `CF_Authorization=${jwt}` }), env())).status);
  assert.equal(result, 403);
});

test('access: missing or foreign Access configuration refuses, and fetches no certs from a foreign host', async () => {
  const jwt = await H.token();
  const configs = {
    'ACCESS_AUD missing': { ACCESS_AUD: undefined }, 'ACCESS_AUD empty': { ACCESS_AUD: '' },
    'ACCESS_TEAM_DOMAIN missing': { ACCESS_TEAM_DOMAIN: undefined }, 'ACCESS_TEAM_DOMAIN empty': { ACCESS_TEAM_DOMAIN: '' },
    'a team domain outside cloudflareaccess.com': { ACCESS_TEAM_DOMAIN: 'https://evil.example.com' },
    'a lookalike host': { ACCESS_TEAM_DOMAIN: 'https://collegedash-test.cloudflareaccess.com.evil.example' },
    'plain http': { ACCESS_TEAM_DOMAIN: 'http://collegedash-test.cloudflareaccess.com' },
  };
  for (const [name, vars] of Object.entries(configs)) {
    A.resetCache();
    const fetched = [];
    const real = globalThis.fetch;
    globalThis.fetch = async (u) => { fetched.push(String(u)); return Response.json(H.CERTS); };
    try {
      const res = await worker.fetch(statusReq(bearer(jwt)), env(vars));
      assert.equal(res.status, 403, name);
      assert.deepEqual(fetched, [], `${name}: fetched ${fetched.join(', ')}`);
    } finally {
      globalThis.fetch = real;
    }
  }
  // the bare team name form is accepted and normalised
  assert.equal(A.accessTeam({ ACCESS_TEAM_DOMAIN: 'collegedash-test.cloudflareaccess.com' }), H.TEAM);
});

test('access: switched off, /api/ask/status is the same 404 as any unknown /api path', async () => {
  const jwt = await H.token();
  for (const vars of [{ ASK_ENABLED: 'false' }, { ANTHROPIC_API_KEY: '' }]) {
    const { result, calls } = await H.withFetch(null, async () => {
      const res = await worker.fetch(statusReq(bearer(jwt)), env(vars));
      return res.status;
    });
    assert.equal(result, 404);
    assert.equal(calls.certs, 0);
  }
});

// ---------- access: the three bypasses Reviewer 2 found no test for on #191 ----------

test('access: a key cached for one team is never used to verify a token for another team', async () => {
  // Team A's certs fill the isolate's cache. Team B is configured next, and a token claims team B while being
  // signed with team A's key under the same kid. Only team B's own certs may decide it, and they do not carry
  // that key, so it must be refused - and team B's certs must actually be fetched.
  const TEAM_B = 'https://another-team.cloudflareaccess.com';
  const certsB = { keys: [{ ...(await crypto.subtle.exportKey('jwk', H.attackerKeys.publicKey)), kid: 'team-b-key', alg: 'RS256', use: 'sig' }] };
  const fetched = [];
  const real = globalThis.fetch;
  globalThis.fetch = async (u) => {
    fetched.push(String(u));
    if (String(u) === H.CERTS_URL) return Response.json(H.CERTS);
    if (String(u) === `${TEAM_B}/cdn-cgi/access/certs`) return Response.json(certsB);
    throw new Error(`unexpected fetch ${u}`);
  };
  A.resetCache();
  try {
    const legit = await worker.fetch(statusReq(bearer(await H.token())), env());
    assert.equal(legit.status, 200, 'the legitimate team A call did not fill the cache');
    const crossTeam = await H.token({ claims: { iss: TEAM_B } }); // team A's key, team A's kid, team B's issuer
    const res = await worker.fetch(statusReq(bearer(crossTeam)), env({ ACCESS_TEAM_DOMAIN: TEAM_B }));
    assert.equal(res.status, 403, 'a team A key from the cache verified a token for team B');
    assert.deepEqual(fetched, [H.CERTS_URL, `${TEAM_B}/cdn-cgi/access/certs`], 'team B\'s certs were not fetched');
  } finally {
    globalThis.fetch = real;
    A.resetCache();
  }
});

test('access: an empty ACCESS_AUD is refused even for a token whose aud is empty too, touching neither certs nor the model', async () => {
  for (const [name, aud] of [['aud: [""]', ['']], ['aud: ""', '']]) {
    A.resetCache();
    const jwt = await H.token({ claims: { aud } });
    const e = env({ ACCESS_AUD: '' });
    const { result, calls } = await H.withFetch(answer({ input_tokens: 1, output_tokens: 1 }), async () => {
      const s = await worker.fetch(statusReq(bearer(jwt)), e);
      const a = await worker.fetch(askReq(bearer(jwt)), e);
      return { s: s.status, a: a.status };
    });
    assert.equal(result.s, 403, `${name}: /api/ask/status answered ${result.s}`);
    assert.equal(result.a, 403, `${name}: /api/ask answered ${result.a}`);
    assert.equal(calls.certs, 0, `${name}: fetched the certs`);
    assert.equal(calls.upstream.length, 0, `${name}: called the model`);
    assert.deepEqual(e.ASK_BUDGET.puts, [], `${name}: wrote the budget`);
  }
});

test('access is checked before the method: an unauthenticated GET /api/ask is 403 with no allow header, not 405', async () => {
  for (const [name, headers] of [['no token', {}], ['a forged token', bearer(await H.token({ privateKey: H.attackerKeys.privateKey }))]]) {
    A.resetCache();
    const { result, calls } = await H.withFetch(null, async () => {
      const res = await worker.fetch(new Request(url('/api/ask'), { headers }), env());
      return { status: res.status, allow: res.headers.get('allow'), body: await res.text() };
    });
    assert.equal(result.status, 403, `${name}: answered ${result.status}, which tells a stranger the route exists and what it accepts`);
    assert.equal(result.allow, null, `${name}: sent an allow header`);
    assert.equal(calls.upstream.length, 0);
  }
  // and the owner's own GET is the 405
  const { result } = await H.withFetch(null, async () => {
    const res = await worker.fetch(new Request(url('/api/ask'), { headers: bearer(await H.token()) }), env());
    return { status: res.status, allow: res.headers.get('allow') };
  });
  assert.deepEqual(result, { status: 405, allow: 'POST' });
});

// ---------- budget ----------

async function askAt(e, { jwt, upstream = answer({ input_tokens: 1000, output_tokens: 100 }) } = {}) {
  const { result, calls } = await H.withFetch(upstream, async () => {
    const res = await worker.fetch(askReq(bearer(jwt || await H.token())), e);
    return { status: res.status, body: await res.json() };
  });
  return { ...result, upstreamCalls: calls.upstream.length };
}

test('budget: the worst case is priced from the request body and max_tokens', () => {
  const body = JSON.stringify(A.buildAskRequest(QUESTION, A.vocabFromIndex(INDEX)));
  const expected = Math.ceil((Buffer.byteLength(body, 'utf8') + A.WORST_CASE_EXTRA_INPUT_TOKENS) * 1 + A.MAX_OUTPUT_TOKENS * 5);
  assert.equal(WORST, expected);
  assert.ok(WORST > 0 && WORST < 100_000, `worst case ${WORST} µ$ is implausible`);
});

test('budget boundary: a worst case landing exactly on $10 is allowed; one micro-dollar more is refused with no call', async () => {
  at('2026-09-16T12:00:00.000Z');
  try {
    const exact = env();
    exact.ASK_BUDGET.store.set('ask-spend:2026-09', String(CAP - WORST));
    const ok = await askAt(exact);
    assert.equal(ok.status, 200, JSON.stringify(ok.body));
    assert.equal(ok.upstreamCalls, 1);
    // the reservation took it to exactly the cap, and the actual cost (1000 in, 100 out = 1,500 µ$) replaced it
    assert.deepEqual(exact.ASK_BUDGET.puts.map(([, v]) => Number(v)), [CAP, CAP - WORST + 1500]);

    const over = env();
    over.ASK_BUDGET.store.set('ask-spend:2026-09', String(CAP - WORST + 1));
    const refused = await askAt(over);
    assert.equal(refused.status, 429);
    assert.match(refused.body.error, /\$10 budget for 2026-09/);
    assert.equal(refused.upstreamCalls, 0, 'called the API over the cap');
    assert.deepEqual(over.ASK_BUDGET.puts, [], 'wrote the counter while refusing');
  } finally {
    release();
  }
});

test('month rollover: a month at its cap refuses to its last UTC millisecond; the next month starts at zero in its own key', async () => {
  const kv = H.memoryKV({ 'ask-spend:2026-09': String(CAP) });
  at('2026-09-30T23:59:59.999Z');
  try {
    const last = await askAt(env({ ASK_BUDGET: kv }));
    assert.equal(last.status, 429, 'the full month was not refused on its last millisecond');
    assert.equal(last.upstreamCalls, 0);
  } finally {
    release();
  }
  at('2026-10-01T00:00:00.000Z');
  try {
    const first = await askAt(env({ ASK_BUDGET: kv }));
    assert.equal(first.status, 200, `the new month was refused: ${JSON.stringify(first.body)}`);
    assert.equal(first.upstreamCalls, 1);
    assert.equal(kv.store.get('ask-spend:2026-10'), '1500');
    assert.equal(kv.store.get('ask-spend:2026-09'), String(CAP), 'the old month\'s counter changed');
  } finally {
    release();
  }
});

test('fail closed: no binding, a failing read, a failing write or a corrupt counter refuses with no call', async () => {
  at('2026-09-16T12:00:00.000Z');
  try {
    const cases = {
      'no ASK_BUDGET binding': () => env({ ASK_BUDGET: undefined }),
      'KV get throws': () => { const e = env(); e.ASK_BUDGET.fail.getThrows = true; return e; },
      'KV put throws': () => { const e = env(); e.ASK_BUDGET.fail.putThrows = true; return e; },
      'a corrupt counter': () => { const e = env(); e.ASK_BUDGET.store.set('ask-spend:2026-09', 'lots'); return e; },
      'a negative counter': () => { const e = env(); e.ASK_BUDGET.store.set('ask-spend:2026-09', '-5'); return e; },
      'a fractional counter': () => { const e = env(); e.ASK_BUDGET.store.set('ask-spend:2026-09', '12.5'); return e; },
    };
    for (const [name, make] of Object.entries(cases)) {
      const res = await askAt(make());
      assert.equal(res.status, 503, `${name}: ${res.status} ${JSON.stringify(res.body)}`);
      assert.equal(res.upstreamCalls, 0, `${name}: called the API`);
    }
    // and the owner's status says the spend is unknown rather than zero
    const e = env();
    e.ASK_BUDGET.fail.getThrows = true;
    const jwt = await H.token();
    const { result } = await H.withFetch(null, async () => (await worker.fetch(statusReq(bearer(jwt)), e)).json());
    assert.deepEqual(result, { ask: true, spend: null });
  } finally {
    release();
  }
});

test('recording: actual cost replaces the reservation; unknowns keep the worst case; an upstream error is released', async () => {
  at('2026-09-16T12:00:00.000Z');
  try {
    const run = async (upstream, prepare = () => { }) => {
      const e = env();
      e.ASK_BUDGET.store.set('ask-spend:2026-09', '100');
      prepare(e);
      const res = await askAt(e, { upstream });
      return { res, counter: Number(e.ASK_BUDGET.store.get('ask-spend:2026-09')) };
    };
    let r = await run(answer({ input_tokens: 1200, output_tokens: 150 }));
    assert.equal(r.counter, 100 + 1200 * 1 + 150 * 5, 'input $1/MTok, output $5/MTok');
    r = await run(answer({ input_tokens: 10, output_tokens: 10, cache_creation_input_tokens: 1000, cache_read_input_tokens: 1000 }));
    assert.equal(r.counter, 100 + 10 + 50 + 2000 + 100, 'cache writes at 2x, reads at 0.1x');
    r = await run(answer(undefined));
    assert.equal(r.counter, 100 + WORST, 'missing usage must keep the worst case');
    r = await run(answer({ input_tokens: 'many', output_tokens: 1 }));
    assert.equal(r.counter, 100 + WORST, 'unreadable usage must keep the worst case');
    r = await run(() => { throw new TypeError('connection reset'); });
    assert.equal(r.res.status, 502);
    assert.equal(r.counter, 100 + WORST, 'a lost connection may have been billed: keep the worst case');
    r = await run(() => new Response('{"error":{}}', { status: 500 }));
    assert.equal(r.res.status, 502);
    assert.equal(r.counter, 100, 'an error response is not billed: release the reservation');
    r = await run(answer({ input_tokens: 1200, output_tokens: 150 }), (e) => {
      const put = e.ASK_BUDGET.put.bind(e.ASK_BUDGET);
      let n = 0;
      e.ASK_BUDGET.put = async (k, v) => { n += 1; if (n > 1) throw new Error('KV put failed after the call (test)'); return put(k, v); };
    });
    assert.equal(r.res.status, 200, 'the answer is still returned');
    assert.equal(r.counter, 100 + WORST, 'a failed settle must leave the reservation, over-counting');
  } finally {
    release();
  }
});

test('the prices and the cap are the named constants for Claude Haiku 4.5', () => {
  assert.equal(A.MODEL, 'claude-haiku-4-5-20251001');
  assert.deepEqual(A.PRICES_USD_PER_MTOK, { input: 1, output: 5, cacheWrite: 2, cacheRead: 0.1 });
  assert.equal(A.BUDGET_CAP_USD, 10);
  assert.equal(A.BUDGET_CAP_MICRO_USD, CAP);
  assert.equal(A.budgetMonth(new Date('2026-12-31T23:59:59.999Z')), '2026-12');
  assert.equal(A.budgetMonth(new Date('2027-01-01T00:00:00.000Z')), '2027-01');
  const src = fs.readFileSync(WORKER, 'utf8');
  assert.match(src, /platform\.claude\.com\/docs\/en\/pricing/, 'the price constants lost their source comment');
});
