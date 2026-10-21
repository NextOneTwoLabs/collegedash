#!/usr/bin/env node
// Before/after evidence for a visible change (issue #502): screenshots and measurements of one page of the
// site, at several widths and in both themes. Run it once against main and once against the branch, then
// compare the two JSON files.
//
//   node .claude/skills/evidence/shots.js --check
//   node .claude/skills/evidence/shots.js BASE_URL OUT_DIR [options]
//   node .claude/skills/evidence/shots.js --compare BEFORE.json AFTER.json
//
// BASE_URL is a local server (python collegedash.py serve --port N -> http://127.0.0.1:N) or the live site
// (https://college.nextonetwo.com; goes through HTTPS_PROXY when that is set, trusting the proxy's CA: see proxyCaArgs). Options:
//   --label NAME      file name prefix and the key in the JSON (default: shot)
//   --route HASH      page to open after BASE_URL (default: #/programs)
//   --cards SELECTOR  what to wait for and measure (default: .grid.cards > .pcard)
//   --widths LIST     viewport widths, comma separated (default: 1280,390)
//   --themes LIST     light,dark (default: both)
//   --zoom LIST       text-only zoom factors, e.g. 1,2 (default: 1). Every font-size is multiplied; widths stay.
//   --card SLUGS      also take a close-up of these cards, e.g. air-force,navy (matches [data-slug])
//   --filters JSON    localStorage cd.filters to seed (default: the unfiltered card view, sorted by name)
//
// What is measured per width/theme/zoom: card count and height min/max, the tallest gap between cards in
// one row, page horizontal scroll (scrollWidth against the window), and contrast inside the cards (WCAG ratio
// of each element's text colour against the colour behind it; text on a gradient or image is counted as
// unmeasured, not guessed). Text (a text node with a letter or digit) is judged at 4.5:1, or 3:1 when large.
// An icon glyph (a text node with no letter or digit, such as the star) is judged at 3:1 (WCAG 1.4.11) and
// reported on its own (contrast.icons), so it never moves the text figures. `worst` lists the lowest ratios
// once per element, foreground and background, with a count. The Inter web font cannot load in this
// sandbox, so text is set in the fallback font: widths are worst-case, and the same on main and the branch.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const DEFAULT_FILTERS = { conf: [], region: [], division: [], sort: 'name', sortDir: null, classYear: [], view: 'cards', moreStats: false, cond: [] };

function loadPlaywright() {
  const tries = [process.env.PLAYWRIGHT_PATH, 'playwright', '/opt/node-tools/node_modules/playwright'].filter(Boolean);
  for (const t of tries) { try { return require(t); } catch { /* try the next */ } }
  console.error(`Playwright not found. Tried: ${tries.join(', ')}. Set PLAYWRIGHT_PATH to the playwright package directory.`);
  process.exit(2);
}

// Chromium does not read the sandbox's CA settings. For the live site (https, through HTTPS_PROXY) trust exactly the proxy's own
// CA by its public-key hash: CD_PROXY_CA, else the agent-proxy CA the sandbox documents. Certificate checking stays on for
// every other certificate. Nothing is added when the file is absent (a normal network trusts normal CAs).
function proxyCaArgs() {
  const file = process.env.CD_PROXY_CA || '/root/.ccr/agent-proxy-ca.crt';
  try {
    const spki = new crypto.X509Certificate(fs.readFileSync(file)).publicKey.export({ type: 'spki', format: 'der' });
    return [`--ignore-certificate-errors-spki-list=${crypto.createHash('sha256').update(spki).digest('base64')}`];
  } catch { return []; }
}

function parseArgs(argv) {
  const o = { _: [], label: 'shot', route: '#/programs', cards: '.grid.cards > .pcard', widths: '1280,390', themes: 'light,dark', zoom: '1', card: '', filters: '' };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--check' || a === '--compare') o[a.slice(2)] = true;
    else if (a.startsWith('--')) { o[a.slice(2)] = argv[++i]; }
    else o._.push(a);
  }
  return o;
}

