"""
Adapter for Sidearm Sports athletics sites (current Nuxt generation: goduke.com, usctrojans.com
and most other D1 sites). Pages are server-rendered.

Roster:   /sports/<sport>/roster[/{year}]   -> first <table> (No., Name, Pos., Ht., Year, Hometown,
          High School/Previous School, [Club Team]) plus "Coaching Staff" / "Support Staff" tables
Bio:      /sports/<sport>/roster/<slug>/<id>  -> .c-rosterbio__playerfields + .sidearm_prose body
Schedule: /sports/<sport>/schedule[/{year}]  -> div.s-game-card-standard cards (no <time> tags),
          or, on sites still on the older theme, li.sidearm-schedule-game rows (see
          _parse_legacy_games)
News:     /sports/<sport>/archives (links) and /rss?path=wsoc (titles + pubDate)
"""

from __future__ import annotations

import collections
import json
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import common

CLASS_CODES = [
    (re.compile(r"^(r-?|rs-?|redshirt\s*)(fr|fresh)", re.I), "R-FR"), (re.compile(r"^(r-?|rs-?|redshirt\s*)(so|soph)", re.I), "R-SO"),
    (re.compile(r"^(r-?|rs-?|redshirt\s*)(jr|jun)", re.I), "R-JR"), (re.compile(r"^(r-?|rs-?|redshirt\s*)(sr|sen)", re.I), "R-SR"),
    (re.compile(r"^(fr|fresh)", re.I), "FR"), (re.compile(r"^(so|soph)", re.I), "SO"), (re.compile(r"^(jr|jun)", re.I), "JR"),
    (re.compile(r"^(sr|sen)", re.I), "SR"), (re.compile(r"^(gr|grad|5th|fifth|6th)", re.I), "GR"),
]
HEIGHT_RE = re.compile(r"(\d)\s*[-'′’]\s*(\d{1,2})")
TITLE_YEAR_RE = re.compile(r"(?:19|20)\d\d")
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
DATE_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})$", re.I)
# ---------- who the head coach is (issue #33) ----------
# Measured over all 1,887 staff rows on the 313 cached Sidearm roster pages: 44 distinct titles
# contain the word "head". `head coach` as a literal missed 41 pages whose coach is titled
# "Head Women's Soccer Coach" (31), "Head Soccer Coach" (8) or "Head Women's Coach" (1) - one of
# them (evansville) with a typographic apostrophe, the only non-ASCII character in any title here.
#
# The words allowed between "head" and "coach" are a closed list rather than `.*`, because
# `head\b.*\bcoach` also matches six rows in the same corpus that belong to somebody else:
# "Head Strength & Conditioning Coach" (4 spellings), "Head Olympic Strength and Conditioning
# Coach" and "Head Sports Performance Coach (Women's Soccer, Softball, Men's Tennis, Golf)".
# Publishing a strength coach as the head coach is worse than publishing nobody.
#
# APOS: ' and the typographic ’ one page uses; ‘ ´ ` and U+FFFD (what a mis-decoded page would
# leave here, though none in the corpus does) cost nothing and save a re-run of this exercise.
APOS = r"['‘’´`�]"
HEAD_QUALIFIER = rf"(?:women{APOS}?s?|men{APOS}?s?|varsity|soccer|wsoc|w|and|&)"
HEAD_COACH_RE = re.compile(rf"\bhead\s+(?:{HEAD_QUALIFIER}\s+){{0,5}}coach\b", re.I)
# A word in front of "head" that makes the title somebody else's job: "Associate Head Coach",
# "Assistant Head Coach", "Former Head Coach (1979-2024)", and the "Assosicate Head Coach" a real
# page spells that way. Scoped to what stands before "head" so that a title which merely mentions
# another role ("Head Coach / Associate Athletic Director") still reads as the head coach; over the
# corpus that scoping changes no row, and every row it excludes is excluded for the reason given.
# "Interim" and "Co-" are deliberately absent: an interim or co-head coach is the head coach.
NOT_HEAD_RE = re.compile(rf"\b(?:asso[cs]\w*|assist\w*|asst\.?|deputy|volunteer|former)\s+"
                         rf"(?:{HEAD_QUALIFIER}\s+)*head\b|\bemerit", re.I)
# The roster page is one program's, but a combined staff directory can list the other program's
# coach too, so a title that says men's and never says women's is not this program's head coach.
# No cached page carries one today; D2 and D3 share staff pages far more often than D1.
MENS_RE = re.compile(rf"\bmen{APOS}?s?\b", re.I)
WOMENS_RE = re.compile(rf"\b(?:w|women{APOS}?s?|wsoc)\b", re.I)


def is_head_coach(title: str) -> bool:
    """Whether this staff title is the women's soccer head coach's.

    build.py publishes the first staff row for which this is true, in page order. After this rule
    exactly one cached page matches more than one row: Butler, which lists two "Co-Head Coach"
    rows because it genuinely has two.
    """
    if not HEAD_COACH_RE.search(title) or NOT_HEAD_RE.search(title):
        return False
    return not (MENS_RE.search(title) and not WOMENS_RE.search(title))

MONTH_NAMES = "January|February|March|April|May|June|July|August|September|October|November|December"
LEGACY_SIDE_CLASSES = {"sidearm-schedule-home-game": "H", "sidearm-schedule-away-game": "A",
                       "sidearm-schedule-neutral-game": "N"}
# Legacy schedule rows date themselves 'Aug 16 (Sun)' - the weekday suffix is what stops DATE_RE,
# which anchors at end of string, from matching. Measured across all 3,226 legacy rows in the
# corpus: every one of them is this shape, so the weekday is optional only for safety.
LEGACY_DATE_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\b", re.I)
# aria-labels inside the row spell the date out in full ('... on August 16, 2026 at 2:00 PM'),
# which is the only place the row states its year.
LEGACY_ARIA_DATE_RE = re.compile(rf"\b({MONTH_NAMES})\s+(\d{{1,2}}),?\s+((?:19|20)\d\d)\b", re.I)
LEGACY_RESULT_RE = re.compile(r"^([WLT]),?$")
LEGACY_SCORE_RE = re.compile(r"\b(\d+)\s*-\s*(\d+)\b")
# Exhibitions and scrimmages, marked however the site writes it (issues #122, #25). Measured over
# the 24,740 games on the 1,220 cached Sidearm schedule pages: 'exhibition' 1,090 rows, '(Exh.)' 288,
# '(Exhib.)/(Exhib)/(Exhi.)' 45, '(EX)/(Ex.)' 43, '(EXH)' 31, '(EXB)/(Exb.)' 8, an unparenthesised
# 'EXH' ('South Florida - EXH', or alone in the location column) 11, 'scrimmage' 100. Before this,
# the legacy branch matched 'exhibition' and 'exh.' and the current-theme branch only 'exhibition',
# and 336 rows -- 87 of them with a result, so 61 published season records -- were counted as real
# games.
#
# What is deliberately NOT a marker, both measured on the same corpus:
#   * 'alumni', 381 rows. Every one is a venue or a promotion: Notre Dame's ground is Alumni Stadium
#     (where NCAA rounds are played), and 'Alumni Day' / 'Alumni Game' are giveaways. None is an
#     exhibition.
#   * 'spring', 65 rows: the note 'Spring Schedule', and towns such as BOILING SPRINGS, NC.
# 'ex' is only a marker inside parentheses, and every other token must be a whole word, so 'Exeter'
# and 'Essex' are not markers either. tests/sidearm_schedule_test.py pins all of this.
# 'Exhibitions' (plural) is what radford and missouri-state print in the card's own label, so the
# plural is part of the word, not an afterthought: the pre-change current-theme branch matched it
# only because its regex had no word boundary at all.
EXHIBITION_RE = re.compile(r"\bexhibitions?\b|\bexh(?:i|ib)?\b\.?|\bexb\b\.?|\(ex\.?\)|\bscrimmages?\b", re.I)
# The same markers where they decorate the opponent's name: '(Exh.)', '(Scrimmage)', 'Florida - EXH'.
# A bare 'Scrimmage' is not stripped: it is part of names like 'Blue vs. Yellow Scrimmage'.
OPPONENT_MARKER_RE = re.compile(r"\s*[-\u2013]\s*(?:exhibitions?|exh(?:i|ib)?|exb)\.?\s*$"
                                r"|\((?:exhibitions?|exh(?:i|ib)?|exb|ex|scrimmages?)\.?\)", re.I)
