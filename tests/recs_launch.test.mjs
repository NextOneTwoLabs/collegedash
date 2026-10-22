// "Find programs for me", the release (issue #400, PR 8 part 2): production switches recommendations on, and the About
// page explains how they work and what is kept, while the switch is on.
//
//     node --test tests/recs_launch.test.mjs
//
// The About-page card is cut out of public/index.html's renderFaq and checked as text, as tests/perf_page.test.mjs does
// for the speed card. Offline, under tests/netguard.
//
// What this proves:
//   - wrangler.toml sets RECS_ENABLED = "true", and still says how to roll back;
//   - the About page has a "Find programs for me" card, hidden unless the switch is on (S.recs.on), and switching on
//     unhides it (the About page can be drawn before api/status answers), so a rollback never leaves the page
//     describing a feature it doesn't show;
//   - the card states the approved method (four optional categories, Must have and Prefer, equal weights over a fixed
//     count, Need verification for unknowns, no match percentage, no admission, recruiting or cost prediction, and
//     no RPI, rankings, rosters or commitments in the ranking) and the approved privacy terms (D6: this browser only,
//     separate from Shortlist, Clear personalization, a shared device, nothing about choices sent, and the data
//     file's requests counted with every other data file's).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const HTML = fs.readFileSync(path.join(ROOT, 'public', 'index.html'), 'utf8').replace(/\r\n/g, '\n');
const fn = name => { const a = HTML.indexOf(`function ${name}(`); return a < 0 ? '' : HTML.slice(a, HTML.indexOf('\n}\n', a)); };

test('production switches recommendations on, and wrangler.toml still says how to roll back', () => {
  const toml = fs.readFileSync(path.join(ROOT, 'wrangler.toml'), 'utf8');
  assert.match(toml, /^RECS_ENABLED = "true"$/m, 'wrangler.toml switches recommendations on');
  assert.match(toml, /Rolling back is setting it back to "false"/, 'the rollback stays written beside the switch');
});

const card = () => /<div class="card" id="faqRecs"\$\{S\.recs\.on \? '' : ' hidden'\}><h3>How does “Find programs for me” work\?<\/h3>([\s\S]*?)<\/div>/.exec(fn('renderFaq'));

test('the About page has a "Find programs for me" card, hidden unless the switch is on', () => {
  assert.ok(card(), 'renderFaq draws the card, hidden while S.recs.on is false');
  // the About page can be drawn before api/status answers: switching on shows the card already on screen
  assert.match(fn('recsSwitchedOn'), /const faqRecs = \$\('#faqRecs'\); if \(faqRecs\) faqRecs\.hidden = false;/, 'switching on unhides the card');
});

test('the card states the approved method', () => {
  const c = card();
  assert.ok(c, 'the card exists');
  const text = c[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
  for (const phrase of [
    'region, division, school size and climate',
    'Must have',
    'Prefer',
    'counts the same',
    'Need verification',
    'no match percentage',
    'never predicts admission, recruiting or what you will pay',
    'RPI, rankings, rosters and commitments are not used',
    'climate is Prefer only',
    'more than 50 km',
  ]) assert.ok(text.includes(phrase), `the card says: ${phrase}`);
});

test('the card states the approved privacy terms (D6)', () => {
  const text = card()[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
  for (const phrase of [
    'saved only in this browser',
    'separate from your Shortlist',
    'Clear personalization',
    'Anyone using this device can see them',
    'Nothing about your choices is sent to our server',
    'counted with every other data file',
  ]) assert.ok(text.includes(phrase), `the card says: ${phrase}`);
});
