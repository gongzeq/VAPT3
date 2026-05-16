# 工作流自定义子界面（混合编排：工具 / 脚本 / 子智能体 / LLM + 定时调度）

## Goal

在 WebUI 中新增一个“工作流 Workflow”子页面，沿用 `prototypes/02-home.html` ~ `05-settings.html` 的海蓝玻璃拟态视觉风格。
工作流由有序步骤组成，**每一步可自由选择下列 4 种执行体之一**，并可配条件分支 / 重试 / 失败策略：

| kind | 场景 | 执行方式 |
|------|------|---------|
| `tool`   | 读日志 / 发 HTTP / 查 CMDB… | 调用 `secbot/agent/tools/*` 已注册工具，纯程序化 |
| `script` | 自定义脚本（python inline / shell） | 包装 `shell` / sandbox 工具执行，纯程序化 |
| `agent`  | 复杂专家流程（`port_scan` / `report` 等 YAML 智能体）| 子智能体内部自驱，LLM + 工具混合 |
| `llm`    | 对中间数据做语义分析 / 提炼 / 分类 | 直接走 `providers/*.chat`，自定义 prompt + 模型 + 温度 |

用户可把整个工作流发布为定时任务（一次性 / 间隔 / cron 表达式），由后端 `CronService` 按计划触发 `WorkflowRunner` 执行。

## Motivating Examples

- **内网扫描**：`agent:asset_discovery` → `agent:port_scan` → `agent:weak_password` → `cond: high_risk>0` → `agent:report`
- **日志异常分析**（新增，展示“脚本先筛 + 有问题再入 LLM”链路）：
  1. `tool:file_read`   读取 `${inputs.log_path}`
  2. `script:python`    跑自定义筛选脚本，输出 `{"errors": N, "samples": […]}`
  3. `cond: ${steps.s2.result.errors} == 0` → **全部正常 `stop` 早退**
  4. `llm:chat`         将 `samples` 嗂给 LLM，system prompt 为“SRE 视角分析以下错误日志…”，输出诊断结论
  5. `tool:message`     把结论推送到告警渠道
- **邮箱巡检**：`tool:http_get` 检 MX → `llm:chat` 判断钓鱼特征 → `cond` → `agent:report`

## What I already know

- **视觉系统（Phase 0 原型已定型）**
  - 位于 `.trellis/tasks/05-09-uiux-template-refactor/prototypes/`，使用 Tailwind CDN + Lucide + Inter/Noto Sans SC/JetBrains Mono
  - 全局设计令牌：主色 `hsl(210 100% 56%)`、`gradient-card`、`bg-glass`、`hover-lift`、`pulse-glow`、`fade-in-up`
  - Sticky navbar (h-16) + `max-w-[1600px]` 三栏布局是主要 Shell 模板
  - 严重度色条规范（CRITICAL 红 / HIGH/MEDIUM 橙 / LOW/INFO 蓝 / SAFE 绿）
- **WebUI 代码**
  - `webui/src/App.tsx` 已使用 react-router-dom，路由注册点 `/`、`/dashboard`、`/tasks/:id`、`/settings`
  - Navbar 需追加第四栏“工作流”
  - Provider / Config 同步已就绪（可复用 provider list API 给 `llm` 步骤做模型下拉）
- **后端能力**
  - `secbot/cron/service.py` 调度完备；`CronPayload.kind="agent_turn"` 仅支持“消息进入 orchestrator”一条路
  - 源码可直接复用：`secbot/agent/tools/*`（ask / file_state / filesystem / mcp / message / notebook / sandbox / search / self / shell / spawn / web 等）、`secbot/agents/*.yaml`（5 个专家智能体）、`secbot/providers/*`（6 家 LLM provider）
- **当前缺口**
  - 后端无“工作流”第一类实体；cron 触发只能走 agent_turn 一条路
  - 需新增 `WorkflowRunner`，能按 step.kind 分派到 4 种执行体（tool / script / agent / llm），不再强制走 orchestrator
  - 前端无任何 workflow 组件 / 路由 / API 客户端

