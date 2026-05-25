/**
 * XLSX (Microsoft Excel) file parser.
 *
 * Uses the SheetJS (`xlsx`) library to extract cell content from .xlsx/.xls
 * files in the browser. Binary format — reads ArrayBuffer.
 *
 * Outputs:
 *   body    — all sheets concatenated as tab-separated text (≤ 100 000 chars)
 *   content — alias for body
 *   sheets  — JSON object mapping sheet name → 2D string array
 *   urls    — JSON array of unique http(s) URLs found in the text
 */

import * as XLSX from "xlsx";
import type { FileParser, FileParseResult } from "./types";

export async function parseXlsx(buffer: ArrayBuffer): Promise<FileParseResult> {
  const workbook = XLSX.read(buffer, { type: "array" });
  const sheets: Record<string, string[][]> = {};
  const textParts: string[] = [];

  for (const sheetName of workbook.SheetNames) {
    const ws = workbook.Sheets[sheetName];
    if (!ws) continue;
    // Convert to 2D array of strings
    const rows: string[][] = XLSX.utils.sheet_to_json(ws, {
      header: 1,
      defval: "",
      raw: false,
    }) as string[][];
    sheets[sheetName] = rows;
    // Build tab-separated text representation
    const text = rows
      .map((row) => row.join("\t"))
      .join("\n");
    if (text.trim()) {
      textParts.push(`[${sheetName}]\n${text}`);
    }
  }

  const body = textParts.join("\n\n").trim().slice(0, 100000);
  const result: FileParseResult = {
    body,
    content: body,
    log_content: body,
    sheets: JSON.stringify(sheets),
  };

  const urls = [
    ...new Set(body.match(/https?:\/\/[^\s<>"'\\]+/g) ?? []),
  ];
  if (urls.length) result.urls = JSON.stringify(urls.slice(0, 50));

  return result;
}

export const xlsxParser: FileParser = {
  name: "Excel 表格",
  binary: true,
  accepts(fileName, mimeType) {
    const lower = fileName.toLowerCase();
    return (
      lower.endsWith(".xlsx") ||
      lower.endsWith(".xls") ||
      lower.endsWith(".xlsm") ||
      mimeType === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" ||
      mimeType === "application/vnd.ms-excel"
    );
  },
  parse() {
    // Binary format — use parseBuffer instead
    return {};
  },
  parseBuffer: parseXlsx,
};
