#!/usr/bin/env python3
"""The steps of .github/workflows/onboard.yml that are not shell: name, plan, run and summarize one
onboarding batch (issue #242; the batch plan is #94, the batch command #143/#172, holds #216/#218).

    python .github/scripts/onboard_batch.py name      --division D3 --conferences "A,B" [--slugs x,y] [--batch-name n]
    python .github/scripts/onboard_batch.py plan      --division D3 --conferences "A,B" [--slugs x,y] [--batch-name n]
                                                      --out-dir DIR [--max-programs 60]
    python .github/scripts/onboard_batch.py run       --plan DIR/plan.json --out DIR/run.json [--no-network]
    python .github/scripts/onboard_batch.py summarize --plan DIR/plan.json --run DIR/run.json --base-registry FILE
                                                      --json-out F --md-out F

`name` and `plan` import nothing from collect/ and make no request: they read the registry file and the
dispatch inputs only, so a bad input fails the run before anything is installed.

`run` is the D2 batch wrapper (#94, batches 10-22) made repository code. It runs the real command in
process - collegedash.main(["onboard", "--slugs-file", ..., "--no-bios", maybe "--collect-staged-divisions", D])
- so the batch form, its workers, the per-host gate, the CollegeDashBot User-Agent, robots.txt and the
holds guard are all exactly what they are locally. The one thing it adds wraps
collect.common._PoliteAdapter.send, which every live request and every redirect hop passes through:
after a host's first HTTP 403 or 429, no further request is sent to that host for the rest of the batch.
That only ever removes traffic. It also counts requests per program, so the summary can say which
program met which 403/429 host. --no-network refuses every request before it is sent (and sets
COLLEGEDASH_OFFLINE=1), which is the workflow's dry run: the whole path runs, nothing is fetched.

`summarize` reads what the run left on disk (programs/<slug>/sources/*.json, refresh-state, the registry)
and writes the batch summary as JSON and markdown. It is also the guard on what the run did to the
registry: a program whose `onboarded` flag the run flipped must be one this plan named, in the division
this plan named. Anything else exits 3 and the workflow commits nothing.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import threading
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests point it at a scratch tree
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # this checkout's code; never moved
REGISTRY = os.path.join(ROOT, "public", "data", "registry.json")
COLLECTORS = ["scorecard", "climate", "wikipedia", "athletics", "tds", "soccerwire", "news", "camps"]

# From the D2 batches (#94, batches 10-22, 16 workers): 7 to 15 programs took 350-415 s of wall time
# whatever the count, because one program's own athletics site (about 13 requests at the per-host gap)
# sets the pace and 16 programs run side by side. So a batch costs about 7 minutes per 16 programs.
# 60 programs is four such waves, about half an hour: a few D3 conferences, still a batch a person can
# read through, and a tenth of the 360-minute job limit, so a run three times slower than D2 still fits.
MAX_PROGRAMS = 60
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DIVISION_RE = re.compile(r"^D[1-9]$")


def _redact(text) -> str:
    """The redact() of this checkout's collect/common.py (ROOT can be a scratch tree without code): error
    text read from refresh-state is redacted again here, since a runner's entries can predate issue #258."""
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    from collect.common import redact
    return redact(text)


class Refused(Exception):
    """An input or a plan this workflow will not run. Printed as ::error; exit 2, nothing collected."""


def _list(raw: str | None, what: str) -> list[str]:
    """Split a comma-separated dispatch input. Ends are trimmed; an empty item (a doubled or trailing
    comma) is an error rather than silently dropped, as refresh.yml treats `only`."""
    raw = (raw or "").strip()
    if not raw:
        return []
    items = [x.strip() for x in raw.split(",")]
    if any(not x for x in items):
        raise Refused(f"{what} has an empty item (a doubled or trailing comma): {raw!r}")
    seen: list[str] = []
    for x in items:
        if x not in seen:
            seen.append(x)
    return seen


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def batch_name(division: str, conferences: list[str], slugs: list[str], given: str | None) -> str:
    """The batch name, and so the branch onboard/<name>. A given name is checked, never rewritten, so what
    the person typed is what the branch is called; a derived one is <division>-<conference>[-<conference>...]
    or <division>-<first slug>[-and-N-more], cut to 64 characters."""
    given = (given or "").strip()
    if given:
        if not NAME_RE.match(given) or "--" in given:
            raise Refused(f"batch_name {given!r} must be 1-64 characters of a-z, 0-9 and single hyphens, "
                          f"starting and ending with a letter or digit")
        return given
    parts = [_slugify(division)]
    if conferences:
        parts += [_slugify(c) for c in conferences]
    if slugs:
        parts.append(slugs[0] if len(slugs) == 1 else f"{slugs[0]}-and-{len(slugs) - 1}-more")
    name = re.sub(r"-+", "-", "-".join(p for p in parts if p))[:64].strip("-")
    if not NAME_RE.match(name):
        raise Refused(f"could not derive a batch name from the inputs; give batch_name")
    return name


