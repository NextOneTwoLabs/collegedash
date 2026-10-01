// Issue #51: at 320-375 px "College Soccer" ran under the theme toggle (41 px of overlap at 320, none to spare at 375).
//
//     node --test tests/header_narrow.test.mjs
//
// Node has no layout engine, so this pins the CSS that fixes it. The page's <style> is parsed and, for the five header
// elements below, the properties the checks read (display, font-size, gap) are resolved at a given viewport width by a
// small cascade that understands exactly the forms the header uses and FAILS LOUDLY on anything else that could set
// one of those properties on one of those elements: a descendant, child or compound selector, a bare tag or `*`, an
// attribute selector, a pseudo-class, !important, visibility, an unknown @media form or another at-rule (Huatuo's
// review of #421, after #413). So a rule it cannot evaluate can never make a check pass; the self-test feeds it each
// of those forms, including the three mutations that passed the first version.
//
// The widths the rules were chosen from were measured in a browser against local serve.py, in both themes (PR body):
// the label clears the toggle by at least 14 px wherever it shows, and the page never scrolls sideways.
// What it CANNOT prove, and a human must check: the rendered gap on a real phone, and fonts that differ from the
// measuring browser's.
//
// HEADER_NARROW_TEST_HTML (optional) points at another copy of index.html, so the page from before this change (or a
// deliberately broken one) can be run through these same checks to show them failing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseCss as parseRules, decls, exactLayout, LAYOUT } from './lib/css_cascade.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HTML = process.env.HEADER_NARROW_TEST_HTML || path.join(HERE, '..', 'public', 'index.html');
const page = fs.readFileSync(HTML, 'utf8');
const CSS = [...page.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n');
const CANNOT = 'the header test cannot read';

// The elements, as the markup has them (pinned by the markup test below): tag, classes, attributes, and the ancestors
// whose display decides whether they are drawn.
const ELEMENTS = {
  '.header': { tag: 'div', classes: ['header'], attrs: ['class'], ancestors: [] },
  '.header-left': { tag: 'div', classes: ['header-left'], attrs: ['class'], ancestors: ['.header'] },
  '.wordmark': { tag: 'a', classes: ['wordmark'], attrs: ['class', 'href'], ancestors: ['.header-left', '.header'] },
  '.header-divider': { tag: 'div', classes: ['header-divider'], attrs: ['class'], ancestors: ['.header-left', '.header'] },
  '.section-label': { tag: 'a', classes: ['section-label'], attrs: ['class', 'href'], ancestors: ['.header-left', '.header'] },
};
// Everything above them in the document: their header ancestors, <body> (no class) and <html lang data-theme>.
const ROOTS = [{ tag: 'body', classes: [], attrs: [] }, { tag: 'html', classes: [], attrs: ['lang', 'data-theme'] }];
const above = target => [...ELEMENTS[target].ancestors.map(t => ELEMENTS[t]), ...ROOTS];
const READ = /^(display|visibility|content-visibility|font-size|font|gap|column-gap)$/;

// [{ media: [prelude, ...], selectors, decls, order }], from the shared parser (tests/lib/css_cascade.mjs, #430).
const parseCss = text => parseRules(text).map((r, order) => ({ media: r.at, selectors: r.selectors, decls: r.body, order }));

// #430: the exact layout of the five header elements' own rules. resolve() below reads only display, font-size and gap;
// a layout property it does not read (position, order, transform, margin, ...) added to one of these selectors, or a
// changed value, fails here instead of passing silently.
const EXACT = {
  '|.header': { padding: '0 20px', height: 'var(--header-height)', display: 'flex', 'align-items': 'center', 'justify-content': 'space-between', position: 'fixed', top: '0', left: '0', right: '0', 'z-index': '100' },
  '|.header-left': { display: 'flex', 'align-items': 'center', gap: '14px', 'min-width': '0' },
  '|.wordmark': { 'font-size': '21px', 'letter-spacing': '-0.6px', 'line-height': '1', 'white-space': 'nowrap' },
  '|.header-divider': { width: '1px', height: '24px' },
  '|.section-label': { 'font-size': '14px', 'white-space': 'nowrap' },
  // #434: at <=768 px the header is two rows - this brand row (left cell, the toggle beside it), then the search box
  '@media (max-width: 768px)|.header': { display: 'grid', 'grid-template-columns': 'minmax(0, 1fr) auto', 'grid-template-rows': '52px 52px', 'column-gap': '8px', 'align-items': 'center' },
  '@media (max-width: 460px)|.header': { padding: '0 12px' },
  '@media (max-width: 460px)|.header-left': { gap: '8px' },
  '@media (max-width: 400px)|.header-left': { gap: '6px' },
  '@media (max-width: 400px)|.wordmark': { 'font-size': '18px' },
  '@media (max-width: 400px)|.section-label': { 'font-size': '13px' },
  '@media (max-width: 359px)|.header-divider': { display: 'none' },
  '@media (max-width: 359px)|.section-label': { display: 'none' },
  '@media print|.header': { display: 'none' },
};
const exactHeader = text => exactLayout(parseRules(text), { watched: sel => sel in ELEMENTS, expected: EXACT, cannot: CANNOT });

// true / false for a screen of `width`, or a loud failure for any form other than (max-width: Npx) / (min-width: Npx)
// joined by "and", and `print` (never a screen).
function mediaMatches(media, width) {
  return media.every(prelude => {
    const m = /^@media\s+(.*)$/.exec(prelude);
    assert.ok(m, `${CANNOT} the at-rule "${prelude}"`);
    if (/^print$/.test(m[1].trim())) return false;
    return m[1].split(/\band\b/).map(s => s.trim()).filter(Boolean).every(c => {
      const q = /^\((max|min)-width:\s*(\d+)px\)$/.exec(c);
      assert.ok(q, `${CANNOT} the media form "${prelude}"`);
      return q[1] === 'max' ? width <= +q[2] : width >= +q[2];
    });
  });
}

// Could the last compound of a selector match `el`? Conservative: pseudo-classes, and attributes the element carries,
// are treated as possibly matching (and then fail loudly below); an ID, an attribute the element lacks ([hidden]), or
// a class it lacks rules it out.
function mayMatch(compound, el) {
  if (compound.includes('::')) return false;  // a pseudo-element is another box
  const attrs = [...compound.matchAll(/\[\s*([\w-]+)/g)].map(m => m[1].toLowerCase());
  if (!attrs.every(a => el.attrs.includes(a))) return false;
  const bare = compound.replace(/:not\([^)]*\)/g, '').replace(/:[\w-]+(\([^)]*\))?/g, '').replace(/\[[^\]]*\]/g, '');
  if (bare.includes('#')) return false;  // none of these elements carries an id
  const tag = /^[a-z*][\w-]*/i.exec(bare)?.[0];
  if (tag && tag !== '*' && tag.toLowerCase() !== el.tag) return false;
  const classes = [...bare.matchAll(/\.([\w-]+)/g)].map(m => m[1]);
  return classes.every(c => el.classes.includes(c));
}

