/**
 * C2 IP List Page — Gap 3.
 *
 * Paginated list of threat infrastructure IPs.
 * Supports search, filter by IP type and status, links to IP detail page.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, Server, Activity } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { fetchThreatIPs, type ThreatInfraIPSummary } from "@/lib/threat-intel-client";

export function IPListPage() {
  const { token } = useClient();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [ips, setIps] = useState<ThreatInfraIPSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const q = searchParams.get("q") ?? "";
  const ipType = searchParams.get("ip_type") ?? "";
  const status = searchParams.get("status") ?? "";
  const page = parseInt(searchParams.get("page") ?? "1", 10);

  const loadIPs = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchThreatIPs(token, {
        q: q || undefined,
        ip_type: ipType || undefined,
        status: status || undefined,
        page,
        page_size: 20,
      });
      setIps(result.items);
      setTotal(result.total);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [token, q, ipType, status, page]);

  useEffect(() => { loadIPs(); }, [loadIPs]);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-slate-900">C2 IP</h1>

      <div className="flex gap-2">
        <input
          value={q}
          onChange={(e) => {
            const p = new URLSearchParams(searchParams);
            if (e.target.value) p.set("q", e.target.value); else p.delete("q");
            p.delete("page");
            setSearchParams(p);
          }}
          placeholder="搜索IP地址..."
          className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm"
        />
        <select
          value={ipType}
          onChange={(e) => {
            const p = new URLSearchParams(searchParams);
            if (e.target.value) p.set("ip_type", e.target.value); else p.delete("ip_type");
            p.delete("page");
            setSearchParams(p);
          }}
          className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
        >
          <option value="">全部类型</option>
          <option value="c2">C2</option>
          <option value="proxy">代理</option>
          <option value="relay">中继</option>
        </select>
        <select
          value={status}
          onChange={(e) => {
            const p = new URLSearchParams(searchParams);
            if (e.target.value) p.set("status", e.target.value); else p.delete("status");
            p.delete("page");
            setSearchParams(p);
          }}
          className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
        >
          <option value="">全部状态</option>
          <option value="active">活跃</option>
          <option value="inactive">非活跃</option>
        </select>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-slate-400">
          <Activity className="h-4 w-4 animate-pulse" />
          加载中...
        </div>
      ) : (
        <>
          <div className="space-y-2">
            {ips.map((ip) => (
              <div
                key={ip.id}
                onClick={() => navigate(`/threat-intel/ips/${ip.id}`)}
                className="cursor-pointer rounded-lg border border-slate-200 bg-white p-4 hover:shadow-md transition-shadow"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Server className="h-4 w-4 text-amber-500" />
                    <span className="font-mono text-sm font-medium text-slate-900">{ip.ip_address}</span>
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{ip.ip_type}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {ip.malware_family && (
                      <span className="rounded bg-rose-50 px-2 py-0.5 text-xs text-rose-600">{ip.malware_family}</span>
                    )}
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                      ip.status === "active" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"
                    }`}>
                      {ip.status === "active" ? "活跃" : "非活跃"}
                    </span>
                  </div>
                </div>
                <div className="mt-1 flex gap-4 text-xs text-slate-500">
                  {ip.geo_country && <span>国家: {ip.geo_country}</span>}
                  {ip.asn && <span>ASN: {ip.asn}</span>}
                  {ip.last_seen && <span>最近: {new Date(ip.last_seen).toLocaleDateString("zh-CN")}</span>}
                  <span>来源: {ip.source}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between text-sm text-slate-600">
            <span>共 {total} 条</span>
            <div className="flex gap-2">
              <button
                disabled={page <= 1}
                onClick={() => { const p = new URLSearchParams(searchParams); p.set("page", String(page - 1)); setSearchParams(p); }}
                className="rounded-lg border px-3 py-1 disabled:opacity-50"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="px-3 py-1">第 {page} 页</span>
              <button
                disabled={page * 20 >= total}
                onClick={() => { const p = new URLSearchParams(searchParams); p.set("page", String(page + 1)); setSearchParams(p); }}
                className="rounded-lg border px-3 py-1 disabled:opacity-50"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default IPListPage;
