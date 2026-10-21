---
name: evidence
description: Produce the before/after evidence a PR needs. For a visible change, Playwright screenshots and measurements of main and the branch at 1280 and 390 px in light and dark (card heights, horizontal scroll, contrast). For a data change, before/after counts. Use before you ask for review of any change a reader would see, or any change to published data.
---

# Before/after evidence

A PR is ready for the owner only when its evidence is posted (see "Review exit rule" in `CLAUDE.md`). "It looks fine" is not evidence. This skill gives you two tools: `shots.js` for what a reader sees, and `data_counts.py` for what the data now holds. Pick the one that matches the change; use both when a change does both.

Do the `setup` skill first (it checks that Playwright can start Chromium). Keep every output file in your session scratchpad, never in the worktree.

## A. Visible change: `shots.js`

Take the same shots of **main** and of **your branch**, then compare. You need two checkouts served at the same time:

```
git worktree add <scratchpad>/main origin/main          # once; a clean main
python collegedash.py serve --port 8101 &                # in <scratchpad>/main: the "before"
python collegedash.py serve --port 8102 &                # in your worktree: the "after"
```

Pick ports nobody else is using (other agents share this machine); a busy port makes `serve` fail with a message, so read its first lines.

```
node .claude/skills/evidence/shots.js --check            # Playwright and Chromium start; prints their versions
node .claude/skills/evidence/shots.js http://127.0.0.1:8101 <scratchpad>/ev --label main
node .claude/skills/evidence/shots.js http://127.0.0.1:8102 <scratchpad>/ev --label branch
node .claude/skills/evidence/shots.js --compare <scratchpad>/ev/main.json <scratchpad>/ev/branch.json
```

Always run **both** labels with identical options, or the comparison means nothing. Stop the servers when you are done.

What one run produces, per width (default 1280 and 390) and theme (light and dark):

- `LABEL-WIDTH-THEME.png`: a screenshot of the page after the cards have rendered.
- `LABEL.json`: the measurements. Per view: card count, card height min and max, the largest height spread inside one row (`rowSpread`), horizontal scroll (page `scrollWidth` against the window), and text contrast inside the cards (WCAG ratio of every text element's colour against the colour behind it, the lowest ratio and the element it belongs to, and how many texts fall below AA: 4.5, or 3 for large text). Text over a gradient or image is counted as `unmeasured`, never guessed.
- `--compare` prints the two JSON files as a Markdown table with the changed rows marked. Paste it in the PR.

Options (all in the header of `shots.js`):

| option | use it to |
| --- | --- |
| `--route '#/programs/air-force'` | open another page (default `#/programs`) |
| `--cards SELECTOR` | wait for and measure other elements (default `.grid.cards > .pcard`) |
| `--card air-force,navy` | add a close-up screenshot of those cards (matched by `data-slug`); use it to show the one card a change is about |
| `--widths 1280,1440,390` | change the widths |
| `--themes dark` | one theme only |
| `--zoom 1,2` | text-only zoom: every font-size is multiplied, widths stay. Shows what a reader with larger text sees |
| `--filters JSON` | seed a different `cd.filters` (default: the unfiltered card view sorted by name). The theme is seeded through `cd.theme` |

### How to read the result

- **Say what you looked at.** Open the screenshots (the file-reading tool shows images) and describe what changed, and what did not. A measurement table with no description is half the evidence.
- **Card heights.** Cards in one grid row should stay equal; `rowSpread` above 0 is a layout change worth explaining. Compare min and max before and after.
- **Horizontal scroll.** `hScroll` must be `no` at 390 px on both. A `YES` that appears only on the branch is a regression.
- **Contrast.** Needed only where colours change, but it is cheap, so read the row anyway. A new `belowAA` count is a regression; an existing one is not yours, but mention it. Compare the lowest ratio and its element.
- **The Inter font cannot load in this sandbox.** The page falls back to another font, so text is wider than in production. That makes the widths worst-case, and it is the same on main and on the branch, so the comparison holds. Say so in the PR instead of presenting the screenshot as pixel-exact.
- **A card or value that only appears under some data.** Use `--card SLUG` for a card that has it, and say which slug.
- If a view fails (the cards never appear), the run writes `LABEL-WIDTH-THEME-FAILED.png`, records the error in the JSON and exits 1. Look at that screenshot before you do anything else; it is usually a server on the wrong port or a script error on the page.

### The live site

`shots.js https://college.nextonetwo.com <dir> --label live` works too: it goes through `HTTPS_PROXY` when that is set, trusting only the proxy's own CA (`CD_PROXY_CA`, default `/root/.ccr/agent-proxy-ca.crt`). Certificate checking stays on for everything else. Use the live site to show what readers see today; this reads the owner's own site and is not scraping a source site. Do not point it anywhere else.

## B. Data change: `data_counts.py`

Offline: it reads git objects or directories, never the network.

```
python3 .claude/skills/evidence/data_counts.py                              # origin/main -> HEAD
python3 .claude/skills/evidence/data_counts.py --before a83a32086~1 --after a83a32086
python3 .claude/skills/evidence/data_counts.py --after <dir with the repo layout, e.g. a build output>
python3 .claude/skills/evidence/data_counts.py --count division --count roster --count commitments
```

It prints Markdown for the PR:

1. files added, removed and changed per folder under `public/data` (`--path` narrows it; `--depth` sets the folder depth);
2. for the program profiles that changed: how many changed in each top-level field (`_build` is left out, since it changes on every build; add `--ignore FIELD` for others);
3. for each `--count FIELD` (a dotted path into a profile, e.g. `division` or `tuition.in_state`): the profiles where it is present and non-empty, the items in it, and its values when there are at most 12 distinct ones (so `division` shows D1, D2 and D3 side by side).

Use `--before` and `--after` with a revision or a directory. When the change is a script that writes data, build once on main and once on the branch into two directories and compare those; the script never has to fetch anything.

### Counts are evidence, not tests

The counts describe one tree on one day. They belong in the PR description. A test must never pin them on live published data, because the next data refresh changes them (#503, #508). Pin exact counts only on frozen fixtures in `tests/`.

## What to post on the PR

For a visible change: the `--compare` table, the screenshots (attach the files, or link them), two or three sentences on what changed and what did not, and the Node and Playwright versions from `--check`. For a data change: the `data_counts.py` output and the command line that made it. Say which parts you could not measure (for example "contrast unmeasured on the gradient band").
