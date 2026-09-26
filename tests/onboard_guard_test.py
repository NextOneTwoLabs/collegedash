"""The guard on `onboard --all` (issue #138).

    python tests/onboard_guard_test.py            # every case
    python tests/onboard_guard_test.py --verbose  # print every check, not only the failures

`onboard --all` collects every collector for every program the registry does not mark onboarded.
That was one batch of a few programs while the registry held D1 only and D1 was finished. PR #137
stages 261 Division II programs with `onboarded: false` and leaves `onboardedDivisions` at ["D1"],
so the same command would have walked 261 athletics sites in one pass, for a division the site does
not publish yet. The guard refuses that batch, says what to run instead, and can be overridden on
the one command that means to.

Nothing here touches the network, the registry file, refresh-state or the cache: `run_onboard()`
runs `collegedash.main(["onboard", ...])` in process against a registry built in memory, with the
collectors, rpi and the build replaced by stand-ins that only record that they were called, and
with `socket.socket.connect` replaced by one that fails the check it is called from. "No request
was made" is therefore an assertion, not an assumption.

Cases, and the mutation each is here to catch (tests/../scratch mutate138.py applies them):
  the-shipped-registry   `onboard --all` against public/data/registry.json as it currently is,
                         with the expectation derived from that file rather than assumed: refused,
                         naming the divisions it stages and the size of the batch, or collected in
                         the pre-guard order when it stages nothing. Fails when batch_todo() stops
                         filtering on `onboarded`, when a rule stops refusing, or when the refusal
                         names the wrong division or count (issue #146).
  unchanged-d1-batch     a handful of unonboarded D1 programs: collected, in the same order and
                         with the same --limit behaviour as the code before the guard.
                         Fails when the guard refuses a batch it has no reason to refuse.
  staged-division        the #137 shape, 261 staged D2 programs: refused, exit 2, nothing
                         collected, no rpi call, no socket opened, registry untouched.
                         Fails when the division rule goes, or when the check moves after rpi.
  refusal-says-what-next the refusal names the division, the count, the conferences, and the two
                         commands to run instead. Fails when the advice block goes.
  conference-batch       --conference is the batch shape the refusal recommends: it narrows the
                         batch, matches a conference exactly, and is still refused while the
                         division is staged. Fails when the conference filter over-matches.
  overrides              the two overrides are independent, and each lifts only its own rule;
                         --collect-staged-divisions has to name the division it is allowing, and
                         naming one this batch would not collect is a refusal of its own.
                         Fails when either is ignored, or when one lifts both.
  one-shot               the overrides are arguments, they default off, they are not read from the
                         environment, and nothing about them survives the command.
                         Fails when a rule can be lifted by an environment variable.
  odd-registries         a program with no division or conference, and a registry with no
                         onboardedDivisions, are described rather than crashed on.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import os
import socket
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collect import common  # noqa: E402
import collegedash  # noqa: E402

FAILS: list[str] = []
TOTAL = 0
VERBOSE = False


def ok(name: str, cond: bool, detail: str = "") -> bool:
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f" - {str(detail)[:500]}" if detail else ""))
    elif VERBOSE:
        print(f"  ok   {name}")
    return bool(cond)


# ---------- registries ----------

def program(slug: str, division: str, conference: str, onboarded: bool = False) -> dict:
    return {"slug": slug, "division": division, "conference": conference, "onboarded": onboarded,
            "name": slug.replace("-", " ").title(), "ids": {"ncaaName": slug}}


def registry(programs: list[dict], onboarded_divisions=("D1",)) -> dict:
    reg = {"updated": "2026-09-15", "season": 2026, "programs": programs}
    if onboarded_divisions is not None:
        reg["onboardedDivisions"] = list(onboarded_divisions)
    return reg


def staged_d2(n_gulf_south: int = 16, n_peach_belt: int = 245) -> dict:
    """The shape PR #137 stages: D1 finished and published, a whole D2 division sitting unonboarded."""
    programs = [program(f"d1-{i}", "D1", "ACC", onboarded=True) for i in range(349)]
    programs += [program(f"gs-{i}", "D2", "Gulf South") for i in range(n_gulf_south)]
    programs += [program(f"pb-{i}", "D2", "Peach Belt") for i in range(n_peach_belt)]
    return registry(programs)


