import { useEffect, useState } from "react";

import { secbotApi, type ReportRecord } from "../api";

const FORMAT_LABEL: Record<string, string> = {
  markdown: "Markdown",
  pdf: "PDF",
  docx: "Word",
};

function fmtBytes(n?: number): string {
  if (!n) return "-";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
  return `${(n / 1024 / 1024).toFixed(1)} MiB`;
}

/**
 * Reports browser — every artifact produced by report-{markdown,pdf,docx}
 * skills shows up here, grouped by scan_id.
 */
export function ReportsView() {
  const [rows, setRows] = useState<ReportRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    secbotApi
      .listReports()
      .then((d) => !cancel && setRows(d))
      .catch((e) => !cancel && setError(String(e)));
    return () => {
      cancel = true;
    };
  }, []);

  if (error) return <div className="p-4 text-red-400">加载失败：{error}</div>;
  if (!rows) return <div className="p-4 text-text-secondary">加载中…</div>;
  if (rows.length === 0)
    return <div className="p-4 text-text-secondary">尚无生成的报告。</div>;

  return (
    <div className="p-4">
      <header className="mb-3 flex items-baseline justify-between">
        <h1 className="text-lg font-semibold">报告</h1>
        <span className="text-xs text-text-secondary">{rows.length} 份报告</span>
      </header>
      <table className="w-full border-collapse text-sm">
        <thead className="text-text-secondary">
          <tr>
            <th className="border-b border-border px-2 py-1.5 text-left">Scan ID</th>
            <th className="border-b border-border px-2 py-1.5 text-left">格式</th>
            <th className="border-b border-border px-2 py-1.5 text-left">大小</th>
            <th className="border-b border-border px-2 py-1.5 text-left">生成时间</th>
            <th className="border-b border-border px-2 py-1.5 text-left">下载</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.scan_id}-${r.format}-${i}`} className="hover:bg-card/50">
              <td className="border-b border-border-subtle px-2 py-1.5 font-mono text-xs">
                {r.scan_id}
              </td>
              <td className="border-b border-border-subtle px-2 py-1.5">
                {FORMAT_LABEL[r.format] ?? r.format}
              </td>
              <td className="border-b border-border-subtle px-2 py-1.5">{fmtBytes(r.size_bytes)}</td>
              <td className="border-b border-border-subtle px-2 py-1.5 text-xs text-text-secondary">
                {r.generated_at}
              </td>
              <td className="border-b border-border-subtle px-2 py-1.5">
                <a
                  href={r.download_url}
                  target="_blank"
                  rel="noreferrer"
                  download
                  className="text-primary hover:underline"
                >
                  下载 ↓
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
