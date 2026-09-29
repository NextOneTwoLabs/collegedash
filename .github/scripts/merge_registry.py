#!/usr/bin/env python3
"""Merge public/data/registry.json after the refresh's rebase, field by field, main winning (issue #132).

    python .github/scripts/merge_registry.py --base <merge-base> --main FETCH_HEAD --run <pre-rebase commit>

Why this exists
---------------
The refresh workflow's commit step rebases the run's data commit onto main with `-X theirs`, so on any
conflicting hunk the RUN's copy wins. That is right for collected files, and wrong for the registry: it is
collected in one field only, and hand-edited through PRs in every other. A run that wrote a program's
`athletics.platform` next to a line main changed mid-run (a membership move, a hold, a skipReason) silently
put main's edit back the way it was, and the rebuild then published from that reverted registry.

So after every rebase the step replaces whatever `-X theirs` left in public/data/registry.json with this
script's output, a three-way merge of the registry as JSON:

  base  the registry at the merge base of the run's commit and main (what the run started from);
  main  the registry on main now (FETCH_HEAD);
  run   the registry the run committed (its commit before any rebase, never an amended retry).

The rules (owner decisions on #132, 2026-09-28):

  * The run did not change the registry (its bytes equal base's): main's bytes, exactly. No reformat.
  * A refresh may change `programs[].athletics.platform` and nothing else. collect/athletics_site.py
    `_persist_platform` is its one registry writer, through common.update_registry, whose save also sets
    the top-level `updated` date, so `updated` is accepted as that write's side effect (see below).
  * Each platform the run changed is applied to main's registry only where main left that program's
    platform as base had it, and only to a program still in main's `programs`. Where main changed it too,
    main's value stands (a ::warning names the program). Where main removed the program or moved it to
    `heldPrograms`, the detection is dropped (a ::warning again): a run never republishes a program main
    took out. A dropped detection costs one probe request on the next run.
  * Any other change the run made (another field, a program added, removed or reordered, `heldPrograms`,
    another top-level key), or any of the three copies not parsing, is unexpected for a refresh: exit 1,
    write nothing, and the step keeps the collection on a refresh-sources/* branch instead of publishing.
  * `updated`: main's, unless main left it alone and a platform of the run's was actually applied.

The output is written the way common.write_json writes the registry (indent 2, ensure_ascii=False, a
trailing newline), so a merge that applies nothing produces main's bytes and one that applies a platform
changes that line alone. When nothing is applied the script writes main's bytes as they are, whatever
their format.

Exit status: 0 when the registry was written; 1 when the run's change is unexpected, a copy cannot be read or
parsed, or the write failed. Anything else (a crash) is also non-zero, and the step fails closed on any
non-zero status: it calls save_collection, never relies on `bash -e`. Offline: git and the file system only.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile

REGISTRY = "public/data/registry.json"
MISSING = object()  # a program with no athletics.platform key at all: not the same as null


class Unexpected(Exception):
    """The run's registry change is not one a refresh makes, or a copy cannot be used. Fail closed."""


def dumps(doc) -> bytes:
    """The registry as common.write_json writes it."""
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def parse(side: str, data: bytes) -> dict:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise Unexpected(f"the {side} copy of {REGISTRY} does not parse as JSON ({e})") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("programs"), list):
        raise Unexpected(f"the {side} copy of {REGISTRY} has no `programs` list")
    seen = set()
    for i, p in enumerate(doc["programs"]):
        if not isinstance(p, dict) or not isinstance(p.get("slug"), str):
            raise Unexpected(f"the {side} copy of {REGISTRY} has a program without a slug (programs[{i}])")
        if p["slug"] in seen:
            raise Unexpected(f"the {side} copy of {REGISTRY} lists {p['slug']} twice in `programs`")
        seen.add(p["slug"])
    return doc


def platform_of(program: dict):
    ath = program.get("athletics")
    if not isinstance(ath, dict):
        return MISSING
    return ath.get("platform", MISSING)


def without_platform(program: dict) -> dict:
    p = copy.deepcopy(program)
    if isinstance(p.get("athletics"), dict):
        p["athletics"].pop("platform", None)
    return p


def show(value) -> str:
    return "(none)" if value is MISSING else json.dumps(value, ensure_ascii=False)


