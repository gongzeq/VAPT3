# Architecture: Two-Layer Agent Platform

> Authoritative architecture contract for `vapt3/` (formerly `nanobot/`).
> Source: `.trellis/tasks/05-07-cybersec-agent-platform/prd.md` §"Architecture Snapshot" + ADR-001/002/003.

---

## 1. Layering

`vapt3` is a **two-layer** agent system. There is no third orchestration layer; there are no peer Orchestrators.

```
Surface (WebUI / CLI / OpenAI-compat HTTP / Python SDK)
        │
        ▼
Orchestrator  (LLM, ReAct loop, tools = expert agents)
        │  tool_call(expert_name, args)
        ▼
Expert Agent  (LLM, ReAct loop, tools = scoped skills)
        │  tool_call(skill_name, args)
        ▼
Skill         (Python module, may shell out via subprocess)
        │
        ▼
External binary (nmap / fscan / nuclei / hydra / masscan / weasyprint / python-docx)
```

| Layer | Implementation | Owns |
|-------|----------------|------|
| Surface | `vapt3/api/`, `vapt3/channels/websocket.py`, `vapt3/cli/` | Transport, auth, streaming |
| Orchestrator | `vapt3/agent/loop.py` + `vapt3/agent/runner.py` | Intent parsing, expert routing, plan timeline |
| Expert Agent | `vapt3/agent/subagent.py` + per-agent YAML under `vapt3/agents/` | Domain reasoning, skill selection |
| Skill | `vapt3/skills/<name>/SKILL.md` + `scripts/` | Single capability, summary JSON, raw log |
| Persistence | SQLite at `~/.vapt3/db.sqlite` | CMDB, scan history, findings, raw log refs |

---

## 2. Data Flow Contract

### 2.1 Request path (user → skill)

1. Surface receives chat input → forwards to Orchestrator via existing WS / HTTP channel.
2. Orchestrator runs ReAct loop (`agent/loop.py`); each tool call resolves to an expert agent.
3. Expert agent runs its own ReAct loop with **only its scoped skill subset** in the tool registry.
4. Skill executes (may call `subprocess`); returns `(summary_json, raw_log_path)`.
5. `summary_json` is fed back into the expert agent's context; `raw_log_path` is stored to SQLite `raw_logs`.

### 2.2 Response path (skill → user)

1. Expert agent returns its final message + tool-call trace to Orchestrator.
2. Orchestrator may invoke another expert (e.g. asset_discovery → port_scan → vuln_scan).
3. Final assistant message + structured `tool_result` events stream to Surface.
4. WebUI renders per [frontend/component-patterns.md §1 MessageBubble Triplet](../frontend/component-patterns.md).

### 2.3 Persistence boundary

- **Inside LLM context**: `summary_json` only. Truncation rules in [context-trimming.md](./context-trimming.md).
- **On disk only**: full subprocess stdout/stderr, raw scan files. Path written to SQLite `raw_logs.path`.
- **Surfaced to UI**: assets / scans / findings tables + clickable raw-log link.

---

## 3. Boundaries (what each layer MUST NOT do)

| Layer | MUST NOT |
|-------|----------|
| Orchestrator | Call a skill directly. Skip an expert agent. Persist scan data. |
| Expert Agent | Invoke another expert agent. Hold cross-domain skills. Talk to Surface. |
| Skill | Call an LLM. Read another skill's raw log. Mutate CMDB outside its declared writes. |
| Surface | Decide routing. Execute skills inline. Bypass `risk_level` gate. |

Violations are review-blocking. Use `trellis-check` to enforce.

---

## 4. Reusable Assets (DO NOT rewrite)

These nanobot modules are kept as-is (renamed only) and form the architectural backbone:

| Module | Reused for |
|--------|------------|
| `agent/loop.py` (1415 lines) | Orchestrator + Expert ReAct loop |
| `agent/subagent.py` (359 lines) | Expert agent instantiation |
| `agent/tools/registry.py` | Skill registration (per agent scope) |
| `agent/tools/ask.py` | High-risk confirmation gate (see [high-risk-confirmation.md](./high-risk-confirmation.md)) |
| `agent/tools/sandbox.py` | Skill subprocess sandboxing (see [tool-invocation-safety.md](./tool-invocation-safety.md)) |
| `skills/` directory contract | Skill packaging (see [skill-contract.md](./skill-contract.md)) |
| `channels/{base,manager,registry,websocket}.py` | Surface transport |

Adding a new layer or replacing any of the above requires an ADR.

---

## 5. Cross-Layer Concerns Index

| Concern | Spec |
|---------|------|
| Expert agent definition | [agent-registry-contract.md](./agent-registry-contract.md) |
| Skill packaging | [skill-contract.md](./skill-contract.md) |
| Orchestrator prompt | [orchestrator-prompt.md](./orchestrator-prompt.md) |
| High-risk gating | [high-risk-confirmation.md](./high-risk-confirmation.md) |
| Subprocess safety | [tool-invocation-safety.md](./tool-invocation-safety.md) |
| Context size | [context-trimming.md](./context-trimming.md) |
| Persistence schema | [cmdb-schema.md](./cmdb-schema.md) |
| Reports | [report-formats.md](./report-formats.md) |
| Removed IM channels | [removed-im-channels.md](./removed-im-channels.md) |
| WebUI integration | [../frontend/webui-design.md](../frontend/webui-design.md) |
