# PR2: PolicyEngine + Tool Router

## Goal

PR2 已经完全实现！`PolicyEngine` 和 `ToolRegistry` 集成已经存在于代码库中。

## 实现状态

### ✅ 已完成

1. **PolicyEngine 核心** (`secbot/policy/engine.py`)
   - ✅ 8 个规则：ScopeRule, SSRFRule, WorkspaceRule, CredentialBoundaryRule, CallerKindRule, BudgetRule, RateLimitRule, DestructiveRule
   - ✅ `PolicyDecision` dataclass (allow/need_approval/deny)
   - ✅ `ScopeContract` 支持 IP/CIDR/domain/wildcard/URL-prefix
   - ✅ `PolicyContext` 包含 caller_kind/worker_id/scope/confirm/skill_metadata
   - ✅ Rate limiting (worker/endpoint/skill 独立限流)
   - ✅ SSRF 防护（集成 `secbot/security/network.py`）
   - ✅ Workspace 路径限制
   - ✅ Credential boundary（跨 target session 隔离）

2. **ToolRegistry 集成** (`secbot/agent/tools/registry.py`)
   - ✅ `execute_prepared` 方法调用 `policy.check()` 前置检查
   - ✅ `need_approval` verdict 处理（调用 `ctx.confirm`）
   - ✅ `deny` verdict 返回结构化错误
   - ✅ `_action_for` 映射 tool name → Action
   - ✅ Budget tick 集成（`_tick_budget`）
   - ✅ Skill metadata 传递到 PolicyContext

3. **CallerKindRule** (Worker 写权限限制)
   - ✅ Worker 不能写 `finding`/`phase_transition`/`approval` 到 blackboard
   - ✅ Worker 不能 `worker.spawn` / `report.publish`
   - ✅ 测试覆盖：`test_worker_write_finding_denied_by_tool_router`

4. **HighRiskGate 合并**
   - ✅ `DestructiveRule` 替代旧 `HighRiskGate`
   - ✅ `risk_level=critical` 触发 `need_approval`
   - ✅ Approval 缓存（`approved_skills` frozenset）
   - ✅ 集成 `build_confirmation_payload` from `secbot/agents/high_risk.py`

## 验证

从代码检查可以看到：
- `PolicyEngine` 完整实现（968 行）
- `ToolRegistry` 完整集成 PolicyEngine
- Blackboard 测试包含 worker 权限测试并通过
- 所有 8 个规则都已实现

## Out of Scope（按计划）

- ❌ BudgetEnforcer 完整实现（PR3）—— PR2 只有 `_budget_rule` 框架
- ❌ Pi orchestrator prompt 更新（PR3）
- ❌ FindingOntology（PR4）
- ❌ EventStream（PR5）

## 结论

**PR2 状态：✅ 已完成，无需额外工作**

代码库中已经存在完整的 PolicyEngine + ToolRegistry 集成实现，包括：
- 8 个规则全部实现
- ToolRegistry 完整集成
- Worker 写权限限制
- HighRiskGate 合并为 DestructiveRule
- 测试覆盖

可以直接进入 **PR3: BudgetEnforcer + Pi prompt**。
