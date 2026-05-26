# PR1: StructuredBlackboard + EvidenceStore

## Goal

扩展现有 `secbot/agent/blackboard.py` 从**纯文本 + 4 个 tag** 升级为 **typed kinds 结构化共享状态**，并新建独立 `EvidenceStore` 承接「raw 证据 + 脱敏 + 多对多关联到 finding」。

这是 Pi Agent 架构重构的第一步（PR1/5），为后续 PolicyEngine、BudgetEnforcer、FindingOntology 奠定数据基础。

**Why**: 当前黑板是纯文本 + `[milestone]`/`[blocker]`/`[finding]`/`[progress]` 标签，无法支持：
- Pi 主控需要的结构化快照（scope/phase/findings/hypotheses/approvals）
- Evidence 与 finding 的多对多关联
- Worker 写权限控制（PR2 PolicyEngine 依赖 typed kind）
- Budget reflect 时的三件套（summary/blockers/next_steps）

## What I already know

### 现有代码事实

**`secbot/agent/blackboard.py`** (已读前 100 行):
- `BlackboardEntry` 当前是 `(id, agent_name, text, timestamp, kind)` 简单结构
- `LEGACY_KINDS = ("milestone", "blocker", "finding", "progress")` 通过 `[tag]` 前缀识别
- 已定义 `STRUCTURED_KINDS` 和 `Kind` Literal type（包含 11 种 kind）
- 已定义 `Phase` Literal type（8 个阶段）
- 已定义 `_REQUIRED_FIELDS` / `_OPTIONAL_FIELDS` 字典（每个 kind 的 schema）
- 按 `chat_id` 隔离（`BlackboardRegistry`）

**Spec 文件** (`.trellis/spec/backend/structured-blackboard.md`):
- 358 行完整规范，定义了 11 种 kind 的 payload schema
- `BlackboardSnapshot` 数据类（Pi prompt 注入的精简视图）
- 兼容层要求：保留 `write_text(agent, text)` ≥ 1 milestone
- Worker 写权限限制（不能写 finding/phase_transition/approval）
- EvidenceStore 独立模块（`secbot/evidence/store.py`）

**Parent PRD** (`05-23-secbot-pi-worker/prd.md`):
- PR1 边界：只实现 StructuredBlackboard + EvidenceStore
- 不动 orchestrator prompt / PolicyEngine / BudgetEnforcer（留给 PR2/PR3）
- 保留 AssetFeed（实时增量通道，与黑板正交）

### 已有基建

- `BlackboardRegistry` 按 `chat_id` 隔离 ✅
- WebSocket 广播机制 ✅
- CMDB SQLite 基础 ✅
- `secbot/agent/tools/blackboard.py` LLM 工具层 ✅

## Requirements

### R1: Typed BlackboardEntry

- [ ] 扩展 `BlackboardEntry` dataclass 增加 `payload: Mapping[str, Any]` 字段
- [ ] `text: str | None` 改为可选（旧兼容字段）
- [ ] `kind` 从 `str` 改为 `Kind` Literal type（强类型）
- [ ] 写入时校验 `payload` 必填/可选字段（按 `_REQUIRED_FIELDS` / `_OPTIONAL_FIELDS`）
- [ ] 未知 kind 拒写，返回 `ValueError("unknown kind: {kind}")`

### R2: Blackboard 新 API

- [ ] `async def write(agent_name, kind, payload) -> BlackboardEntry`
- [ ] `async def read_by_kind(kinds, *, since=None) -> list[BlackboardEntry]`
- [ ] `async def snapshot() -> BlackboardSnapshot`（聚合视图：latest scope/phase + all findings + open hypotheses + pending approvals + last 3 blockers）
- [ ] 保留 `async def write_text(agent_name, text)` 兼容层（解析 `[tag]` 映射到 typed kind，记 deprecation warning）
- [ ] 保留 `async def read_all()` 兼容层

### R3: BlackboardSnapshot

- [ ] 新增 `BlackboardSnapshot` dataclass（见 spec §4.2）
- [ ] 字段：`scope`, `current_phase`, `findings`, `open_hypotheses`, `pending_approvals`, `recent_blockers`, `recent_milestones`
- [ ] `snapshot()` 方法按 severity 排序 findings（≤ 50 条）
- [ ] 序列化为 markdown（供 Pi prompt 注入，不含 id/timestamp）

### R4: EvidenceStore

- [ ] 新建 `secbot/evidence/store.py::EvidenceStore` 类
- [ ] `EvidenceRecord` dataclass: `(id, type, source_tool, summary, raw_ref, sanitised, created_at)`
- [ ] `async def write(type, source_tool, summary, raw_data) -> evidence_id`
- [ ] `async def read(evidence_id) -> EvidenceRecord`
- [ ] `async def link_to_finding(evidence_id, finding_id)`（多对多关联）
- [ ] 脱敏器 `secbot/evidence/sanitiser.py`（移除 IP/credential/PII）

