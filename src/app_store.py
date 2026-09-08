"""Local application state; deliberately separate from source data and Git."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def corpus_hashes(root):
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root/"data/processed/sanitized").glob("*.md"))}


def initialize_snapshot(root):
    path = root/"data/app/index_snapshot.json"
    if not path.exists() and (root/"data/processed/retrieval/chunks.jsonl").exists():
        write_json(path, corpus_hashes(root))


def index_dirty(root):
    snapshot = root/"data/app/index_snapshot.json"
    return not snapshot.exists() or read_json(snapshot, {}) != corpus_hashes(root)


def mark_index_current(root):
    write_json(root/"data/app/index_snapshot.json", corpus_hashes(root))


def save_history(root, query, results, answer=None, usage=None, seconds=0):
    key = uuid.uuid4().hex
    record = {"id":key,"time":datetime.now(timezone.utc).isoformat(),"question":query,
              "answer":answer,"usage":usage or {},"seconds":seconds,"feedback":"未评价",
              "sources":[{"id":i,"file":r["source_file"],"locator":r["locator"]} for i,r in enumerate(results,1)]}
    write_json(root/"data/app/history"/(key+".json"), record)
    return key


def histories(root):
    records = [read_json(p,{}) for p in (root/"data/app/history").glob("*.json")]
    return sorted(records, key=lambda x:x["time"], reverse=True)


def feedback(root, key, rating, note):
    if len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
        raise ValueError("无效历史记录编号")
    path = root/"data/app/history"/(key+".json")
    record = read_json(path, None)
    if record is None:
        raise ValueError("记录不存在")
    record.update(feedback=rating, note=note[:2000])
    write_json(path, record)


def archive(root, path):
    corpus = (root/"data/processed/sanitized").resolve()
    if path.resolve().parent != corpus or not path.is_file():
        raise ValueError("无效资料路径")
    destination = root/"data/app/archive"/uuid.uuid4().hex/path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    path.rename(destination)
    return destination


def restore(root, path):
    base = (root/"data/app/archive").resolve()
    if not path.resolve().is_relative_to(base) or not path.is_file():
        raise ValueError("无效归档路径")
    destination = root/"data/processed/sanitized"/path.name
    if destination.exists():
        raise ValueError("存在同名资料，请先处理冲突")
    path.rename(destination)
    return destination


def edit_document(root, path, content):
    if path.resolve().parent != (root/"data/processed/sanitized").resolve():
        raise ValueError("无效资料路径")
    if not content.strip() or len(content.encode("utf-8")) > 2*1024*1024:
        raise ValueError("内容不能为空或超过 2MB")
    from bm25_baseline import read_frontmatter
    old_meta, _, _ = read_frontmatter(path.read_text(encoding="utf-8"))
    new_meta, _, _ = read_frontmatter(content)
    if any(old_meta.get(k) != new_meta.get(k) for k in ("source_id","acl","product_group","document_type")):
        raise ValueError("编辑正文时请保留顶部来源、权限、产品和文档类型字段")
    backup = root/"data/app/versions"/uuid.uuid4().hex/path.name
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(path.read_bytes())
    temporary = path.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
    return backup
