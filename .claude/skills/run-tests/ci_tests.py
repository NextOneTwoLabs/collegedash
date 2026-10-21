#!/usr/bin/env python3
"""Run the CI check suites on this machine the way .github/workflows/tests.yml runs them (issue #502).

    python3 .claude/skills/run-tests/ci_tests.py --list        # show the steps and floors read from tests.yml; run nothing
    python3 .claude/skills/run-tests/ci_tests.py               # run every step (more than 10 minutes here: run it in the background)
    python3 .claude/skills/run-tests/ci_tests.py --only node   # only steps whose name or command contains "node" (repeatable)
    python3 .claude/skills/run-tests/ci_tests.py --logs DIR    # keep one full log per step in DIR (default: a new temp directory)
    python3 .claude/skills/run-tests/ci_tests.py --main DIR    # DIR = clean checkout of origin/main, for the timing comparison below

The steps, their commands and their --min-checks floors are read from tests.yml every time, so nothing here
can drift from the workflow. The venv's Python and a Node of CI's major version (if one can be found) are put first
on PATH, so the workflow's `python ...` lines and the node that run_node_suites.py starts are the right ones.
The summary at the end says which Python and Node actually ran: paste it into your report.

Two local quirks are handled, and each one is named in the output when it happens:
  * Node before 24 writes junit without file names, so run_node_suites.py reports "no tests" or "0 passing". The
    node step is then run directly (node --test on the same glob and netguard preload) and judged by its own counts.
  * tests/recs_perf.test.mjs measures milliseconds and can fail when this machine is busy. When it is the only
    thing that failed, it is rerun alone. If it passes alone, or fails alone in the --main checkout too, the step is
    marked TIMING, not FAIL. If it fails alone and no --main was given, it stays FAIL until compared with main.

Exit code: 0 every step passed; 1 something failed; 2 nothing failed except timing tests that passed alone.
Standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup"))
import setup_env as env  # noqa: E402  (one place reads tests.yml and finds the venv and node)

ROOT = env.ROOT
TIMING_SUITES = {"recs_perf.test.mjs"}  # measure wall-clock time; known to fail under load on this machine
NETGUARD = "./tests/netguard/netguard.mjs"  # the preload run_node_suites.py gives every Node suite (#345)
NODE_BLIND = re.compile(r"reported 0 passing|reported no tests")  # what run_node_suites.py says on Node < 24
# How the three runners in .github/scripts/ state their count: "N checks passed in 3.1s" / "N checks passed across 40
# discovered suites" / "N tests passed in ..." when they pass; "(reported N passing of ..." / "(reported 7/9 checks)" when not.
COUNT_LINE = re.compile(r"(\d[\d,]*) (?:checks|tests) passed\b|reported (\d[\d,/]*) (?:checks|passing)")
BAD = re.compile(r"^\s*(not ok\b|::error|Traceback)|\bFAIL\b")  # lines worth showing when something failed
GOOD = re.compile(r"passed in [\d.]+s|^# (?:tests|pass|fail|skipped) ")  # the totals


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def floor_of(cmd: str) -> str:
    m = re.search(r"--min-checks\s+(\d+)", cmd)
    return m.group(1) if m else "-"


def node_discovery() -> str:
    """The glob run_node_suites.py hands to node, read from the script so the direct run uses the same one."""
    path = ROOT / ".github" / "scripts" / "run_node_suites.py"
    m = re.search(r'^DISCOVERY\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), re.M) if path.exists() else None
    return m.group(1) if m else "tests/**/*.test.mjs"


def run_env(py: Path | None, node: str | None) -> dict:
    e = dict(os.environ)
    front = []
    if py and py.exists():
        front.append(str(py.parent))
        e["VIRTUAL_ENV"] = str(py.parent.parent)
        e.pop("PYTHONHOME", None)
    if node:
        front.append(str(Path(node).parent))
    e["PATH"] = os.pathsep.join(front + [e.get("PATH", "")])
    return e


def run_logged(argv: list, e: dict, log: Path, verbose: bool, cwd: Path = ROOT) -> tuple[int, float, str]:
    """Run argv from `cwd` (the repository root), tee everything to `log`, return (exit code, seconds, output)."""
    started = time.monotonic()
    chunks = []
    with log.open("w", encoding="utf-8") as fh:
        fh.write("$ " + " ".join(shlex.quote(a) for a in argv) + "\n")
        proc = subprocess.Popen(argv, cwd=cwd, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            fh.write(line)
            chunks.append(line)
            if verbose:
                sys.stdout.write(line)
        code = proc.wait()
    return code, time.monotonic() - started, "".join(chunks)


def failing_files(text: str) -> set | None:
    """Test files named by TAP `not ok` entries, or None when any failure cannot be tied to a file."""
    lines = text.splitlines()
    files: set = set()
    for i, line in enumerate(lines):
        if re.match(r"not ok \d+", line):
            for nxt in lines[i + 1:i + 14]:
                if m := re.search(r"location: '(.+?\.m?js):\d+:\d+'", nxt):
                    files.add(Path(m.group(1)).name)
                    break
            else:
                return None
    return files or None


def tap_counts(text: str) -> tuple[int, int] | None:
    """(pass, fail) from node's `# pass N` and `# fail N` lines."""
    p = re.findall(r"^# pass (\d+)", text, re.M)
    f = re.findall(r"^# fail (\d+)", text, re.M)
    return (int(p[-1]), int(f[-1])) if p and f else None


