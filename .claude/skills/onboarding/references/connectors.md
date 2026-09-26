# Connectors (steps 6–7)

Every connector ends with **one read** that proves it works; a failed read is named with its fix, never hidden.
Secrets (tokens, client JSON contents) never go into the repo, the config, chat or the run log — only into gog's
keyring, Claude Code's own MCP store, or the user's shell. When a token is needed, the user runs the command
in their own terminal (`! <command>` in Claude Code), so it never passes through the conversation.

## Google — Gmail, Calendar, Drive via `gog` (required for /morning)

1. Binary: `command -v gog || brew install gogcli`; then `gog --version`.
2. OAuth client (a Desktop-app client JSON; gog stores it, the file can be deleted afterwards):
   `gog auth credentials list` — a client listed → skip to 3.
   <!-- TODO owner: decide how colleagues get the OAuth client. Recommended: one company client in a ModernTV
   Google Cloud project, consent screen "Internal" (only moderntv.eu accounts, no Google verification needed),
   APIs Gmail + Calendar + Drive enabled; the client JSON shared in 1Password (vault/item name here).
   Until then option B is the fallback. -->
   - **A (company client):** the user downloads the JSON from <!-- TODO owner: 1Password item --> to
     `~/Downloads/`, then `gog auth credentials set ~/Downloads/<file>.json` and `rm` the file.
   - **B (own client):** `gog auth setup "$EMAIL" --services gmail,calendar,drive` guides the Google Cloud project,
     consent screen and Desktop client step by step (`--create-project` needs `gcloud` and project rights).
3. Account: `gog auth add "$EMAIL" --services gmail,calendar,drive --readonly` opens the browser; the user signs in
   with the work account. `--readonly` is the default here (the brain only reads Google); drop it only if the
   user asks for drafts or calendar writes. Tokens land in the OS keychain.
4. Verify: `gog --account "$EMAIL" --no-input calendar events --today -j` → tell the user how many events today
   and the first title. Failure → `gog auth doctor`, fix, retry once.
5. Config: `user.email` = `$EMAIL`; `integrations.google = {"accounts": {"work": "$EMAIL"},
   "morning": "today's calendar; unread mail from people (Action / Waiting / FYI)"}`. A private Google account is
   optional: same steps 3–4 with its address, added as `"private": "<address>"`.

## Company connectors (MCP)

Two routes, same tools for the skills (they load them with ToolSearch `+slack`, `+atlassian`, `+asana`):
- **claude.ai connectors** (Settings → Connectors on claude.ai, same account as Claude Code): appear in Claude Code
  as `claude.ai <Name>`. Preferred when the connector already exists there — do not add it twice.
- **Project `.mcp.json`** (in this repo, no secrets): Claude Code asks once to approve the project servers; then
  `/mcp` → server → Authenticate (OAuth in the browser). `claude mcp list` shows the state.

Check `claude mcp list` first; per connector offer only what is missing. Store each connected one in
`integrations` with its `morning` text.

| connector | route | one-read verification | `integrations` entry |
|---|---|---|---|
| Slack (`moderntv.slack.com`) | `.mcp.json` `slack`, or claude.ai Slack | search users for the user's own name → their profile | `"slack": {"mcp": "slack", "morning": "DMs and mentions since the last run"}` |
| Jira + Confluence (`moderntv.atlassian.net`) | `.mcp.json` `atlassian`, or claude.ai Atlassian | list accessible resources → contains `moderntv.atlassian.net`; JQL `assignee = currentUser() ORDER BY updated DESC`, 1 result | `"atlassian": {"mcp": "atlassian", "site": "moderntv.atlassian.net", "morning": "Jira tickets I am assignee/reporter/watcher of, updated since the last run; Confluence mentions"}` |
| Asana (workspace ModernTV Group) | claude.ai Asana connector <!-- TODO owner: Asana's V2 MCP server needs a registered OAuth app; either a company app (client id here, then add it to .mcp.json) or claude.ai connectors only --> | get my user / my tasks, 1 result | `"asana": {"mcp": "asana", "morning": "my tasks due today and newly assigned"}` |
| GitLab (`git.moderntv.eu`), optional — devs | `glab` CLI: `brew install glab`, `glab auth login --hostname git.moderntv.eu` | `glab api --hostname git.moderntv.eu user` → username | `"gitlab": {"cli": "glab", "host": "git.moderntv.eu", "morning": "MRs waiting for my review"}` |
| GitHub, optional | `gh auth login` | `gh api user --jq .login` | `"github": {"cli": "gh", "morning": "PRs waiting for my review"}` |
| Grafana (`monitorer.moderntv.eu`), optional — technical roles | local-scope server with the user's own read-only service-account token; the user runs in their terminal: `claude mcp add grafana --scope local -e GRAFANA_URL=https://monitorer.moderntv.eu -e GRAFANA_SERVICE_ACCOUNT_TOKEN=<token> -- mcp-grafana -t stdio --disable-write` (binary: `go install github.com/grafana/mcp-grafana/cmd/mcp-grafana@latest` or a release from github.com/grafana/mcp-grafana) <!-- TODO owner: who issues Grafana service-account tokens (Viewer) to colleagues --> | list datasources, 1 result | none (ad-hoc use, not in /morning) |

A connector the user skips is simply absent from `integrations`; never nag on re-runs.
