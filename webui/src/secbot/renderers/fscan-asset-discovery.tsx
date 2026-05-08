import type { ToolCallContentPartComponent } from "@assistant-ui/react";

import { RawLogLink, StatusPill } from "./_shared";

interface FscanAssetResult {
  status?: string;
  scan_id?: string;
  hosts_up?: string[];
  totals?: { hosts: number };
}

export const FscanAssetDiscoveryRenderer: ToolCallContentPartComponent = ({ args, result }) => {
  const r = (result ?? {}) as FscanAssetResult;
  const cidr = (args as { cidr?: string } | undefined)?.cidr ?? "";
  const hosts = r.hosts_up ?? [];
  return (
    <div className="my-2 rounded-md border border-border bg-card p-3 text-sm">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="font-medium">fscan 资产发现</div>
          <div className="text-xs text-text-secondary">网段：{cidr || "(未指定)"}</div>
        </div>
        <StatusPill status={r.status ?? "running"} />
      </div>
      <div className="mb-2 text-xs text-text-secondary">存活主机 {hosts.length}</div>
      {hosts.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {hosts.slice(0, 64).map((h) => (
            <span
              key={h}
              className="rounded border border-border-subtle bg-background/40 px-1.5 py-0.5 font-mono text-[11px]"
            >
              {h}
            </span>
          ))}
          {hosts.length > 64 && (
            <span className="text-[11px] text-text-secondary">… +{hosts.length - 64}</span>
          )}
        </div>
      )}
      <div className="mt-2">
        <RawLogLink scanId={r.scan_id} skill="fscan-asset-discovery" />
      </div>
    </div>
  );
};