def live_registry() -> dict:
    """The registry this repository actually ships, read once and never written."""
    return json.load(open(os.path.join(ROOT, "public", "data", "registry.json"), encoding="utf-8"))


# ---------- the command, with stand-ins for everything that leaves the process ----------

class Run:
    def __init__(self):
        self.code = None
        self.out = ""
        self.collectors: list[tuple[str, str]] = []
        self.rpi: list[str] = []
        self.builds = 0
        self.state: list[str] = []
        self.connects = 0
        self.reg: dict = {}

    @property
    def slugs(self) -> list[str]:
        """Programs a collector was run for, in the order they were collected."""
        seen = []
        for slug, _ in self.collectors:
            if slug not in seen:
                seen.append(slug)
        return seen

    @property
    def refusal(self) -> str:
        return "\n".join(l for l in self.out.splitlines() if "refuses this batch" in l or l.startswith("   "))


def run_onboard(reg: dict, argv: list[str], env: dict | None = None) -> Run:
    """`python collegedash.py onboard <argv>` in process, against a copy of `reg`."""
    r = Run()
    r.reg = copy.deepcopy(reg)

    def run_collector(name, prog, registry_, **kw):
        r.collectors.append((prog["slug"], name))
        return True

    def mark_onboarded(slug):
        for p in r.reg["programs"]:
            if p["slug"] == slug:
                p["onboarded"] = True
        return r.reg

    def build_build(registry_):
        r.builds += 1

    fake_rpi = types.ModuleType("collect.rpi")
    fake_rpi.history = lambda registry_: r.rpi.append("history")
    fake_rpi.current = lambda registry_: r.rpi.append("current")
    fake_build = types.ModuleType("build")
    fake_build.build = build_build

    def no_connect(self, *a, **kw):
        r.connects += 1
        raise AssertionError("the command opened a socket")

    import collect
    saved = {"load_registry": common.load_registry, "update_refresh_state": common.update_refresh_state,
             "run_collector": collegedash.run_collector, "_mark_onboarded": collegedash._mark_onboarded,
             "connect": socket.socket.connect, "connect_ex": socket.socket.connect_ex}
    saved_modules = {k: sys.modules.get(k) for k in ("collect.rpi", "build")}
    saved_rpi_attr = getattr(collect, "rpi", None)
    saved_env = {k: os.environ.get(k) for k in (env or {})}
    try:
        common.load_registry = lambda: r.reg
        common.update_refresh_state = lambda key, info: r.state.append(key)
        collegedash.run_collector = run_collector
        collegedash._mark_onboarded = mark_onboarded
        socket.socket.connect = no_connect
        socket.socket.connect_ex = no_connect
        sys.modules["collect.rpi"] = fake_rpi
        sys.modules["build"] = fake_build
        collect.rpi = fake_rpi
        os.environ.update(env or {})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r.code = collegedash.main(["onboard"] + argv)
        r.out = buf.getvalue()
    finally:
        common.load_registry = saved["load_registry"]
        common.update_refresh_state = saved["update_refresh_state"]
        collegedash.run_collector = saved["run_collector"]
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
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return r


def todo_before_the_guard(reg: dict, limit: int | None = None) -> list[str]:
    """What `onboard_all` selected on origin/main, written out here so the guard's selection can be
    compared with it rather than with itself."""
    todo = [p for p in reg["programs"] if not p.get("onboarded")]
    if limit:
        todo = todo[:limit]
    return [p["slug"] for p in todo]


# ---------- cases ----------

