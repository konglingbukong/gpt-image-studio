"""First-run library download. GET is read-only; opt-out is shared by tabs and survives restarts."""
import errno
import http.client
import os
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from pathlib import Path

from reference_sources import SOURCES, import_archive


class Cancelled(Exception):
    pass


def claim(path):
    """Take a non-blocking process lock; closing the file also releases it after a crash."""
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            raise
        return None
    return handle


class ReferenceSetup:
    def __init__(self, library):
        self.library = library
        self.root = library.directory
        self.preference = self.root / "setup-state"
        self.opt_out = self.root / "skip-auto-download"
        self.lockfile = self.root / "download.lock"
        self.mutex = threading.RLock()
        self.cancel = threading.Event()
        self.job = None

    def choice(self):
        try:
            return self.preference.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            return ""

    def remember(self, value):
        self.root.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.root, prefix=".choice-")
        try:
            with os.fdopen(fd, "w", encoding="ascii") as f:
                f.write(value)
            os.replace(name, self.preference)
        finally:
            Path(name).unlink(missing_ok=True)

    def status(self):
        with self.mutex:
            missing = self.library.missing()
            base = {"missing": missing, "sizeMB": sum(SOURCES[k].size_mb for k in missing)}
            if self.job is not None:
                return {**base, **self.job}
            if not missing:
                return {**base, "state": "ready"}
            if self.opt_out.is_file():
                return {**base, "state": "skipped"}
            choice = self.choice()
            if choice == "requested":
                handle = claim(self.lockfile)
                if handle is None:
                    return {**base, "state": "other"}
                handle.close()
                return {**base, "state": "interrupted"}
            if choice.startswith("error_"):
                return {**base, "state": "error", "reason": choice[6:]}
            offline = os.environ.get("GPT_IMAGE_AUTO_DOWNLOAD", "1").lower() in ("0", "off", "false", "no")
            return {**base, "state": "skipped" if choice == "skipped" or offline else "offer"}

    def action(self, action):
        if action not in ("auto", "start", "skip"):
            raise ValueError("Unknown setup action")
        with self.mutex:
            status = self.status()
            if status["state"] == "ready":
                return status
            if action == "skip":
                self.root.mkdir(parents=True, exist_ok=True)
                self.opt_out.touch()
                self.cancel.set()
                if self.job is not None:
                    self.job["state"] = "stopping"
                return self.status()
            if self.job is not None or status["state"] == "other" or (action == "auto" and status["state"] != "offer"):
                return status
            self.root.mkdir(parents=True, exist_ok=True)
            handle = claim(self.lockfile)
            if handle is None:
                return {**status, "state": "other"}
            try:
                if action == "auto" and self.opt_out.is_file():
                    handle.close()
                    return self.status()
                if action == "start":
                    self.opt_out.unlink(missing_ok=True)
                self.remember("requested")
                self.cancel.clear()
                self.job = {"state": "downloading", "kind": status["missing"][0], "bytes": 0}
                threading.Thread(target=self.run, args=(handle,), daemon=True).start()
            except BaseException:
                self.job = None
                handle.close()
                raise
            return self.status()

    def run(self, handle):
        last_check = 0.0

        def check_cancel():
            nonlocal last_check
            if time.monotonic() - last_check >= .25:
                last_check = time.monotonic()
                if self.opt_out.is_file():
                    self.cancel.set()
            if self.cancel.is_set():
                raise Cancelled()

        result = "finished"
        try:
            # Only reclaim our marked staging folders while holding the inter-process lock.
            for path in self.root.glob(".studio-install-*"):
                if (path.resolve().parent == self.root and path.resolve() == path
                        and (path / ".gpt-image-staging").is_file()):
                    shutil.rmtree(path)
            for kind in self.library.missing():
                check_cancel()
                source = SOURCES[kind]
                if shutil.disk_usage(self.root).free < (2 * source.size_mb + 30) * 1_000_000:
                    raise OSError(errno.ENOSPC, "Insufficient space")
                with self.mutex:
                    self.job.update(kind=kind, bytes=0)
                with tempfile.TemporaryDirectory(dir=self.root, prefix=".studio-install-") as temp:
                    stage = Path(temp)
                    (stage / ".gpt-image-staging").touch()
                    archive = stage / "source.zip"
                    request = urllib.request.Request(source.url, headers={"User-Agent": "GPT-Image-Studio-Library"})
                    with urllib.request.urlopen(request, timeout=30) as stream, archive.open("xb") as out:
                        size = 0
                        while True:
                            check_cancel()
                            data = stream.read1(512 * 1024)
                            if not data:
                                break
                            size += len(data)
                            if size > (source.size_mb + 12) * 1_000_000:
                                raise ValueError("Unexpected archive size")
                            out.write(data)
                            with self.mutex:
                                self.job["bytes"] = size
                    check_cancel()
                    with self.mutex:
                        if not self.cancel.is_set():
                            self.job["state"] = "importing"
                    folder = stage / "library"
                    folder.mkdir()
                    import_archive(kind, archive, folder, check_cancel)
                    check_cancel()
                    # Manual mounts take precedence even if configured during a download.
                    if kind in self.library.missing():
                        folder.rename(self.library.managed_folder(kind))
                    with self.mutex:
                        if not self.cancel.is_set():
                            self.job["state"] = "downloading"
        except Cancelled:
            result = "skipped"
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError):
            result = "error_network"
        except (ValueError, KeyError, IndexError, EOFError, zipfile.BadZipFile, zlib.error):
            result = "error_integrity"
        except OSError as exc:
            result = "error_space" if exc.errno == errno.ENOSPC else "error_storage"
        except Exception:
            result = "error_storage"
            raise
        finally:
            with self.mutex:
                try:
                    self.remember(result)
                finally:
                    self.job = None
                    handle.close()
