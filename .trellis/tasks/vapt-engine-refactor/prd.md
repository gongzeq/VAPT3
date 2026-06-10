# PRD: VAPT 编排引擎重构 — 从反应式 Agent 到宿主态阶段图调度

## Problem Statement

secbot 的 VAPT 扫描流水线（asset_discovery → port_scan → 服务分流 → vuln_scan → verification → report）是一条高度确定的阶段链，但当前实现将整个流程放在 Orchestrator LLM 的反应式循环中执行。这导致：

1. **每推进一步都要重复读取规则、判断下一步、读状态、构造子任务 prompt**，token 成本与工具调用次数被同步放大
2. **`read_blackboard` / `read_assets` / `read_file` 反复出现在工具调用中**，状态复用靠"读文本再回填 prompt"
3. **缺少去重、预算、无增量终止机制**，相似参数的工具调用容易重复（如轻微改写参数但本质相同的调用）
4. **工具面过宽**，LLM 即使没有调用某工具，也为工具 schema、描述和额外系统提示付了 token
5. **`planner.py` 已定义结构化 JSON 执行计划 + 并行 batch 的抽象，但 `orchestrator.py` 仍然是长提示词和自然语言 hard rules**，两者之间存在"契约错位"

行业最佳实践（Anthropic、LangGraph、OpenAI reasoning best practices）明确指出：预定义、顺序明确、成功标准可验证的任务，更适合 workflow 而非高自治 agent。

## Solution

将 VAPT 编排从"LLM 反应式循环"重构为"**宿主态阶段图调度 + LLM 规划**"架构：

- **Orchestrator 转型为 Plan Compiler**：LLM 只输出轻量阶段意图 JSON（哪些阶段、什么参数、是否跳过），不再每轮都做全局决策
- **新增 Plan Expander**：宿主态代码将 LLM 输出展开为完整 ExecutionGraph（自动填充依赖、预算、去重键等）
- **新增 Phase Graph Scheduler**：按 DAG 确定性调度 PlanNode，复用 WorkflowRunner 步骤执行逻辑
- **新增 Tool Gateway**：独立模块，承担参数规范化、语义去重、同飞合流、预算检查、结果缓存
- **VAPT 主链硬编码**：包含服务分流路由（Web/非 Web 分支），由 Plan Expander 用确定性规则判定
- **AgentLoop 保留为 Session Runtime**：会话管理、Provider 热重载、AutoCompact 等用户侧关注点不变
- **State View 为只读物化层**：Blackboard + AssetFeed + CMDB 保留为写入端，不改现有写入逻辑

LLM 只在三类场景出手：**初始规划、异常重规划、Expert Agent 执行**。

## User Stories

