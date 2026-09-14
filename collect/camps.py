"""
ID camps and clinics: the program's camp page, found from the athletics site's navigation (one hop
through an all-sports camps hub when the link is generic), plus camps announced in news releases.

Writes programs/<slug>/sources/camps.json:
  { campsUrl, discoveredVia: registry|anchor|json|null, hubUrl, finalUrl, host, vendor, pageTitle,
    robotsBlocked, fetchError, camps[], newsCamps[], newsScanned }
  camps[] / newsCamps[] entries: { name, startDate, endDate, dateText, precision: day|month|null,
    yearInferred, location, ages, price, registerUrl, sourceUrl, confidence: "heuristic",
    newsTitle, newsUrl, newsDate (news only) }

Discovery order: registry `athletics.campsUrl` wins (no nav parsing); then `skipReason` skips the
program; then the roster page (server-rendered nav even on browser-rendered rosters) is scanned:
anchors first, then flat JSON nav objects (Sidearm "additional-links"). Hosts outside the athletics
site are checked against robots.txt before and after the request (see common.robots_allowed); a
denied host is shown as a link only. Camp entries are heuristic: a table whose header names a date
and a camp/clinic/event column, or a text line naming a camp with a full date. Registration dates
and "TBD" never become camps. At most MAX_CAMPS per page, applied after the gating below.

Row-level gating (issue #39; 119 of 250 stored rows were not camps at that program):
  - review and testimonial containers are stripped with navigation and chrome, because a review
    card's post date otherwise becomes a camp (36 rows on two US Sports Camps pages);
  - on an all-sport camps hub, rows are gated by the sport-section heading above them - the rows
    themselves carry no sport, and wofford's men's and women's rows are all called "ID Camp". A page
    with no sport headings, which is most of them, is parsed exactly as before;
  - a row that names another sport or another gender ITSELF is dropped anywhere;
  - a registerUrl whose host names another sport is dropped from the row, not with it: a hub has one
    registration block for the whole department, and one of those 50 links sits on a real camp;
  - one camp emitted as several overlapping rows collapses into one spanning row;
  - a name that is page chrome ("Camp Dates") is repaired from the page title, never rejected -
    portland's and california's chrome-named rows are real camps.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import adapters, common

NAME = "camps"
MAX_CAMPS = 20

# ---------- link scoring ----------
CAMP_RE = re.compile(r"\b(?:camps?|clinics?)\b", re.I)
CAMP_LOOSE_RE = re.compile(r"(?:camps?|clinics?)(?![a-z])", re.I)  # hosts/paths: vandysoccercamps.com, /girls-soccer-camps; not /jamie-campbell
NOT_CAMP_RE = re.compile(r"campus|campaign", re.I)            # 'Campus Map', utm_campaign
FEMALE_RE = re.compile(r"\b(?:women|girls?|female|ladies)(?:'s|’s|s)?\b", re.I)
MALE_RE = re.compile(r"\b(?:men|boys?)(?:'s|’s|s)?\b", re.I)
FEMALE_LOOSE_RE = re.compile(r"women|girls?|female|ladies|(?<![a-z])wsoc", re.I)                       # hosts/paths: /sports/wsoc/camps
MALE_LOOSE_RE = re.compile(r"(?<!wo)mens?(?:-|/|$|%27s|'s)|boys?|(?<![a-z])msoc|mens-soccer", re.I)   # /sports/msoc/camps
SOCCER_RE = re.compile(r"soccer|wsoc|futbol", re.I)
OTHER_SPORT_RE = re.compile(
    r"\b(?:baseball|basketball|football|golf|lacrosse|tennis|volleyball|softball|swim(?:ming)?|dive|diving|track|"
    r"cross[ -]country|wrestling|gymnastics|hockey|rowing|crew|cheer(?:leading)?|dance|fencing|squash|water[ -]polo|"
    r"bowling|rifle|ski(?:ing)?|equestrian|sailing|running|spirit|esports|fantasy)\b", re.I)
OTHER_SPORT_LOOSE_RE = re.compile(
    r"baseball|basketball|football|golf|lacrosse|tennis|volleyball|softball|swim|wrestling|gymnastics|hockey|rowing|"
    r"cheer|fencing|water-?polo|bowling|rifle|equestrian|esports|runningcamp", re.I)
ID_RE = re.compile(r"\bID\b")
SKIP_HREF_RE = re.compile(r"^(?:#|javascript:|mailto:|tel:|sms:)|^$", re.I)
HTTP_URL_RE = re.compile(r"^https?://", re.I)
NOT_CAMP_PAGE_RE = re.compile(r"/roster|/schedule|/news/|/stats|/coaches/|/staff|/archives|/tickets|/donate|/promotions/|"
                              r"adhandler|/click\?|redirect=|facebook\.com|twitter\.com|x\.com|instagram\.com|youtube\.com|tiktok\.com", re.I)
HUB_PATH_RE = re.compile(r"/sports/\d{4}/\d{1,2}/\d{1,2}/", re.I)
# Class/id tokens that mark navigation, chrome and sidebars (stripped before scanning a page's content).
# A token is kept when it is clearly content ('c-article__header', Weebly's 'wsite-not-footer').
STRIP_TOKEN_RE = re.compile(r"(?:^|[-_])(?:nav|navigation|menu|footer|header|masthead|breadcrumbs?|sidebar|ticker|scoreboard|related|share|social)(?:$|[-_])", re.I)
KEEP_TOKEN_RE = re.compile(r"not-|no-|has-|with|article|story|post|entry|content|section|card|table|modal|accordion|heading|title|text|paragraph|body|item|link", re.I)
# Reviews and testimonials, stripped unconditionally: a review card carries a reviewer, a post date
# and prose about a camp, which is indistinguishable from a camp listing once it reaches _lines.
# US Sports Camps pages ('This camp currently has no active sessions') are entirely review widgets
# below the fold, and every pre-2026 single-day row there was a review post date for someone else's
# camp. Checked BEFORE KEEP_TOKEN_RE, which would otherwise rescue 'rd-google-review-card' on
# 'card' and 'rd-google-reviews__slider-item' on 'item'. Anchored on -/_ so 'preview' is not caught.
REVIEW_TOKEN_RE = re.compile(r"(?:^|[-_])(?:reviews?|testimonials?|ratings?)(?:$|[-_])", re.I)
REGISTER_PORTAL_RE = re.compile(r"campdoc\.com|forms\.gle|docs\.google\.com|/login|/checkout|/cart\b|corsizio|jotform|typeform", re.I)

VENDOR_HOSTS = [("totalcamps.com", "totalcamps"), ("ryzer.com", "ryzer"), ("active.com", "active"), ("teampages.com", "active"),
                ("campnetwork.com", "campnetwork"), ("ussportscamps.com", "ussportscamps"), ("campdoc.com", "campdoc"),
                ("myshopify.com", "shopify"), ("sportscampconnection.com", "sportscampconnection"), ("ryzerregister.com", "ryzer")]
VENDOR_MARKERS = [("cdn.shopify.com", "shopify"), ("weebly.com", "weebly"), ("wsite-", "weebly"), ("squarespace", "squarespace"),
                  ("totalcamps", "totalcamps"), ("ryzer", "ryzer"), ("wixstatic", "wix"), ("firewoodcamps", "firewood")]


def _host(url: str) -> str:
    return (urlparse(url).netloc or "").lower()


def _same_site(url: str, base_host: str) -> bool:
    h, b = _host(url), (base_host or "").lower()
    return re.sub(r"^www\.", "", h) == re.sub(r"^www\.", "", b) if h and b else False


def _http_url(href: str | None, base_url: str | None = None) -> str | None:
    """`href` resolved against `base_url`, or None unless the result is an http(s) URL. Every URL the
    collector emits passes through here: camp pages are third-party content, so a `javascript:` or
    `data:` href (with or without leading whitespace or odd casing) must never reach an href in the
    UI. Protocol-relative `//host/x` takes the page's scheme."""
    href = (href or "").strip()
    if not href or SKIP_HREF_RE.match(href):
        return None
    try:
        url = urljoin(base_url, href) if base_url else href
    except ValueError:
        return None
    return HTTP_URL_RE.sub(lambda m: m.group(0).lower(), url) if HTTP_URL_RE.match(url) else None


