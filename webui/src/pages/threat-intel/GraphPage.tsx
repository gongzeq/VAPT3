/**
 * Knowledge Graph Page — PRD §7.2 知识图谱页.
 *
 * Uses reactflow with force-directed layout for global graph
 * and radial layout for single-group view.
 */

import { useCallback, useEffect, useState, useRef } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeTypes,
} from "reactflow";
import { Shield, Server, Bug, AlertTriangle, Layers, Star } from "lucide-react";
import "reactflow/dist/style.css";
import { useClient } from "@/providers/ClientProvider";
import { fetchGraph, type GraphData, type GraphNode } from "@/lib/threat-intel-client";

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

// ── Force-directed positioning ──────────────────────────────────────────

function applyForceLayout(nodes: Node[]): Node[] {
  const centerX = 400;
  const centerY = 300;
  const radius = 250;

  // Group nodes at center, others on concentric rings
  const groupNodes = nodes.filter((n) => n.type === "group");
  const otherNodes = nodes.filter((n) => n.type !== "group" && n.type !== "cluster");
  const clusterNodes = nodes.filter((n) => n.type === "cluster");

  const positioned: Node[] = [];

  // Place groups in inner circle
  groupNodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / Math.max(groupNodes.length, 1);
    positioned.push({
      ...node,
      position: {
        x: centerX + 120 * Math.cos(angle),
        y: centerY + 120 * Math.sin(angle),
      },
    });
  });

  // Place other nodes on outer ring
  otherNodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / Math.max(otherNodes.length, 1);
    positioned.push({
      ...node,
      position: {
        x: centerX + radius * Math.cos(angle),
        y: centerY + radius * Math.sin(angle),
      },
    });
  });

  // Place cluster nodes between group and outer ring
  clusterNodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / Math.max(clusterNodes.length, 1);
    positioned.push({
      ...node,
      position: {
        x: centerX + 180 * Math.cos(angle),
        y: centerY + 180 * Math.sin(angle),
      },
    });
  });

  return positioned;
}

// ── Main Component ──────────────────────────────────────────────────────

export function GraphPage() {
  const { token } = useClient();
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [topN] = useState(30);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchGraph(token, { watched: true, top_n: topN });
      setGraphData(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token, topN]);

  useEffect(() => { loadGraph(); }, [loadGraph]);

  const nodes: Node[] = graphData
    ? graphData.nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: { x: 0, y: 0 },
        data: { ...n.data, label: n.label },
      }))
    : [];

  const edges: Edge[] = graphData
    ? graphData.edges.map((e, i) => ({
        id: `e-${i}`,
        source: e.source,
        target: e.target,
        type: "default",
        style: edgeStyles[e.type] || edgeStyles.uses_c2,
        animated: e.type === "exploits",
      }))
    : [];

  const positionedNodes = applyForceLayout(nodes);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">知识图谱</h1>
        <div className="flex items-center gap-3 text-sm text-slate-600">
          {graphData && (
            <span>
              节点: {graphData.metadata.total_nodes} | 边: {graphData.metadata.total_edges}
            </span>
          )}
          <button
            onClick={loadGraph}
            className="rounded-lg bg-indigo-500 px-3 py-1.5 text-white hover:bg-indigo-600"
          >
            刷新
          </button>
        </div>
      </div>

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
          <div ref={reactFlowWrapper} className="h-[600px] flex-1 rounded-xl border border-slate-200 bg-white">
            <ReactFlow
              nodes={positionedNodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              attributionPosition="bottom-left"
              onNodeClick={(_, node) => {
                setSelectedNode(graphData.nodes.find((n) => n.id === node.id) || null);
              }}
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
