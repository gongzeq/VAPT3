# Event Stream — TaskGraph + EventLog SQLite 持久化 + replay

> **Status**: DRAFT (not implemented)
> **Implements**: PRD AC6 + D4 + Pi Agent.md §5「Event Stream + Evidence Store」/ §7「resume」
> **Code PR**: PR5 (EventStream 持久化)
> **Open issues**:
> - 是否压缩历史 event（每 N 个旧 event 合并为 phase_summary 节省存储）

---

## 1. Goal

让 secbot 从「无 audit trail / 进程崩溃丢状态」升级到：

- **append-only `event_log`**：所有 plan / tool_call / tool_result / approval /
  finding / phase_transition / policy_decision / budget 事件落盘
- **`task_graph_nodes` + `task_graph_edges`**：Pi 探索的 DAG（observation /
  hypothesis / action / approval / finding 节点）持久化
- **replay 协议**：进程重启 / resume 时按 `chat_id` 重建 Blackboard +
  BudgetTracker + PhaseTracker
- **每个 event 有 `event_id` + `created_at`**，可用于审计、UI 回放、调试

呼应 Pi Agent.md §5「每次计划、工具调用、结果、审批都有 event_id」+ §7「resume
summary」。

## 2. Non-Goals

- 不实现完整的时间序列数据库；用 SQLite append-only 足矣
- 不做事件分发 pub-sub（继续用现 MessageBus + WebSocket）
- 不做跨进程实时 stream（单进程 in-process subscribe；多进程留 V2）
- 不持久化 LLM message[] / chat history（已由 Session/SessionManager 处理）
- 不替换 raw scan log（仍由 EvidenceStore + fs 承接）

## 3. Schema

### 3.1 `event_log`

```sql
CREATE TABLE event_log (
  id             TEXT PRIMARY KEY,             -- 16-char uuid
  chat_id        TEXT NOT NULL,
  type           TEXT NOT NULL,                -- see §3.2 type taxonomy
  source         TEXT NOT NULL,                -- 'pi' | 'worker:<id>' | 'policy' | 'budget' | 'system'
  payload_json   TEXT NOT NULL,                -- 类型化 JSON, schema 取决于 type
  parent_event   TEXT,                         -- 因果父事件 id（如 tool_result.parent=tool_call.id）
  created_at     REAL NOT NULL,                -- monotonic-ish wall clock
  seq            INTEGER NOT NULL              -- per-chat 单调递增（用于 ordering）
);

CREATE INDEX idx_event_chat_seq ON event_log (chat_id, seq);
CREATE INDEX idx_event_chat_type ON event_log (chat_id, type);
CREATE INDEX idx_event_parent ON event_log (parent_event);
```

`seq` 由 `EventLog.append` 自动生成，每 chat 独立计数；确保 replay 顺序确定。

### 3.2 Event Type Taxonomy

| `type` | 触发方 | payload 关键字段 |
|---|---|---|
| `chat_started` | AgentLoop | `chat_id`, `surface`, `user_message_preview` |
| `phase_transition` | Pi (via blackboard) | `from`, `to`, `reason` |
| `plan_published` | Pi | `steps: list[str]` |
| `worker_spawned` | SubagentManager | `worker_id`, `preset`, `task`, `scope_view`, `budget_share` |
| `worker_finished` | SubagentManager | `worker_id`, `status` (ok/error), `stop_reason` |
| `tool_call` | ToolRouter | `tool`, `args_hash`, `caller_kind`, `worker_id?`, `call_id` |
| `tool_result` | ToolRouter | `call_id`, `status` (ok/error/denied), `summary`, `duration_ms` |
| `policy_decision` | PolicyEngine | `action`, `rule`, `verdict`, `reason` |
| `approval_request` | DestructiveRule | `skill`, `summary_for_user`, `payload` |
| `approval_response` | UI → BUS | `request_id`, `approved`, `reason?` |
| `evidence_stored` | EvidenceStore | `evidence_id`, `source_tool`, `evidence_type`, `size_bytes` |
| `hypothesis_added` | Blackboard | `entry_id`, `kind`, `confidence` |
| `finding_added` | Blackboard | `entry_id`, `severity`, `cwe[]` |
| `finding_promoted` | Pi | `finding_id`, `hypothesis_id` |
| `budget_started` | BudgetTracker | `wall_clock_max`, `tool_calls_max` |
| `budget_warned` | BudgetTracker | `status=LOW`, `wall_pct`, `call_pct` |
| `budget_exceeded` | BudgetTracker | `wall_pct`, `call_pct` |
| `budget_extended` | BudgetTracker | `extra_wall`, `extra_calls` |
| `checkpoint_required` | BudgetEnforcer | `reason`, `summary_excerpt` |
| `checkpoint_resumed` | UI → API | `action` (resume/abort/extend), `params?` |
| `report_published` | ReportBuilder | `scan_id`, `path`, `severity_counts` |
| `blackboard_corruption` | Blackboard | `entry_id`, `err` |
| `sanitiser_fallback` | EvidenceStore | `evidence_id`, `err` |
| `finding_adapter_fallback` | FindingAdapter | `skill`, `err` |
| `db_write_fail` | * | `table`, `err` |

