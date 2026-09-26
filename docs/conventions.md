# Conventions

How a note is written by hand (or by a skill) so it stays part of the graph described in
`how-it-works.md`. See `../README.md` for the folder layout these apply within.

## Facts as observations

A fact lives in the body as one line, not as prose buried in a paragraph:

```
- [category] fact — source, YYYY-MM-DD ^f-abc123
```

`[category]` is a free short tag (`[role]`, `[decision]`, `[contact]`, whatever fits). `^f-abc123` is an
Obsidian block reference: a stable anchor another note can link straight to (`[[person#^f-abc123]]`). For
facts about people it's useful to add a confidence, e.g. append `, confidence: medium`.

**Deltas, not rewrites.** Updating a fact means adding a new line — or striking through the old one and
pointing at the new: `~~old fact~~ → replaced by ^f-new123`. A note's fact history is never lost by editing
a line in place.

## Relations

Frontmatter relation keys are wikilink lists, stored in **one canonical direction only** — the inverse is
computed (see `how-it-works.md`), never written by hand on the other side.

| key | from (holder) | to | inverse |
|---|---|---|---|
| `project` | meeting, decision, note | project | `notes` |
| `area` | project, system, org, concept | area | `contains` |
| `owner` | any entity | person | `owns` |
| `stakeholders` | project | person | `stakeholder_in` |
| `attendees` | meeting | person | `attended` |
| `member_of` | person | org | `members` |
| `responsible_for` | area, person, org | system, project | `responsibility_of` |
| `part_of` | any entity | same type | `parts` |
| `uses` | any entity | any entity | `used_by` |
| `depends_on` | any entity | same type | `required_by` |
| `affects` | any entity | any entity | `affected_by` |
| `related` | any | any | `related` (symmetric) |

Full from/to constraints live in `lib/schema.json` › `relations`; `bin/brain validate` checks a value
against them.

## Naming

- Every file and folder below the top level is **ascii lowercase kebab-case**: no diacritics, no spaces,
  no uppercase, no emoji (`40_knowledge/people/ada-example.md`, not `40_Knowledge/People/Ada Example.md`).
- The human-readable name lives in frontmatter, not the filename: `title: Ada Example`, older names in
  `aliases:`.
- Wikilinks reference the file stem and show the human name as a label: `[[ada-example|Ada Example]]`.
- Renames go through `bin/brain rename`, never a manual `mv` — it updates the file, its `title`/`aliases`
  and every wikilink that pointed at it, so links keep resolving.

## The branch/leaf folder rule

See `how-it-works.md` for the rule itself. In practice: don't drop a loose note next to a folder's
subfolders unless it's a recognised companion file (`README.md`, `*-hub.md`, `*-moc.md`, …) — either
promote the folder to hold only subfolders, or keep the note there and don't add subfolders yet.

## `type` / `kind` and inference

`type:` frontmatter is authoritative when present. When it's absent, `lib/schema.json` › `inference`
guesses it from the note's path (or, failing that, its tags) — for example anything under a configured
meetings folder infers `type: meeting`, anything under `10_Daily/YYYY/` infers `type: daily`. This is why a
note filed in the wrong folder can show up in `index.md` with a type you didn't expect: the folder is doing
the inferring. Set `type:` explicitly whenever a note doesn't belong to the folder its content would
suggest.

`kind` is a sub-classification of `type` (e.g. `org` → `company`/`team`, `meeting` → `ritual`/`one-off`/
`1on1`); `lib/schema.json` › `kinds` lists what's allowed per type, and an empty list there means any kind
is accepted. Add a new kind or type with `bin/brain schema add-kind|add-type` rather than forcing a note
into one that doesn't fit — it's a dry run until `--apply`.

## 40_Knowledge/ hub thresholds

A folder under `40_Knowledge/` gets a generated `<folder>-hub.md` once it has at least `hub_min_notes`
(default 10) notes, recursively, or at least `hub_min_subdirs` (default 2) subfolders. A folder past
`list_max` (default 25) notes collapses to a single line in `index.md` rather than listing every note. The
`split_threshold` (15), `cluster_threshold` (5) and `namespace_threshold` (3) settings don't trigger
anything automatically — they exist as thresholds a maintenance routine can use to *propose* splitting a
folder, spinning a repeated cluster into its own topic, or promoting a topic into its own namespace; the
decision to act on one is left to whoever (or whatever routine) is doing that maintenance.
