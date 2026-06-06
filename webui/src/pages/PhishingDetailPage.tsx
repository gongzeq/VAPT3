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

import { useEffect, useState } from "react";
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
  type PhishingHistoryPage,
  type PhishingStats,
  type PhishingTopSenders,
  type PhishingTrend,
} from "@/lib/phishing-client";
import { cn } from "@/lib/utils";
import {
  useTrendOption,
  useRiskPieOption,
  useSenderRankOption,
} from "@/pages/phishing/phishing-chart-options";
import {
  KpiCard,
  DetailRow,
  statusBadgeClass,
  formatPct,
  formatDelta,
  deltaClass,
} from "@/pages/phishing/PhishingDetailTable";

type RangeKey = "7d" | "30d" | "90d";

const PAGE_SIZE = 10;

// ── Component ───────────────────────────────────────────────────────────

/** @description Paginated table and KPI dashboard for phishing email analysis history. */
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
          fetchPhishingTopSenders(token, {
            limit: 8,
            days: range === "7d" ? 7 : range === "30d" ? 30 : 90,
          }),
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
  const avgMs = stats?.avg_duration_ms ?? 0;
  const delta = stats?.delta;

  const totalRows = history?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));

  return (
    <div className="flex h-full w-full flex-col bg-background">
      <Navbar title={t("phishing.detail.title", { defaultValue: "钓鱼邮件检测分析" })} />

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
        <section className="grid grid-cols-2 md:grid-cols-3 gap-4">
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
            valueClass="text-destructive"
            label={`识别为钓鱼 (${formatPct(phishingRate)})`}
            delta={delta ? formatDelta(delta.today_phishing, "raw") : "—"}
            deltaClass={delta ? deltaClass(delta.today_phishing, true) : ""}
            glow
          />
          <KpiCard
            icon="⏱"
            value={avgMs >= 1000 ? `${(avgMs / 1000).toFixed(1)}s` : `${avgMs}ms`}
            label="workflow 平均耗时"
            delta={delta ? formatDelta(delta.avg_duration_ms, "ms") : "—"}
            deltaClass={delta ? deltaClass(delta.avg_duration_ms, true) : ""}
          />
        </section>

        {/* Trend + risk pie */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 rounded-xl border border-border/40 bg-card p-4 overflow-hidden">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-semibold">检测趋势</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  钓鱼 vs 可疑 vs 正常 · 近 {range}
                </p>
              </div>
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-destructive" />
                  钓鱼
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-alert-warning" />
                  可疑
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-alert-success" />
                  正常
                </span>
              </div>
            </div>
            <ReactECharts option={trendOption} opts={{ renderer: "svg" }} className="h-[320px]" />
          </div>

          <div className="rounded-xl border border-border/40 bg-card p-4 overflow-hidden">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-semibold">风险等级分布</h3>
                <p className="text-xs text-muted-foreground mt-0.5">基于 LLM confidence</p>
              </div>
            </div>
            <ReactECharts
              option={riskPieOption}
              opts={{ renderer: "svg" }}
              className="h-[320px]"
            />
          </div>
        </section>

        {/* Top senders + detail table */}
        <section className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          <div className="lg:col-span-2 rounded-xl border border-border/40 bg-card p-4 overflow-hidden">
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
              className="h-[360px]"
            />
          </div>

          <div className="lg:col-span-3 rounded-xl border border-border/40 bg-card p-5">
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
            <div className="overflow-x-auto">
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
                    <th className="text-center py-2 font-medium">可疑度</th>
                    <th className="text-center py-2 font-medium">耗时</th>
                    <th className="text-center py-2 font-medium">AI建议处理</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {(history?.items ?? []).map((row) => (
                    <DetailRow key={row.id} row={row} />
                  ))}
                  {(!history || history.items.length === 0) && (
                    <tr>
                      <td colSpan={6} className="py-6 text-center text-xs text-muted-foreground">
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
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
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
              聚合 postfix / rspamd / workflow / provider / sqlite
            </span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
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
              <div className="col-span-5 text-xs text-muted-foreground py-4 text-center">
                健康数据加载中…
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

export default PhishingDetailPage;