## Decisions（已固化）

- D1 执行模型：**后端 `WorkflowRunner` 程序化驱动**（非 LLM 编译）；LLM 只在 `kind=llm` 或 `kind=agent` 的 step 内出现
- D2 编辑器形态：**线性步骤列表**（MVP 不做节点+连线画布）
- D3 调度入口：**详情页 4 Tab 内嵌 + 顶栏新增「工作流」一级菜单**
- D4 MVP 范围：核心闭环 + 模板库 + 结果引用 + 条件分支 + 工作流级 inputs；不含 DAG 并行 / 跨租户
- D5 cron 集成：不改 `CronPayload` 结构，通过 `message` 前缀 `__workflow__:<wf_id>:<inputs_json>` 派发到 `WorkflowRunner`
- D6 `WorkflowRunner` 内部统一 4 种 executor 的返回契约：`{status, output, error, durationMs}`，便于 `${steps.<id>.result.*}` 结果引用跨 kind 生效

## Requirements

- [R1] 新增路由 `/workflows` 与 `/workflows/:id`，复用 Shell/Navbar；顶栏追加一级"工作流"菜单
- [R2] `/workflows` 列表页：已保存工作流 + 运行状态 + 下次调度时间；支持搜索 / 标签过滤 / 模板库
- [R3] `/workflows/:id` 详情页：4 Tab（基本信息 / 步骤 / 调度 / 运行记录），步骤编排器支持 4 种 kind
- [R4] 工作流数据模型（后端）：
  - `Workflow { id, name, description, tags, inputs[], steps[], scheduleRef, createdAtMs, updatedAtMs }`
  - `WorkflowInput { name, label, type, required, default, enumValues }` —— 字段完全自定义（系统不预设）
  - `WorkflowStep { id, name, kind, ref, args, condition?, onError, retry }`，其中 `kind ∈ tool | script | agent | llm`：
    - `kind=tool`：`ref` 为工具名（`secbot/agent/tools/*` 中已注册）；`args` 按工具 JSON Schema 驱动 UI
    - `kind=script`：`ref ∈ python | shell`；`args = { code, timeoutMs?, env? }`
    - `kind=agent`：`ref` 为 YAML 智能体名（`secbot/agents/*.yaml`）；`args` 为智能体入参
    - `kind=llm`：`ref` 为 provider alias（缺省走 default）；`args = { model?, temperature?, systemPrompt, userPrompt, responseFormat? }`
  - `WorkflowRun { id, workflowId, startedAtMs, finishedAtMs, status, inputs, stepResults, trigger, error }`
- [R5] 新增 REST API：CRUD + `/run` + `/cancel` + `/runs` + `/schedule` + `/_tools` + `/_agents` + `/_providers` + `/_templates`
- [R6] 调度发布：复用 `CronService.add_job`；不新增 `payload.kind`，用 `message` 前缀 `__workflow__:<id>:<inputsJson>` 分派
- [R7] `WorkflowRunner` 内部分派：四种 kind 各有独立 executor，统一返回 `{status, output, error, durationMs}`
- [R8] 模板插值 `${inputs.x}` / `${steps.<id>.result.<jsonpath>}` 对 4 种 kind 统一生效
- [R9] 条件分支 `condition` 表达式受限子集（asteval / ast 白名单），**禁用 `eval`**；可对前面任意 kind 的 `result` 读值判断（例 `${steps.s2.result.errors} == 0`）
- [R10] 视觉与原型一致（`gradient-card` + 脉冲 + 淡入 + 严重度色条），详情头部包含步骤流程图动画栏

## Acceptance Criteria (evolving)

- [ ] 顶栏可从"智能助手 / 大屏分析 / 任务详情"进入第四栏"工作流"，视觉一致
- [ ] 能从模板新建含 ≥2 step + 1 条件分支的工作流，保存后重进页面数据不丢
- [ ] 工作流 inputs 完全自定义（名称 / 类型 / 是否必填由创建者决定，系统不预设任何字段）：
      - 样例A（内网扫描）：`target_ip (cidr)`
      - 样例B（邮箱巡检）：`email_domain (string)`
      - 样例C（日志分析）：`log_path (string)` + `level (enum: error|warn|info)`
