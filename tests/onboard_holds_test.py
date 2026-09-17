"""`onboard` never collects an entry under a collectionHold (issue #216).

    python tests/onboard_holds_test.py            # every case
    python tests/onboard_holds_test.py --verbose  # print every check, not only the failures

#215 (issue #199) marks the ten D2 entries a person decided not to collect with a `collectionHold` block:
the six merged PSAC campuses and four programs with no usable athletics source. They stay in `programs`
with `onboarded: false`, which is exactly what `onboard` selects, so before this fix
`onboard --all --conference "Pennsylvania State Athletic Conference"` would have collected the six PSAC
campuses the owner held out.

Nothing here touches the network, the registry file, refresh-state or the cache: `run_onboard()` runs
`collegedash.main(["onboard", ...])` in process against a registry built in memory, with the collectors,
collect_plan, rpi and the build replaced by stand-ins that only record that they were called, and with
`socket.socket.connect` replaced by one that counts and fails.

ONBOARD_HOLDS_COLLEGEDASH (optional) points at another copy of collegedash.py, so the code from before
the fix can be shown failing through these same checks.

Cases:
  all-skips-held         --all, --all --conference and --all --limit collect only the entries without a
                         hold, in registry order, and name each held entry they left out with its reason;
                         --limit counts only programs it can take
  all-only-held          a --conference whose every uncollected entry is held collects nothing, asks rpi
                         for nothing, exits 0, and names each one
  list-skips-held        a typed slug list, and a --slugs-file, collect the others as a batch and name each
                         held slug with its reason; a list of only held slugs is refused, exit 2
  single-held-refused    one held slug, typed or as the only line of a --slugs-file, is refused, exit 2,
                         naming the hold's reason and evidence, before rpi or any request
  guards-kept            the #142/#172 guards still hold with holds present: a staged division is still
                         refused without --collect-staged-divisions (for --all, a list and a single slug),
                         and the MAX_BATCH limit still refuses a batch over 25 programs it can take - while
                         held entries no longer count towards it
  shipped-registry       against public/data/registry.json as it is: --all --conference for the PSAC names
                         its held campuses and collects none of them
"""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
import socket
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collect import common  # noqa: E402

_ALT = os.environ.get("ONBOARD_HOLDS_COLLEGEDASH")
if _ALT:
    _spec = importlib.util.spec_from_file_location("collegedash", _ALT)
    collegedash = importlib.util.module_from_spec(_spec)
    sys.modules["collegedash"] = collegedash
    _spec.loader.exec_module(collegedash)
else:
    import collegedash  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False
PSAC = "Pennsylvania State Athletic Conference"


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


def hold(reason: str = "merged-scorecard-row", evidence: str = "Owner decision on #94: a test hold.") -> dict:
    return {"reason": reason, "evidence": evidence, "since": "2026-09-16"}


def program(slug: str, division: str = "D2", conference: str = PSAC, onboarded: bool = False, held: dict | None = None) -> dict:
    p = {"slug": slug, "division": division, "conference": conference, "onboarded": onboarded,
         "name": slug.replace("-", " ").title(), "ids": {"ncaaName": slug}}
    if held:
        p["collectionHold"] = held
    return p


def registry(programs: list[dict], onboarded_divisions=("D1", "D2")) -> dict:
    return {"updated": "2026-09-16", "season": 2026, "onboardedDivisions": list(onboarded_divisions), "programs": programs}


def mixed() -> dict:
    """D1 done; in the PSAC three collectable D2 programs around two held campuses; one held elsewhere."""
    return registry([
        program("d1-done", "D1", "ACC", onboarded=True),
        program("psac-a"),
        program("psac-held-1", held=hold()),
        program("psac-b"),
        program("psac-held-2", held=hold()),
        program("psac-c"),
        program("gulf-held", conference="Gulf South Conference", held=hold("no-athletics-source")),
        program("gulf-a", conference="Gulf South Conference"),
    ])


