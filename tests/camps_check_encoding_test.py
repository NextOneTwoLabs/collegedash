"""The camps fixtures suite survives a console that cannot encode its output (issue #326, item 4).

    python tests/camps_check_encoding_test.py

Offline. Runs `tools/camps_check.py --fixtures` in a child process whose stdout/stderr are cp1252, as
on a Windows console without PYTHONIOENCODING=utf-8. A stored camp name carries U+FFFD, which cp1252
cannot encode: before the fix the child died with UnicodeEncodeError on that line. It must now
finish and report its checks, with the character escaped.
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8",)}
    env.update(PYTHONIOENCODING="cp1252", COLLEGEDASH_OFFLINE="1")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "camps_check.py"), "--fixtures"],
                       cwd=ROOT, env=env, capture_output=True)
    out = r.stdout.decode("cp1252", "replace")
    err = r.stderr.decode("cp1252", "replace")
    checks = [
        ("no UnicodeEncodeError on a cp1252 console", "UnicodeEncodeError" not in err, err[-400:]),
        ("fixtures suite exits 0 on a cp1252 console", r.returncode == 0, f"exit {r.returncode}: {err[-400:]}"),
        ("fixtures suite reports its checks", "checks passed" in out, out[-200:]),
    ]
    fails = 0
    for name, ok, detail in checks:
        if not ok:
            fails += 1
            print(f"  FAIL {name} - {detail}")
    print(f"{len(checks) - fails} of {len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