未列入此表的 `type` 拒写（防止类型膨胀）；新增 type 需在本 spec 增补。

### 3.3 `task_graph_nodes`

```sql
CREATE TABLE task_graph_nodes (
  id              TEXT PRIMARY KEY,         -- 12-char uuid
  chat_id         TEXT NOT NULL,
  kind            TEXT NOT NULL,            -- observation | hypothesis | action | approval | finding | phase
  status          TEXT NOT NULL DEFAULT 'open',   -- open | done | rejected | superseded
  payload_json    TEXT NOT NULL,
  created_at      REAL NOT NULL,
  origin_event_id TEXT,                     -- 关联到 event_log.id
  FOREIGN KEY (origin_event_id) REFERENCES event_log(id)
);

CREATE INDEX idx_graph_nodes_chat ON task_graph_nodes (chat_id, created_at);
CREATE INDEX idx_graph_nodes_kind ON task_graph_nodes (chat_id, kind, status);
```

### 3.4 `task_graph_edges`

```sql
CREATE TABLE task_graph_edges (
  parent_id   TEXT NOT NULL,
  child_id    TEXT NOT NULL,
  edge_kind   TEXT NOT NULL,                  -- supports | refutes | depends_on | chains | promoted_to | replaces
  created_at  REAL NOT NULL,
  PRIMARY KEY (parent_id, child_id, edge_kind),
  FOREIGN KEY (parent_id) REFERENCES task_graph_nodes(id),
  FOREIGN KEY (child_id) REFERENCES task_graph_nodes(id)
);

CREATE INDEX idx_graph_edges_parent ON task_graph_edges (parent_id, edge_kind);
CREATE INDEX idx_graph_edges_child ON task_graph_edges (child_id);
```

### 3.5 Node / Edge 语义

| Node kind | 何时创建 | 关联 event |
|---|---|---|
| `observation` | tool_result 成功 + 含新事实 | tool_result |
| `hypothesis` | Blackboard.write(kind=hypothesis) | hypothesis_added |
| `action` | worker_spawned 或 Pi 自行 tool_call (非 evidence/blackboard) | worker_spawned / tool_call |
| `approval` | approval_request | approval_request |
| `finding` | Blackboard.write(kind=finding) | finding_added |
| `phase` | phase_transition | phase_transition |

| Edge kind | 含义 |
|---|---|
| `supports` | observation/finding → hypothesis（证据支持假设） |
| `refutes` | observation/finding → hypothesis（反证） |
| `depends_on` | action → action / hypothesis → action（先决） |
| `chains` | finding → finding（A 链式利用 B） |
| `promoted_to` | hypothesis → finding |
| `replaces` | node → node（旧节点被新节点 superseded） |

## 4. API

### 4.1 `EventLog`

```python
class EventLog:
    def __init__(self, db: sqlite3.Connection): ...

    async def append(
        self,
        chat_id: str,
        *,
        type: EventType,
        source: str,
        payload: Mapping[str, Any],
        parent_event: Optional[str] = None,
    ) -> str:
        """Insert event, return event_id. seq is auto-assigned."""

    async def replay(
        self,
        chat_id: str,
        *,
        until_seq: Optional[int] = None,
    ) -> Iterator[EventRecord]:
        """Yield events in seq order; for state rebuild on resume."""

    async def subscribe(
        self,
        chat_id: str,
        callback: Callable[[EventRecord], Awaitable[None]],
    ) -> Subscription:
        """In-process pub/sub for UI broadcaster."""
```

### 4.2 `TaskGraph`

