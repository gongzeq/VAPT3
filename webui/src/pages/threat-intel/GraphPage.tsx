/**
 * Knowledge Graph Page — PRD §7.2 知识图谱页.
 *
 * Uses reactflow with d3-force layout for global graph.
 * Gap Fixes: toolbar (§4), d3-force (§5), click animate (§6), status bar (§7).
 */

import { useCallback, useEffect, useState, useRef, useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeTypes,
  type ReactFlowInstance,
} from "reactflow";
import { forceSimulation, forceManyBody, forceLink, forceCenter } from "d3-force";
import { Shield, Server, Bug, AlertTriangle, Layers, Star, Search, Filter, Activity } from "lucide-react";
import "reactflow/dist/style.css";
import { useClient } from "@/providers/ClientProvider";
import {
  fetchGraph,
  fetchFeedRuns,
  fetchGroups,
  type GraphData,
  type GraphNode,
  type ThreatGroupSummary,
} from "@/lib/threat-intel-client";

// ── Custom Node Components ──────────────────────────────────────────────

function GroupNode({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="flex items-center gap-2 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-500 px-3 py-2 text-white shadow-lg">
      <Shield className="h-4 w-4" />
      <span className="text-sm font-medium">{data.label as string}</span>
      {data.is_watched as boolean && <Star className="h-3 w-3 fill-yellow-300 text-yellow-300" />}
    </div>
  );
}

function IPNode({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="flex items-center gap-1.5 rounded-full bg-gradient-to-br from-amber-500 to-orange-500 px-2.5 py-1.5 text-white shadow-md">
      <Server className="h-3 w-3" />
      <span className="text-xs font-medium">{data.label as string}</span>
    </div>
  );
}

function MalwareNode({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="flex items-center gap-1.5 rounded bg-gradient-to-br from-rose-500 to-red-500 px-2.5 py-1.5 text-white shadow-md">
      <Bug className="h-3 w-3" />
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
      <AlertTriangle className="h-3 w-3" />
      <span className="text-xs font-medium">{data.label as string}</span>
    </div>
  );
}

function ClusterNode({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="flex items-center gap-1.5 rounded-full border-2 border-dashed border-slate-300 bg-slate-200 px-3 py-2 text-slate-600">
      <Layers className="h-3 w-3" />
      <span className="text-xs font-medium">{data.label as string}</span>
    </div>
  );
}

const nodeTypes: NodeTypes = {
  group: GroupNode,
  ip: IPNode,
  malware: MalwareNode,
  vuln: VulnNode,
  cluster: ClusterNode,
};

const edgeStyles: Record<string, { stroke: string; strokeWidth: number; strokeDasharray?: string }> = {
  uses_c2: { stroke: "#6366F1", strokeWidth: 1.5 },
  uses_malware: { stroke: "#F43F5E", strokeWidth: 1.5 },
  exploits: { stroke: "#DC2626", strokeWidth: 3 },
  targets: { stroke: "#F59E0B", strokeWidth: 1.5, strokeDasharray: "5,5" },
};

// ── d3-force Layout (Gap Fix §5) ───────────────────────────────────────

function applyD3ForceLayout(nodes: Node[], edges: Edge[], width = 800, height = 600): Node[] {
  if (nodes.length === 0) return nodes;

  const simNodes = nodes.map((n) => ({
    ...n,
    x: (n.position?.x ?? width / 2) + Math.random() * 100 - 50,
    y: (n.position?.y ?? height / 2) + Math.random() * 100 - 50,
  }));

  const links = edges.map((e) => ({ source: e.source, target: e.target }));

  const simulation = forceSimulation(simNodes as any)
    .force("charge", forceManyBody().strength(-300))
    .force("link", forceLink(links).id((d: any) => d.id).distance(100))
    .force("center", forceCenter(width / 2, height / 2))
    .stop();

  // Run simulation synchronously (enough ticks for stable layout)
  for (let i = 0; i < 300; i++) simulation.tick();

  return simNodes.map((n) => ({
    ...n,
    position: { x: (n as any).x, y: (n as any).y },
  }));
}

// ── Toolbar Component (Gap Fix §4) ─────────────────────────────────────

interface GraphToolbarProps {
  onSearch: (query: string) => void;
  onGroupSelect: (groupIds: string[]) => void;
  onNodeTypeFilter: (types: string[]) => void;
  onConfidenceChange: (minConfidence: number) => void;
  topN: number;
  onTopNChange: (n: number) => void;
  watchedGroups: ThreatGroupSummary[];
}

