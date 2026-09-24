"""Harness for .github/workflows/onboard.yml and .github/scripts/onboard_batch.py (issue #242).

    python tests/onboard_workflow_test.py            # every case
    python tests/onboard_workflow_test.py --verbose  # print every check, not only the failures

Nothing here touches the network, this repository's data, or any remote. The workflow is read as text (no
YAML library: the data refresh does not install one), its shell steps are extracted verbatim and run under
`bash -eo pipefail` - the way Actions runs a `run:` block - inside scratch repositories under a temporary
directory, with a bare "origin" standing in for GitHub.

Cases:
  shape            dispatch-only; the refresh-data concurrency group, shared with refresh.yml, never cancelled;
                   contents: write and nothing more; job and collect timeouts under the 360-minute limit;
                   checks out main and switches to the batch branch before planning or collecting
  inputs-in-env    no `${{ }}` inside any run block: every dispatch input reaches the shell through env
  never-main       every `git push` targets refs/heads/$BRANCH or its fallback, never main, never forced;
                   nothing merges; both shell guards refuse a branch outside onboard/
  politeness       the workflow sets no User-Agent, gap, worker or offline override; `run` calls the real
                   onboard with --no-bios and passes --collect-staged-divisions only for a staged division
  inputs           name/plan: division shape, empty list items, bad slugs, unknown conference or slug, a
                   slug in another division, nothing named, a bad batch_name, a batch over the cap
  plan             a division neither staged nor published is refused (D3 before #190); staged adds
                   --collect-staged-divisions, published does not; a conference takes only programs not yet
                   onboarded; an explicit slug is taken even when onboarded; held entries are left out and named
  shipped-registry against public/data/registry.json as it is: the PSAC is all onboarded or held (#199), so
                   planning it is refused with each held campus named
  host-stop        through the real collect.common transport, against two local HTTP servers: after a host's
                   first 403 (or 429) nothing more is sent to it, other hosts are unaffected, each hit is
                   attributed to the program collecting; --no-network sends nothing at all
  host-stop-concurrent  many threads at once against one always-403 and one always-429 host (PR #245 review):
                   each host receives exactly one request, however many threads were already queued at its gate
  summary          rows (roster, schedule, staff), failures, not-run collectors, 403/429 hosts, skipReason, and
                   the registry guard: `onboarded` flipped outside the plan or its division, or a division list
                   changed, exits 3
  commit-*         the Prepare and Commit steps against a scratch origin: a new branch off main; an existing
                   branch continued; only the batch's own paths committed; dry run pushes nothing; a failed
                   summary pushes nothing; a moved branch falls back to onboard/<name>-run-*; main never moves
"""

from __future__ import annotations

import argparse
import contextlib
import http.server
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YML = os.environ.get("ONBOARD_YML") or os.path.join(ROOT, ".github", "workflows", "onboard.yml")
REFRESH_YML = os.path.join(ROOT, ".github", "workflows", "refresh.yml")
# ONBOARD_BATCH_HELPER runs these checks against another copy of the helper (to show a check failing on old code)
HELPER = os.environ.get("ONBOARD_BATCH_HELPER") or os.path.join(ROOT, ".github", "scripts", "onboard_batch.py")
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location("onboard_batch", HELPER)
ob = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ob)

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond, detail="") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


# ---------- the workflow as text ----------

TEXT = open(YML, encoding="utf-8").read()
LINES = TEXT.splitlines()


def top_block(key: str) -> list[str]:
    """The lines under a top-level `key:`, up to the next top-level key."""
    start = next(i for i, l in enumerate(LINES) if re.match(rf"^{re.escape(key)}:\s*$", l))
    out = []
    for l in LINES[start + 1:]:
        if l and not l.startswith(" ") and not l.startswith("#"):
            break
        out.append(l)
    return out


def steps() -> list[dict]:
    """[{name, uses, lines}] for the job's steps, in order."""
    out, cur = [], None
    for l in LINES:
        m = re.match(r"^      - (name|uses|run):\s*(.*)$", l)
        if m:
            cur = {"name": m.group(2) if m.group(1) == "name" else "", "uses": m.group(2) if m.group(1) == "uses" else "",
                   "lines": [l]}
            out.append(cur)
        elif cur is not None and (l.startswith("        ") or not l.strip()):
            cur["lines"].append(l)
            m2 = re.match(r"^        uses:\s*(.*)$", l)
            if m2:
                cur["uses"] = m2.group(1)
    return out


def run_block(step_lines: list[str]) -> str:
    """A step's `run: |` block, dedented exactly as YAML's literal block scalar does."""
    idx = next((i for i, l in enumerate(step_lines) if re.match(r"^\s*(- )?run: \|\s*$", l)), None)
    if idx is None:
        m = next((re.match(r"^\s*(- )?run: (.+)$", l) for l in step_lines if re.match(r"^\s*(- )?run: (.+)$", l)), None)
        return (m.group(2) + "\n") if m else ""
    body, indent = [], None
    for l in step_lines[idx + 1:]:
        if l.strip() == "":
            body.append("")
            continue
        lead = len(l) - len(l.lstrip(" "))
        if indent is None:
            indent = lead
        if lead < indent:
            break
        body.append(l[indent:])
    while body and body[-1] == "":
        body.pop()
    return "\n".join(body) + "\n"


def step(name: str) -> dict:
    return next(s for s in steps() if s["name"] == name)


