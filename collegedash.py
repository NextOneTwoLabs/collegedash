#!/usr/bin/env python3
"""
CollegeDash command line.

  python collegedash.py onboard <slug> [--no-bios]      run every collector for one program, then build
  python collegedash.py refresh [--only a,b] [--slug s]  refresh collectors for onboarded programs (scheduled job)
                                [--failed] [--dry-run]   --failed: only collectors whose last run failed
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
import json
import os
import sys
import traceback

from collect import common

COLLECTORS = ["scorecard", "climate", "wikipedia", "athletics", "tds", "soccerwire", "news", "camps"]  # camps after news: it mines the news archive


def run_collector(name: str, program: dict, registry: dict, **kw) -> bool:
    """Run one collector for one program; True unless it failed. See run_collector_outcome for detail."""
    return run_collector_outcome(name, program, registry, **kw)["outcome"] != "failed"


def run_collector_outcome(name: str, program: dict, registry: dict, **kw) -> dict:
    """{"program", "collector", "outcome": ok|skipped|failed, "error"} - records the result in refresh-state."""
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
            m.collect(program, registry, bios=kw.get("bios", True))
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
            return r
        common.update_refresh_state(f"{program['slug']}.{name}", {"ok": True})
        return r
    except common.SkipCollector as e:  # nothing to collect for this program; not a failure
        common.log(f"-- {name} skipped for {program['slug']}: {e}")
        common.update_refresh_state(f"{program['slug']}.{name}", {"ok": True, "skipped": str(e)[:300]})
        r.update(outcome="skipped", error=str(e)[:300])
        return r
    except Exception as e:  # keep going; partial progress is still committed
        common.log(f"!! {name} failed for {program['slug']}: {e}")
        traceback.print_exc()
        common.update_refresh_state(f"{program['slug']}.{name}", {"ok": False, "error": str(e)[:300]})
        r.update(outcome="failed", error=str(e)[:300])
        return r


def _mark_onboarded(slug: str) -> dict:
    def mutate(reg):
        for p in reg["programs"]:
            if p["slug"] == slug:
                p["onboarded"] = True
                p.setdefault("onboardedAt", common.today())
    return common.update_registry(mutate)


def cmd_onboard(args):
    reg = common.load_registry()
    from collect import rpi
    rpi.history(reg)
    try:
        rpi.current(reg)
    except Exception as e:
        common.log(f"!! rpi current failed: {e}")
    if args.slug == "--all" or args.all:
        return onboard_all(reg, bios=not args.no_bios, limit=args.limit)
    program = common.get_program(args.slug, reg)
    if not program.get("onboarded"):
        reg = _mark_onboarded(args.slug)
        program = common.get_program(args.slug, reg)
    results = [run_collector(c, program, reg, bios=not args.no_bios) for c in COLLECTORS]  # no short-circuit
    ok = all(results)
    import build
    build.build(reg)
    return 0 if ok else 1


def onboard_all(reg, *, bios: bool, limit: int | None) -> int:
    """Onboard every registry program not yet marked onboarded. Resumable: each program is marked
    in the registry as soon as its collectors finish, and the site is rebuilt every 10 programs."""
    import build
    todo = [p for p in reg["programs"] if not p.get("onboarded")]
    if limit:
        todo = todo[:limit]
    common.log(f"onboard --all: {len(todo)} programs to go ({len(reg['programs']) - len(todo)} done)")
    failures = {}
    for i, program in enumerate(todo, 1):
        common.log(f"===== [{i}/{len(todo)}] {program['slug']} ({program['ids'].get('ncaaName')})")
        results = {c: run_collector(c, program, reg, bios=bios) for c in COLLECTORS}
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

    plan = [(p, [c for c in only if c in COLLECTORS and wanted(p, c)]) for p in programs]
    plan = [(p, cs) for p, cs in plan if cs]
    run_rpi = "rpi" in only or (not args.only and not args.failed)
    if args.dry_run:
        for p, cs in plan:
            print(f"{p['slug']}: {', '.join(cs)}")
        total = sum(len(cs) for _, cs in plan)
        print(f"-- {len(plan)} programs, {total} collector runs" + (", plus rpi current" if run_rpi else ""))
        return 0
    results = []
    if run_rpi:
        from collect import rpi
        try:
            rpi.current(reg)
            results.append({"program": "-", "collector": "rpi", "outcome": "ok", "error": ""})
        except Exception as e:
            common.log(f"!! rpi current failed: {e}")
            results.append({"program": "-", "collector": "rpi", "outcome": "failed", "error": str(e)[:300]})
    for p, cs in plan:
        for c in cs:
            results.append(run_collector_outcome(c, p, reg, bios=not args.no_bios))
    if not plan and not run_rpi:
        common.log("nothing to refresh")
        return 0
    import build
    build.build(common.load_registry())
    return report_refresh(results, threshold=args.fail_threshold, mode=args.mode)


def report_refresh(results: list[dict], *, threshold: float, mode: str) -> int:
    """Print the run summary, record it in refresh-state as lastRun, annotate GitHub Actions, and
    return the exit code: 0 when the failed share is within the threshold, 1 when above it."""
    total = len(results)
    failed = [r for r in results if r["outcome"] == "failed"]
    skipped = sum(1 for r in results if r["outcome"] == "skipped")
    ok = total - len(failed) - skipped
    share = len(failed) / total if total else 0.0
    exceeded = share > threshold
    common.log(f"refresh summary: {total} runs, {ok} ok, {skipped} skipped, {len(failed)} failed "
               f"({share:.1%}, threshold {threshold:.0%}){' - THRESHOLD EXCEEDED' if exceeded else ''}")
    for r in failed:
        common.log(f"   {r['program']:24} {r['collector']:10} {r['error'][:120]}")
    common.update_refresh_state("lastRun", {
        "mode": mode, "total": total, "ok": ok, "skipped": skipped, "failed": len(failed),
        "failedShare": round(share, 4), "threshold": threshold, "exceeded": exceeded,
        "failures": [{k: r[k] for k in ("program", "collector", "error")} for r in failed[:100]],
    })
    if os.environ.get("GITHUB_ACTIONS"):
        for r in failed:
            print(f"::warning title=refresh: {r['collector']} failed for {r['program']}::{r['error'][:200]}")
        if exceeded:
            print(f"::error title=refresh::{share:.1%} of collector runs failed (threshold {threshold:.0%}); the flow needs attention")
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(f"## Refresh ({mode})\n\n{total} collector runs: **{ok} ok**, {skipped} skipped, "
                        f"**{len(failed)} failed** ({share:.1%}, threshold {threshold:.0%})"
                        f"{' - **threshold exceeded**' if exceeded else ''}\n\n")
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
    p = sub.add_parser("onboard"); p.add_argument("slug", nargs="?", default=""); p.add_argument("--all", action="store_true"); p.add_argument("--limit", type=int); p.add_argument("--no-bios", action="store_true"); p.set_defaults(fn=cmd_onboard)
    p = sub.add_parser("refresh"); p.add_argument("--only"); p.add_argument("--slug"); p.add_argument("--no-bios", action="store_true")
    p.add_argument("--failed", action="store_true", help="only collectors whose last run failed (per refresh-state)")
    p.add_argument("--dry-run", action="store_true", help="print what would run, run nothing")
    p.add_argument("--fail-threshold", type=float, default=float(os.environ.get("COLLEGEDASH_FAIL_THRESHOLD", "0.05")),
                   help="share of collector runs allowed to fail before the run counts as failed (default 0.05, env COLLEGEDASH_FAIL_THRESHOLD)")
    p.add_argument("--mode", default="manual", help="label recorded with the run summary (daily, weekly, full, manual)")
    p.set_defaults(fn=cmd_refresh)
    p = sub.add_parser("sweep"); p.add_argument("source", nargs="?", default="all", choices=["tds", "soccerwire", "all"]); p.add_argument("--years"); p.set_defaults(fn=cmd_sweep)
    p = sub.add_parser("rpi"); p.add_argument("what", nargs="?", default="all", choices=["history", "current", "all"]); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_rpi)
    p = sub.add_parser("registry"); p.add_argument("what", nargs="?", default="build", choices=["build", "tidy", "fix-wiki", "colors"]); p.add_argument("--limit", type=int)
    p.add_argument("--apply", action="store_true", help="fix-wiki/colors: write the results to the registry"); p.add_argument("--slug"); p.set_defaults(fn=cmd_registry)
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
