# Threat Intel Knowledge Graph as a reactflow Dual-Mode Visualization

The threat intelligence knowledge graph is implemented as a reactflow-based interactive visualization with two modes (local radial + global force-directed), served by a dedicated backend aggregation API, and placed entirely in P1 rather than P0.

## Context

The **Threat Intel Store** models a star-shaped domain with **Threat Groups** at the center, surrounded by **Threat Infrastructure IPs**, **Threat Malware Families**, and **Threat Vulnerabilities**. Users need to visually explore these relationships — both for deep-diving into a single group's infrastructure and for comparing overlap across multiple groups.

The project already depends on reactflow (11.11.4) for the Asset Risk Topology. The alternative of composing graph data from existing list APIs on the frontend was rejected because multi-group queries would require N+1 round trips and client-side deduplication.

## Decision

- **Library**: Reuse reactflow (already in `package.json`); no new graph visualization dependency.
- **Dual-mode rendering**:
  - **Local graph** embedded in the **Threat Group** detail page (`/threat-intel/groups/:id`): radial layout with the group at center. No clustering (single-group node count is manageable).
  - **Global graph** at `/threat-intel/graph`: force-directed layout. Default scope is Watchlist groups. Shared infrastructure (same IP or malware used by multiple groups) naturally clusters visually.
- **Dedicated backend API**: `GET /api/threat-intel/graph` returns `{nodes, edges}` with support for `group_id`, `watched=true`, and `group_ids=a,b,c` query parameters. Supports `top_n` clustering (default 30 per entity type per group), `min_confidence` edge filtering, and `node_types` filtering. Cluster nodes (`type: "cluster"`) are expandable via `expand_cluster` parameter.
- **Node visual encoding**: Group=hexagon/blue, IP=circle/orange, Malware=diamond/red, Vulnerability=rounded-rect/severity-colored. Edge styles encode relationship type (uses_c2, uses_malware, exploits, targets) with solid/dashed/thick variants.
- **Interaction**: Single-click node opens a side drawer with summary data and animates the graph viewport to center on that node. No navigation away from the graph.
- **Maritime Intelligence Events excluded**: They are an independent time-series dimension with no Threat Group associations and would appear as disconnected island nodes.
- **MVP phase**: Entirely in P1. P0 only has Group + IP data (two node types), which produces a graph too sparse to deliver user value, and P0 delivery scope is already substantial.

## Consequences

- The graph API requires a new repository method that performs JOIN queries across group, IP, malware, vulnerability, and association tables — this is the first cross-table aggregation query in the threat intel repo.
- reactflow's built-in viewport animation (`fitView`, `setCenter`) handles the fly-to-node interaction without additional animation libraries.
- The clustering strategy means the frontend must handle two node types (real + cluster) and request expansion on cluster click, adding UI state complexity.
- Force-directed layout for the global graph may need parameter tuning (repulsion, link distance) as data grows beyond initial estimates.
- The decision to exclude Maritime Events from the graph reinforces the APT-centric star model boundary — maritime data has its own visualization path (timeline).
