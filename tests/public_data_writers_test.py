"""Collectors write under public/data only to rpi/ and registry.json (issue #90).

    python tests/public_data_writers_test.py

Offline and static: it reads collect/*.py, never runs them.

Why: when build or validate fails after the rebase, refresh.yml's publish_sources_only resets everything under
public/data to main's state except public/data/rpi and public/data/registry.json, the two parts that are collected
rather than built. It keeps no list of build outputs, so that a build output renamed on main mid-run cannot make the
restore fail and lose the run's collection (#90). The price is that anything else a collector writes under public/data
would be silently reset on the sources branch of a gated run. This suite turns that into a red CI run instead.

What it checks: the public/data path constants collect/common.py defines (every name assigned from PUBLIC_DATA_DIR, or
from one of those) are referenced in collect/ only where they are defined, except RPI_OUT_DIR and REGISTRY_PATH; and no
module in collect/ spells a public/data path itself. A collector that needs to write somewhere new under public/data
must add that path to the exclusions in publish_sources_only and to COLLECTED here, together.
"""

from __future__ import annotations

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECT = os.path.join(ROOT, "collect")
COMMON = os.path.join(COLLECT, "common.py")
REFRESH = os.path.join(ROOT, ".github", "workflows", "refresh.yml")
COLLECTED = {"RPI_OUT_DIR": "public/data/rpi", "REGISTRY_PATH": "public/data/registry.json"}
# a literal public/data path, either as one string or as os.path.join(..., "public", "data", ...)
LITERAL = re.compile(r"""["']public/data|["']public["']\s*,\s*["']data["']""")

CHECKS: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(cond), detail))


def public_data_names(src: str) -> set[str]:
    """Module-level names in common.py whose value is built from PUBLIC_DATA_DIR, directly or through another such name."""
    names = {"PUBLIC_DATA_DIR"}
    changed = True
    tree = ast.parse(src)
    while changed:
        changed = False
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                used = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
                if used & names and node.targets[0].id not in names:
                    names.add(node.targets[0].id)
                    changed = True
    return names


def offenders(sources: dict[str, str], names: set[str]) -> list[str]:
    """Every place in `sources` that names a public/data path other than the collected ones, as path:line: text."""
    out = []
    for path, src in sources.items():
        tree = ast.parse(src)
        defined = {id(n.targets[0]) for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1}
        lines = src.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in names and node.id not in COLLECTED and id(node) not in defined:
                if os.path.basename(path) == "common.py" and _is_definition_rhs(tree, node, names):
                    continue
                out.append(f"{path}:{node.lineno}: {lines[node.lineno - 1].strip()}")
            elif isinstance(node, ast.Attribute) and node.attr in names and node.attr not in COLLECTED:
                out.append(f"{path}:{node.lineno}: {lines[node.lineno - 1].strip()}")
        for i, line in enumerate(lines, 1):
            code = line.split("#", 1)[0]
            if LITERAL.search(code) and not (os.path.basename(path) == "common.py" and re.match(r"\s*[A-Z_]+\s*=", line)):
                out.append(f"{path}:{i}: {line.strip()}")
    return sorted(set(out))


def _is_definition_rhs(tree: ast.Module, node: ast.Name, names: set[str]) -> bool:
    """True when `node` sits on the right of a module-level assignment that defines another public/data name."""
    for stmt in tree.body:
        if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id in names and any(n is node for n in ast.walk(stmt.value))):
            return True
    return False


def main() -> int:
    common_src = open(COMMON, encoding="utf-8").read()
    names = public_data_names(common_src)
    ok("common.py defines the two collected paths from PUBLIC_DATA_DIR", set(COLLECTED) <= names, sorted(names))
    ok("and the built ones too (the check is not vacuous)", {"PROGRAMS_OUT_DIR", "CAMPS_OUT_DIR", "COMMITS_OUT_DIR"} <= names, sorted(names))

    sources = {os.path.relpath(os.path.join(COLLECT, f), ROOT).replace(os.sep, "/"): open(os.path.join(COLLECT, f), encoding="utf-8").read()
               for f in sorted(os.listdir(COLLECT)) if f.endswith(".py")}
    ok("collect/ has modules to read", len(sources) > 5, len(sources))
    bad = offenders(sources, names)
    ok("collect/ names no public/data path except rpi/ and registry.json", not bad, "\n    ".join([""] + bad))

    # controls: the check sees a collector that writes a built path, or spells a public/data path itself
    fake = {"collect/fake.py": "import os\nfrom collect import common\n"
                               "common.write_json(os.path.join(common.CAMPS_OUT_DIR, 'x.json'), {})\n"}
    ok("control: a collector writing under CAMPS_OUT_DIR is caught", offenders(fake, names) == [
        "collect/fake.py:3: common.write_json(os.path.join(common.CAMPS_OUT_DIR, 'x.json'), {})"], offenders(fake, names))
    fake = {"collect/fake.py": "import os\nP = os.path.join(ROOT, 'public', 'data', 'extra.json')\n"}
    ok("control: a literal public/data path is caught", len(offenders(fake, names)) == 1, offenders(fake, names))
    fake = {"collect/fake.py": "from collect import common\ncommon.write_json(common.REGISTRY_PATH, {})\n"}
    ok("control: writing the registry is allowed", offenders(fake, names) == [], offenders(fake, names))

    # the workflow's restore excludes exactly these two, and nothing else under public/data
    yml = open(REFRESH, encoding="utf-8").read()
    ok("refresh.yml's gate restore keeps exactly rpi/ and registry.json",
       "find public/data -mindepth 1 -maxdepth 1 ! -name rpi ! -name registry.json -exec rm -rf {} +" in yml
       and "git checkout FETCH_HEAD -- public/data ':(exclude)public/data/rpi' ':(exclude)public/data/registry.json'" in yml)

    fails = 0
    for name, good, detail in CHECKS:
        if not good:
            fails += 1
            print(f"  FAIL {name} - {detail}")
    print(f"{len(CHECKS) - fails} of {len(CHECKS)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