// ---- measured inside the page -------------------------------------------------------------------------
function measureInPage({ sel }) {
  const cards = [...document.querySelectorAll(sel)];
  const rect = e => e.getBoundingClientRect();
  const hs = cards.map(c => rect(c).height);
  const rows = new Map();
  cards.forEach(c => { const t = Math.round(rect(c).top + scrollY); (rows.get(t) || rows.set(t, []).get(t)).push(rect(c).height); });
  const rowSpread = cards.length ? Math.max(...[...rows.values()].map(v => Math.max(...v) - Math.min(...v))) : 0;

  const px = document.createElement('canvas'); px.width = px.height = 1;
  const g = px.getContext('2d', { willReadFrequently: true });
  const rgba = css => { g.clearRect(0, 0, 1, 1); g.fillStyle = '#000'; g.fillStyle = css; g.fillRect(0, 0, 1, 1); const d = g.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const lum = ([r, gg, b]) => [r, gg, b].map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }).reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const over = (top, under) => top.slice(0, 3).map((v, i) => v * top[3] + under[i] * (1 - top[3]));

  // Colour behind an element: stack the background colours of it and its ancestors until one is opaque.
  // null when something on the way is a gradient or image (it cannot be reduced to one colour).
  const behind = el => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.backgroundImage !== 'none') return null;
      const c = rgba(cs.backgroundColor);
      if (c[3] > 0) layers.push(c);
      if (c[3] >= 1) break;
    }
    let out = [255, 255, 255];
    for (let i = layers.length - 1; i >= 0; i--) out = over(layers[i], [...out, 1]);
    return out;
  };
  const opacityOf = el => { let o = 1; for (let e = el; e; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity); return o; };

  // Two groups, judged separately. Text (a text node with a letter or digit) needs 4.5:1, or 3:1 when large (WCAG 1.4.3).
  // An icon glyph (a text node with no letter or digit, such as the star ☆) is a graphical object and needs 3:1 (WCAG 1.4.11).
  // `worst` keeps one entry per element, foreground and background, with how many times it occurs: 1000 identical stars are one line.
  const group = () => ({ n: 0, unmeasured: 0, below: 0, min: Infinity, seen: new Map() });
  const text = group(), icon = group();
  const own = el => [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').trim();
  const finish = g => ({ n: g.n, unmeasured: g.unmeasured, below: g.below, min: Number.isFinite(g.min) ? g.min : null,
    worst: [...g.seen.values()].sort((a, b) => a.cr - b.cr).slice(0, 5).map(w => ({ ...w, cr: +w.cr.toFixed(2) })) });
  cards.forEach(card => {
    [card, ...card.querySelectorAll('*')].forEach(el => {
      const label = own(el);
      if (!label) return;
      const cs = getComputedStyle(el), r = rect(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || r.width === 0 || r.height === 0) return;
      const g = /[\p{L}\p{N}]/u.test(label) ? text : icon;
      g.n++;
      const bg = behind(el);
      if (!bg) { g.unmeasured++; return; }
      const fg = rgba(cs.color), a = fg[3] * opacityOf(el);
      const ink = over([fg[0], fg[1], fg[2], a], [...bg, 1]);
      const cr = ratio(ink, bg);
      const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight, 10) >= 700;
      const need = g === icon || size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5;
      if (cr < need) g.below++;
      g.min = Math.min(g.min, cr);
      const name = el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : '');
      const fgs = ink.map(Math.round).join(','), bgs = bg.map(Math.round).join(',');
      const key = `${name}|${fgs}|${bgs}`, hit = g.seen.get(key);
      if (hit) hit.count++; else g.seen.set(key, { cr, el: name, text: label.slice(0, 32), fg: fgs, bg: bgs, need, count: 1 });
    });
  });
  const t = finish(text), i = finish(icon);
  return {
    cards: cards.length,
    hMin: cards.length ? Math.min(...hs) : null, hMax: cards.length ? Math.max(...hs) : null, rowSpread,
    innerWidth, scrollWidth: document.documentElement.scrollWidth,
    hScroll: document.documentElement.scrollWidth > innerWidth + 1,
    // texts, unmeasured, belowAA, min and worst are text only; icons are reported apart so a glyph never lowers the text figures.
    contrast: { texts: t.n, unmeasured: t.unmeasured, belowAA: t.below, min: t.min, worst: t.worst,
      icons: { count: i.n, unmeasured: i.unmeasured, below3: i.below, min: i.min, worst: i.worst } },
  };
}

function zoomText(z) {
  const els = [document.documentElement, ...document.querySelectorAll('body, body *')];
  const sizes = els.map(e => parseFloat(getComputedStyle(e).fontSize));
  els.forEach((e, i) => e.style.setProperty('font-size', (sizes[i] * z) + 'px', 'important'));
}

// ---- compare two JSON files -----------------------------------------------------------------------------
function compare(beforeFile, afterFile) {
  const A = JSON.parse(fs.readFileSync(beforeFile, 'utf8')), B = JSON.parse(fs.readFileSync(afterFile, 'utf8'));
  const n = v => v == null ? '-' : (Number.isInteger(v) ? String(v) : v.toFixed(2));
  const rows = [['view', 'metric', 'before', 'after', '']];
  for (const key of Object.keys(A.results)) {
    const a = A.results[key], b = B.results[key];
    if (!b) { rows.push([key, '(missing in after)', '', '', '']); continue; }
    for (const [name, get] of [['cards', r => r.cards], ['card height min', r => r.hMin], ['card height max', r => r.hMax], ['row spread', r => r.rowSpread],
      ['horizontal scroll', r => r.hScroll ? 'YES' : 'no'], ['contrast min', r => r.contrast.min], ['text below AA', r => r.contrast.belowAA], ['text unmeasured', r => r.contrast.unmeasured],
      ['icons below 3:1', r => r.contrast.icons?.below3], ['icon min', r => r.contrast.icons?.min]]) {
      const x = get(a), y = get(b);
      rows.push([key, name, typeof x === 'string' ? x : n(x), typeof y === 'string' ? y : n(y), String(x) === String(y) ? '' : 'changed']);
    }
  }
  console.log(`| ${rows[0].join(' | ')} |\n| --- | --- | ---: | ---: | --- |`);
  rows.slice(1).forEach(r => console.log(`| ${r.join(' | ')} |`));
  console.log(`\n${rows.filter(r => r[4] === 'changed').length} of ${rows.length - 1} measurements changed.`);
}

