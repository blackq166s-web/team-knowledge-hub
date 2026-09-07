from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from sentence_transformers import CrossEncoder

from bm25_baseline import covered_targets, reciprocal_rank
from hybrid_baseline import HybridRetriever


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def model_path(root: Path) -> str:
    configured = os.environ.get("RERANK_MODEL")
    if configured:
        return configured
    local = root / ".cache" / "modelscope" / "bge-reranker-v2-m3"
    weights = local / "model.safetensors"
    if weights.exists() and weights.stat().st_size > 1_000_000:
        return str(local)
    return "BAAI/bge-reranker-v2-m3"


def passage_text(item: dict[str, Any]) -> str:
    return "\n".join(
        value
        for value in [
            item.get("product_group", ""),
            item.get("document_type", ""),
            item.get("source_file", ""),
            item.get("section", ""),
            item.get("text", ""),
        ]
        if value
    )


class RerankRetriever:
    def __init__(
        self,
        root: Path,
        *,
        hybrid_top_k: int = 10,
        retrieval_candidate_k: int = 20,
        batch_size: int = 1,
        max_length: int = 512,
    ) -> None:
        self.hybrid = HybridRetriever(root, candidate_k=retrieval_candidate_k)
        self.hybrid_top_k = hybrid_top_k
        self.batch_size = batch_size
        self.model = CrossEncoder(
            model_path(root),
            device=os.environ.get("RERANK_DEVICE", "cpu"),
            max_length=max_length,
        )

    def close(self) -> None:
        self.hybrid.close()

    def search(self, query: str, user_group: str, k: int) -> dict[str, Any]:
        response = self.hybrid.search(query, user_group, self.hybrid_top_k)
        if response["blocked"] or not response["results"]:
            response["rerank_latency_ms"] = 0.0
            return response
        candidates = response["results"]
        pairs = [(query, passage_text(item)) for item in candidates]
        started = time.perf_counter()
        scores = self.model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        reranked: list[dict[str, Any]] = []
        for item, rerank_score in sorted(
            zip(candidates, scores),
            key=lambda pair: (-float(pair[1]), int(pair[0]["rank"])),
        ):
            result = dict(item)
            result["hybrid_rank"] = int(item["rank"])
            result["hybrid_score"] = float(item["score"])
            result["rank"] = len(reranked) + 1
            result["score"] = round(float(rerank_score), 6)
            reranked.append(result)
            if len(reranked) == k:
                break
        return {
            "query": query,
            "user_group": user_group,
            "blocked": False,
            "reason": "",
            "rerank_latency_ms": round(latency_ms, 2),
            "results": reranked,
        }


def percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return ordered[index]


def evaluate(
    root: Path,
    *,
    top_k: int,
    hybrid_top_k: int,
    batch_size: int,
    max_length: int,
) -> dict[str, Any]:
    questions = json.loads((root / "eval" / "golden_questions.json").read_text(encoding="utf-8"))
    retriever = RerankRetriever(
        root,
        hybrid_top_k=hybrid_top_k,
        batch_size=batch_size,
        max_length=max_length,
    )
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
                "rerank_latency_ms": response["rerank_latency_ms"],
                "results": response["results"],
            })
    finally:
        retriever.close()
    content_rows = [row for row in rows if not row["blocked"]]
    latencies = [float(row["rerank_latency_ms"]) for row in content_rows]
    summary = {
        "question_count": len(rows),
        "hybrid_top_k": hybrid_top_k,
        "rerank_top_k": top_k,
        "batch_size": batch_size,
        "max_length": max_length,
        "pass_count": sum(bool(row["passed"]) for row in rows),
        "pass_rate": round(sum(bool(row["passed"]) for row in rows) / len(rows), 4),
        "source_coverage": round(sum(row["source_hits"] for row in content_rows) / max(1, sum(row["source_total"] for row in content_rows)), 4),
        "locator_coverage": round(sum(row["locator_hits"] for row in content_rows) / max(1, sum(row["locator_total"] for row in content_rows)), 4),
        "mrr": round(sum(row["reciprocal_rank"] for row in content_rows) / max(1, len(content_rows)), 4),
        "mean_rerank_latency_ms": round(statistics.mean(latencies), 2),
        "p95_rerank_latency_ms": round(percentile_95(latencies), 2),
        "permission_block_passed": all(
            row["passed"] for row in rows if row["category"] == "权限隔离" and row["blocked"]
        ),
        "failed_questions": [row["question_id"] for row in rows if not row["passed"]],
    }
    report = {"summary": summary, "questions": rows}
    report_path = root / "reports" / "rerank_baseline_eval.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def print_search(response: dict[str, Any]) -> None:
    if response["blocked"]:
        print(response["reason"])
        return
    print(f'重排耗时：{response["rerank_latency_ms"]:.2f} ms')
    for item in response["results"]:
        print(
            f'[{item["rank"]}] {item["source_file"]} | {item["locator"]} | '
            f'rerank={item["score"]} | hybrid=#{item["hybrid_rank"]}'
        )
        print(item.get("text", "")[:400].replace("\n", " "))


def main() -> None:
    parser = argparse.ArgumentParser(description="团队知识库混合召回 + BGE Rerank 基线")
    parser.add_argument("project_root", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    eval_parser = subparsers.add_parser("evaluate")
    eval_parser.add_argument("--top-k", type=int, default=5)
    eval_parser.add_argument("--hybrid-top-k", type=int, default=10)
    eval_parser.add_argument("--batch-size", type=int, default=1)
    eval_parser.add_argument("--max-length", type=int, default=512)
    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--user-group", default="fde-core")
    search_parser.add_argument("--top-k", type=int, default=5)
    search_parser.add_argument("--hybrid-top-k", type=int, default=10)
    search_parser.add_argument("--batch-size", type=int, default=1)
    search_parser.add_argument("--max-length", type=int, default=512)
    args = parser.parse_args()
    root = args.project_root.resolve()
    options = {
        "hybrid_top_k": args.hybrid_top_k,
        "batch_size": args.batch_size,
        "max_length": args.max_length,
    }
    if args.command == "evaluate":
        print(json.dumps(evaluate(root, top_k=args.top_k, **options)["summary"], ensure_ascii=False, indent=2))
    else:
        retriever = RerankRetriever(root, **options)
        try:
            print_search(retriever.search(args.query, args.user_group, args.top_k))
        finally:
            retriever.close()


if __name__ == "__main__":
    main()