def parse_inputs(division: str, conferences: str, slugs: str, given_name: str | None):
    division = (division or "").strip().upper()
    if not DIVISION_RE.match(division):
        raise Refused(f"division must look like D1, D2 or D3, not {division!r}")
    confs = _list(conferences, "conferences")
    slug_list = _list(slugs, "slugs")
    bad = [s for s in slug_list if not SLUG_RE.match(s)]
    if bad:
        raise Refused(f"slugs must be registry slugs (a-z, 0-9, hyphens): {', '.join(repr(b) for b in bad[:20])}")
    if not confs and not slug_list:
        raise Refused("name at least one conference or one slug: this workflow never collects a whole division")
    return division, confs, slug_list, batch_name(division, confs, slug_list, given_name)


def hold_reason(p: dict) -> str | None:
    hold = p.get("collectionHold")
    if not hold:
        return None
    if not isinstance(hold, dict):
        return "collectionHold (no reason given)"
    since = f", since {hold['since']}" if hold.get("since") else ""
    return f"collectionHold {hold.get('reason') or '(no reason given)'}{since}"


def make_plan(reg: dict, division: str, confs: list[str], slug_list: list[str], name: str,
              max_programs: int = MAX_PROGRAMS) -> dict:
    """What this batch collects, or Refused. Mirrors cmd_onboard's own guards so that a refusal happens
    here, in seconds, and cmd_onboard's guards are the second line rather than the only one."""
    published = list(reg.get("onboardedDivisions") or [])
    staged = list(reg.get("stagedDivisions") or [])
    if division in staged:
        state = "staged"
    elif division in published:
        state = "published"
    else:
        raise Refused(f"{division} is neither staged nor published in the registry (stagedDivisions {staged}, "
                      f"onboardedDivisions {published}). Stage it first (#190 for D3); this workflow never marks a "
                      f"program onboarded in a division the registry does not stage.")
    programs = reg.get("programs") or []
    in_div = [p for p in programs if p.get("division") == division]
    by_conf: dict[str, list[dict]] = collections.defaultdict(list)
    for p in in_div:
        by_conf[(p.get("conference") or "").casefold()].append(p)
    unknown_confs = [c for c in confs if c.casefold() not in by_conf]
    if unknown_confs:
        known = sorted({p.get("conference") or "?" for p in in_div})
        raise Refused(f"no {division} program is in conference(s) {', '.join(repr(c) for c in unknown_confs)}. "
                      f"{division} has {len(known)} conferences" + (f", e.g. {', '.join(known[:20])}" if known else ""))
    by_slug = {p.get("slug"): p for p in programs}
    unknown = [s for s in slug_list if s not in by_slug]
    if unknown:
        raise Refused(f"unknown slug(s): {', '.join(unknown[:20])}")
    wrong = [f"{s} ({by_slug[s].get('division')})" for s in slug_list if by_slug[s].get("division") != division]
    if wrong:
        raise Refused(f"slug(s) outside {division}: {', '.join(wrong[:20])}. One batch collects one division.")

    chosen: list[dict] = []
    held: list[dict] = []
    for c in confs:
        for p in by_conf[c.casefold()]:
            if p.get("onboarded"):
                continue  # a conference selects what is still to collect, as `onboard --all --conference` does
            (held if hold_reason(p) else chosen).append(p)
    for s in slug_list:  # a slug named explicitly is collected even if onboarded already (a re-collect)
        p = by_slug[s]
        (held if hold_reason(p) else chosen).append(p)
    slugs: list[str] = []
    for p in chosen:
        if p["slug"] not in slugs:
            slugs.append(p["slug"])
    held_rows: list[dict] = []
    for p in held:
        if p["slug"] not in [h["slug"] for h in held_rows]:
            held_rows.append({"slug": p["slug"], "conference": p.get("conference"), "skipReason": hold_reason(p)})
    if not slugs:
        raise Refused(f"nothing to collect: every program selected is already onboarded or under a collectionHold "
                      f"({len(held_rows)} held: {', '.join(h['slug'] for h in held_rows[:20]) or 'none'})")
    if len(slugs) > max_programs:
        sizes = collections.Counter(by_slug[s].get("conference") or "?" for s in slugs)
        raise Refused(f"{len(slugs)} programs is over the {max_programs} one run collects "
                      f"(about 7 minutes per 16 programs on the D2 timings, and one batch should be one read-through). "
                      f"Split it by conference: " + ", ".join(f"{c} {n}" for c, n in sizes.most_common(20)))
    command = ["python", "collegedash.py", "onboard", "--slugs-file", "<slugs file>", "--no-bios"]
    if state == "staged":
        command += ["--collect-staged-divisions", division]
    return {"batchName": name, "branch": f"onboard/{name}", "division": division, "divisionState": state,
            "conferences": confs, "requestedSlugs": slug_list, "slugs": slugs, "held": held_rows,
            "collectStagedDivisions": division if state == "staged" else None, "command": command}


