import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  Bot,
  Brain,
  Clock,
  PlayCircle,
  Terminal,
  Trash2,
  Wrench,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { STEP_KIND_TONE, type StepKind, type Workflow, type WorkflowStep } from "@/lib/workflow-client";
import type { StatusFilter } from "@/pages/workflow/LeftFilter";

const KIND_ICON: Record<StepKind, React.ComponentType<{ className?: string }>> = {
  tool: Wrench,
  script: Terminal,
  agent: Bot,
  llm: Brain,
};

/** @description Workflow list card with mini-flow step visualization. */
export function WorkflowListCard({
  workflow,
  onOpen,
  onDelete,
}: {
  workflow: Workflow;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const { t, i18n } = useTranslation();
  const updated = new Date(workflow.updatedAtMs).toLocaleString(
    i18n.resolvedLanguage || "zh-CN",
  );
  const status: StatusFilter = workflow.scheduleRef ? "scheduled" : "manual";
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className={cn(
        "gradient-card hover-lift animate-fade-in-up block cursor-pointer rounded-2xl border p-5",
        status === "scheduled" ? "border-primary/30" : "border-[hsl(var(--border))]",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <StatusBadge status={status} />
            <span className="rounded-md bg-[hsl(var(--muted))]/60 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
              {workflow.id}
            </span>
            {workflow.tags.slice(0, 3).map((tg) => (
              <span
                key={tg}
                className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 px-2 py-0.5 text-[10px] text-muted-foreground"
              >
                #{tg}
              </span>
            ))}
          </div>
          <h3 className="truncate text-base font-semibold text-foreground">
            {workflow.name || workflow.id}
          </h3>
          {workflow.description && (
            <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
              {workflow.description}
            </p>
          )}
        </div>
        <button
          type="button"
          aria-label={t("workflow.card.delete")}
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-white/5 hover:text-destructive"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      {workflow.steps.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px]">
          <MiniFlow steps={workflow.steps} />
        </div>
      )}

      <div className="mt-4 grid grid-cols-4 gap-3 text-xs">
        <FactCell label={t("workflow.card.stepsLabel")} value={String(workflow.steps.length)} />
        <FactCell
          label={t("workflow.card.inputsLabel")}
          value={String(workflow.inputs.length)}
        />
        <FactCell
          label={t("workflow.card.scheduleLabel")}
          value={
            workflow.scheduleRef
              ? t("workflow.card.scheduled")
              : t("workflow.card.unscheduled")
          }
          valueCls={workflow.scheduleRef ? "text-primary" : "text-muted-foreground"}
        />
        <FactCell label={t("workflow.card.updatedLabel")} value={updated} mono={false} />
      </div>
    </div>
  );
}

function FactCell({
  label,
  value,
  valueCls,
  mono = true,
}: {
  label: string;
  value: string;
  valueCls?: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div
        className={cn("mt-0.5 truncate text-sm text-foreground", mono && "font-mono", valueCls)}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: StatusFilter }) {
  const { t } = useTranslation();
  if (status === "scheduled") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/40 bg-primary/10 px-2.5 py-0.5 font-mono text-[10px] text-primary">
        <Clock className="h-3 w-3" /> {t("workflow.badge.scheduled")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-alert-success/40 bg-alert-success/10 px-2.5 py-0.5 font-mono text-[10px] text-alert-success">
      <PlayCircle className="h-3 w-3" />{" "}
      {t("workflow.badge.manual", { defaultValue: "已保存" })}
    </span>
  );
}

function MiniFlow({ steps }: { steps: WorkflowStep[] }) {
  const head = steps.slice(0, 5);
  const more = Math.max(0, steps.length - head.length);
  return (
    <>
      {head.map((step, i) => {
        const Icon = KIND_ICON[step.kind];
        const tone = STEP_KIND_TONE[step.kind];
        return (
          <span key={step.id} className="inline-flex items-center gap-1">
            {i > 0 && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
            <span
              className={cn(
                "inline-flex max-w-[120px] items-center gap-1 rounded-md border px-1.5 py-0.5",
                tone.badge,
              )}
              title={step.name || step.ref || step.kind}
            >
              <Icon className="h-3 w-3 shrink-0" />
              <span className="truncate">{step.name || step.ref || step.kind}</span>
            </span>
          </span>
        );
      })}
      {more > 0 && <span className="text-muted-foreground">+{more}</span>}
    </>
  );
}