// The value of `prop` on `target` at `width`, or undefined; fails loudly on any rule it cannot evaluate.
function resolve(target, prop, width, rules) {
  const el = ELEMENTS[target];
  let value;
  for (const r of rules) {
    const lay = decls(r.decls).filter(d => LAYOUT.test(d.prop) || READ.test(d.prop)), read = lay.filter(d => READ.test(d.prop));
    if (!lay.length) continue;
    for (const sel of r.selectors) {
      const parts = sel.split(/\s*[>+~]\s*|\s+/).filter(Boolean), last = parts.pop();
      // Anything that names the element's own class other than the bare class itself (`.section-label.x`,
      // `.section-label:hover`, `.header .section-label`) is a form this cascade does not evaluate.
      const names = el.classes.some(c => new RegExp(`\\.${c}(?![\\w-])`).test(last));
      if (names && sel !== target) assert.fail(`${CANNOT} "${sel}", which may set ${lay.map(d => d.prop).join('/')} on ${target}`);
      if (!mayMatch(last, el)) continue;
      // A context compound no element above it could match (`.trend-table a`) rules the selector out; one that could
      // (`.header .section-label`, `[data-theme] a`) leaves a selector this cascade does not evaluate: it fails below.
      if (!parts.every(p => above(target).some(a => mayMatch(p, a)))) continue;
      if (sel !== target) assert.fail(`${CANNOT} "${sel}", which may set ${lay.map(d => d.prop).join('/')} on ${target}`);
      for (const d of lay) {
        if (/!\s*important/i.test(d.value)) assert.fail(`${CANNOT} !important in "${sel} { ${d.prop}: ${d.value} }"`);
        if (/visibility$/.test(d.prop)) assert.fail(`${CANNOT} ${d.prop} on "${sel}"`);
        if (d.prop === 'font') assert.fail(`${CANNOT} the font shorthand on "${sel}"`);
      }
      if (!mediaMatches(r.media, width)) continue;
      for (const d of read) if (d.prop === prop || (prop === 'gap' && d.prop === 'column-gap')) value = d.value;
    }
  }
  return value;
}
// Drawn = neither it nor an ancestor resolves to display: none.
const drawn = (target, width, rules) => [target, ...ELEMENTS[target].ancestors].every(t => resolve(t, 'display', width, rules) !== 'none');
const RULES = parseCss(CSS);
const at = (target, prop, width) => resolve(target, prop, width, RULES);

