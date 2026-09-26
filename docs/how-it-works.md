# How it works

The engine (`lib/vault.py`, `lib/paths.py`, `bin/brainkg.py`, `bin/context.py`) treats the vault as a
knowledge graph stored in plain Markdown. This is a reference for how that graph is built and kept
consistent — see `../README.md` for setup and daily use.

## The graph

Every `.md` file below the numbered folders is a node: its path, its frontmatter (`id`, `type`, `kind`,
plus whatever else a note carries) and its body. Edges come from three places:

- **Frontmatter relations** — wikilink lists such as `area:`, `project:`, `owner:`, `stakeholders:` (full
  list and canonical direction in `lib/schema.json` › `relations`, explained in `conventions.md`). Each
  relation is stored in **one direction only**: a project note has `area: [[cto-hub]]`, not the other way
  round. `bin/brain related <note>` and `bin/brain project <role>` compute and show the inverse (an area's
  projection lists the projects that point at it).
- **Body wikilinks** (`links_to`, inverse `linked_from`) — any `[[wikilink]]` in the note's prose, outside
  a managed block.
- **`auto:links` wikilinks** (`mentions`, inverse `mentioned_in`) — wikilinks that live inside an
  `<!-- auto:links start -->...end -->` block specifically (see below); kept as a separate edge type from
  ordinary body links so a note's own prose links stay distinct from computed backlink lists.
- **`source:` frontmatter** (`provenance`, inverse `provenance_of`) — when a note's `source:` value
  resolves to another note in the vault.

All three are computed by `Graph._build()` in `lib/vault.py`; nothing above needs to be maintained by
hand beyond writing the wikilink or frontmatter key.

## Agent context: `index.md` and `hot.md`

`bin/brain context --write` regenerates two files under `.claude/`:

- **`index.md`** — one line per note (link, type, context, summary), so an agent can see the whole vault
  without opening every file. `description:` frontmatter overrides the auto-generated summary. A folder (or
  a family of similarly-named folders) past `knowledge.list_max` notes collapses to a single `▸` line
  instead of listing every note.
- **`hot.md`** — a smaller "what's relevant right now" snapshot, built from the same run: waiting
  transcripts, stale Inbox captures, open proposals from a skill's run log — each rendered as a `▸`
  trigger line.

Two hooks (configured in `.claude/settings.json`) keep these current without a manual step:

- **SessionStart** → `brain context --hook`: runs `--write`, then prints `hot.md` to stdout so a fresh
  session opens with today's snapshot already in view.
- **PostToolUse** (after Write/Edit/MultiEdit) → `brain context --post-tool`: reads the hook's JSON on
  stdin and runs `brain validate --file` on just the note that was touched, reporting any errors back to
  the agent inline — a fast, local, single-file check, not a full revalidation.

Both hooks are local and offline by design; they must stay fast enough not to be felt as a pause.

## `brain validate`

Checks schema conformance: required frontmatter present, relation values resolve and match the schema's
allowed from/to types, wikilinks resolve, `id` matches `<type>/<ascii-kebab>`, a note's `type:` matches
what its folder would infer, and the branch/leaf folder rule (below) holds. `--strict` escalates warnings
to errors. `--file PATH` limits the run to one note (what the PostToolUse hook calls). `--json` gives
machine-readable output.

## Managed blocks

A block wrapped in `<!-- auto:NAME start -->` / `<!-- auto:NAME end -->` (`links`, `projection`, `profile`,
`status`, `portfolio`, `registry`, …) is owned by tooling or a skill and rewritten wholesale on each run.
Everything outside a managed block is the author's prose and is never touched by automation — a skill or
script only ever replaces the content between one note's markers.

`bin/brain project <role|entity|MOC|40_Knowledge/folder>` is what (re)writes a note's `auto:projection`
block: a computed summary of its graph neighbourhood, e.g. an area's hub listing the projects and systems
whose `area:`/`responsible_for:` points at it. `--write` applies it to one target, `--all` to every note
that has a projection block.

## The branch/leaf folder rule

A folder below the numbered top level (`10_Daily`, `20_Projects`, `30_Areas`, `40_Knowledge` —
`lib/schema.json` › `branch_leaf_roots`) is either a **branch** (only subfolders) or a **leaf** (only
documents), never both — except named companion files (`README.md`, `CLAUDE.md`, `*-hub.md`, `*-moc.md`,
`*.base`, plus anything added in `brain.config.json` › `companions`), which may sit next to subfolders in
either kind of folder. `brain validate` flags a mix as `branch-leaf`.

## Dry-run by default

The write commands — `create`, `link`, `unlink`, `move`, `rename` — print what they would do and change
nothing until you add `--apply`. `--apply` additionally refuses to touch a file that has uncommitted
changes it didn't itself make (so it can't silently clobber an edit it doesn't know about); `--allow-dirty`
overrides that check when you're sure.

## Health and tests

`bin/brain doctor` runs generic, fast checks — Python version, `brain.config.json` present and parseable,
the expected vault folders exist, the schema loads, git is initialised — and reports plainly what's missing.
`bin/brain test` runs the stdlib `unittest` suite in `tests/` against a temporary fixture vault it builds
and discards; it never touches your real notes.
