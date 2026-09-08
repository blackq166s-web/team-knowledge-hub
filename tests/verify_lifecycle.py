"""Exercise actual local embedding and Qdrant, entirely in a throwaway workspace."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from document_manager import save_upload, promote
from index_service import rebuild
from app_store import archive, restore, index_dirty
from hybrid_baseline import HybridRetriever

os.environ["EMBEDDING_MODEL"]=str(ROOT/".cache/modelscope/bge-m3")
with tempfile.TemporaryDirectory(prefix="kb-lifecycle-") as tmp:
    root=Path(tmp)
    shutil.copytree(ROOT/"src",root/"src",ignore=shutil.ignore_patterns("__pycache__"))
    queue=save_upload(root,"维护说明.txt","演示系统每周一上午十点维护，联系人是测试管理员。".encode())
    document=promote(root,queue,"团队通用","团队说明")
    queue2=save_upload(root,"备用说明.md","## 联系方式\n演示服务电话是0000，仅供测试。".encode())
    promote(root,queue2,"团队通用","团队说明")
    summary=rebuild(root,progress=print)
    assert summary["document_count"]==2 and not index_dirty(root)
    retriever=HybridRetriever(root)
    found=retriever.search("演示系统何时维护？","fde-core",5)
    assert any("每周一" in item["text"] for item in found["results"])
    retriever.close()
    old=(root/"data/processed/retrieval/chunks.jsonl").read_bytes()
    def fail(*args,**kwargs):
        return type("Outcome",(),{"returncode":1})()
    try:
        rebuild(root,runner=fail)
        raise AssertionError("Expected failure")
    except ValueError:
        pass
    assert (root/"data/processed/retrieval/chunks.jsonl").read_bytes()==old
    archived=archive(root,document)
    assert index_dirty(root)
    summary=rebuild(root,progress=print)
    assert summary["document_count"]==1
    retriever=HybridRetriever(root)
    found=retriever.search("演示系统何时维护？","fde-core",5)
    assert all(item["source_file"]!=document.name for item in found["results"])
    retriever.close()
    restore(root,archived)
    assert index_dirty(root)
print("PASS: upload, promote, actual BM25 + BGE-M3 + Qdrant build/search, failed-build preservation, archive/rebuild exclusion, restore")