def _gh_output(pairs: dict) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for k, v in pairs.items():
                f.write(f"{k}={v}\n")


def cmd_name(a) -> int:
    _, _, _, name = parse_inputs(a.division, a.conferences, a.slugs, a.batch_name)
    print(name)
    _gh_output({"name": name, "branch": f"onboard/{name}"})
    return 0


def cmd_plan(a) -> int:
    division, confs, slug_list, name = parse_inputs(a.division, a.conferences, a.slugs, a.batch_name)
    with open(a.registry, encoding="utf-8") as f:
        reg = json.load(f)
    plan = make_plan(reg, division, confs, slug_list, name, a.max_programs)
    os.makedirs(a.out_dir, exist_ok=True)
    slugs_file = os.path.join(a.out_dir, "slugs.txt")
    with open(slugs_file, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(s + "\n" for s in plan["slugs"]))
    plan["slugsFile"] = slugs_file
    with open(os.path.join(a.out_dir, "plan.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(plan, f, indent=1)
        f.write("\n")
    print(f"batch {name}: {len(plan['slugs'])} program(s) in {division} ({plan['divisionState']}), "
          f"{len(plan['held'])} held; branch {plan['branch']}")
    print("  " + ", ".join(plan["slugs"][:20]) + (f" ... and {len(plan['slugs']) - 20} more" if len(plan["slugs"]) > 20 else ""))
    for h in plan["held"][:20]:
        print(f"  skips {h['slug']}: {h['skipReason']}")
    _gh_output({"name": name, "branch": plan["branch"], "division": division, "programs": len(plan["slugs"]),
                "slugs_file": slugs_file})
    return 0


# ---------- run ----------

def install_wrapper(common, collegedash, *, no_network: bool):
    """Wrap _PoliteAdapter.send (every request and redirect hop) and collegedash.collect_one (to know which
    program a thread is collecting). Returns the shared state the run records."""
    import requests
    from urllib.parse import urlsplit

    state = {"lock": threading.Lock(), "stopped": {}, "requests": 0, "refused": collections.Counter(),
             "statuses": collections.Counter(), "perProgram": collections.defaultdict(lambda: {"requests": 0, "blockedHosts": {}}),
             "hits": []}
    current = threading.local()
    original_send = common._PoliteAdapter.send
    original_collect_one = collegedash.collect_one

    def collect_one(name, program, registry, **kw):
        prev = getattr(current, "slug", None)
        current.slug = program.get("slug")
        try:
            return original_collect_one(name, program, registry, **kw)
        finally:
            current.slug = prev

    host_locks: dict[str, threading.Lock] = {}

    def host_lock(host: str) -> threading.Lock:
        with state["lock"]:
            lk = host_locks.get(host)
            if lk is None:
                lk = host_locks[host] = threading.Lock()
            return lk

    def send(self, request, **kwargs):
        host = (urlsplit(request.url).hostname or "").lower()
        slug = getattr(current, "slug", None) or "(batch)"
        if no_network:
            with state["lock"]:
                state["refused"][host] += 1
            raise requests.exceptions.ConnectionError(f"onboard dry run: no request is sent ({host})")
        # The stop check and the send happen under one per-host lock (PR #245 review). Checked before the
        # lock only, every thread already queued at the host's gate inside original_send had passed the
        # check, and each of them still sent after the first 403/429: 8 of 8 in the review's test. The gate
        # already lets one request at a time reach a host, so this lock costs no throughput; redirect hops
        # are separate send() calls made one after another in the same thread, so it cannot deadlock.
        with host_lock(host):
            with state["lock"]:
                code = state["stopped"].get(host)
                if code is not None:
                    state["refused"][host] += 1
                    state["perProgram"][slug]["blockedHosts"].setdefault(host, code)
            if code is not None:
                raise requests.exceptions.ConnectionError(f"onboard batch: {host} stopped after its first HTTP {code}; no request sent")
            resp = original_send(self, request, **kwargs)
            first = False
            with state["lock"]:
                state["requests"] += 1
                state["perProgram"][slug]["requests"] += 1
                state["statuses"][resp.status_code] += 1
                if resp.status_code in (403, 429):
                    first = host not in state["stopped"]
                    state["stopped"].setdefault(host, resp.status_code)
                    state["perProgram"][slug]["blockedHosts"].setdefault(host, resp.status_code)
                    state["hits"].append({"host": host, "status": resp.status_code, "program": slug})
        if resp.status_code in (403, 429) and first:
            common.log(f"!! onboard batch: HTTP {resp.status_code} from {host}; no further request will be sent to it")
        return resp

    common._PoliteAdapter.send = send
    collegedash.collect_one = collect_one
    return state


def cmd_run(a) -> int:
    with open(a.plan, encoding="utf-8") as f:
        plan = json.load(f)
    if a.no_network:
        os.environ["COLLEGEDASH_OFFLINE"] = "1"
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    from collect import common
    import collegedash
    if a.no_network:
        import socket

        def refuse(self, *args, **kwargs):  # belt to the adapter's braces: nothing leaves the runner
            raise OSError("onboard dry run: no network")
        socket.socket.connect = refuse
    state = install_wrapper(common, collegedash, no_network=a.no_network)
    argv = ["onboard", "--slugs-file", plan["slugsFile"], "--no-bios"]
    if plan.get("collectStagedDivisions"):
        argv += ["--collect-staged-divisions", plan["collectStagedDivisions"]]
    started = common.now_iso()
    t0 = time.time()
    try:
        code = collegedash.main(argv)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 2
    except Exception:
        traceback.print_exc()
        code = 2
    wall = time.time() - t0
    with state["lock"]:
        out = {"exit": code, "startedAt": started, "wallSeconds": round(wall, 1),
               "perProgramSeconds": round(wall / max(1, len(plan["slugs"])), 1), "noNetwork": bool(a.no_network),
               "requests": state["requests"], "statuses": {str(k): v for k, v in sorted(state["statuses"].items())},
               "stoppedHosts": dict(state["stopped"]), "refused": dict(state["refused"].most_common(20)),
               "refusedTotal": sum(state["refused"].values()), "hits403or429": state["hits"][:200],
               "perProgram": {k: v for k, v in state["perProgram"].items()}, "argv": argv}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    print(f"onboard exit {code}; {out['requests']} request(s) in {out['wallSeconds']} s; "
          f"stopped hosts {out['stoppedHosts'] or 'none'}; refused {out['refusedTotal']}")
    return code if isinstance(code, int) else 2


# ---------- summarize ----------

def _src(slug: str, name: str):
    p = os.path.join(ROOT, "programs", slug, "sources", f"{name}.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _count(v, key: str) -> int:
    if isinstance(v, dict):
        v = v.get(key)
    return len(v) if isinstance(v, list) else 0


def program_row(slug: str, reg_by_slug: dict, refresh_state: dict, run: dict, started: str) -> dict:
    p = reg_by_slug.get(slug) or {}
    a = _src(slug, "athletics")
    data = (a or {}).get("data") or {}
    failures, not_run = {}, []
    for c in COLLECTORS:
        e = refresh_state.get(f"{slug}.{c}")
        if not e or (started and str(e.get("at") or "") < started):
            not_run.append(c)  # no entry from THIS run: the run stopped before it, or it never started
        elif not e.get("ok"):
            failures[c] = _redact(e.get("error") or "")[:120]
    blocked = ((run.get("perProgram") or {}).get(slug) or {}).get("blockedHosts") or {}
    # the row counts are read from the athletics source on disk; when this run did not write it (athletics
    # failed, was skipped, or never ran) they are an earlier collection's, or zero, and are marked as such
    fresh = bool(a) and bool(started) and str(a.get("fetchedAt") or "") >= started
    return {"slug": slug, "conference": p.get("conference"), "onboarded": bool(p.get("onboarded")),
            "athleticsFromThisRun": fresh,
            "rosterRows": _count(data.get("roster"), "players"), "scheduleRows": _count(data.get("schedule"), "games"),
            "staffRows": _count(data.get("staff"), "staff"), "failures": failures, "notRun": not_run,
            "blockedHosts": blocked, "skipReason": ((p.get("athletics") or {}).get("skipReason")) or hold_reason(p)}


def registry_guard(base: dict, now: dict, plan: dict) -> list[str]:
    """Programs whose `onboarded` changed must be in the plan and in its division; nothing else may change it."""
    before = {p.get("slug"): bool(p.get("onboarded")) for p in base.get("programs") or []}
    problems = []
    planned = set(plan["slugs"])
    for p in now.get("programs") or []:
        s = p.get("slug")
        if bool(p.get("onboarded")) == before.get(s, False):
            continue
        if s not in planned:
            problems.append(f"{s}: onboarded changed to {bool(p.get('onboarded'))} but it is not in this batch")
        elif p.get("division") != plan["division"]:
            problems.append(f"{s}: onboarded in {p.get('division')}, not the batch's {plan['division']}")
        elif hold_reason(p):
            problems.append(f"{s}: onboarded while under a {hold_reason(p)}")
    for key in ("onboardedDivisions", "stagedDivisions"):
        if base.get(key) != now.get(key):
            problems.append(f"registry {key} changed from {base.get(key)} to {now.get(key)}")
    return problems


def render_md(summary: dict) -> str:
    s = summary
    run = s["run"]
    lines = [f"## Onboard batch `{s['batchName']}`", "",
             f"{s['division']} ({s['divisionState']}); conferences: {', '.join(s['conferences']) or '-'}; "
             f"slugs named: {', '.join(s['requestedSlugs']) or '-'}", "",
             f"- programs collected: {len(s['programs'])}; held and skipped: {len(s['held'])}",
             f"- onboard exit: {run.get('exit')} (0 = clean, 1 = some collector failed, 2 = refused or crashed)"
             + ("; **dry run, no network**" if run.get("noNetwork") else ""),
             f"- wall: {run.get('wallSeconds')} s ({run.get('perProgramSeconds')} s per program); requests: {run.get('requests')}",
             f"- hosts stopped after a 403/429: " + (", ".join(f"{h} ({c})" for h, c in (run.get("stoppedHosts") or {}).items()) or "none"),
             f"- collector runs failed: {s['totals']['failed']} of {s['totals']['runs']}; not run: {s['totals']['notRun']}",
             f"- registry guard: " + ("pass" if not s["guard"] else "**FAILED** - " + "; ".join(s["guard"][:10])), "",
             "| program | conference | roster | schedule | staff | failures | 403/429 hosts | skipReason |",
             "| --- | --- | ---: | ---: | ---: | --- | --- | --- |"]
    esc = lambda t: str(t).replace("|", "\\|").replace("\n", " ")
    for r in s["programs"]:
        fails = ", ".join(f"{c}: {esc(_redact(e))[:60]}" for c, e in r["failures"].items())
        if r["notRun"]:
            fails = (fails + "; " if fails else "") + "not run: " + ", ".join(r["notRun"])
        old = "" if r["athleticsFromThisRun"] or not (r["rosterRows"] or r["scheduleRows"] or r["staffRows"]) else " (earlier)"
        lines.append(f"| {r['slug']} | {esc(r['conference'] or '')} | {r['rosterRows']}{old} | {r['scheduleRows']}{old} | {r['staffRows']}{old} | "
                     f"{fails or '-'} | {', '.join(f'{h} ({c})' for h, c in r['blockedHosts'].items()) or '-'} | {esc(r['skipReason'] or '-')} |")
    for h in s["held"]:
        lines.append(f"| {h['slug']} | {esc(h['conference'] or '')} | - | - | - | not collected | - | {esc(h['skipReason'])} |")
    if s.get("compareUrl"):
        lines += ["", f"Open the PR from the branch: {s['compareUrl']}"]
    return "\n".join(lines) + "\n"


def cmd_summarize(a) -> int:
    with open(a.plan, encoding="utf-8") as f:
        plan = json.load(f)
    run = {}
    if a.run and os.path.exists(a.run):
        with open(a.run, encoding="utf-8") as f:
            run = json.load(f)
    with open(os.path.join(ROOT, "public", "data", "registry.json"), encoding="utf-8") as f:
        reg = json.load(f)
    with open(a.base_registry, encoding="utf-8") as f:
        base = json.load(f)
    rs_path = os.path.join(ROOT, "public", "archive", "refresh-state.json")
    refresh_state = {}
    if os.path.exists(rs_path):
        with open(rs_path, encoding="utf-8") as f:
            refresh_state = json.load(f)
    by_slug = {p.get("slug"): p for p in reg.get("programs") or []}
    rows = [program_row(s, by_slug, refresh_state, run, run.get("startedAt") or "") for s in plan["slugs"]]
    guard = registry_guard(base, reg, plan)
    repo = os.environ.get("GITHUB_REPOSITORY")
    summary = {"batchName": plan["batchName"], "branch": plan["branch"], "division": plan["division"],
               "divisionState": plan["divisionState"], "conferences": plan["conferences"],
               "requestedSlugs": plan["requestedSlugs"], "held": plan["held"],
               "run": {k: run.get(k) for k in ("exit", "startedAt", "wallSeconds", "perProgramSeconds", "noNetwork",
                                              "requests", "statuses", "stoppedHosts", "refusedTotal")},
               "totals": {"runs": len(rows) * len(COLLECTORS),
                          "failed": sum(len(r["failures"]) for r in rows),
                          "notRun": sum(len(r["notRun"]) for r in rows),
                          "rosterZero": [r["slug"] for r in rows if not r["rosterRows"] and not r["skipReason"]]},
               "guard": guard, "programs": rows,
               "compareUrl": f"https://github.com/{repo}/compare/main...{plan['branch']}?expand=1" if repo else None}
    for path in (a.json_out, a.md_out):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(a.json_out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=1, ensure_ascii=False)
        f.write("\n")
    md = render_md(summary)
    with open(a.md_out, "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as f:
            f.write(md)
    print(f"summary: {len(rows)} program(s), {summary['totals']['failed']} failed collector run(s), "
          f"{summary['totals']['notRun']} not run, roster 0 for {len(summary['totals']['rosterZero'])}; "
          f"guard {'pass' if not guard else 'FAILED'}")
    for g in guard[:20]:
        print(f"::error title=onboard::registry guard: {g}")
    return 3 if guard else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("name", "plan"):
        p = sub.add_parser(n)
        p.add_argument("--division", required=True)
        p.add_argument("--conferences", default="")
        p.add_argument("--slugs", default="")
        p.add_argument("--batch-name", default="")
        if n == "plan":
            p.add_argument("--registry", default=REGISTRY)
            p.add_argument("--out-dir", required=True)
            p.add_argument("--max-programs", type=int, default=MAX_PROGRAMS)
    p = sub.add_parser("run")
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--no-network", action="store_true")
    p = sub.add_parser("summarize")
    p.add_argument("--plan", required=True)
    p.add_argument("--run", default="")
    p.add_argument("--base-registry", required=True)
    p.add_argument("--json-out", required=True)
    p.add_argument("--md-out", required=True)
    a = ap.parse_args(argv)
    try:
        return {"name": cmd_name, "plan": cmd_plan, "run": cmd_run, "summarize": cmd_summarize}[a.cmd](a)
    except Refused as e:
        print(f"::error title=onboard::{str(e).rstrip('.')}. Nothing was collected.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