def _link_score(text: str, href: str) -> dict | None:
    """Score an anchor/nav item as a camps link; None when it is not one (no camp word, another
    sport). text = visible label + title + aria-label; href = resolved URL."""
    t = NOT_CAMP_RE.sub(" ", common.clean(text))
    h = NOT_CAMP_RE.sub(" ", href or "")
    camp_text, camp_href = bool(CAMP_RE.search(t)), bool(CAMP_LOOSE_RE.search(h))
    if not (camp_text or camp_href):
        return None
    female = bool(FEMALE_RE.search(t) or FEMALE_LOOSE_RE.search(h))
    male = bool(MALE_RE.search(t) or MALE_LOOSE_RE.search(h)) and not female
    soccer = bool(SOCCER_RE.search(t) or SOCCER_RE.search(h))
    if (OTHER_SPORT_RE.search(t) or OTHER_SPORT_LOOSE_RE.search(h)) and not soccer:
        return None
    score = 2 if camp_text else 1
    if female:
        score += 3
    if soccer:
        score += 2
    if ID_RE.search(text or ""):
        score += 1
    return {"score": score, "female": female, "male": male, "soccer": soccer}


def _pick(cands: list[dict]) -> dict | None:
    if not cands:
        return None
    if any(not c["male"] for c in cands):  # a men's/boys' link only when nothing else qualifies
        cands = [c for c in cands if not c["male"]]
    return max(cands, key=lambda c: (c["score"], -c["order"]))


def _anchor_candidates(soup, base_url: str, exclude: set[str]) -> list[dict]:
    out, seen = [], set()
    for i, a in enumerate(soup.find_all("a", href=True)):
        url = _http_url(a.get("href"), base_url)
        if not url or url.split("#")[0] in exclude or url in seen or NOT_CAMP_PAGE_RE.search(url):
            continue
        text = " ".join(filter(None, [a.get_text(" ", strip=True), a.get("title"), a.get("aria-label")]))
        text = re.sub(r"opens in a new (?:window|tab)", "", text, flags=re.I)
        sc = _link_score(text, url)
        if sc:
            seen.add(url)
            out.append({**sc, "url": url, "text": common.clean(text)[:120], "order": i})
    return out