```python
class TaskGraph:
    def __init__(self, db: sqlite3.Connection, chat_id: str): ...

    async def add_node(
        self,
        kind: NodeKind,
        payload: Mapping[str, Any],
        *,
        origin_event_id: Optional[str] = None,
    ) -> str: ...

    async def add_edge(
        self,
        parent_id: str,
        child_id: str,
        edge_kind: EdgeKind,
    ) -> None: ...

    async def update_status(
        self,
        node_id: str,
        status: Literal["open", "done", "rejected", "superseded"],
    ) -> None: ...

    async def neighbours(
        self,
        node_id: str,
        *,
        direction: Literal["in", "out"] = "out",
        edge_kinds: Optional[Iterable[EdgeKind]] = None,
    ) -> list[NodeRef]: ...

    async def to_dag(self) -> DagView:
        """Return a node + edge list snapshot for UI rendering."""
```

### 4.3 集成点

| 触发位置 | 写入 |
|---|---|
| `AgentLoop._begin_turn` | event `chat_started` (first turn only) |
| `Blackboard.write` | event 对应 kind + 若 kind ∈ {finding, hypothesis, phase_transition, summary} 同时 `TaskGraph.add_node` |
| `SubagentManager.spawn` | event `worker_spawned` + node `action` |
| `SubagentManager._run_subagent.done` | event `worker_finished` + node.status='done' |
| `ToolRegistry.execute_tool` (post-policy) | event `tool_call` |
| `ToolRegistry.execute_tool` (post-execute) | event `tool_result` + 可能 node `observation` |
| `PolicyEngine.check` (verdict ≠ allow) | event `policy_decision` |
| `DestructiveRule.check` (need_approval) | event `approval_request` |
| UI 回信 → API | event `approval_response` |
| `EvidenceStore.put` | event `evidence_stored` |
| `BudgetTracker.start/warn/exceed/extend` | 对应 budget_* event |
| `ReportBuilder.publish` | event `report_published` |

## 5. Resume Protocol

### 5.1 触发

1. 进程崩溃 / 重启后 user 打开旧 chat
2. UI 调 `POST /api/chats/<chat_id>/resume`
3. AgentLoop 为该 chat_id 启动 turn 前先 `_rehydrate(chat_id)`

### 5.2 `_rehydrate(chat_id)` 步骤

```python
async def _rehydrate(chat_id: str) -> RehydratedState:
    # 1. event_log 按 seq 顺序读全部 event
    events = list(await event_log.replay(chat_id))

    # 2. 重建 Blackboard（in-memory）
    board = await blackboard_registry.get_or_create(chat_id)
    for evt in events:
        if evt.type in BLACKBOARD_EVENT_TYPES:
            await board.write(
                agent_name=evt.source,
                kind=evt.payload["kind"],
                payload=evt.payload["payload"],
            )
        # legacy_text fallback if needed

    # 3. 重建 BudgetTracker
    budget = BudgetTracker(chat_id, ...)
    budget.start()
    for evt in events:
        if evt.type == "tool_call":
            budget.on_tool_call(worker_id=evt.payload.get("worker_id"))
        elif evt.type == "budget_extended":
            budget.extend(**evt.payload)

    # 4. 重建 PhaseTracker（指向最新 phase_transition）
    latest_phase = next(
        (e for e in reversed(events) if e.type == "phase_transition"),
        None,
    )
    phase = latest_phase.payload["to"] if latest_phase else "Intake"

    # 5. TaskGraph 已在 DB；不需重建
    # 6. EvidenceStore 已在 DB+fs；不需重建

    return RehydratedState(
        blackboard=board,
        budget=budget,
        phase=phase,
        last_seq=events[-1].seq if events else 0,
    )
```

### 5.3 Resume 行为

- 若 `phase=="Checkpoint"`：UI 渲染 checkpoint 卡片（从最近 `checkpoint_required`
  event 读 summary_excerpt）；用户操作 → API 调用
- 若 `phase` 其他：Pi 收到 user 新消息正常回合开始；prompt 注入完整
  `BlackboardSnapshot`

### 5.4 Drift handling

进程重启后 `wall_clock` 无法精确恢复（mono clock 重置）。策略：

- `BudgetTracker.start` 把 wall_clock 从 0 起算（**不**累加重启前耗时）
- 写一条 event `budget_clock_reset` 标记；UI 可显示警告
- `tool_calls_used` 从 event_log 重建（精确）

