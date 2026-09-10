"""Unit tests for tools/feedback_queue.py.

    python tests/test_feedback_queue.py

Nothing here touches Cloudflare or the network: the KV client is stubbed and every call it would
have made is recorded, so the destructive paths can be asserted on.
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import feedback_queue as fq  # noqa: E402

GOOD_KEY = "new:2026-09-10T14:23:05.123Z:k7f3q9x2"
TOMBSTONE = "filed:2026-09-10T14:23:05.123Z:k7f3q9x2"


class StubKV:
    """Records every operation. `values` seeds what get() returns."""

    def __init__(self, listing=None, values=None):
        self.listing = listing or []
        self.values = dict(values or {})
        self.calls: list[tuple] = []
        self.put_fails = False

    def list(self, prefix):
        self.calls.append(("list", prefix))
        return fq.normalize_entries(self.listing)

    def get(self, key):
        self.calls.append(("get", key))
        return self.values.get(key)

    def put(self, key, value, ttl, metadata=None):
        self.calls.append(("put", key, value, ttl))
        if self.put_fails:
            raise fq.WranglerError("simulated put failure")
        self.values[key] = value

    def delete(self, key):
        self.calls.append(("delete", key))
        self.values.pop(key, None)

    def ops(self):
        return [c[0] for c in self.calls]


def run(argv, kv, issue_exists=lambda n: True):
    """Run main() with stdout/stderr captured; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fq.main(argv, kv=kv, issue_exists=issue_exists)
    return code, out.getvalue(), err.getvalue()


class TestParsing(unittest.TestCase):
    def test_plain_json_array(self):
        self.assertEqual(fq.parse_kv_json('[{"name":"a"}]'), [{"name": "a"}])

    def test_tolerates_a_banner_prefixed_on_stdout(self):
        stdout = (
            "\n ⛅️ wrangler 4.131.0\n"
            "-------------------\n"
            '[{"name":"' + GOOD_KEY + '","metadata":{"m":"hi"}}]\n'
        )
        parsed = fq.parse_kv_json(stdout)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["name"], GOOD_KEY)

    def test_empty_and_garbage_raise_cleanly(self):
        for bad in ("", "   ", "wrangler exploded"):
            with self.assertRaises(fq.WranglerError):
                fq.parse_kv_json(bad)

    def test_missing_metadata_and_expiration_get_defaults(self):
        raw = [
            {"name": "new:2026-09-10T14:23:05.123Z:bbbbbbbb"},  # no metadata, no expiration
            {"name": "new:2026-09-09T14:23:05.123Z:aaaaaaaa", "metadata": None},
            {"name": "new:2026-09-11T14:23:05.123Z:cccccccc", "metadata": {"m": "hi"}, "expiration": 1},
        ]
        entries = fq.normalize_entries(raw)
        self.assertEqual(len(entries), 3)
        self.assertEqual([e["metadata"] for e in entries[:2]], [{}, {}])
        self.assertIsNone(entries[0]["expiration"])
        # sorted oldest first by key, which is chronological
        self.assertEqual([e["name"][:14] for e in entries], ["new:2026-09-09", "new:2026-09-10", "new:2026-09-11"])
        # and formatting a row with no metadata must not raise
        for e in entries:
            fq.format_row(e)

    def test_list_subcommand_survives_entries_without_metadata(self):
        kv = StubKV(listing=[{"name": GOOD_KEY}])
        code, out, _ = run(["list"], kv)
        self.assertEqual(code, 0)
        self.assertIn(GOOD_KEY, out)

    def test_split_key(self):
        self.assertEqual(fq.split_key(GOOD_KEY)[0], "new")
        for bad in ("", "new:not-a-date:k7f3q9x2", GOOD_KEY.upper(), "new:2026-09-10T14:23:05.123Z:SHORT"):
            self.assertIsNone(fq.split_key(bad), bad)


