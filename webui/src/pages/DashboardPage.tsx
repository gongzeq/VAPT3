import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactECharts from "echarts-for-react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Server,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { ActivityEventStream } from "@/components/ActivityEventStream";
import { cn } from "@/lib/utils";
import {
  assetCluster,
  assetDistribution,
  kpiCards,
  recentReports,
  riskTrend30,
  riskTrend7,
  riskTrend90,
  vulnDistribution,
  type KpiItem,
  type ReportItem,
  type ReportStatus,
} from "@/data/mock/dashboard";

// ─── Icon map ────────────────────────────────────────────────────────────────

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Server,
  ShieldAlert,
};

const COLOR_MAP: Record<KpiItem["color"], string> = {
  ocean: "text-ocean-500",
  emerald: "text-emerald-400",
  amber: "text-amber-400",
  rose: "text-rose-400",
  violet: "text-violet-400",
  slate: "text-slate-400",
};

const STATUS_BADGE: Record<ReportStatus, string> = {
  已发布: "bg-emerald-500/15 text-emerald-400 border-emerald-500/40",
  待审核: "bg-amber-400/15 text-amber-400 border-amber-400/40",
  编辑中: "bg-primary/15 text-primary border-primary/40",
};

const SEVERITY_COLOR: Record<ReportItem["severity"], string> = {
  critical: "text-rose-400",
  high: "text-orange-400",
  medium: "text-amber-400",
  low: "text-sky-400",
};

// ─── ECharts: Risk Trend ─────────────────────────────────────────────────────

function useRiskTrendOption(days: 7 | 30 | 90) {
  return useMemo(() => {
    const data = days === 7 ? riskTrend7 : days === 30 ? riskTrend30 : riskTrend90;
    const dates = data.map((d) => d.date);
    const makeSeries = (
      name: string,
      key: keyof (typeof data)[0],
      color: string,
    ) => ({
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
        splitLine: { lineStyle: { color: "rgba(51,65,85,0.4)", type: "dashed" as const } },
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

// ─── ECharts: Asset Distribution Pie ─────────────────────────────────────────

function useAssetPieOption() {
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
          itemStyle: { borderRadius: 6, borderColor: "rgba(13,18,30,0.95)", borderWidth: 2 },
          label: { show: true, color: "#cbd5e1", fontSize: 11, formatter: "{b}\n{d}%" },
          labelLine: { length: 8, length2: 8, lineStyle: { color: "#475569" } },
          data: assetDistribution.map((d, i) => ({
            ...d,
            itemStyle: {
              color: [
                "#0ea5e9",
                "#10b981",
                "#8b5cf6",
                "#f97316",
                "#06b6d4",
                "#64748b",
              ][i],
            },
          })),
        },
      ],
    }),
    [],
  );
}

// ─── ECharts: Vulnerability Type Pie ─────────────────────────────────────────

function useVulnPieOption() {
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
          itemStyle: { borderRadius: 6, borderColor: "rgba(13,18,30,0.95)", borderWidth: 2 },
          label: { show: true, color: "#cbd5e1", fontSize: 11, formatter: "{b}\n{d}%" },
          labelLine: { length: 8, length2: 8, lineStyle: { color: "#475569" } },
          data: vulnDistribution.map((d, i) => ({
            ...d,
            itemStyle: {
              color: [
                "#ef4444",
                "#f59e0b",
                "#1E90FF",
                "#06b6d4",
                "#a855f7",
                "#64748b",
              ][i],
            },
          })),
        },
      ],
    }),
    [],
  );
}

// ─── ECharts: Asset Cluster (stacked bar) ────────────────────────────────────

