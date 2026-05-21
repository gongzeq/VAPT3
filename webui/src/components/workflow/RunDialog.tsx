import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Play, Upload } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { WORKFLOW_FIELD_CLASS } from "@/components/workflow/InputsEditor";
import type { Workflow, WorkflowInput } from "@/lib/workflow-client";
import { findParser } from "@/lib/parsers";

/**
 * Detect charset from raw email headers and decode accordingly.
 * Scans the first 4KB of the file for a `charset=XXX` declaration.
 * Falls back to UTF-8 if charset is not detected or decoding fails.
 */
function decodeWithCharsetDetection(buf: ArrayBuffer): string {
  // Peek at first 4KB as ASCII to find charset= in headers
  const peek = new TextDecoder("ascii", { fatal: false }).decode(
    buf.slice(0, Math.min(buf.byteLength, 4096)),
  );
  // Match charset in Content-Type headers (e.g., charset=GBK, charset="gb2312")
  const m = peek.match(/charset=["']?([^"';\s\r\n]+)/i);
  const detected = m?.[1]?.toLowerCase() || "";

  // Common CJK charset aliases
  const charsetMap: Record<string, string> = {
    gb2312: "gbk",
    gb18030: "gb18030",
    gbk: "gbk",
    big5: "big5",
    "euc-jp": "euc-jp",
    "shift_jis": "shift_jis",
    "iso-2022-jp": "iso-2022-jp",
    "euc-kr": "euc-kr",
  };

  const encoding = charsetMap[detected] || detected || "utf-8";
  try {
    return new TextDecoder(encoding, { fatal: false }).decode(buf);
  } catch {
    // If the detected encoding is not supported, fall back to UTF-8
    return new TextDecoder("utf-8", { fatal: false }).decode(buf);
  }
}

export interface RunDialogProps {
  workflow: Workflow | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (inputs: Record<string, unknown>) => Promise<void>;
}

/** Manual-run dialog. Presents the workflow's declared inputs with
 * bare-bones text controls (no per-type JSON Schema form — a simple
 * ``${type}``→cast happens on submit). */
export function RunDialog({
  workflow,
  open,
  onOpenChange,
  onSubmit,
}: RunDialogProps) {
  const { t } = useTranslation();
  const [values, setValues] = useState<Record<string, string>>({});
  const [uploadedFileName, setUploadedFileName] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const seed: Record<string, string> = {};
    for (const input of workflow?.inputs ?? []) {
      if (input.default !== undefined && input.default !== null) {
        seed[input.name] = String(input.default);
      }
    }
    setValues(seed);
    setUploadedFileName("");
    setError(null);
  }, [open, workflow]);

  function handleGlobalUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadedFileName(file.name);

    const parser = findParser(file.name, file.type);

    // Binary parsers (DOCX, XLSX) need ArrayBuffer
    if (parser?.binary && parser.parseBuffer) {
      const reader = new FileReader();
      reader.onload = async () => {
        try {
          const parsed = await parser.parseBuffer!(reader.result as ArrayBuffer);
          applyParsed(parsed, file.name);
        } catch {
          // If binary parsing fails, fallback to nothing
          setError(`无法解析文件: ${file.name}`);
        }
      };
      reader.readAsArrayBuffer(file);
      return;
    }

    // Text-based parsers (EML, TXT, etc.)
    // Read as ArrayBuffer first to detect charset from headers
    const reader = new FileReader();
    reader.onload = () => {
      const buf = reader.result as ArrayBuffer;
      const text = decodeWithCharsetDetection(buf);
      if (parser && workflow?.inputs && workflow.inputs.length > 0) {
        const parsed = parser.parse(text);
        if (applyParsed(parsed, file.name)) return;
      }
      // Fallback: fill first file/string input with raw content
      const target = workflow?.inputs.find(
        (i) => i.type === "file" || i.type === "string",
      );
      if (target) {
        setValues((prev) => ({ ...prev, [target.name]: text }));
      }
    };
    reader.readAsArrayBuffer(file);
  }

  /** Apply parsed fields to form values. Returns true if any fields matched. */
  function applyParsed(parsed: Record<string, string>, _fileName: string): boolean {
    if (!workflow?.inputs || workflow.inputs.length === 0) return false;
    const patch: Record<string, string> = {};
    for (const input of workflow.inputs) {
      if (parsed[input.name] !== undefined) {
        patch[input.name] = parsed[input.name];
      }
    }
    if (Object.keys(patch).length > 0) {
      setValues((prev) => ({ ...prev, ...patch }));
      return true;
    }
    // If no field names matched but parser produced content, try body/content
    const fallbackContent = parsed.body || parsed.content || "";
    if (fallbackContent) {
      const target = workflow.inputs.find(
        (i) => i.type === "file" || i.type === "string",
      );
      if (target) {
        setValues((prev) => ({ ...prev, [target.name]: fallbackContent }));
        return true;
      }
    }
    return false;
  }

  async function submit() {
    if (!workflow) return;
    setError(null);
    try {
      await onSubmit(materialize(workflow.inputs, values));
      // handleRun closes the dialog, bumps refreshKey, and switches tab.
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("workflow.runDialog.title")}</DialogTitle>
          <DialogDescription>
            {workflow && workflow.inputs.length === 0
              ? t("workflow.runDialog.noInputs")
              : t("workflow.runDialog.description")}
          </DialogDescription>
        </DialogHeader>

        {/* Global file upload */}
        <div className="flex items-center gap-3 rounded-xl border border-dashed border-border/40 bg-muted/10 p-3">
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border/40 bg-muted/30 px-3 py-2 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground">
            <Upload className="h-3.5 w-3.5" />
            {uploadedFileName || "上传文件"}
            <input
              type="file"
              className="hidden"
              onChange={handleGlobalUpload}
            />
          </label>
          {uploadedFileName && (
            <span className="text-[10px] text-emerald-400">✓ 已加载 {uploadedFileName}</span>
          )}
        </div>

        {workflow && workflow.inputs.length > 0 && (
          <div className="space-y-3 py-2">
            {workflow.inputs.map((input) => (
              <label key={input.name} className="flex flex-col gap-1 text-xs">
                <span className="text-muted-foreground">
                  {input.label || input.name}
                  {input.required && (
                    <span className="ml-1 text-rose-400">*</span>
                  )}
                  {input.description && (
                    <span className="ml-1 opacity-60">— {input.description}</span>
                  )}
                </span>
                {input.type === "enum" && input.enumValues ? (
                  <select
                    value={values[input.name] ?? ""}
                    onChange={(e) =>
                      setValues({ ...values, [input.name]: e.target.value })
                    }
                    className={WORKFLOW_FIELD_CLASS}
                  >
                    <option value="">—</option>
                    {input.enumValues.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    value={values[input.name] ?? ""}
                    onChange={(e) =>
                      setValues({ ...values, [input.name]: e.target.value })
                    }
                    className={WORKFLOW_FIELD_CLASS}
                    type={input.type === "int" ? "number" : "text"}
                    placeholder={
                      uploadedFileName && workflow?.inputs.findIndex(
                        (i) => i.type === "file" || i.type === "string"
                      ) === workflow?.inputs.indexOf(input)
                        ? `已加载: ${uploadedFileName}`
                        : undefined
                    }
                  />
                )}
              </label>
            ))}
          </div>
        )}
        {error && (
          <p className="text-xs text-rose-300">
            {t("workflow.error.run")}: {error}
          </p>
        )}
        <DialogFooter>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="rounded-xl border border-border/40 bg-muted/30 px-4 py-2 text-sm text-muted-foreground transition-colors hover:border-primary/40"
          >
            {t("workflow.runDialog.cancel")}
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={false}
            className="gradient-primary inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium text-white shadow-md disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            {t("workflow.runDialog.submit")}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function materialize(
  schema: WorkflowInput[],
  raw: Record<string, string>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const spec of schema) {
    const text = raw[spec.name];
    if (text === undefined || text === "") {
      if (spec.default !== undefined && spec.default !== null) {
        out[spec.name] = spec.default;
      }
      continue;
    }
    if (spec.type === "int") {
      const n = Number(text);
      out[spec.name] = Number.isFinite(n) ? Math.trunc(n) : text;
    } else if (spec.type === "bool") {
      out[spec.name] =
        text.toLowerCase() === "true" || text === "1" || text === "yes";
    } else {
      out[spec.name] = text;
    }
  }
  return out;
}
