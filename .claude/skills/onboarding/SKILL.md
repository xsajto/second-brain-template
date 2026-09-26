---
name: onboarding
description: First run and later re-tuning of the second brain for a ModernTV colleague who cloned the template. Detaches the clone from the template (deletes .git after confirmation, fresh git init), checks the install (brew, python3 ≥ 3.10, git, gog, MCP servers, hooks, bin/brain doctor), interviews the user (who they are, work e-mail, roles → contexts and areas, note language, task manager), writes brain.config.json, creates the folders, area hubs and the user's person note with bin/brain, fully connects Google (gog: install, OAuth client, auth, verification read) and the company connectors (Slack, Jira/Confluence, Asana, optional GitLab/GitHub/Grafana) each with one verification read, offers to schedule /morning and /weekly, and ends with a short tour. `--check` = read-only install report. Idempotent — a re-run reviews and adjusts. Use when the user says "onboarding", "set up my brain", "nastav brain", "první spuštění", "get started", "connect my calendar", "připoj kalendář/Slack/Jiru", "zkontroluj instalaci", or /onboarding [--check].
model: opus
effort: high
---
# onboarding

Rules in `CLAUDE.md` bind this skill. Run from the repo root; `BRAIN` = `bin/brain`.
Chat with the user in **Czech** (switch only if they write in another language); this file is English.
One question at a time, short, with a numbered default the user can accept with "ok". Nothing is written,
deleted or installed before the user confirms it in chat.

## Arguments
- `--check` — read-only install report (`references/setup.md` › Install check): table + numbered fixes, applies
  nothing. Stop after it.
- none — first run (steps 1–10) or re-run (step 0).

## 0. Detect state
`BRAIN doctor`, `cat brain.config.json` (missing = first run), `git remote -v`.
**Re-run** → 10-line summary of the config and the install check, then ask what to change (numbered:
1 profile · 2 contexts/areas · 3 language · 4 task manager · 5 Google · 6 company connectors · 7 routines ·
8 nothing) and run only those steps. Existing notes and folders are never deleted or renamed here; a changed
folder name is a `BRAIN move|rename` proposal.

## 1. Detach from the template
`references/setup.md` › Detach. Show exactly what `rm -rf .git` deletes (commits, size, remote), wait for "ano",
then fresh `git init` + first commit. Skip when there is no template remote. Post-condition: no remote, 1 commit.

## 2. Install check
Run the install check table; offer numbered fixes for `missing` rows (brew installs after "ano"; brew itself and
anything needing the user's password the user runs with `! <command>`). Re-check each fixed row.

## 3. Interview (≤ 8 questions)
1. Name, role, team at ModernTV (→ `user.name`, `user.role`, `user.org` = "ModernTV").
2. Work e-mail (→ `user.email`; the Google and Atlassian identity).
3. Contexts: default `work` (slug `mtv`) + `private` (slug `priv`); more only if the user wants them.
4. Per context the roles (standing responsibilities, e.g. "Vývoj backendu", "Podpora zákazníků", "Domácnost")
   → `30_Areas/<kebab>/`; the first is the context's `primary_area`.
5. Active projects now (a goal with an end) — names only.
6. Note language: default `cs` with Czech `weekdays` (Pondělí … Neděle); folder names stay the English defaults.
7. Task manager per context: `none` | Asana (default for `work`) | Jira | Linear | other. Tasks are created only
   on explicit request.
8. One or two roots: default one; two only when the user wants work and private strictly apart.

## 4. Write the config
Show the full JSON (keys as in `brain.config.example.json`, omit defaults), ask `1) zapsat 2) změnit 3) zrušit`.
On 1 write `brain.config.json`; `BRAIN doctor` must show no config problem.

## 5. Skeleton
- `mkdir -p` the seven numbered folders (per root) + `00_Inbox/meetings` + `50_Raw/logs`.
- Per role `BRAIN create area "<Role>" --context <ctx>` (dry run, show) then `--apply`; `primary: true` on the
  primary one (plain Edit of that key).
- `BRAIN create person "<Name>" --context work --apply`, then fill `role`, `org`, `email`, `aliases`, `me: true`.
- Named projects: `BRAIN create project "<Title>" --context <ctx> --area "<Role>" --apply`, one confirmed goal
  sentence each.
- `BRAIN validate` passes; `BRAIN context --write`. Commit: `git add -A && git commit -qm "Onboarding: kostra"`.

## 6. Google (gog) — full setup
`references/connectors.md` › Google: install, OAuth client, `gog auth add` (read-only scopes), verification read
of today's calendar, `integrations.google` + `user.email` in the config.

## 7. Company connectors
`references/connectors.md` › Company connectors: `claude mcp list` first; Slack and Jira/Confluence from the
project `.mcp.json` (approve, `/mcp` → Authenticate) or claude.ai connectors; Asana; optional GitLab, GitHub,
Grafana. One verification read each, then one confirmation to write all `integrations` entries.
Existing notes elsewhere (Confluence pages, old docs) are not imported; the user can paste a brain dump into
`/new-project` or `00_Inbox/` later.

## 8. Routines
`/morning` (daily, ~2 min) and `/weekly` (Friday, ~20 min). Offer `/schedule` (cloud routines need a git remote
and `/sync`; without one the user runs them by hand). Show the exact schedule, create only after "ano".
No cron, launchd or background hooks.

## 9. Tour (≤ 12 Czech lines)
`/morning`, `/weekly`, `/process-meetings`, `/new-project`, `/research`, `/people`, `/correct`, `/sync`,
`/onboarding` (re-tune, `--check`) — one line each; then: capture into `00_Inbox/`, transcripts into
`00_Inbox/meetings/`, open the folder in Obsidian, answer proposals by number.

## 10. Log
`50_Raw/logs/onboarding/YYYY-MM-DD-HHMM.md`: detach result, install check table, answers summary (no secrets),
config diff, notes created, connectors connected / skipped / failed (`⚠ <name>: <what was tried>`), proposals with
answers (`— yes|no|edited|pending`), routines, then `## Friction` (one line each, `- none` if nothing).

## Hard rules
- `rm -rf .git` only in the repo root, only after "ano" to the exact summary, never when a non-template remote
  exists without the user saying it is disposable.
- Never print or store a secret: tokens are entered by the user in their own terminal; client JSON contents are
  never read or echoed.
- Connector calls here are reads; no Slack/Jira/Asana/mail writes.
- Never invent a person, project or source. A failed connection is named with its fix.
- Structural writes only through `bin/brain` (dry run, then `--apply`); `BRAIN validate` passes at the end.