test('the cascade fails loudly on every form it cannot evaluate', () => {
  const run = extra => () => {
    const rules = parseCss(`${CSS}\n${extra}`);
    exactHeader(`${CSS}\n${extra}`);
    for (const t of Object.keys(ELEMENTS)) for (const w of [320, 375, 1280]) { drawn(t, w, rules); resolve(t, 'font-size', w, rules); resolve(t, 'gap', w, rules); }
  };
  assert.doesNotThrow(run(''), 'the page\'s own CSS is not readable');
  for (const [name, extra] of [
    ['a descendant selector hiding the label at every width (Huatuo)', '.header .section-label { display: none; }'],
    ['!important hiding the label at 360-400 px (Huatuo)', '@media (min-width: 360px) and (max-width: 400px) { .section-label { display: none !important; } }'],
    ['a media form without a px width (Huatuo)', '@media (prefers-reduced-motion: reduce) { .section-label { display: none; } }'],
    ['a child combinator', '.header-left > .section-label { display: none; }'],
    ['a compound selector', '.section-label.x { display: none; }'],
    ['a bare tag', '@media (max-width: 400px) { a { font-size: 30px; } }'],
    ['the universal selector', '.header-left > * { display: none; }'],
    ['an attribute selector', 'a[href] { display: none; }'],
    ['a pseudo-class', '.section-label:hover { font-size: 30px; }'],
    ['visibility', '.section-label { visibility: hidden; }'],
    ['the font shorthand', '.wordmark { font: 800 30px sans-serif; }'],
    ['another at-rule', '@supports (display: grid) { .section-label { display: none; } }'],
    ['an ancestor hidden by a descendant rule', 'body .header-left { display: none; }'],
    // #430: a layout property the resolver does not read, on a selector it knows, or in a form it does not evaluate
    ['position on the label', '.section-label { position: absolute; }'],
    ['order on the wordmark', '.wordmark { order: 2; }'],
    ['a margin on the left group at <=400 px', '@media (max-width: 400px) { .header-left { margin-left: 4px; } }'],
    ['a transform on the header', '.header { transform: translateX(10px); }'],
    ['a changed value on a known selector', '@media (max-width: 400px) { .header-left { gap: 9px; } }'],
    ['position in a descendant form', '.header .section-label { position: absolute; }'],
  ]) assert.throws(run(extra), new RegExp(CANNOT), `${name}: the cascade did not fail`);
  // and forms it does read change the answer, as they should
  assert.equal(drawn('.section-label', 1280, parseCss(`${CSS}\n.section-label { display: none; }`)), false);
  assert.equal(drawn('.section-label', 1280, parseCss(`${CSS}\n.header-left { display: none; }`)), false, 'an ancestor hiding it');
});

