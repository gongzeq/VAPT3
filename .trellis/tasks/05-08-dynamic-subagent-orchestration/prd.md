# brainstorm: 动态子智能体编排与黑板共享机制

## Goal

增强Orchestrator编排能力，支持动态加载用户自定义智能体、并行调度子智能体、以及通过黑板（Blackboard）模式实现智能体间的上下文共享。同步升级前端，展示编排流程、工具/技能调用信息和黑板发现。

## What I already know

### 现有能力
- Orchestrator已支持YAML定义智能体（零代码扩展），启动时自动注册
- 子智能体执行通过SubagentManager管理，有完整的Hook追踪系统
- 前端已有TraceEntry/ToolEvent结构化渲染，支持agentLabel分组显示
- Skills系统支持用户自定义（workspace/skills优先于内置）
- WebSocket通道已透传tool_events和agent_label

### 现有限制
- **无并行编排**：Orchestrator LLM按顺序调用工具，等待每个智能体完成后才能继续
- **无智能体间通信**：两层架构严格分离，子智能体之间无法共享上下文
- **无热重载**：智能体/技能仅启动时加载一次
- **上下文通过摘要传递**：精度丢失、token浪费

## Assumptions (temporary)

- 并行编排需要在Orchestrator层面实现（非LLM自主并行，而是编排逻辑支持）
- 黑板为内存数据结构，持久化为可选
- 前端通过WebSocket接收黑板更新事件
- 用户注册的智能体格式延续现有YAML schema

## Open Questions

1. ~~**并行调度机制**~~：✅ 已决定 → **LLM规划式并行**（方案A）
2. ~~**黑板数据模型**~~：✅ 已决定 → **自由文本条目**（方案B）—— `{id, agent_name, text, timestamp}`
3. ~~**黑板生命周期**~~：✅ 已决定 → **单次任务级**（方案A）—— 随一次编排任务创建/销毁
4. ~~**前端黑板展示**~~：✅ 已决定 → **内嵌消息流**（方案A）—— 作为特殊TraceEntry插入，醒目卡片样式

## Requirements

### 后端 - 并行编排层
- [ ] Orchestrator LLM输出结构化执行计划（标注哪些智能体可并行）
- [ ] 编排层解析计划，将无依赖智能体同时dispatch为 asyncio.gather
- [ ] 支持“中间决策点”：每批次完成后，LLM基于黑板内容决定下一批
- [ ] 子智能体失败/超时的优雅降级（记录错误到黑板，不阻塞其他并行智能体）

### 后端 - 黑板系统
- [ ] Blackboard数据结构：`{id, agent_name, text, timestamp}`
- [ ] 生命周期：单次编排任务级，任务完成后销毁
- [ ] 子智能体通过专用工具 `blackboard_write(text)` 写入
- [ ] 子智能体通过专用工具 `blackboard_read()` 读取全量条目
- [ ] 并发安全：多个子智能体同时写入无数据竞争（asyncio.Lock或线程安全list）

### 后端 - 智能体注册
- [ ] 用户可注册自定义智能体（延续YAML格式，零代码扩展）
- [ ] 用户可注册自定义Skills（延续现有机制）
- [ ] Orchestrator动态加载当前智能体列表（启动时扫描）

### 后端 - 智能体配置 API
- [ ] GET /api/agents —— 列出所有已注册智能体
- [ ] GET /api/agents/:name —— 获取智能体详情（YAML内容 + 系统提示）
- [ ] POST /api/agents —— 创建新智能体（写入YAML文件）
- [ ] PUT /api/agents/:name —— 更新智能体配置
- [ ] DELETE /api/agents/:name —— 删除智能体
- [ ] GET /api/skills —— 列出所有已注册技能
- [ ] GET /api/skills/:name —— 获取技能详情（SKILL.md内容）
- [ ] POST /api/skills —— 创建新技能
- [ ] PUT /api/skills/:name —— 更新技能内容
- [ ] DELETE /api/skills/:name —— 删除技能

### 前端 - 会话页面
- [ ] 展示Orchestrator编排输出（规划、决策过程）
- [ ] 展示子智能体并行执行状态（运行中/完成/失败）
- [ ] 展示子智能体调用的工具和技能信息（已部分实现，增强并行场景）
- [ ] 黑板发现以醒目卡片形式内嵌消息流（kind: "blackboard"）
- [ ] 失败智能体显示错误状态标识

### 前端 - 智能体配置管理页
- [ ] 智能体列表页：展示所有已注册智能体（名称、描述、scoped_skills、状态）
- [ ] 智能体新增/编辑：表单或YAML代码编辑器，支持在线编写智能体配置
- [ ] 智能体删除：确认弹窗 + 删除YAML文件
- [ ] 智能体详情：查看系统提示、技能绑定、I/O Schema
- [ ] Skills列表：展示所有已注册技能（名称、描述、依赖、所属智能体）
- [ ] Skills新增/编辑：Markdown编辑器，支持在线编写SKILL.md
- [ ] 操作后提示“需重启生效”（配合当前无热重载的设计）

## Acceptance Criteria

- [ ] Orchestrator LLM输出包含并行标注的执行计划，编排层正确解析并并行执行
- [ ] 多个无依赖的子智能体可并行执行（实际并发，非顺序）
- [ ] 子智能体A写入黑板的数据，子智能体B可实时读取
- [ ] 批次完成后Orchestrator可基于黑板内容做下一步决策
- [ ] 子智能体失败时不阻塞其他并行智能体，错误记录到黑板
- [ ] 前端实时显示各子智能体执行状态和工具调用
- [ ] 黑板发现以醒目卡片形式呈现在会话消息流中
- [ ] 用户新增YAML智能体后重启即可被Orchestrator识别并调用
- [ ] 前端智能体配置页支持完整CRUD（新增/查看/编辑/删除智能体和Skills）

## Definition of Done (team quality bar)

- Tests added/updated (unit/integration where appropriate)
- Lint / typecheck / CI green
- Docs/notes updated if behavior changes
- Rollout/rollback considered if risky

## Out of Scope (explicit)

- 热重载智能体/技能（仅启动时加载，不做runtime热更新）
- 黑板持久化（不写入数据库/文件，仅内存）
- 智能体间直接调用（保持两层架构，仅通过黑板共享）
- 细粒度权限控制（所有智能体共享同一黑板，无读写权限区分）
- 现有spawn子智能体的改造（它们保持独立后台任务模式）

## Technical Notes

### 关键文件
- 编排逻辑：`secbot/agents/orchestrator.py`、`secbot/agents/registry.py`
- 子智能体：`secbot/agent/subagent.py`、`secbot/agent/loop.py`
- 技能系统：`secbot/agent/skills.py`
- 执行循环：`secbot/agent/runner.py`、`secbot/agent/hook.py`
- 前端类型：`webui/src/lib/types.ts`、`webui/src/hooks/useNanobotStream.ts`
- 前端渲染：`webui/src/components/MessageBubble.tsx`
- 通道实现：`secbot/channels/websocket.py`

### 架构约束
- 当前两层架构：Orchestrator → Expert Agents（每个是独立LLM loop）
- 子智能体通过SubagentManager.spawn()创建，是asyncio.Task
- Hook系统提供完整的生命周期回调（before_iteration, on_stream, before_execute_tools, after_iteration）
