# Knowledge Graph Contract (P1)

> Full-stack spec for the threat intel knowledge graph: backend aggregation API + frontend reactflow visualization.
> Source: `docs/prd-threat-intelligence.md` §6.2 (graph API) + §7.2 (graph page).
> Library: reactflow 11.11.4 (already in `webui/package.json` — no new dependency).

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────┐
│  Frontend (reactflow)                           │
│  ┌──────────────────────┐  ┌─────────────────┐ │
│  │ GlobalGraphPage      │  │ GroupDetailPage  │ │
│  │ (force-directed)     │  │ (radial layout)  │ │
│  └──────────┬───────────┘  └───────┬─────────┘ │
│             │                       │           │
│         fetchGraph()           fetchGraph(      │
│         (watched=true)          group_id=id)    │
└─────────────┼───────────────────────┼──────────┘
              │                       │
┌─────────────▼───────────────────────▼──────────┐
│  Backend API                                    │
│  GET /api/threat-intel/graph                    │
│  → repo.py::get_graph_data()                    │
│    1. Query nodes from DB                       │
│    2. Merge shared IPs/malware into single node │
│    3. Cluster nodes exceeding top_n             │
│    4. Return {nodes, edges}                     │
└─────────────────────────────────────────────────┘
```

---

## 2. Backend: Graph Aggregation API

### 2.1 Endpoint

```
GET /api/threat-intel/graph
```

### 2.2 Request Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `group_id` | string | — | Single group: return local graph (group + its IPs/malware/vulns) |
| `watched` | bool | — | `true`: return graph for all Watchlist groups |
| `group_ids` | string | — | Comma-separated group IDs for multi-group comparison (e.g. `a,b,c`) |
| `top_n` | int | `30` | Max nodes per type per group before clustering |
| `min_confidence` | float | `0.0` | Minimum edge confidence to include |
| `node_types` | string | — | Comma-separated filter: `ip,malware,vuln` (omit for all) |
| `expand_cluster` | string | — | Expand a cluster node: pass cluster ID (e.g. `ip`) to get real sub-nodes |

**Mode selection** (exactly one must be provided):
- `group_id` → single-group local graph
- `watched=true` → all Watchlist groups global graph
- `group_ids=a,b,c` → multi-group comparison graph

### 2.3 API Response Structure

```json
{
  "nodes": [
    {
      "id": "01HQ...group_ulid",
      "type": "group",
      "label": "APT41",
      "data": {
        "mitre_id": "G0096",
        "origin_country": "China",
        "is_watched": true,
        "ip_count": 87,
        "malware_count": 5,
        "vuln_count": 12
      }
    },
    {
      "id": "01HQ...ip_ulid",
      "type": "ip",
      "label": "192.168.1.1",
      "data": {
        "ip_type": "c2",
        "status": "active",
        "geo_country": "Germany",
        "malware_family": "ShadowPad",
        "first_seen": "2026-06-01",
        "last_seen": "2026-06-15"
      }
    },
    {
      "id": "cluster:ip:01HQ...group_ulid",
      "type": "cluster",
      "label": "C2 IP × 67",
      "data": {
        "cluster_type": "ip",
        "count": 67,
        "group_id": "01HQ...group_ulid"
      }
    }
  ],
  "edges": [
    {
      "source": "01HQ...group_ulid",
      "target": "01HQ...ip_ulid",
      "type": "uses_c2",
      "confidence": 0.85
    },
    {
      "source": "01HQ...group_ulid",
      "target": "01HQ...malware_ulid",
      "type": "uses_malware",
      "confidence": 0.9
    },
    {
      "source": "01HQ...group_ulid",
      "target": "01HQ...vuln_ulid",
      "type": "exploits",
      "confidence": 0.8
    }
  ],
  "metadata": {
    "total_nodes": 145,
    "total_edges": 132,
    "clustered_nodes": 67,
    "groups_included": 3
  }
}
```

### 2.4 Node Types

| Type | Source Table | ID Format | Label |
|------|-------------|-----------|-------|
| `group` | `threat_group` | ULID | Group name |
| `ip` | `threat_infra_ip` | ULID (or merged ID) | IP address |
| `malware` | `threat_malware_family` | ULID (or merged ID) | Family name |
| `vuln` | `threat_vuln` | ULID | CVE ID |
| `cluster` | (computed) | `cluster:<type>:<group_id>` | `"<Type> × <count>"` |

### 2.5 Edge Types

| Edge Type | Source → Target | Label | Style |
|-----------|----------------|-------|-------|
| `uses_c2` | group → ip | uses_c2 | solid |
| `uses_malware` | group → malware | uses_malware | solid |
| `exploits` | group → vuln (relationship_type=exploited) | exploits | bold solid |
| `targets` | group → vuln (relationship_type=targeted/reported) | targets | dashed |

### 2.6 Node Merging Logic (CRITICAL)

When the same IP address or malware family is associated with multiple groups, the graph API MUST merge them into a single node with edges to each group.

**Implementation** (`repo.py::get_graph_data()`):

```python
# After querying all ThreatInfraIPs for the selected groups:
ip_merge_map: dict[str, str] = {}  # ip_address → canonical_node_id

