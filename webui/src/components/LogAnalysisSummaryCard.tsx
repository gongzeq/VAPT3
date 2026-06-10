/**
 * L1 log-analysis summary card mounted on the main DashboardPage.
 *
 * Shows the most recent log-analysis result: file name, timestamp,
 * confidence, anomaly count, and severity distribution.  Clicking
 * anywhere on the card navigates to ``/dashboard/log-analysis``
 * (L2 detail list).
 *
 * Resilience:
 *   - Loading: skeleton placeholders (avoids layout thrash).
 *   - Network failure / empty DB: show a muted "暂无数据" placeholder.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ArrowRight, ClipboardList, ShieldCheck } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { fetchLogAnalysisLatest, type LogAnalysisLatest } from "@/lib/log-analysis-client";
import { cn } from "@/lib/utils";

// ─── Helpers ────────────────────────────────────────────────────────────

const SEV_COLORS: Record<string, string> = {
  critical: "bg-severity-critical/15 text-severity-critical border-severity-critical/40",
  high: "bg-severity-high/15 text-severity-high border-severity-high/40",
  medium: "bg-severity-medium/15 text-severity-medium border-severity-medium/40",
  low: "bg-severity-low/15 text-severity-low border-severity-low/40",
};

const SEV_LABELS: Record<string, string> = {
  critical: "严重",
  high: "高危",
  medium: "中危",
  low: "低危",
};

function formatConfidence(c: number): string {
  return `${(c * 100).toFixed(0)}%`;
}

function formatDate(raw: string): string {
  if (!raw) return "";
  // ``2026-05-25 14:30:00`` → ``05-25 14:30``
  const m = raw.match(/^\d{4}-(\d{2}-\d{2})\s(\d{2}:\d{2})/);
  return m ? `${m[1]} ${m[2]}` : raw;
}

// ─── Component ──────────────────────────────────────────────────────────

/** @description Summary card showing the latest log-analysis scan result with confidence and action. */
export function LogAnalysisSummaryCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { token } = useClient();
  const [latest, setLatest] = useState<LogAnalysisLatest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const result = await fetchLogAnalysisLatest(token);
        if (cancelled) return;
        setLatest(result);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError((e as Error).message || "fetch failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  // Build severity tags from distribution
  const sevTags: Array<{ key: string; count: number }> = [];
  if (latest?.severity_distribution) {
    const d = latest.severity_distribution;
    for (const k of ["critical", "high", "medium", "low"]) {
      if (d[k as keyof typeof d] > 0) {
        sevTags.push({ key: k, count: d[k as keyof typeof d] });
      }
    }
  }

  const hasData = latest?.found === true;

  return (
    <section>
      <div className="flex items-center gap-3 mb-3">
        <div className="w-1 h-5 rounded-full bg-gradient-to-b from-ocean-500 to-cyan-glow" />
        <h2 className="text-base font-semibold">
          {t("logAnalysis.title", { defaultValue: "日志安全分析" })}
        </h2>
        <span className="text-xs text-muted-foreground">log-analysis workflow</span>
      </div>

      <button
        type="button"
        onClick={() => navigate("/dashboard/log-analysis")}
        className="w-full text-left rounded-xl border border-border/40 bg-card hover:border-alert-success/50 hover-lift p-5 grid grid-cols-1 lg:grid-cols-12 gap-4 items-center transition-colors"
      >
        {/* Hero metric — anomaly count */}
        <div className="lg:col-span-2 flex items-center gap-4">
          <div className="icon-surface icon-surface-success h-12 w-12 rounded-xl">
            <ClipboardList className="h-6 w-6" />
          </div>
          <div>
            {loading ? (
              <div className="space-y-2">
                <div className="h-7 w-12 animate-pulse rounded bg-muted" />
                <div className="h-3 w-16 animate-pulse rounded bg-muted/70" />
              </div>
            ) : (
              <>
                <p className="text-3xl font-bold tracking-tight font-mono text-alert-success">
                  {hasData ? (latest?.total_entries ?? "—") : "—"}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">已检测总条目</p>
              </>
            )}
          </div>
        </div>

        {/* Context info */}
        <div className="lg:col-span-3">
          {loading ? (
            <div className="space-y-2">
              <div className="h-4 w-32 animate-pulse rounded bg-muted" />
              <div className="h-3 w-24 animate-pulse rounded bg-muted/70" />
            </div>
          ) : hasData ? (
            <>
              <p className="text-sm font-medium truncate" title={latest?.file_name}>
                {latest?.file_name}
              </p>
              <p className="text-xs text-muted-foreground">
                {formatDate(latest?.created_at ?? "")}
                {" · "}
                置信度 {formatConfidence(latest?.confidence ?? 0)}
              </p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">暂无分析数据</p>
          )}
        </div>

        {/* Severity tags */}
        <div className="lg:col-span-4 flex items-center gap-2 flex-wrap">
          {loading ? (
            <div className="flex gap-2">
              <div className="h-6 w-14 animate-pulse rounded-full bg-muted" />
              <div className="h-6 w-14 animate-pulse rounded-full bg-muted/70" />
            </div>
          ) : hasData ? (
            sevTags.length > 0 ? (
              sevTags.map((t) => (
                <span
                  key={t.key}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[10px] font-medium",
                    SEV_COLORS[t.key] || "bg-muted/40 text-muted-foreground",
                  )}
                >
                  {SEV_LABELS[t.key] || t.key} {t.count}
                </span>
              ))
            ) : (
              <span className="text-xs text-muted-foreground">无严重级别分布</span>
            )
          ) : (
            <span className="inline-flex items-center rounded-full border border-border/40 bg-muted/40 px-2.5 py-0.5 text-[10px] text-muted-foreground">
              无数据
            </span>
          )}
        </div>

        {/* Suggested action + arrow */}
        <div className="lg:col-span-3 flex items-center justify-between gap-2">
          {loading ? (
            <div className="h-4 w-16 animate-pulse rounded bg-muted" />
          ) : hasData ? (
            <span className="text-xs text-muted-foreground truncate">
              {latest?.suggested_action || "—"}
            </span>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-2 shrink-0">
            <ShieldCheck className="h-4 w-4 text-alert-success" />
            <ArrowRight className="h-4 w-4 text-alert-success" />
          </div>
        </div>
      </button>

      <p className="text-[11px] text-muted-foreground mt-2 text-right">
        {error
          ? t("logAnalysis.summary.unavailable", {
              defaultValue: "数据暂不可用",
            })
          : hasData
            ? t("logAnalysis.summary.click_to_detail", {
                defaultValue: "点击卡片查看历史分析记录 →",
              })
            : t("logAnalysis.summary.no_data", {
                defaultValue: "执行一次日志分析工作流后查看结果",
              })}
      </p>
    </section>
  );
}
