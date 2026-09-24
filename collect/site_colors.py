"""Team colours from each program's own Sidearm athletics site (issue #276, part B).

    python collegedash.py registry colors --source site            # dry run: fetch, decide, write the report
    python collegedash.py registry colors --source site --apply    # write the reviewed report's colours
    python collect/site_colors.py --truth-table                    # rebuild the D1 agreement table, offline

The dry run fetches one page per target program (`athletics.baseUrl + sportPath`), reads the site's own
theme colours from it and writes `data/colors-site-report.json`: slugs, hosts, hex values and outcomes,
never page content. It does not touch the registry. `--apply` fetches nothing: it writes the accepted
colours exactly as the committed report has them, after a Reviewer's verdict on that report (#276), and
sets `colorsSource: "athletics-site"`. Existing colours are never overwritten.

Politeness: robots.txt is checked before every page request and again on the final host when a redirect
leaves the requested host; a host that answers 403 or 429 is stopped for the rest of the run, keyed on the
requested and the final host. Requests carry the CollegeDashBot User-Agent and go one host at a time,
under common's per-host gate plus HOST_PAUSE between live requests.

Where the colours are, on the two Sidearm templates:
  classic  inline config `primary_background` / `secondary_background`; `<meta name="theme-color">` is a
           cross-check, and a page whose theme-color differs from primary_background is left empty
  nuxt     `<script id="__NUXT_DATA__">`: the object holding `siteColorPrimaryBackground` /
           `siteColorSecondaryBackground`, whose values are indices into the same payload array
"""

from __future__ import annotations

import argparse
import colorsys
import json
import os
import random
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

if __package__ in (None, ""):  # run as a script: python collect/site_colors.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from collect import common
else:
    from . import common

SOURCE = "athletics-site"
REPORT_PATH = os.path.join(common.ROOT, "data", "colors-site-report.json")
TRUTH_PATH = os.path.join(common.ROOT, "tests", "fixtures", "colors_site_truth.json")

DENYLIST = {("#FFFFFF", "#FFFFFF")}  # an unconfigured Sidearm theme (george-fox in the probe)
GUARD_HOSTS = 3                      # a raw pair served by this many hosts may be a template default
SECONDARY_MIN_DE = 10                # a secondary this close to the primary adds nothing
AGREE_DE = 25                        # CIE76 distance counted as agreeing with a Wikipedia colour
MIN_ACCEPTED_D1 = 280                # of the D1 ground-truth rows (308), see agreement_failures
MIN_ALL_AGREE = 0.90
MIN_PRIMARY_AGREE = 0.95
HOST_PAUSE = 1.5
WORKERS = 8                          # distinct hosts fetched side by side; one host is never concurrent
MAX_AGE_HOURS = 24 * 30
SAMPLE_SEED, SAMPLE_N = 276, 20      # the report's random accepted-D3 sample
TRUTH_PAGES = ("/roster", "", "/schedule", "/coaches")
TRUTH_SAMPLE_N = 10                  # coloured D2/D3 programs fetched as live ground truth, never written

_HEX = re.compile(r"#?([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})")


def norm_hex(h) -> str | None:
    """'#abc' / '#aabbcc' (any case, '#' optional) -> '#AABBCC'; anything else -> None."""
    if not isinstance(h, str):
        return None
    m = _HEX.fullmatch(h.strip())
    if not m:
        return None
    v = m.group(1).upper()
    return "#" + (v if len(v) == 6 else "".join(c * 2 for c in v))


# ---------- extraction ----------

_NUXT = re.compile(r"<script[^>]*\bid=[\"']__NUXT_DATA__[\"'][^>]*>(.*?)</script>", re.S | re.I)
_THEME = re.compile(r"<meta[^>]+name=[\"']theme-color[\"'][^>]*content=[\"']([^\"']+)", re.I)
_PB = re.compile(r"primary_background[\"']?\s*[:=]\s*[\"'](#[0-9A-Fa-f]{3,6})[\"']")
_SB = re.compile(r"secondary_background[\"']?\s*[:=]\s*[\"'](#[0-9A-Fa-f]{3,6})[\"']")