_JSON_URL_RE = re.compile(r'"url"\s*:\s*"((?:[^"\\]|\\.)+)"')
_JSON_TITLE_RE = re.compile(r'"(?:title|short_title|label|name|text)"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _json_unescape(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except ValueError:
        return s


def _json_candidates(html: str, base_url: str, exclude: set[str]) -> list[dict]:
    """Flat JSON nav objects embedded in the page (Sidearm 'additional-links': "title" and "url" are
    not adjacent, so each "url" is paired with the nearest "title" inside the same object)."""
    out, seen = [], set()
    for i, m in enumerate(_JSON_URL_RE.finditer(html)):
        href = _json_unescape(m.group(1))
        if href.startswith("{"):
            continue
        start = html.rfind("{", max(0, m.start() - 400), m.start())
        if start < 0:
            continue
        seg = html[start:m.start()]
        tail = html[m.end():m.end() + 300]
        cut = min([p for p in (tail.find("{"), tail.find("}")) if p >= 0] or [len(tail)])
        seg += tail[:cut]
        tm = _JSON_TITLE_RE.search(seg)
        title = _json_unescape(tm.group(1)) if tm else ""
        url = _http_url(href, base_url)
        if not url or url.split("#")[0] in exclude or url in seen or NOT_CAMP_PAGE_RE.search(url):
            continue
        sc = _link_score(title, url)
        if sc:
            seen.add(url)
            out.append({**sc, "url": url, "text": common.clean(title)[:120], "order": i})
    return out


def find_camps_link(html: str, page_url: str) -> dict | None:
    """The camps link on a roster page: {url, text, via: anchor|json, female, soccer} or None.
    Anchors (text, title, aria-label, href) first; JSON nav objects only when no anchor matches."""
    exclude = {page_url.split("#")[0]}
    soup = BeautifulSoup(html, "html.parser")
    best = _pick(_anchor_candidates(soup, page_url, exclude))
    via = "anchor"
    if not best:
        best = _pick(_json_candidates(html, page_url, exclude))
        via = "json"
    if not best:
        return None
    return {"url": best["url"], "text": best["text"], "via": via, "female": best["female"], "soccer": best["soccer"]}


def _strippable(el) -> bool:
    if el.name in ("html", "body", "main"):  # Weebly: <body class="header-page ...">
        return False
    for tok in (el.get("class") or []) + [el.get("id") or ""]:
        if REVIEW_TOKEN_RE.search(tok):  # before the keep check: 'rd-google-review-card' has 'card'
            return True
        if STRIP_TOKEN_RE.search(tok) and not KEEP_TOKEN_RE.search(tok):
            return True
    return False


def _content(soup):
    """The page minus navigation, header, footer and sidebars (site nav repeats the camps links)."""
    for t in soup(["script", "style", "noscript", "nav", "header", "footer", "svg", "aside", "template"]):
        t.decompose()
    for t in [t for t in soup.find_all(True) if _strippable(t)]:
        if not t.decomposed:  # already gone with a stripped ancestor
            t.decompose()
    return soup


def _sport_link_score(text: str, href: str) -> dict | None:
    """Hub pages list every sport's camp: 'Women's Soccer - Duke Soccer Academy' has no camp word,
    so a women/girls + soccer link counts even without one."""
    sc = _link_score(text, href)
    if sc:
        return sc
    t, h = common.clean(text), href or ""
    female = bool(FEMALE_RE.search(t) or FEMALE_LOOSE_RE.search(h))
    soccer = bool(SOCCER_RE.search(t) or SOCCER_RE.search(h))
    if female and soccer and not (OTHER_SPORT_RE.search(t) or OTHER_SPORT_LOOSE_RE.search(h)):
        return {"score": 5, "female": True, "male": False, "soccer": True}
    return None


def find_hub_hop(html: str, page_url: str, exclude: set[str]) -> dict | None:
    """On an internal all-sports camps hub, the one link to follow: a camp link that names women/girls
    or soccer (women/girls preferred, men/boys never); on a Sidearm hub page (/sports/YYYY/M/D/...)
    also a single generic camps link. Navigation, header, footer and registration portals are ignored."""
    soup = _content(BeautifulSoup(html, "html.parser"))
    skip = exclude | {page_url.split("#")[0]}
    cands, seen = [], set()
    for i, a in enumerate(soup.find_all("a", href=True)):
        url = _http_url(a.get("href"), page_url)
        if not url or url.split("#")[0] in skip or url in seen:
            continue
        if NOT_CAMP_PAGE_RE.search(url) or REGISTER_PORTAL_RE.search(url):
            continue
        text = " ".join(filter(None, [a.get_text(" ", strip=True), a.get("title"), a.get("aria-label")]))
        sc = _sport_link_score(re.sub(r"opens in a new (?:window|tab)", "", text, flags=re.I), url)
        if sc:
            seen.add(url)
            cands.append({**sc, "url": url, "text": common.clean(text)[:120], "order": i})
    if any(not c["male"] for c in cands):
        cands = [c for c in cands if not c["male"]]
    else:
        return None  # only men's/boys' camps listed
    specific = [c for c in cands if c["female"] or c["soccer"]]
    best = _pick(specific)
    if best:
        return best
    if len(cands) == 1 and HUB_PATH_RE.search(urlparse(page_url).path):
        return cands[0]
    return None


def detect_vendor(url: str | None, html: str | None, base_host: str) -> str | None:
    if not url:
        return None
    if _same_site(url, base_host):
        return "athletics"
    host = _host(url)
    for suffix, vendor in VENDOR_HOSTS:
        if host == suffix or host.endswith("." + suffix):
            return vendor
    for marker, vendor in VENDOR_MARKERS:
        if html and marker in html[:200000]:
            return vendor
    return "external"


# ---------- fetching with robots ----------

def fetch_checked(url: str, base_host: str, *, max_age_hours: float = 24.0) -> dict:
    """Fetch a camp page. Hosts outside the athletics site are checked against robots.txt before
    the request (denied = no request at all) and again on the final host after redirects (denied =
    the body is discarded and its `.cache/http` entry removed). Returns {url, finalUrl, html,
    robotsBlocked, error, nonHtml}; nonHtml is True when the page was fetched but is not HTML (a PDF,
    an empty body, another content type), so nothing could be parsed."""
    out = {"url": url, "finalUrl": None, "html": None, "robotsBlocked": False, "error": None, "nonHtml": False}
    if not _same_site(url, base_host) and not common.robots_allowed(url):
        out["robotsBlocked"] = True
        return out
    try:
        html, meta = common.fetch_text(url, max_age_hours=max_age_hours, retries=1, timeout=30)
    except common.FetchError as e:
        out["error"] = str(e)[:200]
        return out
    final = meta.get("finalUrl") or url
    out["finalUrl"] = final
    if _host(final) != _host(url) and not _same_site(final, base_host) and not common.robots_allowed(final):
        out["robotsBlocked"] = True  # redirected onto a host that disallows crawling: keep the link, drop the body
        common.forget_cached(url)    # common.fetch stored it before the final host could be checked
        return out
    ctype = (meta.get("contentType") or "").lower()
    if "pdf" in ctype or final.lower().endswith(".pdf") or (ctype and "html" not in ctype and "xml" not in ctype) \
            or not (html or "").strip():
        out["nonHtml"] = True  # a camp-info PDF, an empty body or other non-HTML: the link is shown, nothing is parsed
        return out
    out["html"] = html
    return out


# ---------- dates ----------
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_MON = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"
_WEEKDAY = r"(?:(?:Mon|Tues?|Wed(?:nes)?|Thu(?:rs)?|Fri|Sat(?:ur)?|Sun)(?:day)?\.?,?\s+)?"
DATE_RE = re.compile(
    rf"\b{_WEEKDAY}({_MON})\.?\s+{_DAY}(?![:\d])"
    rf"(?:\s*(?:-|–|—|to|through|thru)\s*(?:({_MON})\.?\s+)?{_DAY}(?![:\d]))?"
    rf"(?:,?\s+(20\d\d))?\b", re.I)
NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d\d|\d{2})\b(?!\s+\d{1,2}:\d{2})")  # not a '3/2/2026 4:30:00 PM' dateline
DATE_ONLY_LINE_RE = re.compile(rf"^\W*(?:{_WEEKDAY}{_MON}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:\s*(?:-|–|—|to|through)\s*(?:{_MON}\.?\s+)?\d{{1,2}}(?:st|nd|rd|th)?)?,?\s+20\d\d|\d{{1,2}}/\d{{1,2}}/20\d\d)\W*$", re.I)
MONTH_YEAR_RE = re.compile(rf"\b({_MON})\.?\s+(20\d\d)\b")
BARE_MONTH_RE = re.compile(r"\b(January|February|March|April|June|July|August|September|October|November|December|"
                           r"Jan\.|Feb\.|Mar\.|Apr\.|Jun\.|Jul\.|Aug\.|Sept?\.|Oct\.|Nov\.|Dec\.)|\bin (May)\b")
YEAR_RE = re.compile(r"\b(20\d\d)\b")
REGISTRATION_RE = re.compile(r"regist|deadline|sign[- ]?up|enroll|\bopens\b|\bcloses?\b|\bdue\b|\bearly[- ]bird\b|discount|until", re.I)
TBD_RE = re.compile(r"\bTB[AD]\b", re.I)


def _month(s: str) -> int | None:
    return MONTHS.get(s[:3].lower())


def _valid(y: int, m: int, d: int) -> bool:
    try:
        _dt.date(y, m, d)
        return True
    except ValueError:
        return False


def _infer_year(month: int, day: int, published: str | None) -> int | None:
    """Year for a day/month with no year: the release year, rolled forward when the date would fall
    more than 30 days before the release (a January release about a February camp stays; an
    August release about a July camp means next year) and rolled back when it would fall more than
    330 days after it (a January 5 recap of "the December 20 ID Camp" means last December)."""
    if not published:
        return None
    try:
        pub = _dt.date.fromisoformat(published[:10])
    except ValueError:
        return None
    y = pub.year
    if not _valid(y, month, day):
        return None
    if _dt.date(y, month, day) < pub - _dt.timedelta(days=30):
        y += 1
    elif _dt.date(y, month, day) > pub + _dt.timedelta(days=330):
        y -= 1
    return y if _valid(y, month, day) else None