# Tokens that sit in the location column but are not a place.
LEGACY_NON_PLACE_RE = re.compile(r"^(exhibitions?|exh(?:i|ib)?\.?|exb\.?|scrimmages?|tv|radio|live stats|watch|listen|tickets)\b[:.]?$", re.I)
GAME_LINK_LABELS = ("box score", "recap", "live stats", "history", "watch", "listen", "tickets")

# ---------- rankings and seeds in front of the opponent's name (issue #129) ----------
# Only '#21 Ohio State' was ever read, and that is the one spelling the corpus no longer contains.
# Measured over every cached Sidearm page, re-parsed with the pre-change adapter: 550 decorated names
# on 269 pages - 337 'No. N', 93 '(N)', 58 'RV', 23 '#a/b', 20 'Seed', 19 'No. N seed' - plus the
# long tail this had to be written from rather than guessed at: '[8] Ohio State', '(RV) Iowa',
# '[RV] Xavier', '#T18 Wake Forest', '#7/T9 UCLA', '#NR/RV/23 Brown', '(25/19) Texas Tech',
# '(25/-) Colorado State', 'RV/No. 21 Kansas', 'RV-University of Wisconsin', '(5-Seed) #23/18 Baylor',
# 'Seeded UCLA' and a bare '19 Xavier'.
#
# A poll marker and a tournament seed are different things and are stored separately: `opponentRank`
# is the national ranking the site already renders as '#N', and `opponentSeed` is the bracket seed,
# which nothing renders yet. 'RV' (receiving votes) and 'NR' (not ranked) are markers with no number:
# they are removed from the name and leave both fields None.
#
# Two rules keep this from damaging names:
#   * a prefix is only removed if something is left afterwards, so 'Seed ULM' and 'Seed Old Dominion'
#     - where the label is all that precedes the name - keep their names;
#   * a number alone, with no '#', 'No.' or bracket around it, is never read as a rank, so
#     '2026 Summit League Soccer Championship' and '1st Round' are left alone.
_POLL_TOKEN = r"(?:T\s*\d{1,2}|\d{1,2}|RV|NR|-)"
# '#14/#16', '25/19', 'NR/RV/23', 'T3'; a group of poll positions separated by slashes
_POLL_GROUP = rf"{_POLL_TOKEN}(?:\s*/\s*#?\s*{_POLL_TOKEN})*"
RANK_PREFIXES = [
    # (regex, kind) - kind 'rank' sets opponentRank, 'seed' sets opponentSeed, 'label' neither
    (re.compile(rf"^\(\s*(\d{{1,2}})\s*-\s*seed\s*\)\s*", re.I), "seed"),          # (5-Seed)
    (re.compile(rf"^\(\s*#\s*(\d{{1,2}})\s+seed(?:ed)?\s*\)\s*", re.I), "seed"),   # (#1 Seed): daemen, issue #302
    (re.compile(rf"^[\[(]\s*#?\s*({_POLL_GROUP})\s*[\])]\s*", re.I), "bracket"),      # (6) [8] (RV) (25/19)
    (re.compile(rf"^#\s*({_POLL_GROUP})\s+seed(?:ed|s)?\b\.?\s*", re.I), "seed"),     # #2 Seed, #5 Seeded
    (re.compile(rf"^#\s*({_POLL_GROUP})\s*", re.I), "rank"),                            # #21 #14/#16 #T18 #RV/8/17
    (re.compile(rf"^No\.?\s*({_POLL_GROUP})\s+seed(?:ed|s)?\b\.?\s*", re.I), "seed"),  # No. 1 Seed, No. 1 Seeded
    (re.compile(rf"^No\.?\s*({_POLL_GROUP})\s*", re.I), "rank"),                        # No. 10, No. 6/7
    (re.compile(r"^(RV|NR)\s*[-/]?\s*", re.I), "label"),                                # RV, NR, RV/No. 21, RV-Wisconsin
    (re.compile(r"^seed(?:ed)?\b\.?\s*", re.I), "label"),                              # Seed, Seeded
]
# A bare leading number is deliberately NOT read as a rank. The corpus holds exactly one ('19
# Xavier'), and a rule that caught it would also rewrite a row called '24 Hour Classic' or '3 Point
# Challenge' into a ranked opponent. One missed rank is the cheaper mistake; the suite pins it.


def _first_number(group: str) -> int | None:
    """The first real position in a poll group: 'NR/RV/23' -> 23, 'T18' -> 18, 'RV/-' -> None."""
    for tok in re.split(r"/", group or ""):
        m = re.search(r"\d{1,2}", tok)
        if m:
            return int(m.group(0))
    return None


def rank_seed_and_name(raw: str) -> tuple[int | None, int | None, str]:
    """(rank, seed, name) from an opponent label that may carry poll positions or a bracket seed.

    The name is only stripped when something survives: `rank_seed_and_name('Seed ULM')` is
    (None, None, 'ULM') but `rank_seed_and_name('Seed')` is (None, None, 'Seed').
    """
    name = common.clean(raw or "")
    rank = seed = None
    while name:
        for rx, kind in RANK_PREFIXES:
            m = rx.match(name)
            if not m:
                continue
            rest = common.clean(name[m.end():])
            if not rest:
                return rank, seed, name  # the label is all there is: keep the name as it stands
            group = m.group(1) if m.groups() else ""
            value = _first_number(group)
            if kind == "bracket":
                # a single number in brackets is a tournament seed; anything with a slash or an
                # RV/NR token is a poll line printed in brackets
                if re.fullmatch(r"\s*\d{1,2}\s*", group or ""):
                    seed = seed if seed is not None else value
                else:
                    rank = rank if rank is not None else value
            elif kind == "seed":
                seed = seed if seed is not None else value
            elif kind in ("rank", "bare"):
                rank = rank if rank is not None else value
            name = rest
            break
        else:
            break
    return rank, seed, name


def urls(program: dict, registry: dict) -> dict:
    t = registry["sources"]["athleticsPlatforms"]["sidearm"]
    a = program["athletics"]
    fmt = lambda key, **kw: t[key].format(baseUrl=a["baseUrl"], sportPath=a["sportPath"], **kw)
    return {
        "roster": fmt("roster"),
        "rosterSeason": lambda y: fmt("rosterSeason", year=y),
        "schedule": fmt("schedule"),
        "scheduleSeason": lambda y: fmt("scheduleSeason", year=y),
        "news": fmt("news"),
        "rss": fmt("rss") if "rss" in t else None,
        # Read only when the roster page lists no staff at all (issue #145; see
        # athletics_site._coaches_page_staff). Not a registry template, so the registry is untouched;
        # of the 11 Sidearm sites fetched for #145, 9 serve the sport's coaches here as a server-rendered
        # table and 2 (ohio-university, st-thomas) as a page filled in by the browser, which yields none.
        "coaches": f"{a['baseUrl']}{a['sportPath']}/coaches",
    }


def class_code(label: str) -> str:
    s = (label or "").strip()
    for rx, code in CLASS_CODES:
        if rx.search(s):
            return code
    return ""


def height_inches(txt: str) -> int | None:
    m = HEIGHT_RE.search(txt or "")
    return int(m.group(1)) * 12 + int(m.group(2)) if m else None


def _season_from_title(soup: BeautifulSoup) -> int | None:
    t = soup.find("title")
    if t:
        m = TITLE_YEAR_RE.search(t.get_text())
        if m:
            return int(m.group(0))
    return None


