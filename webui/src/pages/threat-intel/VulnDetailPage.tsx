/**
 * Vulnerability Detail Page — PRD §7.2 漏洞详情页.
 */

import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import { fetchVulnDetail, type ThreatVulnDetail } from "@/lib/threat-intel-client";

export function VulnDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { token } = useClient();
  const navigate = useNavigate();
  const [data, setData] = useState<ThreatVulnDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    (async () => {
      setLoading(true);
      try {
        const d = await fetchVulnDetail(token, id);
        setData(d);
      } catch (e) {
        setError((e as Error).message);
      } finally { setLoading(false); }
    })();
  }, [token, id]);

  if (loading) return <div className="text-slate-400">加载中...</div>;
  if (error) return <div className="text-red-600">{error}</div>;
  if (!data) return <div className="text-slate-400">未找到</div>;

  return (
    <div className="space-y-4">
      <button onClick={() => navigate("/threat-intel/vulns")} className="flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900">
        <ArrowLeft className="h-4 w-4" /> 返回漏洞列表
      </button>

      <div className="rounded-xl border border-slate-200 bg-white p-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-mono text-2xl font-bold text-slate-900">{data.cve_id}</h1>
            {data.title && <p className="mt-1 text-slate-600">{data.title}</p>}
          </div>
          <span className={`rounded px-3 py-1 text-sm font-medium ${
            data.severity === "critical" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"
          }`}>
            {data.severity === "critical" ? "严重" : "高危"}
          </span>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="text-xs text-slate-500">CVSS</div>
            <div className="text-lg font-bold">{data.cvss_score ?? "待补充"}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="text-xs text-slate-500">CISA KEV</div>
            <div className="text-lg font-bold">{data.is_cisa_kev ? "Yes" : "No"}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="text-xs text-slate-500">供应链</div>
            <div className="text-lg font-bold">{data.is_supply_chain ? "Yes" : "No"}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="text-xs text-slate-500">PoC / Exploit</div>
            <div className="text-lg font-bold">{data.has_poc ? "Yes" : "No"} / {data.exploit_available ? "Yes" : "No"}</div>
          </div>
        </div>

        {data.description && (
          <div className="mt-4">
            <h3 className="text-sm font-medium text-slate-700">描述</h3>
            <p className="mt-1 text-sm text-slate-600 whitespace-pre-wrap">{data.description}</p>
          </div>
        )}

        {data.affected_products.length > 0 && (
          <div className="mt-4">
            <h3 className="text-sm font-medium text-slate-700">影响产品</h3>
            <ul className="mt-1 space-y-1">
              {data.affected_products.map((p, i) => (
                <li key={i} className="font-mono text-xs text-slate-600">{p}</li>
              ))}
            </ul>
          </div>
        )}

        {data.exploiting_groups.length > 0 && (
          <div className="mt-4">
            <h3 className="text-sm font-medium text-slate-700">利用该漏洞的组织</h3>
            <div className="mt-1 space-y-1">
              {data.exploiting_groups.map((g) => (
                <Link key={g.group_id} to={`/threat-intel/groups/${g.group_id}`} className="block text-sm text-indigo-600 hover:underline">
                  {g.group_name} ({g.relationship_type}, 置信度 {g.confidence})
                </Link>
              ))}
            </div>
          </div>
        )}

        {data.source_refs.length > 0 && (
          <div className="mt-4">
            <h3 className="text-sm font-medium text-slate-700">来源证据</h3>
            <div className="mt-1 space-y-1">
              {data.source_refs.map((ref, i) => (
                <a key={i} href={ref.url ?? "#"} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-sm text-indigo-600 hover:underline">
                  <ExternalLink className="h-3 w-3" /> {ref.source} {ref.url ? `— ${ref.url}` : ""}
                </a>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default VulnDetailPage;
