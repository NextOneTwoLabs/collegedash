/* Program recommendations V1: the ranker (issue #400, PR 2 of 8).

   A deterministic, client-side ranker over the program list the page already has, joined by slug with the fit
   file (/api/v1/fit, public/data/fit/index.json, taxonomy "fit-1"). Pure functions only: nothing here touches
   the DOM, storage, the network or the clock, so the same input always gives the byte-identical result.
   The page (PR 3 onwards) loads this as a plain <script> and reads window.CDRecs; Node tests require() it.

   The design is the approved plan on #400 (revision 2, owner decision 2026-09-30):
   - Four categories: region, division, size, climate. Each is skip, prefer or must ("must have"); climate is
     prefer-only (D2), so a must on climate is dropped by validatePrefs with an issue, never reinterpreted.
   - Within a category the chosen values are ORed; across categories, ANDed (the sidebar pills' rule).
   - Must haves are tri-state. A known mismatch on any must excludes the program. Otherwise, an unknown value on
     any must puts it in Need verification. Only a program that passes every must is Confirmed. Unknown is never
     a silent drop and never a pass.
   - Prefer categories score 1 for a match, 0 for a miss and 0 for an unknown, over a FIXED denominator: the
     number of answered prefer categories, the same for every program. An unknown is never taken out of the
     denominator, so sparse data can't earn a perfect score (A3). A passed must is not scored.
   - Order inside each group: matched count descending, then the DISPLAYED name (shortName || name, the string
     the reader sees, compared exactly as the page's Name sort compares it), then slug. Total and stable, so a
     shuffled input gives the same order.
   - The ranker reads only what project() returns: slug, the displayed name, and the fit facts. RPI, THE rank,
     roster, commitments and every other list field never reach it (the "no hidden signals" gate).
   - Region, division and undergraduate enrollment come from the list row, so a card and its reasons cannot
     show two different values; climate and the source ids come from the fit file.
   - Existing sidebar filters are their own layer, passed in as a predicate (the page passes matchesFilters),
     and counted apart from must haves and hidden programs, so the page can say which one emptied the list.

   Layers, in order, each counted: filter -> must haves -> hidden. A hidden program that the filters or a
   must have already remove is counted there, not as hidden. */
