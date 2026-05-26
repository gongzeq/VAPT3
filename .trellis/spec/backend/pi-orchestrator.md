# Pi Orchestrator — phase-aware DAG 主控提示词契约

> **Status**: DRAFT (not implemented)
> **Replaces**: `.trellis/spec/backend/orchestrator-prompt.md` (which is now DEPRECATED)
> **Implements**: PRD `.trellis/tasks/05-23-secbot-pi-worker/prd.md` AC1 + D1 + D2
> **Code PR**: PR3 (BudgetEnforcer + Pi prompt)
> **Open issues**:
> - 是否在 prompt 里暴露 `branch_summary` 给 Pi（依赖 V2 BranchManager）

---

## 1. Goal

把 `secbot/agents/orchestrator.py` 的 **硬编码线性 5 阶段管道** 改造为
**phase-aware DAG 探索主控**，与 Pi Agent.md §1/§3/§5/§6 完全一致：

- **不预定义 worker 具体功能**：worker 入参 = `(skills, scope_view, budget)`；
  没有 prompt 锁死 `asset_discovery → port_scan → ...` 字面顺序。
- **DAG 探索**：Pi 在每一回合显式选 `phase`（Intake / Passive Discovery /
  Active Mapping / Hypothesis Generation / Safe Validation / Triage / Reporting）
  并在黑板写下 `phase_transition`。
- **Budget 感知**：prompt 注入 `budget_remaining_seconds` +
  `budget_remaining_tool_calls`；达限交给 BudgetEnforcer 触发 reflect-checkpoint
  (见 `budget-enforcer.md`)。
- **黑板感知**：每回合 Pi 必须 `read_blackboard` 之前才能 spawn worker；
  prompt 显式写明「**已知事实不重复探测**」。

## 2. Non-Goals

- 不实现 `BranchManager` / `/tree` resume（V2 PR8）
- 不引入新的 worker 通信通道（继续用 SubagentManager + AssetFeed + Blackboard）
- 不重新设计 Plan tool（继续用 `write_plan`，仅语义增补）
- 不变更 worker 内部 ReAct loop（worker 仍是 LLM + skill 子集）

## 3. Prompt Composition Contract

新 `render_orchestrator_prompt(registry, *, budget_view, blackboard_snapshot,
worker_presets)` 接口产出 6 段，**只有第 3-5 段是动态的**：

```
# Role
（恒定）

# Hard rules
（恒定 + Pi 思维方式段落）

# Available worker presets   ← 动态：4 泛化 preset + legacy alias 表
# Current phase              ← 动态：从 blackboard_snapshot.phase 读
# Budget                     ← 动态：budget_view 注入

# Working style
（恒定）
```

### 3.1 `# Role` (locked)

```
You are secbot, a security operations orchestrator. You decide which worker
to dispatch and when to checkpoint. You DO NOT execute scans yourself.
```

### 3.2 `# Hard rules` (locked)

必须包含且只包含：

1. **Tool surface**：
   - `create_worker(preset, task, scope_view, budget_share, skills_subset?)`
   - `read_blackboard()` / `write_blackboard(kind, payload)`
   - `request_approval(action, args, justification)`
   - `write_plan(steps[])`
   - `message(content)`（直接回用户）

2. **DAG 决策规则**：
   - 在 spawn worker 之前必须 `read_blackboard`，禁止重复探测已有事实。
   - 不预设任何固定顺序；按 `phase` + `budget` + 黑板事实推导下一步。
   - 当观察到新事实时写 `write_blackboard(kind=finding|hypothesis|...)`，
     不准在 prompt 里复述黑板内容（节省 token）。

3. **Phase transition rules**：
   - 进入新 phase 时 `write_blackboard(kind="phase_transition", payload={
     from, to, reason})`。
   - 每个 phase 的退出条件由 Pi 自主判断；不存在「必须先做完 X 才能做 Y」的
     硬约束（除 destructive gate）。

4. **Budget rules**：
   - 每次 LLM 回合开头检查 `# Budget` 段；剩余 < 10% 时 prompt 注入
     `BUDGET_LOW` 标志，Pi 应该开始收敛（停止 spawn 新 worker，开始 triage）。
   - 收到 `BUDGET_EXCEEDED` 标志时（由 BudgetEnforcer 注入），**必须**
     `summarize_findings + list_blockers + propose_next_steps` 三件套写黑板。

5. **Scope rules**：
   - 越界目标禁止 spawn worker，直接 `message` 拒绝。
   - 高危动作（destructive）必须 `request_approval`，不准在 worker prompt 里
     夹带绕过。

6. **Worker preset selection**：
   - 不再有 `vuln_detec is endpoint-bound and ONLY for HTTP` 这类硬规则。
   - 选 preset 时按 `# Available worker presets` 表的 `applicable_when` 字段
     匹配（见 §4.1）。

### 3.3 `# Available worker presets` (dynamic)

