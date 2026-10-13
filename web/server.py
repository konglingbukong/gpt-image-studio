"""gpt-image local workbench: run `python server.py`, then open http://127.0.0.1:8765
Listens on this computer only; the key never leaves it (only sent to the API URL). Generation reuses ../scripts/gen.py.
"""
import base64
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import gen  # noqa: E402

PORT = int(os.environ.get("GPT_IMAGE_PORT") or 8765)  # override to run a second instance
VERSION = "0.3"
CFG = {}
OUT_DIR = Path()


def reload_config():
    global CFG, OUT_DIR
    CFG = gen.load_config()
    OUT_DIR = Path(CFG.get("out_dir") or str(Path.home() / "Pictures" / "gpt-image"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)


reload_config()


def safe_name(s):
    s = "".join(c for c in (s or "img") if c not in '\\/:*?"<>|').strip()
    return s[:40] or "img"


def mask_key(k):
    return f"{k[:7]}…{k[-4:]}" if k and len(k) > 12 else ("***" if k else "")


# ---------------- generation ----------------

def generate(body):
    """body is the JSON from the page. Returns (meta, None) or (None, error message)."""
    try:
        key = gen.load_key(CFG)
        opener = gen.build_opener(CFG)
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return None, gen.tr("empty_prompt")
        size = gen.parse_size(body.get("size") or CFG.get("size", "2K 16:9"))
        fmt = body.get("format") or CFG.get("format", "png")
        params = {
            "model": body.get("model") or CFG.get("model", "gpt-image-2.5-sunburst"),
            "prompt": prompt,
            "size": size,
            "quality": body.get("quality") or CFG.get("quality", "high"),
            "n": int(body.get("n") or 1),
            "output_format": fmt,
        }
        if body.get("background") and body["background"] != "auto":
            params["background"] = body["background"]
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = safe_name(body.get("name"))

        # references / mask arrive as data URLs: save them to refs/ first (also keeps a copy), then upload
        ref_dir = OUT_DIR / "refs"
        refs = []
        for i, r in enumerate(body.get("refs") or [], 1):
            ref_dir.mkdir(parents=True, exist_ok=True)
            ext = Path(r.get("name") or "ref.png").suffix or ".png"
            p = ref_dir / f"{stamp}_{name}_ref{i}{ext}"
            p.write_bytes(base64.b64decode(r["data"].split(",", 1)[1]))
            refs.append(p)
        mask = None
        if body.get("mask"):
            ref_dir.mkdir(parents=True, exist_ok=True)
            mask = ref_dir / f"{stamp}_{name}_mask.png"
            mask.write_bytes(base64.b64decode(body["mask"]["data"].split(",", 1)[1]))

        timeout = int(CFG.get("timeout", 900))
        endpoint = "/images/edits" if refs else "/images/generations"
        if not refs:
            params["moderation"] = body.get("moderation") or CFG.get("moderation", "auto")
        params = gen.compat_params(params, CFG)
        t0 = time.time()
        try:
            with gen.running_marker(OUT_DIR, stamp, name, params, len(refs), source="web"):
                if refs:
                    fields = {k: str(v) for k, v in params.items()}
                    files = [("image[]", p) for p in refs] + ([("mask", mask)] if mask else [])
                    resp = gen.post_multipart(opener, key, endpoint, fields, files, timeout)
                else:
                    resp = gen.post_json(opener, key, endpoint, params, timeout)
        except SystemExit as e:
            gen.write_failed(OUT_DIR, stamp, name, endpoint, params, [str(p) for p in refs], str(e), time.time() - t0)
            raise
        secs = round(time.time() - t0, 1)

        saved = []
        data = resp.get("data") or []
        if not data:
            gen.write_failed(OUT_DIR, stamp, name, endpoint, params, [str(p) for p in refs], gen.tr("no_image"), secs)
            return None, gen.tr("no_image")
        for i, item in enumerate(data, 1):
            suffix = f"_{i}" if len(data) > 1 else ""
            path = OUT_DIR / f"{stamp}_{name}{suffix}.{fmt}"
            path.write_bytes(gen.image_bytes(item, opener, timeout))
            saved.append(str(path))
        meta = {
            "time": stamp, "endpoint": endpoint, "seconds": secs, "params": params,
            "refs": [str(p) for p in refs], "mask": str(mask) if mask else None,
            "usage": resp.get("usage"), "cost_usd": gen.calc_cost(resp.get("usage"), CFG, len(saved)), "files": saved,
        }
        (OUT_DIR / f"{stamp}_{name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta, None
    except SystemExit as e:  # gen.py error paths all call sys.exit("message")
        return None, str(e)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ---------------- records / status ----------------

def running():
    items = []
    for f in sorted((OUT_DIR / ".running").glob("*.json")):
        try:
            m = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if time.time() - m.get("started", 0) > 1200:  # older than 20 min = leftover from a killed process; clean up
            f.unlink(missing_ok=True)
            continue
        m["elapsed"] = round(time.time() - m["started"])
        items.append(m)
    return items


def history_sig():
    files = sorted(OUT_DIR.glob("*.json"))
    return f"{len(files)}:{files[-1].name if files else ''}"


def history(limit=500):
    items = []
    for f in sorted(OUT_DIR.glob("*.json"), reverse=True)[:limit]:
        try:
            m = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        failed = m.get("status") == "failed"
        m["files"] = [p for p in m.get("files", []) if Path(p).exists()]
        if not m["files"] and not failed:
            continue  # images were deleted by hand
        m["status"] = "failed" if failed else "done"
        if m.get("cost_usd") is None:
            m["cost_usd"] = gen.calc_cost(m.get("usage"), CFG, len(m["files"]) or 1) if m["status"] == "done" else 0
        m["id"] = f.stem
        items.append(m)
    return items


def record_path(rec_id):
    p = (OUT_DIR / f"{rec_id}.json").resolve()
    if p.parent != OUT_DIR.resolve() or not p.exists():
        return None
    return p


def set_fav(rec_id, fav):
    p = record_path(rec_id)
    if not p:
        return {"error": gen.tr("not_found")}
    m = json.loads(p.read_text(encoding="utf-8-sig"))
    if fav:
        m["fav"] = True
    else:
        m.pop("fav", None)
    p.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


def delete_record(rec_id):
    """Not a hard delete: move the record and its images into .trash so they can be restored."""
    p = record_path(rec_id)
    if not p:
        return {"error": gen.tr("not_found")}
    trash = OUT_DIR / ".trash"
    trash.mkdir(exist_ok=True)
    m = json.loads(p.read_text(encoding="utf-8-sig"))
    for f in m.get("files", []):
        fp = Path(f)
        if fp.exists() and fp.resolve().parent == OUT_DIR.resolve():
            fp.replace(trash / fp.name)
    p.replace(trash / p.name)
    return {"ok": True}


# ---------------- balance ----------------
# OpenAI has no balance API: balance = amount the user calibrated with − spending since then.
# Spending comes from /organization/costs when an admin key is set (real org-wide billing incl. other tools, may lag a few hours);
# otherwise only this tool's own records are counted.

_cost_cache = {"key": None, "at": 0, "value": None, "error": None}


def local_spend_since(ts):
    since = datetime.fromtimestamp(ts).strftime("%Y%m%d-%H%M%S")
    total = 0.0
    for f in OUT_DIR.glob("*.json"):
        try:
            m = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if m.get("time", "") >= since:
            total += m.get("cost_usd") or gen.calc_cost(m.get("usage"), CFG) or 0
    return total


def admin_spend_since(ts, admin_key):
    cache_key = (ts, admin_key)
    if _cost_cache["key"] == cache_key and time.time() - _cost_cache["at"] < 300:
        return _cost_cache["value"], _cost_cache["error"]
    opener = gen.build_opener(CFG)
    total, page, err = 0.0, None, None
    try:
        for _ in range(20):
            url = f"{gen.API}/organization/costs?start_time={int(ts)}&bucket_width=1d&limit=180"
            if page:
                url += f"&page={page}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {admin_key}"})
            with opener.open(req, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8"))
            for bucket in d.get("data", []):
                for res in bucket.get("results", []):
                    total += float((res.get("amount") or {}).get("value") or 0)
            if not d.get("has_more"):
                break
            page = d.get("next_page")
    except urllib.error.HTTPError as e:
        err = gen.tr("admin_fail", code=e.code)
        total = None
    except Exception as e:
        err = gen.tr("billing_fail", e=e)
        total = None
    _cost_cache.update(key=cache_key, at=time.time(), value=total, error=err)
    return total, err


_relay_cache = {"at": 0, "value": None}


def relay_balance_cached():
    if time.time() - _relay_cache["at"] < 60:
        return _relay_cache["value"]
    try:
        v = gen.relay_balance(gen.build_opener(CFG), gen.load_key(CFG))
    except SystemExit:
        v = None
    _relay_cache.update(at=time.time(), value=v)
    return v


def balance():
    # balance_source: "auto" (default) | "relay" | "manual"
    # auto = read it from the relay when api_url isn't OpenAI's and the relay supports the billing endpoints
    src = CFG.get("balance_source") or "auto"
    if src == "relay" or (src == "auto" and "api.openai.com" not in gen.API):
        rb = relay_balance_cached()
        if rb:
            return {"set": True, "source": "relay", "amount": rb["total"], "spent": rb["used"], "remaining": rb["remaining"],
                    "at": None, "error": None, "low": rb["remaining"] < float(CFG.get("low_balance_warn", 5))}
    b = CFG.get("balance") or {}
    if b.get("amount") is None:
        return {"set": False}
    ts = b.get("at") or time.time()
    source, err = "local", None
    spent = None
    if CFG.get("admin_key"):
        spent, err = admin_spend_since(ts, CFG["admin_key"])
        if spent is not None:
            source = "admin"
    if spent is None:
        spent = local_spend_since(ts)
    remaining = float(b["amount"]) - spent
    return {
        "set": True, "amount": float(b["amount"]), "at": ts, "spent": round(spent, 4),
        "remaining": round(remaining, 4), "source": source, "error": err,
        "low": remaining < float(CFG.get("low_balance_warn", 5)),
    }


# ---------------- settings ----------------

SETTABLE = ["api_url", "proxy", "model", "size", "quality", "format", "moderation", "out_dir",
            "usd_to_cny", "low_balance_warn", "timeout", "rates", "clear_after_submit", "confirm_over_usd",
            "agent_name", "allowed_origins", "fx_code", "fx_rate", "lang", "minimal_params", "balance_source"]


def settings_view():
    try:
        key = gen.load_key(CFG)
    except SystemExit:
        key = ""
    v = {k: CFG.get(k) for k in SETTABLE}
    v.update({
        "mode": "local",
        "api_key_masked": mask_key(key),
        "key_source": gen.tr("src_env") if os.environ.get("OPENAI_API_KEY") else (gen.tr("src_cfg") if CFG.get("api_key") else (CFG.get("key_file") or "")),
        "admin_key_masked": mask_key(CFG.get("admin_key", "")),
        "balance": CFG.get("balance"),
        "rates": {**gen.DEFAULT_RATES, "per_image": 0, **(CFG.get("rates") or {})},
        "out_dir": str(OUT_DIR), "version": VERSION,
        "skill_dir": str(HERE.parent), "config_file": str(gen.CONFIG_FILE),
    })
    return v


def write_key_file(path, key):
    """Write the new key back into the existing .env file (other lines kept), so there is only one copy of the key."""
    p = Path(path)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    out, done = [], False
    for line in lines:
        if line.strip().startswith("OPENAI_API_KEY="):
            out.append(f"OPENAI_API_KEY={key}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"OPENAI_API_KEY={key}")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")


def save_settings(body):
    cfg = gen.load_config()
    for k in SETTABLE:
        if k in body:
            cfg[k] = body[k]
    if body.get("api_key"):
        if cfg.get("key_file") and not cfg.get("api_key"):
            write_key_file(cfg["key_file"], body["api_key"].strip())
        else:
            cfg["api_key"] = body["api_key"].strip()
    if "admin_key" in body:
        if body["admin_key"]:
            cfg["admin_key"] = body["admin_key"].strip()
        else:
            cfg.pop("admin_key", None)
    if "balance_amount" in body:
        if body["balance_amount"] in (None, ""):
            cfg.pop("balance", None)
        else:
            cfg["balance"] = {"amount": float(body["balance_amount"]), "at": time.time()}
    gen.save_config(cfg)
    reload_config()
    _cost_cache["key"] = None
    _relay_cache["at"] = 0
    return settings_view()


def test_connection(body):
    """Free: confirm the key and network work (falls back to GET /models for relays without /models/{id})."""
    saved_api = gen.API
    try:
        cfg = {**CFG, **{k: body[k] for k in ("api_url", "proxy") if k in body}}
        key = (body.get("api_key") or "").strip() or gen.load_key(CFG)
        gen.API = (cfg.get("api_url") or "https://api.openai.com/v1").rstrip("/")
        model = body.get("model") or CFG.get("model", "gpt-image-2.5-sunburst")
        t0 = time.time()
        r = gen.probe(gen.build_opener(cfg), key, model)
        ms = round((time.time() - t0) * 1000)
        if r["listed"]:
            return {"ok": True, "msg": gen.tr("test_ok", ms=ms, m=model)}
        return {"ok": True, "msg": gen.tr("check_ok_unlisted", m=model)}
    except SystemExit as e:
        return {"ok": False, "msg": str(e)}
    except Exception as e:
        return {"ok": False, "msg": gen.tr("test_conn", e=e)}
    finally:
        gen.API = saved_api


def open_in_file_manager(p, select=False):
    """Open a folder; with select=True open the containing folder and select the file. Windows / macOS / Linux."""
    import subprocess
    p = Path(p)
    if sys.platform == "win32":
        if select:
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(p))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)] if select else ["open", str(p)])
    else:  # Linux has no standard "select file"; open the containing folder
        subprocess.Popen(["xdg-open", str(p.parent if select else p)])


