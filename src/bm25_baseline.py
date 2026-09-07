from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import bm25s
import jieba
import numpy as np
from bm25s.tokenization import Tokenizer


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


PARAGRAPH_RE = re.compile(r"^\[(\d+)]\s*(.*)$")
HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")
TABLE_HEADING_RE = re.compile(r"^表格\s*(\d+)$")
TOKEN_RE = re.compile(
    r"[a-z]+(?:[-_]?[a-z0-9]+)*|\d+(?:\.\d+)?(?:[a-z]+)?|[\u4e00-\u9fff]+",
    re.IGNORECASE,
)


def read_frontmatter(text: str) -> tuple[dict[str, str], list[str], int]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, lines, 1
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}, lines, 1
    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata, lines[end + 1 :], end + 2


def split_long_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts = re.split(r"(?<=[。；！？;])", text)
    result: list[str] = []
    current = ""
    for part in parts:
        if not part:
            continue
        if current and len(current) + len(part) > limit:
            result.append(current)
            current = ""
        while len(part) > limit:
            result.append(part[:limit])
            part = part[limit:]
        current += part
    if current:
        result.append(current)
    return result


def make_chunk(
    *,
    source_file: str,
    metadata: dict[str, str],
    section_path: list[str],
    lines: list[tuple[int, str]],
) -> dict[str, Any]:
    content = "\n".join(text for _, text in lines).strip()
    paragraph_numbers = [
        int(match.group(1))
        for _, text in lines
        if (match := PARAGRAPH_RE.match(text))
    ]
    section = " > ".join(section_path) if section_path else "未命名段落"
    table_numbers = [
        int(match.group(1))
        for heading in section_path
        if (match := TABLE_HEADING_RE.match(heading))
    ]
    locator_parts = [section]
    if paragraph_numbers:
        locator_parts.append(
            f"[{min(paragraph_numbers)}]"
            if len(set(paragraph_numbers)) == 1
            else f"[{min(paragraph_numbers)}]-[{max(paragraph_numbers)}]"
        )
    locator_parts.append(f"Markdown L{lines[0][0]}-L{lines[-1][0]}")
    content_fingerprint = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
    stable_key = (
        f"{metadata.get('source_id', source_file)}|{section}|"
        f"{lines[0][0]}|{lines[-1][0]}|{content_fingerprint}"
    )
    chunk_id = "CHK-" + hashlib.sha1(stable_key.encode("utf-8")).hexdigest()[:12]
    acl = metadata.get("acl", "fde-core")
    return {
        "chunk_id": chunk_id,
        "source_id": metadata.get("source_id", ""),
        "source_file": source_file,
        "product_group": metadata.get("product_group", ""),
        "document_type": metadata.get("document_type", ""),
        "acl": acl,
        "section": section,
        "locator": "；".join(locator_parts),
        "paragraph_numbers": sorted(set(paragraph_numbers)),
        "table_numbers": sorted(set(table_numbers)),
        "markdown_line_start": lines[0][0],
        "markdown_line_end": lines[-1][0],
        "text": content,
    }


