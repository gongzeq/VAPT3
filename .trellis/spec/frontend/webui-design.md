# WebUI Design (Navigational Hub)

> Single entry point for everything UI in `webui/`. This document does NOT redefine rules — it links to the authoritative specs and pins the **view hierarchy** the PRD calls out.
> Source: `.trellis/tasks/05-07-cybersec-agent-platform/prd.md` §R8 + research/cybersec-ui-patterns.md.

---

## 1. View Hierarchy

The secbot WebUI keeps the existing nanobot shell (Sidebar / Settings / Theme / i18n) and replaces only the chat surface internals + adds three security-domain top-level views.

```
App shell
├── Sidebar (kept from nanobot)
│   ├── Conversations         (existing)
│   ├── Assets                (NEW — view 1)
│   ├── ScanHistory           (NEW — view 2)
│   ├── Reports               (NEW — view 3)
│   └── Settings              (kept)
│
└── Main pane
    ├── ChatPane              (REWRITTEN with @assistant-ui/react)
    │   ├── PlanTimeline      (top of conversation, see component-patterns §1)
    │   ├── MessageList       (assistant-ui ThreadPrimitive)
    │   │   └── MessageBubble triplet
    │   │       ├── ToolCallCard
    │   │       ├── ScanResultTable
    │   │       └── PlanTimeline (inline echoes)
    │   ├── DestructiveAlertDialog  (mounted globally, opened by ws event)
    │   └── Composer          (assistant-ui ComposerPrimitive)
    │
    ├── AssetsView            (CMDB browser — table-of-assets + asset detail)
    ├── ScanHistoryView       (scans table + per-scan timeline + raw-log links)
    └── ReportsView           (per-scan report list + format export)
```

**Rule of thumb**: any new surface that is NOT in this tree MUST be proposed in a spec PR before code lands. The shell layout is the binding contract.

### 1.1 New view ownership

