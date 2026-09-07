from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


QUESTIONS = [
    {
        "question_id": "Q001",
        "category": "单文档事实",
        "question": "M1212(ML001)模块的CPU、内存和SATA盘最低或标称配置是什么？",
        "expected_answer": "板载1片四核CPU，主频不低于2.2GHz；CPU外带不小于8GB DDR4；板载128G SATA盘。",
        "expected_behavior": "回答并逐项引用",
        "source_ids": "SRC-e347986ec230",
        "source_files": "M1212(ML001)模块 验收测试程序.md",
        "locator": "简要技术性能，[18]-[20]",
        "evidence_excerpt": "四核CPU≥2.2GHz；DDR4≥8GB；128G SATA盘",
        "user_group": "fde-core",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待人工确认",
        "review_note": "核对三个配置项均被回答，不能遗漏单位。",
    },
    {
        "question_id": "Q002",
        "category": "单文档事实",
        "question": "M1212(ML001)模块提供多少路RS422、千兆电口和千兆光口？",
        "expected_answer": "3路RS422接口、1路电口千兆以太网接口、2路光口千兆以太网接口。",
        "expected_behavior": "回答并逐项引用",
        "source_ids": "SRC-e347986ec230",
        "source_files": "M1212(ML001)模块 验收测试程序.md",
        "locator": "简要技术性能，[23]-[25]",
        "evidence_excerpt": "3路RS422；1路千兆电口；2路千兆光口",
        "user_group": "fde-core",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待人工确认",
        "review_note": "不得把调试接口重复计数。",
    },
    {
        "question_id": "Q003",
        "category": "单文档事实",
        "question": "MI012的掉电数据存储容量和短时断电保持能力分别是什么？",
        "expected_answer": "掉电存储器数据容量不小于32KByte；断电50ms内核心CPU功能不丧失。",
        "expected_behavior": "回答并分别引用两个指标",
        "source_ids": "SRC-cb2234dc9382",
        "source_files": "MI012 验收测试程序.md",
        "locator": "简要技术性能，[37]、[42]",
        "evidence_excerpt": "掉电存储≥32KByte；50ms内核心CPU功能不丧失",
        "user_group": "fde-core",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待人工确认",
        "review_note": "不能把50ms写成掉电存储时长。",
    },
    {
        "question_id": "Q004",
        "category": "单文档事实",
        "question": "MI012验收时的重量和功耗合格条件是什么？",
        "expected_answer": "实际重量不大于850g；在16V、28V、32V输出电压下功耗小于30W，高温下只测试28V。",
        "expected_behavior": "回答并保留电压和高温测试条件",
        "source_ids": "SRC-cb2234dc9382",
        "source_files": "MI012 验收测试程序.md",
        "locator": "重量，[386]；功耗，[389]",
        "evidence_excerpt": "重量≤850g；16V/28V/32V时功耗<30W；高温只测28V",
        "user_group": "fde-core",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待人工确认",
        "review_note": "小于30W不能改写为小于等于30W。",
    },
    {
        "question_id": "Q005",
        "category": "单文档事实",
        "question": "W001鼠标的RS422接口、分辨率、最大追踪速度和最大加速度指标是什么？",
        "expected_answer": "2路异步全双工RS422接口，波特率115200bps；分辨率不小于600cpi；最大追踪速度14 ips @1500fps；最大加速度0.15g @1500fps。",
        "expected_behavior": "回答并逐项引用",
        "source_ids": "SRC-582cd1d296bf",
        "source_files": "W001鼠标 验收测试程序.md",
        "locator": "简要技术性能，[50]、[56]",
        "evidence_excerpt": "2路全双工RS422@115200bps；≥600cpi；14ips；0.15g",
        "user_group": "fde-core",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待人工确认",
        "review_note": "追踪速度和加速度均需保留1500fps条件。",
    },
    {
        "question_id": "Q006",
        "category": "单文档事实",
        "question": "W001鼠标验收测试中的安装尺寸、外形尺寸和重量合格范围是什么？",
        "expected_answer": "安装尺寸为136mm×104.7mm，公差±0.1mm；外形尺寸为146±0.6mm×125±0.6mm×70±0.5mm；单个鼠标重量1.2~1.3kg。",
        "expected_behavior": "回答并逐项引用",
        "source_ids": "SRC-582cd1d296bf",
        "source_files": "W001鼠标 验收测试程序.md",
        "locator": "尺寸，[272]；重量，[277]",
        "evidence_excerpt": "安装136×104.7mm(±0.1)；外形146×125×70mm；重量1.2~1.3kg",
        "user_group": "fde-core",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待人工确认",
        "review_note": "保留三个方向的公差，不依赖结构图。",
    },
    {
        "question_id": "Q007",
        "category": "跨文档比较",
        "question": "按验收合格条件比较M1212、MI012和W001的重量上限，从轻到重如何排列？",
        "expected_answer": "MI012不大于0.85kg，W001上限1.3kg，M1212不大于2.2kg；从轻到重为MI012、W001、M1212。W001同时规定下限1.2kg。",
        "expected_behavior": "合并三份证据并说明W001下限",
        "source_ids": "SRC-e347986ec230;SRC-cb2234dc9382;SRC-582cd1d296bf",
        "source_files": "M1212(ML001)模块 验收测试程序.md;MI012 验收测试程序.md;W001鼠标 验收测试程序.md",
        "locator": "M1212[222]；MI012[386]；W001[277]",
        "evidence_excerpt": "2.2kg；850g；1.2~1.3kg",
        "user_group": "fde-core",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待人工确认",
        "review_note": "先统一单位再排序。",
    },
    {
        "question_id": "Q008",
        "category": "跨文档比较",
        "question": "三种产品的看门狗复位时间要求有何不同？",
        "expected_answer": "M1212停止喂狗约90秒后复位；MI012执行jmWatchDog 1后等待1秒至2.25秒重启；W001执行jmDisFeedDog后1.5秒出现上电启动信息。三者触发条件不同，不能只比较数值。",
        "expected_behavior": "合并三份证据并保留触发条件",
        "source_ids": "SRC-e347986ec230;SRC-cb2234dc9382;SRC-582cd1d296bf",
        "source_files": "M1212(ML001)模块 验收测试程序.md;MI012 验收测试程序.md;W001鼠标 验收测试程序.md",
        "locator": "M1212[197]、[202]；MI012[337]、[348]；W001[246]-[248]",
        "evidence_excerpt": "停止喂狗90s；使能后1~2.25s；禁喂后1.5s",
        "user_group": "fde-core",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待人工确认",
        "review_note": "不可把三个时间写成同一种测试条件。",
    },
    {
        "question_id": "Q009",
        "category": "跨文档比较",
        "question": "M1212、MI012和W001的RS422能力分别如何描述？",
        "expected_answer": "M1212提供3路RS422接口；MI012具备1路RS422双工和1路RS422单向发送；W001具备2路异步全双工RS422，波特率115200bps。",
        "expected_behavior": "合并三份证据，不把路数和方向混为一谈",
        "source_ids": "SRC-e347986ec230;SRC-cb2234dc9382;SRC-582cd1d296bf",
        "source_files": "M1212(ML001)模块 验收测试程序.md;MI012 验收测试程序.md;W001鼠标 验收测试程序.md",
        "locator": "M1212[23]；MI012[36]；W001[50]",
        "evidence_excerpt": "3路；1路双工+1路单发；2路异步全双工@115200bps",
        "user_group": "fde-core",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待人工确认",
        "review_note": "M1212资料未在该段说明三路全部双工。",
    },
    {
        "question_id": "Q010",
        "category": "一致性检查",
        "question": "W001资料中的功耗口径是否一致？",
        "expected_answer": "不完全一致。产品规范的需求段写总功耗不大于7W；产品规范的检验方法和验收测试程序均以1W~2W为合格范围。应标记为口径冲突，不能擅自选一个值。",
        "expected_behavior": "指出冲突并分别引用，不裁决哪个有效",
        "source_ids": "SRC-70ba998f330e;SRC-582cd1d296bf",
        "source_files": "W001鼠标 产品规范.md;W001鼠标 验收测试程序.md",
        "locator": "产品规范[252]、[593]；验收程序[282]",
        "evidence_excerpt": "需求≤7W；检验与验收1~2W",
        "user_group": "fde-core",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待人工确认",
        "review_note": "这是冲突检测题，不要求系统自行裁决。",
    },
    {
        "question_id": "Q011",
        "category": "版本与更新",
        "question": "W001验收测试程序当前封面版本是什么，最近一次变更记录把版本从什么改为什么？",
        "expected_answer": "封面版本为1V1.0.2；最近一次变更记录把版本从V1.0.1改为V1.0.2。",
        "expected_behavior": "回答并引用封面表和更改记录",
        "source_ids": "SRC-582cd1d296bf",
        "source_files": "W001鼠标 验收测试程序.md",
        "locator": "表格1行3；表格7行4",
        "evidence_excerpt": "封面1V1.0.2；V1.0.1→V1.0.2",
        "user_group": "fde-core",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待人工确认",
        "review_note": "日期已脱敏，不应在回答中补造日期。",
    },
    {
        "question_id": "Q012",
        "category": "证据不足拒答",
        "question": "M1212模块的精确厚度是多少毫米？",
        "expected_answer": "现有文字证据无法给出精确厚度。尺寸段只保留“厚度 mm”的空值，并指向外形图；第一版未处理图片语义。",
        "expected_behavior": "明确拒绝猜测，并指出缺失证据",
        "source_ids": "SRC-f3f1e205ac78",
        "source_files": "M1212(ML001)模块 产品规范.md",
        "locator": "尺寸要求，[155]",
        "evidence_excerpt": "厚度字段为空，详细尺寸指向图1",
        "user_group": "fde-core",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待人工确认",
        "review_note": "正确结果是拒答，不可根据常识或图片猜测。",
    },
    {
        "question_id": "Q013",
        "category": "证据不足拒答",
        "question": "MI012模块的具体长、宽、高分别是多少？",
        "expected_answer": "现有文字证据无法给出具体长宽高。产品规范仅写外廓尺寸见图3，验收程序的长宽高字段为空并指向结构尺寸图；第一版未处理图片语义。",
        "expected_behavior": "明确拒绝猜测，并引用两份缺失证据",
        "source_ids": "SRC-6121debe630b;SRC-cb2234dc9382",
        "source_files": "MI012 产品规范.md;MI012 验收测试程序.md",
        "locator": "产品规范[322]-[324]；验收程序[378]-[383]",
        "evidence_excerpt": "外廓尺寸见图3；长宽高字段为空并指向图45",
        "user_group": "fde-core",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待人工确认",
        "review_note": "正确结果是拒答，不读取图片。",
    },
    {
        "question_id": "Q014",
        "category": "权限隔离",
        "question": "MI012验收时的功耗合格条件是什么？",
        "expected_answer": "不返回文档内容；说明当前用户无权访问所需知识项。",
        "expected_behavior": "检索前拒绝，不泄露答案或文档片段",
        "source_ids": "SRC-cb2234dc9382",
        "source_files": "MI012 验收测试程序.md",
        "locator": "功耗，[389]",
        "evidence_excerpt": "ACL测试夹具，不向无权用户展示原文",
        "user_group": "external-partner",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待实现验证",
        "review_note": "ACL为PoC模拟值，需在检索器实现后执行。",
    },
    {
        "question_id": "Q015",
        "category": "权限隔离",
        "question": "MI012验收时的功耗合格条件是什么？",
        "expected_answer": "在16V、28V、32V输出电压下功耗小于30W，高温下只测试28V。",
        "expected_behavior": "允许检索、回答并引用",
        "source_ids": "SRC-cb2234dc9382",
        "source_files": "MI012 验收测试程序.md",
        "locator": "功耗，[389]",
        "evidence_excerpt": "16V/28V/32V时功耗<30W；高温只测28V",
        "user_group": "fde-core",
        "required_acl": "fde-core",
        "requires_image": False,
        "review_status": "待实现验证",
        "review_note": "与Q014组成同题不同权限对照。",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    args = parser.parse_args()

    root = args.project_root.resolve()
    eval_root = root / "eval"
    eval_root.mkdir(parents=True, exist_ok=True)

    if len(QUESTIONS) != 15:
        raise RuntimeError(f"种子评测题应为 15 道，实际为 {len(QUESTIONS)}")
    if any(item["requires_image"] for item in QUESTIONS):
        raise RuntimeError("第一版评测题不得依赖图片语义")
    if len({item["question_id"] for item in QUESTIONS}) != len(QUESTIONS):
        raise RuntimeError("question_id 必须唯一")

    json_path = eval_root / "golden_questions.json"
    json_path.write_text(json.dumps(QUESTIONS, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = eval_root / "golden_questions.csv"
    headers = list(QUESTIONS[0].keys())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(QUESTIONS)

    summary = {
        "question_count": len(QUESTIONS),
        "category_counts": {
            category: sum(1 for item in QUESTIONS if item["category"] == category)
            for category in sorted({item["category"] for item in QUESTIONS})
        },
        "image_dependent_count": sum(1 for item in QUESTIONS if item["requires_image"]),
        "permission_pair": ["Q014", "Q015"],
        "status": "内容已按样本文字证据生成，待检索链路实现后执行",
    }
    summary_path = root / "reports" / "eval_seed_check_data.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "json": str(json_path),
        "csv": str(csv_path),
        **summary,
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
