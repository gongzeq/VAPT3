# P1/P2 Gap Fixes Spec

> Spec for fixing 13 gaps identified during code review against P1/P2 specs.
> Each gap includes: problem description, spec reference, implementation contract, and acceptance criteria.
> Source: Code review of commits `4fb14b9ae` → `ad079289e` (60 files, 15430 lines).

---

## Priority Overview

| Priority | Count | Description |
|----------|-------|-------------|
| P0 | 3 | Core feature completely missing — must fix before merge |
| P1 | 7 | Feature incomplete — fix in current iteration |
| P2 | 3 | UX detail missing — fix in next iteration |

---

## P0: Core Feature Missing

### 1. Feed Failure WebSocket Notification

**Gap**: `detail-and-management.md §5` requires broadcasting `threat_intel_feed_failed` event on failed feed pull. Neither backend broadcast nor frontend toast exists.

**Spec reference**: [detail-and-management.md §5](./detail-and-management.md#5-feed-pull-failure-notification)

#### 1.1 Backend: Broadcast in `finish_feed_pull_run`

In `secbot/threat_intel/repo.py::finish_feed_pull_run()`, after setting `status="failed"`, broadcast event:

```python
async def finish_feed_pull_run(
    session: AsyncSession,
    *,
    run_id: str,
    status: str,
    inserted_count: int = 0,
    updated_count: int = 0,
    skipped_count: int = 0,
    unmapped_count: int = 0,
    error_message: Optional[str] = None,
    metadata_json: Optional[dict] = None,
) -> None:
    # ... existing code to update FeedPullRun ...

    # Broadcast failure event
    if status == "failed":
        try:
            from secbot.bus import get_bus
            bus = get_bus()
            await bus.broadcast({
                "type": "agent_event",
                "event_type": "threat_intel_feed_failed",
                "data": {
                    "source": run.source,
                    "run_id": run_id,
                    "error_message": error_message or "Unknown error",
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "failed_at": _utcnow().isoformat(),
                },
            })
        except Exception:
            _logger.warning("Failed to broadcast feed failure event", exc_info=True)
```

**Key requirements**:
- Only `status="failed"` triggers broadcast. `status="partial"` does NOT.
- Use existing `secbot.bus` event system.
- Event follows `agent_event` protocol with `event_type="threat_intel_feed_failed"`.

#### 1.2 Frontend: Toast Notification

In the WebUI WebSocket message handler (where `agent_event` messages are processed), add a case:

```typescript
case "threat_intel_feed_failed": {
  const data = event.data as {
    source: string;
    run_id: string;
    error_message: string;
  };
  // Show dismissible toast (not blocking alert)
  showToast({
    title: "Feed拉取失败",
    description: `${data.source} 拉取失败: ${data.error_message}`,
    variant: "destructive",
  });
  // If on FeedsPage, refresh the list
  if (location.pathname === "/threat-intel/feeds") {
    refreshFeedRuns();
  }
  // If on OverviewPage, refresh freshness data
  if (location.pathname === "/threat-intel") {
    refreshOverview();
  }
  break;
}
```

**Key requirements**:
- Toast is dismissible, not a blocking alert.
- Only `failed` triggers toast; `partial` does not.
- Auto-refresh FeedsPage / OverviewPage if user is on those pages.

#### 1.3 Acceptance Criteria

- [ ] `finish_feed_pull_run` with `status="failed"` broadcasts `threat_intel_feed_failed` event.
- [ ] `status="partial"` does NOT broadcast.
- [ ] Frontend shows dismissible toast on `threat_intel_feed_failed` event.
- [ ] FeedsPage auto-refreshes if user is on that page when event arrives.

---

### 2. Industry CPE Management Page

**Gap**: `detail-and-management.md §6` requires a CPE management page at `/threat-intel/config/industry-cpes`. Backend API exists (GET/POST/DELETE), but no frontend route or page component.

**Spec reference**: [detail-and-management.md §6](./detail-and-management.md#6-industry-cpe-management-ui)

#### 2.1 Route Registration

In `webui/src/App.tsx`, add inside the `<Route path="/threat-intel" element={<ThreatIntelLayout />}>` block:

```tsx
<Route path="config/industry-cpes" element={<IndustryCPEPage />} />
```

#### 2.2 Component: `IndustryCPEPage.tsx`

Create `webui/src/pages/threat-intel/IndustryCPEPage.tsx`:

```tsx
/**
 * Industry CPE Management Page — admin configuration for maritime/transport CPE entries.
 * Features: list, add, filter by industry_tag, delete.
 */
export function IndustryCPEPage() {
  // State: items, loading, filter (industry_tag), new CPE form
  // API calls:
  //   GET  /api/threat-intel/config/industry-cpes  → list
  //   POST /api/threat-intel/config/industry-cpes  → add
  //   DELETE /api/threat-intel/config/industry-cpes/:id → delete
  // Layout:
  //   [Search/Filter by industry_tag] [Add CPE form]
  //   Table: CPE string | Product name | Vendor | Industry tag | Confidence | [Delete]
}
```

**Features**:

| Feature | API | Notes |
|---------|-----|-------|
| List all CPE entries | `GET /config/industry-cpes` | Already implemented |
| Add new CPE | `POST /config/industry-cpes` | Body: `{cpe_string, product_name, vendor?, industry_tag?, confidence?}` |
| Filter by `industry_tag` | Client-side filter | maritime / transport / scada / port |
| Delete CPE entry | `DELETE /config/industry-cpes/:id` | Already implemented |

**Layout**:
```
┌──────────────────────────────────────────┐
│ 行业CPE管理                               │
│                                          │
│ [行业标签▾] [搜索框]      [新增CPE]       │
│                                          │
│ ┌──────────────────────────────────────┐ │
│ │ CPE              产品      标签  [删除]│ │
│ │ cpe:2.3:a:siemens SIMATIC   maritime  │ │
│ │ cpe:2.3:a:schneider Modicon maritime  │ │
│ └──────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

**API client functions** (already exist in `threat-intel-client.ts`):
- `fetchIndustryCPEs(token)` → `{items, total}`
- `addIndustryCPE(token, data)` → `{id, cpe_string, product_name}`
- `deleteIndustryCPE(token, cpeId)` → `void`

#### 2.3 Acceptance Criteria

- [ ] `/threat-intel/config/industry-cpes` route registered in App.tsx.
- [ ] Page lists all CPE entries with product name, vendor, industry tag.
- [ ] Add new CPE form works (cpe_string + product_name required).
- [ ] Filter by industry_tag works (client-side).
- [ ] Delete button removes CPE entry with confirmation.

---

### 3. GroupDetailPage Local Graph

**Gap**: `graph-contract.md §4` requires a radial-layout local graph embedded in GroupDetailPage. Current page only has tab lists (IPs/Malware/Vulns/Aliases), no graph visualization.

**Spec reference**: [graph-contract.md §4](./graph-contract.md#4-frontend-group-detail-local-graph)

#### 3.1 Implementation

Add a "图谱" tab or section in `GroupDetailPage.tsx` that renders a reactflow graph with radial layout:

```tsx
import ReactFlow, { Background, Controls } from "reactflow";

// Radial positioning: group at center, relations on outer ring
function applyRadialLayout(nodes: Node[], centerX = 300, centerY = 250): Node[] {
  const groupNode = nodes.find((n) => n.type === "group");
  const otherNodes = nodes.filter((n) => n.type !== "group");
  const radius = 200;
  const angleStep = (2 * Math.PI) / Math.max(otherNodes.length, 1);

  return [
    { ...groupNode, position: { x: centerX, y: centerY } },
    ...otherNodes.map((node, i) => ({
      ...node,
      position: {
        x: centerX + radius * Math.cos(i * angleStep),
        y: centerY + radius * Math.sin(i * angleStep),
      },
    })),
  ];
}

// Fetch with top_n=100 to avoid clustering in local view
const graphData = await fetchGraph(token, { group_id: groupId, top_n: 100 });
```

**Key requirements**:

| Aspect | Global Graph | Local Graph (this) |
|--------|-------------|-------------------|
| Layout | Force-directed | Radial (fixed) |
| Default nodes | All Watchlist groups | Single group + direct relations |
| Clustering | Enabled (top_n=30) | Disabled (top_n=100) |
| Cluster expand | Yes | No |
| Group multi-select | Yes | No (fixed to this group) |

**Reuses**: Same `nodeTypes`, `edgeStyles`, custom node components from GraphPage.

#### 3.2 Acceptance Criteria

- [ ] GroupDetailPage has a "图谱" tab showing reactflow canvas.
- [ ] Group node at center, IP/malware/vuln nodes on outer ring.
- [ ] `top_n=100` passed to avoid clustering.
- [ ] Clicking nodes in local graph opens detail drawer (same as global graph).
- [ ] No cluster nodes appear in local graph.

---

## P1: Feature Incomplete

### 4. GraphPage Toolbar

**Gap**: `graph-contract.md §3.9` requires a toolbar with search, group multi-select, node type filter, and confidence slider. Current GraphPage only has a refresh button.

**Spec reference**: [graph-contract.md §3.9](./graph-contract.md#39-toolbar)

#### 4.1 Implementation

Add a `GraphToolbar` component above the reactflow canvas:

```tsx
interface GraphToolbarProps {
  onSearch: (query: string) => void;
  onGroupSelect: (groupIds: string[]) => void;
  onNodeTypeFilter: (types: string[]) => void;
  onConfidenceChange: (minConfidence: number) => void;
  topN: number;
  onTopNChange: (n: number) => void;
}
```

| Control | Component | Behavior |
|---------|-----------|----------|
| Search | `Input` | Filter by name/CVE/IP — on match, `fitView({ nodes: [matched_id] })` |
| Group multi-select | `MultiSelect` | Select groups to display (default = all Watchlist) |
| Node type filter | `Checkbox[]` | Toggle IP / Malware / Vulnerability visibility |
| Confidence slider | `Slider` | Min confidence threshold (0.0–1.0), refetch on release |

**Debounce**: Toolbar changes debounce 500ms before refetch.

**Auto-adjust top_n**: If `data.metadata.total_nodes > 200` and `topN > 10`, reduce `topN` to `Math.max(10, Math.floor(topN * 0.7))`.

#### 4.2 Acceptance Criteria

- [ ] Search box filters nodes by name/CVE/IP and centers on match.
- [ ] Group multi-select allows choosing which Watchlist groups to display.
- [ ] Node type checkbox toggles IP/Malware/Vuln visibility.
- [ ] Confidence slider refetches graph with `min_confidence` param.
- [ ] All toolbar changes debounce 500ms.

---

### 5. GraphPage Force-Directed Layout

**Gap**: `graph-contract.md §3.4` requires d3-force force-directed layout. Current implementation uses concentric circle manual positioning (`applyForceLayout`).

**Spec reference**: [graph-contract.md §3.4](./graph-contract.md#34-layout-algorithm)

#### 5.1 Implementation

Replace `applyForceLayout` with d3-force simulation:

```typescript
import { forceSimulation, forceManyBody, forceLink, forceCenter } from "d3-force";

function applyD3ForceLayout(
  nodes: Node[],
  edges: Edge[],
  width = 800,
  height = 600,
): Node[] {
  const simNodes = nodes.map((n) => ({
    ...n,
    x: n.position?.x ?? width / 2 + Math.random() * 100,
    y: n.position?.y ?? height / 2 + Math.random() * 100,
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
```

**Constraint**: Use d3-force (already available via recharts dependency). No new graph layout library.

#### 5.2 Acceptance Criteria

- [ ] Groups with shared IPs/malware naturally cluster together.
- [ ] Layout adapts to data changes (not hardcoded positions).
- [ ] 200 nodes render without jank (>30fps).

---

### 6. GraphPage Click Node Animate Center

**Gap**: `graph-contract.md §3.8` requires `fitView({ nodes: [node.id], duration: 600 })` on node click. Current implementation only opens drawer.

**Spec reference**: [graph-contract.md §3.8](./graph-contract.md#358-interactions)

#### 6.1 Implementation

```tsx
const reactFlowInstance = useRef<ReactFlowInstance | null>(null);

const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
  setSelectedNode(graphData?.nodes.find((n) => n.id === node.id) || null);
  // Animate: center the clicked node
  reactFlowInstance.current?.fitView({
    nodes: [node.id],
    duration: 600,
    padding: 0.3,
  });
}, [graphData]);

<ReactFlow
  onInit={(instance) => { reactFlowInstance.current = instance; }}
  onNodeClick={onNodeClick}
  // ...
/>
```

#### 6.2 Acceptance Criteria

- [ ] Clicking a node animates the view to center on that node over 600ms.
- [ ] Drawer opens simultaneously with the animation.

---

### 7. GraphPage Status Bar

**Gap**: `graph-contract.md §3.10` requires a status bar showing node/edge count AND data freshness. Current implementation only shows counts.

**Spec reference**: [graph-contract.md §3.10](./graph-contract.md#310-legend--status-bar)

#### 7.1 Implementation

Add a `GraphStatusBar` component at the bottom of the graph:

```tsx
function GraphStatusBar({ metadata }: { metadata: GraphData["metadata"] }) {
  // Fetch last successful feed run time for freshness
  return (
    <div className="flex items-center justify-between rounded-lg bg-white px-4 py-2 text-xs text-slate-600">
      <span>节点: {metadata.total_nodes} | 边: {metadata.total_edges}</span>
      <span>聚类节点: {metadata.clustered_nodes} | 包含组织: {metadata.groups_included}</span>
      {/* Data freshness: show last successful FeedPullRun timestamp */}
      <span>数据新鲜度: {lastSuccessAt || "未知"}</span>
    </div>
  );
}
```

**Freshness data**: Fetch from `GET /api/threat-intel/feeds/runs?status=ok&page=1&page_size=1` to get the most recent successful run's `finished_at`.

#### 7.2 Acceptance Criteria

- [ ] Status bar shows node count, edge count, clustered nodes, groups included.
- [ ] Status bar shows data freshness (last successful feed run time).

---

### 8. Maritime pdfplumber PDF Extraction

**Gap**: `p2-pipeline.md §1.4` requires using `pdfplumber` for PDF text extraction (ReCAAP publishes PDFs). Current implementation only extracts HTML text with regex.

**Spec reference**: [p2-pipeline.md §1.4](./p2-pipeline.md#14-pdf-text-extraction)

#### 8.1 Dependency

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
threat-intel-p2 = [
    "pdfplumber>=0.11.0",
]
```

#### 8.2 Implementation

In `secbot/threat_intel/feeds/maritime.py`, add PDF extraction:

```python
def extract_pdf_text(pdf_path: str) -> list[str]:
    """Extract text from PDF, return page-by-page text chunks."""
    chunks = []
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    chunks.append(text)
    except ImportError:
        _logger.warning("pdfplumber not installed, skipping PDF extraction")
    except Exception as exc:
        _logger.warning("PDF extraction failed: %s", exc)
    return chunks


async def _fetch_recaap(http: aiohttp.ClientSession) -> str:
    """Fetch ReCAAP resources page and linked PDF reports."""
    # 1. GET https://www.recaap.org/resources
    # 2. Parse HTML for PDF links (filter for "Incident" reports)
    # 3. Download each PDF to temp file
    # 4. Extract text with pdfplumber
    # 5. Return combined text
    async with http.get(RECAAP_URL, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        if resp.status != 200:
            raise RuntimeError(f"ReCAAP fetch failed: HTTP {resp.status}")
        html = await resp.text()

    # Extract PDF links from HTML
    pdf_links = re.findall(r'href="([^"]+\.pdf)"', html, re.IGNORECASE)
    all_text = []

    # Also include HTML text (for non-PDF content)
    html_text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html_text = re.sub(r"<[^>]+>", " ", html_text)
    html_text = re.sub(r"\s+", " ", html_text).strip()
    all_text.append(html_text[:4000])

    # Download and extract PDFs (limit to 3 to avoid excessive downloads)
    for pdf_url in pdf_links[:3]:
        if not pdf_url.startswith("http"):
            pdf_url = f"https://www.recaap.org{pdf_url}"
        try:
            async with http.get(pdf_url, timeout=aiohttp.ClientTimeout(total=60)) as pdf_resp:
                if pdf_resp.status == 200:
                    pdf_data = await pdf_resp.read()
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        tmp.write(pdf_data)
                        tmp_path = tmp.name
                    chunks = extract_pdf_text(tmp_path)
                    all_text.extend(chunks)
                    os.unlink(tmp_path)
        except Exception as exc:
            _logger.warning("Failed to fetch/extract PDF %s: %s", pdf_url, exc)

    return "\n\n".join(all_text)[:8000]
```

**Key requirements**:
- `pdfplumber` is optional dependency — code must degrade gracefully if not installed.
- Limit PDF downloads to 3 per pull to avoid excessive network usage.
- Clean up temp files after extraction.

#### 8.3 Acceptance Criteria

- [ ] `pdfplumber` added to `pyproject.toml` optional dependencies.
- [ ] ReCAAP fetch downloads linked PDF reports and extracts text.
- [ ] Graceful fallback when `pdfplumber` not installed (warning log, HTML-only extraction).
- [ ] Temp PDF files cleaned up after extraction.

---

### 9. ReviewQueuePage Remap Action

**Gap**: `p2-pipeline.md §4.5` requires a "重新关联" (remap) button with group selector. Current ReviewQueuePage only has "确认关联" and "驳回归档".

**Spec reference**: [p2-pipeline.md §4.5](./p2-pipeline.md#45-frontend-review-queue-page)

#### 9.1 Implementation

For IP entity type items, add a remap button with group selector dropdown:

```tsx
{item.entity_type === "ip" && (
  <>
    <button onClick={() => handleAction(item, "confirm_mapping")}>
      <Check /> 确认关联
    </button>
    {/* Remap: show group selector */}
    <button onClick={() => setShowRemap(item.id)}>
      <Shuffle /> 重新关联
    </button>
    {showRemap === item.id && (
      <div className="flex gap-2">
        <select
          value={remapGroupId}
          onChange={(e) => setRemapGroupId(e.target.value)}
        >
          <option value="">选择组织...</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>{g.name}</option>
          ))}
        </select>
        <button
          onClick={() => handleAction(item, "remap", { new_group_id: remapGroupId })}
          disabled={!remapGroupId}
        >
          确认
        </button>
        <button onClick={() => setShowRemap(null)}>取消</button>
      </div>
    )}
    <button onClick={() => handleAction(item, "dismiss")}>
      <X /> 驳回归档
    </button>
  </>
)}
```

**API**: `submitReviewAction(token, itemId, "remap", { entity_type: "ip", new_group_id: "..." })`

**Backend**: Already implemented in `apply_review_action()` — validates `new_group_id` and updates `ip.group_id` + `ip.confidence = 0.8`.

#### 9.2 Acceptance Criteria

- [ ] IP items show three buttons: 确认关联 / 重新关联 / 驳回归档.
- [ ] Clicking "重新关联" shows a group selector dropdown.
- [ ] Selecting a group and confirming calls `POST /review-queue/:id/action` with `action="remap"` and `new_group_id`.
- [ ] Maritime items do NOT show remap button (only confirm_event / dismiss).

---

### 10. ReviewQueuePage Note Input

**Gap**: `p2-pipeline.md §4.5` requires a note input field for each review item. Current ReviewQueuePage has no note input.

**Spec reference**: [p2-pipeline.md §4.5](./p2-pipeline.md#45-frontend-review-queue-page)

#### 10.1 Implementation

Add a note input below each review item:

```tsx
<div className="mt-2 flex items-center gap-2">
  <input
    type="text"
    placeholder="输入备注..."
    value={notes[item.id] || ""}
    onChange={(e) => setNotes({ ...notes, [item.id]: e.target.value })}
    className="flex-1 rounded border border-slate-200 px-3 py-1 text-sm"
  />
</div>
```

Pass note in action call:

```tsx
const handleAction = async (item: ReviewQueueItem, action: string, extra: Record<string, unknown> = {}) => {
  await submitReviewAction(token, item.id, action, {
    entity_type: item.entity_type,
    note: notes[item.id] || undefined,
    ...extra,
  });
};
```

**Backend**: `apply_review_action()` should optionally accept `note` and store it. For IP items, the note can be stored in a `tags` array or a dedicated `review_note` field. For maritime items, the note can be appended to `source_refs` metadata.

#### 10.2 Acceptance Criteria

- [ ] Each review item has a note input field.
- [ ] Note is passed to `POST /review-queue/:id/action` as `note` field.
- [ ] Note is optional — action works without note.

---

## P2: UX Detail Missing

### 11. MaritimePage Date Range Filter

**Gap**: `p2-pipeline.md §2.3` requires from/to date range filter. Current MaritimePage has type/severity/status filters but no date range.

**Spec reference**: [p2-pipeline.md §2.3](./p2-pipeline.md#23-features)

#### 11.1 Implementation

Add two date inputs to the filter bar:

```tsx
<input
  type="date"
  value={filter.from}
  onChange={(e) => setFilter({ ...filter, from: e.target.value })}
  className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
/>
<span className="text-slate-400">至</span>
<input
  type="date"
  value={filter.to}
  onChange={(e) => setFilter({ ...filter, to: e.target.value })}
  className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
/>
```

Pass to API: `fetchMaritimeEvents(token, { ...filter, from: filter.from, to: filter.to })`. Backend already supports `from` and `to` query params.

#### 11.2 Acceptance Criteria

- [ ] Two date pickers (from / to) in filter bar.
- [ ] Date range filter sends `from` and `to` params to `GET /maritime`.

---

### 12. MaritimePage Pagination

**Gap**: `p2-pipeline.md §2.2` shows pagination controls. Current MaritimePage has no pagination.

**Spec reference**: [p2-pipeline.md §2.2](./p2-pipeline.md#22-component-maritimepagetsx)

#### 12.1 Implementation

Add pagination controls at the bottom:

```tsx
const [page, setPage] = useState(1);
const pageSize = 20;
const totalPages = Math.ceil(total / pageSize);

// Pass page + page_size to API
fetchMaritimeEvents(token, { ...filter, page: String(page), page_size: String(pageSize) })

// Pagination UI
{totalPages > 1 && (
  <div className="flex items-center justify-center gap-2">
    <button
      onClick={() => setPage(p => Math.max(1, p - 1))}
      disabled={page === 1}
      className="rounded border px-3 py-1 disabled:opacity-50"
    >
      上一页
    </button>
    <span className="text-sm text-slate-600">
      {page} / {totalPages}
    </span>
    <button
      onClick={() => setPage(p => Math.min(totalPages, p + 1))}
      disabled={page === totalPages}
      className="rounded border px-3 py-1 disabled:opacity-50"
    >
      下一页
    </button>
  </div>
)}
```

#### 12.2 Acceptance Criteria

- [ ] Pagination controls appear when total > page_size.
- [ ] Page param sent to `GET /maritime`.
- [ ] Previous/Next buttons disabled at boundaries.

---

### 13. ReviewQueuePage Pagination

**Gap**: `p2-pipeline.md §4.5` shows pagination. Current ReviewQueuePage has no pagination.

**Spec reference**: [p2-pipeline.md §4.5](./p2-pipeline.md#45-frontend-review-queue-page)

#### 13.1 Implementation

Same pattern as MaritimePage pagination (§12.1). Use `page` and `page_size` params in `fetchReviewQueue()` call.

#### 13.2 Acceptance Criteria

- [ ] Pagination controls appear when total > page_size.
- [ ] Page param sent to `GET /review-queue`.
- [ ] Switching entity type resets to page 1.

---

## Implementation Order

```
Phase 1 (P0 — must fix before merge):
  1. Feed failure WS notification (backend + frontend)
  2. Industry CPE management page (frontend only)
  3. GroupDetailPage local graph (frontend only)

Phase 2 (P1 — current iteration):
  4. GraphPage toolbar
  5. GraphPage d3-force layout
  6. GraphPage click node animate center
  7. GraphPage status bar
  8. Maritime pdfplumber PDF extraction (backend)
  9. ReviewQueuePage remap action (frontend)
  10. ReviewQueuePage note input (frontend)

Phase 3 (P2 — next iteration):
  11. MaritimePage date range filter
  12. MaritimePage pagination
  13. ReviewQueuePage pagination
```

---

## Forbidden Patterns

| Pattern | Why Forbidden | Do Instead |
|---------|--------------|------------|
| Blocking alert for feed failure | User cannot dismiss | Use dismissible toast |
| Creating CPE page without delete button | Users cannot remove incorrect entries | Include delete with confirmation |
| Local graph with clustering enabled | Single group has manageable node count | Use `top_n=100` to disable clustering |
| Hardcoding node positions in force layout | Layout must adapt to data | Use d3-force simulation |
| Importing pdfplumber at module level | Fails if dependency not installed | Import inside function with try/except |
| Remap without group validation | Invalid group_id causes FK error | Backend already validates; frontend should show error toast |

---

## Tests Required

### Backend

- [ ] **Feed failure broadcast**: `finish_feed_pull_run(status="failed")` broadcasts event; `status="partial"` does not.
- [ ] **pdfplumber extraction**: Mock PDF → `extract_pdf_text()` returns text chunks.
- [ ] **pdfplumber missing**: `extract_pdf_text()` returns empty list, logs warning (no crash).

### Frontend

- [ ] **Feed failure toast**: WS event triggers dismissible toast.
- [ ] **CPE page**: List, add, filter, delete all work.
- [ ] **Local graph**: Radial layout with group at center, no cluster nodes.
- [ ] **Toolbar search**: Typing filters and centers on matching node.
- [ ] **Toolbar confidence slider**: Refetches graph with new threshold.
- [ ] **Force layout**: Shared IP groups cluster together visually.
- [ ] **Click animate center**: Node click triggers 600ms fitView animation.
- [ ] **Remap action**: Selecting new group and confirming updates IP mapping.
- [ ] **Note input**: Note passed to API on action submit.
- [ ] **Pagination**: MaritimePage and ReviewQueuePage paginate correctly.

---

## Origin

Source: Code review of threat intel P1/P2 implementation (commits `4fb14b9ae` → `ad079289e`) against `.trellis/spec/threat-intel/` specs (feed-integration, graph-contract, detail-and-management, p2-pipeline).