def test_the_shipped_registry():
    """`onboard --all` against public/data/registry.json, whatever that file currently holds.

    This case used to assert the shape of the registry - D1 published, nothing unonboarded - and
    then that the command collected nothing and exited 0. That was true when it was written and
    false 20 seconds later: #137 staged 261 Division II programs and #142 merged just after it, so
    the suite asserted a registry that no longer exists and `main` went red (issue #146).

    So the expectation is derived from the file instead. It is derived *here*, with this case's own
    arithmetic over `programs` and `onboardedDivisions`, and then checked against what the command
    actually does and says - never by asking batch_refusal() what it thinks and agreeing. A rule
    that stopped refusing, a selection that stopped filtering on `onboarded`, a refusal that named
    the wrong division or the wrong count, or a check that moved after rpi is asked for the table,
    all still fail here; a registry that stages or finishes a division does not.
    """
    live = live_registry()
    published = live.get("onboardedDivisions") or []
    # what onboard_all selected before the guard, less entries under a collectionHold, which onboard
    # never collects (issue #216; tests/onboard_holds_test.py)
    todo = [p for p in live["programs"] if not p.get("onboarded") and not p.get("collectionHold")]
    held = [p for p in live["programs"] if not p.get("onboarded") and p.get("collectionHold")]
    staged = sorted({(p.get("division") or "?") for p in todo} - set(published))
    too_many = len(todo) > collegedash.MAX_BATCH
    print(f"the-shipped-registry: {len(live['programs'])} programs, {len(todo)} unonboarded and collectable "
          f"({len(held)} more under a collectionHold), publishes {published}, "
          f"staged {', '.join(staged) if staged else 'nothing'}")
    ok("the registry says which divisions it publishes", bool(published), str(live.get("onboardedDivisions")))
    refusal = collegedash.batch_refusal(live)
    ok("refused exactly when this registry gives a reason to refuse",
       bool(refusal) == (bool(staged) or too_many),
       f"staged={staged} todo={len(todo)} max={collegedash.MAX_BATCH} refusal={refusal[:1]}")
    r = run_onboard(live, ["--all"])
    ok("no socket was opened", r.connects == 0)
    if not too_many:
        # issue #210: the over-limit check below only runs while the LIVE registry has more than
        # MAX_BATCH collectable programs, which stops being true as divisions are collected. Say so,
        # so a check that stops running is visible in the log; test_over_limit_batch runs the same
        # checks on a synthetic registry every time, whatever the live one holds.
        print(f"  skipped: only {len(todo)} collectable uncollected, not over MAX_BATCH "
              f"({collegedash.MAX_BATCH}); the over-limit refusal is checked by test_over_limit_batch")
    if staged or too_many:
        assert_refused(r, refusal, todo, staged, too_many)
    elif held and not todo:
        # every uncollected entry is under a collectionHold (issue #216): nothing to collect, so no
        # request at all - not even rpi's - and each held entry is named
        ok("onboard --all exits 0", r.code == 0, r.out[-400:])
        ok("nothing was collected", r.collectors == [], r.collectors[:3])
        ok("rpi was not asked, since there is nothing to collect", r.rpi == [], r.rpi)
        ok("nothing was recorded in refresh-state", r.state == [], r.state)
        ok("every held entry is named as skipped",
           all(f"onboard skips {p['slug']}" in r.out for p in held), r.out[:600])
    else:
        # nothing staged and a batch within the limit: exactly the behaviour before the guard
        ok("onboard --all still runs", r.code == 0, r.out[-400:])
        ok("it still asks rpi for the table first", r.rpi == ["history", "current"], r.rpi)
        ok("it collects the programs the code before the guard selected, in that order",
           r.slugs == [p["slug"] for p in todo], r.slugs[:5])
        ok("it still records the run in refresh-state", r.state == ["onboardAll"], r.state)


def assert_refused(r, refusal: list[str], todo: list, staged: list[str], too_many: bool) -> None:
    """The refusal path, shared by the live registry and test_over_limit_batch (issue #210): a division
    staged in the registry, or a batch past the limit, means the command refuses and collects nothing."""
    text = "\n".join(refusal)
    ok("exit 2", r.code == 2, r.out[-400:])
    ok("nothing was collected", r.collectors == [], r.collectors[:3])
    ok("rpi was not asked either", r.rpi == [], r.rpi)
    ok("nothing was recorded in refresh-state", r.state == [], r.state)
    for division in staged or ["(none)"]:
        ok(f"the refusal names {division}, which this registry stages",
           division in refusal[0] if staged else True, refusal[:1])
    ok(f"the refusal counts the batch this registry would have collected ({len(todo)})",
       f"{len(todo)} programs" in text, text.splitlines()[:2])
    if too_many:
        ok(f"and says it is over the {collegedash.MAX_BATCH}-program limit, because it is",
           f"over the {collegedash.MAX_BATCH}" in text, refusal[:1])
    ok("and it says what to run instead",
       "--conference" in text and "onboard <slug>" in text, text)