function GraphToolbar({
  onSearch,
  onGroupSelect,
  onNodeTypeFilter,
  onConfidenceChange,
  topN,
  onTopNChange,
  watchedGroups,
}: GraphToolbarProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedGroups, setSelectedGroups] = useState<string[]>([]);
  const [nodeTypes, setNodeTypes] = useState<string[]>(["group", "ip", "malware", "vuln"]);
  const [minConfidence, setMinConfidence] = useState(0);
  const [showGroupSelect, setShowGroupSelect] = useState(false);

  // Debounce search 500ms
  useEffect(() => {
    const timer = setTimeout(() => onSearch(searchQuery), 500);
    return () => clearTimeout(timer);
  }, [searchQuery, onSearch]);

  useEffect(() => {
    onGroupSelect(selectedGroups);
  }, [selectedGroups, onGroupSelect]);

  useEffect(() => {
    onNodeTypeFilter(nodeTypes);
  }, [nodeTypes, onNodeTypeFilter]);

  // Debounce confidence change 500ms
  useEffect(() => {
    const timer = setTimeout(() => onConfidenceChange(minConfidence), 500);
    return () => clearTimeout(timer);
  }, [minConfidence, onConfidenceChange]);

  const toggleNodeType = (type: string) => {
    setNodeTypes((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]
    );
  };

  const toggleGroup = (groupId: string) => {
    setSelectedGroups((prev) =>
      prev.includes(groupId) ? prev.filter((g) => g !== groupId) : [...prev, groupId]
    );
  };

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-2.5">
      {/* Search */}
      <div className="relative min-w-[200px] flex-1">
        <Search className="absolute left-2 top-2.5 h-4 w-4 text-slate-400" />
        <input
          type="text"
          placeholder="搜索节点 (名称/CVE/IP)..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full rounded-lg border border-slate-200 py-1.5 pl-8 pr-3 text-sm"
        />
      </div>

      {/* Group multi-select */}
      <div className="relative">
        <button
          onClick={() => setShowGroupSelect(!showGroupSelect)}
          className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
        >
          <Filter className="h-3.5 w-3.5" />
          组织 ({selectedGroups.length || "全部"})
        </button>
        {showGroupSelect && (
          <div className="absolute z-10 mt-1 max-h-60 w-64 overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
            {watchedGroups.length === 0 ? (
              <div className="px-3 py-2 text-xs text-slate-400">暂无关注组织</div>
            ) : (
              watchedGroups.map((g) => (
                <label key={g.id} className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-slate-50">
                  <input
                    type="checkbox"
                    checked={selectedGroups.includes(g.id)}
                    onChange={() => toggleGroup(g.id)}
                    className="h-3.5 w-3.5"
                  />
                  <span className="truncate">{g.name}</span>
                </label>
              ))
            )}
          </div>
        )}
      </div>

      {/* Node type filter */}
      <div className="flex items-center gap-2">
        {[
          { type: "group", label: "组织", color: "bg-indigo-500" },
          { type: "ip", label: "IP", color: "bg-amber-500" },
          { type: "malware", label: "木马", color: "bg-rose-500" },
          { type: "vuln", label: "漏洞", color: "bg-red-500" },
        ].map((item) => (
          <label key={item.type} className="flex cursor-pointer items-center gap-1 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={nodeTypes.includes(item.type)}
              onChange={() => toggleNodeType(item.type)}
              className="h-3.5 w-3.5"
            />
            <span className={`h-2 w-2 rounded ${item.color}`} />
            {item.label}
          </label>
        ))}
      </div>

      {/* Confidence slider */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500">置信度≥</span>
        <input
          type="range"
          min="0"
          max="1"
          step="0.1"
          value={minConfidence}
          onChange={(e) => setMinConfidence(parseFloat(e.target.value))}
          className="w-24"
        />
        <span className="w-8 text-xs text-slate-600">{minConfidence.toFixed(1)}</span>
      </div>

      {/* top_n control */}
      <div className="flex items-center gap-1">
        <span className="text-xs text-slate-500">显示</span>
        <input
          type="number"
          min="10"
          max="200"
          value={topN}
          onChange={(e) => onTopNChange(Math.max(10, Math.min(200, parseInt(e.target.value) || 30)))}
          className="w-14 rounded border border-slate-200 px-2 py-1 text-xs"
        />
      </div>
    </div>
  );
}

