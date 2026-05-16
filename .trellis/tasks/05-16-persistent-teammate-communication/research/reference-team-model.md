# Research: Reference project team model

- Query: local `learn-claude-code-main` reference implementation for isolated subagent messages, summary-only task returns, file-backed JSONL inboxes, send/read_inbox drain semantics, config.json identity/state, and teammate lifecycle
- Scope: internal
- Date: 2026-05-16

## Findings

### Files Found

- `/Users/shan/Downloads/nanobot/learn-claude-code-main/agents/s04_subagent.py` - disposable child subagent with fresh `messages` and summary-only return.
- `/Users/shan/Downloads/nanobot/learn-claude-code-main/agents/s07_task_system.py` - persistent `.tasks/task_<id>.json` task board pattern.
- `/Users/shan/Downloads/nanobot/learn-claude-code-main/agents/s09_agent_teams.py` - first persistent teammate model with `.team/config.json`, `.team/inbox/<name>.jsonl`, thread-per-agent loops, `send_message`, `read_inbox`, and `/team`/`/inbox` CLI commands.
- `/Users/shan/Downloads/nanobot/learn-claude-code-main/agents/s10_team_protocols.py` - request/response protocols for shutdown and plan approval using `request_id` correlation.
- `/Users/shan/Downloads/nanobot/learn-claude-code-main/agents/s11_autonomous_agents.py` - autonomous teammate loop with WORK/IDLE phases, idle polling, task claiming, identity reinjection, and idle-timeout shutdown.
- `/Users/shan/Downloads/nanobot/learn-claude-code-main/docs/en/s04-subagent.md` - documentation of fresh child context and summary-only parent return.
- `/Users/shan/Downloads/nanobot/learn-claude-code-main/docs/en/s09-agent-teams.md` - documentation of persistent teammate lifecycle and JSONL mailbox contract.
- `/Users/shan/Downloads/nanobot/learn-claude-code-main/docs/en/s10-team-protocols.md` - protocol rationale for shutdown and plan approval.
- `/Users/shan/Downloads/nanobot/learn-claude-code-main/docs/en/s11-autonomous-agents.md` - documentation of idle polling, auto-claiming, identity reinjection, and shutdown timeout.
- Matching Chinese docs exist under `docs/zh/` for s04, s09, s10, and s11 with the same concepts.

### Code Patterns

### Isolated child messages and summary-only return

- `s04_subagent.py` explains the core model: parent keeps `messages=[...]`; subagent starts with `messages=[]`; parent receives only a summary and child context is discarded (`s04_subagent.py:6`, `s04_subagent.py:17`, `s04_subagent.py:20`).
- The child `run_subagent(prompt)` creates `sub_messages = [{"role": "user", "content": prompt}]`, loops through tool calls with `CHILD_TOOLS`, and returns only final text (`s04_subagent.py:118`, `s04_subagent.py:119`, `s04_subagent.py:121`, `s04_subagent.py:136`).
- Parent handles the `task` tool by calling `run_subagent(prompt)` and appending its output as a normal tool result, not child history (`s04_subagent.py:156`, `s04_subagent.py:158`, `s04_subagent.py:162`, `s04_subagent.py:167`).
- The docs state the same contract: subagent starts with `messages=[]`; only final text returns; child message history is discarded (`docs/en/s04-subagent.md:45`, `docs/en/s04-subagent.md:74`).

### File-backed persistent task/state pattern

- `s07_task_system.py` persists tasks as JSON files in `.tasks/`, demonstrating the reference's "state outside the conversation" pattern (`s07_task_system.py:6`, `s07_task_system.py:41`, `s07_task_system.py:46`).
- `TaskManager._save` writes a single task JSON file, and `_load` reads it back by ID (`s07_task_system.py:57`, `s07_task_system.py:63`).
- Task status values are simple strings (`pending`, `in_progress`, `completed`) and dependency clearing is done by scanning files (`s07_task_system.py:79`, `s07_task_system.py:95`).

### JSONL mailboxes and drain-on-read semantics

