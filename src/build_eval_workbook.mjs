import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const projectRoot = path.resolve(process.argv[2]);
const questionsPath = path.join(projectRoot, "eval", "golden_questions.json");
const questions = JSON.parse(await fs.readFile(questionsPath, "utf8"));

if (questions.length !== 15) {
  throw new Error(`种子评测题应为 15 道，实际为 ${questions.length}`);
}

const outputDir = path.join(projectRoot, "outputs", "eval-seed-20260907");
const stagingDir = path.join(projectRoot, "_staging", "20260907_评测集");
const reportPath = path.join(projectRoot, "reports", "eval_workbook_check.json");
await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(stagingDir, { recursive: true });

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("种子评测集");
sheet.showGridLines = false;
sheet.tabColor = "#1F4E78";
sheet.freezePanes.freezeRows(8);
sheet.freezePanes.freezeColumns(3);

sheet.getRange("A2").values = [["团队知识库种子评测集"]];
sheet.getRange("A2").format.font = { name: "Arial", size: 14, bold: true, color: "#1F1F1F" };
sheet.getRange("A3:N3").format.fill = "#1F4E78";
sheet.getRange("A3:N3").format.rowHeight = 3;

const imageIndependentCount = questions.filter((item) => !item.requires_image).length;
const permissionCount = questions.filter((item) => item.category === "权限隔离").length;
const confirmedPendingCount = questions.filter((item) => item.review_status === "待人工确认").length;
sheet.getRange("A4:H5").values = [
  ["题目总数", questions.length, "不依赖图片", imageIndependentCount, "待人工确认", confirmedPendingCount, "权限对照题", permissionCount],
  ["当前用途", "检索链路开发前的种子基线", "执行状态", "尚未运行RAG评测", "图片语义", "未启用", "ACL", "PoC模拟值"],
];
sheet.getRange("A4:H5").format.font = { name: "Arial", size: 10, color: "#1F1F1F" };
sheet.getRange("A4:H5").format.verticalAlignment = "center";
sheet.getRange("A4:H5").format.borders = { preset: "outside", style: "thin", color: "#B4C7E7" };
for (const cell of ["A4", "C4", "E4", "G4", "A5", "C5", "E5", "G5"]) {
  sheet.getRange(cell).format.font = { name: "Arial", size: 10, bold: true, color: "#1F1F1F" };
  sheet.getRange(cell).format.fill = "#D9EAF7";
}
sheet.getRange("B4:D4").format.horizontalAlignment = "center";
sheet.getRange("F4:H4").format.horizontalAlignment = "center";
sheet.getRange("A6").values = [["范围：第一版只使用文字、表格和已有图题；不读取图片语义。证据不足时应拒答。"]];
sheet.getRange("A6:N6").format.font = { name: "Arial", size: 10, italic: true, color: "#595959" };

const headers = [
  "题号", "类别", "问题", "期望答案", "期望行为", "证据定位", "来源ID", "来源文件",
  "证据摘要", "用户组", "所需ACL", "依赖图片", "复核状态", "复核备注",
];
const rows = questions.map((item) => [
  item.question_id,
  item.category,
  item.question,
  item.expected_answer,
  item.expected_behavior,
  item.locator,
  item.source_ids,
  item.source_files,
  item.evidence_excerpt,
  item.user_group,
  item.required_acl,
  item.requires_image ? "是" : "否",
  item.review_status,
  item.review_note,
]);

const headerRow = 8;
const lastRow = headerRow + rows.length;
sheet.getRange(`A${headerRow}:N${lastRow}`).values = [headers, ...rows];
sheet.getRange(`A${headerRow}:N${lastRow}`).format.font = { name: "Arial", size: 10, color: "#1F1F1F" };
sheet.getRange(`A${headerRow}:N${headerRow}`).format = {
  fill: "#1F4E78",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "all", style: "thin", color: "#FFFFFF" },
};
sheet.getRange(`A${headerRow + 1}:N${lastRow}`).format.verticalAlignment = "top";
sheet.getRange(`A${headerRow + 1}:N${lastRow}`).format.borders = {
  insideHorizontal: { style: "thin", color: "#D9E2F3" },
  bottom: { style: "thin", color: "#A6A6A6" },
};
sheet.getRange(`A${headerRow + 1}:N${lastRow}`).format.wrapText = true;
sheet.getRange(`A${headerRow}:N${headerRow}`).format.rowHeight = 30;
sheet.getRange(`A${headerRow + 1}:N${lastRow}`).format.rowHeight = 78;

for (let row = headerRow + 2; row <= lastRow; row += 2) {
  sheet.getRange(`A${row}:N${row}`).format.fill = "#F7F9FC";
}

const table = sheet.tables.add(`A${headerRow}:N${lastRow}`, true, "EvalSeedTable");
table.showFilterButton = true;
table.showBandedRows = false;

const columnWidths = [10, 15, 42, 62, 30, 28, 23, 40, 38, 18, 16, 12, 16, 32];
for (let index = 0; index < columnWidths.length; index += 1) {
  sheet.getRangeByIndexes(0, index, lastRow, 1).format.columnWidth = columnWidths[index];
}
sheet.getRange(`A${headerRow + 1}:B${lastRow}`).format.horizontalAlignment = "center";
sheet.getRange(`J${headerRow + 1}:M${lastRow}`).format.horizontalAlignment = "center";
sheet.getRange(`M${headerRow + 1}:M${lastRow}`).dataValidation = {
  rule: { type: "list", values: ["待人工确认", "已确认", "需修改", "待实现验证"] },
};
sheet.getRange(`M${headerRow + 1}:M${lastRow}`).conditionalFormats.add("containsText", {
  text: "待实现验证",
  format: { fill: "#FFF2CC", font: { bold: true, color: "#7F6000" } },
});
sheet.getRange(`M${headerRow + 1}:M${lastRow}`).conditionalFormats.add("containsText", {
  text: "需修改",
  format: { fill: "#FCE4D6", font: { bold: true, color: "#C00000" } },
});

workbook.recalculate();
const inspect = await workbook.inspect({
  kind: "table",
  range: `种子评测集!A1:N${Math.min(lastRow, 13)}`,
  include: "values,formulas",
  tableMaxRows: 13,
  tableMaxCols: 14,
  maxChars: 18000,
});
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});

const preview = await workbook.render({
  sheetName: "种子评测集",
  range: `A1:N${lastRow}`,
  scale: 1,
  format: "png",
});
const previewPath = path.join(stagingDir, "golden_questions_preview.png");
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

const xlsxPath = path.join(outputDir, "golden_questions.xlsx");
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(xlsxPath);

const exported = await SpreadsheetFile.importXlsx(await FileBlob.load(xlsxPath));
const savedInspect = await exported.inspect({
  kind: "sheet,table",
  maxChars: 5000,
  tableMaxRows: 3,
  tableMaxCols: 5,
});

const check = {
  xlsx_path: xlsxPath,
  preview_path: previewPath,
  question_count: questions.length,
  image_dependent_count: questions.length - imageIndependentCount,
  inspect: inspect.ndjson,
  formula_errors: errors.ndjson,
  saved_inspect: savedInspect.ndjson,
};
await fs.writeFile(reportPath, JSON.stringify(check, null, 2), "utf8");
console.log(JSON.stringify(check));
