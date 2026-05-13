import { useTranslation } from "react-i18next";
import {
  ArrowDown,
  ArrowUp,
  Copy,
  Plus,
  Trash2,
} from "lucide-react";

import { cn } from "@/lib/utils";
import {
  STEP_KIND_TONE,
  blankStep,
  nextStepId,
  type AgentMeta,
  type StepKind,
  type StepOnError,
  type ToolMeta,
  type WorkflowStep,
} from "@/lib/workflow-client";
import {
  KindArgsForm,
  kindLabelKey,
} from "@/components/workflow/kind-forms";
import { WORKFLOW_FIELD_CLASS } from "@/components/workflow/InputsEditor";

const KIND_ORDER: StepKind[] = ["tool", "script", "agent", "llm"];

export interface StepEditorProps {
  steps: WorkflowStep[];
  onChange: (next: WorkflowStep[]) => void;
  tools?: ToolMeta[];
  agents?: AgentMeta[];
}

/**
 * Ordered list of step cards. The only structural operation we offer
 * is move-up/move-down/duplicate/delete — DAG-style branching is
 * expressed via ``condition`` on each step instead of a visual canvas
 * (api-spec §1.3). Each card is self-contained; edits bubble up via
 * ``onChange`` replacing the parent's full ``steps`` array.
 */
export function StepEditor({ steps, onChange, tools, agents }: StepEditorProps) {
  const { t } = useTranslation();

  function addStep(kind: StepKind) {
    onChange([...steps, blankStep(kind, nextStepId(steps))]);
  }

  function updateAt(index: number, patch: Partial<WorkflowStep>) {
    const next = steps.slice();
    next[index] = { ...next[index], ...patch } as WorkflowStep;
    onChange(next);
  }

  function removeAt(index: number) {
    const next = steps.slice();
    next.splice(index, 1);
    onChange(next);
  }

  function move(index: number, delta: -1 | 1) {
    const target = index + delta;
    if (target < 0 || target >= steps.length) return;
    const next = steps.slice();
    const [item] = next.splice(index, 1);
    next.splice(target, 0, item);
    onChange(next);
  }

  function duplicate(index: number) {
    const src = steps[index];
    const copy: WorkflowStep = {
      ...src,
      id: nextStepId(steps),
      name: src.name ? `${src.name} (copy)` : "",
      args: JSON.parse(JSON.stringify(src.args ?? {})),
    };
    const next = steps.slice();
    next.splice(index + 1, 0, copy);
    onChange(next);
  }

  return (
    <section className="space-y-3">
      <header className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">
          {t("workflow.steps.pickKind")}:
        </span>
        {KIND_ORDER.map((kind) => {
          const tone = STEP_KIND_TONE[kind];
          return (
            <button
              key={kind}
              type="button"
              onClick={() => addStep(kind)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors",
                tone.badge,
                "hover:brightness-110",
              )}
            >
              <Plus className="h-3.5 w-3.5" />
              {t(kindLabelKey(kind))}
            </button>
          );
        })}
      </header>

      {steps.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border/40 bg-muted/20 px-4 py-10 text-center text-xs text-muted-foreground">
          {t("workflow.steps.empty")}
        </div>
      ) : (
        <ol className="space-y-3">
          {steps.map((step, index) => (
            <StepCard
              key={step.id}
              index={index}
              total={steps.length}
              step={step}
              onChange={(patch) => updateAt(index, patch)}
              onRemove={() => removeAt(index)}
              onMoveUp={() => move(index, -1)}
              onMoveDown={() => move(index, +1)}
              onDuplicate={() => duplicate(index)}
              tools={tools}
              agents={agents}
            />
          ))}
        </ol>
      )}
    </section>
  );
}

// ─── StepCard ────────────────────────────────────────────────────────

interface StepCardProps {
  index: number;
  total: number;
  step: WorkflowStep;
  onChange: (patch: Partial<WorkflowStep>) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDuplicate: () => void;
  tools?: ToolMeta[];
  agents?: AgentMeta[];
}