def test_over_limit_batch():
    """Issue #210: `onboard --all` over a batch past MAX_BATCH in a PUBLISHED division (nothing staged),
    through the command, on a synthetic registry - so the over-limit refusal is exercised on every run
    rather than only while the live registry happens to hold more than MAX_BATCH uncollected programs."""
    n = collegedash.MAX_BATCH + 5
    print(f"over-limit-batch: {n} unonboarded programs in a published division are refused on size alone")
    reg = registry([program(f"d1-{i}", "D1", "ACC", onboarded=i >= n) for i in range(n + 10)])
    todo = todo_before_the_guard(reg)
    ok(f"the synthetic registry really is over the limit ({len(todo)} > {collegedash.MAX_BATCH})",
       len(todo) > collegedash.MAX_BATCH, len(todo))
    refusal = collegedash.batch_refusal(reg)
    ok("it is refused, and on size alone", bool(refusal) and "does not publish yet" not in refusal[0], refusal[:1])
    r = run_onboard(reg, ["--all"])
    ok("no socket was opened", r.connects == 0)
    assert_refused(r, refusal, todo, [], True)


def test_unchanged_d1_batch():
    print("unchanged-d1-batch: a few unonboarded D1 programs are collected exactly as before")
    reg = registry([program(f"d1-{i}", "D1", "ACC", onboarded=i >= 5) for i in range(20)])
    ok("nothing is refused", collegedash.batch_refusal(reg) == [], collegedash.batch_refusal(reg)[:2])
    r = run_onboard(reg, ["--all"])
    ok("exit 0", r.code == 0, r.out[-400:])
    ok("the same programs the code before the guard selected, in the same order",
       r.slugs == todo_before_the_guard(reg), r.slugs)
    ok("every collector ran for each of them",
       sorted({c for _, c in r.collectors}) == sorted(collegedash.COLLECTORS),
       sorted({c for _, c in r.collectors}))
    ok("each one was marked onboarded", all(p.get("onboarded") for p in r.reg["programs"]))
    ok("the site was rebuilt", r.builds >= 1, r.builds)

    r = run_onboard(reg, ["--all", "--limit", "3"])
    ok("--limit still takes the first N of that same list", r.slugs == todo_before_the_guard(reg, 3), r.slugs)

    ok("one program by slug is untouched by the guard",
       run_onboard(reg, ["d1-7"]).slugs == ["d1-7"])

    big = registry([program(f"d1-{i}", "D1", "ACC", onboarded=i >= 30) for i in range(60)])
    lines = collegedash.batch_refusal(big)
    ok("30 unonboarded D1 programs are refused on size alone - the count rule is not about D2",
       len(lines) > 1 and "does not publish yet" not in lines[0] and "over the 25" in lines[0], lines[:1])


def test_staged_division():
    print("staged-division: the #137 shape, 261 staged D2 programs behind an onboardedDivisions of ['D1']")
    reg = staged_d2()
    r = run_onboard(reg, ["--all"])
    ok("exit 2", r.code == 2, r.code)
    ok("no collector ran", r.collectors == [], r.collectors[:3])
    ok("rpi was not asked either - a refused command makes no request at all", r.rpi == [], r.rpi)
    ok("no socket was opened", r.connects == 0)
    ok("nothing was rebuilt", r.builds == 0, r.builds)
    ok("nothing was recorded in refresh-state", r.state == [], r.state)
    ok("no program was marked onboarded",
       [p["slug"] for p in r.reg["programs"] if p["onboarded"]] == [p["slug"] for p in reg["programs"] if p["onboarded"]])
    ok("the refusal is the only thing printed about the batch", "refuses this batch" in r.out, r.out[:200])


