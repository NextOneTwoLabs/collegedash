// The recommendations pilot link (issue #400, PR 8 part 1). Run by the owner, locally:
//
//     node tools/recs_pilot.mjs new   # make a new tester link; writes only its SHA-256 into public/index.html
//     node tools/recs_pilot.mjs off   # end the pilot: RECS_PILOT_SHA256 back to null, every link stops working
//
// `new` prints the tester link to this terminal and nowhere else: the token is never written to a file, a commit or
// the repository. Only its SHA-256 goes into the page (a one-line change to commit and merge). Making a new link
// revokes the old one. The token is 32 random bytes (256 bits), base64url, so the hash can't be reversed.
// It makes a link only when its output is an interactive terminal (process.stdout.isTTY): run through a pipe, a log,
// CI or an assistant, which would keep the output, it changes nothing and says to run it in your own terminal.
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
export const WARNING = 'Don\u2019t paste this into chat, an issue or a PR, and don\u2019t run this through an assistant: its output is kept in the transcript.';
export const NOT_A_TERMINAL = 'Not an interactive terminal, so no link was made and public/index.html is unchanged. Run this in your own terminal to see the link.';

/** Runs `new` or `off` against the page text. `tty`: whether the output is an interactive terminal. Returns
 *  {html, lines, code}: the page to write (null: leave it), what to print, and the exit code. */
export function runPilot(cmd, html, { tty, token = makeToken() } = {}) {
  if (cmd === 'new') {
    if (!tty) return { html: null, lines: [NOT_A_TERMINAL], code: 1 };
    return { html: setPilotHash(html, sha256Hex(token)), code: 0, lines: [
      WARNING,
      'Wrote the new pilot hash into public/index.html. Commit and merge that one line; then send testers this link',
      '(it is shown only here; anyone with it can open the pilot until you run "off" or make a new one):', '',
      `  ${pilotLink(token)}`, '',
      WARNING] };
  }
  if (cmd === 'off') return { html: setPilotHash(html, null), lines: ['Pilot off: RECS_PILOT_SHA256 is null in public/index.html. Commit and merge that one line.'], code: 0 };
  return { html: null, lines: ['usage: node tools/recs_pilot.mjs new | off'], code: 2 };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const out = runPilot(process.argv[2], readFileSync(PAGE, 'utf8'), { tty: process.stdout.isTTY === true });
  if (out.html !== null) writeFileSync(PAGE, out.html);
  for (const line of out.lines) console.log(line);
  process.exitCode = out.code;
}
