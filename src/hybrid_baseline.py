from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from bm25_baseline import (
    covered_targets,
    load_retriever,
    query_scope,
    reciprocal_rank,
    search as bm25_search,
)
from vector_baseline import VectorRetriever


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def reciprocal_rank_fusion(
    result_lists: dict[str, list[dict[str, Any]]],
    *,
    rank_constant: int = 60,
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Fuse rankings by chunk_id without mixing incomparable raw scores."""
    weights = weights or {name: 1.0 for name in result_lists}
    fused: dict[str, dict[str, Any]] = {}
    for retriever_name, results in result_lists.items():
        weight = weights.get(retriever_name, 1.0)
        for item in results:
            chunk_id = str(item["chunk_id"])
            entry = fused.setdefault(
                chunk_id,
                {"rrf_score": 0.0, "retrievers": {}, "fallback": item},
            )
            entry["rrf_score"] += weight / (rank_constant + int(item["rank"]))
            entry["retrievers"][retriever_name] = {
                "rank": int(item["rank"]),
                "score": float(item["score"]),
            }
    return sorted(
        ({"chunk_id": chunk_id, **entry} for chunk_id, entry in fused.items()),
        key=lambda item: (-item["rrf_score"], item["chunk_id"]),
    )


class HybridRetriever:
    def __init__(
        self,
        root: Path,
        *,
        candidate_k: int = 20,
        rank_constant: int = 60,
        bm25_weight: float = 1.0,
        vector_weight: float = 1.0,
    ) -> None:
        index_dir = root / "data" / "processed" / "retrieval" / "bm25s_index"
        self.bm25, self.tokenizer = load_retriever(index_dir)
        self.vector = VectorRetriever(root)
        self.chunk_by_id = {str(chunk["chunk_id"]): chunk for chunk in self.vector.chunks}
        self.available_acls = {str(item.get("acl", "")) for item in self.bm25.corpus}
        self.candidate_k = candidate_k
        self.rank_constant = rank_constant
        self.weights = {"bm25": bm25_weight, "vector": vector_weight}

    def close(self) -> None:
        self.vector.close()

    def search(self, query: str, user_group: str, k: int) -> dict[str, Any]:
        if user_group not in self.available_acls or user_group not in self.vector.available_acls:
            return {
                "query": query,
                "user_group": user_group,
                "blocked": True,
                "reason": "当前用户组无权访问检索语料",
                "results": [],
            }
        bm25_response = bm25_search(
            self.bm25,
            self.tokenizer,
            query,
            user_group=user_group,
            k=self.candidate_k,
        )
        vector_response = self.vector.search(query, user_group, self.candidate_k)
        fused = reciprocal_rank_fusion(
            {
                "bm25": bm25_response["results"],
                "vector": vector_response["results"],
            },
            rank_constant=self.rank_constant,
            weights=self.weights,
        )
        products, _ = query_scope(query)
        diversify_products = len(products) > 1
        per_source: defaultdict[str, int] = defaultdict(int)
        per_product: defaultdict[str, int] = defaultdict(int)
        results: list[dict[str, Any]] = []
        for entry in fused:
            canonical = dict(self.chunk_by_id.get(entry["chunk_id"], entry["fallback"]))
            if canonical.get("acl") != user_group:
                continue
            source_id = str(canonical.get("source_id", ""))
            product = str(canonical.get("product_group", ""))
            source_cap = 2 if diversify_products else k
            if per_source[source_id] >= source_cap:
                continue
            if diversify_products and per_product[product] >= 2:
                continue
            per_source[source_id] += 1
            per_product[product] += 1
            canonical["rank"] = len(results) + 1
            canonical["score"] = round(float(entry["rrf_score"]), 8)
            canonical["retrievers"] = entry["retrievers"]
            results.append(canonical)
            if len(results) == k:
                break
        return {
            "query": query,
            "user_group": user_group,
            "blocked": False,
            "reason": "",
            "results": results,
        }


def evaluate(
    root: Path,
    *,
    top_k: int,
    candidate_k: int,
    rank_constant: int,
    bm25_weight: float,
    vector_weight: float,
) -> dict[str, Any]:
    questions = json.loads((root / "eval" / "golden_questions.json").read_text(encoding="utf-8"))
    retriever = HybridRetriever(
        root,
        candidate_k=candidate_k,
        rank_constant=rank_constant,
        bm25_weight=bm25_weight,
        vector_weight=vector_weight,
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
                "results": response["results"],
            })
    finally:
        retriever.close()
    content_rows = [row for row in rows if not row["blocked"]]
    summary = {
        "question_count": len(rows),
        "top_k": top_k,
        "candidate_k": candidate_k,
        "rank_constant": rank_constant,
        "weights": {"bm25": bm25_weight, "vector": vector_weight},
        "pass_count": sum(bool(row["passed"]) for row in rows),
        "pass_rate": round(sum(bool(row["passed"]) for row in rows) / len(rows), 4),
        "source_coverage": round(sum(row["source_hits"] for row in content_rows) / max(1, sum(row["source_total"] for row in content_rows)), 4),
        "locator_coverage": round(sum(row["locator_hits"] for row in content_rows) / max(1, sum(row["locator_total"] for row in content_rows)), 4),
        "mrr": round(sum(row["reciprocal_rank"] for row in content_rows) / max(1, len(content_rows)), 4),
        "permission_block_passed": all(
            row["passed"] for row in rows if row["category"] == "权限隔离" and row["blocked"]
        ),
        "failed_questions": [row["question_id"] for row in rows if not row["passed"]],
    }
    report = {"summary": summary, "questions": rows}
    report_path = root / "reports" / f"hybrid_baseline_eval_top{top_k}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def print_search(response: dict[str, Any]) -> None:
    if response["blocked"]:
        print(response["reason"])
        return
    for item in response["results"]:
        methods = ", ".join(
            f'{name}=#{details["rank"]}' for name, details in item["retrievers"].items()
        )
        print(f'[{item["rank"]}] {item["source_file"]} | {item["locator"]} | RRF={item["score"]} | {methods}')
        print(item.get("text", "")[:400].replace("\n", " "))


def add_fusion_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidate-k", type=int, default=20)
    parser.add_argument("--rank-constant", type=int, default=60)
    parser.add_argument("--bm25-weight", type=float, default=1.0)
    parser.add_argument("--vector-weight", type=float, default=1.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="团队知识库 BM25S + BGE-M3 RRF 混合检索基线")
    parser.add_argument("project_root", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    eval_parser = subparsers.add_parser("evaluate")
    eval_parser.add_argument("--top-k", type=int, default=5)
    add_fusion_arguments(eval_parser)
    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--user-group", default="fde-core")
    search_parser.add_argument("--top-k", type=int, default=5)
    add_fusion_arguments(search_parser)
    args = parser.parse_args()
    root = args.project_root.resolve()
    options = {
        "candidate_k": args.candidate_k,
        "rank_constant": args.rank_constant,
        "bm25_weight": args.bm25_weight,
        "vector_weight": args.vector_weight,
    }
    if args.command == "evaluate":
        report = evaluate(root, top_k=args.top_k, **options)
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    else:
        retriever = HybridRetriever(root, **options)
        try:
            print_search(retriever.search(args.query, args.user_group, args.top_k))
        finally:
            retriever.close()


if __name__ == "__main__":
    main()
