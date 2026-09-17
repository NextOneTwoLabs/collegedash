// Shared by the /api/ask tests (issue #179): a stand-in Cloudflare Access team that signs real RS256 tokens,
// an in-memory KV namespace with failure switches, and a global-fetch stub that serves the team's certs and
// routes everything else to the test's own upstream reply. Not a test file: it registers no tests, so it is
// not a node:test suite and discovery does not run it. No network, no key, no real Access team.
export const TEAM = 'https://collegedash-test.cloudflareaccess.com';
export const AUD = 'aud-tag-for-the-ask-application';
export const CERTS_URL = `${TEAM}/cdn-cgi/access/certs`;

const enc = new TextEncoder();
const b64url = (bytes) => Buffer.from(bytes).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const b64urlJson = (obj) => b64url(enc.encode(JSON.stringify(obj)));

async function rsaPair() {
  return crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' },
    true, ['sign', 'verify']);
}

// The team's signing key (published in its certs) and an attacker's key (never published).
export const teamKeys = await rsaPair();
export const attackerKeys = await rsaPair();
export const KID = 'team-key-1';
const publicJwk = await crypto.subtle.exportKey('jwk', teamKeys.publicKey);
export const CERTS = { keys: [{ kid: KID, kty: 'RSA', alg: 'RS256', use: 'sig', n: publicJwk.n, e: publicJwk.e }] };

const nowS = () => Math.floor(Date.now() / 1000);

// A signed token. `claims` override the valid defaults; `header` overrides the JOSE header; `privateKey` signs.
export async function token({ claims = {}, header = {}, privateKey = teamKeys.privateKey } = {}) {
  const h = b64urlJson({ alg: 'RS256', kid: KID, typ: 'JWT', ...header });
  const c = b64urlJson({ aud: [AUD], iss: TEAM, email: 'owner@example.invalid', iat: nowS(), nbf: nowS(), exp: nowS() + 3600,
    type: 'app', sub: 'owner-identity', ...claims });
  const sig = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', privateKey, enc.encode(`${h}.${c}`));
  return `${h}.${c}.${b64url(new Uint8Array(sig))}`;
}

// An unsigned "alg: none" token, the oldest JWT forgery there is.
export function unsignedToken(claims = {}) {
  return `${b64urlJson({ alg: 'none', kid: KID, typ: 'JWT' })}.${b64urlJson({ aud: [AUD], iss: TEAM, exp: nowS() + 3600, ...claims })}.`;
}

// KV with the two methods the Worker uses. `fail` switches: getThrows, putThrows. `puts` records every write.
export function memoryKV(initial = {}) {
  const store = new Map(Object.entries(initial));
  const kv = {
    store, puts: [], fail: { getThrows: false, putThrows: false },
    async get(key) {
      if (kv.fail.getThrows) throw new Error('KV get failed (test)');
      return store.has(key) ? store.get(key) : null;
    },
    async put(key, value) {
      if (kv.fail.putThrows) throw new Error('KV put failed (test)');
      kv.puts.push([key, value]);
      store.set(key, String(value));
    },
  };
  return kv;
}

// The env an owner request needs: switched on, Access configured, a budget namespace.
export function accessVars(extra = {}) {
  return { ASK_ENABLED: 'true', ANTHROPIC_API_KEY: 'sk-test-0000-not-a-real-key', ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD, ...extra };
}

// Replace the global fetch: the certs URL answers CERTS (counted), anything else goes to `upstream`, which
// gets (url, init) and returns a Response; with no `upstream`, any other call throws.
export async function withFetch(upstream, fn) {
  const calls = { certs: 0, upstream: [] };
  const real = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    if (String(url) === CERTS_URL) {
      calls.certs += 1;
      return Response.json(CERTS);
    }
    calls.upstream.push({ url: String(url), init, body: init?.body ? JSON.parse(init.body) : null });
    if (!upstream) throw new Error(`unexpected upstream call to ${url}`);
    return upstream(url, init);
  };
  try {
    return { result: await fn(), calls };
  } finally {
    globalThis.fetch = real;
  }
}
