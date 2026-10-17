#!/usr/bin/env python3
"""Report how far this machine is from the CI runner, and with --install close the gap (issue #502).

    python3 .claude/skills/setup/setup_env.py             # report only; exit 1 if anything differs from CI
    python3 .claude/skills/setup/setup_env.py --install   # create the venv, install requirements, fetch Node
    python3 .claude/skills/setup/setup_env.py --venv DIR  # another venv location (or set CD_VENV)

What CI uses is read from .github/workflows/tests.yml on every run: the Python and Node versions and the
pip install line. This file holds no version number or requirements file name that could go stale.
The .claude/skills/run-tests/ci_tests.py script imports read_workflow() and the helpers below.

Standard library only; any python3 can run it.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
JOB = "suites"  # the job in tests.yml that installs and runs the check suites
# Where the venv and the fetched Node live: shared by every worktree, outside any repository. $CD_CACHE moves it.
CACHE = Path(os.environ.get("CD_CACHE") or Path.home() / ".cache" / "collegedash")
SHOTS = ROOT / ".claude" / "skills" / "evidence" / "shots.js"

# Prints the names (one per line) that are not installed in the interpreter it runs under.
MISSING_SNIPPET = (
    "import sys, importlib.metadata as m\n"
    "for n in sys.argv[1:]:\n"
    "    try: m.version(n)\n"
    "    except m.PackageNotFoundError: print(n)\n"
)


@dataclass
class Workflow:
    python: str  # "3.12"
    node: str  # "24"
    install: list  # the pip install line(s), as written in the workflow
    steps: list  # [(step name, command)] for every single-line `run:` that is not a pip install


def read_workflow(path: Path = WORKFLOW, job: str = JOB) -> Workflow:
    """Versions, the install line and the test commands of one job, straight from the workflow file."""
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#")]
    start = next((i for i, l in enumerate(lines) if re.fullmatch(rf"  {re.escape(job)}:\s*", l)), None)
    if start is None:
        sys.exit(f"{path.name} has no job named '{job}' any more: update JOB in {Path(__file__).name}")
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"  \S", lines[i])), len(lines))
    python = node = name = None
    install, steps = [], []
    for line in lines[start:end]:
        if re.match(r"\s*- ", line):
            name = None  # a new step
        if m := re.match(r"\s*(?:- )?name:\s*(.+?)\s*$", line):
            name = m.group(1).strip("\"'")
        elif m := re.match(r"""\s*python-version:\s*["']?([\d.]+)""", line):
            python = m.group(1)
        elif m := re.match(r"""\s*node-version:\s*["']?([\d.]+)""", line):
            node = m.group(1)
        elif (m := re.match(r"\s*run:\s*(\S.*?)\s*$", line)) and m.group(1)[0] not in "|>":
            cmd = m.group(1)  # a `run: |` block (the Summary table) is deliberately not picked up
            if cmd.split()[0] == "pip":
                install.append(cmd)
            else:
                steps.append((name or cmd, cmd))
    if not (python and node and steps):
        sys.exit(f"could not read Python version, Node version and test steps from job '{job}' in {path.name}")
    return Workflow(python, node, install, steps)


def venv_dir(python_version: str, arg: str | None = None) -> Path:
    default = CACHE / f"venv{python_version.replace('.', '')}"
    return Path(arg or os.environ.get("CD_VENV") or default).expanduser().absolute()


def venv_python(venv: Path) -> Path:
    return venv / "bin" / "python"  # not resolve()d: the venv only works when called by its own path


def _out(cmd: list) -> str | None:
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout + r.stderr).strip() if r.returncode == 0 else None


def python_version(python) -> str | None:
    out = _out([python, "--version"])
    return out.split()[-1] if out else None


def node_version(node) -> str | None:
    return _out([node, "--version"])


def node_major(version: str | None) -> str:
    return (version or "").lstrip("v").split(".")[0]


def node_cache_node(major: str) -> Path:
    return CACHE / f"node{major}" / "node_modules" / ".bin" / "node"


def pick_node(major: str) -> tuple[str | None, str | None]:
    """(path, version) of the first node whose major version is CI's: the one on PATH, then the cache.
    Falls back to the node on PATH, so the caller can still say which version ran."""
    on_path = shutil.which("node")
    cached = node_cache_node(major)
    found = []
    for candidate in (on_path, str(cached) if cached.exists() else None):
        if candidate and (v := node_version(candidate)):
            found.append((candidate, v))
            if node_major(v) == major:
                return candidate, v
    return found[0] if found else (None, None)


def requirement_files(wf: Workflow) -> list[Path]:
    """The files named with -r on the workflow's pip install line."""
    files = []
    for line in wf.install:
        toks = shlex.split(line)
        files += [ROOT / toks[i + 1] for i, t in enumerate(toks[:-1]) if t in ("-r", "--requirement")]
    return files