# ---------------- HTTP ----------------

LOCAL_NAMES = ("127.0.0.1", "localhost", "gpt-image.localhost")


def allowed_hosts():
    return {f"{n}:{PORT}" for n in LOCAL_NAMES}


def allowed_origins():
    """The local page itself + sites listed in allowed_origins in config.json (e.g. your GitHub Pages URL)."""
    own = {f"http://{n}:{PORT}" for n in LOCAL_NAMES}
    extra = {o.rstrip("/").lower() for o in CFG.get("allowed_origins", [])}
    return own | extra

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    # ---- security: only the local page and explicitly allowed sites may connect ----
    # Without this, any web page open in the user's browser could POST to 127.0.0.1 and spend their money,
    # or use DNS rebinding to read data from this server.
    def guard(self):
        """Check Host and Origin. Returns True if allowed; otherwise replies 403 and returns False."""
        host = (self.headers.get("Host") or "").lower()
        if host not in allowed_hosts():
            self.send(403, {"error": "forbidden host"})
            return False
        origin = self.headers.get("Origin")
        self.cors_origin = None
        if origin:
            if origin.rstrip("/").lower() not in allowed_origins():
                self.send(403, {"error": gen.tr("origin_denied", o=origin)})
                return False
            self.cors_origin = origin
        return True

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if getattr(self, "cors_origin", None):
            self.send_header("Access-Control-Allow-Origin", self.cors_origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        """CORS preflight (the browser asks first when the GitHub Pages copy connects to the local service)."""
        if not self.guard():
            return
        self.send_response(204)
        if self.cors_origin:
            self.send_header("Access-Control-Allow-Origin", self.cors_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self):
        if not self.guard():
            return
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path in ("/backend.js", "/i18n.js"):
            return self.send(200, (HERE / path[1:]).read_bytes(), "text/javascript; charset=utf-8")
        if path == "/api/history":
            return self.send(200, history())
        if path == "/api/status":
            return self.send(200, {"running": running(), "sig": history_sig(), "spend": gen.spend_summary(OUT_DIR),
                                   "usd_to_cny": CFG.get("usd_to_cny", 7.1), "balance": balance()})
        if path == "/api/settings":
            return self.send(200, settings_view())
        if path.startswith("/img/"):
            p = (OUT_DIR / unquote(path[5:])).resolve()  # only files inside the output folder
            if OUT_DIR.resolve() in p.parents and p.is_file():
                ctype = {".png": "image/png", ".jpeg": "image/jpeg", ".jpg": "image/jpeg",
                         ".webp": "image/webp"}.get(p.suffix.lower(), "application/octet-stream")
                return self.send(200, p.read_bytes(), ctype)
            return self.send(404, {"error": "not found"})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.guard():
            return
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if path == "/api/size":
            try:
                return self.send(200, {"size": gen.parse_size(body.get("size", ""))})
            except SystemExit as e:
                return self.send(200, {"error": str(e)})
        if path == "/api/generate":
            meta, err = generate(body)
            return self.send(200, {"error": err} if err else meta)
        if path == "/api/settings":
            try:
                return self.send(200, save_settings(body))
            except Exception as e:
                return self.send(200, {"error": gen.tr("save_fail", e=e)})
        if path == "/api/fav":
            return self.send(200, set_fav(body.get("id", ""), bool(body.get("fav"))))
        if path == "/api/delete":
            return self.send(200, delete_record(body.get("id", "")))
        if path == "/api/test":
            return self.send(200, test_connection(body))
        if path == "/api/shutdown":
            self.send(200, {"ok": True})
            threading.Thread(target=SERVER.shutdown, daemon=True).start()
            return
        if path == "/api/open-folder":
            open_in_file_manager(OUT_DIR)
            return self.send(200, {"ok": True})
        if path == "/api/reveal":
            p = Path(body.get("path", "")).resolve()
            if OUT_DIR.resolve() in p.parents and p.exists():
                open_in_file_manager(p, select=True)
            return self.send(200, {"ok": True})
        self.send(404, {"error": "not found"})


class Server(ThreadingHTTPServer):
    allow_reuse_address = False  # True on Windows lets two processes grab the same port
    daemon_threads = True


SERVER = None


def already_running(url):
    try:
        with urllib.request.urlopen(url + "/api/status", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    global SERVER
    url = f"http://127.0.0.1:{PORT}"
    open_browser = "--no-browser" not in sys.argv
    if already_running(url):  # already running: just open the page
        if open_browser:
            webbrowser.open(url)
        return
    SERVER = Server(("127.0.0.1", PORT), Handler)
    print(gen.tr("server_up", url=url, d=OUT_DIR))
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    SERVER.serve_forever()


if __name__ == "__main__":
    if sys.stdout is None:  # started with pythonw: no console
        sys.stdout = sys.stderr = open(OUT_DIR / ".server.log", "a", encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
    main()
