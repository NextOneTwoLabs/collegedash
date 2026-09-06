"""Athletics-site adapters. Each adapter module exposes:

    urls(program, registry) -> dict with keys roster, rosterSeason(year), schedule, scheduleSeason(year), news
    parse_roster(html, base_url) -> {"season": int|None, "players": [...], "staff": [...]}
    parse_bio(html) -> {...}
    parse_schedule(html, base_url) -> {"season": int|None, "games": [...]}
    parse_news(html, base_url) -> [{"title","url","date"}]

Player record shape (shared by every adapter):
    number, name, pos (GK/D/M/F), posLabel, height, heightIn, classLabel, classCode (FR/SO/JR/SR/GR),
    hometown, highSchool, previousSchool, major, bioUrl, social {instagram, x}
"""

from importlib import import_module


def get(platform: str):
    return import_module(f"collect.adapters.{platform}")