# Roster table headers vary by site generation and theme ("Name" / "Full Name" / "Player",
# "Pos." / "Position", "Year" / "Academic Year" / "Class" / "Cl.", "Number Jersey Number" on WMT
# tables). Everything is folded onto one canonical key before column lookup.
HEADER_ALIASES = {
    "full name": "name", "player": "name", "player name": "name", "name": "name",
    "position": "pos", "pos.": "pos", "pos": "pos",
    "academic year": "year", "athletic year": "year", "year": "year", "yr.": "year", "yr": "year",
    "class": "year", "cl.": "year", "cl": "year", "eligibility": "year", "elig.": "year",
    "height": "ht", "ht.": "ht", "ht": "ht",
    "number": "#", "no": "#", "no.": "#", "num": "#", "num.": "#", "#": "#", "jersey number": "#", "number jersey number": "#",
    "club team": "club", "club": "club",
}


def _norm_header(text: str) -> str:
    h = common.clean(text).lower()
    return HEADER_ALIASES.get(h, h)


def _header_index(table) -> tuple[dict[str, int], int, str]:
    """Return (header index, number of header rows, caption). Staff tables have a caption row
    ('Coaching Staff') above the real header row. Header names are canonicalised through
    HEADER_ALIASES; the first column wins when two headers fold onto the same key.

    One exception (issue #313): a legacy Sidearm grid table (mercy) heads first AND last name 'Name'
    twice, side by side (<td class="player_firstname"> / <td class="player_lastname">). The second of
    two adjacent 'Name' headers is indexed as "last name", so the row loop can join the two."""
    rows = table.find_all("tr")[:2]
    caption = ""
    for n, tr in enumerate(rows, start=1):
        raw = [common.clean(c.get_text(" ")).lower() for c in tr.find_all(["th", "td"])]
        heads = [HEADER_ALIASES.get(h, h) for h in raw]
        if "name" in heads:
            idx: dict[str, int] = {}
            for i, h in enumerate(heads):
                # both headers literally 'Name': 'Name | Full Name' (both alias to "name") is not a
                # first/last pair and must not be joined into a doubled name
                if (raw[i] == "name" and i > 0 and raw[i - 1] == "name" and idx.get("name") == i - 1
                        and "last name" not in idx):
                    idx["last name"] = i
                idx.setdefault(h, i)
            return idx, n, caption
        caption = " ".join(heads)
    return {}, 0, caption


def _col(idx: dict, *names):
    """Column index for the first header that equals one of `names`; failing that, the first
    header that starts with one of them (so 'hometown / high school' still serves 'hometown')."""
    for n in names:
        if n in idx:
            return idx[n]
    for n in names:
        for h, i in idx.items():
            if h.startswith(n):
                return i
    return None


# ---------- high school vs. previous school (issue #227) ----------
# `_col(idx, "high school", "previous", "last school")` was the pre-fix `ci["hs"]` lookup. Its
# exact-match pass tries "high school" first, so any page with a real "High School" column (a
# plain one, or a combined "High School / Last School" / "High School (Previous College)" header
# reached through the prefix pass) was never affected. The break was in `_col`'s PREFIX pass:
# checked one candidate at a time across every header, so once "high school" found nothing it
# went on to try "previous" and "last school" as prefixes - and a genuine "Previous School" or
# "Last School" column (holding a transfer's prior COLLEGE, not a high school) starts with
# exactly that. That column won `ci["hs"]`, which did two things: published the transfer's
# college as their high school, and set `ci["hs"] is not None`, which skipped the one rule able to
# split a combined "Hometown / High School" column - so a current player on the same page got no
# high school at all. Measured over the cached pages (#225's discovery report): 104 Sidearm
# programs, 2,023 current rows with an empty high school and 6,307 more across past rosters.
#
# The fix is three lookups, tried in order in the row loop below, instead of one shared one:
#   1. `_col(idx, "high school")` - a real High School column, exact or prefixed (so the combined
#      headers above, and 'high school/previous school' etc., are unaffected) - always wins.
#   2. failing that, the existing "Hometown / High School" split (guarded by `" / " in hometown`,
#      per row) - exactly as it was.
#   3. failing THAT too (no explicit column, and this row's hometown isn't a combined one to
#      split), `hs_fallback` - the old, broad `_col(idx, "high school", "previous", "last
#      school")` match, but refused whenever it lands on the same column `_prev_col` already
#      claims as the real Previous School. That guard is what stops the fix from reintroducing
#      its own bug: a page shaped exactly like the 104 above differs from this tier only by
#      whether a row's hometown cell happens to contain a "/" (tier 2 fires first when it does),
#      so without the guard, a current player with a blank combined cell would fall through to
#      tier 3 and read the very "Previous School" column tier 1/2 exist to keep out of `hs`.
#      Tier 3 exists for the residual pages with no explicit High School column, no combined one,
#      and no real Previous School column either - the site's only school-ish column already
#      couldn't be trusted before this fix, and won't be trusted more precisely by it, so the
#      instruction is the conservative one: keep publishing what was already there rather than
#      invent an empty field. Measured examples: cbulancers.com's only such column is titled
#      "Previous Team" and holds a real high school for 25 of its 28 rows ('ThunderRidge HS') and
#      a real transfer college for the rest ('Northern Illinois University') - genuinely
#      unsplittable without a marker this page doesn't have. goblackbears.com's same-shaped column
#      holds mostly club names ('FC Köln') and a couple of colleges tagged "(NCAA)" - never
#      demonstrably a high school - and tier 3 preserves that as-is too, rather than risk the
#      opposite mistake of discarding a page where it might occasionally be right.
#
# `_prev_col`, below, is a real previous-school column only, never a header that also promises
# "hometown" (that is a combined column for `_split_slash`, not a plain previous-school field) and
# never one that also says "club" or "team" (see `_prev_col`'s own docstring) - so `previousSchool`
# is never populated from a column tier 3 might also be reading from for `highSchool`.
PREV_SCHOOL_NAMES = ("previous school", "previous college", "last school", "last college")


def _prev_col(idx: dict) -> int | None:
    """Column index for a genuine previous-school (transfer college) field, or None.

    Deliberately narrower than `_col`: a header that also says "club" or "team" - 'Club Team /
    Previous School', 'Previous School/Club Team', 'Previous Team' - holds a club name on the
    cached pages that have one ('Kings Hammer ECNL', 'PDA', 'FC Stars of Massachusetts'), not a
    school, so treating it as `previousSchool` would invent a college that was never there. A bare
    'Previous' (jmusports.com: 'Northwestern State') is accepted as an exact match only - not as a
    prefix, which is what let 'Previous Team' slip through the pre-fix lookup (`_col`'s prefix pass
    tried "previous" before "last school", and 'previous team'.startswith('previous') is True).
    """
    if "previous" in idx:
        return idx["previous"]
    for n in PREV_SCHOOL_NAMES:
        if n in idx:
            return idx[n]
    for n in PREV_SCHOOL_NAMES:
        for h, i in idx.items():
            if h.startswith(n) and "club" not in h and "team" not in h:
                return i
    return None


def _home_col(idx: dict) -> int | None:
    """Column index for hometown - `_col(idx, "hometown")`'s plain first-match prefix search,
    except that a "hometown"-prefixed header which also names "high school" wins over one that
    doesn't, when a page has more than one.

    Found on prairie-view-am (issue #227, Huatuo's review of the first version of this fix):
    the page has both "Hometown/Previous School" (holds a club, e.g. 'Mansfield, Texas / Sting
    Royal') and, separately, the real "Hometown / High School" ('Mansfield, Texas / Mansfield
    High School'). `_col`'s prefix search returns whichever of the two comes first in the table's
    own column order - on this page, the club one - so the real combined column was never read at
    all: the club name reached both `highSchool` (via the tier-2 split of the wrong column) and
    `previousSchool` (from its own dedicated column), and the correct, present, correctly-labelled
    high school was silently dropped. Preferring the header that actually says "high school" is
    order-independent and matches every other multi-hometown-column page in the corpus
    (wmubroncos.com, nevadawolfpack.com, usfdons.com), where the "high school" one already carries
    the real data and the other is either a real transfer college or junk."""
    candidates = [h for h in idx if h.startswith("hometown")]
    if not candidates:
        return None
    for h in candidates:
        if "high school" in h:
            return idx[h]
    return idx[candidates[0]]


