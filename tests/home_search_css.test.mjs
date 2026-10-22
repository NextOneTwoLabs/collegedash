// #507 v1, PR 2: the Home search box's CSS (docs/plans/507-search/v1-plan.md, PR 2).
//
//     node --test tests/home_search_css.test.mjs
//
// Node has no layout engine, so this pins the CSS, not the rendering:
//   - exactLayout (tests/lib/css_cascade.mjs): every rule that names one of the box's classes - compound and descendant
//     selectors included (.home-opt.active, .home-group + .home-group) - sets exactly the layout properties below and
//     nothing else, at every @media. A new position, order, width or margin on any of them fails loudly. Home's three
//     options (.home-entries, .home-entry*) are not watched here; tests/shell_nav.test.mjs pins them.
//   - the text that must wrap rather than push the page sideways: option text has min-width: 0 and overflow-wrap.
//   - AA contrast (tests/lib/contrast.mjs, 4.5:1) in both themes of the box's text, its placeholder (through its own
//     token, --home-q-placeholder: the helper cannot read ::placeholder), the label, the section headings, option
//     text and the message, on the surfaces they sit on, the active option's included.
// What it CANNOT prove, and the PR's browser check records: no sideways scroll and the rows' real height at 320, 375,
// 768 and 1440 px in both themes (Playwright on local serve.py; screenshots in the PR body).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseCss, decls, exactLayout } from './lib/css_cascade.mjs';
import { pageCss, themeVars, colour, over, ratio } from './lib/contrast.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HTML = fs.readFileSync(process.env.HOME_SEARCH_TEST_HTML || path.join(HERE, '..', 'public', 'index.html'), 'utf8');
const CSS_TEXT = pageCss(HTML);
const RULES = parseCss(CSS_TEXT);
const CANNOT = 'the Home search CSS test cannot read';

// Every class the box draws; a selector naming any of them is watched.
const CLASSES = ['home-search', 'home-q-label', 'home-q', 'home-results', 'home-list', 'home-group', 'home-group-label', 'home-opt', 'home-opt-name', 'home-opt-sub', 'home-msg'];
const watched = sel => CLASSES.some(c => new RegExp(`\\.${c}(?![\\w-])`).test(sel));
const EXPECTED = {
  '|.home-search': { width: '100%', 'max-width': '720px', margin: '4px 0 24px' },
  '|.home-q-label': { display: 'block', margin: '0 0 6px', 'font-size': '13px' },
  '|.home-q': { width: '100%', 'min-width': '0', height: '52px', padding: '0 14px 0 44px', 'font-size': '16px' },
  '|.home-results': { 'margin-top': '8px' },
  '|.home-group': { padding: '4px' },
  '|.home-group-label': { padding: '8px 10px 2px', 'font-size': '11px', 'letter-spacing': '0.04em' },
  '|.home-opt': { display: 'flex', 'flex-direction': 'column', 'justify-content': 'center', gap: '2px', 'min-height': '44px', padding: '6px 10px' },
  '|.home-opt-name': { 'min-width': '0', 'font-size': '15px' },
  '|.home-opt-sub': { 'min-width': '0', 'font-size': '13px' },
  '|.home-msg': { padding: '10px 2px', 'font-size': '14px' },
};

test('exactLayout: the box\'s classes set exactly these layout properties, at every width', () => {
  exactLayout(RULES, { watched, expected: EXPECTED, cannot: CANNOT });
  assert.ok(!RULES.some(r => r.selectors.some(s => watched(s) && /\.home-entr/.test(s))), 'a rule mixes the box with Home\'s options');
});

test('the self-check: a layout property added to a compound selector, or a new media rule, fails loudly', () => {
  const add = extra => parseCss(`${CSS_TEXT}\n${extra}`);
  for (const extra of ['.home-opt.active { position: relative; }', '.home-list { max-height: 300px; }', '@media (max-width: 768px) { .home-q { height: 48px; } }',
    '.home-search .home-q { width: 90%; }', '.home-msg { order: -1; }'])
    assert.throws(() => exactLayout(add(extra), { watched, expected: EXPECTED, cannot: CANNOT }), new RegExp(CANNOT), extra);
});

test('option text and the message wrap instead of pushing the page sideways', () => {
  const val = (sel, prop) => RULES.filter(r => !r.at.length && r.selectors.includes(sel)).flatMap(r => decls(r.body)).filter(d => d.prop === prop).map(d => d.value).pop();
  for (const sel of ['.home-opt-name', '.home-opt-sub']) assert.equal(val(sel, 'overflow-wrap'), 'anywhere', sel);
  assert.equal(val('.home-q::placeholder', 'color'), 'var(--home-q-placeholder)');
  assert.equal(val('.home-q::placeholder', 'opacity'), '1', 'the placeholder colour is dimmed by an opacity the token does not include');
});

test('AA contrast (4.5:1) in both themes: the box, its placeholder, label, headings, options (active too) and the message', () => {
  const colourOf = (sel, prop = 'color') => RULES.filter(r => !r.at.length && r.selectors.includes(sel)).flatMap(r => decls(r.body)).filter(d => d.prop === prop).map(d => d.value).pop();
  for (const theme of ['light', 'dark']) {
    const vars = themeVars(CSS_TEXT, theme);
    assert.ok(vars['--home-q-placeholder'], `${theme}: no --home-q-placeholder`);
    const c = v => colour(v, vars);
    const surface = c('var(--bg-surface)'), body = c('var(--bg-body)'), active = over(c(colourOf('.home-opt.active', 'background')), surface);
    const pairs = [
      ['box text', colourOf('.home-q'), surface],
      ['placeholder', colourOf('.home-q::placeholder'), surface],
      ['label', colourOf('.home-q-label'), body],
      ['section heading', colourOf('.home-group-label'), surface],
      ['option name', colourOf('.home-opt-name'), surface],
      ['option line', colourOf('.home-opt-sub'), surface],
      ['active option name', colourOf('.home-opt-name'), active],
      ['active option line', colourOf('.home-opt-sub'), active],
      ['message', colourOf('.home-msg'), body],
    ];
    for (const [what, fg, bg] of pairs) {
      assert.ok(fg, `${theme}: ${what} sets no colour`);
      const r = ratio(over(c(fg), bg.slice(0, 3)), bg);
      assert.ok(r >= 4.5, `${theme}: ${what} is ${r.toFixed(2)}:1 (AA needs 4.5:1)`);
    }
  }
});
