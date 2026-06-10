/**
 * ECharts option hooks and presentation constants for the dashboard page.
 *
 * Exports four `useMemo`-based hooks that each return a ready-to-use
 * ECharts option object, plus lookup maps for icons, colours, and badges.
 */

import { useMemo } from "react";
import { Activity, AlertTriangle, Bot, CheckCircle2, Server, ShieldAlert } from "lucide-react";
import {
  assetCluster,
  assetDistribution,
  riskTrend30,
  riskTrend7,
  riskTrend90,
  vulnDistribution,
  type KpiItem,
  type ReportItem,
  type ReportStatus,
} from "@/data/mock/dashboard";

// ─── Icon map ────────────────────────────────────────────────────────────

/** @description Map of icon name strings to Lucide React icon components for KPI cards. */
export const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Server,
  ShieldAlert,
};

/** @description Map of KPI colour tokens to token-driven icon surface classes. */
export const COLOR_MAP: Record<KpiItem["color"], string> = {
  ocean: "icon-surface-brand",
  emerald: "icon-surface-success",
  amber: "icon-surface-warning",
  rose: "icon-surface-danger",
  violet: "icon-surface-brand",
  slate: "icon-surface-muted",
};

/** @description Map of report status labels to Tailwind badge classes. */
export const STATUS_BADGE: Record<ReportStatus, string> = {
  已发布: "bg-emerald-500/15 text-emerald-400 border-emerald-500/40",
  待审核: "bg-amber-400/15 text-amber-400 border-amber-400/40",
  编辑中: "bg-primary/15 text-primary border-primary/40",
};

/** @description Map of severity levels to Tailwind text-colour classes. */
export const SEVERITY_COLOR: Record<ReportItem["severity"], string> = {
  critical: "text-rose-400",
  high: "text-orange-400",
  medium: "text-amber-400",
  low: "text-sky-400",
};

// ─── ECharts: Risk Trend ─────────────────────────────────────────────────

/** Multi-line risk trend chart with area fills for high / medium / low. */
export function useRiskTrendOption(days: 7 | 30 | 90) {
  return useMemo(() => {
    const data = days === 7 ? riskTrend7 : days === 30 ? riskTrend30 : riskTrend90;
    const dates = data.map((d) => d.date);
    const makeSeries = (name: string, key: keyof (typeof data)[0], color: string) => ({
      name,
      type: "line" as const,
      smooth: true,
      symbol: "circle",
      symbolSize: 5,
      lineStyle: { width: 2, color },
      itemStyle: { color },
      areaStyle: {
        color: {
          type: "linear" as const,
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: color + "45" },
            { offset: 1, color: color + "00" },
          ],
        },
      },
      data: data.map((d) => d[key as "critical" | "high" | "medium" | "low"]),
    });

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis" as const,
        backgroundColor: "rgba(15,23,42,0.95)",
        borderColor: "rgba(30,144,255,0.4)",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
      },
      legend: {
        top: 0,
        data: ["高危", "中危", "低危"],
        textStyle: { color: "#94a3b8", fontSize: 11 },
      },
      grid: { top: 36, right: 16, bottom: 24, left: 48 },
      xAxis: {
        type: "category" as const,
        data: dates,
        axisLine: { lineStyle: { color: "#334155" } },
        axisLabel: { color: "#94a3b8", fontSize: 11 },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value" as const,
        axisLine: { show: false },
        splitLine: {
          lineStyle: { color: "rgba(51,65,85,0.4)", type: "dashed" as const },
        },
        axisLabel: { color: "#94a3b8", fontSize: 11 },
      },
      series: [
        makeSeries("高危", "high", "#ef4444"),
        makeSeries("中危", "medium", "#f59e0b"),
        makeSeries("低危", "low", "#1E90FF"),
      ],
    };
  }, [days]);
}

// ─── ECharts: Asset Distribution Pie ─────────────────────────────────────

