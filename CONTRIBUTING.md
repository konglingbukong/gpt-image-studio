# Contributing

All contributions are welcome — **especially support for more AI agents.**

## Supporting a new agent

- **Just requesting it:** open an issue with the "Integration request" template and fill in everything you can (agent name, whether it supports MCP / SKILL.md, where its config lives). The more complete, the faster.
- **Doing it yourself:** follow "Adding a new agent" in [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md), verify it, and send a PR that includes:
  - agent name and version, operating system
  - which route you used (MCP / skill / command line / HTTP), which config file, and what you put in it
  - the output of `check_connection` (or `gen.py --check --json`)
  - the result of one 1K low test image (no need to attach it — cost and time are enough)
  - a new row in the "Verified agents" table in INTEGRATIONS.md

## Translations

The web UI strings live in `web/i18n.js` (English, 中文, 日本語, 한국어, Русский). To add a language, copy the `en` block, translate it, and add the code to `LANGS`. Missing keys fall back to English. Command-line messages are in `scripts/messages.py` (English and Chinese).

## Principles

- **Zero dependencies:** Python 3.9+ standard library only; no build step for the web page. Please keep it that way.
- **Interfaces only grow:** fields of `gen.py --json`, MCP tool arguments and HTTP endpoints may be added but never removed or renamed, so other people's integrations keep working.
- **No personal data:** `config.json` and `rules.local.md` are git-ignored — still double-check for keys and local paths before committing.
- For anything touching money (pricing, balance), explain how it's calculated.

## Reporting bugs

Include your OS, Python version (`python --version`), which entry point you used (web page / command line / MCP / which agent), and the full error. **Redact your API key in screenshots and logs.**
