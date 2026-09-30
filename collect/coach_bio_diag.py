"""
Name-free diagnostics for head-coach bio pages the parser reads no year from (issue #168, step 1).

Measurement only: nothing here changes what is collected, stored or published. On the Monday weekly and the
`full` runs, athletics_site._head_coach_bio hands every fetched bio page to observe() after coach_bio has
read it, on the HTML already in memory (no request). At the end of `collegedash.py refresh` the main thread
calls write_report() once, which writes two files to COACH_BIO_DIAG_DIR (refresh.yml: under runner.temp,
uploaded as a 14-day artifact, never committed) and logs division-level counts only.

Why: 462 published head coaches have a stored bio from which coach_bio.first_season read nothing, and the
page text is not stored anywhere. Three causes need three different fixes - the page states no start year,
it states one in wording the parser does not read, or bio_text() misses the bio on some page template - and
the counts below tell them apart (the plan and its review are on #168).

Privacy (Huatuo's review, P1). Run logs and artifacts of a public repository are readable by anyone, so:
  - a masked pattern is DEFAULT-DENY: a word survives only when its lower-cased form is exactly in ALLOW;
    years become YYYY, ordinals NTH, other all-digit tokens N, and every other token X, whatever its case or
    characters (names in any case, particles, handles, URLs, e-mail, phone numbers, rare words);
  - patterns come only from bios with no statement, as windows of at most WINDOW tokens either side of a
    year, and a pattern is written only when MIN_PROGRAMS or more different programs produce it (TOP at
    most), with the number of programs and never which ones;
  - per-program numbers (keyed by the public slug) go to the artifact only; the log gets division totals.
"""

from __future__ import annotations

import json
import os
import re
import threading

from bs4 import BeautifulSoup

from . import coach_bio, common

ENV = "COACH_BIO_DIAG_DIR"
MIN_PROGRAMS = 3
TOP = 200
WINDOW = 8
PER_PROGRAM_FILE = "per-program.json"
PATTERNS_FILE = "patterns.json"

_FUNCTION_WORDS = """
a an the of in on at to for with as by from and or but nor so than then that this these those which who whom
whose it its he she they him her his their them we our you your i me my is are was were be been being has have
had do does did will would shall should can could may might must not no into onto upon over under after before
prior since during until through throughout while when where about around across along ahead behind between
beyond following following toward towards within without also again still just only even both each every all
any some most more first last next new current former previous now there here what how why up down out off per
""".split()
_CUE_WORDS = """
named name hired hire hiring appointed appointment announced announcement introduced introduces joined joins join
promoted elevated tabbed became become becomes took take takes taking arrived arrives arrival enters enter entered
entering begins begin began beginning starts start started starting embarks embarked returns returned return
tenure helm helmed helms led leads leading guided guides guiding completed concluded finished marks mark marked
effective present date through
""".split()
_MONTHS = """
january february march april may june july august september october november december
jan feb mar apr jun jul aug sep sept oct nov dec
""".split()
_SOCCER_JOB_WORDS = """
head coach coaches coached coaching assistant associate interim co acting permanent women's womens men's
soccer program programs team teams staff squad season seasons year years campaign campaigns fall spring era
university college school athletics athletic department director
""".split()
ALLOW = frozenset(_FUNCTION_WORDS + _CUE_WORDS + _MONTHS + _SOCCER_JOB_WORDS)
ORDINAL_WORDS = frozenset(coach_bio._ORDINALS)
PUNCT = frozenset('.,;:()"“”!?-–—/')
PLACEHOLDERS = frozenset({"X", "YYYY", "NTH", "N"})

_TOKEN_RE = re.compile(r'[^\s.,;:()"“”!?\-–—/]+|[.,;:()"“”!?\-–—/]')
_YEAR_RE = re.compile(r"\b(?:19|20)\d\d\b")
_STRONG_CUE_RE = re.compile(
    r"\b(?:named|hired|hiring|appointed|joined|took\s+over|taking\s+over|arrived|since|enter(?:s|ed|ing)?|"
    r"begin(?:s|ning)?|began|tenure|helm(?:ed)?)\b"
    r"|\b(?:\d{1,2}(?:st|nd|rd|th)|" + "|".join(sorted(ORDINAL_WORDS)) + r")\s+(?:season|year)\b", re.I)
