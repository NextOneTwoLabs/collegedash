// Issue #51: at 320-375 px "College Soccer" ran under the theme toggle (44 px of overlap at 320, 0 px of room at 375).
//
//     node --test tests/header_narrow.test.mjs
//
// Node has no layout engine, so this pins the CSS that fixes it: the page's <style> is parsed and the cascade for a
// handful of header selectors is resolved at a given viewport width (top-level rules and @media max-width/min-width
// blocks, in source order; the selectors compared are single classes, so source order decides). The widths the
// rules were chosen from were measured in a browser against local serve.py, in both themes (see PR #51's body):
// the label now clears the toggle by at least 14 px wherever it shows, and the page never scrolls sideways.
//
// What it CANNOT prove, and a human must check: the rendered gap on a real phone, and fonts that differ from the
// measuring browser's.
//
// HEADER_NARROW_TEST_HTML (optional) points at another copy of index.html, so the page from before this change can
// be run through these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HTML = process.env.HEADER_NARROW_TEST_HTML || path.join(HERE, '..', 'public', 'index.html');
const page = fs.readFileSync(HTML, 'utf8');
const css = (/<style>([\s\S]*?)<\/style>/.exec(page) || [])[1] || '';

// Top-level blocks of a stylesheet: [{ prelude, body }], comments removed, braces matched.
function blocks(text) {
  const src = text.replace(/\/\*[\s\S]*?\*\//g, '');
  const out = [];
  let i = 0;
  while (i < src.length) {
    const open = src.indexOf('{', i);
    if (open < 0) break;
    let depth = 1, j = open + 1;
    while (j < src.length && depth) { if (src[j] === '{') depth++; else if (src[j] === '}') depth--; j++; }
    out.push({ prelude: src.slice(i, open).trim(), body: src.slice(open + 1, j - 1) });
    i = j;
  }
  return out;
}
const mediaMatches = (prelude, width) => {
  if (!prelude.startsWith('@media')) return false;
  if (/\bprint\b/.test(prelude)) return false;
  const max = /max-width:\s*(\d+)px/.exec(prelude), min = /min-width:\s*(\d+)px/.exec(prelude);
  return (!max || width <= Number(max[1])) && (!min || width >= Number(min[1]));
};
// The declarations that apply to `selector` at `width`, later rules winning.
function resolve(selector, width) {
  const decl = {};
  const apply = rules => {
    for (const r of rules) {
      if (r.prelude.startsWith('@')) continue;
      if (!r.prelude.split(',').map(s => s.trim()).includes(selector)) continue;
      for (const d of r.body.split(';')) {
        const k = d.indexOf(':');
        if (k > 0) decl[d.slice(0, k).trim()] = d.slice(k + 1).trim();
      }
    }
  };
  for (const b of blocks(css)) {
    if (b.prelude.startsWith('@media')) { if (mediaMatches(b.prelude, width)) apply(blocks(b.body)); } else apply([b]);
  }
  return decl;
}

test('the header markup still carries the section label and divider (only CSS hides them)', () => {
  assert.match(page, /<div class="header-divider"><\/div>\s*<a class="section-label" href="https:\/\/college\.nextonetwo\.com\/">College Soccer<\/a>/);
});

test('below 360 px the divider and the "College Soccer" label are not drawn', () => {
  for (const w of [320, 340, 359]) {
    assert.equal(resolve('.section-label', w).display, 'none', `.section-label is drawn at ${w}px`);
    assert.equal(resolve('.header-divider', w).display, 'none', `.header-divider is drawn at ${w}px`);
  }
});

test('from 360 to 400 px the label shows, smaller, with the wordmark smaller and the left gaps tighter', () => {
  for (const w of [360, 375, 390, 400]) {
    assert.notEqual(resolve('.section-label', w).display, 'none', `.section-label hidden at ${w}px`);
    assert.equal(resolve('.section-label', w)['font-size'], '13px', `label size at ${w}px`);
    assert.equal(resolve('.wordmark', w)['font-size'], '18px', `wordmark size at ${w}px`);
    assert.equal(resolve('.header-left', w).gap, '6px', `left gap at ${w}px`);
  }
});

test('above 400 px the header is as it was', () => {
  for (const w of [401, 460, 768, 1280]) {
    assert.notEqual(resolve('.section-label', w).display, 'none');
    assert.equal(resolve('.section-label', w)['font-size'], '14px', `label size at ${w}px`);
    assert.equal(resolve('.wordmark', w)['font-size'], '21px', `wordmark size at ${w}px`);
  }
  assert.equal(resolve('.header-left', 1280).gap, '14px');
  assert.equal(resolve('.header-left', 460).gap, '8px');
});
