/**
 * DOCX (Microsoft Word) file parser.
 *
 * Uses the `mammoth` library to extract plain text from .docx files
 * in the browser. Binary format — reads ArrayBuffer.
 *
 * Outputs:
 *   body    — extracted plain text content (≤ 10 000 chars)
 *   content — alias for body
 *   urls    — JSON array of unique http(s) URLs found in the text
 */

import mammoth from "mammoth";
import type { FileParser, FileParseResult } from "./types";

export async function parseDocx(buffer: ArrayBuffer): Promise<FileParseResult> {
  const { value: text } = await mammoth.extractRawText({ arrayBuffer: buffer });
  const body = text.trim().slice(0, 10000);
  const result: FileParseResult = {
    body,
    content: body,
  };

  const urls = [
    ...new Set(body.match(/https?:\/\/[^\s<>"'\\]+/g) ?? []),
  ];
  if (urls.length) result.urls = JSON.stringify(urls.slice(0, 50));

  return result;
}

export const docxParser: FileParser = {
  name: "Word 文档",
  binary: true,
  accepts(fileName, mimeType) {
    const lower = fileName.toLowerCase();
    return (
      lower.endsWith(".docx") ||
      lower.endsWith(".doc") ||
      mimeType === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
      mimeType === "application/msword"
    );
  },
  parse() {
    // Binary format — use parseBuffer instead
    return {};
  },
  parseBuffer: parseDocx,
};
