# Setup: detach from the template + install check

Run from the repo root (`test -f bin/brain && test -f CLAUDE.md`, else stop and say where to `cd`).

## Detach from the template (step 1)

A colleague clones the shared template; their brain must become its own repository with no template history
and no template remote (their notes must never be pushed there).

1. State (read-only):
   ```
   git rev-parse --show-toplevel 2>/dev/null   # must equal "$PWD"; anything else → stop, never delete
   git remote -v                                # template remote?
   git log --oneline | wc -l                    # commits that will disappear
   du -sh .git                                  # size of what will be deleted
   ```
2. Decide:
   - no `.git` → `git init -b main` + first commit (below), no question needed beyond "ok".
   - `.git` with **no remote** → already detached, skip.
   - a remote that is the template (URL ends in `second-brain` or `second-brain.git`)
     <!-- TODO owner: put the canonical template repo URL here so the match is exact -->
     → detach.
   - any other remote → ask whether it is the user's own private repo; yes → skip.
3. Show in Czech, then wait for "ano":
   `Smažu složku .git (<N> commitů šablony, <size>, remote <url>). Soubory zůstanou, zmizí jen historie šablony
   a vazba na ni. Pak založím nový repozitář a udělám první commit. Pokračovat? (ano/ne)`
4. After "ano" (and only then):
   ```
   rm -rf "$(git rev-parse --show-toplevel)/.git" && git init -b main && git add -A && git commit -qm "Nový brain ze šablony"
   ```
   `git config user.email` empty → ask for name + work e-mail, set them with `git config` (repo-local), then commit.
5. Post-condition: `git remote -v` prints nothing and `git log --oneline` shows exactly one commit.
   A private remote for `/sync` is optional and later (the user creates an empty private repo and runs `/sync`).

## Install check (`--check`, and step 2 of a first run)

Read-only; one row per check: `ok | missing | warn` + the fix. Fixes run only after a numbered "ano".
`EMAIL` = `user.email` from `brain.config.json` (`python3 -c 'import json;print(json.load(open("brain.config.json"))["user"]["email"])'`).

| check | command | fix |
|---|---|---|
| brew | `command -v brew` | install from https://brew.sh (the user runs it; needs their password) |
| python ≥ 3.10 | `python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'` | `brew install python` |
| git | `git --version` | `xcode-select --install` or `brew install git` |
| detached | `git remote -v` has no template URL | step 1 |
| config | `test -f brain.config.json` | interview (steps 3–4) |
| gog | `command -v gog && gog --version` | `brew install gogcli` |
| gog client | `gog auth credentials list` lists a client | `references/connectors.md` › Google |
| gog auth | `gog auth list --plain \| grep -F "$EMAIL"` | `gog auth add "$EMAIL" --services gmail,calendar,drive --readonly` |
| gog read | `gog --account "$EMAIL" --no-input calendar events --today -j >/dev/null` | `gog auth doctor`, then re-auth |
| MCP servers | `claude mcp list` (health-checks each; `⏸ Pending approval` = not approved yet) | approve the project servers, then `/mcp` → authenticate |
| glab (optional) | `glab auth status --hostname git.moderntv.eu` | `brew install glab && glab auth login --hostname git.moderntv.eu` |
| hooks | `python3 -c 'import json,sys; h=json.load(open(".claude/settings.json")).get("hooks",{}); sys.exit(not {"SessionStart","PostToolUse"} <= h.keys())'` | `git checkout -- .claude/settings.json` (restores the template hooks) |
| brain | `bin/brain doctor` (exit 0, 0 problems) | the fix line doctor prints |
| vault | `bin/brain validate` | `/weekly` hygiene, or the named fix |

Report as a Czech table (≤ 15 rows), then numbered fixes. `--check` stops there: no fixes, no log beyond the run log.
