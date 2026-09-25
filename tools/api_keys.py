"""Owner tool for /api/v1 keys (issue #345). Keys and usage live in the D1 database collegedash-api.

    python tools/api_keys.py issue --label "Example Co" [--quota 5000]   # prints the new key ONCE
    python tools/api_keys.py revoke <key id>
    python tools/api_keys.py list                                        # ids, labels, status, quota
    python tools/api_keys.py usage [--days 7]                            # served requests per key and day
    python tools/api_keys.py selftest                                    # the quota upsert on the real database

Every command runs `npx wrangler d1 execute collegedash-api --remote --json --command <sql>` on the owner's
machine, logged in to Cloudflare. Nothing here fetches data or touches the site.

Keys: cdk_<12-character id>_<43-character secret>, 32 random bytes from `secrets`. Only the SHA-256 of the whole
key is stored; the key itself is printed once, to this terminal, and never written to a file, a command line or
the database. Do not paste it into an issue, a PR, a chat or a log. To rotate: issue a new key, let the customer
switch, revoke the old one. If a key leaks: revoke it first (effective on the next request), then clean up.

Owner decision 10: while the account is on the Workers Free plan, the daily quotas of all active keys together may
not exceed 20,000 (every Worker request, visitor and customer, comes out of one 100,000/day account limit).
`issue` refuses to go past it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

DB = "collegedash-api"
DEFAULT_QUOTA = 5000          # owner decision 2
FREE_PLAN_TOTAL_QUOTA = 20000  # owner decision 10
KEY_RE = re.compile(r"^cdk_([a-z0-9]{12})_[A-Za-z0-9_-]{43}$")  # the same as api/access.mjs KEY_RE
ID_RE = re.compile(r"^[a-z0-9]{12}$")
LABEL_RE = re.compile(r"^[A-Za-z0-9 .,&'()@_-]{1,60}$")
ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
# The quota upsert, the same statement as api/access.mjs SQL_COUNT; tests/api_keys_tool_test.py checks they match.
SQL_COUNT = ("INSERT INTO usage (key_id, day, count) VALUES (?1, ?2, 1) "
             "ON CONFLICT (key_id, day) DO UPDATE SET count = count + 1 WHERE usage.count < ?3 RETURNING count")


def new_key() -> tuple[str, str]:
    """(key id, full key)."""
    kid = "".join(secrets.choice(ALPHABET) for _ in range(12))
    secret = secrets.token_urlsafe(32)  # 32 bytes -> 43 base64url characters, no padding
    key = f"cdk_{kid}_{secret}"
    assert KEY_RE.match(key), "generated key does not match the format"
    return kid, key


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def q(value: str) -> str:
    """A SQL string literal. Only ever given validated ids, labels, hashes and dates, never a key."""
    return "'" + str(value).replace("'", "''") + "'"


def wrangler(sql: str) -> list[dict]:
    """Run one statement on the remote database and return its rows."""
    npx = shutil.which("npx") or "npx"
    r = subprocess.run([npx, "wrangler", "d1", "execute", DB, "--remote", "--json", "--command", sql],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"wrangler failed ({r.returncode}): {r.stderr.strip()[-400:]}")
    out = json.loads(r.stdout)
    return (out[0] if isinstance(out, list) and out else out).get("results", [])


def cmd_issue(args, run=wrangler, out=print) -> int:
    if not LABEL_RE.match(args.label):
        out("label: letters, digits, spaces and .,&'()@_- only, 1-60 characters")
        return 2
    if args.quota < 1:
        out("quota must be at least 1 (a customer with no allowance is revoked, not given 0)")
        return 2
    rows = run("SELECT COALESCE(SUM(quota), 0) AS total FROM keys WHERE status = 'active'")
    total = int(rows[0]["total"]) if rows else 0
    if total + args.quota > FREE_PLAN_TOTAL_QUOTA and not args.paid_plan:
        out(f"refused: active keys already total {total}/day; adding {args.quota} would pass the Free-plan cap of "
            f"{FREE_PLAN_TOTAL_QUOTA} (owner decision 10). Lower --quota, revoke a key, or pass --paid-plan once the "
            f"account is on Workers Paid.")
        return 2
    kid, key = new_key()
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run(f"INSERT INTO keys (id, hash, label, created, status, quota) VALUES "
        f"({q(kid)}, {q(key_hash(key))}, {q(args.label)}, {q(created)}, 'active', {int(args.quota)})")
    out(f"issued key id {kid} for {args.label!r}, {args.quota} requests/day")
    out("The key, shown once. Copy it to the customer now; it cannot be shown again:")
    out(key)
    return 0


def cmd_revoke(args, run=wrangler, out=print) -> int:
    if not ID_RE.match(args.id):
        out("a key id is 12 lower-case letters and digits (the part after cdk_), never the whole key")
        return 2
    run(f"UPDATE keys SET status = 'revoked' WHERE id = {q(args.id)}")
    rows = run(f"SELECT id, status FROM keys WHERE id = {q(args.id)}")
    if not rows:
        out(f"no key with id {args.id}")
        return 1
    out(f"key {args.id}: {rows[0]['status']}")
    return 0


def cmd_list(args, run=wrangler, out=print) -> int:
    rows = run("SELECT id, label, created, status, quota FROM keys ORDER BY created")
    for r in rows:
        out(f"{r['id']}  {r['status']:<8} {int(r['quota']):>6}/day  {r['created']}  {r['label']}")
    active = sum(int(r["quota"]) for r in rows if r["status"] == "active")
    out(f"{len(rows)} keys; active quotas total {active}/day (Free-plan cap {FREE_PLAN_TOTAL_QUOTA})")
    return 0


def cmd_usage(args, run=wrangler, out=print) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, args.days) - 1)).strftime("%Y-%m-%d")
    rows = run(f"SELECT key_id, day, count FROM usage WHERE day >= {q(since)} ORDER BY day, key_id")
    for r in rows:
        out(f"{r['day']}  {r['key_id']}  {int(r['count'])}")
    out(f"{sum(int(r['count']) for r in rows)} served keyed requests since {since}")
    return 0


def cmd_selftest(args, run=wrangler, out=print) -> int:
    """The quota upsert on the real database (plan section 4.2: D1's support for RETURNING on this upsert is to be
    proven, not assumed). Uses a revoked throwaway key row with quota 2, then removes it."""
    kid = "selftest" + "".join(secrets.choice(ALPHABET) for _ in range(4))
    day = "1970-01-01"
    run(f"INSERT INTO keys (id, hash, label, created, status, quota) VALUES "
        f"({q(kid)}, {q(key_hash(kid))}, 'selftest', '1970-01-01T00:00:00Z', 'revoked', 2)")
    got = []
    try:
        for _ in range(3):
            sql = (SQL_COUNT.replace("?1", q(kid)).replace("?2", q(day)).replace("?3", "2"))
            rows = run(sql)
            got.append(int(rows[0]["count"]) if rows else None)
    finally:
        run(f"DELETE FROM usage WHERE key_id = {q(kid)}")
        run(f"DELETE FROM keys WHERE id = {q(kid)}")
    ok = got == [1, 2, None]
    out(f"quota upsert on D1: {got} (expected [1, 2, None]) -> {'OK' if ok else 'FAILED: use the fallback in plan section 4.2'}")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("issue")
    p.add_argument("--label", required=True)
    p.add_argument("--quota", type=int, default=DEFAULT_QUOTA)
    p.add_argument("--paid-plan", action="store_true", help="the account is on Workers Paid: no 20,000/day total cap")
    p = sub.add_parser("revoke")
    p.add_argument("id")
    sub.add_parser("list")
    p = sub.add_parser("usage")
    p.add_argument("--days", type=int, default=7)
    sub.add_parser("selftest")
    args = ap.parse_args(argv)
    return {"issue": cmd_issue, "revoke": cmd_revoke, "list": cmd_list, "usage": cmd_usage,
            "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
