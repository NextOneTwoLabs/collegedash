"""
Merge every program's machine sources (programs/<slug>/sources/*.json), the human-written
curated.json and commitments.reviewed.json into the published profiles under public/data/.

  public/data/programs/<slug>.json   full profile (what the dashboard renders)
  public/data/programs/index.json    one summary row per program (list/filter views)
  public/data/commitments/index.json every resolved commitment across programs
  public/data/camps/index.json       every published camp across programs, within the date window

Every section carries _meta {source, url, asOf} so the UI can show provenance and staleness.
Curated fields override machine fields; machines never write curated.json.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import urllib.parse
from collections import Counter, defaultdict

import clubs
import schools
import trends
from collect import common
from collect.camps import classify_camp
from collect.commitments_tds import record_key

CURRENT_SEASON_FALLBACK = dt.date.today().year
# Where a real build publishes. Captured at import, before any test swaps common's output dirs, so
# that a build into a scratch directory can be told from the one that publishes: the club review
# report lives in data/, which is outside the swap, and a test run must not rewrite it
# (tests/seasons_test.py and tests/profile_pruning_test.py both run build() into a temp dir).
_PUBLISHED_PROGRAMS_DIR = os.path.abspath(common.PROGRAMS_OUT_DIR)
# Sources whose absence is not staleness: a program never collected for camps (new program, collector
# not yet run) shows "not collected yet" in the UI instead of a stale banner. They are also not in
# the completeness checks.
OPTIONAL_ENVS = {"camps"}
# Seasons that were never played, and so will never have an RPI table. load_rpi_finals otherwise
# fails the build for any season after the archive's last year that resolves no table, which is
# what stops a lost weekly/ snapshot from silently blanking a season on all 350 profiles - but a
# cancelled season is the one case where nothing is wrong. 2020 is the precedent: COVID moved the
# women's championship to spring 2021, and the Chris Thomas archive has no 2020 sheet. It needs no
# entry here, because the gap is only checked above the archive's last year. Add a year here (with
# the reason) only when the NCAA played no season; never to quiet a missing snapshot.
UNPLAYED_SEASONS: set[int] = set()
GRADUATING = {"SR", "R-SR", "GR"}
POS_ORDER = ["GK", "D", "M", "F"]
CLASS_ORDER = ["FR", "R-FR", "SO", "R-SO", "JR", "R-JR", "SR", "R-SR", "GR"]
REGIONS = {
    "West": {"CA", "OR", "WA", "NV", "AZ", "UT", "ID", "MT", "WY", "CO", "NM", "HI", "AK"},
    "Midwest": {"OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "KS", "NE", "SD", "ND"},
    "South": {"TX", "OK", "AR", "LA", "MS", "AL", "TN", "KY", "GA", "FL", "SC", "NC"},
    "Mid-Atlantic": {"VA", "WV", "MD", "DC", "DE", "PA", "NJ", "NY"},
    "Northeast": {"CT", "RI", "MA", "VT", "NH", "ME"},
}
NICKNAMES = {"ale": "alessandra", "alex": "alexandra", "liz": "elizabeth", "beth": "elizabeth", "kate": "katherine",
             "katie": "katherine", "maddie": "madeline", "maddy": "madison", "abby": "abigail", "ellie": "eleanor",
             "sam": "samantha", "izzy": "isabella", "bella": "isabella", "sophie": "sophia", "mia": "amelia",
             "gabby": "gabriella", "nat": "natalie", "jess": "jessica", "becca": "rebecca", "lexi": "alexis",
             "lily": "lillian", "olivia": "olivia", "livi": "olivia", "vi": "vienna"}


def region_for(state: str | None) -> str | None:
    for r, states in REGIONS.items():
        if state in states:
            return r
    return None


def _meta(env: dict | None, url: str | None = None) -> dict | None:
    if not env:
        return None
    return {"source": env.get("collector"), "url": url or env.get("sourceUrl"), "asOf": env.get("fetchedAt")}


def _age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        t = dt.datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 86400


# ---------- the published set ----------

KNOWN_DIVISIONS = {"D1", "D2", "D3"}
_PROFILE_FILE = re.compile(r"([a-z0-9][a-z0-9-]*)\.json")


def published_programs(registry: dict) -> list[dict]:
    """The programs the site publishes: onboarded entries of registry.programs whose division is in
    registry.onboardedDivisions. heldPrograms are never here (issue #100). A registry without
    onboardedDivisions predates that field and publishes every onboarded program."""
    onboarded = registry.get("onboardedDivisions")
    programs = list(common.iter_programs(registry))
    if onboarded is None:
        return programs
    return [p for p in programs if p.get("division") in onboarded]


def profile_slugs_on_disk(out_dir: str) -> set[str]:
    """Slugs of the <slug>.json profiles in out_dir: regular files whose whole name is a slug plus
    `.json`. index.json, temp files, stray names, and anything that is not a regular file (a directory
    or a symlink carrying a profile's name) are not profiles and are never touched."""
    if not os.path.isdir(out_dir):
        return set()
    with os.scandir(out_dir) as it:
        return {m.group(1) for e in it
                if e.name != "index.json" and (m := _PROFILE_FILE.fullmatch(e.name)) and e.is_file(follow_symlinks=False)}


def prune_explanations(registry: dict) -> dict[str, str]:
    """slug -> why the registry says this program is not published. Deliberately written without
    published_programs(), so a bug in that function cannot explain its own deletions:
      - an entry of heldPrograms (reclassified out, or in no Directory list);
      - an entry of programs that is not onboarded;
      - an entry of programs whose division is not in onboardedDivisions."""
    out: dict[str, str] = {}
    onboarded = registry.get("onboardedDivisions")
    for p in registry.get("heldPrograms") or []:
        out[p["slug"]] = f"held ({(p.get('hold') or {}).get('reason', 'no reason recorded')})"
    for p in registry.get("programs") or []:
        if not p.get("onboarded"):
            out[p["slug"]] = "in the registry but not onboarded"
        elif onboarded is not None and p.get("division") not in onboarded:
            out[p["slug"]] = f"division {p.get('division')} is not onboarded"
    return out


def plan_prune(registry: dict, published: set[str], out_dir: str, *, allow_unexplained: frozenset[str] = frozenset()) -> dict[str, str]:
    """slug -> reason, for every profile in out_dir that pruning will delete. Raises, deleting nothing,
    unless every profile outside the published set is explained by the registry (see
    prune_explanations). No share cap: a D2 switch-off is fully explained and needs no override,
    while a registry that loaded short leaves slugs nothing explains and is refused whatever the count.

    Refused outright:
      - an empty published set (a registry that failed to load is not "no programs");
      - onboardedDivisions naming a division that does not exist, which would explain every program away;
      - a slug that is both published and explained, which means the two readings of the registry disagree;
      - a profile the registry does not explain. `allow_unexplained` names such slugs one by one for a
        single run (`python build.py --allow-unexplained-prune a,b`); a slug in it that is not actually
        stale on disk also raises, so an override cannot outlive the files it was written for.
    """
    if not published:
        raise RuntimeError("prune: the published set is empty; refusing to delete any profile")
    onboarded = registry.get("onboardedDivisions")
    if onboarded is not None and (not onboarded or set(onboarded) - KNOWN_DIVISIONS):
        raise RuntimeError(f"prune: onboardedDivisions {onboarded!r} is not a non-empty list of {sorted(KNOWN_DIVISIONS)}; "
                           f"refusing to delete any profile")
    explained = prune_explanations(registry)
    both = sorted(published & set(explained))
    if both:
        raise RuntimeError(f"prune: {len(both)} programs are both published and explained as unpublished "
                           f"({', '.join(both[:5])}); refusing to delete any profile")
    stale = profile_slugs_on_disk(out_dir) - published
    unexplained = sorted(stale - set(explained) - set(allow_unexplained))
    if unexplained:
        raise RuntimeError(f"prune: {len(unexplained)} profiles are outside the published set and nothing in the registry "
                           f"explains why ({', '.join(unexplained[:8])}); refusing to delete any. A registry that loaded "
                           f"short looks exactly like this. If these programs really were removed, name them for one run: "
                           f"python build.py --allow-unexplained-prune {','.join(unexplained[:3])}")
    unused = sorted(set(allow_unexplained) - (stale - set(explained)))
    if unused:
        raise RuntimeError(f"prune: --allow-unexplained-prune names {', '.join(unused)}, which is not an unexplained "
                           f"stale profile here; refusing to delete any profile")
    return {slug: explained.get(slug, "named by --allow-unexplained-prune") for slug in sorted(stale)}


def prune_profiles(plan: dict[str, str], published: set[str], out_dir: str) -> list[str]:
    """Delete the profiles plan_prune decided on; return the slugs deleted. Every target is re-checked
    before anything is removed: it must not be published and must still be a regular profile file, so
    a directory or symlink that appeared since planning stops the prune before the first deletion."""
    for slug in plan:
        path = os.path.join(out_dir, f"{slug}.json")
        if slug in published:  # plan_prune cannot produce this; the cost of being wrong is a live page
            raise RuntimeError(f"prune: refusing to delete published profile {slug}")
        if not (os.path.isfile(path) and not os.path.islink(path)):
            raise RuntimeError(f"prune: {path} is no longer a regular profile file; refusing to delete any profile")
    for slug, why in plan.items():
        os.remove(os.path.join(out_dir, f"{slug}.json"))
        common.log(f"build: pruned {slug}.json ({why})")
    return list(plan)


# Long-standing D1 programs (in the registry before issue #100) that may be absent from the published set, each
# reviewed. PR #112 review, R1: pruning deletes whatever the registry explains, so a registry mistake that makes
# live programs look explained (onboarded: false, a move to heldPrograms) would delete their pages with build and
# validate passing. validate therefore requires the unpublished long-standing programs to be exactly this list.
# A real reclassification or removal is a one-line edit here, in its own reviewed PR; so is a program returning
# (Saint Francis leaves this list the day D3 is onboarded).
LONG_STANDING_PATH = os.path.join(common.ROOT, "tests", "fixtures", "registry", "pre-100-programs.json")
REVIEWED_UNPUBLISHED = {
    "saint-francis": "issue #100: the NCAA Directory lists it in D3 for 2026-27; held until D3 is onboarded",
    "mississippi-val": "issue #100: in no NCAA Directory women's soccer list for 2026-27; held",
}


def check_membership_anchor(registry: dict) -> bool:
    """The long-standing D1 programs missing from the published set are exactly REVIEWED_UNPUBLISHED."""
    doc = common.read_json(LONG_STANDING_PATH)
    if not doc or not doc.get("programs"):
        print(f"MEMBERSHIP: cannot read the long-standing program list {LONG_STANDING_PATH}")
        return False
    long_standing = {p["slug"] for p in doc["programs"]}
    unpublished = long_standing - {p["slug"] for p in published_programs(registry)}
    ok = True
    for slug in sorted(unpublished - set(REVIEWED_UNPUBLISHED)):
        print(f"MEMBERSHIP {slug}: a long-standing D1 program is no longer published and is not in build.REVIEWED_UNPUBLISHED "
              f"- if this is a real reclassification or removal, add it there in a reviewed PR; otherwise the registry is wrong")
        ok = False
    for slug in sorted(set(REVIEWED_UNPUBLISHED) - unpublished):
        print(f"MEMBERSHIP {slug}: listed in build.REVIEWED_UNPUBLISHED but published again - remove it from that list")
        ok = False
    return ok


def check_no_stale_profiles(registry: dict) -> bool:
    """Every profile on disk belongs to a published program (issue #110: a program that leaves the
    published set must not stay reachable by URL)."""
    stale = sorted(profile_slugs_on_disk(common.PROGRAMS_OUT_DIR) - {p["slug"] for p in published_programs(registry)})
    for slug in stale:
        print(f"STALE {slug}: public/data/programs/{slug}.json is not a published program")
    return not stale


# The publish gate's reviewed list (#94; Bianque's review of #252, plan revision 1 on #94): a published program
# with no stored athletics source that is explained by neither athletics.skipReason nor
# athletics.rosterRequiresBrowser. Each entry is slug -> {"reason": why it publishes anyway, "date": "YYYY-MM-DD"
# it was reviewed}, added in a reviewed PR. It starts empty: the six D1 programs with no athletics source
# (oklahoma, utah-state, wyoming, ohio-university, george-mason, st-thomas) all carry rosterRequiresBrowser.
# check_publish_gate() fails on a stale entry, so the list cannot quietly grow.
PUBLISH_GATE_REVIEWED: dict[str, dict] = {}
_GATE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_publish_gate(registry: dict, *, has_athletics=None, reviewed: dict | None = None) -> bool:
    """Nothing is published silently empty (#94). Every published program has a stored athletics source
    (programs/<slug>/sources/athletics.json), or says why not with one of three explicit reasons:
      - athletics.skipReason (e.g. a host that refuses the collector, the D2 treatment);
      - athletics.rosterRequiresBrowser (the no-Playwright rule; the collector skips on it);
      - an entry of PUBLISH_GATE_REVIEWED, with a reason and a date.
    It also fails on a reviewed entry that is stale (the program now has data, or is not published) or
    malformed, and on rosterRequiresBrowser set on a program that has athletics data, which means the flag is
    out of date and is stopping a collector that would work.

    The build never hides a roster-less program by itself: that would make pages appear and vanish whenever
    a site has a bad day. The gate only makes the reason a recorded, reviewed fact.

    Scope is the published set. A staged division joins it when it is switched on (the D3 switch, #94 PR 4),
    so every D3 program is checked by the PR that publishes it."""
    if has_athletics is None:
        def has_athletics(slug: str) -> bool:
            return os.path.isfile(common.source_path(slug, "athletics"))
    reviewed = PUBLISH_GATE_REVIEWED if reviewed is None else reviewed
    published = {p["slug"]: p for p in published_programs(registry)}
    ok = True
    for slug, program in sorted(published.items()):
        ath = program.get("athletics") or {}
        data = has_athletics(slug)
        browser = ath.get("rosterRequiresBrowser") is True
        if data:
            if browser:
                print(f"GATE {slug}: athletics.rosterRequiresBrowser is set but the program has athletics data - "
                      f"remove the flag so the collector runs again")
                ok = False
            continue
        skip = ath.get("skipReason")
        if (isinstance(skip, str) and skip.strip()) or browser or slug in reviewed:
            continue
        print(f"GATE {slug}: published with no athletics data and no recorded reason - give it athletics.skipReason "
              f"or athletics.rosterRequiresBrowser, or add it to build.PUBLISH_GATE_REVIEWED with a reason and a date")
        ok = False
    for slug, entry in sorted(reviewed.items()):
        reason = entry.get("reason") if isinstance(entry, dict) else None
        date = entry.get("date") if isinstance(entry, dict) else None
        if not (isinstance(reason, str) and reason.strip()) or not (isinstance(date, str) and _GATE_DATE.match(date)):
            print(f"GATE {slug}: PUBLISH_GATE_REVIEWED entry needs a non-empty reason and a YYYY-MM-DD date, has {entry!r}")
            ok = False
        if slug not in published:
            print(f"GATE {slug}: stale PUBLISH_GATE_REVIEWED entry - the program is not published; remove it")
            ok = False
        elif has_athletics(slug):
            print(f"GATE {slug}: stale PUBLISH_GATE_REVIEWED entry - the program now has athletics data; remove it")
            ok = False
    return ok


# A staged division this repository currently expects, and the exact entry count it must have
# (issue #140). Like REVIEWED_UNPUBLISHED above, this is a reviewed anchor, not "whatever
# stagedDivisions says today": a real change - D2 finally onboarded and dropped from
# stagedDivisions, or another division staged alongside it - is a one-line edit here, in its own
# reviewed PR. Without an anchor, check_staged_registry() would only ever inspect whatever is
# staged at the moment it runs, so the day stagedDivisions goes empty (a bad merge, a hand edit)
# it would have nothing to look at and silently pass - the exact defect class issue #140 is about.
#
# The anchor has to run both ways (issue #149): a division named here that is not staged is a
# failure (below), and so is a division in stagedDivisions with no entry here. Without the second
# direction, a division staged later and never added to this dict would get the structural checks
# below and no count anchor, silently - staging D3 without writing its count down here would pass
# every check that exists. check_staged_registry() fails that case too, on purpose.
#
# D2 left this dict when it was published (#197). D3 is staged by #190: the 2026-27 Directory lists 416
# D3 programs, and 415 of them are staged entries in `programs`. The 416th is saint-francis, published
# in D1 before #100, which stays in heldPrograms until D3 is onboarded.
STAGED_DIVISION_COUNTS: dict[str, int] = {"D3": 415}

# A slug is lowercase words separated by single hyphens, with no leading, trailing or doubled
# hyphen - the shape every slug in the registry already has (collect/registry_builder.py's
# slug_ladder never produces anything else).
STAGED_SLUG_SHAPE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def check_staged_registry(registry: dict) -> bool:
    """The structural invariants that guard a published program also guard a staged one, checked
    here because nothing else does: a staged entry publishes no profile, so build's own schema
    validation above never reaches it, and `collegedash.py validate` is the one command that runs
    on every push (issue #140).

    "Staged" is deliberately not "onboarded: false". A staged division's batch is collected
    (`onboarded: true`, `onboardedAt` set, its sources kept fresh) long before the division itself
    is onboarded - that is the whole point of the staged-division design (issue #94, option A) - so
    a staged entry can carry `onboarded: true` and still be exactly as staged as one that does not.
    What makes an entry staged is its division being in registry.stagedDivisions; the onboarded flag
    is not part of that test here, on either side of it.

    STAGED_DIVISION_COUNTS is checked first and unconditionally, both ways: a division named there
    that is not currently in registry.stagedDivisions is a failure of this function, not something
    it quietly has nothing to do because of - that is what keeps an empty (or emptied) staged set
    from passing. So is a division in registry.stagedDivisions with no entry in
    STAGED_DIVISION_COUNTS (issue #149): staging a division is not allowed to ship without a
    reviewed count anchor for it, because an anchor nobody wrote is a check nobody runs.
    """
    from collect import registry_builder as rb  # local: only this check needs it

    ok = True
    try:
        staged_divs = set(rb.staged_divisions(registry))
    except ValueError as e:
        print(f"STAGED: registry.stagedDivisions is invalid: {e}")
        return False

    for division in STAGED_DIVISION_COUNTS:
        if division not in staged_divs:
            print(f"STAGED {division}: expected in registry.stagedDivisions {sorted(staged_divs)} with "
                  f"{STAGED_DIVISION_COUNTS[division]} entries, but it is not staged at all - if {division} "
                  f"published, remove it from build.STAGED_DIVISION_COUNTS in the same PR")
            ok = False
    for division in sorted(staged_divs - set(STAGED_DIVISION_COUNTS)):
        print(f"STAGED {division}: in registry.stagedDivisions but has no entry in build.STAGED_DIVISION_COUNTS "
              f"- add {division} with its Directory count to STAGED_DIVISION_COUNTS, in the same PR that stages it")
        ok = False
    if not staged_divs:
        # Nothing below has anything left to check once no division is staged; the anchor loop
        # above is what stops that from reading as "nothing to check, so nothing failed".
        return ok

    programs = registry.get("programs") or []
    held = registry.get("heldPrograms") or []
    staged = [p for p in programs if p.get("division") in staged_divs]

    for division, want in STAGED_DIVISION_COUNTS.items():
        if division in staged_divs:
            got = sum(1 for p in staged if p.get("division") == division)
            if got != want:
                print(f"STAGED {division}: expected {want} staged entries, found {got}")
                ok = False

    for p in staged:
        slug = p.get("slug") or "<no slug>"
        org = (p.get("ids") or {}).get("ncaaOrgId")
        if not isinstance(org, int):
            print(f"STAGED {slug}: ids.ncaaOrgId is {org!r}, not an int")
            ok = False
        state = (p.get("location") or {}).get("state")
        if not state:
            print(f"STAGED {slug}: location.state is {state!r}, not set")
            ok = False
        if not (isinstance(p.get("slug"), str) and STAGED_SLUG_SHAPE.match(p["slug"])):
            print(f"STAGED {slug}: slug does not match lowercase-hyphenated shape {STAGED_SLUG_SHAPE.pattern}")
            ok = False

    # A D1 conference is stored as the label from CONFERENCE_LABELS.values() (e.g. "ACC", "CUSA");
    # every other division keeps the Directory's own spelling (registry_builder's conference_label(),
    # LABELLED_DIVISION == "D1"). A staged row of another division carrying a label only that table
    # produces was run through it by mistake ("Conference USA" stored as "CUSA"). Since #199 D1's
    # independent is plain "Independent", the same string as D2's 8 independents, so the set is
    # rb.d1_only_labels(): labels that differ from the Directory name they come from. A shared string
    # such as "Independent" is told apart by the entry's division, never flagged by its value.
    d1_only = rb.d1_only_labels()
    mislabelled = sorted(p["slug"] for p in staged
                         if p.get("division") != rb.LABELLED_DIVISION and p.get("conference") in d1_only)
    if mislabelled:
        print(f"STAGED: {len(mislabelled)} staged entries carry a Division I conference label instead of "
              f"the Directory's own spelling: {', '.join(mislabelled[:5])}")
        ok = False

    # Duplicates are checked against the whole registry, not only within the staged set: a slug or
    # orgId a staged entry shares with a published or held program is exactly as dangerous as one
    # it shares with another staged entry.
    everything = programs + held
    slug_counts = Counter(p["slug"] for p in everything if p.get("slug"))
    dup_slugs = sorted({p["slug"] for p in staged if slug_counts.get(p.get("slug"), 0) > 1})
    if dup_slugs:
        print(f"STAGED: {len(dup_slugs)} staged slugs are not unique across the registry: {', '.join(dup_slugs[:5])}")
        ok = False
    org_counts = Counter((p.get("ids") or {}).get("ncaaOrgId") for p in everything
                         if isinstance((p.get("ids") or {}).get("ncaaOrgId"), int))
    dup_orgs = sorted({p["slug"] for p in staged
                       if isinstance((p.get("ids") or {}).get("ncaaOrgId"), int)
                       and org_counts.get(p["ids"]["ncaaOrgId"], 0) > 1})
    if dup_orgs:
        print(f"STAGED: {len(dup_orgs)} staged entries carry an ncaaOrgId that is not unique across the "
              f"registry: {', '.join(dup_orgs[:5])}")
        ok = False

    return ok


# ---------- name matching ----------

def _name_parts(name: str) -> tuple[str, str]:
    parts = common.norm_name(name).split()
    if not parts:
        return "", ""
    first = NICKNAMES.get(parts[0], parts[0])
    return first, parts[-1]


def same_person(a: str, b: str) -> bool:
    """True for exact normalised matches and for obvious variants (nickname vs full first name,
    same last name)."""
    na, nb = common.norm_name(a), common.norm_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    fa, la = _name_parts(a)
    fb, lb = _name_parts(b)
    if la != lb:
        # hyphenated / double last names: accept if one contains the other
        if not (la and lb and (la in nb.split() or lb in na.split())):
            return False
    if fa == fb:
        return True
    if len(fa) >= 3 and len(fb) >= 3 and (fa.startswith(fb) or fb.startswith(fa)):
        return True
    return False


# ---------- RPI ----------

def load_rpi_history() -> dict[int, dict[str, dict]]:
    out = {}
    if not os.path.isdir(common.RPI_OUT_DIR):
        return out
    for f in os.listdir(common.RPI_OUT_DIR):
        if re.fullmatch(r"\d{4}\.json", f):
            d = common.read_json(os.path.join(common.RPI_OUT_DIR, f), {})
            out[int(f[:4])] = {t["team"]: t for t in d.get("teams", [])}
    return out


def load_rpi_current() -> dict | None:
    return common.read_json(os.path.join(common.RPI_OUT_DIR, "current.json"))


def load_rpi_finals(cur_season: int) -> dict[int, dict]:
    """season -> the NCAA RPI table that stands for that season, for every finished season a weekly
    snapshot covers.

    The archive (public/data/rpi/<year>.json) is the source of record for every season it
    holds, so its *rank* wins wherever it exists - but a season it covers is still resolved here,
    because archive rows carry no record and build_seasons still needs the snapshot's one. Dropping
    such a season from this dict is what made adding a 2025 archive sheet - an ordinary edit to
    the 17 curated entries in registry.sources.rpiHistory.sheets - collapse lastSeason from 350 to
    173 and re-dash the Record column for 177 programs. Seasons above the archive can only come
    from the NCAA's own table, and current.json is not a home for them: collect/rpi.py
    overwrites that file the day the NCAA posts the first weekly table of a new season, which would
    erase the finished season from all 350 programs at once. The per-through-date snapshots under
    weekly/<season>/ are immutable, so the last snapshot of a finished season is its final table;
    current.json is read only for the season being played now, whose rows are marked in progress.

    On semantics: the NCAA's record column counts Division I opponents only (its nonDiv1 games are
    excluded), so it can differ from a schedule- or Wikipedia-sourced record. Those two stay
    authoritative wherever they exist; this only fills a season that would otherwise carry none.

    Raises rather than degrading, for the reason load_academic_ranks does: an empty weekly/ would
    blank the most recent season for every program at once, and missing data must not be
    indistinguishable from a program that simply did not play.

    The escape hatch, for the one case where that distinction is real: if a season after the
    archive's last year is genuinely never played - the 2020 precedent, when COVID moved the
    women's season to spring 2021 - no table will ever exist for it and this will fail every build
    until someone says so. Add the year to UNPLAYED_SEASONS above, with a comment saying why. Do
    not fabricate a snapshot under weekly/<year>/ to quiet it: that publishes ranks nobody awarded.
    A hole *inside* the archive needs nothing, because the gap is only checked above its last year
    (which is why the missing 2020 sheet is already silent today). README, "Refresh runs and
    failures", carries the same note for whoever meets the error at 03:00.
    """
    archived = set()
    if os.path.isdir(common.RPI_OUT_DIR):
        archived = {int(f[:4]) for f in os.listdir(common.RPI_OUT_DIR) if re.fullmatch(r"\d{4}\.json", f)}
    weekly_dir = os.path.join(common.RPI_OUT_DIR, "weekly")
    out: dict[int, dict] = {}
    if os.path.isdir(weekly_dir):
        for name in sorted(os.listdir(weekly_dir)):
            season_dir = os.path.join(weekly_dir, name)
            if not re.fullmatch(r"\d{4}", name) or not os.path.isdir(season_dir):
                continue
            season = int(name)
            if season == cur_season:
                continue  # the season being played comes from current.json, below
            files = sorted(f for f in os.listdir(season_dir) if f.endswith(".json"))
            doc = common.read_json(os.path.join(season_dir, files[-1])) if files else None
            if doc and doc.get("teams"):
                out[season] = doc
    cur = load_rpi_current()
    if cur and cur.get("teams") and cur.get("season") == cur_season:
        out[cur_season] = cur
    # Every finished season after the archive's last year must resolve to a table. Checking the gap
    # rather than merely "did anything load" is what makes this a guard: once the NCAA posts the
    # first table of a new season, a lost weekly/ would otherwise leave the previous season silently
    # blank on all 350 profiles while current.json still supplied the new one.
    missing = [y for y in range((max(archived) + 1) if archived else cur_season, cur_season)
               if y not in out and y not in UNPLAYED_SEASONS]
    if missing or not (archived or out):
        raise FileNotFoundError(
            f"rpi: no season table resolved for {missing or 'any season'} under {weekly_dir} or "
            f"current.json. The Chris Thomas archive stops at {max(archived, default='(nothing)')}, so "
            f"those seasons would publish with no rank and, for a program Wikipedia does not cover, "
            f"no season at all. If a season was genuinely never played, add it to "
            f"UNPLAYED_SEASONS in build.py; do not fabricate a snapshot")
    return out


def rpi_weekly_for(school: str, season: int) -> list[dict]:
    base = os.path.join(common.RPI_OUT_DIR, "weekly", str(season))
    out = []
    if not os.path.isdir(base):
        return out
    for f in sorted(os.listdir(base)):
        d = common.read_json(os.path.join(base, f), {})
        for t in d.get("teams", []):
            if t.get("school") == school:
                out.append({"through": d.get("throughGames"), "rank": t["rank"], "record": t.get("record")})
                break
    return out


# ---------- sections ----------

# NCAA Division I women's soccer champions by season (NCAA record book; 2025 per the College Cup
# result). Wikipedia infobox rows are cross-checked against this so a mislabelled row can never
# publish a conference title as a national one.
NCAA_D1_WOMENS_CHAMPIONS = {
    1982: "north-carolina", 1983: "north-carolina", 1984: "north-carolina", 1985: "george-mason",
    1986: "north-carolina", 1987: "north-carolina", 1988: "north-carolina", 1989: "north-carolina",
    1990: "north-carolina", 1991: "north-carolina", 1992: "north-carolina", 1993: "north-carolina",
    1994: "north-carolina", 1995: "notre-dame", 1996: "north-carolina", 1997: "north-carolina",
    1998: "florida", 1999: "north-carolina", 2000: "north-carolina", 2001: "santa-clara",
    2002: "portland", 2003: "north-carolina", 2004: "notre-dame", 2005: "portland",
    2006: "north-carolina", 2007: "usc", 2008: "north-carolina", 2009: "north-carolina",
    2010: "notre-dame", 2011: "stanford", 2012: "north-carolina", 2013: "ucla",
    2014: "florida-state", 2015: "penn-state", 2016: "usc", 2017: "stanford",
    2018: "florida-state", 2019: "stanford", 2020: "santa-clara", 2021: "florida-state",
    2022: "ucla", 2023: "florida-state", 2024: "north-carolina", 2025: "florida-state",
}


# NCAA Division II women's soccer champions by season, named as NCAA.com's own championship history
# writes them (https://www.ncaa.com/history/soccer-women/d2, read 2026-09-16). Every played year was
# cross-checked against Wikipedia's "NCAA Division II women's soccer tournament" results table on the
# same day and the two agree on all 37; where NCAA.com spells a school out and Wikipedia abbreviates
# it ("Cal State East Bay" / "Cal State (H)", "Metro State" / "MSU") the spelled-out name is used.
# 1988 is the first tournament and 2020 was cancelled for COVID, so both are absent on purpose. No year
# is entered here that neither source shows; an unsourced year is reported by check_titles, never guessed.
#
# Keyed by champion NAME, not by slug as the D1 table is, because no Division II program is in the
# registry yet: their slugs do not exist to be written down. title_matches() joins a name to a program
# by exact normalised comparison with its registry name or short name, and D2_TITLE_SLUGS pins the ones
# that comparison cannot reach. That table is empty today and gains an entry per D2 champion as D2
# programs are onboarded - "Metro State" against "Metropolitan State University of Denver", say.
NCAA_D2_WOMENS_CHAMPIONS = {
    1988: "Cal State East Bay", 1989: "Barry", 1990: "Sonoma State", 1991: "Cal State Dominguez Hills",
    1992: "Barry", 1993: "Barry", 1994: "Franklin Pierce", 1995: "Franklin Pierce",
    1996: "Franklin Pierce", 1997: "Franklin Pierce", 1998: "Lynn", 1999: "Franklin Pierce",
    2000: "UC San Diego", 2001: "UC San Diego", 2002: "Christian Brothers", 2003: "Kennesaw State",
    2004: "Metro State", 2005: "Nebraska-Omaha", 2006: "Metro State", 2007: "Tampa",
    2008: "Seattle Pacific", 2009: "Grand Valley State", 2010: "Grand Valley State", 2011: "Saint Rose",
    2012: "West Florida", 2013: "Grand Valley State", 2014: "Grand Valley State",
    2015: "Grand Valley State", 2016: "Western Washington", 2017: "Central Missouri",
    2018: "Bridgeport", 2019: "Grand Valley State", 2021: "Grand Valley State",
    2022: "Western Washington", 2023: "Point Loma", 2024: "Cal Poly Pomona", 2025: "Florida Tech",
}
# Reviewed joins from a D2 champion name to a registry slug, for the ones normalisation cannot reach.
# Empty while no D2 program is published; each entry is a reviewed line in the PR that adds it.
D2_TITLE_SLUGS: dict[str, str] = {}
# Division III (#94): the cited NCAA_D3_WOMENS_CHAMPIONS table is added in its own PR, keyed by champion name
# as D2's is, together with its "D3" entry in CHAMPION_TABLES below and 'D3' in public/index.html's
# TITLE_TABLE_DIVISIONS (the two must name the same divisions). Until then a D3 program matches nothing and
# publishes no titles. The D3 join needs no other code: title_matches() reads a name-keyed table, and this
# pin table, for every division but D1.
D3_TITLE_SLUGS: dict[str, str] = {}
CHAMPION_TABLES = {"D1": NCAA_D1_WOMENS_CHAMPIONS, "D2": NCAA_D2_WOMENS_CHAMPIONS}

_TITLE_NAME_DROP = re.compile(r"\b(the|university|universities|college|of|at)\b")


def _title_name(s: str) -> str:
    """'The College of Saint Rose' -> 'saint rose'; 'University of Nebraska at Omaha' -> 'nebraska omaha'."""
    s = common.strip_accents(s or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = _TITLE_NAME_DROP.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def title_matches(program: dict, champion: str | None, division: str | None) -> bool:
    """Is this program the champion the table names? D1 names a slug, so the comparison is exact. D2
    and D3 name a school, so it is an exact match on the normalised registry name or short name, or a pinned
    entry in that division's D2_TITLE_SLUGS / D3_TITLE_SLUGS. Nothing fuzzy: a near-match here publishes another school's title. A
    division with no champions table of its own matches nothing - it does not borrow another's."""
    if not champion or division not in CHAMPION_TABLES:
        return False
    if division == "D1":
        return champion == program.get("slug")
    pins = {"D2": D2_TITLE_SLUGS, "D3": D3_TITLE_SLUGS}.get(division) or {}
    if pins.get(champion):
        return pins[champion] == program.get("slug")
    want = _title_name(champion)
    return bool(want) and want in {_title_name(program.get("name") or ""), _title_name(program.get("shortName") or "")}


def national_titles(program: dict, wiki_years: list[int]) -> tuple[list[int], list[int]]:
    """(the years this program won its own division's championship, the years something claimed for it
    that no champions table supports).

    Issue #113: the second half used to be logged and thrown away, and the first half was always read
    from the Division I table, so a Division II program's real titles were dropped in silence. Both
    halves are now per division and both are published: the unsourced years go into the profile as
    program.unsourcedTitleClaims and check_titles reports them."""
    division = program.get("division")
    table = CHAMPION_TABLES.get(division) or {}
    official = sorted(y for y, champ in table.items() if title_matches(program, champ, division))
    unsourced = sorted(set(wiki_years or []) - set(official))
    if unsourced:
        common.log(f"build: {program.get('slug')}: title years {unsourced} are not in the {division or 'unknown-division'} "
                   f"champions table and are not published; check_titles reports them")
    return official, unsourced


# "(23rd season)" after a name in the Wikipedia infobox's head-coach field; a footnote marker such as
# "Jeff Hosler [ 2 ] (4th season)" may sit between the two, and a co-coached program lists two
# ("Tari St. John (18th season) Rob Alman (12th season)").
_INFOBOX_SEASON_RE = re.compile(r"([^()\[\]]+?)\s*(?:\[\s*\w+\s*\]\s*)*\((\d{1,2})(?:st|nd|rd|th)\s+season\)", re.I)


def infobox_season_number(infobox: str | None, head_name: str | None) -> int | None:
    """N from the infobox's "<name> (Nth season)", only when that name is the head coach's."""
    if not infobox or not head_name:
        return None
    for m in _INFOBOX_SEASON_RE.finditer(infobox):
        if same_person(m.group(1).strip(), head_name):
            return int(m.group(2))
    return None


def coach_since(head_name: str | None, seasons: list[dict], infobox: str | None,
                current_season: int | None = None) -> int | None:
    """The head coach's first season, or None when the stored Wikipedia source cannot show it (issue #168).

    It used to be the earliest season whose coach shared the head coach's LAST name, which published
    four wrong years: pittsburgh's Ben Waldrum "since 2018" (Randy Waldrum's first season),
    south-florida's Chris Brown "since 2007" (Denise Schilte-Brown's), and penn-state and west-virginia
    from seasons tables that name the same coach under an earlier surname. The year is now:

      1. the same person, by same_person (nickname-aware; a hyphenated surname contains the earlier one,
         so "Nikki Izzo" and "Nikki Izzo-Brown" are one coach, but Ben and Randy Waldrum are not);
      2. one unbroken run of seasons ending at the table's latest season - a coach who is not in the
         table's last season, or a gap in the run, gives no year rather than a year from before the gap.
         A season the table lists twice (nebraska 2024) is one season, when every row of it names
         this coach;
      3. published only when it agrees, within one season, with the infobox's "(Nth season)" for that
         coach. The count was written at some point between the table's latest season and today, and
         the source does not say when, so it is counted back from each of those two seasons and the
         run must agree with one of them. Beyond one season from both, the table and the infobox
         disagree about this coach and neither is taken. No "(Nth season)" for the head coach, no year.
    """
    run = wikipedia_run(head_name, seasons)
    if run is None:
        return None
    start, last = run
    n = infobox_season_number(infobox, head_name)
    if n is None:
        return None
    current = current_season if current_season is not None else CURRENT_SEASON_FALLBACK
    anchors = {last, max(current, last)}
    return start if any(abs((anchor - n + 1) - start) <= 1 for anchor in anchors) else None


def wikipedia_run(head_name: str | None, seasons: list[dict]) -> tuple[int, int] | None:
    """(first, last) season of the head coach's unbroken run ending at the table's latest season, before
    any infobox check (rules 1 and 2 of coach_since); None when the table's latest season is not theirs."""
    if not head_name or not seasons:
        return None
    by_year: dict[int, list[dict]] = {}
    for s in seasons:
        if isinstance(s.get("year"), int):
            by_year.setdefault(s["year"], []).append(s)
    years = sorted(by_year)

    def coached(year: int) -> bool:
        return all(r.get("headCoach") and same_person(r["headCoach"], head_name) for r in by_year[year])

    if not years or not coached(years[-1]):
        return None
    start = years[-1]
    for y in reversed(years[:-1]):
        if y != start - 1 or not coached(y):
            break
        start = y
    return start, years[-1]


def head_coach_first_season(program: dict, head_name: str | None, seasons: list[dict], infobox: str | None,
                            bio: dict | None) -> int | None:
    """The published first season (issue #168, part 2). The head coach's own bio page on the athletics site
    wins when it gives a year for this coach: it is the school's source, collected into athletics.json as
    headCoachBio by collect/coach_bio.py. A Wikipedia run that starts in a different year is logged, not used.
    With no bio year, the Wikipedia run confirmed by the infobox (coach_since) is the year, as before."""
    bio_year = None
    if bio and head_name and bio.get("firstSeason") and same_person(bio.get("name") or "", head_name):
        bio_year = bio["firstSeason"]
    if bio_year:
        run = wikipedia_run(head_name, seasons)
        if run and run[0] != bio_year:
            common.log(f"build: {program.get('slug')}: coachSince {bio_year} from {head_name}'s bio page "
                       f"({bio.get('url')}); the Wikipedia seasons table starts the run in {run[0]}, not used (#168)")
        return bio_year
    return coach_since(head_name, seasons, infobox)


def build_program_section(program, wiki, ath) -> dict:
    w = wiki["data"] if wiki else {}
    a = ath["data"] if ath else {}
    staff = a.get("staff", [])
    head = next((s for s in staff if s.get("isHeadCoach")), None)
    seasons = w.get("seasons", [])
    head_name = head["name"] if head else (re.sub(r"\(.*?\)", "", w.get("headCoach") or "").strip() or None)
    since = head_coach_first_season(program, head_name, seasons, w.get("headCoach"), a.get("headCoachBio"))
    wins = sum(s.get("wins") or 0 for s in seasons)
    losses = sum(s.get("losses") or 0 for s in seasons)
    ties = sum(s.get("ties") or 0 for s in seasons)
    coaches = [s for s in staff if s.get("isCoach")]
    support = [s for s in staff if not s.get("isCoach")]
    titles, unsourced_titles = national_titles(program, w.get("nationalTitles", []))
    return {
        "headCoach": {"name": head_name, "title": head["title"] if head else None,
                      "since": since, "seasons": (CURRENT_SEASON_FALLBACK - since + 1) if since else None,
                      "bioUrl": head["bioUrl"] if head else None, "social": head.get("social", {}) if head else {}},
        "coaches": coaches,
        "supportStaff": support,
        "stadium": w.get("stadium"),
        "founded": w.get("founded"),
        "nationalTitles": titles,
        # only when there is something to report, so a program with nothing unsourced publishes exactly
        # the profile it published before this key existed (issue #113)
        **({"unsourcedTitleClaims": unsourced_titles} if unsourced_titles else {}),
        "nationalRunnerUp": w.get("nationalRunnerUp", []),
        "collegeCups": w.get("collegeCups", []),
        "ncaaAppearances": w.get("ncaaAppearances", []),
        "confRegularSeasonTitles": w.get("confRegularSeasonTitles", []),
        "confTournamentTitles": w.get("confTournamentTitles", []),
        "allTimeRecord": {"wins": wins, "losses": losses, "ties": ties,
                          "winPct": round((wins + 0.5 * ties) / (wins + losses + ties), 3) if (wins + losses + ties) else None,
                          "seasons": len(seasons)},
        "_meta": {"wikipedia": _meta(wiki, w.get("pageUrl")), "athletics": _meta(ath)},
    }


def _record_from_games(games: list[dict]) -> dict:
    real = [g for g in games if not g.get("exhibition")]
    w = sum(1 for g in real if g.get("result") == "W")
    l = sum(1 for g in real if g.get("result") == "L")
    t = sum(1 for g in real if g.get("result") == "T")
    conf = [g for g in real if g.get("conferenceGame")]
    cw = sum(1 for g in conf if g.get("result") == "W")
    cl = sum(1 for g in conf if g.get("result") == "L")
    ct = sum(1 for g in conf if g.get("result") == "T")
    return {"wins": w, "losses": l, "ties": t, "text": f"{w}-{l}-{t}", "played": w + l + t, "scheduled": len(real),
            "confText": f"{cw}-{cl}-{ct}" if conf else None, "exhibitions": len(games) - len(real)}


def build_seasons(program, wiki, ath, rpi_hist, rpi_finals, registry) -> list[dict]:
    """Every season this program has a record of, newest first.

    The RPI tables create rows, they do not only decorate them: 173 of 350 programs have no
    Wikipedia season table and no schedule history, and the RPI archive is the only record their
    seasons ever had (issue #3). Both joins are exact matches on the curated ids and nothing else -
    no shortName fallback, no normalisation - because a near-match here does not lose a season, it
    publishes another school's one. Wikipedia and the athletics schedule stay authoritative for
    record, headCoach, confRecord, confFinish and ncaaResult.
    """
    ids = program["ids"]
    hist_name = ids.get("rpiHistoryName")
    ncaa_name = ids.get("ncaaName")
    seasons = {s["year"]: dict(s) for s in ((wiki or {}).get("data", {}).get("seasons") or [])}
    cur_season = registry["season"]["current"]
    a = (ath or {}).get("data", {})
    # Current season from the live schedule (Wikipedia lags).
    sched = a.get("schedule") or {}
    if sched.get("games"):
        yr = sched.get("season") or cur_season
        rec = _record_from_games(sched["games"])
        s = seasons.setdefault(yr, {"year": yr, "label": str(yr)})
        s.update({"record": rec["text"], "wins": rec["wins"], "losses": rec["losses"], "ties": rec["ties"],
                  "inProgress": rec["played"] < rec["scheduled"], "gamesPlayed": rec["played"]})
        if rec.get("confText") and rec["confText"] != "0-0-0" and not s.get("confRecord"):
            s["confRecord"] = rec["confText"]
        if not s.get("headCoach"):
            head = next((st["name"] for st in a.get("staff", []) if st.get("isHeadCoach")), None)
            s["headCoach"] = head
    # Prior seasons' schedules give conference-record-free but reliable records too.
    for y, games in (a.get("scheduleHistory") or {}).items():
        s = seasons.setdefault(int(y), {"year": int(y), "label": y})
        if not s.get("record"):
            rec = _record_from_games(games)
            s.update({"record": rec["text"], "wins": rec["wins"], "losses": rec["losses"], "ties": rec["ties"]})
            if rec.get("confText") and rec["confText"] != "0-0-0" and not s.get("confRecord"):
                s["confRecord"] = rec["confText"]
    # Chris Thomas's archive (from 2010 restated as if the No Overtime rule and the 2024 formula had applied).
    from_archive = set()
    for y, table in (rpi_hist.items() if hist_name else ()):
        h = table.get(hist_name)
        if not h:
            continue
        from_archive.add(y)
        s = seasons.setdefault(y, {"year": y, "label": str(y)})
        s["rpiRank"] = h.get("rpiRank")
        s["rpi"] = {"rank": h.get("rpiRank"), "sosRank": h.get("sosRank"), "balancedRank": h.get("balancedRpiRank"),
                    "kpiRank": h.get("kpiRank"), "masseyRank": h.get("masseyRank"), "ncaaSeed": h.get("ncaaSeed"),
                    "source": "end-of-season (Chris Thomas archive)"}
    # The NCAA's own table (see load_rpi_finals). Where the archive already ranked this program's
    # season the archive's rank stands, but the row is still read for the record: archive rows
    # carry none, so skipping the season outright would blank lastSeason for the 177 programs that
    # have no other source for it, the moment someone adds that year's archive sheet.
    for y, doc in (rpi_finals.items() if ncaa_name else ()):
        row = next((t for t in doc.get("teams") or [] if t.get("school") == ncaa_name), None)
        if not row:
            continue
        s = seasons.setdefault(y, {"year": y, "label": str(y)})
        if y not in from_archive:
            s["rpiRank"] = row["rank"]
            s["rpi"] = {"rank": row["rank"], "record": row.get("record"), "through": doc.get("throughGames"),
                        "prevRank": row.get("prevRank"), "source": "NCAA.com weekly RPI",
                        "weekly": rpi_weekly_for(ncaa_name, y)}
        # not setdefault: a Wikipedia row can carry the key with a null in it (miami-fl 2023-2025).
        if not s.get("record"):
            s["record"] = row.get("record")
        if y == cur_season:
            s.setdefault("inProgress", True)  # a real schedule, where there is one, has the last word
    return [seasons[y] for y in sorted(seasons, reverse=True)]


def build_club_lookup(tds, sw) -> dict[str, dict]:
    """norm name -> {club, source} from every commitment record we hold for this program,
    including past classes (SoccerWire returns alumni profiles too)."""
    out = {}
    for r in ((sw or {}).get("data", {}).get("allRecords") or []):
        if r.get("club"):
            out[common.norm_name(r["name"])] = {"club": r["club"], "source": "SoccerWire"}
    for r in ((tds or {}).get("data", {}).get("records") or {}).values():
        if r.get("club"):
            out[common.norm_name(r["name"])] = {"club": r["club"], "source": "TopDrawerSoccer"}
    return out


def publishing_run() -> bool:
    """True when this build writes to public/data, false when a test redirected it elsewhere.

    Only a publishing run may rewrite data/clubs-review.json: that file lives outside the output
    directories a scratch build swaps, so without this a test run would overwrite the repository's
    copy on its way past."""
    return os.path.abspath(common.PROGRAMS_OUT_DIR) == _PUBLISHED_PROGRAMS_DIR


def club_candidates(tds, sw) -> dict[str, list[dict]]:
    """norm name -> every club string we hold for that person, with the date its source speaks for.

    Unlike `build_club_lookup`, which keeps one winner per person, this keeps them all, because
    `clubs.resolve` has to see a disagreement to settle it by date (issue #228). Dates:

      * SoccerWire publishes a profile-modified date; failing that the profile's created date, and
        failing both the day we last saw the record;
      * TopDrawerSoccer publishes no date of its own, so the day we last saw the record is used.
    """
    out: dict[str, list[dict]] = defaultdict(list)
    for r in ((sw or {}).get("data", {}).get("allRecords") or []):
        if r.get("club"):
            out[common.norm_name(r["name"])].append(
                {"raw": r["club"], "source": "SoccerWire",
                 "updated": r.get("profileModified") or r.get("profileCreated") or r.get("lastSeen")})
    for r in ((tds or {}).get("data", {}).get("records") or {}).values():
        if r.get("club"):
            out[common.norm_name(r["name"])].append(
                {"raw": r["club"], "source": "TopDrawerSoccer", "updated": r.get("lastSeen") or r.get("firstSeen")})
    return out


def annotate_roster_clubs(roster: dict | None, ath, tds, sw, table=None) -> None:
    """Give every current-roster player a `clubInfo` (raw string, cleaned key, canonical id when the
    reviewed table knows it, status) and let the most recent source win, per issue #228.

    The roster page's own Club column is dated with the start of its season, not with the day we
    fetched it: see `clubs.season_date`."""
    if not roster:
        return
    table = table or clubs.load_table()
    cands = club_candidates(tds, sw)
    stored = ((ath or {}).get("data", {}).get("roster") or {}).get("players") or []
    column = {common.norm_name(p["name"]): (p.get("club") or "").strip() for p in stored}
    season_date = clubs.season_date(roster.get("season"))
    for q in roster["players"]:
        key = common.norm_name(q["name"])
        found = cands.get(key)
        if not found:
            found = next((v for n, v in cands.items() if same_person(n, q["name"])), [])
        rows = list(found)
        if column.get(key):
            rows.append({"raw": column[key], "source": "roster page", "updated": season_date})
        clubs.annotate(q, rows, table)


def observe_clubs(recorder, ath, tds, sw, *, slug: str, division: str) -> None:
    """Count every club string this program holds into the review report, matched or not.

    SoccerWire's `allRecords` is what the roster join reads, and it contains its `records`, so only
    `allRecords` is counted here - counting both would double every current recruit."""
    if recorder is None:
        return
    data = (ath or {}).get("data") or {}
    seasons = [("roster page", ((data.get("roster") or {}).get("players")) or [])]
    seasons += [("roster page (past season)", pl or []) for pl in (data.get("rosterHistory") or {}).values()]
    for source, players in seasons:
        for p in players:
            recorder.observe(p.get("club"), source=source, division=division, slug=slug)
    for r in ((tds or {}).get("data", {}).get("records") or {}).values():
        recorder.observe(r.get("club"), source="TopDrawerSoccer", division=division, slug=slug)
    for r in ((sw or {}).get("data", {}).get("allRecords") or []):
        recorder.observe(r.get("club"), source="SoccerWire", division=division, slug=slug)


def annotate_roster_schools(roster: dict | None, *, division: str, table=None, recorder=None) -> None:
    """Give every current-roster player a `schoolInfo`: the raw high-school string, its cleaned key,
    the NCES school id when exactly one school in the hometown's state carries that name, and the
    status (matched / unmatched / ambiguous / outside-us), per issue #229. Never without the state.

    D1 only for now (the owner's decision 7 on #225: D1 first, then D2 on the same model). A D2
    roster is left as it is - no `schoolInfo` - rather than annotated and not counted."""
    if not roster or division != "D1":
        return
    table = table or schools.load_table()
    for q in roster["players"]:
        m = table.match(q.get("highSchool"), q.get("hometown"))
        q["schoolInfo"] = None if m.status == "none" else m.as_dict()
        if recorder is not None:
            recorder.observe(q, m, slug=roster.get("_slug"))


def build_roster(ath, club_lookup: dict | None = None) -> tuple[dict | None, dict]:
    a = (ath or {}).get("data") or {}
    roster = a.get("roster")
    if not roster:
        return None, {}
    players = []
    matrix = {p: {c: 0 for c in CLASS_ORDER} for p in POS_ORDER}
    for p in roster["players"]:
        q = dict(p)
        secs = (q.get("bio") or {}).get("sections") or {}
        q["bio"] = {k: (v[:1500] + "…" if len(v) > 1500 else v) for k, v in secs.items()}
        # Club: recruiting databases are far more reliable than the roster page's own Club column.
        known = club_lookup.get(common.norm_name(q["name"])) if club_lookup else None
        if not known and club_lookup:
            known = next((v for n, v in club_lookup.items() if same_person(n, q["name"])), None)
        if known:
            q["club"], q["clubSource"] = known["club"], known["source"]
        elif q.get("club"):
            # This value always came from the roster table's own Club column, never from a bio
            # page: the refresh runs --no-bios and no stored roster row carries a `bio` key with a
            # club field. Mislabelling it "bio text (unverified)" is issue #227's bug 2.
            q["clubSource"] = "roster page"
        else:
            q["clubSource"] = None
        players.append(q)
        pos = (q.get("pos") or "").split("/")[0]
        cls = q.get("classCode") or ""
        if pos in matrix and cls in matrix[pos]:
            matrix[pos][cls] += 1
    graduating = defaultdict(int)
    for p in players:
        if p.get("classCode") in GRADUATING:
            graduating[(p.get("pos") or "?").split("/")[0]] += 1
    by_class = defaultdict(int)
    for p in players:
        by_class[p.get("classCode") or "?"] += 1
    hist = {}
    cur_names = {common.norm_name(p["name"]) for p in players}
    for y, plist in (a.get("rosterHistory") or {}).items():
        names = {common.norm_name(p["name"]) for p in plist}
        hist[y] = {"count": len(plist),
                   "players": [{k: p.get(k) for k in ("number", "name", "pos", "classCode", "hometown", "highSchool")} for p in plist],
                   "departed": sorted(n for n in names - cur_names) if int(y) == roster["season"] - 1 else None}
    return ({"season": roster["season"], "count": len(players), "players": players,
             "byPosClass": matrix, "byClass": dict(by_class), "graduatingByPos": dict(graduating),
             "_meta": _meta(ath)}, hist)


def build_schedule(ath) -> dict | None:
    a = (ath or {}).get("data") or {}
    s = a.get("schedule")
    if not s:
        return None
    rec = _record_from_games(s["games"])
    hist = {y: {"record": _record_from_games(g)["text"], "games": g} for y, g in (a.get("scheduleHistory") or {}).items()}
    return {"season": s.get("season"), "record": rec, "games": s["games"], "history": hist,
            "_meta": _meta(ath, (ath or {}).get("scheduleUrl"))}


# ---------- camps ----------

_TRACKING_PARAM = re.compile(r"^(utm_|fbclid$|gclid$|mc_cid$|mc_eid$)", re.I)


def registration_key(url) -> str | None:
    """A registration link reduced to what identifies the registration (issue #74): scheme, a leading "www."
    and letter case in the host, a trailing slash, the fragment, query-parameter order and tracking parameters
    do not make two links different; the path and every other parameter (Ryzer's `id`, `sport`) do.
    None for anything that is not an http(s) URL."""
    if not isinstance(url, str) or not url.strip():
        return None
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    host = parts.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    query = sorted((k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING_PARAM.match(k))
    return f"{host}{parts.path.rstrip('/')}?{urllib.parse.urlencode(query)}"


def camp_source(item: dict) -> dict:
    """Where one camp entry came from, kept on the merged entry so a camp found in two places keeps both."""
    src = {"kind": item.get("kind"), "name": item.get("name"), "sourceUrl": item.get("sourceUrl")}
    for k in ("newsTitle", "newsUrl", "newsDate"):
        if item.get(k):
            src[k] = item[k]
    return src


def build_camps(camps, news, curated) -> dict | None:
    """ID camps section: the camp page (link, host, vendor, robots state) plus one merged list of
    entries with `kind`: "camp" (extracted from the camp page), "news" (announced in a news
    release), "curated" (hand-written curated.camps[]). Dated entries first by start date, undated
    last; a news entry that repeats a camp-page entry (same start date, same name) is dropped, and entries
    from different sources with the same start date and the same registration link are merged into one
    that lists every source in `sources` (issue #74).
    `upcoming` is not computed here: the site is static, so the UI splits on today's date.

    Every entry also carries `campType`: "id", "youth" or "unknown" (issue #78). It is a LABEL, not
    a filter - nothing is dropped for carrying it, and this section, which is what the program page
    renders, keeps showing youth camps exactly as before. Only the site-wide camp view filters on
    it, because the owner's rule for that view is women's soccer ID and prospect camps only. A youth
    camp at a program is correct data; deleting it to sharpen one view would damage the page a
    family actually lands on."""
    if not camps and not (curated.get("camps") or []):
        return None
    c = (camps or {}).get("data") or {}
    items = []
    for e in c.get("camps") or []:
        items.append({**e, "kind": "camp"})
    # Source order is precedence (issue #74): camp page, then curated (hand-entered), then news. Whichever of two
    # duplicates comes first here is the entry kept, so a curated entry wins over a news release about it.
    for e in curated.get("camps") or []:
        if isinstance(e, dict) and e.get("name"):
            sd = e.get("startDate")
            items.append({"startDate": None, "endDate": None, "dateText": None,
                          "precision": ("month" if len(sd) == 7 else "day") if isinstance(sd, str) and sd else None,
                          "yearInferred": False, "location": None, "ages": None, "price": None, "registerUrl": None,
                          "sourceUrl": None, "confidence": "curated", **e, "kind": "curated"})
    for e in c.get("newsCamps") or []:
        items.append({**e, "kind": "news"})
    seen, merged = set(), []
    by_registration: dict[tuple[str, str], dict] = {}
    for it in items:
        key = (it.get("startDate"), re.sub(r"\W+", "", (it.get("name") or "").lower())[:40])
        if it.get("startDate") and key in seen:
            continue
        # Issue #74: the same camp announced on the camp page AND in a news release arrives twice, under two
        # names ("Soccer ID Clinic | October 3rd" / "WOMEN'S SOCCER TO HOLD ID CLINIC", le-moyne). Two entries
        # from different sources with the same start date and the same registration link are one camp: the
        # first (camp page, then curated, then news - the order `items` is built in) is kept, and the other's
        # source is recorded on it. A name alone never merges, and neither does a date alone: two camps on one
        # day with different registration links stay two camps.
        reg = registration_key(it.get("registerUrl"))
        rkey = (it.get("startDate"), reg) if it.get("startDate") and reg else None
        kept = by_registration.get(rkey) if rkey else None
        if kept is not None and kept["kind"] != it["kind"]:
            kept["sources"].append(camp_source(it))
            continue
        seen.add(key)
        entry = {**it, "campType": classify_camp(it.get("name")), "sources": [camp_source(it)]}
        merged.append(entry)
        if rkey and rkey not in by_registration:  # the FIRST entry with this date and link is the one a later source merges into
            by_registration[rkey] = entry
    merged.sort(key=lambda it: (it.get("startDate") is None, it.get("startDate") or "", it.get("name") or ""))
    metas = [_meta(camps)] if camps else []
    if news and any(it["kind"] == "news" for it in merged):
        metas.append(_meta(news))
    return {"url": c.get("campsUrl"), "hubUrl": c.get("hubUrl"), "finalUrl": c.get("finalUrl"), "host": c.get("host"),
            "vendor": c.get("vendor"), "pageTitle": c.get("pageTitle"), "discoveredVia": c.get("discoveredVia"),
            "robotsBlocked": bool(c.get("robotsBlocked")), "fetchError": c.get("fetchError"),
            "parsed": c.get("parsed"),  # False: the page was fetched but is not HTML (PDF, empty); None: older camps.json
            "newsScanned": c.get("newsScanned", 0), "items": merged, "_meta": metas}


# ---------- camps index ----------
# public/data/camps/index.json: every program's camp items in one file, so a site-wide camp view
# does not have to load 350 profiles. Rows carry the camp fields plus `slug` and nothing else -
# program name, region, conference and colours are already on the programs index row the view holds,
# and are joined by slug there.
#
# Whether a row is a real women's soccer camp, another sport's camp or a review widget is decided at
# source in collect/camps.py, where the page structure that proves it is still available (issues #39
# and #80); by the time a row reaches here that evidence is gone. The emitter applies the date
# window, and carries the id/youth/unknown label the collector's classifier produced.
#
# CAMP_INDEX_FIELDS is an ALLOW-LIST: a per-item field that is not named here never reaches the
# published file, and until #78 nothing said so. `campType` is the field that made that hazard real
# (#69), so check_camps_index now reports an item field that is neither published nor listed as
# deliberately withheld - see CAMP_ITEM_UNPUBLISHED.
CAMP_INDEX_FIELDS = ("name", "startDate", "endDate", "dateText", "precision", "yearInferred",
                     "location", "ages", "price", "registerUrl", "sourceUrl", "kind", "campType",
                     "confidence")
# Per-item fields build_camps produces that the index deliberately does not carry. A news entry's
# provenance belongs on the profile, where the release can be linked in context; the camp view joins
# by slug and links `sourceUrl`. Listed rather than ignored so the guard below can tell "withheld on
# purpose" from "forgotten", which is the whole point of #69.
# `sources` (issue #74): every place a merged camp was found; the row's own sourceUrl and kind are the kept entry's.
CAMP_ITEM_UNPUBLISHED = ("newsTitle", "newsUrl", "newsDate", "sources")


def camps_window(today: dt.date | None = None) -> dict:
    """The slice of the camp calendar the published index carries: upcoming camps only.

    The owner's rule, 2026-09-14: "only show upcoming camps, drop the past year." So `from` is
    today, not today minus a year, and the 365-day constant that produced the old lower bound is
    gone rather than set to zero - a constant nothing varies is a knob that invites being turned
    back. Written into the file so a stale publish is diagnosable from the file alone.

    A camp that is running RIGHT NOW is upcoming, not past: camp_in_window compares on
    `endDate or startDate`, so a camp that began last week and ends tomorrow is still carried. Only
    a camp that has finished drops out.

    `to` is null because there is no upper bound - a camp announced for 2027 is published today -
    and the key is still emitted so the shape never varies."""
    return {"from": (today or dt.date.today()).isoformat(), "to": None}


def camp_in_window(item, window: dict) -> bool:
    """True when a camp item belongs in the published index.

    A row is placed by when it finishes, not by when it starts: the comparison is on
    `endDate or startDate`, so a camp that is running right now is not past. Month-precision rows
    compare at month granularity, everything else by day.

    This is close to, but not the same as, the profile tab's past/future rule (public/index.html,
    tabCamps), which compares a month-precision row on `startDate` alone. A month row running
    2026-08 to 2026-09 is therefore past to the tab and in-window here. The rule here is the
    deliberate one - a camp still running has not happened yet - and no row in today's corpus falls
    in the gap (one item of 250 is month-precision and it ends in the month it starts). Reconciling
    the tab is issue #65's second PR, which is where the difference would first become visible to a
    visitor; tests/camps_index_test.py pins the case so it cannot be silently "fixed" either way.

    An undated row is dropped: it cannot be placed in the window, and a date-ordered view has
    nowhere to put it. Anything malformed is dropped rather than raised - this reads a profile a
    hand-edit can have left any shape at all.
    """
    if not isinstance(item, dict) or not isinstance(window, dict):
        return False
    start = item.get("startDate")
    if not isinstance(start, str) or not start:
        return False
    end = item.get("endDate") if isinstance(item.get("endDate"), str) else None
    frm, to = window.get("from"), window.get("to")
    month = item.get("precision") == "month"
    last, first = ((end or start), start)
    if month:
        last, first = last[:7], first[:7]
    if isinstance(frm, str) and frm and last < (frm[:7] if month else frm):
        return False
    if isinstance(to, str) and to and first > (to[:7] if month else to):
        return False
    return True


def camp_row(slug: str, item: dict) -> dict:
    """One published row: the camp fields, in a fixed order, plus the slug that joins it to a
    program. Missing fields are published as null so the shape never varies between rows."""
    return {"slug": slug, **{k: item.get(k) for k in CAMP_INDEX_FIELDS}}


def camp_counts(rows: list) -> dict:
    """The published rows tallied by `campType`, with every class named even at zero.

    The camp view shows only `campType == "id"`, so it hides rows. This is what makes the number it
    hides derivable without running the view, and what makes classifier drift visible in the file
    itself: if the id share moves, this moves with it. Today's upcoming corpus is 34 id, 0 youth,
    3 unknown - and `youth: 0` is exactly the kind of fact that has to be stated rather than
    inferred from a missing key, because a class that stopped being produced would otherwise look
    identical to a class that legitimately has no rows this month.

    The classes are fixed, not derived from the rows, so a typo'd campType shows up as a `total`
    that does not equal the sum rather than as a fourth bucket nobody reads."""
    counted = {"id": 0, "youth": 0, "unknown": 0}
    for r in rows:
        t = r.get("campType") if isinstance(r, dict) else None
        if t in counted:
            counted[t] += 1
    return {"total": len(rows), **counted}


# ---------- commitments ----------

def commitment_club_date(rec: dict, kind: str) -> str | None:
    """The date a commitment record's club string speaks for; see `club_candidates`."""
    if kind == "soccerwire":
        return rec.get("profileModified") or rec.get("profileCreated") or rec.get("lastSeen")
    if kind == "tds":
        return rec.get("lastSeen") or rec.get("firstSeen")
    return rec.get("approvedAt") or rec.get("postedAt")


CLUB_SOURCE_NAMES = {"tds": "TopDrawerSoccer", "soccerwire": "SoccerWire"}


def resolve_commitments(program, tds, sw, reviewed, news, roster, registry, table=None) -> list[dict]:
    slug = program["slug"]
    table = table or clubs.load_table()
    tracked = set(registry["season"]["gradYears"])
    merged: list[dict] = []

    def find(name, gy):
        for c in merged:
            if c["gradYear"] == gy and (same_person(c["name"], name) or any(same_person(al, name) for al in c["aliases"])):
                return c
        return None

    def add(rec: dict, source: dict, *, prefer: bool):
        gy = rec["gradYear"]
        if gy not in tracked:
            return
        c = find(rec["name"], gy)
        if c is None:
            c = {"id": record_key(rec["name"], gy), "name": rec["name"], "aliases": [], "gradYear": gy,
                 "pos": rec.get("pos") or "", "club": rec.get("club") or "", "state": rec.get("state") or "",
                 "city": rec.get("city") or "", "highSchool": rec.get("highSchool") or "",
                 "college": slug, "status": "verbal", "announced": None, "announcedSource": None,
                 "firstSeen": None, "sources": [], "flags": []}
            merged.append(c)
        else:
            if common.norm_name(rec["name"]) != common.norm_name(c["name"]) and rec["name"] not in c["aliases"]:
                c["aliases"].append(rec["name"])
                if "name-variant" not in c["flags"]:
                    c["flags"].append("name-variant")
            if prefer and rec["name"] != c["name"]:
                c["aliases"].append(c["name"])
                c["name"] = rec["name"]
                c["id"] = record_key(rec["name"], gy)
        for k in ("pos", "club", "state", "city", "highSchool"):
            v = rec.get(k) or ""
            if v and (prefer or not c[k]):
                c[k] = v
        c["sources"].append(source)
        if rec.get("club"):
            # kept per source, not collapsed: clubs.resolve settles a disagreement by date (#228)
            c.setdefault("_clubCandidates", []).append(
                {"raw": rec["club"], "source": CLUB_SOURCE_NAMES.get(source["kind"], source["kind"]),
                 "updated": commitment_club_date(rec, source["kind"])})
        fs = source.get("firstSeen")
        if fs and (c["firstSeen"] is None or fs < c["firstSeen"]):
            c["firstSeen"] = fs

    ids = program["ids"]
    tds_url = (registry["sources"]["tds"]["teamCommitments"].format(tdsSlug=ids["tdsSlug"], tdsClgId=ids["tdsClgId"])
               if ids.get("tdsClgId") and ids.get("tdsSlug") else None)
    for key, r in ((tds or {}).get("data", {}).get("records") or {}).items():
        add(r, {"kind": "tds", "url": r.get("playerUrl") or tds_url, "listUrl": tds_url,
                "firstSeen": r.get("firstSeen"), "lastSeen": r.get("lastSeen"), "missingSince": r.get("missingSince")}, prefer=True)
    for key, r in ((sw or {}).get("data", {}).get("records") or {}).items():
        if not r.get("isCommitted", True):
            continue
        add(r, {"kind": "soccerwire", "url": r.get("playerUrl"), "firstSeen": r.get("firstSeen"),
                "lastSeen": r.get("lastSeen"), "missingSince": r.get("missingSince"),
                "profileCreated": r.get("profileCreated")}, prefer=False)
    for r in (reviewed or {}).get("approved", []):
        src = {"kind": r.get("sourceKind", "social"), "url": r.get("sourceUrl"), "postedAt": r.get("postedAt"),
               "approvedAt": r.get("approvedAt"), "note": r.get("note")}
        add(r, src, prefer=False)

    # manual merges: [{"from": "<id>", "into": "<id>"}]
    for m in (reviewed or {}).get("merges", []):
        a = next((c for c in merged if c["id"] == m.get("from")), None)
        b = next((c for c in merged if c["id"] == m.get("into")), None)
        if a and b and a is not b:
            b["aliases"].append(a["name"])
            b["sources"].extend(a["sources"])
            for k in ("pos", "club", "state", "city", "highSchool"):
                b[k] = b[k] or a[k]
            b.setdefault("_clubCandidates", []).extend(a.get("_clubCandidates") or [])
            merged.remove(a)

    # One club per recruit, from every source that named one: they agree, or the most recently
    # updated source wins (issue #228). `clubInfo` carries the raw string and, where the reviewed
    # table knows it, the canonical club.
    for c in merged:
        clubs.annotate(c, c.pop("_clubCandidates", []), table)

    roster_names = [p["name"] for p in (roster or {}).get("players", [])]
    recruiting_news = ((news or {}).get("data", {}).get("recruitingItems") or [])
    overrides = (reviewed or {}).get("statusOverrides", {})
    for c in merged:
        kinds = {s["kind"] for s in c["sources"]}
        # announced: only dates that really mark the announcement (dated social post you approved,
        # press release). SoccerWire profile dates and our own first-seen dates are approximations
        # kept separately so the UI can label them honestly.
        dated, approx = [], []
        for s in c["sources"]:
            if s.get("postedAt") and s["kind"] not in ("tds", "soccerwire"):
                dated.append((s["postedAt"], s["kind"]))
            if s.get("profileCreated"):
                approx.append((s["profileCreated"], "SoccerWire profile created"))
        for n in recruiting_news:
            if any(w in common.norm_name(n["title"]) for w in [common.norm_name(c["name"])] if w):
                c["sources"].append({"kind": "press_release", "url": n["url"], "postedAt": n.get("date"), "title": n["title"]})
                kinds.add("press_release")
                if n.get("date"):
                    dated.append((n["date"], "press_release"))
        if c.get("firstSeen"):
            approx.append((c["firstSeen"], "first seen by CollegeDash"))
        if dated:
            dated.sort()
            c["announced"], c["announcedSource"] = dated[0]
        c["approxDate"] = None
        if approx:
            approx.sort()
            # profile-created beats first-seen when both exist; prefer the earliest plausible one
            c["approxDate"] = {"date": approx[0][0], "basis": approx[0][1]}
        # status
        if any(same_person(c["name"], rn) or any(same_person(al, rn) for al in c["aliases"]) for rn in roster_names):
            c["status"] = "enrolled"
        elif "press_release" in kinds:
            c["status"] = "signed"
        if all(s.get("missingSince") for s in c["sources"] if s["kind"] in ("tds", "soccerwire")) and \
                any(s["kind"] in ("tds", "soccerwire") for s in c["sources"]) and c["status"] != "enrolled":
            c["flags"].append("possibly-decommitted")
        if c["id"] in overrides:
            c["status"] = overrides[c["id"]]
        independent = {k for k in kinds if k != "soccerwire_profile"}
        c["confidence"] = "confirmed" if (len(independent) >= 2 or "press_release" in kinds or c["status"] == "enrolled") else "single-source"
        c["sourceKinds"] = sorted(kinds)
    merged.sort(key=lambda c: (c["gradYear"], common.norm_name(c["name"])))
    return merged


# ---------- academic rank ----------
# Times Higher Education's "Best universities in the United States" table, captured once and
# committed as data/the-us-rankings-2026.json with a hand-reviewed slug -> row alias table beside it
# (data/the-rank-aliases.json, derived through Wikidata's IPEDS property by tools/the_rank_derive.py,
# never by name similarity). Nothing here fetches anything: refreshing the ranking is a deliberate
# annual act, tools/the_rank_check.py --refetch, which shows its diff to a person first.

THE_ASSET_PATH = os.path.join(common.DATA_DIR, "the-us-rankings-2026.json")
THE_ALIAS_PATH = os.path.join(common.DATA_DIR, "the-rank-aliases.json")
THE_SOURCE = "Times Higher Education"


def load_academic_ranks(registry: dict) -> dict[str, dict]:
    """slug -> the profile's academicRank block, for every onboarded program.

    Raises rather than degrading. 224 of the 350 programs are genuinely unranked and publish
    `rank: null`; if a missing asset produced nulls as well, losing the feature would look exactly
    like the data it is meant to carry, on every card at once. A missing rank and a missing ranking
    must not render the same.
    """
    asset = common.read_json(THE_ASSET_PATH)
    table = common.read_json(THE_ALIAS_PATH)
    if not asset or not asset.get("rows"):
        raise FileNotFoundError(f"academic rank: missing or empty ranking asset {THE_ASSET_PATH}")
    if not table or not table.get("aliases"):
        raise FileNotFoundError(f"academic rank: missing or empty alias table {THE_ALIAS_PATH}")

    rows = {r["theSlug"]: r for r in asset["rows"] if r.get("theSlug")}
    meta = {"year": asset.get("rankYear"), "label": asset.get("rankLabel"), "source": THE_SOURCE,
            "sourceUrl": asset.get("sourceUrl"), "asOf": asset.get("fetchedAt")}
    aliases, claimed, out = table["aliases"], {}, {}
    for program in published_programs(registry):
        slug = program["slug"]
        a = aliases.get(slug)
        if a is None:
            out[slug] = {"rank": None, "tied": False, "theSlug": None, **meta}
            continue
        row = rows.get(a.get("theSlug"))
        if row is None:
            raise ValueError(f"academic rank: {slug} claims theSlug {a.get('theSlug')!r}, which is not "
                             f"in {os.path.basename(THE_ASSET_PATH)}; run tools/the_rank_check.py")
        if a["theSlug"] in claimed:
            raise ValueError(f"academic rank: asset row {a['theSlug']!r} is claimed by both "
                             f"{claimed[a['theSlug']]} and {slug}; run tools/the_rank_check.py")
        claimed[a["theSlug"]] = slug
        out[slug] = {"rank": row["usRank"], "tied": bool(row.get("tied")), "theSlug": row["theSlug"], **meta}
    return out


# ---------- profile ----------

def build_profile(program: dict, registry: dict, rpi_hist, rpi_finals, state: dict | None = None,
                  ranks: dict[str, dict] | None = None, club_table=None, club_recorder=None,
                  school_table=None, school_recorder=None) -> dict:
    slug = program["slug"]
    if ranks is None:
        ranks = load_academic_ranks(registry)
    club_table = club_table or clubs.load_table()
    school_table = school_table or schools.load_table()
    S = lambda n: common.load_source(slug, n)
    scorecard, climate, wiki, ath = S("scorecard"), S("climate"), S("wikipedia"), S("athletics")
    tds, sw, news, camps = S("commitments.tds"), S("commitments.soccerwire"), S("news"), S("camps")
    curated = common.load_curated(slug)
    reviewed = common.load_reviewed(slug)

    roster, roster_hist = build_roster(ath, build_club_lookup(tds, sw))
    annotate_roster_clubs(roster, ath, tds, sw, club_table)
    observe_clubs(club_recorder, ath, tds, sw, slug=slug, division=program.get("division", "D1"))
    if roster:
        roster["_slug"] = slug  # for the review report's per-program count; dropped below
    annotate_roster_schools(roster, division=program.get("division", "D1"), table=school_table,
                            recorder=school_recorder)
    if roster:
        roster.pop("_slug", None)
    a = program["athletics"]
    profile = {
        "slug": slug, "name": program["name"], "shortName": program.get("shortName"), "nickname": program.get("nickname"),
        "division": program.get("division", "D1"), "conference": program.get("conference"),
        "colors": program.get("colors"), "ids": program.get("ids", {}), "social": program.get("social", {}),
        "links": {
            "athletics": a["baseUrl"] + a["sportPath"], "roster": a["baseUrl"] + a["sportPath"] + "/roster",
            "schedule": a["baseUrl"] + a["sportPath"] + "/schedule", "news": a["baseUrl"] + a["sportPath"] + "/news",
            "camps": ((camps or {}).get("data") or {}).get("finalUrl") or ((camps or {}).get("data") or {}).get("campsUrl"),
            "tds": (registry["sources"]["tds"]["team"].format(tdsSlug=program["ids"]["tdsSlug"], tdsClgId=program["ids"]["tdsClgId"])
                    if program["ids"].get("tdsClgId") and program["ids"].get("tdsSlug") else None),
            "wikipedia": (wiki or {}).get("data", {}).get("pageUrl"),
            "x": f"https://x.com/{program['social']['x']}" if program.get("social", {}).get("x") else None,
            "instagram": f"https://www.instagram.com/{program['social']['instagram']}/" if program.get("social", {}).get("instagram") else None,
        },
        "school": ({**scorecard["data"], "region": region_for(scorecard["data"].get("state")), "_meta": _meta(scorecard)} if scorecard else None),
        "academicRank": ranks[slug],
        "climate": ({**climate["data"], "_meta": _meta(climate)} if climate else None),
        "program": build_program_section(program, wiki, ath),
        "seasons": build_seasons(program, wiki, ath, rpi_hist, rpi_finals, registry),
        "roster": roster,
        "rosterHistory": roster_hist,
        "schedule": build_schedule(ath),
        "commitments": resolve_commitments(program, tds, sw, reviewed, news, roster, registry, club_table),
        "news": ({"recruiting": (news["data"].get("recruitingItems") or [])[:25], "latest": (news["data"].get("items") or [])[:12],
                  "_meta": _meta(news)} if news else None),
        "camps": build_camps(camps, news, curated),
        "curated": {k: v for k, v in curated.items() if not k.startswith("_") and k != "overrides"},
    }
    # curated overrides: {"program": {"headCoach": {"since": 2003}}, "school": {...}}
    for section, patch in (curated.get("overrides") or {}).items():
        if isinstance(profile.get(section), dict) and isinstance(patch, dict):
            _deep_update(profile[section], patch)

    commits_by_year = defaultdict(int)
    for c in profile["commitments"]:
        commits_by_year[str(c["gradYear"])] += 1
    profile["commitmentsByYear"] = dict(sorted(commits_by_year.items()))
    envs = {"athletics": ath, "tds": tds, "soccerwire": sw, "news": news, "scorecard": scorecard,
            "climate": climate, "wikipedia": wiki, "camps": camps}
    profile["_build"] = _build_meta(profile, envs, collector_outcomes(slug, state or {}))
    return profile


def collector_outcomes(slug: str, state: dict) -> tuple[list[dict], list[dict]]:
    """(failed, skipped) collector runs for this program from public/archive/refresh-state.json,
    where run_collector records {ok, error|skipped, at} under '<slug>.<collector>'."""
    failed, skipped = [], []
    for key, entry in state.items():
        if not isinstance(entry, dict) or not key.startswith(slug + "."):
            continue
        collector = key[len(slug) + 1:]
        if "." in collector:
            continue
        if entry.get("ok") is False:
            failed.append({"collector": collector, "error": common.redact(entry.get("error", ""))[:300], "at": entry.get("at")})
        elif entry.get("skipped"):
            skipped.append({"collector": collector, "reason": common.redact(entry["skipped"])[:300], "at": entry.get("at")})
    failed.sort(key=lambda f: f["collector"])
    skipped.sort(key=lambda f: f["collector"])
    return failed, skipped


def _deep_update(dst: dict, patch: dict):
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_update(dst[k], v)
        else:
            dst[k] = v


def _build_meta(profile: dict, envs: dict, outcomes: tuple[list, list] = ([], [])) -> dict:
    checks = {
        "school": bool(profile.get("school")),
        "climate": bool(profile.get("climate")),
        "program": bool(profile["program"].get("headCoach", {}).get("name")),
        "seasons": bool(profile.get("seasons")),
        "rpi": any(s.get("rpiRank") for s in profile.get("seasons", [])),
        "roster": bool(profile.get("roster")),
        "schedule": bool(profile.get("schedule")),
        "commitments": bool(profile.get("commitments")),
        "news": bool(profile.get("news")),
    }  # hand-written curated fields are optional and do not count
    thresholds = {"athletics": 14, "tds": 3, "soccerwire": 3, "news": 7, "scorecard": 120, "climate": 400, "wikipedia": 45,
                  "camps": 45}
    failed, skipped = outcomes
    skipped_names = {s["collector"] for s in skipped}
    stale = []
    for k, env in envs.items():
        age = _age_days((env or {}).get("fetchedAt"))
        if env is None:
            if k not in skipped_names and k not in OPTIONAL_ENVS:  # a deliberate skip (no article, no TDS id) is not staleness
                stale.append(f"{k}: never collected")
        elif age is not None and age > thresholds.get(k, 30):
            stale.append(f"{k}: {age:.0f}d old")
    return {"builtAt": common.now_iso(), "completeness": round(sum(checks.values()) / len(checks), 2),
            "sections": checks, "stale": stale, "failed": failed, "skipped": skipped}


def search_names(p: dict) -> list[str]:
    """Names people might type for this school, for the dashboard search: short name, full name,
    NCAA and RPI-archive names ('ULM', 'CalStateFullerton' -> 'Cal State Fullerton'), initials of a
    3+ word short name ('UC Santa Barbara' -> 'UCSB'), initials of the full name when it is just the
    short name plus a dropped 'University'/'College' ('Grand Valley State University' -> 'GVSU', even
    though shortName's own initials are 'GVS'), and St./Saint swaps. De-duplicated, in order."""
    ids = p.get("ids") or {}
    raw = [p.get("shortName"), p.get("name"), ids.get("ncaaName"), ids.get("rpiHistoryName")]
    out: list[str] = []

    def add(s):
        s = common.clean(s or "")
        s = re.sub(r"\s*\([^)]*\)", "", s)  # 'Miami (FL)' -> 'Miami'
        if s and s.lower() not in {o.lower() for o in out}:
            out.append(s)

    for s in raw:
        if not s:
            continue
        if " " not in s and re.search(r"[a-z][A-Z]", s):  # CamelCase archive names
            s = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
        add(s)
    short = p.get("shortName") or ""
    words = short.split()
    if len(words) >= 3:  # 'UC Santa Barbara' -> 'UCSB' (an all-caps word keeps all its letters)
        add("".join((w if w.isupper() and len(w) <= 4 else w[0]) for w in words if w[0].isalpha()))
    # A shortName built by dropping a trailing generic word ('Grand Valley State' from 'Grand Valley
    # State University') loses that word's letter from the initials above ('GVS', not 'GVSU'). When the
    # full name is exactly the shortName plus one or two purely generic trailing words, restore it -
    # gated tightly (the extra words must be nothing but 'University'/'College') so an unrelated long
    # name never contributes noise (issue #200: filling shortName must not cost an initials match that
    # worked off the long name before).
    name = p.get("name") or ""
    if short and name.lower().startswith(short.lower() + " "):
        extra = name[len(short):].split()
        if extra and len(extra) <= 2 and all(w.strip(",") in ("University", "College") for w in extra):
            full_words = words + extra
            if len(full_words) >= 3:
                add("".join((w if w.isupper() and len(w) <= 4 else w[0]) for w in full_words if w[0].isalpha()))
    for s in list(out):
        if re.search(r"\bSt\.?\s", s):
            add(re.sub(r"\bSt\.?\s", "Saint ", s))
        elif re.search(r"\bSaint\s", s):
            add(re.sub(r"\bSaint\s", "St ", s))
    return out


def summary_row(p: dict) -> dict:
    school = p.get("school") or {}
    rank = p.get("academicRank") or {}
    seasons = p.get("seasons") or []
    cur = next((s for s in seasons if s.get("inProgress")), None)
    last_final = next((s for s in seasons if not s.get("inProgress") and s.get("record")), None)
    return {
        "slug": p["slug"], "name": p["name"], "shortName": p.get("shortName"), "nickname": p.get("nickname"),
        "searchNames": search_names(p),
        "conference": p.get("conference"), "division": p.get("division"), "colors": p.get("colors"),
        "city": school.get("city"), "state": school.get("state"), "region": school.get("region"),
        "ownership": school.get("ownership"), "undergradEnrollment": school.get("undergradEnrollment"),
        "admissionRate": school.get("admissionRate"), "sat25": school.get("sat25"), "sat75": school.get("sat75"),
        "academicRank": rank.get("rank"), "academicRankTied": bool(rank.get("tied")),
        "tuitionInState": school.get("tuitionInState"), "tuitionOutOfState": school.get("tuitionOutOfState"),
        "headCoach": p["program"]["headCoach"].get("name"), "coachSince": p["program"]["headCoach"].get("since"),
        "nationalTitles": len(p["program"].get("nationalTitles") or []),
        "collegeCups": len(p["program"].get("collegeCups") or []),
        "currentSeason": ({"year": cur["year"], "record": cur.get("record"), "rpiRank": cur.get("rpiRank")} if cur else None),
        "lastSeason": ({"year": last_final["year"], "record": last_final.get("record"), "rpiRank": last_final.get("rpiRank"),
                        "ncaaResult": last_final.get("ncaaResult")} if last_final else None),
        "rpiHistory": [{"year": s["year"], "rank": s.get("rpiRank")} for s in seasons if s.get("rpiRank")],
        "rosterSize": (p.get("roster") or {}).get("count"),
        "commitmentsByYear": p.get("commitmentsByYear", {}),
        "fallClimate": (p.get("climate") or {}).get("fallSeason"),
        "completeness": p["_build"]["completeness"], "stale": p["_build"]["stale"], "builtAt": p["_build"]["builtAt"],
        "failed": [f["collector"] for f in p["_build"].get("failed", [])],
        "tags": (p.get("curated") or {}).get("tags", []),
    }


def build(registry: dict, *, allow_unexplained_prune: frozenset[str] = frozenset()) -> list[dict]:
    # The prune plan is decided before the first write, so a refused prune leaves the published tree untouched.
    published = [p for p in published_programs(registry)]
    prune_plan = plan_prune(registry, {p["slug"] for p in published}, common.PROGRAMS_OUT_DIR,
                            allow_unexplained=frozenset(allow_unexplained_prune))
    rpi_hist = load_rpi_history()
    # raises if no season table resolves, rather than blanking the latest season for all 350
    rpi_finals = load_rpi_finals(registry["season"]["current"])
    state = common.load_refresh_state()
    ranks = load_academic_ranks(registry)  # read once; raises if the committed asset is missing
    club_table = clubs.load_table(reload=True)  # reviewed data; a contradictory edit raises here
    club_recorder = clubs.Recorder(club_table)
    school_table = schools.load_table(reload=True)  # derived from NCES by tools/schools_nces.py; a bad file raises here
    school_recorder = schools.Recorder(school_table)
    trends_recorder = trends.Recorder(club_table, candidates=club_candidates, same_person=same_person)  # issue #230
    rows, all_commits, all_camps = [], [], []
    window = camps_window()  # one window for the whole run, so a build spanning midnight is coherent
    for program in published:
        profile = build_profile(program, registry, rpi_hist, rpi_finals, state, ranks, club_table, club_recorder,
                                school_table, school_recorder)
        common.write_json(os.path.join(common.PROGRAMS_OUT_DIR, f"{program['slug']}.json"), profile)
        trends_recorder.observe(profile, program)
        rows.append(summary_row(profile))
        for c in profile["commitments"]:
            # clubInfo is per-profile detail; the cross-program index carries only the canonical id,
            # so it stays small enough to serve to every visitor.
            all_commits.append({**{k: v for k, v in c.items() if k not in ("sources", "clubInfo")},
                                "clubId": (c.get("clubInfo") or {}).get("clubId"),
                                "sourceCount": len(c["sources"]),
                                "collegeName": program.get("shortName") or program["name"]})
        for it in ((profile.get("camps") or {}).get("items") or []):
            if camp_in_window(it, window):
                all_camps.append(camp_row(program["slug"], it))
        common.log(f"build: {program['slug']} completeness {profile['_build']['completeness']} "
                   f"({len(profile['commitments'])} commits, {len(profile['seasons'])} seasons)"
                   + (f" stale: {profile['_build']['stale']}" if profile["_build"]["stale"] else ""))
    common.write_json(os.path.join(common.PROGRAMS_OUT_DIR, "index.json"),
                      {"updated": common.now_iso(), "season": registry["season"], "programs": rows})
    prune_profiles(prune_plan, {r["slug"] for r in rows}, common.PROGRAMS_OUT_DIR)
    common.write_json(os.path.join(common.COMMITS_OUT_DIR, "index.json"),
                      {"updated": common.now_iso(), "commitments": all_commits})
    camp_tally = camp_counts(all_camps)
    common.write_json(os.path.join(common.CAMPS_OUT_DIR, "index.json"),
                      {"updated": common.now_iso(), "window": window, "counts": camp_tally, "camps": all_camps})
    common.log(f"build: camps index {len(all_camps)} rows from {len({c['slug'] for c in all_camps})} programs, "
               f"window from {window['from']}; "
               f"{camp_tally['id']} id, {camp_tally['youth']} youth, {camp_tally['unknown']} unknown "
               f"({camp_tally['total'] - camp_tally['id']} hidden by the camp view)")
    common.log("build: " + trends.summary_line(trends_recorder.write()) + f" -> {trends.out_path()}")
    publishing = publishing_run()
    club_report = (club_recorder.write() if publishing
                   else club_recorder.report(common.read_json(clubs.REVIEW_PATH)))
    cs = club_report["summary"]
    common.log(f"build: clubs {cs['clubStringsMatched']} of {cs['recordsWithAClubString']} club strings matched "
               f"({cs['matchedShareOfStrings']}%) against {cs['clubsInTable']} reviewed clubs; "
               f"{cs['clubStringsUnmatched']} unmatched in {cs['distinctUnmatchedKeys']} names "
               f"({club_report['newSinceLastBuild']['count']} new)"
               + (" -> data/clubs-review.json" if publishing else " (scratch build: review report not written)"))
    school_report = (school_recorder.write() if publishing
                     else school_recorder.report(common.read_json(schools.REVIEW_PATH)))
    ss = school_report["summary"]
    common.log(f"build: high schools (D1) {ss['matched']} of {ss['playersWithAHighSchool']} players matched "
               f"({ss['matchedShareOfPlayersWithAHighSchool']}%) to {ss['distinctSchoolsMatched']} NCES schools; "
               f"{ss['unmatched']} unmatched ({ss['unmatchedWithoutAState']} with no state), "
               f"{ss['ambiguous']} ambiguous, {ss['outsideUS']} outside the US "
               f"({school_report['newSinceLastBuild']['count']} names new)"
               + (" -> data/schools-review.json" if publishing else " (scratch build: review report not written)"))
    if not validate(registry):
        common.log("!! build: schema validation reported errors (see SCHEMA lines above; `python collegedash.py validate`)")
    return rows


def validate(registry: dict, verbose: bool = False) -> bool:
    ok = True
    schema = common.read_json(common.SCHEMA_PATH)
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
        common.log("!! jsonschema not installed; skipping schema validation (pip install jsonschema)")
    for program in published_programs(registry):
        path = os.path.join(common.PROGRAMS_OUT_DIR, f"{program['slug']}.json")
        p = common.read_json(path)
        if not p:
            print(f"MISSING {path}")
            ok = False
            continue
        if schema and jsonschema:
            errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(p), key=lambda e: list(e.path))
            for e in errs[:10]:
                print(f"SCHEMA {program['slug']}: {'/'.join(str(x) for x in e.path)}: {e.message[:160]}")
            ok = ok and not errs
        if verbose:
            b = p["_build"]
            missing = [k for k, v in b["sections"].items() if not v]
            print(f"{program['slug']}: completeness {b['completeness']}; missing {missing or 'none'}; stale {b['stale'] or 'none'}")
    titles_ok = check_titles(registry)
    ranks_ok = check_academic_ranks(registry)
    seasons_ok = check_seasons(registry)
    camps_ok = check_camps_index(registry)
    stale_ok = check_no_stale_profiles(registry)
    membership_ok = check_membership_anchor(registry)
    staged_ok = check_staged_registry(registry)
    gate_ok = check_publish_gate(registry)
    return ok and titles_ok and ranks_ok and seasons_ok and camps_ok and stale_ok and membership_ok and staged_ok and gate_ok


def check_camps_index(registry: dict) -> bool:
    """Everything public/data/camps/index.json claims must be true of the profiles it was built from.

    The camps index is the first published file with no program of its own to sit on: a row that
    names a slug nothing resolves, or that survived a window it should not have, is invisible on
    every profile page and only shows up as a camp with no school in the site-wide view. This is the
    cheap guard that runs on every validate.

    It is checked against the window **the file declares**, not against today's window. A published
    index is a day old by definition the morning after a refresh, and re-deriving the window here
    would fail the check on correct data the first time a row aged out overnight. Staleness is what
    `updated` and the declared `from` are for; this check is about internal consistency.

    Like check_seasons it reports and does not raise: everything it reads is a file on disk that a
    hand-edit or a half-written build can have left any shape at all.

    Two of the checks below exist because the camp view hides rows (issue #78). `counts` must equal
    the tally of the rows actually published, so the number the view reports as hidden cannot drift
    away from the rows; and a per-item field that reaches no row and is not on
    CAMP_ITEM_UNPUBLISHED is reported by name, which is the latent allow-list hazard in #69 finally
    getting a voice.
    """
    path = os.path.join(common.CAMPS_OUT_DIR, "index.json")
    try:
        doc = common.read_json(path)
    except Exception as e:  # noqa: BLE001 - malformed JSON is the thing to name, not to die on
        print(f"CAMPS: {path} is not readable JSON: {type(e).__name__}: {e}")
        return False
    if not isinstance(doc, dict):
        print(f"CAMPS: {path} is {'missing' if doc is None else 'a ' + type(doc).__name__ + ', not an object'}")
        return False
    ok = True
    for key in ("updated", "window", "counts", "camps"):
        if key not in doc:
            print(f"CAMPS: the index declares no {key!r}")
            ok = False
    window = doc.get("window") if isinstance(doc.get("window"), dict) else {}
    if not isinstance(doc.get("window"), dict):
        print(f"CAMPS: `window` is a {type(doc.get('window')).__name__}, not an object with from/to")
        ok = False
    elif not isinstance(window.get("from"), str) or not window.get("from"):
        print(f"CAMPS: the index declares window.from {window.get('from')!r}; without it no row can be "
              f"placed and a stale publish is invisible")
        ok = False
    if isinstance(doc.get("window"), dict) and "to" not in window:
        print("CAMPS: the index declares no window.to (null means no upper bound; the key is still required)")
        ok = False
    published = doc.get("camps")
    if not isinstance(published, list):
        print(f"CAMPS: `camps` is a {type(published).__name__}, not a list of rows")
        return False
    if "counts" in doc:
        declared, actual = doc.get("counts"), camp_counts(published)
        if not isinstance(declared, dict):
            print(f"CAMPS: `counts` is a {type(declared).__name__}, not the id/youth/unknown tally")
            ok = False
        elif declared != actual:
            print(f"CAMPS: the index declares counts {declared}, but its rows tally {actual}; the camp "
                  f"view reports {actual['total'] - actual['id']} hidden rows from this number")
            ok = False
    if not ok:  # without a usable window nothing below can be judged
        return False

    index_path = os.path.join(common.PROGRAMS_OUT_DIR, "index.json")
    idx = common.read_json(index_path)
    known = {r.get("slug") for r in ((idx or {}).get("programs") or []) if isinstance(r, dict)}
    if not known:
        print(f"CAMPS: cannot read program slugs from {index_path}, so no row's slug can be resolved")
        return False
    allowed = {"slug", *CAMP_INDEX_FIELDS}
    for i, row in enumerate(published):
        if not isinstance(row, dict):
            print(f"CAMPS: row {i} is a {type(row).__name__}, not an object")
            ok = False
            continue
        slug = row.get("slug")
        if slug not in known:
            print(f"CAMPS: row {i} ({row.get('name')!r}) names slug {slug!r}, which is not a program in "
                  f"{os.path.basename(index_path)}")
            ok = False
        if not camp_in_window(row, window):
            print(f"CAMPS: row {i} ({slug}, {row.get('name')!r}) starts {row.get('startDate')!r}, outside "
                  f"the declared window from {window.get('from')!r} to {window.get('to')!r}")
            ok = False
        extra = sorted(set(row) - allowed)
        missing = sorted(allowed - set(row))
        if extra or missing:
            print(f"CAMPS: row {i} ({slug}) carries {extra or 'no extra fields'} and is missing "
                  f"{missing or 'nothing'}; the published shape is fixed")
            ok = False

    expected: list[dict] = []
    item_fields: set = set()
    for program in published_programs(registry):
        slug = program.get("slug")
        p = common.read_json(os.path.join(common.PROGRAMS_OUT_DIR, f"{slug}.json")) or {}
        camps = p.get("camps") if isinstance(p, dict) else None
        items = (camps or {}).get("items") if isinstance(camps, dict) else None
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict):
                item_fields |= set(it)
            if camp_in_window(it, window):
                expected.append(camp_row(slug, it))
    # Issue #69: CAMP_INDEX_FIELDS is an allow-list, so a per-item field added to build_camps is
    # dropped on the way out and nothing said so - which is how `campType` would have reached no
    # row at all while every other check here passed. Withheld-on-purpose is declared, so the only
    # thing this can report is a field nobody decided about.
    forgotten = sorted(item_fields - set(CAMP_INDEX_FIELDS) - set(CAMP_ITEM_UNPUBLISHED))
    if forgotten:
        print(f"CAMPS: the profiles carry per-item field(s) {forgotten} that the index publishes on no "
              f"row; add them to CAMP_INDEX_FIELDS, or to CAMP_ITEM_UNPUBLISHED if withholding them "
              f"is deliberate")
        ok = False
    if len(published) != len(expected):
        print(f"CAMPS: the index publishes {len(published)} rows, but the profiles hold {len(expected)} "
              f"items inside the declared window")
        ok = False
    # Whole rows, not an identity key. A key of (slug, startDate, name) leaves ten of the thirteen
    # published fields unchecked, among them registerUrl and sourceUrl - attacker-controllable
    # strings from camp vendors' pages that a view renders as links. Rows are grouped by identity
    # first so a mismatch can be reported as "this camp's price is wrong" rather than as two opaque
    # blobs, one missing and one unexpected.
    def ident(r: dict) -> tuple:
        return (r.get("slug"), r.get("startDate"), r.get("name"))

    def sort_key(k: tuple) -> tuple:
        return tuple(f"{v!r}" for v in k)  # slug/startDate/name can be null; None < str would raise

    pub_by_id: dict[tuple, list[dict]] = defaultdict(list)
    for row in published:
        if isinstance(row, dict):
            pub_by_id[ident(row)].append(row)
    exp_by_id: dict[tuple, list[dict]] = defaultdict(list)
    for row in expected:
        exp_by_id[ident(row)].append(row)

    only_pub = sorted(set(pub_by_id) - set(exp_by_id), key=sort_key)
    only_exp = sorted(set(exp_by_id) - set(pub_by_id), key=sort_key)
    if only_pub:
        print(f"CAMPS: published rows no profile holds inside the window: {only_pub[:5]}")
        ok = False
    if only_exp:
        print(f"CAMPS: profile items inside the window that the index does not publish: {only_exp[:5]}")
        ok = False
    for key in sorted(set(pub_by_id) & set(exp_by_id), key=sort_key):
        pubs, exps = pub_by_id[key], exp_by_id[key]
        if len(pubs) != len(exps):
            print(f"CAMPS: {key} is published {len(pubs)} time(s) but the profiles hold it {len(exps)} time(s)")
            ok = False
        for pub, exp in zip(pubs, exps):
            differs = sorted(f for f in set(pub) | set(exp) if pub.get(f) != exp.get(f))
            if differs:
                print(f"CAMPS: {key} does not match the profile item it was built from, in "
                      f"{differs}: the index says {[pub.get(f) for f in differs]}, the profile says "
                      f"{[exp.get(f) for f in differs]}")
                ok = False
    return ok


def check_seasons(registry: dict) -> bool:
    """Every published RPI rank must be the rank the archive or the NCAA table holds under that
    program's own curated id, and no id may be claimed by two programs.

    build_seasons creates season rows from those tables rather than only decorating rows Wikipedia
    already wrote, so a bad join no longer just mislabels a season that happened - it invents one,
    with another school's rank and record on it. There is no fuzzy matching to blame for that; this
    is the cheap guard that catches a hand-edited profile, a mistyped registry id, or two programs
    pointed at the same row, on every validate.

    It reports; it does not raise. Everything it reads is a file on disk that a hand-edit or a
    half-written build can have left any shape at all, and a validator that dies on the malformed
    input it exists to find tells you less than one that names it. Every value below is therefore
    type-checked before it is used, and the loaders are allowed to fail without taking validate
    down with them.
    """
    try:
        rpi_hist = load_rpi_history()
        finals = load_rpi_finals(registry["season"]["current"])
    except Exception as e:  # noqa: BLE001 - report the failure, do not become it
        print(f"SEASONS: cannot read the RPI tables to check against: {type(e).__name__}: {e}")
        return False
    ok, hist_claims, ncaa_claims = True, {}, {}
    for program in published_programs(registry):
        slug = program.get("slug")
        ids = program.get("ids") if isinstance(program.get("ids"), dict) else {}
        hist_name, ncaa_name = ids.get("rpiHistoryName"), ids.get("ncaaName")
        hist_name = hist_name if isinstance(hist_name, str) else None
        ncaa_name = ncaa_name if isinstance(ncaa_name, str) else None
        if hist_name:
            hist_claims.setdefault(hist_name, []).append(slug)
        if ncaa_name:
            ncaa_claims.setdefault(ncaa_name, []).append(slug)
        p = common.read_json(os.path.join(common.PROGRAMS_OUT_DIR, f"{slug}.json")) or {}
        if not isinstance(p, dict):
            print(f"SEASONS {slug}: the profile is a {type(p).__name__}, not an object")
            ok = False
            continue
        rows = p.get("seasons") or []
        if not isinstance(rows, list):
            print(f"SEASONS {slug}: `seasons` is a {type(rows).__name__}, not a list of season objects")
            ok = False
            continue
        for s in rows:
            if not isinstance(s, dict):
                print(f"SEASONS {slug}: a season entry is a {type(s).__name__}, not an object: {s!r:.60}")
                ok = False
                continue
            rank, y = s.get("rpiRank"), s.get("year")
            if rank is None:
                continue
            if not isinstance(rank, int) or isinstance(rank, bool):
                print(f"SEASONS {slug}: {y} publishes rpiRank {rank!r}, a {type(rank).__name__} "
                      f"where a whole number is required")
                ok = False
                continue
            if not isinstance(y, int) or isinstance(y, bool):
                print(f"SEASONS {slug}: a season publishing RPI #{rank} has year {y!r}, a "
                      f"{type(y).__name__} where a whole number is required")
                ok = False
                continue
            # the same precedence build_seasons applies: the archive's rank wins where this
            # program has an archive row, and the NCAA table stands everywhere else
            h = (rpi_hist.get(y) or {}).get(hist_name) if hist_name else None
            row = next((t for t in (finals.get(y) or {}).get("teams") or []
                        if isinstance(t, dict) and t.get("school") == ncaa_name), None) if ncaa_name else None
            want = h.get("rpiRank") if isinstance(h, dict) else (row.get("rank") if isinstance(row, dict) else None)
            if want is None:
                print(f"SEASONS {slug}: {y} publishes RPI #{rank}, but no {y} row exists under this "
                      f"program's own ids (rpiHistoryName {hist_name!r}, ncaaName {ncaa_name!r})")
                ok = False
            elif want != rank:
                print(f"SEASONS {slug}: {y} publishes RPI #{rank}, but its own row is #{want}")
                ok = False
    for field, claims in (("rpiHistoryName", hist_claims), ("ncaaName", ncaa_claims)):
        for name, slugs in sorted(claims.items()):
            if len(slugs) > 1:
                print(f"SEASONS: {field} {name!r} is claimed by {', '.join(slugs)}")
                ok = False
    return ok


def check_academic_ranks(registry: dict) -> bool:
    """Every published rank must be the row the committed asset holds, and no row may be claimed by
    two programs.

    tools/the_rank_check.py --refetch is the annual guard against the ranking itself moving; this is
    the cheap one that runs on every validate and catches a hand-edit to a profile or to the alias
    table in between. A wrong rank is worse than N/A (issue #46), and #48 is what that looks like.
    """
    asset = common.read_json(THE_ASSET_PATH)
    if not asset or not asset.get("rows"):
        print(f"RANK: missing or empty ranking asset {THE_ASSET_PATH}")
        return False
    rows = {r["theSlug"]: r for r in asset["rows"] if r.get("theSlug")}
    ok, claims = True, {}
    for program in published_programs(registry):
        slug = program["slug"]
        p = common.read_json(os.path.join(common.PROGRAMS_OUT_DIR, f"{slug}.json")) or {}
        ar = p.get("academicRank")
        if not isinstance(ar, dict):
            print(f"RANK {slug}: profile carries no academicRank block")
            ok = False
            continue
        if ar.get("rank") is None:
            if ar.get("theSlug"):
                print(f"RANK {slug}: no rank, yet it claims asset row {ar['theSlug']!r}")
                ok = False
            continue
        row = rows.get(ar.get("theSlug"))
        if row is None:
            print(f"RANK {slug}: rank {ar['rank']} traces to theSlug {ar.get('theSlug')!r}, "
                  f"which is not in {os.path.basename(THE_ASSET_PATH)}")
            ok = False
            continue
        if (row.get("usRank"), bool(row.get("tied"))) != (ar["rank"], bool(ar.get("tied"))):
            print(f"RANK {slug}: publishes {'=' if ar.get('tied') else ''}{ar['rank']}, but asset row "
                  f"{ar['theSlug']} is {'=' if row.get('tied') else ''}{row.get('usRank')}")
            ok = False
        claims.setdefault(ar["theSlug"], []).append(slug)
    for the_slug, slugs in sorted(claims.items()):
        if len(slugs) > 1:
            print(f"RANK: asset row {the_slug} is claimed by {', '.join(slugs)}")
            ok = False
    return ok


def check_titles(registry: dict) -> bool:
    """Every published national-title year is one its own division's champions table gives that program,
    and every year those tables give a published program is published by it.

    Per division since issue #113: a Division II program's titles are checked against the Division II
    table, and a year in neither table is reported rather than disappearing. Those reports print as
    "note: titles ..." and do not fail validate - a year a source claims and no championship record
    supports is a data question, not a broken build, and it arrives from a refresh nobody is watching.
    A published year that no table supports, or a table year a published champion did not publish, does
    fail. Every line that fails starts "TITLES ", which is the prefix tests/seasons_test.py reads as an
    invariant failure, so the notes deliberately do not use it."""
    programs = published_programs(registry)
    published, notes = set(), []
    ok = True
    for program in programs:
        slug, division = program["slug"], program.get("division")
        p = common.read_json(os.path.join(common.PROGRAMS_OUT_DIR, f"{slug}.json")) or {}
        pr = p.get("program") or {}
        for y in pr.get("nationalTitles") or []:
            published.add((division, y, slug))
        unsourced = pr.get("unsourcedTitleClaims") or []
        if unsourced:
            notes.append(f"note: titles {slug}: title years {sorted(unsourced)} are claimed for it by a source but are not "
                         f"in the {division} champions table, so they are not published")
    expected, unclaimed = set(), []
    for division, table in CHAMPION_TABLES.items():
        for year, champion in table.items():
            winners = [q["slug"] for q in programs if q.get("division") == division and title_matches(q, champion, division)]
            if len(winners) == 1:
                expected.add((division, year, winners[0]))
            elif len(winners) > 1:
                print(f"TITLES {division} {year}: champion {champion!r} matches more than one published program: {sorted(winners)}")
                ok = False
            else:
                unclaimed.append((division, year, champion))
    for division, year, slug in sorted(published - expected):
        champion = (CHAMPION_TABLES.get(division) or {}).get(year)
        print(f"TITLES {division} {year}: published by {slug}, champion is {champion!r}")
        ok = False
    for division, year, slug in sorted(expected - published):
        print(f"TITLES {division} {year}: {slug} is the champion but publishes no title for that year")
        ok = False
    for line in notes:
        print(line)
    if unclaimed:
        print(f"note: titles: {len(unclaimed)} champion years belong to programs this site does not publish "
              f"(e.g. {', '.join(f'{d} {y} {c}' for d, y, c in unclaimed[:3])})")
    return ok


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Rebuild public/data from the stored sources.")
    ap.add_argument("--allow-unexplained-prune", default="", metavar="SLUG[,SLUG]",
                    help="for this run only, delete these profiles although the registry does not explain why they are "
                         "unpublished (e.g. a program removed from the registry outright); each must be an unexplained stale profile")
    args = ap.parse_args()
    build(common.load_registry(), allow_unexplained_prune=frozenset(s for s in args.allow_unexplained_prune.split(",") if s))
