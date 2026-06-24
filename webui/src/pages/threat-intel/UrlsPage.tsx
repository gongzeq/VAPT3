/**
 * Malicious URL List Page — Gap 1.
 *
 * Paginated list of threat infrastructure URLs from URLhaus / PhishTank feeds.
 * Supports search by URL string, filter by source and URL type.
 */

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, Link2, Activity } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { fetchThreatURLs, type ThreatURLSummary } from "@/lib/threat-intel-client";

export function UrlsPage() {
  const { token } = useClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [urls, setUrls] = useState<ThreatURLSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const q = searchParams.get("q") ?? "";
  const source = searchParams.get("source") ?? "";
  const urlType = searchParams.get("url_type") ?? "";
  const page = parseInt(searchParams.get("page") ?? "1", 10);

  const loadUrls = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchThreatURLs(token, {
        q: q || undefined,
        source: source || undefined,
        url_type: urlType || undefined,
        page,
        page_size: 20,
      });
      setUrls(result.items);
      setTotal(result.total);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [token, q, source, urlType, page]);

  useEffect(() => { loadUrls(); }, [loadUrls]);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-slate-900">恶意URL</h1>

      <div className="flex gap-2">
        <input
          value={q}
          onChange={(e) => {
            const p = new URLSearchParams(searchParams);
            if (e.target.value) p.set("q", e.target.value); else p.delete("q");
            p.delete("page");
            setSearchParams(p);
          }}
          placeholder="搜索URL..."
          className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm"
        />
        <select
          value={source}
          onChange={(e) => {
            const p = new URLSearchParams(searchParams);
            if (e.target.value) p.set("source", e.target.value); else p.delete("source");
            p.delete("page");
            setSearchParams(p);
          }}
          className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
        >
          <option value="">全部来源</option>
          <option value="urlhaus">URLhaus</option>
          <option value="phishtank">PhishTank</option>
        </select>
        <select
          value={urlType}
          onChange={(e) => {
            const p = new URLSearchParams(searchParams);
            if (e.target.value) p.set("url_type", e.target.value); else p.delete("url_type");
            p.delete("page");
            setSearchParams(p);
          }}
          className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
        >
          <option value="">全部类型</option>
          <option value="phishing">钓鱼</option>
          <option value="malware_download">恶意下载</option>
          <option value="other">其他</option>
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
            {urls.map((u) => (
              <div
                key={u.id}
                className="rounded-lg border border-slate-200 bg-white p-4 hover:shadow-md transition-shadow"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Link2 className="h-4 w-4 text-slate-400" />
                    <span className="font-mono text-sm text-slate-900 truncate max-w-[400px]">{u.url}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{u.source}</span>
                    {u.url_type && u.url_type !== "other" && (
                      <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-700">{u.url_type}</span>
                    )}
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                      u.status === "active" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"
                    }`}>
                      {u.status === "active" ? "活跃" : "非活跃"}
                    </span>
                  </div>
                </div>
                <div className="mt-1 flex gap-4 text-xs text-slate-500">
                  {u.host && <span>Host: {u.host}</span>}
                  {u.malware_family && <span>木马: {u.malware_family}</span>}
                  {u.geo_country && <span>国家: {u.geo_country}</span>}
                  {u.last_seen && <span>最近: {new Date(u.last_seen).toLocaleDateString("zh-CN")}</span>}
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

export default UrlsPage;
