import { useTranslation } from "react-i18next";
import {
  Clock,
  Layers,
  Pause,
  PlayCircle,
  Plus,
  TriangleAlert,
} from "lucide-react";

import { cn } from "@/lib/utils";

/** @description Filter status for the workflow list sidebar. */
export type StatusFilter = "all" | "scheduled" | "manual" | "running";

/** @description Aggregate counts for the workflow status sidebar. */
export interface CountBundle {
  all: number;
  scheduled: number;
  manual: number;
  running: number;
  runningIds: string[];
  failed24h: number;
}

/** @description Left sidebar filter panel with status rows and tag buttons. */
export function LeftFilter({
  counts,
  statusFilter,
  setStatusFilter,
  tag,
  setTag,
  allTags,
  onCreate,
  onOpenFailedRuns,
}: {
  counts: CountBundle;
  statusFilter: StatusFilter;
  setStatusFilter: (v: StatusFilter) => void;
  tag: string;
  setTag: (v: string) => void;
  allTags: string[];
  onCreate: () => void;
  onOpenFailedRuns: () => void;
}) {
  const { t } = useTranslation();
  return (
    <aside className="gradient-card h-fit space-y-5 rounded-2xl border border-[hsl(var(--border))] p-4">
      <button
        type="button"
        onClick={onCreate}
        className="gradient-primary hover-lift inline-flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-white shadow-md"
      >
        <Plus className="h-4 w-4" />
        {t("workflow.createNew")}
      </button>

      <div>
        <p className="px-2 text-[10px] uppercase tracking-wider text-muted-foreground">
          {t("workflow.filter.statusTitle")}
        </p>
        <ul className="mt-1 space-y-1 text-sm">
          <StatusRow
            active={statusFilter === "all"}
            onClick={() => setStatusFilter("all")}
            icon={<Layers className="h-3.5 w-3.5" />}
            label={t("workflow.filter.statusAll")}
            count={counts.all}
          />
          <StatusRow
            active={statusFilter === "running"}
            onClick={() => setStatusFilter("running")}
            icon={<PlayCircle className="h-3.5 w-3.5 text-alert-success" />}
            label={t("workflow.filter.statusRunning")}
            count={counts.running}
            tone="emerald"
          />
          <StatusRow
            active={statusFilter === "scheduled"}
            onClick={() => setStatusFilter("scheduled")}
            icon={<Clock className="h-3.5 w-3.5 text-primary" />}
            label={t("workflow.filter.statusScheduled")}
            count={counts.scheduled}
          />
          <StatusRow
            active={statusFilter === "manual"}
            onClick={() => setStatusFilter("manual")}
            icon={<Pause className="h-3.5 w-3.5 text-muted-foreground" />}
            label={t("workflow.filter.statusManual", { defaultValue: "未调度" })}
            count={counts.manual}
          />
          <StatusRow
            active={false}
            onClick={onOpenFailedRuns}
            icon={<TriangleAlert className="h-3.5 w-3.5 text-destructive" />}
            label={t("workflow.filter.statusFailed", { defaultValue: "失败历史" })}
            count={counts.failed24h}
            tone="rose"
          />
        </ul>
      </div>

      {allTags.length > 0 && (
        <div>
          <p className="px-2 text-[10px] uppercase tracking-wider text-muted-foreground">
            {t("workflow.filter.tagsTitle")}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5 px-1">
            {allTags.map((x) => {
              const active = tag === x;
              return (
                <button
                  key={x}
                  type="button"
                  onClick={() => setTag(active ? "" : x)}
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-xs transition-colors",
                    active
                      ? "border-primary/40 bg-primary/10 text-primary"
                      : "border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 hover:border-primary/40",
                  )}
                >
                  #{x}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </aside>
  );
}

function StatusRow({
  active,
  onClick,
  icon,
  label,
  count,
  tone,
  disabled,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  count: number;
  tone?: "emerald" | "rose";
  disabled?: boolean;
}) {
  const toneCls =
    tone === "emerald" ? "text-alert-success" : tone === "rose" ? "text-destructive" : "";
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className={cn(
          "flex w-full items-center justify-between rounded-lg px-3 py-2 text-left transition-colors",
          active ? "border border-primary/30 bg-primary/10 text-primary" : "hover:bg-white/5",
          disabled && "cursor-not-allowed opacity-60",
        )}
      >
        <span className={cn("inline-flex items-center gap-2", toneCls)}>
          {icon} {label}
        </span>
        <span className="font-mono text-xs text-muted-foreground">{count}</span>
      </button>
    </li>
  );
}
