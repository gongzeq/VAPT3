/**
 * /dashboard/phishing — L2 detail page for the phishing-email workflow.
 *
 * Spec: PRD §R6 + .trellis/tasks/05-13-phishing-email-workflow/prototype.html
 * (the "详情页" view). Layout, in render order:
 *   1. Breadcrumb + back-button + range tabs
 *   2. KPI×4 (today total / phishing / cache hit / avg duration) with delta
 *   3. Trend stacked bar (phishing/suspicious/normal) + rate line
 *   4. Risk pie (confidence buckets derived from history)
 *   5. Top senders horizontal bar + paginated detail table
 *   6. Link health card
 *
 * All data flows through :mod:`@/lib/phishing-client`. Each section
 * degrades to its own empty-state when the underlying request fails.
 */

import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import ReactECharts from "echarts-for-react";
import { Navbar } from "@/components/Navbar";
import { useClient } from "@/providers/ClientProvider";
import {
  fetchPhishingHealth,
  fetchPhishingHistory,
  fetchPhishingStats,
  fetchPhishingTopSenders,
  fetchPhishingTrend,
  type PhishingFilter,
  type PhishingHealth,
  type PhishingHistoryItem,
  type PhishingHistoryPage,
  type PhishingStats,
  type PhishingTopSenders,
  type PhishingTrend,
} from "@/lib/phishing-client";
import { cn } from "@/lib/utils";

type RangeKey = "7d" | "30d" | "90d";

const PAGE_SIZE = 10;

function formatPct(rate: number): string {
  if (!Number.isFinite(rate)) return "0%";
  return `${(rate * 100).toFixed(1)}%`;
}

function formatDelta(value: number, kind: "pct" | "raw" | "ms"): string {
  if (!Number.isFinite(value) || value === 0) return "—";
  const sign = value > 0 ? "↑" : "↓";
  const abs = Math.abs(value);
  if (kind === "pct") return `${sign} ${(abs * 100).toFixed(1)}%`;
  if (kind === "ms") return `${sign} ${Math.round(abs)}ms`;
  return `${sign} ${abs}`;
}

function deltaClass(value: number, goodWhenNegative = false): string {
  if (!Number.isFinite(value) || value === 0) return "text-muted-foreground";
  const isPositive = value > 0;
  if (goodWhenNegative) {
    return isPositive ? "text-rose-400" : "text-emerald-400";
  }
  return isPositive ? "text-emerald-400" : "text-rose-400";
}

function actionBadge(action: string): { label: string; cls: string } {
  const a = (action || "").toLowerCase();
  if (a === "reject")
    return {
      label: "REJECT",
      cls: "bg-rose-500/15 text-rose-300 border-rose-500/40",
    };
  if (a === "quarantine" || a === "review")
    return {
      label: a.toUpperCase(),
      cls: "bg-amber-400/15 text-amber-300 border-amber-400/40",
    };
  if (a === "cached")
    return {
      label: "CACHED",
      cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
    };
  if (a === "accept" || a === "" )
    return {
      label: "ACCEPT",
      cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
    };
  return {
    label: action.toUpperCase(),
    cls: "bg-white/5 text-muted-foreground border-border/40",
  };
}

function statusBadgeClass(status: string): string {
  const s = (status || "").toLowerCase();
  if (s === "down" || s === "error" || s === "failed")
    return "bg-rose-500/15 text-rose-300 border-rose-500/40";
  if (s === "slow" || s === "warn" || s === "degraded")
    return "bg-amber-400/15 text-amber-300 border-amber-400/40";
  return "bg-emerald-500/15 text-emerald-300 border-emerald-500/40";
}

// ── ECharts options ─────────────────────────────────────────────────────

