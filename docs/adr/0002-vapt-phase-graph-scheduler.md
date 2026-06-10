# ADR 0002: VAPT 编排从反应式 Agent 迁移到宿主态阶段图调度

## 状态

Accepted

## 背景

secbot 的 VAPT 扫描主链（asset_discovery → port_scan → 服务分流 → vuln_scan → verification → report）是一条高度确定的阶段链。原架构将整个流程放在 Orchestrator LLM 的反应式循环中执行，导致：

1. 每推进一步都要重复读取规则、判断下一步、读状态、构造子任务 prompt
2. `read_blackboard` / `read_assets` / `read_file` 反复出现在工具调用中
3. 缺少去重、预算、无增量终止机制
4. token 成本与工具调用次数被同步放大

行业最佳实践（Anthropic、LangGraph、OpenAI reasoning best practices）明确指出：预定义、顺序明确、成功标准可验证的任务，更适合 workflow 而非高自治 agent。

## 决策

将 VAPT 编排架构从"LLM 反应式循环"重构为"宿主态阶段图调度 + LLM 规划"：

- **Orchestrator 转型为 Plan Compiler**：LLM 只输出轻量阶段意图 JSON（哪些阶段、什么参数、是否跳过），不再每轮都做全局决策
- **新增 Plan Expander**：宿主态代码将 LLM 输出展开为完整 ExecutionGraph（自动填充依赖、预算、去重键等）
- **新增 Phase Graph Scheduler**：按 DAG 确定性调度 PlanNode，复用 WorkflowRunner 步骤执行逻辑
- **新增 Tool Gateway**：独立模块，承担参数规范化、语义去重、同飞合流、预算检查、结果缓存
- **VAPT 主链硬编码**：服务分流路由由 Plan Expander 用确定性规则判定（HTTP → Web 分支，非 HTTP → 非 Web 分支）
- **AgentLoop 保留为 Session Runtime**：会话管理、Provider 热重载、AutoCompact 等用户侧关注点不变
- **State View 为只读物化层**：Blackboard + AssetFeed + CMDB 保留为写入端

## 后果

**正面**：
- LLM 参与从"每轮全局决策"缩减为"初始规划 + 异常重规划 + Expert Agent 执行"
- 工具调用去重和预算控制从 prompt 规则下沉到宿主态代码，可靠且可测试
- VAPT 主链不再依赖 LLM 理解正确顺序，消除"模型忘了跑报告"类问题
- PlanNode 级 HighRiskGate 在阶段边界确认，不在工具调用中途打断

**负面**：
- 引入多个新模块（scheduler/、gateway/），增加系统复杂度
- 迁移期间需要保持新旧架构兼容
- 非标准任务（用户要求自由组合安全测试阶段）的灵活性降低

## 替代方案

1. **继续优化 prompt**：在不改架构的前提下缩短 orchestrator 提示词。被否决，因为根本问题是反应式循环本身，不是 prompt 过长。
2. **完全废弃 LLM 规划**：纯硬编码流水线。被否决，因为需要 LLM 处理非标准场景（用户指定跳过阶段、特殊目标类型等）。
3. **LangGraph / AutoGen 等外部框架**：被否决，因为现有 WorkflowRunner + SubagentManager 已覆盖核心能力，引入外部框架增加依赖和集成成本。