| Preset name | Applicable when | Preferred/default skills (from agents/{preset}.yaml::scoped_skills) | Risk ceiling |
|---|---|---|---|
| `recon` | 目标为 CIDR/域/未知拓扑 | `qscan-host-discovery, fscan-asset-discovery, httpx-probe` | low |
| `crawl` | 已知 HTTP endpoint，需要 site map | `katana-crawl-web, httpx-probe` | low |
| `triage` | 黑板已有 findings 需要去重 + 严重性 | （无外部 binary，纯 LLM + EvidenceStore 读） | low |
| `report` | Phase = Reporting | `report-html` | low |
| `legacy:asset_discovery` (alias → recon + extra prompt) | 旧调用兼容 | 同 `recon` | low |
| `legacy:port_scan` (alias → recon, skill 限定 `qscan-port-scan`) | 旧调用兼容 | `qscan-port-scan` | low |
| `legacy:vuln_scan` | 旧调用兼容 | `fscan-vuln-scan, nuclei-template-scan` | medium |
| `legacy:vuln_detec` | 旧调用兼容 | `vuln-detec-manual` | medium |
| `legacy:weak_password` | 旧调用兼容 | `hydra-bruteforce` | critical |
| `legacy:crawl_web` | 旧调用兼容 | 同 `crawl` | low |
| `legacy:report` | 旧调用兼容 | 同 `report` | low |

> 表由 `AgentRegistry.render_preset_table()` 动态生成（PR1 扩展）。
> `applicable_when` 是 prompt-only 提示，不是硬约束 —— Pi 仍按黑板判断。

### 3.4 `# Current phase` (dynamic)

从黑板最新 `phase_transition` 条目读，缺省 `Intake`。允许阶段集合：

```
Intake | Passive Discovery | Active Mapping | Hypothesis Generation |
Safe Validation | Triage | Reporting | Checkpoint
```

Pi 在 prompt 里看到的格式：

```
# Current phase
phase: Active Mapping
entered_at: 2026-05-23T14:12:08Z
reason: "recon worker confirmed 3 live hosts; need authenticated mapping"
```

### 3.5 `# Budget` (dynamic)

```
# Budget
wall_clock:        used 4m23s / 15m00s   (29% used, 10m37s left)
tool_calls:        used 18  / 60         (30% used, 42 left)
status:            HEALTHY                # HEALTHY | LOW | EXCEEDED
```

`status=LOW` 当任一指标 ≥ 90%；`status=EXCEEDED` 由 BudgetEnforcer 在
**下一回合开头** 注入 `BUDGET_EXCEEDED` system 消息（见 `budget-enforcer.md` §4）。

### 3.6 `# Working style` (locked)

```
- Plan in 1-3 steps before delegating; call `write_plan` when a visible plan helps.
- After each tool result, decide one of:
    continue / replan / request approval / answer.
- Use the user's language (default: 中文).
- HACKER MINDSET: think deeper than scanners. Chain findings.
- Never accept "this is probably secure" — verify it.
- When `BUDGET_LOW`: stop spawning workers; start triaging; write
  `[milestone]` summaries.
- When `BUDGET_EXCEEDED`: write `summarize_findings` / `list_blockers` /
  `propose_next_steps` to the blackboard and stop.
```

> HACKER MINDSET 段落（chain findings / business logic / payload creativity）
> 从旧 `orchestrator.py::_HARD_RULES` 整段复制到 `# Working style`，避免硬规则
> 区污染。

## 4. Phase State Machine

```
Intake
  ├─ Passive Discovery ─┐
  │                     ▼
  │              Active Mapping
  │                     │
  ▼                     ▼
  Hypothesis Generation ──┐
        │                 │
        ▼                 ▼
   Safe Validation  ──→  Triage
                          │
                          ▼
                      Reporting
                          │
                          ▼
                     Checkpoint  ← BudgetEnforcer / user pause 可从任一阶段进入
```

- **Pi 拥有阶段转移权**，但每次转移必须 `write_blackboard(kind="phase_transition")`。
- `Checkpoint` 由 BudgetEnforcer 强制注入；从 Checkpoint 退出需要用户
  `resume` 或 `extend_budget`。
- 阶段不是 worker 类型 —— 任何 worker preset 都可以在多个阶段被调度（如
  `recon` 既在 Passive Discovery 也在 Active Mapping 被用）。

## 5. Worker Spawning Contract

新 `create_worker` 工具（替代旧 `create_agent`）：

```json
{
  "name": "create_worker",
  "parameters": {
    "preset": "recon | crawl | triage | report | legacy:<old_name>",
    "task": "FULL prompt for the worker (Pi composes from blackboard)",
    "scope_view": {
      "in_scope": ["example.com", "10.0.0.0/24"],
      "out_of_scope": ["payments.example.com"]
    },
    "budget_share": {
      "max_wall_clock_sec": 300,
      "max_tool_calls": 15
    },
    "skills_subset": ["qscan-host-discovery"],
    "endpoint_url": "https://app.example.com/login",
    "endpoint_param": "username"
  }
}
```

