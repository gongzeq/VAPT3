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
 *
 * UX additions (2026-05-13):
 *   - Every kind shows a "placeholders" chip row at the top, listing
 *     ``${inputs.<name>}`` and ``${steps.<prev>.result}`` that the user
 *     can click-to-copy. This cut the 'ref error / empty prompt' class
 *     of bugs where users forgot to fill a placeholder.
 *   - Tool & Agent render a collapsible "入参 / 出参 / 示例" info card
 *     once a ref is picked, pulled from ``inputSchema`` / ``outputSchema``
 *     returned by ``GET /_tools`` / ``/_agents``. Users no longer have
 *     to go to the backend repo to learn what an agent expects.
 *   - LLM form shows a default-value hint next to ``maxTokens`` and a
 *     warning about reasoning-model finish_reason=length responses.
 */

import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  Copy,
  Info,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type {
  AgentMeta,
  JsonSchema,
  StepKind,
  ToolMeta,
  WorkflowInput,
  WorkflowStep,
} from "@/lib/workflow-client";

const FIELD_CLASS =
  "h-9 rounded-lg border border-[hsl(var(--border))] bg-background/40 px-2 text-xs outline-none transition-colors focus:border-primary/50";

const TEXTAREA_CLASS =
  "min-h-[120px] rounded-lg border border-[hsl(var(--border))] bg-background/40 px-3 py-2 text-xs font-mono outline-none transition-colors focus:border-primary/50";

// ─── Shared props ─────────────────────────────────────────────────────

export interface KindFormProps {
  step: WorkflowStep;
  onChange: (patch: Partial<WorkflowStep>) => void;
  /** Metadata dictionaries loaded from `/_tools` / `/_agents`.
   * Either may be missing while still loading. */
  tools?: ToolMeta[];
  agents?: AgentMeta[];
  /** Workflow-level inputs (for ``${inputs.*}`` placeholder chips). */
  inputs?: WorkflowInput[];
  /** Steps occurring BEFORE this one in the workflow, for
   * ``${steps.<id>.result}`` placeholder chips. */
  previousSteps?: WorkflowStep[];
}

/** Dispatcher — render the correct args editor given ``step.kind``. */
export function KindArgsForm(props: KindFormProps) {
  const { step, inputs, previousSteps } = props;
  return (
    <div className="space-y-3">
      <PlaceholderHints inputs={inputs} previousSteps={previousSteps} />
      {step.kind === "tool" && <ToolArgsForm {...props} />}
      {step.kind === "script" && <ScriptArgsForm {...props} />}
      {step.kind === "agent" && <AgentArgsForm {...props} />}
      {step.kind === "llm" && <LlmArgsForm {...props} />}
    </div>
  );
}

// ─── Placeholder chip row ─────────────────────────────────────────────

