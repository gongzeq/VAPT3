/**
 * Ransomware Events Page — Gap 2.
 *
 * Paginated list of ransomware incidents from ransomware.live feed.
 * Supports filter by group name, victim industry, severity, and date range.
 */

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, Activity, AlertTriangle, Database } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { fetchRansomwareEvents, type RansomwareEventSummary } from "@/lib/threat-intel-client";

export function RansomwarePage() {
  const { token } = useClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [events, setEvents] = useState<RansomwareEventSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const groupName = searchParams.get("group_name") ?? "";
  const severity = searchParams.get("severity") ?? "";
  const fromDate = searchParams.get("from") ?? "";
  const toDate = searchParams.get("to") ?? "";
  const page = parseInt(searchParams.get("page") ?? "1", 10);

  const loadEvents = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchRansomwareEvents(token, {
        group_name: groupName || undefined,
        severity: severity || undefined,
        from: fromDate || undefined,
        to: toDate || undefined,
        page,
        page_size: 20,
      });
      setEvents(result.items);
      setTotal(result.total);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [token, groupName, severity, fromDate, toDate, page]);

  useEffect(() => { loadEvents(); }, [loadEvents]);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-slate-900">勒索事件</h1>

      <div className="flex flex-wrap gap-2">
        <input
          value={groupName}
          onChange={(e) => {
            const p = new URLSearchParams(searchParams);
            if (e.target.value) p.set("group_name", e.target.value); else p.delete("group_name");
            p.delete("page");
            setSearchParams(p);
          }}
          placeholder="勒索组织名称..."
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
          <option value="medium">中危</option>
          <option value="low">低危</option>
        </select>
        <input
          type="date"
          value={fromDate}
          onChange={(e) => {
            const p = new URLSearchParams(searchParams);
            if (e.target.value) p.set("from", e.target.value); else p.delete("from");
            p.delete("page");
            setSearchParams(p);
          }}
          className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
        />
        <span className="text-slate-400 self-center">至</span>
        <input
          type="date"
          value={toDate}
          onChange={(e) => {
            const p = new URLSearchParams(searchParams);
            if (e.target.value) p.set("to", e.target.value); else p.delete("to");
            p.delete("page");
            setSearchParams(p);
          }}
          className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
        />
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-slate-400">
          <Activity className="h-4 w-4 animate-pulse" />
          加载中...
        </div>
      ) : (
        <>
          <div className="space-y-2">
            {events.map((e) => (
              <div
                key={e.id}
                className="rounded-lg border border-slate-200 bg-white p-4 hover:shadow-md transition-shadow"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <AlertTriangle className="h-4 w-4 text-red-500" />
                    <span className="font-medium text-slate-900">{e.victim_name}</span>
                    <span className="text-sm text-slate-500">← {e.group_name}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {e.data_leaked && (
                      <span className="flex items-center gap-1 rounded bg-red-100 px-2 py-0.5 text-xs text-red-700">
                        <Database className="h-3 w-3" />
                        数据泄露
                      </span>
                    )}
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                      e.severity === "critical" ? "bg-red-100 text-red-700" :
                      e.severity === "high" ? "bg-orange-100 text-orange-700" :
                      "bg-amber-100 text-amber-700"
                    }`}>
                      {e.severity === "critical" ? "严重" : e.severity === "high" ? "高危" : e.severity}
                    </span>
                  </div>
                </div>
                <div className="mt-1 flex gap-4 text-xs text-slate-500">
                  {e.victim_industry && <span>行业: {e.victim_industry}</span>}
                  {e.victim_country && <span>国家: {e.victim_country}</span>}
                  {e.breach_date && <span>入侵: {new Date(e.breach_date).toLocaleDateString("zh-CN")}</span>}
                  {e.post_url && (
                    <a href={e.post_url} target="_blank" rel="noopener noreferrer" className="text-indigo-500 hover:underline">
                      原文链接
                    </a>
                  )}
                </div>
                {e.description && <p className="mt-1 text-sm text-slate-600">{e.description}</p>}
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

export default RansomwarePage;
