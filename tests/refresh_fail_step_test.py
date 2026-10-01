"""refresh.yml's last step, "Fail if too many collectors failed": when it runs, and so what colour the run ends (#86).

    python tests/refresh_fail_step_test.py            # every case
    python tests/refresh_fail_step_test.py --verbose  # print every check and the full matrix

Offline: reads .github/workflows/refresh.yml (or REFRESH_YML, to show the checks failing on main's copy) and runs the
step's own script under bash, the way tests/refresh_commit_step_test.py runs the commit step (its extract_step and
find_bash are reused). Nothing is pushed or fetched; no workflow is run.

GitHub evaluates a step's `if:`, not bash, so the conditions are evaluated here by a small evaluator for exactly the
expression subset refresh.yml uses: the status functions (success, failure, cancelled, always), with GitHub's implicit
`success() &&` when none is named; `==` and `!=` with GitHub's loose comparison; `&&`, `||`, `!`, parentheses; string,
boolean and null literals; and `steps.*` / `inputs.*` lookups. It FAILS LOUDLY on any other token, so a condition it
cannot read can never make a check pass (the lesson of #413's CSS checker); a self-test feeds it such forms.

Cases:
  structure  the fail step is the job's last step, its `if:` is exactly the reviewed expression, and its script only
             echoes and exits (no git, no network, no file writes).
  script     the script under bash: no code -> "did not finish"; code 1 and 2 -> today's text; every branch exits 1.
  matrix     the fail step's condition over every collector-step outcome (success, failure, cancelled, skipped) x
             code ('', '0', '1', '2') x run cancelled or not x an earlier step already failed or not: it runs exactly
             when the run was not cancelled, the collector step was not skipped and it did not report code 0.
  paths      the whole job simulated from refresh.yml's own conditions and continue-on-error flags for the run paths
             that matter (scheduled ok, over threshold, crash, killed, gated, gated + over threshold, build_only, bad
             `only`, cancelled): the run's conclusion and whether the fail step ran.
  evaluator  the evaluator's self-test.
"""

from __future__ import annotations

import argparse
import itertools
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from refresh_commit_step_test import extract_step, find_bash  # noqa: E402

YML = os.environ.get("REFRESH_YML") or os.path.join(ROOT, ".github", "workflows", "refresh.yml")
TEXT = open(YML, encoding="utf-8").read()
FAIL_STEP = "Fail if too many collectors failed"
REVIEWED_IF = "${{ !cancelled() && steps.refresh.outcome != 'skipped' && steps.refresh.outputs.code != '0' }}"

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail="") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:400]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


# ---------- the job's steps, as refresh.yml lists them ----------

