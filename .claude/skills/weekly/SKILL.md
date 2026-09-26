---
name: weekly
description: Weekly routine that keeps the brain healthy — curator pass (duplicate entities, stale or contradicting facts, facts without source), lifecycle (Inbox captures older than 7 days → destinations, quiet projects → paused, done projects → archive, project knowledge → 40_Knowledge promotion), link review over the whole week including cross-note connections, project status refresh, the auto:portfolio block in the root CLAUDE.md, health check (bin/brain validate, doctor) and a friction roll-up from skill run logs into patch proposals. Every change is a numbered proposal applied after the user answers. Use when the user says "weekly", "weekly review", "close the week", "clean up the brain", "triage the inbox", "update the portfolio", "find duplicates", or /weekly.
model: opus
effort: high
---
# weekly

Rules in `CLAUDE.md` bind this skill. Run from the workspace; `BRAIN` = `bin/brain`. Scans are Glob/Grep/Read.
Chat and notes in `brain.config.json › language`. About 20 minutes, interactive: each section ends with its
numbered proposals; the user answers once per section (`1,3` · `all` · `none` · `-2` · `2: <edit>`).
Scope argument: default all sections; `quick` = 1, 2, 5, 7; a section name runs only that one.

## 0. Start
- Checkpoint: `git status --porcelain` dirty → `git add -A && git commit -qm "weekly: checkpoint"` (the CLI's
  `--apply` refuses files with foreign uncommitted changes). Never push; `/sync` does.
- Cursor = date of the newest `50_Raw/logs/weekly/*.md`, else 7 days ago. `BRAIN validate --json` → baseline
  error/warning counts.
- Carry over `pending` proposals from this week's `50_Raw/logs/morning/` logs; re-propose, do not duplicate.

## 1. Inbox triage
Captures in `00_Inbox/` with age (date prefix, else mtime). Read each (whole). Destination by the `CLAUDE.md` "where does it go" rules:
active project (score it as `/process-meetings` step 2.1) · area
(`30_Areas/<role>/<notes|decisions|meetings>/`) · person/org registry · `40_Knowledge/<namespace>/<topic>/` ·
`50_Raw/` for material kept as-is · stays (ask one question) · empty → propose deletion.
Table `N | file | age | destination | why (≤ 8 words)`. Apply with `BRAIN move <file> <dir> --apply` (set
`context:` when missing). Pending transcripts → one line "n transcripts waiting → /process-meetings".

## 2. Projects and lifecycle
Per `20_Projects/*/CLAUDE.md`: `status`, goal, last activity (newest of `updated:`, dated file names in the folder,
`git log -1 --format=%cs -- <folder>`), open `- [ ]` next steps (overdue = holding a date before today), newest
date in `auto:meetings`. Propose:
quiet ≥ 30 days → `status: paused` (ask first when a connected source might still be active) · `status: done`
or goal reached → archive (`BRAIN move 20_Projects/<slug> 99_Archives/ --apply`) · missing goal → ask for
one sentence · overdue steps → keep / re-date / drop · a note inside a project that would stay true after it ends
(a system, org, how-to) or is linked from ≥ 2 other projects/areas → promote (`BRAIN move <note>
40_Knowledge/<namespace>/<topic>/ --apply`; the project keeps a link). Unchecked Top 3 items from this week's
daily notes → carry into a project's next steps or drop.

## 3. Curator
- **Duplicates**: entity notes sharing a title or alias (case and diacritics ignored; `.claude/index.md` lists
  both) or an `email:` value, plus near-identical titles you notice →
  merge proposal `A ↔ B → keep A` (the loser's name goes to `aliases`, its facts move as lines, its links are
  retargeted with `BRAIN rename`/`move`; nothing is deleted without an explicit "yes").
- **Facts**: `grep -rnE '\^f-[0-9a-f]{6}'` outside `50_Raw/` and `99_Archives/`, struck-through lines skipped →
  no source/date after ` — ` (add from the note's history or invalidate), `low` confidence older than 180 days
  (verify or invalidate), the same fact twice in a note (drop the later copy), several facts of one category in a
  note (read them: contradictions become UPDATE proposals). Deltas only: old line `~~…~~ → replaced by ^f-<new>`, new line below;
  never rewrite a note.
- **Ended things**: entities with `valid_to` still linked → remove the edge from the frontmatter key by Edit and log
  `- <date> — ended: <rel> [[x]] (<source>)` under `## Log`.

## 4. Link review (the whole week)
- Unlinked mentions and orphans in notes changed since the cursor (method of `/morning` step 4, skipping items
  already answered there).
- **Cross-note connections**: read the week's changed notes side by side (group by project/area/person) and
  propose links a per-note scan misses: two notes about the same decision or system, a meeting that belongs to
  a project it does not link, a person who appears across several projects without a `stakeholders` edge, an
  idea that answers an open question elsewhere. One line each, with both paths and the reason.
- Once a month (first weekly of the month) the same orphan check over every note.

## 5. Portfolio
Table of `status: active` projects, ordered by context (`brain.config.json › contexts` order), then last activity:
`| project | context | goal |`, rows `| [[<slug>/CLAUDE\|<title>]] | <context> | <goal ≤ 110 chars, or (goal missing)> |`.
Show it; on "yes" replace only the `<!-- auto:portfolio start -->…<!-- auto:portfolio end -->` block in the root
`CLAUDE.md` (missing → append `## Portfolio` + the block).

## 6. Health
`BRAIN validate --json` (errors above the baseline → fix or revert the files this run touched with
`git checkout -- <files>`), `BRAIN doctor` (report warnings in one line each), `BRAIN context --write`.
Warnings that recur week after week become one proposal (fix the notes or adjust `brain.config.json`).

## 7. Friction roll-up
`## Friction` lines of every `50_Raw/logs/*/YYYY-MM-DD*.md` since the cursor (skip `none`), grouped when they say
the same thing. Anything seen ≥ 2× becomes a patch proposal `N. [patch] <SKILL.md or script> · change · why (n× friction)` with a unified diff.
Apply only after "yes"; then `bin/brain test` must stay green (revert the patch otherwise). Keep SKILL.md < 150 lines.

## 8. Log and close
- Run log `50_Raw/logs/weekly/YYYY-MM-DD-HHMM.md`: cursor, baseline → final validate counts, per section the
  counts and every proposal as `N. [kind] … — yes|no|edited|pending`, applied moves, then `## Friction`
  (one line each; `- none` if nothing). The answers are the memory: next week re-proposes only `pending` items and
  a rejected kind of proposal seen ≥ 2× becomes a rule suggestion for `CLAUDE.md`.
- Commit: `git add -A && git commit -qm "weekly: <date>"`.
- Section in today's daily note (create with `BRAIN create daily <date> --apply`): `## Weekly review`
  with ≤ 10 lines (moved, archived, paused, merged, links added, portfolio yes/no, open items).
- Chat: 1–3 suggestions for next week.

## Hard rules
- Nothing is moved, merged, archived, paused or deleted without a numbered "yes"; never `rm` outside an accepted
  deletion of an empty capture.
- Relation keys, `id`, `type`, `valid_*`, moves and renames only via `bin/brain`; text outside `auto:` blocks is
  the author's except accepted line deltas.
- `99_Archives/` is written to, never mined. No network except reading sources the user connected.
- Skills, scripts and `CLAUDE.md` change only via an accepted diff.