def parse_camp_dates(text: str, published: str | None = None, *, default_year: int | None = None) -> list[dict]:
    """Every date in `text`: [{startDate, endDate, dateText, precision, yearInferred, pos}].
    Day precision needs a year in the text, `default_year` (e.g. a table caption '2026 ... DATES')
    or `published` (news release date, see _infer_year); otherwise the date is dropped. When the
    text has no day-level date, a month name (with `published` or a year) gives month precision."""
    out = []
    for m in DATE_RE.finditer(text):
        mon1, d1, mon2, d2, year = m.group(1), int(m.group(2)), m.group(3), m.group(4), m.group(5)
        m1 = _month(mon1)
        if not m1 or d1 < 1 or d1 > 31:
            continue
        inferred = False
        y = int(year) if year else default_year
        if y is None:
            y = _infer_year(m1, d1, published)
            inferred = y is not None
        elif not year:
            inferred = True
        if y is None or not _valid(y, m1, d1):
            continue
        start = _dt.date(y, m1, d1)
        end = start
        if d2:
            m2 = _month(mon2) if mon2 else m1
            d2i = int(d2)
            if m2 and _valid(y, m2, d2i):
                e = _dt.date(y, m2, d2i)
                if e < start and not mon2:  # 'September 12 - 1' is a time, not a range
                    e = start
                elif e < start:
                    e = _dt.date(y + 1, m2, d2i) if _valid(y + 1, m2, d2i) else start
                if (e - start).days <= 31:
                    end = e
        out.append({"startDate": start.isoformat(), "endDate": end.isoformat(), "dateText": common.clean(m.group(0)),
                    "precision": "day", "yearInferred": inferred, "pos": m.start()})
    for m in NUMERIC_DATE_RE.finditer(text):
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        if _valid(y, mo, d):
            out.append({"startDate": _dt.date(y, mo, d).isoformat(), "endDate": _dt.date(y, mo, d).isoformat(),
                        "dateText": m.group(0), "precision": "day", "yearInferred": False, "pos": m.start()})
    if out:
        return sorted(out, key=lambda x: x["pos"])
    m = MONTH_YEAR_RE.search(text)
    if m and _month(m.group(1)):
        mo, y = _month(m.group(1)), int(m.group(2))
        return [{"startDate": f"{y}-{mo:02d}", "endDate": f"{y}-{mo:02d}", "dateText": f"{_dt.date(y, mo, 1):%B %Y}",
                 "precision": "month", "yearInferred": False, "pos": m.start()}]
    m = BARE_MONTH_RE.search(text)
    if m and (published or default_year):
        mo = _month(m.group(1) or m.group(2))
        y = default_year
        if y is None:
            try:
                pub = _dt.date.fromisoformat(published[:10])
                y = pub.year + (1 if mo < pub.month - 1 else 0)
            except (ValueError, TypeError):
                return []
        return [{"startDate": f"{y}-{mo:02d}", "endDate": f"{y}-{mo:02d}", "dateText": f"{_dt.date(y, mo, 1):%B %Y}",
                 "precision": "month", "yearInferred": True, "pos": m.start()}]
    return []


# ---------- extraction ----------
BLOCK_TAGS = ["p", "li", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt", "div", "section", "article", "blockquote", "figcaption"]
GRADES_RE = re.compile(r"(?:grades?\s+\d{1,2}\s*(?:-|–|to|through)\s*\d{1,2}|\d{1,2}(?:st|nd|rd|th)?\s*(?:-|–|to|through)\s*\d{1,2}(?:st|nd|rd|th)?\s+grade(?:rs|s)?|"
                       r"ages?\s+\d{1,2}\s*(?:-|–|to|through)\s*\d{1,2}|\d{1,2}\s*(?:-|–|to)\s*\d{1,2}\s+years?\s+old|"
                       r"(?:rising\s+)?(?:\d{1,2}(?:st|nd|rd|th)|freshm[ae]n|sophomores?|juniors?|seniors?)(?:\s*(?:-|–|,|and|through)\s*(?:\d{1,2}(?:st|nd|rd|th)|freshm[ae]n|sophomores?|juniors?|seniors?))*\s+grade(?:rs|s)?|"
                       r"high school (?:girls|players|athletes|prospects)|u\d{1,2}(?:\s*-\s*u\d{1,2})?)", re.I)
PRICE_RE = re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?")
LOCATION_RE = re.compile(r"\b(?:at|held at|location:|where:|site:)\s*(?:the\s+)?([A-Z][\w.'&-]*(?:\s+[A-Z][\w.'&-]*){0,6}?\s*(?:Fields?|Stadium|Complex|Center|Centre|Park|Campus|Pitch|Turf|Arena|Facility|Dome|Bubble))\b")
REGISTER_HREF_RE = re.compile(r"regist|campdoc|totalcamps|campnetwork|active\.com|forms\.gle|docs\.google\.com/forms|ryzer|signup|sign-up|enroll|checkout|/shop/", re.I)
REGISTER_TEXT_RE = re.compile(r"regist|sign[- ]?up|enroll|book|reserve", re.I)
# A registration URL that names another sport: montanabasketballcamps.com, moorehoopsacademy,
# kevingiltnerbasketballcamps, chattanoogavolleyball. Host/path text, so no word boundaries; 'hoops'
# and 'gridiron' are here because the host, not the page, is what carries the sport.
OTHER_SPORT_HOST_RE = re.compile(
    r"basketball|hoops|football|gridiron|softball|baseball|volleyball|tennis|lacrosse|golf|wrestl|"
    r"swim|dive|hockey|cheer|dance|spirit|track|gymnastics|rowing|crew|fencing|water-?polo|equestrian", re.I)
# Button labels that a table's cost column yields instead of an amount ('See Prices' x14).
PRICE_LABEL_RE = re.compile(r"^(?:see|view|check|click|more)?\s*(?:prices?|pricing|costs?|fees?|details?|info(?:rmation)?|"
                            r"here|below|register|registration|sign[- ]?up|tb[ad]|varies|n/?a|-|—|–)\s*$", re.I)
CAMP_PHRASE_RE = re.compile(r"((?:[A-Z][\w'&./-]*\s+){0,5}(?i:(?:ID\s+)?(?:Camps?|Clinics?))(?:\s+(?:Dates?|Schedule|Series|Session\s*\d*|\d+))?)")
HEADER_DATE_RE = re.compile(r"\bdates?\b|\bwhen\b", re.I)
HEADER_NAME_RE = re.compile(r"\bcamps?\b|\bclinics?\b|\bevents?\b|\bsessions?\b|\bname\b|\bprogram\b", re.I)

# ---------- sport sections on an all-sport camps hub ----------
# An athletics department's camps hub lists every sport under a heading, and the rows below a
# heading carry no sport of their own: wofford's three men's ID Camp rows and its one genuine
# women's row are all named exactly "ID Camp", and north-dakota's football rows are "Flagship Camp
# #1". The heading is the only thing that separates them, so it has to be read at row level.
#
# A line is a section heading when it names a sport, carries no date, and has nothing left once the
# sport, the camp words, the gender words, the year and the filler are removed - so "Men's
# Basketball Camps", "Soccer - 2026" and "Beach Volleyball" qualify, while "Cal Girls Soccer Camp"
# (leaves "Cal") and "Soccer & Lacrosse Complex" (leaves "Complex") do not. Both non-matches are the
# safe direction: with no heading the section is unset and every row is allowed, so a page without
# sport headings - which is most of them - parses exactly as before.
SECTION_WORD_RE = re.compile(
    r"\b(?:camps?|clinics?|schedules?|academy|academies|programs?|sessions?|dates?|information|info|"
    r"men|women|boys?|girls?|ladies|female|male|mens|womens)(?:'s|’s)?\b|\b\d{2,4}\b", re.I)
SECTION_FILLER_RE = re.compile(r"\b(?:beach|indoor|outdoor|sand|youth|junior|jr|and|the|of|all|amp|"
                               r"id|prospect|elite|skills|summer|winter|spring|fall|high|school|college)\b", re.I)
# A section's rejection only bites on a page that really is an all-sport hub: at least this many
# DIFFERENT sports named in heading-shaped lines. Without it a single cross-promotional line on a
# women's soccer page ("Volleyball Skills Camp") would gate away every camp below it - the
# catastrophic, invisible failure. montana names 5 sports, ut-chattanooga 7; a genuine single-sport
# camps page names one.
HUB_SPORT_COUNT = 3


def _sport_section(line: str) -> dict | None:
    """{"sport": "soccer"|"other", "male": bool, "token": str} when `line` is a sport-section
    heading, else None. None for an ambiguous heading naming both soccer and another sport:
    leaving the section unchanged is safer than guessing."""
    t = common.clean(line or "")
    if not t or len(t) > 60 or len(t.split()) > 7 or t.endswith("."):
        return None
    if DATE_RE.search(t) or NUMERIC_DATE_RE.search(t):
        return None  # a camp row, not a heading
    ms, mo = SOCCER_RE.search(t), OTHER_SPORT_RE.search(t)
    if bool(ms) == bool(mo):  # neither, or both
        return None
    rest = SECTION_WORD_RE.sub(" ", t)
    rest = OTHER_SPORT_RE.sub(" ", SOCCER_RE.sub(" ", rest))
    rest = SECTION_FILLER_RE.sub(" ", rest)
    if re.sub(r"[^A-Za-z]+", "", rest):
        return None  # something other than the sport's own name is in the heading
    return {"sport": "soccer" if ms else "other",
            "male": bool(MALE_RE.search(t)) and not FEMALE_RE.search(t),
            "token": (ms or mo).group(0).lower()}


def _row_allowed(name: str, section: dict | None, *, is_hub: bool = True) -> bool:
    """False when a row is another sport's or another gender's. The name is checked on its own
    (safe anywhere: 'Rod Ray Tennis Camp', "ORU Winter College Men's ID Camp I"); the enclosing
    section applies only on a page that is actually an all-sport hub (see HUB_SPORT_COUNT)."""
    t = common.clean(name or "")
    soccer_name = bool(SOCCER_RE.search(t))
    if OTHER_SPORT_RE.search(t) and not soccer_name:
        return False
    if MALE_RE.search(t) and not FEMALE_RE.search(t):  # MALE_RE does not fire inside "Women's"
        return False
    if section is None or not is_hub:
        return True
    if section["sport"] == "other" and not soccer_name:
        return False
    if section["male"] and not FEMALE_RE.search(t):
        return False
    return True


def _preceding_section(el) -> dict | None:
    """The sport section a table sits under: the nearest heading-like text before it."""
    seen = 0
    for prev in el.previous_elements:
        if getattr(prev, "name", None) not in ("h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "caption", "legend", "summary"):
            continue
        sec = _sport_section(prev.get_text(" "))
        if sec:
            return sec
        seen += 1
        if seen > 40:
            break
    return None


ZERO_WIDTH_RE = re.compile(r"[​‌‍﻿]")  # zero-width space/joiners, BOM


def _prepare(html: str) -> str:
    return re.sub(r"<br\s*/?>", "\n", html, flags=re.I)


def _sentences(text: str) -> list[str]:
    t = re.sub(r"\b(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.\s", r"\1 ", text)
    t = re.sub(r"\b([ap])\.m\.", r"\1.m", t, flags=re.I)
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])", t) if s.strip()]