def recommended_command(lines: list[str]) -> dict:
    """The `onboard --all` command a refusal recommends, parsed back into batch_refusal()'s keywords,
    so the advice can be run rather than only read."""
    import shlex
    line = next((l for l in lines if "onboard --all --conference" in l), None)
    if line is None:
        return None
    parts = shlex.split(line)
    kw: dict = {"conference": parts[parts.index("--conference") + 1]}
    if "--limit" in parts:
        kw["limit"] = int(parts[parts.index("--limit") + 1])
    if "--collect-staged-divisions" in parts:
        after = parts[parts.index("--collect-staged-divisions") + 1:]
        # a flag with nothing after it names no division, which is what the guard will see too
        kw["allow_divisions"] = after[0].split(",") if after and not after[0].startswith("--") else []
    return kw


def test_refusal_says_what_next():
    print("refusal-says-what-next: the refusal names the reason, the size, and the commands to run instead")
    reg = staged_d2()
    text = "\n".join(collegedash.batch_refusal(reg))
    ok("it names the staged division", "D2" in text.split("\n")[0], text.split("\n")[0])
    ok("it quotes onboardedDivisions, so the reader can see what the registry says",
       "onboardedDivisions is ['D1']" in text, text.split("\n")[0])
    ok("it gives the second reason too - 261 programs is over the limit",
       "261 programs" in text and "over the 25" in text, text.split("\n")[0])
    ok("it says nothing was collected", "Nothing was collected" in text)
    ok("it breaks the batch down by conference", "D2 Peach Belt: 245" in text and "D2 Gulf South: 16" in text, text)
    ok("it names a conference batch to run instead", "--conference" in text, text)
    ok("it names the one-program batch too", "onboard <slug>" in text, text)
    for label, args, r in [("the #137 sweep", {}, staged_d2()),
                           ("a division of one huge conference", {}, registry([program(f"p{i}", "D2", "Peach Belt")
                                                                               for i in range(245)])),
                           ("30 unonboarded programs in a published division", {},
                            registry([program(f"d1-{i}", "D1", "Big Ten") for i in range(30)]))]:
        cmd = recommended_command(collegedash.batch_refusal(r, **args))
        ok(f"the command it recommends for {label} is one the guard accepts",
           cmd is not None and collegedash.batch_refusal(r, **cmd) == [],
           (cmd, collegedash.batch_refusal(r, **cmd)[:1] if cmd else "no command was recommended"))
    ok("it names both overrides", "--max-batch" in text and "--collect-staged-divisions" in text, text)
    many = registry([program(f"p{i}", "D2", f"Conf {i % 12}") for i in range(120)])
    listed = [l for l in collegedash.batch_refusal(many) if l.startswith("     D2 Conf")]
    ok("a batch spanning many conferences lists a few and counts the rest",
       len(listed) == 8 and "and 4 more conference(s)" in "\n".join(collegedash.batch_refusal(many)),
       "\n".join(collegedash.batch_refusal(many)))


