/**
 * Kind-specific ``args`` editors for a :class:`WorkflowStep`.
 *
 * Each form speaks the contract from api-spec §1.3:
 *   - tool  → JSON-Schema-driven (dropdown for ref + dynamic fields)
 *   - script→ { code, timeoutMs?, env?, stdin?, ref: python|shell }
 *   - agent → JSON-Schema-driven (same shape as tool)
 *   - llm   → { systemPrompt, userPrompt, temperature?, maxTokens?, responseFormat }
 *
 * The shared JSON-Schema form is intentionally minimal — we render the
 * top-level ``properties`` dictionary, inferring the control type from
 * the property schema's ``type`` / ``enum`` hints. Nested objects fall
 * back to a free-text JSON box. This avoids pulling in @rjsf for MVP
 * (see dev-guide §3.4 / §6 risk log).
 */

import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import type {
  AgentMeta,
  JsonSchema,
  StepKind,
  ToolMeta,
  WorkflowStep,
} from "@/lib/workflow-client";

const FIELD_CLASS =
  "h-9 rounded-lg border border-[hsl(var(--border))] bg-background/40 px-2 text-xs outline-none transition-colors focus:border-primary/50";

const TEXTAREA_CLASS =
  "min-h-[120px] rounded-lg border border-[hsl(var(--border))] bg-background/40 px-3 py-2 text-xs font-mono outline-none transition-colors focus:border-primary/50";

export interface KindFormProps {
  step: WorkflowStep;
  onChange: (patch: Partial<WorkflowStep>) => void;
  /** Metadata dictionaries loaded from `/_tools` / `/_agents`.
   * Either may be missing while still loading. */
  tools?: ToolMeta[];
  agents?: AgentMeta[];
}

/** Dispatcher — render the correct args editor given ``step.kind``. */
export function KindArgsForm(props: KindFormProps) {
  const { step } = props;
  if (step.kind === "tool") return <ToolArgsForm {...props} />;
  if (step.kind === "script") return <ScriptArgsForm {...props} />;
  if (step.kind === "agent") return <AgentArgsForm {...props} />;
  if (step.kind === "llm") return <LlmArgsForm {...props} />;
  return null;
}

// ─── Tool ────────────────────────────────────────────────────────────

function ToolArgsForm({ step, onChange, tools }: KindFormProps) {
  const { t } = useTranslation();
  const selected = tools?.find((m) => m.name === step.ref);
  const schema = selected?.inputSchema;

  return (
    <div className="space-y-3">
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted-foreground">
          {t("workflow.tool.select")}
        </span>
        <select
          value={step.ref}
          onChange={(e) =>
            onChange({ ref: e.target.value, args: {} })
          }
          className={FIELD_CLASS}
        >
          <option value="">—</option>
          {tools === undefined && (
            <option disabled>{t("workflow.tool.loading")}</option>
          )}
          {tools &&
            tools.length === 0 && (
              <option disabled>{t("workflow.tool.empty")}</option>
            )}
          {tools?.map((m) => (
            <option key={m.name} value={m.name}>
              {m.title || m.name}
            </option>
          ))}
        </select>
      </label>
      {selected?.description && (
        <p className="text-xs text-muted-foreground">{selected.description}</p>
      )}
      {schema && (
        <JsonSchemaForm
          schema={schema}
          value={step.args}
          onChange={(args) => onChange({ args })}
        />
      )}
    </div>
  );
}

// ─── Agent ───────────────────────────────────────────────────────────

