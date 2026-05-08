import type { ToolCallContentPartComponent } from "@assistant-ui/react";

import { RawLogLink, StatusPill } from "./_shared";

interface PortRow {
  host: string;
  port: number;
  protocol?: string;
  service?: string;
  product?: string;
  version?: string;
  state?: string;
}

interface NmapResult {
  status?: string;
  scan_id?: string;
  totals?: { hosts: number; open_ports: number };
  ports?: PortRow[];
}

export const NmapPortScanRenderer: ToolCallContentPartComponent = ({ args, result }) => {
  const r = (result ?? {}) as NmapResult;
  const targets = ((args as { targets?: string[] } | undefined)?.targets ?? []).join(", ");
  return (
    <div className="my-2 rounded-md border border-border bg-card p-3 text-sm">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="font-medium">nmap 端口扫描</div>
          <div className="text-xs text-text-secondary">目标：{targets || "(未指定)"}</div>
        </div>
        <StatusPill status={r.status ?? "running"} />
      </div>
      {r.totals && (
        <div className="mb-2 flex gap-4 text-xs text-text-secondary">
          <span>主机 {r.totals.hosts}</span>
          <span>开放端口 {r.totals.open_ports}</span>
        </div>
      )}
      {r.ports && r.ports.length > 0 && (
        <table className="mt-2 w-full border-collapse text-xs">
          <thead className="text-text-secondary">
            <tr>
              <th className="border-b border-border px-2 py-1 text-left">主机</th>
              <th className="border-b border-border px-2 py-1 text-left">端口</th>
              <th className="border-b border-border px-2 py-1 text-left">服务</th>
              <th className="border-b border-border px-2 py-1 text-left">版本</th>
            </tr>
          </thead>
          <tbody>
            {r.ports.slice(0, 50).map((p, i) => (
              <tr key={`${p.host}-${p.port}-${i}`}>
                <td className="border-b border-border-subtle px-2 py-1 font-mono">{p.host}</td>
                <td className="border-b border-border-subtle px-2 py-1">
                  {p.port}/{p.protocol ?? "tcp"}
                </td>
                <td className="border-b border-border-subtle px-2 py-1">{p.service ?? "-"}</td>
                <td className="border-b border-border-subtle px-2 py-1">
                  {[p.product, p.version].filter(Boolean).join(" ") || "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="mt-2">
        <RawLogLink scanId={r.scan_id} skill="nmap-port-scan" />
      </div>
    </div>
  );
};
