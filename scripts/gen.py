"""Generate images with the official OpenAI Images API (gpt-image-2.5). Python standard library only.

Examples:
  python gen.py --prompt-file p.txt --size "2K 16:9" --quality high --name cover
  python gen.py --prompt "an orange cat" --size 1024x1024 --quality low
  python gen.py --prompt-file p.txt --ref a.png --ref b.jpg --size "2K 9:16"   # with references (edits endpoint)
  python gen.py --check                                                        # test key + network, free
  python gen.py ... --json                                                     # one-line JSON result for tools
"""
import argparse
import base64
import contextlib
import json
import math
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from messages import set_lang, tr  # noqa: E402

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE.parent / "config.json"
API = "https://api.openai.com/v1"

# Size limits (gpt-image-2.5): sides are multiples of 16, long side <= 3840, ratio <= 3:1, total pixels in this range
MIN_PIXELS, MAX_PIXELS, MAX_EDGE = 655_360, 8_294_400, 3840
TIER_LONG_EDGE = {"1K": 1536, "2K": 2560, "4K": 3840}


# USD per 1M tokens — gpt-image-2.5 list prices at the time of writing; override with "rates" in config.json
DEFAULT_RATES = {"text_in": 5, "image_in": 8, "image_out": 30}


def calc_cost(usage, cfg):
    """USD cost of one call from its usage; None if there is no usage."""
    if not usage:
        return None
    rates = {**DEFAULT_RATES, **cfg.get("rates", {})}
    ind = usage.get("input_tokens_details") or {}
    outd = usage.get("output_tokens_details") or {}
    text_in = ind.get("text_tokens", usage.get("input_tokens", 0) - ind.get("image_tokens", 0))
    img_in = ind.get("image_tokens", 0)
    img_out = outd.get("image_tokens", usage.get("output_tokens", 0))
    usd = (text_in * rates["text_in"] + img_in * rates["image_in"] + img_out * rates["image_out"]) / 1_000_000
    return round(usd, 5)


FX_SYMBOL = {"CNY": "¥", "JPY": "¥", "KRW": "₩", "RUB": "₽", "EUR": "€", "GBP": "£", "TWD": "NT$", "HKD": "HK$"}


def fmt_cost(usd, cfg):
    """$0.0560 (≈ ¥0.40). Second currency from fx_code / fx_rate; older configs with only usd_to_cny mean CNY."""
    code, rate = cfg.get("fx_code"), cfg.get("fx_rate")
    if code is None and cfg.get("usd_to_cny"):
        code, rate = "CNY", cfg["usd_to_cny"]
    if not code or not rate:
        return f"${usd:.4f}"
    v = usd * float(rate)
    return f"${usd:.4f} (≈ {FX_SYMBOL.get(code, code + ' ')}{v:,.0f})" if float(rate) >= 100 else f"${usd:.4f} (≈ {FX_SYMBOL.get(code, code + ' ')}{v:.2f})"


def spend_summary(out_dir):
    """Spending today / this month / total, summed from the JSON records in the output folder."""
    today = datetime.now().strftime("%Y%m%d")
    month = today[:6]
    tot = {"today": 0.0, "month": 0.0, "all": 0.0, "count_today": 0}
    for f in Path(out_dir).glob("*.json"):
        try:
            m = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        c = m.get("cost_usd")
        if c is None:
            c = calc_cost(m.get("usage"), {}) or 0
        tot["all"] += c
        if m.get("time", "").startswith(month):
            tot["month"] += c
        if m.get("time", "").startswith(today):
            tot["today"] += c
            tot["count_today"] += 1
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in tot.items()}