class Run:
    def __init__(self):
        self.code = None
        self.out = ""
        self.collected: list[str] = []
        self.rpi: list[str] = []
        self.builds = 0
        self.connects = 0
        self.reg: dict = {}

    @property
    def slugs(self) -> list[str]:
        seen = []
        for s in self.collected:
            if s not in seen:
                seen.append(s)
        return seen

    def skip_line(self, slug: str) -> str:
        return next((l for l in self.out.splitlines() if slug in l and "skips" in l), "")


def run_onboard(reg: dict, argv: list[str]) -> Run:
    """`python collegedash.py onboard <argv>` in process, against a copy of `reg`."""
    r = Run()
    r.reg = copy.deepcopy(reg)

    def run_collector(name, prog, registry_, **kw):
        r.collected.append(prog["slug"])
        return True

    def fake_collect_plan(plan, registry_, *, bios, workers, **kw):
        r.collected += [p["slug"] for p, _ in plan]
        return [{"program": p["slug"], "collector": c, "outcome": "ok", "error": ""} for p, cs in plan for c in cs]

    def mark_onboarded(slug):
        for p in r.reg["programs"]:
            if p["slug"] == slug:
                p["onboarded"] = True
        return r.reg

    def build_build(registry_):
        r.builds += 1

    def no_connect(self, *a, **kw):
        r.connects += 1
        raise AssertionError("the command opened a socket")

    fake_rpi = types.ModuleType("collect.rpi")
    fake_rpi.history = lambda registry_: r.rpi.append("history")
    fake_rpi.current = lambda registry_: r.rpi.append("current")
    fake_build = types.ModuleType("build")
    fake_build.build = build_build

    import collect
    saved = {"load_registry": common.load_registry, "update_refresh_state": common.update_refresh_state,
             "run_collector": collegedash.run_collector, "collect_plan": collegedash.collect_plan,
             "_mark_onboarded": collegedash._mark_onboarded,
             "connect": socket.socket.connect, "connect_ex": socket.socket.connect_ex}
    saved_modules = {k: sys.modules.get(k) for k in ("collect.rpi", "build")}
    saved_rpi_attr = getattr(collect, "rpi", None)
    try:
        common.load_registry = lambda: r.reg
        common.update_refresh_state = lambda key, info: None
        collegedash.run_collector = run_collector
        collegedash.collect_plan = fake_collect_plan
        collegedash._mark_onboarded = mark_onboarded
        socket.socket.connect = no_connect
        socket.socket.connect_ex = no_connect
        sys.modules["collect.rpi"] = fake_rpi
        sys.modules["build"] = fake_build
        collect.rpi = fake_rpi
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r.code = collegedash.main(["onboard"] + argv)
        r.out = buf.getvalue()
    finally:
        common.load_registry = saved["load_registry"]
        common.update_refresh_state = saved["update_refresh_state"]
        collegedash.run_collector = saved["run_collector"]
        collegedash.collect_plan = saved["collect_plan"]
        collegedash._mark_onboarded = saved["_mark_onboarded"]
        socket.socket.connect = saved["connect"]
        socket.socket.connect_ex = saved["connect_ex"]
        for k, m in saved_modules.items():
            if m is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = m
        if saved_rpi_attr is None:
            if hasattr(collect, "rpi"):
                delattr(collect, "rpi")
        else:
            collect.rpi = saved_rpi_attr
    return r


def held_untouched(r: Run, reg: dict) -> bool:
    return all(not p["onboarded"] for p in r.reg["programs"] if p.get("collectionHold"))


def slugs_file(lines: list[str]) -> str:
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    f.write("\n".join(lines) + "\n")
    f.close()
    return f.name


# ---------- cases ----------

