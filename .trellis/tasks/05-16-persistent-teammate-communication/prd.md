# brainstorm: persistent teammate communication

## Goal

Implement a teammate communication model inspired by the local
`learn-claude-code-main` reference project, while fitting secbot's existing
agent loop. The feature should support two related modes: parent-to-child task
delegation with isolated child context and summary-only return, plus persistent
teammates that communicate asynchronously through file-backed mailboxes and
survive across turns with durable identity/lifecycle state.

## What I already know

* User wants parent Agent to call a task tool to spawn a child agent.
* Child agent must run on an independent `messages[]` context.
* Child agent completion returns only summary text to parent; child message
  history is discarded and must not pollute the parent conversation context.
* User wants persistent teammate communication with `MessageBus` and JSONL
  mailboxes under paths like `.team/inbox/alice.jsonl`.
* Each teammate should have an independent JSONL inbox.
* `send()` appends a message to the target inbox.
* `read_inbox()` reads and clears the inbox with drain-on-read semantics.
* Teammate identity and lifecycle state should persist in `.team/config.json`.
* Teammates should run a full agent loop independently and support
  `spawn -> working -> idle -> working -> ... -> shutdown`.
* Current secbot already has one-shot subagents via `SubagentManager`,
  `delegate_task`, isolated `AgentRunner` runs, in-memory `MessageBus`,
  chat-scoped `Blackboard`, and websocket `agent_event` status events.
* Current secbot does not have `.team/`, file-backed teammate mailboxes,
  persistent teammate roster/config, or teammate lifecycle manager.

## Requirements

* Parent Agent can delegate a task to a child agent through a task/delegation
  tool.
* One-shot child agent uses an isolated message history and returns only a
  concise summary to the parent.
* Child intermediate messages/tool calls are not appended to the parent
  session history.
* Persistent teammates have durable identity/state in `.team/config.json`.
* Persistent teammates have per-name JSONL inboxes under `.team/inbox/`.
* `send()` appends one structured JSONL message to another teammate's inbox.
* `read_inbox()` returns unread messages and clears the mailbox.
* Teammates run independent full agent loops for manually assigned work and
  transition between `working`, `idle`, and `shutdown`.
* MVP lifecycle is manually driven: spawn/assign work starts `working`, loop
  completion returns the teammate to `idle`, explicit shutdown marks
  `shutdown`.
* Teammate mailbox operations are safe for normal single-process concurrent
  use.

## Acceptance Criteria

* [ ] Existing or new one-shot task delegation has a test proving parent
  conversation history receives only child summary/result text, not child
  intermediate history.
* [ ] `.team/inbox/<name>.jsonl` is created per teammate and receives JSONL
  messages via `send()`.
* [ ] `read_inbox()` returns unread messages and clears the mailbox.
* [ ] `.team/config.json` persists teammate identity, role, and lifecycle
  status.
* [ ] A teammate can move through manual `spawn -> working -> idle -> working
  -> shutdown` in a deterministic test without a real network model call.
* [ ] Tests cover mailbox append/drain, config persistence, and lifecycle
  transitions.

## Definition of Done

* Tests added/updated (unit/integration where appropriate).
* Lint / typecheck / CI commands run where available.
* Docs/notes updated if behavior changes.
* Rollout/rollback considered if risky.

## Research References

* [`research/reference-team-model.md`](research/reference-team-model.md) —
  Local reference patterns for isolated subagents, JSONL inboxes, config state,
  protocols, and autonomous teammate lifecycle.
* [`research/current-code.md`](research/current-code.md) — Current secbot
  integration points and implementation implications.

## Research Notes

### Reference project patterns

* `s04_subagent.py` implements disposable child task isolation: child receives
  fresh `messages`, runs tools, returns final text, and child history is
  discarded.
* `s09_agent_teams.py` introduces `.team/config.json` plus
  `.team/inbox/<name>.jsonl`, `send()`, `read_inbox()`, and thread-per-teammate
  loops.
* `s10_team_protocols.py` adds request/response correlation with `request_id`.
* `s11_autonomous_agents.py` adds the requested lifecycle: work, idle polling,
  resume on inbox/task, and shutdown.

### Current secbot constraints

* `SubagentManager` already satisfies most one-shot delegation semantics:
  isolated child messages and summary-only `_announce_result`.
