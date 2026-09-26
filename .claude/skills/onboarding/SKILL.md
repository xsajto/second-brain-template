---
name: onboarding
description: First-run setup and later re-tuning of the second brain. Interviews the user (who they are, where they work, roles → contexts and areas, one or two roots, note language, task manager), writes brain.config.json, creates the folders, area hubs and the user's own person note with bin/brain, connects optional sources (Google via gog, Slack/Linear/Notion/Jira/GitHub via MCP, a transcripts folder), imports people, projects, areas and knowledge from past Claude Code sessions as numbered proposals, schedules /morning and /weekly, and ends with a short tour. Idempotent — a re-run reviews and adjusts. Use when the user says "onboarding", "set up my brain", "get started", "first run", "configure the brain", "connect my calendar", "import my old sessions", "change my contexts/areas", or /onboarding.
model: opus
effort: high
---
# onboarding

Rules in `CLAUDE.md` bind this skill. Run from the workspace (the repo); `BRAIN` = `bin/brain`.
Speak the user's language from their first message; this file is English. One question at a time, short,
with a numbered default the user can accept with "ok". Never write before the user confirms a summary.

## 0. Detect state
- `BRAIN doctor` and `cat brain.config.json` (missing = first run).
- **First run** → steps 1–8. **Re-run** → show the current config as a 10-line summary, ask what to change
  (numbered: 1 profile · 2 contexts/areas · 3 roots · 4 language · 5 task manager · 6 sources · 7 import sessions
  · 8 routines · 9 nothing), run only the chosen steps. Existing notes and folders are never deleted or renamed
  here; a changed folder name is a `BRAIN move|rename` proposal.

## 1. Interview (≤ 8 questions)
1. Name, role, organisation (→ `user`). Offer to skip the organisation.
2. Life areas the brain should cover → **contexts** (default `work` + `private`; examples: `work`, `client-acme`,
   `private`, `side-business`, `volunteering`). Each context gets a kebab `slug` = project prefix (`work-`, `priv-`).
3. Per context the **roles** (areas of responsibility with no end date, e.g. "Engineering lead", "Home", "Finances")
   → `30_Areas/<kebab>/`; the first one is the context's `primary_area` (holds its standing sources and the
   relationship map).
4. Active projects right now (a goal with an end) — names only; details come from `/new-project` later.
5. **Roots**: one vault (default) or two (e.g. `work/` and `home/`, each with its own numbered folders — only
   when the user wants work and private strictly apart). Two roots → `roots: {"work": {"contexts": [...]}, ...}`.
6. **Note language** (`language`, ISO code, default = the interview language) and weekday names in that language
   (`weekdays`, Monday first) when not English.
7. **Task manager** per context: `none` | Linear | Jira | Todoist | GitHub Issues | other
   (`task_manager: {"default": "...", "<context>": "..."}`). The brain only creates tasks on explicit request.
8. Folder names: keep the English defaults unless the user asks (then fill `folders` from
   `brain.config.example.json`; values stay ascii kebab-case).

## 2. Write the config
Show the full JSON (keys as in `brain.config.example.json`; omit keys equal to the defaults) and ask
`1) write  2) change (say what)  3) cancel`. On 1 write `brain.config.json`, then `BRAIN doctor` must show no
config problem (it runs `config.check`). Fix and re-show on any problem.

## 3. Create the skeleton
- Folders: `mkdir -p` the seven numbered folders (per root) plus `00_Inbox/meetings` and `50_Raw/logs`.
- Areas: per role `BRAIN create area "<Role>" --context <ctx>` (dry run, show), then `--apply`. Mark the primary
  one with `primary: true` in its frontmatter (plain Edit of that one key).
- The user's person note: `BRAIN create person "<Name>" --context <ctx> --apply`, then fill `role`, `org`,
  `aliases` (nicknames) and add `me: true` so skills know who "I" is.
- Projects named in step 1.4: one `BRAIN create project "<Title>" --context <ctx> --area "<Role>" --apply` each,
  with a one-sentence goal the user confirms (`/new-project` enriches it later).
- `BRAIN validate` must pass; `BRAIN context --write` refreshes `.claude/index.md`.