def _player_record(*, number, name, pos_label, height, class_label, hometown, high_school,
                   previous_school="", club="", major="", bio_url=None, social=None) -> dict:
    # #224: a cell the site filled with 'null' / 'None' (or ending ' / null') is absent, never shown as a word
    d = common.drop_placeholders
    number, pos_label, height, class_label = d(number), d(pos_label), d(height), d(class_label)
    hometown, high_school, previous_school, club, major = d(hometown), d(high_school), d(previous_school), d(club), d(major)
    ht = height or ""
    return {
        "number": number or "", "name": name, "pos": common.norm_pos(pos_label), "posLabel": pos_label or "",
        "height": re.sub(r"\s*''\s*$", '"', ht).replace("' ", "'").replace("′", "'").replace("″", '"'),
        "heightIn": height_inches(ht),
        "classLabel": class_label or "", "classCode": class_code(class_label or ""),
        "hometown": hometown or "", "highSchool": high_school or "", "previousSchool": previous_school or "",
        "major": major or "", "club": club or "", "bioUrl": bio_url, "social": social or {},
    }


def _split_slash(txt: str) -> tuple[str, str]:
    """'Milton, Ontario / Kielburger Secondary' -> ('Milton, Ontario', 'Kielburger Secondary')."""
    if " / " in txt:
        a, b = txt.split(" / ", 1)
        return common.clean(a), common.clean(b)
    return txt, ""


def parse_roster_tables(soup: BeautifulSoup, base_url: str, social_by_url: dict | None = None) -> tuple[list, list]:
    """Players and staff from <table> markup: the player table (name + position columns) and the
    'Coaching Staff' / 'Support Staff' tables (name + title). Shared with the WMT adapter, whose
    table theme uses the same header vocabulary."""
    social_by_url = social_by_url or {}
    players, staff = [], []
    for table in soup.find_all("table"):
        idx, nhead, caption = _header_index(table)
        if not idx:
            continue
        keys = " ".join(idx) + " " + caption
        rows = table.find_all("tr")[nhead:]
        # A staff table says "Title" (or "Alma Mater"); some themes label the coach role "Position",
        # so a name+position table with none of number/height/year/hometown is staff too.
        is_staff = ("title" in idx or "alma mater" in idx
                    or ("pos" in idx and not any(k in idx for k in ("#", "ht", "year", "hometown"))))
        if "name" in idx and "pos" in idx and not is_staff:
            real_prev = _prev_col(idx)
            ci = {"num": _col(idx, "#"), "name": _col(idx, "name"), "last": idx.get("last name"),
                  "pos": _col(idx, "pos"), "ht": _col(idx, "ht"),
                  "yr": _col(idx, "year"), "home": _home_col(idx),
                  "hs": _col(idx, "high school"), "prev": real_prev, "club": _col(idx, "club"),
                  "major": _col(idx, "major", "academic major"),
                  # Last resort only (see the loop below): the pre-fix broad match, for a page with
                  # no explicit High School column, no splittable combined one on this row, and no
                  # real Previous School column either - so there is nothing better on offer.
                  "hs_fallback": _col(idx, "high school", "previous", "last school")}
            for tr in rows:
                cells = tr.find_all(["td", "th"])
                if len(cells) < 4:
                    continue

                def cell(k):
                    i = ci.get(k)
                    return common.clean(cells[i].get_text(" ")) if i is not None and i < len(cells) else ""

                name_cell = cells[ci["name"]] if ci["name"] is not None and ci["name"] < len(cells) else None
                link = name_cell.find("a", href=True) if name_cell else None
                name = cell("name")
                if not name or name.lower() in ("name", "full name"):
                    continue
                if ci["last"] is not None:  # first and last name in two 'Name' columns (issue #313)
                    name = common.clean(f"{name} {cell('last')}")
                hometown = cell("home")
                prev = cell("prev")
                if ci["hs"] is not None:
                    # A tier-1 column can itself be a single combined one - 'High School /
                    # Previous Schools', 'High School / Last School' (distinct from the
                    # 'Hometown / High School' combo tier 2 handles) - so it needs the same split
                    # the pre-fix code always applied to whatever `ci["hs"]` pointed to. Left
                    # unsplit (Huatuo's review of the first version of this fix), a page whose only
                    # school column is shaped that way got a previously-clean high school polluted
                    # with an appended " / <College>" - e.g. sam-houston-state's Hannah Stipp,
                    # 'Circle HS' -> 'Circle HS / North Dakota State'. Splitting is a no-op for a
                    # plain 'High School' column, which never contains a slash. The remainder is
                    # only used as `previousSchool` when no real, distinct Previous School column
                    # already supplied one - `real_prev` from a separate column always wins.
                    hs, hs_prev = _split_slash(cell("hs"))
                    if not prev and hs_prev:
                        prev = hs_prev
                elif " / " in hometown:  # single 'Hometown / High School' column
                    hometown, hs = _split_slash(hometown)
                elif ci["hs_fallback"] is not None and ci["hs_fallback"] != real_prev:
                    # No explicit High School column, this row's hometown isn't a combined one to
                    # split, and there is no real Previous School column to protect - `hs_fallback`
                    # can only be the real `real_prev` column when one exists (never a club/team
                    # column, which `_prev_col` refuses), so this never resurrects issue #227's
                    # core bug. It exists for pages like cbulancers.com, whose only school-ish
                    # column is literally titled "Previous Team" but holds real high schools
                    # ('ThunderRidge HS'...) for most rows and real transfer colleges for the rest
                    # (issue #227: ambiguous and unsplittable - keep today's value rather than
                    # invent an empty one).
                    hs = cell("hs_fallback")
                else:
                    hs = ""
                bio_url = urljoin(base_url, link["href"]) if link else None
                players.append(_player_record(
                    number=cell("num"), name=name, pos_label=cell("pos"), height=cell("ht"), class_label=cell("yr"),
                    hometown=hometown, high_school=hs, previous_school=prev, club=cell("club"), major=cell("major"),
                    bio_url=bio_url, social=social_by_url.get(bio_url, {})))
        elif "name" in idx and is_staff:
            is_coaching = "coach" in keys
            title_col = idx.get("title", idx.get("pos"))
            for tr in rows:
                cells = tr.find_all(["td", "th"])
                if len(cells) <= max(idx["name"], title_col):
                    continue
                name = common.clean(cells[idx["name"]].get_text(" "))
                # cells sometimes hold escaped HTML ("Academic Coordinator<br><em>W Soccer, ...</em>")
                title = cells[title_col].get_text("\n")
                segs = [common.clean(re.sub(r"<[^>]+>", " ", x)) for x in re.split(r"<br\s*/?>|\n", title)]
                title = next((x for x in segs if x), "")
                link = cells[idx["name"]].find("a", href=True)
                if not name or name.lower() == "name":
                    continue
                staff.append({
                    "name": name, "title": title,
                    "isHeadCoach": is_head_coach(title),
                    "isCoach": is_coaching or bool(re.search(r"coach", title, re.I)),
                    "bioUrl": urljoin(base_url, link["href"]) if link else None, "social": {},
                })
    return players, staff


def _sr_labelled(el) -> tuple[str, str]:
    """('position', 'GK') from <span><span class="sr-only">Position</span> GK</span>."""
    label = ""
    for sr in el.select(".sr-only"):
        label = common.clean(sr.get_text(" ")).lower()
        sr.extract()
    return label, common.clean(el.get_text(" "))


