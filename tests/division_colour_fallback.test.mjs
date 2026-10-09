// Tests for the division-tint fallback for programs with no team colours (issue #276 part C).
//
//     node --test tests/division_colour_fallback.test.mjs
//
// The team-colour helpers are cut out of the real public/index.html (from the "team colours" marker to
// swatchesHtml) and run in a `vm`, so what is tested is the shipped source, not a copy. The tint tokens
// are read from the real theme blocks in the same file.
//
// What this proves:
//   - a program WITH colours renders exactly the pinned markup (since #492: its colours and the ink that reads on
//     the first as CSS variables on the card's title band, and the swatches);
//   - a program with no colours gets the grey band (#492, owner: no band variables) but the swatches keep its
//     own division's tint (#276);
//   - a program with no colours and an unknown or missing division keeps the old grey swatch placeholder;
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
vm.runInContext(`${escLine}\n${html.slice(start, end)}\nthis.api = { teamColors, bandVars, swatchesHtml };`, ctx);
const { bandVars, swatchesHtml } = ctx.api;
// #492: the card shows the colours as CSS variables on its title band (none when the program has no colours: grey band).
const render = p => [bandVars(p), swatchesHtml(p)];

test('a program with team colours renders its band from them, and the swatches as before', () => {
  assert.deepEqual(render({ division: 'D2', colors: ['#8C1D40', 'FFC627'] }), [
    ' style="--band:#8C1D40;--band2:#FFC627;--band-ink:#ffffff"',
    '<span class="swatches" aria-hidden="true"><i style="background:#8C1D40"></i><i style="background:#FFC627"></i></span>',
  ]);
  // one colour only: the band's edge repeats it; the swatches' second slot is still the old grey, not a division tint
  assert.deepEqual(render({ division: 'D3', colors: ['#ffcc00'] }), [
    ' style="--band:#ffcc00;--band2:#ffcc00;--band-ink:#000000"',
    '<span class="swatches" aria-hidden="true"><i style="background:#ffcc00"></i><i style="background:var(--border-light)"></i></span>',
  ]);
});

test('a program with no colours gets the grey band (no variables) and its division tint in the swatches', () => {
  for (const d of ['D1', 'D2', 'D3']) {
    const v = `var(--div-${d.toLowerCase()})`;
    for (const colors of [undefined, [], ['not-a-colour']]) {
      assert.deepEqual(render({ division: d, colors }), [
        '',  // no style on the band: the CSS fallback, the grey var(--bg-surface-alt) with var(--text-primary) ink
        `<span class="swatches" aria-hidden="true"><i style="background:${v}"></i><i style="background:${v}"></i></span>`,
      ], `${d} ${JSON.stringify(colors)}`);
    }
  }
});

test('no colours and an unknown division falls back to the old grey', () => {
  for (const division of ['NAIA', undefined, null, 'd1']) {
    assert.deepEqual(render({ division }), [
      '',  // no style on the band: the CSS fallback, the old grey (var(--bg-surface-alt))
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