function PlaceholderHints({
  inputs,
  previousSteps,
}: {
  inputs?: WorkflowInput[];
  previousSteps?: WorkflowStep[];
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState<string | null>(null);
  const copyTimer = useRef<number | null>(null);

  const items = useMemo(() => {
    const chips: { label: string; value: string; tone: "input" | "step" }[] = [];
    for (const inp of inputs ?? []) {
      if (!inp.name) continue;
      chips.push({
        label: `\${inputs.${inp.name}}`,
        value: `\${inputs.${inp.name}}`,
        tone: "input",
      });
    }
    for (const s of previousSteps ?? []) {
      if (!s.id) continue;
      chips.push({
        label: `\${steps.${s.id}.result}`,
        value: `\${steps.${s.id}.result}`,
        tone: "step",
      });
    }
    return chips;
  }, [inputs, previousSteps]);

  if (items.length === 0) return null;

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      // Non-secure context fallback (user memory: crypto.randomUUID
      // not available on insecure origins; same family of limitations
      // applies to the clipboard API).
      const ta = document.createElement("textarea");
      ta.value = value;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch {
        // leave the value visible — user can copy manually
      } finally {
        document.body.removeChild(ta);
      }
    }
    setCopied(value);
    if (copyTimer.current) window.clearTimeout(copyTimer.current);
    copyTimer.current = window.setTimeout(() => setCopied(null), 1200);
  }

  return (
    <div className="rounded-lg border border-border/40 bg-muted/20 px-3 py-2">
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Info className="h-3 w-3 text-primary" />
        {t("workflow.placeholders.title")}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {items.map((chip) => {
          const isCopied = copied === chip.value;
          return (
            <button
              key={chip.value}
              type="button"
              onClick={() => void copy(chip.value)}
              className={cn(
                "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[11px] transition-colors",
                chip.tone === "input"
                  ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/15"
                  : "border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/15",
              )}
              title={t("workflow.placeholders.copyHint")}
            >
              <Copy className="h-3 w-3 opacity-70" />
              {chip.label}
              {isCopied && (
                <span className="ml-1 text-[10px] text-muted-foreground">
                  {t("workflow.placeholders.copied")}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
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
      {selected && <SchemaDocCard meta={selected} scope="tool" />}
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
      {selected && <SchemaDocCard meta={selected} scope="agent" />}
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

// ─── SchemaDocCard ───────────────────────────────────────────────────

function SchemaDocCard({
  meta,
  scope,
}: {
  meta: ToolMeta | AgentMeta;
  scope: "tool" | "agent";
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);
  const hasInput = !!(
    meta.inputSchema &&
    meta.inputSchema.properties &&
    Object.keys(meta.inputSchema.properties).length > 0
  );
  const hasOutput = !!(
    meta.outputSchema &&
    meta.outputSchema.properties &&
    Object.keys(meta.outputSchema.properties).length > 0
  );

  return (
    <div className="rounded-lg border border-primary/30 bg-primary/5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 text-primary" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-primary" />
        )}
        <BookOpen className="h-3.5 w-3.5 text-primary" />
        <span className="font-medium text-primary">
          {scope === "tool"
            ? t("workflow.tool.docTitle")
            : t("workflow.agent.docTitle")}
          {meta.title && meta.title !== meta.name ? (
            <span className="ml-1 font-normal text-muted-foreground">
              · {meta.title}
            </span>
          ) : null}
        </span>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
          {meta.name}
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-primary/20 px-3 py-2 text-xs">
          {meta.description && (
            <p className="leading-relaxed text-muted-foreground">
              {meta.description}
            </p>
          )}
          <SchemaDocSection
            title={t("workflow.doc.inputs")}
            schema={hasInput ? meta.inputSchema : undefined}
            emptyHint={t("workflow.doc.inputsEmpty")}
          />
          <SchemaDocSection
            title={t("workflow.doc.outputs")}
            schema={hasOutput ? meta.outputSchema : undefined}
            emptyHint={t("workflow.doc.outputsEmpty")}
          />
        </div>
      )}
    </div>
  );
}

function SchemaDocSection({
  title,
  schema,
  emptyHint,
}: {
  title: string;
  schema?: JsonSchema;
  emptyHint: string;
}) {
  const entries = Object.entries(schema?.properties ?? {});
  const required = new Set(schema?.required ?? []);
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      {entries.length === 0 ? (
        <div className="text-[11px] italic text-muted-foreground/70">
          {emptyHint}
        </div>
      ) : (
        <ul className="space-y-1">
          {entries.map(([k, v]) => (
            <li
              key={k}
              className="rounded-md border border-border/30 bg-background/30 px-2 py-1"
            >
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="font-mono text-[11px] text-primary">
                  {k}
                </span>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {formatType(v)}
                </span>
                {required.has(k) && (
                  <span className="rounded bg-rose-500/20 px-1 text-[9px] text-rose-300">
                    required
                  </span>
                )}
              </div>
              {v.description && (
                <div className="mt-0.5 text-[11px] text-muted-foreground">
                  {v.description}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function formatType(schema: JsonSchema): string {
  if (Array.isArray(schema.enum) && schema.enum.length > 0) {
    return `enum(${schema.enum.map(String).join("|")})`;
  }
  if (schema.type === "array") {
    return `array<${schema.items ? formatType(schema.items) : "any"}>`;
  }
  return schema.type ?? "any";
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

/** Keep in sync with ``secbot/workflow/executors/llm.py::_DEFAULT_MAX_TOKENS``. */
const LLM_DEFAULT_MAX_TOKENS = 4096;

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
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] leading-relaxed text-amber-200">
        {t("workflow.llm.reasoningWarning")}
      </div>
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
            <span className="ml-1 text-[10px] text-muted-foreground/70">
              {t("workflow.llm.maxTokensDefault", {
                value: LLM_DEFAULT_MAX_TOKENS,
              })}
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
