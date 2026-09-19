"""
Local server: serves public/ exactly as Cloudflare does, plus write endpoints that only exist
locally so the dashboard's "My Notes" and (phase 2) "Review" tabs can save to the git-tracked
source files and trigger a rebuild.

  GET  /...                        static files under public/
  GET  /api/status                 {"local": true}
  GET  /api/curated/<slug>         programs/<slug>/curated.json
  PUT  /api/curated/<slug>         replace curated.json (JSON body), rebuild that program
  GET  /api/review/<slug>          programs/<slug>/commitments.reviewed.json
  PUT  /api/review/<slug>          replace commitments.reviewed.json, rebuild
  GET  /api/queue                  scout/queue/*.json (pending social posts)          [phase 2]
  POST /api/queue/<id>             {"decision": "approve|reject|not-a-commit", ...}    [phase 2]

Usage: python collegedash.py serve [--port 8000]
"""

from __future__ import annotations

import datetime
import email.utils
import hashlib
import http.server
import json
import os
import posixpath
import re
import traceback
import urllib.parse
from functools import partial

from collect import common

SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def _json(self, code: int, obj, extra_headers: dict | None = None) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else None

    def _file_for(self, kind: str, slug: str) -> str | None:
        if not SLUG_RE.match(slug):
            return None
        name = {"curated": "curated.json", "review": "commitments.reviewed.json"}.get(kind)
        return os.path.join(common.program_dir(slug), name) if name else None

    def _handle_blocked(self) -> bool:
        raw_path = urllib.parse.urlparse(self.path).path
        norm_path = posixpath.normpath(urllib.parse.unquote(raw_path))
        if re.match(r"^/(archive|data)($|/)", norm_path, re.IGNORECASE):
            self._json(404, {"ok": False, "error": "Not found"})
            return True
        return False

    def _handle_v1(self) -> bool:
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/v1" or path == "/api/v1/":
            self._json(404, {"ok": False, "error": "Not found"})
            return True
        if not path.startswith("/api/v1/"):
            return False

        if self.command not in ("GET", "HEAD"):
            self._json(405, {"ok": False, "error": "Method not allowed"}, {"Allow": "GET, HEAD"})
            return True

        sub = path[len("/api/v1/"):]
        rel_file = None
        if sub == "status":
            rel_file = os.path.join("archive", "refresh-state.json")
        elif sub == "programs":
            rel_file = os.path.join("data", "programs", "index.json")
        elif sub.startswith("programs/"):
            slug = sub[len("programs/"):]
            if not SLUG_RE.match(slug):
                self._json(400, {"ok": False, "error": "Invalid identifier"})
                return True
            rel_file = os.path.join("data", "programs", f"{slug}.json")
        elif sub == "camps":
            rel_file = os.path.join("data", "camps", "index.json")
        elif sub == "trends":
            rel_file = os.path.join("data", "trends", "index.json")
        elif sub == "commitments":
            rel_file = os.path.join("data", "commitments", "index.json")
        else:
            self._json(404, {"ok": False, "error": "Not found"})
            return True

        full_path = os.path.join(common.PUBLIC_DIR, rel_file)
        if not os.path.isfile(full_path):
            self._json(404, {"ok": False, "error": "Not found"})
            return True

        try:
            with open(full_path, "rb") as f:
                content = f.read()
        except OSError:
            self._json(503, {"ok": False, "error": "Data is temporarily unavailable"})
            return True

        etag = f'"{hashlib.sha256(content).hexdigest()[:16]}"'
        mtime = os.path.getmtime(full_path)
        last_modified = email.utils.formatdate(mtime, usegmt=True)

        inm = self.headers.get("If-None-Match")
        if inm:
            inm_tags = [t.strip() for t in inm.split(",")]
            if "*" in inm_tags or etag in inm_tags or f"W/{etag}" in inm_tags:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Last-Modified", last_modified)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return True
        elif self.headers.get("If-Modified-Since"):
            ims = self.headers.get("If-Modified-Since")
            try:
                ims_dt = email.utils.parsedate_to_datetime(ims)
                mtime_dt = datetime.datetime.fromtimestamp(int(mtime), tz=datetime.timezone.utc)
                if mtime_dt <= ims_dt:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.send_header("Last-Modified", last_modified)
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    return True
            except Exception:
                pass

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", last_modified)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)
        return True

    def do_HEAD(self):
        if self._handle_v1():
            return
        if self._handle_blocked():
            return
        super().do_HEAD()

    def do_GET(self):
        if self._handle_v1():
            return
        if self._handle_blocked():
            return
        if self.path == "/api/status":
            return self._json(200, {"local": True, "root": common.ROOT})
        m = re.match(r"^/api/(curated|review)/([^/?]+)$", self.path)
        if m:
            path = self._file_for(m.group(1), m.group(2))
            if not path:
                return self._json(400, {"error": "bad slug"})
            return self._json(200, common.read_json(path, {}))
        if self.path == "/api/queue":
            qdir = os.path.join(common.ROOT, "scout", "queue")
            items = []
            if os.path.isdir(qdir):
                for f in sorted(os.listdir(qdir)):
                    if f.endswith(".json"):
                        items.append(common.read_json(os.path.join(qdir, f)))
            return self._json(200, {"items": items})
        # "no-store" for data so edits show up immediately
        if self.path.startswith("/data/") or self.path.startswith("/archive/"):
            self.protocol_version = "HTTP/1.1"
        return super().do_GET()

    def end_headers(self):
        if self.path.startswith("/data/") or self.path.startswith("/archive/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_PUT(self):
        if self._handle_v1():
            return
        if self._handle_blocked():
            return
        m = re.match(r"^/api/(curated|review)/([^/?]+)$", self.path)
        if not m:
            return self._json(404, {"error": "unknown endpoint"})
        path = self._file_for(m.group(1), m.group(2))
        if not path:
            return self._json(400, {"error": "bad slug"})
        try:
            payload = self._body()
            if not isinstance(payload, dict):
                return self._json(400, {"error": "JSON object required"})
            common.write_json(path, payload)
            import build
            build.build(common.load_registry())
            return self._json(200, {"ok": True, "path": os.path.relpath(path, common.ROOT)})
        except Exception as e:
            traceback.print_exc()
            return self._json(500, {"error": str(e)})

    def do_POST(self):
        if self._handle_v1():
            return
        if self._handle_blocked():
            return
        m = re.match(r"^/api/queue/([^/?]+)$", self.path)
        if not m:
            return self._json(404, {"error": "unknown endpoint"})
        try:
            from scout import review  # phase 2
        except ImportError:
            return self._json(501, {"error": "review queue not implemented yet (phase 2)"})
        try:
            result = review.decide(m.group(1), self._body() or {})
            import build
            build.build(common.load_registry())
            return self._json(200, result)
        except Exception as e:
            traceback.print_exc()
            return self._json(500, {"error": str(e)})


def main(port: int = 8000):
    handler = partial(Handler, directory=common.PUBLIC_DIR)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"CollegeDash local server: http://127.0.0.1:{port}/  (serving {common.PUBLIC_DIR}; Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
