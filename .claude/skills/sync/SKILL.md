---
name: sync
description: Git sync of the vault — show status, commit local changes, pull --rebase and push to the user's private remote, resolve a rebase conflict note by note, and connect a vault to a new remote or a second machine. Use when the user says "sync", "sync the brain", "push the vault", "commit my notes", "is everything pushed", "merge conflict in the brain", "set up the remote", "new machine", or /sync [status|now|conflict|init <remote>].
model: haiku
effort: low
---
# sync

Rules in `CLAUDE.md` bind this skill. Run from the workspace. `G` = `git` (or
`git --git-dir "$BRAIN_GIT_DIR" --work-tree .` when `BRAIN_GIT_DIR` is set: a git dir kept outside a synced
folder). Chat in `brain.config.json › language`; output ≤ 5 lines.

## Arguments
- `status` (default when the user only asks): `G status --short | head -20`, `G fetch -q` then
  `G rev-list --left-right --count HEAD...@{u}` → ahead/behind; a rebase in progress → say so.
- `now`: before committing, scan `G status --porcelain` for secrets (`.env`, `*.pem`, `*token*`, `*secret*`,
  `settings.local.json`) and large media (> 20 MB) → stop and ask. Then `G add -A && G commit -qm "sync: <host>
  <YYYY-MM-DD HH:MM>"` (skip when clean), `G pull --rebase -q`, `G push -q`. Offline → "will retry", not an error.
  Post-condition: `G rev-parse HEAD` equals `G rev-parse @{u}`.
- `conflict`: see below.
- `init <remote>`: the user creates an empty **private** repository first (GitHub, GitLab, any git host). No git
  yet → `G init -b main`; then `G remote add origin <remote>` (existing origin → show it and ask),
  `G add -A && G commit -qm "vault: initial"`, `G push -u origin main`. A second machine with a copy of the
  folder: `G init -b main`, `G remote add origin <remote>`, `G fetch`, `G reset --soft origin/main` (keeps every
  local file; the next `now` commits the local differences). Confirm `.gitignore` covers `brain.config.json`
  only if the user wants it private per machine (default: committed).
- Routines scheduled with `/schedule` run on the remote copy: they need `init` done and push their own commits.

## Conflict
1. `G diff --name-only --diff-filter=U` → conflicted files.
2. Per file show both sides in ≤ 10 lines each (ours = this machine, theirs = remote). Notes are prose: keep
   **both** when they are different sections, the newer when it is the same `auto:` block (it is regenerated
   anyway), ask when the same paragraph differs. Daily notes: keep both, oldest first. Run logs: keep both.
3. `G add <file>`, `G rebase --continue`; then `G push`.
4. In doubt → `G rebase --abort` and report. Never `push --force`, never `reset --hard`, never rewrite history.

## Log
Run log `50_Raw/logs/sync/YYYY-MM-DD-HHMM.md`, written **before** the commit of `now` so it travels with it:
command, files changed (count), secrets check result, then `## Friction` (`- none` if nothing). A failed push or
an unresolved conflict is appended to that log afterwards and gets one line under `## Log` of today's daily
note (`- /sync: conflict in <files>, left for the user`); both are committed by the next sync.

## Hard rules
- The remote is the user's private repository; never add another remote or change visibility.
- A secret in `git status` stops the sync before any commit.
- Only branch `main` (or the branch already checked out); no force pushes, no history rewrites.
