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
  critical: "#dc2626",
  high: "#ef4444",
  medium: "#eab308",
  low: "#22c55e",
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
  /* ── derived values ── */
  const total = totalAnomalies(item);
  const highRisk = highRiskCount(item);
  const pct = total > 0 ? ((highRisk / total) * 100).toFixed(0) : "0";
  const critOnly = item.severity_distribution?.critical ?? 0;
  const centerColor =
    Number(pct) > 50 ? "#dc2626" : Number(pct) > 20 ? "#ef4444" : "#22c55e";

  /* ── dynamic font size based on text length ── */
  const centerText = total > 0 ? `${highRisk}/${total}` : "0/0";
  const centerFontSize =
    centerText.length <= 5 ? 20 :
    centerText.length <= 7 ? 17 :
    centerText.length <= 9 ? 14 :
    centerText.length <= 12 ? 12 : 10;

  /* ── SVG donut segments ── */
  const R = 72;
  const C = 2 * Math.PI * R; // circumference
  const entries = (
    Object.entries(item.severity_distribution) as [string, number][]
  ).filter(([, v]) => v > 0);
  const segTotal = entries.reduce((s, [, v]) => s + v, 0);

  let acc = 0;
  const segments = entries.map(([k, v]) => {
    const dash = segTotal > 0 ? (v / segTotal) * C : 0;
    const offset = acc;
    acc += dash;
    return { key: k, dash, gap: C - dash, offset, color: SEV_COLORS[k] || "#64748b" };
  });

  // Tooltip state
  const [tip, setTip] = useState<{ text: string; x: number; y: number } | null>(null);

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
      {/* SVG donut + centred text overlay */}
      <div className="relative h-[210px] w-full">
        <svg
          viewBox="0 0 220 220"
          className="absolute inset-0 h-full w-full"
          style={{ overflow: "visible" }}
        >
          {segments.length === 0 ? (
            <circle
              cx={110}
              cy={110}
              r={R}
              fill="none"
              stroke="#1e293b"
              strokeWidth={22}
            />
          ) : (
            segments.map((seg) => (
              <circle
                key={seg.key}
                cx={110}
                cy={110}
                r={R}
                fill="none"
                stroke={seg.color}
                strokeWidth={22}
                strokeDasharray={`${seg.dash} ${seg.gap}`}
                strokeDashoffset={-seg.offset}
                strokeLinecap="butt"
                transform="rotate(-90 110 110)"
                className="transition-opacity hover:opacity-80"
                onMouseEnter={(e) => {
                  const val = entries.find(([k]) => k === seg.key)?.[1] ?? 0;
                  const p = segTotal > 0 ? ((val / segTotal) * 100).toFixed(1) : "0";
                  const rect = e.currentTarget.closest("svg")!.getBoundingClientRect();
                  setTip({
                    text: `${SEV_LABELS[seg.key] || seg.key}: ${val} 条 (${p}%)`,
                    x: e.clientX - rect.left,
                    y: e.clientY - rect.top,
                  });
                }}
                onMouseMove={(e) => {
                  if (!tip) return;
                  const rect = e.currentTarget.closest("svg")!.getBoundingClientRect();
                  setTip({ ...tip, x: e.clientX - rect.left, y: e.clientY - rect.top });
                }}
                onMouseLeave={() => setTip(null)}
              />
            ))
          )}
        </svg>
        {/* Tooltip */}
        {tip && (
          <div
            className="absolute z-50 rounded px-2 py-1 text-xs whitespace-nowrap pointer-events-none"
            style={{
              left: tip.x + 8,
              top: tip.y - 28,
              backgroundColor: "rgba(15,23,42,0.95)",
              borderColor: "rgba(30,144,255,0.4)",
              border: "1px solid",
              color: "#e2e8f0",
            }}
          >
            {tip.text}
          </div>
        )}
        {/* Dead-centre text — guaranteed aligned because SVG viewBox
             centre (100,100) == container centre via absolute inset-0 */}
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none select-none">
          <span
            className="font-mono font-bold leading-tight"
            style={{ fontSize: centerFontSize, color: centerColor }}
          >
            {centerText}
          </span>
          <span className="text-xs leading-tight" style={{ color: "#94a3b8" }}>
            {critOnly > 0 ? "严重+高危" : "需处理"}
          </span>
        </div>
      </div>
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
