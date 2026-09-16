"""
The head coach's first season at this program, read from the coach's own bio page on the athletics site
(issue #168, part 2).

`first_season(html, name)` returns {"firstSeason": int | None, "statements": [...], "conflict": bool}.
Every statement it reads is kept with the sentence it came from, so a published year can be checked
against its source and a disagreement can be shown rather than argued about.

Only these phrasings are read, and nothing looser (a wrong year is worse than none):

  hired     "<Surname> was named|hired|appointed|announced ... head coach ... [on|in] <Month> [<day>,] [of] <YYYY>",
            "... announced on <Month> <day>, <YYYY> as the ... head coach", and "head ... coach ... after being
            named to the position on <Month> <day>, <YYYY>". A hire date becomes a first season by month:
            November and December hires start the next fall, January to July the same fall, and an
            August-October hire (the season is under way) gives no year.
  start     a "Start Date: MM/DD/YYYY" field, by the same month rule.
  present   "Head Coach, <School> - <YYYY>-Present" in the page's experience list, and "<Surname> has
            helmed ... (<YYYY>-present)".
  first     "In <YYYY>, <Surname>'s first season".
  count     "<Surname> enters|begins|will begin ... his|her <Nth> season|year ... <YYYY>", "<YYYY> will mark
            <Surname>'s <Nth> year", and the "Through <YYYY> Season / <Nth> Season" header: YYYY - N + 1.
  since     "<Surname> ... at the helm|head coach|leading the X ... since <YYYY>".
  tookover  "<Surname> ... took over ... before|ahead of|in front of|prior to the <YYYY> season".
  interim   "interim head coach during|in|for the <YYYY> season" and "co-head coach in <YYYY>" in a sentence
            naming the coach: the owner ruled that an interim or co-head season is a first season.

The statements must agree. They may differ only where an interim or co-head season comes first and a
later appointment to the permanent job is dated after it (northern-iowa: interim for 2025, named in
November 2025). Any other disagreement publishes nothing and sets `conflict` - radford's page says both
"at the helm since 1996" and "Through 2025 Season / 31st Season", which is 1995.

A sentence must carry the coach's surname to be read, so a bio's related stories and sidebars about other
people are not. The two exceptions are fields that can only be the page's own subject: "Start Date:" and
the "Through <YYYY> Season" header, and a "Head Coach ... <YYYY>-Present" line. A count that describes the
program ("as the program enters its 31st season in 2026") is not the coach's and is not read.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from . import common

_MON = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|"
        r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_ORDINALS = {w: i + 1 for i, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth "
    "sixteenth seventeenth eighteenth nineteenth twentieth".split())}
_NTH = r"(?:(\d{1,2})(?:st|nd|rd|th)|(" + "|".join(_ORDINALS) + r"))"
YEAR = r"((?:19|20)\d\d)"
_HEAD = r"head\s+(?:women['’]?s\s+)?(?:soccer\s+)?coach"
_DAY = r"\d{1,2}(?:st|nd|rd|th)?"
# the season a count is counted in: "in 2026", "into the 2026 season", "for the 2025 fall season", "in the fall of 2026"
_SEASON_OF = rf"(?:in|into|for|during|entering|heading\s+into)\s+(?:the\s+)?(?:(?:fall|spring)\s+of\s+(?:the\s+)?)?{YEAR}\b"
# Not "form": Sidearm's older theme wraps the whole page, bio included, in <form id="aspnetForm">.
_STRIP_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "aside", "svg", "iframe", "template")
_STRIP_TOKEN_RE = re.compile(r"(?:^|[-_])(?:nav|navigation|menu|footer|sidebar|related|share|social|ticker|scoreboard|"
                             r"breadcrumbs?)(?:$|[-_])", re.I)
_ABBREV_RE = re.compile(r"\b(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|St|Mt|Dr|Mr|Mrs|Ms|Jr|Sr|No|vs)\.", re.I)
_CONTACT_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|(?<!\d)(?:\(?\d{3}\)?[-. ]?)?\d{3}[-. ]\d{4}(?!\d)")
_NOT_HEAD_RE = re.compile(r"\b(?:assistant|associate|assoc\.?|volunteer)\s+(?:head\s+)?(?:\w+\s+){0,2}coach\b", re.I)


def season_from_hire(month: int, year: int) -> int | None:
    """The first fall season for a hire in `month` of `year`: Nov-Dec -> next year, Jan-Jul -> same year,
    Aug-Oct -> None (the season is already under way, so the date does not say which season is first)."""
    if month in (11, 12):
        return year + 1
    if 1 <= month <= 7:
        return year
    return None


def _month(token: str | None) -> int | None:
    t = (token or "").lower()[:3]
    return _MONTHS.index(t) + 1 if t in _MONTHS else None


def _ordinal(digits: str | None, word: str | None) -> int | None:
    if digits:
        return int(digits)
    return _ORDINALS.get(word.lower()) if word else None


def bio_text(html: str) -> str:
    """The page's readable text, one line per text block, with navigation, chrome and related blocks removed."""
    soup = BeautifulSoup(html or "", "html.parser")
    for t in soup(_STRIP_TAGS):
        t.decompose()
    for t in soup.find_all(True):
        if t.decomposed or t.name in ("html", "body", "main"):
            continue
        if any(_STRIP_TOKEN_RE.search(tok) for tok in (t.get("class") or []) + [t.get("id") or ""]):
            t.decompose()
    lines = (common.clean(line) for line in soup.get_text("\n").split("\n"))
    return "\n".join(line for line in lines if line)