## 4. Connect sources (each optional; skip = recorded, never nagged)
Ask per source whether the user has it; record the answer in `integrations` (config) as
`{"<name>": {...settings, "morning": "<what /morning checks there>"}}`. A source the user skips is simply absent.
- **Google calendar + mail** (`gog` CLI): check `command -v gog`; missing → `brew install gogcli` (or the
  project's release binary). Auth: `gog auth add <email>` opens the browser; verify with
  `gog calendar events --from today --to tomorrow` (see `gog --help` if flags differ). Store
  `"google": {"accounts": {"<context>": "<email>"}}`.
- **Slack, Linear, Notion, Jira/Confluence, GitHub** via MCP: explain `/mcp` (Claude Code's menu to add and
  authenticate MCP servers; official servers are listed in the Claude Code docs) or `claude mcp add`. After the
  user connects one, load its tools with ToolSearch and make one read call to verify. Store
  `"slack": {"mcp": "<server name>", "morning": "DMs and mentions since the last run"}`. GitHub may use `gh` instead.
- **Meeting transcripts**: any tool that exports text (`.md`, `.txt`, `.vtt`). Ask for the export folder;
  store `"transcripts": {"dir": "<path>"}`. `/process-meetings` picks files up from there and `00_Inbox/meetings/`.
- Write the updated config after one confirmation for the whole step.

## 5. Import from past Claude Code sessions (optional)
- `python3 .claude/skills/onboarding/scripts/sessions.py --list` → numbered table (working dir, sessions, dates,
  size). Ask which ones to read (`1,4`, `all`, `none`). Never read unapproved folders.
- Per approved folder: `sessions.py --extract <folder> --since <date> --out <scratchpad>/<n>.txt`; large sets →
  one subagent per folder (`model: sonnet`, read-only), given the file path and the task below, returning ≤ 30
  lines. Never paste transcripts into notes.
- Extract candidates: **people** (name, role, org, how the user works with them), **projects** (goal, status,
  people, repo/links), **areas** (recurring responsibilities), **knowledge** (systems, decisions, how-tos worth
  keeping), each with its evidence `session <id-prefix>, YYYY-MM-DD`.
- Match against the vault first (`BRAIN find --text "<name>"`); existing → a fact line proposal, not a new note.
- One numbered table: `N. [person|project|area|knowledge|fact] title → destination (evidence)`. Answers as below.
  Apply with `BRAIN create … --apply` (+ facts as `- [category] fact — source, YYYY-MM-DD ^f-<6hex>` under `## Facts`).
- Secrets, tokens, customer data and anything personal about third parties that is not work-relevant are skipped.

## 6. Routines
Explain: `/morning` (daily briefing + link review, ~2 min) and `/weekly` (curation, lifecycle, portfolio,
health, ~20 min). Offer to schedule them with Claude Code's `/schedule` (routines run as cloud agents on the vault's
git remote, so they need `/sync` set up first; without a remote the user runs them by hand). Show the exact
schedule (e.g. weekdays 07:30, Friday 15:00, local time zone) and create it only after "yes". No cron, launchd or
background hooks.

## 7. Tour (≤ 12 lines)
`/morning`, `/weekly`, `/process-meetings`, `/new-project`, `/research`, `/people`, `/correct`, `/sync`,
`/onboarding` (re-tune) — one line each; then daily use: capture anything into `00_Inbox/`, drop transcripts
into `00_Inbox/meetings/`, open the vault folder in Obsidian, answer proposals by number.

## 8. Log
Run log `50_Raw/logs/onboarding/YYYY-MM-DD-HHMM.md`: answers summary (no secrets), config diff, notes created,
sources connected / skipped / failed (`⚠ <source>: <what was tried>`), import stats, proposals with answers
(`— yes|no|edited|pending`), routines scheduled, then `## Friction` (one line each, `- none` if nothing).

## Proposals
Numbered, one line each; the user answers `1,3` · `all` · `none` · `-2` (reject) · `2: <edit>`. Nothing is
created before the answer; unanswered items stay `pending` in the run log.

## Hard rules
- No personal data leaves the machine; MCP and `gog` calls are reads, except what the user explicitly asks.
- Never invent a person, project or source. A failed connection is named with the fix, never hidden.
- Structural writes only through `bin/brain` (dry run, then `--apply`); `brain validate` passes at the end.
