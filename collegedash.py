#!/usr/bin/env python3
"""
CollegeDash command line.

  python collegedash.py onboard <slug> [--no-bios]      run every collector for one program, then build
                                                        (--no-bios skips player bios; the head coach's bio is still fetched)
  python collegedash.py onboard <slug> <slug> ...       or --slugs-file f: batch form (issue #143) - every
                    [--slugs-file f] [--workers 16]      collector for every program, THEN one build;
                 [--collect-staged-divisions D2]         --workers side by side, same politeness as refresh;
                                                          refuses a slug in a division the site does not
                                                          publish yet, same as --all below
  python collegedash.py onboard --all [--conference C]   onboard the programs not yet onboarded, a batch at a
                              [--limit N] [--max-batch N] time; refuses a batch that spans a division the site
                         [--collect-staged-divisions D2] does not publish yet, or one over --max-batch
  python collegedash.py refresh [--only a,b] [--slug s]  refresh collectors for onboarded programs (scheduled job)
                                [--failed] [--dry-run]   --failed: only collectors whose last run failed
                           [--no-bios] [--coach-bios]    --coach-bios: head-coach bio pages even with --no-bios
                                [--workers 16]          programs collected side by side; per-host politeness holds
                                [--fail-threshold 0.05] exit 1 only when more than this share of runs fail; 2 = crash
  python collegedash.py registry build|tidy|fix-wiki|colors [--apply] [--slug a,b]
  python collegedash.py sweep [tds|soccerwire|all] [--years 2027,2028]
  python collegedash.py rpi [history|current|all] [--force]
  python collegedash.py build                            merge programs/* -> public/data
  python collegedash.py validate                         schema + completeness report
  python collegedash.py serve [--port 8000]              local static server (public/) with write endpoints

Collectors: athletics, scorecard, climate, wikipedia, tds, soccerwire, news, camps, rpi
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import threading
import time
import traceback

from collect import common

COLLECTORS = ["scorecard", "climate", "wikipedia", "athletics", "tds", "soccerwire", "news", "camps"]  # camps after news: it mines the news archive


def run_collector(name: str, program: dict, registry: dict, **kw) -> bool:
    """Run one collector for one program; True unless it failed. See run_collector_outcome for detail."""
    return run_collector_outcome(name, program, registry, **kw)["outcome"] != "failed"


def run_collector_outcome(name: str, program: dict, registry: dict, **kw) -> dict:
    """{"program", "collector", "outcome": ok|skipped|failed, "error"} - records the result in refresh-state.
    Never raises for an Exception: neither the collector's nor a failure to record the outcome."""
    r, entry = collect_one(name, program, registry, **kw)
    if entry is not None:
        record_outcomes(program["slug"], {f"{program['slug']}.{name}": entry})
    return r


def collect_one(name: str, program: dict, registry: dict, **kw) -> tuple[dict, dict | None]:
    """Run one collector for one program and return (outcome, refresh-state entry) without writing
    refresh-state. The entry is None when there is nothing to record (an unknown collector name).
    Every Exception the collector raises becomes a failed outcome; nothing else here can raise one."""
    r = {"program": program["slug"], "collector": name, "outcome": "ok", "error": ""}
    try:
        if name == "scorecard":
            from collect import scorecard as m
            m.collect(program, registry)
        elif name == "climate":
            from collect import climate as m
            m.collect(program, registry)
        elif name == "wikipedia":
            from collect import wikipedia as m
            m.collect(program, registry)
        elif name == "athletics":
            from collect import athletics_site as m
            m.collect(program, registry, bios=kw.get("bios", True), coach_bios=kw.get("coach_bios"))
        elif name == "tds":
            from collect import commitments_tds as m
            m.collect(program, registry)
        elif name == "soccerwire":
            from collect import commitments_soccerwire as m
            m.collect(program, registry)
        elif name == "news":
            from collect import news as m
            m.collect(program, registry)
        elif name == "camps":
            from collect import camps as m
            m.collect(program, registry)
        else:
            common.log(f"unknown collector {name}")
            r.update(outcome="failed", error=f"unknown collector {name}")
            return r, None
        entry = {"ok": True}
    except common.SkipCollector as e:  # nothing to collect for this program; not a failure
        common.log(f"-- {name} skipped for {program['slug']}: {e}")
        r.update(outcome="skipped", error=common.error_text(e, 300))
        entry = {"ok": True, "skipped": common.error_text(e, 300)}
    except Exception as e:  # keep going; partial progress is still committed
        common.log(f"!! {name} failed for {program['slug']}: {e}")
        common.log_traceback()
        r.update(outcome="failed", error=common.error_text(e, 300))
        entry = {"ok": False, "error": common.error_text(e, 300)}
    entry["at"] = common.now_iso()  # when the collector finished, not when the batch was written
    return r, entry


RECORD_ATTEMPTS = 3

# Programs whose refresh-state entries could not be written: [(slug, number of entries, error)].
# A failed write loses no collected data - the sources are on disk and the summary, exit code and
# threshold all come from the outcomes held in memory - but it leaves that program's entries STALE,
# which is worse than empty: build.py publishes them as the program's `_build.failed` / `_build.skipped`
# and `refresh --failed` picks its work from them, so yesterday's verdict is republished as today's
# and the program is not retried. So it is reported rather than only logged (issue #119): a warning
# per program as it happens, and a count in the run summary and in lastRun. It is not made fatal:
# the Reviewer's judgement on PR #105 was that this is stale diagnostic metadata, not lost data, and
# failing the run would throw away a complete collection over a metadata write.
_not_recorded: list[tuple[str, int, str]] = []
_not_recorded_lock = threading.Lock()


