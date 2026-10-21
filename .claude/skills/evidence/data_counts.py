#!/usr/bin/env python3
"""Before/after counts of what a data change did to the published data (issue #502). Offline: it reads git, never the network.

    python3 .claude/skills/evidence/data_counts.py                       # origin/main -> HEAD, under public/data
    python3 .claude/skills/evidence/data_counts.py --before a83a32086~5 --after a83a32086
    python3 .claude/skills/evidence/data_counts.py --after DIR          # DIR = a checkout or a build output laid out like the repo
    python3 .claude/skills/evidence/data_counts.py --count division --count roster --count commitments

--before and --after each take a git revision, or a directory that has the repository's layout (a worktree, or the
temporary tree a build wrote). --path (repeatable) is the part of the tree to compare, a folder or a file; the profile tables
(items 2 and 3 below) appear only when it takes in public/data/programs. --count FIELD (repeatable)
adds a table of that profile field over every public/data/programs/<slug>.json, before and after.

It prints Markdown, ready to paste into a report or PR description:
  1. files added, removed and changed, per folder;
  2. for the program profiles that changed (programs/index.json is not one): how many changed in each top-level field
     (--ignore skips fields, `_build` by default, that change on every build; a profile that differs only there is
     counted on its own line, not hidden);
  3. one table per --count: profiles where the field is present and non-empty, items in it (lists and objects),
     and its values when there are at most 12 distinct scalars (so `division` shows D1/D2/D3).
Exact counts here describe one tree on one day. They go in a PR as evidence; a test never pins them on live data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROFILES = "public/data/programs"


def blob_id(data: bytes) -> str:
    """The id a revision holds for a file with these bytes, so a directory side and a revision side agree."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class Tree:
    """The files of one revision or directory: path -> id (equal ids mean equal bytes), and a way to read them."""

    def __init__(self, spec: str, paths: list[str]):
        self.spec, self.ids, self._dir = spec, {}, None
        if os.path.isdir(spec):
            self._dir = Path(spec)
            for p in paths:
                top = self._dir / p
                for f in sorted(top.rglob("*")) if top.is_dir() else [top] if top.is_file() else []:
                    if f.is_file() and not f.is_symlink():
                        self.ids[str(f.relative_to(self._dir))] = blob_id(f.read_bytes())
            return
        out = git("ls-tree", "-r", "-z", spec, "--", *paths).split("\0")
        for rec in filter(None, out):
            meta, path = rec.split("\t", 1)
            if meta.split()[1] == "blob":
                self.ids[path] = meta.split()[2]

    def read(self, path: str) -> bytes:
        if self._dir:
            return (self._dir / path).read_bytes()
        return subprocess.run(["git", "cat-file", "blob", self.ids[path]], capture_output=True, check=True).stdout

    def json(self, path: str):
        try:
            return json.loads(self.read(path))
        except (ValueError, KeyError):
            return None


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def folder(path: str, depth: int) -> str:
    return "/".join(path.split("/")[:depth]) or path


def dig(obj, dotted: str):
    for part in dotted.split("."):
        obj = obj.get(part) if isinstance(obj, dict) else None
    return obj


def present(v) -> bool:
    return v not in (None, "", [], {}, False)


def file_table(a: Tree, b: Tree, depth: int) -> list[str]:
    rows = defaultdict(lambda: [0, 0, 0])
    for p in a.ids.keys() | b.ids.keys():
        row = rows[folder(p, depth)]
        if p not in a.ids:
            row[0] += 1
        elif p not in b.ids:
            row[1] += 1
        elif a.ids[p] != b.ids[p]:
            row[2] += 1
    out = ["| folder | added | removed | changed |", "| --- | ---: | ---: | ---: |"]
    for k in sorted(rows):
        if any(rows[k]):
            out.append(f"| {k} | " + " | ".join(str(n) for n in rows[k]) + " |")
    if len(out) == 2:
        out.append("| (no file differs) | 0 | 0 | 0 |")
    return out


def field_table(a: Tree, b: Tree, ignore: set) -> list[str]:
    per = Counter()
    real = ignored_only = 0
    for p in sorted(a.ids.keys() & b.ids.keys()):
        if not p.startswith(PROFILES + "/") or a.ids[p] == b.ids[p]:
            continue
        x, y = a.json(p) or {}, b.json(p) or {}
        if not (x.get("slug") and y.get("slug")):  # programs/index.json sits beside the profiles; it is not one
            continue
        fields = {k for k in (x.keys() | y.keys()) - ignore if x.get(k) != y.get(k)}
        per.update(fields)
        if fields:
            real += 1
        else:
            ignored_only += 1
    out = [f"{real} program profiles changed in a field that counts; {ignored_only} more differ only in {', '.join(sorted(ignore))}.", "",
           "| field | profiles where it changed |", "| --- | ---: |"]
    out += [f"| {k} | {n} |" for k, n in per.most_common()] or ["| (none) | 0 |"]
    return out


def count_table(a: Tree, b: Tree, field: str) -> list[str]:
    def tally(t: Tree):
        n = items = 0
        vals = Counter()
        for p in t.ids:
            if p.startswith(PROFILES + "/") and p.endswith(".json"):
                prof = t.json(p)
                v = dig(prof, field) if isinstance(prof, dict) and prof.get("slug") else None
                if present(v):
                    n += 1
                    if isinstance(v, (list, dict)):
                        items += len(v)
                    else:
                        vals[str(v)] += 1
        return n, items, vals

    (na, ia, va), (nb, ib, vb) = tally(a), tally(b)
    out = [f"`{field}`", "", "| | before | after |", "| --- | ---: | ---: |",
           f"| profiles with it | {na} | {nb} |"]
    if ia or ib:
        out.append(f"| items in it | {ia} | {ib} |")
    if 0 < len(va | vb) <= 12:
        out += [f"| = {k} | {va[k]} | {vb[k]} |" for k in sorted(va.keys() | vb.keys())]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--before", default="origin/main", help="git revision or directory (default origin/main)")
    ap.add_argument("--after", default="HEAD", help="git revision or directory (default HEAD)")
    ap.add_argument("--path", action="append", help="part of the tree to compare (default public/data)")
    ap.add_argument("--count", action="append", default=[], metavar="FIELD", help="dotted profile field to count, e.g. division")
    ap.add_argument("--ignore", action="append", default=None, metavar="FIELD", help="top-level profile field to leave out (default _build)")
    ap.add_argument("--depth", type=int, default=3, help="folder depth for the file table (default 3: public/data/programs)")
    args = ap.parse_args()
    paths = [p.strip().removeprefix("./").rstrip("/") for p in (args.path or ["public/data"])]
    ignore = set(args.ignore or ["_build"])
    # The profile tables only make sense when the compared part of the tree takes in the profiles.
    profiles_in_scope = any(PROFILES == p or PROFILES.startswith(p + "/") or p.startswith(PROFILES + "/") for p in paths)
    if args.count and not profiles_in_scope:
        sys.exit(f"--count reads the program profiles, which are under {PROFILES}: add --path {PROFILES}, or leave --path out.")
    a, b = Tree(args.before, paths), Tree(args.after, paths)
    print(f"Data change: `{args.before}` -> `{args.after}`, under {', '.join(paths)} (read from git/disk only; nothing fetched)\n")
    print("\n".join(file_table(a, b, args.depth)) + "\n")
    if profiles_in_scope:
        print("\n".join(field_table(a, b, ignore)) + "\n")
    for f in args.count:
        print("\n".join(count_table(a, b, f)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
