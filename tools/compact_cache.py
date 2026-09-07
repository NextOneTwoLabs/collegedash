"""Compress plain .cache/http/<key>.body files to <key>.body.gz in place, one at a time, so it
works even when the disk is nearly full. Also drops cached bodies of Scorecard bulk zips (huge,
already parsed into data/scorecard-bulk.json).

    python tools/compact_cache.py
"""

import gzip
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache", "http")

before = after = n = 0
for name in sorted(os.listdir(CACHE)):
    if not name.endswith(".body"):
        continue
    src = os.path.join(CACHE, name)
    meta_path = src[:-5] + ".json"
    url = ""
    try:
        url = json.load(open(meta_path, encoding="utf-8")).get("url", "")
    except Exception:
        pass
    size = os.path.getsize(src)
    before += size
    if "Most-Recent-Cohorts-Institution" in url or size > 60_000_000:
        os.remove(src)  # bulk zip: parsed already, never needed again
        continue
    dst = src + ".gz"
    with open(src, "rb") as fi, gzip.open(dst, "wb", compresslevel=6) as fo:
        while True:
            chunk = fi.read(1 << 20)
            if not chunk:
                break
            fo.write(chunk)
    os.remove(src)
    after += os.path.getsize(dst)
    n += 1
    if n % 200 == 0:
        print(f"  {n} files, {before / 1e6:.0f} MB -> {after / 1e6:.0f} MB", flush=True)
print(f"compacted {n} bodies: {before / 1e6:.0f} MB -> {after / 1e6:.0f} MB")
