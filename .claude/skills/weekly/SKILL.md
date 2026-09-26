---
name: weekly
description: Weekly routine that keeps the brain healthy — curator pass (duplicate entities, stale or contradicting facts, facts without source), lifecycle (Inbox captures older than 7 days → destinations, quiet projects → paused, done projects → archive, project knowledge → 40_Knowledge promotion), link review over the whole week including cross-note connections, project status refresh, the auto:portfolio block in the root CLAUDE.md, health check (bin/brain validate, doctor) and a friction roll-up from skill run logs into patch proposals. Every change is a numbered proposal applied after the user answers. Use when the user says "weekly", "weekly review", "close the week", "clean up the brain", "triage the inbox", "update the portfolio", "find duplicates", or /weekly.
model: opus
effort: high
---
# weekly

Rules in `CLAUDE.md` bind this skill. Run from the workspace; `BRAIN` = `bin/brain`,
`REVIEW` = `python3 .claude/skills/weekly/scripts/review.py` (read-only JSON scans; `--help`).
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
`REVIEW inbox` → captures with age. Read each (whole). Destination by the `CLAUDE.md` "where does it go" rules:
active project (`python3 .claude/skills/process-meetings/scripts/route.py <file>` scores it) · area
(`30_Areas/<role>/<notes|decisions|meetings>/`) · person/org registry · `40_Knowledge/<namespace>/<topic>/` ·
`50_Raw/` for material kept as-is · stays (ask one question) · empty → propose deletion.
Table `N | file | age | destination | why (≤ 8 words)`. Apply with `BRAIN move <file> <dir> --apply` (set
`context:` when missing). Pending transcripts → one line "n transcripts waiting → /process-meetings".

## 2. Projects and lifecycle
`REVIEW projects` → status, `days_quiet`, open and overdue next steps, goal, last meeting. Propose:
quiet ≥ 30 days → `status: paused` (ask first when a connected source might still be active) · `status: done`
or goal reached → archive (`BRAIN move 20_Projects/<slug> 99_Archives/ --apply`) · missing goal → ask for
one sentence · overdue steps → keep / re-date / drop · a note inside a project that would stay true after it ends
(a system, org, how-to) or is linked from ≥ 2 other projects/areas → promote (`BRAIN move <note>
40_Knowledge/<namespace>/<topic>/ --apply`; the project keeps a link). Unchecked Top 3 items from this week's
daily notes → carry into a project's next steps or drop.

## 3. Curator
- **Duplicates**: `REVIEW dupes` (same normalized title, alias or e-mail) plus near-identical titles you notice →
  merge proposal `A ↔ B → keep A` (the loser's name goes to `aliases`, its facts move as lines, its links are
  retargeted with `BRAIN rename`/`move`; nothing is deleted without an explicit "yes").
- **Facts**: `REVIEW facts` → `no_provenance` (add source/date from the note's history or invalidate),
  `low_confidence_old` (verify or invalidate), `repeated` (drop the later copy), `same_category` (read them:
  contradictions become UPDATE proposals). Deltas only: old line `~~…~~ → replaced by ^f-<new>`, new line below;
  never rewrite a note.
- **Ended things**: entities with `valid_to` still linked → `BRAIN unlink <note> --<rel> "[[x]]" --ended <date>`.

## 4. Link review (the whole week)
- `REVIEW links --since <cursor>` → unlinked mentions and orphans in notes changed this week (as in `/morning`
  step 4, skipping items already answered there).
- **Cross-note connections**: read the week's changed notes side by side (group by project/area/person) and
  propose links a per-note scan misses: two notes about the same decision or system, a meeting that belongs to
  a project it does not link, a person who appears across several projects without a `stakeholders` edge, an
  idea that answers an open question elsewhere. One line each, with both paths and the reason.
- `REVIEW links --all` once a month (first weekly of the month) for orphans across the vault.

## 5. Portfolio
`REVIEW portfolio` → the table of active projects; show it; on "yes" `REVIEW portfolio --write` (replaces only the
`<!-- auto:portfolio -->` block in the root `CLAUDE.md`; appends it with a heading when missing).
Also `BRAIN project --all --write` (diff) → `--apply` refreshes hub projections.

## 6. Health
`BRAIN validate --json` (errors above the baseline → fix or revert the files this run touched with
`git checkout -- <files>`), `BRAIN doctor` (report warnings in one line each), `BRAIN context --write`.
Warnings that recur week after week become one proposal (fix the notes or adjust `brain.config.json`).

## 7. Friction roll-up
`REVIEW friction --since <cursor>` → Friction lines of all skill run logs, grouped. Anything with `count ≥ 2`
becomes a patch proposal `N. [patch] <SKILL.md or script> · change · why (n× friction)` with a unified diff.
Apply only after "yes"; then `bin/brain test` must stay green (revert the patch otherwise). Keep SKILL.md < 150 lines.

## 8. Log and close
- Run log `50_Raw/logs/weekly/YYYY-MM-DD-HHMM.md`: cursor, baseline → final validate counts, per section the
  counts and every proposal as `N. [kind] … — yes|no|edited|pending`, applied moves, then `## Friction`
  (one line each; `- none` if nothing). The answers are the memory: next week re-proposes only `pending` items and
  a rejected kind of proposal seen ≥ 2× becomes a rule suggestion for `CLAUDE.md`.
- Commit: `git add -A && git commit -qm "weekly: <date>"`.
- Section in today's daily note (create with `python3 .claude/skills/morning/scripts/daily.py`): `## Weekly review`
  with ≤ 10 lines (moved, archived, paused, merged, links added, portfolio yes/no, open items).
- Chat: 1–3 suggestions for next week.

## Hard rules
- Nothing is moved, merged, archived, paused or deleted without a numbered "yes"; never `rm` outside an accepted
  deletion of an empty capture.
- Relation keys, `id`, `type`, `valid_*`, moves and renames only via `bin/brain`; text outside `auto:` blocks is
  the author's except accepted line deltas.
- `99_Archives/` is written to, never mined. No network except reading sources the user connected.
- Skills, scripts and `CLAUDE.md` change only via an accepted diff.
