VERDICT: CHANGES REQUESTED

Both round-4 required changes are resolved. I checked each one myself (see the first OPTIONAL item). Two problems block approval. The first is the same kind as round 4's point 2, but for the Coaches section. Revision 4's own check of every `sections` list covered only conference and list rows, and I missed coach rows in rounds 1-4. The second is an environment claim that revision 4 re-checked and got wrong.

REQUIRED:
- 1. From PR 8, coach rows give a Coaches section to judged queries whose `sections` leave Coaches out. That breaks "No check that passes today may fail" (plan 7.4, line 1051).
  - Section 5.2 (602) says Coaches rows are "head coaches whose name the name words match", ranked by match class. So prefix matches count, as they do in ECNL's `expand` (ecnl:public/search/match.mjs:152-154: a prefix is allowed on the last word, or on any word of 3 or more letters).
  - On the fixture's 926 head coaches, the approximate reader in chitu-r4/conf_rule_final.py finds:
    - S02 "cal": 6 coach rows (Lauren Calabrese at lehigh, Caleb Cole, Cally Morrill, Alistair Caldwell, Hannah Callaghan, Jeannine Calhoun);
    - X01 "mac": 2 (Jovany Macias at texas-am-international, Jonny Macadam at bates-college);
    - E02 "a": 105;
    - E03 "st": 42;
    - E15 "saint": 2, through the saint/st twin (Kristen St. Clair at california-baptist, Tari St. John at butler).
  - With typo matching added under 4.5's rules, the list is the same.
  - All five have judged `sections` without Coaches (7.1, and the 5.3 table at 671-672). S02, E02 and E03 pass their section check today, because the header box shows Programs only. From PR 8 each would be Programs, Coaches, so each fails. X01 and E15 would also fail from PR 8.
  - Section 7.1 (876-877) says "Every `sections` list is checked against the rules that make sections". The check covered only conference rows and list rows.
  - Fix: say when name words give a coach row. For example, use 5.2's conference word rule: whole words, a last word of 4 or more letters may be a prefix, and a lone word of one or two letters gives no row. Say whether twins and typos apply. Then make every judged `sections` list agree with that rule.
    - Under the conference rule, "saint" still finds St. Clair and St. John through the twin. So either E15 gains Coaches `pending: "PR 8"`, or coach names don't use the twin.
    - H01, H04 and E07 keep their rows under that rule.
  - Pin the result in PR 8's failing tests (1531-1534). Add coach rows to the 7.1 check, with a script like the other two.
  - My read-only check is huatuo-r5/coach_rows.py and huatuo-r5/coach_typos.py. (G05 in their output is a gap in the approximate reader: it reads lower-case "me" as a name word, where 4.2 rule 3 makes it Maine.)
- 2. The Node 24 claim is false. These lines say there is no Node 24 on this machine:
  - 10, 43, 1132 and 1236;
  - the appendix at 1753 ("no Node 24 on PATH or under /opt, /usr or /root");
  - the change list at 1824-1825.

  But /usr/local/lib/python3.11/dist-packages/playwright/driver/node is v24.21.0. It is the Node bundled with Python Playwright 1.63.0 (`pip show playwright`). A second copy, also v24.21.0, is at /root/.cache/uv/archive-v0/p-TI42glO8xpZ8oBXVFcP/playwright/driver/node. I ran `node --test` with the first one on a one-test scratch file (huatuo-r5/n24probe.test.mjs): 1 pass. `node:test` and `node:vm` both load.

  Fix: correct those lines. Then say in section 8's "How every PR works" (1236) and in 7.5 whether a PR run here also uses this Node 24, which matches tests.yml:122. Note that it comes bundled with a Python package, not installed on its own, so its version can change when that package changes.

OPTIONAL:
- Verified, no change needed. Round-4 point 1 is resolved:
  - build.py:2003-2004 is the swap. build.py and public/index.html are byte-identical at df9417725 and 365ce91ec. Main's public/data/programs/index.json has the fixture's sha256 (5546d056…).
  - On the fixture:
    - 160 programs are State-side;
    - 89 have "st": 50 State-side and 39 others;
    - 40 have "saint", and cal-state-fullerton is the only State-side one;
    - under the new rule, a typed "saint" exactly matches the same 39 programs as E15's `first`, and none of ohio-state, alabama-state or cal-state-fullerton;
    - six programs match only through the nickname "Saints";
    - no State-side program has a "St." or "Saint" meaning Saint.
  - Today's box gives "saint" 46 hits. Cal State Fullerton is 32nd, with score 60 through "Cal Saint Fullerton". I re-ran work/today-all.mjs offline under a dead proxy.

  Round-4 point 2 is resolved:
  - My own walk over the 93 queries and the 98 stored pairs agrees with chitu-r4/conf_rule_final.py. Conference rows go only to F01-F08, X01-X04, L04 and E15. "MAC" and "Metro" are the only stored names with those words, so X01 and X03 get one row each.
  - chitu-r4/list_rows.py agrees with the draft and 7.1 `sections`. S06 is kept out of Lists by the "of" rule.
  - E06 and E14 are Programs-only too-broad slates.
  - The new cites match: 1123-1134, 1126, 1137-1160, 1152, 1403, 2512, 2535-2540, 2631, 2633, 2644, 3582, 3588, 4272, 4283-4293, 4334, 4408 and 4449.
  - The Enter wrapper `function todayEnter(e) { if (false) {}` … `}` is valid JS around 2535-2540.
  - Every free name in the frozen slices is either frozen or stubbed.

  The three round-4 optional notes are taken: E02 140 = 121 + 19, E03 225 = 215 + 10, the frozen names are added, and the "answers" label is fixed. The environment facts check out: Playwright 1.56.1, /opt/pw-browsers chromium-1194, Node 22.22.0, 20.20.0 and 21.7.3, and Python 3.12.3 at /usr/bin/python3.12.
- Optional: PR 3's unit test quotes saint-louis's "St. Louis". Its search names on the fixture are "Saint Louis", "Saint Louis University", "St Louis" and "St Louis University", with no period. Quote one that exists. Likewise 4.1 (434) says the swap replaces a "St." followed by a space. The regex `\bSt\.?\s` (build.py:2003) also matches "St " with no period.
- Optional: decision M (1608) says "a state name right after 'university of'", while 4.3 rule 2 (520) says "the state name or region". Make them say the same.
- Optional: 5.2 rule 2 (606) describes the twins on the query side ("a typed 'st' also matches 'state'"), while 4.1 applies them when indexing, as ECNL does (ecnl:public/search/teams.mjs:23, withAliases on the document's words). Say that conference names are twinned when indexed, and that rule 3's last-word prefix applies to the typed word only. Otherwise "saint", read as "st" plus a prefix, could reach Sunshine State or Lone Star. E15's PR 5 mustNever would catch that, but the text should rule it out.
- Notes: my read-only scripts and outputs are in /tmp/claude-0/-home-user-collegedash/d8e4b319-4da9-585a-a6b2-980aa72c1e2a/scratchpad/search507/huatuo-r5/ (facts5.py, coach_rows.py, coach_typos.py, diff.txt, today-saint.json, n24probe.test.mjs). Nothing in either repo was changed; both working trees are clean, and main is at 365ce91ec.
