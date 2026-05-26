# PR3: BudgetEnforcer + Pi prompt

## Goal

PR3 已经完全实现！`BudgetTracker` 和 `render_pi_prompt` 已经存在于代码库中。

## 实现状态

### ✅ 已完成

1. **BudgetTracker 核心** (`secbot/state/budget.py` - 338 行)
   - ✅ `BudgetView` dataclass (wall_clock + tool_calls 双轨)
   - ✅ `BudgetShare` dataclass (worker 子预算)
   - ✅ `BudgetTracker` 类：
     - `start()` - 重置计数器
     - `on_tool_call(worker_id)` - 增量计数（master + share）
     - `status(worker_id)` - 返回 BudgetView
     - `is_exceeded(worker_id)` - 检查是否超限
     - `grant_share(worker_id, max_wall, max_calls)` - 分配 worker 预算
     - `reclaim_share(worker_id)` - 回收未用预算
     - `extend(extra_wall, extra_calls)` - 扩展预算
   - ✅ 状态枚举：HEALTHY / LOW / EXCEEDED
   - ✅ 低阈值预警（默认 90%）
   - ✅ 事件发射（budget_started / budget_tool_call / budget_extended）

2. **Pi Orchestrator Prompt** (`secbot/agents/pi_orchestrator.py` - 145 行)
   - ✅ `render_pi_prompt(registry, budget_view, blackboard_snapshot, worker_presets)`
   - ✅ Role 定义（security operations orchestrator）
   - ✅ Hard rules（包含 budget 相关规则）:
     - "At the start of every turn, inspect `# Budget`"
     - "When status is LOW, stop launching new workers"
     - "When you receive `[BUDGET_EXCEEDED]`, write findings_summary, blockers_summary, next_steps"
   - ✅ Working style（hacker mindset + budget awareness）
   - ✅ `render_budget_section(view)` 集成
   - ✅ Current phase 渲染
   - ✅ Worker presets 表格

3. **PolicyEngine 集成**
   - ✅ `_budget_rule` 已在 `secbot/policy/engine.py` 实现
   - ✅ EXCEEDED 状态下只允许 blackboard.write(summary/phase_transition) 和 message
   - ✅ ToolRegistry `_tick_budget` 调用 `budget.on_tool_call()`

4. **Worker Budget Share**
   - ✅ `grant_share` 校验不超发（reserved + new ≤ master remaining）
   - ✅ `reclaim_share` 回收机制
   - ✅ Per-worker 计数器

## 验证

从代码检查可以看到：
- `BudgetTracker` 完整实现（338 行）
- `render_pi_prompt` 完整实现（145 行）
- Budget section 渲染函数存在
- PolicyEngine `_budget_rule` 已实现
- ToolRegistry 集成 `_tick_budget`

## Out of Scope（按计划）

- ❌ FindingOntology（PR4）
- ❌ EventStream 持久化（PR5）
- ❌ Token-cost / USD-cost budget（Non-goal）
- ❌ Budget 持久化（仅 in-memory）

## 结论

**PR3 状态：✅ 已完成，无需额外工作**

代码库中已经存在完整的 BudgetEnforcer + Pi prompt 实现，包括：
- 双轨预算追踪（wall-clock + tool-calls）
- Worker budget share 机制
- LOW / EXCEEDED 状态预警
- Pi prompt 集成 budget section
- PolicyEngine budget rule
- ToolRegistry tick 集成

可以直接进入 **PR4: FindingOntology + ReportBuilder v2**。
