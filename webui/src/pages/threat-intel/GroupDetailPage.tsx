/**
 * Threat Intel Group Detail Page — PRD §7.2 威胁组织详情页.
 *
 * Header with name + aliases + watch toggle.
 * Tabs: C2 IPs / Malware / Vulnerabilities / Aliases.
 */

import { useCallback, useEffect, useState, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Star, StarOff, Globe, Calendar, Shield, Link2 } from "lucide-react";
import ReactFlow, {
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeTypes,
} from "reactflow";
import "reactflow/dist/style.css";
import { useClient } from "@/providers/ClientProvider";
import {
  fetchGroupDetail,
  watchGroup,
  unwatchGroup,
  fetchGraph,
  type ThreatGroupDetail,
  type GraphData,
  type GraphNode,
} from "@/lib/threat-intel-client";
import { cn } from "@/lib/utils";

// ── Custom Node Components (reused from GraphPage) ─────────────────────

function GroupNode({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="flex items-center gap-2 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-500 px-3 py-2 text-white shadow-lg">
      <Shield className="h-4 w-4" />
      <span className="text-sm font-medium">{data.label as string}</span>
    </div>
  );
}

function IPNode({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="flex items-center gap-1.5 rounded-full bg-gradient-to-br from-amber-500 to-orange-500 px-2.5 py-1.5 text-white shadow-md">
      <span className="text-xs font-medium">{data.label as string}</span>
    </div>
  );
}

function MalwareNode({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="flex items-center gap-1.5 rounded bg-gradient-to-br from-rose-500 to-red-500 px-2.5 py-1.5 text-white shadow-md">
      <span className="text-xs font-medium">{data.label as string}</span>
    </div>
  );
}

function VulnNode({ data }: { data: Record<string, unknown> }) {
  const severity = data.severity as string;
  const gradient = severity === "critical"
    ? "from-rose-500 to-red-500"
    : "from-amber-500 to-orange-500";
  return (
    <div className={`flex items-center gap-1.5 rounded-md bg-gradient-to-br ${gradient} px-2.5 py-1.5 text-white shadow-md`}>
      <span className="text-xs font-medium">{data.label as string}</span>
    </div>
  );
}

function URLNode({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="flex items-center gap-1.5 rounded bg-gradient-to-br from-cyan-500 to-teal-500 px-2.5 py-1.5 text-white shadow-md">
      <Link2 className="h-3 w-3" />
      <span className="max-w-[100px] truncate text-xs font-medium">{data.label as string}</span>
    </div>
  );
}

const localNodeTypes: NodeTypes = {
  group: GroupNode,
  ip: IPNode,
  malware: MalwareNode,
  vuln: VulnNode,
  url: URLNode,
};

const localEdgeStyles: Record<string, { stroke: string; strokeWidth: number }> = {
  uses_c2: { stroke: "#6366F1", strokeWidth: 1.5 },
  uses_malware: { stroke: "#F43F5E", strokeWidth: 1.5 },
  exploits: { stroke: "#DC2626", strokeWidth: 3 },
  targets: { stroke: "#F59E0B", strokeWidth: 1.5 },
  uses_url: { stroke: "#06B6D4", strokeWidth: 1.5 },
};

// ── Radial Layout (Gap Fix §3.1) ───────────────────────────────────────

function applyRadialLayout(nodes: Node[], centerX = 300, centerY = 250): Node[] {
  const groupNode = nodes.find((n) => n.type === "group");
  const otherNodes = nodes.filter((n) => n.type !== "group");
  const radius = 200;
  const angleStep = (2 * Math.PI) / Math.max(otherNodes.length, 1);

  return [
    ...(groupNode ? [{ ...groupNode, position: { x: centerX, y: centerY } }] : []),
    ...otherNodes.map((node, i) => ({
      ...node,
      position: {
        x: centerX + radius * Math.cos(i * angleStep),
        y: centerY + radius * Math.sin(i * angleStep),
      },
    })),
  ];
}

type TabKey = "ips" | "malware" | "vulns" | "urls" | "aliases" | "graph";

