// WCAG contrast computed from the page's own CSS, for the tests that must not pin a hex (#511).
// Pairs with tests/lib/css_cascade.mjs (parseCss, decls). Two older tests keep their own inline copies of lum/ratio
// (card_brackets, conference_counts); this is the shared one for new tests.
//
//   const css = pageCss(html)                       the page's <style> text
//   const vars = themeVars(css, 'dark')             {--bg-surface: '#171a21', ...}: :root, then [data-theme="dark"]
//   const rgb = colour('var(--star-off)', vars)     [r, g, b, a], var() resolved through the theme (and aliases)
//   const ink = over(rgb, bg, opacity)              what the eye sees: the colour at its opacity over bg (an [r,g,b])
//   ratio(ink, bg)                                  WCAG relative-luminance ratio
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

// [r, g, b, a] from #rgb, #rrggbb, rgb()/rgba() or var(--name[, fallback]) resolved through `vars`.
export function colour(value, vars, depth = 0) {
  const v = String(value).trim();
  if (depth > 8) throw new Error(`contrast helper: variables loop at "${v}"`);
  let m;
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

// The cascade for ONE element, restricted to selectors of the form `tag.a.b:state` (the element's own tag, classes and
// pseudo-classes; no combinators) outside at-rules. `el` = { tag, classes: [...], states: [...] }. Returns the winning
// declaration per property in `props` (specificity, then source order) plus `unreadable`: the rules that set one of
// those properties on a selector this cannot read but `watchSelector` says matters (a combinator, an at-rule,
// !important), so a test can fail loudly instead of measuring something the browser would not.
export function cascadeFor(css, el, watchSelector, props) {
  const tag = el.tag, classes = new Set(el.classes), states = new Set(el.states);
  const win = {}, unreadable = [];
  let order = 0;
  for (const r of parseCss(css)) {
    order++;
    const touches = decls(r.body).filter(d => props.includes(d.prop));
    for (const sel of r.selectors) {
      const simple = /^([a-z][\w-]*)?((?:\.[\w-]+)*)((?::[\w-]+)*)$/i.exec(sel);
      if (!simple || !sel) {
        if (touches.length && watchSelector.test(sel)) unreadable.push(`${r.at.join(' ')} ${sel}`.trim());
        continue;
      }
      if (r.at.length) { if (touches.length && watchSelector.test(sel)) unreadable.push(`${r.at.join(' ')} ${sel}`.trim()); continue; }
      const cls = simple[2].split('.').filter(Boolean), pseudo = simple[3].split(':').filter(Boolean);
      if ((simple[1] && simple[1].toLowerCase() !== tag) || !cls.every(c => classes.has(c)) || !pseudo.every(p => states.has(p))) continue;
      const spec = (cls.length + pseudo.length) * 10 + (simple[1] ? 1 : 0);
      for (const d of touches) {
        if (/!\s*important/i.test(d.value)) { unreadable.push(`!important in ${sel} { ${d.prop} }`); continue; }
        const key = d.prop;
        if (!win[key] || spec > win[key].spec || (spec === win[key].spec && order > win[key].order)) win[key] = { value: d.value, spec, order, sel };
      }
    }
  }
  return { win, unreadable };
}
