from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

from bm25_baseline import covered_targets, query_scope, reciprocal_rank


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def setting(name: str, default: str) -> str:
    return os.environ.get(name, default)


def paths(root: Path) -> tuple[Path, Path, str, Path]:
    chunks_path = root / "data" / "processed" / "retrieval" / "chunks.jsonl"
    qdrant_path = root / setting("QDRANT_PATH", "data/processed/retrieval/qdrant")
    collection = setting("QDRANT_COLLECTION", "kb_chunks_bge_m3")
    cache_path = root / setting("MODEL_CACHE_DIR", ".cache/models")
    return chunks_path, qdrant_path, collection, cache_path


def load_chunks(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise RuntimeError("尚未生成 chunks.jsonl，请先运行 bm25-build")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def embedding_text(chunk: dict[str, Any]) -> str:
    return "\n".join(
        value
        for value in [
            chunk.get("product_group", ""),
            chunk.get("document_type", ""),
            chunk.get("source_file", ""),
            chunk.get("section", ""),
            chunk.get("text", ""),
        ]
        if value
    )


def load_model(cache_path: Path) -> SentenceTransformer:
    cache_path.mkdir(parents=True, exist_ok=True)
    local_model = cache_path.parent / "modelscope" / "bge-m3"
    local_weights = local_model / "pytorch_model.bin"
    default_model = str(local_model) if local_weights.exists() and local_weights.stat().st_size > 1_000_000 else "BAAI/bge-m3"
    return SentenceTransformer(
        setting("EMBEDDING_MODEL", default_model),
        device=setting("EMBEDDING_DEVICE", "cpu"),
        cache_folder=str(cache_path),
    )


def build(root: Path, batch_size: int) -> dict[str, Any]:
    chunks_path, qdrant_path, collection, cache_path = paths(root)
    chunks = load_chunks(chunks_path)
    model = load_model(cache_path)
    vectors = model.encode(
        [embedding_text(chunk) for chunk in chunks],
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    qdrant_path.mkdir(parents=True, exist_ok=True)
    client = QdrantClient(path=str(qdrant_path))
    if client.collection_exists(collection):
        client.delete_collection(collection)
    client.create_collection(
        collection_name=collection,
        vectors_config=models.VectorParams(size=int(vectors.shape[1]), distance=models.Distance.COSINE),
    )
    points = [
        models.PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk["chunk_id"])),
            vector=vector.tolist(),
            payload=chunk,
        )
        for chunk, vector in zip(chunks, vectors)
    ]
    client.upload_points(collection_name=collection, points=points, batch_size=64, wait=True)
    count = client.count(collection_name=collection, exact=True).count
    client.close()
    if count != len(chunks):
        raise RuntimeError(f"向量入库数量不一致：预期 {len(chunks)}，实际 {count}")
    return {"collection": collection, "chunks": len(chunks), "vector_size": int(vectors.shape[1])}


class VectorRetriever:
    def __init__(self, root: Path) -> None:
        chunks_path, qdrant_path, self.collection, cache_path = paths(root)
        self.chunks = load_chunks(chunks_path)
        self.available_acls = {str(chunk.get("acl", "")) for chunk in self.chunks}
        self.client = QdrantClient(path=str(qdrant_path))
        if not self.client.collection_exists(self.collection):
            raise RuntimeError("尚未建立 Qdrant 向量库，请先运行 vector-build")
        self.model = load_model(cache_path)

    def close(self) -> None:
        self.client.close()

    def search(self, query: str, user_group: str, k: int) -> dict[str, Any]:
        if user_group not in self.available_acls:
            return {
                "query": query,
                "user_group": user_group,
                "blocked": True,
                "reason": "当前用户组无权访问检索语料",
                "results": [],
            }
        products, document_types = query_scope(query)
        conditions: list[models.Condition] = [
            models.FieldCondition(key="acl", match=models.MatchValue(value=user_group))
        ]
        if products:
            conditions.append(models.FieldCondition(key="product_group", match=models.MatchAny(any=list(products))))
        if document_types:
            conditions.append(models.FieldCondition(key="document_type", match=models.MatchAny(any=list(document_types))))
        query_vector = self.model.encode(query, normalize_embeddings=True).tolist()
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=models.Filter(must=conditions),
            limit=max(k * 8, 30),
            with_payload=True,
        )
        results: list[dict[str, Any]] = []
        per_source: defaultdict[str, int] = defaultdict(int)
        per_product: defaultdict[str, int] = defaultdict(int)
        diversify_products = len(products) > 1
        for point in response.points:
            payload = dict(point.payload or {})
            source_id = str(payload.get("source_id", ""))
            product = str(payload.get("product_group", ""))
            source_cap = 2 if diversify_products else k
            if per_source[source_id] >= source_cap:
                continue
            if diversify_products and per_product[product] >= 2:
                continue
            per_source[source_id] += 1
            per_product[product] += 1
            payload["score"] = round(float(point.score), 6)
            payload["rank"] = len(results) + 1
            results.append(payload)
            if len(results) == k:
                break
        return {"query": query, "user_group": user_group, "blocked": False, "reason": "", "results": results}


