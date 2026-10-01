// The held-out review sheet (issue #400, PR 7) is what the code gives now: a change to the ranker or its words that
// alters what a reviewer reads can't land without regenerating docs/recs-heldout-review.md (and so re-reviewing it).
// Offline.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { sheet } from '../tools/recs_review_sheet.mjs';

test('docs/recs-heldout-review.md is current: node tools/recs_review_sheet.mjs regenerates it', () => {
  const committed = readFileSync(new URL('../docs/recs-heldout-review.md', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
  assert.equal(committed, sheet(), 'out of date: run node tools/recs_review_sheet.mjs and re-review');
});

test('the sheet covers every held-out scenario with a checklist, and names programs and schools only', () => {
  const scenarios = JSON.parse(readFileSync(new URL('./fixtures/recs/scenarios.json', import.meta.url), 'utf8')).scenarios;
  const reviewer = readFileSync(new URL('./fixtures/recs/heldout_reviewer.jsonl', import.meta.url), 'utf8').split(/\r?\n/).filter(Boolean)
    .map((l) => JSON.parse(l).id);
  const held = [...scenarios.filter((s) => s.split === 'heldout').map((s) => s.id), ...reviewer];
  assert.equal(held.length, 14, `held-out scenarios: ${held.length}`);
  assert.match(sheet(), /\*\*Who wrote the held-out cases\.\*\* H01-H08: the ranker's author[^]*HU1-HU6: a Reviewer \(Huatuo\)/);
  assert.equal((sheet().match(/- \*\*Written by:\*\* a Reviewer \(Huatuo\)/g) || []).length, reviewer.length);
  const text = sheet();
  for (const id of held) assert.ok(text.includes(`\n## ${id}\n`), id);
  assert.equal((text.match(/- \[ \] Reasons true and sourced/g) || []).length, held.length);
  assert.doesNotMatch(text, /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/, 'an email address');
});
