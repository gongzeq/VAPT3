/**
 * File parser registry for the workflow RunDialog.
 *
 * Adding support for a new file format is a three-step process:
 *   1. Create `@/lib/parsers/<format>.ts` implementing the FileParser interface.
 *   2. Import and append it to the `parsers` array below.
 *   3. Done — RunDialog automatically picks it up via `findParser()`.
 */

import type { FileParser, FileParseResult } from "./types";
import { emlParser } from "./eml";
import { txtParser } from "./txt";
import { docxParser } from "./docx";
import { xlsxParser } from "./xlsx";

/** Ordered list of registered file parsers. First match wins. */
const parsers: FileParser[] = [
  emlParser,
  docxParser,
  xlsxParser,
  txtParser, // TXT last — its .txt/.log/.csv matching is more generic
];

/**
 * Returns the first parser that accepts the given file, or null if none match.
 * RunDialog falls back to "dump raw content into first string input" when null.
 */
export function findParser(
  fileName: string,
  mimeType: string,
): FileParser | null {
  return parsers.find((p) => p.accepts(fileName, mimeType)) ?? null;
}

export type { FileParser, FileParseResult };
export { parsers };