function StepCard({
  index,
  total,
  step,
  onChange,
  onRemove,
  onMoveUp,
  onMoveDown,
  onDuplicate,
  tools,
  agents,
}: StepCardProps) {
  const { t } = useTranslation();
  const tone = STEP_KIND_TONE[step.kind];
  return (
    <li className="gradient-card rounded-2xl border border-[hsl(var(--border))] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "flex h-7 w-7 items-center justify-center rounded-full font-mono text-xs text-white",
            tone.dot,
          )}
        >
          {index + 1}
        </span>
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide",
            tone.badge,
          )}
        >
          {t(kindLabelKey(step.kind))}
        </span>
        <input
          value={step.name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder={t("workflow.steps.namePlaceholder")}
          className={cn(WORKFLOW_FIELD_CLASS, "min-w-0 flex-1")}
        />
        <div className="flex shrink-0 items-center gap-1">
          <IconBtn
            ariaLabel={t("workflow.steps.moveUp")}
            disabled={index === 0}
            onClick={onMoveUp}
          >
            <ArrowUp className="h-3.5 w-3.5" />
          </IconBtn>
          <IconBtn
            ariaLabel={t("workflow.steps.moveDown")}
            disabled={index === total - 1}
            onClick={onMoveDown}
          >
            <ArrowDown className="h-3.5 w-3.5" />
          </IconBtn>
          <IconBtn
            ariaLabel={t("workflow.steps.duplicate")}
            onClick={onDuplicate}
          >
            <Copy className="h-3.5 w-3.5" />
          </IconBtn>
          <IconBtn
            ariaLabel={t("workflow.steps.remove")}
            onClick={onRemove}
            tone="danger"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </IconBtn>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
        <label className="flex flex-col gap-1 text-xs md:col-span-2">
          <span className="text-muted-foreground">
            {t("workflow.steps.conditionLabel")}
          </span>
          <input
            value={step.condition ?? ""}
            onChange={(e) =>
              onChange({
                condition: e.target.value.trim() ? e.target.value : null,
              })
            }
            placeholder={t("workflow.steps.conditionPlaceholder")}
            className={cn(WORKFLOW_FIELD_CLASS, "font-mono")}
          />
          <span className="text-[11px] text-muted-foreground opacity-70">
            {t("workflow.steps.conditionHelp")}
          </span>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">
              {t("workflow.steps.onErrorLabel")}
            </span>
            <select
              value={step.onError}
              onChange={(e) =>
                onChange({ onError: e.target.value as StepOnError })
              }
              className={WORKFLOW_FIELD_CLASS}
            >
              <option value="stop">{t("workflow.steps.onErrorStop")}</option>
              <option value="continue">
                {t("workflow.steps.onErrorContinue")}
              </option>
              <option value="retry">
                {t("workflow.steps.onErrorRetry")}
              </option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">
              {t("workflow.steps.retryLabel")}
            </span>
            <input
              type="number"
              min="0"
              max="5"
              value={step.retry}
              onChange={(e) =>
                onChange({ retry: Math.max(0, Number(e.target.value) || 0) })
              }
              className={WORKFLOW_FIELD_CLASS}
            />
          </label>
        </div>
      </div>

      <div className="mt-4 border-t border-border/30 pt-4">
        <p className="mb-2 text-xs text-muted-foreground">
          {t("workflow.steps.args")}
        </p>
        <KindArgsForm
          step={step}
          onChange={onChange}
          tools={tools}
          agents={agents}
        />
      </div>
    </li>
  );
}

function IconBtn({
  ariaLabel,
  onClick,
  disabled,
  tone,
  children,
}: {
  ariaLabel: string;
  onClick: () => void;
  disabled?: boolean;
  tone?: "danger";
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "rounded-lg border border-border/40 p-1.5 text-muted-foreground transition-colors",
        "disabled:opacity-40 disabled:cursor-not-allowed",
        tone === "danger"
          ? "hover:border-rose-500/50 hover:text-rose-400"
          : "hover:border-primary/50 hover:text-primary",
      )}
    >
      {children}
    </button>
  );
}