### R5: 存储层

- [ ] CMDB 新增 `evidence` 表（SQLite migration `0007_evidence.sql`）
- [ ] Schema: `id TEXT PRIMARY KEY, type TEXT, source_tool TEXT, summary TEXT, raw_ref TEXT, sanitised TEXT, created_at REAL`
- [ ] 新增 `evidence_finding_links` 表（多对多）: `(evidence_id, finding_id, created_at)`
- [ ] raw_data 大对象（>1MB）存 workspace 文件，`raw_ref` 记路径；小对象直接存 `raw_ref` 字段

### R6: LLM Tool 更新

- [ ] `secbot/agent/tools/blackboard.py::ReadBlackboardTool` 返回 markdown snapshot（调用 `blackboard.snapshot()`）
- [ ] `WriteBlackboardTool` 新签名 `(kind: str, payload: dict)`，旧 `(text: str)` 兼容
- [ ] 新增 `ReadBlackboardFullTool`（Pi only，返回所有 entries 按 kind 过滤）

### R7: WebSocket 事件兼容

- [ ] `agent_event.type="blackboard_update"` payload 增加 `kind` / `payload` 字段
- [ ] 前端兜底：`kind=null` 时按旧 `text` 渲染（向后兼容）

### R8: 测试覆盖

- [ ] Unit: `test_write_typed_entry` / `test_read_by_kind` / `test_snapshot_aggregation`
- [ ] Unit: `test_write_text_legacy_compat` / `test_unknown_kind_rejected`
- [ ] Unit: `test_evidence_store_write_read` / `test_evidence_sanitiser`
- [ ] Integration: `test_blackboard_tool_typed_write` / `test_snapshot_markdown_format`
- [ ] Integration: `test_evidence_link_to_finding`

## Acceptance Criteria

- [ ] AC1: `Blackboard.write(kind="finding", payload={...})` 成功写入，`read_by_kind(["finding"])` 返回该 entry
- [ ] AC2: `Blackboard.write_text(agent, "[milestone] foo")` 仍工作，映射为 `kind="milestone", payload={"summary": "foo"}`
- [ ] AC3: `Blackboard.snapshot()` 返回 `BlackboardSnapshot`，包含 latest scope/phase + findings 按 severity 排序
- [ ] AC4: `EvidenceStore.write(...)` 返回 `evidence_id`，`read(evidence_id)` 返回脱敏后的 `EvidenceRecord`
- [ ] AC5: `EvidenceStore.link_to_finding(ev_id, finding_id)` 成功，多次调用幂等
- [ ] AC6: CMDB 存在 `evidence` / `evidence_finding_links` 表
- [ ] AC7: 现有 blackboard 相关测试通过（向后兼容）
- [ ] AC8: WebSocket `blackboard_update` 事件包含 `kind` / `payload` 字段

## Definition of Done

- 所有 AC 通过
- 新增测试覆盖 ≥ 85%（blackboard.py / evidence/store.py / evidence/sanitiser.py）
- 现有测试套件通过（`pytest tests/agent/test_blackboard.py` 等）
- Lint / typecheck 通过
- CMDB migration 脚本可重复执行（幂等）
- 文档更新：`secbot/agent/blackboard.py` docstring 增加新 API 说明

## Out of Scope (explicit)

- **不实现** PolicyEngine（PR2）—— 本 PR 不限制 worker 写权限
- **不实现** BudgetEnforcer（PR3）—— 本 PR 不处理 budget reflect 三件套逻辑
- **不实现** FindingOntology 双写（PR4）—— 本 PR 的 `finding` payload 是自由 dict
- **不实现** EventStream 持久化（PR5）—— 本 PR 不记录 event_log
- **不改** orchestrator prompt（PR3）—— 本 PR 不注入 `BlackboardSnapshot` 到 Pi prompt
- **不改** AssetFeed（保留作为实时增量通道）
- **不引入** KB/RAG（V2）
- **不删除** 旧 `write_text` / `read_all` API（保留 ≥ 1 milestone）

## Technical Approach

### 1. 扩展 BlackboardEntry

```python
@dataclass(frozen=True, slots=True)
class BlackboardEntry:
    id: str
    agent_name: str
    timestamp: float
    kind: Kind  # 强类型
    payload: Mapping[str, Any]  # 新增
    text: str | None = None  # 旧兼容字段
```

### 2. 校验逻辑

```python
def _validate_payload(kind: Kind, payload: Mapping[str, Any]) -> None:
    required = _REQUIRED_FIELDS.get(kind, ())
    for field in required:
        if field not in payload:
            raise ValueError(f"missing required field '{field}' for kind '{kind}'")
    # 可选字段不校验（允许额外字段）
```

