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
    program = common.get_program(args.slug, reg)
    if not program.get("onboarded"):
        program["onboarded"] = True
        common.save_registry(reg)
    from collect import rpi
    rpi.history(reg)
    try:
        rpi.current(reg)
    except Exception as e:
        common.log(f"!! rpi current failed: {e}")
    results = [run_collector(c, program, reg, bios=not args.no_bios) for c in COLLECTORS]  # no short-circuit
    ok = all(results)
    import build
    build.build(reg)
    return 0 if ok else 1


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
    p = sub.add_parser("onboard"); p.add_argument("slug"); p.add_argument("--no-bios", action="store_true"); p.set_defaults(fn=cmd_onboard)
    p = sub.add_parser("refresh"); p.add_argument("--only"); p.add_argument("--slug"); p.add_argument("--no-bios", action="store_true"); p.set_defaults(fn=cmd_refresh)
    p = sub.add_parser("sweep"); p.add_argument("source", nargs="?", default="all", choices=["tds", "soccerwire", "all"]); p.add_argument("--years"); p.set_defaults(fn=cmd_sweep)
    p = sub.add_parser("rpi"); p.add_argument("what", nargs="?", default="all", choices=["history", "current", "all"]); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_rpi)
    p = sub.add_parser("build"); p.set_defaults(fn=cmd_build)
    p = sub.add_parser("validate"); p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=8000); p.set_defaults(fn=cmd_serve)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
