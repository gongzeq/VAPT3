# Orchestrator Tool Whitelist

> Contract for the top-level orchestrator tool surface.

## Decision

The main `AgentLoop` is an orchestrator by default. Its registered tool surface
MUST contain exactly:

- `delegate_task`
- `read_blackboard`
- `write_plan`
- `request_approval`

Operational tools such as file access, shell execution, web tools, skills,
blackboard writes, `message`, `ask_user`, cron, MCP, and `my` MUST NOT be
registered on the orchestrator loop. Work requiring those capabilities is
delegated to a subagent with `delegate_task`.

## Subagent Surface

Subagents MUST NOT receive `delegate_task`; recursive orchestration is outside
the two-layer architecture. Subagents retain operational tools, scoped skills,
`ask_user`, `blackboard_write`, and `read_blackboard` so they can perform the
actual resource access and share findings.

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

- Main-loop tests assert the exact four-tool whitelist.
- Subagent registration tests assert `delegate_task` is absent while operational
  tools and blackboard tools remain present.
- Runner tests cover both `ask_user` and `request_approval` as blocking tools.
- Frontend stream tests cover `orchestrator_plan` and approval prompt metadata.
