"""
Issue #387 step 1: a name-free probe of the athletics-wide staff directory.

Eight Sidearm programs publish players but no staff: their roster pages hold no staff markup, and their
/sports/<sport>/coaches pages are 404s (the #390 diagnostic lines). Every one of those roster pages links the site's
staff directory, `/staff-directory` or `/staff`. Before any parser is written for that page - which lists every
sport's staff with their contact details - this probe fetches it once and logs ONE line describing its structure.

What it may do (Huatuo's review and approval on #387, owner's OK 2026-09-30, about 8 requests a week):
  * C2 - fire only at the #390 point (players > 0, final staff list empty) and only on a run that fetches the head
    coach's bio (coach_bios: the weekly, full and onboard runs, never the daily ones); at most one probe per program
    per process; only a link the roster page itself carries, on the roster's host, with path exactly
    /staff-directory or /staff.
  * C1 - common.robots_allowed() (the strict check: unreachable or 5xx robots.txt = disallowed; Crawl-delay
    applied) BEFORE any request; refused -> `robots=0`, nothing sent, whatever COLLEGEDASH_ROBOTS says.
  * Build note - an off-host redirect is never REQUESTED: the page is fetched without following redirects
    (common.fetch_no_redirect); a 3xx is followed at most once, only to the same host and a directory path, and
    only after robots_allowed() says yes for that hop. Anything else is logged (`dir=offhost`, `dir=offpath`,
    `dir=redirects`) and nothing more is sent.
  * C3/C4 - the line holds integers, 0/1-style counts and fixed-vocabulary tokens only. Section labels are matched
    in code against fixed forms and logged only as class counts; column headers only as words of HEADER_WORDS (in
    that list's spelling) or `<x>`. No heading, label, cell or link text and no path from the page reaches it. The
    page is not cached, stored or returned. At most PROBE_MAX_HEADERS headers and PROBE_MAX_LEN characters.

The stored staff stays exactly as collect() built it: this module returns a log line and nothing else.
"""

from __future__ import annotations

import re
import threading
from urllib.parse import urljoin, urlparse

from . import common

DIR_PATHS = ("/staff-directory", "/staff")
HEADER_WORDS = ("name", "title", "position", "email", "phone", "bio", "photo", "department", "sport")
PROBE_MAX_HEADERS = 12
PROBE_MAX_LEN = 400
PREFIX = "  staff directory probe: "
MARKERS = ("tr-group", "caption", "h2", "h3", "h4", "div-heading")  # tie order for `marker`

# Section-label classes. A label is normalised (_norm_label) and must EQUAL one of these forms - never a substring -
# except `combined`, which is a heading naming both teams. The forms are written raw and normalised the same way.
_WSOC_FORMS = ("women's soccer", "womens soccer", "w. soccer", "wsoc", "soccer (w)", "soccer - women", "soccer women")
_MSOC_FORMS = ("men's soccer", "mens soccer", "m. soccer", "msoc", "soccer (m)", "soccer - men", "soccer men")
_LABEL_MAX = 80  # longer text is not a section label
_DIV_HEADING_CLASS = re.compile(r"head(?:ing|er)|title|group|category", re.I)

_probed: set[str] = set()
_probed_lock = threading.Lock()


