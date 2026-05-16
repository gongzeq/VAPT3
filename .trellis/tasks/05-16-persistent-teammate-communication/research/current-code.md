# Research: Current secbot code for persistent teammate communication

- Query: current secbot agent persistence, subagent loop, control/message schemas, snapshotting, CLI/team commands, and tests relevant to persistent teammate communication
- Scope: internal
- Date: 2026-05-16

## Findings

### Files Found

- `agent/subagent.py` - existing background subagent manager, per-subagent runner setup, status events, result injection, cancellation.
- `agent/tools/spawn.py` - orchestrator-facing `delegate_task` tool that spawns background subagents through `SubagentManager`.
- `agent/runner.py` - shared tool-using ReAct loop, checkpoint callbacks, injection callback support, and final `AgentRunResult`.
- `agent/loop.py` - main session loop, session locks/pending queues, subagent-result injection, runtime checkpoints, durable session save/restore.
- `session/manager.py` - JSONL-backed conversation sessions with metadata line, atomic save, fsync flush, corruption repair.
- `bus/queue.py` and `bus/events.py` - current in-process async chat bus and inbound/outbound dataclass schemas.
- `agent/blackboard.py` and `agent/tools/blackboard.py` - current chat-scoped in-memory inter-agent scratchpad and tools.
- `channels/websocket.py` - REST/WS surfaces for agent registry/status and blackboard snapshots.
- `cli/commands.py` - runtime construction for API/gateway/CLI, wiring `MessageBus`, `SessionManager`, `AgentLoop`, `SubagentManager`, `BlackboardRegistry`.
- `api/agents.py` - alternate helper for aggregating static expert-agent registry plus runtime subagent status.
- `agents/orchestrator.py` - orchestrator prompt text that limits direct tool surface to coordination tools including `delegate_task`.

### Code Patterns

- `SubagentManager` is asyncio-task based, not thread based. It keeps `_running_tasks`, `_task_statuses`, and `_session_tasks` in memory, so current subagent lifecycle is not durable across process restarts (`agent/subagent.py:244`, `agent/subagent.py:246`, `agent/subagent.py:342`).
- `delegate_task` validates concurrency and optional expert-agent identity, then calls `SubagentManager.spawn(...)` with origin channel/chat/session context (`agent/tools/spawn.py:69`, `agent/tools/spawn.py:80`, `agent/tools/spawn.py:94`).
- Existing one-shot subagents already use isolated message history. `_run_subagent` builds a fresh `messages` list containing only the subagent system prompt and task before calling `AgentRunner.run` (`agent/subagent.py:497`, `agent/subagent.py:503`, `agent/subagent.py:515`).
- Subagents intentionally get a filtered tool surface: no message tool, no spawn tool, isolated file state, blackboard tools, optional web tools, and scoped skill tools when an expert-agent spec is provided (`agent/subagent.py:430`, `agent/subagent.py:436`, `agent/subagent.py:445`, `agent/subagent.py:474`).
- Subagent completion is summary-only relative to parent context: `result.final_content` is passed to `_announce_result`; the child `result.messages` are not appended to the parent session (`agent/subagent.py:564`, `agent/subagent.py:566`, `agent/subagent.py:592`).
- `_announce_result` wraps the summary in `agent/subagent_announce.md` and publishes a synthetic `InboundMessage(channel="system", metadata.injected_event="subagent_result")` to the main bus (`agent/subagent.py:606`, `agent/subagent.py:620`, `agent/subagent.py:626`, `agent/subagent.py:635`).
- `AgentLoop` routes new messages for active sessions into per-session pending queues, enabling mid-turn injection rather than competing turns (`agent/loop.py:1047`, `agent/loop.py:1051`, `agent/loop.py:1067`, `agent/loop.py:1098`).
- During `_run_agent_loop`, the injection callback drains pending messages. If no messages are ready but this session still has running subagents, it waits up to 300 seconds for a subagent completion and injects it in-order (`agent/loop.py:862`, `agent/loop.py:899`, `agent/loop.py:906`).
- `AgentRunner` supports injection via `AgentRunSpec.injection_callback`; drained injections are normalized into user messages and appended while preserving role alternation (`agent/runner.py:145`, `agent/runner.py:189`, `agent/runner.py:218`, `agent/runner.py:234`).
- System messages from subagents are processed as assistant-role continuation for the originating session; `_persist_subagent_followup` persists exactly one assistant entry per `subagent_task_id` for durability/dedupe (`agent/loop.py:1263`, `agent/loop.py:1291`, `agent/loop.py:1308`, `agent/loop.py:1631`).
- Conversation sessions are JSONL files in `<workspace>/sessions/<safe_key>.jsonl`; first line is metadata and following lines are messages (`session/manager.py:246`, `session/manager.py:260`, `session/manager.py:310`, `session/manager.py:318`).
- Session saving is atomic via temp file plus `os.replace`; optional `fsync=True` also flushes file and directory for graceful shutdown (`session/manager.py:406`, `session/manager.py:416`, `session/manager.py:420`, `session/manager.py:436`, `session/manager.py:438`).
- Runtime checkpointing persists in-flight assistant/tool state in session metadata and restores interrupted turns before processing the next message (`agent/loop.py:857`, `agent/loop.py:1655`, `agent/loop.py:1682`, `agent/loop.py:1736`).
- Current bus is an in-memory `asyncio.Queue` pair for inbound/outbound chat messages; it is not the requested file-backed teammate mailbox (`bus/queue.py:8`, `bus/queue.py:16`, `bus/queue.py:20`, `bus/queue.py:28`).
- Current message schema is `InboundMessage(channel, sender_id, chat_id, content, timestamp, media, metadata, session_key_override)` and `OutboundMessage(channel, chat_id, content, reply_to, media, metadata, buttons)` (`bus/events.py:8`, `bus/events.py:27`).
- Current blackboard is in-memory and chat-scoped through `BlackboardRegistry`; it retains entries across turns but not process restarts, and does not provide drain-on-read mailbox semantics (`agent/blackboard.py:57`, `agent/blackboard.py:117`, `agent/blackboard.py:125`).
- Agent status events currently report only running/error/idle states derived from active subagent tasks; WebSocket `/api/agents?include_status=true` maps no active task to `idle` and no manager to `offline` (`agent/subagent.py:277`, `agent/subagent.py:373`, `agent/subagent.py:570`, `channels/websocket.py:1405`, `channels/websocket.py:1433`).
- Gateway construction wires the live `SubagentManager` and `BlackboardRegistry` into `ChannelManager`, so new teammate runtime state can follow the same injection path for status/HTTP exposure (`cli/commands.py:856`, `cli/commands.py:860`, `cli/commands.py:864`).
- No existing `.team/` implementation, teammate mailbox, `read_inbox` tool, or persistent `config.json` roster was found under the constrained Python code paths.
- No `tests/` directory or local test files were found in this checkout. Existing Trellis specs still require tests for new agent-registry and blackboard behavior, but those tests are absent locally.

