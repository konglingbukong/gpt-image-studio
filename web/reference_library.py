"""Read-only catalog of classified outfit and pose images on the local machine."""
import hashlib
import json
import os
import threading
from pathlib import Path

from reference_sources import SOURCES


KINDS = {"outfits": ("*/*/*.webp", ".webp"), "poses": ("*/*/*/*.png", ".jpg")}
MIME = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg"}
ANGLES = ("正面", "斜侧", "侧面", "俯视", "仰视")


def contained(path, root):
    resolved = path.resolve()
    return resolved if root in resolved.parents and resolved.suffix.lower() == path.suffix.lower() else None


class ReferenceLibrary:
    def __init__(self, config, directory=None):
        self.config = config
        self.directory = Path(directory or os.environ.get("GPT_IMAGE_LIBRARY_DIR")
                              or Path.home() / "Pictures" / "gpt-image-libraries").expanduser().resolve()
        self.index = {}
        self.lock = threading.Lock()

    def configured(self):
        return json.loads(self.config.read_text(encoding="utf-8-sig")) if self.config.is_file() else {}

    def managed_folder(self, kind):
        return self.directory / (kind + "-" + SOURCES[kind].revision[:12])

    def installed(self, kind):
        folder = self.managed_folder(kind)
        marker = folder / "revision"
        return ((folder / "originals").is_dir() and (folder / "thumbnails").is_dir()
                and marker.is_file() and marker.read_text(encoding="ascii") == SOURCES[kind].revision)

    def missing(self):
        mounts = self.configured()
        return [k for k in SOURCES if not mounts.get(k, {}).get("root") and not self.installed(k)]

    def catalog(self, kind):
        """Refresh one library from disk when its tab is opened."""
        pattern, _ = KINDS[kind]
        with self.lock:
            self.index.pop(kind, None)
            spec = self.configured().get(kind, {})
            if not spec.get("root"):
                if not self.installed(kind):
                    return {"available": False, "groups": []}
                folder = self.managed_folder(kind)
                spec = {"root": folder / "originals", "thumbnails": folder / "thumbnails"}
            root = Path(spec["root"]).expanduser().resolve()
            if not root.is_dir():
                return {"available": False, "groups": []}
            thumbs = Path(spec["thumbnails"]).expanduser().resolve() if spec.get("thumbnails") else None
            groups, files = {}, {}
            for path in sorted(root.glob(pattern)):
                if not contained(path, root) or not path.is_file():
                    continue
                rel = path.relative_to(root)
                asset_id = hashlib.sha256(rel.as_posix().encode("utf-8")).hexdigest()[:24]
                category, section = rel.parts[:2]
                if kind == "outfits":
                    name, angle = path.stem, ""
                else:
                    name, angle = path.parent.name, path.stem.partition("_")[0]
                group = groups.setdefault((category, section, name), {
                    "category": category, "section": section, "name": name, "views": []})
                group["views"].append({"id": asset_id, "angle": angle, "file": path.name})
                files[asset_id] = rel
            if kind == "poses":
                rank = {angle: i for i, angle in enumerate(ANGLES)}
                for group in groups.values():
                    group["views"].sort(key=lambda v: (rank.get(v["angle"], len(rank)), v["file"]))
            self.index[kind] = root, thumbs, files
            return {"available": True, "groups": list(groups.values())}

    def asset(self, kind, asset_id, variant):
        if kind not in KINDS or variant not in ("thumb", "original"):
            return None
        with self.lock:
            index = self.index.get(kind)
        if index is None:
            return None
        root, thumbs, files = index
        rel = files.get(asset_id)
        if rel is None:
            return None
        original = contained(root / rel, root)
        if not original or not original.is_file():
            return None
        if variant == "thumb" and thumbs:
            preview = contained(thumbs / rel.with_suffix(KINDS[kind][1]), thumbs)
            if preview and preview.is_file():
                return preview
        return original
