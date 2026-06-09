import { useCallback, useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  type Edge,
  type Node,
  type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import { Filter, GitFork, Loader2, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { fetchAssetRiskTopology } from "@/lib/api";
import type {
  AssetRiskTopologyNode,
  AssetRiskTopologyResponse,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

const ASSET_TYPES = ["业务", "智能体", "OA", "中间件", "支撑", "内网", "其他"];
const CANDIDATE_STATUSES = [
  { value: "candidate", label: "候选" },
  { value: "verified", label: "已验证" },
  { value: "dismissed", label: "已忽略" },
];

const COLUMN_X: Record<AssetRiskTopologyNode["type"], number> = {
  asset: 40,
  service: 330,
  vulnerability: 620,
};
const NODE_GAP = 74;
const TOP_PADDING = 36;

interface TopologyFilters {
  businessSystem: string;
  subnet: string;
  assetType: string;
  vulnerabilityIdentity: string;
  candidateStatus: string;
  recentScan: string;
}

interface RiskNodeData {
  original: AssetRiskTopologyNode;
  focused: boolean;
}

const EMPTY_FILTERS: TopologyFilters = {
  businessSystem: "",
  subnet: "",
  assetType: "all",
  vulnerabilityIdentity: "",
  candidateStatus: "all",
  recentScan: "",
};

function truncateLabel(value: string, max = 22): string {
  return value.length > max ? `${value.slice(0, max - 1)}...` : value;
}

function stringData(node: AssetRiskTopologyNode, key: string): string {
  const value = node.data[key];
  return typeof value === "string" ? value : "";
}

function numberData(node: AssetRiskTopologyNode, key: string): number {
  const value = node.data[key];
  return typeof value === "number" ? value : 0;
}

function queryFromFilters(filters: TopologyFilters, focusId: string | null) {
  return {
    businessSystem: filters.businessSystem.trim() || undefined,
    subnet: filters.subnet.trim() || undefined,
    assetType: filters.assetType === "all" ? undefined : filters.assetType,
    vulnerabilityIdentity: filters.vulnerabilityIdentity.trim() || undefined,
    candidateStatus: filters.candidateStatus === "all" ? undefined : filters.candidateStatus,
    recentScan: filters.recentScan.trim() || undefined,
    focusId: focusId || undefined,
  };
}

function riskNodeClass(node: AssetRiskTopologyNode, focused: boolean): string {
  if (node.type === "asset") {
    return cn(
      "min-h-[44px] w-[180px] rounded-md border border-primary bg-primary/10 px-3 py-2 text-left shadow-sm",
      focused && "ring-2 ring-severity-medium",
    );
  }
  if (node.type === "service") {
    return cn(
      "min-h-[44px] w-[164px] rounded-md border border-border bg-card px-3 py-2 text-left shadow-sm",
      focused && "ring-2 ring-severity-medium",
    );
  }
  const confirmed = stringData(node, "status") === "confirmed";
  return cn(
    "flex items-center justify-center rounded-full border-2 bg-card p-3 text-center shadow-sm",
    confirmed
      ? "border-destructive bg-destructive/10"
      : "border-dashed border-severity-medium",
    focused && "ring-2 ring-primary",
  );
}

function RiskNode({ data }: NodeProps<RiskNodeData>) {
  const { original, focused } = data;
  const radius = Math.max(numberData(original, "radius"), 24);
  const status = stringData(original, "status");
  const subtitle =
    original.type === "asset"
      ? [stringData(original, "system"), stringData(original, "asset_type")]
          .filter(Boolean)
          .join(" / ")
      : original.type === "service"
        ? [
            stringData(original, "state"),
            stringData(original, "product") || stringData(original, "service"),
          ]
            .filter(Boolean)
            .join(" / ")
        : status === "confirmed"
          ? `已确认 / ${numberData(original, "affected_asset_count")}资产`
          : `${status || "candidate"} / ${numberData(original, "affected_asset_count")}资产`;

  const style =
    original.type === "vulnerability"
      ? { width: `${radius * 2}px`, minHeight: `${radius * 2}px` }
      : undefined;

  return (
    <div className={riskNodeClass(original, focused)} style={style}>
      <Handle className="!bg-border" position={Position.Left} type="target" />
      <div className="text-xs font-medium leading-snug text-foreground">
        {truncateLabel(original.label, original.type === "vulnerability" ? 18 : 24)}
      </div>
      {subtitle ? (
        <div className="mt-1 truncate text-[10px] leading-tight text-muted-foreground">
          {subtitle}
        </div>
      ) : null}
      <Handle className="!bg-border" position={Position.Right} type="source" />
    </div>
  );
}

const NODE_TYPES = { riskNode: RiskNode };

function toFlowGraph(
  graph: AssetRiskTopologyResponse,
  focusId: string | null,
): { nodes: Node<RiskNodeData>[]; edges: Edge[] } {
  const activeFocus = graph.focus_id ?? focusId;
  const byType = {
    asset: graph.nodes.filter((node) => node.type === "asset"),
    service: graph.nodes.filter((node) => node.type === "service"),
    vulnerability: graph.nodes.filter((node) => node.type === "vulnerability"),
  };

  const nodes: Node<RiskNodeData>[] = [];
  for (const [type, rows] of Object.entries(byType) as Array<
    [AssetRiskTopologyNode["type"], AssetRiskTopologyNode[]]
  >) {
    const ordered = [...rows].sort((a, b) => {
      if (a.id === activeFocus) return -1;
      if (b.id === activeFocus) return 1;
      return a.label.localeCompare(b.label, "zh-Hans-CN");
    });
    ordered.forEach((node, index) => {
      nodes.push({
        id: node.id,
        type: "riskNode",
        position: {
          x: COLUMN_X[type],
          y: TOP_PADDING + index * NODE_GAP,
        },
        data: { original: node, focused: activeFocus === node.id },
        draggable: false,
      });
    });
  }

  const edges = graph.edges.map<Edge>((edge) => {
    const candidate = edge.kind === "candidate-vulnerability";
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: "smoothstep",
      animated: candidate,
      markerEnd: { type: MarkerType.ArrowClosed, color: "hsl(var(--border))" },
      style: {
        stroke: candidate ? "hsl(var(--sev-medium))" : "hsl(var(--border))",
        strokeDasharray: candidate ? "5 5" : undefined,
      },
    };
  });

  return { nodes, edges };
}

/** Derived CMDB topology widget for asset/service/vulnerability risk edges. */
export function AssetRiskTopology() {
  const { token } = useClient();
  const [graph, setGraph] = useState<AssetRiskTopologyResponse | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [draftFilters, setDraftFilters] = useState<TopologyFilters>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<TopologyFilters>(EMPTY_FILTERS);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFailed(false);
    fetchAssetRiskTopology(token, queryFromFilters(appliedFilters, focusId))
      .then((payload) => {
        if (!cancelled) setGraph(payload);
      })
      .catch(() => {
        if (!cancelled) {
          setGraph(null);
          setFailed(true);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [appliedFilters, focusId, token]);

  const flowGraph = useMemo(() => {
    if (!graph) return { nodes: [], edges: [] };
    return toFlowGraph(graph, focusId);
  }, [focusId, graph]);

  const handleFocus = useCallback((_: unknown, node: Node<RiskNodeData>) => {
    setFocusId((current) => (current === node.id ? null : node.id));
  }, []);

  const applyFilters = useCallback(() => {
    setFocusId(null);
    setAppliedFilters(draftFilters);
  }, [draftFilters]);

  const resetFilters = useCallback(() => {
    setFocusId(null);
    setDraftFilters(EMPTY_FILTERS);
    setAppliedFilters(EMPTY_FILTERS);
  }, []);

  const hasGraph = flowGraph.nodes.length > 0;

  return (
    <section className="rounded-xl border border-border/70 bg-card/70 p-5">
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-2">
          <GitFork className="h-4 w-4 shrink-0 text-primary" />
          <h3 className="truncate text-sm font-semibold text-foreground">
            资产风险拓扑
          </h3>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-destructive" />
            已确认
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-full border border-severity-medium bg-card" />
            候选
          </span>
        </div>
      </div>

      <div className="mb-4 grid gap-2 md:grid-cols-2 xl:grid-cols-6">
        <Input
          aria-label="业务系统"
          placeholder="业务系统"
          value={draftFilters.businessSystem}
          onChange={(event) =>
            setDraftFilters((current) => ({
              ...current,
              businessSystem: event.target.value,
            }))
          }
        />
        <Input
          aria-label="网段"
          placeholder="网段"
          value={draftFilters.subnet}
          onChange={(event) =>
            setDraftFilters((current) => ({ ...current, subnet: event.target.value }))
          }
        />
        <Select
          value={draftFilters.assetType}
          onValueChange={(value) =>
            setDraftFilters((current) => ({ ...current, assetType: value }))
          }
        >
          <SelectTrigger aria-label="资产类型">
            <SelectValue placeholder="资产类型" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部类型</SelectItem>
            {ASSET_TYPES.map((value) => (
              <SelectItem key={value} value={value}>
                {value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          aria-label="漏洞身份"
          placeholder="漏洞身份"
          value={draftFilters.vulnerabilityIdentity}
          onChange={(event) =>
            setDraftFilters((current) => ({
              ...current,
              vulnerabilityIdentity: event.target.value,
            }))
          }
        />
        <Select
          value={draftFilters.candidateStatus}
          onValueChange={(value) =>
            setDraftFilters((current) => ({ ...current, candidateStatus: value }))
          }
        >
          <SelectTrigger aria-label="候选状态">
            <SelectValue placeholder="候选状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            {CANDIDATE_STATUSES.map((row) => (
              <SelectItem key={row.value} value={row.value}>
                {row.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="flex gap-2">
          <Input
            aria-label="最近扫描"
            placeholder="最近扫描"
            value={draftFilters.recentScan}
            onChange={(event) =>
              setDraftFilters((current) => ({
                ...current,
                recentScan: event.target.value,
              }))
            }
          />
          <Button aria-label="筛选" size="icon" type="button" onClick={applyFilters}>
            <Filter />
          </Button>
          <Button
            aria-label="重置筛选"
            size="icon"
            type="button"
            variant="outline"
            onClick={resetFilters}
          >
            <RotateCcw />
          </Button>
        </div>
      </div>

      <div className="h-[380px] overflow-hidden rounded-lg border border-border/50 bg-background/50">
        {loading ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            加载中
          </div>
        ) : failed ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            拓扑不可用
          </div>
        ) : !hasGraph ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            暂无纳管资产
          </div>
        ) : (
          <ReactFlow
            className="asset-risk-topology-flow"
            edges={flowGraph.edges}
            fitView
            maxZoom={1.4}
            minZoom={0.35}
            nodes={flowGraph.nodes}
            nodesConnectable={false}
            nodesDraggable={false}
            nodeTypes={NODE_TYPES}
            onNodeClick={handleFocus}
            panOnScroll
            proOptions={{ hideAttribution: true }}
          >
            <Background color="hsl(var(--border))" gap={18} size={1} />
            <MiniMap
              maskColor="hsl(var(--background) / 0.72)"
              nodeColor="hsl(var(--muted))"
              pannable
              zoomable
            />
            <Controls showInteractive={false} />
          </ReactFlow>
        )}
      </div>
    </section>
  );
}