def _norm_label(text: str) -> str:
    s = text.lower().replace("’", "'").replace("‘", "'")
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for suffix in (" coaching staff", " coaches", " staff"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
            break
    return s.strip("' ")


_WSOC = frozenset(_norm_label(f) for f in _WSOC_FORMS)
_MSOC = frozenset(_norm_label(f) for f in _MSOC_FORMS)
_WOMEN_TOKENS = frozenset(("women's", "womens", "women", "w", "wsoc"))
_MEN_TOKENS = frozenset(("men's", "mens", "men", "m", "msoc"))


def label_class(text: str) -> str | None:
    """'wsoc' | 'soccer' | 'msoc' | 'combined' | None for one section label. Exact matches only."""
    if len(text) > _LABEL_MAX:
        return None
    s = _norm_label(text)
    if s in _WSOC:
        return "wsoc"
    if s in _MSOC:
        return "msoc"
    if s == "soccer":
        return "soccer"
    tokens = set(s.split())
    if ("soccer" in tokens or tokens & {"wsoc", "msoc"}) and tokens & _WOMEN_TOKENS and tokens & _MEN_TOKENS:
        return "combined"
    return None


def header_word(text: str) -> str:
    """A column header as logged: exactly one of HEADER_WORDS (that list's own spelling), else '<x>'."""
    low = re.sub(r"\s+", " ", text).strip().rstrip(":").strip().lower()
    for word in HEADER_WORDS:
        if low == word:
            return word
    return "<x>"


def _host(netloc: str) -> str:
    return netloc.lower().removeprefix("www.")


def _is_dir_path(path: str) -> bool:
    return (path.rstrip("/") or "/").lower() in DIR_PATHS


def directory_link(html: str, base: str) -> str | None:
    """The first link on the roster page to the same host's /staff-directory or /staff, without query or fragment."""
    from bs4 import BeautifulSoup
    host = _host(urlparse(base).netloc)
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.lower().startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        u = urlparse(urljoin(base + "/", href))
        if u.scheme in ("http", "https") and _host(u.netloc) == host and _is_dir_path(u.path):
            return f"{u.scheme}://{u.netloc}{u.path}"
    return None


# ---------- reading the directory page (counts only) ----------

def _cells(tr) -> list:
    return tr.find_all(["td", "th"], recursive=False)


def _is_group_row(tr, wide: bool) -> bool:
    """A full-width group row: one cell, in a table that has wider rows (or the cell spans columns)."""
    cells = _cells(tr)
    if len(cells) != 1:
        return False
    try:
        span = int(cells[0].get("colspan") or 1)
    except ValueError:
        span = 1
    return span > 1 or wide


def _candidates(soup) -> list[tuple[str, object]]:
    """Every section-label element, in document order, with its marker kind."""
    group_rows = set()
    for t in soup.find_all("table"):
        wide = any(len(_cells(tr)) > 1 for tr in t.find_all("tr"))
        group_rows.update(id(tr) for tr in t.find_all("tr") if _is_group_row(tr, wide))
    out = []
    for el in soup.find_all(True):
        if el.name == "tr" and id(el) in group_rows:
            out.append(("tr-group", el))
        elif el.name in ("caption", "h2", "h3", "h4"):
            out.append((el.name, el))
        elif (el.name == "div" and any(_DIV_HEADING_CLASS.search(c) for c in (el.get("class") or []))
              and not el.find(["h2", "h3", "h4", "table", "div"]) and not el.find_parent(["h2", "h3", "h4"])):
            out.append(("div-heading", el))
    return out


def _header_row(rows) -> list | None:
    for tr in rows:
        cells = _cells(tr)
        if len(cells) > 1 and all(c.name == "th" for c in cells):
            return cells
    return None


def _section_table_rows(kind: str, el, same_kind: set[int]) -> tuple[list, list]:
    """(header cells, data rows) of the section `el` opens."""
    if kind == "tr-group":
        table = el.find_parent("table")
        trs = table.find_all("tr")
        after = trs[trs.index(el) + 1:]
        section = []
        for tr in after:
            if id(tr) in same_kind:
                break
            section.append(tr)
        head = _header_row(section) or _header_row(trs) or []
        return head, [tr for tr in section if tr.find("td")]
    if kind == "caption":
        table = el.find_parent("table")
    else:
        table = None
        for nxt in el.find_all_next(True):
            if id(nxt) in same_kind:
                break
            if nxt.name == "table":
                table = nxt
                break
    if table is None:
        return [], []
    trs = table.find_all("tr")
    return _header_row(trs) or [], [tr for tr in trs if tr.find("td")]


def analyse(html: str, base: str) -> dict:
    """The counts and tokens C3 logs, for one directory page. Nothing from the page is returned as text."""
    from bs4 import BeautifulSoup
    from .adapters.sidearm import is_head_coach
    soup = BeautifulSoup(html, "html.parser")
    for el in soup(["script", "style", "noscript", "template"]):
        el.extract()
    cands = _candidates(soup)
    classed = [(kind, el, label_class(el.get_text(" ", strip=True))) for kind, el in cands]
    counts = {c: sum(1 for _, _, k in classed if k == c) for c in ("wsoc", "soccer", "msoc", "combined")}
    pool = [kind for kind, _, k in classed if k] or [kind for kind, _ in cands]
    marker = max(MARKERS, key=lambda m: (pool.count(m), -MARKERS.index(m))) if pool else "none"
    out = {"tables": len(soup.find_all("table")), "marker": marker, **counts,
           "headers": [], "rows": 0, "headCoachRows": 0, "bioLinks": 0}
    if counts["wsoc"] != 1:
        return out
    kind, el = next((kind, el) for kind, el, k in classed if k == "wsoc")
    same_kind = {id(e) for k2, e in cands if k2 == kind}
    head, rows = _section_table_rows(kind, el, same_kind)
    words = [header_word(c.get_text(" ", strip=True)) for c in head]
    title_at = next((i for i, w in enumerate(words) if w in ("title", "position")), None)
    host = _host(urlparse(base).netloc)

    def head_coach(tr) -> bool:
        cells = _cells(tr)
        if title_at is not None:
            return title_at < len(cells) and is_head_coach(cells[title_at].get_text(" ", strip=True))
        return any(is_head_coach(c.get_text(" ", strip=True)) for c in cells)

    def bio_link(tr) -> bool:
        for a in tr.find_all("a", href=True):
            u = urlparse(urljoin(base + "/", a["href"].strip()))
            if _host(u.netloc) == host and u.path.lower().startswith("/staff-directory/"):
                return True
        return False

    out.update(headers=words, rows=len(rows), headCoachRows=sum(1 for tr in rows if head_coach(tr)),
               bioLinks=sum(1 for tr in rows if bio_link(tr)))
    return out


def format_line(robots: str, dir_: str, status: int | None = None, a: dict | None = None) -> str:
    head = f"{PREFIX}robots={robots} dir={dir_}" + (f" status={status}" if status is not None else "")
    if a is None:
        return head[:PROBE_MAX_LEN]
    body = (f" tables={a['tables']} marker={a['marker']} wsoc={a['wsoc']} soccer={a['soccer']} msoc={a['msoc']} "
            f"combined={a['combined']} rows={a['rows']} headCoachRows={a['headCoachRows']} bioLinks={a['bioLinks']}")
    words = list(a["headers"])
    shown = words[:PROBE_MAX_HEADERS]

    def line(ws):
        more = len(words) - len(ws)
        return head + body + f" headers=[{', '.join(ws)}]" + (f" +{more} more" if more else "")
    out = line(shown)
    while len(out) > PROBE_MAX_LEN and shown:
        shown = shown[:-1]
        out = line(shown)
    return out[:PROBE_MAX_LEN]


# ---------- the probe ----------

def probe(html: str, base: str) -> str:
    """One name-free line about the staff directory the roster page links. At most two requests: the directory, and
    one same-host redirect hop to a directory path; neither is made unless robots_allowed() says yes for its URL."""
    url = directory_link(html, base)
    if not url:
        return format_line("-", "none")
    if not common.robots_allowed(url):
        return format_line("0", "skipped")
    try:
        with common.fetch_site("athletics.staffDirectoryProbe"):
            status, location, text = common.fetch_no_redirect(url)
            if location is not None:
                hop = urlparse(urljoin(url, location))
                if hop.scheme not in ("http", "https") or _host(hop.netloc) != _host(urlparse(url).netloc):
                    return format_line("1", "offhost", status)  # nothing is sent to the other host
                hop_url = f"{hop.scheme}://{hop.netloc}{hop.path}" + (f"?{hop.query}" if hop.query else "")
                if not _is_dir_path(hop.path):
                    return format_line("1", "offpath", status)
                if hop_url == url:
                    return format_line("1", "redirects", status)
                if not common.robots_allowed(hop_url):
                    return format_line("0", "skipped", status)
                status, location, text = common.fetch_no_redirect(hop_url)
                if location is not None:
                    return format_line("1", "redirects", status)
    except common.FetchError as e:
        return format_line("1", "error", getattr(e, "status", None))
    if status != 200:
        return format_line("1", "error", status)
    return format_line("1", "ok", status, analyse(text, base))


def probe_once(slug: str, html: str, base: str) -> str | None:
    """probe() for a program not yet probed in this process; None (nothing sent) for one that was."""
    with _probed_lock:
        if slug in _probed:
            return None
        _probed.add(slug)
    return probe(html, base)