def load_config():
    global API
    cfg = {}
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    API = (cfg.get("api_url") or "https://api.openai.com/v1").rstrip("/")
    set_lang(cfg)
    return cfg


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def load_key(cfg):
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"].strip()
    if cfg.get("api_key"):
        return cfg["api_key"].strip()
    key_file = cfg.get("key_file")
    if key_file and Path(key_file).exists():
        for line in Path(key_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit(tr("no_key"))


def build_opener(cfg):
    proxy = os.environ.get("GPT_IMAGE_PROXY") or cfg.get("proxy")
    if proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener()  # no proxy configured: follow the system proxy settings


def _snap(v):
    return max(16, int(v) // 16 * 16)


def parse_size(text):
    """Accepts '2560x1440', 'auto', or shorthand like '2K 16:9' / '4k 9:16' / '1K 1:1'."""
    t = text.strip().replace("×", "x").replace("*", "x")
    if t.lower() == "auto":
        return "auto"
    if "x" in t.lower() and ":" not in t:
        w, h = (int(p) for p in t.lower().split("x"))
        return check_size(w, h)
    parts = t.upper().split()
    if len(parts) != 2 or parts[0] not in TIER_LONG_EDGE or ":" not in parts[1]:
        sys.exit(tr("size_bad", s=text))
    rw, rh = (float(p) for p in parts[1].split(":"))
    long_edge = TIER_LONG_EDGE[parts[0]]
    if rw == rh and parts[0] == "1K":
        long_edge = 1024
    if rw >= rh:
        w, h = long_edge, long_edge * rh / rw
    else:
        w, h = long_edge * rw / rh, long_edge
    # scale down proportionally when over the pixel cap (e.g. 4K 1:1 -> 2880x2880)
    if w * h > MAX_PIXELS:
        s = math.sqrt(MAX_PIXELS / (w * h))
        w, h = w * s, h * s
    if w * h < MIN_PIXELS:
        s = math.sqrt(MIN_PIXELS / (w * h))
        w, h = math.ceil(w * s / 16) * 16, math.ceil(h * s / 16) * 16
    return check_size(_snap(w), _snap(h))


def check_size(w, h):
    problems = []
    if w % 16 or h % 16:
        problems.append(tr("size_16"))
    if max(w, h) > MAX_EDGE:
        problems.append(tr("size_edge", n=MAX_EDGE))
    if max(w, h) / min(w, h) > 3:
        problems.append(tr("size_ratio"))
    if not MIN_PIXELS <= w * h <= MAX_PIXELS:
        problems.append(tr("size_px", lo=MIN_PIXELS, hi=MAX_PIXELS, n=w * h))
    if problems:
        sys.exit(tr("size_invalid", s=f"{w}x{h}", p="; ".join(problems)))
    return f"{w}x{h}"


def request(opener, req, timeout):
    try:
        with opener.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:
            msg = body[:800]
        sys.exit(tr("openai_err", code=e.code, msg=msg))
    except urllib.error.URLError as e:
        sys.exit(tr("cant_reach", e=e.reason))
    except (ConnectionError, TimeoutError, OSError) as e:  # dropped connection / proxy hiccup / read timeout
        sys.exit(tr("cant_reach", e=f"{type(e).__name__}: {e}"))


def post_json(opener, key, path, payload, timeout):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    return request(opener, req, timeout)


def post_multipart(opener, key, path, fields, files, timeout):
    boundary = uuid.uuid4().hex
    chunks = []
    for name, value in fields.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    for name, fp in files:
        mime = mimetypes.guess_type(fp.name)[0] or "application/octet-stream"
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{fp.name}"\r\nContent-Type: {mime}\r\n\r\n'
        chunks.append(head.encode("utf-8") + fp.read_bytes() + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    req = urllib.request.Request(
        API + path,
        data=b"".join(chunks),
        headers={"Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    return request(opener, req, timeout)


def write_failed(out_dir, stamp, name, endpoint, params, refs, error, secs):
    """Keep a record for failures too (no image) so the web UI can show them under "Failed"."""
    meta = {"time": stamp, "endpoint": endpoint, "seconds": round(secs, 1), "params": params,
            "refs": refs, "status": "failed", "error": error, "cost_usd": 0, "files": []}
    (Path(out_dir) / f"{stamp}_{name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


@contextlib.contextmanager
def running_marker(out_dir, stamp, name, params, n_refs, source):
    """While generating, leave a marker in out_dir/.running/; the web UI polls it to show progress."""
    d = Path(out_dir) / ".running"
    d.mkdir(parents=True, exist_ok=True)
    marker = d / f"{stamp}_{uuid.uuid4().hex[:6]}.json"
    info = {"started": time.time(), "name": name, "source": source, "refs": n_refs,
            "size": params["size"], "quality": params["quality"], "model": params["model"], "prompt": params["prompt"]}
    marker.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    try:
        yield
    finally:
        marker.unlink(missing_ok=True)


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Generate images with gpt-image-2.5")
    ap.add_argument("--prompt", help="prompt text (use --prompt-file for long prompts)")
    ap.add_argument("--prompt-file", help="UTF-8 text file containing the prompt")
    ap.add_argument("--model", default=cfg.get("model", "gpt-image-2.5-sunburst"))
    ap.add_argument("--size", default=cfg.get("size", "2K 16:9"), help="2560x1440 / '2K 16:9' / auto")
    ap.add_argument("--quality", default=cfg.get("quality", "high"), help="low / medium / high / xhigh / max / auto")
    ap.add_argument("--n", type=int, default=1, help="number of images")
    ap.add_argument("--ref", action="append", default=[], help="reference image path, repeatable (uses the edits endpoint)")
    ap.add_argument("--mask", help="inpainting mask PNG (transparent = area to repaint)")
    ap.add_argument("--format", default=cfg.get("format", "png"), choices=["png", "jpeg", "webp"])
    ap.add_argument("--moderation", default=cfg.get("moderation", "auto"), choices=["auto", "low"])
    ap.add_argument("--background", choices=["auto", "opaque", "transparent"])
    ap.add_argument("--out-dir", default=cfg.get("out_dir") or str(Path.home() / "Pictures" / "gpt-image"))
    ap.add_argument("--name", default="img", help="file name prefix")
    ap.add_argument("--timeout", type=int, default=900, help="seconds; 4K / max take longer")
    ap.add_argument("--dry-run", action="store_true", help="print the request without calling the API")
    ap.add_argument("--check", action="store_true", help="test key and network only (free)")
    ap.add_argument("--json", action="store_true",
                    help="print a single JSON line (for tools / agent integrations; see docs/INTEGRATIONS.md)")
    a = ap.parse_args()
    global JSON_MODE
    JSON_MODE = a.json

    opener = build_opener(cfg)

    if a.check:
        key = load_key(cfg)
        req = urllib.request.Request(f"{API}/models/{a.model}", headers={"Authorization": f"Bearer {key}"})
        info = request(opener, req, 60)
        if JSON_MODE:
            return emit({"ok": True, "action": "check", "model": info.get("id")})
        print(tr("check_ok", m=info.get("id")))
        return

    if a.prompt_file:
        prompt = Path(a.prompt_file).read_text(encoding="utf-8").strip()
    elif a.prompt:
        prompt = a.prompt.strip()
    else:
        sys.exit(tr("need_prompt"))

    size = parse_size(a.size)
    refs = [Path(p) for p in a.ref]
    for p in refs + ([Path(a.mask)] if a.mask else []):
        if not p.exists():
            sys.exit(tr("file_missing", p=p))

    params = {"model": a.model, "prompt": prompt, "size": size, "quality": a.quality, "n": a.n, "output_format": a.format}
    if a.background:
        params["background"] = a.background
    endpoint = "/images/edits" if refs else "/images/generations"
    if not refs:
        params["moderation"] = a.moderation

    if a.dry_run and JSON_MODE:
        return emit({"ok": True, "action": "dry_run", "endpoint": endpoint, "refs": [str(p) for p in refs], "params": params})
    shown = {k: (v if k != "prompt" else (v[:80] + "…" if len(v) > 80 else v)) for k, v in params.items()}
    say(tr("plan", ep=endpoint, n=len(refs), params=json.dumps(shown, ensure_ascii=False)))
    if a.dry_run:
        return
    key = load_key(cfg)

    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    t0 = time.time()
    try:
        with running_marker(out_dir, stamp, a.name, params, len(refs), source="agent"):
            if refs:
                fields = {k: str(v) for k, v in params.items()}
                files = [("image[]", p) for p in refs] + ([("mask", Path(a.mask))] if a.mask else [])
                resp = post_multipart(opener, key, endpoint, fields, files, a.timeout)
            else:
                resp = post_json(opener, key, endpoint, params, a.timeout)
    except SystemExit as e:
        write_failed(out_dir, stamp, a.name, endpoint, params, [str(p) for p in refs], str(e), time.time() - t0)
        raise
    secs = time.time() - t0
    saved = []
    for i, item in enumerate(resp.get("data", []), 1):
        suffix = f"_{i}" if len(resp["data"]) > 1 else ""
        path = out_dir / f"{stamp}_{a.name}{suffix}.{a.format}"
        path.write_bytes(base64.b64decode(item["b64_json"]))
        saved.append(str(path))

    cost = calc_cost(resp.get("usage"), cfg)
    meta = {
        "time": stamp, "endpoint": endpoint, "seconds": round(secs, 1),
        "params": params, "refs": [str(p) for p in refs], "mask": a.mask,
        "usage": resp.get("usage"), "cost_usd": cost, "files": saved,
    }
    (out_dir / f"{stamp}_{a.name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    s = spend_summary(out_dir)
    if JSON_MODE:
        return emit({"ok": True, "action": "generate", "files": saved, "size": size, "quality": a.quality,
                     "model": a.model, "seconds": round(secs, 1), "cost_usd": cost,
                     "fx": fmt_cost(cost, cfg) if cost is not None else None,
                     "today_usd": s["today"], "month_usd": s["month"], "record": str(out_dir / f"{stamp}_{a.name}.json")})
    print(tr("done", s=secs, size=size, q=a.quality))
    for p in saved:
        print(tr("saved", p=p))
    if cost is not None:
        print(tr("cost", c=fmt_cost(cost, cfg)))
        print(tr("cost_sum", today=fmt_cost(s["today"], cfg), n=s["count_today"], month=fmt_cost(s["month"], cfg)))
    if resp.get("usage"):
        print(tr("usage", u=json.dumps(resp["usage"], ensure_ascii=False)))


# ---- output: human-readable text, or a single JSON line with --json ----
JSON_MODE = False


def say(text):
    if not JSON_MODE:
        print(text)


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        main()
    except SystemExit as e:
        # all error paths call sys.exit("message"); with --json wrap it as JSON, exit code stays 1
        if JSON_MODE and isinstance(e.code, str):
            emit({"ok": False, "error": e.code})
            sys.exit(1)
        raise