def _lines(root) -> list[tuple[str, object]]:
    """(text, element) per block element's own text (text nodes and inline children, so a lead
    paragraph that sits directly in a <div> next to <p> siblings is not lost), split on <br>
    (already newlines) and sentence ends."""
    out = []
    blocks = set(BLOCK_TAGS)

    def add(el, raw):
        for piece in raw.split("\n"):
            piece = common.clean(ZERO_WIDTH_RE.sub("", piece))
            if not piece:
                continue
            for s in _sentences(piece):
                s = common.clean(s)
                if s and (not out or out[-1][0] != s):
                    out.append((s, el))

    for el in root.find_all(BLOCK_TAGS):
        parts = []
        for child in el.children:
            name = getattr(child, "name", None)
            if name is None:
                parts.append(str(child))
            elif name in blocks or child.find(BLOCK_TAGS):
                add(el, " ".join(parts))
                parts = []
            else:
                parts.append(child.get_text(" "))
        add(el, " ".join(parts))
    return out


def _camp_phrase(line: str, fallback: str | None) -> str:
    """A short name for the camp on `line`: the line itself when short (minus a date that carries a
    year: 'Spring ID Camp - April 19, 2026'), else the capitalised phrase ending in camp/clinic
    ('Summer Elite ID Camp'); a news title beats a phrase of fewer than three words."""
    name = DATE_RE.sub(lambda m: "" if m.group(5) else m.group(0), line)
    name = re.sub(r"\s*[-–:|,]\s*$", "", common.clean(name)).strip(" -–:|,")
    if CAMP_RE.search(name) and 3 <= len(name) <= 60 and len(name.split()) <= 8 and not name.endswith("."):
        return name  # a heading: 'June 6th ID Camp', 'Soccer ID Clinic'
    m = CAMP_PHRASE_RE.search(NOT_CAMP_RE.sub(" ", line))
    if m:
        cand = common.clean(m.group(1))
        cand = re.sub(r"^(?:The|Our|A|An|This|Its|Their|Annual|Upcoming|First|Second|Third)\s+", "", cand)
        if 4 <= len(cand) <= 80 and not (fallback and re.fullmatch(r"(?:ID\s+)?(?:camps?|clinics?)", cand, re.I)):
            return cand
    return fallback or "Camp"


def _register_url(elements, page_url: str, section: dict | None = None) -> str | None:
    """The row's registration link, or None when the only candidate contradicts the sport.

    A hub page carries one registration block for the whole department, so the same link lands on
    every row: all 20 wofford rows point at a basketball camps domain, montana's at
    montanabasketballcamps.com, harvard's at moorehoopsacademy. Fifty of the 131 stored
    registerUrls name another sport. Dropping the *link* rather than the row is deliberate - exactly
    one of those 50 sits on a genuine camp (wofford's 2026-11-22 ID Camp), and losing a real camp is
    worse than losing a link. A soccer-named link, or one on a row in a soccer section, is kept."""
    for el in elements:
        for a in el.find_all("a", href=True) if hasattr(el, "find_all") else []:
            url = _http_url(a.get("href"), page_url)
            if not url:
                continue
            if not (REGISTER_HREF_RE.search(url) or REGISTER_TEXT_RE.search(a.get_text(" ", strip=True) or "")):
                continue
            if OTHER_SPORT_HOST_RE.search(url) and not SOCCER_RE.search(url) \
                    and not (section and section["sport"] == "soccer"):
                continue
            return url
    return None


def _details(window: list[str]) -> dict:
    text = " | ".join(window)
    ages = GRADES_RE.search(text)
    price = PRICE_RE.search(text)
    loc = LOCATION_RE.search(text)
    return {"location": common.clean(loc.group(1)) if loc else None,
            "ages": common.clean(ages.group(0)) if ages else None,
            "price": price.group(0).replace(" ", "") if price else None}


def _entry(name, d, details, register, page_url):
    price = details.get("price")
    if price and PRICE_LABEL_RE.match(common.clean(price)):
        price = None  # 'See Prices' is the button, not the amount
    return {"name": _clean_name(name), "startDate": d["startDate"], "endDate": d["endDate"], "dateText": d["dateText"],
            "precision": d["precision"], "yearInferred": bool(d.get("yearInferred")),
            "location": details.get("location"), "ages": details.get("ages"), "price": price,
            "registerUrl": register, "sourceUrl": page_url, "confidence": "heuristic"}