def evaluate(root: Path, top_k: int) -> dict[str, Any]:
    questions = json.loads((root / "eval" / "golden_questions.json").read_text(encoding="utf-8"))
    retriever = VectorRetriever(root)
    rows: list[dict[str, Any]] = []
    try:
        for question in questions:
            response = retriever.search(question["question"], question["user_group"], top_k)
            expected_sources = set(question["source_ids"].split(";"))
            returned_sources = {item["source_id"] for item in response["results"]}
            source_hits = len(expected_sources & returned_sources)
            locator_hits, locator_total = covered_targets(question, response["results"])
            permission_expected = question["category"] == "权限隔离" and question["user_group"] != question["required_acl"]
            passed = (
                response["blocked"] and not response["results"]
                if permission_expected
                else source_hits == len(expected_sources) and locator_hits == locator_total
            )
            rows.append({
                "question_id": question["question_id"],
                "category": question["category"],
                "question": question["question"],
                "blocked": response["blocked"],
                "passed": passed,
                "source_hits": source_hits,
                "source_total": len(expected_sources),
                "locator_hits": locator_hits,
                "locator_total": locator_total,
                "reciprocal_rank": reciprocal_rank(expected_sources, response["results"]),
                "results": response["results"],
            })
    finally:
        retriever.close()
    content_rows = [row for row in rows if not row["blocked"]]
    summary = {
        "question_count": len(rows),
        "top_k": top_k,
        "pass_count": sum(bool(row["passed"]) for row in rows),
        "pass_rate": round(sum(bool(row["passed"]) for row in rows) / len(rows), 4),
        "source_coverage": round(sum(row["source_hits"] for row in content_rows) / max(1, sum(row["source_total"] for row in content_rows)), 4),
        "locator_coverage": round(sum(row["locator_hits"] for row in content_rows) / max(1, sum(row["locator_total"] for row in content_rows)), 4),
        "mrr": round(sum(row["reciprocal_rank"] for row in content_rows) / max(1, len(content_rows)), 4),
        "failed_questions": [row["question_id"] for row in rows if not row["passed"]],
    }
    report = {"summary": summary, "questions": rows}
    report_path = root / "reports" / "vector_baseline_eval.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def print_search(response: dict[str, Any]) -> None:
    if response["blocked"]:
        print(response["reason"])
        return
    for item in response["results"]:
        print(f'[{item["rank"]}] {item["source_file"]} | {item["locator"]} | score={item["score"]}')
        print(item["text"][:400].replace("\n", " "))


def main() -> None:
    parser = argparse.ArgumentParser(description="团队知识库 BGE-M3 + Qdrant 向量检索基线")
    parser.add_argument("project_root", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--batch-size", type=int, default=4)
    eval_parser = subparsers.add_parser("evaluate")
    eval_parser.add_argument("--top-k", type=int, default=5)
    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--user-group", default="fde-core")
    search_parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    root = args.project_root.resolve()
    if args.command == "build":
        print(json.dumps(build(root, args.batch_size), ensure_ascii=False, indent=2))
    elif args.command == "evaluate":
        print(json.dumps(evaluate(root, args.top_k)["summary"], ensure_ascii=False, indent=2))
    else:
        retriever = VectorRetriever(root)
        try:
            print_search(retriever.search(args.query, args.user_group, args.top_k))
        finally:
            retriever.close()


if __name__ == "__main__":
    main()