def job_steps(text: str) -> list[dict]:
    """[{name, id, if, continue_on_error}] for jobs.refresh.steps, in order. Each step starts at the first `- ` under
    `steps:`; its own keys sit two columns deeper. Unnamed steps (`- uses:`, `- run:`) are named by that line."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if re.match(r"^    steps:\s*$", l))
    steps, cur = [], None
    for l in lines[start + 1:]:
        if l.strip() == "" or l.lstrip().startswith("#"):
            continue
        if not l.startswith("      "):
            break  # out of the job
        m = re.match(r"^      - (\w[\w-]*): ?(.*)$", l)
        if m:
            cur = {"name": None, "id": None, "if": None, "continue_on_error": False}
            steps.append(cur)
            key, val = m.group(1), m.group(2).strip()
        else:
            m = re.match(r"^        (\w[\w-]*): ?(.*)$", l)
            if not m or cur is None:
                continue
            key, val = m.group(1), m.group(2).strip()
        if key == "name":
            cur["name"] = val
        elif key in ("uses", "run") and cur["name"] is None:
            cur["name"] = f"{key}: {val}"
        elif key == "id":
            cur["id"] = val
        elif key == "if":
            cur["if"] = val
        elif key == "continue-on-error":
            cur["continue_on_error"] = val == "true"
    return steps


# ---------- a GitHub expression evaluator for refresh.yml's subset ----------

class Unreadable(Exception):
    pass


TOKEN = re.compile(r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<op>==|!=|&&|\|\||!|\(|\))|(?P<call>(?:success|failure|cancelled|always)\(\))"
                   r"|(?P<lit>true|false|null)\b|(?P<ref>(?:steps|inputs)(?:\.[A-Za-z_][\w-]*)+))")
STATUS = re.compile(r"\b(success|failure|cancelled|always)\(\)")


def tokens(expr: str) -> list[tuple[str, str]]:
    out, i = [], 0
    while i < len(expr):
        if expr[i:].strip() == "":
            break
        m = TOKEN.match(expr, i)
        if not m:
            raise Unreadable(f"cannot read the expression at {expr[i:i + 30]!r} (in {expr!r})")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        i = m.end()
    return out


def loose_eq(a, b) -> bool:
    """GitHub's `==`: same type compares directly (strings case-insensitively); otherwise both become numbers
    (null 0, false 0, true 1, '' 0, a numeric string its value, any other string NaN, and NaN equals nothing)."""
    if type(a) is type(b):
        return a.lower() == b.lower() if isinstance(a, str) else a == b

    def num(v):
        if v is None:
            return 0.0
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        if isinstance(v, str):
            s = v.strip()
            if s == "":
                return 0.0
            try:
                return float(s)
            except ValueError:
                return float("nan")
        return float(v)
    x, y = num(a), num(b)
    return x == y  # NaN != NaN


def truthy(v) -> bool:
    return not (v is None or v is False or v == "" or v == 0)


def evaluate(cond: str | None, ctx: dict) -> bool:
    """Whether a step with this `if:` runs. ctx: {steps: {id: {outcome, outputs}}, inputs: {...}, job_failed, cancelled}."""
    if cond is None or cond == "":
        cond = "success()"
    expr = cond.strip()
    if expr.startswith("${{"):
        if not expr.endswith("}}"):
            raise Unreadable(f"unterminated ${{{{ in {cond!r}")
        expr = expr[3:-2].strip()
    if not STATUS.search(expr):
        expr = f"success() && ({expr})"
    toks, pos = tokens(expr), 0

    def peek():
        return toks[pos] if pos < len(toks) else (None, None)

    def take():
        nonlocal pos
        t = peek()
        pos += 1
        return t

    def primary():
        kind, val = take()
        if kind == "op" and val == "(":
            v = disj()
            k2, v2 = take()
            if (k2, v2) != ("op", ")"):
                raise Unreadable(f"missing ) in {cond!r}")
            return v
        if kind == "op" and val == "!":
            return not truthy(primary())
        if kind == "str":
            return val[1:-1].replace("''", "'")
        if kind == "lit":
            return {"true": True, "false": False, "null": None}[val]
        if kind == "call":
            name = val[:-2]
            return {"success": not ctx["job_failed"] and not ctx["cancelled"], "failure": ctx["job_failed"],
                    "cancelled": ctx["cancelled"], "always": True}[name]
        if kind == "ref":
            parts = val.split(".")
            if parts[0] == "inputs":
                return ctx["inputs"].get(parts[1])
            if parts[0] == "steps" and len(parts) == 3 and parts[2] in ("outcome", "conclusion"):
                return ctx["steps"].get(parts[1], {}).get(parts[2], "skipped" if parts[1] not in ctx["steps"] else None)
            if parts[0] == "steps" and len(parts) == 4 and parts[2] == "outputs":
                # an output the step never wrote reads as '' (which is why `code != '0'` alone is true when skipped: #82)
                return ctx["steps"].get(parts[1], {}).get("outputs", {}).get(parts[3], "")
            raise Unreadable(f"cannot read the reference {val!r} in {cond!r}")
        raise Unreadable(f"unexpected {val!r} in {cond!r}")

    def cmp():
        left = primary()
        while peek() in (("op", "=="), ("op", "!=")):
            _, op = take()
            right = primary()
            left = loose_eq(left, right) if op == "==" else not loose_eq(left, right)
        return left

    def conj():
        left = cmp()
        while peek() == ("op", "&&"):
            take()
            right = cmp()
            left = left if not truthy(left) else right
        return left

    def disj():
        left = conj()
        while peek() == ("op", "||"):
            take()
            right = conj()
            left = left if truthy(left) else right
        return left

    v = disj()
    if pos != len(toks):
        raise Unreadable(f"trailing tokens in {cond!r}")
    return truthy(v)


# ---------- the step's script under bash ----------

BASH = find_bash()


def run_script(code: str) -> tuple[int, str]:
    script = extract_step(YML, FAIL_STEP, TEXT)
    env = {**os.environ, "REFRESH_CODE": code, "FAIL_THRESHOLD": "0.05"}
    r = subprocess.run([BASH, "-e", "-c", script], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


# ---------- cases ----------

def test_structure():
    print("structure: the fail step is last, reads exactly as reviewed, and has no side effects")
    steps = job_steps(TEXT)
    names = [s["name"] for s in steps]
    ok("the job's steps were read (at least the collector, commit and fail steps)",
       {"Refresh data", "Commit changed data", FAIL_STEP} <= set(names), names)
    ok("the fail step is the job's last step", names and names[-1] == FAIL_STEP, names[-3:])
    fail = next((s for s in steps if s["name"] == FAIL_STEP), {})
    ok("its `if:` is exactly the reviewed expression", fail.get("if") == REVIEWED_IF, fail.get("if"))
    refresh = next((s for s in steps if s["name"] == "Refresh data"), {})
    ok("the collector step is id `refresh` with continue-on-error (what the condition reads)",
       refresh.get("id") == "refresh" and refresh.get("continue_on_error"), refresh)
    script = extract_step(YML, FAIL_STEP, TEXT)
    allowed = re.compile(r"^\s*(echo\s+\"[^\"`]*\"|exit\s+1|if\s+\[\s+-z\s+\"\$REFRESH_CODE\"\s+\];\s+then|fi)\s*$")
    bad = [l for l in script.splitlines() if l.strip() and not allowed.match(l)]
    ok("its script only echoes double-quoted text without command substitution, tests the code and exits 1", not bad, bad)
    ok("no redirection, pipe, git, curl or python anywhere in it",
       not re.search(r"[>|]|\$\(|\bgit\b|\bcurl\b|\bwget\b|\bpython", script.replace("2 = the command crashed", "")), script)


def test_script():
    print("script: each branch under bash")
    rc, out = run_script("")
    ok("no code: exits 1", rc == 1, (rc, out))
    ok("no code: says the collector step did not finish, and where the data went",
       "the collector step did not finish (killed at its 300-minute limit, or crashed before reporting)" in out
       and "published or saved above" in out, out)
    for code, what in (("1", "more than 0.05 of collector runs failed"), ("2", "2 = the command crashed")):
        rc, out = run_script(code)
        ok(f"code {code}: exits 1", rc == 1, (rc, out))
        ok(f"code {code}: names the code and what it means", f"exited with code {code}" in out and what in out, out)
        ok(f"code {code}: does not claim the step did not finish", "did not finish" not in out, out)


def test_matrix():
    print("matrix: outcome x code x run cancelled x an earlier step failed")
    fail = next(s for s in job_steps(TEXT) if s["name"] == FAIL_STEP)
    rows = []
    for outcome, code, cancelled, job_failed in itertools.product(
            ("success", "failure", "cancelled", "skipped"), ("", "0", "1", "2"), (False, True), (False, True)):
        ctx = {"steps": {"refresh": {"outcome": outcome, "outputs": {"code": code} if code else {}}},
               "inputs": {}, "cancelled": cancelled, "job_failed": job_failed}
        got = evaluate(fail["if"], ctx)
        # the rule, stated independently of the expression: report unless the run was cancelled, the collector step
        # was skipped (build_only), or it reported code 0. A missing code is a step that never finished: report it.
        want = not cancelled and outcome != "skipped" and code != "0"
        rows.append((outcome, code or "''", cancelled, job_failed, got, want))
        ok(f"outcome={outcome} code={code or chr(39) * 2} cancelled={cancelled} earlier-step-failed={job_failed}: "
           f"{'runs' if want else 'skipped'}", got == want, f"got {'runs' if got else 'skipped'}")
    if VERBOSE:
        print("    outcome    code  cancelled  earlier-failed  fail-step")
        for o, c, ca, jf, g, _ in rows:
            print(f"    {o:10} {c:5} {str(ca):10} {str(jf):15} {'RUNS (red)' if g else 'skipped'}")
    print(f"    {sum(1 for r in rows if r[4])} of {len(rows)} rows run the fail step")


def simulate(inputs: dict, results: dict, cancelled: bool = False) -> tuple[str, dict]:
    """Run the job's steps in order by their own conditions. `results`: step name -> 'success' | 'failure', and for the
    collector step also its code (None = never written). Returns (conclusion, {name: 'ran'|'skipped'})."""
    steps, ctx = job_steps(TEXT), {"steps": {}, "inputs": inputs, "cancelled": cancelled, "job_failed": False}
    ran = {}
    for s in steps:
        if not evaluate(s["if"], ctx):
            ran[s["name"]] = "skipped"
            if s["id"]:
                ctx["steps"][s["id"]] = {"outcome": "skipped", "conclusion": "skipped", "outputs": {}}
            continue
        ran[s["name"]] = "ran"
        if s["name"] == FAIL_STEP:
            code = ctx["steps"].get("refresh", {}).get("outputs", {}).get("code", "")
            rc, _ = run_script(code)
            outcome = "success" if rc == 0 else "failure"
        else:
            outcome = results.get(s["name"], "success")
        if s["id"] == "refresh":
            code = results.get("code")
            ctx["steps"]["refresh"] = {"outcome": outcome, "conclusion": "success" if s["continue_on_error"] else outcome,
                                       "outputs": {} if code is None else {"code": code}}
        if outcome == "failure" and not s["continue_on_error"]:
            ctx["job_failed"] = True
    conclusion = "cancelled" if cancelled else "failure" if ctx["job_failed"] else "success"
    return conclusion, ran


def test_paths():
    print("paths: the whole job, from refresh.yml's own conditions")
    sched = {"build_only": None, "only": None, "full": None}
    cases = [
        ("scheduled, collectors ok, published", sched, {"Refresh data": "success", "code": "0"}, False, "success", False),
        ("over the threshold (code 1), published", sched, {"Refresh data": "failure", "code": "1"}, False, "failure", True),
        ("the command crashed (code 2), published", sched, {"Refresh data": "failure", "code": "2"}, False, "failure", True),
        ("collector step killed or timed out (no code), published", sched, {"Refresh data": "failure", "code": None}, False, "failure", True),
        ("killed, and GitHub reports the step as cancelled (no code)", sched, {"Refresh data": "cancelled", "code": None}, False, "failure", True),
        ("a gate stopped the publish, collectors ok", sched, {"Refresh data": "success", "code": "0", "Commit changed data": "failure"}, False, "failure", False),
        ("a gate stopped the publish and collectors over the threshold", sched,
         {"Refresh data": "failure", "code": "1", "Commit changed data": "failure"}, False, "failure", True),
        ("build_only, published", {"build_only": True}, {}, False, "success", False),
        ("build_only, a gate stopped the publish", {"build_only": True}, {"Commit changed data": "failure"}, False, "failure", False),
        ("a bad `only` input", {"only": "nope"}, {"Validate dispatch inputs": "failure"}, False, "failure", False),
        ("cancelled during the collectors (no code)", sched, {"Refresh data": "cancelled", "code": None}, True, "cancelled", False),
    ]
    for name, inputs, results, cancelled, want, fail_runs in cases:
        conclusion, ran = simulate(inputs, results, cancelled)
        ok(f"{name}: run {want}", conclusion == want, f"got {conclusion}; steps {ran}")
        ok(f"{name}: the fail step {'runs' if fail_runs else 'is skipped'}",
           (ran.get(FAIL_STEP) == "ran") == fail_runs, ran.get(FAIL_STEP))


def test_evaluator():
    print("evaluator: reads only what it understands, and the rules it applies are GitHub's")
    base = {"steps": {}, "inputs": {}, "cancelled": False, "job_failed": False}
    for bad in ("contains(inputs.only, 'x')", "github.event_name == 'schedule'", "steps.refresh.outputs.code > 0",
                "${{ format('{0}', 1) }}", "env.FOO == 'x'"):
        try:
            evaluate(bad, base)
            ok(f"refuses {bad!r}", False, "it evaluated")
        except Unreadable:
            ok(f"refuses {bad!r}", True)
    ok("no status function means success() && ...: skipped after a failure",
       not evaluate("inputs.only == ''", {**base, "job_failed": True}))
    ok("an output never written reads as '', so `code != '0'` alone is true for a skipped step (the #82 trap)",
       evaluate("steps.refresh.outputs.code != '0'", {**base, "steps": {"refresh": {"outcome": "skipped", "outputs": {}}}}))
    ok("loose equality: a boolean input is not the string 'true'", not loose_eq(True, "true") and loose_eq(None, False))
    always_variant = REVIEWED_IF.replace("!cancelled()", "always()")
    ctx = {**base, "cancelled": True, "steps": {"refresh": {"outcome": "failure", "outputs": {}}}}
    ok("the matrix can fail: an always() variant would run the step on a cancelled run",
       evaluate(always_variant, ctx) and not evaluate(REVIEWED_IF, ctx))


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_structure, test_script, test_matrix, test_paths, test_evaluator):
        try:
            case()
        except Exception as e:  # a case that raises is a failed case, not a lost run
            ok(f"{case.__name__} ran to the end", False, f"{type(e).__name__}: {e}")
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS[:20]) + (" ..." if len(FAILS) > 20 else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
