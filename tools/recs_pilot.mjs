// The recommendations pilot link (issue #400, PR 8 part 1). Run by the owner, locally:
//
//     node tools/recs_pilot.mjs new   # make a new tester link; writes only its SHA-256 into public/index.html
//     node tools/recs_pilot.mjs off   # end the pilot: RECS_PILOT_SHA256 back to null, every link stops working
//
// `new` prints the tester link to this terminal and nowhere else: the token is never written to a file, a commit or
// the repository. Only its SHA-256 goes into the page (a one-line change to commit and merge). Making a new link
// revokes the old one. The token is 32 random bytes (256 bits), base64url, so the hash can't be reversed.
import { randomBytes, createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const PAGE = path.join(ROOT, 'public', 'index.html');
const SITE = 'https://college.nextonetwo.com/';
const LINE = /^const RECS_PILOT_SHA256 = (?:null|'[0-9a-f]{64}');$/m;

export const makeToken = () => randomBytes(32).toString('base64url');
export const sha256Hex = (text) => createHash('sha256').update(text, 'utf8').digest('hex');
/** The page with RECS_PILOT_SHA256 set to `hash` (64 hex) or null. Throws unless the line is there exactly once. */
export function setPilotHash(html, hash) {
  if (hash !== null && !/^[0-9a-f]{64}$/.test(hash)) throw new Error('not a SHA-256 hex digest');
  const found = html.match(new RegExp(LINE.source, 'gm')) || [];
  if (found.length !== 1) throw new Error(`expected one RECS_PILOT_SHA256 line in the page, found ${found.length}`);
  return html.replace(LINE, `const RECS_PILOT_SHA256 = ${hash === null ? 'null' : `'${hash}'`};`);
}
export const pilotLink = (token, site = SITE) => `${site}#pilot=${token}`;

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const cmd = process.argv[2];
  const html = readFileSync(PAGE, 'utf8');
  if (cmd === 'new') {
    const token = makeToken();
    writeFileSync(PAGE, setPilotHash(html, sha256Hex(token)));
    console.log('Wrote the new pilot hash into public/index.html. Commit and merge that one line; then send testers this link');
    console.log('(it is shown only here; anyone with it can open the pilot until you run "off" or make a new one):\n');
    console.log(`  ${pilotLink(token)}\n`);
  } else if (cmd === 'off') {
    writeFileSync(PAGE, setPilotHash(html, null));
    console.log('Pilot off: RECS_PILOT_SHA256 is null in public/index.html. Commit and merge that one line.');
  } else {
    console.log('usage: node tools/recs_pilot.mjs new | off');
    process.exit(2);
  }
}
