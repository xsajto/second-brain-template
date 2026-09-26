---
name: morning
description: Daily routine — builds today's briefing in the daily note 10_Daily/YYYY/YYYY-MM-DD.md from the calendar, every connected source (mail, Slack, task manager, Jira, GitHub, Notion…), the Inbox and unchecked Top 3 carried over from the previous day, then runs a light curator pass — link review of notes created or changed since the last run (missing wikilinks and relations to people, projects, areas, orgs and systems, facts that belong in another note, orphans) — as numbered proposals, and answers with a short chat summary. Use when the user says "morning", "good morning", "start my day", "daily brief", "what's on today", "brief for tomorrow", or /morning [date].
model: sonnet
effort: medium
---
# morning

Rules in `CLAUDE.md` bind this skill. Run from the workspace; `BRAIN` = `bin/brain`,
`REVIEW` = `python3 .claude/skills/weekly/scripts/review.py`, `DAILY` = `python3 .claude/skills/morning/scripts/daily.py`.
Chat and notes in `brain.config.json › language`. Target: under 2 minutes of the user's time.

## Arguments
`date` — default today; "tomorrow" = the next day (briefing only, no link review).

## 1. Daily note + carry-over
`DAILY [--date D]` → JSON `path`, `created`, `carried` (unchecked Top 3 lines copied from the previous daily note
as `- [ ] (from YYYY-MM-DD) …`, idempotent), `cursor` (date of the last `/morning` run log, else yesterday),
`inbox` (captures, older than 7 days, pending transcripts).

## 2. Sources (read-only, in parallel where independent)
Walk every entry of `integrations` in `brain.config.json`; its `morning` value says what to check there. For each:
- **google** (`gog`): calendar per account of the relevant contexts —
  `gog calendar events --account <email> --from <D> --to <D+1> --json` (check `gog calendar --help` if flags
  differ); mail — `gog gmail search 'is:unread newer_than:2d' --account <email> --max 20`. Classify mail as
  **Action** (a reply, decision or approval expected from the user), **Waiting** (the user wrote last, > 1 day),
  **FYI**; newsletters/notifications only as a count. Open a thread before saying what someone wants.
- **MCP sources** (Slack, Linear, Jira, Notion, GitHub…): load tools with ToolSearch (`+slack`, `+linear` …),
  then one narrow query per the `morning` text since `cursor`. Items addressed to the user without a reply → Action.
- **Meetings prep**: for each calendar event, `BRAIN find --text "<event title>"` and attendee names → link the
  owning project/area/person note and one sentence of prep from it (open questions, last decisions).
- **Nothing configured** → say once: "no sources connected — /onboarding connects calendar, mail, Slack…".
**No silent skip**: a source that fails, is unauthorised or has no tool gets one line
`⚠ <source>: unavailable — <what was tried / the fix>` in the briefing and in chat. Empty = `- nothing new`.

## 3. Write the briefing
Write the block body to a scratch file and run `DAILY --briefing <file> [--date D]` (replaces only the
`auto:briefing` block; the user's Top 3 and log stay untouched). Shape (headings in the note language):
```markdown
### Calendar
- 09:00–09:30 **Title** · prep: one sentence · [[owning-note|Label]]
### Mail
- Action · Subject · sender · what they want · deadline
### Tasks
- [Issue title](url) · due 2026-09-28
### Messages
- Action · #channel / person · what it is about · [link](permalink)
### Inbox
- 4 captures (2 older than 7 days) · 1 transcript waiting → /process-meetings
```
Sensitive content (salaries, credentials, health) is described, never copied. Never fill Top 3 for the user;
you may suggest up to three candidates in chat.

## 4. Link review (light curator pass; skip for a future date)
- `REVIEW links --since <cursor>` → notes changed since the last run with `unlinked` mentions of entities
  (person, org, project, area, system, concept) and `orphan` flags. Read each listed note once.
- Propose, numbered, one line each:
  - `[link] <note> → add [[stem|Title]] where "<term>" is mentioned` — only a real reference to that entity
    (same person/system, not a homonym); daily notes and meeting notes included.
  - `[relation] <note> → brain link --<rel> "[[target]]"` when the mention is structural: attendees of a
    meeting, stakeholders/owner of a project, `member_of` an org, `uses`/`depends_on` a system, `part_of`.
  - `[fact] <fact> → <entity note>` when a changed note states a durable fact about another entity; the
    target gets `- [category] fact — [[source-note]], YYYY-MM-DD ^f-<6hex>` (people: `, confidence: medium`
    before the id) under `## Facts` (heading in the note language, created above `## Log` when missing).
  - `[orphan] <note> → link from <hub/project/area>` or `→ move to <folder>` (captures stay in `00_Inbox/`
    until `/weekly` triages them).
- At most 10 proposals; the rest go to the run log as `pending` for `/weekly`.

## 5. Chat (≤ 10 lines)
Meetings (count, first start, prep needed) · the 1–2 most important Action items · overdue tasks · Inbox line ·
carried-over Top 3 · one line per `⚠` source · the numbered link-review proposals with the answer syntax
(`1,3` · `all` · `none` · `-2` · `2: <edit>`). End with the daily note path.

## 6. Apply and log
- Apply accepted proposals: wikilinks by a one-line Edit in the note body; relations only via
  `BRAIN link <note> --<rel> "[[target]]"` then the same with `--apply`; facts as one appended line.
  `BRAIN validate` must not report new errors; re-read one touched line to confirm.
- Run log `50_Raw/logs/morning/YYYY-MM-DD-HHMM.md`: sources used/failed, counts, proposals as
  `N. [kind] … — yes|no|edited|pending`, then `## Friction` (one line each; `- none` if nothing).
- One line under `## Log` of today's daily note: `- /morning: n meetings, n actions, n link proposals (n applied)`.

## Hard rules
- Read-only outside the vault: never send mail or messages, never change tasks, labels or calendars.
- Never fabricate an event, mail, task or link target. Unknown = say so with what was tried.
- Text outside the `auto:briefing` block is the user's, except the carried-over lines and the one log line.
- Relation keys, `id`, `type` and moves only through `bin/brain`.