// ── Status Bar Component (Gap Fix §7) ──────────────────────────────────

function GraphStatusBar({ metadata, lastSuccessAt }: { metadata: GraphData["metadata"] | null; lastSuccessAt: string | null }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-white px-4 py-2 text-xs text-slate-600">
      {metadata && (
        <>
          <span>节点: {metadata.total_nodes} | 边: {metadata.total_edges}</span>
          <span>聚类节点: {metadata.clustered_nodes} | 包含组织: {metadata.groups_included}</span>
        </>
      )}
      <span className="flex items-center gap-1">
        <Activity className="h-3 w-3" />
        数据新鲜度: {lastSuccessAt ? new Date(lastSuccessAt).toLocaleString("zh-CN") : "未知"}
      </span>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────

export function GraphPage() {
  const { token } = useClient();
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [topN, setTopN] = useState(30);
  const [watchedGroups, setWatchedGroups] = useState<ThreatGroupSummary[]>([]);
  const [lastSuccessAt, setLastSuccessAt] = useState<string | null>(null);

  // Toolbar state
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedGroupIds, setSelectedGroupIds] = useState<string[]>([]);
  const [nodeTypeFilter, setNodeTypeFilter] = useState<string[]>(["group", "ip", "malware", "vuln"]);
  const [minConfidence, setMinConfidence] = useState(0);

  const reactFlowInstance = useRef<ReactFlowInstance | null>(null);

  // Load watched groups for multi-select
  useEffect(() => {
    fetchGroups(token, { watched: true, page_size: 100 })
      .then((result) => setWatchedGroups(result.items))
      .catch(() => { /* ignore */ });
  }, [token]);

  // Load data freshness (last successful feed run)
  useEffect(() => {
    fetchFeedRuns(token, { status: "ok", page: 1, page_size: 1 })
      .then((result) => {
        if (result.items.length > 0 && result.items[0].finished_at) {
          setLastSuccessAt(result.items[0].finished_at);
        }
      })
      .catch(() => { /* ignore */ });
  }, [token]);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Parameters<typeof fetchGraph>[1] = {
        watched: selectedGroupIds.length === 0,
        top_n: topN,
        min_confidence: minConfidence,
        node_types: nodeTypeFilter,
      };
      if (selectedGroupIds.length > 0) {
        params.group_ids = selectedGroupIds;
      }
      const data = await fetchGraph(token, params);

      // Auto-adjust top_n if too many nodes
      if (data.metadata.total_nodes > 200 && topN > 10) {
        const newTopN = Math.max(10, Math.floor(topN * 0.7));
        setTopN(newTopN);
      }

      setGraphData(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token, topN, selectedGroupIds, nodeTypeFilter, minConfidence]);

  // Debounce graph reload on toolbar changes
  useEffect(() => {
    const timer = setTimeout(() => loadGraph(), 500);
    return () => clearTimeout(timer);
  }, [loadGraph]);

  // Compute nodes and edges with d3-force layout
  const { positionedNodes, edges } = useMemo(() => {
    if (!graphData) return { positionedNodes: [], edges: [] };

    // Filter nodes by type
    const filteredNodes = graphData.nodes.filter((n) => nodeTypeFilter.includes(n.type));

    // Filter edges to only include filtered nodes
    const nodeIds = new Set(filteredNodes.map((n) => n.id));
    const filteredEdges = graphData.edges.filter(
      (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
    );

    const rawNodes: Node[] = filteredNodes.map((n) => ({
      id: n.id,
      type: n.type,
      position: { x: 0, y: 0 },
      data: { ...n.data, label: n.label },
    }));

    const rawEdges: Edge[] = filteredEdges.map((e, i) => ({
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      type: "default",
      style: edgeStyles[e.type] || edgeStyles.uses_c2,
      animated: e.type === "exploits",
    }));

    const positioned = applyD3ForceLayout(rawNodes, rawEdges);

    // Search highlight: if searching, dim non-matching nodes
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      positioned.forEach((n) => {
        const label = String(n.data.label || "").toLowerCase();
        const matches = label.includes(q);
        (n as any).hidden = !matches && !filteredEdges.some(
          (e) => e.source === n.id || e.target === n.id
        );
      });
    }

    return { positionedNodes: positioned, edges: rawEdges };
  }, [graphData, nodeTypeFilter, searchQuery]);

  // Gap Fix §6: Click node animate center
  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    if (graphData) {
      setSelectedNode(graphData.nodes.find((n) => n.id === node.id) || null);
    }
    reactFlowInstance.current?.fitView({
      nodes: [{ id: node.id }],
      duration: 600,
      padding: 0.3,
    });
  }, [graphData]);

  // Search: center on matching node
  useEffect(() => {
    if (searchQuery && positionedNodes.length > 0 && reactFlowInstance.current) {
      const q = searchQuery.toLowerCase();
      const match = positionedNodes.find((n) =>
        String(n.data.label || "").toLowerCase().includes(q)
      );
      if (match) {
        reactFlowInstance.current.fitView({
          nodes: [{ id: match.id }],
          duration: 600,
          padding: 0.3,
        });
      }
    }
  }, [searchQuery, positionedNodes]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">知识图谱</h1>
        <button
          onClick={loadGraph}
          className="rounded-lg bg-indigo-500 px-3 py-1.5 text-white hover:bg-indigo-600"
        >
          刷新
        </button>
      </div>

      {/* Toolbar (Gap Fix §4) */}
      <GraphToolbar
        onSearch={setSearchQuery}
        onGroupSelect={setSelectedGroupIds}
        onNodeTypeFilter={setNodeTypeFilter}
        onConfidenceChange={setMinConfidence}
        topN={topN}
        onTopNChange={setTopN}
        watchedGroups={watchedGroups}
      />

      {error && (
        <div className="rounded-lg bg-red-50 p-4 text-red-700">{error}</div>
      )}

      {loading ? (
        <div className="flex h-[600px] items-center justify-center text-slate-400">
          加载中...
        </div>
      ) : !graphData || graphData.nodes.length === 0 ? (
        <div className="flex h-[600px] items-center justify-center text-slate-400">
          尚无关注组织，请先在组织列表中添加关注
        </div>
      ) : (
        <div className="flex gap-4">
          <div className="h-[600px] flex-1 rounded-xl border border-slate-200 bg-white">
            <ReactFlow
              nodes={positionedNodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              attributionPosition="bottom-left"
              onInit={(instance) => { reactFlowInstance.current = instance; }}
              onNodeClick={onNodeClick}
            >
              <Background color="#e2e8f0" gap={20} />
              <Controls />
              <MiniMap
                nodeColor={(n) => {
                  switch (n.type) {
                    case "group": return "#6366F1";
                    case "ip": return "#F59E0B";
                    case "malware": return "#F43F5E";
                    case "vuln": return "#DC2626";
                    default: return "#CBD5E1";
                  }
                }}
              />
            </ReactFlow>
          </div>

          {/* Detail Drawer */}
          {selectedNode && (
            <div className="w-80 rounded-xl border border-slate-200 bg-white p-4">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-lg font-semibold">{selectedNode.label}</h3>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="text-slate-400 hover:text-slate-600"
                >
                  x
                </button>
              </div>
              <dl className="space-y-2 text-sm">
                {Object.entries(selectedNode.data).map(([key, value]) => (
                  <div key={key}>
                    <dt className="text-slate-500">{key}</dt>
                    <dd className="font-medium">
                      {typeof value === "boolean" ? (value ? "Yes" : "No") : String(value)}
                    </dd>
                  </div>
                ))}
              </dl>
              {selectedNode.type === "cluster" && (
                <button
                  onClick={async () => {
                    const expanded = await fetchGraph(token, {
                      group_id: selectedNode.data.group_id as string,
                      expand_cluster: selectedNode.data.cluster_type as string,
                    });
                    setGraphData(expanded);
                    setSelectedNode(null);
                  }}
                  className="mt-3 w-full rounded-lg bg-indigo-500 px-3 py-1.5 text-sm text-white hover:bg-indigo-600"
                >
                  展开聚类
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Status Bar (Gap Fix §7) */}
      <GraphStatusBar metadata={graphData?.metadata ?? null} lastSuccessAt={lastSuccessAt} />

      {/* Legend */}
      <div className="flex flex-wrap gap-4 rounded-lg bg-white p-3 text-xs text-slate-600">
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded bg-gradient-to-br from-indigo-500 to-violet-500" /> 组织
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-full bg-gradient-to-br from-amber-500 to-orange-500" /> IP
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded bg-gradient-to-br from-rose-500 to-red-500" /> 木马
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-md bg-gradient-to-br from-amber-500 to-orange-500" /> 漏洞
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-full border-2 border-dashed border-slate-300 bg-slate-200" /> 聚类
        </span>
      </div>
    </div>
  );
}

export default GraphPage;
