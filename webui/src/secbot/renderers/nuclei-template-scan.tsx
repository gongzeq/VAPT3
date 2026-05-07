import * as React from "react";
import type { ToolCallContentPartComponent } from "@assistant-ui/react";

import { RawLogLink, SeverityBadge, SeveritySummary, StatusPill, type Severity } from "./_shared";

interface VulnFinding {
  template_id?: string;
  title: string;
  host?: string;
  url?: string;
  severity: Severity;
}

interface VulnResult {
  status?: string;
  scan_id?: string;
  severity_counts?: Partial<Record<Severity, number>>;
  findings?: VulnFinding[];
}

function VulnRenderer({
  title,
  skillName,
  result,
}: {
  title: string;
  skillName: string;
  result: unknown;
}) {
  const r = (result ?? {}) as VulnResult;
  const findings = r.findings ?? [];
  return (
    <div className="my-2 rounded-md border border-border bg-card p-3 text-sm">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-medium">{title}</span>
        <StatusPill status={r.status ?? "running"} />
      </div>
      {r.severity_counts && <SeveritySummary counts={r.severity_counts} />}
      {findings.length > 0 ? (
        <ul className="mt-2 space-y-1.5">
          {findings.slice(0, 30).map((f, i) => (
            <li key={`${f.template_id ?? f.title}-${i}`} className="rounded bg-background/40 p-2 text-xs">
              <div className="flex items-center gap-2">
                <SeverityBadge level={f.severity} />
                {f.template_id && (
                  <span className="font-mono text-[11px] text-text-secondary">{f.template_id}</span>
                )}
              </div>
              <div className="mt-1">{f.title}</div>
              {(f.url || f.host) && (
                <div className="mt-0.5 font-mono text-[11px] text-text-secondary">
                  {f.url ?? f.host}
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-2 text-xs text-text-secondary">未发现匹配漏洞。</div>
      )}
      <div className="mt-2">
        <RawLogLink scanId={r.scan_id} skill={skillName} />
      </div>
    </div>
  );
}

export const NucleiTemplateScanRenderer: ToolCallContentPartComponent = ({ result }) => (
  <VulnRenderer title="nuclei 模板扫描" skillName="nuclei-template-scan" result={result} />
);

export const FscanVulnScanRenderer: ToolCallContentPartComponent = ({ result }) => (
  <VulnRenderer title="fscan POC 扫描" skillName="fscan-vuln-scan" result={result} />
);