def test_shape():
    print("shape: dispatch-only, shared concurrency group, permissions, timeouts, branch before collect")
    on = [l for l in top_block("on") if l.strip() and not l.strip().startswith("#")]
    triggers = [l.strip().rstrip(":") for l in on if re.match(r"^  \S", l)]
    ok("the only trigger is workflow_dispatch", triggers == ["workflow_dispatch"], triggers)
    ok("no schedule, push, pull_request or workflow_run anywhere in `on`",
       not any(re.match(r"^\s+-?\s*(schedule|push|pull_request|pull_request_target|workflow_run|cron|repository_dispatch)\s*:", l)
               for l in on), on)
    conc = "\n".join(top_block("concurrency"))
    ok("concurrency group is refresh-data", re.search(r"^\s+group:\s*refresh-data\s*$", conc, re.M), conc)
    ok("cancel-in-progress is false", re.search(r"^\s+cancel-in-progress:\s*false\s*$", conc, re.M), conc)
    refresh = open(REFRESH_YML, encoding="utf-8").read()
    ok("refresh.yml uses the same group, so the two never run at once",
       re.search(r"^concurrency:\s*\n\s+group:\s*refresh-data\s*$", refresh, re.M))
    perms = [l.strip() for l in top_block("permissions") if l.strip() and not l.strip().startswith("#")]
    ok("permissions are contents: write and nothing else", perms == ["contents: write"], perms)
    job_t = re.search(r"^    timeout-minutes:\s*(\d+)\s*$", TEXT, re.M)
    ok("the job has a timeout under the 360-minute limit", job_t and int(job_t.group(1)) < 360, job_t and job_t.group(0))
    col = "\n".join(step("Collect")["lines"])
    col_t = re.search(r"timeout-minutes:\s*(\d+)", col)
    ok("the collect step has its own, shorter timeout, leaving time to summarise and commit",
       col_t and job_t and int(col_t.group(1)) <= int(job_t.group(1)) - 30, col_t and col_t.group(0))
    ok("the collect step continues on error, so a partial collection is still committed",
       re.search(r"continue-on-error:\s*true", col))
    names = [s["name"] or s["uses"] for s in steps()]
    co = next(s for s in steps() if s["uses"].startswith("actions/checkout@"))
    ok("checkout is of main, by name", re.search(r"^\s+ref:\s*main\s*$", "\n".join(co["lines"]), re.M), co["lines"])
    ok("checkout does not persist the token in .git/config (PR #245 review)",
       re.search(r"^\s+persist-credentials:\s*false\s*$", "\n".join(co["lines"]), re.M), co["lines"])
    token_steps = [s["name"] or s["uses"] for s in steps() if re.search(r"github\.token|secrets\.GITHUB_TOKEN", "\n".join(s["lines"]))]
    ok("the token is handed only to the commit step, whose push uses it", token_steps == ["Commit to the batch branch"], token_steps)
    ok("the token reaches git only as a -c option on the push",
       'auth=(-c "http.https://github.com/.extraheader=AUTHORIZATION: basic' in run_block(step("Commit to the batch branch")["lines"]))
    order = [names.index(n) for n in ("Name the batch", "Prepare the batch branch", "Plan the batch", "Collect",
                                       "Summarize the batch", "Commit to the batch branch")]
    ok("the branch is prepared before the plan and the collection, and the commit comes last", order == sorted(order), names)
    for n in ("Summarize the batch", "Commit to the batch branch"):
        ok(f"'{n}' runs after a failed collect, but only once a plan exists",
           "if: always() && steps.plan.outcome == 'success'" in "\n".join(step(n)["lines"]))
    for n in ("division", "conferences", "slugs", "batch_name", "dry_run"):
        ok(f"input {n} is declared", re.search(rf"^      {n}:\s*$", TEXT, re.M))
    ok("division is required", re.search(r"^      division:\s*\n(?:        .*\n)*?        required: true", TEXT, re.M))
    ok("dry_run is a boolean defaulting to false",
       re.search(r"^      dry_run:\s*\n(?:        .*\n)*?        type: boolean\s*\n        default: false", TEXT, re.M))


def test_inputs_in_env():
    print("inputs-in-env: nothing interpolated into a shell line")
    for s in steps():
        body = run_block(s["lines"])
        if body:
            ok(f"no ${{{{ }}}} in the run block of '{s['name'] or s['uses']}'", "${{" not in body, body[:300])
    ok("github.event.inputs is not used at all (inputs.* in env only)", "github.event.inputs" not in TEXT)


def test_never_main():
    print("never-main: pushes only to onboard/, never forced, nothing merged")
    pushes = [l.strip() for l in TEXT.splitlines() if re.search(r"\bgit\b.*\bpush\b", l) and not l.strip().startswith("#")]
    ok("there is at least one push to check", len(pushes) >= 2, pushes)
    for p in pushes:
        ok(f"push targets the batch branch or its fallback: {p[:80]}",
           re.search(r'git (?:"\$\{auth\[@\]\}" )?push origin "HEAD:refs/heads/\$(BRANCH|fallback)"', p), p)
        ok(f"push does not name main: {p[:60]}", "main" not in p, p)
        ok(f"push is not forced: {p[:60]}", not re.search(r"(--force|\s-f\b|\+HEAD|\+refs)", p), p)
    ok("nothing merges or opens a PR from the workflow", not re.search(r"\bgit merge\b|\bgh pr\b|pulls", TEXT))
    commit = run_block(step("Commit to the batch branch")["lines"])
    ok("the fallback branch is still under the batch branch's name", 'fallback="$BRANCH-run-' in commit, commit[:200])
    for n in ("Prepare the batch branch", "Commit to the batch branch"):
        ok(f"'{n}' refuses a branch outside onboard/", "onboard/?*) ;;" in run_block(step(n)["lines"]))
    ok("the commit step checks the checkout is on the batch branch", 'git rev-parse --abbrev-ref HEAD)" != "$BRANCH"' in commit)
    ok("the branch name comes from the name step (the helper's validated output)",
       "BRANCH: ${{ steps.name.outputs.branch }}" in "\n".join(step("Commit to the batch branch")["lines"]))


def test_politeness():
    print("politeness: nothing overridden, the real onboard command")
    ok("the workflow sets no User-Agent", not re.search(r"user.?agent", TEXT, re.I) or
       all(l.strip().startswith("#") for l in TEXT.splitlines() if re.search(r"user.?agent", l, re.I)))
    for var in ("COLLEGEDASH_MIN_GAP", "COLLEGEDASH_WORKERS", "COLLEGEDASH_OFFLINE", "HTTP_PROXY", "HTTPS_PROXY"):
        ok(f"the workflow does not set {var}", var not in TEXT)
    src = open(HELPER, encoding="utf-8").read()
    ok("run calls the real command in process", 'collegedash.main(argv)' in src)
    ok("run passes --slugs-file and --no-bios", '["onboard", "--slugs-file", plan["slugsFile"], "--no-bios"]' in src)
    ok("run adds --collect-staged-divisions only from the plan", 'if plan.get("collectStagedDivisions"):' in src)
    ok("the helper sets no header", "headers" not in src.lower() or "User-Agent" not in src)