def highlights(text: str, limit: int = 20) -> list:
    """The failures (first `limit`) and then the last few total lines, instead of the whole log."""
    lines = text.splitlines()
    bad = [l.rstrip() for l in lines if BAD.search(l)]
    out = bad[:limit] + ([f"... {len(bad) - limit} more failure lines in the log"] if len(bad) > limit else [])
    return out + [l.rstrip() for l in lines if GOOD.search(l)][-4:]


def result_of(name: str, cmd: str, code: int, secs: float, text: str) -> dict:
    counts = COUNT_LINE.findall(text)
    n = (counts[-1][0] or counts[-1][1]).replace(",", "") if counts else "?"
    if code != 0 and (tap := tap_counts(text)):
        n = str(tap[0])  # a failed Node run: show node's own `# pass N`, not the runner's "reported N passing" (a junit sum)
    return {"name": name, "status": "PASS" if code == 0 else "FAIL", "checks": n, "secs": secs, "floor": floor_of(cmd),
            "note": ""}


def rerun_timing(files: set, e: dict, logdir: Path, stem: str, verbose: bool, main: Path | None) -> str | None:
    """Rerun failing timing suites alone. Returns why the failure is not (yet) a real one, or None if it still is."""
    cmd = ["node", "--import", NETGUARD, "--test", *[f"tests/{f}" for f in sorted(files)]]
    print(f"  only timing tests failed ({', '.join(sorted(files))}); rerunning them alone: {' '.join(cmd)}")
    code, secs, _ = run_logged(cmd, e, logdir / f"{stem}-rerun-alone.log", verbose)
    print(f"  alone: {'PASS' if code == 0 else 'FAIL'} in {secs:.0f}s")
    if code == 0:
        return "failed under load, passed alone"
    if not main:
        print("  it fails alone too. Run the same command in a clean copy of origin/main (--main DIR does it) before calling it real")
        return None
    mcode, msecs, _ = run_logged(cmd, e, logdir / f"{stem}-rerun-on-main.log", verbose, cwd=main)
    print(f"  same command alone in {main} (main): {'PASS' if mcode == 0 else 'FAIL'} in {msecs:.0f}s")
    return "fails alone here and also on main: the machine, not this change" if mcode != 0 else None


