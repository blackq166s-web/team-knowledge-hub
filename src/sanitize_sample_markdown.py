from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


PROFILE_VERSION = "kb-v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def apply_rule(text: str, pattern: str, replacement: str, flags: int = 0) -> tuple[str, int]:
    return re.subn(pattern, replacement, text, flags=flags)


def sanitize_text(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}

    for name, source in (
        ("company_name_changsha_electronics", "长沙电子股份有限公司"),
        ("company_name_changsha_hybrid", "长沙混动电子股份有限公司"),
    ):
        text, count = apply_rule(text, re.escape(source), "[单位名称已脱敏]")
        counts[name] = count

    text, counts["signature_rows"] = apply_rule(
        text,
        r"^(- 行 \d+: (?:编\s*写|编写|校\s*对|校对|审\s*核|审核|会\s*签|会签|标\s*审|标审|批\s*准|批准|军代表|专\s*家|专家)).*$",
        r"\1 | [签署信息已脱敏]",
        flags=re.MULTILINE,
    )
    text, counts["signature_placeholders"] = apply_rule(
        text,
        r"(?:<\*\*[^>]*(?:签字|签名)[^>]*\*\*>)+",
        "[签署信息已脱敏]",
    )

    text, counts["labeled_document_id_colon"] = apply_rule(
        text,
        r"(^\s*(?:\[\d+\]\s*|- 行 \d+:\s*)?(?:编\s*号|文档编号|文件编号|代号)\s*[:：]\s*|[，,]\s*代号\s*[:：]\s*)[^\s，。；;|]+",
        r"\1[文档编号已脱敏]",
        flags=re.MULTILINE,
    )
    text, counts["labeled_document_id_table"] = apply_rule(
        text,
        r"^(- 行 \d+:\s*(?:编\s*号|文档编号|文件编号|代号)\s*\|\s*)[^|\r\n]+",
        r"\1[文档编号已脱敏]",
        flags=re.MULTILINE,
    )
    text, counts["cover_internal_code"] = apply_rule(
        text,
        r"^(- 行 \d+: )A\d{2}\s*$",
        r"\1[内部代码已脱敏]",
        flags=re.MULTILINE,
    )

    text, counts["account"] = apply_rule(
        text,
        r"((?:账号|用户名)\s*为?\s*)[“\"]?[^”\"\s，。；;]+[”\"]?",
        r"\1[账号已脱敏]",
    )
    text, counts["password"] = apply_rule(
        text,
        r"(密码\s*为?\s*)[“\"]?[^”\"\s，。；;]+[”\"]?",
        r"\1[密码已脱敏]",
    )
    text, counts["account_token"] = apply_rule(
        text,
        r"(?i)\bjingjia\b",
        "[账号已脱敏]",
    )
    text, counts["document_number_pattern"] = apply_rule(
        text,
        r"(?<![A-Za-z0-9])(?:ADYU2\.\d{3}\.\d{3,4}[A-Z]{2}|0101\.0101(?:JT|CX)|XQ-\d{11}|43\.\d{6})(?![A-Za-z0-9])",
        "[文档编号已脱敏]",
    )

    date_patterns = (
        r"(?<![A-Za-z0-9])20\d{2}[./]\d{1,2}[./]\d{1,2}(?![A-Za-z0-9])",
        r"(?<![A-Za-z0-9])20\d{2}-\d{1,2}-\d{1,2}(?![A-Za-z0-9])",
        r"(?<![A-Za-z0-9])20\d{2}年\d{1,2}月\d{1,2}日(?![A-Za-z0-9])",
        r"(?<![A-Za-z0-9])20\d{6}(?![A-Za-z0-9])",
    )
    counts["calendar_dates"] = 0
    for pattern in date_patterns:
        text, count = apply_rule(text, pattern, "[日期已脱敏]")
        counts["calendar_dates"] += count

    return text, counts


