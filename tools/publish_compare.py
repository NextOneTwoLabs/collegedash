"""Compare two built public/data trees for a division switch (issue #94, the D3 publish plan's test plan).

    python tools/publish_compare.py BEFORE_DATA_DIR AFTER_DATA_DIR

BEFORE is main's own fresh build, AFTER the switch branch's build (each a `public/data` directory). Prints one
line per difference and a summary; exit 0 when there is none, 1 otherwise. Reads two trees, writes nothing.

Checked:
  - trends/index.json is identical apart from `updated` (trends.py writes now_iso() there, so a byte comparison
    could never pass; Huatuo's plan review on #94). Trends counts D1 only, so a D3 switch must not move it;
  - every row of programs/index.json in the divisions that were already published, and every one of their
    profiles, is identical apart from `builtAt` / `_build.builtAt`.
Rows of a newly published division are listed as a count, not compared.
"""

from __future__ import annotations

import json
import os
import sys


def _read(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _mask(doc, keys: tuple[str, ...]):
    if isinstance(doc, dict):
        return {k: _mask(v, keys) for k, v in doc.items() if k not in keys}
    return doc


def compare_trends(before_dir: str, after_dir: str) -> list[str]:
    a, b = _read(os.path.join(before_dir, "trends", "index.json")), _read(os.path.join(after_dir, "trends", "index.json"))
    if a is None or b is None:
        return [f"trends/index.json is missing from {'BEFORE' if a is None else 'AFTER'}"]
    a, b = {k: v for k, v in a.items() if k != "updated"}, {k: v for k, v in b.items() if k != "updated"}
    if a == b:
        return []
    keys = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    return [f"trends/index.json differs apart from `updated`, in: {', '.join(keys)}"]


def compare_programs(before_dir: str, after_dir: str) -> tuple[list[str], dict[str, int]]:
    """(differences, new rows by division) for the divisions BEFORE already published."""
    a, b = _read(os.path.join(before_dir, "programs", "index.json")), _read(os.path.join(after_dir, "programs", "index.json"))
    if a is None or b is None:
        return [f"programs/index.json is missing from {'BEFORE' if a is None else 'AFTER'}"], {}
    old_divs = {r.get("division") for r in a.get("programs") or []}
    before = {r["slug"]: r for r in a.get("programs") or []}
    after = {r["slug"]: r for r in b.get("programs") or []}
    out: list[str] = []
    new: dict[str, int] = {}
    for slug in sorted(set(before) - set(after)):
        out.append(f"programs {slug}: published before, not after")
    for slug, row in sorted(after.items()):
        if slug not in before:
            if row.get("division") in old_divs:
                out.append(f"programs {slug}: a new {row.get('division')} row")
            else:
                new[row.get("division")] = new.get(row.get("division"), 0) + 1
            continue
        if _mask(row, ("builtAt",)) != _mask(before[slug], ("builtAt",)):
            out.append(f"programs {slug}: index row differs apart from builtAt")
        pa = _read(os.path.join(before_dir, "programs", f"{slug}.json"))
        pb = _read(os.path.join(after_dir, "programs", f"{slug}.json"))
        if _mask(pa, ("builtAt",)) != _mask(pb, ("builtAt",)):
            out.append(f"programs {slug}: profile differs apart from builtAt")
    return out, new


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__)
        return 2
    before, after = argv
    diffs = compare_trends(before, after)
    prog_diffs, new = compare_programs(before, after)
    diffs += prog_diffs
    for line in diffs:
        print(line)
    print(f"publish_compare: {len(diffs)} difference(s); newly published rows by division: {new or 'none'}")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