def extract(html: str) -> tuple[str, dict | None]:
    """-> (template, {primary, secondary, theme}) or (template, None) when the page has no usable colours.
    template is 'nuxt', 'classic' or 'none'. Values are '#RRGGBB' or None; primary is never None."""
    html = html or ""
    m = _NUXT.search(html)
    if m:
        try:
            arr = json.loads(m.group(1))
        except ValueError:
            return "nuxt", None
        if not isinstance(arr, list):
            return "nuxt", None

        def resolve(i):  # a value is an index into the payload; out of range or not hex = nothing
            if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(arr):
                return None
            return norm_hex(arr[i])

        for o in arr:
            if isinstance(o, dict) and "siteColorPrimaryBackground" in o:
                primary = resolve(o.get("siteColorPrimaryBackground"))
                if not primary:
                    return "nuxt", None
                return "nuxt", {"primary": primary, "secondary": resolve(o.get("siteColorSecondaryBackground")),
                                "theme": None}
        return "nuxt", None
    pb = _PB.search(html)
    if not pb:
        return "none", None
    primary = norm_hex(pb.group(1))
    if not primary:
        return "classic", None
    sb, th = _SB.search(html), _THEME.search(html)
    return "classic", {"primary": primary, "secondary": norm_hex(sb.group(1)) if sb else None,
                       "theme": norm_hex(th.group(1)) if th else None}


# ---------- colour maths ----------

def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _lab(h: str) -> tuple[float, float, float]:
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = map(lin, _rgb(h))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def delta_e(a: str, b: str) -> float:
    """CIE76 distance between two hex colours (case-insensitive)."""
    return sum((p - q) ** 2 for p, q in zip(_lab(norm_hex(a)), _lab(norm_hex(b)))) ** 0.5


def category(h: str) -> str:
    """white (L > 0.93), black (L < 0.10), grey (saturation < 0.15), otherwise chromatic."""
    r, g, b = (v / 255 for v in _rgb(norm_hex(h)))
    _, light, sat = colorsys.rgb_to_hls(r, g, b)
    return "white" if light > 0.93 else "black" if light < 0.10 else "grey" if sat < 0.15 else "chromatic"


# ---------- the acceptance rule ----------

def _pair(rec: dict) -> tuple[str, str]:
    return norm_hex(rec["primary"]), norm_hex(rec.get("secondary")) or ""


def decide(template: str, primary: str, secondary: str | None, theme: str | None) -> tuple[list | None, str, list]:
    """One program's colours on their own: -> (colors or None, outcome, flags). The pair guard and the
    denylist look across programs and live in decide_all."""
    primary, secondary, theme = norm_hex(primary), norm_hex(secondary), norm_hex(theme)
    if template == "classic" and theme and theme != primary:
        return None, "rejected: theme-mismatch", []
    cp = category(primary)
    if cp in ("white", "grey"):
        return None, f"rejected: primary-{cp}", []
    cs = category(secondary) if secondary else None
    if cp == "black" and cs != "chromatic":
        return None, "rejected: black-without-chromatic-secondary", []
    colors, flags = [primary], []
    if cp == "black":
        flags.append("black-primary")
    if cs == "chromatic" and delta_e(primary, secondary) > SECONDARY_MIN_DE:
        colors.append(secondary)
    elif secondary:
        flags.append("secondary-dropped")
    return colors, "accepted", flags


def decide_all(records: list[dict], *, guard_hosts: int | None = GUARD_HOSTS) -> None:
    """Set colors/outcome/flags on every record that has an extracted primary, in place. A raw pair on the
    denylist, or served by `guard_hosts` or more distinct hosts in this set, is left empty whatever its
    colours (guard_hosts=None turns the host guard off: the agreement controls use that)."""
    hosts: dict[tuple, set] = {}
    for r in records:
        if r.get("primary"):
            hosts.setdefault(_pair(r), set()).add(r.get("host") or r["slug"])
    for r in records:
        if not r.get("primary"):
            continue
        pair = _pair(r)
        if pair in DENYLIST:
            r.update(colors=None, outcome="rejected: denylisted", flags=[])
        elif guard_hosts and len(hosts[pair]) >= guard_hosts:
            r.update(colors=None, outcome="rejected: template-guard", flags=[f"pair on {len(hosts[pair])} hosts"])
        else:
            colors, outcome, flags = decide(r.get("template"), r["primary"], r.get("secondary"), r.get("theme"))
            r.update(colors=colors, outcome=outcome, flags=flags)


# ---------- agreement with Wikipedia (the check the tests run) ----------