def run_changes(base: dict, run: dict) -> dict:
    """{slug: (base platform, run platform)} for every platform the run changed. Raises Unexpected on any
    other change the run made."""
    for key in sorted(set(base) | set(run)):
        if key in ("programs", "updated"):
            continue
        if base.get(key, MISSING) != run.get(key, MISSING):
            raise Unexpected(f"this run changed the registry's top-level `{key}`"
                             + (" (a refresh reads `programs` only and never writes `heldPrograms`)" if key == "heldPrograms" else ""))
    if ("updated" in base) != ("updated" in run):
        raise Unexpected("this run added or removed the registry's top-level `updated`")
    base_slugs = [p["slug"] for p in base["programs"]]
    run_slugs = [p["slug"] for p in run["programs"]]
    if base_slugs != run_slugs:
        added = [s for s in run_slugs if s not in base_slugs]
        removed = [s for s in base_slugs if s not in run_slugs]
        what = "; ".join(x for x in (f"added {', '.join(added)}" if added else "",
                                     f"removed {', '.join(removed)}" if removed else "") if x) or "reordered them"
        raise Unexpected(f"this run changed which programs the registry lists ({what})")
    changes = {}
    for b, r in zip(base["programs"], run["programs"]):
        if without_platform(b) != without_platform(r):
            fields = sorted(k for k in set(b) | set(r) if k != "athletics" and b.get(k, MISSING) != r.get(k, MISSING))
            ba, ra = b.get("athletics"), r.get("athletics")
            if isinstance(ba, dict) and isinstance(ra, dict):
                fields += sorted(f"athletics.{k}" for k in set(ba) | set(ra)
                                 if k != "platform" and ba.get(k, MISSING) != ra.get(k, MISSING))
            elif ba != ra:
                fields.append("athletics")
            raise Unexpected(f"this run changed {b['slug']}'s {', '.join(fields)}; a refresh may change athletics.platform only")
        if platform_of(b) != platform_of(r):
            if not isinstance(r.get("athletics"), dict) or "platform" not in r["athletics"]:
                raise Unexpected(f"this run removed {b['slug']}'s athletics.platform")
            changes[b["slug"]] = (platform_of(b), platform_of(r))
    return changes


def merge(base_bytes: bytes, main_bytes: bytes, run_bytes: bytes) -> tuple[bytes, list[str], list[str]]:
    """(registry bytes to write, warnings, slugs whose run platform was applied). Raises Unexpected."""
    if run_bytes == base_bytes:
        return main_bytes, [], []
    base, main, run = parse("base", base_bytes), parse("main", main_bytes), parse("run", run_bytes)
    changes = run_changes(base, run)
    out = copy.deepcopy(main)
    programs = {p["slug"]: p for p in out["programs"]}
    held = {p.get("slug") for p in (main.get("heldPrograms") or []) if isinstance(p, dict)}
    warnings, applied = [], []
    for slug, (was, now) in changes.items():
        target = programs.get(slug)
        if target is None:
            where = "moved it to heldPrograms" if slug in held else "removed it from programs"
            warnings.append(f"this run detected athletics.platform {show(now)} for {slug}, but main {where} while the run "
                            f"was collecting. Main's registry stands; the detection is dropped.")
            continue
        current = platform_of(target)
        if current == now:
            continue  # main made the same change: nothing to apply, nothing to warn about
        if current != was:
            warnings.append(f"this run set {slug}'s athletics.platform to {show(now)}, but main changed it from {show(was)} to "
                            f"{show(current)} while the run was collecting. Main's value stands.")
            continue
        if not isinstance(target.get("athletics"), dict):
            warnings.append(f"this run set {slug}'s athletics.platform to {show(now)}, but main's entry for {slug} has no "
                            f"athletics block. Main's registry stands; the detection is dropped.")
            continue
        target["athletics"]["platform"] = now
        applied.append(slug)
    if not applied:
        return main_bytes, warnings, applied
    if "updated" in out and main.get("updated") == base.get("updated") and run.get("updated") != base.get("updated"):
        out["updated"] = run["updated"]
    return dumps(out), warnings, applied


def git_show(rev: str, path: str) -> bytes:
    if not rev:  # `git show :path` would read the index, not a commit
        raise Unexpected(f"could not read {path}: no revision given (did git merge-base fail?)")
    r = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True)
    if r.returncode != 0:
        raise Unexpected(f"could not read {path} at {rev}: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def write_bytes(path: str, data: bytes) -> None:
    """Atomically, as common.write_json does: a half-written registry must never be left for the build."""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="the merge base of the run's commit and main")
    ap.add_argument("--main", required=True, help="main as fetched (FETCH_HEAD)")
    ap.add_argument("--run", required=True, help="the run's data commit as it was before any rebase")
    ap.add_argument("--path", default=REGISTRY, help="the registry's path in the tree and in the working tree")
    args = ap.parse_args(argv)
    try:
        data, warnings, applied = merge(git_show(args.base, args.path), git_show(args.main, args.path), git_show(args.run, args.path))
    except Unexpected as e:
        print(f"::error title=registry merge::{e}. Nothing was written; the registry is not this step's to settle.")
        return 1
    for w in warnings:
        print(f"::warning title=registry merge::{w}")
    try:
        write_bytes(args.path, data)
    except OSError as e:
        print(f"::error title=registry merge::could not write {args.path}: {e}")
        return 1
    if applied:
        print(f"registry merge: main's {args.path} with this run's athletics.platform for {', '.join(applied)}")
    else:
        print(f"registry merge: main's {args.path}, unchanged (this run applied no platform of its own)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
