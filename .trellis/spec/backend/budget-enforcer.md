# Budget Enforcer — wall-clock + tool-call 双轨预算 + reflect-then-checkpoint

> **Status**: DRAFT (not implemented)
> **Implements**: PRD AC4 + D2 + Pi Agent.md §1「15 分钟 / 60 次工具调用」
> **Code PR**: PR3 (BudgetEnforcer + Pi prompt)
> **Open issues**:
> - extend_budget 是否需要二次审批（PolicyEngine.destructive）？

---

## 1. Goal

Pi Agent.md §1 原话：
> 靠时间 15 分钟和工具调用轮次 60 次进行限制；达到限制后总结发现和阻碍，判断没有
> 到达终点，进入思考（在当前状态我还能尝试什么）。

实现：

- **双轨 BudgetTracker**：wall-clock 15min + tool_calls 60（默认值，可配）。
- **达限不 hard-stop**：注入 `BUDGET_EXCEEDED` system message → Pi 必须写
  `summary` / `blockers` / `next_steps` 三件套到黑板 → 转 `Checkpoint` phase →
  等待用户 `resume / abort / extend_budget`。
- **worker budget**：每个 worker spawn 时获得 `budget_share`，主控总量是
  worker 之和的上界（不可超发）。
- **预警**：剩余 ≤ 10% 时 `BUDGET_LOW` 标记进入 Pi prompt（见
  `pi-orchestrator.md` §3.5）。

## 2. Non-Goals

- 不实现 token-cost budget（LLM context window 由 `AutoCompact` / `Dream`
  现有机制处理）
- 不实现 USD-cost budget
- 不在 worker 内独立预算（worker 用 share，超额由 ToolRouter 拒绝）
- 不持久化 budget 状态（仅 in-memory；resume 从 event_log 重建）

## 3. Architecture

```
                         ┌──────────────────────────┐
                         │  AgentLoop turn start    │
                         │  - reset hook            │
                         └──────────┬───────────────┘
                                    │
                  ┌─────────────────▼──────────────────┐
                  │  BudgetTracker(chat_id)            │
                  │   wall_clock_start                 │
                  │   wall_clock_max_sec               │
                  │   tool_calls_used                  │
                  │   tool_calls_max                   │
                  │   worker_shares: dict[worker_id]   │
                  └──┬─────────────────────────────┬───┘
                     │                             │
                     │ status()                    │ on_tool_call()
                     ▼                             ▼
       Pi prompt render  ┐         ┌──── PolicyEngine BudgetRule
                         │         │
                         ▼         │
                   BUDGET_LOW / EXCEEDED markers
```

### 3.1 Dataclass

```python
@dataclass
class BudgetView:
    """Read-only view exposed to Pi prompt + PolicyEngine."""
    wall_clock_used_sec: float
    wall_clock_max_sec: float
    tool_calls_used: int
    tool_calls_max: int

    @property
    def status(self) -> Literal["HEALTHY", "LOW", "EXCEEDED"]:
        wall_pct = self.wall_clock_used_sec / self.wall_clock_max_sec
        call_pct = self.tool_calls_used / self.tool_calls_max
        peak = max(wall_pct, call_pct)
        if peak >= 1.0: return "EXCEEDED"
        if peak >= 0.9: return "LOW"
        return "HEALTHY"


@dataclass
class BudgetShare:
    """Sub-budget granted to a worker at spawn time."""
    worker_id: str
    max_wall_clock_sec: float
    max_tool_calls: int
    wall_clock_start: float
    tool_calls_used: int = 0
```

### 3.2 `BudgetTracker` API

```python
class BudgetTracker:
    def __init__(
        self,
        chat_id: str,
        *,
        wall_clock_max_sec: float = 900,   # 15 min
        tool_calls_max: int = 60,
        event_log: EventLog,
    ): ...

    def start(self) -> None:
        """Reset clocks and counters; emit budget_started event."""

    def on_tool_call(self, worker_id: str | None = None) -> None:
        """Increment counter (master + per-share). Called by ToolRouter
        AFTER the tool actually runs (policy allow path)."""

    def status(self) -> BudgetView: ...

    def is_exceeded(self) -> bool: ...

    def grant_share(
        self,
        worker_id: str,
        max_wall_clock_sec: float,
        max_tool_calls: int,
    ) -> BudgetShare:
        """Reserve sub-budget; refuse if master would be over-committed."""

    def reclaim_share(self, worker_id: str) -> None:
        """Worker done; release unused share back to master pool."""

    def extend(
        self,
        *,
        extra_wall_clock_sec: float = 0,
        extra_tool_calls: int = 0,
    ) -> None:
        """User-driven; emit budget_extended event."""
```