- [ ] **混合 kind 端到端样例**：日志分析工作流（`tool:file_read` → `script:python` → `cond` → `llm:chat` → `tool:message`）手动运行完整跑通：
      - 当 `script` 筛选结果 `errors == 0` 时工作流在 `cond` 处 early-stop，不调用 LLM
      - 当 `errors > 0` 时即会将 `samples` 注入 `${steps.s2.result.samples}` 嗂给 `llm:chat`，产出诊断结论后继续派消息
      - `runs` 记录中每个 step 均有独立的 `durationMs` / `status` / `output`
- [ ] 能为工作流设置 cron 表达式（例如每天 09:00），保存后在 `cron/jobs.json` 中出现对应 job
- [ ] 到点后 `WorkflowRunner` 按 step.kind 分派到工具 / 脚本 / 智能体 / LLM，而不再强制走 orchestrator
- [ ] 详情页可查看最近 N 次运行记录（结构化 step 轨迹）；详情头部的步骤流程动画栏能正确反映当前运行位置
- [ ] 列表 / 详情三态齐全（空态 / 加载态 / 错误态），Tab 切换不遗留上一个 Tab 的内容
- [ ] Vitest/pytest 新增的单元测试全部通过

## Definition of Done

- 单测覆盖：workflow CRUD、schedule 对接、4 种 kind 的 executor、模板插值、condition 求值、cron 集成
- 前端 lint + typecheck + build 通过
- 后端 ruff / pytest 通过
- `docs/workflow.md` 涵盖至少 2 个样例（扫描类 + 日志分析类）
- 回滚：feature flag `VITE_WORKFLOW_BUILDER=false` 隐藏入口

## Out of Scope (explicit)

- 全功能可视化 DAG（并行 / 循环 / 聚合）—— 后续迭代
- 跨租户 / 权限模型 —— 当前管控台是单租户
- 工作流市场 / 导入导出 YAML —— 非 MVP
- 自定义 LLM function-calling schema（用 `kind=agent` 封装更合适）
- `kind=script` 的沙箱隔离加固（复用现有 `shell`/sandbox 工具，独立容器化执行留给后续）

## Technical Notes

- 关键参考文件
  - 原型：`.trellis/tasks/05-09-uiux-template-refactor/prototypes/{02-home,03-dashboard,04-task-detail,05-settings}.html`
  - 后端：`secbot/cron/service.py`、`secbot/cron/types.py`、`secbot/agent/tools/*`、`secbot/agents/*.yaml`、`secbot/providers/factory.py`
  - 前端：`webui/src/App.tsx`、`webui/src/components/{Navbar,Shell}.tsx`、`webui/src/pages/*.tsx`
- 四种 kind 的调用接入点
  - `tool`：`secbot/agent/tools/registry.py::get_tool(ref).run(**args)`
  - `script`：包装为 `shell` 工具调用（`python -c` / bash），对重管道 stdout/stderr 并设 `timeoutMs`
  - `agent`：`secbot/agents/registry.py::get_agent(ref).run(args)`（YAML 智能体）
  - `llm`：`providers/factory.create(ref or default).chat(system + user, model=, temperature=)`
- 约束
  - 不引入新 scheduler / 队列，复用 `CronService`
  - 遵循现有 feature flag 习惯 `VITE_*_ENABLED`
  - API 响应 key 用 camelCase（参考 cron service 序列化）

## Research References

（待 Phase 1.2 并行拉起 `trellis-research` 子智能体填充）

- research/workflow-editor-patterns.md — GitHub Actions / n8n / Temporal Web 等交互范式调研
- research/workflow-data-model.md — step 模型与执行语义选型
- research/cron-payload-extension.md — 是否新增 `payload.kind="workflow"` 的权衡
- research/mixed-kind-executor.md — tool / script / agent / llm 四种执行体统一返回值与错误语义
