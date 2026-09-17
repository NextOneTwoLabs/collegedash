"""Derive data/schools.json, the high-school candidate list, from the federal NCES directories.

    python tools/schools_nces.py             # download once into .cache/nces/, then write data/schools.json
    python tools/schools_nces.py --dry-run   # print the counts, write nothing

Two public-domain files from the National Center for Education Statistics (issue #229):

  * the Common Core of Data school directory (public schools, one row per school; the 2023-24 file
    carries 102,274 rows and 65 columns: NCES id, name, addresses, phone, website, status, type,
    charter flags and the grades offered);
  * the Private School Survey public-use files (private schools; the 2023-24 file carries 22,510
    rows and 359 columns: NCES id, name, address, phone, grades, enrolment, religious orientation,
    survey weights). Names are as the survey publishes them, in upper case. The public-use file
    only carries the schools that answered that survey, so the 2021-22 file is read as well and a
    school absent from 2023-24 is kept from 2021-22, with its own year, when it has one there.

Only what a match needs is kept, and nothing that reaches a person: id, name, city, state,
public/private and the source year. No address, phone or website. Rows are limited to open schools
that offer at least one of grades 9-12, so the file stays a few megabytes and the ambiguity within
a state is only between schools a player could have attended.

The download goes to .cache/nces/ (git-ignored) and is skipped when the file is already there.
The written file records the source URLs, the school year and the download date in its header.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import schools  # noqa: E402
from collect import common  # noqa: E402

CACHE_DIR = os.path.join(common.ROOT, ".cache", "nces")
USER_AGENT = "collegedash-research/1.0 (one-off download of public-domain NCES directory files)"

SOURCES = {
    "ccd": {
        "name": "NCES Common Core of Data, Public Elementary/Secondary School Universe Survey Directory",
        "year": "2023-24",
        "url": "https://nces.ed.gov/ccd/Data/zip/ccd_sch_029_2324_w_1a_073124.zip",
        "landing": "https://nces.ed.gov/ccd/files.asp",
        "type": "public",
        "idPrefix": "ccd",
    },
    "pss": {
        "name": "NCES Private School Universe Survey, public-use data file",
        "year": "2023-24",
        "url": "https://nces.ed.gov/surveys/pss/zip/pss2324_pu_csv.zip",
        "landing": "https://nces.ed.gov/surveys/pss/pssdata.asp",
        "type": "private",
        "idPrefix": "pss",
    },
    "pss-previous": {
        "name": "NCES Private School Universe Survey, public-use data file (previous survey, for schools "
                "that did not answer the 2023-24 one)",
        "year": "2021-22",
        "url": "https://nces.ed.gov/surveys/pss/zip/pss2122_pu_csv.zip",
        "landing": "https://nces.ed.gov/surveys/pss/pssdata.asp",
        "type": "private",
        "idPrefix": "pss",
    },
}
# CCD SY_STATUS_TEXT values that mean the school is not operating in the school year.
CCD_NOT_OPERATING = {"Closed", "Inactive", "Future"}
# PSS LOGR/HIGR grade codes: 1 ungraded, 2 prekindergarten, 3 kindergarten, 4 transitional K,
# 5 transitional 1st, 6 = 1st grade ... 17 = 12th grade. Grade 9 is 14.
PSS_GRADE_9 = 14


def download(key: str) -> str:
    src = SOURCES[key]
    path = os.path.join(CACHE_DIR, os.path.basename(src["url"]))
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    import requests  # noqa: WPS433 - only needed for the one-off download

    os.makedirs(CACHE_DIR, exist_ok=True)
    print(f"downloading {src['url']} -> {path}")
    with requests.get(src["url"], headers={"User-Agent": USER_AGENT}, stream=True, timeout=120) as r:
        r.raise_for_status()
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
        os.replace(tmp, path)
    return path


def csv_rows(zip_path: str):
    zf = zipfile.ZipFile(zip_path)
    name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
    with zf.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"))


def ccd_rows(zip_path: str, stats: dict, year: str) -> list[list]:
    out = []
    for row in csv_rows(zip_path):
        stats["ccd rows"] += 1
        if row.get("SY_STATUS_TEXT") in CCD_NOT_OPERATING:
            stats["ccd not operating"] += 1
            continue
        if not any(row.get(f"G_{g}_OFFERED") == "Yes" for g in (9, 10, 11, 12)):
            stats["ccd no grade 9-12"] += 1
            continue
        state = (row.get("ST") or "").strip().upper()
        if state not in common.US_STATES:
            stats["ccd outside the 50 states + DC"] += 1  # PR, GU, VI, AS, MP, BI, DD
            continue
        name = common.clean(row.get("SCH_NAME"))
        city = common.clean(row.get("LCITY") or row.get("MCITY"))
        out.append([f"ccd:{row['NCESSCH'].strip()}", name, city.title() if city.isupper() else city, state, "public", year])
    return out


def pss_rows(zip_path: str, stats: dict, year: str) -> list[list]:
    out = []
    high_col = None
    for row in csv_rows(zip_path):
        stats[f"pss {year} rows"] += 1
        if high_col is None:  # HIGR2024 in the 2023-24 file, HIGR2022 in the 2021-22 one
            high_col = next(c for c in row if c.upper().startswith("HIGR"))
        try:
            high = int(row.get(high_col) or 0)
        except ValueError:
            high = 0
        if high < PSS_GRADE_9:
            stats[f"pss {year} no grade 9-12"] += 1
            continue
        state = (row.get("PSTABB") or "").strip().upper()
        if state not in common.US_STATES:
            stats[f"pss {year} outside the 50 states + DC"] += 1
            continue
        name = common.clean(row.get("PINST"))
        city = common.clean(row.get("PCITY"))
        out.append([f"pss:{row['PPIN'].strip()}", name, city.title() if city.isupper() else city, state, "private", year])
    return out


def write_table(path: str, doc: dict) -> None:
    """Standard JSON, but one school per line: 40,000 rows stay readable in a diff and greppable."""
    head = {k: v for k, v in doc.items() if k != "rows"}
    text = json.dumps(head, indent=2, ensure_ascii=False)
    assert text.endswith("\n}")
    lines = [text[:-2].rstrip() + ",", '  "rows": [']
    rows = doc["rows"]
    for i, row in enumerate(rows):
        lines.append("    " + json.dumps(row, ensure_ascii=False) + ("," if i + 1 < len(rows) else ""))
    lines += ["  ]", "}", ""]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the counts and write nothing")
    args = ap.parse_args()

    stats: dict[str, int] = {k: 0 for k in ("ccd rows", "ccd not operating", "ccd no grade 9-12",
                                            "ccd outside the 50 states + DC")}
    for key in ("pss", "pss-previous"):
        for what in ("rows", "no grade 9-12", "outside the 50 states + DC"):
            stats[f"pss {SOURCES[key]['year']} {what}"] = 0
    rows = ccd_rows(download("ccd"), stats, SOURCES["ccd"]["year"])
    rows += pss_rows(download("pss"), stats, SOURCES["pss"]["year"])
    # A school is carried over from the previous survey only when the newer survey has neither its
    # id nor a private school of the same cleaned name in the same city and state: survey ids are
    # not always stable between rounds, and a carried-over duplicate would make its own name
    # ambiguous. Only the newer PSS rows count here, not the CCD: a private school can share a
    # cleaned name and city with a public one (ASHEVILLE SCHOOL beside Asheville High) and be a
    # different school; kept, the two make the name ambiguous, which is safe.
    seen_ids = {r[0] for r in rows}
    seen_places = {(r[3], schools.school_key(r[1]), r[2].casefold()) for r in rows if r[4] == "private"}
    previous = pss_rows(download("pss-previous"), stats, SOURCES["pss-previous"]["year"])
    prev_year, cur_year = SOURCES["pss-previous"]["year"], SOURCES["pss"]["year"]
    stats[f"pss {prev_year} already in {cur_year} by id"] = sum(r[0] in seen_ids for r in previous)
    stats[f"pss {prev_year} same name and city as a {cur_year} school"] = sum(
        r[0] not in seen_ids and (r[3], schools.school_key(r[1]), r[2].casefold()) in seen_places for r in previous)
    rows += [r for r in previous
             if r[0] not in seen_ids and (r[3], schools.school_key(r[1]), r[2].casefold()) not in seen_places]
    rows.sort(key=lambda r: (r[3], schools.school_key(r[1]), r[0]))
    for k, v in stats.items():
        print(f"{v:8}  {k}")
    print(f"{len(rows):8}  schools kept ({sum(r[4] == 'public' for r in rows)} public, "
          f"{sum(r[4] == 'private' for r in rows)} private)")
    keys: dict[tuple[str, str], int] = {}
    for r in rows:
        k = (r[3], schools.school_key(r[1]))
        keys[k] = keys.get(k, 0) + 1
    print(f"{sum(1 for v in keys.values() if v > 1):8}  (state, cleaned name) keys shared by more than one school")

    doc = {
        "note": ("Derived by tools/schools_nces.py from the public-domain NCES files below: open "
                 "schools in the 50 states and DC offering at least one of grades 9-12. Only id, name, "
                 "city, state, public/private and the source year are kept. Regenerate with the tool; "
                 "do not edit."),
        "downloaded": dt.date.today().isoformat(),
        "sources": {k: {kk: v[kk] for kk in ("name", "year", "url", "landing", "type", "idPrefix")}
                    for k, v in SOURCES.items()},
        "columns": list(schools.COLUMNS),
        "rows": rows,
    }
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    write_table(schools.TABLE_PATH, doc)
    schools.load_table(reload=True)  # a file this tool writes must load
    print(f"wrote {schools.TABLE_PATH} ({os.path.getsize(schools.TABLE_PATH) / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