# ---------- plan ----------

def prog(slug, div="D3", conf="Alpha", onboarded=False, hold=None, skip=None):
    p = {"slug": slug, "division": div, "conference": conf, "onboarded": onboarded,
         "athletics": {"baseUrl": f"https://{slug}.example", "platform": "sidearm", "sportPath": "/sports/wsoc"}}
    if hold:
        p["collectionHold"] = hold
    if skip:
        p["athletics"]["skipReason"] = skip
    return p


def reg(staged=("D3",), published=("D1", "D2")):
    return {"onboardedDivisions": list(published), "stagedDivisions": list(staged), "programs": [
        prog("d1-a", "D1", "Big", True),
        prog("d2-a", "D2", "Mid", True),
        prog("a1"), prog("a2"), prog("a3", onboarded=True),
        prog("a4", hold={"reason": "merged-campus", "since": "2026-09-15"}),
        prog("b1", conf="Beta"), prog("b2", conf="Beta"),
    ]}


def refused(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except ob.Refused as e:
        return str(e)
    return None


def test_inputs():
    print("inputs: name and plan refuse what they should, before anything is installed")
    P = ob.parse_inputs
    ok("division d3 is normalised to D3", P("d3", "Alpha", "", "")[0] == "D3")
    for bad in ("", "3", "D", "Div3", "D3;rm", "D10"):
        ok(f"division {bad!r} is refused", refused(P, bad, "Alpha", "", ""))
    ok("a trailing comma is refused", refused(P, "D3", "Alpha,", "", ""))
    ok("a doubled comma is refused", refused(P, "D3", "Alpha,,Beta", "", ""))
    ok("a slug with a space or capital is refused", refused(P, "D3", "", "a1,A 2", ""))
    ok("a slug with shell metacharacters is refused", refused(P, "D3", "", "a1;$(x)", ""))
    ok("naming neither a conference nor a slug is refused (never a whole division)", refused(P, "D3", " ", " ", ""))
    ok("duplicates are dropped, order kept", P("D3", "Beta, Alpha,Beta", "", "")[1] == ["Beta", "Alpha"])
    for bad in ("Main", "a b", "-x", "x-", "a--b", "x" * 65, "../x", "a/b", "x.lock"):
        ok(f"batch_name {bad!r} is refused", refused(P, "D3", "Alpha", "", bad))
    ok("a good batch_name is kept as typed", P("D3", "Alpha", "", "d3-batch-1")[3] == "d3-batch-1")
    ok("a derived name is division + conferences", P("D3", "Liberty League,NESCAC", "", "")[3] == "d3-liberty-league-nescac")
    ok("a derived name from slugs", P("D3", "", "a1,a2,b1", "")[3] == "d3-a1-and-2-more")
    long = P("D3", "A Very Long Conference Name Indeed," * 1 + "Another Extremely Long Conference Name Here", "", "")[3]
    ok("a derived name is at most 64 characters and still valid", len(long) <= 64 and ob.NAME_RE.match(long), long)
    r = reg()
    ok("an unknown conference is refused", refused(ob.make_plan, r, "D3", ["Gamma"], [], "n"))
    ok("a conference of another division is refused", refused(ob.make_plan, r, "D3", ["Mid"], [], "n"))
    ok("an unknown slug is refused", refused(ob.make_plan, r, "D3", [], ["zz"], "n"))
    e = refused(ob.make_plan, r, "D3", [], ["a1", "d2-a"], "n")
    ok("a slug in another division is refused, naming it", e and "d2-a (D2)" in e, e)
    e = refused(ob.make_plan, r, "D3", ["Alpha", "Beta"], [], "n", max_programs=3)
    ok("a batch over the cap is refused, with conference sizes to split by", e and "Alpha 2" in e and "Beta 2" in e, e)
    ok("the default cap is 60", ob.MAX_PROGRAMS == 60)


def test_plan():
    print("plan: division state, selection, holds")
    e = refused(ob.make_plan, reg(staged=()), "D3", ["Alpha"], [], "n")
    ok("a division neither staged nor published is refused (D3 before #190)", e and "neither staged nor published" in e, e)
    p = ob.make_plan(reg(), "D3", ["Alpha"], [], "n")
    ok("a staged division passes --collect-staged-divisions D3",
       p["collectStagedDivisions"] == "D3" and p["command"][-2:] == ["--collect-staged-divisions", "D3"], p["command"])
    ok("a conference takes only programs not yet onboarded and not held, in registry order", p["slugs"] == ["a1", "a2"], p["slugs"])
    ok("the held entry is named with its reason", p["held"] == [{"slug": "a4", "conference": "Alpha",
                                                                  "skipReason": "collectionHold merged-campus, since 2026-09-15"}], p["held"])
    ok("the branch is onboard/<name>", p["branch"] == "onboard/n")
    p = ob.make_plan(reg(), "D3", [], ["a3", "a4", "b1"], "n")
    ok("an explicit slug is taken even when onboarded; a held one is not", p["slugs"] == ["a3", "b1"] and p["held"][0]["slug"] == "a4", p)
    p = ob.make_plan(reg(), "D2", [], ["d2-a"], "n")
    ok("a published division passes no staged-division flag", p["collectStagedDivisions"] is None
       and "--collect-staged-divisions" not in p["command"] and p["divisionState"] == "published", p["command"])
    e = refused(ob.make_plan, reg(), "D3", [], ["a4"], "n")
    ok("a batch of only held programs is refused, naming them", e and "a4" in e and "nothing to collect" in e, e)
    ok("a conference whose programs are all onboarded is refused",
       refused(ob.make_plan, {**reg(), "programs": [prog("x", onboarded=True)]}, "D3", ["Alpha"], [], "n"))
    tmp = tempfile.mkdtemp(prefix="onboard-plan-")
    try:
        path = os.path.join(tmp, "registry.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(reg(), f)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ob.main(["plan", "--division", "D3", "--conferences", "Alpha,Beta", "--registry", path, "--out-dir", tmp])
        plan = json.load(open(os.path.join(tmp, "plan.json"), encoding="utf-8"))
        ok("plan exits 0 and writes plan.json and the slugs file", code == 0 and
           open(os.path.join(tmp, "slugs.txt"), encoding="utf-8").read() == "a1\na2\nb1\nb2\n", out.getvalue())
        ok("plan.json points at the slugs file", plan["slugsFile"] == os.path.join(tmp, "slugs.txt"))
        with contextlib.redirect_stdout(io.StringIO()) as o2:
            code = ob.main(["plan", "--division", "D4", "--conferences", "Alpha", "--registry", path, "--out-dir", tmp])
        ok("a refusal exits 2 with an ::error line", code == 2 and o2.getvalue().startswith("::error title=onboard::"), o2.getvalue())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_shipped_registry():
    print("shipped-registry: the PSAC is onboarded or held, so there is nothing to collect")
    r = json.load(open(os.path.join(ROOT, "public", "data", "registry.json"), encoding="utf-8"))
    psac = [p for p in r["programs"] if p.get("conference") == "Pennsylvania State Athletic Conference"]
    held = [p["slug"] for p in psac if p.get("collectionHold") and not p.get("onboarded")]
    if not held:
        ok("the shipped registry still holds PSAC campuses (#199); skip the rest", True)
        return
    e = refused(ob.make_plan, r, "D2", ["Pennsylvania State Athletic Conference"], [], "n")
    ok("planning the PSAC is refused", e and "nothing to collect" in e, e)
    ok("each held campus is named", e and all(s in e for s in held), (held, e))


# ---------- host-stop, through the real transport ----------

class _Handler(http.server.BaseHTTPRequestHandler):
    hits: list = []

    def do_GET(self):
        _Handler.hits.append((self.server.server_address[1], self.path))
        code = 403 if self.path.startswith("/forbidden") else 429 if self.path.startswith("/limited") else 200
        body = b"ok"
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_host_stop():
    print("host-stop: after a host's first 403/429 nothing more is sent to it")
    import requests
    from collect import common

    servers = [http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler) for _ in range(2)]
    for s in servers:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    a, b = (f"http://127.0.0.1:{s.server_address[1]}" for s in servers)
    b = b.replace("127.0.0.1", "localhost")  # a different host key for the gate and the stop list
    original_send = common._PoliteAdapter.send

    class FakeCollegedash:
        @staticmethod
        def collect_one(name, program, registry, **kw):
            with common._session() as s:
                for path in kw["paths"]:
                    try:
                        s.get(program["base"] + path, timeout=5, proxies={"http": None, "https": None})
                    except requests.exceptions.ConnectionError as e:
                        kw["errors"].append(str(e))
            return {"outcome": "ok"}, None

    try:
        _Handler.hits = []
        state = ob.install_wrapper(common, FakeCollegedash, no_network=False)
        errors: list = []
        FakeCollegedash.collect_one("athletics", {"slug": "p-a", "base": a}, {}, paths=["/ok", "/forbidden", "/ok2"], errors=errors)
        FakeCollegedash.collect_one("athletics", {"slug": "p-b", "base": b}, {}, paths=["/ok", "/limited", "/again"], errors=errors)
        FakeCollegedash.collect_one("athletics", {"slug": "p-c", "base": a}, {}, paths=["/ok3"], errors=errors)
        port_a, port_b = servers[0].server_address[1], servers[1].server_address[1]
        ok("the 403 host received /ok and /forbidden and nothing after", [p for n, p in _Handler.hits if n == port_a] == ["/ok", "/forbidden"], _Handler.hits)
        ok("the 429 host received /ok and /limited and nothing after", [p for n, p in _Handler.hits if n == port_b] == ["/ok", "/limited"], _Handler.hits)
        ok("both hosts are recorded as stopped with their status",
           state["stopped"] == {"127.0.0.1": 403, "localhost": 429}, state["stopped"])
        ok("the refused requests raised ConnectionError without being sent", len(errors) == 3 and all("no request sent" in e for e in errors), errors)
        ok("each hit is attributed to the program that met it",
           state["perProgram"]["p-a"]["blockedHosts"] == {"127.0.0.1": 403}
           and state["perProgram"]["p-b"]["blockedHosts"] == {"localhost": 429}
           and state["perProgram"]["p-c"]["blockedHosts"] == {"127.0.0.1": 403}, dict(state["perProgram"]))
        ok("requests sent are counted, refused ones are not", state["requests"] == 4 and sum(state["refused"].values()) == 3,
           (state["requests"], state["refused"]))
        common._PoliteAdapter.send = original_send

        _Handler.hits = []
        state = ob.install_wrapper(common, FakeCollegedash, no_network=True)
        errors = []
        FakeCollegedash.collect_one("athletics", {"slug": "p-d", "base": a}, {}, paths=["/ok", "/ok2"], errors=errors)
        ok("--no-network sends nothing at all", _Handler.hits == [] and state["requests"] == 0 and len(errors) == 2, (_Handler.hits, errors))
    finally:
        common._PoliteAdapter.send = original_send
        for s in servers:
            s.shutdown()


def test_host_stop_concurrent(threads: int = 8):
    print(f"host-stop-concurrent: {threads} threads at once per host; each host must receive exactly one request")
    import requests
    from collect import common

    servers = [http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler) for _ in range(2)]
    for s in servers:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    forbidden = f"http://127.0.0.1:{servers[0].server_address[1]}/forbidden"
    limited = f"http://localhost:{servers[1].server_address[1]}/limited"
    original_send = common._PoliteAdapter.send
    # a short gap and 429 backoff keep the case quick; they change how long a queued thread waits at the gate,
    # not whether it is queued there, which is what this case is about
    saved = (common.MIN_GAP_SECONDS, common.JITTER_SECONDS, common.BACKOFF_429_SECONDS)
    common.MIN_GAP_SECONDS, common.JITTER_SECONDS, common.BACKOFF_429_SECONDS = 0.2, 0.0, 0.2
    try:
        _Handler.hits = []
        state = ob.install_wrapper(common, types.SimpleNamespace(collect_one=lambda *a, **k: None), no_network=False)
        barrier = threading.Barrier(threads * 2)
        outcomes: list = []

        def one(url):
            barrier.wait()
            try:
                with common._session() as s:
                    r = s.get(url, timeout=10, proxies={"http": None, "https": None})
                outcomes.append(r.status_code)
            except requests.exceptions.ConnectionError:
                outcomes.append("refused")

        workers = [threading.Thread(target=one, args=(u,)) for u in [forbidden] * threads + [limited] * threads]
        for w in workers:
            w.start()
        for w in workers:
            w.join(60)
        port_a, port_b = servers[0].server_address[1], servers[1].server_address[1]
        got_a = sum(1 for n, _ in _Handler.hits if n == port_a)
        got_b = sum(1 for n, _ in _Handler.hits if n == port_b)
        ok(f"the always-403 host received exactly 1 of {threads} concurrent requests", got_a == 1, f"received {got_a}")
        ok(f"the always-429 host received exactly 1 of {threads} concurrent requests", got_b == 1, f"received {got_b}")
        ok("every other request was refused without being sent", outcomes.count("refused") == 2 * threads - 2
           and sum(state["refused"].values()) == 2 * threads - 2, (outcomes, dict(state["refused"])))
        ok("the wrapper counts 2 sent", state["requests"] == 2, state["requests"])
    finally:
        common._PoliteAdapter.send = original_send
        common.MIN_GAP_SECONDS, common.JITTER_SECONDS, common.BACKOFF_429_SECONDS = saved
        for s in servers:
            s.shutdown()


