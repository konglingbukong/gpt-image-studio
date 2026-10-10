# GPT Image Studio

**English** · [中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Русский](README.ru.md)

**A workbench for OpenAI's `gpt-image-2.5` using your own API key. Ask your AI agent for an image in a single sentence, then watch it appear in a local web gallery with its cost and your remaining balance.**

<!-- screenshot: docs/screenshot.png -->

## Features

- **Generate from any AI agent.** Ask Claude Code, Codex or another agent that can run commands for "a 2K 16:9 image of …". It calls the official API, saves the file locally and tells you what the image cost.
- **Live web gallery.** While an agent is generating, a "generating…" card with a timer appears on the page, and the result replaces it when it's ready. You can also generate directly from the page.
- **All the parameters.** gpt-image-2.5 sunburst / flare; 1K / 2K / 4K at any aspect ratio, up to 3840×2160; quality from `low` to **`xhigh` / `max`**; up to 16 reference images; mask inpainting.
- **Cost tracking.** The cost of every image is calculated from the token usage OpenAI actually returns. Spending is totalled for today, this month and overall. Calibrate your balance once and the remaining amount is tracked for you (OpenAI has no balance API, so this is the most accurate method available).
- **Gallery tools.** Favorites, filters by status (completed / generating / failed), search, one-click reuse of settings, and "use as reference" to keep iterating on a result. Deleted items go to a `.trash` folder instead of being erased.
- **Use it anywhere.** The same page can be hosted on GitHub Pages. On a computer that runs the local service it connects to that service automatically; anywhere else it runs in *browser mode*, where your key and images stay in that browser.
- **5 languages.** English, 中文, 日本語, 한국어 and Русский. The language follows your browser and can be switched in the page.
- **Zero dependencies.** You only need Python 3.9 or later. Nothing to `pip install`.

## Install

### As a Claude Code skill (recommended)

```bash
git clone https://github.com/konglingbukong/gpt-image-studio ~/.claude/skills/gpt-image
```

1. Run `start.bat` (Windows) or `sh start.sh` (macOS / Linux). Your browser opens `http://127.0.0.1:8765`.
2. Go to Settings → API, enter your OpenAI API key, and click "Test connection" (free).
3. Ask Claude Code for an image.

You can also provide the key through the `OPENAI_API_KEY` environment variable, or in `config.json` (see `config.example.json`; `config.json` is git-ignored).

### Just the web page (nothing to install)

Open **https://konglingbukong.github.io/gpt-image-studio/** and enter your key in Settings. The page runs in browser mode: your key and images stay in your browser, and the browser talks to OpenAI directly with no third-party server in between.

### Other agents (Codex, Cursor, Gemini, Antigravity, WorkBuddy …)

Pick whichever of these your agent supports:

**① MCP (supported by most agents).** Register `scripts/mcp_server.py` as an MCP server. Your agent gets three tools: `generate_image`, `check_connection` and `get_spending`. Replace `<path>` with the folder you cloned:

- **Claude Code:** `claude mcp add gpt-image -- python <path>/scripts/mcp_server.py`
- **Codex** (`~/.codex/config.toml`):
  ```toml
  [mcp_servers.gpt-image]
  command = "python"
  args = ["<path>/scripts/mcp_server.py"]
  ```
- **Cursor / Gemini CLI / other JSON-configured clients** (`mcpServers`):
  ```json
  { "mcpServers": { "gpt-image": { "command": "python", "args": ["<path>/scripts/mcp_server.py"] } } }
  ```

**② Skill folder.** Agents that support the `SKILL.md` format (Codex, WorkBuddy …) can use this folder as a skill: drop it into their skills directory.

**③ Instructions file.** Any other agent that can run shell commands can follow [AGENTS.md](AGENTS.md).

Whichever route you choose, images land in the same folder and show up live in the web workbench.

**Verified:** Claude Code, Codex (including the ChatGPT desktop app), WorkBuddy, Antigravity and DeepSeek Harness (dsh). The full list, per-agent setup notes, interface contracts and the steps for adding a new agent are in **[docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)**. If your agent isn't supported yet, open an "Integration request" issue, or wire it up yourself following [CONTRIBUTING.md](CONTRIBUTING.md) and send a PR.

## Command line

```bash
python scripts/gen.py --prompt-file prompt.txt --size "2K 16:9" --quality high --name cover
python scripts/gen.py --prompt "an orange cat" --size 1024x1024 --quality low
python scripts/gen.py --prompt-file p.txt --ref face.png --ref outfit.png --size "4K 9:16"
python scripts/gen.py --check          # test key + network, free
python scripts/gen.py ... --json       # one JSON line, for scripts and integrations
```

All parameters are documented in [SKILL.md](SKILL.md). Command-line messages are in English by default; set `"lang": "zh"` in `config.json` for Chinese.

## Personal preferences

Create `rules.local.md` in the skill folder and write down your own preferences, such as default specs and prompt habits. Agents read it before generating. It is git-ignored.

## Security

- The local service listens on `127.0.0.1` only and checks both `Host` and `Origin`. It accepts requests only from the local page and from the sites listed in `allowed_origins` in `config.json`, so other web pages can't use it to spend your money.
- Your key is only ever sent to the API URL you configure (OpenAI by default).

## Pricing note

Costs are calculated from the `rates` in `config.json`, in USD per 1M tokens. The defaults are gpt-image-2.5 prices at the time of writing: text input 5, image input 8, image output 30. **If OpenAI changes its prices, update them under Settings → Pricing.** The balance shown is an estimate; your OpenAI dashboard is the source of truth.

## Credits

The UI layout is inspired by [CookSleep/gpt_image_playground](https://github.com/CookSleep/gpt_image_playground) (MIT). The code was written independently.

## License

[MIT](LICENSE)