def test_all_skips_held():
    print("all-skips-held: --all, --conference and --limit leave held entries out and name them")
    reg = mixed()
    r = run_onboard(reg, ["--all"])
    ok("--all: exit 0", r.code == 0, r.out[-400:])
    ok("--all: collects exactly the entries without a hold, in registry order",
       r.slugs == ["psac-a", "psac-b", "psac-c", "gulf-a"], r.slugs)
    ok("--all: no held entry is marked onboarded", held_untouched(r, reg))
    for slug, reason in (("psac-held-1", "merged-scorecard-row"), ("psac-held-2", "merged-scorecard-row"),
                         ("gulf-held", "no-athletics-source")):
        line = r.skip_line(slug)
        ok(f"--all: names {slug} as skipped, with its reason", bool(line) and reason in line, r.out[:600])

    r = run_onboard(reg, ["--all", "--conference", PSAC])
    ok("--all --conference: collects the conference's entries without a hold", r.slugs == ["psac-a", "psac-b", "psac-c"], r.slugs)
    ok("--all --conference: names both held PSAC campuses", bool(r.skip_line("psac-held-1")) and bool(r.skip_line("psac-held-2")), r.out[:600])
    ok("--all --conference: does not name a held entry from another conference", not r.skip_line("gulf-held"), r.out[:600])
    ok("--all --conference: no held entry is marked onboarded", held_untouched(r, reg))

    r = run_onboard(reg, ["--all", "--conference", PSAC, "--limit", "2"])
    ok("--all --limit 2: takes the first two programs it can collect, not a held one", r.slugs == ["psac-a", "psac-b"], r.slugs)


def test_all_only_held():
    print("all-only-held: a conference whose every uncollected entry is held collects nothing")
    reg = registry([program("d1-done", "D1", "ACC", onboarded=True), program("psac-done", onboarded=True),
                    program("psac-held-1", held=hold()), program("psac-held-2", held=hold())])
    r = run_onboard(reg, ["--all", "--conference", PSAC])
    ok("exit 0", r.code == 0, r.out[-400:])
    ok("nothing was collected", r.slugs == [], r.slugs)
    ok("rpi was not asked", r.rpi == [], r.rpi)
    ok("nothing was rebuilt", r.builds == 0, r.builds)
    ok("no socket was opened", r.connects == 0)
    ok("no held entry is marked onboarded", held_untouched(r, reg))
    ok("both held campuses are named", bool(r.skip_line("psac-held-1")) and bool(r.skip_line("psac-held-2")), r.out)


def test_list_skips_held():
    print("list-skips-held: a slug list or --slugs-file collects the rest and names each held slug")
    reg = mixed()
    r = run_onboard(reg, ["psac-a", "psac-held-1", "gulf-a"])
    ok("typed list: exit 0", r.code == 0, r.out[-400:])
    ok("typed list: collects the others, in the order given", r.slugs == ["psac-a", "gulf-a"], r.slugs)
    ok("typed list: names psac-held-1 with its reason", "merged-scorecard-row" in r.skip_line("psac-held-1"), r.out[:600])
    ok("typed list: the held slug is not marked onboarded", held_untouched(r, reg))

    path = slugs_file(["psac-b", "gulf-held", "psac-c"])
    try:
        r = run_onboard(reg, ["--slugs-file", path])
    finally:
        os.unlink(path)
    ok("--slugs-file: collects the others", r.slugs == ["psac-b", "psac-c"], r.slugs)
    ok("--slugs-file: names gulf-held with its reason", "no-athletics-source" in r.skip_line("gulf-held"), r.out[:600])

    r = run_onboard(reg, ["psac-a", "psac-held-2"])
    ok("a list left with one program after skipping still collects it", r.slugs == ["psac-a"], r.slugs)
    ok("and still names the held one", bool(r.skip_line("psac-held-2")), r.out[:600])

    r = run_onboard(reg, ["psac-held-1", "psac-held-2"])
    ok("a list of only held slugs: exit 2", r.code == 2, r.out[-400:])
    ok("a list of only held slugs: nothing collected, no rpi", r.slugs == [] and r.rpi == [], (r.slugs, r.rpi))
    ok("a list of only held slugs: no held entry marked onboarded", held_untouched(r, reg))


def test_single_held_refused():
    print("single-held-refused: one held slug is refused, naming the hold")
    reg = mixed()
    r = run_onboard(reg, ["psac-held-1"])
    ok("exit 2", r.code == 2, r.out[-400:])
    ok("nothing collected", r.slugs == [], r.slugs)
    ok("rpi was not asked", r.rpi == [], r.rpi)
    ok("no socket was opened", r.connects == 0)
    ok("not marked onboarded", held_untouched(r, reg))
    ok("the refusal names the slug and the hold's reason",
       "refuses psac-held-1" in r.out and "merged-scorecard-row" in r.out, r.out)
    ok("the refusal quotes the hold's evidence", "Owner decision on #94: a test hold." in r.out, r.out)

    path = slugs_file(["gulf-held"])
    try:
        r = run_onboard(reg, ["--slugs-file", path])
    finally:
        os.unlink(path)
    ok("the only line of a --slugs-file is refused the same way",
       r.code == 2 and r.slugs == [] and "refuses gulf-held" in r.out and "no-athletics-source" in r.out, r.out)