1. As a 安全工程师, I want 提交一个 CIDR 目标后系统自动执行完整 VAPT 流水线, so that 我不需要手动指定每个扫描阶段
2. As a 安全工程师, I want 系统根据 port_scan 发现的服务类型自动分流（Web 服务走 crawl→dirscan→web_vuln_scan，非 Web 服务走 weak_password + version_vuln_match）, so that 扫描路径更精准
3. As a 安全工程师, I want 在 Web 分支中自动执行目录爆破（ffuf-dir-fuzz）, so that 不遗漏隐藏路径
4. As a 安全工程师, I want 自动化漏洞扫描（fscan-vuln-scan）可以与 Web/非 Web 分支并行执行, so that 整体扫描时间缩短
5. As a 安全工程师, I want 漏洞验证阶段由 LLM 辅助（Expert Agent 调 skill + 知识库复现漏洞、剔除误报）, so that 最终报告中的漏洞都是经过验证的
6. As a 安全工程师, I want 在提交"只测弱口令"的请求时，Plan Compiler 自动跳过其他阶段, so that 扫描更高效
7. As a 安全工程师, I want 高危操作（如 sqlmap、hydra）在 PlanNode 分发前触发确认, so that 我可以在阶段边界而非工具调用中途做决策
8. As a 安全工程师, I want 系统自动去重相同参数的工具调用, so that 不会因为 LLM 重复决策而浪费时间和 token
9. As a 安全工程师, I want 系统在同飞合流机制下，对正在执行的相同工具调用自动 join, so that 并行执行时不会重复发起相同任务
10. As a 安全工程师, I want 每个 PlanNode 执行前自动物化 State View, so that Expert Agent 不需要手动调用 read_blackboard / read_assets / read_file
11. As a 安全工程师, I want 前端事件流（agent_event、tool_call、high_risk_confirm）与旧架构行为一致, so that 用户体验不受影响
12. As a 安全工程师, I want 用户中途消息仍由 AgentLoop 处理, so that 扫描过程中我可以随时与系统交互
13. As a 平台开发者, I want Tool Gateway 先以 monitor-only 模式上线, so that 我可以在不拦截任何调用的情况下收集真实重复调用数据
14. As a 平台开发者, I want Tool Gateway 后续切入 enforcement 模式, so that 真实拦截去重和预算控制
15. As a 平台开发者, I want Plan Compiler 输出最小化 JSON, so that LLM 输出格式错误概率最低
16. As a 平台开发者, I want Plan Expander 在宿主态自动填充依赖、预算、去重键等字段, so that LLM 不需要关心运行时细节
17. As a 平台开发者, I want Plan Compiler 输出格式不稳定时，Plan Expander 宽容解析 + 默认模板兜底, so that 系统不会因单次 LLM 输出异常而崩溃
18. As a 平台开发者, I want Phase Graph Scheduler 复用 WorkflowRunner 的条件求值、参数插值、重试逻辑, so that 不重复造轮子
19. As a 平台开发者, I want AgentRegistry YAML 支持新策略字段（tool_bundle、budget_class、dedupe_scope、state_contract、batch_capable）, so that 每个 Expert Agent 的运行时策略可从配置驱动
20. As a 平台开发者, I want 新架构分两个 Phase 交付（Phase 1 执行引擎重构 + Phase 2 可观测性与优化）, so that 迁移风险可控
21. As a 平台开发者, I want Phase 1 内部渐进验收（5 个 Step）, so that 每个子模块可独立验证
22. As a 平台开发者, I want 现有 Expert Agent YAML 和 Skill 框架不做破坏性修改, so that 迁移期间新旧架构可兼容

## Implementation Decisions

### 架构决策

- **Orchestrator → Plan Compiler 转型**：现有 `orchestrator.py` 的 11 条 hard rules 和长 prompt 被替换为轻量 Plan Compiler prompt。LLM 只输出阶段意图（handler + args + skip），不再做全局编排决策。对应 ADR: `docs/adr/0002-vapt-phase-graph-scheduler.md`

- **Phase Graph Scheduler 复用 WorkflowRunner**：新模块 `secbot/scheduler/` 复用现有 `WorkflowRunner` 的步骤执行、条件求值（`secbot/workflow/expr.py`）、参数插值、重试/on_error 逻辑。不复用 `WorkflowService` 的持久化和 API 层。

- **Tool Gateway 作为独立模块**：`secbot/gateway/`，由 Phase Graph Scheduler 直接调用。现有 `SubagentManager._endpoint_inflight` 互斥逻辑迁移到 Tool Gateway。

- **AgentLoop 保留为 Session Runtime**：会话管理（SessionManager）、Provider 热重载、AutoCompact、用户消息消费、斜杠命令路由保留。编排职责（子智能体调度、阶段顺序控制、报告兜底）移交给 Scheduler。

### 模块设计

#### Tool Gateway (`secbot/gateway/`)

承担五大职责：
- **参数规范化**：URL/host/port/param 归一化，生成 canonicalize key
- **语义去重**：相同 canonicalize key 的调用只执行一次
- **同飞合流**：相同 intent 正在执行时，后续请求 join 等待结果
- **预算检查**：per-node 和 per-scan 级别的 token/调用次数限制（Phase 2 精细化）
- **结果缓存**：相同参数的短期结果复用

#### Plan Compiler (`secbot/agents/planner.py` 升级)

LLM 输出格式最小化：
```json
{
  "reasoning": "...",
  "phases": [
    {"handler": "asset_discovery", "args": {"target": "10.0.0.0/24"}},
    {"handler": "port_scan", "args": {}},
    {"handler": "crawl", "args": {}},
    {"handler": "dirscan", "args": {}},
    {"handler": "web_vuln_scan", "args": {"top_k": 10}},
    {"handler": "weak_password", "args": {}, "skip": true, "skip_reason": "无 SSH/DB 服务"},
    {"handler": "automated_vuln_scan", "args": {}},
    {"handler": "verification", "args": {}},
    {"handler": "report", "args": {}}
  ]
}
```

