#!/usr/bin/env python3
"""
CollegeDash command line.

  python collegedash.py onboard <slug> [--no-bios]      run every collector for one program, then build
  python collegedash.py refresh [--only a,b] [--slug s]  refresh collectors for onboarded programs (scheduled job)
  python collegedash.py sweep [tds|soccerwire|all] [--years 2027,2028]
  python collegedash.py rpi [history|current|all] [--force]
  python collegedash.py build                            merge programs/* -> public/data
  python collegedash.py validate                         schema + completeness report
  python collegedash.py serve [--port 8000]              local static server (public/) with write endpoints

Collectors: athletics, scorecard, climate, wikipedia, tds, soccerwire, news, rpi
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback

from collect import common

COLLECTORS = ["scorecard", "climate", "wikipedia", "athletics", "tds", "soccerwire", "news"]


def run_collector(name: str, program: dict, registry: dict, **kw) -> bool:
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
        else:
            common.log(f"unknown collector {name}")
            return False
        common.update_refresh_state(f"{program['slug']}.{name}", {"ok": True})
        return True
    except Exception as e:  # keep going; partial progress is still committed
        common.log(f"!! {name} failed for {program['slug']}: {e}")
        traceback.print_exc()
        common.update_refresh_state(f"{program['slug']}.{name}", {"ok": False, "error": str(e)})
        return False


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
        program["onboarded"] = True
        common.save_registry(reg)
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
        # re-read registry: athletics may have written the detected platform
        reg = common.load_registry()
        for p in reg["programs"]:
            if p["slug"] == program["slug"]:
                p["onboarded"] = True
                p["onboardedAt"] = common.today()
                if failed:
                    p["onboardIssues"] = failed
        common.save_registry(reg)
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
    programs = [common.get_program(args.slug, reg)] if args.slug else list(common.iter_programs(reg))
    ok = True
    if "rpi" in only or not args.only:
        from collect import rpi
        try:
            rpi.current(reg)
        except Exception as e:
            common.log(f"!! rpi current failed: {e}")
            ok = False
    for p in programs:
        for c in only:
            if c in COLLECTORS:
                ok = run_collector(c, p, reg, bios=not args.no_bios) and ok
    import build
    build.build(reg)
    return 0 if ok else 1


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
    p = sub.add_parser("refresh"); p.add_argument("--only"); p.add_argument("--slug"); p.add_argument("--no-bios", action="store_true"); p.set_defaults(fn=cmd_refresh)
    p = sub.add_parser("sweep"); p.add_argument("source", nargs="?", default="all", choices=["tds", "soccerwire", "all"]); p.add_argument("--years"); p.set_defaults(fn=cmd_sweep)
    p = sub.add_parser("rpi"); p.add_argument("what", nargs="?", default="all", choices=["history", "current", "all"]); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_rpi)
    p = sub.add_parser("registry"); p.add_argument("what", nargs="?", default="build", choices=["build"]); p.add_argument("--limit", type=int); p.set_defaults(fn=cmd_registry)
    p = sub.add_parser("build"); p.set_defaults(fn=cmd_build)
    p = sub.add_parser("validate"); p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=8000); p.set_defaults(fn=cmd_serve)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
