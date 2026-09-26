# Routines

The two recurring habits onboarding schedules, and how the rest of the skills relate to them. See
`../README.md` for how to invoke each skill and `how-it-works.md` for the graph they operate on.

## `/morning`

Builds today's daily note from the calendar, whatever sources `brain.config.json` has configured, the
Inbox, and your open Top 3 — a quick "here's today" pass, not a maintenance run. It also does a light
curator pass over yesterday's changes: a link review (below) limited to what changed since the last run.

## `/weekly`

The broader maintenance pass: deduplicating notes and facts, catching stale or contradicting facts,
lifecycle transitions (an active project gone quiet → paused; a paused one finished → archived), a fuller
link review over the whole week's changes, Inbox triage, refreshing project status blocks, rewriting the
portfolio block, and a health check.

## Link review

Both routines include a version of the same check, at different depths: scan recently changed notes for
prose that names another note by title without a wikilink, and propose adding one; and flag notes with no
incoming links (`links_to`/`mentions`/frontmatter relations) as orphans worth connecting or reconsidering.
`/morning` runs this over yesterday's changes only; `/weekly` runs it over the whole week. Either way it's
a **proposal** — see below.

## Scheduling

A routine runs when you invoke it (`/morning`, `/weekly`), or it can be set up to run automatically on a
schedule using Claude Code's own scheduling mechanism (`/schedule`) — a recurring cloud agent run, cron-like,
configured once during onboarding or later by hand. This is the only sanctioned form of automation in this
vault: no ad-hoc cron, launchd, or other background job should be set up from inside the vault itself; if a
routine needs to run unattended, it goes through `/schedule`.

## Everything else is on-demand

The remaining skills aren't scheduled — they trigger on an event, not a clock:

- `process-meetings` — a transcript arrives in the meetings inbox folder.
- `research` — you're comparing options and want a shared, revisitable write-up.
- `new-project` — a new effort is starting and needs a folder.
- `people` — after any communication with someone, to keep their note and the relationship map current.
- `correct` — a fact turns out to be wrong and needs fixing everywhere it was restated.
- `sync` — you want to push or pull the vault's git history.

## Confirmation

Every routine and skill above produces a **numbered list of proposals**; nothing beyond the note you're
actively editing is written until you confirm. There is no routine that silently rewrites other notes in
the background.