容错策略：Plan Expander 宽容解析 + VAPT 默认模板兜底。LLM 输出异常时 fallback 到全阶段默认模板。

#### Plan Expander (`secbot/scheduler/expander.py`)

宿主态代码，将 LLM 轻量输出展开为完整 ExecutionGraph：
- 自动推导 `depends_on`（从 VAPT 主链硬编码顺序 + 分流规则）
- 自动推导 `dedupe_key`（从 handler + target 拼接）
- 自动推导 `budget_class`（从 AgentRegistry 的 ExpertAgentSpec 读取）
- 自动推导 `success_criteria`、`on_no_delta`、`on_error`、`state_inputs`
- 服务分流路由：port_scan 后根据 State View 中的服务类型插入条件分支

#### Phase Graph Scheduler (`secbot/scheduler/`)

- 接收 ExecutionGraph，按依赖关系调度 ready 节点
- 为每个节点物化 State View
- 在分发前检查 HighRiskGate（PlanNode 级别）
- 复用 WorkflowRunner 的条件求值、参数插值、重试逻辑
- 阶段边界评估（是否需要 replan / 跳过后续）

#### State View (`secbot/scheduler/state_view.py`)

只读物化层，每个 PlanNode 执行前从 Blackboard + AssetFeed + CMDB 组装类型化视图。不改现有写入端逻辑。

#### VAPT 新流程（硬编码在 Plan Expander 中）

```
asset_discovery（子域名/IP段/云资产/存活探测）
  ↓
port_scan（全端口/快速扫描 + 服务指纹识别）
  ↓
[服务分流路由 — Plan Expander 确定性规则]
  ├─ Web 服务 (HTTP/HTTPS):
  │    crawl (katana-crawl-web)
  │    → dirscan (ffuf-dir-fuzz)
  │    → web_vuln_scan (nuclei-template-scan)
  │
  └─ 非 Web 服务 (SSH/DB/RDP/邮件等):
       weak_password (hydra-bruteforce)
       + version_vuln_match（可并行）
  ↓
结果汇总
  ↓
automated_vuln_scan (fscan-vuln-scan，可与上一步并行)
  ↓
verification（LLM 辅助验证，Expert Agent 调 skill + 知识库复现漏洞、剔除误报）
  ↓
report (report-html)
```

分流规则：Plan Expander 在 port_scan 完成后用确定性规则判定（HTTP/HTTPS → Web 分支，其他 → 非 Web 分支，两者都有 → 并行）。LLM 不参与分流决策。

#### HighRiskGate 迁移

从 `SkillTool.execute()` 内部提升到 PlanNode 分发前：
1. Scheduler 在分发 PlanNode 前，查询 registry 获取该 Expert Agent 的 scoped_skills
2. 如果任一 skill 的 `risk_level == "critical"` → 触发 HighRiskGate 确认
3. 确认粒度为 PlanNode 级别（不是 Skill 级别）
4. 复用现有 `ctx.confirm()` 机制和 WebSocket `high_risk_confirm` 事件

#### AgentRegistry 新增字段

`ExpertAgentSpec` 新增策略字段：
- `tool_bundle`: minimal / bounded / extended（工具面宽度）
- `budget_class`: cheap / normal / expensive（预算级别）
- `dedupe_scope`: phase_target / endpoint / session（去重作用域）
- `state_contract`: 该 agent 需要哪些 state 切片
- `batch_capable`: 是否支持批处理

对应 YAML 配置驱动。

### 不变组件

| 组件 | 说明 |
|---|---|
| AgentLoop | 保留为 Session Runtime |
| SubagentManager | 保留 Expert Agent 生命周期管理，endpoint 互斥迁移到 Tool Gateway |
| AgentRegistry | 保留 YAML 注册表，新增策略字段 |
| CMDB / Blackboard / AssetFeed | 保留为写入端，不改现有写入逻辑 |
| Skills / SkillTool | 保留现有技能框架，HighRiskGate 触发源迁移 |
| 模型分配 | 不改动，保持现有 per-agent `model` 覆盖机制 |

## Testing Decisions

### 测试原则

