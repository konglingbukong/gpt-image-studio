"""MCP server (stdio) for gpt-image, so any MCP-capable agent can generate images. Python standard library only.

Register it (syntax varies by client, the command is the same):
  command: python
  args:    ["<skill folder>/scripts/mcp_server.py"]

Tools:
  generate_image   text-to-image / references / mask; returns saved paths and cost
  check_connection test key and network (free)
  get_spending     spending today / this month / total, plus the estimated balance

Generation is delegated to gen.py in this folder (same logic as the CLI and the web UI),
so the web workbench still shows progress live.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen  # noqa: E402

SERVER_INFO = {"name": "gpt-image", "version": "0.4"}
SUPPORTED = ["2025-06-18", "2025-03-26", "2024-11-05"]

TOOLS = [
    {
        "name": "generate_image",
        "description": (
            "Generate an image with OpenAI gpt-image-2.5 using the user's own API key; saves it locally and returns the file paths and cost. "
            "Without a requested spec use 2K 16:9 + high (about $0.06). 4K, xhigh, max or several images cost more — tell the user the rough cost first. "
            "Always tell the user what each run cost."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "prompt (positive description of the image)"},
                "size": {"type": "string", "description": "e.g. \"2K 16:9\", \"4K 9:16\", \"1K 1:1\", \"2560x1440\" or \"auto\"", "default": "2K 16:9"},
                "quality": {"type": "string", "enum": ["low", "medium", "high", "xhigh", "max", "auto"], "default": "high"},
                "model": {"type": "string", "enum": ["gpt-image-2.5-sunburst", "gpt-image-2.5-flare"], "default": "gpt-image-2.5-sunburst"},
                "n": {"type": "integer", "minimum": 1, "maximum": 8, "default": 1, "description": "number of images"},
                "reference_images": {"type": "array", "items": {"type": "string"}, "description": "absolute local paths of reference images, up to 16"},
                "mask": {"type": "string", "description": "absolute path of a mask PNG (transparent = repaint); requires reference images"},
                "name": {"type": "string", "description": "short file name prefix", "default": "img"},
                "moderation": {"type": "string", "enum": ["auto", "low"], "default": "auto"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "check_connection",
        "description": "Check that the API key and network work (free).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_spending",
        "description": "Get spending today / this month / total and the estimated remaining balance.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def run_gen(args, timeout):
    p = subprocess.run([sys.executable, str(HERE / "gen.py"), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr.strip() else "")
    return p.returncode, out.strip()


def tool_generate(a):
    prompt = (a.get("prompt") or "").strip()
    if not prompt:
        return gen.tr("empty_prompt"), True
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(prompt)
        pf = f.name
    try:
        args = ["--prompt-file", pf, "--size", a.get("size") or "2K 16:9", "--quality", a.get("quality") or "high",
                "--n", str(int(a.get("n") or 1)), "--name", a.get("name") or "img",
                "--moderation", a.get("moderation") or "auto"]
        if a.get("model"):
            args += ["--model", a["model"]]
        for r in a.get("reference_images") or []:
            args += ["--ref", r]
        if a.get("mask"):
            args += ["--mask", a["mask"]]
        cfg = gen.load_config()
        code, out = run_gen(args, int(cfg.get("timeout", 900)) + 60)
        return out or gen.tr("no_output"), code != 0
    except subprocess.TimeoutExpired:
        return gen.tr("timeout"), True
    finally:
        try:
            os.unlink(pf)
        except OSError:
            pass


def tool_check():
    code, out = run_gen(["--check"], 90)
    return out, code != 0


def tool_spending():
    cfg = gen.load_config()
    out_dir = Path(cfg.get("out_dir") or str(Path.home() / "Pictures" / "gpt-image"))
    s = gen.spend_summary(out_dir)
    lines = [gen.tr("sp_today", c=gen.fmt_cost(s["today"], cfg), n=s["count_today"]),
             gen.tr("sp_month", c=gen.fmt_cost(s["month"], cfg)),
             gen.tr("sp_all", c=gen.fmt_cost(s["all"], cfg))]
    src = cfg.get("balance_source") or "auto"
    if src == "relay" or (src == "auto" and "api.openai.com" not in gen.API):
        try:
            rb = gen.relay_balance(gen.build_opener(cfg), gen.load_key(cfg))
        except SystemExit:
            rb = None
        if rb:
            lines.append(gen.tr("sp_relay", c=gen.fmt_cost(rb["remaining"], cfg), total=rb["total"], used=rb["used"]))
            return "\n".join(lines), False
    b = cfg.get("balance") or {}
    if b.get("amount") is not None:
        since = datetime.fromtimestamp(b.get("at") or time.time()).strftime("%Y%m%d-%H%M%S")
        spent = 0.0
        for f in out_dir.glob("*.json"):
            try:
                m = json.loads(f.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            if m.get("time", "") >= since:
                spent += m.get("cost_usd") or 0
        lines.append(gen.tr("sp_bal", c=gen.fmt_cost(float(b["amount"]) - spent, cfg), amt=float(b["amount"]), spent=spent))
    else:
        lines.append(gen.tr("sp_nobal"))
    return "\n".join(lines), False


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:  # notification (e.g. notifications/initialized): no reply
        return None
    if method == "initialize":
        want = (msg.get("params") or {}).get("protocolVersion")
        return {"protocolVersion": want if want in SUPPORTED else SUPPORTED[0],
                "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO,
                "instructions": "gpt-image: generate images with the user's own OpenAI key. Tell the user the cost after each run; quote expensive specs first."}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        p = msg.get("params") or {}
        name, a = p.get("name"), p.get("arguments") or {}
        if name == "generate_image":
            text, err = tool_generate(a)
        elif name == "check_connection":
            text, err = tool_check()
        elif name == "get_spending":
            text, err = tool_spending()
        else:
            raise LookupError(gen.tr("no_tool", name=name))
        return {"content": [{"type": "text", "text": text}], "isError": err}
    raise LookupError(f"Method not found: {method}")


def main():
    # stdio transport: one JSON-RPC message per line; stdout carries protocol messages only, logs go to stderr
    stdin = open(sys.stdin.fileno(), "r", encoding="utf-8", closefd=False)
    stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", closefd=False, newline="\n")
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            result = handle(msg)
            if result is None:
                continue
            reply = {"jsonrpc": "2.0", "id": msg.get("id"), "result": result}
        except LookupError as e:
            reply = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32601, "message": str(e)}}
        except Exception as e:
            reply = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}}
        stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
        stdout.flush()


if __name__ == "__main__":
    main()
