import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  History,
  Loader2,
  RotateCw,
  XCircle,
} from "lucide-react";

import { cn } from "@/lib/utils";
import {
  type RunStatus,
  type StepResult,
  type Workflow,
  type WorkflowClient,
  type WorkflowRun,
} from "@/lib/workflow-client";

const POLL_INTERVAL_MS = 3_000;

export interface RunHistoryTabProps {
  workflow: Workflow;
  client: WorkflowClient;
  /** Monotonic counter bumped by the detail page whenever a fresh run
   * is kicked off, so the tab can refetch immediately instead of
   * waiting for the next poll tick. */
  refreshKey?: number;
}

/**
 * Run history table. REST-only (WS push lives in a follow-up PR) —
 * when any run is ``running`` we poll ``/runs`` on a 3s cadence; the
 * poller stops once everything is terminal.
 */
export function RunHistoryTab({
  workflow,
  client,
  refreshKey = 0,
}: RunHistoryTabProps) {
  const { t } = useTranslation();
  const [runs, setRuns] = useState<WorkflowRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const refresh = useMemo(
    () => async () => {
      setLoading(true);
      try {
        const res = await client.listRuns(workflow.id, 20);
        setRuns(res.items);
        setError(null);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [client, workflow.id],
  );

  useEffect(() => {
    void refresh();
  }, [refresh, refreshKey]);

  // Poll while there is any running run. We keep the interval local
  // so it tears down cleanly on tab change / workflow change.
  useEffect(() => {
    if (!runs) return;
    const hasRunning = runs.some((r) => r.status === "running");
    if (!hasRunning) return;
    const timer = setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [runs, refresh]);

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <section className="space-y-4">
      <header className="flex items-center gap-2">
        <History className="h-5 w-5 text-primary" />
        <h2 className="text-base font-semibold text-foreground">
          {t("workflow.runs.title")}
        </h2>
        <button
          type="button"
          onClick={() => void refresh()}
          className="ml-auto inline-flex items-center gap-1 rounded-lg border border-border/40 bg-muted/30 px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40"
        >
          <RotateCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          {t("workflow.runs.refresh")}
        </button>
      </header>

      {error && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-200">
          {error}
        </div>
      )}

      {runs === null ? (
        <div className="rounded-xl border border-border/40 bg-muted/30 p-6 text-center text-xs text-muted-foreground">
          {t("workflow.runs.loading")}
        </div>
      ) : runs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border/40 bg-muted/20 p-10 text-center text-xs text-muted-foreground">
          {t("workflow.runs.empty")}
        </div>
      ) : (
        <ul className="space-y-2">
          {runs.map((run) => (
            <RunRow
              key={run.id}
              run={run}
              expanded={expanded.has(run.id)}
              onToggle={() => toggle(run.id)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function RunRow({
  run,
  expanded,
  onToggle,
}: {
  run: WorkflowRun;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t, i18n } = useTranslation();
  const startedStr = new Date(run.startedAtMs).toLocaleString(
    i18n.resolvedLanguage || "zh-CN",
  );
  const duration = run.finishedAtMs
    ? run.finishedAtMs - run.startedAtMs
    : Date.now() - run.startedAtMs;

  return (
    <li className="gradient-card rounded-xl border border-[hsl(var(--border))]">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-3 p-3 text-left"
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
        <RunStatusBadge status={run.status} />
        <code className="font-mono text-xs text-muted-foreground">
          {run.id}
        </code>
        <span className="hidden text-xs text-muted-foreground md:inline">
          {t("workflow.runs.startedAt")}: {startedStr}
        </span>
        <span className="ml-auto rounded-full border border-border/40 bg-muted/30 px-2 py-0.5 text-[10px] text-muted-foreground">
          {t(`workflow.runs.trigger.${run.trigger}`)}
        </span>
        <span className="font-mono text-xs text-muted-foreground">
          {formatDuration(duration, t)}
        </span>
      </button>
      {expanded && (
        <div className="space-y-2 border-t border-border/30 p-3">
          {run.error && (
            <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-200">
              {run.error}
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            {t("workflow.runs.stepsTitle")}
          </p>
          <ul className="space-y-1">
            {Object.entries(run.stepResults).map(([stepId, result]) => (
              <StepResultRow key={stepId} stepId={stepId} result={result} />
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

function StepResultRow({
  stepId,
  result,
}: {
  stepId: string;
  result: StepResult;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-lg border border-border/30 bg-background/30 p-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
        )}
        <StepStatusChip status={result.status} />
        <code className="font-mono text-xs text-muted-foreground">
          {stepId}
        </code>
        <span className="ml-auto font-mono text-[11px] text-muted-foreground">
          {result.durationMs} ms
        </span>
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {result.error && (
            <pre className="max-h-40 overflow-auto rounded border border-rose-500/40 bg-rose-500/10 p-2 text-[11px] text-rose-200">
              {result.error}
            </pre>
          )}
          <pre className="max-h-60 overflow-auto rounded border border-border/30 bg-background/60 p-2 text-[11px] text-muted-foreground">
            {safeJson(result.output)}
          </pre>
        </div>
      )}
    </li>
  );
}

// ─── Chips ───────────────────────────────────────────────────────────

function RunStatusBadge({ status }: { status: RunStatus }) {
  const { t } = useTranslation();
  const map: Record<RunStatus, { icon: React.ReactNode; cls: string }> = {
    running: {
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
      cls: "border-primary/40 bg-primary/10 text-primary",
    },
    ok: {
      icon: <CheckCircle2 className="h-3 w-3" />,
      cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
    },
    error: {
      icon: <XCircle className="h-3 w-3" />,
      cls: "border-rose-500/40 bg-rose-500/10 text-rose-300",
    },
    cancelled: {
      icon: <AlertCircle className="h-3 w-3" />,
      cls: "border-border/40 bg-muted/30 text-muted-foreground",
    },
  };
  const m = map[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
        m.cls,
      )}
    >
      {m.icon}
      {t(`workflow.runs.status.${status}`)}
    </span>
  );
}

function StepStatusChip({ status }: { status: StepResult["status"] }) {
  const { t } = useTranslation();
  const tone =
    status === "ok"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
      : status === "error"
        ? "border-rose-500/40 bg-rose-500/10 text-rose-300"
        : status === "skipped"
          ? "border-border/40 bg-muted/30 text-muted-foreground"
          : "border-amber-500/40 bg-amber-500/10 text-amber-300";
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 text-[10px] uppercase",
        tone,
      )}
    >
      {t(`workflow.runs.step.${status}`)}
    </span>
  );
}

function formatDuration(
  ms: number,
  t: ReturnType<typeof useTranslation>["t"],
): string {
  if (ms < 10_000) {
    return t("workflow.runs.durationMsFmt", { ms });
  }
  return t("workflow.runs.durationFmt", {
    seconds: (ms / 1000).toFixed(1),
  });
}

function safeJson(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