- `preset` 必填；`skills_subset` 可空（用 preset 默认）。`skills_subset` 是 worker prompt 中的优先工具提示，不是硬隔离：worker 仍注册全部未禁用的可执行 SkillTool，以便在任务需要时切换到更精确的 httpx / qscan / katana / nuclei / ffuf / sqlmap / hydra 等工具。
- `scope_view` 是从 ScopeContract 派生的**只读切片**；worker 看不到全局。
- `budget_share` 从主控剩余 budget 划拨；BudgetEnforcer 强制不超主控总量。
- `endpoint_url + endpoint_param` 用于 `_endpoint_inflight` 互斥锁（保留现有
  `subagent.py::_normalise_endpoint_key` 行为）。

### 5.1 Worker 权限边界

- **无最终漏洞确认权**：worker 输出 `candidate_finding`，主控才能升级为
  `confirmed_finding`。
- **无报告签发权**：仅 `report` preset 可以调用 `report-html` skill。
- **无 spawn 权**：worker 不能再 spawn worker。
- **黑板只读其 scope_view 相关项**：BlackboardReadTool 在 worker 上下文中
  按 scope 过滤（PR1 实施）。

## 6. Backward Compatibility

- 旧调用 `create_agent(name="port_scan", ...)` 由 `create_worker` 适配层接住：
  `name → preset="legacy:port_scan"`，args 透传。
- 现有 `agents/*.yaml` 解析行为不变，但 `endpoint_bound` / `allow_exec` 字段被
  PolicyEngine 接管（见 `policy-engine.md` §3.3）。
- `_HARD_RULES` 中所有 `asset_discovery → port_scan → ...` 字面顺序规则
  **删除**；替换为 §3.2 §3.3 §3.4 §3.5 新规则。

## 7. Error / Edge Cases

| Case | Behavior |
|---|---|
| Worker preset 未知 | 返回 `{"error": "unknown preset", "available": [...]}` 到 LLM |
| `scope_view` 包含 `out_of_scope` 主机 | PolicyEngine 拒绝；不 spawn |
| Endpoint 互斥锁冲突 | 沿用现有 `endpoint already busy` 提示 |
| 黑板被损坏（payload 不符合 typed schema） | 容忍 + 写 `event_log(kind="blackboard_corruption")`；旧 text entry fallback |
| Pi 试图在 `Checkpoint` phase spawn worker | 工具调用直接拒绝，提示「等待 resume」 |
| Budget exhausted 但 Pi 仍调 tool | BudgetEnforcer 在 ToolRouter 层拦截，返回 `{"error": "budget_exceeded"}` |

## 8. Migration & Compatibility

### 8.1 Phase 1（PR3 内）

- 新文件 `secbot/agents/pi_orchestrator.py`（与旧 `orchestrator.py` 共存）
- 新文件 `secbot/agents/presets/{recon,crawl,triage,report}.yaml`
- 旧 `secbot/agents/*.yaml` 移到 `secbot/agents/legacy/` 但 import 路径保持
- `AgentLoop._build_orchestrator_prompt` 根据 config flag
  `agents.use_pi_prompt=true|false` 选 render 路径

### 8.2 Phase 2（V2 PR6 后）

- `use_pi_prompt=true` 成为默认；旧 path 删除
- `create_agent` 工具完全替换为 `create_worker`

### 8.3 Config

```python
# secbot/config/schema.py 新增字段（PR3）
class AgentsConfig:
    use_pi_prompt: bool = False  # PR3 引入；V2 默认 true
```

## 9. Test Plan

### Snapshot tests

- `tests/agents/test_pi_orchestrator_prompt.py::test_render_locked_sections`
  断言 `# Role / # Hard rules / # Working style` 字节级稳定
- `test_render_dynamic_sections` 用固定 budget/phase/snapshot 渲染，
  diff `golden/pi-orchestrator-{phase}.md`

### Behavioral tests

- `test_pi_cannot_spawn_in_checkpoint`：phase=Checkpoint 时 `create_worker`
  调用被拒绝
- `test_pi_must_read_blackboard_before_spawn`：第一次 spawn 之前没有
  `read_blackboard` 调用，runner 报警（log warn，不拒绝）
- `test_budget_low_changes_prompt`：剩余 < 10% 时 `# Budget` 段 status=LOW

### Compat tests

- `test_legacy_create_agent_routes_to_preset`：`name="port_scan"` 被适配为
  `preset="legacy:port_scan"`
- `test_legacy_yaml_still_loadable`：现有 7 个 YAML 在 `agents/legacy/` 下不
  报错

## 10. Implementation Anchors (for PR3)

- `secbot/agents/pi_orchestrator.py::render_pi_prompt`
- `secbot/agents/registry.py::AgentRegistry.render_preset_table`
- `secbot/agent/tools/spawn.py::CreateWorkerTool`（重命名 + 扩展 `SpawnTool`）
- `secbot/state/budget.py::BudgetView`（见 `budget-enforcer.md`）
- `secbot/state/phase.py::PhaseTracker`（黑板适配器，读最新 `phase_transition`）

## 11. References

- Pi Agent.md §1 / §3 / §4 / §5 / §6 / §9
- 旧 spec: `orchestrator-prompt.md` (DEPRECATED)
- 关联 spec: `structured-blackboard.md` / `policy-engine.md` /
  `budget-enforcer.md` / `event-stream.md`