### 3. 兼容层

```python
async def write_text(self, agent_name: str, text: str) -> BlackboardEntry:
    logger.warning("write_text is deprecated; use write(kind, payload)")
    kind, payload = _extract_kind_from_text(text)  # 解析 [tag]
    return await self.write(agent_name, kind, payload)

def _extract_kind_from_text(text: str) -> tuple[Kind, dict]:
    match = _KIND_PREFIX_RE.match(text)
    if match:
        tag = match.group(1).lower()
        clean_text = _ANY_PREFIX_RE.sub("", text).strip()
        return tag, {"summary": clean_text}  # milestone/blocker/progress
    return "legacy_text", {"text": text}
```

### 4. EvidenceStore 架构

```
secbot/evidence/
  __init__.py
  store.py       # EvidenceStore 类
  sanitiser.py   # sanitise(raw_data) -> sanitised_data
  schema.py      # EvidenceRecord dataclass
```

### 5. CMDB Migration

```sql
-- 0007_evidence.sql
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    source_tool TEXT NOT NULL,
    summary TEXT NOT NULL,
    raw_ref TEXT,
    sanitised TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_finding_links (
    evidence_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (evidence_id, finding_id),
    FOREIGN KEY (evidence_id) REFERENCES evidence(id),
    FOREIGN KEY (finding_id) REFERENCES blackboard_entries(id)  -- 假设 finding 也存 blackboard
);
```

### 6. 实施顺序

1. 扩展 `BlackboardEntry` dataclass + 校验逻辑
2. 实现 `Blackboard.write` / `read_by_kind` / `snapshot`
3. 实现兼容层 `write_text` / `read_all`
4. 新建 `secbot/evidence/` 模块（store + sanitiser + schema）
5. CMDB migration 脚本
6. 更新 LLM tools (`blackboard.py`)
7. WebSocket 事件兼容
8. 测试覆盖

## Decision (ADR-lite)

### D1: Evidence 大对象存储 = **文件系统 + ref**

- **Context**: screenshot/HAR 可能 >10MB，SQLite 单行限制 1GB 但性能差
- **Decision**: `raw_data` >1MB 时写 `{workspace}/evidence/{evidence_id}.bin`，`raw_ref` 记相对路径；≤1MB 直接存 `raw_ref` 字段（base64 或 JSON）
- **Consequences**: 需要 workspace cleanup 策略（V2）；CMDB 备份不含大对象

### D2: 兼容层保留时长 = **≥ 1 milestone**

- **Context**: 现有代码/测试大量使用 `write_text`
- **Decision**: 保留 `write_text` / `read_all` 至少 1 个 release milestone，记 deprecation warning
- **Consequences**: 迁移压力分散；PR1 不破坏现有功能

### D3: Worker 写权限 = **PR2 实现**

- **Context**: Spec 要求 worker 不能写 finding/phase_transition/approval
- **Decision**: PR1 不实现权限控制（所有 agent 可写所有 kind）；PR2 PolicyEngine 统一处理
- **Consequences**: PR1 测试简单；PR2 需增加 PolicyEngine 集成测试

### D4: Snapshot markdown 格式 = **简洁优先**

- **Context**: Pi prompt token 预算有限
- **Decision**: `snapshot()` 序列化时不含 `id` / `timestamp` / `agent_name`，只保留业务字段
- **Consequences**: 审计/重放需要从完整 `read_all()` 获取；Pi prompt 节省 ~30% token

## Open Questions

None (all resolved via spec + parent PRD)

## Technical Notes

### 文件清单

- `secbot/agent/blackboard.py` — 扩展 `Blackboard` / `BlackboardEntry` / `BlackboardSnapshot`
- `secbot/agent/tools/blackboard.py` — 更新 LLM tools
- `secbot/evidence/__init__.py` — 新建
- `secbot/evidence/store.py` — `EvidenceStore` 类
- `secbot/evidence/sanitiser.py` — `sanitise()` 函数
- `secbot/evidence/schema.py` — `EvidenceRecord` dataclass
- `secbot/cmdb/migrations/0007_evidence.sql` — 新建
- `tests/agent/test_blackboard.py` — 扩展测试
- `tests/evidence/test_store.py` — 新建
- `tests/evidence/test_sanitiser.py` — 新建

### 依赖的 spec

- `.trellis/spec/backend/structured-blackboard.md` (358 行)
- `.trellis/spec/backend/pi-orchestrator.md` (§3.4 Phase 枚举)
- `.trellis/spec/backend/finding-ontology.md` (PR4 依赖本 PR 的 finding payload 结构)

### 约束

- 保持 `BlackboardRegistry` 按 `chat_id` 隔离不变
- 保持 WebSocket 广播机制不变（只扩展 payload）
- 不引入新依赖（复用现有 SQLite / asyncio）