def missing_packages(py, wf: Workflow) -> list[str]:
    """Requirement names from the workflow's -r files that the venv does not have installed."""
    names = []
    for f in requirement_files(wf):
        for line in f.read_text(encoding="utf-8").splitlines():
            if m := re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line.split("#")[0]):
                names.append(m.group(1))
    out = _out([py, "-c", MISSING_SNIPPET, *names])
    return names if out is None else out.split()  # "" means nothing is missing; None means it could not run


def run(cmd: list, **kw) -> None:
    print("+", " ".join(shlex.quote(str(c)) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def make_venv(wf: Workflow, venv: Path) -> None:
    venv.parent.mkdir(parents=True, exist_ok=True)
    if system_python := shutil.which(f"python{wf.python}"):
        try:
            run([system_python, "-m", "venv", venv])
            return
        except subprocess.CalledProcessError:
            print(f"python{wf.python} -m venv failed (no ensurepip?); trying uv", file=sys.stderr)
    if shutil.which("uv"):
        run(["uv", "venv", "--seed", "--python", wf.python, venv])  # --seed puts pip in the venv
        return
    sys.exit(f"no working python{wf.python} and no uv on PATH: install Python {wf.python}, then run this again")


def pip_install_prefix(py: Path) -> list:
    """How to run `install` for this venv: its own pip, else uv, else bootstrap pip with ensurepip."""
    if _out([py, "-m", "pip", "--version"]):
        return [py, "-m", "pip", "install"]
    if shutil.which("uv"):  # a venv made by plain `uv venv` has no pip
        return ["uv", "pip", "install", "--python", py]
    run([py, "-m", "ensurepip", "--upgrade"])
    return [py, "-m", "pip", "install"]


def install_venv(wf: Workflow, venv: Path) -> None:
    py = venv_python(venv)
    if not (python_version(py) or "").startswith(wf.python + "."):
        make_venv(wf, venv)
    prefix = pip_install_prefix(py)
    for line in wf.install:  # the workflow's own arguments, run with this venv's installer
        toks = shlex.split(line)
        run([*prefix, *toks[2:]], cwd=ROOT)  # toks = ["pip", "install", ...]


def install_node(wf: Workflow) -> None:
    prefix = CACHE / f"node{wf.node}"
    prefix.mkdir(parents=True, exist_ok=True)
    npm = shutil.which("npm") or sys.exit("npm is not on PATH, so Node cannot be fetched")
    # The `node` package on npm ships the official binary: a user-level install, no root, no nvm.
    run([npm, "install", "--prefix", prefix, "--no-audit", "--no-fund", "--loglevel=error", f"node@{wf.node}"])


def report(wf: Workflow, venv: Path) -> bool:
    ok = True
    print(f"CI ({WORKFLOW.relative_to(ROOT)}): Python {wf.python}, Node {wf.node}")
    py = venv_python(venv)
    pv = python_version(py)
    good = bool(pv) and pv.startswith(wf.python + ".")
    ok &= good
    print(f"  python  {'ok     ' if good else 'MISSING'} venv {venv}  ({'Python ' + pv if pv else 'not created'})")
    if good:
        missing = missing_packages(py, wf)
        ok &= not missing
        print(f"  pip     {'ok     ' if not missing else 'MISSING'} "
              f"{', '.join(str(f.relative_to(ROOT)) for f in requirement_files(wf))}"
              f"{'' if not missing else '  not installed: ' + ', '.join(missing)}")
    node, nv = pick_node(wf.node)
    good = node_major(nv) == wf.node
    ok &= good
    print(f"  node    {'ok     ' if good else 'DIFFERS'} {node or 'none found'}  ({nv or 'not found'}; CI uses {wf.node})")
    shots = _out(["node", SHOTS, "--check"]) if SHOTS.exists() else None
    print(f"  browser {'ok     ' if shots else 'MISSING'} {shots or 'Playwright did not start: see the evidence skill'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--install", action="store_true", help="create the venv, install requirements, fetch Node")
    ap.add_argument("--venv", help="venv location (default: $CD_VENV, else venv<ver> in ~/.cache/collegedash or $CD_CACHE)")
    args = ap.parse_args()
    wf = read_workflow()
    venv = venv_dir(wf.python, args.venv)
    if args.install:
        install_venv(wf, venv)
        if node_major(pick_node(wf.node)[1]) != wf.node:
            try:
                install_node(wf)
            except (subprocess.CalledProcessError, SystemExit) as e:
                print(f"could not fetch Node {wf.node} ({e}); results must say which Node ran", file=sys.stderr)
        print()
    ok = report(wf, venv)
    if ok:
        print(f"Next: export CD_VENV={venv}   then   python3 .claude/skills/run-tests/ci_tests.py")
    else:
        print("Not the same as CI yet. Run again with --install, or read the setup skill for what to do by hand.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