function AgentArgsForm({ step, onChange, agents }: KindFormProps) {
  const { t } = useTranslation();
  const selected = agents?.find((m) => m.name === step.ref);
  const schema = selected?.inputSchema;

  return (
    <div className="space-y-3">
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted-foreground">
          {t("workflow.agent.select")}
        </span>
        <select
          value={step.ref}
          onChange={(e) =>
            onChange({ ref: e.target.value, args: {} })
          }
          className={FIELD_CLASS}
        >
          <option value="">—</option>
          {agents === undefined && (
            <option disabled>{t("workflow.agent.loading")}</option>
          )}
          {agents && agents.length === 0 && (
            <option disabled>{t("workflow.agent.empty")}</option>
          )}
          {agents?.map((m) => (
            <option key={m.name} value={m.name}>
              {m.title || m.name}
            </option>
          ))}
        </select>
      </label>
      {selected?.description && (
        <p className="text-xs text-muted-foreground">{selected.description}</p>
      )}
      {schema && (
        <JsonSchemaForm
          schema={schema}
          value={step.args}
          onChange={(args) => onChange({ args })}
        />
      )}
    </div>
  );
}

// ─── Script ──────────────────────────────────────────────────────────

function ScriptArgsForm({ step, onChange }: KindFormProps) {
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
          <span className="text-muted-foreground">
            {t("workflow.script.ref")}
          </span>
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
          <span className="text-muted-foreground">
            {t("workflow.script.timeoutMs")}
          </span>
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
        <span className="text-muted-foreground">
          {t("workflow.script.code")}
        </span>
        <textarea
          value={args.code ?? ""}
          onChange={(e) => updateArgs({ code: e.target.value })}
          placeholder={t("workflow.script.codePlaceholder")}
          className={cn(TEXTAREA_CLASS, "min-h-[200px]")}
          spellCheck={false}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted-foreground">
          {t("workflow.script.stdin")}
        </span>
        <textarea
          value={args.stdin ?? ""}
          onChange={(e) => updateArgs({ stdin: e.target.value })}
          className={TEXTAREA_CLASS}
          spellCheck={false}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted-foreground">
          {t("workflow.script.envJson")}
        </span>
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
              // Keep the raw text on screen; env stays unchanged until
              // the user produces valid JSON.
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

function LlmArgsForm({ step, onChange }: KindFormProps) {
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
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted-foreground">
          {t("workflow.llm.systemPrompt")}
        </span>
        <textarea
          value={args.systemPrompt ?? ""}
          onChange={(e) => updateArgs({ systemPrompt: e.target.value })}
          className={TEXTAREA_CLASS}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted-foreground">
          {t("workflow.llm.userPrompt")}
        </span>
        <textarea
          value={args.userPrompt ?? ""}
          onChange={(e) => updateArgs({ userPrompt: e.target.value })}
          className={cn(TEXTAREA_CLASS, "min-h-[160px]")}
        />
      </label>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-muted-foreground">
            {t("workflow.llm.temperature")}
          </span>
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
          </span>
          <input
            type="number"
            min="1"
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
          <span className="text-muted-foreground">
            {t("workflow.llm.responseFormat")}
          </span>
          <select
            value={args.responseFormat ?? "text"}
            onChange={(e) =>
              updateArgs({
                responseFormat: e.target.value as "text" | "json",
              })
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
 * Render the top-level ``properties`` of ``schema`` as a flat grid of
 * labelled fields. The goal is not a full JSON-Schema implementation —
 * just enough to let the user fill in the known input surface of a
 * tool or agent without dropping to raw JSON.
 *
 * Unsupported shapes (nested objects, arrays of objects, oneOf, …)
 * degrade to a ``<textarea>`` JSON editor so the user can still set
 * them via raw JSON. Invalid JSON is silently kept on screen until
 * it parses.
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

function renderField(
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
    // Fall back to raw JSON so power users can still edit nested shapes.
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

function RawJsonEditor({
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

/** Convenience used by StepEditor to colour the step-kind chips. */
export function kindLabelKey(kind: StepKind): string {
  switch (kind) {
    case "tool":
      return "workflow.steps.kindTool";
    case "script":
      return "workflow.steps.kindScript";
    case "agent":
      return "workflow.steps.kindAgent";
    case "llm":
      return "workflow.steps.kindLlm";
  }
}