def not_recorded() -> list[tuple[str, int, str]]:
    """The programs whose refresh-state entries could not be written, in the order they failed."""
    with _not_recorded_lock:
        return list(_not_recorded)


def clear_not_recorded() -> None:
    with _not_recorded_lock:
        _not_recorded.clear()


def record_outcomes(slug: str, entries: dict[str, dict]) -> bool:
    """Write refresh-state entries in one locked read-modify-write. Never raises for an Exception:
    the run's outcomes live in memory and drive the summary and exit code, so a refresh-state write
    that fails must not turn a success into a failure (it used to: the ok path's write raising was
    caught as the collector failing) or escape and cancel the programs still queued. Retried, then
    logged, annotated and counted (see _not_recorded). False when the entries could not be recorded."""
    for attempt in range(1, RECORD_ATTEMPTS + 1):
        try:
            common.update_refresh_state_many(entries)
            return True
        except Exception as e:
            if attempt == RECORD_ATTEMPTS:
                common.log(f"!! refresh-state not recorded for {slug} ({', '.join(entries)}): {e}")
                with _not_recorded_lock:
                    _not_recorded.append((slug, len(entries), str(e)[:200]))
                if os.environ.get("GITHUB_ACTIONS"):
                    common.annotate(f"::warning title=refresh: refresh-state not recorded for {slug}::"
                                    f"{len(entries)} entries could not be written after {RECORD_ATTEMPTS} attempts "
                                    f"({str(e)[:160]}). The collected sources are safe and this run's summary is "
                                    f"correct, but {slug}'s stored per-collector status is now stale: the site will "
                                    f"republish the previous run's verdict for it and `refresh --failed` will not "
                                    f"retry it.")
                return False
            time.sleep(0.2 * attempt)
    return False


def _mark_onboarded(slug: str) -> dict:
    def mutate(reg):
        for p in reg["programs"]:
            if p["slug"] == slug:
                p["onboarded"] = True
                p.setdefault("onboardedAt", common.today())
    return common.update_registry(mutate)


