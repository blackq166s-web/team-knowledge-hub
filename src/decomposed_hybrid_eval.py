from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Protocol

from bm25_baseline import covered_targets, reciprocal_rank
from deepseek_decomposition import (
    DeepSeekDecomposer,
    Decomposition,
    augment_retrieval_query,
    inherit_retrieval_scope,
)
from hybrid_baseline import HybridRetriever, reciprocal_rank_fusion


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class Decomposer(Protocol):
    def decompose(self, query: str) -> Decomposition: ...


class DecomposedHybridRetriever:
    def __init__(
        self,
        root: Path,
        *,
        decomposer: Decomposer | None = None,
        per_query_k: int = 10,
        hybrid: HybridRetriever | None = None,
    ) -> None:
        self.hybrid = hybrid if hybrid is not None else HybridRetriever(root, candidate_k=20)
        self.decomposer = decomposer or DeepSeekDecomposer()
        self.per_query_k = per_query_k

    def close(self) -> None:
        self.hybrid.close()

    def search(self, query: str, user_group: str, k: int) -> dict[str, Any]:
        if user_group not in self.hybrid.available_acls:
            return {
                "query": query,
                "user_group": user_group,
                "blocked": True,
                "reason": "当前用户组无权访问检索语料",
                "decomposition": None,
                "results": [],
            }

        decomposition = self.decomposer.decompose(query)
        queries = [query, *decomposition.subqueries] if decomposition.should_decompose else [query]
        if decomposition.should_decompose:
            retrieval_queries = [query, *(inherit_retrieval_scope(query, item) for item in decomposition.subqueries)]
        else:
            augmented = augment_retrieval_query(query)
            retrieval_queries = [query] + ([augmented] if augmented != query else [])
        responses = [self.hybrid.search(item, user_group, self.per_query_k) for item in retrieval_queries]
        result_lists = {
            f"query_{index}": response["results"]
            for index, response in enumerate(responses)
        }
        fused = reciprocal_rank_fusion(result_lists)
        fused_by_id = {str(item["chunk_id"]): item for item in fused}

        selected_ids: list[str] = []
        # Each generated subquery gets one evidence slot before global score filling.
        if decomposition.should_decompose:
            for response in responses[1:]:
                for item in response["results"]:
                    chunk_id = str(item["chunk_id"])
                    if chunk_id not in selected_ids:
                        selected_ids.append(chunk_id)
                        break
        for entry in fused:
            chunk_id = str(entry["chunk_id"])
            if chunk_id not in selected_ids:
                selected_ids.append(chunk_id)
            if len(selected_ids) >= k:
                break

        results: list[dict[str, Any]] = []
        for chunk_id in selected_ids[:k]:
            entry = fused_by_id[chunk_id]
            canonical = dict(self.hybrid.chunk_by_id.get(chunk_id, entry["fallback"]))
            if canonical.get("acl") != user_group:
                continue
            canonical["rank"] = len(results) + 1
            canonical["score"] = round(float(entry["rrf_score"]), 8)
            canonical["query_hits"] = entry["retrievers"]
            results.append(canonical)
        return {
            "query": query,
            "user_group": user_group,
            "blocked": False,
            "reason": "",
            "decomposition": decomposition.to_dict(),
            "queries": queries,
            "retrieval_queries": retrieval_queries,
            "results": results,
        }


def percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return ordered[index]


def evaluate(root: Path, *, top_k: int, per_query_k: int) -> dict[str, Any]:
    questions = json.loads((root / "eval" / "golden_questions.json").read_text(encoding="utf-8"))
    retriever = DecomposedHybridRetriever(root, per_query_k=per_query_k)
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
                "decomposition": response["decomposition"],
                "queries": response.get("queries", []),
                "retrieval_queries": response.get("retrieval_queries", []),
                "results": response["results"],
            })
    finally:
        retriever.close()

    content_rows = [row for row in rows if not row["blocked"]]
    decompositions = [row["decomposition"] for row in content_rows if row["decomposition"]]
    latencies = [float(item["latency_ms"]) for item in decompositions if item["status"] == "success"]
    status_counts: defaultdict[str, int] = defaultdict(int)
    for item in decompositions:
        status_counts[str(item["status"])] += 1
    summary = {
        "question_count": len(rows),
        "top_k": top_k,
        "per_query_k": per_query_k,
        "pass_count": sum(bool(row["passed"]) for row in rows),
        "pass_rate": round(sum(bool(row["passed"]) for row in rows) / len(rows), 4),
        "source_coverage": round(sum(row["source_hits"] for row in content_rows) / max(1, sum(row["source_total"] for row in content_rows)), 4),
        "locator_coverage": round(sum(row["locator_hits"] for row in content_rows) / max(1, sum(row["locator_total"] for row in content_rows)), 4),
        "mrr": round(sum(row["reciprocal_rank"] for row in content_rows) / max(1, len(content_rows)), 4),
        "decomposition_status_counts": dict(status_counts),
        "deepseek_success_count": status_counts["success"],
        "decomposed_question_count": sum(bool(item["should_decompose"]) for item in decompositions),
        "mean_decomposition_latency_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
        "p95_decomposition_latency_ms": round(percentile_95(latencies), 2),
        "permission_block_passed": all(row["passed"] for row in rows if row["blocked"]),
        "failed_questions": [row["question_id"] for row in rows if not row["passed"]],
    }
    report = {"summary": summary, "questions": rows}
    report_path = root / "reports" / "deepseek_decomposition_eval.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def print_search(response: dict[str, Any]) -> None:
    if response["blocked"]:
        print(response["reason"])
        return
    decomposition = response["decomposition"]
    print(json.dumps(decomposition, ensure_ascii=False, indent=2))
    for item in response["results"]:
        print(f'[{item["rank"]}] {item["source_file"]} | {item["locator"]} | score={item["score"]}')
        print(item.get("text", "")[:400].replace("\n", " "))


def main() -> None:
    parser = argparse.ArgumentParser(description="DeepSeek 复杂问题拆分 + 混合检索评测")
    parser.add_argument("project_root", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    eval_parser = subparsers.add_parser("evaluate")
    eval_parser.add_argument("--top-k", type=int, default=5)
    eval_parser.add_argument("--per-query-k", type=int, default=10)
    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--user-group", default="fde-core")
    search_parser.add_argument("--top-k", type=int, default=5)
    search_parser.add_argument("--per-query-k", type=int, default=10)
    args = parser.parse_args()
    root = args.project_root.resolve()
    if args.command == "evaluate":
        print(json.dumps(evaluate(root, top_k=args.top_k, per_query_k=args.per_query_k)["summary"], ensure_ascii=False, indent=2))
    else:
        retriever = DecomposedHybridRetriever(root, per_query_k=args.per_query_k)
        try:
            print_search(retriever.search(args.query, args.user_group, args.top_k))
        finally:
            retriever.close()


if __name__ == "__main__":
    main()
