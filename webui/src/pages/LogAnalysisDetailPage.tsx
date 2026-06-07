/**
 * /dashboard/log-analysis — L2 detail page for the log-analysis workflow.
 *
 * Card-based layout: each analysis record gets its own card with an
 * individual donut chart. Click the chart area to expand and see the
 * full analysis detail (risk factors, anomaly entries, LLM reasoning).
 */

import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  ChevronDown,
  ChevronUp,
  ShieldAlert,
  ShieldCheck,
  FileText,
  Hash,
  Activity,
  AlertTriangle,
} from "lucide-react";
import ReactECharts from "echarts-for-react";
import { Navbar } from "@/components/Navbar";
import { useClient } from "@/providers/ClientProvider";
import {
  fetchLogAnalysisHistory,
  type LogAnalysisHistoryItem,
  type LogAnalysisHistoryPage,
} from "@/lib/log-analysis-client";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 12;

/* ── colour & label maps ────────────────────────────────────────────── */

const SEV_COLORS: Record<string, string> = {
  critical: "#ef4444",
  high: "#f97316",
  medium: "#f59e0b",
  low: "#10b981",
};

const SEV_LABELS: Record<string, string> = {
  critical: "严重",
  high: "高危",
  medium: "中危",
  low: "低危",
};

const SEV_STYLES: Record<string, string> = {
  critical:
    "text-severity-critical bg-severity-critical/10 border-severity-critical/30",
  high: "text-severity-high bg-severity-high/10 border-severity-high/30",
  medium:
    "text-severity-medium bg-severity-medium/10 border-severity-medium/30",
  low: "text-severity-low bg-severity-low/10 border-severity-low/30",
};

/* ── helpers ─────────────────────────────────────────────────────────── */

function formatConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

function formatDate(raw: string): string {
  if (!raw) return "";
  return raw.replace("T", " ").slice(0, 19);
}

function formatCharCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

/** Whether the item needs human attention. */
function needsAction(item: LogAnalysisHistoryItem): boolean {
  return (
    item.suggested_action === "紧急处理" || item.suggested_action === "告警"
  );
}

/** High-risk count = critical + high (LLM-judged successful attacks). */
function highRiskCount(item: LogAnalysisHistoryItem): number {
  return (
    (item.severity_distribution?.critical ?? 0) +
    (item.severity_distribution?.high ?? 0)
  );
}

/** Total anomalies across all severity levels. */
function totalAnomalies(item: LogAnalysisHistoryItem): number {
  const d = item.severity_distribution;
  return (
    (d?.critical ?? 0) + (d?.high ?? 0) + (d?.medium ?? 0) + (d?.low ?? 0)
  );
}

/* ── Action status badge ─────────────────────────────────────────────── */

function ActionBadge({ item }: { item: LogAnalysisHistoryItem }) {
  const action = item.suggested_action;
  const urgent = needsAction(item);

  if (!action) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-border/40 bg-white/5 px-3 py-1 text-xs font-medium text-muted-foreground">
        待分析
      </span>
    );
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold",
        urgent
          ? "text-severity-critical bg-severity-critical/10 border-severity-critical/30"
          : action === "标记关注"
            ? "text-severity-medium bg-severity-medium/10 border-severity-medium/30"
            : "text-severity-low bg-severity-low/10 border-severity-low/30",
      )}
    >
      {urgent ? (
        <ShieldAlert className="h-3.5 w-3.5" />
      ) : (
        <ShieldCheck className="h-3.5 w-3.5" />
      )}
      {action}
    </span>
  );
}

/* ── Individual donut chart ──────────────────────────────────────────── */

