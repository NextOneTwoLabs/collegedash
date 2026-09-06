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

import http.server
import json
import os
import re
import traceback
from functools import partial

from collect import common

SLUG_RE = re.compile(r"^[a-z0-9-]+$")


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else None

    def _file_for(self, kind: str, slug: str) -> str | None:
        if not SLUG_RE.match(slug):
            return None
        name = {"curated": "curated.json", "review": "commitments.reviewed.json"}.get(kind)
        return os.path.join(common.program_dir(slug), name) if name else None

    def do_GET(self):
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
