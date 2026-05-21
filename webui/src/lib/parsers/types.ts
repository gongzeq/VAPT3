/**
 * File parser interface for workflow RunDialog.
 *
 * Each parser receives the raw file text and returns a flat map of
 * { fieldName → stringValue } pairs. RunDialog then intersects the returned
 * keys with the workflow's declared input names to fill only the matching
 * fields — so parsers never need to know about specific workflow schemas.
 */
export type FileParseResult = Record<string, string>;

export interface FileParser {
  /** Human-readable name, e.g. "EML email" */
  name: string;
  /**
   * Whether this parser requires binary input (ArrayBuffer).
   * Default is false (text-based). When true, `parseBuffer` is used.
   */
  binary?: boolean;
  /**
   * Returns true when this parser should handle the given file.
   * Both the file name and the browser-reported MIME type are provided.
   */
  accepts(fileName: string, mimeType: string): boolean;
  /**
   * Parse raw text content and return a flat map of field-name → value.
   * Keys should match common workflow input names (e.g. "sender", "subject").
   * RunDialog will only apply keys that exist in the current workflow's inputs.
   */
  parse(raw: string): FileParseResult;
  /**
   * Parse binary content (ArrayBuffer) for binary formats (DOCX, XLSX, etc.).
   * Only called when `binary: true`.
   */
  parseBuffer?(buffer: ArrayBuffer): Promise<FileParseResult>;
}