/** Donut chart showing asset-type distribution. */
export function useAssetPieOption() {
  return useMemo(
    () => ({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item" as const,
        backgroundColor: "rgba(15,23,42,0.95)",
        borderColor: "rgba(30,144,255,0.4)",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
      },
      legend: {
        orient: "vertical" as const,
        right: 0,
        top: "middle",
        textStyle: { color: "#94a3b8", fontSize: 11 },
        itemWidth: 10,
        itemHeight: 10,
      },
      series: [
        {
          type: "pie" as const,
          radius: ["50%", "75%"],
          center: ["38%", "50%"],
          avoidLabelOverlap: true,
          itemStyle: {
            borderRadius: 6,
            borderColor: "rgba(13,18,30,0.95)",
            borderWidth: 2,
          },
          label: { show: true, color: "#cbd5e1", fontSize: 11, formatter: "{b}\n{d}%" },
          labelLine: { length: 8, length2: 8, lineStyle: { color: "#475569" } },
          data: assetDistribution.map((d, i) => ({
            ...d,
            itemStyle: {
              color: ["#0ea5e9", "#10b981", "#8b5cf6", "#f97316", "#06b6d4", "#f59e0b", "#64748b"][
                i
              ],
            },
          })),
        },
      ],
    }),
    [],
  );
}

// ─── ECharts: Vulnerability Type Pie ─────────────────────────────────────

/** Donut chart showing vulnerability-type distribution. */
export function useVulnPieOption() {
  return useMemo(
    () => ({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item" as const,
        backgroundColor: "rgba(15,23,42,0.95)",
        borderColor: "rgba(30,144,255,0.4)",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
      },
      legend: {
        orient: "vertical" as const,
        right: 0,
        top: "middle",
        textStyle: { color: "#94a3b8", fontSize: 11 },
        itemWidth: 10,
        itemHeight: 10,
      },
      series: [
        {
          type: "pie" as const,
          radius: ["50%", "75%"],
          center: ["38%", "50%"],
          avoidLabelOverlap: true,
          itemStyle: {
            borderRadius: 6,
            borderColor: "rgba(13,18,30,0.95)",
            borderWidth: 2,
          },
          label: { show: true, color: "#cbd5e1", fontSize: 11, formatter: "{b}\n{d}%" },
          labelLine: { length: 8, length2: 8, lineStyle: { color: "#475569" } },
          data: vulnDistribution.map((d, i) => ({
            ...d,
            itemStyle: {
              color: ["#ef4444", "#f59e0b", "#1E90FF", "#06b6d4", "#a855f7", "#64748b"][i],
            },
          })),
        },
      ],
    }),
    [],
  );
}

// ─── ECharts: Asset Cluster (stacked bar) ────────────────────────────────

/** Stacked bar chart grouping assets by business system and risk level. */
export function useAssetClusterOption() {
  return useMemo(() => {
    const names = assetCluster.map((d) => d.name);
    const makeSeries = (
      name: string,
      key: keyof (typeof assetCluster)[0],
      color: string,
      borderRadius?: number[],
    ) => ({
      name,
      type: "bar" as const,
      stack: "risk",
      barWidth: "45%",
      itemStyle: { color, borderRadius: borderRadius ?? [0, 0, 0, 0] },
      data: assetCluster.map((d) => d[key as "critical" | "high" | "medium" | "low"]),
    });

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis" as const,
        backgroundColor: "rgba(15,23,42,0.95)",
        borderColor: "rgba(30,144,255,0.4)",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
      },
      legend: {
        top: 0,
        data: ["高危", "中危", "低危"],
        textStyle: { color: "#94a3b8", fontSize: 11 },
      },
      grid: { top: 36, right: 16, bottom: 24, left: 48 },
      xAxis: {
        type: "category" as const,
        data: names,
        axisLine: { lineStyle: { color: "#334155" } },
        axisLabel: { color: "#94a3b8", fontSize: 11 },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value" as const,
        axisLine: { show: false },
        splitLine: {
          lineStyle: { color: "rgba(51,65,85,0.4)", type: "dashed" as const },
        },
        axisLabel: { color: "#94a3b8", fontSize: 11 },
      },
      series: [
        makeSeries("高危", "critical", "#ef4444"),
        makeSeries("中危", "high", "#f59e0b"),
        makeSeries("低危", "low", "#1E90FF", [6, 6, 0, 0]),
      ],
    };
  }, []);
}
