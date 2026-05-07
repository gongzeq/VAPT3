# secbot Spec — Cross-Reference Index

> **Entry point** for everything spec-level about secbot (the cybersec rebrand of nanobot).
> This file is **navigational only** — every section links to the authoritative spec living under `.trellis/spec/backend/`, `.trellis/spec/frontend/`, or `.trellis/spec/guides/`. Do not copy content here; update the canonical doc instead.
> Source: `.trellis/tasks/05-07-cybersec-agent-platform/prd.md` §"Spec 文档集".

---

## 1. Why this index exists

The PRD calls for a 12-doc spec set under `.trellis/spec/secbot/`. By trellis convention the docs live under `backend/`, `frontend/`, and `guides/` (organised by tech layer). This file is the **one place** a reader can land to discover all secbot-relevant specs without grepping the tree.

If you arrived here looking for "the secbot spec", that is this file plus the docs it links.

---

## 2. Map: PRD doc list → actual file

The PRD's 12-doc target maps to the existing tree as follows. Items marked **(here)** were added to fill a gap; everything else was already in place.

| PRD doc | Authoritative file |
|---------|--------------------|
| `index.md` | **this file** (here) |
| `architecture.md` | [../backend/architecture.md](../backend/architecture.md) |
| `agent-registry-contract.md` | [../backend/agent-registry-contract.md](../backend/agent-registry-contract.md) |
| `skill-contract.md` | [../backend/skill-contract.md](../backend/skill-contract.md) |
| `orchestrator-prompt.md` | [../backend/orchestrator-prompt.md](../backend/orchestrator-prompt.md) |
| `tool-invocation-safety.md` | [../backend/tool-invocation-safety.md](../backend/tool-invocation-safety.md) |
| `high-risk-confirmation.md` | [../backend/high-risk-confirmation.md](../backend/high-risk-confirmation.md) |
| `context-trimming.md` | [../backend/context-trimming.md](../backend/context-trimming.md) |
| `cmdb-schema.md` | [../backend/cmdb-schema.md](../backend/cmdb-schema.md) |
| `report-formats.md` | [../backend/report-pipeline.md](../backend/report-pipeline.md) (renamed; covers MD / DOCX / PDF pipelines) |
| `webui-design.md` | [../frontend/webui-design.md](../frontend/webui-design.md) (here, navigational hub) |
| `removed-im-channels.md` | [../backend/removed-im-channels.md](../backend/removed-im-channels.md) (here) |

**Naming note**: `report-pipeline.md` is the chosen name — "pipeline" is more accurate than "formats" because the doc covers the full Markdown→DOCX/PDF render chain, not just template files. The PRD predates this rename; treat the two names as synonyms.

---

## 3. By Concern

### 3.1 Architecture & Boundaries

| Spec | What it locks |
|------|---------------|
| [../backend/architecture.md](../backend/architecture.md) | Two-layer Orchestrator → Expert → Skill topology, layer MUST-NOTs, surface list |
| [../backend/removed-im-channels.md](../backend/removed-im-channels.md) | Anti-rollback manifest for the 13 deleted IM channels + bridge |
| [../guides/cross-layer-thinking-guide.md](../guides/cross-layer-thinking-guide.md) | How to reason about boundaries before writing cross-layer features |

### 3.2 Agents & Skills

| Spec | What it locks |
|------|---------------|
| [../backend/agent-registry-contract.md](../backend/agent-registry-contract.md) | Expert agent YAML schema, registration flow, scoped_skills rule |
| [../backend/skill-contract.md](../backend/skill-contract.md) | SKILL.md front-matter, `handler.run()` signature, output schemas |
| [../backend/orchestrator-prompt.md](../backend/orchestrator-prompt.md) | Top-level system prompt skeleton, multi-turn routing strategy |
| [../backend/tool-invocation-safety.md](../backend/tool-invocation-safety.md) | Single sandbox entry point, binary whitelist, no shell |
| [../backend/high-risk-confirmation.md](../backend/high-risk-confirmation.md) | `risk_level` enum, blocking `ask_user` contract |

### 3.3 Lifecycle & Persistence

| Spec | What it locks |
|------|---------------|
| [../backend/scan-lifecycle.md](../backend/scan-lifecycle.md) | Scan state machine, bus events, cancellation semantics |
| [../backend/cmdb-schema.md](../backend/cmdb-schema.md) | SQLite tables, `actor_id` reservation, migration policy |
| [../backend/context-trimming.md](../backend/context-trimming.md) | summary_json budgets vs raw_log_path, autocompact policy |
| [../backend/report-pipeline.md](../backend/report-pipeline.md) | Markdown-canonical render path, DOCX / PDF skills |

