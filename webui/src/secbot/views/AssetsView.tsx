import * as React from "react";
import { useEffect, useState } from "react";

import { secbotApi, type Asset } from "../api";
import { SeverityBadge, type Severity } from "../renderers/_shared";

/**
 * Read-only assets table backed by /api/assets. The orchestrator's CMDB-write
 * skills mutate this dataset, so polling on focus is enough — there is no
 * client-side editing path.
 */
export function AssetsView() {
  const [rows, setRows] = useState<Asset[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    secbotApi
      .listAssets()
      .then((data) => {
        if (!cancel) setRows(data);
      })
      .catch((e) => !cancel && setError(String(e)));
    return () => {
      cancel = true;
    };
  }, []);

  if (error) return <div className="p-4 text-red-400">加载失败：{error}</div>;
  if (!rows) return <div className="p-4 text-text-secondary">加载中…</div>;
  if (rows.length === 0)
    return <div className="p-4 text-text-secondary">尚无资产，请先运行一次扫描。</div>;

  return (
    <div className="p-4">
      <header className="mb-3 flex items-baseline justify-between">
        <h1 className="text-lg font-semibold">资产</h1>
        <span className="text-xs text-text-secondary">{rows.length} 个资产</span>
      </header>
      <table className="w-full border-collapse text-sm">
        <thead className="text-text-secondary">
          <tr>
            <th className="border-b border-border px-2 py-1.5 text-left">IP</th>
            <th className="border-b border-border px-2 py-1.5 text-left">主机名</th>
            <th className="border-b border-border px-2 py-1.5 text-left">OS</th>
            <th className="border-b border-border px-2 py-1.5 text-left">服务</th>
            <th className="border-b border-border px-2 py-1.5 text-left">漏洞</th>
            <th className="border-b border-border px-2 py-1.5 text-left">最高等级</th>
            <th className="border-b border-border px-2 py-1.5 text-left">最近发现</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id} className="hover:bg-card/50">
              <td className="border-b border-border-subtle px-2 py-1.5 font-mono">{a.ip}</td>
              <td className="border-b border-border-subtle px-2 py-1.5">{a.hostname ?? "-"}</td>
              <td className="border-b border-border-subtle px-2 py-1.5">{a.os ?? "-"}</td>
              <td className="border-b border-border-subtle px-2 py-1.5">{a.service_count ?? 0}</td>
              <td className="border-b border-border-subtle px-2 py-1.5">{a.vuln_count ?? 0}</td>
              <td className="border-b border-border-subtle px-2 py-1.5">
                {a.severity_max ? <SeverityBadge level={a.severity_max as Severity} /> : "-"}
              </td>
              <td className="border-b border-border-subtle px-2 py-1.5 text-xs text-text-secondary">
                {a.last_seen ?? "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
