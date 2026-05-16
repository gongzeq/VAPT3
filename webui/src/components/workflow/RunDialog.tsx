import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Play } from "lucide-react";

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
  const [busy, setBusy] = useState(false);
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
    setError(null);
  }, [open, workflow]);

  async function submit() {
    if (!workflow) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(materialize(workflow.inputs, values));
      onOpenChange(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
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
            disabled={busy}
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
