/**
 * Table and KPI sub-components for the phishing detail page.
 *
 * Exports presentational components consumed by `PhishingDetailPage`:
 * - `KpiCard` — single KPI metric card with delta indicator
 * - `DetailRow` — expandable table row for a phishing history item
 * - `RspamdActionBadge` — colour-coded Rspamd action label
 * - `statusBadgeClass` — helper returning Tailwind classes for a status string
 */

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { PhishingHistoryItem } from "@/lib/phishing-client";

// ── Helpers ──────────────────────────────────────────────────────────────

/** @description Format a decimal rate as a percentage string (e.g. 0.123 → "12.3%"). */
export function formatPct(rate: number): string {
  if (!Number.isFinite(rate)) return "0%";
  return `${(rate * 100).toFixed(1)}%`;
}

/** @description Format a numeric delta for display based on its kind (percentage, raw count, or milliseconds). */
export function formatDelta(value: number, kind: "pct" | "raw" | "ms"): string {
  if (!Number.isFinite(value) || value === 0) return "—";
  const sign = value > 0 ? "↑" : "↓";
  const abs = Math.abs(value);
  if (kind === "pct") return `${sign} ${(abs * 100).toFixed(1)}%`;
  if (kind === "ms") return `${sign} ${Math.round(abs)}ms`;
  return `${sign} ${abs}`;
}

/** @description Return a Tailwind colour class indicating whether a delta value is positive or negative. */
export function deltaClass(value: number, goodWhenNegative = false): string {
  if (!Number.isFinite(value) || value === 0) return "text-muted-foreground";
  const isPositive = value > 0;
  if (goodWhenNegative) {
    return isPositive ? "text-destructive" : "text-alert-success";
  }
  return isPositive ? "text-alert-success" : "text-destructive";
}

function actionBadge(action: string): { label: string; cls: string } {
  const a = (action || "").toLowerCase();
  if (a === "reject")
    return {
      label: "REJECT",
      cls: "bg-destructive/15 text-destructive border-destructive/40",
    };
  if (a === "quarantine" || a === "review")
    return {
      label: a.toUpperCase(),
      cls: "bg-alert-warning/15 text-alert-warning border-alert-warning/40",
    };
  if (a === "cached")
    return {
      label: "CACHED",
      cls: "bg-alert-success/15 text-alert-success border-alert-success/40",
    };
  if (a === "accept" || a === "")
    return {
      label: "ACCEPT",
      cls: "bg-alert-success/15 text-alert-success border-alert-success/40",
    };
  return {
    label: action.toUpperCase(),
    cls: "bg-muted/40 text-muted-foreground border-border/40",
  };
}

/** @description Map a status string to Tailwind classes for a coloured badge. */
export function statusBadgeClass(status: string): string {
  const s = (status || "").toLowerCase();
  if (s === "down" || s === "error" || s === "failed")
    return "bg-destructive/15 text-destructive border-destructive/40";
  if (s === "slow" || s === "warn" || s === "degraded")
    return "bg-alert-warning/15 text-alert-warning border-alert-warning/40";
  return "bg-alert-success/15 text-alert-success border-alert-success/40";
}

// ── KPI Card ─────────────────────────────────────────────────────────────

/** @description Single KPI metric card with delta indicator and optional glow effect. */
export function KpiCard({
  icon,
  value,
  valueClass,
  label,
  delta,
  deltaClass: dc,
  glow,
}: {
  icon: string;
  value: string;
  valueClass?: string;
  label: string;
  delta: string;
  deltaClass: string;
  glow?: boolean;
}) {
  return (
    <div
      className={cn(
        "hover-lift rounded-xl border border-border/40 bg-card p-4",
        glow && "shadow-[0_0_12px_rgba(239,68,68,0.4)]",
      )}
    >
      <div className="flex items-center justify-between">
        <span>{icon}</span>
        <span className={cn("text-[10px] font-medium", dc)}>{delta}</span>
      </div>
      <p
        className={cn(
          "text-2xl font-bold font-mono mt-2",
          valueClass ?? "text-foreground",
        )}
      >
        {value}
      </p>
      <p className="text-xs text-muted-foreground mt-1">{label}</p>
    </div>
  );
}