def chunk_markdown(path: Path, max_chars: int = 900, overlap_items: int = 1) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    metadata, body_lines, first_body_line = read_frontmatter(text)
    metadata.setdefault("acl", "fde-core")
    section_by_level: dict[int, str] = {}
    chunks: list[dict[str, Any]] = []
    pending: list[tuple[int, str]] = []

    def section_path() -> list[str]:
        return [section_by_level[level] for level in sorted(section_by_level) if level >= 2]

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        current: list[tuple[int, str]] = []
        for line_number, raw_text in pending:
            pieces = split_long_text(raw_text, max_chars)
            for piece in pieces:
                item = (line_number, piece)
                projected = len("\n".join(text for _, text in current + [item]))
                if current and projected > max_chars:
                    chunks.append(
                        make_chunk(
                            source_file=path.name,
                            metadata=metadata,
                            section_path=section_path(),
                            lines=current,
                        )
                    )
                    overlap = current[-overlap_items:] if overlap_items else []
                    overlap_size = len("\n".join(text for _, text in overlap + [item]))
                    current = overlap if overlap and overlap_size <= max_chars else []
                current.append(item)
        if current:
            chunks.append(
                make_chunk(
                    source_file=path.name,
                    metadata=metadata,
                    section_path=section_path(),
                    lines=current,
                )
            )
        pending = []

    for line_number, raw_line in enumerate(body_lines, start=first_body_line):
        line = raw_line.strip()
        if not line or line.startswith("来源文件："):
            continue
        heading_match = HEADING_RE.match(line)
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            section_by_level[level] = title
            for existing_level in list(section_by_level):
                if existing_level > level:
                    del section_by_level[existing_level]
            continue
        # The initial table of contents is noisy and is superseded by real sections.
        if section_path() == ["正文"]:
            continue
        pending.append((line_number, line))
    flush()
    return [chunk for chunk in chunks if chunk["text"]]


