from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deepseek_decomposition import (
    augment_retrieval_query,
    inherit_retrieval_scope,
    should_decompose_locally,
    validate_subqueries,
)


class DecompositionValidationTests(unittest.TestCase):
    def test_detects_multi_product_question(self) -> None:
        self.assertTrue(should_decompose_locally("M1212、MI012和W001的看门狗时间有何不同？"))

    def test_keeps_simple_question_direct(self) -> None:
        self.assertFalse(should_decompose_locally("MI012的额定电压是多少？"))

    def test_detects_separate_dimensions(self) -> None:
        self.assertTrue(should_decompose_locally("MI012的长、宽、高分别是多少？"))

    def test_adds_structural_hints_without_answer_value(self) -> None:
        cover = augment_retrieval_query("W001验收测试程序当前封面版本是什么？")
        watchdog = augment_retrieval_query("W001的看门狗复位时间要求是什么？")
        rs422 = augment_retrieval_query("W001的RS422能力如何描述？")
        self.assertIn("版 本 号", cover)
        self.assertIn("测试方法", watchdog)
        self.assertIn("简要技术性能", rs422)
        self.assertNotIn("1V1.0.2", cover)

    def test_rewrites_dimension_question_with_missing_evidence_terms(self) -> None:
        rewritten = augment_retrieval_query("MI012模块的具体长、宽、高分别是多少？")
        self.assertEqual("MI012 具体 长 宽 高 外廓尺寸 见图 结构尺寸图", rewritten)

    def test_inherits_acceptance_scope(self) -> None:
        rewritten = inherit_retrieval_scope(
            "按验收合格条件比较三种产品的重量上限",
            "W001的重量上限是多少？",
        )
        self.assertIn("验收合格条件", rewritten)

    def test_accepts_valid_product_split(self) -> None:
        payload = {
            "should_decompose": True,
            "subqueries": [
                "M1212的看门狗复位时间要求是什么？",
                "MI012的看门狗复位时间要求是什么？",
                "W001的看门狗复位时间要求是什么？",
            ],
        }
        result = validate_subqueries("M1212、MI012和W001的看门狗复位时间有何不同？", payload)
        self.assertEqual(3, len(result))

    def test_expands_generic_three_product_question_from_allow_list(self) -> None:
        payload = {
            "should_decompose": True,
            "subqueries": [
                "M1212的看门狗复位时间要求是什么？",
                "MI012的看门狗复位时间要求是什么？",
                "W001的看门狗复位时间要求是什么？",
            ],
        }
        result = validate_subqueries("三种产品的看门狗复位时间要求有何不同？", payload)
        self.assertEqual(3, len(result))

    def test_treats_ml001_as_m1212_alias(self) -> None:
        payload = {
            "should_decompose": True,
            "subqueries": ["M1212的测试条件是什么？", "M1212的预期结果是什么？"],
        }
        result = validate_subqueries("ML001的测试条件和预期结果分别是什么？", payload)
        self.assertEqual(2, len(result))

    def test_rejects_hallucinated_product(self) -> None:
        payload = {
            "should_decompose": True,
            "subqueries": ["MI012的版本是什么？", "W001的版本是什么？"],
        }
        with self.assertRaisesRegex(ValueError, "不存在"):
            validate_subqueries("MI012当前版本和变更记录是什么？", payload)


if __name__ == "__main__":
    unittest.main()
