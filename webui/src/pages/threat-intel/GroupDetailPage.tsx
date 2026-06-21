/**
 * Threat Intel Group Detail Page — PRD §7.2 威胁组织详情页.
 *
 * Header with name + aliases + watch toggle.
 * Tabs: C2 IPs / Malware / Vulnerabilities / Aliases.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Star, StarOff, Globe, Calendar, Shield } from "lucide-react";
import { useClient } from "@/providers/ClientProvider";
import {
  fetchGroupDetail,
  watchGroup,
  unwatchGroup,
  type ThreatGroupDetail,
} from "@/lib/threat-intel-client";
import { cn } from "@/lib/utils";

type TabKey = "ips" | "malware" | "vulns" | "aliases";

export function GroupDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { token } = useClient();
  const navigate = useNavigate();
  const [group, setGroup] = useState<ThreatGroupDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("ips");

  const loadGroup = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchGroupDetail(token, id);
      setGroup(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token, id]);

  useEffect(() => { loadGroup(); }, [loadGroup]);

  const handleToggleWatch = async () => {
    if (!group || !id) return;
    try {
      if (group.is_watched) {
        await unwatchGroup(token, id);
      } else {
        await watchGroup(token, id);
      }
      loadGroup();
    } catch (e) {
      window.alert(`操作失败: ${(e as Error).message}`);
    }
  };

  if (loading) {
    return <div className="flex h-40 items-center justify-center text-sm text-slate-400">加载中…</div>;
  }

  if (error) {
    return <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>;
  }

  if (!group) return null;

  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: "ips", label: "C2 IP", count: group.infra_ips.length },
    { key: "malware", label: "木马家族", count: group.malware_families.length },
    { key: "vulns", label: "已知漏洞", count: group.vulnerabilities.length },
    { key: "aliases", label: "APT别名", count: group.apt_aliases.length },
  ];

  return (
    <div className="space-y-4">
      {/* Back */}
      <button
        type="button"
        onClick={() => navigate("/threat-intel/groups")}
        className="flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700"
      >
        <ArrowLeft className="h-4 w-4" />
        返回组织列表
      </button>

      {/* Header */}
      <div className="rounded-xl border border-slate-200 bg-white p-6">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50">
                <Shield className="h-5 w-5 text-indigo-600" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-slate-900">{group.name}</h1>
                {group.aliases.length > 0 && (
                  <p className="text-sm text-slate-500">
                    {group.aliases.join(" · ")}
                  </p>
                )}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={handleToggleWatch}
            className={cn(
              "flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm transition-colors",
              group.is_watched
                ? "border-amber-300 bg-amber-50 text-amber-700"
                : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
            )}
          >
            {group.is_watched ? (
              <Star className="h-4 w-4 fill-amber-400 text-amber-400" />
            ) : (
              <StarOff className="h-4 w-4" />
            )}
            {group.is_watched ? "已关注" : "关注"}
          </button>
        </div>

        {/* Basic info */}
        <div className="mt-4 grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
          {group.mitre_id && (
            <InfoItem label="MITRE ID" value={group.mitre_id} />
          )}
          {group.origin_country && (
            <InfoItem label="归因国家" value={group.origin_country} icon={<Globe className="h-3 w-3" />} />
          )}
          {group.first_seen && (
            <InfoItem label="首次活动" value={group.first_seen} icon={<Calendar className="h-3 w-3" />} />
          )}
          {group.last_seen && (
            <InfoItem label="最近活跃" value={group.last_seen} icon={<Calendar className="h-3 w-3" />} />
          )}
        </div>

        {group.description && (
          <p className="mt-4 text-sm leading-relaxed text-slate-600">{group.description}</p>
        )}

        {group.target_sectors.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {group.target_sectors.map((s) => (
              <span key={s} className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                {s}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-200">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              "flex items-center gap-1.5 border-b-2 px-4 py-2 text-sm transition-colors",
              activeTab === tab.key
                ? "border-indigo-500 text-indigo-600"
                : "border-transparent text-slate-500 hover:text-slate-700",
            )}
          >
            {tab.label}
            <span className="rounded-md bg-slate-100 px-1.5 text-xs text-slate-500">{tab.count}</span>
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="rounded-xl border border-slate-200 bg-white">
        {activeTab === "ips" && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs text-slate-500">
                <th className="px-4 py-2.5 font-medium">IP地址</th>
                <th className="px-4 py-2.5 font-medium">类型</th>
                <th className="px-4 py-2.5 font-medium">木马家族</th>
                <th className="px-4 py-2.5 font-medium">国家</th>
                <th className="px-4 py-2.5 font-medium">最近发现</th>
                <th className="px-4 py-2.5 font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              {group.infra_ips.map((ip) => (
                <tr key={ip.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-2.5 font-mono text-slate-700">{ip.ip_address}</td>
                  <td className="px-4 py-2.5 text-slate-500">{ip.ip_type}</td>
                  <td className="px-4 py-2.5 text-slate-500">{ip.malware_family || "—"}</td>
                  <td className="px-4 py-2.5 text-slate-500">{ip.geo_country || "—"}</td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {ip.last_seen ? new Date(ip.last_seen).toLocaleDateString("zh-CN") : "—"}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={cn(
                      "rounded-md px-2 py-0.5 text-xs font-medium",
                      ip.status === "active" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500",
                    )}>
                      {ip.status === "active" ? "活跃" : "非活跃"}
                    </span>
                  </td>
                </tr>
              ))}
              {group.infra_ips.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">暂无C2 IP数据</td></tr>
              )}
            </tbody>
          </table>
        )}

        {activeTab === "malware" && (
          <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2 lg:grid-cols-3">
            {group.malware_families.map((m) => (
              <div key={m.id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-center justify-between">
                  <h4 className="font-medium text-slate-800">{m.family_name}</h4>
                  <span className="rounded-md bg-rose-50 px-2 py-0.5 text-xs text-rose-600">{m.type}</span>
                </div>
                {m.aliases.length > 0 && (
                  <p className="mt-1 text-xs text-slate-500">{m.aliases.join(" · ")}</p>
                )}
                <div className="mt-2 flex gap-2 text-xs text-slate-400">
                  {m.platform.map((p) => <span key={p}>{p}</span>)}
                </div>
              </div>
            ))}
            {group.malware_families.length === 0 && (
              <div className="col-span-full py-8 text-center text-slate-400">暂无木马家族数据</div>
            )}
          </div>
        )}

        {activeTab === "vulns" && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs text-slate-500">
                <th className="px-4 py-2.5 font-medium">CVE</th>
                <th className="px-4 py-2.5 font-medium">标题</th>
                <th className="px-4 py-2.5 font-medium">CVSS</th>
                <th className="px-4 py-2.5 font-medium">严重性</th>
                <th className="px-4 py-2.5 font-medium">关系</th>
                <th className="px-4 py-2.5 font-medium">CISA KEV</th>
              </tr>
            </thead>
            <tbody>
              {group.vulnerabilities.map((v) => (
                <tr key={v.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-2.5 font-mono text-indigo-600">{v.cve_id}</td>
                  <td className="px-4 py-2.5 text-slate-600">{v.title || "—"}</td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {v.cvss_score !== null ? v.cvss_score.toFixed(1) : "待补充"}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={cn(
                      "rounded-md px-2 py-0.5 text-xs font-medium",
                      v.severity === "critical" ? "bg-red-50 text-red-700" : "bg-orange-50 text-orange-700",
                    )}>
                      {v.severity === "critical" ? "严重" : "高危"}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-slate-500">{v.relationship_type}</td>
                  <td className="px-4 py-2.5">
                    {v.is_cisa_kev && <span className="text-xs text-amber-600">KEV</span>}
                  </td>
                </tr>
              ))}
              {group.vulnerabilities.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">暂无已知漏洞数据</td></tr>
              )}
            </tbody>
          </table>
        )}

        {activeTab === "aliases" && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs text-slate-500">
                <th className="px-4 py-2.5 font-medium">别名</th>
                <th className="px-4 py-2.5 font-medium">命名机构</th>
                <th className="px-4 py-2.5 font-medium">置信度</th>
              </tr>
            </thead>
            <tbody>
              {group.apt_aliases.map((a, i) => (
                <tr key={i} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-2.5 font-medium text-slate-700">{a.alias_name}</td>
                  <td className="px-4 py-2.5 text-slate-500">{a.naming_org || "—"}</td>
                  <td className="px-4 py-2.5 text-slate-500">{(a.confidence * 100).toFixed(0)}%</td>
                </tr>
              ))}
              {group.apt_aliases.length === 0 && (
                <tr><td colSpan={3} className="px-4 py-8 text-center text-slate-400">暂无别名数据</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function InfoItem({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-1 text-xs text-slate-400">
        {icon}
        {label}
      </div>
      <div className="mt-0.5 font-medium text-slate-700">{value}</div>
    </div>
  );
}

export default GroupDetailPage;