def run_node_direct(cmd: str, e: dict, logdir: Path, stem: str, verbose: bool) -> dict:
    argv = ["node", "--import", NETGUARD, "--test", "--test-reporter=tap", node_discovery()]
    print(f"  Node before 24 cannot name test files in junit, so run_node_suites.py cannot judge the run.\n"
          f"  Running node directly: {' '.join(argv)}")
    code, secs, text = run_logged(argv, e, logdir / f"{stem}-direct.log", verbose)
    counts = tap_counts(text)
    floor = floor_of(cmd)
    ok = code == 0 and counts is not None and counts[1] == 0 and (floor == "-" or counts[0] >= int(floor))
    return {"status": "PASS" if ok else "FAIL", "checks": str(counts[0]) if counts else "?", "secs": secs,
            "floor": floor, "note": "run directly (per-file 'ran something' guard unavailable before Node 24)",
            "text": text, "code": code}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true", help="show the steps and floors read from tests.yml, then stop")
    ap.add_argument("--only", action="append", default=[], metavar="WORD", help="run only steps containing WORD")
    ap.add_argument("--logs", help="directory for one full log per step (default: a new temp directory)")
    ap.add_argument("--venv", help="venv to use (default: $CD_VENV, else ~/.cache/collegedash/venv<ver>)")
    ap.add_argument("--main", help="a clean checkout of origin/main, to compare a timing test that still fails when rerun alone")
    ap.add_argument("--verbose", action="store_true", help="also print every line of every step as it runs")
    args = ap.parse_args()

    main = Path(args.main).expanduser().absolute() if args.main else None
    wf = env.read_workflow()
    venv = env.venv_dir(wf.python, args.venv)
    py = env.venv_python(venv)
    pv = env.python_version(py)
    if not pv:
        py = None
        pv = env.python_version(shutil.which("python") or "python")
    node, nv = env.pick_node(wf.node)
    py_ok = bool(pv) and pv.startswith(wf.python + ".") and py is not None
    node_ok = env.node_major(nv) == wf.node
    e = run_env(py, node)

    print(f"CI ({env.WORKFLOW.relative_to(ROOT)}): Python {wf.python}, Node {wf.node}")
    print(f"here: Python {pv or 'none'} ({'venv ' + str(venv) if py else 'NO VENV at ' + str(venv)}), Node {nv or 'none'}")
    if not py_ok:
        print(f"  WARNING Python is not CI's {wf.python}: run setup first, and say in your report which Python ran")
    if not node_ok:
        print(f"  WARNING Node is not CI's {wf.node}: run setup first, and say in your report which Node ran")

    steps = [s for s in wf.steps if not args.only or any(w.lower() in (s[0] + " " + s[1]).lower() for w in args.only)]
    if not steps:
        print(f"no step in tests.yml matches {args.only}; the steps are: {[s[0] for s in wf.steps]}", file=sys.stderr)
        return 1
    print()
    for i, (name, cmd) in enumerate(steps, 1):
        print(f"{i}. {name}\n     {cmd}\n     floor {floor_of(cmd)}")
    if wf.skipped:
        print(f"\nNOT RUN here: {len(wf.skipped)} multi-line `run: |` step(s) in tests.yml, which this script does not read: "
              f"{'; '.join(wf.skipped)}.\n     If one of them runs tests, run its commands by hand and report them.")
    if args.list:
        return 0

    logdir = Path(args.logs).expanduser() if args.logs else Path(tempfile.mkdtemp(prefix="ci-tests-"))
    logdir.mkdir(parents=True, exist_ok=True)
    print(f"\nlogs: {logdir}\n", flush=True)

    rows = []
    for i, (name, cmd) in enumerate(steps, 1):
        stem = f"{i:02d}-{slug(name)}"
        print(f"== [{i}/{len(steps)}] {name}", flush=True)
        code, secs, text = run_logged(shlex.split(cmd), e, logdir / f"{stem}.log", args.verbose)
        row = result_of(name, cmd, code, secs, text)
        if code != 0 and "run_node_suites" in cmd and not node_ok and NODE_BLIND.search(text):
            direct = run_node_direct(cmd, e, logdir, stem, args.verbose)
            code, text = direct.pop("code"), direct.pop("text")
            row.update(direct)
        if row["status"] == "FAIL" and (files := failing_files(text)) and files <= TIMING_SUITES:
            why = rerun_timing(files, e, logdir, stem, args.verbose, main)
            if why:
                note = f"{', '.join(sorted(files))} {why}"
                row.update(status="TIMING", note="; ".join(filter(None, [row["note"], note])))
        for line in highlights(text):
            print("   ", line)
        print(f"   -> {row['status']} (exit {code}) in {row['secs']:.0f}s; log {logdir / (stem + '.log')}\n", flush=True)
        rows.append(row)

    out = [f"{'step':<46}{'result':<8}{'checks':>8}{'floor':>7}{'time':>8}"]
    for r in rows:
        out.append(f"{r['name'][:45]:<46}{r['status']:<8}{r['checks']:>8}{r['floor']:>7}{r['secs']:>7.0f}s"
                   + (f"  {r['note']}" if r["note"] else ""))
    out.append(f"ran on: Python {pv} (CI {wf.python}){'' if py_ok else '  DIFFERS'}; Node {nv} (CI {wf.node}){'' if node_ok else '  DIFFERS'}")
    summary = "\n".join(out)
    (logdir / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    print(summary)
    if any(r["status"] == "FAIL" for r in rows):
        return 1
    return 2 if any(r["status"] == "TIMING" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
