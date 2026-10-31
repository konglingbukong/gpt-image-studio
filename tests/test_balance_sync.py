import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gen
import mcp_server as mcp
import official_balance as balance


class ModelList(io.BytesIO):
    status = 200

    def __init__(self, organization=None):
        super().__init__(b'{"object":"list","data":[]}')
        self.headers = {"openai-organization": organization} if organization else {}

    def geturl(self):
        return balance.API + "/models"


class BalanceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "config.json"
        cfg_patch = patch.object(gen, "CONFIG_FILE", path)
        cfg_patch.start()
        self.addCleanup(cfg_patch.stop)
        env = patch.dict(os.environ, {"OPENAI_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        self.config = {"api_key": "sk-proj-test", "model": "test-model", "out_dir": str(path.parent / "images"),
                       "balance": {"amount": 8, "at": time.time() - 90}, "quality": "high"}
        gen.save_config(self.config)
        self.args = {"billing_url": balance.BILLING, "amount_usd": 0, "organization_id": "org-example",
                     "observed_at": time.time() - 1}
        api = patch.object(gen, "build_opener", autospec=True)
        self.open = api.start().return_value.open
        self.addCleanup(api.stop)
        self.open.side_effect = lambda *a, **kw: ModelList()

    def call(self, args, name="sync_balance"):
        return mcp.handle({"id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})

    def test_browser_instructions_then_zero_and_repeat(self):
        first = self.call({})
        self.assertEqual(json.loads(first["content"][0]["text"])["status"], "needs_browser")
        self.open.assert_not_called()
        self.assertEqual(gen.read_config(), self.config)
        for _ in range(2):
            result = self.call(self.args)
            self.assertFalse(result["isError"])
            self.assertEqual(json.loads(result["content"][0]["text"])["amount_usd"], 0)
        saved = gen.read_config()
        self.assertEqual(saved["balance"]["at"], self.args["observed_at"])
        self.assertEqual(saved["balance"]["source"], "mcp_browser")
        self.assertEqual(saved["quality"], "high")
        req = self.open.call_args.args[0]
        self.assertEqual(req.get_method(), "GET")
        self.assertEqual(req.full_url, balance.API + "/models")
        self.assertEqual(req.get_header("Openai-organization"), "org-example")
        self.assertNotIn("Authorization", req.headers)  # never forwarded through redirects
        self.assertIn("$0.00", self.call({}, "get_spending")["content"][0]["text"])

    def test_invalid_or_stale_input_preserves_balance(self):
        for changes in [{"amount_usd": True}, {"amount_usd": float("nan")}, {"amount_usd": None},
                        {"observed_at": time.time() - 700}, {"observed_at": time.time() + 120},
                        {"organization_id": "org-example\nx: injected"},
                        {"billing_url": balance.BILLING.replace(".com/", ".com.evil.invalid/")},
                        {"billing_url": balance.BILLING.replace("billing/overview", "usage")}]:
            with self.subTest(changes=changes):
                self.assertTrue(self.call({**self.args, **changes})["isError"])
        self.assertTrue(self.call({"amount_usd": 5})["isError"])
        self.open.assert_not_called()
        self.assertEqual(gen.read_config(), self.config)

    def test_account_mismatch_and_legacy_default(self):
        self.open.side_effect = lambda *a, **kw: ModelList("org-other")
        self.assertTrue(self.call(self.args)["isError"])
        self.open.side_effect = urllib.error.HTTPError(balance.API, 401, "Unauthorized", {}, None)
        self.assertTrue(self.call(self.args)["isError"])
        self.assertEqual(gen.read_config(), self.config)
        gen.save_config({**self.config, "api_key": "legacy-test"})
        self.open.side_effect = lambda *a, **kw: ModelList()
        self.assertTrue(self.call(self.args)["isError"])
        self.open.side_effect = lambda *a, **kw: ModelList("org-example")
        self.assertFalse(self.call(self.args)["isError"])
        self.assertFalse(self.open.call_args.args[0].has_header("Openai-organization"))

    def test_relay_and_missing_key_do_not_start_browser_flow(self):
        for changes in [{"api_url": "https://relay.invalid/v1"}, {"balance_source": "relay"}, {"api_key": ""}]:
            gen.save_config({**self.config, **changes})
            self.assertTrue(self.call({})["isError"])
            self.assertTrue(self.call(self.args)["isError"])
            self.assertEqual(gen.read_config()["balance"], self.config["balance"])
        self.open.assert_not_called()

    def test_newer_calibration_wins_and_changed_key_aborts(self):
        def calibrate(*args, **kwargs):
            with gen.edit_config() as current:
                current["balance"] = {"amount": 9, "at": time.time()}
            return ModelList()
        self.open.side_effect = calibrate
        self.assertTrue(self.call(self.args)["isError"])
        self.assertEqual(gen.read_config()["balance"]["amount"], 9)

        def switch_key(*args, **kwargs):
            with gen.edit_config() as current:
                current["api_key"] = "sk-proj-other"
            return ModelList()
        self.open.side_effect = switch_key
        self.assertTrue(self.call(self.args)["isError"])
        self.assertEqual(gen.read_config()["balance"]["amount"], 9)

    def test_running_web_service_sees_external_sync_and_keeps_web_edits(self):
        code = ("import server; s = server.Server(('127.0.0.1', 0), server.Handler); "
                "server.PORT = s.server_port; print(s.server_port, flush=True); s.serve_forever()")
        proc = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT / "web", stdout=subprocess.PIPE,
                                text=True, env={**os.environ, "GPT_IMAGE_CONFIG": str(gen.CONFIG_FILE)})
        try:
            port = int(proc.stdout.readline())
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def local(endpoint, body=None):
                data = None if body is None else json.dumps(body).encode()
                req = urllib.request.Request(f"http://127.0.0.1:{port}/api/{endpoint}", data=data,
                                             headers={"Content-Type": "application/json"})
                with opener.open(req, timeout=5) as response:
                    return json.load(response)
            self.assertEqual(local("status")["balance"]["remaining"], 8)
            def update_settings(*args, **kwargs):
                local("settings", {"quality": "max"})
                return ModelList()
            self.open.side_effect = update_settings
            self.assertFalse(self.call({**self.args, "amount_usd": 42.75})["isError"])
            self.assertEqual(gen.read_config()["quality"], "max")
            self.assertEqual(local("settings")["balance"]["source"], "mcp_browser")
            shown = local("status")["balance"]
            self.assertTrue(shown["synced"])
            self.assertEqual(shown["remaining"], 42.75)
            local("settings", {"topup_amount": 2})
            self.assertFalse(local("status")["balance"]["synced"])
            self.assertEqual(local("status")["balance"]["remaining"], 44.75)
            self.assertTrue(local("balance-sync", {"amount": 4})["balance"]["synced"])
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            proc.stdout.close()

    def test_stdio_sync_overlapping_a_web_settings_transaction(self):
        marker = gen.CONFIG_FILE.with_suffix(".verified")
        # Run the actual stdio loop in another process, with only the official API
        # response replaced so the test requires neither a real account nor a browser.
        code = (
            "from test_balance_sync import ModelList, Path, gen, mcp, patch, sys, time\n"
            "def models(*args, **kwargs):\n"
            "    Path(sys.argv[1]).touch()\n"
            "    while not Path(sys.argv[1] + '.resume').exists(): time.sleep(0.02)\n"
            "    return ModelList()\n"
            "with patch.object(gen, 'build_opener') as opener:\n"
            "    opener.return_value.open.side_effect = models\n"
            "    mcp.main()\n"
        )
        messages = [{"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                    {"method": "notifications/initialized"}, {"id": 2, "method": "tools/list"},
                    {"id": 3, "method": "tools/call", "params": {"name": "sync_balance", "arguments": {}}},
                    {"id": 4, "method": "tools/call", "params": {"name": "sync_balance", "arguments": self.args}},
                    {"id": 5, "method": "tools/call", "params": {"name": "get_spending", "arguments": {}}}]
        proc = subprocess.Popen([sys.executable, "-X", "utf8", "-c", code, str(marker)],
                                cwd=ROOT / "tests", stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                text=True, encoding="utf-8", env={**os.environ, "GPT_IMAGE_CONFIG": str(gen.CONFIG_FILE)})
        try:
            for message in messages:
                proc.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
            proc.stdin.flush()
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), "MCP never reached the organization check")
            with gen.edit_config() as current:
                Path(str(marker) + ".resume").touch()
                current["quality"] = "max"
            output, _ = proc.communicate(timeout=8)
            replies = {msg["id"]: msg["result"] for msg in map(json.loads, output.splitlines())}
            self.assertEqual(replies[1]["serverInfo"], mcp.SERVER_INFO)
            self.assertIn("sync_balance", [t["name"] for t in replies[2]["tools"]])
            self.assertEqual(json.loads(replies[3]["content"][0]["text"])["status"], "needs_browser")
            self.assertEqual(json.loads(replies[4]["content"][0]["text"])["status"], "synced")
            self.assertIn("$0.00", replies[5]["content"][0]["text"])
            self.assertEqual(gen.read_config()["quality"], "max")
            self.assertEqual(gen.read_config()["balance"]["amount"], 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate(timeout=5)