def test_guards_kept():
    print("guards-kept: the staged-division flag, the batch limit and the single-slug rule still hold")
    staged = registry([program("d1-done", "D1", "ACC", onboarded=True), program("psac-a"), program("psac-held-1", held=hold()),
                       program("psac-b")], onboarded_divisions=("D1",))
    r = run_onboard(staged, ["--all", "--conference", PSAC])
    ok("--all over a staged division is still refused without the flag", r.code == 2 and r.slugs == [] and r.rpi == [], r.out[-400:])
    ok("the refusal counts only the programs it could take (2)", "would have been 2 programs" in r.out, r.out)
    r = run_onboard(staged, ["--all", "--conference", PSAC, "--collect-staged-divisions", "D2"])
    ok("with --collect-staged-divisions D2 it collects the two without a hold", r.code == 0 and r.slugs == ["psac-a", "psac-b"], (r.code, r.slugs))
    r = run_onboard(staged, ["psac-a", "psac-held-1", "psac-b"])
    ok("a staged list is still refused without the flag", r.code == 2 and r.slugs == [], r.out[-400:])
    r = run_onboard(staged, ["psac-a"])
    ok("a single staged slug is still refused without the flag (#172)", r.code == 2 and r.slugs == [], r.out[-400:])
    r = run_onboard(staged, ["psac-a", "--collect-staged-divisions", "D2"])
    ok("and collected with it, on the single-program path", r.code == 0 and r.slugs == ["psac-a"], (r.code, r.slugs))

    over = registry([program(f"psac-{i}") for i in range(26)] + [program(f"psac-held-{i}", held=hold()) for i in range(5)])
    r = run_onboard(over, ["--all"])
    ok("26 programs it can take are still refused on size", r.code == 2 and "over the 25" in r.out and r.slugs == [], r.out[-400:])
    within = registry([program(f"psac-{i}") for i in range(25)] + [program(f"psac-held-{i}", held=hold()) for i in range(5)])
    r = run_onboard(within, ["--all"])
    ok("25 it can take plus 5 held is not refused: held entries do not count towards the limit",
       r.code == 0 and len(r.slugs) == 25 and not any("held" in s for s in r.slugs), (r.code, len(r.slugs), r.out[-300:]))


def test_shipped_registry():
    live = json.load(open(os.path.join(ROOT, "public", "data", "registry.json"), encoding="utf-8"))
    held = [p for p in live["programs"] if not p.get("onboarded") and p.get("collectionHold") and p.get("conference") == PSAC]
    print(f"shipped-registry: {len(held)} held PSAC entries in public/data/registry.json")
    if not held:
        ok("the shipped registry has no held PSAC entry, so there is nothing to check here", True)
        return
    r = run_onboard(live, ["--all", "--conference", PSAC])
    ok("no held PSAC campus is collected", not any(p["slug"] in r.slugs for p in held), r.slugs)
    ok("each held PSAC campus is named with its reason",
       all(p["collectionHold"]["reason"] in r.skip_line(p["slug"]) for p in held), r.out[:800])
    ok("no socket was opened", r.connects == 0)


def main(argv=None) -> int:
    global VERBOSE
    VERBOSE = "--verbose" in (argv if argv is not None else sys.argv[1:])
    for case in (test_all_skips_held, test_all_only_held, test_list_skips_held, test_single_held_refused,
                 test_guards_kept, test_shipped_registry):
        try:
            case()
        except Exception as e:  # a crash is a failure of that case, not the end of the suite
            ok(f"{case.__name__} ran without raising", False, repr(e))
    print()
    if FAILS:
        print(f"{len(FAILS)} of {TOTAL} checks failed")
        return 1
    print(f"{TOTAL} of {TOTAL} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