* Current subagents are `asyncio.Task`s, not durable teammates, and status is
  in memory.
* Existing `bus.MessageBus` is an in-memory chat channel queue; the requested
  teammate `MessageBus` should be separate or namespaced to avoid confusing two
  different contracts.
* Current blackboard is in-memory shared state, not drain-on-read mailbox state.
* There is no local `tests/` tree in this checkout, so this task should add
  focused tests for the new components.

## Feasible Approaches

### Approach A: Add A Teammate Subsystem Beside Existing Subagents (Recommended)

How:
* Keep `SubagentManager` for existing one-shot `delegate_task` behavior.
* Add a new file-backed teammate module, likely under `agent/team.py` or
  `agent/teammate.py`, containing a JSONL mailbox bus, config store, and
  teammate lifecycle manager.
* Add explicit tools such as `spawn_teammate`, `send_teammate_message`,
  `read_teammate_inbox`, and possibly `list_teammates`.
* Reuse `AgentRunner` and existing tool registry patterns for teammate loops.

Pros:
* Low regression risk for current scanning/orchestrator workflows.
* Clear separation between one-shot subagents and durable teammates.
* Easier to test mailbox/config/lifecycle without changing current chat bus.

Cons:
* Two related agent concepts exist side by side and need clear naming/docs.

### Approach B: Extend `SubagentManager` Into A Unified Worker Manager

How:
* Add durable mailbox/config/lifecycle concepts directly to `SubagentManager`.
* Treat current subagents as ephemeral workers and teammates as persistent
  workers under the same status/event system.

Pros:
* One place for agent runtime status and websocket events.
* Potentially simpler API exposure later.

Cons:
* Higher regression risk because existing `delegate_task` is central to the
  orchestrator flow.
* More complex manager with two very different lifecycles.

### Approach C: Replace Blackboard Collaboration With JSONL Mailboxes

How:
* Move inter-agent communication from blackboard to per-agent inboxes.

Pros:
* Strong conceptual alignment with the reference project.

Cons:
* Too disruptive for MVP; current expert-agent prompts and UI already rely on
  blackboard semantics.

## Recommended MVP

* Use Approach A.
* Keep one-shot `delegate_task` behavior and add tests documenting the
  summary-only isolation contract.
* Implement the teammate mailbox/config/lifecycle core with deterministic unit
  tests.
* Add minimal tool surface to create/list/message/read teammates.
* Leave automatic idle polling, richer request/response protocols, task-board
  auto-claiming, and WebUI management pages out of MVP.

## Decision (ADR-lite)

**Context**: The reference project includes progressively more advanced team
features: core JSONL mailboxes in `s09`, request/response protocols in `s10`,
and autonomous idle polling/task claiming in `s11`. The user chose option 1:
core communication.

**Decision**: MVP implements the core communication subsystem only: one-shot
task isolation tests, file-backed teammate inboxes, persistent config/status,
manual spawn/list/send/read/shutdown tools, and manually driven lifecycle
transitions.

**Consequences**: The implementation remains small and testable, and avoids
introducing background polling complexity in the first slice. Automatic idle
polling, `.tasks/` scanning, and plan/shutdown request handshakes can be added
later on top of the same mailbox/config primitives.

## Open Questions

* None for MVP scope.

## Out of Scope

* Distributed multi-process locking beyond local single-machine file safety.
* Networked teammate transport.
* Replacing the existing websocket event protocol.
* Replacing the blackboard.
* Full UI redesign for teammate management.
* Rich plan-approval/shutdown handshakes unless selected for MVP.
* Automatic idle polling while a teammate is idle.
* Autonomous task-board auto-claiming.

## Technical Notes

* Current task directory:
  `.trellis/tasks/05-16-persistent-teammate-communication`.
* Reference project:
  `/Users/shan/Downloads/nanobot/learn-claude-code-main`.
* Relevant secbot files:
  `agent/subagent.py`, `agent/tools/spawn.py`, `agent/loop.py`,
  `agent/runner.py`, `bus/queue.py`, `bus/events.py`, `agent/blackboard.py`,
  `agent/tools/blackboard.py`, `channels/websocket.py`,
  `session/manager.py`.
* Research subprocess briefly recreated this task directory after reporting it
  missing, which removed the first draft `prd.md`; task metadata and PRD were
  restored afterward.
