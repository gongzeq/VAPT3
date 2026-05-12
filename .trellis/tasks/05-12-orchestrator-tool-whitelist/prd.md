# brainstorm: 主 agent 工具白名单（delegate / read_blackboard / write_plan / request_approval）

## Goal

把 orchestrator（主 loop）的工具面严格收敛到**四个编排类工具**，彻底禁止它直接调用任何"操作型"工具（文件读写、shell、web、skill、blackboard_write、message 等）。
所有对真实资源的访问都必须经由子 agent 完成。目标是：

- 让主 agent 在可观测层面只做"规划 / 派发 / 等待结果 / 要人工审核"四件事；
- 从协议层消除"orchestrator 自己扫描自己写盘"这类越权路径；
- 与 PR3（子 agent 按 `scoped_skills` 裁剪）、PR4（exec 默认关）保持对齐，把"工具路由"这一层完全契约化。

## What I already know

### 当前 orchestrator 工具面（`secbot/agent/loop.py::_register_default_tools`）

- 已注册：`AskUserTool` / `ReadFileTool` / `WriteFileTool` / `EditFileTool` / `ListDirTool` / `GlobTool` / `GrepTool` / `NotebookEditTool` / `ExecTool`（受 enable 控制）/ `WebSearchTool` / `WebFetchTool`（受 enable 控制）/ `MessageTool` / `SpawnTool` / `BlackboardWriteTool` / `BlackboardReadTool` / 全部 SkillTool / `CronTool` / `MyTool`
- 也就是说：**主 loop 当前和 subagent loop 共享同一套默认工具集**，只有 subagent 在 PR3 之后会按 `spec.scoped_skills` 过滤

### 已有的"前身工具"