function ItemDonutChart({
  item,
  onClick,
}: {
  item: LogAnalysisHistoryItem;
  onClick?: () => void;
}) {
  const option = useMemo(() => {
    const total = totalAnomalies(item);
    const highRisk = highRiskCount(item);
    const pct = total > 0 ? ((highRisk / total) * 100).toFixed(0) : "0";

    const pieData = (
      Object.entries(item.severity_distribution) as [string, number][]
    )
      .filter(([, v]) => v > 0)
      .map(([k, v]) => ({
        value: v,
        name: SEV_LABELS[k] || k,
        itemStyle: { color: SEV_COLORS[k] || "#64748b" },
      }));

    // Empty state — single grey ring
    if (pieData.length === 0) {
      pieData.push({
        value: 1,
        name: "无异常",
        itemStyle: { color: "#1e293b" },
      });
    }

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item" as const,
        backgroundColor: "rgba(15,23,42,0.95)",
        borderColor: "rgba(30,144,255,0.4)",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
        formatter: (p: { name: string; value: number; percent: number }) =>
          `${p.name}: ${p.value} 条 (${p.percent.toFixed(1)}%)`,
      },
      graphic: [
        {
          type: "text",
          left: "center",
          top: "36%",
          style: {
            text: total > 0 ? `${pct}%` : "0%",
            textAlign: "center",
            fill:
              Number(pct) > 50
                ? "#ef4444"
                : Number(pct) > 20
                  ? "#f59e0b"
                  : "#10b981",
            fontSize: 22,
            fontWeight: 700,
            fontFamily: "ui-monospace, monospace",
          },
        },
        {
          type: "text",
          left: "center",
          top: "52%",
          style: {
            text: "高危占比",
            textAlign: "center",
            fill: "#94a3b8",
            fontSize: 12,
          },
        },
      ],
      series: [
        {
          type: "pie" as const,
          radius: ["54%", "80%"],
          center: ["50%", "48%"],
          avoidLabelOverlap: false,
          itemStyle: { borderColor: "#0f172a", borderWidth: 2 },
          label: { show: false },
          labelLine: { show: false },
          emphasis: { scale: true, scaleSize: 4 },
          data: pieData,
        },
      ],
    };
  }, [item]);

  return (
    <div
      onClick={onClick}
      className="cursor-pointer rounded-lg transition-all hover:bg-white/[0.03] active:scale-[0.98]"
      role="button"
      tabIndex={0}
      aria-label="点击查看分析详情"
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick?.();
        }
      }}
    >
      <ReactECharts
        option={option}
        opts={{ renderer: "svg" }}
        className="h-[140px] w-full pointer-events-none"
      />
      {/* Legend below chart */}
      <div className="flex items-center justify-center gap-3 -mt-1 flex-wrap px-1 pb-1">
        {(
          Object.entries(item.severity_distribution) as [string, number][]
        )
          .filter(([, v]) => v > 0)
          .map(([k, v]) => (
            <span
              key={k}
              className="flex items-center gap-1 text-xs text-muted-foreground"
            >
              <span
                className="inline-block h-2 w-2 rounded-full shrink-0"
                style={{ backgroundColor: SEV_COLORS[k] }}
              />
              {SEV_LABELS[k] || k} {v}
            </span>
          ))}
      </div>
    </div>
  );
}

/* ── Metric chip ─────────────────────────────────────────────────────── */

function MetricChip({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg bg-white/[0.04] px-3 py-2">
      <span className={accent || "text-muted-foreground"}>{icon}</span>
      <div className="flex flex-col">
        <span className="text-xs text-muted-foreground leading-tight">
          {label}
        </span>
        <span className="text-sm font-semibold text-foreground font-mono leading-tight">
          {value}
        </span>
      </div>
    </div>
  );
}

/* ── Severity badge (consistent icon + font) ─────────────────────────── */

function SeverityTag({ severity }: { severity: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium shrink-0",
        SEV_STYLES[severity] || "",
      )}
    >
      {SEV_LABELS[severity] || severity}
    </span>
  );
}

/* ── Analysis record card ────────────────────────────────────────────── */

