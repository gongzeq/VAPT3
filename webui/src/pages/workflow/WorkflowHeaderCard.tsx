import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Activity,
  Bot,
  Brain,
  Check,
  Clock,
  Copy,
  Loader2,
  Play,
  Save,
  Square,
  Terminal,
  Wrench,
  Zap,
} from "lucide-react";

import { cn } from "@/lib/utils";
import {
  STEP_KIND_TONE,
  type RunStatus,
  type StepKind,
  type Workflow,
  type WorkflowDraft,
  type WorkflowRun,
  type WorkflowStep,
} from "@/lib/workflow-client";

const KIND_ICON: Record<StepKind, React.ComponentType<{ className?: string }>> = {
  tool: Wrench,
  script: Terminal,
  agent: Bot,
  llm: Brain,
};

interface HeaderCardProps {
  draft: WorkflowDraft;
  saved: Workflow | null;
  recentRun: WorkflowRun | null;
  savedFlash: boolean;
  saving: boolean;
  canSave: boolean;
  onRun: () => void;
  onSave: () => void;
  onClone: () => void;
  onCancelRun: () => void;
}

/** @description Gradient header card with status, progress stats, and animated flow chart. */
export function WorkflowHeaderCard({
  draft,
  saved,
  recentRun,
  savedFlash,
  saving,
  canSave,
  onRun,
  onSave,
  onClone,
  onCancelRun,
}: HeaderCardProps) {
  const { t } = useTranslation();
  const running = recentRun?.status === "running";
  const steps = draft.steps;

  const currentStepIndex = useMemo(() => {
    if (!recentRun || !running) return -1;
    const results = recentRun.stepResults ?? {};
    for (let i = 0; i < steps.length; i += 1) {
      if (!results[steps[i].id]) return i;
    }
    return steps.length;
  }, [recentRun, running, steps]);

  const completedCount = useMemo(() => {
    if (!recentRun) return 0;
    return Object.values(recentRun.stepResults ?? {}).filter(
      (r) => r.status === "ok" || r.status === "skipped",
    ).length;
  }, [recentRun]);

  const elapsed = useMemo(() => {
    if (!recentRun) return "—";
    const end = recentRun.finishedAtMs ?? Date.now();
    return formatDuration(end - recentRun.startedAtMs);
  }, [recentRun]);

  const kindMix = useMemo(() => {
    const set = new Set<StepKind>();
    for (const s of steps) set.add(s.kind);
    return Array.from(set).join(" + ");
  }, [steps]);

  return (
    <div className="gradient-card border-glow animate-fade-in-up space-y-5 rounded-2xl p-6">
      {/* Top row: status + title + actions */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <RunStatusPill status={recentRun?.status ?? null} elapsed={elapsed} />
            {saved && (
              <span className="rounded-md bg-[hsl(var(--muted))]/50 px-2 py-0.5 font-mono text-xs text-muted-foreground">
                {saved.id}
              </span>
            )}
            {draft.tags.slice(0, 4).map((tg) => (
              <span
                key={tg}
                className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[10px] text-primary"
              >
                #{tg}
              </span>
            ))}
            {kindMix && (
              <span className="rounded-full border border-cyan-glow/40 bg-cyan-glow/10 px-2 py-0.5 font-mono text-[10px] text-cyan-glow">
                {kindMix}
              </span>
            )}
          </div>
          <h1 className="truncate text-2xl font-bold text-foreground">
            {draft.name || t("workflow.createNew")}
          </h1>
          {draft.description && (
            <p className="max-w-3xl text-sm text-muted-foreground">
              {draft.description}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {savedFlash && (
            <span className="rounded-full border border-alert-success/40 bg-alert-success/10 px-3 py-1 text-xs text-alert-success">
              {t("workflow.basic.saved")}
            </span>
          )}
          <button
            type="button"
            disabled={!saved}
            onClick={onClone}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors",
              saved
                ? "border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 hover:border-primary/40"
                : "cursor-not-allowed border-border/40 bg-muted/30 text-muted-foreground",
            )}
          >
            <Copy className="h-4 w-4" />{" "}
            {t("workflow.detail.clone", { defaultValue: "创建副本" })}
          </button>
          {running ? (
            <button
              type="button"
              onClick={onCancelRun}
              className="inline-flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive hover:bg-destructive/20"
            >
              <Square className="h-4 w-4" /> {t("workflow.detail.cancel")}
            </button>
          ) : (
            <button
              type="button"
              onClick={onSave}
              disabled={!canSave}
              className={cn(
                "inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-white shadow-md",
                canSave ? "gradient-primary hover-lift" : "cursor-not-allowed bg-muted/40",
              )}
            >
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              {saving ? t("workflow.basic.saving") : t("workflow.basic.save")}
            </button>
          )}
          <button
            type="button"
            onClick={onRun}
            disabled={!saved}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-white shadow-md",
              saved
                ? "gradient-primary hover-lift animate-pulse-glow"
                : "cursor-not-allowed bg-muted/40",
            )}
          >
            <Play className="h-4 w-4" /> {t("workflow.basic.run")}
          </button>
        </div>
      </div>

      {/* 5-col progress stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <ProgressCell
          label={t("workflow.detail.currentStep")}
          value={
            steps.length > 0
              ? `${Math.max(0, Math.min(currentStepIndex + 1, steps.length)) || completedCount} / ${steps.length}`
              : "—"
          }
          tone="primary"
        />
        <ProgressCell label={t("workflow.detail.elapsed")} value={elapsed} />
        <ProgressCell
          label={t("workflow.detail.totalSteps")}
          value={String(steps.length)}
        />
        <ProgressCell
          label={t("workflow.detail.completed")}
          value={String(completedCount)}
          tone="success"
        />
        <ProgressCell
          label={t("workflow.detail.nextRun")}
          value={saved?.scheduleRef ?? t("workflow.card.unscheduled")}
          tone={saved?.scheduleRef ? "primary" : undefined}
        />
      </div>

      {/* Flow chart */}
      {steps.length > 0 && (
        <div className="border-t border-[hsl(var(--border))] pt-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
              <Activity className="h-3.5 w-3.5 text-primary" />
              {t("workflow.detail.flowTitle")}
              {kindMix && (
                <span className="ml-1 font-mono text-[10px] text-muted-foreground/70">
                  · {kindMix}
                </span>
              )}
            </div>
            <FlowLegend
              completed={completedCount}
              running={running && currentStepIndex >= 0 ? 1 : 0}
              pending={Math.max(
                0,
                steps.length - completedCount - (running && currentStepIndex >= 0 ? 1 : 0),
              )}
            />
          </div>

          <div className="flex items-start overflow-x-auto pb-2">
            {steps.map((step, i) => {
              const prevDone = i < completedCount;
              const isCurrent = running && i === currentStepIndex;
              const isPending = !prevDone && !isCurrent;
              return (
                <FlowNode
                  key={step.id}
                  step={step}
                  index={i}
                  isLast={i === steps.length - 1}
                  state={
                    prevDone ? "done" : isCurrent ? "running" : isPending ? "pending" : "done"
                  }
                />
              );
            })}
          </div>

          {running && currentStepIndex >= 0 && steps[currentStepIndex] && (
            <div className="mt-4 flex items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
              <Zap className="h-4 w-4 animate-pulse text-primary" />
              <div className="min-w-0 flex-1 text-xs">
                <span className="font-semibold text-primary">
                  {t("workflow.detail.stepCounter", {
                    current: currentStepIndex + 1,
                    total: steps.length,
                  })}
                </span>
                <span className="text-muted-foreground"> · </span>
                <span className="font-mono text-foreground">
                  {steps[currentStepIndex].kind}:
                  {steps[currentStepIndex].ref || steps[currentStepIndex].id}
                </span>
                <span className="text-muted-foreground">
                  {" "}
                  · {t("workflow.detail.runningHint")}
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** @description Run status badge pill. */
export function RunStatusPill({
  status,
  elapsed,
}: {
  status: RunStatus | null;
  elapsed: string;
}) {
  const { t } = useTranslation();
  if (status === "running") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-alert-success/40 bg-alert-success/10 px-3 py-1 font-mono text-xs text-alert-success">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-alert-success" />
        {t("workflow.badge.running")} · {elapsed}
      </span>
    );
  }
  if (status === "ok") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-alert-success/40 bg-alert-success/10 px-3 py-1 font-mono text-xs text-alert-success">
        <Check className="h-3 w-3" /> {t("workflow.runs.status.ok")} · {elapsed}
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-destructive/40 bg-destructive/10 px-3 py-1 font-mono text-xs text-destructive">
        {t("workflow.runs.status.error")} · {elapsed}
      </span>
    );
  }
  if (status === "cancelled") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 px-3 py-1 font-mono text-xs text-muted-foreground">
        {t("workflow.runs.status.cancelled")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 px-3 py-1 font-mono text-xs text-muted-foreground">
      <Clock className="h-3 w-3" /> {t("workflow.detail.idle")}
    </span>
  );
}

/** @description Progress stat cell. */
export function ProgressCell({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "primary" | "success";
}) {
  const toneCls =
    tone === "primary"
      ? "text-primary"
      : tone === "success"
        ? "text-alert-success"
        : "text-foreground";
  return (
    <div className="rounded-lg bg-[hsl(var(--muted))]/40 p-3">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 truncate font-mono text-sm", toneCls)} title={value}>
        {value}
      </div>
    </div>
  );
}

/** @description Flow chart legend showing completed/running/pending counts. */
export function FlowLegend({
  completed,
  running,
  pending,
}: {
  completed: number;
  running: number;
  pending: number;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-x-3 font-mono text-[10px] text-muted-foreground">
      <span>
        <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-alert-success align-middle" />
        {t("workflow.detail.legendDone")} {completed}
      </span>
      <span>
        <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-primary align-middle" />
        {t("workflow.detail.legendRunning")} {running}
      </span>
      <span>
        <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-muted-foreground/60 align-middle" />
        {t("workflow.detail.legendPending")} {pending}
      </span>
    </div>
  );
}

/** @description Single node in the workflow flow chart. */
export function FlowNode({
  step,
  index,
  isLast,
  state,
}: {
  step: WorkflowStep;
  index: number;
  isLast: boolean;
  state: "done" | "running" | "pending";
}) {
  const Icon = KIND_ICON[step.kind];
  const tone = STEP_KIND_TONE[step.kind];
  const borderCls =
    state === "done"
      ? "border-alert-success bg-alert-success/15"
      : state === "running"
        ? "border-primary bg-primary/15 flow-node-running animate-pulse-glow"
        : "border-dashed border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30";
  const iconCls =
    state === "done"
      ? "text-alert-success"
      : state === "running"
        ? "text-primary"
        : "text-muted-foreground";

  return (
    <>
      <div className="flex min-w-[84px] shrink-0 flex-col items-center">
        <div
          className={cn(
            "relative flex h-10 w-10 items-center justify-center rounded-full border-2",
            borderCls,
          )}
        >
          {state === "done" ? (
            <Check className="h-5 w-5 text-alert-success" />
          ) : (
            <Icon className={cn("h-5 w-5", iconCls)} />
          )}
          {state === "running" && (
            <span className="absolute inset-[-6px] animate-ping rounded-full border border-primary/30" />
          )}
        </div>
        <div
          className={cn(
            "mt-2 max-w-[96px] truncate text-[11px] leading-tight",
            state === "running"
              ? "font-semibold text-primary"
              : state === "done"
                ? "text-foreground"
                : "text-muted-foreground",
          )}
          title={step.name || step.ref || step.kind}
        >
          {step.name || step.ref || `${step.kind} ${index + 1}`}
        </div>
        <div
          className={cn(
            "mt-0.5 font-mono text-[10px]",
            state === "running" ? "text-primary" : "text-muted-foreground",
          )}
        >
          {tone.label}
        </div>
      </div>
      {!isLast && (
        <div className="flex-1 px-1 pt-5">
          {state === "running" ? (
            <div className="relative h-0.5 w-full overflow-hidden rounded-full bg-[hsl(var(--muted))]/60">
              <div className="flow-progress-bar" />
            </div>
          ) : state === "done" ? (
            <div className="h-0.5 w-full rounded-full bg-alert-success/60" />
          ) : (
            <div className="h-0 w-full border-t-2 border-dashed border-[hsl(var(--border))]" />
          )}
        </div>
      )}
    </>
  );
}

/** @description Format milliseconds as MM:SS duration string. */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
