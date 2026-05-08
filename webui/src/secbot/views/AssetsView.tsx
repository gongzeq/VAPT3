import { useEffect, useMemo, useState } from "react";

import { Metric } from "@/components/tremor/metric";
import { cn } from "@/lib/utils";

import { secbotApi, type Asset } from "../api";
import { SeverityBadge, type Severity } from "../renderers/_shared";

/**
 * Read-only assets table backed by /api/assets. The orchestrator's CMDB-write
 * skills mutate this dataset, so polling on focus is enough — there is no
 * client-side editing path.
 *
 * Ocean-tech styling (PR4-R5):
 *   - Header uses a brand-deep gradient with three KPI `<Metric>` tiles
 *     (total assets, total vulns, critical count) for at-a-glance posture.
 *   - Row hover uses brand-light tint (0.08) instead of card/50 so the
 *     palette stays on-theme.
 *   - Status colors moved to semantic tokens (error / muted / primary).
 *
 * NOTE (deferred to PR4 Phase B): replacing the native table with
 * `@tanstack/react-table` + shadcn DataTable (sorting/filtering/pagination)
 * is a non-trivial refactor and lives in a follow-up PR.
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

  const totals = useMemo(() => {
    const r = rows ?? [];
    const vulns = r.reduce((sum, a) => sum + (a.vuln_count ?? 0), 0);
    const critical = r.filter((a) => a.severity_max === "critical").length;
    return { assets: r.length, vulns, critical };
  }, [rows]);

  if (error)
    return (
      <div className="p-4 text-[hsl(var(--error))]">加载失败：{error}</div>
    );
  if (!rows) return <div className="p-4 text-text-secondary">加载中…</div>;
  if (rows.length === 0)
    return (
      <div className="p-4 text-text-secondary">尚无资产，请先运行一次扫描。</div>
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
              "linear-gradient(135deg, hsl(var(--brand-deep) / 0.15) 0%, transparent 45%, hsl(var(--primary) / 0.10) 100%)",
          }}
        />
        <div className="relative z-[1] flex items-baseline justify-between">
          <h1 className="text-lg font-semibold">资产</h1>
          <span className="text-xs text-text-secondary">
            {rows.length} 个资产
          </span>
        </div>
        <div className="relative z-[1] mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <KpiTile label="资产总数" value={totals.assets} color="text-foreground" />
          <KpiTile
            label="漏洞总数"
            value={totals.vulns}
            color="text-[hsl(var(--primary))]"
          />
          <KpiTile
            label="Critical 资产"
            value={totals.critical}
            color="text-severity-critical"
          />
        </div>
      </header>
      <table className="w-full border-collapse text-sm">
        <thead className="text-text-secondary">
          <tr>
            <th className="border-b border-border px-2 py-1.5 text-left">IP</th>
            <th className="border-b border-border px-2 py-1.5 text-left">
              主机名
            </th>
            <th className="border-b border-border px-2 py-1.5 text-left">OS</th>
            <th className="border-b border-border px-2 py-1.5 text-left">服务</th>
            <th className="border-b border-border px-2 py-1.5 text-left">漏洞</th>
            <th className="border-b border-border px-2 py-1.5 text-left">
              最高等级
            </th>
            <th className="border-b border-border px-2 py-1.5 text-left">
              最近发现
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr
              key={a.id}
              className="transition-colors hover:bg-[hsl(var(--brand-light)/0.08)] motion-reduce:transition-none"
            >
              <td className="border-b border-border-subtle px-2 py-1.5 font-mono">
                {a.ip}
              </td>
              <td className="border-b border-border-subtle px-2 py-1.5">
                {a.hostname ?? "-"}
              </td>
              <td className="border-b border-border-subtle px-2 py-1.5">
                {a.os ?? "-"}
              </td>
              <td className="border-b border-border-subtle px-2 py-1.5">
                {a.service_count ?? 0}
              </td>
              <td className="border-b border-border-subtle px-2 py-1.5">
                {a.vuln_count ?? 0}
              </td>
              <td className="border-b border-border-subtle px-2 py-1.5">
                {a.severity_max ? (
                  <SeverityBadge level={a.severity_max as Severity} />
                ) : (
                  "-"
                )}
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

function KpiTile({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div
      className={cn(
        "rounded-md border px-3 py-2",
        "border-[hsl(var(--brand-deep)/0.20)] bg-background/60 backdrop-blur-[1px]",
      )}
    >
      <div className="text-[11px] uppercase tracking-wide text-text-secondary">
        {label}
      </div>
      <Metric className={cn("text-2xl", color)}>{value}</Metric>
    </div>
  );
}
