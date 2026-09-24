"""
Program history from the team's Wikipedia article: infobox facts (founded, stadium, titles,
College Cups, conference championships) and the year-by-year results table.

Writes programs/<slug>/sources/wikipedia.json. Uses the REST HTML endpoint (stable markup).
"""

from __future__ import annotations

import re
import urllib.parse

from bs4 import BeautifulSoup

from . import common

NAME = "wikipedia"
YEAR_RE = re.compile(r"\b(?:19|20)\d\d\b")
RECORD_RE = re.compile(r"(\d+)\s*[–—-]\s*(\d+)(?:\s*[–—-]\s*(\d+))?")


OTHER_BODY_RE = re.compile(r"\b((?:19|20)\d\d)\s*\((?:[^)]*(?:AIAW|NAIA|NCCAA|NJCAA|vacated|club)[^)]*)\)", re.I)


def _years(text: str, max_year: int | None = None) -> list[int]:
    """Distinct years in a cell, ignoring years tagged as another governing body or vacated
    ('1981 (AIAW)') and anything after `max_year` (typos such as 2026 in a 2025 list)."""
    text = OTHER_BODY_RE.sub(" ", text or "")
    years = {int(y) for y in YEAR_RE.findall(text)}
    if max_year:
        years = {y for y in years if y <= max_year}
    return sorted(years)


def _record(text: str) -> dict | None:
    m = RECORD_RE.search(text or "")
    if not m:
        return None
    w, l, t = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    return {"w": w, "l": l, "t": t, "text": f"{w}-{l}-{t}"}


def _infobox(soup: BeautifulSoup) -> dict:
    """Return {label: text} from the infobox, handling the 'header row then value row' layout
    Wikipedia uses for lists of years."""
    ib = soup.find("table", class_=re.compile(r"\binfobox\b"))
    out: dict[str, str] = {}
    if not ib:
        return out
    rows = ib.find_all("tr")
    pending_header = None
    for tr in rows:
        th, td = tr.find("th"), tr.find("td")
        if th and td:
            out[common.clean(th.get_text(" "))] = common.clean(td.get_text(" "))
            pending_header = None
        elif th and not td:
            pending_header = common.clean(th.get_text(" "))
        elif td and pending_header:
            out[pending_header] = common.clean(td.get_text(" "))
            pending_header = None
    return out


FINISH_RE = re.compile(r"\b(T-?\d+(?:st|nd|rd|th)|\d+(?:st|nd|rd|th))\b")
NCAA_RE = re.compile(r"NCAA[^,;]*")
# Quotes allow a nickname ('P. Matthew "Matt" Dillon', lamar). A result letter is a lone W, L or T, not the
# initial in 'T. Logan Fleck' (south-florida), hence (?!\.) (issue #175).
COACH_RE = re.compile(r"^[A-Z][A-Za-z.'’\- \"“”]{3,}$")
BAD_COACH = re.compile(r"NCAA|Round|Final|Champion|Semifinal|Quarterfinal|Conference|Tournament|Runner|Winner|Sweet|Elite|"
                       r"College Cup|Regional|Did not|—|–|^[WLT]\b(?!\.)", re.I)


def _grid(rows) -> list[list[str]]:
    """The table's cell texts laid out on a grid, one list per <tr>, with rowspans and colspans filled in,
    so that column i of every row is the same column of the rendered table."""
    grid: list[list[str]] = []
    pending: dict[int, tuple[int, str]] = {}  # column -> (rows still covered, text)
    for tr in rows:
        out: list[str] = []
        col = 0
        cells = list(tr.find_all(["th", "td"]))

        def fill_pending():
            nonlocal col
            while col in pending:
                left, text = pending[col]
                out.append(text)
                if left <= 1:
                    del pending[col]
                else:
                    pending[col] = (left - 1, text)
                col += 1

        for c in cells:
            fill_pending()
            text = common.clean(c.get_text(" "))
            try:
                rs, cs = int(c.get("rowspan") or 1), int(c.get("colspan") or 1)
            except ValueError:
                rs, cs = 1, 1
            for _ in range(max(cs, 1)):
                out.append(text)
                if rs > 1:
                    pending[col] = (rs - 1, text)
                col += 1
        fill_pending()
        grid.append(out)
    return grid