def sentences(text: str) -> list[str]:
    """Sentences within each line; 'Dec. 20' and 'St. John' do not end one."""
    out = []
    for line in text.split("\n"):
        protected = _ABBREV_RE.sub(lambda m: m.group(1) + "․", line)
        out += [p.replace("․", ".") for p in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])", protected) if p.strip()]
    return out


# "Before coming to WIU:" / "Prior to joining the Hawkeyes:" heads a section about earlier jobs.
_EARLIER_JOB_HEADING_RE = re.compile(r"^(?:Before|Prior\s+to)\s+(?:coming|joining|arriving|taking)\b[^.]{0,50}$", re.I)


def _sentences_with_sections(text: str):
    """(sentence, in_earlier_job_section) for every sentence. A short heading line such as "Before coming to
    WIU:" opens a section about earlier jobs; the next short heading line ending in ':' closes it."""
    earlier = False
    for line in text.split("\n"):
        if len(line) <= 70 and _EARLIER_JOB_HEADING_RE.match(line):
            earlier = True
            continue
        if len(line) <= 60 and line.endswith(":"):
            earlier = False
        for s in sentences(line):
            yield s, earlier


def _surname(name: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'’-]*", name or "") if w.lower().strip(".") not in ("jr", "sr", "ii", "iii", "iv")]
    return words[-1] if words else ""


def statements(html: str, name: str, school=()) -> list[dict]:
    """Every start-of-tenure statement on the page as {kind, year, text, school}. `year` is the first season
    it implies; a hire dated August-October is kept with year None, since it says nothing either way.
    `school` (the result field) is own/other/unknown against the program's names given in `school`, judged
    on the whole sentence before it is clipped for storage."""
    surname = _surname(name)
    if not surname:
        return []
    sur = re.escape(surname)
    tokens, names = school_tokens(school), [_norm(n) for n in school or () if n]
    text = bio_text(html)
    out: list[dict] = []

    earlier_job = False  # inside a "Before coming to WIU:" section

    def add(kind: str, year: int | None, sentence: str) -> None:
        clipped = _CONTACT_RE.sub("[removed]", common.clean(sentence))[:240]
        school_of = "other" if earlier_job and tokens else _school_of(sentence, tokens, names)
        if not any(o["kind"] == kind and o["year"] == year and o["school"] == school_of for o in out):
            out.append({"kind": kind, "year": year, "text": clipped, "school": school_of})

    def hire(month_token: str | None, year: str, sentence: str) -> None:
        # an announcement can name a later start: "announced Hall will be the third ... head coach beginning in
        # 2025" (dated July 22, 2024), "named ... head coach for the Bears, effective January 1, 2022"
        begins = re.search(r"\b(?:beginning|starting)\s+(?:in|with)\s+(?:the\s+)?((?:19|20)\d\d)\b", sentence, re.I)
        if begins:
            add("hired", int(begins.group(1)), sentence)
            return
        effective = re.search(rf"\beffective\s+({_MON})\.?\s+{_DAY},?\s+((?:19|20)\d\d)\b", sentence, re.I)
        if effective:
            month_token, year = effective.group(1), effective.group(2)
        month = _month(month_token)
        if month:
            add("hired", season_from_hire(month, int(year)), sentence)

    for m in re.finditer(r"\bStart\s+Date\s*:?\s*(\d{1,2})/\d{1,2}/((?:19|20)\d\d)\b", text, re.I):
        add("start", season_from_hire(int(m.group(1)), int(m.group(2))), m.group(0))
    for m in re.finditer(rf"\bThrough\s+{YEAR}\s+Season\s*/\s*{_NTH}\s+Season\b", text, re.I):
        n = _ordinal(m.group(2), m.group(3))
        if n:
            add("count", int(m.group(1)) - n + 1, m.group(0))

    for s, earlier_job in _sentences_with_sections(text):
        for m in re.finditer(rf"\b{_HEAD}\b[^.]{{0,40}}?(?:\b({_MON})\.?\s+\d{{1,2}},?\s+)?\b{YEAR}\s*[-–—]\s*present\b", s, re.I):
            if not _NOT_HEAD_RE.search(s[max(0, m.start() - 25):m.end()]):
                month = _month(m.group(1))  # "Florida Head Coach (December 5, 2025-present)" is a hire date
                add("present", season_from_hire(month, int(m.group(2))) if month else int(m.group(2)), s)
        if not re.search(rf"\b{sur}\b", s, re.I):
            continue
        for m in re.finditer(rf"\b(?:named|hired|appointed|announced|introduced|became|tabbed|joined|promoted|elevated)\b[^.]{{0,200}}?\b{_HEAD}\b[^.]{{0,160}}?"
                             rf"\b(?:on\s+|in\s+(?:the\s+)?)?({_MON})\.?\s+(?:{_DAY},?\s+)?(?:of\s+)?{YEAR}\b", s, re.I):
            if not _NOT_HEAD_RE.search(m.group(0)):
                hire(m.group(1), m.group(2), s)
        for m in re.finditer(rf"\b(?:named|hired|appointed|announced|introduced)\b[^.]{{0,100}}?\b(?:on\s+)?({_MON})\.?\s+{_DAY},?\s+{YEAR}\b"
                             rf"[^.]{{0,60}}?\bas\b[^.]{{0,40}}?\b{_HEAD}\b", s, re.I):
            if not _NOT_HEAD_RE.search(m.group(0)):
                hire(m.group(1), m.group(2), s)
        for m in re.finditer(rf"\bnamed\s+to\s+(?:the|his|her)\s+position\s+on\s+({_MON})\.?\s+{_DAY},?\s+{YEAR}\b", s, re.I):
            if re.search(rf"\b{_HEAD}\b", s, re.I) and not _NOT_HEAD_RE.search(s):
                hire(m.group(1), m.group(2), s)
        # "On Wednesday, February 16, 2022, the University at Albany announced the hiring of Sade Ayinde as the next head coach"
        for m in re.finditer(rf"^On\s+(?:[A-Z][a-z]+day,?\s+)?({_MON})\.?\s+{_DAY},?\s+{YEAR},?\s+[^.]{{0,120}}?"
                             rf"\b(?:named|hired|hiring|appointed|announced)\b[^.]{{0,120}}?\b{_HEAD}\b", s, re.I):
            if not _NOT_HEAD_RE.search(m.group(0)):
                hire(m.group(1), m.group(2), s)
        # "after taking over the program in April of 2015"; "took over the Purple Aces women's soccer program ... in December of 2019"
        for m in re.finditer(rf"\b(?:taking|took)\s+over\s+(?:the\s+)?[^.]{{0,60}}?\bprogram\b[^.]{{0,40}}?\bin\s+({_MON})\s+(?:of\s+)?{YEAR}\b", s, re.I):
            hire(m.group(1), m.group(2), s)
        for m in re.finditer(rf"\b{sur}\b[^.]{{0,60}}?\b(?:helm|helmed|led)\b[^.]{{0,60}}?\(\s*{YEAR}\s*[-–—]\s*present\s*\)", s, re.I):
            add("present", int(m.group(1)), s)
        for m in re.finditer(rf"\bIn\s+{YEAR},\s+{sur}['’]s\s+first\s+season\b", s, re.I):
            add("first", int(m.group(1)), s)
        # the year must be the season being entered ("in 2026", "in the fall of 2026", "heading into the 2026
        # campaign"), not a past season mentioned after it ("after guiding the Redbirds to new heights in 2025")
        for m in re.finditer(rf"\b{sur}\b[^.]{{0,40}}?\b(?:enters|begins|will\s+begin|will\s+enter|heads\s+into|is\s+entering|embarks\s+on)\s+"
                             rf"(?:his|her|their)\s+{_NTH}\s+(?:season|year)\b([^.]{{0,80}}?)\b{_SEASON_OF}", s, re.I):
            n = _ordinal(m.group(1), m.group(2))
            if n and not re.search(r"\b(?:after|following|since|previous)\b", m.group(3), re.I):
                add("count", int(m.group(4)) - n + 1, s)
        # "Entering his seventh season in 2026, Matt Fannon ..."; "will enter the 2026 campaign at the helm ... for his 10th season"
        for m in re.finditer(rf"^Entering\s+(?:his|her|their)\s+{_NTH}\s+season\s+{_SEASON_OF},\s+[^.]{{0,40}}?\b{sur}\b", s, re.I):
            n = _ordinal(m.group(1), m.group(2))
            if n:
                add("count", int(m.group(3)) - n + 1, s)
        for m in re.finditer(rf"\b{sur}\b\s+will\s+enter\s+the\s+{YEAR}\s+(?:season|campaign)\b[^.]{{0,80}}?\bfor\s+(?:his|her|their)\s+{_NTH}\s+season\b", s, re.I):
            n = _ordinal(m.group(2), m.group(3))
            if n:
                add("count", int(m.group(1)) - n + 1, s)
        # "Head coach Neil McGuire completed his 19th season with the Bears in 2025."
        for m in re.finditer(rf"\b{sur}\b\s+(?:completed|concluded|finished)\s+(?:his|her|their)\s+{_NTH}\s+season\b[^.]{{0,60}}?\bin\s+{YEAR}\b", s, re.I):
            n = _ordinal(m.group(1), m.group(2))
            if n:
                add("count", int(m.group(3)) - n + 1, s)
        for m in re.finditer(rf"\b{YEAR}\b[^.]{{0,120}}?\bwill\s+mark\s+{sur}['’]s\s+{_NTH}\s+(?:season|year)\b", s, re.I):
            n = _ordinal(m.group(2), m.group(3))
            if n:
                add("count", int(m.group(1)) - n + 1, s)
        for m in re.finditer(rf"\b{sur}\b[^.]{{0,80}}?\b(?:at\s+the\s+helm|head\s+coach|leading\s+the\s+\w+|has\s+led\s+the\s+\w+)\s+since\s+{YEAR}\b", s, re.I):
            if not _NOT_HEAD_RE.search(m.group(0)):
                add("since", int(m.group(1)), s)
        for m in re.finditer(rf"\b{sur}\b[^.]{{0,80}}?\btook\s+over\b[^.]{{0,80}}?\b(?:before|ahead\s+of|in\s+front\s+of|prior\s+to)\s+the\s+{YEAR}\s+season\b", s, re.I):
            add("tookover", int(m.group(1)), s)
        for m in re.finditer(rf"\binterim\s+head\s+coach\b[^.]{{0,40}}?\b(?:during|in|for|midway\s+through|partway\s+through)\s+the\s+{YEAR}\s+season\b"
                             rf"|\bco-head\s+coach\s+in\s+{YEAR}\b", s, re.I):
            add("interim", int(m.group(1) or m.group(2)), s)
    return out


# ---------- this school's job, or a previous one ----------
# A coach's bio narrates earlier jobs in the same words: florida-state's page says Pensky "was named head
# soccer coach at the University of Tennessee on Jan. 26, 2012", boston-college's that Watkins was "Named
# the head coach of Gonzaga women's soccer in December 2016", cal-poly's that Silva "took over as head
# coach at Cal State Bakersfield prior to the 2023 season". So each statement is marked by the school it
# names: "own" when it names this school (a distinctive word of its name, short name, nickname or athletics
# site), "other" when it names an institution and not this one, and "unknown" when it names none.
_INSTITUTION_RE = re.compile(
    r"\bUniversity\s+of\s+(?:[A-Z][\w.&'’-]*\s*){1,4}|(?:\b[A-Z][\w.&'’-]*\s+){1,4}(?:University|College|State)\b")
# Acronyms that name no school: "at CSU" in a bio is another institution, "in the SEC" is not.
_ORG_ACRONYMS = {"ncaa", "naia", "njcaa", "sec", "acc", "aac", "wcc", "mac", "caa", "asun", "mvc", "ovc", "swac", "meac", "wac",
                 "nec", "uac", "cusa", "usa", "us", "nwsl", "mls", "usl", "wps", "odp", "ecnl", "usys", "ussf", "fifa", "uefa",
                 "mvp", "ga", "da", "gk", "phd", "ma", "ms", "mba", "bs", "ba", "id", "tv"}
# only "at <ACRONYM>": "for the DU women's soccer team" is this school's team, "at CSU" is a place of work
_ACRONYM_AT_RE = re.compile(r"\bat\s+(?:the\s+)?([A-Z]{2,6})\b")
_SCHOOL_NOISE = {"university", "college", "state", "the", "of", "at", "and", "saint", "athletics", "women", "womens",
                 "soccer", "north", "south", "east", "west", "northern", "southern", "eastern", "western", "central",
                 "sports", "official", "site", "go"}


def school_tokens(names) -> set[str]:
    """Distinctive lower-case words of the school's names (registry name, short name, nickname, site label)."""
    tokens = set()
    for n in names or ():
        words = re.findall(r"[A-Za-z][A-Za-z&'’-]*", n or "")
        for w in words:
            if re.fullmatch(r"[A-Z]{2,6}", w):
                tokens.add(w.lower())  # an acronym the school goes by: LSU, UCF, FDU
            w = re.sub(r"[^a-z]", "", w.lower())
            if len(w) >= 4 and w not in _SCHOOL_NOISE:  # not "cal": Cal Poly's token would name Cal State Bakersfield
                tokens.add(w)
        caps = [w for w in words if w[0].isupper() and w.lower() not in ("of", "the", "at", "and")]
        if len(caps) >= 2:
            tokens.add("".join(w[0] for w in caps).lower())  # Louisiana State University -> lsu
    return tokens


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).split())


