/**
 * Vulnerability List Page — PRD §7.2 漏洞列表页.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { fetchVulns, type ThreatVulnSummary } from "@/lib/threat-intel-client";

export function VulnsPage() {
  const { token } = useClient();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [vulns, setVulns] = useState<ThreatVulnSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const q = searchParams.get("q") ?? "";
  const severity = searchParams.get("severity") ?? "";
  const page = parseInt(searchParams.get("page") ?? "1", 10);

  const loadVulns = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchVulns(token, {
        q: q || undefined, severity: severity || undefined, page, page_size: 20,
      });
      setVulns(result.items);
      setTotal(result.total);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [token, q, severity, page]);

  useEffect(() => { loadVulns(); }, [loadVulns]);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-slate-900">高危漏洞</h1>
      <div className="flex gap-2">
        <input
          value={q}
          onChange={(e) => {
            const p = new URLSearchParams(searchParams);
            if (e.target.value) p.set("q", e.target.value); else p.delete("q");
            p.delete("page");
            setSearchParams(p);
          }}
          placeholder="搜索CVE ID或标题..."
          className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm"
        />
        <select
          value={severity}
          onChange={(e) => {
            const p = new URLSearchParams(searchParams);
            if (e.target.value) p.set("severity", e.target.value); else p.delete("severity");
            setSearchParams(p);
          }}
          className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
        >
          <option value="">全部严重性</option>
          <option value="critical">严重</option>
          <option value="high">高危</option>
        </select>
      </div>

      {loading ? (
        <div className="text-slate-400">加载中...</div>
      ) : (
        <>
          <div className="space-y-2">
            {vulns.map((v) => (
              <div
                key={v.id}
                onClick={() => navigate(`/threat-intel/vulns/${v.id}`)}
                className="cursor-pointer rounded-lg border border-slate-200 bg-white p-4 hover:shadow-md transition-shadow"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-sm font-medium text-slate-900">{v.cve_id}</span>
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                      v.severity === "critical" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"
                    }`}>
                      {v.severity === "critical" ? "严重" : "高危"}
                    </span>
                    {v.is_cisa_kev && <span className="rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-700">KEV</span>}
                    {v.is_supply_chain && <span className="rounded bg-green-100 px-2 py-0.5 text-xs text-green-700">供应链</span>}
                    {v.has_poc && <span className="rounded bg-purple-100 px-2 py-0.5 text-xs text-purple-700">PoC</span>}
                  </div>
                  {v.cvss_score && <span className="text-sm font-bold text-slate-700">{v.cvss_score}</span>}
                </div>
                {v.title && <p className="mt-1 text-sm text-slate-600">{v.title}</p>}
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

export default VulnsPage;