function useAssetClusterOption() {
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
        splitLine: { lineStyle: { color: "rgba(51,65,85,0.4)", type: "dashed" as const } },
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

// ─── Component ───────────────────────────────────────────────────────────────

/**
 * /dashboard — KPI grid + ECharts risk trend (7/30/90D) + vuln type pie +
 * asset cluster stacked bar + recent reports table.
 */
export function DashboardPage() {
  const { t } = useTranslation();
  const [trendDays, setTrendDays] = useState<7 | 30 | 90>(30);
  const [pieMode, setPieMode] = useState<"asset" | "vuln">("asset");

  const trendOption = useRiskTrendOption(trendDays);
  const assetPieOption = useAssetPieOption();
  const vulnPieOption = useVulnPieOption();
  const clusterOption = useAssetClusterOption();

  return (
    <div className="flex h-full w-full flex-col bg-background">
      <Navbar title={t("nav.dashboard", { defaultValue: "安全大屏" })} />

      <main className="container flex-1 overflow-y-auto py-6 space-y-6">
        {/* ── KPI Grid ── */}
        <section className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          {kpiCards.map((kpi) => {
            const Icon = ICON_MAP[kpi.icon] ?? Activity;
            return (
              <div
                key={kpi.label}
                className="hover-lift rounded-xl border border-border/40 bg-card p-4 flex flex-col gap-2"
              >
                <div className="flex items-center justify-between">
                  <Icon className={cn("h-4 w-4", COLOR_MAP[kpi.color])} />
                  {kpi.delta != null && kpi.delta !== 0 && (
                    <span
                      className={cn(
                        "flex items-center gap-0.5 text-[10px] font-medium",
                        kpi.delta > 0
                          ? "text-emerald-400"
                          : "text-rose-400",
                      )}
                    >
                      {kpi.delta > 0 ? (
                        <TrendingUp className="h-3 w-3" />
                      ) : (
                        <TrendingDown className="h-3 w-3" />
                      )}
                      {Math.abs(kpi.delta)}
                    </span>
                  )}
                </div>
                <p className="text-2xl font-bold tracking-tight text-foreground font-mono">
                  {kpi.value}
                </p>
                <p className="text-xs text-muted-foreground truncate">
                  {kpi.label}
                </p>
              </div>
            );
          })}
        </section>

        {/* ── Charts Row: Risk Trend + Pie ── */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Risk Trend — 2/3 */}
          <div className="lg:col-span-2 rounded-xl border border-border/40 bg-card p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-foreground">
                {t("dashboard.riskTrend", { defaultValue: "风险趋势" })} · 近 {trendDays} 天
              </h3>
              <div className="flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-0.5 text-xs">
                {[7, 30, 90].map((d) => (
                  <button
                    key={d}
                    onClick={() => setTrendDays(d as 7 | 30 | 90)}
                    className={cn(
                      "rounded-md px-2.5 py-1 transition-colors",
                      trendDays === d
                        ? "gradient-primary text-white"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {d}D
                  </button>
                ))}
              </div>
            </div>
            <ReactECharts
              option={trendOption}
              opts={{ renderer: "svg" }}
              style={{ height: 320 }}
            />
          </div>

          {/* Pie — 1/3 (toggleable: asset / vuln) */}
          <div className="rounded-xl border border-border/40 bg-card p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-foreground">
                {pieMode === "asset"
                  ? t("dashboard.assetDist", { defaultValue: "资产分布" })
                  : "漏洞类型分布"}
              </h3>
              <div className="flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-0.5 text-xs">
                <button
                  onClick={() => setPieMode("asset")}
                  className={cn(
                    "rounded-md px-2.5 py-1 transition-colors",
                    pieMode === "asset"
                      ? "gradient-primary text-white"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  资产
                </button>
                <button
                  onClick={() => setPieMode("vuln")}
                  className={cn(
                    "rounded-md px-2.5 py-1 transition-colors",
                    pieMode === "vuln"
                      ? "gradient-primary text-white"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  漏洞
                </button>
              </div>
            </div>
            <ReactECharts
              option={pieMode === "asset" ? assetPieOption : vulnPieOption}
              opts={{ renderer: "svg" }}
              style={{ height: 320 }}
            />
          </div>
        </section>

        {/* ── Asset Cluster + Recent Reports ── */}
        <section className="grid lg:grid-cols-2 gap-6">
          {/* Asset Cluster — bar */}
          <div className="gradient-card rounded-2xl border border-border p-5 animate-fade-in-up">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-base font-semibold">资产聚类</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  按业务系统 + 风险等级
                </p>
              </div>
              <button className="text-xs text-primary hover:text-primary-glow inline-flex items-center gap-1 transition-colors">
                查看全部 <ArrowRight className="h-3 w-3" />
              </button>
            </div>
            <ReactECharts
              option={clusterOption}
              opts={{ renderer: "svg" }}
              style={{ height: 280 }}
            />
          </div>

          {/* Recent Reports — table */}
          <div className="gradient-card rounded-2xl border border-border p-5 animate-fade-in-up">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-base font-semibold">历史报告</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  近 7 天产出
                </p>
              </div>
              <button className="text-xs text-primary hover:text-primary-glow inline-flex items-center gap-1 transition-colors">
                查看全部 <ArrowRight className="h-3 w-3" />
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-muted-foreground border-b border-border">
                  <tr>
                    <th className="text-left py-2 font-medium">报告</th>
                    <th className="text-left py-2 font-medium">类型</th>
                    <th className="text-right py-2 font-medium">高危</th>
                    <th className="text-right py-2 font-medium">状态</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {recentReports.map((r) => (
                    <tr
                      key={r.id}
                      className="hover:bg-white/5 transition-colors"
                    >
                      <td className="py-3">
                        <div className="font-medium text-foreground">
                          {r.title}
                        </div>
                        <div className="text-xs text-muted-foreground font-mono">
                          {r.id}
                        </div>
                      </td>
                      <td className="py-3 text-xs text-muted-foreground">
                        {r.type}
                      </td>
                      <td className="py-3 text-right">
                        <span className={cn("font-mono font-medium", SEVERITY_COLOR[r.severity])}>
                          {r.highCount}
                        </span>
                      </td>
                      <td className="py-3 text-right">
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium",
                            STATUS_BADGE[r.status],
                          )}
                        >
                          {r.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* Live Activity Stream (PR3) — sits at the bottom of the dashboard
            so operators can peek at what agents are doing right now without
            leaving the overview. */}
        <section className="mt-6">
          <ActivityEventStream />
        </section>
      </main>
    </div>
  );
}

export default DashboardPage;
