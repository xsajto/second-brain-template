---
name: process-meetings
description: Turns meeting transcripts into meeting notes routed to the right project, area ritual or person — collects unprocessed transcripts from 00_Inbox/meetings/ and the configured transcripts folder (any tool that exports .md/.txt/.vtt), scores each against active projects (keywords, stakeholders, title), writes a meeting note with summary, decisions and action items, checks every number, date and quote against the transcript, updates the project's CLAUDE.md, archives the verbatim transcript in 50_Raw/meetings/. Use when the user says "process meetings", "process transcripts", "what happened in the meeting", "route this transcript", "meeting notes", or /process-meetings [file].
model: sonnet
effort: medium
---
# process-meetings

Rules in `CLAUDE.md` bind this skill. Run from the workspace; `BRAIN` = `bin/brain`,
`CHECK` = `python3 .claude/skills/process-meetings/scripts/check_evidence.py`.
Notes and chat in `brain.config.json › language`. Idempotent: a transcript with `processed: true` or already in
`50_Raw/meetings/` is skipped.

## 1. Collect
- `00_Inbox/meetings/*.{md,txt,vtt}` without `processed: true`.
- `integrations.transcripts.dir` (config), when set: files newer than the newest `processed_at` in
  `50_Raw/meetings/` → copy (not move) each into `00_Inbox/meetings/YYYY-MM-DD-<kebab-title>-transcript.md` with
  frontmatter `title`, `date`, `source: <tool or file>`, `source_id: <original path>`, `attendees: [...]`
  (when the export lists them), `processed: false`, then the text **verbatim** (speaker labels kept).
- MCP meeting tools the user connected (Notion, Google Drive notes …): same shape, full transcript paged to the
  end; only a summary available → frontmatter `transcript: summary-only` and a `GAP:` line in the report.
- A missing source is one line `⚠ <source>: <what was tried>`; never fatal. `[file]` argument = only that file.
- More than 5 candidates → table (file · predicted route · score) and ask once "process all n?".

## 2. Per transcript (oldest first)
1. **Route** (case- and diacritics-insensitive, by hand): a note with `meeting_match:` (`grep -rl
   "^meeting_match:" 20_Projects 30_Areas <people folder>`) whose string occurs in the meeting title wins (longest
   match; a tie → ambiguous). Else score each `20_Projects/*/CLAUDE.md` with `status: active` against title, text
   and attendees: +3 slug or title named, +2 per `keywords` hit, +1 per keyword in the title, +2 per
   `stakeholders` person named, +1 same context. Winner needs ≥ 4 and a lead ≥ 2, else ambiguous. `target`:
   `20_Projects/<slug>/` (flat) or `…/<meetings folder>/` (branch project), the ritual note, or
   `00_Inbox/meetings/` when ambiguous; keep the top scores as `candidates`. A transcript that belongs to
   another root (multi-root vault) → propose moving it to that root's `00_Inbox/meetings/`, skip.
2. **Extract** (read the transcript once): summary 3–5 sentences, decisions (explicit outcomes only), action
   items `- [ ] **who** — what — due` (the user's own first; the user = the person note with `me: true`), open
   questions, attendees. Unclear owner or date → open question, never a guess.
3. **Project route**: `BRAIN create meeting "<Title>" --project <slug>` (dry run) shows the note; the CLI dates
   it today, so for an older meeting write that same content at `<target><meeting date>-<kebab title>.md` with
   `id: meeting/<that stem>` and run `BRAIN validate --file <it>`; else `--apply`. Fill the template's sections.
   Attendees that equal exactly one person's title, alias or e-mail → `"[[person]]"` in the note's
   `attendees:` frontmatter; others become person proposals. Then the project's `CLAUDE.md`: new decisions under
   `## Decisions` (`- YYYY-MM-DD — decision`), the user's action items under `## Next steps` (deduplicated), and
   inside `## Status` (blocks created there when missing) one line in `<!-- auto:meetings -->`
   (`- YYYY-MM-DD [[note|Title]] — one line`) and `<!-- auto:status -->` rewritten in 3 lines (where it stands ·
   next · blocker); `updated:` today. Nothing else in the file changes.
4. **Ritual/person route**: append a `### YYYY-MM-DD <title>` section to that note with summary, decisions, action
   items; items that clearly belong to an active project also go to its next steps.
5. **Ambiguous**: leave the file, set `routing: ambiguous`, `candidates: [...]`; ask at the end.
6. **Grounding**: `CHECK <note> --source <transcript> [--section "### YYYY-MM-DD"]`. Every `MISSING` claim →
   re-read that part of the transcript and fix, remove or mark it `(unverified)`; re-run until exit 0. Keep the
   summary line for the report; a MISSING that needed fixing = one Friction line.
7. **Archive**: transcript frontmatter `processed: true`, `processed_at: <today>`, `processed_to: "<note path>"`
   (plain string), a body line `Meeting note: [[note]]`, then `BRAIN move <file> 50_Raw/meetings/YYYY/ --apply`.
   The transcript text is never edited or summarised.

## 3. Report and log
Chat (≤ 15 lines): table `transcript | routed to | decisions | my items`, new action items for the user,
ambiguous ones as numbered questions (`1. <title> — candidates: a (5), b (4) → answer with a number or slug`),
grounding totals, gaps. On an answer, process that transcript with the chosen target (step 2.3–2.7).
Run log `50_Raw/logs/process-meetings/YYYY-MM-DD-HHMM.md`: sources and gaps, one line per transcript (route,
grounding summary), proposals as `N. … — yes|no|pending`, then `## Friction` (`- none` if nothing).
One line under `## Log` of today's daily note.

## Tuning
Routing improves when projects carry `keywords:` and `stakeholders:` and rituals carry `meeting_match:`
Propose adding a keyword when the user corrects a route.

## Hard rules
- Never fabricate a decision, task, deadline, number or attendee; no note is final while `CHECK` reports MISSING.
- A summary is never saved as a transcript; transcripts are moved, never deleted or edited.
- Relation keys are frontmatter wikilinks (`BRAIN validate --file <note>` after an edit); text outside managed blocks and the named sections stays untouched.
- Read-only outside the vault.
