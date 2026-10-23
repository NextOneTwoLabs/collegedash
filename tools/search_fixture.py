"""Freeze the Home search's test data: tests/fixtures/search/programs.json and camps.json (issue #507, v1 PR 1).

    python tools/search_fixture.py              # rebuild both files from the committed public/data
    python tools/search_fixture.py --check      # exit 1 if the committed files are not what the committed data gives
    python tools/search_fixture.py --out DIR    # write somewhere else (a scratch copy)

The Home search's engine tests (tests/home_search_engine.test.mjs) and its judged set
(tests/fixtures/search/judged-v1.json) run against this frozen copy, not against public/data, so the daily refresh
never moves an expectation. It is regenerated only by a reviewed PR: run this, re-check the judged set, commit all
three. `--check` is run by hand when regenerating, never by CI: CI also runs after every daily refresh.

Offline: it reads public/data/programs/index.json and public/data/camps/index.json, and nothing else.

What it keeps, and nothing else (`cut`, a pure function, so cutting the fixture's own docs gives them back):
  programs.json  { updated, programs } - each row only the fields the page's matcher and rows read:
                 slug, name, shortName, nickname, searchNames, city, state, region, division, conference.
  camps.json     { updated, camps } - each row only slug, name, startDate, endDate, precision, campType and the
                 program block (name, shortName, division, city, state, region).
The test clock is the date part of camps.json's `updated`. Programs and camps only: no coach, staff, roster,
commitment or contact field, and tests/search_fixture_test.py fails if a person-shaped key or an email appears.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collect import common  # noqa: E402

OUT_DIR = os.path.join(ROOT, "tests", "fixtures", "search")
PROGRAM_KEYS = ("slug", "name", "shortName", "nickname", "searchNames", "city", "state", "region", "division", "conference")
CAMP_KEYS = ("slug", "name", "startDate", "endDate", "precision", "campType", "program")
CAMP_PROGRAM_KEYS = ("name", "shortName", "division", "city", "state", "region")


def _camp(row: dict) -> dict:
    out = {k: row.get(k) for k in CAMP_KEYS}
    block = row.get("program")
    out["program"] = {k: block.get(k) for k in CAMP_PROGRAM_KEYS} if isinstance(block, dict) else None
    return out


def cut(programs_doc: dict, camps_doc: dict) -> tuple[dict, dict]:
    """The two fixture docs from the published programs and camps docs. Order is kept; nothing is sorted or dropped."""
    programs = {"updated": programs_doc.get("updated"),
                "programs": [{k: r.get(k) for k in PROGRAM_KEYS} for r in programs_doc["programs"]]}
    camps = {"updated": camps_doc.get("updated"), "camps": [_camp(r) for r in camps_doc["camps"]]}
    return programs, camps


def clock(camps_doc: dict) -> str:
    """The test clock: the calendar date the camps index was built on (YYYY-MM-DD)."""
    return str(camps_doc["updated"])[:10]


def dumps(doc: dict, rows_key: str) -> str:
    """One row per line, so a regenerated fixture reviews as a readable diff."""
    def one(v):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))

    rows = doc[rows_key]
    lines = ["{"]
    lines += [f"  {one(k)}: {one(v)}," for k, v in doc.items() if k != rows_key]
    lines.append(f"  {one(rows_key)}: [")
    lines += [f"    {one(r)}{',' if i < len(rows) - 1 else ''}" for i, r in enumerate(rows)]
    lines += ["  ]", "}"]
    return "\n".join(lines) + "\n"


def texts(programs_doc: dict, camps_doc: dict) -> dict[str, str]:
    programs, camps = cut(programs_doc, camps_doc)
    return {"programs.json": dumps(programs, "programs"), "camps.json": dumps(camps, "camps")}


def from_committed() -> dict[str, str]:
    return texts(common.read_json(os.path.join(common.PROGRAMS_OUT_DIR, "index.json")),
                 common.read_json(os.path.join(common.CAMPS_OUT_DIR, "index.json")))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=OUT_DIR, help="directory to write programs.json and camps.json into")
    ap.add_argument("--check", action="store_true", help="compare with the committed fixture, write nothing")
    a = ap.parse_args(argv)
    want = from_committed()
    if a.check:
        differ = []
        for name, text in want.items():
            try:
                with open(os.path.join(a.out, name), encoding="utf-8") as f:
                    if f.read() != text:
                        differ.append(name)
            except FileNotFoundError:
                differ.append(name)
        print("search fixture: " + (f"DIFFERS from the committed data: {', '.join(differ)}" if differ else "matches the committed data"))
        return 1 if differ else 0
    os.makedirs(a.out, exist_ok=True)
    for name, text in want.items():
        with open(os.path.join(a.out, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    camps = json.loads(want["camps.json"])
    print(f"wrote {a.out}: {len(json.loads(want['programs.json'])['programs'])} programs, {len(camps['camps'])} camps, clock {clock(camps)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