def tokenize_for_zh(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens: list[str] = []
    for span in TOKEN_RE.findall(normalized):
        if re.fullmatch(r"[\u4e00-\u9fff]+", span):
            words = [word.strip() for word in jieba.lcut(span) if word.strip()]
            tokens.extend(words)
            if len(span) >= 2:
                tokens.extend(span[index : index + 2] for index in range(len(span) - 1))
        else:
            tokens.append(span)
            letter_number_parts = re.findall(r"[a-z]+|\d+(?:\.\d+)?", span)
            if len(letter_number_parts) > 1:
                tokens.extend(letter_number_parts)
    return tokens


def expand_query(text: str) -> str:
    """Add only transparent domain synonyms that a keyword baseline can explain."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    additions: list[str] = []
    if any(word in normalized for word in ["长、宽、高", "长宽高", "外形尺寸", "外廓尺寸"]):
        additions.extend(["尺寸", "外形", "外廓", "长", "宽", "高"])
    if "多重" in normalized:
        additions.append("重量")
    return text + (" " + " ".join(additions) if additions else "")


def query_scope(query: str) -> tuple[set[str], set[str]]:
    normalized = unicodedata.normalize("NFKC", query).lower()
    products: set[str] = set()
    if "m1212" in normalized or "ml001" in normalized:
        products.add("M1212(ML001)")
    if "mi012" in normalized:
        products.add("MI012")
    if "w001" in normalized:
        products.add("W001鼠标")
    document_types: set[str] = set()
    if "验收" in normalized:
        document_types.add("验收测试程序")
    if "产品规范" in normalized:
        document_types.add("产品规范")
    return products, document_types


def indexed_text(chunk: dict[str, Any]) -> str:
    return " ".join(
        value
        for value in [
            chunk["product_group"],
            chunk["document_type"],
            chunk["source_file"],
            chunk["section"],
            chunk["text"],
        ]
        if value
    )


def build_index(root: Path) -> tuple[list[dict[str, Any]], Path]:
    corpus_dir = root / "data" / "processed" / "sanitized"
    output_dir = root / "data" / "processed" / "retrieval"
    index_dir = output_dir / "bm25s_index"
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks = [
        chunk
        for path in sorted(corpus_dir.glob("*.md"))
        for chunk in chunk_markdown(path)
    ]
    if not chunks:
        raise RuntimeError(f"未在 {corpus_dir} 找到可索引内容")

    chunks_path = output_dir / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8", newline="\n") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    search_texts = [" ".join(tokenize_for_zh(indexed_text(chunk))) for chunk in chunks]
    tokenizer = Tokenizer(splitter=lambda value: value.split(), stopwords=[])
    corpus_tokens = tokenizer.tokenize(search_texts, return_as="tuple")
    retriever = bm25s.BM25(corpus=chunks, method="lucene")
    retriever.index(corpus_tokens, show_progress=False)
    index_dir.mkdir(parents=True, exist_ok=True)
    retriever.save(index_dir, corpus=chunks)
    tokenizer.save_vocab(index_dir)
    tokenizer.save_stopwords(index_dir)

    summary = {
        "document_count": len({chunk["source_id"] for chunk in chunks}),
        "chunk_count": len(chunks),
        "acl_values": sorted({chunk["acl"] for chunk in chunks}),
        "max_chars": 900,
        "overlap_items": 1,
        "index_dir": str(index_dir.relative_to(root)).replace("\\", "/"),
    }
    (output_dir / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return chunks, index_dir


def load_retriever(index_dir: Path) -> tuple[Any, Tokenizer]:
    retriever = bm25s.BM25.load(index_dir, load_corpus=True)
    tokenizer = Tokenizer(splitter=lambda value: value.split(), stopwords=[])
    tokenizer.load_vocab(index_dir)
    tokenizer.load_stopwords(index_dir)
    return retriever, tokenizer


def search(
    retriever: Any,
    tokenizer: Tokenizer,
    query: str,
    *,
    user_group: str,
    k: int,
) -> dict[str, Any]:
    available_acls = {str(item.get("acl", "")) for item in retriever.corpus}
    if user_group not in available_acls:
        return {
            "query": query,
            "user_group": user_group,
            "blocked": True,
            "reason": "当前用户组无权访问检索语料",
            "results": [],
        }
    scoped_products, scoped_document_types = query_scope(query)
    allowed_mask = np.array(
        [
            item.get("acl") == user_group
            and (not scoped_products or item.get("product_group") in scoped_products)
            and (
                not scoped_document_types
                or item.get("document_type") in scoped_document_types
            )
            for item in retriever.corpus
        ],
        dtype=np.float32,
    )
    allowed_count = int(allowed_mask.sum())
    if allowed_count == 0:
        return {
            "query": query,
            "user_group": user_group,
            "blocked": False,
            "reason": "查询范围内没有可访问语料",
            "results": [],
        }
    query_text = " ".join(tokenize_for_zh(expand_query(query)))
    query_tokens = tokenizer.tokenize([query_text], update_vocab=False, return_as="tuple")
    # Retrieve extra candidates, then limit repeated hits from the same source.
    # This keeps cross-document comparison questions from being crowded out by
    # near-duplicate chunks from one long document.
    limit = min(max(k * 8, 30), allowed_count)
    documents, scores = retriever.retrieve(
        query_tokens,
        k=limit,
        show_progress=False,
        return_as="tuple",
        weight_mask=allowed_mask,
    )
    results = []
    per_source: defaultdict[str, int] = defaultdict(int)
    per_product: defaultdict[str, int] = defaultdict(int)
    diversify_products = len(scoped_products) > 1
    for document, score in zip(documents[0], scores[0]):
        if document.get("acl") != user_group:
            continue
        if scoped_products and document.get("product_group") not in scoped_products:
            continue
        if scoped_document_types and document.get("document_type") not in scoped_document_types:
            continue
        source_id = document["source_id"]
        product_group = document.get("product_group", "")
        source_cap = 2 if diversify_products else k
        if per_source[source_id] >= source_cap:
            continue
        if diversify_products and per_product[product_group] >= 2:
            continue
        per_source[source_id] += 1
        per_product[product_group] += 1
        rank = len(results) + 1
        results.append(
            {
                "rank": rank,
                "score": round(float(score), 6),
                "chunk_id": document["chunk_id"],
                "source_id": document["source_id"],
                "source_file": document["source_file"],
                "section": document["section"],
                "locator": document["locator"],
                "paragraph_numbers": document["paragraph_numbers"],
                "table_numbers": document["table_numbers"],
            }
        )
        if len(results) >= k:
            break
    return {
        "query": query,
        "user_group": user_group,
        "blocked": False,
        "results": results[:k],
    }


def expand_number_expression(expression: str) -> set[int]:
    values: set[int] = set()
    for start, end in re.findall(r"\[(\d+)](?:\s*[-~至]\s*\[(\d+)])?", expression):
        first = int(start)
        last = int(end) if end else first
        values.update(range(min(first, last), max(first, last) + 1))
    return values


def locator_targets(question: dict[str, Any]) -> list[dict[str, Any]]:
    source_ids = question["source_ids"].split(";")
    segments = re.split(r"[；;]", question["locator"])
    by_source: dict[str, dict[str, Any]] = {
        source_id: {"source_id": source_id, "paragraph_numbers": set(), "table_numbers": set()}
        for source_id in source_ids
    }
    if len(source_ids) == 1:
        assignments = [(source_ids[0], segment) for segment in segments]
    else:
        assignments = [
            (source_id, segments[index] if index < len(segments) else question["locator"])
            for index, source_id in enumerate(source_ids)
        ]
    for source_id, segment in assignments:
        by_source[source_id]["paragraph_numbers"].update(expand_number_expression(segment))
        by_source[source_id]["table_numbers"].update(
            int(value) for value in re.findall(r"表格\s*(\d+)", segment)
        )
    return list(by_source.values())


def covered_targets(question: dict[str, Any], results: list[dict[str, Any]]) -> tuple[int, int]:
    targets = locator_targets(question)
    covered = 0
    for target in targets:
        source_results = [item for item in results if item["source_id"] == target["source_id"]]
        if not source_results:
            continue
        expected_paragraphs = target["paragraph_numbers"]
        expected_tables = target["table_numbers"]
        found_paragraphs = {
            number for item in source_results for number in item["paragraph_numbers"]
        }
        found_tables = {number for item in source_results for number in item["table_numbers"]}
        # Ranges can include image-only or omitted paragraph IDs. For locator
        # coverage, one explicit anchor in the expected range is sufficient.
        paragraph_ok = not expected_paragraphs or bool(expected_paragraphs & found_paragraphs)
        table_ok = not expected_tables or expected_tables <= found_tables
        if paragraph_ok and table_ok:
            covered += 1
    return covered, len(targets)


def reciprocal_rank(expected_source_ids: set[str], results: list[dict[str, Any]]) -> float:
    for item in results:
        if item["source_id"] in expected_source_ids:
            return 1.0 / item["rank"]
    return 0.0


def evaluate(root: Path, top_k: int = 5) -> dict[str, Any]:
    index_dir = root / "data" / "processed" / "retrieval" / "bm25s_index"
    retriever, tokenizer = load_retriever(index_dir)
    questions = json.loads((root / "eval" / "golden_questions.json").read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for question in questions:
        response = search(
            retriever,
            tokenizer,
            question["question"],
            user_group=question["user_group"],
            k=top_k,
        )
        expected_sources = set(question["source_ids"].split(";"))
        returned_sources = {item["source_id"] for item in response["results"]}
        source_hits = len(expected_sources & returned_sources)
        locator_hits, locator_total = covered_targets(question, response["results"])
        permission_expected = question["category"] == "权限隔离" and question["user_group"] != question["required_acl"]
        if permission_expected:
            passed = response["blocked"] and not response["results"]
        else:
            passed = source_hits == len(expected_sources) and locator_hits == locator_total
        rows.append(
            {
                "question_id": question["question_id"],
                "category": question["category"],
                "question": question["question"],
                "user_group": question["user_group"],
                "blocked": response["blocked"],
                "passed": passed,
                "source_hits": source_hits,
                "source_total": len(expected_sources),
                "locator_hits": locator_hits,
                "locator_total": locator_total,
                "reciprocal_rank": reciprocal_rank(expected_sources, response["results"]),
                "results": response["results"],
            }
        )

    content_rows = [row for row in rows if not row["blocked"]]
    summary = {
        "question_count": len(rows),
        "top_k": top_k,
        "pass_count": sum(bool(row["passed"]) for row in rows),
        "pass_rate": round(sum(bool(row["passed"]) for row in rows) / len(rows), 4),
        "content_question_count": len(content_rows),
        "source_coverage": round(
            sum(row["source_hits"] for row in content_rows)
            / max(1, sum(row["source_total"] for row in content_rows)),
            4,
        ),
        "locator_coverage": round(
            sum(row["locator_hits"] for row in content_rows)
            / max(1, sum(row["locator_total"] for row in content_rows)),
            4,
        ),
        "mrr": round(
            sum(row["reciprocal_rank"] for row in content_rows) / max(1, len(content_rows)),
            4,
        ),
        "permission_block_passed": all(
            row["passed"]
            for row in rows
            if row["category"] == "权限隔离" and row["user_group"] != "fde-core"
        ),
    }
    report = {"summary": summary, "questions": rows}
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "bm25_baseline_eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    markdown = [
        "# BM25S 基线评测",
        "",
        "> 本报告只验证检索、证据定位和模拟权限拦截，不代表 RAG 回答质量或业务验收。",
        "",
        "## 汇总",
        "",
        f"- 评测题：{summary['question_count']} 道",
        f"- Top K：{summary['top_k']}",
        f"- 严格通过：{summary['pass_count']}/{summary['question_count']}（{summary['pass_rate']:.0%}）",
        f"- 预期来源覆盖率：{summary['source_coverage']:.0%}",
        f"- 预期定位覆盖率：{summary['locator_coverage']:.0%}",
        f"- MRR：{summary['mrr']:.4f}",
        f"- 无权限问题拦截：{'通过' if summary['permission_block_passed'] else '未通过'}",
        "",
        "## 逐题结果",
        "",
        "| 题号 | 类型 | 结果 | 来源覆盖 | 定位覆盖 | 首个相关来源排名 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        rank = "—" if row["reciprocal_rank"] == 0 else str(round(1 / row["reciprocal_rank"]))
        markdown.append(
            f"| {row['question_id']} | {row['category']} | {'通过' if row['passed'] else '未通过'} "
            f"| {row['source_hits']}/{row['source_total']} | {row['locator_hits']}/{row['locator_total']} | {rank} |"
        )
    failed = [row["question_id"] for row in rows if not row["passed"]]
    markdown.extend(
        [
            "",
            "## 边界与下一步",
            "",
            f"- 未通过题目：{', '.join(failed) if failed else '无'}。",
            "- 当前权限为 PoC 模拟值：语料统一标记为 `fde-core`，其他用户组在检索前直接拦截。",
            "- 本阶段没有接入 Embedding、Qdrant、Rerank 或大模型，不评价语义召回与最终回答质量。",
            "- 下一步应针对未通过题目检查切块或分词，再建立 BGE-M3 向量检索对照组。",
            "",
        ]
    )
    (reports_dir / "bm25_baseline_eval.md").write_text("\n".join(markdown), encoding="utf-8")
    return report


def print_search(result: dict[str, Any]) -> None:
    if result["blocked"]:
        print(f"已拦截：{result['reason']}")
        return
    for item in result["results"]:
        print(
            f"{item['rank']}. {item['source_file']} | {item['section']} | "
            f"{item['locator']} | score={item['score']:.4f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="团队知识库 BM25S 最小检索基线")
    parser.add_argument("project_root", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("build", help="切块并建立 BM25S 索引")
    evaluate_parser = subparsers.add_parser("evaluate", help="运行种子评测题")
    evaluate_parser.add_argument("--top-k", type=int, default=5)
    search_parser = subparsers.add_parser("search", help="执行一次检索")
    search_parser.add_argument("query")
    search_parser.add_argument("--user-group", default="fde-core")
    search_parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    root = args.project_root.resolve()
    if args.command == "build":
        chunks, index_dir = build_index(root)
        print(f"已生成 {len(chunks)} 个切块；索引：{index_dir}")
    elif args.command == "evaluate":
        report = evaluate(root, top_k=args.top_k)
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    else:
        index_dir = root / "data" / "processed" / "retrieval" / "bm25s_index"
        retriever, tokenizer = load_retriever(index_dir)
        result = search(
            retriever,
            tokenizer,
            args.query,
            user_group=args.user_group,
            k=args.top_k,
        )
        print_search(result)


if __name__ == "__main__":
    main()
