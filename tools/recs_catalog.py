"""Freeze the recommender's test catalog: tests/fixtures/recs/catalog.json (issue #400, PR 2).

    python tools/recs_catalog.py              # rebuild the fixture from the committed public/data
    python tools/recs_catalog.py --check      # exit 1 if the committed fixture is not what the committed data gives
    python tools/recs_catalog.py --out PATH   # write somewhere else (a scratch copy)

The ranker's scenarios and property gates (tests/recs_*.test.mjs) run against this frozen copy, not against
public/data, so the daily refresh never moves an expectation. It is regenerated only by a reviewed PR: run this,
re-check the scenario expectations, commit both.

Offline: it reads public/data/programs/index.json and each program's profile, and nothing else. The fit entries are
made by build.fit_entry and the constants by build.fit_constants - PR 1's builder, the functions the build itself
calls - so the frozen fit facts are exactly what /api/v1/fit serves for the same data.

What it keeps, and nothing else:
  programs[]   the list-row fields the ranker and its tie order read: slug, name, shortName (the displayed name is
               shortName || name), division, conference (the scenarios' filters), region, state, undergradEnrollment.
  fit{}        build.FIT_KEYS per slug, as in public/data/fit/index.json.
  plus         updated, fitTaxonomy, constants and sources from the same build functions.
Programs and schools only: no coach, staff, roster, commitment or contact field is read into it, and
tests/recs_catalog_test.py fails if an email address or a person-shaped key ever appears.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import build  # noqa: E402
from collect import common  # noqa: E402

OUT = os.path.join(ROOT, "tests", "fixtures", "recs", "catalog.json")
ROW_KEYS = ("slug", "name", "shortName", "division", "conference", "region", "state", "undergradEnrollment")


def catalog(index_doc: dict, load_profile) -> dict:
    """The frozen catalog from an index document and a profile loader (slug -> profile dict or None)."""
    rows = index_doc["programs"]
    fit = {r["slug"]: build.fit_entry(load_profile(r["slug"]) or {}) for r in rows}
    doc = build.fit_index(index_doc["updated"], fit)
    return {
        "about": "Frozen recommender test catalog (issue #400). Built by tools/recs_catalog.py from the committed "
                 "public/data; regenerate only in a reviewed PR. Programs and schools only.",
        "updated": doc["updated"],
        "fitTaxonomy": doc["fitTaxonomy"],
        "constants": doc["constants"],
        "sources": doc["sources"],
        "programs": [{k: r.get(k) for k in ROW_KEYS} for r in rows],
        "fit": doc["fit"],
    }


def dumps(doc: dict) -> str:
    """One program per line, so a regenerated fixture reviews as a readable diff. Sorted nowhere: the index's
    order is kept, and the ranker's tests shuffle it anyway."""
    def one(v):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))

    head = {k: v for k, v in doc.items() if k not in ("programs", "fit")}
    lines = ["{"]
    for k, v in head.items():
        lines.append(f"  {one(k)}: {one(v)},")
    lines.append('  "programs": [')
    progs = doc["programs"]
    lines += [f"    {one(p)}{',' if i < len(progs) - 1 else ''}" for i, p in enumerate(progs)]
    lines.append("  ],")
    lines.append('  "fit": {')
    items = list(doc["fit"].items())
    lines += [f"    {one(s)}: {one(e)}{',' if i < len(items) - 1 else ''}" for i, (s, e) in enumerate(items)]
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def from_committed() -> str:
    index_doc = common.read_json(os.path.join(common.PROGRAMS_OUT_DIR, "index.json"))
    return dumps(catalog(index_doc, lambda s: common.read_json(os.path.join(common.PROGRAMS_OUT_DIR, f"{s}.json"))))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--check", action="store_true", help="compare with the committed fixture, write nothing")
    a = ap.parse_args(argv)
    text = from_committed()
    if a.check:
        try:
            with open(a.out, encoding="utf-8") as f:
                same = f.read() == text
        except FileNotFoundError:
            same = False
        print("recs catalog: " + ("matches the committed data" if same else "DIFFERS from the committed data"))
        return 0 if same else 1
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    doc = json.loads(text)
    print(f"wrote {a.out}: {len(doc['programs'])} programs, catalog {doc['updated']}, {doc['fitTaxonomy']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
