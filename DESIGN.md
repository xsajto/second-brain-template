# second-brain — design (v0.1)

Open-source boilerplate for an agent-run second brain in Claude Code + Obsidian.
Source of truth for contributors and agents building this repo. **Less is more.**

## Install flow
1. User clones the repo (or gives the URL to Claude Code) and opens Claude Code in it.
2. Agent reads `CLAUDE.md`, runs `bin/brain doctor`, and suggests `/onboarding`.
3. Onboarding interviews the user and writes `brain.config.json` + the first notes (see below).
4. Two routines keep it alive: `/morning` (daily) and `/weekly`.

## Hard rules for this repo
- No personal data of the author or anyone else: no names, e-mails, companies, IDs (Slack, Asana, Linear…),
  bucket names, hostnames, home-directory paths, cloud-drive paths, tokens. Examples use fictional data
  (Ada Example, Acme Corp, `example.com`).
- Nothing author-specific: no company infrastructure skills, no vendor wrappers for one company's tools.
  Integrations are optional and generic (Google via `gog`, Slack/Linear/Notion/Jira via MCP the user connects).
- Code, docs, SKILL.md, templates and default folder names in **English**. Note language is a config value
  (`language`, default `en`); skills write notes in that language.
- Python 3.10+ stdlib only. Tests: `bin/brain test` (stdlib unittest on a temp fixture vault).

## Layout of the repo = layout of a fresh vault
```
CLAUDE.md                 agent rules (generic, short) — loaded by Claude Code
README.md                 human quickstart
brain.config.json         created by onboarding (brain.config.example.json ships)
.claude/                  settings.json (SessionStart/PostToolUse hooks → bin/brain context)
bin/                      brain (CLI entry), brainkg.py, context.py
lib/                      paths.py, vault.py, schema.json, config.py
.claude/skills/<name>/    project skills (SKILL.md + scripts/) — load automatically, no plugin install
tests/                    unittest suite + fixture builder
templates/                note templates
docs/                     short human docs (how it works, conventions, routines)
00_Inbox/ 10_Daily/ 20_Projects/ 30_Areas/ 40_Knowledge/ 50_Raw/ 99_Archives/   (created by onboarding; .gitkeep only)
```
Single root by default. Multi-root (e.g. work + private) is an onboarding option: `roots` in config.

## Config (`brain.config.json`, read by lib/config.py; every key optional with defaults)
```json
{
  "user": {"name": "", "role": "", "org": ""},
  "language": "en",
  "roots": {".": {"contexts": ["work", "private"]}},
  "contexts": {"work": {"slug": "work", "primary_area": "30_Areas/work"},
               "private": {"slug": "priv", "primary_area": "30_Areas/private"}},
  "folders": {"people": "40_Knowledge/people", "orgs": "40_Knowledge/orgs",
              "meetings": "meetings", "decisions": "decisions", "notes": "notes",
              "outputs": "outputs", "sources": "sources", "ideas": "ideas",
              "reports": "50_Raw/reports", "relationship_map": "relationship-map.md"},
  "vendor_dirs": [],
  "task_manager": {"default": "none"},
  "integrations": {}
}
```
Everything that was hard-coded for one person (contexts, roots, project slug prefixes, Czech folder names,
vendor dirs) comes from config. The author's own vault must be able to run on this engine with a config
that sets Czech folder names — keep names configurable, never assume English in code.

## Skills (`.claude/skills/`, invoked as `/<name>`) — the whole surface
| skill | what |
|---|---|
| `onboarding` | interview (who, where they work, roles→contexts/areas, language, task manager), write config, create folders + first notes (person note for the user, areas, active projects), connect optional sources (Google, Slack, task manager, meeting transcripts) — each optional, import from past Claude Code sessions (`~/.claude/projects/*/…jsonl`) into people/projects/knowledge proposals, schedule the two routines (`/schedule`), explain slash commands |
| `morning` | daily: calendar + sources + Inbox + open Top 3 → daily note; light curator pass on yesterday's changes incl. **link review** of new/changed files (propose missing wikilinks/relations, orphans) |
| `weekly` | weekly: curator (dedup, stale facts, lifecycle, promotion), link review over the week, inbox triage, project status refresh, portfolio block, health check |
| `process-meetings` | transcripts in `00_Inbox/meetings/` → meeting notes routed to project/area |
| `research` | options comparison into `40_Knowledge/research/<date-slug>/` |
| `new-project` | brain dump → project folder with CLAUDE.md |
| `people` | person notes + relationship map from communication the user is part of |
| `correct` | correction sweep for one wrong fact |
| `sync` | git commit/pull/push of the vault |
All proposals are numbered and applied after the user says yes. No background automation except
the user-scheduled routines.

## Engine facts (from phase 1)
- CLI: `bin/brain validate|context|create|move|rename|doctor|test`; everything else is SKILL.md instructions
  executed with Glob/Grep/Read/Edit/git.
- `brain create` reads `templates/{person,project-claude,area-hub,meeting-note,decision,daily,system,org,concept}.md`
  with `{{PLACEHOLDERS}}`; missing template → built-in stub.
- Config lookup: `$BRAIN_CONFIG` → `$BRAIN_WORKSPACE` → nearest folder with `brain.config.json`. Git = the repo holding
  the vault (`$BRAIN_GIT_DIR` for a separate git dir).
- Run logs of skills: `50_Raw/logs/<skill>/YYYY-MM-DD-HHMM.md` (hot.md reads them for proposal triggers).
