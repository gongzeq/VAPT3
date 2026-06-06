/**
 * ECharts option hooks for the phishing detail page charts.
 *
 * Exports three `useMemo`-based hooks that each return a ready-to-use
 * ECharts option object consumed by `<ReactECharts option={…} />`.
 */

import { useMemo } from "react";
import type {
  PhishingHistoryItem,
  PhishingTopSenders,
  PhishingTrend,
} from "@/lib/phishing-client";

/** Stacked-bar trend chart with a phishing-rate line overlay. */
export function useTrendOption(trend: PhishingTrend | null) {
  return useMemo(() => {
    const buckets = trend?.buckets ?? [];
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis" as const,
        backgroundColor: "rgba(15,23,42,0.95)",
        borderColor: "rgba(30,144,255,0.4)",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
      },
      legend: { show: false },
      grid: { left: 36, right: 16, top: 16, bottom: 32 },
      xAxis: {
        type: "category" as const,
        data: buckets.map((b) => b.date.slice(5)),
        axisLine: { lineStyle: { color: "#334155" } },
        axisLabel: { color: "#94a3b8", fontSize: 11 },
      },
      yAxis: [
        {
          type: "value" as const,
          splitLine: { lineStyle: { color: "rgba(148,163,184,0.08)" } },
          axisLabel: { color: "#94a3b8", fontSize: 11 },
        },
        {
          type: "value" as const,
          splitLine: { show: false },
          axisLabel: {
            color: "#94a3b8",
            fontSize: 11,
            formatter: (v: number) => `${(v * 100).toFixed(1)}%`,
          },
        },
      ],
      series: [
        {
          name: "正常",
          type: "bar",
          stack: "mail",
          barWidth: 24,
          itemStyle: { color: "#10b981", borderRadius: [0, 0, 4, 4] },
          data: buckets.map((b) => b.normal),
        },
        {
          name: "可疑",
          type: "bar",
          stack: "mail",
          itemStyle: { color: "#f59e0b" },
          data: buckets.map((b) => b.suspicious),
        },
        {
          name: "钓鱼",
          type: "bar",
          stack: "mail",
          itemStyle: { color: "#ef4444", borderRadius: [4, 4, 0, 0] },
          data: buckets.map((b) => b.phishing),
        },
        {
          name: "钓鱼率",
          type: "line",
          yAxisIndex: 1,
          smooth: true,
          symbol: "circle",
          symbolSize: 6,
          lineStyle: { color: "#1E90FF", width: 2 },
          itemStyle: { color: "#1E90FF", borderColor: "#fff", borderWidth: 2 },
          data: buckets.map((b) => b.rate),
        },
      ],
    };
  }, [trend]);
}

/** Donut chart bucketing history items by suspicion confidence level. */
export function useRiskPieOption(items: PhishingHistoryItem[]) {
  return useMemo(() => {
    let high = 0;
    let mid = 0;
    let low = 0;
    let normal = 0;
    items.forEach((it) => {
      const s = Number.isFinite(it.suspicion_level) ? it.suspicion_level : 0;
      if (s >= 0.7) high += 1;
      else if (s >= 0.4) mid += 1;
      else if (s >= 0.2) low += 1;
      else normal += 1;
    });
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item" as const,
        backgroundColor: "rgba(15,23,42,0.95)",
        borderColor: "rgba(30,144,255,0.4)",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
      },
      legend: {
        bottom: 0,
        left: "center",
        textStyle: { color: "#94a3b8", fontSize: 11 },
        icon: "circle",
      },
      series: [
        {
          type: "pie" as const,
          radius: ["52%", "78%"],
          center: ["50%", "46%"],
          itemStyle: { borderColor: "#0a0e1a", borderWidth: 2 },
          label: { show: false },
          labelLine: { show: false },
          data: [
            { value: high, name: "高 (>0.7)", itemStyle: { color: "#ef4444" } },
            { value: mid, name: "中 (0.4-0.7)", itemStyle: { color: "#f59e0b" } },
            { value: low, name: "低 (<0.4)", itemStyle: { color: "#a855f7" } },
            { value: normal, name: "正常", itemStyle: { color: "#10b981" } },
          ],
        },
      ],
    };
  }, [items]);
}

/** Horizontal bar chart ranking the top phishing senders. */
export function useSenderRankOption(senders: PhishingTopSenders | null) {
  return useMemo(() => {
    const items = senders?.items ?? [];
    const ordered = [...items].reverse();
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis" as const,
        axisPointer: { type: "shadow" as const },
        backgroundColor: "rgba(15,23,42,0.95)",
        borderColor: "rgba(30,144,255,0.4)",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
      },
      grid: { left: 160, right: 32, top: 8, bottom: 8 },
      xAxis: {
        type: "value" as const,
        splitLine: { lineStyle: { color: "rgba(148,163,184,0.08)" } },
        axisLabel: { color: "#94a3b8", fontSize: 11 },
      },
      yAxis: {
        type: "category" as const,
        data: ordered.map((s) => s.sender),
        axisLine: { lineStyle: { color: "#334155" } },
        axisLabel: { color: "#cbd5e1", fontSize: 11 },
      },
      series: [
        {
          type: "bar" as const,
          data: ordered.map((s) => s.phishing),
          barWidth: 16,
          itemStyle: {
            color: {
              type: "linear" as const,
              x: 0,
              y: 0,
              x2: 1,
              y2: 0,
              colorStops: [
                { offset: 0, color: "#ef4444" },
                { offset: 1, color: "#f59e0b" },
              ],
            },
            borderRadius: [0, 4, 4, 0],
          },
          label: {
            show: true,
            position: "right",
            color: "#94a3b8",
            fontSize: 11,
          },
        },
      ],
    };
  }, [senders]);
}
