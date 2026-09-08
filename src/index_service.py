"""Build both indexes in isolation, publish only a complete pair."""
import json
import os
import shutil
import subprocess
import sys
import uuid

from app_store import corpus_hashes, write_json


def rebuild(root, *, release=lambda:None, progress=lambda text:None, runner=subprocess.run):
    job = root/"_staging/index_jobs"/uuid.uuid4().hex
    job.mkdir(parents=True)
    snapshot = corpus_hashes(root)
    if not snapshot:
        raise ValueError("至少保留一份有正文的资料才能建立索引")
    shutil.copytree(root/"data/processed/sanitized", job/"data/processed/sanitized")
    if corpus_hashes(job) != snapshot:
        raise ValueError("复制资料时内容发生变化，请重试")
    environment = dict(os.environ)
    environment.update(QDRANT_PATH="data/processed/retrieval/qdrant",QDRANT_COLLECTION="kb_chunks_bge_m3")
    if not environment.get("EMBEDDING_MODEL"):
        local = root/".cache/modelscope/bge-m3"
        environment["EMBEDDING_MODEL"] = str(local) if local.exists() else "BAAI/bge-m3"
    # Avoid pointing temporary output at any live cache/index via an absolute override.
    environment["MODEL_CACHE_DIR"] = str(root/".cache/models")
    for script in ("bm25_baseline.py", "vector_baseline.py"):
        progress("构建关键词索引" if script.startswith("bm25") else "计算向量并构建语义索引")
        outcome = runner([sys.executable,str(root/"src"/script),str(job),"build"],capture_output=True,
                         timeout=1800,env=environment)
        if outcome.returncode:
            raise ValueError("索引构建失败，现用索引未修改；请检查文档内容、模型和磁盘空间")
    staged = job/"data/processed/retrieval"
    summary = json.loads((staged/"build_summary.json").read_text(encoding="utf-8"))
    if summary["chunk_count"] <= 0 or not (staged/"qdrant").exists():
        raise ValueError("新索引不完整，未发布")
    if corpus_hashes(root) != snapshot:
        raise ValueError("构建期间资料有变化，未发布；请重新更新索引")
    release()
    live = root/"data/processed/retrieval"
    backup = job/"previous_index"
    moved_old = False
    try:
        if live.exists():
            live.rename(backup)
            moved_old = True
        live.parent.mkdir(parents=True, exist_ok=True)
        staged.rename(live)
    except Exception:
        if moved_old and not live.exists():
            backup.rename(live)
        raise ValueError("新索引发布失败，已保留旧索引；请关闭其他检索进程后重试") from None
    write_json(root/"data/app/index_snapshot.json",snapshot)
    return summary
