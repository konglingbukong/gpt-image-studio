"""Pinned upstream archives and their import layout. No upstream media is bundled."""
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Source:
    repository: str
    revision: str
    size_mb: int
    count: int
    metadata: str
    metadata_hash: str
    content_hash: str

    @property
    def url(self):
        return f"https://codeload.github.com/paipiange/{self.repository}/zip/{self.revision}"


SOURCES = {
    "outfits": Source("nvzhuang", "f13741ebc09c73a63b92f626a115a1bb74ed779f", 132, 1407, "data.js",
                      "873220246c9026984d1149dee9307bd8e70814c036bcf76ace3b3da54c8e41cc",
                      "7865149e2fe9c209711bba8326553620427865d8384e392a5efdfbeb25db80f1"),
    "poses": Source("ai-pose-gallery-zh", "0596708b11fe7ce874ac519e4f2538c92918b07f", 685, 1439,
                    "data/pose-zh.json", "eacf396c1002c74e991f149127653a0abf0f0e3cf27977bce7d21c9fc80b7d69",
                    "bccdd159188c870a025247439703713f42cd82082c1fcec6b3301be65a59b824"),
}

SEASONS = {"春": "01 春季穿搭", "夏": "02 夏季穿搭", "秋": "03 秋季穿搭", "冬": "04 冬季穿搭",
           "ランジェリー": "05 内衣与居家", "パーティ": "06 派对穿搭", "水着": "07 泳装与度假", "セクシー": "08 性感造型"}
SPECIAL = {
    "ランジェリー": [("robe", "睡袍搭配"), ("bra", "文胸搭配"), ("dress", "裙式内衣"), ("camisole", "吊带搭配"),
                 ("shorts", "短裤搭配"), ("briefs", "内裤搭配")],
    "水着": [("skirt", "泳装配裙装"), ("shorts", "泳装配短裤"), ("pants", "泳装配长裤"), ("swimsuit", "泳衣造型")],
    "セクシー": [("apron", "围裙造型"), ("corset", "束身搭配"), ("pleated", "百褶元素")],
}


def outfit_section(category, keywords):
    tags = set(keywords.split())
    for tag, section in SPECIAL.get(category, []):
        if tag in tags:
            return section
    for garment, name in [("dress", "连衣裙"), ("skirt", "半身裙")]:
        if garment in tags:
            for tag, length in [("mini", "短款"), ("midi", "中长款"), ("maxi", "长款")]:
                if tag in tags:
                    return length + name
            return name + "（未标裙长）"
    for tag, name in [("shorts", "短裤"), ("jeans", "牛仔裤"), ("pants", "长裤"), ("coat", "大衣"),
                      ("jacket", "夹克"), ("cardigan", "开衫"), ("knit", "针织")]:
        if tag in tags:
            return name + "搭配"
    return "其他搭配"


def component(value):
    # Match existing hand-classified libraries, including Windows filename rules.
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(". ")
    if not name:
        raise ValueError("Invalid library filename")
    return name


def layout(kind, metadata):
    if kind == "outfits":
        data = metadata.decode("utf-8-sig").split("const D=", 1)[1]
        rows = json.JSONDecoder().raw_decode(data)[0]
        for row in rows:
            category = row["カテゴリ"]
            name = component(row["id"]) + ".webp"
            path = Path(SEASONS[category], outfit_section(category, row["キーワード"]), name)
            yield "assets/img/" + name, Path("originals") / path
            yield "assets/thumbs/" + name, Path("thumbnails") / path
    else:
        for row in json.loads(metadata):
            group = component(row["姿势编号"] + " " + row["姿势名称"])
            stem = component(row["角度"] + "_" + row["id"])
            path = Path(component(row["体系"]), component(row["分类"]), group)
            yield row["原图"], Path("originals") / path / (stem + ".png")
            yield row["缩略图"], Path("thumbnails") / path / (stem + ".jpg")


def import_archive(kind, archive, target, check_cancel):
    source = SOURCES[kind]
    with zipfile.ZipFile(archive) as z:
        prefix = z.infolist()[0].filename.split("/")[0] + "/"

        def read(name, limit):
            info = z.getinfo(prefix + name)
            if not 0 < info.file_size <= limit:
                raise ValueError("Unexpected entry size")
            return z.read(info)

        metadata = read(source.metadata, 2_000_000)
        if hashlib.sha256(metadata).hexdigest() != source.metadata_hash:
            raise ValueError("Unexpected catalog")
        paths = dict(layout(kind, metadata))
        if len(paths) != source.count * 2:
            raise ValueError("Incomplete catalog")
        # Hash uncompressed content and stable upstream names; GitHub may recompress a ZIP.
        paths.update({source.metadata: None, "LICENSE": Path("LICENSE")})
        if kind == "outfits":
            paths["docs/LICENSE-DECISION.md"] = Path("ASSET-TERMS.md")
        digest = hashlib.sha256()
        for name, rel in sorted(paths.items()):
            check_cancel()
            data = metadata if name == source.metadata else read(name, 16_000_000)
            digest.update(name.encode() + b"\0" + hashlib.sha256(data).digest())
            if rel:
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("xb") as f:
                    f.write(data)
        if digest.hexdigest() != source.content_hash:
            raise ValueError("Library checksum mismatch")
    (target / "revision").write_text(source.revision, encoding="ascii")
