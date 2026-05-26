/**
 * Plain text file parser.
 *
 * Accepts .txt files (and common plain-text MIME types).
 * Outputs:
 *   body    — the full file content (≤ 100 000 chars)
 *   urls    — JSON array of unique http(s) URLs found in the text
 *   content — alias for body (some workflows may use this name)
 */

import type { FileParser, FileParseResult } from "./types";

export function parseTxt(raw: string): FileParseResult {
  const body = raw.trim().slice(0, 100000);
  const result: FileParseResult = {
    body,
    content: body,
    log_content: body,
  };

  // Extract URLs
  const urls = [
    ...new Set(body.match(/https?:\/\/[^\s<>"'\\]+/g) ?? []),
  ];
  if (urls.length) result.urls = JSON.stringify(urls.slice(0, 50));

  return result;
}

export const txtParser: FileParser = {
  name: "纯文本",
  accepts(fileName, mimeType) {
    const lower = fileName.toLowerCase();
    return (
      lower.endsWith(".txt") ||
      lower.endsWith(".log") ||
      lower.endsWith(".csv") ||
      mimeType === "text/plain" ||
      mimeType === "text/csv"
    );
  },
  parse: parseTxt,
};
