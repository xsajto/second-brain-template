# Contributing

## Stdlib only

`bin/` and `lib/` are Python 3.10+ **standard library only** — no third-party pip dependencies. This is a
hard rule, not a preference: the engine touches people's personal notes, so it must install with nothing
but `python3` (zero-install, works offline, no supply-chain surface from a dependency tree). If a change
needs a package that isn't in the stdlib, find a stdlib way to do it or leave it out.

## Before submitting a change

- Run the test suite: `bin/brain test`. It's a stdlib `unittest` suite in `tests/` that runs against a
  temporary fixture vault it builds itself — it never touches a real vault, including this repo's own
  folders.
- If you changed anything under `templates/` or `lib/schema.json`, also run `bin/brain validate`.
- If you changed a template, confirm its placeholders render by running `bin/brain create` against a
  scratch/temp vault (not this repo) and checking the output note.

## No personal data, ever

This repo ships as boilerplate. No real names, e-mail addresses, companies, task-manager or chat-tool IDs,
hostnames, tokens, or personal file paths may be committed — examples use fictional data (`Ada Example`,
`Acme Corp`, `example.com`). Before opening a PR, scan your diff:

```
grep -rniIE "/Use[r]s/|/hom[e]/[a-z]|xox[bp]-|ghp_|AKIA" . --exclude-dir=.git
```

Also check for stray e-mail addresses whose domain isn't `example.com` or `example.org` — those are
usually personal and should be removed or genericized. This is a heuristic, not exhaustive; read the
diff too:

```
grep -rnIP '[A-Za-z0-9._%+-]+@(?!(example\.com|example\.org))[A-Za-z0-9.-]+\.[A-Za-z]{2,}' . --exclude-dir=.git
```

(`-P` is required here — the pattern uses a negative lookahead, which POSIX `-E` doesn't support; GNU grep's
`-P` does. The exact same pattern runs in CI, see `.github/workflows/test.yml`.)

## Proposing a change

Open an issue or PR describing the change. Keep PRs small and focused on one concern at a time — a
feature, a fix, a docs update, not a mix.

## Code style

Match the existing style in `bin/` and `lib/`: docstrings that explain *why*, not just what; stdlib only;
no dependencies.