def _parse_person_cards(soup: BeautifulSoup, base_url: str, social_by_url: dict) -> list[dict]:
    """Players from .s-person-card markup (current Sidearm theme). Used when the page carries no
    player table. Cards are rendered twice (list + standard variants), so dedupe on bio URL."""
    players, seen = [], set()
    for card in soup.select(".s-person-card"):
        a = card.find("a", href=re.compile(r"/roster/[a-z0-9-]+/\d+$"))
        if not a:
            continue
        bio_url = urljoin(base_url, a["href"])
        if bio_url in seen:
            continue
        h3 = card.select_one(".s-person-details__personal-single-line h3, .s-person-details__personal h3")
        name = common.clean(h3.get_text(" ")) if h3 else common.clean(a.get_text(" "))
        if not name:
            continue
        seen.add(bio_url)
        stats = {}
        for item in card.select(".s-person-details__bio-stats-item"):
            label, value = _sr_labelled(item)
            if label:
                stats.setdefault(label, value)
        stamp = card.select_one(".s-stamp__text")
        number = _sr_labelled(stamp)[1] if stamp else ""
        home_el = card.select_one("[data-test-id$='person-hometown'], .s-person-card__content__person__location-item")
        hs_el = card.select_one("[data-test-id$='person-high-school'], .s-person-card__content__person__high-school-item")
        hometown = _sr_labelled(home_el)[1] if home_el else ""
        high_school = _sr_labelled(hs_el)[1] if hs_el else ""
        club = next((v for k, v in stats.items() if k.startswith("custom field") or "club" in k), "")
        players.append(_player_record(
            number=number, name=name, pos_label=stats.get("position", ""), height=stats.get("height", ""),
            class_label=stats.get("academic year", stats.get("class", stats.get("year", ""))),
            hometown=hometown, high_school=high_school, club=club, bio_url=bio_url,
            social=social_by_url.get(bio_url, {})))
    return players


def _list_view_social(li) -> dict:
    """Instagram / X links from a legacy list-view item's social block."""
    social: dict[str, str] = {}
    for a in li.select(".sidearm-roster-player-social a[href]"):
        if "instagram.com" in a["href"]:
            social.setdefault("instagram", a["href"])
        elif "twitter.com" in a["href"] or "x.com/" in a["href"]:
            social.setdefault("x", a["href"])
    return social


