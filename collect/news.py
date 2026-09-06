"""
Program news headlines from the athletics site, with recruiting-related items flagged.

Writes programs/<slug>/sources/news.json: { items: [{title,url,date,recruiting:bool}] }.
Signing-day / class-announcement releases are the authoritative 'signed' signal for commitments.
"""

from __future__ import annotations

import re

from . import adapters, common

NAME = "news"
RECRUIT_RE = re.compile(
    r"\bsign(?:s|ed|ing)\b|national letter|\bNLI\b|recruiting class|incoming class|class of 20\d\d|"
    r"welcome[sd]?\b|newcomer|commit|add(?:s|ed) .* to (?:roster|program)|transfer",
    re.I,
)


def collect(program: dict, registry: dict) -> dict:
    ad = adapters.get(program["athletics"]["platform"])
    u = ad.urls(program, registry)
    html, meta = common.fetch_text(u["news"], max_age_hours=12)
    items = ad.parse_news(html, program["athletics"]["baseUrl"])
    # Sidearm sites also publish an RSS feed with proper dates; merge it in when the adapter has one.
    if u.get("rss") and hasattr(ad, "parse_rss"):
        try:
            xml_text, _ = common.fetch_text(u["rss"], max_age_hours=12)
            items = ad.parse_rss(xml_text, program["athletics"]["baseUrl"]) + items
        except common.FetchError as e:
            common.log(f"news: rss failed: {e}")
    for it in items:
        it["recruiting"] = bool(RECRUIT_RE.search(it["title"]))
    # Keep the archive growing: merge with what we already have (by url).
    prev = common.load_source(program["slug"], NAME)
    known = {i["url"]: i for i in (prev["data"]["items"] if prev else [])}
    for it in items:
        known[it["url"]] = {**known.get(it["url"], {}), **it}
    merged = sorted(known.values(), key=lambda i: i.get("date") or "", reverse=True)
    data = {"items": merged, "recruitingItems": [i for i in merged if i.get("recruiting")]}
    common.save_source(program["slug"], NAME, data, url=u["news"], collector=NAME,
                       extra={"fromCache": meta.get("fromCache", False)})
    common.log(f"news: {len(items)} on page, {len(merged)} archived, {len(data['recruitingItems'])} recruiting-related")
    return data