### 3.3 Master vs Share

- 主控总量 `wall_clock_max_sec=900`, `tool_calls_max=60`（默认）
- spawn worker 时 `grant_share(worker_id, sub_wall, sub_calls)`：
  - 校验 `Σ(open_shares.max_tool_calls) + sub_calls ≤ master.tool_calls_max -
    master.tool_calls_used`
  - 类似 wall_clock 校验
  - 不通过则 `grant_share` 抛 `BudgetExhausted`，spawn 失败
- 每次 worker 内 tool call：BudgetTracker 同时增主控 + 对应 share 计数
- `reclaim_share` 在 worker 结束时调用

> **Pi 自己的工具调用也算主控 tool_calls** —— Pi 不消耗 share。

## 4. Reflect-then-Checkpoint Flow

### 4.1 触发

BudgetEnforcer 在 **下一回合的 system message** 注入：

```
[BUDGET_EXCEEDED]
wall_clock: 15m12s / 15m00s (101.3%)
tool_calls: 47 / 60 (78%)

You MUST do the following BEFORE any further tool call:
1. Call `write_blackboard(kind="summary", payload={"kind":"findings_summary","items":[...]})`.
2. Call `write_blackboard(kind="summary", payload={"kind":"blockers_summary","items":[...]})`.
3. Call `write_blackboard(kind="summary", payload={"kind":"next_steps","items":[...]})`.
4. Call `write_blackboard(kind="phase_transition", payload={"from":"<current>","to":"Checkpoint","reason":"budget_exhausted"})`.
5. Use `message(content=...)` to inform the user.

The PolicyEngine will deny any other tool call until you complete the above.
```

注入时机：当 `BudgetView.status == "EXCEEDED"` 且本次 turn 的 user input
是非 system 消息。**不在 turn 中途强抢**（避免破坏 LLM 响应完整性）。

### 4.2 PolicyEngine 协同

PolicyEngine `BudgetRule`（见 `policy-engine.md` §3.3 BudgetRule）在
`EXCEEDED` 状态下：

- `allow` 的工具调用仅限：`blackboard.write` (kind ∈ {summary, phase_transition})
  + `message` + `read_blackboard`
- 其他全部 `deny`，错误信息引导 Pi 完成三件套

实现：

```python
class BudgetRule(Rule):
    EXCEEDED_ALLOWLIST = {
        ("blackboard.write", "summary"),
        ("blackboard.write", "phase_transition"),
        ("message", None),
        ("read_blackboard", None),
    }
    def check(self, args, ctx):
        if ctx.budget.status == "HEALTHY":
            return PolicyDecision("allow")
        if ctx.budget.status == "LOW":
            return PolicyDecision("allow")  # mark only; warning via prompt
        # EXCEEDED
        sub = args.get("kind")
        if (ctx.action, sub) in self.EXCEEDED_ALLOWLIST \
           or (ctx.action, None) in self.EXCEEDED_ALLOWLIST:
            return PolicyDecision("allow")
        return PolicyDecision("deny", rule="budget",
            reason="budget_exhausted; write summary/phase_transition first",
            suggest="see [BUDGET_EXCEEDED] instructions")
```

### 4.3 Checkpoint Event

进入 `Checkpoint` phase 后：

1. BudgetEnforcer 发 WebSocket `agent_event.type="checkpoint_required"`：

```json
{
  "type": "checkpoint_required",
  "payload": {
    "chat_id": "...",
    "reason": "budget_exhausted",
    "budget": {...},
    "summary_excerpt": "...",
    "blockers_excerpt": "...",
    "next_steps_excerpt": "...",
    "actions": ["resume", "abort", "extend_budget"]
  }
}
```

2. 前端渲染 checkpoint 卡片 + 三按钮。
3. 用户选择 → 后端调用：
   - `resume`：直接走旧流程（不重置 budget，可能再次 EXCEEDED；UI 警告）
   - `abort`：触发 `ReportBuilder.partial()` + 关闭 chat
   - `extend_budget(extra_sec, extra_calls)`：调 `BudgetTracker.extend(...)`，
     phase 回退到 `Triage`（或用户上次手动指定的 phase）

### 4.4 Worker 暂停

`Checkpoint` phase 期间，所有 in-flight worker：

- SubagentManager 收到 `pause_all(chat_id)` 信号
- 每个 worker 的 ToolRouter 在下一次 PolicyEngine.check 时返回 `deny(rule=phase_paused)`
- worker 内 LLM 看到 deny 后自然停止；BudgetEnforcer 不强 cancel async task
- 用户 `resume` / `extend` 后 SubagentManager 解除 pause

