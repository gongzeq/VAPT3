import { useEffect, useMemo, useState } from "react";

import { ProgressBar } from "@/components/tremor/progress-bar";
import { cn } from "@/lib/utils";

import { secbotApi, type ScanRecord } from "../api";
import { SeveritySummary } from "../renderers/_shared";

/**
 * Status → (pill tint classes, ProgressBar variant, determinate bool).
 *
 * Tints use semantic state tokens (success / warning / error / muted) so the
 * palette stays on-theme — `sky-500/15`, `emerald-500/15`, etc. are forbidden
 * by `theme-tokens.md §1` (no raw Tailwind palette literals in components).
 * The running state uses an indeterminate 75% fill because we do not yet
 * surface step-level progress from the orchestrator.
 */
const STATUS_META: Record<
  ScanRecord["status"],
  {
    pill: string;
    progress: "default" | "warning" | "error" | "success" | "neutral";
    value: number;
  }
> = {
  running: {
    pill: "bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]",
    progress: "default",
    value: 75,
  },
  succeeded: {
    pill: "bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]",
    progress: "success",
    value: 100,
  },
  failed: {
    pill: "bg-[hsl(var(--error)/0.15)] text-[hsl(var(--error))]",
    progress: "error",
    value: 100,
  },
  cancelled: {
    pill: "bg-muted text-muted-foreground",
    progress: "neutral",
    value: 100,
  },
};

/**
 * Scan history table — chronological list of orchestrator runs.
 * Click a row to open `/scans/:id` (drill-down view) or jump to the
 * latest report download.
 *
 * Ocean-tech styling (PR4-R5):
 *   - Status pill + ProgressBar pair replaces the raw `bg-sky-500/15`
 *     literal — each row now has a one-glance signal for run state and
 *     visual completion.
 *   - Header gets the brand-deep gradient panel like other HUD views.
 *   - Summary tiles show total runs and running/failed counts.
 *
 * NOTE (deferred to PR4 Phase B): the xyflow agent DAG visualization
 * lives in a follow-up PR — requires an agent-graph REST contract and
 * CSS isolation work for `@xyflow/react` that is out of scope here.
 */
export function ScanHistoryView() {
  const [rows, setRows] = useState<ScanRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    secbotApi
      .listScans()
      .then((d) => !cancel && setRows(d))
      .catch((e) => !cancel && setError(String(e)));
    return () => {
      cancel = true;
    };
  }, []);

  const summary = useMemo(() => {
    const r = rows ?? [];
    return {
      total: r.length,
      running: r.filter((s) => s.status === "running").length,
      failed: r.filter((s) => s.status === "failed").length,
    };
  }, [rows]);

  if (error)
    return (
      <div className="p-4 text-[hsl(var(--error))]">加载失败：{error}</div>
    );
  if (!rows) return <div className="p-4 text-text-secondary">加载中…</div>;
  if (rows.length === 0)
    return <div className="p-4 text-text-secondary">尚无扫描记录。</div>;

  return (
    <div className="p-4">
      <header
        className={cn(
          "relative mb-4 overflow-hidden rounded-lg border p-4",
          "border-[hsl(var(--brand-deep)/0.25)] bg-card",
        )}
      >
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "linear-gradient(135deg, hsl(var(--brand-deep) / 0.15) 0%, transparent 50%, hsl(var(--primary) / 0.08) 100%)",
          }}
        />
        <div className="relative z-[1] flex items-baseline justify-between">
          <h1 className="text-lg font-semibold">扫描历史</h1>
          <span className="text-xs text-text-secondary">
            {summary.total} 次扫描 · 运行中 {summary.running} · 失败 {summary.failed}
          </span>
        </div>
      </header>
      <table className="w-full border-collapse text-sm">
        <thead className="text-text-secondary">
          <tr>
            <th className="border-b border-border px-2 py-1.5 text-left">
              Scan ID
            </th>
            <th className="border-b border-border px-2 py-1.5 text-left">状态</th>
            <th className="border-b border-border px-2 py-1.5 text-left">进度</th>
            <th className="border-b border-border px-2 py-1.5 text-left">Agent</th>
            <th className="border-b border-border px-2 py-1.5 text-left">资产</th>
            <th className="border-b border-border px-2 py-1.5 text-left">
              漏洞分布
            </th>
            <th className="border-b border-border px-2 py-1.5 text-left">
              开始时间
            </th>
            <th className="border-b border-border px-2 py-1.5 text-left">
              结束时间
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const meta = STATUS_META[s.status] ?? STATUS_META.cancelled;
            return (
              <tr
                key={s.id}
                className="transition-colors hover:bg-[hsl(var(--brand-light)/0.08)] motion-reduce:transition-none"
              >
                <td className="border-b border-border-subtle px-2 py-1.5 font-mono text-xs">
                  {s.id}
                </td>
                <td className="border-b border-border-subtle px-2 py-1.5">
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[11px] font-medium",
                      meta.pill,
                    )}
                  >
                    {s.status}
                  </span>
                </td>
                <td className="border-b border-border-subtle px-2 py-1.5">
                  <ProgressBar
                    variant={meta.progress}
                    value={meta.value}
                    className="w-24"
                    aria-label={`scan ${s.id} progress`}
                  />
                </td>
                <td className="border-b border-border-subtle px-2 py-1.5">
                  {s.agent}
                </td>
                <td className="border-b border-border-subtle px-2 py-1.5">
                  {s.totals.assets}
                </td>
                <td className="border-b border-border-subtle px-2 py-1.5">
                  <SeveritySummary counts={s.severity_counts} />
                </td>
                <td className="border-b border-border-subtle px-2 py-1.5 text-xs text-text-secondary">
                  {s.started_at}
                </td>
                <td className="border-b border-border-subtle px-2 py-1.5 text-xs text-text-secondary">
                  {s.finished_at ?? "-"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
