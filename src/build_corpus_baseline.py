from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath


KNOWN_TYPES = [
    "可靠性维修性测试性保障性安全性环境适应性工作报告",
    "环境应力筛选大纲",
    "使用维护说明书",
    "标准化工作报告",
    "验收测试程序",
    "六性保证大纲",
    "六性工作报告",
    "质量保证大纲",
    "特性分析报告",
    "环境试验大纲",
    "标准化大纲",
    "技术说明书",
    "产品规范",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_stream(handle) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def classify_product(filename: str) -> str:
    if filename.startswith("M1212"):
        return "M1212(ML001)"
    if filename.startswith("MI012"):
        return "MI012"
    if filename.startswith("W001"):
        return "W001鼠标"
    return "待分类"


def classify_document(filename: str) -> str:
    stem = Path(filename).stem
    for item in KNOWN_TYPES:
        if stem.endswith(item):
            return item
    return "待分类"


def safe_target(root: Path, archive_name: str) -> Path:
    parts = PurePosixPath(archive_name).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"不安全的压缩包路径: {archive_name!r}")
    target = root.joinpath(*parts)
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if os.path.commonpath([str(resolved_root), str(resolved_target)]) != str(resolved_root):
        raise ValueError(f"压缩包路径越界: {archive_name!r}")
    return target


def extract_entry(zf: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path) -> str:
    with zf.open(info, "r") as source:
        archive_hash = sha256_stream(source)
    if target.exists():
        existing_hash = sha256_file(target)
        if existing_hash != archive_hash:
            raise RuntimeError(f"目标已存在且内容不同，停止覆盖: {target}")
        return existing_hash

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_name(target.name + ".tmp")
    with zf.open(info, "r") as source, temp_target.open("wb") as destination:
        shutil.copyfileobj(source, destination, length=1024 * 1024)
    if sha256_file(temp_target) != archive_hash:
        temp_target.unlink(missing_ok=True)
        raise RuntimeError(f"解压后哈希不一致: {target}")
    temp_target.replace(target)
    timestamp = datetime(*info.date_time).timestamp()
    os.utime(target, (timestamp, timestamp))
    target.chmod(stat.S_IREAD)
    return archive_hash


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--snapshot", default="20260907")
    args = parser.parse_args()

    root = args.project_root.resolve()
    archive = root / "文档平台用测试文档.zip"
    raw_root = root / "data" / "raw" / args.snapshot
    manifest_path = root / "data" / "corpus_manifest.json"
    if not archive.is_file():
        raise FileNotFoundError(archive)

    archive_hash = sha256_file(archive)
    documents: list[dict] = []
    excluded: list[str] = []

    with zipfile.ZipFile(archive) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise RuntimeError(f"压缩包 CRC 校验失败: {bad}")

        for info in zf.infolist():
            if info.is_dir():
                continue
            filename = PurePosixPath(info.filename).name
            if filename.startswith("~$"):
                excluded.append(info.filename)
                continue
            target = safe_target(raw_root, info.filename)
            file_hash = extract_entry(zf, info, target)
            product = classify_product(filename)
            document_type = classify_document(filename)
            selected = document_type in {"产品规范", "验收测试程序"} and product != "待分类"
            documents.append(
                {
                    "source_id": f"SRC-{file_hash[:12]}",
                    "product_group": product,
                    "document_type": document_type,
                    "file_name": filename,
                    "extension": target.suffix.lower(),
                    "size_bytes": info.file_size,
                    "sha256": file_hash,
                    "revision_id": f"REV-{file_hash[:12]}",
                    "archive_modified_at": datetime(*info.date_time).isoformat(timespec="seconds"),
                    "raw_relative_path": target.relative_to(root).as_posix(),
                    "acl": "待定义",
                    "ingest_status": "抽检样本" if selected else "待解析",
                    "sample_selected": selected,
                    "conversion_required": target.suffix.lower() == ".doc",
                }
            )

    documents.sort(key=lambda item: (item["product_group"], item["document_type"], item["file_name"]))
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project_root": str(root),
        "source_archive": archive.name,
        "source_archive_sha256": archive_hash,
        "snapshot": args.snapshot,
        "crc_check": "通过",
        "usable_document_count": len(documents),
        "excluded_entries": excluded,
        "documents": documents,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "manifest": str(manifest_path),
        "usable": len(documents),
        "samples": sum(1 for item in documents if item["sample_selected"]),
        "excluded": len(excluded),
        "archive_sha256": archive_hash,
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