test('#430: the five header elements\' own rules set exactly the layout they did', () => {
  assert.doesNotThrow(() => exactHeader(CSS));
});

// #434 (Huatuo, change 2): the header gained a search row on phones. Row 1 is still exactly this brand row, in a cell of
// its own (minmax(0, 1fr)) beside the toggle's (auto), so the label can only be clipped by its own cell, never drawn
// under the toggle; the #51 widths below were re-measured in both themes at 320, 360 and 375 px (PR body).
test('#434: at <=768 px the header is two rows, and the brand row keeps its own cell beside the toggle', () => {
  const got = exactHeader(CSS);
  for (const w of [320, 375, 768]) assert.equal(at('.header', 'display', w), 'grid', `the header is not the two-row grid at ${w}px`);
  assert.equal(at('.header', 'display', 769), 'flex', 'the desktop header is not one row');
  const phone = got['@media (max-width: 768px)|.header'];
  assert.equal(phone['grid-template-rows'], '52px 52px');
  assert.equal(phone['grid-template-columns'], 'minmax(0, 1fr) auto');
  for (const w of [320, 340, 359]) assert.equal(drawn('.section-label', w, RULES), false, `the label is drawn at ${w}px`);
  for (const w of [360, 375]) assert.equal(drawn('.section-label', w, RULES), true, `the label is not drawn at ${w}px`);
});

test('the header markup still carries the section label and divider (only CSS hides them)', () => {
  assert.match(page, /<div class="header">\s*<div class="header-left">[\s\S]*?<a class="wordmark" [^>]*>[\s\S]*?<\/a>\s*<div class="header-divider"><\/div>\s*<a class="section-label" href="https:\/\/college\.nextonetwo\.com\/">College Soccer<\/a>\s*<\/div>/);
});

test('below 360 px the divider and the "College Soccer" label are not drawn', () => {
  for (const w of [320, 340, 359]) {
    assert.equal(drawn('.section-label', w, RULES), false, `.section-label is drawn at ${w}px`);
    assert.equal(drawn('.header-divider', w, RULES), false, `.header-divider is drawn at ${w}px`);
    assert.equal(drawn('.wordmark', w, RULES), true, `the wordmark is not drawn at ${w}px`);
  }
});

test('from 360 to 400 px the label shows, smaller, with the wordmark smaller and the left gaps tighter', () => {
  for (const w of [360, 375, 390, 400]) {
    assert.equal(drawn('.section-label', w, RULES), true, `.section-label hidden at ${w}px`);
    assert.equal(drawn('.header-divider', w, RULES), true, `.header-divider hidden at ${w}px`);
    assert.equal(at('.section-label', 'font-size', w), '13px', `label size at ${w}px`);
    assert.equal(at('.wordmark', 'font-size', w), '18px', `wordmark size at ${w}px`);
    assert.equal(at('.header-left', 'gap', w), '6px', `left gap at ${w}px`);
  }
});

test('above 400 px the header is as it was', () => {
  for (const w of [401, 460, 768, 1280]) {
    assert.equal(drawn('.section-label', w, RULES), true, `.section-label hidden at ${w}px`);
    assert.equal(at('.section-label', 'font-size', w), '14px', `label size at ${w}px`);
    assert.equal(at('.wordmark', 'font-size', w), '21px', `wordmark size at ${w}px`);
  }
  assert.equal(at('.header-left', 'gap', 1280), '14px');
  assert.equal(at('.header-left', 'gap', 460), '8px');
});