### Implementation Implications

- One-shot child delegation can likely remain in `SubagentManager`: it already satisfies isolated child messages and summary-only parent return. Tests should assert parent session only receives the rendered summary/injected result, not child tool call history.
- Persistent teammates should be a separate manager/module rather than extending current in-memory `MessageBus`, because the requested contract is file-backed JSONL inboxes and durable roster/lifecycle state.
- Reuse `AgentRunner` for teammate loops instead of hand-rolling LLM/tool execution. The teammate manager can build isolated `AgentRunSpec.initial_messages` per teammate and provide teammate-specific tools (`send_message`, `read_inbox`, `idle`, shutdown tools) plus whatever scoped operational tools are allowed.
- Place `.team/` under the configured workspace, aligning with session and scan storage already rooted at `workspace` (`AgentLoop.workspace`, `SessionManager.workspace`, scan dirs under `.secbot/scans`).
- The file-backed mailbox should not reuse `session/manager.py` directly because sessions are whole-file rewrites with metadata and chat-history semantics. It is still a useful pattern for atomic replace, repair, and optional fsync.
- To avoid duplicate/lost teammate messages during concurrent sends/drains, implementation should improve over the reference sample by adding per-inbox locking and atomic drain semantics. A reasonable single-process MVP is an `asyncio.Lock` or `threading.Lock` keyed by normalized teammate name; multi-process durability would need OS locking, which the PRD currently marks out of scope.
- Teammate lifecycle state should be persisted in `config.json`, but live task handles/threads/asyncio tasks remain process-local. On startup, stale `working` members should be reconciled to `idle`, `shutdown`, or a `stale`/`offline` state rather than claiming they are still running.
- Existing `/api/agents?include_status=true` can expose teammate states, but current status enum in the spec is `idle | running | queued | offline`; the PRD wants `working | idle | shutdown`. The implementer should either map `working` to `running` on the existing endpoint or update/spec a teammate-specific endpoint.
- Existing `/team` string appears only in command router comments and the reference project; there is no secbot team command surface yet. New CLI/WebUI commands should be added deliberately rather than assumed present.

## External References

- None. This research is local-source only.

## Related Specs

- `.trellis/tasks/05-16-persistent-teammate-communication/prd.md` - target requirements and acceptance criteria. Note: this task directory was missing at final write time and was recreated only for research output.
- `.trellis/workflow.md` - persistence and research-output requirements.
- `.trellis/spec/backend/architecture.md` - two-layer platform and summary-only context boundary.
- `.trellis/spec/backend/agent-registry-contract.md` - expert-agent registration and summary schema expectations.
- `.trellis/spec/backend/blackboard-registry.md` - existing chat-scoped shared-state contract; useful contrast with requested drain-on-read mailboxes.
- `.trellis/spec/backend/dashboard-aggregation.md` - likely status endpoint expectations; not fully read for this note, but referenced by `channels/websocket.py`.

## Caveats / Not Found

- No active Trellis task was reported by `../.trellis/scripts/task.py current --source`; this note was written to the explicit task directory supplied in the handoff.
- The target task directory existed in the initial file listing but was missing at write time; only its `research/` directory was recreated to satisfy the required persistence path.
- No local `tests/` tree was found, so test recommendations are based on code surfaces rather than existing test patterns.
- No `config.json` teammate roster, `.team/inbox`, `send()`/`read_inbox()` mailbox implementation, or teammate lifecycle manager currently exists in secbot.
- Current subagents are background asyncio tasks within one process. They are not persistent autonomous teammates and do not survive restarts.