// ---- main ------------------------------------------------------------------------------------------------
(async () => {
  const o = parseArgs(process.argv.slice(2));
  if (o.compare) return compare(o._[0], o._[1]);
  const { chromium } = loadPlaywright();

  if (o.check) {
    const b = await chromium.launch();
    let pv = 'unknown'; try { pv = require('playwright/package.json').version; } catch { /* version is only informative */ }
    console.log(`Playwright ${pv}, Chromium ${b.version()}`);
    await b.close();
    return;
  }

  const [base, out] = o._;
  if (!base || !out) { console.error('usage: shots.js BASE_URL OUT_DIR [options]   (see the top of this file)'); process.exit(2); }
  fs.mkdirSync(out, { recursive: true });
  const filters = o.filters ? JSON.parse(o.filters) : DEFAULT_FILTERS;
  const launch = {};
  if (/^https:/.test(base) && process.env.HTTPS_PROXY) { launch.proxy = { server: process.env.HTTPS_PROXY }; launch.args = proxyCaArgs(); }
  const browser = await chromium.launch(launch);
  const results = {};
  const url = base.replace(/\/$/, '') + '/' + o.route;

  for (const zoom of o.zoom.split(',').map(Number)) for (const width of o.widths.split(',').map(Number)) for (const theme of o.themes.split(',')) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 1 });
    await ctx.addInitScript(([t, f]) => { try { localStorage.setItem('cd.theme', JSON.stringify(t)); localStorage.setItem('cd.filters', JSON.stringify(f)); } catch { /* storage blocked */ } }, [theme, filters]);
    const page = await ctx.newPage();
    const key = `${width}px ${theme}${zoom !== 1 ? ` zoom${zoom}` : ''}`;
    const stem = `${o.label}-${width}-${theme}${zoom !== 1 ? `-zoom${zoom}` : ''}`;
    try {
      await page.goto(url, { waitUntil: 'load', timeout: 60000 });
      await page.waitForSelector(o.cards, { timeout: 30000 });
      await page.waitForTimeout(500);
      if (zoom !== 1) { await page.evaluate(zoomText, zoom); await page.waitForTimeout(300); }
      results[key] = await page.evaluate(measureInPage, { sel: o.cards });
      await page.screenshot({ path: path.join(out, stem + '.png') });
      for (const slug of o.card.split(',').filter(Boolean)) {
        const loc = page.locator(`${o.cards}[data-slug="${slug}"]`).first();
        await loc.scrollIntoViewIfNeeded(); await page.waitForTimeout(150);
        const box = await loc.boundingBox();
        await page.screenshot({ path: path.join(out, `${stem}-card-${slug}.png`), clip: { x: 0, y: Math.max(0, box.y - 8), width, height: box.height + 16 } });
      }
      const r = results[key];
      console.log(`${o.label} ${key}: cards ${r.cards}, height ${r.hMin}..${r.hMax}, rowSpread ${r.rowSpread}, scrollW ${r.scrollWidth}/${r.innerWidth}${r.hScroll ? ' HORIZONTAL SCROLL' : ''}, ` +
        `text contrast min ${r.contrast.min == null ? '-' : r.contrast.min.toFixed(2)}${r.contrast.worst[0] ? ` (${r.contrast.worst[0].el})` : ''}, below AA ${r.contrast.belowAA}/${r.contrast.texts} (unmeasured ${r.contrast.unmeasured}); ` +
        `icons min ${r.contrast.icons.min == null ? '-' : r.contrast.icons.min.toFixed(2)}${r.contrast.icons.worst[0] ? ` (${r.contrast.icons.worst[0].el})` : ''}, below 3:1 ${r.contrast.icons.below3}/${r.contrast.icons.count} (unmeasured ${r.contrast.icons.unmeasured}) -> ${stem}.png`);
    } catch (e) {
      results[key] = { error: String(e.message).split('\n')[0] };
      console.error(`${o.label} ${key}: FAILED ${results[key].error}`);
      try { await page.screenshot({ path: path.join(out, stem + '-FAILED.png') }); } catch { /* nothing to show */ }
    }
    await ctx.close();
  }
  await browser.close();
  fs.writeFileSync(path.join(out, o.label + '.json'), JSON.stringify({ base, route: o.route, label: o.label, results }, null, 1));
  console.log(`measurements: ${path.join(out, o.label + '.json')}`);
  if (Object.values(results).some(r => r.error)) process.exit(1);
})().catch(e => { console.error(e); process.exit(1); });
