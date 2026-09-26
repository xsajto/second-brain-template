---
name: correct
description: Correction sweep for one fact across the whole brain — the user states the corrected fact ("the launch is on 1 November, not 15 October", "Ada no longer leads platform"), the skill finds every note that states the old version, classifies each occurrence as AUTHORITATIVE (the entity note or project CLAUDE.md that owns the fact → line delta, old line struck through and replaced by a new ^f- fact), RESTATEMENT (an undated note repeating it → replaced by a link to the authoritative note) or HISTORICAL (dated notes, meetings, daily notes, transcripts, archives → never edited), shows one numbered table and applies only after the user answers. Use when the user says "correct this", "that's wrong everywhere", "fix this fact", "this is no longer true", "update it everywhere", or /correct "<fact>".
model: opus
effort: medium
---
# correct

Rules in `CLAUDE.md` bind this skill. Run from the workspace; `BRAIN` = `bin/brain`. Chat in
`brain.config.json › language`. One corrected fact per run, swept through the vault without rewriting history.

## Input
`/correct "<new fact>" [instead of "<old fact>"] [source=<wikilink | URL | id>]`. Old wording missing → ask once.
Source missing → the user's statement is the source (`chat, YYYY-MM-DD`, confidence `medium` unless the user
says otherwise). Never invent a source.

## 1. Find (read-only)
- Key terms: the entity and 1–3 distinctive words or values of the OLD fact (also without diacritics).
- `BRAIN find --text "<entity>"` → candidates; `BRAIN show "<entity>"` → its note (the likely authority).
- `grep -rniF "<old value>" 00_Inbox 10_Daily 20_Projects 30_Areas 40_Knowledge` and `grep -rn "\^f-"` on the
  candidates. `99_Archives/` and `50_Raw/` are only counted, never read in full.
- Keep lines that actually state the old fact (read ±2 lines); drop mere mentions.

## 2. Classify
| class | which notes | action |
|---|---|---|
| AUTHORITATIVE | the entity note in `40_Knowledge/`, or `20_Projects/<slug>/CLAUDE.md` for a project's status, goal, dates, people — one per fact (two → ask) | old line `~~…~~ → replaced by ^f-<new>`; new line `- [category] <new fact> — <source>, YYYY-MM-DD, confidence: medium ^f-<new>` under `## Facts` (created above `## Log`) |
| RESTATEMENT | undated notes repeating it: hubs, topic notes, other projects' notes | replace only that clause with `[[<authority stem>\|<label>]]` (+ ≤ 5 words) |
| HISTORICAL | dated file names, meeting folders, `10_Daily/`, `00_Inbox/meetings/`, `50_Raw/`, `99_Archives/`, `## Log` lines, run logs | never edited; counted |
Frontmatter values: `status:` changes are a proposal line; relation changes via
`BRAIN unlink <note> --<rel> "[[x]]" --ended <date> --source <src>` / `BRAIN link`; `auto:` blocks are left to
their owning skill (listed as `auto → /weekly` or `/people`).

## 3. Propose (one round)
```
Correction: "<new>" (was "<old>"), source <source>
| # | class | file:line | change |
| 1 | AUTHORITATIVE | 40_Knowledge/work/launch-plan.md:27 | ~~launch 15 Oct~~ → replaced by ^f-3c1a2b |
| 2 | RESTATEMENT | 30_Areas/work/work-hub.md:14 | "launch 15 Oct" → [[launch-plan|Launch plan]] |
Historical, unchanged: 4 (daily 2, meetings 2)
Answer: 1,2 · all · none · -2 · 2: <edit>
```
Nothing is written before the answer. No occurrence found → say so with the searches tried and offer only the
new fact line on the authoritative note.

## 4. Apply
- Checkpoint: `git status --porcelain` dirty → `git add -A && git commit -qm "correct: checkpoint"`.
- One Edit per line, nothing else in the note. `^f-<6hex>` from
  `python3 -c "import secrets; print(secrets.token_hex(3))"`, unique (`grep -rn "\^f-<hex>"` empty).
- `BRAIN validate` must not report new errors (else `git checkout -- <touched files>` and say why). Re-read each
  touched line.

## 5. Log
Run log `50_Raw/logs/correct/YYYY-MM-DD-HHMM.md`: old → new, source, the table with answers
(`— yes|no|edited|pending`), counts, then `## Friction` (`- none` if nothing). A wrong fact that came from a
skill (a meeting note, an import) → one Friction line naming that skill, so `/weekly` can propose a fix.
One line under `## Log` of today's daily note. Chat ≤ 6 lines.

## Hard rules
- Never edit HISTORICAL notes, never delete a line (strike through), never rewrite a whole note.
- No network: if the right value must be checked in a tool, say which one and stop.