# ---------- summary ----------

def test_summary():
    print("summary: rows, failures, 403/429 hosts, skipReason, and the registry guard")
    tmp = tempfile.mkdtemp(prefix="onboard-summary-")
    old_root = ob.ROOT
    try:
        ob.ROOT = tmp
        started = "2026-09-23T10:00:00Z"
        base = reg()
        now = json.loads(json.dumps(base))
        for p in now["programs"]:
            if p["slug"] in ("a1", "a2", "b1"):
                p["onboarded"] = True
        now["programs"][-2]["athletics"]["skipReason"] = "PrestoSports, no adapter"  # b1
        os.makedirs(os.path.join(tmp, "public", "data"))
        os.makedirs(os.path.join(tmp, "public", "archive"))
        src = os.path.join(tmp, "programs", "a1", "sources")
        os.makedirs(src)
        with open(os.path.join(src, "athletics.json"), "w", encoding="utf-8") as f:
            json.dump({"fetchedAt": "2026-09-23T10:05:00Z", "data": {"roster": {"players": [1, 2, 3]},
                       "schedule": {"games": [1, 2]}, "staff": [1]}}, f)
        src2 = os.path.join(tmp, "programs", "a2", "sources")
        os.makedirs(src2)
        with open(os.path.join(src2, "athletics.json"), "w", encoding="utf-8") as f:
            json.dump({"fetchedAt": "2026-01-01T00:00:00Z", "data": {"roster": {"players": [1]}, "schedule": {"games": []}, "staff": []}}, f)
        state = {f"a1.{c}": {"ok": True, "at": "2026-09-23T10:06:00Z"} for c in ob.COLLECTORS}
        state["a1.camps"] = {"ok": False, "error": "HTTP 500 for x", "at": "2026-09-23T10:06:00Z"}
        state.update({f"a2.{c}": {"ok": True, "at": "2026-09-23T10:06:00Z"} for c in ob.COLLECTORS[:4]})
        state["a2.tds"] = {"ok": True, "at": "2026-08-01T00:00:00Z"}  # stale: not this run's
        state.update({f"b1.{c}": {"ok": True, "at": "2026-09-23T10:06:00Z"} for c in ob.COLLECTORS})
        with open(os.path.join(tmp, "public", "archive", "refresh-state.json"), "w", encoding="utf-8") as f:
            json.dump(state, f)
        plan = ob.make_plan(base, "D3", ["Alpha"], ["b1"], "t")
        run = {"exit": 1, "startedAt": started, "wallSeconds": 60.0, "requests": 10,
               "stoppedHosts": {"a2.example": 403}, "perProgram": {"a2": {"requests": 3, "blockedHosts": {"a2.example": 403}}}}
        for name, data in (("plan.json", plan), ("run.json", run), ("base.json", base)):
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                json.dump(data, f)

        def summarize(reg_now):
            with open(os.path.join(tmp, "public", "data", "registry.json"), "w", encoding="utf-8") as f:
                json.dump(reg_now, f)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = ob.main(["summarize", "--plan", os.path.join(tmp, "plan.json"), "--run", os.path.join(tmp, "run.json"),
                                "--base-registry", os.path.join(tmp, "base.json"),
                                "--json-out", os.path.join(tmp, "out", "t.json"), "--md-out", os.path.join(tmp, "out", "t.md")])
            return code, out.getvalue()

        code, out = summarize(now)
        s = json.load(open(os.path.join(tmp, "out", "t.json"), encoding="utf-8"))
        rows = {r["slug"]: r for r in s["programs"]}
        md = open(os.path.join(tmp, "out", "t.md"), encoding="utf-8").read()
        ok("a clean guard exits 0", code == 0 and s["guard"] == [], out)
        ok("roster, schedule and staff rows are counted", (rows["a1"]["rosterRows"], rows["a1"]["scheduleRows"], rows["a1"]["staffRows"]) == (3, 2, 1), rows["a1"])
        ok("a collector failure is listed with its error", rows["a1"]["failures"] == {"camps": "HTTP 500 for x"}, rows["a1"]["failures"])
        ok("a collector with no entry from this run is 'not run', a stale entry included",
           rows["a2"]["notRun"] == ["tds", "soccerwire", "news", "camps"], rows["a2"]["notRun"])
        ok("counts from an earlier collection are marked", not rows["a2"]["athleticsFromThisRun"] and "| 1 (earlier) |" in md, md)
        ok("the 403/429 host is on the program that met it", rows["a2"]["blockedHosts"] == {"a2.example": 403})
        ok("skipReason comes from the registry", rows["b1"]["skipReason"] == "PrestoSports, no adapter")
        ok("the held program is in the table with its reason", "| a4 | Alpha | - | - | - | not collected | - | collectionHold merged-campus" in md, md)
        ok("the markdown has one row per program plus the held one",
           sum(1 for l in md.splitlines() if l.startswith("| ") and not l.startswith("| program") and not l.startswith("| ---")) == 4, md)

        bad = json.loads(json.dumps(now))
        bad["programs"][0]["onboarded"] = False  # d1-a: not in the plan
        code, out = summarize(bad)
        ok("onboarded changed outside the plan exits 3 with ::error", code == 3 and "::error title=onboard::registry guard: d1-a" in out, out)
        bad = json.loads(json.dumps(now))
        bad["stagedDivisions"] = []
        bad["onboardedDivisions"] = ["D1", "D2", "D3"]
        code, out = summarize(bad)
        ok("a changed division list exits 3", code == 3 and "stagedDivisions changed" in out, out)
        wrong_div = json.loads(json.dumps(now))
        for p in wrong_div["programs"]:
            if p["slug"] == "a1":
                p["division"] = "D2"
        code, out = summarize(wrong_div)
        ok("a planned program onboarded in another division exits 3", code == 3 and "a1: onboarded in D2" in out, out)
    finally:
        ob.ROOT = old_root
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- the Prepare and Commit steps, against a scratch origin ----------

