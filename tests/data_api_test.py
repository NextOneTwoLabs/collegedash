"""Contract test suite for serve.py /api/v1/ and raw data access controls (issue #240).

    python tests/data_api_test.py
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import serve
from collect import common

FAILS: list[str] = []
TOTAL = 0


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        msg = f"{name}: {detail}" if detail else name
        FAILS.append(msg)
        print(f"  FAIL: {msg}")
        return False
    return True


def request_raw(host: str, port: int, method: str, path: str, headers: dict | None = None, body: bytes | None = None):
    conn = http.client.HTTPConnection(host, port, timeout=10)
    hdrs = headers or {}
    conn.request(method, path, body=body, headers=hdrs)
    res = conn.getresponse()
    data = res.read()
    conn.close()
    return res.status, res.headers, data


def main() -> int:
    # Start local server on ephemeral port
    handler = partial(serve.Handler, directory=common.PUBLIC_DIR)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_port
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    try:
        # 1. Test all 6 v1 routes
        routes = [
            ("/api/v1/programs", "data/programs/index.json"),
            ("/api/v1/programs/ucla", "data/programs/ucla.json"),
            ("/api/v1/camps", "data/camps/index.json"),
            ("/api/v1/trends", "data/trends/index.json"),
            ("/api/v1/commitments", "data/commitments/index.json"),
            ("/api/v1/status", "archive/refresh-state.json"),
        ]

        for route, disk_rel in routes:
            status, hdrs, body = request_raw("127.0.0.1", port, "GET", route)
            ok(f"GET {route} status 200", status == 200, f"got {status}")
            ok(
                f"GET {route} content-type json",
                "application/json" in hdrs.get("Content-Type", ""),
                f"got {hdrs.get('Content-Type')}",
            )
            # Preserves local live-reload edit loop via no-store
            ok(
                f"GET {route} cache-control no-store",
                hdrs.get("Cache-Control") == "no-store",
                f"got {hdrs.get('Cache-Control')}",
            )
            # issue #345: the local server runs with sessions off, as the Worker without SESSION_SECRET does
            ok(
                f"GET {route} X-CollegeDash-Session off",
                hdrs.get("X-CollegeDash-Session") == "off",
                f"got {hdrs.get('X-CollegeDash-Session')}",
            )
            etag = hdrs.get("ETag")
            ok(f"GET {route} has etag", bool(etag and etag.startswith('"')), f"got {etag}")

            # Verify body JSON matches disk
            disk_path = os.path.join(common.PUBLIC_DIR, disk_rel)
            if os.path.exists(disk_path):
                disk_data = json.loads(open(disk_path, "r", encoding="utf-8").read())
                resp_data = json.loads(body.decode("utf-8"))
                ok(f"GET {route} payload parity with {disk_rel}", resp_data == disk_data)

        # 2. Test conditional GET (If-None-Match -> 304 and If-Modified-Since -> 304)
        status, hdrs, _ = request_raw("127.0.0.1", port, "GET", "/api/v1/programs")
        etag = hdrs.get("ETag")
        last_modified = hdrs.get("Last-Modified")
        status_cond, hdrs_cond, body_cond = request_raw(
            "127.0.0.1", port, "GET", "/api/v1/programs", headers={"If-None-Match": etag}
        )
        ok("conditional GET with INM yields 304", status_cond == 304, f"got {status_cond}")
        ok("304 response has empty body", len(body_cond) == 0, f"body length {len(body_cond)}")
        ok("304 preserves etag", hdrs_cond.get("ETag") == etag)

        if last_modified:
            status_ims, hdrs_ims, body_ims = request_raw(
                "127.0.0.1", port, "GET", "/api/v1/programs", headers={"If-Modified-Since": last_modified}
            )
            ok("conditional GET with IMS yields 304", status_ims == 304, f"got {status_ims}")
            ok("IMS 304 response has empty body", len(body_ims) == 0)

        # 3. Test HEAD request on v1 route
        status_head, hdrs_head, body_head = request_raw("127.0.0.1", port, "HEAD", "/api/v1/programs")
        ok("HEAD /api/v1/programs yields 200", status_head == 200, f"got {status_head}")
        ok("HEAD has etag", bool(hdrs_head.get("ETag")))
        ok("HEAD body is empty", len(body_head) == 0, f"body length {len(body_head)}")

        # 4. Test invalid slug formats (400 Bad Request)
        for bad_slug in ["ucla_bruins", "UCLA", "bad..slug", "invalid!slug", "a" * 65]:
            status_bad, _, body_bad = request_raw(
                "127.0.0.1", port, "GET", f"/api/v1/programs/{urllib.parse.quote(bad_slug)}"
            )
            ok(f"invalid slug '{bad_slug}' yields 400", status_bad == 400, f"got {status_bad}")
            resp = json.loads(body_bad.decode("utf-8"))
            ok(f"invalid slug error message", resp == {"ok": False, "error": "Invalid identifier"})

        # 5. Test missing slug (404 Not Found)
        status_404, _, body_404 = request_raw("127.0.0.1", port, "GET", "/api/v1/programs/non-existent-slug-xyz")
        ok("missing slug yields 404", status_404 == 404, f"got {status_404}")
        resp_404 = json.loads(body_404.decode("utf-8"))
        ok("missing slug error payload", resp_404 == {"ok": False, "error": "Not found"})

        # 6. Test non-GET/HEAD method on v1 (405 Method Not Allowed)
        status_405, hdrs_405, body_405 = request_raw("127.0.0.1", port, "POST", "/api/v1/programs")
        ok("POST on v1 yields 405", status_405 == 405, f"got {status_405}")
        ok("405 includes Allow header", hdrs_405.get("Allow") == "GET, HEAD", f"got {hdrs_405.get('Allow')}")
        resp_405 = json.loads(body_405.decode("utf-8"))
        ok("405 error payload", resp_405 == {"ok": False, "error": "Method not allowed"})

        # 7. Test direct raw path blocking (/data/* and /archive/*)
        blocked_paths = [
            "/data/programs/index.json",
            "/data/programs/ucla.json",
            "/data/camps/index.json",
            "/data/trends/index.json",
            "/data/commitments/index.json",
            "/data/registry.json",
            "/archive/2024.json",
            "/data",
            "/data/",
            "/archive",
            "/archive/",
        ]
        for p in blocked_paths:
            # GET
            st, hd, b = request_raw("127.0.0.1", port, "GET", p)
            ok(f"GET raw path {p} blocked 404", st == 404, f"got {st}")
            ok(f"GET raw path {p} JSON body", json.loads(b.decode("utf-8")) == {"ok": False, "error": "Not found"})
            # HEAD
            st_h, _, b_h = request_raw("127.0.0.1", port, "HEAD", p)
            ok(f"HEAD raw path {p} blocked 404", st_h == 404, f"got {st_h}")
            ok(f"HEAD raw path {p} body empty", len(b_h) == 0, f"body length {len(b_h)}")

        # 8. Test evasion and normalization attempts
        evasions = [
            "//data/programs/index.json",
            "/data%2fprograms%2findex.json",
            "/data%2Fprograms%2Findex.json",
            "/DATA/programs/index.json",
            "/Data/Programs/Index.json",
            "/archive/../data/programs/index.json",
            "/data/../archive/2024.json",
            "/ARCHIVE/2024.json",
        ]
        for p in evasions:
            st, _, b = request_raw("127.0.0.1", port, "GET", p)
            ok(f"evasion {p} blocked 404", st == 404, f"got {st}")
            ok(f"evasion {p} JSON body", json.loads(b.decode("utf-8")) == {"ok": False, "error": "Not found"})

        # 9. Test PUT on raw path is blocked
        st_put, _, b_put = request_raw(
            "127.0.0.1", port, "PUT", "/data/programs/index.json", body=b'{"hack": true}'
        )
        ok("PUT on raw path blocked 404", st_put == 404, f"got {st_put}")
        ok("PUT on raw path JSON body", json.loads(b_put.decode("utf-8")) == {"ok": False, "error": "Not found"})

        # 10. Test local dev status
        st_status, _, b_status = request_raw("127.0.0.1", port, "GET", "/api/status")
        ok("GET /api/status yields 200", st_status == 200, f"got {st_status}")
        ok("GET /api/status local: true", json.loads(b_status.decode("utf-8")).get("local") is True)

        # 11. Issue #345 phase 2: the local server checks no keys. A made-up key (built here, so no key-shaped literal
        # is in the tree), junk, Basic, an empty header and a key in the query are all served, sessions "off", with no
        # WWW-Authenticate and no cookie.
        fake = "cdash" + "_live_" + "0" * 12 + "_" + "f" * 64
        cases = [
            ("Bearer made-up key", "/api/v1/status", {"Authorization": "Bearer " + fake}),
            ("Bearer junk", "/api/v1/status", {"Authorization": "Bearer junk"}),
            ("Basic", "/api/v1/status", {"Authorization": "Basic eDp5"}),
            ("empty Authorization", "/api/v1/status", {"Authorization": ""}),
            ("key in the query", "/api/v1/status?key=" + fake, {}),
        ]
        for name, path, headers in cases:
            st, hd, _ = request_raw("127.0.0.1", port, "GET", path, headers=headers)
            ok(f"local keys ignored ({name}): 200 off, no WWW-Authenticate, no cookie",
               st == 200 and hd.get("X-CollegeDash-Session") == "off" and not hd.get("WWW-Authenticate")
               and not hd.get("Set-Cookie"), f"got {st} {hd.get('X-CollegeDash-Session')}")

    finally:
        httpd.shutdown()

    print(f"\n{TOTAL - len(FAILS)}/{TOTAL} checks passed")
    if FAILS:
        for f in FAILS:
            print(f"  failed: {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