- `s09_agent_teams.py` sets `TEAM_DIR = WORKDIR / ".team"` and `INBOX_DIR = TEAM_DIR / "inbox"` (`s09_agent_teams.py:63`, `s09_agent_teams.py:64`).
- `MessageBus.__init__` ensures the inbox directory exists (`s09_agent_teams.py:78`, `s09_agent_teams.py:81`).
- `send(sender, to, content, msg_type, extra)` validates message type, builds a JSON object with `type`, `from`, `content`, and `timestamp`, merges `extra`, and appends one JSON line to `<to>.jsonl` (`s09_agent_teams.py:83`, `s09_agent_teams.py:85`, `s09_agent_teams.py:87`, `s09_agent_teams.py:95`, `s09_agent_teams.py:96`).
- `read_inbox(name)` reads all lines from `<name>.jsonl`, parses non-empty lines as JSON, then truncates the file with `write_text("")` before returning the list (`s09_agent_teams.py:100`, `s09_agent_teams.py:105`, `s09_agent_teams.py:108`).
- `broadcast` iterates over teammates and calls `send(..., msg_type="broadcast")` for all except sender (`s09_agent_teams.py:111`, `s09_agent_teams.py:115`).
- `s10_team_protocols.py` and `s11_autonomous_agents.py` repeat the same mailbox implementation pattern (`s10_team_protocols.py:87`, `s10_team_protocols.py:93`, `s10_team_protocols.py:110`, `s11_autonomous_agents.py:80`, `s11_autonomous_agents.py:86`, `s11_autonomous_agents.py:103`).
- The docs explicitly define `.team/inbox/alice.jsonl` as append-only and drain-on-read (`docs/en/s09-agent-teams.md:21`, `docs/en/s09-agent-teams.md:25`, `docs/en/s09-agent-teams.md:66`, `docs/en/s09-agent-teams.md:78`).

### config.json identity/state

- `TeammateManager` owns `.team/config.json`; on initialization it loads existing config or creates `{"team_name": "default", "members": []}` (`s09_agent_teams.py:123`, `s09_agent_teams.py:128`, `s09_agent_teams.py:132`, `s09_agent_teams.py:135`).
- `spawn(name, role, prompt)` either reuses an idle/shutdown member or appends a new member with `name`, `role`, and `status="working"`, then saves config before starting the thread (`s09_agent_teams.py:146`, `s09_agent_teams.py:149`, `s09_agent_teams.py:154`, `s09_agent_teams.py:156`, `s09_agent_teams.py:157`).
- On loop exit, `s09` marks non-shutdown members `idle` and saves config (`s09_agent_teams.py:201`, `s09_agent_teams.py:203`, `s09_agent_teams.py:204`).
- `s11` factors status updates through `_set_status`, saving `config.json` on every lifecycle transition (`s11_autonomous_agents.py:190`, `s11_autonomous_agents.py:193`, `s11_autonomous_agents.py:194`).
- The docs describe `config.json` as the team roster and statuses (`docs/en/s09-agent-teams.md:21`, `docs/en/s09-agent-teams.md:23`, `docs/en/s09-agent-teams.md:40`).

### Thread-per-teammate lifecycle

- `s09` creates a daemon `threading.Thread(target=self._teammate_loop, args=(name, role, prompt))` per teammate and stores it in `self.threads[name]` (`s09_agent_teams.py:157`, `s09_agent_teams.py:162`, `s09_agent_teams.py:163`).
- `s09` teammate loops check inbox before each LLM call and inject each message into their local `messages` history as user JSON (`s09_agent_teams.py:171`, `s09_agent_teams.py:173`, `s09_agent_teams.py:174`, `s09_agent_teams.py:176`).
- `s09` lead loop also drains the lead inbox before each LLM call and wraps it in `<inbox>...</inbox>` (`s09_agent_teams.py:345`, `s09_agent_teams.py:347`, `s09_agent_teams.py:349`).
- `s11` implements the full requested lifecycle: WORK loop, then IDLE polling, then resume WORK on inbox/task or mark shutdown after timeout (`s11_autonomous_agents.py:225`, `s11_autonomous_agents.py:267`, `s11_autonomous_agents.py:300`, `s11_autonomous_agents.py:303`).
- IDLE polling sleeps `POLL_INTERVAL`, drains inbox, resumes on message, scans `.tasks` for pending/unowned/unblocked tasks, claims one, and resumes (`s11_autonomous_agents.py:270`, `s11_autonomous_agents.py:272`, `s11_autonomous_agents.py:273`, `s11_autonomous_agents.py:282`, `s11_autonomous_agents.py:285`).
- Shutdown requests are recognized during work and idle phases; `s11` immediately sets status `shutdown` and returns (`s11_autonomous_agents.py:228`, `s11_autonomous_agents.py:230`, `s11_autonomous_agents.py:231`, `s11_autonomous_agents.py:273`, `s11_autonomous_agents.py:276`).
- The docs summarize the lifecycle as `spawn -> WORKING -> IDLE -> WORKING -> ... -> SHUTDOWN` and show IDLE polling every 5 seconds for up to 60 seconds (`docs/en/s09-agent-teams.md:17`, `docs/en/s09-agent-teams.md:19`, `docs/en/s11-autonomous-agents.md:20`, `docs/en/s11-autonomous-agents.md:34`, `docs/en/s11-autonomous-agents.md:41`).