_GENERIC = {"university", "college", "of", "the", "at", "and"}


def _core(s: str) -> frozenset:
    """An institution's name without its generic words, "State" kept: University of Florida -> {florida},
    Florida State University -> {florida, state}, so the two never match each other."""
    return frozenset(w for w in _norm(s).split() if w not in _GENERIC)


def _school_of(sentence: str, tokens: set[str], names: list[str]) -> str:
    """own / other / unknown (see the note above). A sentence that names an institution ("University of
    Florida", "Cal State Bakersfield", "Boston College") is judged by that name alone: it is this school only
    if it contains one of this school's names of two words or more, or is contained in one. Shared words are
    not enough - "Florida State" is not the University of Florida, nor "Iowa State" the University of Iowa.
    A sentence that names no institution is this school's when it uses one of its distinctive words
    ("the UNI women's soccer program", "Cal Poly women's soccer")."""
    if not tokens:
        return "unknown"
    flat = f" {_norm(sentence)} "
    if any(f" {n} " in flat for n in names if len(n.split()) >= 2):
        return "own"  # "at Boston College", "the University of Delaware named", "App State women's soccer"
    cores = {_core(n) for n in names} - {frozenset()}
    if any(_core(m.group(0)) in cores for m in _INSTITUTION_RE.finditer(sentence)):
        return "own"  # "Indiana University Vice President ...": the institution named IS this school's short name
    outside = _INSTITUTION_RE.sub(" ", sentence)  # words that are not part of a named institution
    if tokens & set(re.findall(r"[a-z]+", outside.lower())):
        return "own"  # "named Brown's head women's soccer coach", beside "Northeastern University and Boston College"
    if _INSTITUTION_RE.search(sentence):
        return "other"
    if any(m.group(1).lower() not in _ORG_ACRONYMS for m in _ACRONYM_AT_RE.finditer(sentence)):
        return "other"  # "named the sixth head women's soccer coach at CSU": another school's acronym
    return "unknown"


