"""Checks for the name-free coach-bio diagnostics (issue #168, step 1).

    python tests/coach_bio_diag_test.py            # everything below, offline
    python tests/coach_bio_diag_test.py --verbose  # print every check

Offline: every bio page is built here from made-up names, handles, addresses and numbers; the one roster page is
the committed fixture tests/fixtures/sidearm/roster-players-and-staff.html, and collect.common.fetch_text is
replaced by a table, so no request is made. Files go to temporary directories outside the repository only.

Why this exists
---------------
462 published head coaches have a stored bio page from which coach_bio.first_season read no year, and the page
text is kept nowhere, so the cause (no year on the page, wording the parser does not read, or an extraction
miss) cannot be measured offline. collect/coach_bio_diag.py measures it on the Monday run from the page already
in memory. The checks follow the approved plan and Huatuo's review on #168:
  P1  default-deny masking; patterns only from 3+ programs; a leak test planting lower- and odd-case names,
      particles, a handle, URLs, an e-mail, four phone forms, a lower-case school and a rare word, with the
      contact scanner as a second net; three mutations (identity, the capital-letter rule, threshold 1) that
      must each fail it;
  P2  written only when COACH_BIO_DIAG_DIR is set, refused inside the repository; refresh.yml sets it under
      runner.temp, uploads one 14-day artifact in an always()/continue-on-error step, and its commit step
      refuses a staged diagnostics file (run for real in a scratch git repository);
  P3  the stored athletics data is byte-identical with diagnostics off, on and raising, with the same requests;
      patterns only from bios with no statement;
  P4  raw and extracted counts, strong and weak cues apart, and the first-fit classifier on three made-up pages
      (extraction, wording with a pronoun subject, no year stated);
  and Huatuo's build notes: the accumulator is exact under 8 threads, and the final write is one call from the
  refresh's main thread whose crash is one log line.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("COLLEGEDASH_OFFLINE", "1")

from collect import athletics_site, coach_bio, coach_bio_diag as diag, common  # noqa: E402
import camps_check  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "refresh.yml")


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {ascii(str(detail))[:300]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


class Env:
    """Set or unset COACH_BIO_DIAG_DIR (and silence common.log) for a block; restore afterwards."""

    def __init__(self, value: str | None, logs: list | None = None):
        self.value, self.logs = value, logs

    def __enter__(self):
        self.old = os.environ.get(diag.ENV)
        self.old_log = common.log
        if self.value is None:
            os.environ.pop(diag.ENV, None)
        else:
            os.environ[diag.ENV] = self.value
        common.log = (lambda m, *a, **k: self.logs.append(str(m))) if self.logs is not None else (lambda *a, **k: None)
        diag.reset()
        return self

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop(diag.ENV, None)
        else:
            os.environ[diag.ENV] = self.old
        common.log = self.old_log
        diag.reset()


def page(*paragraphs: str, related: str = "") -> str:
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    extra = f'<div class="related-stories"><p>{related}</p></div>' if related else ""
    return f"<html><head><title>Coach</title></head><body><main>{body}</main>{extra}</body></html>"


# ---------- P1: masking and the leak test ----------

# Every string planted here is made up. The sentences all carry a year, so each yields patterns.
LEAK_SENTENCES = [
    "jordan quill was named head coach of the women's soccer program in May 2019 by director mcKenzie deGrasse.",
    "She joined de la Vega and van der Berg on staff in 2018 after al-Rahim and Lee-Ortiz left.",
    "Follow @coachquill at x.com/coachquill or https://example.edu/staff/quill since 2020.",
    "Contact quill@example.edu, 555-010-4477, (555) 010-4477, 555.010.4477 or 5550104477 before the 2021 season.",
    "She coached at university of placeholderton in 2016, a zymurgical program.",
]
PLANTED = ["jordan quill", "quill", "mckenzie", "degrasse", "de la vega", "vega", "van der berg", "berg", "al-rahim",
           "rahim", "lee-ortiz", "ortiz", "@coachquill", "coachquill", "x.com", "example.edu", "https://",
           "quill@example.edu", "555-010-4477", "(555) 010-4477", "555.010.4477", "5550104477", "4477", "010",
           "placeholderton", "zymurgical", "jordan"]
# In one program only: with the real threshold its pattern must never be written.
UNIQUE_SENTENCE = "In 1999 the interim coach arrived."
ALLOWED_TOKENS = diag.ALLOW | diag.PLACEHOLDERS | diag.PUNCT


def run_leak_case(tmp: str) -> tuple[str, list[str], dict, dict]:
    """Observe the planted bios in three programs (plus the one-program sentence in a fourth), write the report,
    and return (all output text, log lines, per-program json, patterns json)."""
    out_dir = os.path.join(tmp, "diag")
    logs: list[str] = []
    with Env(out_dir, logs):
        for slug in ("leak-a", "leak-b", "leak-c"):
            diag.observe(slug, "D1", page(*LEAK_SENTENCES), "Jordan Quill", matched=False)
        diag.observe("leak-d", "D2", page(UNIQUE_SENTENCE), "Jordan Quill", matched=False)
        written = diag.write_report()
    per = json.load(open(os.path.join(written, diag.PER_PROGRAM_FILE), encoding="utf-8")) if written else {}
    pats = json.load(open(os.path.join(written, diag.PATTERNS_FILE), encoding="utf-8")) if written else {}
    text = json.dumps(per) + json.dumps(pats) + "\n".join(logs)
    return text, logs, per, pats


def leak_problems(text: str, per: dict, pats: dict) -> list[str]:
    problems = []
    low = text.lower()
    for s in PLANTED:
        if s in low:
            problems.append(f"planted string {s!r} in the output")
    for p in pats.get("patterns", []):
        bad = [t for t in p["pattern"].split() if t not in ALLOWED_TOKENS]
        if bad:
            problems.append(f"token(s) outside the allowlist in a pattern: {len(bad)}")
        if p["programs"] < diag.MIN_PROGRAMS_REQUIRED:
            problems.append("a pattern seen in fewer than 3 programs was written")
    unique = diag_patterns_real(UNIQUE_SENTENCE)
    if any(p["pattern"] in unique for p in pats.get("patterns", [])):
        problems.append("the one-program pattern was written")
    allowed_values = {"D1", "D2", "unknown", *diag.CLASSES, "leak-a", "leak-b", "leak-c", "leak-d"}
    for r in per.get("programs", []):
        for v in (r["slug"], r["division"], r["class"]):
            if v not in allowed_values:
                problems.append(f"unexpected string in a per-program record")
        for part in ("raw", "extracted"):
            if not all(isinstance(n, int) for n in r[part].values()):
                problems.append("a per-program count is not an integer")
    e, p = camps_check.contact_hits(text)
    if e or p:
        problems.append(f"contact scanner: {len(e)} e-mail, {len(p)} phone")
    return problems


_REAL_MASK = diag.mask_token
diag.MIN_PROGRAMS_REQUIRED = 3  # what the output must honour, whatever MIN_PROGRAMS a mutation sets


def diag_patterns_real(sentence: str) -> set[str]:
    saved = diag.mask_token
    diag.mask_token = _REAL_MASK
    try:
        return diag.patterns(sentence)
    finally:
        diag.mask_token = saved


def test_masking() -> None:
    print("P1 masking: default deny")
    ok("CONTROL a pronoun hire sentence keeps its allowlisted words and masks the year",
       diag.patterns("She was named head coach in May 2019.") == {"she was named head coach in may YYYY ."},
       diag.patterns("She was named head coach in May 2019."))
    ok("FIX a lower-case name is X, not itself", diag.masked("jordan quill was named") == ["X", "was", "named"],
       diag.masked("jordan quill was named"))
    ok("FIX odd case, particles and hyphenated names are X",
       set(diag.masked("mcKenzie deGrasse de la Vega van der Berg al-Rahim Lee-Ortiz")) <= {"X", "-"},
       diag.masked("mcKenzie deGrasse de la Vega van der Berg al-Rahim Lee-Ortiz"))
    m = diag.masked("@coachquill x.com/coachquill https://example.edu/staff/quill quill@example.edu")
    ok("FIX a handle, a URL and an e-mail keep only allowlisted words (a path's 'staff') and punctuation",
       set(m) <= ALLOWED_TOKENS and not {"coachquill", "@coachquill", "quill", "example", "edu", "com", "https"} & set(m), m)
    ok("FIX phone numbers keep no digit", not any(re.search(r"\d", t) for t in
                                                  diag.masked("555-010-4477 (555) 010-4477 555.010.4477 5550104477")),
       diag.masked("555-010-4477 (555) 010-4477 555.010.4477 5550104477"))
    ok("FIX ordinals are NTH and years YYYY", diag.masked("her 12th season, twelfth year, 2026") ==
       ["her", "NTH", "season", ",", "NTH", "year", ",", "YYYY"], diag.masked("her 12th season, twelfth year, 2026"))
    ok("CONTROL runs of X collapse", diag.masked("Pat Quill Smith joined") == ["X", "joined"], diag.masked("Pat Quill Smith joined"))
    ok("CONTROL a window is at most 8 tokens either side of the year",
       all(len(p.split()) <= 2 * diag.WINDOW + 1 for p in diag.patterns(" ".join(["the"] * 30) + " 2019 " + " ".join(["the"] * 30))))


def test_leak() -> None:
    print("P1 leak test (#390 style)")
    with tempfile.TemporaryDirectory() as tmp:
        text, logs, per, pats = run_leak_case(tmp)
    problems = leak_problems(text, per, pats)
    ok("FIX nothing planted, and no token outside the allowlist, reaches the artifact or the log", not problems, problems)
    ok("CONTROL the planted sentences, seen in 3 programs, do produce patterns (the test is not vacuous)",
       len(pats.get("patterns", [])) >= 3, pats)
    ok("CONTROL the log holds division counts only", logs and all(l.startswith("coach-bio diag D") for l in logs), logs)
    e, p = camps_check.contact_hits(text)
    ok("CONTROL contact scanner finds nothing", not e and not p, e + p)


def test_leak_mutations() -> None:
    print("P1 mutations: each must fail the leak test")
    cases = {
        # years are still found, so the windows form and the words around them are emitted as written
        "identity masking": (lambda t: "YYYY" if re.fullmatch(r"(?:19|20)\d\d", t) else t, None),
        "the capital-letter rule": (lambda t: "YYYY" if re.fullmatch(r"(?:19|20)\d\d", t) else ("X" if t[:1].isupper() else t.lower()), None),
        "threshold 1": (None, 1),
    }
    for label, (mask, threshold) in cases.items():
        saved_mask, saved_min = diag.mask_token, diag.MIN_PROGRAMS
        if mask:
            diag.mask_token = mask
        if threshold:
            diag.MIN_PROGRAMS = threshold
        try:
            with tempfile.TemporaryDirectory() as tmp:
                text, _, per, pats = run_leak_case(tmp)
            problems = leak_problems(text, per, pats)
        finally:
            diag.mask_token, diag.MIN_PROGRAMS = saved_mask, saved_min
        ok(f"FIX mutation '{label}' fails the leak test", bool(problems), "the mutated code passed")


def test_threshold() -> None:
    print("P1 recurrence threshold")
    with tempfile.TemporaryDirectory() as tmp, Env(os.path.join(tmp, "d")):
        for slug in ("t-a", "t-b"):
            diag.observe(slug, "D3", page("She was hired as head coach in 2015."), "Pat Quill", matched=False)
        two = [p["pattern"] for p in diag.snapshot()[1]]
        diag.observe("t-c", "D3", page("She was hired as head coach in 2015."), "Pat Quill", matched=False)
        three = diag.snapshot()[1]
    ok("FIX a pattern seen in 2 programs is not written", two == [], two)
    ok("CONTROL a pattern seen in 3 programs is written, with its count and no program names",
       three == [{"pattern": "she was hired as head coach in YYYY .", "programs": 3}], three)


# ---------- P2: output location ----------

def test_location() -> None:
    print("P2 output location")
    with Env(None):
        diag.observe("loc-a", "D1", page("She was named head coach in 2019."), "Pat Quill", matched=False)
        ok("FIX nothing is observed or written when COACH_BIO_DIAG_DIR is unset",
           diag.snapshot() == ([], []) and diag.write_report() is None)
    inside = os.path.join(ROOT, "tests", "coach-bio-diag-must-not-exist")
    logs: list[str] = []
    with Env(inside, logs):
        diag.observe("loc-a", "D1", page("She was named head coach in 2019."), "Pat Quill", matched=False)
        r = diag.write_report()
    created = os.path.exists(inside)
    if created:
        shutil.rmtree(inside)  # only the path this test named, and only if the code under test made it
    ok("FIX a directory inside the repository is refused: nothing written, one log line",
       r is None and not created and len(logs) == 1 and "inside the repository" in logs[0], (r, created, logs))
    with tempfile.TemporaryDirectory() as tmp, Env(os.path.join(tmp, "out")):
        diag.observe("loc-a", "D1", page("She was named head coach in 2019."), "Pat Quill", matched=False)
        r = diag.write_report()
        files = sorted(os.listdir(r)) if r else []
    ok("CONTROL outside the repository both files are written", files == sorted([diag.PER_PROGRAM_FILE, diag.PATTERNS_FILE]), files)


def _steps(yml: str) -> dict[str, str]:
    parts = re.split(r"\n      - name: ", yml)
    return {p.split("\n", 1)[0].strip(): p for p in parts[1:]}


def test_workflow() -> None:
    print("P2 refresh.yml")
    yml = open(WORKFLOW, encoding="utf-8").read().replace("\r\n", "\n")
    steps = _steps(yml)
    refresh, upload, commit = steps.get("Refresh data", ""), steps.get("Upload coach-bio diagnostics", ""), steps.get("Commit changed data", "")
    ok("FIX the refresh step sets COACH_BIO_DIAG_DIR under runner.temp",
       "COACH_BIO_DIAG_DIR: ${{ runner.temp }}/coach-bio-diag\n" in refresh, refresh[:200])
    ok("FIX COACH_BIO_DIAG_DIR is set nowhere else in the workflows",
       yml.count("COACH_BIO_DIAG_DIR") == 1 and not any(
           "COACH_BIO_DIAG_DIR" in open(os.path.join(ROOT, ".github", "workflows", f), encoding="utf-8").read()
           for f in os.listdir(os.path.join(ROOT, ".github", "workflows")) if f != "refresh.yml"))
    ok("FIX one upload step: upload-artifact, always(), continue-on-error, 14 days, the runner.temp directory",
       all(s in upload for s in ("if: always()\n", "continue-on-error: true\n", "uses: actions/upload-artifact@v4\n",
                                 "retention-days: 14\n", "path: ${{ runner.temp }}/coach-bio-diag/\n",
                                 "if-no-files-found: ignore\n")) and yml.count("upload-artifact") == 1, upload[:400])
    order = [yml.find("\n      - name: Refresh data"), yml.find("\n      - name: Upload coach-bio diagnostics"),
             yml.find("\n      - name: Commit changed data")]
    ok("FIX the upload step runs after the refresh step and before the commit step", -1 not in order and order == sorted(order), order)
    guard = re.search(r"\n( +)if git diff --cached --name-only \| grep -q 'coach-bio-diag'; then\n.*?\n\1fi\n", commit, re.S)
    first_commit = commit.find('git commit -m "data: $verb $stamp"')
    ok("FIX the commit step's guard stands between `git add -A` and the first commit",
       bool(guard) and commit.find("git add -A") < guard.start() < first_commit, commit[:300])
    if not guard or not shutil.which("bash") or not shutil.which("git"):
        ok("the commit guard ran in a scratch repository", False, "guard not found, or no bash/git on PATH")
        return
    snippet = "\n".join(l.strip() for l in guard.group(0).strip().splitlines())
    for label, path, want in (("a staged diagnostics file", "tmp/coach-bio-diag/per-program.json", 1),
                              ("an ordinary data change", "programs/x/sources/athletics.json", 0)):
        with tempfile.TemporaryDirectory() as repo:
            env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": repo}
            subprocess.run(["git", "init", "-q", repo], check=True, env=env)
            os.makedirs(os.path.join(repo, os.path.dirname(path)), exist_ok=True)
            open(os.path.join(repo, path), "w").write("{}")
            subprocess.run(["git", "-C", repo, "add", "-A"], check=True, env=env)
            r = subprocess.run(["bash", "-e", "-c", snippet], cwd=repo, env=env, capture_output=True, text=True)
        ok(f"{'FIX' if want else 'CONTROL'} the guard exits {want} for {label}", r.returncode == want, (r.returncode, r.stdout[-200:]))


# ---------- P3: the hook cannot change the stored data ----------

BASE = "https://example.invalid"
SPORT = "/sports/womens-soccer"
BIO_URL = BASE + SPORT + "/roster/coaches/tracy--chao/2425"
REGISTRY = {"season": {"current": 2026}, "sources": {"athleticsPlatforms": {"sidearm": {
    "roster": "{baseUrl}{sportPath}/roster", "rosterSeason": "{baseUrl}{sportPath}/roster/{year}",
    "schedule": "{baseUrl}{sportPath}/schedule", "scheduleSeason": "{baseUrl}{sportPath}/schedule/{year}",
    "news": "{baseUrl}{sportPath}/archives", "rss": "{baseUrl}/rss?path=wsoc"}}}}
PROGRAM = {"slug": "fixture", "division": "D1", "name": "Example Test University", "shortName": "ETU",
           "nickname": "Testers", "athletics": {"platform": "sidearm", "baseUrl": BASE, "sportPath": SPORT}}


def collect_once(bio_html: str, mode: str, tmp: str) -> tuple[str, list, list[str], tuple]:
    """athletics_site.collect with the fetch table; mode is off, on or raising. Returns (stored data as sorted
    JSON, requests, log lines, the diagnostics snapshot)."""
    roster = open(os.path.join(ROOT, "tests", "fixtures", "sidearm", "roster-players-and-staff.html"), encoding="utf-8").read()
    pages = {BASE + SPORT + "/roster": roster, BASE + SPORT + "/schedule": "<html></html>", BIO_URL: bio_html}
    saved, requests, logs = {}, [], []

    def fetch_text(url, **kw):
        requests.append(url)
        if url not in pages:
            raise common.FetchError(f"HTTP 404 for {url}")
        return pages[url], {"url": url, "status": 200, "finalUrl": url, "fromCache": False}

    def save_source(slug, name, data, *, url, collector, extra=None):
        saved.update(copy.deepcopy(data))

    def boom(*a, **k):
        raise RuntimeError("diagnostics failed on purpose")

    real = (common.fetch_text, common.save_source, diag.observe)
    with Env(None if mode == "off" else os.path.join(tmp, mode), logs):
        common.fetch_text, common.save_source = fetch_text, save_source
        if mode == "raising":
            diag.observe = boom
        try:
            athletics_site.collect(PROGRAM, REGISTRY, seasons_back=0, bios=False, coach_bios=True)
            snap = diag.snapshot()
        finally:
            common.fetch_text, common.save_source, diag.observe = real
    return json.dumps(saved, sort_keys=True), requests, logs, snap


def test_hook_byte_identical() -> None:
    print("P3 the stored data is byte-identical with diagnostics off, on and raising")
    unmatched = page("Tracy Chao leads the Testers.", "She was named head coach of the program in May 2019.")
    matched = page("Tracy Chao was named head coach at Example Test University on Feb. 12, 2026.")
    with tempfile.TemporaryDirectory() as tmp:
        for label, bio in (("a bio with no statement", unmatched), ("a bio the parser reads", matched)):
            off, on, bad = (collect_once(bio, m, tmp) for m in ("off", "on", "raising"))
            hb = json.loads(off[0]).get("headCoachBio") or {}
            ok(f"CONTROL {label}: the head coach's bio was read", hb.get("url") == BIO_URL, str(hb)[:200])
            ok(f"FIX {label}: athletics data identical off vs on", off[0] == on[0])
            ok(f"FIX {label}: athletics data identical off vs raising", off[0] == bad[0])
            ok(f"FIX {label}: the same requests in all three modes, and none outside the table",
               off[1] == on[1] == bad[1] and all(u.startswith(BASE) for u in off[1]), (off[1], on[1], bad[1]))
            ok(f"FIX {label}: the raising hook costs one log line", sum("coach-bio diag failed: RuntimeError" in l for l in bad[2]) == 1,
               [l for l in bad[2] if "diag" in l])
            records, pats = on[3]
            want_matched = bio is matched
            ok(f"FIX {label}: recorded once, matched={want_matched}",
               len(records) == 1 and records[0]["slug"] == "fixture" and records[0]["matched"] is want_matched, records)
            ok(f"CONTROL {label}: nothing recorded when off", off[3] == ([], []), off[3])


def test_hook_patterns_only_unmatched() -> None:
    print("P3 patterns only from bios with no statement")
    with tempfile.TemporaryDirectory() as tmp, Env(os.path.join(tmp, "d")):
        for s in ("m-a", "m-b", "m-c"):
            diag.observe(s, "D1", page("She was named head coach in May 2019."), "Pat Quill", matched=True)
        ok("FIX matched bios in 3 programs leave no pattern at all", not diag._patterns and diag.snapshot()[1] == [])
        ok("CONTROL ... but are recorded as control counts", len(diag.snapshot()[0]) == 3)


# ---------- P4: counts and classes ----------

def test_classes() -> None:
    print("P4 counts and the first-fit classifier")
    cases = {
        "extraction": page("Pat Quill leads the Testers.", related="Pat Quill was named head coach of the program in May 2019."),
        "wording": page("Pat Quill leads the Testers.", "She was named head coach of the program in May 2019."),
        "no year stated": page("Pat Quill leads the Testers.", "She played in college and loves the game."),
    }
    with tempfile.TemporaryDirectory() as tmp, Env(os.path.join(tmp, "d")):
        for want, html in cases.items():
            parsed = coach_bio.first_season(html, "Pat Quill", ["Example Test University"])
            ok(f"CONTROL the '{want}' page gives the parser no statement", not parsed["statements"], parsed)
            diag.observe(f"c-{want.replace(' ', '-')}", "D2", html, "Pat Quill", matched=False)
        records = {r["slug"]: r for r in diag.snapshot()[0]}
    for want in cases:
        r = records.get(f"c-{want.replace(' ', '-')}", {})
        ok(f"FIX the '{want}' page is classed '{want}'", r.get("class") == want, r)
    w = records.get("c-wording", {})
    ok("FIX a pronoun sentence counts as year + strong cue whatever its subject",
       w.get("extracted", {}).get("yearStrongCue") == 1 and w.get("extracted", {}).get("surnameWithYear") == 0, w)
    ok("FIX 'head coach' sentences are counted, with and without a year",
       w.get("extracted", {}).get("headCoach") == 1 and w.get("extracted", {}).get("headCoachWithYear") == 1, w)
    e = records.get("c-extraction", {})
    ok("FIX raw text counts what the extracted text lacks",
       e.get("raw", {}).get("yearStrongCue") == 1 and e.get("extracted", {}).get("yearStrongCue") == 0, e)
    weak = diag.counts("The Testers won 12 games in the 2019 season.", "Quill")
    ok("FIX a season-result sentence is a weak cue only, not wording evidence",
       weak["yearStrongCue"] == 0 and weak["yearWeakCueOnly"] == 1, weak)
    lines = diag.summary_lines(list(records.values()))
    ok("CONTROL the summary line is division counts only",
       lines == ["coach-bio diag D2: unmatched 3 (extraction 1, wording 1, no year stated 1); control 0 (extraction 0, wording 0, no year stated 0)"], lines)


# ---------- build notes: threads and the one final write ----------

def test_threads() -> None:
    print("build note 1: the accumulator is exact under 8 threads")
    n_threads, per_thread = 8, 25
    bio = page("Pat Quill leads the Testers.", "She was named head coach of the program in May 2019.")
    with tempfile.TemporaryDirectory() as tmp, Env(os.path.join(tmp, "d")):
        barrier = threading.Barrier(n_threads)

        def work(t: int) -> None:
            barrier.wait()
            for i in range(per_thread):
                diag.observe(f"th-{t}-{i}", ("D1", "D2", "D3")[i % 3], bio, "Pat Quill", matched=(i % 5 == 0))

        threads = [threading.Thread(target=work, args=(t,)) for t in range(n_threads)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        records, pats = diag.snapshot()
    total = n_threads * per_thread
    unmatched = sum(1 for t in range(n_threads) for i in range(per_thread) if i % 5)
    ok("FIX every program is recorded exactly once", len(records) == total and len({r["slug"] for r in records}) == total, len(records))
    shared = diag.patterns("She was named head coach of the program in May 2019.")
    ok("FIX the shared pattern counts every unmatched program exactly",
       len(shared) == 1 and pats == [{"pattern": shared.pop(), "programs": unmatched}], pats)
    div = diag.division_counts(records)
    ok("FIX division counts add up to the programs observed",
       sum(sum(d["unmatched"].values()) + sum(d["control"].values()) for d in div.values()) == total
       and sum(sum(d["unmatched"].values()) for d in div.values()) == unmatched, div)


def test_final_write() -> None:
    print("build note 2: one final write, from the refresh's main thread")
    import collegedash  # noqa: E402
    src = open(os.path.join(ROOT, "collegedash.py"), encoding="utf-8").read()
    body = src[src.index("def cmd_refresh("):]
    body = body[:body.index("\ndef ", 1)]
    after = body[body.index("results += collect_plan("):]
    ok("FIX cmd_refresh calls write_coach_bio_diag() once, straight after the collector threads finish",
       body.count("write_coach_bio_diag()") == 1 and after.index("write_coach_bio_diag()") < after.index("import build"))
    ok("CONTROL nothing else writes the report", src.count("write_report(") == 1 and
       sum(open(os.path.join(ROOT, "collect", f), encoding="utf-8").read().count("write_report(")
           for f in os.listdir(os.path.join(ROOT, "collect")) if f.endswith(".py") and f != "coach_bio_diag.py") == 0)
    logs: list[str] = []
    real = diag.write_report
    with tempfile.TemporaryDirectory() as tmp, Env(os.path.join(tmp, "d"), logs):
        diag.write_report = lambda: (_ for _ in ()).throw(OSError("disk full on purpose"))
        try:
            raised = None
            try:
                collegedash.write_coach_bio_diag()
            except Exception as e:  # noqa: BLE001
                raised = e
        finally:
            diag.write_report = real
    ok("FIX a crash in the write is one log line and does not propagate",
       raised is None and logs == ["!! coach-bio diag write failed: OSError"], (raised, logs))
    with Env(None, logs := []):
        collegedash.write_coach_bio_diag()
    ok("CONTROL with the env var unset the write is skipped silently", logs == [], logs)


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    VERBOSE = ap.parse_args(argv).verbose
    for case in (test_masking, test_leak, test_leak_mutations, test_threshold, test_location, test_workflow,
                 test_hook_byte_identical, test_hook_patterns_only_unmatched, test_classes, test_threads, test_final_write):
        try:
            case()
        except Exception as e:  # a case that raises is a failed case, not a lost run
            ok(f"{case.__name__} ran to the end", False, f"{type(e).__name__}: {e}")
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
