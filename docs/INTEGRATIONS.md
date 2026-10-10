# Integrating with AI agents

This tool isn't tied to any one agent. It exposes **4 interfaces**, and almost every agent can use at least one:

| Interface | For | Entry point |
|---|---|---|
| **A. MCP server** | agents that support MCP (most do today) | `scripts/mcp_server.py` (stdio) |
| **B. Skill folder** | agents that support the `SKILL.md` format | the whole folder |
| **C. Command line** | any agent that can run a shell command | `scripts/gen.py` (add `--json`) |
| **D. Local HTTP API** | tools that can make HTTP requests but not run commands | `http://127.0.0.1:8765/api/*` (web service must be running) |

**Decision order:** supports MCP → A; supports SKILL.md → B (can be combined with A); can run commands → have it read [AGENTS.md](../AGENTS.md) and use C; none of these → D.

Whatever the route, images land in the same folder, show up live in the web workbench and are counted in the same spending totals.

## Verified agents

| Agent | Route | Status | Notes |
|---|---|---|---|
| Claude Code | B (skill) | ✅ verified | A also works: `claude mcp add gpt-image -- python <path>/scripts/mcp_server.py` |
| Codex (CLI / ChatGPT desktop app) | B (`~/.codex/skills/`) | ✅ verified | On Windows use the "full access" permission mode: the restricted sandbox can't run Python from the user profile and has no full PATH |
| WorkBuddy / CodeBuddy | B (desktop `~/.workbuddy/skills/`, CLI `~/.codebuddy/skills/`) | ✅ verified | Desktop and CLI use different folders — put a copy (or a link) in each |
| Antigravity | A (`~/.gemini/config/mcp_config.json`) | ✅ verified | Uses the `mcpServers` field; prefer the full path to Python as `command` |
| DeepSeek Harness (dsh) | C (in `~/.dsh/AGENTS.md`) | ✅ verified | Add a section to its global instructions file pointing at this repo's AGENTS.md |
| Cursor / Gemini CLI / other MCP clients | A | should work, not individually verified yet | PRs that confirm one and update this row are welcome |

Want an agent supported? Open an issue with the "Integration request" template, or follow the steps below and send a PR.

## Adding a new agent

1. **Find out what it supports:** MCP? `SKILL.md`? Can it run commands? Where is its global instructions file (`AGENTS.md`, `GEMINI.md`, `CLAUDE.md` …)?
2. **Pick a route** using the decision order above.
3. **Mind the Python path:** many agent sandboxes don't have the full PATH. Prefer the **full path** to Python in configs, or put a copy-paste-ready full command in `rules.local.md`.
4. **Verify (free):** ask the agent to "test the gpt-image connection". Over MCP that's `check_connection`; on the command line `gen.py --check --json` should return `{"ok": true, ...}`.
5. **Generate one cheap image:** `--size "1K 1:1" --quality low` costs about $0.006. Check that it shows up in the web workbench and that the agent reported the cost on its own.
6. Add a row to the table above and send a PR.

## Interface contracts (for integration authors)

### C. Command line `gen.py --json`

Prints **exactly one JSON line** to stdout, success or failure. Exit code is 0 on success and 1 on failure.

```jsonc
// generate succeeded
{"ok": true, "action": "generate", "files": ["/abs/path/20261010-173542_name.png"],
 "size": "1440x2560", "quality": "high", "model": "gpt-image-2.5-sunburst", "seconds": 54.6,
 "cost_usd": 0.0564, "fx": "$0.0564 (≈ ¥0.40)", "today_usd": 0.2256, "month_usd": 1.86,
 "record": "/abs/path/20261010-173542_name.json"}
// --check
{"ok": true, "action": "check", "model": "gpt-image-2.5-sunburst"}
// --dry-run
{"ok": true, "action": "dry_run", "endpoint": "/images/generations", "refs": [], "params": {...}}
// any failure
{"ok": false, "error": "human-readable message"}
```

Fields are only ever **added**, never removed or renamed.

### A. MCP tools

| Tool | Arguments | Returns |
|---|---|---|
| `generate_image` | `prompt` (required), `size`, `quality`, `model`, `n`, `reference_images[]`, `mask`, `name`, `moderation` | text: saved paths, cost, today / month totals; `isError: true` on failure |
| `check_connection` | none | text |
| `get_spending` | none | text: today / month / total spending and the estimated balance |

### D. Local HTTP API (while the web service runs)

Everything listens on `127.0.0.1:8765` only. Requests with an `Origin` header are accepted only from the local page and from sites listed in `allowed_origins` in `config.json`.

| Method | Path | Notes |
|---|---|---|
| POST | `/api/generate` | body `{prompt, size, quality, model, n, format, moderation, name, refs:[{name,data(dataURL)}], mask}`; returns the record or `{error}` |
| GET | `/api/history` | all records, newest first |
| GET | `/api/status` | running jobs, spending totals, balance |
| GET/POST | `/api/settings` | read / update settings |
| POST | `/api/test` | test the connection |

### Showing "… is generating" in the web page

If your integration doesn't go through `gen.py`, write a JSON file into `<out_dir>/.running/` while generating (format: see `running_marker` in `gen.py`) and delete it afterwards — the page shows the progress card. Then write a record JSON in the same format into `<out_dir>/` and the page shows the result.
