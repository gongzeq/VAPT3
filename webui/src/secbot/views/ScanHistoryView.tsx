import { useEffect, useState } from "react";

import { secbotApi, type ScanRecord } from "../api";
import { SeveritySummary } from "../renderers/_shared";

const STATUS_BG: Record<string, string> = {
  running: "bg-sky-500/15 text-sky-300",
  succeeded: "bg-emerald-500/15 text-emerald-300",
  failed: "bg-red-500/15 text-red-300",
  cancelled: "bg-slate-500/15 text-slate-300",
};

/**
 * Scan history table — chronological list of orchestrator runs.
 * Click a row to open `/scans/:id` (drill-down view) or jump to the
 * latest report download.
 */
export function ScanHistoryView() {
  const [rows, setRows] = useState<ScanRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    secbotApi
      .listScans()
      .then((d) => !cancel && setRows(d))
      .catch((e) => !cancel && setError(String(e)));
    return () => {
      cancel = true;
    };
  }, []);

  if (error) return <div className="p-4 text-red-400">加载失败：{error}</div>;
  if (!rows) return <div className="p-4 text-text-secondary">加载中…</div>;
  if (rows.length === 0)
    return <div className="p-4 text-text-secondary">尚无扫描记录。</div>;

  return (
    <div className="p-4">
      <header className="mb-3 flex items-baseline justify-between">
        <h1 className="text-lg font-semibold">扫描历史</h1>
        <span className="text-xs text-text-secondary">{rows.length} 次扫描</span>
      </header>
      <table className="w-full border-collapse text-sm">
        <thead className="text-text-secondary">
          <tr>
            <th className="border-b border-border px-2 py-1.5 text-left">Scan ID</th>
            <th className="border-b border-border px-2 py-1.5 text-left">状态</th>
            <th className="border-b border-border px-2 py-1.5 text-left">Agent</th>
            <th className="border-b border-border px-2 py-1.5 text-left">资产</th>
            <th className="border-b border-border px-2 py-1.5 text-left">漏洞分布</th>
            <th className="border-b border-border px-2 py-1.5 text-left">开始时间</th>
            <th className="border-b border-border px-2 py-1.5 text-left">结束时间</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id} className="hover:bg-card/50">
              <td className="border-b border-border-subtle px-2 py-1.5 font-mono text-xs">{s.id}</td>
              <td className="border-b border-border-subtle px-2 py-1.5">
                <span className={`rounded px-1.5 py-0.5 text-[11px] ${STATUS_BG[s.status] ?? ""}`}>
                  {s.status}
                </span>
              </td>
              <td className="border-b border-border-subtle px-2 py-1.5">{s.agent}</td>
              <td className="border-b border-border-subtle px-2 py-1.5">{s.totals.assets}</td>
              <td className="border-b border-border-subtle px-2 py-1.5">
                <SeveritySummary counts={s.severity_counts} />
              </td>
              <td className="border-b border-border-subtle px-2 py-1.5 text-xs text-text-secondary">
                {s.started_at}
              </td>
              <td className="border-b border-border-subtle px-2 py-1.5 text-xs text-text-secondary">
                {s.finished_at ?? "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
