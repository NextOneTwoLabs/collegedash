"""Guard for issue #102: the 2007-2024 RPI archive is credited to its actual author, Chris Thomas.

    python tests/rpi_attribution_test.py            # offline; exit 0 when every check passes
    python tests/rpi_attribution_test.py --verbose  # also list every file the scan read

The archive ("RPI for Division I Women's Soccer", https://sites.google.com/site/rpifordivisioniwomenssoccer/Home)
was credited on the live site, in the data and in the code to someone else by mistake. This suite
fails if that wrong surname comes back anywhere in the repository.

What it scans: every file git would commit - tracked files plus untracked files that are not
ignored - so a new file carrying the wrong name fails before it is ever added. Nothing is exempt,
this file included. The wrong surname is never written literally in this file (it is assembled
from two halves in WRONG below), so the suite can scan its own source without tripping on it; a
check below asserts that its own path really is in the scanned set, so that property is tested
rather than assumed.

Two rules, because the surname is also an ordinary one. Rosters, hometowns and school cities in
the collected JSON legitimately contain it (players, a coach, towns in Nevada and Kentucky), so:
  strict      any file that is not .json, outside tests/fixtures/: the surname must not appear at
              all. Code, copy and docs have no reason to mention it.
  archive     public/data/rpi/ and public/data/registry.json: the surname must not appear at all
              (no roster data lives there).
  context     every file, JSON included: the surname must not appear next to what identifies the
              archive - a first name "Chris", or "archive", "sheet", "report" or "RPI" right after
              it (optionally possessive). That is every form the wrong credit ever took.

Also checks that the correct credit is in place where the site, the data and the collector state it.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF = os.path.relpath(os.path.abspath(__file__), ROOT).replace(os.sep, "/")

WRONG = "hender" + "son"  # never literal in this file; see the docstring
AUTHOR = "Chris Thomas"
SITE = "https://sites.google.com/site/rpifordivisioniwomenssoccer/Home"
PROVIDER = "RPI for Division I Women's Soccer (Chris Thomas)"
PROFILE_SOURCE = "end-of-season (Chris Thomas archive)"
ARCHIVE_YEARS = [y for y in range(2007, 2025) if y != 2020]

ANY = re.compile(WRONG, re.I)
CONTEXT = re.compile(rf"chris\W{{0,3}}{WRONG}|{WRONG}(?:['’]s)?\W{{0,3}}(?:rpi|archive|sheet|report)", re.I)

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
    return cond


def read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), "rb") as f:
        return f.read().decode("utf-8", "replace")


def strict_applies(rel: str) -> bool:
    return not rel.lower().endswith(".json") and not rel.startswith("tests/fixtures/")


def archive_applies(rel: str) -> bool:
    return rel.startswith("public/data/rpi/") or rel == "public/data/registry.json"


def offences(rel: str, text: str) -> list[str]:
    """Every line of `text` that breaks a rule for a file at `rel`, as 'rel:line: rule: excerpt'."""
    out = []
    strict, archive = strict_applies(rel), archive_applies(rel)
    for i, line in enumerate(text.splitlines(), 1):
        if CONTEXT.search(line):
            rule = "context"
        elif (strict or archive) and ANY.search(line):
            rule = "strict" if strict else "archive"
        else:
            continue
        m = (CONTEXT.search(line) or ANY.search(line))
        s = max(0, m.start() - 40)
        out.append(f"{rel}:{i}: {rule}: ...{line[s:m.end() + 40].strip()}...")
    return out


def repo_files() -> list[str]:
    res = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True)
    if res.returncode != 0:
        raise SystemExit(f"git ls-files failed ({res.returncode}): {res.stderr.decode(errors='replace')}")
    return sorted({p for p in res.stdout.decode("utf-8").split("\0") if p and os.path.isfile(os.path.join(ROOT, p))})


# ---------- the matcher itself ----------

def test_matcher() -> None:
    print("matcher: every form the wrong credit took is caught; ordinary uses of the surname in data are not")
    name = WRONG.capitalize()
    wrong_forms = [
        f"(Chris {name}'s archive)",
        f"’ and Chris {name}’s RPI archive",
        f"RPI for Division I Women's Soccer (Chris {name})",
        f'"source": "end-of-season ({name} archive)"',
        f"adding a 2025 {name} sheet",
        f"from Chris {name}'s \"RPI for Division I Women's",
        f"CHRIS {name.upper()}",
        f"{name} RPI report",
    ]
    for s in wrong_forms:
        ok(f"caught in a JSON data file: {s!r}", bool(offences("public/data/programs/x.json", s)))
    roster = [f'"hometown": "{name}, Nev."', f'"name": "Kate {name}"',
              f'"bioUrl": "https://x.example/roster/kate-{WRONG}/1"', f'"city": "{name}ville"',
              f'"headCoach": "Gordon {name}"', f'"highSchool": "{name} HS"']
    for s in roster:
        ok(f"not flagged in roster JSON: {s!r}", not offences("programs/x/sources/athletics.json", s))
        ok(f"flagged by the strict rule in code or copy: {s!r}", bool(offences("build.py", s)))
        ok(f"flagged by the archive rule in public/data/rpi: {s!r}", bool(offences("public/data/rpi/2024.json", s)))
    ok("a bare mention in a fixture page is allowed (rosters)", not offences("tests/fixtures/x/roster.html", f"Kate {name}"))
    ok("the correct credit is not flagged", not offences("public/index.html", f"Chris Thomas’s RPI archive"))


# ---------- the scan ----------

def test_scan() -> None:
    print("scan: the wrong surname is absent from every file git would commit")
    files = repo_files()
    must = [SELF, "public/index.html", "README.md", "build.py", "collect/rpi.py", "public/data/registry.json"]
    must += [f"public/data/rpi/{y}.json" for y in ARCHIVE_YEARS]
    ok("the scan covers the whole repository (over 1000 files)", len(files) > 1000, str(len(files)))
    for m in must:
        ok(f"the scan reads {m}", m in files)
    ok("the scan reads the published program profiles",
       sum(1 for f in files if f.startswith("public/data/programs/")) >= 350)
    bad = []
    for rel in files:
        text = read(rel)
        if VERBOSE:
            print(f"  read {rel}")
        if ANY.search(text):
            bad += offences(rel, text)
    ok(f"no file credits the archive to the wrong person ({len(files)} files scanned)", not bad,
       "\n    " + "\n    ".join(bad[:40]) + (f"\n    ... and {len(bad) - 40} more" if len(bad) > 40 else ""))


# ---------- the correct credit ----------

def test_credit() -> None:
    print("credit: the site, the data and the collector name Chris Thomas and describe the restated values")
    html = read("public/index.html")
    ok("index.html defines the archive link as his site", f"const RPI_ARCHIVE_URL = '{SITE}';" in html)
    ok("the FAQ links his name to his site", "ext(RPI_ARCHIVE_URL, 'Chris Thomas’s RPI archive')" in html)
    ok("the History tab links his name to his site",
       '<a href="${RPI_ARCHIVE_URL}" target="_blank" rel="noopener">Chris Thomas’s RPI archive</a>' in html)
    ok("both places say the values from 2010 are restated as if the No Overtime rule had been in effect",
       html.count("as if the No Overtime rule and the 2024 NCAA RPI formula had been in effect") == 2)
    ok("both places say they are not the ranks that stood at the time",
       html.count("not the ranks that stood at the time") == 2)

    readme = read("README.md")
    ok("README credits him and links his site", f"Chris Thomas, [*RPI for Division I Women's Soccer*]({SITE})" in readme)
    ok("README describes the restatement", "No Overtime rule" in readme)

    reg = json.loads(read("public/data/registry.json"))["sources"]["rpiHistory"]
    ok("registry comment credits him", AUTHOR in reg["_comment"], reg["_comment"])
    ok("registry comment describes the restatement", "No Overtime rule" in reg["_comment"], reg["_comment"])

    rpi_py = read("collect/rpi.py")
    ok("the collector's default provider label names him", f'"{PROVIDER}"' in rpi_py)

    ok("build.py writes his name into each profile season's rpi.source", f'"source": "{PROFILE_SOURCE}"' in read("build.py"))

    years = sorted(int(os.path.basename(p)[:4]) for p in glob.glob(os.path.join(ROOT, "public/data/rpi/[0-9][0-9][0-9][0-9].json")))
    ok("the archive is the 17 seasons 2007-2024 without 2020", years == ARCHIVE_YEARS, str(years))
    for y in years:
        doc = json.loads(read(f"public/data/rpi/{y}.json"))
        ok(f"rpi/{y}.json provider names him", doc.get("provider") == PROVIDER, repr(doc.get("provider")))


def main() -> int:
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args().verbose

    test_matcher()
    test_scan()
    test_credit()

    print(f"\n{TOTAL - len(FAILS)}/{TOTAL} checks passed")
    if FAILS:
        for f in FAILS:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
