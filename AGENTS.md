# gpt-image — instructions for AI agents

This folder is an image generation tool: the user's own OpenAI API key + the official gpt-image-2.5 API. Full details are in `SKILL.md` in this folder. If `rules.local.md` exists (the user's personal preferences), read it first; it overrides this file where they conflict. Reply to the user in their own language.

## Three ways to use it — pick what your environment supports

1. **MCP tools** (if the user registered `scripts/mcp_server.py` as an MCP server): call `generate_image`, `check_connection`, `get_spending`.
2. **Command line** (anything that can run a shell command): write the prompt to a UTF-8 text file, then run
   ```
   python <this folder>/scripts/gen.py --prompt-file <file> --size "2K 16:9" --quality high --name <short-name>
   ```
   If `python` isn't found, try `python3`, `py -3`, or the full path (on Windows usually `%LOCALAPPDATA%\Programs\Python\Python3xx\python.exe`; use the full command from `rules.local.md` if it has one).
   Common options: `--size` (`"2K 9:16"`, `"4K 16:9"`, `2560x1440`), `--quality` (low / medium / high / xhigh / max), `--ref <image>` (repeatable), `--n <count>`, `--check` (test connection, free), `--json` (machine-readable output).
3. **Web workbench**: after the user runs `start.bat` / `start.sh`, http://127.0.0.1:8765 shows your images live.

## Rules

- It costs the user money. With no spec requested, use 2K + high (about $0.06 per image). For 4K, xhigh, max or several images, **tell the user the rough cost first**.
- **After every run, tell the user what it cost and today's total** (both are in the output), and give them the image path or show the image.
- Don't change `--out-dir`, or the web workbench won't see the image.
- On errors, pass the message to the user as-is. Common causes: no key (add it in the web page's Settings), network (set `proxy` in `config.json`), invalid size.
