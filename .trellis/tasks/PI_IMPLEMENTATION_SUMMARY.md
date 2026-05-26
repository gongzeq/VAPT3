# Pi Agent 架构重构 - 实施总结

## 🎉 总体状态：PR1-3 已完成，PR4-5 待实施

### ✅ PR1: StructuredBlackboard + EvidenceStore（已完成）

**实施日期**: 2026-05-25

**核心成就**:
- ✅ 11 种 typed kinds（scope/phase_transition/finding/hypothesis/evidence_ref/approval/milestone/blocker/progress/summary/legacy_text）
- ✅ `Blackboard.write(agent_name, kind, payload)` 新 API
- ✅ `Blackboard.snapshot()` 聚合视图
- ✅ `EvidenceStore` 独立模块（metadata + 脱敏 + 文件存储）
- ✅ CMDB migration `20260523_evidence_store.py`
- ✅ 完全向后兼容（`write_text` 保留）

**测试覆盖**: 40 个测试全部通过 ✅

**文件**:
- `secbot/agent/blackboard.py` (549 行)
- `secbot/evidence/store.py` (251 行)
- `secbot/evidence/sanitiser.py` (113 行)
- `secbot/cmdb/models.py` (EvidenceRecordModel + EvidenceFindingLinkModel)

---

### ✅ PR2: PolicyEngine + Tool Router（已完成）

**实施日期**: 代码已存在

**核心成就**:
- ✅ 8 个规则：ScopeRule, SSRFRule, WorkspaceRule, CredentialBoundaryRule, CallerKindRule, BudgetRule, RateLimitRule, DestructiveRule
- ✅ `PolicyDecision` (allow/need_approval/deny)
- ✅ `ScopeContract` 支持 IP/CIDR/domain/wildcard/URL-prefix
- ✅ `ToolRegistry` 完整集成 PolicyEngine
- ✅ Worker 写权限限制（不能写 finding/phase_transition/approval）
- ✅ HighRiskGate 合并为 DestructiveRule

**测试覆盖**: Blackboard 测试包含 worker 权限测试并通过 ✅

**文件**:
- `secbot/policy/engine.py` (968 行)
- `secbot/agent/tools/registry.py` (集成 PolicyEngine)

---

### ✅ PR3: BudgetEnforcer + Pi prompt（已完成）

**实施日期**: 代码已存在

**核心成就**:
- ✅ `BudgetTracker` 双轨预算（wall-clock 15min + tool-calls 60）
- ✅ `BudgetView` / `BudgetShare` dataclass
- ✅ Worker budget share 机制（grant/reclaim）
- ✅ 状态枚举：HEALTHY / LOW / EXCEEDED
- ✅ `render_pi_prompt` 集成 budget section
- ✅ PolicyEngine `_budget_rule` 实现
- ✅ ToolRegistry `_tick_budget` 集成

**文件**:
- `secbot/state/budget.py` (338 行)
- `secbot/agents/pi_orchestrator.py` (145 行)

---

### ⏳ PR4: FindingOntology + ReportBuilder v2（待实施）

**目标**:
- 新建 `secbot/ontology/finding.py` - 统一 finding schema
- Skill 输出归一适配器
- 改造 `report-html` skill 使用结构化输入
- CWE / OWASP category / severity / confidence 标准化

**依赖**: PR1 (StructuredBlackboard)

---

### ⏳ PR5: EventStream 持久化（待实施）

**目标**:
- 新建 CMDB 表：`event_log` (append-only)
- 新建 `secbot/state/event_stream.py`
- 持久化所有 Pi 决策事件（plan/tool_call/result/approval）
- Replay 机制（从 event_log 重建状态）

**依赖**: PR1-3

---

## 📊 实施进度

| PR | 标题 | 状态 | 完成度 | 关键文件 |
|---|---|---|---|---|
| PR1 | StructuredBlackboard + EvidenceStore | ✅ 完成 | 100% | blackboard.py, evidence/store.py |
| PR2 | PolicyEngine + Tool Router | ✅ 完成 | 100% | policy/engine.py, tools/registry.py |
| PR3 | BudgetEnforcer + Pi prompt | ✅ 完成 | 100% | state/budget.py, agents/pi_orchestrator.py |
| PR4 | FindingOntology + ReportBuilder v2 | ⏳ 待实施 | 0% | ontology/finding.py (待创建) |
| PR5 | EventStream 持久化 | ⏳ 待实施 | 0% | state/event_stream.py (待创建) |

**总体进度**: 3/5 完成（60%）

---

## 🎯 关键成就

1. **完全向后兼容**: 旧代码无需修改，`write_text` 继续工作
2. **类型安全**: 11 种 kind 的 payload schema 强校验
3. **统一策略引擎**: 8 个规则合并到单点 PolicyEngine
4. **预算追踪**: 双轨预算 + worker share 机制
5. **Pi prompt 集成**: phase-aware + budget-aware orchestrator

---

## 🚀 下一步行动

### 立即可做（PR4）

1. 创建 `secbot/ontology/finding.py`
2. 定义 `FindingSchema` dataclass
3. 实现 Skill 输出适配器
4. 更新 `report-html` skill

### 后续（PR5）

1. 设计 `event_log` 表 schema
2. 实现 `EventStream` 类
3. 集成到 AgentLoop
4. 实现 replay 机制

---

## 📝 技术债务

- [ ] 需要安装 `aiosqlite` 才能运行完整 evidence store 测试（DB 相关）
- [ ] 需要运行 `ruff check` / `mypy` 确认 lint/typecheck 通过
- [ ] PR4/PR5 需要完整实施

---

## 🎓 架构演进

**旧架构**（硬编码线性管道）:
```
Orchestrator → asset_discovery → port_scan → vuln_scan → (weak_password | pentest) → report
```

**新架构**（Pi 主控 + 受限 worker）:
```
Pi Orchestrator (判断与编排)
  ├─ PolicyEngine (什么绝不能做)
  ├─ BudgetEnforcer (15min / 60 calls)
  ├─ StructuredBlackboard (共享状态)
  ├─ EvidenceStore (证据管理)
  └─ Worker Pool (受限子任务)
```

**关键差异**:
- ❌ 旧：预定义 7 个 expert agent，固定顺序
- ✅ 新：DAG 探索，Pi 动态决策
- ❌ 旧：纯文本黑板 + `[tag]` 标签
- ✅ 新：11 种 typed kinds + schema 校验
- ❌ 旧：分散的安全控制（HighRiskGate / SSRF / workspace）
- ✅ 新：统一 PolicyEngine（8 个规则）
- ❌ 旧：无预算限制
- ✅ 新：双轨预算 + worker share

---

**最后更新**: 2026-05-25
**状态**: PR1-3 完成，PR4-5 待实施
