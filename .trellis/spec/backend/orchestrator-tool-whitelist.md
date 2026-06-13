# Orchestrator Tool Whitelist

> Contract for the top-level Orchestrator tool surface.

## Decision

The main `AgentLoop` runs as an Orchestrator by default. Its registered tool
surface MUST contain exactly:

- `create_agent`
- `check_subagents`
- `wait_subagent`
- `read_blackboard`
- `read_assets`
- `read_file`
- `write_plan`
- `request_approval`
- `message`

Operational tools such as shell execution, write/edit/list filesystem tools,
search tools, web/curl tools, skills, blackboard writes, `ask_user`, cron, MCP,
`my`, and notebook tools MUST NOT be registered on the Orchestrator loop. Work
requiring those capabilities is delegated to a subagent via `create_agent`.

`read_file` on the Orchestrator is read-only and jailed to `.secbot/` so the
Orchestrator can inspect persisted scan/tool artifacts announced by subagents.
It MUST NOT provide arbitrary workspace or absolute-path access.

## `create_agent`

`create_agent` is the **only** entry point for spawning expert subagents (see
`05-18-subagent-prompt-minimal-create-agent/prd.md` decisions D2 / D6). Per-
agent tools (one tool per YAML) are no longer exposed; instead `create_agent`
takes:

- `name` (required): registered expert agent name. Unknown names are rejected
  fail-fast.
- `task` (required): the Orchestrator-authored concrete task body. Runtime
  prepends the selected expert's project-authored execution contract from
  `spec.system_prompt` to the subagent's initial user message. The
  Orchestrator must still include scope, relevant findings, constraints, and
  expected output. Bounded by `MAX_TASK_LEN` (currently 16K chars).
- `target` (required): asset/scope identifier (IP, CIDR, domain, URL, etc.).
  Routing and audit only; not auto-injected into the LLM prompt.
- `endpoint_url`, `endpoint_param`: required iff the resolved spec has
  `endpoint_bound: true`; these drive endpoint-level mutual exclusion enforced
  by `SubagentManager`.

## Lifecycle Tools

`check_subagents` returns running and recently terminal expert-agent snapshots
for the current session. `wait_subagent` blocks until one or all selected
subagents reach a terminal state or a bounded timeout expires.

The Orchestrator MUST use these lifecycle tools for completion decisions. It
MUST NOT poll `read_assets` to infer whether a subagent has finished.

## Shared-State Read Tools

`read_blackboard` reads aggregated findings and milestones. `read_assets` reads
structured asset deltas after expert work has produced entries. They are
read-only on the Orchestrator.

The Orchestrator decides what excerpts from these tools matter and embeds only
the relevant summary into `create_agent.task`.

## Subagent Surface

Subagents MUST NOT receive `create_agent`; recursive orchestration is outside
the two-layer architecture. Normal subagents retain operational tools, scoped
skills, `ask_user`, `blackboard_write`, and `read_blackboard` so they can
perform resource access and share findings. `minimal_tools` subagents receive
only their scoped SkillTools.

The Orchestrator-side blackboard snapshot is not auto-injected into the
subagent prompt. The trusted expert execution contract is prepended to the user
message, and the Orchestrator embeds whatever runtime excerpt it considers
relevant into `task` directly.

## Interactive Approval

`request_approval` is the Orchestrator-level blocking approval tool. It reuses
the `AskUserInterrupt` pause/resume mechanism, but the tool name remains
`request_approval` in persisted tool-call history so clients can render a
distinct approval card. When no options are supplied, it defaults to `Approve`
/ `Deny`.

## Plan and Message Events

`write_plan` publishes an `agent_event` with `type: "orchestrator_plan"` and a
payload containing `agent: "orchestrator"`, `steps`, and `timestamp`. This event
is display-only; it does not schedule or execute work.

`message` is the Orchestrator's user-facing notification tool. It may send
progress or final user-visible content, but it does not replace lifecycle
waiting, report generation, or the final answer contract.

## Test Hooks

- Main-loop tests assert the exact nine-tool whitelist above.
- Subagent registration tests assert `create_agent` is absent while operational
  tools and scoped skills remain present according to `minimal_tools`.
- Runner tests cover both `ask_user` and `request_approval` as blocking tools.
- Frontend stream tests cover `orchestrator_plan` and approval prompt metadata.
- `create_agent` validation tests cover unknown-name rejection, missing
  `target`, missing endpoint fields on endpoint-bound agents, task length
  ceiling, and endpoint-level mutual exclusion.
