// WCAG contrast computed from the page's own CSS, for the tests that must not pin a hex (#511).
// Pairs with tests/lib/css_cascade.mjs (parseCss, decls). Two older tests keep their own inline copies of lum/ratio
// (card_brackets, conference_counts); this is the shared one for new tests.
//
//   const css = pageCss(html)                       the page's <style> text
//   const vars = themeVars(css, 'dark')             {--bg-surface: '#171a21', ...}: :root, then [data-theme="dark"]
//   const rgb = colour('var(--star-off)', vars)     [r, g, b, a], var() resolved through the theme (and aliases)
//   const ink = over(rgb, bg, opacity)              what the eye sees: the colour at its opacity over bg (an [r,g,b])
//   ratio(ink, bg)                                  WCAG relative-luminance ratio
//   deltaE(a, b)                                    CIE76 colour difference of two [r,g,b]
//   cascadeFor(css, el, watch, props)               the declarations of `props` that apply to ONE element, in cascade order
//   outlineFrom(applied, colourOf)                  the outline those declarations leave (shorthand and longhands replayed)
//
// Anything it cannot read (a colour function it does not know, a variable that is not defined) THROWS with the value
// in the message, so a restyle fails loudly instead of being measured as something else.
import { parseCss, decls } from './css_cascade.mjs';

export const pageCss = html => {
  const m = /<style>([\s\S]*?)<\/style>/.exec(html);
  if (!m) throw new Error('contrast helper: no <style> block in the page');
  return m[1];
};

// The custom properties in force for one theme: every plain `:root` and `[data-theme="<theme>"]` rule, in source order.
export function themeVars(css, theme) {
  const vars = {};
  for (const r of parseCss(css)) {
    if (r.at.length) continue;
    if (!r.selectors.some(s => s === ':root' || s === `[data-theme="${theme}"]`)) continue;
    for (const d of decls(r.body)) if (d.prop.startsWith('--')) vars[d.prop] = d.value;
  }
  return vars;
}

// [r, g, b, a] from #rgb, #rrggbb, rgb()/rgba(), `transparent` or var(--name[, fallback]) resolved through `vars`.
export function colour(value, vars, depth = 0) {
  const v = String(value).trim();
  if (depth > 8) throw new Error(`contrast helper: variables loop at "${v}"`);
  let m;
  if (/^transparent$/i.test(v)) return [0, 0, 0, 0];
  if ((m = /^var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)$/.exec(v))) {
    const next = vars[m[1]] ?? m[2];
    if (next == null) throw new Error(`contrast helper: ${m[1]} is not defined in this theme`);
    return colour(next, vars, depth + 1);
  }
  if ((m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(v))) {
    const h = m[1].length === 3 ? [...m[1]].map(c => c + c).join('') : m[1];
    return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)).concat(1);
  }
  if ((m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/i.exec(v))) {
    const a = m[4] == null ? 1 : m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]);
    return [Number(m[1]), Number(m[2]), Number(m[3]), a];
  }
  throw new Error(`contrast helper: cannot read the colour "${v}"`);
}

// `fg` ([r,g,b,a]) shown at element `opacity` over an opaque `under` ([r,g,b]) -> [r,g,b] (unrounded).
export const over = (fg, under, opacity = 1) => {
  const a = fg[3] * opacity;
  return [0, 1, 2].map(i => fg[i] * a + under[i] * (1 - a));
};

