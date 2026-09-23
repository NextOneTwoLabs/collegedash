"""Tripwire: no Scorecard API key value in the committed data (issue #258).

    python tests/no_key_in_data_test.py                       # the working tree's tracked files
    python tests/no_key_in_data_test.py --ref origin/some-br  # the tracked files of another ref

Scans every tracked file under public/, programs/ and data/ for an `api_key` URL parameter
(`api_key=`, `api-key=`, `apikey=`, also `%3D`-encoded) whose value is anything but empty, `DEMO_KEY`
(api.data.gov's public demo key) or a prefix of `REDACTED` (a cut can leave `api_key=RED`), and for the
literal SCORECARD_API_KEY value when that is set and at least 8 characters long.

It reports the path and a count only, never the matched text: CI logs are public, and printing a hit
would publish the very value this test exists to find.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRS = ("public", "programs", "data")
PARAM_RE = re.compile(rb"(?i)(?:[?&;]|%3F|%26)api[_-]?key(?:=|%3D)((?:(?!%26|%23)[^&#\s\"'()<>\\])*)")
ALLOWED = {b"", b"DEMO_KEY"}
REDACTED = b"REDACTED"


def bad_values(blob: bytes, env_key: bytes) -> int:
    n = 0
    for m in PARAM_RE.finditer(blob):
        v = m.group(1)
        if v not in ALLOWED and not REDACTED.startswith(v):
            n += 1
    if len(env_key) >= 8:
        n += blob.count(env_key)
    return n


def tracked_files(ref: str | None):
    """(path, bytes) of each tracked file under DIRS, from the working tree or from `ref`."""
    if ref:
        tar = subprocess.run(["git", "-C", ROOT, "archive", "--format=tar", ref, "--", *DIRS],
                             capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(tar), mode="r:") as t:
            for m in t:
                if m.isfile():
                    yield m.name, t.extractfile(m).read()
        return
    names = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--", *DIRS],
                           capture_output=True, check=True).stdout.split(b"\0")
    for n in names:
        if not n:
            continue
        path = n.decode("utf-8")
        full = os.path.join(ROOT, path)
        if os.path.isfile(full):
            with open(full, "rb") as f:
                yield path, f.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", default=None, help="scan this git ref's tracked files instead of the working tree")
    a = ap.parse_args(argv)
    env_key = (os.environ.get("SCORECARD_API_KEY") or "").encode("utf-8")
    scanned, hits = 0, []
    for path, blob in tracked_files(a.ref):
        scanned += 1
        if b"key" not in blob.lower() and not (len(env_key) >= 8 and env_key in blob):
            continue
        n = bad_values(blob, env_key)
        if n:
            hits.append((path, n))
    # the check can fail: a planted value is found, and the allowed forms are not
    probe = bad_values(b"x?api_key=abcdef0123456789&y %26api_key%3Dzz a?API-KEY=q", b"")
    allowed = bad_values(b"x?api_key=REDACTED&y a?api_key=RED b?api_key=DEMO_KEY c?api_key=&d", b"")
    where = a.ref or "working tree"
    checks = [
        ("self-check: planted values are found", probe == 3),
        ("self-check: REDACTED, a cut REDACTED, DEMO_KEY and an empty value are allowed", allowed == 0),
        (f"tracked files under {', '.join(DIRS)} in {where} were scanned", scanned > 0),
        (f"no tracked file in {where} holds an api_key value", not hits),
    ]
    for path, n in hits:
        print(f"  FAIL {path}: {n} api_key value(s) that are not redacted")  # path and count only
    for name, passed in checks:
        if not passed:
            print(f"  FAIL {name}")
    print(f"{scanned} tracked file(s) in {where}; {len(hits)} with an api_key value")
    passed = sum(1 for _, p in checks if p)
    print(f"{passed} of {len(checks)} checks passed")
    return 0 if passed == len(checks) else 1

if __name__ == "__main__":
    sys.exit(main())
