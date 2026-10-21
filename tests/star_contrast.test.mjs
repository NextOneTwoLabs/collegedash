// Issue #511: the unsaved Save star ("☆", button.star-btn) was drawn in text-primary at opacity 0.35 - rgb(172,174,179) on
// a white card, 2.22:1 (light) and 2.88:1 (dark). WCAG 2.2 SC 1.4.11 asks 3:1 of a graphical object that identifies a
// control's state. The same opacity also faded the keyboard focus ring (an outline is painted with its element), so the
// ring on an unsaved star was a pale blue far below 3:1.
//
//     node --test tests/star_contrast.test.mjs
//
// HOW THE RATIOS ARE GOT. From the page's own CSS, never from a pinned hex: the theme variables come from the `:root` and
// `[data-theme]` rules; the cascade for one `button.star-btn` is resolved (specificity, then source order) for the state
// under test; the colour is shown at its resolved opacity over each surface the star sits on; the surfaces are read from
// the rules that paint them. The focus ring is the outline left after replaying `outline`, `outline-color`,
// `outline-style` and `outline-width` in cascade order, in the state a keyboard-focused star really has: it matches both
// `:focus` and `:focus-visible` (a `:focus { outline: none }` rule removes the ring), and with a pointer over it `:hover`.
//
// WHAT IT CHECKS - exactly this and no more.
//   Read and resolved: every rule outside any at-rule whose selector is one compound of the star's own tag, classes and
//   pseudo-classes (`button`, `.star-btn`, `.star-btn.starred`, `.star-btn-label`, `.star-btn:hover`, `button:focus`,
//   `:focus-visible`, ...) and that sets color, opacity or an outline property.
//   Fails loudly rather than being skipped ("cannot read"): a rule that sets one of those properties on any other
//   selector which contains `star-btn`, starts with `button` or starts with `*`; any rule inside an at-rule (@media,
//   @supports) whose selector would match the star; `!important` on one of those properties.
//   NOT checked, and it passes silently: a rule that reaches the star through another selector - `.foot-actions button
//   { color }`, `.foot-actions > * { opacity }`, `:is(...)`, an attribute selector; anything an ancestor does to it, such
//   as `.pcard .foot { opacity: .5 }` or a filter; display or visibility; the labelled variant's border and background.
//   Those are not catchable here without tripping on unrelated rules (`.pchip button`, `.cmp-results button`), so they
//   rest on the browser measurements in the PR (shots.js and the star states: rest, hover, keyboard focus, saved).
//
// WHERE THE STAR APPEARS: every program card's foot (Programs, Shortlist, Recommended), the table view's first column,
// and each camp row. The program page uses the labelled variant ("☆ Save", .star-btn-label), which is text on a bordered
// pill; Compare has no star. The labelled variant is guarded below because it shares `.star-btn`.
//
// Tests marked GUARD pass on main as well: they keep what was already right from being traded away by the fix.
//
// STAR_CONTRAST_TEST_HTML (optional) points at another copy of index.html, so the page from before this change, or a
// mutated copy, can be run through these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseCss, decls } from './lib/css_cascade.mjs';
import { pageCss, themeVars, colour, over, ratio, deltaE, cascadeFor, outlineFrom } from './lib/contrast.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HTML = process.env.STAR_CONTRAST_TEST_HTML || path.join(HERE, '..', 'public', 'index.html');
const CSS = pageCss(fs.readFileSync(HTML, 'utf8'));
const RULES = parseCss(CSS);
const THEMES = ['light', 'dark'].map(name => ({ name, vars: themeVars(CSS, name) }));

// The surfaces a star sits on, as the rule that paints each. Opaque or translucent: a translucent one is laid over the
// card's own surface.
const SURFACES = {
  'program card': '.card',
  'table panel': '.flight-panel',
  'camp list': '.camp-list',
  'hovered table row': '.standings-table tr:hover td',
  'highlighted table row': '.standings-table tr.team-row-highlight td',
};
function surface(selector, vars) {
  let value = null;
  for (const r of RULES) {
    if (r.at.length || !r.selectors.includes(selector)) continue;
    for (const d of decls(r.body)) if (d.prop === 'background' || d.prop === 'background-color') value = d.value;
  }
  assert.ok(value, `no rule paints "${selector}" - the star-contrast test cannot find the surface it sits on`);
  const base = colour(vars['--bg-surface'], vars);
  return over(colour(value, vars), base.slice(0, 3));
}

const WATCH = /star-btn|^button\b|^\*/;
const PROPS = ['color', 'opacity', 'outline', 'outline-color', 'outline-style', 'outline-width'];
// What one star button looks like in `states`, drawn on `under`: the glyph's colour at its opacity, and the focus ring
// (the outline's colour at the SAME opacity - the outline belongs to the element), or why there is none.
function look(classes, states, vars, under) {
  const { applied, win, unreadable } = cascadeFor(CSS, { tag: 'button', classes, states }, WATCH, PROPS);
  assert.deepEqual(unreadable, [], `the star-contrast test cannot read: ${unreadable.join('; ')}`);
  assert.ok(win.color, 'no rule gives the star a colour');
  const opacity = win.opacity ? Number(win.opacity.value) : 1;
  assert.ok(opacity >= 0 && opacity <= 1, `opacity ${win.opacity?.value}`);
  const ink = colour(win.color.value, vars);
  const glyph = over(ink, under, opacity);
  const o = outlineFrom(applied, c => colour(c, vars));
  const ring = o.visible ? over(o.colour.toLowerCase() === 'currentcolor' ? ink : colour(o.colour, vars), under, opacity) : null;
  return { glyph, ring, opacity, colour: win.color.value, outline: `${o.width} ${o.style} ${o.colour}`, ringBy: applied.filter(d => d.prop.startsWith('outline')).map(d => `${d.sel} { ${d.prop}: ${d.value} }`) };
}
const UNSAVED = ['star-btn'];
// A keyboard-focused button matches :focus and :focus-visible, and may have the pointer over it as well.
const FOCUSED = [['focus', 'focus-visible'], ['focus', 'focus-visible', 'hover']];