def agreement(rows: list[dict], *, guard_hosts: int | None = GUARD_HOSTS) -> dict:
    """rows: {slug, template, primary, secondary, theme, wikipedia}. Runs the whole rule and counts how many
    are accepted and how many accepted programs agree with Wikipedia (dE76 <= AGREE_DE against either
    Wikipedia colour; order ignored)."""
    recs = [dict(r) for r in rows]
    decide_all(recs, guard_hosts=guard_hosts)
    acc = [r for r in recs if r.get("outcome") == "accepted"]
    all_ok = prim_ok = 0
    for r in acc:
        near = [min(delta_e(c, w) for w in r["wikipedia"]) <= AGREE_DE for c in r["colors"]]
        all_ok += all(near)
        prim_ok += near[0]
    return {"rows": len(recs), "accepted": len(acc), "allAgree": all_ok, "primaryAgree": prim_ok}


def agreement_failures(stats: dict) -> list[str]:
    """Which clauses fail. Zero accepted fails every clause: it is never a 0/0 pass."""
    fails = []
    if stats["accepted"] < MIN_ACCEPTED_D1:
        fails.append("accepted-floor")
    a = stats["accepted"]
    if not a or stats["allAgree"] / a < MIN_ALL_AGREE:
        fails.append("all-agree")
    if not a or stats["primaryAgree"] / a < MIN_PRIMARY_AGREE:
        fails.append("primary-agree")
    return fails


# ---------- fetching ----------

def page_url(p: dict) -> str:
    a = p.get("athletics") or {}
    return a["baseUrl"].rstrip("/") + (a.get("sportPath") or "")


def fetch_site_page(p: dict, stopped: dict) -> dict:
    """Fetch one program's page under the robots and host-stop rules. `stopped` maps host -> status and is
    updated here. Returns a record: {slug, division, host, template, primary, secondary, theme, outcome,
    live}; outcome is None when colours were extracted (decide_all sets it), else a skip reason."""
    url = page_url(p)
    host = common._host(url)
    rec = {"slug": p["slug"], "division": p.get("division"), "host": host, "template": None,
           "primary": None, "secondary": None, "theme": None, "outcome": None, "live": False}
    if host in stopped:
        rec["outcome"] = f"skipped: host stopped ({stopped[host]})"
        return rec
    if not common.robots_allowed(url):
        rec["outcome"] = "skipped: robots"
        return rec
    try:
        html, meta = common.fetch_text(url, retries=1, timeout=30, max_age_hours=MAX_AGE_HOURS)
    except common.FetchError as e:
        rec["live"] = True
        status = getattr(e, "status", None)
        if status in (403, 429):
            for h in (host, common._host(getattr(e, "final_url", None) or url)):
                stopped.setdefault(h, status)
            rec["outcome"] = f"skipped: host stopped ({status})"
            rec["flags"] = ["refused"]
        else:
            rec["outcome"] = "failed: fetch" + (f" ({status})" if status else "")
        return rec
    rec["live"] = not meta.get("fromCache")
    final = meta.get("finalUrl") or url
    fhost = common._host(final)
    if fhost != host:
        rec["finalHost"] = fhost
        if fhost in stopped:
            rec["outcome"] = f"skipped: host stopped ({stopped[fhost]})"
            return rec
        if not common.robots_allowed(final):
            common.forget_cached(url)  # stored before the final host could be checked: do not keep it
            rec["outcome"] = "skipped: robots (redirect)"
            return rec
    template, c = extract(html)
    rec["template"] = template
    if not c:
        rec["outcome"] = "rejected: no-source"
        return rec
    rec.update(c)
    return rec


def _targets(registry: dict, slugs: list[str] | None) -> tuple[list, list, list]:
    """-> (to fetch, skipped for athletics.skipReason, coloured D2/D3 ground-truth sample)."""
    fetch, skip, coloured = [], [], []
    for p in registry["programs"]:
        a = p.get("athletics") or {}
        if not p.get("onboarded") or (slugs and p["slug"] not in slugs):
            continue
        if a.get("skipReason"):
            if not p.get("colors"):
                skip.append(p)
            continue
        if a.get("platform") != "sidearm" or not a.get("baseUrl"):
            continue
        if p.get("colors"):
            if p.get("division") in ("D2", "D3"):
                coloured.append(p)
        else:
            fetch.append(p)
    truth = [] if slugs else random.Random(SAMPLE_SEED).sample(
        sorted(coloured, key=lambda p: p["slug"]), min(TRUTH_SAMPLE_N, len(coloured)))
    return sorted(fetch, key=lambda p: p["slug"]), skip, truth