def _parse_list_view(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Players from the legacy Sidearm list view, li.sidearm-roster-player (issue #156). Used only when
    neither the tables nor the person cards gave a player. Some legacy pages (Mercyhurst, Hawaii-Hilo)
    serve a grid table with no Name column and no player link beside this list, so the table cannot
    say who a row is and the list is the only place the name is. Rows are never joined to the table:
    every field here is read from the player's own list item.

    Each item carries its details twice (a compact block and a wide one); the first of each is the
    compact form the table shows ("Jr.", "GK"). A trailing parenthetical on the position is pronouns
    ("GK (she/her/hers)") and is dropped from the label."""
    players, seen = [], set()

    def first(li, cls: str) -> str:
        el = li.select_one(f".sidearm-roster-player-{cls}")
        return common.clean(el.get_text(" ")) if el else ""

    for li in soup.select("li.sidearm-roster-player"):
        name_el = li.select_one(".sidearm-roster-player-name h3") or li.select_one(".sidearm-roster-player-name a")
        name = common.clean(name_el.get_text(" ")) if name_el else ""
        if not name:
            continue
        link = li.select_one(".sidearm-roster-player-name a[href]")
        href = link["href"] if link else li.get("data-player-url")
        bio_url = urljoin(base_url, href) if href else None
        key = bio_url or name
        if key in seen:
            continue
        seen.add(key)
        forms = [re.sub(r"\s*\([^)]*\)\s*$", "", common.clean(x.get_text(" ")))
                 for x in li.select(".sidearm-roster-player-position-long-short")]
        pos = forms[-1] if forms else re.sub(r"\s*\([^)]*\)\s*$", "", first(li, "position"))
        social = _list_view_social(li)
        record = _player_record(
            number=first(li, "jersey-number"), name=name, pos_label=pos, height=first(li, "height"),
            class_label=first(li, "academic-year"), hometown=first(li, "hometown"), high_school=first(li, "highschool"),
            previous_school=first(li, "previous-school"), major=first(li, "major"), bio_url=bio_url, social=social)
        if not record["pos"] and forms:  # a short label norm_pos cannot map; the long form beside it may be
            record["pos"] = common.norm_pos(forms[0])
        players.append(record)
    return players


def _list_view_position(li) -> str:
    """The position label a legacy list-view item shows, without the height the same block carries:
    <div class="sidearm-roster-player-position"><span class="text-bold">Goalkeeper</span>
    <span class="sidearm-roster-player-height">5'9"</span></div> -> 'Goalkeeper'. A trailing
    parenthetical is pronouns and is dropped, as in _parse_list_view."""
    el = li.select_one(".sidearm-roster-player-position")
    if el is None:
        return ""
    bold = el.select_one(".text-bold")
    if bold is not None:
        txt = bold.get_text(" ")
    else:
        parts = [s for s in el.find_all(string=True)
                 if not any("sidearm-roster-player-height" in (p.get("class") or []) for p in s.parents if p is not el)]
        txt = " ".join(parts)
    return re.sub(r"\s*\([^)]*\)\s*$", "", common.clean(txt))


def _is_position_label(label: str) -> bool:
    """True when a list-view label is a playing position. The list-view block also holds 'Manager',
    'Student Intern' or a club name for non-players listed in the player table. So every part must
    map through common.pos_code: a POS_EXACT key exactly ('D', 'CB') or a part starting with a
    POS_MAP word or phrase, all of them 3+ letters ('Midfield', 'Center Back'), never merely 'm'."""
    ok = False
    for part in common.pos_parts(label):  # the same splitter as norm_pos (#263 part C); the rule is unchanged
        if not part.strip():
            continue
        if common.pos_code(part):
            ok = True
        else:
            return False
    return ok


def _fill_blank_positions_from_list_view(players: list[dict], soup: BeautifulSoup, base_url: str) -> None:
    """Issue #263. Legacy Sidearm pages serve the roster twice, as a table and as the list view
    (li.sidearm-roster-player). On some sites the table's Pos. cell is empty for every player
    (<td class="rp_position_short"></td>: the site filled in only the long position) while the list
    item beside it shows 'Goalkeeper' / 'Defender' - wheaton-college-il, spalding and mercy parsed to
    all-blank positions this way. For a table player whose position label is EMPTY, take the label
    from the list item with the same bio URL. Nothing else changes: a non-empty table label (even one
    norm_pos cannot map) is kept, a label that is not a playing position ('Manager') is not taken,
    and a player is matched only by bio URL, never by row order (the ordering trap of issue #183).
    A table with no player link in any row (mercy's) is first given its bio URLs by exact unique
    name in _link_unlinked_table_from_list_view (issue #313); other rows with no link are left as
    they are."""
    if not any(not p["posLabel"] for p in players):
        return
    by_url: dict[str, str] = {}
    for li in soup.select("li.sidearm-roster-player"):
        link = li.select_one(".sidearm-roster-player-name a[href]")
        href = link["href"] if link else li.get("data-player-url")
        if href:
            by_url.setdefault(urljoin(base_url, href), _list_view_position(li))
    for p in players:
        label = by_url.get(p["bioUrl"], "") if p["bioUrl"] and not p["posLabel"] else ""
        if label and _is_position_label(label):
            p["posLabel"] = label
            p["pos"] = common.norm_pos(label)


def _link_unlinked_table_from_list_view(players: list[dict], soup: BeautifulSoup, base_url: str) -> None:
    """Issue #313. Some legacy Sidearm grid tables (mercy) carry no player link in any row, while the
    list view beside them (li.sidearm-roster-player) links every player. With no bio URL the table
    rows could not be joined to the list, so their blank positions stayed blank and no bio was read.
    Only when NOT ONE table player has a bio URL, take each player's URL from the list item whose
    name is the same (case-insensitive, whitespace-normalised), and only when that name occurs once
    in the table and once in the list - never by row order (issue #183). A table with even one
    linked row is left exactly as it was. A player linked this way also takes the list item's social
    links when the table gave none (these pages have no person cards to take them from)."""
    if not players or any(p["bioUrl"] for p in players):
        return
    items: dict[str, list[str]] = {}
    social_by_url: dict[str, dict] = {}
    for li in soup.select("li.sidearm-roster-player"):
        name_el = li.select_one(".sidearm-roster-player-name h3") or li.select_one(".sidearm-roster-player-name a")
        link = li.select_one(".sidearm-roster-player-name a[href]")
        href = link["href"] if link else li.get("data-player-url")
        if name_el is not None and href:
            url = urljoin(base_url, href)
            items.setdefault(common.clean(name_el.get_text(" ")).lower(), []).append(url)
            social_by_url.setdefault(url, _list_view_social(li))
    in_table: dict[str, int] = {}
    for p in players:
        in_table[p["name"].lower()] = in_table.get(p["name"].lower(), 0) + 1
    for p in players:
        key = p["name"].lower()
        urls_ = items.get(key, [])
        if in_table[key] == 1 and len(set(urls_)) == 1:
            p["bioUrl"] = urls_[0]
            if not p["social"]:
                p["social"] = dict(social_by_url.get(urls_[0], {}))


# ---------- the legacy Vue/Knockout roster template's embedded JSON (issue #145) ----------
# george-mason, utah-state and wyoming serve no roster table, person card or list item: the page builds them in
# the browser from a roster object written into the server HTML as `new Vue({ el: '...', data: () => ({ roster:
# {...} ...`. That object is plain JSON already in the page, so it is read here with no browser - but it also holds
# staff email and phone, player birthdates, social accounts and photos, none of which may be stored. So a row is
# built ONLY from the named keys below, never by copying the object; everything else in it is ignored.
EMBEDDED_ROSTER_SIG = re.compile(r"new Vue\(\{\s*el:\s*(['\"])[^'\"]*\1,\s*data:\s*\(\)\s*=>\s*\(\{\s*roster:\s*(?=\{)")
# JSON key -> _player_record argument. The name (first_name + last_name), the height (height_feet, height_inches)
# and the long position (position_long, when position_short is empty) are read by name in _embedded_player.
EMBEDDED_PLAYER_FIELDS = {"jersey_number": "number", "position_short": "pos_label", "academic_year_short": "class_label",
                          "hometown": "hometown", "highschool": "high_school", "previous_school": "previous_school",
                          "major": "major"}
# JSON key -> staff row field. The name is firstname + lastname.
EMBEDDED_STAFF_FIELDS = {"title": "title"}


def _embedded_text(v) -> str:
    return common.clean(str(v)) if v not in (None, False) else ""


def _embedded_roster_object(html: str) -> dict | None:
    """The roster object after the legacy template's signature, when it is one: parses as JSON, carries the
    template's own keys and a non-empty players list whose entries all have first_name, last_name and
    jersey_number. An empty list is no roster, so its staff are not taken either."""
    m = EMBEDDED_ROSTER_SIG.search(html)
    if not m:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(html, m.end())
    except ValueError:
        return None
    if not isinstance(obj, dict) or "template_id" not in obj or "display_coaches" not in obj:
        return None
    players = obj.get("players")
    if not isinstance(players, list) or not players or not all(
            isinstance(p, dict) and {"first_name", "last_name", "jersey_number"} <= p.keys() for p in players):
        return None
    return obj


def _embedded_player(p: dict) -> dict | None:
    name = common.clean(f"{_embedded_text(p.get('first_name'))} {_embedded_text(p.get('last_name'))}")
    if not name or p.get("rp_hide"):  # rp_hide: the site itself does not show this player
        return None
    args = {arg: _embedded_text(p.get(key)) for key, arg in EMBEDDED_PLAYER_FIELDS.items()}
    if not args.get("pos_label"):
        args["pos_label"] = _embedded_text(p.get("position_long"))
    ft, inch = _embedded_text(p.get("height_feet")), _embedded_text(p.get("height_inches"))
    height = f"{ft}' {inch or 0}\"" if ft.isdigit() and ft != "0" else ""
    return _player_record(name=name, height=height, bio_url=None, social={},
                          **{k: args.get(k, "") for k in ("number", "pos_label", "class_label", "hometown",
                                                          "high_school", "previous_school", "major")})


def _embedded_staff(s: dict, is_coaching: bool) -> dict | None:
    name = common.clean(f"{_embedded_text(s.get('firstname'))} {_embedded_text(s.get('lastname'))}")
    if not name:
        return None
    row = {field: _embedded_text(s.get(key)) for key, field in EMBEDDED_STAFF_FIELDS.items()}
    title = row.get("title", "")
    return {"name": name, "title": title, "isHeadCoach": is_head_coach(title),
            "isCoach": is_coaching or bool(re.search(r"coach", title, re.I)), "bioUrl": None, "social": {}}


def _parse_embedded_roster(html: str) -> tuple[list[dict], list[dict]]:
    """(players, staff) from the legacy template's embedded roster object (issue #145), or ([], []) when the
    page does not carry it. Staff are the object's `coaches` then its `support` list. No bio URL is built: the
    object carries none."""
    obj = _embedded_roster_object(html)
    if not obj:
        return [], []
    players = [r for r in (_embedded_player(p) for p in obj["players"]) if r]
    staff = []
    for key, is_coaching in (("coaches", True), ("support", False)):
        for s in obj.get(key) or []:
            if isinstance(s, dict):
                row = _embedded_staff(s, is_coaching)
                if row:
                    staff.append(row)
    return players, staff


def looks_client_rendered(html: str) -> bool:
    """True when the roster page is a template filled in by the browser (legacy Sidearm Knockout /
    Vue sites, or the current theme's skeleton loader): the served HTML never contains players."""
    return ("{{ roster." in html or "v-cloak" in html or "@season @sport" in html
            or ("skeleton-loader" in html and "c-rosterpage" in html) or html.count("data-bind=") > 40)


def parse_roster(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    # social links live on the person cards, keyed by bio url
    social_by_url: dict[str, dict] = {}
    for card in soup.select(".s-person-card"):
        a = card.find("a", href=re.compile(r"/roster/[a-z0-9-]+/\d+$"))
        if not a:
            continue
        soc = {}
        for l in card.find_all("a", href=True):
            if "instagram.com" in l["href"]:
                soc["instagram"] = l["href"]
            elif "twitter.com" in l["href"] or "x.com/" in l["href"]:
                soc["x"] = l["href"]
        if soc:
            social_by_url[urljoin(base_url, a["href"])] = soc

    players, staff = parse_roster_tables(soup, base_url, social_by_url)
    if players:
        _link_unlinked_table_from_list_view(players, soup, base_url)
        _fill_blank_positions_from_list_view(players, soup, base_url)
    if not players:
        players = _parse_person_cards(soup, base_url, social_by_url)
    if not players:
        players = _parse_list_view(soup, base_url)
    if not players:  # issue #145: only when tables, person cards and the list view all found no player
        players, embedded_staff = _parse_embedded_roster(html)
        staff = staff or embedded_staff
    seen, uniq = set(), []
    for s in staff:
        k = s["bioUrl"] or s["name"]
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    return {"season": _season_from_title(soup), "players": players, "staff": uniq}


def parse_bio(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    meta = {}
    pf = soup.select_one(".c-rosterbio__playerfields")
    if pf:
        toks = [common.clean(t) for t in pf.get_text("\n").split("\n")]
        toks = [t for t in toks if t]
        i = 0
        while i < len(toks) - 1:
            if toks[i].endswith(":"):
                meta[toks[i][:-1].lower()] = toks[i + 1]
                i += 2
            else:
                i += 1
    candidates = soup.select(".sidearm_prose, .s-text-paragraph-longform")
    body = max(candidates, key=lambda e: len(e.get_text(" ", strip=True))) if candidates else None
    sections: dict[str, str] = {}
    if body:
        current, buf = "intro", []
        for el in body.descendants:
            if getattr(el, "name", None) == "strong":
                txt = common.clean(el.get_text(" "))
                if 2 < len(txt) < 60:
                    if buf:
                        sections[current] = common.clean(" ".join(buf))
                    current, buf = txt.rstrip(":"), []
                    continue
            if isinstance(el, str):
                t = common.clean(el)
                if t and not (el.parent and el.parent.name == "strong"):
                    buf.append(t)
        if buf:
            sections[current] = common.clean(" ".join(buf))
    return {"meta": meta, "sections": sections}


def _top_level_cards(soup: BeautifulSoup):
    cards = [d for d in soup.find_all("div") if any("s-game-card-standard" in c for c in (d.get("class") or []))]
    ids = {id(c) for c in cards}
    return [c for c in cards if not any(id(p) in ids for p in c.parents)]


def parse_schedule(html: str, base_url: str) -> dict:
    """Games from the schedule page, whichever theme it is served in.

    The current theme is tried first and the legacy one only when it yields nothing. Falling back
    on an empty result, rather than branching on which markup is present, is what makes this
    incapable of changing a program that already parses.

    That distinction is not theoretical. Seven programs that parse fine today contain the string
    'sidearm-schedule-game' - but in six of them (Michigan, 1,305 occurrences) every one of those
    is a CSS rule inside <style> for a theme the page does not use, and zero are elements. A
    marker test on the raw HTML would have fired on all six. Selecting elements, and only after
    the current theme has come up empty, does not.
    """
    soup = BeautifulSoup(html, "html.parser")
    season = _season_from_title(soup)
    games = _parse_game_cards(soup, base_url, season)
    if not games:
        # the legacy branch can recover a season the <title> did not state, so it reports one back
        season, games = _parse_legacy_games(soup, base_url, season)
    return {"season": season, "games": _spring_games(games)}


def _spring_games(games: list[dict]) -> list[dict]:
    """Fix the two things a spring block on a fall-season page gets wrong.

    1. **The year.** Both branches date a row by the page's season, because the rows give month and
       day only. A January-July game listed AFTER an August-December one is in the next calendar
       year: the '2025-26' page ends with spring 2026 (issues #122, #97). A spring block printed
       BEFORE the fall block (gonzaga 2024) is that season's own spring and keeps its year.
       Measured over the cached pages: 173 games fall in January-July, 169 of them after the fall.
       Every moved date agrees with the page's own second copy - the Nuxt payload's ISO datetimes
       (74), an aria-label full date (2), a Feb 29 that does not exist in the season year (1) - and
       the audit of PR #127 confirmed all 169 a third way, by the weekday each card prints.

    2. **The record.** A spring game is a non-championship-segment contest and does not count in the
       season record, and most sites say so in a section descriptor ('2025 Spring Exhibition
       Season'). Some rows omit it: okstate.com's 2024 page carries that descriptor on six of the
       seven spring cards and leaves it off the last one, 'vs Tulsa, W 3-2'. Read row by row that is
       a win, and it published Oklahoma State's 2024 record as 15-5-3 where the school's own release
       says 14-5-3. It is the only row of its kind in the corpus, and inheriting a descriptor down
       the page would be the more dangerous rule - the exhibition block usually comes FIRST, so a
       forward-inheriting descriptor would mark a whole fall season. So the rule is the plain one:
       on a page that has a fall block at all, a January-July game is a spring game and is not
       counted, whether or not its own row says so.

    A page with no August-December game is not a fall-season page, so neither rule applies to it.
    """
    if not any(g.get("date") and int(g["date"][5:7]) >= 8 for g in games):
        return games
    seen_fall = False
    for g in games:
        d = g.get("date")
        if not d:
            continue
        if int(d[5:7]) >= 8:
            seen_fall = True
            continue
        g["exhibition"] = True
        if seen_fall:
            g["date"] = f"{int(d[:4]) + 1}{d[4:]}"
    return games


def _parse_game_cards(soup: BeautifulSoup, base_url: str, season: int | None) -> list[dict]:
    """Games from div.s-game-card-standard cards (current Sidearm theme)."""
    games = []
    for c in _top_level_cards(soup):
        text = c.get_text(" | ", strip=True)
        stamp = c.select_one(".s-game-card__header__stamp")
        stamp_txt = common.clean(stamp.get_text()).lower() if stamp else ""
        info = c.select_one(".s-game-card__header__team-event-info")
        toks = [common.clean(t) for t in info.get_text("\n").split("\n")] if info else []
        toks = [t for t in toks if t]
        opp_raw = toks[0] if toks else ""
        rank, seed, opp_raw = rank_seed_and_name(opp_raw)
        exhibition = bool(EXHIBITION_RE.search(text))
        opponent = common.clean(OPPONENT_MARKER_RE.sub("", opp_raw)) or opp_raw
        loc_toks = [t for t in toks[1:] if not t.lower().startswith("tv:") and not t.lower().startswith("radio")]
        location = ", ".join(loc_toks[:2]) if loc_toks else None
        sc = c.select_one(".s-game-card__header__game-score-time")
        st = [common.clean(t) for t in sc.get_text("\n").split("\n")] if sc else []
        st = [t for t in st if t]
        result = score = date = None
        for t in st:
            if re.fullmatch(r"[WLT],?", t):
                result = t[0]
            elif re.fullmatch(r"\d+\s*-\s*\d+", t):
                score = re.sub(r"\s", "", t)
            else:
                dm = DATE_RE.match(t)
                if dm and season:
                    mon = MONTHS.get(dm.group(1).lower()[:3])
                    if mon:
                        date = f"{season}-{mon:02d}-{int(dm.group(2)):02d}"
        links = _game_links(c, base_url)
        if not opponent:
            continue
        games.append({
            "date": date, "datetime": None,
            "exhibition": exhibition,
            "conferenceGame": bool(c.select_one(".s-game-card__header__conf-text, .s-game-card__header__conf-logo")),
            "homeAway": "A" if stamp_txt.startswith("at") else "H" if stamp_txt.startswith("vs") else None,
            "opponent": opponent, "opponentRank": rank, "opponentSeed": seed, "location": location,
            "result": result, "score": score, "links": links,
        })
    return games


def _game_links(el, base_url: str) -> dict:
    """Box score / recap / history links on a game row, keyed by their label. The legacy template
    renders the same list twice (a mobile copy and a desktop one); keying by label collapses them.

    Last occurrence wins, which is what the current-theme branch has always done - Wake Forest is
    the one program in the corpus where it matters (two 'Box Score' links per row, a PDF and the
    live boxscore page) and switching to first-wins silently changed its stored links.
    """
    links = {}
    for a in el.find_all("a", href=True):
        label = common.clean(a.get_text(" ")).lower()
        if label in GAME_LINK_LABELS and a["href"] not in ("#", ""):
            links[label] = urljoin(base_url, a["href"])
    return links


def _lines(el) -> list[str]:
    """Non-empty text lines of an element, in order."""
    if el is None:
        return []
    return [t for t in (common.clean(x) for x in el.get_text("\n").split("\n")) if t]


def _legacy_date(date_el, season: int | None) -> str | None:
    """ISO date for a legacy row. The visible text gives month and day ('Aug 16 (Sun)'); the year
    comes from the season, as it does for every game in the current-theme branch.

    The rows also spell their dates out in aria-labels ('... on August 16, 2026 at 2:00 PM') and an
    earlier draft read the year from there. It was removed: across all 3,226 legacy rows in the
    corpus the aria year and the season agree every time an aria date exists at all (2,345 of
    them), so the code could not change an outcome. The one thing those labels are needed for -
    a page whose <title> states no year - is handled once per page in _parse_legacy_games instead.
    """
    lines = _lines(date_el)
    return _legacy_date_text(lines[0], season) if lines else None


def _legacy_date_text(line: str, season: int | None) -> str | None:
    """ISO date from a legacy date line ('Aug 16 (Sun)') and the season, or None."""
    m = LEGACY_DATE_RE.match(line)
    if not m:
        return None
    mon = MONTHS.get(m.group(1).lower()[:3])
    if not mon or not season:
        return None
    return f"{season}-{mon:02d}-{int(m.group(2)):02d}"


def _legacy_result(li) -> tuple[str | None, str | None]:
    """(result, score) for a legacy row, both read from the result box and neither without the
    other.

    A row that was not played says 'Canceled', 'Postponed' or 'No Contest' where the letter would
    be, which matches nothing here, so it needs no special case - and requiring the letter before
    keeping a score is what stops a row like 'Utah Valley, 1-0' (another pairing in a tournament
    bracket, of which there are two in the corpus) from being recorded as this team's score.

    The <li> also carries the letter as a class. That is not read: across the corpus the class and
    the box agree on all 1,011 rows that have a result, neither ever appears without the other,
    and a second source that never disagrees is a branch no input can exercise.
    """
    lines = _lines(li.select_one(".sidearm-schedule-game-result"))
    result = next((LEGACY_RESULT_RE.match(t).group(1) for t in lines if LEGACY_RESULT_RE.match(t)), None)
    if result is None:
        return None, None
    sm = LEGACY_SCORE_RE.search(" ".join(lines))
    return result, f"{sm.group(1)}-{sm.group(2)}" if sm else None


# A weekday ahead of the month, as the two-team row writes its date ('Sat, Aug 30').
LEGACY_WEEKDAY_PREFIX_RE = re.compile(r"^(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+", re.I)


def _two_team_date(li, season: int | None) -> str | None:
    """The date of a two-team legacy row (issue #302, daemen).

    This variant of the legacy theme has no .sidearm-schedule-game-opponent-date. It prints the date in
    .sidearm-schedule-game-date with the weekday first ('Sat, Aug 30'), so the weekday is dropped and the
    rest is read exactly as _legacy_date reads a legacy date. Only reached for a row that has no
    opponent-date element and does have the two-team block (.sidearm-schedule-game-team-school), so no
    other legacy row changes."""
    lines = _lines(li.select_one(".sidearm-schedule-game-date"))
    return _legacy_date_text(LEGACY_WEEKDAY_PREFIX_RE.sub("", lines[0]), season) if lines else None


def _two_team_result(li) -> tuple[str | None, str | None]:
    """(result, score) for a two-team legacy row (issue #302, daemen).

    The row prints each side's goals in its own .sidearm-schedule-game-result, under
    .sidearm-schedule-game-team-opponent and .sidearm-schedule-game-team-school, and no W/L/T letter, so
    _legacy_result finds nothing. The result follows from the two numbers, and the score is written the
    program's goals first, as the rest of the corpus stores it. Both sides must be a bare number: an
    unplayed, cancelled or postponed row leaves them empty or says so, and gets no result. A level score is a
    tie, as a shootout is in the season record."""
    def goals(side: str) -> int | None:
        text = " ".join(_lines(li.select_one(f".sidearm-schedule-game-team-{side} .sidearm-schedule-game-result")))
        return int(text) if re.fullmatch(r"\d{1,2}", text) else None
    own, opp = goals("school"), goals("opponent")
    if own is None or opp is None:
        return None, None
    return ("W" if own > opp else "L" if own < opp else "T"), f"{own}-{opp}"


def _legacy_location_tokens(li) -> list[str]:
    """City and venue for a legacy row.

    The location box also hosts the match-day promotion - Alabama A&M's home games nest a
    <div class="sidearm-schedule-game-opponent-promotion"> inside it - and taking the box's text
    wholesale turns a location into 'Huntsville, AL, Faculty & Staff Appreciation Day'. The place
    is always in the box's own <span> children, so those are read and the nested boxes are not.
    Falls back to the whole box for any theme that puts the text straight in the div.
    """
    el = li.select_one(".sidearm-schedule-game-location")
    if el is None:
        return []
    spans = el.find_all("span", recursive=False)
    if spans:
        return [t for s in spans for t in _lines(s)]
    return _lines(el)


def _parse_legacy_games(soup: BeautifulSoup, base_url: str, season: int | None) -> tuple[int | None, list[dict]]:
    """(season, games) from li.sidearm-schedule-game rows (the older Sidearm schedule theme,
    issue #35). The season comes back because these rows can supply one the page <title> did not.

    These pages are fully server-rendered - the rows are in the HTML as fetched - so the only
    thing that was missing was a parser. 159 of the 160 Sidearm programs that had no schedule at
    all are this template and nothing else.
    """
    rows = soup.select("li.sidearm-schedule-game")
    if season is None:
        # LIU is the one program in the corpus whose schedule <title> carries no year. Its rows
        # still state theirs in aria-labels, so the page's own most common year stands in for the
        # season - without which every row on such a page would be dateless, which is what the
        # current-theme branch does.
        years = collections.Counter(
            int(m.group(3))
            for li in rows
            for a in li.find_all(attrs={"aria-label": True})
            for m in [LEGACY_ARIA_DATE_RE.search(a.get("aria-label", ""))] if m
        )
        season = years.most_common(1)[0][0] if years else None

    games = []
    for li in rows:
        classes = li.get("class") or []
        name_el = li.select_one(".sidearm-schedule-game-opponent-name")
        opp_raw = common.clean(name_el.get_text(" ")) if name_el else ""
        rank, seed, opp_raw = rank_seed_and_name(opp_raw)
        opponent = common.clean(OPPONENT_MARKER_RE.sub("", opp_raw)) or opp_raw
        if not opponent:
            continue

        # "Exhibition" is as likely to sit in the location column as in the opponent's name, so
        # the whole row is searched - and then the word is kept out of `location`.
        exhibition = bool(EXHIBITION_RE.search(li.get_text(" ", strip=True)))

        # One of these three classes is on every one of the 3,226 legacy rows in the corpus. The
        # row also says 'at' or 'vs' in .sidearm-schedule-game-conference-vs, and an earlier draft
        # fell back to reading that; it is gone for the same reason the result-class fallback is,
        # namely that it agreed with the class on every row that had both and so could never
        # change an answer. A row with none of the three gets None, which is what the current-theme
        # branch returns when its own stamp says neither.
        home_away = next((v for c, v in LEGACY_SIDE_CLASSES.items() if c in classes), None)

        # The conference node is rendered empty on non-conference rows and carries the
        # conference's name ('CAA', 'A10') on conference ones, so presence alone means nothing.
        conf_el = li.select_one(".sidearm-schedule-game-conference")
        conference = bool(conf_el and common.clean(conf_el.get_text(" ")))

        loc_toks = [t for t in _legacy_location_tokens(li) if not LEGACY_NON_PLACE_RE.match(t)]
        result, score = _legacy_result(li)
        date_el = li.select_one(".sidearm-schedule-game-opponent-date")
        date = _legacy_date(date_el, season)
        if date_el is None and li.select_one(".sidearm-schedule-game-team-school"):
            # the two-team row (issue #302): see _two_team_date and _two_team_result
            date = _two_team_date(li, season)
            if result is None:
                result, score = _two_team_result(li)
        games.append({
            "date": date,
            "datetime": None,
            "exhibition": exhibition,
            "conferenceGame": conference,
            "homeAway": home_away,
            "opponent": opponent, "opponentRank": rank, "opponentSeed": seed,
            "location": ", ".join(loc_toks[:2]) if loc_toks else None,
            "result": result, "score": score, "links": _game_links(li, base_url),
        })
    return season, games


def parse_news(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/news/20\d\d/\d{1,2}/\d{1,2}/")):
        href = urljoin(base_url, a["href"])
        title = common.clean(a.get_text(" "))
        if not title or href in seen or len(title) < 8:
            continue
        m = re.search(r"/news/(\d{4})/(\d{1,2})/(\d{1,2})/", href)
        date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None
        seen.add(href)
        items.append({"title": title, "url": href, "date": date})
    return items


def parse_rss(xml_text: str, base_url: str) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    for it in root.iter("item"):
        title = common.clean(it.findtext("title") or "")
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        date = None
        if pub:
            try:
                date = parsedate_to_datetime(pub).date().isoformat()
            except (TypeError, ValueError):
                date = None
        if title and link:
            items.append({"title": title, "url": urljoin(base_url, link), "date": date})
    return items