def _clean_name(name: str) -> str:
    """Trim a name that was cut mid-phrase: columbia's '2026 Elite College ID Clinic &' is the page's
    '... ID Clinic & Showcase' truncated at the ampersand."""
    return re.sub(r"\s*(?:&amp;|&|\+|/|,|-|–|:)\s*$", "", common.clean(name or ""))[:120]


# Page chrome mistaken for a camp name: 'Camp Dates', 'Camps, Clinics and Tournaments',
# 'Camp/Clinic Information', 'CAMP DETAILS', '2025-26 UTC CAMP SCHEDULE'. These rows are usually
# REAL camps wearing the section heading as a name - portland's single camp and california's two
# are genuine - so the name is repaired from the page title, never rejected. Season words are
# deliberately absent from the vocabulary so 'Fall Clinic' keeps its own name.
CHROME_WORD_RE = re.compile(r"^(?:camps?|clinics?|tournaments?|events?|sessions?|dates?|details?|information|info|"
                            r"schedules?|index|page|and|the|our|all|a|of|utc|sports?|"
                            r"sun|mon|tues?|wed|thur?s?|fri|sat|"
                            r"sunday|monday|tuesday|wednesday|thursday|friday|saturday|\d{2,4})$", re.I)
CHROME_NOUN_RE = re.compile(r"^(?:dates?|details?|information|info|schedules?|index|page|tournaments?|events?)$", re.I)
_PLAIN_CAMP_WORDS = {"camp", "camps", "clinic", "clinics"}


def _is_chrome_name(name: str) -> bool:
    toks = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", name or "")]
    if not toks or not all(CHROME_WORD_RE.match(t) for t in toks):
        return False
    return any(CHROME_NOUN_RE.match(t) for t in toks) or all(t in _PLAIN_CAMP_WORDS for t in toks)


def _table_entries(soup, page_url: str, published: str | None, sports: set | None = None) -> list[dict]:
    out = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        header, hi = None, -1
        for i, r in enumerate(rows[:4]):
            cells = [common.clean(c.get_text(" ")) for c in r.find_all(["th", "td"])]
            if len(cells) >= 2 and any(HEADER_DATE_RE.search(c) for c in cells) and any(HEADER_NAME_RE.search(c) for c in cells):
                header, hi = cells, i
                break
        if header is None:
            continue
        pre = " ".join(common.clean(r.get_text(" ")) for r in rows[:hi]) + " " + common.clean((table.find("caption") or table).get_text(" ")[:200])
        ym = YEAR_RE.search(pre)
        default_year = int(ym.group(1)) if ym else None

        def col(pattern):
            for j, c in enumerate(header):
                if re.search(pattern, c, re.I):
                    return j
            return None
        c_date, c_name = col(r"\bdates?\b|\bwhen\b"), col(r"\bcamps?\b|\bclinics?\b|\bevents?\b|\bsessions?\b|\bname\b|\bprogram\b")
        c_age, c_cost, c_loc = col(r"grade|age"), col(r"cost|price|fee"), col(r"location|where|site|venue")
        section = _sport_section(pre) or _preceding_section(table)
        if section is not None and sports is not None:
            sports.add(section["token"])
        for r in rows[hi + 1:]:
            cells = r.find_all(["th", "td"])
            texts = [common.clean(c.get_text(" ")) for c in cells]
            if len(texts) <= max(c_date, c_name):
                continue
            if TBD_RE.search(texts[c_date]) or REGISTRATION_RE.search(texts[c_date]):
                continue
            dates = parse_camp_dates(texts[c_date], published, default_year=default_year)
            if not dates:
                continue
            name = texts[c_name] or _camp_phrase(" ".join(texts), None)
            if not CAMP_RE.search(name) and not CAMP_RE.search(" ".join(header)):
                continue
            details = _details(texts)
            if c_age is not None and texts[c_age]:
                details["ages"] = texts[c_age]
            if c_cost is not None and texts[c_cost]:
                details["price"] = texts[c_cost][:60]
            if c_loc is not None and texts[c_loc]:
                details["location"] = texts[c_loc][:80]
            out.append({**_entry(name, _widen(dates[0], texts), details,
                                 _register_url(cells, page_url, section), page_url),
                        "_section": section})
    return out


def _widen(d: dict, texts: list[str]) -> dict:
    """Recover an endDate the date column dropped. A ryzer row puts '11/21/2026' in the date column
    and the real span in the name: 'Elite Prospect ID Camp | November 21st - 22nd'. The single-day
    date wins the parse, so the range is lost. When another cell carries a day range that starts on
    the same date, its end is taken."""
    if d.get("precision") != "day" or d.get("startDate") != d.get("endDate"):
        return d
    for t in texts:
        for alt in parse_camp_dates(t, None, default_year=int(d["startDate"][:4])):
            if alt["precision"] == "day" and alt["startDate"] == d["startDate"] and alt["endDate"] > d["endDate"]:
                return {**d, "endDate": alt["endDate"], "dateText": alt["dateText"]}
    return d


def _prose_entries(soup, page_url: str, published: str | None, title: str | None, sports: set | None = None) -> list[dict]:
    lines = _lines(soup)
    camp_page = bool(title and CAMP_RE.search(NOT_CAMP_RE.sub(" ", title)))
    out = []
    section = None
    i = 0
    while i < len(lines):
        text, el = lines[i]
        # An all-sport hub is one flat run of <br>-separated lines (montana is a single <div>), so
        # the section is tracked by line order rather than by element nesting. The heading line is
        # NOT skipped afterwards: on a single-sport page the heading and the camp's name are the
        # same line, and winthrop's only camp is called "Youth Soccer Camp" with its dates on the
        # two lines below. A heading that is genuinely just a divider yields no entry anyway - the
        # date lookahead stops at the next camp line - and one that slips through is caught by
        # _row_allowed, which sees the section this line just set.
        sec = _sport_section(text)
        if sec is not None:
            section = sec
            if sports is not None:
                sports.add(sec["token"])
        is_camp_line = bool(CAMP_RE.search(NOT_CAMP_RE.sub(" ", text)))
        if not is_camp_line:
            # a line that is only a date on a page titled '... ID Clinic' (Georgetown: 'July 25-26, 2026')
            if camp_page and DATE_ONLY_LINE_RE.match(text):
                ds = parse_camp_dates(text, published)
                if ds:
                    window = [t for t, _ in lines[i + 1:i + 6] if not CAMP_RE.search(t) or len(t) >= 90]
                    out.append({**_entry(title, ds[0], _details(window), _register_url([e for _, e in lines[i:i + 6]], page_url, section), page_url),
                                "_weak": True, "_section": section})
            i += 1
            continue
        window = [text]
        elems = [el]
        # dates on the camp line itself, else (for a short heading-like line) on one of the next three
        # lines that carries a year or sits in the same block (FSU: name / date / grades / price)
        picked = []
        for d in parse_camp_dates(text, published):
            if REGISTRATION_RE.search(text[max(0, d["pos"] - 60):d["pos"]]):
                continue  # 'Registration opens March 1' is not a camp date
            picked.append(d)
        j = i + 1
        while not picked and len(text) <= 90 and not REGISTRATION_RE.search(text) and j < len(lines) and j <= i + 3:
            t2, e2 = lines[j]
            if CAMP_RE.search(NOT_CAMP_RE.sub(" ", t2)) and len(t2) < 90:
                break  # the next camp starts here
            if TBD_RE.search(t2):
                break
            ds = parse_camp_dates(t2, published)
            ds = [d for d in ds if not REGISTRATION_RE.search(t2[max(0, d["pos"] - 60):d["pos"]])
                  and (YEAR_RE.search(t2) or e2 is el)]
            if ds and not REGISTRATION_RE.search(t2[:40]):
                picked = ds[:1]
                window.append(t2)
                elems.append(e2)
            j += 1
        if picked:
            k = max(j, i + 1)
            while k < len(lines) and k <= i + 6:
                t3, e3 = lines[k]
                if CAMP_RE.search(NOT_CAMP_RE.sub(" ", t3)) and len(t3) < 90:
                    break
                window.append(t3)
                elems.append(e3)
                k += 1
            name = _camp_phrase(text, title)
            details = _details(window)
            register = _register_url(elems, page_url, section)
            for d in picked[:4]:
                out.append({**_entry(name, d, details, register, page_url),
                            "_weak": name == title, "_section": section})
        i += 1
    return out


