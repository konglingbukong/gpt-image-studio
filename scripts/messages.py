"""Messages printed by the command line / local server / MCP server, in English (default) and Chinese.

The language comes from "lang" in config.json ("en" or "zh"), or the GPT_IMAGE_LANG environment variable.
The web UI has its own 5-language pack (web/i18n.js); these strings are mostly read by AI agents,
which relay them to the user in the user's own language anyway.
"""
import os

MSG = {
    "no_key": {
        "en": "No API key found: add it in the web workbench under Settings → API, put \"api_key\" in config.json, or set the OPENAI_API_KEY environment variable",
        "zh": "找不到 API key：在网页工作台的 设置 → API 配置 里填，或在 config.json 里写 \"api_key\"，或设置环境变量 OPENAI_API_KEY"},
    "size_bad": {
        "en": "Can't read size {s!r}: use 2560x1440 or '2K 16:9'",
        "zh": "看不懂尺寸 {s!r}：用 2560x1440 或 '2K 16:9' 这种写法"},
    "size_16": {"en": "both sides must be multiples of 16", "zh": "边长要是 16 的倍数"},
    "size_edge": {"en": "the long side can't exceed {n}", "zh": "长边不能超过 {n}"},
    "size_ratio": {"en": "aspect ratio can't exceed 3:1", "zh": "长宽比不能超过 3:1"},
    "size_px": {"en": "total pixels must be between {lo:,} and {hi:,} (now {n:,})", "zh": "总像素要在 {lo:,}～{hi:,} 之间（现在 {n:,}）"},
    "size_invalid": {"en": "Size {s} is invalid: {p}", "zh": "尺寸 {s} 不合法：{p}"},
    "openai_err": {"en": "OpenAI error {code}: {msg}", "zh": "OpenAI 返回错误 {code}：{msg}"},
    "cant_reach": {
        "en": "Can't reach OpenAI: {e}\n(Usually a network issue — if you need a proxy, set \"proxy\" in config.json, e.g. http://127.0.0.1:PORT)",
        "zh": "连不上 OpenAI：{e}\n（多半是网络问题：需要代理的话在 config.json 里填 proxy，比如 http://127.0.0.1:端口）"},
    "check_ok": {"en": "OK: key is valid, network is fine, model {m} is available", "zh": "OK：key 有效、网络通，模型 {m} 可用"},
    "need_prompt": {"en": "Provide --prompt or --prompt-file", "zh": "要提供 --prompt 或 --prompt-file"},
    "file_missing": {"en": "File not found: {p}", "zh": "找不到文件：{p}"},
    "plan": {"en": "Endpoint {ep}  references {n}  params {params}", "zh": "接口 {ep}  参考图 {n} 张  参数 {params}"},
    "done": {"en": "Done in {s:.0f} s, size {size}, quality {q}", "zh": "完成，用时 {s:.0f} 秒，尺寸 {size}，质量 {q}"},
    "saved": {"en": "Saved: {p}", "zh": "已保存：{p}"},
    "cost": {"en": "Cost: {c}", "zh": "本次花费：{c}"},
    "cost_sum": {"en": "Today: {today} ({n} runs)  This month: {month}", "zh": "今天累计：{today}（{n} 次）  本月：{month}"},
    "usage": {"en": "Usage: {u}", "zh": "用量：{u}"},
    # server.py
    "empty_prompt": {"en": "The prompt is empty", "zh": "提示词是空的"},
    "not_found": {"en": "Record not found", "zh": "找不到这条记录"},
    "admin_fail": {"en": "Admin key query failed ({code}); estimating from this tool's records", "zh": "管理员 key 查询失败（{code}），先用本工具的记录估算"},
    "billing_fail": {"en": "Billing query failed: {e}", "zh": "查询账单失败：{e}"},
    "src_env": {"en": "environment variable", "zh": "环境变量"},
    "src_cfg": {"en": "config file", "zh": "配置文件"},
    "test_ok": {"en": "Connection OK ({ms} ms), model {m} available", "zh": "连接正常（{ms} ms），模型 {m} 可用"},
    "test_err": {"en": "OpenAI returned {code}: {msg}", "zh": "OpenAI 返回 {code}：{msg}"},
    "test_conn": {"en": "Can't connect: {e} (set a proxy above if you need one, e.g. http://127.0.0.1:PORT)",
                  "zh": "连不上：{e}（需要代理的话在上面填，比如 http://127.0.0.1:端口）"},
    "origin_denied": {"en": "Requests from {o} are not allowed (add it to allowed_origins in config.json)",
                      "zh": "不允许来自 {o} 的请求（可在 config.json 的 allowed_origins 里添加）"},
    "save_fail": {"en": "Save failed: {e}", "zh": "保存失败：{e}"},
    "server_up": {"en": "gpt-image workbench running at {url}\nImages are saved in: {d}", "zh": "gpt-image 网页已启动：{url}\n图片保存在：{d}"},
    # mcp_server.py
    "timeout": {"en": "Generation timed out", "zh": "出图超时了"},
    "no_output": {"en": "(no output)", "zh": "（没有输出）"},
    "sp_today": {"en": "Today: {c} ({n} runs)", "zh": "今天：{c}（{n} 次）"},
    "sp_month": {"en": "This month: {c}", "zh": "本月：{c}"},
    "sp_all": {"en": "Total: {c}", "zh": "累计：{c}"},
    "sp_bal": {"en": "Estimated balance: {c} (calibrated at ${amt:.2f}, this tool spent ${spent:.4f} since; your OpenAI dashboard is authoritative)",
               "zh": "估算余额：{c}（校准时 ${amt:.2f}，之后本工具花了 ${spent:.4f}；以 OpenAI 后台为准）"},
    "sp_nobal": {"en": "Balance: not calibrated yet (set it once in the web workbench under Settings → Balance)",
                 "zh": "余额：还没校准（在网页工作台 设置 → 余额 里填一次）"},
    "no_tool": {"en": "Unknown tool: {name}", "zh": "没有这个工具：{name}"},
}

LANG = "en"


def set_lang(cfg):
    global LANG
    lang = (os.environ.get("GPT_IMAGE_LANG") or (cfg or {}).get("lang") or "en").lower()[:2]
    LANG = lang if lang in ("en", "zh") else "en"


def tr(key, **kw):
    m = MSG.get(key, {})
    s = m.get(LANG) or m.get("en") or key
    return s.format(**kw) if kw else s
