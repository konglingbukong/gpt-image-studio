import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))
from reference_library import ReferenceLibrary
from reference_setup import ReferenceSetup
from reference_sources import SOURCES


def fixture(kind):
    source = SOURCES[kind]
    if kind == "outfits":
        row = {"id": "SUM-0211", "カテゴリ": "夏", "キーワード": "shorts"}
        meta = ("const D=" + json.dumps([row]) + ";").encode()
        files = {"assets/img/SUM-0211.webp": b"outfit", "assets/thumbs/SUM-0211.webp": b"thumb",
                 "docs/LICENSE-DECISION.md": b"fixture asset terms"}
    else:
        row = {"id": "P010_diag", "体系": "全身", "分类": "站姿", "姿势编号": "P010", "姿势名称": "样本",
               "角度": "斜侧", "原图": "img/P010_diag.png", "缩略图": "thumbs/P010_diag.jpg"}
        meta = json.dumps([row]).encode()
        files = {row["原图"]: b"pose", row["缩略图"]: b"thumb"}
    files.update({source.metadata: meta, "LICENSE": b"fixture license"})
    archive, checksum = io.BytesIO(), hashlib.sha256()
    with zipfile.ZipFile(archive, "w") as z:
        for name, data in sorted(files.items()):
            z.writestr("upstream/" + name, data)
            checksum.update(name.encode() + b"\0" + hashlib.sha256(data).digest())
    return (replace(source, size_mb=1, count=1, metadata_hash=hashlib.sha256(meta).hexdigest(),
                    content_hash=checksum.hexdigest()), archive.getvalue())


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.lib = ReferenceLibrary(base / "mounts.json", base / "managed")
        self.setup = ReferenceSetup(self.lib)
        self.data, sources = {}, {}
        for kind in SOURCES:
            info, archive = fixture(kind)
            sources[kind], self.data[info.url] = info, archive
        for mock in [patch.dict(SOURCES, sources), patch.dict(os.environ, GPT_IMAGE_AUTO_DOWNLOAD="1")]:
            mock.start()
            self.addCleanup(mock.stop)

    def settled(self):
        for _ in range(250):
            status = self.setup.status()
            if status["state"] not in ("downloading", "importing", "stopping"):
                return status
            time.sleep(.02)
        self.fail("Worker did not settle")

    def fetch(self, request, **kwargs):
        return io.BytesIO(self.data[request.full_url])

    def test_opt_out_survives_refresh_restart_and_stale_tabs(self):
        with patch("urllib.request.urlopen") as network:
            self.assertEqual(self.setup.status()["state"], "offer")
            self.assertFalse(self.lib.directory.exists())
            self.setup.action("skip")
            reopened = ReferenceSetup(self.lib)
            self.assertEqual(reopened.action("auto")["state"], "skipped")
            network.assert_not_called()

    def test_headless_opt_out_can_be_overridden_explicitly(self):
        with patch.dict(os.environ, GPT_IMAGE_AUTO_DOWNLOAD="0"), patch("urllib.request.urlopen", side_effect=self.fetch) as network:
            self.assertEqual(self.setup.action("auto")["state"], "skipped")
            self.assertFalse(self.lib.directory.exists())
            self.setup.action("start")
            self.assertEqual(self.settled()["state"], "ready")
            self.assertEqual(network.call_count, 2)

    def test_default_install_uses_originals_and_is_idempotent(self):
        with patch("urllib.request.urlopen", side_effect=self.fetch) as network:
            self.setup.action("auto")
            self.setup.action("auto")
            self.assertEqual(self.settled()["state"], "ready")
            self.assertEqual(ReferenceSetup(self.lib).action("start")["state"], "ready")
            self.assertEqual(network.call_count, 2)
        for kind, data in [("outfits", b"outfit"), ("poses", b"pose")]:
            view = self.lib.catalog(kind)["groups"][0]["views"][0]
            self.assertEqual(self.lib.asset(kind, view["id"], "original").read_bytes(), data)
            self.assertEqual(self.lib.asset(kind, view["id"], "thumb").read_bytes(), b"thumb")
            self.assertTrue((self.lib.managed_folder(kind) / "LICENSE").is_file())

    def test_protected_manual_mount_and_integrity_failure_then_retry(self):
        self.lib.config.write_text(json.dumps({"outfits": {"root": str(self.lib.directory / "unplugged")}}))
        self.assertEqual(self.setup.status()["missing"], ["poses"])
        self.assertFalse(self.lib.catalog("outfits")["available"])
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b"corrupt")):
            self.setup.action("auto")
            self.assertEqual(self.settled()["reason"], "integrity")
        self.assertFalse(self.lib.managed_folder("poses").exists())
        with patch("urllib.request.urlopen", side_effect=self.fetch) as network:
            self.assertEqual(self.setup.action("auto")["state"], "error")
            self.setup.action("start")
            self.assertEqual(self.settled()["state"], "ready")
            self.assertEqual(network.call_count, 1)
        self.assertFalse(self.lib.managed_folder("outfits").exists())

    def test_stop_during_second_library_and_resume_only_that_library(self):
        waiting, release = threading.Event(), threading.Event()

        def slow_pose(req, **kwargs):
            if req.full_url == SOURCES["poses"].url:
                waiting.set()
                release.wait(5)
            return self.fetch(req)

        with patch("urllib.request.urlopen", side_effect=slow_pose):
            self.setup.action("auto")
            try:
                self.assertTrue(waiting.wait(3))
                other = ReferenceSetup(self.lib)
                self.assertEqual(other.action("start")["state"], "other")
                self.assertEqual(self.setup.action("skip")["state"], "stopping")
            finally:
                release.set()
            self.assertEqual(self.settled()["state"], "skipped")
        self.assertTrue(self.lib.installed("outfits"))
        self.assertFalse(self.lib.managed_folder("poses").exists())
        self.assertFalse(list(self.lib.directory.glob(".studio-install-*")))
        with patch("urllib.request.urlopen", side_effect=self.fetch) as network:
            self.setup.action("start")
            self.assertEqual(self.settled()["state"], "ready")
            self.assertEqual(network.call_count, 1)
