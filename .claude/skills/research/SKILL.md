---
name: research
description: Research and comparisons kept in the brain as one living research folder — turns a question ("which X should we use", "compare A, B and C", "find out about Y") into a scoped plan with a shared rubric, fans out one read-only subagent per option (web, docs, GitHub, the vault), writes a main document with verdict, comparison matrix, fit to the user's context, open questions, sources and change history plus one document per option in 40_Knowledge/<namespace>/research/YYYY-MM-DD-<slug>/, links it from the related project or area, and revises the same folder in place whenever the topic comes back. Use when the user says "research", "compare", "evaluate options", "which one should we pick", "deep dive", "pros and cons of", "redo the comparison", "that's no longer true in the research", or /research "<question>".
model: opus
effort: high
---
# research

Rules in `CLAUDE.md` bind this skill. Run from the workspace; `BRAIN` = `bin/brain`.
Documents and chat in `brain.config.json › language`. Research already done in the conversation (tables,
subagent results) is saved the same way: skip to step 4 with what exists.

## Where it goes
- One research = one folder `40_Knowledge/<namespace>/research/YYYY-MM-DD-<slug>/` (date = start day, never
  changes; `<slug>` ascii kebab ≤ 60 chars). Namespace = whose knowledge it is: a context's namespace
  (`brain.config.json › contexts.<ctx>.namespace`), a company's, or `shared` for general knowledge.
- Main document `YYYY-MM-DD-<slug>.md` (same stem as the folder): `type: note`, `kind: research`, `title`,
  `status: draft|final`, `version`, `updated`, relations `project`/`area`/`related`. Detail documents
  `<slug>-<option>.md` with `related: ["[[YYYY-MM-DD-<slug>]]"]`. Create each with
  `BRAIN create note "<Title>" --kind research --in <namespace>/research/YYYY-MM-DD-<slug> --apply` (the main
  one titled `"YYYY-MM-DD <Topic>"` so its stem equals the folder; the `title:` may be shortened afterwards).
- Subagent raw output stays in the session scratchpad; only distilled, sourced content goes into the documents.
  External material kept verbatim (a PDF, a price list) → `50_Raw/` and cited.

## Living documents
- Before starting: `grep -ril "<topic>" 40_Knowledge 20_Projects` and `ls 40_Knowledge/*/research/`. Same question → revise that
  folder; a genuinely different question → a new folder linked via `related`.
- Any later conversation that changes facts, options, scores or the verdict (correction, new data, a redo) →
  edit the affected documents in place so they read as the current truth, bump `version`, set `updated`, and
  append `- YYYY-MM-DD v<N> — what changed and why (source)` to `## History`. Do it without being asked when the
  conversation clearly revises stored research.

## Procedure
1. **Scope**: one-sentence question, the options (ask only when unknown and not discoverable), the decision it
   feeds, and the user's constraints (read the related project `CLAUDE.md`, area hub, knowledge notes).
2. **Rubric**: one list of criteria every subagent fills, identical across options. Default: what it is ·
   fit/integration with the user's setup · cost and pricing model · maturity (license, activity, last release,
   adoption, with sources) · data ownership and privacy · risks and lock-in · effort to adopt (S/M/L, reasoned).
   Adapt to the domain (SLA for vendors, benchmarks for libraries, total cost for purchases).
3. **Fan out**: load `Agent` with ToolSearch if deferred. One `general-purpose` subagent per option (2–4 minor
   options per agent), all in one message, under 10 agents. Each prompt: the question, the user's context, the
   rubric, allowed sources (WebSearch/WebFetch, official docs, GitHub, vault paths), "every claim with a source URL
   or path; unverified = (unverified)", "read-only", an output file in the scratchpad; it returns the path and
   ≤ 6 lines. Wait for all; never predict results.
4. **Write**: main document —
   - Verdict first: recommendation, the one or two reasons that decide it, what would change it.
   - Matrix: rows = criteria, columns = options, short cells; ✅/⚠️/❌ only for real judgements.
   - Fit to the user's context, open questions, sources (every number/date/version with its link; vendor claims
     labelled), `## History`.
   - Detail documents per option when longer than ~40 lines. Conflicting sources are stated, not resolved
     silently; missing data = "not found".
5. **Link**: one line in the related project `CLAUDE.md` or area hub pointing to the main document; a decision
   taken on it becomes `BRAIN create decision …` linked both ways. `BRAIN validate` passes.
6. **Close**: chat ≤ 12 lines (verdict, matrix headline, path, open questions). Run log
   `50_Raw/logs/research/YYYY-MM-DD-HHMM.md` (question, agents, sources, gaps, `## Friction`); one line under
   `## Log` of today's daily note.

## Hard rules
- Read-only outside the vault: research never installs, deploys or changes remote systems.
- Primary sources (official docs, repos, release notes) over blogs. Never fabricate a source, number or benchmark.
- Secrets met during research are never copied into a document.