class TestFile(unittest.TestCase):
    def test_malformed_key_exits_non_zero_and_deletes_nothing(self):
        for bad in ("nonsense", "new:2026-09-10:k7f3q9x2", "spam:2026-09-10T14:23:05.123Z:k7f3q9x2"):
            kv = StubKV()
            code, _, err = run(["file", bad, "--issue", "57"], kv)
            self.assertNotEqual(code, 0, bad)
            self.assertEqual(kv.ops(), [], "no KV call should have been made for " + bad)
            self.assertIn("malformed", err)

    def test_missing_issue_exits_non_zero_and_deletes_nothing(self):
        kv = StubKV(values={GOOD_KEY: '{"message":"hi"}'})
        code, _, err = run(["file", GOOD_KEY, "--issue", "9999"], kv, issue_exists=lambda n: False)
        self.assertNotEqual(code, 0)
        self.assertNotIn("delete", kv.ops())
        self.assertNotIn("put", kv.ops())
        self.assertIn("does not exist", err)
        self.assertIn("Nothing was deleted", err)

    def test_happy_path_puts_the_tombstone_before_deleting(self):
        kv = StubKV(values={GOOD_KEY: '{"message":"hi"}'})
        code, out, _ = run(["file", GOOD_KEY, "--issue", "57"], kv)
        self.assertEqual(code, 0)
        ops = kv.ops()
        self.assertLess(ops.index("put"), ops.index("delete"))
        put = next(c for c in kv.calls if c[0] == "put")
        self.assertEqual(put[1], TOMBSTONE)
        self.assertEqual(json.loads(put[2])["issue"], 57)
        self.assertEqual(put[3], fq.TOMBSTONE_TTL)
        self.assertIn(("delete", GOOD_KEY), kv.calls)
        self.assertIn("57", out)

    def test_a_failed_put_aborts_before_the_delete(self):
        kv = StubKV(values={GOOD_KEY: '{"message":"hi"}'})
        kv.put_fails = True
        code, _, err = run(["file", GOOD_KEY, "--issue", "57"], kv)
        self.assertNotEqual(code, 0)
        self.assertNotIn("delete", kv.ops())
        self.assertIn("simulated put failure", err)

    def test_refiling_a_different_issue_needs_force(self):
        kv = StubKV(values={GOOD_KEY: '{"message":"hi"}', TOMBSTONE: '{"issue":12,"filed":"x"}'})
        code, _, err = run(["file", GOOD_KEY, "--issue", "57"], kv)
        self.assertNotEqual(code, 0)
        self.assertNotIn("delete", kv.ops())
        self.assertIn("#12", err)

        kv2 = StubKV(values={GOOD_KEY: '{"message":"hi"}', TOMBSTONE: '{"issue":12,"filed":"x"}'})
        code2, _, _ = run(["file", GOOD_KEY, "--issue", "57", "--force"], kv2)
        self.assertEqual(code2, 0)
        self.assertIn("delete", kv2.ops())

    def test_refiling_the_same_issue_is_idempotent(self):
        kv = StubKV(values={GOOD_KEY: '{"message":"hi"}', TOMBSTONE: '{"issue":57,"filed":"x"}'})
        code, _, _ = run(["file", GOOD_KEY, "--issue", "57"], kv)
        self.assertEqual(code, 0)
        self.assertIn("delete", kv.ops())


class TestOtherCommands(unittest.TestCase):
    def test_count(self):
        kv = StubKV(listing=[{"name": GOOD_KEY}, {"name": "new:2026-09-11T00:00:00.000Z:zzzzzzzz"}])
        code, out, _ = run(["count", "--json"], kv)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["count"], 2)

    def test_show_rejects_a_malformed_key_without_reading(self):
        kv = StubKV()
        code, _, err = run(["show", "bogus"], kv)
        self.assertNotEqual(code, 0)
        self.assertEqual(kv.ops(), [])
        self.assertIn("malformed", err)

    def test_delete_rejects_a_malformed_key(self):
        kv = StubKV()
        code, _, _ = run(["delete", "bogus"], kv)
        self.assertNotEqual(code, 0)
        self.assertEqual(kv.ops(), [])

    def test_npx_is_resolved_with_shutil_which(self):
        # Bare "npx" raises FileNotFoundError (WinError 2) on Windows because the executable is
        # npx.CMD and CreateProcess ignores PATHEXT.
        import inspect

        self.assertIn("shutil.which", inspect.getsource(fq._npx))


if __name__ == "__main__":
    unittest.main()