def _dedupe(entries: list[dict]) -> list[dict]:
    """Drop repeats: a weak entry (named after the page/release title, or a bare date line) loses
    to any entry on the same start date; two entries on the same dates whose names nest ('Youth ID
    Camp' / '2026 Denver Women's Soccer Youth ID Camp') keep the one with more details."""
    strong_dates = {e["startDate"] for e in entries if not e.get("_weak")}
    entries = [e for e in entries if not (e.get("_weak") and e["startDate"] in strong_dates and any(
        o is not e and o["startDate"] == e["startDate"] and not o.get("_weak") for o in entries))]
    out: list[dict] = []
    for e in entries:
        toks = set(re.findall(r"[a-z0-9]+", e["name"].lower()))
        rich = sum(1 for k in ("location", "ages", "price", "registerUrl") if e.get(k))
        dup = None
        for o in out:
            if o["startDate"] != e["startDate"] or o["endDate"] != e["endDate"]:
                continue
            otoks = set(re.findall(r"[a-z0-9]+", o["name"].lower()))
            if toks <= otoks or otoks <= toks:
                dup = o
                break
        if dup is None:
            out.append(e)
            continue
        drich = sum(1 for k in ("location", "ages", "price", "registerUrl") if dup.get(k))
        if (rich, len(e["name"])) > (drich, len(dup["name"])):
            out[out.index(dup)] = e
    out = _merge_overlaps(out)
    return [{k: v for k, v in e.items() if not k.startswith("_")} for e in out]


def _merge_overlaps(entries: list[dict]) -> list[dict]:
    """Collapse one camp emitted as several overlapping rows into a single row spanning all of them.

    nicholls lists a youth camp as the range July 21-24 *and* as each of its four days; SMU emits
    Jun 13-16, 15-19 and 17-20 for one camp series, all three named after the page. The rows share a
    name (equal, or one nesting inside the other) and their date ranges touch, so they are the same
    camp seen twice. Rows with the same name on dates that do NOT overlap are left alone - a real ID
    camp series keeps every session."""
    out: list[dict] = []
    for e in entries:
        if e.get("precision") != "day":
            out.append(e)
            continue
        toks = set(re.findall(r"[a-z0-9]+", e["name"].lower()))
        merged = False
        for o in out:
            if o.get("precision") != "day":
                continue
            otoks = set(re.findall(r"[a-z0-9]+", o["name"].lower()))
            if not (toks <= otoks or otoks <= toks):
                continue
            if e["startDate"] > o["endDate"] or o["startDate"] > e["endDate"]:
                continue  # disjoint: two real sessions of the same camp
            o["startDate"] = min(o["startDate"], e["startDate"])
            o["endDate"] = max(o["endDate"], e["endDate"])
            if len(e["name"]) > len(o["name"]):
                o["name"] = e["name"]
            for k in ("location", "ages", "price", "registerUrl"):
                if not o.get(k) and e.get(k):
                    o[k] = e[k]
            merged = True
            break
        if not merged:
            out.append(e)
    return out


def extract_camps(html: str, page_url: str, *, published: str | None = None, title: str | None = None,
                  body_only: bool = False) -> list[dict]:
    """Heuristic camp entries from a server-rendered page: table rows (header names a date and a
    camp/clinic/event column) and text lines naming a camp with a date. Camp pages need a year in
    the text (or a table caption year); news releases pass `published` so a year-less date is
    inferred. Registration dates, deadlines and TBD are never entries. Deduped, at most MAX_CAMPS."""
    soup = BeautifulSoup(_prepare(html), "html.parser")
    for t in soup(["script", "style", "noscript", "svg", "template"]):
        t.decompose()
    root = soup
    if body_only:
        root = _article_body(soup) or _content(soup)
    else:
        _content(soup)
    sports: set = set()
    entries = _table_entries(root, page_url, published, sports) + _prose_entries(root, page_url, published, title, sports)
    day_months = {e["startDate"][:7] for e in entries if e["precision"] == "day"}
    entries = [e for e in entries if not (e["precision"] == "month" and e["startDate"] in day_months)]
    # Sport and gender gating before the cap, not after: MAX_CAMPS is a defence against a runaway
    # parse, but applied first it spends all 20 slots on whatever the page lists earliest. montana
    # yields 28 rows and loses 8 to the cap; on a hub that put soccer last, the real camps would be
    # the rows cut. Gate, then cap.
    is_hub = len(sports) >= HUB_SPORT_COUNT
    entries = [e for e in entries if _row_allowed(e["name"], e.get("_section"), is_hub=is_hub)]
    if title and not _is_chrome_name(title):
        for e in entries:
            if _is_chrome_name(e["name"]):
                e["name"] = _clean_name(title)
    return _dedupe(entries)[:MAX_CAMPS]


ARTICLE_CLASS_RE = re.compile(r"article-content|article__body|article-body|articleBody|story-body|story__body|c-article__content|"
                              r"s-article__content|content-body|entry-content|post-content|article__content|story-content", re.I)


def _article_body(soup):
    for el in soup.find_all(True, class_=ARTICLE_CLASS_RE):
        if len(el.get_text(" ", strip=True)) > 200:
            return el
    for el in soup.find_all(True, attrs={"itemprop": "articleBody"}):
        return el
    for el in soup.find_all("article"):
        if len(el.get_text(" ", strip=True)) > 200:
            return el
    return None


# ---------- news mining ----------
NEWS_BLACKLIST_RE = re.compile(
    r"national team|training camp|base camp|called[- ]?up|call[- ]?ups?\b|named to|selected|invited|preseason|pre-season|"
    r"\bU-?\d{2}\b|\bcanada\b|\busa\b|\bu\.s\.|\buswnt\b|\bcwnt\b|\bwnt\b|\bynt\b|world cup|\bfifa\b|olympic|\bnwsl\b|"
    r"\bdraft\b|\bpro\b|\bprofessional\b|\bcombine\b", re.I)