for ip in all_ips:
    if ip.ip_address not in ip_merge_map:
        ip_merge_map[ip.ip_address] = ip.id  # First occurrence = canonical ID
    # Edge: group → canonical IP node
    edges.append({
        "source": ip.group_id,
        "target": ip_merge_map[ip.ip_address],  # Merged target
        "type": "uses_c2",
        "confidence": ip.confidence,
    })
```

**Same logic applies to malware families**: merge by `lower(family_name)`.

> **Database writes are NOT affected** — merging happens only in the API response layer. The DB still stores one row per `(group_id, ip_address, ip_type)`.

### 2.7 Clustering Logic

When a group has more than `top_n` nodes of a given type, excess nodes are replaced by a cluster node:

```python
# For each group, count nodes by type:
group_ip_counts: dict[str, int] = {}
for ip in all_ips:
    group_ip_counts[ip.group_id] = group_ip_counts.get(ip.group_id, 0) + 1

# If count > top_n, create cluster node and exclude individual nodes:
for group_id, count in group_ip_counts.items():
    if count > top_n:
        cluster_node = {
            "id": f"cluster:ip:{group_id}",
            "type": "cluster",
            "label": f"C2 IP × {count}",
            "data": {"cluster_type": "ip", "count": count, "group_id": group_id}
        }
        nodes.append(cluster_node)
        edges.append({"source": group_id, "target": cluster_node["id"], "type": "uses_c2", "confidence": 1.0})
        # Exclude this group's individual IP nodes from the response
```

### 2.8 Cluster Expansion

When `expand_cluster=ip` is passed with `group_id=<id>`:

```python
# Return ONLY the expanded cluster's real nodes (no other nodes):
# GET /graph?group_id=xxx&expand_cluster=ip
# → Returns all IP nodes for that group (bypassing top_n limit)
```

Response for cluster expansion contains only the expanded nodes + their edges to the group.

### 2.9 Confidence Filtering

Edges with `confidence < min_confidence` are excluded. This also excludes orphaned nodes (nodes with no remaining edges).

```python
# After building edges, filter:
edges = [e for e in edges if e["confidence"] >= min_confidence]

# Remove orphaned nodes:
connected_ids = {e["source"] for e in edges} | {e["target"] for e in edges}
nodes = [n for n in nodes if n["id"] in connected_ids or n["type"] == "group"]
```

### 2.10 API Handler

In `threat_intel_routes.py`:

```python
async def handle_get_graph(request: web.Request) -> web.Response:
    """GET /api/threat-intel/graph — knowledge graph data."""
    await _ensure_engine()
    group_id = _query_param(request, "group_id")
    watched = _bool_param(request, "watched")
    group_ids = _query_param(request, "group_ids")
    top_n = _int_param(request, "top_n", 30)
    min_confidence = _float_param(request, "min_confidence", 0.0)
    node_types = _query_param(request, "node_types")
    expand_cluster = _query_param(request, "expand_cluster")

    # Validate: exactly one mode
    modes = sum(1 for x in [group_id, watched, group_ids] if x)
    if modes != 1:
        return _error(400, "invalid_mode", "Provide exactly one of: group_id, watched=true, group_ids")

    async with get_session() as session:
        data = await get_graph_data(
            session,
            group_id=group_id,
            watched=bool(watched),
            group_ids=group_ids.split(",") if group_ids else None,
            actor_id=DEFAULT_ACTOR,
            top_n=top_n,
            min_confidence=min_confidence,
            node_types=node_types.split(",") if node_types else None,
            expand_cluster=expand_cluster,
        )
    return web.json_response(data)
