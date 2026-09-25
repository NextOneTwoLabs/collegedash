"""tools/api_keys.py, offline (issue #345): a local SQLite database stands in for D1, so no wrangler, no network.

    python tests/api_keys_tool_test.py            # every check
    python tests/api_keys_tool_test.py --verbose

  issue     the key matches the format and is printed once; the database holds its SHA-256 and never the key;
            no SQL statement the tool runs contains the key; label and quota are validated
  cap       the Free-plan cap (owner decision 10): active quotas may not total more than 20,000/day
  revoke    takes a 12-character id only, never a whole key
  upsert    the quota upsert (the same text as api/access.mjs SQL_COUNT) counts 1..quota and then returns no row,
            leaving the count at the quota; selftest reports OK on SQLite
  schema    api/schema.sql refuses a quota of 0 and a status other than active/revoked
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import api_keys  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


class FakeD1:
    """Runs the tool's SQL on SQLite and records every statement."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(open(os.path.join(ROOT, "api", "schema.sql"), encoding="utf-8").read())
        self.statements: list[str] = []

    def __call__(self, sql: str) -> list[dict]:
        self.statements.append(sql)
        cur = self.db.execute(sql)
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []
        self.db.commit()
        return rows


def ns(**kw):
    return argparse.Namespace(**kw)


def test_issue() -> None:
    print("issue")
    d1, lines = FakeD1(), []
    code = api_keys.cmd_issue(ns(label="Example Co", quota=5000, paid_plan=False), run=d1, out=lines.append)
    keys = [x for x in lines if x.startswith("cdk_")]
    ok("exits 0", code == 0, lines)
    ok("prints exactly one key, in the format", len(keys) == 1 and api_keys.KEY_RE.match(keys[0]), keys)
    key = keys[0] if keys else ""
    rows = d1("SELECT id, hash, label, status, quota FROM keys")
    ok("stores one active row with the key's SHA-256 and id", len(rows) == 1 and rows[0]["hash"] == hashlib.sha256(key.encode()).hexdigest()
       and rows[0]["id"] == key[4:16] and rows[0]["status"] == "active" and rows[0]["quota"] == 5000, rows)
    ok("the key is in no SQL statement", key and not any(key in s or key[17:] in s for s in d1.statements))
    ok("the key is in no stored value", key and not any(key in str(v) for r in rows for v in r.values()))
    ok("two keys differ", api_keys.new_key()[1] != api_keys.new_key()[1])
    bad = []
    ok("a label with a quote-escape attempt is refused",
       api_keys.cmd_issue(ns(label="x'); DROP TABLE keys; --", quota=10, paid_plan=False), run=d1, out=bad.append) == 2, bad)
    ok("quota 0 is refused", api_keys.cmd_issue(ns(label="Zero", quota=0, paid_plan=False), run=d1, out=bad.append) == 2)


def test_cap() -> None:
    print("cap: owner decision 10")
    d1, lines = FakeD1(), []
    for label in ("A", "B", "C", "D"):
        api_keys.cmd_issue(ns(label=label, quota=5000, paid_plan=False), run=d1, out=lines.append)
    before = len(d1("SELECT id FROM keys"))
    code = api_keys.cmd_issue(ns(label="E", quota=1, paid_plan=False), run=d1, out=lines.append)
    ok("a fifth 5,000 key would pass 20,000/day and is refused", code == 2 and before == 4 and len(d1("SELECT id FROM keys")) == 4, lines[-1:])
    kid = d1("SELECT id FROM keys LIMIT 1")[0]["id"]
    api_keys.cmd_revoke(ns(id=kid), run=d1, out=lines.append)
    ok("after a revoke there is room again",
       api_keys.cmd_issue(ns(label="E", quota=5000, paid_plan=False), run=d1, out=lines.append) == 0)
    ok("--paid-plan lifts the cap",
       api_keys.cmd_issue(ns(label="F", quota=5000, paid_plan=True), run=d1, out=lines.append) == 0)


def test_revoke() -> None:
    print("revoke")
    d1, lines = FakeD1(), []
    api_keys.cmd_issue(ns(label="Example Co", quota=10, paid_plan=False), run=d1, out=lines.append)
    key = [x for x in lines if x.startswith("cdk_")][0]
    ok("a whole key is refused as an id", api_keys.cmd_revoke(ns(id=key), run=d1, out=lines.append) == 2)
    ok("revoking by id works", api_keys.cmd_revoke(ns(id=key[4:16]), run=d1, out=lines.append) == 0
       and d1("SELECT status FROM keys")[0]["status"] == "revoked")
    ok("an unknown id says so", api_keys.cmd_revoke(ns(id="zzzzzzzzzzzz"), run=d1, out=lines.append) == 1)


def test_upsert() -> None:
    print("upsert: the quota statement")
    src = open(os.path.join(ROOT, "api", "access.mjs"), encoding="utf-8").read()
    js = "".join(re.findall(r"'([^']*)'", src.split("export const SQL_COUNT =", 1)[1].split(";", 1)[0]))
    ok("tools/api_keys.py and api/access.mjs run the same statement", js == api_keys.SQL_COUNT, (js, api_keys.SQL_COUNT))
    d1 = FakeD1()
    d1("INSERT INTO keys VALUES ('abcdefghijkl', 'h', 'x', 't', 'active', 3)")
    got = []
    for _ in range(5):
        cur = d1.db.execute(api_keys.SQL_COUNT.replace("?1", "'abcdefghijkl'").replace("?2", "'2026-09-25'").replace("?3", "3"))
        row = cur.fetchone()
        d1.db.commit()
        got.append(row[0] if row else None)
    ok("counts 1..quota, then no row", got == [1, 2, 3, None, None], got)
    ok("the stored count stays at the quota", d1("SELECT count FROM usage")[0]["count"] == 3)
    lines = []
    ok("selftest reports OK", api_keys.cmd_selftest(ns(), run=FakeD1(), out=lines.append) == 0, lines)


def test_schema() -> None:
    print("schema")
    d1 = FakeD1()
    for sql, what in (("INSERT INTO keys VALUES ('a', 'h1', 'x', 't', 'active', 0)", "quota 0"),
                      ("INSERT INTO keys VALUES ('b', 'h2', 'x', 't', 'paused', 5)", "status paused")):
        try:
            d1(sql)
            ok(f"{what} is refused", False)
        except sqlite3.IntegrityError:
            ok(f"{what} is refused", True)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for t in (test_issue, test_cap, test_revoke, test_upsert, test_schema):
        t()
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
