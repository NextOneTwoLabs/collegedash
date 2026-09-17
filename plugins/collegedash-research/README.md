# CollegeDash Research plugin

A private local Codex research plugin for the existing CollegeDash JSON checkout. It provides instructions and a data guide for finding programs, comparing schools, and explaining roster, commitment, camp, and feeder evidence. It contains no dataset, query service, API, MCP server, or additional model client.

This MVP implements [issue #238](https://github.com/NextOneTwoLabs/collegedash/issues/238). The website, its search behavior, and data publication remain unchanged.

## Use

After local installation, start a **new Codex task** and select CollegeDash Research or invoke its research skill. Example prompts:

- Find D1 programs in CA, OR, or WA with out-of-state tuition below $40,000; explain missing cost data.
- Compare Stanford, UCLA, and USC using academics, costs, and roster evidence.
- Which D1 programs have players from my club? Separate current players, former players, and commitments.

The plugin uses an explicitly supplied checkout path first, then the current working directory if it has the built index, then `D:\Projects\CollegeDash`. Supply a different checkout path on another machine. An unavailable explicit path is reported rather than replaced. Python 3 and the already-built `public/data` JSON files are required; no extra Python packages are needed for research.

Answers describe the current **local** snapshot. They do not refresh data or automatically match the deployed site. Collected facts may be incomplete, stale, or contradictory; recommendations should expose those limits.

## Local installation and updates

Keep this directory as the version-controlled source. Install a copy at `~/plugins/collegedash-research` and register it in the personal marketplace `~/.agents/plugins/marketplace.json`. The personal source entry `./plugins/collegedash-research` resolves from your home directory, **not** the directory containing `marketplace.json`. Personal marketplace state and installed copies are not committed here.

For a new installation, run this PowerShell sequence from the repository root. It assumes the system skills are under the default `~/.codex/skills/.system`; adjust that one path if your installation differs. The official validation helpers require **PyYAML in the Python environment used for validation**; this is a development-only dependency, not a requirement for research.

```powershell
$pluginSource = (Resolve-Path 'plugins/collegedash-research').Path
$systemSkills = Join-Path $env:USERPROFILE '.codex/skills/.system'
$pluginCreator = Join-Path $systemSkills 'plugin-creator/scripts'
$pluginInstalled = Join-Path $env:USERPROFILE 'plugins/collegedash-research'
if (Test-Path -LiteralPath $pluginInstalled) { throw 'Use the update workflow for an existing installation.' }

python "$pluginCreator/create_basic_plugin.py" collegedash-research --with-skills --with-marketplace
if ($LASTEXITCODE -ne 0) { throw 'Plugin registration failed.' }
Copy-Item -LiteralPath "$pluginSource/.codex-plugin/plugin.json" -Destination "$pluginInstalled/.codex-plugin/plugin.json" -Force
Copy-Item -LiteralPath "$pluginSource/skills" -Destination $pluginInstalled -Recurse -Force
Copy-Item -LiteralPath "$pluginSource/README.md" -Destination $pluginInstalled -Force

python "$pluginCreator/validate_plugin.py" $pluginInstalled
if ($LASTEXITCODE -ne 0) { throw 'Plugin validation failed.' }
python "$systemSkills/skill-creator/scripts/quick_validate.py" "$pluginInstalled/skills/research"
if ($LASTEXITCODE -ne 0) { throw 'Skill validation failed.' }
$personalMarketplace = python "$pluginCreator/read_marketplace_name.py"
if ($LASTEXITCODE -ne 0) { throw 'Marketplace validation failed.' }
codex plugin add "collegedash-research@$personalMarketplace"
if ($LASTEXITCODE -ne 0) { throw 'Plugin installation failed.' }
```

The scaffold preserves other personal marketplace entries. The personal marketplace is discovered implicitly; it does not need `codex plugin marketplace add`.

For an existing installation, validate the marketplace name with plugin-creator's `read_marketplace_name.py`, sync this package, run `update_plugin_cachebuster.py` on the installed copy, and reinstall with `codex plugin add`. Do not edit personal marketplace configuration by hand. Start a new task to pick up changes. Filesystem permissions may require approval for personal-directory writes.

## Evidence and privacy

The plugin reads built research JSON and projects only relevant fields before emitting evidence. It excludes curated notes, index tags, raw collector archives, raw RPI tables, credentials, feedback, and review queues. Source content is treated as untrusted evidence, not instructions.

Read-only and field-selection rules are agent instructions, not an operating-system security boundary; this skill-only plugin has no separate permissions enforcement.

Keeping data outside this package avoids distributing the dataset with the plugin. Selected evidence still enters the Codex conversation. This is not an access-control system and does not protect data already published by the website. Roster composition does not establish recruiting openings, and historical relationships do not establish recruiting probabilities.

## Validation

Run the official validators using the installed system skills:

```text
python <plugin-creator>/scripts/validate_plugin.py plugins/collegedash-research
python <skill-creator>/scripts/quick_validate.py plugins/collegedash-research/skills/research
```

Evaluate the two Python projections in the [data guide](skills/research/references/data-guide.md) against the current checkout. Compare search and roster results to independent JSON calculations; check missing data rather than hardcoding snapshot counts.

Before accepting the MVP, also test a school comparison, club/high-school feeder question, unavailable checkout, and a missing section. Verify high-school commitment counts are reported as unavailable and that synthetic `curated`/`tags` values never appear in projected output. Confirm the plugin is discovered in a fresh Codex task after installation; schema validation alone does not establish runtime discovery or answer quality.