> 这是有意的简化：让长时间挂起后的 resume 不被 wall_clock 卡死。

## 6. UI Replay Endpoint

```
GET /api/chats/<chat_id>/events?since_seq=0&type=tool_call,finding_added&limit=200
→ {
  events: [...],
  next_seq: ...,
  has_more: true|false
}

GET /api/chats/<chat_id>/graph
→ {
  nodes: [{id, kind, status, payload, created_at}, ...],
  edges: [{parent, child, kind}, ...]
}
```

前端时间轴 / 任务图 panel 直接消费。

## 7. Error / Edge Cases

| Case | Behavior |
|---|---|
| `event_log` 写失败 | 兜底 logger.error；不中断主流程；视为本次操作未生效（可能导致 replay 状态偏移） |
| 双进程同时写 event_log | SQLite WAL 模式；append 顺序保证；seq 由 `MAX(seq)+1` SELECT FOR UPDATE 计算 |
| Replay 时遇到 unknown type | 跳过 + warn；不让旧 event 阻断 |
| TaskGraph 出现孤立节点（无 edge） | 视为合法（可能是早期 observation 还没关联） |
| Edge `replaces` 形成环 | 检测后拒写；写 `db_write_fail` event |
| Resume 时 event_log 超过 10k 行 | 用 streaming iterator；不一次性 load |

## 8. Migration & Compatibility

### 8.1 与 CMDB 共存

PR5 在 CMDB SQLite 数据库新增 3 张表 + 索引；不动现有 `assets / scans / raw_logs
/ findings` 等表。

migrations 文件：

```
secbot/cmdb/migrations/
  0009_event_log.sql
  0010_task_graph.sql
```

### 8.2 与 WebSocket 兼容

现 `agent_event` WebSocket 协议保留；PR5 内部把 ws broadcast 改为先 `event_log.
append` 再广播（确保 UI 看到的事件 = DB 持久化的事件）。

### 8.3 与 AuditLogger 替换

`secbot/agents/high_risk.py::AuditLogger` 在 PR2 已 delegate 到 PolicyEngine，
PR5 进一步把 audit emit 改为 `event_log.append`，旧 AuditLogger 删除。

## 9. Test Plan

### EventLog unit

- `test_append_assigns_monotonic_seq`
- `test_replay_in_order`
- `test_unknown_type_rejected_at_write`
- `test_subscribe_receives_events`
- `test_concurrent_appends_no_seq_gap`

### TaskGraph unit

- `test_add_node_links_origin_event`
- `test_add_edge_unique_per_kind`
- `test_neighbours_directional`
- `test_replaces_cycle_rejected`

### Resume integration

- `test_rehydrate_rebuilds_blackboard`
- `test_rehydrate_rebuilds_budget_calls`
- `test_rehydrate_phase_checkpoint_renders`
- `test_resume_drift_wall_clock_reset_event`

### UI replay

- `test_get_events_pagination`
- `test_get_graph_returns_dag_view`

### Cross-spec

- `test_policy_deny_emits_event` (与 `policy-engine.md` §4.3 联动)
- `test_finding_added_creates_graph_node` (与 `finding-ontology.md` 联动)
- `test_budget_exceeded_emits_checkpoint_required` (与 `budget-enforcer.md` 联动)

## 10. Implementation Anchors (PR5)

- `secbot/state/event_log.py::EventLog`
- `secbot/state/task_graph.py::TaskGraph`
- `secbot/state/rehydrate.py::rehydrate_chat`
- `secbot/cmdb/migrations/0009_event_log.sql` + `0010_task_graph.sql`
- `secbot/agent/loop.py::AgentLoop._begin_turn`（调 rehydrate）
- `secbot/agent/tools/registry.py::ToolRegistry.execute_tool`（emit tool_call/result）
- `secbot/agent/subagent.py::SubagentManager.{spawn,_run_subagent}`（emit worker_*）
- `secbot/agents/high_risk.py`（最终删除；audit emit 改 event_log）
- `secbot/api/routes/chats.py::resume / events / graph` endpoints

## 11. References

- Pi Agent.md §5（Audit Plane）+ §7（resume summary）+ §8（MVP resume 能恢复任务）
- 关联 spec: `structured-blackboard.md` / `policy-engine.md` /
  `budget-enforcer.md` / `finding-ontology.md`
