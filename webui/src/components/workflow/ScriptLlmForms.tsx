import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import type { JsonSchema } from "@/lib/workflow-client";
import type { KindFormProps } from "@/components/workflow/kind-forms";

const FIELD_CLASS =
  "h-9 rounded-lg border border-[hsl(var(--border))] bg-background/40 px-2 text-xs outline-none transition-colors focus:border-primary/50";

const TEXTAREA_CLASS =
  "min-h-[120px] rounded-lg border border-[hsl(var(--border))] bg-background/40 px-3 py-2 text-xs font-mono outline-none transition-colors focus:border-primary/50";

// ─── Script ──────────────────────────────────────────────────────────

/** @description Script step args editor (code, timeout, env, stdin). */
export function ScriptArgsForm({ step, onChange }: KindFormProps) {
  const { t } = useTranslation();
  const args = (step.args ?? {}) as {
    code?: string;
    timeoutMs?: number;
    env?: Record<string, string>;
    stdin?: string;
  };
  const envJson = useMemo(() => {
    if (!args.env) return "";
    try {
      return JSON.stringify(args.env, null, 2);
    } catch {
      return "";
    }
  }, [args.env]);

  function updateArgs(patch: Record<string, unknown>) {
    onChange({ args: { ...args, ...patch } });
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <label className="flex flex-col gap-1 text-xs md:col-span-1">
          <span className="text-muted-foreground">{t("workflow.script.ref")}</span>
          <select
            value={step.ref || "python"}
            onChange={(e) => onChange({ ref: e.target.value })}
            className={FIELD_CLASS}
          >
            <option value="python">{t("workflow.script.refPython")}</option>
            <option value="shell">{t("workflow.script.refShell")}</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs md:col-span-1">
          <span className="text-muted-foreground">{t("workflow.script.timeoutMs")}</span>
          <input
            type="number"
            value={args.timeoutMs ?? ""}
            onChange={(e) =>
              updateArgs({
                timeoutMs: e.target.value ? Number(e.target.value) : undefined,
              })
            }
            className={FIELD_CLASS}
          />
        </label>
      </div>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted-foreground">{t("workflow.script.code")}</span>
        <textarea
          value={args.code ?? ""}
          onChange={(e) => updateArgs({ code: e.target.value })}
          placeholder={t("workflow.script.codePlaceholder")}
          className={cn(TEXTAREA_CLASS, "min-h-[200px]")}
          spellCheck={false}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted-foreground">{t("workflow.script.stdin")}</span>
        <textarea
          value={args.stdin ?? ""}
          onChange={(e) => updateArgs({ stdin: e.target.value })}
          className={TEXTAREA_CLASS}
          spellCheck={false}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted-foreground">{t("workflow.script.envJson")}</span>
        <textarea
          value={envJson}
          onChange={(e) => {
            const raw = e.target.value.trim();
            if (!raw) {
              updateArgs({ env: undefined });
              return;
            }
            try {
              const parsed = JSON.parse(raw) as Record<string, string>;
              if (parsed && typeof parsed === "object") {
                updateArgs({ env: parsed });
              }
            } catch {
              // Keep the raw text on screen; env stays unchanged until valid JSON.
            }
          }}
          className={cn(TEXTAREA_CLASS, "min-h-[80px]")}
          spellCheck={false}
        />
      </label>
    </div>
  );
}

// ─── LLM ─────────────────────────────────────────────────────────────

const LLM_DEFAULT_MAX_TOKENS = 4096;