SOCCER_SLUG_RE = re.compile(r"^(?:womens?-soccer|women-s-soccer|wsoc|soccer|w-soccer|womens-soc)(?:-|$)", re.I)
OTHER_SPORT_SLUG_RE = re.compile(
    r"(?:^|-)(?:cheer(?:leading)?|football|softball|baseball|basketball|volleyball|lacrosse|golf|tennis|track-and-field|track-field|"
    r"track|xc|cross-country|swimming|swim-dive|swimming-diving|swim|diving|wrestling|hockey|rowing|gymnastics|general|athletics|"
    r"mens-soccer|msoc|men-s-soccer|dance|spirit|esports|beach-volleyball|water-polo|fencing|squash|rifle|skiing|equestrian|sailing|bowling)(?:-|$)", re.I)


def _slug(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    seg = path.rsplit("/", 1)[-1]
    return re.sub(r"\.aspx$", "", seg, flags=re.I).lower()


def mine_camp_news(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """(accepted, rejected) news items whose title announces a camp or clinic run by the program.
    Rejects national-team call-ups and the like (NEWS_BLACKLIST_RE) and releases whose URL slug
    carries another sport (a shared athletics feed leaks cheer, football, softball, 'general')."""
    accepted, rejected = [], []
    for it in items:
        title = common.clean(it.get("title") or "")
        url = it.get("url") or ""
        t = NOT_CAMP_RE.sub(" ", title)
        why = None
        if not CAMP_RE.search(t):
            continue
        if NEWS_BLACKLIST_RE.search(title):
            why = "blacklist"
        else:
            slug = _slug(url)
            if not SOCCER_SLUG_RE.search(slug) and OTHER_SPORT_SLUG_RE.search(slug):
                why = "other-sport slug"
        (rejected if why else accepted).append({**it, "title": title, **({"why": why} if why else {})})
    return accepted, rejected


def _news_camps(slug: str, base_host: str) -> tuple[list[dict], int]:
    prev = common.load_source(slug, "news")
    items = (prev or {}).get("data", {}).get("items") or []
    accepted, _ = mine_camp_news(items)
    out = []
    for it in accepted[:12]:
        url, title, published = it["url"], it["title"], it.get("date")
        entries = []
        try:
            r = fetch_checked(url, base_host, max_age_hours=24 * 7)
            if r["html"]:
                entries = extract_camps(r["html"], r["finalUrl"] or url, published=published, title=title, body_only=True)
        except Exception as e:  # a single article must not sink the collector
            common.log(f"camps: news article failed {url}: {e}")
        if not entries:  # the title alone: 'Owls Host First ID Camp on February 22', 'WSOC April ID Clinic'
            ds = parse_camp_dates(title, published)
            d = ds[0] if ds else {"startDate": None, "endDate": None, "dateText": None, "precision": None, "yearInferred": False}
            entries = [_entry(title, d, {}, None, url)]
        for e in entries[:4]:
            out.append({**e, "newsTitle": title, "newsUrl": url, "newsDate": published})
    return out, len(items)


# ---------- collector ----------

def collect(program: dict, registry: dict) -> dict:
    slug = program["slug"]
    a = program["athletics"]
    base = a.get("baseUrl")
    if not base:
        raise common.FetchError("camps: no athletics baseUrl in registry")
    base_host = _host(base)
    data = {"campsUrl": None, "discoveredVia": None, "hubUrl": None, "finalUrl": None, "host": None, "vendor": None,
            "pageTitle": None, "robotsBlocked": False, "fetchError": None, "parsed": False,
            "camps": [], "newsCamps": [], "newsScanned": 0}
    roster_url = f"{base}{a.get('sportPath', '')}/roster"
    link = None
    registry_url = _http_url(a.get("campsUrl"))
    if a.get("campsUrl") and not registry_url:
        common.log(f"camps: registry athletics.campsUrl is not an http(s) URL, ignored: {a['campsUrl']!r}")
    if registry_url:
        link = {"url": registry_url, "text": "registry", "via": "registry", "female": True, "soccer": True}
    else:
        if a.get("skipReason"):
            raise common.SkipCollector(f"camps: {a['skipReason']} (registry athletics.skipReason)")
        platform = a.get("platform") or "auto"
        if platform != "auto":
            roster_url = adapters.get(platform).urls(program, registry)["roster"]
        html, _ = common.fetch_text(roster_url, max_age_hours=24)
        link = find_camps_link(html, roster_url)
    source_url = roster_url
    if link:
        data["campsUrl"], data["discoveredVia"] = link["url"], link["via"]
        source_url = link["url"]
        r = fetch_checked(link["url"], base_host)
        if r["html"] and _same_site(r["finalUrl"] or link["url"], base_host) and not (link["female"] or link["soccer"]):
            hop = find_hub_hop(r["html"], r["finalUrl"] or link["url"], {roster_url, link["url"]})
            if hop:
                common.log(f"camps: hub {r['finalUrl'] or link['url']} -> {hop['url']} ({hop['text'][:50]})")
                data["hubUrl"], data["campsUrl"] = link["url"], hop["url"]
                source_url = hop["url"]
                r2 = fetch_checked(hop["url"], base_host)
                r = r2 if (r2["html"] or r2["robotsBlocked"]) else {**r2, "finalUrl": r2["finalUrl"] or hop["url"]}
        data["finalUrl"] = r["finalUrl"] or data["campsUrl"]
        data["host"] = _host(data["finalUrl"])
        data["robotsBlocked"] = r["robotsBlocked"]
        data["fetchError"] = r["error"]
        data["vendor"] = detect_vendor(data["finalUrl"], r["html"], base_host)
        data["parsed"] = bool(r["html"])  # False: robots, fetch error, or a PDF/empty/non-HTML page (nothing to read)
        if r["html"]:
            soup = BeautifulSoup(r["html"][:20000], "html.parser")
            data["pageTitle"] = common.clean(soup.title.get_text())[:120] if soup.title else None
            short_title = re.split(r"\s+[-|–]\s+", data["pageTitle"] or "")[0] or None
            data["camps"] = extract_camps(r["html"], data["finalUrl"], title=short_title)
        common.log(f"camps: {data['campsUrl']} via {data['discoveredVia']}"
                   + (f" -> {data['finalUrl']}" if data["finalUrl"] != data["campsUrl"] else "")
                   + (" [robots: link only]" if data["robotsBlocked"] else "")
                   + (f" [fetch failed: {data['fetchError']}]" if data["fetchError"] else "")
                   + (" [not HTML: link only]" if r.get("nonHtml") else "")
                   + f": {len(data['camps'])} dated camps ({data['vendor']})")
    else:
        common.log(f"camps: no camps link found on {roster_url}")
    data["newsCamps"], data["newsScanned"] = _news_camps(slug, base_host)
    if data["newsCamps"]:
        common.log(f"camps: {len(data['newsCamps'])} camp entries from {data['newsScanned']} archived news items")
    _sanitize_urls(data)
    common.save_source(slug, NAME, data, url=_http_url(source_url) or roster_url, collector=NAME)
    return data


URL_FIELDS = ("campsUrl", "hubUrl", "finalUrl")
ENTRY_URL_FIELDS = ("registerUrl", "sourceUrl", "newsUrl")


def _sanitize_urls(data: dict) -> None:
    """Last line of defence before camps.json: every URL field is http(s) or null, whatever the
    registry, a redirect or a page put there."""
    for k in URL_FIELDS:
        data[k] = _http_url(data.get(k))
    for e in (data.get("camps") or []) + (data.get("newsCamps") or []):
        for k in ENTRY_URL_FIELDS:
            if k in e:
                e[k] = _http_url(e.get(k))
