/**
 * IP Detail Page — PRD §7.2 IP详情页.
 */

import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { fetchIPDetail, type ThreatInfraIPDetail } from "@/lib/threat-intel-client";

export function IPDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { token } = useClient();
  const navigate = useNavigate();
  const [data, setData] = useState<ThreatInfraIPDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    (async () => {
      setLoading(true);
      try { setData(await fetchIPDetail(token, id)); }
      catch { /* ignore */ } finally { setLoading(false); }
    })();
  }, [token, id]);

  if (loading) return <div className="text-slate-400">加载中...</div>;
  if (!data) return <div className="text-slate-400">未找到</div>;

  return (
    <div className="space-y-4">
      <button onClick={() => navigate("/threat-intel/groups")} className="flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900">
        <ArrowLeft className="h-4 w-4" /> 返回
      </button>

      <div className="rounded-xl border border-slate-200 bg-white p-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-mono text-2xl font-bold text-slate-900">{data.ip_address}</h1>
            <p className="mt-1 text-slate-600">{data.ip_type === "c2" ? "C2 Server" : data.ip_type}</p>
          </div>
          <span className={`rounded px-3 py-1 text-sm font-medium ${
            data.status === "active" ? "bg-green-100 text-green-700" :
            data.status === "inactive" ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"
          }`}>
            {data.status === "active" ? "活跃" : data.status === "inactive" ? "不活跃" : "已归档"}
          </span>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3">
          {data.group_name && (
            <div>
              <div className="text-xs text-slate-500">关联组织</div>
              <Link to={`/threat-intel/groups/${data.group_id}`} className="text-sm text-indigo-600 hover:underline">{data.group_name}</Link>
            </div>
          )}
          {data.malware_family && (
            <div><div className="text-xs text-slate-500">恶意软件</div><div className="text-sm font-medium">{data.malware_family}</div></div>
          )}
          {data.geo_country && (
            <div><div className="text-xs text-slate-500">地理位置</div><div className="text-sm font-medium">{data.geo_country}</div></div>
          )}
          {data.asn && (
            <div><div className="text-xs text-slate-500">ASN</div><div className="text-sm font-medium">{data.asn}</div></div>
          )}
          {data.first_seen && (
            <div><div className="text-xs text-slate-500">首次发现</div><div className="text-sm font-medium">{data.first_seen}</div></div>
          )}
          {data.last_seen && (
            <div><div className="text-xs text-slate-500">最近活跃</div><div className="text-sm font-medium">{data.last_seen}</div></div>
          )}
        </div>

        {data.source_refs.length > 0 && (
          <div className="mt-4">
            <h3 className="text-sm font-medium text-slate-700">来源证据</h3>
            <div className="mt-1 space-y-1">
              {data.source_refs.map((ref, i) => (
                <a key={i} href={ref.url ?? "#"} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-sm text-indigo-600 hover:underline">
                  <ExternalLink className="h-3 w-3" /> {ref.source}
                </a>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default IPDetailPage;
