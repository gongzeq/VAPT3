import type { ToolCallContentPartComponent } from "@assistant-ui/react";

import { RawLogLink, SeveritySummary, StatusPill, type Severity } from "./_shared";

interface CmdbVuln {
  cve_id: string;
  title: string;
  severity: Severity;
  asset?: string;
}

interface CmdbResult {
  status?: string;
  scan_id?: string;
  totals?: { assets: number; services: number; vulnerabilities: number };
  severity_counts?: Partial<Record<Severity, number>>;
  vulnerabilities?: CmdbVuln[];
}

export const CmdbQueryRenderer: ToolCallContentPartComponent = ({ result }) => {
  const r = (result ?? {}) as CmdbResult;
  return (
    <div className="my-2 rounded-md border border-border bg-card p-3 text-sm">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-medium">CMDB 查询</span>
        <StatusPill status={r.status ?? "running"} />
      </div>
      {r.totals && (
        <div className="mb-2 flex gap-4 text-xs text-text-secondary">
          <span>资产 {r.totals.assets}</span>
          <span>服务 {r.totals.services}</span>
          <span>漏洞 {r.totals.vulnerabilities}</span>
        </div>
      )}
      {r.severity_counts && <SeveritySummary counts={r.severity_counts} />}
      {r.vulnerabilities && r.vulnerabilities.length > 0 && (
        <table className="mt-3 w-full border-collapse text-xs">
          <thead className="text-text-secondary">
            <tr>
              <th className="border-b border-border px-2 py-1 text-left">CVE</th>
              <th className="border-b border-border px-2 py-1 text-left">资产</th>
              <th className="border-b border-border px-2 py-1 text-left">标题</th>
              <th className="border-b border-border px-2 py-1 text-left">等级</th>
            </tr>
          </thead>
          <tbody>
            {r.vulnerabilities.slice(0, 20).map((v, i) => (
              <tr key={`${v.cve_id}-${i}`}>
                <td className="border-b border-border-subtle px-2 py-1 font-mono">{v.cve_id}</td>
                <td className="border-b border-border-subtle px-2 py-1">{v.asset ?? "-"}</td>
                <td className="border-b border-border-subtle px-2 py-1">{v.title}</td>
                <td className="border-b border-border-subtle px-2 py-1">
                  <SeveritySummary counts={{ [v.severity]: 1 } as Partial<Record<Severity, number>>} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="mt-2">
        <RawLogLink scanId={r.scan_id} skill="cmdb-query" />
      </div>
    </div>
  );
};
