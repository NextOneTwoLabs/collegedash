r"""
Times Higher Education's "Best universities in the United States" table.

Unlike every other collector in this package this one is *not* run on a schedule. The ranking is
published once a year, so the parsed table is committed as data/the-us-rankings-2026.json and
refreshing it is a deliberate annual act (tools/the_rank_check.py --refetch shows the diff first).
Nothing here is wired into refresh.yml.

    parse_table(html)   -> {"rankLabel", "rankYear", "rows": [...]}  offline; what the fixture drives
    build_asset(html)   -> the committed asset dict, provenance envelope included
    fetch_table()       -> (html, meta)                              live, robots.txt checked first

Row shape, mirroring the columns the page actually prints:

    {"name": "Harvard University",              verbatim, including any no-break space
     "nameKey": "harvard university",           normalised; this is what a join compares
     "theSlug": "harvard-university",           from the /world-university-rankings/<slug> href
     "usRank": 3, "tied": true,                 "=3" -> rank 3, tied
     "worldRank": "=5",                         raw; also "1501+" and "251-300"
     "overall": "97.1", "overallBanded": false} raw; 116 of the 171 rows are banded, e.g. "10.3-27.2"

Four rows need real normalisation before any name can be compared, and two of them are ranked
programs of ours that exact matching would otherwise silently drop:

    Purdue University West Lafayette    two U+00A0 no-break spaces
    Northeastern University, US         one U+00A0 no-break space
    University of Hawai’i at Mānoa      U+2019 apostrophe, U+0101 macron   (our "hawaii", =63)
    Rutgers University–New Brunswick    U+2013 en dash                      (our "rutgers", =66)

THE reserves all rights in the ranking and licenses ranking marks commercially; their robots.txt
permits the fetch but grants no republication right. The owner has chosen attribution on the card
plus a row in the FAQ sources table. Keeping the whole ranking in one committed file is deliberate,
so that if THE ever objects it can be removed cleanly.
"""

from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

from . import common

NAME = "the-us-rankings"
SOURCE_URL = "https://www.timeshighereducation.com/student/best-universities/best-universities-united-states"
RANK_LABEL = "US Rank 2026"
RANK_YEAR = 2026
TABLE_ID = "rankingTable"
RANKING_HREF = re.compile(r"/world-university-rankings/([^/?#]+)")

# A descriptive agent rather than the browser string collect.common sends by default: this is one
# annual read of one public page, and the publisher should be able to see who asked for it.
HEADERS = {
    "User-Agent": "CollegeDashBot/1.0 (+https://college.nextonetwo.com; annual ranking asset refresh)",
}

US_RANK_RE = re.compile(r"^(=?)(\d+)$")
BANDED_RE = re.compile(r"\d\s*[-–—]\s*\d")  # "10.3-27.2", or "54.3-56.3" with an en dash

# Dropped before comparison because they carry no identity: "University of X" and "X University"
# have to fold together, and THE writes "Northeastern University, US" where nobody else does.
STOPWORDS = frozenset({"the", "of", "at", "in", "us", "usa", "united", "states"})


def norm_key(s: str | None) -> str:
    r"""Fold a university name to the string a join compares. Case, accents, punctuation and the
    stopwords above only -- never a similarity score, because fuzzy matching on this very list
    pairs Penn State with the University of Pennsylvania (issue #46, and #48 before it).

        'University of Hawai’i at Mānoa'    -> 'university hawaii manoa'
        'Rutgers University–New Brunswick'  -> 'rutgers university new brunswick'
        'Purdue University West Lafayette'  -> 'purdue university west lafayette'
    """
    s = unicodedata.normalize("NFKD", s or "")                  # NBSP -> space, macron -> combining
    s = "".join(c for c in s if not unicodedata.combining(c))   # drop the combining macron
    s = re.sub("['’ʻ]", "", s)                       # Hawai'i, curly or okina, -> Hawaii
    s = s.replace("–", "-").replace("—", "-")        # en / em dash, stripped with the rest
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(w for w in s.split() if w not in STOPWORDS)


def parse_us_rank(text: str) -> tuple[int, bool]:
    """'=3' -> (3, True); '3' -> (3, False). Every row on the page matches; anything else raises
    rather than being guessed at, because the rank is the one field that ends up on a card."""
    m = US_RANK_RE.match(common.clean(text))
    if not m:
        raise ValueError(f"unparseable US rank: {text!r}")
    return int(m.group(2)), bool(m.group(1))


def parse_table(html: str) -> dict:
    """Parse the ranking table out of the page. Raises when the table is missing or a row is not
    the shape the asset promises: a silently short table would quietly blank cards."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id=TABLE_ID) or soup.find("table")
    if table is None:
        raise ValueError("no ranking table on the page")

    rows, seen = [], {}
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue  # the header row, which is all <th>
        link = cells[2].find("a", href=RANKING_HREF)
        if link is None:
            raise ValueError(f"row without a /world-university-rankings/ link: {cells[2].get_text()!r}")
        name = re.sub(r"\s*\n\s*", " ", link.get_text()).strip()  # verbatim otherwise; NBSP kept
        slug = RANKING_HREF.search(link["href"]).group(1)
        if slug in seen:
            raise ValueError(f"duplicate ranking slug {slug!r} ({seen[slug]!r} and {name!r})")
        seen[slug] = name
        us_rank, tied = parse_us_rank(cells[0].get_text())
        overall = common.clean(cells[3].get_text())
        rows.append({
            "name": name,
            "nameKey": norm_key(name),
            "theSlug": slug,
            "usRank": us_rank,
            "tied": tied,
            "worldRank": common.clean(cells[1].get_text()),
            "overall": overall,
            "overallBanded": bool(BANDED_RE.search(overall)),
        })
    if not rows:
        raise ValueError("ranking table held no data rows")
    return {"rankLabel": RANK_LABEL, "rankYear": RANK_YEAR, "rows": rows}


def build_asset(html: str, *, source_url: str = SOURCE_URL, fetched_at: str | None = None) -> dict:
    """The committed asset: the provenance envelope every source file in this repo carries, with
    the rows inline rather than under "data", because in this file the rows are the data."""
    table = parse_table(html)
    return {
        "collector": NAME,
        "sourceUrl": source_url,
        "fetchedAt": fetched_at or common.now_iso(),
        "rankLabel": table["rankLabel"],
        "rankYear": table["rankYear"],
        "rows": table["rows"],
    }


def fetch_table(*, max_age_hours: float | None = None) -> tuple[str, dict]:
    """Live read of the ranking page. robots.txt is checked first even though THE's is a plain
    Drupal block with no agent rules at all: that check is this repo's habit, not an optimisation.
    Contrast US News, whose robots.txt names and blocks Claude-family agents across the whole site."""
    if not common.robots_allowed(SOURCE_URL):
        raise common.FetchError(f"robots.txt disallows {SOURCE_URL}")
    return common.fetch_text(SOURCE_URL, headers=HEADERS, max_age_hours=max_age_hours)
