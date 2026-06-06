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
 *     returned by ``GET /_tools`` / ``/_agents``. Users no longer have to
 *     go to the backend repo to learn what an agent expects.
 *   - LLM form shows a default-value hint next to ``maxTokens`` and a
 *     warning about reasoning-model finish_reason=length responses.
 */

import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Copy, Info } from "lucide-react";

import { cn } from "@/lib/utils";
import type {
  AgentMeta,
  StepKind,
  ToolMeta,
  WorkflowInput,
  WorkflowStep,
} from "@/lib/workflow-client";
import { SchemaDocCard } from "@/components/workflow/SchemaDoc";
import {
  ScriptArgsForm,
  LlmArgsForm,
  JsonSchemaForm,
} from "@/components/workflow/ScriptLlmForms";

const FIELD_CLASS =
  "h-9 rounded-lg border border-[hsl(var(--border))] bg-background/40 px-2 text-xs outline-none transition-colors focus:border-primary/50";

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

/** @description Dispatcher — render the correct args editor given step.kind. */
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
                  : "border-alert-success/40 bg-alert-success/10 text-alert-success hover:bg-alert-success/15",
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
        <span className="text-muted-foreground">{t("workflow.tool.select")}</span>
        <select
          value={step.ref}
          onChange={(e) => onChange({ ref: e.target.value, args: {} })}
          className={FIELD_CLASS}
        >
          <option value="">—</option>
          {tools === undefined && (
            <option disabled>{t("workflow.tool.loading")}</option>
          )}
          {tools && tools.length === 0 && (
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
        <span className="text-muted-foreground">{t("workflow.agent.select")}</span>
        <select
          value={step.ref}
          onChange={(e) => onChange({ ref: e.target.value, args: {} })}
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

/** @description Convenience used by StepEditor to colour the step-kind chips. */
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
