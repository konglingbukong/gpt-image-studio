---
name: gpt-image
description: Generate images with the official OpenAI gpt-image-2.5 API using the user's own API key — text-to-image, reference images, mask inpainting; 1K/2K/4K at any aspect ratio, quality low…max; saves locally and reports the cost of every run. Use when the user asks to generate / draw / create an image, poster, cover, portrait, character sheet or scene, or gives specs like 2K, 4K, 16:9, high, max. 用用户自己的 OpenAI key 出图（出图 / 生图 / 画一张 / 海报 / 封面 / 定妆照 / 四视图 / 场景图）。
---

# gpt-image: generate images with the official API

Costs are charged to the user's own OpenAI API balance. The scripts use only the Python standard library — nothing to install.

**Read local rules first:** if `rules.local.md` exists in this folder, read it before anything else. It holds this machine's user preferences (default specs, prompt habits, environment notes) and overrides this file where they conflict. Reply to the user in their own language.

`<skill folder>` below means the folder containing this SKILL.md.

## How to call it

Always write the prompt to a UTF-8 text file first and pass it with `--prompt-file` — long non-ASCII prompts on the command line get mangled by shells.

```
python <skill folder>/scripts/gen.py --prompt-file <p.txt> --size "2K 16:9" --quality high --name <short-name>
```

**If `python` isn't found** (some agent sandboxes don't have the full PATH), try `python3`, then `py -3`, then the full path — on Windows usually `%LOCALAPPDATA%\Programs\Python\Python3xx\python.exe`. If `rules.local.md` gives this machine's full command, use it as-is.

| Option | Values | Default |
|---|---|---|
| `--size` | exact `2560x1440`; `1K`/`2K`/`4K` + ratio (e.g. `"2K 9:16"`); or `auto` | `2K 16:9` |
| `--quality` | `low` `medium` `high` `xhigh` `max` `auto` | `high` |
| `--model` | `gpt-image-2.5-sunburst` / `gpt-image-2.5-flare` | sunburst |
| `--ref` | reference image path, repeatable (up to 16); uses the edits endpoint | none |
| `--mask` | PNG mask, transparent = area to repaint; use with `--ref` | none |
| `--n` | number of images | 1 |
| `--moderation` | `auto`; switch to `low` if normal content gets blocked | auto |
| `--out-dir` | output folder | `out_dir` in `config.json`, default `~/Pictures/gpt-image` |
| `--dry-run` / `--check` | print the request / test key + network — both free | |
| `--json` | print one JSON line instead of text (for tools; see docs/INTEGRATIONS.md) | |

Size limits: sides are multiples of 16, long side ≤ 3840, aspect ratio ≤ 3:1, total pixels between 655,360 and 8,294,400. Shorthand is converted automatically, e.g. `4K 1:1` → 2880x2880, `2K 9:16` → 1440x2560.

Each image is saved next to a `.json` record with the prompt, parameters, timing, usage and cost, so it can be reproduced later.

**Always tell the user what it cost.** The script ends with "Cost" and "Today / This month" lines — relay them. Cost = the usage OpenAI returns × `rates` in `config.json` (USD per 1M tokens); update `rates` if OpenAI changes prices.

Show the user the image afterwards, using whatever your environment offers for sending files or displaying images.

**Default spending rules** (unless `rules.local.md` says otherwise): with no spec requested, use 2K + high; when the user gives a spec, follow it — don't upgrade on your own; for several images, or 4K / xhigh / max, tell the user the rough cost first.

## Web workbench (optional)

`web/server.py` is a local web page at http://127.0.0.1:8765 (this computer only). The user starts it with `start.bat` (Windows) or `start.sh` (macOS / Linux) in this folder. The page and the script share one output folder:
- While you generate, the script writes a marker into `<out_dir>/.running/`. The page polls it every 2 s and shows "<name> is generating" (name = `config.agent_name`) with a timer, then the result. So when the user says they're watching the page, just call `gen.py` as usual.
- **Don't change `--out-dir`** — the page only watches `out_dir` from `config.json`, so images saved elsewhere won't show up.
- The page's Settings read and write `config.json`, which the script also reads, so defaults the user changes there apply to your runs too.

The same page can be hosted on GitHub Pages: on a computer running the local service it connects to it automatically; elsewhere it runs in browser mode (key and images stay in that browser).

**Balance:** OpenAI has no balance API. The balance is estimated as the calibrated amount (`config.balance`) minus spending since then; with an `admin_key`, spending comes from the `/organization/costs` billing API. When the user asks how much is left, read `balance` from `http://127.0.0.1:8765/api/status` if the page is running, otherwise compute it the same way.

## Troubleshooting

- `Can't reach OpenAI`: usually the network. If a proxy is needed, set `"proxy": "http://127.0.0.1:PORT"` in `config.json`.
- `No API key found`: add it in the web page under Settings → API, put `api_key` in `config.json`, or set `OPENAI_API_KEY`.
- `OpenAI error 400`: read which parameter it complains about — usually an invalid size or a wrong model name.
- Blocked by moderation: if the content is fine, retry with `--moderation low` (the edits endpoint doesn't take this option).
- Messages are in English by default; `"lang": "zh"` in `config.json` switches them to Chinese.
