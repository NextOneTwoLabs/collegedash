"""Shape of .github/workflows/freshness.yml, the scheduled age check (issue #69).

    python tests/freshness_workflow_test.py            # every case
    python tests/freshness_workflow_test.py --verbose  # print every check, not only the failures

The workflow is read as text (no YAML library: the data refresh does not install one). Nothing is run.

  triggers    only `schedule` and `workflow_dispatch`: never a push or pull_request, since the clock is read
              only in the scheduled job (a PR check that reads the clock fails on correct data the day it ages)
  cron        freshness runs at 47 23 * * *, and refresh.yml still runs at 0 11 * * *: the thresholds in
              tools/freshness_check.py (12h warn, 36h fail) were derived from that pair, so moving either
              line must fail here until the thresholds are looked at again
  permissions `contents: read` and nothing more
  checkout    main, explicitly
  command     runs tools/freshness_check.py
  no-network  no curl, wget, pip, npm or git fetch/push step: it reads the committed files only
"""

from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRESH = os.path.join(ROOT, ".github", "workflows", "freshness.yml")
REFRESH = os.path.join(ROOT, ".github", "workflows", "refresh.yml")

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {detail}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def code_lines(text: str) -> list[str]:
    """The file's lines with comments dropped."""
    return [re.sub(r"\s+#.*$", "", l).rstrip() for l in text.splitlines() if not l.lstrip().startswith("#")]


def top_block(lines: list[str], key: str) -> list[str]:
    """The indented lines under a top-level `key:`."""
    out, inside = [], False
    for l in lines:
        if re.match(r"^\S", l):
            inside = l.startswith(key + ":")
            continue
        if inside and l.strip():
            out.append(l)
    return out


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true", help="print passing checks too")
    VERBOSE = ap.parse_args(argv).verbose

    if not ok("freshness.yml exists", os.path.exists(FRESH), FRESH):
        print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed; FAILED: {', '.join(FAILS)}")
        return 1
    with open(FRESH, encoding="utf-8") as f:
        text = f.read()
    lines = code_lines(text)

    on = top_block(lines, "on")
    triggers = [m.group(1) for l in on if (m := re.match(r"^  (\w[\w-]*):", l))]
    ok("only schedule and workflow_dispatch trigger it", sorted(triggers) == ["schedule", "workflow_dispatch"], str(triggers))
    crons = [m.group(1) for l in on if (m := re.search(r'cron:\s*"([^"]+)"', l))]
    ok("the cron is exactly 47 23 * * *", crons == ["47 23 * * *"], str(crons))

    with open(REFRESH, encoding="utf-8") as f:
        rcrons = re.findall(r'cron:\s*"([^"]+)"', f.read())
    ok("and refresh.yml's cron is still 0 11 * * *, the pair the 12h/36h thresholds were derived from",
       rcrons == ["0 11 * * *"], str(rcrons))

    perms = [l.strip() for l in top_block(lines, "permissions")]
    ok("top-level permissions are contents: read and nothing else", perms == ["contents: read"], str(perms))
    ok("no job overrides permissions", not any(re.match(r"^\s{4,}permissions:", l) for l in lines))

    ok("it checks out main explicitly",
       bool(re.search(r"uses:\s*actions/checkout@\S+\s*\n\s+with:\s*\n\s+ref:\s*main\b", "\n".join(lines))),
       "expected actions/checkout with ref: main")
    ok("it runs tools/freshness_check.py", "python tools/freshness_check.py" in text)

    run_text = "\n".join(l for l in lines if re.match(r"^\s+(-\s+)?run:|^\s{8,}\S", l))
    banned = [w for w in ("curl", "wget", "pip ", "npm ", "git fetch", "git push", "git pull", "http://", "https://")
              if w in run_text]
    ok("no step fetches or pushes anything", not banned, str(banned))
    ok("no step uses a token or secret", "secrets." not in text and "GITHUB_TOKEN" not in text)

    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed" + (f"; FAILED: {', '.join(FAILS)}" if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
