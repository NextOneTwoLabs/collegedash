// Entry point for the deployed Worker. The site itself is the static files in public/ (see
// [assets] in wrangler.toml). This script does three things and runs ahead of the static assets
// only for "/" and "/api/*" (run_worker_first in wrangler.toml), so every other file is served as
// a free static asset:
//
//   1. Sends the workers.dev address to the canonical custom domain. Browsers carry the #fragment
//      across a redirect, so deep links such as #/p/stanford/roster still land on the right page.
//   2. Answers GET /api/status with {"local":false}. The local dev server (serve.py) answers true;
//      the front end uses it to decide whether write actions are available. Before this existed
//      the request 404'd and logged a console error on every page load (issue #11).
//   3. Accepts footer feedback at POST /api/feedback and stores it in the FEEDBACK KV namespace,
//      one key per submission. Stored: when it was sent, the message, the reply email if the
//      visitor gave one, and which page they were on. No IP, no user agent.
//
// Nothing here echoes a submission back to the client, and nothing renders one into the site.
const CANONICAL_HOST = 'college.nextonetwo.com';
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// Matches the textarea's maxlength in public/index.html; both count UTF-16 code units.
const MAX_MESSAGE = 2000;
// The hash route the visitor was on, e.g. "#/p/stanford/roster", and the program slug when the
// page had one. This site has 350 program pages, so the page is the difference between an
// actionable report and a vague one.
const MAX_ROUTE = 200;
const SLUG = /^[a-z0-9-]{1,64}$/;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // /api/* is routed before the workers.dev redirect below: a 301 is downgraded to GET by most
    // clients, so redirecting a POST would silently turn a submission into a page view.
    if (url.pathname === '/api/status') return Response.json({ local: false });
    if (url.pathname === '/api/feedback') return feedback(request, env);

    if (url.hostname.endsWith('.workers.dev')) {
      url.hostname = CANONICAL_HOST;
      return Response.redirect(url.toString(), 301);
    }
    return env.ASSETS.fetch(request);
  },
};

async function feedback(request, env) {
  if (request.method !== 'POST') {
    return new Response('Method not allowed', { status: 405, headers: { allow: 'POST' } });
  }

  // The page is a JavaScript-rendered single-page app, so its script is the only caller there can
  // be and JSON is the only encoding to support.
  let body = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }
  // JSON.parse can return null or a scalar; neither can be dereferenced below.
  if (!body || typeof body !== 'object') body = {};

  const reply = (status, error) =>
    Response.json(error ? { ok: false, error } : { ok: true }, { status });

  // Honeypot: real visitors never see the "website" field. Pretend it worked and store nothing.
  if (body.website) return reply(200);

  const message = String(body.message || '').trim();
  if (!message) return reply(400, 'Please add a message.');
  if (message.length > MAX_MESSAGE) return reply(400, 'Please keep it under 2,000 characters.');

  // The email is optional, so it is only checked when the visitor gave one.
  const email = String(body.email || '').trim().toLowerCase();
  if (email && (!EMAIL.test(email) || email.length > 254)) {
    return reply(400, 'Please enter a valid email address.');
  }

  // Context, both capped and both dropped silently if they do not fit the shape: they are a
  // convenience for triage, never a reason to refuse a submission.
  const route = String(body.route || '').trim().slice(0, MAX_ROUTE);
  const slug = String(body.program || '').trim();
  const program = SLUG.test(slug) ? slug : '';

  // Fail closed on a missing binding rather than throwing into the router: "/" is
  // run_worker_first, so an uncaught error here would break the home page for everyone.
  if (!env.FEEDBACK) return reply(503, 'Feedback is unavailable right now.');

  // One key per submission. The email cannot be the key: it is optional and not unique. The ISO
  // timestamp makes `kv key list` come back in chronological order and readable by eye; the random
  // suffix keeps two submissions in the same millisecond apart. Repeating the email and the route
  // as metadata lets a listing show the context and whether there is a reply address without
  // fetching every record.
  const suffix = [...crypto.getRandomValues(new Uint8Array(4))]
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
  const record = { sent: new Date().toISOString(), message };
  if (email) record.email = email;
  if (route) record.route = route;
  if (program) record.program = program;
  await env.FEEDBACK.put(`${record.sent}-${suffix}`, JSON.stringify(record), {
    metadata: { email: email || null, route: route || null },
  });
  return reply(200);
}
