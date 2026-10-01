// Shared by the tests that read the page's CSS (#430: tests/card_rows.test.mjs, tests/header_narrow.test.mjs).
// Small on purpose: a parser, and ONE check - the exact layout of the selectors a test watches.
//
// The gap it closes (Bianque, review of #428): a check that only rejected selectors it did not know let a new layout
// property on a selector it DID know through - `.pcard .foot { order: -1 }` passed all 8 card-row tests. exactLayout
// pins, for every watched selector, the exact set of layout properties and their values, so adding, removing or
// changing one fails loudly.
import assert from 'node:assert/strict';

// [{ at: ['@media (max-width: 400px)', ...], selectors: ['.a > .b', ...], body }], comments removed, at-rules nested.
export function parseCss(text) {
  const src = text.replace(/\/\*[\s\S]*?\*\//g, '');
  const out = [];
  const walk = (chunk, at) => {
    let i = 0;
    while (i < chunk.length) {
      const open = chunk.indexOf('{', i);
      if (open < 0) break;
      let depth = 1, j = open + 1;
      while (j < chunk.length && depth) { if (chunk[j] === '{') depth++; else if (chunk[j] === '}') depth--; j++; }
      const prelude = chunk.slice(i, open).trim(), body = chunk.slice(open + 1, j - 1);
      if (prelude.startsWith('@')) walk(body, [...at, prelude.replace(/\s+/g, ' ')]);
      else out.push({ at, selectors: prelude.split(',').map(s => s.replace(/\s+/g, ' ').trim()).filter(Boolean), body });
      i = j;
    }
  };
  walk(src, []);
  return out;
}

export const decls = body => body.split(';').map(d => d.trim()).filter(Boolean).map(d => {
  const i = d.indexOf(':');
  return { prop: d.slice(0, i).trim().toLowerCase(), value: d.slice(i + 1).trim() };
});

// Properties that can move a box, take it out of flow, hide it, reorder it or change its size or its children's layout.
export const LAYOUT = /^(display|visibility|content-visibility|position|inset(-.*)?|top|right|bottom|left|float|clear|order|transform|translate|rotate|scale|z-index|grid(-.*)?|flex(-.*)?|align-(content|items|self)|justify-(content|items|self)|place-(content|items|self)|gap|row-gap|column-gap|margin(-.*)?|padding(-.*)?|width|min-width|max-width|height|min-height|max-height|font|font-size|line-height|letter-spacing|white-space|overflow(-[xy])?|contain)$/;

/* For every selector `watched(sel)` names, the layout declarations it sets, keyed "<at-rules joined by space>|<selector>"
   ("" before the bar outside any at-rule); a later rule with the same key overrides an earlier value, as the cascade
   would. Fails loudly, with `cannot` in the message, on:
     - a watched key not in `expected`;
     - !important on a layout property of a watched selector;
     - a watched key whose layout properties are not EXACTLY expected[key] - one added, removed or changed;
     - an expected key that no rule sets any more. */
export function exactLayout(rules, { watched, expected, cannot, layout = LAYOUT }) {
  const got = {};
  for (const r of rules) {
    const ds = decls(r.body).filter(d => layout.test(d.prop));
    if (!ds.length) continue;
    for (const sel of r.selectors) {
      if (!watched(sel)) continue;
      const key = `${r.at.join(' ')}|${sel}`;
      if (!(key in expected)) assert.fail(`${cannot} "${key}", which sets ${ds.map(d => d.prop).join('/')}`);
      for (const d of ds) {
        if (/!\s*important/i.test(d.value)) assert.fail(`${cannot} !important in "${key} { ${d.prop}: ${d.value} }"`);
        (got[key] = got[key] || {})[d.prop] = d.value;
      }
    }
  }
  for (const [key, want] of Object.entries(expected)) {
    const have = got[key] || {};
    const props = [...new Set([...Object.keys(want), ...Object.keys(have)])].sort();
    const diff = props.filter(p => have[p] !== want[p]).map(p => `${p}: ${have[p] ?? '(none)'} (expected ${want[p] ?? '(none)'})`);
    if (diff.length) assert.fail(`${cannot} "${key}" as it now stands - ${diff.join('; ')}`);
  }
  return got;
}
