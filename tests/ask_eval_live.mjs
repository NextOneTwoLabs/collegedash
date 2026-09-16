// LIVE mode for the /api/ask eval set (issue #165). NOT run in CI, and never run by the tests: it calls the
// Anthropic Messages API and spends money. The offline harness is tests/ask_eval.test.mjs.
//
//     ANTHROPIC_API_KEY=... node tests/ask_eval_live.mjs --live            # score the real model, change nothing
//     ANTHROPIC_API_KEY=... node tests/ask_eval_live.mjs --live --record   # also overwrite `recorded` in the fixture
//
// It sends each question with exactly the request the Worker builds (worker.ask.buildAskRequest, the same
// system prompt, schema, model and output-token limit), validates the answer with the Worker's own
// validateAsk, and compares it with the case's expected state. Exit status 1 if any case differs.
// Cost: 42 requests of a ~4k-token prompt and a small JSON answer on Claude Haiku 4.5. Check the owner's
// budget decision on #165 before running it. The key is read from the environment and never written anywhere.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import worker from '../worker.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.join(HERE, 'fixtures', 'ask', 'eval.json');
const args = new Set(process.argv.slice(2));
if (!args.has('--live') || !process.env.ANTHROPIC_API_KEY) {
  console.error('Refusing to run: pass --live and set ANTHROPIC_API_KEY. This makes paid API calls.');
  process.exit(2);
}
const A = worker.ask;
const vocab = A.vocabFromIndex(JSON.parse(fs.readFileSync(path.join(HERE, '..', 'public', 'data', 'programs', 'index.json'), 'utf8')));
const doc = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
const canon = (s) => JSON.stringify({ ...s, division: [...s.division].sort(), conf: [...s.conf].sort(), region: [...s.region].sort(),
  classYear: [...s.classYear].sort(), cond: s.cond.map((c) => JSON.stringify([c.field, c.op, c.value])).sort() });
let failed = 0;
for (const c of doc.cases) {
  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-api-key': process.env.ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01' },
    body: JSON.stringify(A.buildAskRequest(c.question, vocab)),
  });
  if (!res.ok) { console.error(`${c.id}: HTTP ${res.status}`); failed++; continue; }
  const message = await res.json();
  const answer = A.answerFromMessage(message, vocab);
  const text = (message.content || []).filter((b) => b.type === 'text').map((b) => b.text).join('');
  let ok;
  if (c.expected.unsupported) ok = typeof answer.unsupported === 'string';
  else { const { reading, ...state } = answer; ok = !answer.unsupported && canon(state) === canon(c.expected); }
  if (!ok) failed++;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${c.id}: ${JSON.stringify(answer)}`);
  if (args.has('--record')) { try { c.recorded = JSON.parse(text); } catch { c.recorded = { unreadable: text }; } }
}
if (args.has('--record')) {
  doc.recordedBy = `live, ${A.MODEL}, ${new Date().toISOString()}`;
  fs.writeFileSync(FIXTURE, JSON.stringify(doc, null, 2) + '\n');
}
console.log(`${doc.cases.length - failed} of ${doc.cases.length} cases match`);
process.exit(failed ? 1 : 0);
