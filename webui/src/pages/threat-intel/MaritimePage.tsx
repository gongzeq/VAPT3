/**
 * Maritime Events Page — PRD §7.2 海事安全事件页.
 */

import { useCallback, useEffect, useState } from "react";
import { Skull, AlertTriangle, Radio, Compass, ExternalLink } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { reviewMaritimeEvent } from "@/lib/threat-intel-client";

interface MaritimeEvent {
  id: string;
  event_type: string;
  title: string;
  description: string | null;
  location: { lat?: number; lon?: number; region?: string; description?: string } | null;
  severity: string;
  event_date: string;
  source: string;
  source_url: string | null;
  extraction_confidence: number;
  verification_status: string;
}

// We need to use the maritime list endpoint from the existing API
async function fetchMaritimeEvents(token: string, params?: Record<string, string>): Promise<{ items: MaritimeEvent[]; total: number }> {
  const search = new URLSearchParams(params);
  const qs = search.toString();
  const res = await fetch(`/api/threat-intel/maritime${qs ? `?${qs}` : ""}`, {
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

const eventTypeIcons: Record<string, typeof Skull> = {
  piracy: Skull,
  security_warning: AlertTriangle,
  gnss_interference: Radio,
  navigation_warning: Compass,
  other: AlertTriangle,
};

export function MaritimePage() {
  const { token } = useClient();
  const [events, setEvents] = useState<MaritimeEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState({ event_type: "", severity: "", verification_status: "" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchMaritimeEvents(token, {
        event_type: filter.event_type,
        severity: filter.severity,
        verification_status: filter.verification_status,
      });
      setEvents(result.items || []);
      setTotal(result.total || 0);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [token, filter]);

  useEffect(() => { load(); }, [load]);

  const handleReview = async (eventId: string, status: "confirmed" | "dismissed") => {
    await reviewMaritimeEvent(token, eventId, status);
    load();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">海事安全事件</h1>
        <span className="text-sm text-slate-600">共 {total} 条</span>
      </div>

      <div className="flex gap-2">
        <select value={filter.event_type} onChange={(e) => setFilter({ ...filter, event_type: e.target.value })} className="rounded-lg border border-slate-200 px-3 py-2 text-sm">
          <option value="">全部类型</option>
          <option value="piracy">海盗袭击</option>
          <option value="security_warning">安全警告</option>
          <option value="gnss_interference">GNSS干扰</option>
          <option value="navigation_warning">航行警告</option>
        </select>
        <select value={filter.severity} onChange={(e) => setFilter({ ...filter, severity: e.target.value })} className="rounded-lg border border-slate-200 px-3 py-2 text-sm">
          <option value="">全部严重性</option>
          <option value="critical">严重</option>
          <option value="high">高</option>
          <option value="medium">中</option>
          <option value="low">低</option>
        </select>
        <select value={filter.verification_status} onChange={(e) => setFilter({ ...filter, verification_status: e.target.value })} className="rounded-lg border border-slate-200 px-3 py-2 text-sm">
          <option value="">全部状态</option>
          <option value="unreviewed">待审</option>
          <option value="confirmed">已确认</option>
          <option value="dismissed">已驳回</option>
        </select>
      </div>

      {loading ? (
        <div className="text-slate-400">加载中...</div>
      ) : events.length === 0 ? (
        <div className="text-slate-400">暂无海事事件</div>
      ) : (
        <div className="space-y-3">
          {events.map((event) => {
            const Icon = eventTypeIcons[event.event_type] || AlertTriangle;
            return (
              <div key={event.id} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3">
                    <Icon className="mt-0.5 h-5 w-5 text-slate-600" />
                    <div>
                      <h3 className="font-medium text-slate-900">{event.title}</h3>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                        <span>{new Date(event.event_date).toLocaleString("zh-CN")}</span>
                        <span className={`rounded px-2 py-0.5 font-medium ${
                          event.severity === "critical" ? "bg-red-100 text-red-700" :
                          event.severity === "high" ? "bg-amber-100 text-amber-700" :
                          "bg-slate-100 text-slate-600"
                        }`}>{event.severity}</span>
                        <span className={`rounded px-2 py-0.5 ${
                          event.verification_status === "confirmed" ? "bg-green-100 text-green-700" :
                          event.verification_status === "dismissed" ? "bg-slate-100 text-slate-500" :
                          "bg-amber-100 text-amber-700"
                        }`}>
                          {event.verification_status === "confirmed" ? "已确认" :
                           event.verification_status === "dismissed" ? "已驳回" : "待审"}
                        </span>
                        <span>置信度: {event.extraction_confidence.toFixed(2)}</span>
                      </div>
                    </div>
                  </div>
                  {event.verification_status === "unreviewed" && (
                    <div className="flex gap-2">
                      <button onClick={() => handleReview(event.id, "confirmed")} className="rounded bg-green-50 px-3 py-1 text-sm text-green-600 hover:bg-green-100">确认</button>
                      <button onClick={() => handleReview(event.id, "dismissed")} className="rounded bg-slate-50 px-3 py-1 text-sm text-slate-600 hover:bg-slate-100">驳回</button>
                    </div>
                  )}
                </div>
                {event.description && <p className="mt-2 text-sm text-slate-600">{event.description}</p>}
                {event.location && (
                  <p className="mt-1 text-xs text-slate-400">
                    位置: {event.location.region || event.location.description || "未知"}
                    {event.location.lat && event.location.lon && ` (${event.location.lat}, ${event.location.lon})`}
                  </p>
                )}
                {event.source_url && (
                  <a href={event.source_url} target="_blank" rel="noopener noreferrer" className="mt-2 flex items-center gap-1 text-xs text-indigo-600 hover:underline">
                    <ExternalLink className="h-3 w-3" /> 来源: {event.source}
                  </a>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default MaritimePage;