function useTrendOption(trend: PhishingTrend | null) {
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

function useRiskPieOption(items: PhishingHistoryItem[]) {
  return useMemo(() => {
    let high = 0;
    let mid = 0;
    let low = 0;
    let normal = 0;
    items.forEach((it) => {
      if (!it.is_phishing) {
        normal += 1;
        return;
      }
      if (it.confidence > 0.7) high += 1;
      else if (it.confidence > 0.4) mid += 1;
      else low += 1;
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

function useSenderRankOption(senders: PhishingTopSenders | null) {
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

// ── Component ───────────────────────────────────────────────────────────

export function PhishingDetailPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { token } = useClient();

  const [range, setRange] = useState<RangeKey>("7d");
  const [stats, setStats] = useState<PhishingStats | null>(null);
  const [trend, setTrend] = useState<PhishingTrend | null>(null);
  const [topSenders, setTopSenders] = useState<PhishingTopSenders | null>(null);
  const [history, setHistory] = useState<PhishingHistoryPage | null>(null);
  const [health, setHealth] = useState<PhishingHealth | null>(null);

  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<PhishingFilter>("all");

  // KPI + range-driven data
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [s, tr, ts, h] = await Promise.all([
          fetchPhishingStats(token),
          fetchPhishingTrend(token, range),
          fetchPhishingTopSenders(
            token,
            { limit: 8, days: range === "7d" ? 7 : range === "30d" ? 30 : 90 },
          ),
          fetchPhishingHealth(token),
        ]);
        if (cancelled) return;
        setStats(s);
        setTrend(tr);
        setTopSenders(ts);
        setHealth(h);
      } catch {
        // Each card already has an empty-state — silent fallthrough.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, range]);

  // History (paginated, search/filter-driven)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchPhishingHistory(token, {
          page,
          pageSize: PAGE_SIZE,
          search: search || undefined,
          filter,
        });
        if (cancelled) return;
        setHistory(data);
      } catch {
        if (cancelled) return;
        setHistory({ items: [], total: 0, page, page_size: PAGE_SIZE });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, page, search, filter]);

  const trendOption = useTrendOption(trend);
  const riskPieOption = useRiskPieOption(history?.items ?? []);
  const senderOption = useSenderRankOption(topSenders);

  const todayTotal = stats?.today_total ?? 0;
  const todayPhishing = stats?.today_phishing ?? 0;
  const phishingRate = stats?.today_phishing_rate ?? 0;
  const cacheRate = stats?.cache_hit_rate ?? 0;
  const avgMs = stats?.avg_duration_ms ?? 0;
  const delta = stats?.delta;

  const totalRows = history?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));

  return (
    <div className="flex h-full w-full flex-col bg-background">
      <Navbar
        title={t("phishing.detail.title", { defaultValue: "钓鱼邮件检测分析" })}
      />

      <main className="container flex-1 overflow-y-auto py-6 space-y-6 max-w-[1400px]">
        {/* Breadcrumb + range tabs */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            <button
              onClick={() => navigate("/dashboard")}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              {t("nav.dashboard", { defaultValue: "大屏分析" })}
            </button>
            <span className="text-muted-foreground">/</span>
            <span>钓鱼邮件检测</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-0.5 text-xs">
              {(["7d", "30d", "90d"] as RangeKey[]).map((r) => (
                <button
                  key={r}
                  onClick={() => setRange(r)}
                  className={cn(
                    "rounded-md px-2.5 py-1 transition-colors",
                    range === r
                      ? "gradient-primary text-white"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {r}
                </button>
              ))}
            </div>
            <button
              onClick={() => navigate("/dashboard")}
              className="text-xs text-muted-foreground hover:text-foreground border border-border rounded-lg px-3 py-1.5"
            >
              ← 返回大屏
            </button>
          </div>
        </div>

        {/* KPI×4 */}
        <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <KpiCard
            icon="📧"
            value={todayTotal.toLocaleString()}
            label="今日检测邮件总数"
            delta={delta ? formatDelta(delta.today_total_pct, "pct") : "—"}
            deltaClass={delta ? deltaClass(delta.today_total_pct) : ""}
          />
          <KpiCard
            icon="🎣"
            value={todayPhishing.toLocaleString()}
            valueClass="text-rose-400"
            label={`识别为钓鱼 (${formatPct(phishingRate)})`}
            delta={delta ? formatDelta(delta.today_phishing, "raw") : "—"}
            deltaClass={delta ? deltaClass(delta.today_phishing, true) : ""}
            glow
          />
          <KpiCard
            icon="⚡"
            value={formatPct(cacheRate)}
            label="Redis 缓存命中率"
            delta={delta ? formatDelta(delta.cache_hit_pct, "pct") : "—"}
            deltaClass={delta ? deltaClass(delta.cache_hit_pct) : ""}
          />
          <KpiCard
            icon="⏱"
            value={
              avgMs >= 1000
                ? `${(avgMs / 1000).toFixed(1)}s`
                : `${avgMs}ms`
            }
            label="workflow 平均耗时"
            delta={delta ? formatDelta(delta.avg_duration_ms, "ms") : "—"}
            deltaClass={delta ? deltaClass(delta.avg_duration_ms, true) : ""}
          />
        </section>

        {/* Trend + risk pie */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 rounded-xl border border-border/40 bg-card p-4">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-semibold">检测趋势</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  钓鱼 vs 可疑 vs 正常 · 近 {range}
                </p>
              </div>
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-rose-400" />钓鱼
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-amber-400" />可疑
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-emerald-400" />正常
                </span>
              </div>
            </div>
            <ReactECharts
              option={trendOption}
              opts={{ renderer: "svg" }}
              style={{ height: 320 }}
            />
          </div>

          <div className="rounded-xl border border-border/40 bg-card p-4">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-semibold">风险等级分布</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  基于 LLM confidence
                </p>
              </div>
            </div>
            <ReactECharts
              option={riskPieOption}
              opts={{ renderer: "svg" }}
              style={{ height: 320 }}
            />
          </div>
        </section>

        {/* Top senders + detail table */}
        <section className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          <div className="lg:col-span-2 rounded-xl border border-border/40 bg-card p-4">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-semibold">高危发件人 Top 8</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  近 {range} 累计钓鱼次数
                </p>
              </div>
            </div>
            <ReactECharts
              option={senderOption}
              opts={{ renderer: "svg" }}
              style={{ height: 360 }}
            />
          </div>

          <div className="lg:col-span-3 rounded-xl border border-border/40 bg-card p-4">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-semibold">检测明细</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  来自 SQLite detection_results 表
                </p>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <input
                  type="text"
                  placeholder="搜索发件人 / 主题..."
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      setPage(1);
                      setSearch(searchInput.trim());
                    }
                  }}
                  className="bg-white/5 border border-border rounded-lg px-3 py-1.5 text-xs w-48 outline-none focus:border-ocean-500"
                />
                <select
                  value={filter}
                  onChange={(e) => {
                    setPage(1);
                    setFilter(e.target.value as PhishingFilter);
                  }}
                  className="bg-white/5 border border-border rounded-lg px-2 py-1.5 text-xs text-muted-foreground"
                >
                  <option value="all">全部</option>
                  <option value="phishing">仅钓鱼</option>
                  <option value="suspicious">仅可疑</option>
                  <option value="normal">仅正常</option>
                </select>
              </div>
            </div>
            <div>
              <table className="w-full table-fixed">
                <colgroup>
                  <col className="w-[170px]" />
                  <col className="w-[24%]" />
                  <col />
                  <col className="w-[80px]" />
                  <col className="w-[80px]" />
                  <col className="w-[96px]" />
                </colgroup>
                <thead className="border-b border-border text-xs uppercase text-muted-foreground">
                  <tr>
                    <th className="text-center py-2 font-medium">时间</th>
                    <th className="text-left py-2 font-medium">发件人</th>
                    <th className="text-left py-2 font-medium">主题</th>
                    <th className="text-center py-2 font-medium">置信度</th>
                    <th className="text-center py-2 font-medium">耗时</th>
                    <th className="text-center py-2 font-medium">动作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {(history?.items ?? []).map((row) => (
                    <DetailRow key={row.id} row={row} />
                  ))}
                  {(!history || history.items.length === 0) && (
                    <tr>
                      <td
                        colSpan={6}
                        className="py-6 text-center text-xs text-muted-foreground"
                      >
                        暂无数据
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
              <span>共 {totalRows.toLocaleString()} 条记录</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="border border-border rounded-md px-2 py-1 hover:text-foreground disabled:opacity-40"
                >
                  ‹
                </button>
                <span>
                  {page} / {totalPages}
                </span>
                <button
                  onClick={() =>
                    setPage((p) => Math.min(totalPages, p + 1))
                  }
                  disabled={page >= totalPages}
                  className="border border-border rounded-md px-2 py-1 hover:text-foreground disabled:opacity-40"
                >
                  ›
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* Health card */}
        <section className="rounded-xl border border-border/40 bg-card p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">链路健康</h3>
            <span className="text-xs text-muted-foreground">
              聚合 postfix / rspamd / workflow / provider / redis / sqlite
            </span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3 text-sm">
            {(health?.components ?? []).map((c) => (
              <div
                key={c.name}
                className="border border-border/40 rounded-lg p-3 flex items-center justify-between"
              >
                <span className="text-xs text-muted-foreground">{c.name}</span>
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[10px] border",
                    statusBadgeClass(c.status),
                  )}
                >
                  {(c.status || "—").toUpperCase()}
                </span>
              </div>
            ))}
            {!health && (
              <div className="col-span-6 text-xs text-muted-foreground py-4 text-center">
                健康数据加载中…
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

function KpiCard({
  icon,
  value,
  valueClass,
  label,
  delta,
  deltaClass,
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
        <span className={cn("text-[10px] font-medium", deltaClass)}>
          {delta}
        </span>
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

function DetailRow({ row }: { row: PhishingHistoryItem }) {
  const conf = row.confidence;
  const confClass =
    conf > 0.7
      ? "text-rose-400"
      : conf > 0.4
        ? "text-amber-400"
        : "text-emerald-400";
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
    <tr className="hover:bg-white/5 transition-colors">
      <td className="py-2.5 text-center font-mono text-muted-foreground">{ts}</td>
      <td className="py-2.5">
        <div className="truncate font-mono text-violet-400" title={row.sender}>
          {row.sender}
        </div>
      </td>
      <td className="py-2.5">
        <div className="truncate" title={row.subject}>
          {row.subject}
        </div>
      </td>
      <td className={cn("py-2.5 text-center font-mono", confClass)}>
        {(conf * 100).toFixed(0)}%
      </td>
      <td className="py-2.5 text-center font-mono text-muted-foreground">
        {durSec}
      </td>
      <td className="py-2.5 text-center">
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-[10px] border",
            action.cls,
          )}
        >
          {action.label}
        </span>
      </td>
    </tr>
  );
}

export default PhishingDetailPage;