def _entry(r: dict) -> dict:
    keys = ("slug", "division", "host", "finalHost", "template", "primary", "secondary", "theme", "outcome",
            "colors", "flags")
    return {k: r[k] for k in keys if r.get(k) not in (None, [])}


def build_report(records: list[dict], skipped: list[dict], truth: list[dict]) -> dict:
    by_outcome = Counter(r["outcome"] for r in records)
    accepted = [r for r in records if r["outcome"] == "accepted"]
    d3 = sorted((r for r in accepted if r.get("division") == "D3"), key=lambda r: r["slug"])
    sample = random.Random(SAMPLE_SEED).sample(d3, min(SAMPLE_N, len(d3)))
    refused = sorted({r["host"] for r in records if "refused" in (r.get("flags") or [])})
    return {
        "issue": 276, "source": SOURCE, "generated": common.now_iso(),
        "rule": {"deltaE": "CIE76", "secondaryMinDeltaE": SECONDARY_MIN_DE, "guardHosts": GUARD_HOSTS,
                 "denylist": sorted("/".join(p) for p in DENYLIST), "sampleSeed": SAMPLE_SEED},
        "counts": {
            "targets": len(records), "accepted": len(accepted),
            "acceptedByDivision": dict(Counter(r["division"] for r in accepted)),
            "rejected": {k: v for k, v in sorted(by_outcome.items()) if k.startswith("rejected")},
            "skipped": {k: v for k, v in sorted(by_outcome.items()) if k.startswith("skipped")},
            "failed": {k: v for k, v in sorted(by_outcome.items()) if k.startswith("failed")},
            "skippedForSkipReason": len(skipped), "refusedHosts": len(refused),
            "liveRequests": sum(1 for r in records + truth if r.get("live")),
            "templates": dict(Counter(r["template"] or "not fetched" for r in records)),
            "secondaryStored": sum(1 for r in accepted if len(r["colors"]) == 2),
        },
        "review": {
            "guarded": [_entry(r) for r in records if r["outcome"] in ("rejected: template-guard", "rejected: denylisted")],
            "themeMismatch": [_entry(r) for r in records if r["outcome"] == "rejected: theme-mismatch"],
            "blackPrimaryAccepted": [_entry(r) for r in accepted if "black-primary" in r["flags"]],
            "randomAcceptedD3": [_entry(r) for r in sorted(sample, key=lambda r: r["slug"])],
        },
        "refusedHosts": refused,
        "skippedForSkipReason": sorted(p["slug"] for p in skipped),
        "groundTruth": [dict(_entry(r), wikipedia=r["wikipedia"]) for r in truth],
        "programs": [_entry(r) for r in records],
    }


def run(registry: dict, *, slugs: list[str] | None = None, report_path: str | None = REPORT_PATH,
        sleep=time.sleep, workers: int = WORKERS) -> dict:
    """The dry run: fetch, decide, write the report. Never writes the registry.

    Programs are grouped by host and each host's programs run in order in one worker, so the host-stop
    rule holds within a host and no host sees two requests at once; up to `workers` different hosts run
    side by side. Most Sidearm hosts ask Crawl-delay 30s, which common's per-host gate honours between
    the robots.txt request and the page, so one host at a time would take hours for no politeness gain."""
    targets, skipped, truth_progs = _targets(registry, slugs)
    stopped: dict[str, int] = {}
    common.log(f"site colours: {len(targets)} to fetch, {len(truth_progs)} ground truth, "
               f"{len(skipped)} skipped for athletics.skipReason, {workers} workers")
    jobs = [("target", p) for p in targets] + [("truth", p) for p in truth_progs]
    by_host: dict[str, list] = {}
    for job in jobs:
        by_host.setdefault(common._host(page_url(job[1])), []).append(job)
    done: dict[str, dict] = {}
    n = [0]

    def one_host(host_jobs):
        for group, p in host_jobs:
            r = fetch_site_page(p, stopped)
            if group == "truth":
                r["wikipedia"] = [norm_hex(c) for c in p["colors"]]
            done[p["slug"]] = r
            n[0] += 1
            common.log(f"site colours: {n[0]}/{len(jobs)} {group} {p['slug']:28} {r['outcome'] or r['template']}")
            if r["live"]:
                sleep(HOST_PAUSE)

    if workers <= 1:
        for host_jobs in by_host.values():
            one_host(host_jobs)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for f in [pool.submit(one_host, hj) for hj in by_host.values()]:
                f.result()
    records = [done[p["slug"]] for p in targets]
    truth = [done[p["slug"]] for p in truth_progs]
    decide_all(records)
    decide_all(truth, guard_hosts=None)  # ten programs: the pair guard is for the target set
    for r in records + truth:
        r.setdefault("flags", [])
        if "colors" not in r:
            r["colors"] = None
    report = build_report(records, skipped, truth)
    if report_path:
        common.write_json(report_path, report)
    c = report["counts"]
    print(f"\naccepted {c['accepted']} of {c['targets']}; rejected {c['rejected']}; skipped {c['skipped']}; "
          f"failed {c['failed']}; refused hosts {c['refusedHosts']}; skipReason {c['skippedForSkipReason']}")
    print(f"report: {report_path}. Dry run: the registry is unchanged. A Reviewer's verdict on #276 comes "
          f"before --apply.")
    return report


