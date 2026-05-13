import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type {
  WorkflowInput,
  WorkflowInputType,
} from "@/lib/workflow-client";

const INPUT_TYPES: WorkflowInputType[] = [
  "string",
  "cidr",
  "int",
  "bool",
  "enum",
];

/** Shared classes for the compact form fields used throughout the
 * workflow editor. Kept local so we do not leak a one-off utility into
 * globals.css. */
const FIELD_BASE =
  "h-9 rounded-lg border border-[hsl(var(--border))] bg-background/40 px-2 text-xs outline-none transition-colors focus:border-primary/50";

export interface InputsEditorProps {
  value: WorkflowInput[];
  onChange: (next: WorkflowInput[]) => void;
  className?: string;
}

/**
 * Editor for ``WorkflowInput[]`` used on the Basics tab. Inputs are
 * user-defined scalars the runner resolves at run time. We do not
 * prescribe any semantics beyond ``{name, type, required}``.
 *
 * Editing is row-oriented: each input is a card with label / name /
 * type / required / default / (enum values). The ``name`` field is
 * the only one with a character constraint ([a-z0-9_]) — we normalise
 * on blur rather than on every keystroke so the user can still type
 * uppercase while composing.
 */
export function InputsEditor({ value, onChange, className }: InputsEditorProps) {
  const { t } = useTranslation();

  function update(i: number, patch: Partial<WorkflowInput>) {
    const next = value.slice();
    next[i] = { ...next[i], ...patch } as WorkflowInput;
    onChange(next);
  }

  function remove(i: number) {
    const next = value.slice();
    next.splice(i, 1);
    onChange(next);
  }

  function add() {
    onChange([
      ...value,
      {
        name: `param_${value.length + 1}`,
        label: "",
        description: "",
        type: "string",
        required: false,
        default: null,
        enumValues: null,
      },
    ]);
  }

  return (
    <section className={cn("space-y-3", className)}>
      <header className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            {t("workflow.basic.inputs")}
          </h3>
          <p className="text-xs text-muted-foreground">
            {t("workflow.basic.inputsHelp")}
          </p>
        </div>
        <button
          type="button"
          onClick={add}
          className="inline-flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs text-primary transition-colors hover:bg-primary/15"
        >
          <Plus className="h-3.5 w-3.5" />
          {t("workflow.basic.addInput")}
        </button>
      </header>

      {value.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border/40 bg-muted/20 px-4 py-6 text-center text-xs text-muted-foreground">
          {t("workflow.basic.inputsHelp")}
        </div>
      ) : (
        <div className="space-y-3">
          {value.map((input, i) => (
            <div
              key={i}
              className="rounded-xl border border-[hsl(var(--border))] bg-background/40 p-4"
            >
              <div className="grid grid-cols-1 gap-3 md:grid-cols-6">
                <LabeledField
                  className="md:col-span-2"
                  label={t("workflow.basic.inputNameLabel")}
                >
                  <input
                    value={input.name}
                    onChange={(e) =>
                      update(i, { name: e.target.value })
                    }
                    onBlur={(e) =>
                      update(i, {
                        name: e.target.value
                          .toLowerCase()
                          .replace(/[^a-z0-9_]/g, "_"),
                      })
                    }
                    className={FIELD_BASE}
                  />
                </LabeledField>
                <LabeledField
                  className="md:col-span-2"
                  label={t("workflow.basic.inputLabelLabel")}
                >
                  <input
                    value={input.label}
                    onChange={(e) => update(i, { label: e.target.value })}
                    className={FIELD_BASE}
                  />
                </LabeledField>
                <LabeledField label={t("workflow.basic.inputTypeLabel")}>
                  <select
                    value={input.type}
                    onChange={(e) =>
                      update(i, {
                        type: e.target.value as WorkflowInputType,
                        enumValues:
                          e.target.value === "enum"
                            ? input.enumValues ?? []
                            : null,
                      })
                    }
                    className={FIELD_BASE}
                  >
                    {INPUT_TYPES.map((tt) => (
                      <option key={tt} value={tt}>
                        {tt}
                      </option>
                    ))}
                  </select>
                </LabeledField>
                <LabeledField label={t("workflow.basic.inputRequiredLabel")}>
                  <label className="mt-1 inline-flex items-center gap-2 text-xs text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={input.required}
                      onChange={(e) =>
                        update(i, { required: e.target.checked })
                      }
                      className="h-4 w-4 accent-primary"
                    />
                    {input.required ? "✓" : ""}
                  </label>
                </LabeledField>

                <LabeledField
                  className="md:col-span-3"
                  label={t("workflow.basic.inputDescriptionLabel")}
                >
                  <input
                    value={input.description ?? ""}
                    onChange={(e) =>
                      update(i, { description: e.target.value })
                    }
                    className={FIELD_BASE}
                  />
                </LabeledField>
                <LabeledField
                  className="md:col-span-3"
                  label={t("workflow.basic.inputDefaultLabel")}
                >
                  <input
                    value={
                      input.default === null || input.default === undefined
                        ? ""
                        : String(input.default)
                    }
                    onChange={(e) =>
                      update(i, {
                        default: coerceDefault(input.type, e.target.value),
                      })
                    }
                    className={FIELD_BASE}
                  />
                </LabeledField>

                {input.type === "enum" && (
                  <LabeledField
                    className="md:col-span-6"
                    label={t("workflow.basic.inputEnumLabel")}
                  >
                    <input
                      value={(input.enumValues ?? []).join(", ")}
                      onChange={(e) =>
                        update(i, {
                          enumValues: e.target.value
                            .split(",")
                            .map((s) => s.trim())
                            .filter(Boolean),
                        })
                      }
                      className={FIELD_BASE}
                    />
                  </LabeledField>
                )}
              </div>
              <div className="mt-2 flex justify-end">
                <button
                  type="button"
                  onClick={() => remove(i)}
                  aria-label={t("workflow.basic.removeInput")}
                  className="inline-flex items-center gap-1 rounded-lg border border-border/40 px-2 py-1 text-xs text-muted-foreground transition-colors hover:border-rose-500/50 hover:text-rose-400"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {t("workflow.basic.removeInput")}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function LabeledField({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={cn("flex flex-col gap-1 text-xs", className)}>
      <span className="text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

export { FIELD_BASE as WORKFLOW_FIELD_CLASS };

function coerceDefault(
  type: WorkflowInputType,
  raw: string,
): string | number | boolean | null {
  if (raw === "") return null;
  if (type === "int") {
    const n = Number(raw);
    return Number.isFinite(n) ? Math.trunc(n) : raw;
  }
  if (type === "bool") {
    return raw.toLowerCase() === "true" || raw === "1";
  }
  return raw;
}