def _agreeing_year(years: list[dict]) -> int | None:
    """The one first season these statements agree on, or None. An interim or co-head season may precede
    a later-dated appointment to the permanent job; nothing else may differ."""
    if not years:
        return None
    earliest = min(s["year"] for s in years)
    interim = [s["year"] for s in years if s["kind"] == "interim"]
    if interim and min(interim) == earliest:
        agree = all(s["year"] == earliest or (s["kind"] in ("hired", "start", "present") and s["year"] > earliest) for s in years)
    else:
        agree = len({s["year"] for s in years}) == 1
    return earliest if agree else None


def first_season(html: str, name: str, school=()) -> dict:
    """{"firstSeason", "statements", "conflict"} for coach `name` from their bio page (see the module note).

    `school` is the program's names (registry name, short name, nickname, athletics site label). A statement
    that names another institution and not this one is about a previous job and is not used. When what is
    left disagrees and some appointment names this school, appointments that name no school are set aside
    (boston-college: "named the new head women's soccer coach at Boston College on Dec. 14, 2023" against
    "Named the head coach of Gonzaga women's soccer in December 2016"); if the rest agree, that is the year.
    Season counts and fields are never set aside, so a page whose count and appointment disagree (miami-fl)
    still publishes nothing."""
    found = statements(html, name, school)
    years = [s for s in found if s["year"] is not None and s["school"] != "other"]
    if not years:
        return {"firstSeason": None, "statements": found, "conflict": False}
    year = _agreeing_year(years)
    if year is None and any(s["school"] == "own" and s["kind"] == "hired" for s in years):
        year = _agreeing_year([s for s in years if s["kind"] != "hired" or s["school"] == "own"])
    return {"firstSeason": year, "statements": found, "conflict": year is None}