def find_bash() -> str:
    if os.name == "nt":  # Git for Windows' bash, never WSL's
        exec_path = subprocess.run(["git", "--exec-path"], capture_output=True, text=True).stdout.strip()
        cand = os.path.normpath(os.path.join(exec_path, "..", "..", "..", "bin", "bash.exe"))
        if os.path.exists(cand):
            return cand
    return shutil.which("bash") or "bash"


BASH = find_bash()
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "harness",
           "GIT_AUTHOR_EMAIL": "harness@example.invalid", "GIT_COMMITTER_NAME": "harness",
           "GIT_COMMITTER_EMAIL": "harness@example.invalid"}


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, env={**os.environ, **GIT_ENV})
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.decode(errors='replace')}")
    return r.stdout.decode(errors="replace").strip()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def run_step(name, work, env):
    body = run_block(step(name)["lines"])
    script = os.path.join(os.path.dirname(work), f"{name.replace(' ', '_')}.sh")
    write(script, body)
    r = subprocess.run([BASH, "--noprofile", "--norc", "-eo", "pipefail", script], cwd=work, capture_output=True,
                       env={**os.environ, **GIT_ENV, **env})
    return r.returncode, (r.stdout + r.stderr).decode(errors="replace")


def setup(tmp, case, *, existing_branch=False, reject=None):
    root = os.path.join(tmp, case)
    origin, seed, work, temp = (os.path.join(root, x) for x in ("origin.git", "seed", "work", "runner-temp"))
    os.makedirs(temp)
    subprocess.run(["git", "init", "-q", "--bare", origin], check=True, env={**os.environ, **GIT_ENV})
    git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    subprocess.run(["git", "init", "-q", "-b", "main", seed], check=True, env={**os.environ, **GIT_ENV})
    git(seed, "config", "core.autocrlf", "false")
    write(os.path.join(seed, "public/data/registry.json"), '{"programs": [{"slug": "a1", "onboarded": false}]}\n')
    write(os.path.join(seed, "public/data/programs/a1.json"), '{"builtAt": "old"}\n')
    write(os.path.join(seed, "public/archive/refresh-state.json"), '{"updated": "old"}\n')
    write(os.path.join(seed, "programs/a1/sources/athletics.json"), '"a1-v0"\n')
    write(os.path.join(seed, "programs/zz/sources/athletics.json"), '"zz-v0"\n')
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "seed")
    git(seed, "push", "-q", origin, "HEAD:refs/heads/main")
    if existing_branch:
        write(os.path.join(seed, "data/onboard-batches/earlier.md"), "earlier\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "earlier batch run")
        git(seed, "push", "-q", origin, "HEAD:refs/heads/onboard/t")
    if reject:
        hook = os.path.join(origin, "hooks", "pre-receive")
        write(hook, "#!/bin/sh\nwhile read old new ref; do\n  [ \"$ref\" = \"%s\" ] && { echo rejected >&2; exit 1; }\ndone\nexit 0\n" % reject)
        os.chmod(hook, os.stat(hook).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    url = "file:///" + origin.replace("\\", "/").lstrip("/")
    subprocess.run(["git", "-c", "core.autocrlf=false", "clone", "-q", "--depth=1", "--branch", "main", url, work],
                   check=True, capture_output=True, env={**os.environ, **GIT_ENV})
    git(work, "config", "core.autocrlf", "false")
    return origin, work, temp


def collect_in(work, temp, slugs=("a1", "b2")):
    """What a batch run leaves behind: its sources, onboarded flags, build output, refresh-state, a summary,
    and a change to a program that is not in the batch."""
    write(os.path.join(work, "programs/a1/sources/athletics.json"), '"a1-v1"\n')
    write(os.path.join(work, "programs/b2/sources/athletics.json"), '"b2-v1"\n')
    write(os.path.join(work, "programs/zz/sources/athletics.json"), '"zz-v1"\n')
    write(os.path.join(work, "public/data/registry.json"), '{"programs": [{"slug": "a1", "onboarded": true}]}\n')
    write(os.path.join(work, "public/data/programs/a1.json"), '{"builtAt": "new"}\n')
    write(os.path.join(work, "public/data/programs/b2.json"), '{"builtAt": "new"}\n')
    write(os.path.join(work, "public/archive/refresh-state.json"), '{"updated": "new"}\n')
    write(os.path.join(work, "data/onboard-batches/t.json"), "{}\n")
    write(os.path.join(work, "data/onboard-batches/t.md"), "summary\n")
    write(os.path.join(temp, "onboard", "slugs.txt"), "".join(s + "\n" for s in slugs))


def env_for(temp, **kw):
    e = {"BRANCH": "onboard/t", "NAME": "t", "DIVISION": "D3", "DRY_RUN": "false", "SUMMARY_OUTCOME": "success",
         "RUNNER_TEMP": temp, "GITHUB_REPOSITORY": "owner/repo", "GITHUB_RUN_ID": "77", "GITHUB_RUN_ATTEMPT": "1", "PUSH_TOKEN": "harness-token"}
    e.update(kw)
    return e


def remote_branches(origin):
    return sorted(l.split("refs/heads/")[1] for l in git(origin, "for-each-ref", "--format=%(refname)", "refs/heads").splitlines())


def committed(origin, ref):
    return sorted(git(origin, "diff", "--name-only", f"{ref}~1", ref, check=False).splitlines())


EXPECTED = ["data/onboard-batches/t.json", "data/onboard-batches/t.md", "programs/a1/sources/athletics.json",
            "programs/b2/sources/athletics.json", "public/data/registry.json"]


def test_commit_steps(tmp):
    print("commit-new-branch: a new onboard/<name> off main, only the batch's paths")
    origin, work, temp = setup(tmp, "new")
    main0 = git(origin, "rev-parse", "refs/heads/main")
    code, out = run_step("Prepare the batch branch", work, env_for(temp))
    ok("prepare succeeds and switches to the batch branch", code == 0 and git(work, "rev-parse", "--abbrev-ref", "HEAD") == "onboard/t", out)
    ok("prepare keeps the starting registry aside for the guard",
       open(os.path.join(temp, "onboard", "base-registry.json"), encoding="utf-8").read().strip() == '{"programs": [{"slug": "a1", "onboarded": false}]}')
    collect_in(work, temp)
    code, out = run_step("Commit to the batch branch", work, env_for(temp))
    ok("commit succeeds", code == 0, out)
    ok("origin gets onboard/t and main is untouched", remote_branches(origin) == ["main", "onboard/t"]
       and git(origin, "rev-parse", "refs/heads/main") == main0, remote_branches(origin))
    ok("onboard/t is one commit on main", git(origin, "rev-parse", "onboard/t~1", check=False) == main0)
    ok("only the batch's own paths are committed: no build output, refresh-state, or program outside the batch",
       committed(origin, "onboard/t") == EXPECTED, committed(origin, "onboard/t"))
    ok("the commit says what it is", "data: onboard t (D3, 2 programs)" in git(origin, "log", "-1", "--format=%B", "onboard/t", check=False))
    ok("the PR link is printed", "compare/main...onboard/t?expand=1" in out, out[-400:])
    import base64
    cfg = open(os.path.join(work, ".git", "config"), encoding="utf-8").read()
    ok("after the push the token is not in the clone's config, plain or encoded",
       "harness-token" not in cfg and base64.b64encode(b"x-access-token:harness-token").decode() not in cfg)

    print("commit-existing-branch: a re-run adds a commit on top of onboard/<name>")
    origin, work, temp = setup(tmp, "existing", existing_branch=True)
    tip0 = git(origin, "rev-parse", "refs/heads/onboard/t")
    main0 = git(origin, "rev-parse", "refs/heads/main")
    code, out = run_step("Prepare the batch branch", work, env_for(temp))
    ok("prepare continues the existing branch", code == 0 and git(work, "rev-parse", "HEAD") == tip0 and "already exists" in out, out)
    collect_in(work, temp)
    code, out = run_step("Commit to the batch branch", work, env_for(temp))
    ok("the new commit's parent is the old branch tip (a fast-forward)", code == 0 and git(origin, "rev-parse", "onboard/t~1", check=False) == tip0, out)
    ok("main is untouched", git(origin, "rev-parse", "refs/heads/main") == main0)

    print("commit-dry-run: nothing pushed")
    origin, work, temp = setup(tmp, "dry")
    run_step("Prepare the batch branch", work, env_for(temp, DRY_RUN="true"))
    collect_in(work, temp)
    code, out = run_step("Commit to the batch branch", work, env_for(temp, DRY_RUN="true"))
    ok("dry run exits 0, commits on the runner, and pushes nothing", code == 0 and remote_branches(origin) == ["main"]
       and "Nothing was pushed" in out, (remote_branches(origin), out[-300:]))

    print("commit-summary-failed: a failed summary or registry guard pushes nothing")
    origin, work, temp = setup(tmp, "guard")
    run_step("Prepare the batch branch", work, env_for(temp))
    collect_in(work, temp)
    code, out = run_step("Commit to the batch branch", work, env_for(temp, SUMMARY_OUTCOME="failure"))
    ok("exits 1 and pushes nothing", code == 1 and remote_branches(origin) == ["main"], out[-300:])

    print("commit-not-onboard: a branch outside onboard/ is refused by both steps")
    origin, work, temp = setup(tmp, "main")
    main0 = git(origin, "rev-parse", "refs/heads/main")
    code, out = run_step("Prepare the batch branch", work, env_for(temp, BRANCH="main"))
    ok("prepare refuses BRANCH=main", code == 1 and "refusing branch 'main'" in out, out)
    collect_in(work, temp)
    for b in ("main", "refs/heads/main", "onboard/", "x/onboard/t"):
        code, out = run_step("Commit to the batch branch", work, env_for(temp, BRANCH=b))
        ok(f"commit refuses BRANCH={b!r}", code == 1 and "refusing branch" in out, out[-300:])
    ok("main is untouched and no branch was created", git(origin, "rev-parse", "refs/heads/main") == main0
       and remote_branches(origin) == ["main"])

    print("prepare-lookup-failed: an unreachable origin is an error, not 'no such branch'")
    origin, work, temp = setup(tmp, "lookup")
    git(work, "remote", "set-url", "origin", os.path.join(tmp, "lookup", "missing.git"))
    code, out = run_step("Prepare the batch branch", work, env_for(temp))
    ok("prepare exits 1 and stays on main", code == 1 and "could not ask origin" in out
       and git(work, "rev-parse", "--abbrev-ref", "HEAD") == "main", out[-300:])

    print("commit-off-branch: a checkout not on the batch branch commits nothing")
    origin, work, temp = setup(tmp, "offbranch")
    collect_in(work, temp)  # prepare never ran: still on main
    code, out = run_step("Commit to the batch branch", work, env_for(temp))
    ok("exits 1 naming the branch it is on, and pushes nothing", code == 1 and "not onboard/t" in out
       and remote_branches(origin) == ["main"], out[-300:])

    print("commit-moved-branch: a rejected push falls back to onboard/<name>-run-*")
    origin, work, temp = setup(tmp, "moved", reject="refs/heads/onboard/t")
    main0 = git(origin, "rev-parse", "refs/heads/main")
    run_step("Prepare the batch branch", work, env_for(temp))
    collect_in(work, temp)
    code, out = run_step("Commit to the batch branch", work, env_for(temp))
    ok("the run fails loudly but the collection is on the fallback branch", code == 1
       and remote_branches(origin) == ["main", "onboard/t-run-77-1"] and "moved while this batch ran" in out, (remote_branches(origin), out[-400:]))
    ok("main is untouched", git(origin, "rev-parse", "refs/heads/main") == main0)

    print("commit-nothing: a run that changed none of the batch's files commits nothing")
    origin, work, temp = setup(tmp, "nothing")
    run_step("Prepare the batch branch", work, env_for(temp))
    write(os.path.join(temp, "onboard", "slugs.txt"), "a1\n")
    write(os.path.join(work, "public/data/programs/a1.json"), '{"builtAt": "new"}\n')  # build output only
    write(os.path.join(work, "data/onboard-batches/t.md"), "summary\n")  # and the summary, which is not a batch
    code, out = run_step("Commit to the batch branch", work, env_for(temp))
    ok("exits 0 with a warning and pushes nothing", code == 0 and "nothing is committed or pushed" in out
       and remote_branches(origin) == ["main"], out[-300:])

    # issue #289: data/camps-refused-hosts.json rides along when the run changed it, and only then; the
    # writer's temp file (a <name>.<random>.tmp; a killed run can leave one) is never committed. The seed
    # repo here has no .gitignore, so this checks the step's own exact-path staging, not *.tmp in .gitignore.
    refused_path = "data/camps-refused-hosts.json"
    refused_v1 = '{\n  "camps.example.com": {\n    "firstAt": "2026-09-24",\n    "status": 403\n  }\n}\n'
    for case, on_main in (("refused-new", False), ("refused-changed", True)):
        print(f"commit-{case}: a batch that records a refused camp host commits the file, never a leftover .tmp")
        origin, work, temp = setup(tmp, case)
        if on_main:
            write(os.path.join(work, refused_path), "{}\n")
            git(work, "add", "--", refused_path)
            git(work, "commit", "-q", "-m", "refused-hosts file on main")
            git(work, "push", "-q", "origin", "HEAD:refs/heads/main")
        run_step("Prepare the batch branch", work, env_for(temp))
        collect_in(work, temp)
        write(os.path.join(work, refused_path), refused_v1)
        write(os.path.join(work, refused_path + ".tmp"), '{\n  "half-writ')
        write(os.path.join(work, "data/camps-refused-hosts.json.x1y2z3.tmp"), '{\n  "half-writ')
        code, out = run_step("Commit to the batch branch", work, env_for(temp))
        got = committed(origin, "onboard/t")
        ok(f"{case}: the refused-hosts file is committed with the batch's paths, and nothing else",
           code == 0 and got == sorted(EXPECTED + [refused_path]), (got, out[-300:]))
        ok(f"{case}: the committed file is the run's", git(origin, "show", f"onboard/t:{refused_path}", check=False)
           == refused_v1.strip())
        ok(f"{case}: no .tmp is committed, and the leftovers are still on the runner, untracked",
           not any(p.endswith(".tmp") for p in got)
           and git(work, "ls-files", "--", "*.tmp") == ""
           and os.path.exists(os.path.join(work, refused_path + ".tmp")), got)

    print("commit-refused-untouched: a batch that records no refused host leaves the file as it is on main")
    origin, work, temp = setup(tmp, "refused-untouched")
    write(os.path.join(work, refused_path), "{}\n")
    git(work, "add", "--", refused_path)
    git(work, "commit", "-q", "-m", "refused-hosts file on main")
    git(work, "push", "-q", "origin", "HEAD:refs/heads/main")
    run_step("Prepare the batch branch", work, env_for(temp))
    collect_in(work, temp)
    write(os.path.join(work, refused_path + ".tmp"), '{\n  "half-writ')
    code, out = run_step("Commit to the batch branch", work, env_for(temp))
    ok("refused-untouched: exactly the batch's paths, the file unchanged on the branch",
       code == 0 and committed(origin, "onboard/t") == EXPECTED
       and git(origin, "show", f"onboard/t:{refused_path}", check=False) == "{}", (committed(origin, "onboard/t"), out[-300:]))

    print("commit-refused-only: a run that only recorded a refused host is still not a batch")
    origin, work, temp = setup(tmp, "refused-only")
    run_step("Prepare the batch branch", work, env_for(temp))
    write(os.path.join(temp, "onboard", "slugs.txt"), "a1\n")
    write(os.path.join(work, "data/onboard-batches/t.md"), "summary\n")
    write(os.path.join(work, refused_path), refused_v1)
    code, out = run_step("Commit to the batch branch", work, env_for(temp))
    ok("refused-only: exits 0 with the warning and pushes nothing", code == 0 and "nothing is committed or pushed" in out
       and remote_branches(origin) == ["main"], out[-300:])


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose
    print(f"workflow: {os.path.relpath(YML, ROOT) if YML.startswith(ROOT) else YML}; bash: {BASH}")
    test_shape()
    test_inputs_in_env()
    test_never_main()
    test_politeness()
    test_inputs()
    test_plan()
    test_shipped_registry()
    test_host_stop()
    test_host_stop_concurrent()
    test_summary()
    tmp = tempfile.mkdtemp(prefix="onboard-steps-")
    try:
        test_commit_steps(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
