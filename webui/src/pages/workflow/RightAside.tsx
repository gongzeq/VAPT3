import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Sparkles, Workflow as WorkflowIcon, XCircle, Plus } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  WorkflowClient,
  type FailedRunItem,
  type WorkflowTemplate,
} from "@/lib/workflow-client";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { CountBundle } from "@/pages/workflow/LeftFilter";

/** @description Right sidebar with today stats, templates, and empty/loading states. */
export function RightAside({
  counts,
  templates,
  templatesLoading,
  onPickTemplate,
}: {
  counts: CountBundle;
  templates: WorkflowTemplate[];
  templatesLoading: boolean;
  onPickTemplate: (tpl: WorkflowTemplate) => void;
}) {
  const { t } = useTranslation();
  return (
    <aside className="space-y-4">
      <div className="gradient-card space-y-3 rounded-2xl border border-[hsl(var(--border))] p-5">
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-semibold">
            {t("workflow.stats.todayTitle")}
          </h4>
          <span className="text-xs text-muted-foreground">
            {t("workflow.stats.live")}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <MiniStat label={t("workflow.stats.scheduled")} value={counts.scheduled} valueCls="text-primary" />
          <MiniStat label={t("workflow.stats.running")} value={counts.running} valueCls="text-gradient" />
          <MiniStat label={t("workflow.stats.total")} value={counts.all} />
          <MiniStat
            label={t("workflow.stats.failed24h")}
            value={counts.failed24h}
            valueCls={counts.failed24h > 0 ? "text-destructive" : ""}
          />
        </div>
      </div>

      <div className="gradient-card space-y-3 rounded-2xl border border-[hsl(var(--border))] p-5">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <h4 className="text-sm font-semibold">{t("workflow.templates.title")}</h4>
        </div>
        {templatesLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={`tpl-skeleton-${i}`}
                className="h-14 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40"
              />
            ))}
          </div>
        ) : templates.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t("workflow.templates.empty")}</p>
        ) : (
          <div className="space-y-2">
            {templates.slice(0, 4).map((tpl) => (
              <button
                key={tpl.id}
                type="button"
                onClick={() => onPickTemplate(tpl)}
                className="group w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 px-3 py-2.5 text-left text-sm transition hover:border-primary/40 hover:bg-primary/5"
              >
                <div className="flex items-center gap-2 font-medium">
                  <Sparkles className="h-3.5 w-3.5 text-primary" />
                  <span className="truncate">{tpl.name}</span>
                </div>
                {tpl.description && (
                  <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                    {tpl.description}
                  </p>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

function MiniStat({ label, value, valueCls }: { label: string; value: number; valueCls?: string }) {
  return (
    <div className="hover-lift cursor-default rounded-lg bg-[hsl(var(--muted))]/40 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-1 text-2xl font-bold tabular-nums text-foreground", valueCls)}>
        {value}
      </div>
    </div>
  );
}

/** @description Empty state placeholder for the workflow list. */
export function EmptyState({ onCreate }: { onCreate: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border/40 bg-muted/20 py-16">
      <WorkflowIcon className="h-8 w-8 text-muted-foreground" />
      <p className="text-sm text-muted-foreground">{t("workflow.empty")}</p>
      <button
        type="button"
        onClick={onCreate}
        className="gradient-primary inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium text-white shadow-md"
      >
        <Plus className="h-4 w-4" />
        {t("workflow.createNew")}
      </button>
    </div>
  );
}

/** @description Loading skeleton for the workflow card list. */
export function CardListSkeleton() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={`card-skeleton-${i}`}
          className="h-40 animate-pulse rounded-2xl border border-border/40 bg-muted/30"
        />
      ))}
    </div>
  );
}

/** @description Dialog showing failed workflow runs. */
export function FailedRunsDialog({
  open,
  onOpenChange,
  client,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  client: WorkflowClient;
}) {
  const { i18n } = useTranslation();
  const navigate = useNavigate();
  const [items, setItems] = useState<FailedRunItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    client
      .listFailedRuns(50)
      .then((res) => setItems(res.items))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [open, client]);

  const fmtDate = (ms: number) =>
    new Date(ms).toLocaleString(i18n.resolvedLanguage || "zh-CN");

  const fmtDur = (run: FailedRunItem) => {
    if (!run.finishedAtMs) return "—";
    const sec = (run.finishedAtMs - run.startedAtMs) / 1000;
    return sec < 1 ? `${Math.round(sec * 1000)}ms` : `${sec.toFixed(1)}s`;
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>失败历史</DialogTitle>
          <DialogDescription>所有失败的工作流运行记录</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-y-auto">
          {loading ? (
            <div className="py-10 text-center text-xs text-muted-foreground">加载中…</div>
          ) : items.length === 0 ? (
            <div className="py-10 text-center text-xs text-muted-foreground">暂无失败记录</div>
          ) : (
            <ul className="space-y-2">
              {items.map((run) => (
                <li
                  key={run.id}
                  className="rounded-xl border border-border/40 bg-muted/10 p-3 transition-colors hover:bg-muted/20"
                >
                  <div className="flex items-center gap-3">
                    <XCircle className="h-4 w-4 shrink-0 text-destructive" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{run.workflowName}</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {fmtDate(run.startedAtMs)}
                        <span className="mx-1.5">·</span>
                        耗时 {fmtDur(run)}
                        <span className="mx-1.5">·</span>
                        <code className="font-mono text-xs">{run.id}</code>
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        onOpenChange(false);
                        navigate(`/workflows/${run.workflowId}`);
                      }}
                      className="shrink-0 rounded-lg border border-border/40 bg-muted/30 px-2 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                    >
                      查看工作流
                    </button>
                  </div>
                  {run.error && (
                    <div className="mt-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                      {run.error}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
