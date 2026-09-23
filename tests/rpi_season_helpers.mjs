// What the page's RPI season should be for a given published index (issue #62), for the suites that assert on
// RPI labels and ranks. Not a test file: it imports nothing from node:test.
//
// The rule, from the owner's decision on #62 (2026-09-23): the page shows the latest season any program is
// ranked in. While that season is the one being played (index.season.current - build.py only reads the NCAA's
// live table for that season) it is labelled "in progress". The finished season - what "Record" means - is the
// last ranked season before the one being played, never the one in progress. rpi_season.test.mjs pins this
// against literal years, so a mistake here cannot quietly move the page and its tests together.
export function expectedRpi(index) {
  const years = (index.programs || []).flatMap((p) => (p.rpiHistory || []).map((h) => h.year));
  const current = index.season?.current ?? null;
  const season = years.length ? Math.max(...years) : null;
  const inProgress = season != null && season === current;
  const done = years.filter((y) => current == null || y < current);
  const finished = done.length ? Math.max(...done) : current != null ? current - 1 : null;
  const label = season == null ? 'RPI' : `RPI ${season}${inProgress ? ' (in progress)' : ''}`;
  return { season, inProgress, finished, label };
}

// The rank the page should show for an index row in that season.
export const expectedRpiOf = (index) => {
  const { season } = expectedRpi(index);
  return (p) => (p.rpiHistory || []).find((r) => r.year === season)?.rank ?? null;
};

export const reEscape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