_WEAK_CUE_RE = re.compile(r"\b(?:seasons?|years?|campaigns?)\b", re.I)
_HEAD_COACH_RE = re.compile(r"\bhead\s+(?:women['’]?s\s+)?(?:soccer\s+)?coach", re.I)

# The classifier's thresholds (P4). The control group (bios that did yield a statement) is classified the same
# way, so a threshold that is wrong shows up there as matched bios landing outside "wording".
TINY_EXTRACT_CHARS = 300
LARGE_RAW_CHARS = 1500
CLASSES = ("extraction", "wording", "no year stated")

_lock = threading.Lock()
_records: dict[str, dict] = {}
_patterns: dict[str, set[str]] = {}


def enabled() -> bool:
    return bool(os.environ.get(ENV))


def reset() -> None:
    with _lock:
        _records.clear()
        _patterns.clear()


def raw_text(html: str) -> str:
    """All of the page's visible text: only script, style, noscript and template removed (not nav or sidebars,
    which bio_text drops). The difference between the two is what an extraction miss looks like."""
    soup = BeautifulSoup(html or "", "html.parser")
    for t in soup(("script", "style", "noscript", "template")):
        t.decompose()
    lines = (common.clean(line) for line in soup.get_text("\n").split("\n"))
    return "\n".join(line for line in lines if line)


def counts(text: str, surname: str) -> dict:
    """Integers only. A year+cue sentence is counted whatever its subject, so a pronoun sentence ("She was
    named head coach in 2019") counts as wording, not as a page with no year."""
    sents = coach_bio.sentences(text)
    sur = re.compile(rf"\b{re.escape(surname)}\b", re.I) if surname else None
    strong = weak = hc = hc_year = sur_n = sur_year = 0
    for s in sents:
        has_year = bool(_YEAR_RE.search(s))
        if has_year and _STRONG_CUE_RE.search(s):
            strong += 1
        elif has_year and _WEAK_CUE_RE.search(s):
            weak += 1
        if _HEAD_COACH_RE.search(s):
            hc += 1
            hc_year += has_year
        if sur and sur.search(s):
            sur_n += 1
            sur_year += has_year
    return {"chars": len(text), "years": len(_YEAR_RE.findall(text)), "sentences": len(sents),
            "yearStrongCue": strong, "yearWeakCueOnly": weak, "headCoach": hc, "headCoachWithYear": hc_year,
            "surname": sur_n, "surnameWithYear": sur_year}


def classify(raw: dict, ext: dict) -> str:
    """First rule that fits: extraction, then wording, then no year stated."""
    if (raw["yearStrongCue"] and not ext["yearStrongCue"]) or (raw["surname"] and not ext["surname"]) \
            or (ext["chars"] < TINY_EXTRACT_CHARS and raw["chars"] > LARGE_RAW_CHARS):
        return "extraction"
    if ext["yearStrongCue"]:
        return "wording"
    return "no year stated"


def mask_token(tok: str) -> str:
    """Default deny: a token is itself only when it is punctuation or exactly in ALLOW (lower-cased)."""
    if tok in PUNCT:
        return tok
    if re.fullmatch(r"(?:19|20)\d\d", tok):
        return "YYYY"
    low = tok.lower().replace("’", "'")
    if re.fullmatch(r"\d{1,3}(?:st|nd|rd|th)", low) or low in ORDINAL_WORDS:
        return "NTH"
    if tok.isascii() and tok.isdigit():
        return "N"
    return low if low in ALLOW else "X"


def masked(sentence: str) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN_RE.findall(sentence):
        m = mask_token(tok)
        if m == "X" and out and out[-1] == "X":
            continue  # runs of X collapse to one
        out.append(m)
    return out