def test_conference_batch():
    print("conference-batch: --conference is the shape the refusal recommends")
    reg = staged_d2()
    ok("it narrows the batch to that conference",
       [p["slug"] for p in collegedash.batch_todo(reg, conference="Gulf South")] == [f"gs-{i}" for i in range(16)])
    ok("it matches the name however it is cased",
       len(collegedash.batch_todo(reg, conference="gulf south")) == 16)
    ok("it matches a conference name exactly, not by prefix",
       collegedash.batch_todo(reg, conference="Gulf") == [], len(collegedash.batch_todo(reg, conference="Gulf")))
    lines = collegedash.batch_refusal(reg, conference="Gulf South")
    ok("16 programs is within the limit, so only the staged division is left as a reason",
       len(lines) > 1 and "over the" not in lines[0] and "does not publish yet" in lines[0], lines[:1])
    ok("and the advice is to confirm this batch, not to reshape it",
       "Re-run the same command with --collect-staged-divisions D2" in "\n".join(lines), "\n".join(lines))
    r = run_onboard(reg, ["--all", "--conference", "Gulf South"])
    ok("it is still refused while the division is staged", r.code == 2 and r.collectors == [], r.code)
    r = run_onboard(reg, ["--all", "--conference", "Gulf South", "--collect-staged-divisions", "D2"])
    ok("with the override it runs", r.code == 0, r.out[-400:])
    ok("and collects that conference and nothing else", r.slugs == [f"gs-{i}" for i in range(16)], r.slugs)
    r = run_onboard(reg, ["--all", "--conference", "Nowhere Conference"])
    ok("a conference with nobody unonboarded in it is not refused, it just collects nothing",
       r.code == 0 and r.collectors == [], (r.code, r.collectors[:2]))
    lines = collegedash.batch_refusal(reg, limit=10)
    ok("--limit is not an override: 10 staged D2 programs are still a staged division",
       len(lines) > 1 and "does not publish yet" in lines[0] and "10 programs" in "\n".join(lines), lines[:2])


def test_overrides():
    print("overrides: two rules, two switches, each lifting only its own")
    reg = staged_d2()
    only_count = collegedash.batch_refusal(reg, allow_divisions=["D2"])
    ok("--collect-staged-divisions D2 alone leaves the count rule standing",
       len(only_count) > 1 and "over the 25" in only_count[0] and "does not publish yet" not in only_count[0],
       only_count[:1])
    only_division = collegedash.batch_refusal(reg, max_batch=500)
    ok("--max-batch alone leaves the division rule standing",
       len(only_division) > 1 and "does not publish yet" in only_division[0] and "over the" not in only_division[0],
       only_division[:1])
    both = collegedash.batch_refusal(reg, max_batch=500, allow_divisions=["D2"])
    ok("both together allow the batch", both == [], both[:1])
    ok("the override has to name the division that is actually staged: D3 is a refusal, not a no-op",
       "--collect-staged-divisions names D3" in "\n".join(
           collegedash.batch_refusal(reg, max_batch=500, allow_divisions=["D3"])),
       collegedash.batch_refusal(reg, max_batch=500, allow_divisions=["D3"])[:1])
    ok("naming it in either case works",
       collegedash.batch_refusal(reg, max_batch=500, allow_divisions=["d2"]) == [])
    r = run_onboard(reg, ["--all", "--max-batch", "500", "--collect-staged-divisions", "D2"])
    ok("and the command then collects all 261", r.code == 0 and len(r.slugs) == 261, (r.code, len(r.slugs)))
    r = run_onboard(reg, ["--all", "--max-batch", "500"])
    ok("--max-batch on its own does not smuggle the division through", r.code == 2 and r.collectors == [], r.code)
    r = run_onboard(reg, ["--all", "--max-batch", "500", "--collect-staged-divisions", "D3"])
    ok("naming the wrong division does not smuggle it through either",
       r.code == 2 and r.collectors == [], r.code)
    r = run_onboard(reg, ["--all", "--collect-staged-divisions", "D2"])
    ok("--collect-staged-divisions on its own does not smuggle 261 programs through",
       r.code == 2 and r.collectors == [], r.code)
    d1 = registry([program(f"d1-{i}", "D1", "ACC") for i in range(40)])
    ok("--max-batch raises the limit for a division that is published too",
       collegedash.batch_refusal(d1, max_batch=40) == [] and collegedash.batch_refusal(d1) != [])


