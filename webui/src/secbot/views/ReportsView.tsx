import { useEffect, useMemo, useState } from "react";

import { Callout } from "@/components/tremor/callout";
import { DonutChart } from "@/components/tremor/donut-chart";
import { Metric } from "@/components/tremor/metric";
import { cn } from "@/lib/utils";

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
 *
 * Ocean-tech styling (PR4-R5):
 *   - Header: brand-deep tinted panel with Metric (total reports) and a
 *     DonutChart showing the format distribution (markdown/pdf/docx).
 *   - When there are no reports, render a `<Callout variant="neutral">` so
 *     the empty state is visually consistent with other HUD panels.
 *   - Row hover uses brand-light tint; the download link keeps `text-primary`
 *     + underline on hover (the primary interaction CTA).
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

  const formatDistribution = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const r of rows ?? []) {
      const label = FORMAT_LABEL[r.format] ?? r.format;
      counts[label] = (counts[label] ?? 0) + 1;
    }
    return Object.entries(counts).map(([format, count]) => ({
      format,
      count,
    }));
  }, [rows]);

  if (error)
    return (
      <div className="p-4">
        <Callout variant="error" title="加载失败">
          {error}
        </Callout>
      </div>
    );
  if (!rows) return <div className="p-4 text-text-secondary">加载中…</div>;
  if (rows.length === 0)
    return (
      <div className="p-4">
        <Callout variant="neutral" title="尚无生成的报告">
          运行一次扫描并让 orchestrator 调用 report-* 技能后，报告会出现在这里。
        </Callout>
      </div>
    );

  return (
    <div className="p-4">
      <header
        className={cn(
          "relative mb-4 overflow-hidden rounded-lg border p-4",
          "border-[hsl(var(--brand-deep)/0.25)] bg-card",
        )}
      >
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "linear-gradient(135deg, hsl(var(--brand-deep) / 0.15) 0%, transparent 50%, hsl(var(--primary) / 0.08) 100%)",
          }}
        />
        <div className="relative z-[1] flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-lg font-semibold">报告</h1>
            <div className="mt-1 text-xs text-text-secondary">
              共 {rows.length} 份
            </div>
            <Metric className="mt-2 text-[hsl(var(--primary))]">
              {rows.length}
            </Metric>
          </div>
          {formatDistribution.length > 0 && (
            <div className="flex items-center gap-3">
              <DonutChart
                data={formatDistribution}
                category="format"
                value="count"
                showLabel
                label="格式分布"
                className="h-28 w-28"
                valueFormatter={(n) => `${n}`}
              />
              <ul className="text-xs text-text-secondary">
                {formatDistribution.map((d) => (
                  <li key={d.format} className="tabular-nums">
                    {d.format}: {d.count}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </header>
      <table className="w-full border-collapse text-sm">
        <thead className="text-text-secondary">
          <tr>
            <th className="border-b border-border px-2 py-1.5 text-left">
              Scan ID
            </th>
            <th className="border-b border-border px-2 py-1.5 text-left">格式</th>
            <th className="border-b border-border px-2 py-1.5 text-left">大小</th>
            <th className="border-b border-border px-2 py-1.5 text-left">
              生成时间
            </th>
            <th className="border-b border-border px-2 py-1.5 text-left">下载</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={`${r.scan_id}-${r.format}-${i}`}
              className="transition-colors hover:bg-[hsl(var(--brand-light)/0.08)] motion-reduce:transition-none"
            >
              <td className="border-b border-border-subtle px-2 py-1.5 font-mono text-xs">
                {r.scan_id}
              </td>
              <td className="border-b border-border-subtle px-2 py-1.5">
                {FORMAT_LABEL[r.format] ?? r.format}
              </td>
              <td className="border-b border-border-subtle px-2 py-1.5">
                {fmtBytes(r.size_bytes)}
              </td>
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