- **只测外部行为，不测实现细节**：测试 Tool Gateway 的去重/缓存/合流行为，不测内部数据结构
- **复用现有测试基础设施**：`tests/agent/` 和 `tests/workflow/` 已有成熟的 mock/fixture 模式
- **每个新模块配套单元测试**：gateway/、scheduler/ 各自有独立测试目录

### 测试模块

#### `tests/gateway/` — Tool Gateway 单元测试
- 参数规范化测试（URL 归一化、端口排序、参数排序）
- 语义去重测试（相同 key 只执行一次）
- 同飞合流测试（并发相同 intent 的 join 行为）
- 结果缓存测试（TTL 过期、命中/未命中）
- 先例：`tests/agent/test_subagent_isolation.py`

#### `tests/scheduler/` — Scheduler 单元测试
- ExecutionGraph 构建与 DAG 校验
- Plan Expander 服务分流规则（HTTP → Web 分支，非 HTTP → 非 Web 分支，混合 → 并行）
- Plan Expander skip 逻辑
- Plan Compiler 输出容错（格式异常 → 默认模板兜底）
- State View 物化（从 mock CMDB/Blackboard/AssetFeed 组装）
- 先例：`tests/workflow/test_runner.py`

#### `tests/e2e/` — 端到端集成测试
- 完整 VAPT 流水线（从输入目标到报告生成）
- Web-only 目标分流
- 非 Web-only 目标分流
- 阶段跳过场景
- HighRiskGate PlanNode 级确认
- 前端事件流一致性
- 先例：`scripts/test_scan_e2e.py`

### 验收标准（Phase 1 渐进验收）

**Step 1.1** — Tool Gateway monitor-only：旁路记录所有工具调用的 canonicalize key，不拦截，输出统计日志

**Step 1.2** — Tool Gateway enforcement：切入正式调用链路，重复调用被拦截，现有 VAPT 扫描功能不受影响

**Step 1.3** — Plan Compiler + Plan Expander：Plan Compiler 输出轻量 JSON，Expander 展开为合法 ExecutionGraph，服务分流和 skip 逻辑正确

**Step 1.4** — Phase Graph Scheduler + AgentLoop 拆分：完整 VAPT 扫描全链路由 Scheduler 驱动，前端事件流行为一致，HighRiskGate 在 PlanNode 分发前正确触发

**Step 1.5** — 端到端回归：所有现有测试通过，新 E2E 测试覆盖完整流水线、Web-only、非 Web-only、阶段跳过

## Out of Scope

- **Phase 2 优化项**：Evaluator Gate（阶段边界质量门）、Budget Guard 精细化调参、Prompt caching、Trace replay 对比测试框架 — 这些在 Phase 2 交付
- **模型路由 / Planner-Doer 模型分离**：保持现有 per-agent model 覆盖机制不变
- **外部框架集成**（LangGraph / AutoGen 等）：明确不引入，复用现有 WorkflowRunner + SubagentManager
- **Blackboard / AssetFeed / CMDB 写入逻辑改造**：写入端不变，State View 只做只读投影
- **非 VAPT 场景**（如 White-Box Assessment、Public Asset Discovery）：这些流水线有独立生命周期，不在本次重构范围内
- **GoT / ToT 等复杂推理图**：不在主链中使用，仅限域启用
- **批量工具融合（batch_tool）**：Plan Expander 的 `batch_capable` 字段预留，但批处理融合在 Phase 2 实现

## Further Notes

- **ADR 记录**：`docs/adr/0002-vapt-phase-graph-scheduler.md` 记录了从反应式 Agent 到宿主态阶段图调度的核心架构决策
- **术语更新**：`CONTEXT.md` 已新增/变更 7 个术语（Orchestrator、ExecutionGraph、PlanNode、Phase Graph Scheduler、Tool Gateway、State View、Vulnerability Verification）+ 6 条关系约束
- **迁移兼容性**：Phase 1 期间新旧架构需并存。Tool Gateway 的 monitor-only → enforcement 渐进切换是关键风险缓解措施
- **风险分析**：
  - Plan Compiler LLM 输出格式不稳定 → Plan Expander 宽容解析 + 默认模板兜底
  - Tool Gateway 去重误杀 → 先 monitor-only 收集数据
  - 前端事件流格式变化 → Scheduler 复用现有 broadcast_fn 和 agent_event 协议
  - 服务分流规则覆盖不全 → Plan Expander 对未知服务类型默认走非 Web 分支
