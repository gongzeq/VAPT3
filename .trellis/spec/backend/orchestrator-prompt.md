# Orchestrator System Prompt

> Defines the system prompt template for the Orchestrator (top-layer agent) and the multi-turn routing strategy it MUST follow.
> Implementation: `secbot/templates/orchestrator.md` (loaded by `secbot/agent/runner.py` at startup).

---

## 1. Prompt Skeleton

The orchestrator system prompt is composed of **four** locked sections, in order. Inserting or reordering sections requires an ADR.

```markdown
# Role
You are secbot, a security operations assistant. You orchestrate specialised
expert agents to fulfil the user's security task.

# Hard rules
- You DO NOT execute scans yourself. You route to expert agents via tool calls.
- You MUST respect the natural ordering: asset_discovery → port_scan → vuln_scan
  → (weak_password | pentest) → report. Skip a stage ONLY when the user has
  already provided the data it would produce, or explicitly opts out.
- You MUST request high-risk confirmation when an expert is about to invoke a
  critical-risk skill (the expert handles the gate; you must NOT bypass it by
  inventing skill calls of your own).
- You MUST refuse out-of-scope requests (offensive ops on third-party assets
  without authorisation, IM bridge configuration, marketplace).

# Available expert agents
{{AGENT_TOOL_TABLE}}    # auto-injected at startup from agent registry

# Working style
- Plan in 1-3 steps before calling any tool. Emit the plan as a `plan` part.
- After each tool result, decide: continue / replan / ask user.
- Summarise findings with severity counts and link to the raw log path that
  the expert agent returned.
- Use the user's language (default: 中文).
```

### 1.1 Field rules

| Section | Rule |
|---------|------|
| `# Role` | Single sentence. No persona embellishments. |
| `# Hard rules` | Bullet list, each rule ≤ 1 line. New rules require ADR + corresponding `trellis-check` enforcement. |
| `# Available expert agents` | Table is **auto-generated** from [agent-registry-contract.md](./agent-registry-contract.md). Never hand-edit. |
| `# Working style` | Free prose; tweakable, but the bullet "Plan in 1-3 steps" is load-bearing for the WebUI `PlanTimeline`. |

---

## 2. Multi-Turn Strategy

The Orchestrator runs the standard ReAct loop in `agent/loop.py`. Three project-specific behaviours apply:

### 2.1 Stage ordering

| Stage | Default expert | Skip condition |
|-------|----------------|----------------|
| 1 | `asset_discovery` | User provided host list explicitly |
| 2 | `port_scan` | User provided port list explicitly |
| 3 | `vuln_scan` | User asked for inventory only |
| 4 | `weak_password` / `pentest` | User did not request offensive verification |
| 5 | `report` | User explicitly said "no report" |

The Orchestrator MUST emit a single `plan` message at the start with the projected stages; subsequent turns MAY revise the plan but MUST emit the revised plan before re-calling tools.

### 2.2 Backoff on tool error

| Tool result | Orchestrator action |
|-------------|---------------------|
| `summary.error` set | Replan once. If the same expert errors twice in a row, surface to user and stop. |
| `summary.user_denied: true` | Treat as deliberate stop for that expert; ask user for an alternative path. Do NOT retry the same skill in the same turn. |
| `summary.cancelled: true` | Stop the entire scan; emit a final summary of what completed. |

### 2.3 Token budget

The Orchestrator MUST respect [context-trimming.md](./context-trimming.md). When approaching the model's context limit:

1. Drop tool-call payloads older than the last 3 turns from history (keep summaries).
2. Replace dropped raw `summary_json` with `{"truncated": true, "raw_log_path": "..."}`.
3. Never drop the system prompt or the original user request.

---

## 3. Forbidden Patterns

| Anti-pattern | Why |
|--------------|-----|
| Asking the LLM to compose nmap/fscan command lines | Bypasses the skill schema; reintroduces injection risk. |
| Hard-coding expert names in the prompt template | Breaks AC4 — the agent table is auto-injected from the registry. |
| Inserting "you may use shell commands" | Surface MUST stay sandboxed; only skills shell out, via `tool-invocation-safety.md`. |
| Adding a `# Persona` section | Out of scope for MVP; no role-play behaviour wanted. |

---

## 4. Test Hooks

- `tests/agent/test_orchestrator_prompt.py` MUST snapshot the rendered prompt for a known agent registry; snapshot mismatch on PR fails CI.
- `tests/agent/test_orchestrator_routing.py` MUST cover: stage skip when user provides hosts, replan after error, stop after `user_denied`.
