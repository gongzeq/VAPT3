import type { ToolCallContentPartComponent } from "@assistant-ui/react";

import { StatusPill, type Severity } from "./_shared";

interface ReportResult {
  status?: string;
  scan_id?: string;
  report_path?: string;
  format?: "markdown" | "docx" | "pdf";
  download_url?: string;
  severity_counts?: Partial<Record<Severity, number>>;
  message?: string;
}

const FORMAT_LABEL: Record<string, string> = {
  markdown: "Markdown",
  docx: "Word (DOCX)",
  pdf: "PDF",
};

export const ReportRenderer: ToolCallContentPartComponent = ({ toolName, result }) => {
  const r = (result ?? {}) as ReportResult;
  const fmt = r.format ?? toolName.replace("report-", "");
  const downloadHref =
    r.download_url ??
    (r.scan_id ? `/api/scans/${r.scan_id}/report.${fmt === "markdown" ? "md" : fmt}` : null);
  return (
    <div className="my-2 rounded-md border border-border bg-card p-3 text-sm">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="font-medium">报告生成 · {FORMAT_LABEL[fmt] ?? fmt}</div>
          {r.scan_id && (
            <div className="text-xs text-text-secondary">scan_id: {r.scan_id}</div>
          )}
        </div>
        <StatusPill status={r.status ?? "running"} />
      </div>
      {r.message && (
        <div className="mb-2 text-xs text-text-secondary">{r.message}</div>
      )}
      {downloadHref && r.status === "ok" && (
        <a
          className="inline-block rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90"
          href={downloadHref}
          target="_blank"
          rel="noreferrer"
          download
        >
          下载报告 ↓
        </a>
      )}
      {r.status === "error" && (
        <div className="text-xs text-red-400">报告渲染失败，请检查后端依赖（weasyprint / python-docx）。</div>
      )}
      {r.status === "empty" && (
        <div className="text-xs text-text-secondary">该 scan 暂无任何资产或漏洞，已跳过报告生成。</div>
      )}
    </div>
  );
};