def apply_mutate(found: dict[str, list]):
    """The registry edit: colours only where a program still has none, re-checked at write time."""
    def mutate(reg):
        for p in reg["programs"]:
            if p["slug"] in found and not p.get("colors"):
                p["colors"] = list(found[p["slug"]])
                p["colorsSource"] = SOURCE
    return mutate


def apply_report(report_path: str = REPORT_PATH, *, slugs: list[str] | None = None) -> dict:
    """Write the accepted colours of the committed (reviewed) report. Fetches nothing."""
    report = common.read_json(report_path)
    if not report:
        raise FileNotFoundError(f"no report at {report_path}: run the dry run first")
    found = {e["slug"]: e["colors"] for e in report["programs"]
             if e.get("outcome") == "accepted" and e.get("colors") and (not slugs or e["slug"] in slugs)}
    bad = {s: c for s, c in found.items() if not (1 <= len(c) <= 2 and all(norm_hex(h) == h for h in c))}
    if bad:
        raise ValueError(f"report colours are not 1-2 upper-case #RRGGBB values: {list(bad)[:5]}")
    common.update_registry(apply_mutate(found))
    print(f"registry updated: colors from the athletics site for up to {len(found)} programs "
          f"(programs that already had colours were left alone)")
    return found


# ---------- the D1 ground-truth table (offline, from .cache/http) ----------

def build_truth_table(registry: dict, path: str = TRUTH_PATH) -> list[dict]:
    """D1 Sidearm programs with colours whose soccer roster (or sport, schedule, coaches) page is in `.cache/http`: the site's extracted
    values next to the registry's Wikipedia colours. Hex values and slugs only. No request is made."""
    os.environ["COLLEGEDASH_OFFLINE"] = "1"
    rows = []
    for p in sorted(registry["programs"], key=lambda p: p["slug"]):
        a = p.get("athletics") or {}
        if p.get("division") != "D1" or a.get("platform") != "sidearm" or not p.get("colors"):
            continue
        html = None
        for suffix in TRUTH_PAGES:  # the first of the soccer pages onboarding cached; every page carries the theme
            try:
                html, _ = common.fetch_text(page_url(p) + suffix)
                break
            except common.FetchError:
                continue
        if html is None:
            continue
        template, c = extract(html)
        c = c or {}
        rows.append({"slug": p["slug"], "template": template, "primary": c.get("primary"),
                     "secondary": c.get("secondary"), "theme": c.get("theme"),
                     "wikipedia": [norm_hex(h) for h in p["colors"]]})
    common.write_json(path, {"issue": 276, "note": "D1 Sidearm soccer pages from .cache/http; hex values only",
                             "rows": rows})
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth-table", action="store_true", help="rebuild tests/fixtures/colors_site_truth.json offline")
    ap.add_argument("--cache-dir", help="read pages from this .cache/http (e.g. the main checkout's)")
    args = ap.parse_args()
    if args.cache_dir:
        common.CACHE_DIR = args.cache_dir
    if args.truth_table:
        rows = build_truth_table(common.load_registry())
        print(f"{len(rows)} rows -> {TRUTH_PATH}")
