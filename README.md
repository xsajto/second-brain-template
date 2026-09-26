# second-brain

An open-source boilerplate for an agent-run second brain: Claude Code reads and writes a vault of plain
Markdown notes on your behalf, Obsidian gives you a human view of the same files, and a small Python
stdlib CLI (`bin/brain`) keeps the graph consistent. No server, no database, no proprietary format — the
notes are the product.

```
capture                 process                      routines                     knowledge
--------                -------                       --------                    ---------
Inbox / Daily  ----->  process-meetings / curator  ----->  /morning, /weekly  ----->  40_Knowledge/
   ^                                                                                       |
   |                                                                                       |
   +---------------------------------------------------------------------------------------+
                              (notes and routines feed back into daily use)
```

## Requirements

- [Claude Code](https://claude.com/claude-code)
- Python 3.10+ (stdlib only — no packages to install)
- git
- Optional: [Obsidian](https://obsidian.md) for graph view and a daily-notes UI
- Optional: a Google CLI (e.g. `gog`) or MCP servers for calendar, mail, Slack, or a task manager — every
  integration is opt-in and configured during onboarding

## Install

```
git clone <this repo>
cd second-brain
claude   # open Claude Code in this folder
```

Then run `/onboarding`. It interviews you (who you are, your roles/contexts, note language, task manager),
writes `brain.config.json`, creates the folder structure and your first notes, and optionally connects
sources and schedules the daily/weekly routines.

## Daily use

- `/morning` — daily brief: calendar + configured sources + Inbox + your open Top 3, written to today's
  daily note, plus a light link review of yesterday's changes.
- `/weekly` — weekly review: dedup and stale-fact pass, link review over the week, inbox triage, project
  status refresh, portfolio update, health check.

Other skills trigger as needed:

- `/process-meetings` — when a transcript lands in `00_Inbox/meetings/`, turns it into a routed meeting note.
- `/research` — for an options comparison, written to `40_Knowledge/research/<date-slug>/`.
- `/new-project` — turns a brain dump into a project folder with a `CLAUDE.md`.
- `/people` — maintains person notes and the relationship map from your communication.
- `/correct` — sweeps the vault to fix one wrong fact everywhere it was restated.
- `/sync` — commits, pulls and pushes the vault (this repo is the git repo).

## Folder layout

```
00_Inbox/       unprocessed captures only
10_Daily/       one note per day
20_Projects/    temporary efforts with an end date (<slug>/CLAUDE.md)
30_Areas/       standing responsibilities / roles (<role>/<role>-hub.md)
40_Knowledge/   the wiki: people/orgs registries + namespace/topic folders
50_Raw/         material you did not author, kept as-is
99_Archives/    finished projects and old material
bin/            brain (CLI entry), brainkg.py (graph commands), context.py (agent context + hooks)
lib/            paths.py, vault.py, schema.json, config.py
tests/          unittest suite + fixture builder (bin/brain test)
templates/      note templates ({{PLACEHOLDER}} filled by `brain create`)
docs/           short human docs: how it works, conventions, routines
.claude/skills/ project skills (SKILL.md + scripts/) — load automatically, no plugin install
```

## Config reference (`brain.config.json`)

Every key is optional; a missing file means the defaults below apply. See `brain.config.example.json` for
a filled-in example and `lib/config.py` for the authoritative defaults.

| key | meaning | default |
|---|---|---|
| `user.name`, `user.role`, `user.org` | who the vault belongs to, for templates and prose | `""` each |
| `language` | language skills write notes in | `en` |
| `roots` | root path (relative to the workspace) → which contexts live there; `"."` = the workspace itself | `{".": {}}` (one root, every context) |
| `contexts` | context name → `slug` (project folder prefix), `primary_area` (standing sources, relationship map), `namespace` (its `40_Knowledge/` folder) | `work` and `private`, each with a matching slug/area/namespace |
| `folders.people` | global registry of person notes | `40_Knowledge/people` |
| `folders.orgs` | global registry of org notes | `40_Knowledge/orgs` |
| `folders.meetings` | meeting-notes subfolder of a project/area | `meetings` |
| `folders.decisions` | decision-records subfolder of a project/area | `decisions` |
| `folders.notes` | working-notes subfolder of a project/area | `notes` |
| `folders.outputs` | deliverables subfolder of a project | `outputs` |
| `folders.sources` | raw-material subfolder of a project, kept as-is | `sources` |
| `folders.ideas` | folder name (anywhere below `40_Knowledge/`) that holds ideas | `ideas` |
| `folders.reports` | generated reports folder | `50_Raw/reports` |
| `folders.relationship_map` | relationship-map file name inside a primary area | `relationship-map.md` |
| `folders.templates` | note templates folder (workspace level) | `templates` |
| `folders.system_docs` | human docs folder (workspace level, not notes) | `docs` |
| `shared_namespace` | `40_Knowledge/` namespace for knowledge owned by no single context | `shared` |
| `flat_knowledge` | `40_Knowledge/` folders always listed in full in `index.md` (never collapsed) | `[]` |
| `vendor_dirs` | bulk reference folders kept out of `index.md` and `find --text` | `[]` |
| `companions` | extra file names allowed next to subfolders (branch/leaf rule) | `[]` |
| `system_dirs` | root folders that hold no notes | `["bin", "lib", "tests", "templates", "docs", "plugins"]` |
| `labels` | type → plural label override for projections (note language) | `{}` |
| `weekdays` | weekday names, for note language | English names |
| `stopwords` | extra words `brain find --text` ignores | `[]` |
| `pending_marker` | word ending a run-log line that marks a proposal awaiting an answer | `pending` |
| `task_manager` | default task manager integration | `{"default": "none"}` |
| `integrations` | optional external tool configuration | `{}` |

## FAQ

**Can I run more than one vault (e.g. work and private)?** Yes — set `roots` in `brain.config.json` to map
each root path to the contexts that live there, and give each context its own `slug`, `primary_area` and
`namespace` under `contexts`. A single root with several contexts also works.

**What language are notes written in?** Whatever `language` is set to; skills write notes (and folder
prose) in that language. Folder and file names stay ascii kebab-case regardless.

**How do I sync across machines?** This repo is the git repo for your vault. Run `/sync`, or the plain git
commands yourself (`git add`, `git commit`, `git pull --rebase`, `git push`).

**Is this safe to make public?** The engine (`bin/`, `lib/`, `tests/`, `templates/`) is meant to be shared.
Your notes may not be. `.gitignore` ships with a commented-out block listing `brain.config.json` and the
numbered vault folders — uncomment it if you want a public repo with your own notes kept local-only.