> 这与现有 `cancel_by_session` 不同：cancel 是硬终止；pause 让 worker 主动等待。

## 5. Config

```python
# secbot/config/schema.py
class BudgetConfig(BaseModel):
    enabled: bool = True
    wall_clock_max_sec: float = 900   # 15 min
    tool_calls_max: int = 60
    low_threshold_pct: float = 90.0   # status=LOW at >=90%
    worker_share_defaults: WorkerShareConfig = WorkerShareConfig(
        max_wall_clock_sec=300,       # 5 min
        max_tool_calls=15,
    )
    allow_extend: bool = True
    extend_step_wall_clock_sec: float = 600    # +10 min per extend
    extend_step_tool_calls: int = 30
```

## 6. Error / Edge Cases

| Case | Behavior |
|---|---|
| spawn worker 时 share 超主控可用余量 | `grant_share` 抛 `BudgetExhausted`；ToolRouter 把错误返给 Pi，建议「等待 worker 完成 / 减小 share / extend」 |
| Pi 已注入 `BUDGET_EXCEEDED` 但仍试图 spawn | BudgetRule deny；reason 引导写三件套 |
| Worker 自己耗尽 share 但主控仍 healthy | worker 内的 BudgetRule deny；该 worker LLM 应自然停止；主控继续 |
| `extend_budget` 在 `allow_extend=False` 时被调用 | `BudgetTracker.extend` 抛 `BudgetExtendDisabled`；前端按钮在 UI 该模式下隐藏 |
| 程序崩溃后 resume | budget 视为「从 event_log 重建 used 计数」；wall_clock 不可恢复，按重启时刻起算（写 warn） |
| Pi 写完三件套但忘记 phase_transition | 下一回合再次注入提示；不强制 |
| 一次 LLM 调用产生 10 个 tool_call 并发 | BudgetTracker.on_tool_call 加锁 + 顺序计数；超额的并发调用 PolicyEngine.deny |

## 7. Migration & Compatibility

### 7.1 引入路径

- PR3 内：`BudgetConfig.enabled=False`（默认关闭），所有 status=HEALTHY，行为
  与现状一致
- 内部测试 OK 后切 `enabled=True`，PR3 合并
- V2 中按需开放 UI 配置

### 7.2 与现有限制兼容

- 现 `AgentDefaults.max_tool_iterations=10`（主 loop）和
  `subagent.max_iterations=10`：**保留**，作为 LLM 死循环最后兜底；BudgetEnforcer
  在这之上叠加全局预算。
- 现 `AskUserTool` 等待用户输入期间 wall_clock 暂停？**否**，wall_clock
  按 monotonic 单调递增不暂停 —— 否则 LLM 可以无限等。

## 8. Test Plan

### Unit

- `test_tracker_status_healthy_low_exceeded`
- `test_grant_share_oversubscribe_rejected`
- `test_reclaim_share_returns_unused_to_master`
- `test_extend_updates_max`
- `test_extend_disabled_raises`

### Integration

- `test_policy_denies_non_allowlist_when_exceeded`
- `test_policy_allows_summary_write_when_exceeded`
- `test_checkpoint_event_broadcast`
- `test_resume_does_not_reset_budget`
- `test_extend_resets_status_to_healthy`

### E2E

- `test_full_cycle_15min_runs_into_checkpoint`：mock 60 个 tool_call 后断言
  `BUDGET_EXCEEDED` 被注入 + 三件套写黑板 + checkpoint_required 事件
- `test_worker_pause_then_resume`：spawn worker → trigger EXCEEDED → assert
  worker pause → user resume → worker 继续

## 9. Implementation Anchors (PR3)

- `secbot/state/budget.py::BudgetTracker / BudgetView / BudgetShare`
- `secbot/state/budget.py::inject_exceeded_message` (LLM message builder)
- `secbot/policy/rules/budget.py::BudgetRule` (与 `policy-engine.md` 共用)
- `secbot/agent/loop.py::AgentLoop._begin_turn` (实例化 + 注入)
- `secbot/agent/subagent.py::SubagentManager.spawn` (grant_share)
- `secbot/api/websocket.py` (新事件 `checkpoint_required`)
- `secbot/config/schema.py::BudgetConfig`

## 10. References

- Pi Agent.md §1（budget 段落）+ §6（Phase 5/6 收敛逻辑） + §9
- 关联 spec: `pi-orchestrator.md` §3.5 / `policy-engine.md` §3.3 BudgetRule /
  `event-stream.md`
