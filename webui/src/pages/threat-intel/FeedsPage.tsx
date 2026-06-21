/**
 * Threat Intel Feed Runs Page — PRD §7.2 Feed运行页.
 *
 * Table of feed pull runs + manual trigger button.
 */

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, CheckCircle, XCircle, AlertTriangle, Loader } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import {
  fetchFeedRuns,
  triggerFeedPull,
  type FeedPullRunSummary,
} from "@/lib/threat-intel-client";
import { cn } from "@/lib/utils";

const SOURCE_LABELS: Record<string, string> = {
  mitre: "MITRE ATT&CK",
  cisa_kev: "CISA KEV",
  threatfox: "ThreatFox",
};

export function FeedsPage() {
  const { token } = useClient();
  const [runs, setRuns] = useState<FeedPullRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchFeedRuns(token, { page_size: 50 });
      setRuns(result.items);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  const handleTrigger = async (source: string) => {
    setTriggering(source);
    try {
      await triggerFeedPull(token, source);
      await loadRuns();
    } catch (e) {
      window.alert(`触发失败: ${(e as Error).message}`);
    } finally {
      setTriggering(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-slate-900">Feed 运行记录</h1>
        <div className="flex items-center gap-2">
          {Object.entries(SOURCE_LABELS).map(([key, label]) => (
            <button
              key={key}
              type="button"
              disabled={triggering !== null}
              onClick={() => handleTrigger(key)}
              className="flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-600 transition-colors hover:border-indigo-300 hover:text-indigo-600 disabled:opacity-40"
            >
              {triggering === key ? (
                <Loader className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              {label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex h-40 items-center justify-center text-sm text-slate-400">
          加载中…
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs text-slate-500">
                <th className="px-4 py-3 font-medium">数据源</th>
                <th className="px-4 py-3 font-medium">触发方式</th>
                <th className="px-4 py-3 font-medium">状态</th>
                <th className="px-4 py-3 font-medium">开始时间</th>
                <th className="px-4 py-3 font-medium">结束时间</th>
                <th className="px-4 py-3 text-right font-medium">新增</th>
                <th className="px-4 py-3 text-right font-medium">更新</th>
                <th className="px-4 py-3 text-right font-medium">跳过</th>
                <th className="px-4 py-3 text-right font-medium">未映射</th>
                <th className="px-4 py-3 font-medium">错误</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  <td className="px-4 py-2.5 font-medium text-slate-700">
                    {SOURCE_LABELS[run.source] || run.source}
                  </td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {run.trigger === "schedule" ? "定时" : "手动"}
                  </td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={run.status} />
                  </td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {run.started_at ? new Date(run.started_at).toLocaleString("zh-CN") : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {run.finished_at ? new Date(run.finished_at).toLocaleString("zh-CN") : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-right font-medium text-emerald-600">
                    {run.inserted_count}
                  </td>
                  <td className="px-4 py-2.5 text-right font-medium text-blue-600">
                    {run.updated_count}
                  </td>
                  <td className="px-4 py-2.5 text-right text-slate-400">
                    {run.skipped_count}
                  </td>
                  <td className="px-4 py-2.5 text-right text-amber-600">
                    {run.unmapped_count}
                  </td>
                  <td className="px-4 py-2.5 max-w-xs truncate text-xs text-red-500" title={run.error_message ?? ""}>
                    {run.error_message || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {runs.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-slate-400">
              <p className="text-sm">暂无 Feed 运行记录</p>
              <p className="mt-1 text-xs">点击上方按钮手动触发 Feed 拉取</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { icon: React.ReactNode; className: string; label: string }> = {
    ok: { icon: <CheckCircle className="h-3 w-3" />, className: "bg-emerald-50 text-emerald-700", label: "成功" },
    failed: { icon: <XCircle className="h-3 w-3" />, className: "bg-red-50 text-red-700", label: "失败" },
    partial: { icon: <AlertTriangle className="h-3 w-3" />, className: "bg-amber-50 text-amber-700", label: "部分" },
    running: { icon: <Loader className="h-3 w-3 animate-spin" />, className: "bg-blue-50 text-blue-700", label: "运行中" },
  };
  const c = config[status] || { icon: null, className: "bg-slate-100 text-slate-600", label: status };
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium", c.className)}>
      {c.icon}
      {c.label}
    </span>
  );
}

export default FeedsPage;
