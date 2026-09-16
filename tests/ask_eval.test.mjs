// The /api/ask eval set (issue #165), run OFFLINE against recorded model responses.
//
//     node --test tests/ask_eval.test.mjs
//
// Every case in tests/fixtures/ask/eval.json goes through the deployed Worker's own fetch handler, switched
// on with a fake key. The global fetch is replaced so the Anthropic call never leaves the process: it
// returns the case's `recorded` model output in the Messages API response shape. What comes back must
// equal the case's expected filter state (or be {unsupported}).
//
// What this proves: the prompt/schema request is built, the model's JSON is parsed and validated, and
// the answer is exactly the filter state each question should produce - including units (30% -> 0.3),
// rank direction ("top 25" -> <= 25), conference aliases ("Big 10" -> "Big Ten") and unsupported questions.
// What it CANNOT prove: that the real model gives these answers. The recordings are hand-written (see the
// fixture's _comment) until tests/ask_eval_live.mjs --record is run with a key; that script is the live mode.
//
// ASK_EVAL_FIXTURE and ASK_WORKER (optional) point at other copies of the fixture or worker.js, so a
// deliberately wrong recording or a broken validator can be shown failing through these same checks.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..');
const FIXTURE = process.env.ASK_EVAL_FIXTURE || path.join(HERE, 'fixtures', 'ask', 'eval.json');
const WORKER = process.env.ASK_WORKER || path.join(ROOT, 'worker.js');
const worker = (await import(pathToFileURL(WORKER).href)).default;
const EVAL = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
const FAKE_KEY = 'test-key-not-a-secret';

function assetsEnv() {
  return {
    ASK_ENABLED: 'true', ANTHROPIC_API_KEY: FAKE_KEY,
    ASSETS: {
      fetch: async (req) => {
        const p = path.join(ROOT, 'public', decodeURIComponent(new URL(req.url).pathname));
        return fs.existsSync(p) ? new Response(fs.readFileSync(p), { status: 200, headers: { 'content-type': 'application/json' } })
          : new Response('not found', { status: 404 });
      },
    },
  };
}
// Replay one recorded model output as the Anthropic response, capturing what the Worker sent.
async function askWith(question, recorded, { stopReason = 'end_turn' } = {}) {
  const sent = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    sent.push({ url: String(url), init, body: JSON.parse(init.body) });
    return Response.json({ id: 'msg_recorded', type: 'message', role: 'assistant', model: worker.ask.MODEL, stop_reason: stopReason,
      content: [{ type: 'text', text: JSON.stringify(recorded) }], usage: { input_tokens: 0, output_tokens: 0 } });
  };
  try {
    const res = await worker.fetch(new Request('https://college.nextonetwo.com/api/ask', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ question }) }), assetsEnv());
    return { res, body: await res.json(), sent };
  } finally {
    globalThis.fetch = realFetch;
  }
}
// Order does not carry meaning in a pill list or a set of conditions.
const canon = (s) => ({ ...s, division: [...s.division].sort(), conf: [...s.conf].sort(), region: [...s.region].sort(),
  classYear: [...s.classYear].sort(), cond: s.cond.map((c) => JSON.stringify([c.field, c.op, c.value])).sort() });

test('the eval set is about 40 cases and covers units, rank direction, aliases and unsupported questions', () => {
  const cases = EVAL.cases;
  assert.ok(cases.length >= 38, `only ${cases.length} cases`);
  assert.equal(new Set(cases.map((c) => c.id)).size, cases.length, 'duplicate case ids');
  for (const tag of ['unit', 'rank-direction', 'alias', 'unsupported']) {
    assert.ok(cases.filter((c) => c.tags.includes(tag)).length >= 3, `fewer than 3 cases tagged ${tag}`);
  }
  // The Reviewer's case on #165: a percentage question must expect a stored fraction.
  const unit = cases.find((c) => c.id === 'unit-admit-30');
  assert.deepEqual(unit?.expected.cond, [{ field: 'admissionRate', op: '<', value: 0.3 }]);
  assert.equal(EVAL.model, worker.ask.MODEL, 'the fixture names a different model from the Worker');
});

for (const c of EVAL.cases) {
  test(`eval ${c.id}: ${c.question}`, async () => {
    const { res, body, sent } = await askWith(c.question, c.recorded);
    assert.equal(res.status, 200);
    assert.equal(sent.length, 1, 'expected exactly one upstream call');
    assert.equal(sent[0].body.messages[0].content, c.question, 'the question was not sent as the user message');
    if (c.expected.unsupported) {
      assert.equal(typeof body.unsupported, 'string', `expected unsupported, got ${JSON.stringify(body)}`);
      assert.deepEqual(Object.keys(body), ['unsupported']);
      return;
    }
    assert.equal(body.unsupported, undefined, `unexpected unsupported: ${body.unsupported}`);
    assert.deepEqual(Object.keys(body).sort(), ['classYear', 'cond', 'conf', 'division', 'reading', 'region', 'sort']);
    const { reading, ...state } = body;
    assert.deepEqual(canon(state), canon(c.expected), `filter state for "${c.question}"`);
    assert.ok(typeof reading === 'string' && reading.length > 0, 'no reading line');
  });
}
