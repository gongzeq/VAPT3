import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import ReactECharts from "echarts-for-react";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronRight,
  Server,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { cn } from "@/lib/utils";
import {
  assetDistribution,
  kpiCards,
  recentReports,
  riskTrend,
  type KpiItem,
  type ReportItem,
} from "@/data/mock/dashboard";

// ─── Icon map (mock "icon" string → component) ──────────────────────────────

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

const SEVERITY_COLOR: Record<ReportItem["severity"], string> = {
  critical: "border-l-rose-500 bg-rose-500/5",
  high: "border-l-orange-400 bg-orange-400/5",
  medium: "border-l-amber-400 bg-amber-400/5",
  low: "border-l-sky-400 bg-sky-400/5",
};

const SEVERITY_BADGE: Record<ReportItem["severity"], string> = {
  critical: "bg-rose-500/20 text-rose-300",
  high: "bg-orange-400/20 text-orange-300",
  medium: "bg-amber-400/20 text-amber-300",
  low: "bg-sky-400/20 text-sky-300",
};

// ─── ECharts Options ─────────────────────────────────────────────────────────

function useRiskTrendOption() {
  return useMemo(() => {
    const dates = riskTrend.map((d) => d.date);
    const makeSeries = (
      name: string,
      key: keyof (typeof riskTrend)[0],
      color: string,
    ) => ({
      name,
      type: "line" as const,
      smooth: true,
      symbol: "circle",
      symbolSize: 6,
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
            { offset: 0, color: color + "40" },
            { offset: 1, color: color + "05" },
          ],
        },
      },
      data: riskTrend.map((d) => d[key]),
    });

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis" as const,
        backgroundColor: "rgba(15,23,42,0.9)",
        borderColor: "#334155",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
      },
      legend: {
        top: 0,
        textStyle: { color: "#94a3b8", fontSize: 11 },
      },
      grid: { top: 36, right: 16, bottom: 24, left: 48 },
      xAxis: {
        type: "category" as const,
        data: dates,
        axisLine: { lineStyle: { color: "#334155" } },
        axisLabel: { color: "#94a3b8", fontSize: 11 },
      },
      yAxis: {
        type: "value" as const,
        splitLine: { lineStyle: { color: "#1e293b" } },
        axisLabel: { color: "#94a3b8", fontSize: 11 },
      },
      series: [
        makeSeries("严重", "critical", "#ef4444"),
        makeSeries("高危", "high", "#f97316"),
        makeSeries("中危", "medium", "#eab308"),
        makeSeries("低危", "low", "#0ea5e9"),
      ],
    };
  }, []);
}

function useAssetPieOption() {
  return useMemo(
    () => ({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item" as const,
        backgroundColor: "rgba(15,23,42,0.9)",
        borderColor: "#334155",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
      },
      legend: {
        orient: "vertical" as const,
        right: 16,
        top: "center",
        textStyle: { color: "#94a3b8", fontSize: 11 },
      },
      series: [
        {
          type: "pie" as const,
          radius: ["40%", "70%"],
          center: ["35%", "50%"],
          avoidLabelOverlap: false,
          label: { show: false },
          emphasis: {
            label: { show: true, fontSize: 13, fontWeight: "bold" as const },
          },
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

// ─── Component ───────────────────────────────────────────────────────────────

/**
 * /dashboard — Template §7.3: KPI grid + ECharts risk trend + asset pie +
 * recent reports list. All data sourced from deterministic mock (PR5).
 */
export function DashboardPage() {
  const { t } = useTranslation();
  const trendOption = useRiskTrendOption();
  const pieOption = useAssetPieOption();

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

        {/* ── Charts Row ── */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Risk Trend — 2/3 width */}
          <div className="lg:col-span-2 rounded-xl border border-border/40 bg-card p-4">
            <h3 className="mb-2 text-sm font-semibold text-foreground">
              {t("dashboard.riskTrend", { defaultValue: "风险趋势（近 7 日）" })}
            </h3>
            <ReactECharts
              option={trendOption}
              opts={{ renderer: "svg" }}
              style={{ height: 320 }}
            />
          </div>

          {/* Asset Pie — 1/3 width */}
          <div className="rounded-xl border border-border/40 bg-card p-4">
            <h3 className="mb-2 text-sm font-semibold text-foreground">
              {t("dashboard.assetDist", { defaultValue: "资产分布" })}
            </h3>
            <ReactECharts
              option={pieOption}
              opts={{ renderer: "svg" }}
              style={{ height: 320 }}
            />
          </div>
        </section>

        {/* ── Recent Reports ── */}
        <section className="rounded-xl border border-border/40 bg-card p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-foreground">
              {t("dashboard.recentReports", { defaultValue: "最近报告" })}
            </h3>
            <button className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
              {t("dashboard.viewAll", { defaultValue: "查看全部" })}
              <ChevronRight className="h-3 w-3" />
            </button>
          </div>
          <div className="space-y-2">
            {recentReports.map((r) => (
              <div
                key={r.id}
                className={cn(
                  "flex items-center justify-between rounded-lg border-l-4 p-3 transition-colors hover:bg-accent/30",
                  SEVERITY_COLOR[r.severity],
                )}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-foreground">
                    {r.title}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {r.target} · {r.timestamp}
                  </p>
                </div>
                <span
                  className={cn(
                    "ml-3 shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
                    SEVERITY_BADGE[r.severity],
                  )}
                >
                  {r.severity}
                </span>
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

export default DashboardPage;