### Protocols

- `s10` adds `shutdown_requests` and `plan_requests` dictionaries protected by `_tracker_lock` for request correlation (`s10_team_protocols.py:81`, `s10_team_protocols.py:84`).
- Teammate `shutdown_response` updates the shutdown tracker and sends a correlated response to the lead inbox (`s10_team_protocols.py:236`, `s10_team_protocols.py:239`, `s10_team_protocols.py:242`).
- Teammate `plan_approval` creates a `request_id`, stores pending state, and sends `plan_approval_response` to lead (`s10_team_protocols.py:247`, `s10_team_protocols.py:249`, `s10_team_protocols.py:251`, `s10_team_protocols.py:252`).
- Lead `handle_shutdown_request` creates a request ID, tracks it as pending, and sends a `shutdown_request` to the teammate (`s11_autonomous_agents.py:439`, `s11_autonomous_agents.py:442`, `s11_autonomous_agents.py:443`).
- Lead `handle_plan_review` looks up a request, marks it approved/rejected, and sends the correlated response back (`s11_autonomous_agents.py:450`, `s11_autonomous_agents.py:452`, `s11_autonomous_agents.py:456`, `s11_autonomous_agents.py:457`).

### CLI surface

- `s09`, `s10`, and `s11` include manual CLI commands: `/team` prints roster and `/inbox` drains lead's inbox (`s09_agent_teams.py:390`, `s09_agent_teams.py:393`, `s10_team_protocols.py:471`, `s10_team_protocols.py:474`, `s11_autonomous_agents.py:565`, `s11_autonomous_agents.py:568`).
- `s11` also adds `/tasks` to show the persistent task board with owners (`s11_autonomous_agents.py:571`, `s11_autonomous_agents.py:573`, `s11_autonomous_agents.py:577`).

## External References

- None. This research is local-source only.

## Related Specs

- `.trellis/tasks/05-16-persistent-teammate-communication/prd.md` - secbot target behavior derived from this local reference. Note: this task directory was missing at final write time and was recreated only for research output.
- `.trellis/spec/backend/architecture.md` - secbot two-layer model and summary-only LLM context boundary.
- `.trellis/spec/backend/agent-registry-contract.md` - secbot's existing expert-agent registry constraints that teammate identity/state should not violate.
- `.trellis/spec/backend/blackboard-registry.md` - existing shared-state contrast; blackboard is persistent-in-memory and append-only, while reference mailboxes are per-agent JSONL with drain-on-read.

## Caveats / Not Found

- The reference mailbox uses plain append and truncate with no file locks. That is acceptable for a teaching harness but should be strengthened for secbot's concurrent asyncio/threaded runtime.
- The reference uses synchronous threads and direct Anthropic client calls; secbot should reuse its async `AgentRunner`, provider abstraction, tool registry, risk gates, and workspace restrictions.
- The reference keeps teammate message histories only in process memory. It persists identity/status and inboxes, not full teammate transcripts.
- The reference `config.json` can preserve stale `working` status after an ungraceful process exit; secbot should reconcile stale process-local handles at startup.