PLAYER_COLUMN_RE = re.compile(r"\b(?:top\s+(?:points|scorer|scorers|goals|assists)|leading\s+scorer|captains?|players?|mvp)\b", re.I)


def _column_labels(rows, data_rows) -> list[str]:
    """Each column's header text (all header rows above the first season row, joined), lower case."""
    first = rows.index(data_rows[0]) if data_rows and data_rows[0] in rows else 0
    if first == 0:
        return []
    grid = _grid(rows[:first])
    width = max((len(r) for r in grid), default=0)
    return [" ".join(r[i] for r in grid if i < len(r)).lower() for i in range(width)]


def _coach_column(rows, data_rows) -> int | None:
    """The column whose header says coach, read from the header rows above the first season row."""
    return next((i for i, label in enumerate(_column_labels(rows, data_rows)) if "coach" in label), None)


def _player_columns(rows, data_rows) -> set[int]:
    """Columns whose header names players ('Top points', 'Top scorer'): never a coach."""
    return {i for i, label in enumerate(_column_labels(rows, data_rows)) if PLAYER_COLUMN_RE.search(label)}


NCAA_COLUMN_RE = re.compile(r"\bncaa\b", re.I)
NCAA_STAT_RE = re.compile(r"w[–-]l|pct", re.I)  # south-carolina: 'NCAA W–L', 'NCAA win pct' are tallies, not results
FINISH_COLUMN_RE = re.compile(r"\b(?:finish|standing|place|pos\.)", re.I)
FINISH_NOT_RE = re.compile(r"tourn|natl|final rank|poll", re.I)  # wake-forest 'Conference tourn. pos.' is not the finish
RESULT_RE = re.compile(r"round|final|champion|runner|sweet|elite|college cup|regional", re.I)
OTHER_BODY_CELL_RE = re.compile(r"\b(?:AIAW|NAIA|NCCAA|NJCAA)\b")
FINISH_CELL_RE = re.compile(r"\b(T-?\d+(?:st|nd|rd|th)|\d+(?:st|nd|rd|th))\b", re.I)  # siue 2019: 't1st'


def _result_columns(rows, data_rows, grid) -> tuple[int | None, int | None]:
    """The columns headed as the NCAA result and the conference finish (issue #176), in the laid-out grid.

    Header rows are right-aligned to the season rows: on california and boston-college the 'Head coach' header
    cell has no rowspan, so the lower header rows are one column short on the left. A header row that is one
    cell across the whole table (a coaching-era divider such as "Kate O'Shaughnessy (1996–1997)", or lamar's
    'NCAA year-by-year results' caption) names no column and is skipped."""
    first = rows.index(data_rows[0]) if data_rows and data_rows[0] in rows else 0
    if first == 0:
        return None, None
    season_rows = set(map(id, data_rows))
    width = max((len(grid[i]) for i, r in enumerate(rows) if id(r) in season_rows), default=0)
    labels = [""] * width
    for tr, laid in zip(rows[:first], grid[:first]):
        if len(tr.find_all(["th", "td"])) <= 1 or len(set(laid)) <= 1:
            continue
        laid = laid[-width:] if len(laid) > width else [""] * (width - len(laid)) + laid
        for i, text in enumerate(laid):
            labels[i] += " " + text
    ncaa = next((i for i, l in enumerate(labels) if NCAA_COLUMN_RE.search(l) and not NCAA_STAT_RE.search(l)), None)
    finish = next((i for i, l in enumerate(labels) if FINISH_COLUMN_RE.search(l) and not FINISH_NOT_RE.search(l)), None)
    return ncaa, finish


def _is_record_cell(c: str) -> bool:
    return bool(RECORD_RE.search(c)) and not re.search(r"[A-Za-z]{4,}", c)


