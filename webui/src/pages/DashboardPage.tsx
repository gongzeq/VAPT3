import { useState } from "react";
import { useTranslation } from "react-i18next";
import ReactECharts from "echarts-for-react";
import { Activity, ArrowRight, TrendingDown, TrendingUp } from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { ActivityEventStream } from "@/components/ActivityEventStream";
import { AssetRiskTopology } from "@/components/dashboard/AssetRiskTopology";
import { PhishingSummaryCard } from "@/components/PhishingSummaryCard";
import { LogAnalysisSummaryCard } from "@/components/LogAnalysisSummaryCard";
import { cn } from "@/lib/utils";
import { kpiCards, recentReports } from "@/data/mock/dashboard";
import {
  ICON_MAP,
  COLOR_MAP,
  STATUS_BADGE,
  SEVERITY_COLOR,
  useRiskTrendOption,
  useAssetPieOption,
  useVulnPieOption,
  useAssetClusterOption,
} from "@/pages/dashboard/dashboard-chart-options";

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
                className="glass-card card-hover-glow rounded-xl p-4 flex flex-col gap-2"
              >
                <div className="flex items-center justify-between">
                  <span className={cn("icon-surface h-8 w-8 rounded-lg", COLOR_MAP[kpi.color])}>
                    <Icon className="h-4 w-4" />
                  </span>
                  {kpi.delta != null && kpi.delta !== 0 && (
                    <span
                      className={cn(
                        "flex items-center gap-0.5 text-[10px] font-medium rounded-full px-1.5 py-0.5",
                        kpi.delta > 0
                          ? "text-alert-success bg-alert-success/10"
                          : "text-destructive bg-destructive/10",
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
                <p className="text-xs text-muted-foreground truncate">{kpi.label}</p>
              </div>
            );
          })}
        </section>

        {/* ── Charts Row: Risk Trend + Pie ── */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Risk Trend — 2/3 */}
          <div className="lg:col-span-2 glass-card rounded-xl p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="section-accent-bar text-sm font-semibold text-foreground">
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
                        ? "gradient-primary text-primary-foreground"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {d}D
                  </button>
                ))}
              </div>
            </div>
            <ReactECharts option={trendOption} opts={{ renderer: "svg" }} className="h-[320px]" />
          </div>

          {/* Pie — 1/3 (toggleable: asset / vuln) */}
          <div className="glass-card rounded-xl p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="section-accent-bar text-sm font-semibold text-foreground">
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
                      ? "gradient-primary text-primary-foreground"
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
                      ? "gradient-primary text-primary-foreground"
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
              className="h-[320px]"
            />
          </div>
        </section>

        {/* ── Asset Cluster + Recent Reports ── */}
        <section className="grid lg:grid-cols-2 gap-6">
          {/* Asset Cluster — bar */}
          <div className="gradient-card rounded-2xl border border-border/60 p-5 animate-fade-in-up">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="section-accent-bar text-base font-semibold">资产聚类</h3>
                <p className="text-xs text-muted-foreground mt-0.5 pl-3">按业务系统 + 风险等级</p>
              </div>
              <button className="text-xs text-primary/80 hover:text-primary inline-flex items-center gap-1 transition-colors duration-200">
                查看全部 <ArrowRight className="h-3 w-3" />
              </button>
            </div>
            <ReactECharts option={clusterOption} opts={{ renderer: "svg" }} className="h-[280px]" />
          </div>

          {/* Recent Reports — table */}
          <div className="gradient-card rounded-2xl border border-border/60 p-5 animate-fade-in-up">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="section-accent-bar text-base font-semibold">历史报告</h3>
                <p className="text-xs text-muted-foreground mt-0.5 pl-3">近 7 天产出</p>
              </div>
              <button className="text-xs text-primary/80 hover:text-primary inline-flex items-center gap-1 transition-colors duration-200">
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
                    <tr key={r.id} className="hover:bg-primary/5 transition-colors duration-150">
                      <td className="py-3">
                        <div className="font-medium text-foreground">{r.title}</div>
                        <div className="text-xs text-muted-foreground font-mono">{r.id}</div>
                      </td>
                      <td className="py-3 text-xs text-muted-foreground">{r.type}</td>
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

        <AssetRiskTopology />

        {/* Live Activity Stream (PR3) — sits at the bottom of the dashboard
            so operators can peek at what agents are doing right now without
            leaving the overview. */}
        <section className="mt-6">
          <ActivityEventStream />
        </section>

        {/* Phishing Email Detection summary — single L1 card linking to
            ``/dashboard/phishing`` (L2). Per PRD §R6 + prototype.html. */}
        <PhishingSummaryCard />

        {/* Log Security Analysis summary — latest result card linking to
            ``/dashboard/log-analysis`` (L2 detail list). */}
        <LogAnalysisSummaryCard />
      </main>
    </div>
  );
}

export default DashboardPage;