### 3.4 WebUI

| Spec | What it locks |
|------|---------------|
| [../frontend/webui-design.md](../frontend/webui-design.md) | View hierarchy + assistant-ui integration overview |
| [../frontend/theme-tokens.md](../frontend/theme-tokens.md) | Dark theme tokens, primary = 海蓝, severity palette |
| [../frontend/component-patterns.md](../frontend/component-patterns.md) | MessageBubble triplet, destructive AlertDialog |
| [../frontend/visualization-libraries.md](../frontend/visualization-libraries.md) | react-flow + recharts whitelist |
| [../backend/websocket-protocol.md](../backend/websocket-protocol.md) | Wire envelope, server↔client event catalog |

### 3.5 Quality & Cross-Cutting

| Spec | What it locks |
|------|---------------|
| [../backend/index.md](../backend/index.md) | Backend guideline index |
| [../backend/quality-guidelines.md](../backend/quality-guidelines.md) | Code quality bar (placeholder; project-specific to fill) |
| [../backend/error-handling.md](../backend/error-handling.md) | Error type / propagation policy (placeholder) |
| [../backend/logging-guidelines.md](../backend/logging-guidelines.md) | Structured logging, what NOT to log (placeholder) |
| [../backend/database-guidelines.md](../backend/database-guidelines.md) | DB query patterns, migrations (placeholder) |
| [../backend/directory-structure.md](../backend/directory-structure.md) | Module layout (placeholder) |
| [../guides/code-reuse-thinking-guide.md](../guides/code-reuse-thinking-guide.md) | Pre-modification "search first" rule |
| [../frontend/index.md](../frontend/index.md) | Frontend hard rules + pre-implementation checklist |

> The five "(placeholder)" backend guideline files are inherited from the trellis template. They are out of scope for the cybersec-platform task; fill incrementally as the codebase matures.

---

## 4. ADR Index

The PRD captures decision history inline (ADR-lite). For convenience:

| ADR | Topic | Where it lives |
|-----|-------|----------------|
| ADR-001 | OpenClaw tool-calling loop | [../../tasks/05-07-cybersec-agent-platform/prd.md](../../tasks/05-07-cybersec-agent-platform/prd.md) §Decision |
| ADR-002 | Two-layer agent topology | same |
| ADR-003 | Function-grain skill packaging | same |
| ADR-004 | WebUI = nanobot shell + assistant-ui | same |
| ADR-005 | Local single-user auth | same |
| ADR-006 | Project rename to secbot | same |

A future ADR that overturns any of these MUST update both the PRD AND the relevant spec doc(s) in the same PR.

---

## 5. Research Backing

The specs cite three research outputs as their rationale source. Read them before proposing changes to the corresponding spec.

| Research | Specs it backs |
|----------|----------------|
| [../../tasks/05-07-cybersec-agent-platform/research/assistant-ui-integration.md](../../tasks/05-07-cybersec-agent-platform/research/assistant-ui-integration.md) | webui-design, component-patterns |
| [../../tasks/05-07-cybersec-agent-platform/research/security-tool-functions.md](../../tasks/05-07-cybersec-agent-platform/research/security-tool-functions.md) | skill-contract, tool-invocation-safety, high-risk-confirmation |
| [../../tasks/05-07-cybersec-agent-platform/research/cybersec-ui-patterns.md](../../tasks/05-07-cybersec-agent-platform/research/cybersec-ui-patterns.md) | theme-tokens, component-patterns, visualization-libraries, webui-design |

---

## 6. How to Update

- **Adding a new spec**: place it under `backend/` or `frontend/` per its tech layer; add a row to §3 here. Do NOT create a new top-level directory unless the layer doesn't fit either bucket.
- **Updating an existing spec**: edit the canonical file. This index needs no change unless the spec moves or a heading changes.
- **Renaming a spec**: update §2 (PRD doc → file map) AND every backreference in the rest of the spec tree (`grep -r "<old-name>" .trellis/`).

---

## Related

- [../backend/index.md](../backend/index.md) — backend spec index.
- [../frontend/index.md](../frontend/index.md) — frontend spec index.
- [../guides/index.md](../guides/index.md) — thinking-guide index.
- [../../tasks/05-07-cybersec-agent-platform/prd.md](../../tasks/05-07-cybersec-agent-platform/prd.md) — the PRD this spec set serves.