export function GroupDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { token } = useClient();
  const navigate = useNavigate();
  const [group, setGroup] = useState<ThreatGroupDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("ips");
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [selectedGraphNode, setSelectedGraphNode] = useState<GraphNode | null>(null);

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

  // Load local graph when switching to graph tab (Gap Fix §3)
  useEffect(() => {
    if (activeTab !== "graph" || !id || graphData) return;
    setGraphLoading(true);
    fetchGraph(token, { group_id: id, top_n: 100 })
      .then((data) => setGraphData(data))
      .catch(() => { /* ignore */ })
      .finally(() => setGraphLoading(false));
  }, [activeTab, id, token, graphData]);

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
    { key: "urls", label: "恶意URL", count: group.infra_urls?.length ?? 0 },
    { key: "aliases", label: "APT别名", count: group.apt_aliases.length },
    { key: "graph", label: "图谱", count: 0 },
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

        {/* Local Graph Tab (Gap Fix §3) */}
        {activeTab === "graph" && (
          <div className="p-4">
            {graphLoading ? (
              <div className="flex h-[500px] items-center justify-center text-sm text-slate-400">图谱加载中…</div>
            ) : !graphData || graphData.nodes.length === 0 ? (
              <div className="flex h-[500px] items-center justify-center text-sm text-slate-400">暂无图谱数据</div>
            ) : (
              <LocalGraphView
                graphData={graphData}
                selectedNode={selectedGraphNode}
                onSelectNode={setSelectedGraphNode}
              />
            )}
          </div>
        )}

        {/* URL Tab (Gap 7) */}
        {activeTab === "urls" && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-xs text-slate-500">
                <th className="px-4 py-2.5 font-medium">URL</th>
                <th className="px-4 py-2.5 font-medium">类型</th>
                <th className="px-4 py-2.5 font-medium">木马家族</th>
                <th className="px-4 py-2.5 font-medium">来源</th>
                <th className="px-4 py-2.5 font-medium">最近发现</th>
                <th className="px-4 py-2.5 font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              {(group.infra_urls ?? []).map((u) => (
                <tr key={u.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-2.5 font-mono text-slate-700 truncate max-w-[300px]">{u.url}</td>
                  <td className="px-4 py-2.5 text-slate-500">{u.url_type}</td>
                  <td className="px-4 py-2.5 text-slate-500">{u.malware_family || "—"}</td>
                  <td className="px-4 py-2.5 text-slate-500">{u.source}</td>
                  <td className="px-4 py-2.5 text-slate-500">
                    {u.last_seen ? new Date(u.last_seen).toLocaleDateString("zh-CN") : "—"}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={cn(
                      "rounded-md px-2 py-0.5 text-xs font-medium",
                      u.status === "active" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500",
                    )}>
                      {u.status === "active" ? "活跃" : "非活跃"}
                    </span>
                  </td>
                </tr>
              ))}
              {(group.infra_urls ?? []).length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">暂无恶意URL数据</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ── Local Graph View Component ─────────────────────────────────────────

function LocalGraphView({
  graphData,
  selectedNode,
  onSelectNode,
}: {
  graphData: GraphData;
  selectedNode: GraphNode | null;
  onSelectNode: (node: GraphNode | null) => void;
}) {
  const { positionedNodes, edges } = useMemo(() => {
    const rawNodes: Node[] = graphData.nodes.map((n) => ({
      id: n.id,
      type: n.type,
      position: { x: 0, y: 0 },
      data: { ...n.data, label: n.label },
    }));
    const rawEdges: Edge[] = graphData.edges.map((e, i) => ({
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      type: "default",
      style: localEdgeStyles[e.type] || localEdgeStyles.uses_c2,
      animated: e.type === "exploits",
    }));
    return { positionedNodes: applyRadialLayout(rawNodes), edges: rawEdges };
  }, [graphData]);

  return (
    <div className="flex gap-4">
      <div className="h-[500px] flex-1 rounded-lg border border-slate-200 bg-white">
        <ReactFlow
          nodes={positionedNodes}
          edges={edges}
          nodeTypes={localNodeTypes}
          fitView
          attributionPosition="bottom-left"
          onNodeClick={(_, node) => {
            onSelectNode(graphData.nodes.find((n) => n.id === node.id) || null);
          }}
        >
          <Background color="#e2e8f0" gap={20} />
          <Controls />
        </ReactFlow>
      </div>
      {selectedNode && (
        <div className="w-72 rounded-lg border border-slate-200 bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="font-semibold">{selectedNode.label}</h3>
            <button onClick={() => onSelectNode(null)} className="text-slate-400 hover:text-slate-600">x</button>
          </div>
          <dl className="space-y-2 text-xs">
            {Object.entries(selectedNode.data).map(([key, value]) => (
              <div key={key}>
                <dt className="text-slate-500">{key}</dt>
                <dd className="font-medium">
                  {typeof value === "boolean" ? (value ? "Yes" : "No") : String(value)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
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
