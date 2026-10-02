// Tests for the division-tint fallback for programs with no team colours (issue #276 part C).
//
//     node --test tests/division_colour_fallback.test.mjs
//
// The team-colour helpers are cut out of the real public/index.html (from the "team colours" marker to
// swatchesHtml) and run in a `vm`, so what is tested is the shipped source, not a copy. The tint tokens
// are read from the real theme blocks in the same file.
//
// What this proves:
//   - a program WITH colours renders exactly the pinned markup (since #465 E: a small crest, its colours as CSS
//     variables on the card's band, and the swatches);
//   - a program with no colours renders its own division's tint in the crest and swatches;
//   - a program with no colours and an unknown or missing division keeps the old grey placeholder;
//   - each tint is defined in both themes and body text on it clears WCAG AA (4.5:1) in both.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const html = readFileSync(new URL('../public/index.html', import.meta.url), 'utf8');
const escLine = html.match(/^const esc = .*$/m)[0];
const start = html.indexOf('/* ---------- team colours ---------- */');
const end = html.indexOf('\n', html.indexOf('const swatchesHtml'));
assert.ok(start > 0 && end > start, 'team-colour block found in index.html');
const ctx = vm.createContext({});
vm.runInContext(`${escLine}\n${html.slice(start, end)}\nthis.api = { teamColors, crestVars, swatchesHtml };`, ctx);
const { teamColors, crestVars, swatchesHtml } = ctx.api;
// #465 E: the card shows the colours as a small crest (CSS variables on the band) rather than a coloured band and stripe.
const render = p => { const tc = teamColors(p); return [crestVars(tc), swatchesHtml(p)]; };

test('a program with team colours renders its crest from them, and the swatches as before', () => {
  assert.deepEqual(render({ division: 'D2', colors: ['#8C1D40', 'FFC627'] }), [
    ' style="--crest:#8C1D40;--crest2:#FFC627;--crest-ink:#ffffff"',
    '<span class="swatches" aria-hidden="true"><i style="background:#8C1D40"></i><i style="background:#FFC627"></i></span>',
  ]);
  // one colour only: the crest's edge repeats it; the swatches' second slot is still the old grey, not a division tint
  assert.deepEqual(render({ division: 'D3', colors: ['#ffcc00'] }), [
    ' style="--crest:#ffcc00;--crest2:#ffcc00;--crest-ink:#111111"',
    '<span class="swatches" aria-hidden="true"><i style="background:#ffcc00"></i><i style="background:var(--border-light)"></i></span>',
  ]);
});

test('a program with no colours renders its division tint', () => {
  for (const d of ['D1', 'D2', 'D3']) {
    const v = `var(--div-${d.toLowerCase()})`;
    for (const colors of [undefined, [], ['not-a-colour']]) {
      assert.deepEqual(render({ division: d, colors }), [
        ` style="--crest:${v};--crest2:${v};--crest-ink:var(--text-primary)"`,
        `<span class="swatches" aria-hidden="true"><i style="background:${v}"></i><i style="background:${v}"></i></span>`,
      ], `${d} ${JSON.stringify(colors)}`);
    }
  }
});

test('no colours and an unknown division falls back to the old grey', () => {
  for (const division of ['NAIA', undefined, null, 'd1']) {
    assert.deepEqual(render({ division }), [
      '',  // no style on the band: the crest's own CSS fallback, the old grey (var(--bg-surface-alt))
      '<span class="swatches" aria-hidden="true"><i style="background:var(--border)"></i><i style="background:var(--border-light)"></i></span>',
    ], String(division));
  }
});

test('each tint is defined in both themes and text on it clears AA', () => {
  const lum = hex => { const v = [0, 2, 4].map(i => parseInt(hex.slice(1 + i, 3 + i), 16) / 255)
    .map(c => c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4); return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
  for (const theme of ['light', 'dark']) {
    const i = html.indexOf(`[data-theme="${theme}"] {`), block = html.slice(i, html.indexOf('\n}', i));
    const tok = name => (block.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, 'i')) || [])[1];
    const text = tok('text-primary');
    for (const d of ['d1', 'd2', 'd3']) {
      const bg = tok(`div-${d}`);
      assert.ok(bg, `--div-${d} defined in ${theme}`);
      assert.ok(ratio(text, bg) >= 4.5, `${theme} ${d}: ${ratio(text, bg).toFixed(2)}:1`);
    }
  }
});