```

Register route:
```python
router.add_get("/api/threat-intel/graph", handle_get_graph)
```

---

## 3. Frontend: Global Knowledge Graph Page

### 3.1 Route

`/threat-intel/graph` — registered in `webui/src/App.tsx`.

### 3.2 Component Structure

```
GraphPage.tsx
├── GraphToolbar.tsx          (search, group multi-select, node type filter, confidence slider)
├── ReactFlowCanvas.tsx       (reactflow instance with force-directed layout)
│   ├── CustomNode.tsx        (shape + icon + gradient per node type)
│   ├── CustomEdge.tsx        (solid/dashed/bold per edge type)
│   └── ClusterNode.tsx       (aggregation node with count badge)
├── NodeDetailDrawer.tsx      (right-side drawer on node click)
├── GraphLegend.tsx           (bottom-right legend)
└── GraphStatusBar.tsx        (bottom status bar: node/edge count + freshness)
```

### 3.3 Default Load

On mount, fetch `GET /graph?watched=true&top_n=30`. If Watchlist is empty, show empty state: "尚无关注组织，请先在组织列表中添加关注".

### 3.4 Layout Algorithm

Use `reactflow` with `d3-force` layout (via `react-force-graph` or custom force simulation):

```typescript
// Use dagre or d3-force for layout
// Force-directed: groups cluster together via shared infrastructure
import { forceSimulation, forceManyBody, forceLink, forceCenter } from "d3-force";
```

**Alternative**: If d3-force is not available, use reactflow's built-in `useReactFlow().fitView()` with manual positioning via force simulation.

> **Constraint**: No new graph layout library. Use d3-force (already available via recharts dependency) or manual positioning.

### 3.5 Node Visual Encoding

| Node Type | Shape | Icon (lucide-react) | Gradient CSS |
|-----------|-------|---------------------|-------------|
| group | hexagon | `Shield` | `bg-gradient-to-br from-indigo-500 to-violet-500` |
| ip | circle | `Server` | `bg-gradient-to-br from-amber-500 to-orange-500` |
| malware | diamond | `Bug` | `bg-gradient-to-br from-rose-500 to-red-500` |
| vuln (critical) | rounded rect | `AlertTriangle` | `bg-gradient-to-br from-rose-500 to-red-500` |
| vuln (high) | rounded rect | `AlertTriangle` | `bg-gradient-to-br from-amber-500 to-orange-500` |
| cluster | circle (dashed border) | `Layers` | `bg-slate-200 text-slate-600` |

**All nodes**: White text/icon on gradient background. Node size proportional to importance (groups largest, clusters medium, leaf nodes smallest).

### 3.6 Custom Node Implementation

```tsx
// CustomNode.tsx — register by type
const nodeTypes = {
  group: GroupNode,
  ip: IPNode,
  malware: MalwareNode,
  vuln: VulnNode,
  cluster: ClusterNode,
};

