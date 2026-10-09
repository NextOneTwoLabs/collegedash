"""An RFC 9309 robots.txt resolver (issue #87). No network, no regex built from operator input.

    rb = Robots.parse(body)            # bytes (resp.content) or str; never raises
    rb.allowed(url, "CollegeDashBot")  # raises BudgetExceeded when one verdict needs more than STEP_BUDGET steps
    rb.crawl_delay("CollegeDashBot")   # float seconds or None

The approved spec is the plan on issue #87, revisions 2, 3 and 3.1, with the owner's decisions of 2026-10-09:

Parsing
  * A UTF-8 BOM is stripped; lines split on LF, CRLF or CR; '#' comments and surrounding whitespace removed;
    directive names are case-insensitive. Work is on octets, so a pattern is never decoded and re-encoded.
  * A body over MAX_BODY_OCTETS (500 KiB, decision 7) is cut at the last line break before the limit.
  * A group is one or more User-agent lines followed by rules. Only an Allow or Disallow line (empty or not) closes
    a run of User-agent lines; Crawl-delay, Sitemap, unknown directives and blank lines do not (decision 12).
    Rules before any User-agent line are ignored.
Choosing the group
  * A User-agent value names us when its leading [A-Za-z_-]+ token equals our token, case-insensitively
    (decision 4): 'CollegeDashBot/1.0' does; '*bot', 'bot' and 'CollegeDash' do not. Every group naming us is
    merged; failing that every '*' group is merged; failing that everything is allowed.
Rules
  * An empty Allow or Disallow is ignored. A pattern without a leading '/' gets one (decision 10).
  * A pattern longer than MAX_PATTERN_OCTETS (4096 raw octets, decision 11): a Disallow keeps its first 4096 octets,
    moved back to just before a '%' whose escape the cut would split; an Allow is dropped. Both fail closed and are
    counted in truncated_rules.
  * '*' matches any run of octets; '$' anchors only as the final character and is literal elsewhere; '**' is '*'.
What is matched
  * urlsplit's path (';params' included; '/' when empty), plus '?' and the query whenever the URL has a '?', even
    with an empty query. No fragment. '/robots.txt' is always allowed. Matching is case-sensitive.
Percent-encoding, applied alike to pattern and URL
  1. every octet outside unreserved, reserved and '%' is encoded as %XX from its UTF-8 bytes;
  2. a '%' not followed by two hex digits becomes %25;
  3. every %XX has its hex uppercased and is decoded only when the character is unreserved;
  4. in a pattern %2A and %24 are a literal '*' and '$'; the URL side decodes %2A and %24 before matching.
Precedence
  * The matching rule with the longest normalised pattern (octets, with '*', '$', a literal '*' and a literal '$'
    one octet each) wins; Allow wins a tie; no match allows.
Work bounds
  * A rule's literal prefix (everything before its first '*') is compared first. The glob after it is a linear
    two-pointer match: the segments between '*'s are found leftmost-first from a moving position, which is exact
    for '*'-only globs. Steps = octets scanned, plus one per rule examined. STEP_BUDGET (2e6, decision 11) is shared
    by every rule of one verdict; when it runs out allowed() raises BudgetExceeded. collect/common.py then denies in
    an explicit check, and in the hook counts a resolver error, allowing in report mode and denying in enforce mode.
Crawl-delay
  * Only from the chosen merged group; the largest value across the merged groups; a finite float >= 0.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

MAX_BODY_OCTETS = 500 * 1024
MAX_PATTERN_OCTETS = 4096
STEP_BUDGET = 2_000_000

_UNRESERVED = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_RESERVED = frozenset(b":/?#[]@!$&'()*+,;=")
_KEEP = _UNRESERVED | _RESERVED  # plus '%', handled by steps 2 and 3
_HEX = frozenset(b"0123456789abcdefABCDEF")
_PCT = ord("%")
_TOKEN = re.compile(rb"[A-Za-z_-]+")
_LINES = re.compile(rb"\r\n|\r|\n")


class BudgetExceeded(Exception):
    """One verdict needed more than STEP_BUDGET matcher steps (see collect/common.py for what each caller does)."""


def normalise(raw: bytes) -> bytes:
    """Steps 1-3 above. Returns ASCII octets."""
    out = bytearray()
    i, n = 0, len(raw)
    while i < n:
        c = raw[i]
        if c == _PCT:
            if i + 2 < n and raw[i + 1] in _HEX and raw[i + 2] in _HEX:
                v = int(raw[i + 1:i + 3], 16)
                if v in _UNRESERVED:
                    out.append(v)
                else:
                    out += b"%" + raw[i + 1:i + 3].upper()
                i += 3
                continue
            out += b"%25"
        elif c in _KEEP:
            out.append(c)
        else:
            out += b"%%%02X" % c
        i += 1
    return bytes(out)


def _cut_pattern(raw: bytes) -> bytes:
    """An overlong Disallow pattern's first MAX_PATTERN_OCTETS octets, moved back to just before a '%' whose escape
    the cut would split (a cut through raw multi-byte UTF-8 stays: its octets encode to a prefix of the URL's)."""
    cut = raw[:MAX_PATTERN_OCTETS]
    for back in (1, 2):
        if len(raw) > MAX_PATTERN_OCTETS and len(cut) >= back and cut[-back] == _PCT:
            return cut[:-back]
    return cut


class _Rule:
    __slots__ = ("allow", "prefix", "segs", "tail", "anchored", "wild", "length")

    def __init__(self, allow: bool, raw: bytes):
        if not raw.startswith(b"/"):
            raw = b"/" + raw  # decision 10
        norm = normalise(raw)
        anchored = norm.endswith(b"$")
        if anchored:
            norm = norm[:-1]
        # tokens: literal octets, with '*' a wildcard and %2A / %24 a literal '*' / '$' (step 4)
        parts: list[bytearray] = [bytearray()]
        wilds = 0
        i = 0
        while i < len(norm):
            c = norm[i]
            if c == 0x2A:  # '*'
                if parts[-1] or len(parts) == 1:
                    parts.append(bytearray())
                    wilds += 1
                i += 1
                continue
            if c == _PCT and norm[i + 1:i + 3] in (b"2A", b"24"):
                parts[-1] += b"*" if norm[i + 1:i + 3] == b"2A" else b"$"
                i += 3
                continue
            parts[-1].append(c)
            i += 1
        self.allow = allow
        self.prefix = bytes(parts[0])
        self.wild = len(parts) > 1
        # segments after each '*'; an empty last one means the pattern ends in '*'
        self.segs = [bytes(p) for p in parts[1:-1]]
        self.tail = bytes(parts[-1]) if self.wild else b""
        self.anchored = anchored
        self.length = len(self.prefix) + sum(len(p) for p in parts[1:]) + wilds + (1 if anchored else 0)


class Steps:
    __slots__ = ("n",)

    def __init__(self):
        self.n = 0

    def charge(self, k: int) -> None:
        if self.n + k > STEP_BUDGET:
            raise BudgetExceeded(f"robots.txt verdict needed more than {STEP_BUDGET} steps")
        self.n += k

    def find(self, text: bytes, seg: bytes, start: int, end: int) -> int:
        """text.find(seg, start, end), never scanning past what the budget has left."""
        stop = min(end, start + (STEP_BUDGET - self.n))
        idx = text.find(seg, start, stop)
        if idx >= 0:
            self.n += idx + len(seg) - start
            return idx
        self.n += stop - start
        if stop < end:
            raise BudgetExceeded(f"robots.txt verdict needed more than {STEP_BUDGET} steps")
        return -1


def _matches(rule: _Rule, text: bytes, steps: Steps) -> bool:
    steps.charge(1)
    if not text.startswith(rule.prefix):
        return False
    n = len(text)
    if not rule.wild:
        return not rule.anchored or n == len(rule.prefix)
    pos = len(rule.prefix)
    for seg in rule.segs:
        idx = steps.find(text, seg, pos, n)
        if idx < 0:
            return False
        pos = idx + len(seg)
    tail = rule.tail
    if not tail:
        return True  # ends in '*': the rest of the path, anchored or not
    if rule.anchored:
        steps.charge(len(tail))
        return n - len(tail) >= pos and text.endswith(tail)
    return steps.find(text, tail, pos, n) >= 0


def target(url: str) -> bytes:
    """What a rule is matched against: the normalised path, '?query' when the URL has a '?', no fragment, with %2A
    and %24 decoded (step 4)."""
    parts = urlsplit(url)
    s = parts.path or "/"
    if "?" in url.split("#", 1)[0]:
        s += "?" + parts.query
    out = normalise(s.encode("utf-8", "surrogatepass"))
    return out.replace(b"%2A", b"*").replace(b"%24", b"$")


def agent_token(value: bytes | str) -> str | None:
    """'*', or the lower-cased leading [A-Za-z_-]+ token of a User-agent value (decision 4), or None."""
    if isinstance(value, str):
        value = value.encode("utf-8", "replace")
    if value == b"*":
        return "*"
    m = _TOKEN.match(value)
    return m.group(0).decode("ascii").lower() if m else None


class _Group:
    __slots__ = ("agents", "rules", "delay", "closed")

    def __init__(self):
        self.agents: set[str | None] = set()
        self.rules: list[_Rule] = []
        self.delay: float | None = None
        self.closed = False


class Robots:
    """A parsed robots.txt. ALLOW_ALL and DISALLOW_ALL stand for a missing file and for an unknown one."""

    def __init__(self, groups=(), *, everything: bool | None = None, truncated_body: bool = False,
                 truncated_rules: int = 0):
        self._groups = list(groups)
        self._everything = everything  # True = allow all, False = disallow all, None = use the groups
        self._ordered: dict[str, list[_Rule]] = {}  # agent -> its merged rules, longest first, Allow first on a tie
        self.truncated_body = truncated_body
        self.truncated_rules = truncated_rules

    @classmethod
    def parse(cls, body: bytes | str | None) -> "Robots":
        if body is None:
            return ALLOW_ALL
        if isinstance(body, str):
            body = body.encode("utf-8", "surrogatepass")
        truncated = len(body) > MAX_BODY_OCTETS
        if truncated:
            head = body[:MAX_BODY_OCTETS]
            body = head[:max(head.rfind(b"\n"), head.rfind(b"\r")) + 1]
        if body.startswith(b"\xef\xbb\xbf"):
            body = body[3:]
        groups: list[_Group] = []
        cur: _Group | None = None
        cut = 0
        for line in _LINES.split(body):
            line = line.split(b"#", 1)[0].strip()
            if b":" not in line:
                continue
            field, value = line.split(b":", 1)
            field, value = field.strip().lower(), value.strip()
            if field == b"user-agent":
                if cur is None or cur.closed:
                    cur = _Group()
                    groups.append(cur)
                cur.agents.add(agent_token(value))
            elif field in (b"allow", b"disallow"):
                if cur is None:
                    continue  # a rule before any User-agent line
                cur.closed = True
                if not value:
                    continue  # an empty rule is ignored (it still closes the run of User-agent lines)
                allow = field == b"allow"
                if len(value) > MAX_PATTERN_OCTETS:
                    cut += 1
                    if allow:
                        continue  # fails closed
                    value = _cut_pattern(value)
                cur.rules.append(_Rule(allow, value))
            elif field == b"crawl-delay" and cur is not None:
                try:
                    d = float(value.decode("ascii"))
                except (UnicodeDecodeError, ValueError):
                    continue
                if d == d and d >= 0 and d != float("inf"):
                    cur.delay = d if cur.delay is None else max(cur.delay, d)
        return cls(groups, truncated_body=truncated, truncated_rules=cut)

    def _chosen(self, agent: str) -> list[_Group]:
        me = "*" if agent.strip() == "*" else agent_token(agent)
        ours = [g for g in self._groups if me in g.agents] if me else []
        return ours or [g for g in self._groups if "*" in g.agents]

    def allowed(self, url: str, agent: str, *, steps: Steps | None = None) -> bool:
        if self._everything is not None:
            return self._everything
        if urlsplit(url).path == "/robots.txt":
            return True
        rules = self._ordered.get(agent)
        if rules is None:
            # longest first, Allow before Disallow at the same length: the first match decides
            rules = sorted((r for g in self._chosen(agent) for r in g.rules), key=lambda r: (-r.length, not r.allow))
            self._ordered[agent] = rules
        if not rules:
            return True
        text = target(url)
        steps = steps if steps is not None else Steps()
        for r in rules:
            if _matches(r, text, steps):
                return r.allow
        return True

    def crawl_delay(self, agent: str) -> float | None:
        if self._everything is not None:
            return None
        delays = [g.delay for g in self._chosen(agent) if g.delay is not None]
        return max(delays) if delays else None


ALLOW_ALL = Robots(everything=True)
DISALLOW_ALL = Robots(everything=False)