// Every theme x surface is checked and ALL failures are reported together, so a run shows light and dark at once.
const sweep = (check) => {
  const bad = [];
  for (const { name, vars } of THEMES) for (const [what, sel] of Object.entries(SURFACES)) check({ name, vars, what, bg: surface(sel, vars), bad });
  return bad;
};

test('the unsaved star reaches 3:1 (WCAG 1.4.11) in both themes, on every surface it sits on', () => {
  const bad = sweep(({ name, vars, what, bg, bad }) => {
    const s = look(UNSAVED, [], vars, bg), r = ratio(s.glyph, bg);
    if (r < 3) bad.push(`${name}, ${what}: ${r.toFixed(2)}:1 (colour ${s.colour} at opacity ${s.opacity})`);
  });
  assert.deepEqual(bad, [], `the unsaved star needs 3:1 (1.4.11):\n  ${bad.join('\n  ')}`);
});

test('GUARD (passes on main too): hovering the unsaved star keeps 3:1 and is still a visible step darker than rest', () => {
  const bad = sweep(({ name, vars, what, bg, bad }) => {
    const rr = ratio(look(UNSAVED, [], vars, bg).glyph, bg), rh = ratio(look(UNSAVED, ['hover'], vars, bg).glyph, bg);
    if (rh < 3) bad.push(`${name}, ${what}: hovered star is ${rh.toFixed(2)}:1`);
    if (rh - rr < 0.5) bad.push(`${name}, ${what}: hover (${rh.toFixed(2)}:1) is not a visible step from rest (${rr.toFixed(2)}:1)`);
  });
  assert.deepEqual(bad, [], `hover:\n  ${bad.join('\n  ')}`);
});

test('the keyboard focus ring on an unsaved star reaches 3:1 - not faded by the star\'s opacity, not removed by a :focus rule', () => {
  const bad = sweep(({ name, vars, what, bg, bad }) => {
    for (const states of FOCUSED) {
      const s = look(UNSAVED, states, vars, bg), at = `${name}, ${what}, ${states.join('+')}`;
      if (!s.ring) { bad.push(`${at}: no focus ring (outline ${s.outline}; set by ${s.ringBy.join(' ; ') || 'nothing'})`); continue; }
      const r = ratio(s.ring, bg);
      if (r < 3) bad.push(`${at}: ring is ${r.toFixed(2)}:1 (the star is at opacity ${s.opacity})`);
    }
  });
  assert.deepEqual(bad, [], `the focus ring needs 3:1:\n  ${bad.join('\n  ')}`);
});

// "Distinct" is a colour difference you can see, not "not byte-identical": CIE76 deltaE of the two glyphs as drawn.
// The saved star is amber and the unsaved one a grey; both themes sit far above this floor (the old 0.35-opacity grey did too).
const MIN_DELTA_E = 40;
test('GUARD (passes on main too): the unsaved star stays clearly distinct from the saved one and lighter than muted text', () => {
  for (const { name, vars } of THEMES) {
    const bg = surface(SURFACES['program card'], vars);
    const off = look(UNSAVED, [], vars, bg), on = look(['star-btn', 'starred'], [], vars, bg);
    const d = deltaE(off.glyph, on.glyph);
    assert.ok(d >= MIN_DELTA_E, `${name}: the unsaved and saved stars differ by only deltaE ${d.toFixed(1)} (needs ${MIN_DELTA_E}): not recoloured gold`);
    const mutedRatio = ratio(over(colour(vars['--text-secondary'], vars), bg), bg);
    const inkRatio = ratio(over(colour(vars['--text-primary'], vars), bg), bg);
    const r = ratio(off.glyph, bg);
    assert.ok(r < mutedRatio, `${name}: the unsaved star (${r.toFixed(2)}:1) is not lighter than muted text (${mutedRatio.toFixed(2)}:1)`);
    assert.ok(r < inkRatio, `${name}: the unsaved star (${r.toFixed(2)}:1) is not lighter than the text colour (${inkRatio.toFixed(2)}:1)`);
  }
});

test('GUARD (passes on main too): the program page\'s labelled "☆ Save" is text and keeps 4.5:1, at rest and on hover', () => {
  for (const { name, vars } of THEMES) {
    const bg = surface(SURFACES['program card'], vars);
    for (const states of [[], ['hover']]) {
      const s = look(['star-btn', 'star-btn-label'], states, vars, bg), r = ratio(s.glyph, bg);
      assert.ok(r >= 4.5, `${name}, ${states.join('+') || 'rest'}: the labelled Save is ${r.toFixed(2)}:1`);
    }
  }
});