function GroupNode({ data }: NodeProps) {
  return (
    <div className="flex items-center gap-2 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-500 px-3 py-2 text-white shadow-lg">
      <Shield className="h-4 w-4" />
      <span className="text-sm font-medium">{data.label}</span>
      {data.is_watched && <Star className="h-3 w-3 fill-yellow-300 text-yellow-300" />}
    </div>
  );
}
```

### 3.7 Edge Styles

```tsx
const edgeTypes = {
  uses_c2: { stroke: "#6366F1", strokeWidth: 1.5, strokeDasharray: "0" },
  uses_malware: { stroke: "#F43F5E", strokeWidth: 1.5, strokeDasharray: "0" },
  exploits: { stroke: "#DC2626", strokeWidth: 3, strokeDasharray: "0" },
  targets: { stroke: "#F59E0B", strokeWidth: 1.5, strokeDasharray: "5,5" },
};
```

### 3.8 Interactions

#### Click Node → Drawer + Animate Center

```tsx
const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
  setSelectedNode(node);
  // Animate: center the node
  reactFlowInstance.fitView({ nodes: [node.id], duration: 600, padding: 0.3 });
}, [reactFlowInstance]);
```

**Drawer content** (by node type):
- **group**: Name, aliases, MITRE ID, origin country, IP/malware/vuln counts, source refs (first 3).
- **ip**: IP address, type, status, geo, malware family, first/last seen, source refs (first 3).
- **malware**: Family name, type, platform, aliases, sample count, source refs (first 3).
- **vuln**: CVE ID, title, CVSS, severity, is_cisa_kev, is_supply_chain, source refs (first 3).
- **cluster**: Cluster type, count, "点击展开" button → calls expand API.

#### Click Cluster → Expand

```tsx
const onClusterClick = useCallback(async (_: React.MouseEvent, node: Node) => {
  if (node.type !== "cluster") return;
  const clusterType = node.data.cluster_type;
  const groupId = node.data.group_id;
  // Fetch expanded nodes
  const expanded = await fetchGraph(token, { group_id: groupId, expand_cluster: clusterType });
  // Replace cluster node with real nodes
  setNodes(prev => [...prev.filter(n => n.id !== node.id), ...expanded.nodes]);
  setEdges(prev => [...prev.filter(e => e.source !== node.id), ...expanded.edges]);
}, [token]);
```

### 3.9 Toolbar

| Control | Component | Behavior |
|---------|-----------|----------|
| Search | `Input` | Filter by name/CVE/IP — on match, `fitView({ nodes: [matched_id] })` |
| Group multi-select | `MultiSelect` | Select groups to display (default = all Watchlist) |
| Node type filter | `Checkbox[]` | Toggle IP / Malware / Vulnerability visibility |
| Confidence slider | `Slider` | Min confidence threshold (0.0–1.0), refetch on release |

### 3.10 Legend & Status Bar

**Legend** (bottom-right, `GraphLegend.tsx`):
- 5 color swatches for node types (matching §3.5 gradients)
- 4 edge style samples (solid, bold, dashed)

**Status bar** (bottom, `GraphStatusBar.tsx`):
- `节点: {total_nodes} | 边: {total_edges}`
- `数据新鲜度: {last_success_at}` (from metadata)

### 3.11 Performance Strategy

- **Node limit**: Initial render ≤ 200 nodes. If exceeded, reduce `top_n` automatically.
- **Cluster threshold**: `top_n=30` per group per type. Groups with >30 IPs show cluster.
- **Virtualization**: reactflow handles off-screen nodes efficiently.
- **Debounce**: Toolbar changes debounce 500ms before refetch.

```typescript
// Auto-adjust top_n if too many nodes
useEffect(() => {
  if (data.metadata.total_nodes > 200 && topN > 10) {
    setTopN(Math.max(10, Math.floor(topN * 0.7)));
  }
}, [data.metadata.total_nodes, topN]);
```

---

## 4. Frontend: Group Detail Local Graph

### 4.1 Location

Embedded in `GroupDetailPage.tsx` — a tab or section below the group info.

### 4.2 Layout: Radial

Single group at center, IP/malware/vuln nodes distributed on outer ring:

```typescript
// Radial positioning
const radius = 200;
const angleStep = (2 * Math.PI) / nodes.length;
nodes.forEach((node, i) => {
  node.position = {
    x: centerX + radius * Math.cos(i * angleStep),
    y: centerY + radius * Math.sin(i * angleStep),
  };
});
```

### 4.3 Differences from Global Graph

| Aspect | Global Graph | Local Graph |
|--------|-------------|-------------|
| Layout | Force-directed | Radial (fixed) |
| Default nodes | All Watchlist groups | Single group + direct relations |
| Clustering | Enabled (top_n=30) | Disabled (single group, manageable count) |
| Cluster expand | Yes | No |
| Group multi-select | Yes | No (fixed to this group) |

### 4.4 Data Fetch

```typescript
const graphData = await fetchGraph(token, { group_id: groupId, top_n: 100 });
// top_n=100 to avoid clustering in local view
```

---

## 5. Frontend API Client Extension

Add to `webui/src/lib/threat-intel-client.ts`:

```typescript
// ── Graph Types ──────────────────────────────────────────────────────