def explicit_slugs(args) -> list[str]:
    """The slugs an onboard command names outside --all: the positional slug plus any more_slugs and
    any --slugs-file, in the order given, duplicates dropped after the first. Empty for --all.

    Two or more is the batch form (issue #143): collect every one, then build once, instead of once
    per program. Exactly one - however it arrived, typed directly or the only line of a file - takes
    the single-program path. Either way the division guard applies (onboard_batch_refusal): the owner
    decided on #172 that one staged-division slug needs --collect-staged-divisions exactly as a list
    does. Before that, a single slug was never guarded, and #161 onboarded 56 D2 programs that way."""
    if args.slug == "--all" or args.all:
        return []
    slugs = ([args.slug] if args.slug else []) + list(args.more_slugs)
    if args.slugs_file:
        with open(args.slugs_file, encoding="utf-8") as f:
            slugs += [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
    seen: list[str] = []
    for s in slugs:
        if s not in seen:
            seen.append(s)
    return seen


def collection_hold(p: dict) -> dict | None:
    """The entry's `collectionHold` block (issue #199), or None. A person decided the entry is not to be
    collected (collect/registry_builder.py documents the block), so onboard never collects it (issue #216)."""
    hold = p.get("collectionHold")
    return hold if hold else None


def hold_phrase(p: dict) -> str:
    hold = collection_hold(p)
    if not isinstance(hold, dict):
        return "collectionHold (no reason given)"
    since = f", since {hold['since']}" if hold.get("since") else ""
    return f"collectionHold {hold.get('reason') or '(no reason given)'}{since}"


def cmd_onboard(args):
    reg = common.load_registry()
    if (args.slug == "--all" or args.all) and (args.more_slugs or args.slugs_file):
        # the batch syntax is new (issue #143), so refusing the combination changes no command that
        # worked before; `onboard --all <one slug>` still ignores the slug, as it always has
        common.log("!! onboard refuses: --all and an explicit slug list (more slugs, or --slugs-file) are two "
                   "different batches. Name one of them. Nothing was collected.")
        return 2
    if args.slug == "--all" or args.all:
        # entries under a collectionHold are never part of the batch (issue #216); each is named, before
        # the guard, so a refused command still says which programs it left out and why
        held = batch_held(reg, conference=args.conference)
        for p in held:
            common.log(f"onboard skips {p['slug']}: {hold_phrase(p)}")
        # checked before rpi.history/current, so a refused command makes no request at all
        refusal = batch_refusal(reg, conference=args.conference, limit=args.limit, max_batch=args.max_batch,
                                allow_divisions=args.collect_staged_divisions.split(","))
        if refusal:
            for line in refusal:
                common.log(line)
            return 2
        if held and not batch_todo(reg, conference=args.conference, limit=args.limit):
            common.log(f"onboard --all: nothing to collect - every program it would have taken is under a "
                       f"collectionHold ({len(held)} skipped). Nothing was collected.")
            return 0
    slugs = explicit_slugs(args)
    if slugs:
        known = {p.get("slug"): p for p in reg.get("programs") or []}
        held_slugs = [s for s in slugs if s in known and collection_hold(known[s])]
        if held_slugs and len(slugs) == 1:
            # one program, named explicitly: refused, never silently skipped (issue #216). Overriding a
            # hold is a decision of its own and would need its own flag; there is none.
            p = known[slugs[0]]
            hold = collection_hold(p)
            evidence = hold.get("evidence") if isinstance(hold, dict) else None
            common.log(f"!! onboard refuses {p['slug']}: it is under a {hold_phrase(p)}. Nothing was collected.")
            if evidence:
                common.log(f"   {evidence}")
            common.log("   A collection hold is a decision that this program is not to be collected; lift it in the "
                       "registry first if that decision has changed.")
            return 2
        for s in held_slugs:
            common.log(f"onboard skips {s}: {hold_phrase(known[s])}")
        if held_slugs and len(held_slugs) == len(slugs):
            common.log(f"!! onboard refuses this batch of {len(slugs)} programs: every one is under a collectionHold. "
                       f"Nothing was collected.")
            return 2
        batch_form = len(slugs) > 1
        slugs = [s for s in slugs if s not in held_slugs]
        # one slug or many (owner's decision on #172): same shape as the --all guard above, checked
        # and refused before any request is made
        refusal = onboard_batch_refusal(reg, slugs, allow_divisions=args.collect_staged_divisions.split(","))
        if refusal:
            for line in refusal:
                common.log(line)
            return 2
    from collect import rpi
    rpi.history(reg)
    try:
        rpi.current(reg)
    except Exception as e:
        common.log(f"!! rpi current failed: {e}")
    if args.slug == "--all" or args.all:
        return onboard_all(reg, bios=not args.no_bios, limit=args.limit, conference=args.conference)
    if slugs and batch_form:
        # a list stays the batch form even when skipping held entries leaves one program
        return onboard_batch(reg, slugs, bios=not args.no_bios, workers=args.workers)
    slug = slugs[0] if slugs else args.slug
    program = common.get_program(slug, reg)
    if not program.get("onboarded"):
        reg = _mark_onboarded(slug)
        program = common.get_program(slug, reg)
    # the head coach's bio is fetched on onboard even with --no-bios (issue #168): one request, a host already visited
    results = [run_collector(c, program, reg, bios=not args.no_bios, coach_bios=True) for c in COLLECTORS]  # no short-circuit
    ok = all(results)
    import build
    build.build(reg)
    return 0 if ok else 1


# The largest conference in the registry is the Big Ten with 18 programs, and the batch plan on #94
# collects one conference at a time so each batch can be audited before the next. 25 sits above any
# single conference with room to spare and far below a division: PR #137 stages 261 D2 programs, and
# `onboard --all` would have collected against all 261 live athletics sites in one pass (issue #138).
# At ten or so requests per program and the per-host gap, 25 programs is about twenty minutes of
# collection - a batch somebody can actually read through afterwards.
MAX_BATCH = 25


def batch_todo(reg, *, conference: str | None = None, limit: int | None = None) -> list[dict]:
    """The programs `onboard --all` would collect, in order, after --conference and --limit. An entry under
    a collectionHold is never one of them (issue #216), and --limit counts only the programs it can take."""
    todo = [p for p in reg["programs"] if not p.get("onboarded") and not collection_hold(p)]
    if conference:
        todo = [p for p in todo if (p.get("conference") or "").casefold() == conference.casefold()]
    if limit:
        todo = todo[:limit]
    return todo


def batch_held(reg, *, conference: str | None = None) -> list[dict]:
    """The uncollected programs `onboard --all` (after --conference) leaves out because of a collectionHold."""
    held = [p for p in reg["programs"] if not p.get("onboarded") and collection_hold(p)]
    if conference:
        held = [p for p in held if (p.get("conference") or "").casefold() == conference.casefold()]
    return held


def batch_refusal(reg, *, conference: str | None = None, limit: int | None = None,
                  max_batch: int = MAX_BATCH, allow_divisions: "list[str] | tuple[str, ...]" = ()) -> list[str]:
    """The lines to print instead of collecting, or [] when the batch may go ahead.

    Two independent rules, because they protect different things:

      * **a division the site does not publish yet.** `onboardedDivisions` is what build.py
        publishes; a program staged in the registry for a division outside it is not meant to be
        collected as part of a sweep, one conference at a time is the plan (#94), and the whole
        division would be hundreds of sites at once.
      * **a batch bigger than MAX_BATCH**, whatever the division. This one also catches a staged
        division that somebody remembered to allow but not to size.

    Both are lifted by arguments rather than an environment variable, deliberately: an argument is
    one command, visible in the shell history that ran it, where an environment variable applies to
    every command in a process and outlives the intent that set it. `--collect-staged-divisions`
    takes the divisions it allows rather than being a bare switch, and naming a division this batch
    would not collect is itself a refusal - the shape #112 settled on for `--allow-unexplained-prune`,
    where the override has to say what it is allowing and is checked against what is actually there.
    """
    todo = batch_todo(reg, conference=conference, limit=limit)
    if not todo:
        return []
    published = reg.get("onboardedDivisions")
    staged = sorted({(p.get("division") or "?") for p in todo} - set(published or [])) if published else []
    allowed = {d.strip().upper() for d in allow_divisions if d.strip()}
    unmet = [d for d in staged if d.upper() not in allowed]
    unused = sorted(allowed - {d.upper() for d in staged})
    by_conf = collections.Counter((p.get("division") or "?", p.get("conference") or "?") for p in todo)
    reasons = []
    if unmet:
        reasons.append(f"it spans {', '.join(unmet)}, which the site does not publish yet "
                       f"(registry onboardedDivisions is {published})")
    if unused:
        reasons.append(f"--collect-staged-divisions names {', '.join(unused)}, which this batch would not collect"
                       + (f" (it is {', '.join(staged)} that is staged here)" if staged else " (nothing here is staged)"))
    if len(todo) > max_batch:
        reasons.append(f"it is {len(todo)} programs, over the {max_batch} this command will collect in one pass")
    if not reasons:
        return []
    lines = [f"!! onboard --all refuses this batch: {'; and '.join(reasons)}.",
             f"   Nothing was collected. The batch would have been {len(todo)} programs across "
             f"{len({c for _, c in by_conf})} conference(s):"]
    for (div, conf), n in by_conf.most_common(8):
        lines.append(f"     {div} {conf}: {n}")
    if len(by_conf) > 8:
        lines.append(f"     ... and {len(by_conf) - 8} more conference(s)")
    if unmet and not unused and len(todo) <= max_batch and conference:
        # already the shape the plan asks for: one conference, within the limit. The only thing
        # missing is somebody saying they mean to collect a division the site does not publish.
        lines.append(f"   This is already one conference and within the limit. Re-run the same command with "
                     f"--collect-staged-divisions {','.join(unmet)} if you mean to collect a division that is "
                     f"only staged.")
    else:
        # Name a batch this command would actually accept: the largest conference that fits under
        # max_batch, or the largest one with a --limit when no conference fits on its own. Advice
        # that would be refused a second time is worse than no advice.
        within = [(c, n) for c, n in by_conf.most_common() if n <= max_batch]
        (_, conf), n = within[0] if within else by_conf.most_common(1)[0]
        suggestion = f"     python collegedash.py onboard --all --conference \"{conf}\""
        if n > max_batch:
            suggestion += f" --limit {max_batch}"
        if staged:
            suggestion += f" --collect-staged-divisions {','.join(staged)}"
        lines += [
            "   Collect a batch at a time instead, so each one can be audited before the next (issue #94):",
            suggestion,
            "     python collegedash.py onboard <slug>            one program at a time, by slug",
        ]
        lines.append(f"   To override deliberately, on this one command: --max-batch N raises the {max_batch}-program "
                     f"limit" + (f", and --collect-staged-divisions {','.join(staged)} allows the staged division."
                                 if staged else "."))
    return lines


def onboard_all(reg, *, bios: bool, limit: int | None, conference: str | None = None) -> int:
    """Onboard every registry program not yet marked onboarded. Resumable: each program is marked
    in the registry as soon as its collectors finish, and the site is rebuilt every 10 programs.

    The batch this will collect is whatever batch_refusal() has already allowed: cmd_onboard calls it
    first and returns 2 without making a request when it refuses."""
    import build
    todo = batch_todo(reg, conference=conference, limit=limit)
    common.log(f"onboard --all: {len(todo)} programs to go ({len(reg['programs']) - len(todo)} done)")
    failures = {}
    for i, program in enumerate(todo, 1):
        common.log(f"===== [{i}/{len(todo)}] {program['slug']} ({program['ids'].get('ncaaName')})")
        results = {c: run_collector(c, program, reg, bios=bios, coach_bios=True) for c in COLLECTORS}
        failed = [c for c, ok in results.items() if not ok]
        if failed:
            failures[program["slug"]] = failed
        # locked read-modify-write: athletics may have written the detected platform meanwhile.
        # Per-collector outcomes live in refresh-state (build.py folds them into _build.failed).
        reg = _mark_onboarded(program["slug"])
        if i % 10 == 0 or i == len(todo):
            try:
                build.build(reg)
            except Exception as e:
                common.log(f"!! build failed: {e}")
    common.update_refresh_state("onboardAll", {"done": len(todo), "failures": failures})
    common.log(f"onboard --all finished: {len(todo) - len(failures)} clean, {len(failures)} with issues")
    for slug, f in failures.items():
        common.log(f"   {slug}: {', '.join(f)}")
    return 0 if not failures else 1


def onboard_batch_refusal(reg, slugs: list[str], *, allow_divisions: "list[str] | tuple[str, ...]" = ()) -> list[str]:
    """The lines to print instead of collecting an explicit list of slugs, or [] to go ahead.

    Only one of batch_refusal()'s two rules applies to a named list: the division rule, not the
    MAX_BATCH size cap. The cap exists to stop --all from silently sweeping a whole division in one
    pass (issue #138); a list somebody typed out, or put one per line in a file, is already exactly
    as big as they meant it to be - there is no "--all forgot to filter" failure mode here for a size
    limit to catch. The division rule still matters just as much: naming a slug whose division
    registry.onboardedDivisions does not list is the same mistake --all is guarded against, made
    explicitly instead of by a filter that swept too wide (issue #143). --collect-staged-divisions is
    the same override either way, because it is the same rule."""
    unknown = [s for s in slugs if not any(p.get("slug") == s for p in reg.get("programs") or [])]
    if unknown:
        return [f"!! onboard refuses this batch: unknown slug(s) {', '.join(unknown)}. Nothing was collected."]
    todo = [common.get_program(s, reg) for s in slugs]
    published = reg.get("onboardedDivisions")
    staged = sorted({(p.get("division") or "?") for p in todo} - set(published or [])) if published else []
    allowed = {d.strip().upper() for d in allow_divisions if d.strip()}
    unmet = [d for d in staged if d.upper() not in allowed]
    unused = sorted(allowed - {d.upper() for d in staged})
    reasons = []
    if unmet:
        reasons.append(f"it names program(s) in {', '.join(unmet)}, which the site does not publish yet "
                       f"(registry onboardedDivisions is {published})")
    if unused:
        reasons.append(f"--collect-staged-divisions names {', '.join(unused)}, which this batch would not collect"
                       + (f" (it is {', '.join(staged)} that is staged here)" if staged else " (nothing here is staged)"))
    if not reasons:
        return []
    what = f"{slugs[0]}" if len(slugs) == 1 else f"this batch of {len(slugs)} programs"
    lines = [f"!! onboard refuses {what}: {'; and '.join(reasons)}.", "   Nothing was collected."]
    if staged:
        lines.append("   To override, on this one command: "
                     f"--collect-staged-divisions {','.join(staged)} names the staged division(s) you mean to collect.")
    else:
        lines.append("   Nothing here is staged, so drop --collect-staged-divisions.")
    return lines


def onboard_batch(reg, slugs: list[str], *, bios: bool, workers: int) -> int:
    """Onboard an explicit list of programs (issue #143): every collector for every one of them,
    then ONE build at the end - not one per program, which is what onboard <slug> run N times does.
    Like onboard <slug>, it does not run validate; that stays a separate command. cmd_onboard has
    already run onboard_batch_refusal() and returned 2 without a request when it refuses.

    Programs are marked onboarded before collection, as onboard <slug> does for its one program.
    The build reads the registry afresh, as refresh does, because the athletics collector writes the
    detected platform into it during collection.

    Concurrency is refresh's own collect_plan (issue #105), reused rather than reimplemented: the
    same per-host gate in collect.common applies to its plan whichever caller built it, so one
    program's collectors still run one after another in COLLECTORS order (camps mines the news
    archive), while different programs proceed side by side - and two that happen to share a host
    (SoccerWire, TopDrawerSoccer, Wikipedia) are still never sent two requests at once. Politeness is
    therefore exactly refresh's: the same User-Agent, the same per-host delay and Crawl-delay, and at
    most one worker per host, at any number of workers."""
    common.log(f"onboard: {len(slugs)} program(s) to go: {', '.join(slugs)}")
    clear_not_recorded()
    programs = []
    for slug in slugs:
        program = common.get_program(slug, reg)
        if not program.get("onboarded"):
            reg = _mark_onboarded(slug)  # locked read-modify-write; see onboard_all
            program = common.get_program(slug, reg)
        programs.append(program)
    plan = [(p, list(COLLECTORS)) for p in programs]
    results = collect_plan(plan, reg, bios=bios, coach_bios=True, workers=workers)
    failures: dict[str, list[str]] = {}
    for r in results:
        if r["outcome"] == "failed":
            failures.setdefault(r["program"], []).append(r["collector"])
    import build
    build.build(common.load_registry())
    common.update_refresh_state("onboardBatch", {"slugs": slugs, "failures": failures})
    common.log(f"onboard finished: {len(slugs) - len(failures)} clean, {len(failures)} with issues")
    for slug, cs in failures.items():
        common.log(f"   {slug}: {', '.join(cs)}")
    stale = not_recorded()
    if stale:
        common.log(f"!! refresh-state not recorded for {len(stale)} program(s): {', '.join(s for s, _, _ in stale)}. "
                   f"Their sources are on disk; their stored collector status is stale.")
    return 0 if not failures else 1


def cmd_refresh(args):
    reg = common.load_registry()
    only = [c.strip() for c in args.only.split(",")] if args.only else COLLECTORS
    unknown = [c for c in only if c not in COLLECTORS and c != "rpi"]
    if unknown:
        common.log(f"!! unknown collector(s) in --only: {', '.join(unknown)} (known: {', '.join(COLLECTORS)}, rpi)")
        return 2
    programs = [common.get_program(args.slug, reg)] if args.slug else list(common.iter_programs(reg))
    state = common.load_refresh_state() if args.failed else {}

    def wanted(p, c):
        if not args.failed:
            return True
        entry = state.get(f"{p['slug']}.{c}")
        return isinstance(entry, dict) and entry.get("ok") is False

    # COLLECTORS order, whatever order --only lists them in: camps mines the archive news writes, and
    # reads the roster page athletics already fetched this run (issue #284)
    plan = [(p, [c for c in COLLECTORS if c in only and wanted(p, c)]) for p in programs]
    plan = [(p, cs) for p, cs in plan if cs]
    run_rpi = "rpi" in only or (not args.only and not args.failed)
    if args.dry_run:
        for p, cs in plan:
            print(f"{p['slug']}: {', '.join(cs)}")
        total = sum(len(cs) for _, cs in plan)
        print(f"-- {len(plan)} programs, {total} collector runs" + (", plus rpi current" if run_rpi else ""))
        return 0
    clear_not_recorded()
    if any("camps" in cs for _, cs in plan):
        from collect import camps
        camps.configure(stored_link=args.camps_stored_link, retry_429=args.camps_retry_429)
    results = []
    if run_rpi:
        from collect import rpi
        try:
            rpi.current(reg)
            results.append({"program": "-", "collector": "rpi", "outcome": "ok", "error": ""})
        except Exception as e:
            common.log(f"!! rpi current failed: {e}")
            results.append({"program": "-", "collector": "rpi", "outcome": "failed", "error": common.error_text(e, 300)})
    # --coach-bios fetches the head coach's bio with player bios off (the weekly and full runs, issue #168);
    # without either, a run with player bios fetches it too, and a --no-bios run keeps the stored one
    results += collect_plan(plan, reg, bios=not args.no_bios, coach_bios=args.coach_bios or not args.no_bios,
                            workers=args.workers)
    if not plan and not run_rpi:
        common.log("nothing to refresh")
        return 0
    import build
    if any("camps" in cs for _, cs in plan):
        from collect import camps
        line = camps.refused_summary()  # this run's refused-camp-host counts (issue #284)
        if line:
            common.log(line)
        write_allsport_shadow(camps.allsport_shadow_summary)  # guarded: report only (#326)
    build.build(common.load_registry())
    return report_refresh(results, threshold=args.fail_threshold, mode=args.mode)


def collect_plan(plan: list[tuple[dict, list[str]]], reg: dict, *, bios: bool, workers: int,
                 coach_bios: bool | None = None) -> list[dict]:
    """Run every (program, collectors) pair of the plan and return the outcomes in plan order.

    workers <= 1 walks the programs one at a time, as before. With more, up to `workers` programs are
    collected at once (issue #94). Almost all of a sequential run is spent in the politeness gap of one
    athletics site while every other host sits idle; running programs side by side removes that idle
    time and nothing else, because the gap is enforced per host inside collect.common, for every
    request and redirect hop, whichever thread sends it. Hosts every program uses (SoccerWire,
    TopDrawerSoccer, Wikipedia) stay one request at a time at the configured gap and set the pace.

    Within a program the collectors run strictly one after another in COLLECTORS order (camps mines
    the archive news just wrote), and a program's files are written only by its own worker. Each
    program's refresh-state entries are written in ONE locked read-modify-write when its collectors
    are done, not one per collector: at 1,050 programs the file is ~800 KB, and a write per collector
    run made the lock the bottleneck and, with the old timeout, a way to crash the run (PR #105).
    Nothing a program does can raise out of its worker, so one program cannot cancel the programs
    still queued. The returned list is in plan order whatever order programs finish in, so the
    summary, lastRun and the exit code are the ones a sequential run would produce."""
    def one(program: dict, collectors: list[str]) -> list[dict]:
        results, entries = [], {}
        try:
            for c in collectors:
                r, entry = collect_one(c, program, reg, bios=bios, coach_bios=coach_bios)
                results.append(r)
                if entry is not None:
                    entries[f"{program['slug']}.{c}"] = entry
        except Exception as e:  # collect_one does not raise; this is the belt to its braces
            common.log(f"!! {program['slug']}: worker error after {len(results)} of {len(collectors)} collectors: {e}")
            common.log_traceback()
            for c in collectors[len(results):]:
                results.append({"program": program["slug"], "collector": c, "outcome": "failed", "error": common.error_text(e, 300)})
        finally:
            if entries:
                record_outcomes(program["slug"], entries)
        return results

    if workers <= 1 or len(plan) <= 1:
        return [r for p, cs in plan for r in one(p, cs)]

    from concurrent.futures import ThreadPoolExecutor

    def worker(item):
        program, collectors = item
        common.set_log_context(program["slug"])
        try:
            return one(program, collectors)
        finally:
            common.set_log_context(None)

    common.log(f"refresh: {len(plan)} programs on {min(workers, len(plan))} workers")
    with ThreadPoolExecutor(max_workers=min(workers, len(plan)), thread_name_prefix="collect") as pool:
        # map() yields in submission order; `one` raises no Exception, so no program is cancelled
        return [r for rs in pool.map(worker, plan) for r in rs]


SHADOW_REPORT_FAILURES = 0  # #326: shadow report writes that raised this process (report only, never fatal)


def write_allsport_shadow(summary) -> bool:
    """#326 PR A: the camps all-sport shadow report goes to the run log and, on GitHub Actions, to the
    step Summary as its own block. Never to a committed file (#235).

    `summary` is the callable that builds the lines (camps.allsport_shadow_summary), called here so
    that building AND writing sit inside one guard: this is report-only code running before the build
    and report_refresh, so an error in it (an OSError on GITHUB_STEP_SUMMARY, a bad row) is logged,
    warned and counted, and the refresh carries on. False when it failed."""
    global SHADOW_REPORT_FAILURES
    try:
        lines = summary()
        if not lines:
            return True
        for ln in lines:
            common.log(ln)
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write("## Camps all-sport shadow (#326)\n\n" + lines[0] + "\n\n")
                if len(lines) > 1:
                    f.write("```\n" + "\n".join(lines[1:]) + "\n```\n\n")
        return True
    except Exception as e:  # noqa: BLE001 - a report must never mark the refresh as crashed
        SHADOW_REPORT_FAILURES += 1
        msg = f"camps all-sport shadow report failed (report only; the refresh continues): {common.error_text(e, 200)}"
        common.log(f"!! {msg}")
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning title=camps shadow (#326)::{msg}")
        return False


def report_refresh(results: list[dict], *, threshold: float, mode: str) -> int:
    """Print the run summary, record it in refresh-state as lastRun, annotate GitHub Actions, and
    return the exit code: 0 when the failed share is within the threshold, 1 when above it."""
    total = len(results)
    # every error below is printed, annotated, written to the step summary and committed in refresh-state:
    # redact it once here (issue #258), whatever wrote it
    failed = [{**r, "error": common.redact(r.get("error"))} for r in results if r["outcome"] == "failed"]
    skipped = sum(1 for r in results if r["outcome"] == "skipped")
    ok = total - len(failed) - skipped
    share = len(failed) / total if total else 0.0
    exceeded = share > threshold
    stale = not_recorded()
    common.log(f"refresh summary: {total} runs, {ok} ok, {skipped} skipped, {len(failed)} failed "
               f"({share:.1%}, threshold {threshold:.0%}){' - THRESHOLD EXCEEDED' if exceeded else ''}")
    for r in failed:
        common.log(f"   {r['program']:24} {r['collector']:10} {r['error'][:120]}")
    if stale:
        common.log(f"!! refresh-state not recorded for {len(stale)} program(s), "
                   f"{sum(n for _, n, _ in stale)} entries: {', '.join(s for s, _, _ in stale[:20])}"
                   f"{' …' if len(stale) > 20 else ''}. Their stored status is stale; this run's summary is not.")
    common.update_refresh_state("lastRun", {
        "mode": mode, "total": total, "ok": ok, "skipped": skipped, "failed": len(failed),
        "failedShare": round(share, 4), "threshold": threshold, "exceeded": exceeded,
        "failures": [{k: r[k] for k in ("program", "collector", "error")} for r in failed[:100]],
        "notRecorded": {"programs": len(stale), "entries": sum(n for _, n, _ in stale),
                        "slugs": [s for s, _, _ in stale[:100]]},
    })
    if os.environ.get("GITHUB_ACTIONS"):
        for r in failed:
            print(f"::warning title=refresh: {r['collector']} failed for {r['program']}::{r['error'][:200]}")
        if stale:
            print(f"::warning title=refresh::refresh-state was not recorded for {len(stale)} program(s) "
                  f"({sum(n for _, n, _ in stale)} entries). Their published collector status and "
                  f"`refresh --failed` selection are stale until the next run records them.")
        if exceeded:
            print(f"::error title=refresh::{share:.1%} of collector runs failed (threshold {threshold:.0%}); the flow needs attention")
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(f"## Refresh ({mode})\n\n{total} collector runs: **{ok} ok**, {skipped} skipped, "
                        f"**{len(failed)} failed** ({share:.1%}, threshold {threshold:.0%})"
                        f"{' - **threshold exceeded**' if exceeded else ''}\n\n")
                if stale:
                    f.write(f"**refresh-state not recorded for {len(stale)} program(s)** "
                            f"({sum(n for _, n, _ in stale)} entries): {', '.join(s for s, _, _ in stale[:20])}. "
                            f"Their stored per-collector status is stale.\n\n")
                if failed:
                    f.write("| Program | Collector | Error |\n|---|---|---|\n")
                    for r in failed[:100]:
                        f.write(f"| {r['program']} | {r['collector']} | {r['error'][:160].replace('|', '/')} |\n")
                    if len(failed) > 100:
                        f.write(f"\n… and {len(failed) - 100} more\n")
    return 1 if exceeded else 0


def cmd_sweep(args):
    reg = common.load_registry()
    years = [int(y) for y in args.years.split(",")] if args.years else None
    if args.source in ("tds", "all"):
        from collect import commitments_tds
        commitments_tds.sweep(reg, years)
    if args.source in ("soccerwire", "all"):
        from collect import commitments_soccerwire
        commitments_soccerwire.sweep(reg, years)
    common.update_refresh_state("sweep", {"source": args.source, "years": years})
    return 0


def cmd_rpi(args):
    reg = common.load_registry()
    from collect import rpi
    if args.what in ("history", "all"):
        print(rpi.history(reg, force=args.force))
    if args.what in ("current", "all"):
        d = rpi.current(reg)
        print(f"through {d['throughGames']}: " + ", ".join(f"{t['rank']}. {t['school']}" for t in d["teams"][:10]))
    return 0


def cmd_registry(args):
    reg = common.load_registry()
    from collect import registry_builder
    if args.what == "tidy":
        def mutate(r):
            n = sum(1 for p in r["programs"] if p.pop("onboardIssues", None) is not None)
            common.log(f"registry tidy: removed onboardIssues from {n} programs")
        common.update_registry(mutate)
        return 0
    if args.what == "fix-wiki":
        registry_builder.fix_wiki(reg, apply=args.apply, slugs=args.slug.split(",") if args.slug else None)
        return 0
    if args.what == "colors" and args.source == "site":  # issue #276: the program's own athletics site
        from collect import site_colors
        slugs = args.slug.split(",") if args.slug else None
        if args.apply:
            site_colors.apply_report(slugs=slugs)
        else:
            site_colors.run(reg, slugs=slugs)
        return 0
    if args.what == "colors":
        registry_builder.fill_colors(reg, apply=args.apply, slugs=args.slug.split(",") if args.slug else None)
        return 0
    report = registry_builder.build(reg, limit=args.limit)
    print(json.dumps({"counts": report["counts"], "lowConfidence": report["lowConfidence"][:40],
                      "unmatched": report["unmatched"]}, indent=1, ensure_ascii=False))
    return 0


def cmd_build(args):
    import build
    build.build(common.load_registry())
    return 0


def cmd_validate(args):
    import build
    return 0 if build.validate(common.load_registry(), verbose=True) else 1


def cmd_serve(args):
    import serve
    serve.main(port=args.port)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("onboard"); p.add_argument("slug", nargs="?", default="")
    p.add_argument("more_slugs", nargs="*", metavar="slug", default=[],
                   help="more slugs, for the batch form (issue #143): collects every one, then builds and "
                        "validates once at the end, instead of once per program")
    p.add_argument("--slugs-file", metavar="PATH",
                   help="a file of slugs, one per line (blank lines and #-comments ignored), combined with "
                        "any named directly. Two or more slugs in total is the batch form above")
    p.add_argument("--all", action="store_true"); p.add_argument("--limit", type=int); p.add_argument("--no-bios", action="store_true")
    p.add_argument("--conference", help="with --all: only programs in this conference (the batch shape the plan on #94 uses)")
    p.add_argument("--max-batch", type=int, default=MAX_BATCH,
                   help=f"with --all: programs this command will collect in one pass (default {MAX_BATCH}). "
                        "Raising it is a one-shot decision, made on the command that collects")
    p.add_argument("--collect-staged-divisions", default="", metavar="DIVISION[,DIVISION]",
                   help="with --all or an explicit slug list: allow this batch to collect these staged "
                        "divisions, which registry.onboardedDivisions does not list yet (e.g. D2). Naming a "
                        "division the batch would not collect is a refusal, not a no-op")
    p.add_argument("--workers", type=int, default=int(os.environ.get("COLLEGEDASH_WORKERS", "16")),
                   help="with a batch of two or more explicit slugs: programs collected at once (default 16, "
                        "env COLLEGEDASH_WORKERS; 1 = one at a time). Per-host politeness is refresh's own "
                        "and does not change with this number (issue #143, #105)")
    p.set_defaults(fn=cmd_onboard)
    p = sub.add_parser("refresh"); p.add_argument("--only"); p.add_argument("--slug"); p.add_argument("--no-bios", action="store_true")
    p.add_argument("--coach-bios", action="store_true",
                   help="fetch each head coach's bio page (one request per program) even with --no-bios; without it a "
                        "--no-bios run keeps the stored head-coach bio (issue #168)")
    p.add_argument("--camps-stored-link", action="store_true",
                   help="camps: reuse each program's stored camp link instead of fetching the roster page to find it "
                        "(refresh.yml's Jan-Jul non-Monday runs; issue #284)")
    p.add_argument("--camps-retry-429", action="store_true",
                   help="camps: give each camp host recorded for a 429 at least 7 days ago one retry "
                        "(refresh.yml's Monday run; issue #284)")
    p.add_argument("--failed", action="store_true", help="only collectors whose last run failed (per refresh-state)")
    p.add_argument("--dry-run", action="store_true", help="print what would run, run nothing")
    p.add_argument("--fail-threshold", type=float, default=float(os.environ.get("COLLEGEDASH_FAIL_THRESHOLD", "0.05")),
                   help="share of collector runs allowed to fail before the run counts as failed (default 0.05, env COLLEGEDASH_FAIL_THRESHOLD)")
    p.add_argument("--mode", default="manual", help="label recorded with the run summary (daily, weekly, full, manual)")
    p.add_argument("--workers", type=int, default=int(os.environ.get("COLLEGEDASH_WORKERS", "16")),
                   help="programs collected at once (default 16, env COLLEGEDASH_WORKERS; 1 = the sequential walk). "
                        "Per-host politeness is the same at any value")
    p.set_defaults(fn=cmd_refresh)
    p = sub.add_parser("sweep"); p.add_argument("source", nargs="?", default="all", choices=["tds", "soccerwire", "all"]); p.add_argument("--years"); p.set_defaults(fn=cmd_sweep)
    p = sub.add_parser("rpi"); p.add_argument("what", nargs="?", default="all", choices=["history", "current", "all"]); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_rpi)
    p = sub.add_parser("registry"); p.add_argument("what", nargs="?", default="build", choices=["build", "tidy", "fix-wiki", "colors"]); p.add_argument("--limit", type=int)
    p.add_argument("--apply", action="store_true", help="fix-wiki/colors: write the results to the registry"); p.add_argument("--slug")
    p.add_argument("--source", choices=["wikipedia", "site"], default="wikipedia",
                   help="colors: Wikipedia's colour table (default) or each program's athletics site (#276; dry run "
                        "writes data/colors-site-report.json, --apply writes that reviewed report's colours)")
    p.set_defaults(fn=cmd_registry)
    p = sub.add_parser("build"); p.set_defaults(fn=cmd_build)
    p = sub.add_parser("validate"); p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=8000); p.set_defaults(fn=cmd_serve)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # exit 2 = the command itself crashed (vs 1 = too many collectors failed)
        traceback.print_exc()
        sys.exit(2)