def test_one_shot():
    print("one-shot: the overrides are arguments on one command, not settings")
    parsed = _parse(["onboard", "--all"])  # the parser is built inside main(); parse through it
    ok("--max-batch defaults to MAX_BATCH", parsed.max_batch == collegedash.MAX_BATCH, parsed.max_batch)
    ok("--collect-staged-divisions defaults to naming nothing", parsed.collect_staged_divisions == "",
       parsed.collect_staged_divisions)
    ok("--conference defaults to nothing", parsed.conference is None)
    parsed = _parse(["onboard", "--all", "--conference", "Gulf South", "--max-batch", "40",
                     "--collect-staged-divisions", "D2,D3"])
    ok("all three arrive from the command line",
       (parsed.conference, parsed.max_batch, parsed.collect_staged_divisions) == ("Gulf South", 40, "D2,D3"),
       (parsed.conference, parsed.max_batch, parsed.collect_staged_divisions))
    src = open(os.path.join(ROOT, "collegedash.py"), encoding="utf-8").read()
    guard = src[src.index("def cmd_onboard"):src.index("def cmd_refresh")]
    ok("no environment variable is read anywhere in the guard or the command it guards",
       "os.environ" not in guard and "getenv(" not in guard,
       [l for l in guard.splitlines() if "os.environ" in l or "getenv(" in l])
    reg = staged_d2()
    env = {"COLLEGEDASH_COLLECT_STAGED_DIVISIONS": "D2", "COLLEGEDASH_MAX_BATCH": "1000",
           "COLLEGEDASH_ALLOW_STAGED": "D2"}
    r = run_onboard(reg, ["--all"], env=env)
    ok("setting the obvious environment variables does not lift either rule",
       r.code == 2 and r.collectors == [], (r.code, len(r.collectors)))
    r = run_onboard(reg, ["--all", "--conference", "Gulf South"], env=env)
    ok("nor the division rule on a batch the count rule would have let through",
       r.code == 2 and r.collectors == [], (r.code, len(r.collectors)))
    run_onboard(reg, ["--all", "--max-batch", "500", "--collect-staged-divisions", "D2"])
    ok("and an override does not survive the command it was given on",
       collegedash.batch_refusal(staged_d2()) != [] and collegedash.MAX_BATCH == 25, collegedash.MAX_BATCH)
    ok("no state file is written by a refused command", run_onboard(reg, ["--all"]).state == [])


def _parse(argv: list[str]) -> argparse.Namespace:
    """Parse argv with the real parser, without running the command."""
    holder = {}

    def capture(args):
        holder["args"] = args
        return 0

    saved = collegedash.cmd_onboard
    try:
        collegedash.cmd_onboard = capture
        collegedash.main(argv)
    finally:
        collegedash.cmd_onboard = saved
    return holder["args"]


def test_odd_registries():
    print("odd-registries: incomplete rows are described, not crashed on")
    reg = registry([{"slug": "mystery", "onboarded": False, "ids": {}}] +
                   [program(f"d2-{i}", "D2", "Peach Belt") for i in range(30)])
    lines = collegedash.batch_refusal(reg)
    ok("a program with no division counts as a division the site does not publish",
       "?" in lines[0] and "D2" in lines[0], lines[:1])
    ok("and a program with no conference is listed as unknown rather than dropped",
       "? ?: 1" in "\n".join(lines), "\n".join(lines))
    no_divs = registry([program(f"d2-{i}", "D2", "Peach Belt") for i in range(5)], onboarded_divisions=None)
    ok("a registry that does not say which divisions it publishes cannot trip the division rule",
       collegedash.batch_refusal(no_divs) == [], collegedash.batch_refusal(no_divs))
    ok("but the count rule still applies to it",
       len(collegedash.batch_refusal(registry([program(f"d2-{i}", "D2", "Peach Belt") for i in range(30)],
                                              onboarded_divisions=None))) > 1)
    empty = registry([])
    ok("an empty registry is not a refusal", collegedash.batch_refusal(empty) == [])


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--case", action="append", help="run only these cases (by function suffix)")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose
    cases = [test_the_shipped_registry, test_over_limit_batch, test_unchanged_d1_batch, test_staged_division, test_refusal_says_what_next,
             test_conference_batch, test_overrides, test_one_shot, test_odd_registries]
    for c in cases:
        if args.case and not any(c.__name__.endswith(x.replace("-", "_")) for x in args.case):
            continue
        try:
            c()
        except Exception as e:  # a case that raises is a failed case, not a lost run
            ok(f"{c.__name__} ran to the end", False, f"{type(e).__name__}: {e}")
    print(f"\n{TOTAL - len(FAILS)} of {TOTAL} checks passed")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