(function (root) {
  'use strict';

  const RANKER = 'r1';                 // bump on any change to ordering, scoring, grouping or reason selection
  const PREFS_V = 1;                   // the stored preference format (cd.recs.prefs); migrations land in PR 6
  const TAXONOMIES = ['fit-1'];        // the fit taxonomies this ranker understands
  const CATEGORIES = ['region', 'division', 'size', 'climate'];
  const MODES = { region: ['skip', 'prefer', 'must'], division: ['skip', 'prefer', 'must'],
                  size: ['skip', 'prefer', 'must'], climate: ['skip', 'prefer'] };
  const DIVISIONS = ['D1', 'D2', 'D3'];
  const SIZES = ['lt5k', '5k-15k', 'ge15k'];   // fit-1's half-open bands: <5,000, 5,000-14,999, >=15,000
  const CLIMATES = ['mild', 'four-season', 'cold'];
  const MAX_REASONS = 3;
  const DIVISION_SOURCE = 'NCAA division (program registry)';

  const ENUM_WORDS = {
    size: { lt5k: 'under 5,000 undergraduates', '5k-15k': '5,000–14,999 undergraduates', ge15k: '15,000+ undergraduates' },
    climate: { mild: 'mild winters', 'four-season': 'four seasons', cold: 'cold winters' },
  };
  const UNKNOWN_WHY = {
    'no-school-record': 'no College Scorecard record',
    'no-normals': 'the weather station has no full set of monthly normals',
    'station-distance-unknown': 'the weather station distance is unknown',
    'far-station': 'the nearest weather station is too far away',
    'no-climate-source': 'no weather station data',
    'no-fit-entry': 'no fit data for this program',
  };

  /* ---------- versions and enums ---------- */

  /** The allowed values per category for a fit file's constants. Region values are the taxonomy's own keys. */
  function enums(constants) {
    const regions = constants && constants.regions && typeof constants.regions === 'object' ? Object.keys(constants.regions) : [];
    return { region: regions, division: DIVISIONS, size: SIZES, climate: CLIMATES };
  }

  function defaultPrefs() {
    const p = { v: PREFS_V };
    for (const c of CATEGORIES) p[c] = { mode: 'skip', values: [] };
    return p;
  }

  /** True when at least one category is answered: only then is there anything to recommend by (A4). */
  function isActive(prefs) {
    return !!prefs && CATEGORIES.some(c => prefs[c] && prefs[c].mode !== 'skip');
  }

  /* ---------- preferences ---------- */

  /**
   * Clean a stored or submitted preference object, the way sanitizeConds cleans condition chips: anything not
   * understood is dropped and NAMED in `issues`, never reinterpreted. A category left with no valid value falls
   * back to skip, with an issue. Values come back de-duplicated and in the taxonomy's order.
   *   issues: {kind: 'shape'|'version'|'newer'|'key'|'mode'|'value'|'empty', category?, key?, value?}
   */
  function validatePrefs(raw, constants) {
    const issues = [];
    const prefs = defaultPrefs();
    if (raw === null || raw === undefined) return { prefs, issues };
    if (typeof raw !== 'object' || Array.isArray(raw)) return { prefs, issues: [{ kind: 'shape' }] };
    if (raw.v !== PREFS_V) {
      const newer = typeof raw.v === 'number' && raw.v > PREFS_V;
      return { prefs, issues: [newer ? { kind: 'newer', value: raw.v } : { kind: 'version', value: raw.v === undefined ? null : raw.v }] };
    }
    const allowed = enums(constants);
    for (const key of Object.keys(raw)) {
      if (key !== 'v' && !CATEGORIES.includes(key)) issues.push({ kind: 'key', key });
    }
    for (const c of CATEGORIES) {
      const got = raw[c];
      if (got === undefined) continue;
      if (!got || typeof got !== 'object' || Array.isArray(got)) { issues.push({ kind: 'shape', category: c }); continue; }
      if (!MODES[c].includes(got.mode)) { issues.push({ kind: 'mode', category: c, value: got.mode === undefined ? null : got.mode }); continue; }
      if (got.mode === 'skip') continue;
      if (!Array.isArray(got.values)) { issues.push({ kind: 'shape', category: c }); continue; }
      const keep = new Set();
      for (const v of got.values) {
        if (allowed[c].includes(v)) keep.add(v);
        else issues.push({ kind: 'value', category: c, value: v });
      }
      if (!keep.size) { issues.push({ kind: 'empty', category: c }); continue; }
      prefs[c] = { mode: got.mode, values: allowed[c].filter(v => keep.has(v)) };
    }
    return { prefs, issues };
  }

  /* ---------- the facts ---------- */

  /** fit-1's size band for an undergraduate count: half-open, so 4,999 | 5,000 and 14,999 | 15,000 split (A8). */
  function sizeBand(n, bands) {
    if (typeof n !== 'number' || !Number.isFinite(n) || n < 0 || !Array.isArray(bands) || bands.length !== 2) return null;
    return n < bands[0] ? 'lt5k' : n < bands[1] ? '5k-15k' : 'ge15k';
  }

  /**
   * THE ONLY FIELDS THE RANKER SEES. Everything after this reads the returned object, never the row, so no
   * other list field (RPI, THE rank, roster size, commitments, ...) can move a result.
   */
  function project(row, entry, constants, allowed = enums(constants)) {
    const e = entry && typeof entry === 'object' ? entry : null;
    const n = typeof row.undergradEnrollment === 'number' && Number.isFinite(row.undergradEnrollment) ? row.undergradEnrollment : null;
    const asOf = e && Array.isArray(e.asOf) ? e.asOf : [null, null];
    return {
      slug: row.slug,
      displayName: row.shortName || row.name || '',
      fit: {
        region: allowed.region.includes(row.region) ? row.region : null,
        state: typeof row.state === 'string' && row.state ? row.state : null,
        division: DIVISIONS.includes(row.division) ? row.division : null,
        undergrad: n,
        size: sizeBand(n, constants && constants.sizeBands),
        climate: e && CLIMATES.includes(e.climate) ? e.climate : null,
        climateUnknown: e ? (CLIMATES.includes(e.climate) ? null : (e.climateUnknown || 'no-normals')) : 'no-fit-entry',
        coldMonthMeanF: e && typeof e.coldMonthMeanF === 'number' ? e.coldMonthMeanF : null,
        stationKm: e && typeof e.stationKm === 'number' ? e.stationKm : null,
        unitId: e && Number.isInteger(e.unitId) ? e.unitId : null,
        station: e && typeof e.station === 'string' ? e.station : null,
        asOf: { school: asOf[0] || null, climate: asOf[1] || null },
      },
    };
  }

  /** One category's fact for a projected program: its value (null when unknown), the detail a reason shows, and
   *  where it comes from. */
  function fact(p, category, sources, school) {
    const f = p.fit;
    if (category === 'region') return { value: f.region, detail: { state: f.state }, source: school || schoolSource(f, sources), why: f.region ? null : 'no-school-record' };
    if (category === 'division') return { value: f.division, detail: {}, source: { name: DIVISION_SOURCE, asOf: null }, why: f.division ? null : 'no-division' };
    if (category === 'size') return { value: f.size, detail: { undergrad: f.undergrad }, source: school || schoolSource(f, sources), why: f.size ? null : 'no-school-record' };
    return { value: f.climate, detail: { coldMonthMeanF: f.coldMonthMeanF, stationKm: f.stationKm }, source: climateSource(f, sources),
             why: f.climate ? null : f.climateUnknown };
  }
  const schoolSource = (f, sources) => ({ name: (sources && sources.school && sources.school.name) || 'College Scorecard',
                                          asOf: f.asOf.school, unitId: f.unitId });
  const climateSource = (f, sources) => ({ name: (sources && sources.climate && sources.climate.name) || 'NOAA NCEI U.S. Climate Normals',
                                           asOf: f.asOf.climate, station: f.station });

  /**
   * One contribution per answered category: {category, mode, outcome: match|miss|unknown, value, wanted, detail,
   * source, why}. Everything a reason, a tradeoff or an unknown chip says is built from these and nothing else.
   */
  /** The four facts of a projected program, in category order; region and size share one source object. */
  function factsOf(p, sources) {
    const school = schoolSource(p.fit, sources);
    return CATEGORIES.map(c => fact(p, c, sources, school));
  }

  function contributions(p, prefs, sources, facts = factsOf(p, sources)) {
    const out = [];
    for (let i = 0; i < CATEGORIES.length; i++) {
      const c = CATEGORIES[i], q = prefs[c];
      if (!q || q.mode === 'skip') continue;
      const ft = facts[i];
      const outcome = ft.value === null ? 'unknown' : q.values.includes(ft.value) ? 'match' : 'miss';
      out.push({ category: c, mode: q.mode, outcome, value: ft.value, wanted: q.values, detail: ft.detail, source: ft.source,
                 why: outcome === 'unknown' ? ft.why : null });
    }
    return out;
  }

  /** Tri-state must haves: any known miss -> fail; else any unknown -> unknown; else pass. */
  function mustHave(contribs) {
    const perCategory = {};
    let fail = false, unknown = false;
    for (const k of contribs) {
      if (k.mode !== 'must') continue;
      const s = k.outcome === 'match' ? 'pass' : k.outcome === 'miss' ? 'fail' : 'unknown';
      perCategory[k.category] = s;
      if (s === 'fail') fail = true;
      if (s === 'unknown') unknown = true;
    }
    return { state: fail ? 'fail' : unknown ? 'unknown' : 'pass', perCategory };
  }

  /** Fixed-denominator score: matched prefer categories over ALL answered prefer categories. */
  function score(contribs) {
    let matched = 0, of = 0;
    for (const k of contribs) {
      if (k.mode !== 'prefer') continue;
      of += 1;
      if (k.outcome === 'match') matched += 1;
    }
    return { matched, of, score: of ? matched / of : 0 };
  }

  /* ---------- reasons ---------- */

  // #492 (owner): a size reason names the bracket the program card shows, not the exact count. These edges and names are
  // a copy of public/index.html's UNDERGRAD_EDGES / UNDERGRAD_SIZES (tests/card_brackets.test.mjs fails if they drift).
  const BRACKET_EDGES = [2000, 5000, 15000, 30000];
  const BRACKETS = [['Very small', 'under 2K'], ['Small', '2K–5K'], ['Medium', '5K–15K'], ['Large', '15K–30K'], ['Very large', '30K+']];
  function sizeBracketText(n) {
    const i = BRACKET_EDGES.filter(e => n >= e).length;
    return `${BRACKETS[i][0]} (${BRACKETS[i][1]})`;
  }
  function valueText(k) {
    if (k.category === 'region') return `${k.value} region${k.detail.state ? ` (${k.detail.state})` : ''}`;
    if (k.category === 'division') return k.value;
    if (k.category === 'size') return sizeBracketText(k.detail.undergrad);
    // D2 (owner): the label always comes with the figure it was taken from AND the station distance.
    const w = ENUM_WORDS.climate[k.value];
    return `${w[0].toUpperCase()}${w.slice(1)}: coldest month averages ${k.detail.coldMonthMeanF}°F${stationText(k.detail.stationKm)}`;
  }
  const stationText = km => (typeof km === 'number' ? ` (weather station ${km} km away)` : '');
  function wantedText(k) {
    const words = k.wanted.map(v => (ENUM_WORDS[k.category] && ENUM_WORDS[k.category][v]) || v);
    return words.length > 1 ? `${words.slice(0, -1).join(', ')} or ${words[words.length - 1]}` : words[0];
  }
  const CATEGORY_WORDS = { region: 'Region', division: 'Division', size: 'Size', climate: 'Climate' };

  /**
   * At most three reasons (matched prefers first, then passed musts; shown in category order), one tradeoff (the
   * first known prefer miss) and every unknown. A reason or tradeoff is never built from an unknown, and a
   * program with no match gets no reason at all (it is not claimed as a match).
   */
  function reasons(contribs) {
    // Each reason, the tradeoff and each unknown IS one of the contributions (the same object, not a copy), so
    // nothing can be said that the contributions don't say. contribs are in category order.
    const rs = [];
    let prefer = 0;
    for (const k of contribs) if (k.mode === 'prefer' && k.outcome === 'match') prefer += 1;
    let mustRoom = MAX_REASONS - Math.min(prefer, MAX_REASONS), preferRoom = MAX_REASONS;
    let tradeoff = null;
    const unknowns = [];
    for (const k of contribs) {
      if (k.outcome === 'match') {
        if (k.mode === 'prefer' && preferRoom > 0) { rs.push(k); preferRoom -= 1; }
        else if (k.mode === 'must' && mustRoom > 0) { rs.push(k); mustRoom -= 1; }
      } else if (k.outcome === 'miss') {
        if (!tradeoff && k.mode === 'prefer') tradeoff = k;
      } else {
        unknowns.push(k);
      }
    }
    return { reasons: rs, tradeoff, unknowns };
  }

  /* The words, built at render time for the cards on screen (building them for every program on every rerank
     was most of the ranker's time), and only from the reason, tradeoff or unknown object itself. */
  const reasonText = r => valueText(r);
  const tradeoffText = t => `${valueText(t)}; you preferred ${wantedText(t)}`;
  const unknownText = u => (u.why === 'far-station' && typeof u.detail?.stationKm === 'number'
    ? `Climate unknown: the nearest weather station is ${u.detail.stationKm} km away, too far to label`
    : `${CATEGORY_WORDS[u.category]} unknown: ${UNKNOWN_WHY[u.why] || 'no data'}`);

  /* ---------- order ---------- */

  let collators = null;
  function nameCompare(x, y) {
    // The page's byDisplayName: case-insensitive first, then exact, so the order is total. Collators are built
    // once (localeCompare with options builds one per call, which is most of a sort's time).
    if (!collators) collators = [new Intl.Collator(undefined, { sensitivity: 'accent' }), new Intl.Collator()];
    return collators[0].compare(x, y) || collators[1].compare(x, y);
  }
  const bySlug = (a, b) => (a.slug < b.slug ? -1 : a.slug > b.slug ? 1 : 0);
  /** Matched count descending, then displayed name, then slug: a total order, so ties are stable (A8). This is
   *  THE definition; rank() gets the same order without sorting (see nameOrderOf), and tests hold the two equal
   *  on every scenario and every random preference set. */
  function compareRanked(a, b) {
    return (b.matched - a.matched) || nameCompare(a.displayName, b.displayName) || bySlug(a, b);
  }

  /* Every program's place in name-then-slug order (compareRanked's tie order), worked out once per list array and
     remembered: a rerank then walks the list in this order and drops each program into a bucket by its matched
     count, which yields compareRanked's order with no sort at all. Reused only while every row still has the same
     slug and the same displayed name, so editing a row in place can't leave a stale order behind. */
  const nameOrders = typeof WeakMap === 'function' ? new WeakMap() : null;
  function nameOrderOf(programs) {
    const cached = nameOrders && nameOrders.get(programs);
    if (cached && cached.slugs.length === programs.length) {
      let same = true;
      for (let i = 0; i < programs.length && same; i++) {
        const r = programs[i];
        same = cached.slugs[i] === r.slug && cached.names[i] === (r.shortName || r.name || '');
      }
      if (same) return cached;
    }
    const names = programs.map(r => r.shortName || r.name || ''), slugs = programs.map(r => r.slug);
    const idx = programs.map((_, i) => i)
      .sort((a, b) => nameCompare(names[a], names[b]) || (slugs[a] < slugs[b] ? -1 : slugs[a] > slugs[b] ? 1 : 0));
    const rec = { names, slugs, idx };
    if (nameOrders) nameOrders.set(programs, rec);
    return rec;
  }
  /** slug -> position in name-then-slug order. */
  function nameOrder(programs) {
    const { idx, slugs } = nameOrderOf(programs);
    return new Map(idx.map((i, k) => [slugs[i], k]));
  }

  /* ---------- layers ---------- */

  /** The sidebar's filters as their own layer. `filter` is a predicate over the LIST row (the page's matchesFilters). */
  function applyFilters(rows, filter) {
    if (typeof filter !== 'function') return { rows: rows.slice(), filteredOut: 0 };
    const kept = rows.filter(r => filter(r));
    return { rows: kept, filteredOut: rows.length - kept.length };
  }

  const hiddenSlugs = hidden => new Set((Array.isArray(hidden) ? hidden : [])
    .map(h => (typeof h === 'string' ? h : h && typeof h.slug === 'string' ? h.slug : null)).filter(Boolean));

  /** Split evaluated programs by the hidden list. */
  function applyHidden(items, hidden) {
    const set = hiddenSlugs(hidden);
    const rows = [], hiddenRows = [];
    for (const it of items) (set.has(it.slug) ? hiddenRows : rows).push(it);
    return { rows, hiddenRows };
  }

  /** Confirmed and Need verification, each in rank order (compareRanked). */
  function group(items) {
    const confirmed = [], needVerification = [];
    for (const it of items) (it.mustHave === 'pass' ? confirmed : needVerification).push(it);
    return { confirmed: confirmed.sort(compareRanked), needVerification: needVerification.sort(compareRanked) };
  }

  function item(p, contribs, mustState) {
    const s = score(contribs);
    const r = reasons(contribs);
    const f = p.fit;
    const known = (f.region !== null) + (f.division !== null) + (f.size !== null) + (f.climate !== null);
    return { slug: p.slug, displayName: p.displayName, matched: s.matched, of: s.of, score: s.score, mustHave: mustState,
             reasons: r.reasons, tradeoff: r.tradeoff, unknowns: r.unknowns, coverage: { known, of: CATEGORIES.length } };
  }
  /** One projected program against cleaned preferences: the result item (must state 'pass', 'unknown' or 'fail'). */
  function evaluate(p, prefs, sources) {
    const contribs = contributions(p, prefs, sources);
    return item(p, contribs, mustHave(contribs).state);
  }

  /**
   * Rank the catalog.
   *   list    {updated, programs: [list rows]}       the page's program list
   *   fit     the fit file: {updated, fitTaxonomy, constants, sources, fit: {slug: entry}}
   *   prefs   raw preferences; validated here, and every dropped part is reported in `issues`
   *   filter  predicate over a list row (the sidebar's matchesFilters), or null for none
   *   hidden  hidden slugs, or [{slug, ...}] as stored
   * Returns the versioned result. Nothing is ranked when the taxonomy is unknown or the two files come from
   * different builds (`error`), or when no category is answered (`active: false`).
   */
  function rank({ list, fit, prefs, filter = null, hidden = [] } = {}) {
    const base = { v: 1, ranker: RANKER, taxonomy: fit && fit.fitTaxonomy || null, catalog: list && list.updated || null };
    if (!list || !Array.isArray(list.programs) || !fit || !fit.fit || typeof fit.fit !== 'object') return { ...base, error: 'catalog' };
    if (!TAXONOMIES.includes(fit.fitTaxonomy)) return { ...base, error: 'taxonomy' };
    if (fit.updated !== list.updated) return { ...base, error: 'mismatch' };
    const seen = new Set();
    for (const r of list.programs) { if (!r || typeof r.slug !== 'string' || seen.has(r.slug)) return { ...base, error: 'catalog' }; seen.add(r.slug); }

    const { prefs: clean, issues } = validatePrefs(prefs, fit.constants);
    const set = hiddenSlugs(hidden);
    const staleHidden = [...set].filter(s => !seen.has(s)).sort();
    const empty = { confirmed: [], needVerification: [], hiddenRows: [],
                    excluded: { byFilter: 0, byMustHave: 0, hidden: 0, byMustHaveCategory: {} } };
    if (!isActive(clean)) return { ...base, active: false, prefs: clean, issues, total: list.programs.length, ...empty, staleHidden };

    // One pass over the list in name-then-slug order: the filter layer, then must haves, then hidden, each counted.
    // applyFilters, mustHave, applyHidden and group are the same rules, exported for tests; they are inlined here
    // so a rerank sorts nothing and builds nothing for an excluded program.
    const programs = list.programs, allowed = enums(fit.constants);
    const byMustHaveCategory = {};
    for (const c of CATEGORIES) if (clean[c].mode === 'must') byMustHaveCategory[c] = 0;
    const top = CATEGORIES.length;
    const cBuckets = [], nBuckets = [];
    for (let m = 0; m <= top; m++) { cBuckets.push([]); nBuckets.push([]); }
    const hiddenRows = [];
    let filteredOut = 0, byMustHave = 0;
    for (const i of nameOrderOf(programs).idx) {
      const row = programs[i];
      if (typeof filter === 'function' && !filter(row)) { filteredOut += 1; continue; }
      const p = project(row, fit.fit[row.slug], fit.constants, allowed);
      const contribs = contributions(p, clean, fit.sources);
      let fail = false, unknown = false;
      for (let j = 0; j < contribs.length; j++) {
        const k = contribs[j];
        if (k.mode !== 'must') continue;
        if (k.outcome === 'miss') { fail = true; byMustHaveCategory[k.category] += 1; }
        else if (k.outcome === 'unknown') unknown = true;
      }
      if (fail) { byMustHave += 1; continue; }
      if (set.has(row.slug)) { hiddenRows.push(row.slug); continue; }
      const it = item(p, contribs, unknown ? 'unknown' : 'pass');
      (unknown ? nBuckets : cBuckets)[it.matched].push(it);
    }
    const confirmed = [], needVerification = [];
    for (let m = top; m >= 0; m--) { for (const it of cBuckets[m]) confirmed.push(it); for (const it of nBuckets[m]) needVerification.push(it); }
    hiddenRows.sort();
    return { ...base, active: true, prefs: clean, issues, total: list.programs.length, confirmed, needVerification,
             hiddenRows, excluded: { byFilter: filteredOut, byMustHave, hidden: hiddenRows.length, byMustHaveCategory }, staleHidden };
  }

  /* ---------- the saved document (cd.recs) and its migrations ---------- */

  const DOC_V = 1;   // the cd.recs format: {v: 1, prefs, hidden?, notices?, applied?}
  /* One step per version: MIGRATIONS[k] turns a version-k document into version k + 1, or returns null when it can't.
     Pure, never throws. v0 is the shape before cd.recs carried a version: a bare preference set ({region: …, …}) or
     {prefs} with no v. A later format adds MIGRATIONS[1], and so on; nothing is ever skipped. */
  const MIGRATIONS = Object.freeze({
    0(doc) {
      const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
      const isObj = x => !!x && typeof x === 'object' && !Array.isArray(x);
      if (isObj(doc.prefs)) {
        const rest = {};
        for (const k of Object.keys(doc)) if (k !== 'prefs' && k !== 'v') rest[k] = doc[k];
        return { ...rest, v: 1, prefs: { ...doc.prefs, v: 1 } };
      }
      if (!CATEGORIES.some(c => own(doc, c))) return null;
      const prefs = { v: 1 };
      for (const c of CATEGORIES) if (own(doc, c)) prefs[c] = doc[c];
      return { v: 1, prefs };
    },
  });
  /**
   * Bring a parsed cd.recs document to the current version.
   *   {status: 'current'|'migrated', doc, from}   doc is version DOC_V
   *   {status: 'newer', from}                      a later page wrote it: leave it untouched
   *   {status: 'unreadable'}                       not an object, a bad version, or a step that couldn't apply
   */
  function migrateDoc(doc, migrations = MIGRATIONS) {
    if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return { status: 'unreadable' };
    const from = doc.v === undefined ? 0 : doc.v;
    if (!Number.isInteger(from) || from < 0) return { status: 'unreadable' };
    if (from > DOC_V) return { status: 'newer', from };
    let d = doc;
    for (let v = from; v < DOC_V; v++) {
      const step = migrations[v];
      d = typeof step === 'function' ? step(d) : null;
      if (!d || d.v !== v + 1) return { status: 'unreadable' };
    }
    return { status: from === DOC_V ? 'current' : 'migrated', doc: d, from };
  }

  /* ---------- staleness ---------- */

  /** What a saved `applied` stamp records: the versions a result was computed under. */
  function stamp(result) {
    return { taxonomy: result.taxonomy, ranker: result.ranker, catalog: result.catalog };
  }
  /** Which versions changed since `applied` (empty when none): the page recomputes and says so, never shows old results. */
  function staleness(applied, current) {
    if (!applied || typeof applied !== 'object') return ['taxonomy', 'ranker', 'catalog'];
    return ['taxonomy', 'ranker', 'catalog'].filter(k => applied[k] !== current[k]);
  }

  const API = Object.freeze({
    RANKER, PREFS_V, TAXONOMIES, CATEGORIES, MODES, DIVISIONS, SIZES, CLIMATES, MAX_REASONS,
    enums, defaultPrefs, isActive, validatePrefs, sizeBand, project, fact, contributions, mustHave, score, reasons,
    reasonText, tradeoffText, unknownText, sizeBracketText,
    compareRanked, nameOrder, applyFilters, applyHidden, group, evaluate, rank, stamp, staleness, DOC_V, MIGRATIONS, migrateDoc,
  });
  if (typeof module === 'object' && module && module.exports) module.exports = API;
  else root.CDRecs = API;
})(typeof globalThis !== 'undefined' ? globalThis : this);