- `spawn`（[`secbot/agent/tools/spawn.py`](file:///Users/shan/Downloads/nanobot/secbot/agent/tools/spawn.py)） — 已支持 `agent=` 参数，本质就是"delegate_task"的雏形
- `blackboard_read` / `blackboard_write`（[`secbot/agent/tools/blackboard.py`](file:///Users/shan/Downloads/nanobot/secbot/agent/tools/blackboard.py)） — 已存在；本期要把 write 从主 agent 下掉
- `ask_user`（[`secbot/agent/tools/ask.py`](file:///Users/shan/Downloads/nanobot/secbot/agent/tools/ask.py)） — 通用"阻塞问用户"；`request_approval` 大概率是它的语义专化
- `HighRiskGate`（[`secbot/agents/high_risk.py`](file:///Users/shan/Downloads/nanobot/secbot/agents/high_risk.py)） — 已有"高风险确认"流程（request/approve/deny/timeout 四类事件），`request_approval` 可直接复用其事件模型
- `write_plan` — **完全新增**，现有仅有"plan part"（assistant 气泡里的 `plan` markdown 块，`_WORKING_STYLE` 里提到）没有专门的工具

### 相关正在进行/已规划的任务

- `.trellis/tasks/05-08-dynamic-subagent-orchestration/prd.md` — 动态子智能体编排与黑板共享（LLM 规划式并行、blackboard 协议、前端卡片）
- `.trellis/tasks/05-11-security-tools-as-tools/prd.md` — PR3 子 agent 裁剪（已完成）、PR4 exec 默认关闭（未开始）
- 本任务在这两条线的上方，给 orchestrator 层加一层**硬性工具白名单**

## Assumptions (temporary)

- 四个工具是**主 agent 的"唯一可调集合"**；其余所有工具（包括 FS / Web / Message / Blackboard Write / Skill）一律不挂到主 loop 的 ToolRegistry
- 主 agent 回复用户仍靠**普通 assistant content**（不依赖 `message` 工具）
- `delegate_task` 是 `spawn` 的"语义别名"，底层调用链不变；至少保留 `spawn` 别名一个版本以兼容测试/文档
- `read_blackboard` 是 `blackboard_read` 的语义别名，同理
- `write_plan` 只产出"结构化 plan 广播"（前端卡片），**不**负责调度——调度仍然由 LLM 后续 `delegate_task` 调用决定
- `request_approval` 独立于 `ask_user`：前者是"编排级人工审核"（HITL），走 `HighRiskGate` 事件总线；后者是普通问答。两者 MVP 阶段可以**共享底层**但 tool name 分开

## Decision Log

- **D1 `write_plan` 语义 = 纯展示广播**
  - 参数：`steps: list[{title: string, detail?: string}]`
  - 只触发一条 `agent_event`（类型暂定 `orchestrator_plan`）给前端渲染"阶段计划卡片"
  - **不**驱动调度；后续仍靠 LLM 逐个 `delegate_task`
  - 与 05-08 的"结构化并行 plan"解耦：那边若需要结构化契约，另起 tool

- **D2 `request_approval` = `ask_user` 的语义别名**
  - 底层复用 `AskUserInterrupt`（阻塞 + 用户回复作为 tool 结果）
  - tool name 独立，schema：`{title: string, detail?: string, options?: [Approve, Deny, ...]}`
  - 前端按"审核待批"卡片渲染（Approve/Deny 结构化按钮），与普通 ask_user 视觉区分
  - 不引入 HighRiskGate 的 timeout / 审计日志（MVP 不做；未来可升级）

- **D3 严格 4 工具白名单**
  - 主 agent ToolRegistry 最终只含 4 个 Tool；**`message` / `ask_user` 也下掉**
  - 主 agent 与用户的所有非阻塞对话一律走 assistant content
  - 需要阻塞式人工交互 → `request_approval`

- **D4 PR4 独立推进**
  - 本任务只负责"主 agent 工具面白名单"，**不**动子 agent 的 exec / skill
  - PR4（`ExecToolConfig.enable=False` 全局默认 + 子 agent 层 docs）另行完成

- **D5 `spawn` → `delegate_task` 直接改名（破坏性升级）**
  - `SpawnTool.name` 改为 `"delegate_task"`
  - `BlackboardReadTool.name` 改为 `"read_blackboard"`
  - 一次性迁移：`tests/providers/*`、WebUI TraceEntry、`docs/*`、orchestrator prompt 中的 tool name 断言
  - 不做 alias；LLM 和测试看到的是同一套新名

- **D6 子 agent 也下掉 `delegate_task`**
  - `SubagentManager._run_subagent` 注册工具时不再注入 `SpawnTool / DelegateTaskTool`
  - 强制"主 → 子 → 具体工具"的两层架构，禁止递归 spawn
  - 给子 agent 直接会省掉一整分支逻辑（没有 manager 就禁止注册）

- **D7 侦查场景：允许主 agent 纯 assistant content 回答**
  - 用户问纯只读问题（代码解读、概念问答、对既有报告的段落理解）时，主 agent 直接用模型内存知识回复即可
  - orchestrator prompt 需明确授权："纯信息问题无需 delegate"
  - 涉及实时 / 外部资源 / 写入写改 → 必须 `delegate_task`

## Open Questions

- _(all resolved —— see Decision Log D1–D7)_

## Diverge Sweep（需要用户确认进入 MVP / 还是 Out-of-Scope）

### 未来演进

- 多级编排（team-lead → sub-lead → worker）：白名单机制要能分层覆盖；建议把 `_register_orchestrator_tools()` 做成"按 agent 级别取不同白名单"的注册器
- 前端"计划卡片"可能演进为可点击的甘特图 / 进度条；`orchestrator_plan` 事件协议要预留 `step_id` 字段以便后续补"完成度"

### 相邻场景

- CLI 模式（无前端）：`request_approval` 走 `AskUserInterrupt` 时，CLI 端 prompt 样式与 `ask_user` 必须区分（否则用户看不出这是"审批"而非"问答"）
- 非交互模式（cron / API）：`request_approval` 是自动 deny？还是抛错？—— 建议与现有 HighRiskGate 的非交互策略对齐
- 老 provider 回归（例如 DeepSeek / Gemini / Qwen 的 tool-call 集成测试）：断言了 `tool_name="spawn"` 的用例需要迁移

### 故障 / 边界

- LLM 幻觉调用不存在的 tool（如 `read_file`）：provider 层会返回 schema 错误；orchestrator prompt 需要显式写"你只有 4 个工具，其余能力用 delegate_task"
- `write_plan` 被调多次：前端 MVP 默认"覆盖显示最新一份"（未来再做 diff / 历史）
- `request_approval` 超时：MVP 不做 timeout（等同 ask_user）；长任务下可能挂起 —— 需要在 docs 里说明
- `delegate_task` 指向 offline agent：PR3 已返回 tool error 文本，主 agent 自然能读到
- `blackboard_write` 从主 agent 下掉后，主 agent 若想"记个笔记"只能走 assistant content 或 delegate 给子 agent —— 需要 prompt 说清楚这个行为边界

## Requirements

### 主 agent 工具注册

- `AgentLoop` 区分"主 loop" vs "子 loop"（新增 `is_orchestrator: bool` 或从 `subagents` 参数推断）
- 主 loop `_register_default_tools` 只注册 4 个 Tool：
  - `DelegateTaskTool`（`SpawnTool` 重命名）
  - `ReadBlackboardTool`（`BlackboardReadTool` 重命名）
  - `WritePlanTool`（新建）
  - `RequestApprovalTool`（新建，复用 AskUserInterrupt）
- 主 loop 不注册：File / Web / Exec / Notebook / Message / AskUser / BlackboardWrite / Cron / My / SkillTool

### 子 agent 工具注册

- `SubagentManager._run_subagent` 在现有 PR3 逻辑上追加：**不**再注册 `DelegateTaskTool`（旧 SpawnTool）
- 其余所有 tool 保持现状（File / Web / Message / AskUser / BlackboardWrite/Read / Skill 等）

### 新增 Tool 类

- `secbot/agent/tools/plan.py::WritePlanTool`
  - schema：`{steps: list[{title: string, detail?: string}]}`，required=["steps"]
  - `execute()`：调 `bus.publish_agent_event({type: "orchestrator_plan", steps, timestamp})`，返回 `"Plan recorded: N steps"`
  - 事件广播通道复用现有 `broadcast_agent_event` 接口
- `secbot/agent/tools/approval.py::RequestApprovalTool`
  - schema：`{title: string, detail?: string, options?: list[string]}`，required=["title"]
  - `execute()`：raise `AskUserInterrupt(question=formatted, options=options or ["Approve", "Deny"])`
  - 前端根据 `tool_name="request_approval"` 切换成审批卡片样式（区别 `ask_user`）

### 重命名

- `SpawnTool.name` 直接改为 `"delegate_task"`；同时在 `tool_parameters` 里调整 description 更观感
- `BlackboardReadTool.name` 直接改为 `"read_blackboard"`
- 所有上游断言 `"spawn"` / `"blackboard_read"` 的测试 / 导出 / 前端键名一次性更新

### orchestrator prompt

- `secbot/agents/orchestrator.py::_HARD_RULES` 新增：
  - "你只有 4 个工具：`delegate_task` / `read_blackboard` / `write_plan` / `request_approval`。其余任何能力用 `delegate_task` 分派给专家 agent。"
  - "纯信息问答可用自然语言直接回复；涉及实时/外部资源/写入写改的需求必须 `delegate_task`。"
- `_WORKING_STYLE` 调整："需要明确计划时调 `write_plan`；需要人工批准时调 `request_approval`。"

### 事件协议

- `orchestrator_plan` 进入 `secbot.bus.events` 的 `AgentEventType`（若有枚举）
- WebUI `useNanobotStream.ts` / `types.ts` 新增 `OrchestratorPlanEvent`
- `MessageBubble.tsx` 增加 plan 卡片渲染
- `RequestApprovalTool` 的前端渲染在已有 `ask_user` 按钮基础上做样式切换（源头识别 `tool_name`）

## Acceptance Criteria

- [ ] 主 loop `AgentLoop.tools.tool_names == ["delegate_task", "read_blackboard", "request_approval", "write_plan"]`（顺序无关）
- [ ] 子 loop `tools.tool_names` 不包含 `"delegate_task"`；仍包含 skill / file / web / blackboard_write 等
- [ ] `WritePlanTool.execute({steps:[{title:"a"},{title:"b"}]})` 返回成功文案并广播一条 `orchestrator_plan` 事件
- [ ] `RequestApprovalTool.execute({title:"run nmap",detail:"..."})` raise `AskUserInterrupt`，`options` 默认 `["Approve","Deny"]`
- [ ] 新 orchestrator prompt 快照包含"你只有 4 个工具"字样
- [ ] provider 集成测试 全部绹（断言迁移到新名）
- [ ] WebUI plan 卡片在收到 `orchestrator_plan` 事件时渲染；request_approval 卡片与普通 ask_user 视觉上可区分
- [ ] 端到端：扫描 `http://111.228.2.47:8080/` 时，主 agent 的 tool_event 只出现这 4 种名字；具体 skill 调用只出现在子 agent 卡片内

## Definition of Done

- 单测：主 loop/子 loop 工具清单、`WritePlanTool` 广播、`RequestApprovalTool` interrupt、SpawnTool/BlackboardReadTool 重命名后的断言
- 测试迁移：`tests/providers/*`、`tests/agent/*`、`tests/channels/*` 中所有 `"spawn"` / `"blackboard_read"` 断言 更新
- 前端：plan 卡片 + approval 卡片 e2e（TypeScript 编译绿）
- Lint（ruff）/ typecheck（mypy）/ pytest 全部绹
- orchestrator prompt 更新后 `tests/agent/test_orchestrator_prompt.py` 快照同步
- docs：新建 `.trellis/spec/backend/orchestrator-tool-whitelist.md` 记录设计决策

## Decision (ADR-lite)

**Context** orchestrator 与子 agent 共享同一套 default tools，导致主 loop 可以直接 exec / skill / file write，越权路径没有契约级别的保护；调度时名字混用（spawn 不像编排动词），视觉上难以辨认主/子 agent。

**Decision** 把主 agent 工具面严格收敛到 4 个编排类 tool：`delegate_task` / `read_blackboard` / `write_plan` / `request_approval`；子 agent 也禁止递归 `delegate_task`。重命名采用破坏性升级，一次性迁移下游断言。

**Consequences**
- 优点：主 agent 行为约束为"规划 + 派发 + 读板 + 求批"，攻击面最小；名字语义与编排对齐
- 风险：一次性迁移测试改动面大（预估 40–60 个 test 需更新）；早期聊天记录里的旧 tool name 无法重新回放
- 缓解：迁移集中在一个 PR、一条 sed 批改 + 手动校对；旧会话重放不在 MVP 范围

## Implementation Plan (small PRs)

### PR1：主 agent 工具白名单 + 重命名（后端）
- SpawnTool.name 改 `delegate_task`；BlackboardReadTool.name 改 `read_blackboard`
- 新建 `WritePlanTool`、`RequestApprovalTool`
- `AgentLoop` 区分主/子 loop，`_register_default_tools` 分流
- `SubagentManager._run_subagent` 不再注册 `DelegateTaskTool`
- orchestrator prompt 更新 （Hard rules + Working style）
- 单测：主 loop tool 清单、WritePlanTool、RequestApprovalTool、SubagentManager no-spawn

### PR2：上游测试迁移（后端）
- `tests/providers/*` 中断言 `"spawn"` / `"blackboard_read"` 的用例批改
- `tests/agent/test_orchestrator_prompt.py` 快照更新
- `tests/channels/test_ws_activity_event.py` 等任何流式工具名断言更新
- 目标：`pytest` 全绿（忽略 pre-existing 2 个回归与本任务无关的失败）

### PR3：前端渲染（WebUI）
- `webui/src/lib/types.ts` 新增 `OrchestratorPlanEvent`、扩展 tool_name 枚举
- `useNanobotStream.ts` 监听 `orchestrator_plan` 事件并写入 trace
- `MessageBubble.tsx` 新增 plan 卡片 + approval 卡片样式分支
- TypeScript 编译绿

### PR4：文档 + 端到端
- `.trellis/spec/backend/orchestrator-tool-whitelist.md` 新建
- `docs/my-tool.md` 增补一节
- 手动验证：`http://111.228.2.47:8080/` 扫描，前端确认 plan 卡片 / approval 卡片 / delegate 子 agent 卡 / blackboard 卡 同时展示

## Out of Scope

- 改造子 agent 的工具面（PR3 / 动态子智能体编排的任务）
- 并行调度（`05-08-dynamic-subagent-orchestration`）
- `request_approval` 的 timeout / 审计日志 / 角色级审批（未来升级到 HighRiskGate 模型）
- `write_plan` 的历史 / diff / 甘特图（未来）
- PR4：`ExecToolConfig.enable=False` 全局默认（`05-11-security-tools-as-tools` PR4）
- 最早版本会话历史的向后兼容（旧 `"spawn"` tool_call 无法重新回放）

## Technical Notes

### 关键注入点

- [`secbot/agent/loop.py::_register_default_tools`](file:///Users/shan/Downloads/nanobot/secbot/agent/loop.py) — 主 loop 工具注册入口；需要"主 loop vs 子 loop"分支
- [`secbot/agent/subagent.py::SubagentManager._run_subagent`](file:///Users/shan/Downloads/nanobot/secbot/agent/subagent.py) — 子 loop 工具注册入口；保留现有逻辑
- [`secbot/agents/orchestrator.py::render_orchestrator_prompt`](file:///Users/shan/Downloads/nanobot/secbot/agents/orchestrator.py) — 需要更新 "Hard rules" + "Working style"
- [`secbot/agent/tools/spawn.py`](file:///Users/shan/Downloads/nanobot/secbot/agent/tools/spawn.py) — 将名字对外暴露为 `delegate_task`（或新增 `DelegateTaskTool` 包装）
- [`secbot/agent/tools/blackboard.py`](file:///Users/shan/Downloads/nanobot/secbot/agent/tools/blackboard.py) — 将 `blackboard_read` 对外暴露为 `read_blackboard`
- `secbot/agent/tools/plan.py` — 新建 WritePlanTool
- `secbot/agent/tools/approval.py` — 新建 RequestApprovalTool（或 `ask.py` 里扩）

### 事件协议候选

- `write_plan` → 新 agent_event 类型 `plan_step` 或直接复用现有 `plan` part；前端 MessageBubble 已有 plan 渲染可扩展
- `request_approval` → 复用 HighRiskGate 的 `confirm_request` / `confirm_approve` / `confirm_deny` / `confirm_timeout` 四类事件，但 source 标记为 "orchestrator" 而非 "skill"

### 关键约束

- 不能把子 agent 的能力一起砍掉 —— 子 agent 必须仍能访问 skill / file / web / blackboard_write
- 不再做 alias；迁移集中在 PR2 一批改完（预计 40–60 个 test）
- Hook / runner 层对"plan part"已有原生支持，`WritePlanTool` 需避免与其重复广播（选用新事件类型 `orchestrator_plan`，不踩 `plan` part 通道）
- `AskUserInterrupt` 在 `RequestApprovalTool` 复用时，前端需能从 `tool_name` 分流渲染（而非只识别 interrupt 本身）

### 与其他任务的衔接

- PR4 的 "exec 默认关" —— 本任务让主 agent 根本看不到 exec，完全解决主端面；PR4 仍需做子 agent 全局默认关闭（纵深防御）
- 动态子智能体编排 —— 本任务的 `orchestrator_plan` 事件可作为那边结构化并行 plan 的展示层（底层 schema 均保留扩展位）
- PR3（已完成）的 `spec.scoped_skills` 裁剪 —— 本任务在子 agent 层的唯一动作是下掉 `DelegateTaskTool`，其余均沉淀为 PR3 既定行为
