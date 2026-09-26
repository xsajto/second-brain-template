---
name: people
description: Keeps person notes and relationship maps current from communication the user is part of — meeting notes and transcripts with speaker labels, the vault's own notes, and (when connected) mail, calendar and chat — maintaining per person an auto:profile block (communication style, what motivates them, how to work with them, relation to the user and to others, confidence), a dated log line, and a mermaid relationship map per context; proposes new person notes for recurring names. Descriptive and respectful, never judgemental. Use when the user says "people", "update profiles", "who is who", "how should I talk to <name>", "relationship map", "team dynamics", "prepare for my 1:1 with <name>", or /people [name|context].
model: opus
effort: high
---
# people

Rules in `CLAUDE.md` bind this skill. Run from the workspace; `BRAIN` = `bin/brain`,
`PEOPLE` = `python3 .claude/skills/people/scripts/people.py` (`--help`). Person notes live in the people registry
(`brain.config.json › folders.people`). Notes and chat in `brain.config.json › language`.

## Arguments
`scope` — default everyone with contact in the window; a name = that person; a context = its people.
`days` — evidence window, default 90 (first profile of a person: 365).

## 1. Registry
`PEOPLE --list [--context C]` → name, path, context, role, org, e-mail, aliases, `profile` flag, `last_log`,
relations. `profile: false` → skip that person entirely. The user is the note with `me: true`.

## 2. Evidence (read-only; one subagent per person when more than 3, `model: haiku`, ≤ 20 lines, source ids)
| source | what to extract |
|---|---|
| vault: the person note, meeting notes and transcripts naming them (`BRAIN find --text "<name>"`, `BRAIN related <note>`), daily notes | dated observations, decisions, how they speak (turn length, questions vs statements, data vs story) |
| mail (`gog gmail search 'from:<email> OR to:<email> newer_than:<days>d'`), when connected | formality, length, reply latency, when they write |
| chat via its MCP (messages from them and DMs with the user), when connected | directness, channel habits, response time |
| calendar (`gog calendar events` filtered by attendee), when connected | cadence of contact, shared rituals |
A source that is not connected is named once in the report. Relations between other people come only from
shared meetings, public channels and transcripts — observed, never inferred from absence.
Evidence files go to `50_Raw/logs/people/evidence/<stem>-evidence.md` (plain, no `id`/`type`).

## 3. Profile block (per person; ≤ 25 lines, every line ends with `(source id, YYYY-MM-DD)` or `(n signals)`)
```
**In one line:** a friendly, slightly exaggerated archetype, never mocking
**Communication:** channel · response time · formality · data vs story · length · when reachable
**Motivated by:** …        **Watch out for:** …
**How to work with them:** 1) … 2) … 3) …
**Relation to me:** manager/peer/report/client/vendor/family · strength 1–5 · trend ↑ → ↓ · last contact YYYY-MM-DD
**Relations:**
- [[stem|Name]] — works with / leads / reports to / tension — 1–5
**Confidence:** low | medium | high (n interactions, period)
```
Headings in the note language; the `- [[stem|Name]] — relation — strength` line shape stays (the map reads it).
Depth follows evidence: fewer than 3 interactions and no 1:1 → only the first two lines and `Confidence: low`.
Change only what new evidence supports; keep earlier lines otherwise. Write it with
`PEOPLE --write-block <person.md> --from <scratch file>`, then one log line
`PEOPLE --log <person.md> --line "<what changed and why> (source)"`.
Explicit role/org/e-mail found in evidence (signature, org chart) → numbered proposal to update frontmatter;
`member_of`/`stakeholders` edges only via `BRAIN link … --apply` after "yes".

## 4. New people
A name seen in ≥ 3 interactions (or one 1:1) without a note → proposal `N. [person] Name → <people folder>
(role?, evidence)`; on "yes" `BRAIN create person "<Name>" --context <ctx> --apply`. Never from a single mention.

## 5. Map, log, report
- Per touched context: `PEOPLE --map <context> --write` → `<primary area>/<relationship map file>` (`auto:map`).
- Run log `50_Raw/logs/people/YYYY-MM-DD-HHMM.md`: scope, window, sources and gaps, per person evidence count
  and whether the block changed, proposals as `N. … — yes|no|pending`, then `## Friction` (`- none` if nothing).
- Chat ≤ 12 lines: who was updated, the single most useful tip per person, numbered proposals.

## Hard rules
- Only communication the user is a party to, public channels and meetings the user attended; never other
  people's private conversations.
- Describe behaviour, never diagnose: no health, family, politics, religion or private-life inferences, no labels
  like "toxic". Guesses are marked `?`. At most one short quote per person, from the user's own notes.
- Writes: `auto:profile` and `auto:map` blocks, `## Log` lines, the run log; everything else after "yes".
- Read-only outside the vault.