| View | Data source | Authoritative spec |
|------|-------------|--------------------|
| Sidebar / Settings / i18n | local store / existing routes | (kept; no new spec) |
| ChatPane | WebSocket stream | [../backend/websocket-protocol.md](../backend/websocket-protocol.md) drives events |
| AssetsView | REST `/api/assets` against CMDB | [../backend/cmdb-schema.md §2.1](../backend/cmdb-schema.md#21-asset) |
| ScanHistoryView | REST `/api/scans` + `scan.*` WS events | [../backend/scan-lifecycle.md](../backend/scan-lifecycle.md), [../backend/cmdb-schema.md §2.4](../backend/cmdb-schema.md#24-scan) |
| ReportsView | REST `/api/scans/{id}/reports` | [../backend/report-pipeline.md](../backend/report-pipeline.md) |

---

## 2. Authoritative Sub-Specs

The detailed UI rules live in three specs below. **All four hard rules listed in [../frontend/index.md](./index.md) apply**; this hub does not override them.

| Concern | Spec | What it locks |
|---------|------|----------------|
| Color tokens | [theme-tokens.md](./theme-tokens.md) | Dark base palette, primary = 海蓝 `#1E90FF`, severity 5-tier, `globals.css` contract |
| Chat / tool / destructive UI | [component-patterns.md](./component-patterns.md) | MessageBubble triplet, tool-call folding, AlertDialog destructive structure |
| Charts / graphs | [visualization-libraries.md](./visualization-libraries.md) | `react-flow` + `recharts` whitelist, banned libraries |

When in doubt, the **sub-specs win** over this hub. This hub is map; the sub-specs are law.

---

## 3. assistant-ui Integration Summary

PR8 swaps the legacy ChatPane internals for `@assistant-ui/react` while keeping the shell. The integration approach is locked:

1. Wrap the existing `useNanobotStream` WebSocket adapter with `useExternalStoreRuntime` — see research §3 for the bridging code skeleton.
2. Skill renderers register through `runtime.toolUI[<skill-name>]`. No switch/case in a mega-component (already enforced by [component-patterns.md §1.1](./component-patterns.md#11-registration-contract)).
3. shadcn primitives stay; `npx assistant-ui add` drops Tailwind+Radix sources into `webui/src/components/assistant-ui/` so the existing `@/components/ui/button` path keeps working.
4. i18n: assistant-ui ships English-only — wrap the styled exports in i18next; do NOT fork the upstream package.

Detailed feasibility analysis and risks are in [../../tasks/05-07-cybersec-agent-platform/research/assistant-ui-integration.md](../../tasks/05-07-cybersec-agent-platform/research/assistant-ui-integration.md). That doc is the single source for "why we picked assistant-ui" — do NOT re-litigate the choice in component code comments.

---

## 4. New View — Acceptance Snapshot

These bullets describe the minimum Each new view ships in PR9. They are **not** UI rules (those live in the sub-specs); they are the acceptance shape so a reviewer can sanity-check the implementation.

### 4.1 AssetsView

- Left panel: tree of assets grouped by `kind` (cidr / ip / domain), then by tag.
- Right panel: selected asset detail (services + recent vulnerabilities with severity badges).
- Severity badges MUST consume the `severity-*` Tailwind classes from [theme-tokens.md §3](./theme-tokens.md#3-severity-palette).

### 4.2 ScanHistoryView

- Table columns: scan id, target, status, started_at, finished_at, severity counts.
- Status column uses the labels from [scan-lifecycle.md §1](../backend/scan-lifecycle.md#1-state-machine); no custom status string.
- Click-through opens a per-scan detail with the PlanTimeline replayed and a "View raw logs" link per skill ([context-trimming.md §5](../backend/context-trimming.md#5-webui-hooks)).

### 4.3 ReportsView

- One row per `(scan_id, format)` triple where format ∈ {markdown, docx, pdf}.
- Action buttons: re-render, download. Both call backend skills (`report-markdown` / `report-docx` / `report-pdf` per [report-pipeline.md §5](../backend/report-pipeline.md#5-skill-wiring)).
- No in-page PDF preview in v1 (the research doc rules this out as out-of-scope).

---

## 5. Forbidden in WebUI PRs

These are aggregated from the sub-specs for quick reference. Treat them as a checklist; the canonical ban lives in the linked file.

- Raw hex / rgb in component code → see [theme-tokens.md §5](./theme-tokens.md#5-forbidden).
- Custom modal for destructive flows → see [component-patterns.md §5](./component-patterns.md#5-forbidden).
- Adding a 4th MessageBubble sub-component → see [component-patterns.md §1](./component-patterns.md#1-messagebubble-triplet).
- Importing a chart library not on the whitelist → see [visualization-libraries.md §2](./visualization-libraries.md#2-banned-libraries).
- Branching renderer selection inside a single component → see [component-patterns.md §1.1](./component-patterns.md#11-registration-contract).

---

## 6. Pre-Implementation Workflow

1. Read [index.md](./index.md) → Hard Rules.
2. Pick the relevant sub-spec from §2 above.
3. Map the data flow to the backend contracts in §1.1 (especially [websocket-protocol.md](../backend/websocket-protocol.md) for ChatPane).
4. If anything is unclear, file a spec PR before writing the component — this hub is intentionally thin so the sub-specs stay authoritative.

---

## Related

- [index.md](./index.md) — frontend hard rules and authoring conventions.
- [theme-tokens.md](./theme-tokens.md) — color contract.
- [component-patterns.md](./component-patterns.md) — chat / tool / destructive surfaces.
- [visualization-libraries.md](./visualization-libraries.md) — chart library whitelist.
- [../backend/websocket-protocol.md](../backend/websocket-protocol.md) — events the ChatPane consumes.
- [../backend/scan-lifecycle.md](../backend/scan-lifecycle.md) — states ScanHistoryView renders.
- [../backend/cmdb-schema.md](../backend/cmdb-schema.md) — tables AssetsView and ScanHistoryView read.
- [../backend/report-pipeline.md](../backend/report-pipeline.md) — formats ReportsView exports.
- [../../tasks/05-07-cybersec-agent-platform/research/cybersec-ui-patterns.md](../../tasks/05-07-cybersec-agent-platform/research/cybersec-ui-patterns.md) — design rationale.
- [../../tasks/05-07-cybersec-agent-platform/research/assistant-ui-integration.md](../../tasks/05-07-cybersec-agent-platform/research/assistant-ui-integration.md) — assistant-ui adoption research.
