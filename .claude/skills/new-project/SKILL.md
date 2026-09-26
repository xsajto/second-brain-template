---
name: new-project
description: Turns a free-text brain dump (goal, people, links, open questions) into a new project folder 20_Projects/<slug>/ with a filled CLAUDE.md — parses the dump, researches the topic in parallel across the vault and every connected source (mail, Slack, task manager, Drive/Notion, GitHub), checks for an existing or archived project that already covers it, shows the findings plus the proposed CLAUDE.md, and creates it only after the user confirms. Use when the user says "new project", "start a project", "kick off", "here is a brain dump", "make a project out of this", or /new-project.
model: opus
effort: high
---
# new-project

Rules in `CLAUDE.md` bind this skill (what deserves a project folder, naming, `## Sources`). Run from the
workspace; `BRAIN` = `bin/brain`. Notes and chat in `brain.config.json › language`.

## Input
- `dump` (required): the pasted or dictated text. None → ask for it ("goal, people, links, questions — bullets
  are fine").
- `area`: the role it serves (an area hub in `30_Areas/`); the context follows from the area. Infer from the
  dump; unclear → numbered list of the existing areas. Never guess.
- `slug`: `<context slug>-<2–3 ascii words>` (slug prefixes from `brain.config.json › contexts`); the user may
  override.
- Not a project (a single task, a recurring duty, an idea, a small effort under two weeks) → say so and offer the
  right home (task manager, area ritual, `40_Knowledge/<ns>/ideas/`, a note with `- [ ]` steps in the area).

## 1. Parse
Working title, context, goal (one sentence + done criterion), people (name → role / what the user needs from
them), links and ids verbatim, open questions, 3–8 search keywords.

## 2. Research in parallel (read-only)
One subagent per available source (`model: haiku`, `general-purpose`, all in one message), each returning
≤ 15 lines of `title · link/id · date · one-line relevance`, exactly `nothing`, or `GAP: <why>`:
- VAULT: `grep -ril "<keyword>" 20_Projects 30_Areas 40_Knowledge 99_Archives` + frontmatter of hits (earlier notes, archived incarnations).
- Each connected source in `brain.config.json › integrations` (mail via `gog`, Slack/Linear/Jira/Notion/GitHub
  via their MCP tools, loaded with ToolSearch): matches for the title and keywords in the last 90 days.
- Local repos only when the dump names one (`git -C <path> log -5 --oneline`, README).
A source that is not connected is listed as `GAP: not connected`, never silently dropped.

## 3. Overlap check
Score the dump against active projects as `/process-meetings` step 2.1 does:
an active project scoring ≥ 4 is a probable duplicate → recommend updating it instead. An archived hit from
VAULT → recommend reviving it (`BRAIN move 99_Archives/<slug> 20_Projects/`).

## 4. Present
(a) findings per source with links verbatim and gaps; (b) the full proposed `20_Projects/<slug>/CLAUDE.md`:
frontmatter (`title`, `context`, `area`, `status: active`, `keywords` 5–10, `stakeholders` as wikilinks to
existing people), then the template's sections: `## Goal` (one sentence + done criterion, 2–5 sentences of
context), `## People` (roles), `## Sources` (`id | where | note`, only ids actually found or typed by the user),
`## Status` (open questions), `## Decisions`, `## Next steps` (3–7 `- [ ]` items); (c) the overlap verdict.
Ask: `1) create  2) change (say what)  3) cancel`. Loop on 2.

## 5. Create (only after 1)
- `BRAIN create project "<Title>" --context <ctx> --area "<Area>" --slug <slug>` (dry run) → `--apply`; then fill
  the body as approved (≤ 80 lines). Stakeholders that equal exactly one person →
  `"[[person]]"` in its `stakeholders:` frontmatter; unknown people → person
  proposals (numbered, `BRAIN create person … --apply` on yes).
- The raw dump verbatim in `20_Projects/<slug>/YYYY-MM-DD-brain-dump.md` (frontmatter `title`, `context`,
  `type: resource`).
- Add its row to the `auto:portfolio` block of the root `CLAUDE.md` (row shape in `/weekly` step 5).
- Post-condition: `BRAIN validate` passes; re-read `20_Projects/<slug>/CLAUDE.md`: `area` and `stakeholders` set.

## 6. Report and log
Chat ≤ 8 lines: created path, sources found per source and gaps, first three next steps, open questions count.
Run log `50_Raw/logs/new-project/YYYY-MM-DD-HHMM.md` (sources, gaps, proposals with answers, `## Friction`);
one line under `## Log` of today's daily note.

## Hard rules
- Nothing is written before "1". Never overwrite an existing project folder or edit another project.
- Never fabricate ids, URLs, dates or people; ids typed by the user are copied verbatim.
- Read-only outside the vault; subagents never write.