export interface GraphNode {
  id: string;
  type: "group" | "ip" | "malware" | "vuln" | "cluster";
  label: string;
  data: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: "uses_c2" | "uses_malware" | "exploits" | "targets";
  confidence: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  metadata: {
    total_nodes: number;
    total_edges: number;
    clustered_nodes: number;
    groups_included: number;
  };
}

// ── Graph API Function ───────────────────────────────────────────────

export async function fetchGraph(
  token: string,
  params: {
    group_id?: string;
    watched?: boolean;
    group_ids?: string[];
    top_n?: number;
    min_confidence?: number;
    node_types?: string[];
    expand_cluster?: string;
  },
): Promise<GraphData> {
  const search = new URLSearchParams();
  if (params.group_id) search.set("group_id", params.group_id);
  if (params.watched !== undefined) search.set("watched", String(params.watched));
  if (params.group_ids) search.set("group_ids", params.group_ids.join(","));
  if (params.top_n) search.set("top_n", String(params.top_n));
  if (params.min_confidence !== undefined) search.set("min_confidence", String(params.min_confidence));
  if (params.node_types) search.set("node_types", params.node_types.join(","));
  if (params.expand_cluster) search.set("expand_cluster", params.expand_cluster);
  const qs = search.toString();
  return request<GraphData>(`${BASE}/graph${qs ? `?${qs}` : ""}`, token);
}
```

---

## 6. Forbidden Patterns

| Pattern | Why Forbidden | Do Instead |
|---------|--------------|------------|
| Introducing new graph library | Project whitelist: reactflow + recharts only | Use reactflow 11.11.4 |
| Writing merged nodes back to DB | Merging is a response-layer concern only | DB keeps per-group records; API response merges |
| Dark theme for graph | Module uses light style (#F5F7FA) | Use `bg-slate-50` background |
| Rendering >500 nodes without clustering | Browser performance degradation | Enforce `top_n` and cluster |
| Hardcoding node positions in global graph | Force-directed layout must adapt to data | Use d3-force simulation |
| Inline cluster expansion (client-side) | Cluster contents need server-side query | Call `GET /graph?expand_cluster=...` |
| Raw hex colors in node styles | Violates frontend coding standards | Use Tailwind gradient classes |

---

## 7. Tests Required

### Backend

- [ ] **Node merging**: Same IP from 2 groups → 1 node, 2 edges.
- [ ] **Clustering**: Group with 35 IPs, `top_n=30` → 1 cluster node + 30 real nodes excluded.
- [ ] **Cluster expand**: `expand_cluster=ip` returns only expanded IP nodes.
- [ ] **Confidence filter**: `min_confidence=0.8` excludes edges below threshold + orphaned nodes.
- [ ] **Node type filter**: `node_types=ip,vuln` excludes malware nodes.
- [ ] **Empty watchlist**: `watched=true` with no watchlist → empty graph (0 nodes, 0 edges).
- [ ] **Mode validation**: No mode or multiple modes → 400 error.

### Frontend

- [ ] **Global graph renders**: Watchlist groups + relations display with correct node shapes.
- [ ] **Click node → drawer**: Drawer shows correct summary for each node type.
- [ ] **Click cluster → expand**: Cluster node replaced with real nodes.
- [ ] **Local graph**: Radial layout with group at center.
- [ ] **Search**: Typing in search box filters and centers on matching node.
- [ ] **Performance**: 200 nodes render without jank (>30fps).

---

## Origin

Source: `docs/prd-threat-intelligence.md` §6.2 (graph API params) + §7.2 (graph page UI) + §9.3 (PRD clarifications on node merging).
