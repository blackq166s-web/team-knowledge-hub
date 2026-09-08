"""Local-only upload queue and explicit index rebuild, serialized with searches."""
import hashlib
import io
import json
import re
import subprocess
import shutil
import sys
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import streamlit as st
from app_store import (archive, restore, edit_document, initialize_snapshot, index_dirty,
                       mark_index_current, read_json)


def extract_text(name, data):
    suffix = Path(name).suffix.lower()
    if suffix in {".md", ".txt"}:
        return data.decode("utf-8-sig")
    if suffix == ".docx":
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            info = package.getinfo("word/document.xml")
            if info.file_size > 20*1024*1024:
                raise ValueError("Word 解压后过大")
            tree = ET.fromstring(package.read(info))
        ns = {"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        body = tree.find("w:body", ns)
        lines = []
        for element in body:
            if element.tag.endswith("}tbl"):
                for row in element.findall("w:tr", ns):
                    cells = ["".join(n.text or "" for n in cell.findall(".//w:t",ns)) for cell in row.findall("w:tc",ns)]
                    lines.append(" | ".join(cells))
            else:
                lines.append("".join(n.text or "" for n in element.findall(".//w:t", ns)))
        if not any(line.strip() for line in lines):
            raise ValueError("Word 中没有可提取正文，图片不会自动识别")
        return "## Word 正文与表格\n" + "\n\n".join(lines)
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("不支持加密 PDF，请先导出可读取版本")
        if len(reader.pages) > 100:
            raise ValueError("PDF 最多支持 100 页")
        pages = [page.extract_text() or "" for page in reader.pages]
        if not any(t.strip() for t in pages):
            raise ValueError("此 PDF 没有可提取文字，扫描件请先 OCR")
        return "\n\n".join(f"## 第 {i} 页\n{text or '[本页没有可提取文字，图片内容未识别]'}" for i,text in enumerate(pages,1))
    raise ValueError("支持 Markdown、TXT、DOCX、文字型 PDF；不支持旧版 DOC 或扫描件 OCR")


def save_upload(root, name, data):
    if not data or len(data) > 10 * 1024 * 1024:
        raise ValueError("单个文件需大于 0 且不超过 10MB。")
    try:
        text = extract_text(name, data)
    except (zipfile.BadZipFile, KeyError, ET.ParseError, UnicodeError):
        raise ValueError("文件格式损坏或编码不是 UTF-8") from None
    if "\x00" in text or not text.strip() or len(text.encode("utf-8")) > 2*1024*1024:
        raise ValueError("提取文字为空、包含二进制内容或超过 2MB。")
    queue = root / "_staging" / "uploads"
    queue.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    for metadata in queue.glob("*.json"):
        if read_json(metadata, {}).get("sha256") == digest:
            raise ValueError("这份文件已上传，请在待处理列表中查找")
    path = queue / (uuid.uuid4().hex[:12] + ".md")
    path.write_text(text, encoding="utf-8")
    path.with_suffix(".original").write_bytes(data)
    path.with_suffix(".json").write_text(json.dumps({"name":Path(name).name, "created":datetime.now().isoformat(), "sha256":digest}, ensure_ascii=False), encoding="utf-8")
    return path


def promote(root, path, product, doc_type):
    from bm25_baseline import read_frontmatter
    if path.resolve().parent != (root / "_staging" / "uploads").resolve():
        raise ValueError("非法待处理文件。")
    _, body, _ = read_frontmatter(path.read_text(encoding="utf-8"))
    text = "\n".join(body)
    # Existing baseline excludes the root 正文 section; give plain text a useful heading.
    if not any(line.startswith("## ") for line in body):
        text = "## 上传正文\n" + text
    source = "SRC-" + hashlib.sha256(path.name.encode()).hexdigest()[:12]
    name = read_json(path.with_suffix(".json"), {}).get("name", path.name)
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', Path(name).stem).strip(' .')[:70] or "上传资料"
    target = root / "data" / "processed" / "sanitized" / (title + "-" + path.name)
    if target.exists():
        raise ValueError("此文件已经登记，无需重复登记。")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\nsource_id: {source}\nproduct_group: {product}\ndocument_type: {doc_type}\nacl: fde-core\n---\n" + text, encoding="utf-8")
    return target


def render_documents(root, resource_factory):
    initialize_snapshot(root)
    st.subheader("资料管理")
    st.caption("上传 → 预览 → 确认脱敏并登记 → 更新索引 → 回到问答。支持 Markdown / TXT / DOCX / 文字型 PDF。")
    if index_dirty(root):
        st.warning("资料发生变更，请更新索引后继续问答；避免使用已归档或过期内容。")
    indexed = root / "data" / "processed" / "retrieval" / "chunks.jsonl"
    counts = {}
    if indexed.exists():
        for line in indexed.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            counts[item["source_file"]] = counts.get(item["source_file"], 0) + 1
    paths = sorted((root / "data" / "processed" / "sanitized").glob("*.md"))
    term = st.text_input("按文件名筛选")
    visible = [p for p in paths if term.lower() in p.name.lower()]
    snapshot = read_json(root/"data/app/index_snapshot.json", {})
    st.dataframe([{"文件":p.name,"状态":"已入库" if p.name in counts and snapshot.get(p.name)==hashlib.sha256(p.read_bytes()).hexdigest() else "待更新索引", "片段数":counts.get(p.name,0)} for p in visible], hide_index=True, width="stretch")
    if paths:
        selected = st.selectbox("查看资料", paths, format_func=lambda p:p.name)
        with st.expander("预览正文"):
            st.text(selected.read_text(encoding="utf-8")[:20000])
            st.download_button("下载此 Markdown", selected.read_bytes(), selected.name, "text/markdown")
        with st.expander("编辑正文（自动保留旧版本）"):
            content = st.text_area("正文及元信息", selected.read_text(encoding="utf-8"), height=300, key="edit_"+selected.name)
            if st.button("保存修改"):
                try:
                    edit_document(root, selected, content)
                    st.success("修改已保存，旧版已备份；请更新索引")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        if st.button("归档当前资料（可恢复）"):
            archive(root, selected)
            st.session_state.pop("search", None)
            st.session_state.pop("answer", None)
            st.rerun()
    archived = sorted((root/"data/app/archive").glob("*/*.md"))
    if archived:
        with st.expander("已归档资料"):
            chosen_archive = st.selectbox("恢复目标", archived, format_func=lambda p:p.name+" · "+p.parent.name[:8])
            if st.button("恢复资料"):
                try:
                    restore(root, chosen_archive)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    with st.form("upload"):
        upload = st.file_uploader("上传已脱敏资料（最大 10MB；文字最大 2MB）", type=["md","txt","docx","pdf"])
        submit = st.form_submit_button("保存到待处理区")
    if submit and upload:
        try:
            save_upload(root, upload.name, upload.getvalue())
            st.success("已保存到本机待处理区，尚未入库。")
        except (ValueError, UnicodeError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("文件解析失败，请检查格式；扫描 PDF 和旧版 DOC 请先转换")
    queued = sorted((root / "_staging" / "uploads").glob("*.md"))
    if queued:
        def label(p):
            metadata = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
            return metadata["name"] + " · " + p.stem
        chosen = st.selectbox("待处理资料", queued, format_func=label)
        with st.expander("检查待入库内容"):
            st.text(chosen.read_text(encoding="utf-8")[:20000])
        product = st.selectbox("所属产品", ["M1212(ML001)","MI012","W001鼠标","团队通用"])
        kind = st.selectbox("文档类型", ["产品规范","验收测试程序","团队说明"])
        checked = st.checkbox("我已检查这份文件，确认已脱敏，可加入本机知识库")
        if st.button("登记入库", disabled=not checked):
            try:
                promote(root, chosen, product, kind)
                st.success("已登记，请点击下方更新索引。待处理副本仍保留。")
            except ValueError as exc:
                st.error(str(exc))
    st.divider()
    st.write("更新索引会重新计算向量，本机 CPU 可能需要数分钟；期间请勿另开命令行评测。")
    if st.button("更新检索索引", type="primary"):
        try:
            from index_service import rebuild
            def release():
                if (root/"data/processed/retrieval/qdrant").exists():
                    hybrid, lock = resource_factory()
                    with lock:
                        hybrid.close()
                resource_factory.clear()
            with st.status("正在构建新索引，成功后才替换现用索引…", expanded=True) as status:
                summary = rebuild(root, release=release, progress=st.write)
                status.update(label=f"更新完成：{summary['document_count']} 份文档，{summary['chunk_count']} 个片段", state="complete")
            st.session_state.pop("search", None)
            st.session_state.pop("answer", None)
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error("索引更新未完成。请检查模型、磁盘空间及索引占用；原文仍保留。")
