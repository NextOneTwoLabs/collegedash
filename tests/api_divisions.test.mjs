// /api/v1 serves exactly the published programs, by division (issue #94; plan revision 1's /api/v1 check).
//
//     node --test tests/api_divisions.test.mjs
//
// Through worker.js, against the committed public/ tree, compared with the committed registry:
//   - /api/v1/programs serves exactly the registry's published set (onboarded entries of programs whose
//     division is in onboardedDivisions), division by division. While D3 is staged that is 0 D3 rows; once the
//     switch publishes it (#94 PR 4) it is every published D3 program (411 in the plan), with nothing else to
//     change here;
//   - no held program (heldPrograms), no collectionHold entry and no staged-division entry is served, in the
//     list or by slug (/api/v1/programs/<slug> is 404).
//
// API_DIV_INDEX (optional) is a path to another programs index.json, served in place of the committed one, so a
// deliberately wrong index (a held campus served, a D3 row dropped) can be shown failing through these checks.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import worker from '../worker.js';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const PUBLIC = path.join(ROOT, 'public');
const HOST = 'https://college.nextonetwo.com';
const INDEX_OVERRIDE = process.env.API_DIV_INDEX;
const REGISTRY = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'data/registry.json'), 'utf8'));

const env = {
  FEEDBACK: { put() { } },
  ASSETS: {
    async fetch(req) {
      const rel = decodeURIComponent(new URL(req.url).pathname).replace(/^\//, '');
      const file = INDEX_OVERRIDE && rel === 'data/programs/index.json' ? INDEX_OVERRIDE : path.join(PUBLIC, rel);
      if (!fs.existsSync(file) || !fs.statSync(file).isFile()) return new Response(null, { status: 404 });
      return new Response(fs.readFileSync(file), { status: 200, headers: { 'content-type': 'application/json; charset=utf-8', etag: '"t"' } });
    },
  },
};
const get = (p) => worker.fetch(new Request(HOST + p), env);

// The published set, computed the way build.published_programs() does.
const onboardedDivs = REGISTRY.onboardedDivisions;
const published = REGISTRY.programs.filter((p) => p.onboarded && (!onboardedDivs || onboardedDivs.includes(p.division)));
const bySlug = new Map(published.map((p) => [p.slug, p]));
const neverServed = new Map([
  ...(REGISTRY.heldPrograms || []).map((p) => [p.slug, 'heldPrograms']),
  ...REGISTRY.programs.filter((p) => p.collectionHold).map((p) => [p.slug, 'collectionHold']),
  ...REGISTRY.programs.filter((p) => (REGISTRY.stagedDivisions || []).includes(p.division)).map((p) => [p.slug, `staged ${p.division}`]),
]);
for (const s of bySlug.keys()) neverServed.delete(s);

test('/api/v1/programs serves exactly the published programs, division by division', async () => {
  const res = await get('/api/v1/programs');
  assert.equal(res.status, 200);
  const rows = (await res.json()).programs;
  const count = (list) => list.reduce((m, p) => ({ ...m, [p.division]: (m[p.division] || 0) + 1 }), {});
  const served = count(rows), want = count(published);
  for (const d of ['D1', 'D2', 'D3']) assert.equal(served[d] || 0, want[d] || 0, `${d}: served ${served[d] || 0}, published ${want[d] || 0}`);
  const slugs = new Set(rows.map((r) => r.slug));
  assert.deepEqual([...slugs].filter((s) => !bySlug.has(s)).sort(), [], 'served but not published');
  assert.deepEqual([...bySlug.keys()].filter((s) => !slugs.has(s)).sort(), [], 'published but not served');
  for (const r of rows) assert.equal(r.division, bySlug.get(r.slug).division, `${r.slug} is served under another division`);
  console.log(`# served by division: ${JSON.stringify(served)}; D3 ${onboardedDivs?.includes('D3') ? 'published' : 'staged'}`);
});

test('no held, collectionHold or staged program is served, in the list or by slug', async () => {
  assert.ok(neverServed.size > 0, 'the registry has nothing held or staged to check');
  const rows = (await (await get('/api/v1/programs')).json()).programs;
  const leaked = rows.filter((r) => neverServed.has(r.slug)).map((r) => `${r.slug} (${neverServed.get(r.slug)})`);
  assert.deepEqual(leaked, [], 'served from the list');
  const held = [...neverServed].filter(([, why]) => !why.startsWith('staged'));
  const sample = [...held, ...[...neverServed].filter(([, why]) => why.startsWith('staged')).slice(0, 5)];
  for (const [slug, why] of sample) {
    const res = await get(`/api/v1/programs/${slug}`);
    assert.equal(res.status, 404, `/api/v1/programs/${slug} (${why}) is served`);
  }
});