// ── Rspamd badge ─────────────────────────────────────────────────────────

/** @description Colour-coded badge for Rspamd delivery actions (reject, add_header, greylist, accept). */
export function RspamdActionBadge({ action }: { action: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    reject: { label: "拒绝投递", cls: "text-destructive" },
    add_header: { label: "标记为 spam", cls: "text-alert-warning" },
    greylist: { label: "临时拒绝", cls: "text-severity-high" },
    accept: { label: "正常投递", cls: "text-alert-success" },
  };
  const info = map[action] || { label: action, cls: "" };
  return <span className={info.cls}>{info.label}</span>;
}

// ── Detail Row ───────────────────────────────────────────────────────────

/** @description Expandable table row showing a single phishing history item with detail panel. */
export function DetailRow({ row }: { row: PhishingHistoryItem }) {
  const [expanded, setExpanded] = useState(false);
  const conf = Number.isFinite(row.suspicion_level) ? row.suspicion_level : 0;
  const confClass =
    conf > 0.7
      ? "text-destructive"
      : conf > 0.4
        ? "text-alert-warning"
        : "text-alert-success";
  const action = actionBadge(row.action || (row.processed_time_ms === 0 ? "cached" : "accept"));
  const raw = row.created_at || "";
  const date = raw.slice(0, 10);
  const time = raw.length >= 19 ? raw.slice(11, 19) : "";
  const ts = date && time ? `${date} ${time}` : raw;
  const durSec =
    row.processed_time_ms && row.processed_time_ms > 0
      ? `${(row.processed_time_ms / 1000).toFixed(2)}s`
      : "—";
  return (
    <>
      <tr
        className="hover:bg-white/5 transition-colors cursor-pointer text-xs"
        onClick={() => setExpanded((e) => !e)}
        title="点击查看详情"
      >
        <td className="py-2 text-center font-mono text-muted-foreground">{ts}</td>
        <td className="py-2">
          <div className="truncate font-mono text-ocean-300" title={row.sender}>
            {row.sender}
          </div>
        </td>
        <td className="py-2">
          <div className="truncate" title={row.subject}>
            {row.subject}
          </div>
        </td>
        <td className={cn("py-2 text-center font-mono", confClass)}>
          {(conf * 100).toFixed(0)}%
        </td>
        <td className="py-2 text-center font-mono text-muted-foreground">{durSec}</td>
        <td className="py-2 text-center">
          <span
            className={cn("rounded-full px-2 py-0.5 text-[10px] border", action.cls)}
          >
            {action.label}
          </span>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6} className="py-3 px-4 bg-white/[3%]">
            <div className="text-xs text-muted-foreground leading-relaxed space-y-1.5">
              <div>
                <span className="text-foreground font-medium">AI 分析理由：</span>
                {row.reason || "无"}
              </div>
              {row.risk_factors && row.risk_factors.length > 0 && (
                <div>
                  <span className="text-foreground font-medium">可疑特征：</span>
                  {row.risk_factors.join("、")}
                </div>
              )}
              <div className="flex items-center gap-4">
                {row.rspamd_score != null && (
                  <span>
                    <span className="text-foreground font-medium">Rspamd 评分：</span>
                    {row.rspamd_score.toFixed(2)}
                  </span>
                )}
                {row.final_score != null && (
                  <span>
                    <span className="text-foreground font-medium">最终评分：</span>
                    <span
                      className={
                        row.final_score >= 6
                          ? "text-destructive"
                          : row.final_score >= 4
                            ? "text-alert-warning"
                            : ""
                      }
                    >
                      {row.final_score.toFixed(2)}
                    </span>
                  </span>
                )}
                {row.rspamd_action && (
                  <span>
                    <span className="text-foreground font-medium">最终处理：</span>
                    <RspamdActionBadge action={row.rspamd_action} />
                  </span>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