def _record_columns(labels: list[str], laid_out_rows) -> tuple[int, int] | None:
    """Issue #303: (overall column, conference column) for a table whose header puts the conference record
    FIRST, as florida's ('Conference record' ... 'Regular season record') and san-diego-state's ('Record:
    Conference | Overall') do; None for every other table, which keeps reading the first record cell as the
    overall one. The first two columns that hold a record in any season row (tournament columns aside) are compared by their headers: the
    first must name the conference and not 'overall', the second must name 'overall' or not the conference. A
    conference name in a header row above the whole table ('Western Athletic Conference') is in every label, so
    'overall' decides there."""
    cols = sorted({i for row in laid_out_rows for i, c in enumerate(row) if i > 0 and _is_record_cell(c)})
    # a tournament's own record ('Conference tournament results': florida's '1–1') is neither
    cols = [i for i in cols if i < len(labels) and not re.search(r"tourn|postseason|ncaa|playoff", labels[i])]
    if len(cols) < 2:
        return None
    first, second = labels[cols[0]], labels[cols[1]]
    if "conf" in first and "overall" not in first and ("overall" in second or "conf" not in second):
        return cols[1], cols[0]
    return None


def _seasons_table(soup: BeautifulSoup) -> list[dict]:
    """Year-by-year results. Wikipedia articles use several layouts:
      Stanford: Year | Head coach | Overall | Conference | Conference Standing | NCAA Tournament
      UCLA:     Season | Coach | Record (Overall, Conference) | Notes            (coach cell rowspans)
      Duke:     Season | Head coach | Wins Losses Ties | Wins Losses Ties | Conference | NCAA
    so the parser reads records from whatever cells look like records or W/L/T triples, and the
    coach from the first name-like cell (carrying it forward across rowspans)."""
    best = None
    for t in soup.find_all("table", class_=re.compile(r"wikitable")):
        rows = t.find_all("tr")
        first = rows[0] if rows else None
        heads = [common.clean(c.get_text(" ")).lower() for c in first.find_all(["th", "td"])] if first else []
        if not heads or not heads[0].startswith(("year", "season")):
            continue
        def is_season_row(r):
            first_txt = common.clean(r.find(["th", "td"]).get_text(" ")) if r.find(["th", "td"]) else ""
            # '2011' or '2020–21' are seasons; '2007–2013' is a coaching era, not a season
            return bool(r.find("td")) and bool(YEAR_RE.match(first_txt)) and not re.search(r"\d{4}\s*[–-]\s*\d{4}", first_txt)
        data_rows = [r for r in rows if is_season_row(r)]
        if len(data_rows) < 5:
            continue
        joined = " ".join(common.clean(r.get_text(" ")).lower() for r in rows[:3])
        if not re.search(r"record|overall|wins|w–l|w-l", joined) or re.search(r"opponent|round", joined):
            continue
        if best is None or len(data_rows) > len(best[1]):
            best = (t, data_rows, rows)
    if not best:
        return []
    t, data_rows, rows = best
    header_txt = " ".join(common.clean(r.get_text(" ")).lower() for r in rows[:3])
    split_wlt = "wins" in header_txt and "losses" in header_txt
    # Issue #175: the coach is read from the column headed "coach" when the table has one. The first
    # name-like cell is only the fallback for tables without such a header: clemson's coach cell spans
    # 2011-2025 by rowspan, so those rows carry no coach cell of their own, and the first name-like cell
    # left in them was the "Top points" player (Makenna Morris, Kendall Bodak, JuJu Harris).
    # A table with no coach header but with player columns (wake-forest: 'Top points', 'Top scorer') has no
    # coach to read at all; the fallback only looks outside columns that name players.
    coach_col = _coach_column(rows, data_rows)
    player_cols = _player_columns(rows, data_rows) if coach_col is None else set()
    laid_out_rows = _grid(rows)
    grid = dict(zip(map(id, rows), laid_out_rows))
    # Issue #176: the NCAA result and the conference finish come from the columns headed as such, when the table
    # has them. Before, a table that splits wins, losses and ties took the NCAA result from the last text cell in
    # the row: clemson's 'Top points' players (2004, 2021) or its conference finish (2009, 'NCAA 11th').
    ncaa_col, finish_col = _result_columns(rows, data_rows, laid_out_rows)
    rec_cols = None if split_wlt else _record_columns(_column_labels(rows, data_rows), [grid.get(id(r)) or [] for r in data_rows])
    seasons, coach_last, legacy_last = [], None, None
    for tr in data_rows:
        cells = [common.clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
        year_txt = cells[0]
        year = int(YEAR_RE.search(year_txt).group(0))
        rest = cells[1:]
        name_like = lambda c: bool(COACH_RE.match(c) and not BAD_COACH.search(c) and not RECORD_RE.search(c))
        # What the first name-like cell was before #175. It no longer sets the coach where a header says which
        # column is the coach's, but the NCAA and finish lookups below still skip it, exactly as before, so this
        # change moves only the coach (their own column mapping is a separate fault, reported on the issue).
        legacy = next((c for c in rest if name_like(c)), None)
        legacy_last = legacy or legacy_last
        if coach_col is not None:
            laid_out = grid.get(id(tr)) or []
            cell = laid_out[coach_col] if coach_col < len(laid_out) else ""
            coach = cell if name_like(cell) else None
        elif player_cols:
            laid_out = grid.get(id(tr)) or []
            coach = next((c for i, c in enumerate(laid_out[1:], start=1) if i not in player_cols and name_like(c)), None)
        else:
            coach = legacy
        if coach:
            coach_last = coach
        else:
            coach = coach_last
        legacy_coach = legacy or legacy_last
        rec = crec = None
        if split_wlt:
            nums = [int(c) for c in rest if re.fullmatch(r"\d{1,2}", c)]
            if len(nums) >= 3:
                rec = {"w": nums[0], "l": nums[1], "t": nums[2], "text": f"{nums[0]}-{nums[1]}-{nums[2]}"}
            if len(nums) >= 6:
                crec = {"w": nums[3], "l": nums[4], "t": nums[5], "text": f"{nums[3]}-{nums[4]}-{nums[5]}"}
        else:
            recs = [c for c in rest if _is_record_cell(c)]
            if rec_cols and len(recs) >= 2:
                # #303: the header puts the conference record first and the overall record after it. Read in cell
                # order, not by column (florida's rows leave cells out, so a column number does not hold across its
                # rows): the first record is the conference one, the last the overall one, and a conference
                # tournament's own record between them ('1–1') is neither.
                rec, crec = _record(recs[-1]), _record(recs[0])
            elif rec_cols and len(recs) == 1:
                # one record: its own column says which it is (san-diego-state 1989 has an overall record only)
                laid = grid.get(id(tr)) or []
                col = next((i for i, c in enumerate(laid) if i > 0 and c == recs[0]), None)
                rec, crec = (None, _record(recs[0])) if col == rec_cols[1] else (_record(recs[0]), None)
            else:
                rec = _record(recs[0]) if recs else None
                crec = _record(recs[1]) if len(recs) > 1 else None
        ncaa = None
        laid_out = grid.get(id(tr)) or []
        if ncaa_col is not None:
            cell = laid_out[ncaa_col] if ncaa_col < len(laid_out) else ""
            m = NCAA_RE.search(cell)
            # a dash, 'Ineligible due to Transition to Division I' (north-dakota-state 2004) or a blank is no result
            # north-carolina 1980-81 'AIAW Semifinals'/'AIAW Champions' sit in its NCAA column but are not NCAA results
            ncaa = common.clean(m.group(0)) if m else ("NCAA " + cell if RESULT_RE.search(cell) and not OTHER_BODY_CELL_RE.search(cell) else None)
        else:
            for c in rest:
                m = NCAA_RE.search(c)
                if m:
                    ncaa = common.clean(m.group(0))
                    break
        if ncaa is None and split_wlt and ncaa_col is None:
            tail = [c for c in rest if not re.fullmatch(r"\d{1,2}", c) and c not in ("—", "–", "-") and c != legacy_coach]
            if tail:
                ncaa = "NCAA " + tail[-1] if "ncaa" not in tail[-1].lower() else tail[-1]
        finish = None
        if finish_col is not None:
            cell = laid_out[finish_col] if finish_col < len(laid_out) else ""
            m = FINISH_CELL_RE.search(cell)
            finish = m.group(1) if m and not re.search(r"round|ncaa", cell, re.I) else None
            if finish and finish[0] == "t":  # a tie written in lower case, 't-2nd' (wake-forest) or 't1st' (siue)
                finish = "T" + finish[1:]
        else:
            for c in rest:
                if c == legacy_coach or (ncaa and c == ncaa):
                    continue
                m = FINISH_RE.search(c)
                if m and not re.search(r"round|ncaa", c, re.I):
                    finish = m.group(1)
                    break
        seasons.append({
            "year": year, "label": year_txt, "headCoach": coach,
            "record": rec["text"] if rec else None,
            "wins": rec["w"] if rec else None, "losses": rec["l"] if rec else None, "ties": rec["t"] if rec else None,
            "confRecord": crec["text"] if crec else None, "confFinish": finish, "ncaaResult": ncaa,
        })
    return seasons


MENS_TITLE_RE = re.compile(r"(?<!wo)men's[ _]soccer", re.I)


def collect(program: dict, registry: dict) -> dict:
    title = program["ids"].get("wikipedia")
    if not title:
        raise common.SkipCollector("wikipedia: no team article in the registry (most mid-majors have none; "
                                   "try `registry fix-wiki`)")
    if MENS_TITLE_RE.search(title):
        # #303: old-dominion, east-tennessee-state, manhattan and campbell were registered to the men's team's
        # article, and their men's season records were published as the women's
        raise common.SkipCollector(f"wikipedia: {title!r} is the men's team's article, not this program's")
    url = registry["sources"]["wikipedia"]["htmlApi"].format(title=urllib.parse.quote(title, safe=""))
    html, meta = common.fetch_text(url, max_age_hours=24 * 7)
    soup = BeautifulSoup(html, "html.parser")
    ib = _infobox(soup)

    def find(*labels):  # loose match, for descriptive rows (stadium, head coach, nickname)
        for k, v in ib.items():
            kl = k.lower()
            if any(l in kl for l in labels):
                return v
        return ""

    def row(*patterns):
        """Honours rows are matched on the WHOLE label, anchored, so 'Conference tournament
        championships' can never satisfy the national-title pattern (that bug published Big West
        titles as NCAA championships)."""
        for k, v in ib.items():
            kl = common.clean(k).lower()
            if any(re.fullmatch(p, kl) for p in patterns):
                return v
        return ""

    max_year = (registry.get("season") or {}).get("current")
    honours = lambda *patterns: _years(row(*patterns), max_year)
    stadium_txt = find("stadium")
    cap = re.search(r"capacity[:\s]*([\d,]+)", stadium_txt, re.I)
    seasons = _seasons_table(soup)
    data = {
        "title": title,
        "pageUrl": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title)}",
        "founded": (_years(find("founded")) or [None])[0],
        "headCoach": find("head coach") or None,
        "conference": find("conference") or None,
        "stadium": {"name": re.sub(r"\(.*", "", stadium_txt).strip() or None,
                    "capacity": int(cap.group(1).replace(",", "")) if cap else None},
        "nickname": find("nickname") or None,
        "nationalTitles": honours(r"ncaa (?:tournament |division i )?champion(?:s|ships?)?", r"national champion(?:s|ships?)?"),
        "nationalRunnerUp": honours(r"ncaa .*runner[- ]up"),
        # some articles label the final four 'Semifinals' instead of 'College Cup'
        "collegeCups": honours(r"ncaa .*college cup", r"ncaa .*semifinals?"),
        "ncaaQuarterfinals": honours(r"ncaa .*quarterfinals?"),
        "ncaaAppearances": honours(r"ncaa .*appearances", r"ncaa tournament"),
        "confRegularSeasonTitles": honours(r"conference regular[- ]season champion(?:s|ships?)?"),
        "confTournamentTitles": honours(r"conference tournament champion(?:s|ships?)?"),
        "seasons": seasons,
        "infobox": ib,
    }
    common.save_source(program["slug"], NAME, data, url=data["pageUrl"], collector=NAME,
                       extra={"fromCache": meta.get("fromCache", False)})
    common.log(f"wikipedia: {len(seasons)} seasons, titles {data['nationalTitles']}, stadium {data['stadium']}")
    return data
