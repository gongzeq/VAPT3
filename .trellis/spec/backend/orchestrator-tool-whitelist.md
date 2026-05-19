# Orchestrator Tool Whitelist

> Contract for the top-level orchestrator tool surface.

## Decision

The main `AgentLoop` is an orchestrator by default. Its registered tool surface
MUST contain exactly:

- `create_agent`
- `read_blackboard`
- `write_plan`
- `request_approval`

Operational tools such as file access, shell execution, web tools, skills,
blackboard writes, `message`, `ask_user`, cron, MCP, and `my` MUST NOT be
registered on the orchestrator loop. Work requiring those capabilities is
delegated to a subagent via `create_agent`.

`create_agent` is the **only** entry point for spawning expert subagents (see
`05-18-subagent-prompt-minimal-create-agent/prd.md` decisions D2 / D6). Per-
agent tools (one tool per yaml) are no longer exposed; instead `create_agent`
takes:

- `name` (required) — the registered expert agent name; unknown names are
  rejected fail-fast.
- `task` (required) — the FULL prompt body the subagent will see. The
  orchestrator owns prompt composition; the subagent does NOT read
  `spec.system_prompt`. Bounded by `MAX_TASK_LEN` (currently 16K chars).
- `target` (required) — asset / scope identifier (IP / CIDR / domain / URL).
  Routing & audit only; not auto-injected into the LLM prompt.
- `endpoint_url`, `endpoint_param` (required iff the resolved spec has
  `endpoint_bound: true`) — drive the endpoint-level mutual exclusion enforced
  by `SubagentManager`.

## Subagent Surface

Subagents MUST NOT receive `create_agent`; recursive orchestration is outside
the two-layer architecture. Subagents retain operational tools, scoped skills,
`ask_user`, `blackboard_write`, and `read_blackboard` so they can perform the
actual resource access and share findings. The orchestrator-side blackboard
snapshot is **not** auto-injected into the subagent system prompt anymore
(decision D3); the orchestrator embeds whatever excerpt it considers relevant
into `task` directly.

## Interactive Approval

`request_approval` is the orchestrator-level blocking approval tool. It reuses
the `AskUserInterrupt` pause/resume mechanism, but the tool name remains
`request_approval` in persisted tool-call history so clients can render a
distinct approval card. When no options are supplied, it defaults to
`Approve` / `Deny`.

## Plan Events

`write_plan` publishes an `agent_event` with `type: "orchestrator_plan"` and a
payload containing `agent: "orchestrator"`, `steps`, and `timestamp`. This event
is display-only; it does not schedule or execute any work.

## Test Hooks

- Main-loop tests assert the exact four-tool whitelist (with `create_agent` in
  place of the legacy `delegate_task`).
- Subagent registration tests assert `create_agent` is absent while operational
  tools and blackboard tools remain present.
- Runner tests cover both `ask_user` and `request_approval` as blocking tools.
- Frontend stream tests cover `orchestrator_plan` and approval prompt metadata.
- `create_agent` validation tests cover unknown-name rejection, missing
  `target`, missing endpoint fields on endpoint-bound agents, `task` length
  ceiling, and endpoint-level mutual exclusion.
