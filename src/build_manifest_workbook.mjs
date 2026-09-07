import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const projectRoot = path.resolve(process.argv[2]);
const manifestPath = path.join(projectRoot, "data", "corpus_manifest.json");
const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
const documents = manifest.documents;

const outputDir = path.join(projectRoot, "outputs", "corpus-baseline-20260907");
const stagingDir = path.join(projectRoot, "_staging", "20260907_语料基线");
await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(stagingDir, { recursive: true });

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("语料清单");
sheet.showGridLines = false;
sheet.freezePanes.freezeRows(9);
sheet.freezePanes.freezeColumns(4);

sheet.getRange("A2").values = [["团队知识库语料清单"]];
sheet.getRange("A2").format.font = { name: "Arial", size: 14, bold: true, color: "#000000" };
sheet.getRange("A4:B7").values = [
  ["生成时间", manifest.generated_at.slice(0, 19).replace("T", " ")],
  ["有效文档", manifest.usable_document_count],
  ["抽检样本", documents.filter((item) => item.sample_selected).length],
  ["压缩包校验", manifest.crc_check],
];
sheet.getRange("A4:A7").format.font = { name: "Arial", size: 10, bold: true, color: "#1F1F1F" };
sheet.getRange("B4:B7").format.font = { name: "Arial", size: 10, color: "#1F1F1F" };
sheet.getRange("B5:B6").setNumberFormat("#,##0");

const headers = [
  "Source ID", "产品组", "文档类型", "文件名", "格式", "大小 (KB)", "SHA256", "版本 ID",
  "压缩包时间", "原文相对路径", "ACL", "入库状态", "抽检样本", "需格式转换",
];
const rows = documents.map((item) => [
  item.source_id,
  item.product_group,
  item.document_type,
  item.file_name,
  item.extension,
  Math.round(item.size_bytes / 1024),
  item.sha256,
  item.revision_id,
  item.archive_modified_at.replace("T", " "),
  item.raw_relative_path,
  item.acl,
  item.ingest_status,
  item.sample_selected ? "是" : "否",
  item.conversion_required ? "是" : "否",
]);

const startRow = 9;
const endRow = startRow + rows.length;
sheet.getRange(`A${startRow}:N${endRow}`).values = [headers, ...rows];
sheet.getRange(`A${startRow}:N${endRow}`).format.font = { name: "Arial", size: 10, color: "#1F1F1F" };
sheet.getRange(`A${startRow}:N${startRow}`).format = {
  fill: "#1F4E78",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  borders: { preset: "all", style: "thin", color: "#D9D9D9" },
};
sheet.getRange(`A${startRow + 1}:N${endRow}`).format.borders = { preset: "all", style: "thin", color: "#D9D9D9" };
sheet.getRange(`A${startRow + 1}:N${endRow}`).format.verticalAlignment = "center";
sheet.getRange(`F${startRow + 1}:F${endRow}`).setNumberFormat("#,##0");

for (let row = startRow + 2; row <= endRow; row += 2) {
  sheet.getRange(`A${row}:N${row}`).format.fill = "#F3F6FA";
}

const table = sheet.tables.add(`A${startRow}:N${endRow}`, true, "CorpusManifestTable");
table.showFilterButton = true;
table.showBandedRows = false;

const widths = [18, 16, 30, 48, 9, 12, 46, 20, 21, 58, 12, 14, 12, 14];
for (let index = 0; index < widths.length; index += 1) {
  sheet.getRangeByIndexes(0, index, endRow, 1).format.columnWidth = widths[index];
}
sheet.getRange(`D${startRow + 1}:D${endRow}`).format.wrapText = true;
sheet.getRange(`G${startRow + 1}:G${endRow}`).format.wrapText = true;
sheet.getRange(`J${startRow + 1}:J${endRow}`).format.wrapText = true;
sheet.getRange(`A${startRow}:N${endRow}`).format.autofitRows();

workbook.recalculate();
const inspect = await workbook.inspect({
  kind: "table",
  range: `语料清单!A1:N${Math.min(endRow, 16)}`,
  include: "values,formulas",
  tableMaxRows: 16,
  tableMaxCols: 14,
  maxChars: 12000,
});
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});

const preview = await workbook.render({
  sheetName: "语料清单",
  range: `A1:N${Math.min(endRow, 18)}`,
  scale: 1.5,
  format: "png",
});
const previewPath = path.join(stagingDir, "corpus_manifest_preview.png");
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

const xlsxPath = path.join(outputDir, "corpus_manifest.xlsx");
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(xlsxPath);

const csvHeaders = [
  "source_id", "product_group", "document_type", "file_name", "extension", "size_bytes", "sha256",
  "revision_id", "archive_modified_at", "raw_relative_path", "acl", "ingest_status", "sample_selected", "conversion_required",
];
const csvEscape = (value) => {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};
const csvLines = [
  csvHeaders.join(","),
  ...documents.map((item) => csvHeaders.map((header) => csvEscape(item[header])).join(",")),
];
const csvPath = path.join(projectRoot, "data", "corpus_manifest.csv");
await fs.writeFile(csvPath, `\uFEFF${csvLines.join("\r\n")}\r\n`, "utf8");

console.log(JSON.stringify({
  xlsxPath,
  csvPath,
  previewPath,
  inspect: inspect.ndjson,
  errors: errors.ndjson,
}));