def risk_scan(text: str) -> dict[str, list[str]]:
    patterns = {
        "company_names": r"[\u4e00-\u9fff]{2,24}(?:股份有限公司|有限责任公司|有限公司)",
        "calendar_dates": r"(?<![A-Za-z0-9])(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|20\d{2}年\d{1,2}月\d{1,2}日|20\d{6})(?![A-Za-z0-9])",
        "labeled_document_ids_line": r"(?m)^\s*(?:\[\d+\]\s*|- 行 \d+:\s*)?(?:编\s*号|文档编号|文件编号|代号)\s*[:：]\s*(?!\[文档编号已脱敏\])[^\s|，。；;]+",
        "labeled_document_ids_inline": r"[，,]\s*代号\s*[:：]\s*(?!\[文档编号已脱敏\])[^\s|，。；;]+",
        "labeled_document_ids_table": r"(?m)^- 行 \d+:\s*(?:编\s*号|文档编号|文件编号|代号)\s*\|\s*(?!\[文档编号已脱敏\])[^|\r\n]+",
        "plain_account_tokens": r"(?i)\bjingjia\b",
        "document_number_patterns": r"(?<![A-Za-z0-9])(?:ADYU2\.\d{3}\.\d{3,4}[A-Z]{2}|0101\.0101(?:JT|CX)|XQ-\d{11}|43\.\d{6})(?![A-Za-z0-9])",
    }
    findings: dict[str, list[str]] = {}
    for name, pattern in patterns.items():
        values = sorted(set(re.findall(pattern, text)))
        if name.startswith("labeled_document_ids"):
            values = [value for value in values if "[文档编号已脱敏]" not in value]
        findings[name] = values[:20]
    credential_values: list[str] = []
    for match in re.finditer(
        r"(?:账号|用户名|密码)\s*为\s*[“\"]?([^”\"\s，。；;]+)[”\"]?",
        text,
    ):
        value = match.group(1)
        if value not in {"[账号已脱敏]", "[密码已脱敏]"}:
            credential_values.append(value)
    findings["plain_credentials"] = sorted(set(credential_values))[:20]
    return findings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    args = parser.parse_args()

    root = args.project_root.resolve()
    sample_root = root / "data" / "processed" / "samples"
    output_root = root / "data" / "processed" / "sanitized"
    output_root.mkdir(parents=True, exist_ok=True)

    parse_results = json.loads((root / "reports" / "parse_check_data.json").read_text(encoding="utf-8"))
    metadata_by_name = {
        Path(item["processed_relative_path"]).name: item for item in parse_results
    }
    results: list[dict] = []

    for source_path in sorted(sample_root.glob("*.md"), key=lambda item: item.name):
        item = metadata_by_name[source_path.name]
        source_text = source_path.read_text(encoding="utf-8")
        sanitized_body, replacement_counts = sanitize_text(source_text)
        header = "\n".join(
            [
                "---",
                f"source_id: {item['source_id']}",
                f"product_group: {item['product_group']}",
                f"document_type: {item['document_type']}",
                f"sanitization_profile: {PROFILE_VERSION}",
                "content_scope: text, tables, captions",
                "image_semantics: excluded",
                "---",
                "",
            ]
        )
        output_text = header + sanitized_body
        output_path = output_root / source_path.name
        output_path.write_text(output_text, encoding="utf-8")
        findings = risk_scan(output_text)
        results.append(
            {
                "source_id": item["source_id"],
                "product_group": item["product_group"],
                "document_type": item["document_type"],
                "source_relative_path": source_path.relative_to(root).as_posix(),
                "output_relative_path": output_path.relative_to(root).as_posix(),
                "source_sha256": sha256(source_path),
                "output_sha256": sha256(output_path),
                "replacement_counts": replacement_counts,
                "replacement_total": sum(replacement_counts.values()),
                "risk_findings": findings,
                "risk_finding_total": sum(len(values) for values in findings.values()),
                "image_semantics": "excluded",
            }
        )

    if len(results) != 6:
        raise RuntimeError(f"脱敏样本数量应为 6，实际为 {len(results)}")

    report = {
        "profile_version": PROFILE_VERSION,
        "input_directory": "data/processed/samples",
        "output_directory": "data/processed/sanitized",
        "sample_count": len(results),
        "all_risk_scans_clear": all(item["risk_finding_total"] == 0 for item in results),
        "documents": results,
    }
    report_path = root / "reports" / "sanitization_check_data.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(report_path),
        "sample_count": len(results),
        "replacement_total": sum(item["replacement_total"] for item in results),
        "risk_finding_total": sum(item["risk_finding_total"] for item in results),
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
