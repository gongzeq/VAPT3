/**
 * /dashboard/log-analysis — L2 detail page for the log-analysis workflow.
 *
 * Shows a paginated table of all historical log-analysis results with
 * expandable detail rows.
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { useClient } from "@/providers/ClientProvider";
import {
  fetchLogAnalysisHistory,
  type LogAnalysisHistoryItem,
  type LogAnalysisHistoryPage,
} from "@/lib/log-analysis-client";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 15;

const SEV_STYLES: Record<string, string> = {
  critical: "text-rose-400 bg-rose-500/10 border-rose-500/30",
  high: "text-orange-400 bg-orange-500/10 border-orange-500/30",
  medium: "text-amber-400 bg-amber-500/10 border-amber-500/30",
  low: "text-sky-400 bg-sky-500/10 border-sky-500/30",
};

const SEV_LABELS: Record<string, string> = {
  critical: "严重",
  high: "高危",
  medium: "中危",
  low: "低危",
};

const SUGGESTED_BADGE: Record<string, string> = {
  紧急处理: "text-rose-400 bg-rose-500/10 border-rose-500/30",
  告警: "text-orange-400 bg-orange-500/10 border-orange-500/30",
  标记关注: "text-amber-400 bg-amber-500/10 border-amber-500/30",
  忽略: "text-sky-400 bg-sky-500/10 border-sky-500/30",
};

function formatConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

function formatDate(raw: string): string {
  if (!raw) return "";
  return raw.replace("T", " ").slice(0, 19);
}

// ─── Expandable detail row ──────────────────────────────────────────────

function DetailRow({ item }: { item: LogAnalysisHistoryItem }) {
  const [expanded, setExpanded] = useState(false);

  const badgeCls =
    SUGGESTED_BADGE[item.suggested_action] ||
    "text-muted-foreground bg-white/5 border-border/40";

  return (
    <>
      {/* Summary row */}
      <tr
        onClick={() => setExpanded((v) => !v)}
        className="hover:bg-white/5 transition-colors cursor-pointer"
      >
        <td className="py-3 pl-4 w-8">
          {expanded ? (
            <ChevronUp className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          )}
        </td>
        <td className="py-3">
          <div className="font-medium text-foreground text-sm truncate max-w-[220px]">
            {item.file_name}
          </div>
          <div className="text-xs text-muted-foreground font-mono">
            #{item.id}
          </div>
        </td>
        <td className="py-3 text-xs text-muted-foreground">
          {formatDate(item.created_at)}
        </td>
        <td className="py-3 text-right">
          <span className="font-mono font-medium text-foreground">
            {item.anomaly_count}
          </span>
        </td>
        <td className="py-3 text-right">
          <span className="font-mono text-sm text-emerald-400">
            {formatConfidence(item.confidence)}
          </span>
        </td>
        <td className="py-3 text-right">
          <span
            className={cn(
              "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium",
              badgeCls,
            )}
          >
            {item.suggested_action || "—"}
          </span>
        </td>
      </tr>

      {/* Expanded detail */}
      {expanded && (
        <tr>
          <td colSpan={6} className="bg-white/[0.02] border-t border-border/20">
            <div className="p-5 space-y-4">
              {/* Severity distribution tags */}
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-muted-foreground">严重分布：</span>
                {(Object.entries(item.severity_distribution) as [string, number][])
                  .filter(([, v]) => v > 0)
                  .map(([k, v]) => (
                    <span
                      key={k}
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[10px] font-medium",
                        SEV_STYLES[k] || "",
                      )}
                    >
                      {SEV_LABELS[k] || k} {v}
                    </span>
                  ))}
                {Object.values(item.severity_distribution).every((v) => v === 0) && (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </div>

              {/* Risk factors */}
              {item.risk_factors.length > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1.5">风险因素：</p>
                  <ul className="list-disc list-inside text-sm text-foreground space-y-0.5">
                    {item.risk_factors.map((rf, i) => (
                      <li key={i}>{rf}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Anomaly entries */}
              {item.anomaly_entries.length > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1.5">
                    异常条目（共 {item.anomaly_entries.length} 条）：
                  </p>
                  <div className="space-y-1.5 max-h-64 overflow-y-auto">
                    {item.anomaly_entries.map((ae, i) => (
                      <div
                        key={i}
                        className="flex items-start gap-2 text-sm bg-white/[0.03] rounded-lg px-3 py-2"
                      >
                        <span
                          className={cn(
                            "inline-block rounded-full px-1.5 py-0 text-[10px] font-medium mt-0.5 shrink-0",
                            SEV_STYLES[ae.severity] || "",
                          )}
                        >
                          {SEV_LABELS[ae.severity] || ae.severity}
                        </span>
                        <span className="text-foreground">{ae.desc}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Summary text */}
              {item.summary && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1">摘要：</p>
                  <p className="text-sm text-foreground/80 whitespace-pre-wrap leading-relaxed">
                    {item.summary}
                  </p>
                </div>
              )}

              {/* LLM reason */}
              {item.reason && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1">LLM 分析依据：</p>
                  <p className="text-sm text-foreground/70">{item.reason}</p>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ─── Page component ─────────────────────────────────────────────────────

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

  return (
    <div className="flex h-full w-full flex-col bg-background">
      <Navbar
        title={t("logAnalysis.detail.title", { defaultValue: "日志安全分析详情" })}
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
            className="text-xs text-muted-foreground hover:text-foreground border border-border rounded-lg px-3 py-1.5"
          >
            ← 返回大屏
          </button>
        </div>

        {/* Table card */}
        <div className="rounded-xl border border-border/40 bg-card">
          <div className="flex items-center justify-between px-5 py-4 border-b border-border/20">
            <div>
              <h3 className="text-sm font-semibold text-foreground">
                历史分析记录
              </h3>
              <p className="text-xs text-muted-foreground mt-0.5">
                共 {totalRows} 条记录
              </p>
            </div>
            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center gap-1 text-xs">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-2 py-1 rounded border border-border hover:bg-white/5 disabled:opacity-30"
                >
                  ‹
                </button>
                <span className="px-2 text-muted-foreground">
                  {page} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="px-2 py-1 rounded border border-border hover:bg-white/5 disabled:opacity-30"
                >
                  ›
                </button>
              </div>
            )}
          </div>

          {/* Table */}
          {loading ? (
            <div className="p-10 space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div
                  key={i}
                  className="h-10 bg-white/5 rounded animate-pulse"
                />
              ))}
            </div>
          ) : error ? (
            <div className="p-10 text-center text-sm text-muted-foreground">
              {t("logAnalysis.detail.unavailable", { defaultValue: "数据暂不可用" })}
              <button
                onClick={() => setPage(1)}
                className="ml-2 text-primary hover:text-primary-glow"
              >
                重试
              </button>
            </div>
          ) : history && history.items.length === 0 ? (
            <div className="p-10 text-center text-sm text-muted-foreground">
              {t("logAnalysis.detail.empty", { defaultValue: "暂无分析记录" })}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-muted-foreground border-b border-border">
                  <tr>
                    <th className="text-left py-3 pl-4 w-8" />
                    <th className="text-left py-3 font-medium">文件名</th>
                    <th className="text-left py-3 font-medium">时间</th>
                    <th className="text-right py-3 font-medium">异常数</th>
                    <th className="text-right py-3 font-medium">置信度</th>
                    <th className="text-right py-3 pr-4 font-medium">建议</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/20">
                  {history?.items.map((item) => (
                    <DetailRow key={item.id} item={item} />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Bottom pagination */}
          {totalPages > 1 && !loading && (
            <div className="flex items-center justify-between px-5 py-3 border-t border-border/20 text-xs text-muted-foreground">
              <span>
                第 {page} 页，共 {totalRows} 条
              </span>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setPage(1)}
                  disabled={page <= 1}
                  className="hover:text-foreground disabled:opacity-30"
                >
                  首页
                </button>
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="hover:text-foreground disabled:opacity-30"
                >
                  上一页
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="hover:text-foreground disabled:opacity-30"
                >
                  下一页
                </button>
                <button
                  onClick={() => setPage(totalPages)}
                  disabled={page >= totalPages}
                  className="hover:text-foreground disabled:opacity-30"
                >
                  末页
                </button>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

export default LogAnalysisDetailPage;