def patterns(sentence: str) -> set[str]:
    """Masked windows of at most WINDOW tokens either side of each year in one sentence."""
    toks = masked(sentence)
    found = set()
    for i, t in enumerate(toks):
        if t == "YYYY":
            window = toks[max(0, i - WINDOW): i + WINDOW + 1]
            collapsed = [w for k, w in enumerate(window) if not (w == "X" and k and window[k - 1] == "X")]
            found.add(" ".join(collapsed))
    return found


def observe(slug: str, division: str | None, html: str, name: str, matched: bool) -> None:
    """Record one fetched bio. Called from collector threads: everything is computed first, and the shared
    state is touched only under the lock. Takes plain values, never the bio dict the collector returns."""
    if not enabled() or not slug:
        return
    surname = coach_bio._surname(name)
    raw_t, ext_t = raw_text(html), coach_bio.bio_text(html)
    raw, ext = counts(raw_t, surname), counts(ext_t, surname)
    record = {"slug": slug, "division": division or "unknown", "matched": bool(matched),
              "class": classify(raw, ext), "raw": raw, "extracted": ext}
    found: set[str] = set()
    if not matched:  # the control group contributes numbers only, never its sentences
        for s in coach_bio.sentences(ext_t):
            if _YEAR_RE.search(s):
                found |= patterns(s)
    with _lock:
        _records[slug] = record
        for p in found:
            _patterns.setdefault(p, set()).add(slug)


def snapshot() -> tuple[list[dict], list[dict]]:
    """(per-program records, recurring patterns) as they would be written."""
    with _lock:
        records = [dict(r) for r in _records.values()]
        pats = [(p, len(s)) for p, s in _patterns.items() if len(s) >= MIN_PROGRAMS]
    records.sort(key=lambda r: r["slug"])
    pats.sort(key=lambda x: (-x[1], x[0]))
    return records, [{"pattern": p, "programs": n} for p, n in pats[:TOP]]


def division_counts(records: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in records:
        d = out.setdefault(r["division"], {"unmatched": dict.fromkeys(CLASSES, 0), "control": dict.fromkeys(CLASSES, 0)})
        d["control" if r["matched"] else "unmatched"][r["class"]] += 1
    return dict(sorted(out.items()))


def summary_lines(records: list[dict]) -> list[str]:
    lines = []
    for div, d in division_counts(records).items():
        u, c = d["unmatched"], d["control"]
        lines.append(f"coach-bio diag {div}: unmatched {sum(u.values())} (extraction {u['extraction']}, wording "
                     f"{u['wording']}, no year stated {u['no year stated']}); control {sum(c.values())} (extraction "
                     f"{c['extraction']}, wording {c['wording']}, no year stated {c['no year stated']})")
    return lines


def _inside_repo(path: str) -> bool:
    root = os.path.realpath(common.ROOT)
    try:
        return os.path.commonpath([os.path.realpath(path), root]) == root
    except ValueError:  # another drive (Windows): not inside
        return False


def write_report() -> str | None:
    """Write the two files once, from the main thread, at the end of the refresh. Nothing when COACH_BIO_DIAG_DIR
    is unset, and nothing (one log line) when it points inside the repository, whose commit step runs
    `git add -A`. Returns the directory written, or None."""
    out = os.environ.get(ENV)
    if not out:
        return None
    if _inside_repo(out):
        common.log(f"coach-bio diag: {ENV} is inside the repository; nothing written (issue #168)")
        return None
    records, pats = snapshot()
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, PER_PROGRAM_FILE), "w", encoding="utf-8") as f:
        json.dump({"issue": 168, "minPrograms": MIN_PROGRAMS, "programs": records}, f, indent=1)
    with open(os.path.join(out, PATTERNS_FILE), "w", encoding="utf-8") as f:
        json.dump({"issue": 168, "minPrograms": MIN_PROGRAMS, "window": WINDOW, "patterns": pats}, f, indent=1)
    lines = summary_lines(records)
    for line in lines:
        common.log(line)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY") if os.environ.get("GITHUB_ACTIONS") else None
    if summary_path and lines:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("## Coach bio diagnostics (issue #168)\n\n" + "\n".join(f"- {l}" for l in lines) + "\n\n")
    return out
