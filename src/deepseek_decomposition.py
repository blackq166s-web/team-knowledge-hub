from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx


PRODUCT_RE = re.compile(r"(?i)(?:M1212|ML001|MI012|W001)")
VERSION_RE = re.compile(r"(?i)\bV?\d+(?:\.\d+){1,3}\b")
COMPLEX_MARKERS = (
    "比较",
    "对比",
    "差异",
    "不同",
    "各自",
    "分别",
    "三种",
    "两种",
    "同时",
    "以及",
    "并且",
    "最近一次",
)
KNOWN_PRODUCTS = ("M1212", "MI012", "W001")


@dataclass(frozen=True)
class Decomposition:
    original_query: str
    should_decompose: bool
    subqueries: list[str]
    reason: str
    provider: str
    model: str
    status: str
    latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def should_decompose_locally(query: str) -> bool:
    products = {item.upper() for item in PRODUCT_RE.findall(query)}
    if len(products) >= 2:
        return True
    if any(marker in query for marker in COMPLEX_MARKERS):
        return True
    return bool(re.search(r"(?:当前|现行).{0,30}(?:变更|修改|改为)", query))


def augment_retrieval_query(query: str) -> str:
    """Add transparent document-language hints without adding answer values."""
    hints: list[str] = []
    normalized = query.lower()
    if "看门狗" in query and any(word in query for word in ("时间", "复位", "要求")):
        products = list(dict.fromkeys(PRODUCT_RE.findall(query)))
        return " ".join([*products, "看门狗", "测试方法", "合格判据", "复位", "时间"])
    if all(word in query for word in ("长", "宽", "高")):
        products = list(dict.fromkeys(PRODUCT_RE.findall(query)))
        return " ".join([*products, "具体", "长", "宽", "高", "外廓尺寸", "见图", "结构尺寸图"])
    if "封面" in query and "版本" in query:
        hints.extend(["封面信息", "档号", "保管期限", "版 本 号"])
    if any(word in query for word in ("变更", "更改记录")) and "版本" in query:
        hints.extend(["更改记录", "变更内容", "版本号"])
    if "rs422" in normalized and any(word in query for word in ("能力", "描述", "分别")):
        hints.append("简要技术性能")
    return query + (" " + " ".join(hints) if hints else "")


def inherit_retrieval_scope(original_query: str, subquery: str) -> str:
    """Restore explicit source/scope constraints that decomposition may omit."""
    inherited: list[str] = []
    for phrase in ("验收合格条件", "验收测试程序", "产品规范"):
        if phrase in original_query and phrase not in subquery:
            inherited.append(phrase)
    scoped = subquery + (" " + " ".join(inherited) if inherited else "")
    return augment_retrieval_query(scoped)


def _tokens(pattern: re.Pattern[str], text: str) -> set[str]:
    return {item.upper() for item in pattern.findall(text)}


def _products(text: str) -> set[str]:
    return {
        "M1212" if item.upper() in {"M1212", "ML001"} else item.upper()
        for item in PRODUCT_RE.findall(text)
    }


def validate_subqueries(original_query: str, payload: Any, max_subqueries: int = 5) -> list[str]:
    if not isinstance(payload, dict):
        raise ValueError("DeepSeek 返回值不是 JSON 对象")
    if payload.get("should_decompose") is not True:
        return []
    raw = payload.get("subqueries")
    if not isinstance(raw, list):
        raise ValueError("subqueries 不是数组")
    subqueries: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("subqueries 只能包含字符串")
        normalized = " ".join(item.strip().split())
        if not normalized or len(normalized) > 200:
            raise ValueError("子问题为空或超过 200 字")
        if normalized not in subqueries and normalized != original_query.strip():
            subqueries.append(normalized)
    if not 2 <= len(subqueries) <= max_subqueries:
        raise ValueError(f"有效子问题数量必须为 2 到 {max_subqueries}")

    combined = " ".join(subqueries)
    original_products = _products(original_query)
    generated_products = _products(combined)
    if not original_products.issubset(generated_products):
        raise ValueError("子问题遗漏了原问题中的产品标识")
    # A generic comparison such as "三种产品" may legitimately expand to the
    # allow-listed products supplied to the model. When the user names a product,
    # however, the model must not introduce another one.
    allowed_products = original_products or set(KNOWN_PRODUCTS)
    if not generated_products.issubset(allowed_products):
        raise ValueError("子问题增加了原问题中不存在的产品标识")
    original_versions = _tokens(VERSION_RE, original_query)
    if not original_versions.issubset(_tokens(VERSION_RE, combined)):
        raise ValueError("子问题遗漏了原问题中的版本号")
    return subqueries


class DeepSeekDecomposer:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 60.0,
        max_subqueries: int = 5,
    ) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
        self.timeout_seconds = timeout_seconds
        self.max_subqueries = max_subqueries

    def _fallback(self, query: str, status: str, reason: str, latency_ms: float = 0.0) -> Decomposition:
        return Decomposition(
            original_query=query,
            should_decompose=False,
            subqueries=[],
            reason=reason,
            provider="deepseek",
            model=self.model,
            status=status,
            latency_ms=round(latency_ms, 2),
        )

    def decompose(self, query: str) -> Decomposition:
        if not should_decompose_locally(query):
            return self._fallback(query, "not_needed", "本地规则判断为简单问题")
        if not self.api_key:
            return self._fallback(query, "missing_api_key", "未配置 DEEPSEEK_API_KEY，已回退原问题")

        system_prompt = (
            "你是企业知识库的检索问题拆分器。只拆分包含比较、多个对象或多个独立信息需求的问题。"
            "不得回答问题，不得补充原问题没有的事实、产品、数字或版本。每个子问题必须能独立用于检索，"
            f"最多 {self.max_subqueries} 个。必须输出 json，格式示例："
            '{"should_decompose":true,"reason":"多个独立信息需求","subqueries":["子问题1","子问题2"]}。'
            "简单问题输出 should_decompose=false 和空 subqueries。"
        )
        user_prompt = (
            "允许识别的三种产品：M1212（别名 ML001）、MI012、W001\n"
            f"待判断问题：{query}\n"
            "请只返回 json。"
        )
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": 600,
            "stream": False,
        }
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
            response.raise_for_status()
            envelope = response.json()
            content = envelope["choices"][0]["message"]["content"]
            if not content:
                raise ValueError("DeepSeek 返回了空内容")
            payload = json.loads(content)
            subqueries = validate_subqueries(query, payload, self.max_subqueries)
            latency_ms = (time.perf_counter() - started) * 1000
            return Decomposition(
                original_query=query,
                should_decompose=bool(subqueries),
                subqueries=subqueries,
                reason=str(payload.get("reason", ""))[:200],
                provider="deepseek",
                model=self.model,
                status="success",
                latency_ms=round(latency_ms, 2),
            )
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            return self._fallback(query, "fallback", f"{type(exc).__name__}: {exc}", latency_ms)
