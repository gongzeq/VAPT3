/**
 * L1 phishing summary card mounted on the main DashboardPage.
 *
 * Spec: PRD §R6 + .trellis/tasks/05-13-phishing-email-workflow/prototype.html
 * (the "概要卡" view). The card is a single horizontal block: hero metric →
 * 7-day sparkline → 3 secondary metrics → health badge. Clicking anywhere
 * on the card navigates to ``/dashboard/phishing`` (L2 detail).
 *
 * Resilience:
 *   - Loading: render skeleton placeholders (no spinner, prevents layout
 *     thrash on the otherwise-stable dashboard).
 *   - Network/server failure: show a muted "数据暂不可用" line; do NOT
 *     surface the dashboard-level error toast — phishing is a sub-section.
 *   - Empty DB (today_total == 0): keep the card visible with zeroed
 *     numbers so the operator knows the workflow exists.
 */

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import ReactECharts from "echarts-for-react";
import { useClient } from "@/providers/ClientProvider";
import {
  fetchPhishingHealth,
  fetchPhishingSummary,
  type PhishingHealth,
  type PhishingSummary,
} from "@/lib/phishing-client";

function formatRate(rate: number): string {
  if (!Number.isFinite(rate) || rate <= 0) return "0%";
  return `${(rate * 100).toFixed(1)}%`;
}

function formatMs(ms: number): string {
  if (!ms) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function healthBadge(health: PhishingHealth | null): {
  label: string;
  cls: string;
} {
  if (!health) {
    return {
      label: "—",
      cls: "border border-border/40 text-muted-foreground bg-white/5",
    };
  }
  const statuses = health.components.map((c) => (c.status || "").toLowerCase());
  const hasDown = statuses.some((s) => s === "down" || s === "error" || s === "failed");
  const hasSlow = statuses.some((s) => s === "slow" || s === "warn" || s === "degraded");
  if (hasDown) {
    return {
      label: "链路异常",
      cls: "bg-rose-500/15 text-rose-300 border border-rose-500/40",
    };
  }
  if (hasSlow) {
    return {
      label: "链路降级",
      cls: "bg-amber-400/15 text-amber-300 border border-amber-400/40",
    };
  }
  return {
    label: "链路正常",
    cls: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/40",
  };
}

export function PhishingSummaryCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { token } = useClient();
  const [summary, setSummary] = useState<PhishingSummary | null>(null);
  const [health, setHealth] = useState<PhishingHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [s, h] = await Promise.all([
          fetchPhishingSummary(token),
          fetchPhishingHealth(token),
        ]);
        if (cancelled) return;
        setSummary(s);
        setHealth(h);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError((e as Error).message || "fetch failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const sparkOption = useMemo(() => {
    const points = summary?.spark_7d ?? [];
    return {
      backgroundColor: "transparent",
      grid: { left: 0, right: 0, top: 4, bottom: 4 },
      xAxis: {
        type: "category" as const,
        show: false,
        data: points.map((p) => p.date),
      },
      yAxis: { type: "value" as const, show: false },
      tooltip: {
        trigger: "axis" as const,
        backgroundColor: "rgba(15,23,42,0.95)",
        borderColor: "rgba(30,144,255,0.4)",
        textStyle: { color: "#e2e8f0", fontSize: 11 },
      },
      series: [
        {
          type: "line" as const,
          smooth: true,
          symbol: "circle",
          symbolSize: 4,
          data: points.map((p) => p.phishing),
          lineStyle: { color: "#ef4444", width: 2 },
          itemStyle: { color: "#ef4444" },
          areaStyle: {
            color: {
              type: "linear" as const,
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(239,68,68,0.35)" },
                { offset: 1, color: "rgba(239,68,68,0)" },
              ],
            },
          },
        },
      ],
    };
  }, [summary]);

  const phishingRate =
    summary && summary.today_total > 0
      ? (summary.today_phishing / summary.today_total) * 100
      : 0;

  const badge = healthBadge(health);
  const todayPhishing = summary?.today_phishing ?? 0;
  const todayTotal = summary?.today_total ?? 0;
  const cacheRate = summary?.cache_hit_rate ?? 0;
  const avgMs = summary?.avg_duration_ms ?? 0;

  return (
    <section>
      <div className="flex items-center gap-3 mb-3">
        <div className="w-1 h-5 rounded-full bg-gradient-to-b from-ocean-500 to-violet-500" />
        <h2 className="text-base font-semibold">
          {t("phishing.title", { defaultValue: "钓鱼邮件检测" })}
        </h2>
        <span className="text-xs text-muted-foreground">
          phishing-email workflow
        </span>
      </div>

      <button
        type="button"
        onClick={() => navigate("/dashboard/phishing")}
        className="w-full text-left rounded-xl border border-border/40 bg-card hover:border-ocean-500/50 hover-lift p-5 grid grid-cols-1 lg:grid-cols-12 gap-4 items-center transition-colors"
      >
        {/* Hero metric */}
        <div className="lg:col-span-3 flex items-center gap-4">
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center text-2xl"
            style={{
              background: "rgba(239,68,68,0.15)",
              border: "1px solid rgba(239,68,68,0.3)",
            }}
          >
            🎣
          </div>
          <div>
            <p className="text-3xl font-bold tracking-tight font-mono text-rose-400">
              {todayPhishing}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {t("phishing.summary.today_phishing", {
                defaultValue: "今日识别钓鱼",
              })}
            </p>
          </div>
        </div>

        {/* Sparkline */}
        <div className="lg:col-span-4">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-muted-foreground">
              {t("phishing.summary.trend_7d", {
                defaultValue: "近 7 天检测趋势",
              })}
            </span>
            <span className="text-xs text-muted-foreground">
              {t("phishing.summary.rate", { defaultValue: "钓鱼率" })}{" "}
              {phishingRate.toFixed(2)}%
            </span>
          </div>
          <div style={{ height: 56 }}>
            <ReactECharts
              option={sparkOption}
              style={{ height: "100%", width: "100%" }}
              opts={{ renderer: "svg" }}
            />
          </div>
        </div>

        {/* Secondary metrics */}
        <div className="lg:col-span-4 grid grid-cols-3 gap-3 text-sm">
          <div>
            <p className="text-lg font-mono font-semibold">{todayTotal}</p>
            <p className="text-[11px] text-muted-foreground">
              {t("phishing.summary.today_total", { defaultValue: "今日总数" })}
            </p>
          </div>
          <div>
            <p className="text-lg font-mono font-semibold text-amber-400">
              {formatRate(cacheRate)}
            </p>
            <p className="text-[11px] text-muted-foreground">
              {t("phishing.summary.cache_hit", {
                defaultValue: "缓存命中率",
              })}
            </p>
          </div>
          <div>
            <p className="text-lg font-mono font-semibold">{formatMs(avgMs)}</p>
            <p className="text-[11px] text-muted-foreground">
              {t("phishing.summary.avg_duration", {
                defaultValue: "平均耗时",
              })}
            </p>
          </div>
        </div>

        {/* Status / arrow */}
        <div className="lg:col-span-1 flex items-center justify-end gap-2">
          <span className={`rounded-full px-2 py-0.5 text-[10px] ${badge.cls}`}>
            {badge.label}
          </span>
          <span className="text-ocean-400 text-sm">→</span>
        </div>
      </button>

      <p className="text-[11px] text-muted-foreground mt-2 text-right">
        {error
          ? t("phishing.summary.unavailable", {
              defaultValue: "数据暂不可用",
            })
          : t("phishing.summary.click_to_detail", {
              defaultValue: "点击卡片查看详情 →",
            })}
      </p>
    </section>
  );
}
