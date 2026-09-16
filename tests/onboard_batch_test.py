"""The batch form of `onboard` (issue #143): an explicit slug list collects every program, then
builds and validates ONCE, rather than once per program, and does its collecting through refresh's
own concurrent path (issue #105) rather than a second one.

    python tests/onboard_batch_test.py            # every case
    python tests/onboard_batch_test.py --verbose  # print every check, not only the failures

Nothing here touches the network, the registry file, refresh-state, programs/*/sources or
public/data: every case builds a registry in memory, patches collect_plan/build or the collector
modules themselves with stand-ins, and points collect.common's cache and gate state at scratch
state for the duration of the case (see fresh_state()).

Covers, in order:
  explicit-slugs     one slug (typed directly, or the only line of a --slugs-file) is the existing
                      single-program form and is not batch mode; two or more, from either source
                      combined, is
  guard-reuse         onboard_batch_refusal() applies batch_refusal()'s division rule - not its
                      MAX_BATCH size cap, which an explicit list has no reason to need - to a named
                      list of slugs, with the same --collect-staged-divisions override; an unknown
                      slug is refused by name before anything else is checked
  guard-wiring        cmd_onboard checks the batch guard, in the same "before rpi, before any
                      request" position as --all's, and only when two or more slugs were named
  rebuild-once        onboard_batch collects every program through ONE collect_plan call and builds
                      ONCE at the end, against the same batch that onboard <slug> run once per
                      program (the pre-#143 shape) builds once per program for
  all-unaffected      onboard --all's own guard and behaviour are untouched by any of this (the full
                      suite is tests/onboard_guard_test.py, which this does not duplicate)
  per-host-politeness a real fetch, through collect.common.fetch and collegedash.collect_plan, from
                      several programs at once: no two requests to a host they share overlap, and
                      the gap between them holds - checked from the server's side, which cannot be
                      fooled - and a control shows the same checker catching a deliberately disabled
                      gate, so the check is one that can fail
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import http.server
import io
import os
import sys
import tempfile
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# Not COLLEGEDASH_OFFLINE=1: test_per_host_politeness fetches real HTTP, from stub servers on
# 127.0.0.1 - offline in the sense that matters (no real network, no real host), but not in the
# sense that flag means (refuse every request and serve only the cache).
for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(var, None)
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"

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

def program(slug: str, division: str = "D1", conference: str = "ACC", onboarded: bool = False) -> dict:
    return {"slug": slug, "division": division, "conference": conference, "onboarded": onboarded,
            "name": slug.replace("-", " ").title(), "ids": {"ncaaName": slug}}


def registry(programs: list[dict], onboarded_divisions=("D1",)) -> dict:
    reg = {"updated": "2026-09-16", "season": 2026, "programs": programs}
    if onboarded_divisions is not None:
        reg["onboardedDivisions"] = list(onboarded_divisions)
    return reg


def staged_d2(n: int = 8) -> dict:
    return registry([program(f"d2-{i}", "D2", "Peach Belt") for i in range(n)])


# ---------- argparse ----------

def parse(argv: list[str]) -> argparse.Namespace:
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


def test_explicit_slugs() -> None:
    print("explicit-slugs: one slug (however it arrives) is not batch mode; two or more is")
    ok("one slug, typed directly", collegedash.explicit_slugs(parse(["onboard", "d1-7"])) == ["d1-7"])
    ok("two slugs, typed directly, is a batch",
       collegedash.explicit_slugs(parse(["onboard", "d1-7", "d1-8"])) == ["d1-7", "d1-8"])
    ok("--all names no explicit slugs", collegedash.explicit_slugs(parse(["onboard", "--all"])) == [])
    ok("nothing named is empty, same as before", collegedash.explicit_slugs(parse(["onboard"])) == [])

    with tempfile.TemporaryDirectory() as tmp:
        one = os.path.join(tmp, "one.txt")
        with open(one, "w", encoding="utf-8") as f:
            f.write("solo-slug\n")
        ok("--slugs-file with one line is still one slug, not batch mode",
           collegedash.explicit_slugs(parse(["onboard", "--slugs-file", one])) == ["solo-slug"])

        many = os.path.join(tmp, "many.txt")
        with open(many, "w", encoding="utf-8") as f:
            f.write("# a comment\nfirst\n\nsecond\nfirst\n")
        ok("--slugs-file: comments and blank lines are ignored, and a repeat is not",
           collegedash.explicit_slugs(parse(["onboard", "--slugs-file", many])) == ["first", "second"])
        ok("a slug given directly plus --slugs-file combine, directly-named first, no duplicate",
           collegedash.explicit_slugs(parse(["onboard", "first", "--slugs-file", many])) == ["first", "second"])


# ---------- guard reuse ----------

def test_guard_reuse() -> None:
    print("guard-reuse: onboard_batch_refusal applies the division rule, not the size cap, to a named list")
    reg = staged_d2()
    ok("an unpublished division is refused, and says which",
       collegedash.onboard_batch_refusal(reg, ["d2-0", "d2-1"]) != []
       and "D2" in collegedash.onboard_batch_refusal(reg, ["d2-0", "d2-1"])[0])
    ok("the override lifts it", collegedash.onboard_batch_refusal(reg, ["d2-0", "d2-1"], allow_divisions=["D2"]) == [])
    ok("naming the wrong division does not smuggle it through",
       collegedash.onboard_batch_refusal(reg, ["d2-0"], allow_divisions=["D3"]) != [])
    ok("naming it in either case works",
       collegedash.onboard_batch_refusal(reg, ["d2-0"], allow_divisions=["d2"]) == [])

    d1 = registry([program(f"d1-{i}") for i in range(200)])
    long_list = [f"d1-{i}" for i in range(200)]
    ok("a long list of programs already in a published division is never refused for size - "
       "an explicit list has no MAX_BATCH, unlike --all",
       collegedash.onboard_batch_refusal(d1, long_list) == [])

    ok("an unknown slug is refused by name, before the division check runs",
       collegedash.onboard_batch_refusal(d1, ["d1-0", "nope"])
       == ["!! onboard refuses this batch: unknown slug(s) nope. Nothing was collected."])

    mixed = registry([program("d1-0"), program("d2-0", "D2", "Peach Belt")])
    lines = collegedash.onboard_batch_refusal(mixed, ["d1-0", "d2-0"])
    ok("a batch mixing a published and a staged program is refused for the staged one",
       lines != [] and "D2" in lines[0], lines[:1])

    ok("--collect-staged-divisions naming a division this batch would not collect is a refusal too",
       collegedash.onboard_batch_refusal(reg, ["d2-0"], allow_divisions=["D3"])
       != collegedash.onboard_batch_refusal(reg, ["d2-0"]))


# ---------- guard wiring: cmd_onboard checks it, in the right position, only for 2+ ----------

class Run:
    def __init__(self):
        self.code = None
        self.out = ""
        self.plans: list[list[str]] = []   # slugs passed to collect_plan, per call
        self.builds = 0
        self.rpi: list[str] = []
        self.reg: dict = {}


def run_onboard(reg: dict, argv: list[str]) -> Run:
    """`python collegedash.py onboard <argv>` in process, against a copy of `reg`. collect_plan and
    build are stand-ins that only record they were called; nothing here opens a socket."""
    r = Run()
    r.reg = copy.deepcopy(reg)

    def fake_collect_plan(plan, registry_, *, bios, workers):
        r.plans.append([p["slug"] for p, _ in plan])
        return [{"program": p["slug"], "collector": c, "outcome": "ok", "error": ""}
               for p, cs in plan for c in cs]

    def fake_run_collector(name, prog, registry_, **kw):
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

    import collect
    saved = {"load_registry": common.load_registry, "update_refresh_state": common.update_refresh_state,
             "collect_plan": collegedash.collect_plan, "run_collector": collegedash.run_collector,
             "_mark_onboarded": collegedash._mark_onboarded}
    saved_modules = {k: sys.modules.get(k) for k in ("collect.rpi", "build")}
    saved_rpi_attr = getattr(collect, "rpi", None)
    try:
        common.load_registry = lambda: r.reg
        common.update_refresh_state = lambda key, info: None
        collegedash.collect_plan = fake_collect_plan
        collegedash.run_collector = fake_run_collector
        collegedash._mark_onboarded = mark_onboarded
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
        collegedash.collect_plan = saved["collect_plan"]
        collegedash.run_collector = saved["run_collector"]
        collegedash._mark_onboarded = saved["_mark_onboarded"]
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


def test_guard_wiring_and_rebuild_once() -> None:
    print("guard-wiring & rebuild-once: cmd_onboard refuses a staged batch before rpi, "
          "and collects+builds an allowed one exactly once")
    reg = staged_d2()

    r = run_onboard(reg, ["d2-0", "d2-1", "d2-2"])
    ok("a staged batch of 2+ explicit slugs is refused, exit 2", r.code == 2, r.code)
    ok("rpi was not asked - refused before any request is made", r.rpi == [], r.rpi)
    ok("nothing was collected", r.plans == [], r.plans)
    ok("nothing was built", r.builds == 0, r.builds)
    ok("no program was marked onboarded", not any(p["onboarded"] for p in r.reg["programs"]))

    r = run_onboard(reg, ["d2-0", "d2-1", "d2-2", "--collect-staged-divisions", "D2"])
    ok("with the override the batch runs, exit 0", r.code == 0, r.out[-300:])
    ok("rpi was asked once, before collection", r.rpi == ["history", "current"], r.rpi)
    ok("collect_plan was called exactly ONCE, with all three programs - not once per program",
       r.plans == [["d2-0", "d2-1", "d2-2"]], r.plans)
    ok("build was called exactly ONCE for the whole batch, not once per program", r.builds == 1, r.builds)
    ok("all three are marked onboarded",
       all(p["onboarded"] for p in r.reg["programs"] if p["slug"] in ("d2-0", "d2-1", "d2-2")))

    # control: the pre-#143 shape - the same three programs, one onboard <slug> call each - builds
    # once PER PROGRAM, which is exactly the cost issue #143 is about
    reg2 = staged_d2()
    total_builds = 0
    for slug in ("d2-0", "d2-1", "d2-2"):
        rr = run_onboard(reg2, [slug, "--collect-staged-divisions", "D2"])
        reg2 = rr.reg
        total_builds += rr.builds
    ok("CONTROL: three separate onboard <slug> calls build three times, once each",
       total_builds == 3, total_builds)

    # a single explicit slug is not batch mode: no division guard, exactly as before #143
    r = run_onboard(reg, ["d2-0"])
    ok("one slug by itself is untouched by the new guard (same as before #143)",
       r.code == 0 and r.plans == [] , (r.code, r.plans))


def test_all_unaffected() -> None:
    print("all-unaffected: onboard --all's guard is not touched by any of this "
          "(full coverage: tests/onboard_guard_test.py)")
    reg = staged_d2()
    ok("--all is still refused for the same staged division",
       collegedash.batch_refusal(reg) != [])
    ok("MAX_BATCH is unchanged", collegedash.MAX_BATCH == 25)
    src = open(os.path.join(ROOT, "collegedash.py"), encoding="utf-8").read()
    ok("batch_refusal's own source is untouched by this file's changes (still defines the two rules)",
       "def batch_refusal(reg" in src and "MAX_BATCH" in src[src.index("def batch_refusal"):src.index("def onboard_all")])


# ---------- per-host politeness, through the real gate ----------

GAP = 0.25
JITTER = 0.05


class Stub:
    """One host: a threaded HTTP server on its own port that records (path, arrived, sent)."""

    def __init__(self, name: str):
        self.name = name
        self.log: list[tuple[str, float, float]] = []
        self.lock = threading.Lock()
        stub = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                arrived = time.monotonic()
                body = b"<html>ok</html>" * 20
                time.sleep(0.02)
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                sent = time.monotonic()
                with stub.lock:
                    stub.log.append((self.path, arrived, sent))

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.host = f"127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, path: str) -> str:
        return f"http://{self.host}{path}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def violations(stub: Stub, min_gap: float) -> list[str]:
    rows = sorted(stub.log, key=lambda r: r[1])
    bad = []
    for (p1, a1, s1), (p2, a2, s2) in zip(rows, rows[1:]):
        if a2 < s1:
            bad.append(f"overlap: {p2} arrived before {p1} was answered")
        if a2 - a1 < min_gap - 0.03:
            bad.append(f"gap: {p2} arrived {a2 - a1:.3f}s after {p1} (< {min_gap}s)")
    return bad


@contextlib.contextmanager
def fresh_state(tmp: str):
    """Politeness/gate state reset to the suite's short timings, and refresh-state writes (both the
    per-program ones from record_outcomes and onboard_batch's own summary) redirected to a scratch
    file rather than public/archive/refresh-state.json."""
    saved = (common.CACHE_DIR, common.MIN_GAP_SECONDS, common.JITTER_SECONDS, common.REFRESH_STATE_PATH)
    common.CACHE_DIR = tempfile.mkdtemp(dir=tmp)
    common.MIN_GAP_SECONDS, common.JITTER_SECONDS = GAP, JITTER
    common.REFRESH_STATE_PATH = os.path.join(tempfile.mkdtemp(dir=tmp), "refresh-state.json")
    common.write_json(common.REFRESH_STATE_PATH, {})
    common._gates.clear()
    common._last_request_at.clear()
    common._robots.clear()
    common._host_delay.clear()
    common._key_locks.clear()
    try:
        yield
    finally:
        common.CACHE_DIR, common.MIN_GAP_SECONDS, common.JITTER_SECONDS, common.REFRESH_STATE_PATH = saved


@contextlib.contextmanager
def gate_disabled():
    """The deliberately broken version: politeness switched off, everything else unchanged - proof
    that the checker below can fail, not only pass."""
    real_polite = common._polite

    @contextlib.contextmanager
    def no_gate(url):
        yield common._HostGate()  # a gate nobody else shares, never waited on

    common._polite = no_gate
    try:
        yield
    finally:
        common._polite = real_polite


MODULES = {"scorecard": "scorecard", "climate": "climate", "wikipedia": "wikipedia", "athletics": "athletics_site",
          "tds": "commitments_tds", "soccerwire": "commitments_soccerwire", "news": "news", "camps": "camps"}


@contextlib.contextmanager
def fetching_collectors(shared: Stub, own_of: dict):
    """Every collector for a program fetches the shared host once and its own host once - a program
    from a real onboard batch touches several hosts, some of them shared with every other program
    (SoccerWire, TopDrawerSoccer, Wikipedia), which is exactly the case this proof is about."""
    import importlib
    mods = {name: importlib.import_module(f"collect.{m}") for name, m in MODULES.items()}
    real = {name: mod.collect for name, mod in mods.items()}

    def make(name):
        def collect(program, registry_, **kw):
            common.fetch(shared.url(f"/{name}/{program['slug']}"), max_age_hours=None)
            own = own_of[program["slug"]]
            common.fetch(own.url(f"/{name}"), max_age_hours=None)
        return collect

    for name, mod in mods.items():
        mod.collect = make(name)
    try:
        yield
    finally:
        for name, mod in mods.items():
            mod.collect = real[name]


@contextlib.contextmanager
def build_stubbed():
    """onboard_batch calls `import build; build.build(reg)` - stand in for the real thing, which
    would otherwise run against the actual public/data/programs on disk. Nothing about the fetch
    layer this case is proving anything about goes through build()."""
    fake = types.ModuleType("build")
    fake.build = lambda registry_: None
    saved = sys.modules.get("build")
    sys.modules["build"] = fake
    try:
        yield
    finally:
        if saved is None:
            sys.modules.pop("build", None)
        else:
            sys.modules["build"] = saved


def test_per_host_politeness() -> None:
    print("per-host-politeness: an onboard batch never sends a shared host two requests at once, "
          "and the gap holds")
    n = 6
    shared = Stub("shared")
    own = {f"p{i}": Stub(f"own{i}") for i in range(n)}
    reg = registry([program(f"p{i}") for i in range(n)], onboarded_divisions=("D1",))
    for p in reg["programs"]:
        p["onboarded"] = True  # already onboarded: this proof is about the fetch layer, not the guard
    try:
        with tempfile.TemporaryDirectory() as tmp:
            with fresh_state(tmp), fetching_collectors(shared, own), build_stubbed():
                code = collegedash.onboard_batch(copy.deepcopy(reg), [f"p{i}" for i in range(n)],
                                                 bios=False, workers=6)
            ok("the batch ran clean", code == 0, code)
            ok(f"the shared host saw one request per program per collector ({n} programs x "
               f"{len(collegedash.COLLECTORS)} collectors)",
               len(shared.log) == n * len(collegedash.COLLECTORS), len(shared.log))
            bad = violations(shared, GAP)
            ok(f"the shared host: no overlap, arrivals >= {GAP}s apart, under 6-way concurrency",
               not bad, "; ".join(bad[:4]))
            for slug, s in own.items():
                bad = violations(s, GAP)
                ok(f"{slug}'s own host: no overlap either ({len(s.log)} requests)", not bad, "; ".join(bad[:2]))

            # control: the exact same load, with the gate disabled - proof the checker above is one
            # that can fail, not a tautology that always passes
            shared.log.clear()
            for s in own.values():
                s.log.clear()
            with fresh_state(tmp), gate_disabled(), fetching_collectors(shared, own), build_stubbed():
                collegedash.onboard_batch(copy.deepcopy(reg), [f"p{i}" for i in range(n)], bios=False, workers=6)
            ok("CONTROL: with the gate disabled, the same checker reports violations on the shared host",
               len(violations(shared, GAP)) > 0, f"{len(violations(shared, GAP))} found")
    finally:
        shared.close()
        for s in own.values():
            s.close()


def main(argv=None) -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    VERBOSE = args.verbose
    for case in (test_explicit_slugs, test_guard_reuse, test_guard_wiring_and_rebuild_once,
                test_all_unaffected, test_per_host_politeness):
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