/** @description LLM step args editor (prompts, temperature, max tokens). */
export function LlmArgsForm({ step, onChange }: KindFormProps) {
  const { t } = useTranslation();
  const args = (step.args ?? {}) as {
    systemPrompt?: string;
    userPrompt?: string;
    temperature?: number;
    maxTokens?: number;
    responseFormat?: "text" | "json";
  };

  function updateArgs(patch: Record<string, unknown>) {
    onChange({ args: { ...args, ...patch }, ref: "chat" });
  }

  return (
    <div className="space-y-3">
      <p className="rounded-lg border border-border/40 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        {t("workflow.llm.providerHint")}
      </p>
      <div className="rounded-lg border border-alert-warning/30 bg-alert-warning/10 px-3 py-2 text-[11px] leading-relaxed text-alert-warning">
        {t("workflow.llm.reasoningWarning")}
      </div>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted-foreground">{t("workflow.llm.systemPrompt")}</span>
        <textarea
          value={args.systemPrompt ?? ""}
          onChange={(e) => updateArgs({ systemPrompt: e.target.value })}
          className={TEXTAREA_CLASS}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted-foreground">{t("workflow.llm.userPrompt")}</span>
        <textarea
          value={args.userPrompt ?? ""}
          onChange={(e) => updateArgs({ userPrompt: e.target.value })}
          className={cn(TEXTAREA_CLASS, "min-h-[160px]")}
        />
      </label>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-muted-foreground">{t("workflow.llm.temperature")}</span>
          <input
            type="number"
            step="0.1"
            min="0"
            max="2"
            value={args.temperature ?? ""}
            onChange={(e) =>
              updateArgs({
                temperature: e.target.value ? Number(e.target.value) : undefined,
              })
            }
            className={FIELD_CLASS}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-muted-foreground">
            {t("workflow.llm.maxTokens")}
            <span className="ml-1 text-[10px] text-muted-foreground/70">
              {t("workflow.llm.maxTokensDefault", { value: LLM_DEFAULT_MAX_TOKENS })}
            </span>
          </span>
          <input
            type="number"
            min="1"
            placeholder={String(LLM_DEFAULT_MAX_TOKENS)}
            value={args.maxTokens ?? ""}
            onChange={(e) =>
              updateArgs({
                maxTokens: e.target.value ? Number(e.target.value) : undefined,
              })
            }
            className={FIELD_CLASS}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-muted-foreground">{t("workflow.llm.responseFormat")}</span>
          <select
            value={args.responseFormat ?? "text"}
            onChange={(e) =>
              updateArgs({ responseFormat: e.target.value as "text" | "json" })
            }
            className={FIELD_CLASS}
          >
            <option value="text">{t("workflow.llm.formatText")}</option>
            <option value="json">{t("workflow.llm.formatJson")}</option>
          </select>
        </label>
      </div>
    </div>
  );
}

// ─── JSON-Schema driven args form ────────────────────────────────────

export interface JsonSchemaFormProps {
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
}

/**
 * @description Render the top-level properties of a JSON schema as a flat
 * grid of labelled fields. Unsupported shapes degrade to raw JSON.
 */
export function JsonSchemaForm({ schema, value, onChange }: JsonSchemaFormProps) {
  const properties = schema.properties ?? {};
  const required = new Set(schema.required ?? []);

  function update(key: string, next: unknown) {
    onChange({ ...value, [key]: next });
  }

  const entries = Object.entries(properties);
  if (entries.length === 0) {
    return <RawJsonEditor value={value} onChange={onChange} />;
  }

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {entries.map(([key, propSchema]) => {
        const current = value[key];
        const labelText = key + (required.has(key) ? " *" : "");
        return (
          <label key={key} className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">
              {labelText}
              {propSchema.description && (
                <span className="ml-1 text-[10px] opacity-60">
                  — {propSchema.description}
                </span>
              )}
            </span>
            {renderField(propSchema, current, (next) => update(key, next))}
          </label>
        );
      })}
    </div>
  );
}

/** @description Render a single field based on its JSON schema type. */
export function renderField(
  schema: JsonSchema,
  value: unknown,
  onChange: (next: unknown) => void,
) {
  if (Array.isArray(schema.enum) && schema.enum.length > 0) {
    return (
      <select
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value)}
        className={FIELD_CLASS}
      >
        <option value="">—</option>
        {schema.enum.map((opt) => (
          <option key={String(opt)} value={String(opt)}>
            {String(opt)}
          </option>
        ))}
      </select>
    );
  }
  if (schema.type === "boolean") {
    return (
      <input
        type="checkbox"
        checked={value === true}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1 h-4 w-4 accent-primary"
      />
    );
  }
  if (schema.type === "integer" || schema.type === "number") {
    return (
      <input
        type="number"
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) =>
          onChange(e.target.value === "" ? undefined : Number(e.target.value))
        }
        className={FIELD_CLASS}
      />
    );
  }
  if (schema.type === "object" || schema.type === "array") {
    return (
      <RawJsonEditor
        value={(value as Record<string, unknown>) ?? {}}
        onChange={(next) => onChange(next)}
      />
    );
  }
  return (
    <input
      type="text"
      value={value === undefined || value === null ? "" : String(value)}
      onChange={(e) => onChange(e.target.value)}
      className={FIELD_CLASS}
    />
  );
}

/** @description Raw JSON textarea editor for complex schema types. */
export function RawJsonEditor({
  value,
  onChange,
}: {
  value: Record<string, unknown> | unknown;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const text = useMemo(() => {
    try {
      return JSON.stringify(value ?? {}, null, 2);
    } catch {
      return "";
    }
  }, [value]);
  return (
    <textarea
      defaultValue={text}
      onBlur={(e) => {
        const raw = e.target.value.trim();
        if (!raw) {
          onChange({});
          return;
        }
        try {
          const parsed = JSON.parse(raw) as Record<string, unknown>;
          if (parsed && typeof parsed === "object") onChange(parsed);
        } catch {
          // keep raw text until user produces valid JSON
        }
      }}
      className={cn(TEXTAREA_CLASS, "min-h-[120px]")}
      spellCheck={false}
    />
  );
}