function RecordCard({ item }: { item: LogAnalysisHistoryItem }) {
  const [expanded, setExpanded] = useState(false);
  const urgent = needsAction(item);
  const highRisk = highRiskCount(item);
  const total = totalAnomalies(item);

  const toggleExpanded = () => setExpanded((v) => !v);

  return (
    <div
      className={cn(
        "rounded-xl border bg-card transition-all",
        urgent
          ? "border-severity-critical/30 shadow-[0_0_20px_rgba(239,68,68,0.06)]"
          : "border-border/40",
      )}
    >
      {/* Card header */}
      <div className="px-5 pt-4 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1">
              <ActionBadge item={item} />
              <span className="text-xs text-muted-foreground font-mono">
                #{item.id}
              </span>
            </div>
            <h3 className="text-sm font-semibold text-foreground truncate">
              {item.file_name || "未知文件"}
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              {formatDate(item.created_at)}
              {item.log_format && item.log_format !== "unknown" && (
                <span className="ml-2 uppercase text-xs bg-white/[0.06] rounded px-1.5 py-0.5">
                  {item.log_format}
                </span>
              )}
            </p>
          </div>
        </div>
      </div>

      {/* Card body: chart + metrics side-by-side */}
      <div className="px-5 pb-4">
        <div className="flex items-center gap-4">
          {/* Left: donut chart (clickable to expand) */}
          <div className="w-[160px] shrink-0">
            <ItemDonutChart item={item} onClick={toggleExpanded} />
          </div>

          {/* Right: key metrics */}
          <div className="flex-1 grid grid-cols-2 gap-2">
            <MetricChip
              icon={<AlertTriangle className="h-4 w-4" />}
              label="高危条目"
              value={`${highRisk} / ${total}`}
              accent={
                highRisk > 0 ? "text-severity-critical" : "text-severity-low"
              }
            />
            <MetricChip
              icon={<Activity className="h-4 w-4" />}
              label="置信度"
              value={formatConfidence(item.confidence)}
              accent={
                item.confidence > 0.5
                  ? "text-severity-critical"
                  : "text-severity-low"
              }
            />
            <MetricChip
              icon={<FileText className="h-4 w-4" />}
              label="内容大小"
              value={
                item.char_count > 0
                  ? `${formatCharCount(item.char_count)} 字符`
                  : "—"
              }
            />
            <MetricChip
              icon={<Hash className="h-4 w-4" />}
              label="异常总数"
              value={String(item.anomaly_count)}
            />
          </div>
        </div>
      </div>

      {/* Expandable detail toggle */}
      <button
        onClick={toggleExpanded}
        className="w-full flex items-center justify-center gap-1.5 py-2.5 text-xs text-muted-foreground hover:text-foreground transition-colors border-t border-border/20 cursor-pointer"
      >
        {expanded ? (
          <>
            <ChevronUp className="h-4 w-4" /> 收起详情
          </>
        ) : (
          <>
            <ChevronDown className="h-4 w-4" /> 点击饼图或此处查看详情
          </>
        )}
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-5 pb-5 pt-2 space-y-4 border-t border-border/20 bg-white/[0.01]">
          {/* Summary */}
          {item.summary && (
            <div>
              <p className="text-xs text-muted-foreground mb-1.5 font-medium">
                分析摘要
              </p>
              <p className="text-sm text-foreground/80 leading-relaxed">
                {item.summary}
              </p>
            </div>
          )}

          {/* Risk factors */}
          {item.risk_factors.length > 0 && (
            <div>
              <p className="text-xs text-muted-foreground mb-1.5 font-medium">
                风险因素
              </p>
              <ul className="list-disc list-inside text-sm text-foreground space-y-0.5">
                {item.risk_factors.map((rf) => (
                  <li key={`rf-${rf}`}>{rf}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Anomaly entries */}
          {item.anomaly_entries.length > 0 && (
            <div>
              <p className="text-xs text-muted-foreground mb-1.5 font-medium">
                异常条目（共 {item.anomaly_entries.length} 条）
              </p>
              <div className="space-y-1.5 max-h-64 overflow-y-auto">
                {item.anomaly_entries.map((ae, idx) => (
                  <div
                    key={`ae-${ae.severity}-${ae.desc.slice(0, 20)}-${idx}`}
                    className="flex items-start gap-2 text-sm bg-white/[0.03] rounded-lg px-3 py-2"
                  >
                    <SeverityTag severity={ae.severity} />
                    <span className="text-foreground">{ae.desc}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* LLM reason */}
          {item.reason && (
            <div>
              <p className="text-xs text-muted-foreground mb-1 font-medium">
                LLM 分析依据
              </p>
              <p className="text-sm text-foreground/70 leading-relaxed">
                {item.reason}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Page component ──────────────────────────────────────────────────── */

/** @description Card-based detail page for log-analysis security scan results. */
export function LogAnalysisDetailPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { token } = useClient();

  const [history, setHistory] = useState<LogAnalysisHistoryPage | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const data = await fetchLogAnalysisHistory(token, {
          page,
          pageSize: PAGE_SIZE,
        });
        if (cancelled) return;
        setHistory(data);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError((e as Error).message || "fetch failed");
        setHistory({ items: [], total: 0, page, page_size: PAGE_SIZE });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, page]);

  const totalRows = history?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));

  // Aggregate stats for the page header
  const urgentCount = useMemo(
    () => (history?.items ?? []).filter(needsAction).length,
    [history],
  );

  return (
    <div className="flex h-full w-full flex-col bg-background">
      <Navbar
        title={t("logAnalysis.detail.title", {
          defaultValue: "日志安全分析详情",
        })}
      />

      <main className="container flex-1 overflow-y-auto py-6 space-y-6 max-w-[1400px]">
        {/* Breadcrumb + controls */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            <button
              onClick={() => navigate("/dashboard")}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              {t("nav.dashboard", { defaultValue: "大屏分析" })}
            </button>
            <span className="text-muted-foreground">/</span>
            <span>日志安全分析</span>
          </div>
          <button
            onClick={() => navigate("/dashboard")}
            className="text-xs text-muted-foreground hover:text-foreground border border-border rounded-lg px-3 py-1.5 transition-colors"
          >
            &larr; 返回大屏
          </button>
        </div>

        {/* Page summary bar */}
        <div className="flex items-center gap-4 flex-wrap">
          <h2 className="text-lg font-semibold text-foreground">
            历史分析记录
          </h2>
          <span className="text-xs text-muted-foreground">
            共 {totalRows} 条
          </span>
          {urgentCount > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-severity-critical/30 bg-severity-critical/10 px-3 py-1 text-xs font-semibold text-severity-critical">
              <ShieldAlert className="h-3.5 w-3.5" />
              {urgentCount} 条需要处理
            </span>
          )}
          {/* Pagination */}
          {totalPages > 1 && (
            <div className="ml-auto flex items-center gap-1 text-xs">
              <button
                onClick={() => setPage(1)}
                disabled={page <= 1}
                className="px-2 py-1 rounded border border-border hover:bg-white/5 disabled:opacity-30 transition-colors"
              >
                首页
              </button>
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="px-2 py-1 rounded border border-border hover:bg-white/5 disabled:opacity-30 transition-colors"
              >
                &lsaquo;
              </button>
              <span className="px-2 text-muted-foreground font-mono">
                {page}/{totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="px-2 py-1 rounded border border-border hover:bg-white/5 disabled:opacity-30 transition-colors"
              >
                &rsaquo;
              </button>
              <button
                onClick={() => setPage(totalPages)}
                disabled={page >= totalPages}
                className="px-2 py-1 rounded border border-border hover:bg-white/5 disabled:opacity-30 transition-colors"
              >
                末页
              </button>
            </div>
          )}
        </div>

        {/* Loading skeleton */}
        {loading && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={`card-skeleton-${i}`}
                className="h-56 rounded-xl bg-white/5 animate-pulse"
              />
            ))}
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div className="rounded-xl border border-border/40 bg-card p-10 text-center text-sm text-muted-foreground">
            {t("logAnalysis.detail.unavailable", {
              defaultValue: "数据暂不可用",
            })}
            <button
              onClick={() => setPage(1)}
              className="ml-2 text-primary hover:text-primary-glow"
            >
              重试
            </button>
          </div>
        )}

        {/* Empty */}
        {!loading && !error && history && history.items.length === 0 && (
          <div className="rounded-xl border border-border/40 bg-card p-10 text-center text-sm text-muted-foreground">
            {t("logAnalysis.detail.empty", {
              defaultValue: "暂无分析记录",
            })}
          </div>
        )}

        {/* Card grid */}
        {!loading && !error && history && history.items.length > 0 && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {history.items.map((item) => (
              <RecordCard key={item.id} item={item} />
            ))}
          </div>
        )}

        {/* Bottom pagination */}
        {totalPages > 1 && !loading && (
          <div className="flex items-center justify-center gap-3 text-xs text-muted-foreground pt-2 pb-4">
            <button
              onClick={() => setPage(1)}
              disabled={page <= 1}
              className="hover:text-foreground disabled:opacity-30 transition-colors"
            >
              首页
            </button>
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="hover:text-foreground disabled:opacity-30 transition-colors"
            >
              上一页
            </button>
            <span className="font-mono">
              第 {page} 页，共 {totalRows} 条
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="hover:text-foreground disabled:opacity-30 transition-colors"
            >
              下一页
            </button>
            <button
              onClick={() => setPage(totalPages)}
              disabled={page >= totalPages}
              className="hover:text-foreground disabled:opacity-30 transition-colors"
            >
              末页
            </button>
          </div>
        )}
      </main>
    </div>
  );
}

export default LogAnalysisDetailPage;