export const lum = c => {
  const [r, g, b] = c.slice(0, 3).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
export const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

// CIE76 colour difference between two [r,g,b] (sRGB, 0-255): about 2.3 is a just-noticeable difference, 10 or more is
// plainly a different colour.
export const deltaE = (a, b) => {
  const lab = c => {
    const [r, g, bl] = c.slice(0, 3).map(v => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    const xyz = [(0.4124 * r + 0.3576 * g + 0.1805 * bl) / 0.95047, 0.2126 * r + 0.7152 * g + 0.0722 * bl, (0.0193 * r + 0.1192 * g + 0.9505 * bl) / 1.08883];
    const [fx, fy, fz] = xyz.map(t => (t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116));
    return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
  };
  const [p, q] = [lab(a), lab(b)];
  return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
};

// The cascade for ONE element, restricted to selectors of the form `tag.a.b:state` (the element's own tag, classes and
// pseudo-classes; no combinators). `el` = { tag, classes: [...], states: [...] }. Returns
//   applied    every declaration of a property in `props` that applies to the element, in cascade order (specificity,
//              then source order), so a caller can replay shorthands and longhands the way the browser does;
//   win        the last of those per property;
//   unreadable the rules a test must not silently skip: a rule outside the plain form that sets one of `props` and
//              whose selector `watchSelector` matches; a rule inside an at-rule whose selector, ignoring the at-rule,
//              would match the element; and any `!important` on one of `props`.
// It does NOT see a rule whose selector is outside the plain form and does not match `watchSelector` (a descendant
// rule on a parent, `.foot-actions button`, `:is(...)`), nor anything inherited or applied by an ancestor (opacity).
export function cascadeFor(css, el, watchSelector, props) {
  const tag = el.tag, classes = new Set(el.classes), states = new Set(el.states);
  const applied = [], unreadable = [];
  let order = 0;
  for (const r of parseCss(css)) {
    order++;
    const touches = decls(r.body).filter(d => props.includes(d.prop));
    if (!touches.length) continue;
    for (const sel of r.selectors) {
      const simple = /^([a-z][\w-]*)?((?:\.[\w-]+)*)((?::[\w-]+)*)$/i.exec(sel);
      if (!simple) {
        if (watchSelector.test(sel)) unreadable.push(`${r.at.join(' ')} ${sel}`.trim());
        continue;
      }
      const cls = simple[2].split('.').filter(Boolean), pseudo = simple[3].split(':').filter(Boolean);
      if ((simple[1] && simple[1].toLowerCase() !== tag) || !cls.every(c => classes.has(c)) || !pseudo.every(p => states.has(p))) continue;
      if (r.at.length) { unreadable.push(`${r.at.join(' ')} ${sel}`.trim()); continue; }
      const spec = (cls.length + pseudo.length) * 10 + (simple[1] ? 1 : 0);
      for (const d of touches) {
        if (/!\s*important/i.test(d.value)) { unreadable.push(`!important in ${sel} { ${d.prop} }`); continue; }
        applied.push({ prop: d.prop, value: d.value, spec, order, sel });
      }
    }
  }
  applied.sort((a, b) => a.spec - b.spec || a.order - b.order);
  const win = {};
  for (const d of applied) win[d.prop] = d;
  return { applied, win, unreadable };
}

// The outline an element ends up with, replaying `applied` (from cascadeFor) in order: the `outline` shorthand resets
// width, style and colour to their initial values (medium, none, currentcolor); each longhand sets one.
// -> { width, style, colour } as written, plus `visible`: false for style none/hidden, a zero width or a transparent
// colour (`colourOf` turns a written colour into [r,g,b,a]; `currentcolor` is left to the caller).
const STYLES = /^(none|hidden|auto|solid|dashed|dotted|double|groove|ridge|inset|outset)$/i;
const WIDTH = /^(\d*\.?\d+(px|em|rem)?|thin|medium|thick)$/i;
const tokens = v => {
  const out = []; let depth = 0, cur = '';
  for (const ch of v.trim()) {
    if (ch === '(') depth++; else if (ch === ')') depth--;
    if (/\s/.test(ch) && !depth) { if (cur) out.push(cur); cur = ''; } else cur += ch;
  }
  if (cur) out.push(cur);
  return out;
};
export function outlineFrom(applied, colourOf) {
  const o = { width: 'medium', style: 'none', colour: 'currentcolor' };
  for (const d of applied) {
    if (d.prop === 'outline') {
      Object.assign(o, { width: 'medium', style: 'none', colour: 'currentcolor' });
      for (const t of tokens(d.value)) { if (STYLES.test(t)) o.style = t.toLowerCase(); else if (WIDTH.test(t)) o.width = t; else o.colour = t; }
    } else if (d.prop === 'outline-style') o.style = d.value.trim().toLowerCase();
    else if (d.prop === 'outline-width') o.width = d.value.trim();
    else if (d.prop === 'outline-color') o.colour = d.value.trim();
  }
  const zero = /^0*\.?0*(px|em|rem)?$/.test(o.width);
  const clear = o.colour.toLowerCase() !== 'currentcolor' && colourOf(o.colour)[3] === 0;
  return { ...o, visible: !/^(none|hidden)$/.test(o.style) && !zero && !clear };
}
